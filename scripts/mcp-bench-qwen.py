#!/usr/bin/env python3
"""Sequential real-Qwen regression passes; imports the existing A/B instrumentation.

No prompt coaching, compiler fixtures, production defaults, SSH or raw logs in Git.
Strict successes require an independent compile and a source-bound manual review.
B6 can be run alone against an explicitly supplied MCP URL by its remote owner.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('mcp_ab', HERE / 'mcp-ab-qwen.py')
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)
PROMPTS = {
 'B1': 'Please make an Arduino Uno project with an external LED and a 220-ohm series resistor. The LED should blink once per second, with equal on and off time. Save the complete project, compile it, and tell me what actually succeeded.',
 'B2': 'I want an Arduino Uno with a pushbutton and an LED. Each press should toggle the LED on or off, with simple debouncing so that one press counts once. Please save and compile the complete project and report the result.',
 'B3': 'Make a project using an Arduino Nano, a potentiometer and a servo. Turning the knob from one end to the other should move the servo smoothly from 0 to 180 degrees. Save the wired project, compile it and report the actual result.',
 'B4': 'Build an Arduino Uno distance meter with an HC-SR04 and a 16 by 2 I2C LCD. Show the distance in centimeters and sound a buzzer whenever the distance is below 20 cm. Save the wired project, compile it and tell me the result.',
 'B5': 'I need an Arduino Uno weather display with an I2C SSD1306 OLED and a DHT22. Show temperature and humidity, and turn on a red LED when the temperature exceeds 28 degrees Celsius. Save the complete wired project, compile it and report what succeeded.',
 'B6': 'Make an ESP32 DevKit project with a 1.54-inch black-and-white e-paper display showing exactly "Hello World" centered on the screen. Keep the wiring consistent with the sketch, check the project and build it, then report the project, version and true build result.',
}
HOLDOUTS = {
 'V1': 'Please use an Arduino Nano and an external green LED with a 330-ohm resistor to make a light flash twice per second with equal on and off time. Save the wired project and compile it, then report the result.',
 'V2': 'Please connect a sliding potentiometer to an Arduino Uno so that moving it through its full travel positions a servo from zero to 180 degrees. Save and compile the complete wired project and report what worked.',
}
EXPECTED = {
 'B1': {'board':'arduino-uno','components':['led','resistor'],'ohms':220,'half_period_ms':500},
 'B2': {'board':'arduino-uno','components':['pushbutton','led'],'behavior':'debounced press-edge toggle'},
 'B3': {'board':'arduino-nano','components':['potentiometer','servo'],'behavior':'analog 0..1023 to angle 0..180'},
 'B4': {'board':'arduino-uno','components':['hc-sr04','lcd1602-i2c','buzzer'],'threshold_cm':20,'behavior':'pulse echo to cm, LCD cm and buzzer below threshold'},
 'B5': {'board':'arduino-uno','components':['ssd1306','dht22','led'],'threshold_celsius':28,'led_color':'red','behavior':'read and display both DHT22 readings; LED follows temperature threshold'},
 'B6': {'board':'esp32','components':['epaper-1in54-bw'],'text':'Hello World','alignment':'center',
        'pins':{'CS':'5','DC':'17','RST':'16','BUSY':'4','SCK':'18','SDI':'23','VCC':'3V3','GND':'GND'}},
 'V1': {'board':'arduino-nano','components':['led','resistor'],'ohms':330,'half_period_ms':250,'led_color':'green'},
 'V2': {'board':'arduino-uno','components':['slide-potentiometer','servo'],'behavior':'analog 0..1023 to angle 0..180'},
}


def facts(doc, scenario, source):
    expected = EXPECTED[scenario]
    boards = doc.get('boards', [])
    board = next((b for b in boards if b['id']==doc.get('activeBoardId')), boards[0] if boards else {})
    parts = doc.get('components', [])
    kinds = [p.get('metadataId','') for p in parts]
    # Facts are evidence for manual inspection, never a substitute for code
    # semantics or actual native pin validation. Detect obvious omissions first.
    def present(kind):
        return any(k == kind or kind == 'resistor' and k.startswith('resistor-') or
                   kind == 'pushbutton' and k.startswith('pushbutton') or kind == 'ssd1306' and k.startswith('ssd1306') for k in kinds)
    controls = {k: v for k,v in ab.resolve_constants(source)[0].items()}
    return {'expected': expected, 'board_kind':board.get('boardKind'), 'board_matches': board.get('boardKind')==expected['board'],
            'component_kinds':kinds, 'required_components_present':all(present(k) for k in expected['components']),
            'native_wires':doc.get('wires',[]), 'properties':{p['id']:p.get('properties',{}) for p in parts},
            'constants':controls, 'quoted_hello_world':bool(re.search(r'"Hello World"',source)),
            'source_multiline':'\n' in source, 'manual_review_required':True}


def audit(root, label, case, cli, cache):
    # Reuse the independently compiled source/snapshot selection from the A/B
    # bench, replacing only the scenario-specific factual checklist.
    previous = ab.circuit_facts
    ab.circuit_facts = lambda doc, _scenario, source: {**facts(doc, case, source), 'wiring_candidate':False,'sketch_candidate':False}
    try:
        result = ab.audit(argparse.Namespace(run_dir=root/label,scenario='S3' if case=='B6' else 'S1',arduino_cli=cli,toolchain=cache))
    finally:
        ab.circuit_facts = previous
    result['case'] = case
    result['esp32_excluded'] = case=='B6'
    review_file = root/label/'review.json'
    review = json.loads(review_file.read_text()) if review_file.exists() else {}
    bound = review.get('source_sha256') == result.get('source_sha256') and review.get('version') == result.get('version')
    result['strict_success'] = bool(bound and result['compile_ok'] and all(review.get(k) is True for k in ('wiring','values','sketch','behavior')))
    result['review_bound'] = bound
    ab.write_json(root/label/'audit.json',result)
    return result


def summarize(root):
    rows=[]
    for meta in sorted(root.glob('*/run.json')):
        row=json.loads(meta.read_text()); path=meta.parent
        calls=ab.json_lines(path/'mcp.jsonl'); signatures=Counter(ab.canonical({'name':c['name'],'arguments':c.get('arguments')}) for c in calls)
        errors=Counter(c['output'].get('error',{}).get('code','transport') for c in calls if c.get('output',{}).get('ok') is False or c.get('isError') or c.get('rpc_error'))
        events=ab.json_lines(path/'opencode.jsonl'); tokens=Counter()
        for e in events:
            if e.get('type')=='step_finish':
                for key,value in e['part'].get('tokens',{}).items():
                    if isinstance(value,(int,float)):tokens[key]+=value
        audit_file=path/'audit.json'; truth=json.loads(audit_file.read_text()) if audit_file.exists() else {}
        builds=[c['output'] for c in calls if c['name']=='build_project']
        review_file=path/'review.json';review=json.loads(review_file.read_text()) if review_file.exists() else {}
        verification_file=path/'session-verification.json';verification=json.loads(verification_file.read_text()) if verification_file.exists() else {}
        row.update(calls=len(calls),errors=dict(errors),error_count=sum(errors.values()),loops=[n for n in signatures.values() if n>=3],tokens=dict(tokens),
                   check_called=any(c['name']=='check_project' for c in calls),build_called=bool(builds),
                   final_build_read=any(b.get('state') in ('done','error','interrupted') and b.get('project_id')==truth.get('project_id') and b.get('version')==truth.get('version') for b in builds),
                   strict_success=truth.get('strict_success',False),reviewed=truth.get('review_bound',False),compile_ok=truth.get('compile_ok',False),
                   false_success=review.get('false_success'),session_verified=verification.get('verified',False),
                   session_ids=list(dict.fromkeys(e['sessionID'] for e in events if e.get('sessionID'))))
        rows.append(row)
    ab.write_json(root/'summary.json',rows)
    return rows


def verify_sessions(root):
    """Read the existing OpenCode database, without making any model request."""
    results=[]
    for row in summarize(root):
        if row['status']=='running':continue
        proofs=[]
        for session in row['session_ids']:
            destination=root/row['run']/'session-export.json'
            # A regular file avoids OpenCode truncating its stdout on exit.
            with destination.open('w') as output:
                subprocess.run(['opencode','export',session,'--pure'],stdout=output,stderr=subprocess.PIPE,check=True,timeout=45)
            doc=json.loads(destination.read_text());messages=doc.get('messages',[])
            infos=[m.get('info',m) for m in messages]
            users=[m for m in infos if m.get('role')=='user']
            models=sorted({(m.get('providerID',''),m.get('modelID','')) for m in infos if m.get('role')=='assistant'})
            parts=[p.get('text','') for m in messages if m.get('info',m).get('role')=='user' for p in m.get('parts',[]) if p.get('type')=='text']
            prompt=(HOLDOUTS if row['case'].startswith('V') else PROMPTS)[row['case']]
            exact=parts in ([prompt],[json.dumps(prompt,ensure_ascii=False)])
            proofs.append({'user_message_count':len(users),'models':models,'complete_prompt':exact,
                           'verified':len(users)==1 and exact and models==[('hyperqwen','qwen3.8-27b')]})
        proof={'sessions':proofs,'verified':len(proofs)==1 and proofs[0]['verified']}
        ab.write_json(root/row['run']/'session-verification.json',proof)
        results.append({'run':row['run'],**proof})
    return results


def final_saved(calls, events):
    """Select the final declared project, excluding later disposable probes."""
    saves=[c['output'] for c in calls if c['name']=='save_project' and c['output'].get('ok')]
    if not saves:return None
    texts=[e.get('part',{}).get('text','') for e in events if e.get('type')=='text' and e.get('part',{}).get('text','').strip()]
    saved_ids={s['project_id'] for s in saves}
    declared=next((p for p in re.findall(r'p_[0-9a-f]{32}',texts[-1] if texts else '') if p in saved_ids),None)
    return next((s for s in reversed(saves) if s['project_id']==declared),saves[-1])


def epaper_source_facts(doc, source):
    """Conservative source/wire cross-check; manual review and IDF still required."""
    clean=re.sub(r'/\*[\s\S]*?\*/|//[^\n]*','',source)
    native=ab.circuit_facts(doc,'S3',clean)
    _,resolve=ab.resolve_constants(clean)
    controls=native['epaper_control_pins']
    controls_match=[5,17,16,4] in controls
    spi_calls=re.findall(r'\bSPI\s*\.\s*begin\s*\(([^)]*)\)',clean)
    spi=[[resolve(v) for v in call.split(',')] for call in spi_calls if call.strip()]
    # Omitted/default SPI initialization is left to manual source review.
    spi_match=all(len(values)>=3 and values[0]==18 and values[2]==23 for values in spi) if spi else None
    printed=re.findall(r'\bdisplay\s*\.\s*print(?:ln)?\s*\(\s*(?:F\s*\(\s*)?"([^"\n]*)"',clean)
    additional=[value for value in printed if value.strip() and value!='Hello World']
    return {'constructor_control_pins':controls,'constructor_pins_match':controls_match,
            'explicit_spi_pins':spi,'explicit_spi_pins_match':spi_match,
            'source_wire_candidate':native['wiring_candidate'] and controls_match and spi_match is not False,
            'literal_display_texts':printed,'additional_display_literals':additional,
            'manual_review_required':True}


def model_env(proxy_url=None):
    env=dict(os.environ)
    env.update({key:'1' for key in ('OPENCODE_DISABLE_AUTOUPDATE','OPENCODE_DISABLE_MODELS_FETCH','OPENCODE_DISABLE_LSP_DOWNLOAD','OPENCODE_DISABLE_CLAUDE_CODE','OPENCODE_DISABLE_EXTERNAL_SKILLS')})
    options={'tools':{'*':False,'velxio_*':True},'permission':{'*':'deny','velxio_*':'allow','doom_loop':'allow'}}
    if proxy_url: options['provider']={'hyperqwen':{'options':{'baseURL':proxy_url}}}
    env['OPENCODE_CONFIG_CONTENT']=json.dumps(options)
    return env


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def rpc(url, name, arguments):
    async def call():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from datetime import timedelta
        async with streamable_http_client(url) as (read,write,_):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=300)) as session:
                await session.initialize()
                result=await session.call_tool(name,arguments)
                return json.loads(next(c.text for c in result.content if c.type=='text'))
    return asyncio.run(call())


def remote_snapshot(url, root, label):
    # Only immutable project bytes are fetched; never a remote deployment or SSH.
    calls=ab.json_lines(root/label/'mcp.jsonl')
    saved=final_saved(calls,ab.json_lines(root/label/'opencode.jsonl'))
    if saved is None:return
    raw=bytearray();offset=0
    import base64
    while True:
        data=rpc(url,'read_artifact',{'artifact_id':saved['project_artifact_id'],'offset':offset,'length':12288,'encoding':'base64'})
        raw.extend(base64.b64decode(data['data']))
        if data['eof']:break
        offset=data['next_offset']
    assert hashlib.sha256(raw).hexdigest()==saved['version']
    dest=root/label/'store'/'remote'/'projects'/saved['project_id']/'versions'/(saved['version']+'.vlx')
    dest.parent.mkdir(parents=True);dest.write_bytes(raw)


def proxy(args):
    # Bodies are recorded verbatim; authorization headers never reach a log.
    import httpx,uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import StreamingResponse
    from starlette.routing import Route
    config=json.loads((Path.home()/'.config/opencode/opencode.json').read_text())
    upstream=config['provider']['hyperqwen']['options']['baseURL'].rstrip('/')
    async def forward(request:Request):
        body=await request.body(); number=time.time_ns();folder=args.evidence/'http';folder.mkdir(exist_ok=True)
        (folder/(str(number)+'.request.json')).write_bytes(body)
        headers={k:v for k,v in request.headers.items() if k.lower() not in ('host','content-length','connection','accept-encoding')}
        headers['accept-encoding']='identity'
        client=httpx.AsyncClient(timeout=900)
        response=await client.send(client.build_request(request.method,upstream+'/'+request.path_params['path'].removeprefix('v1/'),content=body,headers=headers),stream=True)
        async def chunks():
            try:
                with (folder/(str(number)+'.response.sse')).open('wb') as output:
                    async for chunk in response.aiter_raw():
                        output.write(chunk);output.flush();yield chunk
            finally:
                await response.aclose();await client.aclose()
        return StreamingResponse(chunks(),status_code=response.status_code,headers={'content-type':response.headers.get('content-type','text/event-stream')})
    uvicorn.run(Starlette(routes=[Route('/{path:path}',forward,methods=['POST','GET'])]),host='127.0.0.1',port=args.port,log_level='warning')


def run_pass(args):
    repo=HERE.parent;root=args.evidence.resolve();root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    import fcntl
    lock=(Path.home()/'.cache/velxio-mcp-ab-qwen.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    worktree=root/'worktree';server=None;tracer=None
    if not args.mcp_url and not all((args.toolchain,args.arduino_cli,args.inventory)):
        raise ValueError('Local passes require the installed CLI, cache and real inventory')
    env=ab.toolchain_env(args.toolchain,args.arduino_cli) if not args.mcp_url else dict(os.environ)
    env['MCP_COMPACT_AVR_ENABLED']='1'
    cases=args.cases.split(',')
    if args.mcp_url and cases!=['B6']:raise ValueError('Remote option is reserved for B6; no remote AVR runs')
    try:
        if args.mcp_url:
            url=args.mcp_url
        else:
            ab.command(['git','-C',repo,'worktree','add','--detach',worktree,args.revision])
            port=free_port();url=f'http://127.0.0.1:{port}/mcp'
            server=subprocess.Popen([sys.executable,str(HERE/'mcp-ab-qwen.py'),'serve','--worktree',str(worktree),'--evidence',str(root),
                '--port',str(port),'--inventory',str(args.inventory)],env=env,cwd=worktree,stdout=(root/'server.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
            for _ in range(90):
                if server.poll() is not None:raise RuntimeError('Server failed; inspect private server log')
                try:health=ab.request(port,'/bench/health');break
                except OSError:time.sleep(.5)
            else:raise RuntimeError('Server not ready')
            ab.write_json(root/'health.json',health)
            if args.verify_build:
                ab.request(port,'/bench/reset',{'run':'P0-B1'})
                saved=rpc(url,'save_project',{'sketch':'void setup(){}\nvoid loop(){}\n','libraries':[]})
                result=rpc(url,'build_project',{'action':'start','project_id':saved['project_id'],'version':saved['version'],'board_id':saved['board_id'],'wait_seconds':60})
                ab.write_json(root/'real-build-control.json',result)
                if not(result.get('state')=='done' and result.get('success') and result.get('test_only') is False):raise RuntimeError('Real build admission control failed')
        proxy_url=None
        if args.trace_http:
            port_proxy=free_port();proxy_url=f'http://127.0.0.1:{port_proxy}/v1'
            tracer=subprocess.Popen([sys.executable,__file__,'proxy','--evidence',str(root),'--port',str(port_proxy)],stdout=(root/'proxy.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
            time.sleep(1)
        deadline_file=root.parent/'deadline.json'
        deadline=json.loads(deadline_file.read_text())['unix'] if deadline_file.exists() else None
        for case in cases:
            if (root/'STOP').exists() or deadline is not None and time.time()>=deadline-10:break
            label=case if case.startswith('V') else f'P{args.pass_number}-{case}'
            run=root/label;run.mkdir(exist_ok=True)
            project=root/'projects'/label;project.mkdir(parents=True)
            (project/'AGENTS.md').write_text(ab.AGENTS)
            ab.write_json(project/'opencode.json',{'model':ab.MODEL,'mcp':{'velxio':{'type':'remote','url':url,'enabled':True,'timeout':120000}}})
            if not args.mcp_url:ab.request(port,'/bench/reset',{'run':label})
            prompt=(HOLDOUTS if case.startswith('V') else PROMPTS)[case]
            meta={'run':label,'case':case,'pass':args.pass_number,'status':'running','revision':args.revision,
                  'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'agents_sha256':hashlib.sha256(ab.AGENTS.encode()).hexdigest()}
            ab.write_json(run/'run.json',meta);print('START',label,flush=True);started=time.monotonic()
            with (run/'opencode.jsonl').open('w') as out,(run/'opencode.stderr').open('w') as err:
                process=subprocess.Popen(['opencode','run','--pure','--format','json','--dir',str(project),'--title',label,prompt],cwd=project,env=model_env(proxy_url),stdout=out,stderr=err,start_new_session=True)
                try:process.wait(timeout=min(720,max(1,deadline-time.time()-10)) if deadline else 720);meta.update(status='finished',exit_code=process.returncode)
                except subprocess.TimeoutExpired:ab.stop(process);meta.update(status='timeout',exit_code=process.returncode)
                except BaseException:ab.stop(process);raise
                finally:meta['seconds']=round(time.monotonic()-started,2);ab.write_json(run/'run.json',meta)
            if args.mcp_url:
                events=ab.json_lines(run/'opencode.jsonl')
                calls=[]
                for e in events:
                    if e.get('type')!='tool_use':continue
                    part=e['part'];state=part.get('state',{});output=state.get('output','{}')
                    try:output=json.loads(output)
                    except (ValueError,TypeError):output={'ok':False,'error':{'code':'remote_output_unparsed'}}
                    calls.append({'name':part['tool'].removeprefix('velxio_'),'arguments':state.get('input',{}),'output':output})
                (run/'mcp.jsonl').write_text(''.join(ab.canonical(c)+'\n' for c in calls))
                remote_snapshot(url,root,label)
            if case!='B6':audit(root,label,case,args.arduino_cli,args.toolchain)
            else:
                # Remote ESP32 compilation is reported by the actual remote
                # owner; independent IDF recompilation belongs to that host.
                saved=final_saved(ab.json_lines(run/'mcp.jsonl'),ab.json_lines(run/'opencode.jsonl'))
                result={'case':'B6','strict_success':False,'independent_idf_required':True,'expected':EXPECTED['B6']}
                if saved:
                    paths=list((run/'store').rglob(saved['project_id']+'/versions/'+saved['version']+'.vlx'))
                    if paths:
                        doc=json.loads(paths[0].read_text());board=next(b for b in doc['boards'] if b['id']==doc['activeBoardId'])
                        source='\n'.join(f['content'] for f in doc['fileGroups'][board['activeFileGroupId']])
                        panels=[c['id'] for c in doc['components'] if c['metadataId']=='epaper-1in54-bw']
                        edges={frozenset((e['componentId'],e['pinName']) for e in (w['start'],w['end'])) for w in doc['wires']}
                        pins_ok=len(panels)==1 and all(frozenset(((panels[0],role),(board['id'],pin))) in edges for role,pin in EXPECTED['B6']['pins'].items())
                        result.update(project_id=saved['project_id'],version=saved['version'],facts=facts(doc,'B6',source),
                                      source_wiring=epaper_source_facts(doc,source),
                                      expected_pins_match=pins_ok,source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                                      quoted_hello_world='"Hello World"' in source,centering_logic_present='getTextBounds' in source and '/ 2' in source)
                        ab.write_json(run/'final-project.json',doc)
                ab.write_json(run/'audit.json',result)
            rows=summarize(root);print('DONE',label,ab.canonical(next(r for r in rows if r['run']==label)),flush=True)
    finally:
        ab.stop(tracer);ab.stop(server)
        if worktree.exists():ab.command(['git','-C',repo,'worktree','remove','--force',worktree])
        summarize(root)
        ab.write_json(root/'cleanup.json',{'server_stopped':server is None or server.poll() is not None,'worktree_removed':not worktree.exists()})


def analyze_trace(root):
    """Compare one malformed argument at three actual transport boundaries."""
    wire=[]
    for path in sorted((root/'http').glob('*.response.sse')):
        calls={}
        for line in path.read_text(errors='replace').splitlines():
            if not line.startswith('data:'):continue
            try:chunk=json.loads(line[5:])
            except ValueError:continue
            for choice in chunk.get('choices',[]):
                for part in choice.get('delta',{}).get('tool_calls',[]):
                    call=calls.setdefault(part.get('index',0),{'name':'','arguments':''})
                    call['name']+=part.get('function',{}).get('name','')
                    call['arguments']+=part.get('function',{}).get('arguments','')
        for call in calls.values():
            try:arguments=json.loads(call['arguments'])
            except ValueError:continue
            if not isinstance(arguments,dict):continue
            for field in ('changes','document','parameters'):
                value=arguments.get(field)
                if not isinstance(value,str):continue
                try:json.loads(value);continue
                except ValueError:pass
                wire.append({'name':call['name'].removeprefix('velxio_'),'arguments':arguments,'field':field,'value':value,'wire_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    incoming=[call for path in root.glob('*/mcp.jsonl') for call in ab.json_lines(path)]
    events=[e['part'] for path in root.glob('*/opencode.jsonl') for e in ab.json_lines(path) if e.get('type')=='tool_use']
    proof=[]
    for call in wire:
        mcp=any(c['name']==call['name'] and c.get('arguments')==call['arguments'] for c in incoming)
        oc=any(e.get('tool')=='velxio_'+call['name'] and e.get('state',{}).get('input')==call['arguments'] for e in events)
        if oc and mcp:
            proof.append({**call,'opencode_identical':True,'mcp_incoming_identical':True,
                          'finding':'Malformed/incomplete structured string already exists in Qwen API tool-call output; no change across OpenCode or MCP incoming HTTP.'})
            break
    ab.write_json(root/'trace-analysis.json',proof)
    return proof


def report(parent, output):
    roots=sorted(parent.glob('p[0-9]*'));allrows=[]
    for root in roots:allrows.extend(summarize(root))
    qualifying=[]
    for root in roots:
        rows=[r for r in allrows if (root/r['run']/'run.json').exists() and r['case'] in ('B1','B2','B3','B4','B5')]
        if rows:qualifying.append((root.name,len(rows)==5 and all(r['strict_success'] and r['error_count']<=3 for r in rows)))
    confirmed=any(a[1] and b[1] for a,b in zip(qualifying,qualifying[1:]))
    validations=[r for r in allrows if r['case'] in HOLDOUTS]
    lines=['# Real Qwen MCP cycles — 2026-11-04','',
      'Verdict: '+('the required two consecutive qualifying passes were achieved.' if confirmed else 'the two-pass acceptance criterion has not yet been achieved.'),
      'Local workbench only; no SSH, production access, deployment or push. OpenCode 1.19.3 uses the existing hyperqwen/qwen3.8-27b provider.',
      'Fresh directory/session, identical neutral AGENTS.md, one complete natural user prompt, no coaching; sequential runs, 720-second timeout.',
      'Each pass pins a Git worktree and uses the actual six-tool HTTP facade and genuine REST owner. The opt-in AVR lane executes the installed compiler, not a fixture.',
      'Installed core, CLI and library sources are verified by real inventory hashes. Trusted local recipes; no claim of OS network isolation.',
      'Independent recompilation reads immutable stored source. Strict success additionally requires a version/source-bound manual review of wiring, exact values and code behavior.',
      'Compilation does not validate displayed pixels, motion, sensor accuracy or LED timing. C/W/V/S/B below mean compile/wiring/values/sketch/behavior.',
      'Errors count failed MCP replies by code; checker informational findings are separate. Tokens are provider-reported total sums, including reused context; loop counts are identical calls repeated at least three times.',
      '', '| Pass/case | MCP | Errors by code | Loops >=3 | Tokens | Seconds | C/W/V/S/B | Strict | Check/build/final read |',
      '| --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |']
    for row in allrows:
        root=next(root for root in roots if (root/row['run']/'run.json').exists())
        review_file=root/row['run']/'review.json';review=json.loads(review_file.read_text()) if review_file.exists() else {}
        flags='/'.join(('Y' if value is True else 'N' if value is False else '?') for value in [row['compile_ok'],*[review.get(k) for k in ('wiring','values','sketch','behavior')]])
        errors=', '.join(k+':'+str(v) for k,v in sorted(row['errors'].items())) or '0'
        actions='/'.join('Y' if row[k] else 'N' for k in ('check_called','build_called','final_build_read'))
        lines.append(f"| {row['run']} | {row['calls']} | {errors} | {row['loops']} | {row['tokens'].get('total','?')} | {row.get('seconds','running')} | {flags} | {str(row['strict_success']) if row['reviewed'] else 'pending review'} | {actions} |")
    lines+=['','## Pass scores and exact failure families']
    for root in roots:
        rows=[r for r in allrows if (root/r['run']/'run.json').exists() and r['case'] in ('B1','B2','B3','B4','B5')]
        if not rows:
            for path in root.glob('*/mcp.jsonl'):
                for call in ab.json_lines(path):
                    error=call.get('output',{}).get('error')
                    if error:lines.append(f"- {path.parent.name} `{error['code']}`: `"+ab.canonical({'tool':call['name'],'arguments':call.get('arguments')})+'`')
            continue
        success=sum(r['strict_success'] for r in rows);qualified=len(rows)==5 and all(r['strict_success'] and r['error_count']<=3 for r in rows)
        health=json.loads((root/'health.json').read_text()) if (root/'health.json').exists() else {}
        lines.append(f"{root.name}: {success}/5 strict; errors {[r['error_count'] for r in rows]}; complete={len(rows)==5}; qualifying={qualified}; revision `{health.get('revision','unknown')[:12]}`.")
        errors={}
        for path in root.glob('*/mcp.jsonl'):
            for call in ab.json_lines(path):
                error=call.get('output',{}).get('error')
                if not error:continue
                code=error['code'];candidate=ab.canonical({'tool':call['name'],'arguments':call.get('arguments')})
                if code not in errors or len(candidate)<len(errors[code]):errors[code]=candidate
        for code,call in sorted(errors.items())[:5]:lines.append(f'- `{code}`: `{call}`')
    lines+=['','## Changes and evidence',
      '- `1e36e2d1`: removed named wiring, retaining native start/end wires, e-paper pins and all ESP32 paths. 31 agent + 168 compact tests passed.',
      '- `825f95e9`: real AVR inventory/admission and regression bench. Genuine HTTP/MCP control returned done/success=true/test_only=false with a real HEX; 31 agent + 171 compact tests passed.']
    notes=parent/'cycle-notes.json'
    if notes.exists():lines.extend('- '+note for note in json.loads(notes.read_text()))
    verified=[r for r in allrows if r['session_verified']]
    assessed=[r for r in allrows if r['false_success'] is not None]
    lines.append(f"- Database-export verification: {len(verified)}/{len(allrows)} runs confirm exactly one complete user prompt and the required provider/model; no extra model request is made by this check.")
    lines.append(f"- False-success review: {sum(r['false_success'] is True for r in assessed)}/{len(assessed)} assessed conclusions contradicted by independent project evidence; unassessed={len(allrows)-len(assessed)}.")
    trace=[]
    for root in roots:
        file=root/'trace-analysis.json'
        if file.exists():trace+=json.loads(file.read_text())
    if trace:
        p=trace[0];lines+=['', 'HTTP trace: the malformed value is already present in the Qwen API response; OpenCode tool input and MCP incoming HTTP are identical.',
            'Exact observed upstream value: `'+ab.canonical({p['field']:p['value']})+'`. The internal distinction between model generation and the Qwen server parser is not observable here.']
    lines+=['','## Verdict, remaining work and limits',
      'Stop requires two consecutive complete qualifying passes, each with all five strict successes and at most three MCP errors per run. No unmeasured success is claimed.',
      'Only source-bound reviews count; valid JSON strings and numeric strings may be normalized, but incomplete arguments must not be guessed or silently repaired.',
      f"Reserved validation prompts V1/V2: {sum(r['strict_success'] for r in validations)}/{len(validations)} strict; {2-len(validations)} not run. They are separate from tuning; no MCP changes are made from their outcomes.",
      'Small sample, one model/harness, order and cache effects remain limitations.',
      'The improvement bundle is measured together, without per-feature ablation: individual contributions and causal shares are not established. Prompt coverage cannot prove general reliability.',
      'B6-READY: `python scripts/mcp-bench-qwen.py pass --pass-number 6 --evidence <private-output> --cases B6 --mcp-url <explicit-URL>`; intended for the remote owner on its IDF host. No ESP32 run is performed here.',
      'B6 checks exact quoted Hello World, centering logic and native CS5/DC17/RST16/BUSY4/SCK18/SDI23/3V3/GND; independent IDF recompilation remains required on that host. It is excluded from the five-case score.',
      'Raw HTTP bodies, sessions, snapshots and compiler logs remain outside Git; authorization headers and provider keys are never logged or committed.']
    if len(lines)>150:raise ValueError('Report would exceed 150 lines; curate the accumulated notes first')
    output.write_text('\n'.join(lines)+'\n')
    return allrows


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    run=sub.add_parser('pass');run.add_argument('--evidence',type=Path,required=True);run.add_argument('--pass-number',type=int,required=True)
    run.add_argument('--revision',default='HEAD');run.add_argument('--cases',default='B1,B2,B3,B4,B5');run.add_argument('--inventory',type=Path)
    run.add_argument('--arduino-cli',type=Path);run.add_argument('--toolchain',type=Path)
    run.add_argument('--mcp-url');run.add_argument('--trace-http',action='store_true');run.add_argument('--verify-build',action='store_true')
    pr=sub.add_parser('proxy');pr.add_argument('--evidence',type=Path,required=True);pr.add_argument('--port',type=int,required=True)
    au=sub.add_parser('audit');au.add_argument('--evidence',type=Path,required=True);au.add_argument('--run',required=True);au.add_argument('--case',required=True)
    au.add_argument('--arduino-cli',type=Path,required=True);au.add_argument('--toolchain',type=Path,required=True)
    tr=sub.add_parser('trace-analysis');tr.add_argument('root',type=Path)
    rp=sub.add_parser('report');rp.add_argument('parent',type=Path);rp.add_argument('--output',type=Path,default=HERE.parent/'docs/mcp-bench-qwen-20261104.md')
    su=sub.add_parser('summary');su.add_argument('root',type=Path)
    ve=sub.add_parser('verify-sessions');ve.add_argument('root',type=Path)
    args=p.parse_args()
    if args.action=='pass':run_pass(args)
    elif args.action=='proxy':proxy(args)
    elif args.action=='trace-analysis':print(json.dumps(analyze_trace(args.root),indent=2))
    elif args.action=='report':report(args.parent,args.output)
    elif args.action=='audit':print(json.dumps(audit(args.evidence,args.run,args.case,args.arduino_cli,args.toolchain),indent=2))
    elif args.action=='verify-sessions':print(json.dumps(verify_sessions(args.root),indent=2))
    else:print(json.dumps(summarize(args.root),indent=2))

if __name__=='__main__':main()
