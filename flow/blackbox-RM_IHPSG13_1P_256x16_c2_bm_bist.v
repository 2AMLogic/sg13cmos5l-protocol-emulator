/*
 * Copyright (c) 2026 2AMLogic
 * SPDX-License-Identifier: Apache-2.0
 *
 * Yosys blackbox declaration for the program-memory SRAM macro
 * (`RM_IHPSG13_1P_256x16_c2_bm_bist`, adopted by
 * `spec/decision-records/0005-program-memory-implementation.md`).
 *
 * WHY THIS FILE EXISTS -- and why it is under `flow/`, not `rtl/`:
 *
 * The LibreLane flow of record does not need it. `tt-support-tools`
 * merges this repo's `src/config.json`, whose `MACROS` / `EXTRA_LEFS` /
 * `EXTRA_LIBS` / `EXTRA_GDS_FILES` entries hand LibreLane the macro's
 * LEF/liberty/GDS, and LibreLane's Yosys step reads the liberty with
 * `-lib`, which creates the blackbox itself.
 *
 * This repo's *other* flow -- the `klt`/Yosys/OpenROAD iteration flow of
 * DR 0002 -- has no equivalent. `klt synthesize`'s request schema has no
 * field for a hard macro (no `macros`, `extra_libs` or `blackbox`
 * entry), so Yosys sees an undeclared module and aborts:
 *
 *     ERROR: Module `\RM_IHPSG13_1P_256x16_c2_bm_bist' referenced in
 *     module `\protocol_program_memory' in cell `\u_sram' is not part
 *     of the design.
 *
 * That is exactly the tool gap DR 0005 anticipated in its open item 4
 * ("a klt-side place-and-route flow that handles a hard macro against
 * this PDK ... if that surfaces a tool gap, it is a
 * 2AMLogic/klayout-tools issue under CLAUDE.md's friction protocol").
 * It is filed upstream; this file is the interim workaround, listed in
 * `flow/synthesize-*.json`'s `sources` so the klt leg can synthesize the
 * surrounding logic. **Retire it when `klt synthesize` grows a macro /
 * liberty-blackbox input**, and do not add it to `info.yaml`'s
 * `source_files` -- LibreLane would then see two competing declarations
 * of the same cell.
 *
 * Port list and widths are transcribed from the PDK's own behavioural
 * model (`rtl/vendor/RM_IHPSG13_1P_256x16_c2_bm_bist.v`, whose provenance
 * is in `rtl/vendor/README.md`); the `(* blackbox *)` attribute tells
 * Yosys to keep the instance and never look inside it. There is
 * deliberately no body: a body would be synthesized, and synthesizing
 * the behavioural model is the 4,096-flip-flop implementation DR 0005
 * measured as unplaceable and replaced.
 *
 * Consequence for every number the klt leg reports with this file in the
 * source list: the macro contributes **no cells and no area** to that
 * flow's totals. Its 28,127.104 um^2 (LEF SIZE, DR 0005 Finding 1) must
 * be added separately when comparing against a tile budget, and any
 * record citing a klt-flow cell area for this design has to say so.
 */

`default_nettype none

(* blackbox *)
module RM_IHPSG13_1P_256x16_c2_bm_bist (
    input  wire        A_CLK,
    input  wire        A_MEN,
    input  wire        A_WEN,
    input  wire        A_REN,
    input  wire [7:0]  A_ADDR,
    input  wire [15:0] A_DIN,
    input  wire        A_DLY,
    output wire [15:0] A_DOUT,
    input  wire [15:0] A_BM,
    input  wire        A_BIST_CLK,
    input  wire        A_BIST_EN,
    input  wire        A_BIST_MEN,
    input  wire        A_BIST_WEN,
    input  wire        A_BIST_REN,
    input  wire [7:0]  A_BIST_ADDR,
    input  wire [15:0] A_BIST_DIN,
    input  wire [15:0] A_BIST_BM
);
endmodule

`default_nettype wire
