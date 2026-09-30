# rtl/vendor — vendored PDK simulation models

Files here are **copied verbatim from the IHP Open PDK** and are not this
repo's work. They exist so every simulation leg in this repo (the
template's `test/` harness and this program's own `klt
functional-verification` benches) can elaborate the
`RM_IHPSG13_1P_256x16_c2_bm_bist` SRAM macro without a `$PDK_ROOT`
dependency, and so the evidence records under `verification/records/` can
hash the exact model bytes a run used (`provenance.inputs[]` only hashes
tracked repo files — an out-of-tree PDK path is unhashable, so a model
swap underneath a record would be invisible).

Adopted by issue #18 when it implemented
[`spec/decision-records/0005-program-memory-implementation.md`](../../spec/decision-records/0005-program-memory-implementation.md)
Decision item 1 (the program-memory macro swap).

## Provenance

| | |
|---|---|
| Source install | `<PDK_ROOT>/ihp-sg13cmos5l/libs.ref/sg13cmos5l_sram/verilog/` |
| …which is a symlink to | `<PDK_ROOT>/ihp-sg13g2/libs.ref/sg13g2_sram/verilog/` (IHP ships **one** SRAM macro set shared by SG13G2 and CMOS5L — see DR 0005 "Finding 1") |
| Upstream project | [IHP-GmbH/IHP-Open-PDK](https://github.com/IHP-GmbH/IHP-Open-PDK) |
| PDK revision used by the flow of record | `2bbec755dc67…` (the revision `tt-gds-action@ihp-cmos5l`'s `install_sg13cmos5l.sh` checks out; recorded in DR 0005) |
| Licence | Apache-2.0, "Copyright 2023/2025 IHP PDK Authors" — the licence header is intact in each file and is not modified here |
| Modifications | **None.** Byte-for-byte copies. |

| File | sha256 |
|---|---|
| `RM_IHPSG13_1P_256x16_c2_bm_bist.v` | `9d456840a37dff650ee6a09dc1f3d4e2d8d3348fcea7dc305933dd4543feff1a` |
| `RM_IHPSG13_1P_core_behavioral_bm_bist.v` | `e2e43ec0159cbc34662fe91114e8cb03a697a2a829ad63b0d4f06631908ea787` |

Re-derive with:

```bash
sha256sum "$(klt pdk find --pdk ihp-sg13cmos5l | awk '/libs_ref/{print $2}')"/sg13cmos5l_sram/verilog/RM_IHPSG13_1P_256x16_c2_bm_bist.v
```

## These files are for simulation only

They are deliberately **not** listed in `info.yaml`'s `source_files` and
therefore never reach LibreLane's `VERILOG_FILES`. The macro is a hard
block: the LibreLane flow blackboxes it against the PDK's LEF/liberty
(`MACROS` / `EXTRA_LEFS` / `EXTRA_LIBS` / `EXTRA_GDS_FILES` in
`src/config.json`), and this program's own `klt`/Yosys flow does the same.
Feeding the behavioural model to a synthesizer would infer a 4,096-flop
array — exactly the implementation DR 0005 measured as unplaceable and
replaced.

`RM_IHPSG13_1P_256x16_c2_bm_bist.v` has two elaboration modes, selected by
the `FUNCTIONAL` define:

- **`FUNCTIONAL` defined** — a plain behavioural instance, no `specify`
  block. This is what every zero-delay simulation in this repo uses
  (`test/Makefile` defines it for both the RTL and the gate-level leg; the
  `klt` requests set `options.defines.FUNCTIONAL`), and it is what the Tiny
  Tapeout `gl_test` action already defines for the standard cells.
- **`FUNCTIONAL` undefined** — the same instance wrapped in a `specify`
  block with `$setuphold`/`$width` timing checks, for an SDF-annotated
  post-layout run. `klt functional-verification` deliberately refuses
  `options.sdf` together with `FUNCTIONAL`, so the post-layout SDF leg
  (`flow/run-post-layout-sdf.sh`) must elaborate this file **without** the
  define and annotate the macro's own SDF — see that leg's note in
  `spec/gap-to-submission.md` row 8.
