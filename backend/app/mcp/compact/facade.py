"""Six-tool FastMCP HTTP facade in the REST process; never imports compatibility MCP."""
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import asyncio
import hashlib
import json
import os
from pathlib import Path

from .catalog import Catalog, bounded
from .contracts import TOOL_SCHEMAS
from .projects import ProjectStore, MISSING, pointer, validate_save_arguments, validation_error
from .checks import LibraryInventory, ProjectChecker
from .builds import BuildService, ToolchainInventory, proof_bytes

DESCRIPTIONS = {
    'search_catalog': 'Search IDs, names, tags, summaries and keywords. If a compound phrase has no matches, merge matching words without duplicate IDs; query_used lists the actual terms. Use next_offset for pagination, never repeat the same page. Five results by default, limit up to 50.',
    'get_reference': 'Reference by catalog ID. section=project gives a saveable native board document or a component instance_template with bare metadataId, defaults and known pinNames. Follow example_references for library APIs; read source with section=code. Boards report execution unsupported: builds do not start simulation.',
    'save_project': 'Save plain Arduino sketch text with sketch and optional board/libraries, without embedding source in a document. Real newlines and quotes are preserved exactly; suspicious single-line text returns warnings. Existing project updates require project_id and expected_version. Native documents and allowlisted changes remain supported.',
    'check_project': 'Check an exact version, including unusable Arduino sketches. Errors are listed first with file, observed, expected and next_action. ok means the tool returned a report, not that the sketch is valid. No electrical or functional certification.',
    'build_project': 'Start an offline build, waiting up to wait_seconds (default 20, max 60) for its final result. Claim build success only for state=done AND success=true; ok only means the tool request succeeded. Otherwise follow next_action. Read first_error before separate capped warnings. No installation or simulation.',
    'read_artifact': 'Read an immutable artifact by opaque ID in bounded byte slices.',
}
_SCOPE = ContextVar('compact_http_scope', default=None)
BASE = Path(__file__).parent


def _normalize_arguments(arguments):
    # Tolerate this removed model-generated field without relaxing other keys.
    if isinstance(arguments, dict):
        return {key: value for key, value in arguments.items() if key != 'cursor'}
    return arguments


def _save_schema_error(exc, arguments):
    # Prefer the native validator's precise expected values and missing fields.
    try:
        validate_save_arguments(arguments)
    except ValueError as native:
        if hasattr(native, 'details'):
            return native
        raise
    parts = list(exc.absolute_path)
    if parts and parts[0] == 'document':
        parts.pop(0)
    path = ''
    for part in parts:
        path = pointer(path, part)
    received = exc.instance
    if exc.validator == 'required':
        missing = sorted(set(exc.validator_value) - received.keys())[0]
        path = pointer(path, missing)
        received = MISSING
        expected = 'required field: ' + missing
    elif exc.validator == 'additionalProperties':
        unknown = sorted(set(received) - set(exc.schema.get('properties', {})))[0]
        path = pointer(path, unknown)
        received = received[unknown]
        expected = 'known field: ' + ', '.join(exc.schema.get('properties', {}))
    else:
        expected = str(exc.validator) + ': ' + json.dumps(exc.validator_value, ensure_ascii=True)
    return validation_error(path, received, expected)


class NamespaceStore(ProjectStore):
    """Principal isolation with ONE global quota lock and global byte accounting."""
    def __init__(self, quota, principal, catalog=None):
        self.quota = quota
        super().__init__(Path(quota.root) / principal, max_storage_bytes=quota.max_storage_bytes, catalog=catalog)

    @contextmanager
    def _locked(self, exclusive):
        with self.quota._locked(exclusive):
            with super()._locked(exclusive) as root:
                yield root

    def _usage(self, directory):
        root = self.quota._root()
        try:
            return self.quota._usage(root)
        finally:
            os.close(root)


class CompactRuntime:
    def __init__(self, app, *, catalog=None, root=None, inventory_file=None, source_root=None):
        self.app = app
        self.catalog = catalog or Catalog.from_snapshot(BASE / 'catalog.snapshot.json')
        self.root = Path(root or os.environ.get('MCP_COMPACT_DATA', '/app/data/mcp-compact'))
        self.source_root = source_root or os.environ.get('MCP_COMPACT_SOURCE_ROOT', str(Path(__file__).resolve().parents[4]))
        self.inventory_file = Path(inventory_file or os.environ.get('MCP_COMPACT_INVENTORY', '/app/data/mcp-compact-inventory/inventory.json'))
        self.services = {}
        self.quota = None
        self.closing = False

    def inventories(self):
        # Missing evidence permits save/check, never builds. No discovery/install.
        if not self.inventory_file.exists():
            return None, None
        raw = proof_bytes(str(self.inventory_file.parent), self.inventory_file.name, 1024 * 1024)
        if len(raw) > 1024 * 1024:
            raise ValueError('Inventory exceeds 1 MiB')
        doc = json.loads(raw)
        return (LibraryInventory(doc['library_root'], doc['libraries'], complete=doc['complete']),
                ToolchainInventory(doc['toolchain_root'], doc['toolchains'], complete=doc['complete']))

    async def call(self, name, arguments):
        arguments = _normalize_arguments(arguments)
        if name == 'run_project':
            return {'ok': False, 'error': {'code': 'unsupported', 'message': 'Simulation is not supported by the six-tool MCP. Use build_project for compilation only; do not poll for startup.'}}
        if name not in TOOL_SCHEMAS or not isinstance(arguments, dict):
            return {'ok': False, 'error': {'code': 'invalid_argument', 'message': 'Unknown tool or invalid arguments'}}
        if self.closing:
            return {'ok': False, 'error': {'code': 'owner_conflict', 'message': 'REST owner is draining'}}
        if name in ('search_catalog', 'get_reference'):
            return getattr(self.catalog, name)(**arguments)
        scope = _SCOPE.get()
        if scope is None:
            return {'ok': False, 'error': {'code': 'owner_integration_required', 'message': 'An active HTTP REST-owner request is required'}}
        from starlette.requests import Request
        from app.core.hooks import get_current_user_id
        from app.api.routes.compile import bind_compact_offline_owner
        request = Request({**scope, 'app': self.app})
        user = await get_current_user_id(request)
        principal = hashlib.sha256(('anonymous' if user is None else 'user:' + str(user)).encode()).hexdigest()
        if principal not in self.services:
            if len(self.services) >= 64:
                return {'ok': False, 'error': {'code': 'quota_exceeded', 'message': '64 active principals maximum; existing files retained'}}
            libs, tools = self.inventories()
            if self.quota is None:
                self.quota = ProjectStore(self.root)
            store = NamespaceStore(self.quota, principal, catalog=self.catalog)
            checker = ProjectChecker(store, self.catalog, source_root=self.source_root, inventory=libs)
            self.services[principal] = BuildService(store, checker, toolchains=tools)
        service = self.services[principal]
        if name == 'build_project':
            service.adapter = await bind_compact_offline_owner(request, user)
            return await service.build_project(**arguments)
        target = service.checker if name == 'check_project' else service.store
        return getattr(target, name)(**arguments)

    async def close(self):
        self.closing = True
        await asyncio.gather(*(service.close() for service in self.services.values()))


class RequestScope:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = _SCOPE.set(scope)
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > 3 * 1024 * 1024:
                raise ValueError('MCP request exceeds 3 MiB')
            return message
        try:
            await self.app(scope, limited_receive, send)
        finally:
            _SCOPE.reset(token)


def create_facade(app, **runtime_options):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import Tool, TextContent
    from jsonschema import validate, ValidationError
    mcp = FastMCP('velxio-compact', host='0.0.0.0', stateless_http=True, json_response=True, streamable_http_path='/mcp')
    runtime = CompactRuntime(app, **runtime_options)

    @mcp._mcp_server.list_tools()
    async def list_tools():
        return [Tool(name=name, description=DESCRIPTIONS[name], inputSchema=schema['inputSchema'])
                for name, schema in TOOL_SCHEMAS.items()]

    # Normalize before schema validation; the SDK would otherwise reject cursor.
    @mcp._mcp_server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            arguments = _normalize_arguments(arguments)
            if name in TOOL_SCHEMAS:
                validate(instance=arguments, schema=TOOL_SCHEMAS[name]['inputSchema'])
            result = bounded(await runtime.call(name, arguments))
        except ValidationError as exc:
            if name == 'save_project':
                error = _save_schema_error(exc, arguments)
                result = {'ok': False, 'error': {'code': error.code, 'message': str(error), **error.details}}
            else:
                result = {'ok': False, 'error': {'code': 'invalid_argument',
                    'message': 'Arguments do not match the tool input schema'}}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result = {'ok': False, 'error': {'code': getattr(exc, 'code', 'preflight_unknown'),
                'message': 'Local prerequisite unavailable or invalid; no installation attempted'}}
        return [TextContent(type='text', text=json.dumps(result, ensure_ascii=False, separators=(',', ':')))]

    transport = RequestScope(mcp.streamable_http_app())
    @asynccontextmanager
    async def lifespan():
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await runtime.close()
    return transport, lifespan, runtime
