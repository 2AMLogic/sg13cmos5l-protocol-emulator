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

- `protocol_program_memory.v` — the 256x16-bit program memory and serial
  load-phase shift-in logic (target-spec row 6, issue #19, per DR 0001
  section "Program memory sizing and loading"). Verified stand-alone by
  `verification/test_program_memory.py` (driven by
  `verification/request-program-memory.json`) against the module directly;
  the core-datapath issue (#18) wires it into the top
  (`ui_in[7]` -> `mode_pin`, `ui_in[0]` -> `serial_in`, PC -> `fetch_addr`)
  when the core lands.
