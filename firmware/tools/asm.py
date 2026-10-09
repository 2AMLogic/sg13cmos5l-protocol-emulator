#!/usr/bin/env python3
"""The DR 0003 firmware assembler for DR 0001's ISA (issue #22).

A small text assembler, hand-written for this ISA, with mnemonics matching
DR 0001's opcode table exactly (`spec/decision-records/0001-isa.md`,
section "Encoding" -- that table is the authority this tool cites, never
re-derives). Per `spec/decision-records/0003-firmware-toolchain.md`:

- Source programs are `.asm` text files under `firmware/asm/`.
- The assembler emits, per program, a **committed** build artifact pair
  under `firmware/build/`: a hex program image (one 16-bit word per line,
  `$readmemh`-compatible) plus a cycle-accounting report (total instruction
  count, and for each timing-critical `.cyclesec` section the exact cycle
  count from entry to exit, computed statically per DR 0001's
  no-data-dependent-latency guarantee).
- Output is committed, not gitignored, and deterministic: no timestamps,
  no paths except the source path as given, so `--check` can re-assemble
  and byte-compare the committed artifacts.

Encoding (DR 0001 section "Encoding", cited):

    15  14  13  12 | 11  10 |  9   8  |  7   6   5   4   3   2   1   0
    -----opcode----- --Rd--- --Rs/port- -----------imm8/unused-----------

    [9:8] is "Rs (register-register ops) or port (I/O ops)" -- so for both
    I/O opcodes (IN and OUT) the port code occupies [9:8] and the register
    occupies [11:10], keeping the encoding uniform (DR 0001's stated goal
    for the port field). DR 0001's port table maps the names this
    assembler accepts:

        UI_IN   = 00 (read-only)   UIO_IN  = 01 (read-only)
        UO_OUT  = 10 (write-only)  UIO_OUT = 11 (write-only)

Cycle costs (DR 0001's opcode table): every instruction is 1 cycle except
`WAIT imm8`, which stalls `imm8 + 1` cycles. `HALT` retires in 1 cycle and
then idles.

Control space (DR 0012, `spec/decision-records/
0012-control-space-and-runtime-pin-direction.md`, issue #135). Two of DR
0001's no-op I/O encodings carry a control-register index `k` in imm8:

    WCTL k, Rs   = OUT to port 00 with imm8 = k   (control register k <- Rs)
    RCTL Rd, k   = IN from port 10 with imm8 = k  (Rd <- control register k)

`k` is a name from DR 0012's register map (`UIO_DIR`, `UIO_OD`, `PM_ADDR`,
`PM_DATA_HI`, `PM_DATA_LO`, `RUN`, `PM_CRC_LO`, `PM_CRC_HI`, `BOOT_STATUS`,
`HW_ID`) or a number. Cycle costs are DR 0012's per-index table: 1, except
`WCTL PM_DATA_LO`, `WCTL RUN` and `RCTL PM_DATA_HI`, which are a fixed 2.
An index DR 0012 does not assign in that direction -- an unassigned `k`,
a write to a read-only register, a read of the write-only `RUN` -- is an
error unless `--allow-reserved` is given (hardware: a 1-cycle no-op / a
read of 0x00). `OUT` to port 01 and `IN` from port 11 stay reserved no-ops
and stay errors, with or without the flag; so do `OUT UI_IN` / `IN UO_OUT`
written as plain `OUT`/`IN` (use the `WCTL`/`RCTL` mnemonics).

Assembler lint (DR 0001 section "Timing model" delegates to DR 0003):
"a loop whose exit condition is derived from pin data is a
data-dependent-latency violation" when used for protocol timing -- the
assembler flags, as a *warning*, any conditional branch whose governing
flags were last set by an instruction consuming an `IN`-sampled (tainted)
register. Taint survives a trip through writable control state (`WCTL`
then `RCTL`); the per-register rules are at `_lint_data_dependent_branches`
and in firmware/README.md. Warning-level, not an error, because DR 0001 itself names the
legitimate case (an I2C ACK wait is a protocol handshake, not a timing
budget).

Usage:
    python3 firmware/tools/asm.py <source.asm> [--out-dir DIR] [--check]
                                  [--allow-reserved]
    python3 firmware/tools/asm.py --selftest-prefix DIR   (internal, used
        by test_asm.py to locate fixtures; not a user entry point)

Exit codes: 0 assembled (warnings allowed) / check passed; 1 assembly
errors or --check drift; 2 usage error.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

WORD_COUNT = 256  # DR 0001: 256 x 16-bit program words, 8-bit PC


class AsmError(Exception):
    """A single assembly error, carrying the offending source line number."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message


# --- DR 0001 opcode table (cited, not re-derived) -------------------------
# kind selects operand parsing and field packing:
#   none    : no operands            (NOP, HALT)
#   ldi     : Rd, imm8               (LDI)
#   rr      : Rd, Rs                 (MOV ADD SUB AND OR XOR)
#   shf     : Rd, LEFT|RIGHT         (SHF; direction bit in Rs[0], 1=left)
#   in      : Rd, readable-port      (IN)
#   out     : writable-port, Rs      (OUT)
#   wait    : imm8                   (WAIT; cycles = imm8 + 1)
#   branch  : imm8 | label           (JMP BZ BNZ; absolute 8-bit target)
#   wctl    : ctl-index, Rs          (WCTL; DR 0012: OUT port 00, imm8 = k)
#   rctl    : Rd, ctl-index          (RCTL; DR 0012: IN  port 10, imm8 = k)
OPCODES = {
    "NOP":  (0x0, "none"),
    "LDI":  (0x1, "ldi"),
    "MOV":  (0x2, "rr"),
    "ADD":  (0x3, "rr"),
    "SUB":  (0x4, "rr"),
    "AND":  (0x5, "rr"),
    "OR":   (0x6, "rr"),
    "XOR":  (0x7, "rr"),
    "SHF":  (0x8, "shf"),
    "IN":   (0x9, "in"),
    "OUT":  (0xA, "out"),
    "WAIT": (0xB, "wait"),
    "JMP":  (0xC, "branch"),
    "BZ":   (0xD, "branch"),
    "BNZ":  (0xE, "branch"),
    "HALT": (0xF, "none"),
}

# DR 0012 mnemonics. Not new opcodes (DR 0001's table stays exactly 16):
# WCTL is OUT's opcode with the port fixed at 00, RCTL is IN's with the
# port fixed at 10, and the control-register index rides imm8.
CTL_MNEMONICS = {
    "WCTL": (OPCODES["OUT"][0], "wctl"),
    "RCTL": (OPCODES["IN"][0], "rctl"),
}

# DR 0012 section 2 register map (cited, not re-derived):
#   name -> (k, writable, readable, write cycles, read cycles)
# "writable"/"readable" are the map's W / R columns. A direction the map
# does not assign is reserved: hardware makes the write a 1-cycle no-op
# and the read a 1-cycle 0x00.
CTL_PORT_WRITE = 0b00  # WCTL rides OUT to port 00 (ui_in's code)
CTL_PORT_READ = 0b10   # RCTL rides IN from port 10 (uo_out's code)
CTL_REGS = {
    "UIO_DIR":     (0x00, True,  True,  1, 1),
    "UIO_OD":      (0x01, True,  True,  1, 1),
    "PM_ADDR":     (0x02, True,  True,  1, 1),
    "PM_DATA_HI":  (0x03, True,  True,  1, 2),
    "PM_DATA_LO":  (0x04, True,  True,  2, 1),
    "RUN":         (0x05, True,  False, 2, 1),
    "PM_CRC_LO":   (0x06, True,  True,  1, 1),
    "PM_CRC_HI":   (0x07, True,  True,  1, 1),
    "BOOT_STATUS": (0x08, False, True,  1, 1),
    "HW_ID":       (0x09, False, True,  1, 1),
}
CTL_BY_INDEX = {entry[0]: (name,) + entry[1:] for name, entry in CTL_REGS.items()}

# DR 0001 port table: name -> (code, readable, writable)
PORTS = {
    "UI_IN":   (0b00, True,  False),
    "UIO_IN":  (0b01, True,  False),
    "UO_OUT":  (0b10, False, True),
    "UIO_OUT": (0b11, False, True),
}

REGISTERS = {f"R{i}": i for i in range(4)}  # DR 0001: R0-R3, four 8-bit GPRs

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Ops that set the Z flag read by BZ/BNZ (DR 0001 register/pin model).
# SHF is deliberately absent: it writes C only (the shifted-out bit), never
# the Z this set governs (rtl/protocol_core.v OP_SHF block; DR 0001 table).
FLAG_SETTING_OPS = {"ADD", "SUB", "AND", "OR", "XOR"}


@dataclass
class Instruction:
    addr: int
    word: int
    mnemonic: str
    text: str          # canonical operand text for the listing
    cycles: int
    line_no: int


@dataclass
class CycleSection:
    name: str
    start_addr: int   # inclusive
    end_addr: int     # inclusive
    cycles: int       # exact, entry -> exit, straight-line (static)
    has_branch: bool  # a branch instruction inside (report notes it)


@dataclass
class Program:
    source_name: str                  # source path as given on the CLI
    instructions: List[Instruction] = field(default_factory=list)
    sections: List[CycleSection] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def words(self) -> List[int]:
        return [ins.word for ins in self.instructions]

    @property
    def total_cycles(self) -> int:
        return sum(ins.cycles for ins in self.instructions)


def _parse_imm8(token: str, line_no: int) -> int:
    """Parse a decimal or 0x-hex immediate in [0, 255]."""
    value: Optional[int] = None
    if token.startswith(("0x", "0X")):
        try:
            value = int(token, 16)
        except ValueError:
            value = None
    elif token.isdigit():
        value = int(token, 10)
    elif token.startswith("-") and token[1:].isdigit():
        raise AsmError(line_no, f"negative immediate {token} (imm8 is 0..255)")
    if value is None:
        raise AsmError(line_no, f"bad immediate {token!r} (decimal or 0x-hex)")
    if not 0 <= value <= 255:
        raise AsmError(line_no, f"immediate {token} out of range (imm8 is 0..255)")
    return value


def _parse_register(token: str, line_no: int) -> int:
    reg = REGISTERS.get(token.upper())
    if reg is None:
        raise AsmError(
            line_no,
            f"bad register {token!r} (this ISA has exactly R0-R3, DR 0001)",
        )
    return reg


def _parse_port(token: str, line_no: int, *, need_read: bool, need_write: bool):
    entry = PORTS.get(token.upper())
    if entry is None:
        valid = ", ".join(PORTS)
        raise AsmError(line_no, f"bad port {token!r} (expected one of: {valid})")
    code, readable, writable = entry
    if need_read and not readable:
        if code == CTL_PORT_READ:
            raise AsmError(
                line_no,
                f"IN from write-only port {token.upper()} is a firmware bug: "
                "that encoding is DR 0012's control read -- write it as "
                "RCTL Rd, <control register>",
            )
        raise AsmError(
            line_no,
            f"IN from write-only port {token.upper()} is a firmware bug "
            "(DR 0001/0012: a reserved no-op in hardware; the assembler flags it)",
        )
    if need_write and not writable:
        if code == CTL_PORT_WRITE:
            raise AsmError(
                line_no,
                f"OUT to read-only port {token.upper()} is a firmware bug: "
                "that encoding is DR 0012's control write -- write it as "
                "WCTL <control register>, Rs",
            )
        raise AsmError(
            line_no,
            f"OUT to read-only port {token.upper()} is a firmware bug "
            "(DR 0001/0012: a reserved no-op in hardware; the assembler flags it)",
        )
    return code


def _parse_ctl(token: str, line_no: int, *, write: bool, allow_reserved: bool):
    """Parse a DR 0012 control-register operand (a name or a number).

    Returns (k, cycles, canonical text). An index DR 0012 does not assign
    in this direction is an error unless `allow_reserved`."""
    mnemonic = "WCTL" if write else "RCTL"
    entry = CTL_REGS.get(token.upper())
    if entry is not None:
        k, name = entry[0], token.upper()
    else:
        if IDENT_RE.match(token):
            valid = ", ".join(CTL_REGS)
            raise AsmError(
                line_no,
                f"bad control register {token!r} (DR 0012: expected one of: "
                f"{valid}, or a numeric index)",
            )
        k = _parse_imm8(token, line_no)
        name = CTL_BY_INDEX[k][0] if k in CTL_BY_INDEX else None
    if name is None:
        if not allow_reserved:
            raise AsmError(
                line_no,
                f"{mnemonic} index {k:#04x} is reserved (unassigned in DR 0012's "
                "register map: a no-op write / a read of 0x00 in hardware); "
                "pass --allow-reserved to assemble it anyway",
            )
        return k, 1, f"{k:#04x}"
    _, writable, readable, wcyc, rcyc = CTL_REGS[name]
    if write and not writable:
        if not allow_reserved:
            raise AsmError(
                line_no,
                f"WCTL to read-only control register {name} is reserved (DR 0012: "
                "a no-op in hardware); pass --allow-reserved to assemble it anyway",
            )
        return k, 1, name
    if not write and not readable:
        if not allow_reserved:
            raise AsmError(
                line_no,
                f"RCTL of write-only control register {name} is reserved (DR 0012: "
                "reads 0x00 in hardware); pass --allow-reserved to assemble it anyway",
            )
        return k, 1, name
    return k, (wcyc if write else rcyc), name


# -- the data-dependent-latency lint: control-space taint (DR 0012) ----------
#
# A control register is not a pin, but a writable one *stores* whatever a
# program wrote, so pin-derived data written with WCTL and read back with
# RCTL is still pin-derived. The lint therefore tracks taint per piece of
# control state, following what rtl/protocol_core.v (and, for the CRC,
# rtl/protocol_program_memory.v) actually does on each access:
#
#   UIO_DIR, UIO_OD, PM_ADDR   plain registers: RCTL returns the byte last
#       written. WCTL of a tainted register taints the index, WCTL of an
#       untainted one clears it. (WCTL/RCTL PM_DATA_LO also post-increment
#       PM_ADDR; +1 neither adds nor removes taint.)
#   PM_DATA_HI, PM_DATA_LO     ALWAYS tainted on read. RCTL PM_DATA_HI does
#       not read back the WCTL PM_DATA_HI latch (`pm_hi`): it returns the
#       high byte of PM[PM_ADDR] and parks the low byte in `pm_lo`, which is
#       all RCTL PM_DATA_LO ever returns. Both are program-memory contents,
#       and what a word holds depends on every commit ever made to it (by
#       this program, a loader before it, or the serial load) -- provenance
#       the assembler cannot establish per word, so it does not try.
#   PM_CRC_LO, PM_CRC_HI       one 16-bit accumulator over every committed
#       word {pm_hi, Rs}. Any WCTL to either index clears it (the written
#       value is ignored, so even a tainted Rs clears the taint). A WCTL
#       PM_DATA_LO whose word is tainted -- tainted Rs, or a tainted
#       `pm_hi` latch from an earlier WCTL PM_DATA_HI -- taints it, and it
#       stays tainted until cleared: a later clean commit folds into the
#       tainted sum. The CRC does not cover the address, so a tainted
#       PM_ADDR does not taint it.
#   BOOT_STATUS, HW_ID         never tainted: a load-time status bit and a
#       build-time constant; WCTL to them is a no-op.
#   RUN (write-only) and unassigned indices   read a constant 0x00.
#
# The scan is linear, so stored state is only known along straight-line
# code from reset (where every control register and the CRC are cleared;
# a CRC that already covers a serial load is a load-time fact, like
# BOOT_STATUS). Wherever control can arrive from somewhere else, the stored
# state is unknown and is treated as tainted until the program rewrites
# (or, for the CRC, clears) it:
#
#   - at every label, and at every numeric branch target (a merge with
#     whatever jumps there);
#   - after an unconditional transfer (JMP, HALT, WCTL RUN): what follows
#     is reachable only from elsewhere;
#   - everywhere, in a program containing a WCTL RUN: a computed jump can
#     land on any address, labelled or not.
_CTL_STORED = ("UIO_DIR", "UIO_OD", "PM_ADDR")
_CTL_PM_READ = ("PM_DATA_HI", "PM_DATA_LO")
_CTL_CRC = ("PM_CRC_LO", "PM_CRC_HI")


def _lint_data_dependent_branches(program: Program, label_addrs: set) -> None:
    """Append DR 0001's data-dependent-latency warnings to `program`.

    Runs over the assembled instructions (it changes no word): a `BZ`/`BNZ`
    warns when the flag-setting op governing it consumed a tainted
    register. Taint enters at `IN`, and at `RCTL` under the control-space
    rules in the comment above.
    """
    idx = {name: entry[0] for name, entry in CTL_REGS.items()}
    stored = {idx[n] for n in _CTL_STORED}
    pm_read = {idx[n] for n in _CTL_PM_READ}
    crc = {idx[n] for n in _CTL_CRC}
    run = idx["RUN"]

    def is_run(ins: Instruction) -> bool:
        return ins.mnemonic == "WCTL" and (ins.word & 0xFF) == run

    has_run = any(is_run(i) for i in program.instructions)
    # Labels, plus the targets of branches written as bare addresses
    # (forward references are resolved by now, so every branch word
    # carries its target in imm8).
    merge_addrs = set(label_addrs) | {
        i.word & 0xFF for i in program.instructions if i.mnemonic in ("JMP", "BZ", "BNZ")
    }

    tainted = [False, False, False, False]  # per-register taint
    last_flag_setter: Optional[Tuple[str, Tuple[bool, ...]]] = None
    # Stored control state. Keys: the plain register indices, "hi" (the
    # WCTL PM_DATA_HI latch, write-only but half of every committed word)
    # and "crc" (PM_CRC_HI:LO, one accumulator behind two indices).
    ctl = {k: has_run for k in (*stored, "hi", "crc")}

    def forget_ctl() -> None:
        for key in ctl:
            ctl[key] = True

    for ins in program.instructions:
        mnemonic = ins.mnemonic
        rd = (ins.word >> 10) & 0x3
        rs = (ins.word >> 8) & 0x3
        k = ins.word & 0xFF

        if ins.addr in merge_addrs:
            forget_ctl()

        if mnemonic == "LDI":
            tainted[rd] = False
        elif mnemonic == "IN":
            tainted[rd] = True
        elif mnemonic == "RCTL":
            if k in stored:
                tainted[rd] = ctl[k]
            elif k in pm_read:
                tainted[rd] = True
            elif k in crc:
                tainted[rd] = ctl["crc"]
            else:  # BOOT_STATUS, HW_ID, and the constant-0x00 reads
                tainted[rd] = False
        elif mnemonic == "WCTL":
            # The source register rides the Rd field (as OUT's does).
            if k in stored:
                ctl[k] = tainted[rd]
            elif k == idx["PM_DATA_HI"]:
                ctl["hi"] = tainted[rd]
            elif k == idx["PM_DATA_LO"]:
                ctl["crc"] = ctl["crc"] or ctl["hi"] or tainted[rd]
            elif k in crc:
                ctl["crc"] = False
        elif mnemonic == "MOV":
            tainted[rd] = tainted[rs]
        elif mnemonic in FLAG_SETTING_OPS:
            last_flag_setter = (mnemonic, (tainted[rd], tainted[rs]))
            tainted[rd] = tainted[rd] or tainted[rs]
        if mnemonic in ("BZ", "BNZ") and last_flag_setter is not None:
            setter, taints = last_flag_setter
            if any(taints):
                program.warnings.append(
                    f"line {ins.line_no}: {mnemonic} branches on flags set by "
                    f"{setter} over IN-sampled (pin-derived) data -- a "
                    "data-dependent-latency hazard if this loop produces "
                    "protocol timing (DR 0001 'Timing model'; legitimate "
                    "for protocol handshakes, e.g. an I2C ACK wait)"
                )

        if mnemonic in ("JMP", "HALT") or is_run(ins):
            forget_ctl()


def _split_operands(rest: str) -> List[str]:
    """Split an operand field on commas/whitespace (commas optional)."""
    return [p for p in re.split(r"[,\s]+", rest.strip()) if p]


def assemble_text(
    text: str, source_name: str = "<memory>", *, allow_reserved: bool = False
) -> Program:
    """Assemble `text` into a `Program`, raising `AsmError` on the first
    error encountered. `allow_reserved` admits WCTL/RCTL to indices DR 0012
    leaves reserved (the `--allow-reserved` CLI flag)."""
    program = Program(source_name=source_name)
    labels: dict = {}
    forward_refs: List[Tuple[str, int, int]] = []  # (label, addr, line_no)
    open_section: Optional[Tuple[str, int]] = None  # (name, start addr)
    closed_sections: List[Tuple[str, int, int]] = []  # (name, start, end)

    lines = text.splitlines()
    for line_no, raw in enumerate(lines, start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue

        # Labels (possibly several) at the head of a line.
        while True:
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*", line)
            if not match:
                break
            label = match.group(1)
            if label in labels:
                raise AsmError(line_no, f"duplicate label {label!r}")
            labels[label] = len(program.instructions)
            line = line[match.end():]
        if not line:
            continue

        # Directives.
        if line.startswith("."):
            parts = line.split()
            directive = parts[0].lower()
            if directive == ".cyclesec":
                if open_section is not None:
                    raise AsmError(line_no, ".cyclesec inside another .cyclesec")
                if len(parts) != 2 or not IDENT_RE.match(parts[1]):
                    raise AsmError(line_no, "usage: .cyclesec <name>")
                if any(name == parts[1] for name, _, _ in closed_sections):
                    raise AsmError(line_no, f"duplicate .cyclesec name {parts[1]!r}")
                open_section = (parts[1], len(program.instructions))
            elif directive == ".endcyclesec":
                if open_section is None:
                    raise AsmError(line_no, ".endcyclesec with no open .cyclesec")
                name, start = open_section
                end = len(program.instructions) - 1
                if end < start:
                    raise AsmError(line_no, f".cyclesec {name!r} is empty")
                closed_sections.append((name, start, end))
                open_section = None
            else:
                raise AsmError(line_no, f"unknown directive {parts[0]!r}")
            continue

        # Instruction.
        parts = line.split(None, 1)
        mnemonic = parts[0].upper()
        if mnemonic in OPCODES:
            opcode, kind = OPCODES[mnemonic]
        elif mnemonic in CTL_MNEMONICS:
            opcode, kind = CTL_MNEMONICS[mnemonic]
        else:
            raise AsmError(line_no, f"unknown mnemonic {parts[0]!r}")
        operands = _split_operands(parts[1] if len(parts) > 1 else "")

        rd = rs = port = imm = 0
        text_out = parts[0]
        ctl_cycles = 1

        def need(n):
            if len(operands) != n:
                raise AsmError(
                    line_no,
                    f"{mnemonic} takes {n} operand(s), got {len(operands)}",
                )

        if kind == "none":
            need(0)
        elif kind == "ldi":
            need(2)
            rd = _parse_register(operands[0], line_no)
            imm = _parse_imm8(operands[1], line_no)
            text_out = f"{mnemonic} R{rd}, {imm:#04x}"
        elif kind == "rr":
            need(2)
            rd = _parse_register(operands[0], line_no)
            rs = _parse_register(operands[1], line_no)
            text_out = f"{mnemonic} R{rd}, R{rs}"
        elif kind == "shf":
            need(2)
            rd = _parse_register(operands[0], line_no)
            direction = operands[1].upper()
            if direction == "LEFT":
                rs = 1  # DR 0001: dir bit in Rs[0], 1=left
            elif direction == "RIGHT":
                rs = 0
            else:
                raise AsmError(line_no, f"bad shift direction {operands[1]!r} (LEFT/RIGHT)")
            text_out = f"{mnemonic} R{rd}, {'LEFT' if rs else 'RIGHT'}"
        elif kind == "in":
            need(2)
            rd = _parse_register(operands[0], line_no)
            port = _parse_port(operands[1], line_no, need_read=True, need_write=False)
            text_out = f"{mnemonic} R{rd}, {operands[1].upper()}"
        elif kind == "out":
            need(2)
            port = _parse_port(operands[0], line_no, need_read=False, need_write=True)
            # DR 0001's encoding puts the port in [9:8] for I/O ops and the
            # register in [11:10] -- so OUT's source register rides the Rd
            # field (Rs stays 0). This is the uniform-port-slot reading the
            # encoding diagram states ("[9:8] ... or port (I/O ops)").
            rd = _parse_register(operands[1], line_no)
            text_out = f"{mnemonic} {operands[0].upper()}, R{rd}"
        elif kind == "wctl":
            # WCTL k, Rs -- OUT's encoding with the port fixed at 00: the
            # source register rides [11:10] exactly as OUT's does.
            need(2)
            imm, ctl_cycles, ctl_text = _parse_ctl(
                operands[0], line_no, write=True, allow_reserved=allow_reserved
            )
            rd = _parse_register(operands[1], line_no)
            port = CTL_PORT_WRITE
            text_out = f"{mnemonic} {ctl_text}, R{rd}"
        elif kind == "rctl":
            # RCTL Rd, k -- IN's encoding with the port fixed at 10.
            need(2)
            rd = _parse_register(operands[0], line_no)
            imm, ctl_cycles, ctl_text = _parse_ctl(
                operands[1], line_no, write=False, allow_reserved=allow_reserved
            )
            port = CTL_PORT_READ
            text_out = f"{mnemonic} R{rd}, {ctl_text}"
        elif kind == "wait":
            need(1)
            imm = _parse_imm8(operands[0], line_no)
            text_out = f"{mnemonic} {imm}"
        elif kind == "branch":
            need(1)
            token = operands[0]
            if IDENT_RE.match(token) and not token.isdigit():
                forward_refs.append((token, len(program.instructions), line_no))
                text_out = f"{mnemonic} {token}"
            else:
                imm = _parse_imm8(token, line_no)
                text_out = f"{mnemonic} {imm:#04x}"
        else:  # pragma: no cover - kinds are exhaustive
            raise AssertionError(kind)

        addr = len(program.instructions)
        if addr >= WORD_COUNT:
            raise AsmError(
                line_no,
                f"program exceeds DR 0001's {WORD_COUNT}-word program memory",
            )
        word = (opcode << 12) | (rd << 10) | ((rs | port) << 8) | (imm & 0xFF)

        if mnemonic == "WAIT":
            cycles = imm + 1
        elif mnemonic in ("WCTL", "RCTL"):
            cycles = ctl_cycles  # DR 0012's per-index latency table
        else:
            cycles = 1
        program.instructions.append(
            Instruction(addr, word, mnemonic, text_out, cycles, line_no)
        )

    if open_section is not None:
        raise AsmError(len(lines), f".cyclesec {open_section[0]!r} never closed")

    # Resolve forward label references.
    for label, addr, line_no in forward_refs:
        if label not in labels:
            raise AsmError(line_no, f"undefined label {label!r}")
        target = labels[label]
        if not 0 <= target <= 255:
            raise AsmError(line_no, f"label {label!r} (address {target}) out of imm8 range")
        ins = program.instructions[addr]
        opcode = ins.word >> 12
        ins.word = (opcode << 12) | target
        ins.text = f"{ins.mnemonic} {label}"

    _lint_data_dependent_branches(program, set(labels.values()))

    # Build cycle sections.
    for name, start, end in closed_sections:
        body = program.instructions[start : end + 1]
        program.sections.append(
            CycleSection(
                name=name,
                start_addr=start,
                end_addr=end,
                cycles=sum(i.cycles for i in body),
                has_branch=any(
                    i.mnemonic in ("JMP", "BZ", "BNZ")
                    # WCTL RUN is DR 0012's computed jump (PC <- Rs).
                    or (i.mnemonic == "WCTL" and (i.word & 0xFF) == CTL_REGS["RUN"][0])
                    for i in body
                ),
            )
        )
    return program


def render_hex(program: Program) -> str:
    """One 4-digit uppercase hex word per line ($readmemh-compatible)."""
    return "".join(f"{word:04X}\n" for word in program.words)


def render_cycles_report(program: Program) -> str:
    """The committed cycle-accounting report (DR 0003).

    Deterministic (no timestamps), greppable machine lines:
    WORDS / TOTAL-CYCLES / CYCLES / WARNING / ADDR.
    """
    out = [
        "cycle-accounting report (DR 0003 firmware toolchain)",
        f"program: {Path(program.source_name).stem}",
        f"source: {program.source_name}",
        f"WORDS {len(program.instructions)}",
        f"TOTAL-CYCLES {program.total_cycles}",
    ]
    for sec in program.sections:
        out.append(
            f"CYCLES name={sec.name} start={sec.start_addr} end={sec.end_addr} "
            f"cycles={sec.cycles} branches={'true' if sec.has_branch else 'false'}"
        )
    for warning in program.warnings:
        out.append(f"WARNING {warning}")
    for ins in program.instructions:
        out.append(
            f"ADDR 0x{ins.addr:02X} WORD 0x{ins.word:04X} {ins.text} cycles={ins.cycles}"
        )
    return "\n".join(out) + "\n"


def assemble_file(path: Path, *, allow_reserved: bool = False) -> Program:
    # The report's `source:` line must be canonical -- repo-relative when
    # the source lives in this repo -- so `--check` byte-compares the same
    # rendered text regardless of cwd or how the path was spelled.
    path = Path(path)
    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        name = str(path.resolve().relative_to(repo_root))
    except ValueError:
        name = str(path)
    return assemble_text(
        path.read_text(encoding="utf-8"), source_name=name, allow_reserved=allow_reserved
    )


def check_against(program: Program, out_dir: Path) -> List[str]:
    """Compare `program`'s artifacts with the committed ones in `out_dir`.

    Returns a list of drift descriptions (empty when byte-identical)."""
    stem = Path(program.source_name).stem
    hex_path = out_dir / f"{stem}.hex"
    cycles_path = out_dir / f"{stem}.cycles.txt"
    drift = []
    for path, rendered in (
        (hex_path, render_hex(program)),
        (cycles_path, render_cycles_report(program)),
    ):
        if not path.exists():
            drift.append(f"missing committed artifact {path}")
        elif path.read_text(encoding="utf-8") != rendered:
            drift.append(f"committed artifact {path} does not match the source")
    return drift


def main(argv: List[str]) -> int:
    args = list(argv)
    check = False
    allow_reserved = False
    out_dir: Optional[str] = None
    sources: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--check":
            check = True
        elif arg == "--allow-reserved":
            allow_reserved = True
        elif arg in ("--out-dir", "-o"):
            i += 1
            if i >= len(args):
                print("usage: --out-dir needs a value", file=sys.stderr)
                return 2
            out_dir = args[i]
        elif arg.startswith("-") and arg != "-":
            print(f"unknown option {arg}", file=sys.stderr)
            return 2
        else:
            sources.append(arg)
        i += 1
    if len(sources) != 1:
        print(
            "usage: asm.py <source.asm> [--out-dir DIR] [--check] [--allow-reserved]",
            file=sys.stderr,
        )
        return 2

    source = Path(sources[0])
    if not source.exists():
        print(f"error: no such source file {source}", file=sys.stderr)
        return 2
    if out_dir is None:
        # DR 0003's fixed layout: build output lives in firmware/build/,
        # which is <this script's dir>/../build regardless of cwd.
        out_dir = str(Path(__file__).resolve().parent.parent / "build")

    try:
        program = assemble_file(source, allow_reserved=allow_reserved)
    except AsmError as err:
        print(f"{source}:{err.line_no}: error: {err.message}", file=sys.stderr)
        return 1

    for warning in program.warnings:
        print(f"{source}: warning: {warning}", file=sys.stderr)

    if check:
        drift = check_against(program, Path(out_dir))
        if drift:
            for item in drift:
                print(f"drift: {item}", file=sys.stderr)
            print(
                "Re-run: python3 firmware/tools/asm.py <source> "
                "and commit the regenerated firmware/build/ artifacts.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: committed artifacts match {source}")
        return 0

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    (out / f"{stem}.hex").write_text(render_hex(program), encoding="utf-8")
    (out / f"{stem}.cycles.txt").write_text(
        render_cycles_report(program), encoding="utf-8"
    )
    print(
        f"{source}: {len(program.instructions)} words, "
        f"{program.total_cycles} fall-through cycles, "
        f"{len(program.sections)} cycle section(s), "
        f"{len(program.warnings)} warning(s) -> {out}/{stem}.hex, "
        f"{out}/{stem}.cycles.txt"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
