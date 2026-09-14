# Environment

This document records the pinned tool versions `scripts/setup-env.sh`
provisions for `verification/`'s `klt`-driven cocotb harness, and how the
`ihp-sg13cmos5l` PDK location is resolved for the parts of this repo that
need it. `verification/records/**/*.md` cite these versions (in each
record's `klt provenance` field); if you re-pin anything here, mint fresh
records rather than editing old ones (see `verification/README.md`'s
append-only rule).

Ported, near-verbatim in structure, from `2AMLogic/sky130-modexp`'s
`docs/environment.md` per `CLAUDE.md`'s "Harness bootstrap" section (issue
#6) — adapted where this repo's toolchain genuinely differs (see "Why this
differs from sky130-modexp's script" below).

## Provisioning: `scripts/setup-env.sh`

```bash
./scripts/setup-env.sh
```

This installs `klayout-tools` (`klt`) as a [`uv`](https://docs.astral.sh/uv/)
tool, together with pinned `cocotb`/`cocotb-tools` versions in one shot,
resolves the `ihp-sg13cmos5l` PDK location via `klt pdk find`, and checks
`iverilog` / `yosys` / `openroad` on `$PATH` — reporting what's missing with
an actionable install pointer, never a traceback. It is safe to re-run
(`uv tool install --force` reinstalls cleanly). `./scripts/setup-env.sh
--help` prints the script's own header comment with the full rationale.

## Pinned versions

| Component | Pinned to | Resolved via |
|---|---|---|
| `klayout-tools` (`klt`) | the exact git revision recorded in [`layout/toolchain.json`](../layout/toolchain.json)'s `klt_install` field — **not duplicated here**, so the two flows (`layout/`'s DRC/LVS and `verification/`'s cocotb harness) can never drift onto different `klt` pins by accident. As of this writing: [`5c757081680e207b6abbc7a6ca7d3688ad07072a`](https://github.com/2AMLogic/klayout-tools/commit/5c757081680e207b6abbc7a6ca7d3688ad07072a) (bumped by issue #2, 2026-09-14) | `uv tool install --force --with cocotb==2.1.0 --with cocotb-tools==0.1.0 "klayout-tools @ $(python3 -c "import json;print(json.load(open('layout/toolchain.json'))['klt_install'])")"` (what `scripts/setup-env.sh` runs) |
| `cocotb` | `2.1.0` (pinned explicitly in `scripts/setup-env.sh`, installed as a `uv tool install --with` extra alongside `klt`) | verified end-to-end: `klt functional-verification verification/request-protocol-emulator.json --format json` reports `"cocotb_version": "2.1.0"` in its `environment` block |
| `cocotb-tools` | `0.1.0` (its only published release as of this writing) | same `uv tool install --with` step |
| Python | whatever `uv`'s own resolver selects for `klayout-tools`' `requires-python = ">=3.10"` floor — `uv tool install` manages this itself; no separate interpreter-selection step is needed here (contrast with sky130-modexp's script, which hand-picks an interpreter — see "Why this differs" below) | `uv tool install` |

**Pin rationale**: `scripts/setup-env.sh` deliberately reads the `klt` pin
live from `layout/toolchain.json` instead of hardcoding a second copy of the
commit hash. `layout/toolchain.json`'s own append-only comment log is the
authoritative history of every `klt` pin bump and why — see that file
directly for the full rationale chain, rather than duplicating it here where
it could go stale independently.

## `iverilog` / `yosys` / `openroad`

`klt` resolves these three from the host — it does not vendor them.
`scripts/setup-env.sh`'s step 3 checks each is on `$PATH` and prints an
actionable install pointer (a package-manager command or upstream install
doc link) for any that are missing, rather than letting a downstream `klt`
command fail with an opaque error.

| Tool | Used for | Resolved version on the environment these records were produced on |
|---|---|---|
| Icarus Verilog (`iverilog`) | `klt functional-verification` (the only leg this script's acceptance criterion requires) | 12.0 (stable) (`iverilog -V`) |
| Yosys (`yosys`) | `flow/run_synthesize_direct_yosys.py` (stopgap; `klt synthesize` itself, once [`2AMLogic/klayout-tools#1786`](https://github.com/2AMLogic/klayout-tools/issues/1786)'s liberty-naming gap is fixed) | 0.68 (`yosys -V`) |
| OpenROAD (`openroad`) | any future place-and-route leg of `flow/` (this program's own flow; distinct from the Tiny Tapeout LibreLane flow, which bundles and drives its own OpenROAD internally — see `.github/workflows/gds.yaml`) | `26Q3-1278-g4421880472` (`openroad -version`) |

Unlike `sky130-modexp`, this repo does not pin or wrap `openroad` behind a
Docker fallback: at the time this document was written, a native `openroad`
was already available on `$PATH` in every environment this script has been
exercised in, so there has been no provisioning gap to work around yet. If
that changes, extend `scripts/setup-env.sh`'s step 3 rather than silently
declaring `openroad` "missing" with no fallback — and record the new route
here.

## `$PDK_ROOT` for `ihp-sg13cmos5l`

**IHP SG13 PDKs are not distributed via [`volare`](https://github.com/efabless/volare)** — `volare` is Skywater/GlobalFoundries-specific (confirmed:
`sky130-modexp`'s own script fetches `sky130A` via `volare enable`, which has
no IHP equivalent to call). This is a genuine difference from
`sky130-modexp`'s script, not an oversight, and it changes what "provision
the PDK" can mean here — see "Why this differs" below.

### Two provisioning routes exist, and this repo does not yet unify them into one script step

- **Local dev** (what a contributor running `scripts/setup-env.sh` hits):
  there is no single canonical fetch command this script can shell out to.
  Instead, `scripts/setup-env.sh` calls `klt pdk find --pdk ihp-sg13cmos5l`
  — this program's **one shared PDK_ROOT resolver** (`klt pdk find --help`;
  every `layout/`/`flow/` runner that needs a PDK path already imports this
  same lookup instead of re-deriving it) — and reports whatever it resolves:
  root path, resolution method, and version stamp if one exists. If nothing
  resolves, the script prints where to get a PDK install from (see below)
  and how to point `$PDK_ROOT` at it; it does not fetch one itself, since
  there is no single trustworthy "the" IHP SG13CMOS5L PDK source with the
  same one-command reproducibility `volare enable <pdk> <version>` gives
  sky130-modexp.
- **CI** (`.github/workflows/gds.yaml` → `TinyTapeout/tt-gds-action@ihp-cmos5l`):
  provisions its own copy via that action's `install_sg13cmos5l.sh`, which
  `git init`s a fresh directory, `git fetch --depth 1`s a pinned commit of
  [`IHP-GmbH/IHP-Open-PDK`](https://github.com/IHP-GmbH/IHP-Open-PDK) (the
  `dev` branch, at whatever revision that action pins — see the action's own
  source at the `ihp-cmos5l` ref for the current pin), and `git checkout
  FETCH_HEAD`s it into `$PDK_ROOT` — writing a `SOURCES` stamp
  (`IHP-Open-PDK <rev>`) into the resulting `ihp-sg13cmos5l/` directory,
  mirroring how `ciel`-installed PDKs record their own provenance. This
  route is **not** invoked by `scripts/setup-env.sh` (see "Scope boundary"
  in the issue that added this script) — it is documented here so a reader
  comparing local vs. CI PDK provenance knows both routes exist and why they
  differ.

### Existing `$PDK_ROOT` conventions observed in this repo

Multiple `$PDK_ROOT` values are already in play across this repo's various
environments, and this document does not collapse them into one — it
records what each one is so a reader can tell them apart:

| Where | `$PDK_ROOT` | PDK source / provenance |
|---|---|---|
| `.devcontainer/Dockerfile` | `/home/vscode/ttsetup/pdk` | Not populated by the Dockerfile itself — left for whatever installs the PDK at container-run time (the devcontainer predates this script and does not yet call it). |
| This repo's own sandbox environments (where `verification/records/synthesis-baseline/`'s records were produced) | `/home/ubuntu/share/pdk` | A raw, unversioned checkout with no `volare`/`open_pdks`/`ciel` version stamp — `klt pdk find` resolves it (`resolved_via: "search root: ~/share/pdk"`) but reports `version: null`. |
| `.github/workflows/gds.yaml` CI runs | `/home/runner/pdk` (set by `tt-gds-action`'s own composite action) | `IHP-Open-PDK` at the pinned revision `tt-gds-action@ihp-cmos5l`'s `install_sg13cmos5l.sh` fetches, stamped via the `SOURCES` file it writes. |

`klt pdk find`'s search order (documented in its own `--help`) already
checks `$PDK_ROOT`, `$PDK`, and a list of common install roots including
`~/share/pdk`, so `scripts/setup-env.sh` finds whichever of the above is
present on the host it runs on without needing to hardcode any of them.
**This script does not pick a winner among the three** — that would require
either fetching a PDK copy of its own (rejected — see above) or asserting
one of the existing ad hoc locations is "the" canonical one when none of
them is authoritative today. A future issue that actually needs local
`layout/` DRC/LVS or `klt synthesize` runs to be reproducible byte-for-byte
should revisit this and either wire a `--pdk-root` fetch step into this
script (once a trustworthy, versioned IHP PDK source is settled on) or
formally adopt one of the existing locations as canonical.

### Why `klt functional-verification` doesn't need any of this

`klt functional-verification verification/request-protocol-emulator.json`
drives Icarus + cocotb directly against `src/tt_um_2amlogic_protocol_emulator.v`
— an RTL-level cocotb bench with no standard-cell library dependency at all.
It has no PDK dependency, so this script's PDK-resolution step (step 2) is
purely informational for that specific acceptance criterion; it exists
because a *future* `verification/` or `layout/` runner (a gate-level cocotb
run with `GATES=yes`, `klt drc`, `klt synthesize`) does need one, and having
`scripts/setup-env.sh` report the resolved (or unresolved) `$PDK_ROOT` up
front is cheaper than debugging a downstream tool's cryptic "file not found"
once one of those runners is added.

## Why this differs from `sky130-modexp`'s script

- **No `volare` PDK-fetch step.** `sky130-modexp`'s script's step 3 runs
  `volare enable --pdk-root ... --pdk sky130 <rev>` unconditionally. There is
  no IHP equivalent, so this script's step 2 resolves-and-reports via
  `klt pdk find` instead of fetching — see "$PDK_ROOT for ihp-sg13cmos5l"
  above for the full reasoning.
- **`klt` installed via `uv tool install`, not a hand-rolled `.venv` +
  `pip install`.** This repo's own `layout/toolchain.json` and
  `verification/README.md`'s prior ad hoc workaround both already used `uv
  tool install`; this script continues that convention (and reads the pin
  straight from `layout/toolchain.json`) rather than introducing a second,
  `pip`-based install mechanism sky130-modexp happened to pick.
- **No hand-rolled Python-interpreter-version selection loop.**
  `sky130-modexp`'s script picks a `python3.13`/`3.12`/`3.11`/`3.10`
  interpreter itself because its `pip install`-based venv approach needs one
  compatible with cocotb 2.0.1's upper Python-version cap. `uv tool install`
  manages its own interpreter resolution against `klayout-tools`' declared
  `requires-python` floor, so this script does not need to duplicate that
  logic.
- **No pinned OpenROAD Docker fallback.** Native `openroad` has been
  available on `$PATH` in every environment this script has been exercised
  in so far — see "`iverilog` / `yosys` / `openroad`" above.

## Why local, not CI, for the PDK-heavy legs

`.github/workflows/ci.yml` does not run `klt synthesize` or `klt
functional-verification` — provisioning `klt`, cocotb, and a PDK on every PR
in a hosted CI runner is a cost this repo has chosen not to pay per-PR
(confirmed in `ci.yml`'s own header comment). Instead:

- CI runs the tool-light legs only (RTL lint/format checks and the
  evidence-record linter — see `ci.yml` directly for the current list).
- `klt functional-verification` / `klt synthesize` / `klt drc` are run
  locally by a contributor with `scripts/setup-env.sh`'s environment
  provisioned, and the result is committed as an append-only record under
  `verification/records/` (see `verification/README.md`).
- The Tiny Tapeout LibreLane flow (`.github/workflows/gds.yaml`) is the one
  PDK-heavy flow that *does* run in CI — it provisions its own PDK and
  toolchain independently of this script (see "$PDK_ROOT for
  ihp-sg13cmos5l" above), consistent with `CLAUDE.md`'s "two flows, one
  record of truth" rule.

This split is stated explicitly, not left implicit — see
`verification/README.md`'s "The `klt functional-verification` cocotb
dependency" note, which this document is cross-referenced from.
