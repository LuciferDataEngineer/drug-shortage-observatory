"""Bounded FDA smoke test, or offline replay of a verified local acquisition.

Exported evidence contains aggregate values and hashes, never raw contact fields.
The independent Python oracle checks every SQL aggregate, then a reopened replay.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import platform
import tempfile

import source
import warehouse
from reports import analyze, export_report


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_tables(rows, export_date):
    """Independent tuple/set/count reference, not the warehouse transform or SQL."""
    statuses, avail, ages, categories = {}, {}, Counter(), {}
    natural, exact, projection, generic_status = Counter(), Counter(), Counter(), defaultdict(set)
    unknown = missing_dosage = missing_reason = 0
    def clean(value):
        return value if value is not None and str(value).strip() else None
    for row in rows:
        status, generic = row['status'], row['generic_name']
        company = clean(row.get('company_name'))
        require(status in {'Current', 'Resolved', 'To Be Discontinued'} and generic, 'Unexpected source status or missing generic label')
        group = statuses.setdefault(status, [0, set(), set()])
        group[0] += 1
        group[1].add(generic)
        if company is not None:
            group[2].add(company)
        availability = clean(row.get('availability'))
        group = avail.setdefault((status, availability or 'Not reported', int(availability is not None)), [0, set()])
        group[0] += 1
        group[1].add(generic)
        update = row.get('update_date')
        days = None if not update else (date.fromisoformat(export_date) - datetime.strptime(update, '%m/%d/%Y').date()).days
        bucket = ('Missing date' if days is None else 'After export date' if days < 0 else
                  '0-7 days' if days <= 7 else '8-30 days' if days <= 30 else
                  '31-90 days' if days <= 90 else '91+ days')
        ages[(status, bucket)] += 1
        cats = sorted(set(row.get('therapeutic_category', [])))
        if status == 'Current':
            for category in cats:
                group = categories.setdefault(category, [0, set()])
                group[0] += 1
                group[1].add(generic)
        fields = ('generic_name', 'company_name', 'presentation', 'package_ndc')
        natural[tuple(clean(row.get(f)) for f in fields)] += 1
        exact[json.dumps(row, sort_keys=True, separators=(',', ':'))] += 1
        texts = ('generic_name','company_name','presentation','package_ndc','dosage_form','status','availability','shortage_reason')
        dates = ('initial_posting_date','update_date','discontinued_date')
        normalized_dates = tuple(datetime.strptime(row[f], '%m/%d/%Y').date().isoformat() if row.get(f) else None for f in dates)
        projection[tuple(clean(row.get(f)) for f in texts) + normalized_dates + (tuple(cats),)] += 1
        generic_status[generic].add(status)
        unknown += availability is not None and availability not in {'Available','Unavailable','Limited Availability'}
        missing_dosage += clean(row.get('dosage_form')) is None
        missing_reason += clean(row.get('shortage_reason')) is None
    quality = {
        'raw_rows': len(rows), 'accepted_rows': len(rows), 'quarantined_rows': 0,
        'repeated_natural_key_groups': sum(v > 1 for v in natural.values()),
        'extra_rows_at_repeated_natural_keys': sum(v-1 for v in natural.values()),
        'exact_raw_duplicate_extra_rows': sum(v-1 for v in exact.values()),
        'projected_duplicate_extra_rows': sum(v-1 for v in projection.values()),
        'generic_labels_with_multiple_statuses': sum(len(v)>1 for v in generic_status.values()),
        'unknown_availability_rows': unknown, 'missing_dosage_form_rows': missing_dosage,
        'missing_shortage_reason_rows': missing_reason,
    }
    return {
        'status_summary': [{'status': k,'listing_rows': v[0], 'generic_labels': len(v[1]), 'company_labels': len(v[2])} for k,v in statuses.items()],
        'availability': [{'status': k[0],'availability': k[1],'availability_reported': k[2],'listing_rows': v[0],'generic_labels': len(v[1])} for k,v in avail.items()],
        'recency': [{'status': k[0],'update_age': k[1],'listing_rows': v} for k,v in ages.items()],
        'categories': [{'category': k,'current_listing_rows': v[0],'current_generic_labels': len(v[1])} for k,v in categories.items()],
        'quality': [{'metric': k,'value': v} for k,v in quality.items()],
    }


def run(data_dir, output, manifest=None):
    acquisition = source.read_snapshot(manifest) if manifest else source.fetch_snapshot(data_dir)
    # Reopen through the persisted digest-checked sidecar in both modes.
    acquisition = source.read_snapshot(acquisition['manifest_path'])
    reference = expected_tables(acquisition['rows'], acquisition['export_date'])
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir, prefix='validation-') as temporary:
        db_path = Path(temporary) / 'replay.sqlite'
        with closing(warehouse.connect(db_path)) as db:
            first = warehouse.load_snapshot(db, acquisition)
            observed = analyze(db)
            require(first['accepted'] == len(acquisition['rows']) and first['quarantined'] == 0, 'Live snapshot did not fully pass validation')
            for name, rows in reference.items():
                normalize = lambda items: sorted(json.dumps(item, sort_keys=True) for item in items)
                if normalize(rows) != normalize(observed['tables'][name]):
                    raise ValueError('Independent aggregate mismatch: ' + name)
            counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in
                      ('snapshots','listings','categories','quarantine','observations','observation_rows')}
            require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity check failed')
            require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'Foreign key violations')
        with closing(warehouse.connect(db_path)) as db:
            replay = warehouse.load_snapshot(db, acquisition)
            require(replay['idempotent'] and analyze(db) == observed, 'Reopened replay changed analysis')
            for table, count in counts.items():
                require(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == count, 'Reopened replay changed ' + table)
    export_report(observed, output)
    evidence = {
        'validated_at': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        'python': platform.python_version(),
        'mode': 'verified offline replay' if manifest else 'bounded public-source acquisition and replay',
        'source_url': acquisition['source_url'], 'source_accessed_at': acquisition['accessed_at'],
        'export_date': acquisition['export_date'], 'raw_sha256': acquisition['raw_sha256'],
        'raw_bytes': acquisition['raw_bytes'], 'snapshot_id': first['snapshot_id'],
        'raw_rows': first['raw_rows'], 'accepted_rows': first['accepted'], 'quarantined_rows': first['quarantined'],
        'sql_tables_compared_independently': len(reference),
        'aggregate_rows_compared': sum(len(v) for v in reference.values()),
        'replay_after_database_reopen_unchanged': True, 'sqlite_integrity': 'ok',
        'foreign_key_violations': 0, 'cloud_deployed': False,
        'coverage': 'One complete observed FDA export; no observed longitudinal trend.',
    }
    (output / 'validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--manifest', type=Path, help='Verify a saved acquisition instead of making network calls')
    parser.add_argument('--output', type=Path, required=True, help='New aggregate-only report directory')
    args = parser.parse_args()
    print(json.dumps(run(args.data_dir, args.output, args.manifest), indent=2))
