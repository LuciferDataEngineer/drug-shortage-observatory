"""Fetch, validate, store and analyze FDA drug-shortage snapshots."""
import argparse
from contextlib import closing
import json
import logging
from pathlib import Path

import source
import warehouse
from reports import analyze, export_report


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return warehouse.connect(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--data-dir", type=Path, default=Path("data"))
    ingest = commands.add_parser("ingest")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("--db", type=Path, default=Path("data/shortages.sqlite"))
    report = commands.add_parser("analyze")
    report.add_argument("--db", type=Path, default=Path("data/shortages.sqlite"))
    report.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("before")
    compare.add_argument("after")
    compare.add_argument("--db", type=Path, default=Path("data/shortages.sqlite"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "fetch":
        envelope = source.fetch_snapshot(args.data_dir)
        print(envelope["manifest_path"])
        return
    with closing(database(args.db)) as db:
        if args.command == "ingest":
            result = warehouse.load_snapshot(db, source.read_snapshot(args.manifest))
        elif args.command == "compare":
            result = warehouse.compare_snapshots(db, args.before, args.after)
        else:
            result = analyze(db)
            export_report(result, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
