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
[`spec/target-spec.md`](spec/target-spec.md) (Status: **RATIFIED**
2026-09-21 via the two-key mechanism; record:
[`spec/decision-records/0004-target-spec-ratification.md`](spec/decision-records/0004-target-spec-ratification.md)).
Design decisions behind those targets (the ISA, which flow produces the submitted
GDS, the firmware toolchain) are recorded in
[`spec/decision-records/`](spec/decision-records/). What's judged and how
it's checked is in [`spec/verification-plan.md`](spec/verification-plan.md).
Current status against every row and the 2027-01-18 deadline is tracked in
[`spec/gap-to-submission.md`](spec/gap-to-submission.md).

This block's evidence-tier (T1) state against the `klayout-tools` checklist
is graded, not hand-read: `klt signoff --manifest` renders it from the
committed block manifest at
[`manifests/sg13cmos5l-protocol-emulator.json`](manifests/sg13cmos5l-protocol-emulator.json)
(see [`manifests/README.md`](manifests/README.md) for how the report is
produced and where the committed verdict of record lives; the gap-to-T1
tracker is issue #27).

The `flow/` directory description below names Yosys and OpenROAD because that
is this program's standard digital flow; whether the *submitted* GDS comes
from it or from the Tiny Tapeout template's LibreLane flow is an open decision
record (see `spec/decision-records/0002-flow-of-record.md`).

## Repo layout

```
src/           Verilog sources, at the path the Tiny Tapeout template expects
info.yaml      Tiny Tapeout project metadata (top module, pinout, tile count)
test/          the Tiny Tapeout template's own cocotb harness (gds/test CI)
docs/          the Tiny Tapeout template's project datasheet source
flow/          synthesis + place-and-route (Yosys, OpenROAD), driven through klt
layout/        GDS + DRC/LVS reports (klayout-tools driven)
manifests/     the klt signoff block manifest that grades this block's T1 state
measurements/  silicon characterization (empty until tape-out)
rtl/           this program's own Verilog sources below the Tiny Tapeout
               top (the ISA core datapath + program memory, issues
               #18/#19); see rtl/README.md
spec/          ratified spec + decision records
verification/  this program's own cocotb bench + append-only evidence records
```

`src/`/`info.yaml`/`test/`/`docs/`/the `.github/workflows/{gds,test,fpga,docs}.yaml`
files are taken verbatim from the [Tiny Tapeout CMOS5L
template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l)
(issue #2); everything else is this program's own harness, ported from
[`2AMLogic/sky130-modexp`](https://github.com/2AMLogic/sky130-modexp).

The `gds` workflow — the LibreLane sign-off flow, and the only thing here that
builds a GDS — now passes end to end on `main` (`gds`/`precheck`/`gl_test`/
`viewer` all succeed) — last confirmed green on the harness-bootstrap
stub top (run `34905475502`; issue #18's core top re-runs it in CI). It
previously failed
before doing any work, on a confirmed upstream bug in the Tiny Tapeout action
it calls ([`TinyTapeout/tt-gds-action#52`](https://github.com/TinyTapeout/tt-gds-action/issues/52)),
which also skipped `precheck`/`gl_test`/`viewer`; that symptom stopped
reproducing on its own (the upstream issue remains open, unreconciled), and a
separate template gap that broke `gl_test` and a missing GitHub Pages setting
that broke `viewer` have both been fixed. Full write-up, including the
still-open upstream-issue caveat: [`layout/README.md`](layout/README.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
