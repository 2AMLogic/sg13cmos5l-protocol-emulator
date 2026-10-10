# Work Log

Chronological record of merged pull requests and closed issues, newest first.

### 2026-10-10

- **PR #202**: Run the post-layout SDF bench at the SDC's IO timing: 12 pass + 1 skip at all corners (#106)
- **PR #204**: Verification: independent ISA reference simulator with per-edge lockstep co-simulation (#152)
- **PR #200**: Warm start refuses a zero signature (DR 0013 F1, option 4)
- **PR #199**: Repair the SRAM A_REN max-slew with a LibreLane-only drive buffer (#173)
- **PR #198**: spec: fix six of the PR #84 two-key findings (SPI sketch, row 4 State, rows 1/2/7/8/9/10/12 citations)
- **PR #197**: docs: one device on the uio header at a time (#196)
- **PR #188**: feat: SPI-flash boot from the Tiny Tapeout QSPI Pmod (DR 0013 strap 01) with an independent flash model (#140)
- **PR #194**: Add stale-record report and re-mint helper (#193)
- **PR #191**: Host-side direct-load pin-sequence generator and RTL replay (#118)
- **PR #190**: Move UART RX from ui_in[0] to ui_in[1] (DR 0010 target pin plan)
- **PR #189**: check_records.py hardening: gitlinks and meta.experiment (#187)
- **PR #186**: CI: measure formal gate on hosted runner; keep manual-dispatch (#122)
- **PR #185**: verification: re-run klt DRC/LVS on the current GDS and re-point signoff items 3, 4, 7 (#158)
- **PR #183**: check_records.py: key the freshness exemption on (experiment, record_id) and re-mint the 3 hidden-stale records
- **PR #181**: Move SPI and I2C firmware to the Tiny Tapeout Pmod pins (DR 0010 target; part of #155)
- **PR #180**: spec: target-spec rows 1, 8, 12 cite live I2C records and the pad model (#164)
- **PR #179**: feat: grade UART frame pitch so 0xFF frames cannot hide drift (#97)
- **PR #176**: Reset/power-up/reselect: gate-level X and seeded-random init bench, reset-coverage listing (row 14)
- **PR #175**: spec: DR 0012 area figures, I2C preamble order, and the RTL's choices
- **PR #174**: fix(asm): WCTL RUN makes every address a control-state merge point (#161)
- **PR #163**: test: run the I2C evidence through the real uio_oe on a silicon-true pad model
- **Issue #106** (closed): Post-layout SDF: make the core bench drive/sample alignment SDF-aware (annotated run passes 1/13)
- **Issue #152** (closed): Verification: independent ISA reference simulator with lockstep co-simulation against the core RTL
- **Issue #168** (closed): DR 0013 warm start: the all-zero image verifies (CRC seed 0x0000); decide seed, magic word, or accept
- **Issue #173** (closed): LibreLane max-slew violation is on the SRAM macro's A_REN pin (new with the boot ROM read gate, #138)
- **Issue #196** (closed): Design: the QSPI flash Pmod (strap 01) and the SPI/I2C profiles share uio[0..3]; decide the rule and record it in DR 0010/0013 and info.md
- **Issue #124** (closed): Auditor: retain detached scratch checkout force-op guard
- **Issue #140** (closed): Boot firmware: SPI-flash boot from the Tiny Tapeout QSPI Pmod with an independent flash model
- **Issue #193** (closed): Records: re-mint helper and stale-record report for check_records.py freshness failures
- **Issue #187** (closed): check_records.py hardening: clean error for gitlinks under records/, check meta.experiment against directory
- **Issue #184** (closed): Re-mint PR #181's stale evidence records after rebasing onto main
- **Issue #178** (closed): Move UART RX from ui_in[0] to ui_in[1] (DR 0010 target pin plan; UART half of #155)
- **Issue #177** (closed): Re-mint the records that hash firmware/tools/asm.py on the post-#163/#175 tree (follow-up to PR #174)
- **Issue #164** (closed): target-spec rows 1, 8 and 12: State cells still cite superseded I2C records and say uio_oe is fixed to 0
- **Issue #161** (closed): asm lint: a WCTL RUN landing between a control-register rewrite and its readback is not treated as tainted
- **Issue #159** (closed): DR 0012: correct the area estimate, state the I2C preamble order, and decide the points the RTL had to choose
- **Issue #158** (closed): Signoff manifest, klt DRC/LVS and the gap tracker still describe the layout from before the control space
- **Issue #157** (closed): check_records.py: freshness exemption keyed on record ID alone hides stale live records in other experiments
- **Issue #155** (closed): Move firmware profiles to the Tiny Tapeout-aligned pin plan after #135 (UART RX ui_in[1], SPI and I2C on the uio Pmod rows)
- **Issue #136** (closed): Verification: silicon-true uio pad model; re-run I2C evidence through the real uio_oe (today silicon cannot drive an I2C line)
- **Issue #131** (closed): Verification: prove every flop reaches a known state from rst_n alone (gate-level X/random-init run; post-deselect safe idle)
- **Issue #123** (closed): Auditor: guard rejects scoped worktree writes through shell variables
- **Issue #122** (closed): CI: assess provisioning the formal mutant gate
- **Issue #118** (closed): Host-side program loader: generate the load-phase pin sequence from firmware images for a physical Tiny Tapeout board (none exists)
- **Issue #97** (closed): UART reference model: drift check is blind to frames with no late edge (e.g. payload 0xFF)

### 2026-10-09

- **PR #171**: spec: reconcile DR 0015 with the baseline-only DR 0011
- **PR #170**: docs(spec): record in DR 0010 that the UART RX debug writes drive no pad under DR 0012
- **PR #169**: feat: boot ROM, fetch-source switch and warm start; MODE-low no longer runs uninitialized SRAM (DR 0013 layer 2)
- **Issue #156** (closed): DR 0015 still describes DR 0011 as a defer verdict; reconcile it with the baseline-only DR 0011
- **Issue #154** (closed): UART RX bench-debug writes to UIO_OUT would pull uio[0]/uio[7] low under an open-drain mask
- **Issue #138** (closed): DR 0013 layer 2: boot ROM + fetch-source switch + warm start; MODE-low no longer runs uninitialized SRAM (row 14c)

### 2026-10-09

- **PR #162**: refactor(verification): share firmware hex and cycle-report parsers
- **PR #160**: feat: implement DR 0012 control space with runtime uio direction
- **PR #128**: docs(spec): DR 0011 current-ISA baseline schedules for low-speed USB and 10BASE-T (verdict in DR 0015)
- **PR #148**: docs(spec): required external parts, TT Pmod pinout alignment, pad-speed claims unverified
- **PR #151**: spec: reconcile target-spec State cells (rows 1, 6, 10-12) with the evidence records
- **PR #153**: spec: DR 0015, stretch protocols with protocol-neutral ISA primitives (Proposed)
- **PR #150**: docs: judge-facing submission tracker (#134)
- **PR #149**: Pin roles: inventory UART RX/low-baud firmware in DR 0010 and run the checker in lint
- **PR #147**: spec: DR 0014, what area beyond 2x2 buys (Proposed)
- **PR #127**: formal: pin_write_latency on the real core (verification-plan 2.2)
- **PR #146**: spec: land the target-spec / verification-plan / tracker half of #144
- **PR #144**: spec: respond to the organizers' 2026-10-09 entrant update (DR 0012 control space, DR 0013 loading, rows 13-14)
- **PR #96**: Firmware: UART receive path and low-baud (9600) with RX bench (rows 1, 10)
- **Issue #115** (closed): Consolidate firmware-bench hex and cycle-report parsers while preserving caller semantics
- **Issue #135** (closed): RTL: implement DR 0012's control space (WCTL/RCTL, runtime uio direction, program-memory access, PM_CRC, RUN) + assembler + formal + bench
- **Issue #109** (closed): Decision record: admit or defer the stretch protocols (low-speed USB, 10BASE-T) against the ISA cycle budget — row 2's entry condition is unevaluated
- **Issue #133** (closed): I/O: required external parts on a Pmod (I2C pull-ups close DR 0008 item 1), align pinout with TT recommended Pmods, mark pad-speed claims unverified
- **Issue #142** (closed): Spec: reconcile target-spec State cells (rows 1, 6, 10-12) with the evidence records — they still read 'no firmware'
- **Issue #130** (closed): Stretch protocols: rescope DR 0011 around protocol-neutral ISA primitives (CRC/LFSR, NRZI/bit-stuff, Manchester, clock recovery) instead of a plain defer
- **Issue #134** (closed): Submission tracker: map each required deliverable (arch/ISA doc, toolchain+examples, verification + AI-use write-ups, unplanned-protocol demo) to a judge-facing artifact
- **Issue #143** (closed): check_protocol_pin_roles.py fails on main: four UART firmware files missing from DR 0010's inventory; checker not in lint
- **Issue #129** (closed): Area: decide what tiles beyond 2×2 buy in flexibility (6×4 guaranteed, 8×4 expected mid-Oct) — revisit row 7 / DR 0005 Axis 2
- **Issue #116** (closed): Formal: complete deferred pin_write_latency checks on the real core outputs
- **Issue #132** (closed): Loader is submission-critical: program is lost on every deselect — re-tier #118 and target the demo board's MCU
- **Issue #91** (closed): Firmware: UART receive path and low-baud (9600) case with RX jitter bench (rows 1, 10)

### 2026-10-09

- **Issue #82** (closed): T1 item 4: re-run klt lvs on the routed GDS now that klayout-tools#2656 and #2657 are fixed
- **Issue #90** (closed): Formal: run no_data_dependent_latency against the real rtl/protocol_core.v (row 3's remaining scope is tracked nowhere)
- **Issue #92** (closed): Firmware: I2C repeated-START (t_SU;STA), controller-read and clock-stretch cases (row 12 reason a)
- **Issue #93** (closed): Verification §4: seeded constrained-random regression of generated firmware on the real core, graded by the independent models
- **Issue #94** (closed): Decision record: pin roles for ui_in/uo_out/uio per protocol (row 5; unblocks DR 0008's open-drain mask) plus a drift checker
- **Issue #101** (closed): Auditor guard telemetry: worktree-write-confinement-unresolved-var false positives
- **Issue #102** (closed): Post-layout: refresh SDF regression evidence for the SRAM-backed ISA core
- **Issue #103** (closed): CI: discover all committed firmware images for freshness checks
- **Issue #104** (closed): Verification: seed I2C read and clock-stretch scenarios on the real core
- **Issue #108** (closed): Verification: run the committed UART/SPI/I2C firmware against the synthesized gate-level netlist (verification-plan §3 is only smoke-tested today)
- **Issue #110** (closed): Docs: docs/info.md datasheet documents none of the shipped protocol firmware, with a drift check against the committed images
- **Issue #114** (closed): Consolidate duplicated firmware-bench repository-root discovery
- **Issue #117** (closed): CI: run the RTL-level cocotb benches (no PDK) on every PR — today only the template's 8-instruction test and the record linter gate merges
- **PR #89**: T1 item 4: bump klt pin to 6457a605 and re-run LVS on the routed GDS (#82)
- **PR #95**: Formal: run no_data_dependent_latency on the real protocol_core (#90)
- **PR #98**: feat(verification): seeded constrained-random DUT regression of generated firmware (#93)
- **PR #99**: Firmware: I2C repeated-START, controller-read and clock-stretch cases (#92)
- **PR #105**: ci: discover all committed firmware images for freshness checks
- **PR #107**: Post-layout: SDF regression of the SRAM-backed ISA core (annotated, bench fails 1/13) (#102)
- **PR #111**: Verification: seed I2C read and clock-stretch scenarios on the real core
- **PR #112**: docs: protocol datasheet with firmware table, run recipes, provisional pins, drift check
- **PR #113**: feat(verification): firmware benches on the LibreLane gate-level netlist (#108)
- **PR #119**: refactor(verification): share firmware-bench repo-root discovery
- **PR #120**: spec: Proposed DR 0010 protocol pin roles plus drift checker
- **PR #121**: ci: run the RTL-level cocotb benches (no PDK) on every PR

### 2026-10-07

- **PR #80**: chore: delete retired direct-Yosys synthesis stopgap
- **Issue #32** (closed): Remove flow/run_synthesize_direct_yosys.py (retired stopgap) and its stale doc references

### 2026-10-04

- **Issue #23** (closed): Firmware: UART, SPI and I2C programs from DR 0001's cycle-budget sketches (target-spec rows 1, 10, 11, 12)

### 2026-10-03

- **PR #79**: spec: propose DR 0008 for silicon-true open-drain uio_oe wiring
- **Issue #75** (closed): Pin-plan decision record: silicon-true open-drain SCL/SDA needs uio_oe wiring (DR 0001's flagged open question, surfaced by the I2C firmware)

### 2026-10-02

- **PR #78**: spec: propose DR 0007 — row 4's corner set under the 3-corner macro
- **PR #77**: feat: add four-mode SPI controller firmware and its DUT-facing bench
- **PR #76**: feat: add bit-banged I2C controller firmware for both speed grades and its DUT-facing bench
- **PR #74**: feat: bit-banged 8N1 UART TX firmware with reference-model-graded bench
- **PR #70**: evidence: row-4 timing on the LibreLane leg (partial: 3 of 6 corners)
- **Issue #73** (closed): Firmware: I2C program(s) + DUT-facing bench for row 1/12, Standard+Fast mode (part of #23)
- **Issue #72** (closed): Firmware: SPI program(s) + DUT-facing bench for row 1/11, all four modes (part of #23)
- **Issue #71** (closed): Firmware: UART program + DUT-facing bench for row 1/10 (part of #23)
- **Issue #69** (closed): Decision record needed: target-spec row 4's corner-set bar is unreachable by construction for the macro-backed design (3 characterized corners vs 6 declared)

### 2026-10-01

- **PR #68**: docs(records): klt drc/extract/lvs against the LibreLane routed GDS; manifest items 3/4 cited
- **PR #67**: fix: stop SHF from erasing the lint's governing-flag record
- **PR #64**: fix(librelane): bridge the SRAM macro's Metal4-only power pins with a same-layer PDN
- **PR #63**: chore: drop unused pytest pin from test requirements
- **PR #61**: ci: drop the dead workflow_dispatch trigger from the ratification gate
- **Issue #66** (closed): Remove asm.py's dead FLAG_SETTING_OPS and the SHF flag-setter branch: SHF writes C only, and that branch silences the data-dependent-latency lint
- **Issue #65** (closed): T1 items 3/4: run klt drc/extract/lvs against the LibreLane-produced macro-backed GDS (#60 unblocked this, klayout-tools#2635 does not block it)
- **Issue #62** (closed): Remove unused pytest dependency from test/requirements.txt
- **Issue #60** (closed): LibreLane: PDN cannot reach the SRAM macro's Metal4-only power pins — gds blocked at OpenROAD.GeneratePDN
- **Issue #51** (closed): ratification-gate.yml's workflow_dispatch trigger is dead: job condition excludes it

### 2026-09-30

- **PR #59**: RTL: ISA core datapath per DR 0001 + SRAM-macro program memory per DR 0005 (first RTL in this repo)
- **PR #48**: feat: enforce the two-key RATIFY-KEY gate on spec Status flips
- **Issue #45** (closed): The two-key ratification mechanism has no enforcement hook: a spec Status flip can merge with zero RATIFY-KEY reviews
- **Issue #18** (closed): RTL: core datapath per DR 0001 — registers, pin ports, fetch/execute (first RTL in this repo)

### 2026-09-27

- **PR #58**: chore: retire vendored manifests/design-evidence-tiers.md
- **PR #57**: fix: verify signoff baseline via klt signoff --check at v0.6.0 pin
- **PR #56**: chore: replace CI compileall file list with directory form
- **PR #55**: refactor: dedupe flow runners' klt preamble into flow/_klt.sh
- **PR #54**: fix: replace vacuous test-result assertion in npm run test
- **Issue #53** (closed): Replace ci.yml's hand-enumerated compileall file list with directories: it has drifted and skips 2 of 18 scripts
- **Issue #52** (closed): Retire the vendored manifests/design-evidence-tiers.md: the pinned klt now bundles all 11 T1 items
- **Issue #50** (closed): npm run test always exits 1: '! grep -q failure results.xml' matches the failures="0" attribute name
- **Issue #49** (closed): CI job 'klt signoff manifest re-run' has been red on main since before 2026-09-26: a dirty-build fingerprint, not a real drift
- **Issue #47** (closed): Deduplicate the flow runners' klt preamble and netlist-path resolution into one sourced flow/ helper

### 2026-09-26

- **PR #46**: spec: record that the two-key ratification act never ran; reconcile every Status line

### 2026-09-25

- **PR #43**: spec: add DR 0005 taking the SRAM-macro path for program memory
- **Issue #39** (closed): Decision record: program-memory implementation vs the ratified area budget (rows 6/7) — the FF 256x16 memory cannot fit any legal tile count

### 2026-09-23

- **PR #42**: docs: embed fleet burndown chart in README
- **Issue #41** (closed): README: embed the fleet burndown chart (one line)

### 2026-09-22

- **PR #40**: feat(formal): add no_data_dependent_latency formal property with qualification harness
- **PR #37**: feat: add independent UART/SPI/I2C reference models with constrained-random validation (plan section 4)
- **PR #36**: feat(flow): measure the first die-area number via klt place-and-route (row 7)
- **PR #35**: feat(verification): SDF-annotated post-route functional regression (T1 item 7)
- **PR #34**: feat: add DR 0003 firmware assembler with RTL round-trip bench
- **Issue #26** (closed): T1 item 7: the passing gl_test is zero-delay — an SDF-annotated regression is what item 7 actually requires
- **Issue #25** (closed): Verification plan section 4: constrained-random suites and reference models (T1 item 5's bit-exact functional suite)
- **Issue #24** (closed): Verification plan section 2: write the formal properties, starting with no_data_dependent_latency (target-spec row 3)
- **Issue #22** (closed): Firmware: create firmware/ and the assembler per DR 0003 (neither exists)
- **Issue #21** (closed): Target-spec row 7: no die-area number exists on either flow — the <=2x2 tile budget is unverified

### 2026-09-21

- **PR #31**: feat(flow): declare the CMOS5L sta corner set and wire a klt sta corner sweep
- **PR #30**: feat: add 256x16 program memory with serial load-phase protocol and cocotb load test
- **PR #29**: spec: ratify target spec and DRs; install the two-key reviewer variant
- **PR #28**: feat: grade this block's T1 state mechanically via a klt signoff block manifest
- **Issue #19** (closed): RTL: 256x16 program memory + serial load-phase shift-in logic (target-spec row 6)
- **Issue #17** (closed): Ratify the target spec and DR 0001/0002/0003 via the two-key mechanism (T1 item 5's precondition) — and install the ratification tree this repo lacks
- **Issue #16** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read

### 2026-09-14

- **PR #15**: feat: add scripts/setup-env.sh to pin klt + cocotb + PDK
- **PR #14**: docs: close out issue #2 — gds workflow now green end to end
- **PR #13**: fix: remove dead venv-reexec code from verification/_repo_utils.py
- **PR #12**: fix: add missing sg13cmos5l_udp.v to gate-level test sources
- **PR #11**: docs: backfill LibreLane cell count for the synthesis-baseline record
- **PR #9**: docs: reconcile gap-to-submission tracker with the landed harness bootstrap (Part of #2)
- **PR #7**: Bootstrap Tiny Tapeout template + klt/cocotb harness (issue #2)
- **PR #4**: docs: ratify target spec, ISA/flow/firmware decision records
- **Issue #10** (closed): Investigate gl_test and viewer job failures in the gds GitHub Actions workflow
- **Issue #8** (closed): Remove dead venv-reexec code in verification/_repo_utils.py: cites nonexistent files/issues
- **Issue #6** (closed): Add scripts/setup-env.sh to pin klt + cocotb + PDK for the verification/ harness
- **Issue #5** (closed): Backfill LibreLane cell count for the harness-bootstrap stub's synthesis-baseline record
- **Issue #2** (closed): Harness bootstrap: Tiny Tapeout CMOS5L template wiring + cocotb bench and synthesis baseline ported from sky130-modexp
- **Issue #1** (closed): Ratify the target spec: protocol emulator ISA — draft spec, ISA / flow-of-record / firmware-toolchain decision records, verification plan, gap-to-submission tracker
