"""Diagnostic/FD tests only: no app import, Arduino, real compiler or network."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts/mcp-compact-review-smoke.py'
spec = importlib.util.spec_from_file_location('review_smoke_diagnostics', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeDiagnosticsTests(unittest.TestCase):
    def test_group_cause_context_and_last_frames(self):
        def original_failure():
            raise FileNotFoundError('controlled local preflight failure')
        try:
            try:
                original_failure()
            except FileNotFoundError as cause:
                raise ValueError('controlled admission failure') from cause
        except ValueError as inner:
            inner.__context__ = LookupError('distinct implicit context')
            try:
                raise ExceptionGroup('TaskGroup wrapper', [ExceptionGroup('nested', [inner]), TypeError('sibling')])
            except ExceptionGroup as group:
                failure = smoke.exception_failure(group)
        records = failure['exceptions']
        self.assertEqual([r['type'] for r in records],
                         ['ExceptionGroup', 'ExceptionGroup', 'ValueError', 'FileNotFoundError', 'LookupError', 'TypeError'])
        self.assertEqual(records[2]['parent'], 1)
        self.assertEqual(records[3]['relation'], '__cause__')
        self.assertEqual(records[4]['relation'], '__context__')
        self.assertTrue(records[3]['frames'][-1].endswith(':original_failure'))
        self.assertIn(str(Path(__file__)), records[3]['frames'][-1])
        self.assertEqual(failure['type'], 'ExceptionGroup')
        self.assertFalse(failure['truncated'])

    def test_exception_unicode_quotas_cycles_and_deep_frames(self):
        def deep(level):
            if level: return deep(level - 1)
            raise RuntimeError('unicode/error "' + '\U0001f9ea' * 10000)
        try:
            deep(8)
        except RuntimeError as leaf:
            group = ExceptionGroup('many children', [leaf] + [ValueError(str(i)) for i in range(30)])
            leaf.__cause__ = group
            leaf.__context__ = leaf
            failure = smoke.exception_failure(group)
        self.assertEqual(len(failure['exceptions']), 8)
        self.assertTrue(failure['truncated'])
        self.assertTrue(failure['shared_or_cyclic'])
        self.assertEqual(len(failure['exceptions'][1]['frames']), 3)
        for record in failure['exceptions']:
            raw = json.dumps(record, ensure_ascii=True, separators=(',', ':')).encode('ascii')
            self.assertLessEqual(len(raw), 2048)
            self.assertLessEqual(len(record['frames']), 3)

    def test_real_python_native_child_and_exit_output_leave_json_only(self):
        # The controlled subprocess only emits markers and fails; it never
        # imports the backend or executes a compiler/startup service.
        program = r'''
import atexit, importlib.util, json, os, subprocess, sys
spec = importlib.util.spec_from_file_location('smoke', sys.argv[1])
smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
atexit.register(lambda: os.write(1, b'late native exit marker\n'))
with smoke.proof_stdout():
    print('Python startup marker')
    os.write(1, b'native startup marker\n')
    try:
        subprocess.run([sys.executable, '-c', "import os,sys; os.write(1,b'child stdout marker\\n'); os.write(2,b'child stderr marker\\n'); sys.exit(7)"], check=True)
    except subprocess.CalledProcessError as exc:
        print(json.dumps({'failure':smoke.exception_failure(exc)}), file=smoke.PROOF_OUTPUT, flush=True)
        raise
'''
        result = subprocess.run([sys.executable, '-c', program, str(SCRIPT)],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        rows = result.stdout.splitlines()
        self.assertEqual(len(rows), 1, result.stdout)
        self.assertEqual(json.loads(rows[0])['failure']['type'], 'CalledProcessError')
        for marker in ('Python startup marker', 'native startup marker', 'child stdout marker',
                       'child stderr marker', 'late native exit marker', 'CalledProcessError'):
            self.assertIn(marker, result.stderr)
        # The command text may legitimately appear INSIDE the JSON exception.
        # Parsing the sole stdout line proves there are no stray output lines.


if __name__ == '__main__':
    unittest.main()
