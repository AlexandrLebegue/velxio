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
| P4 / B1 | 3 | 0 | [] | 56.96 | True | True |
| P4 / B2 | 3 | 0 | [] | 36.16 | True | True |
| P4 / B3 | 4 | {'invalid_argument': 1} | [] | 49.35 | True | True |
| P4 / B4 | 3 | 0 | [] | 38.93 | True | True |
| P4 / B5 | 3 | 0 | [] | 47.39 | True | True |
| P5 / B1 | 3 | 0 | [] | 38.24 | False | True |
| P5 / B2 | 3 | 0 | [] | 127.6 | True | True |
| P5 / B3 | 3 | 0 | [] | 40.07 | True | True |
| P5 / B4 | 3 | 0 | [] | 162.44 | True | True |
| P5 / B5 | 3 | 0 | [] | 88.3 | True | True |
| P6 / V1 | 2 | 0 | [] | 37.79 | True | True |
| P6 / V2 | 3 | 0 | [] | 37.83 | True | True |

P3 (`d2830fcb`): 5/5 strict successes, errors [0,0,0,0,0]; calls [14,10,11,16,33]. Total 879.23 seconds.
All five database/API exports confirm one exact prompt, qwen3.8-27b through the chat provider, and the correct OpenCode cwd.
The construction/build confidence criterion is met once; repeated catalog browsing still makes this slower than the external MCP. No latency parity is claimed.

## Changes and failures found
- `ac0b2ab4`: conversation-bound shared ProjectStore/ProjectChecker/BuildService, native source paths, recipe application through editor validation, real authenticated compiler context and visible build failures.
- `d2830fcb`: recovery after a rejected source update, version-bound build results, serialized project operations and explicit model context/output limits.
- Preflight smoke: real chat saved/applied the LED circuit and independently compiled it; one malformed/overlong generation reached about 32000 output tokens. This uncommitted smoke is not a frozen baseline.
- Infrastructure-only P2: OpenCode rejected incomplete model limit configuration before any Qwen request. Context/output must be configured together. Five attempts were excluded from Qwen success rates; configuration creation was then verified without a model call.
- P3 remaining bottleneck: repeated search_catalog calls omitted query and browsed the first page. B5 needed 33 MCP calls despite eventually producing a correct project.
- Next candidate: advertise all reviewed catalog starters and their actual parameter schemas in the initial chat context; require explicit search intent; bound informational check details while preserving errors, warnings and full report artifacts. Measured P4 (`3c0af840`): 5/5 strict, errors [0,0,1,0,0] and no loops. Calls [3, 3, 4, 3, 3], total 228.79 seconds; no generation reached its limit. P5 confirmation failed strict fidelity: 4/5, despite zero MCP errors. LED used 1000 ms per phase (0.5 Hz) while claiming 1 Hz. The two-pass criterion is not yet met.

## Verification and limits
Backend agent suite: 40 tests OK before the next optimization; compact MCP suite: 180 tests OK; targeted frontend agent bridge/circuit/execution/events: 31 tests OK.
Global TypeScript check fails identically on the original baseline: 357 diagnostics, no new diagnostic after normalizing worktree paths. These existing failures are not represented as a passing build.
Small sample, one model and one harness; no separate old-chat baseline or individual-feature ablation. Raw sessions, settings and compiler evidence remain outside Git.
No deployment, push, SSH or production access. ESP32 templates, compile lane and immediate simulation refusal are retained; actual ESP32 execution/display is not tested here.

P6 reserved French validations: 2/2 strict. Existing Nano source was edited in cwd and its user header/call preserved; an Uno/sliding-potentiometer/servo project was created correctly. These outcomes were not used for tuning.

Next correction: shared blink recipes expose frequency_hz for full cycles, document delay_ms as per-phase, and return nominal source-derived timing. Exact P5 wrong-rate call: `{"from_example":"example:blink-led","parameters":{"board":"arduino-uno","delay_ms":1000,"external_led":true,"resistance_ohms":220}}`. No API error was expected: the supplied parameters were valid but did not fulfill the user request.
Centered e-paper recipes now remove extra demo labels while preserving legacy/default mode and native ESP32 pins. This is a deterministic source-fidelity fix, not a display/runtime validation.
