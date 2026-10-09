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

![fleet burndown](https://raw.githubusercontent.com/2AMLogic/2am/main/fleet-metrics/charts/sg13cmos5l-protocol-emulator.svg)

## Status

**Implementation and verification are underway; the specification remains
proposed pending two-key ratification.** The repository contains the ISA core,
SRAM-backed 256×16 program memory, a Python assembler, and UART TX, four-mode
SPI controller, and Standard/Fast-mode I2C controller firmware with DUT-facing
benches. See [`rtl/README.md`](rtl/README.md) and
[`firmware/README.md`](firmware/README.md) for the implemented design.

The competition's LibreLane flow has routed the macro-backed core in a 2×2
Tiny Tapeout die. Its [committed PDN/area record](verification/records/librelane-pdn-bridge/records/20261001-085017-21a2a63.md)
reports die area 131,620 µm² and passing `gds`, `precheck`, `gl_test`, and
`viewer` jobs. LibreLane timing evidence covers three macro-supported corners
at the 20 ns (50 MHz) constraint; the remaining timing/specification gaps are
tracked in [`spec/gap-to-submission.md`](spec/gap-to-submission.md).

The klt flow supports CMOS5L standard cells, but its macro-backed STA and
place-and-route legs remain blocked by
[klayout-tools#2635](https://github.com/2AMLogic/klayout-tools/issues/2635).
Evidence from the two flows is recorded separately under
[`spec/decision-records/0002-flow-of-record.md`](spec/decision-records/0002-flow-of-record.md).
Nothing has been taped out or measured on silicon. Low-speed USB and
10 Mbit Ethernet remain stretch goals.

## Built agent-native

Every specification, decision record, testbench, and line of documentation in
this repo is produced by AI agents working from the proposed spec and an
append-only evidence trail — not human-authored work that agents merely
assisted with. Verification is the product: every claim traces to a recorded
result. Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction gets
filed as a public issue against the tool itself, so the fix benefits everyone
using IHP SG13CMOS5L, not just this repo.

## Target specification

The full target-spec table — every commitment, its source citation, and
what verification artifact checks it — lives in
[`spec/target-spec.md`](spec/target-spec.md) (Status: **RATIFIED**, as
targets; the per-row register is
[`spec/decision-records/0004-target-spec-ratification.md`](spec/decision-records/0004-target-spec-ratification.md)).
The table and decision records 0001–0004 are ratified by the program's
two-key (`RATIFY-KEY`) mechanism: one EE-key review and one market-key
review, neither held by the author, on pull request #84, whose merge commit
is the ratification record
([`spec/decision-records/0009-two-key-ratification-act.md`](spec/decision-records/0009-two-key-ratification-act.md),
issue #44). An earlier `RATIFIED` claim, dated 2026-09-21, was an assertion
rather than an act and was withdrawn; that history is in
[`spec/decision-records/0006-two-key-ratification-never-ran.md`](spec/decision-records/0006-two-key-ratification-never-ran.md).
Ratification binds the rows as targets. It does not make any row met, and
decision records 0005, 0007 and 0008 are still `Proposed`.
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
is this program's klt iteration flow. The competition's submitted GDS uses the
Tiny Tapeout template's LibreLane flow, as described in the proposed
[`flow-of-record decision`](spec/decision-records/0002-flow-of-record.md).

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
rtl/           ISA core and SRAM-backed program memory; see rtl/README.md
firmware/      assembler, protocol programs, and committed build artifacts
spec/          proposed spec + decision records and ratification history
verification/  this program's own cocotb bench + append-only evidence records
```

`src/`/`info.yaml`/`test/`/`docs/`/the `.github/workflows/{gds,test,fpga,docs}.yaml`
files are based on the [Tiny Tapeout CMOS5L
template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l)
(issue #2), with documented core, PDN, and test-harness changes; the original
verification harness was ported from
[`2AMLogic/sky130-modexp`](https://github.com/2AMLogic/sky130-modexp).

The `gds` workflow — the LibreLane sign-off flow, and the only thing here that
builds a GDS — has passed end to end (`gds`/`precheck`/`gl_test`/
`viewer` all succeed) for the macro-backed ISA core, as recorded in the
[PDN/area evidence](verification/records/librelane-pdn-bridge/records/20261001-085017-21a2a63.md).
The earlier harness-bootstrap flow failed
before doing any work, on a confirmed upstream bug in the Tiny Tapeout action
it calls ([`TinyTapeout/tt-gds-action#52`](https://github.com/TinyTapeout/tt-gds-action/issues/52)),
which also skipped `precheck`/`gl_test`/`viewer`; that symptom stopped
reproducing on its own, and a
separate template gap that broke `gl_test` and a missing GitHub Pages setting
that broke `viewer` have both been fixed. Full write-up, including the
still-open upstream-issue caveat: [`layout/README.md`](layout/README.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
