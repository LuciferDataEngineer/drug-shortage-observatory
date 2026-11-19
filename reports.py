"""Aggregate analyst outputs with explicit snapshot identity and denominator."""
import fcntl
import csv
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

QUERIES = ("status_summary", "availability", "recency", "categories", "quality")
SQL_DIR = Path(__file__).parent / "sql"


def source_coverage(source_url):
    """Label evidence from the recorded source, without treating arbitrary URLs as FDA."""
    try:
        url = urlsplit(source_url)
        if url.hostname == "example.invalid" or (url.hostname or "").endswith(".example.invalid"):
            return ("synthetic_fixture", "SYNTHETIC teaching fixtures; fictional labels and IDs, no clinical interpretation.")
        if (url.scheme == "https" and url.hostname == "download.open.fda.gov"
                and url.port in (None, 443) and not url.username and not url.password
                and not url.query and not url.fragment
                and url.path.startswith("/drug/shortages/") and url.path.endswith(".json.zip")):
            return ("official_fda_bulk", "Observed FDA bulk snapshot at the recorded export date; a source listing census, not patient-level or clinical evidence.")
    except ValueError:
        pass
    return ("custom_unverified", "CUSTOM / UNVERIFIED source snapshot; source authenticity and real-world coverage are not established.")


def analyze(db):
    # The transaction keeps all five queries on one reader snapshot during concurrent loads.
    db.execute("BEGIN")
    try:
        current = db.execute("SELECT * FROM current_snapshot").fetchone()
        if current is None:
            raise ValueError("Load a snapshot before requesting an analysis")
        tables = {}
        for name in QUERIES:
            cursor = db.execute((SQL_DIR / (name + ".sql")).read_text())
            columns = [column[0] for column in cursor.description]
            tables[name] = [dict(zip(columns, row)) for row in cursor.fetchall()]
        provenance, coverage = source_coverage(current["source_url"])
        result = {
            "snapshot_id": current["snapshot_id"],
            "export_date": current["export_date"],
            "source_accessed_at": current["accessed_at"],
            "source_url": current["source_url"],
            "provenance": provenance,
            "coverage": coverage,
            "raw_sha256": current["raw_sha256"],
            "raw_rows": current["raw_rows"],
            "accepted_rows": current["accepted"],
            "quarantined_rows": current["quarantined"],
            "tables": tables,
        }
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def table_md(rows):
    if not rows:
        return "_No rows._\n"
    columns = list(rows[0])
    def cell(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(cell(row[column]) for column in columns) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def export_report(report, destination):
    """Write a new report directory atomically, preserving previous results on failure."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # The parent-directory advisory lock coordinates parallel exporters without
    # leaving a lock file. Closing the descriptor releases it on every exit.
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Report directory exists. Choose a new output path.")
        with tempfile.TemporaryDirectory(prefix=".report-", dir=destination.parent) as temp:
            temp_path = Path(temp)
            prepared = temp_path / "complete"
            prepared.mkdir()
            (prepared / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            source_labels = {
                "synthetic_fixture": ("SYNTHETIC shortage snapshot analysis", "SYNTHETIC fixture snapshot"),
                "official_fda_bulk": ("FDA shortage snapshot analysis", "FDA bulk export"),
                "custom_unverified": ("CUSTOM / UNVERIFIED shortage snapshot analysis", "Custom / unverified snapshot"),
            }
            title, source_label = source_labels[report["provenance"]]
            paragraphs = [
                "# " + title,
                "**Coverage: " + report["coverage"] + "**",
                f"{source_label} **{report['export_date']}**, acquired {report['source_accessed_at']}.",
                f"Recorded source: `{report['source_url']}`.",
                f"Accepted {report['accepted_rows']:,} of {report['raw_rows']:,} source listing rows. Quarantined {report['quarantined_rows']:,}.",
                "Generic labels, company labels and listing rows have separate denominators. FDA advises against using openFDA for medical-care decisions.",
                f"Snapshot ID `{report['snapshot_id']}`. Archive SHA-256 `{report['raw_sha256']}`.",
            ]
            labels = {
                "status_summary": "Listing status",
                "availability": "Status and reported availability",
                "recency": "Age of the source update at the export date",
                "categories": "Therapeutic categories among Current listings",
                "quality": "Source quality and duplicate counts",
            }
            for name, rows in report["tables"].items():
                with (prepared / (name + ".csv")).open("w", newline="", encoding="utf8") as stream:
                    if rows:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                        writer.writeheader()
                        writer.writerows(rows)
                paragraphs.extend(["## " + labels[name], table_md(rows)])
            paragraphs.extend([
                "Generic labels may have listings in multiple statuses. A listing marked Current can report Available for an individual presentation. Category memberships overlap. Update age measures source metadata freshness and does not estimate shortage duration.",
                "The first collected export provides one observed time point. Future local observations support record multiset comparisons. Disappearance from an export is recorded as an observation change.",
                "[FDA dataset overview](https://open.fda.gov/apis/drug/drugshortages/) · [Reuse terms](https://open.fda.gov/license/)",
            ])
            (prepared / "report.md").write_text("\n\n".join(paragraphs) + "\n")
            os.rename(prepared, destination)
    finally:
        os.close(directory_fd)
