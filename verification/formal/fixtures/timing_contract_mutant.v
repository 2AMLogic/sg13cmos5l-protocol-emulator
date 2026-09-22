/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * QUALIFICATION FIXTURE (NEGATIVE CONTROL), NOT DESIGN RTL (issue #24).
 *
 * Byte-for-byte the conformant timing-contract shell above, with exactly
 * ONE defect injected: a WAIT may terminate early when a free data input
 * matches a magic value. This is precisely the bug class
 * `no_data_dependent_latency` exists to catch -- DR 0001: "a conditional
 * branch, an early-out, a shift loop that terminates on data all break
 * it". The property monitor must produce a counterexample against this
 * module (a WAIT whose stall was cut short by data). If it ever passes
 * against this mutant, the property is vacuous or wrong and must be
 * fixed before anyone trusts it against the real core.
 *
 * The injected early-out reads `mutant_early_data` -- a stand-in for any
 * data-dependent state (a general-purpose register, a sampled pin, a
 * flag) that a naive implementation might route into its stall counter.
 */

`default_nettype none

module timing_contract_mutant (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run_phase,
    input  wire [15:0] instr_word,
    input  wire [7:0]  branch_data,
    input  wire [7:0]  mutant_early_data,
    output reg  [7:0]  fetch_addr
);

  wire [3:0] op  = instr_word[15:12];
  wire [7:0] imm = instr_word[7:0];

  // THE INJECTED DEFECT (the only difference from the conformant shell):
  // a WAIT whose data happens to equal the magic value terminates in one
  // cycle regardless of its immediate. Latency now depends on data.
  wire early_out = (mutant_early_data == 8'hA5);

  reg [8:0] wait_rem;

  wire [7:0] pc_p1 = fetch_addr + 8'd1;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fetch_addr <= 8'd0;
      wait_rem   <= 9'd0;
    end else if (!run_phase) begin
      fetch_addr <= 8'd0;
      wait_rem   <= 9'd0;
    end else if (wait_rem > 9'd1) begin
      wait_rem <= wait_rem - 9'd1;
      if (wait_rem == 9'd2)
        fetch_addr <= pc_p1;
    end else begin
      case (op)
        4'b1011: begin
          if (imm == 8'd0 || early_out)              // <-- defect: early_out short-circuits the stall
            fetch_addr <= pc_p1;
          else
            wait_rem <= 9'd1 + {1'b0, imm};
        end
        4'b1100: fetch_addr <= imm;
        4'b1101: fetch_addr <= branch_data[0] ? imm : pc_p1;
        4'b1110: fetch_addr <= branch_data[0] ? pc_p1 : imm;
        4'b1111: fetch_addr <= fetch_addr;
        default: fetch_addr <= pc_p1;
      endcase
    end
  end

  wire _unused_ok = 1'b1; // port lists already identical; nothing unused here

endmodule

`default_nettype wire
