/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal SVA monitors for the serial-load shift-in and load-to-run handoff
 * (issue #529, target-spec row 3, characterization row 3 second gap).
 *
 * `no_data_dependent_latency.sv` stays byte-identical (sha256 6e9691ef...);
 * this file adds two port-only monitors for `formal_top_load.v`:
 *
 *   1. `serial_load_seq_monitor` (standalone loader `formal_top_load_seq`):
 *      tracks a shadow loader whose control state (`s_started`, `s_load`,
 *      `s_run`, `s_sl`, `s_bit`, `s_addr`, `s_full`) depends ONLY on
 *      `mode_pin` (`ui_in[7]`), never on `serial_in` (`ui_in[0]`) or SRAM
 *      contents. Asserts at every post-reset edge:
 *        - `run_phase == s_run` (load duration, exit edge, mode-low direct
 *          boot entry, and no mid-run re-entry on a later `mode_pin` rise);
 *        - `serial_loaded == s_sl` (rises on the exit edge of a serial load,
 *          remains 0 forever on the `mode_pin == 0` boot-ROM path);
 *        - `pm_crc == s_crc` (CRC-16/XMODEM over words committed on the
 *          shadow's 16th-bit edges while `< 256` words have been written,
 *          which pins MSB-first bit order, 16th-bit commit timing, mid-word
 *          discard on an early `mode_pin` drop, and 256-word saturation).
 *      Together with the SRAM stub's `wcnt <= 255` and `A_ADDR == wcnt[7:0]`
 *      assertions in `formal_top_load.v`, this gives 5 safety properties.
 *
 *   2. `serial_load_latency` (integrated core + loader `formal_top_load`):
 *      adds `exec_phase == s_exec` (proving DR 0005's fixed +1-cycle
 *      run-phase priming latency into `protocol_core`), maintains `pm_crc`
 *      equivalence across run-phase `WCTL PM_DATA_LO` / `PM_CRC_*` accesses,
 *      and uses a symbolic-slot observer (`(* anyconst *) reg [2:0] obs_idx`)
 *      to assert that every 16-bit word shifted in on `ui_in[0]` during the
 *      load phase arrives intact on `instr_word` when `protocol_core` fetches
 *      that slot in the run phase.
 */

`default_nettype none

module serial_load_seq_monitor (
    input wire        clk,
    input wire        rst_n,
    input wire        mode_pin,
    input wire        serial_in,
    input wire        run_phase,
    input wire        serial_loaded,
    input wire [15:0] pm_crc
);
  function [15:0] crc16_word;
    input [15:0] crc_in;
    input [15:0] data;
    integer i;
    reg [15:0] c;
    begin
      c = crc_in;
      for (i = 15; i >= 0; i = i - 1)
        c = {c[14:0], 1'b0} ^ ((c[15] ^ data[i]) ? 16'h1021 : 16'h0000);
      crc16_word = c;
    end
  endfunction

  // Shadow state: control depends on `mode_pin` alone.
  reg        s_started = 1'b0;
  reg        s_load    = 1'b0;
  reg        s_run     = 1'b0;
  reg        s_sl      = 1'b0;
  reg        s_full    = 1'b0;
  reg [3:0]  s_bit     = 4'd0;
  reg [7:0]  s_addr    = 8'd0;
  reg [15:0] s_sreg    = 16'd0;
  reg [15:0] s_crc     = 16'd0;

  wire [15:0] s_word     = {s_sreg[14:0], serial_in};
  wire        s_load_wen = s_load && mode_pin && (s_bit == 4'd15) && !s_full;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_started <= 1'b0;
      s_load    <= 1'b0;
      s_run     <= 1'b0;
      s_sl      <= 1'b0;
      s_full    <= 1'b0;
      s_bit     <= 4'd0;
      s_addr    <= 8'd0;
      s_sreg    <= 16'd0;
      s_crc     <= 16'd0;
    end else begin
      if (s_load_wen)
        s_crc <= crc16_word(s_crc, s_word);
      if (s_load && !mode_pin)
        s_sl <= 1'b1;
      if (!s_started) begin
        s_started <= 1'b1;
        if (mode_pin) s_load <= 1'b1;
        else          s_run  <= 1'b1;
      end else if (s_load) begin
        if (!mode_pin) begin
          s_load <= 1'b0;
          s_run  <= 1'b1;
        end else begin
          s_sreg <= s_word;
          if (s_bit == 4'd15) begin
            s_bit <= 4'd0;
            if (!s_full) begin
              if (s_addr == 8'd255) s_full <= 1'b1;
              else                  s_addr <= s_addr + 8'd1;
            end
          end else begin
            s_bit <= s_bit + 4'd1;
          end
        end
      end
    end
  end

  always @(posedge clk) begin
    if (rst_n) begin
      assert (run_phase == s_run);
      assert (serial_loaded == s_sl);
      assert (pm_crc == s_crc);
    end
`ifdef FORMAL
    cover (rst_n && s_load_wen && s_addr == 8'd1);
    cover (rst_n && s_load && !mode_pin && s_bit != 4'd0);
    cover (rst_n && s_sl && s_run && run_phase && serial_loaded && s_crc != 16'd0);
    cover (rst_n && !s_sl && s_run && run_phase && !serial_loaded);
`endif
  end
endmodule

module serial_load_latency (
    input wire        clk,
    input wire        rst_n,
    input wire        mode_pin,
    input wire        serial_in,
    input wire        run_phase,
    input wire        exec_phase,
    input wire        serial_loaded,
    input wire        fetch_rom,
    input wire        pm_we,
    input wire        pm_re,
    input wire [7:0]  pm_addr,
    input wire [15:0] pm_wdata,
    input wire        pm_crc_clr,
    input wire [7:0]  pc,
    input wire [15:0] instr_word,
    input wire [15:0] pm_crc
);
  function [15:0] crc16_word;
    input [15:0] crc_in;
    input [15:0] data;
    integer i;
    reg [15:0] c;
    begin
      c = crc_in;
      for (i = 15; i >= 0; i = i - 1)
        c = {c[14:0], 1'b0} ^ ((c[15] ^ data[i]) ? 16'h1021 : 16'h0000);
      crc16_word = c;
    end
  endfunction

  (* anyconst *) reg [2:0] obs_idx;
  reg        obs_valid;
  reg [15:0] obs_word;

  reg        s_started, s_load, s_run, s_exec, s_sl, s_full;
  reg [3:0]  s_bit;
  reg [7:0]  s_addr;
  reg [15:0] s_sreg, s_crc;
  reg        s_prev_pm_re;
  reg        s_prev_pm_we;

  wire [15:0] s_word     = {s_sreg[14:0], serial_in};
  wire        s_load_wen = s_load && mode_pin && (s_bit == 4'd15) && !s_full;
  wire        s_run_wen  = s_run && pm_we;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_started    <= 1'b0;
      s_load       <= 1'b0;
      s_run        <= 1'b0;
      s_exec       <= 1'b0;
      s_sl         <= 1'b0;
      s_full       <= 1'b0;
      s_bit        <= 4'd0;
      s_addr       <= 8'd0;
      s_sreg       <= 16'd0;
      s_crc        <= 16'd0;
      s_prev_pm_re <= 1'b0;
      s_prev_pm_we <= 1'b0;
      obs_valid    <= 1'b0;
      obs_word     <= 16'd0;
    end else begin
      s_exec       <= s_run;
      s_prev_pm_re <= s_run && pm_re;
      s_prev_pm_we <= s_run && pm_we;

      if (s_load_wen)
        s_crc <= crc16_word(s_crc, s_word);
      else if (s_run_wen)
        s_crc <= crc16_word(s_crc, pm_wdata);
      else if (pm_crc_clr)
        s_crc <= 16'h0000;

      if (s_load_wen && (s_addr[2:0] == obs_idx)) begin
        obs_valid <= 1'b1;
        obs_word  <= s_word;
      end else if (s_run_wen && (pm_addr[2:0] == obs_idx)) begin
        obs_valid <= 1'b1;
        obs_word  <= pm_wdata;
      end

      if (s_load && !mode_pin)
        s_sl <= 1'b1;
      if (!s_started) begin
        s_started <= 1'b1;
        if (mode_pin) s_load <= 1'b1;
        else          s_run  <= 1'b1;
      end else if (s_load) begin
        if (!mode_pin) begin
          s_load <= 1'b0;
          s_run  <= 1'b1;
        end else begin
          s_sreg <= s_word;
          if (s_bit == 4'd15) begin
            s_bit <= 4'd0;
            if (!s_full) begin
              if (s_addr == 8'd255) s_full <= 1'b1;
              else                  s_addr <= s_addr + 8'd1;
            end
          end else begin
            s_bit <= s_bit + 4'd1;
          end
        end
      end
    end
  end

  always @(posedge clk) begin
    if (rst_n) begin
      assert (run_phase == s_run);
      assert (exec_phase == s_exec);
      assert (serial_loaded == s_sl);
      assert (pm_crc == s_crc);
      if (s_exec && !fetch_rom && !s_prev_pm_re && !s_prev_pm_we && obs_valid && (pc[2:0] == obs_idx)) begin
        assert (instr_word == obs_word);
      end
    end
`ifdef FORMAL
    cover (rst_n && s_load_wen && s_addr == 8'd1);
    cover (rst_n && s_load && !mode_pin && s_bit != 4'd0);
    cover (rst_n && s_exec && s_sl && !fetch_rom && obs_valid && (pc[2:0] == obs_idx) && pc == 8'd1);
    cover (rst_n && s_exec && !s_sl && fetch_rom);
`endif
  end
endmodule

`default_nettype wire
