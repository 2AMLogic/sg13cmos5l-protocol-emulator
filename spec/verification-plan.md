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

> **2026-10-09: the organizers' own criteria.** The organizers' entrant update
> (quoted verbatim in issues #129–#134) describes judging as having "no fixed
> weighting. Flexibility is the main thing: can the chip be reprogrammed to
> support protocols it wasn't designed for? Beyond that, we'll look at which
> protocols you demonstrate, anything unique your architecture makes
> possible, and how you designed and verified it." The table above, written
> from the original blog post, has no row for the first of those. It is
> answered by §7 (target-spec row 13), and the reset obligations the update
> spells out are answered by §8 (row 14). The submission must also include "a
> write-up of your verification approach" and a description of how AI tools
> were used; §5 is the raw material for both (#134).

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

> **2026-09-22 (issue #24): the property is written.**
> `verification/formal/no_data_dependent_latency.sv` is this section's
> property of record: a port-only SVA monitor that operationalizes the
> statement above as mechanical assertions over DR 0001's ratified latency
> table (1 cycle per opcode; `imm8+1` for `WAIT`; `HALT` then idle), with
> data-independence enforced by construction — every assertion's
> right-hand side is a function of the instruction word alone, and branch
> targets may respond to free data while branch *cost* never does, which
> is DR 0001's "data may choose *where*, never *how long*" encoded
> exactly. The monitor observes only the signals the core must already
> use to wire the landed program memory (`clk`/`rst_n`/`run_phase`/`pc`
> /`instr`), so it binds to issue #18's core unchanged. Tooling, chosen
> by #24: Yosys (`write_smt2`) + `yosys-smtbmc` + Z3 — the same engine
> pair SymbiYosys drives, without the `sby` wrapper (not installed here);
> cold-start invocation is
> `./verification/formal/run-no-data-dependent-latency.sh` (T1 item 9
> shape: committed bench, documented one-command invocation, no PDK
> dependency). Qualification state, recorded append-only in
> `verification/records/no-data-dependent-latency/`: the property passes
> bounded model checking on a conformant timing-contract fixture with all
> non-vacuity covers reached, and catches a deliberately data-dependent
> `WAIT` early-out mutant within 5 cycles. **This is property
> qualification, not row-3 evidence**: the DUT in those runs is a
> qualification fixture standing in for the core; row 3 stays unmet until
> the same property passes against issue #18's real core RTL. The
> bounded/unbounded split of that future run is documented in the property
> header and the record.

### 2.2 `pin_write_latency`

**Statement**: for every `OUT` instruction that retires at cycle `N`, the
addressed output pin's physical value at cycle `N+1` equals the value
written, and the pin's value at every cycle before `N+1` is unaffected by
that `OUT` (no earlier visibility, e.g. via a combinational leak from the
write data to the pin).

This directly backs DR 0001's "drive on edge" definition and is the
property a protocol timing claim (e.g., "the SPI SCLK edge lands where the
program says") ultimately reduces to.

> **2026-09-22 (issue #24): explicitly deferred, with the reason.**
> §2.1's property was written and qualified now because its expected
> values are DR 0001's ratified latency table and its observable surface
> (`pc`, `instr`, `run_phase`) is already fixed by the landed program
> memory. `pin_write_latency` does not have that second anchor yet: it
> asserts a relation between an `OUT` instruction's retirement event and
> the physical pin output register's value one cycle later, and neither
> that retirement event nor the pin-drive path exists in RTL until issue
> #18's core lands (today's top is still the harness-bootstrap stub).
> Writing it now would mean guessing #18's observable retirement/pin
> surface — exactly the guessing §2.1's bind contract avoided by anchoring
> on landed RTL. It is therefore deferred to the #18 follow-up sweep that
> re-runs `no_data_dependent_latency` against the real core; the deferral,
> not silence, is recorded here per this plan's own evidence discipline.

> **2026-10-09 (issue #116): the deferral is discharged; the property is
> written and run on the real core.** The core and its output ports landed
> with #18, so this section's second anchor now exists.
> `verification/formal/pin_write_latency.sv` is this section's property of
> record. It is an independent shadow-ISA monitor written from DR 0001's
> text, and it reads no core-internal signal. Execution eligibility comes
> from the harness phase model plus the monitor's own shadow `WAIT`/`HALT`
> state, not from any core write enable. The monitor is bound to the
> unmodified `rtl/protocol_core.v` by `verification/formal/formal_top_pin_write.v`.
> Cold start: `./verification/formal/run-pin-write-latency.sh`. Evidence:
> record `verification/records/pin-write-latency/records/20261009-164147-7cf622d.md`
> (flow: Yosys + `yosys-abc` + `yosys-smtbmc`/Z3; RTL only, no synthesis or
> timing flow ran).
>
> *Clock convention.* The statement above and DR 0001's "Drive on edge"
> describe the same event; they do not conflict. Cycle `N` is the clock
> period in which `OUT` occupies execute. During `N` the source register
> holds the pre-edge value and the pin still shows its old value. The edge
> that ends `N` is the retiring edge: the output flop captures the value
> there. Throughout cycle `N+1` the pin shows the new value, which is the
> state the next assertion sampling point observes. There is no extra
> output pipeline stage. "Physical pin" in the statement is read here as
> the core's output-port register, which the top
> (`src/tt_um_2amlogic_protocol_emulator.v`) wires straight to
> `uo_out`/`uio_out`. Pad, post-route and SDF behaviour are separate checks
> (#106). No spec change is proposed and the statement above is not
> relaxed.
>
> *What was shown.* Every executed `OUT` writes the source register's
> value to the addressed writable port at the retiring edge, and the other
> port holds. No output moves for read-only-port `OUT`s, other
> instructions, `WAIT` stalls, `HALT`, a `run_phase`-low (load) window of any length
> of at least one cycle after reset, or the priming cycle, except on reset (both ports return to 0). Two clock models check this:
>
> - a once-per-cycle EDGE model;
> - a `clk2fflogic` FINE model, in which the clock and inputs may change
>   between edges and an output may change only on a rising edge.
>
> ABC `scorr`+`pdr` proved both. That proof is **unbounded only within the
> harness model**, and it rests on that one engine. The model is a free
> 8-word program table behind a registered fetch, the mode_pin-low phase
> model with a free-length `run_phase`-low window after each reset (a free
> `go` input chooses when run phase starts; the serial shift-in itself is
> not modelled), and reset synchronised to the clock. The scorr-independent bounded
> cross-check reached only 9 cycles (EDGE) and 14 samples (FINE). All
> non-vacuity covers were reached: 16 EDGE and 18 FINE. A structural check
> confirms every output bit is a rising-edge flop output on `clk`. Eight
> faulty core copies are rejected by both ABC and Z3:
>
> - wrong destination;
> - wrong value;
> - read-only-port write;
> - one cycle late;
> - combinational early visibility;
> - executes in the priming cycle;
> - falling-edge (half a cycle early);
> - a fault that only fires after three consecutive load-phase cycles
>   (an earlier fixed one-cycle load window could not see it; the Judge
>   review of PR #127 caught this and the harness was changed).
>
> The falling-edge mutant *passes* the EDGE model and fails only the FINE
> model and the structural check. That is recorded as the reason a
> once-per-cycle result is not a claim about behaviour between edges. DR
> 0001 and DR 0005 remain Proposed (DR 0006), so this is evidence against
> the proposed contract, not ratification. The original text above is left
> as written.

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

> **2026-10-09 (issue #108): reconciliation with what actually runs.**
> The paragraph above is the target, not the status. Until #108 the only
> gate-level leg was the template's `gl_test` (`test/test.py`, one short
> program), so the §4 *firmware* benches had no evidence on gates. Now the
> committed UART, SPI (modes 0-3) and I2C (Standard/Fast, plus the Sr/stretch
> sibling) benches run unmodified, zero-delay, on the LibreLane `tt_submission`
> netlist of `gds` run `37911842396` via `flow/run-firmware-gate-level.sh`
> (reusing `test/Makefile` `GATES=yes`), all passing, with a WAIT-counter
> stuck-at fault injected into the netlist failing every bench (record
> `firmware-gate-level/20261009-120000-35c5332`; flow: LibreLane netlist,
> Icarus/cocotb). Still not run at gates: the constrained-random regression
> (`test_random_regression.py`) and the white-box core bench
> (`test_protocol_emulator.py::test_alu_flags_whitebox` needs RTL hierarchy);
> the SDF-annotated leg remains failing (#102 record, #106). The netlist is the
> final routed one, not an intermediate post-synthesis netlist. The original
> text above is left as written.

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
  DR 0015 (Proposed) now shows a hand-counted budget for low-speed USB
  transmit with protocol-neutral primitives (10BASE-T deferred there); if it
  is ratified, a bench per admitted primitive and a USB TX-only firmware
  bench (independent decoder, timing checked) are added here.
  Nothing is added until then.
- Exact tooling choices (which formal tool, which cocotb/Icarus versions,
  which specific open-source UART/SPI/I2C reference-model libraries) are
  deferred to the harness-bootstrap issue (#2) and the firmware/RTL issues
  that follow it — this plan fixes *what* is checked and *against what
  independent standard*, which is the part that has to be right before any
  tool is chosen.
- Area (row 7): no area number is checked by a bench. DR 0014 (Proposed,
  issue #129) recommends keeping 2×2; any multi-engine design it gates would
  need the §2 formal properties re-proved per engine and for their interaction,
  and the `gds` wall-clock recorded (6-hour Actions limit, #134).

## 7. Reprogrammability, the control space and program loading (rows 6, 13; DRs 0012, 0013)

*Added 2026-10-09. Proposed, like the rest of this plan.*

- **Unplanned-protocol firmware (row 13).** Each protocol gets a committed
  program and a cocotb bench graded by an **independent reference model**,
  with the same bar as §4. The protocol is chosen after the submission ISA is
  frozen, and the record states the freeze commit, so the evidence cannot have
  shaped the ISA. Its stretch (a role or pin direction the core protocols
  never use) runs on the silicon-true pad model below.
- **Control-register bench (DR 0012).** It checks:
  - reset values, readback, and reserved-index behaviour (no-op write, read
    returns 0)
  - the fixed stall of the `PM_*` accesses and `RUN`
  - that no `WCTL`/`RCTL` sets the flags

  `no_data_dependent_latency` (§2.1) extends to `WCTL`/`RCTL` with DR 0012's
  per-index latency table.
- **Silicon-true pad model.** Per pin, `uio_oe`/`uio_out` drive a resolved
  line with an optional pull-up, and `uio_in` reads the resolved line. It
  replaces the bench-composed wired-AND bus (DR 0008 § Context), and the I2C
  evidence re-runs on it, because until DR 0012 is built no bench has shown
  that I2C works through the real `uio_oe`.
- **Load integrity (DR 0013 layer 1).** The `PM_CRC` exposed on `uo_out`
  during load, and through `RCTL`, matches an independent CRC-16/XMODEM
  (`binascii.crc_hqx`) for random images, including truncated loads and loads
  with a dropped or doubled clock edge, which must produce a mismatch.
- **Boot programs (DR 0013 layer 2).** Each boot ROM program is tested
  against an independent host:
  - a UART host model that frames, sends and checks the reply, at nominal
    baud and at ± tolerance
  - a SPI-flash behavioural model that answers `0x03` reads from an image
  - corrupted frames and flash contents, which must never reach `RUN`

  The SPI-flash half is built (issue #140): `verification/test_boot_spi.py`
  with `verification/reference_models/spi_flash.py`, which checks SPI mode 0
  as well as answering `0x03`, plus the rule that the boot drives only the
  Pmod's CS0, MOSI and SCK pins. The UART half is issue #139.

  The ROM image is freshness-checked against its `.asm` source like every
  other committed `.hex`.
- **Runtime swap.** A program loads a second program through `PM_*` and runs
  it with `RUN`. The second program's protocol is graded by its own reference
  model.
- All of the above also runs at gate level (§3).

## 8. Reset, power-up and reselect (row 14)

*Added 2026-10-09 (issue #131). Recorded 2026-10-10 on the LibreLane
netlist (Icarus + cocotb, zero-delay): (a), (b) and the reselect cycle
pass; (c) is met on the serial-load and boot-ROM paths **except** the
all-zero warm-start case -- an all-zero program memory is its own valid
CRC signature and warm-starts unloaded on strap `10` (256 `NOP`s), tracked
in #168 and pending operator decision #166 (CRC initial value), so (c) is
not fully met. The negative controls fail as required --
`verification/records/reset-power-up/records/20261010-012219-02f84e3.md`.
2026-10-10 (issue #168): the warm start now refuses a zero signature (DR
0013 Finding F1, option 4), so the all-zero case above no longer runs: RTL
`verification/records/boot-rom/records/20261010-082233-704a3fb.md`, gate
level `verification/records/firmware-gate-level/records/20261010-083703-704a3fb.md`;
this section's bench re-run on that netlist is
`verification/records/reset-power-up/records/20261010-091001-704a3fb.md`.
The host's reload obligation after deselect is in `verification/README.md`
(issue #118).*

*2026-10-10 (issue #140): re-run on the netlist with the SPI-flash boot
program. Strap `01` is no longer a stub: it runs the SPI-flash boot, which
drives CS0, MOSI and SCK, so the bench checks those pins against the
independent boot model edge for edge (row 14's "until a program writes
them") and the program memory against what the boot wrote; the other
straps are checked as before. Same outcome: (a), (b) and reselect pass, (c)
as above, every negative control fails as required --
`verification/records/reset-power-up/records/20261010-045739-b28ebcc.md`.*

- **Random-initial-state gate-level run.** Every flop of the flow-of-record
  netlist starts at a seeded random value (and, separately, at X). Then
  `rst_n` is applied. After reset deasserts, the top-level outputs must be
  identical across seeds and free of X, and must equal the documented reset
  state. Several seeds; the seeds are recorded.
- **Reset-coverage listing.** Every flop the netlist leaves without a reset is
  listed, with a justification (for example a datapath register always
  written before it is read). A new unjustified entry fails the check.
- **Uninitialized program memory.** With the SRAM model holding random
  contents and `MODE` low at reset, the design runs the boot ROM, drives no
  `uio` pin, and does not execute program memory until a load passes its CRC
  (DR 0013). This is the post-reselect case the organizers describe.
- **Re-select.** Load, run, power-cycle (state randomized), reset, reload,
  run. The second run's output must match the first.

