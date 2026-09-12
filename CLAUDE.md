# sg13cmos5l-protocol-emulator — agent instructions

Open-source canary block: a Protocol emulator ASIC on the IHP SG13CMOS5L PDK,
designed and verified by AI agents — a **digital** block.

- **PDK**: IHP SG13CMOS5L (open PDK).
  cocotb + Icarus for verification, Yosys for synthesis, OpenROAD for place-and-route.
  Layout, DRC, and LVS go through klayout-tools (`klt`).
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker is
  scoped to the tool, so keep design-specific detail (spec values, this repo's
  content) out of it and describe the gap, not the design.
- **Verification is the product**: no claim without a testbench. Recorded
  results are append-only evidence; a result is not superseded by deletion, it
  is superseded by a later record that says why.
- Spec changes go through `spec/` with a decision record. Agents do not relax
  the ratified spec to make a result pass.

- **The ISA is the product; do not build fixed-function peripherals.** The
  brief asks for a tiny CPU whose instructions read pins, write pins, count
  cycles and hit timing, so that UART/SPI/I2C are *firmware*. The mistake most
  likely here is to "help" a protocol along with a dedicated UART or SPI
  block in RTL. A hardware peripheral for any target protocol is out of scope
  unless a decision record in `spec/` admits it and says why the ISA could
  not. Prove timing with the core alone.
- **Two flows, one record of truth.** The competition's sign-off is the Tiny
  Tapeout CMOS5L template (LibreLane in GitHub Actions); this program's flow
  is `klt`/Yosys/OpenROAD, which does not yet know the CMOS5L cells. Never
  report a synthesis or timing number without naming which flow produced it,
  and never let the two disagree silently — a mismatch is a finding to
  record, not a number to pick from.
- **Firmware is evidence.** A protocol claim ("this core does I2C fast mode")
  is only true when a committed program, run on the RTL under cocotb, passes
  against an independent reference model of that protocol with the timing
  checked. The program is part of the evidence record, byte for byte.
- **Deadline discipline.** Submissions are due 2027-01-18. Work that cannot
  reach the submitted design by then (stretch protocols, silicon-side
  features) goes in a decision record as deferred, not into the RTL.

## Harness bootstrap

Copy from `2AMLogic/sky130-modexp`, this program's first digital canary: it
supplies the RTL→GDS half — the `klt synthesize` / `klt
functional-verification` / `klt drc` entry points, the cocotb bench layout
under `verification/` with append-only `records/`, the gate-level regression,
and the `flow/*.json` recipe shape. Port that harness onto the CMOS5L
standard cells (`sg13cmos5l_stdcell`, `libs.tech/librelane/` in the PDK).
The other half — the Tiny Tapeout template wiring (`info.yaml`, the
`tt_um_*` top with the fixed pin budget, the template's `test/` cocotb
harness and its `gds`/`test`/`fpga` Actions workflows) — has no sibling in
this program; take it verbatim from the template's `cmos5l` branch and keep
the template's files where the template expects them. See issue #2.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
