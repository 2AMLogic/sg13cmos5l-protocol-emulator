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
; Pin map: DR 0010's target plan, the standard Tiny Tapeout SPI Pmod
; (upper row), adopted by issue #155:
;   uio[0] = CS   (active low; driven by this program)
;   uio[1] = MOSI (driven)
;   uio[2] = MISO (peripheral-driven; sampled by IN on uio_in)
;   uio[3] = SCLK (the Pmod's SCK; idles at CPOL; driven)
; The three controller outputs are push-pull through DR 0012's pin-mode
; register: the setup writes the idle image to UIO_OUT and only THEN
; 0x0B (CS|MOSI|SCLK) to UIO_DIR. uio_out resets to 0x00, so enabling
; the drivers first would assert CS for a cycle. Until the WCTL retires
; every uio pin is an input (DR 0012's reset state). MISO stays an input.
; The received byte is still published on uo_out[7:0].
;
; Two bursts per program, both full-duplex (an IN samples MISO every
; bit), both graded by the independent model in
; verification/test_firmware_spi.py:
;   1. ceiling burst: exactly 4 cycles/bit (SCLK = f_clk/4), MOSI
;      byte 0xA5. The write on the sampling edge carries the data
;      bit; the other phase's write is static (MOSI low) -- the model
;      samples only on the mode-correct edges, so the sampled value is
;      the data bit with a half-period of setup.
;   2. functional burst: 10 cycles/bit, MOSI byte 0x3C, slower so
;      the loop can also EXTRACT and ASSEMBLE the received MISO bits
;      (IN + AND + 2 x SHF + SHF + OR per bit; that extraction cannot fit
;      in the 4-cycle ceiling budget). MISO sits on uio bit 2, so the
;      isolated bit takes two right shifts to reach bit 0 before it is
;      ORed into the accumulator. On the earlier plan (MISO on uio bit 0)
;      it took none and the burst ran at 8 cycles/bit; the two extra
;      instructions per bit do not fit in 8. After CS releases, the
;      assembled byte
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
        OUT   UIO_OUT, R2       ; the idle image, BEFORE the drivers are on
        LDI   R3, 0x0B          ; CS|MOSI|SCLK: the pins this program drives
        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]
        WAIT  13                 ; 16 cycles of driven idle before the burst

; --------------------------------------------- burst 1: ceiling rate
; 4 cycles/bit: OUTs land 2 cycles apart (2-cycle half-periods), the
; IN (MISO sample) rides inside the loop at no timing cost.
        LDI   R2, 0x00          ; CS asserted, SCLK still idle
        OUT   UIO_OUT, R2          ; CS falls
        WAIT  3                  ; 4 cycles of CS setup (>= half period)
        LDI   R1, 0x00          ; static image for the trailing phase
.cyclesec spi_mode0_ceil
        LDI   R2, 0x0A          ; bit 0: SCLK active + MOSI 1
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 0)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x08          ; bit 1: SCLK active + MOSI 0
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 1)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x0A          ; bit 2: SCLK active + MOSI 1
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 2)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x08          ; bit 3: SCLK active + MOSI 0
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 3)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x08          ; bit 4: SCLK active + MOSI 0
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 4)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x0A          ; bit 5: SCLK active + MOSI 1
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 5)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x08          ; bit 6: SCLK active + MOSI 0
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 6)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
        LDI   R2, 0x0A          ; bit 7: SCLK active + MOSI 1
        OUT   UIO_OUT, R2          ; leading edge (sampling edge)
        IN    R3, UIO_IN         ; sample MISO (bit 7)
        OUT   UIO_OUT, R1         ; trailing edge (static image)
.endcyclesec
        WAIT  3                  ; 4 cycles of CS hold (>= half period)
        LDI   R2, 0x01          ; CS released, SCLK idle
        OUT   UIO_OUT, R2          ; CS rises
        WAIT  31                 ; 32 cycles between bursts

; ------------------------------------------- burst 2: functional rate
; 10 cycles/bit (OUTs 5 cycles apart): the same full-duplex shape plus
; MISO extraction and assembly -- R0 accumulates the received byte,
; MSB first, and is echoed on uo_out after CS releases. MISO is uio
; bit 2, so the isolated bit is shifted right twice (one SHF in each
; half-period) before it is ORed in at bit 0.
        LDI   R2, 0x00          ; CS asserted, SCLK still idle
        OUT   UIO_OUT, R2          ; CS falls
        WAIT  3                  ; 4 cycles of CS setup
        LDI   R0, 0x00            ; RX accumulator, cleared
        LDI   R1, 0x04            ; MISO mask (uio_in bit 2)
        LDI   R2, 0x08          ; data image for bit 0 (preloaded)
.cyclesec spi_mode0_func
        OUT   UIO_OUT, R2         ; leading edge (data bit 0)
        IN    R3, UIO_IN        ; sample MISO (bit 0)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x08          ; bit 1 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 1)
        IN    R3, UIO_IN        ; sample MISO (bit 1)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x0A          ; bit 2 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 2)
        IN    R3, UIO_IN        ; sample MISO (bit 2)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x0A          ; bit 3 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 3)
        IN    R3, UIO_IN        ; sample MISO (bit 3)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x0A          ; bit 4 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 4)
        IN    R3, UIO_IN        ; sample MISO (bit 4)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x0A          ; bit 5 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 5)
        IN    R3, UIO_IN        ; sample MISO (bit 5)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x08          ; bit 6 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 6)
        IN    R3, UIO_IN        ; sample MISO (bit 6)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x08          ; bit 7 data image (next)
        OUT   UIO_OUT, R2         ; leading edge (data bit 7)
        IN    R3, UIO_IN        ; sample MISO (bit 7)
        AND   R3, R1            ; isolate MISO bit (uio bit 2)
        SHF   R3, RIGHT         ; MISO bit -> bit 1
        LDI   R2, 0x00          ; trailing static image
        OUT   UIO_OUT, R2         ; trailing edge
        SHF   R3, RIGHT         ; MISO bit -> bit 0
        SHF   R0, LEFT          ; RX accumulator <<= 1
        OR    R0, R3            ; RX accumulator |= MISO bit
        LDI   R2, 0x00          ; bit 7 data image (pad, never written)
.endcyclesec
        WAIT  3                  ; 4 cycles of CS hold
        LDI   R2, 0x01          ; CS released, SCLK idle
        OUT   UIO_OUT, R2          ; CS rises
        OUT   UO_OUT, R0          ; ECHO the assembled RX byte on uo_out[7:0]
        WAIT  4                  ; hold the echo past the bench window
        HALT                   ; freeze the core with the echo held
