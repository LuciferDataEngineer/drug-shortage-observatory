from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import warehouse


def listing(**changes):
    record = {
        "generic_name": "Example medicine", "company_name": "Example manufacturer",
        "presentation": "10 mg tablet", "package_ndc": "12345-6789-01",
        "dosage_form": "Tablet", "status": "Current", "availability": "Available",
        "shortage_reason": "Synthetic fixture", "initial_posting_date": "01/02/2026",
        "update_date": "11/15/2026", "therapeutic_category": ["Example category"],
        "contact_info": "synthetic-contact@example.invalid",
        "related_info": "synthetic-private-note",
        "openfda": {"contact": "synthetic-internal-note"},
    }
    record.update(changes)
    return record


def envelope(rows, day="2026-11-18", at="2026-11-19T01:00:00Z"):
    return {
        "rows": rows, "records_declared": len(rows), "source_url": "https://example.invalid/export.zip",
        "export_date": day, "accessed_at": at, "raw_sha256": warehouse.digest(rows),
        "raw_bytes": len(warehouse.canonical(rows).encode()), "raw_path": "data/raw/synthetic.zip",
    }


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite"
        self.db = warehouse.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_duplicate_rows_conserved_with_auditable_ordinals(self):
        report = warehouse.load_snapshot(self.db, envelope([listing(), listing()]))
        self.assertEqual((report["raw_rows"], report["accepted"], report["quarantined"]), (2, 2, 0))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM categories").fetchone()[0], 2)
        result = self.db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT projected_sha256),COUNT(DISTINCT natural_key) FROM listings"
        ).fetchone()
        self.assertEqual(tuple(result), (2, 1, 1))
        self.assertEqual([r[0] for r in self.db.execute("SELECT ordinal FROM listings ORDER BY ordinal")], [1, 2])

    def test_identical_retry_and_reordered_acquisition_preserve_snapshot(self):
        a, b = listing(), listing(package_ndc="54321-9876-01")
        first = warehouse.load_snapshot(self.db, envelope([a, b, a]))
        same = warehouse.load_snapshot(self.db, envelope([a, b, a]))
        changed_order = warehouse.load_snapshot(self.db, envelope([a, a, b], at="2026-11-19T02:00:00Z"))
        self.assertFalse(first["idempotent"])
        self.assertTrue(same["idempotent"])
        self.assertTrue(changed_order["idempotent"])
        self.assertEqual(first["snapshot_id"], changed_order["snapshot_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 3)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
        mapped = list(self.db.execute(
            "SELECT raw_row_sha256 FROM observation_rows WHERE observation_id=? ORDER BY ordinal",
            (changed_order["observation_id"],),
        ))
        self.assertEqual([r[0] for r in mapped], list(map(warehouse.digest, [a, a, b])))

    def test_quarantine_strict_fields_dates_and_statuses(self):
        rows = [
            listing(), listing(generic_name=""), listing(status="Unknown"),
            listing(update_date="02/30/2026"), listing(initial_posting_date="2026-01-02"),
            listing(discontinued_date="2/29/2025"), listing(company_name=["bad"]),
            listing(therapeutic_category="bad"), "not an object",
            listing(package_ndc={"bad": 1}), listing(update_date=True),
        ]
        result = warehouse.load_snapshot(self.db, envelope(rows))
        self.assertEqual((result["accepted"], result["quarantined"]), (1, 10))
        self.assertEqual(result["raw_rows"], len(rows))
        self.assertEqual(self.db.execute("SELECT update_date FROM listings").fetchone()[0], "2026-11-15")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observation_rows").fetchone()[0], len(rows))

    def test_no_sensitive_payload_is_stored_and_raw_availability_is_preserved(self):
        row = listing(availability="Unvailable", therapeutic_category=["B", "A", "A"])
        warehouse.load_snapshot(self.db, envelope([row]))
        all_sql = "\n".join(self.db.iterdump())
        for private in ("synthetic-contact", "synthetic-private-note", "synthetic-internal-note", "contact_info", "openfda"):
            self.assertNotIn(private, all_sql)
        self.assertEqual(self.db.execute("SELECT availability FROM listings").fetchone()[0], "Unvailable")
        self.assertEqual([r[0] for r in self.db.execute("SELECT category FROM categories ORDER BY category")], ["A", "B"])

    def test_failed_transaction_leaves_no_partial_snapshot(self):
        self.db.execute(
            """CREATE TRIGGER fail_observation BEFORE INSERT ON observations
               BEGIN SELECT RAISE(ABORT,'injected storage fault'); END"""
        )
        with self.assertRaisesRegex(Exception, "injected storage fault"):
            warehouse.load_snapshot(self.db, envelope([listing(), listing(status="invalid")]))
        for table in ("snapshots", "listings", "categories", "quarantine", "observations", "observation_rows"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.db.execute("DROP TRIGGER fail_observation")
        self.assertEqual(warehouse.load_snapshot(self.db, envelope([listing()]))["accepted"], 1)

    def test_old_export_cannot_replace_current_and_latest_access_breaks_same_date_tie(self):
        newer = warehouse.load_snapshot(self.db, envelope([listing()]))
        warehouse.load_snapshot(self.db, envelope([listing(status="Resolved")], day="2026-11-17", at="2026-11-20T00:00:00Z"))
        self.assertEqual(self.db.execute("SELECT snapshot_id FROM current_snapshot").fetchone()[0], newer["snapshot_id"])
        correction = warehouse.load_snapshot(self.db, envelope([listing(availability="Limited Availability")], at="2026-11-19T02:00:00Z"))
        self.assertEqual(self.db.execute("SELECT snapshot_id FROM current_snapshot").fetchone()[0], correction["snapshot_id"])
        warehouse.load_snapshot(self.db, envelope([listing()]))
        self.assertEqual(self.db.execute("SELECT availability FROM current_listings").fetchone()[0], "Limited Availability")

    def test_history_uses_multiset_changes_without_invented_resolution(self):
        original = warehouse.load_snapshot(self.db, envelope([listing(), listing()]))
        revised = warehouse.load_snapshot(self.db, envelope([listing(), listing(availability="Unavailable")], day="2026-11-19"))
        result = warehouse.compare_snapshots(self.db, original["snapshot_id"], revised["snapshot_id"])
        self.assertEqual((result["added"], result["removed"], result["unchanged"]), (1, 1, 1))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM current_listings WHERE status='Resolved'").fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, "unknown"):
            warehouse.compare_snapshots(self.db, "missing", revised["snapshot_id"])

    def test_envelope_count_and_timestamp_fail_before_mutation(self):
        for changes in ({"records_declared": 2}, {"accessed_at": "2026-11-19"}, {"raw_sha256": "wrong"},
                        {"raw_bytes": True}, {"export_date": "2026-02-29"}):
            value = envelope([listing()])
            value.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                warehouse.load_snapshot(self.db, value)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 0)

    def test_concurrent_identical_load_has_one_effect(self):
        value = envelope([listing(), listing()])
        def load():
            with closing(warehouse.connect(self.path)) as conn:
                return warehouse.load_snapshot(conn, deepcopy(value))
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(lambda _: load(), range(2)))
        self.assertEqual(sorted(x["idempotent"] for x in reports), [False, True])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)

    def test_timezone_normalization_and_null_optional_dates(self):
        value = envelope([listing(update_date="", discontinued_date=None)])
        value["accessed_at"] = "2026-11-19T12:00:00+11:00"
        warehouse.load_snapshot(self.db, value)
        self.assertEqual(self.db.execute("SELECT accessed_at FROM current_snapshot").fetchone()[0], "2026-11-19T01:00:00.000000Z")
        self.assertIsNone(self.db.execute("SELECT update_date FROM current_listings").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
