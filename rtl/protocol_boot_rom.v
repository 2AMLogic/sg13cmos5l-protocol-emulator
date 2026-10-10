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
 *   image words  : 158 (cap 256: the fetch address space, DR 0013 finding F2)
 *   image sha256 : 250c42af1a4a3e7868d8f31c88cabd1405803831f37ae7ab8c5330cf1c75020c
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
      8'h05: word = 16'hD08B;
      8'h06: word = 16'h1420;
      8'h07: word = 16'h4400;
      8'h08: word = 16'hD08A;
      8'h09: word = 16'h10FF;
      8'h0A: word = 16'hA300;
      8'h0B: word = 16'hA001;
      8'h0C: word = 16'h1001;
      8'h0D: word = 16'hA200;
      8'h0E: word = 16'h1C00;
      8'h0F: word = 16'h1402;
      8'h10: word = 16'h9800;
      8'h11: word = 16'h5900;
      8'h12: word = 16'hE010;
      8'h13: word = 16'h1480;
      8'h14: word = 16'hB0FF;
      8'h15: word = 16'hB0FF;
      8'h16: word = 16'hB085;
      8'h17: word = 16'h9800;
      8'h18: word = 16'h8800;
      8'h19: word = 16'h8900;
      8'h1A: word = 16'h8900;
      8'h1B: word = 16'h8900;
      8'h1C: word = 16'h8900;
      8'h1D: word = 16'h8900;
      8'h1E: word = 16'h8900;
      8'h1F: word = 16'h8900;
      8'h20: word = 16'h8000;
      8'h21: word = 16'h6200;
      8'h22: word = 16'h8400;
      8'h23: word = 16'h6500;
      8'h24: word = 16'hB0FF;
      8'h25: word = 16'hB0A3;
      8'h26: word = 16'hE017;
      8'h27: word = 16'h6F00;
      8'h28: word = 16'hD072;
      8'h29: word = 16'h1401;
      8'h2A: word = 16'h4D00;
      8'h2B: word = 16'hD077;
      8'h2C: word = 16'h4D00;
      8'h2D: word = 16'hD07D;
      8'h2E: word = 16'h4D00;
      8'h2F: word = 16'hD080;
      8'h30: word = 16'h4D00;
      8'h31: word = 16'hD037;
      8'h32: word = 16'h9607;
      8'h33: word = 16'h7100;
      8'h34: word = 16'hA000;
      8'h35: word = 16'h1C04;
      8'h36: word = 16'hC00F;
      8'h37: word = 16'h9606;
      8'h38: word = 16'h7100;
      8'h39: word = 16'h9600;
      8'h3A: word = 16'h6100;
      8'h3B: word = 16'h1015;
      8'h3C: word = 16'hE03E;
      8'h3D: word = 16'h1006;
      8'h3E: word = 16'hA000;
      8'h3F: word = 16'h1400;
      8'h40: word = 16'hA402;
      8'h41: word = 16'h1801;
      8'h42: word = 16'h1C00;
      8'h43: word = 16'hAE00;
      8'h44: word = 16'h1480;
      8'h45: word = 16'hB0FF;
      8'h46: word = 16'hB0AD;
      8'h47: word = 16'h2C00;
      8'h48: word = 16'h5E00;
      8'h49: word = 16'hAE00;
      8'h4A: word = 16'h8000;
      8'h4B: word = 16'h8400;
      8'h4C: word = 16'h6500;
      8'h4D: word = 16'hB0FF;
      8'h4E: word = 16'hB0AA;
      8'h4F: word = 16'hE047;
      8'h50: word = 16'hB001;
      8'h51: word = 16'hAA00;
      8'h52: word = 16'hB0FF;
      8'h53: word = 16'hB0AA;
      8'h54: word = 16'h9602;
      8'h55: word = 16'h6500;
      8'h56: word = 16'hE05B;
      8'h57: word = 16'h9207;
      8'h58: word = 16'h1401;
      8'h59: word = 16'hA402;
      8'h5A: word = 16'hC041;
      8'h5B: word = 16'h1801;
      8'h5C: word = 16'h4600;
      8'h5D: word = 16'hE062;
      8'h5E: word = 16'h9206;
      8'h5F: word = 16'h1402;
      8'h60: word = 16'hA402;
      8'h61: word = 16'hC041;
      8'h62: word = 16'h9200;
      8'h63: word = 16'h1406;
      8'h64: word = 16'h7100;
      8'h65: word = 16'hE070;
      8'h66: word = 16'h1000;
      8'h67: word = 16'hA200;
      8'h68: word = 16'hA000;
      8'h69: word = 16'hA001;
      8'h6A: word = 16'hA300;
      8'h6B: word = 16'hA002;
      8'h6C: word = 16'h2400;
      8'h6D: word = 16'h2800;
      8'h6E: word = 16'h1C01;
      8'h6F: word = 16'hC09A;
      8'h70: word = 16'h1C00;
      8'h71: word = 16'hC00F;
      8'h72: word = 16'h14A5;
      8'h73: word = 16'h7400;
      8'h74: word = 16'hE00F;
      8'h75: word = 16'h1C01;
      8'h76: word = 16'hC00F;
      8'h77: word = 16'hA000;
      8'h78: word = 16'h1400;
      8'h79: word = 16'hA402;
      8'h7A: word = 16'hA406;
      8'h7B: word = 16'h1C02;
      8'h7C: word = 16'hC00F;
      8'h7D: word = 16'hA003;
      8'h7E: word = 16'h1C03;
      8'h7F: word = 16'hC00F;
      8'h80: word = 16'hA004;
      8'h81: word = 16'h9600;
      8'h82: word = 16'h6500;
      8'h83: word = 16'h1C05;
      8'h84: word = 16'hD00F;
      8'h85: word = 16'h1801;
      8'h86: word = 16'h4600;
      8'h87: word = 16'hA400;
      8'h88: word = 16'h1C02;
      8'h89: word = 16'hC00F;
      8'h8A: word = 16'hF000;
      8'h8B: word = 16'h1800;
      8'h8C: word = 16'h1C01;
      8'h8D: word = 16'hA802;
      8'h8E: word = 16'hA806;
      8'h8F: word = 16'h9203;
      8'h90: word = 16'h9604;
      8'h91: word = 16'hA802;
      8'h92: word = 16'hA003;
      8'h93: word = 16'hA404;
      8'h94: word = 16'h3B00;
      8'h95: word = 16'hE08F;
      8'h96: word = 16'h9207;
      8'h97: word = 16'h9606;
      8'h98: word = 16'h6100;
      8'h99: word = 16'hE009;
      8'h9A: word = 16'h6F00;
      8'h9B: word = 16'h1C00;
      8'h9C: word = 16'h8C00;
      8'h9D: word = 16'hA805;
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
