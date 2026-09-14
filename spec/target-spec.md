# Target Specification

Status: **DRAFT** — proposed 2026-09-14 in issue #1, awaiting ratification
through the program's two-key mechanism (one agent proposes, a second
independent key holder — human or a distinct agent role — signs off before
Status moves to `RATIFIED`). Until ratified, every row below may still move;
what makes it a *spec* rather than a wishlist is that every row already
carries a citable source and a description of how the verification suite
checks it, per `spec/verification-plan.md`.

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

## Rows

| # | Parameter | Target | Stretch | Source | Checked by |
|---|---|---|---|---|---|
| 1 | Protocols emulated in firmware | UART (8N1, 9600–1,000,000 baud), SPI (modes 0–3, controller, SCLK ≤ f_clk/4), I2C (Standard-mode 100 kHz + Fast-mode 400 kHz, controller) | — | [Jane Street Protocol Emulator ASIC Competition post](https://blog.janestreet.com/protocol-emulator-asic-competition/): "UART, SPI, I2C" named as the core set | Constrained-random protocol-traffic suite (§4, verification-plan.md), one per protocol |
| 2 | Stretch protocols | — | Low-speed USB 1.1 (1.5 Mbit/s), 10BASE-T Ethernet (10 Mbit/s) | Same competition post: "low-speed USB and 10 Mbit Ethernet are stretch" | Not yet designed; enters this spec only if DR 0001's ISA can show a cycle budget for it (none shown yet — see gap tracker) |
| 3 | Timing determinism | No instruction's cycle latency depends on the data it operates on; every pin sample/drive and every `WAIT` lands on a cycle computable by reading the program alone | — | `spec/decision-records/0001-isa.md` (this repo's design commitment — no external body specifies CPU timing determinism) | Formal property `no_data_dependent_latency` (§2, verification-plan.md) |
| 4 | Core clock | ≥ 50 MHz timing closure on CMOS5L (flow of record per DR 0002) | 100 MHz | README draft baseline (2026-09-12 standup) informed by typical Tiny Tapeout `clock_hz` operating points; no shuttle-specific clock spec exists yet for the CMOS5L TT template | Static timing analysis in the flow-of-record's sign-off run (gate-level regression, §3, verification-plan.md) |
| 5 | I/O pin budget | 8 dedicated inputs (`ui_in[7:0]`), 8 dedicated outputs (`uo_out[7:0]`), 8 bidirectional (`uio_in/out/oe[7:0]`), plus `clk`/`rst_n`/`ena` | — | [Tiny Tapeout CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l), `tt_um_*` wrapper interface (fixed by the template, not negotiable) | cocotb functional suite instantiates the `tt_um_*` top exactly as the template defines it |
| 6 | Program storage | On-chip program memory, 256 × 16-bit words (512 bytes), addressed by an 8-bit PC; loaded serially over a dedicated input pin during a reset-gated load phase | Program memory backed by a Tiny Tapeout SRAM macro instead of flip-flops, if area allows | `spec/decision-records/0001-isa.md` §"Program memory sizing and loading" (sizing and load-protocol are this repo's own design call — no external spec governs it) | cocotb load-phase test (loads a known program, confirms readback via a program-dump instruction path) — not yet written, tracked in gap tracker |
| 7 | Area | ≤ 2×2 Tiny Tapeout tiles (draft) | Competition maximum is 8×4 tiles | Competition post (8×4 ceiling); README draft (2×2 internal target, chosen because judging rewards verification novelty, not size) | Post-synthesis area report from the flow-of-record (§3, verification-plan.md). **Open gap**: exact tile pitch for the CMOS5L TT template is not yet confirmed in this repo — see gap tracker |
| 8 | Verification | cocotb functional suite + gate-level regression on the flow-of-record; ≥1 formal property on the timing guarantees; constrained-random protocol traffic checked against an independent reference model per protocol | Silicon bring-up on the dev board after tape-out | Competition post: judged on "novel approaches to design and verification methodologies (formal methods, constrained random, AI-assisted verification)" | `spec/verification-plan.md` in full |
| 9 | Submission | Open source (Apache-2.0), via the Tiny Tapeout CMOS5L template, due **2027-01-18** | — | Competition post (license + template + date); 2AMLogic/2am#782 (operator decision to admit this repo as a canary) | `spec/gap-to-submission.md` tracks readiness against this date |
| 10 | UART bit-timing accuracy | Each bit sampled/driven within its nominal period at all supported bauds; no formal tolerance body exists for UART, so this repo adopts the common asynchronous-serial design practice of keeping cumulative per-frame drift under ~2% of the bit period (UART tolerates larger per-bit error than per-frame, since the receiver resynchronizes on each start bit) | — | No owning standards body for UART bit-rate tolerance; general practice per e.g. NXP AN10406 ("UART/USART asynchronous serial communication") and common MCU datasheet guidance | Reference-model comparison in the UART constrained-random suite (§4, verification-plan.md) measures actual vs. nominal bit timing from the cocotb waveform |
| 11 | SPI clock ceiling and modes | Controller mode, SCLK ≤ f_clk/4, all four clock-polarity/phase combinations (modes 0–3) | — | SPI has no formal owning standards body; the de facto reference is the Motorola/Freescale/NXP "SPI Block Guide" (V03.06) mode/timing conventions | SPI constrained-random suite (§4, verification-plan.md) sweeps all 4 modes against a reference SPI controller/peripheral model |
| 12 | I2C timing | Standard-mode (100 kHz) and Fast-mode (400 kHz), controller role, meeting `t_LOW`, `t_HIGH`, `t_HD;STA`, `t_SU;STA`, `t_SU;STO` minimums | Fast-mode Plus (1 MHz) | NXP UM10204 "I²C-bus specification and user manual," Rev. 6 (2014), Table 10 (Standard/Fast-mode AC characteristics) | Formal property on ACK-window timing plus I2C constrained-random suite (§2 and §4, verification-plan.md) against an independent I2C reference model |

## Ratification

This file's `Status:` line is the ratification record. Moving it from
`DRAFT` to `RATIFIED` requires the program's two-key sign-off; until then,
every downstream decision record and the verification plan build on these
rows provisionally, and a change to any row here is itself the kind of
change that goes through a decision record per `CLAUDE.md`'s "Spec changes
go through `spec/` with a decision record" rule.
