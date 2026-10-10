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
