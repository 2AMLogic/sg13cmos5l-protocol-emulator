# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-19T14:58:25Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#399**: build: track the fleet klayout-tools version instead of pinning one, and delete the re-mint loop that enforced the pin

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(held)*

## Important

`loom:important`; taken before unlabelled work.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction
- **#272**: Firmware: Fast-mode I2C t_LOW has zero margin (65 cycles = 1.30 µs) — move slack from the high phase *(held)*
- **#273**: Ask the organizers: must info.yaml set tiles to 6x4, or is 2x2 accepted? (ratified row 7 vs the post's instruction) *(held)*
- **#275**: Re-run firmware gate-level and post-layout SDF regression on the 70/55 Fast-mode I2C image (#272) *(held)*

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction
- **#445**: Firmware: DMX512 on the existing ISA (multi-protocol extra credit)

## In Progress

Issues currently being built (`loom:building`).

- **#371**: chore: pin a klt containing request.macros (PR #2645) and re-mint the records it stales
- **#443**: Docs: protocol catalog (docs/protocols.md), every candidate protocol ranked by sourced demand and fit
- **#444**: Firmware: MIDI on the existing ISA (multi-protocol extra credit)
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit)
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit)
- **#448**: Firmware: NEC infrared on the existing ISA (multi-protocol extra credit)
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit)
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit)
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit)
- **#452**: Firmware: SWD probe on the existing ISA (multi-protocol extra credit)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#399**: build: track the fleet klayout-tools version instead of pinning one, and delete the re-mint loop that enforced the pin — closes #371

## Proposed

Issues carrying `loom:curated`.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction *(curated)*
- **#262**: Re-run the firmware gate-level suite on the post-#258 I2C images *(curated)* *(held)*
- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(curated)* *(held)*
- **#273**: Ask the organizers: must info.yaml set tiles to 6x4, or is 2x2 accepted? (ratified row 7 vs the post's instruction) *(curated)* *(held)*
- **#278**: Re-stamp SG13CMOS5L PDK pin from klayout-tools (IHP-Open-PDK dev f7bca326) *(curated)* *(held)*
- **#324**: Delete verification/_dut.py and stale _dut docstrings at next post-layout-sdf-regression / reset-pin-through re-mint *(curated)* *(held)*
- **#329**: T1 item 4: re-run klt lvs against the gate-level reference now that klayout-tools#2941 is closed *(curated)* *(held)*
- **#348**: T1 item 6 (Monte Carlo): record "not applicable" as a hash-bound statement covering every ratified spec row *(curated)* *(held)*
- **#360**: T1 item 3 (DRC clean): resolve the 4,484 nwell findings in the SRAM macro under the klt 0.8.0 deck *(curated)* *(held)*
- **#365**: T1 item 3: apply foundry-cell DRC exception for the SRAM macro once klt releases grading *(curated)* *(held)*
- **#371**: chore: pin a klt containing request.macros (PR #2645) and re-mint the records it stales *(curated)*
- **#435**: Ratification gate on merge_group: a batched queue group attributes flips to one PR's reviews *(curated)* *(held)*
- **#443**: Docs: protocol catalog (docs/protocols.md), every candidate protocol ranked by sourced demand and fit *(curated)*
- **#444**: Firmware: MIDI on the existing ISA (multi-protocol extra credit) *(curated)*
- **#445**: Firmware: DMX512 on the existing ISA (multi-protocol extra credit) *(curated)*
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit) *(curated)*
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit) *(curated)*
- **#448**: Firmware: NEC infrared on the existing ISA (multi-protocol extra credit) *(curated)*
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit) *(curated)*
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit) *(curated)*
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit) *(curated)*
- **#452**: Firmware: SWD probe on the existing ISA (multi-protocol extra credit) *(curated)*

## Proposed (Architect / Hermit)

- **#304**: Verification: I2C pad model has no pull-up rise time, so fixed-count firmware margins are graded as if t_r = 0 *(architect)* *(held)*
- **#404**: Dedupe the two single-protocol gate-level runners: 78 of 82 body lines are identical *(hermit)* *(held)*
- **#405**: flow/: run-ps2-gate-level.sh and run-ws2812-gate-level.sh are 74 of 80 executable lines identical — consolidate, or record why not *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 4 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 2 |
| In Progress (`loom:building`) | 10 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 22 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
