# Chat and compact MCP share one project engine

The integrated chat uses the existing OpenCode adapter and authenticated
`/api/agent` session/message/event routes. It now exposes the same six core
operations as the compact MCP: search_catalog, get_reference, save_project,
check_project, build_project and read_artifact. Existing editor operations remain
available for component edits and supported simulation. Legacy low-level tools
are still accepted for resumed conversations but are omitted from discovery.

## Conversation scope

The conversation selects its project. Chat calls omit project_id, version and
expected_version; those fields are not advertised. Each conversation owns a
private ProjectStore, ProjectChecker and BuildService using the unchanged compact
implementations and reviewed catalog recipes. Other conversations cannot select
its snapshots or artifacts. The external six-tool MCP contract is unchanged.

`save_project(from_example="example:blink-led", parameters={...})` instantiates
the same code, libraries and native wires as compact MCP. The candidate must pass
the editor's real circuit validation and revision check before it is applied and
its sources are materialized. An editor rejection preserves existing sources.
Replacements retain the workspace's immutable previous revisions.

`save_project(sketch=source)` preserves literal source and supports a blank
workspace. `save_project()` captures files edited using OpenCode's native tools.
`check_project()` and build start also capture those current files. Libraries
can be explicitly updated with `save_project(libraries=[...])`.

OpenCode starts in workspace.work; its HTTP client explicitly selects that
directory. Every turn supplies cwd, exact relative file paths and active_file.
File tool summaries hide the workspace's absolute path. The model need not read
an artifact ID to find its own sketch. Native files remain grouped for projects
with several boards; moving directories is unnecessary.

The initial context advertises all reviewed starter examples with their real
parameter schemas from the shared recipe registry. No prompt classification or
benchmark-specific recipe selection occurs. A suitable starter needs no catalog
round trip. For other searches the chat schema requires an explicit query;
missing query receives a precise repair message, rather than repeated browsing.
The external compact search schema remains unchanged. Save returns a bounded
summary of the applied components; checks retain all returned errors/warnings,
summarize informational codes and link the complete report artifact.

## Build truth and editor truth

Chat compilation uses the genuine sealed REST owner, with the original chat
message's authenticated request and user. A model argument or callback token
cannot supply another compiler identity. The same configured inventory, admission
rules, diagnostics and bounded start wait apply as in compact MCP. Missing
inventory/toolchain/owner evidence remains an explicit error; nothing is installed.
AVR requires the existing owner opt-in and verified installed-cache inventory.
ESP32 retains its IDF lane and immediately unsupported simulation response.

Only done + success=true establishes compilation. Build results retain the source
revision actually built and indicate whether it still matches current files.
Polling an old job after editing cannot label it as a build of the new source.
Compile failures and invalid structural checks are error steps in the timeline,
even when the RPC itself completed. Compiler errors appear in the step summary.
Project-mutating calls are serialized within a conversation.

Simulation remains an editor operation: compile success never acknowledges
startup, movement, displayed pixels or sensor readings. Manual editor changes
continue to be protected by revision comparisons and the browser lease.

## Bounded model generation

AI settings include max_output_tokens (default 8192, range 512..32768) under
advanced limits. It is passed to OpenCode's model output limit. One pathological
response must not silently inherit a roughly 32000-token allowance. This limit
does not repair incomplete tool arguments or establish tool/model correctness.
OpenCode also requires a context window in this model declaration; the configurable
context_window defaults to 65536 and should match the connected model server.
Both limits are passed together. A configuration failure before a model request
is reported separately from a project or Qwen failure.

## Reproducible evaluation

`scripts/chat-bench-qwen.py` calls the real settings, session, message, SSE and
browser-result APIs and the real OpenCode adapter. It reuses the five AVR prompts
from the MCP evaluation, one prompt per fresh conversation, strictly sequential.
Actual REST-owner builds are independently recompiled from final stored sources.
MCP transport logging includes calls rejected before runtime validation.

Its backend editor adapter checks actual packaged native pins and acknowledges
only document application. It implements no simulator and does not establish
browser rendering or electrical behavior. Frontend bridge/circuit/execution tests
remain a separate check; production browser execution needs its own evidence.
Raw events, model sessions, settings and compiler logs stay outside Git. Provider
credentials come from existing configuration and are never committed.
