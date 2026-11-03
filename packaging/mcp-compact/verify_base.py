"""Fail before overlay if inspected compiler/UI-serving sources differ."""
import hashlib
import json
from pathlib import Path
reviewed = json.loads(Path('/opt/mcp-reviewed-base.json').read_bytes())
required = set(reviewed) | {'/etc/nginx/conf.d/default.conf', '/app/entrypoint.sh'}
doc = json.loads(Path('/opt/mcp-base-preimages.json').read_bytes())
if set(doc) != required:
    raise SystemExit('Exact reviewed base preimages required; inspect and review differences first')
for path, expected in reviewed.items():
    if doc[path] != expected:
        raise SystemExit('Unreviewed base correction would be overwritten: ' + path)
for path, digest in doc.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise SystemExit('Base preimage changed: ' + path)
# Hash equality binds the inspected base; manager must still review its diff
# against payload before replacing a service (preserve local compiler fixes).
