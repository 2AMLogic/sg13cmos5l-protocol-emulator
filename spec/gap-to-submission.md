# Gap to Submission

Status: DRAFT — proposed 2026-09-14 in issue #1.
Submission deadline: **2027-01-18** (Jane Street Protocol Emulator ASIC
Competition, targeting the March 2027 IHP CMOS5L shuttle via the Tiny
Tapeout CMOS5L template).

This tracker exists so "what's left" is never re-derived from scratch —
per `CLAUDE.md`'s deadline-discipline instruction, work that cannot reach
the submitted design by the deadline is recorded here as deferred, not
folded into `rtl/` as a shortcut. Update this file (append a dated note per
row, don't silently flip a status) whenever a gap closes or a new one is
discovered.

## Spec rows (`spec/target-spec.md`)

| # | Parameter | Status | Gap |
|---|---|---|---|
| 1 | Protocols emulated in firmware | Spec only | No RTL, no firmware, no verification suite yet. DR 0001's cycle-budget sketches are the sufficiency argument; the ISA itself is unimplemented. |
| 2 | Stretch protocols | Not started | No cycle-budget sketch exists for USB 1.1 or 10BASE-T against DR 0001's ISA — per that record, they don't enter the spec until one exists. Explicitly deferred; not blocking core-protocol submission. |
| 3 | Timing determinism | Spec only | Formal property `no_data_dependent_latency` (verification-plan.md §2.1) named but not written; no RTL to check it against yet. |
| 4 | Core clock (≥50 MHz) | Spec only | No synthesis run on either flow (DR 0002) has been performed; the 50 MHz target is a draft carried over from the README, not yet confirmed achievable on CMOS5L by either flow. |
| 5 | I/O pin budget | Template-fixed, unconsumed | The `tt_um_*` wrapper interface is fixed by the Tiny Tapeout template (once it's pulled in per DR 0002/issue #2); this repo has not yet instantiated it. |
| 6 | Program storage (256×16-bit, serial load) | Spec only | RTL for program memory and the load-phase shift-in logic (DR 0001) does not exist. No cocotb test for the load protocol exists. |
| 7 | Area (≤2×2 tiles) | Unverified, open question | No synthesis has run, so no real area number exists. **Open question, not yet resolved**: the exact Tiny Tapeout tile pitch for the CMOS5L shuttle is not confirmed in this repo — needs to be pulled from the `cmos5l` branch of the template (issue #2) before "2×2 tiles" can be checked against a real number. |
| 8 | Verification (cocotb + gate-level + formal + constrained-random) | Plan only | `spec/verification-plan.md` names the shape; none of §2–§4's artifacts (formal properties, gate-level regression, constrained-random suites, reference models) exist yet. |
| 9 | Submission (Apache-2.0, TT CMOS5L template, 2027-01-18) | License set (repo-wide, per `LICENSE`); template not yet pulled in | Template wiring (`info.yaml`, `tt_um_*` top, `test/`, docs) is issue #2's scope per `CLAUDE.md`'s "Harness bootstrap," taken verbatim from the template's `cmos5l` branch. Not started. |
| 10 | UART bit-timing accuracy | Spec only | No firmware, no RTL, no reference-model comparison exists to check this against yet. |
| 11 | SPI clock ceiling and modes | Spec only | Same — no firmware/RTL/test exists yet. |
| 12 | I2C timing | Spec only | Same — no firmware/RTL/test exists yet. |

## Decision records

| Record | Status |
|---|---|
| `0001-isa.md` | Proposed, includes cycle-budget sketches for UART/SPI/I2C as required by this issue's acceptance criteria. Pending ratification. |
| `0002-flow-of-record.md` | Proposed. klayout-tools CMOS5L platform gap filed: 2AMLogic/klayout-tools#1784. Pending ratification and pending that upstream gap's resolution before klt-side iteration is usable. |
| `0003-firmware-toolchain.md` | Proposed. Assembler design fixed; `firmware/` directory and the assembler itself do not exist yet (deliberately out of scope for this ratification issue). |

## Tiny Tapeout template's own checklist

Per `CLAUDE.md`'s "Harness bootstrap" instruction, this half of the harness
is taken verbatim from the template's `cmos5l` branch, not reimplemented —
tracked here as a checklist against that source, all currently unstarted:

- [ ] `info.yaml` — project metadata, pin mapping, clock frequency declaration.
- [ ] `tt_um_*` top-level module wired to this design's core, matching the
      template's fixed pin budget (`spec/target-spec.md` row 5).
- [ ] `test/` — the template's own cocotb harness, pulled in as the
      structural basis that this repo's protocol-specific tests
      (`spec/verification-plan.md` §4) build on top of.
- [ ] `gds` / `test` / `fpga` GitHub Actions workflows — the template's
      CI, which is also the flow-of-record's actual execution mechanism
      per DR 0002.
- [ ] Docs — whatever documentation surface the template itself expects
      populated for a submission (README sections, `info.yaml` description
      fields, etc.) — exact list to be confirmed against the template
      when issue #2 pulls it in.

## rtl/ status

Empty except for its stub `README.md`, as required by this issue's
acceptance criteria ("nothing in `rtl/` yet — this issue ratifies, it does
not implement"). First RTL is scoped to a future issue once this spec and
its decision records are ratified.

## Sequencing implied by the gaps above

1. Ratify this spec and its decision records (two-key mechanism).
2. Issue #2: pull in the Tiny Tapeout template (`cmos5l` branch, verbatim)
   and port the `klt`/Yosys/OpenROAD harness shape from
   `2AMLogic/sky130-modexp`, per `CLAUDE.md`. Resolves the row-5 template-
   pin-budget consumption and the row-7 tile-pitch open question.
3. Track 2AMLogic/klayout-tools#1784 (CMOS5L platform gap) — does not block
   step 2's template-flow work, but blocks klt-side iteration convenience
   per DR 0002.
4. First RTL issue(s): the core datapath per DR 0001 (registers, pin ports,
   program memory + load-phase logic, fetch/execute).
5. Firmware issue(s) per DR 0003: the assembler, then the UART/SPI/I2C
   `.asm` programs from DR 0001's sketches.
6. Verification issue(s) per `spec/verification-plan.md`: formal
   properties (§2), gate-level regression wiring (§3), constrained-random
   suites + reference models (§4).
7. Submission packaging against the template's checklist above, well
   before 2027-01-18 to leave margin for the flow-of-record's own CI
   turnaround and any late-discovered gap.

Every step above is a future issue, not a commitment made by this one.
