/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Formal property `i2c_ack_window` (issue #259, part of #243; target-spec
 * row 12): the committed I2C controller-write images sample each ninth-
 * clock ACK INSIDE the ninth SCL high, release SDA for the ACK, and turn an
 * address NACK into STOP without a data byte.
 *
 * INDEPENDENT MONITOR. This file shares nothing with the core's branch or
 * decode logic. Every window it checks is derived from the BUS alone: it
 * watches the resolved SCL and SDA levels (the harness builds them from the
 * core's real uio_out / uio_dir / uio_od state through the top level's
 * uio_oe formula, plus the modelled peripheral) and keeps its own counters:
 *
 *   START  = SDA falls while SCL is high (and was high the cycle before);
 *   STOP   = SDA rises while SCL is high;
 *   nrise  = SCL rising edges seen since START. The Nth rise opens SCL
 *            high phase N; clocks 1..8 are the address byte and clock 9 is
 *            the address ACK slot; clocks 10..17 are the data byte and
 *            clock 18 is the data ACK slot. ("ninth rise" = clock 9 rise,
 *            "ninth fall" = the fall that ends high phase 9.)
 *
 * The one thing the monitor takes from the core side is `in_pulse`: "an IN
 * of port UIO_IN executes this cycle", which the harness decodes from the
 * instruction word of the constant image and the harness's own execute-
 * eligibility. That is the SAMPLING INSTANT being graded; it is not used to
 * define any window.
 *
 * ASSERTIONS (A* = checked every cycle in every explored trace)
 *   A1  SDA is released (the controller's uio_oe[3] is low) from the cycle
 *       of the clock-8 fall (ACK low phase start) through every cycle of
 *       the ninth high, for both ACK slots. The ninth-fall cycle itself is
 *       outside: the controller may present the next bit there.
 *   A2  An IN of uio_in executes only strictly after the ninth rise (the
 *       rise cycle is excluded: SCL high in this cycle AND the previous one)
 *       and before the ninth fall (SCL still high this cycle), in the
 *       address or the data ACK slot. Any other IN is a failure.
 *   A3  Exactly one such IN per ACK-slot high phase: a second one fails when
 *       it executes (extra), and none by the ninth fall fails at the fall
 *       (missing).
 *   A4  Address NACK (SDA high in the last cycle of high phase 9): no data
 *       byte -- no later SCL high phase may end in an SCL fall (a data clock)
 *       -- and STOP follows. Address ACK (SDA low): STOP may not occur
 *       before the data byte is clocked.
 *   A5  After the data ninth fall, whether ACKed or NACKed, no further
 *       clock; the transfer terminates in STOP (data NACK needs no branch).
 *   A6  STOP follows the NACKed/data ninth fall within STOP_BOUND cycles,
 *       the sum of the two committed STOP sections of the assembled image
 *       (pre-STOP low + STOP setup; derived by the runner from the image's
 *       cycle report, never typed here).
 *
 * ENVIRONMENT (the modelled peripheral). `p_raw` is a free input per cycle:
 * the peripheral's wish to pull SDA low (= ACK) or release it. What the
 * peripheral actually drives (`p_low`) is built so the I2C rules hold BY
 * CONSTRUCTION, not through a flagged assumption (a flagged illegal
 * peripheral would still steer the bus, and with it this monitor's own
 * START/STOP tracking, in the solver's view):
 *   E1  p_low is 0 except in an ACK slot (clock-8 fall through the ninth
 *       high, plus the ninth-fall cycle itself, held);
 *   E2  p_low is p_raw while SCL is low in the slot and in the ninth-rise
 *       cycle, then HELD for the rest of the ninth high and the ninth-fall
 *       cycle (stable throughout the high phase);
 *   E3  (the one constraint that has to be a trace restriction, because it
 *       looks at the future of p_raw relative to a rise the firmware
 *       chooses) at the ninth rise p_raw has been unchanged for at least
 *       SU_CYC cycles (t_SU;DAT in cycles at the bench's nominal 20 ns
 *       clock: 5 Fast, 13 Standard). A trace that violates it sets a sticky
 *       flag and every assertion is vacuous from then on, so the solver
 *       cannot use an illegal peripheral to break the firmware.
 *   ADDR_OUTCOME case split (the runner runs both): 1 = the address slot's
 *       high-phase value is ACK, 0 = NACK, 2 = free. It is exhaustive (E2
 *       makes the high value the rise-cycle value, and e4 requires p_raw to
 *       equal it there) and keeps the core's branch outcome a constant; the
 *       free setting makes the core's program counter depend on the whole
 *       peripheral history and the solvers do not finish it.
 * Inside the ACK low phase p_raw is otherwise free every cycle: ACK may
 * appear, vanish and reappear, in any cycle at or after the original early
 * sample instant, and nothing requires agreement with any earlier IN. No
 * assertion below depends on WHEN the peripheral answers; the constraints
 * only decide which traces are legal (and so which covers count). SCL is
 * never stretched (the harness has no peripheral SCL drive).
 *
 * Covers (`COVER`, one per source line, labelled `// cover: <name>`) show
 * every outcome is reachable by a LEGAL peripheral. In the plain build they
 * are `cover`; in the ABC build (`COVERABC`) the one selected by COVER_SEL
 * becomes `assert(!cond)` so a counterexample means "reached".
 *
 * Zero-delay logical model, EDGE clocking (one solver step per clock), no
 * pad delay or pull-up rise time: nothing here is an electrical claim.
 */

`default_nettype none

`ifndef SU_CYC
 `error "SU_CYC must be defined by the runner"
`endif
`ifndef STOP_BOUND
 `error "STOP_BOUND must be defined by the runner"
`endif
`ifndef FORMER_AGE
 `error "FORMER_AGE must be defined by the runner"
`endif
`ifndef ADDR_OUTCOME
 `define ADDR_OUTCOME 2
`endif

`ifndef COVER_SEL
 `define COVER_SEL 0
`endif
// COVERABC (ABC build): the cover numbered COVER_SEL becomes
// `assert(!cond)`, so a counterexample means "reached". Otherwise a plain
// `cover`. Both only count while the modelled peripheral has been legal
// (`env_ok`), so a reached cover is a legal trace. Each cover is one source line with a `// cover: <name>` label.
`ifdef COVERABC
 `define COVER(n, c) always @(posedge clk) if (`COVER_SEL == n && env_ok) assert (!(c));
`else
 `define COVER(n, c) always @(posedge clk) if (env_ok) cover (c);
`endif

module i2c_ack_window (
    input wire clk,
    input wire rst_n,
    input wire scl,       // resolved bus level this cycle
    input wire sda,       // resolved bus level this cycle
    input wire sda_oe,    // controller output enable on the SDA pad (uio_oe[3])
    input wire p_raw,     // free: the modelled peripheral's wish to pull SDA low
    output wire p_low,    // what the peripheral actually drives (see ADDR_OUTCOME)
    input wire in_pulse   // an IN of uio_in executes this cycle
);

  localparam integer SU_CYC     = `SU_CYC;
  localparam integer STOP_BOUND = `STOP_BOUND;
  localparam integer FORMER_AGE = `FORMER_AGE;
  localparam integer ADDR_OUTCOME = `ADDR_OUTCOME;  // 1 ACK, 0 NACK, 2 free

  reg        scl_q = 1'b1, sda_q = 1'b1, pl_q = 1'b0;
  reg        active = 1'b0;
  reg  [4:0] nrise_q = 5'd0;
  reg  [1:0] in_cnt = 2'd0;
  reg        a_phase = 1'b0, a_nack = 1'b0;
  reg        d_phase = 1'b0, d_nack = 1'b0;
  reg        pend = 1'b0;
  reg  [10:0] pend_cnt = 11'd0;
  reg  [8:0] age_r = 9'h1FF;
  reg  [9:0] lage_r = 10'h3FF;
  reg        late_ack = 1'b0, eold = 1'b0;
  reg  [1:0] nchg = 2'd0;
  reg        bad_q = 1'b0;

  wire rise     = scl && !scl_q;
  wire fall     = !scl && scl_q;
  wire start_ev = scl && scl_q && sda_q && !sda;
  wire stop_ev  = scl && scl_q && !sda_q && sda;

  wire [4:0] nr = nrise_q + ((rise && active) ? 5'd1 : 5'd0);
  wire slot9  = active && (nr == 5'd9);
  wire slot18 = active && (nr == 5'd18);
  wire slot   = slot9 || slot18;
  wire pre9   = active && (nr == 5'd8);
  wire pre18  = active && (nr == 5'd17);

  wire ack_low  = (pre9 || pre18) && !scl;      // clock-8/17 fall .. ninth rise (exclusive)
  wire ack_high = slot && scl;                  // ninth high, including its rise cycle
  wire ack_fall = slot && fall;                 // the ninth fall
  wire in_valid = in_pulse && ack_high && scl_q;

  // ------------------------------------------- peripheral and its checks
  // E1/E2 hold BY CONSTRUCTION, not by a flagged assumption: a flagged
  // illegal peripheral would still steer the bus (and so this monitor's own
  // START/STOP tracking) in the solver's view and make every later cone
  // symbolic. The peripheral therefore drives
  //   - p_raw (free, any change at any cycle) while SCL is low in an ACK slot;
  //   - at the ninth rise cycle, p_raw (with the SU_CYC check E3 below), then
  //     in the rest of the high phase and in the ninth-fall cycle the value
  //     it had in the cycle before (held: stable throughout the high);
  //   - 0 (released) in every other cycle.
  // Case split (ADDR_OUTCOME 0 or 1): the address slot's high-phase value is
  // the constant, and e4 requires the free p_raw to equal it at the rise
  // (the rise-cycle value IS the high value). The split is exhaustive and
  // keeps the core's branch outcome a constant for the solvers.
  wire force_a = (ADDR_OUTCOME != 2) && slot9;
  wire force_v = (ADDR_OUTCOME == 1);
  wire hold_ph = (ack_high && !rise) || ack_fall;
  assign p_low = ack_low ? p_raw
               : (rise && slot) ? (force_a ? force_v : p_raw)
               : hold_ph ? pl_q
               : 1'b0;
  wire e4      = force_a && rise && (p_raw != force_v);
  wire chg     = (p_low != pl_q);
  wire [8:0] age_now = chg ? 9'd0 : ((age_r == 9'h1FF) ? 9'h1FF : age_r + 9'd1);
  wire e3      = rise && slot && (age_now < SU_CYC);
  wire bad_now = e3 || e4;
  wire env_ok  = !(bad_q || bad_now) && rst_n;

  // ack-low-phase age: 0 in the clock-8/17 fall cycle
  wire low_start = fall && (pre9 || pre18);
  wire [9:0] lage_now = low_start ? 10'd0 : ((lage_r == 10'h3FF) ? 10'h3FF : lage_r + 10'd1);

  // ------------------------------------------------------------- state
  always @(posedge clk) begin
    if (!rst_n) begin
      scl_q <= 1'b1; sda_q <= 1'b1; pl_q <= 1'b0;
      active <= 1'b0; nrise_q <= 5'd0; in_cnt <= 2'd0;
      a_phase <= 1'b0; a_nack <= 1'b0; d_phase <= 1'b0; d_nack <= 1'b0;
      pend <= 1'b0; pend_cnt <= 11'd0;
      age_r <= 9'h1FF; lage_r <= 10'h3FF;
      late_ack <= 1'b0; eold <= 1'b0; nchg <= 2'd0; bad_q <= 1'b0;
    end else begin
      scl_q <= scl; sda_q <= sda; pl_q <= p_low;
      bad_q <= bad_q || bad_now;
      age_r <= age_now;
      lage_r <= lage_now;

      if (stop_ev) begin
        active <= 1'b0; nrise_q <= 5'd0;
        a_phase <= 1'b0; d_phase <= 1'b0; pend <= 1'b0;
      end else if (start_ev) begin
        active <= 1'b1; nrise_q <= 5'd0;
        a_phase <= 1'b0; d_phase <= 1'b0; pend <= 1'b0;
      end else if (active) begin
        nrise_q <= nr;
      end

      if (rise) in_cnt <= 2'd0;
      else if (in_valid && in_cnt != 2'd3) in_cnt <= in_cnt + 2'd1;

      if (ack_fall && slot9)  begin a_phase <= 1'b1; a_nack <= sda_q; end
      if (ack_fall && slot18) begin d_phase <= 1'b1; d_nack <= sda_q; end
      if (ack_fall && ((slot9 && sda_q) || slot18)) begin
        pend <= 1'b1; pend_cnt <= 11'd0;
      end else if (pend && !stop_ev) begin
        pend_cnt <= (pend_cnt == 11'h7FF) ? 11'h7FF : pend_cnt + 11'd1;
      end

      // per-window peripheral-history flags for the covers
      if (low_start) begin late_ack <= 1'b0; nchg <= 2'd0; end
      else if (ack_low && chg) begin
        if (nchg != 2'd3) nchg <= nchg + 2'd1;
        if (p_low && lage_now > FORMER_AGE) late_ack <= 1'b1;
      end
      if (ack_low && lage_now == FORMER_AGE) eold <= p_low;
    end
  end

  // -------------------------------------------------------- assertions
  wire a_seen_nack = a_phase && a_nack;

  always @(posedge clk) if (rst_n) begin
    // A1
a1_sda_released: assert (!env_ok || !(ack_low || ack_high) || !sda_oe);
    // A2
a2_in_window: assert (!env_ok || !in_pulse || in_valid);
    // A3 extra / missing
a3_extra_sample: assert (!env_ok || !(in_valid && in_cnt != 2'd0));
a3_missing_sample: assert (!env_ok || !ack_fall || in_cnt == 2'd1);
    // A4
a4_no_data_after_nack: assert (!env_ok || !(fall && active && nr >= 5'd10 && nr < 5'd18 && a_seen_nack));
a4_ack_continues_to_data: assert (!env_ok || !(stop_ev && a_phase && !a_nack && !d_phase && nrise_q < 5'd18));
    // A5
a5_no_clock_after_data_ack: assert (!env_ok || !(fall && active && nr >= 5'd19 && d_phase));
    // A6 (bounded STOP)
a6_stop_bound: assert (!env_ok || !(pend && pend_cnt > STOP_BOUND));
  end

  // ------------------------------------------------------------ covers
  wire samp9  = in_valid && slot9;
  wire samp18 = in_valid && slot18;
  `COVER(1, samp9 && !sda)                                  // cover: addr_ack_sampled
  `COVER(2, samp9 && sda)                                   // cover: addr_nack_sampled
  `COVER(3, samp18 && !sda)                                 // cover: data_ack_sampled
  `COVER(4, samp18 && sda)                                  // cover: data_nack_sampled
  `COVER(5, stop_ev && a_seen_nack && nrise_q == 5'd10)     // cover: addr_nack_stop_no_data
  `COVER(6, stop_ev && d_phase && !d_nack)                  // cover: data_ack_stop
  `COVER(7, stop_ev && d_phase && d_nack)                   // cover: data_nack_stop
  `COVER(8, samp9 && !sda && late_ack && !eold)             // cover: addr_ack_after_former_sample
  `COVER(9, samp9 && sda && eold)                           // cover: addr_ack_withdrawn_after_former_sample
  `COVER(10, samp18 && !sda && late_ack && !eold)            // cover: data_ack_after_former_sample
  `COVER(11, samp18 && sda && eold)                          // cover: data_ack_withdrawn_after_former_sample
  `COVER(12, rise && slot9 && nchg == 2'd3)                  // cover: addr_ack_low_phase_changes_3plus

endmodule

`default_nettype wire
