/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Core datapath per `spec/decision-records/0001-isa.md` (issue #18,
 * target-spec rows 1/3/6). The ISA is the product: this is a pin-timing
 * engine, not a general CPU -- no RAM, no stack, no interrupts, no
 * fixed-function protocol peripherals. Every instruction the ratified
 * ISA defines retires in exactly one clock cycle except `WAIT`, whose
 * duration is fixed by its own immediate, so the cycle count of any
 * program is computable from the instruction stream alone (DR 0001's
 * timing-determinism guarantee, target-spec row 3).
 *
 * Module contract (all of it DR 0001, section names in quotes):
 *
 *   - Single-cycle, non-pipelined fetch-and-execute ("Timing model"):
 *     the instruction at `fetch_addr` is read combinationally from
 *     `protocol_program_memory`'s fetch port and executes in the same
 *     cycle; there is no fetch latency to reason about separately.
 *     `fetch_addr` is the program counter, held at 0 while `run_phase`
 *     is low (reset or load phase) per the program-memory module's
 *     "Interface intent": first fetch lands at address 0 on the first
 *     cycle `run_phase` is high.
 *
 *   - Four 8-bit general-purpose registers R0-R3 and a 2-bit flag
 *     register {Z, C} ("Register and pin model"). ADD/SUB write Z and
 *     C; AND/OR/XOR write Z only (C unchanged); SHF writes C only (the
 *     shifted-out bit; Z unchanged). BZ/BNZ read Z. C is write-only
 *     state in this ISA revision -- no instruction consumes it -- so it
 *     is observable only as the internal `flag_c` register (the cocotb
 *     bench checks it there, white-box, and says so where it does).
 *
 *   - SUB's C is the borrow convention: C = 1 when the minuend is
 *     less than the subtrahend (the 9-bit subtract's MSB, the same
 *     bit x86's SUB flag computes). DR 0001 says only "sets Z, C" --
 *     no instruction in this revision reads C (BZ/BNZ read Z only),
 *     so the polarity is this module's pin of a detail the ratified
 *     record leaves open, chosen to match what the arithmetic itself
 *     produces. A future ISA revision that exposes C (e.g. branch on
 *     carry, or rotate-through-carry) must ratify the polarity in a
 *     decision record before relying on it.
 *
 *   - Four addressable 8-bit pin ports ("Register and pin model"):
 *       port 00 -> ui_in  (read-only)        port 10 -> uo_out (write-only)
 *       port 01 -> uio_in (read-only)        port 11 -> uio_out(write-only)
 *     `IN` samples the port value at the retiring clock edge ("Sample
 *     on edge"); `IN` to a write-only port is a no-op that still costs
 *     its 1 cycle. `OUT` writes the port's output register at the
 *     retiring edge ("Drive on edge"), so the new pin value is visible
 *     exactly one clock cycle after the `OUT` executes; `OUT` to a
 *     read-only port is a likewise-1-cycle no-op. `uio_oe` direction is
 *     NOT runtime-programmable in this ISA revision ("Consequences") --
 *     `OUT` to port 11 only ever targets `uio_out`; the top level fixes
 *     `uio_oe` at synthesis time.
 *
 *   - Encoding ("Encoding"): fixed 16-bit words,
 *       [15:12] opcode, [11:10] Rd, [9:8] Rs/port, [7:0] imm8.
 *     For `IN Rd, port` the destination register is [11:10] and the
 *     port is [9:8]. For `OUT port, Rs` the *source* register sits in
 *     the [11:10] field and the port in [9:8] -- the encoding keeps one
 *     uniform register field and one uniform port field for both I/O
 *     ops, exactly as DR 0001's field table ("Rs (register-register
 *     ops) or port (I/O ops)") reads. `SHF`'s direction bit is Rs[0]
 *     (0 = right, 1 = left).
 *
 *   - `WAIT imm8` stalls exactly imm8 + 1 cycles before advancing the
 *     PC (so `WAIT 0` is a legal 1-cycle stall). The counter derives
 *     from the immediate alone -- never a register, never a pin -- which
 *     is the load-bearing "no data-dependent latency" property. Branch
 *     *outcome* may depend on data; branch *cost* never does: the
 *     next-PC mux (target vs. PC+1) is combinational and both paths
 *     cost 1 cycle.
 *
 *   - `HALT` stops fetch/execute: the core idles (PC, registers, flags
 *     and pin registers all hold) until the next `rst_n` pulse.
 *
 *   - `ena` is deliberately not a port: DR 0001's load protocol is
 *     reset-gated, and the Tiny Tapeout template documents `ena` as
 *     "always 1 when the design is powered, so you can ignore it".
 *
 * Reset behavior: `rst_n` low clears the PC, all four registers, both
 * flags, the WAIT counter, the halt flag and both pin-output registers,
 * so a freshly reset core drives 0 on `uo_out` and `uio_out`. While
 * `run_phase` is low (reset released into the load phase) the core
 * changes nothing but holds the PC at 0, so the first run-phase cycle
 * fetches from address 0 with pristine architectural state.
 */

`default_nettype none

module protocol_core (
    input  wire        clk,         // clock
    input  wire        rst_n,       // reset_n - low to reset
    input  wire        run_phase,   // 1 in run phase (from protocol_program_memory)
    input  wire [15:0] instr_word,  // combinational fetch read at fetch_addr
    output wire [7:0]  fetch_addr,  // the core's 8-bit program counter
    input  wire [7:0]  port_ui_in,  // port 00: ui_in, read-only
    input  wire [7:0]  port_uio_in, // port 01: uio_in, read-only
    output reg  [7:0]  port_uo_out, // port 10: uo_out, write-only, registered ("Drive on edge")
    output reg  [7:0]  port_uio_out // port 11: uio_out, write-only, registered
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
  localparam [1:0] PORT_UI_IN  = 2'd0; // read-only
  localparam [1:0] PORT_UIO_IN = 2'd1; // read-only
  localparam [1:0] PORT_UO_OUT = 2'd2; // write-only
  localparam [1:0] PORT_UIO_OUT= 2'd3; // write-only

  // Architectural state.
  reg [7:0] regs [0:3];   // R0-R3
  reg       flag_z;       // zero flag, written by ADD/SUB/AND/OR/XOR, read by BZ/BNZ
  reg       flag_c;       // carry/no-borrow flag, written by ADD/SUB/SHF (write-only state)
  reg [7:0] pc;           // program counter, 8 bits == 256-word program memory
  reg       waiting;      // a WAIT stall is in progress
  reg [7:0] wait_cnt;     // remaining stall cycles (loaded from the WAIT immediate)
  reg       halted;       // HALT executed: idle until reset

  assign fetch_addr = pc;

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

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      regs[0]      <= 8'h00;
      regs[1]      <= 8'h00;
      regs[2]      <= 8'h00;
      regs[3]      <= 8'h00;
      flag_z       <= 1'b0;
      flag_c       <= 1'b0;
      pc           <= 8'd0;
      waiting      <= 1'b0;
      wait_cnt     <= 8'd0;
      halted       <= 1'b0;
      port_uo_out  <= 8'h00;
      port_uio_out <= 8'h00;
    end else if (!run_phase) begin
      // Load phase (or the pre-sampling cycle): hold the PC at 0 so the
      // first run-phase cycle fetches address 0. No architectural state
      // changes -- nothing executes until run_phase rises.
      pc <= 8'd0;
    end else if (halted) begin
      // HALT: idle until reset. PC, registers, flags and pins all hold.
    end else if (waiting) begin
      // WAIT stall in progress. The stall length was fixed by the WAIT's
      // own immediate at decode time; nothing sampled here can change it
      // (the no-data-dependent-latency property).
      if (wait_cnt == 8'd1) begin
        waiting <= 1'b0;
        pc      <= pc + 8'd1;
      end else begin
        wait_cnt <= wait_cnt - 8'd1;
      end
    end else begin
      case (opcode)
        OP_NOP: begin
          pc <= pc + 8'd1;
        end
        OP_LDI: begin
          regs[rd] <= imm8;
          pc       <= pc + 8'd1;
        end
        OP_MOV: begin
          regs[rd] <= rs_val;
          pc       <= pc + 8'd1;
        end
        OP_ADD: begin
          regs[rd] <= add_sum[7:0];
          flag_z   <= (add_sum[7:0] == 8'h00);
          flag_c   <= add_sum[8];
          pc       <= pc + 8'd1;
        end
        OP_SUB: begin
          regs[rd] <= sub_diff[7:0];
          flag_z   <= (sub_diff[7:0] == 8'h00);
          flag_c   <= sub_diff[8];  // borrow: minuend < subtrahend (see header)
          pc       <= pc + 8'd1;
        end
        OP_AND: begin
          regs[rd] <= and_res;
          flag_z   <= (and_res == 8'h00);
          pc       <= pc + 8'd1;
        end
        OP_OR: begin
          regs[rd] <= or_res;
          flag_z   <= (or_res == 8'h00);
          pc       <= pc + 8'd1;
        end
        OP_XOR: begin
          regs[rd] <= xor_res;
          flag_z   <= (xor_res == 8'h00);
          pc       <= pc + 8'd1;
        end
        OP_SHF: begin
          regs[rd] <= shf_res;
          flag_c   <= shf_c;
          pc       <= pc + 8'd1;
        end
        OP_IN: begin
          if (in_readable) begin
            regs[rd] <= in_val;
          end
          // IN to a write-only port: no-op, still 1 cycle.
          pc <= pc + 8'd1;
        end
        OP_OUT: begin
          case (rs)
            PORT_UO_OUT:  port_uo_out  <= rd_val;
            PORT_UIO_OUT: port_uio_out <= rd_val;
            default: ;  // OUT to a read-only port: no-op, still 1 cycle.
          endcase
          pc <= pc + 8'd1;
        end
        OP_WAIT: begin
          if (imm8 == 8'd0) begin
            pc <= pc + 8'd1;  // WAIT 0: legal 1-cycle stall, nothing more.
          end else begin
            // Total cycles consumed by this WAIT = imm8 + 1: this decode
            // cycle plus imm8 stall cycles, the last of which also
            // advances the PC (handled by the waiting branch above).
            waiting  <= 1'b1;
            wait_cnt <= imm8;
          end
        end
        OP_JMP: begin
          pc <= imm8;  // absolute, 8-bit target == 256-word memory
        end
        OP_BZ: begin
          pc <= flag_z ? imm8 : (pc + 8'd1);
        end
        OP_BNZ: begin
          pc <= (!flag_z) ? imm8 : (pc + 8'd1);
        end
        OP_HALT: begin
          halted <= 1'b1;  // costs its 1 cycle, then idles until reset
        end
        default: begin
          pc <= pc + 8'd1;  // unreachable: opcode is 4 bits and all 16 are named
        end
      endcase
    end
  end

  // List unused inputs to prevent warnings (none today: every port is
  // consumed by the logic above).

endmodule

`default_nettype wire
