# Real Qwen MCP cycles — 2026-11-04

Local workbench only; no SSH, production access, deployment or push. OpenCode 1.19.3 uses the existing hyperqwen/qwen3.8-27b provider.
Fresh directory/session, identical neutral AGENTS.md, one complete natural user prompt, no coaching; sequential runs, 720-second timeout.
Each pass pins a Git worktree and uses the actual six-tool HTTP facade and genuine REST owner. The opt-in AVR lane executes the installed compiler, not a fixture.
Installed core, CLI and library sources are verified by real inventory hashes. Trusted local recipes; no claim of OS network isolation.
Independent recompilation reads immutable stored source. Strict success additionally requires a version/source-bound manual review of wiring, exact values and code behavior.
Compilation does not validate displayed pixels, motion, sensor accuracy or LED timing. C/W/V/S/B below mean compile/wiring/values/sketch/behavior.
Errors count failed MCP replies by code; checker informational findings are separate. Tokens are provider-reported total sums, including reused context; loop counts are identical calls repeated at least three times.

| Pass/case | MCP | Errors by code | Loops >=3 | Tokens | Seconds | C/W/V/S/B | Strict | Check/build/final read |
| --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |
| P1-B1 | 25 | invalid_argument:4 | [] | 476463 | 373.31 | Y/N/Y/Y/Y | False | Y/Y/Y |
| P1-B2 | 25 | dependencies_unknown:1, invalid_argument:6 | [3] | 353451 | 215.06 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P1-B3 | 38 | invalid_argument:6 | [3, 3] | 798173 | 720.06 | N/Y/N/N/N | False | N/N/N |
| P1-B4 | 44 | invalid_argument:6 | [4, 3] | 1053138 | 720.07 | N/N/N/N/N | False | N/N/N |
| P1-B5 | 32 | invalid_argument:10, project_invalid:1 | [3, 5] | 555482 | 720.06 | N/Y/N/N/N | False | N/Y/N |
| P2-B1 | 13 | 0 | [] | 103250 | 117.12 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P2-B2 | 14 | not_found:1 | [7] | 185548 | 99.22 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P2-B3 | 8 | 0 | [] | 45457 | 61.81 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P2-B4 | 7 | 0 | [] | 38773 | 57.71 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P2-B5 | 13 | 0 | [5] | 160542 | 99.74 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P3-B1 | 12 | 0 | [] | 120308 | 65.97 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P3-B2 | 10 | 0 | [] | 67154 | 86.0 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P3-B3 | 10 | 0 | [] | 62703 | 75.43 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P3-B4 | 6 | 0 | [] | 48885 | 47.24 | Y/Y/Y/Y/Y | True | Y/Y/Y |
| P3-B5 | 7 | not_found:1 | [] | 47310 | 50.25 | Y/Y/Y/Y/Y | True | Y/Y/Y |

## Pass scores and exact failure families
p1: 1/5 strict; errors [4, 7, 6, 6, 11]; complete=True; qualifying=False; revision `825f95e9550f`.
- `dependencies_unknown`: `{"arguments":{"action":"start","board_id":"arduino-uno-1","project_id":"p_9c56ab4730954935847ce3b01d5202e2","version":"5b738440884381ff83155e41f0bc01752cbb662862e5dde2942d8849ec9bf965","wait_seconds":60},"tool":"build_project"}`
- `invalid_argument`: `{"arguments":{"expected_version":"502da1f6fa4f068697d36f2c70e5f8a33d589e1537450d5766744d9d5e915386"},"tool":"save_project"}`
- `project_invalid`: `{"arguments":{"action":"start","board_id":"arduino-uno-1","project_id":"p_4035a67ccdd546a2bcceeb9caadbdd3a","version":"e27cbb314e6ae32de32191618b90966edbff4c5bf3461fc1296835f30b8172f4","wait_seconds":60},"tool":"build_project"}`
p2: 5/5 strict; errors [0, 1, 0, 0, 0]; complete=True; qualifying=True; revision `a8a6fc842be1`.
- `not_found`: `{"arguments":{"id":"component:push-button","section":"project"},"tool":"get_reference"}`
p3: 5/5 strict; errors [0, 0, 0, 0, 1]; complete=True; qualifying=True; revision `a8a6fc842be1`.
- `not_found`: `{"arguments":{"id":"p_737f3f4ce4f449bb962da0fb5e52d23c","section":"project"},"tool":"get_reference"}`

## Changes and evidence
- `1e36e2d1`: removed named wiring, retaining native start/end wires, e-paper pins and all ESP32 paths. 31 agent + 168 compact tests passed.
- `825f95e9`: real AVR inventory/admission and regression bench. Genuine HTTP/MCP control returned done/success=true/test_only=false with a real HEX; 31 agent + 171 compact tests passed.
- Cycle 1 measured 1/5 strict successes; error counts were [4,7,6,6,11], so no run set qualified. B3/B4/B5 reached the 720-second deadline. B1 compiled but used nonexistent cathode K; B2 implemented debounced toggle correctly.
- Cycle 2 implementation: lossless normalization of complete encoded structures and scalar numbers; incomplete strings remain errors. The LLM discovery schema is smaller while native validation remains authoritative.
- Cycle 2: real installed web-component pad references (including the distinct 4-pin I2C OLED) replace unknown names where evidence exists. Native endpoint aliases use the editor resolver; no named-wiring command is reintroduced.
- Cycle 2: scalar LED resistance/color, portable analog servo control, debounced button modes and composable sensor readouts/alarms; values and modes remain explicit parameters, with no benchmark prompt matching. E-paper gains optional metric-based centering without changing its default pins.
- Candidate verification: six real AVR REST-owner builds passed across alternate sensor/display/alarm and board combinations; 31 agent + 177 compact MCP tests passed, including ESP32. These controls are not counted as Qwen benchmark successes.
- Measured cycle 2 (`a8a6fc84`): 5/5 strict successes; MCP calls [13,14,8,7,13] versus [25,25,38,44,32], errors [0,1,0,0,0] versus [4,7,6,6,11]. All five read their final successful real owner build and independently recompile. One not_found ID guess remains; B2 repeats one search seven times and B5 five times. First qualifying pass; no further MCP change before confirmation.
- Confirmation pass 3, unchanged MCP revision `a8a6fc84`: 5/5 strict successes; calls [12,10,10,6,7], errors [0,0,0,0,1], no identical-call loops. All five checked, read their final successful real owner build and independently recompiled; final immutable documents match the reviewed pass-2 versions. Two consecutive qualifying passes achieved. The remaining error is an a saved project ID passed to catalog-only get_reference, not a failed project build.
- Database-export verification: 15/15 runs confirm exactly one complete user prompt and the required provider/model; no extra model request is made by this check.
- False-success review: 1/15 assessed conclusions contradicted by independent project evidence; unassessed=0.

HTTP trace: the malformed value is already present in the Qwen API response; OpenCode tool input and MCP incoming HTTP are identical.
Exact observed upstream value: `{"changes":"[{\"op\": \"set\", \"path\": \"/"}`. The internal distinction between model generation and the Qwen server parser is not observable here.

## Verdict, remaining work and limits
Stop requires two consecutive complete qualifying passes, each with all five strict successes and at most three MCP errors per run. No unmeasured success is claimed.
Only source-bound reviews count; valid JSON strings and numeric strings may be normalized, but incomplete arguments must not be guessed or silently repaired.
Two reserved validation prompts V1/V2 are separate from tuning; their results will be reported only when run. Small sample, one model/harness, order and cache effects remain limitations.
The improvement bundle is measured together, without per-feature ablation: individual contributions and causal shares are not established. Prompt coverage cannot prove general reliability.
B6-READY: `python scripts/mcp-bench-qwen.py pass --pass-number 6 --evidence <private-output> --cases B6 --mcp-url <explicit-URL>`; intended for the remote owner on its IDF host. No ESP32 run is performed here.
B6 checks exact quoted Hello World, centering logic and native CS5/DC17/RST16/BUSY4/SCK18/SDI23/3V3/GND; independent IDF recompilation remains required on that host. It is excluded from the five-case score.
Raw HTTP bodies, sessions, snapshots and compiler logs remain outside Git; authorization headers and provider keys are never logged or committed.
