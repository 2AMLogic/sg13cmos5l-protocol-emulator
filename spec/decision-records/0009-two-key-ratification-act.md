# 0009: The Two-Key Ratification Act — Target Spec and DRs 0001–0004

Status: **Recorded 2026-10-08** — a record of an act, not a decision. The act
is the two `RATIFY-KEY` reviews on pull request #84; this record states what
that act binds and what it leaves unbound, and it decides no design question
of its own. It is the record
[`0006-two-key-ratification-never-ran.md`](0006-two-key-ratification-never-ran.md)
§ "How this gets closed", step 4, calls for (there named "a `0007` record";
0007 and 0008 were taken, so this is the next free number).
Date: 2026-10-08
Issue: #44

## Context

DR 0006 found that the two-key mechanism had never run in this repository:
pull request #29 flipped `spec/target-spec.md` and DRs 0001–0004 to
`Ratified` and merged (merge commit `8be9d1e`) with zero pull-request reviews
of any kind. Every such status was reconciled to `Proposed`, and DR 0006 set
out five steps to close the gap. Their state:

| Step (DR 0006) | State |
|---|---|
| 1. Ruling on the independence question | Recorded in issue #44's body on 2026-10-02: the keys are held by two dedicated forge identities, one per key, and the shared identity that authored this repository's earlier pull requests satisfies neither key. That is the *distinct forge principals* reading of DR 0006 § "Routed, not decided". |
| 2. The second identity | Provided as part of that ruling: one forge identity for the EE key and another for the market key. |
| 3. Two `RATIFY-KEY` reviews on a carrying PR | Pull request #84. |
| 4. A record reporting the act | This record. |
| 5. `Status:` lines move to `Ratified`, citing that record | Done by the same pull request, for the five files in "What the act binds" below. |

## The act

The carrying PR is **pull request #84**. It flips five `Status:` lines under
`spec/` and adds this record, so it is subject to the
`two-key gate (spec Status flips)` check
([`docs/ratification-gate.md`](../../docs/ratification-gate.md)): one `ee`
and one `market` marker in its own `/pulls/84/reviews`, well-formed, with
releasing verdicts, distinct `reviewer=` values, and neither attributable to
the PR's author.

**This file was written before either review and before the merge.** It does
not contain the two review URLs, the two verdict tokens, or the merge commit
hash, and it could not: the reviews are posted on the PR that carries this
file, and no file can contain the hash of the commit that merges it. Those
three facts are read from the forge:

```
gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/84/reviews \
  --jq '.[] | select(.body | test("RATIFY-KEY")) | {user: .user.login, state, html_url, marker: (.body | split("\n")[0])}'
gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/84 --jq '{merged, merge_commit_sha, merged_at}'
```

A follow-up change appends them here as a dated note. Until it does, the
forge is the record, and this file's presence on `main` means only that pull
request #84 merged. If that pull request is closed without merging, this file
never reaches `main` and nothing in `spec/` changes.

## What the act binds

| File | Status after the act | What binds |
|---|---|---|
| `spec/target-spec.md` | `RATIFIED` | All twelve rows **as targets**, exactly as DR 0004's per-row register states them: values, sources, stretch entries and checking artifacts. Row 2 is a stretch aim and binds nothing numeric. |
| `0001-isa.md` | `Ratified` | As written. |
| `0002-flow-of-record.md` | `Ratified` | As written. |
| `0003-firmware-toolchain.md` | `Ratified` | As written. |
| `0004-target-spec-ratification.md` | `Ratified` | The register, the separation of what is bound from what is evidenced, and the binding process. |

These are the five files pull request #29 claimed to ratify and DR 0006
reopened. No content in any of them changes: each gains a new `Status:` line,
and its 2026-09-26 and 2026-09-21 status text is preserved verbatim beneath
it.

## What the act does not bind

| File | Status | Why it is not bound here |
|---|---|---|
| `0005-program-memory-implementation.md` | `Proposed`, unchanged | It is a separate ratification question (which implementation holds the program bits), it carries its own open items, and its Status line says it binds through key reviews on a PR that carries it. No such PR has existed. |
| `0007-row4-corner-set-under-the-macro.md` | `Proposed`, unchanged | It decides how row 4 is graded and depends on DR 0005. Its own § "New record, not an amendment to DR 0005" argues that it must stay separable, so that a key-holder can accept one question and reject another. |
| `0008-open-drain-uio-oe-wiring.md` | `Proposed`, unchanged | A separate design decision with its own carrying-PR requirement. |
| `0006-two-key-ratification-never-ran.md` | `Recorded`, unchanged | A finding of fact; there is nothing in it to ratify. |
| `spec/verification-plan.md`, `spec/gap-to-submission.md` | `DRAFT`, unchanged | Neither claims ratification. |

**On DR 0007 specifically.** DR 0006's 2026-10-02 numbering note and DR 0007's
own numbering note both say that the record reporting the act "must also list
DR 0007 among the records it binds". This record lists DR 0007 and does
**not** bind it. Issue #44 scopes this act to the records pull request #29
claimed to ratify. Folding DRs 0005, 0007 and 0008 into the same act would
place four independent questions under one pair of verdicts, which is what DR
0007 itself argues against. The two notes were written when the mechanism had
no path to completion; it has one now, and each of the three records can go
to the keys on a carrying PR of its own. Anyone who reads the two notes as
requiring DR 0007 to be bound by *this* act should treat that as unresolved,
not as satisfied.

Three consequences follow, and each is a live gap rather than a formality:

- **DR 0001 is ratified as written, without DR 0005's amendment.** DR 0005
  § "Amendment to DR 0001 — fetch-ahead" proposes one change to DR 0001's
  fetch stage. That amendment is not in force. The RTL on `main` was built on
  the macro path under an explicit go-ahead recorded on issue #18, ahead of
  ratification, so until DR 0005 is ratified the implementation follows a
  proposed amendment to a ratified record. The gap is recorded, not hidden.
- **Row 4's corner set is not bound.** The row's text binds "≥ 50 MHz timing
  closure on CMOS5L (flow of record per DR 0002)" and has never named a
  corner set. Which corners it is graded at is DR 0007's question and stays
  open.
- **The open-drain `uio_oe` wiring is not bound.** DR 0001's "direction is
  fixed at synthesis time" text is ratified as written; DR 0008's proposal
  for how that is wired is not.

## What the act does not do

- **It moves no row between target and met, in either direction.** The
  `State` column of `spec/target-spec.md` and DR 0004's register describe
  the evidence as of 2026-09-21 (row 4's `State` wording alone was updated
  on 2026-10-02). Evidence has moved since then: for example, several rows'
  `State` text still says no RTL or firmware exists, and both now do.
  `spec/gap-to-submission.md` is the live tracker. A row that the snapshot
  calls unmet is not made met by this act, and a row the tracker now reports
  progress on is not made met by it either.
- **It relaxes nothing.** No target, source, stretch entry or checking
  artifact is reworded. No previously-ratified row exists to relax: DR 0006
  established that nothing in `spec/` had ever been ratified by mechanism.
- **It does not weaken the two-key requirement or the non-author rule**, and
  it changes no file of the gate that enforces them.
- **It does not edit any evidence record** under `verification/records/`.

## Consequences

- **The precondition of T1 item 5 is met from the merge of pull request
  #84**: there is a ratified spec to grade against. Item 5 itself is full
  corner verification against that spec and is not met by this act.
- **Issue #17's deliverable, the act, now exists**, for the five files above.
- **Later changes to a bound row go through a new decision record and the
  same mechanism**, and a relax of a ratified row to make a failing
  measurement pass is the change both key skills escalate (their Step 5).
  From this act onward that check has something to apply to.
- **Statements elsewhere in the repository that the spec is unratified become
  out of date at the merge** and are left for the follow-up change that
  appends the forge facts above, so that each correction can cite the merge
  commit: comments in `info.yaml`, `rtl/README.md`, `docs/info.md`,
  `manifests/README.md`, and the Status prose of DRs 0005, 0007 and 0008
  where it says the mechanism has never run, and the `State` cell of
  `spec/target-spec.md` row 4, which lists "this spec is unratified" among
  three reasons the row is unmet (the other two stand). Until then those
  statements understate the spec's status. `flow/README.md` is a different case: it
  still attributes ratification to pull request #29, which DR 0006 showed
  was not an act, and it needs the same follow-up.
