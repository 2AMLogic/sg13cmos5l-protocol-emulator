/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * QUALIFICATION FIXTURE (NEGATIVE CONTROL), NOT DESIGN RTL (issue #135).
 *
 * The conformant timing-contract shell (timing_contract_conformant.v) with
 * exactly ONE defect injected, in the part of the latency table DR 0012
 * added: a 2-cycle control access (WCTL PM_DATA_LO, WCTL RUN, RCTL
 * PM_DATA_HI) retires in ONE cycle when a free data input matches a magic
 * value. An early-out skipped access falls through the opcode `case` to
 * its `default` (pc + 1), exactly as a 1-cycle OUT/IN would.
 *
 * This is the control-space sibling of timing_contract_mutant.v (whose
 * defect is a data-dependent WAIT early-out): `no_data_dependent_latency`
 * must produce a counterexample against this module too, or its extension
 * to WCTL/RCTL is vacuous. WAIT is conformant here, so a counterexample
 * can only come from the control-access rows of the table.
 *
 * The injected early-out reads `mutant_early_data` -- a stand-in for any
 * data-dependent state (the register being written, a sampled pin, a flag)
 * that a naive implementation might let short-circuit the stall, e.g.
 * "skip the program-memory cycle when the value is unchanged".
 */

`default_nettype none

module timing_contract_mutant_ctl (
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

  // DR 0012 control space (issue #135): WCTL = OUT (1010) to port 00, RCTL
  // = IN (1001) from port 10, index k in imm8. Three accesses occupy a
  // fixed 2 cycles: WCTL PM_DATA_LO (0x04), WCTL RUN (0x05), RCTL
  // PM_DATA_HI (0x03). Every other index, in either direction, is 1 cycle.
  wire is_wctl = (op == 4'b1010) && (instr_word[9:8] == 2'b00);
  wire is_rctl = (op == 4'b1001) && (instr_word[9:8] == 2'b10);
  wire is_run  = is_wctl && (imm == 8'h05);
  wire is_ctl2 = is_run || (is_wctl && (imm == 8'h04)) || (is_rctl && (imm == 8'h03));

  // THE INJECTED DEFECT (the only difference from the conformant shell):
  // a 2-cycle control access whose data happens to equal the magic value
  // skips its stall cycle. Latency now depends on data.
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
        fetch_addr <= is_run ? branch_data : pc_p1;
    end else if (is_ctl2 && !early_out) begin        // <-- defect: early_out skips the fixed stall
      wait_rem <= 9'd2;
    end else begin
      case (op)
        4'b1011: begin
          if (imm == 8'd0)
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
