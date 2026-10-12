; spi_mode0_burst3.asm -- bit-banged SPI controller, mode 0 (CPOL=0,
; CPHA=0), THREE bytes clocked under ONE chip-select assertion
; (issue #286; the multi-byte-burst caveat of target-spec row 11).
;
; Every other committed SPI program clocks one byte per CS-low window.
; Real peripherals (flash reads, ADCs, displays) clock several bytes
; under one CS, and the byte boundary is where a bit-banged controller
; most plausibly loses the f_clk/4 cadence (reloading the MOSI byte, loop
; overhead). This program is the byte-boundary evidence, core alone: no
; peripheral hardware, the ISA only.
;
; Pin map, setup and idle/CS framing are spi_mode0.asm's (DR 0010 SPI Pmod
; plan: uio[0]=CS, uio[1]=MOSI, uio[2]=MISO, uio[3]=SCLK).
;
; Straight-line, NOT a loop (decision, issue #286). At the 4 cycle/bit
; ceiling each bit is exactly LDI (the data image) / OUT (leading edge) /
; IN (MISO sample) / OUT (trailing edge): four instructions, no spare
; slot. A loop would need a per-bit MOSI-bit extraction, a counter and a
; branch, none of which fits in the 4-cycle budget (spi_mode0.asm's
; functional burst needs 10). The byte reload is therefore the next
; byte's first LDI image, and the inter-byte path costs ZERO extra cycles:
; the SCLK half-period across a byte boundary is the same 2 cycles as
; inside a byte. The bench MEASURES that from the captured edges rather
; than assuming it (verification/test_firmware_spi_burst.py).
;
; MOSI bytes 0xA5, 0x3C, 0xD2 (distinct); the bench peripheral drives
; MISO bytes 0xC3, 0x5A, 0x96. MISO is sampled (IN) every bit; at this
; rate there is no room to extract it, so the received bits are judged
; from the pins by the independent model, not echoed on uo_out.
; 3 x 32 = 96 burst cycles in one .cyclesec section.

; ---------------------------------------------------------------- setup
        LDI   R2, 0x01          ; CS released, SCLK at CPOL idle
        OUT   UIO_OUT, R2       ; the idle image, BEFORE the drivers are on
        LDI   R3, 0x0B          ; CS|MOSI|SCLK: the pins this program drives
        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]
        WAIT  13                ; 16 cycles of driven idle before the burst

; ------------------------------------------- one CS window, three bytes
        LDI   R2, 0x00          ; CS asserted, SCLK still idle
        OUT   UIO_OUT, R2       ; CS falls
        WAIT  3                 ; 4 cycles of CS setup (>= half period)
        LDI   R1, 0x00          ; static image for the trailing phase
.cyclesec spi_mode0_burst3
        LDI   R2, 0x0A          ; byte 0 bit 0: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 0 bit 0 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 0 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 0 trailing edge (static image)
        LDI   R2, 0x08          ; byte 0 bit 1: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 0 bit 1 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 1 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 1 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 0 bit 2: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 0 bit 2 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 2 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 2 trailing edge (static image)
        LDI   R2, 0x08          ; byte 0 bit 3: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 0 bit 3 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 3 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 3 trailing edge (static image)
        LDI   R2, 0x08          ; byte 0 bit 4: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 0 bit 4 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 4 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 4 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 0 bit 5: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 0 bit 5 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 5 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 5 trailing edge (static image)
        LDI   R2, 0x08          ; byte 0 bit 6: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 0 bit 6 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 6 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 6 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 0 bit 7: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 0 bit 7 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 0 bit 7 sample MISO
        OUT   UIO_OUT, R1       ; byte 0 bit 7 trailing edge (static image)
        LDI   R2, 0x08          ; byte 1 bit 0: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 1 bit 0 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 0 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 0 trailing edge (static image)
        LDI   R2, 0x08          ; byte 1 bit 1: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 1 bit 1 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 1 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 1 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 1 bit 2: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 1 bit 2 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 2 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 2 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 1 bit 3: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 1 bit 3 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 3 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 3 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 1 bit 4: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 1 bit 4 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 4 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 4 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 1 bit 5: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 1 bit 5 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 5 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 5 trailing edge (static image)
        LDI   R2, 0x08          ; byte 1 bit 6: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 1 bit 6 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 6 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 6 trailing edge (static image)
        LDI   R2, 0x08          ; byte 1 bit 7: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 1 bit 7 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 1 bit 7 sample MISO
        OUT   UIO_OUT, R1       ; byte 1 bit 7 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 2 bit 0: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 2 bit 0 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 0 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 0 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 2 bit 1: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 2 bit 1 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 1 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 1 trailing edge (static image)
        LDI   R2, 0x08          ; byte 2 bit 2: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 2 bit 2 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 2 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 2 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 2 bit 3: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 2 bit 3 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 3 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 3 trailing edge (static image)
        LDI   R2, 0x08          ; byte 2 bit 4: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 2 bit 4 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 4 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 4 trailing edge (static image)
        LDI   R2, 0x08          ; byte 2 bit 5: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 2 bit 5 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 5 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 5 trailing edge (static image)
        LDI   R2, 0x0A          ; byte 2 bit 6: SCLK active + MOSI 1
        OUT   UIO_OUT, R2       ; byte 2 bit 6 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 6 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 6 trailing edge (static image)
        LDI   R2, 0x08          ; byte 2 bit 7: SCLK active + MOSI 0
        OUT   UIO_OUT, R2       ; byte 2 bit 7 leading edge (sampling edge)
        IN    R3, UIO_IN        ; byte 2 bit 7 sample MISO
        OUT   UIO_OUT, R1       ; byte 2 bit 7 trailing edge (static image)
.endcyclesec
        WAIT  3                 ; 4 cycles of CS hold (>= half period)
        LDI   R2, 0x01          ; CS released, SCLK idle
        OUT   UIO_OUT, R2       ; CS rises
        WAIT  4                 ; hold past the bench window
        HALT                    ; freeze the core
