; boot_rom.asm -- the on-chip boot ROM image (DR 0013 layer 2, issue #138).
;
; This program is not loaded into program memory. It is assembled to
; firmware/build/boot/boot_rom.hex, and firmware/tools/gen_boot_rom.py turns
; that image into rtl/protocol_boot_rom.v, the ROM the core fetches from
; when `rst_n` is released with MODE (ui_in[7]) low. It is ordinary firmware
; in the ordinary ISA: the chip chooses how to load its program with the
; same instructions a protocol uses.
;
; Straps (spec/decision-records/0013-program-loading.md, "Layer 2"), read
; once, from ui_in[6:5], by the first instruction:
;
;   ui_in[6:5]   boot program                               status here
;   00           UART load                                  implemented (issue #139)
;   01           SPI-flash boot                             implemented (issue #140)
;   10           warm start: verify program memory, RUN 0   implemented
;   11           reserved; behaves as 00                    implemented (as 00)
;
; There are no stubs left. Both loaders drive pins (the UART load sets TX
; high and a uio guard, the SPI-flash boot drives the Pmod's CS/SCK/MOSI),
; and both leave the ROM only through `WCTL RUN` after a CRC check. Nothing
; in program memory is fetched before that.
;
; Warm start (strap 10). Signature format (DR 0013 open item 1): word 255
; holds the CRC-16/XMODEM of words 0..254, each word high byte first. The
; check uses DR 0012's one CRC register, PM_CRC, which covers words
; *committed* to program memory and nothing else -- so the loop reads each
; word and commits the same word back to the same address. The array is
; unchanged and PM_CRC ends as the CRC of all 256 words. For this CRC (no
; reflection, no final XOR) the CRC of a message followed by its own CRC,
; high byte first, is zero, and it is zero only then: with s = the CRC of
; words 0..254, the last step leaves ((s xor word255) * x^16) mod P, which
; is zero exactly when word255 == s. So "PM_CRC == 0 after all 256 words"
; is "word 255 equals the CRC of words 0..254".
;
; A signature of 0x0000 is refused before the CRC verdict (issue #168, DR
; 0013 Finding F1). PM_CRC starts at 0x0000 (DR 0012), so 256 zero words are
; their own valid signature; without this check an SRAM that powers up
; all-zero would pass. The SPI-flash boot below refuses the same word for
; the same reason. Here it costs two words, not that path's six: the loop's
; last pass leaves word 255 in R0 (high byte) and R1 (low byte), so it need
; not be read back. A real image whose CRC happens to be 0x0000 (one in
; 65,536) must be given a different last word, e.g. by changing a filler
; word, exactly as firmware/tools/mkflash.py already requires for flash.
;
;   pass    RUN 0, entered with R0-R3 = 0, Z = 0 and C = 0 (the reset
;           values, restored below), PM_ADDR = 0 and PM_CRC = 0x0000. A
;           warm-started program reads BOOT_STATUS = 0x00; a serial-loaded
;           one reads 0x01. The PM_DATA latches hold word 255's bytes.
;   fail    falls through to the UART load below. PM_CRC is left holding
;           the nonzero residue, or 0x0000 if the image was refused for its
;           zero signature; the loader clears it.
;
; Registers in the warm-start loop:
;   R0 = high byte of the word      R2 = word index (0..255, wraps to 0)
;   R1 = low byte of the word       R3 = constant 1
;
; Cycle counts (DR 0001 / DR 0012 latency table), from the first executed
; instruction: the dispatch reaches a stub's HALT or `warm_start` in a fixed
; number of cycles per strap value, and one pass of `warm_loop` is 9 cycles.
; A warm start that passes spends 6 + 4 + 256 * 9 + 2 + 4 + 3 = 2,323 cycles
; before its 2-cycle RUN, so word 0 of the verified program executes exactly
; 2,325 cycles after this program's first instruction, whatever the image
; holds (verification/test_boot_rom.py checks that number at the pins).
;
; The assembler's data-dependent-latency lint reports warnings for this
; program, all intended: the two strap branches (which boot program runs is the
; straps' whole purpose), the warm start's two verdict branches, on the
; signature word and on PM_CRC (whether the image runs is the check's whole
; purpose), and in the loaders the branches on received data (the UART load's
; start-edge poll, phase dispatch, handlers and verdicts; the SPI-flash boot's
; own checks). None paces a pin: the warm start drives none; in the UART load
; the samples and the transmitted bits are paced by WAIT literals and a counter
; that never holds pin data, and no branch on a received byte sits between two
; samples.

        IN    R0, UI_IN             ; straps ride ui_in[6:5]
        LDI   R1, 0x60
        AND   R0, R1                ; R0 = straps, in place
        LDI   R1, 0x40
        SUB   R1, R0                ; Z <=> straps == 10
        BZ    warm_start
        LDI   R1, 0x20
        SUB   R1, R0                ; Z <=> straps == 01
        BZ    spi_boot

; Straps 00 and 11, and a warm start whose image fails its check.
;
; UART load (issue #139, DR 0013 layer 2). Tiny Tapeout "option B": RX is
; ui_in[1], TX is uo_out[0]. 8N1, 434 core cycles per bit (115,200 baud at
; the 50 MHz row-4 clock; the cycle count is the claim, any baud figure is
; arithmetic at that unconfirmed clock). Frame, all bytes 8N1:
;
;   0xA5   N-1   2N bytes, each word high byte first   CRC-16/XMODEM, high first
;
; N is 1..256. Each payload word is written through PM_DATA_HI / PM_DATA_LO,
; so PM_CRC covers exactly the words written. The trailer is compared with
; PM_CRC. The reply is 0x06 (accepted) or 0x15 (rejected) followed by PM_CRC,
; high byte first -- the CRC of what was actually written, so a host sees
; what the chip computed. Accepted: hand over and RUN 0. Rejected: go back to
; waiting for 0xA5. A failed image is never run.
;
; No subroutines exist in this ISA, so the receiver is one block, entered
; at rx_next, followed by a dispatch on a phase number kept in R3:
;
;   P0  waiting for 0xA5 (any other byte is ignored: that is the resync)
;   P1  the count byte N-1
;   P2  a payload word's high byte      P3  its low byte (commits the word)
;   P5  the trailer's high byte         P4  the trailer's low byte
;
; The count is kept as N-1 in UIO_DIR and tested for 0 after each commit, so
; N = 256 (count byte 0xFF) needs no ninth bit.
;
; Scratch. The receiver needs R0-R2, so R3 holds the phase and UIO_DIR holds
; a byte (the words still to come minus one, then the trailer's high-byte
; difference, then the verdict). UIO_DIR is a pin-direction register, so it
; is only safe as storage while no uio pin can be driven: with UIO_OD = 0xFF
; and uio_out = 0xFF, uio_oe = (od & ~out) | (~od & dir) = 0 whatever dir
; holds. Both are put back to 0 before RUN. PM_ADDR is storage once the
; payload is in (the reply's byte counter).
;
; Sampling. The start edge is found by a 3-cycle poll of ui_in[1] (the other
; ui_in bits are masked off, never assumed constant). The first sample is
; placed 1.5 bit periods after the edge and the rest exactly 434 cycles
; apart, with nothing that branches on pin data between samples. After the
; eighth sample the loop exits at the middle of the stop bit, so the next
; start edge is at least half a bit away while the handlers run (about 30
; cycles, 4 more for the trailer). Row-10 tolerance: a host that is 2 % fast
; or slow moves the last sample by 0.15 bit.
;
; Transmit. Bit period 434 as well; the line idles high from the first
; instruction here to the RUN. The reply's stop bits are padded past 434.
uart_load:
        LDI   R0, 0xFF
        OUT   UIO_OUT, R0           ; uio_out = 0xFF: with UIO_OD below, no uio pin drives
        WCTL  UIO_OD, R0
        LDI   R0, 0x01
        OUT   UO_OUT, R0            ; TX idle high
        LDI   R3, 0                 ; phase P0
rx_next:
        LDI   R1, 0x02              ; mask for ui_in[1]
rx_poll:
        IN    R2, UI_IN
        AND   R2, R1
        BNZ   rx_poll               ; loop while the line is high
        LDI   R1, 0x80              ; one-hot bit counter
        WAIT  255
        WAIT  255
        WAIT  133                   ; first sample 650 cycles after the poll's IN saw the edge
.cyclesec uart_rx_bit
rx_bit:
        IN    R2, UI_IN             ; SAMPLE
        SHF   R2, RIGHT             ; ui_in[1] -> bit 0 ...
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT
        SHF   R2, LEFT              ; ... -> bit 7, every other bit shifted out
        SHF   R0, RIGHT
        OR    R0, R2                ; byte assembled LSB first
        SHF   R1, RIGHT
        OR    R1, R1                ; Z <=> eight bits are in
        WAIT  255
        WAIT  163
        BNZ   rx_bit                ; 13 + 256 + 164 + 1 = 434 cycles per bit
.endcyclesec
        ; R0 = the byte; the line is at the middle of the stop bit.
        OR    R3, R3
        BZ    h_magic               ; P0
        LDI   R1, 1
        SUB   R3, R1
        BZ    h_count               ; P1
        SUB   R3, R1
        BZ    h_hi                  ; P2
        SUB   R3, R1
        BZ    h_lo                  ; P3
        SUB   R3, R1
        BZ    h_trail_lo            ; P4
        ; P5: the trailer's high byte. Keep its difference from PM_CRC's.
        RCTL  R1, PM_CRC_HI
        XOR   R0, R1
        WCTL  UIO_DIR, R0           ; zero <=> the high byte matches
        LDI   R3, 4
        JMP   rx_next
h_trail_lo:
        RCTL  R1, PM_CRC_LO
        XOR   R0, R1
        RCTL  R1, UIO_DIR           ; the high byte's difference
        OR    R0, R1                ; Z <=> the trailer is PM_CRC
        LDI   R0, 0x15
        BNZ   reply
        LDI   R0, 0x06
reply:
        WCTL  UIO_DIR, R0           ; keep the verdict
        LDI   R1, 0
        WCTL  PM_ADDR, R1           ; reply byte counter
.cyclesec uart_tx_frame
tx:
        LDI   R2, 0x01
        LDI   R3, 0x00
        OUT   UO_OUT, R3            ; START
        LDI   R1, 0x80
        WAIT  255
        WAIT  173
tx_bit:
        MOV   R3, R0
        AND   R3, R2
        OUT   UO_OUT, R3            ; data bit, LSB first
        SHF   R0, RIGHT
        SHF   R1, RIGHT
        OR    R1, R1
        WAIT  255
        WAIT  170
        BNZ   tx_bit                ; 434 cycles from one OUT to the next
        WAIT  1                     ; the loop-back path's MOV and AND
        OUT   UO_OUT, R2            ; STOP
        WAIT  255
        WAIT  170
.endcyclesec
        RCTL  R1, PM_ADDR
        OR    R1, R1
        BNZ   tx_more
        RCTL  R0, PM_CRC_HI         ; the verdict is out: now the CRC
        LDI   R1, 1
        WCTL  PM_ADDR, R1
        JMP   tx
tx_more:
        LDI   R2, 1
        SUB   R1, R2
        BNZ   tx_done               ; counter was 2: all three bytes are out
        RCTL  R0, PM_CRC_LO
        LDI   R1, 2
        WCTL  PM_ADDR, R1
        JMP   tx
tx_done:
        RCTL  R0, UIO_DIR           ; the verdict
        LDI   R1, 0x06
        XOR   R0, R1
        BNZ   rejected
        ; Accepted. Give the program the pins and registers a reset leaves.
        LDI   R0, 0
        OUT   UO_OUT, R0
        WCTL  UIO_DIR, R0           ; dir first, then od, then uio_out: no cycle drives a pin
        WCTL  UIO_OD, R0
        OUT   UIO_OUT, R0
        WCTL  PM_ADDR, R0
        MOV   R1, R0
        MOV   R2, R0
        LDI   R3, 1
        JMP   run_image             ; the warm start's tail: Z, C, R3, then RUN 0
rejected:
        LDI   R3, 0
        JMP   rx_next

h_magic:
        LDI   R1, 0xA5
        XOR   R1, R0
        BNZ   rx_next               ; not 0xA5: still P0
        LDI   R3, 1
        JMP   rx_next
h_count:
        WCTL  UIO_DIR, R0           ; words still to come, minus one
        LDI   R1, 0
        WCTL  PM_ADDR, R1
        WCTL  PM_CRC_LO, R1         ; PM_CRC covers this frame's words only
        LDI   R3, 2
        JMP   rx_next
h_hi:
        WCTL  PM_DATA_HI, R0
        LDI   R3, 3
        JMP   rx_next
h_lo:
        WCTL  PM_DATA_LO, R0        ; 2 cycles: commit the word -> PM_CRC; PM_ADDR++
        RCTL  R1, UIO_DIR
        OR    R1, R1                ; Z <=> no words were left after this one
        LDI   R3, 5                 ; (so the trailer's high byte is next)
        BZ    rx_next
        LDI   R2, 1
        SUB   R1, R2
        WCTL  UIO_DIR, R1
        LDI   R3, 2
        JMP   rx_next

; Strap 10.
warm_start:
        LDI   R2, 0x00              ; word index
        LDI   R3, 0x01
        WCTL  PM_ADDR, R2
        WCTL  PM_CRC_LO, R2         ; clear PM_CRC (the value written is ignored)
.cyclesec warm_word
warm_loop:
        RCTL  R0, PM_DATA_HI        ; 2 cycles: R0 = high byte, low byte latched
        RCTL  R1, PM_DATA_LO        ; R1 = low byte; PM_ADDR++
        WCTL  PM_ADDR, R2           ; back to the word just read
        WCTL  PM_DATA_HI, R0
        WCTL  PM_DATA_LO, R1        ; 2 cycles: commit it unchanged -> PM_CRC; PM_ADDR++
        ADD   R2, R3
        BNZ   warm_loop             ; 256 passes: R2 wraps to 0
.endcyclesec
        OR    R0, R1                ; Z <=> word 255, still in R0/R1, is 0x0000
        BZ    uart_load             ; a zero signature is refused (issue #168)
        RCTL  R0, PM_CRC_HI
        RCTL  R1, PM_CRC_LO
        OR    R0, R1                ; Z <=> PM_CRC == 0 <=> word 255 is the CRC of words 0..254
        BNZ   uart_load             ; not a verified image: never RUN it
        ; Verified. Hand over with the architectural state a reset leaves:
        ; R0 = R1 = R2 = 0 already; restore Z, R3 and C.
run_image:                          ; also entered by the SPI-flash boot: R0-R2 = 0, R3 != 0
        OR    R3, R3                ; R3 = 1: Z = 0
        LDI   R3, 0x00
        SHF   R3, RIGHT             ; shifts out a 0: C = 0
        WCTL  RUN, R2               ; 2 cycles: fetch source -> program memory, PC = 0

; ---------------------------------------------------------------------------
; Strap 01: SPI-flash boot (issue #140, DR 0013 layer 2).
;
; The Tiny Tapeout QSPI Pmod (mole99/qspi-pmod) on the demo board's uio
; header, used as a plain single-bit SPI flash:
;
;   uio[0] = CS0 (flash, active low, output)   uio[1] = MOSI (output)
;   uio[2] = MISO (input)                      uio[3] = SCK  (output)
;
; UIO_DIR = 0x0B makes exactly pins 0, 1 and 3 outputs. Every other uio is
; left an input, so the PSRAM chip selects uio[6] and uio[7] are never
; driven here and sit at the Pmod's pull-up level (deselected); SD2/SD3
; (uio[4], uio[5]) are inputs too and 0x03 does not use them.
;
; One transaction, SPI mode 0 (SCK idles low, the flash samples MOSI on the
; rising edge, the master samples MISO on the rising edge, the flash changes
; MISO after the falling edge): CS0 low, command 0x03 (READ), the 24-bit
; address 0, then 512 bytes (256 words, high byte first, as every image in
; this repository is laid out), then SCK low and CS0 high. A word is
; committed to program memory with PM_DATA_HI / PM_DATA_LO, which also
; runs it through PM_CRC (the one register the warm start uses too).
;
; The image format is the warm start's (DR 0013 open item 1): word 255 is
; the CRC-16/XMODEM of words 0..254, so after all 256 words PM_CRC reads
; 0x0000 exactly when the signature matches. Two outcomes:
;
;   pass    every pin is released (UIO_DIR = 0, UIO_OUT = 0), then the
;           warm start's handover: R0-R3, Z and C at their reset values,
;           PM_ADDR = 0, PM_CRC = 0x0000, and `RUN 0`. BOOT_STATUS reads
;           0x00, as after a warm start.
;   fail    every pin released, then HALT. Nothing is run. The program
;           memory holds whatever the flash sent; that is harmless because
;           it is never executed and the next reset starts from the boot ROM.
;
; Two failures this catches that the CRC alone does not: a flash (or no
; Pmod at all) that answers 0x00 for every byte is 256 zero words, and the
; all-zero image is its own valid signature (Finding F1 of DR 0013). Here
; it is a symptom of a dead MISO line, not an image, so signature word
; 0x0000 is refused, as the warm start also refuses it since issue #168
; (an image whose real CRC is 0x0000 must be given a different last word,
; e.g. by changing a filler word). An all-0xFF (blank) flash fails the CRC.
;
; Registers. Setup: R3 = 0x04, R2 = 0x08, R0 = 0x06, R1 = 0x0E. Data loop:
;   R0 = byte shift register   R2 = scratch (SCK-high image, MISO, test)
;   R1 = bit counter, steps of 4 (64 = 16 bits down to 0)
;   R3 = 0x04, which is at once MISO's mask in uio_in, the decrement, and
;        the SCK-low image (uio_out = 0x04: CS0 low, MOSI 0, SCK low;
;        bit 2 is the MISO pin, an input, so its value is ignored)
; Images written to UIO_OUT: 0x01 idle (CS0 high), 0x04 SCK low / MOSI 0,
; 0x08 SCK high / MOSI 0, 0x06 SCK low / MOSI 1, 0x0E SCK high / MOSI 1,
; 0x05 SCK low, CS0 high. CS0 is written high BEFORE UIO_DIR makes it an
; output, because uio_out resets to 0x00 and would otherwise select the
; flash for a cycle. MOSI changes only while SCK is low, at least one core
; cycle from either SCK edge.
;
; Clock rate: SCK is high for 2 core cycles and low for 12 or more (a period
; of 14, 16 or 17 cycles), so the flash sees at most f_clk/14; at the 50 MHz
; row-4 target (unconfirmed) that is about 3.6 MHz, far under the 0x03 READ
; ceiling of 50 MHz-class parts. From its first instruction the boot program
; reaches `RUN` after 58,793 cycles (verification/test_boot_spi.py).
; The assembler's data-dependent-latency lint reports warnings here, all
; intended: no branch paces a pin from pin data. The loop counters are
; constants; the two verdict branches decide whether the image runs.

spi_boot:
        LDI   R2, 0x01
        OUT   UIO_OUT, R2           ; CS0 high first ...
        LDI   R2, 0x0B
        WCTL  UIO_DIR, R2           ; ... then CS0, MOSI, SCK become outputs
        LDI   R3, 0x04
        LDI   R2, 0x08
        LDI   R0, 0x06
        OUT   UIO_OUT, R3           ; CS0 falls (SCK low, MOSI 0)
        LDI   R1, 24                ; six clocks of the command's leading zeros
spi_cmd0:
        OUT   UIO_OUT, R2           ; SCK rises
        OUT   UIO_OUT, R3           ; SCK falls
        SUB   R1, R3
        BNZ   spi_cmd0
        LDI   R1, 0x0E
        OUT   UIO_OUT, R0           ; MOSI = 1 (SCK low)
        OUT   UIO_OUT, R1           ; SCK rises: command bit 1
        OUT   UIO_OUT, R0           ; SCK falls
        OUT   UIO_OUT, R1           ; SCK rises: command bit 0 -> 0x03
        OUT   UIO_OUT, R3           ; SCK falls, MOSI back to 0
        LDI   R1, 96                ; 24 address bits, all zero
spi_addr:
        OUT   UIO_OUT, R2           ; SCK rises
        OUT   UIO_OUT, R3           ; SCK falls
        SUB   R1, R3
        BNZ   spi_addr
spi_word:
        LDI   R1, 64                ; 16 bits per word
spi_bit:
        LDI   R2, 0x08
        OUT   UIO_OUT, R2           ; SCK rises: the flash's bit is stable
        IN    R2, UIO_IN
        OUT   UIO_OUT, R3           ; SCK falls
        AND   R2, R3                ; MISO (uio[2]) -> 0x04 or 0x00
        SHF   R2, RIGHT
        SHF   R2, RIGHT             ; -> 0x01 or 0x00
        SHF   R0, LEFT
        OR    R0, R2
        SUB   R1, R3
        BZ    spi_word_done
        LDI   R2, 32                ; after the 8th bit the high byte is complete
        XOR   R2, R1
        BNZ   spi_bit
        WCTL  PM_DATA_HI, R0
        JMP   spi_bit
spi_word_done:
        WCTL  PM_DATA_LO, R0        ; commit {HI, LO}, PM_ADDR++, PM_CRC updated
        RCTL  R2, PM_ADDR           ; wraps to 0 after word 255
        OR    R2, R2
        BNZ   spi_word
        LDI   R2, 0x05
        OUT   UIO_OUT, R2           ; CS0 rises (SCK already low)
        LDI   R0, 0x00
        WCTL  UIO_DIR, R0           ; every uio pin an input again ...
        OUT   UIO_OUT, R0           ; ... and uio_out at its reset value
        RCTL  R0, PM_CRC_HI
        RCTL  R1, PM_CRC_LO
        OR    R0, R1                ; Z <=> PM_CRC == 0 <=> word 255 is the CRC of words 0..254
        BNZ   spi_fail
        LDI   R2, 0xFF
        WCTL  PM_ADDR, R2           ; word 255 ...
        RCTL  R2, PM_DATA_HI
        RCTL  R0, PM_DATA_LO        ; ... PM_ADDR wraps back to 0
        OR    R0, R2                ; Z <=> the signature word is 0x0000
        BZ    spi_fail
        LDI   R0, 0x00              ; R1 = PM_CRC_LO = 0 already
        LDI   R2, 0x00
        JMP   run_image             ; the warm start's handover; R3 = 0x04 != 0
spi_fail:
        HALT                        ; nothing runs; every pin is an input
