# 0019: Open-Drain Pad Data Is Held Low — Only `uio_oe` Toggles

Status: **Proposed 2026-10-11.** Like the records it amends, this one is a
proposal: the two-key (`RATIFY-KEY`) mechanism has never run in this
repository (DR [`0006`](0006-two-key-ratification-never-ran.md), issue #44).
It makes no target-spec row met and changes nothing a program can observe.
Date: 2026-10-11
Issues: #244 (finding); #217 (routed protocol evidence that exposed it).

## Context

DR [`0012`](0012-control-space-and-runtime-pin-direction.md) ("Pin mode, per
`uio[n]`") says that when `UIO_OD[n]` is set the pin is open-drain and
`uio_oe[n] = ~uio_out[n]`, and its register table says an open-drain pin
"drives low when `uio_out[n] = 0`, releases (hi-Z) when `1`". The top level
(`src/tt_um_2amlogic_protocol_emulator.v`) implemented that literally:

    assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);

with `uio_out` the core's port-11 register passed straight to the pad. The two
nets are therefore different paths from the same register. On the routed
netlist (Tiny Tapeout `gds` run 38083802720, SDF corner `nom_typ_1p20V_25C`,
LibreLane flow; development smoke check from the #217 harness, no record
minted) `uio_out` arrived about 100 ps before `uio_oe` fell, so on every
release the pad saw `oe = 1, out = 1`: a push-pull HIGH for the skew. The
pad model (`verification/uio_pads.py`) flagged it on SCL (`uio[2]`) and SDA
(`uio[3]`). On an I2C bus that is a short drive-fight whenever a target holds
the line low (ACK, clock stretch, arbitration). Zero-delay RTL has the same
skew as a delta-cycle glitch, which the settled-sample benches could not see.

## Decision (proposed)

On a pin with `UIO_OD[n]` set, the pad's data bit is held at 0 and only
`uio_oe[n]` toggles:

    assign uio_out = core_uio_out & ~uio_od;
    assign uio_oe  = (uio_od & ~core_uio_out) | (~uio_od & uio_dir);

`uio_oe` is still computed from the core's port-11 register, so DR 0012's
rule is kept in the terms it states it in ("drives low on a 0, releases on a
1", `uio_oe[n] = ~port11[n]`). What changes is the value on the pad's data
wire: pad `uio_out[n]` is `port11[n] & ~UIO_OD[n]`. The pad therefore never
sees `oe = 1, out = 1` on an open-drain pin, whatever the relative delays.

Alternative considered and not taken: keep the structure and record a
tolerance for a ~100 ps push-pull window. It depends on the Tiny Tapeout pad
and mux delays that are outside the netlist and were not simulated, and
it would need a delay-aware relaxation of the bench's open-drain assertion.
Removing the cause costs one AND per `uio` bit and needs no tolerance.

## What does not change

- No program can read the pad's `uio_out`: port 11 is write-only and
  `uio_in` reads the line. Instruction semantics, timing, flags, reset values
  and the control space are unchanged.
- The settled line is the same: an open-drain pin pulls low iff `port11[n]`
  is 0, else it is released. Push-pull and input pins are untouched.
- When `UIO_OD[n]` itself changes, pad data and enable still change on the
  same edge from registers; the preamble rule of DR 0012 (release before
  `WCTL UIO_OD`) is unchanged.
- One case is not clean, and is named here rather than claimed away: on a
  push-pull-high pin (`UIO_DIR[n]=1`, `port11[n]=1`), switching `UIO_OD[n]` in
  either direction now changes both `uio_out[n]` and `uio_oe[n]` on the same
  register edge, so a skew can briefly give `oe = 1, out = 0` (a short low
  drive). The previous top held `out = 1` throughout. The ordering rule that
  avoids it is DR 0012's: clear `UIO_DIR[n]` (release the pin) before changing
  `UIO_OD[n]` on a high pin. No committed firmware does otherwise: I2C and PS/2
  run with `UIO_DIR = 0` on their lines, SPI never sets `UIO_OD`, and the boot
  ROM clears `UIO_DIR` before `UIO_OD`.

What changes is only the pad-visible `uio_out` of an open-drain pin (now 0).
Benches that read `uio_out` as the firmware's intent on an open-drain pin read
the port-11 register instead (white-box in RTL) or the line via the pad model.

## Verification

`verification/test_control_space.py`: the pad data bit is checked against
`port11 & ~UIO_OD` over the pin-mode sequence; the I2C images are run with the
invariant "pad data on SCL/SDA is 0 and `uio_oe == ~port11`" on every edge;
and `test_open_drain_pad_never_sees_oe_high_with_data_high` watches every value
change of `uio_out` and `uio_oe` (delta-cycle level) and fails if `uio_oe &
uio_out` is ever nonzero on an open-drain pin. That test fails on the previous
top (14 glitches on the I2C image) and passes on this one. The routed-delay
confirmation is #217's measured-evidence leg, which this record does not
claim.

## Consequences

- `src/tt_um_2amlogic_protocol_emulator.v` is pinned by DR 0017. This is a
  `conformance-fix` amendment (`spec/isa-freeze.json`): DR 0012's "releases
  (hi-Z) when 1" was broken for the skew window. It invalidates no row-13
  evidence: the settled line levels the PS/2 and I2C benches grade are
  unchanged, and those benches are re-run on this top.
- DR 0012 is pinned and is not edited; this record is its pad-level
  refinement.
- Synthesis/timing numbers for the added gates are not claimed here; any such
  number must name its flow (`klt` vs. the Tiny Tapeout LibreLane flow).
