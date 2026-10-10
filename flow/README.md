# flow

Synthesis and place-and-route recipes (Yosys, OpenROAD), driven through klt
-- this program's own digital flow, distinct from the Tiny Tapeout template's
LibreLane flow (`src/config.json`, `.github/workflows/gds.yaml`). Per
`CLAUDE.md`'s two-flows rule, every synthesis/timing number this repo
reports names which flow produced it, and a disagreement between the two is
recorded rather than silently resolved.

## Contents

- `_klt.sh` — sourced-not-executed helper shared by the three bash runners
  below (`run-sta-corner-sweep.sh`, `run-die-area-par.sh`,
  `run-post-layout-sdf.sh`): `klt_resolve`, `klt_require_verbs`,
  `klt_export_pdk_root`, and `klt_response_path` (the `{path, scope}` /
  `2AMLogic/klayout-tools#2073` unwrap, named in exactly this one place —
  issue #47).
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
  `info.yaml`) into `flow/die-area-par-results.json`. **That tile constant is
  superseded** (2026-09-25, issue #39): the flow of record sizes the die from
  `tile_sizes.yaml`, vendored in `flow/tt-cmos5l-reference.json`, and the
  corrected arithmetic lives in `run-sram-macro-feasibility.py` below. This
  runner's *measured* die/cell areas are unaffected and still stand; only the
  tile comparison it derives from them is wrong. First P&R run of
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
- `run-reset-power-up-gate-level.sh` — target-spec row 14 /
  `spec/verification-plan.md` section 8 (issue #131): reset, power-up and
  reselect on the **LibreLane gate-level netlist** (default: the frozen
  copy under `verification/records/post-layout-sdf-regression/`),
  zero-delay, Icarus + cocotb through `test/Makefile` `GATES=yes`, the same
  plumbing `run-firmware-gate-level.sh` uses. It runs the reset-coverage
  listing (`verification/reset_coverage.py` against
  `verification/reset_coverage_justifications.json`) and the bench
  `verification/test_reset_power_up.py` (every flop forced to X or to a
  seeded random value, 8 recorded seeds, the SRAM array random or X, then
  `rst_n`), then three negative controls that must fail: a flop whose
  reset is tied off and which drives `uio_oe[0]` (bench and coverage
  check), a stale justification entry (coverage check), and the boot ROM
  bypassed at reset (bench). The netlist file is never edited; the
  mutants are copies, diffed into the scratch dir. Produces no synthesis
  or timing number of either flow. Needs `PDK_ROOT`, `iverilog` and
  `cocotb-config` (a throwaway venv is enough). Scratch:
  `flow/reset-power-up/` (gitignored). Evidence:
  `verification/records/reset-power-up/`.
- `run-sram-macro-feasibility.py` — the issue #39 program-memory feasibility
  probe: does an SRAM macro implementing DR 0001's ratified 256×16 program
  memory exist for this PDK, and does it fit a legal Tiny Tapeout CMOS5L tile
  allocation? Stdlib-only Python plus three read-only klt verbs
  (`pdk find`, `stats`, `layers`). It resolves the PDK, reports whether
  `libs.ref/sg13cmos5l_sram` exists **and how** (it is a symlink into the
  SG13G2 tree — load-bearing, see the record), reads the whole `RM_IHPSG13_1P_*`
  family's footprints out of their LEF `SIZE` statements, cross-checks the
  selected macro's GDS layer inventory against the **competition precheck's
  own** CMOS5L layer allowlist (resolved through the PDK's `.lyp` exactly as
  `precheck.load_layers()` does), and re-derives the tile budget for every
  legal `tiles` value. **It runs no synthesis, P&R, STA or DRC and claims no
  utilization/timing/routability result.** Evidence:
  `verification/records/program-memory-macro-feasibility/`.
- `tt-cmos5l-reference.json` — the upstream constants that probe depends on,
  vendored with repo/ref/blob-sha provenance rather than transcribed:
  `tech/ihp-sg13cmos5l/tile_sizes.yaml` (the **DIE_AREA per `tiles` value the
  flow of record actually hardens into** — not the template comment's
  order-of-magnitude 167 × 108 µm tile), `precheck/tech_data.py`'s
  `valid_layers_ihp_sg13cmos5l` allowlist, this repo's own `src/config.json`
  margins, and how `tt-gds-action@ihp-cmos5l` materializes the PDK. Both
  upstream files are taken at the `ihp-sg13cmos5l` branch of
  `TinyTapeout/tt-support-tools`, which is the ref
  `tt-gds-action@ihp-cmos5l` defaults `tools-ref` to — i.e. the ref this
  repo's `gds` workflow really runs. Keep it append-only: re-vendor under a
  new provenance stamp, never edit a value under an old one.
- *(removed)* `run_synthesize_direct_yosys.py` — the historical direct-Yosys
  stopgap runner for the recipes above, written while
  `2AMLogic/klayout-tools#1786` (liberty-naming) was open. That gap closed
  2026-09-14; with `layout/toolchain.json`'s klt pin at 1d964cf4 or later,
  plain `klt synthesize` drives the synthesis leg itself (verified live
  2026-09-21, issue #20), and `run-sta-corner-sweep.sh` uses it that way.
  The script was **retired from the active path** on 2026-09-21 and
  **deleted** on 2026-10-07 (issue #32). It had been kept until then only
  because records hashed it as an input. Those records are all superseded
  now, and `verification/check_records.py` does not re-hash a superseded
  record's inputs: `synthesis-baseline` `20260914-032200-7e4a21a` →
  `20260914-203044-45af1c2` → `20260930-195410-ead870a`, and
  `program-load-phase` `20260921-185910-248bf61` →
  `20260930-195410-ead870a`. Neither successor lists the script as an
  input. The superseded records still cite it by path and content hash as
  frozen history. Recover the bytes with
  `git show 01c0095:flow/run_synthesize_direct_yosys.py` if you need them.
  Mentions in `_klt.sh` / `run-sta-corner-sweep.sh` comments stay on
  purpose, because live records hash those files whole.

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

Run the program-memory macro feasibility probe (issue #39) with:

```bash
./flow/run-sram-macro-feasibility.py
KLT_BIN=.venv/bin/klt ./flow/run-sram-macro-feasibility.py   # pinned local install
```

It needs only a resolvable `ihp-sg13cmos5l` PDK and `klt` — no `openroad`, no
docker — and writes `flow/sram-macro-feasibility-results.json` (gitignored);
`verification/records/program-memory-macro-feasibility/artifacts/` freezes the
copy that constitutes the claim.

See `verification/README.md` for the append-only evidence-record convention
these runs feed, and the root `README.md` / `CLAUDE.md` for why this flow
and the Tiny Tapeout LibreLane flow (`.github/workflows/gds.yaml`) are kept
as two independently-recorded flows rather than one.
