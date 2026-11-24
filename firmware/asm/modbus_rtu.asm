; modbus_rtu.asm -- Modbus RTU server, 8N2 at 115,207 baud (434 core
; cycles per bit), issue #446 (multi-protocol extra credit, catalog #443).
;
; Firmware on the frozen ISA (DR 0017), no RTL change and no hardware
; peripheral: the UART framing (start, 8 data, two stops), the
; 3.5-character silent interval, the CRC-16/MODBUS and the register map
; are all instructions -- IN, OUT, WAIT, WCTL/RCTL and ordinary ALU ops.
;
; BIT-PERIOD-CYCLES 434
;
; 434 cycles x 20 ns = 8.68 us = 115,207 baud at the unconfirmed 50 MHz
; nominal (+0.006% on 115,200; target-spec row 4, unconfirmed). The issue
; allows 9600-115200 and 8E1 or 8N2 framing; this build takes the top of
; the baud range and the 8N2 framing -- Modbus over Serial Line V1.02
; permits no-parity with two stop bits, and the even-parity bit costs
; this ISA a fifth live value in the transmit loop (byte, mask, image,
; DE constant, parity accumulator -- four registers), which the 256-word
; budget cannot pay: the pre-computed parity fold (17 words per byte
; loop) plus the CRC engine does not fit. 8E1 is the recorded cut.
;
; At 434 cycles the whole per-bit delay is two WAIT
; instructions, so no register is spent on a delay loop: all four
; registers stay live as data (accumulator, mask, scratch, counter) and
; the bit loops LOOP over bytes instead of unrolling -- the word budget
; a 9600-baud build cannot close (a 5,208-cycle bit period costs 21 WAIT
; words per bit slot; eight unrolled receive bits plus eight transmit
; bits overruns the 256-word store before the CRC exists). One baud, one
; framing, one function pair: the claim.
;
; Pins (DR 0010's modbus profile, added by this issue; the catalog row's
; plan), all through an external RS-485 transceiver:
;   RX   ui_in bit 1 (idle HIGH; the uart_rx profile's pad, fed by the
;                   transceiver's R output)
;   TX   uo_out bit 0 (idle HIGH on the line while DE is low; the
;                   uart_tx/dmx512 pad, to the transceiver's D input)
;   DE   uo_out bit 1 (driver enable; high while this server transmits
;                   its response, low while it listens; wired to DE and
;                   /RE together)
;
; Server scope (what the program implements, and what it does not):
;   - slave address 0x11, function 0x03 (read holding registers) and
;     0x06 (write single register), one fixed map of two 16-bit holding
;     registers (addresses 0x0000-0x0001, values DEAD BEEF at load).
;   - 0x03 answers ONLY start 0x0000 count 0x0002 (the whole map, one
;     fixed 9-byte response); 0x06 writes register 0 or 1 and echoes
;     the request (the 0x06 response IS the request).
;   - a request the server does not serve -- any other function code,
;     any other start or count, a register outside 0-1 -- is met with
;     SILENCE: the program re-arms and never responds. (A full Modbus
;     server answers unicast requests it cannot serve with an exception
;     frame; the exception reply is the recorded cut the issue's word
;     fallback names -- see firmware/README.md. A CRC-valid unicast
;     request is never answered with a wrong frame.)
;   - a frame with a bad CRC, or addressed to another slave, is met
;     with silence.
;   - broadcast (address 0x00) is NOT handled: the program listens only
;     for 0x11 (recorded cut).
;   - 8E1 (even parity) is NOT sent: 8N2 is (the framing the issue and
;     the Modbus serial-line spec both allow; the parity fold's register
;     cost is a recorded cut -- see the BIT-PERIOD section).
;   - received frames are a FIXED eight bytes (the length of both
;     supported requests): the program does not parse variable-length
;     frames or enforce the 1.5-character inter-character gap inside a
;     frame (recorded cut). A truncated frame shows up as a CRC or
;     framing failure and is dropped; the receiver re-arms -- and
;     because there is no inter-character timeout, a truncated frame
;     desynchronises the receiver until one further complete frame has
;     been consumed (that phantom frame's CRC fails: silence, then
;     sync). Both stop bits are checked; there is no parity bit to
;     check (the frame CRC carries the frame's integrity).
;
; No data memory exists (DR 0001), so the program memory DR 0012 exposes
; at run time IS the data memory. The serial loader stops at the last
; instruction word, so every data word is written by the program before
; it is read (the code stays below 0xF0 = 240 words):
;
;   0xF0-0xF7   the frame buffer: each of the eight request bytes in
;               the HIGH half of its own word. One byte per word costs
;               buffer words (eight, not four) and buys the addressing:
;               a byte is fetched with one RCTL PM_DATA_HI (which does
;               NOT advance the pointer) followed by one RCTL
;               PM_DATA_LO (a 1-cycle dummy read that returns the
;               written-0 low half and advances), so no half-of-word
;               state exists anywhere -- DR 0012's windowed P1 bytes
;               (CRC_POLY, CRC_STATE) cannot be used as scratch (their
;               reads advance P1's own pointer), UIO_DIR/UIO_OD must
;               stay untouched (they drive uio pads), and PM_ADDR is
;               the working pointer. For a 0x03 response the buffer
;               holds the request's {address, function} in place and is
;               rebuilt with the response -- only after the request has
;               been fully received, CRC-checked, address-checked,
;               dispatched and validated, so no live request byte is
;               ever overwritten. A 0x06 response transmits the request
;               words unchanged.
;   0xF8-0xF9   the tail of a 0x03 response (CRC low, CRC high).
;   0xFC-0xFD   the two holding registers, one 16-bit register per
;               word, high byte first: exactly the word layout Modbus
;               sends. 0x06 writes land here and persist across frames.
;
; The CRC-16/MODBUS (polynomial 0xA001 reflected, init 0xFFFF, no final
; XOR) is computed in SOFTWARE -- the shift/xor loop DR 0015's P1
; primitive implements in hardware; this program never steps the P1
; data path. One engine serves both uses, entered with the byte range
; in PM_ADDR, the byte count in CRC_CFG (a plain round-trip register:
; written values 7 and 8 read back unchanged), the seed 0xFFFF in
; R0 (low) / R2 (high) and the constant 1 in R1:
;
;   per bit:  crc >>= 1 (16 bits);  if (t was crc_low & 1) crc ^= 0xA001
;
; (the polynomial XOR must FOLLOW the shift: a pre-shift XOR would
; compute poly>>1 = 0x5000, not 0xA001 -- the shift distributes over
; XOR. The two paths are separate shift blocks; the engine runs between
; frames, so their unequal lengths are not protocol timing.)
;
;   CHECK covers all eight request bytes: a valid frame leaves the
;     running CRC at exactly 0x0000 (the transmitted CRC bytes ARE the
;     running CRC, low byte first), so the check is two zero tests --
;     no received CRC byte is ever compared -- and the engine stops
;     with PM_ADDR = 0xF8 (even).
;   APPEND covers a built response's seven payload bytes, then writes
;     the state after them (one byte per word: no read-modify-write),
;     and stops with PM_ADDR = 0xF7 (odd).
;   The continuation is therefore PM_ADDR bit 0 at engine exit: even =
;     the check (branch), odd = an append (fall through).
;
; The 16-bit shift across two registers has no carry flag to move R2's
; bit 0 into R0's bit 7 (nothing reads C -- DR 0015's baseline
; finding), so the carry rides 7 SHF LEFTs of a saved copy. The
; conditional polynomial XOR branches on CRC state, never on pin data.
; The engine runs between frames -- after the 3.5-character silence --
; so its path lengths are not protocol timing and are not padded. Its
; bit counter rides LINE_CFG (P2's configuration byte: writing it only
; resets P2's unused line state).
;
; Registers. Receive path: R0 the shift accumulator (bits enter at bit
;   7, shift right -- the first bit lands at bit 0 after eight passes),
;   R1 the constant 2 (the RX pin mask AND the loop's decrement), R2
;   the pin sample, R3 the bit counter (16 down to 0 over eight
;   SUB R3, R1 -- 0 again exactly when the byte is stored, which is the
;   zero the store's dummy halves write). Transmit path: R0 the byte
;   (shifts right to zero), R1 the constant 1, R2 the pin-image scratch
;   and dummy-read target, R3 the constant 2 -- the DE bit, a pure
;   constant through the loop (8N2 sends no parity bit). The engine:
;   R0/R2 the CRC state, R1 the constant 1, R3 scratch.
;
; Timing, all in core cycles (DR 0001: every instruction is 1 cycle
; except WAIT imm8 = imm8 + 1, WCTL PM_DATA_LO 2, RCTL PM_DATA_HI 2 --
; each fixed by the instruction word). Within a transmitted character
; every bit slot is exactly 434 cycles: the .cyclesec sections pin each
; span to the cycle, and nothing in the transmit path branches on pin
; data. The receive path re-anchors on every character's start edge (a
; 3-cycle poll: IN, AND, BNZ -- the same sanctioned start-edge
; handshake uart_rx.asm carries), so drift cannot accumulate across a
; frame: the first data sample lands 1.5 bit periods after the edge
; that released the poll and every later sample is exactly 434 cycles
; after the previous one; nothing between samples branches on the
; sampled data. The assembler's data-dependent-latency lint reports the
; sanctioned handshakes only, each between characters or between frames
; (never between a character's samples): the start-edge poll, the
; stop-bit framing check, the CRC residual tests, the address/function
; dispatch, the request validation branches, and the response-length
; branch -- firmware/README.md tabulates them.
;
; Between the last received character and the first transmitted one the
; program holds the 3.5-character silent interval RTU framing requires
; (3.5 x 11 x 434 = 16,709 cycles, a counted WAIT loop), then spends
; ~2,600 more cycles on the CRC, the address, the dispatch and the
; build: the response's start bit leaves the pad no earlier than ~4.3
; character times after the request's last stop bit -- past the 3.5
; characters the framing requires, far inside any master's response
; timeout.

; ------------------------------------------------------------------ setup
        LDI   R3, 0xFC         ; the register map at 0xFC-0xFD
        WCTL  PM_ADDR, R3
        LDI   R0, 0xDE         ; register 0 = 0xDEAD
        WCTL  PM_DATA_HI, R0
        LDI   R0, 0xAD
        WCTL  PM_DATA_LO, R0   ; commit; PM_ADDR -> 0xFD
        LDI   R0, 0xBE         ; register 1 = 0xBEEF
        WCTL  PM_DATA_HI, R0
        LDI   R0, 0xEF
        WCTL  PM_DATA_LO, R0   ; commit; PM_ADDR -> 0xFE

; ------------------------------------------------------------- receive
; Eight bytes into the frame buffer at 0xF0, one byte per pass of the
; `poll`..`bcnt` loop: the byte to the high half, the counter's zero to
; the low half (the commit that advances the pointer).
main:   LDI   R1, 2            ; RX mask (ui_in bit 1) and decrement
        LDI   R3, 0xF0
        WCTL  PM_ADDR, R3      ; the frame buffer
poll:   IN    R2, UI_IN        ; start-edge detect (3-cycle handshake;
        AND   R2, R1           ;  a low line reads as a start edge and
        BNZ   poll             ;  fails the stop-bit check: self-healing)
        WAIT  255              ; to the centre of data bit 0:
        WAIT  255              ; AND+BNZ+256+256+135+LDI+IN = 651
        WAIT  134
        LDI   R3, 16           ; bit counter (eight SUB R3, R1 passes)
.cyclesec modbus_rx_bit
rxbit:  IN    R2, UI_IN        ; SAMPLE (bit centre); the whole loop
        AND   R2, R1           ;  body is one bit period: 12 logic
        SHF   R2, LEFT         ;  the sampled bit rides from bit 1
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT         ; .. up to bit 7
        SHF   R0, RIGHT        ; make room
        OR    R0, R2           ; insert (first bit ends at bit 0)
        SUB   R3, R1           ; count -= 2; Z on the eighth pass
        WAIT  255              ;  + 256 + 166 = 434 (IN-to-IN span =
        WAIT  165              ;  the body: the IN is inside)
        BNZ   rxbit
.endcyclesec
        IN    R2, UI_IN        ; first stop-bit SAMPLE
        AND   R2, R1
        XOR   R2, R1           ; 0 iff the stop bit read 1
        BNZ   main             ; framing error: drop the frame, re-arm
        WAIT  255              ; 4+256+173+IN = 434
        WAIT  172
        IN    R2, UI_IN        ; second stop-bit SAMPLE
        AND   R2, R1
        XOR   R2, R1
        BNZ   main             ; framing error: drop the frame, re-arm
        WCTL  PM_DATA_HI, R0   ; the byte to the high half
        WCTL  PM_DATA_LO, R3   ; R3 = 0: commit, PM_ADDR advances
        RCTL  R3, PM_ADDR      ; the pointer passes 0xF8 when the
        LDI   R2, 0xF8         ;  eighth byte has committed
        SUB   R3, R2
        BNZ   poll
        ; ---- 3.5 character times of silence: 16,709 cycles
        LDI   R3, 128          ; 64 passes x 258 + 197
sil:    WAIT  255
        SUB   R3, R1           ; R1 = 2 still
        BNZ   sil
        WAIT  196

; ------------------------------------------------- CRC engine (shared)
; `check` covers all eight request bytes (residual 0x0000 on a valid
; frame); the append caller (`eng2`) covers a built response's seven
; payload bytes. The engine's continuation is PM_ADDR bit 0 at exit:
; 0xF8 (even) = the check, 0xF7 (odd) = an append.
check:  LDI   R3, 8
        WCTL  CRC_CFG, R3      ; all eight request bytes (falls through
eng2:   WCTL  CRC_CFG, R3      ;  eng2's identical write, harmless)
eng_seed:
        LDI   R3, 0xF0
        WCTL  PM_ADDR, R3      ; the frame buffer
        LDI   R0, 0xFF         ; the CRC seed 0xFFFF
        LDI   R2, 0xFF
        LDI   R1, 1
eng_b:  RCTL  R3, PM_DATA_HI   ; the byte (the high half of its word)
        XOR   R0, R3           ; crc_low ^= byte
        RCTL  R3, PM_DATA_LO   ; dummy read of the written-0 low half;
        LDI   R3, 8            ;  PM_ADDR advances to the next word
        WCTL  LINE_CFG, R3     ; eight bits
cbit:   MOV   R3, R0
        AND   R3, R1           ; t = crc_low & 1: the shift happens
        BZ    cnp              ;  FIRST (a pre-shift XOR would compute
        ; ---- t = 1: shift, then crc ^= 0xA001  poly 0xA001: low 01,
        ; high A0 -- three LDI/XOR pairs after the carry lands
        MOV   R3, R2           ; carry R2's bit 0 into R0's bit 7:
        SHF   R3, LEFT         ; the saved copy's low bit walks up
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R2, RIGHT        ; crc high >>= 1
        SHF   R0, RIGHT        ; crc low >>= 1
        OR    R0, R3           ; .. plus the carried bit
        LDI   R3, 0x01
        XOR   R0, R3           ; crc_low ^= 01
        LDI   R3, 0xA0
        XOR   R2, R3           ; crc_high ^= A0
        JMP   cbot
cnp:    ; ---- t = 0: the bare shift
        MOV   R3, R2
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R2, RIGHT
        SHF   R0, RIGHT
        OR    R0, R3
cbot:   RCTL  R3, LINE_CFG
        SUB   R3, R1
        WCTL  LINE_CFG, R3
        BNZ   cbit
        RCTL  R3, CRC_CFG      ; one byte fewer to go
        SUB   R3, R1
        WCTL  CRC_CFG, R3
        BNZ   eng_b

; ---------------------------------------------- engine continuations
        RCTL  R3, PM_ADDR      ; bit 0: which caller was this
        AND   R3, R1
        BZ    cmp_crc          ; 0xF8, even: the request check
        ; append: the CRC state after the covered bytes. One byte per
        ; word: two latches and two zero-commits, no read-modify-write.
        LDI   R3, 0
        WCTL  PM_DATA_HI, R0   ; crc_low to word 0xF7
        WCTL  PM_DATA_LO, R3
        WCTL  PM_DATA_HI, R2   ; crc_high to word 0xF8
        WCTL  PM_DATA_LO, R3
        LDI   R2, 9            ; the 0x03 response: 9 bytes

; ------------------------------------------------------- transmit
; One loop, byte count in CRC_CFG. Each character: start (image 0x02),
; eight data bits, two stop bits (image 0x03). DE
; (uo_out bit 1) rises more than a bit time before the first start bit
; and falls half a bit after the last stop bit. Nothing here branches
; on pin data.
tx_go:  WCTL  CRC_CFG, R2      ; the transmit byte count
        LDI   R3, 0xF0
        WCTL  PM_ADDR, R3      ; frame buffer = transmit source
        LDI   R3, 0x03         ; TX high, DE high: driver enabled
        OUT   UO_OUT, R3
        WAIT  255              ; driver-enable setup: 433 cycles, then
        WAIT  176              ;  the fetch (2) before the first OUT
        LDI   R3, 0x02         ; the DE constant for the bit loop
        LDI   R1, 1
tx_b:   RCTL  R0, PM_DATA_HI   ; the byte
        RCTL  R2, PM_DATA_LO   ; dummy read; PM_ADDR advances
        LDI   R2, 8
        WCTL  LINE_CFG, R2     ; the bit counter
        OUT   UO_OUT, R3       ; START bit (0x02: DE, TX low)
.cyclesec modbus_tx_start
        WAIT  255              ; 256+169 = 425, then the next pass's
        WAIT  168              ;  fetch(3: HI=2,LO=1)+LDI+WCTL+3+OUT
.endcyclesec                   ;  = 434 to bit 0's OUT
tx_bl:  MOV   R2, R0
.cyclesec modbus_tx_bit
        AND   R2, R1           ; the data bit
        OR    R2, R3           ; image = DE | bit
        OUT   UO_OUT, R2       ; the whole loop body is one bit period:
        SHF   R0, RIGHT        ;  11 logic + 256 + 166 = 434 (the
        RCTL  R2, LINE_CFG     ;  OUT-to-OUT span = the body: the OUT
        SUB   R2, R1           ;  is inside). R3 stays the pure DE
        WCTL  LINE_CFG, R2     ;  constant: 8N2 sends no parity bit
        WAIT  255
        WAIT  168
        BNZ   tx_bl
.endcyclesec
        ; the eighth bit's own slot ends at the loop's tail (430
        ; cycles); the first stop bit's OUT completes it
.cyclesec modbus_tx_stop1
        LDI   R2, 3            ; the stop-bit image (DE, TX high)
        NOP
        NOP
.endcyclesec
        OUT   UO_OUT, R2       ; STOP bit 1 (0x03): 430+3+1 = 434
.cyclesec modbus_tx_stop2
        WAIT  255              ; 256+177+OUT = 434
        WAIT  176
.endcyclesec
        OUT   UO_OUT, R2       ; STOP bit 2
.cyclesec modbus_tx_stop
        WAIT  255              ; the next character follows at once:
        WAIT  164              ;  256+165+RCTL+SUB+WCTL+BNZ = 425,
        RCTL  R2, CRC_CFG      ;  then fetch(3)+LDI+WCTL+3+OUT(1) =
        SUB   R2, R1           ;  434: each stop bit lasts a full
        WCTL  CRC_CFG, R2      ;  period before the next edge
        BNZ   tx_b             ;  (gap << 1.5 characters)
.endcyclesec
        WAIT  210              ; driver-disable hold ~= half a bit
        LDI   R2, 1            ; idle image: TX high, DE low
        OUT   UO_OUT, R2
        JMP   main

cmp_crc:OR    R0, R2           ; a valid frame leaves the residual at
        BNZ   main             ;  exactly 0x0000 (the transmitted CRC
                                ;  bytes ARE the running CRC, low byte
                                ;  first) -- bad CRC: silence, re-arm
        ; ---- address: 0x11 only (broadcast is a recorded cut)
        LDI   R3, 0xF0
        WCTL  PM_ADDR, R3
        RCTL  R3, PM_DATA_HI   ; the address byte
        LDI   R2, 0x11
        SUB   R3, R2
        BNZ   main             ; not ours: silence, re-arm
        RCTL  R2, PM_DATA_LO   ; dummy advance to the function's word
        ; ---- dispatch on the function code
        RCTL  R3, PM_DATA_HI   ; the function byte (word 0xF1)
        RCTL  R2, PM_DATA_LO   ; advance: 0x03/0x06 read words 0xF2..
        LDI   R2, 3
        SUB   R3, R2
        BZ    b03
        SUB   R3, R2           ; fc - 6
        BZ    b06
        JMP   main             ; any other function: silence

; -------------------------------------------------- 0x03 read request
; PM_ADDR stands on 0xF2 (the dispatch advanced past the function).
b03:    RCTL  R3, PM_DATA_HI   ; start high (byte 2, word 0xF2)
        RCTL  R0, PM_DATA_LO   ; advance (R0 dead: the CRC checked)
        RCTL  R2, PM_DATA_HI   ; start low (byte 3, word 0xF3)
        OR    R3, R2           ; start high | start low
        RCTL  R0, PM_DATA_LO   ; advance
        RCTL  R2, PM_DATA_HI   ; count high (byte 4, word 0xF4)
        OR    R3, R2           ; a start outside the map or a count
        BNZ   main             ;  high byte: silence
        RCTL  R0, PM_DATA_LO   ; advance
        RCTL  R2, PM_DATA_HI   ; count low (byte 5, word 0xF5)
        LDI   R3, 2            ; a count this server does not serve:
        SUB   R2, R3           ;  silence
        BNZ   main
        ; build the response in place: the request's first two words
        ; (address, function) ARE the response's first two bytes --
        ; untouched. The count byte 4 goes to word 0xF2, the four map
        ; bytes to words 0xF3-0xF6 (one byte per word, the zero half
        ; committed from R2, which the count SUB just zeroed; the
        ; pointer auto-advances). The CRC append writes 0xF7, 0xF8.
        LDI   R3, 0xF2
        WCTL  PM_ADDR, R3
        LDI   R3, 4            ; the count byte: two registers = four
        WCTL  PM_DATA_HI, R3   ;  data bytes
        WCTL  PM_DATA_LO, R2   ; commit {4, 0}; PM_ADDR -> 0xF3
        LDI   R3, 0xFC         ; map word 0
        WCTL  PM_ADDR, R3
        RCTL  R1, PM_DATA_HI   ; map 0 high
        RCTL  R3, PM_DATA_LO   ; map 0 low (PM_ADDR -> 0xFD)
        LDI   R0, 0xF3
        WCTL  PM_ADDR, R0
        WCTL  PM_DATA_HI, R1   ; map 0 high (word 0xF3)
        WCTL  PM_DATA_LO, R2   ; commit; -> 0xF4
        WCTL  PM_DATA_HI, R3   ; map 0 low (word 0xF4)
        WCTL  PM_DATA_LO, R2   ; commit; -> 0xF5
        LDI   R0, 0xFD         ; map word 1 (the pointer moved)
        WCTL  PM_ADDR, R0
        RCTL  R1, PM_DATA_HI   ; map 1 high
        RCTL  R3, PM_DATA_LO   ; map 1 low (PM_ADDR -> 0xFE)
        LDI   R0, 0xF5
        WCTL  PM_ADDR, R0
        WCTL  PM_DATA_HI, R1   ; map 1 high (word 0xF5)
        WCTL  PM_DATA_LO, R2   ; commit; -> 0xF6
        WCTL  PM_DATA_HI, R3   ; map 1 low (word 0xF6)
        WCTL  PM_DATA_LO, R2   ; commit; -> 0xF7: the CRC continues here
        LDI   R3, 7            ; seven payload bytes
        JMP   eng2

; -------------------------------------------------- 0x06 write request
; PM_ADDR stands on 0xF2 (the dispatch advanced past the function).
b06:    RCTL  R3, PM_DATA_HI   ; register high (byte 2, word 0xF2)
        AND   R3, R3           ; register above 0x0001: silence
        BNZ   main
        RCTL  R2, PM_DATA_LO   ; advance
        RCTL  R2, PM_DATA_HI   ; register low (byte 3, word 0xF3)
        MOV   R0, R2           ; keep the register number
        LDI   R3, 0xFE
        AND   R2, R3           ; zero iff register <= 1
        BNZ   main
        RCTL  R3, PM_DATA_LO   ; advance
        LDI   R1, 0xFC         ; the map word 0xFC + register
        ADD   R1, R0
        RCTL  R3, PM_DATA_HI   ; value high (byte 4, word 0xF4)
        RCTL  R0, PM_DATA_LO   ; advance
        RCTL  R2, PM_DATA_HI   ; value low (byte 5, word 0xF5)
        WCTL  PM_ADDR, R1      ; (no advance: the pointer is rewritten)
        WCTL  PM_DATA_HI, R3   ; the register is written
        WCTL  PM_DATA_LO, R2
        LDI   R2, 8            ; the response IS the request: transmit
        JMP   tx_go            ; the frame buffer, whose CRC checked
