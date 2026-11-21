# 0025: `supersedes` May Be a List — a Collapse Re-mint Supersedes Several Leaves at Once

Status: **Proposed 2026-11-19.** Like the other proposed records it is not
bound by the two-key (`RATIFY-KEY`) mechanism (DR
[`0006`](0006-two-key-ratification-never-ran.md)). It changes no RTL, spec
value, claim or ratified text; it widens the evidence-record schema and
changes no already-committed record.
Date: 2026-11-19
Issues: #472 (filed from the review of PR #457).

## Context

A re-mint of `signoff-baseline` emits one record per stale live leaf, and
two branches that each re-mint in parallel leave both chains live after the
merge, so the live-leaf count — and every docs PR's record diff — grows
geometrically: 8 → 16 → 32 records in one day (PR #457 carried 62 record
files and +6,526 of +6,761 diff lines for a 225-line docs change). The
measured 32 leaves are interchangeable restatements of one verdict: a
pairwise diff shows only `record_id`, `supersedes` and the timestamp
differing.

The schema allowed only a scalar `supersedes`, so one successor record
citing N superseded ids could not be expressed; the append-only rule
(nothing under `records/` is deleted or edited) is not the problem and is
unchanged.

## Decision

1. `record-meta.supersedes` accepts a record-id string, null, **or a
   non-empty list of record-id strings** (#472). Every listed id must exist
   in the same experiment, differ from the record's own id, sort strictly
   earlier than it, and appear at most once. Each entry is judged by the
   same rules as the scalar form. A malformed or repeated entry is an error.
   Valid siblings still exempt their targets.
2. Every consumer of the field treats each listed id as superseded:
   `check_records.py` (freshness exemption), `remint_records.py`
   (`live_records()`), `check_docs_records.py` (which ids a doc may cite)
   and `scripts/characterization_report.py` (which records are live).
3. `remint_records.py --collapse EXPERIMENT` mints, for the
   interchangeable-leaf experiments (`signoff-baseline` today), ONE record
   superseding every stale live leaf, so parallel re-mints converge instead
   of doubling. Other experiments keep one successor per leaf — their
   records assert genuinely distinct runs.
4. The collapse mint is bookkeeping only; it re-runs nothing. Its **Result**,
   **Run configuration** and **Design provenance** are `(fill in)` placeholders
   that `check_records.py` rejects until the operator who re-ran the experiment
   fills them in — the tool never mints a verdict it did not measure.

## Consequences

A collapse re-mint's diff is one record instead of N; the live-leaf count
of a collapsed experiment stays at one after every future re-mint. Review
of a collapse record must check the listed ids (the linter already
validates them mechanically). A record superseded by two records (one
scalar, one list) is simply superseded; no rule forbids the double naming,
and neither naming record becomes stale for it.

## Per-entry rule and guards

Every consumer (the linter, the re-minter, the docs-citation checker and the
characterization report) judges each `supersedes` entry on its own: an invalid
sibling (non-string, duplicate, unknown ID) is reported but never voids the
valid entries beside it. `check_records.effective_supersedes` is the single
implementation all four consumers share. `--collapse` compares the
complete Claim and Result bodies (continuation lines included, indented or
flush-left wrapping) and refuses to mint a second draft while an untracked one
for the same leaves is pending.

## Migration

The first collapse replaced 112 interchangeable predecessors with
[`20261120-002909-822afb0`](../../verification/records/signoff-baseline/records/20261120-002909-822afb0.md).
That run met 4 of 11 T1 items at klt 0.8.0. After the fleet grader changed,
a [separate run on main](../../verification/records/signoff-baseline/records/20261120-042002-d4b4205.md)
reproduced the 5-of-11 result of main’s 344 live records at klt 0.9.2.
The PR then refreshed the item 9 and 10 attestations. All 345 stale records
had identical input paths, Claims and Results, so `--collapse signoff-baseline`
minted [one live record](../../verification/records/signoff-baseline/records/20261120-042052-5050f25.md).
Its measured result is 5 of 11 met, with one item not applicable.

At the branch’s review revision `f5425e19` the guard refused to repeat the
collapse: the branch’s live record and main’s chain of newer leaves word the
Claim and Result differently, so the 2,761 stale leaves were not
interchangeable by the fingerprint’s definition. The operator minted the
successor
[`20261120-100345-e66478e`](../../verification/records/signoff-baseline/records/20261120-100345-e66478e.md)
by hand with the tool’s renderer, listing `5050f25` among its 2,761
superseded ids.

PR #477 took in `origin/main` at `6fb3838e7`. A fresh klt 0.9.2 run
graded that revision and found 5 of 11 items met, with item 6 not applicable.
The same Claim and Result wording difference made `--collapse signoff-baseline`
refuse the 5,521 stale records, so the Doctor wrote
[`20261120-164259-6fb3838`](../../verification/records/signoff-baseline/records/20261120-164259-6fb3838.md)
from that run. When #477 landed on `main` at `a9c989e05`, both
`docs/ROADMAP.md` and `docs/submission/verification.md` cited this baseline.
