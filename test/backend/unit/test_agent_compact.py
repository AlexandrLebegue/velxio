"""Chat uses the shared compact core with session identities kept server-side."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.agent.runtime import AgentRuntime
from app.agent.workspace import project_revision


EMPTY = {'format': 'velxio-project', 'version': 1, 'boards': [], 'components': [],
         'wires': [], 'fileGroups': {}, 'activeBoardId': None}


class ChatCompactTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = AgentRuntime(self.directory.name)
        self.session = self.runtime.create('owner', copy.deepcopy(EMPTY))
        self.commands = []

        async def editor(session, action, **data):
            self.commands.append((action, data))
            if action == 'validate_circuit':
                return {'ok': True, 'document': data['document'], 'revision': project_revision(data['document'])}
            if action == 'apply':
                session.browser_revision = data['revision']
                return {'ok': True, 'applied_revision': data['revision']}
            return {'ok': True}
        self.runtime.browser_command = editor

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def test_recipes_apply_to_the_editor_and_materialize_the_exact_current_source(self):
        cases = [
            ('example:blink-led', {'external_led': True, 'resistance_ohms': 220, 'delay_ms': 500}, 'arduino-uno'),
            ('example:button-led', {'mode': 'toggle'}, 'arduino-uno'),
            ('example:uno-servo', {'board': 'arduino-nano', 'control': 'potentiometer'}, 'arduino-nano'),
            ('example:uno-hcsr04', {'display': 'lcd1602-i2c', 'alarm': 'buzzer', 'threshold': 20}, 'arduino-uno'),
            ('example:uno-dht22', {'display': 'ssd1306', 'alarm': 'led', 'threshold': 28}, 'arduino-uno'),
            ('example:epaper-1in54-uno-hello', {'board': 'esp32', 'text': 'Hello World', 'align': 'center'}, 'esp32'),
        ]
        for example, parameters, board in cases:
            with self.subTest(example=example):
                saved = await self.runtime.call_tool(self.session, 'save_project', {'from_example': example, 'parameters': parameters})
                self.assertTrue(saved['ok'], saved)
                self.assertNotIn('project_id', saved)
                self.assertEqual(saved['workspace']['cwd'], str(self.session.workspace.work.resolve()))
                path = self.session.workspace.work / saved['workspace']['active_file']
                self.assertTrue(path.is_file())
                doc = self.session.workspace.capture()
                native = next(b for b in doc['boards'] if b['id'] == doc['activeBoardId'])
                self.assertEqual(native['boardKind'], board)
                self.assertEqual(path.read_text(), doc['fileGroups'][native['activeFileGroupId']][0]['content'])
                checked = await self.runtime.call_tool(self.session, 'check_project', {})
                self.assertTrue(checked['ok'], checked)
                self.assertEqual(checked['structure_status'], 'valid', checked)
                self.assertNotIn('project_id', checked)
                self.assertEqual(self.commands[-2][0], 'validate_circuit')
                self.assertEqual(self.commands[-1][0], 'apply')

    async def test_file_edits_are_captured_without_an_id_and_broken_source_is_refused(self):
        await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:blink-led'})
        path = self.session.workspace.work / self.runtime.source_context(self.session)['active_file']
        source = '// Exact source\nvoid setup() { Serial.begin(9600); Serial.println("Hello"); }\nvoid loop() {}\n'
        path.write_text(source)
        saved = await self.runtime.call_tool(self.session, 'save_project', {})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(path.read_text(), source)
        path.write_text('// All code lost: void setup() {} void loop() {}')
        checked = await self.runtime.call_tool(self.session, 'check_project', {})
        self.assertEqual(checked['structure_status'], 'invalid', checked)
        self.assertTrue(any(issue['severity']=='error' and issue.get('file')=='sketch.ino' for issue in checked['issues']), checked)
        with patch('app.api.routes.compile.bind_compact_offline_owner', new=AsyncMock()) as bind:
            result = await self.runtime.call_tool(self.session, 'build_project', {})
            self.assertFalse(result['ok'])
            bind.assert_not_awaited()  # no authenticated REST request was supplied

    async def test_rejected_editor_candidate_preserves_source_and_current_binding(self):
        saved = await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:blink-led'})
        self.assertTrue(saved['ok'])
        before = self.session.workspace.capture()
        binding = dict(self.session.project_service.current)
        async def reject(session, action, **data):
            return {'ok': False, 'error': {'code': 'revision_conflict', 'message': 'Manual editor edit preserved'}}
        self.runtime.browser_command = reject
        result = await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:uno-servo'})
        self.assertFalse(result['ok'])
        self.assertEqual(self.session.workspace.capture(), before)
        self.assertEqual(self.session.project_service.current, binding)

    async def test_a_rejected_source_update_does_not_poison_the_next_save(self):
        await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:blink-led'})
        original = self.runtime.browser_command
        async def reject(session, action, **data):
            return {'ok': False, 'error': {'code': 'revision_conflict', 'message': 'Manual edit preserved'}}
        self.runtime.browser_command = reject
        result = await self.runtime.call_tool(self.session, 'save_project', {'sketch': 'void setup() {}\nvoid loop() { delay(10); }\n'})
        self.assertFalse(result['ok'])
        self.runtime.browser_command = original
        next_save = await self.runtime.call_tool(self.session, 'save_project', {})
        self.assertTrue(next_save['ok'], next_save)

    async def test_another_conversation_cannot_select_the_first_project(self):
        await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:blink-led'})
        other = self.runtime.create('other', self.session.workspace.capture())
        identity = self.session.project_service.current
        result = await self.runtime.call_tool(other, 'check_project', {'project_id': identity['project_id'], 'version': identity['version']})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'revision_conflict')

    async def test_plain_source_can_create_an_empty_workspace_and_preserves_quotes(self):
        source = '// Literal text\nvoid setup() { Serial.begin(9600); Serial.println("Hello"); }\nvoid loop() {}\n'
        saved = await self.runtime.call_tool(self.session, 'save_project', {'sketch': source, 'board': 'arduino-nano'})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual((self.session.workspace.work / saved['workspace']['active_file']).read_text(), source)
        self.assertEqual(self.session.workspace.document['boards'][0]['boardKind'], 'arduino-nano')

    async def test_plain_source_round_trip_preserves_crlf_and_literal_escapes(self):
        source = '// UTF-8: écran\r\nvoid setup() { Serial.begin(9600); Serial.println("quote \\n"); }\r\nvoid loop() {}\r\n'
        saved = await self.runtime.call_tool(self.session, 'save_project', {'sketch':source})
        self.assertTrue(saved['ok'], saved)
        path = self.session.workspace.work / saved['workspace']['active_file']
        self.assertEqual(path.read_bytes().decode('utf-8'), source)
        document = self.session.workspace.capture()
        board = document['boards'][0]
        self.assertEqual(document['fileGroups'][board['activeFileGroupId']][0]['content'], source)

    async def test_starter_context_is_derived_from_shared_recipes_without_reading_ids(self):
        from app.mcp.compact.examples import RECIPES, recipe_metadata
        context = await self.runtime.project_context(self.session)
        starters = {entry['id']:entry for entry in context['starter_examples']}
        self.assertEqual(set(starters), set(RECIPES))
        for key in starters:
            self.assertEqual(starters[key]['parameters'], recipe_metadata(key)['parameters'])
        saved = await self.runtime.call_tool(self.session, 'save_project', {'from_example':'example:blink-led','parameters':{'external_led':True,'resistance_ohms':330}})
        self.assertEqual(saved['project']['board'], 'arduino-uno')
        self.assertEqual(saved['project']['connection_count'], 3)
        self.assertEqual(next(p['properties']['value'] for p in saved['project']['components'] if p['metadataId']=='resistor'), '330')
        checked = await self.runtime.call_tool(self.session, 'check_project', {})
        self.assertTrue(checked['issues_truncated'])
        self.assertGreater(checked['issue_count'], len(checked['issues']))
        self.assertIn('attribute_default_type_unknown', checked['informational_codes'])

    async def test_blink_rate_is_reported_from_the_shared_generated_source(self):
        saved = await self.runtime.call_tool(self.session, 'save_project', {'from_example':'example:blink-led',
                                            'parameters':{'board':'arduino-nano','frequency_hz':'1'}})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(saved['generated_behavior']['frequency_hz'], 1)
        source = (self.session.workspace.work / saved['workspace']['active_file']).read_text()
        self.assertEqual(source.count('delay(500);'), 2)
        phased = await self.runtime.call_tool(self.session, 'save_project', {'from_example':'example:blink-led',
                                              'parameters':{'delay_ms':1000}})
        self.assertEqual(phased['generated_behavior']['frequency_hz'], 0.5)

    async def test_a_finished_old_build_is_never_relabelled_as_the_current_source(self):
        await self.runtime.call_tool(self.session, 'save_project', {'from_example': 'example:blink-led'})
        service = self.session.project_service
        self.session.compile_request = object()
        self.session.compile_user = 'authenticated-user'
        old = {}
        async def controlled_build(**arguments):
            if arguments['action'] == 'start':
                old.update(project_id=arguments['project_id'], version=arguments['version'])
            return {'ok': True, 'state': 'done', 'success': True, 'build_id': 'controlled-test-only', **old}
        with patch('app.api.routes.compile.bind_compact_offline_owner', new=AsyncMock()) as bind, patch.object(service.builds, 'build_project', side_effect=controlled_build):
            started = await self.runtime.call_tool(self.session, 'build_project', {})
            bind.assert_awaited_with(self.session.compile_request, 'authenticated-user')
            self.assertTrue(started['matches_current_workspace'])
            path = self.session.workspace.work / self.runtime.source_context(self.session)['active_file']
            path.write_text(path.read_text().replace('delay(1000)', 'delay(100)'))
            status = await self.runtime.call_tool(self.session, 'build_project', {'action': 'status', 'build_id': 'controlled-test-only'})
            self.assertEqual(status['workspace_revision'], started['workspace_revision'])
            self.assertFalse(status['matches_current_workspace'])
            self.assertNotEqual(self.session.workspace.revision, started['workspace_revision'])

    async def test_existing_workspace_with_a_local_header_survives_check_and_file_edits(self):
        from app.mcp.compact.examples import instantiate
        doc, _ = instantiate(self.runtime.get_catalog(), 'example:blink-led', {'board':'arduino-nano'})
        group = doc['boards'][0]['activeFileGroupId']
        doc['fileGroups'][group][0]['content'] = '#include "user_note.h"\n' + doc['fileGroups'][group][0]['content']
        header = '#pragma once\ninline int userValue() { return 7; }\n'
        doc['fileGroups'][group].append({'name':'user_note.h','content':header})
        other = self.runtime.create('header-owner', doc)
        path = other.workspace.work / self.runtime.source_context(other)['active_file']
        path.write_text(path.read_text().replace('delay(1000)', 'delay(250)'))
        checked = await self.runtime.call_tool(other, 'check_project', {})
        self.assertEqual(checked['structure_status'], 'valid', checked)
        self.assertEqual((path.parent/'user_note.h').read_text(), header)
        self.assertIn('delay(250)', other.workspace.document['fileGroups'][group][0]['content'])

    async def test_a_failed_build_is_an_error_step_even_with_a_successful_rpc(self):
        result = {'ok': True, 'state': 'error', 'success': False, 'first_error': {'file': 'sketch.ino', 'line': 4, 'message': 'controlled compile failure', 'suggestion': 'Fix line 4'}}
        with patch.object(self.runtime, '_call_tool', new=AsyncMock(return_value=result)):
            await self.runtime.call_tool(self.session, 'build_project', {})
        step = self.session.events[-1]['payload']
        self.assertEqual(step['status'], 'error')
        self.assertIn('controlled compile failure', step['summary'])

    async def test_shared_tools_are_exposed_without_ids_and_all_errors_have_repair_fields(self):
        from fastapi import FastAPI
        import httpx
        from app.agent.tools import create_tools
        app = FastAPI()
        tools, manager = create_tools(self.runtime)
        app.mount('/', tools)
        self.session.task = asyncio.create_task(asyncio.Event().wait())
        async with manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
                headers = {'Accept': 'application/json, text/event-stream', 'Authorization': 'Bearer ' + self.session.token}
                response = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'chat-contract-test','version':'1'}}})
                self.assertEqual(response.status_code, 200, response.text)
                response = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
                offered = {item['name']:item for item in response.json()['result']['tools']}
                from app.mcp.compact import TOOL_SCHEMAS
                self.assertIn('query', offered['search_catalog']['inputSchema']['required'])
                self.assertNotIn('query', TOOL_SCHEMAS['search_catalog']['inputSchema'].get('required', []))
                self.assertNotIn('update_circuit', offered)
                for index, name in enumerate(('search_catalog','get_reference','save_project','check_project','build_project','read_artifact'), 3):
                    self.assertIn(name, offered)
                    for key in ('project_id','version','expected_version'):
                        self.assertNotIn(key, offered[name]['inputSchema']['properties'])
                    response = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':index,'method':'tools/call','params':{'name':name,'arguments':{'unexpected':True}}})
                    result = json.loads(response.json()['result']['content'][0]['text'])
                    self.assertFalse(result['ok'], result)
                    for key in ('code','path','received','expected','next_action'):
                        self.assertIn(key, result['error'], result)
                    self.assertEqual(self.session.events[-1]['payload']['name'], name)
                    self.assertEqual(self.session.events[-1]['payload']['status'], 'error')


if __name__ == '__main__':
    unittest.main()
