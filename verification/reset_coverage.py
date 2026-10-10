#!/usr/bin/env python3
"""Reset-coverage listing for a gate-level netlist (issue #131, target-spec
row 14 (a), `spec/verification-plan.md` section 8 "Reset-coverage listing").

Question answered: which state elements of the netlist does `rst_n` *not*
put into a known state on its own? Every such element must be listed in a
committed justification file with the reason it is allowed to stay that
way. An element that is not reset and not listed fails the check; so does a
justification that no longer names a non-reset element (a stale entry is a
claim about a netlist that no longer exists).

How an element is classified -- structurally, from the netlist text and the
PDK's own cell models, never from instance names:

- **Sequential standard cell**: a cell whose PDK Verilog model instantiates
  a flip-flop or latch UDP (`ihp_dff*` / `ihp_latch*`). Its asynchronous
  control pins are `RESET_B` and `SET_B` (active low).
  - `reset`: it has `RESET_B` and/or `SET_B`, and exactly one of them is
    driven by the top-level `rst_n` port through nothing but buffers and
    inverters with an even number of inversions (so `rst_n` low asserts
    it); any other async pin is tied inactive (a constant 1 through
    buffers). Its reset value is 0 for `RESET_B`, 1 for `SET_B`.
  - `not-reset`: anything else -- no async pin, async pins tied inactive,
    or driven by logic other than a buffered `rst_n` (a gated reset is not
    "from `rst_n` alone").
- **Macro**: an instance of a module that is not in the PDK standard-cell
  library (here the SRAM macro). A macro has no reset pin in this flow, so
  it is always `not-reset` and must be justified.
- Everything else (combinational cells, ties, fill/decap) holds no state.

An element is named by its output net (`Q`, else `Q_N`) with the Verilog
escape removed (`\\u_core.pc[3] ` -> `u_core.pc[3]`), or by its instance
name for a macro, so the names survive re-placement better than the
`_NNNN_` instance numbers do. A justification entry may name one element
exactly or a bus with a `[*]` suffix (`u_core.regs[*]`).

Usage:
    python3 verification/reset_coverage.py --netlist N.v \\
        --justifications verification/reset_coverage_justifications.json \\
        [--stdcell-model PDK/.../sg13cmos5l_stdcell.v] [--json OUT.json]

`--stdcell-model` defaults to `$PDK_ROOT/ihp-sg13cmos5l/libs.ref/
sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v` (PDK_ROOT defaults to
~/share/pdk). Exit 0 = every non-reset element is justified and every
justification is live; 1 = not; 2 = usage / parse error.

Zero dependencies beyond the Python 3 standard library. The cocotb bench
`verification/test_reset_power_up.py` imports `parse_netlist` and
`classify` from here, so the bench forces and observes exactly the element
list this check grades.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

RESET_PORT = "rst_n"
ASYNC_PINS = ("RESET_B", "SET_B")
SEQ_UDP_RE = re.compile(r"^\s*(ihp_dff\w*|ihp_latch\w*)\s*\(", re.M)

_MODULE_RE = re.compile(r"^module\s+(\w+)\s*\((.*?)\);(.*?)^endmodule", re.S | re.M)
_DIR_RE = re.compile(r"^\s*(input|output)\s+([^;]+);", re.M)
_PRIM_RE = re.compile(r"^\s*(buf|not)\s*\(\s*(\w+)\s*,\s*([^)\s]+)\s*\)\s*;", re.M)
_INST_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s+(\\\S+\s|[A-Za-z_]\w*)\s*\((.*?)\);", re.S | re.M
)
_PIN_RE = re.compile(r"\.(\w+)\s*\(\s*((?:\\\S+\s)|[^()]*?)\s*\)")


def norm(net: str) -> str:
    """`\\u_core.pc[3] ` -> `u_core.pc[3]`; plain names unchanged."""
    net = net.strip()
    return net[1:].strip() if net.startswith("\\") else net


def default_stdcell_model() -> Path:
    root = Path(os.environ.get("PDK_ROOT", str(Path.home() / "share" / "pdk")))
    return root / "ihp-sg13cmos5l" / "libs.ref" / "sg13cmos5l_stdcell" / "verilog" / "sg13cmos5l_stdcell.v"


def parse_cell_library(text: str) -> dict:
    """cell name -> {"kind": seq|buf|inv|tie0|tie1|comb, "outputs", "inputs"}
    from the PDK's functional Verilog models."""
    cells = {}
    for name, _ports, body in _MODULE_RE.findall(text):
        outputs, inputs = [], []
        for direction, names in _DIR_RE.findall(body):
            for pin in (p.strip() for p in names.split(",")):
                if pin:
                    (outputs if direction == "output" else inputs).append(pin)
        function = body.split("specify")[0]
        kind = "comb"
        prims = _PRIM_RE.findall(function)
        if SEQ_UDP_RE.search(function):
            kind = "seq"
        elif len(prims) == 1 and len(outputs) == 1 and prims[0][1] == outputs[0]:
            prim, _out, src = prims[0]
            if src == "1'b1" and prim == "buf":
                kind = "tie1"
            elif src == "1'b0" and prim == "buf":
                kind = "tie0"
            elif src in inputs and len(inputs) == 1:
                kind = "buf" if prim == "buf" else "inv"
        cells[name] = {"kind": kind, "outputs": outputs, "inputs": inputs}
    if not cells:
        raise ValueError("no cell models parsed from the standard-cell library")
    return cells


def _top_module_body(text: str) -> tuple[str, str]:
    match = re.search(r"^module\s+(\w+)\s*\((.*?)\);(.*?)^endmodule", text, re.S | re.M)
    if not match:
        raise ValueError("no module found in the netlist")
    return match.group(1), match.group(3)


def parse_netlist(text: str) -> dict:
    """{"top": name, "instances": [{"cell", "name", "pins": {pin: net}}]}.
    Bus connections (`{a, b}`) are kept as the raw string; only scalar pins
    matter to the reset analysis."""
    top, body = _top_module_body(text)
    instances = []
    for cell, name, conns in _INST_RE.findall(body):
        if cell in ("input", "output", "inout", "wire", "reg", "assign", "module"):
            continue
        pins = {pin: net.strip() for pin, net in _PIN_RE.findall(conns)}
        instances.append({"cell": cell, "name": norm(name), "pins": pins})
    if not instances:
        raise ValueError("no cell instances found in the netlist")
    return {"top": top, "instances": instances}


def _driver_map(netlist: dict, cells: dict) -> dict:
    drivers = {}
    for inst in netlist["instances"]:
        lib = cells.get(inst["cell"])
        if lib is None:
            continue
        for pin in lib["outputs"]:
            net = inst["pins"].get(pin)
            if net:
                drivers[norm(net)] = (inst, lib)
    return drivers


def trace_async(net: str, drivers: dict, cells: dict, limit: int = 64) -> dict:
    """Follow `net` back through buffers/inverters.
    -> {"source": "rst_n"|"const1"|"const0"|"logic", "inversions": n,
        "path": [cell names], "detail": str}"""
    inversions, path = 0, []
    current = net.strip()
    for _ in range(limit):
        if current in ("1'b1", "1'h1"):
            return {"source": "const1" if inversions % 2 == 0 else "const0",
                    "inversions": inversions, "path": path, "detail": current}
        if current in ("1'b0", "1'h0"):
            return {"source": "const0" if inversions % 2 == 0 else "const1",
                    "inversions": inversions, "path": path, "detail": current}
        name = norm(current)
        if name == RESET_PORT:
            return {"source": RESET_PORT, "inversions": inversions, "path": path, "detail": name}
        found = drivers.get(name)
        if found is None:
            return {"source": "logic", "inversions": inversions, "path": path,
                    "detail": f"undriven or port net {name}"}
        inst, lib = found
        path.append(inst["cell"])
        if lib["kind"] == "tie1":
            return {"source": "const1" if inversions % 2 == 0 else "const0",
                    "inversions": inversions, "path": path, "detail": inst["name"]}
        if lib["kind"] == "tie0":
            return {"source": "const0" if inversions % 2 == 0 else "const1",
                    "inversions": inversions, "path": path, "detail": inst["name"]}
        if lib["kind"] not in ("buf", "inv"):
            return {"source": "logic", "inversions": inversions, "path": path,
                    "detail": f"{inst['cell']} {inst['name']}"}
        if lib["kind"] == "inv":
            inversions += 1
        current = inst["pins"].get(lib["inputs"][0], "")
    return {"source": "logic", "inversions": inversions, "path": path, "detail": "buffer chain too deep"}


def classify(netlist: dict, cells: dict) -> list:
    """Every state element of the netlist with its reset classification."""
    drivers = _driver_map(netlist, cells)
    elements = []
    for inst in netlist["instances"]:
        lib = cells.get(inst["cell"])
        if lib is None:
            elements.append({
                "element": inst["name"], "kind": "macro", "cell": inst["cell"],
                "instance": inst["name"], "reset": False, "reset_value": None,
                "why": "macro: not a standard cell, no reset pin in this flow",
            })
            continue
        if lib["kind"] != "seq":
            continue
        out = inst["pins"].get("Q") or inst["pins"].get("Q_N")
        name = norm(out) if out else inst["name"]
        asyncs = {pin: trace_async(inst["pins"].get(pin, ""), drivers, cells)
                  for pin in ASYNC_PINS if pin in lib["inputs"]}
        from_reset = [p for p, t in asyncs.items()
                      if t["source"] == RESET_PORT and t["inversions"] % 2 == 0]
        others_inactive = all(t["source"] == "const1" for p, t in asyncs.items()
                              if p not in from_reset)
        is_reset = len(from_reset) == 1 and others_inactive
        if is_reset:
            pin = from_reset[0]
            value = (0 if pin == "RESET_B" else 1) if "Q" in inst["pins"] else (1 if pin == "RESET_B" else 0)
            why = f"{pin} <- {RESET_PORT} through {len(asyncs[pin]['path'])} buffer/inverter cell(s)"
        else:
            value = None
            if not asyncs:
                why = "no asynchronous reset/set pin"
            else:
                why = "; ".join(f"{p}: {t['source']} ({t['detail']})" for p, t in asyncs.items())
        elements.append({
            "element": name, "kind": "flop", "cell": inst["cell"], "instance": inst["name"],
            "reset": is_reset, "reset_value": value, "why": why,
            "reset_pins": {p: t["source"] for p, t in asyncs.items()},
        })
    return elements


def _matches(pattern: str, element: str) -> bool:
    if pattern.endswith("[*]"):
        return fnmatch.fnmatchcase(element, pattern[:-3] + "[[]*[]]")
    return pattern == element


def check(elements: list, justifications: list) -> tuple[list, list, dict]:
    """-> (errors, unjustified, {pattern: [elements it covers]})."""
    errors = []
    for entry in justifications:
        for key in ("element", "justification"):
            if not str(entry.get(key, "")).strip():
                errors.append(f"justification entry {entry!r} has an empty `{key}`")
    covered = {e["element"]: [] for e in justifications}
    non_reset = [e for e in elements if not e["reset"]]
    unjustified = []
    for element in non_reset:
        hits = [j["element"] for j in justifications if _matches(j["element"], element["element"])]
        if not hits:
            unjustified.append(element)
            errors.append(
                f"UNJUSTIFIED non-reset state element `{element['element']}` "
                f"({element['kind']}, {element['cell']} {element['instance']}): {element['why']}"
            )
        for h in hits:
            covered[h].append(element["element"])
    for pattern, hits in covered.items():
        if not hits:
            errors.append(
                f"STALE justification `{pattern}`: it names no non-reset state element of this netlist"
            )
    return errors, unjustified, covered


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--netlist", required=True, type=Path)
    ap.add_argument("--justifications", required=True, type=Path)
    ap.add_argument("--stdcell-model", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None, help="write the full listing here")
    args = ap.parse_args(argv)
    model = args.stdcell_model or default_stdcell_model()
    try:
        cells = parse_cell_library(model.read_text(encoding="utf-8"))
        netlist = parse_netlist(args.netlist.read_text(encoding="utf-8"))
        doc = json.loads(args.justifications.read_text(encoding="utf-8"))
        justifications = doc["justifications"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    elements = classify(netlist, cells)
    errors, _unjustified, covered = check(elements, justifications)
    flops = [e for e in elements if e["kind"] == "flop"]
    reset = [e for e in elements if e["reset"]]
    print(f"netlist {args.netlist} (top {netlist['top']}): {len(elements)} state element(s): "
          f"{len(flops)} flop(s), {len(elements) - len(flops)} macro(s); "
          f"{len(reset)} reset from {RESET_PORT} alone, {len(elements) - len(reset)} not")
    for e in elements:
        if not e["reset"]:
            print(f"  not reset: {e['element']} ({e['kind']}, {e['cell']}): {e['why']}")
    for pattern, hits in covered.items():
        print(f"  justified by `{pattern}`: {len(hits)} element(s)")
    if args.json:
        args.json.write_text(json.dumps({
            "netlist": str(args.netlist), "top": netlist["top"],
            "stdcell_model": str(model), "elements": elements,
            "justified": covered, "errors": errors,
        }, indent=2) + "\n", encoding="utf-8")
    for err in errors:
        print(f"FAIL: {err}", file=sys.stderr)
    if errors:
        return 1
    print("OK: every non-reset state element is justified and every justification is live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
