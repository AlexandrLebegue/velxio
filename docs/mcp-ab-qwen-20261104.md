# Real local Qwen: compact MCP A/B, 2026-11-04

## Protocol and scope
A = `f11eef9d56786ca073bb385d0489da1c605378ce`; B = `f9e3591e28eb079e5425224e16913f554c9b292f`.
OpenCode 1.19.3 used the existing global `hyperqwen/qwen3.8-27b` provider unchanged; no credentials were copied.
Two pristine temporary Git worktrees served their actual six-tool facade and genuine REST owner on loopback only; production was never contacted.
No MCP source, compiler callback or tool result was patched. HTTP request/response tracing covered schema rejections as well as dispatched calls.
Each run had a new directory, a new session, only `model` and one `velxio` MCP in its local configuration, and identical neutral instructions:
`Complete the user's requested Velxio project. Use only the velxio MCP tools.`
Built-in tools and unrelated integrations were disabled identically through environment configuration. No follow-up prompts, corrections or model retries were sent.
Each model run had a 720-second timeout. Order: S1 A/B, S2 B/A, S3 A; the quota stop prevented every subsequent run.
Session exports verify one user message, the actual provider/model, and identical complete user-text hashes within each executed pair; OpenCode applies the same outer quote wrapper.
**Partial experiment:** the user reported Codex quota below 10% and requested stopping after S3-A-1. Missing runs are marked **not executed, quota**: S3-B-1 and all six second repetitions (S1-A-2, S1-B-2, S2-A-2, S2-B-2, S3-A-2, S3-B-2).

## Exact scenario prompts
P1: Create and save a Velxio project with an Arduino Uno, one external LED and one 220-ohm series resistor. Make the external LED blink at 1 Hz (500 ms on, 500 ms off). Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.
P2: Create and save a Velxio project with an Arduino Nano and a servo motor. Repeatedly sweep the servo smoothly from 0 to 180 degrees and back to 0 degrees. Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.
P3: Create and save a Velxio project with an ESP32 DevKit and a 1.54-inch black-and-white e-paper display. Display exactly "Hello World" centered on the screen. Wire the circuit consistently with the sketch. Check the saved project and request a build. Report the saved project and version, the actual build outcome and any limitations. Use only the velxio MCP tools.

## Measurements from the journals
`mean [raw]`: with one execution per cell, mean equals the raw observation. E counts failed MCP replies, grouped by error code; checker findings are separate.
L counts distinct identical tool-name/argument signatures occurring at least three times. Tokens are provider-reported totals, including cached input and reasoning, summed across steps; not unique context size or independently tokenized text.
Durations cover the OpenCode session, excluding independent recompilation. No production or hardware execution is included.

| Scenario/version | n | MCP calls, mean [raw] | E, mean [raw] | Error codes (raw counts) | L [signature occurrence counts] | Tokens, mean [raw] | Seconds, mean [raw] |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| S1/A | 1 | 24 [24] | 2 [2] | dependencies_unknown=1; invalid_argument=1 | 0 [] | 181154 [181154] | 572.15 [572.15] |
| S1/B | 1 | 30 [30] | 9 [9] | dependencies_unknown=1; invalid_argument=8 | 0 [] | 522347 [522347] | 380.24 [380.24] |
| S2/A | 1 | 41 [41] | 9 [9] | dependencies_unknown=3; invalid_argument=6 | 1 [3] | 595092 [595092] | 421.11 [421.11] |
| S2/B | 1 | 38 [38] | 13 [13] | dependencies_unknown=1; invalid_argument=10; not_found=1; project_invalid=1 | 1 [4] | 899327 [899327] | 551.15 [551.15] |
| S3/A | 1 | 20 [20] | 2 [2] | dependencies_unknown=1; invalid_argument=1 | 0 [] | 156401 [156401] | 325.49 [325.49] |
| S3/B | 0 | not executed, quota | — | — | — | — | — |
| All scenario/version repetitions 2 | 0 | not executed, quota | — | — | — | — | — |

## Independent truth and conclusions
The final project explicitly named in the model's conclusion was audited, not a later disposable probe. If no final ID exists, use the last saved snapshot and disclose that fallback.
The audit checked immutable snapshot hashes, read the complete stored sketch and native wiring, and rebuilt the unchanged source using the same installed Arduino CLI environment. Real firmware hashes are retained locally.
Uno/Nano empty-sketch compiler controls both passed. The installed cache contains AVR 1.8.6, Servo 1.3.0 and the e-paper libraries; no toolchain/library installation was attempted.
**Shared laboratory limitation:** no verified MCP build inventory was provisioned, and the unchanged production owner restricts offline dispatch. MCP requests were refused before compiler execution; these results do not measure admitted production build completion or `wait_seconds` latency.
ESP-IDF is absent. Any S3 Arduino CLI fallback recompilation is supplementary only: S3 is excluded from success rates, and B/S3 was not executed.
`NL` is the number of stored source lines. One-line valid C++ is not automatically corruption: A/S1 is valid minified C++; A/S2 starts with `//` and comments out the entire program. Directly submitted source matched the stored bytes.
Success requires independent compilation, scenario-conforming wiring/components and faithful source. Compilation never establishes LED timing, servo motion or displayed pixels.

| Run | check / build requested | Final build job status read | Independent compile | Wiring / faithful sketch | NL | What Qwen concluded versus reality |
| --- | --- | --- | --- | --- | ---: | --- |
| S1-A-1 | yes / yes | no job: preflight refused | OK | no / yes | 1 | Disclosed refused build and unverified pins; stored LED cathode is `K`, but the native cathode is `C`. |
| S1-B-1 | yes / yes | no job: preflight refused | OK | no / yes | 13 | Disclosed refused build and the 1 kOhm resistor; correct series wiring, but the requested value was 220 ohms. |
| S2-A-1 | yes / yes | no job: preflight refused | KO | yes / no | 1 | Said “All steps complete” and described a sweep; the entire stored program is a comment. Old check reported valid structure and zero errors. |
| S2-B-1 | yes / yes | no job: preflight refused | OK | yes / yes | 33 | Disclosed refused MCP build. The final recipe really compiles; D9/PWM, 5V/V+ and GND match the 0–180–0 sweep source. |
| S3-A-1 | yes / yes | no job: preflight refused | KO, supplementary CLI; excluded | pins consistent / no | 1 | No final answer: last step ended with `length`. Last saved source has adjacent includes, invalid text APIs and unquoted `F(Hello World)`. Text is present, not a valid displayed literal. |

Eligible strict task successes: **A 0/2; B 1/2**. This is an observation, not a statistically established improvement.
False compilation-success declarations: **A 0; B 0** across the five executed runs; S3/A had no final answer. Every completed final report disclosed its build refusal. Separately, A/S2 supplied a false source-behavior assurance despite unusable code.
B/S1 and B/S2 blamed a transport defect. The requests already contained incomplete encoded strings; the origin of that truncation/encoding was not isolated. Neither that diagnosis nor the claim that removing `Servo` would enable a build is established by the logs.

## Top three remaining B error families: exact triggers
1. **invalid_argument, 18 occurrences** across S1/B and S2/B: encoded/incomplete structures or missing required IDs. P1 produced this exact call:
`save_project({"changes":"[{\"op\": \"set\", \"path\": \"/","expected_version":"4f2211044abb87ee0d6db173d2a7eb012258fe4ccef309bce8b66bb95f788aea","project_id":"p_dfb9d37209024b9ab728e5cde301ecfd"})`
2. **dependencies_unknown, 2 occurrences**, a shared environment/admission blocker rather than a B-specific regression. P1 produced:
`build_project({"action":"start","board_id":"board","project_id":"p_dfb9d37209024b9ab728e5cde301ecfd","version":"4f2211044abb87ee0d6db173d2a7eb012258fe4ccef309bce8b66bb95f788aea","wait_seconds":60})`
3. **not_found, 1 occurrence**: P2 attempted a nonexistent library namespace: `get_reference({"id":"library:Servo","section":"overview"})`.
The other single B error, `project_invalid`, was a useful guard: an all-comment diagnostic sketch was refused before compilation. It is included in E, not treated as a server defect.

## Verdict by change (observational, not a feature ablation)
| Change | Verdict | Evidence from actual runs |
| --- | --- | --- |
| build_project wait_seconds | Not measurable | No build reached admission; setting 60 seconds did not bypass preflight. |
| Reject unusable sketches | Positive safeguard | B/S2 refused an all-comment control sketch with `project_invalid`; A/S2's final all-comment source passed the old check and independently failed compilation. |
| Plain sketch text | Neutral / preservation verified | Plain-text probes were saved, including incomplete input. Recorded source bytes were preserved; this did not repair caller-side truncated content. |
| from_example | Positive, limited | B/S2's final Nano recipe passed the strict independent audit; B/S1 still needed an unsupported 220-ohm customization and failed that requirement. |
| Named wiring | Negative observed usability | B/S1 sent `connect` as an incomplete JSON string and received `invalid_argument`; no successful named-wire resolution was observed. This does not prove the resolver is incorrect. |
| Uniform errors + next_action | Neutral for recovery | The uniform fields were present, but B/S2 repeated the identical invalid patch four times despite them. |
| Reference pagination | Not measurable | Executed B runs used no reference continuation offset and triggered no size refusal. S3/B is missing. |
| Tolerant search | Positive discovery | B/S1 `220 resistor led` returned merged matches with `query_used=[220,resistor,led]`; it did not solve the final resistor mismatch. |
| instance_template | Not separately measurable | B advertised native templates, but its final successful deliverable came through from_example; no isolated template effect can be scored. |

## Three priorities and limits
1. Trace Qwen output → OpenCode argument parsing → MCP request encoding in a separate authorized experiment; incomplete strings/arrays dominate B failures. Do not assume the MCP transport caused them.
2. Add reviewed scalar customizations for common requirements (220-ohm resistance, centered display text), and a plain connection-string form, so weak models can avoid native document/patch arrays.
3. Provision a genuine common build inventory/admitted compiler lane before measuring terminal-state trust or wait behavior; expose unavailable capabilities directly to avoid futile library/inventory searches.
Small, quota-truncated sample; one model/harness, no seed control, warm caches and order effects, no per-feature randomized ablation. S3 has no executed B comparator and no local ESP-IDF.
The previous deterministic five-call path does not predict these real-model paths: B used 30 and 38 calls, with 9 and 13 errors, for the two eligible cases.
Raw journals, session exports, snapshots and compiler logs stay outside Git. Only the benchmark script and this report are committed; temporary worktrees and servers are removed/stopped.

Cleanup proof: both servers stopped and both temporary worktrees removed; no S3-B-1 session or second repetition was started. Five session exports each verify one complete prompt and only the requested model; paired prompt hashes and every AGENTS.md hash match. Benchmark syntax compilation passed.
