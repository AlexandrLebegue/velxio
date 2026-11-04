"""Compiler logs must lead with errors, never with a warning mentioning errors."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact.diagnostics import diagnostics, parse_line


class ReadableDiagnosticsTests(unittest.TestCase):
    def test_error_after_hundreds_of_warnings_is_first_and_warnings_are_separate(self):
        raw = ('sketch.ino:1: warning: comment [-Wcomment]\n' * 300 +
               '\x1b[31msketch.ino:12:7: error: missing semicolon\x1b[0m\n' +
               'sketch.ino:13: note: an example says error: this is still a note\n').encode()
        rows, truncated, warnings, warnings_truncated = diagnostics(raw, {'id': 'artifact', 'sha256': 'a' * 64}, {'files': [{'name': 'sketch.ino'}]})
        self.assertEqual(rows[0]['severity'], 'error')
        self.assertEqual(rows[0]['line'], 12)
        self.assertEqual(rows[0]['file'], 'sketch.ino')
        self.assertTrue(rows[0]['suggestion'])
        self.assertEqual(len(warnings), 5)
        self.assertTrue(warnings_truncated)
        self.assertFalse(truncated)
        self.assertTrue(all(row['severity'] != 'warning' for row in rows))

    def test_bare_warning_and_note_cannot_become_errors_from_their_message(self):
        self.assertEqual(parse_line('warning: example: error: quoted diagnostic')['severity'], 'warning')
        self.assertEqual(parse_line('note: example: error: quoted diagnostic')['severity'], 'note')
        error = parse_line('cc1plus: fatal error: Missing.h: No such file or directory')
        self.assertEqual(error['severity'], 'error')
        self.assertIsNone(error['line'])
        self.assertIn('installed library', error['suggestion'])
        self.assertIsNone(parse_line('Build progress: 42%'))
        self.assertIn('without a message', parse_line('main.c:1: error:')['message'])

    def test_paths_are_basenames_and_linker_errors_have_a_suggestion(self):
        row = parse_line('C:\\build\\sketch.ino.cpp:5:2: error: no member named display')
        self.assertEqual(row['file'], 'sketch.ino.cpp')
        self.assertEqual(row['line'], 5)
        row = parse_line("ld: sketch.o: undefined reference to `loop'")
        self.assertEqual(row['severity'], 'error')
        self.assertIn('setup()', row['suggestion'])
