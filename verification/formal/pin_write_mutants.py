#!/usr/bin/env python3
"""Write fault-injected scratch copies of rtl/protocol_core.v for the
`pin_write_latency` negative controls (issue #116).

The shipped RTL is never edited and carries no fault switch: each mutant is
a text substitution applied to a COPY. Every substitution must match its
anchor exactly once in the source; if any anchor is missing or ambiguous
(e.g. after a future RTL edit) this script fails loudly rather than emitting
a copy identical to the original, so a negative control can never silently
become a second positive run.

Usage: pin_write_mutants.py <protocol_core.v> <out-dir> [name ...]
Writes <out-dir>/protocol_core_<name>.v for each mutant (all by default) and
prints the names it wrote, one per line.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Anchors (verbatim lines/fragments of rtl/protocol_core.v).
OUT_UO_WRITE = "PORT_UO_OUT:  port_uo_out  <= rd_val;"
OUT_UIO_WRITE = "PORT_UIO_OUT: port_uio_out <= rd_val;"
UO_DECL = "output reg  [7:0]  port_uo_out,"
UIO_DECL = "output reg  [7:0]  port_uio_out"
UO_RESET = "port_uo_out  <= 8'h00;"
UIO_RESET = "port_uio_out <= 8'h00;"
RO_DEFAULT = "default: ;  // OUT to a read-only port"
EXEC_GATE = "if (fetch_valid && !halted) begin"
INSERT_AT = "  assign fetch_addr = next_addr;\n"

# The core's own "an OUT to port P executes this cycle" condition, re-stated
# for the mutants that need a second write path (only used inside mutants).
EXEC_OUT = "run_phase && fetch_valid && !halted && !waiting && opcode == OP_OUT"

MUTANTS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    # --- wrong destination / wrong value ----------------------------------
    "wrong_destination": (
        "OUT to port 10 writes port 11 instead",
        [(OUT_UO_WRITE, "PORT_UO_OUT:  port_uio_out <= rd_val;")],
    ),
    "wrong_value": (
        "OUT to port 11 writes the register named by the PORT field (rs_val) "
        "instead of the source register",
        [(OUT_UIO_WRITE, "PORT_UIO_OUT: port_uio_out <= rs_val;")],
    ),
    "readonly_port_writes": (
        "OUT to a read-only port (00/01) writes port 10",
        [(RO_DEFAULT, "default: port_uo_out <= rd_val;  // MUTANT: OUT to a read-only port")],
    ),
    # --- wrong update timing --------------------------------------------
    "late_one_cycle": (
        "port 10 gets an extra register stage: the value appears one cycle late",
        [
            (UO_DECL, "output wire [7:0]  port_uo_out,"),
            (UO_RESET, "port_uo_out_r <= 8'h00;"),
            (OUT_UO_WRITE, "PORT_UO_OUT:  port_uo_out_r <= rd_val;"),
            (
                INSERT_AT,
                "  reg [7:0] port_uo_out_r;  // MUTANT\n"
                "  reg [7:0] port_uo_out_d;  // MUTANT: extra output stage\n"
                "  always @(posedge clk or negedge rst_n)\n"
                "    if (!rst_n) port_uo_out_d <= 8'h00;\n"
                "    else        port_uo_out_d <= port_uo_out_r;\n"
                "  assign port_uo_out = port_uo_out_d;\n" + INSERT_AT,
            ),
        ],
    ),
    "comb_early_visibility": (
        "port 11 is bypassed combinationally while its OUT executes: the value "
        "is visible in cycle N instead of N+1",
        [
            (UIO_DECL, "output wire [7:0]  port_uio_out"),
            (UIO_RESET, "port_uio_out_r <= 8'h00;"),
            (OUT_UIO_WRITE, "PORT_UIO_OUT: port_uio_out_r <= rd_val;"),
            (
                INSERT_AT,
                "  reg [7:0] port_uio_out_r;  // MUTANT\n"
                f"  assign port_uio_out = ({EXEC_OUT} && rs == PORT_UIO_OUT) ? rd_val : port_uio_out_r;\n"
                + INSERT_AT,
            ),
        ],
    ),
    "executes_in_priming_cycle": (
        "the execute gate ignores fetch_valid, so the word presented in DR "
        "0005's priming cycle executes one cycle early (eligibility fault)",
        [(EXEC_GATE, "if (!halted) begin  // MUTANT: fetch_valid dropped")],
    ),
    "negedge_half_cycle_early": (
        "port 10 is a register clocked on the FALLING edge in the middle of "
        "the OUT's own cycle: registered, but half a cycle early",
        [
            (UO_DECL, "output wire [7:0]  port_uo_out,"),
            (UO_RESET, "port_uo_out_r <= 8'h00;"),
            (OUT_UO_WRITE, "PORT_UO_OUT:  port_uo_out_r <= rd_val;"),
            (
                INSERT_AT,
                "  reg [7:0] port_uo_out_r;  // MUTANT (no longer drives the pin)\n"
                "  reg [7:0] port_uo_out_n;  // MUTANT: falling-edge output register\n"
                "  always @(negedge clk or negedge rst_n)\n"
                "    if (!rst_n) port_uo_out_n <= 8'h00;\n"
                f"    else if ({EXEC_OUT} && rs == PORT_UO_OUT) port_uo_out_n <= rd_val;\n"
                "  assign port_uo_out = port_uo_out_n;\n" + INSERT_AT,
            ),
        ],
    ),
}


def mutate(src: str, subs: list[tuple[str, str]], name: str) -> str:
    out = src
    for old, new in subs:
        n = out.count(old)
        if n != 1:
            raise SystemExit(f"ERROR: mutant {name}: anchor {old!r} occurs {n} times (need exactly 1)")
        out = out.replace(old, new)
    if out == src:
        raise SystemExit(f"ERROR: mutant {name}: substitution left the core unchanged")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    core = Path(argv[1]).read_text()
    out_dir = Path(argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    names = argv[3:] or list(MUTANTS)
    for name in names:
        if name not in MUTANTS:
            raise SystemExit(f"ERROR: unknown mutant {name!r}")
        _, subs = MUTANTS[name]
        (out_dir / f"protocol_core_{name}.v").write_text(mutate(core, subs, name))
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
