"""Cutover syntax and DRY-RUN only; external commands are strict local stubs.

Never invokes actual Docker/systemctl, HTTP, the backend or a compiler.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts/mcp-compact-cutover-20261103b.sh'


class CutoverScriptTests(unittest.TestCase):
    def test_bash_syntax(self):
        result = subprocess.run(['bash', '-n', str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_explicit_and_rollback_dry_runs_never_mutate_services(self):
        with tempfile.TemporaryDirectory(prefix='compact-cutover-DRY-RUN-') as temporary:
            root = Path(temporary)
            backup = root / 'backup'; backup.mkdir()
            host = {'NetworkMode':'bridge', 'AutoRemove':False, 'VolumesFrom':None,
                    'Binds':['existing-data:/app/data'], 'Mounts':None,
                    'PortBindings':{'80/tcp':[{'HostIp':'','HostPort':'3080'}],
                                    '8002/tcp':[{'HostIp':'','HostPort':'8002'}]}}
            old = {'Id':'c'*64, 'Name':'/velxio', 'Image':'sha256:11c7b4bd'+'0'*56,
                   'State':{'Running':True}, 'Config':{'Image':'ghcr.io/controlled/velxio:master'},
                   'HostConfig':host, 'Mounts':[{'Type':'volume','Name':'existing-data',
                   'Source':'/var/lib/docker/volumes/existing-data/_data','Destination':'/app/data',
                   'RW':True,'Propagation':''}]}
            original = backup / 'container-inspect.json'
            original.write_text(json.dumps([old]))
            for name, value in [('wrapper','#!/bin/sh\n# CONTROLLED BACKUP ONLY\n'),
                                ('was-active','active\n'),('was-enabled','enabled\n')]:
                (backup / name).write_text(value)
            expected = 'sha256:'+'6'*64
            create = root / 'create.json'
            create.write_text(json.dumps({'Image':'velxio:compact-20261103b',
                'Entrypoint':['/app/mcp-compact-entrypoint.sh'],'Cmd':[],'HostConfig':host}))
            stubs = root / 'bin'; stubs.mkdir()
            # Every non-read-only command fails loudly. The CLI argument log
            # independently proves that no mutation was even attempted.
            stub = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name=pathlib.Path(sys.argv[0]).name; args=sys.argv[1:]
with open(os.environ['CALL_LOG'],'a') as out: out.write(json.dumps([name,*args])+'\\n')
if name=='docker' and args[:2]==['container','inspect']:
 print(pathlib.Path(os.environ['ORIGINAL']).read_text())
elif name=='docker' and args[:2]==['container','ls']:
 print('velxio'); print('velxio-before-20261103b' if os.environ['ACTION']=='rollback' else '')
elif name=='docker' and args[:2]==['image','inspect']:
 print(json.dumps([{'Id':os.environ['EXPECTED']}]))
elif name=='systemctl' and args[0]=='show':
 print('{ path=/usr/local/bin/velxio-mcp ; argv[]=/usr/local/bin/velxio-mcp ; }')
elif name=='systemctl' and args[0]=='is-active': print('active')
elif name=='systemctl' and args[0]=='is-enabled': print('enabled')
else:
 print('FORBIDDEN MUTATION OR HTTP: '+str([name,*args]),file=sys.stderr); sys.exit(97)
'''
            for name in ('docker','systemctl','curl'):
                file = stubs / name; file.write_text(stub); file.chmod(0o755)
            for index, mode in enumerate(([], ['--dry-run'], ['--rollback'])):
                with self.subTest(mode=mode):
                    log = root / f'calls-{index}.jsonl'
                    env = {**os.environ, 'PATH':str(stubs)+os.pathsep+os.environ['PATH'],
                           'CALL_LOG':str(log), 'ORIGINAL':str(original), 'EXPECTED':expected,
                           'ACTION':'rollback' if '--rollback' in mode else 'cutover'}
                    result = subprocess.run(['bash', str(SCRIPT), '--backup-dir', str(backup),
                        '--create-json', str(create), '--expected-image-id', expected,
                        '--evidence-dir', str(root / f'evidence-{index}'), *mode],
                        env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn('MODE=--dry-run', result.stdout)
                    self.assertIn('DRY-RUN: no docker/systemctl mutation or HTTP', result.stdout)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertTrue(calls)
                    for call in calls:
                        self.assertTrue((call[0]=='docker' and call[1:3] in
                            [['container','inspect'],['container','ls'],['image','inspect']]) or
                            (call[0]=='systemctl' and call[1] in ['show','is-active','is-enabled']), call)
                    pinned = json.loads((root / f'evidence-{index}/pinned-create.json').read_bytes())
                    self.assertEqual(pinned['Image'], expected)
                    self.assertEqual(pinned['HostConfig'], host)


if __name__ == '__main__':
    unittest.main()
