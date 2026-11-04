"""Six independent contracts; production build owner integration is not wired."""

from copy import deepcopy

MAX_RESPONSE_BYTES = 24 * 1024
MAX_SEARCH_OFFSET = 1_000_000
MAX_PROJECT_BYTES = 2 * 1024 * 1024


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def string(maximum=200):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def enum(*values):
    return {"type": "string", "enum": list(values)}


identifier = string()
version = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
file = obj({"name": string(240), "content": {"type": "string", "maxLength": 262144}}, ["name", "content"])


def native_obj(properties, required, description):
    # Preserve UI extensions while documenting the fields needed to author a snapshot.
    return {**obj(properties, required), "additionalProperties": True, "description": description}


coordinate = {"type": "number", "description": "Finite canvas coordinate, e.g. 0."}
board = native_obj({
    "id": {**identifier, "description": "Unique instance ID used by wires and activeBoardId, e.g. esp."},
    "boardKind": {**identifier, "description": "Native board key, e.g. esp32 (not board:esp32). Obtain it with get_reference(section=project)."},
    "x": coordinate, "y": coordinate,
    "activeFileGroupId": {**identifier, "description": "Key present in document.fileGroups, e.g. sketch."},
    "languageMode": {**enum("arduino", "micropython", "espidf"), "default": "arduino",
                     "description": "Source language; Arduino uses sketch.ino, ESP-IDF main.c."},
    "rotation": {"type": "number", "description": "Clockwise degrees, e.g. 0 or 90."},
    "libraries": {"type": "array", "items": {"type": "string"}, "description": "Declared library names, e.g. [\"GxEPD2\"]."},
    "boardOptions": {"type": "object", "description": "Native UI build options, preserved."},
}, ["id", "boardKind", "x", "y", "activeFileGroupId"],
    'Native board instance. Minimal: {"id":"esp","boardKind":"esp32","x":0,"y":0,"activeFileGroupId":"sketch"}.')
component = native_obj({
    "id": {**identifier, "description": "Unique instance ID referenced by wires, e.g. epd."},
    "metadataId": {**identifier, "description": "Native metadata key, e.g. epaper-1in54-bw (not component:epaper-1in54-bw and not type)."},
    "x": coordinate, "y": coordinate,
    "properties": {"type": "object", "description": 'Required, even if empty. Use get_reference(section=project) defaults, e.g. {"panelKind":"epaper-1in54-bw","refreshMs":50}.'},
    "rotation": {"type": "number", "description": "Clockwise degrees, e.g. 0."},
}, ["id", "metadataId", "x", "y", "properties"], "Native component instance; metadataId selects its catalog definition.")
endpoint = native_obj({
    "componentId": {**identifier, "description": "Existing board or component instance ID, e.g. esp or epd."},
    "pinName": {**identifier, "description": "Exact case-sensitive pin name from get_reference(section=pins), e.g. 18 or SCK."},
    "x": coordinate, "y": coordinate,
}, ["componentId", "pinName"], 'Wire endpoint, e.g. {"componentId":"epd","pinName":"SCK"}. Coordinates are optional.')
wire = native_obj({
    "id": {**identifier, "description": "Unique wire ID, e.g. w-sck."},
    "start": endpoint, "end": endpoint,
    "color": {**string(100), "description": "Optional CSS color, e.g. #ffaa00."},
    "waypoints": {"type": "array", "items": native_obj({"x": coordinate, "y": coordinate}, ["x", "y"], "Finite waypoint coordinates.")},
}, ["id", "start", "end"], 'Native wire: {"id":"w-sck","start":{"componentId":"esp","pinName":"18"},"end":{"componentId":"epd","pinName":"SCK"}}.')
document = obj({
    "format": {"const": "velxio-project"}, "version": {"const": 1},
    "name": string(200), "exportedAt": string(80),
    "boards": {"type": "array", "maxItems": 8, "items": board},
    "fileGroups": {"type": "object", "maxProperties": 128, "additionalProperties": {
        "type": "array", "maxItems": 128, "items": file},
        "description": 'Map group IDs to source files, e.g. {"sketch":[{"name":"sketch.ino","content":""}]}. Each board references a key via activeFileGroupId.'},
    "folderGroups": {"type": "object", "additionalProperties": {"type": "array", "items": string(240)}},
    "components": {"type": "array", "maxItems": 512, "items": component},
    "wires": {"type": "array", "maxItems": 1024, "items": wire},
    "activeBoardId": {"type": ["string", "null"], "maxLength": 200, "description": "Existing board instance ID, e.g. esp, or null."},
}, ["format", "version", "boards", "fileGroups", "components", "wires", "activeBoardId"])
document["description"] = "Native .vlx snapshot. Start from get_reference(id=board:esp32,section=project). Catalog IDs are not native boardKind/metadataId values."
change = obj({
    "op": enum("set", "remove"),
    "path": {"type": "string", "maxLength": 512,
             "pattern": "^/(name|boards|fileGroups|folderGroups|components|wires|activeBoardId)(/.*)?$"},
    "value": {},
}, ["op", "path"])
change["oneOf"] = [
    {"properties": {"op": {"const": "set"}}, "required": ["value"]},
    {"properties": {"op": {"const": "remove"}}, "not": {"required": ["value"]}},
]
save = obj({"connect": {"type": "array", "minItems": 1, "maxItems": 128, "items": string(512), "description": "Named connections, e.g. board.5 -> epd.CS. Appends native wires atomically; board aliases the active board. May accompany creation or update alone with project_id/expected_version."}, "document": document, "changes": {"type": "array", "minItems": 1, "maxItems": 128, "items": change},
            "sketch": {"type": "string", "maxLength": 262144, "description": "Plain Arduino source. Supply real newlines and quotes; never JSON-encode a document or unescape the source yourself."},
            "board": {**identifier, "description": "Sketch creation only; defaults to arduino-uno."},
            "board_id": {**identifier, "description": "Optional existing board selected for a sketch update; defaults to the active board."},
            "libraries": {"type": "array", "maxItems": 128, "items": identifier},
            "from_example": {**string(240), "description": "Create a new project from a catalog example advertising from_example.supported=true. No source rewriting by the model."},
            "parameters": {"type": "object", "description": "Only the short parameters advertised by this example: board, text, pins, delay_ms, angle or other explicitly listed fields."},
            "project_id": identifier, "expected_version": version})
# Keep action/CAS alternatives below the object root for MCP client schemas.
save["if"] = {"required": ["changes"]}
save["then"] = {"required": ["project_id", "expected_version"], "not": {"required": ["document"]}}
save["else"] = {
    "required": ["document"],
    "if": {"anyOf": [{"required": ["project_id"]}, {"required": ["expected_version"]}]},
    "then": {"required": ["project_id", "expected_version"]},
}
legacy_save_alternatives = {key: save.pop(key) for key in ('if', 'then', 'else')}
save['if'] = {'required': ['sketch']}
save['then'] = {'not': {'anyOf': [{'required': ['document']}, {'required': ['changes']}]},
                'if': {'anyOf': [{'required': ['project_id']}, {'required': ['expected_version']}]},
                'then': {'required': ['project_id', 'expected_version']}}
save['else'] = legacy_save_alternatives
text_save_alternatives = {key: save.pop(key) for key in ('if', 'then', 'else')}
save['if'] = {'required': ['from_example']}
save['then'] = {'not': {'anyOf': [{'required': [key]} for key in ('document', 'changes', 'sketch', 'project_id', 'expected_version', 'board', 'board_id', 'libraries')]}}
save['else'] = text_save_alternatives
save['else'] = {'if': {'required': ['connect'], 'not': {'anyOf': [{'required': [key]} for key in ('document', 'changes', 'sketch')]}}, 'then': {'required': ['project_id', 'expected_version']}, 'else': save['else']}
# Per-action required/forbidden fields are enforced by BuildService.build_project.
build = obj({"action": enum("start", "status"), "project_id": identifier, "version": version,
             "board_id": identifier, "build_id": identifier,
             "wait_seconds": {"type": "number", "minimum": 0, "maximum": 60, "default": 20,
                              "description": "Start only: wait for a terminal build result; 0 returns immediately. A timed-out wait never cancels the build."}}, ["action"])

_INPUTS = {
    "search_catalog": obj({"query": {"type": "string", "maxLength": 256, "default": ""},
        "kind": {**enum("all", "component", "board", "example"), "default": "all"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
        "offset": {"type": "integer", "minimum": 0, "maximum": MAX_SEARCH_OFFSET, "default": 0}}),
    "get_reference": obj({"offset": {"type": "integer", "minimum": 0, "maximum": MAX_SEARCH_OFFSET, "default": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}, "id": string(240), "section": {**enum("overview", "pins", "attrs", "protocol", "libraries", "init", "limitations", "sources", "files", "project", "code"), "default": "overview",
        "description": "project: boards return a directly saveable native document in data and an instance_template beside data. Components return data.instance_template (id, bare metadataId, x, y, properties), components[] and known pinNames or unknown. example_references links real examples; code retrieves source. Simulation is unsupported."}}, ["id"]),
    "save_project": save,
    "check_project": obj({"project_id": identifier, "version": version}, ["project_id", "version"]),
    "build_project": build,
    "read_artifact": obj({"artifact_id": identifier,
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "length": {"type": "integer", "minimum": 1, "maximum": 12288, "default": 4096},
        "encoding": {**enum("utf8", "base64"), "default": "utf8"}}, ["artifact_id"]),
}

_ERROR = obj({"ok": {"const": False}, "error": obj({
    "code": string(80), "message": string(500),
    "path_truncated": {"type": "boolean"},
    "path": {"type": "string", "maxLength": 512, "description": "RFC 6901 pointer; document errors are relative to the native document, argument errors to the tool arguments. Empty string denotes the root."},
    "received": {"type": "string", "maxLength": 200, "description": "JSON value preview (truncated), or <missing>."},
    "expected": string(500),
    "file": string(240), "observed": string(240), "next_action": string(500),
}, ["code", "message", "path", "received", "expected", "next_action"])}, ["ok", "error"])
artifact = obj({"id": identifier, "kind": string(80), "size_bytes": {"type": "integer", "minimum": 0}, "sha256": version}, ["id", "kind", "size_bytes", "sha256"])
readable_error = obj({"file": {"type": ["string", "null"], "maxLength": 240},
                      "line": {"type": ["integer", "null"], "minimum": 0},
                      "message": string(240), "suggestion": string(500)}, ["file", "line", "message", "suggestion"])
_RESULTS = {
    "search_catalog": obj({"revision": version, "items": {"type": "array", "maxItems": 50, "items": obj({
        "id": identifier, "kind": enum("component", "board", "example"), "name": string(500),
        "summary": {"type": "string", "maxLength": 300}, "metadataId": identifier, "boardKind": identifier,
        "from_example": {"type": "object"}}, ["id", "kind", "name", "summary"])},
        "query_original": {"type": "string", "maxLength": 256},
        "query_used": {"type": "array", "items": {"type": "string", "maxLength": 256}, "maxItems": 128},
        "total": {"type": "integer", "minimum": 0}, "has_more": {"type": "boolean"},
        "next_offset": {"type": ["integer", "null"], "minimum": 0, "maximum": MAX_SEARCH_OFFSET}},
        ["revision", "items", "query_original", "query_used", "total", "has_more", "next_offset"]),
    "get_reference": obj({"id": identifier, "revision": version, "section": _INPUTS["get_reference"]["properties"]["section"],
                          "data": {}, "instance_template": {"type": "object"},
                          "from_example": {"type": "object"},
                          "example_references": {"type": "array", "items": identifier, "maxItems": 8},
                          "example_options": {"type": "array", "maxItems": 8, "items": {"type": "object"}},
                          "execution": obj({"supported": {"const": False}, "state": {"const": "unsupported"}, "message": string(500)}, ["supported", "state", "message"])}, ["id", "revision", "section", "data"]),
    "save_project": obj({"project_id": identifier, "version": version, "content_sha256": version,
        "board_id": identifier, "sketch_file": string(240),
        "example_provenance": {"type": "object"},
        "warnings": {"type": "array", "maxItems": 2, "items": obj({"file": string(240), "observed": string(240), "correction": string(500)}, ["file", "observed", "correction"])},
        "project_artifact_id": identifier, "summary": string(500),
        # A future downloadable artifact, not a promised existing HTTP route.
        "download_url": {"type": ["string", "null"], "maxLength": 2048}},
        ["project_id", "version", "content_sha256", "project_artifact_id", "summary", "download_url"]),
    "check_project": obj({"status": enum("valid", "invalid", "partial"),
        "structure_status": enum("valid", "invalid"), "project_id": identifier, "version": version,
        "catalog_revision": version, "diagnostic_artifact_sha256": version,
        "issues": {"type": "array", "maxItems": 20, "items": obj({
            "code": string(100), "path": {"type": "string", "maxLength": 512},
            "severity": enum("error", "warning", "unknown", "info"), "message": string(240),
            "file": string(240), "observed": string(240), "expected": string(240), "next_action": string(500),
            "path_truncated": {"type": "boolean"}}, ["code", "path", "severity", "message"])},
        "issue_count": {"type": "integer", "minimum": 0, "maximum": 4096}, "issues_truncated": {"type": "boolean"},
        "checks_performed": {"type": "array", "items": string(100)},
        "checks_unavailable": {"type": "array", "items": string(100)},
        "diagnostic_summary": string(500), "diagnostic_artifact_id": {"type": ["string", "null"]}, "next_action": string(500)},
        ["status", "structure_status", "project_id", "version", "catalog_revision", "diagnostic_artifact_sha256", "issues", "issue_count", "issues_truncated", "checks_performed", "checks_unavailable", "diagnostic_summary", "diagnostic_artifact_id", "next_action"]),
    "build_project": obj({"build_id": identifier, "state": enum("running", "done", "error", "interrupted"),
        "stage": enum("queued", "compiling", "complete"), "next_action": string(500),
        "first_error": {**readable_error, "type": ["object", "null"]},
        "warnings": {"type": "array", "maxItems": 5, "items": {"type": "object"}}, "warnings_truncated": {"type": "boolean"},
        "project_id": identifier, "version": version, "board_id": identifier,
        "test_only": {"type": "boolean"}, "log_truncated": {"type": "boolean"},
        "provenance_sha256": version, "toolchain_version": string(200),
        "firmware_type": {"type": ["string", "null"], "enum": [None, "bin", "hex", "uf2", "elf"]},
        "reproducibility_limited": {"const": True}, "shared_cache_allowed": {"const": False},
        "diagnostics": {"type": "array", "maxItems": 10, "items": {"type": "object"}},
        "diagnostics_truncated": {"type": "boolean"},
        "success": {"type": ["boolean", "null"]}, "error_kind": {"type": ["string", "null"]},
        "artifacts": {"type": "array", "maxItems": 20, "items": artifact},
        "diagnostic_summary": {"type": "string", "maxLength": 500}}, ["build_id", "state", "stage", "success", "first_error", "warnings", "warnings_truncated", "next_action"]),
    "read_artifact": obj({"data": {"type": "string", "maxLength": 16384},
        "offset": {"type": "integer", "minimum": 0}, "next_offset": {"type": ["integer", "null"], "minimum": 0},
        "total_bytes": {"type": "integer", "minimum": 0}, "sha256": version,
        "eof": {"type": "boolean"}, "truncated": {"type": "boolean"}, "encoding": enum("utf8", "base64")},
        ["data", "offset", "next_offset", "total_bytes", "sha256", "eof", "truncated", "encoding"]),
}

# Catalog navigation is machine-readable and byte bounded for both tools.
for name in ('search_catalog', 'get_reference'):
    _RESULTS[name]['properties'].update({
        'offset': {'type': 'integer', 'minimum': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
        'total': {'type': 'integer', 'minimum': 0},
        'has_more': {'type': 'boolean'},
        'truncated': {'type': 'boolean'},
        'next_offset': {'type': ['integer', 'null'], 'minimum': 0},
        'max_response_bytes': {'const': MAX_RESPONSE_BYTES},
        'next_section': {'type': ['string', 'null']},
        'next_request': {'type': ['object', 'null']},
        'next_action': string(500),
    })
    for field in ('offset', 'limit', 'total', 'has_more', 'truncated', 'next_offset', 'max_response_bytes', 'next_section', 'next_request', 'next_action'):
        if field not in _RESULTS[name]['required']:
            _RESULTS[name]['required'].append(field)
_RESULTS['get_reference']['properties'].update({'data_complete': {'type': 'boolean'},
    'metadata_omitted': {'type': 'array', 'items': {'type': 'string'}},
    'fragments': {'type': 'array', 'maxItems': 50, 'items': {'type': 'object'}}})
_RESULTS['get_reference']['required'].append('data_complete')

# A transport-success response is not itself a build-success certificate.
_RESULTS['build_project']['allOf'] = [
    {'if': {'properties': {'state': {'const': 'done'}}},
     'then': {'properties': {'success': {'const': True}, 'stage': {'const': 'complete'}}}},
    {'if': {'properties': {'state': {'const': 'running'}}},
     'then': {'properties': {'success': {'const': None}, 'stage': enum('queued', 'compiling'),
                             'next_action': {'pattern': '^call build_project status build_id=b_[0-9a-f]{32}$'}}}},
    {'if': {'properties': {'state': {'enum': ['error', 'interrupted']}}},
     'then': {'properties': {'success': {'const': False}, 'stage': {'const': 'complete'}}}},
]


def output_schema(name):
    success = deepcopy(_RESULTS[name])
    success["properties"]["ok"] = {"const": True}
    success["required"].append("ok")
    return {"oneOf": [success, deepcopy(_ERROR)]}


TOOL_SCHEMAS = {name: {"name": name, "inputSchema": deepcopy(schema),
                       "outputSchema": output_schema(name),
                       "implemented": True}
                for name, schema in _INPUTS.items()}
