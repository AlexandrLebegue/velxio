"""Optional agent API. Model credentials and the harness stay on the server."""
import asyncio
import hashlib
import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.hooks import get_current_user_id
from app.agent.runtime import AgentRuntime, test_connection
from app.agent.settings import AgentError, ConnectionSettings, connection_key
from app.agent.workspace import checked_document, project_revision
from app.agent.tools import create_tools


runtime = AgentRuntime()
tools_app, tools_manager = create_tools(runtime)
router = APIRouter()


async def owner(request: Request, response: Response):
    user = await get_current_user_id(request)
    if user is not None:
        return hashlib.sha256(("user:" + str(user)).encode()).hexdigest()
    local = request.client and request.client.host in ("127.0.0.1", "::1", "testclient") and not request.headers.get("x-forwarded-for")
    if not local and os.environ.get("VELXIO_AGENT_ALLOW_ANONYMOUS", "0") != "1":
        raise AgentError("authentication_required", "Sign in to use the agent. A private single-user installation can enable VELXIO_AGENT_ALLOW_ANONYMOUS=1.", 401)
    token = request.cookies.get("velxio_agent_owner", "")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        token = secrets.token_hex(32)
        response.set_cookie("velxio_agent_owner", token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=86400 * 30, path="/api/agent")
    return hashlib.sha256(("local:" + token).encode()).hexdigest()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectBody(StrictBody):
    document: dict
    expected_revision: str = Field(default="", max_length=64)
    base_revision: str | None = Field(default=None,max_length=64)


class MessageBody(StrictBody):
    message: str = Field(min_length=1, max_length=16000)
    request_id: str = Field(min_length=1, max_length=100)


class BrowserResult(StrictBody):
    command_id: str = Field(min_length=32, max_length=32)
    browser_id: str = Field(min_length=16, max_length=64)
    result: dict


@router.get("/settings")
async def read_settings(principal=Depends(owner)):
    return {**runtime.settings.public(runtime.settings.read(principal)), "available": runtime.available(), "harness": "OpenCode", "protocol": "chat-completions"}


@router.put("/settings")
async def save_settings(body: ConnectionSettings, principal=Depends(owner)):
    return {**runtime.settings.save(principal, body), "available": runtime.available()}


@router.post("/settings/test")
async def check_connection(body: ConnectionSettings, principal=Depends(owner)):
    value = body.model_copy(update={"api_key": connection_key(body, runtime.settings.read(principal))})
    return await test_connection(value)


@router.post("/revision")
async def snapshot_revision(body: ProjectBody, principal=Depends(owner)):
    return {"revision": project_revision(checked_document(body.document))}


@router.post("/sessions")
async def create_session(body: ProjectBody, principal=Depends(owner)):
    return runtime.create(principal, body.document).public()


@router.get("/sessions/{sid}")
async def get_session(sid: str, principal=Depends(owner)):
    return runtime.get(principal, sid).public()


@router.get("/sessions/{sid}/workspace")
async def read_workspace(sid: str, base: bool=False, principal=Depends(owner)):
    session=runtime.get(principal,sid)
    if base:
        document=session.editor_document or session.workspace.document
        return {'document':document,'revision':project_revision(document)}
    return session.workspace.describe()


@router.patch("/sessions/{sid}/workspace")
async def sync_workspace(sid: str, body: ProjectBody, principal=Depends(owner)):
    return runtime.sync(runtime.get(principal, sid), body.document, body.expected_revision,body.base_revision)


@router.post("/sessions/{sid}/messages")
async def send_message(sid: str, body: MessageBody, request: Request, principal=Depends(owner)):
    server_port = (request.scope.get("server") or ("127.0.0.1", 8001))[1]
    callback = os.environ.get("VELXIO_AGENT_CALLBACK_URL", f"http://127.0.0.1:{server_port}/api/agent/tools/mcp")
    session = runtime.get(principal, sid)
    # Preserve the real authenticated owner context for the shared compiler
    # admission lane. A model-supplied ID or MCP callback token cannot replace it.
    session.compile_request = request
    session.compile_user = await get_current_user_id(request)
    return await runtime.start_turn(session, body.message, body.request_id, callback)


@router.post("/sessions/{sid}/stop")
async def stop_session(sid: str, principal=Depends(owner)):
    session = runtime.get(principal, sid)
    await runtime.stop(session)
    return {"ok": True}


@router.post("/sessions/{sid}/browser-result")
async def browser_result(sid: str, body: BrowserResult, principal=Depends(owner)):
    session = runtime.get(principal, sid)
    if body.browser_id != session.browser_id:
        raise AgentError("browser_lease_lost", "This editor no longer owns the simulation connection", 409)
    future = session.pending.get(body.command_id)
    if future is None or future.done():
        raise AgentError("command_expired", "Browser command expired", 409)
    # Internal editor snapshots are up to 2 MiB each; they are distinct from
    # the model-facing 24 KiB tool-response budget.
    if len(json.dumps(body.result).encode()) > 8*1024*1024:
        raise AgentError("quota_exceeded", "Browser result exceeds 8 MiB")
    future.set_result(body.result)
    return {"ok": True}


@router.get("/sessions/{sid}/events")
async def events(sid: str, request: Request, browser_id: str, after: int = 0, principal=Depends(owner)):
    session = runtime.get(principal, sid)
    if not 16 <= len(browser_id) <= 64:
        raise AgentError("invalid_browser", "Invalid browser connection ID")
    if session.browser_id and session.browser_id != browser_id and time.monotonic() - session.browser_seen < 25:
        raise AgentError("browser_in_use", "This conversation is already connected to another editor tab", 409)
    stream_id = secrets.token_hex(16)
    session.browser_id, session.stream_id = browser_id, stream_id
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise AgentError("invalid_cursor", "Invalid event cursor")

    async def stream():
        nonlocal cursor
        session.browser_seen = time.monotonic()
        yield ": connected\n\n"
        if session.events and cursor < session.events[0]["event_id"] - 1:
            yield "event: resync\ndata: {}\n\n"
            cursor = session.sequence
        try:
            while session.stream_id == stream_id and not await request.is_disconnected():
                session.browser_seen = time.monotonic()
                session.changed.clear()
                for event in list(session.events):
                    if event["event_id"] > cursor:
                        cursor = event["event_id"]
                        yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                try:
                    await asyncio.wait_for(session.changed.wait(), 10)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if session.stream_id == stream_id:
                session.browser_seen = 0

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
