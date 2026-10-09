# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#127**: formal: pin_write_latency on the real core (verification-plan 2.2)

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#109**: Decision record: admit or defer the stretch protocols (low-speed USB, 10BASE-T) against the ISA cycle budget — row 2's entry condition is unevaluated

## In Progress

Issues currently being built (`loom:building`).

_None._

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#127**: formal: pin_write_latency on the real core (verification-plan 2.2)

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*
- **#109**: Decision record: admit or defer the stretch protocols (low-speed USB, 10BASE-T) against the ISA cycle budget — row 2's entry condition is unevaluated *(curated)*
- **#116**: Formal: complete deferred pin_write_latency checks on the real core outputs *(curated)*

## Proposed (Architect / Hermit)

- **#118**: Host-side program loader: generate the load-phase pin sequence from firmware images for a physical Tiny Tapeout board (none exists) *(architect)*
- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target *(architect)*
- **#115**: Dedupe bench bootstrap helpers in verification/ (5x _find_repo_root, 4x parse_cycle_sections) *(hermit)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 0 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 5 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
