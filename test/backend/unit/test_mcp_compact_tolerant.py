"""General scalar/JSON transport, real native pads and composable example variants."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from app.mcp.compact import Catalog, ProjectStore, ProjectChecker, TOOL_SCHEMAS
from app.mcp.compact.arguments import normalize
from app.mcp.compact.contracts import model_input_schema

ROOT=Path(__file__).resolve().parents[3]

class TolerantTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.catalog=Catalog.from_snapshot(ROOT/'backend/app/mcp/compact/catalog.snapshot.json')
        self.store=ProjectStore(tmp.name,catalog=self.catalog)
    def document(self,saved):
        return json.loads(self.store.read_artifact(artifact_id=saved['project_artifact_id'],length=12288)['data'])
    def test_complete_encoded_structures_and_scalar_numbers_are_tolerated_losslessly(self):
        raw={'from_example':'example:blink-led','parameters':json.dumps({'external_led':True,'resistance_ohms':'330','delay_ms':'250','board':'arduino-nano','led_color':'green'})}
        saved=self.store.save_project(**raw);self.assertTrue(saved['ok'],saved)
        doc=self.document(saved)
        self.assertEqual(next(c for c in doc['components'] if c['metadataId']=='resistor')['properties']['value'],'330')
        source=doc['fileGroups']['sketch'][0]['content'];self.assertIn('delay(250);',source)
        changed=self.store.save_project(project_id=saved['project_id'],expected_version=saved['version'],changes=json.dumps([{'op':'set','path':'/name','value':'Renamed'}]))
        self.assertTrue(changed['ok'],changed)
        self.assertIsInstance(raw['parameters'],str)
        self.assertEqual(normalize('save_project',{'from_example':'example:uno-hcsr04','parameters':{'display_address':'0x27'}})['parameters']['display_address'],39)
        escaped=json.dumps(json.dumps([{'op':'set','path':'/name','value':'Decoded'}]))[1:-1]
        self.assertIsInstance(normalize('save_project',{'changes':escaped})['changes'],list)
        doc['boards'][0]['x']='12.5'
        encoded=self.store.save_project(document=json.dumps(doc));self.assertTrue(encoded['ok'],encoded)
        self.assertEqual(self.document(encoded)['boards'][0]['x'],12.5)
    def test_incomplete_structures_are_rejected_without_guessing_and_source_is_never_unescaped(self):
        for key,value in [('document','{"format":"velxio-pro'),('changes','[{"op":"set","path":"/')]:
            result=self.store.save_project(**{key:value});self.assertFalse(result['ok'])
        source='// keep literal \\n and "quotes"\r\nvoid setup(){}\r\nvoid loop(){}\r\n'
        saved=self.store.save_project(sketch=source)
        self.assertEqual(self.document(saved)['fileGroups']['sketch'][0]['content'],source)
    def test_small_model_schema_keeps_authoritative_validation(self):
        full=TOOL_SCHEMAS['save_project']['inputSchema'];small=model_input_schema('save_project')
        self.assertLess(len(json.dumps(small)),len(json.dumps(full))*.7)
        self.assertEqual(next(iter(small['properties'])),'from_example')
        self.assertNotIn('connect',small['properties'])
        broken=self.catalog.get_reference(id='board:esp32',section='project')['data'];del broken['boards'][0]['boardKind']
        error=self.store.save_project(document=broken)['error'];self.assertEqual(error['path'],'/boards/0/boardKind')
    def test_real_native_pins_disallow_invented_cathode_but_accept_editor_ground_alias(self):
        saved=self.store.save_project(from_example='example:blink-led',parameters={'external_led':True})
        doc=self.document(saved);wire=next(w for w in doc['wires'] if w['start'].get('pinName')=='C')
        wire['end']['pinName']='GND'
        good=self.store.save_project(document=doc)
        self.assertEqual(ProjectChecker(self.store,self.catalog).check_project(project_id=good['project_id'],version=good['version'])['structure_status'],'valid')
        wire['start']['pinName']='K';bad=self.store.save_project(document=doc)
        report=ProjectChecker(self.store,self.catalog).check_project(project_id=bad['project_id'],version=bad['version'])
        issue=next(i for i in report['issues'] if i['code']=='pin_invalid');self.assertIn('C',issue['expected'])
    def test_peripheral_variants_have_consistent_native_wires_and_portable_sources(self):
        cases=[('button-led',{'board':'arduino-nano','mode':'toggle','debounce_ms':'40'}),
               ('uno-servo',{'board':'arduino-uno','control':'potentiometer','input_component':'slide-potentiometer','analog_pin':'A1'}),
               ('uno-hcsr04',{'board':'arduino-nano','display':'ssd1306','alarm':'led','threshold':'80'}),
               ('uno-dht22',{'display':'lcd1602-i2c','alarm':'buzzer','alarm_metric':'humidity','threshold':70}),
               ('epaper-1in54-uno-hello',{'board':'esp32','text':'Quotes "ok"','align':'center'})]
        for key,parameters in cases:
            with self.subTest(key=key):
                saved=self.store.save_project(from_example='example:'+key,parameters=parameters);self.assertTrue(saved['ok'],saved)
                doc=self.document(saved);source=doc['fileGroups']['sketch'][0]['content'];self.assertGreater(source.count('\n'),5)
                report=ProjectChecker(self.store,self.catalog).check_project(project_id=saved['project_id'],version=saved['version'])
                self.assertEqual(report['structure_status'],'valid',report['issues'])
                if key.startswith('epaper'):
                    self.assertIn('getTextBounds',source);self.assertIn('\\"ok\\"',source)
    def test_invalid_parameters_cannot_inject_code_or_short_sensor_pins(self):
        for parameters in [{'threshold':'1); bad();'},{'threshold':True},{'trigger_pin':9,'echo_pin':9},{'alarm':'led','alarm_pin':9}]:
            self.assertFalse(self.store.save_project(from_example='example:uno-hcsr04',parameters=parameters)['ok'])
