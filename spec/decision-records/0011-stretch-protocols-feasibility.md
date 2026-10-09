# 0011: Stretch Protocols — Low-speed USB and 10BASE-T Against the ISA Cycle Budget

Status: **Proposed 2026-10-09.** It goes to ratification through the program's
two-key (`RATIFY-KEY`) mechanism on the PR that carries it (`spec/README.md`,
"How ratification works here"; DR [`0004`](0004-target-spec-ratification.md)
and [`0006`](0006-two-key-ratification-never-ran.md)). That mechanism has never
run in this repository, so for now this record is a proposal, like DRs
0001–0005, 0007, 0008 and 0010. It edits no target-spec value and relaxes
nothing ratified or proposed; it only discharges `spec/target-spec.md` row 2's
own entry condition ("enters this spec only if DR 0001's ISA can show a cycle
budget for it").
Date: 2026-10-09
Issue: #109

**Numbering note.** Checked 2026-10-09 against `origin/main` (DRs 0001–0008,
0010) and the open PRs: PR #84 reserves 0009; none adds 0011.

## Verdict

| Protocol | Transmit | Receive | Verdict |
|---|---|---|---|
| Low-speed USB (1.5 Mbit/s) | Cycles are **not** the limit (33 cycles/bit; stuffing + NRZI uses ~10). Online CRC16 plus stuffing/NRZI needs more live state than 4 registers and 256 words hold. | Edge timing is representable (3-cycle poll vs a ±8.3-cycle window); CRC check and stuffing state are not. | **Defer** |
| 10BASE-T (10 Mbit/s) | A raw Manchester serializer fits at 5 cycles/bit (no slack in the half-bit placement, 5 spare slots per octet), but the half-bit is 2.5 cycles (mid-bit edge off by 10 ns) and CRC-32 cannot be computed. | The half-bit (50 ns) is shorter than the fastest possible poll loop (60 ns). | **Defer** |

Neither protocol is admitted. Row 2 keeps committing to no value. No firmware
or reference-model follow-up issue is opened, because nothing is admitted; the
reopening conditions below say what would change that.

## Method and assumptions

- **Baseline** is the ISA as implemented (`rtl/protocol_core.v`, DR 0001 as
  amended by DR 0005), not a claim that it is frozen. Facts used: every
  instruction is 1 cycle; `WAIT n` is `n+1` cycles; `BZ`/`BNZ`/`JMP` cost 1
  cycle taken or not (DR 0005: next address is combinational, no branch
  bubble); 4 registers `R0`–`R3`; `LDI` is the only way to get a constant
  (no immediate ALU forms), so constants cost a slot and a register; `AND`,
  `OR`, `XOR`, `ADD`, `SUB` set `Z`; `SHF` sets only `C`, which **no
  instruction can read**; no data memory, stack, call/return or indirect
  branch; `OUT` writes the whole 8-bit port, so a protocol pin shares the
  port with 7 others; `uio_oe` is fixed at synthesis (DR 0001
  "Consequences", DR 0008).
- **Clock.** 50 MHz (T = 20 ns) is the row 4 *proposed target*. It is not
  demonstrated closure for all corners: row 4 records closure at 3 of the 6
  declared corners on the LibreLane flow and no klt-flow result. Every
  verdict below is conditional on that target. 100 MHz (T = 10 ns) appears
  only as sensitivity analysis. No synthesis or timing number is introduced
  here.
- **Arithmetic only.** No RTL, simulation or firmware was run. The schedules
  below are instruction-level and were counted by hand from the ISA; they are
  not assembled or simulated programs, and they are not evidence of protocol
  conformance. They are labelled "schedule" where every cycle is accounted and
  "estimate" where it is not.
- **Sources.** USB: *Universal Serial Bus Specification Revision 2.0* (USB
  2.0 carries the low-speed signalling of USB 1.1 forward; the section
  numbers below were checked against the 2024-09-27 USB-IF release text,
  except the Table 7-10 source-jitter figures, which are marked "confirm").
  10BASE-T: IEEE 802.3 (Clauses 3, 4, 7, 14). **The IEEE text is paywalled
  and was not retrievable here, so the 802.3 citations are clause-level from
  memory; sub-clause numbers and the jitter/rate limits marked "confirm"
  must be checked against the standard at review.** Every verdict that rests
  on a "confirm" figure says so.
- **Out of scope for the digital budget (not evaluated, not ignored).** Both
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
  for state, not timing: the 33/33/34 phase is a third counter that would
  have to live in a register (none is free, see "No byte counter") or in
  the program counter (3× the slot copies). The uniform bit has zero
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
    limits that apply to this core in its only plausible role (no host
    stack fits, see "No CRC"). They are far looser than either 33-cycle
    scheme needs.
  - Neither figure changes the verdict, which rests on state.
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
under "No byte counter" below. A data slot consumes bit `k` and falls
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

What this does **not** hold:

- **No byte counter.** All four registers are live. The bit position within
  the byte has to be encoded in the program counter, i.e. 8 copies of the
  slot. Words per copy: `s0`–`s1` 2, common data path 4, one-bit path 3,
  zero-bit path 3, `emit` (`OUT`+`WAIT`) 2, and stuff path 7 (`LDI`,
  `XOR`, `LDI`, `WAIT`, `OUT`, `WAIT`, `JMP`). That totals **21**, so
  8 copies take **168 of 256 words** before SYNC/PID/EOP code and the
  per-copy byte reload. (An earlier draft counted 19 words and 152 in
  total, because its stuff path rejoined the shared `emit` and so dropped
  a data bit. Review estimated about 22 words and 176 in total for the
  corrected path. The listing above needs 21, because one `WAIT 3`
  replaces the old `WAIT 2` + `JMP emit` pair.) Packet length would have
  to come from an external end-of-packet pin read with `IN` and
  `BZ`/`BNZ`. That deviates from the "firmware owns the protocol" claim,
  and this record names the deviation.
- **No CRC.** CRC16 (§8.3.5.2, G(X) = X¹⁶+X¹⁵+X²+1, seed all ones, shift
  left, residual 1000000000001101B) needs two more registers for the
  remainder. The 16-bit left shift crosses the register boundary, and since
  `C` is unreadable the carry must be extracted with a mask and `AND`/branch
  per bit. Estimate: about 14–16 instructions per data bit (feedback bit 3,
  cross-byte bit 2, two `SHF`, conditional `OR`, conditional polynomial
  `XOR`s each needing an `LDI` constant). Added to the 9–10 above that is
  about 25 of 33 cycles, so cycles still fit, but it does not fit **4
  registers**:
  data + CRC (2) + temporary already use all four, leaving nothing for the
  ones counter or line state, which must move to PC-encoding
  (7 × 2 × 8 = 112 copies of the bit code, an order of magnitude over 256
  words). CRC5 (§8.3.5.1, X⁵+X²+1, 11 field bits) is one register and is
  closer, but a token only matters if a host exists to send it.
- **Constant packets are the exception.** ACK/NAK/STALL are fixed bit strings
  and fixed tokens can carry a precomputed CRC5; a payload with a precomputed
  CRC16 is fixed too. Their NRZI and stuffing are static, so the waveform is a
  straight list of `OUT` + `WAIT 31` (32 cycles) pairs,
  8 SYNC + 8 PID + EOP (2 bit times SE0 then J, §7.1.13.2.1). That fits
  trivially, but it is a canned waveform replay, not a protocol
  implementation, and this record does not admit it as one.
- **Bus turnaround.** A device transmits and receives on the same D+/D− pair.
  `uio_oe` is not runtime-programmable, so the pair must be split into
  dedicated input pins and output pins with an external transceiver.

### Receive

- Poll loop (the fastest possible, `R3` is a mask register):
  `IN R0,ui_in` / `AND R0,R3` / `BZ poll` = **3 cycles = 60 ns** per
  iteration. There is no cheaper branch-on-pin: `IN` takes a whole byte and
  only ALU ops set `Z`.
- Edge-time uncertainty is therefore one poll period, 60 ns (±1.5 cycles
  once a centring offset is applied). Against the §7.1.15.1 window of ±166.7 ns, plus
  Table 7-5's 152 ns jitter specification, the sample point keeps
  333 − 152 − 30 ≈ 150 ns of margin to the bit edges per bit. **So edge
  timing alone fits** at 50 MHz. The ±1.5 % rate mismatch over a worst-case
  7-bit run without a transition is 10 ns/bit × 7 = 70 ns (Table 7-5), also
  inside the window, provided the sample clock re-locks on every edge.
- Per-bit receive work (NRZI decode by `XOR` of the previous level, un-stuff
  count, shift into the byte, SE0 test of both lines for EOP) is about 10
  instructions plus the interleaved polls: estimate, not a verified schedule.
- What fails is the same as transmit: the receive CRC16 residual check and
  stuffing, NRZI previous-level and byte state need more than 4 registers,
  and the packet has nowhere to live (no data memory), so decoded bytes can
  only be streamed out on pins as they complete. Without the CRC check the
  receiver cannot reject corrupted packets as §8.3.5 requires.

### Verdict: defer

Cycles are not the blocker (the bit period offers about 3.7× the instruction
budget of the stuffing/NRZI path). State capacity is: 4 registers, no
carry-readable flag, no data memory, 256 words. A reduced "bit-level, no-CRC"
USB would not be USB.

**Assumptions:** 50 MHz proposed target; uniform 33-cycle bit (+1.01 %);
external transceiver and level handling; clock-source accuracy within 4,900
ppm; the §7.1.15.1 and §7.1.13.1.1 figures as read in the USB 2.0 text;
the Table 7-10 jitter figures marked "confirm" (the verdict does not rest
on them).

**Reopening conditions** (any of these needs its own decision record and ISA
revision, not a firmware edit):

1. An ISA revision with enough state for CRC16 + stuffing + NRZI (a fifth and
   sixth register, or a small scratch memory), or a carry-consuming branch
   and rotate-through-carry that make 16-bit shifts cheap. Arithmetic to
   redo: CRC16 per-bit instruction count against 33 cycles, and program
   words against 256.
2. Runtime `uio_oe` control (the open question already flagged in DR 0001
   "Consequences"), so one D+/D− pair can turn around.
3. A decision record that admits a canned-packet subset (constant handshakes
   and fixed tokens) *and* says why a subset is a meaningful protocol claim.
4. Sensitivity: at **100 MHz** the bit is 66.67 cycles; 67 cycles is −0.50 %,
   which spends a third of the rate budget instead of two thirds, and the
   slot has about twice the cycles for CRC (67 vs 33; 57 vs 23 left after
   the 10-cycle stuffing/NRZI path). That helps the cycle count but not the
   register and word limits, so 100 MHz alone does not reopen this. The 100
   MHz target is a row 4 stretch with no closure evidence.

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
  nanoseconds; **this is unverified**, and is why the transmit side is not
  admitted even though the serializer fits.

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

What it does not hold:

- **FCS.** Bitwise CRC-32 needs a 32-bit remainder = all four registers,
  plus a data bit, a constant polynomial and a feedback test, per bit, in
  5 cycles. Impossible for registers (the remainder alone is 4, with the octet and
  serializer state needing more) and for cycles (the serializer already
  uses all but 5/40 slots and the CRC update needs well over 5
  instructions per bit). The FCS would have to be supplied
  precomputed from outside, which leaves the "protocol" as a serializer plus
  a host.
- **Pin sharing.** `OUT` writes 8 pins; bits 1–7 of the port would toggle
  with the data. The line needs a port whose other pins are not used.
- **Octet supply.** Registers are exhausted, so octets come from `ui_in`
  at 1 octet per 40 cycles from an external source, or from `LDI` constants
  in program memory (one word per octet, 72 words minimum frame — and no
  shared bit loop across octets since there is no call/return).

### Receive

- A Manchester receiver must find the mid-bit transitions. Poll loop
  `IN` / `AND` / `BZ` = 3 cycles = **60 ns** per iteration, longer than the
  50 ns half-bit. A polling receiver therefore cannot see every half-bit
  level, and its edge-time uncertainty (60 ns) exceeds the half-bit window
  itself.
- A *sampling* receiver (unconditional `IN` at fixed cycles instead of
  branch-polling) can run 1 sample per bit, but needs an accumulate step
  (`AND`, `SHF`, `OR`: about 4 instructions) and the phase must be
  re-locked on mid-bit edges to track the transmitter. Relative frequency
  error of 2 × 100 ppm (confirm) over 12,208 bit times drifts
  12,208 × 200 ppm = **2.44 bit times**, so re-locking is required within a
  frame, and the only way to re-lock is the 60 ns poll.
- CRC-32 check and frame storage (up to 1526 octets) hit the same limits as
  transmit: no registers and no data memory.

### Verdict: defer

**Assumptions:** 50 MHz proposed target; an external 10BASE-T line
interface (Clause 14 analog, link test, jabber); octets and FCS supplied
externally for transmit; the Clause 7/14 rate and jitter figures marked
"confirm".

**Reopening conditions:**

1. A clock for which the half-bit is an integer number of cycles. Sensitivity
   at **100 MHz** (T = 10 ns): bit = 10 cycles, half-bit = 5 cycles, so the
   mid-bit edge is exact and the serializer gets 10 slots per bit (4 for
   shifts/OUTs, 6 spare). The 3-cycle poll is 30 ns against a 50 ns half-bit,
   better but not clean. This remains sensitivity analysis: 100 MHz is a
   row 4 stretch with no timing-closure evidence.
2. An ISA or I/O addition that removes polling from the receive path (for
   example a synchronous input sampler or edge timestamp) so a mid-bit edge
   is located to better than one cycle.
3. State for CRC-32 (at least 6 live registers or a scratch memory plus a
   carry-readable shift).
4. Confirmation of the Clause 14 jitter limit against a 10 ns skew, or an
   external retimer that makes that skew irrelevant.

## Corrected arithmetic table

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

- `spec/target-spec.md` row 2 stays "Stretch, nothing numeric bound". This
  record is the evaluation its entry condition asked for; the result is that
  the condition is **not** met, so the row still commits to no value.
- README's "stretch goals" wording is qualified to point here (README says
  deferred, not abandoned). The stretch text is not deleted.
- Per CLAUDE.md's deadline discipline, no RTL, firmware or reference model is
  added for either protocol before 2027-01-18. No fixed-function USB or
  Ethernet block is admitted: the finding is that the ISA, not a missing
  peripheral, is the limit, and the reopening conditions are ISA-side.
- If the human-gated two-key process ratifies a reopening condition, a
  follow-up issue for firmware plus an independent reference model (the
  CLAUDE.md "firmware is evidence" rule) opens then, not now.

## Alternatives considered

1. **Admit USB TX of canned packets.** Rejected here: it satisfies the
   letter of the cycle-budget condition and none of the protocol claim, and it
   spends the same program words the core protocols need. Listed as a
   reopening option (3) instead.
2. **Admit 10BASE-T as a serializer.** Rejected: unverified jitter, no FCS, no
   receive.
3. **Add a fixed-function block.** Out of scope by CLAUDE.md absent a record
   that says why the ISA could not; this record says the ISA could with the
   named additions.
