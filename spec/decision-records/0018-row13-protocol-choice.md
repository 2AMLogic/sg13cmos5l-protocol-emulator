# 0018: Row 13 Protocol Choice — WS2812 (Single-Wire NRZ LED Data)

Status: **Proposed 2026-10-10.** Like DRs 0001–0005, 0007, 0008 and 0010–0017,
this record is a proposal. The two-key (`RATIFY-KEY`) mechanism has never run
in this repository (DR [`0006`](0006-two-key-ratification-never-ran.md),
issue #44). It changes no RTL, no pinned file of DR 0017's freeze, and no
target-spec value. It makes no row met.
Date: 2026-10-10
Issues: #141 (part 2: choose and build row 13's protocol); #134 (judge-facing
write-up); #44 (ratification).

**Numbering note.** When this record was numbered (2026-10-10), `origin/main`
had DRs 0001–0008 and 0010–0017, and open draft PR #84 reserved 0009. No other
open PR carries a decision record, so this record is 0018, the first number
DR 0017 leaves for later records.

**Order of commits.** This record is committed on its own, before any WS2812
firmware, bench or reference model exists in the repository. Its parent is
the freeze commit below. The firmware and its evidence come in later commits
on the same branch.

## Context

Target-spec row 13 asks for at least one protocol that is not in rows 1–2 and
"was not considered when the ISA was designed", built as firmware only (no RTL
change) and graded by an independent reference model with timing checked.
"The choice is recorded *after* the ISA is frozen for submission, so it cannot
shape the ISA."

DR [`0017`](0017-submission-isa-freeze.md) is that freeze. Its section 6
("Row 13: how the protocol is chosen") sets three rules for this record:

1. The protocol and the reasoning are recorded in a commit after DR 0017 has
   merged, and the record cites DR 0017's merge commit as the freeze.
2. The primary protocol must not be any protocol in DR 0015's tables, any
   protocol DR 0015 marks ineligible, or any of rows 1–2's protocols.
3. It must not be a protocol the pinned ISA records were designed around
   (DR 0012's Context, DR 0013's loads and its Open item 2).

The same lists are machine-readable in
[`spec/isa-freeze.json`](../isa-freeze.json), `row13_excluded_protocols`.

## Decision (proposed)

### 1. The freeze this choice follows

- **Freeze commit:** `1696045bfa1a33f93c95a5bf6c29b05f4ea0d734`, the merge of
  PR #233 (DR 0017, issue #141 part 1), 2026-10-10 23:13:29 UTC. DR 0017's
  pins were taken from its base `e74d2b656de35e492e6f7b3e34cbe2266b4aeff3`,
  and `scripts/check_isa_freeze.py` reports that all eleven pinned files at
  this record's parent still match, with 0 amendments.
- **This choice postdates it.** This record's commit has the freeze commit as
  its parent. Nothing in the freeze names WS2812 as a target, and no pinned
  file changes in this record or in the work that builds on it. That work is
  firmware, a bench, a reference model and records only. If a later change to
  a pinned file is needed, it goes through DR 0017 section 4 with a record
  numbered 0019 or later. It is not folded into this one.

### 2. The primary protocol: WS2812

Row 13's primary protocol is **WS2812**, the single-wire, self-clocked LED
data protocol of the Worldsemi WS2812 / WS2812B addressable RGB LEDs. It is
graded against the **WS2812B** datasheet's timing, which is the conservative
of the WS2812 timings:

| Symbol | Meaning | Value | Tolerance |
|---|---|---|---|
| T0H | `0` code, high time | 0.40 µs | ±150 ns |
| T1H | `1` code, high time | 0.80 µs | ±150 ns |
| T0L | `0` code, low time | 0.85 µs | ±150 ns |
| T1L | `1` code, low time | 0.45 µs | ±150 ns |
| TH + TL | one bit | 1.25 µs | ±600 ns |
| RES | low time that latches the frame (reset code) | above 50 µs | — |

Source: Worldsemi, *WS2812B Intelligent control LED integrated light source*
datasheet, "Data transfer time" table and the "Composition of 24bit data"
note, as distributed by Adafruit
(`https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf`, 5 pages; the copy
read for this record has sha256
`670517e400d01f76e91187e173c9bb105e5470741604f81243364c5f13d37448`). Each
pixel takes 24 bits in the order G7…G0, R7…R0, B7…B0, most significant bit
first. The first pixel keeps the first 24 bits and passes the rest on.

**Reset time.** The graded bound is the datasheet's "above 50 µs". Later
WS2812B parts are widely reported to need about 280 µs. This record has not
checked that figure against a primary source, so it is not a graded bound.
The firmware still holds the line low for more than 280 µs between frames.
That costs one loop count, and it means the program does not depend on which
revision of the part is on the board.

**What is in scope.** The controller (transmit) side only: one output pin,
`N` pixels of 24-bit GRB data, refreshed repeatedly with a reset between
frames. A WS2812 controller only drives the line, so the ISA's output timing
alone decides whether this works. The 50 MHz clock is target-spec row 4's
target, which is not confirmed. The firmware's claim is in core cycles, as for
rows 1 and 10–12, and every nanosecond figure is cycles × 20 ns.

### 3. Why WS2812 is allowed

**Not in rows 1–2.** Rows 1–2 are UART, SPI controller, I2C controller,
USB and 10BASE-T.

**Not in DR 0015's tables or its ineligible lists.** It is not in the P1 table
(USB, Ethernet, the DR 0013 load CRC, 1-Wire, SMBus, Modbus RTU, HDLC/PPP, SD,
CAN, BLE), the P2 list (USB, HDLC/PPP/SDLC, CAN, NRZI-coded links in general),
the P3 table and prose (10BASE-T and the other 802.3 Manchester PHYs,
RC-5/RC-6 and Manchester/IR generally, DALI, MIL-STD-1553), the P4 list
(USB, 10BASE-T and RC-5 receive, DMX512, LIN, CAN receive, 1-Wire slot
sampling, UART receive), or the baseline, result and verdict tables
(low-speed USB and 10BASE-T). It is not caught by "NRZI-coded links in
general" either. The datasheet calls its coding "NZR", but it is a pulse-width
code: every bit is one high pulse followed by a low, and the bit's value is the
width of the high pulse. NRZI encodes a bit as a level change or no change and
has no fixed pulse per bit. WS2812 is not Manchester coding either: a bit has
one rising edge at its start whatever its value, not a mid-bit transition
whose direction is the value.

**Not a protocol the ISA records were designed around.** DR 0012's Context
names 1-Wire, a target-role SPI and a QSPI flash. DR 0013 builds a UART load
frame and an SPI-flash read, and its Open item 2 names I2C-target and
SPI-target loads. WS2812 is none of these.

**Not considered when the ISA was designed.** A search of the whole
repository and its history at the freeze commit (`git grep -i ws2812`, and
`git log --all -G ws2812 -i`) finds WS2812 in exactly three places, all added
on 2026-10-09, after DR 0001 (2026-09-14) had fixed the instruction set and
its timing model:

| Where | Commit | What it says |
|---|---|---|
| `spec/target-spec.md` row 13 | `a9a495cb` (2026-10-09) | WS2812 is one of row 13's four candidates |
| `docs/submission/README.md` D6 | `024c92ad` (2026-10-09) | WS2812 is an example of a protocol "the ISA was **not** designed for" |
| DR 0015, "Interaction with other records and rows" | `24e9ff0a` (2026-10-09) | Row 13's choice "must come from outside this record (for example WS2812-style single-wire timing …)" |

None of the three weighs WS2812 against an instruction, a primitive or a
cycle budget. DR 0015 names it as an example of something **outside** its
analysis. The pinned ISA-defining files (DRs 0001, 0005, 0012, 0013, 0015's
tables, 0016, `rtl/protocol_core.v`, `rtl/protocol_program_memory.v`, the
top, `firmware/tools/asm.py`, `verification/reference_models/isa.py`) do not
mention it, apart from DR 0015's one sentence. A search of the issue and PR
tracker for "ws2812" finds only #141 (this work) and #134 (the submission
tracker that points at row 13). DR 0001's cycle-budget sketches, the evidence
the ISA was sized on, cover UART, SPI and I2C only.

**It tests what the ISA claims.** DR 0001's central claim is that a programmer
can predict, from the instruction stream alone, the exact cycle on which every
pin write happens. WS2812 has no clock line and no handshake. The receiver
decides each bit by measuring a high pulse against a ±150 ns window (±7.5 core
cycles at 20 ns), so every pulse the program makes is graded as a width. A
bit-banged WS2812 driver on a conventional microcontroller usually needs
interrupts off and hand-counted cycles. Here the guarantee is the ISA's: no
instruction's latency depends on data (target-spec row 3).

### 4. What is not chosen here

- **The stretch column** (a role or pin direction the core protocols never
  use, which exercises DR 0012's runtime pin direction) is not chosen here.
  WS2812 is output-only push-pull, so it is evidence for the primary column
  only. The stretch is left to a follow-up issue, and its candidates must be
  checked against the same exclusion list.
- **Row 13's other candidates** are 1-Wire, DMX512 and Manchester/IR. All
  three are excluded by DR 0017 section 6 (DR 0015's tables), so WS2812 is the
  only one of row 13's four listed candidates that remains.

## Alternatives considered

1. **A protocol that is not on row 13's list** (for example a PWM servo
   train, a seven-segment multiplex, or a stepper-motor sequence). Such a
   protocol would meet the "not considered" rule. Rejected as the primary:
   none has a datasheet timing window as tight as WS2812's, so none tests the
   ISA's timing claim as hard. Row 13 also lists WS2812 by name, so a judge
   can recognise it.
2. **Wait for the stretch and choose one protocol for both columns.** Rejected.
   The stretch's natural candidates (1-Wire, target-role SPI or I2C) are
   excluded from the primary column (DR 0017 section 6), so one protocol
   cannot serve both. The primary should not wait for the harder column.
3. **Grade against the WS2812 (non-B) timing or the 280 µs reset.** Rejected
   for the graded bound. The WS2812B values are the conservative ones that this
   repository could check against a primary source. The 280 µs reset is met as
   margin (section 2), not graded.

## Consequences

- Issue #141 part 2 builds `firmware/asm/ws2812*.asm`, an independent WS2812B
  reference model written from the table in section 2, and a cocotb bench
  that runs at RTL and on the gate-level netlist, with negative controls. The
  results are evidence records under `verification/records/`.
- Target-spec row 13 is not marked met by this record. Its State column moves
  only by the evidence, and the row itself stays Proposed until the two-key
  act runs (#44). Its stretch column stays open.
- If a pinned file changes after this record, DR 0017 section 4 item 3
  decides whether the change invalidates this protocol's evidence.

## Open items

1. **The 280 µs reset figure** (section 2) has no primary source in this
   repository. If one is found, a dated note here can record it. The firmware
   already meets it.

## Dated note 2026-10-11 (issue #235): the stretch column's protocol is the PS/2 device

Status: Proposed, like the rest of this record. It changes no RTL, no pinned
file of DR 0017's freeze and no target-spec value, and it makes no row met.
This note is committed before any PS/2 firmware, bench or reference model
exists. Its parent is `origin/main` at `39287e2c`, which contains the freeze
commit `1696045bfa1a33f93c95a5bf6c29b05f4ea0d734`; `python3
scripts/check_isa_freeze.py` reports the same eleven pinned files and the same
two amendments before and after this note.

Section 4 above left the stretch column to a follow-up. Issue #235 is that
follow-up. Row 13's stretch column asks for "a protocol in a role or pin
direction the core protocols never use".

### What is chosen

**The device side of the PS/2 keyboard/mouse interface**, graded against Adam
Chapweske, *The PS/2 Mouse/Keyboard Protocol* (1999), read at
`https://www.burtonsys.com/ps2_chapweske.htm` (the copy read for this note has
sha256 `0010e2a50bb08b8b0d59207f582d08ec459f301d4d217ab9b110b0f4eac9a284`).
That page says it comes from the author's experience and that IBM's manual was
not available to him, so it is a secondary description of a de facto
interface. It is the best primary-quality text this repository could check.
The model's limits are quoted from it, and a reader who holds the IBM manual
can check them there.

The firmware plays the keyboard or mouse. The model plays the host.

### Why this meets the stretch column

The core protocols (UART, SPI controller, I2C controller, WS2812) never do any
of the three things below. The PS/2 device does all three on two lines:

1. **It generates a clock on an open-drain line that the other side may hold
   low.** The device owns the clock, but the host can inhibit it by holding
   CLK low for 100 µs or more, and the device must notice, abort the frame
   and release DATA. I2C's controller can see a peripheral stretch SCL, but
   a stretch there pauses a bit and does not cancel a frame.
2. **It turns a data line around mid-transaction, on a schedule set by the
   other side.** In host-to-device frames the host drives DATA for eight data
   bits, parity and stop. The device then pulls DATA low as the ACK bit, in
   the high phase of the 11th clock, and releases both lines.
3. **It samples a data line the other side drives, on a clock the device
   itself generates.** The host changes DATA while CLK is low, and the device
   reads it while CLK is high. The device-to-host direction is the reverse
   (device writes while CLK is high, host reads while CLK is low), so one
   program does both phase relationships.

All of it uses DR 0012's runtime `UIO_OD`: both pins open-drain, the program
releases a line by writing 1 and pulls it low by writing 0. It also reads
`uio_in` to learn whether the line is really high, which is the case the pad
model (`verification/uio_pads.py`) resolves from the design's `uio_oe`,
`uio_out` and the host's driver, with a pull-up on each line.

### Exclusion check (DR 0017 section 6; the rules are the same as for WS2812)

The stretch column is not bound by the primary column's exclusion list, but
the issue asks for the same check, and a protocol the ISA records named would
say little about "not designed for".

- **Rows 1-2:** UART, SPI controller, I2C controller, USB, 10BASE-T. PS/2 is
  none of them. It is a synchronous two-wire interface, but I2C's start and
  stop conditions, addressing and per-byte ACK-by-the-receiver have no
  counterpart in it, and the clock owner differs.
- **DR 0015's tables and ineligible lists** (`spec/isa-freeze.json`,
  `row13_excluded_protocols.dr_0015`): PS/2 is not named, and it is not a
  coded-line scheme (NRZI, Manchester) or a CRC protocol. It has one odd
  parity bit per byte and no CRC.
- **The protocols the ISA records were designed around**
  (`row13_excluded_protocols.isa_design_records`): target-role SPI, the
  I2C-target and SPI-target loads, the SPI flash read and the UART load
  frame. PS/2 is none of them.
- **Search:** `git grep -i -E 'ps/2|ps2'` over the repository at this note's
  parent finds the string in `spec/gap-to-submission.md` row 13 (the line
  that lists this issue's candidates, added 2026-10-11) and in a Loom hook
  test (an unrelated tool). It is in no spec, decision record, firmware,
  bench or model before then.

### Why not the other candidates

- **PS/2 host:** a controller that inhibits and requests. It exercises the
  same two lines but the device role is the harder half (the clock source and
  the ACK), so the device is the more demanding firmware.
- **SWD target:** it would sample a clock it does not generate, which neither
  PS/2 role does, so it is the only candidate that covers that part of the
  column. It is a larger build (line reset, the request packet, parity, ACK
  and turnaround cycles, a data phase) and is not chosen here. It stays a
  candidate for a later increment if the deadline allows (CLAUDE.md,
  deadline discipline).
- **MDIO PHY side:** the issue notes that it is part of IEEE 802.3, and DR
  0015 excludes "other 802.3 Manchester PHYs". MDIO is not a Manchester PHY,
  but the reviewer was asked to confirm that the exclusion does not reach it.
  That has not been confirmed, so it is not chosen.
- **Target-role SPI or I2C, 1-Wire:** valid stretch evidence by the issue's
  text, but they are the protocols DR 0012 was designed around, so they say
  less about "not designed for".

### What is graded, and what is not

Graded (the model's limits, each cited to Chapweske's page):

| Quantity | Limit |
|---|---|
| CLK high, CLK low (device generated) | 30 to 50 µs each |
| Frame, device to host | start 0, eight data bits LSB first, odd parity, stop 1; 11 clocks including the stop |
| Data change after a CLK rising edge | at least 5 µs |
| Data change before the next CLK falling edge | at least 5 µs and at most 25 µs |
| Device may start a transmission | only after CLK and DATA have both been high, CLK continuously for at least 50 µs |
| Host inhibit | CLK held low for 100 µs or more; the device must abort a frame inhibited before its 11th clock, release DATA, and send nothing until CLK has been high 50 µs |
| Host request to send | CLK low 100 µs or more, then DATA low, then CLK released; the device must begin clocking (the page allows 15 ms; the bench checks that the device does so well within the 10 ms polling bound) |
| Frame, host to device | eight data bits LSB first, odd parity, stop 1, read by the device while CLK is high |
| ACK | the device pulls DATA low in the high phase of the 11th clock, with the CLK fall 5 to 25 µs later, and releases both lines after that pulse |
| Contention | the design only ever pulls CLK and DATA low and drives no other pin, and the pad model (`verification/uio_pads.py`) reports no fight between the design and the host |

Not graded, and stated as limits of this increment: the keyboard and mouse
command sets above the byte layer (the program answers a command byte by
echoing it, or with 0xFE "resend" on a parity or stop error, which is a
bench-visible behaviour and not a claim to be a keyboard); the device's
handling of a host that never releases DATA after the ACK (the page says the
device keeps clocking; this program does not); a 16-byte output buffer (the
program holds one pending byte); clock timing at an electrical level (the pad
model has zero delay and ideal pull-ups, and no pad's real rise time is
measured). The 50 MHz clock is row 4's target and is not confirmed, so every
microsecond figure is core cycles times 20 ns.

### Consequences

- Issue #235 builds `firmware/asm/ps2_device.asm`, an independent PS/2 host
  model written from the table above, a cocotb bench at RTL and at gate level
  with negative controls, and the append-only records. Pin roles go into DR
  0010's table as a `ps2` phase.
- Row 13 stays Proposed. The stretch column then has a candidate with
  evidence. It is not marked met by this note.
- If a pinned file changes after this note, DR 0017 section 4 item 3 decides
  whether the change invalidates this evidence.

## Dated note 2026-11-19 (issue #452): the SWD probe examined — first arithmetic corrected; the agreed fallback fits

Status: Proposed, like the rest of this record. It changes no RTL, no pinned
file of DR 0017's freeze and no target-spec value, and it makes no row met.
This note is committed before any SWD firmware, bench or reference model
exists — and none is created by the work it records. Its parent at the
note's first commit was `origin/main` at `ff4029fb`; the branch has since
merged `origin/main` through `aeb90997` and then `325447e7`, which
contain the same freeze commit
`1696045bfa1a33f93c95a5bf6c29b05f4ea0d734`; `python3
scripts/check_isa_freeze.py` reports the same eleven pinned files and the
same amendments before and after this note, re-run at each parent.

Issue #452 asked for the other half of SWD: the chip as the **debug probe**
(host) — line reset, JTAG-to-SWD switch, an 8-bit request with parity, and a
read of a target's IDCODE through turnaround cycles and an ACK. DR 0018's
PS/2 note (above) had left the SWD *target* as a candidate for a later
increment and said why it was not chosen then ("a larger build"). This note
is the examination that note deferred.

**Revision, same day, before merge.** The first draft of this note (the
original revision of PR #456) concluded "the probe side does not fit the
256 × 16 program memory at any size". That conclusion was wrong, and the
review of PR #456 showed why: the draft's per-cycle floor counted
**execution instances** of instructions, while the 256-word constraint is on
**stored program words** — two registers can preload the high and low pin
images, one `OUT` per SWCLK transition then suffices, and a loop stores its
body once however many cycles it runs. This revision replaces the draft's
arithmetic with a counted, assembler-measured implementation and reaches
the opposite verdict: **on DR 0017's frozen ISA the issue's agreed fallback
(line reset, switch, second line reset and idle clocks, then IDCODE + one DP
register read) fits the 256 × 16 program memory with room to spare —
192 of 256 stored words, turnaround cycles included.** What still does not
fit **the unrolled schedule measured here** is the issue's full goal
(a word of AP memory), which needs probe-driven write transactions; whether
a tighter, table-driven shape reaches it is unmeasured — see the boundary
section below.

**Second revision, same day, before merge.** The first revision of this
note assigned every SWCLK rising edge to startup, a request or response
bits, called the request/read parity odd, and ruled out the AP-memory read
on the unrolled arithmetic alone. The PR's re-review corrected all three,
with Arm's CMSIS-DAP as the observable reference: a one-clock turnaround
cycle is clocked after the request's park bit (before the ACK is sampled)
and another after the read parity (before the host re-drives SWDIO); the
parity is even, for the request header and the read data alike; and the
write-transaction boundary is a property of the unrolled schedule costed
here, not of the ISA. The corrected fallback count is **192 of 256 stored
words, 210 SWCLK rising edges** at this point — later revisions correct
the sample order and add the §B4.1.4 idle tail, and the figures in the
rest of this note are the fourth revision's **201 words, 218 rising
edges**.

**Third revision, same day, before merge.** The second revision's prose
said even parity, but the two request bytes it recorded as the evidence
(`0x91`, `0xB9`) encode the odd-parity bit — `0x91` decodes as a *write*
under either bit order — so the recorded trace contradicted the
protocol statement it was cited for. The counted program was never
committed and the tree that measured it no longer exists, so this
revision rebuilds the program from the section list below and re-measures
with the committed assembler and model: the same **192 words, no
warnings, 1145 core edges, 210 SWCLK rising edges**, and the request
bytes on the wire are `0xA5` and `0xBD` — even-parity DP reads, recorded
below with their field decode and bit order. The scripted target now
decodes the request frame and rejects a request whose parity bit is not
the even value, so the parity claim is checked by the measurement
instead of being stated over it. Byte values change no count: a request
is 8 driven bits whichever even-parity shape it carries.

**Fourth revision, same day, before merge.** The re-review of the third
revision caught two timing defects in the measured schedule, both now
corrected and re-measured. First, the sample loop raised SWCLK and only
then executed `IN` — but IHI 0031 §B4.3.1 permits the target to change or
release SWDIO on a rising edge, so a sample taken after the rise may
already be the *next* bit; Arm's CMSIS-DAP read primitive samples the pin
during the preceding SWCLK-low phase, and the loop body now does the same
(`IN` first, the rising `OUT` after — a reorder that changes no stored
word). Second, the schedule stopped SWCLK immediately after the final
turnaround; ADIv5 §§B4.1.1 and B4.1.4 require at least eight idle cycles
with SWDIO low before the host stops clocking (idle cycles are not
required between the first read and the next request), so a nine-word
idle loop now runs before the existing `HALT`. Re-measured against a
scripted target with exactly that aggressive-but-legal timing — SWDIO
launches on the rising edge that ends the turnaround and advances one bit
on every subsequent rise — the corrected schedule is **201 words, no
warnings, 1182 core edges, 218 SWCLK rising edges** (the IDCODE-only
schedule: **151 words, 172 rises**), both reads ACK OK with the expected
data and parity and the eight-edge idle tail present; the same target
run against the third revision's order mis-decodes the first read as ACK
`100` and data `0xA5D0023B` — every response bit read one rise late.

### The protocol choice was legal

The probe role passes DR 0017 section 6's exclusion check, the same check the
WS2812 and PS/2 choices took. It is not in rows 1–2 (UART, SPI controller,
I2C controller, USB, 10BASE-T); it is not named in `spec/isa-freeze.json`'s
`row13_excluded_protocols` (rows 1–2, DR 0015's tables and ineligible lists,
the protocols DRs 0012 and 0013 were designed around — none names SWD or
Serial Wire); and `git grep -i "swd\|serial wire" -- spec/` at this note's
parent finds the string only in DR 0018 line 283 (the SWD *target*, a
different role — the target samples a clock it does not generate, the probe
generates one) and in `spec/gap-to-submission.md` row 13's status prose. The
examination below, not the exclusion list, is what decides the probe's
fate.

### The protocol constants used, and their source quality

The arithmetic needs only the shape of one connection, not exact constants:

- a line reset of at least 50 SWCLK cycles with SWDIO high;
- a 16-bit JTAG-to-SWD switch sequence (0xE79E, LSB first);
- **after the switch, a second line reset followed by idle clocks with
  SWDIO low** — pyOCD's mode selection for the 0xE79E transition sends a
  second line reset and then idle cycles, and issue #452's curated
  requirements call for at least two idle clocks (source: pyOCD,
  `pyocd/probe/swj.py`, the SWJ sequence around `0ce0fbd`);
- one 8-bit request sampled by the target on SWCLK rising edges; **a
  one-clock turnaround cycle after the request's park bit — the probe
  releases SWDIO while SWCLK is low and clocks one further rising edge
  before the first ACK bit is sampled**; a 3-bit one-hot ACK and 32 data
  bits plus one even-parity bit driven by the target, each of them
  **sampled by the probe in the SWCLK-low phase *before* the next rising
  edge — IHI 0031 §B4.3.1 permits the target to change or release SWDIO
  on a rising edge, so the value seen after a rise may already be the
  next bit**; **a second one-clock turnaround after the read parity,
  before the probe re-enables its SWDIO driver**; and **after the last
  transfer, at least eight idle cycles with SWDIO low before the host
  stops SWCLK** (idle cycles are not required between a read and the next
  request) — ADIv5 §§B4.1.1 and B4.1.4. Arm's CMSIS-DAP clocks
  both turnaround slots (release before the response, re-drive after read
  parity), generates/checks even parity, and reads response bits during
  the preceding low phase; it is the observable reference
  for what a working probe does, in the same standing as pyOCD above.

Source: Arm Debug Interface v5 Architecture Specification (ARM IHI 0031,
section B4, "SWD"), with the connection-shape point above taken from pyOCD's
implementation because it is the observable reference for what a working
probe sends. **No copy of IHI 0031 was fetched into this repository for this
note**, so these figures carry DR 0015's "confirm" mark: a fetched copy must
be checked before any SWD firmware work resumes. The conclusion does not
hinge on them: a fetched copy moving any constant by a few cycles moves the
stored-word counts below by single words per cycle, against a margin of 55.

### The corrected cost model: stored words, not execution cycles

DR 0001's constraint is program memory: **256 stored 16-bit words**.
Execution time is a separate axis this record does not budget — SWD is not
free-running, and this repository records no upper bound on the probe's
clock period ("confirm": a fetched copy of IHI 0031 settles what, if
anything, target-side idle limits exist). The first draft counted
per-execution instruction instances against the 256-word budget; that is
the defect the review caught. Stored words are what follow:

- **Two preloaded images make one `OUT` per transition.** The high and low
  `UIO_OUT` images (e.g. `0x0C` = SWCLK high + SWDIO high, `0x08` = SWCLK
  low + SWDIO high) live in two registers; every SWCLK transition is then a
  single `OUT UIO_OUT, Rn` — one stored word per transition, two per cycle
  if unrolled. The draft's "two words per transition, four per cycle"
  assumed the image register must be reloaded before every `OUT`; it need
  not be.
- **A loop stores its body once.** The line reset is `LDI R2, 50` plus a
  4-word body (`OUT` high, `OUT` low, `SUB`, `BNZ`): **5 stored words for
  any reset length**. The draft's "a loop amortises only its exit test …
  always more than straight-line's four" divided per-execution body
  instances by cycles; the stored cost is the body, once.
- **Fixed bit patterns transmit at 4 words per bit.** For a known pattern
  (the switch sequence, a request byte), each bit is: `LDI` low image
  (SWCLK low, SWDIO = bit); `OUT`; `LDI` high image (SWCLK high, SWDIO =
  bit); `OUT`. SWDIO then changes only while SWCLK is low and is stable at
  every rising edge. (A 3-word-per-bit shape exists — change SWDIO with the
  same `OUT` that raises SWCLK — but it gives the target no hold margin at
  the rising edge, so the count uses the safe shape.)
- **Target-driven bits sample through one shared body.** ACK and data are
  read through an 8-word loop body — `IN` (sample while SWCLK is low);
  `AND` with the dio mask; `OUT UO_OUT` (report the masked sample byte);
  `OUT` high — the rise the target may advance SWDIO on, per §B4.3.1,
  which is why the `IN` precedes it; `OUT` low; `LDI 1`; `SUB`; `BNZ` —
  stored once for however many samples the transaction needs. A read
  transaction's 36 samples (3 ACK + 32 data + 1 parity), each taken in
  the low phase before the rise that may change the bit, cost 9 stored
  words including the counter load, and the second transaction re-uses
  the shape with its own copy (9 words).
- **Four registers suffice, and result bytes need not live in registers.**
  R0/R1 hold the two images, and R0's `0x08` doubles as the SWDIO mask for
  the `AND`; R2 counts; R3 is the sample/decrement scratch. The draft's
  full-word-accumulator objection ("the IDCODE is 32 bits against four
  8-bit registers …") assumed the four result bytes must all sit in
  registers at once. They need not: DR 0012 gives firmware read/write
  access to program memory (`PM_ADDR`, `PM_DATA_HI`/`PM_DATA_LO`, its
  "Program-memory timing" section), so bytes can be parked in unused words
  and reported byte-at-a-time — and the counted implementation below
  sidesteps accumulation entirely by reporting each masked dio sample as it
  is taken. (Scratch check on the committed model, only `R0` live: store
  `0x1234` and `0x5678` at words 254 and 255, read them back on `UO_OUT`
  as `12 34 56 78`.)
- The DR 0012 variants and DR 0015 primitives change none of this: toggling
  a pin through `UIO_DIR`/`UIO_OD` costs one `WCTL` per transition, the
  same stored word as an `OUT`; P2's `LINE_PUT`/`LINE_OUT` still encode
  NRZI/stuffing bits SWD does not use; P3 (Manchester) was never built —
  its control indices do not exist in DR 0012's register map or
  `firmware/tools/asm.py`.

### The counted implementation: the fallback measured at 201 stored words

The issue's agreed fallback — line reset, switch, second line reset and idle
clocks, then IDCODE + one DP register read — was written as a program and
measured. The shapes above compose into these stored-word sections, counted
by the committed assembler (`firmware/tools/asm.py`):

| Phase | Stored words |
|---|---|
| Setup (two images, `UIO_DIR` push-pull, SWDIO high before the first edge, decrement constant) | 5 |
| Line reset loop — ≥ 50 cycles, SWDIO high (counter + 4-word body, any length) | 5 |
| JTAG-to-SWD switch, 16 bits at 4 words/bit | 64 |
| Second line reset (dio-high fall, counter, decrement-constant reload, own 4-word body) | 7 |
| Idle clocks ×2, SWDIO low | 10 |
| Request 1 (IDCODE read), 8 bits at 4 words/bit | 32 |
| Turnaround 1 — park-bit fall, release SWDIO, one clocked turnaround cycle, SWCLK left low for sampling | 5 |
| Sample loop 1 — counter + 8-word body for 36 low-phase samples (ACK 3, data 32, parity 1; `IN` before the rising `OUT`) | 9 |
| Turnaround after read parity + re-drive SWDIO (`OUT` rise, `OUT` fall, `LDI`, `WCTL UIO_DIR`) | 4 |
| Request 2 (DP read), 8 bits | 32 |
| Turnaround 2 (same clocked shape as turnaround 1) | 5 |
| Sample loop 2 (36 low-phase samples, own copy) | 9 |
| Final turnaround + SWDIO re-drive (`OUT` rise, `OUT` fall, `LDI`, `WCTL UIO_DIR`) | 4 |
| Trailing idle ×8, SWDIO low before SWCLK stops — idle image pair, SWDIO-low fall, counter, decrement constant, own 4-word body (§§B4.1.1, B4.1.4) | 9 |
| `HALT` | 1 |
| **Total — startup + both reads** | **201** |

Startup (91 words) plus the first transaction only (the minimum the
fallback names) is **137 stored words** at the end of the first sample
loop; the final turnaround and re-drive (4), the trailing idle tail (9)
and `HALT` (1) bring the IDCODE-only schedule to **151 words and 172
SWCLK rising edges**. The second read, its turnaround and the shared
handback and tail add 50 more. **201 of 256: the fallback fits with 55
words (21%) spare.**

Measured, not just added up. Assembling the program with the committed
assembler gives exactly 201 words and no warnings. Running that image on
the committed ISA model (`verification/reference_models/isa.py`) against a
scripted SWD target with §B4.3.1 timing and full line-ownership rules —
it takes SWDIO on the rising edge that ends the turnaround cycle,
**launches the first ACK bit on that rise and advances SWDIO by one bit
on every subsequent rise**, releases the line on the rise after the read
parity, decodes the request frames, rejects a wrong-parity request, and
counts the trailing idle edges:

- the program runs to `HALT` (1182 core edges; 218 SWCLK rising edges =
  118 startup + 2 × (8 request + 1 turnaround + 36 sample-loop rises +
  1 turnaround) + **8 trailing idle rises**, the count the re-review
  derived for the corrected schedule); the target counts exactly eight
  trailing rises with SWDIO low at each, the §B4.1.4 tail;
- the SWDIO value at every rising edge matches the scripted patterns: the
  switch reads `0111100111100111` (0xE79E, LSB first), and both request
  bytes come back bit-exact: `0xA5` then `0xBD`, both **LSB first** (bit 0
  of the byte on the first wire edge). Decoded against the request frame
  defined above — `[start, APnDP, RnW, A2, A3, parity, stop, park]` —
  both are DP reads (APnDP 0, RnW 1) with **even** parity over the four
  header bits: `0xA5` is start 1, APnDP 0, RnW 1, A[2:3] 00 (the
  IDCODE/ABORT bank — the read of IDCODE this probe performs), one
  header one → parity bit 1, stop 0, park 1; `0xBD` is the same shape at
  A[2:3] 11 (the RDBUFF bank), three header ones → parity bit 1. The
  scripted target decodes the frame and rejects a request whose parity
  bit is not the even value, so the measurement checks the parity rather
  than assuming it. The second revision recorded `0x91`/`0xB9` here —
  both carry the odd-parity bit, the contradiction the third revision
  exists to fix. Which DP register a real probe reads second is exactly
  the kind of IHI 0031 constant this note marks "confirm". The first
  revision called this parity odd, which would accept the opposite
  parity bit; CMSIS-DAP's request-parity generation and read-parity
  check are even, and the wire bits here follow them;
- the bytes the probe reports on `UO_OUT` match the target's answers: ACK
  `001` — the first sample taken in the SWCLK-low phase *before* the rise
  that advances the target (§B4.3.1; CMSIS-DAP's read primitive does the
  same) — then IDCODE `0x4BA00477` LSB first with even parity
  (13 ones → parity bit 1), then the same for a second 32-bit DP value
  (`0x12345678`, also parity bit 1) — one masked dio byte per sample,
  in transaction order. The sample order is load-bearing, and the
  measurement shows it: the same target run against the third revision's
  order (raise SWCLK, *then* `IN`) mis-decodes the first read as ACK
  `100` and data `0xA5D0023B` — every response bit read one rise late —
  while the corrected order reads both transactions clean.

The program text is ~200 commented source lines composed of the shapes
above and **is not committed with this note** — the figures and wire
constants in this section are the record of the measurement and its only
artifact. Every figure in the table is re-derivable from the section
list, and the measurement is the committed assembler plus the committed
model — no bench, no RTL, no new tool. The third and fourth revisions'
numbers come from rebuilds of the program from this list (the images
earlier revisions measured were equally uncommitted and no longer
exist); the rebuilds agree on every count they share — the fourth
revision's reorder and idle tail change no figure before the final
handback, where the tail adds its 9 words and 8 rises.

### What does not fit the measured schedule: probe-driven write transactions

The issue's full goal is one word of AP memory. That needs at least two
probe-driven write transactions (SELECT, then TAR) before the read. On the
unrolled schedule costed above, a write transaction's data phase drives 33
bits (32 + parity) at 4 words/bit = 132 stored words, ≈ 180 all-in per
transaction with its request, turnarounds and ACK loop (derived from the
section table, not separately assembler-measured). Two of those do not fit
alongside the 91-word startup; arbitrary (computed) data would cost more
still.

**That is a result for the unrolled schedule, not a bound on the ISA.**
The review of this PR measured a table-driven alternative for the same data
phase with the committed assembler and ISA model: a 15-word driver
(including setup and `HALT`) looping over 33 stored low-clock pin images —
48 words total including the table — raising the clock for each image and
reproducing all 33 bits of `0x13579BDF` and their even parity. Stored pin
images are data, not code, so the per-bit cost is ~1 stored word plus the
shared loop, not 4. The full AP sequence (two write transactions plus the
read, with turnarounds and ACK handling) has been measured under neither
shape, so this note claims only: **on the unrolled 4-words-per-bit
schedule, IDCODE + one DP register read fits and a memory-word read does
not; whether a table-driven probe fits the memory-word read is an open
measurement, recorded here as the issue's next step.** This is the
conclusion shape the issue itself anticipated when it set the fallback.

### What this note does and does not claim

- It corrects the first draft's verdict on the **probe role**: the agreed
  fallback fits, with margin. Issue #452 therefore **stays open** — the
  probe is buildable on the frozen ISA, and the firmware, bench, reference
  model and evidence records are the issue's own next step. This PR creates
  none of them.
- A real probe would check the ACK (`BZ`/`BNZ` on the sampled `001`) before
  clocking data. The counted shape reports ACK instead of branching on it;
  an ACK check is a protocol handshake, the legitimate branch case DR
  0003's assembler lint already names, and the 55-word margin absorbs its
  words.
- The **SWD target** (issue #235's candidate, `gap-to-submission.md` row 13)
  has a different cost shape — it samples SWCLK with `IN` and drives SWDIO
  in response, so it pays one output word per driven bit — and this note's
  arithmetic says nothing about it. It remains a candidate.
- It is a feasibility record, in the sense of DR 0011: it writes down one
  cost accounting and what it excludes, and reaches no verdict about SWD on
  any other ISA. If DR 0017's freeze is ever amended (section 4), this
  accounting must be re-run before firmware work is planned against it — a
  wider program memory, an edge-generating primitive or a second output
  port each changes it.
- The ADIv5 constants stay "confirm" (no copy of IHI 0031 was fetched).
  They move the stored-word counts by single words per cycle (reset length,
  idle clocks), not by tens — the margin absorbs them.
- It makes no row met and does not touch the PS/2 or WS2812 evidence.
- **Same-flaw watch, out of scope here:** DR 0011's USB feasibility uses
  per-bit unrolled straight-line accounting ("per-bit copies, unrolled,
  because the loop test is pure overhead") — the same stored-vs-executed
  distinction this revision corrects. Re-running that record is a separate
  piece of work; it is flagged here, not silently left standing.

### Consequences

- Issue #452 stays open: the first draft's close-as-not-planned rationale is
  withdrawn by this revision, and PR #456 drops the closing keyword. The
  probe's firmware, bench, reference model, pin-role table entry and
  evidence records are the issue's own work, to be picked up from the
  counted implementation above.
- DR 0010's pin table is unchanged by this note: `uio[2]`/`uio[3]` keep
  their existing SPI / I2C / PS/2 roles, and no `swd` phase is added until
  firmware exists to hold to it. The counted implementation's would-be plan
  (SWCLK = `uio[2]`, SWDIO = `uio[3]`, push-pull while driving, SWDIO
  released for turnaround and target-driven phases) stays inside this
  analysis.
- Row 13's stretch column keeps its remaining candidate (the SWD target),
  still subject to its own examination.

## Dated note 2026-11-23 (issue #500): the table-driven probe measured — the memory-word read fits

This note closes the measurement the 2026-11-19 note left open ("whether a
table-driven probe fits the memory-word read is an open measurement"). It
changes no decision above and relaxes nothing in the ratified spec: it
records one assembled image, measured with the committed assembler, and
the bench that exercises it. DR 0017's freeze is untouched (no RTL, ISA
or assembler byte changed; `scripts/check_isa_freeze.py` passes).

### The image and its section counts

`firmware/asm/swd_probe.asm` now holds the complete probe: line reset, the
0xE79E switch, a second line reset, two idle clocks, then five transactions
— DP IDCODE read (0xA5), DP SELECT write (0xB1, 0x00000000), AP TAR write
(0x8B, 0x20000004), the posted AP DRW read (0x9F) and the DP RDBUFF read
(0xBD) — and eight trailing idle clocks. **245 stored words of 256; 11
spare.** Every stored instruction and table entry is counted once:

| Section | Stored words |
|---|---|
| setup, first line reset (50 clocks) | 10 |
| switch loop (`PM_ADDR` setup, 16-bit table pass, 8-word loop) | 11 |
| second line reset, two idle clocks | 17 |
| transaction engine: start word, the one transmit loop (8), the word after the request, turnaround, ACK slot, response loop (8), return turnaround and re-drive, the word after the response | 44 |
| WAIT / FAULT path (`ackerr`) | 13 |
| trailing idle (8 clocks) and `HALT` | 10 |
| **code** | **105** |
| table: 16 switch bits | 16 |
| table: 5 start words + 40 request bits + 5 words after the request + 5 words after the response | 55 |
| table: 2 x 33 write-data bits + 2 words after the write data | 68 |
| table: end word | 1 |
| **table** | **140** |

(The code rows add to 105 — 10 + 11 + 17 + 44 + 13 + 10 — and, with the
140 table words, to the 245 that `python3 firmware/tools/asm.py
firmware/asm/swd_probe.asm` reports.) The shape is the one the 2026-11-19 note measured for a single
data phase: each probe-driven bit is one stored `LDI` word the program never
executes, read through DR 0012's `PM_ADDR` / `PM_DATA_HI` / `PM_DATA_LO`, and
one 8-word loop sends the request bits and the write-data bits of every
transaction. A start word, a word after the request and a word after the
response (all table data) make the sequence, kind and length of each
transaction data too, so one copy of the engine serves reads and writes
alike. That is why the five transactions fit where the unrolled schedule
(≈180 words per write) could not.

### What the bench shows (RTL)

`verification/test_firmware_swd.py`, against `verification/reference_models/
swd.py` extended with a DP and one MEM-AP (`MemAp`): the probe connects,
reads the IDCODE, writes SELECT and TAR (each 33 data bits, checked from the
pads), issues the posted DRW read — whose data is the read buffer's previous
value 0xA5A5C3C3, deliberately different from the word — and fetches the
addressed word 0xCAFEF00D through RDBUFF; the golden run ends with eight
low-data idle clocks and zero contention. Mutants (a flipped SELECT or TAR
write parity bit, a broken ACK-to-write-data handoff, and the earlier
connection / turnaround / request-parity / trailing-idle set) each fail for
their own reason; each of the five transactions answered WAIT or FAULT ends
the run with no data phase, changes no model state for a rejected write, and
never returns the word. The record is under `verification/records/
firmware-swd/`; the superseded 227-word records stay in place.

### What is assumed, not established

- **ADIv5 constants stay "confirm"**, as above: no copy of IHI 0031 is in
  the repository. The register addresses (DPIDR A=0x0, SELECT A=0x8, RDBUFF
  A=0xC, MEM-AP TAR 0x04, DRW 0x0C), SELECT and TAR having no reset value, and
  the posted DRW read are written into the model from the ADIv5 description;
  a fetched copy must be checked against them before the model certifies
  anything about silicon.
- **The MEM-AP's word-access starting state** is a model assumption: CSW is
  not written by the probe, and the model starts with CSW.Size = 0b010 and
  CSW.AddrInc = 0b00. A real part's CSW reset is implementation-defined.
- SELECT is written 0x00000000 (APSEL 0, bank 0), so its payload is the
  all-zero word; TAR is word aligned. Auto-increment bursts, multi-drop and
  retry stay out of scope.
- Cycle figures name target-spec row 4's unconfirmed 50 MHz clock; the claim
  is the cycle count. No gate-level run is claimed, and the two-flow rule
  stands: nothing here is a synthesis or timing number.
