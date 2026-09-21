# 0002: Flow of Record

Status: Ratified 2026-09-21 — carried into force with `spec/target-spec.md`'s
ratification via the two-key mechanism, recorded in
`0004-target-spec-ratification.md` (issue #17: the ratifying PR's two
`RATIFY-KEY` reviews and merge commit are the act). **Live-state note,
2026-09-21:** both upstream klayout-tools gaps this record filed are
closed as of this ratification ([#1784](https://github.com/2AMLogic/klayout-tools/issues/1784)
— CMOS5L platform entry; [#1786](https://github.com/2AMLogic/klayout-tools/issues/1786)
— corner-naming resolver), so the klt-side iteration flow is no longer
upstream-blocked. Retiring this repo's interim direct-Yosys workaround
(`flow/run_synthesize_direct_yosys.py`) for a plain `klt synthesize` call
is implementation follow-up work, deliberately not part of this
ratification; the two-flows reconciliation policy below binds unchanged.
Date: 2026-09-14
Issue: #1

## Context

Two implementation flows exist for this program, and they do not agree
today:

1. **The competition's sign-off flow**: the
   [Tiny Tapeout CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l)
   runs [LibreLane](https://github.com/librelane/librelane) in GitHub
   Actions to go from RTL to a submittable GDS. This is the flow the
   competition actually accepts a submission through.
2. **This program's own digital flow**: `klt synthesize` /
   `klt functional-verification` / `klt drc` (klayout-tools) driving Yosys
   for synthesis and OpenROAD for place-and-route, per `CLAUDE.md`'s
   "Harness bootstrap" instruction to port this half of the flow from
   `2AMLogic/sky130-modexp`. As of this repo's standup
   (`layout/toolchain.json`, 2026-09-12), klt's synthesize/PAR platform
   table has **no IHP CMOS5L entry** — this flow cannot run against this
   PDK yet at all.

`CLAUDE.md` is explicit that a mismatch between the two flows "is a finding
to record, not a number to pick from" — so this record has to say which
flow is authoritative for what, not just note that they differ.

## Decision

**The Tiny Tapeout CMOS5L template's LibreLane-in-GitHub-Actions flow is the
flow of record for the submitted GDS.** It is the only flow the competition
accepts, it is the only flow with a working CMOS5L standard-cell platform
today, and per `CLAUDE.md`'s "Harness bootstrap" section its wiring
(`info.yaml`, the `tt_um_*` top, the template's `test/` cocotb harness, and
its `gds`/`test`/`fpga` Actions workflows) is to be taken **verbatim** from
the template's `cmos5l` branch — this repo does not fork or reinterpret that
half of the flow, it inherits it.

**`klt`/Yosys/OpenROAD is the flow used for day-to-day iteration**, once its
CMOS5L platform gap (below) is closed — synthesis-area estimates, quick
functional-verification turnaround, and DRC/LVS against `klt drc` during
development, per the bootstrap instruction to port the RTL→GDS half of the
harness from `2AMLogic/sky130-modexp` (its `klt synthesize` /
`klt functional-verification` / `klt drc` entry points, cocotb bench layout
under `verification/`, gate-level regression, and `flow/*.json` recipe
shape). **This porting work is out of scope for this issue** — issue #1
ratifies the decision of which flow is which; issue #2 (per `CLAUDE.md`,
already filed) is where the harness itself gets built.

### Reconciliation policy

The two flows are expected to disagree, at minimum on area and timing
margin, because they use different synthesis tools and cell libraries were
they to both target CMOS5L (Yosys+OpenROAD vs. LibreLane's internal flow)
even once both point at the same PDK. When they disagree:

1. **The flow-of-record's number is the one reported in any submission-
   facing claim** (the target-spec table, README, competition materials).
   A `klt`/Yosys/OpenROAD number is never substituted for a LibreLane number
   to make a target-spec row look met.
2. **Every reported synthesis or timing number must name which flow
   produced it** (`CLAUDE.md`'s rule, restated here as this record's
   concrete mechanism): a number with no flow attribution is treated as
   unusable evidence in `spec/verification-plan.md`'s append-only record.
3. **A disagreement between the two flows on a target-spec commitment
   (e.g., one flow closes timing at 50 MHz and the other doesn't) is logged
   as a gap-to-submission entry**, not silently resolved by preferring one
   flow's answer — the discrepancy itself is evidence about flow parity
   that a later reader needs, per `CLAUDE.md`'s "no claim without a
   testbench" / append-only philosophy applied to tool-flow parity, not
   just functional correctness.
4. The klt-side gate-level regression (once it exists) is still required to
   pass on its own terms — it is not exempted from correctness just because
   it is not the flow of record. It exists to catch RTL bugs early and
   cheaply; the flow-of-record run is the one whose GDS actually gets
   submitted.

## klayout-tools gap filed

Per the brief's "Friction protocol," the missing IHP CMOS5L platform entry
in klt's synthesize/PAR platform table is filed as a **generic tool gap**
(no design-specific detail from this repo) against `2AMLogic/klayout-tools`:

**Issue**: https://github.com/2AMLogic/klayout-tools/issues/1784 —
"synthesize/PAR platform table has no IHP CMOS5L (sg13g2/SG13CMOS5L) entry"

(Filed as part of this decision record's ratification — see
`spec/gap-to-submission.md` for the tracked status of this gap and its
effect on when the klt-side iteration flow can come up.)

## Alternatives considered

**Treat `klt`/Yosys/OpenROAD as the flow of record and submit through it
directly.** Rejected: the competition's submission mechanism is the Tiny
Tapeout CMOS5L template's own Actions-driven LibreLane flow; a GDS produced
outside that flow is not a valid submission artifact regardless of its
quality, and klt has no CMOS5L platform entry to produce one with today
regardless.

**Wait for the klt CMOS5L platform gap to close before doing any
iteration**, rather than splitting flow-of-record (submission) from flow-
for-iteration (day-to-day). Rejected: this would block all RTL/verification
progress on an external tool-repo timeline this program does not control,
which conflicts with the 2027-01-18 deadline discipline in `CLAUDE.md`. The
template's own cocotb `test/` harness and LibreLane flow are usable for
iteration in the meantime (they are, after all, the actual sign-off path),
so the "iteration flow" is not blocked even while klt's CMOS5L gap is open
— it is only the *klt-specific* iteration conveniences (its DRC/LVS
tooling, its synthesis-recipe shape from `flow/*.json`) that wait on the
gap.

## Consequences

- Nothing in `layout/` or `flow/` in this repo can claim a working CMOS5L
  synthesis/PAR run until the klt platform gap closes; until then, the
  template's own LibreLane Actions runs are this program's only source of
  real synthesis/timing/area numbers.
- `layout/toolchain.json`'s existing pin (klt commit
  `051e8f772281beddd21a3d0022bc83821267056a`, "STARTING pin, not a verified
  one") is consistent with this record: it is honest that no layout/ runner
  has exercised `klt drc` against this PDK yet.
- Every number that later lands in `spec/target-spec.md`, README, or a
  submission document must carry a flow attribution from now on — this is
  now a review checklist item, not just a stated principle.
