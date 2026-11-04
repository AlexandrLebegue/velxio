#!/usr/bin/env python3
"""Sequential, isolated A/B measurement of unchanged compact MCP revisions.

Requires the user's existing OpenCode provider, installed Python dependencies
and local Arduino tools. Never installs, contacts production, patches MCP code,
retries a model prompt, or writes credentials. Raw evidence stays outside Git.

Example (the provider is inherited, not copied):
  /path/to/python scripts/mcp-ab-qwen.py run --arduino-cli /path/to/arduino-cli \
    --toolchain /path/to/existing/cache --deadline-minutes 80
Use `serve` only through `run`. `summarize` and `audit` never contact a model.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REVISIONS = {'A': 'f11eef9', 'B': 'f9e3591e'}
MODEL = 'hyperqwen/qwen3.8-27b'
AGENTS = "# Task\nComplete the user's requested Velxio project. Use only the velxio MCP tools.\n"
PROMPTS = {
    'S1': 'Create and save a Velxio project with an Arduino Uno, one external LED and one 220-ohm series resistor. Make the external LED blink at 1 Hz (500 ms on, 500 ms off). Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.',
    'S2': 'Create and save a Velxio project with an Arduino Nano and a servo motor. Repeatedly sweep the servo smoothly from 0 to 180 degrees and back to 0 degrees. Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.',
    'S3': 'Create and save a Velxio project with an ESP32 DevKit and a 1.54-inch black-and-white e-paper display. Display exactly "Hello World" centered on the screen. Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.',
}


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n')
    tmp.replace(path)


def json_lines(path):
    result = []
    if Path(path).exists():
        for line in Path(path).read_text(errors='replace').splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def command(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, text=True, capture_output=True, **kwargs)


def toolchain_env(root, cli):
    env = dict(os.environ)
    for part, key in [('data', 'DATA'), ('downloads', 'DOWNLOADS'), ('user', 'USER')]:
        env['ARDUINO_DIRECTORIES_' + key] = str(root / part)
    env['PATH'] = str(cli.parent) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
    return env


def request(port, route, value=None):
    body = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}' + route, body, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def serve(args):
    # Import ONLY from the selected pristine worktree. This is instrumentation
    # around its real facade/owner, not another implementation of the tools.
    sys.path.insert(0, str(args.worktree / 'backend'))
    import uvicorn
    from fastapi import FastAPI
    from app.api.routes import compile as route
    from app.mcp.compact.facade import create_facade
    from app.mcp.compact.contracts import TOOL_SCHEMAS
    from app.services.espidf_compiler import espidf_compiler
    active = {'run': None, 'store': None}

    @asynccontextmanager
    async def lifespan(app):
        async with route._compact_offline_lifespan(app), mcp_lifespan():
            yield

    app = FastAPI(lifespan=lifespan)
    transport, mcp_lifespan, runtime = create_facade(
        app, root=args.evidence / 'unused-store', source_root=args.worktree,
        inventory_file=getattr(args, 'inventory', None) or args.evidence / 'absent-inventory.json')
    app.state.compact_runtime = runtime

    @app.get('/bench/health')
    async def health():
        owner = route._COMPACT_OFFLINE_OWNER
        return {'revision': command(['git', '-C', args.worktree, 'rev-parse', 'HEAD']).stdout.strip(),
                'idf_available': espidf_compiler.available,
                'owner_active': bool(owner and owner.active),
                'owner_blockers': owner.production_blockers if owner else ['owner_missing'],
                'tool_count': len(TOOL_SCHEMAS),
                'schema_sha256': hashlib.sha256(canonical(TOOL_SCHEMAS).encode()).hexdigest()}

    @app.post('/bench/reset')
    async def reset(body: dict):
        label = body['run']
        if not re.fullmatch(r'(?:S[123]-[AB]-[12]|P[0-9]+-B[1-6]|V[12])', label):
            raise ValueError('Invalid run label')
        await runtime.close()
        runtime.services.clear()
        runtime.quota = None
        runtime.closing = False
        runtime.root = args.evidence / label / 'store'
        active.update(run=label, store=str(runtime.root))
        return {'run': label, 'store': str(runtime.root)}

    app.mount('/', transport)

    class Trace:
        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or scope['path'] != '/mcp' or scope['method'] != 'POST':
                return await app(scope, receive, send)
            incoming, outgoing = bytearray(), bytearray()
            started = time.monotonic()
            async def traced_receive():
                message = await receive()
                incoming.extend(message.get('body', b''))
                return message
            async def traced_send(message):
                outgoing.extend(message.get('body', b''))
                await send(message)
            failure = None
            try:
                await app(scope, traced_receive, traced_send)
            except Exception as exc:
                failure = type(exc).__name__
                raise
            finally:
                try:
                    call = json.loads(incoming)
                    if call.get('method') == 'tools/call' and active['run']:
                        response = json.loads(outgoing) if outgoing else {}
                        payload = response.get('result', {})
                        content = payload.get('content', [])
                        texts = [item['text'] for item in content if item.get('type') == 'text']
                        try:
                            output = json.loads(texts[0]) if texts else payload
                        except (ValueError, TypeError):
                            output = {'transport_error': texts[:1]}
                        event = {'rpc_id': call.get('id'), **call['params'], 'output': output,
                                 'rpc_error': response.get('error'), 'isError': payload.get('isError', False),
                                 'elapsed': round(time.monotonic() - started, 4), 'exception': failure}
                        path = args.evidence / active['run'] / 'mcp.jsonl'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with path.open('a') as stream:
                            stream.write(canonical(event) + '\n')
                except (ValueError, KeyError, TypeError):
                    pass

    uvicorn.run(Trace(), host='127.0.0.1', port=args.port, log_level='warning', access_log=False)


def resolve_constants(source):
    constants = {}
    for name, value in re.findall(r'#define\s+(\w+)\s+(\d+)\b', source):
        constants[name] = int(value)
    for name, value in re.findall(r'(?:const\s+)?(?:unsigned\s+)?(?:int|long|uint\d+_t|byte)\s+(\w+)\s*=\s*(\d+)\s*;', source):
        constants[name] = int(value)
    def resolve(value):
        value = value.strip()
        return int(value) if value.isdigit() else constants.get(value)
    return constants, resolve


def circuit_facts(doc, scenario, source):
    # Independent read of the immutable circuit, not check_project's verdict.
    boards = doc.get('boards', [])
    components = doc.get('components', [])
    active = next((b for b in boards if b['id'] == doc.get('activeBoardId')), boards[0] if boards else {})
    bid = active.get('id')
    kind = active.get('boardKind')
    parents = {}
    def pin(name):
        name = str(name).upper()
        if name.startswith('GND'):
            return 'GND'
        return {'RX2': '16', 'TX2': '17', '3.3V': '3V3'}.get(name, re.sub(r'^(?:D|GPIO)(\d+)$', r'\1', name))
    def key(obj, name):
        return obj, pin(name)
    def find(node):
        parents.setdefault(node, node)
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node
    for wire in doc.get('wires', []):
        left, right = [key(wire[side]['componentId'], wire[side]['pinName']) for side in ('start', 'end')]
        parents[find(left)] = find(right)
    def linked(a, ap, b, bp):
        return find(key(a, ap)) == find(key(b, bp))
    def parts(name):
        return [c for c in components if (c.get('metadataId', '').removeprefix('component:').removeprefix('wokwi-') == name or
                name == 'resistor' and c.get('metadataId', '').startswith('resistor-'))]
    constants, resolve = resolve_constants(source)
    facts = {'board_kind': kind, 'board_count': len(boards), 'wire_count': len(doc.get('wires', [])),
             'component_kinds': [c.get('metadataId') for c in components], 'constants': constants}
    proper_board = kind == {'S1': 'arduino-uno', 'S2': 'arduino-nano', 'S3': 'esp32'}[scenario]
    if scenario == 'S1':
        leds, resistors = parts('led'), parts('resistor')
        facts['resistor_values'] = [c.get('properties', {}).get('value') for c in resistors]
        gpio = [str(resolve(value)) for value in re.findall(r'digitalWrite\s*\(\s*(\w+)\s*,', source) if resolve(value) is not None]
        series = False
        resistor_ok = False
        for led in leds:
            for resistor in resistors:
                value = str(resistor.get('properties', {}).get('value', '')).lower().replace(' ', '').replace('ohms', '').replace('ohm', '').replace('Ω', '')
                resistor_ok |= value in ('220', '220.0', '220r', '0.22k')
                for a, b in [('1', '2'), ('2', '1')]:
                    for drive in gpio:
                        series |= (linked(bid, drive, resistor['id'], a) and linked(resistor['id'], b, led['id'], 'A') and linked(led['id'], 'C', bid, 'GND') or
                                   linked(bid, drive, led['id'], 'A') and linked(led['id'], 'C', resistor['id'], a) and linked(resistor['id'], b, bid, 'GND'))
        delays = [resolve(v) for v in re.findall(r'delay\s*\(\s*(\w+)\s*\)', source)]
        facts.update(series_path=series, resistor_220=resistor_ok, digital_write_pins=gpio, delays=delays,
                     wiring_candidate=proper_board and len(leds) == 1 and len(resistors) == 1 and series and resistor_ok,
                     sketch_candidate=delays.count(500) >= 2 and 'HIGH' in source and 'LOW' in source)
    elif scenario == 'S2':
        servos = parts('servo')
        attach = [resolve(v) for v in re.findall(r'\.attach\s*\(\s*(\w+)', source)]
        good = any(linked(s['id'], 'V+', bid, '5V') and linked(s['id'], 'GND', bid, 'GND') and
                   any(p is not None and linked(s['id'], 'PWM', bid, str(p)) for p in attach) for s in servos)
        facts.update(servo_attach_pins=attach, wiring_candidate=proper_board and len(servos) == 1 and good,
                     sketch_candidate=bool(re.search(r'\b180\b', source) and re.search(r'\b0\b', source) and '.write(' in source and ('++' in source or '+=' in source) and ('--' in source or '-=' in source)))
    else:
        panels = [c for c in components if c.get('metadataId', '').startswith('epaper-')]
        controls = re.findall(r'GxEPD2_\w+\s*\(\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\)', source)
        pins = [[resolve(v) for v in values] for values in controls]
        good = False
        for panel in panels:
            common = all(linked(panel['id'], role, bid, board_pin) for role, board_pin in [('VCC', '3V3'), ('GND', 'GND'), ('SCK', '18'), ('SDI', '23')])
            good |= common and any(None not in values and len(set(values)) == 4 and all(linked(panel['id'], role, bid, str(value)) for role, value in zip(('CS', 'DC', 'RST', 'BUSY'), values)) for values in pins)
        facts.update(epaper_control_pins=pins, hello_world='Hello World' in source,
                     centering_candidate='getTextBounds' in source and bool(re.search(r'(?:width\s*\(\)|\b200\b)[\s\S]{0,120}/\s*2', source)),
                     wiring_candidate=proper_board and len(panels) == 1 and good,
                     sketch_candidate='Hello World' in source and 'getTextBounds' in source and '.firstPage(' in source and '.nextPage(' in source)
    return facts


def audit(args):
    run = args.run_dir
    calls = json_lines(run / 'mcp.jsonl')
    saves = [c for c in calls if c['name'] == 'save_project' and c.get('output', {}).get('ok')]
    result = {'has_saved_project': bool(saves), 'compile_ok': False, 'compile_status': 'no_project',
              'manual_review_required': True, 'esp32_excluded': args.scenario == 'S3'}
    if not saves:
        write_json(run / 'audit.json', result)
        return result
    events = json_lines(run / 'opencode.jsonl')
    texts = [e.get('part', {}).get('text', '') for e in events if e.get('type') == 'text' and e.get('part', {}).get('text', '').strip()]
    conclusion = texts[-1] if texts else ''
    saved_ids = {call['output']['project_id'] for call in saves}
    declared = next((project for project in re.findall(r'p_[0-9a-f]{32}', conclusion) if project in saved_ids), None)
    selected = [call for call in saves if call['output']['project_id'] == declared] if declared else saves
    saved = selected[-1]['output']
    result.update(selection='declared_final_project' if declared else 'last_saved_project_no_declared_id', last_saved_project_id=saves[-1]['output']['project_id'])
    paths = list((run / 'store').rglob(saved['project_id'] + '/versions/' + saved['version'] + '.vlx'))
    if len(paths) != 1:
        raise RuntimeError('Cannot uniquely locate last successful immutable snapshot')
    raw = paths[0].read_bytes()
    if hashlib.sha256(raw).hexdigest() != saved['version']:
        raise RuntimeError('Snapshot integrity failure')
    doc = json.loads(raw)
    write_json(run / 'final-project.json', doc)
    board = next((b for b in doc['boards'] if b['id'] == doc['activeBoardId']), doc['boards'][0] if doc['boards'] else {})
    files = doc['fileGroups'].get(board.get('activeFileGroupId'), [])
    primary = next((f for f in files if f['name'] == 'sketch.ino'), next((f for f in files if f['name'].endswith('.ino')), None))
    source = primary['content'] if primary else ''
    submitted = selected[-1].get('arguments', {})
    transport_match = None
    if isinstance(submitted.get('sketch'), str):
        transport_match = submitted['sketch'] == source
    elif isinstance(submitted.get('document'), dict) and primary:
        group = submitted['document'].get('fileGroups', {}).get(board.get('activeFileGroupId'), [])
        original = next((f['content'] for f in group if f.get('name') == primary['name']), None)
        transport_match = original == source if original is not None else None
    result.update(source_transport_match=transport_match, source_multiline='\n' in source and len(source.splitlines()) > 1)
    facts = circuit_facts(doc, args.scenario, source)
    result.update(project_id=saved['project_id'], version=saved['version'], facts=facts,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(), source_lines=len(source.splitlines()),
                  sketch_intact='\n' in source and len(source.splitlines()) > 1,
                  has_setup=bool(re.search(r'void\s+setup\s*\(', source)), has_loop=bool(re.search(r'void\s+loop\s*\(', source)))
    destination = run / 'independent' / 'sketch'
    destination.mkdir(parents=True, exist_ok=True)
    for file in files:
        name = 'sketch.ino' if file is primary else file['name']
        path = destination / name
        if not path.resolve().is_relative_to(destination.resolve()):
            raise RuntimeError('Unsafe source path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file['content'].encode())
    fqbn = {'arduino-uno': 'arduino:avr:uno', 'arduino-nano': 'arduino:avr:nano', 'esp32': 'esp32:esp32:esp32'}.get(board.get('boardKind'))
    if primary and fqbn:
        argv = [str(args.arduino_cli), 'compile', '--fqbn', fqbn, '--build-path', str(run / 'independent' / 'build')]
        if fqbn.startswith('esp32:'):
            argv += ['--build-property', 'compiler.cpp.extra_flags=-DBitOrder=uint8_t']
        argv += [str(destination)]
        started = time.monotonic()
        try:
            compiled = subprocess.run(argv, env=toolchain_env(args.toolchain, args.arduino_cli), capture_output=True, text=True, timeout=300)
            (run / 'independent' / 'compile.log').write_text(compiled.stdout + '\n' + compiled.stderr)
            firmware = [{'name': p.name, 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((run / 'independent' / 'build').glob('*')) if p.suffix in ('.hex', '.bin', '.elf') and p.is_file()]
            real_success = compiled.returncode == 0 and bool(firmware)
            result.update(compile_ok=real_success, compile_status='ok' if real_success else 'error', firmware_artifacts=firmware,
                          compile_exit=compiled.returncode, compile_seconds=round(time.monotonic() - started, 2), compiler='arduino-cli-real',
                          compile_fqbn=fqbn, esp32_excluded=args.scenario == 'S3')
        except subprocess.TimeoutExpired:
            result.update(compile_status='timeout', compile_seconds=round(time.monotonic() - started, 2))
    result['automated_success_candidate'] = bool(result['compile_ok'] and result.get('source_transport_match') is not False and facts['wiring_candidate'] and facts['sketch_candidate'] and not result['esp32_excluded'])
    write_json(run / 'audit.json', result)
    return result


def summarize(root):
    rows = []
    for run in sorted(root.glob('S[123]-[AB]-[12]')):
        if not (run / 'run.json').exists():
            continue
        meta = json.loads((run / 'run.json').read_text())
        calls = json_lines(run / 'mcp.jsonl')
        signatures = Counter(canonical({'name': c['name'], 'arguments': c.get('arguments')}) for c in calls)
        errors = Counter()
        for call in calls:
            output = call.get('output', {})
            if output.get('ok') is False:
                errors[output.get('error', {}).get('code', 'unknown')] += 1
            elif call.get('rpc_error') or call.get('isError') or call.get('exception'):
                errors['transport_or_schema'] += 1
        events = json_lines(run / 'opencode.jsonl')
        finals = [e.get('part', {}).get('text', '') for e in events if e.get('type') == 'text']
        tokens = Counter()
        for event in events:
            if event.get('type') == 'step_finish':
                for key, value in event.get('part', {}).get('tokens', {}).items():
                    if isinstance(value, (int, float)):
                        tokens[key] += value
                    elif key == 'cache' and isinstance(value, dict):
                        for cache_key, count in value.items():
                            tokens['cache_' + cache_key] += count
        audit_result = json.loads((run / 'audit.json').read_text()) if (run / 'audit.json').exists() else {}
        build_results = [c['output'] for c in calls if c['name'] == 'build_project']
        session_ids = list(dict.fromkeys(e.get('sessionID') for e in events if e.get('sessionID')))
        review = json.loads((run / 'review.json').read_text()) if (run / 'review.json').exists() else {}
        check_results = [c['output'] for c in calls if c['name'] == 'check_project' and c['output'].get('ok')]
        final_builds = [b for b in build_results if b.get('project_id') == audit_result.get('project_id') and b.get('version') == audit_result.get('version')]
        row = {**meta, 'mcp_calls': len(calls), 'errors': dict(errors), 'errors_total': sum(errors.values()),
               'loops_ge3': [n for n in signatures.values() if n >= 3], 'calls_by_tool': dict(Counter(c['name'] for c in calls)),
               'check_called': any(c['name'] == 'check_project' for c in calls), 'build_called': bool(build_results),
               'terminal_build_observed': any(b.get('ok') and b.get('state') in ('done', 'error', 'interrupted') for b in build_results),
               'terminal_success_observed': any(b.get('ok') and b.get('state') == 'done' and b.get('success') is True for b in build_results),
               'session_ids': session_ids, 'review': review,
               'finish_reasons': [e.get('part', {}).get('reason') for e in events if e.get('type') == 'step_finish'],
               'non_mcp_tools': [e['part'].get('tool') for e in events if e.get('type') == 'tool_use' and not e['part'].get('tool', '').startswith('velxio_')],
               'final_version_terminal_observed': any(b.get('state') in ('done', 'error', 'interrupted') for b in final_builds),
               'check_status': check_results[-1].get('status') if check_results else None,
               'loop_details': [{'name': c['name'], 'arguments': c.get('arguments'), 'count': signatures[canonical({'name': c['name'], 'arguments': c.get('arguments')})]} for index, c in enumerate(calls) if signatures[canonical({'name': c['name'], 'arguments': c.get('arguments')})] >= 3 and not any(prior['name'] == c['name'] and prior.get('arguments') == c.get('arguments') for prior in calls[:index])],
               'tokens': dict(tokens), 'final_text': finals[-1] if finals else '', 'text_parts': finals, 'audit': audit_result}
        rows.append(row)
    write_json(root / 'summary.json', rows)
    return rows


def run(args):
    repo = Path(__file__).resolve().parents[1]
    args.arduino_cli = args.arduino_cli.resolve(strict=True)
    args.toolchain = args.toolchain.resolve(strict=True)
    base = Path.home() / '.cache'
    root = Path(tempfile.mkdtemp(prefix='velxio-mcp-ab-', dir=base))
    root.chmod(0o700)
    print('Evidence directory:', root, flush=True)
    # Avoid /tmp/AGENTS.md and any repository parent instructions.
    for parent in [root, *root.parents]:
        if (parent / 'AGENTS.md').exists():
            raise RuntimeError('Benchmark parent has AGENTS.md; choose an instruction-free parent')
    deadline = time.monotonic() + args.deadline_minutes * 60
    processes, worktrees, ports = {}, {}, {}
    lock = (base / 'velxio-mcp-ab-qwen.lock').open('a')
    import fcntl
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    env = toolchain_env(args.toolchain, args.arduino_cli)
    # Keep the user's provider and credential source unchanged. Disable only
    # unrelated integrations/automatic downloads, identically for A and B.
    model_env = dict(os.environ)
    model_env.update({key: '1' for key in ('OPENCODE_DISABLE_AUTOUPDATE', 'OPENCODE_DISABLE_MODELS_FETCH',
        'OPENCODE_DISABLE_LSP_DOWNLOAD', 'OPENCODE_DISABLE_CLAUDE_CODE', 'OPENCODE_DISABLE_EXTERNAL_SKILLS')})
    model_env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'tools': {'*': False, 'velxio_*': True},
        'permission': {'*': 'deny', 'velxio_*': 'allow', 'doom_loop': 'allow'}})
    try:
        for version, revision in REVISIONS.items():
            worktree = root / 'worktrees' / version
            worktree.parent.mkdir(exist_ok=True)
            command(['git', '-C', repo, 'worktree', 'add', '--detach', worktree, revision])
            worktrees[version] = worktree
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                ports[version] = listener.getsockname()[1]
            log = (root / ('server-' + version + '.log')).open('w')
            processes[version] = subprocess.Popen([sys.executable, __file__, 'serve', '--worktree', str(worktree),
                '--evidence', str(root), '--port', str(ports[version])], cwd=worktree, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(60):
                if processes[version].poll() is not None:
                    raise RuntimeError('Benchmark server failed; inspect its local log')
                try:
                    health = request(ports[version], '/bench/health')
                    write_json(root / ('health-' + version + '.json'), health)
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError('Server startup deadline exceeded')
        write_json(root / 'protocol.json', {'revisions': REVISIONS, 'model': MODEL, 'prompts': PROMPTS, 'agents': AGENTS,
            'timeout_seconds': 720, 'max_rounds': args.rounds, 'host': socket.gethostname(), 'idf_required_for_S3_success': True,
            'adapter': 'unchanged real REST-owner facade; no injected compiler', 'independent_compile': 'real Arduino CLI, no firmware fixture',
            'quota_api_available': False})
        for repetition in range(1, args.rounds + 1):
            if repetition > 1:
                prior = [json.loads(p.read_text()) for p in root.glob('S[123]-[AB]-1/run.json')]
                estimated = sum(r.get('seconds', 720) for r in prior) + 300
                if len(prior) != 6 or estimated > deadline - time.monotonic():
                    print('Stopping at six balanced runs: another complete round would exceed the time reserve.', flush=True)
                    return
            for scenario in PROMPTS:
                order = ('A', 'B') if (repetition + int(scenario[-1])) % 2 == 0 else ('B', 'A')
                for version in order:
                    if (root / 'quota-stop-request.json').exists():
                        print('Stopping after the completed run: external quota stop requested.', flush=True)
                        return
                    # Always reserve time to stop servers, audit and remove trees.
                    if deadline - time.monotonic() < 14 * 60:
                        print('Stopping before another run: global deadline reserve.', flush=True)
                        return
                    label = f'{scenario}-{version}-{repetition}'
                    project = root / 'projects' / label
                    project.mkdir(parents=True)
                    (project / 'AGENTS.md').write_text(AGENTS)
                    write_json(project / 'opencode.json', {'model': MODEL, 'mcp': {'velxio': {
                        'type': 'remote', 'url': f'http://127.0.0.1:{ports[version]}/mcp', 'enabled': True, 'timeout': 120000}}})
                    resolved = json.loads(command(['opencode', 'debug', 'config', '--pure'], cwd=project, env=model_env, timeout=30).stdout)
                    if set(resolved.get('mcp', {})) != {'velxio'} or resolved.get('model') != MODEL:
                        raise RuntimeError('OpenCode configuration is not isolated as requested')
                    if 'hyperqwen' not in resolved.get('provider', {}):
                        raise RuntimeError('Existing hyperqwen provider missing; no credentials will be synthesized')
                    request(ports[version], '/bench/reset', {'run': label})
                    run_dir = root / label
                    run_dir.mkdir(exist_ok=True)
                    stdout = (run_dir / 'opencode.jsonl').open('w')
                    stderr = (run_dir / 'opencode.stderr').open('w')
                    meta = {'run': label, 'scenario': scenario, 'version': version, 'repetition': repetition, 'status': 'running',
                            'prompt_sha256': hashlib.sha256(PROMPTS[scenario].encode()).hexdigest(),
                            'agents_sha256': hashlib.sha256(AGENTS.encode()).hexdigest()}
                    write_json(run_dir / 'run.json', meta)
                    print('START', label, flush=True)
                    started = time.monotonic()
                    process = subprocess.Popen(['opencode', 'run', '--pure', '--format', 'json', '--dir', str(project),
                        '--title', label, PROMPTS[scenario]], cwd=project, env=model_env, stdout=stdout, stderr=stderr, start_new_session=True)
                    try:
                        process.wait(timeout=min(720, max(1, deadline - time.monotonic() - 120)))
                        meta.update(status='finished', exit_code=process.returncode)
                    except subprocess.TimeoutExpired:
                        stop(process)
                        meta.update(status='timeout', exit_code=process.returncode)
                    except BaseException:
                        stop(process)
                        raise
                    finally:
                        stdout.close()
                        stderr.close()
                        meta['seconds'] = round(time.monotonic() - started, 2)
                        write_json(run_dir / 'run.json', meta)
                    # No further model call: independent truth from the saved bytes.
                    audit(argparse.Namespace(run_dir=run_dir, scenario=scenario, arduino_cli=args.arduino_cli, toolchain=args.toolchain))
                    rows = summarize(root)
                    current = next(r for r in rows if r['run'] == label)
                    print('DONE', label, canonical({k: current[k] for k in ('status', 'seconds', 'mcp_calls', 'errors', 'loops_ge3', 'tokens')}), flush=True)
    finally:
        for process in processes.values():
            stop(process)
        for worktree in worktrees.values():
            command(['git', '-C', repo, 'worktree', 'remove', '--force', worktree])
        summarize(root)
        write_json(root / 'cleanup.json', {'servers_stopped': all(p.poll() is not None for p in processes.values()),
            'worktrees_removed': all(not p.exists() for p in worktrees.values())})
        print('STOP. Raw evidence retained outside Git:', root, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    start = commands.add_parser('run')
    start.add_argument('--arduino-cli', type=Path, required=True)
    start.add_argument('--toolchain', type=Path, required=True)
    start.add_argument('--deadline-minutes', type=int, default=75, choices=range(15, 86))
    start.add_argument('--rounds', type=int, default=2, choices=(1, 2))
    server = commands.add_parser('serve')
    server.add_argument('--worktree', type=Path, required=True)
    server.add_argument('--evidence', type=Path, required=True)
    server.add_argument('--inventory', type=Path)
    server.add_argument('--port', type=int, required=True)
    inspect = commands.add_parser('audit')
    inspect.add_argument('--run-dir', type=Path, required=True)
    inspect.add_argument('--scenario', choices=PROMPTS, required=True)
    inspect.add_argument('--arduino-cli', type=Path, required=True)
    inspect.add_argument('--toolchain', type=Path, required=True)
    exports = commands.add_parser('exports')
    exports.add_argument('root', type=Path)
    summary = commands.add_parser('summarize')
    summary.add_argument('root', type=Path)
    args = parser.parse_args()
    if args.action == 'exports':
        for row in summarize(args.root):
            for session in row['session_ids']:
                if row['status'] == 'running':
                    continue
                destination = args.root / row['run'] / 'session-export.json'
                # OpenCode may exit before flushing a >64 KiB pipe; a regular
                # file descriptor preserves the complete local database export.
                with destination.open('w') as output:
                    subprocess.run(['opencode', 'export', session, '--pure'], stdout=output, stderr=subprocess.PIPE, check=True, timeout=45)
                doc = json.loads(destination.read_text())
                messages = doc.get('messages', [])
                info = [m.get('info', m) for m in messages]
                users = [m for m in info if m.get('role') == 'user']
                models = sorted({(m.get('providerID', ''), m.get('modelID', '')) for m in info if m.get('role') == 'assistant'})
                # Message content is checked locally without printing prompts or credentials.
                user_parts = [part.get('text', '') for message in messages if message.get('info', message).get('role') == 'user' for part in message.get('parts', []) if part.get('type') == 'text']
                same_prompt = user_parts in ([PROMPTS[row['scenario']]], [json.dumps(PROMPTS[row['scenario']], ensure_ascii=False)])
                verification = {'user_message_count': len(users), 'models': models, 'complete_prompt': same_prompt,
                    'actual_user_text_sha256': hashlib.sha256(canonical(user_parts).encode()).hexdigest(),
                    'cli_quote_wrapper': user_parts == [json.dumps(PROMPTS[row['scenario']], ensure_ascii=False)]}
                write_json(args.root / row['run'] / 'session-verification.json', verification)
                print(row['run'], 'user_messages', len(users), 'models', models, 'exact_prompt', same_prompt)
    elif args.action == 'summarize':
        rows = summarize(args.root)
        print(json.dumps([{k: row.get(k) for k in ('run', 'status', 'seconds', 'mcp_calls', 'errors', 'loops_ge3', 'tokens')} for row in rows], indent=2))
    else:
        globals()[args.action](args)


if __name__ == '__main__':
    main()
