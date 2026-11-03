#!/bin/bash
# Manager ONLY. Default --dry-run; --execute authorizes the selected operation.
# Usage: ... --create-json /absolute/context/create.json --expected-image-id sha256:...
#            --evidence-dir /absolute/new-proof-dir [--execute] [--rollback]
# Latest manager rollback instruction restores the original container/entrypoint;
# its known legacy startup can attempt setup. No installer/bypass is added here.
set -euo pipefail
set -E
EXECUTE=0
MODE_SEEN=''
ACTION=cutover
BACKUP=/root/velxio-compact-20261103
CREATE=''
EXPECTED=''
EVIDENCE=''
HEALTH_SECONDS=120
PROD=velxio
BEFORE=velxio-before-20261103b
FAILED=velxio-failed-20261103b
UNIT=velxio-mcp.service
TARGET=velxio:compact-20261103b
STARTED=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --execute|--dry-run)
            [ -z "$MODE_SEEN" ] || { echo 'Choose one execution mode' >&2; exit 2; }
            MODE_SEEN=$1; [ "$1" != --execute ] || EXECUTE=1; shift;;
        --rollback) ACTION=rollback; shift;;
        --create-json|--expected-image-id|--evidence-dir|--backup-dir|--health-seconds)
            [ "$#" -ge 2 ] || exit 2
            case "$1" in
                --create-json) CREATE=$2;; --expected-image-id) EXPECTED=$2;;
                --evidence-dir) EVIDENCE=$2;; --backup-dir) BACKUP=$2;;
                --health-seconds) HEALTH_SECONDS=$2;;
            esac; shift 2;;
        --help) sed -n '2,5p' "$0"; exit 0;;
        *) echo "Unknown argument: $1" >&2; exit 2;;
    esac
done
[[ "$EXPECTED" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Full expected image ID required' >&2; exit 2; }
[[ "$CREATE" = /* && "$BACKUP" = /* && "$EVIDENCE" = /* ]] || { echo 'Absolute input/evidence paths required' >&2; exit 2; }
[[ "$HEALTH_SECONDS" =~ ^[0-9]+$ ]] && ((HEALTH_SECONDS >= 1 && HEALTH_SECONDS <= 300)) || exit 2
for tool in docker systemctl python3 curl tee flock sha256sum; do command -v "$tool" >/dev/null; done
[ ! -e "$EVIDENCE" ] || { echo 'Evidence directory already exists; preserved' >&2; exit 2; }
umask 077
mkdir -m 700 "$EVIDENCE"
exec > >(tee -a "$EVIDENCE/journal.log") 2>&1
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
mutate() {
    ((EXECUTE == 1)) || { log 'Refused mutation without --execute'; return 2; }
    { printf '%s COMMAND' "$(date -u +%FT%TZ)"; printf ' %q' "$@"; printf '\n'; } >&2
    "$@"
}
if ((EXECUTE)); then
    ((EUID == 0)) || { log 'Execution requires root'; exit 2; }
    exec 9>/run/lock/velxio-mcp-cutover-20261103b.lock
    flock -n 9 || { log 'Another cutover/rollback owns the lock'; exit 2; }
fi
log "MODE=$([ "$EXECUTE" = 1 ] && echo --execute || echo --dry-run) ACTION=$ACTION"
sha256sum "$0" > "$EVIDENCE/script-sha256.txt"
for name in container-inspect.json wrapper was-active was-enabled; do
    [ -s "$BACKUP/$name" ] && [ ! -L "$BACKUP/$name" ] || { log "Missing/unsafe backup: $name"; exit 2; }
done
[ -s "$CREATE" ] && [ ! -L "$CREATE" ] || exit 2
cp "$CREATE" "$EVIDENCE/input-create.json"
sha256sum "$BACKUP/container-inspect.json" "$BACKUP/wrapper" "$CREATE" > "$EVIDENCE/input-sha256.txt"
systemctl show --property=ExecStart --value "$UNIT" > "$EVIDENCE/exec-start.txt"
systemctl is-active "$UNIT" > "$EVIDENCE/unit-active.txt" || true
systemctl is-enabled "$UNIT" > "$EVIDENCE/unit-enabled.txt" || true
docker container ls --all --format '{{.Names}}' > "$EVIDENCE/container-names.txt"
if [ "$ACTION" = cutover ]; then
    docker container inspect "$PROD" > "$EVIDENCE/original-live.json"
else
    docker container inspect "$BEFORE" > "$EVIDENCE/original-live.json"
fi
docker image inspect "$TARGET" > "$EVIDENCE/target-image.json"
python3 - "$BACKUP" "$EVIDENCE" "$EXPECTED" "$ACTION" <<'PY'
import copy, json, re, sys
from pathlib import Path
backup, evidence, expected_image, action = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
def require(ok, message):
    if not ok: raise SystemExit('PREFLIGHT REFUSED: ' + message)
old_rows = json.loads((backup/'container-inspect.json').read_bytes())
live_rows = json.loads((evidence/'original-live.json').read_bytes())
require(len(old_rows) == len(live_rows) == 1, 'Single original container required')
old, live = old_rows[0], live_rows[0]
require(old['Name'] == '/velxio', 'Original name differs')
require(old['Image'].startswith('sha256:11c7b4bd'), 'Unexpected original production image')
require('ghcr.io/' in old['Config']['Image'] and 'master' in old['Config']['Image'], 'Original ghcr master reference differs')
require(live['Id'] == old['Id'] and live['Image'] == old['Image'], 'Original container/image identity differs from backup')
if action == 'cutover': require(live['State']['Running'], 'Production container is not running')
require((backup/'was-active').read_text().strip() == 'active', 'Saved wrapper state must be active')
require((backup/'was-enabled').read_text().strip() == 'enabled', 'Saved wrapper state must be enabled')
paths = re.findall(r'path=([^ ;}]+)', (evidence/'exec-start.txt').read_text())
require(paths == ['/usr/local/bin/velxio-mcp'], 'Wrapper ExecStart differs')
if action == 'cutover':
    require((evidence/'unit-active.txt').read_text().strip() == 'active', 'Wrapper not active')
    require((evidence/'unit-enabled.txt').read_text().strip() == 'enabled', 'Wrapper not enabled')
names = set((evidence/'container-names.txt').read_text().splitlines())
require('velxio-failed-20261103b' not in names, 'Failed-container evidence name already occupied')
require(('velxio-before-20261103b' not in names) if action == 'cutover' else ('velxio-before-20261103b' in names), 'Backup-container name/state conflict')
images = json.loads((evidence/'target-image.json').read_bytes())
require(len(images) == 1 and images[0]['Id'] == expected_image, 'Target tag does not match exact expected image ID')
spec = json.loads((evidence/'input-create.json').read_bytes())
require(spec['Image'] in ('velxio:compact-20261103b', expected_image), 'create.json selects a different image')
require(spec.get('Entrypoint') == ['/app/mcp-compact-entrypoint.sh'] and spec.get('Cmd') == [], 'Unexpected new entrypoint/command')
host = copy.deepcopy(old['HostConfig'])
require(host.get('NetworkMode') == 'bridge' and not host.get('AutoRemove') and not host.get('VolumesFrom'), 'Unsupported original HostConfig')
require(set(host['PortBindings']) == {'80/tcp','8002/tcp'}, 'Unexpected original ports')
for key, port in [('80/tcp','3080'), ('8002/tcp','8002')]:
    require({b['HostPort'] for b in host['PortBindings'][key]} == {port}, 'Unexpected host port')
represented = {b.split(':')[1] for b in (host.get('Binds') or [])}
represented |= {m['Target'] for m in (host.get('Mounts') or [])}
represented |= set(host.get('Tmpfs') or {})
require(bool(old['Mounts']), 'Original mounts absent')
for mount in old['Mounts']:
    if mount['Destination'] not in represented:
        require(mount['Type'] == 'volume' and bool(mount.get('Name')), 'Unrepresented non-volume mount')
        if host.get('Mounts') is None: host['Mounts'] = []
        host['Mounts'].append({'Type':'volume','Source':mount['Name'],'Target':mount['Destination'],
                              'ReadOnly':not mount['RW'],'VolumeOptions':{'NoCopy':True}})
require(spec['HostConfig'] == host, 'HostConfig/HostIp/binds/volumes differ from original')
require(sorted(live['Mounts'], key=lambda mount: mount['Destination']) ==
        sorted(old['Mounts'], key=lambda mount: mount['Destination']),
        'Original actual mounts changed since backup')
spec['Image'] = expected_image  # Freeze creation against tag changes after preflight.
(evidence/'pinned-create.json').write_text(json.dumps(spec, sort_keys=True, indent=2)+'\n')
(evidence/'original-id.txt').write_text(old['Id']+'\n')
print(json.dumps({'preflight':'verified','action':action,'target':expected_image,
                  'port_bindings':host['PortBindings'],'mount_count':len(old['Mounts'])}))
PY
if ((EXECUTE == 0)); then
    log 'DRY-RUN: no docker/systemctl mutation or HTTP request performed.'
    log 'PLAN: stop+disable wrapper; stop/rename original; create pinned replacement; start; verify; rollback on failure.'
    [ "$ACTION" != rollback ] || log 'PLAN: preserve failed replacement; restore original name/container and saved wrapper state; verify legacy endpoints.'
    exit 0
fi
inspect_names() { docker container ls --all --format '{{.Names}}'; }
check_new_mounts() {
    docker container inspect "$PROD" > "$EVIDENCE/new-inspect.json" || return
    python3 - "$BACKUP/container-inspect.json" "$EVIDENCE/new-inspect.json" "$EXPECTED" <<'PY'
import json, sys
old, new = (json.load(open(p))[0] for p in sys.argv[1:3])
def mounts(doc):
    return sorted((m['Type'],m.get('Name') if m['Type']=='volume' else m['Source'],m['Destination'],m['RW'],m.get('Propagation','')) for m in doc['Mounts'])
if new['Image'] != sys.argv[3] or mounts(old) != mounts(new) or old['HostConfig']['PortBindings'] != new['HostConfig']['PortBindings']:
    raise SystemExit('New image/actual mounts/HostIp/port bindings do not match the approved state')
PY
}
verify_http() {
    local kind=$1
    python3 - "$EVIDENCE" "$kind" "$HEALTH_SECONDS" <<'PY'
import http.client, json, sys, time
from pathlib import Path
evidence, kind, seconds = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
expected = {'search_catalog','get_reference','save_project','check_project','build_project','read_artifact'}
def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    connection.request(method,path,body=body,headers=headers or {})
    return connection, connection.getresponse()
def payload(response):
    if 'text/event-stream' not in response.getheader('Content-Type',''):
        raw = response.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('HTTP response quota')
        return json.loads(raw)
    total, data = 0, []
    while total<=1024*1024:
        line = response.readline(65537); total += len(line)
        if not line or len(line)>65536: raise ValueError('Missing/bounded SSE response')
        if line.startswith(b'data:'): data.append(line[5:].strip())
        if line.strip()==b'' and data: return json.loads(b'\n'.join(data))
    raise ValueError('SSE response quota')
deadline = time.monotonic()+seconds
attempt = 0
while True:
    attempt += 1
    try:
        for path, filename in [('/health','health.json'),('/','ui.html')]:
            connection,response=request(3080,'GET',path)
            try:
                if response.status!=200: raise ValueError('UI/health status '+str(response.status))
                raw=response.read(1024*1024+1)
                if len(raw)>1024*1024: raise ValueError('UI response quota')
                (evidence/(kind+'-'+filename)).write_bytes(raw)
            finally: connection.close()
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        def rpc(method, params, number=None):
            body={'jsonrpc':'2.0','method':method,'params':params}
            if number is not None: body['id']=number
            connection,response=request(8002,'POST','/mcp',json.dumps(body),headers)
            try:
                if response.status not in ([200] if number is not None else [200,202,204]): raise ValueError('MCP HTTP '+str(response.status))
                if response.getheader('Mcp-Session-Id'): headers['Mcp-Session-Id']=response.getheader('Mcp-Session-Id')
                if number is None: return None
                result=payload(response)
                if result.get('error') or 'result' not in result: raise ValueError('JSON-RPC error '+str(result)[:500])
                (evidence/(kind+'-'+str(number)+'.json')).write_text(json.dumps(result,sort_keys=True)+'\n')
                return result['result']
            finally: connection.close()
        initialized=rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'manager-cutover-check','version':'20261103b'}},1)
        headers['MCP-Protocol-Version']=initialized['protocolVersion']
        rpc('notifications/initialized',{})
        tools=rpc('tools/list',{},2)['tools']; names={tool['name'] for tool in tools}
        if kind=='compact' and (names!=expected or len(tools)!=6): raise ValueError('Expected exactly six compact tools')
        if kind=='legacy' and not tools: raise ValueError('Legacy wrapper tools missing')
        print(json.dumps({'verification':kind,'ui_port':3080,'mcp_port':8002,'tools':sorted(names),'attempt':attempt}))
        break
    except Exception as error:
        print(json.dumps({'verification':kind,'attempt':attempt,'error':str(error)[:500]}),flush=True)
        if time.monotonic()>=deadline: raise SystemExit('Health/MCP verification deadline expired')
        time.sleep(min(2,max(0,deadline-time.monotonic())))
PY
}
rollback() {
    log 'ROLLBACK: restore original container; all replacement/evidence containers retained.'
    local names image old_id
    names=$(inspect_names) || return
    old_id=$(cat "$EVIDENCE/original-id.txt")
    if printf '%s\n' "$names" | python3 -c 'import sys;sys.exit(0 if "velxio-before-20261103b" in sys.stdin.read().splitlines() else 1)'; then
        if printf '%s\n' "$names" | python3 -c 'import sys;sys.exit(0 if "velxio" in sys.stdin.read().splitlines() else 1)'; then
            image=$(docker container inspect --format '{{.Image}}' "$PROD") || return
            [ "$image" = "$EXPECTED" ] || { log 'Refuse to stop an unexpected replacement'; return 1; }
            mutate docker stop --time 30 "$PROD" || return
            mutate docker rename "$PROD" "$FAILED" || return
        fi
        mutate docker rename "$BEFORE" "$PROD" || return
    fi
    [ "$(docker container inspect --format '{{.Id}}' "$PROD")" = "$old_id" ] || { log 'Original container identity not restored'; return 1; }
    mutate docker start "$PROD" || return
    mutate systemctl enable "$UNIT" || return
    mutate systemctl start "$UNIT" || return
    systemctl is-enabled "$UNIT" > "$EVIDENCE/restored-unit-enabled.txt" || return
    systemctl is-active "$UNIT" > "$EVIDENCE/restored-unit-active.txt" || return
    verify_http legacy || return
    docker container inspect "$PROD" > "$EVIDENCE/restored-inspect.json" || return
    log 'ROLLBACK VERIFIED: original container running, wrapper restored active+enabled.'
}
on_error() {
    local result=$?
    trap - ERR
    log "FAILED status=$result; preserving evidence and containers."
    if ((STARTED)) && [ "$ACTION" = cutover ]; then
        if rollback; then log 'Automatic rollback succeeded; cutover still reported failed.'
        else log 'ROLLBACK FAILED: manual manager intervention required; nothing removed.'; fi
    fi
    exit "$result"
}
trap on_error ERR
trap 'false' INT TERM
if [ "$ACTION" = rollback ]; then
    rollback
    exit 0
fi
STARTED=1
mutate systemctl stop "$UNIT"
mutate systemctl disable "$UNIT"
mutate docker stop --time 30 "$PROD"
mutate docker rename "$PROD" "$BEFORE"
API_VERSION=$(docker version --format '{{.Server.APIVersion}}')
[[ "$API_VERSION" =~ ^[0-9]+\.[0-9]+$ ]]
mutate curl --fail --silent --show-error --max-time 30 --unix-socket /var/run/docker.sock \
    -H 'Content-Type: application/json' --data-binary @"$EVIDENCE/pinned-create.json" \
    "http://localhost/v$API_VERSION/containers/create?name=$PROD" > "$EVIDENCE/create-result.json"
mutate docker start "$PROD"
check_new_mounts
verify_http compact
systemctl is-active "$UNIT" > "$EVIDENCE/unit-after.txt" || true
systemctl is-enabled "$UNIT" > "$EVIDENCE/unit-after-enabled.txt" || true
[ "$(cat "$EVIDENCE/unit-after.txt")" = inactive ]
[ "$(cat "$EVIDENCE/unit-after-enabled.txt")" = disabled ]
log 'CUTOVER VERIFIED: six compact tools and UI/health respond; legacy wrapper remains disabled.'
