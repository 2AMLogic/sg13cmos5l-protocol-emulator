#!/usr/bin/env python3
"""Self-test for `verification/reset_coverage.py` (issue #131).

The reset-coverage check is only evidence if it can fail. Each way a state
element can escape `rst_n` gets a synthetic netlist here, built against a
tiny cell library written in the same style as the PDK's functional models
(a sequential UDP for flops, one `buf`/`not` primitive for buffers and
inverters, `buf (X, 1'b1)` for a tie). No PDK and no simulator needed.

Usage:
    python3 verification/test_reset_coverage.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import reset_coverage as rc  # noqa: E402

LIBRARY = """
module lib_dfrbpq_1 (Q, CLK, D, RESET_B);
	output Q;
	input CLK, D, RESET_B;
	reg notifier;
	// Function
	wire int_fwire_IQ, int_fwire_r, xcr_0;
	not (int_fwire_r, RESET_B);
	ihp_dff_r (int_fwire_IQ, notifier, CLK, D, int_fwire_r, xcr_0);
	buf (Q, int_fwire_IQ);
	specify
		(posedge CLK => (Q : D)) = (0.0,0.0);
	endspecify
endmodule

module lib_dfxtp_1 (Q, CLK, D);
	output Q;
	input CLK, D;
	reg notifier;
	// Function
	wire int_fwire_IQ;
	ihp_dff (int_fwire_IQ, notifier, CLK, D, 1'b0);
	buf (Q, int_fwire_IQ);
endmodule

module lib_buf_1 (X, A);
	output X;
	input A;
	// Function
	buf (X, A);
endmodule

module lib_inv_1 (Y, A);
	output Y;
	input A;
	// Function
	not (Y, A);
endmodule

module lib_and2_1 (X, A, B);
	output X;
	input A, B;
	// Function
	and (X, A, B);
endmodule

module lib_tiehi (L_HI);
	output L_HI;
	// Function
	buf (L_HI, 1'b1);
endmodule
"""


def netlist(body: str) -> str:
    return f"""module top (clk, rst_n, en, out);
 input clk;
 input rst_n;
 input en;
 output out;
 wire n1;
 wire n2;
 wire n3;
{body}
endmodule
"""


GOOD = """
 lib_buf_1 rb0 (.A(rst_n), .X(n1));
 lib_dfrbpq_1 _10_ (.RESET_B(n1), .D(en), .Q(\\u_core.pc[0] ), .CLK(clk));
 lib_inv_1 i0 (.A(rst_n), .Y(n2));
 lib_inv_1 i1 (.A(n2), .Y(n3));
 lib_dfrbpq_1 _11_ (.RESET_B(n3), .D(en), .Q(\\u_core.pc[1] ), .CLK(clk));
 lib_dfrbpq_1 _12_ (.RESET_B(rst_n), .D(en), .Q(halted), .CLK(clk));
"""


def classify(body: str) -> dict:
    cells = rc.parse_cell_library(LIBRARY)
    return {e["element"]: e for e in rc.classify(rc.parse_netlist(netlist(body)), cells)}


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def library_kinds():
    cells = rc.parse_cell_library(LIBRARY)
    kinds = {name: c["kind"] for name, c in cells.items()}
    assert kinds == {"lib_dfrbpq_1": "seq", "lib_dfxtp_1": "seq", "lib_buf_1": "buf",
                     "lib_inv_1": "inv", "lib_and2_1": "comb", "lib_tiehi": "tie1"}, kinds


@case
def buffered_and_double_inverted_reset_counts():
    els = classify(GOOD)
    assert set(els) == {"u_core.pc[0]", "u_core.pc[1]", "halted"}, set(els)
    assert all(e["reset"] and e["reset_value"] == 0 for e in els.values()), els


@case
def single_inversion_is_not_a_reset():
    els = classify(GOOD + " lib_inv_1 i2 (.A(rst_n), .Y(n1x));\n"
                   " lib_dfrbpq_1 _13_ (.RESET_B(n1x), .D(en), .Q(bad), .CLK(clk));\n")
    assert not els["bad"]["reset"], els["bad"]


@case
def tied_high_reset_is_not_a_reset():
    els = classify(GOOD + " lib_dfrbpq_1 _13_ (.RESET_B(1'b1), .D(en), .Q(bad), .CLK(clk));\n")
    assert not els["bad"]["reset"] and "const1" in els["bad"]["why"], els["bad"]
    els = classify(GOOD + " lib_tiehi t0 (.L_HI(th));\n"
                   " lib_dfrbpq_1 _13_ (.RESET_B(th), .D(en), .Q(bad), .CLK(clk));\n")
    assert not els["bad"]["reset"], els["bad"]


@case
def gated_reset_is_not_from_rst_n_alone():
    els = classify(GOOD + " lib_and2_1 g0 (.A(rst_n), .B(en), .X(gr));\n"
                   " lib_dfrbpq_1 _13_ (.RESET_B(gr), .D(en), .Q(bad), .CLK(clk));\n")
    assert not els["bad"]["reset"] and "logic" in els["bad"]["why"], els["bad"]


@case
def flop_without_reset_pin_and_macro_are_listed():
    els = classify(GOOD + " lib_dfxtp_1 _13_ (.D(en), .Q(\\u_core.regs[2] ), .CLK(clk));\n"
                   " SOME_MACRO \\u_mem.u_sram  (.CLK(clk), .D({en, en}));\n")
    assert not els["u_core.regs[2]"]["reset"], els
    assert els["u_mem.u_sram"]["kind"] == "macro" and not els["u_mem.u_sram"]["reset"], els


@case
def check_unjustified_stale_and_bus_pattern():
    els = list(classify(GOOD + " lib_dfxtp_1 _13_ (.D(en), .Q(\\u_core.regs[2] ), .CLK(clk));\n"
                        " lib_dfxtp_1 _14_ (.D(en), .Q(\\u_core.regs[3] ), .CLK(clk));\n").values())
    errors, unjustified, _ = rc.check(els, [])
    assert sorted(e["element"] for e in unjustified) == ["u_core.regs[2]", "u_core.regs[3]"], errors
    errors, unjustified, covered = rc.check(els, [{"element": "u_core.regs[*]", "justification": "x"}])
    assert not errors and covered["u_core.regs[*]"] == ["u_core.regs[2]", "u_core.regs[3]"], errors
    errors, _, _ = rc.check(els, [{"element": "u_core.regs[*]", "justification": "x"},
                                  {"element": "u_core.pc[0]", "justification": "x"}])
    assert len(errors) == 1 and "STALE" in errors[0], errors
    errors, _, _ = rc.check(els, [{"element": "u_core.regs[*]", "justification": " "}])
    assert any("empty `justification`" in e for e in errors), errors


@case
def cli_exit_codes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "lib.v").write_text(LIBRARY)
        (tmp / "good.v").write_text(netlist(GOOD))
        (tmp / "bad.v").write_text(netlist(GOOD + " lib_dfxtp_1 _13_ (.D(en), .Q(q), .CLK(clk));\n"))
        (tmp / "j.json").write_text(json.dumps({"justifications": []}))
        def run(nl):
            return subprocess.run([sys.executable, str(SCRIPT_DIR / "reset_coverage.py"),
                                   "--netlist", str(tmp / nl), "--justifications", str(tmp / "j.json"),
                                   "--stdcell-model", str(tmp / "lib.v")],
                                  capture_output=True, text=True).returncode
        assert run("good.v") == 0
        assert run("bad.v") == 1
        assert run("missing.v") == 2


def main() -> int:
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
    print(f"{len(CASES) - failed}/{len(CASES)} cases as specified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
