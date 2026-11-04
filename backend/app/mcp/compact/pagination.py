"""Deterministic item and byte bounded catalog pages with explicit continuations."""
import copy
import json

from .contracts import MAX_RESPONSE_BYTES


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def text_chunks(text, size=2048):
    raw = text.encode('utf-8')
    offset = 0
    while offset < len(raw):
        end = min(offset + size, len(raw))
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        yield offset, end, raw[offset:end].decode('utf-8')
        offset = end


def next_section(section, kind):
    if section == 'overview':
        return 'project'
    if section == 'project':
        return 'code' if kind == 'example' else 'pins'
    if section in ('pins', 'attrs', 'protocol'):
        return 'libraries'
    if section == 'libraries':
        return 'init'
    if section == 'init':
        return 'limitations'
    if section == 'limitations':
        return 'sources'
    if section == 'sources':
        return 'files'
    if section == 'files':
        return 'code' if kind == 'example' else None
    return None


def continuation(tool, arguments):
    return {'tool': tool, 'arguments': arguments}


def search_page(result, arguments):
    result = copy.deepcopy(result)
    offset = arguments.get('offset', 0)
    limit = arguments.get('limit', 5)
    def decorate():
        end = offset + len(result['items'])
        more = end < result['total']
        result.update(offset=offset, limit=limit, has_more=more,
                      truncated=offset > 0 or more, next_offset=end if more else None,
                      max_response_bytes=MAX_RESPONSE_BYTES, next_section='project')
        if more:
            request = continuation('search_catalog', {**arguments, 'offset': end, 'limit': limit})
        elif result['items']:
            first = result['items'][0]
            request = (continuation('save_project', {'from_example': first['id']}) if first.get('from_example', {}).get('supported') else
                       continuation('get_reference', {'id': first['id'], 'section': 'project'}))
        else:
            request = None
        result['next_request'] = request
        result['next_action'] = ('Use a matching item now. Only if none fits, call next_request with its exact arguments; do not repeat this page.' if more else
                                 'Use a matching ID and its advertised parameters; next_request is an optional starting point.' if request else
                                 'No matches on this page. Refine the query or return to offset=0; do not repeat this empty page.')
    decorate()
    while len(encoded(result)) > MAX_RESPONSE_BYTES and len(result['items']) > 1:
        result['items'].pop()
        decorate()
    return result


def _atoms(value, path=()):
    # Large nested values become explicit pointer fragments; never return a
    # half-native document that could be mistaken for a complete template.
    if len(encoded(value)) <= 12 * 1024:
        return [(path, value, None)]
    if isinstance(value, dict):
        return [unit for key, child in value.items() for unit in _atoms(child, (*path, key))]
    if isinstance(value, list):
        return [unit for index, child in enumerate(value) for unit in _atoms(child, (*path, index))]
    if isinstance(value, str):
        total = len(value.encode('utf-8'))
        return [(path, chunk, {'text_offset': start, 'next_text_offset': end if end < total else None,
                               'text_total_bytes': total}) for start, end, chunk in text_chunks(value)]
    return [(path, value, None)]


def _units(value):
    if isinstance(value, dict):
        return [unit for key, child in value.items() for unit in _atoms(child, (key,))]
    if isinstance(value, list):
        return [unit for index, child in enumerate(value) for unit in _atoms(child, (index,))]
    return _atoms(value)


def _code_units(value):
    units = []
    for group, field in (('files', 'content'), ('raw_inputs', 'content_b64')):
        for item in value.get(group, []):
            if len(encoded(item)) <= 8192:
                units.append((group, item))
                continue
            text = item.get(field, '')
            total = len(text.encode('utf-8'))
            for start, end, chunk in text_chunks(text):
                units.append((group, {**item, field: chunk, field + '_offset': start,
                                     field + '_next_offset': end if end < total else None,
                                     field + '_total_bytes': total}))
    return units


def reference_page(result, arguments, kind):
    result = copy.deepcopy(result)
    data = result.pop('data')
    omitted = []
    for field in ('instance_template', 'example_options', 'example_references'):
        if field in result and len(encoded(result[field])) > 4096:
            result.pop(field)
            omitted.append(field)
    if omitted:
        result['metadata_omitted'] = omitted
    offset, limit = arguments.get('offset', 0), arguments.get('limit', 20)
    code = result['section'] == 'code' and isinstance(data, dict)
    units = _code_units(data) if code else _units(data)
    total = len(units)
    depth = 1 if isinstance(data, (dict, list)) else 0
    fragment_mode = not code and any(len(path) != depth or chunk is not None for path, _, chunk in units)
    following = next_section(result['section'], kind)
    count = min(limit, max(0, total - offset))
    def render(count):
        page = units[offset:offset + count]
        fragments = []
        chunked = False
        if code:
            payload = {'files': [], 'raw_inputs': []}
            for group, value in page:
                payload[group].append(value)
                chunked |= 'content_offset' in value or 'content_b64_offset' in value
        else:
            if not fragment_mode:
                payload = ({path[0]: value for path, value, _ in page} if isinstance(data, dict) else
                           [value for _, value, _ in page] if isinstance(data, list) else page[0][1] if page else None)
            else:
                payload = None
                for path, value, chunk in page:
                    pointer = ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in path)
                    fragments.append({'path': pointer, 'value': value, **(chunk or {})})
        end = offset + count
        more = end < total
        partial = offset > 0 or more or fragment_mode or chunked
        output = {**result, 'data': payload, 'data_complete': not partial,
                  'offset': offset, 'limit': limit, 'total': total,
                  'has_more': more, 'truncated': partial or bool(omitted), 'next_offset': end if more else None,
                  'max_response_bytes': MAX_RESPONSE_BYTES, 'next_section': following}
        if fragment_mode:
            output['fragments'] = fragments
        if more:
            output['next_request'] = continuation('get_reference', {'id': result['id'], 'section': result['section'], 'offset': end, 'limit': limit})
            output['next_action'] = 'If you need the complete section, call next_request. This page is partial; do not save it as a complete native project.'
        else:
            output['next_request'] = continuation('get_reference', {'id': result['id'], 'section': following}) if following else None
            output['next_action'] = ('Section finished. Partial pages/fragments must be combined by path or file and byte offset before use; prefer from_example when supported. next_section is optional.' if partial else
                                     'Section complete. Use the template or advertised example parameters; next_section is optional.')
        return output
    output = render(count)
    while len(encoded(output)) > MAX_RESPONSE_BYTES and count > 1:
        count -= 1
        output = render(count)
    return output
