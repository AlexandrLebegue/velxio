"""Opt-in pinned AVR compilation inside the genuine REST owner's admission lane.

Executes only compile on an installed arduino:avr core. No core/lib management,
ESP32 fallback, upload or claim of OS network isolation. Trusted local platform
recipes are an explicit prerequisite; hook recipes are refused.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import tempfile

from .projects import fail, filename


def digest_file(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
        fail('preflight_unknown', 'AVR evidence paths must be canonical regular files')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


async def compile_avr(payload, log):
    if os.environ.get('MCP_COMPACT_AVR_ENABLED') != '1':
        fail('unsupported', 'Pinned local AVR compilation is not enabled by the application owner')
    if not payload['board_fqbn'].startswith('arduino:avr:') or payload['language'] != 'arduino':
        fail('unsupported', 'Installed arduino:avr Arduino targets only; ESP32 retains its IDF lane')
    evidence = payload['toolchain']
    avr = evidence.get('avr')
    if not isinstance(avr, dict):
        fail('toolchain_unknown', 'AVR requires an installed compiler/cache inventory')
    for path, digest in [(avr['cli'], avr['cli_sha256']),
                         (avr['platform'], avr['platform_sha256']), (avr['boards'], avr['boards_sha256'])]:
        if digest_file(path) != digest:
            fail('toolchain_unknown', 'Pinned AVR compiler or platform changed')
    if 'recipe.hooks.' in Path(avr['platform']).read_text():
        fail('unsupported', 'AVR platforms containing build hooks require a separate review')
    from app.services.espidf_offline import digest, tree_manifest
    if digest(tree_manifest(Path(avr['core_root']))) != avr['core_tree_sha256']:
        fail('toolchain_unknown', 'Pinned AVR core tree changed')
    # Expose exactly the verified declared libraries plus their inventoried
    # transitive dependencies. No sketchbook scan or automatic installation.
    proofs = payload.get('library_proofs', {})
    needed = set(proofs)
    pending = list(needed)
    entries = avr['libraries']
    while pending:
        name = pending.pop()
        if name not in entries:
            fail('dependencies_unknown', 'Declared library lacks installed AVR source evidence: ' + name)
        for dependency in entries[name].get('dependencies', []):
            if dependency not in needed:
                needed.add(dependency)
                pending.append(dependency)
    for name in needed:
        entry = entries[name]
        if digest(tree_manifest(Path(entry['source_root']))) != entry['tree_sha256']:
            fail('dependencies_unknown', 'Installed library tree changed: ' + name)
    with tempfile.TemporaryDirectory(prefix='compact-avr-') as temporary:
        root = Path(temporary)
        sketch = root / 'sketch'
        sketch.mkdir()
        files = payload['files']
        primary = next((f for f in files if f['name'] == 'sketch.ino'), next((f for f in files if f['name'].endswith('.ino')), None))
        if primary is None:
            fail('project_invalid', 'AVR requires a primary .ino source')
        for file in files:
            name = 'sketch.ino' if file is primary else file['name']
            filename(name)
            path = sketch / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file['content'].encode('utf-8'))
        user = root / 'user'
        libraries = user / 'libraries'
        libraries.mkdir(parents=True)
        for index, name in enumerate(sorted(needed)):
            (libraries / ('lib' + str(index))).symlink_to(entries[name]['source_root'], target_is_directory=True)
        env = {**os.environ, 'ARDUINO_DIRECTORIES_DATA': avr['data_root'],
               'ARDUINO_DIRECTORIES_DOWNLOADS': str(root / 'downloads'), 'ARDUINO_DIRECTORIES_USER': str(user)}
        build = root / 'build'
        process = await asyncio.create_subprocess_exec(avr['cli'], 'compile', '--fqbn', payload['board_fqbn'],
            '--build-path', str(build), str(sketch), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=240)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        log(output.decode('utf-8', 'replace'))
        firmware = build / 'sketch.ino.hex'
        if process.returncode or not firmware.is_file():
            return {'success': False, 'error_kind': 'compile_error'}
        return {'success': True, 'firmware': firmware.read_bytes(), 'firmware_type': 'hex'}
