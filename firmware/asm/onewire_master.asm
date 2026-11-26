; onewire_master.asm -- 1-Wire (Dallas/Maxim) bus MASTER speaking to one
; DS18B20 temperature sensor (multi-protocol extra credit, issue #447; the
; catalog is #443). Firmware only: DR 0001 instructions plus DR 0012's
; runtime pin mode (UIO_OD) and PM_ADDR as a one-byte scratch cell, exactly
; the ps2_device.asm idiom. No DR 0015 primitive (the CRC is software
; shift/xor), no RTL change, no ISA change (frozen, DR 0017).
;
; The bus. One open-drain DQ line with an external pull-up: DQ = uio[3]
; (mask 0x08), the I2C Pmod's SDA position, the row that carries pull-ups
; (DR 0010's `onewire` profile: UIO_DIR 0x00, UIO_OD 0x08). Writing 1 to
; the bit releases the line, 0 pulls it low. The DS18B20 hangs on it with a
; 4.7 kOhm pull-up to Vdd; no transceiver, no optocoupler (named in
; firmware/README.md's 1-Wire section).
;
; What it does, in order (single-drop, standard speed, DS18B20 datasheet):
;   1. reset pulse (>= 480 us low) + presence detect; nobody home -> status
;      2 on uo_out, halt.
;   2. Read ROM (0x33): 8 bytes, Dallas CRC-8 accumulated in firmware;
;      bad CRC -> status 3, halt.
;   3. reset, Skip ROM (0xCC) + Convert T (0x44), then read-time-slot poll
;      until the device releases a 1 (the real part's 750 ms conversion is
;      not simulated; the bench's model holds 0 for a configured few slots).
;   4. reset, Skip ROM (0xCC) + Read Scratchpad (0xBE): 9 bytes, CRC-8;
;      bad CRC -> status 4, halt.
;   5. status 1 (ok), halt.
; Every received byte is published on uo_out as it completes (the result
; convention of the I2C/SPI programs), so the bench captures the ROM, the
; scratchpad (temperature = bytes 0 and 1) and then the final status byte.
;
; CRC-8, Dallas/Maxim (x^8 + x^5 + x^4 + 1, reflected poly 0x8C, init 0),
; Maxim AN27's algorithm, computed incrementally: 1-Wire bits arrive LSB
; first and the reflected CRC eats them LSB first, so each wire bit updates
; the CRC the moment it is sampled: fb = (crc & 1) ^ bit; crc >>= 1;
; crc ^= 0x8C if fb. The two read loops below carry crc in R2 and update it
; inline, so no byte loop of its own exists.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle except
; WAIT imm8 = imm8 + 1). Every wall-clock figure is arithmetic at
; target-spec row 4's target 50 MHz clock (unconfirmed): 1 cycle = 20 ns.
; Long waits are `WAIT 246` loops at 250 cycles an iteration (WAIT 247 +
; LDI + SUB + BNZ); the 60 us-class delays inside the write engine are
; unrolled `WAIT 255` so the write engine never touches R2 (the phase
; register its tail dispatches on). Datasheet numbers (DS18B20 "1-Wire
; standard speed"): reset low >= 480 us, presence sampled at 70 us after
; release, write-1 low 1..15 us, write-0 low 60..120 us, slot >= 60 us with
; >= 1 us recovery, read slot sampled <= 15 us after the falling edge.
;
;   quantity                cycles          at 20 ns       DS18B20 limit
;   reset low               24,002          480.04 us      >= 480 us
;   presence sample         3,502           70.04 us       inside 15..60+60..240 us
;   reset window (release)  ~24,100         ~482 us        >= 480 us
;   write-1 low             ~102            ~2.04 us       1..15 us
;   write-0 low             ~3,077          ~61.5 us       60..120 us
;   write-1 slot            ~3,019          ~60.4 us       >= 60 us + >= 1 us rec
;   write-0 slot            ~3,332          ~66.6 us       >= 60 us + >= 1 us rec
;   read low                ~99             ~1.98 us       >= 1 us, < 15 us
;   read sample point       ~449            ~8.98 us       <= 15 us after fall
;   read slot total         ~3,218          ~64.4 us       >= 60 us + >= 1 us rec
; Those are static accounting from DR 0001's opcode table; the bench
; measures the pads and grades every edge against the datasheet's numbers.
;
; Registers.
;   R0  byte accumulator: write byte / read byte (bits land at 7)
;   R1  constants and temps (never live across a slot)
;   R2  the phase register between engines, the CRC inside the read loops
;   R3  walk counters, timing loop counters, sample temp
; PM_ADDR is a scratch cell: the write engine's optional second command
; byte, the read loops' remaining-bit counter.
;
; The assembler's data-dependent-latency lint warns on nine branches; the
; bench asserts the exact list. Four are pin-data handshakes or data-neutral
; skips, each named where it happens:
;   reset:  BNZ rsnop      presence detect (a protocol handshake)
;   poll:   BZ  poll       conversion-done poll (a protocol handshake)
;   read 1: BZ  rd1cn      CRC feedback skip (1 cycle either way)
;   read 2: BZ  rd2cn      CRC feedback skip (1 cycle either way)
; The other five branch on the PM_ADDR bit counter (write engine: BNZ wrtwo;
; each read loop: BNZ rdNchk and BNZ rdNbit). The lint's taint scan is
; linear and forgets stored control state at every label, and the engines
; sit at labels, so PM_ADDR reads back "unknown" to it. Along every real
; path the cell holds a constant the program itself wrote (0 in setup and
; after1, 0x44/0xBE before each pair, 72/64 before each read), so the
; branches are compile-time-constant loop machinery, not pin timing; ps2
; documented the same class for its PM_ADDR byte. No timing budget depends
; on any of the nine.

; ------------------------------------------------------------- setup
        LDI   R3, 0x08
        OUT   UIO_OUT, R3      ; DQ released ...
        WCTL  UIO_OD, R3       ; ... then open-drain on DQ alone
        LDI   R3, 0
        WCTL  PM_ADDR, R3      ; the scratch cell starts at a known 0
        LDI   R2, 1            ; phase 1: first reset
        JMP   reset

; ---------------------- reset + presence (R2 = 1, 3 or 6 on entry)
; Pull DQ low 480 us, release, sample presence at 70 us (low = somebody
; home), pace out the rest of the 480 us reset window, dispatch on R2.
reset:  LDI   R3, 0
        OUT   UIO_OUT, R3      ; DQ low: the reset pulse
        LDI   R3, 96
rsl:    WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   rsl              ; 96 x 250 = 24,000 cycles
        LDI   R3, 0x08
        OUT   UIO_OUT, R3      ; release DQ
        LDI   R3, 14
rsw:    WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   rsw              ; 14 x 250 = 3,500 cycles = 70 us
        IN    R3, UIO_IN
        LDI   R1, 0x08
        AND   R3, R1           ; DQ (bit 3) isolated
        BNZ   rsnop            ; high: no presence pulse
        LDI   R3, 84
rsr:    WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   rsr              ; 84 x 250 = 21,000 cycles: window >= 480 us
        LDI   R3, 1            ; dispatch: R2 = 1 -> after1
        SUB   R2, R3
        BZ    after1
        SUB   R2, R3
        SUB   R2, R3           ; R2 = 3 -> after3
        BZ    after3
        JMP   after6           ; R2 = 6
rsnop:  LDI   R3, 2            ; status 2: no presence
        OUT   UO_OUT, R3
        HALT

; ---------------------- write engine (R2 preserved; R0 = first byte,
; PM_ADDR = second byte or 0 for none)
; Eight slots LSB first; the walk mask in R3 both counts and selects the
; bit, so no shift of R0 is needed. Write 0 holds the line low ~61.5 us,
; write 1 pulls low ~2 us and paces the rest of the ~60 us slot. The long
; delays are unrolled WAIT 255 precisely because R2 must survive.
wrent:  LDI   R3, 1            ; walk mask: bit 0 first (1-Wire is LSB first)
wrbit:  LDI   R1, 0
        OUT   UIO_OUT, R1      ; falling edge: the slot starts
        MOV   R1, R0
        AND   R1, R3           ; this bit
        BNZ   wrone
        WAIT  255              ; ---- write 0: 12 x 256 cycles low
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
        LDI   R1, 0x08
        OUT   UIO_OUT, R1      ; release after ~61.5 us
        WAIT  246              ; recovery ~5 us
        JMP   wrnext
wrone:  WAIT  96               ; ---- write 1: ~2 us low
        LDI   R1, 0x08
        OUT   UIO_OUT, R1      ; release
        WAIT  255              ; rest of the slot: 11 x 256 + 93
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
        WAIT  92
wrnext: SHF   R3, LEFT         ; walk the mask
        OR    R3, R3           ; SHF leaves Z alone: set it
        BNZ   wrbit
        RCTL  R3, PM_ADDR      ; a second byte pending?
        OR    R3, R3
        BNZ   wrtwo
        JMP   wrdisp
wrtwo:  MOV   R0, R3
        LDI   R3, 0
        WCTL  PM_ADDR, R3      ; clear the slot, then send it
        JMP   wrent
wrdisp: LDI   R3, 2            ; dispatch: R2 = 2 -> start the ROM read
        SUB   R2, R3
        BZ    rd1go
        SUB   R2, R3           ; R2 = 4 -> after4
        BZ    after4
        JMP   after7           ; R2 = 7

; ---------------------- conversion-done poll (single use)
; Read time slots until the device answers 1. Each pass is one legal read
; slot; the branch on pin data is the poll handshake.
poll:   LDI   R3, 0
        OUT   UIO_OUT, R3      ; falling edge
        WAIT  96
        LDI   R1, 0x08
        OUT   UIO_OUT, R1      ; release after ~2 us
        WAIT  255              ; sample ~9 us after the falling edge
        WAIT  92               ; (255 + 92: 349 cycles past the release)
        IN    R3, UIO_IN
        AND   R3, R1           ; DQ isolated, nonzero = 1
        MOV   R2, R3
        LDI   R3, 11
polwt:  WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   polwt            ; pace out the rest of the slot
        OR    R2, R2
        BZ    poll             ; 0: still converting (pin handshake)
        JMP   after5

; ---------------------- read engine, used twice (R2 = CRC, R0 = byte)
; PM_ADDR holds the remaining bit count (64 = Read ROM, 72 = scratchpad).
; One loop per wire bit: read slot, sample at ~9 us, shift the bit into R0,
; fold it into the CRC (AN27, incremental), pace the slot, publish each
; finished byte on uo_out. rdent1/rdent2 name the two entries.
rdent1: LDI   R2, 0            ; crc = 0
        LDI   R0, 0
rd1bit: LDI   R3, 0
        OUT   UIO_OUT, R3      ; falling edge: read slot
        WAIT  96               ; ~2 us low
        LDI   R1, 0x08
        OUT   UIO_OUT, R1      ; release the line
        WAIT  255              ; master samples here: ~9 us after the fall
        WAIT  92               ; (255 + 92: 349 cycles past the release)
        IN    R3, UIO_IN
        AND   R3, R1           ; bit << 3
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; bit << 7
        SHF   R0, RIGHT        ; the byte's bits land at 7, shift down
        OR    R0, R3
        MOV   R1, R2           ; ---- CRC: fb = (crc & 1) ^ bit
        LDI   R3, 1
        AND   R1, R3           ; crc & 1
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT         ; to bit 7: fb must XOR, not OR
        LDI   R3, 0x80
        AND   R3, R0           ; bit << 7 again, from the byte
        XOR   R1, R3           ; fb << 7
        SHF   R2, RIGHT        ; crc >>= 1
        BZ    rd1cn            ; fb = 0 (XOR set Z; SHF left it alone)
        LDI   R3, 0x8C
        XOR   R2, R3           ; crc ^= 0x8C
rd1cn:  LDI   R3, 11
rd1wt:  WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   rd1wt            ; pace to a >= 60 us slot
        RCTL  R3, PM_ADDR      ; one bit fewer
        LDI   R1, 1
        SUB   R3, R1
        WCTL  PM_ADDR, R3
        LDI   R1, 7
        AND   R3, R1
        BNZ   rd1chk           ; not a byte boundary
        OUT   UO_OUT, R0       ; publish the finished byte
        LDI   R0, 0
rd1chk: RCTL  R3, PM_ADDR
        OR    R3, R3
        BNZ   rd1bit
        JMP   after2           ; all bits: R2 = CRC over the ROM

rdent2: LDI   R2, 0            ; crc = 0
        LDI   R0, 0
rd2bit: LDI   R3, 0
        OUT   UIO_OUT, R3      ; falling edge: read slot
        WAIT  96               ; ~2 us low
        LDI   R1, 0x08
        OUT   UIO_OUT, R1      ; release the line
        WAIT  255              ; master samples here: ~9 us after the fall
        WAIT  92               ; (255 + 92: 349 cycles past the release)
        IN    R3, UIO_IN
        AND   R3, R1           ; bit << 3
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; bit << 7
        SHF   R0, RIGHT
        OR    R0, R3
        MOV   R1, R2           ; ---- CRC: fb = (crc & 1) ^ bit
        LDI   R3, 1
        AND   R1, R3
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT
        SHF   R1, LEFT         ; to bit 7: fb must XOR, not OR
        LDI   R3, 0x80
        AND   R3, R0
        XOR   R1, R3
        SHF   R2, RIGHT
        BZ    rd2cn
        LDI   R3, 0x8C
        XOR   R2, R3
rd2cn:  LDI   R3, 11
rd2wt:  WAIT  246
        LDI   R1, 1
        SUB   R3, R1
        BNZ   rd2wt
        RCTL  R3, PM_ADDR
        LDI   R1, 1
        SUB   R3, R1
        WCTL  PM_ADDR, R3
        LDI   R1, 7
        AND   R3, R1
        BNZ   rd2chk
        OUT   UO_OUT, R0
        LDI   R0, 0
rd2chk: RCTL  R3, PM_ADDR
        OR    R3, R3
        BNZ   rd2bit
        OR    R2, R2           ; all bits: CRC over the scratchpad
        BZ    scrok
scrbad: LDI   R3, 4            ; status 4: scratchpad CRC error
        OUT   UO_OUT, R3
        HALT
scrok:  LDI   R3, 1            ; status 1: ok
        OUT   UO_OUT, R3
        HALT

; ---------------------- the phase flow between the engines
after1: LDI   R2, 2
        LDI   R0, 0x33         ; Read ROM (PM_ADDR already 0: single byte)
        JMP   wrent
after2: OR    R2, R2           ; ROM CRC == 0?
        BZ    romok
rombad: LDI   R3, 3            ; status 3: ROM CRC error
        OUT   UO_OUT, R3
        HALT
romok:  LDI   R2, 3            ; phase 3: reset before Convert T
        JMP   reset
rd1go:  LDI   R3, 64           ; 8 ROM bytes
        WCTL  PM_ADDR, R3
        JMP   rdent1
after3: LDI   R2, 4
        LDI   R0, 0xCC         ; Skip ROM
        LDI   R3, 0x44         ; Convert T
        WCTL  PM_ADDR, R3
        JMP   wrent
after4: JMP   poll
after5: LDI   R2, 6            ; phase 6: reset before Read Scratchpad
        JMP   reset
after6: LDI   R2, 7
        LDI   R0, 0xCC         ; Skip ROM
        LDI   R3, 0xBE         ; Read Scratchpad
        WCTL  PM_ADDR, R3
        JMP   wrent
after7: LDI   R3, 72           ; 9 scratchpad bytes
        WCTL  PM_ADDR, R3
        JMP   rdent2
