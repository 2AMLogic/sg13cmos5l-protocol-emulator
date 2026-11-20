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
   same rules as the scalar form, per entry: a bad entry is an error and
   exempts its own target only; valid siblings still exempt theirs.
2. Every consumer of the field treats each listed id as superseded:
   `check_records.py` (freshness exemption), `remint_records.py`
   (`live_records()`), `check_docs_records.py` (which ids a doc may cite)
   and `scripts/characterization_report.py` (which records are live).
3. `remint_records.py --collapse EXPERIMENT` mints, for the
   interchangeable-leaf experiments (`signoff-baseline` today), ONE record
   superseding every stale live leaf, so parallel re-mints converge instead
   of doubling. Other experiments keep one successor per leaf — their
   records assert genuinely distinct runs.
4. The collapse mint is bookkeeping only; it re-runs nothing. Its
   **Result** and **Run configuration** are `(fill in)` placeholders that
   `check_records.py` rejects until the operator who re-ran the experiment
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
implementation the linter and re-minter share. `--collapse` compares the
complete Claim and Result bodies (continuation lines included, indented or
flush-left wrapping) and refuses to mint a second draft while an untracked one
for the same leaves is pending.

## Done

The migration is complete: the 112 live `signoff-baseline` predecessors on this
branch (one distinct full Claim and Result among them) are superseded by one
live record, `20261120-002909-822afb0`. Adding further experiments to the
collapsible set remains future work (each needs the interchangeability evidence
this record's guards enforce).
