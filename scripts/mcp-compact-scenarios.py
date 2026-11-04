#!/usr/bin/env python3
"""Deterministic six-tool contract evaluation. No LLM, compiler, HTTP or install.

Run from the repository root: PYTHONPATH=backend python scripts/mcp-compact-scenarios.py
Builds use the existing OwnerQueueAdapter test double and verified fixture files.
Only counts and public scenario names are printed; temporary paths never escape.
"""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from jsonschema import validate
from app.mcp.compact import (BuildService, Catalog, LibraryInventory, OwnerQueueAdapter,
                             ProjectChecker, ProjectStore, TOOL_SCHEMAS, ToolchainInventory)
from app.mcp.compact.projects import canonical

SCENARIOS = (
    ('led-uno', 'arduino-uno', ('led', 'resistor'), (),
     'void setup(){pinMode(13,OUTPUT);}\nvoid loop(){digitalWrite(13,HIGH);delay(500);digitalWrite(13,LOW);delay(500);}\n'),
    ('servo-nano', 'arduino-nano', ('servo',), ('Servo',),
     '#include <Servo.h>\nServo servo;\nvoid setup(){servo.attach(9);servo.write(45);}\nvoid loop(){}\n'),
    ('eink-esp32', 'esp32', ('epaper-1in54-bw',), ('GxEPD2', 'Adafruit GFX Library'),
     '#include <GxEPD2_BW.h>\nGxEPD2_BW<GxEPD2_154_D67,16> display(GxEPD2_154_D67(5,17,16,4));\n'
     'void setup(){display.init();display.setFullWindow();display.firstPage();do{'
     'display.fillScreen(GxEPD_WHITE);display.drawRect(0,0,200,200,GxEPD_BLACK);'
     'display.setCursor(10,40);display.print("Hello Velxio");}while(display.nextPage());}\nvoid loop(){}\n'),
)


class ControlledGate:
    @asynccontextmanager
    async def slot(self, **kwargs):
        yield


class DeterministicClient:
    """Same strict schemas and real catalog/store/check/build services as MCP."""
    def __init__(self, catalog, store, checker, builds):
        self.catalog, self.store, self.checker, self.builds = catalog, store, checker, builds
        self.calls, self.errors, self.signatures = [], 0, Counter()
        self.expected_errors = 0
        self.max_catalog_bytes = 0
        self.reference_pages_followed = 0

    async def call(self, name, *, expect_error=False, **arguments):
        validate(arguments, TOOL_SCHEMAS[name]['inputSchema'])
        self.calls.append(name)
        self.signatures[canonical({'tool': name, 'arguments': arguments})] += 1
        if name in ('search_catalog', 'get_reference'):
            result = getattr(self.catalog, name)(**arguments)
        elif name == 'check_project':
            result = self.checker.check_project(**arguments)
        elif name == 'build_project':
            result = await self.builds.build_project(**arguments)
        else:
            result = getattr(self.store, name)(**arguments)
        validate(result, TOOL_SCHEMAS[name]['outputSchema'])
        if name in ('search_catalog', 'get_reference'):
            self.max_catalog_bytes = max(self.max_catalog_bytes, len(canonical(result)))
            assert len(canonical(result)) <= 24 * 1024
        if expect_error:
            assert result['ok'] is False
            assert {'code', 'path', 'received', 'expected', 'next_action'} <= result['error'].keys()
            self.expected_errors += 1
            return result
        if not result['ok']:
            self.errors += 1
            raise AssertionError(result['error']['code'])
        return result


async def run_scenario(catalog, scenario, from_example=False, named_wiring=False, recover_once=False, paged_references=False):
    name, board_kind, parts, dependencies, code = scenario
    with tempfile.TemporaryDirectory(prefix='compact-contract-') as temporary:
        root = Path(temporary)
        store = ProjectStore(root / 'projects')
        proofs = root / 'proofs'
        proofs.mkdir()
        libraries = {}
        for index, library in enumerate(dependencies):
            path = proofs / (str(index) + '.properties')
            path.write_text('name=' + library + '\nversion=CONTROLLED-TEST\n')
            libraries[library] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        inventory = LibraryInventory(str(proofs), libraries, complete=True)
        checker = ProjectChecker(store, catalog, inventory=inventory, source_root=ROOT)
        fqbn = catalog.get_reference(id='board:' + board_kind)['data']['fqbn']
        member = proofs / 'non-executable-proof.txt'
        member.write_text('CONTROLLED TEST DOUBLE; NOT A COMPILER')
        identity = fqbn + '|arduino'
        manifest = proofs / 'toolchain.json'
        manifest.write_bytes(canonical({'kind': 'toolchain', 'name': identity, 'version': 'CONTROLLED-TEST',
            'test_only': True, 'members': [{'path': member.name, 'sha256': hashlib.sha256(member.read_bytes()).hexdigest()}]}))
        toolchains = ToolchainInventory(str(proofs), {identity: {'path': manifest.name,
            'sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}}, complete=True)
        callbacks = []
        async def compile_double(request, log):
            assert request['test_only'] and request['offline'] and not request['allow_install']
            callbacks.append(request)
            log('CONTROLLED TEST DOUBLE: no compiler or simulator executed\n')
            return {'success': True, 'firmware': b'CONTROLLED TEST DOUBLE FIRMWARE', 'firmware_type': 'bin'}
        builds = BuildService(store, checker, adapter=OwnerQueueAdapter(lambda heavy: ControlledGate(), compile_double,
                              test_only=True, name='deterministic-scenarios-v1'), toolchains=toolchains)
        client = DeterministicClient(catalog, store, checker, builds)
        async def request_reference(**arguments):
            if paged_references:
                arguments['limit'] = 2
            result = await client.call('get_reference', **arguments)
            merged = result['data']
            while result['has_more']:
                request = result['next_request']
                assert request['tool'] == 'get_reference'
                result = await client.call(request['tool'], **request['arguments'])
                client.reference_pages_followed += 1
                # These reviewed templates fit whole top-level field units;
                # never save pointer fragments as if they were a native doc.
                assert 'fragments' not in result
                for key, value in result['data'].items():
                    if key in merged and isinstance(merged[key], list):
                        merged[key].extend(value)
                    else:
                        merged[key] = value
            return {**result, 'data': merged}
        try:
            if from_example:
                query = 'blink' if name == 'led-uno' else 'servo' if name == 'servo-nano' else 'epaper'
                search = await client.call('search_catalog', query=query, kind='example')
                example = next(item for item in search['items'] if item.get('from_example', {}).get('supported'))
                parameters = {'board': board_kind}
                if name == 'led-uno':
                    parameters.update(external_led=True, delay_ms=500)
                elif name == 'servo-nano':
                    parameters.update(angle=45, delay_ms=1000)
                else:
                    parameters.update(text='Hello Velxio', frame=True)
                if recover_once:
                    invalid_parameters = {**parameters, 'pins': {'LED' if name == 'led-uno' else 'PWM' if name == 'servo-nano' else 'CS': 999}}
                    rejected = await client.call('save_project', expect_error=True, from_example=example['id'], parameters=invalid_parameters)
                    assert rejected['error']['path'].startswith('/parameters/pins/')
                saved = await client.call('save_project', from_example=example['id'], parameters=parameters)
                board = {'id': saved['board_id']}
            else:
                search = await client.call('search_catalog', query='e-ink epaper 1.54' if name == 'eink-esp32' else parts[0], kind='component')
                assert 'component:' + parts[0] in [item['id'] for item in search['items']]
                board_reference = await request_reference(id='board:' + board_kind, section='project')
                assert board_reference['execution']['state'] == 'unsupported'
                document = board_reference['data']
                board = document['boards'][0]
                board['libraries'] = list(dependencies)
                for part in parts:
                    reference = await request_reference(id='component:' + part, section='project')
                    template = reference['data']['instance_template']
                    assert template['metadataId'] == part
                    document['components'].append(template)
                    if name == 'eink-esp32':
                        example = reference['data']['example_references'][0]
                        source = await request_reference(id=example, section='code')
                        assert 'GxEPD2' in source['data']['files'][0]['content']
                group = board['activeFileGroupId']
                document['fileGroups'][group] = [{'name': 'sketch.ino', 'content': code}]
                def wire(index, left, pin, right, other_pin):
                    return {'id': 'w' + str(index), 'start': {'componentId': left, 'pinName': pin},
                            'end': {'componentId': right, 'pinName': other_pin}}
                if name == 'led-uno':
                    led, resistor = [item['id'] for item in document['components']]
                    document['wires'] = [wire(1, board['id'], '13', resistor, '1'), wire(2, resistor, '2', led, 'A'), wire(3, led, 'C', board['id'], 'GND.1')]
                elif name == 'servo-nano':
                    servo = document['components'][0]['id']
                    document['wires'] = [wire(i, board['id'], pin, servo, target) for i, (pin, target) in enumerate([('9', 'PWM'), ('5V', 'V+'), ('GND.1', 'GND')])]
                else:
                    epd = document['components'][0]['id']
                    document['wires'] = [wire(i, board['id'], pin, epd, target) for i, (pin, target) in enumerate([
                        ('18', 'SCK'), ('23', 'SDI'), ('5', 'CS'), ('17', 'DC'), ('16', 'RST'), ('4', 'BUSY'), ('3V3', 'VCC'), ('GND', 'GND')])]
                if named_wiring:
                    connections = [f"{w['start']['componentId']}.{w['start']['pinName']} -> {w['end']['componentId']}.{w['end']['pinName']}" for w in document['wires']]
                    document['wires'] = []
                    saved = await client.call('save_project', document=document, connect=connections)
                else:
                    saved = await client.call('save_project', document=document)
            checked = await client.call('check_project', project_id=saved['project_id'], version=saved['version'])
            assert checked['structure_status'] == 'valid', (name, checked['issues'])
            assert not any(item['severity'] == 'error' for item in checked['issues'])
            finished = await client.call('build_project', action='start', project_id=saved['project_id'], version=saved['version'], board_id=board['id'])
            polls = 0
            if finished['state'] == 'running':
                # Only a non-terminal start result needs another tool call.
                await asyncio.gather(*builds.tasks.values())
                finished = await client.call('build_project', action='status', build_id=finished['build_id'])
                polls = 1
            assert finished['state'] == 'done' and finished['success'] and finished['test_only']
            firmware = next(item for item in finished['artifacts'] if item['kind'] == 'firmware')
            await client.call('read_artifact', artifact_id=firmware['id'], length=4096, encoding='base64')
            return {'scenario': name, 'tool_calls': len(client.calls), 'calls_by_tool': dict(Counter(client.calls)),
                    'reference_pages_followed': client.reference_pages_followed, 'max_catalog_response_bytes': client.max_catalog_bytes,
                    'unexpected_errors': client.errors, 'expected_errors': client.expected_errors, 'repeated_identical_calls': sum(count - 1 for count in client.signatures.values()),
                    'build_status_polls': polls, 'controlled_build_callbacks': len(callbacks),
                    'simulation': 'unsupported', 'test_only': True, 'real_compiler_executed': False}
        finally:
            await builds.close()


async def evaluate():
    catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
    return {'method': 'deterministic scripted client; strict six-tool schemas; controlled owner adapter',
            'real_llm_used': False, 'real_compiler_used': False,
            'baseline': [await run_scenario(catalog, scenario) for scenario in SCENARIOS],
            'paged_manual': [await run_scenario(catalog, scenario, named_wiring=True, paged_references=True) for scenario in SCENARIOS],
            'error_recovery': [await run_scenario(catalog, scenario, from_example=True, recover_once=True) for scenario in SCENARIOS],
            'named_wiring': [await run_scenario(catalog, scenario, named_wiring=True) for scenario in SCENARIOS],
            'previous_optimized_calls': {'led-uno': 5, 'servo-nano': 5, 'eink-esp32': 5},
            'scenarios': [await run_scenario(catalog, scenario, from_example=True) for scenario in SCENARIOS]}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(evaluate()), indent=2))
