# Multi-protocol extra credit: an SWD debug probe on two turnaround lines

Status: **written 2026-11-20** for issue #452, from the catalog (#443). It
describes evidence that is in the repository. It does not mark target-spec
row 13 met: the row is Proposed and outside DR 0004's register. The row-13
stretch column's first evidence is
[`row13-ps2.md`](row13-ps2.md); its primary column is
[`row13-ws2812.md`](row13-ws2812.md).

## What the probe role asks

The catalog's SWD row asked for the chip as the **debug probe** (host): the
chip generates SWCLK, sends line reset and the JTAG-to-SWD switch, frames
8-bit requests with parity, and reads a target's ACK, data and parity
through **turnaround cycles** on a bidirectional data line. That is new
evidence beyond every earlier row in two directions: it is the first
firmware that **samples a line the other side clocks back at it** (the
probe drives SWCLK and reads SWDIO in the read phases), and the first that
**hands a line over mid-transaction and takes it back** — SWDIO is
push-pull while the probe drives it, released for the target's response
phases, re-driven after the read parity.

## Why the order was kept honest

The protocol choice was made by a dated note in
[DR 0018](../../spec/decision-records/0018-row13-protocol-choice.md) — the
note of 2026-11-19, **fourth revision** — before any SWD firmware existed,
checked against DR 0017's exclusion list and a `git grep` at the note's
parent commit. That note has its own history, recorded in full there: its
first draft concluded the probe side did not fit the 256-word store and was
**wrong** — it counted executed instructions instead of stored words. The
review of PR #456 corrected the arithmetic (two preloaded pin images make
one `OUT` per SWCLK transition; a loop stores its body once), measured the
fallback program with the committed assembler and ISA model, and reached
the opposite verdict: the agreed fallback fits with 55 words spare. The
committed program reproduces those figures exactly — **201 words, 218 SWCLK
rising edges, 1,182 model edges** — which is why the fourth revision's
counts are part of this file's evidence.

The freeze held: `scripts/check_isa_freeze.py` reports the same eleven
pinned files and the same eight amendments before and after this work, and
no RTL, assembler or ISA-model byte changed.

## What was built

| Item | Where |
|---|---|
| Program | [`firmware/asm/swd_probe.asm`](../../firmware/asm/swd_probe.asm) (201 words) |
| Independent model | [`verification/reference_models/swd.py`](../../verification/reference_models/swd.py): an **interactive** target written from Arm's ADIv5 description and pyOCD's observable connection shape (constants marked "confirm" — no copy of IHI 0031 is in the repository, the same caveat DR 0018 records). It takes SWDIO at the turnaround rise, advances it on every subsequent rise (the aggressive-but-legal IHI 0031 B4.3.1 corner that catches a probe sampling after the rise), releases after the read parity, and in the same pass grades the line resets, the switch, every request field, the turnarounds, host SWDIO stability and the trailing idle |
| Model self-test | [`verification/test_swd_model.py`](../../verification/test_swd_model.py) (20 cases, `npm run lint`) |
| Bench | [`verification/test_firmware_swd.py`](../../verification/test_firmware_swd.py) |
| Pad model | [`verification/uio_pads.py`](../../verification/uio_pads.py): pull-up on SWDIO (ADIv5 requires one), SWCLK pulled low, the other six `uio` pins tied low; contention is flagged, so a probe that keeps SWDIO driven into a response phase is caught electrically |
| Pin roles | `swd` phase in [DR 0010](../../spec/decision-records/0010-protocol-pin-roles.md): SWCLK `uio[2]`, SWDIO `uio[3]`, `pin_modes` UIO_DIR 0x0C / UIO_OD 0x00, held by the checker's `swd` profile |
| RTL evidence | [`firmware-swd` 20261120-032427-4cd1eb6](../../verification/records/firmware-swd/records/20261120-032427-4cd1eb6.md) — no gate-level run is claimed for this leg |

## What was measured

Every figure is read off the pads by the model, in core cycles x 20 ns
(target-spec row 4's unconfirmed 50 MHz target).

| Quantity | Measured | Held against |
|---|---|---|
| SWCLK high / low, line resets | 1 / 3 cycles | >= 50 cycles with SWDIO high per reset |
| SWCLK high / low, switch and requests | 2 / 2 cycles | SWDIO changes only while SWCLK low; stable across every rising edge |
| SWCLK high, response sample loop | 1 cycle (low 5..7) | samples taken in the SWCLK-low phase before the rise (IHI 0031 B4.3.1) |
| SWCLK rising edges, whole program | 218 | DR 0018's fourth revision |
| Report bytes | 72 | ACK 001, IDCODE 0x4BA00477 LSB first + even parity, ACK 001, 0x12345678 + even parity |
| Trailing idle before SWCLK stops | 8 clocks, SWDIO low | ADIv5's >= 8 |

The scenarios: the golden connection and both DP reads; the target
answering **WAIT (ACK 010)** and **FAULT (ACK 001)** — the committed shape
reports the ACK and the pull-up data phase faithfully and does not retry,
the choice DR 0018 records (the ACK branch is the documented legitimate
follow-up, absorbed by the 55-word margin, not built here). Five mutant
programs are each rejected for their own reason: a 49-clock first line
reset (the target stays dormant, `line-reset-short`), a flipped switch bit
(`switch-sequence`), a missing turnaround release (`no-release` **and** the
pad model's contention of both drivers), an inverted request parity bit
(`request-parity`, no response: the probe clocks the pull-up while the
first transaction stays clean), and a 3-clock trailing idle
(`trailing-idle-short`).

## What does not fit, on purpose

The catalog row's full goal — one **word of AP memory** — needs probe-driven
write transactions (SELECT, TAR) before the read. On the unrolled schedule
those do not fit beside the 91-word startup; a table-driven alternative
(stored pin images as data, a 15-word driver looping over them) is measured
for the data phase alone in DR 0018 and recorded there as the issue's next
step. It is not built here; the fallback this file evidences — line reset,
switch, and **two DP register reads** — is exactly the scope DR 0018's
review measured and issue #452's sizing note set.

## Wiring a target

Direct, same rail: the chip's I/O is 3.3 V on the Tiny Tapeout demo board
(`docs/info.md`, "External hardware") and common SWD targets are 3.3 V, so
no level shifter is needed — SWCLK to the target's SWCLK, SWDIO to the
target's SWDIO with a pull-up (about 10 kohm to 3.3 V; ADIv5 requires one,
and the probe tri-states SWDIO for the turnaround and response phases),
one common ground. A 5 V target would need level shifting. Receipt on real
silicon is out of scope: the claim this file points at is the cycle-exact
waveform at the pads against the scripted target, verified at RTL.
