"""Chat-only API snippets, derived from catalog examples and reviewed recipes.

The shared compact catalog deliberately does not extract library APIs. Chat
cards can include a bounded, provenance-carrying API slice so a small model
does not have to invent a driver or spend extra tool calls on a full example.
Nothing here rewrites the catalog or changes the six-tool MCP responses.
"""
from __future__ import annotations

import re


# A focused reviewed recipe is preferred over a broad native example. Recipe
# parameters use only documented defaults except for the optional peripheral
# that makes the generated code exercise this component.
_RECIPES = {
    'servo': ('example:uno-servo', {}),
    'potentiometer': ('example:uno-servo', {'control': 'potentiometer'}),
    'slide-potentiometer': ('example:uno-servo', {'control': 'potentiometer', 'input_component': 'slide-potentiometer'}),
    'lcd1602-i2c': ('example:uno-hcsr04', {'display': 'lcd1602-i2c'}),
    'ssd1306-i2c-4pin': ('example:uno-hcsr04', {'display': 'ssd1306'}),
    'buzzer': ('example:uno-hcsr04', {'alarm': 'buzzer', 'threshold': 25}),
    'hc-sr04': ('example:uno-hcsr04', {}),
    'dht22': ('example:uno-dht22', {}),
}

# Driver class names and functions that belong to each component. Calls are
# matched against these instead of returning the whole example.
_HINTS = {
    'servo': (('Servo',), ('attach', 'write', 'writeMicroseconds', 'read', 'detach')),
    'potentiometer': ((), ('analogRead', 'map', 'constrain')),
    'slide-potentiometer': ((), ('analogRead', 'map', 'constrain')),
    'lcd1602-i2c': (('LiquidCrystal_I2C',), ('init', 'begin', 'backlight', 'noBacklight', 'clear', 'home',
                                            'setCursor', 'print', 'println', 'blink', 'noBlink', 'createChar')),
    'lcd1602': (('LiquidCrystal',), ('begin', 'clear', 'home', 'setCursor', 'print', 'println', 'blink',
                                     'noBlink', 'createChar')),
    'lcd2004': (('LiquidCrystal',), ('begin', 'clear', 'home', 'setCursor', 'print', 'println', 'blink',
                                     'noBlink', 'createChar')),
    'ssd1306-i2c-4pin': (('Adafruit_SSD1306',), ('begin', 'clearDisplay', 'setCursor', 'print', 'println', 'display',
                                                'setTextColor', 'setTextSize', 'drawPixel', 'drawLine', 'drawRect',
                                                'fillRect', 'drawCircle', 'fillCircle')),
    'dht22': (('DHT',), ('begin', 'readTemperature', 'readHumidity', 'computeHeatIndex')),
    'hc-sr04': ((), ('pulseIn', 'digitalWrite', 'delayMicroseconds', 'pinMode')),
    'buzzer': ((), ('tone', 'noTone')),
    'led': ((), ('digitalWrite', 'analogWrite', 'pinMode')),
    'pushbutton': ((), ('digitalRead', 'pinMode')),
}

_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
_ARDUINO = re.compile(r'\bvoid\s+(?:setup|loop)\s*\(')
_BOARD_PREFIXES = {
    'uno': 'arduino-uno', 'nano': 'arduino-nano', 'mega': 'arduino-mega',
    'esp32': 'esp32', 'pico': 'raspberry-pi-pico', 'c3': 'esp32-c3',
}
_BOARD_TYPES = {
    'arduino-uno': 'arduino-uno', 'arduino-nano': 'arduino-nano', 'arduino-mega': 'arduino-mega',
    'esp32-devkit-v1': 'esp32', 'esp32': 'esp32', 'raspberry-pi-pico': 'raspberry-pi-pico',
}


def _native_board(project, entry):
    for board in project.get('boards', []):
        if board.get('boardKind'):
            return board['boardKind']
    if project.get('boardFilter'):
        return project['boardFilter']
    for component in project.get('components', []):
        kind = component.get('type', '').removeprefix('wokwi-').removeprefix('velxio-')
        if kind in _BOARD_TYPES:
            return _BOARD_TYPES[kind]
    prefix = entry.get('id', '').split(':', 1)[-1].split('-', 1)[0]
    return _BOARD_PREFIXES.get(prefix)


def _project_code(project):
    code = project.get('code')
    if isinstance(code, str) and '\n' in code:
        return code
    for board in project.get('boards', []):
        board_code = board.get('code')
        if isinstance(board_code, str) and '\n' in board_code:
            return board_code
    return ''


def _declarations(code, classes):
    out = []
    for name in classes:
        for match in re.finditer(r'^\s*' + re.escape(name) + r'\s+([A-Za-z_]\w*)\s*(?:\([^;\n]*\))?\s*;', code, re.M):
            line = match.group(0).strip()
            if line not in out:
                out.append(line)
    return out


def _instances(code, classes):
    names = []
    for name in classes:
        for match in re.finditer(r'^\s*' + re.escape(name) + r'\s+([A-Za-z_]\w*)\s*(?:\([^;\n]*\))?\s*;', code, re.M):
            if match.group(1) not in names:
                names.append(match.group(1))
    return names


def _calls(code, classes, functions):
    out = []
    funcs = '|'.join(re.escape(name) for name in functions)
    if funcs:
        for match in re.finditer(r'^\s*.*?(?<!\.)\b(?:' + funcs + r')\s*\([^;\n]*\).*?$', code, re.M):
            line = match.group(0).strip()
            if line and line not in out and not line.startswith(('#', '//')):
                out.append(line)
    for instance in _instances(code, classes):
        pattern = r'^\s*.*?\b' + re.escape(instance) + r'\.\w+\s*\([^;\n]*\).*?$'
        for match in re.finditer(pattern, code, re.M):
            line = match.group(0).strip()
            if line and line not in out and not line.startswith(('#', '//')):
                out.append(line)
    return out


def _slice(code, key):
    classes, functions = _HINTS.get(key, ((), ()))
    includes = []
    for match in _INCLUDE.finditer(code):
        header = match.group(1)
        if header not in includes:
            includes.append(header)
    declarations = _declarations(code, classes)
    calls = _calls(code, classes, functions)
    # Keep cards small and deterministic. The first occurrence of a call is
    # the clearest one; duplicate argument shapes add little for the model.
    seen, unique = set(), []
    for call in calls:
        shape = re.sub(r'"[^"]*"|\'[^\']*\'|\b\d+(?:\.\d+)?\b', 'x', call)
        if shape in seen:
            continue
        seen.add(shape)
        unique.append(call)
    return {'includes': includes[:6], 'declarations': declarations[:6], 'calls': unique[:10]}


def _recipe(catalog, key):
    target = _RECIPES.get(key)
    if not target:
        return None
    reference, parameters = target
    try:
        from app.mcp.compact.examples import instantiate
        document = instantiate(catalog, reference, parameters)
        if isinstance(document, tuple):
            document = document[0]
        group = document['boards'][0]['activeFileGroupId']
        code = document['fileGroups'][group][0]['content']
    except Exception:
        return None
    board = document['boards'][0].get('boardKind')
    return {
        'source': reference,
        'kind': 'reviewed_recipe',
        'board': board,
        'libraries': list(document['boards'][0].get('libraries', [])),
        'parameters': parameters,
        'code': code,
    }


def _native(catalog, key, board_kind=None):
    candidates = []
    for entry in catalog._entries.values():
        if entry.get('kind') != 'example':
            continue
        project = entry.get('project', {})
        types = {component.get('type', '').removeprefix('wokwi-').removeprefix('velxio-')
                 for component in project.get('components', [])}
        if key not in types:
            continue
        code = _project_code(project)
        if not code or not _ARDUINO.search(code):
            continue
        board = _native_board(project, entry)
        candidates.append({
            'source': entry['id'],
            'kind': 'example',
            'board': board,
            'libraries': list(project.get('libraries', [])),
            'code': code,
            '_score': (board != board_kind, len(project.get('components', [])), entry['id']),
        })
    candidates.sort(key=lambda item: (item['_score'], item['source']))
    return candidates[0] if candidates else None


def usage(catalog, key, board_kind=None):
    """Return a bounded API slice for a component, or None.

    The slice is derived from code that already exists in the catalog or from
    a reviewed recipe. No API names are invented from component metadata.
    """
    cache = getattr(catalog, '_chat_usage_cache', None)
    if cache is None:
        cache = catalog._chat_usage_cache = {}
    cache_key = (key, board_kind)
    if cache_key in cache:
        return cache[cache_key]
    candidate = _recipe(catalog, key) or _native(catalog, key, board_kind)
    if not candidate:
        cache[cache_key] = None
        return None
    sliced = _slice(candidate['code'], key)
    if not any(sliced.values()) and not candidate.get('libraries'):
        cache[cache_key] = None
        return None
    result = {name: candidate[name] for name in ('source', 'kind', 'board', 'libraries') if candidate.get(name) is not None}
    result.update(sliced)
    result['note'] = 'Extracted from a verified example; adapt pin numbers and addresses to your circuit.'
    cache[cache_key] = result
    return result
