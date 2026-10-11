#!/usr/bin/env python3
"""Drift check: docs/submission/architecture.md's ISA tables vs the assembler (issue #230).

The judge-facing architecture document (submission deliverable D2) carries
five machine-readable Markdown tables, each between
`<!-- arch-table:NAME:begin -->` and `<!-- arch-table:NAME:end -->`
markers: `ports`, `opcodes`, `shift`, `control` and `reserved`. The
document's own section "The table contract" states the cell grammar. This
checker fails (exit 1) when any of them disagrees with its sources:

  * `firmware/tools/asm.py` (frozen by DR 0017; imported read-only, never
    edited): `OPCODES` and `CTL_MNEMONICS` (every mnemonic exactly once,
    opcode, kind), `CTL_REGS` and `CTL_PORT_WRITE`/`CTL_PORT_READ` (index,
    W/R permission, per-direction cycles), `PORTS`, and the words and
    `Instruction.cycles` the assembler actually produces for representative
    operands of every form: all registers, both shift directions, every
    port, `WAIT 0` and `WAIT 255`, branch targets, every assigned control
    index in each direction, and the reserved-encoding examples with and
    without `allow_reserved`.
  * `verification/reference_models/isa.py` (the independent ISA model,
    written from DR 0001/0012/0015/0016): opcode table, `CONTROL`
    permissions and costs, `static_cost`, and -- because the assembler
    exposes no flag-effect table -- the Z/C effects of each instruction on
    representative operands (ADD carry, SUB borrow, logic leaving C, SHF
    leaving Z and filling with 0). This checks the document against the
    existing sources; it is not a new proof of the ISA.

It also fails on a missing table or column, a missing, duplicate or
unknown row, a malformed cell, an `Encoding` whose letter fields are not
exactly the operands the instruction has (a phantom field on bits the
assembler always emits as 0 would otherwise encode to the same word), a
relative link that does not resolve, and a `#fragment` link naming no
heading of the document.
Every message names the document line and row.

It never rewrites anything and sets `sys.dont_write_bytecode` before
importing the two sources. Stdlib only.

    python3 scripts/check_architecture.py [--root DIR] [--doc PATH]
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

DOC_REL = Path("docs") / "submission" / "architecture.md"
ASM_REL = Path("firmware") / "tools" / "asm.py"
ISA_REL = Path("verification") / "reference_models" / "isa.py"

TABLES = {
    "ports": ("Name", "Code", "IN", "OUT"),
    "opcodes": ("Mnemonic", "Opcode", "Kind", "Operands", "Encoding", "Cycles", "Z", "C"),
    "shift": ("Direction", "Rs[0]", "Fill", "C"),
    "control": ("k", "Name", "W", "R", "Write cycles", "Read cycles"),
    "reserved": ("Example", "Default", "With --allow-reserved"),
}

Z_RULES = ("zero", "unchanged")
C_RULES = ("carry", "borrow", "shift-out", "unchanged")
FIELD_WIDTH = {"d": 2, "s": 2, "p": 2, "r": 1, "i": 8, "k": 8}
FIELD_NAME = {"d": "Rd", "s": "Rs", "p": "port", "r": "shift direction", "i": "imm8", "k": "control index"}
LINK = re.compile(r"\]\(([^)\s]+)\)")
RESERVED_CASES = (
    "unassigned write",
    "unassigned read",
    "write to a read-only register",
    "read of a write-only register",
    "OUT to port 01",
    "IN from port 11",
)


# --- loading the sources (read-only) --------------------------------------
def load_module(path: Path, name: str):
    """Import a source file by path without writing bytecode next to it."""
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses resolve annotations via sys.modules
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = old


def load_sources(root: Path):
    asm = load_module(root / ASM_REL, "_arch_check_asm")
    isa = load_module(root / ISA_REL, "_arch_check_isa")
    return asm, isa


# --- table parsing --------------------------------------------------------
class Table:
    def __init__(self, name, header, rows, line):
        self.name = name
        self.header = header  # list of column names
        self.rows = rows      # list of (line_no, {column: cell})
        self.line = line      # line of the begin marker


def _cells(line: str):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [norm(c) for c in body.split("|")]


def norm(cell: str) -> str:
    return " ".join(cell.replace("`", "").split())


def parse_tables(text: str, errs: list) -> dict:
    lines = text.splitlines()
    tables = {}
    for name, required in TABLES.items():
        begin, end = f"<!-- arch-table:{name}:begin -->", f"<!-- arch-table:{name}:end -->"
        b = [i for i, ln in enumerate(lines) if ln.strip() == begin]
        e = [i for i, ln in enumerate(lines) if ln.strip() == end]
        if len(b) != 1 or len(e) != 1 or e[0] < b[0]:
            errs.append(
                f"table '{name}': expected exactly one `{begin}` followed by one "
                f"`{end}` (found {len(b)} begin, {len(e)} end)"
            )
            continue
        body = [(i + 1, lines[i]) for i in range(b[0] + 1, e[0]) if lines[i].strip()]
        if len(body) < 2 or not body[0][1].strip().startswith("|"):
            errs.append(f"line {b[0] + 1}: table '{name}': no Markdown table between its markers")
            continue
        header = _cells(body[0][1])
        sep = _cells(body[1][1])
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in sep) or len(sep) != len(header):
            errs.append(f"line {body[1][0]}: table '{name}': second line is not a separator row")
            continue
        missing = [c for c in required if c not in header]
        if missing:
            errs.append(
                f"line {body[0][0]}: table '{name}': missing column(s) "
                + ", ".join(f"'{c}'" for c in missing)
                + f" (header has {header})"
            )
            continue
        rows = []
        for line_no, raw in body[2:]:
            if not raw.strip().startswith("|"):
                errs.append(f"line {line_no}: table '{name}': non-table line inside the markers")
                continue
            cells = _cells(raw)
            if len(cells) != len(header):
                errs.append(
                    f"line {line_no}: table '{name}': {len(cells)} cells, header has {len(header)}"
                )
                continue
            rows.append((line_no, dict(zip(header, cells))))
        if not rows:
            errs.append(f"line {b[0] + 1}: table '{name}': no data rows")
            continue
        tables[name] = Table(name, header, rows, b[0] + 1)
    return tables


def keyed(table: Table, key: str, errs: list) -> dict:
    """Index rows by `key`, reporting duplicates. Returns {key: (line, row)}."""
    out = {}
    for line_no, row in table.rows:
        k = row[key]
        if k in out:
            errs.append(
                f"line {line_no}: table '{table.name}': duplicate row '{k}' "
                f"(first at line {out[k][0]})"
            )
            continue
        out[k] = (line_no, row)
    return out


def yes_no(value: str, where: str, col: str, errs: list):
    if value not in ("yes", "no"):
        errs.append(f"{where}: {col} '{value}' is not 'yes' or 'no'")
        return None
    return value == "yes"


def parse_int(value: str, where: str, col: str, errs: list, *, pattern=r"\d+", base=10):
    if not re.fullmatch(pattern, value):
        errs.append(f"{where}: {col} '{value}' is malformed")
        return None
    return int(value, base)


# --- the assembler side ---------------------------------------------------
def assemble_one(asm, source: str, allow_reserved: bool = False):
    """Return the single Instruction for `source`, or the AsmError text."""
    try:
        program = asm.assemble_text(source + "\n", allow_reserved=allow_reserved)
    except asm.AsmError as err:
        return None, err.message
    return program.instructions[0], None


def parse_encoding(pattern: str, where: str, errs: list):
    """'0011 dd ss 00000000' -> list of 16 chars, MSB first, or None."""
    bits = pattern.replace(" ", "")
    if len(bits) != 16 or any(ch not in "01dsprik" for ch in bits):
        errs.append(
            f"{where}: Encoding '{pattern}' is malformed (16 characters from 0 1 d s p r i k)"
        )
        return None
    for letter, width in FIELD_WIDTH.items():
        idx = [i for i, ch in enumerate(bits) if ch == letter]
        if idx and (len(idx) != width or idx != list(range(idx[0], idx[0] + width))):
            errs.append(
                f"{where}: Encoding '{pattern}': field '{letter}' must be one run of "
                f"{width} bit(s)"
            )
            return None
    return bits


def encode(bits, fields: dict) -> int:
    """Pack operand values into a documented bit pattern."""
    word = 0
    for letter in set(bits) - {"0", "1"}:
        idx = [i for i, ch in enumerate(bits) if ch == letter]
        lsb = 15 - idx[-1]
        word |= (fields.get(letter, 0) & ((1 << len(idx)) - 1)) << lsb
    for i, ch in enumerate(bits):
        if ch == "1":
            word |= 1 << (15 - i)
    return word


def parse_cycles(cell: str, where: str, errs: list):
    if re.fullmatch(r"\d+", cell):
        n = int(cell)
        return lambda f, ctl: n
    m = re.fullmatch(r"imm8 \+ (\d+)", cell)
    if m:
        n = int(m.group(1))
        return lambda f, ctl: f["i"] + n
    if cell == "control table":
        return lambda f, ctl: ctl
    errs.append(f"{where}: Cycles '{cell}' is malformed (a number, 'imm8 + N' or 'control table')")
    return None


def samples(asm, mnemonic: str, kind: str):
    """(operand text, field values, control direction or None) per form."""
    regs = range(4)
    if kind == "none":
        return [("", {}, None)]
    if kind == "ldi":
        return [(f"R{d}, {v:#04x}", {"d": d, "i": v}, None)
                for d, v in ((0, 0), (1, 0x5A), (2, 0xA5), (3, 255))]
    if kind == "rr":
        return [(f"R{d}, R{s}", {"d": d, "s": s}, None)
                for d, s in ((0, 1), (1, 3), (2, 2), (3, 0))]
    if kind == "shf":
        return [(f"R{d}, {name}", {"d": d, "r": r}, None)
                for d in regs for name, r in (("LEFT", 1), ("RIGHT", 0))]
    if kind == "in":
        return [(f"R{d}, {p}", {"d": d, "p": code}, None)
                for d in (0, 3) for p, (code, readable, _) in asm.PORTS.items() if readable]
    if kind == "out":
        return [(f"{p}, R{s}", {"s": s, "p": code}, None)
                for s in (1, 2) for p, (code, _, writable) in asm.PORTS.items() if writable]
    if kind == "wait":
        return [(str(v), {"i": v}, None) for v in (0, 1, 17, 254, 255)]
    if kind == "branch":
        return [(f"{v:#04x}", {"i": v}, None) for v in (0x00, 0x42, 0xFF)]
    if kind == "wctl":
        out = []
        for name, (k, writable, _r, _wc, _rc) in asm.CTL_REGS.items():
            if writable:
                out.append((f"{name}, R{k % 4}", {"k": k, "s": k % 4}, ("W", name)))
                out.append((f"{k:#04x}, R{(k + 1) % 4}", {"k": k, "s": (k + 1) % 4}, ("W", name)))
        return out
    if kind == "rctl":
        out = []
        for name, (k, _w, readable, _wc, _rc) in asm.CTL_REGS.items():
            if readable:
                out.append((f"R{k % 4}, {name}", {"k": k, "d": k % 4}, ("R", name)))
                out.append((f"R{(k + 3) % 4}, {k}", {"k": k, "d": (k + 3) % 4}, ("R", name)))
        return out
    return []


# --- the reference-model side (flags) ------------------------------------
def model_flags(isa, word: int, regs):
    """Run one instruction's effect in the independent model.

    Returns (writes as {kind: value}, Rd result or None)."""
    m = isa.Machine([word])
    m.regs = list(regs)
    m.z, m.c = 1, 1  # a flag the instruction does not write stays 1
    ins = isa.decode(word)
    _cost, writes, _info = isa.BY_CODE[ins.op].effect(m, ins, 0x5A, 0x3C)
    flags = {w[0]: w[1] for w in writes if w[0] in ("z", "c")}
    result = next((w[2] for w in writes if w[0] == "reg" and w[1] == ins.rd), None)
    return flags, result


FLAG_CASES = {
    "rr": [(0x80, 0x80), (0x01, 0x02), (0xFF, 0x01), (0x05, 0x05), (0x05, 0x03),
           (0x00, 0xFF), (0xF0, 0x0F), (0xAA, 0x55), (0x00, 0x00)],
    "shf": [(v, 0) for v in (0x00, 0x01, 0x80, 0x81, 0x7E, 0xFF)],
}


def expected_c(rule: str, a: int, b: int, left: bool):
    if rule == "carry":
        return (a + b) >> 8
    if rule == "borrow":
        return int(a < b)
    if rule == "shift-out":
        return (a >> 7) & 1 if left else a & 1
    return None


# --- the checks -----------------------------------------------------------
def check_ports(asm, t: Table, errs: list):
    rows = keyed(t, "Name", errs)
    for name in asm.PORTS:
        if name not in rows:
            errs.append(f"line {t.line}: table 'ports': missing row for port `{name}`")
    for name, (line_no, row) in rows.items():
        where = f"line {line_no}: table 'ports' row '{name}'"
        if name not in asm.PORTS:
            errs.append(f"{where}: unknown port (assembler PORTS has {list(asm.PORTS)})")
            continue
        code, readable, writable = asm.PORTS[name]
        c = parse_int(row["Code"], where, "Code", errs, pattern=r"[01]{2}", base=2)
        if c is not None and c != code:
            errs.append(f"{where}: Code {row['Code']} but the assembler has {code:02b}")
        for col, want in (("IN", readable), ("OUT", writable)):
            got = yes_no(row[col], where, col, errs)
            if got is not None and got != want:
                errs.append(
                    f"{where}: {col} '{row[col]}' but the assembler says "
                    f"{'yes' if want else 'no'}"
                )


def check_control(asm, isa, t: Table, errs: list) -> dict:
    """Returns {name: {"W": cycles or None, "R": cycles or None}} as documented."""
    rows = keyed(t, "Name", errs)
    documented = {}
    for name in asm.CTL_REGS:
        if name not in rows:
            errs.append(f"line {t.line}: table 'control': missing row for control register `{name}`")
    seen_k = {}
    for name, (line_no, row) in rows.items():
        where = f"line {line_no}: table 'control' row '{name}'"
        k = parse_int(row["k"], where, "k", errs, pattern=r"0x[0-9A-Fa-f]{2}", base=16)
        if k is not None:
            if k in seen_k:
                errs.append(f"{where}: index {row['k']} already used by '{seen_k[k]}'")
            seen_k[k] = name
        if name not in asm.CTL_REGS:
            errs.append(f"{where}: unknown control register (not in the assembler's CTL_REGS)")
            continue
        ak, writable, readable, wcyc, rcyc = asm.CTL_REGS[name]
        if k is not None and k != ak:
            errs.append(f"{where}: k {row['k']} but the assembler has {ak:#04x}")
        model = isa.CONTROL.get(ak)
        doc = {}
        for col, ccol, want, cyc, mdir in (
            ("W", "Write cycles", writable, wcyc, "w"),
            ("R", "Read cycles", readable, rcyc, "r"),
        ):
            perm = yes_no(row[col], where, col, errs)
            if perm is not None and perm != want:
                errs.append(
                    f"{where}: {col} '{row[col]}' but the assembler's CTL_REGS says "
                    f"{'yes' if want else 'no'}"
                )
            cell = row[ccol]
            if cell == "reserved":
                doc[col] = None
                if want:
                    errs.append(
                        f"{where}: {ccol} 'reserved' but the direction is assigned "
                        f"({cyc} cycle(s) in CTL_REGS)"
                    )
                continue
            n = parse_int(cell, where, ccol, errs)
            doc[col] = n
            if n is None:
                continue
            if not want:
                errs.append(f"{where}: {ccol} '{cell}' but that direction is unassigned; write 'reserved'")
            elif n != cyc:
                errs.append(f"{where}: {ccol} {n} but the assembler's CTL_REGS has {cyc}")
            if model is not None and want:
                mperm = model.writable if mdir == "w" else model.readable
                mcost = model.wcost if mdir == "w" else model.rcost
                if not mperm or mcost != n:
                    errs.append(
                        f"{where}: {ccol} {n} disagrees with the reference model's CONTROL "
                        f"({'cost ' + str(mcost) if mperm else 'unassigned'})"
                    )
        if model is None:
            errs.append(f"{where}: index {ak:#04x} is absent from the reference model's CONTROL")
        elif (model.writable, model.readable) != (writable, readable):
            errs.append(f"{where}: the reference model's W/R permissions differ from CTL_REGS")
        documented[name] = doc
    return documented


def check_opcodes(asm, isa, t: Table, ctl_doc: dict, errs: list):
    rows = keyed(t, "Mnemonic", errs)
    table = dict(asm.OPCODES)
    table.update(asm.CTL_MNEMONICS)
    for mnemonic in table:
        if mnemonic not in rows:
            errs.append(f"line {t.line}: table 'opcodes': missing row for mnemonic `{mnemonic}`")
    zero_setters = set()
    for mnemonic, (line_no, row) in rows.items():
        where = f"line {line_no}: table 'opcodes' row '{mnemonic}'"
        if mnemonic not in table:
            errs.append(f"{where}: unknown mnemonic (not in the assembler's OPCODES or CTL_MNEMONICS)")
            continue
        opcode, kind = table[mnemonic]
        op = parse_int(row["Opcode"], where, "Opcode", errs, pattern=r"0x[0-9A-Fa-f]", base=16)
        if op is not None and op != opcode:
            errs.append(f"{where}: Opcode {row['Opcode']} but the assembler has {opcode:#x}")
        if row["Kind"] != kind:
            errs.append(f"{where}: Kind '{row['Kind']}' but the assembler's kind is '{kind}'")
        if not row["Operands"]:
            errs.append(f"{where}: Operands is empty")
        if mnemonic in asm.OPCODES:
            mop = isa.BY_MNEMONIC.get(mnemonic)
            if mop is None or mop.code != opcode:
                errs.append(f"{where}: the reference model's opcode table disagrees with the assembler")
        z_rule, c_rule = row["Z"], row["C"]
        if z_rule not in Z_RULES:
            errs.append(f"{where}: Z '{z_rule}' is malformed (one of {', '.join(Z_RULES)})")
            z_rule = None
        if c_rule not in C_RULES:
            errs.append(f"{where}: C '{c_rule}' is malformed (one of {', '.join(C_RULES)})")
            c_rule = None
        if z_rule == "zero":
            zero_setters.add(mnemonic)
        bits = parse_encoding(row["Encoding"], where, errs)
        cycles = parse_cycles(row["Cycles"], where, errs)
        if bits is not None and op is not None:
            if not all(ch in "01" for ch in bits[:4]):
                errs.append(f"{where}: Encoding's opcode bits {bits[:4]} are not fixed 0/1 bits")
            elif int(bits[:4], 2) != op:
                errs.append(
                    f"{where}: Encoding's opcode bits {bits[:4]} do not match Opcode {row['Opcode']}"
                )
        form = samples(asm, mnemonic, kind)
        if bits is not None:
            # A letter run on bits the assembler always emits as 0 would encode
            # to the same word, so compare the field sets, not just the words.
            have = set(bits) - {"0", "1"}
            need = set().union(*(set(f) for _o, f, _c in form)) if form else set()
            for letter in sorted(have - need):
                errs.append(
                    f"{where}: Encoding '{row['Encoding']}' has field '{letter}' "
                    f"({FIELD_NAME[letter]}) but {mnemonic} ({kind}) has no such operand; "
                    f"write those bits as the fixed 0/1 the assembler emits"
                )
            for letter in sorted(need - have):
                errs.append(
                    f"{where}: Encoding '{row['Encoding']}' has no field '{letter}' "
                    f"({FIELD_NAME[letter]}) but {mnemonic} ({kind}) takes that operand"
                )
        for operands, fields, ctl in form:
            source = f"{mnemonic} {operands}".strip()
            ins, err = assemble_one(asm, source)
            if err is not None:
                errs.append(f"{where}: the assembler refused `{source}`: {err}")
                continue
            if bits is not None:
                want = encode(bits, fields)
                if want != ins.word:
                    errs.append(
                        f"{where}: documented encoding gives {want:#06x} for `{source}`, "
                        f"the assembler emits {ins.word:#06x}"
                    )
            if cycles is not None:
                ctl_cycles = None
                if ctl is not None:
                    ctl_cycles = ctl_doc.get(ctl[1], {}).get(ctl[0])
                doc_cycles = cycles(fields, ctl_cycles)
                if doc_cycles is None:
                    errs.append(
                        f"{where}: no documented cycle count for `{source}` "
                        f"(Cycles is 'control table' but that table has no usable "
                        f"{ctl[0] if ctl else '?'} entry for {ctl[1] if ctl else 'it'})"
                    )
                elif doc_cycles != ins.cycles:
                    errs.append(
                        f"{where}: documented cycles {doc_cycles} for `{source}`, "
                        f"the assembler counts {ins.cycles}"
                    )
                elif isa.static_cost(ins.word) != doc_cycles:
                    errs.append(
                        f"{where}: documented cycles {doc_cycles} for `{source}`, "
                        f"the reference model's static_cost is {isa.static_cost(ins.word)}"
                    )
            if z_rule is None or c_rule is None:
                continue
            check_flags(isa, where, source, ins.word, kind, z_rule, c_rule, errs)
    if hasattr(asm, "FLAG_SETTING_OPS") and zero_setters and set(asm.FLAG_SETTING_OPS) != zero_setters:
        errs.append(
            f"line {t.line}: table 'opcodes': Z = zero rows {sorted(zero_setters)} differ from "
            f"the assembler lint's Z-setting set {sorted(asm.FLAG_SETTING_OPS)}"
        )


def check_flags(isa, where, source, word, kind, z_rule, c_rule, errs):
    rd = (word >> 10) & 3
    rs = (word >> 8) & 3
    left = bool(rs & 1)
    cases = FLAG_CASES.get(kind, [(0x81, 0x7E)])
    reported = set()
    for a, b in cases:
        regs = [0x11, 0x22, 0x33, 0x44]
        regs[rs] = b
        regs[rd] = a  # Rd wins when Rd == Rs
        if kind == "rr" and rd == rs:
            b = a
        flags, result = model_flags(isa, word, regs)
        problems = []
        if z_rule == "unchanged" and "z" in flags:
            problems.append(f"Z documented unchanged, the model writes Z={flags['z']}")
        if z_rule == "zero":
            if "z" not in flags:
                problems.append("Z documented 'zero', the model leaves Z unchanged")
            elif result is not None and flags["z"] != int(result == 0):
                problems.append(f"Z documented 'zero', the model writes Z={flags['z']} for result {result:#04x}")
        if c_rule == "unchanged" and "c" in flags:
            problems.append(f"C documented unchanged, the model writes C={flags['c']}")
        elif c_rule != "unchanged":
            want = expected_c(c_rule, a, b, left)
            if "c" not in flags:
                problems.append(f"C documented '{c_rule}', the model leaves C unchanged")
            elif flags["c"] != want:
                problems.append(f"C documented '{c_rule}' (= {want}), the model writes C={flags['c']}")
        for p in problems:
            if p not in reported:
                reported.add(p)
                errs.append(f"{where}: `{source}` with Rd={a:#04x}, Rs={b:#04x}: {p}")


def check_shift(asm, isa, t: Table, errs: list):
    rows = keyed(t, "Direction", errs)
    for name in ("LEFT", "RIGHT"):
        if name not in rows:
            errs.append(f"line {t.line}: table 'shift': missing row for `{name}`")
    for name, (line_no, row) in rows.items():
        where = f"line {line_no}: table 'shift' row '{name}'"
        if name not in ("LEFT", "RIGHT"):
            errs.append(f"{where}: unknown direction (LEFT or RIGHT)")
            continue
        ins, err = assemble_one(asm, f"SHF R1, {name}")
        if err is not None:
            errs.append(f"{where}: the assembler refused `SHF R1, {name}`: {err}")
            continue
        bit = parse_int(row["Rs[0]"], where, "Rs[0]", errs, pattern=r"[01]")
        if bit is not None and bit != (ins.word >> 8) & 1:
            errs.append(f"{where}: Rs[0] {bit} but the assembler sets bit 8 to {(ins.word >> 8) & 1}")
        fill = parse_int(row["Fill"], where, "Fill", errs, pattern=r"[01]")
        m = re.fullmatch(r"Rd\[([0-7])\]", row["C"])
        if not m:
            errs.append(f"{where}: C '{row['C']}' is malformed (Rd[0] .. Rd[7])")
        left = name == "LEFT"
        for v in (0x00, 0xFF, 0x80, 0x01, 0x5A):
            flags, result = model_flags(isa, ins.word, [0, v, 0, 0])
            fill_bit = (result & 1) if left else (result >> 7) & 1
            if fill is not None and fill_bit != fill:
                errs.append(f"{where}: Fill {fill} but the model shifts {v:#04x} to {result:#04x}")
                break
            if m and flags.get("c") != (v >> int(m.group(1))) & 1:
                errs.append(
                    f"{where}: C is {row['C']} but the model writes C={flags.get('c')} "
                    f"shifting {v:#04x}"
                )
                break


def classify_reserved(asm, source: str):
    parts = asm._split_operands(source.split(None, 1)[1]) if " " in source.strip() else []
    mnemonic = source.split()[0].upper() if source.split() else ""
    try:
        if mnemonic == "WCTL" and parts:
            entry = asm.CTL_REGS.get(parts[0].upper())
            if entry is None:
                k = int(parts[0], 0)
                if k not in asm.CTL_BY_INDEX:
                    return "unassigned write"
            elif not entry[1]:
                return "write to a read-only register"
        if mnemonic == "RCTL" and len(parts) > 1:
            entry = asm.CTL_REGS.get(parts[1].upper())
            if entry is None:
                k = int(parts[1], 0)
                if k not in asm.CTL_BY_INDEX:
                    return "unassigned read"
            elif not entry[2]:
                return "read of a write-only register"
    except ValueError:
        return None
    if mnemonic == "OUT" and parts and asm.PORTS.get(parts[0].upper(), (None,))[0] == 0b01:
        return "OUT to port 01"
    if mnemonic == "IN" and len(parts) > 1 and asm.PORTS.get(parts[1].upper(), (None,))[0] == 0b11:
        return "IN from port 11"
    return None


def check_reserved(asm, t: Table, errs: list):
    rows = keyed(t, "Example", errs)
    covered = set()
    for source, (line_no, row) in rows.items():
        where = f"line {line_no}: table 'reserved' row '{source}'"
        case = classify_reserved(asm, source)
        if case:
            covered.add(case)
        for col, allow in (("Default", False), ("With --allow-reserved", True)):
            cell = row[col]
            if cell != "error" and not re.fullmatch(r"\d+", cell):
                errs.append(f"{where}: {col} '{cell}' is malformed ('error' or a cycle count)")
                continue
            ins, err = assemble_one(asm, source, allow_reserved=allow)
            if cell == "error" and err is None:
                errs.append(
                    f"{where}: {col} says error, but the assembler accepts it "
                    f"({ins.cycles} cycle(s), word {ins.word:#06x})"
                )
            elif cell != "error" and err is not None:
                errs.append(f"{where}: {col} says {cell} cycle(s), but the assembler refuses it: {err}")
            elif cell != "error" and ins.cycles != int(cell):
                errs.append(f"{where}: {col} says {cell} cycle(s), the assembler counts {ins.cycles}")
    for case in RESERVED_CASES:
        if case not in covered:
            errs.append(f"line {t.line}: table 'reserved': no example row for the case '{case}'")


def heading_anchors(text: str) -> set:
    """GitHub-style slugs of the document's own ATX headings (outside code fences)."""
    anchors, counts, fenced = set(), {}, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = None if fenced else re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        slug = re.sub(r"[^\w\- ]", "", m.group(1).replace("`", "").lower()).replace(" ", "-")
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        anchors.add(slug if n == 0 else f"{slug}-{n}")
    return anchors


def check_links(text: str, doc_dir: Path, errs: list):
    anchors = heading_anchors(text)
    for line_no, line in enumerate(text.splitlines(), start=1):
        for link in LINK.findall(line):
            if link.startswith("#"):
                if link[1:] not in anchors:
                    errs.append(f"line {line_no}: link {link} names no heading in this document")
                continue
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target = link.split("#", 1)[0]
            if target and not (doc_dir / target).exists():
                errs.append(f"line {line_no}: link target {link} does not exist")


def check_text(text: str, asm, isa, doc_dir: Path) -> list:
    """Return a list of drift errors for document `text` (empty = in step)."""
    errs = []
    tables = parse_tables(text, errs)
    if "ports" in tables:
        check_ports(asm, tables["ports"], errs)
    ctl_doc = {}
    if "control" in tables:
        ctl_doc = check_control(asm, isa, tables["control"], errs)
    if "opcodes" in tables:
        check_opcodes(asm, isa, tables["opcodes"], ctl_doc, errs)
    if "shift" in tables:
        check_shift(asm, isa, tables["shift"], errs)
    if "reserved" in tables:
        check_reserved(asm, tables["reserved"], errs)
    check_links(text, doc_dir, errs)
    return errs


def check(root: Path, doc: Path = None) -> list:
    doc = doc or (root / DOC_REL)
    if not doc.is_file():
        return [f"{doc}: missing"]
    asm, isa = load_sources(root)
    return check_text(doc.read_text(encoding="utf-8"), asm, isa, doc.parent)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--doc", type=Path, default=None,
                    help=f"document to check (default: <root>/{DOC_REL})")
    args = ap.parse_args(argv)
    doc = args.doc or (args.root / DOC_REL)
    errs = check(args.root, doc)
    for e in errs:
        print(f"check_architecture: {doc.name}: {e}", file=sys.stderr)
    print(f"check_architecture: {len(errs)} drift error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
