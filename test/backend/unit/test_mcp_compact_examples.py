"""Reviewed recipes; real catalog and checker, no compiler or model."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from jsonschema import validate
from app.mcp.compact import Catalog, ProjectChecker, ProjectStore, TOOL_SCHEMAS
from app.mcp.compact.examples import BLINK, SERVO, EPAPER


class ExampleAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ProjectStore(temporary.name, catalog=self.catalog)

    def saved(self, key, parameters):
        arguments = {'from_example': key, 'parameters': parameters}
        validate(arguments, TOOL_SCHEMAS['save_project']['inputSchema'])
        result = self.store.save_project(**arguments)
        self.assertTrue(result['ok'], result)
        validate(result, TOOL_SCHEMAS['save_project']['outputSchema'])
        payload = self.store.read_artifact(artifact_id=result['project_artifact_id'], length=12288)
        self.assertTrue(payload['eof'])
        document = json.loads(payload['data'])
        checked = ProjectChecker(self.store, self.catalog).check_project(project_id=result['project_id'], version=result['version'])
        self.assertEqual(checked['structure_status'], 'valid', checked)
        self.assertFalse(any(item['severity'] == 'error' for item in checked['issues']))
        source = document['fileGroups']['sketch'][0]['content']
        self.assertGreater(len(source.splitlines()), 4)
        self.assertIn('void setup()', source)
        self.assertIn('void loop()', source)
        self.assertEqual(result['example_provenance']['example_id'], key)
        return document, source

    def test_led_uno_native_variant_and_pin_delay_apply_together(self):
        doc, source = self.saved(BLINK, {'external_led': True, 'pins': {'LED': 8}, 'delay_ms': 500})
        self.assertEqual(doc['boards'][0]['boardKind'], 'arduino-uno')
        self.assertEqual(len(doc['components']), 2)
        self.assertEqual(doc['wires'][0]['start']['pinName'], '8')
        self.assertIn('pinMode(8, OUTPUT)', source)
        self.assertEqual(source.count('delay(500);'), 2)

    def test_servo_nano_fixed_angle_with_coherent_pin_and_dependency(self):
        doc, source = self.saved(SERVO, {'board': 'arduino-nano', 'angle': 45, 'pins': {'PWM': 10}, 'delay_ms': 1000})
        self.assertEqual(doc['boards'][0]['boardKind'], 'arduino-nano')
        self.assertEqual(doc['boards'][0]['libraries'], ['Servo'])
        self.assertIn('#define SERVO_PIN 10', source)
        self.assertIn('myServo.write(45);', source)
        self.assertEqual(next(w for w in doc['wires'] if w['end']['pinName'] == 'PWM')['start']['pinName'], '10')

    def test_epaper_uno_and_esp32_keep_spi_and_control_pins_coherent(self):
        for board, spi in [('arduino-uno', {'SDI': '11', 'SCK': '13'}), ('esp32', {'SDI': '23', 'SCK': '18'})]:
            text = 'Hi "V" \\'
            doc, source = self.saved(EPAPER, {'board': board, 'text': text, 'frame': True})
            self.assertIn('display.drawRect(0, 0, 200, 200, GxEPD_BLACK);', source)
            self.assertIn('F(' + json.dumps(text, ensure_ascii=False) + ')', source)
            for wire in doc['wires']:
                role = wire['end']['pinName']
                if role in spi:
                    self.assertEqual(wire['start']['pinName'], spi[role])
            self.assertEqual(doc['boards'][0]['libraries'], ['GxEPD2', 'Adafruit GFX Library'])

    def test_parameters_are_discoverable_from_search_and_linked_examples(self):
        self.assertEqual(len(TOOL_SCHEMAS), 6)
        for key, query in [(BLINK, 'blink'), (SERVO, 'servo'), (EPAPER, 'epaper')]:
            result = self.catalog.search_catalog(query=query, kind='example')
            item = next(item for item in result['items'] if item['id'] == key)
            self.assertTrue(item['from_example']['supported'])
            self.assertIn('board', item['from_example']['parameters']['properties'])
            reference = self.catalog.get_reference(id=key)
            self.assertEqual(reference['data']['from_example'], item['from_example'])
        linked = self.catalog.get_reference(id='component:servo', section='project')['data']
        self.assertIn(SERVO, linked['example_references'])
        self.assertTrue(next(item for item in linked['example_options'] if item['id'] == SERVO)['from_example']['supported'])

    def test_invalid_unknown_colliding_and_unsafe_parameters_are_rejected(self):
        cases = [(BLINK, {'pins': {'LED': 8}}), (SERVO, {'angle': 181}), (SERVO, {'angle': True}),
                 (SERVO, {'delay_ms': 5}), (SERVO, {'board': 'esp32'}), (EPAPER, {'text': 'bad\ntext'}),
                 (EPAPER, {'pins': {'CS': 9}}), (EPAPER, {'board': 'esp32', 'pins': {'CS': 20}}),
                 (EPAPER, {'pins': {'CS': 12}}), (EPAPER, {'code': 'arbitrary code'}),
                 ('example:missing', {}), (EPAPER, {'pins': {'SDI': 10}})]
        for key, parameters in cases:
            with self.subTest(key=key, parameters=parameters):
                result = self.store.save_project(from_example=key, parameters=parameters)
                self.assertFalse(result['ok'], result)

    def test_recipe_anchor_changes_are_not_silently_accepted(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        entry = next(item for item in snapshot['entries'] if item['id'] == BLINK)
        entry['project']['code'] = entry['project']['code'].replace('pinMode(13, OUTPUT)', 'pinMode(7, OUTPUT)')
        self.store.catalog = Catalog(snapshot)
        result = self.store.save_project(from_example=BLINK)
        self.assertEqual(result['error']['code'], 'unsupported')
