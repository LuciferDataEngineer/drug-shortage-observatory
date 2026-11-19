"""Bounded, credential-free acquisition of complete openFDA shortage snapshots.

Only content-addressed raw archives under ignored data/ contain original fields.
Public output must use the warehouse's explicit safe-field projection.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

MANIFEST_URL = "https://api.fda.gov/download.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 50_000
REQUEST_TIMEOUT = 15
ACQUISITION_SECONDS = 60


class SourceError(ValueError):
    """The source cannot be proven complete, consistent, or safely bounded."""


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise SourceError("Export date must use YYYY-MM-DD")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise SourceError("Invalid export date") from exc
    return value


def _allowed_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
        raise SourceError("Unexpected source URL")
    if url == MANIFEST_URL:
        return
    if (parsed.hostname != "download.open.fda.gov"
            or not parsed.path.startswith("/drug/shortages/")
            or not parsed.path.endswith(".json.zip")):
        raise SourceError("Archive must be an official FDA shortage download")


def _download(url, limit, deadline):
    _allowed_url(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError("Acquisition deadline exceeded")
    request = Request(url, headers={"User-Agent": "drug-shortage-observatory/1.0 (public-data research)"})
    try:
        with urlopen(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
            _allowed_url(response.url)
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise SourceError("Source exceeds bounded download size")
            chunks = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise SourceError("Acquisition deadline exceeded")
                # read1 performs at most one buffered/socket read, allowing the
                # wall-clock deadline to be checked even on a trickling source.
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise SourceError("Source exceeds bounded download size")
                chunks.append(chunk)
            return b"".join(chunks)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("Public FDA download failed; retry the complete snapshot") from exc


def _spec(payload):
    try:
        selected = json.loads(payload)["results"]["drug"]["shortages"]
        export_date = _date(selected["export_date"])
        total = selected["total_records"]
        partitions = selected["partitions"]
        if type(total) is not int or not 0 < total <= MAX_RECORDS:
            raise SourceError("Declared record count is invalid or exceeds bounds")
        if not isinstance(partitions, list) or len(partitions) != 1:
            raise SourceError("Expected one complete shortage partition; schema review required")
        partition = partitions[0]
        if type(partition["records"]) is not int or partition["records"] != total:
            raise SourceError("Partition count does not match complete export")
        source_url = partition["file"]
        _allowed_url(source_url)
        if source_url == MANIFEST_URL:
            raise SourceError("Partition must identify an archive")
        size = float(partition["size_mb"])
        if not math.isfinite(size) or not 0 < size <= MAX_ARCHIVE_BYTES / 1024 / 1024:
            raise SourceError("Declared archive size exceeds bounds")
        return {"export_date": export_date, "source_url": source_url,
                "records_declared": total, "size_mb": str(partition["size_mb"])}
    except SourceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("Unexpected FDA download manifest schema") from exc


def _rows(archive, export_date, expected):
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if len(members) != 1:
                raise SourceError("Expected exactly one JSON member")
            member = members[0]
            if (member.is_dir() or not member.filename.endswith(".json")
                    or Path(member.filename).name != member.filename
                    or member.file_size > MAX_EXPANDED_BYTES
                    or member.flag_bits & 1
                    or member.file_size > max(member.compress_size, 1) * 200):
                raise SourceError("Unsafe or oversized archive member")
            with bundle.open(member) as stream:
                payload = stream.read(MAX_EXPANDED_BYTES + 1)
            if len(payload) != member.file_size or len(payload) > MAX_EXPANDED_BYTES:
                raise SourceError("Expanded JSON size mismatch")
        document = json.loads(payload)
        rows = document["results"]
        meta = document["meta"]
        pagination = meta["results"]
        if (not isinstance(rows, list) or len(rows) != expected
                or any(not isinstance(row, dict) for row in rows)
                or meta["last_updated"] != export_date
                or pagination["skip"] != 0 or pagination["limit"] != expected
                or pagination["total"] != expected):
            raise SourceError("Archive is incomplete or differs from export metadata")
        return rows
    except SourceError:
        raise
    except (KeyError, TypeError, ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SourceError("Malformed FDA archive") from exc


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_snapshot(path):
    """Reopen a local acquisition manifest and verify its complete raw archive."""
    path = Path(path).resolve()
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise SourceError("Local manifest is oversized")
        envelope = json.loads(path.read_bytes())
        spec = envelope["source_manifest"]
        if _sha(_json_bytes(spec)) != envelope["source_manifest_sha256"]:
            raise SourceError("Local source manifest checksum mismatch")
        _date(envelope["export_date"])
        _allowed_url(envelope["source_url"])
        if (spec["export_date"] != envelope["export_date"]
                or spec["source_url"] != envelope["source_url"]
                or spec["records_declared"] != envelope["records_declared"]):
            raise SourceError("Local manifest metadata mismatch")
        count = envelope["records_declared"]
        size = envelope["raw_bytes"]
        if type(count) is not int or not 0 < count <= MAX_RECORDS:
            raise SourceError("Local record count exceeds bounds")
        if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
            raise SourceError("Local archive size exceeds bounds")
        raw_path = Path(envelope["raw_path"]).resolve()
        raw_root = path.parent.parent / "raw"
        if not raw_path.is_relative_to(raw_root.resolve()):
            raise SourceError("Raw archive must remain inside the snapshot data directory")
        if raw_path.stat().st_size != size:
            raise SourceError("Raw archive length mismatch")
        archive = raw_path.read_bytes()
        if _sha(archive) != envelope["raw_sha256"]:
            raise SourceError("Raw archive checksum mismatch")
        rows = _rows(archive, envelope["export_date"], count)
        return {**envelope, "manifest_path": str(path), "rows": rows}
    except SourceError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise SourceError("Cannot verify local snapshot manifest") from exc


def fetch_snapshot(data_dir):
    """Fetch one complete export with a manifest consistency check around the GET.

    No pagination, API keys, accounts, or paid service calls. Every acquisition
    reacquires the archive: upstream byte corrections can leave the manifest's
    date, count and rounded size unchanged. Explicit read_snapshot() is offline.
    Existing identical raw content is rehashed before storage reuse.
    FDA does not publish a signed archive checksum: local SHA-256 establishes
    local integrity and reproducibility, not independent authenticity.
    """
    data_dir = Path(data_dir).resolve()
    deadline = time.monotonic() + ACQUISITION_SECONDS
    before = _spec(_download(MANIFEST_URL, MAX_MANIFEST_BYTES, deadline))
    identity = _sha(_json_bytes(before))
    archive = _download(before["source_url"], MAX_ARCHIVE_BYTES, deadline)
    rows = _rows(archive, before["export_date"], before["records_declared"])
    after = _spec(_download(MANIFEST_URL, MAX_MANIFEST_BYTES, deadline))
    if before != after:
        raise SourceError("FDA manifest changed during acquisition; retry entire snapshot")
    digest = _sha(archive)
    raw_path = data_dir / "raw" / f"{digest}.zip"
    if raw_path.exists():
        if raw_path.stat().st_size != len(archive) or _sha(raw_path.read_bytes()) != digest:
            raise SourceError("Existing content-addressed archive is corrupt")
    else:
        _atomic_write(raw_path, archive)
    accessed_at = _utc_now()
    stamp = accessed_at.replace(":", "").replace("-", "").replace(".", "")
    manifest_path = data_dir / "manifests" / f"{before['export_date']}-{digest[:16]}-{stamp}-{uuid.uuid4().hex[:8]}.json"
    envelope = {"source_url": before["source_url"], "accessed_at": accessed_at,
                "export_date": before["export_date"], "raw_sha256": digest,
                "raw_bytes": len(archive), "raw_path": str(raw_path),
                "records_declared": before["records_declared"],
                "source_manifest": before, "source_manifest_sha256": identity}
    _atomic_write(manifest_path, json.dumps(envelope, indent=2).encode() + b"\n")
    return {**envelope, "manifest_path": str(manifest_path), "rows": rows}
