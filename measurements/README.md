# measurements

Silicon characterization. Empty until tape-out.

## Pre-silicon characterization report (T1 item 8)

`characterization.md` is **not** bench data. It is the pre-silicon
characterization report: one row per `spec/target-spec.md` row (target,
measured value, conditions, verdict, evidence record ids), plus Fmax per
corner, area and power, each naming the flow that produced it. It is generated
by `python3 scripts/characterization_report.py` from the committed records,
the tracker digest and `characterization-sources.json`; `--check` (run by
`npm run lint`, so by CI) fails on drift. `manifests/evidence/characterization.json`
is the generic envelope that pins its hash for item 8; its `status` is `pass`
only when no row fails.
