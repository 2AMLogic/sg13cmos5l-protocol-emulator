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
- `run_synthesize_direct_yosys.py` — a **stopgap** runner for the recipes
  above. `klt synthesize` cannot resolve any liberty corner for
  `sg13cmos5l_stdcell` today (see the script's own docstring and
  `verification/records/synthesis-baseline/` for the filed gap and the
  worked-around run); this script reads the identical request document and
  drives Yosys directly with the same pass sequence `klt synthesize`
  documents, so it can be retired the moment the gap is fixed upstream.

Run the (stopgap) synthesis baseline with:

```bash
python3 flow/run_synthesize_direct_yosys.py flow/synthesize-protocol-emulator.json \
    --pdk-root "$PDK_ROOT" --out-dir /tmp/synth-out
```

Once the upstream liberty-naming gap is fixed, the same recipe should run
directly through `klt synthesize flow/synthesize-protocol-emulator.json
--pdk ihp-sg13cmos5l --format json` with no request-file changes.

See `verification/README.md` for the append-only evidence-record convention
these runs feed, and the root `README.md` / `CLAUDE.md` for why this flow
and the Tiny Tapeout LibreLane flow (`.github/workflows/gds.yaml`) are kept
as two independently-recorded flows rather than one.
