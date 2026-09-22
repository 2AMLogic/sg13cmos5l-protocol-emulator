/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * QUALIFICATION FIXTURE, NOT DESIGN RTL (issue #24).
 *
 * This module is the *conformant* positive-control stand-in for the core
 * datapath that issue #18 is building. It exists so the formal property
 * `no_data_dependent_latency` (../no_data_dependent_latency.sv) can be
 * exercised end to end -- and proven sound (no false positives) -- before
 * the real core exists. It implements EXACTLY the ratified timing
 * contract of DR 0001's "Timing model" section and nothing else:
 *
 *   - every opcode occupies exactly 1 cycle, except WAIT (imm8+1) and
 *     HALT (1 cycle, then idle forever);
 *   - branch *targets* may respond to free data inputs (`branch_data`
 *     stands in for the flags/registers/pins that will steer BZ/BNZ in
 *     the real core) -- DR 0001: "branch outcome may depend on data ...
 *     but branch cost never does";
 *   - no timing decision anywhere reads a data value.
 *
 * It is deliberately NOT a datapath: no registers, no ALU, no pin ports.
 * Building those is issue #18's scope, not this fixture's. When #18
 * lands, `formal_top.v` swaps this module for the real core and the same
 * property file binds unchanged (see the property header's bind
 * contract).
 */

`default_nettype none

module timing_contract_conformant (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run_phase,
    input  wire [15:0] instr_word,
    input  wire [7:0]  branch_data,       // free: may steer branch targets, never timing
    input  wire [7:0]  mutant_early_data, // unused here; common port so formal_top is fixture-agnostic
    output reg  [7:0]  fetch_addr
);

  wire [3:0] op  = instr_word[15:12];
  wire [7:0] imm = instr_word[7:0];

  // WAIT occupancy countdown, in cycles remaining INCLUDING the current
  // cycle, while a WAIT is in progress (0 = no WAIT in progress). Counting
  // inclusive makes this register directly comparable to the property
  // monitor's `rem_eff` shadow.
  reg [8:0] wait_rem;

  wire [7:0] pc_p1 = fetch_addr + 8'd1;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fetch_addr <= 8'd0;
      wait_rem   <= 9'd0;
    end else if (!run_phase) begin
      // DR 0001 / rtl/protocol_program_memory.v "Interface intent": hold
      // pc at 0 while not in run phase; first fetch lands at address 0.
      fetch_addr <= 8'd0;
      wait_rem   <= 9'd0;
    end else if (wait_rem > 9'd1) begin
      // Mid-WAIT stall: hold pc, count down. No data input is read here
      // or anywhere in this branch -- that is the whole point.
      wait_rem <= wait_rem - 9'd1;
      if (wait_rem == 9'd2)
        fetch_addr <= pc_p1;  // last stall cycle: advance to next instruction
    end else begin
      case (op)
        4'b1011: begin // WAIT: occupy imm+1 cycles, then advance
          if (imm == 8'd0)
            fetch_addr <= pc_p1;                     // 1-cycle occupancy
          else
            wait_rem <= 9'd1 + {1'b0, imm};          // this cycle + imm more
        end
        4'b1100: fetch_addr <= imm;                  // JMP: unconditional, target from the program
        4'b1101: fetch_addr <= branch_data[0] ? imm : pc_p1; // BZ: outcome on (free) flags
        4'b1110: fetch_addr <= branch_data[0] ? pc_p1 : imm; // BNZ: mirrored polarity
        4'b1111: fetch_addr <= fetch_addr;           // HALT: idle until reset
        default: fetch_addr <= pc_p1;                // every other opcode: 1 cycle, straight-line
      endcase
    end
  end

  // Sink the deliberately-unused port so the port list stays identical
  // across both fixtures (formal_top wires the same nets either way).
  wire _unused = &{mutant_early_data, 1'b0};

endmodule

`default_nettype wire
