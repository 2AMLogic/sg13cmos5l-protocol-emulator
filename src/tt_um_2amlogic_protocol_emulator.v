/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top for the protocol-emulator ASIC: the ISA's core
 * datapath (`rtl/protocol_core.v`, issue #18) wired to its program
 * memory (`rtl/protocol_program_memory.v`, issue #19), per
 * `spec/decision-records/0001-isa.md` with the fetch-ahead amendment of
 * `spec/decision-records/0005-program-memory-implementation.md`.
 *
 * This replaces the harness-bootstrap stub (issue #2): the pin budget,
 * clock and reset wiring are unchanged (they are fixed by the Tiny
 * Tapeout template), but `ui_in` is no longer registered onto `uo_out`.
 * What drives `uo_out`/`uio_out` now is firmware -- the program loaded
 * over the serial load-phase protocol, executing on the core. Per
 * `CLAUDE.md`, "the ISA is the product": there is deliberately no
 * fixed-function UART/SPI/I2C peripheral here, only the pin-timing
 * engine those protocols are firmware for.
 *
 * Wiring (DR 0001 section "Program memory sizing and loading" and
 * `rtl/protocol_program_memory.v`'s "Interface intent"):
 *
 *   - `ui_in[7]` (MODE) and `ui_in[0]` (serial data) feed the program
 *     memory's load-phase port. All other pins are undisturbed by the
 *     load mechanism; after reset release with MODE low (or once MODE
 *     drops after a load), `ui_in` reads as an ordinary input port
 *     (ISA port 00) -- MODE is latched only at reset release, never
 *     sampled mid-run.
 *   - The core drives the program memory's address port with the
 *     *fetch-ahead* address (the instruction that executes next cycle),
 *     and the memory's registered output drives the core's decoder --
 *     DR 0005's amended fetch stage. That is the only wiring difference
 *     from the pre-DR-0005 design; the nets are the same three.
 *   - `uo_out` / `uio_out` come from the core's registered pin-port
 *     outputs (ISA ports 10 / 11; new values visible exactly one cycle
 *     after the retiring `OUT`). `uio_in` / `ui_in` feed the core's
 *     input ports (ISA ports 01 / 00).
 *   - `uio_oe` is driven at run time by firmware, per
 *     `spec/decision-records/0012-control-space-and-runtime-pin-direction.md`
 *     (issue #135): the core's control registers `UIO_DIR` and `UIO_OD`
 *     select each pin's mode, and the pin-mode logic at the bottom of
 *     this file turns them into `uio_oe` --
 *       UIO_OD[n] set   -> open-drain: uio_oe[n] = ~uio_out[n] (drive low
 *                          on a 0, release on a 1; uio_out[n] is 0 when
 *                          driving, so the pad only ever pulls low)
 *       else UIO_DIR[n] -> push-pull:  uio_oe[n] = 1
 *       else            -> input:      uio_oe[n] = 0
 *     Both registers reset to 0, so after `rst_n` every bidirectional pin
 *     is an input until a program configures it (`WCTL UIO_DIR` /
 *     `WCTL UIO_OD`). This supersedes the synthesis-time direction of DR
 *     0001 "Consequences" and the synthesis-time open-drain mask DR 0008
 *     proposed, which was never built. `uio_in` is always readable.
 *   - The core's program-memory access port (`pm_*`, DR 0012) and the
 *     program memory's `pm_crc` / `serial_loaded` are wired straight
 *     across.
 *   - Load-phase CRC readout (DR 0013 layer 1, issue #137): until the run
 *     phase begins, `uo_out` carries the running `PM_CRC` instead of the
 *     core's port-10 register -- the low byte when `ui_in[1]` is 0, the
 *     high byte when it is 1. A host reads both bytes before it drops
 *     MODE and runs the image only if they match its own CRC. See the
 *     mux at the bottom of this file. The load protocol itself is
 *     untouched: this reads state and feeds nothing back.
 *   - `ena` is unused on purpose: the template documents it as "always
 *     1 when the design is powered, so you can ignore it", and DR
 *     0001's load protocol is reset-gated, not power-gated.
 *
 * This file is this design's one and only top-level RTL source (the
 * Tiny Tapeout template fixes the top at `src/<file>.v`, per
 * `info.yaml`'s `source_files`); the modules it instantiates live under
 * `rtl/` and reach this flow through symlinks in `src/`, so the
 * template's "sources must be in ./src" rule and this repo's
 * one-copy-under-`rtl/` rule (see `rtl/README.md`) both hold without a
 * second copy of anything. This program's own klt-driven flow
 * (`flow/synthesize-protocol-emulator.json`) points at these same
 * files, so the two flows can never disagree on *what* they
 * synthesized -- only, potentially, on the result.
 */

`default_nettype none

module tt_um_2amlogic_protocol_emulator (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire [15:0] instr_word;
  wire [7:0]  fetch_addr;
  wire        run_phase;

  // DR 0012 control space: pin mode, and the run-phase program-memory
  // access between the core and the program memory.
  wire [7:0]  uio_dir;
  wire [7:0]  uio_od;
  wire        pm_we;
  wire        pm_re;
  wire [7:0]  pm_addr;
  wire [15:0] pm_wdata;
  wire        pm_crc_clr;
  wire [15:0] pm_crc;
  wire        serial_loaded;
  wire [7:0]  core_uo_out;  // the core's port-10 register (run-phase uo_out)

  // Program memory + serial load-phase logic (issue #19, DR 0001
  // "Program memory sizing and loading"), backed by the
  // RM_IHPSG13_1P_256x16_c2_bm_bist SRAM macro (DR 0005).
  protocol_program_memory u_prog_mem (
      .clk       (clk),
      .rst_n     (rst_n),
      .mode_pin  (ui_in[7]),
      .serial_in (ui_in[0]),
      .fetch_addr(fetch_addr),
      .instr_word(instr_word),
      .run_phase (run_phase),
      .pm_we        (pm_we),
      .pm_re        (pm_re),
      .pm_addr      (pm_addr),
      .pm_wdata     (pm_wdata),
      .pm_crc_clr   (pm_crc_clr),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  // Core datapath (issue #18, DR 0001 "Timing model" / "Register and
  // pin model" / "Encoding", DR 0005 fetch-ahead).
  protocol_core u_core (
      .clk         (clk),
      .rst_n       (rst_n),
      .run_phase   (run_phase),
      .instr_word  (instr_word),
      .fetch_addr  (fetch_addr),
      .port_ui_in  (ui_in),
      .port_uio_in (uio_in),
      .port_uo_out (core_uo_out),
      .port_uio_out(uio_out),
      .uio_dir      (uio_dir),
      .uio_od       (uio_od),
      .pm_we        (pm_we),
      .pm_re        (pm_re),
      .pm_addr      (pm_addr),
      .pm_wdata     (pm_wdata),
      .pm_crc_clr   (pm_crc_clr),
      .pm_crc       (pm_crc),
      .serial_loaded(serial_loaded)
  );

  // Pin-mode logic (DR 0012 "Pin mode, per uio[n]"): open-drain wins,
  // then push-pull, else input. With both registers at their reset value
  // of 0 this is 8'h00 -- every bidirectional pin an input.
  assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);

  // Load-phase CRC readout (DR 0013 layer 1, issue #137). `run_phase` is
  // low in exactly three situations, and PM_CRC is the right thing to show
  // in each:
  //   - reset held, and the one mode-sampling cycle after its release:
  //     PM_CRC is at its reset value 16'h0000, so uo_out is 8'h00 -- what
  //     the core's own reset value put there before this mux existed;
  //   - the load phase (MODE was high at reset release and has not dropped
  //     yet): PM_CRC is the CRC-16/XMODEM of the words committed so far.
  // Once `run_phase` rises it never falls without a reset, so from then on
  // uo_out is the core's register alone and `ui_in[1]` is an ordinary input
  // again. The byte select is combinational from `ui_in[1]`: the host can
  // read both bytes without a clock edge in between. PM_CRC only changes on
  // the edge that commits a word (every 16th load-phase edge), so it is
  // stable for the 15 edges after a commit.
  assign uo_out = run_phase ? core_uo_out :
                  ui_in[1]  ? pm_crc[15:8] :
                              pm_crc[7:0];

  // List unused inputs to prevent warnings.
  wire _unused = &{ena, 1'b0};

endmodule

`default_nettype wire
