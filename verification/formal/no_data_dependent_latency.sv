/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal property `no_data_dependent_latency` (spec/verification-plan.md
 * section 2.1, target-spec row 3, issue #24).
 *
 * THE PROPERTY OF RECORD. This monitor operationalizes verification-plan
 * section 2.1's statement -- "for every instruction opcode, the number of
 * clock cycles between fetch and the retirement of that instruction ...
 * depends only on the instruction's own encoded fields (opcode, and for
 * WAIT, its immediate) -- never on the value of any general-purpose
 * register, any pin input, or any flag" -- as mechanical assertions over
 * DR 0001's latency table, extended by DR 0012's control space (issue
 * #135; `spec/decision-records/0012-control-space-and-runtime-pin-
 * direction.md` sections 1-2, "Every latency is fixed per index k, and k
 * is an immediate"):
 *
 *   L(instr) = imm8 + 1  if opcode == WAIT (4'b1011)
 *   L(instr) = 2         if WCTL (OUT 4'b1010, port [9:8] == 00) with
 *                           k = imm8 == 0x04 (PM_DATA_LO) or 0x05 (RUN)
 *   L(instr) = 2         if RCTL (IN 4'b1001, port [9:8] == 10) with
 *                           k = imm8 == 0x03 (PM_DATA_HI)
 *   L(instr) = 1         for everything else: every other opcode, every
 *                        other WCTL/RCTL index (assigned or reserved), and
 *                        the two reserved no-op encodings (OUT port 01,
 *                        IN port 11). HALT then idles forever.
 *
 * `WCTL RUN` is DR 0012's one computed jump (PC <- Rs). Like a branch, the
 * data chooses WHERE it lands and never HOW LONG it takes: the monitor
 * pins its occupancy to 2 cycles and leaves its target free.
 *
 * Because a 2-cycle control access gives the program memory's single port
 * to a data access, the word on `instr` during its second cycle is NOT the
 * access's own instruction (it is program-memory read data, or stale). The
 * monitor therefore decodes an occupant ONCE, on its first cycle, and
 * carries that decode (`occ_*`) for the rest of the occupancy; it never
 * re-decodes `instr` mid-occupancy. For WAIT this changes nothing (the
 * word is held stable for the whole stall).
 *
 * Data-independence is enforced by construction: every assertion's
 * right-hand side is a function of the instruction word alone (opcode,
 * immediate, pc). No register, pin, or flag value appears anywhere in the
 * expected-latency logic, so a datapath whose cycle count depended on data
 * cannot satisfy it. DR 0001's "data may choose *where* execution goes,
 * never *how long* an instruction takes" is encoded the same way: branch
 * targets may be either pc+1 or the encoded immediate (the outcome is free
 * -- data may steer it), but the *occupancy* of every instruction is
 * pinned to the table.
 *
 * BIND CONTRACT (deliberately minimal, and deliberately not invented
 * here): the monitor observes exactly the signals issue #18's core
 * datapath must already use to wire up the landed program memory
 * (rtl/protocol_program_memory.v, whose header documents this same
 * interface intent for #18):
 *
 *   - clk, rst_n
 *   - run_phase  (input to the core, from protocol_program_memory)
 *   - pc         (the core's program counter; drives fetch_addr)
 *   - instr      (the combinational same-cycle fetch read at pc)
 *
 * No internal core signal is referenced, so the same unmodified property
 * file binds to the real core once #18 lands. Until then it is exercised
 * against the two qualification fixtures in fixtures/ (see
 * run-no-data-dependent-latency.sh): a conformant timing-contract shell
 * (property must PASS) and a mutant with one deliberately data-dependent
 * WAIT early-out (property must FAIL -- the negative control that proves
 * the checker has teeth and is not vacuous).
 *
 * Proof status at the time this file landed (recorded in full in
 * verification/records/no-data-dependent-latency/): bounded model check at
 * depth 30 with NO assumptions on program contents or data inputs -- the
 * program is the harness's free anyconst table, so the check quantifies
 * over every opcode/immediate combination the solver can instantiate, with
 * free per-cycle data inputs throughout. Non-vacuity is proven by the
 * cover set (a multi-cycle WAIT observed to run its full table latency and
 * advance, taken and not-taken branches, a branch-to-self re-execution,
 * HALT freeze), and the property's detection power is proven by the mutant
 * negative control: a deliberately data-dependent WAIT early-out is caught
 * within 5 cycles with the exact expected counterexample. Unbounded
 * k-induction does not close on this monitor as shipped: the countdown
 * shadow is a function of observable *history* (it resynchronizes at every
 * instruction boundary), so arbitrary induction start states can
 * desynchronize it from the DUT. Closing induction needs an invariant that
 * couples the shadow to the real core's internal stall counter, which
 * requires exactly the internal-signal visibility that #18 will provide;
 * that follow-up is tracked with #18's landing. Depth 30 itself is a
 * measured feasibility bound of the z3 solver on this host (see the
 * runner's BMC_DEPTH note), not a semantic limit of the property -- the
 * assertions bind at every cycle and simply re-run deeper given a faster
 * solver.
 *
 * Issue #135 (DR 0012) changed this file: the latency table gained the
 * three 2-cycle control accesses, the occupant decode became latched (see
 * above), `WCTL RUN` got its own retirement rule, and covers c6-c9 were
 * added. The proof status of the extended monitor is the later record
 * under verification/records/no-data-dependent-latency/, not the paragraph
 * above, which describes the monitor as it first landed.
 */

`default_nettype none

module no_data_dependent_latency (
    input wire        clk,
    input wire        rst_n,
    input wire        run_phase,
    input wire [7:0]  pc,   // core program counter (protocol_program_memory.fetch_addr)
    input wire [15:0] instr // fetched instruction word (protocol_program_memory.instr_word)
);

  // ---------------------------------------------------------------------
  // Decoded fields and opcode classes (DR 0001 encoding: [15:12] opcode,
  // [11:10] Rd, [9:8] Rs/port, [7:0] imm8).
  // ---------------------------------------------------------------------

  wire [3:0] op  = instr[15:12];
  wire [7:0] imm = instr[7:0];

  localparam [3:0] OP_IN   = 4'b1001;
  localparam [3:0] OP_OUT  = 4'b1010;
  localparam [3:0] OP_WAIT = 4'b1011;
  localparam [3:0] OP_JMP  = 4'b1100;
  localparam [3:0] OP_BZ   = 4'b1101;
  localparam [3:0] OP_BNZ  = 4'b1110;
  localparam [3:0] OP_HALT = 4'b1111;

  // DR 0012 control-register indices with a 2-cycle access.
  localparam [7:0] K_PM_DATA_HI = 8'h03;
  localparam [7:0] K_PM_DATA_LO = 8'h04;
  localparam [7:0] K_RUN        = 8'h05;

  wire [1:0] port = instr[9:8];

  wire is_wait   = (op == OP_WAIT);
  wire is_branch = (op == OP_JMP) || (op == OP_BZ) || (op == OP_BNZ);
  wire is_halt   = (op == OP_HALT);
  wire is_wctl   = (op == OP_OUT) && (port == 2'b00);  // DR 0012: OUT port 00
  wire is_rctl   = (op == OP_IN)  && (port == 2'b10);  // DR 0012: IN  port 10
  wire is_run    = is_wctl && (imm == K_RUN);
  wire is_pm_wr  = is_wctl && (imm == K_PM_DATA_LO);
  wire is_pm_rd  = is_rctl && (imm == K_PM_DATA_HI);
  wire is_ctl2   = is_run || is_pm_wr || is_pm_rd;

  // The latency table (DR 0001 + DR 0012): the ONLY legal per-instruction
  // occupancy, as a function of the encoded fields alone.
  wire [8:0] tbl_lat = is_wait ? (9'd1 + {1'b0, imm})
                     : is_ctl2 ? 9'd2
                     :           9'd1;

  wire [7:0] pc_p1 = pc + 8'd1; // 8-bit wraparound at 255 -> 0 (8-bit PC)

  // ---------------------------------------------------------------------
  // Occupancy countdown shadow.
  //
  //   rem_eff(t) = remaining occupancy cycles of the instruction at pc,
  //                counted INCLUSIVE of cycle t.
  //
  // It is (re)established from the table exactly when a fresh instruction
  // occupies pc: at run-phase entry, or on the cycle after the previous
  // occupant's last cycle (rem_eff == 1 means the occupant retires this
  // cycle). Between those boundaries it counts down once per cycle. It
  // never reads any DUT state besides pc/instr, and no assertion below
  // references anything but this shadow and the instruction word.
  // ---------------------------------------------------------------------

  reg        prev_run;  // run_phase delayed one cycle
  reg [8:0]  rem;       // rem_eff delayed one cycle
  reg        sync;      // a boundary has been seen since reset (entry latches)

  wire entry = run_phase && !prev_run;  // first run-phase cycle after idle/reset

  // A fresh instruction occupies pc this cycle: decode it now, once.
  wire boundary = !sync || entry || (rem == 9'd1);  // rem == 1: previous occupant retired last cycle

  wire [8:0] rem_eff = boundary ? tbl_lat : (rem - 9'd1);

  // The occupant's decode, taken on its first cycle and held for the rest
  // of its occupancy (see the header: `instr` is not the occupant's own
  // word during the second cycle of a 2-cycle control access).
  reg        q_wait, q_br, q_halt, q_run, q_ctl2, q_pm_wr, q_pm_rd;
  reg [7:0]  q_imm;
  wire       occ_wait  = boundary ? is_wait   : q_wait;
  wire       occ_br    = boundary ? is_branch : q_br;
  wire       occ_halt  = boundary ? is_halt   : q_halt;
  wire       occ_run   = boundary ? is_run    : q_run;
  wire       occ_ctl2  = boundary ? is_ctl2   : q_ctl2;
  wire       occ_pm_wr = boundary ? is_pm_wr  : q_pm_wr;
  wire       occ_pm_rd = boundary ? is_pm_rd  : q_pm_rd;
  wire [7:0] occ_imm   = boundary ? imm       : q_imm;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prev_run <= 1'b0;
      rem      <= 9'd1;
      sync     <= 1'b0;
      q_wait   <= 1'b0;
      q_br     <= 1'b0;
      q_halt   <= 1'b0;
      q_run    <= 1'b0;
      q_ctl2   <= 1'b0;
      q_pm_wr  <= 1'b0;
      q_pm_rd  <= 1'b0;
      q_imm    <= 8'd0;
    end else begin
      prev_run <= run_phase;
      rem      <= run_phase ? rem_eff : 9'd1;
      if (entry)
        sync <= 1'b1;
      q_wait   <= occ_wait;
      q_br     <= occ_br;
      q_halt   <= occ_halt;
      q_run    <= occ_run;
      q_ctl2   <= occ_ctl2;
      q_pm_wr  <= occ_pm_wr;
      q_pm_rd  <= occ_pm_rd;
      q_imm    <= occ_imm;
    end
  end

  // ---------------------------------------------------------------------
  // Past-frame: one registered copy of everything the assertions need
  // about cycle t, so every assertion is evaluated at cycle t+1 as a
  // relation between cycle t's state and the pc the DUT produced for t+1.
  // ---------------------------------------------------------------------

  reg        f_valid;
  reg        f_run;
  reg [7:0]  f_pc;
  reg [7:0]  f_imm;
  reg [8:0]  f_rem_r;
  reg        f_wait_r, f_br_r, f_halt_r, f_entry_r;
  reg        f_run_r, f_ctl2_r, f_pm_wr_r, f_pm_rd_r, f_wctl1_r;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      f_valid   <= 1'b0;
      f_run     <= 1'b0;
      f_pc      <= 8'd0;
      f_imm     <= 8'd0;
      f_rem_r   <= 9'd1;
      f_wait_r  <= 1'b0;
      f_br_r    <= 1'b0;
      f_halt_r  <= 1'b0;
      f_entry_r <= 1'b0;
      f_run_r   <= 1'b0;
      f_ctl2_r  <= 1'b0;
      f_pm_wr_r <= 1'b0;
      f_pm_rd_r <= 1'b0;
      f_wctl1_r <= 1'b0;
    end else begin
      f_valid   <= 1'b1;
      f_run     <= run_phase;
      f_pc      <= pc;
      f_imm     <= occ_imm;
      f_rem_r   <= rem_eff;
      f_wait_r  <= occ_wait;
      f_br_r    <= occ_br;
      f_halt_r  <= occ_halt;
      f_entry_r <= entry;
      f_run_r   <= occ_run;
      f_ctl2_r  <= occ_ctl2;
      f_pm_wr_r <= occ_pm_wr;
      f_pm_rd_r <= occ_pm_rd;
      // a 1-cycle control write, decoded on its (only) cycle -- cover c9
      f_wctl1_r <= boundary && is_wctl && !is_ctl2;
    end
  end

  // ---------------------------------------------------------------------
  // Assertions (verification-plan section 2.1 / DR 0001 "Timing model").
  // ---------------------------------------------------------------------

  always @(posedge clk) begin
    if (f_valid) begin

      // (P1) Load/idle phase: the core holds pc at 0 (the program-memory
      // header's documented contract for #18), so run phase always begins
      // at address 0 (DR 0001: MODE dropping low "resets the program
      // counter to 0, and begins run phase").
      if (!f_run) begin
        assert (f_pc == 8'd0);
      end

      // (P2) Run-phase entry: the first instruction executes at pc 0.
      if (f_entry_r) begin
        assert (f_pc == 8'd0);
      end

      if (f_run) begin
        if (f_rem_r > 9'd1) begin
          // (P3) Mid-occupancy: pc must hold, and only WAIT and DR 0012's
          // 2-cycle control accesses may occupy more than one cycle. Any
          // data-dependent early exit or stretch of a stall violates
          // this -- the mutant fixtures exist to prove it.
          assert (pc == f_pc);
          assert (f_wait_r || f_ctl2_r);
        end else begin
          // (P4) Retirement cycle: the occupant retires now, so the next
          // pc is a function of the encoded fields alone.
          if (f_wait_r) begin
            // WAIT always advances to the next instruction (imm+1-th cycle).
            assert (pc == f_pc + 8'd1);
          end else if (f_halt_r) begin
            // HALT: core idles until reset (DR 0001 table row 1111).
            assert (pc == f_pc);
          end else if (f_run_r) begin
            // WCTL RUN (DR 0012): PC <- Rs. Its occupancy was pinned to
            // exactly 2 cycles by (P3) and the countdown; the target is
            // data and deliberately unconstrained -- data may choose
            // where, never how long.
          end else if (f_br_r) begin
            // Branch: 1 cycle taken or not taken; the target is either
            // pc+1 or the encoded immediate -- data may choose where,
            // never how long. pc+1 and imm coincide for wraparound cases;
            // a branch-to-self (imm == pc) legally holds pc while still
            // retiring every cycle.
            assert ((pc == f_pc + 8'd1) || (pc == f_imm));
          end else begin
            // Every other instruction -- including the two 2-cycle
            // program-memory accesses on their second cycle, every
            // 1-cycle WCTL/RCTL and the reserved no-ops: straight-line.
            assert (pc == f_pc + 8'd1);
          end
        end
      end
    end
  end

  // ---------------------------------------------------------------------
  // Covers (non-vacuity): the checks above must actually be exercised on
  // trajectories the solver explored, or a BMC "pass" would prove nothing.
  // ---------------------------------------------------------------------

  reg saw_multi_wait;   // a WAIT with imm >= 2 was seen mid-stall
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)                          saw_multi_wait <= 1'b0;
    else if (run_phase && occ_wait && rem_eff > 9'd2)
                                         saw_multi_wait <= 1'b1;
  end

  always @(posedge clk) begin
    if (f_valid && f_run) begin
      // (c1) A multi-cycle WAIT ran its full table latency and advanced.
      cover (saw_multi_wait && f_wait_r && (f_rem_r == 9'd1) && (pc == f_pc + 8'd1));
      // (c2) A branch retired in 1 cycle with a data-chosen taken target.
      cover (f_br_r && (pc == f_imm) && (f_imm != f_pc + 8'd1));
      // (c3) A branch retired in 1 cycle not taken.
      cover (f_br_r && (pc == f_pc + 8'd1));
      // (c4) A branch-to-self held pc across a genuine retirement.
      cover (f_br_r && (pc == f_pc) && (f_imm == f_pc));
      // (c5) HALT froze the core.
      cover (f_halt_r && (pc == f_pc));
      // (c6) A WCTL PM_DATA_LO ran its full 2 cycles and advanced.
      cover (f_pm_wr_r && (f_rem_r == 9'd1) && (pc == f_pc + 8'd1));
      // (c7) An RCTL PM_DATA_HI ran its full 2 cycles and advanced.
      cover (f_pm_rd_r && (f_rem_r == 9'd1) && (pc == f_pc + 8'd1));
      // (c8) A WCTL RUN retired after 2 cycles to a data-chosen target
      //      that is neither the next instruction nor itself.
      cover (f_run_r && (f_rem_r == 9'd1) && (pc != f_pc + 8'd1) && (pc != f_pc));
      // (c9) A 1-cycle control write (any other WCTL index) retired in one cycle.
      cover (f_wctl1_r && (f_rem_r == 9'd1) && (pc == f_pc + 8'd1));
    end
  end

endmodule

`default_nettype wire
