# manifests/ — the block manifest that grades this block's T1 state

This directory holds this block's `klt signoff` **block manifest** (issue
#16) — the machine-readable declaration of the block's `kind` and, per T1
checklist item, the evidence envelope backing it. `klt signoff --manifest`
renders the eleven-item T1 evidence-tier checklist mechanically, with a
per-item `met`/`unmet` verdict and a `reason`, so this block's "gap to T1"
state is graded, not hand-read. This is the first block manifest in the
canary fleet (see `2AMLogic/2am`#956, the fleet roll-up that consumes this
file to grade every block's tier in one query — the fleet roll-up consumes
exactly this manifest, and identifies this block's row by its `block` field).

## Contents

| File | What it is |
|---|---|
| [`sg13cmos5l-protocol-emulator.json`](sg13cmos5l-protocol-emulator.json) | The block manifest itself. `block` (required — the fleet roll-up's row identity) and `kind` are the two declarations; `evidence` maps T1 item ids to their citations. |
| [`design-evidence-tiers.md`](design-evidence-tiers.md) | The vendored `klayout-tools` evidence-tiers checklist `klt signoff` grades against (see "The vendored tiers doc" below for its provenance and the rule for refreshing it). |

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
            --format json \
            --tiers-doc manifests/design-evidence-tiers.md
```

and checks that the `klt` on `PATH` is at the pinned commit before grading.
Its output is committed as an append-only evidence record under
`verification/records/signoff-baseline/` — the **committed report is the
verdict of record** for this block's T1 state; the gap-to-T1 tracker (issue
#27) points at it and must not re-derive grades by hand. `--check-latest`
re-runs the grading and byte-compares the fresh report against the latest
committed record's artifact — a mismatch means either an evidence artifact
changed under a citation's pinned hash or a manifest edit landed without a
fresh record, and it fails. CI (`.github/workflows/ci.yml`'s `signoff` job)
does this on every push and PR.

### Exit-code semantics — read this before scripting around `klt signoff`

`klt signoff --manifest` exits `0` only when every rendered T1 item is
`met` (tier `T1`); it exits `3` when it ran successfully but at least one
item is `unmet` — **the normal, correct gap state for this block today, not
an error**, exactly like the issue's "an all-unmet manifest is a correct
result". Exit `1`/`2` are real errors (unreadable manifest, unparseable
tier doc, bad `--format`, …). `scripts/signoff-report.sh` maps `0` and `3`
to success for this reason; gate tiers and per-item statuses, not exit
codes.

## What the manifest currently declares, and why every row is `unmet`

`kind` is declared `"digital"` (the block is a CPU implemented as RTL on a
CMOS5L standard-cell flow — no analog partition), so the Digital column of
T1 items 1, 2, 5, 7 and 11 applies: this repo is not held to schematic
capture, PVT corner sweeps, or Monte Carlo.

- **Items 7 and 9 cite the one committed `klt` evidence envelope this repo
  has** — record `20260914-031931-7e4a21a`'s
  `klt-functional-verification.json` (`verification/records/reset-pin-through/`),
  the harness-bootstrap stub's passing zero-delay Icarus/cocotb run:
  - item 7 (post-layout verification): the cited run is zero-delay
    (`environment.sdf` is `null`), so it does **not** satisfy the item —
    SDF-annotated re-verification is issue #26. Citing it states the
    honest gap: the best post-layout-adjacent evidence on record is a
    run the checklist's own text excludes.
  - item 9 (testbenches shipped): the cited run's testbench
    (`verification/test_protocol_emulator.py`) is committed with a
    documented cold-start invocation — the harness half of item 9; the
    protocol-specific firmware benches (#22/#23) and formal properties
    (#24) are the unmet remainder.
  - Under the pinned `klt` both citations render
    `unmet`/`unrecognized_envelope`: `klt signoff` at that commit does not
    yet classify `functional-verification` envelopes (that recognition is
    `2AMLogic/klayout-tools` #1959/#1967, newer than the pin). The verdict
    is `unmet` under every grader version — pinned-build, current release,
    or current `main` — never a false green, which is why shading a
    reason that varies by grader (`unrecognized_envelope` →
    `not_post_layout`/`unverifiable_provenance`) is safe.
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
