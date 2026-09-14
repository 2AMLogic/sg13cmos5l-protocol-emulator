# sg13cmos5l-protocol-emulator

A Protocol emulator ASIC on the [IHP SG13CMOS5L](https://github.com/IHP-GmbH/ihp-sg13cmos5l) open PDK,
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
flow — cocotb + Icarus for verification, Yosys and OpenROAD for implementation.

It is a tiny CPU whose instruction set is built for exactly one job — reading
pins, writing pins, counting cycles, and hitting timing precisely — so that a
real serial protocol (UART, SPI, I2C to start; low-speed USB and 10 Mbit
Ethernet as stretch goals) is implemented in firmware running on the chip
rather than in fixed logic. One chip, many protocols, chosen at run time by
the program it loads. It is this program's entry in the
[Jane Street Protocol Emulator ASIC Competition](https://blog.janestreet.com/protocol-emulator-asic-competition/)
(submissions due 2027-01-18, targeting the March 2027 CMOS5L shuttle via
[Tiny Tapeout](https://tinytapeout.com/)), and it is built in public from the
first commit because the competition asks for exactly that.

## Status

**Just opened, specification phase.** Nothing is designed yet, nothing has been
taped out, and nothing has been measured.

Deliberately not being built yet:

- **The instruction set.** No opcode is defined. The ISA is the design: how
  a program expresses "wait exactly N cycles", "sample this pin on that edge",
  and "drive this pin at that time" decides whether UART, SPI and I2C can all
  be firmware on one core, and it is ratified in `spec/` (issue #1) before any
  RTL is written. Nothing here presumes a register file width, a pipeline, or
  an instruction encoding.
- **Firmware and its toolchain.** Protocols live in programs, so an assembler
  (or generator) and a firmware tree are deliverables of this repo. Their
  shape — hand assembler, Python generator, or a Hardcaml-style embedding —
  is a decision record, not a default, and it waits on the ISA.
- **The flow of record.** The competition submits through the
  [Tiny Tapeout CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l),
  whose sign-off flow is LibreLane run in GitHub Actions. This program's own
  digital flow (`klt synthesize`, Yosys, OpenROAD) does not yet know the
  CMOS5L standard cells. Which flow produces the submitted GDS, and which is
  used for day-to-day iteration, is recorded in `spec/decision-records/`
  before the first synthesis number is written down.
- **Area.** The competition allows up to 8×4 Tiny Tapeout tiles. The draft
  budget below is far smaller on purpose: the judging criterion is novelty of
  design and verification, not size, and a small core is easier to verify
  formally.
- **The stretch protocols.** Low-speed USB and 10 Mbit Ethernet are named in
  the brief as stretch goals. They enter the spec only if the ratified ISA can
  hit their timing; they are not assumed.

## Built agent-native

Every specification, decision record, testbench, and line of documentation in
this repo is produced by AI agents working from a ratified spec and an
append-only evidence trail — not human-authored work that agents merely
assisted with. Verification is the product: every claim traces to a recorded
result. Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction gets
filed as a public issue against the tool itself, so the fix benefits everyone
using IHP SG13CMOS5L, not just this repo.

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target | Stretch |
|---|---|---|
| Protocols emulated in firmware | UART (8N1, 9600–1 Mbaud), SPI (modes 0–3, controller, ≤ f_clk/4), I2C (standard + fast mode, controller) | Low-speed USB 1.1 (1.5 Mbit/s), 10BASE-T Ethernet |
| Timing determinism | Every pin read/write lands on a cycle the program names; no data-dependent instruction latency | — |
| Core clock | Runs at the Tiny Tapeout board clock; ≥ 50 MHz timing closure on CMOS5L | 100 MHz |
| I/O | The Tiny Tapeout pin budget: 8 dedicated inputs, 8 dedicated outputs, 8 bidirectional, plus `clk`/`rst_n`/`ena` | — |
| Program storage | On-chip program memory loaded over one of the pins at boot; size set by the ratified ISA | Program memory from a Tiny Tapeout SRAM macro |
| Area | ≤ 2×2 Tiny Tapeout tiles (draft; competition maximum is 8×4) | — |
| Verification | cocotb functional suite + gate-level regression on the template's flow; formal properties on the timing guarantees; constrained-random protocol traffic against a reference model | Silicon bring-up on the dev board |
| Submission | Open source (Apache-2.0), Tiny Tapeout CMOS5L template, due 2027-01-18 | — |

Every row above is a draft. Ratification (issue #1) may move any of them and
must cite a source for each bound it keeps.

The `flow/` directory description below names Yosys and OpenROAD because that
is this program's standard digital flow; whether the *submitted* GDS comes
from it or from the Tiny Tapeout template's LibreLane flow is an open decision
record (see Status).

## Repo layout

```
src/           Verilog sources, at the path the Tiny Tapeout template expects
info.yaml      Tiny Tapeout project metadata (top module, pinout, tile count)
test/          the Tiny Tapeout template's own cocotb harness (gds/test CI)
docs/          the Tiny Tapeout template's project datasheet source
flow/          synthesis + place-and-route (Yosys, OpenROAD), driven through klt
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
rtl/           this program's own Verilog sources -- empty until the ratified
               ISA needs RTL beyond the Tiny Tapeout top; see rtl/README.md
spec/          ratified spec + decision records
verification/  this program's own cocotb bench + append-only evidence records
```

`src/`/`info.yaml`/`test/`/`docs/`/the `.github/workflows/{gds,test,fpga,docs}.yaml`
files are taken verbatim from the [Tiny Tapeout CMOS5L
template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l)
(issue #2); everything else is this program's own harness, ported from
[`2AMLogic/sky130-modexp`](https://github.com/2AMLogic/sky130-modexp).

The `gds` workflow — the LibreLane sign-off flow, and the only thing here that
builds a GDS — currently fails before doing any work, on a confirmed upstream
bug in the Tiny Tapeout action it calls
([`TinyTapeout/tt-gds-action#52`](https://github.com/TinyTapeout/tt-gds-action/issues/52)),
which also skips `precheck`/`gl_test`/`viewer`. It is not fixable from this
repo without abandoning the verbatim-template rule above. Full write-up:
[`layout/README.md`](layout/README.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
