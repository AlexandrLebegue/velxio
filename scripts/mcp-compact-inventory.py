#!/usr/bin/env python3
"""Manager-only deterministic local evidence. No imports of services or SDK commands."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
sys.path.insert(0, '/app' if Path('/app/app').is_dir() else str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.espidf_offline import digest, tree_manifest


def collect(output, idf, arduino, libraries, managed=(), board='esp32:esp32:esp32', executables=()):
    output = Path(output).absolute()
    idf, arduino = Path(idf).absolute(), Path(arduino).absolute()
    required = {'GxEPD2', 'Adafruit GFX Library', 'Adafruit BusIO'}
    if len(libraries) != 3 or {name for name, _ in libraries} != required:
        raise ValueError('Exactly GxEPD2, Adafruit GFX Library and Adafruit BusIO caches are required')
    # Pin files as they exist at runtime. '/' is the common proof root; every
    # member is relative and verified by the store's no-follow primitives.
    members = []
    def member(path):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('Proof path must be absolute')
        # Verify parents and file with no-follow before reading bounded bytes.
        from app.mcp.compact.builds import proof_bytes
        raw = proof_bytes('/', path.as_posix().lstrip('/'))
        members.append({'path': path.as_posix().lstrip('/'), 'sha256': hashlib.sha256(raw).hexdigest()})
        return raw
    if len(executables) != 4 or {name for name, _ in executables} != {'gcc', 'cmake', 'ninja', 'python'}:
        raise ValueError('Explicit local gcc/cmake/ninja/python executable paths required')
    for name, path in sorted(executables):
        member(Path(path).resolve(strict=True))
    member(idf / 'tools/idf.py'); member(idf / 'tools/cmake/project.cmake'); member(arduino / 'CMakeLists.txt')
    if (idf / 'version.txt').is_file():
        version = member(idf / 'version.txt').decode().strip()
    else:
        version_source = member(idf / 'tools/cmake/version.cmake').decode()
        version = '.'.join(re.search(r'set\(IDF_VERSION_' + field + r'\s+\"?([0-9]+)', version_source)[1] for field in ('MAJOR', 'MINOR', 'PATCH'))
    # Caches are real trees, not package names or promised installations.
    library_entries = {}
    for name, path in sorted(libraries):
        path = Path(path).absolute()
        manifest = tree_manifest(path)
        raw = member(path / 'library.properties')
        props = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line and not line.startswith('#'))
        if props.get('name', '').strip() != name or not props.get('version', '').strip():
            raise ValueError('Cached library identity/version mismatch: ' + name)
        library_entries[name] = {'path': str(path / 'library.properties').lstrip('/'),
            'sha256': hashlib.sha256(raw).hexdigest(), 'source_root': str(path), 'tree_sha256': digest(manifest)}
    managed_entries = []
    for name, path in sorted(managed):
        path = Path(path).absolute()
        managed_entries.append({'name': name, 'source_root': str(path), 'tree_sha256': digest(tree_manifest(path))})
    output.mkdir(parents=True, exist_ok=True)
    tools = {}
    for language in ('arduino', 'espidf'):
        key = board + '|' + language
        doc = {'kind': 'toolchain', 'name': key, 'version': version, 'test_only': False,
            'idf_root': str(idf), 'arduino_root': str(arduino), 'members': members, 'managed_components': managed_entries}
        raw = (json.dumps(doc, sort_keys=True, separators=(',', ':')) + '\n').encode()
        name = 'toolchain-' + language + '.json'
        (output / name).write_bytes(raw)
        tools[key] = {'path': str(output / name).lstrip('/'), 'sha256': hashlib.sha256(raw).hexdigest()}
    result = {'schema_version': 1, 'complete': True, 'library_root': '/', 'toolchain_root': '/',
        'libraries': library_entries, 'toolchains': tools, 'scope': 'explicit declared caches only; transitive closure unproven'}
    (output / 'inventory.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def pair(value):
    name, sep, path = value.partition('=')
    if not sep or not name or not Path(path).is_absolute():
        raise argparse.ArgumentTypeError('Expected name=/absolute/local/cache')
    return name, path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--idf', required=True)
    parser.add_argument('--arduino', required=True)
    parser.add_argument('--library', type=pair, action='append', required=True)
    parser.add_argument('--managed', type=pair, action='append', default=[])
    parser.add_argument('--executable', type=pair, action='append', required=True)
    parser.add_argument('--board', default='esp32:esp32:esp32')
    args = parser.parse_args()
    collect(args.output, args.idf, args.arduino, args.library, args.managed, args.board, args.executable)
    print('Local evidence written; no compile/install/download; transitive closure unproven')
