# 0011: Stretch Protocols — Current-ISA Baseline Schedules for Low-speed USB and 10BASE-T

Status: **Proposed baseline 2026-10-09**: per-protocol TX/RX instruction
schedules for USB-LS and 10BASE-T on the CURRENT ISA (DR 0001 as built), pure
firmware, with assumptions. It is not ratified. Ratification runs through the
program's two-key (`RATIFY-KEY`) mechanism (`spec/README.md`, "How
ratification works here"; DR [`0004`](0004-target-spec-ratification.md) and
[`0006`](0006-two-key-ratification-never-ran.md)), which has never run in this
repository, so this record is a proposal like the other decision records. It
edits no target-spec value, relaxes nothing ratified or proposed, admits
nothing and defers nothing.
Date: 2026-10-09
Issue: #109

**Numbering note.** PR #128 has held 0011 since 2026-10-09. DRs 0012–0015
were numbered around it; 0009 is unused.

**Scope (rescoped 2026-10-09).** This record is a **baseline only**. It
writes down what a pure-firmware implementation on today's ISA looks like,
cycle by cycle, for the two stretch protocols of `spec/target-spec.md` row 2,
and lists what those schedules leave out. It reaches no conclusion about
whether either protocol can or cannot be built, on this ISA or any other. An
earlier draft of this record (PR #128 up to commit `0f085b5`) carried a
"defer both" verdict, reopening conditions and statements that some parts
were impossible. Review found those statements went further than the
schedules show, and they are withdrawn.

## Verdict: see DR 0015

This record gives no verdict. See DR
[`0015`](0015-stretch-protocols-with-neutral-primitives.md), which evaluates
the same protocols with protocol-neutral primitives and supersedes any
verdict here. DR 0015 quotes the schedules below as its baseline.

## What the baseline schedules show

Each row is the one schedule written out below, not a bound on every
possible schedule.

| Protocol | Transmit, as scheduled here | Receive, as scheduled here |
|---|---|---|
| Low-speed USB (1.5 Mbit/s) | Uniform 33-cycle bit. NRZI + bit stuffing is a full schedule: 10 cycles to the `OUT`, 21 words per bit copy × 8 copies = 168 of 256 words. CRC16 is **not included**; no schedule that adds it was produced. | Poll loop of 3 cycles (60 ns) against a ±8.33-cycle window. Per-bit decode is an estimate only. No CRC check and no packet storage are included. |
| 10BASE-T (10 Mbit/s) | Raw Manchester serializer at 5 cycles/bit, 40-cycle octet loop, 5 spare slots per octet. Half-bit is 2.5 cycles, so the mid-bit edge is at 40/60 ns (±10 ns). FCS (CRC-32) is **not included**; no schedule that adds it was produced. | Poll loop of 3 cycles (60 ns) against a 50 ns half-bit. A fixed-cycle sampling receiver is described but not scheduled. |

## Method and assumptions

- **Baseline** is the ISA as implemented (`rtl/protocol_core.v`, DR 0001 as
  amended by DR 0005), not a claim that it is frozen. Facts used: every
  instruction is 1 cycle; `WAIT n` is `n+1` cycles; `BZ`/`BNZ`/`JMP` cost 1
  cycle taken or not (DR 0005: next address is combinational, no branch
  bubble); 4 registers `R0`–`R3`; `LDI` is the only way to get a constant
  (no immediate ALU forms), so constants cost a slot and a register; `AND`,
  `OR`, `XOR`, `ADD`, `SUB` set `Z`; `SHF` sets only `C`, which **no
  instruction reads** (`flag_c` is write-only in `rtl/protocol_core.v`); no data memory, stack, call/return or indirect
  branch; `OUT` writes the whole 8-bit port, so a protocol pin shares the
  port with 7 others; `uio_oe` is fixed at synthesis (DR 0001
  "Consequences", DR 0008).
- **Clock.** 50 MHz (T = 20 ns) is the row 4 *proposed target*. It is not
  demonstrated closure for all corners: row 4 records closure at 3 of the 6
  declared corners on the LibreLane flow and no klt-flow result. Every
  count below is conditional on that target. 100 MHz (T = 10 ns) appears
  only as sensitivity analysis. No synthesis or timing number is introduced
  here.
- **Arithmetic only.** No RTL, simulation or firmware was run. The schedules
  below are instruction-level and were counted by hand from the ISA; they are
  not assembled or simulated programs, and they are not evidence of protocol
  conformance. They are labelled "schedule" where every cycle is accounted and
  "estimate" where it is not.
- **One allocation each, not a search.** Each schedule uses one register
  allocation and one program layout. Other allocations (packed state, register
  reuse, shared code, a different pin map) were **not evaluated**. Where a
  function is missing from a schedule, the finding is "not included here, no
  fitting schedule demonstrated". It is never a claim that no schedule fits.
- **Sources.** USB: *Universal Serial Bus Specification Revision 2.0* (USB
  2.0 carries the low-speed signalling of USB 1.1 forward; the section
  numbers below were checked against the 2024-09-27 USB-IF release text,
  except the Table 7-10 source-jitter figures, which are marked "confirm").
  10BASE-T: IEEE 802.3 (Clauses 3, 4, 7, 14). **The IEEE text is paywalled
  and was not retrievable here, so the 802.3 citations are clause-level from
  memory; sub-clause numbers and the jitter/rate limits marked "confirm"
  must be checked against the standard at review.** Every count that rests
  on a "confirm" figure says so.
- **Not counted in the digital budget (not evaluated, not ignored).** Both
  protocols need analog or level-translation parts outside the digital
  core: USB low-speed signalling levels, the pull-up that identifies a
  low-speed device (USB 2.0 §7.1.5), and a transceiver; 10BASE-T needs
  differential drive, magnetics and link-test pulses (Clause 14). The
  analysis assumes an external part turns a pin-level Manchester or J/K/SE0
  stream into the line signal. Pad speed at 10 MHz toggle rates is not
  characterized in this repository and is not claimed.

## Low-speed USB

### Rate, quantization, jitter (USB 2.0 §7.1.11, §7.1.13.1.1, Table 7-10, §7.1.15.1)

- Nominal 1.5 Mbit/s, bit time 666.67 ns = **33.333 cycles** at 50 MHz.
  §7.1.11: low-speed rate 1.50 Mbit/s **±1.5 %** (15,000 ppm) when
  transmitting.
- The bit period must be an integer number of cycles. 33 cycles is
  50/33 = 1.5152 Mbit/s, +1.01 %, inside ±1.5 %. 34 cycles is −1.96 % and 32
  is +4.2 %, both outside. A 33/33/34 repeating pattern has the exact average
  but each edge lands up to ±0.33 cycle (±6.7 ns) off the ideal grid, so two
  edges can differ by up to 13.3 ns. Jitter does **not** exclude that
  pattern (see the next bullet). **A uniform 33-cycle bit is still chosen**,
  for state, not timing: the 33/33/34 phase is a third counter, and in the
  allocation below all four registers are already in use (see "Byte
  position"), so it would go into the program counter (3× the slot
  copies). The uniform bit has zero
  data-dependent jitter by construction, and its price is 1.01 % of the
  1.5 % rate budget. The remaining 0.49 % (4,900 ppm) is all the 50 MHz
  clock source may drift or be inaccurate by. The repository does not yet
  state a clock-source accuracy, so this is an assumption to confirm.
- Source jitter limits (USB 2.0 Table 7-10, low-speed data timing; figures
  read from memory of the table, **confirm**). Each limit includes frequency
  tolerance.
  - **Downstream-facing port** (a host or hub transmitting to a low-speed
    device): T<sub>DDJ1</sub> ±25 ns to the next transition (1.25 cycles)
    and T<sub>DDJ2</sub> ±14 ns for paired transitions (0.7 cycle). An
    earlier draft of this record gave ±10 ns paired. That figure does not
    match the table and is withdrawn. Against ±14 ns, the 33/33/34 pattern's
    13.3 ns fits, but only just.
  - **Upstream-facing port**: T<sub>UDJ1</sub> ±95 ns and T<sub>UDJ2</sub>
    ±150 ns. A low-speed *device* transmits upstream, so these are the
    limits that apply if this core acts as a low-speed device. They are far
    looser than either 33-cycle scheme needs.
  - No count in this record rests on these figures.
- Receivers must decode edges within ±a quarter bit cell of nominal
  (§7.1.15.1) = ±166.7 ns = **±8.33 cycles**; Table 7-5 budgets the host
  receiver 164 ns for the next-transition case.

### Transmit schedule

Encoding rules: NRZI, a `0` toggles the line and a `1` holds it (§7.1.8);
a `0` is inserted after every six consecutive `1`s, starting with the final
`1` of SYNC (§7.1.9, Figure 7-34); SYNC is KJKJKJKK (§7.1.10); PID is a
4-bit type plus its complement (§8.3.1); CRCs are computed before stuffing
(§8.3.5).

Register roles: `R0` data byte (LSB first, `SHF right`), `R1` line pin
pattern (the J/K pair, one `OUT` sets D+ and D− atomically), `R2` "ones left
before a stuff" (reset value 6), `R3` temporary. One slot is one bit time on
the wire: `s0` is the first cycle of the slot, the `OUT` is at `s9`, and every
path is exactly 33 cycles.

The listing is copy `k` (`k` = 0..7) of the slot; why there are 8 copies is
under "Byte position" below. A data slot consumes bit `k` and falls
through to copy `k+1`. A stuff slot consumes no data bit, so it must
return to the **same** copy's `s0_k`. It has its own `OUT` and exit for
that reason, and it cannot share `emit_k`, which falls through to copy
`k+1`.

```
s0_k:
s0   AND R2,R2        ; Z = (ones_left == 0)
s1   BZ  stuff_k
; data bit
s2   LDI R3,1
s3   AND R3,R0        ; Z = (bit == 0)
s4   SHF R0,right     ; C only; Z kept from s3
s5   BZ  zero_bit_k
s6   LDI R3,1         ; bit == 1: no toggle
s7   SUB R2,R3        ; ones_left--
s8   JMP emit_k
zero_bit_k:           ; lands at s6
s6   LDI R3,3
s7   XOR R1,R3        ; toggle J<->K
s8   LDI R2,6         ; fall through to emit_k
emit_k:
s9   OUT uo_out,R1    ; the same cycle in every path
s10  WAIT 22          ; 23 cycles: s10..s32, then falls through to s0_(k+1)
; stuff path, entered at s2 from the BZ at s1
stuff_k:
s2   LDI R3,3
s3   XOR R1,R3        ; stuffed 0: toggle J<->K
s4   LDI R2,6
s5   WAIT 3           ; 4 cycles: s5..s8
s9   OUT uo_out,R1    ; same cycle as emit_k
s10  WAIT 21          ; 22 cycles: s10..s31
s32  JMP s0_k         ; data bit NOT consumed: back to the same copy
```

All three paths reach `OUT` at `s9` and the slot closes at `s32`. The data
paths take 10 + 23 (`WAIT 22`) = 33 cycles. The stuff path takes
10 + 22 (`WAIT 21`) + 1 (`JMP`) = 33 cycles, with the `JMP` filling the
cycle that the shorter `WAIT` frees. So the `OUT` repeats every 33 cycles
with no data-dependent variation. Worst-case stuffing (a data run of
`0xFF…`) makes every seventh slot a stuff slot: the wire carries 7 slots
per 6 data bits and every slot is still 33 cycles, so the schedule holds
under the worst case. A stuff slot leaves `R0` and the copy index
unchanged, so the next slot sends the bit that was pending. Instruction
use is 9 of 33 cycles on the longest path (about 27 %).

What this schedule does **not** include:

- **Byte position.** In this allocation all four registers are live, so the
  bit position within the byte is encoded in the program counter, i.e. 8
  copies of the slot. Words per copy: `s0`–`s1` 2, common data path 4,
  one-bit path 3, zero-bit path 3, `emit` (`OUT`+`WAIT`) 2, and stuff path 7
  (`LDI`, `XOR`, `LDI`, `WAIT`, `OUT`, `WAIT`, `JMP`). That totals **21**, so
  8 copies take **168 of 256 words** before SYNC/PID/EOP code and the
  per-copy byte reload. (An earlier draft counted 19 words and 152 in
  total, because its stuff path rejoined the shared `emit` and so dropped
  a data bit. Review estimated about 22 words and 176 in total for the
  corrected path. The listing above needs 21, because one `WAIT 3`
  replaces the old `WAIT 2` + `JMP emit` pair.) A packed allocation, for
  example the 3-bit ones counter and the 1-bit J/K state sharing a
  register, might free a register for a byte counter and remove the 8
  copies. That was **not evaluated**. In this schedule the packet length
  has no counter either; it would come from an external end-of-packet pin
  read with `IN` and `BZ`/`BNZ`.
- **CRC.** CRC16 (§8.3.5.2, G(X) = X¹⁶+X¹⁵+X²+1, seed all ones, shift
  left, residual 1000000000001101B) is not in the schedule. A bitwise
  update holds a 16-bit remainder (two registers in the obvious
  allocation). The 16-bit left shift crosses the register boundary, and
  since no instruction reads `C`, the carry is extracted with a mask and
  `AND`/branch per bit. Estimate, not a schedule: about 14–16 instructions
  per data bit (feedback bit 3, cross-byte bit 2, two `SHF`, conditional
  `OR`, conditional polynomial `XOR`s each needing an `LDI` constant).
  Added to the 9–10 above that is about 25 of 33 cycles, so the cycle
  count leaves room. The register allocation is the open part: data +
  remainder (2) + temporary uses all four registers in the obvious
  allocation, which leaves the ones counter and line state without a
  register. Moving both into the program counter unpacked would be
  7 × 2 × 8 = 112 copies of the bit code, far more than 256 words, so
  that particular layout does not fit. **No complete schedule with CRC16
  was demonstrated. Packed state, register reuse and shared code were not
  analysed, so this is not a lower bound.** CRC5 (§8.3.5.1, X⁵+X²+1, 11
  field bits) has a remainder that fits one register; it was not scheduled
  either.
- **Constant packets.** ACK/NAK/STALL are fixed bit strings and fixed tokens
  can carry a precomputed CRC5; a payload with a precomputed CRC16 is fixed
  too. Their NRZI and stuffing are static, so the waveform is a straight
  list of `OUT` + `WAIT 31` (32 cycles) pairs, 8 SYNC + 8 PID + EOP (2 bit
  times SE0 then J, §7.1.13.2.1). That is a canned waveform replay. Whether
  it counts as a protocol claim is not decided here.
- **Bus turnaround.** A device transmits and receives on the same D+/D− pair.
  `uio_oe` is fixed at synthesis in the ISA as built, so this baseline
  assumes dedicated input pins and output pins with an external transceiver.
  DR 0012 proposes runtime pin direction; it is not part of this baseline.

### Receive

- Poll loop used here (`R3` is a mask register):
  `IN R0,ui_in` / `AND R0,R3` / `BZ poll` = **3 cycles = 60 ns** per
  iteration. `IN` takes a whole byte and does not set `Z`, so this loop
  needs an ALU op before the branch. No shorter loop was found; none was
  searched for systematically.
- Edge-time uncertainty is therefore one poll period, 60 ns (±1.5 cycles
  once a centring offset is applied). Against the §7.1.15.1 window of ±166.7 ns, plus
  Table 7-5's 152 ns jitter specification, the sample point keeps
  333 − 152 − 30 ≈ 150 ns of margin to the bit edges per bit. **So the
  edge-timing arithmetic alone fits** at 50 MHz. The ±1.5 % rate mismatch over a worst-case
  7-bit run without a transition is 10 ns/bit × 7 = 70 ns (Table 7-5), also
  inside the window, provided the sample clock re-locks on every edge.
- Per-bit receive work (NRZI decode by `XOR` of the previous level, un-stuff
  count, shift into the byte, SE0 test of both lines for EOP) is about 10
  instructions plus the interleaved polls: estimate, not a verified schedule.
- Not included, as for transmit: the receive CRC16 residual check, and an
  allocation that holds stuffing, NRZI previous-level and byte state
  together. No such allocation was demonstrated and none was ruled out.
  There is no data memory, so in this baseline decoded bytes are streamed
  out on pins as they complete. §8.3.5 requires a receiver to reject
  packets with a bad CRC, so a receiver without the check does not meet
  that clause.

### What the USB baseline establishes

On the transmit schedule, instructions use 10 of 33 cycles up to the `OUT`,
so the bit period offers about 3.3× the cycles of the stuffing/NRZI path. The open
part is state: 4 registers, no instruction that reads `C`, no data memory,
256 words. A complete low-speed USB schedule with CRC16 on the current ISA
was **not demonstrated and not ruled out**.

**Assumptions:** 50 MHz proposed target; uniform 33-cycle bit (+1.01 %);
external transceiver and level handling; clock-source accuracy within 4,900
ppm; the §7.1.15.1 and §7.1.13.1.1 figures as read in the USB 2.0 text;
the Table 7-10 jitter figures marked "confirm" (no count rests on them).

**Sensitivity at 100 MHz (not a target).** The bit is 66.67 cycles; 67
cycles is −0.50 %, which spends a third of the rate budget instead of two
thirds, and the slot has about twice the cycles (67 vs 33; 57 vs 23 left
after the 10-cycle stuffing/NRZI path). The register and word counts are
unchanged. 100 MHz is a row 4 stretch with no closure evidence.

## 10BASE-T Ethernet

### Rate and frame (IEEE 802.3 Clauses 3, 4, 7, 14 — confirm sub-clauses)

- 10 Mbit/s Manchester, bit cell 100 ns = **5 cycles** at 50 MHz; half-bit
  50 ns = **2.5 cycles**, which is not an integer. Every output edge falls on a
  20 ns clock grid, so the mid-bit transition is either 2 or 3 cycles after the
  bit start: 40/60 ns, i.e. ±10 ns off nominal on every bit. The bit rate is
  exact (50 MHz ÷ 5 = 10.000 Mbit/s); the standard requires 10 Mbit/s with a
  tight tolerance on the order of ±0.01 % (Clause 7/14, confirm).
- Frame (Clause 3): 7-byte preamble `0x55`, SFD `0xD5` (§3.2.5, §3.2.6),
  octets sent LSB first, FCS = CRC-32 over the frame (§3.2.9). Smallest
  frame 64 bytes + 8 = 72 bytes = 576 bit times = 57.6 µs = 2,880 cycles;
  largest 1518 + 8 = 1526 bytes = 12,208 bit times = 1.2208 ms = 61,040
  cycles. Inter-frame gap 96 bit times = 9.6 µs = 480 cycles (Clause 4,
  §4.4.2.1, confirm).
- Transmit output jitter limits are in Clause 14.3.1 (confirm the figure).
  A deterministic ±10 ns mid-bit skew is within one clock cycle of the ideal
  but is, at this scale, not obviously inside a limit measured in a few
  nanoseconds; **this is unverified**.

### Transmit schedule (serializer only)

Registers: `R0` current octet (`SHF right`, LSB first), `R1` its complement
(`~octet`, also shifted right), `R2` the next octet, `R3` constant `0xFF`.
The pin is bit 0 of the port (Manchester level = bit 0 of the written
register), so no `AND` mask is needed: a half-bit level of `b` is `OUT R0`
and of `~b` is `OUT R1`.

```
bit k, 5 cycles (t0..t4), k = 0..6
t0   OUT port,R1      ; first half-bit level = ~b
t1   SHF R1,right
t2   OUT port,R0      ; mid-bit edge, second half-bit level = b
t3   SHF R0,right
t4   (spare)          ; NOP / IN R2 / the loop JMP
bit 7 (replaces the shifts with the octet hand-off)
t0   OUT port,R1
t1   MOV R1,R2
t2   OUT port,R0
t3   XOR R1,R3        ; R1 = ~next octet
t4   MOV R0,R2
```

The octet loop is 8 × 5 = **40 cycles**, and the loop branch costs no
extra cycle because it sits in a spare `t4`. Bit 7's `t4` is taken by
`MOV R0,R2`, so the loop is **rotated**. The loop label sits at the bit-7
block, and the body in program order is: bit 7 of octet n−1, then bits
0–6 of octet n. Bit 6's `t4` is `JMP` back to the bit-7 block, and the
`t4` of one of bits 0–5 is `IN R2,ui_in` (the next octet, needed before
bit 7's `t1`). The first octet enters at the bit-0 block after a
prologue loads `R0`, `R1` and `R2`. The last octet's bit 7 and the loop
exit are outside this schedule. That uses 2 of the 7 `t4` slots of bits
0–6 and leaves **5 spare slots per octet**. The half-bit placement has
no slack. Output edges are at fixed cycles `0, 2, 5, 7, 10, …`, i.e. a 2/3-cycle
half-bit pattern (40 ns/60 ns), the bit cell is exact, and the preamble
(`0x55`, SFD `0xD5`) uses the same structure with `LDI` for the octet.

What this schedule does not include:

- **FCS.** A bitwise CRC-32 holds a 32-bit remainder, which is four
  registers in the obvious allocation, and this serializer already uses
  all four (`R0`–`R3`) and all but 5 of its 40 slots per octet. A bitwise
  update takes more than 5 instructions per bit by the USB estimate above.
  **No schedule that computes the FCS alongside this serializer was
  demonstrated, and other allocations were not analysed.** In this baseline the FCS is supplied precomputed from
  outside.
- **Pin sharing.** `OUT` writes 8 pins; bits 1–7 of the port toggle with
  the data. This schedule assumes a port whose other pins are not used.
- **Octet supply.** With all four registers in use, octets come from
  `ui_in` at 1 octet per 40 cycles from an external source, or from `LDI`
  constants in program memory (one word per octet, 72 words for a minimum
  frame; the ISA has no call/return, so this layout does not share one bit
  loop across octets).

### Receive

- A Manchester receiver must find the mid-bit transitions. The poll loop
  `IN` / `AND` / `BZ` is 3 cycles = **60 ns** per iteration, longer than
  the 50 ns half-bit. So **this poll loop** does not observe every
  half-bit level, and its edge-time uncertainty (60 ns) is larger than the
  half-bit.
- A *sampling* receiver (unconditional `IN` at fixed cycles instead of
  branch-polling) can take 1 sample per bit, with an accumulate step
  (`AND`, `SHF`, `OR`: about 4 instructions). Its phase has to track the
  transmitter: a relative frequency error of 2 × 100 ppm (confirm) over
  12,208 bit times drifts 12,208 × 200 ppm = **2.44 bit times**, so a
  maximal frame needs re-locking within the frame. Re-locking with the
  60 ns poll loop above is the only method counted here. **Fixed-cycle
  sampling that compares successive samples to find the edge is another
  candidate; it was not scheduled and its feasibility is unevaluated.**
- CRC-32 check and frame storage (up to 1526 octets) are not included:
  there is no data memory, and no register allocation for the check was
  demonstrated.

### What the 10BASE-T baseline establishes

A raw Manchester serializer fits a 5-cycle bit at 50 MHz with 5 spare slots
per octet, with the mid-bit edge 10 ns off nominal. FCS generation, receive
and the Clause 14 jitter check are **not demonstrated and not ruled out**.

**Assumptions:** 50 MHz proposed target; an external 10BASE-T line
interface (Clause 14 analog, link test, jabber); octets and FCS supplied
externally for transmit; the Clause 7/14 rate and jitter figures marked
"confirm".

**Sensitivity at 100 MHz (not a target).** T = 10 ns: bit = 10 cycles,
half-bit = 5 cycles, so the mid-bit edge is exact and the serializer gets
10 slots per bit (4 for shifts/`OUT`s, 6 spare). The 3-cycle poll is 30 ns
against a 50 ns half-bit. 100 MHz is a row 4 stretch with no
timing-closure evidence.

## Arithmetic table

All values at 50 MHz (T = 20 ns); recomputed twice.

| Quantity | Value |
|---|---|
| USB LS bit time | 666.67 ns = 33.333 cycles; 33 cycles = 660 ns = 1.5152 Mbit/s (+1.01 %) |
| USB ±1.5 % window | 33.333/1.015 to 33.333/0.985 = 32.84 to 33.84 cycles → only 33 is an integer |
| USB quarter bit | 166.7 ns = 8.33 cycles |
| USB TX slot | data: 9 instruction cycles + `OUT` + 23 pad = 33; stuff: 5 + 4 pad + `OUT` + 22 pad + `JMP` = 33 |
| USB TX words | 21 per bit copy × 8 = 168 of 256 (no CRC) |
| USB paired-edge jitter, 33/33/34 pattern | 13.3 ns vs T<sub>DDJ2</sub> ±14 ns downstream / T<sub>UDJ2</sub> ±150 ns upstream (confirm) |
| 10BASE-T bit / half-bit | 100 ns = 5 cycles / 50 ns = 2.5 cycles |
| Min frame (preamble to FCS) | 72 bytes = 576 bits = 57.6 µs = 2,880 cycles |
| Max frame | 1526 bytes = 12,208 bits = 1.2208 ms = 61,040 cycles |
| IFG | 96 bits = 9.6 µs = 480 cycles |
| Poll loop `IN`/`AND`/`BZ` | 3 cycles = 60 ns |
| TX octet loop | 8 × 5 = 40 cycles (rotated: bit 7 of octet n−1, then bits 0–6 of octet n); 7 `t4` slots − `IN` − `JMP` = 5 spare |
| Drift, 200 ppm over 12,208 bits | 2.44 bit times |
| At 100 MHz: USB bit / 10BASE-T bit / poll | 66.67 cycles / 10 cycles / 30 ns |

## Consequences

- `spec/target-spec.md` row 2 is not edited and still commits to no value.
  Its entry condition asks for a cycle budget on DR 0001's ISA. This record
  supplies the current-ISA cycle counts; DR 0015 carries the verdict on what
  that means for the row.
- `README.md`, `spec/README.md` and `spec/gap-to-submission.md` point at
  DR 0015 for the verdict and at this record for the baseline.
- No RTL, firmware or reference model is added by this record.
- If a number here is corrected later, DR 0015's baseline table ("Re-counted
  schedules") quotes it and must be checked in the same change.

## Not evaluated

Listed so a reader does not take silence for a result.

1. Packed-state or register-reuse allocations for USB (ones counter, J/K
   state, byte position, CRC remainder), and shared code in place of the 8
   slot copies.
2. Any complete schedule with CRC5, CRC16 or CRC-32.
3. A fixed-cycle sampling receiver for either protocol.
4. A canned-packet USB subset as a protocol claim.
5. The Clause 14 transmit jitter limit against the 10 ns mid-bit skew, and
   pad behaviour at 10 MHz.
6. Any ISA change. DR 0012 (control space, runtime pin direction) and
   DR 0015 (protocol-neutral primitives) cover those.
