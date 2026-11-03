"""EXPLICITLY MONKEYPATCHED SERVICES. No real compile, setup, network or ASGI server."""

import ast
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
import sys
import hashlib
import json
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.mcp.compact.offline_owner import RestCompileOwner, BoundOfflineAdapter
from app.mcp.compact.builds import OwnerQueueAdapter, ToolchainInventory
from app.mcp.compact.checks import CompilerPolicy


def actual_method(file, name):
    """Load only an actual pure guard method AST: no SDK/import/init side effects."""
    tree = ast.parse((ROOT / file).read_bytes())
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), file, 'exec'), namespace)
    return namespace[name]


class OfflineOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.retry = ContextVar('controlled_retry', default=True)
        self.admissions = []
        self.compiles = []
        self.release = None
        test = self
        class Gate:
            @asynccontextmanager
            async def slot(self, **kwargs):
                test.admissions.append(kwargs)
                try:
                    yield
                finally:
                    test.admissions.append({'released': True})
        self.gate = Gate()
        async def offline(*args, **kwargs):
            self.compiles.append((args, kwargs, self.retry.get()))
            if self.release:
                await self.release.wait()
            return {'success': True, 'binary_content': 'AQID', 'binary_type': 'bin', 'stdout': 'main.c:1: warning: EXPLICIT SERVICE DOUBLE\n'}
        self.idf = SimpleNamespace(compile_offline=AsyncMock(side_effect=offline))
        self.arduino = SimpleNamespace(compile_offline=AsyncMock(side_effect=offline))
        self.scope = AsyncMock(return_value=({'GxEPD2'}, 'controlled-owner'))
        self.priority = AsyncMock(return_value=(10, 'controlled-tier', 7))
        self.admit = AsyncMock(return_value=({'GxEPD2'}, True, None, None))
        self.owner = RestCompileOwner.for_tests(lane_for=lambda heavy: self.gate, arduino=self.arduino, idf=self.idf,
            request_model=lambda **kw: SimpleNamespace(**kw), resolve_scope=self.scope, resolve_priority=self.priority,
            admit=self.admit, retry_context=self.retry)
        self.app = object()
        self.owner.activate(self.app)
        self.addAsyncCleanup(self.owner.close)
        self.request = SimpleNamespace(app=self.app)
        self.adapter = self.owner.bind(self.request, 'requester')
        self.payload = {'files': [{'name': 'main.c', 'content': 'CONTROLLED'}], 'board_fqbn': 'esp32:esp32:esp32',
            'board_kind': 'esp32', 'project_id': 'controlled-project', 'board_options': {'flashSize': '8MB'},
            'libraries': ['GxEPD2'], 'spiffs_files': [{'name': 'x.bin', 'content_b64': 'AQID'}], 'language': 'espidf',
            'toolchain': {'members': [{'path': 'CONTROLLED'}]}, 'library_proofs': {'GxEPD2': {}}, 'request_key': 'controlled-key'}

    async def test_idf_selection_same_gate_scope_priority_and_mapping(self):
        logs, running = [], []
        result = await self.adapter.compile(self.payload, lambda: running.append(True), logs.append)
        self.assertTrue(self.adapter.test_only)
        self.assertTrue(result['success'])
        self.assertEqual(result['firmware'], b'\x01\x02\x03')
        self.assertEqual(self.admissions, [{'priority': 10, 'key': 'controlled-key'}, {'released': True}])
        self.assertEqual(running, [True])
        self.idf.compile_offline.assert_awaited_once()
        self.arduino.compile_offline.assert_not_awaited()
        args, kwargs, retry = self.compiles[0]
        self.assertEqual(args[0], self.payload['files'])
        self.assertEqual(kwargs['board_options'], self.payload['board_options'])
        self.assertEqual(kwargs['spiffs_files'], self.payload['spiffs_files'])
        self.assertEqual(kwargs['allowed_libraries'], {'GxEPD2'})
        self.assertEqual(kwargs['owner_id'], 'controlled-owner')
        self.assertEqual(kwargs['cpu_nice'], 7)
        self.assertTrue(kwargs['pure_idf'])
        self.assertFalse(retry)
        self.assertTrue(self.retry.get())
        self.assertIn('EXPLICIT SERVICE DOUBLE', ''.join(logs))

    async def test_arduino_selection_and_no_idf_or_install_fallback(self):
        self.payload.update(board_fqbn='arduino:avr:uno', language='arduino')
        await self.adapter.compile(self.payload, lambda: None, lambda _: None)
        self.arduino.compile_offline.assert_awaited_once()
        self.idf.compile_offline.assert_not_awaited()
        self.arduino.compile_offline.reset_mock()
        self.payload.update(board_fqbn='esp32:esp32:esp32', language='espidf')
        self.idf.compile_offline.side_effect = None
        self.idf.compile_offline.return_value = {'success': False, 'error_kind': 'dependency_unavailable'}
        result = await self.adapter.compile(self.payload, lambda: None, lambda _: None)
        self.assertEqual(result['error_kind'], 'dependency_unavailable')
        self.arduino.compile_offline.assert_not_awaited()

    async def test_client_cancellation_does_not_release_slot_before_drain(self):
        self.release = asyncio.Event()
        call = asyncio.create_task(self.adapter.compile(self.payload, lambda: None, lambda _: None))
        while not self.compiles:
            await asyncio.sleep(0)
        call.cancel()
        await asyncio.sleep(0)
        self.assertFalse(call.done())
        self.assertNotIn({'released': True}, self.admissions)
        closing = asyncio.create_task(self.owner.close())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        self.assertFalse(self.adapter.ready)
        closing.cancel()
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        self.release.set()
        self.assertTrue((await call)['success'])
        await closing
        self.assertIn({'released': True}, self.admissions)

    async def test_changed_scope_or_refusal_no_compile(self):
        self.admit.return_value = ({'Other'}, False, None, None)
        with self.assertRaisesRegex(ValueError, 'changed'):
            await self.adapter.compile(self.payload, lambda: None, lambda _: None)
        self.assertFalse(self.compiles)
        self.assertFalse(self.admissions)
        self.admit.return_value = ({'GxEPD2'}, False, None, object())
        with self.assertRaisesRegex(ValueError, 'refused'):
            await self.adapter.compile(self.payload, lambda: None, lambda _: None)
        self.assertFalse(self.compiles)

    async def test_no_fake_production_binding_and_pid_lifespan_guards(self):
        self.assertFalse(OwnerQueueAdapter(lambda _: self.gate, self.idf.compile_offline, test_only=False).ready)
        with self.assertRaises(TypeError):
            BoundOfflineAdapter(object(), self.owner, self.request, None)
        with self.assertRaises(ValueError):
            RestCompileOwner.from_route(ModuleType('fake-route'))
        with self.assertRaises(TypeError):
            RestCompileOwner.for_tests(test_only=False)
        with self.assertRaises(ValueError):
            self.owner.bind(SimpleNamespace(app=object()))
        self.owner.pid = -1
        with self.assertRaises(ValueError):
            await self.adapter.compile(self.payload, lambda: None, lambda _: None)
        import os
        self.owner.pid = os.getpid()

    async def test_actual_offline_service_guards_never_call_normal_compile(self):
        forbidden = AsyncMock(side_effect=AssertionError('REAL COMPILATION/INSTALL FORBIDDEN IN TEST'))
        service = SimpleNamespace(compile=forbidden, ensure_core_for_board=forbidden, install_core=forbidden)
        arduino = actual_method('backend/app/services/arduino_cli.py', 'compile_offline')
        idf = actual_method('backend/app/services/espidf_compiler.py', 'compile_offline')
        result = await arduino(service, [], 'arduino:avr:uno')
        self.assertEqual(result['error_kind'], 'core_unavailable')
        evidence = {'arduino_core': {'id': 'arduino:avr', 'version': 'CONTROLLED', 'platform_sha256': 'x'}}
        result = await arduino(service, [], 'arduino:avr:uno', offline_evidence=evidence, allowed_libraries=set(), library_proofs={})
        self.assertEqual(result['error_kind'], 'offline_guard_unavailable')
        result = await idf(service, [], 'esp32:esp32:esp32', offline_evidence={'members': ['CONTROLLED']}, allowed_libraries={'missing'}, library_proofs={})
        self.assertEqual(result['error_kind'], 'dependency_unavailable')
        result = await idf(service, [], 'esp32:esp32:esp32', offline_evidence={'members': ['CONTROLLED']}, allowed_libraries=set(), library_proofs={})
        self.assertEqual(result['error_kind'], 'dependency_unavailable')
        forbidden.assert_not_awaited()

    async def test_existing_file_behavior_fingerprints_still_match(self):
        policy = CompilerPolicy(ROOT)
        self.assertEqual(policy.prefix, 'user_')
        self.assertIn('main.cpp', policy.reserved)

    async def test_core_inventory_requires_real_local_platform_and_boards_hashes(self):
        with tempfile.TemporaryDirectory(prefix='offline-core-proof-') as root:
            path = Path(root)
            members = []
            for name in ('platform.txt', 'boards.txt'):
                file = path / name
                file.write_text('EXPLICIT CONTROLLED CORE PROOF, NOT AN INSTALLED COMPILER')
                members.append({'path': name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
            key = 'arduino:avr:uno|arduino'
            core = {'id': 'arduino:avr', 'version': 'CONTROLLED',
                    'platform_path': 'platform.txt', 'platform_sha256': members[0]['sha256'],
                    'boards_path': 'boards.txt', 'boards_sha256': members[1]['sha256']}
            manifest = {'kind': 'toolchain', 'name': key, 'version': 'CONTROLLED', 'test_only': True, 'members': members, 'arduino_core': core}
            file = path / 'manifest.json'
            file.write_text(json.dumps(manifest))
            inventory = ToolchainInventory(root, {key: {'path': file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}}, complete=True)
            self.assertEqual(inventory.verify()['toolchains'][key]['arduino_core'], core)
            (path / 'boards.txt').write_text('modified')
            with self.assertRaises(ValueError):
                inventory.verify()


if __name__ == '__main__':
    unittest.main()
