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
 * DR 0012 CONTROL SPACE (issue #135). Two of DR 0001's no-op encodings now
 * do something: `OUT` to port 00 is `WCTL k, Rs` and `IN` from port 10 is
 * `RCTL Rd, k` (k = imm8). Neither writes a pin, but `RCTL` writes a
 * general-purpose register that a later `OUT` can put on one, and three
 * accesses take a fixed second cycle in which nothing executes. So the
 * shadow model grew, written from DR 0012's sections 1-2 (its register map
 * and latency table), not from the core:
 *
 *   - s_dir, s_od, s_pmaddr, s_pmlo : UIO_DIR, UIO_OD, PM_ADDR and the
 *                   low-byte latch (the registers RCTL can read back that
 *                   are core state);
 *   - s_stall     : the fixed second cycle of WCTL PM_DATA_LO, WCTL RUN
 *                   and RCTL PM_DATA_HI is in progress (nothing executes);
 *   - s_stall_rd  : for RCTL PM_DATA_HI, where the high byte lands.
 *
 * Three RCTL sources are not core state and reach the monitor as inputs,
 * the same nets the harness hands the core: `pm_crc` and `serial_loaded`
 * (free every cycle in the harness), and the program-memory read data,
 * which DR 0012 defines as the word the memory returns in the stall cycle
 * -- i.e. `instr` in that cycle. HW_ID is the core's documented constant.
 * What a program-memory WRITE does to memory contents is outside this
 * property (the harness's program table is a constant; the cocotb bench
 * verification/test_control_space.py owns that).
 *
 * DR 0013 LAYER 2 BOOT ROM (issue #138). The core now has two instruction
 * sources -- the boot ROM and program memory -- and decodes one of them
 * per cycle. The shadow model does NOT take the core's word for which: it
 * receives BOTH words (`rom_instr` and `instr`, the harness's two free
 * tables behind their registered read ports) and selects with its own
 * state, written from DR 0013 ("At `rst_n` release with `MODE` low, fetch
 * comes from a small boot ROM instead of program memory"; a serial load
 * runs program memory "as today") and DR 0012 (`RUN`: "switch the fetch
 * source to program memory"):
 *
 *   - s_rom_exit  : a WCTL RUN has completed since reset;
 *   - s_from_rom  = !serial_loaded && !s_rom_exit -- the ROM is the source
 *                   unless a serial load completed or a RUN has left it;
 *   - s_stall_run : the control-access stall in progress is a RUN's (so
 *                   its end is where the source switches).
 *
 * The instruction the shadow executes is `rom_instr` when s_from_rom and
 * `instr` otherwise; a RUN's own stall cycle still belongs to the source
 * the RUN was decoded from. `BOOT_STATUS` reads {s_from_rom,
 * serial_loaded} in bits [1:0]. Program-memory READ DATA (the stall cycle
 * of RCTL PM_DATA_HI) is always `instr`, whichever source is selected:
 * the ROM has no data port. A core that decodes the wrong source, switches
 * at the wrong cycle, or misreports BOOT_STATUS[1] therefore drives a pin
 * the shadow does not expect, for some pair of free tables. The core's
 * `fetch_rom` output is deliberately not an input of this monitor.
 *
 * Execution eligibility ("is the instruction on `instr` executing this
 * cycle") is derived HERE: exec_valid (from the harness's phase model --
 * run phase with DR 0005's priming cycle excluded, never the core's
 * fetch_valid) AND NOT s_halted AND s_wait_rem == 0 AND NOT s_stall. No core-internal
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
 *       the reserved OUT to port 01, a WCTL (OUT to port 00), WAIT stalls,
 *       control-access stall cycles, HALT, load phase or the priming cycle
 *       all fail A2 (and A1).
 *
 * COVERS (non-vacuity; a bounded or unbounded PASS is only meaningful if a
 * real OUT executes): OUT of each of the four source registers to each of
 * the two writable ports with a NONZERO value that visibly changes the pin
 * (8 covers); back-to-back OUTs with distinct values; back-to-back OUTs one
 * to each port with the other port holding; an OUT executed after a WAIT
 * stall; an OUT to the reserved read-only port 01 retiring; a nonzero pin
 * held through a WAIT stall; a nonzero pin held after HALT. DR 0012: a WCTL
 * retiring with a nonzero pin held; a nonzero pin held through a
 * control-access stall cycle; and a value read by RCTL (a 1-cycle index,
 * and the 2-cycle PM_DATA_HI) later driven onto a pin by an OUT -- the
 * path by which a wrong RCTL would reach a pin. DR 0013: an OUT decoded
 * from the boot ROM changing a pin; an OUT decoded from program memory
 * changing a pin after a RUN left the ROM; and BOOT_STATUS read from the
 * ROM (bit 1 set) driven onto a pin.
 */

`default_nettype none

module pin_write_latency (
    input wire        clk,
    input wire        rst_n,
    input wire        exec_valid,   // an instruction occupies `instr` this cycle (run phase, priming excluded)
    input wire [15:0] instr,        // program memory's registered output: the instruction when PM is the
                                    // fetch source, and the read data in an RCTL PM_DATA_HI stall cycle
    input wire [15:0] rom_instr,    // DR 0013: the boot ROM's registered output (the instruction when the ROM is the source)
    input wire [7:0]  ui_in,        // read-only port 00, free
    input wire [7:0]  uio_in,       // read-only port 01, free
    input wire [7:0]  uo_out,       // DUT port 10 output register
    input wire [7:0]  uio_out,      // DUT port 11 output register
    input wire [15:0] pm_crc,       // DR 0012 PM_CRC as handed to the core (free in the harness)
    input wire        serial_loaded // DR 0012 BOOT_STATUS[0] as handed to the core (free in the harness)
);

  // DR 0012 section 2: control-register indices, and the core's documented
  // HW_ID constant (rtl/protocol_core.v parameter default).
  localparam [7:0] K_UIO_DIR = 8'h00, K_UIO_OD = 8'h01, K_PM_ADDR = 8'h02,
                   K_PM_DATA_HI = 8'h03, K_PM_DATA_LO = 8'h04, K_RUN = 8'h05,
                   K_PM_CRC_LO = 8'h06, K_PM_CRC_HI = 8'h07,
                   K_BOOT_STATUS = 8'h08, K_HW_ID = 8'h09;
  localparam [7:0] HW_ID_VALUE = 8'h01;

  // DR 0001 "Encoding": [15:12] opcode, [11:10] Rd (for OUT: the SOURCE
  // register), [9:8] Rs / port, [7:0] imm8.
  //
  // DR 0013 layer 2: which word that is. The ROM is the fetch source from
  // reset unless a serial load completed, until a WCTL RUN completes.
  reg         s_rom_exit;    // a WCTL RUN has completed since reset
  reg         s_stall_run;   // the control stall in progress is a RUN's
  wire        s_from_rom = !serial_loaded && !s_rom_exit;
  wire [15:0] xw  = s_from_rom ? rom_instr : instr;
  wire [3:0] op  = xw[15:12];
  wire [1:0] rd  = xw[11:10];
  wire [1:0] rs  = xw[9:8];
  wire [7:0] imm = xw[7:0];

  // Shadow architectural state (independent of the DUT).
  reg [7:0] s_r0, s_r1, s_r2, s_r3;
  reg       s_halted;
  reg [7:0] s_wait_rem;
  reg [7:0] exp_uo, exp_uio;
  // DR 0012 shadow state.
  reg [7:0] s_dir, s_od, s_pmaddr, s_pmlo;
  reg       s_stall;       // second cycle of a 2-cycle control access
  reg       s_stall_pmrd;  // ...of an RCTL PM_DATA_HI (instr = read data now)
  reg [1:0] s_stall_rd;    // ...whose high byte lands in this register

  function [7:0] rdreg(input [1:0] i, input [7:0] a, input [7:0] b, input [7:0] c, input [7:0] d);
    case (i) 2'd0: rdreg = a; 2'd1: rdreg = b; 2'd2: rdreg = c; default: rdreg = d; endcase
  endfunction
  wire [7:0] v_rd = rdreg(rd, s_r0, s_r1, s_r2, s_r3);
  wire [7:0] v_rs = rdreg(rs, s_r0, s_r1, s_r2, s_r3);

  wire executing = exec_valid && !s_halted && (s_wait_rem == 8'd0) && !s_stall;
  wire stalling  = exec_valid && !s_halted && (s_wait_rem != 8'd0);
  wire ctl_stalling = exec_valid && !s_halted && s_stall;  // WAIT and a control stall never overlap

  // DR 0012 decode: WCTL = OUT to port 00, RCTL = IN from port 10.
  wire is_wctl  = (op == 4'hA) && (rs == 2'd0);
  wire is_rctl  = (op == 4'h9) && (rs == 2'd2);
  wire rctl_two = is_rctl && (imm == K_PM_DATA_HI);                        // R 2 cycles
  wire wctl_two = is_wctl && (imm == K_PM_DATA_LO || imm == K_RUN);        // W 2 cycles

  // RCTL value for every 1-cycle index (DR 0012 register map; unassigned
  // and write-only indices read 0x00).
  reg [7:0] rctl_v;
  always @* begin
    case (imm)
      K_UIO_DIR:     rctl_v = s_dir;
      K_UIO_OD:      rctl_v = s_od;
      K_PM_ADDR:     rctl_v = s_pmaddr;
      K_PM_DATA_LO:  rctl_v = s_pmlo;
      K_PM_CRC_LO:   rctl_v = pm_crc[7:0];
      K_PM_CRC_HI:   rctl_v = pm_crc[15:8];
      K_BOOT_STATUS: rctl_v = {6'b000000, s_from_rom, serial_loaded};  // DR 0012: bit 1 = running from the boot ROM
      K_HW_ID:       rctl_v = HW_ID_VALUE;
      default:       rctl_v = 8'h00;
    endcase
  end

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
      4'h9: begin                                                       // IN: ports 00/01; port 10 = RCTL
                  if (rs == 2'd0)      begin wr_rd = 1'b1; wr_val = ui_in;  end
                  else if (rs == 2'd1) begin wr_rd = 1'b1; wr_val = uio_in; end
                  else if (rs == 2'd2 && !rctl_two)                    // RCTL, 1-cycle index
                                       begin wr_rd = 1'b1; wr_val = rctl_v; end
                  // RCTL PM_DATA_HI writes Rd in its stall cycle (below);
                  // IN from port 11 is the reserved no-op.
            end
      default: ;                                                        // NOP/OUT/WAIT/JMP/BZ/BNZ/HALT: no Rd write
    endcase
  end

  wire is_out  = executing && (op == 4'hA);
  wire out_uo  = is_out && (rs == 2'd2);   // OUT to port 10 (uo_out)
  wire out_uio = is_out && (rs == 2'd3);   // OUT to port 11 (uio_out)
  wire out_ro  = is_out && (rs == 2'd1);   // OUT to port 01: the reserved architectural no-op
  wire out_ctl = is_out && (rs == 2'd0);   // OUT to port 00: WCTL -- writes a control register, never a pin

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s_r0 <= 8'h00; s_r1 <= 8'h00; s_r2 <= 8'h00; s_r3 <= 8'h00;
      s_halted   <= 1'b0;
      s_wait_rem <= 8'd0;
      exp_uo     <= 8'h00;   // documented reset behaviour: pins reset to 0
      exp_uio    <= 8'h00;
      s_dir <= 8'h00; s_od <= 8'h00; s_pmaddr <= 8'h00; s_pmlo <= 8'h00;  // DR 0012 reset values
      s_stall <= 1'b0; s_stall_pmrd <= 1'b0; s_stall_rd <= 2'd0;
      s_rom_exit <= 1'b0; s_stall_run <= 1'b0;   // DR 0013: the boot ROM is the source after reset
    end else begin
      if (stalling) s_wait_rem <= s_wait_rem - 8'd1;
      if (ctl_stalling) begin
        // The fixed second cycle. For RCTL PM_DATA_HI the memory's read
        // data is on `instr`: high byte to Rd, low byte to the latch.
        s_stall      <= 1'b0;
        s_stall_pmrd <= 1'b0;
        s_stall_run  <= 1'b0;
        // DR 0012 RUN / DR 0013: the word after a RUN's stall comes from
        // program memory, and so does every word after it until reset.
        if (s_stall_run) s_rom_exit <= 1'b1;
        if (s_stall_pmrd) begin
          case (s_stall_rd)
            2'd0: s_r0 <= instr[15:8];
            2'd1: s_r1 <= instr[15:8];
            2'd2: s_r2 <= instr[15:8];
            default: s_r3 <= instr[15:8];
          endcase
          s_pmlo <= instr[7:0];
        end
      end
      if (executing) begin
        // DR 0012 control accesses (no pin is written by any of them).
        if (is_wctl) begin
          case (imm)
            K_UIO_DIR:    s_dir    <= v_rd;
            K_UIO_OD:     s_od     <= v_rd;
            K_PM_ADDR:    s_pmaddr <= v_rd;
            K_PM_DATA_LO: s_pmaddr <= s_pmaddr + 8'd1;   // commit, then PM_ADDR++
            default: ;
          endcase
          if (wctl_two) s_stall <= 1'b1;
          if (imm == K_RUN) s_stall_run <= 1'b1;
        end
        if (is_rctl) begin
          if (rctl_two) begin
            s_stall      <= 1'b1;
            s_stall_pmrd <= 1'b1;
            s_stall_rd   <= rd;
          end else if (imm == K_PM_DATA_LO) begin
            s_pmaddr <= s_pmaddr + 8'd1;                 // return the latch, then PM_ADDR++
          end
        end
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
  reg       f_out_ctl;         // previous cycle executed a WCTL
  // DR 0012 covers: which register last took a value from RCTL (cleared when
  // anything else writes it), so "an RCTL result reached a pin" is observable.
  reg [3:0] c_from_rctl1;      // ...from a 1-cycle RCTL of a nonzero value
  reg [3:0] c_from_pmrd;       // ...from an RCTL PM_DATA_HI
  // DR 0013 covers.
  reg [3:0] c_from_boot1;      // ...from an RCTL BOOT_STATUS decoded from the boot ROM
  reg       f_from_rom;        // previous cycle's instruction came from the boot ROM
  reg       c_rom_out_seen;    // an OUT decoded from the ROM has executed since reset
  reg       c_left_by_run;     // a RUN decoded from the ROM completed since reset
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      f_valid   <= 1'b0; f_uo <= 8'h00; f_uio <= 8'h00;
      f_out_uo  <= 1'b0; f_out_uio <= 1'b0; f_out_ro <= 1'b0; f_out_any <= 1'b0;
      f_src     <= 8'h00; f_rd <= 2'd0; f_stalled_before <= 1'b0;
      f_out_ctl <= 1'b0; c_from_rctl1 <= 4'b0000; c_from_pmrd <= 4'b0000;
      c_from_boot1 <= 4'b0000; f_from_rom <= 1'b0;
      c_rom_out_seen <= 1'b0; c_left_by_run <= 1'b0;
    end else begin
      f_out_ctl <= out_ctl;
      f_from_rom <= s_from_rom;
      if (s_from_rom && (out_uo || out_uio)) c_rom_out_seen <= 1'b1;
      if (ctl_stalling && s_stall_run && s_from_rom) c_left_by_run <= 1'b1;
      if (executing && wr_rd) begin
        c_from_rctl1[rd] <= is_rctl && (wr_val != 8'h00);
        c_from_pmrd[rd]  <= 1'b0;
        c_from_boot1[rd] <= is_rctl && (imm == K_BOOT_STATUS) && s_from_rom;
      end
      if (ctl_stalling && s_stall_pmrd) begin
        c_from_pmrd[s_stall_rd]  <= (instr[15:8] != 8'h00);
        c_from_rctl1[s_stall_rd] <= 1'b0;
        c_from_boot1[s_stall_rd] <= 1'b0;
      end
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
      // C12: an OUT to the reserved read-only port 01 retired (the architectural no-op).
      cover (f_out_ro);
      // C15 (DR 0012): a WCTL retired while a nonzero pin value held.
      cover (f_out_ctl && (uo_out != 8'h00) && (uo_out == f_uo));
      // C16 (DR 0012): a nonzero pin value held through a control-access stall cycle.
      cover (ctl_stalling && (uo_out != 8'h00 || uio_out != 8'h00));
      // C17 (DR 0012): a nonzero value read by a 1-cycle RCTL is driven onto a pin.
      cover (f_out_any && c_from_rctl1[f_rd] && (f_src != 8'h00) &&
             ((f_out_uo && uo_out == f_src) || (f_out_uio && uio_out == f_src)));
      // C18 (DR 0012): a nonzero program-memory high byte (RCTL PM_DATA_HI,
      // 2 cycles) is driven onto a pin.
      cover (f_out_any && c_from_pmrd[f_rd] && (f_src != 8'h00) &&
             ((f_out_uo && uo_out == f_src) || (f_out_uio && uio_out == f_src)));
      // C19 (DR 0013): an OUT decoded from the boot ROM puts a nonzero value on a pin.
      cover (f_out_any && f_from_rom && (f_src != 8'h00) &&
             ((f_out_uo && uo_out == f_src && uo_out != f_uo) ||
              (f_out_uio && uio_out == f_src && uio_out != f_uio)));
      // C20 (DR 0013): after a WCTL RUN left the boot ROM, an OUT decoded from
      // program memory changes a pin a ROM instruction had already written.
      cover (f_out_any && !f_from_rom && c_left_by_run && c_rom_out_seen && (f_src != 8'h00) &&
             ((f_out_uo && uo_out == f_src && uo_out != f_uo) ||
              (f_out_uio && uio_out == f_src && uio_out != f_uio)));
      // C21 (DR 0013): BOOT_STATUS read from the boot ROM (bit 1 set) reaches a pin.
      cover (f_out_any && c_from_boot1[f_rd] && f_src[1] &&
             ((f_out_uo && uo_out == f_src) || (f_out_uio && uio_out == f_src)));
      // C13: a nonzero pin value held through a WAIT stall cycle.
      cover (stalling && (uo_out != 8'h00 || uio_out != 8'h00));
      // C14: a nonzero pin value held after HALT.
      cover (s_halted && (uo_out != 8'h00 || uio_out != 8'h00));
    end
  end

endmodule

`default_nettype wire
