"""Named wiring exercises real saves, aliases, net conflicts and atomic CAS."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from jsonschema import validate
from app.mcp.compact import Catalog, ProjectStore, ProjectChecker, TOOL_SCHEMAS

ROOT = Path(__file__).resolve().parents[3]


class NamedConnectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
        self.store = ProjectStore(tmp.name, catalog=self.catalog)
        self.doc = self.catalog.get_reference(id='board:esp32', section='project')['data']
        self.doc['fileGroups']['sketch'][0]['content'] = 'void setup(){}\nvoid loop(){}\n'
        epd = self.catalog.get_reference(id='component:epaper-1in54-bw', section='project')['data']['instance_template']
        self.doc['components'].append(epd)

    def read(self, saved):
        return json.loads(self.store.read_artifact(artifact_id=saved['project_artifact_id'], length=12288)['data'])

    def save(self, **args):
        validate(args, TOOL_SCHEMAS['save_project']['inputSchema'])
        result = self.store.save_project(**args)
        validate(result, TOOL_SCHEMAS['save_project']['outputSchema'])
        return result

    def test_batch_aliases_resolve_to_native_and_check_passes(self):
        saved = self.save(document=self.doc, connect=['board.GPIO5 -> epd.cs', 'board.D18 -> epd.CLK', 'board.23 -> epd.MOSI', 'board.3.3V -> epd.VDD', 'board.GROUND -> epd.GND', 'board.17 -> epd.DC', 'board.16 -> epd.RES', 'board.4 -> epd.BUSY'])
        self.assertTrue(saved['ok'], saved)
        doc = self.read(saved)
        self.assertEqual(doc['wires'][0]['start'], {'componentId': 'esp', 'pinName': '5'})
        self.assertEqual(doc['wires'][1]['end']['pinName'], 'SCK')
        checked = ProjectChecker(self.store, self.catalog).check_project(project_id=saved['project_id'], version=saved['version'])
        self.assertEqual(checked['structure_status'], 'valid', checked)

    def test_invalid_pin_role_duplicates_and_input_only_gpio_are_actionable(self):
        cases = [(['board.999 -> epd.CS'], 'invalid_argument'),
                 (['board.5 -> epd.NOPE'], 'invalid_argument'),
                 (['board.5 -> epd.VCC'], 'pin_role_conflict'),
                 (['board.GND -> epd.VCC'], 'pin_role_conflict'),
                 (['board.34 -> epd.CS'], 'pin_role_conflict'),
                 (['board.5 -> epd.CS', 'board.5 -> epd.DC'], 'pin_role_conflict'),
                 (['board.5 -> epd.CS', 'epd.cs -> board.GPIO5'], 'connection_duplicate'),
                 (['board.RX2 -> epd.CS', 'board.16 -> epd.CS'], 'connection_duplicate')]
        for connections, code in cases:
            with self.subTest(connections=connections):
                result = self.save(document=self.doc, connect=connections)
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], code)
                self.assertIn('valid pins', result['error']['expected'])
                self.assertTrue(result['error']['path'].startswith('/connect/'))

    def test_update_is_atomic_checks_existing_nets_and_honors_cas(self):
        original = self.save(document=self.doc)
        updated = self.save(project_id=original['project_id'], expected_version=original['version'], connect=['board.5 -> epd.CS'])
        self.assertTrue(updated['ok'], updated)
        bad = self.save(project_id=original['project_id'], expected_version=updated['version'], connect=['board.5 -> epd.DC'])
        self.assertFalse(bad['ok'])
        self.assertEqual(self.read(updated)['wires'][0]['end']['pinName'], 'CS')
        stale = self.save(project_id=original['project_id'], expected_version=original['version'], connect=['board.17 -> epd.DC'])
        self.assertEqual(stale['error']['code'], 'version_conflict')
        good = self.save(project_id=original['project_id'], expected_version=updated['version'], connect=['board.17 -> epd.DC'])
        self.assertTrue(good['ok'], good)
        self.assertEqual(len(self.read(good)['wires']), 2)

    def test_reviewed_profiles_and_unknown_parts(self):
        for example, params in [('example:blink-led', {'external_led': True}), ('example:uno-servo', {'board': 'arduino-nano', 'angle': 45})]:
            saved = self.save(from_example=example, parameters=params)
            doc = self.read(saved)
            connections = [f"{w['start']['componentId']}.{w['start']['pinName']} -> {w['end']['componentId']}.{w['end']['pinName']}" for w in doc['wires']]
            doc['wires'] = []
            result = self.save(document=doc, connect=connections)
            self.assertTrue(result['ok'], result)
        doc = copy.deepcopy(self.doc)
        doc['components'][0]['metadataId'] = 'custom-chip'
        failure = self.save(document=doc, connect=['board.5 -> epd.CS'])
        self.assertIn('valid pins: unknown', failure['error']['expected'])

    def test_forms_and_rejected_syntax(self):
        for expression in ['board.5 epd.CS', 'missing.5 -> epd.CS', 'board.5 -> epd.CS -> epd.DC']:
            self.assertFalse(self.save(document=self.doc, connect=[expression])['ok'])
        for bad in ([], 'board.5 -> epd.CS', [False]):
            self.assertFalse(self.store.save_project(document=self.doc, connect=bad)['ok'])
        self.assertFalse(self.store.save_project(connect=['board.5 -> epd.CS'])['ok'])
