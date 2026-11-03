"""Stdlib/static checks. ASGI tests below require already installed SDK; no installs."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact import Catalog, TOOL_SCHEMAS, ProjectStore
from app.mcp.compact.facade import CompactRuntime, NamespaceStore
from app.mcp.compact.builds import proof_bytes
from app.mcp.compact.checks import CompilerPolicy, LibraryInventory


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class FacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_matches_real_extractor_and_runtime_no_subprocess(self):
        snapshot = ROOT / 'backend/app/mcp/compact/catalog.snapshot.json'
        catalog = Catalog.from_snapshot(snapshot)
        self.assertEqual(catalog._snapshot, Catalog.from_repository(ROOT)._snapshot)
        with patch('subprocess.run', side_effect=AssertionError('NO NODE/SUBPROCESS AT RUNTIME')):
            runtime = CompactRuntime(object())
            result = await runtime.call('search_catalog', {})
        self.assertEqual(len(result['items']), 5)
        self.assertEqual((await runtime.call('run_project', {}))['error']['code'], 'invalid_argument')
        self.assertEqual((await runtime.call('save_project', {}))['error']['code'], 'owner_integration_required')
        await runtime.close()

    async def test_snapshot_hash_tamper_refused(self):
        source = ROOT / 'backend/app/mcp/compact/catalog.snapshot.json'
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'catalog.json'
            dest.write_bytes(source.read_bytes() + b' ')
            dest.with_suffix('.json.sha256').write_text(source.with_suffix('.json.sha256').read_text())
            with self.assertRaises(ValueError): Catalog.from_snapshot(dest)

    async def test_namespace_isolation_global_quota_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            quota = ProjectStore(tmp, max_storage_bytes=300)
            a = NamespaceStore(quota, 'a'); b = NamespaceStore(quota, 'b')
            (Path(a.root) / 'proof').write_bytes(b'x' * 200)
            with b._locked(True) as fd:
                self.assertGreaterEqual(b._usage(fd), 200)
            (Path(b.root) / 'link').symlink_to('/etc/passwd')
            with b._locked(False) as fd, self.assertRaises(ValueError): b._usage(fd)

    async def test_root_inventory_and_local_cache_routine(self):
        routine = load('scripts/mcp-compact-inventory.py', 'compact_inventory_test')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); idf = root / 'idf'; arduino = root / 'arduino'
            for name in ['tools/idf.py', 'tools/cmake/project.cmake', 'version.txt']:
                p = idf / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('5.5.4' if name == 'version.txt' else '# CONTROLLED SDK PROOF')
            arduino.mkdir(); (arduino / 'CMakeLists.txt').write_text('# CONTROLLED CORE PROOF')
            libraries = []
            for index, name in enumerate(['GxEPD2', 'Adafruit GFX Library', 'Adafruit BusIO']):
                path = root / str(index); path.mkdir()
                (path / 'library.properties').write_text('name=' + name + '\nversion=TEST-ONLY\n')
                (path / 'a.h').write_text('// TEST ONLY')
                libraries.append((name, str(path)))
            exe = root / 'CONTROLLED-NONEXECUTABLE-PROOF'; exe.write_text('TEST FIXTURE; NO REAL TOOLCHAIN')
            executables = [(name, str(exe)) for name in ('gcc','cmake','ninja','python')]
            doc = routine.collect(root / 'out', idf, arduino, libraries, executables=executables)
            before = (root / 'out/inventory.json').read_bytes()
            routine.collect(root / 'out', idf, arduino, libraries, executables=executables)
            self.assertEqual(before, (root / 'out/inventory.json').read_bytes())
            self.assertEqual(len(LibraryInventory('/', doc['libraries'], complete=True).verify()['entries']), 3)
            self.assertTrue(proof_bytes('/', str(idf / 'version.txt').lstrip('/')))
            with self.assertRaises(ValueError): routine.collect(root / 'out', idf, arduino, libraries[:1])

    async def test_package_spec_exact_bindings_mounts_policy_snapshot(self):
        prepare = load('packaging/mcp-compact/prepare.py', 'compact_prepare_test')
        host = {'NetworkMode': 'bridge', 'PortBindings': {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '3080'}], '8002/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8002'}]}, 'Binds': ['/real/data:/app/data:rw'], 'RestartPolicy': {'Name': 'unless-stopped'}}
        inspected = [{'Image': 'sha256:' + 'a'*64, 'Name': '/controlled-test', 'HostConfig': host, 'Config': {'Env': ['KEEP=yes'], 'WorkingDir': '/app'}, 'Mounts': [{'Type': 'bind', 'Source': '/real/data', 'Destination': '/app/data', 'RW': True}]}]
        preimages = json.loads((ROOT / 'packaging/mcp-compact/reviewed-base.json').read_bytes())
        preimages.update({'/app/entrypoint.sh': 'b'*64, '/etc/nginx/conf.d/default.conf': 'b'*64})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'context'
            manifest = prepare.prepare(inspected, preimages, out, 'controlled:TEST-ONLY')
            config = json.loads((out / 'create.json').read_bytes())
            self.assertEqual(config['HostConfig'], host)
            self.assertEqual(manifest['mounts'], inspected[0]['Mounts'])
            self.assertEqual(CompilerPolicy(out / 'payload/source').prefix, 'user_')
            self.assertTrue((out / 'payload/app/mcp/compact/catalog.snapshot.json').exists())
            self.assertNotIn('__pycache__', '\n'.join(manifest['files']))
            # Existing image-declared anonymous volumes MUST keep their name.
            anonymous = json.loads(json.dumps(inspected))
            anonymous[0]['HostConfig']['Binds'] = None
            anonymous[0]['HostConfig']['Mounts'] = None
            anonymous[0]['Mounts'] = [{'Type': 'volume', 'Name': 'existing-volume-id', 'Source': '/var/lib/docker/volumes/existing-volume-id/_data', 'Destination': '/app/data', 'RW': True}]
            prepare.prepare(anonymous, preimages, Path(tmp) / 'anonymous', 'controlled:TEST-ONLY')
            spec = json.loads((Path(tmp) / 'anonymous/create.json').read_bytes())
            self.assertEqual(spec['HostConfig']['Mounts'][0]['Source'], 'existing-volume-id')
            bad = dict(preimages); bad['/app/app/services/espidf_compiler.py'] = 'c'*64
            with self.assertRaisesRegex(ValueError, 'preserve/port'):
                prepare.prepare(inspected, bad, Path(tmp) / 'bad', 'controlled:TEST-ONLY')
            hidden = json.loads(json.dumps(inspected))
            hidden[0]['Mounts'][0]['Destination'] = '/app/app/services'
            with self.assertRaisesRegex(ValueError, 'hides overlay'):
                prepare.prepare(hidden, preimages, Path(tmp) / 'hidden', 'controlled:TEST-ONLY')


    async def test_registration_lifespan_transport_and_no_legacy_import(self):
        source = (ROOT / 'backend/app/mcp/compact/facade.py').read_text()
        tree = ast.parse(source)
        self.assertNotIn('app.mcp.server', source)
        self.assertEqual(set(TOOL_SCHEMAS), {'search_catalog','get_reference','save_project','check_project','build_project','read_artifact'})
        self.assertIn('session_manager.run()', source)
        self.assertIn('bind_compact_offline_owner(request, user)', source)
        self.assertIn("streamable_http_path='/mcp'", source)
        entry = (ROOT / 'packaging/mcp-compact/entrypoint.sh').read_text()
        for forbidden in ['core install', 'update-index', 'install.sh', 'pip install', 'npm install']:
            self.assertNotIn(forbidden, entry.replace('# Its own environment/dependency failure stops startup; no healing/fallback.', '').replace('# export.sh is the existing local SDK activation, never install.sh.', ''))
        self.assertIn('wait -n', entry)
        self.assertIn('--workers 1', entry)


@unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('fastapi', 'mcp', 'httpx')), 'ASGI SDK absent locally; no installation authorized')
class ActualSDKASGITests(unittest.IsolatedAsyncioTestCase):
    async def test_real_http_protocol_initialize_list_search(self):
        from fastapi import FastAPI
        import httpx
        from app.mcp.compact.facade import create_facade
        app = FastAPI(); transport, lifespan, runtime = create_facade(app)
        app.mount('/', transport)
        from app.mcp.compact.facade import _SCOPE
        original = runtime.call
        async def observed_call(name, arguments):
            self.assertIsNotNone(_SCOPE.get(), 'SDK lost the HTTP request context')
            self.assertEqual(_SCOPE.get()['path'], '/mcp')
            return await original(name, arguments)
        runtime.call = observed_call  # Observe real SDK context; no compiler double.
        async with lifespan():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
                headers = {'Accept': 'application/json, text/event-stream'}
                init = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'real-ASGI-protocol-test','version':'1'}}})
                self.assertEqual(init.status_code, 200, init.text)
                result = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
                names = {item['name'] for item in result.json()['result']['tools']}
                self.assertEqual(names, set(TOOL_SCHEMAS))
                result = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'search_catalog','arguments':{}}})
                payload = json.loads(result.json()['result']['content'][0]['text'])
                self.assertEqual(len(payload['items']), 5)
                self.assertLessEqual(len(result.content), 24*1024+2048)
