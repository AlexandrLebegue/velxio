"""Parameterized error contracts for all six services and the actual SDK callback."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from jsonschema import validate
from app.mcp.compact import Catalog, ProjectStore, ProjectChecker, BuildService, TOOL_SCHEMAS
from app.mcp.compact.errors import normalize_error
from app.mcp.compact.facade import create_facade, CompactRuntime

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = {'code', 'path', 'received', 'expected', 'next_action'}


class UniformErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.catalog = Catalog.from_snapshot(ROOT / 'backend/app/mcp/compact/catalog.snapshot.json')
        self.store = ProjectStore(tmp.name, catalog=self.catalog)
        self.checker = ProjectChecker(self.store, self.catalog)
        self.builds = BuildService(self.store, self.checker)
        self.addAsyncCleanup(self.builds.close)

    def assert_error(self, name, result, path=None):
        self.assertFalse(result['ok'], result)
        error = result['error']
        self.assertTrue(REQUIRED <= error.keys(), error)
        for key in REQUIRED:
            self.assertIsInstance(error[key], str)
            if key != 'path':
                self.assertTrue(error[key])
        self.assertLessEqual(len(error['received']), 200)
        self.assertLessEqual(len(error['next_action']), 500)
        if path is not None:
            self.assertEqual(error['path'], path)
        validate(result, TOOL_SCHEMAS[name]['outputSchema'])

    async def test_parameterized_service_argument_errors_for_all_six_tools(self):
        cases = [('search_catalog', {'limit': 0}, '/limit'),
                 ('get_reference', {}, '/id'),
                 ('save_project', {'sketch': 123}, '/sketch'),
                 ('check_project', {}, '/project_id'),
                 ('build_project', {'action': 'invalid'}, '/action'),
                 ('read_artifact', {}, '/artifact_id')]
        for name, arguments, path in cases:
            with self.subTest(tool=name):
                target = self.catalog if name in ('search_catalog', 'get_reference') else self.checker if name == 'check_project' else self.builds if name == 'build_project' else self.store
                result = getattr(target, name)(**arguments)
                if name == 'build_project':
                    result = await result
                self.assert_error(name, result, path)

    async def test_parameterized_sdk_schema_rejection_for_all_six_tools(self):
        # Exercise the registered callback, retaining the real JSON validator.
        class SDK:
            def __init__(self, *args, **kwargs):
                self._mcp_server = self
            def list_tools(self):
                return lambda callback: callback
            def call_tool(self, **kwargs):
                def register(callback):
                    self.callback = callback
                    return callback
                return register
            def streamable_http_app(self):
                return object()
        sdk = SDK()
        with patch('mcp.server.fastmcp.FastMCP', return_value=sdk):
            _, _, runtime = create_facade(object(), catalog=self.catalog, root=self.store.root)
        self.addAsyncCleanup(runtime.close)
        for name in TOOL_SCHEMAS:
            with self.subTest(tool=name):
                response = await sdk.callback(name, {'unexpected': True})
                self.assert_error(name, json.loads(response[0].text))
        response = await sdk.callback('read_artifact', {'artifact_id': 'a_' + '0' * 32})
        self.assert_error('read_artifact', json.loads(response[0].text))

    async def test_domain_and_infrastructure_failures_are_uniform_without_retry_loops(self):
        cases = [('get_reference', self.catalog.get_reference(id='component:missing')),
                 ('get_reference', self.catalog.get_reference(id='arduino-uno')),
                 ('check_project', self.checker.check_project(project_id='p_' + '0' * 32, version='0' * 64)),
                 ('read_artifact', self.store.read_artifact(artifact_id='a_' + '0' * 32)),
                 ('build_project', await self.builds.build_project(action='start', project_id='p_' + '0' * 32, version='0' * 64, board_id='board')),
                 ('build_project', await self.builds.build_project(action='start', wait_seconds=float('inf')))]
        for name, result in cases:
            with self.subTest(tool=name, code=result['error']['code']):
                self.assert_error(name, result)
        runtime = CompactRuntime(object(), catalog=self.catalog)
        self.addAsyncCleanup(runtime.close)
        runtime.closing = True
        for name in TOOL_SCHEMAS:
            self.assert_error(name, await runtime.call(name, {}))

    async def test_native_details_and_bounded_received_are_preserved(self):
        result = self.store.save_project(sketch='void setup(){}\nvoid loop(){}')
        updated = self.store.save_project(project_id=result['project_id'], expected_version=result['version'], sketch='void setup(){}\nvoid loop(){delay(1);}')
        stale = self.store.save_project(project_id=result['project_id'], expected_version=result['version'], sketch='void setup(){}\nvoid loop(){}')
        self.assertTrue(updated['ok'])
        self.assert_error('save_project', stale)
        self.assertIn('stale', stale['error']['next_action'])
        invalid = self.store.save_project(sketch={'large': 'é' * 10000})
        self.assert_error('save_project', invalid, '/sketch')
        self.assertEqual(normalize_error(invalid, 'save_project', {}), invalid)
