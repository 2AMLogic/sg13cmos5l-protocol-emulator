/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Program memory and serial load-phase logic (target-spec row 6, issue #19).
 *
 * Implements `spec/decision-records/0001-isa.md` section  "Program memory sizing
 * and loading", which is the authoritative contract for this module:
 *
 *   - 256 x 16-bit program words (512 bytes), addressed by an 8-bit
 *     program counter.
 *   - On release of `rst_n`, the mode line (`ui_in[7]`, `MODE`) is sampled:
 *     MODE high at the first clock edge after reset release enters the
 *     **load phase**; MODE low enters the **run phase** directly.
 *   - During load phase, each clock edge shifts one bit from the serial
 *     data line (`ui_in[0]`) into a 16-bit shift register MSB-first.
 *     Every 16 shifted bits commits one program word to memory at an
 *     auto-incrementing write address starting at 0. The commit happens
 *     on the same clock edge as the 16th bit, so a host that holds MODE
 *     high for exactly N*16 bit cycles and then drops it loads exactly N
 *     words with no boundary ambiguity.
 *   - MODE dropping low ends the load phase and begins the run phase at
 *     the next clock cycle. The run phase is signalled by `run_phase`
 *     rising; the core datapath is expected to hold its PC at 0 while
 *     `run_phase` is low and fetch from 0 on the first cycle it is high
 *     (DR 0001: "MODE dropping low ends load phase, resets the program
 *     counter to 0, and begins run phase at the next cycle").
 *   - Mode is latched only at reset release, never sampled mid-run: once
 *     `run_phase` is high, raising MODE again does nothing until a fresh
 *     `rst_n` pulse with MODE held high. This is DR 0001's no-race rule
 *     between a running program and an external reprogram attempt.
 *   - Load phase saturates at 256 words: once all 256 words are written,
 *     further shifted bits are discarded rather than wrapping over the
 *     program just loaded. MODE dropping low remains the only exit to
 *     the run phase.
 *
 * Interface intent (for the core-datapath issue, #18):
 *
 *   - `fetch_addr` is the core's program counter and `instr_word` is the
 *     same-cycle combinational read DR 0001's single-cycle
 *     fetch-and-execute model requires (`assign instr_word = mem[...]`,
 *     no registered read port: a registered read would add an instruction
 *     fetch latency the ISA's cycle determinism does not budget for).
 *   - The core should hold `pc <= 0` while `run_phase` is low so first
 *     fetch lands at address 0 in the cycle after MODE drops. `run_phase`
 *     is also low during reset, so one reset expression covers both
 *     (`if (!rst_n || !run_phase) pc <= 8'd0;`).
 *   - Top wiring (`src/tt_um_2amlogic_protocol_emulator.v`, once the core
 *     lands): `mode_pin` <- `ui_in[7]`, `serial_in` <- `ui_in[0]`. All
 *     other pins are undisturbed by the load mechanism, per DR 0001.
 *   - `ena` (Tiny Tapeout's power/selection line) is deliberately not a
 *     port: DR 0001's load protocol is reset-gated, not power-gated, and
 *     the template documents `ena` as "always 1 when the design is
 *     powered, so you can ignore it".
 *
 * This module is simulation-portable out-of-band state: DR 0001 defines no
 * program-readback instruction (the ISA's 16-opcode table is exactly
 * full), so the verifiable path for "the bits landed where the ISA says"
 * is the fetch port itself -- what the core will execute -- exercised by
 * `verification/test_program_memory.py` after MODE drops.
 */

`default_nettype none

module protocol_program_memory (
    input  wire        clk,        // clock
    input  wire        rst_n,      // reset_n - low to reset; mode is sampled at the first post-release edge
    input  wire        mode_pin,   // ui_in[7] - MODE: high at reset release enters load phase; during load, high = shifting, low = enter run phase
    input  wire        serial_in,   // ui_in[0] - serial program bit, sampled MSB-first during load phase
    input  wire [7:0]  fetch_addr,  // core's 8-bit program counter (run phase)
    output wire [15:0] instr_word,  // combinational fetch read of program memory
    output wire        run_phase    // high once the load phase has ended (or was never entered)
);

  // 256 x 16-bit program memory. Flip-flop based (the target-spec row 6
  // stretch item of an SRAM macro is deliberately not taken here).
  reg [15:0] mem [0:255];

  // Load-phase state.
  reg        started;      // has the post-reset mode-sampling edge happened?
  reg        load_active;  // 1 while in the load phase
  reg        run_phase_r;  // 1 in run phase (normal fetch/execute)
  reg [15:0] shift_reg;    // MSB-first bit accumulator
  reg [3:0]  bit_cnt;      // 0..15 within the current word
  reg [7:0]  wr_addr;      // next program word to be written, 0..255
  reg        full;         // all 256 words loaded: saturate, never wrap

  // Fetch read: combinational, same-cycle, per DR 0001's single-cycle
  // fetch-and-execute timing model.
  assign instr_word = mem[fetch_addr];
  assign run_phase  = run_phase_r;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      started     <= 1'b0;
      load_active <= 1'b0;
      run_phase_r <= 1'b0;
      shift_reg   <= 16'h0000;
      bit_cnt     <= 4'd0;
      wr_addr     <= 8'd0;
      full        <= 1'b0;
    end else begin
      if (!started) begin
        // First clock edge after reset release: the one place MODE is
        // latched (DR 0001: "mode is latched only at reset release, not
        // sampled mid-run").
        started <= 1'b1;
        if (mode_pin) begin
          load_active <= 1'b1;
        end else begin
          run_phase_r <= 1'b1;
        end
      end else if (load_active) begin
        if (!mode_pin) begin
          // MODE dropped low: end load phase, begin run phase next cycle.
          // The partially accumulated word (if any) is discarded -- only
          // complete 16-bit groups commit.
          load_active <= 1'b0;
          run_phase_r <= 1'b1;
        end else begin
          // Shift one bit, MSB-first.
          shift_reg <= {shift_reg[14:0], serial_in};
          if (bit_cnt == 4'd15) begin
            // Commit-on-16th-bit-edge: this edge shifts the final bit AND
            // writes the assembled word, so a host can drop MODE on the
            // very next cycle without losing the word.
            if (!full) begin
              mem[wr_addr] <= {shift_reg[14:0], serial_in};
              if (wr_addr == 8'd255) begin
                full <= 1'b1;
              end else begin
                wr_addr <= wr_addr + 8'd1;
              end
            end
            // After saturation, further groups keep shifting (harmless)
            // but never commit.
            bit_cnt <= 4'd0;
          end else begin
            bit_cnt <= bit_cnt + 4'd1;
          end
        end
      end
      // In run phase there is nothing to do: MODE is not sampled again
      // (no re-entry without a rst_n pulse with MODE high), and program
      // memory is not data-addressable by the ISA.
    end
  end

  // List unused inputs to prevent warnings (none today: every port is
  // consumed by the logic above).

endmodule

`default_nettype wire
