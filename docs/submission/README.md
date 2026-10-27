# Submission tracker

Status: **living tracker**, opened 2026-10-09 for issue #134. Readiness below
is stated from what is in the repo on that date, with the file that backs each
statement. Update a row when its state changes, and date the change. Do not
upgrade a state without citing the artifact or run that justifies it.

This is the judge-facing half of [`spec/gap-to-submission.md`](../../spec/gap-to-submission.md).
That file tracks spec rows and the template checklist; this one tracks the
**package a judge will open**.

## What the organizers require

Source: the organizers' update and FAQ email to registered entrants,
2026-10-09 (asic-competition@janestreet.com), quoted verbatim in issue #134.
They say the same text will reach the competition blog post; until then the
email is the citable source.

> A link to your public repository with your RTL, tests and a passing
> GDS/precheck from the Tiny Tapeout flow. Please also include documentation
> of your architecture and instruction set, your assembler or toolchain with
> example programs, and a write-up of your verification approach. A video or
> demo isn't required, but we'll look at it if you have one.

> Can I use AI tools? Yes. Please describe how you used them in your write-up.

The deadline is **2027-01-18** (`spec/target-spec.md` row 9). The submission
form opens close to the deadline. Small non-functional fixes, such as
re-hardening for a newer flow, are allowed after it.

## Readiness states

| State | Meaning |
|---|---|
| **Ready** | The judge-facing artifact exists, is current, and needs no further work for submission. |
| **Partial** | The content exists but is not yet in judge-facing form, or the artifact describes a design that will still change. |
| **Not started** | No judge-facing artifact exists. |
| **Blocked** | The artifact cannot be finished until a named issue closes. |

## Checking the documents before a push

Two checks cover the documents in this directory:

- **Record citations (offline, in `npm run lint`).**
  `python3 verification/check_docs_records.py` fails if a document here cites
  a record that does not exist or that a later record supersedes (#238).
- **Issue and PR states (on demand, needs the network).**
  `python3 scripts/check_docs_issue_states.py` finds each `#N` written next
  to "open", "still open", "closed", "merged" or "unmerged", asks GitHub for
  its live state through `gh`, and prints every mismatch (exit 1 if there is
  one). It is not in lint or CI, because it needs an authenticated `gh` and
  its answer changes whenever an issue moves; run it before pushing a change
  to this directory. It is a heuristic: it reads a paragraph, list item or
  table row at a time and takes the nearest state word, so it can misread a
  sentence that lists several states, and it cannot see a state claim that
  names no `#N`. Read each hit, and still read the prose. Dated text kept as written can carry
  `<!-- state-ok: reason -->`; prefer a dated correction. Its offline
  self-test is `python3 scripts/test_check_docs_issue_states.py`.

## Deliverables

| # | Deliverable | Judge-facing artifact (target) | What exists today | State |
|---|---|---|---|---|
| D1 | Passing GDS + precheck, Tiny Tapeout flow | `gds` workflow (`.github/workflows/gds.yaml`) green on the **final** top, with the run linked from this file and from `README.md` | All four jobs (`gds`, `precheck`, `gl_test`, `viewer`) green on `main` @ `4193268`: [run 37974043486](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/37974043486), 2026-10-09. Sign-off evidence: `verification/records/librelane-gds-signoff-check/records/20261011-144308-e5a0bae.md`, `verification/records/librelane-pdn-bridge/records/20261011-145000-e5a0bae.md`. | **Partial.** It is green, but not on the final top. DR 0012 (control space, #135) and DR 0013 (program loading) still change the RTL, and #129 may change the tile count. Re-run and re-link after the last RTL change. **Updated 2026-10-11 (#238):** the sign-off records cited in this row are the live ones and describe gds run [38136727636](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38136727636) at `6dd0e9d` (the PR #260 branch: DR 0020's open-drain fix and #246's timing repair, all four jobs green), not run 37974043486. #135 and #129 are closed, and `main`'s own `gds` runs since PR #260 merged are green on the same design files (for example run 38166393534 at `cd47c724`). Still **Partial**: no run is linked as the run of record from the root `README.md`. | <!-- superseded-ok: the v0.7.0-pin record the signoff manifest still cites for items 3 and 4; re-run at klt f979a965 with the same outcome by 20261012-204118-0af4491 (issue #289) -->
| D2 | Architecture + ISA documentation | A standalone doc, `docs/submission/architecture.md` (to write), distilled from DR 0001. It must not be the decision record itself. | The content is spread across `spec/decision-records/0001-isa.md`, `rtl/README.md`, and the datasheet `docs/info.md` § How it works. DR 0012 and DR 0013 extend the ISA and the load path. | **Partial.** The material exists, but there is no judge-facing doc. The ISA is not frozen until #135 lands. DR 0001's Status is still **Proposed** (DR 0006, #44). **Superseded 2026-10-11 (#230, #251):** the judge-facing doc now exists and #135 is closed; see the D2 dated update below and [Judge quickstart](#judge-quickstart-d2-d3). DR 0001 was ratified on 2026-10-11 (PR #242; see the [ratification update](#ratification-update-2026-10-11-pr-242-issue-44)). The row text is kept as the 2026-10-09 record. |
| D3 | Assembler / toolchain + example programs | `firmware/` with a quickstart a judge can run from a fresh clone | `firmware/tools/asm.py` (the DR 0003 assembler) and its test `firmware/tools/test_asm.py`. 16 programs in `firmware/asm/` (UART TX/RX at three bauds, SPI modes 0–3, I2C Standard/Fast with repeated START and clock stretch, plus `demo_roundtrip.asm`) with committed images in `firmware/build/`. `firmware/README.md` § Cold-start invocation. | **Partial, close to ready.** The cold-start section is the quickstart, but nothing links it as the judge's entry point. The assembler has to gain the DR 0012 control-space mnemonics (#135). **Superseded 2026-10-11 (#251):** `WCTL`/`RCTL` are implemented (#135, closed); the quickstart is now linked from here. See the D3 dated update and [Judge quickstart](#judge-quickstart-d2-d3). |
| D4 | Verification write-up | `docs/submission/verification.md` (to write), distilled from `spec/verification-plan.md` and the evidence records, and stating what is **not** covered | `spec/verification-plan.md` (Status DRAFT; its preamble line "None of the artifacts described below exist yet" is now stale). 21 record families under `verification/records/`, for example `firmware-uart`, `firmware-spi`, `firmware-i2c`, `firmware-gate-level`, `random-regression`, `no-data-dependent-latency` (formal), `post-layout-sdf-regression` and `sta-corner-sweep`. | **Partial.** The evidence is strong and append-only, but nothing reads it to a judge. Known holes that the write-up must state: #136 (I2C evidence does not run through the real `uio_oe`, so silicon cannot drive an I2C line today) and row 14 (reset/reselect, unmet). **Updated 2026-10-10 (issue #214): see the dated update below the table; the preceding text is the 2026-10-09 reading and is kept as written.** |
| D5 | AI-use write-up | [`docs/submission/ai-use.md`](ai-use.md): how agents produced the spec, RTL, firmware and verification; the Loom Builder/Judge/Curator loop; the append-only evidence rule; the klayout-tools friction issues filed; and the ratification history told honestly | **2026-10-10 (#213):** [`ai-use.md`](ai-use.md) is written. It covers who acted as the forge records it, the development loop (intended vs observed, with PR #210 as a worked example), the mechanical CI checks and their limits, append-only evidence (including the failing-then-superseded post-layout record), agent verdict vs operator decision, the ratification history (DR 0006, PR #29, the PR #48 gate, the refused PR #84 ceremony, #85), klayout-tools friction, and the limits of AI-generated verification. Before 2026-10-10 only fragments existed: `README.md` § Built agent-native and `spec/verification-plan.md` § 5. | **Partial** (2026-10-10). The document is judge-facing and written against `main` @ `9fb7815`; on 2026-10-11 (#238) its record citations, counts and ratification history were refreshed to `main` as of `a9ac6940` (after PR #242's merge `72f48153`). It describes a history that is still moving. Before submission, refresh the PR counts, the ratification history (PR #84 refused and closed unmerged; PR #242 merged 2026-10-11, ratifying target-spec rows 1-12 and DRs 0001-0004, #44 closed; rows 13-14 and the other DRs still **Proposed**; no independent human review has taken place), and the open klayout-tools issues. Then mark it Ready. |
| D6 | Demo (optional) | A protocol the ISA was **not** designed for (for example 1-Wire, WS2812, DMX512 or Manchester), written as firmware after the fact with a bench: target-spec row 13. If possible, a video. | Nothing. Row 13 is "Proposed 2026-10-09 ... unmet, no firmware yet" (`spec/target-spec.md`). | **Blocked** on the frozen submission ISA (#135, with #130 deciding which protocol-neutral primitives exist). A physical-board demo also needs the host loader (#118). **Superseded 2026-10-10 and 2026-10-11:** #135, #141, #118 and #235 are closed; WS2812 (primary column) and a PS/2 device (stretch column) have firmware and evidence; the row stays Proposed and unmet. See the D6 dated updates below. |
| D7 | Required external parts | A parts list in the datasheet (`docs/info.md`) and the submission, aligned with TT-recommended Pmods | Nothing beyond DR 0008 item 1 (I2C needs external pull-ups). | **Parts list written** in `docs/info.md` (#133). Pins are not yet on the TT-recommended pinouts: DR 0010 records the target plan, and the moves are #155 (after #135). **Updated 2026-10-11 (#238):** #155 closed on 2026-10-10: SPI and I2C moved to the Pmod `uio[0..3]` pins (PR #181, merged) and UART RX to `ui_in[1]` (PR #190, merged), DR 0010's target plan. |

### D2 dated update, 2026-10-11 (issue #230)

Reviewed commit: `main` @ `16c0b2a`. The D2 row above is left as written;
this update supersedes its "What exists today" and its reason for Partial.

- **Artifact.** [`architecture.md`](architecture.md) now exists, linked from
  the root `README.md`. It covers the datapath and a block diagram,
  fetch-ahead and the fixed +1 run-entry cycle, `IN`/`OUT` pin timing, the
  instruction table (encoding, operands, cycles, `Z`/`C`), the ports, the
  full control map with per-direction latency, runtime direction and open
  drain, P1/P2, the reserved encodings and `--allow-reserved`, the
  boot/load path, what the ISA does not do, evidence links, and limitations.
  It separates logical timing from electrical evidence.
- **Checker.** [`scripts/check_architecture.py`](../../scripts/check_architecture.py)
  compares the document's five marked tables with `firmware/tools/asm.py`
  (mnemonics, opcodes, kinds, control indices, permissions, latencies,
  ports, and assembled words and cycle counts for every operand form) and,
  for flags, with the independent model `verification/reference_models/isa.py`.
  Its self-test is [`scripts/test_check_architecture.py`](../../scripts/test_check_architecture.py).
  Both run in `npm run lint`, which the CI `records` job runs.
- **The "ISA is not frozen until #135 lands" reason is stale.** #135 and
  #141 are closed, and DR 0017's freeze is on `main` with its lint.
- **State: still Partial, not Ready.** The document is marked provisional,
  and, on this date, known changes would still make it refresh: finding #244
  (routed open-drain release glitch; any fix changes the pinned top and the
  open-drain text), PR #248 for #211 (the boot ROM's UART frame, which the
  load-path section describes), and #217 (no routed-SDF evidence for the
  protocol firmware). All three have since resolved: PR #248 merged and #211
  closed (2026-10-11T08:09Z), #244 closed (16:08Z, DR 0020), #217 closed
  (16:34Z); see the D3 update below. The tracker's Ready definition needs a current
  document with no known refresh left. DR 0001, 0005, 0012, 0013, 0015, 0016
  and 0017 stay **Proposed**; ratification is #44. This update ratifies
  nothing and marks no spec row met. (Since: #44 closed when PR #242 ratified
  DR 0001 on 2026-10-11; the others stay Proposed. See the
  [ratification update](#ratification-update-2026-10-11-pr-242-issue-44).)

### D3 dated update, 2026-10-11 (issue #251)

Reviewed commit: `origin/main` @ `f015802f`. The D3 row above is left as
written; this update supersedes its "What exists today" count and its reason
for Partial.

- **Control-space mnemonics are implemented.** `firmware/tools/asm.py`
  assembles `WCTL k, Rs` and `RCTL Rd, k` (#135, closed) and 13 committed
  programs under `firmware/asm/` use them (for example `i2c_std.asm`,
  `spi_mode0.asm`, `ws2812.asm`, `boot/boot_rom.asm`). The row's "has to
  gain the mnemonics" reason is stale.
- **Program count.** `firmware/asm/` now holds 18 top-level programs (the
  16 listed in the row, plus `ps2_device.asm` and `ws2812.asm`) and one boot
  program under `firmware/asm/boot/`. `firmware/tools/check_firmware.py` checks every committed program and
  the boot program.
- **Entry point.** The cold-start section is now linked from the
  [Judge quickstart](#judge-quickstart-d2-d3) below.
- **Corrections to the D2 update above, from the live tracker on this date.**
  That update treats PR #248 for #211 as a pending refresh. PR #248 is
  merged and #211 is closed; the 232-word boot ROM the load-path section
  describes is on `main`. At this update's reviewed
  commit, #244 (routed open-drain release glitch) and #217 (no routed-SDF
  evidence for the protocol firmware) had not closed; both closed later the
  same day (see the last bullet).
- **State: still Partial, not Ready.** What is implemented: the assembler,
  its 53 unit tests, the 18 + 1 programs with committed images, the
  freshness check and the RTL round-trip bench. What remains: the ISA text
  stays **Proposed** (DR 0001, 0012, 0013, 0017; ratification was then
  pending on #44), so nothing here is ratified (DR 0001 has since been ratified, the
  others have not; see the ratification update below); #244 and #217, then not closed, could still
  change the architecture document or its evidence (both have since closed,
  below); and D1 has to be re-run on the final top. Nothing in this update
  is a hardware or physical-signoff claim.
- **Update 2026-10-11 (issues #244 and #246).** #244 is fixed in the top by
  DR 0020 (an open-drain pin's pad data is tied to 0), with the routed-SDF
  I2C repeated-START run passing at all three corners and failing on the
  pre-fix netlist; `architecture.md`'s open-drain text is refreshed for it.
  #246's slow-corner margin is +5.8 ns on the LibreLane flow (it was +1.9 ns),
  with no max-slew or max-capacitance violation, from five repair settings
  in `src/config.json`. Both are in the records of gds run 38136727636
  (`librelane-corner-timing` `20261011-144900-e5a0bae`,
  `post-layout-sdf-regression` `20261011-114800-e5a0bae`). #217 closed at
  2026-10-11T16:34Z on that evidence: UART TX, SPI and I2C repeated START
  have routed-SDF runs at all three corners; the boot programs, UART RX,
  PS/2, WS2812 and the random regression do not. D1 still has to be
  re-linked to the final top's run. Nothing here is a silicon claim.

## Judge quickstart (D2, D3)

Commands below were run on 2026-10-11 against `origin/main` @ `f015802f`
(Python 3.12.3). Steps 1 to 3 need only Python 3 (>= 3.9) from the stdlib.

1. **Read the architecture and ISA.** [`architecture.md`](architecture.md)
   (provisional draft; the decision records win where they disagree). Its
   tables are compared with the assembler and the independent ISA model by
   [`scripts/check_architecture.py`](../../scripts/check_architecture.py):
   `python3 scripts/check_architecture.py`.
2. **Assemble an example.** From the repository root:
   `python3 firmware/tools/asm.py firmware/asm/demo_roundtrip.asm`
   writes `firmware/build/demo_roundtrip.hex` and `.cycles.txt` (27 words,
   30 fall-through cycles). Use `--out-dir <dir>` to write elsewhere.
3. **Compare with the committed artifacts.**
   `python3 firmware/tools/asm.py firmware/asm/demo_roundtrip.asm --check`
   for one program (prints `OK: committed artifacts match ...`), or
   `python3 firmware/tools/check_firmware.py` for every program, the boot
   ROM chain and the load sequences (ends with `0 failing check(s)`). The
   unit tests are `python3 firmware/tools/test_asm.py` (53 tests).
4. **Run it on the RTL.** This step needs the pinned `klt`, cocotb and
   Icarus (`./scripts/setup-env.sh`; see
   [`verification/README.md`](../../verification/README.md)):
   `klt functional-verification verification/request-firmware-roundtrip.json --format json`
   assembles `demo_roundtrip.asm`, loads it through the program-memory load
   phase and reads every word back; it reported `status: pass`, 3 of 3 tests.
   The per-protocol firmware benches and their append-only records are listed
   in the [`firmware/README.md`](../../firmware/README.md#cold-start-invocation-a-third-party-can-run-this-from-a-fresh-clone)
   cold-start section and under `verification/records/`.

Step 4 is a logical RTL simulation of the load path. It is not evidence of
silicon behaviour, and this walkthrough infers none.

### D6 dated update, 2026-10-10 (issue #141 part 2)

The D6 row above is left as written. Row 13's primary column now has
firmware and evidence. WS2812 was chosen by DR 0018 after DR 0017's ISA
freeze (merge `1696045b`), and no ISA-defining file changed. The program
passes an independent WS2812B model at RTL and on the gate-level netlist.
The judge-facing write-up, including what the frozen ISA made easy and hard,
is [`row13-ws2812.md`](row13-ws2812.md). **State: partial.** The row is
Proposed and unmet. There is no SDF run, no board and no video. The stretch
column (a new role or pin direction) was then issue #235, closed 2026-10-11
with the PS/2 device in the next update.

### D6 dated update, 2026-10-11 (issue #235)

The stretch column of row 13 has firmware and evidence too: a PS/2 keyboard
or mouse **device** on two open-drain lines that a host also drives, chosen by
a dated note in DR 0018 after the freeze, with no pinned file changed. An
independent host model, running on the silicon-true pad model, graded it at
RTL and on the gate-level netlist; see `docs/info.md` and
[`row13-ps2.md`](row13-ps2.md). **State: partial.** The row is Proposed and
unmet, the pad model has zero delay, and there is no SDF run, no board and no
video.

### D4 dated update, 2026-10-10 (issue #214)

Reviewed commit: `main` @ `ceaebe02` (first written at `9fb7815`; its record
citations were refreshed to `ceaebe02` on 2026-10-11 for #238). The
judge-facing narrative now exists:
[`docs/submission/verification.md`](verification.md), linked from the root
`README.md`. It maps each claim to its independent oracle, tested design level
and flow, evidence record, reproduction command and limits, and lists what is
not shown. The 2026-10-09 row above is left as written, except that its record citations point to the live records; these corrections
supersede its stale parts:

- **Record families:** 34 directories under `verification/records/` at this
  commit, not 21.
- **`gds` run the records name:** [38083802720](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38083802720)
  at `bce5bf4`, a PR-branch run (all four jobs green, as recorded in
  `post-layout-sdf-regression` `20261010-205119-af36071` <!-- superseded-ok: live at ceaebe02, this update's reviewed commit; newer records and a newer gds run exist -->); the design files
  (`src`, `rtl`, `info.yaml`, `firmware/build/boot`) are unchanged from there
  to `ceaebe02`, whose own `gds` run, 38107612922, is green. D1 stays
  **Partial** for the reasons in its row.
- **#136 has landed.** The I2C and SPI evidence runs on the logical, zero-delay
  `uio` pad model, which resolves the design's own `uio_oe`/`uio_out`
  (`uio-pad-model` record `20261011-012812-428e12f` <!-- superseded-ok: live at ceaebe02, this update's reviewed commit -->). It is not an electrical
  pad characterization. The "does not run through the real `uio_oe`" hole is
  closed; the electrical hole is not.
- **UART RX is covered**, directed (`firmware-uart-rx`) and in the seeded
  constrained-random regression (`random-regression`, `uart_rx` family,
  #192), and on the zero-delay gate-level run. The regression itself is RTL
  only. The line in `manifests/evidence/testbenches.txt` that says no claim is
  made for UART RX under constrained random predates #192 and is left as
  written.
- **Row 14** still reads unmet in `spec/target-spec.md`. The
  `reset-power-up` record `20261010-205223-af36071` <!-- superseded-ok: live at ceaebe02, this update's reviewed commit --> shows (a), (b), (c) and
  the reselect cycle on the routed netlist at zero delay; no grade is changed
  here.
- **Limits stated in the narrative** (as of 2026-10-11): the residue of
  DR 0013 finding F8 (#211, closed, added a count-complement byte that the
  UART load checks before it commits a word; a coordinated corruption of
  count and complement that also aliases the CRC is still not rejected), no
  SDF run for the boot programs, UART RX, PS/2, WS2812 or the random
  regression, bounded versus unbounded formal scope, SRAM timing omitted from
  SDF, decision records and rows 13-14 still Proposed (target-spec rows 1-12
  and DRs 0001-0004 were ratified by PR #242 on 2026-10-11), and no silicon.
  Resolved since the first version and described as such: the PM_CRC readout
  (PR #167, merged 2026-10-10), the Standard-mode I2C allocation (#125,
  closed 2026-10-11, ruled `enforce_500`), and routed-SDF runs of UART TX,
  SPI and I2C repeated START (#217, closed 2026-10-11).
- **State:** still **Partial**, not Ready. The ISA is frozen mechanically —
  DR 0017 pins the ISA-defining files in `spec/isa-freeze.json` and
  `npm run lint` enforces the pins — and target-spec rows 1-12 and DRs
  0001-0004 are ratified (PR #242), but DR 0012, 0013, 0016 and 0017 and
  rows 13-14 are Proposed. #211 has since closed DR 0013's F8 (its residue is listed
  above), and the design has changed under the report since (DR 0020's
  open-drain fix and #246's timing repair, gds run 38136727636). What remains
  before Ready: re-review the report against the current tree, and the final
  `gds` re-link (D1).

### Ratification update, 2026-10-11 (PR #242, issue #44)

Reviewed: `main` @ `a9ac6940` (PR #242 merged as `72f48153`). The rows and dated
updates above that call the specification Proposed or ratification pending were true
when written and are kept; this update supersedes them.

- **The act.** PR #242 carried the five `Status:` flips and
  [DR 0009](../../spec/decision-records/0009-two-key-ratification-act.md).
  At its head `26297b9e` the EE key answered `approve` and the market key
  `adequate-for-catalog` (forge reviews 5484904651 and 5484909288); the PR
  merged at 2026-10-11T20:57Z as `72f48153` and #44 closed. Earlier on #242
  the EE key had requested changes, and PR #84 had been refused and closed
  unmerged.
- **What is Ratified.** `spec/target-spec.md` rows 1-12, as targets and as
  DR 0004 registers them, and DRs 0001-0004. Ratifying a row binds it; it
  does not mark it met, and no `State` cell changed.
- **What is not.** Rows 13 and 14; the DR 0013 clause in row 6; DRs 0005,
  0007, 0008, 0010-0018 and 0020 (still Proposed); DR 0006 and DR 0009 are
  `Recorded`. DR 0009 records a limit on independence: one coordinating
  session dispatched both key agents.
- **Effect on the deliverables.** D2's DR 0001 is now ratified, but the
  control space, load path and freeze it relies on (DR 0012, 0013, 0017) are
  not. D4, D5 and D6 are refreshed for this in `verification.md`,
  `ai-use.md` and `row13-*.md`. No readiness state changes.

## Risks

| # | Risk | Finding as of 2026-10-09 | State |
|---|---|---|---|
| R1 | **Flow runtime.** The 6-hour GitHub Actions limit could kill the `gds` job if #129 grows the design toward 6×4 or 8×4. The fallback is [local hardening](https://tinytapeout.com/guides/local-hardening/). | At 2×2 the `gds` job took **6 min 24 s** (run 37974043486: 18:32:55Z to 18:39:19Z), far from the limit. No larger floorplan has been hardened. Nobody has tried local hardening on any fleet host; there is no record of it in this repo. | **Open.** Before #129 commits to a larger tile count, harden it once in CI and record the wall time. Separately, prove local hardening on a fleet host and record it, before we depend on it. **Updated 2026-10-11 (#238):** #129 closed on 2026-10-09 without growing the tile count, so the CI-hardening half did not trigger; the local-hardening half stands. |
| R2 | **tt-gds-action version.** The organizers ask for the latest tt-gds-action, which carries the CMOS5L install fix. | Checked against `TinyTapeout/tt-gds-action` on 2026-10-09. `gds.yaml` uses the **branch** ref `@ihp-cmos5l` for all four jobs. Its tip is `3412659` (2026-09-14), *"fix: install ihp-sg13cmos5l from the merged IHP-Open-PDK tree #52"*, which is the CMOS5L install fix. Upstream has **no CMOS5L release tag**: the newest tags are `ttsky26d` and `ttihp26b`, and `ttihp*` is SG13G2. So the workflow is already on the latest CMOS5L code, and no edit is needed. Two caveats follow. (a) A branch ref floats, so a later upstream push changes our flow silently. Evidence records should name the action SHA a run used. (b) `ihp-cmos5l` is 3 commits behind upstream `main`, and two of those commits fix `gl_test` result detection. On `ihp-cmos5l`, `gl_test/action.yml` checks with `! grep failure results.xml`. Our pinned `cocotb==2.0.1` marks a crashed test with an `<error>` element, which that grep does not match. So a gate-level test that **errors** rather than fails could still turn the job green. `main` uses `cocotb_tools.check_results` instead. The RTL leg is not exposed, because `test.yaml` uses `scripts/check_test_results.py`. | **Open.** (Caveat (b) is closed by the [GL-gate R2 update](#r2-update-2026-10-11-240-the-gl-results-gate-ran-in-ci) below. Caveat (a), the floating branch ref, is addressed by the [commit-SHA pin](#r2-update-2026-10-11-231-tt-gds-action-pinned-to-a-commit-sha), pending a green `gds` run on that SHA.) As first written: **caveat (b) needs a follow-up.** Either add a post-step to the `gl_test` job that runs `scripts/check_test_results.py` on the GL `results.xml`, or ask upstream to merge `main`'s `gl_test` fixes into `ihp-cmos5l`. Re-check the branch tip and the tags before submission. |
| R3 | **SRAM integration cross-check** against Ken Pettit's walkthrough (<https://kdp1965.github.io/ihp-um-janestreet-prism/ihp_sram_macro.html>, written 2026-09-29 for a 512×32 macro; ours is `RM_IHPSG13_1P_256x16_c2_bm_bist`). | A desk comparison was done for this tracker; it is not a measurement. **Matches:** `A_DLY` is tied to 1 and BIST is tied off (`src/protocol_program_memory.v`). Behavioural models are compiled with `-DFUNCTIONAL` for both the RTL and GL legs (`test/Makefile`, `rtl/vendor/`). There are two `PDN_MACRO_CONNECTIONS` lines, one for `VDD!` and one for `VDDARRAY!`. The PDN is Metal4-only (`FP_PDN_MULTILAYER` 0, `FP_PDN_VWIDTH` 2.1, `FP_PDN_VPITCH` 44.96 = 4 × 11.24). Precheck layers 25/0 and 16/0 are not a problem, because precheck is green. **Differs, and why:** our bridges are drawn by `src/pdn_cfg.tcl` rather than by stripe-nudging; record `librelane-pdn-bridge` reports PSM-connected nets, LVS 0, antenna 0, and worst IR drop 2.68 mV (his is 0.46 mV, on a different macro and floorplan). We set no `FP_MACRO_HORIZONTAL_HALO` and no `ROUTING_OBSTRUCTIONS`, and nothing on record shows a problem from either. **Worth a second look:** his flow runs `RUN_KLAYOUT_DRC` 1 with the CMOS5L deck in place of Magic, whereas ours has `RUN_KLAYOUT_DRC` 0 **and** `ERROR_ON_MAGIC_DRC` 0 (29,297 Magic hits, all inside the macro GDS, per the PDN-bridge record). That leaves the TT precheck's DRC as our only DRC gate. That is likely sufficient, but nobody has confirmed it. | **Partially done.** Follow-up: confirm which DRC deck `precheck` runs on CMOS5L, or turn on `RUN_KLAYOUT_DRC` as the walkthrough does. Confirm also that the IHP-Open-PDK commit the action installs matches the one precheck pins. |
| R4 | **Submission form.** It opens near the deadline. | It is not open. Watch the organizers' email and the competition blog post. | **Watch.** Re-check monthly, and weekly from 2026-12-15. |

## Order of work

1. Freeze the ISA: #135 (DR 0012), then DR 0013. D2, D3 and D6 cannot finish
   before this.
   (Superseded 2026-10-11, #251: #135 and #141 are closed and DR 0017's
   freeze is on `main`; what is left for D2/D3 is in their dated updates.)
2. Settle the area: #129. If the tile count grows, harden it in CI and record
   the wall time (R1).
3. Write D5 (AI-use) now. It depends on no RTL change and is the most
   distinctive document. (2026-10-10: written as
   [`ai-use.md`](ai-use.md), #213. Refresh it before submission.)
4. Write D4 (verification) once #136 lands. List row 14 and anything else
   still unmet as such. (First version written 2026-10-10, #214; re-review
   after the ISA freeze.)
5. Do D6, the row-13 unplanned-protocol firmware, on the frozen ISA.
   (2026-10-11: #141 is closed — WS2812 and PS/2 firmware and evidence are
   in; the rows stay partial per their dated updates and `row13-*.md`.)
6. Do the final `gds` run on the final top (D1), link it, then update every
   row here to **Ready** with citations.
   (2026-10-11: #129 is closed — the tile count did not grow, so R1's CI
   hardening did not trigger. Item 6 is the remaining gate before Ready.)

## R2 update, 2026-10-11 (#240): the GL results gate ran in CI

The 2026-10-10 R2 update above is left as written; its **Not verified** bullet
is superseded by this one.

- **The gate is in the job and has passed.** [Run 38083802720](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38083802720)
  at `bce5bf4` — with the gate change (`15f112cc`, PR #228) already merged —
  ran the modified `gds.yaml`: the `Validate GL results (repository-owned)`
  step executed after `gl_sim`, the `if:` expression was exercised by the
  Actions runner, and all four jobs are green. [Run 38136727636](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38136727636)
  at `6dd0e9d` (the final top, DR 0020 + #246) passed the same gate with all
  four jobs green. Caveat (b) is closed by those runs.
- **R2 state.** Still **Open** on caveat (a) when written: the `ihp-cmos5l`
  branch ref floated, evidence records should keep naming the action SHA a
  run used, and the branch tip and tags must be re-checked before
  submission. Since then #231 (closed 2026-10-11) pinned every reference to
  a commit SHA; see the #231 update at the end of this file.

## R2 update, 2026-10-10 (#216): repository-owned GL results gate

- **Action revision checked.** `ihp-cmos5l` resolved via `gh api` to
  `3412659307918422f3f0727917cf9b499aaca588` on 2026-10-10 (unchanged from the
  2026-10-09 tip). Its `gl_test/action.yml` at that SHA runs `GATES=yes make` in
  `test/` directly on the runner workspace (no container), after
  `rm -f ... results.xml`, and its only verdict is `test -f results.xml` then
  `! grep failure results.xml`. The results file is therefore `test/results.xml`
  in the workspace. This confirms R2(b). The branch ref still floats; the SHA
  above is what was inspected, not a pin.
- **Change.** `.github/workflows/gds.yaml` `gl_test` now (1) removes
  `test/results.xml` before simulation, (2) runs the action as step
  `gl_sim`, and (3) runs `python3 scripts/check_test_results.py test/results.xml`
  when `gl_sim` succeeded or failed (not skipped, not cancelled). There is no
  `continue-on-error`, so a failed `gl_sim` keeps the job red even if the XML
  says pass; a missing file fails in the checker.
- **Verified locally (fixtures only).** `python3 scripts/test_check_test_results.py`
  passes, including the workflow's exact relative-path invocation against
  passing, error-only, failure, contradictory, malformed, empty, all-skipped
  and missing results, the stale-result ordering check, and structural checks
  of the step conditions. The workflow parses as YAML.
- **Not verified.** No GitHub Actions run of the modified `gds.yaml` exists yet,
  so a passing GDS/GL run with the new gate is **not** claimed, and the
  `if:` expression has not been exercised by the Actions runner. The R2
  state stays **Open** until a run on this change is green and linked here.
  Re-check the branch tip and tags before submission.

## R2 update, 2026-10-11 (#231): tt-gds-action pinned to a commit SHA

- **Pin.** All six `TinyTapeout/tt-gds-action` references (four in
  `gds.yaml`, one each in `fpga.yaml` and `docs.yaml`) now use
  `3412659307918422f3f0727917cf9b499aaca588` with the trailing comment
  `# ihp-cmos5l`. Resolved on 2026-10-11 with
  `gh api repos/TinyTapeout/tt-gds-action/commits/ihp-cmos5l --jq .sha`. The tip
  subject is *"fix: install ihp-sg13cmos5l from the merged IHP-Open-PDK tree
  #52"*, the same commit inspected on 2026-10-09 and 2026-10-10, so the pin does
  not change the flow itself.
- **Lint.** `scripts/check_action_pins.py` (self-test
  `scripts/test_check_action_pins.py`, both in `npm run lint`) fails if any
  such ref is not a lowercase 40-hex SHA, if the refs do not all share one SHA,
  or if none are found.
- **Bump procedure.** Bumping is allowed and expected near 2027-01-18, as a
  deliberate, recorded change. (1) Resolve the new tip with the `gh api`
  command above. (2) Edit all six refs together. (3) Run
  `python3 scripts/check_action_pins.py`. (4) Re-run all four `gds.yaml` jobs
  plus `fpga` and `docs` on the new SHA. (5) Add a dated entry here with the old
  SHA, the new SHA, the `git log old..new` subjects and the run link. The lint
  validates only the end state, not this procedure.
- **Limit.** Only our reference is immutable. The composite actions at that SHA
  call floating refs of their own (`actions/checkout@v6`,
  `actions/setup-python@v6`, `actions/upload-artifact@v7`,
  `TinyTapeout/ciel-action@v1`, `test-summary/action@v2.6`,
  `YosysHQ/setup-oss-cad-suite@v4`). Pinning does not freeze those; they are
  upstream's and out of scope.
- **Not verified.** No GitHub Actions run on the pinned SHA has been seen, so no
  green run is claimed. The run log's "Download action repository ... @<sha>"
  lines are unchecked. R2 stays **Open** until a `gds` run on this SHA is green
  and linked here.

## R3 update, 2026-10-11 (#257): what the precheck DRC covers

The R3 row above is unchanged. This section answers its "nobody has
confirmed it" by reading the action source. All sources were read with `gh api`
and `git ls-remote` on **2026-10-11** (read-only; nothing installed).

**Flow naming.** Every number below is labelled with the flow that produced it:
**TT/LibreLane CI** is the `gds` and `precheck` workflow jobs. **klt** is this
program's `klt drc` flow (`layout/toolchain.json` pin `0e2362bd`). They use
different decks and are not interchangeable.

### What was inspected

| Item | Inspected at | Source read |
|---|---|---|
| `TinyTapeout/tt-gds-action` (`gds` job) | `3412659307918422f3f0727917cf9b499aaca588` (tip of `ihp-cmos5l` on 2026-10-11, and the SHA `gds.yaml` now pins) | `action.yml`, `install_sg13cmos5l.sh` |
| `TinyTapeout/tt-gds-action/precheck` | same SHA | `precheck/action.yml` |
| `TinyTapeout/tt-support-tools`, both actions' default `tools-ref: ihp-sg13cmos5l` (**floating**) | `d66cf179e7bc4d296362ab7e2e3b344dc3c4f665` (tip on 2026-10-11) | `precheck/precheck.py`, `precheck/tech_data.py` |
| `IHP-GmbH/IHP-Open-PDK` at the commit the install script fetches | `2bbec755dc67ca3db0261c3d6163e15735d66710` | `ihp-sg13cmos5l/libs.tech/klayout/tech/drc/ihp-sg13cmos5l.drc` and `rule_decks/`, `ihp-sg13cmos5l/libs.tech/librelane/config.tcl` |

The latest completed `gds` run seen, 38174354943 (main at `72f48153`, TT/LibreLane
CI), still ran `@ihp-cmos5l` because it predates the #231 pin. Its precheck log
shows `tt-support-tools` checked out at `d66cf179…`, the same SHA as above, and
the action branch tip was `3412659…`, the pinned SHA. So the tip and that run's
SHA coincide and there is no difference to record. `tt-support-tools` is not
pinned by us: it is a floating ref inside the action (the "Limit" bullet of the
#231 update), and a later push to it changes the precheck silently.

### DRC deck and runner that `precheck` invokes (CMOS5L)

`precheck/action.yml` runs `nix-shell --run "python precheck.py --gds
tt_submission/*.gds* --tech ihp-sg13cmos5l"` in `tt/precheck`. For this tech,
`precheck.py` (tt-support-tools `d66cf179`) runs:

- **KLayout SG13CMOS5L DRC**: `klayout -b -r
  $PDK_ROOT/ihp-sg13cmos5l/libs.tech/klayout/tech/drc/ihp-sg13cmos5l.drc` with
  `-rd sg13cmos5l=true -rd input=<gds> -rd thr=1`. No `tables`, `no_*` or
  `precheck_drc` option is passed. So it runs the deck's default `main` tables
  with every group on (FEOL, BEOL, offgrid, angle, PIN, FORBIDDEN, RECOMMENDED)
  and `PRECHECK_DRC=false`, which keeps the rules that the deck's reduced mode
  skips (for example M1.e/f and Mn.e/f wide-metal spacing, Vn enclosure). Any
  violation in the report database fails the job (`report.num_items() > 0`).
  No `run_mode` is passed either, and the deck's `setup_run_mode` uses `flat`
  only when `run_mode` is `flat` (or tiles when it is `tiling`), otherwise
  `deep`. So precheck runs in **deep (hierarchical) mode from the top cell**.
  Run 38174354943's log confirms this with an empty `" mode is enabled."` line.
  Deep mode still processes the whole hierarchy under the top cell, so the SRAM
  macro is included. (Precheck's `thr=1` is not read by this deck, which reads
  `$threads`. Nothing here relies on it.)
- **Not run on CMOS5L:** `Magic DRC` (its `techs` list is sky130A and gf180mcuD
  only), the KLayout FEOL/BEOL/offgrid decks (sky130A only) and the urpm/nwell
  check (sky130A only).
- **Also run (not DRC rules):** pin-label/drawing overlap, zero-area shapes,
  top cell name, forbidden layers `TopMetal1.drawing|pin|label`, `prBoundary`
  present, pin check against the `tt_block_2x2_pgvdd.def` template, boundary
  check (no shape outside `prBoundary`), layer allowlist, cell-name characters,
  analog-pin check.

Run 38174354943 (TT/LibreLane CI) logged `tables selected: main`, `PreCheck DRC
enabled: false`, 333 `Executing rule` lines across the table list NWell through
FORBIDDEN (including M1-M4, Via1-3, TopVia1, Cont, Act, Gat, offgrid and
angle), `KLayout DRC run for tables 'main' completed in 117.0 seconds`, a
design of 419.52 x 313.74 um, and `Precheck passed`. The whole `precheck` job took
3 min 13 s. This is a pass in the TT/LibreLane CI flow; it is not a count of
violations, because the gate only reports zero.

**The deck the in-flow gate would run is the same file.** The PDK's LibreLane
config (`libs.tech/librelane/config.tcl` at `2bbec755`) sets
`KLAYOUT_DRC_RUNSET` to `ihp-sg13cmos5l.drc` with
`KLAYOUT_DRC_OPTIONS` `no_recommended=true`, `run_mode=deep`. So `RUN_KLAYOUT_DRC=1`
would run the same rules as precheck, in the same deep mode, minus the
RECOMMENDED group (`no_recommended` is the only option that differs), at
the LibreLane step position (which GDS it would read there was not checked). Precheck is a superset for this
tech. The same config exports `KLAYOUT_DENSITY_RUNSET` (`density.drc`) and
`KLAYOUT_ANTENNA_RUNSET` (`antenna.drc`) as separate runsets. Neither is included
by `ihp-sg13cmos5l.drc`, and neither is a precheck step.

### IHP-Open-PDK commit comparison

| Consumer | Commit | Basis |
|---|---|---|
| `gds` action (`action.yml` runs `install_sg13cmos5l.sh`) | `2bbec755dc67ca3db0261c3d6163e15735d66710` | `IHP_PDK_REV` in the script at the pinned SHA; run 38136727636's `pdk.json` records `PDK_VERSION 2bbec755dc67…` (`verification/records/librelane-gds-signoff-check/artifacts/20261011-144308-e5a0bae/pdk.json`) | <!-- superseded-ok: the v0.7.0-pin record the signoff manifest still cites for items 3 and 4; re-run at klt f979a965 with the same outcome by 20261012-204118-0af4491 (issue #289) -->
| `precheck` action (`precheck/action.yml` runs `${{ github.action_path }}/../install_sg13cmos5l.sh`) | `2bbec755dc67ca3db0261c3d6163e15735d66710` | the same script file, at the same action SHA |
| `layout/toolchain.json` (klt flow) | `2bbec755` (prose only; **matches**) | no machine-readable PDK pin field. The append-only `_comment` paragraph for the current `0e2362bd` klt pin (issue #83, 2026-10-10) says that pin was "Verified live at 0e2362bd … IHP-Open-PDK 2bbec755 (scratch checkout)" |
| Repo-level statement | `2bbec755dc67` | `README.md` ("Legs that need the PDK"), `manifests/evidence/layout-gds.json`; `docs/environment.md` says klt resolves the PDK path via `klt pdk find` and records no commit |

Finding 1: the `gds` and `precheck` actions provision **the same PDK commit**,
because both call one script. No mismatch between them.
Finding 2: `layout/toolchain.json` has no PDK pin field, but the `_comment` for
the `0e2362bd` klt pin records verification against IHP-Open-PDK `2bbec755`,
which **matches** the commit both actions install. No mismatch. The match is a
coincidence of the current pin, not a shared source: the two flows provision
their PDK independently — the TT CI script fetches `2bbec755` itself, while
the klt flow gets whatever klt's own fetch script materializes.
klayout-tools#2720 (merged 2026-10-12, not in the pinned klt v0.7.0) repoints
the klt fetch at IHP-Open-PDK `dev` @ `f7bca326`, so the klt flow's revision
will diverge from the flow of record at the klt pin bump (issue #289);
reconciling the two (evidence re-runs and re-stamp) is issue #290. What is still
missing is a per-run record: the klt DRC report's `provenance.pdk` is `null`
(`verification/records/librelane-gds-signoff-check/artifacts/20261027-190021-1ec5186/klt-drc.json`,
klt 0.8.0, KLayout 0.30.12), so the PDK a given klt run used is not
machine-recorded, and nothing machine-checks that the local `PDK_ROOT` is
`2bbec755`. The klt DRC deck is
klt's own `sg13cmos5l` deck (content hash `sha256:5a43b8eb…` at the current klt pin, `klayout-tools==0.8.0`; it has moved at every pin bump, see `layout/toolchain.json`), not the IHP file
precheck runs, so the two DRC results are different evidence.

### Coverage

"Precheck" below means `ihp-sg13cmos5l.drc` plus the structural checks above
(TT/LibreLane CI). klt evidence is the klt flow's `klt drc` report on the CI GDS,
`verification/records/librelane-gds-signoff-check/artifacts/20261027-190021-1ec5186/klt-drc.json`
(33 rules checked, 12 inapplicable, `status: violations`, 4,484 violations, every one inside the foundry SRAM macro: `nwell.enclosing.pactiv.1` 4,352 and `nwell.space.2` 132; the deck at the current klt pin checks 33 rules where the previous pin's checked 26 and graded `clean`; see the record).

| Layout we draw | Checked by precheck | Absent from precheck | Evidence |
|---|---|---|---|
| **PDN bridges** (fixed Metal4 stripes from `src/pdn_cfg.tcl`, plus the Via1-3 stacks pdngen adds) | Metal4 width, space, wide-metal spacing; Via1/2/3 size, space, enclosure; Metal1-3 rails; offgrid and angle on all those layers; `TopMetal1.drawing` forbidden (the reason the bridges are Metal4-only). | **Opposite-net shorts and opens**: DRC is net-agnostic, so a merged opposite-net overlap is not a rule violation. Antenna. Metal density. | Deck source: `rule_decks/beol/5_17_metaln.drc`, `5_20_vian.drc`; run 38174354943 log. Net-level checks are on record from **TT/LibreLane CI** only: PSM "all shapes connected", `design__power_grid_violation__count` 0, LVS 0 (`librelane-pdn-bridge` record `20261011-145000-e5a0bae`). klt also reports Metal4 width and space clean on the same layout. |
| **Signal routing** (Metal1-4, Via1-3, stdcell Cont/Activ/GatPoly) | The same width, space, enclosure, offgrid and angle rules, plus Cont, Activ, GatPoly, NWell, PWell-block, latch-up. | Antenna, density, and connectivity (LVS). | Same as above. In-flow antenna and LVS results are TT/LibreLane CI and klt records, not precheck. |
| **Macro halo and boundary** (SRAM macro `RM_IHPSG13_1P_256x16_c2_bm_bist`; no `FP_MACRO_HORIZONTAL_HALO` or `ROUTING_OBSTRUCTIONS` set) | The macro is inside the hierarchy the deck processes in deep mode from the top cell, so macro-internal and macro-to-stdcell geometry (spacing, width) is checked by the same rules. Boundary check, `prBoundary` present, layer allowlist, pin check against the template DEF. | The halo is a placement keep-out, not a DRC rule, so it is **not covered**: a missing halo is only visible as a geometry violation. Macro-vs-Magic mismatch below. | `precheck.py` `boundary_check`, `layer_check`, `pin_check`. The macro is part of the 419.52 x 313.74 um design the deck read. |

**Open point, not resolved here: the Magic count.** The in-flow Magic DRC
(TT/LibreLane CI) reported **29,296** errors on run 38174354943 (the R3 row
records 29,297 on an earlier run), while the KLayout deck over the same final
GDS reported none. The R3 row and the `librelane-pdn-bridge` record place all of
the Magic hits inside the macro GDS. Magic is the only DRC engine in this
comparison that disagrees. This section did not re-derive their location, and
the PDK's own LibreLane config states "Magic doesn't have CMOS5L support"
(`config.tcl:15`). That makes a Magic tech-file limitation the likely cause, which
is an inference, not a measurement.

### Recommendation

**(a) Precheck covers the layout this repo draws for DRC, so the in-flow gates
may stay off.** The reasons are the deck source and the in-flow config, not the
green run:

1. Precheck runs the PDK's own full KLayout deck (`ihp-sg13cmos5l.drc`, default
   `main` tables, `PRECHECK_DRC=false`) in deep (hierarchical) mode from the top
   cell of the final GDS, so the macro is included, and any violation fails the
   job.
2. `RUN_KLAYOUT_DRC=1` would run the same file, also in deep mode, with fewer
   rule groups (`no_recommended=true` is the only difference), so enabling it
   adds no coverage and costs wall time.
   The `gds` job already takes about 17 minutes (20:57:28Z to 21:14:29Z on run
   38174354943).
3. `ERROR_ON_MAGIC_DRC` stays 0 because Magic is not a CMOS5L-capable DRC engine
   per the PDK config, and precheck does not run it either.

Residual gaps that neither the in-flow gate nor precheck covers, and that this
recommendation does **not** claim are closed: metal density and the KLayout
antenna runset (separate decks, not included by `ihp-sg13cmos5l.drc`), net-level
shorts in the PDN bridges (covered only by the TT/LibreLane CI LVS and PSM
records), and the missing halo (no rule exists). Separately, the klt flow's PDK
commit is recorded only in prose (`layout/toolchain.json` `_comment`, `2bbec755`,
matching both actions); its per-run DRC report carries `provenance.pdk: null`
(Finding 2). None of these changes the choice between precheck and the in-flow
KLayout gate, so no follow-on issue is filed. Re-check this section when the
`tt-gds-action` pin or `tt-support-tools` tip moves; the latter is not pinned by
us.

No file other than this one changed: `.github/workflows/gds.yaml` and
`src/config.json` are untouched.
