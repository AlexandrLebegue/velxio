"""One bounded, actionable error envelope for every compact tool and transport."""
import json

MISSING = object()


def preview(value):
    if value is MISSING:
        return '<missing>'
    try:
        result = ''
        for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=True).iterencode(value):
            result += chunk[:201]
            if len(result) > 200:
                break
    except (ValueError, TypeError, RecursionError):
        result = '<unserializable value>'
    return result if len(result) <= 200 else result[:197] + '...'


def pointer(parts):
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def schema_details(tool, arguments):
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return {}
    from .contracts import TOOL_SCHEMAS
    if tool not in TOOL_SCHEMAS:
        return {}
    error = next(Draft7Validator(TOOL_SCHEMAS[tool]['inputSchema']).iter_errors(arguments), None)
    if error is None:
        return {}
    parts = list(error.absolute_path)
    value = error.instance
    if error.validator == 'required' and isinstance(value, dict):
        missing = next(key for key in error.validator_value if key not in value)
        parts.append(missing)
        value = MISSING
        expected = 'required field: ' + missing
    elif error.validator == 'additionalProperties' and isinstance(value, dict):
        unknown = next((key for key in value if key not in error.schema.get('properties', {})), None)
        if unknown is not None:
            parts.append(unknown)
            value = value[unknown]
        expected = 'known fields: ' + ', '.join(error.schema.get('properties', {}))
    else:
        expected = str(error.validator) + ': ' + json.dumps(error.validator_value, ensure_ascii=True)
    # Preserve the established native document-relative pointer contract.
    if tool == 'save_project' and parts and parts[0] == 'document':
        parts.pop(0)
    return {'path': pointer(parts), 'received': preview(value), 'expected': expected[:500]}


ACTIONS = {
    'invalid_argument': 'Correct the value at path to match expected, then call {tool} once with the corrected arguments.',
    'not_found': 'Use an ID returned by a successful tool call. For catalog IDs, call search_catalog; for project/build/artifact IDs, use their creation response.',
    'ambiguous_id': 'Choose one explicit namespaced ID from expected and call get_reference.',
    'version_conflict': 'Reconcile the current project version before saving; use its version as expected_version. Do not repeat the stale update.',
    'connection_duplicate': 'Remove the duplicate or self-connection from connect; reuse the existing wire, then call save_project.',
    'pin_role_conflict': 'Choose pins with compatible roles from expected, correct connect, then call save_project.',
    'quota_exceeded': 'Reduce the requested size or release local storage through the application, then retry once; do not repeat the same oversized request.',
    'unsupported': 'Use the supported alternatives listed in expected. Do not poll or repeat an unsupported action.',
    'owner_integration_required': 'Ask the application owner to enable the offline REST build binding; do not poll or attempt installation.',
    'owner_conflict': 'Wait for the application owner to finish draining or release the build lease; do not start duplicate work.',
}


def normalize_error(result, tool=None, arguments=None):
    if not isinstance(result, dict) or result.get('ok') is not False:
        return result
    error = dict(result.get('error', {}))
    code = str(error.get('code', 'internal_error'))[:80]
    message = str(error.get('message', 'Tool request failed'))[:500]
    details = schema_details(tool, arguments) if 'path' not in error and arguments is not None else {}
    error = {**details, **error}
    error.update(code=code, message=message)
    error.setdefault('path', '')
    error.setdefault('received', preview(arguments))
    error.setdefault('expected', message or 'A valid request and available local prerequisites')
    error.setdefault('next_action', ACTIONS.get(code, 'Resolve the prerequisite described in expected before calling {tool} again. Do not repeat unchanged arguments.').format(tool=tool or 'the tool'))
    error['expected'] = str(error['expected'])[:500]
    error['next_action'] = str(error['next_action'])[:500]
    return {**result, 'error': error}


def failure(code, message, *, tool=None, arguments=None, **details):
    return normalize_error({'ok': False, 'error': {'code': code, 'message': message, **details}}, tool, arguments)
