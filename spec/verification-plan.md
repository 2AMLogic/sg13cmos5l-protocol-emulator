# Verification Plan

Status: DRAFT — proposed 2026-09-14 in issue #1, pending ratification
alongside `spec/target-spec.md`.

Per `CLAUDE.md`: "Verification is the product: no claim without a
testbench," and per the competition post, judging weighs "novel approaches
to design and verification methodologies (formal methods, constrained
random, AI-assisted verification are named)" as heavily as functional
correctness. This plan is therefore itself a submission artifact, not
internal process documentation — every section below is expected to be
legible to a competition judge as evidence, not just to this program's own
agents.

None of the artifacts described below exist yet; `spec/gap-to-submission.md`
tracks that. This document specifies what "verified" means for this design
before any of it is built, per `CLAUDE.md`'s "no claim without a testbench"
applied recursively to the test plan itself: a testbench built without a
spec of what it's supposed to check is no more trustworthy than RTL built
without an ISA spec.

## 1. What is judged, and how this plan maps to it

| Judging criterion (competition post) | This plan's response |
|---|---|
| "Unique functionality" | §4's constrained-random suites demonstrate three distinct protocols running as firmware on one core — the functional claim itself. |
| "Formal methods" | §2 |
| "Constrained random" | §4 |
| "AI-assisted verification" | §5 — this entire program is built by AI agents from a ratified spec with an append-only evidence trail; §5 makes that auditable rather than just asserted. |

## 2. Formal properties

Two properties are named now, both directly checking DR 0001's timing
guarantee (`spec/target-spec.md` row 3) — the property this whole ISA
design stands or falls on:

### 2.1 `no_data_dependent_latency`

**Statement**: for every instruction opcode, the number of clock cycles
between fetch and the retirement of that instruction (advance to the next
PC, or the start of a `WAIT`'s stall count) depends only on the
instruction's own encoded fields (opcode, and for `WAIT`, its immediate) —
never on the value of any general-purpose register, any pin input, or any
flag.

**Why this is checkable formally rather than only by simulation**: this is
a property about the *control* path (does the FSM/next-state logic ever
branch its own cycle count on a data register or pin value), which model
checkers handle well as a bounded/unbounded assertion over the RTL's state
machine, independent of what specific data values are simulated. A
simulation-only check would need to enumerate register/pin value corners
to gain confidence; a formal property closes that corner space by
construction. Tooling choice (SymbiYosys/other) is deferred to the issue
that writes this property against real RTL — this record fixes *what* is
checked, not the specific formal tool invocation.

### 2.2 `pin_write_latency`

**Statement**: for every `OUT` instruction that retires at cycle `N`, the
addressed output pin's physical value at cycle `N+1` equals the value
written, and the pin's value at every cycle before `N+1` is unaffected by
that `OUT` (no earlier visibility, e.g. via a combinational leak from the
write data to the pin).

This directly backs DR 0001's "drive on edge" definition and is the
property a protocol timing claim (e.g., "the SPI SCLK edge lands where the
program says") ultimately reduces to.

## 3. Gate-level regression

A cocotb gate-level regression run against the flow-of-record's synthesized
netlist (DR 0002: the Tiny Tapeout CMOS5L template's LibreLane output),
re-running the same functional test suite from §4 against gates instead of
RTL. This is the check that catches synthesis-introduced behavioral
divergence (e.g., a latch inferred where a flop was intended, an X-
propagation issue masked by RTL-level simulation defaults) before it
reaches a taped-out chip. Per DR 0002, a `klt`/Yosys/OpenROAD gate-level
regression is additionally run once the platform-table gap
(2AMLogic/klayout-tools#1784) closes, as a second, faster-iteration
correctness signal — not a substitute for the flow-of-record run.

## 4. Constrained-random protocol traffic + reference models

One suite per core protocol (`spec/target-spec.md` row 1), each structured
the same way: a cocotb testbench drives randomized-but-legal protocol
traffic at the design-under-test (the core running the relevant committed
firmware program, per DR 0003) on one side, and an **independent reference
model** — a model that does not share code with this design's RTL or
firmware, so it cannot silently encode the same bug on both sides of the
comparison — checks the resulting pin-level waveform against what the
protocol requires.

| Protocol | Constrained-random dimensions | Independent reference model |
|---|---|---|
| UART | baud rate (across the 9,600–1,000,000 range), byte values, frame timing jitter injected on the receive side | A software UART decoder independent of this repo's firmware/RTL (e.g. a well-established open-source UART bit-timing model, not hand-rolled to match this design's own assumptions) |
| SPI | mode (0–3), transfer length, clock rate up to the f_clk/4 ceiling, MOSI/MISO data patterns | A software SPI controller/peripheral reference model checking mode-correct clock-edge/sample-edge alignment against Motorola/NXP SPI Block Guide conventions (`spec/target-spec.md` row 11) |
| I2C | Standard vs. Fast mode, address values, ACK/NACK injection from the simulated peripheral, clock-stretching from the simulated peripheral | A reference I2C bus-functional model checking timing against NXP UM10204 Rev. 6's AC characteristics table (`spec/target-spec.md` row 12) directly, not against this repo's own DR 0001 cycle-budget arithmetic — the whole point of an *independent* reference is that it does not trust this repo's own math |

Each suite's pass/fail record is append-only per `CLAUDE.md`: a later run
that fails does not retroactively erase an earlier recorded pass; it is
recorded as a new result explaining why (e.g., a regression, a spec change
via a new decision record, or a reference-model correction) — see §5.

## 5. AI-agent evidence process

Every artifact in this repo — spec, decision records, RTL (once it exists),
testbenches, and this document — is produced by AI agents (`CLAUDE.md`:
"designed and verified by AI agents"). This section is what makes that
auditable rather than a bare assertion:

- **Producing agent identified per artifact**: commit authorship (this
  repo's Loom-orchestrated Builder/Judge/Curator roles) is the audit trail
  for who (which agent role, under which issue) produced each piece of
  spec, RTL, or testbench.
- **Independent review before merge**: the Loom workflow's Judge role
  reviews every PR against its issue's acceptance criteria before merge —
  this is the "audit" half of "AI agents produce and audit all of it,"
  applied uniformly to spec changes and RTL changes alike, not just to
  code.
- **Append-only results**: per `CLAUDE.md`, "recorded results are append-
  only evidence; a result is not superseded by deletion, it is superseded
  by a later record that says why." Concretely: verification results
  (§3, §4) are committed test-run records (e.g., a results log or CI
  artifact reference tied to a commit), and a later contradicting result
  is a new committed record, not an edit or deletion of the old one. The
  specific storage mechanism (a `records/` directory in the harness ported
  per DR 0002 from `2AMLogic/sky130-modexp`, or CI artifact retention) is
  implementation detail for the harness-bootstrap issue, not fixed here.
- **Spec changes are decision records, not silent edits**: per `CLAUDE.md`,
  "spec changes go through `spec/` with a decision record. Agents do not
  relax the ratified spec to make a result pass." A verification failure
  is grounds for a new decision record proposing a spec change (reviewed
  and ratified through the two-key mechanism, same as the original spec),
  never grounds for an agent quietly loosening a target-spec row.

## 6. What this plan does not yet cover

- The stretch protocols (low-speed USB, 10BASE-T Ethernet) have no cycle-
  budget sketch in DR 0001 yet, so they have no verification plan entry
  either — per `spec/target-spec.md` row 2, they enter this plan only once
  DR 0001 (or a successor decision record) shows they fit the ISA's timing
  budget.
- Exact tooling choices (which formal tool, which cocotb/Icarus versions,
  which specific open-source UART/SPI/I2C reference-model libraries) are
  deferred to the harness-bootstrap issue (#2) and the firmware/RTL issues
  that follow it — this plan fixes *what* is checked and *against what
  independent standard*, which is the part that has to be right before any
  tool is chosen.
