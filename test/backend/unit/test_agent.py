"""Project isolation, tool contracts and lifecycle tests; no external model required."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.agent.runtime import AgentRuntime
from app.agent.settings import AgentError, ConnectionSettings
from app.agent.workspace import Workspace, project_revision
from app.mcp.compact.catalog import Catalog


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

    def test_wire_defaults_are_normalized_before_hashing(self):
        value = document()
        value["wires"] = [{"id": "w", "start": {"componentId": "uno", "pinName": "13"}, "end": {"componentId": "uno", "pinName": "12"}}]
        before = project_revision(value)
        value["wires"][0].update(color="#00c853", waypoints=[])
        self.assertEqual(before, project_revision(value))
        value["wires"][0]["waypoints"] = [{"x": 3, "y": 5}]
        self.assertNotEqual(before, project_revision(value))

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

    async def test_esp32_run_refuses_before_browser_or_build_dispatch(self):
        value = document()
        value['boards'][0]['boardKind'] = 'esp32'
        session = self.runtime.create('owner', value)
        with patch.object(self.runtime, 'browser_command', new=AsyncMock()) as browser:
            result = await asyncio.wait_for(self.runtime.call_tool(session, 'run_project', {}), .5)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'unsupported')
        self.assertEqual(result['state'], 'unsupported')
        self.assertFalse(result['confirmed'])
        browser.assert_not_awaited()

    async def test_esp32_pending_harness_tool_refuses_without_waiting_for_dispatch(self):
        value = document()
        value['boards'][0]['boardKind'] = 'esp32'
        session = self.runtime.create('owner', value)
        async def events(ready):
            ready.set()
            yield {'type': 'message.part.updated', 'properties': {'part': {
                'id': 'pending-run', 'messageID': 'assistant', 'sessionID': 'harness',
                'type': 'tool', 'tool': 'velxio_run_project', 'state': {'status': 'pending', 'input': {}, 'raw': ''}}}}
            await asyncio.Event().wait()  # Reproduce a provider that never finishes arguments.
        session.adapter = SimpleNamespace(session_id='harness', events=events)
        done = asyncio.get_running_loop().create_future()
        collector = asyncio.create_task(self.runtime._collect(session, asyncio.Event(), done))
        try:
            with self.assertRaises(AgentError) as caught:
                await asyncio.wait_for(done, .5)
            self.assertEqual(caught.exception.code, 'unsupported')
            self.assertEqual(session.pending, {})
        finally:
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
            session.adapter = None

    async def test_catalog_uses_existing_metadata(self):
        session = self.runtime.create("owner", document())
        response = await self.runtime.call_tool(session, "search_catalog", {"query": "led", "kind": "component"})
        self.assertTrue(response["ok"])
        self.assertTrue(response["items"])
        for item in response["items"]:
            self.assertEqual(item["metadataId"], item["id"].removeprefix("component:"))

    async def test_agent_catalog_recovers_multiword_search_and_exposes_pagination(self):
        session = self.runtime.create("owner", document())
        response = await self.runtime.call_tool(session, "search_catalog", {"query": "e-ink epaper 1.54", "kind": "component", "limit": 10})
        self.assertTrue(any(item["id"] == "component:epaper-1in54-bw" for item in response["items"]))
        self.assertEqual(response["query_original"], "e-ink epaper 1.54")
        self.assertTrue(set(response["query_used"]) & {"e-ink", "epaper", "1.54"})
        page = await self.runtime.call_tool(session, "search_catalog", {"kind": "component", "limit": 1})
        self.assertEqual(page["next_offset"], 1)
        following = await self.runtime.call_tool(session, "search_catalog", {"kind": "component", "limit": 1, "offset": page["next_offset"]})
        self.assertNotEqual(page["items"][0]["id"], following["items"][0]["id"])

    async def test_panel_reference_exposes_readable_library_example(self):
        session = self.runtime.create("owner", document())
        reference = await self.runtime.call_tool(session, "get_reference", {"id": "component:epaper-1in54-bw"})
        examples = reference["data"]["example_references"]
        self.assertIn("example:epaper-1in54-uno-hello", examples)
        code = await self.runtime.call_tool(session, "get_reference", {"id": examples[0], "section": "code"})
        self.assertTrue(code["ok"])
        self.assertIn("GxEPD2_BW", json.dumps(code["data"]))
        recommended = reference["data"]["recommended_example"]
        self.assertTrue(recommended["matches_active_board"])
        self.assertFalse(recommended["adapt_board_pins"])
        self.assertEqual(recommended["board_kinds"], ["arduino-uno"])
        self.assertIn("GxEPD2", recommended["libraries"])

    async def test_recommendation_ranks_matching_board_and_failed_lookup_suggests_real_ids(self):
        snapshot = json.loads((Path(__file__).resolve().parents[3] / "backend/app/mcp/compact/catalog.snapshot.json").read_text())
        example = next(item for item in snapshot["entries"] if item["id"] == "example:epaper-1in54-uno-hello")
        clone = json.loads(json.dumps(example))
        clone.update(id="example:test-epaper-esp32", key="test-epaper-esp32")
        clone["project"]["boardType"] = "esp32"
        snapshot["entries"].append(clone)
        self.runtime.catalog = Catalog(snapshot)
        value = document()
        value["boards"][0]["boardKind"] = "esp32"
        session = self.runtime.create("owner", value)
        reference = await self.runtime.call_tool(session, "get_reference", {"id": "component:epaper-1in54-bw"})
        self.assertEqual(reference["data"]["recommended_example"]["id"], clone["id"])
        self.assertTrue(reference["data"]["recommended_example"]["matches_active_board"])
        missing = await self.runtime.call_tool(session, "get_reference", {"id": "example:epaper-2in13-esp32-weather", "section": "code"})
        self.assertFalse(missing["ok"])
        self.assertTrue(missing["error"]["suggestions"])
        for item in missing["error"]["suggestions"]:
            self.assertTrue(self.runtime.get_catalog().get_reference(id=item["id"], section="code")["ok"])

    async def test_add_component_defaults_unique_ids_positions_and_preserves_staged_sources(self):
        session = self.runtime.create("owner", document())
        source = session.workspace.work / "group-1/sketch.ino"
        source.write_text("// staged source\nvoid setup() {} void loop() {}")
        actions = []
        async def browser(_, action, **payload):
            actions.append(action)
            candidate = payload["document"]
            return {"ok": True, "document": candidate, "revision": project_revision(candidate)}
        with patch.object(self.runtime, "browser_command", side_effect=browser):
            first = await self.runtime.call_tool(session, "add_component", {"component": "component:led", "properties": {"color": "blue"}, "x": 0})
            second = await self.runtime.call_tool(session, "add_component", {"component": "led"})
            duplicate = await self.runtime.call_tool(session, "add_component", {"component": "led", "instance_id": "uno"})
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["component"]["id"], "led-1")
        self.assertEqual(first["component"]["x"], 0)
        self.assertEqual(first["component"]["properties"]["color"], "blue")
        self.assertEqual(first["component"]["properties"]["brightness"], 1)
        self.assertEqual(second["component"]["id"], "led-2")
        self.assertNotEqual(first["component"]["x"], second["component"]["x"])
        self.assertEqual(duplicate["error"]["code"], "duplicate_id")
        self.assertEqual(len(session.workspace.document["components"]), 2)
        self.assertIn("staged source", session.workspace.document["fileGroups"]["sketch"][0]["content"])
        self.assertIn("staged source", source.read_text())
        self.assertEqual(actions, ["validate_circuit", "apply"] * 2)

    async def test_add_component_refusal_and_unknown_type_leave_project_unchanged(self):
        session = self.runtime.create("owner", document())
        before = session.workspace.revision
        with patch.object(self.runtime, "browser_command", new=AsyncMock(return_value={"ok": False, "error": {"code": "component_unknown"}})) as browser:
            refused = await self.runtime.call_tool(session, "add_component", {"component": "led"})
            unknown = await self.runtime.call_tool(session, "add_component", {"component": "__missing_part__"})
        self.assertFalse(refused["ok"] or unknown["ok"])
        self.assertEqual(browser.await_count, 1)
        self.assertEqual(session.workspace.revision, before)
        self.assertEqual(session.workspace.document["components"], [])

    async def test_connection_batch_is_atomic_preserves_old_wires_and_supports_single_pair(self):
        value = document()
        value["wires"] = [{"id": "old", "start": {"componentId": "uno", "pinName": "13"}, "end": {"componentId": "uno", "pinName": "12"}}]
        session = self.runtime.create("owner", value)
        pairs = [{"from": {"componentId": "uno", "pinName": "11"}, "to": {"componentId": "uno", "pinName": pin}} for pin in ["10", "9"]]
        async def browser(_, action, **payload):
            candidate = payload["document"]
            return {"ok": True, "document": candidate, "revision": project_revision(candidate)}
        with patch.object(self.runtime, "browser_command", side_effect=browser) as bridge:
            result = await self.runtime.call_tool(session, "connect_pins", {"connections": pairs})
            self.assertEqual(bridge.await_count, 2)
            self.assertEqual(result["added_connections"], 2)
            self.assertEqual(len(set(result["connection_ids"])), 2)
            self.assertEqual(session.workspace.document["wires"][0]["id"], "old")
            self.assertEqual(len(session.workspace.document["wires"]), 3)
            single = await self.runtime.call_tool(session, "connect_pins", pairs[0])
            self.assertTrue(single["ok"])
        before = session.workspace.revision
        async def reject(_, action, **payload):
            self.assertEqual(action, "validate_circuit")
            return {"ok": False, "error": {"code": "pin_invalid", "details": {"wire_id": payload["document"]["wires"][-1]["id"], "pin": "__bad__"}}}
        pairs[1]["to"]["pinName"] = "__bad__"
        with patch.object(self.runtime, "browser_command", side_effect=reject) as bridge:
            failed = await self.runtime.call_tool(session, "connect_pins", {"connections": pairs})
        self.assertEqual(bridge.await_count, 1)
        self.assertEqual(failed["error"]["connection_index"], 1)
        self.assertEqual(failed["error"]["connection"]["to"]["pinName"], "__bad__")
        self.assertEqual(session.workspace.revision, before)
        self.assertEqual(len(session.workspace.document["wires"]), 4)

    async def test_mcp_accepts_single_or_batch_connections_and_rejects_mixed_formats(self):
        from app.agent.tools import create_tools
        session = self.runtime.create("owner", document())
        session.task = asyncio.create_task(asyncio.sleep(30))
        tools, manager = create_tools(self.runtime)
        app = FastAPI()
        app.mount("/tools", tools)
        pair = {"from": {"componentId": "uno", "pinName": "13"}, "to": {"componentId": "uno", "pinName": "12"}}
        headers = {"Authorization": "Bearer " + session.token, "Accept": "application/json, text/event-stream"}
        async with manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:1234", headers=headers) as client:
                listing = (await client.post("/tools/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})).json()
                self.assertEqual([tool["name"] for tool in listing["result"]["tools"]],
                                 ['search_component','components','connect','run'])
                with patch.object(self.runtime, "call_tool", new=AsyncMock(return_value={"ok": True})) as call:
                    for index, arguments in enumerate([pair, {"connections": [pair]}, {"connections": [pair], "from": pair["from"]}, {**pair, "connections": [pair]}, {"connections": []}]):
                        response = (await client.post("/tools/mcp", json={"jsonrpc": "2.0", "id": index + 2, "method": "tools/call", "params": {"name": "connect_pins", "arguments": arguments}})).json()
                        result = json.loads(response["result"]["content"][0]["text"])
                        self.assertEqual(result["ok"], index < 2)
                    self.assertEqual(call.await_count, 2)

    async def test_board_swap_preserves_sources_ids_and_maps_pins_before_validation(self):
        value = document()
        value["wires"] = [{"id": "w", "start": {"componentId": "uno", "pinName": "13"}, "end": {"componentId": "uno", "pinName": "12"}}]
        session = self.runtime.create("owner", value)
        source = session.workspace.work / "group-1/sketch.ino"
        source.write_text("// staged changes\nvoid setup() {} void loop() {}")
        actions = []
        async def browser(_, action, **payload):
            actions.append(action)
            candidate = payload["document"]
            self.assertEqual(candidate["boards"][0]["boardKind"], "esp32")
            self.assertEqual(candidate["boards"][0]["id"], "uno")
            self.assertEqual(candidate["boards"][0]["activeFileGroupId"], "sketch")
            self.assertEqual(candidate["wires"][0]["start"]["pinName"], "23")
            return {"ok": True, "document": candidate, "revision": project_revision(candidate), "applied_revision": project_revision(candidate)}
        with patch.object(self.runtime, "browser_command", side_effect=browser):
            result = await self.runtime.call_tool(session, "change_board", {"board": "esp32", "pin_map": {"13": "23"}})
        self.assertTrue(result["ok"] and result["sources_preserved"])
        self.assertEqual(actions, ["validate_circuit", "apply"])
        self.assertIn("staged changes", source.read_text())
        self.assertEqual(session.workspace.groups, {"sketch": "group-1"})

    async def test_board_swap_refuses_invalid_wiring_without_changing_board(self):
        session = self.runtime.create("owner", document())
        initial = session.workspace.revision
        with patch.object(self.runtime, "browser_command", new=AsyncMock(return_value={"ok": False, "error": {"code": "pin_invalid"}})) as browser:
            result = await self.runtime.call_tool(session, "change_board", {"board": "esp32"})
        self.assertFalse(result["ok"])
        self.assertEqual(session.workspace.revision, initial)
        self.assertEqual(session.workspace.document["boards"][0]["boardKind"], "arduino-uno")
        self.assertEqual(browser.await_count, 1)

    async def test_project_context_and_reference_include_live_pins_without_section_hunting(self):
        session = self.runtime.create("owner", document())
        session.browser_seen = time.monotonic()
        async def browser(_, action, **payload):
            if action == "inspect_project": return {"ok": True, "pinouts": {"uno": {"pins": ["13", "GND.1"]}}}
            self.assertEqual(action, "describe_part")
            return {"ok": True, "pins": [{"name": "A"}, {"name": "C"}], "defaults": {"color": "red"}, "attrs": [{"name": "color"}]}
        with patch.object(self.runtime, "browser_command", side_effect=browser):
            project = await self.runtime.call_tool(session, "get_project", {})
            reference = await self.runtime.call_tool(session, "get_reference", {"id": "component:led"})
        self.assertEqual(project["pinouts"]["uno"]["pins"], ["13", "GND.1"])
        self.assertTrue(project["capabilities"]["edit_components"])
        self.assertEqual(reference["data"]["pins"], [{"name": "A"}, {"name": "C"}])
        self.assertEqual(reference["data"]["defaults"]["color"], "red")
        template = reference["data"]["instance_template"]
        self.assertEqual(template["metadataId"], "led")
        self.assertEqual(template["properties"], {"color": "red"})
        # The exact reference output must be accepted as a project instance.
        session.workspace.update_circuit([{"op": "set", "path": "/components", "value": [template]}])
        self.assertEqual(session.workspace.document["components"][0], template)

    async def test_empty_workspace_accepts_esp32_and_rolls_back_if_editor_refuses(self):
        empty = {"format": "velxio-project", "version": 1, "boards": [], "fileGroups": {}, "components": [], "wires": [], "activeBoardId": None}
        session = self.runtime.create("owner", empty)
        async def browser(_, action, **payload):
            self.assertEqual(action, "create")
            self.assertEqual(payload["document"]["boards"][0]["boardKind"], "esp32")
            return {"ok": False, "error": {"code": "editor_error"}}
        with patch.object(self.runtime, "browser_command", side_effect=browser):
            self.assertFalse((await self.runtime.call_tool(session, "create_project", {"board": "esp32"}))["ok"])
        self.assertEqual(session.workspace.document["boards"], [])
        self.assertEqual(session.workspace.groups, {})
        self.assertEqual(session.workspace.capture()["boards"], [])

    async def test_reasoning_parts_never_enter_answer_stream_and_early_deltas_are_buffered(self):
        session = self.runtime.create("owner", document())
        session.active_turn = "turn"
        self.runtime.emit(session, "turn.started", {"turn_id": "turn", "message_index": 0})
        async def events(ready):
            ready.set()
            for item in [
                {"type": "message.part.delta", "properties": {"sessionID": "s", "partID": "r", "field": "text", "delta": "Reasoning only"}},
                {"type": "message.part.updated", "properties": {"part": {"id": "r", "sessionID": "s", "type": "reasoning", "text": ""}}},
                {"type": "message.part.updated", "properties": {"part": {"id": "a", "sessionID": "s", "type": "text", "text": ""}}},
                {"type": "message.part.delta", "properties": {"sessionID": "s", "partID": "a", "field": "text", "delta": "Answer"}},
            ]: yield item
        session.adapter = SimpleNamespace(session_id="s", events=events)
        await self.runtime._collect(session, asyncio.Event(), asyncio.get_running_loop().create_future())
        session.adapter = None
        self.assertEqual([e["payload"]["text"] for e in session.events if e["type"] == "message.delta"], ["Answer"])
        self.assertEqual(session.turns[0]["reasoning"]["r"], "Reasoning only")
        self.assertTrue(all(e["turn_id"] == "turn" for e in session.events))

    async def test_invalid_circuit_is_not_committed_and_action_failure_is_retained(self):
        session = self.runtime.create("owner", document())
        session.messages.append({"role": "user", "content": "Connect the pins"})
        session.active_turn = "turn"
        self.runtime.emit(session, "turn.started", {"turn_id": "turn", "message_index": 0})
        session.browser_seen = time.monotonic()
        initial = session.workspace.revision
        operation = asyncio.create_task(self.runtime.call_tool(session, "connect_pins", {"from": {"componentId": "uno", "pinName": "typo"}, "to": {"componentId": "uno", "pinName": "12"}}))
        await asyncio.sleep(0)
        command = session.events[-1]["payload"]
        self.assertEqual(command["action"], "validate_circuit")
        session.pending[command["command_id"]].set_result({"ok": False, "error": {"code": "pin_invalid", "message": "Unknown pin typo"}})
        self.assertFalse((await operation)["ok"])
        self.assertEqual(session.workspace.revision, initial)
        self.assertEqual(session.workspace.document["wires"], [])
        self.assertEqual(session.turns[0]["steps"][0]["status"], "error")
        self.runtime.emit(session, "turn.completed", {"turn_id": "turn"})
        session.active_turn = ""
        self.runtime.save(session)
        restored = AgentRuntime(self.directory.name).get("owner", session.id)
        self.assertEqual(restored.turns[0]["steps"][0]["status"], "error")

    async def test_connection_is_committed_only_after_validation_then_applied(self):
        session = self.runtime.create("owner", document())
        session.browser_seen = time.monotonic()
        operation = asyncio.create_task(self.runtime.call_tool(session, "connect_pins", {"from": {"componentId": "uno", "pinName": "13"}, "to": {"componentId": "uno", "pinName": "12"}}))
        await asyncio.sleep(0)
        validate = session.events[-1]["payload"]
        self.assertEqual(session.workspace.document["wires"], [])
        session.pending[validate["command_id"]].set_result({"ok": True, "revision": validate["revision"]})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        apply = next(e["payload"] for e in reversed(session.events) if e["type"] == "browser.command" and e["payload"]["action"] == "apply")
        session.pending[apply["command_id"]].set_result({"ok": True, "applied_revision": apply["revision"]})
        result = await operation
        self.assertTrue(result["validated"] and result["applied"])
        self.assertEqual(len(session.workspace.document["wires"]), 1)

    async def test_browser_pin_resolution_is_validated_before_apply_and_disconnect_keeps_previous_project(self):
        from app.agent.workspace import project_revision
        session = self.runtime.create("owner", document())
        session.browser_seen = time.monotonic()
        operation = asyncio.create_task(self.runtime.call_tool(session, "connect_pins", {"from": {"componentId": "uno", "pinName": "D13"}, "to": {"componentId": "uno", "pinName": "12"}}))
        await asyncio.sleep(0)
        validate = session.events[-1]["payload"]
        resolved = validate["document"]
        resolved["wires"][0]["start"]["pinName"] = "13"
        session.pending[validate["command_id"]].set_result({"ok": True, "document": resolved, "revision": project_revision(resolved)})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        apply = session.events[-1]["payload"]
        self.assertEqual(apply["action"], "apply")
        self.assertEqual(apply['document']['wires'][0]['start']['pinName'],'13')
        self.assertEqual(session.workspace.document['wires'],[])
        session.pending[apply["command_id"]].set_exception(AgentError("browser_unavailable", "Disconnected"))
        self.assertFalse((await operation)["ok"])
        self.assertEqual(session.workspace.document["wires"], [])

    async def test_retained_steps_stay_attached_to_messages_when_history_is_trimmed(self):
        session = self.runtime.create("owner", document())
        session.messages = [{"role": "user", "content": str(index)} for index in range(110)]
        session.active_turn = "recent-turn"
        self.runtime.emit(session, "turn.started", {"turn_id": session.active_turn})
        self.runtime.emit(session, "tool.state", {"call_id": "read", "name": "get_project", "status": "completed"})
        session.active_turn = ""
        self.runtime.save(session)
        restored = AgentRuntime(self.directory.name).get("owner", session.id)
        self.assertEqual(len(restored.messages), 100)
        self.assertEqual(restored.turns[0]["message_index"], 99)
        self.assertEqual(restored.messages[restored.turns[0]["message_index"]]["content"], "109")

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
