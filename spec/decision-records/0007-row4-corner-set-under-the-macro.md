# 0007: Row 4's Corner Set Under a Three-Corner-Characterized Macro

Status: **Proposed 2026-10-02.** It goes to ratification through the
program's two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"). It binds only when that
PR's history shows **two** `RATIFY-KEY` reviews, one EE key and one market
key, neither held by this record's author, and the merge commit is the
ratification act. As
[`0006-two-key-ratification-never-ran.md`](0006-two-key-ratification-never-ran.md)
records, that mechanism has never run in this repository (issue #44), so for
now this record is a proposal, the same way DRs 0001–0005 are. It does
**not** make target-spec row 4 met, and nothing in it may be cited as
though it did.
Date: 2026-10-02
Issue: #69

**Numbering note.** DR 0006 § "How this gets closed", steps 4–5, names the
future ratification-act record "a `0007` record". This record took 0007
because it was the next free number when this record was filed, which is
how this directory numbers its records. Read DR 0006's "`0007`" as "the next
free number when the act happens". That record's list of what it binds
must also include this one. DR 0006 carries a dated note to the same effect.

## New record, not an amendment to DR 0005

This is a **standalone record that depends on DR 0005**. It does not amend
DR 0005, for three reasons:

1. **It decides something different.** DR 0005 decides what holds the
   program bits, and its Decision item 6 explicitly leaves
   `spec/target-spec.md` alone. This record decides how a target-spec row
   is graded: which PVT points row 4's timing closure is checked at. If this
   were folded into DR 0005, one record would contain two independent
   ratification questions, and a key-holder could not accept one and reject
   the other.
2. **The corner set came up as its own follow-up before the macro existed.**
   On 2026-09-21 the six-corner declaration was recorded in
   `spec/gap-to-submission.md` row 4 with the note "folding the corner
   matrix into a spec decision record of its own is tracked follow-up". This
   is that record. The macro forces the question but did not create it.
3. **It still depends on DR 0005, and says so.** This record's corner set
   exists only because of the macro. If DR 0005 is superseded, this record
   lapses with it (see "Lapse condition" below). Under DR 0005 open item 1,
   that would happen if the shuttle does not admit an SRAM macro and the
   flip-flop fallback becomes the live option.

DR 0005 carries a dated status note pointing here. Its body is not edited.

## Context

### What row 4 says, and where the six corners actually live

`spec/target-spec.md` row 4 states the target as "≥ 50 MHz timing closure
on CMOS5L (flow of record per DR 0002)". Its checked-by entry is "Static
timing analysis in the flow-of-record's sign-off run". **The row text has
never named a corner set.** DR 0002 names the Tiny Tapeout LibreLane flow as
the flow of record.

The six-corner set lives in two other places:

- **`flow/run-sta-corner-sweep.sh`** (PR #31, commit `4d0a581`,
  2026-09-21). Its `ALL_CORNERS` lists all six shipped
  `sg13cmos5l_stdcell` liberty corners: `slow_1p08V_125C`,
  `slow_1p35V_125C`, `typ_1p20V_25C`, `typ_1p50V_25C`, `fast_1p32V_m40C`,
  `fast_1p65V_m40C`. Its header says "This sweep IS the corner-set
  declaration for target-spec row 4". It also states the rule behind the
  list: "the set this block is held to is the PDK's own shipped set, pending
  the spec's own ratification machinery (issue #17) folding it into a
  decision record."
- **`spec/gap-to-submission.md` row 4**, in its 2026-09-21 dated note, which
  repeats that declaration.

The PR #70 evidence record and issue #69 then graded row 4 against those
six corners. This record treats that as a real, de facto declaration. It
does not treat it as a loophole, because the evidence trail has relied on
it. It also states plainly that the six corners were declared in a klt-leg
script and a progress tracker, and that the spec row itself never named
them.

### Order of events

| Date | Event | Source |
|---|---|---|
| 2026-09-21 | Six-corner set declared. The design has **no macro**: the program memory is a flip-flop array, so every cell in the design is an `sg13cmos5l_stdcell` cell characterized at all six corners | PR #31 / `4d0a581`; gap tracker row 4 |
| 2026-09-25 | DR 0005 adopts `RM_IHPSG13_1P_256x16_c2_bm_bist` (`Proposed`) | PR #43 / `a59a0f3` |
| 2026-09-30 – 10-01 | Macro integrated (#18, #60). `src/config.json` maps the macro's three shipped liberty files onto the flow's corner globs | `src/config.json` `MACROS` → `lib` |
| 2026-10-02 | Row-4 evidence minted. The three corners the LibreLane flow emits all close | `verification/records/librelane-corner-timing/records/20261002-095445-21a2a63.md` (PR #70) |

The six-corner set was the right declaration for the design that existed
when it was made. It stopped describing the design four days later, when
DR 0005 replaced the flip-flop array with a macro. The PDK ships that macro
characterized at three PVT points and no others:
`..._typ_1p20V_25C.lib`, `..._slow_1p08V_125C.lib`, and
`..._fast_1p32V_m55C.lib`. None is above **1.32 V**.

### What the evidence says (LibreLane flow only)

Every number in this record comes from the **LibreLane flow** (LibreLane
`3.1.0.dev3` via `tt-gds-action@ihp-cmos5l`, OpenSTA, post-route, CI run
36837745318 @ `21a2a63`), copied from the evidence record above. None was
re-measured for this record. The **klt flow has no number** for this
design: `klt sta` cannot declare the macro, and fails 0 of 6 corners
(`2AMLogic/klayout-tools#2635`, record
`sta-corner-sweep/records/20260930-195410-ead870a.md`). So there is no
cross-flow disagreement to reconcile here, and none is created.

| corner (as the flow names it) | std-cell liberty | macro liberty | worst setup (ns) | worst hold (ns) |
|---|---|---|---|---|
| `nom_slow_1p08V_125C` | `slow_1p08V_125C` | `slow_1p08V_125C` | +9.6214 | +0.6718 |
| `nom_typ_1p20V_25C` | `typ_1p20V_25C` | `typ_1p20V_25C` | +13.5576 | +0.3228 |
| `nom_fast_1p32V_m40C` | `fast_1p32V_m40C` | **`fast_1p32V_m55C`** | +14.6486 | **+0.1156** |

All three corners have 0 setup and 0 hold violations at the 20 ns
constraint. The binding hold corner is the fast one. It is also the only
corner where the two libraries do not describe the same PVT point.

## Decision

**Option 1, with three additions that keep it from being a relaxation.**

1. **Row 4's corner set is the set of PVT points at which every cell in
   the design is characterized.** That is the 2026-09-21 rule ("the PDK's
   own shipped set") applied to the whole design rather than to one library
   in it. For the macro-backed design this gives **three** corners, each
   defined as a voltage-matched pairing of a standard-cell liberty and a
   macro liberty:

   | design corner | std-cell liberty | macro liberty | match |
   |---|---|---|---|
   | slow | `sg13cmos5l_stdcell_slow_1p08V_125C` | `..._slow_1p08V_125C` | exact (P, V, T) |
   | typ | `sg13cmos5l_stdcell_typ_1p20V_25C` | `..._typ_1p20V_25C` | exact (P, V, T) |
   | fast | `sg13cmos5l_stdcell_fast_1p32V_m40C` | `..._fast_1p32V_m55C` | **V matched, T differs by 15 °C**. This is a known approximation, resolved in § "The fast-corner temperature pairing" |

2. **The three high-voltage standard-cell corners (1.35 V, 1.50 V, 1.65 V)
   are recorded as uncharacterized for this design, not as passed.** No
   sign-off claim is made at those supplies. Any statement of the submitted
   design's operating range says **1.08–1.32 V core supply**: sign-off
   covers that range and nothing above it.
3. **The set is fixed before grading and does not depend on results.** A
   setup or hold violation at any of the three corners is a row-4 failure.
   No corner may later be dropped, re-paired, or re-labelled because of a
   result. Only a later record that changes the *characterization facts*
   (a different macro, a new macro liberty, or DR 0005's supersession) can
   change the set.
4. **Row 4 is not carried as met on the strength of the fast-corner hold
   margin until open item 1 below is resolved.** This adds to the bar the
   row had before. It does not lower it.

### Lapse condition

If DR 0005 is superseded and the program memory goes back to standard
cells, this record lapses **automatically**, and row 4's corner set reverts
to all six `sg13cmos5l_stdcell` corners. Under the rule in Decision item 1,
those six are again the set at which every cell in the design is
characterized. This is the main protection against a relaxation: the
narrowing follows the structural cause (a macro with three
characterizations), not the result (three corners that happened to pass).

### Why this is a correction and not a relaxation

`CLAUDE.md` says "Agents do not relax the ratified spec to make a result
pass". The issue rightly calls this option the one that rule is most
suspicious of. This record's answer:

- **The declaration came first.** The six corners were declared on
  2026-09-21 for a design with no macro. DR 0005 adopted the macro on
  2026-09-25. The six-corner list was correct when written and went stale
  when the design changed, not when a result came in. Fixing a declaration
  that a later design decision made stale is a correction.
- **The rule is kept; only its scope changes.** The rule recorded in
  `flow/run-sta-corner-sweep.sh` is "the PDK's own shipped set". For the
  macro-backed design, the PDK's shipped set for the *design* is three
  points, because a macro corner that is not shipped cannot be part of it.
  Six corners would mean pairing standard cells at 1.35 / 1.50 / 1.65 V with
  a macro characterized at some other supply. As PR #70's record puts it,
  that is a voltage mismatch, not a corner.
- **The result does not choose the set.** The three remaining corners are
  the ones the macro is characterized at. They are not the ones that passed:
  had `slow_1p08V_125C` failed setup, it would still be in the set and row 4
  would read FAIL. The three dropped corners were never measured for this
  design and *cannot* be. This record does not drop a single measured
  result.
- **The bar gains a condition.** Decision item 4 adds a requirement that did
  not exist before: the fast-corner temperature pairing must be resolved
  before the binding hold margin is relied on.
- **It is not self-ratifying.** It goes to the same two keys as every other
  spec change. Neither key's Step 5 relax-after-measured-FAIL check
  applies, because nothing failed. The keys can still reject this record.
  The status quo on rejection is described under option 2.

## The fast-corner temperature pairing

The fast corner pairs a **−40 °C** standard-cell liberty with a **−55 °C**
macro liberty, both at 1.32 V. It carries the thinnest margin in the
evidence: +0.1156 ns of hold slack, LibreLane flow. This record states the
pairing explicitly as a **known approximation** and does not adopt it as the
silent definition of "this design's fast corner". It then asks whether that
approximation is pessimistic or optimistic for hold.

**Finding: the sign is not established, and this record does not claim one.**
The argument:

Let Δ be the difference between the macro's timing as characterized at
−55 °C and what a −40 °C characterization at the same process and voltage
would show. Hold paths fall into three classes:

- **(A) No macro pin on the path.** Δ enters only through second-order
  loading: the macro's `A_CLK` pin capacitance on the clock tree, and its
  input-pin capacitances on their drivers. Those effects are small, and
  their sign is not established.
- **(B) The macro launches the path** (`A_CLK → A_DOUT`, captured by a
  standard-cell flop). Hold slack rises with the macro's minimum
  clock-to-output delay. *If* the macro is faster at −55 °C than at −40 °C,
  the characterization understates that delay and the hold slack it reports
  is **pessimistic**, which is safe. *If* the process shows temperature
  inversion at 1.32 V (colder is slower), the reported slack is
  **optimistic**, which is unsafe.
- **(C) The macro captures the path** (hold checks on `A_ADDR`, `A_DIN`,
  `A_WEN`, `A_MEN`, `A_BM` against `A_CLK`). Hold slack is data arrival
  minus (clock arrival at `A_CLK` plus the macro's hold requirement). How
  that requirement moves with temperature depends on the macro's internal
  clock and data paths. No general argument fixes its sign, even if the
  answer for class B is known.

Neither question that would settle the sign can be answered from data in
this repository:

- **No −40 °C macro characterization exists to compare against.** The macro
  ships exactly one fast liberty file. Its three shipped files change
  process, voltage, and temperature together, so they cannot show a trend
  in temperature alone.
- **Whether this process inverts at 1.32 V is not measured anywhere in this
  repo.** Conventional expectation, with supply well above threshold, is
  that colder is faster, which would make class B pessimistic. That is an
  expectation and not a measurement, so this record does not assert it.
- **Which class the binding hold path is in is not established.** The
  evidence artifact
  (`librelane-corner-timing/artifacts/20261002-095445-21a2a63/librelane-sta-metrics.json`)
  shows `timing__hold_r2r__ws` at the fast corner as 0.115626 ns, the same
  as the overall `timing__hold__ws` of 0.1156255124373293 ns. So the
  binding hold path is register-to-register *by the flow's own
  classification*. The committed metrics do not say whether OpenSTA's
  register set includes the macro. The macro's liberty has a `memory()`
  group but no `ff`/`latch` group. That cannot be resolved without the
  run's path report, which is not committed.

**Consequence for `src/config.json`.** The comment beside its `MACROS` →
`lib` block says the −55 °C macro liberty "makes the fast corner slightly
pessimistic for the macro". For hold, this record cannot support that claim
in general. It holds at most for class B, and only under the no-inversion
expectation. For class C it is undetermined. The comment is **not edited
in this record's PR**, because `src/config.json` is a content-hashed input
of the row-4 evidence record. Editing it would make
`verification/check_records.py` fail that record and force a re-mint for a
comment-only change. This record is the correction on file. The comment
should be reworded the next time `src/config.json` changes for a
substantive reason.

## Options considered

**Option 1: re-declare the bar as the corners the design can be
characterized at (3).** **Proposed**, with the additions in § Decision.
Cost: it narrows a de facto bar after a passing result exists, which is the
pattern `CLAUDE.md` warns about. That cost is paid openly in "Why this is a
correction and not a relaxation". It is limited by the lapse condition and
by the result-independence rule, and it is offset by the open item that
adds to the bar.

**Option 2: keep six corners and record row 4 as permanently partial.**
Rejected. It is the most conservative option on paper, but it records
*uncharacterized* as if it meant *not met*. A row that can never read
"met" for the design the project has committed to is not a target. It
becomes a standing false negative that every later review has to explain
away, and T1 item 5 could never close no matter how good the timing is. It
also hides the real open risk, the fast-corner pairing, behind a structural
gap that no work can close. **This is also the status quo:** until this
record is ratified, row 4 reads "closes at three of six declared corners,
three structurally unreachable". `spec/target-spec.md` and
`spec/gap-to-submission.md` say exactly that, and they say it again if the
keys reject this record.

**Option 3: split the row** (three corners for macro-backed paths, six for
standard-cell logic). Rejected. In a single-clock design, no standard-cell
timing graph at 1.35–1.65 V can exclude the macro. Its arcs either drop out
of the analysis, which leaves every path into or out of program memory
unconstrained and reports coverage that does not exist, or they come from a
liberty at another supply, which is the voltage mismatch option 1 refuses.
Neither flow can produce the split today: LibreLane emits three corners and
the klt leg is blocked on `klayout-tools#2635`. Building that machinery
would produce a statement about a chip that cannot be operated as stated.
If a key-holder wants six-corner standard-cell figures, they can be recorded
as **informational**, not as a bar.

**Option 4: change the design so six corners become reachable.** Rejected,
for DR 0005's reasons. The flip-flop memory needs 2.46×–2.98× the *entire*
2×2 core in cell area alone. The macro reduces the memory's area
11.1×–13.4× (DR 0005: 312,062.8896 µm² klt flow / 378,066.857 µm² LibreLane
flow, against 28,127.104 µm²). The alternatives would give up row 7's ≤ 2×2
target, or row 1's capability through a smaller program, in exchange for
three corners at supplies the design need not run at. Nothing in this repo
shows that any other macro is characterized above 1.32 V. This option
returns automatically through the lapse condition if DR 0005 is ever
superseded for its own reasons.

## Consequences

- **`spec/target-spec.md` row 4**: the Target column is **unchanged**,
  because it never named a corner set. The State column's stale sentence
  ("both flows have produced cell counts only, never a clock period or STA
  result") is replaced with the PR #70 evidence state and a pointer to this
  record. The row stays **unmet; not carried as met**. Three things keep
  it unmet: this record is `Proposed`, `spec/target-spec.md` is
  `PROPOSED — not ratified`, and open item 1 is unresolved.
  *Dated note 2026-10-10 (issue #85, item 3):* the row 4 State cell no
  longer gives the spec's own ratification status as a reason the row is
  unmet. That reason would contradict the cell the moment the spec is
  ratified. The cell now says the row's Target names no corner set, that
  this record (Proposed) proposes one, that open item 1 is unresolved, and
  that the klt flow has no result. Nothing in this record's decision
  changes.
- **`spec/gap-to-submission.md` row 4** gets a dated note. Its Status cell
  names this record as the proposed resolution of the corner-set question.
- **`flow/run-sta-corner-sweep.sh` is not changed by this record's PR.** The
  klt leg's `ALL_CORNERS` list is the klt flow's declaration, and it should
  change only once this record binds. On ratification, the follow-up
  narrows that list to the three paired corners and adds the macro's
  liberty per corner, which `klayout-tools#2635` blocks today. Or it keeps
  six and labels the three high-voltage runs as standard-cell-only
  informational output.
- **T1 item 5** ("Full corner verification vs a ratified spec") stays
  unmet: the spec is unratified (#44). This record clarifies which corners
  item 5 will eventually be graded at, and does not satisfy item 5.
- **Two flows, one record of truth.** When `klayout-tools#2635` lands, the
  klt leg's three-corner result is compared against the LibreLane numbers
  above. Any mismatch is a finding to record. Neither flow's number gets
  chosen over the other.

## Open items (assigned, not left hanging)

1. **Find out which class (A/B/C) the fast-corner binding hold path is in.**
   Read the endpoints from the LibreLane run's own STA path report. That
   means reading an existing artifact of run 36837745318 or of a later
   flow-of-record run, not a new measurement. If neither endpoint is a
   macro pin and no macro arc is on the path (class A), the 15 °C pairing
   is second-order for that margin, and this item closes by recording so.
   If the macro launches or captures the path (B or C), +0.1156 ns stays
   unrelied-on until either IHP supplies a −40 °C characterization (or a
   statement of the macro's temperature sensitivity), or a later record
   bounds Δ from data. Tracked under #20 (T1 item 5 / row-4 evidence).
2. **Confirm the shuttle's nominal core supply is inside 1.08–1.32 V.**
   Decision item 2 limits sign-off to that range. Whether the CMOS5L Tiny
   Tapeout shuttle runs the core inside it is not recorded anywhere in this
   repo. If it does not, this record is incomplete, and a later record must
   say so.
3. **Reword the `src/config.json` corner comment**, as described in "The
   fast-corner temperature pairing". Do it the next time that file changes
   for a substantive reason, not as a standalone edit.
4. **Ratification.** This record, DRs 0001–0005, and `spec/target-spec.md`
   are waiting on the same two-key act (DR 0006 § "How this gets closed";
   #44, #45).
