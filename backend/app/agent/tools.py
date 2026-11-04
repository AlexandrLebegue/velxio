"""Session-bound MCP tools sharing the FastAPI lifecycle."""
from contextvars import ContextVar
from copy import deepcopy
import json
import secrets

from app.mcp.compact.contracts import TOOL_SCHEMAS, model_input_schema
from app.mcp.compact.arguments import normalize
from app.mcp.compact.errors import normalize_error, preview, pointer
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
        "run_project": ("Run a supported active project through the editor's build/load/execute pipeline. ESP32 execution is unsupported by this bridge and returns immediately: do not poll or retry. Compact MCP build_project provides compilation separately. Other engines: starting/booting are pending; only confirmed=true acknowledges startup.", empty),
        "observe_project": ("Read current simulation state, serial output and compilation diagnostics", {"type": "object", "properties": {"duration_ms": {"type": "integer", "minimum": 0, "maximum": 15000}}, "additionalProperties": False}),
        "stop_project": ("Stop the active project's simulation", empty),
        "update_circuit": ("Advanced set/remove JSON-pointer edits under /components and /wires. Prefer add_component for additions and connect_pins(connections=[...]) for wiring; those fill IDs/defaults and preserve existing items. Each component requires {id, metadataId, x, y, properties}. Arrays require numeric existing indices; /components/name and /components/- are not supported.", {"type": "object", "properties": {"changes": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "object", "properties": {"op": {"enum": ["set", "remove"]}, "path": {"type": "string"}, "value": {}}, "required": ["op", "path"], "additionalProperties": False}}}, "required": ["changes"], "additionalProperties": False}),
        "search_catalog": ("Find IDs of new boards, components or examples. Use a short keyword; query_used identifies a keyword fallback when a longer phrase has no matches. To paginate use next_offset, never repeat the same page. Existing parts and their pins are already in the project context.", TOOL_SCHEMAS["search_catalog"]["inputSchema"]),
        "get_reference": ("Read a NEW component or board once with section=overview (default): real pins, attributes, defaults and available library information together. Other sections are for specific missing details; do not repeat reads of known pins.", TOOL_SCHEMAS["get_reference"]["inputSchema"]),
    }

    # Same six core operations, bound to this conversation instead of making
    # the model shuttle opaque IDs and immutable versions between calls.
    for name in ('save_project', 'check_project', 'build_project', 'read_artifact'):
        schema = deepcopy(model_input_schema(name))
        for key in ('if', 'then', 'else'):
            schema.pop(key, None)
        for key in ('project_id', 'version', 'expected_version'):
            schema['properties'].pop(key, None)
        schema['required'] = [key for key in schema.get('required', [])
                              if key not in ('project_id', 'version', 'expected_version', 'action')]
        schemas[name] = ('', schema)
    schemas['save_project'] = ('Save the current project. Prefer from_example with its advertised parameters for complete code and native wires. Otherwise edit source files in cwd and call with no arguments, or supply plain sketch text. Never stringify objects. No project IDs needed.', schemas['save_project'][1])
    schemas['check_project'] = ('Check the current files and circuit. Fix error-severity findings before build; partial is not runtime proof. No arguments needed.', schemas['check_project'][1])
    schemas['build_project'] = ('Compile the current project. No arguments needed; default action=start waits 20 seconds, max 60 via wait_seconds. Only state=done AND success=true proves compilation. Follow next_action if running. No simulation.', schemas['build_project'][1])
    schemas['read_artifact'] = ('Read a build log or firmware artifact in byte slices. Project source files are already in cwd: read workspace.active_file directly.', schemas['read_artifact'][1])
    hidden = {'create_project', 'update_circuit', 'disconnect_wire'}
    search = deepcopy(schemas['search_catalog'][1])
    search['required'] = ['query']
    search['properties']['query'].pop('default', None)
    schemas['search_catalog'] = ('Search only for a missing capability. Send query=<short keyword> explicitly; starter_examples are already supplied in the project context. Use next_offset for another page.', search)

    @mcp._mcp_server.list_tools()
    async def list_tools():
        order = list(TOOL_SCHEMAS) + [name for name in schemas if name not in TOOL_SCHEMAS and name not in hidden]
        return [Tool(name=name, description=schemas[name][0], inputSchema=schemas[name][1]) for name in order]

    @mcp._mcp_server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        session, dispatched = None, False
        try:
            session = runtime.by_token(authorization.get().removeprefix("Bearer "))
            if name not in schemas:
                raise AgentError("unknown_tool", "Unknown tool")
            arguments = normalize(name, arguments or {})
            validate(arguments, schemas[name][1])
            dispatched = True
            result = normalize_error(await runtime.call_tool(session, name, arguments), name, arguments)
            raw = json.dumps(result, ensure_ascii=False)
            if len(raw.encode()) > 24 * 1024:
                raw = json.dumps({"ok": False, "error": {"code": "quota_exceeded", "message": "Result exceeds 24 KiB; request a narrower catalog section"}})
        except Exception as exc:
            from jsonschema import ValidationError
            details = {}
            if isinstance(exc, ValidationError):
                details = {'path': pointer(exc.absolute_path), 'received': preview(exc.instance),
                           'expected': str(exc.message)[:500]}
                if name == 'search_catalog' and isinstance(arguments, dict) and 'query' not in arguments:
                    details.update(path='/query', received='<missing>', expected='Explicit query string (empty only for intentional browsing)',
                                   next_action='Call search_catalog with query set to the short keyword you intended. Your previous call contained no query. Use an advertised starter directly when it already fits.')
                if isinstance(arguments, dict) and set(arguments) & {'project_id', 'version', 'expected_version'}:
                    details['next_action'] = f'Call {name} again without project_id, version or expected_version. This conversation selects the project automatically.'
            raw = json.dumps(normalize_error({"ok": False, "error": {"code": getattr(exc, "code", "invalid_argument"), "message": str(exc)[:500], **details}}, name, arguments))
            if session is not None and not dispatched:
                runtime.emit(session, 'tool.state', {'call_id':secrets.token_hex(16), 'name':name,
                             'title':name, 'status':'error', 'summary':raw[:3000]})
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
