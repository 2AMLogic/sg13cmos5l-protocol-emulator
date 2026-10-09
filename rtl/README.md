# rtl

Verilog sources for this program's own `klt`/Yosys/OpenROAD flow.

The Tiny Tapeout template fixes the top-level source path at
`src/<file>.v` (`info.yaml`'s `source_files`), so the top module,
`tt_um_2amlogic_protocol_emulator`, lives at
`src/tt_um_2amlogic_protocol_emulator.v` rather than here. This program's
own flow (`flow/synthesize-protocol-emulator.json`,
`verification/test_protocol_emulator.py`) reads that same file directly
instead of keeping a second copy under `rtl/` — a copy could silently drift
from the template's source, which is exactly the kind of two-flows
disagreement `CLAUDE.md` says must never happen silently.

`rtl/` holds RTL modules the top-level `src/` file includes/instantiates
that are not themselves the Tiny Tapeout top:

- `protocol_core.v` — the ISA core datapath (target-spec rows 1/3/6, issue
  #18, per DR 0001 sections "Timing model", "Register and pin model" and
  "Encoding"): four 8-bit registers `R0`-`R3`, the 2-bit `{Z, C}` flag
  register, the four addressable 8-bit pin ports, and single-cycle
  fetch/execute over all 16 opcodes, with the *fetch-ahead* amendment of DR
  0005 (the next instruction's address is presented one cycle early, at zero
  cycles per instruction and a fixed +1 cycle at run-phase entry). Checked by
  `verification/test_protocol_emulator.py` against the **top**, with every
  program loaded through the real load-phase pins rather than a backdoor.
  It also holds DR 0012's control space (issue #135): the `WCTL`/`RCTL`
  decode, the pin-mode registers `UIO_DIR`/`UIO_OD`, the program-memory
  access registers and the fixed one-cycle fetch stall of the three
  2-cycle accesses. Checked by `verification/test_control_space.py`, and
  its latency table by the formal property under `verification/formal/`.
- `protocol_program_memory.v` — the 256x16-bit program memory and serial
  load-phase shift-in logic (target-spec row 6, issue #19, per DR 0001
  section "Program memory sizing and loading"), with its storage array
  rebuilt on the PDK's `RM_IHPSG13_1P_256x16_c2_bm_bist` single-port SRAM
  macro per DR 0005 — DR 0001's organisation and load protocol are unchanged;
  only *what holds the bits* is. Verified by
  `verification/test_program_memory.py` (driven by
  `verification/request-program-memory.json`) against the module directly.
  Since issue #135 it also arbitrates the macro's single port between
  instruction fetch and the core's DR 0012 data accesses (`pm_we`/`pm_re`),
  and keeps `PM_CRC` (CRC-16/XMODEM over every committed word, by either
  path) and `BOOT_STATUS[0]`.
  It is wired into the top by issue #18's core (`ui_in[7]` -> `mode_pin`,
  `ui_in[0]` -> `serial_in`, the core's fetch-ahead address -> `fetch_addr`,
  `run_phase` -> the core).
- `protocol_boot_rom.v` — the boot ROM of DR 0013 layer 2 (issue #138),
  target-spec row 14 (c). **Generated, never edited by hand**:
  `firmware/tools/gen_boot_rom.py` writes it from the committed boot image
  `firmware/build/boot/boot_rom.hex`, which the DR 0003 assembler assembles
  from `firmware/asm/boot/boot_rom.asm`. `firmware/tools/check_firmware.py`
  (run by CI and by `npm run lint`) fails on a stale link in that chain.
  It is a `case` over the fetch address behind one register, so it reads
  with the macro's one-cycle delay and the core takes either source through
  the same fetch stage; addresses outside the image read as `HALT`. The
  image is 30 words; DR 0013 caps it at 128 and the generator refuses more.
  The core decodes the ROM from `rst_n` release with `MODE` low until the
  boot program executes `WCTL RUN` (`fetch_rom`, also `BOOT_STATUS[1]`),
  and tells the program memory not to read the macro for fetch meanwhile
  (`pm_fetch` → `fetch_en`). A serial load never decodes it. Checked by
  `verification/test_boot_rom.py` on the top, with
  `verification/boot_rom_mutants.py` as its negative controls.
- `vendor/` — the SRAM macro's behavioural model, vendored byte-for-byte from
  the PDK with provenance and licence in `vendor/README.md`. Simulation only:
  the macro is a hard block, blackboxed by LibreLane against the LEF/liberty
  in `src/config.json` and by the klt/Yosys leg against
  `flow/blackbox-RM_IHPSG13_1P_256x16_c2_bm_bist.v`.

All three modules reach the Tiny Tapeout flow through symlinks in `src/`
(`src/protocol_core.v`, `src/protocol_program_memory.v`,
`src/protocol_boot_rom.v`), so the template's
"sources live in `./src`" rule and this file's one-copy rule above both hold
without a second copy of anything.

Note that DR 0001, DR 0005, DR 0012 and DR 0013 are all `Status: Proposed`, not ratified — the
two-key mechanism has never run in this repository
(`spec/decision-records/0006-two-key-ratification-never-ran.md`). This RTL
implements their content as if binding, under the operator's explicit
2026-09-30 approval on issue #18.
