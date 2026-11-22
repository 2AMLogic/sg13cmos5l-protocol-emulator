#!/usr/bin/env python3
"""Generator for `i2c_fast.asm` / `i2c_std.asm` (issue #374).

The committed `.asm` files under `firmware/asm/` are the evidence (DR 0003);
this script is how the pair is kept in sync, so the two provably share one
instruction stream and differ only in the per-mode WAIT literals (`WAITS`)
and the per-mode prose/annotation blocks (`SLOTS`). It does not run in the
verification flow; the `.hex` / `.cycles.txt` are still produced by asm.py.

    python3 firmware/tools/gen_i2c_pair.py            # (re)write the pair
    python3 firmware/tools/gen_i2c_pair.py --check    # exit 1 on drift

The single-stream contract is structural (issue #554): every instruction
and every `.cyclesec` / `.endcyclesec` directive passes through
`PairBuilder.raw()` / `.wait()` / `.note()` exactly once for both modes, the
12 identical unrolled bit-clock blocks come from one helper loop, and
`SLOTS` is asserted comment-only prose -- so the only way the two programs
can differ is a WAITS literal or an annotation. The sibling `gen_i2c_sr.py`
does the same for the shift-register variants.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "firmware" / "asm"

#: Per-mode WAIT immediates: site -> (fast, std). Every WAIT whose length
#: differs between the modes is named here; the program below emits the
#: instruction once via `PairBuilder.wait(site)`.
WAITS = {
    'start_hold': (56, 196),  # START hold, OUT to the address-byte LDI
    'data_low': (62, 255),    # ordinary bit clock, SCL low phase
    'data_high': (51, 233),   # ordinary bit clock, SCL high phase
    'last_high': (57, 239),   # 8th bit's high phase (ACK prep follows)
    'ack_pre': (28, 119),     # ACK high: SCL rise to the IN sample point
    'ack1_post': (19, 110),   # address ACK: sample to the BNZ
    'ack2_post': (26, 117),   # data ACK: sample to the LDI
    'stop_low': (60, 253),    # pre-STOP SCL low (both STOP paths)
    'stop_setup': (57, 202),  # STOP setup: SCL rise to the SDA rise
    'idle': (255, 255),       # post-STOP bus idle (mode-invariant length)
}

#: Repeated `.endcyclesec` phase annotations: (fast, std).
T_LOW = ('                   ; t_LOW = 65',
         '                   ; t_LOW = 258')
T_HIGH = ('                   ; t_HIGH = 60',
          '                   ; t_HIGH = 242')
T_SU_STO = ('                   ; t_SU;STO = 60',
            '                   ; t_SU;STO = 205')

#: Per-mode prose blocks: (fast, std). Comment-only, asserted by `build()`
#: and by `PairBuilder.slot()` -- the two files' one shared instruction
#: stream lives below, not here.
SLOTS = {
    'title': (
        '; i2c_fast.asm -- bit-banged I2C controller, Fast-mode 400 kHz phase budget\n'
        '; (issue #73, part of #23).',
        '; i2c_std.asm -- bit-banged I2C controller, Standard-mode 100 kHz period\n'
        '; (issue #73, part of #23; 500-cycle clock per issue #125).',
    ),
    'budget': (
        '; cycle-budget sketch -> I2C (controller, Fast-mode 400 kHz)": SCL period\n'
        '; 125 cycles at the target 50 MHz core clock, allocated low = 65 cycles\n'
        '; (the UM10204 Table 10 Fast-mode t_LOW minimum of 1.3 us, to the cycle)\n'
        "; and high = 60 cycles (t_HIGH's minimum is 30 cycles; DR 0001's sketch\n"
        '; allocates the remaining period slack to the high phase). Standard-mode\n'
        '; is the sibling program `i2c_std.asm` -- same instruction stream, larger\n'
        '; phase literals.',
        '; cycle-budget sketch -> I2C" on the Standard-mode side, paced to the\n'
        '; 100 kHz CEILING (issue #125, operator ruling `enforce_500`): every\n'
        '; ordinary data and ACK clock is at least 500 core cycles, i.e. no faster\n'
        "; than UM10204 Table 10's f_SCL maximum of 100 kHz at the target 50 MHz\n"
        '; core clock (nominal, unconfirmed -- the cycle counts are the claim, the\n'
        '; kHz figure is arithmetic at that clock). The allocation is t_LOW = 258\n'
        '; cycles + t_HIGH = 242 cycles = 500; both clear their UM10204 Table 10\n'
        '; minimums (235 / 200 cycles, 4.7 / 4.0 us). The earlier allocation was the\n'
        '; two minimums, 235 + 200 = 435 cycles (~114.9 kHz at 50 MHz), which met\n'
        '; every phase minimum but exceeded the 100 kHz ceiling; this program\n'
        '; supersedes it. 258 is the longest low a single WAIT reaches in these\n'
        '; phases (OUT + WAIT 255 (=256) + OR), so the extra 65 cycles are split\n'
        '; 23 into the low and 42 into the high with NO added instruction words.\n'
        '; Fast-mode is the sibling program `i2c_fast.asm` -- same instruction\n'
        '; stream, smaller phase literals.',
    ),
    'data_clock_table': (
        ';   data-clock low phase   OUT(fall) + WAIT 62 (=63) + OR        = 65\n'
        ';   data-clock high phase  OUT(rise) + SHF + WAIT 55 (=56)\n'
        ';                          + MOV + AND                          = 60\n'
        ";   last bit's high phase  OUT(rise) + WAIT 57 (=58) + MOV       = 60",
        ';   data-clock low phase   OUT(fall) + WAIT 255 (=256) + OR     = 258\n'
        ';   data-clock high phase  OUT(rise) + SHF + WAIT 233 (=234)\n'
        ';                          + MOV + 4x SHF + AND                 = 242\n'
        ";   last bit's high phase  OUT(rise) + WAIT 239 (=240) + MOV    = 242",
    ),
    'ack_low_table': (
        ';   ACK low phase          OUT(fall) + WAIT 62 (=63) + LDI       = 65',
        ';   ACK low phase          OUT(fall) + WAIT 255 (=256) + LDI    = 258',
    ),
    'addr_ack_table': (
        ';   address ACK high       OUT(rise) + WAIT 28 (=29) + IN + AND\n'
        ';                          + WAIT 19 (=20) + BNZ, then either',
        ';   address ACK high       OUT(rise) + WAIT 119 (=120) + IN + AND\n'
        ';                          + WAIT 110 (=111) + BNZ, then either',
    ),
    'addr_ack_total': (
        ';                          through)                               = 60',
        ';                          through)                             = 242',
    ),
    'nack_stop_table': (
        ';                          (NACK, branch taken)                   = 60\n'
        ';                            (IN at high offset 30 on both paths)\n'
        ';   data ACK high          OUT(rise) + WAIT 28 (=29) + IN + AND\n'
        ';                          + WAIT 26 (=27) + LDI                  = 60\n'
        ';   START hold             OUT(START) + WAIT 60 (=61) + LDI\n'
        ';                          + MOV + AND                           = 65\n'
        ';                            (UM10204 t_HD;STA minimum: 30 cycles)\n'
        ';   STOP setup             OUT(SCL rise) + WAIT 57 (=58) + LDI   = 60\n'
        ';                            (UM10204 t_SU;STO minimum: 30 cycles)',
        ';                          (NACK, branch taken)                 = 242\n'
        ';                            (IN at high offset 121 on both paths)\n'
        ';   data ACK high          OUT(rise) + WAIT 119 (=120) + IN + AND\n'
        ';                          + WAIT 117 (=118) + LDI              = 242\n'
        ';   => every data / ACK clock is 258 + 242 = 500 cycles, fall to fall.\n'
        ';   START hold             OUT(START) + WAIT 196 (=197) + LDI\n'
        ';                          + MOV + 4x SHF + AND                 = 205\n'
        ';                            (UM10204 t_HD;STA minimum: 200 cycles)\n'
        ';   STOP setup             OUT(SCL rise) + WAIT 202 (=203) + LDI = 205\n'
        ';                            (UM10204 t_SU;STO minimum: 200 cycles)\n'
        ';   pre-STOP low           as the data-clock low phase          = 258',
    ),
    'in_offset_note': (
        '; #258 the IN sat 22 cycles into this low phase.',
        '; #258 the IN sat 32 cycles into this low phase.',
    ),
    'nack_stop_note': (
        "; ---------- the SCL fall exactly 60 cycles after the ACK clock's rise.)",
        "; ---------- the SCL fall exactly 242 cycles after the ACK clock's rise.\n"
        '; ---------- Issue #258 correction: this WAIT was 47 from issue #125 until\n'
        '; ---------- #258, which held the ninth SCL high 284 cycles on this taken\n'
        '; ---------- path, not 242 -- legal (UM10204 sets no t_HIGH maximum) but\n'
        '; ---------- not the stated budget, and invisible to the fall-through\n'
        "; ---------- `.cyclesec` count and to the model's t_HIGH(min). From the\n"
        '; ---------- BNZ at high offset 234 both paths now take 8 cycles to the\n'
        '; ---------- fall: BNZ + LDI + MOV + 4x SHF + AND (ACK) and BNZ + LDI +\n'
        '; ---------- WAIT 5 (=6) (NACK), the same shape as i2c_fast.asm.)',
    ),
}

#: i2c_ack1_low's "no sample" prose: fast carries the first line on the WAIT
#: itself, std as standalone lines with the WAIT after the shared "answer
#: anywhere" line. Placement is annotation; the instruction stream is one.
ACK1_NO_SAMPLE_STD = (
    '                               ; 256 cycles, no sample: the peripheral may\n'
    '                               ; answer anywhere in this low phase'
)
ANSWER_ANYWHERE = '                               ; answer anywhere in this low phase'


def _prose_lines(block, where):
    """Split a per-mode annotation block into lines, asserting every line is
    comment-only prose (or empty): nothing executable can hide in per-mode
    text, which is what keeps the two instruction streams one stream."""
    lines = block.split("\n") if block else []
    for line in lines:
        assert not line.strip() or line.lstrip().startswith(";"), (
            f"{where}: per-mode text must be comment-only, got {line!r}")
    return lines


class PairBuilder:
    """Emits the one shared program for both modes at once.

    `raw()` text and `note()` lines are byte-identical in both files except
    for `note()`'s per-mode trailing prose; `wait()` emits a site's single
    WAIT with the mode's `WAITS` immediate. Every instruction and directive
    of the pair passes through here exactly once.
    """

    def __init__(self):
        self.lines = ([], [])

    def raw(self, text):
        """Lines shared verbatim by both modes (may be multi-line)."""
        lines = text.split("\n")
        self.lines[0].extend(lines)
        self.lines[1].extend(lines)

    def note(self, line, notes=("", "")):
        """A shared instruction or directive line with per-mode trailing
        prose: `line` exists once, `notes[i]` (comment-only, asserted) is
        appended for mode i and may continue on further lines."""
        for i, note in enumerate(notes):
            _prose_lines(note, "note")
            self.lines[i].extend((line + note).split("\n"))

    def wait(self, site, notes=("", ""), before=("", ""), after=("", "")):
        """The site's one WAIT instruction: per-mode immediate WAITS[site]
        and per-mode prose. `notes` glue onto the WAIT line (single line);
        `before` / `after` are per-mode comment-only blocks around it --
        fast's ack1_low carries its prose on and after the WAIT, std's
        before it, so the shared "answer anywhere" annotation line is part
        of that block on the std side."""
        for i in (0, 1):
            self.lines[i].extend(_prose_lines(before[i], f"wait {site} before"))
            assert "\n" not in notes[i], f"wait {site}: note must be one line"
            _prose_lines(notes[i], f"wait {site} note")
            self.lines[i].append(f"        WAIT  {WAITS[site][i]}{notes[i]}")
            self.lines[i].extend(_prose_lines(after[i], f"wait {site} after"))

    def slot(self, name):
        """A per-mode prose block from SLOTS (comment-only, asserted)."""
        for i, block in enumerate(SLOTS[name]):
            self.lines[i].extend(_prose_lines(block, f"slot {name}"))


def plain_bit_low(b, prefix, n):
    b.raw(f".cyclesec i2c_{prefix}{n}_low\n"
          "        OUT   UIO_OUT, R3")
    b.wait("data_low")
    b.raw("        OR    R3, R2\n"
          ".endcyclesec")


def plain_bit_high(b, prefix, n):
    b.raw(f".cyclesec i2c_{prefix}{n}_high\n"
          "        OUT   UIO_OUT, R3\n"
          "        SHF   R0, LEFT")
    b.wait("data_high")
    b.raw("        MOV   R3, R0\n"
          "        SHF   R3, RIGHT\n"
          "        SHF   R3, RIGHT\n"
          "        SHF   R3, RIGHT\n"
          "        SHF   R3, RIGHT       ; R0's MSB -> SDA (bit 3)\n"
          "        AND   R3, R1\n"
          ".endcyclesec")


def plain_bit_clocks(b, prefix, first, last):
    """The ordinary unrolled bit clocks, identical in both modes but for the
    WAITS literals. The ISA has no spare register for a loop counter (see
    the header prose), so the eight clocks per byte stay unrolled in the
    program; the loop lives here in the generator."""
    for n in range(first, last + 1):
        plain_bit_low(b, prefix, n)
        plain_bit_high(b, prefix, n)


def program(b):
    b.slot('title')
    b.raw(';\n'
          '; Implements `spec/decision-records/0001-isa.md` section "Per-protocol')
    b.slot('budget')
    b.raw("""\
;
; Pin plan: DR 0010's target plan, the standard Tiny Tapeout I2C Pmod
; (upper row), adopted by issue #155:
;   UIO_OUT bit 2 = SCL (controller side of the open-drain line, uio[2])
;   UIO_OUT bit 3 = SDA (controller side, uio[3])
; Open-drain convention: writing 1 RELEASES the line (pull-up wins),
; writing 0 asserts it low. On silicon that convention is DR 0012's
; open-drain pin mode: the setup below writes 0x0C to the UIO_OD control
; register (`WCTL UIO_OD`, SCL|SDA), after which uio_oe[n] = ~uio_out[n]
; on those two pins -- a 0 drives the pad low, a 1 releases it. The OUT of
; 0x0C comes BEFORE the WCTL on purpose: uio_out resets to 0x00, so
; enabling open-drain first would pull both lines low for a cycle. Until
; the WCTL retires both pins are inputs (DR 0012's reset state), i.e.
; released. The bench runs this program on a pad model that resolves
; each line from uio_oe/uio_out, a pull-up and the peripheral, and reads
; it back on uio_in (verification/uio_pads.py, issue #136): the bus it
; grades goes low only where this program's pad is enabled and driving 0.
;
; The 0x08 mask (R1) does double duty: it extracts the current data bit
; (R0's MSB, moved to bit 3 by four `SHF R3, RIGHT`) AND is exactly the
; "SCL low, SDA released" ACK-slot pin value, because SDA sits on bit 3.
; The four shifts are the cost of SDA not being bit 7 (on the earlier
; plan, SDA on uio[7], R0's MSB was already in place); each high phase
; pays for them out of its WAIT, so every phase length is unchanged. The
; 0x04 constant (R2) is the SCL bit OR-ed in for the high phase. With
; R0 = byte and R3 = temp all four
; registers are live; there is no room for a loop counter, so the eight
; data clocks per byte are UNROLLED (the evidence record carries this as
; an ISA finding: DR 0001's blessed constant-trip-count loop needs a
; fifth live value -- byte, mask, SCL constant, temp, counter -- and this
; ISA has four registers).
;
; Transfer shape (one write transfer, address 0x50, one data byte 0x5A):
;   START -> 0xA0 (0x50<<1 | write) -> ACK -> 0x5A -> ACK -> STOP
; The address ACK slot is the one place this program branches on pin data
; (`IN` + `AND` + `BNZ` on the sampled SDA): a NACK from the peripheral
; skips the data byte and goes straight to STOP. That is DR 0001's one
; explicitly-sanctioned data-dependent branch (an I2C ACK wait is a
; protocol handshake, not a timing budget), and the assembler's
; data-dependent-latency lint reports it as a WARNING -- exactly one per
; program, expected, and asserted by the bench. The data byte's ACK slot
; samples the same way but does not branch: the transfer ends after one
; byte either way, so a branch there would be decorative. Both ACK samples
; are taken in the middle of the ninth SCL HIGH phase (issue #258), where
; I2C guarantees SDA is stable; the ACK low phases carry no sample.
;
; Cycle accounting (DR 0001's opcode table: every instruction is 1 cycle
; except WAIT imm8 = imm8 + 1). Each measured window is the span between
; two OUT retirements; because every OUT's new value is visible on the
; pin exactly one cycle after it retires, the +1 visibility delay cancels
; in every window. `.cyclesec` convention in this file: a phase's section
; opens AT the OUT that starts the phase and closes before the OUT that
; ends it, so the section's cycle count IS the phase's measured length:
;""")
    b.slot('data_clock_table')
    b.raw(';                            (no SHF/AND: the ACK prep is one MOV)')
    b.slot('ack_low_table')
    b.raw(';                            (no sample in the low phase, issue #258)')
    b.slot('addr_ack_table')
    b.raw(';                          LDI + MOV + 4x SHF + AND (ACK, falls')
    b.slot('addr_ack_total')
    b.raw(';                          or LDI + WAIT 5 (=6) at stop_from_addr')
    b.slot('nack_stop_table')
    b.raw("""\
;
; Every timing-critical delay is an assemble-time literal. Nothing that
; produces protocol timing branches on pin data -- the single BNZ is the
; sanctioned ACK handshake, and its outcome chooses WHAT is transmitted
; next (data byte vs STOP), never how long a phase lasts.

; ---------------------------------------------------------------- setup
        LDI   R1, 0x08        ; bit mask / "SCL low, SDA released" pins
        LDI   R2, 0x04        ; SCL bit, OR-ed in for the high phase
        LDI   R3, 0x0C        ; both lines released: bus idle
        OUT   UIO_OUT, R3
        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)
        WAIT  255             ; > 1 SCL period of guaranteed idle

; --------------------------------------------------------------- START
        LDI   R3, 0x04        ; SCL high, SDA low
.cyclesec i2c_start
        OUT   UIO_OUT, R3     ; START: SDA falls while SCL high""")
    b.wait('start_hold',
           notes=('              ; 61 cycles',
                  '              ; 197 cycles'))
    b.raw("""\
        LDI   R0, 0xA0        ; address byte 0x50<<1|W, MSB first
        MOV   R3, R0
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT       ; R0's MSB -> SDA (bit 3)
        AND   R3, R1          ; R3 = SDA(bit 1 = 1), SCL low""")
    b.note('.endcyclesec',
           notes=('                   ; t_HD;STA = 65 cycles',
                  '                   ; t_HD;STA = 205 cycles'))
    b.raw("""\
; ---------------------------------------------- address byte 0xA0, MSB first
.cyclesec i2c_abit1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA rises (bit 1 = 1) in low""")
    b.wait('data_low',
           notes=('              ; 63 cycles', ''))
    b.raw("        OR    R3, R2          ; raise SCL, SDA unchanged")
    b.note('.endcyclesec', notes=T_LOW)
    b.raw("""\
.cyclesec i2c_abit1_high
        OUT   UIO_OUT, R3     ; SCL rises: bit 1 sampled on the line
        SHF   R0, LEFT        ; bit 2 into position""")
    b.wait('data_high',
           notes=('              ; 56 cycles', ''))
    b.raw("""\
        MOV   R3, R0
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT       ; R0's MSB -> SDA (bit 3)
        AND   R3, R1          ; R3 = SDA(bit 2), SCL low""")
    b.note('.endcyclesec', notes=T_HIGH)

    plain_bit_clocks(b, 'abit', 2, 7)
    plain_bit_low(b, 'abit', 8)
    b.raw(".cyclesec i2c_abit8_high\n"
          "        OUT   UIO_OUT, R3     ; last address clock rises")
    b.wait('last_high',
           notes=('              ; 58 cycles (the ACK prep is one MOV)',
                  '              ; (the ACK prep is one MOV)'))
    b.raw("        MOV   R3, R1          ; 0x08: SDA released for the ACK slot")
    b.note('.endcyclesec', notes=T_HIGH)
    b.raw("""\
; ------------------------------------- address ACK slot (the branch point)
; Issue #258: the ACK bit is sampled INSIDE the ninth SCL high, never in
; its low phase. The peripheral may put its ACK on SDA anywhere in the low
; phase (UM10204 only asks for t_SU;DAT before the rise), so a sample
; taken in the low phase can read a legal but late ACK as a NACK. Until""")
    b.slot('in_offset_note')
    b.raw("""\
.cyclesec i2c_ack1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA released for the peripheral""")
    b.wait('data_low',
           notes=('              ; 63 cycles, no sample: the peripheral may', ''),
           before=('', ACK1_NO_SAMPLE_STD),
           after=(ANSWER_ANYWHERE, ''))
    b.raw("        LDI   R3, 0x0C        ; SCL high, SDA released")
    b.note('.endcyclesec', notes=T_LOW)
    b.raw("""\
.cyclesec i2c_ack1_high
        OUT   UIO_OUT, R3     ; SCL rises: ACK/NACK must now hold on SDA
                               ; for the whole high phase""")
    b.wait('ack_pre',
           notes=('              ; 29 cycles',
                  '             ; 120 cycles'))
    b.note("        IN    R3, UIO_IN",
           notes=('      ; sample the bus at high offset 30: 30\n'
                  '                               ; cycles after the rise, 30 before the',
                  '      ; sample the bus at high offset 121: 121\n'
                  '                               ; cycles after the rise, 121 before the'))
    b.raw("""\
                               ; fall (taints R3; the rise pins in R3 are
                               ; already on the pads)
        AND   R3, R1          ; isolate SDA (bit 3); sets Z. Nothing from
                               ; here to the BNZ writes the flags (WAIT
                               ; does not)""")
    b.wait('ack1_post',
           notes=('              ; 20 cycles: the BNZ keeps its offset (52),',
                  '             ; 111 cycles: the BNZ keeps its offset (234),'),
           after=('                               ; so both branch paths below are unchanged',
                  '                               ; so the fall-through path is unchanged'))
    b.raw("""\
        BNZ   stop_from_addr  ; SDA read 1 = NACK -> STOP. The one
                               ; sanctioned data-dependent branch; the
                               ; assembler warns about exactly this line
        LDI   R0, 0x5A        ; the data byte (ACK path)
        MOV   R3, R0
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT       ; R0's MSB -> SDA (bit 3)
        AND   R3, R1          ; R3 = SDA(bit 1 = 0), SCL low""")
    b.note('.endcyclesec', notes=T_HIGH)
    b.raw("""\
; ------------------------------------------------ data byte 0x5A, MSB first
.cyclesec i2c_dbit1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA falls (bit 1 = 0) in low""")
    b.wait('data_low')
    b.raw("        OR    R3, R2\n"
          ".endcyclesec")
    plain_bit_high(b, 'dbit', 1)
    plain_bit_clocks(b, 'dbit', 2, 7)
    plain_bit_low(b, 'dbit', 8)
    b.raw(".cyclesec i2c_dbit8_high\n"
          "        OUT   UIO_OUT, R3     ; last data clock rises")
    b.wait('last_high',
           notes=('              ; 58 cycles',
                  '              ; (the ACK prep is one MOV)'))
    b.raw("        MOV   R3, R1          ; 0x08: SDA released for the ACK slot")
    b.note('.endcyclesec', notes=T_HIGH)
    b.raw("""\
; ------------------------------- data ACK slot (sampled, not branched on:
; ------------------------------- the transfer ends after one byte either
; ------------------------------- way -- the branch lives on the address
; ------------------------------- ACK, where its outcome changes the rest)
.cyclesec i2c_ack2_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA released for the peripheral""")
    b.wait('data_low',
           notes=('              ; 63 cycles, no sample (as i2c_ack1_low)', ''),
           before=('', '                               ; 256 cycles, no sample (as i2c_ack1_low)'))
    b.raw("        LDI   R3, 0x0C        ; SCL high, SDA released")
    b.note('.endcyclesec', notes=T_LOW)
    b.raw(".cyclesec i2c_ack2_high\n"
          "        OUT   UIO_OUT, R3     ; SCL rises")
    b.wait('ack_pre',
           notes=('              ; 29 cycles',
                  '             ; 120 cycles'))
    b.note("        IN    R3, UIO_IN",
           notes=('      ; sample at high offset 30, as the address ACK',
                  '      ; sample at high offset 121, as the address ACK'))
    b.raw("""\
        AND   R3, R1          ; isolate SDA; sets Z (no branch reads it: the
                               ; Z flag holds this reading to HALT)""")
    b.wait('ack2_post',
           notes=('              ; 27 cycles',
                  '             ; 118 cycles'))
    b.raw("        LDI   R3, 0x08        ; SDA released, SCL still high")
    b.note('.endcyclesec', notes=T_HIGH)
    b.raw("""\
; ------------------------------------------------- STOP from the data ACK
.cyclesec i2c_stop_data_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA still released
        LDI   R3, 0x00        ; SDA low during the low period
        OUT   UIO_OUT, R3     ; SDA falls (while SCL low)""")
    b.wait('stop_low',
           notes=('              ; 61 cycles: pads this low period', ''))
    b.raw("        LDI   R3, 0x04        ; SCL high, SDA low")
    b.note('.endcyclesec',
           notes=('                   ; 65: the full pre-STOP low period, SCL',
                  '                   ; 258: the full pre-STOP low period, SCL'))
    b.raw("                               ; fall to (exclusive) the SCL rise")
    b.raw(".cyclesec i2c_stop_data\n"
          "        OUT   UIO_OUT, R3     ; SCL rises: STOP setup begins")
    b.wait('stop_setup',
           notes=('              ; 58 cycles',
                  '              ; 203 cycles'))
    b.raw("        LDI   R3, 0x0C        ; SDA released")
    b.note('.endcyclesec', notes=T_SU_STO)
    b.raw("""\
        OUT   UIO_OUT, R3     ; SDA rises while SCL high: STOP
        WAIT  255             ; hold the bus idle
        HALT
; ------------------------------------- STOP from a NACKed address (jumped
; ---------- to from i2c_ack1_high's BNZ: same sequence, own copy, so the
; ---------- taken-branch path needs no extra JMP whose cycle would then
; ---------- have to be subtracted from a phase budget. LDI + WAIT 5 land""")
    b.slot('nack_stop_note')
    b.raw("""\
stop_from_addr:
        LDI   R3, 0x08        ; SDA released, SCL still high
        WAIT  5               ; 6 cycles (the 4 the ACK path spends on SHFs)
.cyclesec i2c_stop_addr_low""")
    b.note("        OUT   UIO_OUT, R3",
           notes=('     ; SCL falls (at ACK-rise + 60 exactly)',
                  '     ; SCL falls (at ACK-rise + 242 exactly)'))
    b.raw("        LDI   R3, 0x00        ; SDA low during the low period\n"
          "        OUT   UIO_OUT, R3")
    b.wait('stop_low')
    b.raw("        LDI   R3, 0x04")
    b.note('.endcyclesec',
           notes=('                   ; 65 (same shape as i2c_stop_data_low)',
                  '                   ; 258: the full pre-STOP low period, SCL\n'
                  '                               ; fall to (exclusive) the SCL rise'))
    b.raw(".cyclesec i2c_stop_addr\n"
          "        OUT   UIO_OUT, R3     ; SCL rises: STOP setup begins")
    b.wait('stop_setup')
    b.raw("        LDI   R3, 0x0C")
    b.note('.endcyclesec', notes=T_SU_STO)
    b.raw("        OUT   UIO_OUT, R3     ; SDA rises while SCL high: STOP")
    b.wait('idle',
           notes=('', '             ; hold the bus idle'))
    b.raw("        HALT")


def build(idx):
    for name, pair in SLOTS.items():
        for block in pair:
            _prose_lines(block, f"slot {name}")
    b = PairBuilder()
    program(b)
    return "\n".join(b.lines[idx]) + "\n"


def main(argv):
    check = "--check" in argv
    drift = False
    for idx, name in enumerate(("i2c_fast", "i2c_std")):
        path = OUT_DIR / f"{name}.asm"
        text = build(idx)
        if check:
            if not path.exists() or path.read_text() != text:
                print(f"DRIFT {path}")
                drift = True
        else:
            path.write_text(text)
            print(f"wrote {path}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
