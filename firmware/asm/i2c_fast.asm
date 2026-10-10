; i2c_fast.asm -- bit-banged I2C controller, Fast-mode 400 kHz phase budget
; (issue #73, part of #23).
;
; Implements `spec/decision-records/0001-isa.md` section "Per-protocol
; cycle-budget sketch -> I2C (controller, Fast-mode 400 kHz)": SCL period
; 125 cycles at the target 50 MHz core clock, allocated low = 65 cycles
; (the UM10204 Table 10 Fast-mode t_LOW minimum of 1.3 us, to the cycle)
; and high = 60 cycles (t_HIGH's minimum is 30 cycles; DR 0001's sketch
; allocates the remaining period slack to the high phase). Standard-mode
; is the sibling program `i2c_std.asm` -- same instruction stream, larger
; phase literals.
;
; Pin plan (this program's own; the ratified pin-role decision record is
; still open per target-spec row 5):
;   UIO_OUT bit 0 = SCL (controller side of the open-drain line)
;   UIO_OUT bit 7 = SDA (controller side)
; Open-drain convention: writing 1 RELEASES the line (pull-up wins),
; writing 0 asserts it low. On silicon that convention is DR 0012's
; open-drain pin mode: the setup below writes 0x81 to the UIO_OD control
; register (`WCTL UIO_OD`, SCL|SDA), after which uio_oe[n] = ~uio_out[n]
; on those two pins -- a 0 drives the pad low, a 1 releases it. The OUT of
; 0x81 comes BEFORE the WCTL on purpose: uio_out resets to 0x00, so
; enabling open-drain first would pull both lines low for a cycle. Until
; the WCTL retires both pins are inputs (DR 0012's reset state), i.e.
; released. The bench runs this program on a pad model that resolves
; each line from uio_oe/uio_out, a pull-up and the peripheral, and reads
; it back on uio_in (verification/uio_pads.py, issue #136): the bus it
; grades goes low only where this program's pad is enabled and driving 0.
;
; The 0x80 mask (R1) does double duty: it extracts the current data bit
; from R0's MSB AND is exactly the "SCL low, SDA released" ACK-slot pin
; value, because SDA sits on bit 7. The 0x01 constant (R2) is the SCL bit
; OR-ed in for the high phase. With R0 = byte and R3 = temp all four
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
; byte either way, so a branch there would be decorative.
;
; Cycle accounting (DR 0001's opcode table: every instruction is 1 cycle
; except WAIT imm8 = imm8 + 1). Each measured window is the span between
; two OUT retirements; because every OUT's new value is visible on the
; pin exactly one cycle after it retires, the +1 visibility delay cancels
; in every window. `.cyclesec` convention in this file: a phase's section
; opens AT the OUT that starts the phase and closes before the OUT that
; ends it, so the section's cycle count IS the phase's measured length:
;
;   data-clock low phase   OUT(fall) + WAIT 62 (=63) + OR        = 65
;   data-clock high phase  OUT(rise) + SHF + WAIT 55 (=56)
;                          + MOV + AND                          = 60
;   last bit's high phase  OUT(rise) + WAIT 57 (=58) + MOV       = 60
;                            (no SHF/AND: the ACK prep is one MOV)
;   ACK low phase          OUT(fall) + WAIT 20 (=21) + IN + WAIT 39
;                          (=40) + AND + LDI                    = 65
;   START hold             OUT(START) + WAIT 60 (=61) + LDI
;                          + MOV + AND                           = 65
;                            (UM10204 t_HD;STA minimum: 30 cycles)
;   STOP setup             OUT(SCL rise) + WAIT 57 (=58) + LDI   = 60
;                            (UM10204 t_SU;STO minimum: 30 cycles)
;
; Every timing-critical delay is an assemble-time literal. Nothing that
; produces protocol timing branches on pin data -- the single BNZ is the
; sanctioned ACK handshake, and its outcome chooses WHAT is transmitted
; next (data byte vs STOP), never how long a phase lasts.

; ---------------------------------------------------------------- setup
        LDI   R1, 0x80        ; bit mask / "SCL low, SDA released" pins
        LDI   R2, 0x01        ; SCL bit, OR-ed in for the high phase
        LDI   R3, 0x81        ; both lines released: bus idle
        OUT   UIO_OUT, R3
        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)
        WAIT  255             ; > 1 SCL period of guaranteed idle

; --------------------------------------------------------------- START
        LDI   R3, 0x01        ; SCL high, SDA low
.cyclesec i2c_start
        OUT   UIO_OUT, R3     ; START: SDA falls while SCL high
        WAIT  60              ; 61 cycles
        LDI   R0, 0xA0        ; address byte 0x50<<1|W, MSB first
        MOV   R3, R0
        AND   R3, R1          ; R3 = SDA(bit 1 = 1), SCL low
.endcyclesec                   ; t_HD;STA = 65 cycles
; ---------------------------------------------- address byte 0xA0, MSB first
.cyclesec i2c_abit1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA rises (bit 1 = 1) in low
        WAIT  62              ; 63 cycles
        OR    R3, R2          ; raise SCL, SDA unchanged
.endcyclesec                   ; t_LOW = 65
.cyclesec i2c_abit1_high
        OUT   UIO_OUT, R3     ; SCL rises: bit 1 sampled on the line
        SHF   R0, LEFT        ; bit 2 into position
        WAIT  55              ; 56 cycles
        MOV   R3, R0
        AND   R3, R1          ; R3 = SDA(bit 2), SCL low
.endcyclesec                   ; t_HIGH = 60
.cyclesec i2c_abit2_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit2_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit3_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit3_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit4_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit4_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit5_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit5_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit6_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit6_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit7_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit7_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_abit8_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_abit8_high
        OUT   UIO_OUT, R3     ; last address clock rises
        WAIT  57              ; 58 cycles (the ACK prep is one MOV)
        MOV   R3, R1          ; 0x80: SDA released for the ACK slot
.endcyclesec                   ; t_HIGH = 60
; ------------------------------------- address ACK slot (the branch point)
.cyclesec i2c_ack1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA released
        WAIT  20              ; 21 cycles: the bench's peripheral pulls
                               ; SDA low two cycles after seeing this
                               ; fall, well before the sample below
        IN    R3, UIO_IN      ; sample the bus (taints R3)
        WAIT  39              ; 40 cycles
        AND   R3, R1          ; isolate SDA (bit 7); sets Z -- and the
                               ; flags must survive to the BNZ, so the rise
                               ; pins are built with LDI (not flag-setting),
                               ; never MOV/OR which would clobber Z
        LDI   R3, 0x81        ; SCL high, SDA released
.endcyclesec                   ; t_LOW = 65
.cyclesec i2c_ack1_high
        OUT   UIO_OUT, R3     ; SCL rises: ACK/NACK is the line level AT
                               ; this edge; sampled above at IN
        WAIT  54              ; 55 cycles
        BNZ   stop_from_addr  ; SDA read 1 = NACK -> STOP. The one
                               ; sanctioned data-dependent branch; the
                               ; assembler warns about exactly this line
        LDI   R0, 0x5A        ; the data byte (ACK path)
        MOV   R3, R0
        AND   R3, R1          ; R3 = SDA(bit 1 = 0), SCL low
.endcyclesec                   ; t_HIGH = 60
; ------------------------------------------------ data byte 0x5A, MSB first
.cyclesec i2c_dbit1_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA falls (bit 1 = 0) in low
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit1_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit2_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit2_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit3_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit3_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit4_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit4_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit5_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit5_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit6_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit6_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit7_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit7_high
        OUT   UIO_OUT, R3
        SHF   R0, LEFT
        WAIT  55
        MOV   R3, R0
        AND   R3, R1
.endcyclesec
.cyclesec i2c_dbit8_low
        OUT   UIO_OUT, R3
        WAIT  62
        OR    R3, R2
.endcyclesec
.cyclesec i2c_dbit8_high
        OUT   UIO_OUT, R3     ; last data clock rises
        WAIT  57              ; 58 cycles
        MOV   R3, R1          ; 0x80: SDA released for the ACK slot
.endcyclesec                   ; t_HIGH = 60
; ------------------------------- data ACK slot (sampled, not branched on:
; ------------------------------- the transfer ends after one byte either
; ------------------------------- way -- the branch lives on the address
; ------------------------------- ACK, where its outcome changes the rest)
.cyclesec i2c_ack2_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA released
        WAIT  20              ; 21 cycles
        IN    R3, UIO_IN      ; sample the bus (taints R3)
        WAIT  39              ; 40 cycles
        AND   R3, R1          ; isolate SDA; sets Z (no branch reads it)
        LDI   R3, 0x81
.endcyclesec                   ; t_LOW = 65
.cyclesec i2c_ack2_high
        OUT   UIO_OUT, R3     ; SCL rises
        WAIT  56              ; 57 cycles
        LDI   R3, 0x80        ; SDA released, SCL still high
        WAIT  0               ; 1 cycle: pads the SCL fall to exactly 60
.endcyclesec                   ; t_HIGH = 60
; ------------------------------------------------- STOP from the data ACK
.cyclesec i2c_stop_data_low
        OUT   UIO_OUT, R3     ; SCL falls; SDA still released
        LDI   R3, 0x00        ; SDA low during the low period
        OUT   UIO_OUT, R3     ; SDA falls (while SCL low)
        WAIT  60              ; 61 cycles: pads this low period
        LDI   R3, 0x01        ; SCL high, SDA low
.endcyclesec                   ; 65: the full pre-STOP low period, SCL
                               ; fall to (exclusive) the SCL rise
.cyclesec i2c_stop_data
        OUT   UIO_OUT, R3     ; SCL rises: STOP setup begins
        WAIT  57              ; 58 cycles
        LDI   R3, 0x81        ; SDA released
.endcyclesec                   ; t_SU;STO = 60
        OUT   UIO_OUT, R3     ; SDA rises while SCL high: STOP
        WAIT  255             ; hold the bus idle
        HALT
; ------------------------------------- STOP from a NACKed address (jumped
; ---------- to from i2c_ack1_high's BNZ: same sequence, own copy, so the
; ---------- taken-branch path needs no extra JMP whose cycle would then
; ---------- have to be subtracted from a phase budget. LDI + WAIT 1 land
; ---------- the SCL fall exactly 60 cycles after the ACK clock's rise.)
stop_from_addr:
        LDI   R3, 0x80        ; SDA released, SCL still high
        WAIT  1               ; 2 cycles
.cyclesec i2c_stop_addr_low
        OUT   UIO_OUT, R3     ; SCL falls (at ACK-rise + 60 exactly)
        LDI   R3, 0x00        ; SDA low during the low period
        OUT   UIO_OUT, R3
        WAIT  60
        LDI   R3, 0x01
.endcyclesec                   ; 65 (same shape as i2c_stop_data_low)
.cyclesec i2c_stop_addr
        OUT   UIO_OUT, R3     ; SCL rises: STOP setup begins
        WAIT  57
        LDI   R3, 0x81
.endcyclesec                   ; t_SU;STO = 60
        OUT   UIO_OUT, R3     ; SDA rises while SCL high: STOP
        WAIT  255
        HALT
