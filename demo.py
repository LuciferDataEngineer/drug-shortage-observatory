"""Run two explicitly synthetic snapshots without network access or dependencies."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path

import warehouse
from reports import analyze, export_report

FIXTURE = Path(__file__).parent / 'fixtures/synthetic-snapshots.json'


def run_demo(work_dir):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    fixture = json.loads(FIXTURE.read_text())
    reports = []
    with closing(warehouse.connect(work_dir / 'demo.sqlite')) as db:
        for label in ('before', 'after'):
            batch = fixture[label]
            payload = json.dumps(batch['rows'], sort_keys=True).encode()
            raw = work_dir / f'synthetic-{label}.json'
            raw.write_bytes(payload)
            envelope = {
                'source_url': 'https://example.invalid/synthetic-teaching-fixture',
                'accessed_at': batch['export_date'] + 'T12:00:00Z',
                'export_date': batch['export_date'],
                'raw_sha256': hashlib.sha256(payload).hexdigest(),
                'raw_bytes': len(payload), 'raw_path': str(raw.resolve()),
                'records_declared': len(batch['rows']), 'rows': batch['rows'],
            }
            result = warehouse.load_snapshot(db, envelope)
            if not warehouse.load_snapshot(db, envelope)['idempotent']:
                raise ValueError('Synthetic snapshot replay was not idempotent')
            reports.append(result)
            export_report(analyze(db), work_dir / label)
        comparison = warehouse.compare_snapshots(db, reports[0]['snapshot_id'], reports[1]['snapshot_id'])
    evidence = {'coverage': fixture['coverage'], 'loads': reports, 'comparison': comparison}
    (work_dir / 'comparison.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=Path('data/demo'))
    print(json.dumps(run_demo(parser.parse_args().work_dir), indent=2))
