#!/usr/bin/env python3
"""Local full editor/chat/REST compiler test server. No mocked editor or model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root',type=Path,required=True)
parser.add_argument('--dist',type=Path,required=True)
parser.add_argument('--evidence',type=Path,required=True)
parser.add_argument('--inventory',type=Path,required=True)
parser.add_argument('--arduino-cli',type=Path,required=True)
parser.add_argument('--toolchain',type=Path,required=True)
args=parser.parse_args()
root=args.source_root.resolve();evidence=args.evidence.resolve();evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
sys.path.insert(0,str(root/'backend'))
spec=importlib.util.spec_from_file_location('chat_ui_common',root/'scripts/mcp-ab-qwen.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
os.environ.update(common.toolchain_env(args.toolchain,args.arduino_cli))
os.environ.update({'VELXIO_AGENT_DATA':str(evidence/'private/agent'),'MCP_COMPACT_DATA':str(evidence/'private/mcp'),
    'MCP_COMPACT_INVENTORY':str(args.inventory.resolve()),'MCP_COMPACT_AVR_ENABLED':'1',
    'MCP_COMPACT_SOURCE_ROOT':str(root),'VELXIO_ARTIFACT_CACHE':str(evidence/'private/compiler-cache'),
    'VELXIO_NEWS':'off'})
from app.main import app
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.routing import Mount
import uvicorn

class Frontend(StaticFiles):
    async def get_response(self,path,scope):
        try:return await super().get_response(path,scope)
        except HTTPException as exc:
            if exc.status_code!=404 or path.startswith('api/') or '.' in path.rsplit('/',1)[-1]:raise
            return await super().get_response('index.html',scope)

# The final compact facade owns /mcp; preserve it and send other frontend
# requests to the exact prebuilt bundle. All genuine API routes stay ahead.
facade=app.router.routes.pop()
frontend=Frontend(directory=args.dist.resolve(),html=True)
async def fallback(scope,receive,send):
    if scope.get('path','').startswith('/mcp'):return await facade.app(scope,receive,send)
    return await frontend(scope,receive,send)
app.router.routes.append(Mount('/',app=fallback))
with socket.socket() as listener:
    listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
(evidence/'server.json').write_text(json.dumps({'port':port,'mode':'full-real-editor-chat-and-REST-compiler'})+'\n')
uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning',access_log=False)
