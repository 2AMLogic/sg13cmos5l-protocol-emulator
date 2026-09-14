# layout

GDS and DRC/LVS reports. Empty until there is something to lay out.

## Known blocker: the `gds` workflow cannot build a GDS today (upstream)

`.github/workflows/gds.yaml` — the LibreLane sign-off flow `CLAUDE.md` calls
"the competition's sign-off", and the only thing in this repo that produces a
GDS — **fails deterministically** at its first step and has never produced an
artifact. The failure is upstream, in the third-party action the workflow
calls, not in anything this repo owns.

**Symptom.** In the "Install ihp-sg13cmos5l PDK" step of
`TinyTapeout/tt-gds-action@ihp-cmos5l`:

```
fatal: destination path '/home/runner/pdk/ihp-sg13cmos5l' already exists and is not an empty directory.
##[error]Process completed with exit code 128.
```

**Root cause.** That action's `install_sg13cmos5l.sh` clones twice:

```bash
git clone --branch dev https://github.com/IHP-GmbH/IHP-Open-PDK.git "$PDK_ROOT"
git clone https://github.com/IHP-GmbH/ihp-sg13cmos5l.git "$PDK_ROOT/ihp-sg13cmos5l"
```

`IHP-Open-PDK@dev` was restructured to vendor `ihp-sg13cmos5l/` inline, so the
*first* clone already materializes a non-empty `$PDK_ROOT/ihp-sg13cmos5l`, and
the second clone can never succeed.

**Upstream issue.** Already filed, by a third party, before this repo hit it:
[`TinyTapeout/tt-gds-action#52`](https://github.com/TinyTapeout/tt-gds-action/issues/52)
— "Latest IHP-Open-PDK causes issues in install_sg13cmos5l.sh" (opened
2026-09-11, open as of 2026-09-14). Its description matches this symptom
exactly, so per the friction protocol there is nothing new to file; this note
is the reference.

**Blast radius.** `precheck`, `gl_test`, and `viewer` all declare `needs: gds`,
so all three are *skipped*, not run — the entire LibreLane path currently
produces zero information. Consequences worth stating plainly:

- There is **no LibreLane cell count** to compare against the Yosys number in
  `verification/records/synthesis-baseline/` (issue #5). `CLAUDE.md`'s
  two-flows rule is unsatisfiable in this direction until `gds` runs at all —
  the two flows are not silently disagreeing, one of them is not running.
- The **gate-level regression** (`gl_test`) cannot run, because there is no
  GDS/gate-level netlist for it to run against.

**Not fixable from this repo.** `.github/workflows/gds.yaml` is taken verbatim
from the Tiny Tapeout CMOS5L template, as `CLAUDE.md`'s "Harness bootstrap"
section requires ("take it verbatim from the template's `cmos5l` branch"). The
only local "fixes" available — forking `tt-gds-action`, or pinning a different
ref — would deviate from that instruction and silently diverge this repo's
sign-off flow from the one the competition actually runs. Deliberately not
done. This resolves itself, with **no change on this side**, once
`tt-gds-action#52` is fixed upstream.

**Reproduced on** (all runs identical, this repo): PR-branch runs
[34802819850](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34802819850)
and
[34803033165](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34803033165),
then — after PR #7 merged — on `main` itself at `a3585ea`:
[34804131079](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34804131079)
(`fatal: destination path … already exists`, exit 128, same step). That last
run is the one to cite: it establishes the failure is a property of `main`, not
of an unmerged branch.

**Last re-probed**: 2026-09-14 — `tt-gds-action#52` still `state: open`, last
upstream activity 2026-09-11, zero comments. Re-probe it (and re-run `gds`)
before concluding anything downstream of this blocker is still stuck.
