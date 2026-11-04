"""Small-model authoring: native fragments, actionable errors and search variants.

All persistence is temporary; no compiler, dependency install, service or network.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact import Catalog, ProjectChecker, ProjectStore, TOOL_SCHEMAS
from app.mcp.compact.facade import _save_schema_error


class CompactAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='compact-authoring-')
        self.addCleanup(temporary.cleanup)
        self.store = ProjectStore(temporary.name)

    def board(self):
        result = self.catalog.get_reference(id='board:esp32', section='project')
        self.assertTrue(result['ok'], result)
        return result['data']

    def screen(self):
        result = self.catalog.get_reference(id='component:epaper-1in54-bw', section='project')
        self.assertTrue(result['ok'], result)
        return result['data']

    def assembled(self):
        doc = self.board()
        doc['fileGroups']['sketch'][0]['content'] = 'void setup() {}\nvoid loop() {}\n'
        fragment = self.screen()
        doc['components'].extend(fragment['components'])
        # Exact board names come from the pins reference, not guessed GPIO labels.
        connections = [('GND', 'GND'), ('3V3', 'VCC'), ('18', 'SCK'), ('23', 'SDI'),
                       ('5', 'CS'), ('17', 'DC'), ('16', 'RST'), ('4', 'BUSY')]
        self.assertEqual({end for _, end in connections}, set(fragment['pinNames']))
        page = self.catalog.get_reference(id='board:esp32', section='pins')
        board_pins = list(page['data'])
        while page['has_more']:
            page = self.catalog.get_reference(**page['next_request']['arguments'])
            board_pins.extend(page['data'])
        self.assertEqual(len(board_pins), page['total'])
        self.assertTrue({start for start, _ in connections} <= {p['name'] for p in board_pins})
        doc['wires'] = [{'id': 'w-' + end, 'start': {'componentId': doc['boards'][0]['id'], 'pinName': start},
                         'end': {'componentId': fragment['components'][0]['id'], 'pinName': end}}
                        for start, end in connections]
        return doc

    def assert_error(self, result, path, code='invalid_argument'):
        self.assertFalse(result['ok'], result)
        error = result['error']
        self.assertEqual(error['code'], code, error)
        self.assertEqual(error['path'], path, error)
        self.assertTrue(error['expected'], error)
        self.assertIsInstance(error['received'], str)
        self.assertLessEqual(len(error['received']), 200)
        self.assertIn('expected', error['message'])
        return error

    def test_board_reference_is_directly_saveable_and_native_templates_are_complete(self):
        doc = self.board()
        self.assertEqual(len(doc['boards']), 1)
        self.assertEqual(doc['components'], [])
        group = doc['boards'][0]['activeFileGroupId']
        self.assertEqual(doc['fileGroups'][group], [{'name': 'sketch.ino', 'content': ''}])
        self.assertEqual(doc['activeBoardId'], doc['boards'][0]['id'])
        self.assertTrue(self.store.save_project(document=doc)['ok'])
        for key in ('board:arduino-uno', 'board:arduino-nano'):
            result = self.catalog.get_reference(id=key, section='project')
            self.assertTrue(self.store.save_project(document=result['data'])['ok'])
            self.assertEqual(result['instance_template']['boardKind'], key.split(':', 1)[1])
            self.assertFalse(result['execution']['supported'])
        for key in ('led', 'resistor', 'servo', 'epaper-1in54-bw'):
            fragment = self.catalog.get_reference(id='component:' + key, section='project')['data']
            template = fragment['instance_template']
            self.assertTrue({'id', 'metadataId', 'x', 'y', 'properties'} <= template.keys())
            self.assertEqual(template['metadataId'], key)
            self.assertEqual(fragment['components'], [template])
            candidate = copy.deepcopy(doc)
            candidate['components'].append(template)
            self.assertTrue(self.store.save_project(document=candidate)['ok'])
        self.assertIn('example:epaper-1in54-uno-hello', self.screen()['example_references'])
        self.assertEqual(self.catalog.get_reference(id='board-velxio-esp32', section='project')['data'], doc)
        self.screen()['components'][0]['properties']['refreshMs'] = 999
        self.assertEqual(self.screen()['components'][0]['properties'],
                         {'panelKind': 'epaper-1in54-bw', 'refreshMs': 50})

    def test_reference_board_screen_eight_wires_save_and_check_roundtrip(self):
        doc = self.assembled()
        saved = self.store.save_project(document=doc)
        self.assertTrue(saved['ok'], saved)
        read = self.store.read_artifact(artifact_id=saved['project_artifact_id'])
        self.assertEqual(json.loads(read['data']), doc)
        checked = ProjectChecker(self.store, self.catalog).check_project(
            project_id=saved['project_id'], version=saved['version'])
        self.assertTrue(checked['ok'], checked)
        self.assertEqual(checked['structure_status'], 'valid', checked)
        self.assertFalse(any(i['severity'] == 'error' for i in checked['issues']), checked)
        # Unavailable electrical/functional checks remain explicit.
        self.assertEqual(checked['status'], 'partial', checked)
        self.assertIn('electrical_validation', checked['checks_unavailable'])

    def test_search_separator_case_variants_find_screen_and_example(self):
        for variants in (('epaper', 'e-paper', 'E_PAPER', ' e paper '),
                         ('eink', 'e-ink', 'E_INK', ' e ink ')):
            expected = None
            for query in variants:
                ids, offset = [], 0
                while True:
                    page = self.catalog.search_catalog(query=query, offset=offset)
                    self.assertTrue(page['ok'], page)
                    ids.extend(e['id'] for e in page['items'])
                    if not page['has_more']:
                        break
                    offset += len(page['items'])
                self.assertTrue({'component:epaper-1in54-bw', 'example:epaper-1in54-uno-hello'} <= set(ids), query)
                if expected is None:
                    expected = ids
                self.assertEqual(ids, expected, query)

    def test_search_indexes_tags_and_summary_independently(self):
        snapshot = copy.deepcopy(self.catalog._snapshot)
        target = next(e for e in snapshot['entries'] if e['id'] == 'component:epaper-1in54-bw')
        target['tags'] = ['tag-only-needle']
        target['summary'] = 'Summary_only needle'
        catalog = Catalog(snapshot)
        for query in ('TAG ONLY NEEDLE', 'summary-only_needle'):
            self.assertEqual([e['id'] for e in catalog.search_catalog(query=query)['items']], [target['id']])

    def test_document_errors_identify_exact_native_fields_and_received_values(self):
        cases = [
            ('/boards/0/boardKind', lambda d: d['boards'][0].pop('boardKind')),
            ('/boards/0/x', lambda d: d['boards'][0].update(x=float('nan'))),
            ('/boards/0/activeFileGroupId', lambda d: d['boards'][0].update(activeFileGroupId='missing')),
            ('/boards/0/languageMode', lambda d: d['boards'][0].update(languageMode='python')),
            ('/components/0/metadataId', lambda d: d['components'][0].pop('metadataId')),
            ('/components/0/properties', lambda d: d['components'][0].pop('properties')),
            ('/components/0/properties', lambda d: d['components'][0].update(properties=[])),
            ('/components/0/id', lambda d: d['components'][0].update(id='esp')),
            ('/wires/0/start/componentId', lambda d: d['wires'][0]['start'].update(componentId='absent')),
            ('/wires/0/end/pinName', lambda d: d['wires'][0]['end'].pop('pinName')),
            ('/wires/0/start', lambda d: d['wires'][0].update(start='esp:18')),
            ('/wires/0/waypoints/0/y', lambda d: d['wires'][0].update(waypoints=[{'x': 0}])),
            ('/activeBoardId', lambda d: d.update(activeBoardId=[])),
            ('/format', lambda d: d.update(format='wokwi')),
            ('/version', lambda d: d.update(version=True)),
            ('/fileGroups/sketch/0/content', lambda d: d['fileGroups']['sketch'][0].update(content=2)),
            ('/boards/0/spiffsFiles/0/contentB64', lambda d: d['boards'][0].update(spiffsFiles=[{'name': 'x', 'contentB64': '!'}])),
            ('/components/0/properties/sourceC', lambda d: d['components'][0]['properties'].update(sourceC=[])),
            ('/folderGroups/sketch/0', lambda d: d.update(folderGroups={'sketch': ['../bad']})),
            ('/components/0/properties/extension', lambda d: d['components'][0]['properties'].update(extension=float('inf'))),
        ]
        for path, mutate in cases:
            with self.subTest(path=path):
                doc = self.assembled()
                mutate(doc)
                self.assert_error(self.store.save_project(document=doc), path)
        doc = self.assembled()
        doc['components'][0]['metadataId'] = 'x' * 1000
        error = self.assert_error(self.store.save_project(document=doc), '/components/0/metadataId')
        self.assertTrue(error['received'].endswith('...'))
        doc = self.board()
        doc['fileGroups']['a/b~c'] = [{'name': '../unsafe', 'content': ''}]
        self.assert_error(self.store.save_project(document=doc), '/fileGroups/a~1b~0c/0/name')
        doc = self.board()
        doc['fileGroups']['sketch'] = [{'name': name, 'content': ''} for name in ('src/main.c', 'lib/main.c')]
        error = self.assert_error(self.store.save_project(document=doc), '/fileGroups/sketch/1/name')
        self.assertEqual(error['received'], '"lib/main.c"')
        self.assertFalse(list(Path(self.store.root).glob('projects/*')))

    def test_quota_errors_include_the_received_value_at_the_real_field(self):
        doc = self.assembled()
        doc['components'][0]['properties']['sourceC'] = 'x' * (256 * 1024 + 1)
        error = self.assert_error(self.store.save_project(document=doc),
                                 '/components/0/properties/sourceC', 'quota_exceeded')
        self.assertTrue(error['received'].startswith('"xxx'))
        self.assertTrue(error['received'].endswith('...'))
        doc = self.board()
        doc['fileGroups']['sketch'][0]['content'] = 'y' * (256 * 1024 + 1)
        self.assert_error(self.store.save_project(document=doc), '/fileGroups/sketch/0/content', 'quota_exceeded')

    def test_save_argument_patch_and_result_validation_errors_remain_actionable(self):
        self.assert_error(self.store.save_project(), '/document')
        self.assert_error(self.store.save_project(document=self.board(), surprise=True), '/surprise')
        self.assert_error(self.store.save_project(document=self.board(), project_id='bad'), '/expected_version')
        self.assert_error(self.store.save_project(document=self.board(), project_id='bad', expected_version='a' * 64), '/project_id')
        saved = self.store.save_project(document=self.assembled())
        base = {'project_id': saved['project_id'], 'expected_version': saved['version']}
        self.assert_error(self.store.save_project(**{**base, 'expected_version': 'bad'}, document=self.board()), '/expected_version')
        for changes, path in [([], '/changes'), ([{'op': 'add', 'path': '/name'}], '/changes/0/op'),
                              ([{'op': 'set', 'path': '/name'}], '/changes/0/value'),
                              ([{'op': 'remove', 'path': '/name', 'value': 1}], '/changes/0/value'),
                              ([{'op': 'remove', 'path': '/wires/99'}], '/changes/0/path'),
                              ([{'op': 'remove', 'path': '/components/0/metadataId'}], '/components/0/metadataId')]:
            self.assert_error(self.store.save_project(**base, changes=changes), path)

    def test_facade_schema_rejection_preserves_native_and_patch_error_details(self):
        doc = self.assembled()
        del doc['components'][0]['metadataId']
        error = _save_schema_error(SimpleNamespace(), {'document': doc})
        self.assertEqual(error.details['path'], '/components/0/metadataId')
        self.assertEqual(error.details['received'], '<missing>')
        doc = self.board()
        doc['boards'][0]['rotation'] = 'north'
        error = _save_schema_error(SimpleNamespace(absolute_path=['document', 'boards', 0, 'rotation'],
                                  instance='north', validator='type', validator_value='number'), {'document': doc})
        self.assertEqual(error.details['path'], '/boards/0/rotation')
        self.assertEqual(error.details['received'], '"north"')
        self.assertIn('number', error.details['expected'])
        args = {'project_id': 'p_' + 'a' * 32, 'expected_version': 'b' * 64,
                'changes': [{'op': 'set', 'path': '/name'}]}
        error = _save_schema_error(SimpleNamespace(absolute_path=['changes', 0], instance=args['changes'][0],
                                  validator='required', validator_value=['value']), args)
        self.assertEqual(error.details['path'], '/changes/0/value')
        self.assertEqual(error.details['received'], '<missing>')
        args['changes'][0] = {'op': 'remove', 'path': '/name', 'value': 1}
        error = _save_schema_error(SimpleNamespace(), args)
        self.assertEqual(error.details['path'], '/changes/0/value')
        self.assertEqual(error.details['received'], '1')

    def test_authoring_inputs_and_errors_satisfy_published_schemas(self):
        doc = self.assembled()
        cases = [({'document': doc}, True)]
        for container, field in [('boards', 'boardKind'), ('boards', 'x'), ('components', 'metadataId'),
                                 ('components', 'properties'), ('wires', 'start')]:
            broken = copy.deepcopy(doc)
            del broken[container][0][field]
            cases.append(({'document': broken}, False))
        broken = copy.deepcopy(doc)
        broken['boards'][0]['languageMode'] = 'python'
        cases.append(({'document': broken}, False))
        errors = [self.store.save_project(document=broken), self.store.save_project()]
        script = """const fs=require('fs'),Ajv=require('ajv');
const {schema,cases,errors}=JSON.parse(fs.readFileSync(0,'utf8')); const ajv=new Ajv({strict:false});
const input=ajv.compile(schema.inputSchema), output=ajv.compile(schema.outputSchema);
for(const [value,want] of cases) if(input(value)!==want) throw Error(JSON.stringify(input.errors));
for(const error of errors) if(!output(error)) throw Error(JSON.stringify(output.errors));
"""
        subprocess.run(['node', '-e', script], input=json.dumps({'schema': TOOL_SCHEMAS['save_project'],
                       'cases': cases, 'errors': errors}).encode(), check=True, timeout=10)
