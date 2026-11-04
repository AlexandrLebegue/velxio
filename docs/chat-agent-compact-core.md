# Four chat tools, with shared project validation

The integrated chat uses OpenCode through the authenticated `/api/agent`
session/message/event routes. Model discovery exposes exactly four Velxio tools.
The external six-tool compact MCP remains unchanged.

| Tool | Purpose |
| --- | --- |
| `search_component` | Search boards/components; return IDs, native pins, defaults and known library names together. |
| `components` | Create/replace the board, batch-add/update/remove parts and declare libraries. Empty arguments read current state. |
| `connect` | Batch native wires or remove wire IDs; preserve other wires and skip exact/reversed duplicates. |
| `run` | Capture files, check, validate/apply, compile and start supported simulation; resume pending work without IDs. |

The conversation selects the project. The model needs no project/version/build
IDs, separate create/save/check/compile calls or starter recipe. Legacy calls
remain accepted for resumed conversations but are absent from discovery and new
system instructions. Shared compact recipes are preserved; no task-specific
recipe is added to the chat.

OpenCode runs in the actual workspace with native read, write, edit, glob, grep
and list tools. Context includes relative source paths and the active file.
Sources remain grouped for multi-board projects. New boards receive only an
empty source skeleton; the model authors the code. Unrelated user code/files
are preserved when editing components or replacing boards.

## Circuit operations

`components` accepts `board`, `add`, `update`, `remove`, `libraries`, and optional
board `pin_map`/`language_mode`. Adds use catalog IDs; updates/removals use mounted
instance IDs. Responses include generated IDs, reference pins and source paths.
A connected editor also supplies actual mounted pinouts for property variants.

`connect` accepts `wires:[{start:{componentId,pinName},end:{componentId,pinName}}]`
and optional `remove:[wire_id]`. No named-wiring command strings are accepted.
Each batch forms one candidate, which passes editor validation and revision
comparison before application. A failed batch publishes no partial circuit.
Removing a component also removes its attached wires. Board swaps preserve IDs
and sources, remapping pins only when explicitly requested.

Editor and agent snapshots now merge automatically against their last common
snapshot. Components/boards/wires are matched by ID, source files by name;
independent edits are combined instead of requiring a reconnect. Idle sync keeps
the latest manual edit on a true overlap and retains the previous agent draft in
immutable history. An active overlapping tool edit returns precise edit_conflict
paths; the agent can read current state with components() rather than asking the
user to synchronize. Read-only pin inspection is independent of snapshot age.
Compiler-inferred library updates are acknowledged with the actual final editor
revision. Internal editor callbacks allow bounded project snapshots up to 8 MiB;
the model-facing 24 KiB tool-response budget is unchanged.

Complete JSON strings used for arrays/objects and numeric/boolean strings are
normalized losslessly; incomplete JSON is rejected, not guessed. Errors retain
code/path/received/expected/next_action and refer to the four visible operations.
Search is paginated and component/board-only. Library API extraction is deferred.

## Run truth

`run()` captures file edits and checks the exact current source/circuit with the
shared ProjectChecker. Invalid sketches stop before compilation. The candidate
passes the editor's validation and revision guard. Supported simulation uses the
editor's existing compile/load/execute entry point once, without a second compact
build first. Existing board access rules and engine acknowledgements still apply.

`run(simulate=false)` compiles through the shared BuildService and genuine sealed
REST owner, bound to the original authenticated chat request/user. Inventory,
dependency and toolchain admission are preserved; nothing is installed. ESP32
uses this offline build path even for default `run()`, with simulation explicitly
unsupported. Native ESP32 board/pin/template/IDF paths remain available. This
change makes no real ESP32 build or runtime claim.

`wait_seconds` defaults to 20, maximum 60, for compilation-only work. A pending
build stays server-side; another `run()` follows that job without an ID or a new
compilation. Pending editor startup is observed rather than restarted.
`action=status` reads progress, `stop` stops simulation, and `restart` explicitly
restarts execution except that a live build is always resumed first. Stopping
simulation never claims to cancel an already admitted backend compilation.

Results separate compilation, startup confirmation and behavioral verification.
Only `compilation.success=true` for current files proves compilation.
Starting/booting is pending; only `confirmed=true` acknowledges startup. No run
response claims functional correctness. Revision checks reject old results as
evidence about current files. Compiler failures are failed timeline steps.

## Short file paths

Tool titles/summaries show paths such as `group-1/sketch.ino`; the workspace root
alone is `.`. Server presentation removes the exact workspace prefix, including
paths missing their initial slash. The frontend also shortens legacy persisted
agent/session paths and renders `<path>` wrappers as `File: ...`. Actual native
tool arguments/results, model cwd and source contents are unaffected.

## Validation

Deterministic tests cover the real four-tool HTTP transport, atomic edits,
native wiring, source preservation, check-before-run, compiler failures,
pending/resumed jobs, stale results, ESP32 e-paper pins and shortened paths.
Frontend tests cover stream rendering, circuit validation and the shared execution
pipeline. New Qwen performance has not been measured for this four-tool surface;
earlier benchmark reports describe their frozen prior revisions. No model call,
push or deployment is part of this change.

Verified on this change: 63 agent tests, 182 compact MCP tests, 32 frontend
agent tests and four benchmark/provenance tests passed. The Vite production
bundle builds; targeted frontend lint and formatting checks also pass.
