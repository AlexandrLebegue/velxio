"""Real OpenCode + MCP + deterministic local model fixture; browser is a controlled double.

RUN_OPENCODE_TEST=1 PYTHONPATH=backend python -m unittest discover \
    -s test/backend/integration -p test_agent_opencode.py -v
"""
import asyncio
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.agent.runtime import AgentRuntime
from app.agent.settings import AgentError
from app.agent.tools import create_tools


class ModelFixture(BaseHTTPRequestHandler):
    calls = []
    failure = None
    circuit = False
    thinking = False
    swap = False
    pico = False

    @staticmethod
    def project_in(value):
        if isinstance(value, str):
            try: return ModelFixture.project_in(json.loads(value))
            except (ValueError, RecursionError): return None
        if isinstance(value, dict):
            if "boards" in value and "wires" in value: return value
            for item in value.values():
                found = ModelFixture.project_in(item)
                if found: return found
        if isinstance(value, list):
            for item in value:
                found = ModelFixture.project_in(item)
                if found: return found
        return None

    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tools = {item["function"]["name"]: item["function"] for item in body.get("tools", [])}
            used = [call["function"]["name"] for item in body["messages"] for call in item.get("tool_calls", [])]
            name, args = None, None
            if "velxio_connection_probe" in tools:
                name, args = "velxio_connection_probe", {"ok": True}
            elif self.circuit and "velxio_get_project" not in used:
                name, args = "velxio_get_project", {}
            elif self.pico and "velxio_change_board" not in used:
                name, args = "velxio_change_board", {"board": "raspberry-pi-pico", "language_mode": "micropython"}
            elif self.swap and "velxio_get_reference" not in used:
                name, args = "velxio_get_reference", {"id": "component:led", "section": "overview"}
            elif self.swap and used.count("velxio_change_board") < 2:
                name, args = "velxio_change_board", {"board": "esp32" if "velxio_change_board" not in used else "arduino-uno"}
            elif "write" not in used:
                code = "void setup() { Serial.begin(9600); pinMode(12, OUTPUT); }\nvoid loop() { digitalWrite(12, HIGH); Serial.println(42); delay(100); }\n" if self.circuit else "void setup() { Serial.begin(9600); }\nvoid loop() { Serial.println(42); delay(100); }\n"
                name, args = "write", {"filePath": "group-1/sketch.ino", "content": code}
                if self.pico:
                    args = {"filePath": "group-1/main.py", "content": "from machine import Pin\nimport time\nled = Pin(12, Pin.OUT)\nwhile True:\n    led.value(1)\n    print(42)\n    time.sleep_ms(100)\n"}
            elif self.circuit and used.count("velxio_update_circuit") < 2:
                project = self.project_in([item for item in body["messages"] if item.get("role") == "tool"])
                if not project: raise AssertionError("Project tool output not found")
                wires = project["wires"]
                wires[0]["start"]["pinName"] = "__missing_pin__" if used.count("velxio_update_circuit") == 0 else "12"
                wires[0].pop("color", None)
                wires[0].pop("waypoints", None)
                for endpoint in (wires[0]["start"], wires[0]["end"]):
                    endpoint.pop("x", None); endpoint.pop("y", None)
                name, args = "velxio_update_circuit", {"changes": [{"op": "set", "path": "/wires", "value": wires}]}
            else:
                for suffix in ("run_project", "observe_project"):
                    candidates = [key for key in tools if key.endswith(suffix)]
                    if not candidates:
                        raise AssertionError(f"MCP tool {suffix} unavailable; tools: {list(tools)}")
                    if candidates[0] not in used:
                        name, args = candidates[0], {}
                        if self.pico and suffix == "observe_project": args = {"duration_ms": 2000}
                        break
            self.calls.append(name or "answer")
            if len(self.calls) > 16:
                raise AssertionError("Unexpected model retry loop")
            delta = {"role": "assistant"}
            if name:
                if self.thinking: delta["reasoning_content"] = "Inspect the project and verify its real connections."
                delta["tool_calls"] = [{"index": 0, "id": "call_" + str(len(self.calls)), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
            else:
                delta["content"] = ("<think>The GPIO connection and serial output have been checked.</think>" if self.thinking else "") + "The simulation is running. Serial output contains 42."
            chunks = [{"id": "fixture", "object": "chat.completion.chunk", "created": 1, "model": "probe", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"id": "fixture", "object": "chat.completion.chunk", "created": 1, "model": "probe", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if name else "stop"}], "usage": {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40}}]
            data = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data.encode())))
            self.end_headers()
            self.wfile.write(data.encode())
        except Exception as exc:
            type(self).failure = str(exc)
            self.send_error(500, "Fixture failure")


@unittest.skipUnless(os.environ.get("RUN_OPENCODE_TEST") == "1" and shutil.which("opencode"), "Explicit real OpenCode integration test")
class OpenCodeIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_edit_real_file_call_mcp_run_and_observe(self):
        from app.api.routes import agent
        model = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
        ModelFixture.calls, ModelFixture.failure = [], None
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(tmp)
            tools, manager = create_tools(runtime)
            @asynccontextmanager
            async def lifespan(app):
                async with manager.run():
                    try:
                        yield
                    finally:
                        await runtime.close()
            app = FastAPI(lifespan=lifespan)
            app.include_router(agent.router, prefix="/api/agent")
            app.mount("/api/agent/tools", tools)
            @app.exception_handler(AgentError)
            async def errors(request, exc):
                return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="on", timeout_graceful_shutdown=2))
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            reader = None
            with patch.object(agent, "runtime", runtime):
                try:
                    for _ in range(100):
                        if server.started: break
                        await asyncio.sleep(.05)
                    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=70, trust_env=False) as client:
                        await client.get("/api/agent/settings")
                        settings = {"base_url": f"http://127.0.0.1:{model.server_port}/v1", "model": "probe", "timeout_seconds": 60}
                        self.assertEqual((await client.put("/api/agent/settings", json=settings)).status_code, 200)
                        probe = (await client.post("/api/agent/settings/test", json=settings)).json()
                        self.assertTrue(probe["tool_calling"])
                        value = {"format": "velxio-project", "version": 1, "boards": [{"id": "uno", "boardKind": "arduino-uno", "x": 0, "y": 0, "activeFileGroupId": "sketch"}], "components": [], "wires": [], "fileGroups": {"sketch": [{"name": "sketch.ino", "content": "void setup() {}\nvoid loop() {}"}]}, "activeBoardId": "uno"}
                        created = (await client.post("/api/agent/sessions", json={"document": value})).json()
                        sid = created["id"]
                        connected = asyncio.Event()
                        actions = []
                        async def browser_double():
                            async with client.stream("GET", f"/api/agent/sessions/{sid}/events?browser_id=integration-browser") as response:
                                connected.set()
                                async for line in response.aiter_lines():
                                    if not line.startswith("data:"): continue
                                    event = json.loads(line[5:])
                                    if event["type"] == "browser.command":
                                        command = event["payload"]
                                        actions.append(command["action"])
                                        result = {"ok": True, "state": "running", "serial": "42\n"}
                                        if command["action"] == "run": result["applied_revision"] = command["revision"]
                                        await client.post(f"/api/agent/sessions/{sid}/browser-result", json={"command_id": command["command_id"], "browser_id": "integration-browser", "result": result})
                        reader = asyncio.create_task(browser_double())
                        await asyncio.wait_for(connected.wait(), 5)
                        sent = await client.post(f"/api/agent/sessions/{sid}/messages", json={"message": "Modifie le sketch, lance et observe.", "request_id": "integration"})
                        self.assertEqual(sent.status_code, 200, sent.text)
                        session = runtime.sessions[sid]
                        await asyncio.wait_for(session.task, 65)
                        errors_found = [event for event in session.events if event["type"] == "error"]
                        if errors_found:
                            log = session.workspace.root / "harness/server.log"
                            print(log.read_text()[-5000:] if log.exists() else "No harness log")
                        self.assertFalse(errors_found, errors_found)
                        self.assertIsNone(ModelFixture.failure)
                        self.assertEqual(actions, ["inspect_project", "run", "observe"])
                        self.assertIn("Serial.println(42)", (session.workspace.work / "group-1/sketch.ino").read_text())
                        self.assertEqual(session.messages[-1]["role"], "assistant")
                        self.assertIn("42", session.messages[-1]["content"])
                        print("Real harness:", ModelFixture.calls, "browser commands:", actions)
                finally:
                    if reader:
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
                    await runtime.close()
                    server.should_exit = True
                    await server_task
                    model.shutdown()
                    model.server_close()


if __name__ == "__main__":
    if "--serve-model" in sys.argv:
        ModelFixture.circuit = "--circuit" in sys.argv
        ModelFixture.thinking = "--thinking" in sys.argv
        ModelFixture.swap = "--swap-board" in sys.argv
        ModelFixture.pico = "--pico" in sys.argv
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
        print(f"AGENT_TEST_MODEL_URL=http://127.0.0.1:{server.server_port}/v1", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    else:
        unittest.main()
