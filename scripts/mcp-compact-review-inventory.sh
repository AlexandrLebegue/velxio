#!/bin/bash
# Manager-only isolated image. Paths must be observed, never installed/discovered here.
set -euo pipefail
: "${MCP_REVIEW_ISOLATED:?set to 1 only in the isolated review image}"
[ "$MCP_REVIEW_ISOLATED" = 1 ] || exit 2
for key in REVIEW_ROOT REVIEW_APP_ROOT INVENTORY_SCRIPT IDF_ROOT ARDUINO_ROOT GXEPD2_ROOT GFX_ROOT BUSIO_ROOT GCC_PATH CMAKE_PATH NINJA_PATH IDF_PYTHON; do
    value="${!key:-}"
    [[ "$value" = /* ]] || { echo "Explicit absolute path required: $key" >&2; exit 2; }
done
# Canonicalize BEFORE mkdir; require an isolated temporary review directory.
REVIEW_ROOT=$("$IDF_PYTHON" - "$REVIEW_ROOT" <<'PYROOT'
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
if not any(parent in root.parents for parent in (Path('/tmp'), Path('/review'))):
    raise SystemExit('Review root must be below /tmp or /review inside the isolated image')
print(root)
PYROOT
)
[ ! -e "$REVIEW_ROOT/inventory" ] && [ ! -e "$REVIEW_ROOT/inventory-proof.json" ] || {
    echo 'Existing inventory/proof retained; choose a new review root' >&2; exit 2;
}
extra=()
while [ "$#" -gt 0 ]; do
    [ "$1" = --managed ] && [ "$#" -ge 2 ] && [[ "$2" = *=/* ]] || {
        echo 'Only repeated --managed name=/absolute/cache is accepted' >&2; exit 2;
    }
    extra+=(--managed "$2")
    shift 2
done
mkdir -p "$REVIEW_ROOT"
# Activate the installed SDK; never install.sh, index/core/library management.
set +u
. "$IDF_ROOT/export.sh" >&2
set -u
export PYTHONPATH="$REVIEW_APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$IDF_PYTHON" "$INVENTORY_SCRIPT" --output "$REVIEW_ROOT/inventory" \
    --idf "$IDF_ROOT" --arduino "$ARDUINO_ROOT" \
    --library "GxEPD2=$GXEPD2_ROOT" --library "Adafruit GFX Library=$GFX_ROOT" --library "Adafruit BusIO=$BUSIO_ROOT" \
    --executable "gcc=$GCC_PATH" --executable "cmake=$CMAKE_PATH" --executable "ninja=$NINJA_PATH" --executable "python=$IDF_PYTHON" "${extra[@]}" >&2
# Verify the written evidence with the SAME production primitives; emit JSON only.
"$IDF_PYTHON" - "$REVIEW_ROOT/inventory/inventory.json" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
from app.mcp.compact import LibraryInventory, ToolchainInventory
file = Path(sys.argv[1])
with file.open('rb') as stream:
    raw = stream.read(1024 * 1024 + 1)
if len(raw) > 1024 * 1024:
    raise ValueError('Inventory exceeds 1 MiB')
doc = json.loads(raw)
libraries = LibraryInventory(doc['library_root'], doc['libraries'], complete=doc['complete']).verify()
tools = ToolchainInventory(doc['toolchain_root'], doc['toolchains'], complete=doc['complete']).verify()
proof = {'kind':'real-local-inventory', 'pid':os.getpid(), 'inventory_path':str(file),
    'inventory_sha256':hashlib.sha256(raw).hexdigest(), 'libraries':libraries, 'toolchains':tools,
    'compiler_executed':False, 'installation_attempted':False, 'transitive_closure_proven':False}
out = file.parent.parent / 'inventory-proof.json'
with out.open('x') as stream:
    stream.write(json.dumps(proof, sort_keys=True, indent=2) + '\n'); stream.flush(); os.fsync(stream.fileno())
print(json.dumps(proof, sort_keys=True))
PY
