# spec

Specification and decision records.

> **2026-10-11 (issue #44): the two-key mechanism has now run.**
> `target-spec.md` (rows 1–12, as DR 0004 registers them) and decision
> records 0001–0004 are ratified by the two `RATIFY-KEY` reviews on pull
> request #242; that PR's merge commit is the ratification record, and
> [`decision-records/0009-two-key-ratification-act.md`](decision-records/0009-two-key-ratification-act.md)
> records the act and exactly what it binds. DR 0001 is ratified with its
> 2026-10-11 fetch-ahead amendment. Target-spec rows 13 and 14 and decision
> records 0005, 0007, 0008 and 0010–0018 are **not** bound by it and stay
> `Proposed`. The 2026-09-26 banner below is preserved as written: it was
> true until that PR merged.

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

- `target-spec.md` — the checkable target table (Status: **RATIFIED**, rows
  1–12 as targets; rows 13 and 14 `Proposed`; each row's binding and its met/unmet evidence state
  are in the table's State column, registered per row in
  `decision-records/0004-target-spec-ratification.md`).
- `decision-records/` — numbered decision records (0001-isa.md and up),
  including `0004-target-spec-ratification.md` — the per-row register and
  binding record of 2026-09-21, whose own invalidation clause
  fired, `0006-two-key-ratification-never-ran.md`, which records that it
  did, and `0009-two-key-ratification-act.md`, which records the act that was
  then performed.
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
- `decision-records/0016-isa-flag-and-shift-details.md` — **Proposed
  2026-10-10** (not ratified), issue #203. Rules the four ISA details DR 0001
  leaves open, each as the RTL already behaves: `SUB` sets `C` as a borrow,
  `SHF` leaves `Z` unchanged, `AND`/`OR`/`XOR` leave `C` unchanged, and `SHF`
  fills with 0. No RTL change.
- `decision-records/0017-submission-isa-freeze.md` — **Proposed
  2026-10-10** (not ratified), issue #141 part 1. Freezes the submission ISA
  at the merge of its PR (base `e74d2b656de35e492e6f7b3e34cbe2266b4aeff3`):
  it pins by sha256 the eleven files that define the ISA a programmer sees
  (DRs 0001, 0005, 0012, 0013, 0015, 0016, the core, program-memory and top
  RTL, the assembler and the ISA reference model), says what is left out and
  why. An ISA change or conformance fix to them needs a later record (0018
  or above) stating whether it invalidates row-13 evidence; a change nothing
  can observe (a dated note, a Status line) cites its issue or PR. It also
  sets which
  protocols row 13 may not choose. The pins are machine-readable in
  `isa-freeze.json` and checked by `scripts/check_isa_freeze.py`
  (`npm run lint`). Row 13's protocol is chosen in a later commit.
- `decision-records/0018-row13-protocol-choice.md` — **Proposed
  2026-10-10** (not ratified), issue #141 part 2. Chooses WS2812 (single-wire
  NRZ LED data, graded on the WS2812B datasheet's timing) as row 13's primary
  protocol, after DR 0017's freeze at merge commit
  `1696045bfa1a33f93c95a5bf6c29b05f4ea0d734`. It checks the choice against
  DR 0017's exclusion list and records where WS2812 appears in the repository
  (three places, none weighing it against the ISA). The stretch column is not
  chosen. No pinned file changes.
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
`0006-two-key-ratification-never-ran.md` and
`0009-two-key-ratification-act.md` are the only such records). A record
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

See issue #1 for how this surface came to exist, DR 0006 for why the act
it describes had not happened as of 2026-09-26, and DR 0009 for the act.
