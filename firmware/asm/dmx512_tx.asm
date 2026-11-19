; dmx512_tx.asm -- DMX512 (USITT DMX512-A) universe transmitter, firmware on
; the frozen ISA (issue #445; multi-protocol extra credit, catalog #443).
; No RTL change, no hardware assist: the same bit-banged UART transmitter
; shape as `uart_tx.asm`, at DMX512's 250 kbaud 8N2 rate, framed by a BREAK
; and a mark-after-break instead of idle.
;
; What it sends. An endless stream of complete universes. Each packet is:
;
;   BREAK            line low, 4,609 cycles from the falling edge to the
;                    rising edge (91.78 us at row 4's nominal 50 MHz clock)
;                    -- above the 4,600-cycle (92-us-class) controller
;                    target the issue sets (the 88 us figure of the 1986
;                    spec is the receiver-recognition limit)
;   MARK-AFTER-BREAK line high, 605 cycles (12.1 us) -- above the
;                    600-cycle (12-us-class) target (again a step above the
;                    spec's 8 us receiver limit)
;   START CODE       one 8N2 slot carrying 0x00
;   512 SLOTS        one 8N2 slot per channel, back to back
;   then the next BREAK, whose falling edge lands exactly on the end of
;   slot 512's second stop bit.
;
; Each slot is 11 bit periods: one low start bit, eight data bits LSB
; first, two high stop bits -- exactly the `uart_tx.asm` frame at 200
; cycles/bit instead of 50, with a second stop bit. Every instruction is
; 1 cycle except `WAIT imm8` = imm8 + 1 (DR 0001's opcode table), so every
; figure above is an assemble-time literal, never data-dependent (DR 0001
; "Timing model"): the program reads no pin at all.
;
; Cycle accounting, edge to edge. A pin changes when its OUT retires, so
; an interval between two edges sums the first OUT's own cycle plus the
; instructions between the two OUTs (the second OUT's cost is not part of
; the interval):
;
;   per data bit (the `.cyclesec dmx512_*_bit` sections)
;     OUT+SHF+SUB+WAIT 193+BNZ+MOV+AND      = 1+1+1+194+1+1+1+1 = 200 cycles
;   START -> first data bit   OUT+WAIT 194+WCTL+LDI+MOV+AND
;                                                     = 1+195+1+1+1+1   = 200
;   last data bit -> stop 1   OUT+SHF+SUB+WAIT 193+BNZ+WAIT 1
;                                             = 1+1+1+194+1+2 (+OUT) = 200
;   stop 1 -> next START      OUT + WAIT 194 + WAIT 195 + RCTL + ADD x5
;                             + BNZ + XOR + (OUT)  = 1+195+196+1+5+1+1+1 = 400
;   one slot = 11 x 200 = 2,200 cycles, no extra inter-slot mark.
;
; Where the 512 levels come from. The ISA has four registers and no data
; memory, so the universe is not stored. The channel level evolves by a
; fixed pattern, `level <- level + 5` each slot from 0: slot n carries
; (5 x (n-1)) mod 256. A 5-step walk mod 256 (5 is odd) visits all 256
; levels with period 256, and adjacent slots always differ -- including
; across the 255 -> 4 wrap at slot 53. The pattern's natural 0x00 slots
; (1 and 257) send nine consecutive low periods, and slot 512 carries 251
; (0xFB). 512 slots = two full pattern periods.
;
; How the level survives the slot. The bit loop is `uart_tx.asm`'s: it
; shifts R0 right eight times, which destroys the byte -- fine there, but
; here R0 must still hold the level for the next slot's `+ 5`. So the
; level is stashed in a spare writable control register across the slot
; (`WCTL PM_ADDR, R0` in the head, `RCTL R0, PM_ADDR` in the tail) -- the
; same storage trick the DR 0013 boot loader uses with `UIO_DIR`, and
; PM_ADDR is otherwise untouched here (this program reads no table). The
; ISA has no ADD immediate, so `+ 5` is `ADD R0, R1` five times with
; R1 = 1.
;
; How the two halves are counted without a slot counter. No register is
; free inside a slot for one: R1 is the pin mask, R0 the level, R2 the
; transient pin image, R3 the bit counter. Instead each half loop of 256
; slots terminates on the pattern itself: the last of the tail's five
; `ADD`s sets the Z flag exactly when the level returns to 0 -- which
; happens only after slots 256 and 512. Copy A's tail is `BNZ chan_a`
; (next slot) with a fall-through into copy B's head; copy B's tail is
; `BNZ chan_b` with a fall-through `JMP universe` that starts the next
; BREAK. Taken or fallen, the `BNZ` costs one cycle and each path then
; passes exactly one instruction (`XOR` or `JMP`) before the next OUT, so
; the slot pitch is 400 cycles on every path. A slot counter that wrapped
; at 8 bits cannot hide in this structure: the loop cannot leave early on
; a count, and the bench decodes all 512 slots plus the following BREAK.
;
; Registers: R1 = 0x01 (the TX pin mask of DR 0010's dmx512 role on
; uo_out[0], the idle level, the bit-isolation mask and the +1 step), R0
; the channel level (reloaded from PM_ADDR each tail), R2 the transient
; pin image, R3 the bit counter, which is 0 at every slot head and at the
; BREAK image by loop exit. The other seven uo_out bits are driven 0 by
; construction: every OUT writes 0x00 or 0x01.
;
; All microsecond figures are arithmetic at target-spec row 4's
; **unconfirmed** 50 MHz core clock (STA against this core is blocked,
; `verification/records/sta-corner-sweep/`), the same stance as
; `uart_tx.asm`: the claim this program and its bench make is the cycle
; count, and the baud/us reading of it is conditional on row 4.
;
; Lint. The assembler reports exactly two data-dependent-branch warnings,
; the `BNZ` of each half loop's tail: the flags come from an `ADD` over R0
; as reloaded through `RCTL PM_ADDR`, and the linear taint scan cannot see
; through a branch-target label, so it treats the control-register stash
; as unknown. The taint cannot actually enter: the program executes no
; `IN` at all (nothing is pin-sampled), and PM_ADDR is written only by
; this same loop one instruction after the stash. The warning is the cost
; of the storage trick, not a data-dependent latency: the branch governs
; slot counting, and the pin timing is all `WAIT` literals.

; ------------------------------------------------------------------ setup
        LDI   R1, 1            ; TX mask (uo_out[0]), idle level, step/mask
        OUT   UO_OUT, R1       ; TX idles HIGH
        WAIT  255              ; 256 cycles of idle before the first BREAK
        XOR   R3, R3           ; R3 = 0: the BREAK / START low pin image

; ------------------------------------------------------- BREAK, then MAB
universe:
        OUT   UO_OUT, R3       ; falling edge: BREAK begins (R3 = 0: from the
                               ; setup, the bit counter, or the JMP path)
        WAIT  255              ; 18 of these
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255
        WAIT  255              ; 18 x 256 = 4,608 cycles, + the OUT that ends
                               ; the low: BREAK = 4,609 cycles >= 4,600
        OUT   UO_OUT, R1       ; rising edge: mark-after-break begins
        WAIT  200              ; 3 of these: 603 cycles
        WAIT  200
        WAIT  200              ; + LDI + the START OUT below: MAB = 605 >= 600
        LDI   R0, 0            ; the DMX start code 0x00 (R3 still 0)

; ------------------------------------------ start code as one 8N2 slot
        OUT   UO_OUT, R3       ; START bit (anchor)
        WAIT  194              ; 195; + WCTL + LDI + MOV + AND + OUT -> +200
        WCTL  PM_ADDR, R0      ; 1: stash the byte (0x00) across the slot
        LDI   R3, 8            ; 1: the data-bit counter (assemble-time literal)
sc_bit:
.cyclesec dmx512_sc_bit
        MOV   R2, R0           ; isolate next bit
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        SUB   R3, R1           ; R3 stays the counter: the image lives in R2
        WAIT  193              ; 194: pads the body to exactly 200 cycles
        BNZ   sc_bit
.endcyclesec
        WAIT  1                ; 2: stop 1 lands 200 cycles after D7
        OUT   UO_OUT, R1       ; stop bit 1 (high)

; --------------------- enter the channel slots: 400 cycles to slot 1's START
        WAIT  198              ; 199
        WAIT  198              ; 199: 1 + 199 + 199 + 1 (chan_a's XOR) + OUT
        ; R0 is already the first channel level: the start code 0x00 left it
        ; at 0, which is level 1 of the pattern (slot n carries 5(n-1) mod 256)

; ================== channel slots 1..256 (pattern period 1) ==================
; Slot head entry invariant: R3 = 0 (the counter's exit value on every
; path), and the head's START OUT lands exactly 400 cycles after the
; previous slot's stop 1.
chan_a:
        XOR   R3, R3           ; 1  START image (clears the tail's step)
        OUT   UO_OUT, R3       ; 1  START bit (anchor)
        WAIT  194              ; 195 -> D0 at +200 as in the start code
        WCTL  PM_ADDR, R0      ; 1  stash the level across the slot
        LDI   R3, 8            ; 1  the data-bit counter
chan_a_bit:
.cyclesec dmx512_bit_a
        MOV   R2, R0
        AND   R2, R1
        OUT   UO_OUT, R2
        SHF   R0, RIGHT
        SUB   R3, R1
        WAIT  193
        BNZ   chan_a_bit
.endcyclesec
        WAIT  1
        OUT   UO_OUT, R1       ; stop 1 at anchor + 1800
.cyclesec dmx512_slot_tail_a
        WAIT  194              ; 195
        WAIT  195              ; 196 -> 391
        RCTL  R0, PM_ADDR      ; 1  the level back from PM_ADDR
        ADD   R0, R1           ; 1  level += 1, five times: + 5 (no ADD imm)
        ADD   R0, R1           ; 1
        ADD   R0, R1           ; 1
        ADD   R0, R1           ; 1
        ADD   R0, R1           ; 1  Z on this last one iff level wrapped to 0
        BNZ   chan_a           ; 1  next slot (Z clear); when Z is set it falls
.endcyclesec               ;  through into chan_b's XOR -- one cycle either
                           ;  way, then one XOR, then the OUT: pitch 400

; ================= channel slots 257..512 (pattern period 2) =================
; Identical shape; the level continues across the boundary and wraps to 0
; again only after slot 512. The exit path carries `JMP universe` instead
; of falling into an XOR (the BREAK image is already R3 = 0).
chan_b:
        XOR   R3, R3           ; 1  START image
        OUT   UO_OUT, R3       ; 1  slot 257 START, 400 cycles after stop 256
        WAIT  194
        WCTL  PM_ADDR, R0
        LDI   R3, 8
chan_b_bit:
.cyclesec dmx512_bit_b
        MOV   R2, R0
        AND   R2, R1
        OUT   UO_OUT, R2
        SHF   R0, RIGHT
        SUB   R3, R1
        WAIT  193
        BNZ   chan_b_bit
.endcyclesec
        WAIT  1
        OUT   UO_OUT, R1
.cyclesec dmx512_slot_tail_b
        WAIT  194              ; 195
        WAIT  195              ; 196 -> 391
        RCTL  R0, PM_ADDR      ; 1
        ADD   R0, R1           ; 1  level += 5 across the five ADDs; the last
        ADD   R0, R1           ; 1  one sets Z iff the level wrapped to 0
        ADD   R0, R1           ; 1
        ADD   R0, R1           ; 1
        ADD   R0, R1           ; 1  (after slot 512: 251 + 5 = 0)
        BNZ   chan_b           ; 1  next slot (Z clear)
        JMP   universe         ; 1  fall-through: universe complete; the
.endcyclesec               ;     BREAK's fall lands 1 + 391 + 1 + 5 + 1 + 1
                           ;     = 400 cycles after stop 1, exactly on the
                           ;     end of slot 512's stop 2
