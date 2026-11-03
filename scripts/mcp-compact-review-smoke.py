#!/usr/bin/env python3
"""Real app lifespan + SDK/ASGI JSON-RPC; optional build ONLY through active REST owner.

Manager executes in an isolated image, no production mounts. No fake compiler,
HTTP socket, service control, firmware fixture, setup or install is used here.
"""
import argparse
import asyncio
import base64
from collections import deque
from contextlib import contextmanager, redirect_stdout
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time

PROOF_OUTPUT = sys.stdout
TOOLS = {'search_catalog', 'get_reference', 'save_project', 'check_project', 'build_project', 'read_artifact'}


@contextmanager
def proof_stdout():
    """CLI process only: preserve a private proof FD, route FD1 to FD2 until exit.

    redirect_stdout alone misses inherited subprocess FDs and native writes.
    FD1 deliberately stays on stderr after this context, including atexit/C
    buffer flushes; the private proof descriptor is non-inheritable.
    """
    global PROOF_OUTPUT
    sys.stdout.flush()
    sys.stderr.flush()
    previous = PROOF_OUTPUT
    with os.fdopen(os.dup(1), 'w', encoding='utf-8', buffering=1) as proof:
        os.dup2(2, 1)
        PROOF_OUTPUT = proof
        try:
            with redirect_stdout(sys.stderr):
                yield
        finally:
            proof.flush()
            sys.stderr.flush()
            PROOF_OUTPUT = previous


def exception_failure(error):
    """Bounded exception graph: groups, explicit causes and implicit contexts.

    Frames contain only file/line/function, no source text or locals. Each
    exception is <=2 KiB of compact ASCII JSON; at most eight are traversed.
    """
    def clip(value, budget):
        text = str(value)
        truncated = len(text) > 2048
        text = text[:2048]
        while len(json.dumps(text, ensure_ascii=True).encode('ascii')) > budget:
            text = text[:len(text) // 2]
            truncated = True
        return text, truncated

    records, seen = [], set()
    truncated, shared = False, False
    def visit(exc, parent, relation):
        nonlocal truncated, shared
        if id(exc) in seen:
            shared = True
            return
        if len(records) >= 8:
            truncated = True
            return
        seen.add(id(exc))
        index = len(records)
        message, cut = clip(exc, 900)
        kind, cut_kind = clip(type(exc).__qualname__, 120)
        frames = deque(maxlen=3)
        frame_count = 0
        trace = exc.__traceback__
        while trace is not None:
            code = trace.tb_frame.f_code
            frame, cut_frame = clip(f'{code.co_filename}:{trace.tb_lineno}:{code.co_name}', 256)
            cut |= cut_frame
            frames.append(frame)
            frame_count += 1
            trace = trace.tb_next
        record = {'index':index, 'parent':parent, 'relation':relation, 'type':kind,
                  'message':message, 'frames':list(frames),
                  'truncated':cut or cut_kind or frame_count > 3}
        while len(json.dumps(record, ensure_ascii=True, separators=(',', ':')).encode('ascii')) > 2048:
            record['truncated'] = True
            if record['frames']:
                record['frames'].pop(0)
            else:
                record['message'] = record['message'][:len(record['message']) // 2]
        records.append(record)
        if isinstance(exc, BaseExceptionGroup):
            if len(exc.exceptions) > 8:
                truncated = True
            for child_index, child in enumerate(exc.exceptions[:8]):
                if len(records) >= 8:
                    truncated = True
                    break
                visit(child, index, f'group[{child_index}]')
        if exc.__cause__ is not None:
            visit(exc.__cause__, index, '__cause__')
        if exc.__context__ is not None:
            visit(exc.__context__, index, '__context__')
    visit(error, None, 'root')
    return {'type':records[0]['type'], 'message':records[0]['message'],
            'exceptions':records, 'truncated':truncated or any(r['truncated'] for r in records),
            'shared_or_cyclic':shared, 'limits':{'exceptions':8, 'json_bytes_each':2048, 'frames_each':3}}


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review-root', required=True, type=Path)
    p.add_argument('--app-root', required=True, type=Path, help='Directory containing app/, observed by manager')
    p.add_argument('--source-root', required=True, type=Path, help='Policy snapshot containing backend/app/services')
    p.add_argument('--inventory', required=True, type=Path)
    p.add_argument('--project', required=True, type=Path, help='Reviewed native .vlx; never synthesized by smoke')
    p.add_argument('--board-id', required=True)
    p.add_argument('--build', action='store_true', help='Explicit real compiler authorization in isolated image')
    p.add_argument('--status-seconds', type=int, default=120, choices=range(1, 601), metavar='1..600')
    p.add_argument('--max-polls', type=int, default=120, choices=range(1, 301), metavar='1..300')
    return p.parse_args(argv)


async def run(args):
    if os.environ.get('MCP_REVIEW_ISOLATED') != '1':
        raise ValueError('MCP_REVIEW_ISOLATED=1 required; never point this script at production')
    paths = (args.review_root, args.app_root, args.source_root, args.inventory, args.project)
    if not all(path.is_absolute() and '..' not in path.parts for path in paths):
        raise ValueError('All paths must be explicit absolute paths without ..')
    root = args.review_root.resolve()
    if not any(parent in root.parents for parent in (Path('/tmp'), Path('/review'))):
        raise ValueError('Review root must be below /tmp or /review inside the isolated image')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (root / 'smoke-proof.json').exists() or (root / 'store').exists():
        raise ValueError('Existing proof/store retained; choose a fresh review root')
    with args.project.open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Input project exceeds 2 MiB')
    project = json.loads(raw)
    # Must be set before importing app.main and creating its CompactRuntime.
    os.environ['MCP_COMPACT_DATA'] = str(root / 'store')
    os.environ['MCP_COMPACT_SOURCE_ROOT'] = str(args.source_root)
    os.environ['MCP_COMPACT_INVENTORY'] = str(args.inventory)
    os.environ['DATA_DIR'] = str(root / 'runtime-data')
    sys.path.insert(0, str(args.app_root))
    proof = {'kind':'real-ASGI-MCP-smoke', 'pid':os.getpid(), 'real_sdk':False,
        'project_input_sha256':hashlib.sha256(raw).hexdigest(), 'build_requested':args.build,
        'events':[], 'artifacts':[], 'completed':False}
    def publish():
        text = json.dumps(proof, sort_keys=True, indent=2) + '\n'
        if len(text.encode()) > 256 * 1024:
            raise ValueError('Proof exceeds 256 KiB; existing proof retained')
        temporary = root / 'smoke-proof.tmp'
        with temporary.open('w') as out:
            out.write(text); out.flush(); os.fsync(out.fileno())
        temporary.replace(root / 'smoke-proof.json')
    headers = {'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-03-26'}
    counter = 0
    async def rpc(client, method, params, notification=False, timeout=30):
        nonlocal counter
        counter += 1
        body = {'jsonrpc':'2.0', 'method':method, 'params':params}
        if not notification: body['id'] = counter
        response = await asyncio.wait_for(client.post('/mcp', headers=headers, json=body), timeout=timeout)
        if response.status_code not in ((200, 202, 204) if notification else (200,)):
            raise RuntimeError('MCP HTTP ' + str(response.status_code) + ': ' + response.text[:400])
        if notification: return None
        doc = response.json()
        if 'error' in doc: raise RuntimeError('JSON-RPC error: ' + json.dumps(doc['error'])[:500])
        return doc['result']
    async def call(client, name, params, timeout=30):
        result = await rpc(client, 'tools/call', {'name':name, 'arguments':params}, timeout=timeout)
        if result.get('isError'): raise RuntimeError('MCP tool error: ' + json.dumps(result)[:500])
        payload = json.loads(next(c['text'] for c in result['content'] if c['type'] == 'text'))
        if not payload.get('ok'): raise RuntimeError(name + ': ' + json.dumps(payload)[:800])
        return payload
    async def artifact(client, artifact_id, expected_hash=None):
        if not isinstance(artifact_id, str) or not re.fullmatch(r'a_[0-9a-f]{32}', artifact_id):
            raise ValueError('Invalid opaque artifact ID')
        offset, size, digest = 0, 0, hashlib.sha256()
        destination = root / ('artifact-' + artifact_id + '.bin')
        with destination.open('xb') as output:
            for _ in range(3000):  # >32 MiB at 12 KiB; still bounded.
                part = await call(client, 'read_artifact', {'artifact_id':artifact_id, 'offset':offset, 'length':12288, 'encoding':'base64'})
                data = base64.b64decode(part['data'], validate=True)
                if len(data) > 12288 or size + len(data) > 32 * 1024 * 1024:
                    raise ValueError('Artifact quota exceeded')
                digest.update(data); output.write(data); size += len(data)
                if part['eof']:
                    if size != part['total_bytes'] or digest.hexdigest() != part['sha256'] or expected_hash is not None and digest.hexdigest() != expected_hash:
                        raise ValueError('Artifact hash/size mismatch')
                    proof['artifacts'].append({'id':artifact_id, 'size_bytes':size, 'sha256':digest.hexdigest(), 'file':str(destination)})
                    publish(); return destination
                if part['next_offset'] != size or size <= offset:
                    raise ValueError('Artifact made no progress')
                offset = size
            raise ValueError('Artifact pagination quota exceeded')
    publish()
    try:
        with args.inventory.open('rb') as stream:
            inventory_raw = stream.read(1024 * 1024 + 1)
        if len(inventory_raw) > 1024 * 1024:
            raise ValueError('Inventory exceeds 1 MiB')
        proof['inventory_sha256'] = hashlib.sha256(inventory_raw).hexdigest()
        import httpx
        from app.main import app
        from app.api.routes import compile as route
        from importlib.metadata import version
        proof['real_sdk'] = True
        proof['versions'] = {name:version(name) for name in ('mcp', 'fastapi', 'httpx')}
        publish()
        async with app.router.lifespan_context(app):
            owner = route._COMPACT_OFFLINE_OWNER
            if owner is None or owner.test_only or not owner.active or owner.loop is not asyncio.get_running_loop() or owner.pid != os.getpid():
                raise RuntimeError('Genuine active same-process REST owner is required')
            proof['owner'] = {'pid':owner.pid, 'test_only':owner.test_only, 'blockers':owner.production_blockers}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost', timeout=30) as client:
                proof['initialize'] = await rpc(client, 'initialize', {'protocolVersion':'2025-03-26', 'capabilities':{}, 'clientInfo':{'name':'manager-real-isolated-smoke','version':'1'}})
                await rpc(client, 'notifications/initialized', {}, notification=True)
                listed = await rpc(client, 'tools/list', {})
                if {t['name'] for t in listed['tools']} != TOOLS or len(listed['tools']) != 6:
                    raise ValueError('Expected exactly six compact tools')
                proof['tools'] = sorted(TOOLS)
                search = await call(client, 'search_catalog', {})
                if len(search['items']) != 5: raise ValueError('Expected five default results')
                proof['search'] = {'count':len(search['items']), 'revision':search['revision']}
                saved = await call(client, 'save_project', {'document':project})
                proof['save'] = saved; publish()
                restored = await artifact(client, saved['project_artifact_id'], saved['version'])
                if json.loads(restored.read_bytes()) != project: raise ValueError('Native project roundtrip differs')
                checked = await call(client, 'check_project', {'project_id':saved['project_id'], 'version':saved['version']})
                proof['check'] = checked; publish()
                await artifact(client, checked['diagnostic_artifact_id'], checked['diagnostic_artifact_sha256'])
                if checked['structure_status'] != 'valid': raise ValueError('Structural check invalid; no build attempted')
                if args.build:
                    status = await call(client, 'build_project', {'action':'start', 'project_id':saved['project_id'], 'version':saved['version'], 'board_id':args.board_id})
                    deadline = time.monotonic() + args.status_seconds
                    polls = 0
                    while True:
                        proof['build'] = status
                        proof['events'].append({'poll':polls, 'state':status['state']})
                        publish()
                        if status.get('test_only') is not False: raise ValueError('A test-only build is not a real smoke')
                        if status['state'] in ('done', 'error', 'interrupted'): break
                        remaining = deadline - time.monotonic()
                        if polls >= args.max_polls or remaining <= 0:
                            proof['status_wait_expired'] = True; publish(); break
                        await asyncio.sleep(min(1, remaining))
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            proof['status_wait_expired'] = True; publish(); break
                        try:
                            status = await call(client, 'build_project', {'action':'status', 'build_id':status['build_id']}, timeout=min(30, remaining))
                        except asyncio.TimeoutError:
                            proof['status_wait_expired'] = True; publish(); break
                        polls += 1
                    if status['state'] in ('done', 'error', 'interrupted'):
                        for item in status['artifacts']:
                            await artifact(client, item['id'], item['sha256'])
                        if status['state'] != 'done' or status['success'] is not True:
                            raise ValueError('Real build failed; inspect saved logs/proof')
                    else:
                        # Publish BEFORE lifespan drain: no cancel/release of the
                        # shared compiler to manufacture a bounded success.
                        proof['events'].append({'phase':'status_bound_reached_draining_real_owner'})
                        publish()
                        print(json.dumps({'proof':str(root / 'smoke-proof.json'), 'status_wait_expired':True, 'draining':True}), flush=True, file=PROOF_OUTPUT)
            proof['events'].append({'phase':'lifespan_draining'}); publish()
        proof['completed'] = not proof.get('status_wait_expired', False)
        proof['owner_drained'] = True; publish()
        print(json.dumps(proof, sort_keys=True), flush=True, file=PROOF_OUTPUT)
        return 0 if proof['completed'] else 3
    except Exception as exc:
        proof['failure'] = exception_failure(exc)
        publish(); print(json.dumps(proof, sort_keys=True), flush=True, file=PROOF_OUTPUT); return 1


if __name__ == '__main__':
    # Process-level redirection also covers child/native startup and exit writes.
    with proof_stdout():
        try:
            result = asyncio.run(run(arguments()))
        except Exception as exc:
            # Input/preflight errors before a proof file exists still emit JSON.
            print(json.dumps({'completed':False, 'failure':exception_failure(exc)}, sort_keys=True),
                  flush=True, file=PROOF_OUTPUT)
            result = 1
    sys.exit(result)
