# Chat generalization evaluation — 2026-11-04

This is a held-out measurement of the existing integrated chat, not a recipe
demonstration. Application code, system instructions and the six reviewed
recipes are frozen before the first run. No solution is added to the catalog.

The six prompts in `scripts/chat-generalization-cases.json` contain user
requirements only. They cover two-output asymmetric timing, bounded servo steps
from buttons, an RGB gradient with an enable toggle, three-zone parking signals
with nonblocking beeps, a latched PIR alarm, and a binary counter added to an
existing project. None can be fulfilled by an unchanged reviewed recipe.

Existing catalog references and general-purpose recipes remain available exactly
as in the actual chat. Reusing a foundation is allowed; the saved project must
still satisfy every new requirement. Recipe use and authored adaptations are
reported separately. A build alone is never counted as strict success.

G1–G5 start in empty projects. G6 starts with a Nano, empty loop and unrelated
user-owned header/callback; it contains no counter or LED solution. Requirements,
expected results and audit code are outside the model workspace. File access and
the exact single user prompt are checked from the real harness session.

Runs use the actual chat API/OpenCode adapter and genuine REST-owner AVR builds,
one prompt per fresh session, strictly sequential, with a 720-second ceiling.
Independent recompilation and native wiring/value/source review determine truth.
Where feasible, deterministic input stimuli are applied to compiled AVR firmware
to check timing and state transitions. Those checks do not validate browser
rendering, physical motion, sound levels or sensor accuracy.

The backend editor adapter checks real packaged pin names and acknowledges the
editor protocol; it is not a browser simulator. ESP32 is outside this local AVR
suite. Raw credentials, traces, snapshots and compiler artifacts remain outside
Git. No deployment, production access, SSH or push is performed.

## Frozen run and results

Product baseline: `46055192`; frozen measurement worktree: `f4012acd`.
All six runs used that same immutable worktree, Qwen `qwen3.8-27b`, and the real
chat adapter. No application, tool description, recipe or system prompt changed.
Only evaluation scripts, tests and this report were subsequently edited.
Six single human prompts, six fresh conversations, sequential; no human repair.
OpenCode automatically compacted G3–G6 once each and inserted its generic
synthetic continuation. These are disclosed separately from supplied prompts;
literal single-message proof is false for those four runs. No solution coaching
was supplied. G1 hit the generation limit once and recovered autonomously.
All completed native file accesses resolve inside their own project workspace.

Strict success means independent compilation, faithful multiline source, correct
native wiring/values, and passing the tested firmware behavior. Table values are
raw observations, one run per case. RPC errors exclude compiler failures.
Tokens are provider-reported total, including cached input and reasoning.

| Case | Requirement | MCP / native calls | RPC errors | Failed builds | Seconds | Tokens | Strict |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| G1 | Two LEDs, asymmetric alternating sequence | 11 / 2 | 0 | 0 | 227.40 | 261863 | PASS |
| G2 | Two buttons, bounded servo steps | 12 / 2 | 0 | 1 | 150.70 | 289292 | PASS |
| G3 | Common-anode RGB gradient and toggle | 20 / 2 | unsupported: 1 | 0 | 304.51 | 459682 | PASS |
| G4 | Three-zone parking alarm, nonblocking beep | 21 / 2 | invalid_argument: 1 | 0 | 300.78 | 285826 | PASS |
| G5 | Latched PIR alarm with reset/rearm | 24 / 2 | unsupported: 1 | 0 | 381.44 | 556456 | FAIL |
| G6 | Binary counter, held reset, preserve user code | 18 / 3 | unsupported: 1 | 0 | 324.20 | 371291 | FAIL |

Totals: 106 MCP calls, 13 native calls, four RPC errors, one recovered compiler
failure, 1689.03 seconds. Mean: 17.67 MCP calls and 281.51 seconds per project.
No identical MCP call repeated three times. No native-tool errors were reported.
All six called check, read a successful real build of the final current revision,
matched the editor snapshot and independently recompiled successfully.
Final source retained real newlines and quotes in all six cases.

Token details, input / output / reasoning / cached-input-read:
G1 `39460/9938/4385/208080`; G2 `35943/1964/5769/245616`;
G3 `84770/4364/8244/362304`; G4 `88021/4276/9929/183600`;
G5 `98362/5006/14080/439008`; G6 `87246/4778/9987/269280`.

## Independent truth and remaining failures

G1's generated starter was only a one-channel foundation. Qwen added a second
branch and rewrote the timing. Firmware trace: 150 ms pulses, 2000 ms periods,
1000 ms channel separation, no overlap. Both resistors are 330 ohms.
G2 authored its own project; bounce, a held button, repeated presses and both
saturation limits passed the servo pulse audit. It recovered from a missing
Servo library declaration after the first real compiler failure.
G3 authored its own project: correct common anode, three 220-ohm branches,
blue/purple/red ADC positions, green off and debounced held-button toggle passed.
G4 adapted the existing ultrasonic foundation, adding three LED branches and
rewriting the sketch. Three zones, approximately 200/800 ms beep envelope and
response during a beep passed. One tested transition took 4.98 ms; this is not
a proof of worst-case latency over every possible input or sensor condition.

G5 has correct wiring/330-ohm values but a broken generated debounce function:
`if (rawPressed != buttonStable) lastButtonChangeMs = millis();` runs repeatedly
while pressed, so its 30 ms acceptance interval never elapses. The alarm latches
but does not reset on a fresh press after motion stops. Firmware I/O confirms
red/tone remain active when reset should clear them. Qwen concluded “the task is
complete”; that completion claim is contradicted by the independent audit.

G6 connects GPIO5 to `btn-reset.1.l` and ground to `btn-reset.1.r`. These are the
same internal contact, so GPIO5 is permanently grounded and the button cannot
reset the counter. Source review agrees with packaged pushbutton documentation
and the circuit-to-SPICE contact model. The firmware fixture respects that fixed
ground instead of injecting an impossible button transition. Counting and wrap
work, but the reset requirement fails. The header is byte-for-byte preserved;
UART output `USER_CODE_KEEP` also proves its setup callback executes. Qwen said
“fully complete” despite the wiring fault: a second contradicted completion.

Remaining exact RPC error calls:
`run_project({})` in G3/G5/G6: unsupported because this editor adapter has no
simulator; each run stopped retrying and disclosed that limitation.
G4: `search_catalog({"kind":"component","properties":"{}","x":"0","y":"0"})`
omits required query; the next_action recovery worked without intervention.
There were zero false compile-success claims, but two false task-completion claims.

## Reproduction and limits

`chat-bench-qwen.py --suite scripts/chat-generalization-cases.json --evidence ...`
uses the existing configured provider. Keep raw evidence outside the repository.
Then run `node scripts/chat-generalization-audit.mjs EVIDENCE BINDINGS.json`.
Private bindings come from the saved native circuit, not the requested circuit:
G1 red13/green12; G2 servo9/up2/down3; G3 red5/green6/blue3/button2/ADC0;
G4 red5/yellow7/green6/buzzer8/TRIG9/ECHO10; G5 red10/green11/buzzer9/button3/PIR2;
G6 red2/yellow3/green4/button5, with `fixed_inputs.button=0` for the observed short.
The generic probe executes the independently compiled HEX under avr8js 0.21.0
at 16 MHz with timers, ADC, UART and ideal sensor/button fixtures. It records
firmware/stimulus SHA-256, transitions, samples and assertions outside Git.
Firmware/stimulus SHA-256 prefixes: G1 `9ae3e35c6e04/bea2bf62b444`,
G2 `d6631724cb8a/8eedcc2dd309`, G3 `8ea1e68675ce/6895d5345497`,
G4 `7a9a84db6428/4c247e7a5192`, G5 `d1ea59d4e411/a65b1fc14c2e`,
G6 `c3f7f92c74e1/537ad42efdc8`.
Control tests reject corrupted firmware, floating-output success, wrong pulse
duration and fixture transitions that would conceal a hard-wired net.

Observed verdict: 4/6 strict successes on previously unseen combinations,
not evidence of universal reliability. Four projects were authored without
from_example; the other two required substantial changes to existing foundations.
No exact solution recipe was added. This is one sample per project, one model,
without a paired old-chat baseline. The earlier three-call starter scores are
not comparable to these more complex projects. No physical, browser rendering,
sound-level, servo-motion, sensor-accuracy or ESP32 result is claimed.

Next priorities: check internal terminal groups and electrical nets; add general
behavioral verification before claiming task completion; reduce catalog/setup
round trips with general batch operations. Do not add six task-specific recipes.
If product changes use these findings, this suite becomes a regression set and
new unseen prompts are required to measure generalization again.

Verification: 31 agent tests, 13 chat/core tests, 182 compact MCP tests,
four benchmark-input/provenance tests and five firmware-probe tests passed.
Local server/harness cleanup was confirmed; the temporary worktree was removed.
No push, deployment, SSH or production access was performed.
