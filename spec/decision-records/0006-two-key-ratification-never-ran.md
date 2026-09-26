# 0006: The Two-Key Ratification Act Never Happened

Status: **Recorded 2026-09-26** — a finding of fact, not a binding decision.
This record introduces no target, relaxes no row, and decides no design
question, so there is nothing in it for a `RATIFY-KEY` review to bind: it
states a forge-checkable fact, and applies the invalidation clause
[`0004-target-spec-ratification.md`](0004-target-spec-ratification.md) wrote
against itself. It deliberately does **not** attempt to ratify anything —
including itself — because the one question that would have to be settled
first cannot be settled by an authoring session (see
"[Routed, not decided](#routed-not-decided-the-operator-question)").
Date: 2026-09-26
Issue: #44

## Context

`spec/README.md` § "How ratification works here", `spec/target-spec.md`
§ "Ratification", and DR 0004 § "The binding process" all define one act as
the ratification of this repo's spec: **two `RATIFY-KEY` reviews on the
carrying PR** — one EE key, one market key, *"neither held by the ratifying
PR's author or the design's author"* — after which *"the merge commit is the
ratification record."* All three texts also say, in their own words, that a
merge without both key reviews is not that act. DR 0004's Status line is the
sharpest of the three:

> If that PR merged without both key reviews, this record's `Ratified` line
> is invalid until superseded by a later record that says so.

This is that later record. It says so.

## The fact

Re-verified 2026-09-26 against the live forge, independently of issue #44's
own evidence, using the REST reviews endpoint (the same one the mechanism's
own acceptance check names):

```
$ for p in $(gh api "repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls?state=all&per_page=100" \
      --jq '.[].number'); do
    gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/$p/reviews \
      --jq 'length, ([.[]|select(.body|test("RATIFY-KEY"))]|length)'
  done
```

- **21 pull requests exist in this repository's entire history** (#4 … #43).
- **Every one of them has zero pull-request reviews of any kind.** Not zero
  key reviews — zero reviews. The repository has never carried a single
  formal PR review record.
- **Therefore zero `RATIFY-KEY` markers exist in any review**, on any PR,
  ever.

The carrying PR specifically:

| | |
|---|---|
| Carrying PR | **#29** — "spec: ratify target spec and DRs; install the two-key reviewer variant" |
| Author | `loom-fleet-dispatch[bot]` |
| Reviews (`/pulls/29/reviews`) | **0** total, **0** with a `RATIFY-KEY` marker |
| Merged | 2026-09-21T19:07:39Z by `loom-fleet-dispatch[bot]` |
| **Merge commit** | **`8be9d1e`** (`8be9d1e622eeed1abd8d1d0fcc551a15a32d0b39`) |
| Labels at merge | `loom:pr` — **not** `loom:auto-merge-ok`, the label DR 0004 § "The binding process" names as the second key-holder's release signal |

And the failure was seen at the time, not discovered later. A sweep comment
on PR #29 at 2026-09-21T19:02:01Z–19:03:02Z stood the merge down in terms
that need no interpretation: *"Sweep status: judge-approved (quality gate) —
merge deferred awaiting the two-key release… Merging before 1–3 would enact
exactly the assertion-without-mechanism state this PR's invalidation clause
names. The merge step of this sweep pass therefore stands down."* **The PR
merged 4 minutes 37 seconds later**, with none of steps 1–3 performed.

**One false positive to expect, named here so nobody re-derives it as
evidence.** A text search for `RATIFY-KEY` across *PR comments* (rather than
reviews) returns two hits — one on #29, one on #43. Both were read in full on
2026-09-26: both are Loom pipeline prose that *names* the marker while
explicitly disclaiming being one (#29's stand-down comment listing what would
release the PR; #43's Judge review saying *"it does not conflate my Judge
approval with a RATIFY-KEY review, and neither do I"*). Neither contains a
`<!-- RATIFY-KEY: … -->` marker line, and neither is a review. The count that
matters is the one on `/pulls/<N>/reviews`, and it is zero.

## What DR 0004's own clause does to each record

DR 0004 § "The binding process" states the consequence itself — *"in that
case this record and the Status lines it flips are assertions without a
mechanism, and a later record must reopen them rather than inherit them."*
Applying that, unchanged and without re-litigating any content:

| Record / file | `Status:` as written | Post-repair truth | Why |
|---|---|---|---|
| `spec/target-spec.md` | `**RATIFIED**` (2026-09-21) | **`PROPOSED` — not ratified** | Its own § "Ratification" says: *"If this file's Status reads `RATIFIED` but the ratifying PR's record cannot show both key reviews, the ratification did not happen by mechanism, and this status is invalid until superseded by a later record that says so."* PR #29 cannot show them. |
| `0004-target-spec-ratification.md` | `Ratified 2026-09-21` | **`Proposed` — the ratification act it describes was not performed** | Its own Status line's invalidation clause, quoted above, fires directly. |
| `0001-isa.md` | `Ratified 2026-09-21` | **`Proposed`** (pending ratification alongside `spec/target-spec.md`) | Its `Ratified` line is expressly derivative — *"carried into force with `spec/target-spec.md`'s ratification… the ratifying PR's two `RATIFY-KEY` reviews and merge commit are the act."* The act did not occur, so nothing was carried. Returns to the status it was authored with. |
| `0002-flow-of-record.md` | `Ratified 2026-09-21` | **`Proposed`** (same derivation) | Same. Its separate live-state note (both upstream klayout-tools gaps closed) is a statement of fact about the world and is unaffected. |
| `0003-firmware-toolchain.md` | `Ratified 2026-09-21` | **`Proposed`** (same derivation) | Same. |
| `0005-program-memory-implementation.md` | `**Proposed 2026-09-25**` | **`Proposed`, unchanged** | Already correct. DR 0005 declined to self-certify and said so; it is the control case, not part of this defect. See "DR 0005" below. |
| `spec/verification-plan.md` | `DRAFT` | **`DRAFT`, unchanged** | Never claimed ratification. |
| `spec/gap-to-submission.md` | `DRAFT` + a 2026-09-21 note saying the rows it measures against "were **ratified**" | `DRAFT`; the 2026-09-21 note is corrected by a dated 2026-09-26 note pointing here | The tracker's own convention is to append a dated note, never to rewrite one. |

**Nothing about the *content* of DRs 0001–0005 or of `spec/target-spec.md` is
changed, questioned, or weakened by this record.** Every value, source,
checking artifact, cycle budget, per-row register entry, and measured number
in those files stands exactly as written, and the reasoning that produced
them was reviewed at the time by the ordinary pipeline. What is missing is the
*act* that makes them binding, and an act cannot be supplied by describing it.
In particular DR 0004's load-bearing separation — **what the ratification
binds** versus **whether the design has met it** — survives this repair
untouched: no row's met/unmet state moves in either direction, and `State`
column entries such as row 5's "met at the stub level" remain true as
statements of evidence regardless of whether the binding is ratified or
proposed.

### Append-only discipline

Per `CLAUDE.md` (*"Recorded results are append-only evidence; a result is not
superseded by deletion, it is superseded by a later record that says why"*),
the earlier text is **not** deleted to hide the gap:

- Each affected file's original 2026-09-21 `Status:` text is preserved
  verbatim, in the same file, in a clearly-labelled block immediately below
  the reconciled line — so the file itself shows what it used to claim.
- The prose in `spec/target-spec.md` § "Ratification", `spec/README.md`
  § "How ratification works here", and DR 0004 § "The binding process" is
  left as written, under a dated reconciliation banner saying the act
  described there was not performed.
- No entry under `verification/records/` is touched at all. This repair
  concerns governance, not evidence; every record stands.
- `git show 8be9d1e` remains the complete record of what was merged.

## DR 0005

DR 0005 stays **`Proposed`**, and this record resolves its status by saying so
explicitly rather than by ratifying it. It was authored honestly — its Status
line already required *"two `RATIFY-KEY` reviews… neither held by this
record's author"* before it binds, and its carrying PR (#43, merge commit
`a59a0f3`) left the corresponding checklist item unticked with *"not satisfied
by this PR, and cannot be."* That was the correct behaviour and it is not
disturbed here.

What being unratified currently blocks, recorded so it is tracked rather than
assumed:

- **The SRAM-macro program-memory path is a measured proposal, not the decided
  implementation path.** Issue #18 / PR #38's acceptance criterion 4 waits on
  that decision, and #20 (STA on the core) and #23 (firmware) sit downstream
  of #18.
- **`spec/target-spec.md` rows 6 and 7 stay unmet and bound as written.** DR
  0005 changes the *implementation* rather than either target, and explicitly
  declines the budget-revision axis; that remains its proposal.
- `info.yaml`'s `tiles: "1x1"` stays as it is — the submitted top is still the
  0.092-tile stub, and `tiles` moves when a real top is measured.

DR 0005 is therefore the standing demonstration that the mechanism has no path
to completion in this repo: a record that correctly refuses to self-certify
simply waits, with nothing available to ratify it. That is the gap this record
exists to make visible, and it is not closed by this record either.

## Routed, not decided: the operator question

**Why this record does not just run the mechanism and close the loop.**

Issue #44 flagged one question as needing an operator ruling before the repair
merges, and this record does not answer it:

> Whether agent-held keys in separate sessions satisfy *"neither held by …
> the design's author"* for a repo where every session descends from the same
> fleet identity (`loom-fleet-dispatch`).

That question is genuinely open, and it is not open for want of effort. The
two key skills contemplate agent key-holders — their marker grammar carries a
`reviewer=<agent-id>` field — and both state the non-author rule while
explicitly delegating the identity check elsewhere:

> **Non-author enforcement (stated here, enforced elsewhere).** This skill
> must not be invoked by an agent that authored the PR under review or the
> spec/design the PR ratifies. The actual identity check is the invoking
> review automation's job — until it lands, self-check: if the PR's author, or
> the design's original proposer, is the same identity running this review,
> **stop and say so instead of producing a verdict.**
> — `ratification/ee-key/SKILL.md`, and verbatim in `market-key/SKILL.md`

The "invoking review automation" does not exist in this repo, so the self-check
governs. Applying it to this repo's actual forge state:

- **Every artefact in this repository — all 21 PRs, every commit under
  `spec/`, every comment, and every merge — is authored by the single GitHub
  App identity `loom-fleet-dispatch[bot]`.** PR #29's author is
  `loom-fleet-dispatch[bot]`; so is its merger; so is the author of DRs
  0001–0005; so is any review this or any other fleet session could post.
- A `RATIFY-KEY` review posted from a fleet session therefore lands on the
  forge as **the carrying PR's own author and the design's author**, which is
  precisely the identity the self-check names. The mechanism's own instruction
  in that case is *stop and say so*, and this section is the saying so.
- GitHub reinforces the same boundary mechanically: it refuses an `APPROVE` or
  `REQUEST_CHANGES` review from a pull request's own author, accepting only a
  `COMMENT`-event review. So the only thing that identity *can* record is a
  review that satisfies a count-based check while failing the rule the count
  exists to evidence — an outcome worse than the current honest zero, because
  it would look repaired.

**The disagreement axis, stated plainly**, because this is a preference about
what the rule protects rather than a fact derivable from this repo:

- **Independence as incentive separation.** The rule exists so no interested
  party grades its own work. A fresh session, with no memory of authoring and
  no stake in the verdict, applying a published rubric to a public diff, *is*
  incentive-separated; the shared app token is a credential artefact, not an
  interest. On this reading, agent-held keys in separate sessions satisfy the
  rule, and the `reviewer=<agent-id>` field is how the distinct holders are
  recorded.
- **Independence as auditable identity.** The whole point of *"the merge
  commit is the ratification record"* is a record a third party can check
  **without trusting anyone's narrative** about how the review was produced.
  If the forge record cannot distinguish the reviewer from the author, then
  the evidence is the claim again — the exact failure this repair exists to
  end. On this reading, distinct forge principals are the requirement, and no
  amount of session hygiene substitutes.

Both readings are held by informed people; nothing in `spec/`,
`ratification/`, or `CLAUDE.md` settles which one the mechanism means. The
choice also has consequences the operator owns and an agent does not:
provisioning a second forge identity, or ruling that this fleet's sessions
count, is an act that binds how every future ratification in every canary repo
is evidenced.

**So it is routed, not assumed.** Closing the loop by having two fleet
sessions post both keys and then asserting that satisfies the independence
rule would reproduce the defect this record documents, with more ceremony —
and would do so in a way that is *harder* to detect than the present state,
because the mechanical check would pass. Issue #44 says the same thing:
*"route that question rather than assuming either answer."*

## What this record does NOT do

Stated explicitly so that no later reader mistakes its scope:

- **It does not ratify anything**, including itself. It is not a
  self-certifying ratification by another name.
- **It does not relax, reword, or reinterpret any spec row, target, source,
  or checking artifact.** Per `CLAUDE.md`, agents do not relax the ratified
  spec to make a result pass — and that applies with at least as much force
  to the ratification mechanism itself. The two-key requirement is left
  exactly as strict as DR 0004 and `spec/README.md` wrote it.
- **It does not weaken the non-author rule, add an exception to it, or
  redefine what counts as a key.** No new status vocabulary is introduced
  beyond this record's own non-binding `Recorded` label (see below).
- **It does not move any row from target to met, or from met to target.**
- **It does not edit or delete any existing evidence record.**

**On the `Recorded` status label.** `spec/`'s vocabulary to date is
`DRAFT` / `Proposed` / `Ratified`. This record is none of those: it proposes
nothing to be ratified, so labelling it `Proposed` would imply a pending act
that does not apply, and labelling it `Ratified` would be the very error it
documents. `Recorded` means: *a statement of forge-checkable fact plus the
mechanical consequence another record already prescribed for that fact; binds
nothing on its own.* A record needs ratification when it **decides**
something; this one only **observes**. `spec/README.md` § "How ratification
works here" now says the same thing in one line, so the vocabulary is
documented where a reader will look for it.

## Consequences

- **T1 item 5's precondition is not met.** `manifests/design-evidence-tiers.md`
  item 5 is "Full corner verification vs a **ratified** spec". The spec is
  proposed, not ratified, so verdicts graded against it remain provisional by
  construction — the state DR 0004 § Context was written to end, and which it
  did not end. `manifests/README.md` already records item 5 as unmet with *"an
  unratified spec (#17)"* as one of its reasons; that line was and remains
  accurate, and needs no correction.
- **Issue #17 is not satisfied.** Its deliverable was the act, not the
  description of the act.
- **DRs 0001–0005 continue to be the best available design reasoning and
  should be treated as such in implementation work** — nothing here asks
  anyone to stop building against them. They simply do not *bind* until the
  mechanism runs, and no evidence graded against them is more than
  provisional until then.
- **The mechanism has no enforcement hook anywhere.** DR 0004 and
  `spec/README.md` describe the second key-holder's release as applying
  `loom:auto-merge-ok` — but in the surrounding tooling that label is an
  *override of a merge-risk hold*, not a merge precondition, so its **absence
  blocks nothing**. No required check, no label gate, and no script asserts
  the `RATIFY-KEY` review count before a `spec/` change merges. That is why an
  explicit, correct stand-down comment on PR #29 was followed by a merge 4m37s
  later: the stand-down was prose, and nothing mechanical was watching. Filed
  as its own defect (see issue #45) — a repair that only adds documentation
  would leave the same hole open.

## How this gets closed

In order, and not skippable:

1. **Operator ruling on the independence question** above — agent-held keys in
   separate fleet sessions, or distinct forge principals.
2. **If distinct principals are required**: the operator provisions the second
   identity (a mechanical, credential-holding act no agent can perform), and
   the keys are run under it.
3. **Two `RATIFY-KEY` reviews on a carrying PR** — one `ee`, one `market`,
   distinct `reviewer=` values, neither the carrying PR's author nor the
   design's author, each matching its skill's § "Output format" grammar.
4. **A `0007` record** reporting the act: the carrying PR, both review URLs,
   both verdicts, the merge commit, and which of DRs 0001–0005 and which
   `spec/target-spec.md` rows it binds. The merge commit of *that* PR is the
   ratification record, per the mechanism.
5. Status lines across `spec/` move to `Ratified` **at that point and not
   before**, each citing `0007` and the merge commit rather than citing a
   process description.

Until step 4 lands, every `Status:` line under `spec/` says `DRAFT`,
`Proposed`, or `Recorded`, and the repository's governance claims and its
forge record agree.
