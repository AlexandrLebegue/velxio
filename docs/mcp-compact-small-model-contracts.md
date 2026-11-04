# Compact MCP: small-model authoring contracts

## Plain sketch text

`save_project(sketch=source, board="arduino-uno")` creates a native Arduino
project without asking the client to construct a JSON document. `board` defaults
to Uno; `libraries` optionally declares dependencies. `sketch` is the actual
source string: normal MCP JSON-RPC serialization still applies once, but there
is no nested JSON document or additional escaping layer.

The server preserves UTF-8 characters, double quotes, literal backslash
sequences, LF/CRLF and trailing newlines exactly. It never unescapes or silently
repairs source. For existing projects use `project_id`, `expected_version`,
`sketch`, and optionally `board_id`; helpers, wiring and other file groups are
preserved. The selected board must already be in Arduino mode. Updates retain
the existing primary `.ino` filename and use compare-and-swap under the store lock.

The response includes `board_id`, `sketch_file` and up to two `warnings` with
`file`, `observed` and `correction`. A single-line sketch with `//` comments or
empty character literals (`''`) is saved unchanged with a warning. Saving is
not validation: `check_project` still rejects unusable code before a build.

```python
source = '''// A real multiline sketch
void setup() {
  Serial.begin(9600);
  Serial.println("Hello, Velxio");
}
void loop() {}
'''
arguments = {"board": "arduino-uno", "sketch": source}
```

The public MCP still exposes exactly six tools: `search_catalog`, `get_reference`,
`save_project`, `check_project`, `build_project`, and `read_artifact`.
The compact catalog now owns the authoring improvements shared with the chat
agent. The agent no longer implements a separate first-keyword search fallback.

## Authoring without guessing native fields

For a component, `get_reference(section="project")` returns
`data.instance_template`, `data.components`, `data.pinNames`, and
`data.example_references`. The template includes `id`, a bare `metadataId`,
`x`, `y`, and the component's authored `properties`. For example:

```json
{
  "id": "epd",
  "metadataId": "epaper-1in54-bw",
  "x": 300,
  "y": 0,
  "properties": {"panelKind": "epaper-1in54-bw", "refreshMs": 50}
}
```

Copy the template, assign a unique instance ID, and append it to the native
document's `components`. Wires reference that instance ID. Reference IDs such
as `component:epaper-1in54-bw` are never native `metadataId` values.

For a board, `data` remains a native document that can be passed directly to
`save_project`. Its board template is also exposed as the response's
`instance_template`, outside `data`, so metadata does not invalidate the saved
document. Uno, Nano, ESP32 and other catalog boards use the same bridge.
Templates establish native structure, not compiler or simulator availability.

Unknown pin lists remain `"unknown"`. Some authored defaults contradict their
declared UI property types. The checker preserves an **exact typed default**,
reports `attribute_default_type_unknown`, and keeps the check `partial`.
Different invalid values still produce errors. This prevents a native template
from being falsely rejected without inventing a stronger type guarantee.

## Tolerant search and library examples

Search first tries the complete normalized phrase. If the entire result set is
empty, it searches the separate words, merges by catalog ID, and ranks by the
number of matching words followed by ID. `query_used` is an array containing the
exact phrase or the fallback terms that matched; `query_original` preserves the request. An empty page of
a successful exact search never triggers expansion.

For `"e-ink epaper 1.54"`, the screen can be discovered in one request.
Pagination happens after merging: `total` counts unique results, `has_more`
describes the next page, and `next_offset` is an integer or `null`. Reuse the
same query and the returned offset rather than repeating a page.

Component overview/project references expose up to eight existing example IDs.
For this screen, the list includes `example:epaper-1in54-uno-hello`; retrieve its
actual source with `get_reference(section="code")`. An example for Uno still
requires pin adaptation for ESP32. Defaults and references never claim that a
library is installed or that a different target has compiled successfully.

## Execution is explicitly unsupported

The six-tool MCP compiles; it does not start an electronic simulator. Board
references advertise `execution.supported=false`. A legacy `run_project` request
returns `unsupported` immediately, without allocating a build job, polling, or
adding a seventh advertised tool. `build_project` remains the separate offline
compiler contract and retains its existing verified-owner prerequisites.

The chat agent also refuses ESP32 `run_project` before browser/build dispatch.
Its OpenCode event collector handles an ESP32 `velxio_run_project` in `pending`
state immediately, even if the provider never completes the empty tool
arguments. This reproduces the previously stalled stage without contacting a
real model. Other board execution paths are unchanged. A provider that produces
no event at all is still subject to the existing overall turn timeout; no MCP
server can answer a request it has never received.

## Deterministic measurements

No real Qwen endpoint, compiler, simulator, service deployment, or dependency
installation is used in this evaluation. The scripted client validates both
input and output schemas and uses the real catalog, store, checker and build
orchestrator with the existing controlled owner adapter pattern.

| Scenario | Tool calls | Unexpected tool errors | Repeated identical calls | Status polls |
| --- | ---: | ---: | ---: | ---: |
| LED / Uno | 5 | 0 | 0 | 0 |
| Servo 45 degrees / Nano | 5 | 0 | 0 | 0 |
| E-ink / ESP32 | 5 | 0 | 0 | 0 |

Each optimized scenario searches for an example once, saves from that example,
checks once, starts one **test-only** build, receives its terminal result in the
same call and retrieves one controlled firmware artifact. The explicit-authoring
baseline still reads native templates and the linked GxEPD2 example separately.
The controlled owner completes within the bounded start wait; these counts
do not predict real compiler polling or LLM latency. Pin coverage can remain
partial, and no electrical behavior is certified. Test-only AVR callbacks do
not extend the production offline owner's supported targets.

Full per-tool counts are checked into [mcp-compact-scenarios.json](mcp-compact-scenarios.json).
The regression test reruns the scenarios and compares the complete result.
These are finite contract paths, not a statistical estimate of Qwen reliability.

```sh
PYTHONPATH=backend python scripts/mcp-compact-scenarios.py
PYTHONPATH=backend python -m unittest discover -s test/backend/unit -p 'test_agent.py'
PYTHONPATH=backend python -m unittest discover -s test/backend/unit -p 'test_mcp_compact*.py'
```

Negative tests additionally cover union deduplication and stable pagination,
native template/save/check round trips, linked example source, unknown pin/type
limits, a legacy execution request, and the never-completed pending ESP32 tool.

Validation recorded for this change:

```text
test_agent.py:             Ran 31 tests — OK
test_mcp_compact*.py:      Ran 156 tests — OK
```

## Bounded start results and explicit success

`build_project(action="start")` accepts `wait_seconds`, a number from 0 through
60, defaulting to 20. The option is forbidden on `status`. A fast build returns
its terminal result directly. Only `state="done"` **and** `success=true` establish
compilation success; `ok=true` only means a valid tool response. Simulation
remains unsupported.

If the wait expires, the owner continues running and the response contains:

```json
{
  "state": "running",
  "stage": "queued",
  "success": null,
  "next_action": "call build_project status build_id=<returned build_id>"
}
```

`stage` distinguishes queued admission from active compilation. A final result
has `stage="complete"` and `state="done"`, `"error"` or `"interrupted"`.
The wait holds no storage lock and neither timeout nor client cancellation
cancels the owner. Different wait values reuse the same build identity.
An explicit `wait_seconds=0` retains nonblocking admission without exposing a
misleading public `pending` state.

## Unusable Arduino sketches are errors

`check_project` checks primary/`.ino` Arduino sources for collapsed single-line comments or
directives, entirely commented-out code, absent active `setup()`/`loop()`
definitions, and empty character literals such as `Serial.print(''Hello'')`.
Definitions are checked across source tabs. Comments, quoted text, character
literals and raw string literals do not count as function definitions. These
checks also run when compiler-policy evidence is missing. They do not apply
Arduino entry-point requirements to ESP-IDF or MicroPython.

An issue includes the JSON pointer `path`, `file` (for example `sketch.ino`),
`observed`, `expected`, and `next_action`. Errors precede warnings and informational
messages in the bounded response. `status="invalid"` prevents build admission;
the compiler callback is never entered for that snapshot. Empty board templates
remain saveable starters but must receive real source before a build.

This is a conservative lexical sanity check, not a C++ parser or preprocessor.
It does not resolve conditional compilation, macro-generated callbacks, external
headers or prove functional correctness. A passing structural report remains
`partial`, and the actual compiler result is still required.

## Read the first error before warnings

Build responses place `first_error` before the diagnostic lists. It is either
`null` or `{file, line, message, suggestion}`. The first error observed in the
compiler stream is retained even if later output truncates the bounded log
tail. Split log chunks and ANSI color sequences are handled. Generated-file
line mappings remain explicitly unverified.

Warnings, including `-Wcomment`, appear only in the separate `warnings` list,
capped at five with `warnings_truncated`. They cannot displace a real error.
The additional `diagnostics` list puts errors before notes and retains artifact
provenance. If a failing compiler provides no parseable error, the response
states that explicitly with a null location instead of inventing one. A compiler
callback that claims success while emitting an error is rejected and publishes
no firmware artifact.

## Earlier bounded-wait milestone counts

| Scenario | Calls before | Calls now | Unexpected errors before/now | Repeated calls before/now |
| --- | ---: | ---: | --- | --- |
| LED / Uno | 9 | 8 | 0 / 0 | 0 / 0 |
| Servo / Nano | 8 | 7 | 0 / 0 | 0 / 0 |
| E-ink / ESP32 | 9 | 8 | 0 / 0 | 0 / 0 |

Each fast controlled build saves exactly one status call. The scenario client
still supports a follow-up status request when `start` is non-terminal. These
are deterministic contract measurements, not a claim about real model latency
or real compilation. No real Qwen endpoint is used.

## Create from a catalog example without rewriting code

`save_project(from_example=example_id, parameters={...})` creates a new native
project. It is mutually exclusive with `document`, `changes`, `sketch`, and
existing project IDs. The server supplies source, board, components, libraries
and wiring. No source string or JSON document is required from the model.

The initial reviewed recipes are:

| Catalog ID | Accepted short parameters |
| --- | --- |
| `example:blink-led` | `board` (Uno), `delay_ms`, `pins.LED`, `external_led` |
| `example:uno-servo` | `board` (Uno/Nano), `pins.PWM`, `angle`, `delay_ms` |
| `example:epaper-1in54-uno-hello` | `board` (Uno/ESP32), `text`, `pins.CS/DC/RST/BUSY`, `frame` |

```json
{
  "from_example": "example:uno-servo",
  "parameters": {"board": "arduino-nano", "angle": 45, "pins": {"PWM": 9}, "delay_ms": 1000}
}
```

Search results and example references expose `from_example.supported` and the
full per-example JSON Schema under `from_example.parameters`. Query-matching
reviewed examples are prioritized in example searches. The existing
`example_references` ID list remains compatible; the companion `example_options`
lists those IDs with their supported parameter schemas. Unsupported recipes
advertise `supported=false` and fail explicitly instead of guessing a conversion.

Delays are integer milliseconds from 1 through 60000. Servo `angle` is 0 through
180; specifying it selects fixed-angle mode. Otherwise the original sweep is
preserved, and `delay_ms` requires an angle. The blink example uses its built-in
LED by default. `external_led=true` adds a native LED and series resistor and
allows the selected GPIO to be changed. Parameterized code and wiring use the
same pin values. E-paper control pins must be distinct, outside fixed SPI,
serial and reserved pins; board-specific defaults are advertised. User display
text is limited to 16 printable characters and is escaped safely as a C++ string.
Font coverage and actual rendering are not certified.

The server applies reviewed transformations to catalog source. Missing source
anchors are rejected; arbitrary parameter names and code injection parameters
are never accepted. `example_provenance` records the example ID, catalog revision,
original source hash, recipe version and resolved parameters. The native project
version remains the hash of the resulting snapshot. These recipes do not claim
that dependencies are installed or that a real compiler/simulator has run.

Tests cover native creation/checking for LED/Uno, fixed servo/Nano, e-paper/Uno,
and the e-paper/ESP32 variant; multiline source, quotes/backslashes in display
text, pin/code consistency, unknown parameters, reserved/colliding pins and
catalog-source changes. Structural checks remain honest `partial` reports when
electrical or other evidence is unavailable, with no structural errors.

### Native recipe call counts

The scenario script now reruns both the explicit-authoring baseline and the
recipe path. All three retain the same target board; the LED comparison uses
the external LED/resistor variant in both paths.

| Scenario | Explicit authoring | `from_example` | Unexpected errors before/after | Repeated calls before/after |
| --- | ---: | ---: | --- | --- |
| LED / Uno | 8 | 5 | 0 / 0 | 0 / 0 |
| Servo / Nano | 7 | 5 | 0 / 0 | 0 / 0 |
| E-ink / ESP32 | 8 | 5 | 0 / 0 | 0 / 0 |

The five calls are search, save from example, check, build and read the controlled
firmware artifact. Search already supplies the accepted parameters, so a second
reference read is unnecessary. The checked-in JSON includes both `baseline` and
`scenarios`. These remain controlled contract tests with no real model,
compiler, deployment or network dependency installation.

### Native wiring

Wires use native `start` and `end` endpoints containing `componentId` and
`pinName`. Copy these from the native templates or reviewed examples. Updates
use the native document or versioned changes; no `connect` argument is exposed.
ESP32 e-paper examples retain CS=5, DC=17, RST=16, BUSY=4, SCK=18 and SDI=23.

### Uniform errors (milestone 4g)

Every failed tool request (`ok=false`) now requires one error envelope with
`code`, `path`, `received`, `expected` and `next_action`; the compatible `message`
field remains. `path` is an RFC 6901 pointer (empty means the root); native
snapshot errors retain document-relative pointers. `received` is a JSON preview
of at most 200 characters, or `<missing>`. Expected values and next actions are
capped at 500 characters. Parameter failures inside reviewed recipes identify
the exact nested parameter and its advertised constraints.

The same formatter covers catalog/store/check/build services, SDK input-schema
rejections, owner/prerequisite failures and transport response-size refusals.
Retry guidance distinguishes malformed values from missing IDs, unsupported
operations, stale versions, wiring conflicts and unavailable prerequisites.
A parameterized regression checks all six services and all six SDK callbacks.
Successful check/build reports still carry their existing diagnostic formats:
`ok=true` is not proof of a valid circuit or successful compilation.

Deterministic happy-path calls remain 5 → 5 for each of LED/Uno, servo/Nano and
e-paper/ESP32, with zero errors or repeated calls. A separate recovery probe
uses one out-of-range pin, verifies the uniform error and exact parameter path,
then corrects it once: 6 calls, 1 expected error, 0 unexpected errors and 0
repeated calls per scenario. This measures the scripted recovery contract,
not the reasoning behavior of a real model. Native manual authoring
remain 8/7/8 calls. All compiler output remains an explicit controlled double.

Validation for milestone 4g: `test_agent.py` — 31 tests OK;
`test_mcp_compact*.py` — 165 tests OK. The deterministic report is regenerated
from the script, including the three successful one-correction recovery probes.

### Bounded catalog navigation (milestone 4h)

Both catalog tools return at most **24 KiB of UTF-8 JSON**, measured before MCP
transport framing. Search accepts `limit=1..50` (default 5); references accept
`limit=1..50` (default 20). Both accept an integer `offset=0..1000000`. Oversized
pages shrink to the largest prefix that fits the byte budget rather than
failing the entire request. Units and ordering are deterministic for a given
catalog revision; changing the requested limit does not change their identity.

Every successful catalog response includes `offset`, `limit`, `total`,
`has_more`, `truncated`, `next_offset`, `max_response_bytes`, `next_section`,
`next_request` and `next_action`. `next_offset` is strictly increasing while
`has_more=true`, and is `null` at the end. Follow the complete `next_request`
object when more data is needed, retaining the same query or reference section.
A matching search hit can be used immediately without reading further pages. `next_section` is an
optional navigation hint after the current section finishes, not a requirement
to read every section. Section hints terminate and cannot form a cycle.
An empty page beyond the total never restarts the search or reference.

For references, `total` and `offset` count section units: list entries, object
fields, file chunks, or explicit nested fragments. `data_complete=true` means
`data` is the complete section. Ordinary native board/component templates fit
in one default page and retain their existing directly usable shape. A page
with omitted preceding/following data has `truncated=true`; never save it as a
complete project. A successful tool request is not evidence of completeness.

Large `code` files are returned as plain `data.files[].content` chunks, with
`content_offset`, `content_next_offset` and `content_total_bytes` measured in
UTF-8 bytes. File identity and SHA-256 still refer to the complete file. Join
chunks of the same file in byte-offset order; no newline, quote or Unicode
repair is performed. Original non-UTF-8 source evidence remains lossless in
`data.raw_inputs[].content_b64`, with corresponding byte-offset fields.
Files small enough to fit one unit retain the original file object shape.

For an unusually large nested non-code field, `data=null` and `fragments`
contain explicit JSON-pointer paths, values and, for split strings,
`text_offset`/`next_text_offset`/`text_total_bytes`. These fragments are not a
native document. Concatenate strings at identical paths by byte offset and
reassemble the section only when needed; prefer a reviewed `from_example`
recipe for project creation. Oversized duplicate outer metadata is listed in
`metadata_omitted`; the section data remains available through pagination
(and example metadata through `overview`). Error paths are capped at 512
characters with `path_truncated=true` when necessary, keeping errors bounded.

| Scenario | Previous optimized calls | Current optimized calls | Manual native | Forced two-unit reference pages |
| --- | ---: | ---: | ---: | ---: |
| LED / Uno | 5 | 5 | 8 | 15 |
| Servo / Nano | 5 | 5 | 7 | 12 |
| E-paper / ESP32 | 5 | 5 | 8 | 13 |

All paths finish with zero unexpected errors, repeated identical calls or build
status polls. Forced paging adds 7/5/5 continuation calls, and produces the same
valid project structures before the controlled build. Happy-path catalog
responses peak at 2003/2712/3026 bytes respectively. The separate one-error
recovery paths remain 6 calls, 1 expected error and 0 unexpected errors each.
These are deterministic contract checks, not real-model success rates or real
firmware execution measurements.

Final validation for milestone 4h: `test_agent.py` — **31 tests OK**;
`test_mcp_compact*.py` — **173 tests OK**, including eight pagination regressions.
The scenario regression reproduces the checked-in JSON report exactly. Tests
use temporary isolated stores and controlled compiler adapters only.
