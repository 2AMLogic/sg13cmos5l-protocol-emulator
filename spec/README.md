# spec

Proposed specification and decision records.

> **2026-09-26: nothing in this directory is ratified.** The two-key
> (`RATIFY-KEY`) mechanism described below has never run — not on any PR in
> this repository's history — so the 2026-09-21 `Ratified`/`RATIFIED` claims
> were assertions rather than acts, and every one of them has been reconciled
> to `Proposed`. The finding of fact, the per-file reconciliation table, and
> what is required to actually close this out are in
> [`decision-records/0006-two-key-ratification-never-ran.md`](decision-records/0006-two-key-ratification-never-ran.md).
> **No spec content changed** — only the claim that it binds. The missing
> enforcement hook that allowed the gap is issue #45.

- `target-spec.md` — the checkable target table (Status: **PROPOSED — not
  ratified**; each row's proposed binding and its met/unmet evidence state
  are in the table's State column, registered per row in
  `decision-records/0004-target-spec-ratification.md`).
- `decision-records/` — numbered decision records (0001-isa.md and up),
  including `0004-target-spec-ratification.md` — the per-row register and
  *proposed* binding record of 2026-09-21, whose own invalidation clause
  fired, and `0006-two-key-ratification-never-ran.md`, which records that it
  did.
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

**Status vocabulary.** A record's `Status:` line is one of: `DRAFT` (a
surface still being written), `Proposed` (complete, awaiting the two-key act),
`Ratified` (the act ran — two `RATIFY-KEY` reviews on a named carrying PR,
cited with that PR's merge commit), or `Recorded` (a finding of fact plus the
mechanical consequence another record already prescribed for it; decides and
binds nothing, so nothing in it needs ratifying —
`0006-two-key-ratification-never-ran.md` is the only such record). A record
needs ratification when it **decides** something, not when it **observes**
something. Nothing writes `Ratified` on the strength of a process description:
the line must cite the carrying PR and its merge commit, and that PR's
`/pulls/<N>/reviews` must actually show the two markers —
`gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/<N>/reviews --jq
'[.[]|select(.body|test("RATIFY-KEY"))]|length'` is the check, and it is
currently `0` for every PR in the repo. **This is not yet enforced anywhere
mechanically** (issue #45); until it is, it is a convention a reader can
verify in one command, which is the next best thing.

See issue #1 for how this surface came to exist, and DR 0006 for why the act
it describes had not happened as of 2026-09-26.
