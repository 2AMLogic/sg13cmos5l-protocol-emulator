/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal harness top for `i2c_ack_window` (issue #259, part of #243),
 * bound to the shipped rtl/protocol_core.v (read unmodified) running a
 * CONSTANT committed image on the actual core.
 *
 * Sibling of formal_top_pin_write.v, NOT a copy of its memory model: that
 * harness quantifies over eight free `anyconst` program words; this one
 * runs the real firmware, so the program is the `i2c_image_rom` module the
 * runner generates from a hex image (the committed firmware/build/
 * i2c_{fast,std}.hex for the proof legs, a freshly assembled scratch image
 * for each mutant). Both are the same shape: a combinational 256-word case
 * ROM (unused words 0000) behind a REGISTERED read port, which models DR
 * 0005's one-cycle synchronous fetch exactly as formal_top_pin_write.v's
 * `instr_q` does.
 *
 * MODEL AND ASSUMPTIONS (stated here so a reader of a result can check them)
 *   - Reset/load: `rst_n` is low for the first two cycles, then released.
 *     The serial load phase is NOT modelled: the image is already in
 *     program memory, `serial_loaded` is 1 (so the core fetches program
 *     memory, never the boot ROM, whose port is tied to 0), `run_phase`
 *     rises the cycle after reset release and `exec_valid` is run_phase
 *     delayed one cycle (DR 0005's priming cycle). Later start-up delay
 *     (a longer load phase) only shifts every event in time because the
 *     core is held in reset-state until `run_phase`; that is an argument,
 *     not something this harness explores. No mid-run reset.
 *   - Memory: the image is constant. The core's program-memory strobes
 *     (pm_we / pm_re) are asserted never to fire (the images use no
 *     program-memory access), so the fetch address is always the PC
 *     address; the constant ROM would otherwise not model a write.
 *   - Pins: uio_oe/uio_out are the top level's own formulas
 *     (src/tt_um_2amlogic_protocol_emulator.v) from the core's uio_out,
 *     uio_dir and uio_od. SCL is uio[2], SDA is uio[3] (DR 0010). Each line
 *     is open-drain with a pull-up: low iff the controller drives it low
 *     (oe & ~out) or, for SDA, the modelled peripheral pulls it low.
 *     `uio_in` is {4'b0, sda, scl, 2'b0}: the resolved lines, so the
 *     firmware reads back the wired-AND of itself and the peripheral, as
 *     on silicon. Zero delay, NO clock stretching (the peripheral never
 *     drives SCL), ui_in is free and unused by the images.
 *   - The one free per-cycle input besides ui_in is `ack_raw` (peripheral
 *     pulls SDA low). The monitor constrains it to I2C-legal behaviour
 *     (see i2c_ack_window.sv, E1..E3); it never requires an early answer.
 *   - `in_pulse` (the sampling instant the monitor grades) is decoded here
 *     from the instruction word on the registered fetch port and the
 *     harness's own exec_valid: opcode 9 (IN) from port 01 (UIO_IN). The
 *     images only ever hold WAIT words (stable) across stalls, so an IN
 *     word on the port executes exactly once.
 *
 * Elaborated EDGE only (one solver step per clock); there is no FINE
 * variant for this property.
 */

`default_nettype none

module formal_top_i2c_ack (
    input wire       clk,
    input wire [7:0] ui_in,
    input wire       ack_raw
);

  reg rst_pre = 1'b0, rst_n_r = 1'b0;
  always @(posedge clk) begin
    rst_pre <= 1'b1;
    rst_n_r <= rst_pre;
  end

  reg run_phase_r = 1'b0;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) run_phase_r <= 1'b0;
    else          run_phase_r <= 1'b1;
  wire run_phase = run_phase_r;

  reg exec_valid;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) exec_valid <= 1'b0;
    else          exec_valid <= run_phase;

  // Constant image behind a registered fetch port.
  wire [7:0]  fetch_addr;
  wire [15:0] image_word;
  i2c_image_rom u_image (.addr(fetch_addr), .word(image_word));
  reg [15:0] instr_q;
  always @(posedge clk)
    instr_q <= image_word;

  // Bus: controller pad state through the top level's formulas.
  wire [7:0] core_uio_out, uio_dir, uio_od;
  wire [7:0] core_uo;
  wire [7:0] uio_out = core_uio_out & ~uio_od;
  wire [7:0] uio_oe  = (uio_od & ~core_uio_out) | (~uio_od & uio_dir);

  wire scl_ctrl_low = uio_oe[2] && !uio_out[2];
  wire sda_ctrl_low = uio_oe[3] && !uio_out[3];
  wire scl = !scl_ctrl_low;
  wire ack_low;                           // effective peripheral drive (from the monitor)
  wire sda = !(sda_ctrl_low || ack_low);
  wire [7:0] uio_in = {4'b0000, sda, scl, 2'b00};

  wire        core_pm_we, core_pm_re, core_pm_crc_clr, core_fetch_rom, core_pm_fetch;
  wire [7:0]  core_pm_addr;
  wire [15:0] core_pm_wdata;

  protocol_core dut_core (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .run_phase    (run_phase),
      .instr_word   (instr_q),
      .fetch_addr   (fetch_addr),
      .rom_word     (16'h0000),
      .fetch_rom    (core_fetch_rom),
      .pm_fetch     (core_pm_fetch),
      .port_ui_in   (ui_in),
      .port_uio_in  (uio_in),
      .port_uo_out  (core_uo),
      .port_uio_out (core_uio_out),
      .uio_dir      (uio_dir),
      .uio_od       (uio_od),
      .pm_we        (core_pm_we),
      .pm_re        (core_pm_re),
      .pm_addr      (core_pm_addr),
      .pm_wdata     (core_pm_wdata),
      .pm_crc_clr   (core_pm_crc_clr),
      .pm_crc       (16'h0000),
      .serial_loaded(1'b1)
  );

  // IN of port 01 executes this cycle (see header).
  wire in_pulse = exec_valid && instr_q[15:12] == 4'h9 && instr_q[9:8] == 2'd1;

  i2c_ack_window u_property (
      .clk     (clk),
      .rst_n   (rst_n_r),
      .scl     (scl),
      .sda     (sda),
      .sda_oe  (uio_oe[3]),
      .p_raw   (ack_raw),
      .p_low   (ack_low),
      .in_pulse(in_pulse)
  );

  // Harness-model assumptions that are PROVED rather than assumed.
  always @(posedge clk) if (rst_n_r) begin
    h_no_pm_strobes: assert (!core_pm_we && !core_pm_re);   // constant image is never written/read as data
    h_fetch_from_program_memory: assert (!core_fetch_rom);              // program memory is the fetch source
  end

endmodule

`default_nettype wire
