# spec

Proposed specification and decision records.

> **2026-09-26: nothing in this directory is ratified.** The two-key
> (`RATIFY-KEY`) mechanism described below has never run — not on any PR in
> this repository's history — so the 2026-09-21 `Ratified`/`RATIFIED` claims
> were assertions rather than acts, and every one of them has been reconciled
> to `Proposed`. The finding of fact, the per-file reconciliation table, and
> what is required to actually close this out are in
> [`decision-records/0006-two-key-ratification-never-ran.md`](decision-records/0006-two-key-ratification-never-ran.md).
> **No spec content changed** — only the claim that it binds. The missing
> enforcement hook that allowed the gap was issue #45, and it now exists:
> see "How ratification works here" below and
> [`docs/ratification-gate.md`](../docs/ratification-gate.md).

- `target-spec.md` — the checkable target table (Status: **PROPOSED — not
  ratified**; each row's proposed binding and its met/unmet evidence state
  are in the table's State column, registered per row in
  `decision-records/0004-target-spec-ratification.md`).
- `decision-records/` — numbered decision records (0001-isa.md and up),
  including `0004-target-spec-ratification.md` — the per-row register and
  *proposed* binding record of 2026-09-21, whose own invalidation clause
  fired, and `0006-two-key-ratification-never-ran.md`, which records that it
  did.
- `decision-records/0010-protocol-pin-roles.md` — **Proposed** (not
  ratified) pin-role table for `ui_in` / `uo_out` / `uio` per firmware
  profile, the open-drain mask value DR 0008 defers to it, and the
  machine-readable table that `scripts/check_protocol_pin_roles.py` checks
  against `info.yaml`, the committed firmware and the benches.
- `decision-records/0011-stretch-protocols-feasibility.md` — **Proposed
  baseline 2026-10-09** (not ratified), issue #109. Hand-counted TX/RX
  instruction schedules for low-speed USB and 10BASE-T on the current ISA,
  pure firmware, with assumptions. It gives the baseline only; the verdict
  is in DR 0015.
- `decision-records/0012-control-space-and-runtime-pin-direction.md` and
  `decision-records/0013-program-loading.md` — **Proposed 2026-10-09** (not
  ratified), written in response to the organizers' 2026-10-09 entrant
  update (issues #129–#134). They cover the runtime `uio` direction and
  program-memory access through the ISA's two spare no-op encodings, and a
  layered loader (serial recovery path + boot ROM in this ISA).
- `decision-records/0014-area-beyond-2x2.md` — **Proposed 2026-10-09** (not
  ratified), issue #129: what tiles beyond 2×2 buy (second engine, more SRAM,
  ISA assists) with sourced area costs, and a tile recommendation (keep 2×2).
- `decision-records/0015-stretch-protocols-with-neutral-primitives.md` —
  **Proposed 2026-10-09** (not ratified). Starts from DR 0011's
  current-ISA baseline and re-asks the stretch-protocol question with
  protocol-neutral ISA primitives in DR 0012's control space; admits CRC/LFSR and NRZI/bit-stuff, proposes
  low-speed USB TX-only, defers 10BASE-T (its Manchester stage fails the
  record's admission test) and all receive.
- `verification-plan.md` — what is verified and how, including the formal
  properties, constrained-random suites, and reference models.
- `gap-to-submission.md` — every spec row and template checklist item
  against current status, tracked against the 2027-01-18 deadline.

**How ratification works here.** Ratification of this spec runs through the
program's two-key (RATIFY-KEY) mechanism, installed in this repo at
[`ratification/ee-key/`](../ratification/ee-key/SKILL.md) and
[`ratification/market-key/`](../ratification/market-key/SKILL.md) (2026-09-21):
an EE key and a market key, **neither held by the ratifying PR's author
or the design's author**, each post one PR review opening with a
`RATIFY-KEY` marker line (the grammar lives in each skill's "Output
format" section); **the two reviews themselves are the release signal**, and
**the merge commit is the ratification record**. Pipeline approvals (Judge,
Champion) are quality gates, not keys — they never substitute for one.

> **2026-09-27 (issue #45) — the release signal is the reviews, not a label.**
> This paragraph previously named the second key-holder's release as applying
> `loom:auto-merge-ok`. That was wrong in a way that mattered: in the
> surrounding pipeline that label *overrides a merge-risk hold*, so its
> **absence blocked nothing** — one of the two mechanical reasons PR #29 could
> merge with zero key reviews (DR 0006 § Consequences). The release signal is
> now named as what the mechanism always said the act was: the two
> `RATIFY-KEY` reviews on the carrying PR. Nothing about the requirement is
> relaxed by the correction, and a key-holder may of course still apply
> pipeline labels — they are simply not what releases a ratification.

**Status vocabulary.** A record's `Status:` line is one of: `DRAFT` (a
surface still being written), `Proposed` (complete, awaiting the two-key act),
`Ratified` (the act ran — two `RATIFY-KEY` reviews on a named carrying PR,
cited with that PR's merge commit), or `Recorded` (a finding of fact plus the
mechanical consequence another record already prescribed for it; decides and
binds nothing, so nothing in it needs ratifying —
`0006-two-key-ratification-never-ran.md` is the only such record). A record
needs ratification when it **decides** something, not when it **observes**
something. Nothing writes `Ratified` on the strength of a process description:
the line must cite the carrying PR and its merge commit, and that PR's
`/pulls/<N>/reviews` must actually show the two markers —
`gh api repos/2AMLogic/sg13cmos5l-protocol-emulator/pulls/<N>/reviews --jq
'[.[]|select(.body|test("RATIFY-KEY"))]|length'` is the check, and it was `0`
for every PR in the repo as of 2026-09-26.

**This is enforced mechanically as of 2026-09-27 (issue #45).** A pull request
that moves any `Status:` line under `spec/` to `Ratified` fails the
`two-key gate (spec Status flips)` check
([`.github/workflows/ratification-gate.yml`](../.github/workflows/ratification-gate.yml))
and `npm run check:ci` unless that PR's own `/pulls/<N>/reviews` carries two
well-formed `RATIFY-KEY` markers — one `ee`, one `market`, distinct
`reviewer=` values, releasing verdicts, neither attributable to the PR's
author. The gate acts only on such a flip: editing a `Proposed` record,
amending prose on an already-`Ratified` line, and reconciling a line *away*
from `Ratified` are untouched. [`docs/ratification-gate.md`](../docs/ratification-gate.md)
is the authoritative description of what it checks, including the one question
it deliberately leaves to an operator (DR 0006 § "Routed, not decided") and
the operator step that makes the check *blocking* rather than merely red.

See issue #1 for how this surface came to exist, and DR 0006 for why the act
it describes had not happened as of 2026-09-26.
