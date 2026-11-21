# Protocol catalog — what this chip could speak as firmware

The **breadth** half of the competition's multi-protocol extra credit
(submissions due 2027-01-18): every serial protocol this chip could
plausibly run as firmware, ranked so the next ones to build are chosen on
evidence rather than enthusiasm. One chip, one firmware image at a time;
each image assigns its own pin roles (DR
[`0010`](../spec/decision-records/0010-protocol-pin-roles.md), DR
[`0012`](../spec/decision-records/0012-control-space-and-runtime-pin-direction.md)),
so adding a protocol costs program memory and verification effort, not pins.

This file assesses; it builds nothing. The nine protocols chosen for build
issues are linked from the [ranked shortlist](#ranked-shortlist-build-order).
The frozen ISA (DR
[`0017`](../spec/decision-records/0017-submission-isa-freeze.md)) and the
admitted protocol-neutral primitives (DR
[`0015`](../spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md):
P1 CRC/LFSR step and P2 NRZI + bit stuffing, at control indices `0x10`–`0x19`)
are fixed; everything in this catalog is firmware on that ISA, per the
deadline-discipline rule. Protocols that would need new RTL are **deferred**,
never "helped along" with hardware.

## How to read the numbers

**Sourcing convention.** Every numeric demand figure in this file names its
source and retrieval date; anything that could not be verified when this was
written is marked *unsourced, not used for ranking*. Demand proxies were
measured on 2026-11-19 by three reproducible, keyless queries
([method](#sources-and-method)): the size of the Arduino Library Manager
ecosystem (`[A n]`), public GitHub repository counts (`[G n]`), and
electronics.StackExchange tag sizes (`[SE n]`). Transceiver or
optocoupler part counts at distributors were **not** used: the distributor
catalog APIs need keys this work does not have. Spec-side timing figures cite
the standard or a public summary fetched the same day; years and bit rates in
a row carry that row's citations.

**Cycles, not bauds.** Every timing figure is in core cycles at the target
clock: 50 cycles per microsecond at 50 MHz. The 50 MHz clock is
target-spec row 4's **unconfirmed target** (the klt-flow STA leg has hold
violations; see the target-spec table), so no wall-clock rate is claimed here
— the same convention [`docs/info.md`](info.md) applies to the built
protocols. Bit time = 50,000,000 / bit rate. A protocol whose timing needs
better than about ±2 % of a bit period (the cumulative drift budget
target-spec row 10 derives for UART-class links) or whose bit loop is shorter
than the demonstrated loop rate is flagged **tight** in its row.

**Program memory.** The budget is 256 × 16-bit words (target-spec row 6).
Every estimate below is *an estimate, not assembled* — no program in this
file has been written or run. Anchors from the committed, measured images in
[`docs/info.md`](info.md#protocols-as-firmware): `uart_tx` 34 words,
`ws2812` 60, `ps2_device` 213, `swd_probe` 227, `i2c_fast` 245; DR
[`0011`](../spec/decision-records/0011-stretch-protocols-feasibility.md)'s
hand-counted low-speed USB TX schedule is 168 words for eight bit-copies.
For protocols needing data buffering: the ISA has four registers and
addressable program memory (DR 0012), so a buffer costs words.

## Shared constraints

- **Pins are shared across protocols; one image at a time.** The silicon does
  not decide what a pin means — the loaded firmware does (DR 0001, DR 0010).
  The roles named in the table are the *exemplar* assignments of DR 0010
  (`uart`, `spi`, `i2c`, `ps2` phases); a new protocol image assigns its own
  roles to the same `ui` / `uo` / `uio` pins through DR 0012's runtime pin
  mode, and only one image runs at a time. Only one device sits on the
  `uio` header per image (decided in #196, recorded in
  [`docs/info.md`](info.md#one-device-on-the-uio-header-at-a-time-decided-in-196-2026-10-09)).
- **Program memory and verification are the binding limits.** 256 words caps
  every row's "Words" column, and the evidence bar — a bench plus an
  independent reference model with timing checked
  ([`CLAUDE.md`](../CLAUDE.md) § "Firmware is evidence") — caps how fast a
  protocol can be claimed. A protocol is not "supported" until its program,
  model and record exist.
- **The RTL is frozen.** DR 0017 pins the eleven ISA files by sha256. Anything
  here that the frozen ISA cannot do is *deferred* (DR 0015's verdict table is
  the precedent), never an RTL change.

## Already built — reference, not re-assessed

| Protocol | Where the evidence is |
|---|---|
| UART (8N1, TX and RX at 50 / 434 / 5,208 cycles/bit) | target-spec rows 1 and 10; the firmware-images table in [`docs/info.md`](info.md#protocols-as-firmware) |
| SPI controller (modes 0–3, bursts) | target-spec row 11; [`docs/info.md`](info.md#protocols-as-firmware) |
| I2C controller (Standard and Fast mode, read, repeated START, clock stretching) | target-spec row 12; [`docs/info.md`](info.md#protocols-as-firmware) |
| WS2812 (row 13 primary column) | [`docs/submission/row13-ws2812.md`](submission/row13-ws2812.md) |
| PS/2 device (row 13 stretch column) | [`docs/submission/row13-ps2.md`](submission/row13-ps2.md) |
| SWD probe (multi-protocol extra credit, issue #452) | [`docs/submission/row13-swd.md`](submission/row13-swd.md) |

Low-speed USB is not re-assessed here either: DR
[`0015`](../spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md)
holds the verdict (TX-only admitted with P1/P2; RX deferred).

## Catalog

Rows are grouped by verdict: the nine **build** protocols (issues filed),
then **candidate** (worth an issue after the nine land), **deferred**
(technically interesting, blocked on something recorded), and **not a fit**
(one-line reason). Pins column abbreviations: `uo` = `uo_out`, `ui` = `ui_in`,
`uio` = `uio`; open-drain (OD) means the image needs DR 0008/0012's
open-drain path on that pin.

### Build (issue filed — ranked shortlist order)

| Protocol (year, domain) | Primitive class | Pins and roles | External parts | Timing vs 50 MHz | Program memory (est.) | Demand | Verdict |
|---|---|---|---|---|---|---|---|
| **MIDI** (1983, music) ([wiki MIDI](https://en.wikipedia.org/wiki/MIDI), 2026-11-19) | UART-framed, 31,250 baud (same source) | TX `uo[0]`, RX `ui[1]` — the `uart` roles of DR 0010 | 5-pin DIN + optocoupler on IN (opto-isolated current loop; [wiki MIDI](https://en.wikipedia.org/wiki/MIDI), 2026-11-19) | 1,600 cycles/bit — inside the proven UART range (50–5,208); ±2 % budget trivially met by the exact-cycle TX | est. 100–200 (TX + note decode RX) | [A 293](https://downloads.arduino.cc/libraries/library_index.json) · [G 61,899](https://github.com/search?q=midi+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 135](https://electronics.stackexchange.com/questions/tagged/midi), 2026-11-19 | **Build — #444.** Largest ecosystem of any row; pure UART-framing; cheapest verification of the nine |
| **1-Wire** (Dallas Semiconductor, 1990s, sensors) ([wiki 1-Wire](https://en.wikipedia.org/wiki/1-Wire), 2026-11-19) | Pulse-width / single-wire | one `uio[n]`, **open-drain** with pull-up — the `ps2` roles prove the mechanism (DR 0008/0012) | pull-up resistor only | reset ≥ 480 µs (24,000 cycles), write-1 pulse ≤ 15 µs (750), slots 60–120 µs (3,000–6,000) — all easy ([wiki 1-Wire](https://en.wikipedia.org/wiki/1-Wire), 2026-11-19) | est. 80–150 (pulse-chain structure like `ws2812`'s 60 words) | [A 151](https://downloads.arduino.cc/libraries/library_index.json) · [G 1,823](https://github.com/search?q=%221-wire%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 90](https://electronics.stackexchange.com/questions/tagged/1-wire), 2026-11-19 | **Build — #447.** Strong sensor demand; single OD line is a direction the core protocols never use, extending the row-13 stretch claim |
| **RS-485 Modbus RTU** (Modbus 1979 / RTU framing, industrial) ([Modbus over Serial Line V1.02](https://web.archive.org/web/2024/https://www.modbus.org/docs/Modbus_over_serial_line_V1_02.pdf), retrieved 2026-11-19) | UART-framed, silent-interval delimiting | TX `uo[0]`, RX `ui[1]`; transceiver direction pin on a `uo` bit | RS-485 transceiver on a Pmod | 9,600 baud default (same spec): 5,208 cycles/bit; 3.5-char inter-frame gap ≈ 4.0 ms ≈ 200,000 cycles — long `WAIT` runs, trivial in cycles | est. 150–256 (CRC-16 fits P1; a register map costs ~a word per constant — DR 0011's 72-octet table anchor) | [A 276](https://downloads.arduino.cc/libraries/library_index.json) · [G 21,295](https://github.com/search?q=modbus+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 155](https://electronics.stackexchange.com/questions/tagged/modbus), 2026-11-19 | **Build — #446.** Highest industrial demand; UART-framed; CRC engine already admitted |
| **DMX512** (1986, stage lighting) ([wiki DMX512](https://en.wikipedia.org/wiki/DMX512), 2026-11-19) | UART-framed (EIA-485), break/MAB framing | TX `uo[0]`; transceiver direction on a `uo` bit | RS-485 transceiver on a Pmod (E1.11 is EIA-485; same source) | 250 kbaud (same source): 200 cycles/bit, slot = 11 bits = 2,200; break ≥ 88 µs (4,400 cycles) and MAB ≥ 8 µs (400) are long `WAIT`s; ≤ 513 slots ≈ 22.6 ms per universe | est. 100–180 (unrolled slot loop) | [A 90](https://downloads.arduino.cc/libraries/library_index.json) · [G 676](https://github.com/search?q=dmx512+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 67](https://electronics.stackexchange.com/questions/tagged/dmx), 2026-11-19 | **Build — #445.** Controller (transmit-only) role only — no receive state machine; shares the RS-485 Pmod with Modbus |
| **NEC infrared** (NEC, 1980s, remote control) ([sbprojects NEC](https://sbprojects.net/knowledge/ir/nec.php), 2026-11-19) | Pulse-width / single-wire over a 38 kHz carrier | one `uo[n]` push-pull to the LED (TX); one `ui[n]` from the receiver (RX) | IR LED + driver (TX); demodulating receiver module (RX) | 38 kHz carrier ≈ 1,316 cycles/period; AGC burst 9 ms, bits 560 µs burst + 560/1,680 µs space (same source) — pulse chains well inside the proven `ws2812` edge precision | est. 80–160 TX; 120–200 RX | [A 14](https://downloads.arduino.cc/libraries/library_index.json) (`NEC` token) · [G 88](https://github.com/search?q=nec+infrared+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE infrared 787](https://electronics.stackexchange.com/questions/tagged/infrared), 2026-11-19 | **Built (TX) — #448.** The transmitter landed: `firmware/asm/nec_ir.asm` (164 words), [`test_firmware_nec_ir.py`](../verification/test_firmware_nec_ir.py) + [`nec_ir.py`](../verification/reference_models/nec_ir.py), DR 0010 `nec_ir_tx`/`nec_ir_rx` roles (`firmware/README.md` § `nec_ir.asm`); the RX decode from the `ui_in[4]` receiver-module pin is the recorded follow-up — the same row's wiring, no new pin |
| **I2S** (Philips, 1986, digital audio) ([wiki I2S](https://en.wikipedia.org/wiki/I2S), 2026-11-19) | Clocked serial (3-wire, controller owns both clocks) | SCK/WS/SD on three `uio` pins — per-image assignment à la DR 0010's `spi` roles | I2S DAC on a Pmod | BCLK = 64 × fs (same source): 48 kHz → 3.072 MHz → 16.3 cycles per BCLK — **tight flag**: inside the 10-cycles/bit proven SPI path but only just; no rate-accuracy issue (the chip generates the clock) | est. 80–140 + one word per stored sample | [A 82](https://downloads.arduino.cc/libraries/library_index.json) · [G 2,675](https://github.com/search?q=i2s+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 161](https://electronics.stackexchange.com/questions/tagged/i2s), 2026-11-19 | **Build — #451.** Solid audio demand; streaming TX only for the first issue; flagged tight |
| **CAN 2.0A** (Bosch, 1991, vehicles/industrial) ([wiki CAN](https://en.wikipedia.org/wiki/CAN_bus), 2026-11-19) | Bit-stuffing + CRC (and bitwise arbitration) | TX/RX through the transceiver on two `uio` pins; sample point via `IN` | CAN transceiver on a Pmod (dominant/recessive is the transceiver's job) | 250 kbit/s → 200 cycles/bit with a mid-bit arbitration sample; 500 kbit/s → 100, 1 Mbit/s (classic max; same source) → 50 — **tight flag** above ~250 kbit/s; CRC-15 fits P1 | est. 200–256 — tightest of the nine; arbitration + ACK + error states may overflow the budget | [A 257](https://downloads.arduino.cc/libraries/library_index.json) (`canbus`-class patterns) · [G 7,747](https://github.com/search?q=canbus+OR+%22can+bus%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 899](https://electronics.stackexchange.com/questions/tagged/can), 2026-11-19 | **Build — #450.** Highest Q&A volume of the nine (SE 899), hardest firmware; scope limited to 125–250 kbit/s class frames |
| **DALI** (IEC 62386, 2001, lighting control) ([wiki DALI](https://en.wikipedia.org/wiki/Digital_Addressable_Lighting_Interface), 2026-11-19) | Manchester/biphase | TX/RX through the line interface on two `uio` pins | DALI line interface (16–22.5 V bus) on a Pmod | 1,200 bit/s Manchester (same source): half-bit 416.7 µs = 20,833 cycles — slow, exact `OUT`+`WAIT` pairs | 210 assembled (forward + backward frames) | [A 4](https://downloads.arduino.cc/libraries/library_index.json) · [G 12,054](https://github.com/search?q=dali+in%3Aname%2Cdescription%2Ctopics&type=repositories) (count includes the painter-Dalí name noise) · [SE 105](https://electronics.stackexchange.com/questions/tagged/dali), 2026-11-19 | **Built in RTL — #449.** The [control-device image](../firmware/asm/dali_master.asm) sends direct arc power and queries the actual level of short address zero. The [RTL record](../verification/records/firmware-dali/records/20261119-151157-bd0e3dc.md) covers valid replies, rejection and recovery. |
| **SWD** (Arm ADIv5, ~2005, debug) ([JTAG/SWD description](https://en.wikipedia.org/wiki/Joint_Test_Action_Group), 2026-11-19; spec: Arm IHI 0031, [developer.arm.com](https://developer.arm.com/documentation/ihi0031/latest/), 2026-11-19) | Clocked serial (2-wire, probe owns SWCLK) | SWCLK/SWDIO on two `uio` pins | none beyond wiring to the target's voltage | SWCLK is probe-chosen — no standard ceiling to meet; 33-bit transfer + parity per DP access is state, not speed | est. 120–200 (IDCODE + one memory read) | [A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 12,395](https://github.com/search?q=swd+in%3Aname%2Cdescription%2Ctopics&type=repositories) (token noise included) · [SE 171](https://electronics.stackexchange.com/questions/tagged/swd), 2026-11-19 | **Build — #452.** Developer-facing breadth claim; clocked serial the SPI path already proves |

### Candidate (worth filing after the nine land)

| Protocol (year, domain) | Primitive class | Pins and roles | External parts | Timing vs 50 MHz | Program memory (est.) | Demand | Verdict |
|---|---|---|---|---|---|---|---|
| **SMBus / PMBus** (Intel et al., 1995, system management) ([SMBus specs](https://www.smbus.org/specs/), current spec v3.3.1 dated 2024-10-20, retrieved 2026-11-19; [wiki I²C SMBus section](https://en.wikipedia.org/wiki/I2C), 2026-11-19) | Clocked serial, open-drain, address-acked | `uio[2..3]` open-drain — the proven `i2c` roles | none (same pull-ups as I2C) | SCL 10–100 kHz → 500–5,000 cycles per SCL (I2C-class; the committed 125/500-cycle SCL programs already meet the I²C minimums) | est. 200–256 (`i2c_fast` is 245 words; PEC CRC-8 fits P1) — tight | [A 10](https://downloads.arduino.cc/libraries/library_index.json) · [G 485](https://github.com/search?q=smbus+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 62](https://electronics.stackexchange.com/questions/tagged/smbus), 2026-11-19 | Candidate — mostly a reuse of the proven I2C path plus PEC; file after I2C-focused rows settle |
| **LIN** (LIN Consortium, ~2000, automotive subbus) ([wiki LIN](https://en.wikipedia.org/wiki/Local_Interconnect_Network), 2026-11-19) | UART-framed with break sync | TX through the transceiver on one `uo` bit, RX on one `ui` bit | LIN transceiver on a Pmod | up to 19.2 kbit/s (same source) → 2,604 cycles/bit; break ≥ 13 dominant bit times → ≥ 33,855 cycles of `WAIT` | est. 120–200 (PID checksum is an XOR/add loop) | [A 31](https://downloads.arduino.cc/libraries/library_index.json) · [G 372](https://github.com/search?q=%22lin+bus%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 33](https://electronics.stackexchange.com/questions/tagged/lin), 2026-11-19 | Candidate — real automotive demand, small ecosystem; UART-framed so cheap to build |
| **NMEA 0183** (NMEA, 1980s, marine) ([wiki NMEA 0183](https://en.wikipedia.org/wiki/NMEA_0183), 2026-11-19) | UART-framed sentences | TX `uo[0]`, RX `ui[1]` — the `uart` roles | line driver/receiver for RS-422-level talker pairs (or direct wiring to a 3.3 V-tolerant listener) | 4,800 baud (same source) → 10,417 cycles/bit; AIS variants 38,400 → 1,302 | TX 40–120; RX with sentence parsing 120–200 | [A 59](https://downloads.arduino.cc/libraries/library_index.json) · [G 3,499](https://github.com/search?q=nmea+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no `nmea` tag), 2026-11-19 | Candidate — pure UART framing; demand concentrated in marine/GPS communities |
| **SBUS** (Futaba, ~2010s, hobby RC) ([bolderflight/sbus README](https://github.com/bolderflight/sbus), 2026-11-19) | UART-framed, inverted 100 kbaud 8E1 | RX on one `ui` bit (channel data); TX for trainer mode | none (3.3 V logic; series resistor) | 100,000 baud, 8E1 + 2 stop, 25 bytes/frame (same source) → 500 cycles/bit, 300 bits ≈ 3.0 ms; inverted logic: RX loop XORs each sample (1 instr/bit) | est. 150–256 — buffering a 25-byte frame in program memory is the squeeze | [A 28](https://downloads.arduino.cc/libraries/library_index.json) · [G 1,594](https://github.com/search?q=sbus+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no `sbus` tag), 2026-11-19 | Candidate — hobby demand; no transceiver needed; buffering is the open question |
| **Microwire** (National Semiconductor, 1980s, EEPROMs) ([wiki Microwire](https://en.wikipedia.org/wiki/Microwire), 2026-11-19) | Clocked serial (SPI's predecessor, same source) | CS/data/clock on `uio[0..3]` — the `spi` roles | none | firmware-chosen clock at the proven 4–10 cycles/bit | est. ≤ 140 (the `spi_mode*` images are 110–140) | [A 2](https://downloads.arduino.cc/libraries/library_index.json) · [G 49](https://github.com/search?q=microwire+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — trivially close to built SPI; low standalone demand |
| **JTAG** (IEEE 1149.1, 1990, test/debug) ([wiki JTAG](https://en.wikipedia.org/wiki/Joint_Test_Action_Group), 2026-11-19) | Clocked serial with a TAP state machine | TCK/TMS/TDI out on `uio` pins, TDO in on one `ui` bit | level shifting to the target's voltage | TCK is firmware-chosen; the standard sets no ceiling (same source) — no accuracy flag, only loop cost per TCK | est. 100–180 for an IDCODE-only probe | [A 21](https://downloads.arduino.cc/libraries/library_index.json) · [G 2,029](https://github.com/search?q=jtag+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 375](https://electronics.stackexchange.com/questions/tagged/jtag), 2026-11-19 | Candidate — high SE demand; the TAP state machine is real state but no timing wall |
| **SSI encoders** (SSI, 1980s, position feedback) ([wiki SSI](https://en.wikipedia.org/wiki/Synchronous_Serial_Interface), 2026-11-19) | Clocked serial (controller-clock latched data) | clock out on one `uio`, data in on one `ui` | RS-422 receivers for the encoder's differential pairs (same source) | clock firmware-chosen; a 25-bit position read is a short unrolled loop | est. 80–140 + gray-code decode | [A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 8](https://github.com/search?q=%22ssi+encoder%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — industrially real, tiny ecosystem; nearly free after SPI |
| **RC5 IR** (Philips, ~1990, remote control) ([sbprojects RC-5](https://sbprojects.net/knowledge/ir/rc5.php), 2026-11-19) | Manchester/biphase over a 36 kHz carrier | one `uo[n]` to the LED (TX); one `ui[n]` from a demod module (RX) | IR LED (TX); demodulating receiver (RX) | 36 kHz carrier, half-bit 889 µs = 44,450 cycles (same source) — DR 0015's own table notes RC-5 needs no Manchester primitive | est. 100–180 | [A 4](https://downloads.arduino.cc/libraries/library_index.json) · [G 1,595](https://github.com/search?q=rc5+in%3Aname%2Cdescription%2Ctopics&type=repositories) (count includes the RC5 cipher) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — feasible and slow, but demand is small next to NEC IR |
| **DShot** (betaflight community, 2016, ESC control) ([betaflight repo](https://github.com/betaflight/betaflight), 2026-11-19) | Pulse-width / single-wire, CRC4 | one `uo[n]` push-pull (TX); bidir variants read on the same pin | none (3.3 V ESC signal) | DShot300/600 → 167/83 cycles/bit with 16-unit duty inside each bit (bit-rate grades community-documented — unsourced here, not used for ranking) — **tight flag** at DShot600 | est. 120–200 (unrolled pulse chains à la `ws2812`) | [A 24](https://downloads.arduino.cc/libraries/library_index.json) · [G 313](https://github.com/search?q=dshot+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — the TX pulse chains are within the proven `ws2812` edge class; narrow demand |
| **DCC** (NMRA S-9.x, 1990s, model railroading) ([wiki DCC](https://en.wikipedia.org/wiki/Digital_Command_Control), 2026-11-19) | Pulse-width (bipolar half-bits on the rail) | two `uo` bits to the booster's direction inputs | H-bridge booster to the track (the rail signal is not 3.3 V logic) | "1" half-bits 58 µs → 2,900 cycles, "0" half-bits ≥ 90 µs (same source) — trivial cycle counts | est. 120–200 (preamble + packet encode) | [A 70](https://downloads.arduino.cc/libraries/library_index.json) · [G 100](https://github.com/search?q=%22dcc+decoder%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — a real installed base in hobby rail; booster needed for the rail |
| **Wiegand** (1970s, access control) ([wiki Wiegand interface](https://en.wikipedia.org/wiki/Wiegand_interface), 2026-11-19) | Pulse-pair, two one-way wires | D0/D1 on two `ui` bits (reader side); emit on two `uo` bits | none (open-collector sources with pull-ups) | pulse widths in the 10–100 µs class (pulse figures on the cited page — unsourced here, not used for ranking) → 500–5,000 cycles, easy | est. 40–80 | [A 7](https://downloads.arduino.cc/libraries/library_index.json) · [G 532](https://github.com/search?q=wiegand+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — cheap to build both directions; access-control niche |
| **N64 / GameCube controller** (Nintendo, 1996/2001, consoles) ([wiki N64 accessories](https://en.wikipedia.org/wiki/Nintendo_64_accessories), 2026-11-19) | Pulse-width / single-wire, console-polled | one `uio[n]`, **open-drain**, console drives polling | none (3.3 V single line with pull-up) | ~4 µs/bit polling (community-documented — unsourced here, not used for ranking) → 200 cycles/bit with 1–3 µs sub-pulses — **borderline flag** | est. 100–180 (emit poll-response bursts) | [A 9](https://downloads.arduino.cc/libraries/library_index.json) · [G 389](https://github.com/search?q=%22n64+controller%22+OR+%22gamecube+controller%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — the open-drain mid-bit-turnaround PS/2 already proved; nostalgia demand |
| **HDLC / AX.25** (ISO HDLC 1976; AX.25 1980s, amateur radio) ([wiki AX.25](https://en.wikipedia.org/wiki/AX.25), 2026-11-19) | Bit-stuffing + CRC (NRZI at the modem) | TX/RX through the modem on `uo`/`ui` bits | Bell-202-class AFSK modem for 1,200 baud (same source) | 1,200 baud → 41,667 cycles/bit — slow; stuffing and CRC-16 are exactly P2 + P1 | est. 180–256 — tight | [A 2](https://downloads.arduino.cc/libraries/library_index.json) · [G 783](https://github.com/search?q=hdlc+OR+ax25+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — the admitted primitives fit it best of anything here; the radio channel lives off-chip in the modem |
| **SMPTE LTC** (SMPTE 12M, 1980s, timecode) ([wiki linear timecode](https://en.wikipedia.org/wiki/Linear_timecode), 2026-11-19) | Manchester/biphase, audio-rate | one `uo[n]` out (TX); one `ui[n]` in (RX) | audio jack wiring; a comparator for RX level safety | 80 bits/frame × 25 fps = 2,000 bit/s (same source) → 25,000 cycles/bit — very easy | est. 120–200 | [A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 646](https://github.com/search?q=smpte+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | Candidate — an easy biphase win if a media-use story is wanted |

### Deferred

| Protocol (year, domain) | Primitive class | Pins and roles | External parts | Timing vs 50 MHz | Program memory (est.) | Demand | Verdict |
|---|---|---|---|---|---|---|---|
| **MIL-STD-1553** (1973/1978, avionics) ([wiki MIL-STD-1553](https://en.wikipedia.org/wiki/MIL-STD-1553), 2026-11-19) | Manchester/biphase (Manchester II, same source) | TX/RX through transformer-coupled transceivers | mil-spec transceiver + isolation transformers — far beyond a Pmod | 1 Mbit/s (same source) → 50 cycles/bit, half-bits 25 cycles — **tight flag**; sync patterns and response windows add state | est. 180–256, unproven | [A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 76](https://github.com/search?q=%22mil-std-1553%22+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE n/a](https://electronics.stackexchange.com/tags) (no tag), 2026-11-19 | **Deferred** — half-bit loop rate is at the ISA's limit and the line interface is a project of its own; revisit only after the nine land |
| **S/PDIF** (Sony/Philips, 1980s, consumer digital audio) ([wiki S/PDIF](https://en.wikipedia.org/wiki/S/PDIF), 2026-11-19) | Biphase-mark (same source) | one `uo[n]` through a line driver | coax/optical driver (pulse transformer or TOTX) | frame = 64 bit-cells at fs; 44.1 kHz → 2.8224 Mbit/s → 17.7 cycles per cell, half-cell ≈ 9 cycles — below the demonstrated loop rate (the fastest proven bit loop is SPI at 10 cycles/bit) | not scheduled | [A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 187](https://github.com/search?q=spdif+in%3Aname%2Cdescription%2Ctopics&type=repositories) · [SE 23](https://electronics.stackexchange.com/questions/tagged/spdif), 2026-11-19 | **Deferred** — timing, not demand; would need a sub-10-cycle biphase loop the ISA has not demonstrated |

### Not a fit

| Protocol (year, domain) | Reason |
|---|---|
| **GPIB** (IEEE 488, 1975, instrumentation) ([wiki IEEE-488](https://en.wikipedia.org/wiki/IEEE-488), 2026-11-19) | Byte-parallel: 8 bidirectional data lines plus DAV/NRFD/NDAC and management lines (~12–16 pins) with multi-drop open-collector handshaking — exceeds the 8+8+3 pad budget outright |
| **Centronics parallel** (1970, printers) ([wiki Centronics](https://en.wikipedia.org/wiki/Centronics), 2026-11-19) | Byte-parallel data plus strobe/handshakes — same pin-budget wall as GPIB, with none of the breadth value |
| **CAN FD** (Bosch, 2012, vehicles) ([wiki CAN FD](https://en.wikipedia.org/wiki/CAN_FD), 2026-11-19) | Data-phase bit rates up to 8 Mbit/s (same source) → 6.25 cycles/bit — below anything the ISA loop rate can schedule; classic CAN is row CAN 2.0A above |
| **10BASE-T** (IEEE 802.3i, 1990, Ethernet) | Not a fit for the frozen ISA by DR [0015](../spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md)'s verdict: TX needs P3 (Manchester) and RX needs P4 (sampler), neither admitted |
| **HART** (1980s, process control) ([wiki HART](https://en.wikipedia.org/wiki/Highway_Addressable_Remote_Transducer_Protocol), 2026-11-19) | Bell-202 1,200-baud FSK superimposed on a 4–20 mA current loop (same source): the protocol lives in an external modem's analog front end — the chip's share would be a plain UART |
| **Kansas City Standard** (1970s, cassette storage) ([wiki KCS](https://en.wikipedia.org/wiki/Kansas_City_standard), 2026-11-19) | 300/1200-baud AFSK to cassette audio (same source) is bit-bangable, but the demand proxies are ~zero ([A 0](https://downloads.arduino.cc/libraries/library_index.json) · [G 18](https://github.com/search?q=%22kansas+city+standard%22+in%3Aname%2Cdescription%2Ctopics&type=repositories), 2026-11-19) — no modern use to serve |

## Ranked shortlist (build order)

Chosen on the demand columns above, adjusted for fit and verification cost;
each entry names the issue that carries it.

1. **#444 — MIDI.** Largest ecosystem of any row (Arduino 293 libs, GitHub 61,899 repos). UART-framed at 1,600 cycles/bit — the proven UART path with a DIN-and-opto front end. Cheapest evidence of the nine.
2. **#447 — 1-Wire.** Strong sensor demand (Arduino 151, GitHub 1,823, SE 90) and the single open-drain line extends the row-13 stretch claim (a direction the core protocols never use) onto a second protocol.
3. **#446 — RS-485 Modbus RTU.** Highest industrial demand (Arduino 276, GitHub 21,295, SE 155). UART-framed; CRC-16 through the admitted P1; the only new moving part is the RS-485 Pmod.
4. **#445 — DMX512.** Transmit-only controller at 200 cycles/bit on the same RS-485 Pmod; break/MAB are long `WAIT`s. Demand solid (Arduino 90, GitHub 676, SE 67) and the role (one-way controller) keeps the bench small.
5. **#448 — NEC infrared.** Pulse-width TX plus decode from a demod module; carrier and bit times both inside the proven pulse chains; SE's `infrared` tag (787) is the broad audience signal.
6. **#451 — I2S.** Real audio demand (Arduino 82, GitHub 2,675, SE 161); clocked serial the SPI path proves, with the BCLK-period flag (≈16 cycles) stated, not hidden.
7. **#450 — CAN 2.0A.** Highest Q&A volume of the nine (SE 899; Arduino 257, GitHub 7,747) but the hardest firmware: bitwise arbitration, ACK, error states, and the ≥ 500 kbit/s tight flag. Worth the cost; scoped to the 125–250 kbit/s class.
8. **#449 — DALI.** Niche demand (SE 105; Arduino 4) but a formal IEC standard with the slowest, easiest Manchester of any row; needs the 16–22.5 V line interface.
9. **#452 — SWD.** Developer-facing breadth claim (SE 171; GitHub count carries token noise). Clocked serial at a probe-chosen clock — no standard ceiling — so the work is protocol state, not timing.

Rows not on the shortlist stay candidate/deferred/not-a-fit as their table
rows say; a shortlist promotion means filing the issue, not editing this
file's verdict silently — the ranking above is the record of the decision
taken with this catalog.

## Sources and method

All demand proxies measured 2026-11-19. The three proxies are reproducible
without keys:

- **[A n] — Arduino Library Manager index**: the file
  <https://downloads.arduino.cc/libraries/library_index.json> (56,297
  libraries that day), counted with a case-insensitive, word-bounded regex
  over each library's `name` + `sentence`. Patterns used (uppercase-only for
  the short ambiguous tokens):

  <details>
  <summary>patterns per row</summary>

  ```
  MIDI: \bMIDI\b                       DMX: \bDMX\b                    Modbus: \bModbus\b
  LIN: \bLIN\b (uppercase-only)        NMEA: \bNMEA\b                  SBUS: \bS\.?BUS\b
  I2S: \bI2S\b                         SMBus: \bSMBus\b|\bSMB\b|\bPMBus\b|\bPMB\b
  Microwire: \bMicrowire\b             JTAG: \bJTAG\b                  SWD: \bSWD\b (uppercase-only)
  SSI: \bSSI\b (uppercase-only)        1-Wire: \b1[- ]?Wire\b|\bOneWire\b
  NEC IR: \bNEC\b (uppercase-only)     RC5: \bRC5\b|\bRC-5\b           DShot: \bDShot\b
  DCC: \bDCC\b (uppercase-only)        Wiegand: \bWiegand\b            N64/GC: \bN64\b|\bGame\s?Cube\b
  DALI: \bDALI\b                       MIL-1553: \b1553\b|\bMIL[- ]?STD\b
  LTC: \bLTC\b|\bSMPTE\b|\btimecode\b  S/PDIF: \bSPDIF\b|\bS/PDIF\b
  CAN: \bCAN\s?[-]?Bus\b|\bCANBUS\b|\bCAN\d\b        HDLC/AX.25: \bHDLC\b|\bAX\s?\.?\s?25\b
  GPIB: \bGPIB\b|\bIEEE[- ]?488\b      Centronics: \bCentronics\b      CAN FD: \bCAN\s?FD\b
  HART: \bHART\b (uppercase-only)      KCS: \bKansas\s+City\b|\bKCS\b (uppercase-only)
  ```
  </details>

- **[G n] — GitHub repository counts**: `total_count` from
  `https://api.github.com/search/repositories?q=<query>&per_page=1`; the
  human-viewable query is linked from each cell. Counts are token-based and
  carry noise where a token has other meanings (noted in the affected cells:
  `dali`, `swd`, `rc5`).
- **[SE n] — electronics.StackExchange tag size**: question count for the
  named tag from `https://api.stackexchange.com/2.3/tags/<tag>/info?site=electronics`,
  linked to the public tag page per cell. Rows with no such tag say
  *no tag* — a missing measurement, not a zero.

Timing figures cite, per row, the standard or public summary fetched the same
day (linked in the row): Wikipedia summaries for MIDI, DMX512, NMEA 0183, LIN,
I2S, I²C/SMBus context, JTAG/SWD, 1-Wire, DALI, MIL-STD-1553, linear
timecode, S/PDIF, CAN, CAN FD, AX.25, DCC, Wiegand, N64 accessories, IEEE-488,
Centronics, HART, Kansas City standard, Microwire and SSI; sbprojects.net for
the NEC and RC-5 infrared encodings; the Futaba-SBUS framing from the
bolderflight/sbus project README; the Modbus serial-line framing from the
archived Modbus over Serial Line V1.02 PDF; the SMBus specification family
from smbus.org. Specifications that were not fetchable without a key are not
cited as sources for figures here; where a figure rests on community
documentation only, the cell says *unsourced, not used for ranking*.

This catalog inherits the repo's evidence rules — a protocol moves from
"build" to "built" only with program, bench, independent model and record,
and nothing here edits the frozen ISA (DR 0017) or relaxes the ratified spec.
