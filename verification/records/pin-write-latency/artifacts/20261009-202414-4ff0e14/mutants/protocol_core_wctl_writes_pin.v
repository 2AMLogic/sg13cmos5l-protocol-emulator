/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Core datapath per `spec/decision-records/0001-isa.md` (issue #18,
 * target-spec rows 1/3/6), with the fetch-ahead amendment of
 * `spec/decision-records/0005-program-memory-implementation.md`.
 *
 * The ISA is the product: this is a pin-timing engine, not a general
 * CPU -- no RAM, no stack, no interrupts, and no fixed-function protocol
 * peripherals. Every instruction the ISA defines retires in exactly one
 * clock cycle except `WAIT`, whose duration is fixed by its own
 * immediate, and DR 0012's three control accesses that take a fixed 2
 * cycles (`WCTL PM_DATA_LO`, `WCTL RUN`, `RCTL PM_DATA_HI`; the k that
 * selects them is an immediate too), so the cycle count of any program is
 * computable from the instruction stream alone (DR 0001's timing-determinism guarantee,
 * target-spec row 3).
 *
 * ---------------------------------------------------------------------
 * TIMING MODEL: single-cycle execute, one-cycle-ahead fetch
 * ---------------------------------------------------------------------
 *
 * DR 0001 as authored assumed an asynchronous-read program memory
 * ("fetch and execute happen in the same cycle"). DR 0005 replaced the
 * flip-flop array with the PDK's `RM_IHPSG13_1P_256x16_c2_bm_bist` SRAM
 * macro, whose read is synchronous with one-cycle data access, and
 * amended that one sentence:
 *
 *   > The datapath is single-cycle and non-pipelined in its *execute*
 *   > stage; instruction fetch is one cycle ahead of execute. The address
 *   > presented to program memory at the clock edge ending cycle N is the
 *   > address of the instruction that executes in cycle N+1, and is
 *   > computed combinationally within cycle N from the instruction
 *   > executing in cycle N and the current flags -- i.e. it is exactly
 *   > DR 0001's existing next-PC mux, moved to the memory's address port
 *   > instead of its output.
 *
 * That is exactly what `next_addr` below is, and `fetch_addr` is it
 * driven straight out to the memory's address port. Concretely:
 *
 *   cycle N   : `instr_word` holds mem[pc]; the instruction at `pc`
 *               executes; `next_addr` is computed combinationally.
 *   edge N/N+1: the macro captures `next_addr`; `pc <= next_addr`.
 *   cycle N+1 : `instr_word` holds mem[next_addr]; `pc` == next_addr;
 *               that instruction executes. One instruction per cycle.
 *
 * **This costs zero cycles per instruction**, and that is a property of
 * the ratified ISA rather than luck: every control transfer DR 0001
 * defines -- `JMP imm8`, `BZ imm8`, `BNZ imm8` -- takes its target from
 * an immediate in the instruction word, and `Z` was written by the
 * *previous* instruction, so the next address is always combinationally
 * available in the same cycle the branch executes. There is no
 * register-indirect or computed branch, hence no branch bubble that
 * could be taken or not taken, hence branch *cost* stays independent of
 * data and row 3's guarantee holds by construction. DR 0012's `WCTL RUN`
 * is the one computed jump (PC <- Rs); it pays its fetch cycle *always*
 * (a fixed 2 cycles, see CONTROL SPACE below), so its cost is still
 * independent of the target.
 *
 * The one visible cost is at run-phase entry, and it is fixed and
 * data-independent (DR 0005): while `run_phase` is low the core holds
 * `pc` at 0 and executes nothing; on the **first** cycle `run_phase` is
 * high it presents address 0 without executing (`fetch_valid` is still
 * 0, and `instr_word` is whatever the macro last read); on the
 * **second** it executes the instruction at address 0. A one-time +1
 * cycle per reset, which perturbs no cycle-budget sketch in DR 0001 --
 * all of them count from the first executed instruction.
 *
 * `WAIT imm8` holds the address (so the macro re-reads the same word and
 * `instr_word` is stable across the stall) and releases with `pc + 1` on
 * the final stall cycle, so the instruction after the `WAIT` executes
 * in the cycle immediately following -- total cost exactly `imm8 + 1`
 * cycles, with no fetch bubble added. `HALT` holds the address
 * indefinitely.
 *
 * ---------------------------------------------------------------------
 * REST OF THE CONTRACT (all of it DR 0001, section names in quotes)
 * ---------------------------------------------------------------------
 *
 *   - Four 8-bit general-purpose registers R0-R3 and a 2-bit flag
 *     register {Z, C} ("Register and pin model"). ADD/SUB write Z and
 *     C; AND/OR/XOR write Z only (C unchanged); SHF writes C only (the
 *     shifted-out bit; Z unchanged). BZ/BNZ read Z. C is write-only
 *     state in this ISA revision -- no instruction consumes it -- so it
 *     is observable only as the internal `flag_c` register (the cocotb
 *     bench checks it there, white-box, and says so where it does).
 *
 *   - SUB's C is the borrow convention: C = 1 when the minuend is less
 *     than the subtrahend (the 9-bit subtract's MSB, the same bit x86's
 *     SUB flag computes). DR 0001 says only "sets Z, C" -- no
 *     instruction in this revision reads C (BZ/BNZ read Z only), so the
 *     polarity is this module's pin of a detail the record leaves open,
 *     chosen to match what the arithmetic itself produces. A future ISA
 *     revision that exposes C (branch-on-carry, rotate-through-carry)
 *     must ratify the polarity in a decision record before relying on
 *     it.
 *
 *   - Four addressable 8-bit pin ports ("Register and pin model"):
 *       port 00 -> ui_in  (read-only)        port 10 -> uo_out (write-only)
 *       port 01 -> uio_in (read-only)        port 11 -> uio_out(write-only)
 *     `IN` samples the port value at the retiring clock edge ("Sample
 *     on edge"); `IN` to a write-only port is a no-op that still costs
 *     its 1 cycle. `OUT` writes the port's output register at the
 *     retiring edge ("Drive on edge"), so the new pin value is visible
 *     exactly one clock cycle after the `OUT` executes; `OUT` to a
 *     read-only port is a likewise-1-cycle no-op -- EXCEPT the two
 *     encodings DR 0012 gives a meaning (the control space, below).
 *
 *   - Encoding ("Encoding"): fixed 16-bit words,
 *       [15:12] opcode, [11:10] Rd, [9:8] Rs/port, [7:0] imm8.
 *     For `IN Rd, port` the destination register is [11:10] and the port
 *     is [9:8]. For `OUT port, Rs` the *source* register sits in the
 *     [11:10] field and the port in [9:8] -- the encoding keeps one
 *     uniform register field and one uniform port field for both I/O
 *     ops, exactly as DR 0001's field table reads. `SHF`'s direction bit
 *     is Rs[0] (0 = right, 1 = left).
 *
 *   - `HALT` stops fetch/execute: the core idles (PC, registers, flags
 *     and pin registers all hold) until the next `rst_n` pulse.
 *
 *   - `ena` is deliberately not a port: DR 0001's load protocol is
 *     reset-gated, and the Tiny Tapeout template documents `ena` as
 *     "always 1 when the design is powered, so you can ignore it".
 *
 * ---------------------------------------------------------------------
 * CONTROL SPACE (DR 0012, issue #135)
 * ---------------------------------------------------------------------
 *
 * `spec/decision-records/0012-control-space-and-runtime-pin-direction.md`
 * gives two of DR 0001's no-op encodings a meaning, with the control
 * register index `k` in the otherwise-unused imm8 field:
 *
 *   `OUT` port 00, imm8 = k  ->  `WCTL k, Rs`  (control register k <- Rs;
 *                                Rs rides the [11:10] field, as for OUT)
 *   `IN`  port 10, imm8 = k  ->  `RCTL Rd, k`  (Rd <- control register k)
 *   `OUT` port 01, `IN` port 11 stay 1-cycle no-ops (reserved).
 *
 * Register map (DR 0012 section 2), with the per-k latency it fixes:
 *
 *   k     name         W                          R                      cyc
 *   0x00  UIO_DIR      push-pull enable per pin   register value         1
 *   0x01  UIO_OD       open-drain enable per pin  register value         1
 *   0x02  PM_ADDR      PM word address            register value         1
 *   0x03  PM_DATA_HI   latch the high byte (1)    read PM[PM_ADDR]: Rd <- W1 R2
 *                                                 high byte, latch low
 *   0x04  PM_DATA_LO   commit {HI, Rs} to         latched low byte,      W2 R1
 *                      PM[PM_ADDR], PM_ADDR++     then PM_ADDR++
 *   0x05  RUN          PC <- Rs                   (unassigned: 0x00)     W2
 *   0x06  PM_CRC_LO    clears the CRC             CRC[7:0]               1
 *   0x07  PM_CRC_HI    clears the CRC             CRC[15:8]              1
 *   0x08  BOOT_STATUS  (no-op)                    bit0 serial-loaded,    1
 *                                                 bit1 boot ROM (0: no
 *                                                 ROM yet, DR 0013/#138)
 *   0x09  HW_ID        (no-op)                    the HW_ID parameter    1
 *   other              1-cycle no-op              0x00 in 1 cycle        1
 *
 * Every latency is a function of the opcode, the port field and the
 * immediate k alone -- never of a register, pin or flag -- so DR 0001's
 * row-3 guarantee holds unchanged; the formal property
 * `no_data_dependent_latency` carries this exact table. No control
 * access touches Z or C.
 *
 * The three 2-cycle accesses share one mechanism, `ctl_stall`. In the
 * access's own cycle N the core holds `fetch_addr` at `pc` (as WAIT does)
 * and, for the two program-memory accesses, asks the program memory to
 * use the single-port macro for the data access instead of the fetch
 * (`pm_we` / `pm_re`, DR 0012 "Program-memory timing"). Cycle N+1 is the
 * stall cycle: nothing new executes, `instr_word` carries the PM read data
 * (or a stale word after a write, which is ignored), and the core presents
 * the next fetch address -- `pc + 1`, or Rs for `RUN` (whose word is
 * still on `instr_word`: RUN makes no program-memory access). The instruction
 * after the access therefore executes in N+2: exactly one fetch stall,
 * always. A PM write commits at the edge ending cycle N, so the fetch
 * presented in N+1 already sees it (DR 0012: "a write to the word being
 * fetched next takes effect for the fetches after the write retires").
 *
 * The CRC itself (CRC-16/XMODEM over every committed word, by either the
 * serial load or `PM_DATA_LO`) lives in `protocol_program_memory`, the one
 * module that sees both commit paths; the core reads it and requests its
 * clear. `uio_dir` / `uio_od` leave the core for the top level's pin-mode
 * logic (open-drain wins, then push-pull, else input).
 *
 * Reset behavior: `rst_n` low clears the PC, all four registers, both
 * flags, the WAIT counter, the halt flag, the fetch-valid flag and both
 * pin-output registers, so a freshly reset core drives 0 on `uo_out` and
 * `uio_out`. It also clears every control register (DR 0012 "Reset values:
 * everything is an input"): `UIO_DIR = UIO_OD = 0`, so no `uio` pin is
 * driven until a program configures one, and `PM_ADDR`, both data latches
 * and the control stall are cleared. While `run_phase` is low (reset, or reset released into the
 * load phase) the core changes nothing but holds the PC at 0, so the
 * first executed instruction runs with pristine architectural state.
 */

`default_nettype none

module protocol_core #(
    // DR 0012 `HW_ID` (k = 0x09): a constant design/revision byte. DR 0012
    // fixes the register, not its value; 0x01 = the first revision that has
    // a control space at all. Bump it when a silicon-visible change ships.
    parameter [7:0] HW_ID = 8'h01
) (
    input  wire        clk,          // clock
    input  wire        rst_n,        // reset_n - low to reset
    input  wire        run_phase,    // 1 in run phase (from protocol_program_memory)
    input  wire [15:0] instr_word,   // program word fetched one cycle ago: the instruction executing NOW
                                     // (in a PM_DATA_HI stall cycle: the program-memory read data)
    output wire [7:0]  fetch_addr,   // fetch-ahead: address of the instruction to execute NEXT cycle
    input  wire [7:0]  port_ui_in,   // port 00: ui_in, read-only
    input  wire [7:0]  port_uio_in,  // port 01: uio_in, read-only
    output reg  [7:0]  port_uo_out,  // port 10: uo_out, write-only, registered ("Drive on edge")
    output reg  [7:0]  port_uio_out, // port 11: uio_out, write-only, registered
    // DR 0012 control space: runtime pin mode, to the top's uio_oe logic.
    output reg  [7:0]  uio_dir,      // UIO_DIR (k=0x00): push-pull drive enable per uio pin
    output reg  [7:0]  uio_od,       // UIO_OD  (k=0x01): open-drain enable per uio pin
    // DR 0012 program-memory access, to protocol_program_memory.
    output wire        pm_we,        // this cycle: commit pm_wdata to PM[pm_addr] (WCTL PM_DATA_LO)
    output wire        pm_re,        // this cycle: read PM[pm_addr] instead of fetching (RCTL PM_DATA_HI)
    output wire [7:0]  pm_addr,      // PM_ADDR (k=0x02)
    output wire [15:0] pm_wdata,     // {PM_DATA_HI latch, Rs}
    output wire        pm_crc_clr,   // this cycle: clear PM_CRC (WCTL PM_CRC_LO / PM_CRC_HI)
    input  wire [15:0] pm_crc,       // PM_CRC_HI:PM_CRC_LO (k=0x07:0x06), kept by the program memory
    input  wire        serial_loaded // BOOT_STATUS[0]: a serial load completed since reset
);

  // Opcodes (DR 0001 "Encoding" table, exactly 16 -- the table is full).
  localparam [3:0] OP_NOP  = 4'h0;
  localparam [3:0] OP_LDI  = 4'h1;
  localparam [3:0] OP_MOV  = 4'h2;
  localparam [3:0] OP_ADD  = 4'h3;
  localparam [3:0] OP_SUB  = 4'h4;
  localparam [3:0] OP_AND  = 4'h5;
  localparam [3:0] OP_OR   = 4'h6;
  localparam [3:0] OP_XOR  = 4'h7;
  localparam [3:0] OP_SHF  = 4'h8;
  localparam [3:0] OP_IN   = 4'h9;
  localparam [3:0] OP_OUT  = 4'hA;
  localparam [3:0] OP_WAIT = 4'hB;
  localparam [3:0] OP_JMP  = 4'hC;
  localparam [3:0] OP_BZ   = 4'hD;
  localparam [3:0] OP_BNZ  = 4'hE;
  localparam [3:0] OP_HALT = 4'hF;

  // Port codes (DR 0001 "Register and pin model" table).
  localparam [1:0] PORT_UI_IN   = 2'd0; // read-only
  localparam [1:0] PORT_UIO_IN  = 2'd1; // read-only
  localparam [1:0] PORT_UO_OUT  = 2'd2; // write-only
  localparam [1:0] PORT_UIO_OUT = 2'd3; // write-only

  // Control register indices (DR 0012 section 2). Any other k is
  // unassigned: a write is a 1-cycle no-op, a read returns 0x00 in 1 cycle.
  localparam [7:0] CTL_UIO_DIR     = 8'h00;
  localparam [7:0] CTL_UIO_OD      = 8'h01;
  localparam [7:0] CTL_PM_ADDR     = 8'h02;
  localparam [7:0] CTL_PM_DATA_HI  = 8'h03;
  localparam [7:0] CTL_PM_DATA_LO  = 8'h04;
  localparam [7:0] CTL_RUN         = 8'h05;
  localparam [7:0] CTL_PM_CRC_LO   = 8'h06;
  localparam [7:0] CTL_PM_CRC_HI   = 8'h07;
  localparam [7:0] CTL_BOOT_STATUS = 8'h08;
  localparam [7:0] CTL_HW_ID       = 8'h09;

  // Architectural state.
  reg [7:0] regs [0:3];   // R0-R3
  reg       flag_z;       // zero flag, written by ADD/SUB/AND/OR/XOR, read by BZ/BNZ
  /* verilator lint_off UNUSEDSIGNAL */
  // flag_c is deliberately write-only state in ISA revision 1: DR 0001's
  // opcode table has no instruction that reads C (BZ/BNZ read Z only), so
  // no RTL cone consumes it. It is verified white-box by the bench
  // (test_alu_flags_whitebox reads dut.u_core.flag_c) and exists for a
  // future revision that ratifies a carry-consuming instruction -- see the
  // header's SUB borrow-convention note. Silence Verilator's UNUSEDSIGNAL
  // for exactly this declaration and nothing else.
  reg       flag_c;       // carry/borrow flag, written by ADD/SUB/SHF (write-only state)
  /* verilator lint_on UNUSEDSIGNAL */
  reg [7:0] pc;           // address of the instruction executing NOW (8 bits == 256-word memory)
  reg       fetch_valid;  // `instr_word` holds a real instruction for `pc` (clear for one cycle at run entry)
  reg       waiting;      // a WAIT stall is in progress
  reg [7:0] wait_cnt;     // remaining stall cycles (loaded from the WAIT immediate)
  reg       halted;       // HALT executed: idle until reset

  // DR 0012 control-space state (uio_dir / uio_od are the output regs above).
  reg [7:0] pm_addr_r;    // PM_ADDR
  reg [7:0] pm_hi;        // PM_DATA_HI write latch
  reg [7:0] pm_lo;        // low-byte latch filled by an RCTL PM_DATA_HI read
  reg       ctl_stall;    // this cycle is the fixed stall cycle of a 2-cycle control access
  reg       stall_pmrd;   // ...and it completes an RCTL PM_DATA_HI (instr_word = PM data)
  reg       stall_run;    // ...and it completes a WCTL RUN (next fetch from run_target)
  reg [1:0] stall_rd;     // RCTL PM_DATA_HI destination register

  // Decode (combinational, fixed width -- part of the determinism argument).
  wire [3:0] opcode = instr_word[15:12];
  wire [1:0] rd     = instr_word[11:10];
  wire [1:0] rs     = instr_word[9:8];
  wire [7:0] imm8   = instr_word[7:0];

  // Register-file read ports (two, both combinational).
  wire [7:0] rd_val = regs[rd];
  wire [7:0] rs_val = regs[rs];

  // ALU operand results.
  wire [8:0] add_sum  = {1'b0, rd_val} + {1'b0, rs_val};
  wire [8:0] sub_diff = {1'b0, rd_val} - {1'b0, rs_val};
  wire [7:0] and_res  = rd_val & rs_val;
  wire [7:0] or_res   = rd_val | rs_val;
  wire [7:0] xor_res  = rd_val ^ rs_val;

  // SHF: shift Rd by 1; direction is Rs[0] (0 = right, 1 = left); the
  // shifted-out bit lands in C.
  wire       shf_left = rs[0];
  wire [7:0] shf_res  = shf_left ? {rd_val[6:0], 1'b0} : {1'b0, rd_val[7:1]};
  wire       shf_c    = shf_left ? rd_val[7] : rd_val[0];

  // IN port mux: only ports 00/01 are readable; IN to 10/11 is a no-op.
  wire       in_readable = (rs == PORT_UI_IN) || (rs == PORT_UIO_IN);
  wire [7:0] in_val      = (rs == PORT_UI_IN) ? port_ui_in : port_uio_in;

  // ------------------------------------------------------------------
  // Control space decode (DR 0012). `executing` is high in exactly the
  // cycles in which the instruction at `pc` takes effect (the same gate the
  // sequential block uses), so the program-memory strobes below fire once,
  // in the access's own cycle, and never during WAIT/HALT/the stall cycle.
  // ------------------------------------------------------------------
  wire       executing = run_phase && fetch_valid && !halted && !waiting && !ctl_stall;
  wire       is_wctl   = (opcode == OP_OUT) && (rs == PORT_UI_IN);   // OUT port 00
  wire       is_rctl   = (opcode == OP_IN)  && (rs == PORT_UO_OUT);  // IN  port 10
  wire       wctl_lo   = is_wctl && (imm8 == CTL_PM_DATA_LO);
  wire       wctl_run  = is_wctl && (imm8 == CTL_RUN);
  wire       rctl_hi   = is_rctl && (imm8 == CTL_PM_DATA_HI);
  // The fixed-2-cycle accesses (DR 0012 table): a function of the encoded
  // fields alone.
  wire       ctl_two   = wctl_lo || wctl_run || rctl_hi;

  assign pm_we      = executing && wctl_lo;
  assign pm_re      = executing && rctl_hi;
  assign pm_addr    = pm_addr_r;
  assign pm_wdata   = {pm_hi, rd_val};  // OUT/WCTL source register rides [11:10]
  assign pm_crc_clr = executing && is_wctl &&
                      ((imm8 == CTL_PM_CRC_LO) || (imm8 == CTL_PM_CRC_HI));

  // RCTL read mux for every 1-cycle readable index (PM_DATA_HI is read in
  // its stall cycle, from instr_word, below).
  reg [7:0] rctl_val;
  always @(*) begin
    case (imm8)
      CTL_UIO_DIR:     rctl_val = uio_dir;
      CTL_UIO_OD:      rctl_val = uio_od;
      CTL_PM_ADDR:     rctl_val = pm_addr_r;
      CTL_PM_DATA_LO:  rctl_val = pm_lo;
      CTL_PM_CRC_LO:   rctl_val = pm_crc[7:0];
      CTL_PM_CRC_HI:   rctl_val = pm_crc[15:8];
      // bit 1 (running from the boot ROM) reads 0: there is no boot ROM
      // in this revision (DR 0013 layer 2 is issue #138).
      CTL_BOOT_STATUS: rctl_val = {6'b000000, 1'b0, serial_loaded};
      CTL_HW_ID:       rctl_val = HW_ID;
      default:         rctl_val = 8'h00;  // unassigned (and write-only RUN)
    endcase
  end

  // ------------------------------------------------------------------
  // Fetch-ahead next-address mux (DR 0005's amendment to DR 0001). This
  // is DR 0001's next-PC mux verbatim -- branch target vs. PC+1 --
  // relocated from the PC register's input to the memory's address
  // port. It is purely combinational and both branch paths cost the
  // same single cycle, so branch *outcome* may depend on data while
  // branch *cost* never does.
  // ------------------------------------------------------------------
  wire [7:0] pc_next = pc + 8'd1;
  reg  [7:0] next_addr;

  always @(*) begin
    if (!run_phase || !fetch_valid) begin
      // Reset / load phase, and the single fetch-ahead priming cycle at
      // run entry: present address 0 so instruction 0 executes next.
      next_addr = 8'd0;
    end else if (halted) begin
      next_addr = pc;                                  // HALT: hold forever
    end else if (ctl_stall) begin
      // Stall cycle of a 2-cycle control access: the macro was busy with
      // the data access last cycle, so fetch now. RUN's target is Rs (a
      // data-chosen *where*, at a fixed *how long*, like a branch
      // outcome). RUN held the fetch address and made no program-memory
      // access in its own cycle, so `instr_word` is still the RUN word
      // here and `rd_val` is still its Rs -- the same held-word argument
      // WAIT relies on -- which is why no target latch is needed.
      next_addr = stall_run ? rd_val : pc_next;
    end else if (waiting) begin
      // Mid-WAIT: hold the address (the macro re-reads the same word, so
      // `instr_word` is stable) until the final stall cycle, which
      // presents PC+1 so the next instruction executes immediately after.
      next_addr = (wait_cnt == 8'd1) ? pc_next : pc;
    end else begin
      case (opcode)
        OP_WAIT: next_addr = (imm8 == 8'd0) ? pc_next : pc;  // WAIT 0: no stall
        OP_JMP:  next_addr = imm8;                           // absolute, 8-bit target
        OP_BZ:   next_addr = flag_z  ? imm8 : pc_next;
        OP_BNZ:  next_addr = !flag_z ? imm8 : pc_next;
        OP_HALT: next_addr = pc;
        // 2-cycle control accesses hold the address for their own cycle
        // (the macro's single port is busy with the PM access, or -- for
        // RUN -- the target is fetched from the stall cycle).
        OP_OUT,
        OP_IN:   next_addr = ctl_two ? pc : pc_next;
        default: next_addr = pc_next;
      endcase
    end
  end

  assign fetch_addr = next_addr;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      regs[0]      <= 8'h00;
      regs[1]      <= 8'h00;
      regs[2]      <= 8'h00;
      regs[3]      <= 8'h00;
      flag_z       <= 1'b0;
      flag_c       <= 1'b0;
      pc           <= 8'd0;
      fetch_valid  <= 1'b0;
      waiting      <= 1'b0;
      wait_cnt     <= 8'd0;
      halted       <= 1'b0;
      port_uo_out  <= 8'h00;
      port_uio_out <= 8'h00;
      uio_dir      <= 8'h00;  // DR 0012: every uio pin an input at reset
      uio_od       <= 8'h00;
      pm_addr_r    <= 8'h00;
      pm_hi        <= 8'h00;
      pm_lo        <= 8'h00;
      ctl_stall    <= 1'b0;
      stall_pmrd   <= 1'b0;
      stall_run    <= 1'b0;
      stall_rd     <= 2'd0;
    end else if (!run_phase) begin
      // Load phase (or the pre-sampling cycle): hold the PC at 0 and keep
      // the fetched word marked invalid. No architectural state changes --
      // nothing executes until run_phase rises.
      pc          <= 8'd0;
      fetch_valid <= 1'b0;
    end else begin
      // Every run-phase edge advances the fetch-ahead address, including
      // the priming edge (next_addr == 0 there) and the HALT/WAIT hold
      // edges (next_addr == pc there).
      pc          <= next_addr;
      fetch_valid <= 1'b1;

      if (fetch_valid && !halted) begin
        if (ctl_stall) begin
          // The fixed second cycle of a 2-cycle control access. Nothing
          // here reads data to decide anything about timing: it always
          // ends after this one cycle.
          ctl_stall  <= 1'b0;
          stall_pmrd <= 1'b0;
          stall_run  <= 1'b0;
          if (stall_pmrd) begin
            // RCTL PM_DATA_HI: instr_word is PM[PM_ADDR] (read in cycle N).
            regs[stall_rd] <= instr_word[15:8];
            pm_lo          <= instr_word[7:0];
          end
        end else if (waiting) begin
          // WAIT stall in progress. The stall length was fixed by the
          // WAIT's own immediate when it executed; nothing sampled here
          // can change it (the no-data-dependent-latency property).
          if (wait_cnt == 8'd1) begin
            waiting <= 1'b0;
          end else begin
            wait_cnt <= wait_cnt - 8'd1;
          end
        end else begin
          case (opcode)
            OP_NOP: begin
              // no architectural effect; the PC advance is `next_addr`
            end
            OP_LDI: begin
              regs[rd] <= imm8;
            end
            OP_MOV: begin
              regs[rd] <= rs_val;
            end
            OP_ADD: begin
              regs[rd] <= add_sum[7:0];
              flag_z   <= (add_sum[7:0] == 8'h00);
              flag_c   <= add_sum[8];
            end
            OP_SUB: begin
              regs[rd] <= sub_diff[7:0];
              flag_z   <= (sub_diff[7:0] == 8'h00);
              flag_c   <= sub_diff[8];  // borrow: minuend < subtrahend (see header)
            end
            OP_AND: begin
              regs[rd] <= and_res;
              flag_z   <= (and_res == 8'h00);
            end
            OP_OR: begin
              regs[rd] <= or_res;
              flag_z   <= (or_res == 8'h00);
            end
            OP_XOR: begin
              regs[rd] <= xor_res;
              flag_z   <= (xor_res == 8'h00);
            end
            OP_SHF: begin
              regs[rd] <= shf_res;
              flag_c   <= shf_c;
            end
            OP_IN: begin
              if (in_readable) begin
                regs[rd] <= in_val;
              end else if (is_rctl) begin
                // RCTL Rd, k (DR 0012). PM_DATA_HI takes the stall path;
                // every other index retires now.
                if (rctl_hi) begin
                  ctl_stall  <= 1'b1;
                  stall_pmrd <= 1'b1;
                  stall_rd   <= rd;
                end else begin
                  regs[rd] <= rctl_val;
                  if (imm8 == CTL_PM_DATA_LO) begin
                    pm_addr_r <= pm_addr_r + 8'd1;
                  end
                end
              end
              // IN from port 11 (write-only): no-op, still 1 cycle (reserved).
            end
            OP_OUT: begin
              case (rs)
                PORT_UO_OUT:  port_uo_out  <= rd_val;
                PORT_UIO_OUT: port_uio_out <= rd_val;
                PORT_UI_IN: begin
                  // WCTL k, Rs (DR 0012).
                  case (imm8)
                    CTL_UIO_DIR:    begin uio_dir <= rd_val; port_uo_out <= rd_val; end  // MUTANT
                    CTL_UIO_OD:     uio_od    <= rd_val;
                    CTL_PM_ADDR:    pm_addr_r <= rd_val;
                    CTL_PM_DATA_HI: pm_hi     <= rd_val;
                    CTL_PM_DATA_LO: begin
                      // The commit itself is pm_we this cycle; the
                      // address advances on the same edge.
                      pm_addr_r <= pm_addr_r + 8'd1;
                      ctl_stall <= 1'b1;
                    end
                    CTL_RUN: begin
                      // The jump itself is next_addr in the stall cycle.
                      ctl_stall <= 1'b1;
                      stall_run <= 1'b1;
                    end
                    // PM_CRC_LO/HI: the clear is pm_crc_clr this cycle.
                    // BOOT_STATUS, HW_ID and unassigned k: no-op.
                    default: ;
                  endcase
                end
                default: ;  // OUT to port 01 (read-only): no-op, still 1 cycle (reserved).
              endcase
            end
            OP_WAIT: begin
              // Total cycles consumed by this WAIT = imm8 + 1: this
              // execute cycle plus imm8 stall cycles. WAIT 0 takes the
              // execute cycle alone (a legal 1-cycle padding stall).
              if (imm8 != 8'd0) begin
                waiting  <= 1'b1;
                wait_cnt <= imm8;
              end
            end
            OP_JMP: begin
              // Control transfer only; the target is already in next_addr.
            end
            OP_BZ: begin
              // Control transfer only; the outcome is already in next_addr.
            end
            OP_BNZ: begin
              // Control transfer only; the outcome is already in next_addr.
            end
            OP_HALT: begin
              halted <= 1'b1;  // costs its 1 cycle, then idles until reset
            end
            default: begin
              // Unreachable: opcode is 4 bits and all 16 are named above.
            end
          endcase
        end
      end
    end
  end

  // List unused inputs to prevent warnings (none today: every port is
  // consumed by the logic above).

endmodule

`default_nettype wire
