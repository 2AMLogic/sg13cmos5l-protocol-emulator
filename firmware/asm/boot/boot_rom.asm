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
;   00           UART load                                  STUB (issue #139)
;   01           SPI-flash boot                             STUB (issue #140)
;   10           warm start: verify program memory, RUN 0   implemented
;   11           reserved; behaves as 00                    STUB (as 00)
;
; The stubs are a HALT each. A halted core holds everything at its reset
; value: UIO_DIR = UIO_OD = 0, so every uio pin is an input, and uo_out is
; 0x00. Nothing in program memory is fetched, because only `WCTL RUN` leaves
; the ROM and neither stub reaches one.
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
;   fail    falls through to the UART load (the stub, until #139). PM_CRC
;           is left holding the nonzero residue; the loader clears it.
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
; The assembler's data-dependent-latency lint reports three warnings, all
; intended: the two strap branches (which boot program runs is the straps'
; whole purpose) and the verdict branch on PM_CRC (whether the image runs
; is the check's whole purpose). No branch here paces a pin: this program
; drives none.

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
uart_load:
        HALT                        ; STUB: the UART load is issue #139

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
        OR    R3, R3                ; R3 = 1: Z = 0
        LDI   R3, 0x00
        SHF   R3, RIGHT             ; shifts out a 0: C = 0
        WCTL  RUN, R2               ; 2 cycles: fetch source -> program memory, PC = 0
