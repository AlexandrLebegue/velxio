"""Session-bound MCP tools sharing the FastAPI lifecycle."""
from contextvars import ContextVar
import json

from app.mcp.compact.contracts import TOOL_SCHEMAS
from .settings import AgentError


def create_tools(runtime):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import Tool, TextContent
    from jsonschema import validate

    authorization = ContextVar("velxio_agent_authorization", default="")
    mcp = FastMCP("velxio-project", stateless_http=True, json_response=True, streamable_http_path="/mcp")
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    schemas = {
        "create_project": ("Create a valid AVR starter when the current workspace is empty; automatically attach its source folder and project ID", {"type": "object", "properties": {"board": {"enum": ["arduino-uno", "arduino-nano", "arduino-mega", "attiny85"]}}, "additionalProperties": False}),
        "get_project": ("Inspect the active project, board, circuit and source group paths", empty),
        "run_project": ("Compile and really start the active project in the connected editor. Read the returned status; compilation alone is not success.", empty),
        "observe_project": ("Read current simulation state, serial output and compilation diagnostics", {"type": "object", "properties": {"duration_ms": {"type": "integer", "minimum": 0, "maximum": 5000}}, "additionalProperties": False}),
        "stop_project": ("Stop the active project's simulation", empty),
        "update_circuit": ("Apply validated set/remove JSON-pointer changes under /components and /wires; set an entire array to add an instance", {"type": "object", "properties": {"changes": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "object", "properties": {"op": {"enum": ["set", "remove"]}, "path": {"type": "string"}, "value": {}}, "required": ["op", "path"], "additionalProperties": False}}}, "required": ["changes"], "additionalProperties": False}),
        **{name: ("Consult Velxio's real component, board and example catalog", TOOL_SCHEMAS[name]["inputSchema"]) for name in ("search_catalog", "get_reference")},
    }

    @mcp._mcp_server.list_tools()
    async def list_tools():
        return [Tool(name=name, description=description, inputSchema=schema) for name, (description, schema) in schemas.items()]

    @mcp._mcp_server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            session = runtime.by_token(authorization.get().removeprefix("Bearer "))
            if name not in schemas:
                raise AgentError("unknown_tool", "Unknown tool")
            validate(arguments or {}, schemas[name][1])
            result = await runtime.call_tool(session, name, arguments or {})
            raw = json.dumps(result, ensure_ascii=False)
            if len(raw.encode()) > 24 * 1024:
                raw = json.dumps({"ok": False, "error": {"code": "quota_exceeded", "message": "Result exceeds 24 KiB; request a narrower catalog section"}})
        except Exception as exc:
            raw = json.dumps({"ok": False, "error": {"code": getattr(exc, "code", "invalid_argument"), "message": str(exc)[:1000]}})
        return [TextContent(type="text", text=raw)]

    child = mcp.streamable_http_app()

    async def scoped(scope, receive, send):
        headers = dict(scope.get("headers", []))
        token = authorization.set(headers.get(b"authorization", b"").decode())
        try:
            # Discovery also requires a live session token; no public tools endpoint.
            runtime.by_token(authorization.get().removeprefix("Bearer "))
            if scope.get("method") == "GET":
                from starlette.responses import Response
                await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
                return
            await child(scope, receive, send)
        except AgentError:
            from starlette.responses import JSONResponse
            await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)
        finally:
            authorization.reset(token)

    return scoped, mcp.session_manager
