/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal harness top for `no_data_dependent_latency` (issue #24).
 *
 * Wiring:
 *
 *   - The PROGRAM is modeled as a table of 8 `anyconst` 16-bit words
 *     selected by pc[2:0]: free (the solver chooses every instruction --
 *     the proof quantifies over every opcode/immediate combination) and
 *     stable (an anyconst holds its value for all time, exactly like a
 *     program-memory read at a held pc). This is a deliberate, documented
 *     abstraction of `rtl/protocol_program_memory.v`'s fetch port: the
 *     landed module wired in with its contents as a free-initial-value SMT
 *     array is semantically identical for this property but makes the
 *     z3/BMC problem exponentially slower (measured: >45 s per step at
 *     depth 5, vs. well under a second per step here). What the latency
 *     property needs from memory is exactly "a stable, freely-chosen
 *     instruction at each pc" -- the table provides that. The memory's own
 *     loading/phase behavior is verified separately by the
 *     program-load-phase cocotb record; nothing there overlaps this
 *     property. Addresses alias modulo 8 (pc 0 and 8 fetch the same word);
 *     every assertion in the property is instruction-local, so aliasing
 *     removes no checkable behavior.
 *
 *   - `run_phase` is a 2-line faithful extraction of the program memory's
 *     own phase timing for the mode_pin-tied-low case (DR 0001 / the
 *     module header: reset, then one mode-sampling edge, then run phase):
 *     rst_n low holds it low; the first post-release edge latches the
 *     (constant-low) mode line and raises run_phase from the next cycle.
 *
 *   - The DUT under the property is selected by the MUTANT define:
 *     default = the conformant timing-contract fixture (property must
 *     PASS); -D MUTANT = the data-dependent early-out mutant (property
 *     must FAIL with a counterexample). When issue #18's core lands, this
 *     ifdef is where the real core module slots in -- the monitor and the
 *     property file stay byte-identical.
 *
 *   - rst_n is asserted for the first cycle after time 0 and released
 *     from then on (init attribute), giving every block a defined reset
 *     without an assumption.
 *
 *   - branch_data / mutant_early_data are free top-level inputs: the
 *     solver may vary them every cycle, which is exactly the data
 *     freedom the property must be robust to.
 */

`default_nettype none

module formal_top (
    input wire        clk,
    input wire [7:0]  branch_data,
    input wire [7:0]  mutant_early_data
);

  // Reset sequencing: low at t=0, released on the first edge, high after.
  reg rst_n_r = 1'b0;
  always @(posedge clk)
    rst_n_r <= 1'b1;

  // run_phase: faithful extraction of protocol_program_memory's timing
  // with mode_pin tied low (reset -> one mode-sampling edge -> run).
  reg started     = 1'b0;
  reg run_phase_r = 1'b0;
  always @(posedge clk or negedge rst_n_r) begin
    if (!rst_n_r) begin
      started     <= 1'b0;
      run_phase_r <= 1'b0;
    end else if (!started) begin
      started     <= 1'b1;
      run_phase_r <= 1'b1;  // mode_pin == 0: enter run phase directly
    end
  end
  wire run_phase = run_phase_r;

  // The free, stable program: 8 anyconst words, selected by pc[2:0].
  (* anyconst *) reg [15:0] prog0;
  (* anyconst *) reg [15:0] prog1;
  (* anyconst *) reg [15:0] prog2;
  (* anyconst *) reg [15:0] prog3;
  (* anyconst *) reg [15:0] prog4;
  (* anyconst *) reg [15:0] prog5;
  (* anyconst *) reg [15:0] prog6;
  (* anyconst *) reg [15:0] prog7;

  wire [7:0]  fetch_addr;
  wire [15:0] instr_word;

  wire [15:0] prog_sel = fetch_addr[2] ?
                         (fetch_addr[1] ? (fetch_addr[0] ? prog7 : prog6)
                                        : (fetch_addr[0] ? prog5 : prog4)) :
                         (fetch_addr[1] ? (fetch_addr[0] ? prog3 : prog2)
                                        : (fetch_addr[0] ? prog1 : prog0));
  assign instr_word = prog_sel;

`ifdef MUTANT
  timing_contract_mutant dut_core (
`else
  timing_contract_conformant dut_core (
`endif
      .clk               (clk),
      .rst_n             (rst_n_r),
      .run_phase         (run_phase),
      .instr_word        (instr_word),
      .branch_data       (branch_data),
      .mutant_early_data (mutant_early_data),
      .fetch_addr        (fetch_addr)
  );

  // The property of record, observing exactly the bind-contract signals.
  no_data_dependent_latency u_property (
      .clk       (clk),
      .rst_n     (rst_n_r),
      .run_phase (run_phase),
      .pc        (fetch_addr),
      .instr     (instr_word)
  );

endmodule

`default_nettype wire
