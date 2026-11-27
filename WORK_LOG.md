# Work Log

Chronological record of merged pull requests and closed issues, newest first.

> **Provenance correction (2026-11-15, issue #415).** 165 entries in this log belonged to a
> different project and have been removed per-entry by the commit that carries this note.
> They all entered in one misdirected write, commit `329b5a18` ("docs: update WORK_LOG,
> WORK_PLAN, and README", merged as PR #373, merge `caa257dc`, 2026-11-02); the bytes remain
> in git history — this note supersedes them rather than destroying them, per the
> append-only rule. The mechanical two-signal sweep (identity against the live issue/PR
> list, provenance against `329b5a18`) also flags exactly one entry that is deliberately
> **retained** as this project's own: `- **Issue #44**` (in the 2026-10-11 section,
> introduced by `dacc38c4`, not by `329b5a18`; its logged title is an exact prefix of
> issue #44's current title, which was renamed after it was logged). Do not delete it to
> make a re-run of the sweep report zero.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-23

- **PR #537**: firmware: CAN 2.0A node on the frozen ISA (arbitrated TX, RX with CRC-15 and ACK)
- **Issue #450** (closed): Firmware: CAN 2.0A on the existing ISA (multi-protocol extra credit)
- **PR #532**: feat: map every failing characterization row to an open owner or ratification wait
- **Issue #524** (closed): T1 item 8: map failing characterization rows to open evidence issues or ratification waits
- **PR #568**: fix: name withheld changed segments in signoff_movement_diff excerpts
- **PR #566**: refactor: consolidate test_check_records fixture boilerplate into shared _commit/_commit_record/_update_rtl/_run_fixture helpers
- **PR #559**: docs: require merge-first, --collapse re-minting of stale signoff leaves
- **Issue #565** (closed): Simplify verification/test_check_records.py: unify layered record-commit and fixture helpers (~290 LOC)
- **Issue #558** (closed): Re-mint signoff records against post-merge live leaves, not pre-merge ones
- **Issue #503** (closed): signoff_movement_diff: excerpt truncation is silent — say how many changed segments were withheld
- **PR #564**: Reuse the control-space harness helpers in the primitives bench and re-mint the affected evidence
- **PR #563**: refactor(verification): drop dead DMX512 model API and reuse shared bench helpers
- **PR #562**: refactor: factor test_check_ratification_gate.py boilerplate into shared helpers
- **Issue #561** (closed): Simplify scripts/test_check_ratification_gate.py: factor duplicated flip, review, and CLI boilerplate (~220 LOC)
- **Issue #560** (closed): Simplify DMX512 verification model and bench: remove dead check_packet and reuse shared helpers (~55 LOC)
- **Issue #557** (closed): Reuse control-space harness helpers in verification/test_primitives.py (~50 LOC)
- **PR #549**: refactor: share record-linter self-test reporting and count all 51 cases
- **Issue #542** (closed): Share record-linter self-test reporting and count all 51 cases
- **PR #489**: refactor: share the program-memory pin driver between the two benches
- **Issue #486** (closed): Share the program-memory pin driver across the load-phase and assembler round-trip benches

### 2026-11-22

- **PR #555**: refactor: emit i2c pair instruction stream from one shared builder
- **Issue #554** (closed): Simplify firmware/tools/gen_i2c_pair.py: emit the 12 repeated bit blocks from a loop and keep SLOTS prose-only (~280 LOC)
- **PR #553**: fix: anchor remint results_xml on REPO_ROOT and fail on a missing XML
- **Issue #552** (closed): remint_records.py resolves klt's repo-scoped results_xml path against the caller's cwd, and a miss is silent
- **PR #551**: Reuse the shared serial loader in the boot-ROM, boot-SPI and primitives benches and re-mint the affected evidence
- **PR #550**: docs: qualify the refresh rule's movement disclosure by klt build and tell the three comparisons apart
- **PR #548**: records: lint a record's artifact links against the git inventory
- **Issue #545** (closed): Record linter does not resolve a record's cited artifact links
- **Issue #540** (closed): Reuse the serial loader in the boot ROM, SPI boot and primitives benches
- **PR #527**: fix: restore missing signoff-baseline artifact files cited by 15 records
- **Issue #521** (closed): Restore the missing artifact files cited by 15 signoff-baseline records
- **Issue #508** (closed): manifests/README.md: PR #498's refresh-disclosure paragraph will contradict #505's live-check paragraph once both land

### 2026-11-21

- **Issue #547** (closed): signoff-baseline refresh: per-leaf re-mint added 11,043 records (1.3M lines) where --collapse exists to mint one
- **Issue #544** (closed): check_protocol_pin_roles.py: express the 'explicit zero pin-mode write' allowance as a rule, not a profile name
- **PR #535**: feat: produce T1 item 11 part 2 power-grid evidence (run-power-par.sh, deck-bearing ERC re-mint, signoff round)
- **PR #533**: docs: extend roadmap Proposed range to DR 0025 and finish its collapse history
- **PR #528**: refactor: pass the pin role into the shared TX firmware and bench checks
- **Issue #526** (closed): Reuse the transmit pin checks for NEC infrared
- **Issue #523** (closed): T1 item 11 part 2: klt place-and-route with a power grid on the macro-backed top (power.pdn, tap cell statement, strap layers)
- **Issue #511** (closed): Update the roadmap’s Proposed range and finish DR 0025’s collapse history
- **PR #498**: feat(signoff): add --diff-vs non-graded movement comparison for baseline refreshes
- **Issue #403** (closed): signoff baseline: name the tiers-doc (source_doc_content_hash) movement when the klt version moves, as the 0.8.0->0.9.0 refresh did not

### 2026-11-21

- **PR #(this PR)**: firmware: CAN 2.0A node on the frozen ISA (issue #450): arbitrated transmit, receive with de-stuffing/CRC-15/ACK

### 2026-11-20

- **PR #477**: feat: collapse parallel evidence re-mints via a list-form supersedes
- **Issue #472** (closed): Evidence hygiene: signoff-baseline leaf count doubles on every concurrent merge (8 to 16 to 32 in one day)
- **PR #518**: docs: mark the STATISTICAL_TEXT_RE mirror comment's klt source as historical
- **Issue #517** (closed): docs: check_statistical_claims_na.py's mirror comment still reads "at the pinned klayout-tools==0.8.0"
- **PR #516**: docs(manifests): record the klt 0.8.0 pin parenthetical in the item-6 statement as historical
- **Issue #481** (closed): docs(spec): spec/statistical-claims-na.md still says "the pinned klayout-tools==0.8.0" after #371 removes the pin
- **PR #513**: feat(records): fail lint on attested-file drift; README is item-10 evidence
- **Issue #507** (closed): Guide README refreshes trip the T1 item-10 attestation gate (README.md is hash-pinned evidence)
- **PR #501**: firmware: SWD debug probe on the frozen ISA (issue #452)
- **PR #505**: fix: report klt checklist-wording movement in signoff --check-latest
- **PR #495**: fix(flow): declare the program-memory SRAM macro in the die-area P&R request and record the first measured die area
- **Issue #452** (closed): Firmware: SWD probe on the existing ISA (multi-protocol extra credit)
- **Issue #502** (closed): Show checklist wording changes reported by klt in signoff --check-latest
- **Issue #389** (closed): Follow-up to #371: die-area P&R (ORD-2013 / request.macros) and die-area-baseline re-mint
- **PR #499**: Re-mint sta-corner-sweep at fleet klt 0.9.2 with a stamped PDK and the live LibreLane hold figure
- **PR #496**: docs: correct #399's one-for-one round count to four at review, five by merge
- **PR #493**: docs: record the externally-triggered signoff-baseline red and its standing response
- **PR #492**: fix: bound the Git root search in the envelope input-path normalizer
- **PR #487**: firmware: NEC infrared remote transmitter on the frozen ISA
- **PR #399**: build: track the fleet klayout-tools version instead of pinning one, and delete the re-mint loop that enforced the pin
- **Issue #494** (closed): Clarify the four rounds at review and five by merge in the PR #399 baseline note
- **Issue #491** (closed): Bound the Git root search in the signoff envelope normalizer
- **Issue #482** (closed): signoff baseline will drift on an unchanged tree at the next klayout-tools release that changes the report shape (post-#371 unpinned klt)
- **Issue #448** (closed): Firmware: NEC infrared on the existing ISA (multi-protocol extra credit)
- **Issue #394** (closed): Re-run the macro-backed klt sta sweep at the fleet klayout-tools version, stamping the PDK and correcting the Flow comparison (#377)
- **Issue #371** (closed): chore: pin a klt containing request.macros (PR #2645) and re-mint the records it stales

### 2026-11-19

- **PR #484**: refactor: share the UART and DMX512 TX pin checks
- **Issue #479** (closed): Share the UART and DMX512 TX pin checks
- **PR #476**: chore: ignore .loom/account-ranking.* token-pool runtime artifacts
- **PR #474**: docs: claim CAN 2.0A demand lead only on the SE proxy
- **PR #469**: docs: align signoff-baseline citation label with the linked record id
- **PR #468**: records: re-file MIDI evidence in a firmware-midi family, pin UART RX rows
- **PR #467**: feat(spec): record T1 item 6 as not applicable with a hash-bound statement
- **PR #461**: firmware: DMX512 universe transmitter on the frozen ISA
- **PR #457**: docs: protocol catalog ranked by sourced demand and fit
- **PR #456**: docs: record the SWD probe examination in DR 0018 (agreed fallback fits)
- **PR #454**: feat: send and monitor MIDI channel messages on the protocol core
- **Issue #478** (closed): signoff-baseline live-record set inflates on every merge: 56 live records, 54 of them redundant copies
- **Issue #475** (closed): gitignore: Loom token-pool ranking artifact .loom/account-ranking.codex trips check-main-clean.sh
- **Issue #473** (closed): docs: protocols.md calls CAN 2.0A the highest-demand build row, contradicting its own demand table
- **Issue #466** (closed): docs: signoff-baseline citation in submission/verification.md labels a superseded record id
- **Issue #462** (closed): MIDI evidence record filed under the firmware-uart-rx experiment heads characterization rows 1 and 10
- **Issue #445** (closed): Firmware: DMX512 on the existing ISA (multi-protocol extra credit)
- **Issue #444** (closed): Firmware: MIDI on the existing ISA (multi-protocol extra credit)
- **Issue #443** (closed): Docs: protocol catalog (docs/protocols.md), every candidate protocol ranked by sourced demand and fit
- **Issue #360** (closed): T1 item 3 (DRC clean): resolve the 4,484 nwell findings in the SRAM macro under the klt 0.8.0 deck
- **Issue #348** (closed): T1 item 6 (Monte Carlo): record "not applicable" as a hash-bound statement covering every ratified spec row
- **Issue #278** (closed): Re-stamp SG13CMOS5L PDK pin from klayout-tools (IHP-Open-PDK dev f7bca326)
- **PR #459**: fix: characterization_report --check misses the stale item 8 manifest pin
- **Issue #458** (closed): characterization_report.py regeneration leaves the top-manifest item 8 pin stale; --check still passes

### 2026-11-18

- **Issue #440** (closed): WORK_PLAN omits operator-held curated issues with no priority label (#435 is invisible)
- **PR #437**: docs: state the merge-group group-size-1 precondition in the ratification gate doc
- **PR #434**: ci: report the required checks on merge_group commits (merge queue readiness)
- **Issue #432** (closed): Merge queue: add the merge_group trigger and adapt the PR-metadata gates

### 2026-11-17

- **PR #427**: chore(loom): resync installed Loom to v0.19.1306

### 2026-11-16

- **PR #423**: chore(loom): resync installed Loom to v0.19.1302

### 2026-11-15

- **PR #421**: test: assert run_inventory reads METADATA_PROFILES so the mapping cannot go dead
- **PR #420**: docs: excise 165 foreign WORK_LOG entries from 329b5a18 and backfill 7 suppressed items
- **PR #418**: docs: restate provisional pin-role preamble around DR 0010's Proposed status
- **PR #417**: test: declare the profile->layer mapping as METADATA_PROFILES with a structure guard
- **PR #395**: docs: roadmap as of 2026-11-13
- **Issue #419** (closed): METADATA_PROFILES guard does not pin the run_inventory dispatch site to the constant
- **Issue #416** (closed): docs/info.md: pin-role status says issue #94 is "still open"; it closed 2026-10-09
- **Issue #415** (closed): WORK_LOG.md carries another project's history (54 SXT-* lines), so the Guide's presence check skips this repo's merged PRs
- **Issue #413** (closed): Test the profile→layer mapping for run_inventory's missing-file diagnostic (currently unreachable through main, so untested)
- **PR #412**: refactor: hoist prof_* read prologues into run_inventory; drop dead pins_of and top_text
- **Issue #409** (closed): Simplify scripts/check_protocol_pin_roles.py: hoist the 19 identical read/None-guard prologues into run_inventory (~53 LOC)

### 2026-11-14

- **PR #410**: docs: re-point 20 superseded record citations in info.md at their live heads
- **PR #408**: docs(spec): add DR 0024 defining the LVS reference, coverage and evidence audit
- **Issue #398** (closed): Docs: README and submission write-ups still say the klt STA leg is blocked on klayout-tools#2635 and claims nothing
- **Issue #396** (closed): Draft the decision record for the T1 item 4 (LVS) evidence contract authorized on #329
- **Issue #400** (closed): docs/info.md cites 21 superseded evidence records; check_docs_records.py only runs over docs/submission
- **Issue #411** (closed): Remove two dead members of Checker in scripts/check_protocol_pin_roles.py: pins_of (0 callers) and top_text (0 readers)
- **PR #406**: refactor(lint): declare the Checker's 10 late-created attributes in __init__
- **Issue #401** (closed): Simplify scripts/check_protocol_pin_roles.py: 10 undeclared instance attributes make the Checker order-dependent
- **PR #407**: docs: state the recorded klt STA result instead of a closed-upstream blocker

### 2026-11-10

- **PR #387**: docs: retire closed UART RX and 434-cycle TX blockers from gap digest
- **Issue #386** (closed): gap-to-submission: reconcile rows 1 and 10 with the #281 and #192 UART evidence

### 2026-11-04

- **PR #384**: lint: enforce --require-implemented for protocol pin role check
- **Issue #382** (closed): Enforce or remove advisory [implementation] layer in check_protocol_pin_roles.py
- **PR #381**: docs(manifests): quote grader detail for T1 item 7
- **Issue #330** (closed): T1 item 7: find and fix why the SDF-annotated regression grades unverifiable_provenance
- **PR #378**: docs(spec): append dated klt hold result and LibreLane hold correction to row 4
- **Issue #377** (closed): Row 4 record consistency follow-ups from the #370 key reviews
- **PR #370**: feat(flow): declare SRAM macro in klt sta sweep and record macro-backed klt result
- **Issue #20** (closed): T1 item 5: no timing evidence exists — both flows reported cell counts only, so >=50 MHz is unconfirmed (need a klt sta corner sweep)

### 2026-11-03

- **PR #375**: refactor(firmware): generate i2c_fast/i2c_std asm from one template
- **Issue #374** (closed): Generate i2c_fast.asm / i2c_std.asm from one template like the _sr variants

### 2026-10-29

- **PR #366**: records: reproduce SRAM-macro DRC findings on the bare macro
- **PR #362**: docs: classify SRAM-macro DRC findings, propose waiver options

### 2026-10-28

- **PR #363**: feat: attest T1 items 1, 9, 10 with klt signoff --attest inventories
- **Issue #361** (closed): T1 grading: attest items 1, 9, 10 with klt signoff --attest instead of hand-written text-list envelopes

### 2026-10-27

- **PR #357**: build: pin klayout-tools to release 0.8.0 and re-mint evidence (item 3 now unmet)
- **Issue #356** (closed): Bump klayout-tools pin b447d8899760 → 0.8.0
- **PR #354**: test: klt erc supply spec and report on the LibreLane GDS
- **PR #352**: feat: generate pre-silicon characterization report and bind it to T1 item 8
- **Issue #349** (closed): T1 item 8 (Characterization report): aggregate per-row results with Fmax, area and power across corners

### 2026-10-25

- **Issue #100** (closed): Auditor Capability Request: Python interpreter unavailable for tool-light validation

### 2026-10-23

- **PR #345**: feat: store bulk evidence in the artifact store, commit manifests
- **Issue #344** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)

### 2026-10-21

- **PR #316**: test: run firmware artifact parser self-test in npm run lint
- **Issue #315** (closed): test_firmware_artifacts.py never runs: needs pytest (removed in #62) and isn't in npm run lint

### 2026-10-20

- **PR #340**: docs: correct boot ROM size and cap in rtl/README.md
- **Issue #339** (closed): rtl/README.md: stale boot ROM claim (says 30 words, cap 128; actual 232 words, cap 256)
- **PR #301**: Tooling: manifest-driven lint runner + self-test wiring inventory (#296)
- **Issue #296** (closed): Tooling: replace the 38-command npm lint && chain with a manifest runner that reports all failures and enforces self-test wiring

### 2026-10-17

- **PR #331**: docs: diagnose item 7 unverifiable_provenance cause in manifests README (partial #330)
- **PR #332**: Bump klt pin to b447d889; item 4 LVS now runs and returns mismatch
- **PR #323**: docs: correct README claim that _dut.py is imported by a bench
- **PR #322**: refactor(firmware): generate the four SPI mode programs from one script
- **PR #321**: refactor(firmware): generate nested-WAIT UART programs from one script
- **Issue #325** (closed): Delete unused verification/_dut.py at next re-mint of its hashing records
- **Issue #320** (closed): verification/_dut.py has no caller but README says benches import it; fix doc now, delete at next re-mint
- **Issue #319** (closed): Generate the four SPI mode firmware variants from one generator (as gen_i2c_sr.py does for I2C)
- **Issue #318** (closed): Generate the four nested-WAIT UART firmware variants from one generator (as gen_i2c_sr.py does for I2C)

### 2026-10-14

- **PR #312**: Firmware: SPI modes 1/3 functional-burst IN placed 4 cycles after the MISO launch edge (#309)
- **PR #311**: refactor(verification): share mutant-runner scaffolding across ten *_mutants.py scripts
- **PR #310**: Verification: rst_n release-offset bench under SDF back-annotation (row 14) (#305)
- **Issue #309** (closed): Firmware: SPI modes 1/3 functional burst samples MISO one core cycle after the peripheral's launch edge
- **Issue #305** (closed): Verification: rst_n release-offset bench under SDF back-annotation (row 14, split from #300)
- **Issue #295** (closed): Consolidate duplicated runner scaffolding across ten verification/*_mutants.py scripts

### 2026-10-13

- **PR #308**: Record rst_n recovery/removal timing at all reset flops (#300)
- **PR #307**: Spec: DR 0021 direct sampling of asynchronous pins by IN (#303)
- **PR #302**: Spec: second ratification batch worksheet and RTL-citation checker (#299)
- **PR #298**: Formal: unbounded proof for no_data_dependent_latency on the real core (#293)
- **PR #297**: CI: wire test_check_docs_issue_states.py into npm run lint
- **Issue #303** (closed): Spec: no decision record covers direct (unsynchronized) sampling of asynchronous pins by IN
- **Issue #300** (closed): Verification: no evidence for rst_n release timing under real delays (row 14 recovery/removal gap has no open issue)
- **Issue #299** (closed): Spec: prepare the second ratification batch (the still-Proposed DRs and rows 13-14 the shipped design depends on) ahead of 2027-01-18
- **Issue #294** (closed): CI: wire scripts/test_check_docs_issue_states.py into npm run lint (the only unwired script self-test)
- **Issue #293** (closed): Formal: close the unbounded proof for no_data_dependent_latency (row 3)

### 2026-10-12

- **PR #292**: Bump klt pin to f979a965 (klayout-tools#2720) with re-minted evidence
- **PR #291**: docs: point PDK link at IHP-Open-PDK subtree and note klt/TT PDK revision split
- **PR #288**: Firmware: SPI mode-0 three-byte burst under one CS, graded against the reference model (#286)
- **PR #287**: ci: scheduled digest issue-state check; fix gap digest row 10
- **PR #284**: Firmware: 434 cycles/bit UART transmitter with drift evidence (#281)
- **PR #283**: Add a checked current-reading digest atop gap-to-submission.md
- **PR #279**: docs(spec): dispose of the ratification keys' non-blocking notes on rows 1-12 (#271)
- **Issue #289** (closed): Bump klt pin to a klayout-tools commit containing #2720 (IHP-Open-PDK fetch)
- **Issue #286** (closed): Firmware: SPI multi-byte burst under one CS (target-spec row 11 caveat) graded against the reference model
- **Issue #285** (closed): CI: run the digest issue-state check on a schedule — the gap digest already cites a closed issue as open
- **Issue #282** (closed): Add a checked current-reading digest atop gap-to-submission.md
- **Issue #281** (closed): Firmware: UART transmitter at 434 cycles/bit (115,200-class) with drift evidence
- **Issue #271** (closed): spec: the ratification keys' non-blocking notes on rows 1–12 (PR #242)
- **Issue #243** (closed): Formal: prove ACK-window sampling and NACK handling for shipped I2C firmware
- **PR #277**: Move the generated i2c_fast_sr* programs to the 70/55 Fast split (#276)
- **PR #240**: docs: cite live evidence records in docs/submission; lint superseded citations (#238)
- **Issue #276** (closed): Move the generated i2c_fast_sr* programs to the 70/55 Fast split (zero t_LOW margin at 65/60)
- **Issue #238** (closed): docs/submission/verification.md cites superseded evidence records (§3.2/§3.3)

### 2026-10-11

- **PR #270**: Prove corrected I2C controller-write ACK windows and address-NACK STOP (#259)
- **PR #269**: docs: R3 update, what the precheck DRC covers (#257)
- **PR #268**: ci: pin tt-gds-action to a commit SHA and lint it (R2)
- **PR #242**: spec: two-key act — flip target spec and DRs 0001-0004 to Ratified (#44)
- **Issue #259** (closed): Prove corrected I2C controller-write ACK windows and address-NACK STOP
- **Issue #257** (closed): Confirm precheck is a sufficient DRC gate: in-flow Magic/KLayout DRC are both off (submission risk R3)
- **Issue #231** (closed): Pin tt-gds-action to a commit SHA and lint against floating refs (submission risk R2)
- **Issue #44** (closed): Two-key ratification has never run: zero RATIFY-KEY reviews exist, so target-spec + DRs 0001-0004 are 'Ratified' by assertion
- **PR #264**: Sample I2C controller-write ACK inside the ninth SCL high
- **PR #260**: Open-drain pad data tied low (DR 0020) and LibreLane timing repair: slow-corner margin +5.8 ns, no slew violations (#244, #246)
- **PR #255**: docs(submission): reconcile D2/D3 and add judge quickstart (#251)
- **PR #253**: fix: portable bench list read and README timing wording (#241)
- **PR #250**: docs: judge-facing architecture and ISA document with a drift checker (#230)
- **PR #249**: spec: DR 0001 dated amendment for run-time uio direction (#44, ruling 3)
- **PR #248**: boot: UART frame carries a count-complement byte checked before any word is committed (#211, DR 0013 F8)
- **PR #247**: firmware: PS/2 device on open-drain CLK/DATA for row 13's stretch column (#235)
- **PR #245**: Opt-in protocol suite for the routed SDF runner (harness increment of #217)
- **PR #239**: spec: DR 0001 fetch-ahead amendment; DRs 0006/0007 agree with DR 0009 (#85 items 1, 4)
- **PR #229**: Include independent host-load replay benches in the RTL CI gate
- **PR #227**: Pace Standard-mode I2C at 500-cycle clocks and bound the full SCL period (#125)
- **Issue #258** (closed): Move Standard/Fast controller-write ACK samples into ninth SCL high
- **Issue #252** (closed): Review scoped shell-assignment resolution in worktree write guard
- **Issue #251** (closed): Reconcile submission D2/D3 readiness and link the judge toolchain quickstart
- **Issue #246** (closed): LibreLane: slow-corner setup margin fell to +1.9 ns and two max-slew violations appeared with the 232-word boot ROM (#211)
- **Issue #244** (closed): Open-drain uio pins drive HIGH for ~100 ps on release under routed delay (uio_oe derived from uio_out)
- **Issue #241** (closed): run-rtl-benches.sh uses mapfile (bash ≥4): breaks local runs under macOS's bash 3.2; README wording nit
- **Issue #235** (closed): Row 13 stretch: a protocol in a role or pin direction the core protocols never use (PS/2, SWD target, MDIO PHY side)
- **Issue #230** (closed): Submission D2: write the judge-facing architecture and ISA document
- **Issue #225** (closed): Include independent host-load replay benches in the RTL CI gate
- **Issue #217** (closed): Run protocol firmware waveform checks on the routed SDF corner sweep
- **Issue #211** (closed): UART load: count byte is outside the CRC; a one-bit count flip can ACK and RUN a truncated image (DR 0013 F8)
- **Issue #125** (closed): I2C Standard-mode: reconcile the 435-cycle firmware clock with the proposed 100 kHz target
- **Issue #85** (closed): spec: fix the eight findings that stopped the two-key ratification of PR #84 (fetch model, SPI sketch, row 10 source and four other citations)
- **PR #236**: Row 13: WS2812 chosen after the ISA freeze (DR 0018), firmware + independent WS2812B model at RTL and gate level (#141)
- **PR #234**: DR 0013 layer 1 after the #166 ruling: loadseq zero refusal, readout load roles (#218)
- **Issue #218** (closed): DR 0013 layer 1 after the #166 ruling: loadseq refuses all-zero images, record the CRC-0 gap, findings 3 and 4
- **Issue #141** (closed): Row 13: freeze the submission ISA, then demonstrate a protocol the chip was not designed for (WS2812 / 1-Wire / DMX512)

### 2026-10-10

- **PR #233**: spec: freeze the submission ISA (DR 0017) with a sha256 check (#141 part 1)
- **PR #232**: Buffer all SRAM macro inputs in the LibreLane flow (#201)
- **PR #228**: Gate gl_test on repository-owned GL results validation
- **PR #221**: Submission D4: judge-facing verification write-up
- **PR #212**: Build DR 0015's P1 (CRC/LFSR step) and P2 (NRZI + bit-stuff) in control space 0x10-0x19 (#208)
- **PR #167**: feat: show PM_CRC on uo_out during the serial load so the host can verify before running (DR 0013 layer 1)
- **PR #224**: CI: cancel in-progress only for pull_request events
- **PR #222**: docs: judge-facing AI-use narrative (submission D5)
- **PR #220**: Reject contradictory and empty JUnit results in check_test_results.py
- **PR #210**: Boot firmware: UART load over the demo board's USB bridge (strap 00) with an independent host model (#139)
- **PR #209**: Add UART RX to the constrained-random regression and gate-level firmware run (#192)
- **PR #207**: spec: DR 0016 rules the four ISA details DR 0001 leaves open (Proposed)
- **PR #206**: Bind T1 items 1, 2, 9 and 10 to audited artifacts; klt pin to v0.7.0 (#83)
- **PR #172**: feat: fail lint on a new file with an absolute home-directory path
- **Issue #223** (closed): CI: preserve started main verification runs during merge bursts
- **Issue #219** (closed): Re-mint stale evidence records and signoff baseline for PR #212 after #139 merge
- **Issue #216** (closed): Gate the Tiny Tapeout gl_test job on repository-owned XML result validation
- **Issue #214** (closed): Submission D4: distill current verification evidence into a judge-facing write-up
- **Issue #208** (closed): Build DR 0015's admitted primitives P1 (CRC/LFSR step) and P2 (NRZI + bit-stuff) in control space 0x10–0x1F
- **Issue #201** (closed): LibreLane max-slew violation on an SRAM macro input pin (A_DIN[0], then A_WEN) after the UART-load ROM re-roll
- **Issue #137** (closed): DR 0013 layer 1: expose PM_CRC on uo_out during serial load so the host can verify before running
- **Issue #215** (closed): Reject contradictory and empty JUnit results in check_test_results.py
- **Issue #213** (closed): Submission D5: write the judge-facing AI-use narrative
- **Issue #203** (closed): Spec: DR 0001 leaves SUB's C polarity (an RTL pin) and three SHF/logic flag details open; ratify or mark unspecified
- **Issue #192** (closed): Verification: add UART RX to the constrained-random regression and gate-level firmware run
- **Issue #166** (closed): DR 0013 layer 1: rule on the four findings from the #137 build (row 14(b) vs the uo_out readout, CRC init 0, doubled-edge wording, DR 0010 load roles)
- **Issue #139** (closed): Boot firmware: UART load over the demo board's USB bridge (TT option B pins) with an independent host model
- **Issue #86** (closed): Two committed LVS error records contain an absolute home-directory path
- **Issue #83** (closed): signoff: bind T1 items 1, 2, 9 and 10 to audited artifacts (klayout-tools#2718 landed)
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

