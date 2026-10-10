# Target Specification

Status: **PROPOSED — not ratified.** Proposed 2026-09-14 in issue #1.
Reconciled 2026-09-26 per
[`decision-records/0006-two-key-ratification-never-ran.md`](decision-records/0006-two-key-ratification-never-ran.md):
the 2026-09-21 `RATIFIED` claim below rested on an act that never happened.
The PR carrying
[`decision-records/0004`](decision-records/0004-target-spec-ratification.md)
was **#29**, and it merged (merge commit `8be9d1e`) with **zero**
`RATIFY-KEY` reviews — in fact with zero PR reviews of any kind. The
§ "Ratification" section's own clause therefore fires: *"If this file's
Status reads `RATIFIED` but the ratifying PR's record cannot show both key
reviews, the ratification did not happen by mechanism, and this status is
invalid until superseded by a later record that says so."* DR 0006 is that
record.

**Nothing in the table below changes.** Every row's target, stretch entry,
citable source, checking artifact, and `State` reading stands exactly as
written, and DR 0004's load-bearing separation — what a ratification *binds*
versus whether the design has *met* it — is preserved intact: no row moves
between target and met in either direction. What the reconciliation withdraws
is only the claim that these rows *bind by mechanism*. They are this repo's
proposed spec-of-record, unratified, and every verdict graded against them
stays provisional by construction (T1 item 5) until two `RATIFY-KEY` reviews
land on a carrying PR. The `[DR-4]` markers in the State column should be
read as *"as DR 0004 proposes to bind it"*, not as a completed ratification.
What made this a *spec* rather than a wishlist is unaffected: every row
carries a citable source and a description of how the verification suite
checks it, per `spec/verification-plan.md`.

> **Status line as written 2026-09-21, preserved verbatim (superseded by the
> text above, not deleted — DR 0006 records why):**
>
> Status: **RATIFIED** — proposed 2026-09-14 in issue #1; ratified
> 2026-09-21 in issue #17, via the program's two-key (EE + market) mechanism:
> the ratification act is the two `RATIFY-KEY` reviews on the PR that carries
> [`decision-records/0004-target-spec-ratification.md`](decision-records/0004-target-spec-ratification.md)
> (neither key held by that PR's author or the design's author — the marker
> convention both keys follow is documented in this repo's installed
> [`ratification/ee-key/SKILL.md`](../ratification/ee-key/SKILL.md) and
> [`ratification/market-key/SKILL.md`](../ratification/market-key/SKILL.md),
> "Output format"), and the merge commit is the ratification record. The
> ratification binds the **rows as targets** — every row's ratified state is
> explicit in the State column below and in
> [`decision-records/0004`](decision-records/0004-target-spec-ratification.md)'s
> per-row register; no row is carried as *met* unless its State says so, and
> the rows whose evidence does not exist yet (2, 10–12: no evidence at all;
> 4, 7: cell counts only, no STA or die-area number on either flow) are
> ratified as targets with that said out loud. What made it a *spec* rather
> than a wishlist before ratification still holds: every row carries a
> citable source and a description of how the verification suite checks it,
> per `spec/verification-plan.md`.

This table supersedes the draft table formerly inline in `README.md` (see
that file's "Target specification" section, now a pointer here). Rationale
for design choices that produced these numbers — not just the numbers
themselves — lives in `spec/decision-records/`.

## How to read this table

- **Target** is the committed value this spec asks the design to hit.
- **Source** is the citable origin of the bound — a competition rule, a
  platform constraint from the submission template, a protocol standard's
  timing table, or (where no external body governs the interface) a named
  decision record in this repo.
- **Checked by** names the verification artifact from
  `spec/verification-plan.md` that is expected to exercise this row. A row
  with no artifact yet is a gap, tracked in `spec/gap-to-submission.md`.
- **State** is the row's status *as ratified by
  [`0004-target-spec-ratification.md`](decision-records/0004-target-spec-ratification.md)*
  (`[DR-4]`), read as two axes: what the ratification bound, and whether the
  design has met it. `Target [DR-4] — unmet` is a binding target with no
  evidence yet (ratified *as a target*, not carried as met — this is the
  state the 2026-09-21 ratification deliberately makes explicit for rows 2
  and 10–12); `Target [DR-4] — unmet; not carried as met` adds the
  ratification record's explicit bar against rows 4 and 7 being read as met
  (no STA result / no die-area number exists on either flow); `Stretch
  target [DR-4]` marks an aim that binds nothing numeric; `Ratified
  [DR-4] — met` marks a row whose checked-by artifact exists and passes
  *for the current stub top*. The per-row statements, evidence, and tracking
  issues live in 0004's register — this column is its one-line index, and
  the live met/unmet tracker of record is `spec/gap-to-submission.md`.

## Rows

| # | Parameter | Target | Stretch | Source | Checked by | State |
|---|---|---|---|---|---|---|
| 1 | Protocols emulated in firmware | UART (8N1, 9600–1,000,000 baud), SPI (modes 0–3, controller, SCLK ≤ f_clk/4), I2C (Standard-mode 100 kHz + Fast-mode 400 kHz, controller) | — | [Jane Street Protocol Emulator ASIC Competition post](https://blog.janestreet.com/protocol-emulator-asic-competition/): "Start with UART, SPI, and I2C." *Quote made verbatim 2026-10-10 (issue #85).* | Constrained-random protocol-traffic suite (§4, verification-plan.md), one per protocol | Target [DR-4] — unmet. *Evidence wording updated 2026-10-09 (issue #142); the Target column and the unmet reading are unchanged.* *Evidence wording updated 2026-10-10 (issue #164); the Target column and the unmet reading are unchanged.* Firmware for all three protocols runs on the ISA core (`rtl/protocol_core.v`, record `verification/records/core-datapath/records/20261010-020604-ed5f2d1.md`) and is graded by the independent reference models. UART: TX at 50 cycles/bit (`verification/records/firmware-uart/records/20261010-040735-c48e4f2.md`); TX at 5,208 cycles/bit and RX at 50 / 434 / 5,208 cycles/bit (`verification/records/firmware-uart-rx/records/20261010-040736-c48e4f2.md`). SPI: controller, modes 0–3 (`verification/records/firmware-spi/records/20261010-040750-c48e4f2.md`). I2C: controller write at Standard and Fast mode (`verification/records/firmware-i2c/records/20261010-040813-c48e4f2.md`); write, repeated START and one-byte read, with clock stretching (`verification/records/firmware-i2c/records/20261010-040816-fb86d71.md`); both on a logical, zero-delay pad model that resolves SCL and SDA from the design's own `uio_oe` / `uio_out` (`verification/records/uio-pad-model/records/20261010-040848-fb86d71.md`). The constrained-random suite named in Checked by exists: 80/80 generated programs pass (UART TX, SPI, I2C write, I2C write/read) and the negative controls fail (`verification/records/random-regression/records/20261010-041004-fb86d71.md`). The directed UART TX, SPI and I2C benches also pass on the LibreLane gate-level netlist, zero-delay, with the I2C benches on the pad model (`verification/records/firmware-gate-level/records/20261010-044333-89cd241.md`). The row stays unmet: UART RX is not in the constrained-random suite; the I2C pad model is logical, not electrical, so there is no rise-time, pad-delay or drive-strength evidence and no I2C drive has reached a silicon pin; the runtime pin mode it exercises (DR 0012) and DR 0008 and DR 0001 are Proposed. Every rate is a core-cycle count; the clock is row 4's unconfirmed target, so no baud, SCLK or kHz figure is measured. *As written 2026-09-21, superseded by the wording above:* (no RTL, firmware, or protocol suite yet; DR 0001's cycle-budget sketches are the sufficiency evidence) |
| 2 | Stretch protocols | — | Low-speed USB 1.1 (1.5 Mbit/s), 10BASE-T Ethernet (10 Mbit/s) | Same competition post: "Stretch goals include low-speed USB and 10Mbit Ethernet." *Quote made verbatim 2026-10-10 (issue #85).* | Not yet designed; enters this spec only if DR 0001's ISA can show a cycle budget for it (none shown yet — see gap tracker) | Stretch target [DR-4] — aim ratified, nothing numeric bound (no cycle-budget sketch exists; the row's own entry condition is unmet, so it commits to no value — ratified as a *target*, explicitly not met) |
| 3 | Timing determinism | No instruction's cycle latency depends on the data it operates on; every pin sample/drive and every `WAIT` lands on a cycle computable by reading the program alone | — | `spec/decision-records/0001-isa.md` (this repo's design commitment — no external body specifies CPU timing determinism) | Formal property `no_data_dependent_latency` (§2, verification-plan.md) | Target [DR-4] — unmet (a design commitment, now bound; the formal property itself is not yet written) |
| 4 | Core clock | ≥ 50 MHz timing closure on CMOS5L (flow of record per DR 0002) | 100 MHz | README draft baseline (2026-09-12 standup) informed by typical Tiny Tapeout `clock_hz` operating points; no shuttle-specific clock spec exists yet for the CMOS5L TT template | Static timing analysis in the flow-of-record's sign-off run (gate-level regression, §3, verification-plan.md) | Target [DR-4] — unmet; not carried as met. *Evidence wording updated 2026-10-10 (issue #85); the Target column and the unmet reading are unchanged; the 2026-10-02 wording is kept under § "Dated notes — 2026-10-10" below.* **LibreLane flow** (post-route, 20 ns): 50 MHz closes at all 3 corners that flow emits for the macro-backed design (`nom_slow_1p08V_125C`, `nom_typ_1p20V_25C`, `nom_fast_1p32V_m40C`), with 0 setup and 0 hold violations; worst hold slack is 0.114 ns at the fast corner, and the flow reports a few max-capacitance and max-fanout violations, which are not timing violations (`verification/records/librelane-corner-timing/records/20261010-020340-ed5f2d1.md`). **klt flow**: no result at any corner; the leg is blocked on klayout-tools#2635, still open (`verification/records/sta-corner-sweep/records/20261010-042124-89cd241.md`). **Corner set**: this row's Target names none. The 6 `sg13cmos5l_stdcell` corners declared on 2026-09-21 include 3 (1.35 / 1.50 / 1.65 V) that cannot be analysed, because the program-memory macro ships no liberty above 1.32 V. [`decision-records/0007`](decision-records/0007-row4-corner-set-under-the-macro.md) (**Proposed**) proposes the 3 macro-characterized corners as the set and records the fast corner's −40 °C / −55 °C liberty pairing as a known approximation whose effect on hold is not established. The row stays unmet because no corner set is bound for it, DR 0007's open item 1 (which class the fast-corner hold path is in) is unresolved, and the klt flow has no result |
| 5 | I/O pin budget | 8 dedicated inputs (`ui_in[7:0]`), 8 dedicated outputs (`uo_out[7:0]`), 8 bidirectional (`uio_in/out/oe[7:0]`), plus `clk`/`rst_n`/`ena` | — | [Tiny Tapeout CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), `tt_um_*` wrapper interface (fixed by the template, not negotiable) | cocotb functional suite instantiates the `tt_um_*` top exactly as the template defines it | Ratified [DR-4] — met at the stub level (`src/tt_um_2amlogic_protocol_emulator.v` drives the full fixed budget; protocol pin-role assignment is deliberately a later decision record) |
| 6 | Program storage | On-chip program memory, 256 × 16-bit words (512 bytes), addressed by an 8-bit PC; loaded serially over a dedicated input pin during a reset-gated load phase; *proposed 2026-10-09 (DR 0013):* or by an on-chip boot ROM written in this ISA (UART or SPI-flash load), with every load integrity-checked (CRC-16) before it runs | Program memory backed by a Tiny Tapeout SRAM macro instead of flip-flops, if area allows | `spec/decision-records/0001-isa.md` §"Program memory sizing and loading" (sizing and load-protocol are this repo's own design call — no external spec governs it) | cocotb load-phase test (loads a known program, confirms readback via a program-dump instruction path) — not yet written, tracked in gap tracker | Target [DR-4] — unmet. *Evidence wording updated 2026-10-09 (issue #142); the Target column and the unmet reading are unchanged.* `rtl/protocol_program_memory.v` implements the 256 × 16 store on the PDK SRAM macro (the stretch, under DR 0005, Proposed) and is wired into the submitted top. The load-phase test passes 6/6: serial MSB-first load, a full 256-word program read back at every address, saturation at 256 words, and a full load of exactly 4,097 clock edges (`verification/records/program-load-phase/records/20260930-195410-ead870a.md`). Every firmware record cited in rows 1 and 10–12 loads its program over these pins. The row stays unmet: the test reads back through the core's fetch port, not the program-dump path that Checked by names (DR 0012's `PM_*` read access, not built); DR 0013's CRC check and boot ROM are not built; load time is in cycles and no clock is claimed (row 4); and DR 0005 is Proposed. *As written 2026-09-21, superseded by the wording above:* (no program-memory or load-phase RTL, and the load-phase test is unwritten; the sizing/load decision itself is bound via DR 0001) |
| 7 | Area | ≤ 2×2 Tiny Tapeout tiles (draft) | Competition maximum: 6×4 tiles today; 8×4 is possible, not confirmed | [Competition post](https://blog.janestreet.com/protocol-emulator-asic-competition/), as served 2026-10-10: "The current maximum area is 6x4 tiles per design. We are working on the possibility of scaling up to 8x4 tiles (~30% more area)."; README draft (2×2 internal target, chosen because judging rewards verification novelty, not size) | Post-synthesis area report from the flow-of-record (§3, verification-plan.md). **Open gap**: exact tile pitch for the CMOS5L TT template is not yet confirmed in this repo — see gap tracker | Target [DR-4] — unmet; not carried as met (no die-area or floorplan number exists on either flow — cell counts are not area — the 0004 register bars reading this row as met; the tile-pitch half is resolved, the area half is open) *Dated note 2026-10-09 (issue #129; the Target column is unchanged):* [`decision-records/0014`](decision-records/0014-area-beyond-2x2.md) (**Proposed**, unratified) weighs what area beyond 2×2 would buy against the organizers' stated criteria and recommends keeping 2×2 for now, with 3×2 as the next step if a multi-engine design is admitted; it commits nothing past 6×4 before the 8×4 template lands. Nothing here relaxes the row. |
| 8 | Verification | cocotb functional suite + gate-level regression on the flow-of-record; ≥1 formal property on the timing guarantees; constrained-random protocol traffic checked against an independent reference model per protocol | Silicon bring-up on the dev board after tape-out | Competition post: "We’re particularly interested in projects with unique functionality, as well as those that demonstrate novel approaches to design and verification methodologies!" and "We are excited to see the languages and verification techniques you use, including formal methods, random constrained tests, AI-assisted verification, and more." *Quotes made verbatim 2026-10-10 (issue #85).* | `spec/verification-plan.md` in full | Target [DR-4] — partially realized (cocotb harnesses and the gate-level regression exist and pass on the stub; the formal-property and constrained-random/reference-model artifacts do not exist yet) *Dated note 2026-10-09 (issue #93; the Target column is unchanged):* the constrained-random leg now reaches the core — a seeded regression (seed 20261009, 20 programs per protocol) generates UART-TX, SPI (modes 0-3) and I2C-write (Standard + Fast) firmware from templates, assembles it with the DR 0003 assembler, runs it on the real RTL over the load-phase pins, and grades the pin waveforms with the independent reference models (60/60 pass; 4/4 mutated-template negative controls failed by the model; cover bins stated, unhit bins listed; record newest record `verification/records/random-regression/records/20261010-041004-fb86d71.md`, which supersedes the one first minted with this note). **Not covered, deferred:** UART RX and I2C read (no firmware exists), SPI multi-byte bursts under one CS, I2C clock stretching/repeated START. The formal-property leg and the gate-level regression are untouched by this note, so the row stays partially realized. *Dated note 2026-10-09 (issue #104; the Target column is unchanged):* the same seeded regression now also generates I2C write / repeated-START / controller-read programs (the polling firmware of `firmware/tools/gen_i2c_sr.py`, both speed grades, seeded address/pointer/read-payload classes) against a reactive peripheral that stretches SCL after 1-3 of three fixed sites for seeded short/medium/long durations; the independent I2C model grades every transfer, the received byte is checked at `uo_out`, non-stretched SCL phases are compared against an unstretched run, and the non-polling program under a selected schedule plus a truncated capture are failed as controls (record `verification/records/random-regression/records/` newest entry, which supersedes the 2026-10-09 #93 record because the bench inputs it hashed changed). This was first run on a bench-composed bus, not silicon open-drain pad behaviour, and takes no pin-plan decision (#94). UART RX and SPI multi-byte bursts under one CS stay deferred. *Evidence wording updated 2026-10-10 (issue #164); the Target column and the partially-realized reading are unchanged.* The I2C families of the regression now run on a logical, zero-delay pad model that resolves SCL and SDA from the design's own `uio_oe` / `uio_out`, with the runtime pin mode of DR 0012 (Proposed, unratified) (`verification/records/uio-pad-model/records/20261010-040848-fb86d71.md`; newest regression `verification/records/random-regression/records/20261010-041004-fb86d71.md`: 80/80 generated programs PASS, 14/14 negative controls FAIL as required, including the programs that leave `UIO_OD` at reset). The model is not electrical evidence (no rise time, pad delay or drive strength), the ACK-window formal property is not written, and rates are core-cycle counts at row 4's unconfirmed clock, so the row stays partially realized. |
| 9 | Submission | Open source, licensed Apache-2.0 (this repo's choice), via the Tiny Tapeout CMOS5L template, due **2027-01-18** | — | Competition post: "Your submission should be open source so others can use and build on it"; "Start with the CMOS5L Verilog template"; "Submit your design by January 18th, 2027". The post names no licence: Apache-2.0 is this repo's own choice, set in [`LICENSE`](../LICENSE). *Source restated 2026-10-10 (issue #85).* | `spec/gap-to-submission.md` tracks readiness against this date | Target [DR-4] — on track, deadline pending (license, template wiring, and the sign-off flow are green on the stub; the actual submission is due 2027-01-18) |
| 10 | UART bit-timing accuracy | Each bit sampled/driven within its nominal period at all supported bauds; cumulative per-frame drift **≤ 2 % of the nominal bit period**, that is, the timing error accumulated by the frame's last edge, as the row's reference model measures it (UART tolerates larger per-bit error than per-frame, since the receiver resynchronizes on each start bit). *Bound restated 2026-10-10 (issue #85) from "under ~2%" to a number; the value is unchanged.* | — | No standards body owns UART bit-rate tolerance, so the bound is derived, then given margin. *Basis restated 2026-10-10 (issue #85).* Maxim Integrated tutorial 2141, "Determining Clock Accuracy Requirements for UART Communications" ([archived copy](https://web.archive.org/web/20211207151039/https://www.maximintegrated.com/en/design/technical-documents/tutorials/2/2141.html)), derives the whole-link clock-mismatch budget for an 8N1 frame and a receiver clocked at 16× the bit rate: the stop bit is sampled 9.5 bit periods (152 receive clocks) after the start edge, one receive clock is lost to start-edge synchronization, and a link that can be sampled only in the middle 50 % of a bit leaves ±3 clocks, so the budget is ±3/152 (≈ ±1.97 %, which the tutorial rounds to 2 %) of rate mismatch, shared between transmitter and receiver (±5/152 ≈ ±3.3 % for a link sampled in the middle 75 %). That budget allows 3/16 of a bit (18.75 %) of accumulated error at the stop-bit sample. This row allows 2 % of a bit accumulated by the frame's last edge, which is at most 10 bit periods after the start edge, so about 0.2 % of rate error. The transmitter therefore uses about a tenth of the tighter link budget and leaves the rest to the receiver at the other end. The 2 % figure is this repo's design margin; the tutorial shows it sits inside a published budget and is not the origin of the number. | Reference-model comparison in the UART constrained-random suite (§4, verification-plan.md) measures actual vs. nominal bit timing from the cocotb waveform | Target [DR-4] — unmet. *Evidence wording updated 2026-10-09 (issue #142); the Target column and the unmet reading are unchanged.* The independent UART model measures 0.000 % frame drift on TX at 50 cycles/bit (`verification/records/firmware-uart/records/20261009-141536-dc05940.md`) and at 5,208 cycles/bit, the 9,600-baud-class end (`verification/records/firmware-uart-rx/records/20261010-040736-c48e4f2.md`). In the constrained-random suite, 20 generated TX programs at 50 / 100 / 217 / 250 cycles/bit pass `check_frame` inside the 2 % bound, every edge on a whole multiple of the bit period (`verification/records/random-regression/records/20261009-141800-dc05940.md`). The RX programs (50 / 434 / 5,208 cycles/bit) receive model frames with ±2 % per-bit rate error (`verification/records/firmware-uart-rx/records/20261010-040736-c48e4f2.md`). That is a receiver-tolerance result, not this row's transmitter drift bound. The row stays unmet: TX at the 434-cycle (115,200-class) rate is not measured, and every rate is a core-cycle count; the clock is row 4's unconfirmed target, so no baud, SCLK or kHz figure is measured. *As written 2026-09-21, superseded by the wording above:* (no evidence yet: the ~2% per-frame drift bound is adopted as a target; the UART suite that would measure it does not exist — ratified as a *target*, not carried as met) |
| 11 | SPI clock ceiling and modes | Controller mode, SCLK ≤ f_clk/4, all four clock-polarity/phase combinations (modes 0–3) | — | SPI has no formal owning standards body; the de facto reference is the Motorola/Freescale/NXP "SPI Block Guide" (V03.06) mode/timing conventions | SPI constrained-random suite (§4, verification-plan.md) sweeps all 4 modes against a reference SPI controller/peripheral model | Target [DR-4] — unmet. *Evidence wording updated 2026-10-09 (issue #142); the Target column and the unmet reading are unchanged.* Four directed controller programs, one per mode, run at exactly 4 core cycles per SCLK period (f_clk/4) and are graded conformant by the independent SPI model, MOSI and MISO decoded byte-exact (`verification/records/firmware-spi/records/20261009-141610-dc05940.md`). The constrained-random suite sweeps modes 0–3 round-robin over 20 generated programs at SCLK periods of 4 / 6 / 8 / 12 cycles, all model-graded PASS (`verification/records/random-regression/records/20261009-141800-dc05940.md`). The directed benches also pass on the LibreLane gate-level netlist, zero-delay (`verification/records/firmware-gate-level/records/20261009-142200-dc05940.md`). This change does not carry the row as met: the ceiling is shown as a cycle ratio only, the wall-clock ceiling at the pins also depends on pad edge rates that are not characterized (rows 10–12 dated note), and multi-byte bursts under one CS are untested. *As written 2026-09-21, superseded by the wording above:* (no evidence yet: modes 0–3 and the SCLK ceiling are bound as targets; the SPI suite that would check them does not exist — ratified as a *target*, not carried as met) |
| 12 | I2C timing | Standard-mode (100 kHz) and Fast-mode (400 kHz), controller role, meeting `t_LOW`, `t_HIGH`, `t_HD;STA`, `t_SU;STA`, `t_SU;STO` minimums | Fast-mode Plus (1 MHz) | NXP UM10204 "I²C-bus specification and user manual," Rev. 7.0 (1 October 2021), Table 11 ("Characteristics of the SDA and SCL bus lines for Standard, Fast, and Fast-mode Plus I²C-bus devices"). *Revision updated 2026-10-10 (issue #85): Rev. 6 numbered this table 10; the five minimums named in Target have the same values in Rev. 7.0 Table 11 as in the reference model.* | Formal property on ACK-window timing plus I2C constrained-random suite (§2 and §4, verification-plan.md) against an independent I2C reference model | Target [DR-4] — unmet. *Evidence wording updated 2026-10-09 (issue #142); the Target column and the unmet reading are unchanged.* *Evidence wording updated 2026-10-10 (issue #164); the Target column and the unmet reading are unchanged.* Controller write at both grades meets every Table 11 minimum (Table 10 in Rev. 6) the model checks, in core cycles: Fast t_LOW / t_HIGH 65 / 60, Standard 235 / 200 (`verification/records/firmware-i2c/records/20261010-040813-c48e4f2.md`). Repeated START (t_SU;STA exercised), a one-byte read and SCL clock stretching pass the same model (`verification/records/firmware-i2c/records/20261010-040816-fb86d71.md`). Both run on a logical, zero-delay pad model driven through the design's real `uio_oe` (`verification/records/uio-pad-model/records/20261010-040848-fb86d71.md`). The constrained-random suite runs 20 I2C-write and 20 write/repeated-START/read programs with seeded clock stretching, all model-graded PASS (`verification/records/random-regression/records/20261010-041004-fb86d71.md`). The directed benches also pass on the LibreLane gate-level netlist, zero-delay, on the pad model (`verification/records/firmware-gate-level/records/20261010-044333-89cd241.md`). The row stays unmet: the pad model is logical, not electrical, and the runtime pin mode that drives the lines is DR 0012 (Proposed, unratified), so no open-drain drive has reached a silicon pin (DR 0008, Proposed); the ACK-window formal property named in Checked by does not exist; pad rise times, pad delay and drive strength are not characterized; and every rate is a core-cycle count; the clock is row 4's unconfirmed target, so no baud, SCLK or kHz figure is measured. *As written 2026-09-21, superseded by the wording above:* (no evidence yet: the UM10204 minimums are bound as targets; the formal property and I2C suite do not exist — ratified as a *target*, not carried as met) |
| 13 | Reprogrammability beyond the designed protocol set | At least one protocol that is **not** in rows 1–2 and was not considered when the ISA was designed, implemented as firmware only (no RTL change) and passing against an independent reference model with timing checked, the same evidence bar `CLAUDE.md` sets for rows 1 and 10–12. Candidates: 1-Wire, WS2812, DMX512, Manchester/IR. The choice is recorded *after* the ISA is frozen for submission, so it cannot shape the ISA | A protocol in a **role or pin direction** the core protocols never use (for example a target-role SPI or I2C, or 1-Wire's single bidirectional open-drain line), which exercises DR 0012's runtime pin direction | Organizers' 2026-10-09 entrant update, quoted verbatim in issue #129: "Flexibility is the main thing: can the chip be reprogrammed to support protocols it wasn't designed for?" | A firmware bench per protocol with an independent reference model (`spec/verification-plan.md` §7) | Proposed 2026-10-09 — **not in DR 0004's register** (added after it); unmet, no firmware yet |
| 14 | Reset, power-up and reselect behaviour | From `rst_n` alone, with every flop starting at an arbitrary value: (a) every state element reaches its documented reset value; (b) no `uio` pin is driven and `uo_out` holds its documented reset value until a program writes them, *amended 2026-10-10 (operator ruling on issue #166, option 1):* except during a serial load (`MODE` high at `rst_n` release, until the edge that takes `MODE` low), when `uo_out` presents `PM_CRC` per DR 0013 layer 1; (c) the core never executes program memory whose contents were not loaded and integrity-checked since power-up (DR 0013) | — | Organizers' 2026-10-09 entrant update (issue #131): "flops don't start at 0, so your design needs to use the reset signal (rst_n) to get into a known state … When your design is deselected it's powered down and loses its state" | Gate-level random-initial-state and X-propagation regression, plus a reset-coverage listing of non-reset flops with a justification for each (`spec/verification-plan.md` §8) | Proposed 2026-10-09 — **not in DR 0004's register**; unmet. Today (b) holds only because `uio_oe` is hardwired to 0, and (c) fails: `MODE` low at reset runs the SRAM from address 0 whatever it holds (DR 0013 § Context) *Dated note 2026-10-09 (issue #138; the Target column and the unmet reading are unchanged):* (c) no longer fails that way. `MODE` low at reset runs DR 0013's boot ROM, and program memory is decoded only after a boot program's CRC check passes (`verification/records/boot-rom/records/20261010-020820-0f0490a.md`, RTL; `verification/records/firmware-gate-level/records/20261010-042012-89cd241.md`, gate level). One image passes the check by arithmetic, the all-zero one (DR 0013, finding F1). (a) and (b) are unaddressed: the random-initial-state run and the reset-coverage listing of verification-plan §8 are not built, and (b) now rests on `UIO_DIR`/`UIO_OD` resetting to 0 *Dated note 2026-10-10 (issue #168; the Target column and the unmet reading are unchanged):* the all-zero image no longer passes: the warm start refuses a signature of `0x0000` (DR 0013, implementation notes of issue #168; DR 0012's `PM_CRC` seed is unchanged). *Dated note 2026-10-10 (issue #166; the Proposed status and the unmet reading are unchanged):* (b)'s Target wording is amended above by the operator's ruling on issue #166 (https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/166#issuecomment-6100509020). DR 0013 layer 1 (issue #137) puts the running `PM_CRC` on `uo_out` while a serial load is in progress, low byte or high byte by `ui_in[1]`, so the host can check the load before it drops `MODE`; outside that phase (in reset, through the boot ROM's paths with `MODE` low, and from the `MODE`-drop edge on) the clause reads as before. The readout is graded per cycle on the RTL and on the routed netlist with back-annotated SDF by `verification/test_protocol_emulator.py::test_reset_and_load_leaves_pins_cleared` (records in `verification/records/core-datapath/` and `verification/records/post-layout-sdf-regression/`). Nothing else about (b) is claimed by this note. Status of this row is tracked in `spec/gap-to-submission.md` row 14 |

## Dated notes — 2026-10-09 organizers' entrant update

On 2026-10-09 the competition organizers sent registered entrants an update
and FAQ. Its relevant statements are quoted verbatim in issues #129–#134; the
organizers say the same material will be added to the competition blog post.
No existing row's **Target** is weakened by anything below. Rows 13 and 14 are
new, and row 6 gains a load path (DR 0013). Each note says what changed in
that row's *reasoning* or *evidence obligations*. The cells above are left as
written, apart from row 6's added clause, because they are long and this is
the convention this file uses for dated notes.

- **Row 1.** The core protocol set and its settings match the organizers'
  "standard settings (common UART baud rates, SPI modes 0-3, I2C at 100 and
  400 kHz)" exactly. They add: "Running protocols concurrently, or supporting
  both controller and target roles, is a plus but not required." Target roles
  enter through row 13's stretch column. Concurrency is an area question
  (#129).
- **Row 2.** The organizers: "For USB and Ethernet, the more of the protocol
  work (line coding, CRC, clock recovery) your chip does itself, the better."
  The row's entry condition ("DR 0001's ISA can show a cycle budget") assumes
  pure firmware on today's ISA. #130 re-evaluates it with protocol-neutral ISA
  primitives in DR 0012's reserved control indices `0x10`–`0x1F`.
  *Update (DR 0015, Proposed, same day):* DR 0015 does that evaluation. With a
  CRC/LFSR step and an NRZI/bit-stuff unit, hand counts show a cycle budget
  for low-speed USB transmit, which it proposes TX-only. A Manchester
  transmit stage would give 10BASE-T transmit a budget too, but it serves
  one protocol and fails the record's admission test, so 10BASE-T is
  deferred, conditionally. Receive (clock recovery) is deferred to a
  separate record. The row's cells are unchanged and nothing numeric is
  bound; the hand counts are not measurements, the area figures are
  estimates, and the 10BASE-T edge-rate and jitter assumptions are
  unverified (#133).
- **Row 3.** This row constrains instruction *latency*, not branch
  *outcome*. DR 0001 already lets an outcome depend on data (the I2C ACK
  wait), so polling-based clock recovery is consistent with this row. Any
  hardware primitive admitted under #130 must still have a latency fixed by
  the instruction word. DR 0012's control-space accesses meet this: the
  latency is fixed per immediate index.
- **Row 5.** No change to the budget. The organizers confirm "24 digital
  pins … plus clock and reset" and 3.3 V I/O on the demo board. Pin *roles*
  should follow Tiny Tapeout's recommended Pmod pinouts
  (https://tinytapeout.com/specs/pinouts/), which DR 0010's plan does not
  (#133).
- **Row 6.** DR 0013 adds the boot-ROM path and a CRC check on every load,
  and keeps DR 0001's serial load unchanged as the recovery path. The
  "program-dump readback path" named in Checked by becomes DR 0012's `PM_*`
  read access and the `PM_CRC` exposure.
- **Row 7.** The rationale "judging rewards verification novelty, not size"
  no longer matches how the organizers describe judging: flexibility first,
  then protocols shown, unique architecture, and design and verification
  approach. They also confirm several SRAM macros are allowed, and say "Our
  planned maximum is 8x4 tiles. Design to 6x4 until the 8x4 template is
  out", with the 8×4 template expected "around mid-October" (issue #129).
  *Wording corrected 2026-10-10 (issue #85); it read "at least 6×4 tiles
  today, and 8×4 expected from mid-October".* The competition post itself
  still gives 6×4 as the current maximum and 8×4 only as a possibility. The 2×2 target stands;
  [`decision-records/0014`](decision-records/0014-area-beyond-2x2.md)
  (**Proposed**, issue #129) records what extra area would buy and
  recommends keeping 2×2 for now.
- **Row 8.** Source additionally: the organizers' "How will entries be
  judged?" answer, which says "A design with fewer protocols but a strong
  architecture and verification approach can definitely be competitive."
  Rows 13 and 14 add verification obligations (§7, §8 of the plan).
- **Row 9.** The organizers list the submission's required contents: a public
  repository with RTL, tests and a passing GDS/precheck from the Tiny Tapeout
  flow; architecture and instruction-set documentation; the assembler or
  toolchain with example programs; a verification write-up; and a description
  of how AI tools were used. A video or demo is optional. #134 tracks each one
  against a judge-facing artifact. The organizers also ask entrants to "stick
  to the Tiny Tapeout flow", which agrees with DR 0002's flow of record.
- **Rows 10–12.** The organizers: "there aren't characterized numbers for the
  pads". Any claim about pad edge rate is unverified until Tiny Tapeout
  publishes numbers. That affects row 11's SCLK ceiling at the pins (the
  f_clk/4 *core* timing is unaffected) and row 12's rise-time terms (#133).
  **Row 11's SCLK ceiling at the pins (f_clk/4 = 12.5 MHz at 50 MHz) is
  therefore unverified**, as is any 10BASE-T edge-rate assumption behind
  row 2; the core-side f_clk/4 cycle count is unaffected. The chip's pins are
  3.3 V digital only, so external parts (I2C pull-ups, transceivers, level
  shifters) go on a Pmod and must be documented (`docs/info.md`, "External
  hardware"; DR 0008 item 1; DR 0010). The numbers are tracked as an
  external dependency in `spec/gap-to-submission.md`. No row value changes.
- **State column.** The State cells of rows 1, 6 and 10–12 still say "no
  firmware" or "no RTL". `spec/gap-to-submission.md` records that firmware
  and RTL now exist and pass for most of those rows. Reconciling these cells
  against the evidence records is tracked as its own issue. This note only
  flags the drift.
  *Reconciled 2026-10-09 (issue #142):* the State cells of rows 1, 6 and
  10–12 now cite the newest evidence record for each claim. Each cell keeps
  its 2026-09-21 wording at the end, marked as superseded. No Target changed
  and no row moved to met. Those five cells are therefore no longer "left as
  written", as the introduction to these notes says.

## Dated notes — 2026-10-10 corrections from the two-key review (issue #85)

The two-key review of PR #84 (2026-10-08) did not release. Issue #85 lists
what the two keys required. The cells named below were corrected for that
review. **No Target is relaxed and no row moves to met.** Where a cell's
wording was replaced, the earlier wording is kept here, verbatim, so the
change can be read against it. Issue #85's items 1 and 4 (DR 0001's fetch
model and whether the act binds DR 0007) are questions about the scope of
the ratification act and are left to issue #44.

- **Row 4, State (item 3).** The 2026-10-02 cell gave "this spec is
  unratified" as a reason the row is unmet, which stops being true the
  moment the spec is ratified, and it did not say that the row names no
  corner set of its own. The cell now cites the newest evidence records and
  gives only reasons that hold whether or not this spec is ratified. Wording
  replaced:

  > Target [DR-4] — unmet; not carried as met. *Evidence wording updated
  > 2026-10-02 (issue #69); the Target column is unchanged.* **LibreLane
  > flow** (post-route, 20 ns): 50 MHz closes at all 3 corners that flow
  > emits for the macro-backed design, with 0 setup and 0 hold violations
  > (record
  > `verification/records/librelane-corner-timing/records/20261002-095445-21a2a63.md`).
  > That is 3 of the 6 `sg13cmos5l_stdcell` corners declared on 2026-09-21.
  > The other 3 (1.35 / 1.50 / 1.65 V) cannot be analysed for this design
  > because the program-memory macro ships no liberty above 1.32 V. **klt
  > flow**: no result (0 of 6 corners; blocked on klayout-tools#2635).
  > [`decision-records/0007`](decision-records/0007-row4-corner-set-under-the-macro.md)
  > (**Proposed**, unratified) proposes the 3 macro-characterized corners as
  > this row's corner set and records the fast corner's −40 °C / −55 °C
  > liberty pairing as a known approximation whose effect on hold is not
  > established. Three things keep this row unmet: DR 0007 is unratified,
  > this spec is unratified, and DR 0007's open item 1 is unresolved
- **Row 10, Target and Source (item 5).** The Source cell cited NXP AN10406
  as a UART note. AN10406 is "Accessing SD/MMC card using SPI on LPC2000"
  (Rev. 03, checked 2026-10-10) and does not mention UART or baud rate. The
  cell now derives the bound from Maxim Integrated tutorial 2141's
  clock-mismatch budget (fetched and read 2026-10-10) and says that 2 % is
  this repo's margin inside it. The Target's "under ~2%" is written as
  "≤ 2 %". That is the same value, which is the value the reference model
  already enforces (`MAX_FRAME_DRIFT_PCT = 2.0` in
  `verification/reference_models/uart.py`), so no evidence record changes.
  The derivation is arithmetic from a published tutorial, not a measurement,
  and no independent party has checked it yet. Wording replaced:

  > Target: Each bit sampled/driven within its nominal period at all
  > supported bauds; no formal tolerance body exists for UART, so this repo
  > adopts the common asynchronous-serial design practice of keeping
  > cumulative per-frame drift under ~2% of the bit period (UART tolerates
  > larger per-bit error than per-frame, since the receiver resynchronizes
  > on each start bit)
  >
  > Source: No owning standards body for UART bit-rate tolerance; general
  > practice per e.g. NXP AN10406 ("UART/USART asynchronous serial
  > communication") and common MCU datasheet guidance
- **Row 7, Stretch and Source (item 6).** The cells cited the competition
  post for an 8×4 ceiling. The post, re-read 2026-10-10, says 6×4 is the
  current maximum and 8×4 a possibility it is working on. The cells now
  quote it. The organizers' 2026-10-09 entrant email calls 8×4 the "planned
  maximum"; that is a plan, not the current rule, and the row-7 note above
  now quotes it as such. The 2×2 Target is unchanged. Wording replaced:

  > Stretch: Competition maximum is 8×4 tiles
  >
  > Source: Competition post (8×4 ceiling); README draft (2×2 internal
  > target, chosen because judging rewards verification novelty, not size)
- **Row 9, Target and Source (item 7).** The cells attributed Apache-2.0
  to the competition post. The post, re-read 2026-10-10, says only "Your
  submission should be open source" and names no licence. The cells now
  quote the post for open source, the template and the date, and say that
  Apache-2.0 is this repo's own choice (`LICENSE`). The Target still
  requires Apache-2.0, so nothing is relaxed. The Source cell also cited an
  issue in a private repository as the decision to admit this repo; that
  reference is removed, because a reader of this public spec cannot open
  it and it is not a source for the row's bound. Earlier wording, with that
  reference left out:

  > Target: Open source (Apache-2.0), via the Tiny Tapeout CMOS5L template,
  > due **2027-01-18**
  >
  > Source: Competition post (license + template + date); [reference to a
  > private-repository issue removed]
- **Rows 1, 2, 8 and 12, Source (item 8).** Rows 1, 2 and 8 put paraphrases
  of the competition post in quotation marks. They now quote the post as
  served on 2026-10-10, word for word. Row 12 cited UM10204 Rev. 6,
  Table 10. The current revision is Rev. 7.0 (1 October 2021), where the
  table is Table 11. The row now cites Rev. 7.0 Table 11; the Standard- and
  Fast-mode minimums for `t_LOW`, `t_HIGH`, `t_HD;STA`, `t_SU;STA` and
  `t_SU;STO` were read from it on 2026-10-10 (a Wayback Machine copy of
  NXP's PDF, because NXP's own URL returned 404) and are the same values
  the reference model `verification/reference_models/i2c.py` checks. The
  State cell's "Table 10" now says Table 11, with the Rev. 6 number in
  brackets. The model's own comments still say "Rev. 6, Table 10"; they
  are outside this docs-only change and still correct for Rev. 6. Wording
  replaced:

  > Row 1 Source: … "UART, SPI, I2C" named as the core set
  >
  > Row 2 Source: Same competition post: "low-speed USB and 10 Mbit
  > Ethernet are stretch"
  >
  > Row 8 Source: Competition post: judged on "novel approaches to design
  > and verification methodologies (formal methods, constrained random,
  > AI-assisted verification)"
  >
  > Row 12 Source: NXP UM10204 "I²C-bus specification and user manual,"
  > Rev. 6 (2014), Table 10 (Standard/Fast-mode AC characteristics)

## Ratification

> **2026-09-26 reconciliation — the act described in this section was not
> performed.** The PR carrying DR 0004 was **#29**; it merged (merge commit
> `8be9d1e`) with **zero** `RATIFY-KEY` reviews and without
> `loom:auto-merge-ok`. Everything from here to the end of this section is
> preserved verbatim as written on 2026-09-21 — read the first paragraph as
> the ratification this repo *intended*, not one it carried out. The second
> paragraph's *"it cannot substitute for the two keys"* and the third
> paragraph's *"this status is invalid until superseded by a later record that
> says so"* are the operative sentences, and they are reaffirmed, not relaxed.
> The later record is
> [`decision-records/0006-two-key-ratification-never-ran.md`](decision-records/0006-two-key-ratification-never-ran.md);
> the missing enforcement hook that let the merge happen is issue #45.

Ratified 2026-09-21 via the program's two-key mechanism (issue #17): an
**EE key** and a **market key**, neither held by the ratifying PR's author
or the design's author, each posted a `RATIFY-KEY` review on that PR; the
second key-holder's application released the PR for merge
(`loom:auto-merge-ok` + a consolidated ratification-record comment), and
the **merge commit is the ratification record**. The full per-row register
— every row's ratified state and the evidence behind it — is
[`decision-records/0004-target-spec-ratification.md`](decision-records/0004-target-spec-ratification.md);
the key skills that define the review procedure and the marker grammar each
review opens with are installed in this repo at
[`ratification/ee-key/SKILL.md`](../ratification/ee-key/SKILL.md) and
[`ratification/market-key/SKILL.md`](../ratification/market-key/SKILL.md).

An approval inside the ordinary Loom review pipeline (Judge, Champion) is a
**quality gate, not a ratification key** — it cannot substitute for the two
keys. If this file's Status reads `RATIFIED` but the ratifying PR's record
cannot show both key reviews, the ratification did not happen by mechanism,
and this status is invalid until superseded by a later record that says so.

Post-ratification, this spec binds: a change to any row here — a weaker
value, a dropped row, a reinterpreted source — is itself the kind of change
that goes through a decision record per `CLAUDE.md`'s "Spec changes go
through `spec/` with a decision record" rule, and a *relax of a
previously-ratified row to make a failing measurement pass* is the one
change the two-key review escalates rather than quietly accepts (the
relax-after-measured-FAIL check both key skills run at their Step 5).
