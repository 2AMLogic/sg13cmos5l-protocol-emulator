# Target Specification

Status: **RATIFIED** — proposed 2026-09-14 in issue #1; ratified
2026-09-21 in issue #17, via the program's two-key (EE + market) mechanism:
the ratification act is the two `RATIFY-KEY` reviews on the PR that carries
[`decision-records/0004-target-spec-ratification.md`](decision-records/0004-target-spec-ratification.md)
(neither key held by that PR's author or the design's author — the marker
convention both keys follow is documented in this repo's installed
[`ratification/ee-key/SKILL.md`](../ratification/ee-key/SKILL.md) and
[`ratification/market-key/SKILL.md`](../ratification/market-key/SKILL.md),
"Output format"), and the merge commit is the ratification record. The
ratification binds the **rows as targets** — every row's ratified state is
explicit in the State column below and in
[`decision-records/0004`](decision-records/0004-target-spec-ratification.md)'s
per-row register; no row is carried as *met* unless its State says so, and
the rows whose evidence does not exist yet (2, 10–12: no evidence at all;
4, 7: cell counts only, no STA or die-area number on either flow) are
ratified as targets with that said out loud. What made it a *spec* rather
than a wishlist before ratification still holds: every row carries a
citable source and a description of how the verification suite checks it,
per `spec/verification-plan.md`.

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
| 1 | Protocols emulated in firmware | UART (8N1, 9600–1,000,000 baud), SPI (modes 0–3, controller, SCLK ≤ f_clk/4), I2C (Standard-mode 100 kHz + Fast-mode 400 kHz, controller) | — | [Jane Street Protocol Emulator ASIC Competition post](https://blog.janestreet.com/protocol-emulator-asic-competition/): "UART, SPI, I2C" named as the core set | Constrained-random protocol-traffic suite (§4, verification-plan.md), one per protocol | Target [DR-4] — unmet (no RTL, firmware, or protocol suite yet; DR 0001's cycle-budget sketches are the sufficiency evidence) |
| 2 | Stretch protocols | — | Low-speed USB 1.1 (1.5 Mbit/s), 10BASE-T Ethernet (10 Mbit/s) | Same competition post: "low-speed USB and 10 Mbit Ethernet are stretch" | Not yet designed; enters this spec only if DR 0001's ISA can show a cycle budget for it (none shown yet — see gap tracker) | Stretch target [DR-4] — aim ratified, nothing numeric bound (no cycle-budget sketch exists; the row's own entry condition is unmet, so it commits to no value — ratified as a *target*, explicitly not met) |
| 3 | Timing determinism | No instruction's cycle latency depends on the data it operates on; every pin sample/drive and every `WAIT` lands on a cycle computable by reading the program alone | — | `spec/decision-records/0001-isa.md` (this repo's design commitment — no external body specifies CPU timing determinism) | Formal property `no_data_dependent_latency` (§2, verification-plan.md) | Target [DR-4] — unmet (a design commitment, now bound; the formal property itself is not yet written) |
| 4 | Core clock | ≥ 50 MHz timing closure on CMOS5L (flow of record per DR 0002) | 100 MHz | README draft baseline (2026-09-12 standup) informed by typical Tiny Tapeout `clock_hz` operating points; no shuttle-specific clock spec exists yet for the CMOS5L TT template | Static timing analysis in the flow-of-record's sign-off run (gate-level regression, §3, verification-plan.md) | Target [DR-4] — unmet; not carried as met (both flows have produced cell counts only, never a clock period or STA result — the 0004 register bars reading this row as met until one exists) |
| 5 | I/O pin budget | 8 dedicated inputs (`ui_in[7:0]`), 8 dedicated outputs (`uo_out[7:0]`), 8 bidirectional (`uio_in/out/oe[7:0]`), plus `clk`/`rst_n`/`ena` | — | [Tiny Tapeout CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), `tt_um_*` wrapper interface (fixed by the template, not negotiable) | cocotb functional suite instantiates the `tt_um_*` top exactly as the template defines it | Ratified [DR-4] — met at the stub level (`src/tt_um_2amlogic_protocol_emulator.v` drives the full fixed budget; protocol pin-role assignment is deliberately a later decision record) |
| 6 | Program storage | On-chip program memory, 256 × 16-bit words (512 bytes), addressed by an 8-bit PC; loaded serially over a dedicated input pin during a reset-gated load phase | Program memory backed by a Tiny Tapeout SRAM macro instead of flip-flops, if area allows | `spec/decision-records/0001-isa.md` §"Program memory sizing and loading" (sizing and load-protocol are this repo's own design call — no external spec governs it) | cocotb load-phase test (loads a known program, confirms readback via a program-dump instruction path) — not yet written, tracked in gap tracker | Target [DR-4] — unmet (no program-memory or load-phase RTL, and the load-phase test is unwritten; the sizing/load decision itself is bound via DR 0001) |
| 7 | Area | ≤ 2×2 Tiny Tapeout tiles (draft) | Competition maximum is 8×4 tiles | Competition post (8×4 ceiling); README draft (2×2 internal target, chosen because judging rewards verification novelty, not size) | Post-synthesis area report from the flow-of-record (§3, verification-plan.md). **Open gap**: exact tile pitch for the CMOS5L TT template is not yet confirmed in this repo — see gap tracker | Target [DR-4] — unmet; not carried as met (no die-area or floorplan number exists on either flow — cell counts are not area — the 0004 register bars reading this row as met; the tile-pitch half is resolved, the area half is open) |
| 8 | Verification | cocotb functional suite + gate-level regression on the flow-of-record; ≥1 formal property on the timing guarantees; constrained-random protocol traffic checked against an independent reference model per protocol | Silicon bring-up on the dev board after tape-out | Competition post: judged on "novel approaches to design and verification methodologies (formal methods, constrained random, AI-assisted verification)" | `spec/verification-plan.md` in full | Target [DR-4] — partially realized (cocotb harnesses and the gate-level regression exist and pass on the stub; the formal-property and constrained-random/reference-model artifacts do not exist yet) |
| 9 | Submission | Open source (Apache-2.0), via the Tiny Tapeout CMOS5L template, due **2027-01-18** | — | Competition post (license + template + date); 2AMLogic/2am#782 (operator decision to admit this repo as a canary) | `spec/gap-to-submission.md` tracks readiness against this date | Target [DR-4] — on track, deadline pending (license, template wiring, and the sign-off flow are green on the stub; the actual submission is due 2027-01-18) |
| 10 | UART bit-timing accuracy | Each bit sampled/driven within its nominal period at all supported bauds; no formal tolerance body exists for UART, so this repo adopts the common asynchronous-serial design practice of keeping cumulative per-frame drift under ~2% of the bit period (UART tolerates larger per-bit error than per-frame, since the receiver resynchronizes on each start bit) | — | No owning standards body for UART bit-rate tolerance; general practice per e.g. NXP AN10406 ("UART/USART asynchronous serial communication") and common MCU datasheet guidance | Reference-model comparison in the UART constrained-random suite (§4, verification-plan.md) measures actual vs. nominal bit timing from the cocotb waveform | Target [DR-4] — unmet, no evidence yet (the ~2% per-frame drift bound is adopted as a target; the UART suite that would measure it does not exist — ratified as a *target*, not carried as met) |
| 11 | SPI clock ceiling and modes | Controller mode, SCLK ≤ f_clk/4, all four clock-polarity/phase combinations (modes 0–3) | — | SPI has no formal owning standards body; the de facto reference is the Motorola/Freescale/NXP "SPI Block Guide" (V03.06) mode/timing conventions | SPI constrained-random suite (§4, verification-plan.md) sweeps all 4 modes against a reference SPI controller/peripheral model | Target [DR-4] — unmet, no evidence yet (modes 0–3 and the SCLK ceiling are bound as targets; the SPI suite that would check them does not exist — ratified as a *target*, not carried as met) |
| 12 | I2C timing | Standard-mode (100 kHz) and Fast-mode (400 kHz), controller role, meeting `t_LOW`, `t_HIGH`, `t_HD;STA`, `t_SU;STA`, `t_SU;STO` minimums | Fast-mode Plus (1 MHz) | NXP UM10204 "I²C-bus specification and user manual," Rev. 6 (2014), Table 10 (Standard/Fast-mode AC characteristics) | Formal property on ACK-window timing plus I2C constrained-random suite (§2 and §4, verification-plan.md) against an independent I2C reference model | Target [DR-4] — unmet, no evidence yet (the UM10204 minimums are bound as targets; the formal property and I2C suite do not exist — ratified as a *target*, not carried as met) |

## Ratification

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
