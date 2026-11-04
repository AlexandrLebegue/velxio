import copy
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.agent.reconcile import merge_documents
from app.agent.runtime import AgentRuntime
from app.agent.settings import AgentError
from app.agent.workspace import project_revision

ROOT=Path(__file__).resolve().parents[3]

def document():
    return {'format':'velxio-project','version':1,'boards':[{'id':'board','boardKind':'arduino-uno','activeFileGroupId':'g','x':0,'y':0}],
            'components':[{'id':'led','metadataId':'led','x':1,'y':1,'properties':{'color':'red'}}],
            'wires':[],'fileGroups':{'g':[{'name':'sketch.ino','content':'void setup() {}\nvoid loop() {}\n'}]},'activeBoardId':'board'}


class MergeTests(unittest.TestCase):
    def test_shared_cross_language_cases(self):
        for case in json.loads((ROOT/'test/fixtures/agent-merge-cases.json').read_text()):
            with self.subTest(case=case['name']):
                args=[case[k] for k in ('base','proposed','local')];before=copy.deepcopy(args)
                result,conflicts=merge_documents(*args,prefer_local=True)
                self.assertEqual(result,case['expected']);self.assertEqual(conflicts,case['conflicts'])
                self.assertEqual(args,before)
                if conflicts:
                    with self.assertRaises(AgentError) as caught:merge_documents(*args)
                    self.assertEqual(caught.exception.code,'edit_conflict')
                else:self.assertEqual(merge_documents(*args)[0],case['expected'])

    def test_stale_revision_sync_merges_manual_properties_and_native_file_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=AgentRuntime(folder);session=runtime.create('owner',document());base=session.workspace.revision
            path=session.workspace.work/'group-1/sketch.ino'
            source='void setup() {}\nvoid loop() { delay(7); }\n';path.write_text(source)
            session.workspace.commit()
            manual=document();manual['components'][0]['properties']['color']='green'
            result=runtime.sync(session,manual,base)
            self.assertTrue(result['synchronization']['automatic'])
            self.assertEqual(result['document']['components'][0]['properties']['color'],'green')
            self.assertEqual(path.read_text(),source)
            self.assertNotEqual(result['editor_revision'],result['revision'])
            ack=runtime.sync(session,result['document'],result['revision'],result['revision'])
            self.assertEqual(ack['editor_revision'],ack['revision'])

    def test_overlapping_manual_source_wins_and_agent_draft_remains_in_history(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=AgentRuntime(folder);session=runtime.create('owner',document());base=session.workspace.revision
            path=session.workspace.work/'group-1/sketch.ino';path.write_text('void setup() {}\nvoid loop() { delay(1); }\n')
            session.workspace.commit();draft=session.workspace.revision
            manual=document();manual['fileGroups']['g'][0]['content']='void setup() {}\nvoid loop() { delay(2); }\n'
            result=runtime.sync(session,manual,draft,base)
            self.assertEqual(path.read_text(),manual['fileGroups']['g'][0]['content'])
            self.assertTrue(result['synchronization']['overlaps'])
            saved=json.loads((session.workspace.root/'revisions'/(draft+'.vlx')).read_text())
            self.assertIn('delay(1)',saved['fileGroups']['g'][0]['content'])

    def test_automatic_compile_manifest_update_does_not_discard_late_native_source(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=AgentRuntime(folder);session=runtime.create('owner',document())
            path=session.workspace.work/'group-1/sketch.ino';source='void setup() {}\nvoid loop() { delay(9); }\n';path.write_text(source)
            editor=document();editor['boards'][0]['libraries']=['Servo']
            runtime.adopt_editor(session,editor,project_revision(editor))
            self.assertEqual(path.read_text(),source)
            self.assertEqual(session.workspace.document['boards'][0]['libraries'],['Servo'])
            self.assertEqual(session.browser_revision,project_revision(editor))

    def test_unknown_snapshot_cannot_force_a_stale_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=AgentRuntime(folder);session=runtime.create('owner',document())
            with self.assertRaises(AgentError):runtime.sync(session,document(),'a'*64)


class EditorTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_editor_snapshot_is_not_limited_to_model_tool_response_size(self):
        import httpx
        from fastapi import FastAPI
        from app.api.routes import agent
        with tempfile.TemporaryDirectory() as folder:
            runtime=AgentRuntime(folder);app=FastAPI();app.include_router(agent.router,prefix='/api/agent')
            with patch.object(agent,'runtime',runtime):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000') as client:
                    created=await client.post('/api/agent/sessions',json={'document':document()})
                    session=runtime.sessions[created.json()['id']];session.browser_id='test-editor-browser'
                    command='a'*32;future=asyncio.get_running_loop().create_future();session.pending[command]=future
                    snapshot=document();snapshot['fileGroups']['g'][0]['content']='// '+('x'*65536)+'\nvoid setup() {}\nvoid loop() {}\n'
                    response=await client.post('/api/agent/sessions/'+session.id+'/browser-result',json={
                        'command_id':command,'browser_id':session.browser_id,'result':{'ok':True,'document':snapshot}})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(future.result()['document'],snapshot)
            await runtime.close()
