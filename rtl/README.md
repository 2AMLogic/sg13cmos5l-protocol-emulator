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
disagreement `CLAUDE.md` says must never happen silently. `rtl/` stays empty
until the ratified ISA (see `spec/`, issue #1) needs RTL modules the
top-level `src/` file includes/instantiates that are not themselves the
Tiny Tapeout top -- e.g. a separate core/decoder module the top wraps.
