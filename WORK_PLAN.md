# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#116**: Formal: complete deferred pin_write_latency checks on the real core outputs

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#96**: Firmware: UART receive path and low-baud (9600) with RX bench (rows 1, 10)

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*

## Proposed (Architect / Hermit)

- **#109**: Decision record: admit or defer the stretch protocols (low-speed USB, 10BASE-T) against the ISA cycle budget — row 2's entry condition is unevaluated *(architect)*
- **#118**: Host-side program loader: generate the load-phase pin sequence from firmware images for a physical Tiny Tapeout board (none exists) *(architect)*
- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target *(architect)*
- **#115**: Dedupe bench bootstrap helpers in verification/ (5x _find_repo_root, 4x parse_cycle_sections) *(hermit)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 3 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
