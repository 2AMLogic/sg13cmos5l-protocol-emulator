# layout

GDS and DRC/LVS reports. Empty until there is something to lay out.

## Former blocker: PDK-install failure cleared; `gds` still fails downstream (issue #5)

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

**What is still broken, precisely.** The overall workflow run still reports
`conclusion: failure`, at two *later*, unrelated jobs:

- **`gl_test`** — the gate-level cocotb regression fails its own run
  (`Process completed with exit code 2`, `test/results.xml` missing). Not
  investigated in this pass; if worth tracking, file a dedicated follow-up
  issue rather than assuming it shares a root cause with the (now-resolved)
  PDK-install symptom this section used to describe.
- **`viewer`** — fails deploying its GDS render to GitHub Pages (`Creating
  Pages deployment failed`), because GitHub Pages is not enabled in this
  repo's settings. An operator/settings gap, not a code or flow defect.

Neither failure touches synthesis, placement, routing, or cell-count
reporting — both are downstream of the data this section (and issue #5) care
about.

**Not fixable from this repo (for the `gds`/`gl_test`/`viewer` jobs
themselves).** `.github/workflows/gds.yaml` is taken verbatim from the Tiny
Tapeout CMOS5L template, as `CLAUDE.md`'s "Harness bootstrap" section requires
("take it verbatim from the template's `cmos5l` branch"). Forking
`tt-gds-action` or pinning a different ref to chase either remaining failure
would deviate from that instruction. The `viewer` failure is fixable by
enabling GitHub Pages in this repo's settings (an operator action, not a code
change); the `gl_test` failure needs its own investigation.

**Last re-probed**: 2026-09-14, against run `34884059362`. Re-probe before
concluding anything about the PDK-install step, `gl_test`, or `viewer` is
still in the state described here.
