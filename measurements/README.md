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

### Owner audit (on demand)

`characterization_report.py` checks only the *shape* of each row's
`owner.issues` and never touches the network. To confirm those owners are still
open, run `python3 scripts/check_docs_issue_states.py --characterization-owners`
(needs network and an authenticated `gh`; deliberately not in `npm run lint` or
CI, like the other modes of that script, issue #238). It prints one line per
row/issue pair, so an owner shared by two rows appears twice, and skips
wait-only rows. Exit 0: every owner is an open issue; 1: at least one is
closed, missing or a pull request (printed as `MISMATCH ... row N: owner #M`);
2: the lookup could not complete. The Markdown-heuristic default mode cannot see
the Owner column, which holds bare links with no state wording.
