#!/usr/bin/env python3
"""Prepare ONLY local reviewed context + Docker create spec; never calls Docker/network."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
FILES = ['app/main.py', 'app/api/routes/compile.py', 'app/services/espidf_compiler.py',
         'app/services/espidf_offline.py', 'app/services/arduino_cli.py']


def prepare(inspected, preimages, output, derived_image):
    if len(inspected) != 1:
        raise ValueError('Exactly one inspected container required')
    doc = inspected[0]; host = doc['HostConfig']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', doc['Image']):
        raise ValueError('Base must be an immutable local image ID')
    if host.get('AutoRemove') or host.get('VolumesFrom'):
        raise ValueError('AutoRemove/VolumesFrom requires explicit backup/mount review')
    if host['NetworkMode'] != 'bridge':
        raise ValueError('Only inspected bridge supported; no guessed networking')
    ports = host['PortBindings']
    if {p['HostPort'] for p in ports.get('80/tcp', [])} != {'3080'} or {p['HostPort'] for p in ports.get('8002/tcp', [])} != {'8002'}:
        raise ValueError('Expected inspected 80->3080 and 8002->8002 bindings')
    reviewed = json.loads((ROOT / 'packaging/mcp-compact/reviewed-base.json').read_bytes())
    required = set(reviewed) | {'/etc/nginx/conf.d/default.conf', '/app/entrypoint.sh'}
    if set(preimages) != required:
        raise ValueError('Exact inspected preimages required, including all template files')
    for path, expected in reviewed.items():
        if preimages[path] != expected:
            raise ValueError('Base has unreviewed differences; preserve/port its fixes before overlay: ' + path)
    if not doc.get('Mounts'):
        raise ValueError('Inspected mounts required; never invent data volume')
    protected = ('/app/app', '/opt/velxio-mcp-source', '/app/mcp-compact-scripts',
                 '/app/mcp-compact-entrypoint.sh', '/etc/nginx/conf.d/mcp-compact.conf')
    for mount in doc['Mounts']:
        destination = mount['Destination'].rstrip('/') or '/'
        if any(destination == p or destination == '/' or destination.startswith(p + '/') or p.startswith(destination + '/') for p in protected):
            raise ValueError('Mount hides overlay; explicit manager mapping required')
    host = copy.deepcopy(host)
    represented = {entry.split(':')[1] for entry in (host.get('Binds') or [])}
    represented |= {entry['Target'] for entry in (host.get('Mounts') or [])}
    represented |= set(host.get('Tmpfs') or {})
    # Image-declared anonymous volumes otherwise become NEW empty volumes.
    # Materialize their actual inspected name, without copying/purging data.
    for mount in doc['Mounts']:
        if mount['Destination'] in represented:
            continue
        if mount['Type'] != 'volume' or not mount.get('Name'):
            raise ValueError('Unrepresented non-volume mount requires explicit review')
        if host.get('Mounts') is None:
            host['Mounts'] = []
        host['Mounts'].append({'Type': 'volume', 'Source': mount['Name'],
            'Target': mount['Destination'], 'ReadOnly': not mount['RW'], 'VolumeOptions': {'NoCopy': True}})
    out = Path(output)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ('Dockerfile', 'entrypoint.sh', 'nginx-mcp.conf', 'verify_base.py', 'reviewed-base.json'):
        shutil.copyfile(ROOT / 'packaging/mcp-compact' / name, out / name)
    (out / 'base-preimages.json').write_text(json.dumps(preimages, sort_keys=True, indent=2) + '\n')
    for relative in FILES:
        dest = out / 'payload' / relative; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'backend' / relative, dest)
    shutil.copytree(ROOT / 'backend/app/mcp/compact', out / 'payload/app/mcp/compact', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'backend/app/services/esp-idf-template', out / 'payload/app/services/esp-idf-template')
    # Minimal exact policy snapshot, independent from /app/app runtime layout.
    policy = out / 'payload/source/backend/app/services'; policy.mkdir(parents=True)
    for name in ('espidf_compiler.py', 'arduino_cli.py'):
        shutil.copyfile(ROOT / 'backend/app/services' / name, policy / name)
    shutil.copytree(ROOT / 'backend/app/services/esp-idf-template', policy / 'esp-idf-template')
    scripts = out / 'payload/scripts'; scripts.mkdir()
    shutil.copyfile(ROOT / 'scripts/mcp-compact-inventory.py', scripts / 'mcp-compact-inventory.py')
    config = copy.deepcopy(doc['Config'])
    # Config is container-create Config, not read-only inspect container fields.
    config['Image'] = derived_image
    config['Entrypoint'] = ['/app/mcp-compact-entrypoint.sh']; config['Cmd'] = []
    environment = dict(item.split('=', 1) for item in config.get('Env', []))
    environment['MCP_COMPACT_SOURCE_ROOT'] = '/opt/velxio-mcp-source'
    config['Env'] = [k + '=' + v for k, v in sorted(environment.items())]
    config.setdefault('ExposedPorts', {})['8002/tcp'] = {}
    config['HostConfig'] = copy.deepcopy(host)
    (out / 'create.json').write_text(json.dumps(config, sort_keys=True, indent=2) + '\n')
    manifest = {'base_image': doc['Image'], 'derived_image': derived_image, 'original_name': doc['Name'],
        'port_bindings': ports, 'mounts': doc['Mounts'], 'host_config_preserved': host == doc['HostConfig'], 'anonymous_volumes_reused_by_name': True,
        'base_preimages': preimages, 'files': {}}
    for path in sorted(out.rglob('*')):
        if path.is_file(): manifest['files'][str(path.relative_to(out))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inspect', required=True); p.add_argument('--preimages', required=True)
    p.add_argument('--output', required=True); p.add_argument('--image', required=True)
    args = p.parse_args()
    result = prepare(json.loads(Path(args.inspect).read_bytes()), json.loads(Path(args.preimages).read_bytes()), args.output, args.image)
    print(json.dumps({'base_image': result['base_image'], 'files': len(result['files']), 'deployed': False}))
