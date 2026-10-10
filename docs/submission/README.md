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

## Deliverables

| # | Deliverable | Judge-facing artifact (target) | What exists today | State |
|---|---|---|---|---|
| D1 | Passing GDS + precheck, Tiny Tapeout flow | `gds` workflow (`.github/workflows/gds.yaml`) green on the **final** top, with the run linked from this file and from `README.md` | All four jobs (`gds`, `precheck`, `gl_test`, `viewer`) green on `main` @ `4193268`: [run 37974043486](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/37974043486), 2026-10-09. Sign-off evidence: `verification/records/librelane-gds-signoff-check/records/20261009-054750-676f8b2.md`, `verification/records/librelane-pdn-bridge/records/20261001-085017-21a2a63.md`. | **Partial.** It is green, but not on the final top. DR 0012 (control space, #135) and DR 0013 (program loading) still change the RTL, and #129 may change the tile count. Re-run and re-link after the last RTL change. |
| D2 | Architecture + ISA documentation | A standalone doc, `docs/submission/architecture.md` (to write), distilled from DR 0001. It must not be the decision record itself. | The content is spread across `spec/decision-records/0001-isa.md`, `rtl/README.md`, and the datasheet `docs/info.md` § How it works. DR 0012 and DR 0013 extend the ISA and the load path. | **Partial.** The material exists, but there is no judge-facing doc. The ISA is not frozen until #135 lands. DR 0001's Status is still **Proposed** (DR 0006, #44). |
| D3 | Assembler / toolchain + example programs | `firmware/` with a quickstart a judge can run from a fresh clone | `firmware/tools/asm.py` (the DR 0003 assembler) and its test `firmware/tools/test_asm.py`. 16 programs in `firmware/asm/` (UART TX/RX at three bauds, SPI modes 0–3, I2C Standard/Fast with repeated START and clock stretch, plus `demo_roundtrip.asm`) with committed images in `firmware/build/`. `firmware/README.md` § Cold-start invocation. | **Partial, close to ready.** The cold-start section is the quickstart, but nothing links it as the judge's entry point. The assembler has to gain the DR 0012 control-space mnemonics (#135). |
| D4 | Verification write-up | `docs/submission/verification.md` (to write), distilled from `spec/verification-plan.md` and the evidence records, and stating what is **not** covered | `spec/verification-plan.md` (Status DRAFT; its preamble line "None of the artifacts described below exist yet" is now stale). 21 record families under `verification/records/`, for example `firmware-uart`, `firmware-spi`, `firmware-i2c`, `firmware-gate-level`, `random-regression`, `no-data-dependent-latency` (formal), `post-layout-sdf-regression` and `sta-corner-sweep`. | **Partial.** The evidence is strong and append-only, but nothing reads it to a judge. Known holes that the write-up must state: #136 (I2C evidence does not run through the real `uio_oe`, so silicon cannot drive an I2C line today) and row 14 (reset/reselect, unmet). |
| D5 | AI-use write-up | [`docs/submission/ai-use.md`](ai-use.md): how agents produced the spec, RTL, firmware and verification; the Loom Builder/Judge/Curator loop; the append-only evidence rule; the klayout-tools friction issues filed; and the ratification history told honestly | **2026-10-10 (#213):** [`ai-use.md`](ai-use.md) is written. It covers who acted as the forge records it, the development loop (intended vs observed, with PR #210 as a worked example), the mechanical CI checks and their limits, append-only evidence (including the failing-then-superseded post-layout record), agent verdict vs operator decision, the ratification history (DR 0006, PR #29, the PR #48 gate, the refused PR #84 ceremony, #85), klayout-tools friction, and the limits of AI-generated verification. Before 2026-10-10 only fragments existed: `README.md` § Built agent-native and `spec/verification-plan.md` § 5. | **Partial** (2026-10-10). The document is judge-facing and current as of `main` @ `9fb7815`, but it describes a history that is still moving. Before submission, refresh the PR counts, the ratification outcome (#44, #84, #85: the spec is still **Proposed**, and no independent human review has taken place), and the open klayout-tools issues. Then mark it Ready. |
| D6 | Demo (optional) | A protocol the ISA was **not** designed for (for example 1-Wire, WS2812, DMX512 or Manchester), written as firmware after the fact with a bench: target-spec row 13. If possible, a video. | Nothing. Row 13 is "Proposed 2026-10-09 ... unmet, no firmware yet" (`spec/target-spec.md`). | **Blocked** on the frozen submission ISA (#135, with #130 deciding which protocol-neutral primitives exist). A physical-board demo also needs the host loader (#118). |
| D7 | Required external parts | A parts list in the datasheet (`docs/info.md`) and the submission, aligned with TT-recommended Pmods | Nothing beyond DR 0008 item 1 (I2C needs external pull-ups). | **Parts list written** in `docs/info.md` (#133). Pins are not yet on the TT-recommended pinouts: DR 0010 records the target plan, and the moves are #155 (after #135). |

## Risks

| # | Risk | Finding as of 2026-10-09 | State |
|---|---|---|---|
| R1 | **Flow runtime.** The 6-hour GitHub Actions limit could kill the `gds` job if #129 grows the design toward 6×4 or 8×4. The fallback is [local hardening](https://tinytapeout.com/guides/local-hardening/). | At 2×2 the `gds` job took **6 min 24 s** (run 37974043486: 18:32:55Z to 18:39:19Z), far from the limit. No larger floorplan has been hardened. Nobody has tried local hardening on any fleet host; there is no record of it in this repo. | **Open.** Before #129 commits to a larger tile count, harden it once in CI and record the wall time. Separately, prove local hardening on a fleet host and record it, before we depend on it. |
| R2 | **tt-gds-action version.** The organizers ask for the latest tt-gds-action, which carries the CMOS5L install fix. | Checked against `TinyTapeout/tt-gds-action` on 2026-10-09. `gds.yaml` uses the **branch** ref `@ihp-cmos5l` for all four jobs. Its tip is `3412659` (2026-09-14), *"fix: install ihp-sg13cmos5l from the merged IHP-Open-PDK tree #52"*, which is the CMOS5L install fix. Upstream has **no CMOS5L release tag**: the newest tags are `ttsky26d` and `ttihp26b`, and `ttihp*` is SG13G2. So the workflow is already on the latest CMOS5L code, and no edit is needed. Two caveats follow. (a) A branch ref floats, so a later upstream push changes our flow silently. Evidence records should name the action SHA a run used. (b) `ihp-cmos5l` is 3 commits behind upstream `main`, and two of those commits fix `gl_test` result detection. On `ihp-cmos5l`, `gl_test/action.yml` checks with `! grep failure results.xml`. Our pinned `cocotb==2.0.1` marks a crashed test with an `<error>` element, which that grep does not match. So a gate-level test that **errors** rather than fails could still turn the job green. `main` uses `cocotb_tools.check_results` instead. The RTL leg is not exposed, because `test.yaml` uses `scripts/check_test_results.py`. | **Open, caveat (b) needs a follow-up.** Either add a post-step to the `gl_test` job that runs `scripts/check_test_results.py` on the GL `results.xml`, or ask upstream to merge `main`'s `gl_test` fixes into `ihp-cmos5l`. Re-check the branch tip and the tags before submission. |
| R3 | **SRAM integration cross-check** against Ken Pettit's walkthrough (<https://kdp1965.github.io/ihp-um-janestreet-prism/ihp_sram_macro.html>, written 2026-09-29 for a 512×32 macro; ours is `RM_IHPSG13_1P_256x16_c2_bm_bist`). | A desk comparison was done for this tracker; it is not a measurement. **Matches:** `A_DLY` is tied to 1 and BIST is tied off (`src/protocol_program_memory.v`). Behavioural models are compiled with `-DFUNCTIONAL` for both the RTL and GL legs (`test/Makefile`, `rtl/vendor/`). There are two `PDN_MACRO_CONNECTIONS` lines, one for `VDD!` and one for `VDDARRAY!`. The PDN is Metal4-only (`FP_PDN_MULTILAYER` 0, `FP_PDN_VWIDTH` 2.1, `FP_PDN_VPITCH` 44.96 = 4 × 11.24). Precheck layers 25/0 and 16/0 are not a problem, because precheck is green. **Differs, and why:** our bridges are drawn by `src/pdn_cfg.tcl` rather than by stripe-nudging; record `librelane-pdn-bridge` reports PSM-connected nets, LVS 0, antenna 0, and worst IR drop 2.68 mV (his is 0.46 mV, on a different macro and floorplan). We set no `FP_MACRO_HORIZONTAL_HALO` and no `ROUTING_OBSTRUCTIONS`, and nothing on record shows a problem from either. **Worth a second look:** his flow runs `RUN_KLAYOUT_DRC` 1 with the CMOS5L deck in place of Magic, whereas ours has `RUN_KLAYOUT_DRC` 0 **and** `ERROR_ON_MAGIC_DRC` 0 (29,297 Magic hits, all inside the macro GDS, per the PDN-bridge record). That leaves the TT precheck's DRC as our only DRC gate. That is likely sufficient, but nobody has confirmed it. | **Partially done.** Follow-up: confirm which DRC deck `precheck` runs on CMOS5L, or turn on `RUN_KLAYOUT_DRC` as the walkthrough does. Confirm also that the IHP-Open-PDK commit the action installs matches the one precheck pins. |
| R4 | **Submission form.** It opens near the deadline. | It is not open. Watch the organizers' email and the competition blog post. | **Watch.** Re-check monthly, and weekly from 2026-12-15. |

## Order of work

1. Freeze the ISA: #135 (DR 0012), then DR 0013. D2, D3 and D6 cannot finish
   before this.
2. Settle the area: #129. If the tile count grows, harden it in CI and record
   the wall time (R1).
3. Write D5 (AI-use) now. It depends on no RTL change and is the most
   distinctive document. (2026-10-10: written as
   [`ai-use.md`](ai-use.md), #213. Refresh it before submission.)
4. Write D4 (verification) once #136 lands. List row 14 and anything else
   still unmet as such.
5. Do D6, the row-13 unplanned-protocol firmware, on the frozen ISA.
6. Do the final `gds` run on the final top (D1), link it, then update every
   row here to **Ready** with citations.
