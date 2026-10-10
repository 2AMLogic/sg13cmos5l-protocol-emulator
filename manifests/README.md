# manifests/ — the block manifest that grades this block's T1 state

This directory holds this block's `klt signoff` **block manifest** (issue
#16) — the machine-readable declaration of the block's `kind` and, per T1
checklist item, the evidence envelope backing it. `klt signoff --manifest`
renders the eleven-item T1 evidence-tier checklist mechanically, with a
per-item `met`/`unmet` verdict and a `reason`, so this block's "gap to T1"
state is graded, not hand-read. This is one of the first two block manifests
in the canary fleet — `sg13g2-comparator`'s landed a few hours ahead
(`2AMLogic/sg13g2-comparator` PR #39, commit `681270b`, 2026-09-21T15:26Z,
its evidence map empty like this one's nearly is; the two repos independently
converged on the same `manifests/<block>.json`-at-repo-root convention and
the same cwd-relative evidence-path finding this README documents). The fleet
roll-up that consumes this file is `2AMLogic/2am`#956 — it grades every
block's tier in one query, consuming exactly this manifest and identifying
this block's row by its `block` field.

## Contents

| File | What it is |
|---|---|
| [`sg13cmos5l-protocol-emulator.json`](sg13cmos5l-protocol-emulator.json) | The block manifest itself. `block` (required — the fleet roll-up's row identity) and `kind` are the two declarations; `evidence` maps T1 item ids to their citations. |

There is no longer a vendored copy of the evidence-tiers checklist in this
directory — see "The vendored tiers doc" below for why it was retired.

## How the report is produced and where it lives

```bash
# Provisioning: klt at the exact pinned commit (scripts/setup-env.sh installs
# it; the pin lives in layout/toolchain.json's klt_install and is the single
# klt pin shared by the layout/ and verification/ flows):
./scripts/setup-env.sh

# Render + CI comparison, one entry point:
scripts/signoff-report.sh --check-latest
```

`scripts/signoff-report.sh` (run it from anywhere; it `cd`s to the repo root
itself — **evidence paths inside the manifest are cwd-relative**, which is
why the runner always invokes from the repo root) runs

```bash
klt signoff --manifest manifests/sg13cmos5l-protocol-emulator.json \
            --format json
```

and checks that the `klt` on `PATH` is at the pinned commit before grading.
Its output is committed as an append-only evidence record under
`verification/records/signoff-baseline/` — the **committed report is the
verdict of record** for this block's T1 state; the gap-to-T1 tracker (issue
#27) points at it and must not re-derive grades by hand. `--check-latest`
re-runs the grading and verifies the committed record still reproduces via
`klt signoff --check` (klayout-tools #2258) — the grader's own comparison,
which excludes the report's `build` block so the same pinned commit
verifies from any provisioning route (clean-tree or `.dirty`-stamped,
klayout-tools #2249). A `drifted` result means a graded field outside the
build block — an evidence artifact changed under a citation's pinned hash,
a manifest or tiers-doc edit, a per-item verdict, or a count — landed
without a fresh record, and it fails. CI (`.github/workflows/ci.yml`'s
`signoff` job) does this on every push and PR.

### Exit-code semantics — read this before scripting around `klt signoff`

`klt signoff --manifest` exits `0` only when every rendered T1 item is
`met` (tier `T1`); it exits `3` when it ran successfully but at least one
item is `unmet` — **the normal, correct gap state for this block today, not
an error**, exactly like the issue's "an all-unmet manifest is a correct
result". Exit `1`/`2` are real errors (unreadable manifest, unparseable
tier doc, bad `--format`, …). `scripts/signoff-report.sh` maps `0` and `3`
to success for this reason; gate tiers and per-item statuses, not exit
codes.

**`--check` mode overloads `3` with the opposite meaning.**
`klt signoff --manifest … --check REPORT` re-grades and verifies the
committed report still reproduces (excluding the `build` block): `0` is
`status: "match"`, `3` is `status: "drifted"` — a graded field outside the
build block moved, a hard failure — and `1` a missing/unparseable
committed report. So the render-mode `0|3 → success` mapping above must
never be reused for a `--check` invocation: `scripts/signoff-report.sh
--check-latest` maps `--check`'s `3` to exit `1` for exactly this reason
(the trap is called out in its header).

## What the manifest currently declares, and why every row is `unmet`

`kind` is declared `"digital"` (the block is a CPU implemented as RTL on a
CMOS5L standard-cell flow — no analog partition), so the Digital column of
T1 items 1, 2, 5, 7 and 11 applies: this repo is not held to schematic
capture, PVT corner sweeps, or Monte Carlo.

- **Item 7 cites the SDF-annotated post-route regression** (issue #26) —
  record `20260922-011856-87e8166`'s typ-corner
  `klt-functional-verification-nom_typ_1p20V_25C.json`
  (`verification/records/post-layout-sdf-regression/`): the committed cocotb
  bench re-run against the post-route gate-level netlist with
  `options.sdf` set, `environment.sdf.annotated: true` — exactly the
  machine-checkable shape the checklist's Digital column accepts for this
  item. The citation is fresh against the current top (the swept netlist is
  the `gds` workflow's own output at the manifest-edit commit's `src/`
  revision) and must be re-run when the top changes — issue #18's core
  integration is the next such change, and the record's provenance pin on
  `src/tt_um_2amlogic_protocol_emulator.v` is the tripwire
  (`verification/check_records.py` fails a stale record).
  - Under the pinned `klt` the citation renders
    `unmet`/`unverifiable_provenance`: the post-layout gate passes (the
    envelope is SDF-annotated — no longer the zero-delay
    `not_post_layout` this item rendered before issue #26), and the
    remaining unmet is the grader-side provenance binding — this repo
    pins the cited file's sha256 (every citation does, see below), while
    `functional-verification` envelopes carry no internal
    `provenance.input.content_hash` for the grader to compare against
    (klayout-tools #2182; the binding itself is #2097, open). Unmet
    everywhere, never silently met; the pin is enforced at the record
    layer instead.
- **Item 9 still cites the zero-delay `reset-pin-through` envelope**
  (`verification/records/reset-pin-through/artifacts/20260914-031931-7e4a21a/klt-functional-verification.json`,
  unchanged by issue #26): the cited run's testbench
  (`verification/test_protocol_emulator.py`) is committed with a
  documented cold-start invocation — the harness half of item 9; the
  protocol-specific firmware benches (#22/#23) and formal properties
  (#24) are the unmet remainder. It renders
  `unmet`/`unverifiable_provenance` at the pinned `klt` for the same
  provenance-binding reason as item 7 (below).
- **Items 3 and 4 (layout evidence), state as of 2026-10-09 (issue #82)** —
  append-only; earlier states are in the superseded records. Both citations
  now point at record `20261009-054750-676f8b2`
  (`verification/records/librelane-gds-signoff-check/`), run at klt pin
  `6457a605d73e`. **Item 3 (DRC clean) is `met`** (`status: clean`, 0
  violations, same GDS `sha256:9a5eb00e…`; deck hash moved to
  `sha256:db9f44fa…`, coverage unchanged). **Item 4 (LVS clean) is still
  `unmet`/`check_errored`**: klayout-tools #2656 and #2657 are fixed (45
  top-level pins now promoted; the vector-macro connections convert), but
  the cited klt/Yosys reference now stops at three further `write_verilog`
  shapes the converter rejects (an `assign` part-select, a sized-constant
  bus `assign`, and `1'h0`/`1'h1`), filed as klayout-tools#2941. For
  information, not cited: the same run's compare against the LibreLane
  post-route reference is `status: match` with `power_connectivity.status:
  match` (`klt-lvs-asrouted.json`); whether item 4 should be defined against
  that reference rather than the pre-place-and-route klt/Yosys netlist is an
  open question for the issue owner, not decided by this note.
- **Items 3, 4 and 7, state as of 2026-10-10 (issue #158).** Append-only;
  the bullet above is the earlier state. All three citations now describe
  the layout the LibreLane flow builds for the design with the control space
  (DR 0012) and the boot ROM (DR 0013). Items 3 and 4 cite record
  `20261010-020408-5a5cddc` (`librelane-gds-signoff-check/`, the GDS of gds
  run 38014090810, `sha256:ca28f860…`). Item 7 cites
  `post-layout-sdf-regression` record `20261009-220911-1dc1842`, whose routed
  netlist is byte-identical to that run's. **Item 3 stays `met`.** **Item 4
  stays `unmet`/`check_errored`**: the converter now stops at a different
  Yosys shape (an `assign` with a concatenation on the left given a sized
  constant), added to klayout-tools#2941. The compare against the post-route
  reference is again `match` with `power_connectivity` `match`, and is again
  not cited; the open question above stands. **Item 7 stays
  `unmet`/`check_failed`** (#106). Baseline: `signoff-baseline` record
  `20261010-020408-5a5cddc`, 1 of 11.
- **Items 3, 4 and 7, state as of 2026-10-10 (issue #140, PR #188).**
  Append-only; the bullet above is the earlier state. The SPI-flash boot
  program changed the boot ROM, so the layout changed. Items 3 and 4 cite
  record `20261010-041033-fb86d71` (`librelane-gds-signoff-check/`, the GDS
  of gds run 38018615820, `sha256:60e37b52…`). Item 7 cites
  `post-layout-sdf-regression` record `20261010-020805-ed5f2d1`, whose routed
  netlist is byte-identical to that run's. **Item 3 stays `met`.** **Item 4
  stays `unmet`/`check_errored`**: the converter now stops at a multi-bit
  range slice in an instance port connection (`pm_wdata[7:0]`), the same
  grammar gap as klayout-tools#2941. The compare against the post-route
  reference is `match` with `power_connectivity` `match`, and is not cited.
  **Item 7 stays `unmet`/`check_failed`** (#106). Baseline:
  `signoff-baseline` record `20261010-044125-89cd241`, 1 of 11.
- **Items 3, 4 and 7, state as of 2026-10-10 (issue #173).** Append-only;
  the bullet above is the earlier state. A LibreLane-only drive buffer on the
  SRAM macro's `A_REN` input changed the layout. Items 3 and 4 cite record
  `20261010-070156-c914bbc` (`librelane-gds-signoff-check/`, the GDS of gds
  run 38032061275, `sha256:5de2d0ad…`). Item 7 cites
  `post-layout-sdf-regression` record `20261010-072000-c914bbc`, whose routed
  netlist is byte-identical to that run's. **Item 3 stays `met`.** **Item 4
  stays `unmet`/`check_errored`** on the same converter shape
  (`pm_wdata[7:0]`, klayout-tools#2941). The compare against the post-route
  reference is `match` with `power_connectivity` `match`, and is not cited.
  **Item 7 stays `unmet`/`check_failed`** (#106). Baseline:
  `signoff-baseline` record `20261010-080000-c914bbc`, 1 of 11.
- **Items 3, 4 and 7, state as of 2026-10-10 (issue #168).** Append-only;
  the bullet above is the earlier state. The warm start's zero-signature
  refusal (two boot-ROM words) changed the layout. Items 3 and 4 cite record
  `20261010-083721-704a3fb` (`librelane-gds-signoff-check/`, the GDS of gds
  run 38037477407, `sha256:c59b4c7a…`). Item 7 cites
  `post-layout-sdf-regression` record `20261010-083555-704a3fb`, whose routed
  netlist is byte-identical to that run's. **Item 3 stays `met`.** **Item 4
  stays `unmet`/`check_errored`** on the same converter shape
  (`pm_wdata[7:0]`, klayout-tools#2941). The compare against the post-route
  reference is `match` with `power_connectivity` `match`, and is not cited.
  **Item 7 stays `unmet`/`check_failed`** (#106). Baseline:
  `signoff-baseline` record `20261010-090628-704a3fb`, 1 of 11.
- **Every citation pins a `content_hash`** — the sha256 of the cited
  artifact file, verifiable with `sha256sum`. Two honest caveats, on
  record here because the issue calls freshness "the point":
  `klt functional-verification` envelopes carry no `provenance` block (by
  design) — there is no recorded
  *input* hash to pin freshness against, so the pin names the exact file
  bytes instead, and any grader that tries to compare a pin against the
  envelope's own recorded input hash finds none and renders the item
  `unmet` (`unverifiable_provenance` on current `main`) — again unmet
  everywhere, never silently met. The append-only
  `verification/check_records.py` freshness check independently pins the
  same file's hash on the evidence record citing it, so a changed
  artifact is caught at the record layer too.
- **Every other item is uncited** (`no_evidence`) — the truthful per-item
  states are tracked in the gap-to-T1 tracker (issue #27) and its linked
  issues: no RTL yet for the ISA core (#18/#19), no layout/DRC/LVS at all
  (items 2–4, none filed yet — downstream of item 1), no timing evidence
  (#20) and an unratified spec (#17) behind item 5, no characterization
  numbers (#21) for item 8, and no power grid (item 11 — `klayout-tools`
  #2025's new power-delivery item; nothing to cite yet, no layout exists).
  Do not cite an envelope that does not actually support an item just to
  change a reason string — the tracker's linked issues are the
  per-item "why", the manifest's rendered reasons are the mechanical
  statement.
- **Item 5 stays uncited even though timing evidence now exists (2026-10-02,
  issue #20)** — this is a deliberate decision, recorded here so a later
  reader does not mistake it for an oversight. The LibreLane flow has now
  produced a real multi-corner setup/hold result for the macro-backed core
  (record
  `verification/records/librelane-corner-timing/records/20261002-095445-21a2a63.md`:
  3 corners, 0 setup and 0 hold violations at the 20 ns / 50 MHz
  constraint), so the bullet above is stale in saying there is "no timing
  evidence" behind item 5. **It is still not a citation this manifest may
  carry**, for three independent reasons, any one of which is sufficient:
  (1) **it is the wrong flow's artifact.** The cited file would be a
  LibreLane `final-metrics.json`, not a `klt sta` report — it carries no
  `klt` provenance block, no `timing_status`, and no per-corner
  schema the grader reads. Feeding it to `klt signoff` as this item's
  evidence would be substituting a LibreLane number for a klt one inside
  the klt grader, which is exactly what `CLAUDE.md` § "Two flows, one record
  of truth" forbids — and it is the "cite an envelope that does not actually
  support an item just to change a reason string" move the bullet above
  already rules out. (2) **The item cannot render `met` regardless**: its own
  checklist note reads "Both require the spec table itself to be ratified —
  verdicts against a draft spec are provisional by construction", and
  `spec/target-spec.md` is `PROPOSED — not ratified` (DR 0006, issues
  #44/#45). (3) **Coverage is partial anyway** — 3 of the 6 corners row 4
  declares, the other 3 structurally unreachable for this design (issue
  #69). So item 5 correctly remains `unmet`/`no_evidence`, the manifest is
  unchanged by that work, and no re-render was needed: `klt signoff --check`
  grades the manifest and the files it cites, and issue #20's change touches
  neither. The evidence lives in `verification/records/` and is cited from
  `spec/gap-to-submission.md` row 4, which is where a claim about row 4
  belongs; when `2AMLogic/klayout-tools#2635` closes and the klt leg can
  produce a `klt sta` report for the macro-backed core, *that* report is the
  citation this item has been waiting for.
- **Item 6 is uncited by explicit statement, not omission**: this block's
  spec table (`spec/target-spec.md`) has **no statistical row** — every
  row is a deterministic protocol-timing, area, or pin-budget bound — so
  the checklist's own text ("a block whose spec has no statistical row
  must say so explicitly rather than omitting the item") is satisfied by
  this paragraph (and tracker issue #27's item-6 row), not by a citation.

## The vendored tiers doc — provenance and refresh rule

`manifests/design-evidence-tiers.md` is a **verbatim vendored copy** of
[`2AMLogic/klayout-tools`](https://github.com/2AMLogic/klayout-tools)'s
`docs/design-evidence-tiers.md` at commit
[`428951e03693`](https://github.com/2AMLogic/klayout-tools/commit/428951e03693)
(the commit that added T1 item 11, power delivery —
`klayout-tools`#2025's implementation landing #2057), fetched 2026-09-21.
File sha256: `275964ed6cdc3ed57566710540daa76beb26c1b67fb4b3dbf598d05b640a7ce0`.

Why vendored: the `klt` pin recorded in `layout/toolchain.json`
(`5c75708`, 2026-09-14) predates that checklist's eleventh item, and its
bundled copy of the tiers doc lists only ten T1 items — grading against it
would render no item-11 row at all, which the issue's acceptance criteria
require ("Item 11 has a row, even if `unmet`"). `--tiers-doc` is the graded
command's documented mechanism for pointing the mechanical parse at a
different copy of the checklist, so the pinned build can render all eleven
rows; an uncited item renders `unmet`/`no_evidence` in any grader, so the
pinned build's lack of item-11 *grading rules* never produces a wrong
verdict — item 11 has nothing to cite yet either way (this is a
pre-#2176 `klt`: it has no `graded_by_build` marking; a newer build would
mark it instead).

**Never hand-edit this file.** It is tool data: `klt signoff --manifest`
parses it mechanically (`klayout_tools/design_evidence_tiers.py`). Refresh
only by re-vendoring a verbatim upstream copy at a newer pinned commit,
recording the new commit here, in the same sentence style; a checklist
refresh changes the rendered report and therefore requires a fresh
append-only signoff record in the same PR (see "How the report is
produced" above), and a `klt` pin bump that brings the tool's own bundled
doc to eleven or more items may retire the vendored copy — do that
retirement in its own change, with the commit that makes it true recorded
here (append-only: never rewrite this paragraph, only add new ones).

**Retired (issue #52).** `manifests/design-evidence-tiers.md` is deleted as
of this paragraph's commit and `scripts/signoff-report.sh` no longer passes
`--tiers-doc`. The retirement trigger this section wrote above is satisfied:
`layout/toolchain.json`'s pin has moved twice since the vendoring decision
(`5c75708` → `1d964cf4ed93` under issue #20 → `c622e8addb36` / v0.6.0 under
issue #49), and the tiers doc bundled with the current pin has carried all
eleven T1 items since before `1d964cf4ed93`. `klt signoff` now resolves the
checklist from its own packaged/source copy
(`design_evidence_tiers.default_doc_path()`'s precedence order —
`$KLT_TIERS_DOC`, then the wheel-packaged `klayout_tools/data/` copy, then
the source checkout's `docs/design-evidence-tiers.md`), with no repo-local
override. Re-rendering at the current pin without `--tiers-doc` changed
exactly three things versus the prior committed report, none of them a
graded verdict: the `source_doc`/`source_doc_content_hash` fields (now
naming the pin's own copy instead of the vendored file) and item 11's
`notes[0]` prose (grew with upstream caveat/known-gap paragraphs added to
the checklist between the vendored copy's commit and the current pin) —
every item's `status`/`reason`/`citations`, `t1_item_count` (11), and
`t1_met_count` (0) are byte-identical to the prior record. The fresh
append-only signoff-baseline record this change requires is
`verification/records/signoff-baseline/records/20260927-112359-2baa6f0b.md`,
superseding `20260927-092721-91f489d4` (not the older
`20260922-012257-3dbfdc5` this retirement was originally proposed against —
that record had already been superseded by `20260927-092721-91f489d4` under
issue #49's klt pin bump by the time this retirement landed, and that
record still cited the vendored file by content hash, so it is the one this
retirement's supersession chain must extend).

## Companion links

- Fleet roll-up design (consumes this file): `2AMLogic/2am`#956.
- Checklist and grader contract:
  `klayout-tools`'s `docs/design-evidence-tiers.md` (vendored here, see
  above) and `docs/cli/signoff.md`.
- Gap-to-T1 tracker (issue #27) — the living checklist that points at
  this manifest's committed report as the verdict of record.
- Toolchain pin: `layout/toolchain.json` (`klt_install`,
  `klt_last_verified_commit`); provisioning: `scripts/setup-env.sh`;
  environment record: `docs/environment.md`.
