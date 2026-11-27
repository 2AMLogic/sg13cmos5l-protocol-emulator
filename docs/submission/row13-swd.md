# Multi-protocol extra credit: an SWD debug probe on two turnaround lines

Status: **written 2026-11-20** for issue #452, from the catalog (#443);
**updated 2026-11-23** for issue #500, which extends the probe from the
IDCODE-and-DP-read fallback to one word of AP memory (the sections below say
which figures are the fallback's and which the extended image's). It
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
first committed program reproduced those figures exactly — 201 words, 218 SWCLK
rising edges, 1,182 model edges. Review of PR #501 then added the ACK branch
(a WAIT or FAULT must end the transfer, not clock a data phase that is not
there), so the fallback program was **227 words, 218 SWCLK rising edges
on the OK path, 1,179 model edges**; the 201-word figures are the first
revision's, kept in its superseded record. Issue #500 then answered the
question that note left: a **table-driven** probe, with the five
transactions of a memory-word read, was **245 words** (105 code, 140 table),
**356 SWCLK rising edges**, with 11 words spare; the review's full-ACK check
(a silent or invalid ACK never gets write data) uses them: **256 words**
(116 code, 140 table), the same 356 rising edges.

The freeze held: `scripts/check_isa_freeze.py` reports the same eleven
pinned files and the same eight amendments before and after this work, and
no RTL, assembler or ISA-model byte changed.

## What was built

| Item | Where |
|---|---|
| Program | [`firmware/asm/swd_probe.asm`](../../firmware/asm/swd_probe.asm) (256 words, table-driven) |
| Independent model | [`verification/reference_models/swd.py`](../../verification/reference_models/swd.py): an **interactive** target written from Arm's ADIv5 description and pyOCD's observable connection shape (constants marked "confirm" — no copy of IHI 0031 is in the repository, the same caveat DR 0018 records). It takes SWDIO at the turnaround rise, advances it on every subsequent rise (the aggressive-but-legal IHI 0031 B4.3.1 corner that catches a probe sampling after the rise), releases after the response, decodes the requests against a DP and one MEM-AP (`MemAp`: SELECT and TAR have no reset value, the DRW read is posted, only RDBUFF returns the addressed word, CSW starts in the word-access state), takes the 33-bit write data, and in the same pass grades the line resets, the switch, every request field, the turnarounds, host SWDIO stability and the trailing idle |
| Model self-test | [`verification/test_swd_model.py`](../../verification/test_swd_model.py) (37 cases, `npm run lint`) |
| Bench | [`verification/test_firmware_swd.py`](../../verification/test_firmware_swd.py) |
| Pad model | [`verification/uio_pads.py`](../../verification/uio_pads.py): pull-up on SWDIO (ADIv5 requires one), SWCLK pulled low, the other six `uio` pins tied low; contention is flagged, so a probe that keeps SWDIO driven into a response phase is caught electrically |
| Pin roles | `swd` phase in [DR 0010](../../spec/decision-records/0010-protocol-pin-roles.md): SWCLK `uio[2]`, SWDIO `uio[3]`, `pin_modes` UIO_DIR 0x0C / UIO_OD 0x00, held by the checker's `swd` profile |
| RTL evidence | [`firmware-swd` 20261124-151332-ddf433e](../../verification/records/firmware-swd/records/20261124-151332-ddf433e.md) — no gate-level run is claimed for this leg |

## What was measured

Every figure is read off the pads by the model, in core cycles x 20 ns
(target-spec row 4's unconfirmed 50 MHz target). The extended image
(issue #500):

| Quantity | Measured | Held against |
|---|---|---|
| Stored words | 256 of 256 (116 code, 140 table) | DR 0001's program memory |
| SWCLK high / low, line resets | 1 / 3 cycles (2 low on the second reset's first clock) | >= 50 cycles with SWDIO high per reset |
| SWCLK high / low, switch, requests, write data | 7 / 2 cycles | SWDIO changes only while SWCLK low; stable across every rising edge |
| SWCLK high, response sample loop | 1 cycle (low 4..7) | samples taken in the SWCLK-low phase before the rise (IHI 0031 B4.3.1) |
| SWCLK rising edges, whole program | 356; last SWCLK fall at core edge 2,615 | the bench |
| Write payloads, from the pads | SELECT 0x00000000 and TAR 0x20000004, each LSB first + even parity (33 bits) | the model's DP / MEM-AP decode |
| Report bytes (five transactions) | ACK OK (wire order 1,0,0) each; IDCODE 0x4BA00477; **DRW read 0xA5A5C3C3 (the stale buffer, not the word)**; **RDBUFF 0xCAFEF00D (the addressed word)**; each read with even parity | independent model; posted-read semantics |
| Trailing idle before SWCLK stops | 8 clocks, SWDIO low | ADIv5's >= 8 |

The scenarios: the golden connection and all five transactions; **each of
the five transactions in turn** answered **WAIT (wire 0,1,0)** or
**FAULT (wire 0,0,1)** — the probe branches on the first ACK bit, reports
the three ACK samples, releases the return turnaround, re-drives SWDIO low
and ends the transfer with the eight idle clocks (no data slots and no write
data, no retry; CTRL/STAT.ORUNDETECT = 0). A rejected write changes no
state in the model and the memory word is never read or reported. ACK wire
order: OK numeric 0b001 is sent LSB first, so 1,0,0. Mutant programs are
each rejected for their own reason: a 49-clock first line reset (the target
stays dormant, `line-reset-short`), a flipped switch bit
(`switch-sequence`), a missing turnaround release (`no-release` **and** the
pad model's contention of both drivers), an inverted request parity bit
(`request-parity`, no response: the probe clocks the pull-up while the
earlier transactions stay clean), a flipped SELECT or TAR write-data parity
bit (`write-parity`; the write is discarded and the later access fails for
it — `ap-not-selected` / `tar-unset` — so no memory word is returned), a
broken ACK-to-write-data handoff (`write-data-not-driven`), and a 3-clock
trailing idle (`trailing-idle-short`); two more cover the PR #501
review's findings: the ACK branch removed (data slots clocked after a WAIT,
`line-released-after-transfer`) and SWDIO driven on the return turnaround
(`return-turnaround-driven`).

The MEM-AP's **word-access starting state** is the model's assumption, stated
in `reference_models/swd.py`: CSW.Size = 0b010 (32-bit), CSW.AddrInc = 0b00,
CSW never written by the probe. A real part's CSW reset is
implementation-defined; the ADIv5 register addresses and fields carry the
same "confirm" mark as the other constants (no copy of IHI 0031 is in the
repository).

## What the extended image still does not do

Out of scope, as the issue states: any RTL or ISA change (frozen by DR
0017), multi-drop, sticky-error recovery beyond one retry (the probe does
not retry at all), and MEM-AP auto-increment bursts. The probe reads **one**
fixture word at a fixed TAR; reading a second address would mean another
table row (eleven words per read transaction) or a data-driven TAR, neither
built here. Silicon receipt is out of scope: the claim is the cycle-exact
waveform at the pads against the independent model, verified at RTL.

## Wiring a target

Direct, same rail: the chip's I/O is 3.3 V on the Tiny Tapeout demo board
(`docs/info.md`, "External hardware") and common SWD targets are 3.3 V, so
no level shifter is needed — SWCLK to the target's SWCLK, SWDIO to the
target's SWDIO with a pull-up (about 10 kohm to 3.3 V; ADIv5 requires one,
and the probe tri-states SWDIO for the turnaround and response phases),
one common ground. A 5 V target would need level shifting. Receipt on real
silicon is out of scope: the claim this file points at is the cycle-exact
waveform at the pads against the scripted target, verified at RTL.
