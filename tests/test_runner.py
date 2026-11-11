import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('adapter', ROOT / 'runner.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_action(self, code, **values):
        path = self.root / 'firmware with spaces.py'
        path.write_text(code, encoding='utf-8')
        env = dict(os.environ, RUNNER_TEMP=str(self.root), PIN_AUDIT_PATHS=str(path),
                   GITHUB_OUTPUT=str(self.root / 'outputs'), GITHUB_STEP_SUMMARY=str(self.root / 'summary'))
        env.update(values)
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'runner.py')],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        reports = list(self.root.glob('pin-audit-*/report.json'))
        return result, json.loads(reports[-1].read_text())

    def test_valid_resource_lifetime(self):
        result, report = self.run_action('import board, digitalio\nwith digitalio.DigitalInOut(board.D0): pass\na=digitalio.DigitalInOut(board.D0)')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report['scan']['files'][0]['conflicts'], 0)
        self.assertIn('exit-code<<', (self.root/'outputs').read_text())

    def test_conflict_is_failed_and_annotated(self):
        result, report = self.run_action('import board, digitalio\na=digitalio.DigitalInOut(board.D0)\nb=digitalio.DigitalInOut(board.D0)')
        self.assertEqual(result.returncode, 1)
        self.assertIn('::error ', result.stdout)
        self.assertEqual(report['scan']['files'][0]['conflicts'], 1)
        self.assertIn('1 potential conflict', (self.root/'summary').read_text())

    def test_strict_by_default(self):
        result, report = self.run_action('import board\na=board.I2C()')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report['scan']['files'][0]['incomplete'])

    def test_coverage_can_be_advisory(self):
        result, _ = self.run_action('import board\na=board.I2C()', PIN_AUDIT_STRICT='false')
        self.assertEqual(result.returncode, 0)

    def test_invalid_boolean_is_operational_error(self):
        result, report = self.run_action('pass', PIN_AUDIT_STRICT='maybe')
        self.assertEqual(result.returncode, 2)
        self.assertIn('strict must', report['error'])

    def test_missing_input_still_saves_report_and_outputs(self):
        result, report = self.run_action('pass', PIN_AUDIT_PATHS='missing-file.py')
        self.assertEqual(result.returncode, 2)
        self.assertIn('does not exist', report['error'])
        self.assertIn('report-path<<', (self.root/'outputs').read_text())

    def test_invalid_syntax_is_saved(self):
        result, report = self.run_action('if (')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report['scan']['files'][0]['diagnostics'][0]['code'], 'PA900')

    def test_repository_module_shadowing_cannot_execute_code(self):
        sentinel = self.root/'executed'
        for name in ['pin_audit.py', 'json.py']:
            (self.root/name).write_text(f'open({str(sentinel)!r}, "w").write("bad")\nraise RuntimeError("shadow")')
        result, _ = self.run_action('pass', PYTHONPATH=str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse(sentinel.exists())

    def test_firmware_itself_is_never_executed(self):
        sentinel = self.root/'executed'
        result, _ = self.run_action(f'open({str(sentinel)!r}, "w").write("bad")')
        self.assertEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_input_is_never_shell_code_or_cli_options(self):
        invocation = adapter.command({'PIN_AUDIT_PATHS': '--version\n$(touch sentinel)\npath with spaces.py'})
        self.assertEqual(invocation[-4:], ['--', '--version', '$(touch sentinel)', 'path with spaces.py'])
        self.assertEqual(invocation[1], '-I')

    def test_empty_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            adapter.command({'PIN_AUDIT_PATHS':' \n '})

    def test_annotation_escaping(self):
        message = adapter.annotation('error', 'a\n::warning::bad%', path='a,b:c\n.py')
        self.assertEqual(len(message.splitlines()), 1)
        self.assertIn('a%2Cb%3Ac%0A.py', message)
        self.assertIn('a%0A::warning::bad%25', message)

    def test_aliases_passed_as_data(self):
        config = self.root/'aliases with spaces.json'
        config.write_text('{"aliases":[["D0","LED"]]}')
        result, report = self.run_action('import board,digitalio\na=digitalio.DigitalInOut(board.D0)\nb=digitalio.DigitalInOut(board.LED)', PIN_AUDIT_ALIASES=str(config))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['scan']['files'][0]['conflicts'], 1)

    def test_report_does_not_contain_firmware_contents(self):
        marker = 'PRIVATE_SOURCE_MARKER_823'
        _, report = self.run_action(f'# {marker}\npass')
        self.assertNotIn(marker, json.dumps(report))


if __name__ == '__main__':
    unittest.main()
