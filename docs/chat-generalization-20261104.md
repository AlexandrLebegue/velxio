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

Results are pending. Failures and false completion claims will remain in the
report. If outcomes motivate product changes, this suite becomes a regression
set; a new unseen set is required before claiming generalization again.
