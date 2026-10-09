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

- **#131**: Verification: prove every flop reaches a known state from rst_n alone (gate-level X/random-init run; post-deselect safe idle)
- **#136**: Verification: silicon-true uio pad model; re-run I2C evidence through the real uio_oe (today silicon cannot drive an I2C line)
- **#137**: DR 0013 layer 1: expose PM_CRC on uo_out during serial load so the host can verify before running
- **#138**: DR 0013 layer 2: boot ROM + fetch-source switch + warm start; MODE-low no longer runs uninitialized SRAM (row 14c)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#163**: test: run the I2C evidence through the real uio_oe on a silicon-true pad model

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*

## Proposed (Architect / Hermit)

- **#118**: Host-side program loader: generate the load-phase pin sequence from firmware images for a physical Tiny Tapeout board (none exists) *(architect)*
- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target *(architect)*
- **#152**: Verification: independent ISA reference simulator with lockstep co-simulation against the core RTL *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 4 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 3 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
