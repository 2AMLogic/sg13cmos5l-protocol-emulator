/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal harness top for `pin_write_latency` (verification-plan section
 * 2.2, issue #116), bound to the shipped rtl/protocol_core.v (read
 * unmodified; mutants are scratch copies made by the runner).
 *
 * This is a sibling of formal_top.v's REAL_CORE binding rather than a new
 * `ifdef` inside it, on purpose: formal_top.v and the section 2.1 monitor
 * are hash-pinned by the live append-only `no-data-dependent-latency`
 * record, and editing formal_top.v would stale that pin. The program /
 * phase abstraction below is the SAME one:
 *
 *   - Program: 8 `anyconst` 16-bit words selected by fetch_addr[2:0],
 *     read through a REGISTERED port (`instr_q`) modelling DR 0005's
 *     one-cycle synchronous fetch. Free and stable: the result quantifies
 *     over every opcode/register/port/immediate combination in each of the
 *     8 words. Addresses alias modulo 8 (JMP/branch targets wrap inside the
 *     table), so straight-line code longer than 8 words is not represented;
 *     loops through the table are. (`anyconst` is deliberate: a
 *     self-holding register with no init is folded to a constant by
 *     `opt_dff`, which would silently turn the program into all-NOPs.)
 *   - Boot ROM (DR 0013 layer 2, issue #138): a SECOND table of 8
 *     `anyconst` words, `rom0..7`, read at fetch_addr[2:0] through its own
 *     registered port (`rom_q`) -- the boot ROM as a free program, so the
 *     result quantifies over every ROM image, not over the committed one.
 *     Both words go to the core (`rom_word`, `instr_word`) and to the
 *     monitor (`rom_instr`, `instr`); the monitor picks between them with
 *     its own shadow of the fetch source and never sees the core's
 *     `fetch_rom`. Which way the run phase is entered -- the ROM, or
 *     program memory after a serial load -- is the free `serial_loaded`
 *     input: before issue #138 "mode_pin low" here meant "run program
 *     memory", which is no longer what the design does.
 *   - Run phase: the program memory's own phase timing for mode_pin low
 *     (reset, one mode-sampling edge, then run), as in formal_top.v. The
 *     load phase proper (mode_pin high, serial shift-in) is modelled only
 *     by what the core can see of it: run_phase low for any number of
 *     cycles (>= 1) after reset, chosen by the free `go` input.
 *   - exec_valid = run_phase delayed one cycle (DR 0005's priming cycle
 *     executes nothing). DERIVED HERE from the phase model, never from the
 *     core's fetch_valid.
 *   - ui_in / uio_in are free in every solver step, and `rst_req` is a free
 *     per-step input that requests a reset at the next edge, so mid-run
 *     reset pulses and HALT-until-reset are inside the explored space.
 *     rst_n_r is a clocked register (reset changes are clock-synchronised),
 *     as in formal_top.v; the core's reset is asynchronous in RTL, but in
 *     this harness it only ever changes at a clock edge.
 *
 * `FINE` adds F1 (between-edge isolation, sampled on the solver's global
 * step clock) and the fine-model covers; the runner elaborates that build
 * with clk2fflogic so `clk` is a free signal and the pin inputs may change
 * between edges.
 */

`default_nettype none

module formal_top_pin_write (
    input wire        clk,
    input wire [7:0]  ui_in,
    input wire [7:0]  uio_in,
    input wire        rst_req,
    input wire        go,
    // DR 0012 (issue #135): the two control-space values the core reads
    // from the program memory rather than holding itself. Free every
    // cycle, and handed to the core and the monitor alike.
    input wire [15:0] pm_crc,
    input wire        serial_loaded
);

  reg rst_n_r = 1'b0;
  always @(posedge clk)
    rst_n_r <= ~rst_req;

  reg started     = 1'b0;
  reg run_phase_r = 1'b0;
  always @(posedge clk or negedge rst_n_r) begin
    if (!rst_n_r) begin
      started     <= 1'b0;
      run_phase_r <= 1'b0;
    end else if (!started && go) begin
      started     <= 1'b1;
      run_phase_r <= 1'b1;  // mode_pin == 0: enter run phase (free `go`: the
                            // run_phase-low window after reset has ANY length >= 1)
    end
  end
  wire run_phase = run_phase_r;

  // Cover: a run_phase-low window of at least 2 cycles after a reset,
  // followed by run phase and a real pin write (nonzero output). Shows the
  // multi-cycle load window is reachable, not just assumed.
  reg [1:0] lw       = 2'd0;
  reg       long_win = 1'b0;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) begin
      lw       <= 2'd0;
      long_win <= 1'b0;
    end else if (!run_phase_r) begin
      lw <= (lw == 2'd3) ? 2'd3 : lw + 2'd1;
    end else if (lw >= 2'd2) begin
      long_win <= 1'b1;
    end

  (* anyconst *) reg [15:0] prog0;
  (* anyconst *) reg [15:0] prog1;
  (* anyconst *) reg [15:0] prog2;
  (* anyconst *) reg [15:0] prog3;
  (* anyconst *) reg [15:0] prog4;
  (* anyconst *) reg [15:0] prog5;
  (* anyconst *) reg [15:0] prog6;
  (* anyconst *) reg [15:0] prog7;

  wire [7:0]  fetch_addr;
  // DR 0012 (issue #135): the program memory's address mux, as in
  // rtl/protocol_program_memory.v -- a program-memory data access takes
  // the single port, so the word returned the next cycle is the table
  // entry at PM_ADDR. In the stall cycle of such an access the core (and
  // the monitor) therefore see a free word unrelated to the instruction
  // stream; for RCTL PM_DATA_HI it is the read data. A write does not
  // change the anyconst table (see the monitor header).
  wire        core_pm_we, core_pm_re, core_pm_crc_clr;
  wire [7:0]  core_pm_addr;
  wire [15:0] core_pm_wdata;
  wire [7:0]  core_uio_dir, core_uio_od;
  wire [7:0]  mem_addr = (core_pm_we || core_pm_re) ? core_pm_addr : fetch_addr;
  wire [15:0] prog_sel = mem_addr[2] ?
                         (mem_addr[1] ? (mem_addr[0] ? prog7 : prog6)
                                      : (mem_addr[0] ? prog5 : prog4)) :
                         (mem_addr[1] ? (mem_addr[0] ? prog3 : prog2)
                                      : (mem_addr[0] ? prog1 : prog0));

  reg [15:0] instr_q;
  always @(posedge clk)
    instr_q <= prog_sel;

  // DR 0013 layer 2 (issue #138): the boot ROM as a second free, stable
  // table behind its own registered read port. It is always read at the
  // fetch address (the ROM has no data port).
  (* anyconst *) reg [15:0] rom0;
  (* anyconst *) reg [15:0] rom1;
  (* anyconst *) reg [15:0] rom2;
  (* anyconst *) reg [15:0] rom3;
  (* anyconst *) reg [15:0] rom4;
  (* anyconst *) reg [15:0] rom5;
  (* anyconst *) reg [15:0] rom6;
  (* anyconst *) reg [15:0] rom7;
  wire [15:0] rom_sel = fetch_addr[2] ?
                        (fetch_addr[1] ? (fetch_addr[0] ? rom7 : rom6)
                                       : (fetch_addr[0] ? rom5 : rom4)) :
                        (fetch_addr[1] ? (fetch_addr[0] ? rom3 : rom2)
                                       : (fetch_addr[0] ? rom1 : rom0));
  reg [15:0] rom_q;
  always @(posedge clk)
    rom_q <= rom_sel;
  // Core outputs this harness does not use: the monitor derives the fetch
  // source itself, and the macro's read gate is the cocotb bench's subject.
  wire core_fetch_rom, core_pm_fetch;

  reg exec_valid;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) exec_valid <= 1'b0;
    else          exec_valid <= run_phase;

  wire [7:0] core_uo, core_uio;
  protocol_core dut_core (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .run_phase    (run_phase),
      .instr_word   (instr_q),
      .fetch_addr   (fetch_addr),
      .rom_word     (rom_q),
      .fetch_rom    (core_fetch_rom),
      .pm_fetch     (core_pm_fetch),
      .port_ui_in   (ui_in),
      .port_uio_in  (uio_in),
      .port_uo_out  (core_uo),
      .port_uio_out (core_uio),
      .uio_dir      (core_uio_dir),
      .uio_od       (core_uio_od),
      .pm_we        (core_pm_we),
      .pm_re        (core_pm_re),
      .pm_addr      (core_pm_addr),
      .pm_wdata     (core_pm_wdata),
      .pm_crc_clr   (core_pm_crc_clr),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  pin_write_latency u_property (
      .clk        (clk),
      .rst_n      (rst_n_r),
      .exec_valid (exec_valid),
      .instr      (instr_q),
      .rom_instr  (rom_q),
      .ui_in      (ui_in),
      .uio_in     (uio_in),
      .uo_out     (core_uo),
      .uio_out    (core_uio),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  always @(posedge clk)
    if (long_win && (core_uo != 8'h00 || core_uio != 8'h00))
      cover (1'b1);

  // Harness-level cover (both builds): a mid-run reset returns a nonzero
  // pin to the documented reset value 0 -- the one sanctioned non-OUT
  // output change, shown reachable rather than assumed.
  reg       h_nonzero_seen = 1'b0;
  reg       h_rst_q        = 1'b0;
  always @(posedge clk) begin
    h_rst_q <= rst_n_r;
    if (rst_n_r && (core_uo != 8'h00 || core_uio != 8'h00))
      h_nonzero_seen <= 1'b1;
    if (h_nonzero_seen && h_rst_q && !rst_n_r)
      cover (core_uo == 8'h00 && core_uio == 8'h00);
  end

`ifdef FINE
  // F1: between-edge isolation. Sampled on the solver's global step clock:
  // across any two consecutive samples with no rising edge of `clk`
  // between them, both output registers must be exactly as before,
  // whatever ui_in / uio_in / rst_req did meanwhile.
  (* gclk *) reg gclk;
  reg       g_clk_q = 1'b0;
  reg [7:0] g_uo_q  = 8'h00, g_uio_q = 8'h00, g_ui_q = 8'h00;
  reg       g_valid = 1'b0;
  wire      g_rise  = clk && !g_clk_q;
  always @(posedge gclk) begin
    g_clk_q <= clk;
    g_uo_q  <= core_uo;
    g_uio_q <= core_uio;
    g_ui_q  <= ui_in;
    g_valid <= 1'b1;
    if (g_valid && !g_rise) begin
      assert (core_uo  == g_uo_q);
      assert (core_uio == g_uio_q);
    end
    // FC1: an input change between edges while a nonzero pin value is held
    // (the isolation F1 checks is exercised, not vacuous).
    if (g_valid && !g_rise && rst_n_r)
      cover (ui_in != g_ui_q && core_uo != 8'h00 && core_uo == g_uo_q);
    // FC2: an output update coinciding with a rising edge.
    if (g_valid && g_rise && rst_n_r)
      cover (core_uo != g_uo_q);
  end
`endif

endmodule

`default_nettype wire
