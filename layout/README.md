# layout

GDS and DRC/LVS reports. Empty until there is something to lay out.

## Former blocker: PDK-install failure cleared; `gl_test` fixed, `viewer` operator-only (issues #5, #10)

An earlier version of this section (added `dcbd4af`) documented the `gds`
workflow (`.github/workflows/gds.yaml`, `TinyTapeout/tt-gds-action@ihp-cmos5l`)
failing deterministically in its "Install ihp-sg13cmos5l PDK" step with
`fatal: destination path '/home/runner/pdk/ihp-sg13cmos5l' already exists and
is not an empty directory` (exit 128), tracked upstream at
[`TinyTapeout/tt-gds-action#52`](https://github.com/TinyTapeout/tt-gds-action/issues/52).

**That symptom is now confirmed stale.** GitHub Actions run
[`34884059362`](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34884059362)
(`main` @ `45af1c2`, 2026-09-14T18:58Z) shows the "Install ihp-sg13cmos5l PDK"
step succeeding in ~15s, with no clone conflict, in every job that runs it
(`gds`, `precheck`, `gl_test`). `tt-gds-action#52` itself is **still open
upstream** as of 2026-09-14 — the install succeeding here despite that is
unreconciled (possibly a PDK mirror/cache change, or an intermittent failure
mode; not investigated further). Do not assume the install is durably fixed
without a re-check; do assume the *exact* exit-128 symptom this section used
to describe is gone.

**What now works, precisely.** In that same run, the `Build GDS` job
**completed successfully end-to-end** — LibreLane ran `Yosys.Synthesis`
through `OpenROAD.FillInsertion`, `Magic.StreamOut`, and `Netgen.LVS`, and the
`precheck` job also passed. This is the first `gds` run to produce real
cell-count data for the harness-bootstrap stub; that data has been backfilled
into `verification/records/synthesis-baseline/records/` (issue #5).

**What was still broken as of run `34884059362` (now resolved for `gl_test`,
see below).** That run's overall `conclusion: failure` came from two *later*,
unrelated jobs:

- **`gl_test`** — the gate-level cocotb regression failed its own run
  (`Process completed with exit code 2`, `test/results.xml` missing).
- **`viewer`** — failed deploying its GDS render to GitHub Pages (`Creating
  Pages deployment failed`), because GitHub Pages is not enabled in this
  repo's settings. An operator/settings gap, not a code or flow defect.

Neither failure touches synthesis, placement, routing, or cell-count
reporting — both are downstream of the data this section (and issue #5) care
about.

## `gl_test` fixed: missing `sg13cmos5l_udp.v` in `test/Makefile` (issue #10)

**Root cause**, confirmed against run `34884059362`'s `gl_test` job log: Icarus
Verilog's gate-level elaboration failed with `17 error(s) during elaboration` /
`These modules were missing: ihp_dff_r referenced 8 times. ihp_mux2 referenced
8 times.` `sg13cmos5l_stdcell.v`'s structural cell models instantiate lower-level
`ihp_*` Verilog user-defined primitives (UDPs — `ihp_mux2`, `ihp_dff_r`, and 14
others) that live in a **separate** PDK file, `sg13cmos5l_udp.v`, in the same
directory. `test/Makefile`'s `GATES=yes` `VERILOG_SOURCES` list included
`sg13cmos5l_stdcell.v` but never `sg13cmos5l_udp.v`.

This gap is **inherited from the upstream Tiny Tapeout CMOS5L template** — this
repo's `test/Makefile` was byte-for-byte identical to
`TinyTapeout/ttihp-verilog-template@cmos5l`'s copy, which has the same
omission. It is a genuine upstream harness bug, not a local regression, and not
a deviation from `CLAUDE.md`'s "take the template's `test/` harness verbatim"
instruction so much as a necessary patch to it.

**Fix**: `test/Makefile`'s `GATES=yes` branch now also lists

```
VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_udp.v
```

next to the existing `sg13cmos5l_stdcell.v` line.

**Verified fixed** by a fresh `gds` workflow run on this fix:
[`34895381099`](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34895381099)
(branch `feature/issue-10` @ `68201e3`, 2026-09-14T20:51Z). The `gl_test` job
now completes with `conclusion: success` — no `Unknown module type` / elaboration
errors, and the cocotb summary line reads `TESTS=1 PASS=1 FAIL=0 SKIP=0`.

Consider filing the missing-UDP gap upstream against
`TinyTapeout/ttihp-verilog-template` (or `tt-gds-action`) so other CMOS5L Tiny
Tapeout projects don't hit the same wall; not done as part of this fix.

## `viewer` / GitHub Pages: confirmed operator-only, still unresolved

Confirmed via `gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pages`
returning `404 Not Found`, and reproduced again in run `34895381099` above (the
`viewer` job's own error: `Failed to create deployment... Ensure GitHub Pages
has been enabled: https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/settings/pages`).
**This requires an operator to enable GitHub Pages in this repo's Settings →
Pages** (build/deployment source: GitHub Actions) — no code-side fix applies;
`.github/workflows/gds.yaml`'s `viewer` job is taken verbatim from the Tiny
Tapeout CMOS5L template per `CLAUDE.md`'s harness-bootstrap instruction, and
the failure is entirely explained by the missing repo setting.

**Not fixable from this repo (for the `gds` job itself).**
`.github/workflows/gds.yaml` is taken verbatim from the Tiny Tapeout CMOS5L
template, as `CLAUDE.md`'s "Harness bootstrap" section requires ("take it
verbatim from the template's `cmos5l` branch"). Forking `tt-gds-action` or
pinning a different ref to chase the `viewer` failure would deviate from that
instruction; enabling Pages in Settings is the correct fix.

**Last re-probed**: 2026-09-14, against runs `34884059362` (pre-fix) and
`34895381099` (post-fix). Re-probe before concluding anything about the
PDK-install step, `gl_test`, or `viewer` is still in the state described here.

## `viewer` / GitHub Pages: now resolved — operator enabled Pages (issue #2)

The operator-only gap described in the section above has been closed:
`gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pages` now returns a
populated config (`build_type: "workflow"`, `source.branch: "main"`) instead
of `404 Not Found`. GitHub Pages has been enabled in this repo's Settings →
Pages with the GitHub Actions build/deployment source, exactly as the section
above asked for.

**Confirmed end-to-end on a fresh `gds` run**: workflow run
[`34905475502`](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34905475502)
(`main` @ `599fd0e`, 2026-09-14T22:43Z) completed with all four `gds`-workflow
jobs succeeding — `gds`, `precheck`, `gl_test`, and `viewer` — the first run in
this repo's history to do so. This is the last item that was still open on
issue #2's first acceptance criterion ("the `gds` and `test` workflows pass on
`main`"); with it cleared, that criterion is fully met, and there is no
further code-side or settings-side gap remaining in the Tiny Tapeout template
checklist that this section (and the two above it) track.

**Last re-probed**: 2026-09-14, against run `34905475502`. As always, re-probe
before concluding anything about the PDK-install step, `gl_test`, or `viewer`
is still in the state described here — this section supersedes the "still
unresolved" framing above by recording why, not by editing it away.
