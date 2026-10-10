# 0015: Stretch Protocols With Protocol-Neutral ISA Primitives — Rescoping DR 0011

Status: **Proposed 2026-10-09.** It goes to ratification through the
two-key (`RATIFY-KEY`) mechanism on the PR that carries it (`spec/README.md`).
That mechanism has never run here (DR 0006, issue #44), so this is a proposal
like DRs 0001–0005, 0007, 0008, 0010, 0012 and 0013. It edits no target-spec
value, relaxes nothing ratified or proposed, and makes no row met.
Date: 2026-10-09
Issues: #130 (this decision); #129 (area, DR 0014); #133 (pads); #44
(ratification). Depends on DR [`0012`](0012-control-space-and-runtime-pin-direction.md)
(the control space the primitives live in). Starts from the current-ISA
baseline in DR [`0011`](0011-stretch-protocols-feasibility.md).

**Revision (2026-10-09, review of PR #153).** The first draft admitted P3
(Manchester transmit) and 10BASE-T TX, although P3 failed this record's own
test 3 (three unrelated protocols). P3 is now **not admitted** and
10BASE-T TX is **deferred**, conditionally; test 3 is worded more precisely
and is not relaxed (Admission test, P3, Verdicts, reopening condition 2).

**Revision (2026-10-09, issue #156).** This record was written against an
earlier draft of DR 0011 (PR #128 up to commit `0f085b5`), which carried a
"defer both" verdict and reopening conditions. DR 0011 merged as a
**baseline-only** record with no verdict. Every statement here about DR 0011
is reworded to match the merged text: the Relationship paragraph, Context,
Method, the baseline table, the `WAIT`/`Z` assumption, the 10BASE-T paragraphs that
describe the baseline, "Result against the baseline", reopening condition 3,
Consequences and Alternatives 1 and 3. Where this record fell back on
"DR 0011's defer", it now states the fallback itself. **No verdict, primitive,
admission test, count or area figure changes**, and every figure quoted from
DR 0011 still matches it. The title's "Rescoping DR 0011" is kept as the
record's name; it means this record re-asks row 2's question with primitives
added, not that it edits DR 0011.

**Numbering note.** When this record was numbered (2026-10-09), `origin/main`
had DRs 0001–0008, 0010, 0012 and 0013; PR #128 held 0011, PR #84 reserved
0009 and PR #147 held 0014. This record is 0015. DRs 0011 and 0014 have since
merged to main.

**Relationship to DR 0011.** DR 0011 is on main (merged by PR #128). It is a
**baseline only**: hand-counted, pure-firmware schedules for both protocols on
the ISA as built, with a list of what those schedules leave out. It gives no
verdict, defers nothing and rules nothing out. This record **keeps DR 0011's
hand-counted current-ISA schedules as the baseline** (quoted, not recomputed)
and asks the question the organizers' 2026-10-09 update changed: what if the
ISA gains a few protocol-neutral primitives? The two records do not conflict.
DR 0011 supplies the counts "against today's ISA"; this record's verdict
applies "against today's ISA plus the primitives admitted below". DR 0011
points here for the verdict. Where this record needs a fallback (reopening
condition 3, Consequences), it is row 2 as it reads today, not a DR 0011
verdict.

## Context

The organizers' update, quoted verbatim in issue #130:

> For USB and Ethernet, the more of the protocol work (line coding, CRC, clock
> recovery) your chip does itself, the better.

> Flexibility is the main thing: can the chip be reprogrammed to support
> protocols it wasn't designed for?

A plain defer leaves the stretch credit on the table. `CLAUDE.md` bars a
fixed-function USB or Ethernet block; it does not bar primitives the firmware
composes. DR 0011's baseline shows that cycles are not what its low-speed
USB transmit schedule runs short of (33 cycles per bit, about 10 used). The
open part it names is state: 4 registers, no instruction that reads `C`, no
data memory, 256 words. It did not demonstrate a complete schedule with CRC16
on the current ISA and did not rule one out. A CRC engine, a stuffing unit and
a Manchester stage hold that state in hardware, so the firmware does not have
to find a register allocation for it.

### Admission test for a primitive

A primitive is admitted by this record only if all four hold. This is what
keeps the ISA the product and keeps out a peripheral.

1. **No protocol framing.** No start/stop/ACK/address/header/packet concept.
   It transforms or times bits; the firmware owns the frame.
2. **Fixed latency.** Its cycle cost is fixed by the instruction word (row 3).
   A blocking "wait for edge" read is therefore ruled out; hardware may run
   asynchronously, firmware polls a flag.
3. **At least three unrelated protocols** can use it with different
   configuration (table below). "Use" means the protocol at its own rate
   **needs** the primitive on this ISA (the firmware alone cannot do that
   job in the cycles available), not merely that it could be configured
   onto it. Protocols of one family (for example the 802.3 Manchester PHYs)
   count once. This record makes **no exception** to this test; a primitive
   that fails it is not admitted, whatever target depends on it (P3,
   Verdicts).
4. **Reached through DR 0012's control space** (`WCTL`/`RCTL`, indices
   `0x10`–`0x1F`, reserved there for this record). No new opcode: DR 0001's
   table stays full at 16 of 16.

## Method and what is, and is not, a number

- **No tool was run.** No synthesis, timing, simulation or firmware exists for
  this record. Schedules are **hand counts**, not assembled or simulated
  programs, and are not evidence of protocol conformance. The primitives
  below are proposals; none exists in RTL.
- **Area figures are estimates, flow-unattributed.** The only tool-produced
  area is the existing design's: 10,323.2556 µm², 567 cells, **klt/Yosys**
  cell area (not placed die area), from `info.yaml` as quoted in DR 0014. Its
  average is 18.2 µm² per cell (10,323.2556 / 567). Each primitive is sized as
  a rough **cell count** (flops plus combinational), converted at that
  average, with a wide band because flops are larger than the average. DR 0014
  (PR #147) is the source of the 2×2 core area (126,685 µm², LibreLane die
  model), the macro (28,127 µm²) and the 38,450 µm² cells+macro floor. This is
  **not** a CMOS5L Tiny Tapeout (LibreLane) number for these blocks; when the
  blocks exist, the LibreLane flow's number is the one of record and any
  disagreement with the klt number is a finding to record (`CLAUDE.md`, two
  flows).
- **Timing cost is qualitative.** Row 4 has closure at 50 MHz at 3 of 6
  corners on the LibreLane flow and no klt result; no slack figure is quoted
  here. No claim is made that any primitive preserves that closure. It is a
  re-run obligation (Consequences).
- **Standards figures from memory** (polynomials, residuals, jitter limits)
  are marked "confirm". The 802.3 text is paywalled and was not retrievable;
  USB 2.0 figures follow DR 0011's reading.
- **Not counted in the digital budget, as in DR 0011:** USB signalling
  levels, the low-speed pull-up and transceiver; 10BASE-T differential drive,
  magnetics, link-test pulses. An external part turns pin-level streams into
  line signals.
- **Pads are uncharacterized (#133).** Every assumption below about how fast
  a pad toggles, its rise/fall time, or its 10 MHz behaviour is
  **unverified**. In particular the 10BASE-T edge-rate and transmit-jitter
  assumptions (a 10 ns mid-bit skew at 50 MHz; Clause 14 limits, "confirm")
  are unverified, and so is the USB low-speed rise/fall requirement.

## The candidate primitives

All are `WCTL k, Rs` / `RCTL Rd, k` accesses (DR 0012). None sets `Z`/`C`
(DR 0012), so each flag read is followed by an `AND` to branch, and the
schedules below count that.

### P1. CRC / LFSR step with programmable polynomial

- **Interface.** `CRC_CFG` (width 1–32, direction reflected/normal, read-out
  inversion, which byte is next), `CRC_POLY` and `CRC_STATE` written and read
  a byte at a time (4 accesses each), `CRC_BIT` (`WCTL`, bit 0 of `Rs` is
  shifted in, 1 cycle), `CRC_BYTE` (`WCTL`, 8 bits from `Rs`, 1 cycle plus 8
  stall cycles, fixed), `CRC_NEXT` (`RCTL`, returns the next byte of
  `state ^ xorout` and advances a 2-bit pointer; a read with a side effect,
  like DR 0012's `PM_DATA_LO`). With data-in tied to 0 and a non-zero seed the
  same step is a Galois LFSR (scramblers, PRBS, whitening); no extra logic.
- **Why it is neutral.** It is `state' = shift(state) ^ (feedback ? poly : 0)`.
  It knows no frame.
- **Rough area (estimate).** About 80 flops (32 state, 32 polynomial, width,
  config, byte counter, pointer) plus about 130 combinational cells (32 AND +
  32 XOR step, load/shift/width muxing, read mux) = about 210 cells, **about
  3,800 µm²** at the design average, band 3,000–6,000 µm². The byte op reuses
  the bit step (8 cycles) instead of unrolling it eight times; an unrolled
  byte step would be several times larger and is not proposed.
- **Rough timing cost.** One AND-XOR level on the state: shorter than the
  existing 8-bit adder path as a structural expectation, **not measured**. The
  `RCTL` read mux grows by one source (all control reads share DR 0012's mux).
- **Protocols served.**

  | Class | Protocols and settings (polynomials: confirm) |
  |---|---|
  | Core | none needs it. DR 0013's load CRC (CRC-16/XMODEM) could reuse this engine in place of the hard-wired `PM_CRC`; that is an option for DR 0012/0013, not decided here |
  | Stretch | USB CRC5 (0x05) and CRC16 (0x8005, seed all ones, reflected form, residual constant; confirm); Ethernet CRC-32 (0x04C11DB7, reflected 0xEDB88320, seed all ones, residual constant; confirm) |
  | Plausible reuse (considered here, so **ineligible as row 13 evidence**) | 1-Wire CRC8 (0x31 reflected), SMBus PEC CRC8 (0x07), Modbus RTU CRC16 (0x8005 reflected), HDLC/PPP CRC16 (0x1021 reflected) and CRC32, SD CRC7/CRC16, CAN CRC15 (0x4599, normal form, width 15), BLE CRC24 and data whitening (LFSR) |

### P2. NRZI encode/decode with a bit-stuff counter

- **Interface.** `LINE_CFG` (NRZI mode: none / zero-toggles / one-toggles;
  stuff rule: off / after N ones / after N equal bits; N), `LINE_PUT`
  (`WCTL`, bit 0 of `Rs` is the data bit), `LINE_OUT` (`RCTL`, returns the
  line level in bit 0 and its complement in bit 1, so one `OUT` can drive a
  differential pair), `LINE_STUF` (`RCTL`, 1 if the last `LINE_PUT` emitted a
  stuffed bit and **did not consume** the data bit). Firmware advances its
  shifter only when `LINE_STUF` is 0. The unit decides nothing about frames;
  the same data bit is simply presented again after a stuff slot.
- **Rough area (estimate).** About 12 flops (level, ones counter, limit,
  mode, stuffed flag) plus about 30 cells = about 42 cells, **about 800 µm²**,
  band 500–1,200.
- **Rough timing cost.** A 3-bit compare and a toggle: negligible
  structurally, unmeasured.
- **Protocols served.** Stretch: USB (zero-toggles, N = 6; the run count
  includes the last `1` of SYNC, which falls out of keeping the counter
  across the SYNC bits). Plausible reuse (ineligible as row 13 evidence):
  HDLC/PPP/SDLC (N = 5 ones; NRZ or NRZI), CAN (stuff after 5 equal bits of
  either polarity, which is why the stuff rule has an "equal bits" form),
  NRZI-coded links in general. Core: none.

### P3. Manchester transmit stage

- **Interface.** `MAN_CFG` (half-bit period `H` in cycles, pin mask,
  polarity), `MAN_PUT` (`WCTL`, bit 0 of `Rs` is the first-half level). The
  stage drives the masked `uo_out` pins to the level, then toggles them `H`
  cycles after the `WCTL` retires, and holds. The masked pins override `OUT`
  so the other seven port bits are not disturbed (the pin-sharing limitation
  DR 0011 records for 10BASE-T, removed).
- **Rough area (estimate).** About 20 flops (half-period counter and
  configuration, mask, toggle state) plus about 30 cells = about 50 cells,
  **about 900 µm²**, band 600–1,400.
- **Rough timing cost.** A small counter and an 8-way output override mux on
  `uo_out`. The mux sits on the output path to the pad; its cost against the
  pad is unverified (#133).
- **Protocols served.** Stretch: 10BASE-T transmit. Core: none. That is
  **one** protocol, so **P3 fails admission test 3** and is not admitted
  (Verdicts). The search for others, recorded so it is not repeated:

  | Candidate (figures from memory, confirm) | Half-bit at 50 MHz | Needs P3? |
  |---|---|---|
  | Other 802.3 Manchester PHYs (10BASE5/10BASE2 style) | 2.5 cycles (5-cycle bit), same as 10BASE-T | Same family as 10BASE-T; counts once under test 3 |
  | RC-5/RC-6 style IR, baseband | ~889 µs ≈ 44,000 cycles | No: an `OUT` plus a `WAIT` loop places the edge exactly. P3 also has no IR carrier, so it does not do the modulated part either |
  | DALI forward frame (1200 bit/s) | ~417 µs ≈ 20,800 cycles | No, for the same reason |
  | MIL-STD-1553 (1 Mbit/s, Manchester II) | 500 ns = 25 cycles | No: 25 cycles leaves the firmware ample slots for `OUT`, shift and loop |

  These slower links *could* be configured onto P3, but none needs it, and
  test 3 asks for need. Counting them would stretch the test to admit the
  one primitive a target depends on. The ~20-flop size above also assumes a
  small `H`; serving the slow links would need a counter of about 16 bits.
  Because RC-5/RC-6 IR (a row 13 candidate) was considered here, **naming it
  here still removes it from row 13's list**, and so do DALI and
  MIL-STD-1553. Row 13's protocol must be chosen from outside this record's
  tables.
- **Half-cycle edges are not proposed.** A mid-bit edge at 2.5 cycles (50 MHz)
  needs a negative-edge output flop. That adds a second clock-edge timing
  domain to a flow that has no 50 MHz closure evidence across all corners
  (row 4); listed as a reopening option, not admitted.

### P4. Edge-locked bit sampler (clock recovery)

- **Why it is a sampler and not a blocking read.** A `RCTL` that waits for
  the next edge would have data-dependent latency (row 3). So the hardware
  runs on its own and the firmware polls: a bit shifter and a one-byte holding
  register fill at hardware timing, the firmware reads the byte whenever it
  is ready (within one byte time).
- **Interface.** `SAMP_CFG` (input pin select and polarity, period `P` in
  cycles, sample phase, mode: edge-restart / Manchester / one-shot, optional
  NRZI-decode and de-stuff reusing P2, idle limit), `SAMP_ARM` (`WCTL`: the
  first edge after the arm starts the capture), `SAMP_STAT` (`RCTL`: bit 0
  byte ready, bit 1 idle-timeout, bit 2 overrun, bit 3 stuff violation),
  `SAMP_BYTE` (`RCTL`). In edge-restart mode every input edge re-loads the
  phase counter to the sample phase (clock recovery); in Manchester mode the
  edge in the middle of the bit cell re-loads it and the edge direction is the
  bit; the framing of the bits (SYNC, preamble, SFD) stays in firmware.
- **Rough area (estimate).** About 70 flops (two-flop input synchronizer,
  period, phase counter, shift register, holding register, bit count, idle
  counter and limit, flags, configuration) plus about 110 cells = about 180
  cells, **about 3,300 µm²**, band 2,500–5,000. Sharing P2's destuff/NRZI
  logic is assumed; without sharing, add about 800.
- **Rough timing cost.** The input synchronizer adds a fixed two-cycle latency
  and a ±0.5 cycle quantization (10 ns at 50 MHz). Counters only; no wide
  combinational path.
- **Protocols served.** Stretch: USB receive (edge-restart, NRZI decode,
  de-stuff), 10BASE-T receive (Manchester). Plausible reuse (ineligible as row
  13 evidence): RC-5 receive, DMX512 receive, LIN, CAN receive (with a stuff
  rule), 1-Wire slot sampling. Core: UART receive in one-shot mode
  (start-edge-locked mid-bit sampling). The core already receives UART in
  firmware (DR 0001), so this is a convenience there, not a need.
- **Neutrality risk.** In one-shot mode this primitive is two steps from a
  UART receiver. The admission test (no framing, three unrelated protocols,
  configuration only) holds, but a reviewer should watch for any field that
  names a protocol. P4 is the one most likely to be refused on that ground
  (Verdicts).

### Totals

| Primitive | Cells (est.) | µm² (est., design-average cell) | Band |
|---|---|---|---|
| P1 CRC / LFSR | ~210 | ~3,800 | 3,000–6,000 |
| P2 NRZI + stuff | ~42 | ~800 | 500–1,200 |
| P3 Manchester TX (not admitted) | ~50 | ~900 | 600–1,400 |
| P4 sampler (not admitted) | ~180 | ~3,300 | 2,500–5,000 |
| **Admitted (P1, P2)** | ~252 | **~4,600** | 3,500–7,200 |
| **All four** | ~480 | **~8,800** | 6,600–13,600 |

Against DR 0014's numbers: current cells+macro 38,450 µm² (30.4 % of the 2×2
core of 126,685 µm²). Adding ~8,800 gives ~47,250 µm², **~37 %** of the 2×2
core (band 36–41 %), below the repo's 60 % density target; the admitted
pair alone (~4,600) gives ~43,050 µm², **~34 %** (band 33–36 %). These are
floors-plus-estimates, not placed areas (wire, clock tree, fill excluded). The
conclusion for #129: **the primitives fit in 2×2** and do not, on these
numbers, move the tile recommendation of DR 0014; their price is ISA and
verification effort, and the 6-hour Actions-run risk (#134) which scales with
cell count and must be read from a real run, not from this table. The cell
total roughly doubles (+~480 cells on 567), which is the number to watch for
that risk.

## Re-counted schedules

Baseline is DR 0011's, quoted:

| | DR 0011 baseline (current ISA, 50 MHz) |
|---|---|
| USB-LS TX | 33-cycle uniform bit; stuffing + NRZI uses ~10 cycles; 21 words per bit copy × 8 copies = 168 of 256 words; CRC16 not included in the baseline schedule |
| USB-LS RX | poll loop 3 cycles = 60 ns vs ±8.33 cycle window; no CRC, no storage |
| 10BASE-T TX | 5-cycle bit, 2/3-cycle half-bit (40/60 ns, ±10 ns skew); serializer only, 5 spare slots per 40-cycle octet, no FCS; pin sharing |
| 10BASE-T RX | 60 ns poll vs 50 ns half-bit: that poll loop does not observe every half-bit level; a fixed-cycle sampling receiver is described but not scheduled |

Assumptions for the counts below: every instruction 1 cycle, `WAIT n` = n+1
cycles, branches cost 1 cycle taken or not (DR 0005), `WCTL`/`RCTL` 1 cycle
except `CRC_BYTE` (1 + 8 stall). `WAIT` leaves `Z` untouched. That is read
from `rtl/protocol_core.v`, not assumed: `flag_z` is written only by the
`ADD`/`SUB`/`AND`/`OR`/`XOR` cases, and neither the `OP_WAIT` case nor the
`waiting` stall branch writes it. Neither record depends on it today: in
DR 0011's listing and in the listings below, every `BZ`/`BNZ` directly
follows the ALU op that sets `Z`, with at most one `SHF` between in
DR 0011's (`SHF` writes `C` only). A "word" is one instruction.

### Low-speed USB, transmit, 50 MHz, 33-cycle bit

Registers: `R0` data (LSB first), `R1` line pattern, `R2` bits left in the
byte, `R3` temporary. P2 holds the stuff counter and NRZI level; P1 holds the
CRC. Prologue (not in the slot): configure P2 (zero-toggles, N = 6, idle
level J), P1 (CRC16 or CRC5 for the field), `R2 = 8`.

```
loop:
a  WCTL LINE_PUT,R0     ; present the data bit, unit applies stuff + NRZI
b  RCTL R1,LINE_OUT     ; R1 = {D-,D+}
c  OUT  uo_out,R1       ; cycle 2 of the slot on every path
d  RCTL R3,LINE_STUF
e  AND  R3,R3           ; Z = not stuffed
f  BZ   consume
; stuffed slot (data bit not consumed): 6 instr so far
   WAIT 25              ; 26 cycles
   JMP  loop            ; 6 + 26 + 1 = 33
consume:                ; reached at cycle 6
g  WCTL CRC_BIT,R0      ; omitted in the SYNC/PID copy and the CRC copy
h  SHF  R0,right
i  LDI  R3,1
j  SUB  R2,R3           ; Z = last bit of the byte
k  BZ   byteend         ; cycle 10 -> 11
m  WAIT 20              ; 21 cycles
n  JMP  loop            ; 11 + 21 + 1 = 33
byteend:                ; entered after k (11 cycles used)
p  LDI  R0,next         ; or IN R0,ui_in for a payload byte
q  LDI  R2,8
r  WAIT 18              ; 19 cycles
s  JMP  loop            ; 11 + 1 + 1 + 19 + 1 = 33
```

All three paths are 33 cycles: data path 11 (`a`–`k`) + 21 + 1; byte-end
path 11 + 2 reload + 19 + 1; stuffed slot 6 + 26 + 1. The `OUT` is at cycle 2 of every slot on every path, so the bit
period has no data-dependent jitter. Instructions: 11 of 33 cycles on the
data path (the CRC-bytes copy has 10). Words: the loop plus its two exits is
about 18; three copies (SYNC/PID without CRC, data with CRC, CRC bytes read
with `CRC_NEXT` without CRC) are about 54, plus prologues and EOP (two `OUT`
slots of SE0, then J, via `OUT` of a constant): **about 80–100 words,
estimate**, against the baseline's 168 without CRC, and with no 8x copying
because the byte counter is `R2` and the stuff counter is in P2.

CRC16 is computed over the unstuffed field only because `g` sits on the
consume path. At the data end, `CRC_NEXT` supplies the two CRC bytes (read-out
inversion on) and the third copy sends them.

Rate: 33 cycles = 1.5152 Mbit/s, +1.01 % (inside ±1.5 %), the same as DR 0011.
At 60 MHz (sensitivity) the bit is 40 cycles and the rate exact; the loop is
the same with longer `WAIT`s.

### Low-speed USB, receive, 50 MHz, with P4

Hardware: P4 in edge-restart mode on D+, NRZI decode, de-stuff (N = 6), period
33. Edge placement is one clock (20 ns) rather than DR 0011's 60 ns poll
period, so the §7.1.15.1 window (±8.33 cycles) is met with 6× more margin than
the poll (estimate; synchronizer ±0.5 cycle included). Firmware per byte:

```
poll:  RCTL R3,SAMP_STAT / AND R3,R2 (R2 = 0x01) / BNZ got
       RCTL R3,SAMP_STAT / AND R3,R1 (R1 = 0x02) / BNZ idle / JMP poll   ; 7 cycles
got:   RCTL R0,SAMP_BYTE          ; 1
       WCTL CRC_BYTE,R0           ; 9
       OUT  uo_out,R0             ; stream the byte out (no data memory)
       JMP  poll
```

About 18 cycles of work per byte against a byte time of 8 × 33 = 264 cycles:
**cycles are not the limit; state moved into P1 and P4.** At the end the
firmware reads the 2-byte CRC residual with `CRC_NEXT` and compares to the
constant (confirm: 0xB001 in reflected form). EOP is SE0, which D+ alone
cannot show (D+ is low for both J and SE0 at low speed): the idle/stuff-
violation flags tell the firmware to `IN` D- and test both lines. That
sequence is **estimate, not a verified schedule**. What remains unsolved by
the primitives: no data memory, so the packet is streamed out, not stored; a
device that must answer a token within the turnaround time has its reply
latency set by firmware, which fits cycle-wise (the reply is a TX schedule of
the above) but is unproven.

### 10BASE-T, transmit, 50 MHz, 5-cycle bit

**This schedule depends on P3, which is not admitted** (it fails test 3).
It is kept as the cycle budget a future record would start from, not as a
basis for a verdict here (Verdicts: 10BASE-T TX is deferred).

Registers: `R0` octet, `R1` octet counter. P3 drives the pin and does the
mid-bit toggle; P1 does CRC-32.

```
bit k (k = 0..6), 5 cycles
t0  WCTL MAN_PUT,R0    ; first-half level; P3 toggles H cycles later
t1  WCTL CRC_BIT,R0    ; (payload copy only)
t2  SHF  R0,right
t3  WAIT 1             ; t3..t4
bit 7
t0  WCTL MAN_PUT,R0
t1  WCTL CRC_BIT,R0
t2  IN   R0,ui_in      ; next octet (LDI in the preamble copy,
                       ; RCTL CRC_NEXT in the FCS copy)
t3  NOP
t4  JMP  bit0
```

Three loop copies (preamble + SFD with `LDI`, payload from `ui_in` with CRC,
FCS with `CRC_NEXT` and no CRC), each 7 × 4 + 5 = 33 words: about 100 words
of loops plus about 30 of prologue (CRC-32 configuration and seed are 8
`WCTL` + 8 `LDI`, done in the 9.6 µs inter-frame gap, 480 cycles) and octet
counting: **about 130–150 words, estimate**. Every 5-cycle bit has 3 busy
slots and 2 free; the octet loop is 40 cycles exactly, so the baseline's
"5 spare slots" becomes 16, and the FCS, which the baseline schedule leaves
out, is computed by P1 in one slot per bit.
Preamble and SFD need no CRC (the copy omits `t1`).

What this does not fix, and must not be claimed to:

- **Half-bit skew.** The bit rate is exact (50 MHz ÷ 5 = 10.000 Mbit/s) but
  `H` can only be 2 or 3, so the mid-bit edge is 40/60 ns, ±10 ns off nominal
  on every bit. Whether Clause 14's transmit jitter limit tolerates that is
  **unverified** (confirm the figure) and depends on the pad (#133,
  unverified). At 60 MHz the bit is 6 cycles and `H` = 3, exact; at 100 MHz
  10 and 5. Neither clock has closure evidence (row 4: 50 MHz target, 100 MHz
  stretch, no result above 50). The clock the area/clock analysis supports is
  **50 MHz**; a 60 MHz clock is a **new proposal** and also depends on what
  clock the demo board can supply, which this record has not verified.
- **Payload supply.** Octets come from `ui_in` at one per 40 cycles from an
  external source, or from program-memory words through DR 0012's `PM_DATA`
  access (2-cycle reads; the loop shape for that is not counted here). There
  is no data memory. So the chip's claim is line coding, CRC and timing, not
  frame buffering.
- **Link-test pulses, TP_IDL, differential drive** are external or firmware
  and are not counted; link-pulse timing is a firmware timer
  (≈ 16 ms is 800,000 cycles at 50 MHz, a `WAIT` loop). Unverified.

### 10BASE-T, receive, 50 MHz, with P4

P4 in Manchester mode on the receiver's single-ended output, period 5, the
mid-bit edge restarts the phase counter and its direction is the bit.
DR 0011's 3-cycle poll loop (60 ns) does not observe every half-bit, and the
fixed-cycle sampling receiver it describes was not scheduled; hardware
resolves the edge to one
clock (20 ns, ±0.5 cycle from the synchronizer) against a 100 ns bit cell, and
re-locks every bit so oscillator error between sender and receiver (DR 0011's
2.44 bit drift over a maximal frame) is irrelevant. Firmware per octet is the
USB-receive loop above: about 18 cycles of work in a 40-cycle octet, i.e. 22
cycles of slack, with a one-byte holding register so the firmware may be up to
that late. The frame is streamed out, the CRC-32 residual is compared at the
end via `CRC_NEXT`. Whether the 10 ns synchronizer quantization is within the
receiver's required jitter tolerance is **unverified** ("confirm"), and the
receiver front end (comparator, squelch, link detect) is external.

### Result against the baseline

| | Not in the baseline schedule (DR 0011) | With primitives |
|---|---|---|
| USB TX | CRC16 not included; all four registers in use, so byte position is 8 slot copies (168 words, no CRC); a complete schedule with CRC16 not demonstrated, not ruled out | fits: 11 of 33 cycles, ~80–100 words; CRC in P1, stuffing/NRZI in P2 |
| USB RX | CRC check and packet storage not included; per-bit decode is an estimate; 60 ns poll | fits with P4: edge to 20 ns, ~18 of 264 cycles per byte; no packet storage |
| 10BASE-T TX | FCS not included (supplied precomputed); pin sharing; all four registers and all but 5 of 40 slots per octet in use | fits **only with P3** (not admitted): 3 of 5 slots per bit, CRC-32 and FCS from P1; skew ±10 ns unverified |
| 10BASE-T RX | 60 ns poll > 50 ns half-bit; sampling receiver not scheduled; no CRC-32 check or frame storage | fits with P4: ~18 of 40 cycles per octet; no frame storage |

## Verdicts

Per protocol, with what would reopen it. "Admit" means admit as a stretch
target to be evidenced by committed firmware plus an independent reference
model under cocotb (`CLAUDE.md`), not that anything is met.

| Protocol | Verdict | Primitives | Claim limited to |
|---|---|---|---|
| Low-speed USB | **Admit TX-only** | P1, P2 | A packet transmitter: SYNC, PID, data, CRC5/CRC16, NRZI, stuffing, EOP, graded by an independent bit-level USB decoder with the 33-cycle timing checked. **Not** "a USB device": enumeration needs receive. RX deferred |
| 10BASE-T TX | **Defer** (conditional) | P1, P3 | until P3, or a replacement for it, passes the admission test (reopening 2). If reopened, the claim would be: a frame transmitter (preamble, SFD, payload, CRC-32 FCS, Manchester at 10 Mbit/s) graded by an independent Manchester/CRC-32 decoder (zlib CRC-32 is an independent oracle), edge rate and jitter unverified |
| Low-speed USB RX | **Defer** | P4 | until P4 is admitted (below) |
| 10BASE-T RX | **Defer** | P4 | until P4 is admitted (below) |

**Primitives.** Admit P1 and P2 as proposed control-space entries: they are
cheap (about 4,600 µm², about 12 % of the existing cells-plus-macro floor), the
admission test holds with the widest protocol reach, and they carry the "CRC
and line coding" half of the organizers' wording.

**P3 is not admitted.** It serves one protocol that needs it (10BASE-T
transmit); the other Manchester links considered either belong to the same
family or are slow enough for plain firmware (P3, table). It fails test 3.
This record does **not** make an exception for it. Test 3 is the rule that
keeps a primitive from being a single-protocol peripheral in parts. A
Manchester stage whose only real user is 10BASE-T TX is that peripheral's
line coder. Waiving the test for the one primitive a stretch verdict
depends on would bend the record's own rule to fit the result it wants.
So **10BASE-T TX is deferred**, conditionally. Its cycle budget (the
schedule above) is kept so a later record does not have to recount it.
Without P3, the baseline's pin sharing and missing mid-bit slot remain.
Whether P1 alone, with firmware `OUT`s for both half-bits, fits in 5 cycles
per bit was **not counted** here and is not claimed.

**P4 is not admitted
by this record**: it is the largest verification surface (a free-running
asynchronous block that the formal timing property and the
gate-level regression must cover), the closest to a peripheral, and the
organizers' third item ("clock recovery") is the one it buys. It is deferred
as a **separate proposal**, not rejected, because it is the only primitive that
turns the TX-only verdict into a protocol.

Why TX-only is a real result and not a hedge: with P1 and P2 the chip does
the line coding and CRC for low-speed USB and holds exact bit timing. That
is two of the organizers' three named items, and the transmit claim is
fully gradable against independent models. It is also the half that fits
the 2027-01-18 deadline discipline. For 10BASE-T this record has no
admitted result, only a costed path (P1 plus an admissible output-timing
primitive).

**Reopening conditions.**

1. **P4 (and so both RX verdicts).** Reopen when a follow-up record admits P4
   with (a) an admission-test review that no field names a protocol,
   (b) a plan to extend the formal `no_data_dependent_latency` property to a
   free-running block (the property constrains instruction latency; the block
   must be shown not to alter it), (c) the area band re-read from a LibreLane
   run, and (d) the pad/input-synchronizer assumption re-checked after #133.
2. **10BASE-T TX (P3).** Reopen when a follow-up record does one of these.
   (a) It shows a third unrelated protocol that *needs* P3's interface,
   under test 3 as worded here. (b) It replaces P3 with a more general
   output-timing primitive, such as a scheduled masked-pin write at a fixed
   cycle offset, that passes test 3 on its own merits. Any protocol named
   to make that case is then excluded from row 13, as above. (c) It argues
   for an exception to test 3 in the open, with reasons, and is ratified as
   such. That record is not this one. Whichever path is taken, the half-bit
   skew remains open: the Clause 14 jitter limit (confirm) may not tolerate
   40/60 ns, and the pad may not toggle at 10 MHz (#133). If either holds,
   the remedies are a clock giving an integer half-bit (60 or 100 MHz,
   needing row 4 evidence at that clock), an external retimer, or a
   negative-edge output flop.
3. **Ratification.** None of this exists until DR 0012 and DR 0001 are
   ratified (#44) and the control indices are frozen. If they are not, no
   verdict above takes effect and both protocols stay as row 2 reads today:
   stretch targets with nothing numeric bound and the entry condition unmet.
   DR 0011 gives no verdict to fall back on.
4. **Area / runtime.** If a LibreLane run of the design with P1 and P2 shows
   the 6-hour Actions limit (#134) or the density target is at risk, drop
   P1's byte op first. A reopened P3 (condition 2) is then the first
   candidate to drop, because it has the smallest protocol reach.
5. **A drop-out condition on USB TX.** If the USB-LS TX claim, once its
   independent decoder exists, would need receive to be meaningful to a judge,
   the record that admits P4 should be written; this record does not pre-empt
   that.

## Interaction with other records and rows

- **DR 0001 and the ISA freeze.** The primitives are an ISA change (new
  control indices), so they touch DR 0001, which is unratified (#44), and
  DR 0012, also unratified. They must exist before the submission ISA freeze.
  **Row 13's rule** ("chosen after the ISA is frozen, so it cannot shape the
  ISA") is respected by excluding every protocol named in this record's
  tables from row 13: they were considered here, whether or not the
  primitive they were weighed against was admitted. That includes
  Manchester/IR, which row 13 currently lists as a candidate (weighed
  against P3 and found not to need it); the row 13 choice must come from
  outside this record (for example WS2812-style single-wire timing, or a
  target-role protocol).
- **Row 3.** Every primitive's latency is fixed by its index. P4 is
  asynchronous hardware; row 3 constrains instruction latency, not hardware
  concurrency, but this needs the formal property to say so (reopening 1b).
- **Row 2.** Its text is not changed. The entry condition ("DR 0001's ISA can
  show a cycle budget") is met for TX by the schedules above **if** the
  primitives are admitted; row 2 stays "Stretch, nothing numeric bound" until
  the ratifying act, and the dated note in the target spec points here.
- **Row 4.** No value changes. 50 MHz is the working clock; 60 and 100 MHz are
  sensitivity only.
- **Row 7 / DR 0014.** About +4,600 µm² (P1, P2: admitted), +5,500 (with a
  reopened P3) or +8,800 (all four) in a 2×2 core; tile recommendation
  unchanged.
- **`CLAUDE.md`.** "The ISA is the product" is honoured: nothing here frames a
  USB or Ethernet packet; the firmware does, and the same primitives are
  configuration-only for other protocols. A hardware USB or Ethernet block is
  still out of scope.

## Consequences

- If ratified, DR 0012's index range `0x10`–`0x1F` is allocated to P1
  (`CRC_*`) and P2 (`LINE_*`); P3 (`MAN_*`, or its replacement) and P4
  (`SAMP_*`) are held pending their own records. Indices are not assigned
  here; the 16-index range is enough for P1–P3 (about 10 used) and not for
  P4 as well, which is another reason P4 needs its own record (it may need a
  second block of indices, a DR 0012 amendment).
- If ratified and built, each primitive needs: a bench against an independent
  oracle (for CRC, zlib/known test vectors; for NRZI/stuffing and Manchester,
  an independent decoder), extension of `no_data_dependent_latency` to the new
  indices, and a re-run of the LibreLane corner timing (row 4) with the new
  logic present. `spec/verification-plan.md` §6 is updated to point here.
- No RTL, firmware or reference model is added by this record. Per deadline
  discipline, USB-TX firmware is scheduled only after DR 0012 and P1/P2
  exist; 10BASE-T-TX firmware is not scheduled until reopening condition 2
  is met.
- If no primitive is ever built, both protocols stay as row 2 reads today
  (stretch targets, nothing numeric bound, entry condition unmet). DR 0011's
  baseline stands either way; it carries no verdict.

**Dated note, 2026-10-10 (issue #208): index map, and the measured area that
replaces the estimates.** This note records what was built from this Proposed
record. It does not ratify, reopen or relax anything: no Status line changes,
the admission test and the verdicts are as written, and the interface is
unchanged.

- **Index map** (DR 0012's range, which keeps `0x1A`-`0x1F` unassigned):
  P1 is `CRC_CFG 0x10`, `CRC_POLY 0x11`, `CRC_STATE 0x12`, `CRC_BIT 0x13`,
  `CRC_BYTE 0x14` (`WCTL`, 9 cycles: 1 + 8 stall, fixed), `CRC_NEXT 0x15`
  (`RCTL`). P2 is `LINE_CFG 0x16`, `LINE_PUT 0x17`, `LINE_OUT 0x18`,
  `LINE_STUF 0x19`. DR 0012 carries the same table, with the field layouts, as
  a dated note under its register table. Every index but `CRC_BYTE` takes
  1 cycle. The flags are untouched.
- **Area, measured, against this record's estimates.** The estimates were
  P1 about 3,800 um^2 (band 3,000-6,000), P2 about 800 um^2 (band 500-1,200),
  and about 4,600 um^2 together (band 3,500-7,200). Built, the two together
  cost, flow by flow and never mixed:
  - **klt/Yosys** (cell area, no placement): top 1,377 instances, 21,331.03
    um^2 -> 2,161 instances, 32,178.72 um^2, **+10,847.69 um^2**
    (sequential +4,213.04 um^2). That is 2.4 times the estimate and 1.5 times
    the top of its band.
  - **LibreLane** (placed standard-cell area, gds runs 38051226323 on `main`
    and 38055685598 on the branch): 28,255.7 -> 41,827.4 um^2, **+13,571.7
    um^2**. This figure also includes the drive buffers that the SRAM
    macro's inputs needed in this flow (the branch's build had max-slew
    violations on them without the buffers; a LibreLane-only fix, as in
    issues #173, #199 and #201). Placed
    utilization of the unchanged 126,685 um^2 core rose from 44.5 % to
    55.2 %. DR 0014's 60 % target is 76,011 um^2 of cells plus macro, and the
    design is now 69,955 um^2, 6,056 um^2 under it.
  - The estimate assumed the design-average cell area for a flop. A reset
    flop in this library is about 49 um^2 and the library has no enable flop,
    so each byte-written register carries its own hold mux: P1's two 32-bit
    registers (`CRC_POLY`, `CRC_STATE`) cost about 2,400 um^2 each, and they
    were the estimate's largest line. Trimming readbacks and masks reaches at
    best +9,900 um^2 (klt/Yosys), still outside the band.
  - The two flows disagree on the absolute figures, as they did for DR 0012
    and DR 0013 (different cells chosen, placement buffers, timing repair). The
    disagreement is recorded, not resolved; each number above is quoted with
    its flow.
- **Reopening condition 4, evaluated.** The drop triggers are a placed density
  above the 60 % target, or a `gds` run near the 6-hour Actions limit. Neither
  fired: 55.2 % (below 60 %) and a `gds` job of about 19 minutes. Setup and hold have
  zero violations at all three corners the flow emits. So the full interface
  is kept, including `CRC_BYTE`, which condition 4 names first for dropping.
  The estimate being outside its band is a finding about the estimate, not a
  trigger. If a smaller P1 is preferred (no readback, a fixed width, or no byte
  op), that is a follow-up record, and it is reversible.- **Evidence.** `verification/test_primitives.py` (independent oracles: the
  CRC RevEng catalogue check values for CRC-5/USB, CRC-16/USB, CRC-32,
  CRC-8/MAXIM, CRC-15/CAN and CRC-16/XMODEM, a carry-less-multiplication LFSR
  oracle and the PRBS7 period, and an independent NRZI/de-stuffing receiver for
  USB N = 6, HDLC N = 5 and CAN 5 equal bits), `verification/primitives_mutants.py`
  (14 single-defect copies, each caught by a named test), the extended
  `no_data_dependent_latency` and `pin_write_latency` properties, the extended
  ISA reference model and lockstep bench, and the gate-level run. The records
  are under `verification/records/` (`primitives`, `no-data-dependent-latency`,
  `pin-write-latency`, `isa-lockstep`, `firmware-gate-level`,
  `librelane-corner-timing`, `synthesis-baseline`).

## Alternatives considered

1. **A plain defer, with DR 0011's baseline as the only record.** Rejected
   as the only outcome: it forgoes
   credit the organizers' wording names, and the area exists (DR 0014).
2. **A USB or Ethernet MAC/PHY block.** Rejected by `CLAUDE.md`; this record
   shows the ISA route.
3. **More registers or a scratch data memory instead of primitives.** It
   would fix state capacity (the open part DR 0011's USB baseline names) but
   not the
   per-bit instruction cost of CRC-32 at 5 cycles per bit, and it does nothing
   for clock recovery. DR 0012's `PM_DATA` access is a partial scratch memory
   (2-cycle reads, program words) and may be used for payload; it is not
   relied on.
4. **A byte-unrolled CRC step.** One cycle per byte instead of 9, at several
   times the logic (not sized). Not needed: both protocols have more than 9
   cycles per octet.
5. **Admit P4 now.** Rejected for scope and verification risk, deferred as its
   own proposal (Verdicts).
