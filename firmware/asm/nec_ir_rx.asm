; nec_ir_rx.asm -- NEC infrared remote-control RECEIVER, firmware on the
; frozen ISA (issue #488, follow-up to the #448 transmitter; catalog #443).
; No RTL change, no hardware assist: the receiver is IN (pin read), WAIT
; (cycle count), the four ALU ops and DR 0012's PM_DATA_* scratch.
;
; What it receives, forever: the demodulated envelope a 38 kHz
; demodulating receiver module (idle HIGH, active LOW) puts on IR_RX =
; ui_in[4] (DR 0010's nec_ir_rx role). A frame is the leader (9 ms mark +
; 4.5 ms space), 32 bits -- address, ~address, command, ~command, least
; significant bit first -- each a 562.5-us-class mark followed by a
; 562.5-us (0) or 1,687.5-us (1) space, and a final mark. A repeat code
; is the leader, a 2.25 ms space and one bit-class mark.
;
; The decoding rule. Every bit is sampled ONCE, mid-space, 40,781 cycles
; (815.62 us) after the bit's mark ends (the mark end is found by a 3-cycle
; poll, so the sample lands 40,781 + 0..2 cycles after the pin edge):
;
;   sample LOW  -> the next mark is already running -> the space was
;                  0-class -> the bit is 0
;   sample HIGH -> the space is still running       -> the bit is 1
;
; Why 815.62 us and not the ~1.1 ms of the issue text. With every width
; at the +-10% edge of the model's TIMING_TOL_PCT windows at once, a 0's
; next mark runs [506.25, 1012.5] us after the mark ends and a 1's space
; runs at least 1518.75 us. A single sample decodes EVERY +-10% frame
; (including any mix of edges) iff it sits inside [618.75, 1012.5] us --
; 1100 us is past 1012.5 and misreads a 0 whose mark and space are both
; -10%, so the acceptance criterion (edges must decode) forces the
; earlier point; 815.62 us is the interval's midpoint, 3,719 cycles from
; its floor and 4,250 from its ceiling. In cycles: sample 40,781 after
; the observed mark end, decision interval [30,937.5 .. 50,625].
;
; The other three fixed instants (all from the observed edge, 0..2 cycles
; of poll skew on top):
;
;   leader width probe   100,000 cycles after a mark STARTS. LOW = the
;                        mark is still running = leader-class (a bit mark
;                        ends by 61,875; a leader runs at least 405,000);
;                        HIGH = bit-class, skip it and keep hunting.
;   leader/repeat split  125,000 cycles after the leader mark ends. LOW =
;                        a bit-class mark is running = the 2.25 ms repeat
;                        space just ended (every +-10% repeat's mark
;                        covers 125,000: it starts by 123,750 and ends at
;                        126,562 or later); HIGH = the 4.5 ms frame space
;                        (still at least 202,500 to run).
;   silence check         97,266 cycles after each sampled mark ends, on
;                        the 1 path only. Every +-10% 1-space's next mark
;                        covers 97,266 (starts by 93,281, ends at 101,250
;                        or later), so LOW = the frame continues; HIGH =
;                        silence -- either a truncated frame or the
;                        trailing silence after the 32nd bit. The check is
;                        the frame's bit counter in disguise (below).
;
; The bit counter is program memory. Each sampled bit is accumulated into
; a byte in R0 (bits enter at bit 7, the accumulator shifts right, the
; first bit lands at bit 0 after 8 shifts -- the uart_rx recipe) and the
; PARTIAL byte is spilled to PM[PM_ADDR] with WCTL PM_DATA_LO (which
; commits {HI, LO} and auto-increments PM_ADDR). Word SCRATCH+7 therefore
; holds the complete address, +15 ~address, +23 command, +31 ~command,
; and after the 32nd bit PM_ADDR = SCRATCH+32. The 33rd sample then runs
; into the trailing silence, reads HIGH, spills word 33 and hits the
; silence check -- which now reads HIGH (silence) and leaves the loop
; through `anom`: if PM_ADDR reads SCRATCH+33 the frame was whole,
; otherwise (a mid-frame silence) it was broken and is discarded. No
; register is spent on counting.
;
; Result reporting (the nec_ir_rx_result phase, DR 0010): a valid frame
; writes the ADDRESS byte to uo_out first and the COMMAND byte a few
; cycles later; the last value stays until the next valid frame. A bad
; complement, a repeat code, a truncated frame and a mid-frame silence
; write NOTHING (the frame is discarded at the complement check, or never
; reaches it); a repeat also never alters the previous result. The two
; writes are the only OUTs in the program besides the boot-time clear.
;
; The frame is discarded unless addr ^ ~addr == 0xFF AND cmd ^ ~cmd ==
; 0xFF, the model's own complement rule. Divergence, documented: the
; model latches a frame only after 3,645 us of trailing silence
; (FRAME_SILENCE_MIN_NS), while this program commits at the 33rd sample's
; silence check (97,266 cycles = 1,945.3 us after the final mark ends) --
; a frame driven with 1.95..3.645 ms of trailing silence would be
; accepted here and not latched there. The bench never drives one.
;
; Registers: R1 = 0x10 (the IR_RX mask on ui_in[4]), R3 = 1 (the loop
; decrement, later reused to hold the command byte), R0 the byte
; accumulator / read scratch, R2 the delay counter / sample scratch. The
; only pin read is ui_in bit 4; uo_out is written at boot (0) and twice
; per valid frame. No uio pin is touched and no pin-mode register is
; written.
;
; Cycle accounting. Every delay below is a fixed-trip-count loop plus
; pads, measured from the observing poll's fall-through to the sampling
; IN, so every sample instant is data-independent (the poll's 3-cycle
; granularity is the only jitter). WCTL PM_DATA_LO takes 2 cycles (DR
; 0012) and is counted in the silence-check delay.
;
; Lint. The assembler reports exactly fifteen data-dependent-branch
; warnings: eleven pin-handshake polls (sync0, hl, the width probe, cle,
; the split probe, fb, fe, wh, zh, rep, the silence check), the sample
; branch itself (the pulse-distance encoding's own data dependence, the
; transmitter's `BZ bit0` analogue), and the three readback branches
; (anom's word count, the two complement checks) -- all taken outside the
; mark-end-to-sample window, so no sample instant depends on data
; (DR 0001 'Timing model').

; ------------------------------------------------------------------ setup
        LDI   R1, 0x10        ; the IR_RX mask (ui_in bit 4)
        LDI   R3, 1           ; the loop decrement
        LDI   R0, 0           ;
        OUT   UO_OUT, R0      ; result bus starts at 0
        LDI   R2, 0           ;
        WCTL  PM_DATA_HI, R2  ; every spill word's high byte latched to 0

; -------------------------------- idle: wait for an idle-high line at boot
sync0:  IN    R2, UI_IN       ; a receiver module idles high
        AND   R2, R1
        BZ    sync0

; ------------------------------------------------- hunt a leader-class mark
; Any mark found while hunting is width-probed 100,000 cycles after its
; start: bit-class marks (which end by 61,875) are skipped and the hunt
; resumes; a leader-class mark (which runs at least 405,000) is still low
; at the probe and is waited out to its end.
hunt:   IN    R2, UI_IN       ; wait for a mark (line low)
        AND   R2, R1
        BNZ   hunt
        LDI   R2, 194         ; 194 x 514 = 99,716
.cyclesec nec_ir_rx_hunt_probe
hw:     WAIT  255             ; 256
        WAIT  255             ; 256
        SUB   R2, R3          ; 1
        BNZ   hw              ; 1   514 per iteration
.endcyclesec
        WAIT  255             ; 256  pads: 99,720 + 280 = 100,000
        WAIT  23              ; 24   from the observing IN
        IN    R2, UI_IN       ; still low = the mark is leader-class
        AND   R2, R1
        BNZ   hunt            ; already high = bit-class: skip, hunt on

; --------------------- classify the space: a 4.5 ms frame space or a repeat
cle:    IN    R2, UI_IN       ; wait out the leader mark (line high)
        AND   R2, R1
        BZ    cle
        LDI   R2, 243         ; 243 x 514 = 124,902
.cyclesec nec_ir_rx_split_probe
cw:     WAIT  255             ; 256
        WAIT  255             ; 256
        SUB   R2, R3          ; 1
        BNZ   cw              ; 1   514 per iteration
.endcyclesec
        WAIT  92              ; 93   124,907 + 93 = 125,000
        IN    R2, UI_IN       ; low = a bit mark is running = repeat space
        AND   R2, R1
        BZ    rep             ; high = the frame's leader space

; ---------------------------------------------------------- frame: bit 0 on
fb:     IN    R2, UI_IN       ; wait for bit 0's mark (line low)
        AND   R2, R1
        BNZ   fb
fe:     IN    R2, UI_IN       ; wait out the mark (line high)
        AND   R2, R1
        BZ    fe
        LDI   R2, 128         ; SCRATCH: the spill region, 33 words
        WCTL  PM_ADDR, R2
        LDI   R0, 0           ; byte accumulator, bits enter at bit 7

; ------------------------------------------------------- the 32 bits (x33)
loop:   LDI   R2, 158         ; 158 x 258 = 40,764
.cyclesec nec_ir_rx_sample_wait
sd:     WAIT  255             ; 256
        SUB   R2, R3          ; 1
        BNZ   sd              ; 1   258 per iteration
.endcyclesec
        WAIT  11              ; 12   2+1+40,764+12+1 = 40,781 from the IN
        IN    R2, UI_IN       ; SAMPLE mid-space: low = 0, high = 1
        AND   R2, R1
        BZ    bit0

; bit = 1: enter it at bit 7, spill, then the silence check at +97,266
        SHF   R2, LEFT        ; 0x20
        SHF   R2, LEFT        ; 0x40
        SHF   R2, LEFT        ; 0x80
        SHF   R0, RIGHT       ; make room at bit 7
        OR    R0, R2          ; the bit enters
        WCTL  PM_DATA_LO, R0  ; spill the partial byte (2 cycles); PM_ADDR++
        LDI   R2, 218         ; 218 x 258 = 56,244
.cyclesec nec_ir_rx_silence_wait
an:     WAIT  255             ; 256
        SUB   R2, R3          ; 1
        BNZ   an              ; 1   258 per iteration
.endcyclesec
        WAIT  228             ; 229  10+56,244+229+1 = 56,485 after the
                               ;      sample: 40,781 + 56,485 = 97,266
        IN    R2, UI_IN       ; high = silence: the frame ended or broke
        AND   R2, R1
        BNZ   anom            ; low = the next mark runs: the frame lives
wh:     IN    R2, UI_IN       ; wait out the running mark (line high)
        AND   R2, R1
        BZ    wh
        JMP   loop

; bit = 0: the sample sat inside the next mark; enter the 0 and wait it out
bit0:   SHF   R0, RIGHT       ; make room; the 0 enters as nothing
        WCTL  PM_DATA_LO, R0  ; spill the partial byte; PM_ADDR++
zh:     IN    R2, UI_IN       ; wait out the running mark (line high)
        AND   R2, R1
        BZ    zh
        JMP   loop

; ------------------------------------------------- a repeat: no result write
rep:    IN    R2, UI_IN       ; the repeat's bit mark is running
        AND   R2, R1
        BZ    rep             ; wait it out
        JMP   hunt            ; then hunt the next leader; uo_out untouched

; ------------------------------------------- frame end: count, check, report
anom:   RCTL  R2, PM_ADDR     ; SCRATCH + words spilled (33 = whole frame)
        LDI   R1, 161         ; SCRATCH + 33
        SUB   R2, R1
        BNZ   resync          ; broken frame: discard, write nothing
        LDI   R2, 135         ; SCRATCH + 7: the address byte
        WCTL  PM_ADDR, R2
        RCTL  R0, PM_DATA_HI
        RCTL  R0, PM_DATA_LO  ; R0 = addr
        LDI   R2, 143         ; SCRATCH + 15: the inverted address byte
        WCTL  PM_ADDR, R2
        RCTL  R2, PM_DATA_HI
        RCTL  R2, PM_DATA_LO  ; R2 = ~addr
        MOV   R1, R0          ; R1 = addr (kept for the result write)
        XOR   R0, R2          ; addr ^ ~addr
        LDI   R2, 0xFF
        XOR   R0, R2          ; zero iff the pair is complementary
        BNZ   resync          ; bad complement: discard, write nothing
        LDI   R2, 151         ; SCRATCH + 23: the command byte
        WCTL  PM_ADDR, R2
        RCTL  R0, PM_DATA_HI
        RCTL  R0, PM_DATA_LO  ; R0 = cmd
        LDI   R2, 159         ; SCRATCH + 31: the inverted command byte
        WCTL  PM_ADDR, R2
        RCTL  R2, PM_DATA_HI
        RCTL  R2, PM_DATA_LO  ; R2 = ~cmd
        MOV   R3, R0          ; R3 = cmd (kept for the result write)
        XOR   R0, R2
        LDI   R2, 0xFF
        XOR   R0, R2
        BNZ   resync          ; bad complement: discard, write nothing
        OUT   UO_OUT, R1      ; RESULT write 1: the ADDRESS byte
        OUT   UO_OUT, R3      ; RESULT write 2: the COMMAND byte
        JMP   resync

; The discard/report paths above leave R1 and R3 holding readback
; scratch (SCRATCH+33, the address/command bytes); hunt's polls and delay
; loops need the mask and the unit decrement back before they run.
resync: LDI   R1, 0x10
        LDI   R3, 1
        JMP   hunt
