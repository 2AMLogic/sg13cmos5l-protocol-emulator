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
;   01           SPI-flash boot                             STUB (issue #140)
;   10           warm start: verify program memory, RUN 0   implemented
;   11           reserved; behaves as 00                    implemented (as 00)
;
; The SPI stub is a HALT. A halted core holds everything at its reset value:
; UIO_DIR = UIO_OD = 0, so every uio pin is an input, and uo_out is 0x00.
; Nothing in program memory is fetched, because only `WCTL RUN` leaves the
; ROM and the stub does not reach one.
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
;   pass    RUN 0, entered with R0-R3 = 0, Z = 0 and C = 0 (the reset
;           values, restored below), PM_ADDR = 0 and PM_CRC = 0x0000. A
;           warm-started program reads BOOT_STATUS = 0x00; a serial-loaded
;           one reads 0x01. The PM_DATA latches hold word 255's bytes.
;   fail    falls through to the UART load below. PM_CRC is left holding
;           the nonzero residue; the loader clears it.
;
; Registers in the warm-start loop:
;   R0 = high byte of the word      R2 = word index (0..255, wraps to 0)
;   R1 = low byte of the word       R3 = constant 1
;
; Cycle counts (DR 0001 / DR 0012 latency table), from the first executed
; instruction: the dispatch reaches a stub's HALT or `warm_start` in a fixed
; number of cycles per strap value, and one pass of `warm_loop` is 9 cycles.
; A warm start that passes spends 6 + 4 + 256 * 9 + 4 + 3 = 2,321 cycles
; before its 2-cycle RUN, so word 0 of the verified program executes exactly
; 2,323 cycles after this program's first instruction, whatever the image
; holds (verification/test_boot_rom.py checks that number at the pins).
;
; The assembler's data-dependent-latency lint reports eight warnings, all
; intended. Three are in the warm start and the dispatch: the two strap
; branches (which boot program runs is the straps' whole purpose) and the
; verdict branch on PM_CRC (whether the image runs is the check's whole
; purpose). Five are in the UART load: the start-edge poll, the phase
; dispatch, the handlers and the verdicts, which all act on received bytes.
; None paces a pin. The warm start drives none; in the UART load the samples
; and the transmitted bits are paced by WAIT literals and a counter that never
; holds pin data, and no branch on a received byte sits between two samples.

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
        JMP   handover              ; as the warm start: Z, C, R3, then RUN 0
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

; Strap 01.
spi_boot:
        HALT                        ; STUB: the SPI-flash boot is issue #140

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
        RCTL  R0, PM_CRC_HI
        RCTL  R1, PM_CRC_LO
        OR    R0, R1                ; Z <=> PM_CRC == 0 <=> word 255 is the CRC of words 0..254
        BNZ   uart_load             ; not a verified image: never RUN it
        ; Verified. Hand over with the architectural state a reset leaves:
        ; R0 = R1 = R2 = 0 already; restore Z, R3 and C.
handover:                           ; needs R0 = R1 = R2 = 0, R3 = 1
        OR    R3, R3                ; R3 = 1: Z = 0
        LDI   R3, 0x00
        SHF   R3, RIGHT             ; shifts out a 0: C = 0
        WCTL  RUN, R2               ; 2 cycles: fetch source -> program memory, PC = 0
