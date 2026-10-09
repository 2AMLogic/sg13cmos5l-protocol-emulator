#!/usr/bin/env python3
"""Protocol pin-role drift checker (issue #94, decision record 0010).

`spec/decision-records/0010-protocol-pin-roles.md` carries a fenced
machine-readable JSON table (info string `json pin-roles`) that assigns each
of the 24 physical pins (`ui_in[7:0]`, `uo_out[7:0]`, `uio[7:0]`) an
electrical role, a load-phase role and a role per protocol phase. This script
compares that table against the places the repository actually encodes pin
assignments, so the record and the sources cannot drift apart silently.

Four separate results are reported -- they are different claims and are never
merged into one green/red bit:

1. `schema`                 the table is well formed (24 pins, no duplicates,
                            no unknown ports, bits in range, consistent
                            electrical roles, known extraction patterns,
                            every committed firmware file inventoried).
2. `metadata-capability`    `info.yaml` pin keys, directions and *generic* ISA
                            labels, plus the top-level load wiring, agree with
                            the table. A generic label ("ISA output port 10
                            bit 3") is a statement about an ISA capability,
                            NOT evidence that any UART/SPI/I2C assignment or
                            open-drain pad is implemented.
3. `concrete-firmware-bench` every committed assembly variant, the I2C
                            generator, and every pin-observing bench uses the
                            pins the table assigns. A mismatch names the file,
                            the site and the pin. There is deliberately no
                            switch that suppresses a mismatch: a proposal
                            that moves a pin makes this result FAIL until the
                            follow-up edits land.
4. `implementation`         which proposed electrical roles are not wired in
                            the top level (e.g. `uio_oe = 8'h00` leaves every
                            open-drain role unwired), plus prerequisites such
                            as the `uio_out` reset value. Since issue #135 the
                            top level has DR 0012's runtime pin mode
                            (`uio_oe` from the UIO_OD / UIO_DIR control
                            registers); in that shape an open-drain role is
                            "wired" when each I2C program sets the table's
                            mask with `WCTL UIO_OD` after releasing the
                            lines, and the registers must reset to 0. Default success
                            means results 1-3 agree with the Proposed record;
                            `--require-implemented` additionally fails while
                            this list is non-empty.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/check_protocol_pin_roles.py
    python3 scripts/check_protocol_pin_roles.py --require-implemented
    python3 scripts/check_protocol_pin_roles.py --repo-root DIR --format json

Exit codes: 0 pass, 1 a checked layer failed (or, with
`--require-implemented`, an electrical role is unwired), 2 usage error.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

DEFAULT_RECORD = "spec/decision-records/0010-protocol-pin-roles.md"
TABLE_FENCE_RE = re.compile(r"^```json pin-roles[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)

PORTS = ("ui_in", "uo_out", "uio")
ELECTRICAL = ("input", "push_pull", "open_drain")
PHASES = (
    "uart_tx",
    "uart_rx",
    "uart_rx_result",
    "spi_transfer",
    "spi_result",
    "i2c_transfer",
    "i2c_result",
)
UNUSED = "unused"
LOAD_ROLES = ("PROG_SER", "PROG_MODE", "none")

# Role classes (what the role does electrically).
DRIVE_PP = {"TX", "CS", "SCLK", "MOSI"} | {f"RESULT[{i}]" for i in range(8)}
DRIVE_OD = {"SCL", "SDA"}
SAMPLE = {"MISO", "RX"}
ALL_ROLES = DRIVE_PP | DRIVE_OD | SAMPLE

# Phase role vocabulary (the record's `phases` object must match exactly).
PHASE_VOCAB = {
    "uart_tx": {"TX"},
    "uart_rx": {"RX"},
    "uart_rx_result": {f"RESULT[{i}]" for i in range(8)},
    "spi_transfer": {"CS", "SCLK", "MOSI", "MISO"},
    "spi_result": {f"RESULT[{i}]" for i in range(8)},
    "i2c_transfer": {"SCL", "SDA"},
    "i2c_result": {f"RESULT[{i}]" for i in range(8)},
}

# Extraction patterns this script implements. An inventory entry naming any
# other pattern is rejected (unsupported extraction pattern).
PATTERNS = {
    "asm_ports",            # set of OUT / IN port names used by the file
    "uart_tx_mask",         # first `LDI R1, imm` == TX bit mask; ALU mask LDIs
    "uart_rx_debug",        # every OUT UIO_OUT in uart_rx*.asm is a declared bench-debug write
    "uart_rx_mask",         # first `LDI R1, imm` == RX bit mask; ALU masks; IN/AND masks
    "spi_images",           # LDI R2 -> OUT UO_OUT pin images
    "spi_miso_mask",        # IN UIO_IN ... AND Rx, Ry nearest-LDI mask
    "i2c_idle_start",       # first two `LDI R3, imm` before OUT UIO_OUT, R3
    "i2c_alu_masks",        # LDI Rn,imm immediately followed by AND/OR/XOR use
    "i2c_in_masks",         # IN UIO_IN ... AND Rx, Ry nearest-LDI mask
    "i2c_poll_mask",        # `LDI R3, imm` before `pollN: IN`
    "gen_strings",          # instruction string literals of gen_i2c_sr.py
    "bench_uart_tx",        # TX_PIN, TX_BIT = "port", n
    "bench_spi_consts",     # CS/SCLK/MOSI/MISO constants and capture ports
    "bench_i2c_consts",     # SCL/SDA constants, _RELEASED, _ACK_PULL
    "bench_i2c_sr_consts",  # imports, 0x81 / (sda_drive << N), capture ports
    "bench_load_pins",      # load_program ui_in MODE / serial assignments
    "top_load_wiring",      # .mode_pin(ui_in[n]) / .serial_in(ui_in[n])
    "top_uio_oe",           # assign uio_oe = <literal | DR 0008 mask | DR 0012 pin-mode rule>;
    "top_port_passthrough", # .port_*(whole-port) connections
    "core_uio_out_reset",   # port_uio_out reset literal
    "isa_port_table",       # firmware/tools/asm.py PORTS codes
    "info_pinout",          # info.yaml pinout block
}

# Bench-debug writes a profile may make that are NOT pin roles. The table's
# optional `bench_debug` block declares the bit of each; nothing else may be
# written to that port by the profile.
BENCH_DEBUG_VOCAB = {"uart_rx": {"SAMPLE_MARK", "FRAME_ERROR"}}

ISA_PORT_CODES = {"UI_IN": 0, "UIO_IN": 1, "UO_OUT": 2, "UIO_OUT": 3}
PORT_ASM = {
    ("ui_in", "in"): "UI_IN",
    ("uio", "in"): "UIO_IN",
    ("uo_out", "out"): "UO_OUT",
    ("uio", "out"): "UIO_OUT",
}


class Layer:
    """One reported result: a name, a list of failure diagnostics, notes."""

    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []
        self.notes: list[str] = []
        self.sites = 0

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


class Checker:
    def __init__(self, root: Path, record: str):
        self.root = root
        self.record = record
        self.schema = Layer("schema")
        self.meta = Layer("metadata-capability")
        self.concrete = Layer("concrete-firmware-bench")
        self.unwired: list[str] = []
        self.uart_rx_debug: dict[str, set[int]] = {}  # file -> values written to UIO_OUT
        self.table: dict | None = None
        self.pins: dict[tuple[str, int], dict] = {}
        self._cache: dict[str, str | None] = {}

    # ------------------------------------------------------------ file access
    def read(self, rel: str, layer: Layer) -> str | None:
        if rel not in self._cache:
            p = self.root / rel
            self._cache[rel] = p.read_text(encoding="utf-8") if p.is_file() else None
        text = self._cache[rel]
        if text is None:
            layer.err(f"{rel}: missing source file (listed in the inventory)")
        return text

    # ----------------------------------------------------------------- schema
    def load_table(self) -> bool:
        s = self.schema
        text = self.read(self.record, s)
        if text is None:
            return False
        found = TABLE_FENCE_RE.findall(text)
        if len(found) != 1:
            s.err(
                f"{self.record}: expected exactly one ```json pin-roles fenced "
                f"table, found {len(found)}"
            )
            return False
        try:
            self.table = json.loads(found[0])
        except json.JSONDecodeError as exc:
            s.err(f"{self.record}: pin-roles table is not valid JSON: {exc}")
            return False
        return self.validate_table()

    def validate_table(self) -> bool:
        s, t = self.schema, self.table
        assert t is not None
        for key in ("schema", "open_drain_mask", "push_pull_mask", "phases", "pins", "inventory"):
            if key not in t:
                s.err(f"table: missing top-level key {key!r}")
        if s.errors:
            return False
        phases = t["phases"]
        if set(phases) != set(PHASES):
            s.err(f"table.phases: keys {sorted(phases)} != {sorted(PHASES)}")
        else:
            for ph in PHASES:
                roles = phases[ph]
                if not isinstance(roles, list) or len(set(roles)) != len(roles):
                    s.err(f"table.phases.{ph}: must be a list of distinct roles")
                    continue
                if set(roles) != PHASE_VOCAB[ph]:
                    s.err(
                        f"table.phases.{ph}: roles {sorted(roles)} != the "
                        f"supported vocabulary {sorted(PHASE_VOCAB[ph])}"
                    )

        seen: dict[tuple[str, int], dict] = {}
        for i, pin in enumerate(t["pins"]):
            where = f"table.pins[{i}]"
            for key in ("pin", "port", "bit", "electrical_role", "load_role",
                        "metadata_class", "protocol_roles", "shared_pin_rationale"):
                if key not in pin:
                    s.err(f"{where}: missing key {key!r}")
            if any(k not in pin for k in ("port", "bit", "electrical_role", "protocol_roles")):
                continue
            port, bit = pin["port"], pin["bit"]
            if port not in PORTS:
                s.err(f"{where}: unknown port {port!r} (expected one of {PORTS})")
                continue
            if not isinstance(bit, int) or isinstance(bit, bool) or not 0 <= bit <= 7:
                s.err(f"{where}: bit {bit!r} out of range 0..7")
                continue
            label = f"{port}[{bit}]"
            if pin.get("pin") != label:
                s.err(f"{where}: pin name {pin.get('pin')!r} != {label!r}")
            if (port, bit) in seen:
                s.err(f"{where}: duplicate entry for {label}")
                continue
            seen[(port, bit)] = pin
            if pin["electrical_role"] not in ELECTRICAL:
                s.err(f"{label}: unknown electrical_role {pin['electrical_role']!r}")
            if pin.get("load_role") not in LOAD_ROLES:
                s.err(f"{label}: unknown load_role {pin.get('load_role')!r}")
            if pin.get("metadata_class") != "generic_isa_capability":
                s.err(f"{label}: metadata_class must be 'generic_isa_capability'")
            pr = pin["protocol_roles"]
            if set(pr) != set(PHASES):
                s.err(f"{label}: protocol_roles keys {sorted(pr)} != {sorted(PHASES)}")
        for port in PORTS:
            for bit in range(8):
                if (port, bit) not in seen:
                    s.err(f"table: missing pin {port}[{bit}]")
        if len(t["pins"]) != 24:
            s.err(f"table.pins: {len(t['pins'])} entries, expected exactly 24")
        if s.errors:
            return False
        self.pins = seen
        self.validate_roles()
        self.validate_masks()
        self.validate_inventory()
        self.validate_bench_debug()
        return s.ok

    def validate_bench_debug(self) -> None:
        """`bench_debug` declares writes that are NOT pin roles but that a
        profile must still account for bit by bit. Only `uart_rx` has any."""
        s = self.schema
        self.debug_bits: dict[str, dict[str, int]] = {}
        bd = self.table.get("bench_debug", {})
        if not isinstance(bd, dict) or set(bd) - set(BENCH_DEBUG_VOCAB):
            s.err(f"table.bench_debug: keys must be a subset of {sorted(BENCH_DEBUG_VOCAB)}")
            return
        for prof, ent in bd.items():
            where = f"table.bench_debug.{prof}"
            bits = ent.get("bits") if isinstance(ent, dict) else None
            if not isinstance(ent, dict) or ent.get("port") != "uio" or not isinstance(bits, dict):
                s.err(f"{where}: must be {{\"port\": \"uio\", \"bits\": {{name: bit}}}}")
                continue
            if set(bits) != BENCH_DEBUG_VOCAB[prof]:
                s.err(f"{where}.bits: names {sorted(bits)} != {sorted(BENCH_DEBUG_VOCAB[prof])}")
                continue
            vals = list(bits.values())
            if any(not isinstance(b, int) or isinstance(b, bool) or not 0 <= b <= 7 for b in vals) \
                    or len(set(vals)) != len(vals):
                s.err(f"{where}.bits: each bit must be a distinct integer 0..7")
                continue
            self.debug_bits[prof] = dict(bits)

    def validate_roles(self) -> None:
        s = self.schema
        for (port, bit), pin in sorted(self.pins.items()):
            label = f"{port}[{bit}]"
            el = pin["electrical_role"]
            # electrical role vs port
            if port == "ui_in" and el != "input":
                s.err(f"{label}: dedicated input cannot be {el}")
            if port == "uo_out" and el != "push_pull":
                s.err(f"{label}: dedicated output must be push_pull, not {el}")
            driving = set()
            for ph, role in pin["protocol_roles"].items():
                if role == UNUSED:
                    continue
                if ph in PHASE_VOCAB and role not in PHASE_VOCAB[ph]:
                    s.err(f"{label}: role {role!r} not in phase {ph} vocabulary")
                    continue
                if role in DRIVE_PP:
                    driving.add("push_pull")
                    if port == "ui_in":
                        s.err(f"{label}: output role {role} on a dedicated input")
                    if el != "push_pull":
                        s.err(f"{label}: {role} ({ph}) needs push_pull, table says {el}")
                elif role in DRIVE_OD:
                    driving.add("open_drain")
                    if port != "uio":
                        s.err(f"{label}: open-drain role {role} must sit on uio")
                    if el != "open_drain":
                        s.err(f"{label}: {role} ({ph}) needs open_drain, table says {el}")
                elif role in SAMPLE:
                    if port == "uo_out":
                        s.err(f"{label}: input role {role} on a dedicated output")
            kinds = driving
            if len(kinds) > 1:
                s.err(f"{label}: contradictory driven roles across phases: {sorted(kinds)}")
            if pin["load_role"] != "none" and port != "ui_in":
                s.err(f"{label}: load role {pin['load_role']} must be on ui_in")
            sampled = any(r in SAMPLE for r in pin["protocol_roles"].values())
            if sampled and el != "input" and not driving:
                s.err(f"{label}: sampled-only role needs electrical_role input, table says {el}")
            if sampled and driving and not str(pin["shared_pin_rationale"]).strip():
                s.err(f"{label}: input role shares a driven pad but has no shared_pin_rationale")
            if el != "input" and not driving:
                s.err(f"{label}: electrical_role {el} with no driving protocol role")
        # every phase role placed exactly once
        for ph, roles in self.table["phases"].items():
            placed: dict[str, list[str]] = {}
            for (port, bit), pin in self.pins.items():
                role = pin["protocol_roles"].get(ph, UNUSED)
                if role != UNUSED:
                    placed.setdefault(role, []).append(f"{port}[{bit}]")
            for role in roles:
                where = placed.get(role, [])
                if len(where) != 1:
                    s.err(f"phase {ph}: role {role} placed on {where or 'no pin'}, expected exactly one")
            for role in placed:
                if role not in roles:
                    s.err(f"phase {ph}: role {role} placed but not declared in table.phases")
            for r, where in placed.items():
                if r.startswith("RESULT[") and where != [f"uo_out[{r[7]}]"]:
                    s.err(f"phase {ph}: {r} must sit on uo_out[{r[7]}], found {where}")
        loads = {p["load_role"]: f"{k[0]}[{k[1]}]" for k, p in self.pins.items() if p["load_role"] != "none"}
        if set(loads) != {"PROG_SER", "PROG_MODE"}:
            s.err(f"load roles placed: {sorted(loads)}; need exactly PROG_SER and PROG_MODE once each")

    def validate_masks(self) -> None:
        s = self.schema
        od = pp = 0
        for (port, bit), pin in self.pins.items():
            if port != "uio":
                continue
            if pin["electrical_role"] == "open_drain":
                od |= 1 << bit
            elif pin["electrical_role"] == "push_pull":
                pp |= 1 << bit
        for name, derived in (("open_drain_mask", od), ("push_pull_mask", pp)):
            try:
                declared = int(self.table[name], 0)
            except (TypeError, ValueError):
                s.err(f"table.{name}: {self.table[name]!r} is not an integer literal")
                continue
            if declared != derived:
                s.err(
                    f"table.{name} 0x{declared:02X} != 0x{derived:02X} derived "
                    f"from the per-pin electrical roles on uio"
                )
        self.od_mask, self.pp_mask = od, pp

    def validate_inventory(self) -> None:
        s = self.schema
        inv = self.table["inventory"]
        self.inv = {}
        for i, ent in enumerate(inv):
            where = f"table.inventory[{i}]"
            if "file" not in ent or "patterns" not in ent or "profile" not in ent:
                s.err(f"{where}: needs file, profile, patterns")
                continue
            if ent["file"] in self.inv:
                s.err(f"{where}: duplicate inventory file {ent['file']}")
            for pat in ent["patterns"]:
                if pat not in PATTERNS:
                    s.err(f"{where} ({ent['file']}): unsupported extraction pattern {pat!r}")
            self.inv[ent["file"]] = ent
        asm_dir = self.root / "firmware" / "asm"
        if asm_dir.is_dir():
            for f in sorted(asm_dir.glob("*.asm")):
                rel = f"firmware/asm/{f.name}"
                if rel not in self.inv:
                    s.err(
                        f"{rel}: committed firmware file is not in the inventory "
                        f"(add it with its pin-role patterns; do not claim coverage "
                        f"for files not on this tree)"
                    )
        for rel in self.inv:
            if not (self.root / rel).is_file():
                s.err(f"{rel}: inventory lists a file that is not on this tree")

    # -------------------------------------------------------------- pin lookup
    def role_pin(self, phase: str, role: str) -> tuple[str, int] | None:
        for (port, bit), pin in self.pins.items():
            if pin["protocol_roles"].get(phase) == role:
                return port, bit
        return None

    def mask_of(self, phase: str, role: str) -> int:
        pb = self.role_pin(phase, role)
        return 0 if pb is None else 1 << pb[1]

    def pins_of(self, phase: str, roles) -> list[tuple[str, int]]:
        return [self.role_pin(phase, r) for r in roles]

    # --------------------------------------------------------- asm extraction
    INSTR_RE = re.compile(r"^\s*(?:(\w+):)?\s*([A-Za-z]+)\s+(.*?)\s*$")
    MNEM = {"LDI": 2, "MOV": 2, "IN": 2, "OUT": 2, "AND": 2, "OR": 2, "XOR": 2,
            "ADD": 2, "SUB": 2, "SHF": 2,
            "WCTL": 2, "RCTL": 2}  # DR 0012 control space (issue #135)
    WRITES = {"LDI", "MOV", "IN", "AND", "OR", "XOR", "ADD", "SUB", "SHF", "RCTL"}

    def parse_lines(self, lines) -> list[dict]:
        out = []
        for no, raw in lines:
            line = raw.split(";", 1)[0]
            m = self.INSTR_RE.match(line)
            if not m:
                continue
            label, mnem, rest = m.group(1), m.group(2).upper(), m.group(3)
            if mnem not in self.MNEM:
                continue
            ops = [o.strip() for o in rest.split(",")]
            if len(ops) != self.MNEM[mnem] or not all(re.fullmatch(r"\w+", o) for o in ops):
                continue
            out.append({"no": no, "label": label, "m": mnem, "ops": ops})
        return out

    @staticmethod
    def imm(tok: str) -> int | None:
        try:
            return int(tok, 0)
        except ValueError:
            return None

    def asm_instrs(self, text: str) -> list[dict]:
        return self.parse_lines(enumerate(text.splitlines(), 1))

    def gen_instrs(self, text: str, rel: str) -> list[dict]:
        tree = ast.parse(text)
        pieces = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                pieces.append((node.lineno, node.col_offset, node.value))
            elif isinstance(node, ast.JoinedStr):
                s = "".join(
                    v.value if isinstance(v, ast.Constant) else "0" for v in node.values
                )
                pieces.append((node.lineno, node.col_offset, s))
        pieces.sort()
        lines = []
        for no, _col, s in pieces:
            for sub in s.splitlines():
                lines.append((no, sub))
        return self.parse_lines(lines)

    def check_ports(self, rel: str, ins: list[dict], allowed_out: set, allowed_in: set,
                    need_out: set, need_in: set) -> None:
        c = self.concrete
        outs = {i["ops"][0].upper() for i in ins if i["m"] == "OUT"}
        ins_ = {i["ops"][0].upper() for i in ins if False}
        ins_ = {i["ops"][1].upper() for i in ins if i["m"] == "IN"}
        c.sites += len(outs) + len(ins_)
        for p in sorted(outs - allowed_out):
            c.err(f"{rel}: OUT to port {p}; the table allows {sorted(allowed_out)} for this profile")
        for p in sorted(need_out - outs):
            c.err(f"{rel}: no OUT to port {p}; the table assigns pins on it")
        for p in sorted(ins_ - allowed_in):
            c.err(f"{rel}: IN from port {p}; the table allows {sorted(allowed_in)} for this profile")
        for p in sorted(need_in - ins_):
            c.err(f"{rel}: no IN from port {p}; the table assigns pins on it")

    def check_mask_sites(self, rel: str, ins: list[dict], mask_ok: set, name: str,
                         lineno_filter=None) -> None:
        """LDI Rn,imm immediately followed by AND/OR/XOR Rx,Rn must use a pin mask."""
        c = self.concrete
        for a, b in zip(ins, ins[1:]):
            if a["m"] == "LDI" and b["m"] in ("AND", "OR", "XOR") and b["ops"][1] == a["ops"][0]:
                v = self.imm(a["ops"][1])
                c.sites += 1
                if v not in mask_ok:
                    c.err(
                        f"{rel}:{a['no']}: {name} mask LDI {a['ops'][0]}, {a['ops'][1]} feeding "
                        f"{b['m']} is not a pin mask of this profile "
                        f"{sorted(f'0x{m:02X}' for m in mask_ok)}"
                    )

    def in_and_sites(self, rel: str, ins: list[dict], want_for, port: str = "UIO_IN") -> None:
        """For each IN Rx,<port>, the next AND Rx,Ry takes its mask from the nearest LDI Ry."""
        c = self.concrete
        for idx, i in enumerate(ins):
            if not (i["m"] == "IN" and i["ops"][1].upper() == port):
                continue
            rx = i["ops"][0]
            found = None
            for j in range(idx + 1, len(ins)):
                k = ins[j]
                if k["m"] == "IN":
                    break
                if k["m"] == "AND" and k["ops"][0] == rx:
                    found = (j, k)
                    break
            if not found:
                continue
            j, k = found
            ry = k["ops"][1]
            ldi = next((q for q in reversed(ins[:j]) if q["m"] in self.WRITES and q["ops"][0] == ry), None)
            if ldi is None or ldi["m"] != "LDI":
                continue
            want, what = want_for(i)
            c.sites += 1
            v = self.imm(ldi["ops"][1])
            if v != want:
                c.err(
                    f"{rel}:{ldi['no']}: IN {port} at line {i['no']} is masked with "
                    f"{ldi['ops'][1]} but the table's {what} is 0x{want:02X}"
                )

    def run_inventory(self) -> None:
        for rel, ent in self.inv.items():
            prof = ent["profile"]
            fn = getattr(self, f"prof_{prof}", None)
            if fn is None:
                self.schema.err(f"{rel}: unsupported inventory profile {prof!r}")
                continue
            fn(rel, ent)
            if prof != "demo" and not ent["patterns"]:
                self.schema.err(f"{rel}: no extraction patterns listed")

    def out_in_ports(self, phase_roles_out, phase_roles_in, result_phase):
        out_ports, in_ports = set(), set()
        for ph, roles in phase_roles_out:
            for r in roles:
                pb = self.role_pin(ph, r)
                if pb:
                    out_ports.add(PORT_ASM[(pb[0], "out")])
        for ph, roles in phase_roles_in:
            for r in roles:
                pb = self.role_pin(ph, r)
                if pb:
                    in_ports.add(PORT_ASM[(pb[0], "in")])
        res = set()
        for r in PHASE_VOCAB[result_phase]:
            pb = self.role_pin(result_phase, r)
            if pb:
                res.add(PORT_ASM[(pb[0], "out")])
        return out_ports, in_ports, res

    # ---------------------------------------------------------- profile: uart
    def prof_uart_tx(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        c = self.concrete
        ins = self.asm_instrs(text)
        outs, _ins, _ = self.out_in_ports([("uart_tx", ["TX"])], [], "spi_result")
        self.check_ports(rel, ins, outs, set(), outs, set())
        mask = self.mask_of("uart_tx", "TX")
        first = next((i for i in ins if i["m"] == "LDI" and i["ops"][0] == "R1"), None)
        if first is None:
            c.err(f"{rel}: no `LDI R1, imm` TX bit-mask site found (pattern uart_tx_mask)")
        else:
            c.sites += 1
            v = self.imm(first["ops"][1])
            if v != mask:
                c.err(f"{rel}:{first['no']}: TX bit mask LDI R1, {first['ops'][1]} but the table's "
                      f"uart_tx TX pin {self.role_pin('uart_tx', 'TX')} is 0x{mask:02X}")
        self.check_mask_sites(rel, ins, {mask}, "UART TX")
        # the bit isolated by AND must come from the R1 mask
        if not any(i["m"] == "AND" and i["ops"][1] == "R1" for i in ins):
            c.err(f"{rel}: no `AND Rx, R1` bit-isolation site found")

    def prev_write(self, ins: list[dict], idx: int, reg: str):
        """(index, instr) of the nearest instruction before `idx` that writes `reg`."""
        for j in range(idx - 1, -1, -1):
            if ins[j]["m"] in self.WRITES and ins[j]["ops"][0] == reg:
                return j, ins[j]
        return None, None

    def uart_rx_debug_value(self, text, ins, idx, mask_reg, mask, rx_port):
        """The set of values `OUT UIO_OUT, <reg>` at ins[idx] can write, when
        the source is one of the three recognised debug shapes; else None.

          constant     nearest write is `LDI reg, imm`           -> {imm}
          countdown    nearest write is `SUB reg, x` whose next
                       source line is `BNZ` (loop exits at zero) -> {0}
          frame error  IN reg, <RX port>; AND reg, M; XOR reg, M;
                       SHF reg, LEFT   (M = the RX mask register) -> {0, mask << 1}
        """
        reg = ins[idx]["ops"][1]
        j, w = self.prev_write(ins, idx, reg)
        if w is None:
            return None
        if w["m"] == "LDI":
            v = self.imm(w["ops"][1])
            return None if v is None else {v}
        if w["m"] == "SUB":
            following = [l.split(";", 1)[0].split() for l in text.splitlines()[w["no"]:]]
            nxt = next((t for t in following if t), None)
            return {0} if nxt and nxt[0].upper() == "BNZ" else None
        if w["m"] == "SHF" and w["ops"][1].upper() == "LEFT":
            j2, x = self.prev_write(ins, j, reg)
            j3, a = self.prev_write(ins, j2, reg) if x else (None, None)
            _j4, i = self.prev_write(ins, j3, reg) if a else (None, None)
            if (x and a and i and x["m"] == "XOR" and a["m"] == "AND" and i["m"] == "IN"
                    and x["ops"][1] == mask_reg and a["ops"][1] == mask_reg
                    and i["ops"][1].upper() == rx_port):
                return {0, (mask << 1) & 0xFF}
        return None

    def prof_uart_rx(self, rel, ent):
        """UART receive: RX sampled from the table's uart_rx.RX pin, the byte
        written to the uart_rx_result port.

        The RX programs also write `UIO_OUT` as a bench observability aid: a
        sample mark and a frame-error flag. Those are NOT pin roles, but they
        are checked: the table's `bench_debug.uart_rx` block names the two
        bits, every `OUT UIO_OUT` must be one of the recognised debug shapes
        (`uart_rx_debug_value`) and may only write 0, the mark bit, or the
        frame-error bit. Anything else -- the received byte in particular --
        is an error, and the received byte must reach the result port.

        These writes are electrically inert ONLY while the top level has
        `uio_oe = 8'h00`. Under DR 0010's proposed open-drain mask they would
        pull the open-drain uio pins low; `implementation()` reports that as
        an unmet prerequisite (DR 0010 "UART receive")."""
        text = self.read(rel, self.concrete)
        if text is None:
            return
        c = self.concrete
        ins = self.asm_instrs(text)
        _outs, in_ports, res = self.out_in_ports([], [("uart_rx", ["RX"])], "uart_rx_result")
        dbg = self.debug_bits.get("uart_rx")
        self.check_ports(rel, ins, res | ({"UIO_OUT"} if dbg else set()), in_ports, res, in_ports)
        mask = self.mask_of("uart_rx", "RX")
        first = next((i for i in ins if i["m"] == "LDI" and i["ops"][0] == "R1"), None)
        if first is None:
            c.err(f"{rel}: no `LDI R1, imm` RX bit-mask site found (pattern uart_rx_mask)")
        else:
            c.sites += 1
            v = self.imm(first["ops"][1])
            if v != mask:
                c.err(f"{rel}:{first['no']}: RX bit mask LDI R1, {first['ops'][1]} but the table's "
                      f"uart_rx RX pin {self.role_pin('uart_rx', 'RX')} is 0x{mask:02X}")
        self.check_mask_sites(rel, ins, {mask}, "UART RX")
        pb = self.role_pin("uart_rx", "RX")
        if pb is not None:
            before = c.sites
            self.in_and_sites(rel, ins, lambda _i: (mask, "uart_rx RX mask"),
                              port=PORT_ASM[(pb[0], "in")])
            if c.sites == before:
                c.err(f"{rel}: no `IN Rx, {PORT_ASM[(pb[0], 'in')]}` ... `AND Rx, Ry` RX sample site found")
        # the received byte: at least one OUT to the result port carries a
        # computed value (the initial `LDI 0` clear does not count)
        for port in sorted(res):
            c.sites += 1
            computed = False
            for idx, i in enumerate(ins):
                if i["m"] == "OUT" and i["ops"][0].upper() == port:
                    _j, w = self.prev_write(ins, idx, i["ops"][1])
                    computed |= w is not None and w["m"] != "LDI"
            if not computed:
                c.err(f"{rel}: no `OUT {port}, Rx` emits a received (computed) byte; only "
                      f"constants reach the uart_rx_result port (pattern uart_rx_debug)")
        if not dbg:
            return
        self.uart_rx_debug.setdefault(rel, set())
        mark, ferr = 1 << dbg["SAMPLE_MARK"], 1 << dbg["FRAME_ERROR"]
        rx_port = PORT_ASM[(pb[0], "in")] if pb else "UI_IN"
        seen = set()
        for idx, i in enumerate(ins):
            if not (i["m"] == "OUT" and i["ops"][0].upper() == "UIO_OUT"):
                continue
            c.sites += 1
            vals = self.uart_rx_debug_value(text, ins, idx, "R1", mask, rx_port)
            if vals is None:
                c.err(f"{rel}:{i['no']}: OUT UIO_OUT, {i['ops'][1]} is not a recognised bench-debug "
                      f"write (constant, countdown-to-zero, or the frame-error shape); the "
                      f"uart_rx profile allows only the sample mark and frame-error flag on "
                      f"uio_out, and the received byte belongs on the uart_rx_result port")
                continue
            bad = sorted(v for v in vals if v not in (0, mark, ferr))
            if bad:
                c.err(f"{rel}:{i['no']}: OUT UIO_OUT, {i['ops'][1]} writes "
                      f"{', '.join(f'0x{v:02X}' for v in bad)}; bench_debug.uart_rx allows only 0, "
                      f"SAMPLE_MARK 0x{mark:02X} and FRAME_ERROR 0x{ferr:02X}")
            seen |= vals
            self.uart_rx_debug[rel] |= vals
        for name, bit in (("SAMPLE_MARK", mark), ("FRAME_ERROR", ferr)):
            if bit not in seen:
                c.err(f"{rel}: no OUT UIO_OUT writes the declared {name} bit 0x{bit:02X} "
                      f"(pattern uart_rx_debug)")

    # ----------------------------------------------------------- profile: spi
    def prof_spi(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        c = self.concrete
        m = re.search(r"spi_mode([0-3])\.asm$", rel)
        if not m:
            c.err(f"{rel}: SPI profile file name must be spi_modeN.asm")
            return
        cpol = int(m.group(1)) >> 1
        ins = self.asm_instrs(text)
        outs, ins_p, res = self.out_in_ports(
            [("spi_transfer", ["CS", "SCLK", "MOSI"])], [("spi_transfer", ["MISO"])], "spi_result"
        )
        self.check_ports(rel, ins, outs | res, ins_p, outs, ins_p)
        cs = self.mask_of("spi_transfer", "CS")
        sclk = self.mask_of("spi_transfer", "SCLK")
        mosi = self.mask_of("spi_transfer", "MOSI")
        idle_s = sclk if cpol else 0
        allowed = {(idle_s ^ (sclk * a)) | (mosi * b) for a in (0, 1) for b in (0, 1)} | {cs | idle_s}
        pairs = [(a, b) for a, b in zip(ins, ins[1:])
                 if a["m"] == "LDI" and b["m"] == "OUT" and b["ops"][0].upper() == "UO_OUT"
                 and b["ops"][1] == a["ops"][0]]
        if not pairs:
            c.err(f"{rel}: no LDI -> OUT UO_OUT pin-image sites found (pattern spi_images)")
            return
        first_img = self.imm(pairs[0][0]["ops"][1])
        c.sites += 1
        if first_img != (cs | idle_s):
            c.err(f"{rel}:{pairs[0][0]['no']}: idle image {pairs[0][0]['ops'][1]} but the table "
                  f"(CS {self.role_pin('spi_transfer','CS')}, CPOL {cpol}) gives 0x{cs | idle_s:02X}")
        seen_sclk = seen_mosi = False
        for a, _b in pairs:
            v = self.imm(a["ops"][1])
            c.sites += 1
            if v not in allowed:
                c.err(f"{rel}:{a['no']}: pin image {a['ops'][1]} uses bits outside the table's "
                      f"CS/SCLK/MOSI pins (allowed images "
                      f"{sorted(f'0x{x:02X}' for x in allowed)})")
            seen_sclk |= v is not None and bool(v & sclk) != bool(idle_s)
            seen_mosi |= v is not None and bool(v & mosi)
        if not seen_sclk:
            c.err(f"{rel}: no image toggles the SCLK pin (table bit mask 0x{sclk:02X})")
        if not seen_mosi:
            c.err(f"{rel}: no image sets the MOSI pin (table bit mask 0x{mosi:02X})")
        miso = self.mask_of("spi_transfer", "MISO")
        self.in_and_sites(rel, ins, lambda i: (miso, "MISO pin mask"))
        if not any(i["m"] == "AND" for i in ins):
            c.err(f"{rel}: no MISO isolation AND site found (pattern spi_miso_mask)")

    # ----------------------------------------------------------- profile: i2c
    def i2c_checks(self, rel, ins, poll_label_prefix="poll", is_gen=False):
        c = self.concrete
        scl = self.mask_of("i2c_transfer", "SCL")
        sda = self.mask_of("i2c_transfer", "SDA")
        outs = [i for i in ins if i["m"] == "OUT" and i["ops"][0].upper() == "UIO_OUT"]
        # idle / START images: the two `LDI R3` immediately preceding the first two OUT UIO_OUT
        firsts = []
        for idx, i in enumerate(ins):
            if i in outs[:2]:
                prev = next((q for q in reversed(ins[:idx]) if q["m"] in self.WRITES
                             and q["ops"][0] == i["ops"][1]), None)
                firsts.append(prev)
        if len(firsts) < 2 or any(f is None or f["m"] != "LDI" for f in firsts):
            c.err(f"{rel}: cannot locate the idle/START `LDI R3` -> OUT UIO_OUT sites (pattern i2c_idle_start)")
        else:
            c.sites += 2
            idle, start = self.imm(firsts[0]["ops"][1]), self.imm(firsts[1]["ops"][1])
            if idle != (scl | sda):
                c.err(f"{rel}:{firsts[0]['no']}: bus-idle image {firsts[0]['ops'][1]} but the table's "
                      f"SCL|SDA (uio bits {self.role_pin('i2c_transfer','SCL')}, "
                      f"{self.role_pin('i2c_transfer','SDA')}) is 0x{scl | sda:02X}")
            if start != scl:
                c.err(f"{rel}:{firsts[1]['no']}: START image {firsts[1]['ops'][1]} (SCL high, SDA low) "
                      f"but the table's SCL mask is 0x{scl:02X}")
        # every adjacent LDI -> ALU mask is an SCL or SDA mask
        self.check_mask_sites(rel, ins, {scl, sda}, "I2C")
        # poll mask
        for idx, i in enumerate(ins):
            if i["m"] == "IN" and i["label"] and i["label"].startswith(poll_label_prefix):
                prev = next((q for q in reversed(ins[:idx]) if q["m"] == "LDI" and q["ops"][0] == "R3"), None)
                c.sites += 1
                if prev is None or self.imm(prev["ops"][1]) != scl:
                    c.err(f"{rel}:{i['no']}: SCL poll mask "
                          f"{prev['ops'][1] if prev else '(none)'} != table SCL mask 0x{scl:02X}")

    def prof_i2c(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        c = self.concrete
        ins = self.asm_instrs(text)
        outs, ins_p, res = self.out_in_ports(
            [("i2c_transfer", ["SCL", "SDA"])], [("i2c_transfer", ["SCL", "SDA"])], "i2c_result"
        )
        self.check_ports(rel, ins, outs | res, ins_p, outs, ins_p)
        self.i2c_checks(rel, ins)
        scl = self.mask_of("i2c_transfer", "SCL")
        sda = self.mask_of("i2c_transfer", "SDA")

        def want(i):
            if i["label"] and i["label"].startswith("poll"):
                return scl, "SCL poll mask"
            return sda, "SDA pin mask"

        self.in_and_sites(rel, ins, want)

    def prof_i2c_gen(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        try:
            ins = self.gen_instrs(text, rel)
        except SyntaxError as exc:
            self.concrete.err(f"{rel}: cannot parse generator: {exc}")
            return
        if not ins:
            self.concrete.err(f"{rel}: no instruction string literals found (pattern gen_strings)")
            return
        self.i2c_checks(rel, ins)

    def prof_demo(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        ins = self.asm_instrs(text)
        # generic ISA demo: whole-port use, no protocol pin roles asserted
        self.check_ports(rel, ins, {"UO_OUT"}, {"UI_IN"}, {"UO_OUT"}, {"UI_IN"})

    # ------------------------------------------------------- profile: benches
    def need(self, text, pattern, rel, what, flags=re.M):
        m = re.search(pattern, text, flags)
        if not m:
            self.concrete.err(f"{rel}: cannot find {what} (unsupported/missing extraction pattern)")
        else:
            self.concrete.sites += 1
        return m

    def check_pb(self, rel, what, port, bit, phase, role, bench_dirs=None):
        """Bench (port, bit) vs the table; bench ports uio_in/uio_out both mean uio."""
        want = self.role_pin(phase, role)
        norm = "uio" if port in ("uio_in", "uio_out") else port
        if want is None:
            self.concrete.err(f"{rel}: table has no {phase}.{role} pin to compare with {what}")
        elif (norm, bit) != want:
            self.concrete.err(
                f"{rel}: {what} is {port}[{bit}] but the table assigns {phase}.{role} to "
                f"{want[0]}[{want[1]}]"
            )

    def prof_bench_uart(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        m = self.need(text, r'^TX_PIN,\s*TX_BIT\s*=\s*"(\w+)",\s*(\d+)', rel, "TX_PIN, TX_BIT")
        if m:
            self.check_pb(rel, "TX_PIN/TX_BIT", m.group(1), int(m.group(2)), "uart_tx", "TX")

    def prof_bench_spi(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        m = self.need(text, r"^CS_BIT,\s*SCLK_BIT,\s*MOSI_BIT\s*=\s*(\d+),\s*(\d+),\s*(\d+)", rel,
                      "CS_BIT, SCLK_BIT, MOSI_BIT")
        if m:
            for name, val in zip(("CS", "SCLK", "MOSI"), m.groups()):
                self.check_pb(rel, f"{name}_BIT", "uo_out", int(val), "spi_transfer", name)
        m = self.need(text, r'^MISO_PIN,\s*MISO_BIT\s*=\s*"(\w+)",\s*(\d+)', rel, "MISO_PIN, MISO_BIT")
        if m:
            self.check_pb(rel, "MISO_PIN/MISO_BIT", m.group(1), int(m.group(2)), "spi_transfer", "MISO")
            if m.group(1) != "uio_in":
                self.concrete.err(f"{rel}: MISO_PIN {m.group(1)!r} must be the input path uio_in")
        for name in ("cs", "sclk", "mosi"):
            m = self.need(text, rf'"{name}":\s*\("(\w+)",\s*{name.upper()}_BIT\)', rel, f"{name} capture spec")
            if m and m.group(1) != "uo_out":
                self.concrete.err(f"{rel}: {name} captured on {m.group(1)}, table puts it on uo_out")
        m = self.need(text, r'specs\[f"uo\{i\}"\]\s*=\s*\("(\w+)",\s*i\)', rel, "result-byte capture")
        if m and m.group(1) != "uo_out":
            self.concrete.err(f"{rel}: RESULT bits captured on {m.group(1)}, table says uo_out")

    def prof_bench_i2c(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        for role in ("SCL", "SDA"):
            m = self.need(text, rf'^{role}_PIN,\s*{role}_BIT\s*=\s*"(\w+)",\s*(\d+)', rel,
                          f"{role}_PIN, {role}_BIT")
            if m:
                self.check_pb(rel, f"{role}_PIN/{role}_BIT", m.group(1), int(m.group(2)),
                              "i2c_transfer", role)
                if m.group(1) != "uio_out":
                    self.concrete.err(f"{rel}: {role}_PIN {m.group(1)!r}; controller intent is uio_out")
        scl, sda = self.mask_of("i2c_transfer", "SCL"), self.mask_of("i2c_transfer", "SDA")
        m = self.need(text, r"^_RELEASED\s*=\s*(0x[0-9A-Fa-f]+)", rel, "_RELEASED")
        if m and int(m.group(1), 16) != (scl | sda):
            self.concrete.err(f"{rel}: _RELEASED {m.group(1)} != table SCL|SDA 0x{scl | sda:02X}")
        m = self.need(text, r"^_ACK_PULL\s*=\s*(0x[0-9A-Fa-f]+)", rel, "_ACK_PULL")
        if m and int(m.group(1), 16) != scl:
            self.concrete.err(f"{rel}: _ACK_PULL {m.group(1)} != SCL-released/SDA-low 0x{scl:02X}")

    def prof_bench_i2c_sr(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        m = self.need(text, r"from test_firmware_i2c import \((.*?)^\)", rel,
                      "constant import from test_firmware_i2c", re.S | re.M)
        if m:
            body = re.sub(r"#[^\n]*", "", m.group(1))
            names = {n.strip() for n in body.split(",")}
            for n in ("SCL_BIT", "SCL_PIN", "SDA_BIT", "SDA_PIN"):
                if n not in names:
                    self.concrete.err(f"{rel}: does not import {n} from test_firmware_i2c "
                                      f"(would re-derive the pin)")
        scl, sda = self.mask_of("i2c_transfer", "SCL"), self.mask_of("i2c_transfer", "SDA")
        m = self.need(text, r"dut\.uio_in\.value\s*=\s*(0x[0-9A-Fa-f]+)", rel, "uio_in released literal")
        if m and int(m.group(1), 16) != (scl | sda):
            self.concrete.err(f"{rel}: uio_in released literal {m.group(1)} != table SCL|SDA 0x{scl | sda:02X}")
        m = self.need(text, r"dut\.uio_in\.value\s*=\s*\(sda_drive\s*<<\s*(\d+)\)\s*\|\s*scl_drive", rel,
                      "(sda_drive << N) | scl_drive composition")
        if m:
            self.check_pb(rel, "peripheral SDA drive shift", "uio_in", int(m.group(1)), "i2c_transfer", "SDA")
            if scl != 1:
                self.concrete.err(f"{rel}: scl_drive is composed unshifted (bit 0) but the table's "
                                  f"SCL mask is 0x{scl:02X}")
        for key in ("per_scl", "per_sda"):
            m = self.need(text, rf'"{key}":\s*\("(\w+)",\s*(SCL|SDA)_BIT\)', rel, f"{key} capture spec")
            if m and m.group(1) != "uio_in":
                self.concrete.err(f"{rel}: {key} captured on {m.group(1)}, peripheral intent is uio_in")

    def prof_bench_load(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        mode_pin = next((k for k, p in self.pins.items() if p["load_role"] == "PROG_MODE"), None)
        ser_pin = next((k for k, p in self.pins.items() if p["load_role"] == "PROG_SER"), None)
        m = re.search(r"async def load_program\(.*?(?=^async def |^def |\Z)", text, re.S | re.M)
        if not m:
            self.concrete.err(f"{rel}: cannot find load_program (pattern bench_load_pins)")
            return
        body = m.group(0)
        assigns = re.findall(r"dut\.ui_in\.value\s*=\s*([^#\n]+)", body)
        self.concrete.sites += len(assigns)
        mode_mask = 1 << mode_pin[1]
        ser_shift = ser_pin[1]
        mode_hi = self.need(body, r"dut\.ui_in\.value\s*=\s*(0x[0-9A-Fa-f]+)\s*#\s*MODE high", rel,
                            "MODE-high ui_in literal")
        if mode_hi and int(mode_hi.group(1), 16) != mode_mask:
            self.concrete.err(f"{rel}: MODE-high literal {mode_hi.group(1)} != table PROG_MODE "
                              f"ui_in[{mode_pin[1]}] mask 0x{mode_mask:02X}")
        comp = self.need(body, r"dut\.ui_in\.value\s*=\s*(0x[0-9A-Fa-f]+)\s*\|\s*(\(serial\s*<<\s*(\d+)\)|serial)",
                         rel, "`MODE | serial` composition")
        if comp:
            if int(comp.group(1), 16) != mode_mask:
                self.concrete.err(f"{rel}: load composition MODE literal {comp.group(1)} != "
                                  f"table PROG_MODE mask 0x{mode_mask:02X}")
            shift = int(comp.group(3)) if comp.group(3) else 0
            if shift != ser_shift:
                self.concrete.err(f"{rel}: serial data driven on ui_in[{shift}] but the table's "
                                  f"PROG_SER is ui_in[{ser_shift}]")
        drop = self.need(body, r"dut\.ui_in\.value\s*=\s*(0x[0-9A-Fa-f]+)\s*#\s*MODE drop", rel,
                         "MODE-drop ui_in literal")
        if drop and int(drop.group(1), 16) & mode_mask:
            self.concrete.err(f"{rel}: MODE-drop literal {drop.group(1)} still sets the PROG_MODE bit")

    def prof_top(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        for pat, role in ((r"\.mode_pin\s*\(\s*ui_in\[(\d+)\]\s*\)", "PROG_MODE"),
                          (r"\.serial_in\s*\(\s*ui_in\[(\d+)\]\s*\)", "PROG_SER")):
            m = self.need(text, pat, rel, f"{role} connection", re.M)
            want = next((k for k, p in self.pins.items() if p["load_role"] == role), None)
            if m and want != ("ui_in", int(m.group(1))):
                self.meta.err(f"{rel}: {role} wired to ui_in[{m.group(1)}] but the table says "
                              f"{want[0]}[{want[1]}]")
        for port in ("ui_in", "uio_in", "uo_out", "uio_out"):
            m = re.search(rf"\.port_{port}\s*\(\s*(\w+)\s*\)", text)
            self.meta.sites += 1
            if not m or m.group(1) != port:
                self.meta.err(f"{rel}: core port_{port} is not connected to the whole {port} bus")
        m = re.search(r"assign\s+uio_oe\s*=\s*([^;]+);", text)
        self.top_text = text
        self.uio_oe_expr = m.group(1).strip() if m else None
        if m is None:
            self.concrete.err(f"{rel}: no `assign uio_oe = ...;` found (pattern top_uio_oe)")

    def prof_core(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        self.core_text = text
        m = re.search(r"port_uio_out\s*<=\s*8'h([0-9A-Fa-f]{2})\s*;", text)
        self.uio_out_reset = int(m.group(1), 16) if m else None
        if m is None:
            self.concrete.err(f"{rel}: no `port_uio_out <= 8'hXX;` reset literal (pattern core_uio_out_reset)")

    def prof_isa_ports(self, rel, ent):
        text = self.read(rel, self.concrete)
        if text is None:
            return
        for name, code in ISA_PORT_CODES.items():
            m = re.search(rf'"{name}":\s*\(0b([01]{{2}}),', text)
            self.concrete.sites += 1
            if not m or int(m.group(1), 2) != code:
                self.concrete.err(f"{rel}: ISA port {name} is not code {code:02b} "
                                  f"(info.yaml labels port codes 00/01/10/11)")

    # ------------------------------------------------------------- metadata
    def prof_info(self, rel, ent):
        text = self.read(rel, self.meta)
        if text is None:
            return
        m = self.meta
        block = re.search(r"^pinout:\s*\n(.*?)^yaml_version", text, re.S | re.M)
        if not block:
            m.err(f"{rel}: no pinout block found (pattern info_pinout)")
            return
        section = None
        seen: dict[str, str] = {}
        sect_for = {"Inputs": "ui", "Outputs": "uo", "Bidirectional pins": "uio"}
        for line in block.group(1).splitlines():
            h = re.match(r"^\s*#\s*(Inputs|Outputs|Bidirectional pins)\s*$", line)
            if h:
                section = sect_for[h.group(1)]
                continue
            k = re.match(r'^\s{2}((?:ui|uo|uio)\[(\d+)\]):\s*"(.*)"\s*$', line)
            if not k:
                continue
            key, desc = k.group(1), k.group(3)
            if key in seen:
                m.err(f"{rel}: duplicate pinout key {key}")
            seen[key] = desc
            if section != re.match(r"[a-z]+", key).group(0):
                m.err(f"{rel}: {key} sits under the wrong direction section ({section!r})")
        expected = {f"{p}[{b}]" for p in ("ui", "uo", "uio") for b in range(8)}
        for key in sorted(expected - set(seen)):
            m.err(f"{rel}: pinout key {key} missing (exactly 24 keys required)")
        for key in sorted(set(seen) - expected):
            m.err(f"{rel}: unexpected pinout key {key}")
        generic = {"ui_in": "ISA input port 00 bit {b}", "uo_out": "ISA output port 10 bit {b}",
                   "uio": "ISA input port 01 bit {b}"}
        short = {"ui_in": "ui", "uo_out": "uo", "uio": "uio"}
        for (port, bit), pin in sorted(self.pins.items()):
            key = f"{short[port]}[{bit}]"
            desc = seen.get(key)
            if desc is None:
                continue
            m.sites += 1
            want = generic[port].format(b=bit)
            if want not in desc:
                m.err(f"{rel}: {key} lacks the generic ISA capability label {want!r}")
            for role in ("PROG_SER", "PROG_MODE"):
                has = role in desc
                if has != (pin["load_role"] == role):
                    m.err(f"{rel}: {key} {'names' if has else 'omits'} {role} but the table's "
                          f"load_role is {pin['load_role']!r}")
            claimed = set(re.findall(r"\b(TX|RX|SCLK|MOSI|MISO|CS|SCL|SDA)\b", desc))
            have = {r for r in pin["protocol_roles"].values() if r != UNUSED}
            for tok in sorted(claimed - have):
                m.err(f"{rel}: {key} claims protocol role {tok} but the table does not assign it "
                      f"to {port}[{bit}] (generic metadata must not assert concrete roles)")
        m.notes.append(
            "info.yaml labels are generic ISA capabilities; they are not evidence that any "
            "UART/SPI/I2C assignment or open-drain pad is implemented."
        )

    # -------------------------------------------------------- implementation
    def implementation(self) -> None:
        expr = getattr(self, "uio_oe_expr", None)
        pp, od = self.pp_mask, self.od_mask
        lit = re.fullmatch(r"(?:8)?'h([0-9A-Fa-f]+)|(\d+)'h([0-9A-Fa-f]+)", expr or "")
        if expr is None:
            self.unwired.append("uio_oe: no assignment found; every proposed uio electrical role is unwired")
            return
        if lit:
            val = int((lit.group(1) or lit.group(3)), 16)
            for bit in range(8):
                role = self.pins[("uio", bit)]["electrical_role"]
                bitset = (val >> bit) & 1
                if role == "open_drain":
                    self.unwired.append(
                        f"uio[{bit}] open_drain: needs uio_oe[{bit}] = ~uio_out[{bit}]; top level has "
                        f"`uio_oe = {expr}`")
                elif role == "push_pull" and not bitset:
                    self.unwired.append(f"uio[{bit}] push_pull: needs uio_oe[{bit}] = 1; top level has `uio_oe = {expr}`")
                elif role == "input" and bitset:
                    self.concrete.err(
                        f"src top: uio[{bit}] is an input in the table but uio_oe = {expr} drives it")
        elif "uio_od" in expr or "uio_dir" in expr:
            # the DR 0012 shape: pin mode is two runtime control registers
            # (issue #135). See runtime_pin_mode().
            self.runtime_pin_mode(expr)
            return
        elif "uio_out" in expr:
            # the DR 0008 shape: PUSH_PULL | (OPEN_DRAIN & ~uio_out)
            if f"{od:02X}".lower() not in expr.lower() or "~" not in expr:
                self.unwired.append(f"uio_oe expression `{expr}` does not visibly realise open-drain mask 0x{od:02X}")
        else:
            self.concrete.err(f"top-level `uio_oe = {expr}` is an unsupported extraction pattern")
        reset = getattr(self, "uio_out_reset", None)
        if od and reset is not None and (reset & od) != od:
            self.unwired.append(
                f"prerequisite: port_uio_out resets to 8'h{reset:02X}; open-drain pins (mask "
                f"0x{od:02X}) must reset to 1 (released) or the pad asserts low from reset"
            )

        # UART RX bench-debug writes: every write leaves the open-drain bits it
        # does not set at 0, which under `uio_oe = od & ~uio_out` asserts them.
        if od and self.uart_rx_debug:
            always = od
            sometimes = 0
            for vals in self.uart_rx_debug.values():
                for v in vals:
                    always &= ~v
                    sometimes |= od & ~v
            sometimes &= ~always
            names = lambda m: ", ".join(f"uio[{b}]" for b in range(8) if (m >> b) & 1) or "none"
            self.unwired.append(
                f"prerequisite: {len(self.uart_rx_debug)} uart_rx program(s) write bench-debug "
                f"values to UIO_OUT; under the open-drain mask 0x{od:02X} that asserts low "
                f"continuously: {names(always)}; except while a debug bit is set: "
                f"{names(sometimes)}. Inert only while uio_oe is 8'h00 -- move or remove the "
                f"debug writes, or make the mask per-image (DR 0012), before the uio_oe wiring lands"
            )

    DR0012_UIO_OE = "(uio_od&~uio_out)|(~uio_od&uio_dir)"

    def runtime_pin_mode(self, expr: str) -> None:
        """DR 0012 (issue #135): `uio_oe` is driven by the core's `UIO_OD` /
        `UIO_DIR` control registers, so no electrical role is wired at
        synthesis time. What can still drift, and is checked here:

        - the top-level expression is DR 0012's pin-mode rule (open-drain
          wins, then push-pull, else input) -- anything else is an error;
        - both registers reset to 0, so every uio pin is an input from
          reset (an error otherwise: a pin would be driven before any
          program asked);
        - each open-drain role in the table is a *firmware* convention:
          every inventoried assembly file that drives `UIO_OUT` in an I2C
          phase must set the table's open-drain mask with `WCTL UIO_OD`,
          and must have released the lines (`OUT UIO_OUT`) first, because
          `uio_out` resets to 0 and open-drain on a 0 pulls the pad low.
          A file that does not is reported as unwired, not as an error.

        The DR 0008 prerequisite "uio_out must reset released" does not
        apply in this shape: the pins are inputs at reset whatever
        `uio_out` holds."""
        if re.sub(r"\s+", "", expr) != self.DR0012_UIO_OE:
            self.concrete.err(
                f"top-level `uio_oe = {expr}` is not DR 0012's pin-mode rule "
                "`(uio_od & ~uio_out) | (~uio_od & uio_dir)`")
        core = getattr(self, "core_text", None) or ""
        for reg in ("uio_dir", "uio_od"):
            self.concrete.sites += 1
            m = re.search(rf"\b{reg}\s*<=\s*8'h([0-9A-Fa-f]{{2}})\s*;", core)
            if not m:
                self.concrete.err(f"core: no `{reg} <= 8'hXX;` reset literal found (DR 0012 reset value)")
            elif int(m.group(1), 16) != 0:
                self.concrete.err(
                    f"core: {reg} resets to 8'h{m.group(1)}; DR 0012 requires 0 (every uio pin an input at reset)")
        od = self.od_mask
        if not od:
            return
        asm_dir = self.root / "firmware" / "asm"
        # UART RX bench-debug writes to UIO_OUT (issue #154). Under a
        # synthesis-time open-drain mask they would pull uio pins low (the
        # prerequisite reported in the other shapes). Under DR 0012 they
        # enable no pin as long as the program never writes a pin-mode
        # register, so that -- not the write itself -- is what is checked.
        for rel in sorted(getattr(self, "uart_rx_debug", {}) or {}):
            text = self.read(rel, self.concrete)
            if text is None:
                continue
            self.concrete.sites += 1
            modes = sorted({x["ops"][0].upper() for x in self.asm_instrs(text)
                            if x["m"] == "WCTL" and x["ops"][0].upper() in ("UIO_OD", "UIO_DIR", "0X00", "0X01")})
            if modes:
                self.unwired.append(
                    f"prerequisite: {rel} writes bench-debug values to UIO_OUT and also writes "
                    f"{', '.join(modes)}: the debug values would reach uio pads (DR 0012; issue #154)")
        for path in sorted(asm_dir.glob("i2c_*.asm")) if asm_dir.is_dir() else []:
            rel = str(path.relative_to(self.root))
            ins = self.asm_instrs(path.read_text(encoding="utf-8"))
            site = next((i for i, x in enumerate(ins)
                         if x["m"] == "WCTL" and x["ops"][0].upper() == "UIO_OD"), None)
            if site is None:
                self.unwired.append(
                    f"{rel}: drives open-drain pins (mask 0x{od:02X}) but has no `WCTL UIO_OD` "
                    "(DR 0012: the pins stay inputs and the bus is never pulled low)")
                continue
            reg = ins[site]["ops"][1]
            val = next((self.imm(x["ops"][1]) for x in reversed(ins[:site])
                        if x["m"] == "LDI" and x["ops"][0] == reg), None)
            if val != od:
                self.unwired.append(
                    f"{rel}: `WCTL UIO_OD` writes {val if val is None else hex(val)}, "
                    f"table open-drain mask is 0x{od:02X}")
            released = any(x["m"] == "OUT" and x["ops"] == ["UIO_OUT", reg] for x in ins[:site])
            if not released:
                self.unwired.append(
                    f"{rel}: `WCTL UIO_OD` precedes the first `OUT UIO_OUT` (uio_out resets to 0: "
                    "the open-drain pins would be pulled low until released)")

    # -------------------------------------------------------------------- run
    def run(self) -> None:
        if not self.load_table():
            return
        self.run_inventory()
        # load/top/core fill state used by the implementation layer
        self.implementation()

    def summary(self) -> dict:
        return {
            "record": self.record,
            "layers": {
                l.name: {"ok": l.ok, "sites_checked": l.sites, "errors": l.errors, "notes": l.notes}
                for l in (self.schema, self.meta, self.concrete)
            },
            "unwired_electrical_roles": self.unwired,
            "open_drain_mask": f"0x{getattr(self, 'od_mask', 0):02X}",
        }


def format_text(ck: Checker, require_implemented: bool) -> str:
    out = [f"protocol pin-role check against {ck.record}"]
    for l in (ck.schema, ck.meta, ck.concrete):
        out.append(f"[{l.name}] {'PASS' if l.ok else 'FAIL'} ({l.sites} site(s) checked)")
        for e in l.errors:
            out.append(f"    ERROR: {e}")
        for n in l.notes:
            out.append(f"    note: {n}")
    out.append(f"[implementation] {'COMPLETE' if not ck.unwired else 'INCOMPLETE'}: "
               f"{len(ck.unwired)} proposed electrical role(s)/prerequisite(s) not wired")
    for u in ck.unwired:
        out.append(f"    unwired: {u}")
    consistent = ck.schema.ok and ck.meta.ok and ck.concrete.ok
    out.append(f"consistency (schema + metadata + concrete): {'PASS' if consistent else 'FAIL'}")
    if require_implemented:
        out.append(f"--require-implemented: {'PASS' if not ck.unwired else 'FAIL'}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--record", default=DEFAULT_RECORD, help="decision record carrying the table")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--require-implemented", action="store_true",
                    help="also fail while any proposed electrical role is unwired")
    args = ap.parse_args(argv)
    root = Path(args.repo_root)
    if not root.is_dir():
        print(f"error: --repo-root {root} is not a directory", file=sys.stderr)
        return 2
    ck = Checker(root, args.record)
    ck.run()
    if args.format == "json":
        print(json.dumps(ck.summary(), indent=2))
    else:
        print(format_text(ck, args.require_implemented))
    ok = ck.schema.ok and ck.meta.ok and ck.concrete.ok
    if args.require_implemented and (ck.unwired or not ok):
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
