# 0026: Adopt the 8×4 Submission Allocation the Competition Rules Set

Status: **Ratified** — by the two `RATIFY-KEY` reviews (one EE key, one
market key, neither held by the carrying PR's author or the design's
author) on pull request #NNN (issue #464). That PR's merge commit is the
ratification record, the same act shape [`0009`](0009-two-key-ratification-act.md)
records for DRs 0001–0004. This file was written before either review: it
names no review URLs and no merge hash, because the reviews are posted on
the PR that carries it and those facts are read from the forge (DR 0009
§ "The act"). The `two-key gate (spec Status flips)` check on the carrying
PR holds it red until both keys release, which is the mechanism, not a
defect. A new file born `Ratified` is a flip the gate documents
([`docs/ratification-gate.md`](../../docs/ratification-gate.md) § "What
counts as a flip").
Date: 2026-11-19
Issues: #464 (this decision); the operator ruling on #273 (2026-11-19);
supersedes row 7's Target as [`0004`](0004-target-spec-ratification.md)
registers it and pull request #242 ratified it; revisits
[`0014`](0014-area-beyond-2x2.md)'s recommendation.

## Context

Row 7's binding Target has been "≤ 2×2 Tiny Tapeout tiles" since DR 0004's
register (2026-09-21), ratified by the two-key act on PR #242 (DR 0009).
Everything area-related this repo has measured since — the flip-flop
non-fit, the SRAM-macro path, the 2×2 placed figures — was measured against
that target. DR 0014 (Proposed 2026-10-09) recommended keeping 2×2 and
committed nothing past 6×4 "before the 8×4 template lands"; its own source,
the organizers' 2026-10-09 entrant update, then said "Design to 6x4 until
the 8x4 template is out."

That condition is now settled, in the rules themselves. The
[competition post](https://blog.janestreet.com/protocol-emulator-asic-competition/),
read 2026-11-19, carries an "Update November 9th" that says, under
**The rules → Process**:

> Set the tile size in `info.yaml` to 8x4.

and under **The rules → Area**:

> The maximum area is 8x4 tiles per design. This is confirmed for the
> March 2027 shuttle, and Tiny Tapeout says the tile sizes are final.

The earlier 6×4 wording is gone. The same Process rule states the template's
main branch now targets CMOS5L, so the `cmos5l` branch this repo's workflow
pins descend from is no longer needed. The operator ruling on #273
(2026-11-19, attended `/fleet:decide` round 20261119-r17) directs: set the
tile size according to the contest rules — the target is `tiles: "8x4"` —
through a new decision record on the two-key path; the ruling itself does
not ratify this record.

## The decision

1. **Row 7's binding Target is superseded: the design is submitted at the
   8×4 allocation.** `info.yaml` declares `tiles: "8x4"` in the same PR as
   this record, so the file never disagrees with the spec it is bound to.
   The allocation's geometry, per this repo's dated vendored reference
   (`flow/tt-cmos5l-reference.json`, from `tt-support-tools`
   `tech/ihp-sg13cmos5l/tile_sizes.yaml`): die **1724.16 × 710.64 µm**
   (1,225,257 µm²). Row 7's Target cell keeps its ratified words ("≤ 2×2
   Tiny Tapeout tiles (draft)") as written — ratified history is not
   rewritten — and carries a dated note naming this record as the
   supersession, exactly as the spec's own header text was preserved
   verbatim under a superseding act (DR 0009). The row's Stretch cell
   ("Competition maximum: 6×4 tiles today; 8×4 is possible, not confirmed")
   is superseded the same way: the Area rule now confirms 8×4 for the
   March 2027 shuttle.

2. **The submission wiring moves to the template's main-branch flow.** At
   upstream `TinyTapeout/ttihp-verilog-template` `4b1204ab` (main branch
   head, verified 2026-11-19), the template lists 8x4 among the valid
   `tiles` values and pins every workflow in the family to
   `TinyTapeout/tt-gds-action@ttihp27a`. That tag is annotated; its commit —
   resolved with `git ls-remote … 'refs/tags/ttihp27a^{}'` and verified to
   carry the `pdk: ihp-sg13cmos5l` input and the `precheck` / `gl_test` /
   `viewer` / `docs` / `fpga/ice40up5k` subactions — is
   **`e7a50f8f46f9f8df4b2c9935bfeb1cbc6b6ae4f6`**, which is what all six
   family references in `.github/workflows/{gds,docs,fpga}.yaml` now pin
   (`scripts/check_action_pins.py` enforces the single immutable SHA, as
   before). The repo's own deviations from the template survive the move:
   the CMOS5L PDK selection (`pdk: ihp-sg13cmos5l`) and the
   repository-owned gate-level results validation in the `gl_test` job
   (`scripts/check_test_results.py`, docs/submission/README.md R2(b)),
   which stays the authoritative verdict over the action's own grep.

3. **Allocation is not measured fit, and no measured claim moves.** Every
   committed placed figure remains a 2×2-die figure (die 419.52 × 313.74
   µm, 131,620 µm²; the newest at 44.51 % core utilization, LibreLane
   flow, per row 7's 2026-10-10 note); no 8×4 placed number exists at the
   date of this record, so row 7 stays **unmet** and the gap tracker's
   digest keeps its unmet reading. The fixed macro placement in
   `src/config.json` (die coordinates (91.2, 173.88), site multiples) and
   the PDN bridge lattice in `src/pdn_cfg.tcl` are die-size-independent in
   the sense that matters here — the 2×2 core box lies inside the 8×4 core
   box, so the placement stays legal — and the 8×4 build itself is the
   check (`src/config.json`'s own banner asks that deviations be proven,
   not assumed). The first 8×4 `gds` run on the carrying PR is recorded
   there. The dependent campaign — superseding the geometry-bound records
   (die-area, corner-timing, the signoff items pinned to the 2×2 GDS) with
   8×4 runs — is follow-up work this record admits and does not perform.

## What this record does not decide

- **No use of the extra area.** DR 0014's question — what area beyond 2×2
  buys, and whether to spend it — stays open and separate, as the operator
  ruling keeps it. Nothing here adds logic, SRAM, or a second engine; the
  RTL is untouched.
- **No relaxation of any other row.** Rows other than 7's Target are
  untouched, and no row's met/unmet reading changes: allocation and
  measured fit are kept distinct on purpose.
- **No organizer contact.** The rules as served 2026-11-19 answer the
  question; the FAQ's silence on smaller allocations is not this record's
  problem to solve.

## Ratification

This record binds only through the two-key act on its carrying PR, per
[`spec/README.md`](../README.md) § "How ratification works here" and
DR 0004 § "The binding process": one `RATIFY-KEY: ee` review with a
releasing verdict and one `RATIFY-KEY: market` review with a releasing
verdict, from distinct reviewers, neither attributable to the PR's author.
The operator ruling on #273 settles the allocation choice the keys are
asked to release — the keys execute the act, they are not asked to re-litigate
the organizers' rules. Until the act completes, this PR stays unmerged and
nothing in it binds; if it is closed unmerged, row 7's target stands as
PR #242 ratified it and `info.yaml` stays `"2x2"`.
