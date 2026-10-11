# 0020: An Open-Drain Pin's Pad Data Is Tied Low — RTL Conformance Fix to DR 0012's Pin-Mode Rule

Status: **Proposed 2026-10-11.** Like DRs 0001–0005, 0007, 0008 and 0010–0018,
this record is a proposal. The two-key (`RATIFY-KEY`) mechanism has not bound
it (DR [`0006`](0006-two-key-ratification-never-ran.md), issue #44). It is a
**conformance fix** in the sense of DR
[`0017`](0017-submission-isa-freeze.md) section 4: the RTL is brought into
line with a frozen record. It changes no instruction, control index, latency,
flag, reset value or assembler rule, edits no pinned record and no target-spec
value, and makes no row met.
Date: 2026-10-11
Issues: #244 (the finding and its triage); #217 (the routed-SDF protocol
harness that found it); #135 (DR 0012's build); #44 (ratification).

**Numbering note.** When this record was numbered (2026-10-11), `origin/main`
had DRs 0001–0008 and 0010–0018. Open PR #242 carries 0009, and two open PRs
each carry a record numbered 0019: #254 (an accept-and-watch record for issue
#246) and #256 (another build of this same fix for issue #244, opened while
this one was being measured). This record is **0020** so that it collides
with neither, as earlier records stepped over 0009 and 0011. Which of the
overlapping PRs merge is for their reviewers; this record does not depend on
either.

## Context

DR [`0012`](0012-control-space-and-runtime-pin-direction.md) (pinned by DR
0017) defines the open-drain pin mode twice:

- register map, row `0x01`: "`UIO_OD` … per-pin open-drain enable for
  `uio[n]`: drives low when `uio_out[n] = 0`, releases (hi-Z) when `1`";
- "Pin mode, per `uio[n]`": "If `UIO_OD[n]` is set, the pin is open-drain and
  `uio_oe[n] = ~uio_out[n]`."

`uio_out` in both sentences is the ISA's port 11, the register a program
writes with `OUT`. An open-drain pin therefore has two states, pulled low and
released. It has no state in which the pad drives HIGH.

The top level, `src/tt_um_2amlogic_protocol_emulator.v`, built the rule as

```verilog
// .port_uio_out(uio_out): the core's port-11 register straight onto the pads
assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);
```

so an open-drain pin's pad data was the register bit itself, and the pad
enable was derived from it. Its own header comment said "`uio_out[n]` is 0
when driving, so the pad only ever pulls low". That holds only if `uio_oe[n]`
falls no later than `uio_out[n]` rises. At zero delay the two change in the
same time step. On the routed netlist they do not.

**The finding (issue #244).** `flow/run-post-layout-sdf.sh --suite protocols
--protocol i2c_sr`, the #217 harness, runs the committed I2C repeated-START
images on the LibreLane post-route netlist with its SDF delays. On the
netlist of gds run 38083802720, at `nom_typ_1p20V_25C`, `uio_out` reached the
pins 690–710 ps after the clock pin edge and `uio_oe` 800–820 ps after it.
When firmware released SCL or SDA, `uio_out[n]` rose about 100 ps before
`uio_oe[n]` fell, and for that window the pad was push-pull HIGH. The pad
model reported `drove_high = 0x0c` (SCL `uio[2]` and SDA `uio[3]`). On a
shared bus, that is a short drive-fight whenever a target holds the line low
(ACK, clock stretch, arbitration). The Tiny Tapeout IO cells and mux are
outside the netlist and were not simulated.

So the netlist broke DR 0012's "drives low … releases (hi-Z)": for about
100 ps per release it did a third thing.

## Decision (proposed)

### 1. The fix

For an open-drain pin the pad data is the constant 0 and the pad enable alone
carries the port-11 bit:

```verilog
// .port_uio_out(core_uio_out): the core's port-11 register
assign uio_out = core_uio_out & ~uio_od;
assign uio_oe  = (uio_od & ~core_uio_out) | (~uio_od & uio_dir);
```

- `uio_out[n]` can be 1 only where `uio_od[n]` is 0. On an open-drain pin the
  data net never rises, so there is no order of arrival of `uio_out[n]` and
  `uio_oe[n]` at the pad that drives it HIGH. The property no longer depends
  on a delay.
- `uio_oe` is the same function of the three registers as before. Written out
  per pin it is still DR 0012's rule: open-drain wins, then push-pull, else
  input.
- Push-pull and input pins are untouched: their pad data is the port-11
  register, as before.
- Readback is untouched. `IN` from port 01 reads `uio_in`, the pad; `RCTL` of
  `UIO_DIR` / `UIO_OD` returns the registers. No instruction reads the
  `uio_out` pins.

The only file of DR 0017's pinned set that changes is
`src/tt_um_2amlogic_protocol_emulator.v`: one new wire (`core_uio_out`), the
core's `port_uio_out` connection, the two `assign`s above and the comments
that describe them. `rtl/protocol_core.v` is not changed.

### 2. Why this is a conformance fix and not an ISA change

DR 0017 section 4 item 2 defines a `conformance-fix` as one where "the RTL,
the reference model or the assembler is brought into line with the frozen
records", and requires its record to "say it is a conformance fix and name the
frozen text the old behaviour broke". This is one, and the frozen text is DR
0012's register-map row `0x01` and its "Pin mode, per `uio[n]`" paragraph,
both quoted in Context.

Nothing a program can observe changes:

| What a program or its author can see | Before | After |
|---|---|---|
| Any instruction's encoding, effect or cycle count | DR 0001, 0012, 0015, 0016 | unchanged |
| `UIO_DIR` / `UIO_OD` write, read-back and reset value | DR 0012 | unchanged |
| `uio_oe` as a function of port 11, `UIO_DIR`, `UIO_OD`, on every clock edge | DR 0012's rule | the same function |
| The line an open-drain pin makes on a pulled-up bus, at the clock-edge resolution every program is timed in | low when the port-11 bit is 0, released when 1 | the same |
| `IN` from `uio_in` | the pad | the pad |
| The assembly language (`firmware/tools/asm.py`) | pinned | unchanged, not edited |
| The reference model (`verification/reference_models/isa.py`) | pinned | unchanged, not edited: its trace row's `uio_out` is the port-11 register, and its `uio_oe` is the rule above |

What does change is outside the ISA: the logic value on the eight `uio_out`
wires of an open-drain pin (0 instead of the register bit), which only the
pad sees, and the sub-cycle glitch that the old value made possible.

### 3. Row 13 evidence: not invalidated

DR 0017 section 4 item 3: "A `conformance-fix` invalidates [row-13 evidence]
if the row-13 program ran on the behaviour being fixed."

- **Primary column, WS2812 (DR [`0018`](0018-row13-protocol-choice.md)).**
  `firmware/asm/ws2812.asm` drives `uo_out[0]` only. It writes neither
  `UIO_DIR` nor `UIO_OD` and never writes port 11; its only `WCTL` is to
  `PM_ADDR`. It does not run on the pin-mode logic at all.
- **Stretch column, the PS/2 device (DR 0018's 2026-10-11 note).** It does use
  two open-drain pins. Its evidence is graded on the pad-resolved lines at
  RTL and on the zero-delay gate-level netlist, where the old and the new
  wiring produce the same lines on every edge; the behaviour being fixed is a
  sub-cycle window that exists only with routed delays, on which no PS/2
  evidence was taken. One PS/2 bench assertion read the `uio_out` wires of
  the idle open-drain pins and is updated (below); no protocol result moves.

So the amendment's `invalidates_row13_evidence` is `false`. The WS2812 and
PS/2 records are re-minted in the same PR for a different reason: the top
file's hash and the routed netlist change, and every record that binds either
is stale by this repository's own rules.

### 4. Evidence the fix must carry

1. **The property, at RTL and on gates.** `test_control_space.py`,
   `test_open_drain_pad_data_is_tied_low`: on every clock edge,
   `uio_out[n] & UIO_OD[n] == 0` for every pin, hence
   `uio_oe[n] & uio_out[n] & UIO_OD[n]` is never 1. The pin-mode logic is
   combinational in three bits per pin and the pins are independent, so its
   input space is 8 combinations per pin; the test requires all 8 on all 8
   pins and at least two open-drain releases per pin, as counted gates. It is
   pin-only, so it also runs on the gate-level netlist. This is a bench, not a
   formal proof: the repository's formal harnesses bind `rtl/protocol_core.v`,
   not the top, and extending them was not cheap. The exhaustive per-pin
   coverage is the substitute, and it is stated as such.
2. **A negative control with the old wiring.** At zero delay the old wiring
   also satisfies `oe & out & od == 0`; it fails only the stronger
   `out & od == 0`. So the control is two things:
   - at RTL, `control_space_mutants.py`'s `od-pad-data-follows-register`
     restores `assign uio_out = core_uio_out;` and must be caught by the test
     above;
   - with routed delays, the same harness on the pre-fix netlist must still
     report `drove_high != 0` (the finding itself).
3. **The acceptance run.** `flow/run-post-layout-sdf.sh --suite protocols
   --protocol i2c_sr` on the post-route netlist of this change reports
   `drove_high == 0` at all three corners.
4. **A lint.** `scripts/check_protocol_pin_roles.py` accepts exactly the two
   `assign`s of section 1 and refuses the pre-fix wiring by name.

The results are evidence records under `verification/records/`; this record
does not state them.

### 5. Benches that read the `uio_out` wires of an open-drain pin

Five benches treated `dut.uio_out` as the port-11 register on pins that were
open-drain at the time. None is pinned (DR 0017 section 3). Each is updated to
check what the pad sees, and none loses a check:

| Bench | What it read | What it reads now |
|---|---|---|
| `test_control_space.py` (I2C preamble) | `uio_oe == ~uio_out & 0x0C` | pad data 0 on SCL and SDA on every edge, no other pin enabled, and (RTL, white-box) `uio_oe == ~port 11 & 0x0C` on every edge |
| `test_firmware_i2c.py` | SCL line equals the `uio_out` intent | SCL line equals the complement of `uio_oe[2]`; pad data rises once (idle image) and falls once (`WCTL UIO_OD`), never again |
| `test_firmware_ps2.py` (idle check) | `uio_out` shows both lines released | `uio_oe` 0 on both, pad data 0, `uio_in` high on both |
| `test_boot_rom.py` (UART loader idle) | `uio_out == 0xFF` behind the guard | `uio_out` is 0xFF between the guard's `OUT` and its `WCTL UIO_OD`, and 0 after |
| `test_isa_lockstep.py` | ISS `uio_out` against the `uio_out` pins | ISS `uio_out` against the core's port-11 register, and the pins against `port 11 & ~UIO_OD` taken from the ISS |

The `UIO_OD` negative control of the I2C benches (the image with its `WCTL
UIO_OD` removed) still composes a bus from the `uio_out` intent: with
`UIO_OD` at its reset value the pad data is the register, as before.

## Limits

- **A write to `UIO_OD` on a pin that is push-pull and high.** If
  `UIO_DIR[n]` is 1 and the port-11 bit is 1, the pad drives HIGH, as a
  push-pull pin should. Setting `UIO_OD[n]` then makes `uio_out[n]` and
  `uio_oe[n]` both fall, and their order at the pad is not fixed: if the data
  falls first the pad drives LOW until the enable follows. The old wiring did
  not have this case (its data stayed 1) and had the release glitch on every
  open-drain write instead. The transition is a mode change that firmware
  chooses to make, once, and it has a clean order: make the pin an input
  first (`UIO_DIR[n] = 0`), then set `UIO_OD[n]`. Every committed image sets
  `UIO_OD` on pins that are still inputs (the I2C images and the PS/2 device
  from reset; the boot ROM's guard). The reverse write, clearing `UIO_OD` on a
  pin whose `UIO_DIR` is 1, has the mirrored case and the same rule.
- **Pads.** The Tiny Tapeout IO cell, its output-enable path and the mux are
  not in the netlist. This record removes the glitch at the design's boundary;
  it does not claim a pad-level waveform.
- **`uio_od` changing against `core_uio_out`.** Both are registers on the
  same clock in the core; a single instruction writes one of them.

## Alternatives considered

1. **Accept the glitch and give the bench a delay-aware tolerance** (issue
   #244's second direction). Rejected. It leaves a window in which the pad
   does something DR 0012 says an open-drain pin does not do, and its width
   would move with every placement.
2. **Register `uio_oe` and `uio_out` in the top so they leave on the same
   clock edge.** Rejected: two flops per pin still arrive at the pad at
   different times after routing. It would shrink the window, not remove it,
   and it adds a cycle of latency to the pins, which is an ISA change.
3. **Fix it in the core** (give `rtl/protocol_core.v` a pad-data output).
   Rejected: the pin-mode logic lives in the top by DR 0012's build, the top
   change is two lines, and it leaves the core's hash alone.
4. **Change DR 0012's text to describe the pad data.** Not done. DR 0012 is
   pinned and its rule is right as written; this record is where the pad-data
   detail lives.

## Consequences

- `spec/isa-freeze.json` gains one `conformance-fix` amendment for
  `src/tt_um_2amlogic_protocol_emulator.v`, citing this record, with
  `invalidates_row13_evidence: false`.
- The routed netlist changes, so every LibreLane-derived record and every
  record that hashes the top file is re-minted in the same PR.
- DR 0012 and DR 0001 are not edited. Where they write `uio_oe[n] =
  ~uio_out[n]`, `uio_out` is the ISA's port 11, as it always was.
- DR [`0010`](0010-protocol-pin-roles.md)'s firmware convention (write the
  idle image with `OUT UIO_OUT` before the pin-mode register) is unchanged and
  still required: `uio_oe` follows the port-11 register the moment `UIO_OD`
  is set.

## Open items

1. **A formal statement of the property on the top.** The bench covers the
   whole combinational input space per pin; a formal harness for the top
   would replace the coverage argument with a proof. Not built here.
