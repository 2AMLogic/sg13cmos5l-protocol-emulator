# verification/ — evidence record format

**This file is the authoritative convention.** The scripts under
`verification/` (`check_records.py`) implement it; if a script and this
document ever disagree, this document wins and the script is the thing that
gets fixed. Ported, near-verbatim, from `2AMLogic/sky130-modexp`'s
`verification/README.md` per `CLAUDE.md`'s "Harness bootstrap" section
(issue #2) — that repo is this program's first digital canary and the
sibling this convention is copied from.

This directory holds this program's own cocotb testbench (distinct from the
Tiny Tapeout template's own `test/` harness — see "Two harnesses, one
design" below) and the results it produces. Results are **append-only
evidence**: once a record is written, it is never edited or deleted. A
re-run — even one that corrects a mistake — mints a new record with a new
ID; a correction references the prior record it supersedes rather than
overwriting it.

This convention exists because `CLAUDE.md` commits this repo to rules that
need a concrete schema to be checkable rather than aspirational:

- **Verification is the product.** No claim without a testbench.
- **`verification/` is append-only evidence.** Re-runs get new records;
  records are never edited or deleted.
- **Two flows, one record of truth.** Never report a synthesis or timing
  number without naming which flow (`klt`/Yosys/OpenROAD vs. the Tiny
  Tapeout LibreLane CI flow) produced it, and never let the two disagree
  silently.

## Two harnesses, one design

This repo carries **two** cocotb harnesses against the same RTL, and that is
deliberate, not duplication:

- **`test/`** — the Tiny Tapeout template's own harness, taken verbatim from
  `TinyTapeout/ttihp-verilog-template@cmos5l` (issue #2). Driven by the
  template's `gds`/`test` GitHub Actions workflows; its job is CI sign-off
  against the template's own toolchain (LibreLane, `tt-gds-action`).
- **`verification/`** (this directory) — this program's own bench, driven by
  `klt functional-verification` and feeding the append-only `records/`
  convention below. Its job is the evidence trail `CLAUDE.md` requires,
  independent of whether the Tiny Tapeout CI pipeline is green.

Both harnesses check the same behavior against the same
`src/tt_um_2amlogic_protocol_emulator.v` source (no second copy under
`rtl/`; see `rtl/README.md`) — a divergence between what `test/test.py` and
`verification/test_protocol_emulator.py` each assert about the DUT would
itself be a two-flows disagreement worth noticing, not just redundant
coverage.

## Contents

- `test_protocol_emulator.py` — this program's own cocotb testbench for
  `src/tt_um_2amlogic_protocol_emulator.v` (the harness-bootstrap stub top,
  issue #2). Driven by `klt functional-verification` (see
  `request-protocol-emulator.json`).
- `test_program_memory.py` — cocotb testbench for
  `rtl/protocol_program_memory.v`, the program memory and serial
  load-phase logic (target-spec row 6, issue #19): loads known programs
  serially and reads them back through the module's fetch port, pinning
  the load protocol's DR 0001 contracts (MSB-first shift, commit-on-16th-
  bit-edge, mid-word discard, no mid-run re-entry, 256-word saturation).
  Driven by `klt functional-verification` (see
  `request-program-memory.json`).
- `_dut.py` — shared `reset(dut)` coroutine, imported as a sibling module by
  `test_protocol_emulator.py` (and any future bench added here) so reset
  sequencing lives in one place.
- `request-protocol-emulator.json` — `klt functional-verification` request
  driving `test_protocol_emulator.py` against
  `src/tt_um_2amlogic_protocol_emulator.v` via Icarus.
- `request-program-memory.json` — `klt functional-verification` request
  driving `test_program_memory.py` against
  `rtl/protocol_program_memory.v` via Icarus.
- `test_firmware_roundtrip.py` — cocotb round-trip bench for the DR 0003
  firmware toolchain (issue #22): re-assembles the committed
  `firmware/asm/demo_roundtrip.asm` and checks the committed
  `firmware/build/` artifacts match byte-for-byte, serially loads the
  committed image through `protocol_program_memory`'s DR 0001 load phase,
  reads every word back through the fetch port (the assembler's encoding
  and the RTL agreeing), and cross-checks the committed cycle-accounting
  report against cycle arithmetic decoded independently from the image
  words. Driven by `klt functional-verification` (see
  `request-firmware-roundtrip.json`).
- `request-firmware-roundtrip.json` — `klt functional-verification`
  request driving `test_firmware_roundtrip.py` against
  `rtl/protocol_program_memory.v` via Icarus.
- `check_records.py` — the evidence-record linter (see "Enforcement").
- `test_check_records.py` — the linter's own self-test: one executable
  negative case per violation class named below, run against a throwaway
  fixture repo.
- `_repo_utils.py` — shared `REPO_ROOT`/`run_git`/`sha256_of` helpers used by
  `check_records.py`.
- `records/` — the append-only evidence records this convention produces.

Run the klt-driven bench with:

```bash
klt functional-verification verification/request-protocol-emulator.json --format json
```

See `flow/README.md` for the synthesis-baseline leg (Yosys against
`sg13cmos5l_stdcell`, and the `klt synthesize` liberty-naming gap that leg
currently has to work around).

## The `klt functional-verification` cocotb dependency (a local-environment note)

`klt functional-verification` needs `cocotb`/`cocotb-tools` importable from
`klt`'s own Python environment, not just the ambient `python3`. If `klt` is
installed as an isolated tool (e.g. `uv tool install klayout-tools`), that
isolated venv does not automatically pick up an ambient `cocotb` install --
running the command above then fails with `cocotb is not installed`, even
when `python3 -c "import cocotb"` works fine outside of `klt`.

**Fix: run `./scripts/setup-env.sh`.** It installs `klt` together with
pinned `cocotb`/`cocotb-tools` versions in one `uv tool install` call, at
the exact `klt` commit `layout/toolchain.json` records (so this flow and
the `layout/` DRC/LVS flow never drift onto different `klt` pins), and also
reports the resolved `ihp-sg13cmos5l` `$PDK_ROOT` and whether
`iverilog`/`yosys`/`openroad` are on `$PATH`. See `docs/environment.md` for
the full pinned-version record and rationale. (This replaces the ad hoc
`uv tool install --with cocotb --with cocotb-tools klayout-tools` workaround
this note previously described.)

## Directory / naming convention

Each distinct claim being verified gets its own experiment directory under
`verification/records/`:

```
verification/records/
  <experiment-slug>/                 # e.g. reset-pin-through, synthesis-baseline
    records/
      <record-id>.md                 # append-only summary record
    artifacts/
      <record-id>/                   # frozen inputs/outputs for this run
        ...                          # e.g. the raw klt JSON envelope, a
                                      # netlist snapshot, a JUnit report
```

- **`<experiment-slug>`** — short, descriptive, kebab-case name for the
  claim being verified (`reset-pin-through`, `synthesis-baseline`, and
  future entries such as `gate-level-sim`, `drc-lvs`, once those legs
  exist). One directory per distinct claim, not per run.
- **`<record-id>`** — unique and traceable:
  `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` (e.g. `20260914-031931-7e4a21a`).
  Re-runs mint a new `<record-id>`; nothing under `records/` or `artifacts/`
  is ever edited in place. `<short-git-sha>` is the design's git revision at
  the time the record was minted (necessarily the parent commit, since the
  commit that adds the record cannot cite its own hash).

## Record format

Each record is a markdown file, `records/<record-id>.md`, with two parts:

1. A machine-readable `<!-- record-meta ... -->` HTML-comment block
   containing JSON (invisible in a rendered preview, trivially parseable
   with the stdlib `json` module — no YAML dependency). Required keys:

   - `record_id` — must equal the filename stem.
   - `experiment` — the experiment-slug this record belongs to.
   - `supersedes` — `null`, or the `record_id` of a prior record in the
     same experiment directory this one corrects/replaces.
   - `git_revision` — the full design git revision this record was
     produced against.
   - `provenance` — the klt provenance block:
     - `klt_version`
     - `pdk.name` / `pdk.version` — the resolved PDK name/version, or
       `"n/a"` when the run has no PDK dependency (e.g. an Icarus-only
       cocotb run, which never touches a standard-cell library).
     - `deck.content_hash` — the liberty/PDK deck's content hash, or
       `"n/a"` when not applicable.
     - `inputs` — a non-empty list of `{"path": ..., "content_hash": ...}`
       for every source file this record's claim depends on (at minimum,
       the RTL under test). Hashes use klt's own `"sha256:<hex>"` format.

2. Human-readable prose bullets, each a **required field**:

   - **Record ID** — matches the metadata block and the filename.
   - **Claim** — which spec/doc line this record substantiates.
   - **Design provenance** — `rtl` (`src/<file>.v` @ `<git-sha>`) today;
     once post-synthesis/post-P&R records exist, `netlist` (post-synthesis)
     or `layout` (post-P&R, extracted) analogous to `sky130-modexp`'s
     convention.
   - **Run configuration** — the exact tool invocation and settings.
   - **Statistical convention** — sample size / seed for a randomized claim,
     or `N/A` for a single deterministic run.
   - **Result** — the measured outcome(s) and an overall pass/fail against
     the claim.
   - **klt provenance** — human-readable echo of the metadata block's
     `provenance`, including the informational case where klt did not drive
     the run (see the synthesis-baseline record's own "klt provenance"
     bullet for a worked example of that case).
   - **Links** — paths to the driver/testbench script(s), the design under
     test, and the raw artifacts under `artifacts/<record-id>/`.
   - **Timestamp / author** — ISO-8601 UTC timestamp and who (human or
     agent) minted the record.
   - **Supersedes** — `none`, or the prior `<record-id>` this corrects.

## Append-only rule

`records/*.md` and `artifacts/**` are never edited or deleted after
creation. A re-run or correction always mints a new record with a new
`<record-id>`; a correction references the record it supersedes via the
**Supersedes** field rather than overwriting it in place.

## Enforcement

This convention is checked, not merely documented.
`verification/check_records.py` runs as `npm run lint` (see `package.json`).
It needs nothing but Python 3 and `git`, reads tracked files only, and fails
on:

- a record missing a required field (metadata key or prose bullet), or with
  a placeholder/empty value;
- a filename or metadata `record_id` that is not a well-formed
  `<record-id>`, or the two disagreeing;
- a `supersedes` value naming a record that does not exist in the same
  experiment directory;
- a live record whose `provenance.inputs[].content_hash` no longer matches
  the current working tree;
- **append-only violations**: any file under `verification/records/`
  modified, renamed, or deleted relative to the merge base with
  `origin/main`.

`verification/test_check_records.py` (also run by `npm run lint`) holds one
executable negative case per bullet above. Run it directly with
`python3 verification/test_check_records.py`.

If the checker and this document ever disagree, this document wins and the
checker is the thing that gets fixed.

## Worked example

The two records backfilled when this convention was introduced (issue #2)
illustrate the format:

- `verification/records/reset-pin-through/records/<record-id>.md` —
  the stub top's reset and registered pin-through behavior, driven by `klt
  functional-verification` against `src/tt_um_2amlogic_protocol_emulator.v`.
- `verification/records/synthesis-baseline/records/<record-id>.md` — the
  Yosys-against-`sg13cmos5l_stdcell` half of the two-flows cell-count claim,
  including the `klt synthesize` liberty-naming gap that record had to work
  around, and the explicit note that the LibreLane half is not yet captured.
