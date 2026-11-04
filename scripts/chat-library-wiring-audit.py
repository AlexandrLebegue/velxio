#!/usr/bin/env python3
"""Independently compile saved chat artifacts and export reviewable native facts.

Never called by the model. This does not claim display output or servo motion.
Raw evidence must stay outside Git.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


def load_common():
    spec=importlib.util.spec_from_file_location('chat_audit_common',Path(__file__).with_name('mcp-ab-qwen.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def audit(folder,toolchain,cli):
    result=json.loads((folder/'result.json').read_text())
    workspace=json.loads((folder/'workspace.json').read_text())
    document=workspace['document'];board=next(b for b in document['boards'] if b['id']==document['activeBoardId'])
    files=document['fileGroups'][board['activeFileGroupId']]
    root=folder/'independent';sketch=root/'sketch';sketch.mkdir(parents=True,exist_ok=True)
    for file in files:
        relative=Path(file['name'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe saved filename')
        path=sketch/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(file['content'].encode())
    fqbn={'arduino-uno':'arduino:avr:uno','arduino-nano':'arduino:avr:nano:cpu=atmega328'}.get(board['boardKind'])
    if not fqbn:raise ValueError('No independent local build route for '+board['boardKind'])
    compiled=subprocess.run([str(cli),'compile','--fqbn',fqbn,'--build-path',str(root/'build'),str(sketch)],
        env=load_common().toolchain_env(toolchain,cli),capture_output=True,text=True,timeout=300)
    (root/'compile.log').write_text(compiled.stdout+compiled.stderr)
    program=root/'build/sketch.ino.hex'
    record={'case':result['case'],'mcp_calls':result['mcp_calls'],'failed_steps':result['failed_steps'],
        'seconds':result['seconds'],'single_exact_prompt':result['single_exact_prompt'],
        'application_final_compiled':any(r.get('state')=='compiled' and r.get('compiled') is True for r in result['browser_results']),
        'independent_compile':compiled.returncode==0 and program.is_file(),
        'source_multiline':all('\n' in f['content'] for f in files if f['name'].endswith('.ino')),
        'source_hashes':{f['name']:hashlib.sha256(f['content'].encode()).hexdigest() for f in files},
        'board':board,'component_counts':dict(Counter(p['metadataId'] for p in document['components'])),
        'properties':{p['id']:p['properties'] for p in document['components']},'native_wires':document['wires'],
        'runtime_behavior_verified':False,'manual_code_and_pin_review_required':True}
    (root/'audit.json').write_text(json.dumps(record,indent=2)+'\n')
    return {k:record[k] for k in ('case','mcp_calls','seconds','application_final_compiled','independent_compile','source_multiline')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--toolchain',type=Path,required=True)
    parser.add_argument('--arduino-cli',type=Path,required=True)
    parser.add_argument('--cases',required=True)
    args=parser.parse_args()
    rows=[audit(args.evidence/name,args.toolchain,args.arduino_cli) for name in args.cases.split(',')]
    (args.evidence/'independent-summary.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows))


if __name__=='__main__':main()
