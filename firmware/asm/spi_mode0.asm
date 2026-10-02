; spi_mode0.asm -- bit-banged SPI controller, mode 0 (CPOL=0, CPHA=0)
; (issue #72, the SPI third of #23; target-spec rows 1 and 11).
;
; Implements DR 0001's SPI cycle-budget sketch ("SPI (controller,
; mode 0, SCLK <= f_clk/4)") extended to all four (CPOL, CPHA)
; combinations. At the ceiling rate the SCLK period is exactly 4 core
; cycles (SCLK = f_clk/4), so each phase gets a 2-cycle budget, with
; zero added WAIT -- the same budget the sketch states. The sketch's
; literal 4-instruction loop is not writable in this ISA (its SHF
; comment presumes one shift both assembling the sampled MISO bit and
; advancing the MOSI bit through the port image; the real SHF shifts
; one register, fills with 0, and there is no immediate ALU form), so
; this program keeps the sketch's BUDGET with per-bit LDI immediates
; for the data-bearing phase write and a static register for the
; other phase's write; the IN (the MISO sample) is in the loop, as
; the sketch requires. See the evidence record for the dated ISA
; note this files per #72's acceptance criterion 5.
;
; Pin map (fixed pin-port table, no new port codes: uio_oe stays 0,
; all bidirectional pins remain inputs, so MISO is read on uio_in):
;   uo_out[0] = CS   (active low)
;   uo_out[1] = SCLK (idles at CPOL)
;   uo_out[2] = MOSI
;   uio_in[0] = MISO (peripheral-driven; sampled by IN)
;
; Two bursts per program, both full-duplex (an IN samples MISO every
; bit), both graded by the independent model in
; verification/test_firmware_spi.py:
;   1. ceiling burst: exactly 4 cycles/bit (SCLK = f_clk/4), MOSI
;      byte 0xA5. The write on the sampling edge carries the data
;      bit; the other phase's write is static (MOSI low) -- the model
;      samples only on the mode-correct edges, so the sampled value is
;      the data bit with a half-period of setup.
;   2. functional burst: 8 cycles/bit, MOSI byte 0x3C, slower so
;      the loop can also EXTRACT and ASSEMBLE the received MISO bits
;      (IN + AND + SHF + OR per bit; that extraction cannot fit in the
;      4-cycle ceiling budget). After CS releases, the assembled byte
;      0x5A-expected is echoed on uo_out[7:0] (bench-checked: the
;      echo window reuses uo_out as a readout bus once the burst is
;      over).
;
; Mode timing (Motorola numbering, per verification/reference_models/
; spi.py -- the model is the authority, not this comment):
;   CPOL=0 -> SCLK idles 0; CPHA=0 -> sampling edge is the leading edge.
;   This program drives data on the leading edge (the sampling edge for
;   CPHA=0) and the static image on the trailing edge.
;
; Every trip count and delay here is an assemble-time literal; the
; program is straight-line (no branches at all), so the assembler's
; TOTAL-CYCLES is the exact execution length and nothing branches on
; pin data (DR 0001 "Timing model").

; ---------------------------------------------------------------- setup
        LDI   R2, 0x01          ; CS released, SCLK at CPOL idle
        OUT   UO_OUT, R2
        WAIT  15                 ; 16 cycles of idle before the burst

; --------------------------------------------- burst 1: ceiling rate
; 4 cycles/bit: OUTs land 2 cycles apart (2-cycle half-periods), the
; IN (MISO sample) rides inside the loop at no timing cost.
        LDI   R2, 0x00          ; CS asserted, SCLK still idle
        OUT   UO_OUT, R2          ; CS falls
        WAIT  3                  ; 4 cycles of CS setup (>= half period)
        LDI   R1, 0x00          ; static image for the trailing phase
.cyclesec spi_mode0_ceil
        LDI   R2, 0x06          ; bit 0: SCLK active + MOSI 1
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 0)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x02          ; bit 1: SCLK active + MOSI 0
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 1)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x06          ; bit 2: SCLK active + MOSI 1
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 2)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x02          ; bit 3: SCLK active + MOSI 0
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 3)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x02          ; bit 4: SCLK active + MOSI 0
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 4)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x06          ; bit 5: SCLK active + MOSI 1
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 5)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x02          ; bit 6: SCLK active + MOSI 0
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 6)
        OUT   UO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x06          ; bit 7: SCLK active + MOSI 1
        OUT   UO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 7)
        OUT   UO_OUT, R1         ; trailing edge (static image)
.endcyclesec
        WAIT  3                  ; 4 cycles of CS hold (>= half period)
        LDI   R2, 0x01          ; CS released, SCLK idle
        OUT   UO_OUT, R2          ; CS rises
        WAIT  31                 ; 32 cycles between bursts

; ------------------------------------------- burst 2: functional rate
; 8 cycles/bit (OUTs 4 cycles apart): the same full-duplex shape plus
; MISO extraction and assembly -- R0 accumulates the received byte,
; MSB first, and is echoed on uo_out after CS releases.
        LDI   R2, 0x00          ; CS asserted, SCLK still idle
        OUT   UO_OUT, R2          ; CS falls
        WAIT  3                  ; 4 cycles of CS setup
        LDI   R0, 0x00            ; RX accumulator, cleared
        LDI   R1, 0x01            ; MISO mask (uio_in bit 0)
        LDI   R2, 0x02          ; data image for bit 0 (preloaded)
.cyclesec spi_mode0_func
        OUT   UO_OUT, R2         ; leading edge (data bit 0)
        IN    R3, UIO_IN        ; sample MISO (bit 0)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x02          ; bit 1 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 1)
        IN    R3, UIO_IN        ; sample MISO (bit 1)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x06          ; bit 2 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 2)
        IN    R3, UIO_IN        ; sample MISO (bit 2)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x06          ; bit 3 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 3)
        IN    R3, UIO_IN        ; sample MISO (bit 3)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x06          ; bit 4 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 4)
        IN    R3, UIO_IN        ; sample MISO (bit 4)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x06          ; bit 5 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 5)
        IN    R3, UIO_IN        ; sample MISO (bit 5)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x02          ; bit 6 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 6)
        IN    R3, UIO_IN        ; sample MISO (bit 6)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x02          ; bit 7 data image (next)
        OUT   UO_OUT, R2         ; leading edge (data bit 7)
        IN    R3, UIO_IN        ; sample MISO (bit 7)
        AND   R3, R1            ; isolate MISO bit
        LDI   R2, 0x00          ; trailing static image
        OUT   UO_OUT, R2         ; trailing edge
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x00          ; bit 7 data image (pad, never written)
.endcyclesec
        WAIT  3                  ; 4 cycles of CS hold
        LDI   R2, 0x01          ; CS released, SCLK idle
        OUT   UO_OUT, R2          ; CS rises
        OUT   UO_OUT, R0          ; ECHO the assembled RX byte on uo_out[7:0]
        WAIT  4                  ; hold the echo past the bench window
        HALT                   ; freeze the core with the echo held
