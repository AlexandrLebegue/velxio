"""Plain sketch transport and immutable CAS updates; no network or compiler."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from jsonschema import validate
from app.mcp.compact import ProjectStore, Catalog, ProjectChecker, TOOL_SCHEMAS


class PlainSketchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
        self.store = ProjectStore(temporary.name, catalog=self.catalog)

    def read(self, saved):
        result = self.store.read_artifact(artifact_id=saved['project_artifact_id'], length=12288)
        self.assertTrue(result['eof'])
        return json.loads(result['data'])

    def test_exact_multiline_roundtrip_with_quotes_crlf_unicode_and_literal_escapes(self):
        sketch = '// Keep CRLF and quotes intact\r\nvoid setup() {\r\n  Serial.begin(9600);\r\n  Serial.println("Hello \\"world\\" é; literal \\n");\r\n}\r\nvoid loop() {}\r\n'
        arguments = {'board': 'arduino-uno', 'sketch': sketch}
        # The MCP SDK serializes the string once; it is not a nested JSON document.
        arguments = json.loads(json.dumps(arguments))
        validate(arguments, TOOL_SCHEMAS['save_project']['inputSchema'])
        saved = self.store.save_project(**arguments)
        self.assertTrue(saved['ok'], saved)
        validate(saved, TOOL_SCHEMAS['save_project']['outputSchema'])
        document = self.read(saved)
        actual = document['fileGroups']['sketch'][0]['content']
        self.assertEqual(actual.encode('utf-8'), sketch.encode('utf-8'))
        self.assertEqual(saved['warnings'], [])
        result = ProjectChecker(self.store, self.catalog).check_project(project_id=saved['project_id'], version=saved['version'])
        self.assertEqual(result['structure_status'], 'valid', result)

    def test_suspicious_source_warns_but_is_never_silently_repaired(self):
        for sketch in ('// header void setup(){} void loop(){}', "void setup(){Serial.print(''Hello'');}void loop(){}"):
            saved = self.store.save_project(sketch=sketch)
            self.assertTrue(saved['ok'], saved)
            self.assertTrue(saved['warnings'])
            warning = saved['warnings'][0]
            self.assertEqual(warning['file'], 'sketch.ino')
            self.assertTrue(warning['observed'] and warning['correction'])
            self.assertEqual(self.read(saved)['fileGroups']['sketch'][0]['content'], sketch)

    def test_text_update_preserves_helpers_and_uses_compare_and_swap(self):
        original = self.store.save_project(sketch='void setup(){}\nvoid loop(){}\n')
        document = self.read(original)
        document['fileGroups']['sketch'].append({'name': 'helper.h', 'content': '#pragma once\n'})
        with_helper = self.store.save_project(document=document, project_id=original['project_id'], expected_version=original['version'])
        source = 'void setup(){Serial.println("new");}\nvoid loop(){}\n'
        updated = self.store.save_project(sketch=source, project_id=original['project_id'], expected_version=with_helper['version'])
        self.assertTrue(updated['ok'], updated)
        files = self.read(updated)['fileGroups']['sketch']
        self.assertEqual(files[0]['content'], source)
        self.assertEqual(files[1], {'name': 'helper.h', 'content': '#pragma once\n'})
        stale = self.store.save_project(sketch=source, project_id=original['project_id'], expected_version=original['version'])
        self.assertEqual(stale['error']['code'], 'version_conflict')
        self.assertNotEqual(self.read(original)['fileGroups']['sketch'][0]['content'], source)

    def test_invalid_mixed_forms_and_unsupported_modes_do_not_create_a_project(self):
        self.assertFalse(self.store.save_project(sketch={}, board='arduino-uno')['ok'])
        self.assertFalse(self.store.save_project(sketch='x', changes=[])['ok'])
        self.assertFalse(self.store.save_project(sketch='x', board_id='missing')['ok'])
        self.assertFalse(self.store.save_project(sketch='x', board='not-a-board')['ok'])
