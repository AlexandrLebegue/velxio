# Chat libraries, wiring and automatic synchronization — 2026-11-04

This evaluates the actual integrated chat, not direct hand-authored tool calls
presented as model results. Product baseline: `9d135ab5`; frozen regression
inputs/driver limits: `a1124af0`. One complete natural French prompt per new
conversation, real Qwen `qwen3.8-27b`, sequential only, 20 steps/300 seconds.
No solution recipe, prompt coaching or component API extraction was added.
Raw settings, logs, snapshots and compiler artifacts stay outside Git.

## Baseline

| Case | Task | MCP calls | RPC errors | Seconds | Independent compile | Audit |
| --- | --- | ---: | --- | ---: | --- | --- |
| L1 | Add servo to existing Uno, hold 45 degrees | 4 | 0 | 44.96 | OK | Source/pins consistent |
| L2 | Nano potentiometer controls servo | 8 | 0 | 63.95 | OK | Source/pins consistent |
| L3 | Uno DHT22 + OLED, readings every 2 seconds | 6 | 0 | 68.57 | OK | Display/sensor runtime unverified |
| L4 | Uno distance sensor + I2C LCD + buzzer | 15 | dependency_absent: 2 | 167.21 | OK | Dependency workaround; not a functional success |

Every run read its final real build. The local toolchain already contained eight
user libraries plus core libraries, unlike the running instance. Four green
compiles therefore do not establish that the user's deployment was healthy.
L4 initially declared a library name the inventory did not recognize. After two
dependency errors Qwen replaced the LCD library with a handwritten driver. This
is not accepted as proof of displayed output, despite successful compilation.

## Running-instance checks

The served frontend bundle matched the baseline bundle byte-for-byte. Read-only
library enumeration showed ESP32/RP2040 servo libraries but no AVR `Servo`.
The user's Arduino case therefore had a real missing dependency. `Servo 1.3.0`
was installed through the existing application's library manager API, respecting
that API's policy. A separate tiny Uno servo sketch then compiled through the
real REST compiler and returned actual HEX firmware. It does not prove motion.
This dependency repair is the only application-state change made on that host.
No application image, source deployment, existing user conversation or key was
changed. Test conversations/settings used a fresh isolated browser owner.

The first browser attempt was blocked by the normal news modal before a prompt;
the runner was corrected to dismiss it through its Close button. The next real
UI attempt sent one prompt but failed creating a new OpenCode conversation
with HTTP 400, before any model/tool activity. It is a harness-start failure,
not a Qwen-quality sample. Existing-user sessions were not inspected or changed.

## Cycle 1: automatic synchronization

Both sides previously rejected the entire next edit when snapshot hashes differed,
even for independent component layout/property edits. Internal editor callbacks
also shared the 24 KiB model-output limit, although native projects may be 2 MiB.

Changes: shared three-way merge semantics with cross-language fixtures; stable
entity/file identities; automatic idle reconciliation/acknowledgement before and
after turns; safe reconnect restoration; serialized editor work; project-switch
cancellation; latest manual edits win overlapping idle updates while previous
agent drafts remain in immutable history. Active true overlaps identify fields
instead of requiring manual server synchronization. The editor reports its real
post-compile revision, including automatically inferred library declarations.
Object key order cannot trigger a false board replacement. Read-only references
do not fail because the editor moved ahead. Internal callbacks have a separate
8 MiB bounded budget; model replies remain bounded to 24 KiB.

Validation: 69 deterministic agent tests and 47 frontend agent tests; shared
merge fixtures include independent edits, deletion, concurrent additions, source
overlap, library inference and measured wire coordinates. A 64 KiB editor
callback is accepted. New source-file edits remain intact during circuit edits.
The production frontend bundle builds. Repository-wide typecheck has pre-existing
failures; no diagnostics reference the changed chat files.

Library resolution and the application-native compile path are the next cycle.
No success rate for the corrected chat is claimed before fresh model replays.

## Cycle 2 candidate: native editor regression and library/compile path

The frozen cycle-1 bundle was replayed in the actual local editor, with real
OpenCode, Qwen and compiler: L1 took 12 MCP calls, six failed steps and 173.30 s.
Five manifest edits incorrectly returned `edit_conflict`; one compile lacked
`Servo.h`. Qwen then used software pulses instead of repairing the dependency.
This is a failed dependency regression, not a successful servo validation.

Root cause: native editor snapshots retain optional properties as `undefined`,
whereas JSON omits those properties. The three-way merge mistook absence versus
`undefined` for a user edit. The candidate normalizes all three snapshots to
JSON before merging. It also preserves explicitly empty manifests and updates
board metadata without recreating the MCU unless board identity/kind changes.

Chat compile-only requests now use the application's real compiler and owner
policy, like the toolbar, rather than the separate compact offline build lane.
Imports select canonical installed library names and transitive dependencies.
Exact pins are retained; core libraries are not invented as user packages.
Missing unique registry identities use the existing managed Library API and its
owner checks, then verify installed headers. Unknown/ambiguous imports are not
guessed. Source text is never rewritten to bypass dependencies. Component
references identify related libraries as candidates, not requirements.
The external compact MCP and its offline AVR/ESP32 build paths are unchanged.
Pending application builds are polled without restarting; late results after
source/configuration changes or cancellation never overwrite current firmware.
Fresh model replay results are pending; deterministic success is not a model
quality result.

The first native-editor cycle-2 replays produced L1: 4 calls/0 errors/61.94 s,
L2: 7/0/75.41 s, L3: 9/1 MCP error plus 1 denied native read/129.82 s.
L1 started without Servo installed: the existing managed API installed Servo
1.3.0, and the real application compiler produced firmware using `Servo.h`.
Independent recompilation passed for L1/L2. An independent AVR firmware probe
also measured L1's ~1007.5 us servo pulse and L2's ~543.4/1471.6/2399.4 us
pulses at low/mid/high analog input. This verifies generated pin signals, not
rendered motor movement. L3 eventually compiled after choosing an alternative
OLED library; display and sensor runtime remain unverified.

L3 exposed a useful generic correction: the model wrote `#include <U8g2.h>`,
but the installed package exports `U8g2lib.h`. Missing-header errors now return
bounded, verified public header names and direct the model to edit the include,
instead of switching drivers or reading private server directories. No include
is automatically rewritten. Tool/system descriptions explain automatic import
resolution and distinguish optional library candidates from requirements.
