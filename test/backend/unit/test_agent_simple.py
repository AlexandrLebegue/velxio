"""Deterministic real chat workflows; no model calls or solution recipes."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.agent.runtime import AgentRuntime
from app.agent.simple_tools import CHAT_TOOLS, normalize_chat
from app.agent.workspace import project_revision

EMPTY={'format':'velxio-project','version':1,'boards':[],'components':[],'wires':[],
       'fileGroups':{},'activeBoardId':None}


def wire(a,ap,b,bp):
    return {'start':{'componentId':a,'pinName':ap},'end':{'componentId':b,'pinName':bp}}


class SimpleChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.runtime=AgentRuntime(self.directory.name)
        self.session=self.runtime.create('owner',copy.deepcopy(EMPTY))
        self.commands=[]
        async def editor(session,action,**data):
            self.commands.append((action,copy.deepcopy(data)))
            if action=='validate_circuit':
                document=data['document'];parts={p['id']:p for p in document['boards']+document['components']}
                for item in document['wires']:
                    for side in ('start','end'):
                        endpoint=item[side];part=parts[endpoint['componentId']]
                        key=('board:'+part['boardKind']) if 'boardKind' in part else 'component:'+part['metadataId']
                        valid={p['name'] for p in self.runtime.get_catalog()._entries[key]['pins']}
                        if endpoint['pinName'] not in valid:
                            return {'ok':False,'error':{'code':'pin_invalid','message':'Valid pins: '+', '.join(sorted(valid))}}
                return {'ok':True,'document':document,'revision':project_revision(document)}
            if action=='apply':
                session.browser_revision=data['revision'];return {'ok':True,'applied_revision':data['revision']}
            if action in ('run','observe'):
                return {'ok':True,'state':'running','compiled':True,'confirmed':True,'serial':'ready\n'}
            return {'ok':True,'state':'stopped'}
        self.editor=editor
        self.runtime.browser_command=editor

    async def asyncTearDown(self):
        await self.runtime.close();self.directory.cleanup()

    async def call(self,name,**arguments):
        return await self.runtime.call_tool(self.session,name,arguments)

    async def board(self,kind='arduino-uno',**kwargs):
        result=await self.call('components',board=kind,**kwargs)
        self.assertTrue(result['ok'],result)
        return result

    def source(self):
        return self.session.workspace.work/self.runtime.source_context(self.session)['active_file']

    async def test_empty_project_board_and_batch_have_no_recipe_and_real_pins(self):
        result=await self.board(add=[{'component':'led','id':'red','properties':{'color':'red'}},
                                    {'component':'resistor','id':'r','properties':{'value':'330'}}])
        self.assertEqual(result['added'],['red','r'])
        self.assertEqual([a for a,_ in self.commands],['validate_circuit','apply'])
        self.assertEqual(len(self.session.workspace.document['components']),2)
        self.assertEqual(self.source().read_text(),'void setup() {}\n\nvoid loop() {}\n')
        self.assertIn('A',{p['name'] for p in result['references']['red']['pins']})
        self.assertEqual(result['references']['red']['metadataId'],'led')
        self.assertNotIn('recommended_example',result['references']['red'])

    async def test_empty_run_requires_a_board_and_pure_idf_has_an_idf_source_skeleton(self):
        result=await self.call('run')
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'board_unknown')
        await self.board('esp32',language_mode='espidf')
        self.assertEqual(self.source().name,'main.c')
        self.assertIn('void app_main(void)',self.source().read_text())
        checked=await self.runtime._call_tool(self.session,'check_project',{})
        self.assertEqual(checked['structure_status'],'valid',checked)

    async def test_batch_is_atomic_and_preserves_existing_user_files_on_update_remove(self):
        await self.board(add=[{'component':'led','id':'led'},{'component':'resistor','id':'r'}])
        await self.call('connect',wires=[wire('board','13','r','1'),wire('r','2','led','A')])
        source='// existing user code\r\nvoid setup() {}\r\nvoid loop() {}\r\n'
        self.source().write_bytes(source.encode());header=self.source().parent/'user_hook.h';header.write_bytes(b'#pragma once\r\n')
        before=self.session.workspace.capture();self.commands.clear()
        bad=await self.call('components',add=[{'component':'led','id':'new'},{'component':'DOES-NOT-EXIST'}])
        self.assertFalse(bad['ok']);self.assertEqual(self.session.workspace.capture(),before)
        self.assertEqual(self.commands,[])
        updated=await self.call('components',update=[{'id':'r','properties':{'value':'220'}}])
        self.assertTrue(updated['ok'],updated);self.assertEqual(self.source().read_bytes(),source.encode())
        self.assertEqual(header.read_bytes(),b'#pragma once\r\n')
        removed=await self.call('components',remove=['led'])
        self.assertTrue(removed['ok'],removed)
        self.assertEqual(len(self.session.workspace.document['wires']),1)
        self.assertEqual(self.source().read_bytes(),source.encode())

    async def test_duplicate_ids_and_editor_refusal_do_not_partially_apply(self):
        await self.board();before=self.session.workspace.capture()
        result=await self.call('components',add=[{'component':'led','id':'same'},{'component':'resistor','id':'same'}])
        self.assertFalse(result['ok']);self.assertEqual(self.session.workspace.capture(),before)
        with patch.object(self.runtime,'browser_command',new=AsyncMock(return_value={'ok':False,'error':{'code':'revision_conflict','message':'Manual edit'}})):
            result=await self.call('components',add=[{'component':'led'}])
        self.assertFalse(result['ok']);self.assertEqual(self.session.workspace.capture(),before)

    async def test_circuit_edit_does_not_overwrite_a_native_file_edit_during_editor_validation(self):
        await self.board(add=[{'component':'led','id':'led'}])
        changed=b'// Native write completed concurrently\r\nvoid setup() {}\r\nvoid loop() {}\r\n'
        async def editing(session,action,**data):
            if action=='apply':self.source().write_bytes(changed)
            return await self.editor(session,action,**data)
        self.runtime.browser_command=editing
        result=await self.call('components',update=[{'id':'led','properties':{'color':'green'}}])
        self.assertTrue(result['ok'],result);self.assertEqual(self.source().read_bytes(),changed)

    async def test_connect_batch_invalid_pin_rolls_back_and_reversed_duplicates_are_skipped(self):
        await self.board(add=[{'component':'led','id':'led'},{'component':'resistor','id':'r'}])
        pair=wire('board','13','r','1')
        good=await self.call('connect',wires=[pair,wire('r','1','board','13')])
        self.assertTrue(good['ok'],good);self.assertEqual(good['added_connections'],1)
        self.assertEqual(good['duplicates_skipped'],1)
        before=self.session.workspace.capture()
        bad=await self.call('connect',wires=[wire('r','2','led','A'),wire('led','C','board','BAD')])
        self.assertFalse(bad['ok']);self.assertIn('Valid pins',bad['error']['message'])
        self.assertEqual(self.session.workspace.capture(),before)
        removed=await self.call('connect',remove=good['connection_ids'])
        self.assertTrue(removed['ok']);self.assertEqual(self.session.workspace.document['wires'],[])

    async def test_search_is_paginated_and_returns_pins_without_another_tool(self):
        result=await self.call('search_component',query='LED',limit=1)
        self.assertTrue(result['ok'],result);self.assertEqual(len(result['items']),1)
        self.assertTrue(result['has_more']);self.assertEqual(result['next_offset'],1)
        self.assertIn('pins',result['items'][0]);self.assertNotIn('code',result['items'][0])
        following=await self.call('search_component',query='LED',limit=1,offset=result['next_offset'])
        self.assertNotEqual(result['items'][0]['id'],following['items'][0]['id'])
        self.assertNotIn('example:',json.dumps(result['items']))

    async def test_run_captures_source_checks_and_uses_exactly_one_editor_build_run(self):
        await self.board()
        source='void setup() { Serial.begin(9600); }\nvoid loop() { Serial.println("ready"); delay(100); }\n'
        self.source().write_text(source);self.commands.clear()
        result=await self.call('run')
        self.assertTrue(result['ok'],result);self.assertTrue(result['compilation']['success'])
        self.assertTrue(result['confirmed']);self.assertFalse(result['behavior_verified'])
        runs=[data for action,data in self.commands if action=='run'];self.assertEqual(len(runs),1)
        self.assertEqual(runs[0]['document']['fileGroups']['sketch'][0]['content'],source)
        again=await self.call('run')
        self.assertTrue(again['ok']);self.assertEqual([a for a,_ in self.commands].count('run'),1)
        self.assertEqual(self.commands[-1][0],'observe')

    async def test_broken_source_blocks_run_before_any_compile_and_retains_file(self):
        await self.board();source='// void setup() {} void loop() {}'
        self.source().write_text(source);self.commands.clear()
        result=await self.call('run')
        self.assertFalse(result['ok']);self.assertEqual(result['state'],'invalid')
        self.assertTrue(result['issues']);self.assertEqual(self.commands,[])
        self.assertEqual(self.source().read_text(),source)

    async def test_read_current_state_and_board_swap_preserve_source_and_remap_wires(self):
        await self.board(add=[{'component':'led','id':'led'}])
        await self.call('connect',wires=[wire('board','13','led','A')])
        source='void setup() {}\nvoid loop() { delay(7); }\n';self.source().write_text(source)
        read=await self.call('components');self.assertEqual(read['boards'][0]['boardKind'],'arduino-uno')
        result=await self.call('components',board='esp32',pin_map={'13':'5'})
        self.assertTrue(result['ok'],result);self.assertEqual(result['board']['id'],'board')
        self.assertEqual(self.source().read_text(),source)
        self.assertEqual(self.session.workspace.document['wires'][0]['start']['pinName'],'5')

    async def test_compile_failure_is_never_a_successful_run_even_with_old_loaded_firmware(self):
        await self.board()
        async def failed(session,action,**data):
            if action=='run':return {'ok':False,'state':'blocked','compiled':True,'confirmed':False,
                                    'error':{'code':'compilation_failed','message':'sketch.ino:3: broken source'}}
            return await self.editor(session,action,**data)
        self.runtime.browser_command=failed
        result=await self.call('run')
        self.assertFalse(result['ok']);self.assertFalse(result['compilation']['success'])
        self.assertFalse(result['confirmed'])
        self.assertEqual(self.session.events[-1]['payload']['status'],'error')

    async def test_running_source_changed_during_execution_is_not_a_success(self):
        await self.board()
        async def changed(session,action,**data):
            if action=='run':
                self.source().write_text('void setup() {}\nvoid loop() {delay(17);}\n')
                return {'ok':True,'state':'running','compiled':True,'confirmed':True}
            return await self.editor(session,action,**data)
        self.runtime.browser_command=changed
        result=await self.call('run')
        self.assertFalse(result['ok']);self.assertEqual(result['state'],'stale')
        self.assertFalse(result['confirmed'])

    async def test_pending_simulation_resumes_and_stale_status_cannot_confirm_current_source(self):
        await self.board()
        async def pending(session,action,**data):
            if action=='run':return {'ok':True,'state':'booting','compiled':True,'confirmed':False}
            return await self.editor(session,action,**data)
        self.runtime.browser_command=pending
        result=await self.call('run');self.assertFalse(result['confirmed'])
        self.assertIn('Call run()',result['next_action']);self.assertNotIn('observe_project',result['next_action'])
        self.assertTrue((await self.call('run'))['confirmed'])
        self.source().write_text('void setup() {}\nvoid loop() {delay(2);}\n')
        stale=await self.call('run',action='status');self.assertFalse(stale['ok'])
        self.assertEqual(stale['state'],'not_run')

    async def test_compile_only_resumes_private_job_without_ids_and_reuses_final_truth(self):
        await self.board();await self.runtime._call_tool(self.session,'check_project',{})
        service=self.session.project_service;self.session.compile_request=object();self.session.compile_user='owner'
        calls=[]
        async def build(**arguments):
            calls.append(arguments)
            return {'ok':True,'state':'running' if arguments['action']=='start' else 'done',
                    'success':None if arguments['action']=='start' else True,'build_id':'private-job'}
        with patch('app.api.routes.compile.bind_compact_offline_owner',new=AsyncMock()) as bind,patch.object(service.builds,'build_project',side_effect=build):
            result=await self.call('run',simulate=False,wait_seconds=0)
            self.assertEqual(result['state'],'compiling');self.assertNotIn('build_id',result)
            result=await self.call('run')
            self.assertEqual(result['state'],'compiled');self.assertTrue(result['compilation']['success'])
            self.assertFalse(result['confirmed']);self.assertTrue(result['matches_current_workspace'])
            cached=await self.call('run',simulate=False);self.assertEqual(cached['state'],'compiled')
            self.assertEqual([c['action'] for c in calls],['start','status'])
            bind.assert_awaited_with(self.session.compile_request,'owner')
        self.assertFalse(any(a=='run' for a,_ in self.commands))

    async def test_compile_only_error_preserves_first_diagnostic_and_never_confirms_startup(self):
        await self.board();await self.runtime._call_tool(self.session,'check_project',{})
        service=self.session.project_service;self.session.compile_request=object()
        diagnostic={'file':'sketch.ino','line':3,'message':'Missing declaration','suggestion':'Declare the symbol before use.'}
        async def build(**arguments):
            return {'ok':True,'state':'error','success':False,'build_id':'private-failure',
                    'first_error':diagnostic,'diagnostics':[diagnostic]}
        with patch('app.api.routes.compile.bind_compact_offline_owner',new=AsyncMock()),patch.object(service.builds,'build_project',side_effect=build):
            result=await self.call('run',simulate=False)
        self.assertEqual(result['state'],'error');self.assertFalse(result['compilation']['success'])
        self.assertFalse(result['confirmed']);self.assertEqual(result['first_error'],diagnostic)
        self.assertNotIn('build_id',result);self.assertIsNone(self.session.simple_tools.last_run)
        self.assertEqual(self.session.events[-1]['payload']['status'],'error')

    async def test_esp32_native_epaper_wiring_and_compile_lane_are_preserved(self):
        result=await self.board('esp32',add=[{'component':'epaper-1in54-bw','id':'epd'}])
        board_id=result['board']['id']
        pairs={'CS':'5','DC':'17','RST':'16','BUSY':'4','SCK':'18','SDI':'23','VCC':'3V3','GND':'GND'}
        # Catalog pad names, not named-wiring strings or inferred aliases.
        pins={p['name'] for p in result['references']['epd']['pins']}
        self.assertTrue(set(pairs)<=pins,pins)
        connected=await self.call('connect',wires=[wire(board_id,pin,'epd',role) for role,pin in pairs.items()])
        self.assertTrue(connected['ok'],connected)
        await self.runtime._call_tool(self.session,'check_project',{})
        service=self.session.project_service;self.session.compile_request=object()
        async def build(**arguments):return {'ok':True,'state':'done','success':True,'build_id':'esp-offline'}
        with patch('app.api.routes.compile.bind_compact_offline_owner',new=AsyncMock()),patch.object(service.builds,'build_project',side_effect=build):
            ran=await self.call('run')
        self.assertEqual(ran['state'],'compiled',ran);self.assertEqual(ran['simulation']['state'],'unsupported')
        self.assertFalse(ran['confirmed']);self.assertFalse(any(a=='run' for a,_ in self.commands))

    async def test_display_shortens_paths_without_changing_model_cwd_or_native_source(self):
        await self.board();root=str(self.session.workspace.work.resolve())
        event=self.runtime.emit(self.session,'tool.state',{'call_id':'read','name':'read','status':'completed',
            'title':root,'summary':f'<path>{root.lstrip("/")}</path>\n{root}/group-1/sketch.ino'})
        self.assertEqual(event['payload']['title'],'.')
        self.assertEqual(event['payload']['summary'],'<path>.</path>\ngroup-1/sketch.ino')
        self.assertEqual(self.runtime.source_context(self.session)['cwd'],root)
        self.assertTrue(self.source().exists())

    async def test_real_four_tool_transport_constructs_and_runs_without_hidden_calls(self):
        from fastapi import FastAPI
        import httpx
        from app.agent.tools import create_tools
        app=FastAPI();tools,manager=create_tools(self.runtime);app.mount('/',tools)
        self.session.task=asyncio.create_task(asyncio.Event().wait())
        headers={'Accept':'application/json, text/event-stream','Authorization':'Bearer '+self.session.token}
        async with manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000',headers=headers) as client:
                async def call(name,args):
                    response=await client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
                    self.assertEqual(response.status_code,200,response.text)
                    result=json.loads(response.json()['result']['content'][0]['text'])
                    self.assertTrue(result['ok'],result);return result
                found=await call('search_component',{'query':'resistor','limit':'1'})
                self.assertIn('pins',found['items'][0])
                await call('components',{'board':'arduino-uno','add':json.dumps([{'component':'led','id':'led'},{'component':'resistor','id':'r'}])})
                await call('connect',{'wires':json.dumps([wire('board','13','r','1'),wire('r','2','led','A'),wire('led','C','board','GND.1')])})
                self.source().write_text('void setup() {pinMode(13, OUTPUT);}\nvoid loop() {digitalWrite(13,HIGH);}\n')
                result=await call('run',{})
                self.assertTrue(result['checks']['structure_status']=='valid')
                self.assertTrue(result['compilation']['success']);self.assertTrue(result['confirmed'])
                names={e['payload']['name'] for e in self.session.events if e['type']=='tool.state'}
                self.assertEqual(names,{'search_component','components','connect','run'})

    def test_only_lossless_complete_transport_forms_are_accepted(self):
        from jsonschema import validate,ValidationError
        args=normalize_chat('components',{'add':'[{"component":"resistor","x":"0","properties":{"value":"330"}}]'})
        validate(args,CHAT_TOOLS['components'][1]);self.assertEqual(args['add'][0]['x'],0)
        self.assertEqual(args['add'][0]['properties']['value'],'330')
        validate(normalize_chat('run',{'simulate':'false','wait_seconds':'0'}),CHAT_TOOLS['run'][1])
        with self.assertRaises(ValidationError):validate(normalize_chat('components',{'add':'[{"component":"led"'}),CHAT_TOOLS['components'][1])


if __name__=='__main__':unittest.main()
