# spec

Ratified specification and decision records.

- `target-spec.md` — the checkable target table (Status: **RATIFIED**
  since 2026-09-21 via the program's two-key mechanism:
  `decision-records/0004-target-spec-ratification.md` is the ratification
  record, and each row's ratified state is explicit in the table's State
  column).
- `decision-records/` — numbered decision records (0001-isa.md and up),
  including `0004-target-spec-ratification.md` — the per-row register and
  binding record of the 2026-09-21 ratification.
- `verification-plan.md` — what is verified and how, including the formal
  properties, constrained-random suites, and reference models.
- `gap-to-submission.md` — every spec row and template checklist item
  against current status, tracked against the 2027-01-18 deadline.

**How ratification works here.** Ratification of this spec runs through the
program's two-key (RATIFY-KEY) mechanism, installed in this repo at
[`ratification/ee-key/`](../ratification/ee-key/SKILL.md) and
[`ratification/market-key/`](../ratification/market-key/SKILL.md) (2026-09-21):
an EE key and a market key, **neither held by the ratifying PR's author
or the design's author**, each post one PR review opening with a
`RATIFY-KEY` marker line (the grammar lives in each skill's "Output
format" section); the second key-holder's application releases the PR
(`loom:auto-merge-ok`), and **the merge commit is the ratification
record**. Pipeline approvals (Judge, Champion) are quality gates, not
keys — they never substitute for one.

See issue #1 for how this surface came to exist.
