/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED FILE -- DO NOT EDIT. Written by firmware/tools/gen_boot_rom.py
 * from firmware/build/boot/boot_rom.hex, which firmware/tools/asm.py
 * assembles from firmware/asm/boot/boot_rom.asm. To change the ROM, edit
 * the .asm, re-assemble, and re-run the generator;
 * firmware/tools/check_firmware.py fails on any stale link in that chain.
 *
 *   image words  : 30 (cap 128, DR 0013 layer 2)
 *   image sha256 : cf2abaecc0e148efec6165fb7e988c2840735c2572030dac29a5564a773f3859
 *
 * The boot ROM of spec/decision-records/0013-program-loading.md layer 2
 * (issue #138): the program the core fetches when `rst_n` is released with
 * MODE low. It is logic, not a macro -- a `case` over the fetch address --
 * and it is registered once, so a word appears on `data` in the cycle after
 * its address was presented: the program-memory macro's one-cycle read
 * (DR 0005), which is what lets the core take either source through one
 * fetch stage. Addresses outside the image read as HALT (16'hF000).
 *
 * `data` resets to 16'h0000 (NOP). The value is never executed -- the core
 * ignores the fetched word until one real fetch has completed -- but a
 * reset value means this register is not one more flop that powers up
 * unknown (target-spec row 14).
 */

`default_nettype none

module protocol_boot_rom (
    input  wire        clk,    // clock
    input  wire        rst_n,  // reset_n - low to reset
    input  wire [7:0]  addr,   // the core's fetch-ahead address
    output reg  [15:0] data    // the word at the address presented one cycle earlier
);

  reg [15:0] word;

  always @(*) begin
    case (addr)
      8'h00: word = 16'h9000;
      8'h01: word = 16'h1460;
      8'h02: word = 16'h5100;
      8'h03: word = 16'h1440;
      8'h04: word = 16'h4400;
      8'h05: word = 16'hD00B;
      8'h06: word = 16'h1420;
      8'h07: word = 16'h4400;
      8'h08: word = 16'hD00A;
      8'h09: word = 16'hF000;
      8'h0A: word = 16'hF000;
      8'h0B: word = 16'h1800;
      8'h0C: word = 16'h1C01;
      8'h0D: word = 16'hA802;
      8'h0E: word = 16'hA806;
      8'h0F: word = 16'h9203;
      8'h10: word = 16'h9604;
      8'h11: word = 16'hA802;
      8'h12: word = 16'hA003;
      8'h13: word = 16'hA404;
      8'h14: word = 16'h3B00;
      8'h15: word = 16'hE00F;
      8'h16: word = 16'h9207;
      8'h17: word = 16'h9606;
      8'h18: word = 16'h6100;
      8'h19: word = 16'hE009;
      8'h1A: word = 16'h6F00;
      8'h1B: word = 16'h1C00;
      8'h1C: word = 16'h8C00;
      8'h1D: word = 16'hA805;
      default: word = 16'hF000;  // outside the image: HALT
    endcase
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      data <= 16'h0000;
    end else begin
      data <= word;
    end
  end

endmodule

`default_nettype wire
