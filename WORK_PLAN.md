# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge

## Important

`loom:important`; taken before unlabelled work.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction
- **#272**: Firmware: Fast-mode I2C t_LOW has zero margin (65 cycles = 1.30 µs) — move slack from the high phase
- **#275**: Re-run firmware gate-level and post-layout SDF regression on the 70/55 Fast-mode I2C image (#272)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction *(curated)*
- **#262**: Re-run the firmware gate-level suite on the post-#258 I2C images *(curated)*
- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(curated)*
- **#278**: Re-stamp SG13CMOS5L PDK pin from klayout-tools (IHP-Open-PDK dev f7bca326) *(curated)*
- **#324**: Delete verification/_dut.py and stale _dut docstrings at next post-layout-sdf-regression / reset-pin-through re-mint *(curated)*
- **#329**: T1 item 4: re-run klt lvs against the gate-level reference now that klayout-tools#2941 is closed *(curated)*
- **#330**: T1 item 7: find and fix why the SDF-annotated regression grades unverifiable_provenance *(curated)*
- **#348**: T1 item 6 (Monte Carlo): record "not applicable" as a hash-bound statement covering every ratified spec row *(curated)*
- **#360**: T1 item 3 (DRC clean): resolve the 4,484 nwell findings in the SRAM macro under the klt 0.8.0 deck *(curated)*

## Proposed (Architect / Hermit)

- **#304**: Verification: I2C pad model has no pull-up rise time, so fixed-count firmware margins are graded as if t_r = 0 *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 3 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 10 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
