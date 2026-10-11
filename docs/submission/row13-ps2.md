# Row 13, stretch column: a PS/2 device on two open-drain lines

Status: **written 2026-10-11** for issue #134 (deliverable D6) from issue #235.
It describes evidence that is in the repository. It does not mark target-spec
row 13 met: the row is Proposed and outside DR 0004's register. Its primary
column is [`row13-ws2812.md`](row13-ws2812.md).

## What the stretch column asks

Row 13's stretch column wants a protocol "in a **role or pin direction** the
core protocols never use", which exercises DR 0012's runtime pin direction. The
core protocols are all controllers that own their clock on push-pull lines. WS2812
is output-only push-pull, so it says nothing about this column.

## Why PS/2, and how the order was kept honest

DR 0018's dated note of 2026-10-11 chose the **device side of PS/2** in a commit
whose parent contains the freeze (DR 0017's merge, `1696045b`), before any PS/2
file existed. It checked the choice against DR 0017's exclusion list and a
`git grep`. Three things make PS/2 new in this design:

1. **It generates a clock on an open-drain line that the other side may hold
   low.** The host inhibits by holding CLK low for 100 µs or more. The device
   must notice, abandon the frame, release DATA, and send the same frame again
   after CLK has been high for 50 µs.
2. **It turns a data line around mid-transaction.** In a host-to-device frame
   the host drives DATA for eight bits, parity and stop; the device then pulls
   DATA low as the ACK in the high phase of the 11th clock, and lets go.
3. **It reads a line the other side drives, on a clock the device itself
   generates.** One program does both phase relationships (the host reads on the
   falling edge, the device on the rising edge).

The freeze held: `scripts/check_isa_freeze.py` reports the same eleven pinned
files and the same two amendments as before this work, and no RTL, assembler or
ISA-model byte changed.

## What was built

| Item | Where |
|---|---|
| Program | [`firmware/asm/ps2_device.asm`](../../firmware/asm/ps2_device.asm) (213 words) |
| Independent model | [`verification/reference_models/ps2.py`](../../verification/reference_models/ps2.py): a host-side bus monitor written from Chapweske's description of the interface. It imports nothing from the design, the firmware or the assembler, and it also grades the bench's own host driver |
| Bench | [`verification/test_firmware_ps2.py`](../../verification/test_firmware_ps2.py) |
| Pad model | [`verification/uio_pads.py`](../../verification/uio_pads.py): pull-ups on both lines, the other six `uio` pins tied low; the bench requires no contention and the design only ever driving CLK and DATA low |
| Pin roles | `ps2` phase in [DR 0010](../../spec/decision-records/0010-protocol-pin-roles.md): CLK `uio[2]`, DATA `uio[3]`, the standard I2C Pmod row with its pull-ups |
| RTL evidence | [`firmware-ps2` 20261011-104232-d81097f](../../verification/records/firmware-ps2/records/20261011-104232-d81097f.md) |
| Gate-level evidence | [`firmware-ps2-gate-level` 20261011-120015-e5a0bae](../../verification/records/firmware-ps2-gate-level/records/20261011-120015-e5a0bae.md) (LibreLane netlist, zero-delay) |

## What was measured

Every figure is read off the pads by the model, in core cycles × 20 ns (row 4's
unconfirmed 50 MHz target).

| Quantity | Measured | Limit (Chapweske) |
|---|---|---|
| CLK low, device generated | 40.12 to 40.14 µs | 30 to 50 µs |
| CLK high | 40.70 to 41.66 µs | 30 to 50 µs |
| Data change before the falling edge | 20.34 µs | 5 to 25 µs |
| Data change after a rising edge | at least 20.36 µs | at least 5 µs |
| ACK before the 11th falling edge | 20.34 µs | 5 to 25 µs |
| CLK high before the device starts a frame | at least 80.2 µs | at least 50 µs |

The scenarios: the BAT code at power-up; eight host bytes ACKed and echoed; bad
parity and a 0 stop bit answered 0xFE; inhibits after clock 1, 4 and 10
(abandon, release, wait, resend) and after clock 11 (no repeat); a bus held
inhibited from reset; a request to send before the BAT code is out; a host that
abandons its own transfer. Eight mutant programs and a log-path control are
rejected for their own reasons: no inhibit check, a hold-off of 18 polls, no
ACK, data too late, data too early, even parity, push-pull pads (contention),
and an unchecked host parity (caught by the byte comparison).

## What the frozen ISA made easy and hard

- **Easy:** exact timing. Every phase is an assemble-time wait, so CLK low
  measured 40.12 to 40.14 µs across all runs, and the small spread in CLK high
  is the dispatch code, not data. DR 0012's `UIO_OD` made the open-drain lines
  one instruction. `PM_ADDR` is a free one-byte store, and it held the pending
  byte and the received parity bit.
- **Hard:** four registers and no call or return, so there is one shared pulse
  routine reached by jump, and its direction is a flag bit in the pin image.
  `SHF` writes only the carry, so each shift loop and each isolated bit needs
  an `OR Rx, Rx` to set `Z` (this cost a debugging run: the first version
  hung in its first wait). There is no add-with-carry, so a bit is isolated by
  shifting it to bit 7 and back. The assembler's lint calls the program's
  ten branches on pin data data-dependent; each is a handshake or an inhibit
  check.

## What is not claimed

- Row 13 is **Proposed and unmet**; a PS/2 device is not a ratified result.
- The source is a secondary description of a de facto interface. The author says
  he did not have IBM's manual.
- The keyboard and mouse command sets are not implemented, only the byte layer
  (echo, and 0xFE on an error). The device holds one pending byte, not 16. A host
  that never releases DATA after the ACK is not modelled.
- The pad model has zero delay and ideal pull-ups. There is no SDF run, no
  pull-up rise time and no board.
- The stretch column's other candidate that samples a clock someone else
  drives (SWD target) is not built.
