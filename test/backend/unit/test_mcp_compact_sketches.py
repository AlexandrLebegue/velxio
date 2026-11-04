"""Arduino sanity checks: damaged source is not a usable-build certificate."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact import Catalog, ProjectChecker, ProjectStore
from app.mcp.compact.sketches import sketch_issues


class SketchSanityTests(unittest.TestCase):
    def errors(self, source, extras=()):
        return sketch_issues([{'name': 'sketch.ino', 'content': source}, *extras], '/fileGroups/sketch')

    def test_requested_corruptions_are_actionable_errors_with_filename(self):
        self.assertEqual(sketch_issues([], '/fileGroups/sketch')[0]['path'], '/fileGroups/sketch')
        cases = (
            ('void setup(){} // void loop(){}', 'sketch_collapsed_lines'),
            ('#include <Servo.h> void setup(){} void loop(){}', 'sketch_collapsed_lines'),
            ('void setup() {}\n', 'sketch_missing_entry_points'),
            ('/* void setup() {}\nvoid loop() {} */', 'sketch_comment_only'),
            ('void setup(){Serial.println(\'\'Hello\'\');}\nvoid loop(){}', 'sketch_empty_character_literal'),
            ('', 'sketch_missing_entry_points'),
            ('void setup();\nvoid loop();', 'sketch_missing_entry_points'),
            ('#define CALLBACKS \\\nvoid setup(){} void loop(){}', 'sketch_missing_entry_points'),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                issues = self.errors(source)
                item = next(item for item in issues if item['code'] == expected)
                self.assertEqual(item['file'], 'sketch.ino')
                self.assertEqual(item['path'], '/fileGroups/sketch/0/content')
                self.assertEqual(item['severity'], 'error')
                self.assertTrue(item['observed'] and item['expected'] and item['next_action'])

    def test_literals_comments_and_multifile_callbacks_do_not_create_false_errors(self):
        valid = (
            'void setup(){} void loop(){}',
            '#include <Servo.h>\n// header\nvoid setup(void){}\nvoid loop(){}\n',
            'void setup(){Serial.println("https://example.test/#include \'\'");}\nvoid loop(){}',
            'void setup(){auto s=R"tag(// \'\' /* text */)tag";}\nvoid loop(){}',
            'void setup(){char c=\'a\';}\nvoid loop(){}',
        )
        for source in valid:
            self.assertEqual(self.errors(source), [], source)
        self.assertEqual(self.errors('void setup(){}', ({'name': 'loop.cpp', 'content': 'void loop() {}'}, {'name': 'notes.ino', 'content': '// notes only'})), [])
        self.assertEqual(self.errors('void setup(){}\nvoid loop(){}', ({'name': 'helper.hpp', 'content': '#pragma once'},)), [])
        self.assertTrue(self.errors('const char *s="void setup(){} void loop(){}";'))

    def test_checker_surfaces_sanity_without_a_compiler_policy_and_skips_espidf(self):
        catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectStore(temporary)
            checker = ProjectChecker(store, catalog, source_root=Path(temporary) / 'no-policy')
            doc = catalog.get_reference(id='board:arduino-uno', section='project')['data']
            doc['fileGroups']['sketch'][0]['content'] = '/* setup and loop are missing */'
            saved = store.save_project(document=doc)
            result = checker.check_project(project_id=saved['project_id'], version=saved['version'])
            self.assertEqual(result['status'], 'invalid')
            self.assertEqual(result['issues'][0]['severity'], 'error')
            self.assertIn('sketch.ino', result['issues'][0]['next_action'])
            doc['boards'][0]['languageMode'] = 'espidf'
            doc['boards'][0]['boardKind'] = 'esp32'
            doc['fileGroups']['sketch'] = [{'name': 'main.c', 'content': 'void app_main() {}'}]
            saved = store.save_project(document=doc)
            result = checker.check_project(project_id=saved['project_id'], version=saved['version'])
            self.assertFalse(any(item['code'].startswith('sketch_') for item in result['issues']))
