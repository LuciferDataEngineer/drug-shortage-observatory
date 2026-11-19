"""Independent aggregate oracles and transactional report publication tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import csv
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from unittest.mock import patch

import reports
import warehouse


def row(**changes):
    result = {
        "generic_name": "Synthetic A", "company_name": "Maker A",
        "presentation": "10 mg tablet", "package_ndc": "11111-1111-11",
        "dosage_form": "Tablet", "status": "Current", "availability": "Available",
        "shortage_reason": "Synthetic reason", "initial_posting_date": "01/01/2026",
        "update_date": "11/18/2026", "therapeutic_category": ["Alpha", "Beta", "Alpha"],
        "contact_info": "synthetic-private-contact", "openfda": {"private": "unpublished"},
    }
    result.update(changes)
    return result


def envelope(rows, export_date="2026-11-18"):
    return {
        "rows": rows, "records_declared": len(rows), "export_date": export_date,
        "accessed_at": "2026-11-19T00:00:00Z", "source_url": "https://example.invalid/synthetic.zip",
        "raw_sha256": warehouse.digest(rows), "raw_bytes": len(warehouse.canonical(rows).encode()),
        "raw_path": "data/raw/synthetic.zip",
    }


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = warehouse.connect(self.root / "analysis.sqlite")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def load_report(self, rows):
        warehouse.load_snapshot(self.db, envelope(rows))
        return reports.analyze(self.db)

    def test_status_category_overlap_and_duplicate_denominators(self):
        rejected = row(status="Unrecognized")
        value = self.load_report([
            row(), row(), row(contact_info="a-different-private-contact"),
            row(status="Resolved", therapeutic_category=["Resolved only"]),
            row(generic_name="Synthetic B", company_name="Maker B", package_ndc="22222-2222-22",
                availability="Unvailable", dosage_form=None, therapeutic_category=["Beta"]),
            row(generic_name="Synthetic C", status="To Be Discontinued", package_ndc="33333-3333-33",
                availability=None, shortage_reason=None, therapeutic_category=["Other"]),
            rejected, deepcopy(rejected),
        ])
        self.assertEqual((value["raw_rows"], value["accepted_rows"], value["quarantined_rows"]), (8, 6, 2))
        statuses = {r["status"]: r for r in value["tables"]["status_summary"]}
        self.assertEqual(statuses["Current"], {
            "status": "Current", "listing_rows": 4, "generic_labels": 2, "company_labels": 2,
        })
        self.assertEqual(statuses["Resolved"]["listing_rows"], 1)
        self.assertEqual(statuses["To Be Discontinued"]["listing_rows"], 1)
        categories = {r["category"]: (r["current_listing_rows"], r["current_generic_labels"])
                      for r in value["tables"]["categories"]}
        self.assertEqual(categories, {"Alpha": (3, 1), "Beta": (4, 2)})
        # Memberships overlap, while each category counts one membership per source row.
        self.assertGreater(sum(n for n, _ in categories.values()), statuses["Current"]["listing_rows"])
        quality = {r["metric"]: r["value"] for r in value["tables"]["quality"]}
        self.assertEqual(quality, {
            "raw_rows": 8, "accepted_rows": 6, "quarantined_rows": 2,
            "repeated_natural_key_groups": 1, "extra_rows_at_repeated_natural_keys": 3,
            "exact_raw_duplicate_extra_rows": 2, "projected_duplicate_extra_rows": 2,
            "generic_labels_with_multiple_statuses": 1, "unknown_availability_rows": 1,
            "missing_dosage_form_rows": 1, "missing_shortage_reason_rows": 1,
        })
        self.assertEqual(sum(r["listing_rows"] for r in value["tables"]["availability"]), 6)

    def test_literal_missing_label_remains_distinct_from_absent_availability(self):
        value = self.load_report([
            row(availability=None), row(availability="Not reported"),
            row(status="Resolved", availability="Available"),
        ])
        actual = {(r["status"], r["availability"], r["availability_reported"]): r["listing_rows"]
                  for r in value["tables"]["availability"]}
        self.assertEqual(actual, {
            ("Current", "Not reported", 0): 1,
            ("Current", "Not reported", 1): 1,
            ("Resolved", "Available", 1): 1,
        })

    def test_recency_boundaries_are_relative_to_export_with_explicit_missing_and_future(self):
        export_day = date(2026, 11, 18)
        rows = [row(package_ndc=str(age), update_date=(export_day - timedelta(days=age)).strftime("%m/%d/%Y"))
                for age in (0, 7, 8, 30, 31, 90, 91, -1)]
        rows.extend([row(update_date=None), row(status="Resolved", update_date="11/18/2026")])
        value = self.load_report(rows)
        actual = {(r["status"], r["update_age"]): r["listing_rows"] for r in value["tables"]["recency"]}
        self.assertEqual(actual, {
            ("Current", "0-7 days"): 2, ("Current", "8-30 days"): 2,
            ("Current", "31-90 days"): 2, ("Current", "91+ days"): 1,
            ("Current", "After export date"): 1, ("Current", "Missing date"): 1,
            ("Resolved", "0-7 days"): 1,
        })
        self.assertEqual(sum(actual.values()), value["accepted_rows"])

    def test_analysis_reader_snapshot_is_consistent_during_new_load(self):
        old = warehouse.load_snapshot(self.db, envelope([row(), row()]))
        other = warehouse.connect(self.root / "analysis.sqlite")
        invoked, failures = [], []
        def concurrent_load(sql):
            if "COUNT(DISTINCT company_name)" in sql and not invoked:
                invoked.append(True)
                try:
                    warehouse.load_snapshot(other, envelope([row(status="Resolved")], "2026-11-19"))
                except BaseException as error:
                    failures.append(error)
        try:
            self.db.set_trace_callback(concurrent_load)
            value = reports.analyze(self.db)
        finally:
            self.db.set_trace_callback(None)
            other.close()
        self.assertEqual(failures, [])
        self.assertEqual(invoked, [True])
        self.assertEqual(value["snapshot_id"], old["snapshot_id"])
        self.assertEqual(value["tables"]["status_summary"][0]["status"], "Current")
        self.assertEqual(value["accepted_rows"], 2)
        self.assertEqual(sum(r["listing_rows"] for r in value["tables"]["availability"]), 2)
        self.assertEqual(reports.analyze(self.db)["export_date"], "2026-11-19")

    def test_empty_warehouse_failure_releases_reader_transaction(self):
        with self.assertRaisesRegex(ValueError, "Load a snapshot"):
            reports.analyze(self.db)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.load_report([row()])["accepted_rows"], 1)

    def test_exports_keep_observed_identity_and_only_aggregates(self):
        value = self.load_report([row(), row(status="Resolved")])
        destination = self.root / "exports" / "snapshot"
        reports.export_report(value, destination)
        self.assertEqual(json.loads((destination / "summary.json").read_text()), value)
        markdown = (destination / "report.md").read_text()
        self.assertIn(value["snapshot_id"], markdown)
        self.assertIn(value["raw_sha256"], markdown)
        self.assertIn(value["export_date"], markdown)
        for name in reports.QUERIES:
            with (destination / (name + ".csv")).open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), len(value["tables"][name]))
        combined = "\n".join(p.read_text() for p in destination.iterdir())
        for private in ("synthetic-private-contact", "contact_info", "openfda", "unpublished"):
            self.assertNotIn(private, combined)

    def test_actual_demo_and_monitor_reanalysis_are_explicitly_synthetic(self):
        from demo import run_demo
        demo_path = self.root / "synthetic-demo"
        run_demo(demo_path)
        replay_path = demo_path / "reanalysis"
        outcome = subprocess.run(
            [sys.executable, str(Path(reports.__file__).parent / "monitor.py"), "analyze",
             "--db", str(demo_path / "demo.sqlite"), "--output", str(replay_path)],
            check=True, capture_output=True, text=True,
        )
        cli_report = json.loads(outcome.stdout)
        self.assertEqual(cli_report["provenance"], "synthetic_fixture")
        self.assertIn("SYNTHETIC", cli_report["coverage"])
        for folder in (demo_path / "before", demo_path / "after", replay_path):
            with self.subTest(folder=folder.name):
                document = json.loads((folder / "summary.json").read_text())
                self.assertEqual(document["source_url"], "https://example.invalid/synthetic-teaching-fixture")
                self.assertEqual(document["provenance"], "synthetic_fixture")
                self.assertIn("SYNTHETIC", document["coverage"])
                markdown = (folder / "report.md").read_text()
                self.assertIn("# SYNTHETIC shortage snapshot analysis", markdown)
                self.assertIn("SYNTHETIC teaching fixtures", markdown)
                self.assertNotIn("FDA bulk export", markdown)

    def test_only_official_archive_provenance_uses_fda_bulk_label(self):
        urls = {
            "https://download.open.fda.gov/drug/shortages/drug-shortages-0001-of-0001.json.zip": "official_fda_bulk",
            "https://download.open.fda.gov.example.invalid/drug/shortages/file.json.zip": "synthetic_fixture",
            "https://download.open.fda.gov.evil.test/drug/shortages/file.json.zip": "custom_unverified",
            "https://download.open.fda.gov/drug/other/file.json.zip": "custom_unverified",
            "http://download.open.fda.gov/drug/shortages/file.json.zip": "custom_unverified",
            "https://another-source.test/export.json.zip": "custom_unverified",
        }
        for number, (url, expected) in enumerate(urls.items()):
            with self.subTest(url=url):
                batch = envelope([row()])
                batch["source_url"] = url
                batch["accessed_at"] = f"2026-11-19T00:00:{number:02d}Z"
                warehouse.load_snapshot(self.db, batch)
                value = reports.analyze(self.db)
                self.assertEqual(value["provenance"], expected)
                self.assertEqual(value["source_url"], url)
                destination = self.root / f"provenance-{number}"
                reports.export_report(value, destination)
                markdown = (destination / "report.md").read_text()
                self.assertEqual("FDA bulk export" in markdown, expected == "official_fda_bulk")
                self.assertEqual(value["accepted_rows"], 1)
                if expected == "custom_unverified":
                    self.assertIn("CUSTOM / UNVERIFIED", value["coverage"])
                    self.assertIn("# CUSTOM / UNVERIFIED", markdown)

    def test_writer_failure_publishes_nothing_and_cleans_staging(self):
        value = self.load_report([row()])
        parent = self.root / "exports"
        destination = parent / "snapshot"
        with patch("reports.csv.DictWriter.writerows", side_effect=OSError("injected disk fault")):
            with self.assertRaisesRegex(OSError, "injected disk fault"):
                reports.export_report(value, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(parent.iterdir()), [])
        reports.export_report(value, destination)
        self.assertTrue((destination / "summary.json").is_file())

    def test_existing_empty_nonempty_or_dangling_output_is_never_replaced(self):
        value = self.load_report([row()])
        for name in ("empty", "nonempty"):
            destination = self.root / name
            destination.mkdir()
            if name == "nonempty":
                (destination / "previous.txt").write_text("preserve this")
            with self.assertRaisesRegex(ValueError, "exists"):
                reports.export_report(value, destination)
            self.assertEqual(sorted(p.name for p in destination.iterdir()), [] if name == "empty" else ["previous.txt"])
        self.assertEqual((self.root / "nonempty" / "previous.txt").read_text(), "preserve this")
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(ValueError, "exists"):
            reports.export_report(value, dangling)
        self.assertTrue(dangling.is_symlink())

    def test_concurrent_exporters_publish_one_complete_report(self):
        value = self.load_report([row()])
        destination = self.root / "exports" / "snapshot"
        barrier = threading.Barrier(2)
        def export():
            barrier.wait(timeout=5)
            try:
                reports.export_report(value, destination)
                return "published"
            except ValueError:
                return "exists"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: export(), range(2)))
        self.assertEqual(sorted(outcomes), ["exists", "published"])
        self.assertEqual(json.loads((destination / "summary.json").read_text()), value)
        self.assertEqual(sorted(p.name for p in destination.parent.iterdir()), ["snapshot"])


if __name__ == "__main__":
    unittest.main()
