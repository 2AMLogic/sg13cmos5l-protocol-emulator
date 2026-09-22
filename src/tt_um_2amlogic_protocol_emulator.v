/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top for the protocol-emulator ASIC: the ratified ISA's
 * core datapath (`rtl/protocol_core.v`, issue #18) wired to its program
 * memory (`rtl/protocol_program_memory.v`, issue #19), per
 * `spec/decision-records/0001-isa.md`.
 *
 * This replaces the harness-bootstrap stub (issue #2): the pin budget,
 * clock and reset wiring are unchanged (they are fixed by the Tiny
 * Tapeout template), but `ui_in` is no longer registered onto `uo_out`.
 * What drives `uo_out`/`uio_out` now is firmware -- the program loaded
 * over the serial load-phase protocol executing on the core. Per
 * CLAUDE.md, "the ISA is the product": there is deliberately no
 * fixed-function UART/SPI/I2C peripheral here, only the pin-timing
 * engine those protocols are firmware for.
 *
 * Wiring (DR 0001 section "Program memory sizing and loading" and
 * `rtl/protocol_program_memory.v`'s "Interface intent"):
 *
 *   - `ui_in[7]` (MODE) and `ui_in[0]` (serial data) feed the program
 *     memory's load-phase port. All other pins are undisturbed by the
 *     load mechanism; after reset release with MODE low (or once MODE
 *     drops after a load), `ui_in` reads as an ordinary input port
 *     (ISA port 00) -- MODE is latched only at reset release, never
 *     sampled mid-run.
 *   - The core's PC drives the program memory's combinational fetch
 *     port, and the fetched word drives the core's decoder -- the
 *     same-cycle fetch-and-execute path DR 0001's timing model
 *     requires.
 *   - `uo_out` / `uio_out` come from the core's registered pin-port
 *     outputs (ISA ports 10 / 11; new values visible exactly one cycle
 *     after the retiring `OUT`). `uio_in` / `ui_in` feed the core's
 *     input ports (ISA ports 01 / 00).
 *   - `uio_oe` direction is fixed at synthesis time per protocol pin
 *     plan (DR 0001 "Consequences": `OUT` to port 11 only ever targets
 *     `uio_out`, never the direction). No pin-role decision record has
 *     admitted a bidirectional protocol yet, so all 8 bidirectional
 *     pins are still held as inputs (`uio_oe = 0`), same as the stub.
 *   - `ena` is unused on purpose: the template documents it as "always
 *     1 when the design is powered, so you can ignore it", and DR
 *     0001's load protocol is reset-gated, not power-gated.
 *
 * This file is this design's one and only top-level RTL source (the
 * Tiny Tapeout template fixes the top at `src/<file>.v`, per
 * `info.yaml`'s `source_files`); the modules it instantiates live under
 * `rtl/` and reach this flow through symlinks in `src/` so the
 * template's "sources must be in ./src" rule and this repo's
 * one-copy-under-`rtl/` rule (see `rtl/README.md`) both hold without a
 * second copy of anything. This program's own klt-driven flow
 * (`flow/synthesize-protocol-emulator.json`) points at these same
 * files, so the two flows can never disagree on *what* they
 * synthesized -- only, potentially, on the result.
 */

`default_nettype none

module tt_um_2amlogic_protocol_emulator (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire [15:0] instr_word;
  wire [7:0]  fetch_addr;
  wire        run_phase;

  // Program memory + serial load-phase logic (issue #19, DR 0001
  // "Program memory sizing and loading").
  protocol_program_memory u_prog_mem (
      .clk       (clk),
      .rst_n     (rst_n),
      .mode_pin  (ui_in[7]),
      .serial_in (ui_in[0]),
      .fetch_addr(fetch_addr),
      .instr_word(instr_word),
      .run_phase (run_phase)
  );

  // Core datapath (issue #18, DR 0001 "Timing model" / "Register and
  // pin model" / "Encoding").
  protocol_core u_core (
      .clk        (clk),
      .rst_n      (rst_n),
      .run_phase  (run_phase),
      .instr_word (instr_word),
      .fetch_addr (fetch_addr),
      .port_ui_in (ui_in),
      .port_uio_in(uio_in),
      .port_uo_out(uo_out),
      .port_uio_out(uio_out)
  );

  // Bidirectional direction is fixed at synthesis time (DR 0001
  // "Consequences"); no admitted protocol pin plan drives it yet, so
  // every bidirectional pin stays an input and uio_out's value is a
  // don't-care downstream -- but every output pin must still be
  // assigned.
  assign uio_oe = 8'h00;

  // List unused inputs to prevent warnings.
  wire _unused = &{ena, 1'b0};

endmodule

`default_nettype wire
