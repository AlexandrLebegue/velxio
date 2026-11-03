"""Project isolation, tool contracts and lifecycle tests; no external model required."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.agent.runtime import AgentRuntime
from app.agent.settings import AgentError, ConnectionSettings
from app.agent.workspace import Workspace, project_revision


def document():
    return {"format": "velxio-project", "version": 1,
            "boards": [{"id": "uno", "boardKind": "arduino-uno", "x": 0, "y": 0, "activeFileGroupId": "sketch"}],
            "components": [], "wires": [], "fileGroups": {"sketch": [{"name": "sketch.ino", "content": "void setup() {}\nvoid loop() {}"}]}, "activeBoardId": "uno"}


class WorkspaceTests(unittest.TestCase):
    def test_sources_commit_and_compare_revision_preserves_staged_edits_on_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp), document())
            initial = workspace.revision
            source = workspace.work / "group-1/sketch.ino"
            source.write_text("void setup() {}\nvoid loop() { delay(50); }")
            workspace.commit()
            self.assertNotEqual(initial, workspace.revision)
            self.assertEqual(json.loads((Path(tmp) / ".velxio.json").read_text())["revision"], workspace.revision)
            with self.assertRaises(AgentError) as caught:
                workspace.sync(document(), initial)
            self.assertEqual(caught.exception.code, "revision_conflict")
            self.assertIn("delay(50)", source.read_text())
            self.assertTrue((Path(tmp) / "revisions" / f"{initial}.vlx").exists())

    def test_traversal_symlinks_and_oversized_sources_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp), document())
            source = workspace.work / "group-1/sketch.ino"
            source.unlink()
            source.symlink_to("/etc/passwd")
            with self.assertRaises(AgentError): workspace.capture()
            source.unlink()
            source.write_text("x" * 262145)
            with self.assertRaises(AgentError): workspace.capture()
            invalid = document()
            invalid["fileGroups"]["sketch"][0]["name"] = "../escape.ino"
            with self.assertRaises(AgentError): Workspace(Path(tmp) / "other", invalid)

    def test_circuit_validation_retains_sources_and_rejects_other_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp), document())
            workspace.update_circuit([{"op": "set", "path": "/components", "value": [{"id": "led", "metadataId": "led", "x": 5, "y": 5, "properties": {}}]}])
            self.assertEqual(workspace.document["components"][0]["id"], "led")
            with self.assertRaises(AgentError): workspace.update_circuit([{"op": "set", "path": "/name", "value": "oops"}])

    def test_export_timestamp_does_not_change_revision(self):
        value = document()
        before = project_revision(value)
        value["exportedAt"] = "2026-11-03T10:00:00Z"
        value["name"] = "Renamed"
        self.assertEqual(before, project_revision(value))

    def test_runtime_baud_and_wire_geometry_do_not_create_false_conflicts(self):
        value = document()
        value["components"] = [{"id": "led", "metadataId": "led", "x": 1, "y": 2, "properties": {}}]
        value["wires"] = [{"id": "w", "start": {"componentId": "uno", "pinName": "13", "x": 0, "y": 0}, "end": {"componentId": "led", "pinName": "A", "x": 1, "y": 2}}]
        before = project_revision(value)
        value["boards"][0]["serialBaudRate"] = 9600
        value["components"][0]["properties"].update(state=True, value=True)
        value["wires"][0]["start"]["x"] = 999
        value["wires"][0]["signalType"] = "digital"
        self.assertEqual(before, project_revision(value))
        value["wires"][0]["start"]["pinName"] = "12"
        self.assertNotEqual(before, project_revision(value))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = AgentRuntime(self.directory.name)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def test_owner_isolation_secret_redaction_and_restart(self):
        session = self.runtime.create("owner-a", document())
        with self.assertRaises(AgentError): self.runtime.get("owner-b", session.id)
        public = self.runtime.settings.save("owner-a", ConnectionSettings(model="probe", api_key="secret"))
        self.assertNotIn("secret", json.dumps(public))
        self.runtime.settings.save("owner-a", ConnectionSettings(model="probe", api_key=""))
        self.assertEqual(self.runtime.settings.read("owner-a").api_key, "secret")
        self.assertEqual((Path(self.directory.name) / "owner-a/connection.json").stat().st_mode & 0o777, 0o600)
        restored = AgentRuntime(self.directory.name).get("owner-a", session.id)
        self.assertEqual(restored.workspace.revision, session.workspace.revision)
        self.assertFalse(restored.busy)
        self.runtime.settings.save("owner-a", ConnectionSettings(model="probe", base_url="http://another-host/v1"))
        self.assertIsNone(self.runtime.settings.read("owner-a").api_key)

    async def test_restart_marks_active_turn_interrupted_and_keeps_idempotency(self):
        session = self.runtime.create("owner", document())
        session.active_turn = "turn-before-restart"
        session.requests = {"same-request": session.active_turn}
        self.runtime.save(session)
        restored = AgentRuntime(self.directory.name).get("owner", session.id)
        self.assertEqual(restored.events[-1]["type"], "turn.interrupted")
        response = await self.runtime.start_turn(restored, "retry", "same-request", "http://unused")
        self.assertEqual(response["turn_id"], "turn-before-restart")
        self.assertFalse(restored.busy)

    async def test_create_starter_only_in_empty_project(self):
        empty = {"format": "velxio-project", "version": 1, "boards": [], "fileGroups": {}, "components": [], "wires": [], "activeBoardId": None}
        session = self.runtime.create("owner", empty)
        session.browser_seen = time.monotonic()
        create = asyncio.create_task(self.runtime.call_tool(session, "create_project", {"board": "arduino-uno"}))
        await asyncio.sleep(0)
        command = session.events[-1]["payload"]
        self.assertEqual(command["action"], "create")
        session.pending[command["command_id"]].set_result({"ok": True, "applied_revision": command["revision"]})
        self.assertTrue((await create)["ok"])
        self.assertTrue((session.workspace.work / "group-1/sketch.ino").exists())
        self.assertEqual((await self.runtime.call_tool(session, "create_project", {}))["error"]["code"], "project_not_empty")

    async def test_run_requires_browser_and_waits_for_correlated_result(self):
        session = self.runtime.create("owner", document())
        result = await self.runtime.call_tool(session, "run_project", {})
        self.assertEqual(result["error"]["code"], "browser_unavailable")
        session.browser_seen = time.monotonic()
        run = asyncio.create_task(self.runtime.call_tool(session, "run_project", {}))
        await asyncio.sleep(0)
        event = session.events[-1]
        self.assertEqual(event["type"], "browser.command")
        self.assertFalse(run.done())
        session.pending[event["payload"]["command_id"]].set_result({"ok": True, "state": "running", "applied_revision": session.workspace.revision})
        self.assertEqual((await run)["state"], "running")
        self.assertFalse(session.pending)

    async def test_catalog_uses_existing_metadata(self):
        session = self.runtime.create("owner", document())
        response = await self.runtime.call_tool(session, "search_catalog", {"query": "led"})
        self.assertTrue(response["ok"])
        self.assertTrue(response["items"])

    async def test_mcp_tokens_expire_outside_active_turn(self):
        session = self.runtime.create("owner", document())
        with self.assertRaises(AgentError): self.runtime.by_token(session.token)
        session.task = asyncio.create_task(asyncio.sleep(30))
        self.assertIs(self.runtime.by_token(session.token), session)
        with self.assertRaises(AgentError): self.runtime.by_token("invalid")
        await self.runtime.stop(session)
        with self.assertRaises(AgentError): self.runtime.by_token(session.token)

    async def test_api_private_cookies_validation_and_no_cross_owner_reads(self):
        from app.api.routes import agent
        app = FastAPI()
        app.include_router(agent.router, prefix="/api/agent")
        @app.exception_handler(AgentError)
        async def errors(request, exc):
            return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status)
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        with patch.object(agent, "runtime", self.runtime):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as first, httpx.AsyncClient(transport=transport, base_url="http://test") as second:
                response = await first.get("/api/agent/settings")
                self.assertEqual(response.status_code, 200)
                self.assertIn("HttpOnly", response.headers["set-cookie"])
                saved = await first.put("/api/agent/settings", json={"model": "probe", "api_key": "secret"})
                self.assertNotIn("secret", saved.text)
                invalid = await first.put("/api/agent/settings", json={"base_url": "file:///etc/passwd"})
                self.assertEqual(invalid.status_code, 422)
                created = (await first.post("/api/agent/sessions", json={"document": document()})).json()
                denied = await second.get(f'/api/agent/sessions/{created["id"]}')
                self.assertEqual(denied.status_code, 404)
                conflict = await first.patch(f'/api/agent/sessions/{created["id"]}/workspace', json={"document": document(), "expected_revision": "stale"})
                self.assertEqual(conflict.status_code, 409)


if __name__ == "__main__":
    unittest.main()
