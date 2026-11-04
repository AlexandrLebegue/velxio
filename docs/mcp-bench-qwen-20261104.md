# Real Qwen MCP cycles — 2026-11-04

Local workbench only; no SSH, production access, deployment or push. OpenCode 1.19.3 uses the existing hyperqwen/qwen3.8-27b provider.
Fresh directory/session, identical neutral AGENTS.md, one complete natural user prompt, no coaching; sequential runs, 720-second timeout.
Each pass pins a Git worktree and uses the actual six-tool HTTP facade and genuine REST owner. The opt-in AVR lane executes the installed compiler, not a fixture.
Installed core, CLI and library sources are verified by real inventory hashes. Trusted local recipes; no claim of OS network isolation.
Independent recompilation reads immutable stored source. Strict success additionally requires a version/source-bound manual review of wiring, exact values and code behavior.
Compilation does not validate displayed pixels, motion, sensor accuracy or LED timing. C/W/V/S/B below mean compile/wiring/values/sketch/behavior.

| Pass/case | MCP | Errors by code | Loops >=3 | Tokens | Seconds | C/W/V/S/B | Strict | Final build read |
| --- | ---: | --- | --- | ---: | ---: | --- | --- | --- |
| P1-B1 | 25 | invalid_argument:4 | [] | 476463 | 373.31 | Y/N/Y/Y/Y | False | True |
| P1-B2 | 25 | dependencies_unknown:1, invalid_argument:6 | [3] | 353451 | 215.06 | Y/Y/Y/Y/Y | True | True |
| P1-B3 | 38 | invalid_argument:6 | [3, 3] | 798173 | 720.06 | N/Y/N/N/N | False | False |
| P1-B4 | 44 | invalid_argument:6 | [4, 3] | 1053138 | 720.07 | N/N/N/N/N | False | False |
| P1-B5 | 32 | invalid_argument:10, project_invalid:1 | [3, 5] | 555482 | 720.06 | N/Y/N/N/N | False | False |

## Pass scores and exact failure families
p1: 1/5 strict; errors [4, 7, 6, 6, 11]; complete=True; qualifying=False; revision `825f95e9550f`.
- `dependencies_unknown`: `{"arguments":{"action":"start","board_id":"arduino-uno-1","project_id":"p_9c56ab4730954935847ce3b01d5202e2","version":"5b738440884381ff83155e41f0bc01752cbb662862e5dde2942d8849ec9bf965","wait_seconds":60},"tool":"build_project"}`
- `invalid_argument`: `{"arguments":{"expected_version":"502da1f6fa4f068697d36f2c70e5f8a33d589e1537450d5766744d9d5e915386"},"tool":"save_project"}`
- `project_invalid`: `{"arguments":{"action":"start","board_id":"arduino-uno-1","project_id":"p_4035a67ccdd546a2bcceeb9caadbdd3a","version":"e27cbb314e6ae32de32191618b90966edbff4c5bf3461fc1296835f30b8172f4","wait_seconds":60},"tool":"build_project"}`

## Changes and evidence
- `1e36e2d1`: removed named wiring, retaining native start/end wires, e-paper pins and all ESP32 paths. 31 agent + 168 compact tests passed.
- `825f95e9`: real AVR inventory/admission and regression bench. Genuine HTTP/MCP control returned done/success=true/test_only=false with a real HEX; 31 agent + 171 compact tests passed.
- Cycle 1 measured 1/5 strict successes; error counts were [4,7,6,6,11], so no run set qualified. B3/B4/B5 reached the 720-second deadline. B1 compiled but used nonexistent cathode K; B2 implemented debounced toggle correctly.
- Prepared cycle 2, not yet measured: lossless normalization of complete encoded structures and scalar numbers; incomplete strings remain errors. The LLM discovery schema is smaller while native validation remains authoritative.
- Prepared cycle 2: real installed web-component pad references (including the distinct 4-pin I2C OLED) replace unknown names where evidence exists. Native endpoint aliases use the editor resolver; no named-wiring command is reintroduced.
- Prepared cycle 2: scalar LED resistance/color, portable analog servo control, debounced button modes and composable sensor readouts/alarms; values and modes remain explicit parameters, with no benchmark prompt matching. E-paper gains optional metric-based centering without changing its default pins.
- Candidate verification: six real AVR REST-owner builds passed across alternate sensor/display/alarm and board combinations; 31 agent + 177 compact MCP tests passed, including ESP32. These controls are not counted as Qwen benchmark successes.

HTTP trace: the malformed value is already present in the Qwen API response; OpenCode tool input and MCP incoming HTTP are identical.
Exact observed upstream value: `{"changes":"[{\"op\": \"set\", \"path\": \"/"}`. The internal distinction between model generation and the Qwen server parser is not observable here.

## Verdict, remaining work and limits
Stop requires two consecutive complete qualifying passes, each with all five strict successes and at most three MCP errors per run. No unmeasured success is claimed.
Only source-bound reviews count; valid JSON strings and numeric strings may be normalized, but incomplete arguments must not be guessed or silently repaired.
Two reserved validation prompts V1/V2 are separate from tuning; their results will be reported only when run. Small sample, one model/harness, order and cache effects remain limitations.
B6-READY: `scripts/mcp-bench-qwen.py pass --cases B6 --mcp-url <explicit URL>`; intended for the remote owner on its IDF host. No ESP32 run is performed here.
B6 checks exact quoted Hello World, centering logic and native CS5/DC17/RST16/BUSY4/SCK18/SDI23/3V3/GND; independent IDF recompilation remains required on that host. It is excluded from the five-case score.
Raw HTTP bodies, sessions, snapshots and compiler logs remain outside Git; authorization headers and provider keys are never logged or committed.
