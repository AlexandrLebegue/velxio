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
