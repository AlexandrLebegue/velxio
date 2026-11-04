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
    endpoint = {"type": "object", "properties": {"componentId": {"type": "string"}, "pinName": {"type": "string"}}, "required": ["componentId", "pinName"], "additionalProperties": False}
    connection = {"type": "object", "properties": {"from": endpoint, "to": endpoint}, "required": ["from", "to"], "additionalProperties": False}
    schemas = {
        "add_component": ("Add a real catalog component without JSON patches. Supply component (bare metadataId or component: ID), optional instance_id, properties and position. Velxio fills defaults, generates an ID and places it beside the board. Returns the saved component, real pins and recommended examples; use those directly without another reference read.", {"type": "object", "properties": {"component": {"type": "string", "minLength": 1, "maxLength": 240}, "instance_id": {"type": "string", "minLength": 1, "maxLength": 200}, "properties": {"type": "object"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["component"], "additionalProperties": False}),
        "connect_pins": ("Connect real pins. Prefer connections:[{from:{componentId,pinName},to:{componentId,pinName}},...] for ALL planned wires in one call. Existing wires are preserved; the whole batch is validated before anything is applied. No IDs or coordinates needed. A single from/to pair remains supported; do not combine both formats.", {"type": "object", "properties": {"from": endpoint, "to": endpoint, "connections": {"type": "array", "items": connection, "minItems": 1, "maxItems": 128}}, "oneOf": [{"required": ["from", "to"], "not": {"required": ["connections"]}}, {"required": ["connections"], "not": {"anyOf": [{"required": ["from"]}, {"required": ["to"]}]}}], "additionalProperties": False}),
        "disconnect_wire": ("Remove a wire by its ID and apply the validated circuit", {"type": "object", "properties": {"wire_id": {"type": "string"}}, "required": ["wire_id"], "additionalProperties": False}),
        "set_component_properties": ("Merge properties into an existing component and revalidate all connected pins before applying", {"type": "object", "properties": {"component_id": {"type": "string"}, "properties": {"type": "object"}}, "required": ["component_id", "properties"], "additionalProperties": False}),
        "change_board": ("Replace the active board while preserving its ID, sources and circuit. No new conversation needed. Unmapped pins keep their names and are validated before application; use pin_map to remap incompatible pins. This does not port source code between architectures.", {"type": "object", "properties": {"board": {"type": "string", "description": "Exact boardKind, e.g. esp32, arduino-nano, raspberry-pi-pico"}, "board_id": {"type": "string"}, "pin_map": {"type": "object", "additionalProperties": {"type": "string"}}, "language_mode": {"enum": ["arduino", "micropython", "espidf"]}}, "required": ["board"], "additionalProperties": False}),
        "create_project": ("Create a starter for any catalog board in an empty workspace; for an existing board use change_board instead. Execution capabilities are reported separately by get_project.", {"type": "object", "properties": {"board": {"type": "string", "description": "Exact catalog boardKind; defaults to arduino-uno"}}, "additionalProperties": False}),
        "get_project": ("Read current project, source paths, real mounted pinouts and explicit capabilities together. Initial project context is already supplied: call only if you need updated state.", empty),
        "run_project": ("Run the active project through the editor's existing build, firmware-loading and execution pipeline for any installed board engine/language. Read state and confirmed: starting/booting are pending, running/completed with confirmed=true are acknowledged. Poll observe_project while booting; do not rebuild.", empty),
        "observe_project": ("Read current simulation state, serial output and compilation diagnostics", {"type": "object", "properties": {"duration_ms": {"type": "integer", "minimum": 0, "maximum": 15000}}, "additionalProperties": False}),
        "stop_project": ("Stop the active project's simulation", empty),
        "update_circuit": ("Advanced set/remove JSON-pointer edits under /components and /wires. Prefer add_component for additions and connect_pins(connections=[...]) for wiring; those fill IDs/defaults and preserve existing items. Each component requires {id, metadataId, x, y, properties}. Arrays require numeric existing indices; /components/name and /components/- are not supported.", {"type": "object", "properties": {"changes": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "object", "properties": {"op": {"enum": ["set", "remove"]}, "path": {"type": "string"}, "value": {}}, "required": ["op", "path"], "additionalProperties": False}}}, "required": ["changes"], "additionalProperties": False}),
        "search_catalog": ("Find IDs of new boards, components or examples. Use a short keyword; query_used identifies a keyword fallback when a longer phrase has no matches. To paginate use next_offset, never repeat the same page. Existing parts and their pins are already in the project context.", TOOL_SCHEMAS["search_catalog"]["inputSchema"]),
        "get_reference": ("Read a NEW component or board once with section=overview (default): real pins, attributes, defaults and available library information together. Other sections are for specific missing details; do not repeat reads of known pins.", TOOL_SCHEMAS["get_reference"]["inputSchema"]),
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
