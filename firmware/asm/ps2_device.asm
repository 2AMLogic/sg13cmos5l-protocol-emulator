; ps2_device.asm -- PS/2 keyboard/mouse DEVICE (target-spec row 13, stretch
; column, issue #235; the protocol choice is the dated note of 2026-10-11 in
; DR 0018, made after DR 0017's ISA freeze at merge commit
; 1696045bfa1a33f93c95a5bf6c29b05f4ea0d734).
;
; Firmware only: base DR 0001 instructions plus DR 0012's runtime pin mode
; (UIO_OD) and PM_ADDR read/write used as a one-byte scratch store. No DR 0015
; primitive and no hardware assist of any kind.
;
; The role. The device owns the clock but not the bus: the host can inhibit it
; (CLK held low) or ask to send (CLK low, DATA low, CLK released). Both lines
; are open-drain with pull-ups; this program only ever pulls a line low or
; releases it. Source of the numbers: Chapweske, "The PS/2 Mouse/Keyboard
; Protocol" (see DR 0018's note). Pins (the standard I2C Pmod row, which
; carries pull-ups): CLK = uio[2] (mask 0x04), DATA = uio[3] (mask 0x08).
; Writing a 1 to a bit of UIO_OUT releases that line, a 0 pulls it low
; (UIO_OD = 0x0C).
;
; What it does. After reset it sends the BAT completion code 0xAA to the
; host. Then it waits for a host request to send. Each byte the host sends is
; echoed back as a device-to-host frame (0xFE, "resend", if the host's parity
; or stop bit was wrong), after the ACK. A transmission that the host inhibits
; before its last clock is abandoned (DATA released) and retried from the top
; once CLK has been high for 50 us. The one pending byte lives in PM_ADDR
; (RCTL/WCTL, 1 cycle each). A newer response replaces an unsent older one;
; there is no 16-byte buffer.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle except
; WAIT imm8 = imm8 + 1). At target-spec row 4's target clock of 50 MHz
; (unconfirmed) one cycle is 20 ns. Every wait below is a loop of
; `WAIT 246` (250 cycles an iteration with the shift, the OR that sets Z --
; SHF writes C only -- and the branch) on a counter that SHF walks to zero,
; so no register beyond R3 is needed:
;
;   phase                         cycles          at 20 ns        limit (Chapweske)
;   CLK low (device pulse)        2,006..2,007    40.12..40.14 us  30..50 us
;   CLK high (rise to fall)       2,035..2,083    40.70..41.66 us  30..50 us
;   data change after a rise      1,018..1,035    20.36..20.70 us  >= 5 us
;   data change before the fall   1,017           20.34 us         5..25 us
;   hold-off before a frame       about 4,016     about 80.3 us    >= 50 us of CLK high
;
; Those are the ranges the bench measured on the RTL (nanoseconds, from the
; edges on the pads); the bench grades the pads, and this table is a reading
; aid, not the evidence.
;
; Registers.
;   transmit: R0 = the byte, shifted right (re-read from PM_ADDR for parity)
;             R1 = the pin image of the current bit with CLK low (data << 3)
;             R2 = pulses remaining (11 .. 1)
;             R3 = scratch
;   receive:  R0 = the byte, shifted in at bit 7
;             R1 = the pin image with CLK low: 0x48 (DATA released, bit 6 is
;                  the "receive" flag)
;             R2 = pulses remaining (11 .. 1), R3 = scratch
;             PM_ADDR holds the parity bit between the 9th and 10th bit, then
;             the response byte
; The pin image only matters in bits 2 and 3 (UIO_OD covers those two pins).
; Bit 6 of R1 is the direction flag the shared pulse tail tests; transmit
; images are 0x00 and 0x08, so it is clear there.
;
; Only bits 2 and 3 of the images written to UIO_OUT reach a pad: UIO_OD
; enables those two pins and no others (bits 6 and 7 of R1 are program state).
; The branches on IN-sampled data are the protocol's own handshakes (wait for
; the host, abort on inhibit); the assembler's lint says so for each one, and
; the bench lists them.

; ------------------------------------------------------------- setup
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; both lines released ...
        WCTL  UIO_OD, R3       ; ... then open-drain on CLK and DATA
        LDI   R0, 0xAA
        WCTL  PM_ADDR, R0      ; the pending byte: BAT completion

; ---------------------------------- wait until the bus is free to talk
; Bus state v = DATA << 1 | CLK. v = 3: idle. v = 1: host request to send.
; v = 0 or 2: CLK held low, the host is inhibiting.
tx_wait:
        LDI   R2, 200          ; polls of "idle" in a row (about 20 cycles each)
tw_poll:
        IN    R3, UIO_IN
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; bit 3 -> 7, bit 2 -> 6
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT        ; R3 = DATA << 1 | CLK
        OR    R3, R3           ; SHF leaves Z alone: set it
        BZ    tx_wait          ; v = 0
        LDI   R1, 1
        SUB   R3, R1
        BZ    rx_start         ; v = 1: request to send
        SUB   R3, R1
        BZ    tx_wait          ; v = 2: CLK low, inhibited
        SUB   R2, R1
        BNZ   tw_poll          ; v = 3: count it
; ---------------------------------- the bus was idle long enough: transmit
        RCTL  R0, PM_ADDR
        LDI   R1, 0
        LDI   R2, 11

; ------------------------- transmit: choose the data bit for this pulse
tx_action:
        LDI   R3, 11
        SUB   R3, R2
        BZ    tx_start
        LDI   R3, 2
        SUB   R3, R2
        BZ    tx_par
        LDI   R3, 1
        SUB   R3, R2
        BZ    tx_stop
        LDI   R3, 1            ; data bit: bit 0 of R0, moved to bit 3
        AND   R3, R0
        ADD   R3, R3
        ADD   R3, R3
        ADD   R3, R3
        MOV   R1, R3
        SHF   R0, RIGHT
        JMP   pulse
tx_start:
        LDI   R1, 0            ; start bit: DATA low
        JMP   pulse
tx_stop:
        LDI   R1, 8            ; stop bit: DATA released
        JMP   pulse
tx_par:                        ; odd parity: 1 if the byte has an even number of ones
        RCTL  R0, PM_ADDR
        MOV   R1, R0
        MOV   R3, R1
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        XOR   R1, R3
        MOV   R3, R1
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        XOR   R1, R3
        MOV   R3, R1
        SHF   R3, RIGHT
        XOR   R1, R3           ; bit 0 = xor of the byte (even parity bit)
        LDI   R3, 1
        AND   R1, R3
        XOR   R1, R3           ; the odd-parity bit
        ADD   R1, R1
        ADD   R1, R1
        ADD   R1, R1           ; moved to bit 3
        JMP   pulse

; ------------- one clock pulse, shared by both directions (R1 = low image)
; pulse:   CLK high, DATA = this pulse's bit (transmit) or released (receive)
; then ~20 us later: look at CLK (low means the host is inhibiting), pull CLK
; low for ~40 us, release it, and count the pulse.
pulse:
        LDI   R3, 0x04
        OR    R3, R1
        OUT   UIO_OUT, R3      ; CLK stays released; DATA takes this pulse's bit
        LDI   R3, 0x10         ; 4 x 250 cycles
w_mid:  WAIT  246
        SHF   R3, LEFT
        OR    R3, R3           ; SHF leaves Z alone
        BNZ   w_mid
        IN    R3, UIO_IN
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; CLK (bit 2) -> bit 7
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT        ; R3 = CLK
        OR    R3, R3           ; SHF leaves Z alone: set it
        BZ    abort            ; CLK low although released: the host inhibits
fall:
        OUT   UIO_OUT, R1      ; CLK falls (the host reads on this edge)
        LDI   R3, 0x01         ; 8 x 250 cycles
w_low:  WAIT  246
        SHF   R3, LEFT
        OR    R3, R3           ; SHF leaves Z alone
        BNZ   w_low
        LDI   R3, 1
        SUB   R2, R3
        BZ    done             ; that was the last pulse
        LDI   R3, 0x04
        OR    R3, R1
        OUT   UIO_OUT, R3      ; CLK released; DATA keeps this pulse's bit
        LDI   R3, 0x10         ; 4 x 250 cycles
w_high: WAIT  246
        SHF   R3, LEFT
        OR    R3, R3           ; SHF leaves Z alone
        BNZ   w_high
        LDI   R3, 0x40
        AND   R3, R1
        BZ    tx_action        ; flag clear: next transmit pulse
        JMP   rx_action        ; flag set: next receive pulse

; -------------------------- the frame is over (or abandoned): free the bus
done:
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; release both lines
        LDI   R3, 0x40
        AND   R3, R1
        BZ    idle_wait        ; sent: nothing pending
        JMP   tx_wait          ; received: the response is pending
abort:
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; release both lines, DATA included
        LDI   R3, 0x40
        AND   R3, R1
        BZ    tx_wait          ; inhibited while sending: send it again later
        JMP   idle_wait        ; the host abandoned its own frame

; --------------------------------------- nothing pending: wait for the host
idle_wait:
        IN    R3, UIO_IN
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT        ; R3 = DATA << 1 | CLK
        LDI   R1, 1
        SUB   R3, R1
        BNZ   idle_wait        ; wait for v = 1: request to send

; ------------------------------------------------ host to device: receive
; The host has CLK released and DATA low. The device clocks 8 data bits,
; parity and stop (10 pulses, read while CLK is high), then pulls DATA low as
; the ACK on the 11th.
rx_start:
        LDI   R0, 0
        LDI   R1, 0x48         ; CLK low image: DATA released; bit 6 = receive
        LDI   R2, 11
        JMP   fall             ; the first pulse needs no data bit from us

rx_action:                     ; ~20 us into the high phase: read DATA
        IN    R3, UIO_IN
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; DATA (bit 3) -> bit 7
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT        ; DATA in bit 0
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT
        SHF   R3, LEFT         ; R3 = DATA << 7
        LDI   R1, 2
        SUB   R1, R2
        BZ    rx_par           ; the 9th bit is the parity bit
        LDI   R1, 1
        SUB   R1, R2
        BZ    rx_stop          ; the 10th is the stop bit
        LDI   R1, 0x48
        SHF   R0, RIGHT
        OR    R0, R3           ; data bits arrive least significant first
        JMP   pulse
rx_par:
        LDI   R1, 0x48
        WCTL  PM_ADDR, R3      ; keep the parity bit (in bit 7) until the stop bit
        JMP   pulse
rx_stop:
        OR    R3, R3
        BZ    rx_bad           ; the stop bit was 0: framing error
        RCTL  R3, PM_ADDR
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT
        SHF   R3, RIGHT        ; R3 = the parity bit
        MOV   R1, R0
        MOV   R2, R1
        SHF   R2, RIGHT
        SHF   R2, RIGHT
        SHF   R2, RIGHT
        SHF   R2, RIGHT
        XOR   R1, R2
        MOV   R2, R1
        SHF   R2, RIGHT
        SHF   R2, RIGHT
        XOR   R1, R2
        MOV   R2, R1
        SHF   R2, RIGHT
        XOR   R1, R2           ; bit 0 = xor of the data bits
        XOR   R3, R1           ; bit 0 = xor of data and parity: odd means good
        LDI   R2, 1
        AND   R3, R2
        BZ    rx_bad           ; even number of ones: parity error
        WCTL  PM_ADDR, R0      ; good frame: the response is an echo
        JMP   rx_ack
rx_bad:
        LDI   R0, 0xFE         ; bad frame: the response is "resend"
        WCTL  PM_ADDR, R0
rx_ack:
        LDI   R1, 0x40         ; DATA low: the ACK (also while CLK is low)
        LDI   R2, 1
        JMP   pulse
