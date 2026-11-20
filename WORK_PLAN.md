# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-20T05:26:39Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#497**: spec: reconcile gap-digest rows 7 and 11 with the burst evidence and the closed macro gap

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(held)*

## Important

`loom:important`; taken before unlabelled work.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction
- **#272**: Firmware: Fast-mode I2C t_LOW has zero margin (65 cycles = 1.30 µs) — move slack from the high phase *(held)*
- **#273**: Adopt the contest’s 8×4 submission allocation and supersede the 2×2 layout evidence *(held)*
- **#275**: Re-run firmware gate-level and post-layout SDF regression on the 70/55 Fast-mode I2C image (#272) *(held)*

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit)
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit)
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit)

## In Progress

Issues currently being built (`loom:building`).

- **#389**: Follow-up to #371: die-area P&R (ORD-2013 / request.macros) and die-area-baseline re-mint
- **#397**: gap-to-submission: reconcile rows 7 and 11 with the #286 burst evidence and the closed klayout-tools#2635
- **#403**: signoff baseline: name the tiers-doc (source_doc_content_hash) movement when the klt version moves, as the 0.8.0->0.9.0 refresh did not
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit)
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit)
- **#452**: Firmware: SWD probe on the existing ISA (multi-protocol extra credit)
- **#460**: CI flake: gds `viewer` job intermittently fails deploying to Pages ("No artifacts named github-pages")
- **#464**: Ratify the 8×4 submission allocation and verify it with the main-template precheck
- **#472**: Evidence hygiene: signoff-baseline leaf count doubles on every concurrent merge (8 to 16 to 32 in one day)
- **#486**: Share the program-memory pin driver across the load-phase and assembler round-trip benches
- **#488**: firmware: NEC infrared RX decode from the demodulating receiver module (follow-up to #448)
- **#502**: Show checklist wording changes reported by klt in signoff --check-latest

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#483**: feat(spec): adopt the 8x4 allocation the rules set (DR 0026, two-key gate) on the template main flow
- **#498**: feat(signoff): add --diff-vs non-graded movement comparison for baseline refreshes
- **#501**: firmware: SWD debug probe on the frozen ISA (issue #452)
- **#505**: fix: report klt checklist-wording movement in signoff --check-latest

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#495**: fix(flow): declare the program-memory SRAM macro in the die-area P&R request and record the first measured die area — closes #389
- **#497**: spec: reconcile gap-digest rows 7 and 11 with the burst evidence and the closed macro gap — closes #397

## Proposed

Issues carrying `loom:curated`.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction *(curated)*
- **#262**: Re-run the firmware gate-level suite on the post-#258 I2C images *(curated)* *(held)*
- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(curated)* *(held)*
- **#324**: Delete verification/_dut.py and stale _dut docstrings at next post-layout-sdf-regression / reset-pin-through re-mint *(curated)* *(held)*
- **#329**: T1 item 4: re-run klt lvs against the gate-level reference now that klayout-tools#2941 is closed *(curated)* *(held)*
- **#365**: T1 item 3: apply foundry-cell DRC exception for the SRAM macro once klt releases grading *(curated)* *(held)*
- **#389**: Follow-up to #371: die-area P&R (ORD-2013 / request.macros) and die-area-baseline re-mint *(curated)*
- **#397**: gap-to-submission: reconcile rows 7 and 11 with the #286 burst evidence and the closed klayout-tools#2635 *(curated)*
- **#403**: signoff baseline: name the tiers-doc (source_doc_content_hash) movement when the klt version moves, as the 0.8.0->0.9.0 refresh did not *(curated)*
- **#435**: Ratification gate on merge_group: a batched queue group attributes flips to one PR's reviews *(curated)* *(held)*
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit) *(curated)*
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit) *(curated)*
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit) *(curated)*
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit) *(curated)*
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit) *(curated)*
- **#452**: Firmware: SWD probe on the existing ISA (multi-protocol extra credit) *(curated)*
- **#460**: CI flake: gds `viewer` job intermittently fails deploying to Pages ("No artifacts named github-pages") *(curated)*
- **#464**: Ratify the 8×4 submission allocation and verify it with the main-template precheck *(curated)*
- **#472**: Evidence hygiene: signoff-baseline leaf count doubles on every concurrent merge (8 to 16 to 32 in one day) *(curated)*
- **#481**: docs(spec): spec/statistical-claims-na.md still says "the pinned klayout-tools==0.8.0" after #371 removes the pin *(curated)*
- **#488**: firmware: NEC infrared RX decode from the demodulating receiver module (follow-up to #448) *(curated)*
- **#502**: Show checklist wording changes reported by klt in signoff --check-latest *(curated)*

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
| Ready (`loom:issue`, net of holds/building/merge-pending) | 3 |
| In Progress (`loom:building`) | 12 |
| PRs awaiting review | 4 |
| Approved PRs awaiting merge | 2 |
| Curated | 22 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
