#!/usr/bin/env python3
"""Actual chat API/OpenCode evaluation, with an explicit backend editor adapter.

Real model and genuine REST-owner compilation; no browser/simulation claims.
Sequential only. Provider secrets are read from existing config into memory;
private chat settings and raw evidence must remain outside Git.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
spec = importlib.util.spec_from_file_location('chat_bench_core', ROOT / 'scripts/mcp-bench-qwen.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
ab = bench.ab
VALIDATIONS = {
    'V1': 'Sur cette Arduino Nano, conserve le câblage et mon fichier user_note.h, ainsi que son appel dans setup. Change seulement le clignotement pour avoir deux flashes par seconde, avec des durées allumée et éteinte égales. Compile le projet et rapporte le résultat réel.',
    'V2': 'Crée un montage Arduino Uno où un potentiomètre à glissière commande un servomoteur de 0 à 180 degrés sur toute sa course. Enregistre le montage câblé, compile-le et dis-moi ce qui a réellement réussi.',
}


def prompt_proof(messages, prompt):
    """Separate real user instructions from automatic harness compaction parts."""
    users = [m for m in messages if m.get('info', {}).get('role') == 'user']
    texts = [p for m in users for p in m.get('parts', []) if p.get('type') == 'text']
    supplied = [p['text'] for p in texts if not p.get('synthetic')]
    return {'single_exact_prompt': len(users) == 1 and [p['text'] for p in texts] == [prompt],
            'single_exact_user_prompt': supplied == [prompt],
            'synthetic_continuations': sum(bool(p.get('synthetic')) for p in texts),
            'automatic_compactions': sum(p.get('type') == 'compaction'
                                         for m in users for p in m.get('parts', []))}


def external_file_accesses(parts, workspace):
    """Include relative traversal as well as absolute paths in isolation checks."""
    workspace = Path(workspace).resolve()
    outside = []
    for part in parts:
        if part.get('type') != 'tool' or part.get('tool', '').startswith('velxio_'):
            continue
        state = part.get('state', {})
        if state.get('status') != 'completed':
            continue
        arguments = state.get('input', {})
        for key in ('filePath', 'path'):
            value = arguments.get(key)
            if isinstance(value, str) and not (workspace / value).resolve().is_relative_to(workspace):
                outside.append(arguments)
                break
    return outside


def initial_document(case, catalog):
    if case == 'V1':
        from app.mcp.compact.examples import instantiate
        document, _ = instantiate(catalog, 'example:blink-led', {'board':'arduino-nano','external_led':True,
                                  'resistance_ohms':330,'led_color':'green','delay_ms':1000})
        board = document['boards'][0]
        files = document['fileGroups'][board['activeFileGroupId']]
        files[0]['content'] = '#include "user_note.h"\n' + files[0]['content'].replace('void setup() {','void setup() {\n  Serial.begin(9600);\n  userNote();',1)
        files.append({'name':'user_note.h','content':'#pragma once\n#include <Arduino.h>\ninline void userNote() { Serial.println("KEEP_USER_HOOK"); }\n'})
        return document
    return {'format':'velxio-project','version':1,'boards':[],'components':[],'wires':[],'fileGroups':{},'activeBoardId':None}


class EditorAdapter:
    """Models only editor protocol/real native pads; never execution or pixels."""
    def __init__(self, catalog, document):
        self.catalog, self.document = catalog, copy.deepcopy(document)

    def describe(self, kind, key, properties=None):
        reference = self.catalog.get_reference(id=kind + ':' + key, section='overview')
        if not reference.get('ok'):
            return reference
        entry = self.catalog._entries[kind + ':' + key]
        pins = entry.get('pins')
        for property, value in (properties or {}).items():
            pins = entry.get('_pin_variants', {}).get(property, {}).get(str(value), {}).get('pins', pins)
        return {'ok': True, 'pins': pins, 'attrs': entry.get('attrs', []),
                'defaults': reference['data'].get('defaults', {}),
                'pin_source': 'packaged real web-component pins; backend editor adapter'}

    def validate(self, document):
        from app.agent.workspace import checked_document
        from app.agent.settings import AgentError
        value = checked_document(document)
        parts = {p['id']: p for p in value['boards'] + value['components']}
        for wire in value['wires']:
            for side in ('start', 'end'):
                endpoint = wire[side];part = parts[endpoint['componentId']]
                kind = 'board' if 'boardKind' in part else 'component'
                key = part.get('boardKind', part.get('metadataId'))
                info = self.describe(kind, key, part.get('properties'))
                pins = info.get('pins')
                if not isinstance(pins, list):
                    raise AgentError('pins_unavailable', 'No verified pins for ' + key)
                names = {p['name'] for p in pins}
                aliases = self.catalog._entries[kind + ':' + key].get('_pin_aliases', {})
                pin = endpoint['pinName']
                canonical = pin if pin in names else aliases.get(pin)
                if canonical not in names:
                    canonical = next((name for name in sorted(names) if pin == name.split('.')[0]), None)
                if canonical not in names:
                    raise AgentError('pin_unknown', f"{key}: invalid pin {pin}; valid pins: {', '.join(sorted(names))}")
                endpoint['pinName'] = canonical
        return value

    def command(self, command):
        from app.agent.workspace import project_revision
        if command['expected_revision'] != project_revision(self.document):
            return {'ok': False, 'error': {'code': 'revision_conflict', 'message': 'Editor source changed'}}
        action = command['action']
        if action == 'describe_part':
            return self.describe(command['kind'], command['part_id'])
        if action == 'inspect_project':
            return {'ok': True, 'available_boards': [], 'pinouts': {
                p['id']: self.describe('board' if 'boardKind' in p else 'component', p.get('boardKind', p.get('metadataId')), p.get('properties'))
                for p in self.document['boards'] + self.document['components']}}
        if action in ('validate_circuit', 'apply', 'create'):
            value = self.validate(command['document']);revision = project_revision(value)
            if action == 'validate_circuit':
                return {'ok': True, 'document': value, 'revision': revision, 'validated': True}
            self.document = value
            return {'ok': True, 'applied_revision': revision, 'revision': revision, 'validated': True}
        return {'ok': False, 'confirmed': False, 'error': {'code': 'unsupported',
                'message': 'Backend editor adapter has no simulator. build_project compiles; no runtime observation is available.'}}


async def editor_stream(client, sid, browser_id, editor, directory, ready):
    async with client.stream('GET', f'/api/agent/sessions/{sid}/events', params={'browser_id': browser_id}, timeout=None) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith(': connected'):
                ready.set()
            if not line.startswith('data: '):
                continue
            event = json.loads(line[6:])
            with (directory / 'events.jsonl').open('a') as out:
                out.write(ab.canonical(event) + '\n')
            if event['type'] == 'browser.command':
                try:
                    result = editor.command(event['payload'])
                except (ValueError, KeyError, TypeError) as exc:
                    result = {'ok': False, 'error': {'code': getattr(exc, 'code', 'adapter_error'), 'message': str(exc)}}
                acknowledged = await client.post(f'/api/agent/sessions/{sid}/browser-result', json={
                    'command_id': event['payload']['command_id'], 'browser_id': browser_id, 'result': result})
                acknowledged.raise_for_status()


def independent(document, directory, cli, cache):
    board = next(b for b in document['boards'] if b['id'] == document['activeBoardId'])
    files = document['fileGroups'][board['activeFileGroupId']]
    sketch = directory / 'independent/sketch';sketch.mkdir(parents=True)
    for file in files:
        target = sketch / file['name'];target.parent.mkdir(parents=True, exist_ok=True);target.write_text(file['content'])
    fqbn = {'arduino-uno': 'arduino:avr:uno', 'arduino-nano': 'arduino:avr:nano'}[board['boardKind']]
    result = subprocess.run([str(cli), 'compile', '--fqbn', fqbn, '--build-path', str(directory / 'independent/build'), str(sketch)],
                            env=ab.toolchain_env(cache, cli), capture_output=True, text=True, timeout=300)
    (directory / 'independent/compile.log').write_text(result.stdout + result.stderr)
    return result.returncode == 0 and (directory / 'independent/build/sketch.ino.hex').is_file()


def suite_document(spec, catalog):
    """Only user-owned initial files, never a generated answer to the task."""
    if 'initial' not in spec:
        return initial_document('', catalog)
    initial = spec['initial']
    document = copy.deepcopy(catalog.get_reference(id='board:'+initial['board'], section='project')['data'])
    board = next(b for b in document['boards'] if b['id']==document['activeBoardId'])
    document['fileGroups'][board['activeFileGroupId']] = copy.deepcopy(initial['files'])
    return document


def general_facts(document, spec, source):
    board = next((b for b in document['boards'] if b['id']==document['activeBoardId']), {})
    return {'expected':spec['expected'], 'board_kind':board.get('boardKind'),
            'component_counts':dict(Counter(p['metadataId'] for p in document['components'])),
            'native_wires':document['wires'], 'properties':{p['id']:p.get('properties',{}) for p in document['components']},
            'source_multiline':'\n' in source, 'manual_review_required':True}


async def main(args):
    # Same lock as MCP evaluation: this service is single-user.
    lock = (Path.home() / '.cache/velxio-mcp-ab-qwen.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    root = args.evidence.resolve();root.mkdir(parents=True, exist_ok=True);root.chmod(0o700)
    revision = ab.command(['git', '-C', ROOT, 'rev-parse', 'HEAD']).stdout.strip()
    suite = json.loads(args.suite.read_text()) if args.suite else None
    ab.write_json(root/'protocol.json', {'revision':revision,'model':'qwen3.8-27b','mode':'real-chat-api/backend-editor-adapter',
                 'single_prompt':True,'sequential':True,'timeout_seconds':720,'max_steps':40,'max_output_tokens':8192,
                 'suite_sha256':hashlib.sha256(args.suite.read_bytes()).hexdigest() if args.suite else None})
    os.environ.update(ab.toolchain_env(args.toolchain, args.arduino_cli))
    os.environ['MCP_COMPACT_INVENTORY'] = str(args.inventory.resolve())
    os.environ['MCP_COMPACT_AVR_ENABLED'] = '1'
    import httpx
    import uvicorn
    from fastapi import FastAPI
    from app.agent.runtime import AgentRuntime
    from app.agent.opencode import OpenCodeAdapter
    from app.agent.tools import create_tools
    from app.agent.workspace import project_revision
    from app.api.routes import agent as route, compile as compile_route
    from app.agent.settings import ConnectionSettings
    from app.mcp.compact.facade import CompactRuntime

    adapters = []
    def factory(*params):
        adapter = OpenCodeAdapter(*params);adapters.append(adapter);return adapter
    runtime = AgentRuntime(root / 'private', adapter_factory=factory)
    route.runtime = runtime
    tools, manager = create_tools(runtime)
    active = {'directory': None}
    class TraceTools:
        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or scope['method'] != 'POST':
                return await tools(scope, receive, send)
            incoming, outgoing = bytearray(), bytearray();started = time.monotonic()
            async def read():
                message = await receive();incoming.extend(message.get('body', b''));return message
            async def write(message):
                outgoing.extend(message.get('body', b''));await send(message)
            try:
                await tools(scope, read, write)
            finally:
                try:
                    request = json.loads(incoming)
                    if request.get('method') == 'tools/call' and active['directory']:
                        response = json.loads(outgoing);result = response.get('result', {})
                        texts = [p['text'] for p in result.get('content', []) if p.get('type') == 'text']
                        output = json.loads(texts[0]) if texts else {'ok': False, 'error': {'code': 'transport'}}
                        event = {**request['params'], 'output': output, 'seconds': round(time.monotonic()-started, 3)}
                        with (active['directory']/'tools.jsonl').open('a') as out:out.write(ab.canonical(event)+'\n')
                except (ValueError, KeyError, TypeError):
                    pass
    @asynccontextmanager
    async def lifespan(app):
        async with compile_route._compact_offline_lifespan(app), manager.run():
            try:yield
            finally:await runtime.close()
    app = FastAPI(lifespan=lifespan)
    app.state.compact_runtime = CompactRuntime(app, inventory_file=args.inventory)
    app.include_router(route.router, prefix='/api/agent')
    app.mount('/api/agent/tools', TraceTools())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0));port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():await serving
        await asyncio.sleep(.05)
    config = json.loads((Path.home() / '.config/opencode/opencode.json').read_text())['provider']['hyperqwen']
    options = config['options'];key = options.get('apiKey')
    # Some global providers use an environment credential reference.
    if isinstance(key, str) and key.startswith('{env:') and key.endswith('}'):
        key = os.environ[key[5:-1]]
    settings = ConnectionSettings(base_url=options['baseURL'], api_key=key, model='qwen3.8-27b', max_steps=40, timeout_seconds=720)
    rows = []
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=30) as client:
            # Same settings/session/message routes as AgentPanel, no test prompt suffix.
            response = await client.put('/api/agent/settings', json=settings.model_dump());response.raise_for_status()
            for case in args.cases.split(','):
                if (root / 'STOP').exists():break
                directory = root / case;directory.mkdir();active['directory'] = directory
                spec = suite['cases'][case] if suite else None
                document = suite_document(spec, runtime.get_catalog()) if spec else initial_document(case, runtime.get_catalog())
                initial = copy.deepcopy(document)
                response = await client.post('/api/agent/sessions', json={'document': document});response.raise_for_status();sid = response.json()['id']
                editor = EditorAdapter(runtime.get_catalog(), document);ready = asyncio.Event()
                stream = asyncio.create_task(editor_stream(client, sid, 'backend-bench-editor', editor, directory, ready))
                try:
                    await asyncio.wait_for(ready.wait(), 10)
                    prompt = spec['prompt'] if spec else VALIDATIONS[case] if case in VALIDATIONS else bench.PROMPTS[case]
                    print('START', case, flush=True);started = time.monotonic()
                    response = await client.post(f'/api/agent/sessions/{sid}/messages', json={'message': prompt, 'request_id': 'single-prompt'});response.raise_for_status()
                    session = next(s for s in runtime.sessions.values() if s.id == sid)
                    await asyncio.wait_for(asyncio.shield(session.task), 735)
                    elapsed = round(time.monotonic()-started, 2)
                    # AgentPanel refreshes and applies the workspace on a
                    # terminal event, including direct native file edits.
                    response = await client.get(f'/api/agent/sessions/{sid}/workspace');response.raise_for_status()
                    refreshed = response.json()
                    if project_revision(editor.document) != refreshed['revision']:
                        editor.command({'action':'apply','expected_revision':project_revision(editor.document),'document':refreshed['document']})
                    capture_error = None
                    try:
                        document = session.workspace.capture()
                    except (ValueError, OSError, UnicodeError) as exc:
                        capture_error = {'code':getattr(exc,'code','workspace_error'),'message':str(exc)[:1000]}
                        document = copy.deepcopy(session.workspace.document)
                    ab.write_json(directory/'project.json', document)
                    board = next((b for b in document['boards'] if b['id'] == document['activeBoardId']), None)
                    source = '\n'.join(f['content'] for f in document['fileGroups'].get(board['activeFileGroupId'], [])) if board else ''
                    compile_error = None
                    compiled = False
                    if board and capture_error is None:
                        try:
                            compiled = await asyncio.to_thread(independent, document, directory, args.arduino_cli, args.toolchain)
                        except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
                            compile_error = {'code':type(exc).__name__,'message':str(exc)[:1000]}
                    calls = ab.json_lines(directory/'tools.jsonl');errors = Counter(c['output'].get('error', {}).get('code', 'unknown') for c in calls if c['output'].get('ok') is False)
                    loops = Counter(ab.canonical({'name':c['name'],'arguments':c['arguments']}) for c in calls)
                    adapter = next((a for a in reversed(adapters) if a.root.parent == session.workspace.root), None)
                    tokens = Counter();proof = {}
                    if adapter:
                        # Use the exact running chat adapter's read-only API.
                        # Global CLI exports do not share its isolated config.
                        if adapter.client is not None:
                            messages = await adapter.messages()
                        else:
                            import sqlite3
                            db = next((adapter.root/'data').rglob('opencode.db'))
                            with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as connection:
                                messages = [{'info':json.loads(data),'parts':[json.loads(p[0]) for p in connection.execute('select data from part where message_id=? order by time_created',(mid,))]}
                                            for mid,data in connection.execute('select id,data from message where session_id=? order by time_created',(adapter.session_id,))]
                        ab.write_json(directory/'session-export.json', {'messages':messages})
                        proof = {**prompt_proof(messages, prompt),
                                 'models':sorted({m['info'].get('modelID') for m in messages if m['info'].get('role')=='assistant'}),
                                 'providers':sorted({m['info'].get('providerID') for m in messages if m['info'].get('role')=='assistant'}),
                                 'cwd_verified':all(m['info'].get('path',{}).get('cwd')==str(session.workspace.work.resolve()) for m in messages if m['info'].get('role')=='assistant'),
                                 'cwd':str(session.workspace.work.resolve())}
                        for m in messages:
                            if m.get('info',{}).get('role')=='assistant':
                                for key,value in m['info'].get('tokens',{}).items():
                                    if isinstance(value,(int,float)):tokens[key]+=value
                    row = {'case':case,'calls':len(calls),'errors':dict(errors),'error_count':sum(errors.values()),
                           'loops':[v for v in loops.values() if v>=3],'seconds':elapsed,'tokens':dict(tokens),
                           'compile_ok':compiled,'editor_matches':project_revision(editor.document)==project_revision(document),
                           'workspace_capture_error':capture_error,'independent_compile_error':compile_error,
                           'check_called':any(c['name']=='check_project' or c['name']=='run' and c['output'].get('checks',{}).get('structure_status') in ('valid','invalid') for c in calls),
                           'final_build_read':any((c['name']=='build_project' and c['output'].get('state')=='done' and c['output'].get('success') is True or
                               c['name']=='run' and c['output'].get('compilation',{}).get('success') is True and c['output'].get('matches_current_workspace') is True)
                               and c['output'].get('workspace_revision')==session.workspace.revision for c in calls),
                           'facts':general_facts(document,spec,source) if spec else bench.facts(document,case,source),
                           'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                           'revision':session.workspace.revision,'proof':proof,'strict_success':False,'manual_review_required':True,
                           'conclusion':session.messages[-1] if session.messages else None,'turns':session.turns}
                    row['code_revision'] = revision
                    row['failed_builds'] = len({c['output'].get('build_id', 'response-'+str(index))
                                               for index,c in enumerate(calls)
                                               if c['name']=='build_project' and c['output'].get('success') is False or
                                               c['name']=='run' and c['output'].get('compilation',{}).get('success') is False})
                    parts = [p for m in messages for p in m.get('parts', [])] if adapter else []
                    row['harness_tool_errors'] = sum(p.get('type')=='tool' and p.get('state',{}).get('status')=='error' for p in parts)
                    row['generation_limits'] = sum(m.get('info',{}).get('finish')=='length' for m in messages) if adapter else 0
                    row['file_tool_calls'] = sum(p.get('type')=='tool' and not p.get('tool','').startswith('velxio_') for p in parts)
                    row['recipe_calls'] = [c['arguments'] for c in calls if c['name']=='save_project' and 'from_example' in c['arguments']]
                    row['external_file_accesses'] = external_file_accesses(parts, session.workspace.work)
                    if spec and spec.get('preserve'):
                        current_files={f['name']:f['content'] for files in document['fileGroups'].values() for f in files}
                        original_files={f['name']:f['content'] for files in initial['fileGroups'].values() for f in files}
                        row['user_files_preserved']=all(current_files.get(name)==original_files[name] for name in spec['preserve']['files'])
                        row['user_calls_preserved']=all(token in source for token in spec['preserve']['source_tokens'])
                    if case == 'V1':
                        original = next(f['content'] for files in initial['fileGroups'].values() for f in files if f['name']=='user_note.h')
                        preserved = any(f['name']=='user_note.h' and f['content']==original for files in document['fileGroups'].values() for f in files)
                        row['user_helper_preserved'] = preserved and 'userNote();' in source
                    ab.write_json(directory/'result.json',row);rows.append(row);ab.write_json(root/'summary.json',rows)
                    print('DONE',case,ab.canonical({k:row[k] for k in ('calls','errors','loops','seconds','compile_ok','editor_matches','final_build_read','proof')}),flush=True)
                    if not proof.get('single_exact_prompt') and not proof.get('models'):
                        print('STOP: harness failed before a model request; repair configuration before retrying.', flush=True)
                        break
                finally:
                    stream.cancel();await asyncio.gather(stream,return_exceptions=True)
                    if 'session' in locals():await runtime.stop(session)
            ab.write_json(root/'summary.json',rows)
    finally:
        server.should_exit = True
        await serving
        ab.write_json(root/'cleanup.json',{'server_stopped':serving.done(),'harnesses_stopped':all(a.process is None or a.process.returncode is not None for a in adapters)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--cases')
    parser.add_argument('--suite', type=Path, help='Frozen held-out prompt/requirements JSON; never supplied as model context')
    parser.add_argument('--arduino-cli', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    args = parser.parse_args()
    allowed = set(json.loads(args.suite.read_text())['cases']) if args.suite else {'B1','B2','B3','B4','B5','V1','V2'}
    import re
    if any(not re.fullmatch(r'[A-Z][0-9]{1,2}',case) for case in allowed):
        parser.error('Case labels must be one letter followed by one or two digits')
    if not args.cases:
        args.cases = ','.join(json.loads(args.suite.read_text())['cases']) if args.suite else 'B1,B2,B3,B4,B5'
    unknown = set(args.cases.split(',')) - allowed
    if unknown:
        parser.error('This chat bench supports AVR cases B1..B5 and V1/V2 only; ESP32 requires a separate IDF evaluation.')
    asyncio.run(main(args))
