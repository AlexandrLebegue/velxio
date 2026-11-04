"""Pinned AVR admission guards and preserved ESP32 dispatch; no network/compiler."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.mcp.compact.avr import compile_avr
from app.mcp.compact import Catalog, ProjectStore, ProjectChecker, TOOL_SCHEMAS

ROOT=Path(__file__).resolve().parents[3]

class AvrTests(unittest.IsolatedAsyncioTestCase):
    async def test_avr_is_explicit_and_does_not_accept_esp32(self):
        payload={'board_fqbn':'arduino:avr:uno','language':'arduino','toolchain':{}}
        with patch.dict(os.environ,{'MCP_COMPACT_AVR_ENABLED':'0'}):
            with self.assertRaisesRegex(ValueError,'not enabled'):await compile_avr(payload,lambda _:None)
        with patch.dict(os.environ,{'MCP_COMPACT_AVR_ENABLED':'1'}):
            with self.assertRaisesRegex(ValueError,'inventory'):await compile_avr(payload,lambda _:None)
            with self.assertRaisesRegex(ValueError,'ESP32'):await compile_avr({**payload,'board_fqbn':'esp32:esp32:esp32'},lambda _:None)

    async def test_native_esp32_epaper_survives_without_connect(self):
        catalog=Catalog.from_snapshot(ROOT/'backend/app/mcp/compact/catalog.snapshot.json')
        with tempfile.TemporaryDirectory() as tmp:
            store=ProjectStore(tmp,catalog=catalog)
            saved=store.save_project(from_example='example:epaper-1in54-uno-hello',parameters={'board':'esp32','text':'Hello World'})
            self.assertTrue(saved['ok'],saved)
            doc=json.loads(store.read_artifact(artifact_id=saved['project_artifact_id'],length=12288)['data'])
            pins={w['end']['pinName']:w['start']['pinName'] for w in doc['wires']}
            self.assertEqual(pins,{'CS':'5','DC':'17','RST':'16','BUSY':'4','SCK':'18','SDI':'23','VCC':'3V3','GND':'GND'})
            self.assertEqual(ProjectChecker(store,catalog).check_project(project_id=saved['project_id'],version=saved['version'])['structure_status'],'valid')
            self.assertNotIn('connect',TOOL_SCHEMAS['save_project']['inputSchema']['properties'])

    async def test_real_owner_keeps_idf_guard_with_avr_opt_in(self):
        from app.mcp.compact.offline_owner import BoundOfflineAdapter
        class Owner:
            test_only=False;active=True;closing=False;production_blockers=['IDF unavailable']
            def _owned_loop(self):pass
        with patch.dict(os.environ,{'MCP_COMPACT_AVR_ENABLED':'1'}):
            adapter=object.__new__(BoundOfflineAdapter);adapter.owner=Owner();adapter.owner.app=object();adapter.request=SimpleNamespace(app=adapter.owner.app)
            self.assertTrue(adapter.ready)
            with self.assertRaisesRegex(ValueError,'ESP32'):
                await adapter.compile({'board_fqbn':'esp32:esp32:esp32'},lambda:None,lambda _:None)
