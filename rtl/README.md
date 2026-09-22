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

- `protocol_core.v` — the ratified ISA's core datapath (target-spec rows
  1/3, issue #18, per DR 0001 sections "Timing model", "Register and pin
  model", and "Encoding"): four 8-bit registers, the Z/C flags, the four
  addressable pin ports, single-cycle fetch/execute for every opcode,
  and the immediate-driven `WAIT` stall that gives every program a
  cycle count computable from the instruction stream alone. Verified at
  the top level by `verification/test_protocol_emulator.py` (driven by
  `verification/request-protocol-emulator.json`), which loads firmware
  over the real serial load phase and checks every instruction class
  cycle-exactly; the top wires it to the program memory's fetch port and
  run-phase line, per `protocol_program_memory.v`'s "Interface intent".
- `protocol_program_memory.v` — the 256x16-bit program memory and serial
  load-phase shift-in logic (target-spec row 6, issue #19, per DR 0001
  section "Program memory sizing and loading"). Verified stand-alone by
  `verification/test_program_memory.py` (driven by
  `verification/request-program-memory.json`) against the module
  directly; wired into the top by issue #18
  (`ui_in[7]` -> `mode_pin`, `ui_in[0]` -> `serial_in`, PC ->
  `fetch_addr`).

Since issue #18, the top instantiates both modules, so the Tiny Tapeout
template's "source files must be in ./src" rule (`info.yaml`) is
satisfied through symlinks: `src/protocol_core.v` and
`src/protocol_program_memory.v` point at these files. The symlinks exist
only so the template's flow (LibreLane in GitHub Actions, the
`test/` Makefile) can compile the design from `./src`; the single copy
of each module stays here, and this program's own flow
(`flow/synthesize-protocol-emulator.json`,
`verification/request-protocol-emulator.json`) reads the real `rtl/`
paths directly — so there is still exactly one copy of everything and
nothing that can drift.
