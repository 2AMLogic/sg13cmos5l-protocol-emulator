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

- **#125**: I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target
- **#208**: Build DR 0015's admitted primitives P1 (CRC/LFSR step) and P2 (NRZI + bit-stuff) in control space 0x10–0x1F
- **#214**: Submission D4: distill current verification evidence into a judge-facing write-up

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#221**: Submission D4: judge-facing verification write-up

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#20**: T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep) *(curated)*
- **#44**: Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion (DR 0004's own invalidation clause fires) *(curated)*
- **#85**: spec: fix the eight findings that stopped the two-key ratification of PR #84 (fetch model, SPI sketch, row 10 source and four other citations) *(curated)*
- **#100**: Auditor Capability Request: Python interpreter unavailable for tool-light validation *(curated)*
- **#201**: LibreLane max-slew violation on an SRAM macro input pin (A_DIN[0], then A_WEN) after the UART-load ROM re-roll *(curated)*
- **#208**: Build DR 0015's admitted primitives P1 (CRC/LFSR step) and P2 (NRZI + bit-stuff) in control space 0x10–0x1F *(curated)*
- **#211**: UART load: count byte is outside the CRC; a one-bit count flip can ACK and RUN a truncated image (DR 0013 F8) *(curated)*
- **#218**: DR 0013 layer 1 after the #166 ruling: loadseq refuses all-zero images, record the CRC-0 gap, findings 3 and 4 *(curated)*

## Proposed (Architect / Hermit)

- **#216**: Gate the Tiny Tapeout gl_test job on repository-owned XML result validation *(architect)*
- **#217**: Run protocol firmware waveform checks on the routed SDF corner sweep *(architect)*
- **#225**: Include independent host-load replay benches in the RTL CI gate *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 8 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
