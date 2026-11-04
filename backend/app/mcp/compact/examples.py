"""Reviewed catalog example recipes. No model-authored code substitutions."""
import copy
import hashlib
import json
import math

from .catalog import CatalogError

BLINK = 'example:blink-led'
SERVO = 'example:uno-servo'
EPAPER = 'example:epaper-1in54-uno-hello'
RECIPES = {
    BLINK: {'board': {'type': 'string', 'enum': ['arduino-uno','arduino-nano'], 'default': 'arduino-uno'},
            'frequency_hz': {'type':'number','minimum':0.01,'maximum':500,
                             'description':'Full blink cycles per second (on AND off). Prefer this for a requested blink rate. Rounded to whole milliseconds per phase; do not also set delay_ms.'},
            'delay_ms': {'type': 'integer', 'minimum': 1, 'maximum': 60000, 'default': 1000,
                         'description':'Duration of EACH on/off phase, not the full cycle. A cycle takes 2*delay_ms; alternative to frequency_hz.'},
            'external_led': {'type': 'boolean', 'default': False},
            'resistance_ohms': {'type':'integer','minimum':10,'maximum':1000000,'default':1000},
            'led_color': {'type':'string','enum':['red','green','blue','yellow','white'],'default':'red'},
            'pins': {'type': 'object', 'properties': {'LED': {'type': 'integer', 'minimum': 2, 'maximum': 13, 'default': 13}}, 'additionalProperties': False}},
    SERVO: {'board': {'type': 'string', 'enum': ['arduino-uno', 'arduino-nano'], 'default': 'arduino-uno'},
            'delay_ms': {'type': 'integer', 'minimum': 1, 'maximum': 60000, 'default': 1000, 'description': 'Fixed-angle mode only: supply angle as well.'},
            'angle': {'type': 'integer', 'minimum': 0, 'maximum': 180, 'description': 'When supplied, replace the sweep with a fixed angle.'},
            'pins': {'type': 'object', 'properties': {'PWM': {'type': 'integer', 'minimum': 2, 'maximum': 13, 'default': 9}}, 'additionalProperties': False}},
    EPAPER: {'board': {'type': 'string', 'enum': ['arduino-uno', 'esp32'], 'default': 'arduino-uno'},
             'text': {'type': 'string', 'minLength': 1, 'maxLength': 16, 'default': 'Velxio'},
             'frame': {'type': 'boolean', 'default': False},
             'align': {'type':'string','enum':['original','center'],'default':'original'},
             'pins': {'type': 'object', 'properties': {role: {'type': 'integer', 'minimum': 2, 'maximum': 33}
                      for role in ('CS', 'DC', 'RST', 'BUSY')}, 'additionalProperties': False,
                      'description': 'Defaults: Uno CS=10 DC=9 RST=8 BUSY=7; ESP32 CS=5 DC=17 RST=16 BUSY=4. Controls must be distinct. Uno allows 2..10; ESP32 allows 2,4,5,12..17,21,22,25..27,32,33. SPI, serial and reserved pins are excluded.'}},
}


from .peripherals import SCHEMAS as PERIPHERAL_SCHEMAS
RECIPES.update(PERIPHERAL_SCHEMAS)
RECIPES[SERVO].update(control={'type':'string','enum':['sweep','potentiometer'],'default':'sweep'},
    analog_pin={'type':'string','enum':['A0','A1','A2','A3','A4','A5'],'default':'A0'},
    input_component={'type':'string','enum':['potentiometer','slide-potentiometer'],'default':'potentiometer'},
    sample_ms={'type':'integer','minimum':1,'maximum':1000,'default':15})


def recipe_metadata(reference_id):
    fields = RECIPES.get(reference_id)
    if fields is None:
        return {'supported': False}
    return {'supported': fields is not None, 'parameters': {
        'type': 'object', 'properties': copy.deepcopy(fields or {}), 'additionalProperties': False}}


def uses_component(reference_id, component):
    if reference_id in PERIPHERAL_SCHEMAS:
        actual = {'pushbutton','led','resistor'} if reference_id=='example:button-led' else {'hc-sr04' if 'hcsr04' in reference_id else 'dht22','lcd1602-i2c','ssd1306-i2c-4pin','led','resistor','buzzer'}
        return component in actual
    if reference_id==SERVO and component in ('potentiometer','slide-potentiometer'):
        return True
    return component in ({BLINK: ('led', 'resistor'), SERVO: ('servo',), EPAPER: ('epaper-1in54-bw',)}.get(reference_id, ()))


def _checked(parameters, fields, path='/parameters'):
    from .projects import invalid, pointer
    if not isinstance(parameters, dict):
        invalid(path, parameters, 'short parameter object')
    for key in parameters.keys() - fields.keys():
        invalid(pointer(path, key), parameters[key], 'known parameters: ' + ', '.join(fields))
    for key, value in parameters.items():
        spec = fields[key]
        kind = spec['type']
        if kind == 'object':
            _checked(value, spec['properties'], pointer(path, key))
        elif (kind == 'number' and (type(value) not in (int,float) or not math.isfinite(value) or not spec['minimum'] <= value <= spec['maximum'])
              or kind == 'integer' and (type(value) is not int or not spec['minimum'] <= value <= spec['maximum'])
              or kind == 'boolean' and type(value) is not bool
              or kind == 'string' and (not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value)
                  or 'enum' in spec and value not in spec['enum']
                  or not spec.get('minLength', 1) <= len(value) <= spec.get('maxLength', 200))):
            invalid(pointer(path, key), value, json.dumps(spec, ensure_ascii=True))


def _replace(source, old, new, count=1):
    if source.count(old) != count:
        raise CatalogError('unsupported', 'Catalog source no longer matches the reviewed recipe; review is required')
    return source.replace(old, new)


def instantiate(catalog, reference_id, parameters):
    if reference_id in PERIPHERAL_SCHEMAS:
        from .peripherals import instantiate as peripheral
        return peripheral(catalog,reference_id,parameters)
    entry = catalog._entries.get(reference_id)
    if reference_id not in RECIPES or entry is None or entry['kind'] != 'example':
        raise CatalogError('unsupported', 'No reviewed native recipe for this example; select one advertising from_example.supported=true')
    _checked(parameters, RECIPES[reference_id])
    values = {key: copy.deepcopy(spec['default']) for key, spec in RECIPES[reference_id].items() if 'default' in spec}
    values.update(copy.deepcopy(parameters))
    board_kind = values['board']
    project = entry['project']
    source = project.get('code')
    if not isinstance(source, str) or '\n' not in source:
        raise CatalogError('unsupported', 'The reviewed recipe requires the catalog multiline Arduino source')
    original_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    doc = catalog.get_reference(id='board:' + board_kind, section='project')['data']
    board = doc['boards'][0]
    board.update(id='arduino-uno', libraries=copy.deepcopy(project.get('libraries', [])))
    doc['activeBoardId'] = board['id']
    for part in project['components']:
        key = part['type'].removeprefix('wokwi-').removeprefix('velxio-')
        if key == 'arduino-uno':
            continue
        fragment = catalog.get_reference(id='component:' + key, section='project')
        if not fragment.get('ok'):
            raise CatalogError('unsupported', 'A recipe component is missing from the catalog')
        native = fragment['data']['instance_template']
        native.update(id=part['id'], x=part.get('x', 400), y=part.get('y', 100))
        native['properties'].update(copy.deepcopy(part.get('properties', {})))
        doc['components'].append(native)
    doc['wires'] = copy.deepcopy(project['wires'])
    pins = values.get('pins', {})
    if reference_id == BLINK:
        if 'frequency_hz' in parameters:
            if 'delay_ms' in parameters:
                raise CatalogError('invalid_argument','Choose frequency_hz OR per-phase delay_ms, not both')
            values['delay_ms'] = max(1, int(math.floor(500 / values['frequency_hz'] + 0.5)))
        pin = pins.get('LED', 13)
        if pin != 13 and not values['external_led']:
            raise CatalogError('invalid_argument', 'The built-in LED is fixed at 13; set external_led=true to remap it')
        source = _replace(source, 'pinMode(13, OUTPUT)', f'pinMode({pin}, OUTPUT)')
        source = _replace(source, 'digitalWrite(13,', f'digitalWrite({pin},', 2)
        source = _replace(source, 'delay(1000);', f"delay({values['delay_ms']});", 2)
        source = source.replace('built-in LED on pin 13', f'LED on pin {pin}')
        if values['external_led']:
            for key in ('led', 'resistor'):
                native = catalog.get_reference(id='component:' + key, section='project')['data']['instance_template']
                native.update(x=450 if key == 'led' else 300, y=100)
                native['properties'].update({'value':str(values['resistance_ohms'])} if key=='resistor' else {'color':values['led_color']})
                doc['components'].append(native)
            doc['wires'] = [
                {'id': 'led-drive', 'start': {'componentId': board['id'], 'pinName': str(pin)}, 'end': {'componentId': 'resistor-1', 'pinName': '1'}},
                {'id': 'led-series', 'start': {'componentId': 'resistor-1', 'pinName': '2'}, 'end': {'componentId': 'led-1', 'pinName': 'A'}},
                {'id': 'led-ground', 'start': {'componentId': 'led-1', 'pinName': 'C'}, 'end': {'componentId': board['id'], 'pinName': 'GND.1'}},
            ]
        pins = {'LED': pin}
    elif reference_id == SERVO:
        pin = pins.get('PWM', 9)
        source = _replace(source, '#define SERVO_PIN 9', f'#define SERVO_PIN {pin}')
        source = source.replace('pin 9', 'pin ' + str(pin))
        if values['control']=='potentiometer' and 'angle' in parameters:
            raise CatalogError('invalid_argument','Choose either potentiometer control or a fixed angle')
        if 'angle' in values:
            if source.count('void loop() {') != 1:
                raise CatalogError('unsupported', 'Servo loop no longer matches the reviewed recipe')
            source = source.split('void loop() {')[0] + f"void loop() {{\n  myServo.write({values['angle']});\n  delay({values['delay_ms']});\n}}\n"
            source = source.replace('Servo Motor Sweep', 'Fixed Servo Angle')
            source = _replace(source, 'Serial.println("Servo Sweep demo");', f'Serial.println("Servo angle={values["angle"]}");')
        elif 'delay_ms' in parameters:
            raise CatalogError('invalid_argument', 'Servo delay_ms requires angle; otherwise the original sweep is preserved')
        else:
            values.pop('delay_ms', None)
        for wire in doc['wires']:
            if wire['end']['pinName'] == 'PWM':
                wire['start']['pinName'] = str(pin)
        pins = {'PWM': pin}
        if board_kind == 'arduino-nano':
            source = source.replace('Arduino Uno', 'Arduino Nano')
        if values['control']=='potentiometer':
            native = catalog._native_fragment(catalog._entries['component:'+values['input_component']])['instance_template']
            native.update(id='control',x=450,y=180);doc['components'].append(native)
            for role, board_pin in [('VCC','5V'),('GND','GND.1'),('SIG',values['analog_pin'])]:
                doc['wires'].append({'id':'control-'+role,'start':{'componentId':board['id'],'pinName':board_pin},'end':{'componentId':'control','pinName':role}})
            source = source.split('void loop() {')[0] + 'void loop() {\n  int angle = map(analogRead(' + values['analog_pin'] + '), 0, 1023, 0, 180);\n  myServo.write(angle);\n  delay(' + str(values['sample_ms']) + ');\n}\n'
            source = source.replace('Servo Sweep demo','Potentiometer servo control')

    else:
        defaults = dict(zip(('CS', 'DC', 'RST', 'BUSY'), (10, 9, 8, 7) if board_kind == 'arduino-uno' else (5, 17, 16, 4)))
        pins = {**defaults, **pins}
        forbidden = {0, 1, 11, 12, 13} if board_kind == 'arduino-uno' else {0, 1, 3, 6, 7, 8, 9, 10, 18, 19, 20, 23, 24, 28, 29, 30, 31}
        limit = 13 if board_kind == 'arduino-uno' else 33
        if len(set(pins.values())) != 4 or any(pin > limit or pin in forbidden for pin in pins.values()):
            raise CatalogError('invalid_argument', 'Control pins must be distinct board GPIOs outside fixed SPI, serial and reserved pins')
        for role, old in zip(('CS', 'DC', 'RST', 'BUSY'), (10, 9, 8, 7)):
            source = _replace(source, f'/*{role}=*/{old}', f'/*{role}=*/{pins[role]}')
        source = '\n'.join(line.replace('Arduino Uno', 'ESP32') if board_kind == 'esp32' and line.startswith('//') else line
                           for line in source.split('\n') if not line.startswith('// Wiring:'))
        source = f'// Native {board_kind} variant; ' + ', '.join(f'{role}={pin}' for role, pin in pins.items()) + '\n' + source
        source = _replace(source, 'F("Velxio")', 'F(' + json.dumps(values['text'], ensure_ascii=False) + ')')
        if values['align']=='center':
            import re
            cursor = re.search(r'    display.setCursor\([^\n]+\);',source)
            if cursor is None:
                raise CatalogError('unsupported','The reviewed display source no longer has the expected cursor anchor')
            text_literal = json.dumps(values['text'],ensure_ascii=False)
            center = '    int16_t tx, ty; uint16_t tw, th;\n    display.getTextBounds(' + text_literal + ', 0, 0, &tx, &ty, &tw, &th);\n    display.setCursor((display.width() - tw) / 2 - tx, (display.height() - th) / 2 - ty);'
            source = source[:cursor.start()]+center+source[cursor.end():]
            source = _replace(source, '    display.setCursor(20, 100);\n    display.print(F("ePaper"));\n    display.setCursor(20, 140);\n    display.print(F("OK!"));\n', '')
        if values['frame']:
            source = _replace(source, '    display.fillScreen(GxEPD_WHITE);', '    display.fillScreen(GxEPD_WHITE);\n    display.drawRect(0, 0, 200, 200, GxEPD_BLACK);')
        for wire in doc['wires']:
            role = wire['end']['pinName']
            if role in pins:
                wire['start']['pinName'] = str(pins[role])
            elif board_kind == 'esp32':
                wire['start']['pinName'] = {'SDI': '23', 'SCK': '18', 'VCC': '3V3', 'GND': 'GND'}[role]
    for wire in doc['wires']:
        if wire['start']['componentId'] == board['id'] and wire['start']['pinName'] == 'GND' and board_kind != 'esp32':
            wire['start']['pinName'] = 'GND.1'
    board['id'] = 'board'
    doc['activeBoardId'] = 'board'
    for wire in doc['wires']:
        for endpoint in (wire['start'], wire['end']):
            if endpoint['componentId'] == 'arduino-uno':
                endpoint['componentId'] = 'board'
    doc['fileGroups'][board['activeFileGroupId']] = [{'name': 'sketch.ino', 'content': source}]
    doc['name'] = entry['name']
    provenance = {'example_id': reference_id, 'catalog_revision': catalog.revision, 'source_sha256': original_hash,
                  'recipe_version': 2, 'parameters': {**values, 'pins': pins}}
    if reference_id == BLINK:
        delay = values['delay_ms']
        provenance['generated_behavior'] = {'on_ms':delay, 'off_ms':delay, 'cycle_ms':2*delay,
                                            'frequency_hz':500/delay, 'basis':'generated source; no runtime observation'}
    return doc, provenance
