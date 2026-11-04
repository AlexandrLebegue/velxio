# Integrated chat evaluation — 2026-11-04

Scope: actual chat API, OpenCode adapter, project workspace and session-bound tools. External six-tool MCP results are a separate evaluation.
The Qwen provider is reused from existing local configuration; no credentials or internal addresses are recorded here.
Fresh conversation and workspace per case; one unchanged natural prompt from the five AVR MCP cases; no follow-up coaching; strictly sequential.
Backend editor adapter acknowledges the real SSE/browser-result protocol and validates packaged native pads. It does not render a browser or implement a simulator.
Compilation uses the genuine REST owner and installed inventory, followed by independent Arduino CLI compilation of the final source.
Strict success requires compile, editor/document agreement, exact wiring/values and intact behavior reviewed against the prompt, plus the final build result being read.
Runtime display, movement and electrical behavior are not established by compilation.

| Pass / case | MCP calls | Errors | Repeated identical calls >=3 | Seconds | Strict | Final build read |
| --- | ---: | --- | --- | ---: | --- | --- |
| P3 / B1 | 14 | 0 | [3] | 189.06 | True | True |
| P3 / B2 | 10 | 0 | [] | 78.46 | True | True |
| P3 / B3 | 11 | 0 | [] | 102.63 | True | True |
| P3 / B4 | 16 | 0 | [3] | 116.03 | True | True |
| P3 / B5 | 33 | 0 | [4] | 393.05 | True | True |

P3 (`d2830fcb`): 5/5 strict successes, errors [0,0,0,0,0]; calls [14,10,11,16,33]. Total 879.23 seconds.
All five database/API exports confirm one exact prompt, qwen3.8-27b through the chat provider, and the correct OpenCode cwd.
The construction/build confidence criterion is met once; repeated catalog browsing still makes this slower than the external MCP. No latency parity is claimed.

## Changes and failures found
- `ac0b2ab4`: conversation-bound shared ProjectStore/ProjectChecker/BuildService, native source paths, recipe application through editor validation, real authenticated compiler context and visible build failures.
- `d2830fcb`: recovery after a rejected source update, version-bound build results, serialized project operations and explicit model context/output limits.
- Preflight smoke: real chat saved/applied the LED circuit and independently compiled it; one malformed/overlong generation reached about 32000 output tokens. This uncommitted smoke is not a frozen baseline.
- Infrastructure-only P2: OpenCode rejected incomplete model limit configuration before any Qwen request. Context/output must be configured together. Five attempts were excluded from Qwen success rates; configuration creation was then verified without a model call.
- P3 remaining bottleneck: repeated search_catalog calls omitted query and browsed the first page. B5 needed 33 MCP calls despite eventually producing a correct project.
- Next candidate: advertise all reviewed catalog starters and their actual parameter schemas in the initial chat context; require explicit search intent; bound informational check details while preserving errors, warnings and full report artifacts. Not yet measured.

## Verification and limits
Backend agent suite: 40 tests OK before the next optimization; compact MCP suite: 180 tests OK; targeted frontend agent bridge/circuit/execution/events: 31 tests OK.
Global TypeScript check fails identically on the original baseline: 357 diagnostics, no new diagnostic after normalizing worktree paths. These existing failures are not represented as a passing build.
Small sample, one model and one harness; no separate old-chat baseline or individual-feature ablation. Raw sessions, settings and compiler evidence remain outside Git.
No deployment, push, SSH or production access. ESP32 templates, compile lane and immediate simulation refusal are retained; actual ESP32 execution/display is not tested here.
