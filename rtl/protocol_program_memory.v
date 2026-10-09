/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Program memory and serial load-phase logic (target-spec row 6, issue #19),
 * backed by the IHP PDK's `RM_IHPSG13_1P_256x16_c2_bm_bist` single-port SRAM
 * macro per `spec/decision-records/0005-program-memory-implementation.md`
 * (issue #18's implementation of that record's Decision item 1).
 *
 * Implements `spec/decision-records/0001-isa.md` section "Program memory
 * sizing and loading", which is the authoritative contract for this module:
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
 *     rising.
 *   - Mode is latched only at reset release, never sampled mid-run: once
 *     `run_phase` is high, raising MODE again does nothing until a fresh
 *     `rst_n` pulse with MODE held high. This is DR 0001's no-race rule
 *     between a running program and an external reprogram attempt.
 *   - Load phase saturates at 256 words: once all 256 words are written,
 *     further shifted bits are discarded rather than wrapping over the
 *     program just loaded. MODE dropping low remains the only exit to
 *     the run phase.
 *
 * ---------------------------------------------------------------------
 * WHAT DR 0005 CHANGED (and what it deliberately did not)
 * ---------------------------------------------------------------------
 *
 * The storage array changed from a flip-flop `reg [15:0] mem [0:255]` to
 * the PDK macro. **Nothing about DR 0001's organisation or load protocol
 * changed**: still 256 x 16, still an 8-bit PC, still MSB-first serial
 * shift-in with commit on the 16th bit's own edge, mid-word discard,
 * 256-word saturation and no mid-run re-entry. DR 0005 Decision item 1:
 * "this is an implementation decision about *what holds the bits*, not a
 * spec change."
 *
 * The one behavioural consequence is the **fetch port's timing**, and it
 * is the DR 0005 "Amendment to DR 0001":
 *
 *   OLD (flip-flop array): `assign instr_word = mem[fetch_addr]` -- an
 *   asynchronous read, valid in the same cycle the address is presented.
 *
 *   NEW (macro): the macro's read is **synchronous, one-cycle data
 *   access**. The address presented on `fetch_addr` during cycle N is
 *   captured at the clock edge ending cycle N; `instr_word` carries that
 *   word throughout cycle N+1. The core therefore drives `fetch_addr`
 *   with the address of the instruction that will execute *next* cycle
 *   (fetch-ahead) -- see `rtl/protocol_core.v`. This costs zero cycles
 *   per instruction, because every DR 0001 control transfer (`JMP`,
 *   `BZ`, `BNZ`) takes its target from an immediate in the instruction
 *   word, so the next address is always combinationally available in the
 *   same cycle the branch executes.
 *
 * Load and run phases stay mutually exclusive (DR 0001 latches MODE only
 * at reset release and forbids mid-run re-entry), which is exactly why a
 * **single-port** macro suffices: the memory is never read and written in
 * the same cycle, so no arbitration and no dual-port macro is needed.
 *
 * Macro pin mapping (DR 0005: "the load protocol itself is unchanged and
 * maps onto the macro directly"):
 *
 *   A_ADDR   <- wr_addr during load phase, fetch_addr during run phase
 *   A_DIN    <- the 16-bit shift register's about-to-complete word
 *   A_BM     <- 16'hFFFF (whole-word writes; no partial writes exist here)
 *   A_WEN    <- asserted for the one cycle whose ending edge commits a word
 *   A_REN    <- asserted whenever the fetch port is live (not load phase)
 *   A_MEN    <- A_WEN | A_REN (macro deactivated otherwise)
 *   A_DLY    <- 1'b1 (the datasheet's mandatory setting)
 *   A_BIST_* <- tied off, A_BIST_EN = 0
 *
 * Simulation vs. synthesis: the macro has no synthesizable RTL. Icarus
 * runs the PDK's own behavioural model, vendored at
 * `rtl/vendor/RM_IHPSG13_1P_256x16_c2_bm_bist.v` (plus its
 * `RM_IHPSG13_1P_core_behavioral_bm_bist.v` core) with provenance and
 * licence in `rtl/vendor/README.md`; Yosys/LibreLane blackbox it against
 * the PDK LEF/liberty wired up in `src/config.json`. The macro's array
 * has no reset and powers up X in simulation, exactly as the silicon
 * does -- a program must be loaded before anything is fetched, which is
 * what the load phase is for.
 *
 * Interface intent (for the core datapath, `rtl/protocol_core.v`):
 *
 *   - `fetch_addr` is the address of the instruction that will execute in
 *     the NEXT cycle (fetch-ahead, above), not the currently-executing
 *     one. The core computes it combinationally from the instruction it
 *     is executing now plus the current flags.
 *   - `run_phase` is low during reset and during the load phase. The core
 *     holds its PC at 0 and executes nothing while it is low, presents
 *     address 0 on the first cycle it is high, and executes the
 *     instruction at address 0 on the second -- DR 0005's "run-phase
 *     entry costs one additional cycle", a fixed, data-independent +1 at
 *     a single point per reset.
 *   - Top wiring (`src/tt_um_2amlogic_protocol_emulator.v`):
 *     `mode_pin` <- `ui_in[7]`, `serial_in` <- `ui_in[0]`. All other pins
 *     are undisturbed by the load mechanism, per DR 0001.
 *   - `ena` (Tiny Tapeout's power/selection line) is deliberately not a
 *     port: DR 0001's load protocol is reset-gated, not power-gated, and
 *     the template documents `ena` as "always 1 when the design is
 *     powered, so you can ignore it".
 *
 * DR 0001 defines no program-readback instruction (the ISA's 16-opcode
 * table is exactly full), so the verifiable path for "the bits landed
 * where the ISA says" is the fetch port itself -- what the core will
 * execute -- exercised by `verification/test_program_memory.py`.
 *
 * ---------------------------------------------------------------------
 * DR 0012: RUN-PHASE PROGRAM-MEMORY ACCESS AND PM_CRC (issue #135)
 * ---------------------------------------------------------------------
 *
 * `spec/decision-records/0012-control-space-and-runtime-pin-direction.md`
 * makes program memory reachable from firmware through the core's control
 * space (`WCTL PM_DATA_LO` writes, `RCTL PM_DATA_HI` reads). The macro is
 * still single-port, so a run-phase data access *takes the port* for one
 * cycle: when the core raises `pm_we` or `pm_re` it presents `pm_addr` to
 * the macro instead of `fetch_addr`, and the core stalls fetch for exactly
 * that one cycle (see `rtl/protocol_core.v`, CONTROL SPACE). `pm_re` puts
 * PM[pm_addr] on `instr_word` the next cycle -- the core consumes it as
 * data there, not as an instruction. The load phase and the run phase are
 * still mutually exclusive, so the port has at most one requester per
 * cycle: the loader in load phase, the core in run phase.
 *
 *   A_ADDR <- wr_addr (load) / pm_addr (pm_we | pm_re) / fetch_addr
 *   A_DIN  <- load_word (load) / pm_wdata (run)
 *   A_WEN  <- a serial-load commit, or pm_we
 *   A_REN  <- run phase and not a write cycle
 *
 * `pm_crc` is DR 0012's PM_CRC: CRC-16/XMODEM (poly 0x1021, init 0x0000,
 * no reflection, no final XOR) over every word committed to the macro
 * since reset or since the last `pm_crc_clr`, **by either path** -- the
 * serial load's commits and the core's `PM_DATA_LO` commits update the same
 * register, through the same `mem_wen`/`mem_din` the macro itself sees, so
 * no commit can reach the array without reaching the CRC. Each word is
 * fed MSB first (high byte, then low byte), i.e. the CRC of the image as a
 * big-endian byte string -- `binascii.crc_hqx(bytes, 0)` on the host side
 * (DR 0013's UART frame is big-endian too). This module only keeps the
 * register; exposing it on `uo_out` during load is issue #137.
 *
 * `serial_loaded` is DR 0012's `BOOT_STATUS[0]`: set when a load phase
 * ends (MODE dropped), cleared only by reset.
 */

`default_nettype none

module protocol_program_memory (
    input  wire        clk,         // clock
    input  wire        rst_n,       // reset_n - low to reset; mode is sampled at the first post-release edge
    input  wire        mode_pin,    // ui_in[7] - MODE: high at reset release enters load phase; during load, high = shifting, low = enter run phase
    input  wire        serial_in,   // ui_in[0] - serial program bit, sampled MSB-first during load phase
    input  wire [7:0]  fetch_addr,  // address of the instruction to execute NEXT cycle (fetch-ahead, DR 0005)
    output wire [15:0] instr_word,  // the word read at the address presented one cycle earlier
    output wire        run_phase,   // high once the load phase has ended (or was never entered)
    // DR 0012 run-phase data access (from protocol_core's control space).
    input  wire        pm_we,       // commit pm_wdata to PM[pm_addr] this cycle (WCTL PM_DATA_LO)
    input  wire        pm_re,       // read PM[pm_addr] this cycle instead of fetching (RCTL PM_DATA_HI)
    input  wire [7:0]  pm_addr,     // PM_ADDR
    input  wire [15:0] pm_wdata,    // word to commit
    input  wire        pm_crc_clr,  // clear pm_crc this cycle (WCTL PM_CRC_LO / PM_CRC_HI)
    output reg  [15:0] pm_crc,      // PM_CRC: CRC-16/XMODEM over every committed word
    output reg         serial_loaded // BOOT_STATUS[0]: a serial load completed since reset
);

  // One CRC-16/XMODEM step over a whole 16-bit word, MSB first (high byte
  // then low byte, the order binascii.crc_hqx sees a big-endian image in).
  function [15:0] crc16_word;
    input [15:0] crc_in;
    input [15:0] data;
    integer i;
    reg [15:0] c;
    begin
      c = crc_in;
      for (i = 15; i >= 0; i = i - 1) begin
        c = {c[14:0], 1'b0} ^ ((c[15] ^ data[i]) ? 16'h1021 : 16'h0000);
      end
      crc16_word = c;
    end
  endfunction

  // Load-phase state.
  reg        started;      // has the post-reset mode-sampling edge happened?
  reg        load_active;  // 1 while in the load phase
  reg        run_phase_r;  // 1 in run phase (normal fetch/execute)
  reg [15:0] shift_reg;    // MSB-first bit accumulator
  reg [3:0]  bit_cnt;      // 0..15 within the current word
  reg [7:0]  wr_addr;      // next program word to be written, 0..255
  reg        full;         // all 256 words loaded: saturate, never wrap

  assign run_phase = run_phase_r;

  // ------------------------------------------------------------------
  // Macro port drive (combinational: the macro registers every input on
  // the same posedge clk this module's own state advances on).
  // ------------------------------------------------------------------

  // The word that completes on THIS edge: 15 already-shifted bits plus
  // the bit presented now. This is the same expression the flip-flop
  // implementation wrote into `mem[wr_addr]`, so the
  // commit-on-16th-bit-edge contract is bit-for-bit the one
  // `verification/test_program_memory.py` pins.
  wire [15:0] load_word = {shift_reg[14:0], serial_in};

  // A commit cycle: in the load phase, with MODE still high (a MODE drop
  // on this edge exits instead of shifting), on the 16th bit of a word,
  // and not yet saturated.
  wire        load_wen  = load_active && mode_pin && (bit_cnt == 4'd15) && !full;

  // A run-phase commit from the core (DR 0012 WCTL PM_DATA_LO). Gated on
  // run_phase so nothing the core does outside run phase can write.
  wire        run_wen   = run_phase_r && pm_we;
  wire        mem_wen   = load_wen || run_wen;

  // The fetch port is live whenever the load phase is not. That includes
  // the single pre-sampling cycle after reset release (harmless: the
  // core holds address 0 and executes nothing until run_phase rises). A
  // run-phase write cycle reads nothing (the core ignores instr_word in
  // the stall cycle that follows); a PM read (pm_re) reads pm_addr.
  wire        mem_ren   = !load_active && !run_wen;

  wire        mem_men   = mem_wen || mem_ren;
  wire [7:0]  mem_addr  = load_active          ? wr_addr :
                          (run_wen || pm_re)   ? pm_addr :
                                                 fetch_addr;
  wire [15:0] mem_din   = load_active ? load_word : pm_wdata;

  RM_IHPSG13_1P_256x16_c2_bm_bist u_sram (
      .A_CLK      (clk),
      .A_MEN      (mem_men),
      .A_WEN      (mem_wen),
      .A_REN      (mem_ren),
      .A_ADDR     (mem_addr),
      .A_DIN      (mem_din),
      .A_DLY      (1'b1),          // datasheet's mandatory setting (DR 0005)
      .A_DOUT     (instr_word),
      .A_BM       (16'hFFFF),      // whole-word writes only
      // BIST port tied off: this design never uses it (DR 0005).
      .A_BIST_CLK (1'b0),
      .A_BIST_EN  (1'b0),
      .A_BIST_MEN (1'b0),
      .A_BIST_WEN (1'b0),
      .A_BIST_REN (1'b0),
      .A_BIST_ADDR(8'h00),
      .A_BIST_DIN (16'h0000),
      .A_BIST_BM  (16'h0000)
  );

  // ------------------------------------------------------------------
  // PM_CRC and BOOT_STATUS[0] (DR 0012). The CRC advances on exactly the
  // macro's own write strobe and data, so it covers every commit by any
  // path. A commit and a clear cannot coincide (a clear is a WCTL in run
  // phase, a commit there is a different WCTL; load-phase commits happen
  // while the core executes nothing), but if they did the commit would
  // win, so no committed word ever escapes the CRC.
  // ------------------------------------------------------------------
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pm_crc        <= 16'h0000;
      serial_loaded <= 1'b0;
    end else begin
      if (mem_wen) begin
        pm_crc <= crc16_word(pm_crc, mem_din);
      end else if (pm_crc_clr) begin
        pm_crc <= 16'h0000;
      end
      if (load_active && !mode_pin) begin
        serial_loaded <= 1'b1;  // the load phase ends on this edge
      end
    end
  end

  // ------------------------------------------------------------------
  // Load-phase sequencer. Unchanged from the flip-flop implementation
  // except that the word commit is now the macro's own synchronous
  // write, driven by the combinational `mem_*` signals above rather than
  // by an array assignment in this block.
  // ------------------------------------------------------------------

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
          shift_reg <= load_word;
          if (bit_cnt == 4'd15) begin
            // Commit-on-16th-bit-edge: this edge shifts the final bit AND
            // writes the assembled word (through `mem_wen` above), so a
            // host can drop MODE on the very next cycle without losing
            // the word.
            if (!full) begin
              if (wr_addr == 8'd255) begin
                full <= 1'b1;
              end else begin
                wr_addr <= wr_addr + 8'd1;
              end
            end
            // After saturation, further groups keep shifting (harmless)
            // but never commit -- `mem_wen` gates on `!full`.
            bit_cnt <= 4'd0;
          end else begin
            bit_cnt <= bit_cnt + 4'd1;
          end
        end
      end
      // In run phase there is nothing to do here: MODE is not sampled
      // again (no re-entry without a rst_n pulse with MODE high). Program
      // memory is data-addressable only through the core's DR 0012
      // control space (pm_we / pm_re above), never through this sequencer.
    end
  end

  // List unused inputs to prevent warnings (none today: every port is
  // consumed by the logic above).

endmodule

`default_nettype wire
