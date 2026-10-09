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
 *     PASS); -D MUTANT = the data-dependent WAIT early-out mutant and
 *     -D MUTANT_CTL = the data-dependent control-access early-out mutant
 *     (issue #135, DR 0012) -- the property must FAIL on each with a
 *     counterexample. When issue #18's core lands, this
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

  // The address the (modeled) program memory reads this cycle. For the
  // fixtures it is the fetch address. For the real core it is the macro's
  // own address mux (rtl/protocol_program_memory.v, DR 0012): a
  // program-memory data access takes the single port, so the word that
  // comes back the next cycle is the table entry at PM_ADDR, not at the
  // fetch address. Modeling that mux, rather than always reading at
  // fetch_addr, hands the core a free, unrelated word during the stall
  // cycle of every 2-cycle program-memory access -- so the proof also
  // shows the core's timing does not depend on that word.
  wire [7:0]  mem_addr;

  wire [15:0] prog_sel = mem_addr[2] ?
                         (mem_addr[1] ? (mem_addr[0] ? prog7 : prog6)
                                      : (mem_addr[0] ? prog5 : prog4)) :
                         (mem_addr[1] ? (mem_addr[0] ? prog3 : prog2)
                                      : (mem_addr[0] ? prog1 : prog0));
  assign instr_word = prog_sel;

`ifdef REAL_CORE
  // Second DUT binding (issue #90): the shipped rtl/protocol_core.v, read
  // unmodified (the core mutant leg feeds it a text-mutated COPY, see the
  // runner). Differences from the fixture binding, all in this harness and
  // none in the property file:
  //
  //   - Program memory: the real core consumes `instr_word` ONE CYCLE AFTER
  //     it presents `fetch_addr` (DR 0005 fetch-ahead; the PDK SRAM macro's
  //     read is synchronous). `instr_q` models exactly that registered read
  //     of the same free anyconst table, so the proof still quantifies over
  //     every program. (Its power-on value is free; it is overwritten on
  //     every edge, and the monitor ignores it outside run phase.)
  //   - Monitor pc binding: the monitor's `pc` is the instruction occupying
  //     execute NOW, i.e. the core's `pc` register. Yosys has no
  //     hierarchical references, so the harness reconstructs it from the
  //     core's port-level contract (the core's own rule: pc <= fetch_addr
  //     every run-phase edge, pc <= 0 otherwise, 0 at reset). This uses no
  //     core-internal signal.
  //   - Monitor run_phase binding: DR 0005's priming cycle (first run_phase
  //     cycle presents address 0 and executes nothing) is a fixed, data-free
  //     +1 per reset. The monitor's run_phase means "an instruction occupies
  //     pc this cycle", so it is bound to run_phase delayed one cycle
  //     (== the core's fetch_valid). The monitor file is untouched.
  //   - The core's pin inputs are free per-cycle inputs (data freedom).
  //   - DR 0012 (issue #135): the core's program-memory access port is
  //     bound to the macro address mux above (`mem_addr`). A PM write does
  //     not change the anyconst table -- the table stays the free, stable
  //     program the proof quantifies over, which is the abstraction this
  //     harness has always made; what a write does to memory *contents* is
  //     the cocotb bench's subject (verification/test_control_space.py),
  //     not this latency property's. The two data inputs the control
  //     space reads from the program memory, `pm_crc` and `serial_loaded`,
  //     are free per-cycle (`anyseq`): the latency must not depend on
  //     them either.
  (* anyseq *) wire [15:0] free_pm_crc;
  (* anyseq *) wire        free_serial_loaded;
  wire        core_pm_we, core_pm_re, core_pm_crc_clr;
  wire [7:0]  core_pm_addr;
  wire [15:0] core_pm_wdata;
  wire [7:0]  core_uio_dir, core_uio_od;
  assign mem_addr = (core_pm_we || core_pm_re) ? core_pm_addr : fetch_addr;

  reg [15:0] instr_q;
  always @(posedge clk)
    instr_q <= prog_sel;

  reg       exec_phase;
  reg [7:0] pc_q;
  always @(posedge clk or negedge rst_n_r)
    if (!rst_n_r) begin
      exec_phase <= 1'b0;
      pc_q       <= 8'd0;
    end else begin
      exec_phase <= run_phase;
      pc_q       <= run_phase ? fetch_addr : 8'd0;
    end

  wire [7:0] core_uo, core_uio;
  protocol_core dut_core (
      .clk          (clk),
      .rst_n        (rst_n_r),
      .run_phase    (run_phase),
      .instr_word   (instr_q),
      .fetch_addr   (fetch_addr),
      .port_ui_in   (branch_data),
      .port_uio_in  (mutant_early_data),
      .port_uo_out  (core_uo),
      .port_uio_out (core_uio),
      .uio_dir      (core_uio_dir),
      .uio_od       (core_uio_od),
      .pm_we        (core_pm_we),
      .pm_re        (core_pm_re),
      .pm_addr      (core_pm_addr),
      .pm_wdata     (core_pm_wdata),
      .pm_crc_clr   (core_pm_crc_clr),
      .pm_crc       (free_pm_crc),
      .serial_loaded(free_serial_loaded)
  );

  no_data_dependent_latency u_property (
      .clk       (clk),
      .rst_n     (rst_n_r),
      .run_phase (exec_phase),
      .pc        (pc_q),
      .instr     (instr_q)
  );
`else
  assign mem_addr = fetch_addr;  // fixtures: same-cycle fetch at pc
`ifdef MUTANT
  timing_contract_mutant dut_core (
`elsif MUTANT_CTL
  // Issue #135: the control-space negative control (a data-dependent
  // early-out of a DR 0012 2-cycle access).
  timing_contract_mutant_ctl dut_core (
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
`endif

endmodule

`default_nettype wire
