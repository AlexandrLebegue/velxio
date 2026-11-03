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
from types import ModuleType, SimpleNamespace
from unittest.mock import patch, AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact import Catalog, CatalogError, TOOL_SCHEMAS, ProjectStore, ProjectChecker, BuildService
from app.mcp.compact.facade import CompactRuntime, NamespaceStore, create_facade
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

    async def test_runtime_ignores_legacy_cursor_and_keeps_other_arguments_strict(self):
        runtime = CompactRuntime(object())
        args = {'cursor': {'stale': True}, 'offset': 5, 'limit': 50}
        result = await runtime.call('search_catalog', args)
        self.assertEqual(result, runtime.catalog.search_catalog(offset=5, limit=50))
        self.assertIn('cursor', args)  # Caller-owned arguments are not mutated.
        ref = await runtime.call('get_reference', {'id':'component:led', 'cursor':'stale'})
        self.assertTrue(ref['ok'])
        bad = await runtime.call('search_catalog', {'cursor':'stale', 'unexpected':1})
        self.assertEqual(bad['error']['code'], 'invalid_argument')
        await runtime.close()

    async def test_sdk_registration_normalizes_before_strict_validation_controlled_doubles(self):
        # Registration/ordering unit test with explicit SDK/validator doubles.
        # Real JSON schemas are checked with Ajv; installed-SDK ASGI test below.
        class FakeSDK:
            def __init__(self, *args, **kwargs):
                self._mcp_server = self
            def list_tools(self):
                return lambda callback: callback
            def call_tool(self, *, validate_input):
                self.validate_input = validate_input
                def register(callback):
                    self.callback = callback
                    return callback
                return register
            def streamable_http_app(self):
                return None
        class ValidationError(Exception):
            pass
        sdk = FakeSDK()
        validate = Mock()
        runtime = SimpleNamespace(call=AsyncMock(return_value={'ok':True}))
        modules = {}
        for name in ('mcp.server.fastmcp', 'mcp.types', 'jsonschema'):
            modules[name] = ModuleType(name)
        modules['mcp.server.fastmcp'].FastMCP = lambda *a, **kw: sdk
        modules['mcp.types'].Tool = SimpleNamespace
        modules['mcp.types'].TextContent = SimpleNamespace
        modules['jsonschema'].validate = validate
        modules['jsonschema'].ValidationError = ValidationError
        with patch.dict(sys.modules, modules), patch('app.mcp.compact.facade.CompactRuntime', return_value=runtime):
            create_facade(object())
        self.assertFalse(sdk.validate_input)
        for name in TOOL_SCHEMAS:
            runtime.call.reset_mock(); validate.reset_mock()
            args = {'cursor':'stale'}
            response = await sdk.callback(name, args)
            validate.assert_called_once_with(instance={}, schema=TOOL_SCHEMAS[name]['inputSchema'])
            runtime.call.assert_awaited_once_with(name, {})
            self.assertEqual(json.loads(response[0].text), {'ok':True})
            self.assertEqual(args, {'cursor':'stale'})
        runtime.call.reset_mock()
        validate.side_effect = ValidationError('CONTROLLED INVALID ARGUMENT FIXTURE')
        response = await sdk.callback('search_catalog', {'cursor':'stale','other':1})
        self.assertEqual(json.loads(response[0].text)['error']['code'], 'invalid_argument')
        runtime.call.assert_not_called()
        # A save rejected before runtime/storage must retain the native field error.
        malformed = {'format':'velxio-project','version':1,'boards':[],'fileGroups':{},
                     'components':[{'id':'epd','x':0,'y':0,'properties':{}}],
                     'wires':[],'activeBoardId':None}
        response = await sdk.callback('save_project', {'document':malformed})
        error = json.loads(response[0].text)['error']
        self.assertEqual(error['path'], '/components/0/metadataId')
        self.assertEqual(error['received'], '<missing>')
        self.assertIn('string', error['expected'])
        runtime.call.assert_not_called()

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


class StartupInventoryTests(unittest.TestCase):
    """Local fixture hashes and explicit service-selection doubles; no real SDK."""
    def fixture(self, root):
        idf, arduino, libs, tools = (root / name for name in ('idf', 'arduino', 'libraries', 'bin'))
        for name in ('tools/idf.py', 'tools/cmake/project.cmake', 'version.txt'):
            file = idf/name; file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('5.5.4' if name == 'version.txt' else '# CONTROLLED SDK PROOF')
        arduino.mkdir(); (arduino/'CMakeLists.txt').write_text('# CONTROLLED CORE PROOF')
        for folder, name in [('GxEPD2','GxEPD2'), ('Adafruit_GFX_Library','Adafruit GFX Library'), ('Adafruit_BusIO','Adafruit BusIO')]:
            path = libs/folder; path.mkdir(parents=True)
            (path/'library.properties').write_text('name='+name+'\nversion=TEST-ONLY\n')
            (path/'a.h').write_text('// CONTROLLED LIBRARY PROOF')
        tools.mkdir()
        for name in ('xtensa-esp32-elf-gcc','cmake','ninja','python'):
            file = tools/name; file.write_text('CONTROLLED NONEXECUTABLE CONTENT; NEVER RUN'); file.chmod(0o755)
        service = SimpleNamespace(available=True, _idf_target=lambda _: 'esp32',
            _arduino_supports_target=lambda _: True, _use_idf5=lambda *args: True,
            _idf_root=lambda _: str(idf), _arduino_path_for=lambda _: str(arduino),
            _find_arduino_libraries_dir=lambda: libs, _build_env=lambda *args, **kw: {'PATH':str(tools)})
        module = ModuleType('app.services.espidf_compiler'); module.espidf_compiler = service
        return module, libs, tools

    def test_startup_loads_verified_subset_and_unlisted_dependency_stays_unknown(self):
        routine = load('scripts/mcp-compact-inventory.py','startup_inventory_test')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); module, libs, tools = self.fixture(root)
            output = root/'inventory'
            with patch.dict(sys.modules, {'app.services.espidf_compiler':module}), \
                    patch('subprocess.run', side_effect=AssertionError('NO COMPILE/INSTALL/DOWNLOAD')):
                doc = routine.startup(output)
            self.assertFalse(doc['complete'])
            runtime = CompactRuntime(object(), inventory_file=output/'inventory.json')
            inventory, toolchains = runtime.inventories()
            self.assertEqual(set(inventory.verify()['entries']), {'GxEPD2','Adafruit GFX Library','Adafruit BusIO'})
            self.assertEqual(toolchains.verify()['toolchains']['esp32:esp32:esp32|arduino']['idf_root'], str(root/'idf'))
            project = json.loads((ROOT/'review/mcp-compact-smoke-20261103/hello-epaper-esp32.vlx').read_bytes())
            project['boards'][0]['libraries'].append('ArduinoJson')
            store = ProjectStore(root/'store')
            saved = store.save_project(document=project); self.assertTrue(saved['ok'], saved)
            checker = ProjectChecker(store, runtime.catalog, inventory=inventory, source_root=ROOT)
            with self.assertRaises(CatalogError) as failure:
                BuildService(store, checker)._preflight(saved['project_id'], saved['version'], 'esp32')
            self.assertEqual(failure.exception.code, 'dependencies_unknown')
            (libs/'GxEPD2/library.properties').write_text('altered')
            with self.assertRaises(ValueError): inventory.verify()

    def test_missing_local_tool_or_library_does_not_install_or_reuse_evidence(self):
        routine = load('scripts/mcp-compact-inventory.py','startup_inventory_missing_test')
        for missing in ('gcc','library'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); module, libs, tools = self.fixture(root)
                (tools/'xtensa-esp32-elf-gcc' if missing == 'gcc' else libs/'Adafruit_BusIO/library.properties').unlink()
                with patch.dict(sys.modules, {'app.services.espidf_compiler':module}), \
                        patch('subprocess.run', side_effect=AssertionError('INSTALL/DOWNLOAD FORBIDDEN')):
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        routine.startup(root/'inventory')
                self.assertFalse((root/'inventory/inventory.json').exists())

    def test_entrypoint_sets_inventory_before_app_and_hides_failed_partial_manifest(self):
        import os
        import subprocess
        prefix = (ROOT/'packaging/mcp-compact/entrypoint.sh').read_text().split('nginx -t',1)[0]
        for exit_code in (0,1):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); idf = root/'idf'; idf.mkdir()
                (idf/'export.sh').write_text('# controlled local activation only\n')
                app_python = root/'app-python-double'
                app_python.write_text('#!/bin/bash\nprintf \'{}\\n\' > "${@: -1}/inventory.json"\nexit ' + str(exit_code) + '\n')
                app_python.chmod(0o755)
                result = subprocess.run(['bash','-c',prefix+'\nprintf "%s\\n" "$MCP_COMPACT_INVENTORY"\n'],
                    env={**os.environ,'SECRET_KEY':'CONTROLLED','DATA_DIR':str(root/'data'),
                         'IDF_PATH':str(idf),'APP_PYTHON':str(app_python),'MCP_COMPACT_INVENTORY':''},
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                selected = Path(result.stdout.splitlines()[-1])
                self.assertEqual(selected.name, 'inventory.json' if exit_code == 0 else 'unavailable.json')
                self.assertTrue((selected.parent/'inventory.json').exists())
                if exit_code:
                    self.assertFalse(selected.exists())
                    self.assertEqual(CompactRuntime(object(),inventory_file=selected).inventories(), (None,None))


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
                result = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'search_catalog','arguments':{'cursor':{'stale':True},'offset':5,'limit':50}}})
                payload = json.loads(result.json()['result']['content'][0]['text'])
                self.assertTrue(payload['ok'], payload)
                self.assertEqual(len(payload['items']), 50)
                self.assertEqual(payload['total'], 524)
                self.assertTrue(payload['has_more'])
                self.assertNotIn('next_cursor', payload)
                result = await client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'search_catalog','arguments':{'cursor':'stale','other':1}}})
                payload = json.loads(result.json()['result']['content'][0]['text'])
                self.assertEqual(payload['error']['code'], 'invalid_argument')
