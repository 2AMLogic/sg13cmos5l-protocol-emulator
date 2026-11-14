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
- **#396**: Draft the decision record for the T1 item 4 (LVS) evidence contract authorized on #329
- **#398**: Docs: README and submission write-ups still say the klt STA leg is blocked on klayout-tools#2635 and claims nothing
- **#400**: docs/info.md cites 21 superseded evidence records; check_docs_records.py only runs over docs/submission

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction

## In Progress

Issues currently being built (`loom:building`).

- **#371**: chore: pin a klt containing request.macros (PR #2645) and re-mint the records it stales

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#395**: docs: roadmap as of 2026-11-13
- **#399**: build: track the fleet klayout-tools version instead of pinning one, and delete the re-mint loop that enforced the pin

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#261**: LibreLane: max-cap on SRAM A_DOUT[5..6] is avoided by placement, not by construction *(curated)*
- **#262**: Re-run the firmware gate-level suite on the post-#258 I2C images *(curated)*
- **#265**: PR #263: netlist-dependent evidence re-mint for the A_DOUT buffers (#261) before merge *(curated)*
- **#273**: Ask the organizers: must info.yaml set tiles to 6x4, or is 2x2 accepted? (ratified row 7 vs the post's instruction) *(curated)*
- **#278**: Re-stamp SG13CMOS5L PDK pin from klayout-tools (IHP-Open-PDK dev f7bca326) *(curated)*
- **#324**: Delete verification/_dut.py and stale _dut docstrings at next post-layout-sdf-regression / reset-pin-through re-mint *(curated)*
- **#329**: T1 item 4: re-run klt lvs against the gate-level reference now that klayout-tools#2941 is closed *(curated)*
- **#348**: T1 item 6 (Monte Carlo): record "not applicable" as a hash-bound statement covering every ratified spec row *(curated)*
- **#360**: T1 item 3 (DRC clean): resolve the 4,484 nwell findings in the SRAM macro under the klt 0.8.0 deck *(curated)*
- **#365**: T1 item 3: apply foundry-cell DRC exception for the SRAM macro once klt releases grading *(curated)*
- **#371**: chore: pin a klt containing request.macros (PR #2645) and re-mint the records it stales *(curated)*
- **#396**: Draft the decision record for the T1 item 4 (LVS) evidence contract authorized on #329 *(curated)*
- **#398**: Docs: README and submission write-ups still say the klt STA leg is blocked on klayout-tools#2635 and claims nothing *(curated)*

## Proposed (Architect / Hermit)

- **#304**: Verification: I2C pad model has no pull-up rise time, so fixed-count firmware margins are graded as if t_r = 0 *(architect)*
- **#401**: Simplify scripts/check_protocol_pin_roles.py: 10 undeclared instance attributes make the Checker order-dependent *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 6 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 0 |
| Curated | 13 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
