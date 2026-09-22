; demo_roundtrip.asm -- the assembler's RTL round-trip program (issue #22).
;
; Purpose: exercise every one of DR 0001's 16 opcode mnemonics at least
; once so that assembling this file and loading the committed image through
; `rtl/protocol_program_memory.v`'s serial load phase (DR 0001 "Program
; memory sizing and loading") demonstrates the assembler's encoding and the
; RTL agreeing on all of them -- the round-trip claim of
; `spec/decision-records/0003-firmware-toolchain.md`.
;
; It is deliberately not a protocol program: the UART/SPI/I2C programs are
; issue #23's scope. This one is a deterministic coverage program:
;
;   1. a straight-line `.cyclesec banner` that drives two marker bytes onto
;      UO_OUT with a WAIT between them (the exact entry->exit cycle count
;      is computed statically by the assembler, per DR 0001's
;      no-data-dependent-latency guarantee);
;   2. a shift loop with an assemble-time-constant trip count (DR 0001's
;      blessed loop shape -- the count comes from LDI, never from a pin);
;   3. a pin-sample-and-echo stretch whose IN-sampled value is deliberately
;      never branched on (that would be the data-dependent-latency hazard
;      DR 0001's timing model forbids for protocol timing);
;   4. a constant-trip-count tail loop using BZ and BNZ, then HALT.

        NOP                     ; cycle-padding no-op (also: opcode coverage)

.cyclesec banner
        LDI   R0, 0xA5         ; marker byte 10100101
        OUT   UO_OUT, R0       ; drive it on the dedicated outputs
        WAIT  3                ; hold marker for 4 cycles (imm8 + 1)
        LDI   R0, 0x5A         ; marker byte 01011010
        OUT   UO_OUT, R0
.endcyclesec

        LDI   R1, 4            ; loop trip count (assemble-time constant)
        LDI   R2, 1            ; loop decrement constant (no SUBI in DR 0001)
blink:
        SHF   R0, LEFT         ; walk the marker through the output port
        OUT   UO_OUT, R0
        SUB   R1, R2           ; count down; sets Z, C
        BZ    sample           ; constant-trip-count exit (never pin data)
        JMP   blink

sample:
        IN    R3, UI_IN        ; sample the dedicated input pins once
        MOV   R0, R3
        AND   R0, R2           ; isolate bit 0 of the sample
        OR    R0, R3           ; merge back (sample | bit0(sample) == sample)
        XOR   R0, R3           ; XOR with itself-scoped value; flags from sample
        ADD   R0, R3           ; arithmetic path over the same operand
        SUB   R0, R3           ; restore R0 == R3 (the sample)
        OUT   UO_OUT, R0       ; echo inputs onto outputs
        SHF   R0, RIGHT        ; both shift directions exercised
        LDI   R1, 3            ; tail loop trip count
spin:
        WAIT  0                ; legal 1-cycle stall (DR 0001: WAIT 0 == 1 cycle)
        SUB   R1, R2
        BNZ   spin             ; constant trip count; Z from constants only
        HALT
