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
| 4 | Core clock (≥50 MHz) | One flow has synthesized a stub; timing still unconfirmed | No synthesis run on either flow (DR 0002) has been performed; the 50 MHz target is a draft carried over from the README, not yet confirmed achievable on CMOS5L by either flow. — **2026-09-14 (issue #2):** one flow has now run, on the *harness-bootstrap stub* top, not the ISA core: Yosys against `sg13cmos5l_stdcell`, 16 cells, record `verification/records/synthesis-baseline/records/20260914-032200-7e4a21a.md`. That run reports **cell count only, not timing** — the direct-Yosys fallback it had to use (klayout-tools#1786) neither reads nor enforces `constraints.clock_period_ns`. The LibreLane leg of DR 0002's two flows has still produced no number at all (row 9). 50 MHz therefore remains unconfirmed on **both** flows. |
| 5 | I/O pin budget | Template-fixed; instantiated by the stub top | The `tt_um_*` wrapper interface is fixed by the Tiny Tapeout template (once it's pulled in per DR 0002/issue #2); this repo has not yet instantiated it. — **2026-09-14 (issue #2):** now instantiated. `src/tt_um_2amlogic_protocol_emulator.v` drives the full fixed budget (`clk`/`rst_n`/`ena`, `ui_in[7:0]`, `uo_out[7:0]`, `uio_in`/`uio_out`/`uio_oe`) and `info.yaml` declares the pinout. It is a **stub** (`ui_in` registered onto `uo_out`, `uio_oe = 0`), so the budget is consumed *structurally*; assigning protocol roles to specific pins is a later decision record, and `info.yaml`'s pinout labels say so explicitly. |
| 6 | Program storage (256×16-bit, serial load) | Spec only | RTL for program memory and the load-phase shift-in logic (DR 0001) does not exist. No cocotb test for the load protocol exists. |
| 7 | Area (≤2×2 tiles) | Tile pitch confirmed; area still unverified | No synthesis has run, so no real area number exists. **Open question, not yet resolved**: the exact Tiny Tapeout tile pitch for the CMOS5L shuttle is not confirmed in this repo — needs to be pulled from the `cmos5l` branch of the template (issue #2) before "2×2 tiles" can be checked against a real number. — **2026-09-14 (issue #2): the tile-pitch half of this question is resolved.** The template's own `info.yaml`, now in this repo verbatim from the `cmos5l` branch, states a single tile is **about 167 × 108 µm**, so a ≤2×2-tile budget is on the order of **334 × 216 µm** (the template states no inter-tile spacing or margin, so treat that as the order of magnitude, not an exact die area). The stub declares `tiles: "1x1"`. **The area half is still open**: the only synthesis that has run reports 537.0624 liberty-area units for the *stub's cells* (record `20260914-032200-7e4a21a`) with no floorplan or P&R, and the LibreLane flow that would produce a real die area has never run (row 9). |
| 8 | Verification (cocotb + gate-level + formal + constrained-random) | Plan only; cocotb harnesses bootstrapped, gate-level blocked upstream | `spec/verification-plan.md` names the shape; none of §2–§4's artifacts (formal properties, gate-level regression, constrained-random suites, reference models) exist yet. — **2026-09-14 (issue #2):** two cocotb harnesses now exist against the stub top — `test/` (the template's own, driven by the `test` workflow, green on `main`) and `verification/` (this program's own, driven by `klt functional-verification`, with one passing append-only record `20260914-031931-7e4a21a`). §3's **gate-level regression is wired but cannot run**: the template's `gl_test` job declares `needs: gds`, and `gds` fails upstream before producing a netlist (row 9). §2 formal properties and §4 constrained-random suites + reference models still do not exist. |
| 9 | Submission (Apache-2.0, TT CMOS5L template, 2027-01-18) | License set (repo-wide, per `LICENSE`); template pulled in (stub); sign-off flow blocked upstream | Template wiring (`info.yaml`, `tt_um_*` top, `test/`, docs) is issue #2's scope per `CLAUDE.md`'s "Harness bootstrap," taken verbatim from the template's `cmos5l` branch. Not started. — **2026-09-14 (issue #2, PR #7):** template wiring **landed**, verbatim from the `cmos5l` branch — `info.yaml`, `src/tt_um_2amlogic_protocol_emulator.v`, `src/config.json`, `test/`, `docs/info.md`, `.devcontainer/`, and the `gds`/`test`/`fpga`/`docs` workflows (checklist below). `test` and `docs` are green on `main`; **`gds` fails deterministically** in `tt-gds-action`'s PDK-install step (upstream `TinyTapeout/tt-gds-action#52`, open as of 2026-09-14; re-confirmed on `main` at `a3585ea`), so the competition's sign-off flow has never produced a GDS and `precheck`/`gl_test`/`viewer` are all skipped. Not fixable from this side without forking the template — full analysis in `layout/README.md`. |
| 10 | UART bit-timing accuracy | Spec only | No firmware, no RTL, no reference-model comparison exists to check this against yet. |
| 11 | SPI clock ceiling and modes | Spec only | Same — no firmware/RTL/test exists yet. |
| 12 | I2C timing | Spec only | Same — no firmware/RTL/test exists yet. |

## Decision records

| Record | Status |
|---|---|
| `0001-isa.md` | Proposed, includes cycle-budget sketches for UART/SPI/I2C as required by this issue's acceptance criteria. Pending ratification. |
| `0002-flow-of-record.md` | Proposed. klayout-tools CMOS5L platform gap filed: 2AMLogic/klayout-tools#1784. Pending ratification and pending that upstream gap's resolution before klt-side iteration is usable. **2026-09-14 (issue #2):** a second klayout-tools gap was hit and filed while porting the synthesis leg — [2AMLogic/klayout-tools#1786](https://github.com/2AMLogic/klayout-tools/issues/1786): `klt synthesize`'s liberty resolver hardcodes a SkyWater-style `<cell_library>__<corner>.lib` filename, while IHP's SG13 PDKs ship `<cell_library>_<corner>.lib`. Interim workaround committed as `flow/run_synthesize_direct_yosys.py` (same pass sequence, liberty resolved directly); retire it for a plain `klt synthesize` call when #1786 closes — no request-file change needed. Separately, DR 0002's *other* flow (LibreLane via the template's `gds` workflow) is itself blocked by `TinyTapeout/tt-gds-action#52`, so **neither** flow is currently fully exercised. |
| `0003-firmware-toolchain.md` | Proposed. Assembler design fixed; `firmware/` directory and the assembler itself do not exist yet (deliberately out of scope for this ratification issue). |

## Tiny Tapeout template's own checklist

Per `CLAUDE.md`'s "Harness bootstrap" instruction, this half of the harness
is taken verbatim from the template's `cmos5l` branch, not reimplemented —
tracked here as a checklist against that source. Originally recorded (2026-09-14,
issue #1) as *all unstarted*; **updated 2026-09-14 after issue #2 / PR #7 landed
the wiring** — every file is now present, but "present" is not "signed off":
the `gds` workflow that would exercise them fails upstream (row 9).

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
      `test` and `docs` pass on `main`; **`gds` fails upstream**
      (`TinyTapeout/tt-gds-action#52`), taking `precheck`/`gl_test`/`viewer`
      with it. Per `CLAUDE.md` these files stay verbatim — no local patch.*
- [x] Docs — whatever documentation surface the template itself expects
      populated for a submission (README sections, `info.yaml` description
      fields, etc.) — exact list to be confirmed against the template
      when issue #2 pulls it in.
      *Confirmed list: `docs/info.md` (the template's project-documentation
      page) plus `info.yaml`'s `title`/`description`/`author` fields. Both
      populated for the stub; the `docs` workflow renders them and is green on
      `main`. They describe a stub and will need rewriting once the ISA lands.*

**Still open on this checklist** (tracked on issue #2, not re-filed here):
a green `gds` run and the gate-level regression (`gl_test`) that depends on it,
both waiting on the upstream fix; and the LibreLane cell count that would sit
beside the Yosys one (issue #5).

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
3. Track 2AMLogic/klayout-tools#1784 (CMOS5L platform gap) — does not block
   step 2's template-flow work, but blocks klt-side iteration convenience
   per DR 0002. **2026-09-14:** add 2AMLogic/klayout-tools#1786 (liberty
   filename convention) to the same watch — `flow/run_synthesize_direct_yosys.py`
   is the interim workaround and should be retired when it closes.
   - **New blocker, discovered 2026-09-14 (issue #2):**
     `TinyTapeout/tt-gds-action#52` — the template's `gds` workflow cannot
     install the IHP PDK, so the competition's own sign-off flow produces
     nothing and `precheck`/`gl_test`/`viewer` never run. Third-party issue,
     already filed upstream, nothing to file from here; resolves with zero
     changes on this side. Blocks rows 4 (LibreLane timing), 7 (real die
     area), 8 (gate-level regression), and 9 (a signed-off submission
     artifact). Re-probe it before assuming any of those are still stuck.
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
