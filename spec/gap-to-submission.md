# Gap to Submission

Status: DRAFT — proposed 2026-09-14 in issue #1. **2026-09-21:** the spec
rows and decision records this tracker measures against were **ratified**
via the program's two-key mechanism (`spec/target-spec.md` Status:
RATIFIED, per `spec/decision-records/0004-target-spec-ratification.md`);
this file's own `DRAFT` label above refers to that pre-ratification spec
state and is superseded by it. The tracker itself stays the live
evidence/progress record, unchanged in role.
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
| 4 | Core clock (≥50 MHz) | Both flows have now synthesized the stub; timing still unconfirmed | No synthesis run on either flow (DR 0002) has been performed; the 50 MHz target is a draft carried over from the README, not yet confirmed achievable on CMOS5L by either flow. — **2026-09-14 (issue #2):** one flow has now run, on the *harness-bootstrap stub* top, not the ISA core: Yosys against `sg13cmos5l_stdcell`, 16 cells, record `verification/records/synthesis-baseline/records/20260914-032200-7e4a21a.md`. That run reports **cell count only, not timing** — the direct-Yosys fallback it had to use (klayout-tools#1786) neither reads nor enforces `constraints.clock_period_ns`. The LibreLane leg of DR 0002's two flows has still produced no number at all (row 9). 50 MHz therefore remains unconfirmed on **both** flows. — **2026-09-14 (issue #5, PR #11):** the LibreLane leg has now run too (record `20260914-203044-45af1c2.md`, superseding the record above): 32 cells at its own `Yosys.Synthesis` stage (the correct apples-to-apples comparison point; the two flows agree on substantive logic and diverge only on tie-cell insertion — see that record for the full reconciliation). **Still cell counts only, not timing** — neither flow's run reports a clock-period/STA result, so 50 MHz remains unconfirmed on both flows even though both now have a synthesis data point. — **2026-09-21 (issue #20, first increment; record `verification/records/sta-corner-sweep/records/20260921-194500-7678c06.md`):** the klt-side *timing evidence harness* now exists and has been exercised end to end. The corner set this block is held to is now **declared**: all six shipped `sg13cmos5l_stdcell` liberty corners (`slow_1p08V_125C`, `slow_1p35V_125C`, `typ_1p20V_25C`, `typ_1p50V_25C`, `fast_1p32V_m40C`, `fast_1p65V_m40C`), enumerated in `flow/run-sta-corner-sweep.sh`. The target spec and its decision records are now **ratified** (issue #17 / PR #29, earlier 2026-09-21 — see `0004-target-spec-ratification.md`), so T1 item 5's verdicts against them are no longer provisional; folding the corner matrix into a spec decision record of its own is tracked follow-up alongside that ratification. `klt sta` (verilog mode, wire load `1k`/`top`) ran all six corners over one freshly synthesized netlist at the 20 ns (50 MHz) constraint, each returning `timing_status: "constrained"` with non-negative setup and hold slack. **Those numbers are the harness-bootstrap STUB's, cited only as toolchain bring-up — they are explicitly NOT row-4 evidence**, per issue #20's own note ("a 16-cell stub closing timing says nothing about the core"); the sweep is a pre-layout `netlist_estimate` besides (no routed DEF exists on this flow yet). Enabling change: `layout/toolchain.json`'s klt pin bumped to 1d964cf4 — `klt sta` needs a commit past klayout-tools#1861 to resolve IHP's single-underscore liberty naming (pre-#1861 `klt sta` is the last verb still carrying the #1786 bug). Plain `klt synthesize` now drives the synthesis leg (see the `0002-flow-of-record.md` row below). **Status unchanged: 50 MHz remains unconfirmed for the ISA core on both flows.** The core-RTL sweep — issue #20's remaining scope — is a one-command re-run of that harness once the ISA core top is complete: #19's program memory landed (PR #30) as this PR was being judged, and #18's core datapath is still in flight at this writing, so there is not yet a real core to sweep (`rtl/protocol_program_memory.v` stand-alone is real RTL but not the ISA core top the issue's note names); `info.yaml`'s `clock_hz` reconciliation is deferred with it. |
| 5 | I/O pin budget | Template-fixed; instantiated by the stub top | The `tt_um_*` wrapper interface is fixed by the Tiny Tapeout template (once it's pulled in per DR 0002/issue #2); this repo has not yet instantiated it. — **2026-09-14 (issue #2):** now instantiated. `src/tt_um_2amlogic_protocol_emulator.v` drives the full fixed budget (`clk`/`rst_n`/`ena`, `ui_in[7:0]`, `uo_out[7:0]`, `uio_in`/`uio_out`/`uio_oe`) and `info.yaml` declares the pinout. It is a **stub** (`ui_in` registered onto `uo_out`, `uio_oe = 0`), so the budget is consumed *structurally*; assigning protocol roles to specific pins is a later decision record, and `info.yaml`'s pinout labels say so explicitly. |
| 6 | Program storage (256×16-bit, serial load) | RTL + cocotb load test exist and pass (stand-alone); top-level integration and a demonstrated clock still open | RTL for program memory and the load-phase shift-in logic (DR 0001) does not exist. No cocotb test for the load protocol exists. — **2026-09-21 (issue #19):** both halves of "Spec only" are now built and verified stand-alone: `rtl/protocol_program_memory.v` implements DR 0001's 256×16-bit program memory + serial load-phase shift-in (MODE latched at reset release on `ui_in[7]`, bits shifted MSB-first from `ui_in[0]` one per clock edge, a word committed on its 16th bit's own edge at an auto-incrementing address from 0, mid-word drop discarded, saturation at 256 words, no mid-run re-entry without a fresh reset), and `verification/test_program_memory.py` is the row's "Checked by" cocotb load test — 6/6 directed tests PASS via `klt functional-verification` at the pinned klt (record `verification/records/program-load-phase/records/20260921-185910-248bf61.md`), loading known programs serially and reading them back through the fetch port the core will execute from. Load timing is recorded **in cycles**, asserted cycle-exact by the bench (1 mode-sampling + 4096 bit + 1 exit edge = 4097 edges, 16 per word, for the full 256-word load; 81.94 µs at the draft 50 MHz target by arithmetic only) — **no silicon clock is claimed**: no STA run exists on either flow for this cell library (row 4 open on both flows; even the newer unpinned klt build corroboration in the record reports `timing: null` for `sg13cmos5l_stdcell`), so row 6 is not claimed at any demonstrated clock. What remains open for this row: (1) top-level wiring of the module into `tt_um_2amlogic_protocol_emulator` (`ui_in[7]`→`mode_pin`, `ui_in[0]`→`serial_in`, PC→`fetch_addr`, `run_phase` gating the core's PC reset — the interface contract is documented in the module header and `rtl/README.md`) is the core-datapath issue #18's integration step, and the module is stand-alone-verified until then; (2) the flip-flop memory's cost is now a real number — 11,603 cells / 312,062.8896 liberty µm² on the iteration flow (`klt synthesize` attempt + Yosys stopgap per the synthesis-baseline leg of the record, corroborated by an unpinned local klt build with an identical histogram, flow attribution in the record) — to be weighed against row 7's still-unverified area budget; the row 6 stretch item (a Tiny Tapeout SRAM macro instead of flip-flops, if area allows) remains untaken. |
| 7 | Area (≤2×2 tiles) | Tile pitch confirmed; area still unverified | No synthesis has run, so no real area number exists. **Open question, not yet resolved**: the exact Tiny Tapeout tile pitch for the CMOS5L shuttle is not confirmed in this repo — needs to be pulled from the `cmos5l` branch of the template (issue #2) before "2×2 tiles" can be checked against a real number. — **2026-09-14 (issue #2): the tile-pitch half of this question is resolved.** The template's own `info.yaml`, now in this repo verbatim from the `cmos5l` branch, states a single tile is **about 167 × 108 µm**, so a ≤2×2-tile budget is on the order of **334 × 216 µm** (the template states no inter-tile spacing or margin, so treat that as the order of magnitude, not an exact die area). The stub declares `tiles: "1x1"`. **The area half is still open**: the only synthesis that has run reports 537.0624 liberty-area units for the *stub's cells* (record `20260914-032200-7e4a21a`) with no floorplan or P&R, and the LibreLane flow that would produce a real die area has never run (row 9). — **2026-09-14 (issue #5, PR #11):** the LibreLane flow has now run end to end (`gds` workflow, run `34884059362`), through placement and fill insertion, but it produced *cell-count* checkpoints (32 / 53 / 2340 cells at successive stages, record `20260914-203044-45af1c2.md`), not a floorplan or die-area report. **The area half remains genuinely open** — no run of either flow has reported a die area or utilization-against-tile-budget number yet. |
| 8 | Verification (cocotb + gate-level + formal + constrained-random) | Plan only; cocotb harnesses bootstrapped, gate-level now passing | `spec/verification-plan.md` names the shape; none of §2–§4's artifacts (formal properties, gate-level regression, constrained-random suites, reference models) exist yet. — **2026-09-14 (issue #2):** two cocotb harnesses now exist against the stub top — `test/` (the template's own, driven by the `test` workflow, green on `main`) and `verification/` (this program's own, driven by `klt functional-verification`, with one passing append-only record `20260914-031931-7e4a21a`). §3's **gate-level regression is wired but cannot run**: the template's `gl_test` job declares `needs: gds`, and `gds` fails upstream before producing a netlist (row 9). §2 formal properties and §4 constrained-random suites + reference models still do not exist. — **2026-09-14 (issue #10, PR #12; re-confirmed issue #2):** §3's gate-level regression **now runs and passes**. The blocker above (`gds` failing before a netlist existed) cleared, and a separate upstream gap in `test/Makefile` (missing `sg13cmos5l_udp.v` UDP source, inherited verbatim from the template) was patched — see `layout/README.md`. Latest confirmation: `gds`-workflow run `34905475502` (`main` @ `599fd0e`) reports `gl_test: success`. §2 formal properties and §4 constrained-random suites + reference models still do not exist — unchanged, and still future-issue scope. |
| 9 | Submission (Apache-2.0, TT CMOS5L template, 2027-01-18) | License set (repo-wide, per `LICENSE`); template pulled in; sign-off flow now green end to end | Template wiring (`info.yaml`, `tt_um_*` top, `test/`, docs) is issue #2's scope per `CLAUDE.md`'s "Harness bootstrap," taken verbatim from the template's `cmos5l` branch. Not started. — **2026-09-14 (issue #2, PR #7):** template wiring **landed**, verbatim from the `cmos5l` branch — `info.yaml`, `src/tt_um_2amlogic_protocol_emulator.v`, `src/config.json`, `test/`, `docs/info.md`, `.devcontainer/`, and the `gds`/`test`/`fpga`/`docs` workflows (checklist below). `test` and `docs` are green on `main`; **`gds` fails deterministically** in `tt-gds-action`'s PDK-install step (upstream `TinyTapeout/tt-gds-action#52`, open as of 2026-09-14; re-confirmed on `main` at `a3585ea`), so the competition's sign-off flow has never produced a GDS and `precheck`/`gl_test`/`viewer` are all skipped. Not fixable from this side without forking the template — full analysis in `layout/README.md`. — **2026-09-14 (issues #5/#10/#2, PRs #11/#12, this re-check):** the PDK-install symptom above stopped reproducing (confirmed stale in `layout/README.md`, run `34884059362`), `gl_test` was fixed (row 8), and the last remaining gap — GitHub Pages not enabled, blocking the `viewer` job — has now been cleared by the operator (`gh api .../pages` returns a populated config, not `404`). **Confirmed on run [`34905475502`](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/34905475502) (`main` @ `599fd0e`, 2026-09-14T22:43Z): all four `gds`-workflow jobs — `gds`, `precheck`, `gl_test`, `viewer` — succeed.** The competition's sign-off flow is therefore now fully exercised end to end on the harness-bootstrap stub; `TinyTapeout/tt-gds-action#52` remains open upstream but no longer reproduces here (unreconciled — see `layout/README.md`). Nothing further is blocked on this row for the stub; the ISA itself (rows 1, 3, 6, 10–12) is what future issues still need to build. |
| 10 | UART bit-timing accuracy | Spec only | No firmware, no RTL, no reference-model comparison exists to check this against yet. |
| 11 | SPI clock ceiling and modes | Spec only | Same — no firmware/RTL/test exists yet. |
| 12 | I2C timing | Spec only | Same — no firmware/RTL/test exists yet. |

## Decision records

| Record | Status |
|---|---|
| `0001-isa.md` | Proposed, includes cycle-budget sketches for UART/SPI/I2C as required by this issue's acceptance criteria. Pending ratification. — **2026-09-21:** **Ratified** via the two-key mechanism, carried into force with `spec/target-spec.md` (per `decision-records/0004-target-spec-ratification.md`, issue #17). The cycle-budget sketches are now bound as the row-1/row-3/row-6 sufficiency evidence — unmet, not carried as met. |
| `0002-flow-of-record.md` | Proposed. klayout-tools CMOS5L platform gap filed: 2AMLogic/klayout-tools#1784. Pending ratification and pending that upstream gap's resolution before klt-side iteration is usable. **2026-09-14 (issue #2):** a second klayout-tools gap was hit and filed while porting the synthesis leg — [2AMLogic/klayout-tools#1786](https://github.com/2AMLogic/klayout-tools/issues/1786): `klt synthesize`'s liberty resolver hardcodes a SkyWater-style `<cell_library>__<corner>.lib` filename, while IHP's SG13 PDKs ship `<cell_library>_<corner>.lib`. Interim workaround committed as `flow/run_synthesize_direct_yosys.py` (same pass sequence, liberty resolved directly); retire it for a plain `klt synthesize` call when #1786 closes — no request-file change needed. Separately, DR 0002's *other* flow (LibreLane via the template's `gds` workflow) is itself blocked by `TinyTapeout/tt-gds-action#52`, so **neither** flow is currently fully exercised. — **2026-09-21:** **Ratified** via the two-key mechanism (per `decision-records/0004-target-spec-ratification.md`, issue #17). Since the earlier notes: both upstream klayout-tools gaps this record tracks are **closed** ([#1784](https://github.com/2AMLogic/klayout-tools/issues/1784) platform entry; [#1786](https://github.com/2AMLogic/klayout-tools/issues/1786) corner-naming resolver — both verified live 2026-09-21), and the LibreLane leg has been exercised end to end (green `gds` workflow run `34905475502`, row 9), so the "neither flow fully exercised" state above is superseded. The flow-of-record policy itself binds unchanged; retiring the interim direct-Yosys workaround for a plain `klt synthesize` call remains follow-up implementation work, not part of the ratification. | — **2026-09-21 (issue #20):** that retirement follow-up is done: with `layout/toolchain.json`'s klt pin at 1d964cf4, plain `klt synthesize flow/synthesize-protocol-emulator.json --pdk ihp-sg13cmos5l` drives the synthesis leg itself (verified live; `flow/run-sta-corner-sweep.sh` uses exactly that route), and the interim direct-Yosys script is **retired from the active path** — retained committed for record history only, since the synthesis-baseline records cite it by content hash. |
| `0003-firmware-toolchain.md` | Proposed. Assembler design fixed; `firmware/` directory and the assembler itself do not exist yet (deliberately out of scope for this ratification issue). — **2026-09-21:** **Ratified** via the two-key mechanism, carried into force with `spec/target-spec.md` (per `decision-records/0004-target-spec-ratification.md`, issue #17). `firmware/` and the assembler remain future implementation work (issues #22, #23), exactly as this record scoped. |

## Tiny Tapeout template's own checklist

Per `CLAUDE.md`'s "Harness bootstrap" instruction, this half of the harness
is taken verbatim from the template's `cmos5l` branch, not reimplemented —
tracked here as a checklist against that source. Originally recorded (2026-09-14,
issue #1) as *all unstarted*; **updated 2026-09-14 after issue #2 / PR #7 landed
the wiring** — every file is now present, but "present" is not "signed off":
the `gds` workflow that would exercise them fails upstream (row 9). **Further
updated 2026-09-14 (issues #5/#10/#2, PRs #11/#12, this re-check): the `gds`
workflow now passes end to end on `main` (run `34905475502`) — every item on
this checklist is both present and signed off; nothing remains open here.**

- [x] `info.yaml` — project metadata, pin mapping, clock frequency declaration.
      *Landed 2026-09-14; populated for the stub top (`tiles: "1x1"`,
      `clock_hz: 50000000`, generic stub pinout labels). `tiles`/`pinout`/`clock_hz`
      are placeholders sized for the stub, not a ratified budget — the file says so.*
- [x] `tt_um_*` top-level module wired to this design's core, matching the
      template's fixed pin budget (`spec/target-spec.md` row 5).
      *Landed as `src/tt_um_2amlogic_protocol_emulator.v` — wired to the pin
      budget, but there is no core yet: it registers `ui_in` onto `uo_out` and
      holds `uio_oe = 0`. Row 5 covers the distinction.*
- [x] `test/` — the template's own cocotb harness, pulled in as the
      structural basis that this repo's protocol-specific tests
      (`spec/verification-plan.md` §4) build on top of.
      *Landed verbatim (`test/Makefile`, `test/tb.v`, `test/test.py`,
      `test/requirements.txt`); the `test` workflow is green on `main`.*
- [x] `gds` / `test` / `fpga` GitHub Actions workflows — the template's
      CI, which is also the flow-of-record's actual execution mechanism
      per DR 0002.
      *All present verbatim (plus the template's `docs` workflow).
      `test` and `docs` pass on `main`. **2026-09-14 update: `gds` now
      passes end to end too** — the upstream PDK-install symptom
      (`TinyTapeout/tt-gds-action#52`) stopped reproducing, `gl_test` was
      fixed (issue #10, a one-line `test/Makefile` patch for a template gap,
      see `layout/README.md`), and the operator enabled GitHub Pages,
      clearing the last `viewer` gap. Confirmed on run `34905475502`
      (`main` @ `599fd0e`): `gds`/`precheck`/`gl_test`/`viewer` all succeed.
      Per `CLAUDE.md` these files stay verbatim — `gl_test`'s fix was a
      necessary patch to an upstream template bug, not a deviation; no other
      local patch was needed.*
- [x] Docs — whatever documentation surface the template itself expects
      populated for a submission (README sections, `info.yaml` description
      fields, etc.) — exact list to be confirmed against the template
      when issue #2 pulls it in.
      *Confirmed list: `docs/info.md` (the template's project-documentation
      page) plus `info.yaml`'s `title`/`description`/`author` fields. Both
      populated for the stub; the `docs` workflow renders them and is green on
      `main`. They describe a stub and will need rewriting once the ISA lands.*

**Nothing remains open on this checklist as of 2026-09-14.** The green `gds`
run and the gate-level regression (`gl_test`) it gates both now pass (issues
#2/#10), and the LibreLane cell count beside the Yosys one has been backfilled
(issue #5, closed via PR #11). This checklist item of issue #2 is complete;
remaining gap-to-submission work is scoped to the ISA/firmware/verification
rows above, not to this checklist.

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
   **2026-09-14: mostly done (PR #7)** — both resolutions it predicted landed
   (row 5 consumed, row-7 tile pitch confirmed at ~167 × 108 µm per tile).
   Issue #2 stays open on the LibreLane half: a green `gds` run and the
   gate-level regression behind it, blocked on `TinyTapeout/tt-gds-action#52`
   (see the blocker note below step 3), plus the LibreLane cell count (issue #5).
   **2026-09-14, later the same day: fully done.** The `tt-gds-action#52`
   symptom stopped reproducing, `gl_test` was fixed (issue #10, PR #12), the
   LibreLane cell count was backfilled (issue #5, PR #11), and the operator
   enabled GitHub Pages, clearing the last `viewer` gap. `gds`-workflow run
   `34905475502` (`main` @ `599fd0e`) is green end to end — issue #2's harness-
   bootstrap scope is complete.
3. Track 2AMLogic/klayout-tools#1784 (CMOS5L platform gap) — does not block
   step 2's template-flow work, but blocks klt-side iteration convenience
   per DR 0002. **2026-09-14:** add 2AMLogic/klayout-tools#1786 (liberty
   filename convention) to the same watch — `flow/run_synthesize_direct_yosys.py`
   is the interim workaround and should be retired when it closes.
   - **Blocker, discovered 2026-09-14 (issue #2), now cleared:**
     `TinyTapeout/tt-gds-action#52` — the template's `gds` workflow could not
     install the IHP PDK, so the competition's own sign-off flow produced
     nothing and `precheck`/`gl_test`/`viewer` never ran. Third-party issue,
     already filed upstream, nothing to file from here; resolved with zero
     changes on this side (the exit-128 install symptom stopped reproducing
     on its own — see `layout/README.md`; `tt-gds-action#52` itself remains
     open upstream, unreconciled). Previously blocked rows 4 (LibreLane
     timing — cell count now in hand, timing still separately open), 7 (real
     die area — cell-stage data now in hand, floorplan/die-area still open),
     8 (gate-level regression — now passing), and 9 (a signed-off submission
     artifact — now produced end to end). **2026-09-14, same day:** all four
     runs clean on run `34905475502`; re-probe before assuming a regression.
     Full analysis: `layout/README.md`.
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
