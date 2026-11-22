# Wave 3 — Commercial native embed PoC (gates only)

Wave 1–2 (MMB2 data + analysis text/dll TEMP, Nuitka `--module`, BUILD carry-forward)
are the **shipping** defense posture. This document is the **next** milestone only
after a Wave 2 portable release is stable in the field.

## Goal

Evaluate whether selected `.pyd` / analysis DLLs can live **inside** a protected
Windows binary without unpacking to a sibling folder (disk hide stronger than TEMP).

## Candidate stack

1. Nuitka Commercial: `data-hiding`, optional `dll-embedding`
2. If still insufficient: **Nuitka VM + Themida / WinLicense XBundler**
   (“Never write to disk”)

Do **not** adopt DIY MemoryModule as the product default loader.

## Compat gates (all must pass before any production switch)

| Gate | Pass criteria |
|------|----------------|
| WinNotify + analysis DLLs | Monitor / print_state / mapId / body_pose work after protect |
| Party websocket | Multi-process leader/member still connects |
| License / Soft DeviceKey | OOB activate + offline reload unchanged |
| Incremental vs full rebuild | Document whether incremental_release still applies |
| AV / SmartScreen | Clean run on a fresh Windows 10/11 laptop |
| Startup time | Within acceptable delta vs Wave 2 portable |
| Crash rate | No new hangs in 30+ min hunt smoke |

## Explicit non-goals

- Claiming “unbreakable” / memory-dump proof
- Changing login, movement, combat, HP, or MapSubsystem decision logic
- Shipping SellerData or raw CEK

## Exit

- **Pass:** write a short follow-up plan to integrate into `RELEASE_PLAYBOOK.md`
- **Fail:** keep Wave 1–2; record why in `RELEASE_BUGFIX_LOG.md` / this file
