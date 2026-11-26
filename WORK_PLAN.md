# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#497**: spec: reconcile gap-digest rows 7 and 11 with the burst evidence and the closed macro gap
- **#538**: feat: post-route klt sta corner sweep over the flow-of-record DEF/SPEF
- **#543**: firmware, bench, spec, records: NEC infrared RX decoder on the frozen ISA

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge

## Important

`loom:important`; taken before unlabelled work.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction
- **#272**: Firmware: Fast-mode I2C t_LOW has zero margin (65 cycles = 1.30 µs) — move slack from the high phase
- **#273**: Adopt the contest’s 8×4 submission allocation and supersede the 2×2 layout evidence
- **#275**: Re-run firmware gate-level and post-layout SDF regression on the 70/55 Fast-mode I2C image (#272)
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit)
- **#500**: Firmware: SWD probe AP memory-word read via the table-driven write shape (follow-up to #452)
- **#529**: Formal: re-prove no_data_dependent_latency on a second engine and model the serial-load shift-in (characterization row 3)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#397**: gap-to-submission: reconcile rows 7 and 11 with the #286 burst evidence and the closed klayout-tools#2635
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit)
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit)
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit)
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit)
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit)
- **#460**: CI flake: gds `viewer` job intermittently fails deploying to Pages ("No artifacts named github-pages")
- **#464**: Ratify the 8×4 submission allocation and verify it with the main-template precheck
- **#488**: firmware: NEC infrared RX decode from the demodulating receiver module (follow-up to #448)
- **#500**: Firmware: SWD probe AP memory-word read via the table-driven write shape (follow-up to #452)
- **#520**: remint_records --collapse: three continuation shapes escape the interchangeable-leaf field comparison
- **#522**: T1 item 5: produce a post-route klt sta corner sweep (real clock tree, parasitics, complete IO constraints) as the klt timing evidence row 4 and DR 0007 are waiting on
- **#524**: T1 item 8: map failing characterization rows to open evidence issues or ratification waits
- **#529**: Formal: re-prove no_data_dependent_latency on a second engine and model the serial-load shift-in (characterization row 3)
- **#531**: UART: measure bit period and per-frame drift in time units from the SDF-annotated post-route netlist (characterization row 10)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#483**: feat(spec): adopt the 8x4 allocation the rules set (DR 0026, two-key gate) on the template main flow
- **#534**: fix: refuse ambiguous field continuations during record collapse
- **#537**: firmware: CAN 2.0A node on the frozen ISA (arbitrated TX, RX with CRC-15 and ACK)
- **#539**: measure UART TX bit period and per-frame drift in time units from the SDF post-route netlist (row 10)
- **#541**: firmware: Modbus RTU server on the frozen ISA
- **#572**: firmware: table-driven SWD probe reads one AP memory word

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#497**: spec: reconcile gap-digest rows 7 and 11 with the burst evidence and the closed macro gap
- **#532**: feat: map every failing characterization row to an open owner or ratification wait
- **#538**: feat: post-route klt sta corner sweep over the flow-of-record DEF/SPEF
- **#543**: firmware, bench, spec, records: NEC infrared RX decoder on the frozen ISA

## Proposed

Issues carrying `loom:curated`.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction *(curated)*
- **#262**: Re-run the firmware gate-level suite on the post-#258 I2C images *(curated)*
- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(curated)*
- **#324**: Delete verification/_dut.py and stale _dut docstrings at next post-layout-sdf-regression / reset-pin-through re-mint *(curated)*
- **#329**: T1 item 4: re-run klt lvs against the gate-level reference now that klayout-tools#2941 is closed *(curated)*
- **#365**: T1 item 3: apply foundry-cell DRC exception for the SRAM macro once klt releases grading *(curated)*
- **#397**: gap-to-submission: reconcile rows 7 and 11 with the #286 burst evidence and the closed klayout-tools#2635 *(curated)*
- **#435**: Ratification gate on merge_group: a batched queue group attributes flips to one PR's reviews *(curated)*
- **#446**: Firmware: Modbus RTU on the existing ISA (multi-protocol extra credit) *(curated)*
- **#447**: Firmware: 1-Wire on the existing ISA (multi-protocol extra credit) *(curated)*
- **#449**: Firmware: DALI on the existing ISA (multi-protocol extra credit) *(curated)*
- **#450**: Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit) *(curated)*
- **#451**: Firmware: I2S on the existing ISA (multi-protocol extra credit) *(curated)*
- **#460**: CI flake: gds `viewer` job intermittently fails deploying to Pages ("No artifacts named github-pages") *(curated)*
- **#464**: Ratify the 8×4 submission allocation and verify it with the main-template precheck *(curated)*
- **#488**: firmware: NEC infrared RX decode from the demodulating receiver module (follow-up to #448) *(curated)*
- **#500**: Firmware: SWD probe AP memory-word read via the table-driven write shape (follow-up to #452) *(curated)*
- **#520**: remint_records --collapse: three continuation shapes escape the interchangeable-leaf field comparison *(curated)*
- **#522**: T1 item 5: produce a post-route klt sta corner sweep (real clock tree, parasitics, complete IO constraints) as the klt timing evidence row 4 and DR 0007 are waiting on *(curated)*
- **#524**: T1 item 8: map failing characterization rows to open evidence issues or ratification waits *(curated)*
- **#529**: Formal: re-prove no_data_dependent_latency on a second engine and model the serial-load shift-in (characterization row 3) *(curated)*
- **#530**: Program storage: measured silicon load/readback at a recorded clock (characterization row 6 evidence half) *(curated)*
- **#531**: UART: measure bit period and per-frame drift in time units from the SDF-annotated post-route netlist (characterization row 10) *(curated)*

## Proposed (Architect / Hermit)

- **#304**: Verification: I2C pad model has no pull-up rise time, so fixed-count firmware margins are graded as if t_r = 0 *(architect)*
- **#404**: Dedupe the two single-protocol gate-level runners: 78 of 82 body lines are identical *(hermit)*
- **#405**: flow/: run-ps2-gate-level.sh and run-ws2812-gate-level.sh are 74 of 80 executable lines identical — consolidate, or record why not *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 3 |
| Very important | 1 |
| Important | 7 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 15 |
| PRs awaiting review | 6 |
| Approved PRs awaiting merge | 4 |
| Curated | 23 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
