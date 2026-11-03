"""Six independent contracts; production build owner integration is not wired."""

from copy import deepcopy

MAX_RESPONSE_BYTES = 24 * 1024
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
document = obj({
    "format": {"const": "velxio-project"}, "version": {"const": 1},
    "name": string(200), "exportedAt": string(80),
    # UI-owned nested shapes are preserved, not asserted to be fully validated here.
    "boards": {"type": "array", "maxItems": 8, "items": {"type": "object"}},
    "fileGroups": {"type": "object", "maxProperties": 128, "additionalProperties": {
        "type": "array", "maxItems": 128, "items": file}},
    "folderGroups": {"type": "object", "additionalProperties": {"type": "array", "items": string(240)}},
    "components": {"type": "array", "maxItems": 512, "items": {"type": "object"}},
    "wires": {"type": "array", "maxItems": 1024, "items": {"type": "object"}},
    "activeBoardId": {"type": ["string", "null"], "maxLength": 200},
}, ["format", "version", "boards", "fileGroups", "components", "wires", "activeBoardId"])
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
save = obj({"document": document, "changes": {"type": "array", "minItems": 1, "maxItems": 128, "items": change},
            "project_id": identifier, "expected_version": version})
save["oneOf"] = [
    {"required": ["document"], "not": {"anyOf": [{"required": ["changes"]}, {"required": ["project_id"]}, {"required": ["expected_version"]}]}},
    {"required": ["document", "project_id", "expected_version"], "not": {"required": ["changes"]}},
    {"required": ["changes", "project_id", "expected_version"], "not": {"required": ["document"]}},
]
build = {"oneOf": [
    obj({"action": {"const": "start"}, "project_id": identifier, "version": version, "board_id": identifier}, ["action", "project_id", "version", "board_id"]),
    obj({"action": {"const": "status"}, "build_id": identifier}, ["action", "build_id"]),
]}

_INPUTS = {
    "search_catalog": obj({"query": {"type": "string", "maxLength": 256, "default": ""},
        "kind": {**enum("all", "component", "board", "example"), "default": "all"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        "cursor": string(1024)}),
    "get_reference": obj({"id": string(240), "section": {**enum("overview", "pins", "attrs", "protocol", "libraries", "init", "limitations", "sources", "files", "project", "code"), "default": "overview"}}, ["id"]),
    "save_project": save,
    "check_project": obj({"project_id": identifier, "version": version}, ["project_id", "version"]),
    "build_project": build,
    "read_artifact": obj({"artifact_id": identifier,
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "length": {"type": "integer", "minimum": 1, "maximum": 12288, "default": 4096},
        "encoding": {**enum("utf8", "base64"), "default": "utf8"}}, ["artifact_id"]),
}

_ERROR = obj({"ok": {"const": False}, "error": obj({"code": string(80), "message": string(500)}, ["code", "message"])}, ["ok", "error"])
artifact = obj({"id": identifier, "kind": string(80), "size_bytes": {"type": "integer", "minimum": 0}, "sha256": version}, ["id", "kind", "size_bytes", "sha256"])
_RESULTS = {
    "search_catalog": obj({"revision": version, "items": {"type": "array", "maxItems": 20, "items": obj({
        "id": identifier, "kind": enum("component", "board", "example"), "name": string(500),
        "summary": {"type": "string", "maxLength": 300}}, ["id", "kind", "name", "summary"])},
        "next_cursor": {"type": ["string", "null"], "maxLength": 1024}}, ["revision", "items", "next_cursor"]),
    "get_reference": obj({"id": identifier, "revision": version, "section": _INPUTS["get_reference"]["properties"]["section"],
                          "data": {}}, ["id", "revision", "section", "data"]),
    "save_project": obj({"project_id": identifier, "version": version, "content_sha256": version,
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
            "path_truncated": {"type": "boolean"}}, ["code", "path", "severity", "message"])},
        "issue_count": {"type": "integer", "minimum": 0, "maximum": 4096}, "issues_truncated": {"type": "boolean"},
        "checks_performed": {"type": "array", "items": string(100)},
        "checks_unavailable": {"type": "array", "items": string(100)},
        "diagnostic_summary": string(500), "diagnostic_artifact_id": {"type": ["string", "null"]}},
        ["status", "structure_status", "project_id", "version", "catalog_revision", "diagnostic_artifact_sha256", "issues", "issue_count", "issues_truncated", "checks_performed", "checks_unavailable", "diagnostic_summary", "diagnostic_artifact_id"]),
    "build_project": obj({"build_id": identifier, "state": enum("pending", "running", "done", "error", "interrupted"),
        "project_id": identifier, "version": version, "board_id": identifier,
        "test_only": {"type": "boolean"}, "log_truncated": {"type": "boolean"},
        "provenance_sha256": version, "toolchain_version": string(200),
        "firmware_type": {"type": ["string", "null"], "enum": [None, "bin", "hex", "uf2", "elf"]},
        "reproducibility_limited": {"const": True}, "shared_cache_allowed": {"const": False},
        "diagnostics": {"type": "array", "maxItems": 10, "items": {"type": "object"}},
        "diagnostics_truncated": {"type": "boolean"},
        "success": {"type": ["boolean", "null"]}, "error_kind": {"type": ["string", "null"]},
        "artifacts": {"type": "array", "maxItems": 20, "items": artifact},
        "diagnostic_summary": {"type": "string", "maxLength": 500}}, ["build_id", "state"]),
    "read_artifact": obj({"data": {"type": "string", "maxLength": 16384},
        "offset": {"type": "integer", "minimum": 0}, "next_offset": {"type": ["integer", "null"], "minimum": 0},
        "total_bytes": {"type": "integer", "minimum": 0}, "sha256": version,
        "eof": {"type": "boolean"}, "truncated": {"type": "boolean"}, "encoding": enum("utf8", "base64")},
        ["data", "offset", "next_offset", "total_bytes", "sha256", "eof", "truncated", "encoding"]),
}


def output_schema(name):
    success = deepcopy(_RESULTS[name])
    success["properties"]["ok"] = {"const": True}
    success["required"].append("ok")
    return {"oneOf": [success, deepcopy(_ERROR)]}


TOOL_SCHEMAS = {name: {"name": name, "inputSchema": deepcopy(schema),
                       "outputSchema": output_schema(name),
                       "implemented": True}
                for name, schema in _INPUTS.items()}
