# Compact MCP: small-model authoring contracts

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
| LED / Uno | 9 | 0 | 0 | 1 |
| Servo 45 degrees / Nano | 8 | 0 | 0 | 1 |
| E-ink / ESP32 | 9 | 0 | 0 | 1 |

Each scenario searches once, reads native templates, saves once, checks once,
starts one **test-only** build, reads its terminal status once and retrieves one
controlled firmware artifact. E-ink also reads the real linked library example.
The controlled owner completes before the single status request; these counts
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
test_mcp_compact*.py:      Ran 133 tests — OK
test_agent_opencode.py:    Ran 1 test — OK (real OpenCode, local deterministic model fixture)
```
