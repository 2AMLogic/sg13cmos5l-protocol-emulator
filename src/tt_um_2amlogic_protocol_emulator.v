/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Harness-bootstrap stub (issue #2).
 *
 * The ISA is not ratified yet (see spec/, issue #1): this design has no
 * instructions, no program memory, and no protocol logic. Its only job is
 * to prove the fixed Tiny Tapeout pin budget, clock, and reset wiring that
 * a future ISA gets built on top of -- clk/rst_n/ena, 8 dedicated inputs,
 * 8 dedicated outputs, and 8 bidirectional pins (held as inputs here, since
 * nothing drives them yet).
 *
 * Behavior: `ui_in` is registered onto `uo_out` synchronously on every
 * `clk` edge while `ena` is asserted, and cleared to zero on `rst_n` low.
 * That is enough to exercise reset and one full clk/pin round trip through
 * real sequential logic (not a bare combinational `assign`), which is what
 * `verification/`'s cocotb bench and `test/test.py` both check.
 *
 * This file is this design's one and only RTL source today. It lives here
 * (rather than under `rtl/`) because the Tiny Tapeout template fixes the
 * top-level source path at `src/<file>.v` (`info.yaml`'s `source_files`);
 * see `rtl/README.md` for how this repo's own klt-driven flow
 * (`flow/synthesize-protocol-emulator.json`) points at this same file
 * instead of keeping a second copy, so the two flows can never disagree on
 * *what* they synthesized -- only, potentially, on the result.
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

  reg [7:0] uo_reg;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      uo_reg <= 8'h00;
    end else if (ena) begin
      uo_reg <= ui_in;
    end
  end

  assign uo_out  = uo_reg;

  // Bidirectional pins are held as inputs (uio_oe = 0): nothing drives them
  // yet, so uio_out's value is a don't-care downstream, but every output
  // pin must still be assigned.
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  // List all unused inputs to prevent warnings
  wire _unused = &{uio_in, 1'b0};

endmodule
