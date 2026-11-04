"""Live local-model build evaluation, without Chromium or a fake LLM.

AGENT_MODEL_CONFIG=/private/connection.json PYTHONPATH=backend python scripts/test-agent-backend-local.py
Requires the backend dependencies, OpenCode, frontend node_modules (jsdom only),
arduino-cli and installed AVR/ESP32 cores + Servo/GxEPD2/Adafruit GFX libraries.
Use ARDUINO_DIRECTORIES_{DATA,DOWNLOADS,USER} to isolate the toolchain.
The editor transport is replaced ONLY here: run compiles but never simulates.
"""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("VELXIO_CACHE_BYPASS_TOKEN", "validation-fresh-build")
os.environ.setdefault("VELXIO_ARTIFACT_CACHE", str(Path(os.environ.get("AGENT_TEST_ARTIFACTS", "/tmp/velxio-agent-backend-tests")).resolve() / "private/compiler-cache"))

import httpx
from fastapi import FastAPI
import uvicorn
from app.agent.opencode import OpenCodeAdapter
from app.agent.runtime import AgentRuntime, test_connection
from app.agent.settings import AgentError, ConnectionSettings
from app.agent.tools import create_tools
from app.agent.workspace import checked_document, project_revision
from app.api.routes import compile as compile_routes

CASES = [
    ("blink", "arduino-uno", "Crée un projet Arduino Uno avec une LED externe et sa résistance. Fais-la clignoter 500 ms allumée puis 500 ms éteinte en boucle, avec LED_ON et LED_OFF sur le port série."),
    ("servo-nano", "arduino-nano", "Crée un projet Arduino Nano avec un servomoteur correctement alimenté et câblé. Avec la bibliothèque Servo standard, positionne-le à 45 degrés et laisse-le à cet angle. Écris SERVO_ANGLE=45 sur le port série une fois par seconde."),
    ("eink-esp32", "esp32", "Crée un projet ESP32 avec le panneau e-ink 1,54 pouce noir et blanc 200×200 disponible dans Velxio. Utilise GxEPD2 et Adafruit GFX. Affiche Hello Velxio avec un cadre noir sur fond blanc. Câble SPI, CS, DC, RST, BUSY et l'alimentation. Après la mise à jour, écris EINK_REFRESH_DONE sur le port série."),
]
TEST_CONTEXT = (
    "\nBACKEND BUILD EVALUATION: There is no editor or simulation engine in this test. "
    "The editor transport is replaced by an isolated project store and real pin validation. "
    "run_project performs a REAL compile through the production backend compiler; state=compiled "
    "with confirmed=false is a successful BUILD, not a simulation startup. Observe once for diagnostics. "
    "Never retry a successful compiled state to obtain running. No serial, display or servo runtime "
    "observations are available. Do not claim them. Dependencies are already installed: Servo, "
    "GxEPD2, Adafruit GFX Library, Adafruit BusIO. Prepare and compile the project; report build only."
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class BuildAdapter(OpenCodeAdapter):
    async def prompt(self, text, system):
        await super().prompt(text, system + TEST_CONTEXT)


class BackendRuntime(AgentRuntime):
    def __init__(self, root, pins, output):
        super().__init__(root, adapter_factory=BuildAdapter)
        self.pins, self.output = pins, output
        self.documents, self.builds = {}, {}
        self.tool_calls = {}
        self.origin = ""

    async def call_tool(self, session, name, args):
        self.tool_calls.setdefault(session.id, []).append({"name": name, "arguments": args})
        return await super().call_tool(session, name, args)

    def describe(self, kind, key):
        ref = self.get_catalog().get_reference(id=kind + ":" + key)
        if not ref.get("ok"):
            return ref
        data = ref["data"]
        if key not in self.pins:
            return {"ok": False, "error": {"code": "test_pin_inventory_missing", "message": "Backend test has no verified pin inventory for " + key}}
        attrs = data.get("attrs", [])
        return {"ok": True, "pins": self.pins[key]["pins"], "attrs": attrs,
                "defaults": {attr["name"]: attr["defaultValue"] for attr in attrs if "defaultValue" in attr},
                "pin_source": "backend test inventory; no mounted editor"}

    def validate(self, document):
        document = checked_document(document)
        parts = {item["id"]: item.get("boardKind", item.get("metadataId")) for item in document["boards"] + document["components"]}
        for wire in document["wires"]:
            for side in ("start", "end"):
                endpoint = wire[side]
                kind = parts[endpoint["componentId"]]
                inventory = self.pins.get(kind)
                if not inventory:
                    raise AgentError("test_pin_inventory_missing", "No verified pins for " + kind)
                canonical = inventory["aliases"].get(endpoint["pinName"])
                if not canonical:
                    error = AgentError("pin_unknown", f"{kind}: invalid pin {endpoint['pinName']}; valid pins: " + ", ".join(p["name"] for p in inventory["pins"]))
                    error.details = {"wire_id": wire["id"], "endpoint": side, "instance_id": endpoint["componentId"], "pin": endpoint["pinName"]}
                    raise error
                endpoint["pinName"] = canonical
        return document

    async def compile(self, session, document, independent=False):
        board = next(b for b in document["boards"] if b["id"] == document["activeBoardId"])
        fqbn = self.board_definition(board["boardKind"], session)["fqbn"]
        request = {"files": document["fileGroups"][board["activeFileGroupId"]], "board_fqbn": fqbn,
                   "board_kind": board["boardKind"], "language": board.get("languageMode", "arduino"), "initiated_by": "agent"}
        build = {"request": request, "source_sha256": digest(request["files"]), "independent": independent}
        self.builds.setdefault(session.id, []).append(build)
        index = len(self.builds[session.id])
        print(f"{session.owner}: real compile {index} ({fqbn}, independent={independent})", flush=True)
        async with httpx.AsyncClient(base_url=self.origin, trust_env=False, timeout=60) as client:
            response = await client.post("/api/compile/start", json=request, headers={"x-velxio-cache-bypass": os.environ["VELXIO_CACHE_BYPASS_TOKEN"]})
            response.raise_for_status()
            job = response.json()["job_id"]
            for _ in range(600):
                response = await client.get("/api/compile/status/" + job)
                response.raise_for_status()
                status = response.json()
                if status["state"] in ("done", "error"):
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError("Compilation did not finish in 600 seconds")
        result = status.get("result") or {"success": False, "error": status.get("error", "Unknown compile failure")}
        directory = self.output / session.owner
        directory.mkdir(exist_ok=True)
        firmware = result.get("hex_content") or result.get("binary_content")
        if firmware:
            (directory / f"build-{index}.firmware.txt").write_text(firmware)
        build.update(result={k: v for k, v in result.items() if k not in ("hex_content", "binary_content", "uf2_content")},
                     firmware_sha256=hashlib.sha256(firmware.encode()).hexdigest() if firmware else None,
                     job_id=job)
        success = result.get("success", False)
        print(f"{session.owner}: compile {index} {'PASS' if success else 'FAIL'}", flush=True)
        return {"ok": success, "state": "compiled" if success else "error", "compiled": success,
                "confirmed": False, "simulation_available": False,
                "logs": (result.get("stdout", "") + "\n" + result.get("stderr", ""))[-5000:],
                **({"error": {"code": result.get("error_kind") or "compile_failed", "message": result.get("error") or result.get("stderr", "")[-3000:]}} if not success else {})}

    async def browser_command(self, session, action, **data):
        # This is intentionally a test adapter, never a production simulation result.
        session.browser_seen = time.monotonic()
        if action == "inspect_project":
            document = self.documents.get(session.id, session.workspace.document)
            pinouts = {part["id"]: self.describe("board" if "boardKind" in part else "component", part.get("boardKind", part.get("metadataId"))) for part in document["boards"] + document["components"]}
            return {"ok": True, "pinouts": pinouts, "available_boards": []}
        if action == "describe_part":
            return self.describe(data["kind"], data["part_id"])
        if action in ("validate_circuit", "create", "apply", "run"):
            document = self.validate(data["document"])
            revision = project_revision(document)
            if action == "validate_circuit":
                return {"ok": True, "document": document, "revision": revision}
            self.documents[session.id] = document
            session.browser_revision = revision
            if action == "run":
                return {**await self.compile(session, document), "applied_revision": revision}
            return {"ok": True, "applied_revision": revision}
        if action == "observe":
            builds = self.builds.get(session.id, [])
            result = builds[-1]["result"] if builds else {}
            return {"ok": True, "state": "compiled" if result.get("success") else "idle", "confirmed": False,
                    "simulation_available": False, "serial": "", "logs": result.get("stderr", "")[-4000:]}
        if action == "stop":
            return {"ok": True, "state": "stopped", "confirmed": False, "simulation_available": False}
        raise ValueError("Unexpected test action " + action)


async def main():
    output = Path(os.environ.get("AGENT_TEST_ARTIFACTS", "/tmp/velxio-agent-backend-tests")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = ConnectionSettings.model_validate_json(Path(os.environ["AGENT_MODEL_CONFIG"]).read_text())
    config = config.model_copy(update={"max_steps": 40, "timeout_seconds": int(os.environ.get("AGENT_TEST_TIMEOUT", 900))})
    subprocess.run(["node", "scripts/agent-test-pins.mjs", str(output / "pins.json")], cwd=ROOT, check=True)
    pins = json.loads((output / "pins.json").read_text())
    runtime = BackendRuntime(output / "private", pins, output)
    tools, manager = create_tools(runtime)
    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield
    app = FastAPI(lifespan=lifespan)
    app.include_router(compile_routes.router, prefix="/api/compile")
    app.mount("/api/agent/tools", tools)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    runtime.origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    reports = []
    try:
        while not server.started:
            if server_task.done():
                await server_task
            await asyncio.sleep(.05)
        print("Live model preflight:", await test_connection(config), flush=True)
        selected = os.environ.get("AGENT_TEST_CASES", "").split(",")
        for case, board_kind, prompt in CASES:
            if selected != [""] and case not in selected:
                continue
            directory = output / case
            directory.mkdir(exist_ok=True)
            runtime.settings.save(case, config)
            document = {"format": "velxio-project", "version": 1, "boards": [], "components": [], "wires": [], "fileGroups": {}, "activeBoardId": None}
            session = runtime.create(case, document)
            session.browser_seen = time.monotonic()
            report = {"case": case, "model": config.model, "mode": "backend-build-only", "prompt": prompt, "simulation_verified": False}
            print(case + ": starting actual model", flush=True)
            async def heartbeat():
                previous = 0
                while True:
                    session.browser_seen = time.monotonic()
                    for event in session.events:
                        if event["event_id"] > previous and event["type"] in ("tool.state", "error"):
                            payload = event["payload"]
                            if payload.get("status") != "running":
                                print(case + ": " + json.dumps(payload, ensure_ascii=False)[:600], flush=True)
                        previous = max(previous, event["event_id"])
                    await asyncio.sleep(2)
            pulse = asyncio.create_task(heartbeat())
            try:
                await runtime.start_turn(session, prompt + " Compile puis vérifie les diagnostics avec les outils. Test backend seulement, aucune simulation demandée.", case, runtime.origin + "/api/agent/tools/mcp")
                await session.task
                final = session.workspace.capture()
                (directory / "project.vlx").write_text(json.dumps(final, ensure_ascii=False, indent=2))
                for group, files in final["fileGroups"].items():
                    for file in files:
                        target = directory / "sources" / session.workspace.groups[group] / file["name"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(file["content"])
                validated = runtime.validate(final)
                report["pins_valid"] = True
                report["target_board"] = any(b["boardKind"] == board_kind for b in final["boards"])
                report["independent_build"] = await runtime.compile(session, validated, independent=True)
            except Exception as exc:
                report["error"] = str(exc)
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
                report["messages"], report["turns"] = session.messages, session.turns
                steps = [step for turn in session.turns for step in turn["steps"]]
                report["tool_counts"] = dict(Counter(step["name"] for step in steps))
                report["builds"] = runtime.builds.get(session.id, [])
                report["mcp_calls"] = runtime.tool_calls.get(session.id, [])
                independent = next((b for b in reversed(report["builds"]) if b["independent"]), None)
                agent_builds = [b for b in report["builds"] if not b["independent"]]
                report["agent_build_matches_final_sources"] = bool(independent and any(
                    b["result"].get("success") and b["source_sha256"] == independent["source_sha256"]
                    and b["request"]["board_fqbn"] == independent["request"]["board_fqbn"] for b in agent_builds))
                report["agent_completed"] = bool(session.turns and session.turns[-1]["status"] == "completed")
                text = json.dumps(report, ensure_ascii=False, indent=2)
                if config.api_key:
                    text = text.replace(config.api_key, "[REDACTED]")
                (directory / "report.json").write_text(text)
                reports.append({"case": case, "target_board": report.get("target_board"), "pins_valid": report.get("pins_valid"), "build_success": report.get("independent_build", {}).get("ok", False), "agent_build_matches_final_sources": report["agent_build_matches_final_sources"], "agent_completed": report["agent_completed"], "tool_counts": report["tool_counts"], "error": report.get("error"), "simulation_verified": False})
                (output / "summary.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
                if session.adapter:
                    await session.adapter.close()
                    session.adapter = None
                print(case + ": saved report", flush=True)
    finally:
        await runtime.close()
        server.should_exit = True
        await server_task
    return 0 if reports and all(
        all(report.get(key) for key in ("target_board", "pins_valid", "build_success", "agent_build_matches_final_sources", "agent_completed"))
        and not report.get("error") for report in reports) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
