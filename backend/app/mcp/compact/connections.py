"""Named wiring compiled to native endpoints, with conservative structural checks."""
import copy
import re

from .projects import invalid

# Reviewed native pin names used by the packaged examples. Other parts require
# an explicit catalog pin list; unknown pins are never guessed from pinCount.
PROFILES = {
    'arduino-uno': [*(str(n) for n in range(14)), *(f'A{n}' for n in range(6)), 'GND.1', 'GND.2', 'GND.3', '5V', '3.3V', 'VIN', 'RESET', 'AREF', 'IOREF'],
    'arduino-nano': [*(str(n) for n in range(14)), *(f'A{n}' for n in range(8)), 'GND.1', 'GND.2', '5V', '3.3V', 'VIN', 'RST', 'AREF'],
    'led': ['A', 'C'], 'resistor': ['1', '2'], 'servo': ['PWM', 'V+', 'GND'],
}
ALIASES = {'SCLK': 'SCK', 'CLK': 'SCK', 'MOSI': 'SDI', 'DIN': 'SDI', 'SDA': 'SDI',
           'RESET': 'RST', 'RES': 'RST', 'VDD': 'VCC', 'GROUND': 'GND',
           'ANODE': 'A', 'CATHODE': 'C', 'SIGNAL': 'PWM', 'SIG': 'PWM'}


def pin_profile(catalog, obj, board):
    key = obj['boardKind' if board else 'metadataId']
    entry = catalog._entries.get(('board:' if board else 'component:') + key, {})
    pins = entry.get('pins')
    return pins if isinstance(pins, list) else [{'name': name} for name in PROFILES.get(key, [])]


def connect_document(catalog, document, connections):
    doc = copy.deepcopy(document)
    objects = {obj['id']: (obj, board) for board, group in ((True, 'boards'), (False, 'components')) for obj in doc[group]}
    profiles = {key: pin_profile(catalog, obj, board) for key, (obj, board) in objects.items()}

    def resolve(instance, name, path):
        if instance == 'board' and instance not in objects:
            instance = doc['activeBoardId']
        if instance not in objects:
            invalid(path, instance, 'existing instance ID: ' + ', '.join(objects))
        pins = profiles[instance]
        valid = [pin['name'] for pin in pins]
        if not valid:
            invalid(path, name, 'documented pins required; valid pins: unknown; request get_reference section=pins or use a reviewed from_example')
        lookup = {pin.casefold(): pin for pin in valid}
        obj, board = objects[instance]
        alias = name.upper()
        if board:
            if alias == 'GROUND':
                alias = 'GND'
            alias = re.sub(r'^(?:GPIO|D)(\d+)$', r'\1', alias)
            if alias == 'GND' and 'GND' not in valid:
                alias = 'GND.1'
            if alias in ('3V3', '3.3V'):
                alias = '3V3' if '3V3' in valid else '3.3V'
            if obj['boardKind'] in ('arduino-uno', 'arduino-nano'):
                alias = {'SCK': '13', 'SCLK': '13', 'MOSI': '11', 'MISO': '12', 'SS': '10', 'SDA': 'A4', 'SCL': 'A5'}.get(alias, alias)
        else:
            alias = ALIASES.get(alias, alias)
            if obj['metadataId'] == 'servo' and alias in ('VCC', '5V'):
                alias = 'V+'
        native = lookup.get(name.casefold(), lookup.get(alias.casefold()))
        if native is None:
            invalid(path, name, 'valid pins for ' + str(instance) + ': ' + ', '.join(valid))
        return {'componentId': instance, 'pinName': native}

    def physical(ep):
        pin = next((p for p in profiles[ep['componentId']] if p['name'] == ep['pinName']), {})
        position = (pin['x'], pin['y']) if 'x' in pin and 'y' in pin else ep['pinName']
        return ep['componentId'], str(position)

    def role(ep):
        obj, board = objects[ep['componentId']]
        pin = ep['pinName']
        if pin.startswith('GND'):
            return 'ground'
        if pin in ('VCC', 'V+', 'VDD', '5V', '3V3', '3.3V', 'VIN', 'IOREF'):
            return 'power'
        if board:
            if obj['boardKind'] == 'esp32' and pin in ('34', '35', 'VN', 'VP'):
                return 'input'
            return 'gpio'
        if obj['metadataId'].startswith('epaper-'):
            return 'output' if pin == 'BUSY' else 'input'
        return 'input' if obj['metadataId'] == 'servo' and pin == 'PWM' else 'passive'

    # Canonicalize aliases on the existing circuit for comparison, without
    # mutating those stored endpoints. Unknown existing endpoints fail clearly.
    edges, pairs = [], set()
    for index, wire in enumerate(doc['wires']):
        ends = [resolve(wire[side]['componentId'], wire[side]['pinName'], f'/wires/{index}/{side}/pinName') for side in ('start', 'end')]
        pair = frozenset(physical(ep) for ep in ends)
        pairs.add(pair)
        edges.append((ends, f'/wires/{index}'))
    used_ids = {wire['id'] for wire in doc['wires']}
    for index, expression in enumerate(connections):
        path = f'/connect/{index}'
        parts = expression.split('->')
        if len(parts) != 2:
            invalid(path, expression, 'instance.pin -> instance.pin; e.g. board.5 -> epd.CS')
        ends = []
        for part in parts:
            part = part.strip()
            # IDs and pins can contain dots: prefer the longest existing ID.
            candidates = [key for key in [*objects, 'board'] if part.startswith(key + '.')]
            if not candidates:
                invalid(path, part, 'instance.pin; valid instance IDs: ' + ', '.join(objects) + ', board (active board)')
            instance = max(candidates, key=len)
            ends.append(resolve(instance, part[len(instance) + 1:], path))
        pair = frozenset(physical(ep) for ep in ends)
        if len(pair) != 2 or pair in pairs:
            invalid(path, expression, 'new connection between distinct physical pins; valid pins: ' + '; '.join(ep['componentId'] + '=' + ','.join(p['name'] for p in profiles[ep['componentId']]) for ep in ends), 'connection_duplicate')
        pairs.add(pair)
        edges.append((ends, path))
        number = len(doc['wires']) + 1
        while 'connect-' + str(number) in used_ids:
            number += 1
        wire_id = 'connect-' + str(number)
        used_ids.add(wire_id)
        doc['wires'].append({'id': wire_id, 'start': ends[0], 'end': ends[1]})

    # Validate complete nets, including conflicts through intermediate endpoints.
    parents, members = {}, {}
    def find(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    for ends, path in edges:
        parents[find(physical(ends[0]))] = find(physical(ends[1]))
        for ep in ends:
            members[physical(ep)] = ep
    groups = {}
    for key, ep in members.items():
        groups.setdefault(find(key), []).append(ep)
    for net in groups.values():
        roles = {role(ep) for ep in net}
        signal = roles & {'input', 'output', 'gpio'}
        bad = ('ground' in roles and ('power' in roles or signal) or 'power' in roles and signal
               or sum(role(ep) == 'output' for ep in net) > 1
               or 'input' in roles and not roles & {'gpio', 'output', 'power', 'ground', 'passive'})
        panels = {}
        for ep in net:
            obj, board = objects[ep['componentId']]
            if not board and obj['metadataId'].startswith('epaper-') and role(ep) in ('input', 'output'):
                panels.setdefault(ep['componentId'], set()).add(ep['pinName'])
        bad = bad or any(len(names) > 1 for names in panels.values())
        if bad:
            keys = {physical(ep) for ep in net}
            path = next(path for ends, path in reversed(edges) if physical(ends[0]) in keys)
            valid = '; '.join(instance + '=' + ','.join(p['name'] for p in profiles[instance]) for instance in dict.fromkeys(ep['componentId'] for ep in net))
            invalid(path, [ep['componentId'] + '.' + ep['pinName'] for ep in net], 'compatible roles (ground to ground, power to power, GPIO to signal); valid pins: ' + valid, 'pin_role_conflict')
    return doc
