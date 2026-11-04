# Integrated chat evaluation — 2026-11-04

Verdict: the final shared-core chat achieves 5/5 strict successes twice consecutively, with zero MCP errors and three MCP calls per project.
Two reserved French validations also pass on the final engine, including editing an existing workspace while preserving a user header and its call.
Final measured agent/recipe code: `5d82b099`. A subsequent workspace-only newline fix preserves CRLF; the measured LF workflow is unchanged and the exact round trip has a regression test.

## Protocol and independent truth
Actual settings/session/message/SSE/browser-result chat APIs and the real OpenCode adapter, using qwen3.8-27b from existing local connection configuration.
Fresh conversation per case; one complete unchanged user prompt, no follow-up coaching; runs strictly sequential. Provider alias is velxio, as in the actual chat.
Limits: 40 steps, 720 seconds, 8192 output tokens, 65536 context tokens. The final five-case runs fit the normal 20-step/300-second defaults too.
Compilation uses the genuine sealed REST owner and verified local AVR inventory. Every final terminal build is test_only=false and matches the final workspace.
An independent Arduino CLI compilation reads final stored source. Version/source-bound manual review checks native wiring, exact values, intact sketch and code behavior.
Strict success requires all of those checks, editor/document agreement and observing the final successful build before conclusion. Compilation alone is insufficient.
The backend editor adapter implements the actual event/acknowledgement protocol and packaged native pin validation, not browser rendering or an electrical simulator.
Displayed pixels, LED timing and motor movement are not runtime-validated. Frontend bridge/circuit/execution tests are a separate check.
Tokens below sum provider-reported totals, including cached context. Loops list identical MCP calls repeated at least three times. File calls and harness errors are counted separately.

| Pass/case | MCP/file calls | MCP errors | Harness errors | Loops | Tokens | Seconds | Strict | Final build read |
| --- | ---: | --- | ---: | --- | ---: | ---: | --- | --- |
| P3/B1 | 14/1 | 0 | 0 | [3] | 285361 | 189.06 | True | True |
| P3/B2 | 10/1 | 0 | 0 | [] | 165059 | 78.46 | True | True |
| P3/B3 | 11/1 | 0 | 0 | [] | 209493 | 102.63 | True | True |
| P3/B4 | 16/0 | 0 | 0 | [3] | 248289 | 116.03 | True | True |
| P3/B5 | 33/1 | 0 | 0 | [4] | 415813 | 393.05 | True | True |
| P4/B1 | 3/1 | 0 | 0 | [] | 60968 | 56.96 | True | True |
| P4/B2 | 3/1 | 0 | 0 | [] | 55553 | 36.16 | True | True |
| P4/B3 | 4/1 | invalid_argument:1 | 0 | [] | 69192 | 49.35 | True | True |
| P4/B4 | 3/0 | 0 | 0 | [] | 44819 | 38.93 | True | True |
| P4/B5 | 3/0 | 0 | 0 | [] | 47526 | 47.39 | True | True |
| P5/B1 | 3/1 | 0 | 0 | [] | 44618 | 38.24 | False | True |
| P5/B2 | 3/0 | 0 | 0 | [] | 50881 | 127.6 | True | True |
| P5/B3 | 3/0 | 0 | 0 | [] | 44901 | 40.07 | True | True |
| P5/B4 | 3/0 | 0 | 0 | [] | 52100 | 162.44 | True | True |
| P5/B5 | 3/0 | 0 | 0 | [] | 52351 | 88.3 | True | True |
| P6/V1 | 2/3 | 0 | 0 | [] | 64686 | 37.79 | True | True |
| P6/V2 | 3/0 | 0 | 0 | [] | 44147 | 37.83 | True | True |
| P7/B1 | 3/0 | 0 | 0 | [] | 44790 | 44.1 | True | True |
| P7/B2 | 3/1 | 0 | 0 | [] | 57163 | 41.79 | True | True |
| P7/B3 | 3/1 | 0 | 0 | [] | 58484 | 43.26 | True | True |
| P7/B4 | 3/1 | 0 | 0 | [] | 58272 | 41.69 | True | True |
| P7/B5 | 3/1 | 0 | 0 | [] | 59978 | 46.79 | True | True |
| P8/B1 | 3/0 | 0 | 0 | [] | 45666 | 40.47 | True | True |
| P8/B2 | 3/1 | 0 | 0 | [] | 64382 | 149.74 | True | True |
| P8/B3 | 3/0 | 0 | 0 | [] | 44322 | 35.29 | True | True |
| P8/B4 | 3/0 | 0 | 0 | [] | 38137 | 67.02 | True | True |
| P8/B5 | 3/1 | 0 | 0 | [] | 57913 | 104.15 | True | True |
| P9/V1 | 2/3 | 0 | 0 | [] | 65408 | 67.62 | True | True |
| P9/V2 | 3/1 | 0 | 0 | [] | 58124 | 129.63 | True | True |

## Scores and measured effects
P3: 5/5 strict; calls [14, 10, 11, 16, 33]; errors [0, 0, 0, 0, 0]; total 879.23 seconds.
P4: 5/5 strict; calls [3, 3, 4, 3, 3]; errors [0, 0, 1, 0, 0]; total 228.79 seconds.
P5: 4/5 strict; calls [3, 3, 3, 3, 3]; errors [0, 0, 0, 0, 0]; total 456.65 seconds.
P7: 5/5 strict; calls [3, 3, 3, 3, 3]; errors [0, 0, 0, 0, 0]; total 217.63 seconds.
P8: 5/5 strict; calls [3, 3, 3, 3, 3]; errors [0, 0, 0, 0, 0]; total 396.67 seconds.
P7 and P8 are the two qualifying final passes on unchanged engine code. All ten source/circuit snapshots match independently reviewed correct versions; no contradictory success was found.
P3 was the first complete shared-core chat implementation, not an old-production-chat baseline. Calls fell from 84 to 15 for five cases; time changed from 879.23 s to 217.63/396.67 s.
P5 demonstrates the importance of independent review: it had zero MCP errors and compiled every project, but one valid sketch blinked at 0.5 Hz while Qwen claimed 1 Hz. It is scored 4/5, with one false completion.
Reserved P6 and final P9: both 2/2 strict; zero MCP errors. V1 edits Nano blink timing in cwd and retains user_note.h byte-for-byte plus userNote(); V2 uses Uno and a sliding potentiometer for servo control. No changes were tuned from those validation outcomes.

## Changes and exact failure families
- `ac0b2ab4`: shared compact catalog/store/check/build core behind conversation-bound tools; project identities stay server-side, sources stay in cwd, real compiler admission retains the authenticated chat owner.
- `d2830fcb`: recover after rejected editor updates, serialize mutations, bind build results to the source actually compiled, expose failures in the timeline, configure both required model limits.
- `3c0af840`: advertise every reviewed catalog starter and its real parameters in initial context. No benchmark prompt matching. Require explicit query for other searches and summarize informational check details with full report artifacts retained.
- `5d82b099`: frequency_hz means complete on/off cycles; delay_ms explicitly means each phase. Generated nominal timing is returned for comparison. Centered e-paper removes extra demo labels while preserving native SPI/control pins and default mode.
- Repeated catalog browsing came from calls such as `search_catalog(kind="example",limit=10,offset=0)` with query omitted. Initial starter context removes that discovery loop; missing-query errors now explain the exact missing field.
- P4 B3 recoverable invalid_argument: `save_project(from_example="example:uno-servo",parameters={"PWM":9,"analog_pin":"A0","board":"arduino-nano","control":"potentiometer","input_component":"potentiometer","sample_ms":15})`. PWM belongs inside pins. The model repaired it; final passes have no such errors.
- P5 wrong-rate call: `save_project(from_example="example:blink-led",parameters={"board":"arduino-uno","delay_ms":1000,"external_led":true,"led_color":"red","pins":{"LED":13},"resistance_ohms":220})`. This is API-valid but gives a 2000 ms cycle. Explicit Hz and returned source-derived timing address the ambiguity.
- An initial uncommitted LED smoke used about 32000 output tokens in one malformed/overlong generation. It is not a frozen baseline. Output is now bounded; neither final pass hit its generation limit.
- Infrastructure-only P2 attempts failed before Qwen requests because OpenCode requires context and output limits together. These five attempts are excluded from model success rates; session creation with the corrected configuration was separately verified without a model call.

## Verification, deployment prerequisites and limits
Backend: test_agent*.py — 44 tests OK; test_mcp_compact*.py — 182 tests OK, including native ESP32 pins and source fidelity.
Deterministic six-tool scenarios remain 5/5/5 calls with zero unexpected errors; their checked-in byte-size measurements were refreshed after recipe metadata changed.
Frontend: four targeted agent suites, 31 tests OK; formatting OK; Vite production bundle built successfully in 9.53 s.
Global TypeScript check still reports the same 357 diagnostics on the original baseline after normalizing worktree paths. It is not reported as passing.
AVR requires owner opt-in and a verified installed-cache inventory. The private AVR-only benchmark inventory must not replace production ESP32 evidence when enabling both targets.
ESP32 offline compilation and immediate simulation refusal are retained. Centered e-paper source is corrected and tested deterministically; actual ESP32 build/display needs its IDF host and is not claimed here.
This is one model/harness and a small sample, with order/cache/reasoning-time variation. There is no old-chat A/B baseline or per-feature causal ablation. Broader custom projects and real browser execution remain separate validation work.
All benchmark servers and managed harnesses were stopped. Raw sessions, credentials, compiler logs and snapshots remain outside Git. No SSH, production access, deployment or push was performed.
At the user request, no further Qwen calls are made; remaining work is offline reporting and committing.
