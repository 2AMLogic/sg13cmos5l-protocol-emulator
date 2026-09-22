# flow

Synthesis and place-and-route recipes (Yosys, OpenROAD), driven through klt
-- this program's own digital flow, distinct from the Tiny Tapeout template's
LibreLane flow (`src/config.json`, `.github/workflows/gds.yaml`). Per
`CLAUDE.md`'s two-flows rule, every synthesis/timing number this repo
reports names which flow produced it, and a disagreement between the two is
recorded rather than silently resolved.

## Contents

- `synthesize-protocol-emulator.json` — a `klt.synthesize.request/1` recipe
  synthesizing `src/tt_um_2amlogic_protocol_emulator.v` against
  `sg13cmos5l_stdcell` via Yosys.
- `synthesize-program-memory.json` — the same recipe shape for
  `rtl/protocol_program_memory.v` (the 256x16-bit program memory +
  serial load-phase logic, issue #19): same `klt.synthesize.request/1`
  schema, same cell library and corner, same 20 ns (50 MHz) clock
  constraint. Its results feed
  `verification/records/program-load-phase/` like any other run.
- `run-sta-corner-sweep.sh` — a standalone multi-corner static-timing
  runner (`klt sta`, verilog mode) over **one freshly synthesized gate-level
  netlist** of a recipe's output, at all six `sg13cmos5l_stdcell`
  liberty corners the PDK ships. This is the target-spec row-4 / T1
  item-5 corner-sweep leg (issue #20): the corner list in the script **is**
  the declared corner set this block is held to — the target spec and its
  decision records are now ratified (issue #17 / PR #29, so T1 item 5's
  verdicts are no longer provisional-on-a-draft), and folding the corner
  matrix into a spec decision record is tracked there. Every number it
  reports is a `geometry_source: "netlist_estimate"`
  number (cell delays + the liberty's own default `1k`/`top` wire-load
  model, never routing parasitics) — see the script's header for the
  environment requirements (`PDK_ROOT` must be exported for the common
  docker-wrapped `openroad`; `KLT_BIN` can point at a pinned install).
- `run-die-area-par.sh` — the target-spec row-7 die-area leg (issue #21):
  synthesizes both existing tops fresh (`rtl/protocol_program_memory.v`
  and the stub `src/tt_um_2amlogic_protocol_emulator.v`), runs
  `klt place-and-route` on each with `target_stage: "place"` (floorplan at
  a stated utilization **through legalized placement** — one stage past
  the floorplan minimum issue #21's dependency note asks for, so the
  utilization figure is a placed one), and folds the numbers plus the
  tile-budget arithmetic (1 tile ≈ 167 × 108 µm per the template's
  `info.yaml`) into `flow/die-area-par-results.json`. First P&R run of
  this flow against this PDK — the enabling pin verification is
  `layout/toolchain.json`'s 2026-09-22 paragraph (`place-and-route` added
  to `klt_required_commands`). `cts`/`route` are **not** reached:
  `sg13cmos5l_stdcell` has no verified CTS-buffer/routing-layer/antenna
  table entry in klt at this pin (a klayout-tools capability gap, recorded
  in the die-area record — not worked around). Same environment
  requirements as the corner sweep (`PDK_ROOT`, `KLT_BIN`,
  docker-wrapped `openroad`).
- `run-post-layout-sdf.sh` — the T1 item-7 post-route SDF regression
  runner (issue #26): downloads the `gds` workflow's `tt_submission` +
  `GDS_logs` artifacts (or takes `--from <dir>`), freezes the final
  **post-route gate-level netlist** and the **per-corner SDFs** LibreLane's
  post-route STA stage emits, and re-runs this repo's own committed cocotb
  bench (`verification/test_protocol_emulator.py`, unmodified, via
  `testbench.search_path`) against that netlist with `options.sdf` set —
  one `klt functional-verification` run per emitted corner, each required
  to report `environment.sdf.annotated: true` and `status: "pass"`. The
  SDF normalization it applies for Icarus 13.0 (header `min::max` triplets
  filled, klayout-tools#1880; all-zero INTERCONNECTs onto assign-aliased
  ports dropped, klayout-tools#2285) is mechanically audited per corner in
  a `*.normalization.json` report; original and normalized bytes are both
  frozen by the evidence record
  (`verification/records/post-layout-sdf-regression/`). Environment:
  `klt` at the `layout/toolchain.json` pin (`KLT_BIN` honored), Icarus
  >= 13.0, a resolvable `ihp-sg13cmos5l` PDK, and `gh` for `--run-id`
  mode.
- `run_synthesize_direct_yosys.py` — the **historical** stopgap runner for
  the recipes above, kept for record history only
  (`verification/records/synthesis-baseline/` cites it). It predates the
  upstream resolution of `2AMLogic/klayout-tools#1786` (liberty-naming),
  which closed 2026-09-14: with `layout/toolchain.json`'s klt pin at
  1d964cf4 or later, plain
  `klt synthesize flow/synthesize-protocol-emulator.json --pdk ihp-sg13cmos5l --format json`
  drives the synthesis leg itself — verified live 2026-09-21, issue #20 —
  and `run-sta-corner-sweep.sh` uses it that way. Nothing on the active
  path invokes this script anymore; do not delete it (the records cite it
  by content hash), and do not route new work through it.

Run the (now-canonical) synthesis leg with:

```bash
klt synthesize flow/synthesize-protocol-emulator.json --pdk ihp-sg13cmos5l --format json
```

Run the STA corner sweep with:

```bash
./flow/run-sta-corner-sweep.sh                 # all 6 shipped corners
KLT_BIN=.venv/bin/klt ./flow/run-sta-corner-sweep.sh   # pinned local install
```

Both write scratch under `flow/.klt/`, `flow/sta-sweep/`,
`flow/sta-corners/`, and `flow/sta-corner-sweep-results.json` (all
gitignored); the evidence record under
`verification/records/sta-corner-sweep/artifacts/` freezes the copies
that constitute the claim.

Run the die-area leg (issue #21) with:

```bash
./flow/run-die-area-par.sh
KLT_BIN=.venv/bin/klt ./flow/run-die-area-par.sh       # pinned local install
```

It writes scratch under `flow/.klt/`, `flow/par-scratch/`, and
`flow/die-area-par-results.json` (all gitignored); the evidence record
under `verification/records/die-area-baseline/artifacts/` freezes the
copies that constitute the claim.

See `verification/README.md` for the append-only evidence-record convention
these runs feed, and the root `README.md` / `CLAUDE.md` for why this flow
and the Tiny Tapeout LibreLane flow (`.github/workflows/gds.yaml`) are kept
as two independently-recorded flows rather than one.
