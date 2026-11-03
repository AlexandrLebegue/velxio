#!/usr/bin/env python3
"""Local pinned SDK/library evidence for manager and startup; never runs SDK commands."""
import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import sys
sys.path.insert(0, '/app' if Path('/app/app').is_dir() else str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.espidf_offline import digest, tree_manifest


def collect(output, idf, arduino, libraries, managed=(), board='esp32:esp32:esp32', executables=(), *, complete=True):
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
    result = {'schema_version': 1, 'complete': complete, 'library_root': '/', 'toolchain_root': '/',
        'libraries': library_entries, 'toolchains': tools, 'scope': 'explicit declared caches only; transitive closure unproven'}
    (output / 'inventory.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def startup(output):
    """Pin the real ESP32 service's selected local inputs before ASGI starts.

    Import only the IDF service (local path discovery), never ArduinoCLI/routes.
    The compile/admission APIs are not called. This is a three-library subset,
    so complete=False keeps every unlisted dependency unknown.
    """
    from app.services.espidf_compiler import espidf_compiler as service
    from app.mcp.compact import LibraryInventory, ToolchainInventory
    target = service._idf_target('esp32:esp32:esp32')
    arduino_mode = service._arduino_supports_target(target)
    if not service.available or not arduino_mode:
        raise ValueError('Local ESP32 IDF/Arduino component unavailable; no setup attempted')
    use_idf5 = service._use_idf5(target, arduino_mode)
    idf = Path(service._idf_root(use_idf5))
    arduino = Path(service._arduino_path_for(use_idf5))
    if idf != idf.resolve(strict=True) or arduino != arduino.resolve(strict=True):
        raise ValueError('Selected SDK roots must be canonical no-link paths')
    library_root = service._find_arduino_libraries_dir()
    if library_root is None:
        raise ValueError('Local library volume unavailable; no installation attempted')
    libraries = [(name, Path(library_root) / folder) for name, folder in (
        ('GxEPD2', 'GxEPD2'), ('Adafruit GFX Library', 'Adafruit_GFX_Library'),
        ('Adafruit BusIO', 'Adafruit_BusIO'))]
    build_env = service._build_env(target, use_idf5=use_idf5, arduino_mode=True)
    executables = []
    for label, command in [('gcc','xtensa-esp32-elf-gcc'), ('cmake','cmake'),
                           ('ninja','ninja'), ('python','python')]:
        path = shutil.which(command, path=build_env['PATH'])
        if path is None:
            raise ValueError('Local selected executable missing: ' + command)
        executables.append((label, path))
    doc = collect(output, idf, arduino, libraries, executables=executables, complete=False)
    LibraryInventory(doc['library_root'], doc['libraries'], complete=False).verify()
    ToolchainInventory(doc['toolchain_root'], doc['toolchains'], complete=False).verify()
    return doc


def pair(value):
    name, sep, path = value.partition('=')
    if not sep or not name or not Path(path).is_absolute():
        raise argparse.ArgumentTypeError('Expected name=/absolute/local/cache')
    return name, path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--startup', action='store_true', help='Discover verified local inputs from the real ESP32 service; no compile/install')
    parser.add_argument('--idf')
    parser.add_argument('--arduino')
    parser.add_argument('--library', type=pair, action='append')
    parser.add_argument('--managed', type=pair, action='append', default=[])
    parser.add_argument('--executable', type=pair, action='append')
    parser.add_argument('--board', default='esp32:esp32:esp32')
    args = parser.parse_args()
    if args.startup:
        if args.idf or args.arduino or args.library or args.executable or args.managed or args.board != 'esp32:esp32:esp32':
            parser.error('--startup uses only the real service selection; explicit overrides are not accepted')
        doc = startup(args.output)
        print(json.dumps({'inventory':'verified', 'path':str(Path(args.output) / 'inventory.json'),
                          'libraries':sorted(doc['libraries']), 'complete':doc['complete'],
                          'compile_or_install_attempted':False}, sort_keys=True))
    else:
        if not all((args.idf, args.arduino, args.library, args.executable)):
            parser.error('--idf, --arduino, --library and --executable are required without --startup')
        collect(args.output, args.idf, args.arduino, args.library, args.managed, args.board, args.executable)
        print('Local evidence written; no compile/install/download; transitive closure unproven')
