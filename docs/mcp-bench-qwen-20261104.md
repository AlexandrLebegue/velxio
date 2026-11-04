# Real Qwen MCP regression cycles — 2026-11-04

Scope: local workbench only, no SSH, deployment or production access. Global
OpenCode 1.19.3 provider `hyperqwen/qwen3.8-27b` is inherited without copying keys.
Each fresh session receives one natural prompt and identical neutral AGENTS.md;
no coaching or retries. Runs are sequential and time out after 12 minutes.

Cycle 0: removed named wiring (`1e36e2d1`); native start/end wires retained.
Validation: 31 agent tests and 168 compact MCP tests passed before AVR additions.
ESP32 templates, e-paper example and original IDF/offline route are retained.

AVR setup: opt-in genuine REST-owner lane with installed CLI/core/library hash
proofs, closed dependency sources, actual compile and firmware artifacts. No
compiler fixture or test-only adapter. The existing ESP32 startup inventory is
unchanged. Local AVR recipes are trusted; no OS network-isolation claim is made.

The benchmark imports the previous A/B instrumentation, records provider HTTP
bodies once (never authorization headers), and compares them with OpenCode and
MCP arguments. Raw logs and local paths stay outside Git.
Strict success needs an independent recompile and a source/version-bound manual
review of wiring, exact values and code behavior. Compilation does not validate
pixels, LED timing, servo motion or hardware sensor accuracy.

| Pass | Case | MCP calls | Errors by code | Strict success | Final build read |
| --- | --- | ---: | --- | --- | --- |
| 1 | B1–B5 | pending | pending | pending | pending |

Stop criterion: all five AVR cases succeed with at most three MCP errors each
on two consecutive complete passes, then two unused holdout formulations.
No Qwen pass has yet been measured. A genuine HTTP/MCP admission control
returned state=done, success=true, test_only=false, with a 1265-byte HEX artifact.
Validation after the AVR addition: 31 agent and 171 compact MCP tests passed.

B6 is prepared separately (ESP32 + 1.54-inch monochrome e-paper, centered exact
"Hello World"). Its expected native pins are CS5/DC17/RST16/BUSY4/SCK18/SDI23,
3V3 and GND. Run it alone with `--cases B6 --mcp-url <explicit URL>` on the
remote owner's IDF host; independent IDF verification is still required there.
B6 does not enter the local five-case score. It is not executed locally.

Entry point: `scripts/mcp-bench-qwen.py pass`; use `--help` for installed cache,
real inventory, revision, evidence directory and optional HTTP tracing arguments.
The two holdouts are defined separately and will not be used for tuning.
