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
 *     across; neither reaches a pin in this revision (the load-phase CRC
 *     readout on `uo_out` is issue #137).
 *   - The boot ROM (`rtl/protocol_boot_rom.v`, generated from the committed
 *     boot image; `spec/decision-records/0013-program-loading.md` layer 2,
 *     issue #138) is read at the same fetch-ahead address as the program
 *     memory and hands the core a second instruction word, `rom_word`. The
 *     core decodes the ROM from `rst_n` release with MODE low until the boot
 *     program executes `WCTL RUN`, and program memory otherwise. While the
 *     core fetches from the ROM its `pm_fetch` is low and the program memory
 *     does not read the macro for fetch, so program memory that nothing has
 *     loaded and checked is never decoded. A serial load (MODE high at
 *     reset) never touches the ROM. The straps the boot program reads are
 *     `ui_in[6:5]`, through the ordinary `IN` path -- there is no strap
 *     hardware here.
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

  // DR 0013 layer 2 boot ROM (issue #138): the second fetch source.
  wire [15:0] rom_word;
  wire        fetch_rom;
  wire        pm_fetch;

  protocol_boot_rom u_boot_rom (
      .clk  (clk),
      .rst_n(rst_n),
      .addr (fetch_addr),
      .data (rom_word)
  );

  // Program memory + serial load-phase logic (issue #19, DR 0001
  // "Program memory sizing and loading"), backed by the
  // RM_IHPSG13_1P_256x16_c2_bm_bist SRAM macro (DR 0005).
  protocol_program_memory u_prog_mem (
      .clk       (clk),
      .rst_n     (rst_n),
      .mode_pin  (ui_in[7]),
      .serial_in (ui_in[0]),
      .fetch_addr(fetch_addr),
      .fetch_en  (pm_fetch),
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
      .rom_word    (rom_word),
      .fetch_rom   (fetch_rom),
      .pm_fetch    (pm_fetch),
      .port_ui_in  (ui_in),
      .port_uio_in (uio_in),
      .port_uo_out (uo_out),
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

  // List unused inputs to prevent warnings.
  // `fetch_rom` (BOOT_STATUS[1]) is a core output for the formal harnesses
  // and for observability; nothing at the top consumes it.
  wire _unused = &{ena, fetch_rom, 1'b0};

endmodule

`default_nettype wire
