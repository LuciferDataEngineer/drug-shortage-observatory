"""Transactional FDA listing snapshots with bounded public projections and provenance."""
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3

LOGGER = logging.getLogger(__name__)
STATUSES = {"Current", "Resolved", "To Be Discontinued"}
TEXT_FIELDS = (
    "generic_name", "company_name", "presentation", "package_ndc",
    "dosage_form", "status", "availability", "shortage_reason",
)
DATE_FIELDS = ("initial_posting_date", "update_date", "discontinued_date")
PROJECTED_FIELDS = (*TEXT_FIELDS, *DATE_FIELDS)
NATURAL_FIELDS = ("generic_name", "company_name", "presentation", "package_ndc")


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def connect(path):
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript((Path(__file__).parent / "sql/schema.sql").read_text())
    return db


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def iso_date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be an ISO date")
    return date.fromisoformat(value).isoformat()


def accessed_at(value):
    if not isinstance(value, str):
        raise ValueError("accessed_at must be a timezone-aware ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("accessed_at needs a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def source_date(value, field):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value):
        raise ValueError(f"invalid {field} format")
    month, day, year = map(int, value.split("/"))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise ValueError(f"invalid {field} calendar date") from None


def project(row):
    if not isinstance(row, dict):
        raise ValueError("record must be an object")
    result = {}
    for field in TEXT_FIELDS:
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        result[field] = value if value and value.strip() else None
    if result["generic_name"] is None:
        raise ValueError("generic_name is required")
    if result["status"] not in STATUSES:
        raise ValueError("status is outside the supported source vocabulary")
    for field in DATE_FIELDS:
        result[field] = source_date(row.get(field), field)
    cats = row.get("therapeutic_category", [])
    if not isinstance(cats, list) or any(not isinstance(x, str) or not x.strip() for x in cats):
        raise ValueError("therapeutic_category must be a list of non-empty strings")
    result["therapeutic_category"] = sorted(set(cats))
    return result


def validate_envelope(envelope):
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    declared = envelope.get("records_declared")
    if type(declared) is not int or declared != len(rows):
        raise ValueError("declared record count differs from observed rows")
    raw_bytes = envelope.get("raw_bytes")
    if type(raw_bytes) is not int or raw_bytes <= 0:
        raise ValueError("raw_bytes must be positive")
    raw_hash = envelope.get("raw_sha256")
    if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("raw_sha256 must be a lowercase SHA-256")
    for field in ("source_url", "raw_path"):
        if not isinstance(envelope.get(field), str) or not envelope[field].strip():
            raise ValueError(f"{field} is required")
    return iso_date(envelope["export_date"], "export_date"), accessed_at(envelope["accessed_at"])


def load_snapshot(db, envelope):
    export_date, access = validate_envelope(envelope)
    hashes = [digest(row) for row in envelope["rows"]]
    snapshot_id = digest({"export_date": export_date, "row_hashes": sorted(hashes)})
    observation = {
        "snapshot_id": snapshot_id, "source_url": envelope["source_url"],
        "accessed_at": access, "raw_sha256": envelope["raw_sha256"],
        "raw_bytes": envelope["raw_bytes"], "raw_path": envelope["raw_path"],
    }
    observation_id = digest(observation)
    with transaction(db):
        existing = db.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if existing is None:
            accepted, rejected = [], []
            for ordinal, (raw, raw_hash) in enumerate(zip(envelope["rows"], hashes), 1):
                try:
                    doc = project(raw)
                except ValueError as error:
                    rejected.append((snapshot_id, ordinal, raw_hash, str(error)))
                    continue
                accepted.append((ordinal, raw_hash, doc))
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                       (snapshot_id, export_date, len(hashes), len(accepted), len(rejected)))
            for ordinal, raw_hash, doc in accepted:
                key = digest([doc[field] for field in NATURAL_FIELDS])
                db.execute(
                    "INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (snapshot_id, ordinal, raw_hash, digest(doc), key, *(doc[field] for field in PROJECTED_FIELDS)),
                )
                db.executemany("INSERT INTO categories VALUES (?,?,?)",
                               [(snapshot_id, ordinal, name) for name in doc["therapeutic_category"]])
            db.executemany("INSERT INTO quarantine VALUES (?,?,?,?)", rejected)
        db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                   (observation_id, *observation.values()))
        db.executemany(
            "INSERT OR IGNORE INTO observation_rows VALUES (?,?,?)",
            [(observation_id, ordinal, raw_hash) for ordinal, raw_hash in enumerate(hashes, 1)],
        )
        stored = db.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        report = dict(stored)
        report.update(observation_id=observation_id, idempotent=existing is not None)
        counts = db.execute(
            """SELECT (SELECT COUNT(*) FROM listings WHERE snapshot_id=?),
                      (SELECT COUNT(*) FROM quarantine WHERE snapshot_id=?),
                      (SELECT COUNT(*) FROM observation_rows WHERE observation_id=?)""",
            (snapshot_id, snapshot_id, observation_id),
        ).fetchone()
        if tuple(counts) != (stored["accepted"], stored["quarantined"], stored["raw_rows"]):
            raise ValueError("snapshot row conservation failed")
    LOGGER.info("snapshot %s rows=%s accepted=%s quarantined=%s idempotent=%s",
                snapshot_id, report["raw_rows"], report["accepted"], report["quarantined"], report["idempotent"])
    return report


def compare_snapshots(db, before, after):
    """Compare complete projected-row multisets; missing rows have no inferred status."""
    def counts(snapshot_id):
        if db.execute("SELECT 1 FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone() is None:
            raise ValueError("unknown comparison snapshot")
        return Counter(dict(db.execute(
            "SELECT projected_sha256,COUNT(*) FROM listings WHERE snapshot_id=? GROUP BY projected_sha256",
            (snapshot_id,),
        )))
    previous, current = counts(before), counts(after)
    return {
        "before_snapshot_id": before, "after_snapshot_id": after,
        "added": sum((current - previous).values()),
        "removed": sum((previous - current).values()),
        "unchanged": sum((current & previous).values()),
    }
