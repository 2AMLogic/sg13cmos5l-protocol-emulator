# 0009: The Two-Key Ratification Act — Target Spec and DRs 0001–0004

Status: **Recorded 2026-10-11** — a record of an act, not a decision. The act
is the two `RATIFY-KEY` reviews on pull request #242; this record states what
that act binds and what it leaves unbound, and it decides no design question
of its own. It is the record
[`0006-two-key-ratification-never-ran.md`](0006-two-key-ratification-never-ran.md)
§ "How this gets closed", step 4, calls for (there named "a `0007` record";
0007 and 0008 were taken, so this is the next free number).
Date: 2026-10-11
Issue: #44

## Context

DR 0006 found that the two-key mechanism had never run in this repository:
pull request #29 flipped `spec/target-spec.md` and DRs 0001–0004 to
`Ratified` and merged (merge commit `8be9d1e`) with zero pull-request reviews
of any kind. Every such status was reconciled to `Proposed`, and DR 0006 set
out five steps to close the gap. Their state:

| Step (DR 0006) | State |
|---|---|
| 1. Ruling on the independence question | Recorded on issue #44 on 2026-10-02: the keys are held by two dedicated forge identities, one per key, and the shared identity that authored this repository's earlier pull requests satisfies neither key. That is the *distinct forge principals* reading of DR 0006 § "Routed, not decided". |
| 2. The second identity | Provided as part of that ruling: one forge identity for the EE key and another for the market key. |
| 3. Two `RATIFY-KEY` reviews on a carrying PR | Pull request #242. |
| 4. A record reporting the act | This record. |
| 5. `Status:` lines move to `Ratified`, citing that record | Done by the same pull request, for the five files in "What the act binds" below. |

**The earlier candidate.** The keys were first offered on draft pull
request #84 (2026-10-08). Neither released: the EE key requested changes
and the market key returned `uncompetitive`, so that PR did not merge and
nothing in `spec/` changed. Issue #85 lists what the two keys required. Its
items 2, 3 and 5–8 were fixed by pull request #198, and items 1 and 4 by
pull request #239 under the operator's rulings on issue #85 of 2026-10-11.
None of those changes moved a `Status:` line. Pull request #242 is a fresh
carrying PR from `main` with those fixes in place, and it supersedes #84.
A review posted on #84 is not a review on #242 and counts for nothing here.

## The act

The carrying PR is **pull request #242**. It flips five `Status:` lines under
`spec/` and adds this record, so it is subject to the
`two-key gate (spec Status flips)` check
([`docs/ratification-gate.md`](../../docs/ratification-gate.md)): one `ee`
and one `market` marker in its own `/pulls/242/reviews`, well-formed, with
releasing verdicts, distinct `reviewer=` values, and neither attributable to
the PR's author.

**This file was written before either review and before the merge.** It does
not contain the two review URLs, the two verdict tokens, or the merge commit
hash, and it could not: the reviews are posted on the PR that carries this
file, and no file can contain the hash of the commit that merges it. Those
three facts are read from the forge:

```
gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/242/reviews \
  --jq '.[] | select(.body | test("RATIFY-KEY")) | {user: .user.login, state, html_url, marker: (.body | split("\n")[0])}'
gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/242 --jq '{merged, merge_commit_sha, merged_at}'
```

A follow-up change appends them here as a dated note. Until it does, the
forge is the record, and this file's presence on `main` means only that pull
request #242 merged. If that pull request is closed without merging, this file
never reaches `main` and nothing in `spec/` changes.

### How the keys are applied, and a known limit on independence

The operator ruled on issue #44 on 2026-10-11 (ruling 1) on who applies
the keys. The ruling is quoted here in full, because it records a limit on
the independence of the two reviews that a reader of this act should know:

> **Who applies the keys → option 2.** The coordinating session launches two
> isolated review agents, one per key. Each is given only PR #242 and its own
> key's instructions (the installed key skill), and none of the coordinating
> session's conversation. Each agent applies its own key with
> `ratify-key.sh apply`. This is recorded as a known limit on independence:
> one coordinator dispatches both agents and relays their verdicts. The
> coordinator does not edit, summarise or filter what a key agent posts.

The two keys are still two distinct forge identities, neither the PR's
author nor the design's author, and the gate checks that. What the gate
cannot check is the limit above: both key agents are launched by one
coordinating session. This record states it and does not resolve it.

## What the act binds

| File | Status after the act | What binds |
|---|---|---|
| `spec/target-spec.md` | `RATIFIED` | Rows 1–12 **as targets**, exactly as DR 0004's per-row register states them: values, sources, stretch entries and checking artifacts, as corrected on `main` for issue #85 before this act. Row 2 is a stretch aim and binds nothing numeric. |
| `0001-isa.md` | `Ratified` | As written, **including its dated amendment of 2026-10-11** under "Timing model" (issue #85, item 1), which supersedes the sentence "fetch and execute happen in the same cycle for every instruction" with the fetch-ahead model: instruction fetch one cycle ahead of execute, every instruction still 1 cycle (`WAIT imm8` in `imm8 + 1`), branch cost independent of data, and a fixed +1 cycle at run-phase entry. Also **including its dated amendment of 2026-10-11 under the port table** (issue #44, operator ruling 3, pull request #249), which supersedes "direction (`uio_oe`) is fixed at synthesis time" with run-time direction per pin from `UIO_DIR` and `UIO_OD`, reset to all inputs. Both amendments are part of DR 0001's text, so they are bound with it. |
| `0002-flow-of-record.md` | `Ratified` | As written. |
| `0003-firmware-toolchain.md` | `Ratified` | As written. |
| `0004-target-spec-ratification.md` | `Ratified` | The register, the separation of what is bound from what is evidenced, and the binding process. |

These are the five files pull request #29 claimed to ratify and DR 0006
reopened. No content in any of them changes in this act: each gains a new
`Status:` line (and DR 0004 and `spec/target-spec.md` a dated pointer note),
and its 2026-09-26 and 2026-09-21 status text is preserved verbatim beneath
it.

## What the act does not bind

| File or row | Status | Why it is not bound here |
|---|---|---|
| `0005-program-memory-implementation.md` | `Proposed`, unchanged | Operator ruling on issue #85, item 1 (2026-10-11): DR 0001 is amended instead, and DR 0005 is not bound. It is a separate question (which implementation holds the program bits, its integration and its area), and it goes to the keys on its own carrying PR. DR 0001's amendment quotes its fetch-ahead sentence, so that sentence binds as part of DR 0001; nothing else in DR 0005 does. |
| `0007-row4-corner-set-under-the-macro.md` | `Proposed`, unchanged | Operator ruling on issue #85, item 4 (2026-10-11). DR 0007 decides how row 4 is graded, and its own § "New record, not an amendment to DR 0005" argues that it must stay separable, so that a key-holder can accept one question and reject another. It stays `Proposed`, and with it row 4's corner set, until the klt flow produces timing evidence for this design (`2AMLogic/klayout-tools#2635`). |
| `0008-open-drain-uio-oe-wiring.md` | `Proposed`, unchanged | A separate design decision with its own carrying-PR requirement. |
| DRs 0010, 0011 and 0013–0018 | `Proposed`, unchanged | Each was written after DR 0004's register and states its own carrying-PR requirement. |
| `spec/target-spec.md` rows 13 and 14 | `Proposed`, unchanged | **Out of scope by operator ruling** (issue #44, 2026-10-11, ruling 2): "Act scope → rows 1–12 only, as drafted. Target-spec rows 13 and 14 are not bound by this act; they get their own act later." Both were added on 2026-10-09, after DR 0004's register, and their `State` cells say they are not in it. |
| `0012-control-space-and-runtime-pin-direction.md` | `Proposed`, unchanged | Operator ruling on issue #44, ruling 3 (2026-10-11): DR 0001 is amended instead, and DR 0012 is not bound. DR 0001's amendment quotes its pin-mode and reset text, so that text binds as part of DR 0001; the rest of DR 0012's control space does not. |
| `0006-two-key-ratification-never-ran.md` | `Recorded`, unchanged | A finding of fact; there is nothing in it to ratify. |
| `spec/verification-plan.md`, `spec/gap-to-submission.md` | `DRAFT`, unchanged | Neither claims ratification. |

**On DR 0007.** DR 0006's 2026-10-02 numbering note and DR 0007's own
numbering note said that the record reporting the act "must also list DR
0007 among the records it binds". That sentence is superseded: both records
carry dated notes of 2026-10-11 (issue #85, item 4, pull request #239)
recording the operator's ruling that the act does not bind DR 0007. DRs
0006, 0007 and this record now say the same thing, and the question is
settled.

Three consequences follow. Each says what is bound and what is still a proposal:

- **DR 0001's fetch model is bound; DR 0005's other decisions are not.**
  The RTL on `main` fetches one cycle ahead of execute
  (`rtl/protocol_core.v`, § "TIMING MODEL"), and DR 0001, as amended, now
  says so. Under DR 0017 that amendment is a `no-behaviour-change` amendment
  citing issue #85. Whether the program bits live in the SRAM macro, and
  how it is integrated, is still DR 0005's proposal; the macro path on
  `main` was built under the operator's explicit go-ahead on issues #18 and
  #60, ahead of ratification.
- **Row 4's corner set is not bound.** The row's text binds "≥ 50 MHz timing
  closure on CMOS5L (flow of record per DR 0002)" and has never named a
  corner set. Which corners it is graded at is DR 0007's question and stays
  open.
- **DR 0001's `uio` direction model is bound; the rest of DR 0012 is
  not.** DR 0001's port table said `uio_oe` "is fixed at synthesis time per
  protocol pin plan, not runtime-programmable in this ISA revision", while
  the design on `main` sets direction at run time. The operator ruled on
  issue #44 (2026-10-11, ruling 3) to settle this with a dated amendment to
  DR 0001 that points at DR 0012, landed on `main` by pull request #249
  before any key review. DR 0001, as amended, now states the direction
  model the RTL implements (`UIO_DIR` / `UIO_OD`, per pin, reset to all
  inputs), and that is what this act binds. Under DR 0017 the amendment is
  a `no-behaviour-change` amendment citing issue #44. DR 0012 is not bound:
  its program-memory access, `PM_CRC`, `BOOT_STATUS`, `HW_ID`, `RUN` and
  the remaining control indices are still its proposal, and so are DR
  0013's loader, DR 0008's open-drain wiring and DR 0016's flag and shift
  details. All of them are built on `main` and frozen by DR 0017.

## What the act does not do

- **It moves no row between target and met, in either direction.** The
  `State` column of `spec/target-spec.md` began as the one-line index of
  DR 0004's 2026-09-21 register, and several of its cells have since been
  updated by dated notes; neither is the evidence state on the date of the
  act. `spec/gap-to-submission.md` is the live tracker. A row that the
  snapshot calls unmet is not made met by this act, and a row the tracker
  now reports progress on is not made met by it either.
- **It relaxes nothing.** No target, source, stretch entry or checking
  artifact is reworded by this act. No previously-ratified row exists to
  relax: DR 0006 established that nothing in `spec/` had ever been ratified
  by mechanism.
- **It changes nothing a program can observe.** DR 0001 is pinned by DR
  0017's ISA freeze, so its Status flip changes the file's hash; pull
  request #242 appends the `no-behaviour-change` amendment citing itself to
  `spec/isa-freeze.json`, as DR 0017 section 4, item 4 requires.
- **It does not weaken the two-key requirement or the non-author rule**, and
  it changes no file of the gate that enforces them.
- **It does not edit any evidence record** under `verification/records/`.

## Consequences

- **The precondition of T1 item 5 is met from the merge of pull request
  #242** for rows 1–12: there is a ratified spec to grade them against.
  Item 5 itself is full corner verification against that spec and is not
  met by this act.
- **Issue #17's deliverable, the act, now exists**, for the five files above.
- **Later changes to a bound row go through a new decision record and the
  same mechanism**, and a relax of a ratified row to make a failing
  measurement pass is the change both key skills escalate (their Step 5).
  From this act onward that check has something to apply to.
- **Statements elsewhere in the repository that the spec, or DR 0001, is
  unratified become out of date at the merge** and are left for the
  follow-up change that appends the forge facts above, so that each
  correction can cite the merge commit: comments in `info.yaml`,
  `rtl/README.md`, `docs/info.md`, `manifests/README.md`,
  `docs/submission/ai-use.md` and `docs/submission/verification.md`, and the
  Status prose of DRs 0005, 0007, 0008 and 0010–0018 where it says the
  mechanism has never run. Until then those statements understate the
  spec's status. `flow/README.md` is a different case: it still attributes
  ratification to pull request #29, which DR 0006 showed was not an act, and
  it needs the same follow-up. Pinned records (DRs 0005, 0012, 0013, 0015,
  0016) need a `no-behaviour-change` amendment for that edit too.
