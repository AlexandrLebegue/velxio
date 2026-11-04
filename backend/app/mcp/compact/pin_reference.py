"""Packaged real web-component pins; native endpoint names, no connection DSL."""
import hashlib
import json
from pathlib import Path


def enrich(entries, revision, inputs=()):
    source = Path(__file__).with_name('pins.snapshot.json')
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if source.with_suffix('.json.sha256').read_text().strip() != digest:
        raise ValueError('Pin reference manifest differs')
    document = json.loads(raw)
    recorded = next(s['sha256'] for s in document['sources'] if s['path']=='frontend/public/components-metadata.json')
    actual = next((s['sha256'] for s in inputs if s['path']=='frontend/public/components-metadata.json'),None)
    if actual != recorded:
        return revision
    records = document['entries']
    for key, entry in entries.items():
        if entry.get('pins') != 'unknown' or key not in records:
            continue
        entry['pins'] = records[key]['pins']
        entry['_pin_aliases'] = records[key]['aliases']
        entry['_pin_variants'] = records[key].get('variants',{})
        entry['limitations'] = [line for line in entry['limitations'] if 'pinCount' not in line and 'Unextracted pin' not in line]
        entry['limitations'].append('Native pad names extracted from the installed web component; electrical behavior remains unverified.')
        entry['sources'] = [*entry['sources'], {'path':'backend/app/mcp/compact/pins.snapshot.json','line':1,'sha256':digest}]
    return hashlib.sha256((revision + '|pins:' + digest).encode()).hexdigest()
