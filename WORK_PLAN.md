# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#229**: Include independent host-load replay benches in the RTL CI gate

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target

## In Progress

Issues currently being built (`loom:building`).

- **#217**: Run protocol firmware waveform checks on the routed SDF corner sweep

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#229**: Include independent host-load replay benches in the RTL CI gate

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#85**: spec: fix the eight findings that stopped the two-key ratification of PR #84 (fetch model, SPI sketch, row 10 source and four other citations) *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*
- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target *(curated)*
- **#211**: UART load: count byte is outside the CRC; a one-bit count flip can ACK and RUN a truncated image (DR 0013 F8) *(curated)*
- **#217**: Run protocol firmware waveform checks on the routed SDF corner sweep *(curated)*
- **#235**: Row 13 stretch: a protocol in a role or pin direction the core protocols never use (PS/2, SWD target, MDIO PHY side) *(curated)*

## Proposed (Architect / Hermit)

- **#230**: Submission D2: write the judge-facing architecture and ISA document *(architect)*
- **#231**: Pin tt-gds-action to a commit SHA and lint against floating refs (submission risk R2) *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 8 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
