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
 *     Since DR 0013 layer 2 (issue #138) that is the timing of BOTH ways
 *     into the run phase as the core sees them -- straight into the boot
 *     ROM (MODE low), or into program memory after a serial load -- and
 *     which of the two it is reaches the core as `serial_loaded`, which
 *     this harness leaves free, as a per-trace constant (see the REAL_CORE
 *     notes below).
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
  //     not this latency property's. `pm_crc`, a data input the control
  //     space reads from the program memory, is free per-cycle (`anyseq`):
  //     the latency must not depend on it either. (`serial_loaded` was
  //     free per-cycle too until issue #138; see the next item.)
  //   - DR 0013 layer 2 (issue #138): the core has two instruction sources
  //     and a fetch-source mux. Before this, MODE low at reset ran program
  //     memory, and this harness's one program table was that memory. Now
  //     there are TWO free tables: `prog*` is program memory and `rom*` is
  //     the boot ROM, each 8 `anyconst` words read through its own
  //     registered port at the same fetch address -- so the proof
  //     quantifies over every boot ROM as well as every program, not over
  //     the one committed boot image. The monitor's `instr` is the word
  //     the core decodes this cycle: `rom_q` while the core's `fetch_rom`
  //     output is high, `instr_q` otherwise. `fetch_rom` is a core OUTPUT
  //     (it is BOOT_STATUS[1]), not an internal signal, and the monitor
  //     file is untouched.
  //   - `serial_loaded` is now a free CONSTANT (`anyconst`), no longer free
  //     per-cycle. It selects the fetch source, and in the design it cannot
  //     change while anything executes: rtl/protocol_program_memory.v sets
  //     it on the very edge that starts the run phase and only reset clears
  //     it. A per-cycle-free value would swap the instruction under an
  //     occupant the core has already decoded -- for example under a HALT,
  //     which the monitor would then re-decode as something else -- a
  //     behaviour no reachable state of the design has, and the property
  //     fails on it for that reason alone (tried, and recorded in the
  //     evidence record). As a constant it covers both ways into the run
  //     phase: 1 = after a serial load (program memory from the first
  //     instruction, never the ROM), 0 = MODE low (the boot ROM until a
  //     WCTL RUN). The one in-run source switch the design has, at RUN, is
  //     therefore inside the proof, with a free ROM on one side and a free
  //     program on the other. Cost: BOOT_STATUS[0] as *data* is constant
  //     within a trace; it is a 1-cycle RCTL index like any other.
  //     That the mux selects the RIGHT source is not this property's
  //     subject; `pin_write_latency`'s shadow model derives the source
  //     independently and owns that.
  (* anyseq *) wire [15:0] free_pm_crc;
  (* anyconst *) reg       free_serial_loaded;

  // The free, stable boot ROM (DR 0013 layer 2): 8 more anyconst words.
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
  wire        core_fetch_rom, core_pm_fetch;
  wire        core_pm_we, core_pm_re, core_pm_crc_clr;
  wire [7:0]  core_pm_addr;
  wire [15:0] core_pm_wdata;
  wire [7:0]  core_uio_dir, core_uio_od;
  assign mem_addr = (core_pm_we || core_pm_re) ? core_pm_addr : fetch_addr;

  reg [15:0] instr_q;
  always @(posedge clk)
    instr_q <= prog_sel;

  // The boot ROM's registered read: always at the fetch address (the ROM
  // has no data port), one cycle of delay like the macro's.
  reg [15:0] rom_q;
  always @(posedge clk)
    rom_q <= rom_sel;

  // The word the core decodes this cycle.
  wire [15:0] exec_word = core_fetch_rom ? rom_q : instr_q;

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
      .rom_word     (rom_q),
      .fetch_rom    (core_fetch_rom),
      .pm_fetch     (core_pm_fetch),
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
      .instr     (exec_word)
  );

  // Harness-level covers for the fetch-source mux (non-vacuity of the
  // DR 0013 part of the binding; the monitor's own covers c1-c9 do not
  // know there are two sources).
  //   h1: an instruction decoded from the boot ROM occupies execute;
  //   h2: one decoded from program memory does, after one from the ROM
  //       did -- the source switched under the property;
  //   h3: that switch followed a WCTL RUN decoded from the ROM -- the way
  //       the design leaves the boot ROM, and with `serial_loaded` a
  //       constant the only way this harness can;
  //   h4: a 2-cycle program-memory access (RCTL PM_DATA_HI) decoded from
  //       the ROM completed its stall -- the boot program's own way of
  //       reading program memory as data.
  reg h_rom_seen = 1'b0;
  reg h_rom_run  = 1'b0;   // previous cycle: the stall cycle of a RUN decoded from the ROM
  reg h_run1     = 1'b0;   // previous cycle: a RUN decoded from the ROM, first cycle
  reg h_pmrd1    = 1'b0;   // previous cycle: an RCTL PM_DATA_HI decoded from the ROM, first cycle
  wire h_is_run  = (exec_word[15:12] == 4'hA) && (exec_word[9:8] == 2'b00) && (exec_word[7:0] == 8'h05);
  wire h_is_pmrd = (exec_word[15:12] == 4'h9) && (exec_word[9:8] == 2'b10) && (exec_word[7:0] == 8'h03);
  always @(posedge clk or negedge rst_n_r) begin
    if (!rst_n_r) begin
      h_rom_seen <= 1'b0;
      h_rom_run  <= 1'b0;
      h_run1     <= 1'b0;
      h_pmrd1    <= 1'b0;
    end else begin
      if (exec_phase && core_fetch_rom) h_rom_seen <= 1'b1;
      h_run1    <= exec_phase && core_fetch_rom && h_is_run && !h_run1 && !h_pmrd1;
      h_rom_run <= h_run1 && core_fetch_rom;
      h_pmrd1   <= exec_phase && core_fetch_rom && h_is_pmrd && !h_run1 && !h_pmrd1 && core_pm_re;
    end
  end
  always @(posedge clk) begin
    if (rst_n_r) begin
      cover (exec_phase && core_fetch_rom);                                   // h1
      cover (exec_phase && !core_fetch_rom && h_rom_seen);                    // h2
      cover (exec_phase && !core_fetch_rom && h_rom_run);                     // h3
      cover (exec_phase && core_fetch_rom && h_pmrd1);                        // h4
    end
  end
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
