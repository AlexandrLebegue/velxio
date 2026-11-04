"""Lossless tolerant argument transport; incomplete structures are never repaired."""
import copy
import json
import math
import re


def normalize(tool, arguments):
    if not isinstance(arguments, dict):
        return arguments
    result = {key: copy.deepcopy(value) for key, value in arguments.items() if key != 'cursor'}
    fields = {'document':dict,'changes':list,'parameters':dict,'libraries':list} if tool == 'save_project' else {}
    for key, kind in fields.items():
        value = result.get(key)
        if isinstance(value, str) and len(value) <= 2 * 1024 * 1024:
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                # An extra quoting layer is tolerable only if BOTH parses are
                # complete. No guessed brackets, paths, values or source edits.
                try:
                    unquoted = json.loads('"' + value + '"')
                    decoded = json.loads(unquoted)
                except (ValueError, TypeError, RecursionError):
                    continue
            if isinstance(decoded, kind):
                result[key] = decoded
    from .contracts import TOOL_SCHEMAS
    def coerce(value, spec):
        kind = spec.get('type')
        if isinstance(value, str):
            if kind in ('integer','number') and re.fullmatch(r'0[xX][0-9a-fA-F]{1,8}',value):
                return int(value,16)
            if kind in ('integer','number') and re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d+)?',value) and len(value) <= 40:
                number = float(value) if '.' in value else int(value)
                if kind == 'number' or isinstance(number,int):
                    return number
            if kind == 'boolean' and value in ('true','false'):
                return value == 'true'
        if isinstance(value,dict) and kind == 'object':
            return {key:coerce(child,spec.get('properties',{}).get(key,{})) for key,child in value.items()}
        if isinstance(value,list) and kind == 'array':
            return [coerce(child,spec.get('items',{})) for child in value]
        return value
    result = coerce(result, TOOL_SCHEMAS.get(tool,{}).get('inputSchema',{}))
    if tool == 'save_project' and isinstance(result.get('from_example'),str) and isinstance(result.get('parameters'),dict):
        from .examples import recipe_metadata
        key = result['from_example'];key = key if key.startswith('example:') else 'example:'+key
        schema = recipe_metadata(key).get('parameters',{})
        result['parameters'] = coerce(result['parameters'],schema)
    return result
