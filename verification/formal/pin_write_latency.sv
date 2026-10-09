/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal property `pin_write_latency` (spec/verification-plan.md section
 * 2.2, issue #116): every executed OUT writes the selected source
 * register's value to the addressed WRITABLE port at the registered
 * boundary, the other port holds, and nothing else ever moves an output.
 *
 * INDEPENDENT MODEL. This monitor shares no logic and no signal with the
 * core's write path. It re-derives, from the instruction word alone (plus
 * the free pin inputs and the harness's phase signal), a shadow ISA model
 * written from DR 0001's text, not copied from rtl/protocol_core.v:
 *
 *   - s_r[0..3]   : the four general-purpose registers (DR 0001 semantics
 *                   for LDI/MOV/ADD/SUB/AND/OR/XOR/SHF/IN),
 *   - s_halted    : HALT executed (idle until reset),
 *   - s_wait_rem  : remaining WAIT stall cycles (WAIT imm8 costs imm8+1
 *                   cycles: its own execute cycle plus imm8 stall cycles),
 *   - exp_uo/uio  : the expected output registers (reset value 0, DR 0001
 *                   / core header "Reset behavior").
 *
 * Execution eligibility ("is the instruction on `instr` executing this
 * cycle") is derived HERE: exec_valid (from the harness's phase model --
 * run phase with DR 0005's priming cycle excluded, never the core's
 * fetch_valid) AND NOT s_halted AND s_wait_rem == 0. No core-internal
 * signal (write enable, `waiting`, `halted`, `fetch_valid`, `regs`) is
 * read, so a faulty DUT write enable or register file cannot be inherited.
 * What the monitor DOES share with the core is the instruction stream:
 * `instr` is the word the core's own fetch address selected from the
 * harness's program table. Which instruction executes next is section
 * 2.1's property (`no_data_dependent_latency`); this monitor checks what
 * each instruction that is fetched does to the pins.
 *
 * CLOCK CONVENTION (the DR 0001 / verification-plan section 2.2
 * reconciliation). DR 0001 "Drive on edge": OUT writes the output
 * register at the clock edge that RETIRES it; the pin shows the value one
 * cycle after OUT executes. Plan 2.2: "OUT retires at cycle N ... value at
 * cycle N+1". These are one event under one labelling, with no extra
 * pipeline stage:
 *
 *   cycle N              | edge E (ends N)          | cycle N+1
 *   ---------------------+--------------------------+------------------------
 *   OUT p,Rs occupies    | the retiring edge: the   | out[p] == Rs(N) (new),
 *   execute (`instr`);   | output flop captures     | the other port == its
 *   Rs(N) is the PRE-    | Rs(N); every other flop  | old value. The NEXT
 *   edge source value;   | (Rs itself included)     | assertion sampling
 *   out[p] == OLD value  | updates at the same edge | point is edge E+1, which
 *   (no early            |                          | sees the pre-edge (i.e.
 *   visibility)          |                          | cycle N+1) value
 *
 * "Cycle N" is the clock period in which OUT occupies the execute stage
 * ("executes"), ending with the edge that "retires" it. A synchronous
 * observer capturing AT edge E sees the OLD value; one capturing at E+1
 * sees the NEW value. That is exactly "visible one cycle after OUT
 * executes" and exactly plan 2.2's "at cycle N+1". Nothing here contradicts
 * DR 0001, so the convention itself raises no spec finding.
 *
 * WHAT EACH CLOCK MODEL OBSERVES (see run-pin-write-latency.sh).
 *   - EDGE model (default build): one solver step per clock cycle; the
 *     asserts below are evaluated on the state between edge E and edge
 *     E+1 (i.e. "during cycle N+1"), with ui_in/uio_in free in every step.
 *     It checks value, destination and cycle-exact timing at the registered
 *     boundary. It cannot see anything that happens BETWEEN edges: the
 *     clock net is not modelled, so (for example) an output register
 *     clocked on the falling edge is indistinguishable from one clocked on
 *     the rising edge.
 *   - FINE model (`FINE`, elaborated through Yosys `clk2fflogic`): `clk`
 *     becomes an ordinary free input and every solver step is a time
 *     sample at which clk, ui_in and uio_in may all change independently.
 *     The asserts below are then evaluated at EVERY sample (always @*), and
 *     the harness adds F1: an output may change only in a sample where a
 *     rising clk edge occurred. Limits: zero-delay RTL semantics, so this
 *     says nothing about physical pads, clock-tree skew, setup/hold or
 *     glitches inside a sample (#106/#94 territory); and the reset request
 *     is clock-synchronised by the harness, so asynchronous reset assertion
 *     between edges is not explored.
 *
 * ASSERTIONS
 *   A1  out of reset, at every sampling point: uo_out == exp_uo and
 *       uio_out == exp_uio. Value, destination and timing at once: a late,
 *       early, wrong-port or wrong-value write mismatches.
 *   A2  event form over consecutive edge-samples: an output differs from
 *       its previous-sample value only if the previous cycle executed an OUT
 *       to exactly that port, and then it equals that OUT's source value;
 *       otherwise it holds. Spurious updates from non-OUT instructions,
 *       read-only-port OUTs, WAIT stalls, HALT, load phase or the priming
 *       cycle all fail A2 (and A1).
 *
 * COVERS (non-vacuity; a bounded or unbounded PASS is only meaningful if a
 * real OUT executes): OUT of each of the four source registers to each of
 * the two writable ports with a NONZERO value that visibly changes the pin
 * (8 covers); back-to-back OUTs with distinct values; back-to-back OUTs one
 * to each port with the other port holding; an OUT executed after a WAIT
 * stall; an OUT to a read-only port retiring; a nonzero pin held through a
 * WAIT stall; a nonzero pin held after HALT.
 */

`default_nettype none

module pin_write_latency (
    input wire        clk,
    input wire        rst_n,
    input wire        exec_valid,   // an instruction occupies `instr` this cycle (run phase, priming excluded)
    input wire [15:0] instr,        // the instruction word being executed (stable through WAIT stalls)
    input wire [7:0]  ui_in,        // read-only port 00, free
    input wire [7:0]  uio_in,       // read-only port 01, free
    input wire [7:0]  uo_out,       // DUT port 10 output register
    input wire [7:0]  uio_out       // DUT port 11 output register
);

  // DR 0001 "Encoding": [15:12] opcode, [11:10] Rd (for OUT: the SOURCE
  // register), [9:8] Rs / port, [7:0] imm8.
  wire [3:0] op  = instr[15:12];
  wire [1:0] rd  = instr[11:10];
  wire [1:0] rs  = instr[9:8];
  wire [7:0] imm = instr[7:0];

  // Shadow architectural state (independent of the DUT).
  reg [7:0] s_r0, s_r1, s_r2, s_r3;
  reg       s_halted;
  reg [7:0] s_wait_rem;
  reg [7:0] exp_uo, exp_uio;

  function [7:0] rdreg(input [1:0] i, input [7:0] a, input [7:0] b, input [7:0] c, input [7:0] d);
    case (i) 2'd0: rdreg = a; 2'd1: rdreg = b; 2'd2: rdreg = c; default: rdreg = d; endcase
  endfunction
  wire [7:0] v_rd = rdreg(rd, s_r0, s_r1, s_r2, s_r3);
  wire [7:0] v_rs = rdreg(rs, s_r0, s_r1, s_r2, s_r3);

  wire executing = exec_valid && !s_halted && (s_wait_rem == 8'd0);
  wire stalling  = exec_valid && !s_halted && (s_wait_rem != 8'd0);

  // Result written back to Rd (LDI/MOV/ALU/IN), per DR 0001.
  reg       wr_rd;
  reg [7:0] wr_val;
  always @* begin
    wr_rd  = 1'b0;
    wr_val = 8'h00;
    case (op)
      4'h1: begin wr_rd = 1'b1; wr_val = imm; end                       // LDI
      4'h2: begin wr_rd = 1'b1; wr_val = v_rs; end                      // MOV
      4'h3: begin wr_rd = 1'b1; wr_val = v_rd + v_rs; end               // ADD
      4'h4: begin wr_rd = 1'b1; wr_val = v_rd - v_rs; end               // SUB
      4'h5: begin wr_rd = 1'b1; wr_val = v_rd & v_rs; end               // AND
      4'h6: begin wr_rd = 1'b1; wr_val = v_rd | v_rs; end               // OR
      4'h7: begin wr_rd = 1'b1; wr_val = v_rd ^ v_rs; end               // XOR
      4'h8: begin wr_rd = 1'b1;                                         // SHF: dir = Rs[0], 1 = left
                  wr_val = rs[0] ? {v_rd[6:0], 1'b0} : {1'b0, v_rd[7:1]}; end
      4'h9: begin                                                       // IN: ports 00/01 only
                  if (rs == 2'd0)      begin wr_rd = 1'b1; wr_val = ui_in;  end
                  else if (rs == 2'd1) begin wr_rd = 1'b1; wr_val = uio_in; end
            end
      default: ;                                                        // NOP/OUT/WAIT/JMP/BZ/BNZ/HALT: no Rd write
    endcase
  end

  wire is_out  = executing && (op == 4'hA);
  wire out_uo  = is_out && (rs == 2'd2);   // OUT to port 10 (uo_out)
  wire out_uio = is_out && (rs == 2'd3);   // OUT to port 11 (uio_out)
  wire out_ro  = is_out && !rs[1];         // OUT to read-only port 00/01: architectural no-op

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_r0 <= 8'h00; s_r1 <= 8'h00; s_r2 <= 8'h00; s_r3 <= 8'h00;
      s_halted   <= 1'b0;
      s_wait_rem <= 8'd0;
      exp_uo     <= 8'h00;   // documented reset behaviour: pins reset to 0
      exp_uio    <= 8'h00;
    end else begin
      if (stalling) s_wait_rem <= s_wait_rem - 8'd1;
      if (executing) begin
        if (wr_rd) begin
          case (rd)
            2'd0: s_r0 <= wr_val;
            2'd1: s_r1 <= wr_val;
            2'd2: s_r2 <= wr_val;
            default: s_r3 <= wr_val;
          endcase
        end
        if (op == 4'hB) s_wait_rem <= imm;     // WAIT imm8: imm8 stall cycles follow (0 = none)
        if (op == 4'hF) s_halted   <= 1'b1;    // HALT: idle until reset
        if (out_uo)  exp_uo  <= v_rd;          // pre-edge source value, captured at the retiring edge
        if (out_uio) exp_uio <= v_rd;
      end
    end
  end

  // ---------------------------------------------------------------------
  // Past frame for A2 and the covers: what the previous cycle looked like.
  // f_valid is low until the first post-reset edge.
  // ---------------------------------------------------------------------
  reg       f_valid;
  reg [7:0] f_uo, f_uio;
  reg       f_out_uo, f_out_uio, f_out_ro, f_out_any;
  reg [7:0] f_src;
  reg [1:0] f_rd;
  reg       f_stalled_before;  // a WAIT stall has been observed since reset
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      f_valid   <= 1'b0; f_uo <= 8'h00; f_uio <= 8'h00;
      f_out_uo  <= 1'b0; f_out_uio <= 1'b0; f_out_ro <= 1'b0; f_out_any <= 1'b0;
      f_src     <= 8'h00; f_rd <= 2'd0; f_stalled_before <= 1'b0;
    end else begin
      f_valid   <= 1'b1;
      f_uo      <= uo_out;
      f_uio     <= uio_out;
      f_out_uo  <= out_uo;
      f_out_uio <= out_uio;
      f_out_ro  <= out_ro;
      f_out_any <= out_uo || out_uio;
      f_src     <= v_rd;
      f_rd      <= rd;
      if (stalling) f_stalled_before <= 1'b1;
    end
  end

  // ---------------------------------------------------------------------
  // Assertions. EDGE build: sampled once per clock cycle. FINE build: at
  // every time sample (all state read is flop state or a free input, so
  // the same statements are meaningful between edges).
  // ---------------------------------------------------------------------
`ifdef FINE
  always @* begin
`else
  always @(posedge clk) begin
`endif
    if (rst_n) begin
      // A1: output registers equal the independently derived expectation.
      assert (uo_out  == exp_uo);
      assert (uio_out == exp_uio);
      if (f_valid) begin
        // A2: update iff the previous cycle executed an OUT to THIS port,
        // and then to exactly that OUT's source value; else hold.
        if (f_out_uo)  assert (uo_out  == f_src); else assert (uo_out  == f_uo);
        if (f_out_uio) assert (uio_out == f_src); else assert (uio_out == f_uio);
      end
    end
  end

  // ---------------------------------------------------------------------
  // Covers (non-vacuity).
  // ---------------------------------------------------------------------
  genvar k;
  generate
    for (k = 0; k < 4; k = k + 1) begin : g_cov
      // OUT of source register k to port 10 / port 11 with a NONZERO value
      // that visibly changes the pin one cycle later.
      always @(posedge clk) begin
        if (rst_n && f_valid) begin
          cover (f_out_uo  && f_rd == k && f_src != 8'h00 && uo_out  == f_src && uo_out  != f_uo);
          cover (f_out_uio && f_rd == k && f_src != 8'h00 && uio_out == f_src && uio_out != f_uio);
        end
      end
    end
  endgenerate

  always @(posedge clk) begin
    if (rst_n && f_valid) begin
      // C9: back-to-back OUTs (consecutive cycles) with distinct values.
      cover (f_out_any && (out_uo || out_uio) && (v_rd != f_src));
      // C10: back-to-back OUTs, port 10 then port 11, distinct values: the
      // first pin shows its value while the second (other) port holds.
      cover (f_out_uo && out_uio && (v_rd != f_src) && (uo_out == f_src) && (uio_out == f_uio));
      // C11: an OUT executing after a WAIT stall was observed.
      cover (f_stalled_before && (out_uo || out_uio));
      // C12: an OUT to a read-only port retired (the architectural no-op).
      cover (f_out_ro);
      // C13: a nonzero pin value held through a WAIT stall cycle.
      cover (stalling && (uo_out != 8'h00 || uio_out != 8'h00));
      // C14: a nonzero pin value held after HALT.
      cover (s_halted && (uo_out != 8'h00 || uio_out != 8'h00));
    end
  end

endmodule

`default_nettype wire
