# How AI was used to build this design

Status: written 2026-10-10 for issue #213 (submission deliverable D5),
against `main` @ `9fb7815`. Refreshed 2026-10-11 for issue #238: the record
citations, the counts and the ratification history describe `main` as of
`a9ac6940` (after PR #242's merge `72f48153`), and issue and PR states are as of that
date. Every claim below links to
a file in this repository, a pull request, or an issue. Where the text
describes how the process is *meant* to work rather than what the forge
record shows, it says so.

## Summary

AI agents (Claude, driven by the [Loom](https://github.com/rjwalters/loom)
orchestrator) wrote the specification, the decision records, the RTL, the
assembler and firmware, the testbenches and reference models, the CI checks,
and the documentation, including this file. A human operator set the
direction. The operator also made the decisions the agents were not allowed to
make, and held the credentials they did not have.

The specification is **partly ratified**, and only recently. The two-key
ratification this repository requires did not happen when it was first
claimed ([DR 0006](../../spec/decision-records/0006-two-key-ratification-never-ran.md)).
When it was first really run, both keys withheld release (PR #84). The
second act, PR #242, merged on 2026-10-11 after the EE key's `approve` and
the market key's `adequate-for-catalog` reviews at its head: it ratified the
target spec's rows 1-12 (as DR 0004 registers them) and DRs 0001-0004
([DR 0009](../../spec/decision-records/0009-two-key-ratification-act.md)).
Rows 13 and 14 and the other decision records are still `Proposed` (DR 0006
and DR 0009 read `Recorded`), so a verdict graded against them is
provisional. Ratification binds a row as a target; it does not mark it met.

## Who acted, as the forge records it

| Actor | What the record shows |
|---|---|
| `loom-fleet-dispatch[bot]` (GitHub App) | Opened 99 of the 130 merged PRs, and posts the Loom role comments (Curator, Champion, Judge, Doctor) on issues and PRs. |
| `rjwalters` (the operator's account) | Opened the other 31 merged PRs. Their bodies carry the Claude Code footer (for example #160, #163, #198, #207), so agent sessions run under the operator's account also open PRs. The forge record does not separate which actions under this account were typed by the human. |
| `2am-ee-key[bot]`, `2am-market-key[bot]` | Separate GitHub Apps that hold the two ratification keys. They have posted formal reviews on two PRs: #84 (both requested changes) and #242 (first the market key approved and the EE key requested changes; at the final head both approved, and it merged). |
| Git commit author names | These come from host git configuration (`Robb Walters`, `Loom CI`, `Loom Auditor`, and others). They do not record which role, or whether a human, produced a commit. |

Two things follow. First, one App identity both authors and approves most
work, so "reviewed by a different agent" means a different session and role
prompt, not a different forge principal. Second, PRs #84 and #242, the two two-key acts, are the only
PRs in the repository's history with a formal GitHub review, and only the
key Apps posted them. Judge verdicts are posted as PR comments.

## The development loop

**Intended workflow** (Loom's role definitions, and
[`spec/verification-plan.md` § 5](../../spec/verification-plan.md#5-ai-agent-evidence-process)):

1. A Curator or Architect writes an issue. A Champion checks it against a
   fixed rubric and promotes it (`loom:issue`).
2. A Builder claims it and works in an isolated git worktree. It opens a PR
   with `Closes #N` and `loom:review-requested`.
3. A Judge reviews the PR against the issue's acceptance criteria. It either
   approves or requests changes. A Doctor addresses requested changes.
4. A Champion merges an approved PR. CI must be green.
5. Any change to the spec goes through a decision record in `spec/`. A
   decision record binds only after two-key ratification.

**One observed instance, end to end:** issue #139 (UART boot loader), PR #210.

- The Judge requested changes with a concrete counterexample. A one-bit flip
  in the frame's count byte was still accepted, because the count lies
  outside the CRC.
- The Doctor reproduced the counterexample on the RTL and accepted the
  finding. It added a bench that pins the behaviour, and recorded it as
  finding F8 in
  [DR 0013](../../spec/decision-records/0013-program-loading.md). The
  wire-format fix is a spec change, so the Doctor did not slip it in.
- The Judge's re-review then failed the PR on a mechanical point: the CI
  record check found a stale hash and a missing provenance line.
- The Doctor re-minted the
  [record](../../verification/records/boot-uart/records/20261010-223341-e74d2b6.md) <!-- superseded-ok: the record that PR #210's review actually re-minted, cited as history -->.
  The Judge checked the hashes byte for byte and approved, and the PR merged.
- The fix went to the operator as a ranked decision (#211). The operator
  chose a count-complement byte; the frame became `0xA5`, `N-1`, `~(N-1)`,
  payload, CRC-16, the boot ROM checks the complement before it commits a
  word, and the bench that had pinned the acceptance now asserts rejection of
  every single-bit flip of the count and complement bytes (DR 0013, dated
  entry 2026-10-11).

Steps 1 to 4 are visible in issue and PR comments throughout the history. We
have not audited every merged PR for a Judge verdict. Step 5's ratification
half is the part that did not work until 2026-10-11; see below.

## Checks that are mechanical

These run without anyone's judgement. A failure blocks a green CI run.

| Check | Where | What it enforces |
|---|---|---|
| Evidence records (lint + append-only) | `records` job in [`ci.yml`](../../.github/workflows/ci.yml), [`verification/check_records.py`](../../verification/check_records.py) | Record schema and input hashes. Records are never edited or deleted, and a stale record must be re-minted, not patched. The convention is [`verification/README.md`](../../verification/README.md). |
| RTL cocotb benches (no PDK) | `rtl-benches` job, [`scripts/run-rtl-benches.sh`](../../scripts/run-rtl-benches.sh) | Every PDK-free bench passes on every PR. |
| klt signoff manifest | `signoff` job, [`manifests/`](../../manifests/README.md) | The T1 evidence-tier grade is re-rendered by a tool from the committed manifest, not written by hand. |
| Two-key gate | [`ratification-gate.yml`](../../.github/workflows/ratification-gate.yml), [`docs/ratification-gate.md`](../ratification-gate.md) | No `spec/` `Status:` line can flip to `Ratified` unless the carrying PR has both `RATIFY-KEY` reviews. Each review must come from a distinct reviewer, and neither may come from the PR's author. |
| Tiny Tapeout sign-off | [`gds.yaml`](../../.github/workflows/gds.yaml), [`test.yaml`](../../.github/workflows/test.yaml) | The competition's own LibreLane flow and precheck. |

Two limits apply. The formal gate (`formal` job) runs only on manual
dispatch, not on every PR. As recorded on #44 on 2026-10-08, the two-key gate
reports but is not a required check on `main`.

## How evidence is kept honest

- **No claim without a recorded run.** There are 36 record kinds under
  [`verification/records/`](../../verification/records/), indexed in
  [`manifests/evidence/testbenches.txt`](../../manifests/evidence/testbenches.txt).
  Each record names its command, tool versions and input hashes.
- **Failures are recorded, not hidden.** PR #107 committed a post-layout run
  that **failed** 12 of 13 tests at every corner, and left every assertion
  unchanged:
  [record](../../verification/records/post-layout-sdf-regression/records/20261009-103407-9716a9e.md) <!-- superseded-ok: history of the failed-then-fixed record chain -->.
  The cause was diagnosed as stimulus and sampling racing the routed delays.
  The failure was kept. As the design moved on, it was re-run on each later
  netlist and re-recorded five more times, still failing 12 of 13, each record
  superseding the one before by reference. PR #202 then drove the unmodified
  bench file at the flow's own SDC timing, on the design current at the time,
  which gave 12 passes and 1 skip:
  [record](../../verification/records/post-layout-sdf-regression/records/20261010-102552-d43f89c.md) <!-- superseded-ok: history of the failed-then-fixed record chain -->.
  That record supersedes the last failing one
  ([`704a3fb`](../../verification/records/post-layout-sdf-regression/records/20261010-083555-704a3fb.md) <!-- superseded-ok: history of the failed-then-fixed record chain -->),
  whose netlist it shares, and states what it still does not show. A later
  record on a newer netlist
  ([`e5a0bae`](../../verification/records/post-layout-sdf-regression/records/20261011-114802-e5a0bae.md))
  has since superseded it, still passing.
- **Independent references.** Protocol firmware is graded against separately
  written reference models
  ([record](../../verification/records/protocol-reference-models/records/20261010-180436-9fb7815.md)).
  The core is checked edge by edge against an independent instruction-set
  simulator written from the decision records (PR #204,
  [record](../../verification/records/isa-lockstep/records/20261011-182004-080e6be.md)).
  The control space is checked with mutants
  ([record](../../verification/records/control-space/records/20261011-165710-56ebaf9.md)).
- **Two flows, both named.** Every number is attributed either to the
  competition's LibreLane flow or to this program's klt flow, per
  [DR 0002](../../spec/decision-records/0002-flow-of-record.md).

## Agent verdict versus operator decision

An agent's approval is a quality verdict. It does not bind the spec, and it
does not stand in for a decision reserved to the operator. The ratification
history is the case where this mattered.

| Date | Event |
|---|---|
| 2026-09-21 | PR #29 flipped five `Status:` lines to `Ratified` and merged with **zero** reviews. A sweep comment on the PR had just stood the merge down for lack of key reviews, and the PR merged 4 min 37 s later. The Judge's approval was the only gate, and it was treated as enough. |
| 2026-09-26 | [DR 0006](../../spec/decision-records/0006-two-key-ratification-never-ran.md) (PR #46, issue #44) recorded that the act never happened, and reset every affected status to `Proposed`. The original text was kept in place. DR 0006 ratified nothing, and it routed the question of whether separate agent sessions count as independent key holders to the operator instead of answering it. |
| 2026-09-30 | PR #48 added the two-key gate, so that the next attempt would fail CI rather than rely on a PR comment (issue #45). |
| 2026-10-02 | A comment on #44 under the operator's account recorded that the independence question had been settled at fleet level: keys are held by dedicated GitHub Apps, not the dispatch identity. That ruling lived outside this repository until DR 0009 recorded it. |
| 2026-10-08 | The ceremony ran on PR #84. The EE key answered `request-changes`; it had written its own Icarus testbench and found statements in DR 0001 that the RTL contradicts. The market key answered `uncompetitive`, because row 10's cited source does not support the row. **Release was refused.** |
| 2026-10-10 | PR #198 fixed six of the findings. Issue #85 lists all eight. |
| 2026-10-11 | Issue #85 closed (03:24Z). The second act opened as draft PR #242 (03:31Z). PR #84 was closed unmerged (06:02Z). On #242 the market key approved (07:29Z) and the EE key requested changes (07:33Z); its branch addressed the EE findings (`080e6be8`, 18:13Z). At the head `26297b9e` the EE key answered `approve` (20:51Z) and the market key `adequate-for-catalog` (20:53Z); PR #242 merged as `72f48153` (20:57Z) and #44 closed. The target spec's rows 1-12 and DRs 0001-0004 are **Ratified**; [DR 0009](../../spec/decision-records/0009-two-key-ratification-act.md) records what binds, and that one coordinating session dispatched both key agents (a recorded limit on independence). |

As of this writing the key reviewers are agent skills
([`ratification/ee-key/SKILL.md`](../../ratification/ee-key/SKILL.md),
[`ratification/market-key/SKILL.md`](../../ratification/market-key/SKILL.md))
running under separate identities. **No independent human engineering review
of this design has taken place, and we do not claim one.**

Other operator decisions on record:

- Closing PR #38 (a flip-flop program memory at 1306 % utilisation) in favour
  of the SRAM macro.
- The `loom:operator-only` hold on #44.
- Holding the key-App credentials, which fleet workers do not have.

## Upstream tooling friction

When `klt` (klayout-tools) lacked something or got it wrong, agents filed a
public issue at `2AMLogic/klayout-tools` describing the tool gap without
design detail. Representative issues:

- Fixed upstream:
  - no IHP CMOS5L platform entry, and standard-cell naming assumptions that
    rejected the library ([#1784](https://github.com/2AMLogic/klayout-tools/issues/1784),
    [#1786](https://github.com/2AMLogic/klayout-tools/issues/1786))
  - an extraction deck that read pin labels from one layer purpose only
    ([#2656](https://github.com/2AMLogic/klayout-tools/issues/2656))
  - SDF-annotation parsing problems
    ([#1136](https://github.com/2AMLogic/klayout-tools/issues/1136),
    [#1880](https://github.com/2AMLogic/klayout-tools/issues/1880),
    [#2285](https://github.com/2AMLogic/klayout-tools/issues/2285))
  - signoff items that accepted any passing envelope
    ([#2718](https://github.com/2AMLogic/klayout-tools/issues/2718))
- Still open:
  - request schemas cannot declare a hard macro
    ([#2635](https://github.com/2AMLogic/klayout-tools/issues/2635)). This
    blocks the klt flow's STA and place-and-route for this macro-backed
    design, so timing and the GDS come from LibreLane alone.
  - LVS netlist constructs that are still rejected
    ([#2941](https://github.com/2AMLogic/klayout-tools/issues/2941))
  - no control over gate-level power-up state
    ([#2998](https://github.com/2AMLogic/klayout-tools/issues/2998))
  - a remaining log-interleaving case
    ([#2996](https://github.com/2AMLogic/klayout-tools/issues/2996)). The
    workaround for it is disclosed in the
    [record](../../verification/records/post-layout-sdf-regression/records/20261010-205119-af36071.md) <!-- superseded-ok: the record that needed the workaround, cited as history -->
    that needed it.

## Limitations of AI-generated verification

- **Correlated authorship.** The same model family wrote the RTL, the benches,
  the reference models and the ISA simulator. Agents writing "independently"
  from the same decision record can share a misreading of it. Formal
  properties, mutants, Judge counterexamples, and the EE key's own testbench
  reduce this risk; they do not remove it.
- **No human or silicon ground truth.** Nothing has been taped out or measured.
  Pad electrical timing is not characterised: the
  [pad model](../../verification/records/uio-pad-model/records/20261011-104304-d81097f.md)
  is logical and zero-delay. Post-layout simulation runs the SRAM as a
  zero-delay functional model, so its read timing is evidenced only by STA.
- **Partly unratified targets.** Rows 13 and 14, and the decision records
  other than DR 0001-0004, are still Proposed; passes against them are
  graded against proposed text.
- **Review rigour varies.** Judge verdicts are prompts applied by agents, and
  the 2026-09-21 merge shows a pipeline can approve what its own rules forbid.
  The fix was a mechanical gate, not more prose.

Open gaps against the spec are tracked in
[`spec/gap-to-submission.md`](../../spec/gap-to-submission.md).
