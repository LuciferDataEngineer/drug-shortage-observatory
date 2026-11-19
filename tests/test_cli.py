"""Offline end-to-end CLI contract checks using explicitly fictional records."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from demo import FIXTURE
from validate_live import expected_tables

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_two_snapshot_demo_and_cli_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / 'demo'
            execution = subprocess.run([sys.executable, str(ROOT/'demo.py'), '--work-dir', str(work)],
                                       cwd=temp, capture_output=True, text=True, check=True)
            result = json.loads(execution.stdout)
            self.assertEqual((result['comparison']['added'], result['comparison']['removed'], result['comparison']['unchanged']), (2, 2, 3))
            self.assertEqual((result['loads'][0]['accepted'], result['loads'][0]['quarantined']), (5, 1))
            output = Path(temp) / 'report'
            report = subprocess.run([sys.executable, str(ROOT/'monitor.py'), 'analyze', '--db', str(work/'demo.sqlite'), '--output', str(output)],
                                    cwd=temp, capture_output=True, text=True, check=True)
            summary = json.loads(report.stdout)
            expected = expected_tables(json.loads(FIXTURE.read_text())['after']['rows'], '2026-11-19')
            for name, rows in expected.items():
                normalized = lambda values: sorted(json.dumps(x, sort_keys=True) for x in values)
                self.assertEqual(normalized(rows), normalized(summary['tables'][name]), name)
            self.assertEqual(json.loads((output/'summary.json').read_text()), summary)
            rerun = subprocess.run([sys.executable, str(ROOT/'monitor.py'), 'compare',
                                    result['loads'][0]['snapshot_id'], result['loads'][1]['snapshot_id'],
                                    '--db', str(work/'demo.sqlite')], cwd=temp, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(rerun.stdout), result['comparison'])

    def test_empty_database_does_not_create_report(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'report'
            result = subprocess.run([sys.executable, str(ROOT/'monitor.py'), 'analyze', '--db', str(Path(temp)/'empty.sqlite'), '--output', str(target)],
                                    cwd=temp, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Load a snapshot', result.stderr)
            self.assertFalse(target.exists())

    def test_demo_refuses_overwrite_before_mutating_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'already-exists'
            target.mkdir()
            sentinel = target / 'sentinel.txt'
            sentinel.write_text('preserve')
            result = subprocess.run([sys.executable, str(ROOT/'demo.py'), '--work-dir', str(target)],
                                    cwd=temp, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(), 'preserve')
            self.assertEqual(list(target.iterdir()), [sentinel])
