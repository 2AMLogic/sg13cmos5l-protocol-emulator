# 0004: Target-Spec Ratification

Status: Ratified 2026-09-21 — this record is itself part of the act it
describes: it is ratified by the same two `RATIFY-KEY` reviews on the
carrying PR that ratify `spec/target-spec.md` (see "The binding process"
below). If that PR merged without both key reviews, this record's
`Ratified` line is invalid until superseded by a later record that says so.
Date: 2026-09-21
Issue: #17

## Context

T1 item 5 ("Full corner verification vs a **ratified** spec" —
`manifests/design-evidence-tiers.md`, vendored from
`2AMLogic/klayout-tools`) makes a ratified spec table the precondition for
every evidence-graded claim this repo can make: verdicts produced against a
draft spec are provisional by construction, and the mechanical T1 grading
this repo already runs (the `scripts/signoff-report.sh` baseline of
2026-09-21, `0/11` items met) reports blocks like this one as blocked at
item 5 until the spec it would grade against is ratified. The same held for
items 6, 7 and 8, which grade against spec rows.

Two things stood in the way, both scoped by issue #17:

1. **This repo had no `ratification/` tree** — the program's two-key
   (RATIFY-KEY) mechanism had nowhere to record a key, so a ratification
   PR would have been an assertion, not a mechanism (the identical gap in
   `2AMLogic/sg13g2-comparator` is that repo's issue #19). This PR installs
   the mechanism's generated reviewer variants —
   [`ratification/ee-key/`](../../ratification/ee-key/SKILL.md) and
   [`ratification/market-key/`](../../ratification/market-key/SKILL.md) —
   byte-identical to the fleet's installed copies, so both key skills,
   their rubrics, and the marker convention each key review opens with are
   documented in this repo itself.
2. **No measurement exists to ratify.** This block predates its own RTL:
   `rtl/` is empty except for a stub README, both flows have produced
   cell counts only, and no protocol has been run by anything. What a
   ratification *can* and *should* bind at this stage is the target table
   itself — every row's value, its citable source, and the verification
   artifact that will check it — with each row's current state said out
   loud so that binding the targets never becomes a claim that they are
   met. Separating those two axes (what is bound vs. what is evidenced) is
   the load-bearing design of this record.

## Decision

`spec/target-spec.md` is **ratified, as targets**, in full:

- **All twelve rows are ratified as the binding spec-of-record** — their
  values, sources, stretch entries, and checking artifacts bind. Each
  row's state is explicit in the register below and condensed into the
  spec's new **State** column.
- **No row is carried as met except where the register says so**: row 5 is
  the only row whose checking artifact exists and passes *for the current
  stub top*. Rows 2 and 10–12 are ratified as targets with **no evidence
  at all** (said per row, per issue #17's own wording, "ratified as
  *targets*, and say so, rather than silently carrying them as met").
- **Rows 4 and 7 are ratified as targets and are explicitly barred from
  being read as met**: both flows have produced cell counts only — record
  `20260914-203044-45af1c2.md` (LibreLane, superseding
  `20260914-032200-7e4a21a.md`) and the klt baseline it reconciles with —
  and no run of either flow has reported a clock period, an STA result, or
  a die area. A synthesis run that did not measure a number cannot stand
  behind "≥ 50 MHz timing closure" or "≤ 2×2 tiles" as *met*; the
  register's row-4/row-7 statements are the bar against that reading, and
  issues #20 and #21 track the missing evidence.
- **Decision records 0001 (ISA), 0002 (flow of record), and 0003
  (firmware toolchain) are carried into force** — `Proposed` →
  `Ratified` on each record's own Status line. None was returned to draft:
  each was authored with its ratification deliberately pending on this
  table (`Status: Proposed (pending ratification alongside
  spec/target-spec.md)`), none contains a defect or an unowned claim that
  would justify returning it, and 0002's two upstream klayout-tools gaps
  (the CMOS5L platform entry [#1784] and the corner-naming resolver
  [#1786]) are both closed as of this ratification, so the two-flow policy
  it binds has already been exercised live without its assumptions
  changing.

The binding process is what makes the above a ratification rather than an
assertion — see the next section.

## The binding process (two-key; merge commit = ratification record)

Per the program's two-key mechanism ([`ratification/ee-key/SKILL.md`](../../ratification/ee-key/SKILL.md),
[`ratification/market-key/SKILL.md`](../../ratification/market-key/SKILL.md)):

- **Two independent, non-author keys** review the carrying PR: an **EE
  key** (technical soundness — device/budget plausibility of each claimed
  source and target, evidence-tier reading, sibling-canary precedent) and
  a **market key** (competitiveness of the externally-observable rows
  against public comparable parts). **Neither key may be held by the PR's
  author or the design's author.** Each key posts one PR review opening
  with a `RATIFY-KEY: <ee|market> verdict=… block=… reviewer=… date=…`
  marker line (the grammar both skills' "Output format" sections define).
- The second key-holder's application **releases the PR for merge**
  (`loom:auto-merge-ok` plus a consolidated ratification-record comment
  quoting both keys with links to the reviews). **The merge commit is the
  ratification record.**
- Approvals inside the ordinary Loom pipeline (Judge, Champion) are
  **quality gates, not keys**. A merge of the carrying PR without both key
  reviews does not enact this ratification: in that case this record and
  the Status lines it flips are assertions without a mechanism, and a
  later record must reopen them rather than inherit them.

## Per-row register (ratification-time snapshot)

Evidence states below are as of 2026-09-21, recorded so the binding of each
target is never confused with its being met. `spec/gap-to-submission.md`
remains the live met/unmet tracker of record; issue numbers are this repo's
tracking vehicles.

| # | Row | Ratified as | Evidence state at ratification | Tracked by |
|---|---|---|---|---|
| 1 | Protocols emulated in firmware | Binding target (UART/SPI/I2C parameter sets as stated) | Unmet — no RTL, no firmware, no protocol suite. Sufficiency evidence: DR 0001's per-protocol cycle-budget sketches (1 Mbaud/9,600-baud UART, SCLK ≤ f_clk/4 SPI, Fast-mode I2C timing math) | #18, #19 (RTL), #22, #23 (firmware), #25 (suites) |
| 2 | Stretch protocols | Stretch aim only — **nothing numeric is bound** (the row's own entry condition — a DR 0001 cycle-budget sketch for USB 1.1 / 10BASE-T — is unmet, so the committed table gains no value) | Unmet, no evidence; explicitly deferred, not blocking core-protocol submission | gap tracker row 2 (deferral recorded 2026-09-14) |
| 3 | Timing determinism | Binding target (the no-data-dependent-latency guarantee) | Unmet as a *checked* property — the formal property `no_data_dependent_latency` is named but not written; the guarantee itself is bound via DR 0001 | #24 |
| 4 | Core clock ≥ 50 MHz | Binding target | Unmet and **not carried as met**: both flows report cell counts only (records `20260914-203044-45af1c2.md`, `20260914-032200-7e4a21a.md`); no STA result exists on either flow. The target's source is the repo's own standup baseline — confirmation of achievability is the flow-of-record's future STA run, not this record | #20 |
| 5 | I/O pin budget | Binding target | **Met at the stub level**: `src/tt_um_2amlogic_protocol_emulator.v` instantiates the full fixed template budget, `info.yaml` declares the pinout, and the template's own cocotb `test/` suite (green on `main`) drives that top. Protocol pin-role assignment is deliberately a later decision record (the stub's `info.yaml` says its pinout labels are placeholders) | row 5 of gap tracker |
| 6 | Program storage 256×16, serial load | Binding target (sizing + load protocol bound via DR 0001) | Unmet — no program-memory or load-phase RTL; the cocotb load-phase test is unwritten | #19 |
| 7 | Area ≤ 2×2 tiles | Binding target | Unmet and **not carried as met**: no die-area or floorplan number exists on either flow; cell counts are not area (the LibreLane run produced placement checkpoints, never a die-area report — record `20260914-203044-45af1c2.md`). Tile pitch itself is resolved (~167 × 108 µm per tile, per the template's `info.yaml`, recorded in gap tracker row 7) — the area half is the open half | #21 |
| 8 | Verification (cocotb + gate-level + formal + constrained-random w/ reference models) | Binding target (the verification *shape*) | Partially realized — cocotb harnesses (template `test/` + this program's `verification/`) and the gate-level regression (`gl_test`, green) exist and pass **on the stub**; the formal properties and the constrained-random suites with independent reference models do not exist | #24, #25 |
| 9 | Submission (Apache-2.0, TT CMOS5L template, 2027-01-18) | Binding target | On track, deadline pending — license set repo-wide, template wiring landed verbatim, the `gds`-workflow sign-off chain (`gds`/`precheck`/`gl_test`/`viewer`) is green end to end on the stub (run `34905475502`); the submission itself is due 2027-01-18 | gap tracker row 9 |
| 10 | UART bit-timing accuracy (~2% per-frame drift bound) | Binding target | Unmet, **no evidence yet** — the tolerance bound is adopted from common asynchronous-serial practice (NXP AN10406 et al.); the UART constrained-random suite + reference model that would measure it do not exist. Ratified as a target, not carried as met | #25 |
| 11 | SPI ceiling/modes 0–3 | Binding target | Unmet, **no evidence yet** — modes/ceiling follow the Motorola/Freescale SPI Block Guide conventions; the SPI suite does not exist. Ratified as a target, not carried as met | #25 |
| 12 | I2C SM/FM timing minimums | Binding target | Unmet, **no evidence yet** — the minimums are UM10204 Rev. 6 Table 10 values; the ACK-window formal property and the I2C suite do not exist. Ratified as a target, not carried as met | #24, #25 |

**Rows 4 and 7's shared bar, stated once more plainly, because cell-count
runs are the nearest thing this repo has to "results" and the temptation is
to read them as met:** a synthesis record that reports gates-per-stage
without an STA check proves the flow runs, not that 50 MHz closes; a run
through placement without a die-area report proves placement happened, not
that the result fits 2×2 tiles. Neither row may be recorded as met on the
strength of either record. That is the T1 checklist's own freshness rule
(the signoff baseline's 0/11 verdict already grades this block accordingly)
and it is inherited here verbatim.

*klayout-tools issue citations above: [#1784] and [#1786] are
`2AMLogic/klayout-tools` issues 1784 and 1786, both closed as of
2026-09-21.*

## Alternatives considered

**Ratify only evidenced rows (the measured-row pattern sibling canaries
use).** Rejected for this repo, at this stage: this block has zero
measured rows — it precedes its RTL — so an evidence-gated ratification
would bind nothing and change nothing. The measured-row pattern suits a
block whose benches already produce numbers to pick bounds from; here the
ratification's entire job is to bind the *targets* so that every future
corner run, formal check, and constrained-random comparison has something
authoritative to be verified *against* (T1 item 5's precondition). Waiting
for evidence inverts the dependency: the evidence tiers need the ratified
spec first.

**Treat ordinary pipeline approval (Judge/Champion sign-off, or operator
approval) as the ratification.** Rejected: the spec's own pre-ratification
text (and issue #17's mandate) committed this repo to the two-key
mechanism, whose entire point is that no interested party — including the
agent that drafted the spec, the DRs, and this record — can ratify its own
work. A merge without the keys is expressly recorded above as *not* a
ratification.

**Return one or more of DR 0001/0002/0003 to draft instead of ratifying.**
Considered per record; rejected per record, with reasons on each flip line.
Nothing in the three records contradicts the ratified table or cites
evidence that has since failed; DR 0002 is the only one whose live state
moved (both klayout-tools gaps closed), and its policy was written to be
correct in exactly that world — the workaround note in its Status area
records the retirement as follow-up work.

## Consequences

- The spec-of-record now exists: T1 item 5's precondition is satisfied.
  The next evidence runs (STA on the flow of record, the formal properties,
  the constrained-random suites) grade *against these rows*, and their
  verdicts are no longer "provisional by construction."
- `spec/gap-to-submission.md` remains the live per-row evidence tracker —
  this register is the ratification-time snapshot; the two are explicitly
  not duplicates (bound-target state lives here, met/unmet progress lives
  there).
- Every future change to a ratified row goes through a new decision record
  (per `CLAUDE.md`'s "Spec changes go through `spec/` with a decision
  record" rule, restated in `spec/target-spec.md`'s Ratification section) —
  and a *relax of a previously-ratified row to make a failing measurement
  pass* is the one change form that escalates rather than quietly
  accepts: both key skills run a relax-after-measured-FAIL check (their
  Step 5) exactly so "agents never relax a ratified spec to make results
  pass."
- The market key operates without bundled comp data for now: this block's
  class has no seeded comp-library entry, so the key researches public
  comparables from scratch per its own installed-mode Step 0. Seeding the
  class entry upstream is tracked follow-up work (see the carrying PR's
  body). This changes nothing about the key's authority — only its
  starting point.

[#1784]: https://github.com/2AMLogic/klayout-tools/issues/1784
[#1786]: https://github.com/2AMLogic/klayout-tools/issues/1786
