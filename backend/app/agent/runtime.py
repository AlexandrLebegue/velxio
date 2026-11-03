from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any

import httpx

from app.mcp.compact.catalog import Catalog
from .opencode import OpenCodeAdapter
from .settings import AgentError, ConnectionSettings, SettingsStore, private_json
from .workspace import Workspace


@dataclass
class Session:
    id: str
    owner: str
    workspace: Workspace
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    sequence: int = 0
    task: Any = None
    adapter: Any = None
    connection_hash: str = ""
    active_turn: str = ""
    browser_revision: str = ""
    browser_seen: float = 0
    browser_id: str = ""
    stream_id: str = ""
    pending: dict = field(default_factory=dict)
    requests: dict = field(default_factory=dict)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def public(self):
        return {"id": self.id, "revision": self.workspace.revision, "messages": self.messages, "busy": self.busy, "sequence": self.sequence}


class AgentRuntime:
    def __init__(self, root=None, adapter_factory=OpenCodeAdapter):
        self.root = Path(root or os.environ.get("VELXIO_AGENT_DATA", str(Path.home() / ".local/share/velxio/agent")))
        self.settings = SettingsStore(self.root)
        self.sessions: dict[str, Session] = {}
        self.adapter_factory = adapter_factory
        self.catalog = None
        self.closing = False

    def available(self):
        return os.environ.get("VELXIO_AGENT_ENABLED", "1") != "0" and bool(OpenCodeAdapter.executable())

    def save(self, session):
        private_json(session.workspace.root / "session.json", {
            "id": session.id, "messages": session.messages[-100:], "sequence": session.sequence,
            "events": session.events[-150:], "browser_revision": session.browser_revision,
            "document": session.workspace.document,
            "requests": session.requests, "active_turn": session.active_turn,
        })

    def emit(self, session, kind, payload):
        session.sequence += 1
        event = {"event_id": session.sequence, "type": kind, "payload": payload}
        session.events.append(event)
        session.events = session.events[-500:]
        session.changed.set()
        return event

    def create(self, owner, document):
        if self.closing or sum(s.owner == owner for s in self.sessions.values()) >= 16:
            raise AgentError("quota_exceeded", "Maximum 16 active agent sessions per user", 409)
        sid = secrets.token_hex(16)
        workspace = Workspace(self.root / owner / "sessions" / sid, document)
        session = Session(sid, owner, workspace, browser_revision=workspace.revision)
        self.sessions[sid] = session
        self.save(session)
        return session

    def get(self, owner, sid):
        if len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
            raise AgentError("not_found", "Conversation not found", 404)
        session = self.sessions.get(sid)
        if session is None:
            path = self.root / owner / "sessions" / sid / "session.json"
            if not path.exists():
                raise AgentError("not_found", "Conversation not found", 404)
            data = json.loads(path.read_text())
            workspace = Workspace(path.parent, data["document"])
            session = Session(sid, owner, workspace, messages=data["messages"], sequence=data["sequence"], events=data.get("events", []), browser_revision=data.get("browser_revision", workspace.revision))
            session.requests = data.get("requests", {})
            self.sessions[sid] = session
            if data.get("active_turn"):
                self.emit(session, "turn.interrupted", {"turn_id": data["active_turn"], "reason": "server_restart"})
                self.save(session)
        if session.owner != owner:
            raise AgentError("not_found", "Conversation not found", 404)
        return session

    def by_token(self, token):
        for session in self.sessions.values():
            if secrets.compare_digest(session.token, token):
                if not session.busy:
                    break
                return session
        raise AgentError("unauthorized", "Inactive agent tool session", 401)

    def sync(self, session, document, expected_revision):
        if session.busy:
            raise AgentError("turn_running", "Stop the agent before synchronizing manual edits", 409)
        session.workspace.sync(document, expected_revision)
        session.browser_revision = session.workspace.revision
        self.save(session)
        return session.public()

    async def start_turn(self, session, message, request_id, callback_url):
        if request_id in session.requests:
            return {"turn_id": session.requests[request_id]}
        if session.busy:
            raise AgentError("turn_running", "An agent turn is already running", 409)
        if self.closing or not self.available():
            raise AgentError("harness_unavailable", "Install OpenCode 1.19.3 on the Velxio server to use the agent", 503)
        settings = self.settings.read(session.owner)
        if not settings.model:
            raise AgentError("model_required", "Configure and test a model in AI settings first")
        turn_id = secrets.token_hex(16)
        session.active_turn = turn_id
        session.requests[request_id] = turn_id
        if len(session.requests) > 100:
            session.requests.pop(next(iter(session.requests)))
        session.messages.append({"role": "user", "content": message})
        self.emit(session, "turn.started", {"turn_id": turn_id})
        self.save(session)
        session.task = asyncio.create_task(self._turn(session, settings, message, callback_url, turn_id))
        return {"turn_id": turn_id}

    async def _turn(self, session, settings, message, callback_url, turn_id):
        collector = None
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                signature = hashlib.sha256(settings.model_dump_json().encode()).hexdigest()
                if session.adapter and session.connection_hash != signature:
                    await session.adapter.close()
                    session.adapter = None
                if session.adapter is None:
                    session.adapter = self.adapter_factory(session.workspace.root / "harness", session.workspace.work, settings, callback_url, session.token)
                    await session.adapter.start()
                    await session.adapter.create_session()
                    session.connection_hash = signature
                ready, done = asyncio.Event(), asyncio.get_running_loop().create_future()
                collector = asyncio.create_task(self._collect(session, ready, done))
                await asyncio.wait_for(ready.wait(), 15)
                system = (
                    "You are the Velxio electronics coding agent. Work only on the active project. "
                    "Use your existing file tools to edit source files in the group directories. "
                    "Use velxio MCP tools to inspect the circuit, search real component pins, change wiring, run and observe. "
                    "Never use shell commands, install dependencies or invent a successful simulation. "
                    "After editing code, call run_project, then observe_project to inspect serial output. "
                    "Report compilation, simulation startup and functional observations separately. "
                    "A revision conflict means preserve the user's manual edits and explain it. "
                    "Reply in the user's language. Group mapping: " + json.dumps(session.workspace.groups) +
                    ". Previous conversation (context after a reconnect): " + json.dumps(session.messages[-8:-1], ensure_ascii=False)
                )
                await session.adapter.prompt(message, system)
                await done
                messages = await session.adapter.messages()
                text_parts = [part.get("text", "") for item in messages if item.get("info", {}).get("role") == "assistant" for part in item.get("parts", []) if part.get("type") == "text"]
                # Only assistant text from this turn; upstream messages are chronological.
                latest = []
                for item in reversed(messages):
                    if item.get("info", {}).get("role") == "user":
                        break
                    latest[0:0] = [p.get("text", "") for p in item.get("parts", []) if p.get("type") == "text"]
                answer = "\n\n".join(latest) or (text_parts[-1] if text_parts else "")
                if answer:
                    session.messages.append({"role": "assistant", "content": answer[:64000]})
                    self.emit(session, "message.completed", {"text": answer[:64000]})
                old_revision = session.workspace.revision
                session.workspace.commit()
                if old_revision != session.workspace.revision:
                    self.emit(session, "workspace.changed", {"revision": session.workspace.revision})
                self.emit(session, "turn.completed", {"turn_id": turn_id})
        except asyncio.CancelledError:
            if session.adapter:
                await session.adapter.abort()
            self.emit(session, "turn.interrupted", {"turn_id": turn_id})
        except Exception as exc:
            if session.adapter:
                await session.adapter.abort()
                await session.adapter.close()
                session.adapter = None
            code = getattr(exc, "code", "agent_error")
            message = str(exc) if isinstance(exc, AgentError) else "The agent connection failed or timed out. Check the model connection and retry."
            self.emit(session, "error", {"code": code, "message": message})
        finally:
            if collector:
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
            for future in session.pending.values():
                if not future.done():
                    future.cancel()
            session.pending.clear()
            try:
                previous = session.workspace.revision
                session.workspace.commit()
                if session.workspace.revision != previous:
                    self.emit(session, "workspace.changed", {"revision": session.workspace.revision})
            except (ValueError, OSError, UnicodeError):
                pass  # Retain the last valid snapshot and the staging files.
            session.active_turn = ""
            self.save(session)

    async def _collect(self, session, ready, done):
        try:
            async for event in session.adapter.events(ready):
                kind, props = event.get("type"), event.get("properties", {})
                if props.get("sessionID") not in (None, session.adapter.session_id):
                    continue
                if kind == "message.part.delta" and props.get("field") == "text":
                    self.emit(session, "message.delta", {"text": props.get("delta", "")[:12000]})
                elif kind == "message.part.updated":
                    part = props.get("part", {})
                    if part.get("sessionID") == session.adapter.session_id and part.get("type") == "tool":
                        state = part.get("state", {})
                        self.emit(session, "tool.state", {"name": part.get("tool"), "status": state.get("status"), "title": state.get("title", part.get("tool"))})
                elif kind == "session.error":
                    if not done.done():
                        done.set_exception(AgentError("model_error", "The model rejected the request or could not call its tools. Test the connection in AI settings."))
                elif kind == "session.idle" or (kind == "session.status" and props.get("status", {}).get("type") == "idle"):
                    if props.get("sessionID") == session.adapter.session_id and not done.done():
                        done.set_result(None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not done.done():
                done.set_exception(exc)

    async def browser_command(self, session, action, **data):
        if time.monotonic() - session.browser_seen > 25:
            raise AgentError("browser_unavailable", "Keep this project's editor and Agent panel connected to run or observe the simulation", 409)
        command_id = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        session.pending[command_id] = future
        self.emit(session, "browser.command", {"command_id": command_id, "action": action, "expected_revision": session.browser_revision, **data})
        try:
            result = await asyncio.wait_for(future, 180 if action == "run" else 20)
            if result.get("applied_revision") == session.workspace.revision:
                session.browser_revision = result["applied_revision"]
            return result
        except asyncio.TimeoutError as exc:
            raise AgentError("browser_timeout", "The editor did not confirm the action; compilation may still be running", 504) from exc
        finally:
            session.pending.pop(command_id, None)

    async def call_tool(self, session, name, args):
        try:
            if name in ("search_catalog", "get_reference"):
                if self.catalog is None:
                    self.catalog = Catalog.from_snapshot(Path(__file__).parents[1] / "mcp/compact/catalog.snapshot.json")
                return getattr(self.catalog, name)(**args)
            if name == "get_project":
                value = session.workspace.document
                return {"ok": True, "revision": session.workspace.revision, "groups": session.workspace.groups,
                        "boards": value["boards"], "components": value["components"], "wires": value["wires"],
                        "files": {g: [f["name"] for f in files] for g, files in value["fileGroups"].items()}}
            if name == "create_project":
                if session.workspace.document["boards"] or session.workspace.document["components"]:
                    raise AgentError("project_not_empty", "The current project already has a circuit. Edit it, or open a blank workspace before creating a starter.")
                board = args.get("board", "arduino-uno")
                if board not in ("arduino-uno", "arduino-nano", "arduino-mega", "attiny85"):
                    raise AgentError("unsupported_board", "Choose an AVR board for the first agent starter")
                value = {"format": "velxio-project", "version": 1,
                         "boards": [{"id": "board", "boardKind": board, "x": 100, "y": 100, "activeFileGroupId": "group-board", "languageMode": "arduino", "serialBaudRate": 0}],
                         "fileGroups": {"group-board": [{"name": "sketch.ino", "content": "void setup() {\n  pinMode(LED_BUILTIN, OUTPUT);\n}\n\nvoid loop() {\n  digitalWrite(LED_BUILTIN, HIGH);\n  delay(500);\n  digitalWrite(LED_BUILTIN, LOW);\n  delay(500);\n}\n"}]},
                         "components": [], "wires": [], "activeBoardId": "board"}
                session.workspace.sync(value, session.workspace.revision)
                result = await self.browser_command(session, "create", document=value, revision=session.workspace.revision)
                return {**result, "groups": session.workspace.groups}
            if name == "update_circuit":
                session.workspace.update_circuit(args["changes"])
                self.emit(session, "workspace.changed", {"revision": session.workspace.revision})
                return {"ok": True, "revision": session.workspace.revision}
            if name == "run_project":
                session.workspace.commit()
                self.emit(session, "workspace.changed", {"revision": session.workspace.revision})
                return await self.browser_command(session, "run", document=session.workspace.document, revision=session.workspace.revision)
            if name == "observe_project":
                return await self.browser_command(session, "observe", duration_ms=min(max(args.get("duration_ms", 500), 0), 5000))
            if name == "stop_project":
                return await self.browser_command(session, "stop")
            raise AgentError("unknown_tool", "Unknown Velxio tool")
        except (AgentError, ValueError, KeyError) as exc:
            return {"ok": False, "error": {"code": getattr(exc, "code", "invalid_argument"), "message": str(exc)[:1000]}}

    async def stop(self, session):
        if session.busy:
            session.task.cancel()
            await asyncio.gather(session.task, return_exceptions=True)

    async def close(self):
        self.closing = True
        for session in self.sessions.values():
            await self.stop(session)
            if session.adapter:
                await session.adapter.close()


async def test_connection(settings: ConnectionSettings):
    if not settings.model:
        raise AgentError("model_required", "Enter a model ID")
    payload = {"model": settings.model, "messages": [{"role": "user", "content": "Call velxio_connection_probe with ok=true. Do not modify anything."}],
               "tools": [{"type": "function", "function": {"name": "velxio_connection_probe", "description": "Harmless connectivity check", "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}}}],
               "tool_choice": "auto", "stream": True, "max_tokens": 256}
    saw_event, saw_tool = False, False
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream("POST", settings.base_url + "/chat/completions", headers={"Authorization": "Bearer " + (settings.api_key or "local")}, json=payload) as response:
                if response.status_code != 200:
                    raise AgentError("connection_rejected", f"The model endpoint returned HTTP {response.status_code}; check URL, model and credentials")
                size = 0
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 128 * 1024:
                        raise AgentError("invalid_response", "The connection test response was too large")
                    if line.startswith("data:") and line[5:].strip() != "[DONE]":
                        event = json.loads(line[5:])
                        saw_event = True
                        for choice in event.get("choices", []):
                            for call in choice.get("delta", {}).get("tool_calls", []):
                                if call.get("function", {}).get("name") == "velxio_connection_probe":
                                    saw_tool = True
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, AgentError):
            raise
        raise AgentError("connection_failed", "Cannot reach a compatible streaming model from the Velxio server") from exc
    return {"ok": saw_event and saw_tool, "streaming": saw_event, "tool_calling": saw_tool,
            "message": "Connection and tool calling verified" if saw_tool else "Endpoint responded, but the model did not call the diagnostic tool"}
