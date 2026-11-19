"""Deterministic acquisition-integrity tests; no external requests."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import source


def manifest(*, export="2026-11-18", count=2, url=None):
    return json.dumps({"results": {"drug": {"shortages": {
        "export_date": export, "total_records": count,
        "partitions": [{"file": url or "https://download.open.fda.gov/drug/shortages/example.json.zip",
                        "records": count, "size_mb": "0.01"}],
    }}}}).encode()


def archive(*, export="2026-11-18", count=2, rows=None, member="fixture.json"):
    # Original synthetic records: no patient data, contacts, or real manufacturers.
    rows = rows if rows is not None else [{
        "package_ndc": "00000-0000-00", "generic_name": "Synthetic Example",
        "company_name": "Synthetic Manufacturer", "presentation": "Synthetic presentation",
        "status": "Current", "availability": "Available",
        "initial_posting_date": "11/01/2026", "update_date": "11/18/2026",
        "therapeutic_category": ["Synthetic"], "update_type": "New",
    }] * 2
    document = {"meta": {"last_updated": export,
                         "results": {"skip": 0, "limit": count, "total": count}},
                "results": rows}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        info = zipfile.ZipInfo(member, date_time=(2026, 11, 18, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, json.dumps(document))
    return stream.getvalue()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fetch(self):
        with patch("source._download", side_effect=[manifest(), archive(), manifest()]):
            return source.fetch_snapshot(self.root)

    def test_complete_archive_is_reproducible_and_retains_source_duplicates(self):
        result = self.fetch()
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0], result["rows"][1])
        saved = json.loads(Path(result["manifest_path"]).read_text())
        self.assertNotIn("rows", saved)
        self.assertEqual(source.read_snapshot(result["manifest_path"]), result)

    def test_identical_content_reuses_raw_archive_but_keeps_each_acquisition(self):
        first = self.fetch()
        with patch("source._download", side_effect=[manifest(), archive(), manifest()]) as fetch:
            cached = source.fetch_snapshot(self.root)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(first["raw_sha256"], cached["raw_sha256"])
        self.assertEqual(first["raw_path"], cached["raw_path"])
        self.assertNotEqual(first["manifest_path"], cached["manifest_path"])
        self.assertEqual(len(list((self.root / "manifests").glob("*.json"))), 2)

    def test_same_manifest_with_corrected_archive_preserves_both_versions(self):
        first = self.fetch()
        corrected = [dict(row, availability="Limited Availability") for row in first["rows"]]
        with patch("source._download", side_effect=[manifest(), archive(rows=corrected), manifest()]):
            second = source.fetch_snapshot(self.root)
        self.assertNotEqual(first["raw_sha256"], second["raw_sha256"])
        self.assertEqual(first["export_date"], second["export_date"])
        self.assertEqual(len(list((self.root / "raw").glob("*.zip"))), 2)
        self.assertEqual(len(list((self.root / "manifests").glob("*.json"))), 2)
        self.assertEqual(source.read_snapshot(first["manifest_path"])["rows"], first["rows"])

    def test_tampered_cache_is_rejected_without_silent_replacement(self):
        result = self.fetch()
        path = Path(result["raw_path"])
        payload = bytearray(path.read_bytes())
        payload[len(payload) // 2] ^= 1
        path.write_bytes(payload)
        with patch("source._download", side_effect=[manifest(), archive(), manifest()]):
            with self.assertRaisesRegex(source.SourceError, "corrupt"):
                source.fetch_snapshot(self.root)

    def test_truncated_archive_is_rejected(self):
        result = self.fetch()
        path = Path(result["raw_path"])
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(source.SourceError, "length"):
            source.read_snapshot(result["manifest_path"])

    def test_manifest_drift_persists_no_accepted_snapshot(self):
        with patch("source._download", side_effect=[manifest(), archive(), manifest(export="2026-11-19")]):
            with self.assertRaisesRegex(source.SourceError, "changed"):
                source.fetch_snapshot(self.root)
        self.assertFalse(list(self.root.rglob("*.json")))
        self.assertFalse(list(self.root.rglob("*.zip")))

    def test_incomplete_export_is_rejected(self):
        with patch("source._download", side_effect=[manifest(), archive(rows=[{}])]):
            with self.assertRaisesRegex(source.SourceError, "incomplete"):
                source.fetch_snapshot(self.root)

    def test_archive_export_date_must_match_manifest(self):
        with patch("source._download", side_effect=[manifest(), archive(export="2026-11-17")]):
            with self.assertRaisesRegex(source.SourceError, "incomplete"):
                source.fetch_snapshot(self.root)

    def test_partition_drift_requires_deliberate_adapter_update(self):
        data = json.loads(manifest())
        data["results"]["drug"]["shortages"]["partitions"] *= 2
        with self.assertRaisesRegex(source.SourceError, "one complete"):
            source._spec(json.dumps(data).encode())

    def test_untrusted_archive_host_is_rejected(self):
        with self.assertRaisesRegex(source.SourceError, "official FDA"):
            source._spec(manifest(url="https://example.org/drug/shortages/x.json.zip"))

    def test_archive_path_traversal_is_rejected_without_extraction(self):
        with self.assertRaisesRegex(source.SourceError, "Unsafe"):
            source._rows(archive(member="../fixture.json"), "2026-11-18", 2)

    def test_expansion_limit_is_enforced_before_reading_json(self):
        with patch("source.MAX_EXPANDED_BYTES", 10):
            with self.assertRaisesRegex(source.SourceError, "oversized"):
                source._rows(archive(), "2026-11-18", 2)

    def test_manifest_cannot_point_outside_local_data_directory(self):
        result = self.fetch()
        path = Path(result["manifest_path"])
        data = json.loads(path.read_text())
        data["raw_path"] = str(self.root.parent / "unrelated.zip")
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(source.SourceError, "inside"):
            source.read_snapshot(path)

    def test_remote_size_budget_is_enforced(self):
        class Response(io.BytesIO):
            url = source.MANIFEST_URL
            headers = {"Content-Length": "100"}
        with patch("source.urlopen", return_value=Response(b"a" * 100)):
            with self.assertRaisesRegex(source.SourceError, "bounded"):
                source._download(source.MANIFEST_URL, 10, source.time.monotonic() + 2)

    def test_missing_content_length_cannot_bypass_byte_limit(self):
        class Response(io.BytesIO):
            url = source.MANIFEST_URL
            headers = {}
        with patch("source.urlopen", return_value=Response(b"a" * 100)):
            with self.assertRaisesRegex(source.SourceError, "bounded"):
                source._download(source.MANIFEST_URL, 10, source.time.monotonic() + 2)

    def test_declared_zero_or_huge_count_is_rejected(self):
        for count in (0, 50_001, True):
            with self.subTest(count=count), self.assertRaises(source.SourceError):
                source._spec(manifest(count=count))


if __name__ == "__main__":
    unittest.main()
