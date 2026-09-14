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

## Target specification

The full target-spec table — every commitment, its source citation, and
what verification artifact checks it — lives in
[`spec/target-spec.md`](spec/target-spec.md) (Status: DRAFT). Design
decisions behind those targets (the ISA, which flow produces the submitted
GDS, the firmware toolchain) are recorded in
[`spec/decision-records/`](spec/decision-records/). What's judged and how
it's checked is in [`spec/verification-plan.md`](spec/verification-plan.md).
Current status against every row and the 2027-01-18 deadline is tracked in
[`spec/gap-to-submission.md`](spec/gap-to-submission.md).

The `flow/` directory description below names Yosys and OpenROAD because that
is this program's standard digital flow; whether the *submitted* GDS comes
from it or from the Tiny Tapeout template's LibreLane flow is an open decision
record (see `spec/decision-records/0002-flow-of-record.md`).

## Repo layout

```
flow/          synthesis + place-and-route (Yosys, OpenROAD)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
rtl/           Verilog sources
spec/          ratified spec + decision records
verification/  cocotb testbenches
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
