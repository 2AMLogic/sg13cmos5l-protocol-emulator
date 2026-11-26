/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal harness for the serial-load shift-in and load-to-run handoff
 * (issue #529, target-spec row 3, characterization row 3 second gap).
 *
 * Two configurations, selected by `-D INTEGRATED_LOAD`:
 *
 *   1. Default (standalone loader, top `formal_top_load_seq`):
 *      Instantiates the shipped `rtl/protocol_program_memory.v` against a
 *      stub of `RM_IHPSG13_1P_256x16_c2_bm_bist` whose otherwise unused read port
 *      exposes the macro write strobe and full 8-bit address to
 *      `serial_load_seq_monitor` (`serial_load_latency.sv`). `mode_pin`
 *      (`ui_in[7]`) and `serial_in` (`ui_in[0]`) are completely free every
 *      cycle after the single reset cycle, covering:
 *        - `mode_pin == 1` at reset release -> MSB-first shift-in, commit on
 *          every 16th bit's edge, auto-increment `0..255`, saturation at 256
 *          words, mid-word discard when `mode_pin` drops mid-word, and no
 *          mid-run re-entry if `mode_pin` rises again;
 *        - `mode_pin == 0` at reset release -> direct boot-ROM run entry with
 *          `serial_loaded` held at 0 and zero load commits.
 *
 *   2. `-D INTEGRATED_LOAD` (end-to-end loader + core, top `formal_top_load`):
 *      Replaces `formal_top.v`'s constant-table / `free_serial_loaded`
 *      abstraction by wiring the shipped `rtl/protocol_program_memory.v`
 *      directly to the shipped `rtl/protocol_core.v` (exact top-level port
 *      connections of `src/tt_um_2amlogic_protocol_emulator.v`). The SRAM
 *      macro is modelled as an 8-word aliased synchronous single-port array
 *      (`A_ADDR[2:0]`, matching `rtl/vendor/RM_IHPSG13_1P_core_behavioral_bm_bist.v`'s
 *      clocked write/read/bit-mask semantics and `formal_top.v`'s modulo-8
 *      address aliasing, with free `anyconst` power-up contents). Both the
 *      byte-identical `no_data_dependent_latency.sv` monitor (8 core timing
 *      assertions) and `serial_load_latency` (5 load-to-fetch assertions,
 *      unless `-D CORE_PROP_ONLY` selects the 8 core assertions alone) run
 *      over the combined transition system.
 */

`default_nettype none

`ifdef INTEGRATED_LOAD

module RM_IHPSG13_1P_256x16_c2_bm_bist (
    input  wire        A_CLK, A_MEN, A_WEN, A_REN,
    input  wire [7:0]  A_ADDR,
    input  wire [15:0] A_DIN,
    input  wire        A_DLY,
    output wire [15:0] A_DOUT,
    input  wire [15:0] A_BM,
    input  wire        A_BIST_CLK, A_BIST_EN, A_BIST_MEN, A_BIST_WEN, A_BIST_REN,
    input  wire [7:0]  A_BIST_ADDR,
    input  wire [15:0] A_BIST_DIN, A_BIST_BM
);
  (* anyconst *) reg [15:0] init0, init1, init2, init3, init4, init5, init6, init7;
  (* anyconst *) reg [15:0] init_dr;
  reg        inited = 1'b0;
  reg [15:0] m0, m1, m2, m3, m4, m5, m6, m7;
  reg [15:0] dr_r;

  wire [15:0] cur0 = inited ? m0 : init0;
  wire [15:0] cur1 = inited ? m1 : init1;
  wire [15:0] cur2 = inited ? m2 : init2;
  wire [15:0] cur3 = inited ? m3 : init3;
  wire [15:0] cur4 = inited ? m4 : init4;
  wire [15:0] cur5 = inited ? m5 : init5;
  wire [15:0] cur6 = inited ? m6 : init6;
  wire [15:0] cur7 = inited ? m7 : init7;

  wire [2:0]  idx    = A_ADDR[2:0];
  wire [15:0] rd_cur = idx[2] ? (idx[1] ? (idx[0] ? cur7 : cur6) : (idx[0] ? cur5 : cur4))
                              : (idx[1] ? (idx[0] ? cur3 : cur2) : (idx[0] ? cur1 : cur0));
  wire [15:0] wr_val = (rd_cur & ~A_BM) | (A_DIN & A_BM);

  always @(posedge A_CLK) begin
    inited <= 1'b1;
    m0 <= (A_MEN && A_WEN && idx == 3'd0) ? wr_val : cur0;
    m1 <= (A_MEN && A_WEN && idx == 3'd1) ? wr_val : cur1;
    m2 <= (A_MEN && A_WEN && idx == 3'd2) ? wr_val : cur2;
    m3 <= (A_MEN && A_WEN && idx == 3'd3) ? wr_val : cur3;
    m4 <= (A_MEN && A_WEN && idx == 3'd4) ? wr_val : cur4;
    m5 <= (A_MEN && A_WEN && idx == 3'd5) ? wr_val : cur5;
    m6 <= (A_MEN && A_WEN && idx == 3'd6) ? wr_val : cur6;
    m7 <= (A_MEN && A_WEN && idx == 3'd7) ? wr_val : cur7;
    if (A_MEN && A_WEN && A_REN)
      dr_r <= wr_val;
    else if (A_MEN && A_REN)
      dr_r <= rd_cur;
    else if (!inited)
      dr_r <= init_dr;
  end

  assign A_DOUT = inited ? dr_r : init_dr;
endmodule

module formal_top_load (
    input wire       clk,
    input wire [7:0] ui_in,
    input wire [7:0] uio_in
);
  reg rst_n_r = 1'b0;
  always @(posedge clk) rst_n_r <= 1'b1;

  // Free 8-word boot ROM (DR 0013 layer 2), registered read matching protocol_boot_rom.
  (* anyconst *) reg [15:0] rom0, rom1, rom2, rom3, rom4, rom5, rom6, rom7;
  wire [7:0]  fetch_addr;
  wire [15:0] rom_sel = fetch_addr[2]
      ? (fetch_addr[1] ? (fetch_addr[0] ? rom7 : rom6) : (fetch_addr[0] ? rom5 : rom4))
      : (fetch_addr[1] ? (fetch_addr[0] ? rom3 : rom2) : (fetch_addr[0] ? rom1 : rom0));
  reg [15:0] rom_q = 16'd0;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) rom_q <= 16'd0;
    else          rom_q <= rom_sel;

  wire [15:0] instr_word, pm_wdata, pm_crc;
  wire [7:0]  pm_addr, core_uo, core_uio, core_uio_dir, core_uio_od;
  wire        run_phase, serial_loaded, fetch_rom, pm_fetch, pm_we, pm_re, pm_crc_clr;

  protocol_program_memory dut_mem (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .mode_pin     (ui_in[7]),
      .serial_in    (ui_in[0]),
      .fetch_addr   (fetch_addr),
      .fetch_en     (pm_fetch),
      .instr_word   (instr_word),
      .run_phase    (run_phase),
      .pm_we        (pm_we),
      .pm_re        (pm_re),
      .pm_addr      (pm_addr),
      .pm_wdata     (pm_wdata),
      .pm_crc_clr   (pm_crc_clr),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  protocol_core dut_core (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .run_phase    (run_phase),
      .instr_word   (instr_word),
      .fetch_addr   (fetch_addr),
      .rom_word     (rom_q),
      .fetch_rom    (fetch_rom),
      .pm_fetch     (pm_fetch),
      .port_ui_in   (ui_in),
      .port_uio_in  (uio_in),
      .port_uo_out  (core_uo),
      .port_uio_out (core_uio),
      .uio_dir      (core_uio_dir),
      .uio_od       (core_uio_od),
      .pm_we        (pm_we),
      .pm_re        (pm_re),
      .pm_addr      (pm_addr),
      .pm_wdata     (pm_wdata),
      .pm_crc_clr   (pm_crc_clr),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  reg       exec_phase;
  reg [7:0] pc_q;
  always @(posedge clk or negedge rst_n_r) begin
    if (!rst_n_r) begin
      exec_phase <= 1'b0;
      pc_q       <= 8'd0;
    end else begin
      exec_phase <= run_phase;
      pc_q       <= run_phase ? fetch_addr : 8'd0;
    end
  end

  wire [15:0] exec_word = fetch_rom ? rom_q : instr_word;

  no_data_dependent_latency u_core_prop (
      .clk      (clk),
      .rst_n    (rst_n_r),
      .run_phase(exec_phase),
      .pc       (pc_q),
      .instr    (exec_word)
  );

`ifndef CORE_PROP_ONLY
  serial_load_latency u_load_prop (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .mode_pin     (ui_in[7]),
      .serial_in    (ui_in[0]),
      .run_phase    (run_phase),
      .exec_phase   (exec_phase),
      .serial_loaded(serial_loaded),
      .fetch_rom    (fetch_rom),
      .pm_fetch     (pm_fetch),
      .pm_we        (pm_we),
      .pm_re        (pm_re),
      .pm_addr      (pm_addr),
      .pm_wdata     (pm_wdata),
      .pm_crc_clr   (pm_crc_clr),
      .pc           (pc_q),
      .instr_word   (instr_word),
      .pm_crc       (pm_crc)
  );
`endif
endmodule

`else // standalone loader (formal_top_load_seq)

module RM_IHPSG13_1P_256x16_c2_bm_bist (
    input  wire        A_CLK, A_MEN, A_WEN, A_REN,
    input  wire [7:0]  A_ADDR,
    input  wire [15:0] A_DIN,
    input  wire        A_DLY,
    output wire [15:0] A_DOUT,
    input  wire [15:0] A_BM,
    input  wire        A_BIST_CLK, A_BIST_EN, A_BIST_MEN, A_BIST_WEN, A_BIST_REN,
    input  wire [7:0]  A_BIST_ADDR,
    input  wire [15:0] A_BIST_DIN, A_BIST_BM
);
  // Standalone only: no core reads instructions. Return the physical write
  // pins to the monitor through the DUT's pass-through instr_word port.
  assign A_DOUT = {7'b0, A_MEN && A_WEN, A_ADDR};
endmodule

module formal_top_load_seq (
    input wire clk,
    input wire mode_pin,
    input wire serial_in
);
  reg rst_n_r = 1'b0;
  always @(posedge clk) rst_n_r <= 1'b1;

  wire        run_phase, serial_loaded;
  wire [15:0] pm_crc, instr_word;

  protocol_program_memory dut (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .mode_pin     (mode_pin),
      .serial_in    (serial_in),
      .fetch_addr   (8'd0),
      .fetch_en     (1'b0),
      .instr_word   (instr_word),
      .run_phase    (run_phase),
      .pm_we        (1'b0),
      .pm_re        (1'b0),
      .pm_addr      (8'd0),
      .pm_wdata     (16'd0),
      .pm_crc_clr   (1'b0),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  serial_load_seq_monitor mon (
      .sram_write   (instr_word[8]),
      .sram_addr    (instr_word[7:0]),
      .clk          (clk),
      .rst_n        (rst_n_r),
      .mode_pin     (mode_pin),
      .serial_in    (serial_in),
      .run_phase    (run_phase),
      .serial_loaded(serial_loaded),
      .pm_crc       (pm_crc)
  );
endmodule

`endif

`default_nettype wire
