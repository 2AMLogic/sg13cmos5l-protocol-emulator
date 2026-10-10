# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#167**: feat: show PM_CRC on uo_out during the serial load so the host can verify before running (DR 0013 layer 1)
- **#172**: feat: fail lint on a new file with an absolute home-directory path

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#83**: signoff: bind T1 items 1, 2, 9 and 10 to audited artifacts (klayout-tools#2718 landed)
- **#139**: Boot firmware: UART load over the demo board's USB bridge (TT option B pins) with an independent host model

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#167**: feat: show PM_CRC on uo_out during the serial load so the host can verify before running (DR 0013 layer 1)
- **#172**: feat: fail lint on a new file with an absolute home-directory path

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#83**: signoff: bind T1 items 1, 2, 9 and 10 to audited artifacts (klayout-tools#2718 landed) *(curated)*
- **#85**: spec: fix the eight findings that stopped the two-key ratification of PR #84 (fetch model, SPI sketch, row 10 source and four other citations) *(curated)*
- **#86**: Two committed LVS error records contain an absolute home-directory path *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*

## Proposed (Architect / Hermit)

- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target *(architect)*
- **#192**: Verification: add UART RX to the constrained-random regression and gate-level firmware run *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 6 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
