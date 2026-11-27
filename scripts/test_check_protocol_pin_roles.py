#!/usr/bin/env python3
"""Self-test for `scripts/check_protocol_pin_roles.py`.

The checker is the only mechanical link between the pin-role table in
`spec/decision-records/0010-protocol-pin-roles.md` and the places the
repository encodes pin assignments. A checker that silently stops noticing a
moved pin is worse than none, so every class of drift gets an executable case
that edits the REAL assignment site (an `LDI` immediate in an assembly file, a
bench constant, a generator string literal, a port connection in the top
level, an `info.yaml` key) -- not a comment.

Method (the same shape as `scripts/test_check_ratification_gate.py`): copy the
files the shipped table inventories into a throwaway tree, apply one mutation,
run the REAL shipped script as a subprocess against it via `--repo-root`, and
assert on the exit code and the diagnostic. Nothing is monkeypatched.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/test_check_protocol_pin_roles.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKER = SCRIPT_DIR / "check_protocol_pin_roles.py"
REPO_ROOT = SCRIPT_DIR.parent
RECORD = "spec/decision-records/0010-protocol-pin-roles.md"
FENCE = re.compile(r"(^```json pin-roles[ \t]*\n)(.*?)(^```[ \t]*$)", re.M | re.S)

_results: list[tuple[str, bool, str]] = []


def real_table() -> dict:
    text = (REPO_ROOT / RECORD).read_text(encoding="utf-8")
    return json.loads(FENCE.search(text).group(2))


def load_checker():
    """The shipped checker as a module object, imported by path because
    `python3 -I` does not put `scripts/` on `sys.path`; importing runs no check."""
    spec = importlib.util.spec_from_file_location("check_protocol_pin_roles", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fixture:
    """A throwaway tree holding exactly the inventoried files plus the record."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {RECORD} | {e["file"] for e in real_table()["inventory"]}
        for rel in sorted(files):
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dst)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def mutate(self, rel: str, old: str, new: str, count: int = 1) -> None:
        """Replace `old` with `new` in a fixture file; `old` MUST exist (so a
        refactor of the real source cannot turn a case into a no-op)."""
        p = self.path(rel)
        text = p.read_text(encoding="utf-8")
        assert old in text, f"mutation anchor {old!r} not found in {rel}"
        p.write_text(text.replace(old, new, count), encoding="utf-8")

    def mutate_table(self, fn) -> None:
        p = self.path(RECORD)
        text = p.read_text(encoding="utf-8")
        table = json.loads(FENCE.search(text).group(2))
        fn(table)
        p.write_text(
            FENCE.sub(lambda m: m.group(1) + json.dumps(table, indent=1) + "\n" + m.group(3), text, count=1),
            encoding="utf-8",
        )

    def run(self, *extra: str) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, "-I", str(CHECKER), "--repo-root", str(self.root), *extra],
            capture_output=True, text=True, check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def close(self) -> None:
        self.tmp.cleanup()


def pin(table: dict, label: str) -> dict:
    return next(p for p in table["pins"] if p["pin"] == label)


def case(name: str):
    def deco(fn):
        def runner():
            fx = Fixture()
            try:
                fn(fx)
                _results.append((name, True, ""))
            except AssertionError as exc:
                _results.append((name, False, str(exc)))
            finally:
                fx.close()
        runner.case_name = name
        CASES.append(runner)
        return runner
    return deco


CASES: list = []


def expect_fail(fx: Fixture, needle: str, layer: str | None = None, *extra: str) -> None:
    code, out = fx.run(*extra)
    assert code == 1, f"expected exit 1, got {code}:\n{out}"
    assert needle in out, f"diagnostic {needle!r} missing from:\n{out}"
    if layer:
        assert f"[{layer}] FAIL" in out, f"layer {layer} did not fail:\n{out}"


def concrete_mutation_case(
    name: str, rel: str, old: str, new: str, needle: str
) -> None:
    @case(name)
    def check(fx: Fixture) -> None:
        fx.mutate(rel, old, new)
        expect_fail(fx, needle, "concrete-firmware-bench")


def expect_ordered(fx: Fixture, *needles: str) -> None:
    """The run fails with every `needle` among the concrete layer's
    diagnostics, in this order."""
    code, out = fx.run()
    assert code == 1, f"expected exit 1, got {code}:\n{out}"
    assert "[concrete-firmware-bench] FAIL" in out, f"layer concrete-firmware-bench did not fail:\n{out}"
    at = [out.find(f"ERROR: {n}") for n in needles]
    missing = [n for n, i in zip(needles, at) if i < 0]
    assert not missing, f"diagnostic(s) {missing} missing from:\n{out}"
    assert at == sorted(at), f"diagnostics out of order {list(zip(needles, at))} in:\n{out}"


def expect_vocabulary_errors(fx: Fixture, phases: list[str]) -> None:
    code, out = fx.run()
    assert code == 1, f"expected exit 1, got {code}:\n{out}"
    assert "[schema] FAIL" in out, out
    reported = re.findall(
        r"ERROR: table\.phases\.(\w+): roles .*supported vocabulary\b", out
    )
    assert reported == phases, (
        f"expected vocabulary errors for {phases}, got {reported}:\n{out}"
    )


# ---------------------------------------------------------------- baseline
# Issue #135 (DR 0012): the committed top level now derives uio_oe from the
# core's UIO_OD / UIO_DIR control registers, and the committed I2C programs
# set the table's open-drain mask with `WCTL UIO_OD`. So the committed tree
# is implementation-COMPLETE, and the cases that used to start from
# `assign uio_oe = 8'h00;` first put that synthesis-time shape back.
TOP = "src/tt_um_2amlogic_protocol_emulator.v"
RUNTIME_OE = "assign uio_oe  = (uio_od & ~core_uio_out) | (~uio_od & uio_dir);"
# DR 0020 (issue #244): the pad data of an open-drain pin is tied to 0.
PAD_DATA = "assign uio_out = core_uio_out & ~uio_od;"


@case("committed tree: consistency passes, runtime pin mode is complete")
def _(fx):
    code, out = fx.run()
    assert code == 0, out
    for layer in ("schema", "metadata-capability", "concrete-firmware-bench"):
        assert f"[{layer}] PASS" in out, out
    assert "[implementation] COMPLETE" in out, out
    # DR 0012: the UART RX bench-debug writes (issue #154) enable no pin,
    # because those programs write no pin-mode register.
    assert "uart_rx program(s) write bench-debug values" not in out, out
    code, out = fx.run("--require-implemented")
    assert code == 0 and "--require-implemented: PASS" in out, out


@case("synthesis-time uio_oe = 0: consistency passes, implementation incomplete")
def _(fx):
    # Issue #155: SPI and I2C sit on uio[0..3], whose electrical role is set
    # per firmware image (`runtime`). No synthesis-time uio_oe can serve them.
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = 8'h00;")
    code, out = fx.run()
    assert code == 0, out
    assert "[implementation] INCOMPLETE: 4" in out, out
    for bit in range(4):
        assert f"uio[{bit}] runtime: its electrical role is set per firmware image" in out, out
    # no pin is a fixed open-drain pin any more, so the UART RX debug
    # writes are no hazard under this shape and uio_out's reset is moot
    assert "uart_rx program(s) write bench-debug values" not in out, out
    assert "port_uio_out resets" not in out, out


concrete_mutation_case(
    "runtime pin mode: a top-level uio_oe that is not DR 0012's rule fails",
    TOP,
    RUNTIME_OE,
    # open-drain no longer wins over push-pull
    "assign uio_oe = (uio_od & ~core_uio_out) | uio_dir;",
    "is not DR 0012's pin-mode rule",
)


@case("DR 0020: the pre-#244 wiring (uio_oe from the pad data) is refused by name")
def _(fx):
    # The old top: the core's register straight onto the pads and the
    # open-drain enable derived from it. Under routed delays the pad saw
    # oe=1 with out=1 for about 100 ps on every release.
    fx.mutate(TOP, ".port_uio_out(core_uio_out),", ".port_uio_out(uio_out),")
    fx.mutate(TOP, PAD_DATA + "\n", "")
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);")
    expect_fail(fx, "is the pre-DR-0020 wiring", "concrete-firmware-bench")


@case("DR 0020: pad data that is not masked by ~uio_od fails")
def _(fx):
    # uio_oe is right but an open-drain pin's pad data still follows the
    # register, so the release race of issue #244 is back.
    fx.mutate(TOP, PAD_DATA, "assign uio_out = core_uio_out;")
    expect_fail(fx, "the top must have `assign uio_out = core_uio_out & ~uio_od;`",
                "metadata-capability")


@case("DR 0020: pad data masked on only some pins fails")
def _(fx):
    fx.mutate(TOP, PAD_DATA, "assign uio_out = core_uio_out & ~(uio_od & 8'h0C);")
    expect_fail(fx, "the top must have `assign uio_out = core_uio_out & ~uio_od;`",
                "metadata-capability")


# Issue #137 (DR 0013 layer 1): outside the run phase uo_out shows the load
# CRC, so the core's port reaches uo_out through a mux. The check accepts
# exactly one shape of it -- the run-phase arm is the core's port, whole.
UO_MUX_HEAD = "assign uo_out = run_phase ? core_uo_out :"


@case("load CRC readout: the committed run_phase mux on uo_out is accepted")
def _(fx):
    assert UO_MUX_HEAD in fx.path(TOP).read_text(encoding="utf-8"), (
        "fixture premise: the committed top has the readout mux")
    code, out = fx.run()
    assert code == 0 and "[metadata-capability] PASS" in out, out


@case("load CRC readout: a direct core-to-uo_out connection fails while the table declares CRC_READOUT")
def _(fx):
    # no special case for the readout: the table says uo_out is read out in load
    fx.mutate(TOP, ".port_uo_out (core_uo_out),", ".port_uo_out (uo_out),")
    fx.mutate(TOP, UO_MUX_HEAD, "wire [7:0] unused_readout = run_phase ? core_uo_out :")
    expect_fail(fx, "the table gives uo_out the CRC_READOUT load role", "metadata-capability")


@case("load CRC readout: a direct connection is accepted when the table has no readout roles")
def _(fx):
    fx.mutate(TOP, ".port_uo_out (core_uo_out),", ".port_uo_out (uo_out),")
    fx.mutate(TOP, UO_MUX_HEAD, "wire [7:0] unused_readout = run_phase ? core_uo_out :")

    def drop(t):
        for k in ("ui_in[1]",) + tuple(f"uo_out[{b}]" for b in range(8)):
            pin(t, k)["load_role"] = "none"
    fx.mutate_table(drop)
    code, out = fx.run()
    assert code == 0 and "[metadata-capability] PASS" in out, out


@case("load CRC readout: a byte select on a pin other than the table's CRC_BYTE_SEL fails")
def _(fx):
    fx.mutate(TOP, "ui_in[1]  ? pm_crc[15:8] :", "ui_in[2]  ? pm_crc[15:8] :")
    expect_fail(fx, "the table gives uo_out the CRC_READOUT load role", "metadata-capability")


@case("load CRC readout: CRC_READOUT on a partial uo_out bus fails the schema")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uo_out[7]").update(load_role="none"))
    expect_fail(fx, "CRC_READOUT placed on", "schema")


@case("load CRC readout: CRC_BYTE_SEL without the readout fails the schema")
def _(fx):
    fx.mutate_table(lambda t: [pin(t, f"uo_out[{b}]").update(load_role="none") for b in range(8)])
    expect_fail(fx, "need the whole readout with exactly one byte-select pin", "schema")


@case("load CRC readout: CRC_READOUT on an input pin fails the schema")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "ui_in[3]").update(load_role="CRC_READOUT"))
    expect_fail(fx, "load role CRC_READOUT must be on uo_out", "schema")


@case("load CRC readout: a mux not selected by run_phase fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = !ui_in[7] ? core_uo_out :")
    expect_fail(fx, "the table gives uo_out the CRC_READOUT load role",
                "metadata-capability")


@case("load CRC readout: a run-phase arm that is not the core's port fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = run_phase ? (core_uo_out & 8'h7F) :")
    expect_fail(fx, "the table gives uo_out the CRC_READOUT load role",
                "metadata-capability")


@case("load CRC readout: the core's port left off uo_out altogether fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = run_phase ? pm_crc[7:0] :")
    expect_fail(fx, "the table gives uo_out the CRC_READOUT load role",
                "metadata-capability")


concrete_mutation_case(
    "runtime pin mode: a pin-mode register that does not reset to 0 fails",
    "rtl/protocol_core.v",
    "uio_od       <= 8'h00;",
    "uio_od       <= 8'h81;",
    "uio_od resets to 8'h81",
)


@case("runtime pin mode: an I2C program without the WCTL UIO_OD preamble is unwired")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast.asm",
              "        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)\n", "")
    code, out = fx.run()
    assert code == 0 and "[implementation] INCOMPLETE: 1" in out, out
    assert "i2c_fast.asm: drives open-drain pins (mask 0x0C) but has no `WCTL UIO_OD`" in out, out
    code, out = fx.run("--require-implemented")
    assert code == 1 and "--require-implemented: FAIL" in out, out


@case("runtime pin mode: WCTL UIO_OD before the releasing OUT is unwired")
def _(fx):
    fx.mutate("firmware/asm/i2c_std.asm",
              "        OUT   UIO_OUT, R3\n        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)\n",
              "        WCTL  UIO_OD, R3\n        OUT   UIO_OUT, R3\n")
    code, out = fx.run()
    assert code == 0 and "i2c_std.asm: `WCTL UIO_OD` precedes the first `OUT UIO_OUT`" in out, out


@case("runtime pin mode: a WCTL UIO_OD mask that differs from the table is unwired")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast_sr.asm",
              "        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)\n",
              "        LDI   R2, 0x80\n        WCTL  UIO_OD, R2\n")
    code, out = fx.run()
    assert code == 0 and "i2c_fast_sr.asm: `WCTL UIO_OD` writes 0x80" in out, out


@case("runtime pin mode: a source register overwritten between its LDI and the WCTL is unwired")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast.asm",
              "        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)\n",
              "        XOR   R3, R3\n        WCTL  UIO_OD, R3\n")
    code, out = fx.run()
    assert code == 0 and "[implementation] INCOMPLETE: 1" in out, out
    assert "i2c_fast.asm: `WCTL UIO_OD` writes None, table open-drain mask is 0x0C" in out, out
    code, out = fx.run("--require-implemented")
    assert code == 1 and "--require-implemented: FAIL" in out, out


@case("runtime pin mode: the WCTL source register matches its writer in either case")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast.asm",
              "        WCTL  UIO_OD, R3      ; DR 0012: SCL|SDA open-drain (after the OUT)\n",
              "        WCTL  UIO_OD, r3\n")
    code, out = fx.run("--require-implemented")
    assert code == 0 and "[implementation] COMPLETE: 0" in out, out


@case("runtime pin mode: an SPI program without the WCTL UIO_DIR preamble is unwired")
def _(fx):
    fx.mutate("firmware/asm/spi_mode2.asm",
              "        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]\n", "")
    code, out = fx.run()
    assert code == 0 and "[implementation] INCOMPLETE: 1" in out, out
    assert "spi_mode2.asm: drives push-pull pins (mask 0x0B) but has no `WCTL UIO_DIR`" in out, out
    code, out = fx.run("--require-implemented")
    assert code == 1 and "--require-implemented: FAIL" in out, out


@case("runtime pin mode: SPI WCTL UIO_DIR before the idle image, or with the wrong mask, is unwired")
def _(fx):
    fx.mutate("firmware/asm/spi_mode0.asm",
              "        LDI   R2, 0x01          ; CS released, SCLK at CPOL idle\n"
              "        OUT   UIO_OUT, R2       ; the idle image, BEFORE the drivers are on\n"
              "        LDI   R3, 0x0B          ; CS|MOSI|SCLK: the pins this program drives\n"
              "        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]\n",
              "        LDI   R3, 0x0F\n        WCTL  UIO_DIR, R3\n"
              "        LDI   R2, 0x01\n        OUT   UIO_OUT, R2\n")
    code, out = fx.run()
    assert code == 0, out
    assert "spi_mode0.asm: `WCTL UIO_DIR` precedes the first `OUT UIO_OUT`" in out, out
    assert "spi_mode0.asm: `WCTL UIO_DIR` writes 0xf, table push-pull mask is 0x0B" in out, out


@case("runtime pin mode: an SPI program that also writes UIO_OD is unwired")
def _(fx):
    fx.mutate("firmware/asm/spi_mode1.asm",
              "        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]\n",
              "        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]\n"
              "        WCTL  UIO_OD, R3\n")
    code, out = fx.run()
    assert "spi_mode1.asm: writes UIO_OD, but the table's spi profile drives no open-drain pin" in out, out


@case("runtime pin mode: a UART RX program that also enables a uio pin is a hazard")
def _(fx):
    # Issue #154: the RX bench-debug writes to UIO_OUT are inert under DR 0012
    # only while the program writes no pin-mode register.
    p = fx.path("firmware/asm/uart_rx.asm")
    text = p.read_text(encoding="utf-8")
    anchor = next(l for l in text.splitlines() if l.strip().startswith("LDI"))
    fx.mutate("firmware/asm/uart_rx.asm", anchor + "\n", anchor + "\n        WCTL  UIO_OD, R1\n")
    code, out = fx.run()
    assert "uart_rx.asm writes bench-debug values to UIO_OUT and also writes UIO_OD" in out, out
    assert "[implementation] INCOMPLETE" in out, out


@case("--require-implemented fails while uio_oe = 0")
def _(fx):
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = 8'h00;")
    code, out = fx.run("--require-implemented")
    assert code == 1 and "--require-implemented: FAIL" in out, out


@case("DR 0008's synthesis-time mask cannot serve the runtime pins")
def _(fx):
    # Issue #155 retired the cases that wired DR 0008's 0x81 mask: the table
    # has no fixed open-drain pin left, so SPI and I2C need DR 0012.
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = 8'h00 | (8'h81 & ~uio_out);")
    code, out = fx.run("--require-implemented")
    assert code == 1 and "[implementation] INCOMPLETE: 4" in out, out
    assert "DR 0008's synthesis-time mask cannot serve it" in out, out


concrete_mutation_case(
    "a top-level uio_oe that drives a table input pin fails",
    TOP,
    RUNTIME_OE,
    "assign uio_oe = 8'h10;",
    "uio[4] is an input in the table",
)


@case("no broad allow-mismatch switch exists")
def _(fx):
    fx.mutate("firmware/asm/uart_tx.asm", "LDI   R1, 1 ", "LDI   R1, 2 ")
    for flag in ("--allow-mismatch", "--ignore-mismatch", "--allow"):
        code, out = fx.run(flag)
        assert code == 2, f"{flag} should be a usage error, got {code}"


# ----------------------------------------------- concrete: assembly sites
concrete_mutation_case(
    "UART TX mask LDI mutated",
    "firmware/asm/uart_tx.asm",
    "LDI   R1, 1 ",
    "LDI   R1, 2 ",
    "firmware/asm/uart_tx.asm",
)

concrete_mutation_case(
    "UART program gains an OUT to uio_out",
    "firmware/asm/uart_tx.asm",
    "OUT   UO_OUT, R1       ; TX idles HIGH",
    "OUT   UIO_OUT, R1       ; TX idles HIGH",
    "OUT to port UIO_OUT",
)

concrete_mutation_case(
    "WS2812 DIN pin image LDI mutated",
    "firmware/asm/ws2812.asm",
    "LDI   R2, 0x80 ",
    "LDI   R2, 0x40 ",
    "DIN pin image LDI R2, 0x40",
)

concrete_mutation_case(
    "DALI receive samples must extract the isolated receiver pin",
    "firmware/asm/dali_master.asm",
    "SHF   R3, RIGHT",
    "SHF   R3, LEFT",
    "RX sample",
)

concrete_mutation_case(
    "WS2812 program drives uo_out from another register",
    "firmware/asm/ws2812.asm",
    "OUT   UO_OUT, R1       ; s20",
    "OUT   UO_OUT, R0       ; s20",
    "OUT UO_OUT from R0",
)

concrete_mutation_case(
    "WS2812 bench DIN bit moved",
    "verification/test_firmware_ws2812.py",
    'DIN_PIN, DIN_BIT = "uo_out", 7',
    'DIN_PIN, DIN_BIT = "uo_out", 6',
    "DIN_PIN/DIN_BIT is uo_out[6]",
)


@case("WS2812 DIN moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uo_out[7]")["protocol_roles"]["ws2812"] = "unused"
        pin(t, "uo_out[6]")["protocol_roles"]["ws2812"] = "DIN"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/ws2812.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "DMX512 TX mask LDI mutated",
    "firmware/asm/dmx512_tx.asm",
    "LDI   R1, 1 ",
    "LDI   R1, 2 ",
    "firmware/asm/dmx512_tx.asm",
)

concrete_mutation_case(
    "DMX512 bench TX pin mutated",
    "verification/test_firmware_dmx512.py",
    'TX_PIN, TX_BIT = "uo_out", 0',
    'TX_PIN, TX_BIT = "uo_out", 1',
    "TX_PIN/TX_BIT is uo_out[1]",
)


@case("DMX512 TX moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uo_out[0]")["protocol_roles"]["dmx512"] = "unused"
        pin(t, "uo_out[1]")["protocol_roles"]["dmx512"] = "TX"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/dmx512_tx.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "I2S SD mask LDI mutated",
    "firmware/asm/i2s_tx.asm",
    "LDI   R1, 0x80          ; s9\n        AND   R1, R0            ; s10  SD for the MSB",
    "LDI   R1, 0x40          ; s9\n        AND   R1, R0            ; s10  SD for the MSB",
    "firmware/asm/i2s_tx.asm",
)

concrete_mutation_case(
    "I2S WS mask LDI mutated",
    "firmware/asm/i2s_tx.asm",
    "LDI   R2, 0x20          ; s11\n        OR    R1, R2            ; s12  + WS\n        LDI   R3, 1",
    "LDI   R2, 0x10          ; s11\n        OR    R1, R2            ; s12  + WS\n        LDI   R3, 1",
    "firmware/asm/i2s_tx.asm",
)

concrete_mutation_case(
    "I2S pin driven from a register other than R1",
    "firmware/asm/i2s_tx.asm",
    "OUT   UO_OUT, R1        ; s8   BCLK rises\n        LDI   R1, 0x80          ; s9\n        AND   R1, R0            ; s10  SD for the MSB",
    "OUT   UO_OUT, R2        ; s8   BCLK rises\n        LDI   R1, 0x80          ; s9\n        AND   R1, R0            ; s10  SD for the MSB",
    "OUT UO_OUT from R2",
)

concrete_mutation_case(
    "I2S bench BCLK pin mutated",
    "verification/test_firmware_i2s.py",
    'BCLK_PIN, BCLK_BIT = "uo_out", 6',
    'BCLK_PIN, BCLK_BIT = "uo_out", 4',
    "BCLK_PIN/BCLK_BIT is uo_out[4]",
)


@case("I2S WS moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uo_out[5]")["protocol_roles"]["i2s"] = "unused"
        pin(t, "uo_out[4]")["protocol_roles"]["i2s"] = "WS"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/i2s_tx.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "NEC IR carrier-image LDI mutated",
    "firmware/asm/nec_ir.asm",
    "LDI   R1, 0x80        ; 1   carrier-high image / bit-7 mask",
    "LDI   R1, 0x40        ; 1   carrier-high image / bit-7 mask",
    # the diagnostic must still identify the carrier image through the
    # #526 consolidation, not just any wrong mask
    "IR_TX mask LDI R1, 0x40",
)

concrete_mutation_case(
    "NEC IR bench TX pin mutated",
    "verification/test_firmware_nec_ir.py",
    'TX_PIN, TX_BIT = "uo_out", 7',
    'TX_PIN, TX_BIT = "uo_out", 6',
    "TX_PIN/TX_BIT is uo_out[6]",
)


@case("NEC IR TX moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uo_out[7]")["protocol_roles"]["nec_ir_tx"] = "unused"
        pin(t, "uo_out[6]")["protocol_roles"]["nec_ir_tx"] = "IR_TX"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/nec_ir.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "Modbus RX mask LDI mutated",
    "firmware/asm/modbus_rtu.asm",
    "main:   LDI   R1, 2            ; RX mask (ui_in bit 1) and decrement",
    "main:   LDI   R1, 4            ; RX mask (ui_in bit 1) and decrement",
    "RX bit mask LDI R1, 4",
)

concrete_mutation_case(
    "Modbus TX image writes a pin outside TX/DE",
    "firmware/asm/modbus_rtu.asm",
    "        LDI   R2, 1            ; idle image: TX high, DE low",
    "        LDI   R2, 5            ; idle image: TX high, DE low",
    "can write 0x05",
)

concrete_mutation_case(
    "Modbus bench DE pin mutated",
    "verification/test_firmware_modbus.py",
    "TX_BIT, DE_BIT = 0, 1",
    "TX_BIT, DE_BIT = 0, 2",
    "DE_BIT is uo_out[2]",
)


@case("Modbus DE moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uo_out[1]")["protocol_roles"]["modbus"] = "unused"
        pin(t, "uo_out[2]")["protocol_roles"]["modbus"] = "DE"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/modbus_rtu.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "PS/2 released-bus image mutated",
    "firmware/asm/ps2_device.asm",
    "LDI   R3, 0x0C\n        OUT   UIO_OUT, R3      ; both lines released ...",
    "LDI   R3, 0x0D\n        OUT   UIO_OUT, R3      ; both lines released ...",
    "released-bus image 0x0D",
)

concrete_mutation_case(
    "PS/2 CLK mask mutated",
    "firmware/asm/ps2_device.asm",
    "LDI   R3, 0x04\n        OR    R3, R1\n        OUT   UIO_OUT, R3      ; CLK stays",
    "LDI   R3, 0x02\n        OR    R3, R1\n        OUT   UIO_OUT, R3      ; CLK stays",
    "CLK mask 0x02",
)

concrete_mutation_case(
    "PS/2 stop-bit image is not the DATA mask",
    "firmware/asm/ps2_device.asm",
    "LDI   R1, 8            ; stop bit",
    "LDI   R1, 0            ; stop bit",
    "the pure pin images in LDI R1 are [0]",
)

concrete_mutation_case(
    "PS/2 data bit moved by the wrong number of doublings",
    "firmware/asm/ps2_device.asm",
    "        ADD   R3, R3\n        ADD   R3, R3\n        ADD   R3, R3\n",
    "        ADD   R3, R3\n        ADD   R3, R3\n",
    "a bit is moved by 2 doubling(s)",
)

concrete_mutation_case(
    "PS/2 bit-isolation shifts do not match the table's pin",
    "firmware/asm/ps2_device.asm",
    "        SHF   R3, LEFT         ; CLK (bit 2) -> bit 7\n",
    "        SHF   R3, LEFT\n        SHF   R3, LEFT         ; CLK (bit 2) -> bit 7\n",
    "which is none of the recipes",
)

concrete_mutation_case(
    "PS/2 bench pin constants moved",
    "verification/test_firmware_ps2.py",
    "CLK_BIT, DATA_BIT = 2, 3",
    "CLK_BIT, DATA_BIT = 2, 4",
    "DATA_BIT is uio[4]",
)


@case("PS/2 pins moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uio[2]")["protocol_roles"]["ps2"] = "unused"
        pin(t, "uio[0]")["protocol_roles"]["ps2"] = "PS2_CLK"
        pin(t, "uio[0]")["shared_pin_rationale"] = "moved for the test"
        t["pin_modes"]["ps2"]["uio_od"] = "0x09"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/ps2_device.asm", "concrete-firmware-bench")


@case("PS/2 program does not write the table's UIO_OD value")
def _(fx):
    fx.mutate("firmware/asm/ps2_device.asm", "WCTL  UIO_OD, R3       ; ... then", "NOP                    ; ... then")
    code, out = fx.run("--require-implemented")
    assert code == 1 and "ps2_device.asm" in out and "UIO_OD" in out, out


concrete_mutation_case(
    "SWD preloaded image pair mutated",
    "firmware/asm/swd_probe.asm",
    "        LDI   R0, 0x08         ; image: SWCLK low, SWDIO high",
    "        LDI   R0, 0x09         ; (mutated)",
    "the preloaded images are R0=9",
)

concrete_mutation_case(
    "SWD per-bit pin image is not an SWCLK x SWDIO combination",
    "firmware/asm/swd_probe.asm",
    "        LDI   R3, 0x00\n        OUT   UIO_OUT, R3      ; SWDIO falls low",
    "        LDI   R3, 0x10         ; (mutated)\n        OUT   UIO_OUT, R3      ; SWDIO falls low",
    "is not one of",
)

concrete_mutation_case(
    "SWD sample isolation does not use the SWDIO-mask register",
    "firmware/asm/swd_probe.asm",
    "        AND   R3, R0           ; keep the SWDIO bit (R0 = 0x08)",
    "        AND   R3, R1           ; (mutated)",
    "IN UIO_IN must be followed by",
)

concrete_mutation_case(
    "SWD UIO_DIR release value mutated",
    "firmware/asm/swd_probe.asm",
    "        LDI   R3, 0x04         ; direction: SWCLK only",
    "        LDI   R3, 0x05         ; (mutated)",
    "WCTL UIO_DIR writes 0x05",
)

concrete_mutation_case(
    "SWD bench pin constants moved",
    "verification/test_firmware_swd.py",
    "SWCLK_BIT, SWDIO_BIT = 2, 3",
    "SWCLK_BIT, SWDIO_BIT = 2, 4",
    "SWDIO_BIT is uio[4]",
)


@case("SWD pins moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uio[2]")["protocol_roles"]["swd"] = "unused"
        pin(t, "uio[0]")["protocol_roles"]["swd"] = "SWCLK"
        t["pin_modes"]["swd"]["uio_dir"] = "0x09"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/swd_probe.asm", "concrete-firmware-bench")


@case("SWD program does not write the table's UIO_DIR value")
def _(fx):
    fx.mutate("firmware/asm/swd_probe.asm",
              "        WCTL  UIO_DIR, R1      ; push-pull on SWCLK and SWDIO",
              "        NOP                    ; (mutated)")
    code, out = fx.run("--require-implemented")
    assert code == 1 and "swd_probe.asm" in out and "UIO_DIR" in out, out


concrete_mutation_case(
    "1-Wire released-DQ image mutated",
    "firmware/asm/onewire_master.asm",
    "        LDI   R3, 0x08\n        OUT   UIO_OUT, R3      ; DQ released ...",
    "        LDI   R3, 0x09\n        OUT   UIO_OUT, R3      ; DQ released ...",
    "pin image 0x09",
)

concrete_mutation_case(
    "1-Wire assert image is not 0",
    "firmware/asm/onewire_master.asm",
    "wrent:  LDI   R3, 1            ; walk mask: bit 0 first (1-Wire is LSB first)\nwrbit:  LDI   R1, 0\n        OUT   UIO_OUT, R1      ; falling edge: the slot starts",
    "wrent:  LDI   R3, 1            ; walk mask: bit 0 first (1-Wire is LSB first)\nwrbit:  LDI   R1, 2\n        OUT   UIO_OUT, R1      ; falling edge: the slot starts",
    "pin image 2",
)

concrete_mutation_case(
    "1-Wire DQ sample mask mutated",
    "firmware/asm/onewire_master.asm",
    "        IN    R3, UIO_IN\n        LDI   R1, 0x08\n        AND   R3, R1           ; DQ (bit 3) isolated",
    "        IN    R3, UIO_IN\n        LDI   R1, 0x04\n        AND   R3, R1           ; DQ (bit 3) isolated",
    "masked with 0x04",
)

concrete_mutation_case(
    "1-Wire bench DQ_BIT moved",
    "verification/test_firmware_onewire.py",
    "DQ_BIT = 3",
    "DQ_BIT = 2",
    "DQ_BIT is uio[2]",
)


@case("1-Wire DQ moved in the table alone")
def _(fx):
    def mv(t):
        pin(t, "uio[3]")["protocol_roles"]["onewire"] = "unused"
        pin(t, "uio[2]")["protocol_roles"]["onewire"] = "DQ"
        t["pin_modes"]["onewire"]["uio_od"] = "0x04"
    fx.mutate_table(mv)
    expect_fail(fx, "firmware/asm/onewire_master.asm", "concrete-firmware-bench")


@case("1-Wire program does not write the table's UIO_OD value")
def _(fx):
    fx.mutate("firmware/asm/onewire_master.asm",
              "        WCTL  UIO_OD, R3       ; ... then open-drain on DQ alone",
              "        NOP                   ; ... then open-drain on DQ alone")
    code, out = fx.run("--require-implemented")
    assert code == 1 and "onewire_master.asm" in out and "UIO_OD" in out, out


@case("UART RX mask LDI mutated in each RX program")
def _(fx):
    for stem in ("uart_rx", "uart_rx_115200", "uart_rx_9600"):
        f = Fixture()
        try:
            f.mutate(f"firmware/asm/{stem}.asm", "LDI   R1, 2", "LDI   R1, 1")
            expect_fail(f, f"firmware/asm/{stem}.asm", "concrete-firmware-bench")
        finally:
            f.close()


concrete_mutation_case(
    "UART RX sampled from the wrong port",
    "firmware/asm/uart_rx.asm",
    "IN    R2, UI_IN        ; SAMPLE (bit centre)",
    "IN    R2, UIO_IN        ; SAMPLE (bit centre)",
    "IN from port UIO_IN",
)


@case("table moves UART RX back to ui_in[0]: RX programs fail by file")
def _(fx):
    def mv(t):
        pin(t, "ui_in[1]")["protocol_roles"]["uart_rx"] = "unused"
        pin(t, "ui_in[0]")["protocol_roles"]["uart_rx"] = "RX"
        pin(t, "ui_in[0]")["shared_pin_rationale"] = "UART RX shares PROG_SER (mutation)."
    fx.mutate_table(mv)
    code, out = fx.run()
    assert code == 1 and "[schema] PASS" in out and "[concrete-firmware-bench] FAIL" in out, out
    for stem in ("uart_rx", "uart_rx_115200", "uart_rx_9600"):
        assert f"firmware/asm/{stem}.asm" in out, out


RX_STEMS = ("uart_rx", "uart_rx_115200", "uart_rx_9600")


@case("UART RX received byte misrouted to uio_out in each RX program")
def _(fx):
    for stem in RX_STEMS:
        f = Fixture()
        try:
            rel = f"firmware/asm/{stem}.asm"
            f.mutate(rel, "OUT   UO_OUT, R0       ; emit the received byte",
                     "OUT   UIO_OUT, R0       ; emit the received byte")
            code, out = f.run()
            assert code == 1 and "[concrete-firmware-bench] FAIL" in out, out
            assert re.search(rf"{re.escape(rel)}:\d+: OUT UIO_OUT, R0 is not a recognised bench-debug write", out), out
            assert f"{rel}: no `OUT UO_OUT, Rx` emits a received (computed) byte" in out, out
        finally:
            f.close()


concrete_mutation_case(
    "UART RX received byte copied to uio_out as well as uo_out",
    "firmware/asm/uart_rx.asm",
    "OUT   UO_OUT, R0       ; emit the received byte",
    "OUT   UO_OUT, R0       ; emit the received byte\n        OUT   UIO_OUT, R0",
    "OUT UIO_OUT, R0 is not a recognised bench-debug write",
)

concrete_mutation_case(
    "UART RX arbitrary constant written to uio_out",
    "firmware/asm/uart_rx.asm",
    "LDI   R3, 0\n",
    "LDI   R3, 0x7E\n",
    "OUT UIO_OUT, R3 writes 0x7E; bench_debug.uart_rx allows only 0, "
    "SAMPLE_MARK 0x02 and FRAME_ERROR 0x04",
)

concrete_mutation_case(
    "UART RX frame-error flag shifted onto an undeclared uio_out bit",
    "firmware/asm/uart_rx.asm",
    "SHF   R2, LEFT         ; -> UIO_OUT bit 2 (SHF leaves Z alone)",
    "SHF   R2, RIGHT        ; -> UIO_OUT bit 2 (SHF leaves Z alone)",
    "is not a recognised bench-debug write",
)


@case("table moves the UART RX debug bits: RX programs fail by file")
def _(fx):
    fx.mutate_table(lambda t: t["bench_debug"]["uart_rx"]["bits"].update(SAMPLE_MARK=2, FRAME_ERROR=3))
    code, out = fx.run()
    assert code == 1 and "[schema] PASS" in out and "[concrete-firmware-bench] FAIL" in out, out
    for stem in RX_STEMS:
        assert f"firmware/asm/{stem}.asm" in out, out


@case("table drops bench_debug: any UART RX write to uio_out fails")
def _(fx):
    fx.mutate_table(lambda t: t.pop("bench_debug"))
    expect_fail(fx, "firmware/asm/uart_rx.asm: OUT to port UIO_OUT", "concrete-firmware-bench")


@case("schema: bench_debug with an unknown bit name or out-of-range bit")
def _(fx):
    fx.mutate_table(lambda t: t["bench_debug"]["uart_rx"]["bits"].update(RESULT=4))
    expect_fail(fx, "table.bench_debug.uart_rx.bits: names", "schema")
    fx2 = Fixture()
    try:
        fx2.mutate_table(lambda t: t["bench_debug"]["uart_rx"]["bits"].update(FRAME_ERROR=8))
        expect_fail(fx2, "each bit must be a distinct integer 0..7", "schema")
    finally:
        fx2.close()


concrete_mutation_case(
    "UART TX 9600 mask LDI mutated",
    "firmware/asm/uart_tx_9600.asm",
    "LDI   R1, 1",
    "LDI   R1, 2",
    "firmware/asm/uart_tx_9600.asm",
)


@case("SPI idle image (CS bit) mutated in each mode")
def _(fx):
    for n in range(4):
        f = Fixture()
        try:
            anchor, wrong = ("0x09", "0x01") if n >= 2 else ("0x01", "0x09")
            first = re.search(rf"LDI   R2, {anchor}", f.path(f"firmware/asm/spi_mode{n}.asm").read_text())
            assert first, f"mode {n} anchor missing"
            f.mutate(f"firmware/asm/spi_mode{n}.asm", first.group(0), f"LDI   R2, {wrong}")
            expect_fail(f, f"firmware/asm/spi_mode{n}.asm", "concrete-firmware-bench")
        finally:
            f.close()


concrete_mutation_case(
    "SPI MISO mask LDI mutated",
    "firmware/asm/spi_mode0.asm",
    "LDI   R1, 0x04            ; MISO mask (uio_in bit 2)",
    "LDI   R1, 0x01            ; MISO mask (uio_in bit 2)",
    "firmware/asm/spi_mode0.asm",
)

concrete_mutation_case(
    "SPI pin image written to uo_out instead of uio_out",
    "firmware/asm/spi_mode0.asm",
    "OUT   UIO_OUT, R2          ; CS falls",
    "OUT   UO_OUT, R2          ; CS falls",
    "constant pin image 0x00 written to UO_OUT",
)


@case("SPI MISO sampled from the wrong port")
def _(fx):
    fx.mutate("firmware/asm/spi_mode1.asm", "IN    R3, UIO_IN", "IN    R3, UI_IN", count=100)
    expect_fail(fx, "IN from port UI_IN", "concrete-firmware-bench")


@case("SPI mode 1: a sample into the image register between LDI and OUT breaks the pairing")
def _(fx):
    # issue #309: the functional burst's IN sits between the trailing image
    # LDI and its OUT. Only an IN into some other register is skipped; one
    # that overwrites the image register is not a pin-image pair, and the
    # data-bearing images are then unseen. Mutating also the ceiling
    # burst's LDIs would hide the effect, so only the functional IN moves.
    fx.mutate("firmware/asm/spi_mode1.asm", "IN    R3, UIO_IN        ; sample MISO (bit",
              "IN    R2, UIO_IN        ; sample MISO (bit", count=8)
    expect_fail(fx, "firmware/asm/spi_mode1.asm", "concrete-firmware-bench")


concrete_mutation_case(
    "I2C idle image mutated (SDA moved)",
    "firmware/asm/i2c_fast.asm",
    "LDI   R3, 0x0C        ; both lines released",
    "LDI   R3, 0x0A        ; both lines released",
    "bus-idle image",
)

concrete_mutation_case(
    "I2C SDA mask register LDI mutated",
    "firmware/asm/i2c_std.asm",
    "LDI   R1, 0x08",
    "LDI   R1, 0x40",
    "firmware/asm/i2c_std.asm",
)

concrete_mutation_case(
    "I2C SCL poll mask mutated in a poll variant",
    "firmware/asm/i2c_fast_sr_poll.asm",
    "LDI   R3, 0x04       ; poll mask",
    "LDI   R3, 0x02       ; poll mask",
    "SCL poll mask",
)


@case("I2C SCL poll mask register overwritten between its LDI and the poll")
def _(fx):
    rel, poll = "firmware/asm/i2c_fast_sr_poll.asm", "        poll0: IN    R2, UIO_IN"
    fx.mutate(rel, poll, "        XOR   R3, R3\n" + poll)
    code, out = fx.run()
    assert code == 1, f"expected exit 1, got {code}:\n{out}"
    assert "[concrete-firmware-bench] FAIL" in out, f"layer concrete-firmware-bench did not fail:\n{out}"
    assert "consistency (schema + metadata + concrete): FAIL" in out, out
    sites = [n for n, l in enumerate(fx.path(rel).read_text(encoding="utf-8").splitlines(), 1)
             if l.startswith(poll)]
    assert len(sites) == 1, sites
    assert f"ERROR: {rel}:{sites[0]}: SCL poll mask " in out, out
    assert "`XOR R3, R3`" in out, out


concrete_mutation_case(
    "I2C generator string literal mutated",
    "firmware/tools/gen_i2c_sr.py",
    '"LDI   R3, 0x04       ; poll mask"',
    '"LDI   R3, 0x02       ; poll mask"',
    "firmware/tools/gen_i2c_sr.py",
)


# Issue #638: `in_and_sites` took a sample's isolation mask from the nearest
# write of the AND's mask register and, unless that write was an `LDI`,
# skipped the site -- no error, no site counted. On `169fa5fd5` the
# read-byte SDA sample masked with zero by `XOR R3, R3` passed as consistent
# (792 sites against the clean fixture's 793, exit 0). A matched IN/AND
# pair must count once and name whatever leaves the mask unreadable; both
# cases compare the concrete site count with the clean fixture's, so a
# sample that vanishes from the count fails without a hard-coded total.
I2C_POLL = "firmware/asm/i2c_fast_sr_poll.asm"
SDA_SAMPLE = "        IN    R2, UIO_IN     ; sample the bus"
SDA_ISOLATE = "        AND   R2, R3         ; isolate SDA (bit 3)"


def only_line(fx: Fixture, rel: str, line: str) -> int:
    """The 1-based number of `line` in the fixture file; it MUST occur once."""
    nos = [n for n, l in enumerate(fx.path(rel).read_text(encoding="utf-8").splitlines(), 1)
           if l == line]
    assert len(nos) == 1, f"{line!r} occurs at lines {nos} in {rel}; expected exactly one"
    return nos[0]


def concrete_sites(out: str) -> int:
    """The concrete layer's `N site(s) checked` count of one run."""
    m = re.search(r"\[concrete-firmware-bench\] (?:PASS|FAIL) \((\d+) site\(s\) checked\)", out)
    assert m, f"no concrete-layer site count in:\n{out}"
    return int(m.group(1))


def unresolved_sample(rel: str, in_no: int, and_no: int, why: str) -> str:
    """The diagnostic of a read-byte SDA sample whose mask cannot be read."""
    return (f"ERROR: {rel}:{in_no}: IN UIO_IN at line {in_no} is masked by `AND R2, R3` "
            f"at line {and_no} with an unresolved mask: {why}; the table's SDA pin mask is 0x08")


def expect_consistency_fail(fx: Fixture) -> str:
    """The run exits 1 with the concrete layer and consistency both failing."""
    code, out = fx.run()
    assert code == 1, f"expected exit 1, got {code}:\n{out}"
    assert "[concrete-firmware-bench] FAIL" in out, (
        f"layer concrete-firmware-bench did not fail:\n{out}")
    assert "consistency (schema + metadata + concrete): FAIL" in out, out
    return out


@case("I2C read-byte SDA sample: the mask register overwritten before the AND fails")
def _(fx):
    xor = "        XOR   R3, R3"
    _code, clean = fx.run()
    fx.mutate(I2C_POLL, SDA_ISOLATE, xor + "\n" + SDA_ISOLATE)
    out = expect_consistency_fail(fx)
    in_no, xor_no, and_no = (only_line(fx, I2C_POLL, l) for l in (SDA_SAMPLE, xor, SDA_ISOLATE))
    why = f"the nearest write of R3 is `XOR R3, R3` (line {xor_no}), not an `LDI`"
    assert unresolved_sample(I2C_POLL, in_no, and_no, why) in out, out
    assert concrete_sites(out) == concrete_sites(clean), out


@case("I2C read-byte SDA sample: a lowercase XOR destination overwrites the mask")
def _(fx):
    fx.mutate(I2C_POLL, SDA_ISOLATE, "        XOR   r3, R3\n" + SDA_ISOLATE)
    expect_fail(fx, "the nearest write of R3 is `XOR r3, R3`",
                "concrete-firmware-bench", "--require-implemented")


@case("I2C read-byte SDA sample: a lowercase AND mask operand finds the uppercase LDI")
def _(fx):
    fx.mutate(I2C_POLL, SDA_ISOLATE, SDA_ISOLATE.replace("R3", "r3"))
    code, out = fx.run("--require-implemented")
    assert code == 0, out
    # An incorrect immediate must still reach this sample's mask comparison.
    fx.mutate(I2C_POLL, "0x08       ; mask AND next SCL-low pins",
              "0x04       ; mask AND next SCL-low pins")
    expect_fail(fx, "is masked with 0x04 but the table's SDA pin mask is 0x08",
                "concrete-firmware-bench", "--require-implemented")


@case("I2C read-byte SDA sample: a mask register with no earlier write fails")
def _(fx):
    early = ("        IN    R2, UIO_IN     ; sample the bus, before any mask is written\n"
             "        AND   R2, R3         ; isolate SDA (bit 3), before any mask is written\n")
    setup = "        LDI   R3, 0x0C        ; both lines released: bus idle"
    _code, clean = fx.run()
    fx.mutate(I2C_POLL, setup, early + setup)
    out = expect_consistency_fail(fx)
    in_no, and_no = (only_line(fx, I2C_POLL, l) for l in early.splitlines())
    assert unresolved_sample(I2C_POLL, in_no, and_no,
                             "R3 has no earlier write in this file") in out, out
    assert concrete_sites(out) == concrete_sites(clean) + 1, out


# CAN 2.0A (issue #584): DR 0010's can section records that the image uses
# UIO_DIR as scratch, pinned by CAN_UIO_DIR_WRITE_SITES = 7 sites and the
# setup immediate LDI <reg>, 0x05 before the first write. Both guards need
# negative evidence: a silent drift between can_2a.asm and the record must
# not pass the checker.
concrete_mutation_case(
    "CAN UIO_DIR scratch: an 8th WCTL site fails the DR 0010 record",
    "firmware/asm/can_2a.asm",
    "\tWCTL  UIO_DIR, R2\n\tRCTL  R1, PM_DATA_HI\n",
    "\tWCTL  UIO_DIR, R2\n\tWCTL  UIO_DIR, R2\n\tRCTL  R1, PM_DATA_HI\n",
    "8 `WCTL UIO_DIR` sites but DR 0010's can section records 7",
)

concrete_mutation_case(
    "CAN UIO_DIR scratch: a deleted 6th WCTL site fails the DR 0010 record",
    "firmware/asm/can_2a.asm",
    # The first site (and its LDI R2, 0x05 setup) stays, so only the count
    # guard fires; the anchor is the unique XOR-zeroed release site.
    "\tXOR   R2, R2\n\tWCTL  UIO_DIR, R2\n",
    "\tXOR   R2, R2\n",
    "6 `WCTL UIO_DIR` sites but DR 0010's can section records 7",
)

concrete_mutation_case(
    "CAN UIO_DIR scratch: a wrong first-site setup immediate fails",
    "firmware/asm/can_2a.asm",
    "\tLDI   R2, 0x05\n\tWCTL  UIO_DIR, R2\n",
    "\tLDI   R2, 0x06\n\tWCTL  UIO_DIR, R2\n",
    "the first `WCTL UIO_DIR` is not preceded by `LDI <reg>, 0x05`",
)


# ------------------------------------------------- concrete: bench sites
concrete_mutation_case(
    "SPI bench CS/SCLK swap",
    "verification/test_firmware_spi.py",
    "CS_BIT, SCLK_BIT, MOSI_BIT = 0, 3, 1",
    "CS_BIT, SCLK_BIT, MOSI_BIT = 3, 0, 1",
    "verification/test_firmware_spi.py",
)

concrete_mutation_case(
    "SPI bench MISO pin/bit mutated",
    "verification/test_firmware_spi.py",
    'MISO_PIN, MISO_BIT = "uio_in", 2',
    'MISO_PIN, MISO_BIT = "uio_in", 3',
    "MISO_PIN/MISO_BIT",
)

concrete_mutation_case(
    "SPI bench grades a line captured on uo_out",
    "verification/test_firmware_spi.py",
    '"sclk": (LINE_PIN, SCLK_BIT)',
    '"sclk": ("uo_out", SCLK_BIT)',
    "SCLK_BIT (captured on uo_out) is uo_out[3]",
)


@case("SPI bench board wired with a literal pin, or uio_in written directly")
def _(fx):
    fx.mutate("verification/test_firmware_spi.py",
              "spi_board(dut, cs=CS_BIT, sclk=SCLK_BIT, mosi=MOSI_BIT, miso=MISO_BIT)",
              "spi_board(dut, cs=CS_BIT, sclk=SCLK_BIT, mosi=MOSI_BIT, miso=2)")
    expect_fail(fx, "spi_board(dut, cs=CS_BIT", "concrete-firmware-bench")
    fx2 = Fixture()
    try:
        fx2.mutate("verification/test_firmware_spi.py", "            pads.drive(MISO_BIT, write)",
                   "            dut.uio_in.value = write << 2")
        expect_fail(fx2, "writes dut.uio_in directly", "concrete-firmware-bench")
    finally:
        fx2.close()


concrete_mutation_case(
    "UART bench TX pin mutated",
    "verification/test_firmware_uart.py",
    'TX_PIN, TX_BIT = "uo_out", 0',
    'TX_PIN, TX_BIT = "uo_out", 4',
    "TX_PIN/TX_BIT",
)

concrete_mutation_case(
    "I2C bench SCL/SDA constants mutated",
    "verification/test_firmware_i2c.py",
    'SDA_PIN, SDA_BIT = "uio_out", 3',
    'SDA_PIN, SDA_BIT = "uio_out", 6',
    "SDA_PIN/SDA_BIT",
)

concrete_mutation_case(
    "I2C bench line read on the wrong port",
    "verification/test_firmware_i2c.py",
    'LINE_PIN = "uio_in"',
    'LINE_PIN = "uio_out"',
    "LINE_PIN",
)

concrete_mutation_case(
    "I2C bench grades a line captured on the wrong bit",
    "verification/test_firmware_i2c.py",
    '"sda": (LINE_PIN, SDA_BIT)',
    '"sda": (LINE_PIN, 6)',
    '"sda": (LINE_PIN, SDA_BIT) capture spec',
)

concrete_mutation_case(
    "I2C bench board wired with a literal pin",
    "verification/test_firmware_i2c.py",
    "i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)",
    "i2c_board(dut, scl=SCL_BIT, sda=6)",
    "i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)",
)

concrete_mutation_case(
    "I2C bench peripheral names a pad by literal",
    "verification/test_firmware_i2c.py",
    "pads.pull_low(SDA_BIT)",
    "pads.pull_low(6)",
    "pads.pull_low(6, ...)",
)

concrete_mutation_case(
    "I2C bench bypasses the pad model by writing uio_in",
    "verification/test_firmware_i2c.py",
    "                pads.pull_low(SDA_BIT)",
    "                pads.pull_low(SDA_BIT)\n                dut.uio_in.value = 0x01",
    "writes dut.uio_in directly",
)

concrete_mutation_case(
    "I2C SR bench peripheral drives a pad named by literal",
    "verification/test_firmware_i2c_sr.py",
    "pads.set_open_drain(SDA_BIT, sda_drive)",
    "pads.set_open_drain(6, sda_drive)",
    "pads.set_open_drain(6, ...)",
)

concrete_mutation_case(
    "I2C SR bench wires its own board",
    "verification/test_firmware_i2c_sr.py",
    "    pads = i2c_pads(dut).start()",
    "    pads = i2c_board(dut, scl=0, sda=6).start()",
    "i2c_pads(dut)",
)

concrete_mutation_case(
    "I2C SR bench does not import the capture specs",
    "verification/test_firmware_i2c_sr.py",
    "    CAPTURE_SPECS,\n",
    "",
    "does not import CAPTURE_SPECS",
)


@case("load bench MODE literal and serial position mutated")
def _(fx):
    fx.mutate("verification/test_protocol_emulator.py", "dut.ui_in.value = 0x80 | serial",
              "dut.ui_in.value = 0x80 | (serial << 1)")
    expect_fail(fx, "serial data driven on ui_in[1]", "concrete-firmware-bench")
    fx2 = Fixture()
    try:
        fx2.mutate("verification/test_protocol_emulator.py", "dut.ui_in.value = 0x80 | serial",
                   "dut.ui_in.value = 0x40 | serial")
        expect_fail(fx2, "PROG_MODE", "concrete-firmware-bench")
    finally:
        fx2.close()


@case("top-level program-load wiring mutated")
def _(fx):
    fx.mutate("src/tt_um_2amlogic_protocol_emulator.v", ".serial_in (ui_in[0])", ".serial_in (ui_in[1])")
    expect_fail(fx, "PROG_SER wired to ui_in[1]", "metadata-capability")


concrete_mutation_case(
    "ISA port table code mutated",
    "firmware/tools/asm.py",
    '"UO_OUT":  (0b10,',
    '"UO_OUT":  (0b11,',
    "ISA port UO_OUT",
)


# ------------------------------------------------- metadata (info.yaml)
@case("info.yaml pin key renamed / missing")
def _(fx):
    fx.mutate("info.yaml", "  uo[3]:", "  uo[33]:")
    expect_fail(fx, "pinout key uo[3] missing", "metadata-capability")
    assert "unexpected pinout key uo[33]" in fx.run()[1]


@case("info.yaml duplicate key")
def _(fx):
    fx.mutate("info.yaml", '  ui[2]: "ISA input port 00 bit 2 (read by IN Rd, 00)"',
              '  ui[1]: "ISA input port 00 bit 1 (read by IN Rd, 00)"')
    expect_fail(fx, "duplicate pinout key ui[1]", "metadata-capability")


@case("info.yaml pin under the wrong direction section")
def _(fx):
    fx.mutate("info.yaml", "  # Outputs\n", "  # Bidirectional pins\n")
    expect_fail(fx, "wrong direction section", "metadata-capability")


@case("info.yaml generic label replaced by a concrete claim the table lacks")
def _(fx):
    fx.mutate("info.yaml", 'ui[1]: "ISA input port 00 bit 1 (read by IN Rd, 00)"',
              'ui[1]: "ISA input port 00 bit 1 (read by IN Rd, 00); SPI MISO"')
    expect_fail(fx, "claims protocol role MISO", "metadata-capability")


@case("info.yaml concrete claim that the table does assign is accepted")
def _(fx):
    fx.mutate("info.yaml", 'uo[0]: "ISA output port 10 bit 0 (driven by OUT 10, Rs;',
              'uo[0]: "ISA output port 10 bit 0, UART TX (driven by OUT 10, Rs;')
    code, out = fx.run()
    assert code == 0, out


@case("info.yaml keeps a moved SPI role on its old pin")
def _(fx):
    fx.mutate("info.yaml", 'uo[1]: "ISA output port 10 bit 1 (driven by OUT 10, Rs)"',
              'uo[1]: "ISA output port 10 bit 1 (driven by OUT 10, Rs); SPI SCLK"')
    expect_fail(fx, "uo[1] claims protocol role SCLK", "metadata-capability")


@case("info.yaml load label missing")
def _(fx):
    fx.mutate("info.yaml", "PROG_MODE:", "MODE:")
    expect_fail(fx, "omits PROG_MODE", "metadata-capability")


@case("info.yaml generic port label wrong")
def _(fx):
    fx.mutate("info.yaml", "ISA output port 10 bit 5", "ISA output port 01 bit 5")
    expect_fail(fx, "generic ISA capability label", "metadata-capability")


# ---------------------------------------------------------- table schema
@case("schema: unsupported CAN role")
def _(fx):
    fx.mutate_table(lambda t: t["phases"]["can"].append("BOGUS"))
    expect_vocabulary_errors(fx, ["can"])


@case("schema: CAN vocabulary error precedes Modbus vocabulary error")
def _(fx):
    def add_unsupported_roles(table):
        for phase in ("modbus", "can"):
            table["phases"][phase].append("BOGUS")

    fx.mutate_table(add_unsupported_roles)
    expect_vocabulary_errors(fx, ["can", "modbus"])


@case("schema: missing pin")
def _(fx):
    fx.mutate_table(lambda t: t["pins"].remove(pin(t, "uio[3]")))
    expect_fail(fx, "missing pin uio[3]", "schema")


@case("schema: duplicate pin")
def _(fx):
    fx.mutate_table(lambda t: t["pins"].append(dict(pin(t, "uio[3]"))))
    expect_fail(fx, "duplicate entry for uio[3]", "schema")


@case("schema: unknown port")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uio[3]").update(port="uiox"))
    expect_fail(fx, "unknown port 'uiox'", "schema")


@case("schema: bit out of range")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uio[3]").update(bit=9))
    expect_fail(fx, "out of range", "schema")


@case("schema: contradictory electrical role")
def _(fx):
    # a fixed (non-runtime) role cannot carry push-pull SCLK and open-drain SDA
    fx.mutate_table(lambda t: pin(t, "uio[3]").update(electrical_role="push_pull"))
    expect_fail(fx, "uio[3]: SDA (i2c_transfer) needs open_drain", "schema")
    assert "contradictory driven roles" in fx.run()[1]
    fx2 = Fixture()
    try:
        fx2.mutate_table(lambda t: pin(t, "uo_out[0]").update(electrical_role="open_drain"))
        expect_fail(fx2, "dedicated output must be push_pull", "schema")
    finally:
        fx2.close()


@case("schema: declared mask disagrees with derived mask")
def _(fx):
    fx.mutate_table(lambda t: t.update(open_drain_mask="0x80"))
    expect_fail(fx, "open_drain_mask 0x80 != 0x00", "schema")


@case("schema: declared pin_modes disagree with the runtime pins' roles")
def _(fx):
    fx.mutate_table(lambda t: t["pin_modes"]["spi"].update(uio_dir="0x0F"))
    expect_fail(fx, "table.pin_modes.spi.uio_dir 0x0F != 0x0B", "schema")
    fx2 = Fixture()
    try:
        fx2.mutate_table(lambda t: t.pop("pin_modes"))
        expect_fail(fx2, "runtime pins need a top-level `pin_modes`", "schema")
    finally:
        fx2.close()


@case("schema: runtime electrical role off uio")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uo_out[5]").update(electrical_role="runtime"))
    expect_fail(fx, "uo_out[5]: electrical_role runtime (DR 0012 pin mode) exists only on uio", "schema")


@case("schema: shared pad without rationale")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uio[2]").update(shared_pin_rationale=""))
    expect_fail(fx, "uio[2]: input role shares a driven pad but has no shared_pin_rationale", "schema")
    fx2 = Fixture()
    try:
        fx2.mutate_table(lambda t: pin(t, "uio[3]").update(shared_pin_rationale=""))
        expect_fail(fx2, "uio[3]: runtime pin is open_drain and push_pull in different phases", "schema")
    finally:
        fx2.close()


@case("schema: unsupported extraction pattern")
def _(fx):
    def f(t):
        t["inventory"][0]["patterns"].append("regex_everything")
    fx.mutate_table(f)
    expect_fail(fx, "unsupported extraction pattern 'regex_everything'", "schema")


@case("schema: inventory file missing from the tree")
def _(fx):
    fx.path("firmware/asm/spi_mode2.asm").unlink()
    expect_fail(fx, "firmware/asm/spi_mode2.asm", "schema")


@case("schema: uninventoried committed firmware file")
def _(fx):
    fx.path("firmware/asm/uart_rx_57600.asm").write_text("HALT\n", encoding="utf-8")
    expect_fail(fx, "firmware/asm/uart_rx_57600.asm: committed firmware file is not in the inventory", "schema")


@case("schema: protocol role placed twice or not at all")
def _(fx):
    fx.mutate_table(lambda t: pin(t, "uo_out[3]")["protocol_roles"].update(spi_transfer="MOSI"))
    expect_fail(fx, "role MOSI placed on", "schema")
    fx2 = Fixture()
    try:
        fx2.mutate_table(lambda t: pin(t, "uio[1]")["protocol_roles"].update(spi_transfer="unused"))
        expect_fail(fx2, "role MOSI placed on no pin", "schema")
    finally:
        fx2.close()


@case("schema: no pin-roles fence")
def _(fx):
    p = fx.path(RECORD)
    p.write_text(p.read_text().replace("```json pin-roles", "```json"), encoding="utf-8")
    expect_fail(fx, "expected exactly one", "schema")


# ---------------------------------- proposed moves fail concrete, not schema
@case("table moves SCLK: schema passes, concrete firmware/bench fails (documented outcome)")
def _(fx):
    def f(t):
        pin(t, "uio[3]")["protocol_roles"]["spi_transfer"] = "unused"
        pin(t, "uio[5]")["protocol_roles"]["spi_transfer"] = "SCLK"
        pin(t, "uio[5]")["electrical_role"] = "runtime"
        t["pin_modes"]["spi"]["uio_dir"] = "0x23"
    fx.mutate_table(f)
    code, out = fx.run()
    assert code == 1, out
    assert "[schema] PASS" in out and "[concrete-firmware-bench] FAIL" in out, out
    assert "spi_mode0.asm" in out and "test_firmware_spi.py" in out, out


@case("table moves SPI MISO to ui_in[1]: SPI asm and bench fail by file")
def _(fx):
    def f(t):
        pin(t, "uio[2]")["protocol_roles"]["spi_transfer"] = "unused"
        # the rationale is emptied below, so the push-pull swd.SWCLK role
        # must move off uio[2] too (mixed drive kinds need the rationale,
        # and the phase still needs its pin; #452)
        pin(t, "uio[2]")["protocol_roles"]["swd"] = "unused"
        pin(t, "uio[0]")["protocol_roles"]["swd"] = "SWCLK"
        t["pin_modes"]["swd"]["uio_dir"] = "0x09"
        pin(t, "uio[2]")["shared_pin_rationale"] = ""
        pin(t, "ui_in[1]")["protocol_roles"]["spi_transfer"] = "MISO"
    fx.mutate_table(f)
    code, out = fx.run()
    assert code == 1 and "[schema] PASS" in out, out
    assert "MISO" in out and "spi_mode3.asm" in out, out


# ------------------------------------------------------ concrete: port roles
@case("SPI result write is optional: an image without it passes")
def _(fx):
    fx.mutate("firmware/asm/spi_mode0.asm", "OUT   UO_OUT, R0          ; ECHO the assembled RX byte",
              "OUT   UIO_OUT, R0          ; ECHO the assembled RX byte")
    code, out = fx.run()
    assert code == 0, out


@case("SPI transfer output is required: writing only the result port fails")
def _(fx):
    fx.mutate("firmware/asm/spi_mode0.asm", "OUT   UIO_OUT, ", "OUT   UO_OUT, ", count=100)
    expect_fail(fx, "firmware/asm/spi_mode0.asm: no OUT to port UIO_OUT; the table assigns pins on it",
                "concrete-firmware-bench")


@case("SPI on the wrong ports: all four port diagnostics report, in order")
def _(fx):
    fx.mutate("firmware/asm/spi_mode1.asm", "OUT   UIO_OUT, ", "OUT   UI_IN, ", count=100)
    fx.mutate("firmware/asm/spi_mode1.asm", "IN    R3, UIO_IN", "IN    R3, UI_IN", count=100)
    expect_ordered(fx,
                   "firmware/asm/spi_mode1.asm: OUT to port UI_IN; "
                   "the table allows ['UIO_OUT', 'UO_OUT'] for this profile",
                   "firmware/asm/spi_mode1.asm: no OUT to port UIO_OUT; the table assigns pins on it",
                   "firmware/asm/spi_mode1.asm: IN from port UI_IN; "
                   "the table allows ['UIO_IN'] for this profile",
                   "firmware/asm/spi_mode1.asm: no IN from port UIO_IN; the table assigns pins on it")


# ------------------------------------------- the Checker's state is declared
@case("structure: every Checker instance attribute is declared in __init__")
def _(fx):
    """Attributes created outside `__init__` make the layered order
    (`load_table` -> `run_inventory` -> `implementation`) a hidden protocol: no
    reader of a `prof_*` method can tell which state is live at that point
    without tracing `run()` by hand, and two readers of the same attribute can
    disagree about whether it exists. Declaring every attribute in `__init__`
    with its empty/None default is what makes that order checkable, so this
    case fails if a new attribute is introduced by assignment elsewhere."""
    cls = next(n for n in ast.walk(ast.parse(CHECKER.read_text(encoding="utf-8")))
               if isinstance(n, ast.ClassDef) and n.name == "Checker")

    def stores(node) -> list[tuple[str, int]]:
        """Every `self.X = ...` / `self.X: T = ...` / `self.X += ...` in `node`."""
        out = []
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                targets = n.targets
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
                targets = [n.target]
            else:
                continue
            for t in targets:
                for sub in ast.walk(t):
                    if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                            and sub.value.id == "self"):
                        out.append((sub.attr, sub.lineno))
        return out

    methods = [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
    init = next(m for m in methods if m.name == "__init__")
    declared = {attr for attr, _ in stores(init)}
    undeclared = sorted(
        f"self.{attr} ({m.name}:{line})"
        for m in methods if m.name != "__init__"
        for attr, line in stores(m) if attr not in declared
    )
    assert not undeclared, (
        f"{CHECKER.name}: Checker attribute(s) assigned outside __init__; declare "
        f"them there with their empty/None defaults: {undeclared}"
    )


@case("structure: every prof_* handler is classified by METADATA_PROFILES")
def _(fx):
    """`run_inventory` picks the layer a missing inventory file is reported on
    with one dispatch -- `self.meta if prof in METADATA_PROFILES else
    self.concrete` -- so the profile -> layer mapping is declared in that one
    constant. A wrong choice attributes the diagnostic to the wrong one of
    DR 0010's four reported results (the `info` profile's missing `info.yaml`
    would be blamed on `concrete-firmware-bench` instead of
    `metadata-capability`) while every behavioural case stays green: the CLI
    reports an absent file during schema validation and returns before this
    dispatch. So this case imports the shipped checker by path and calls
    `Checker.run_inventory()` itself, on one missing path per handler with a
    nonempty `patterns` list, and asserts which layer reports each filename.
    The two lists below stay independent of the shipped constant -- an
    explicit decision for every `prof_*` handler -- and an AST check keeps
    the dispatch reading that constant rather than a bare literal that would
    leave it, and this partition, dead code."""
    mod = load_checker()
    handlers = {n for n in dir(mod.Checker) if n.startswith("prof_")}

    # The committed ground truth (DR 0010): `info` reads `info.yaml`, a
    # metadata document; every other inventoried profile's source file is
    # firmware, bench or RTL, and its missing file reports on
    # concrete-firmware-bench.
    metadata = {"prof_info"}
    concrete = {
        "prof_uart_tx", "prof_uart_rx", "prof_spi", "prof_i2c", "prof_i2c_gen",
        "prof_demo", "prof_ws2812", "prof_ps2", "prof_onewire", "prof_dmx512", "prof_nec_ir",
        "prof_swd", "prof_can", "prof_modbus", "prof_i2s", "prof_bench_i2s",
        "prof_bench_can", "prof_bench_uart", "prof_bench_dmx512", "prof_bench_ws2812",
        "prof_bench_nec_ir", "prof_bench_modbus",
        "prof_bench_ps2", "prof_bench_onewire", "prof_bench_swd", "prof_bench_spi",
        "prof_bench_i2c", "prof_bench_i2c_sr", "prof_bench_load", "prof_top",
        "prof_core", "prof_isa_ports", "prof_dali", "prof_bench_dali",
    }

    classified = metadata | concrete
    assert classified == handlers, (
        f"{CHECKER.name}: prof_* handler name(s) {sorted(classified ^ handlers)} are "
        "classified here but have no method, or shipped but unclassified; add each new "
        "handler to `metadata` (metadata source) or `concrete` (firmware/bench/RTL "
        "source), and drop names whose method is gone"
    )
    declared = {f"prof_{p}" for p in getattr(mod, "METADATA_PROFILES", ())}
    assert declared == metadata, (
        f"{CHECKER.name}: METADATA_PROFILES names {sorted(declared)} where this case "
        f"classifies {sorted(metadata)} as metadata sources; reconcile the two"
    )

    fn = getattr(mod.Checker, "run_inventory", None)
    assert fn is not None, (
        f"{CHECKER.name}: Checker.run_inventory moved; teach this case its new home"
    )
    dispatch = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    assert any(isinstance(n, ast.Name) and n.id == "METADATA_PROFILES"
               for n in ast.walk(dispatch)), (
        f"{CHECKER.name}: Checker.run_inventory does not reference METADATA_PROFILES; "
        "the missing-file layer dispatch has drifted back to a literal and the "
        "constant -- with this case's handler partition -- is dead code"
    )

    empty = fx.path("empty-tree")
    empty.mkdir()
    ck = mod.Checker(empty, RECORD)
    ck.inv = {
        f"missing/{h}.txt": {"file": f"missing/{h}.txt",
                             "profile": h[len("prof_"):], "patterns": ["any"]}
        for h in sorted(handlers)
    }
    ck.run_inventory()

    def reported(layer) -> list[str]:
        """The inventory paths `layer` reports a missing file for, sorted."""
        return sorted(e.split(": ", 1)[0] for e in layer.errors)

    assert ck.schema.errors == [], ck.schema.errors
    for layer, expected in ((ck.meta, metadata), (ck.concrete, concrete)):
        want = sorted(f"missing/{h}.txt" for h in expected)
        assert reported(layer) == want, (
            f"{CHECKER.name}: [{layer.name}] reports missing {reported(layer)}; "
            f"expected {want}"
        )


@case("summary: a schema failure still prints a complete JSON summary")
def _(fx):
    """`--format json` reaches `summary()` even when `load_table()` failed and
    `run()` returned before the schema layer filled its derived state. The
    summary must still carry every key at its declared default -- this is the
    path the checker used to defend with a `getattr` on one of them."""
    fx.mutate_table(lambda t: t.pop("open_drain_mask"))
    code, out = fx.run("--format", "json")
    assert code == 1, out
    doc = json.loads(out)
    assert doc["open_drain_mask"] == "0x00", out
    assert doc["record"] == RECORD, out
    assert doc["layers"]["schema"]["ok"] is False, out
    assert "table: missing top-level key 'open_drain_mask'" in doc["layers"]["schema"]["errors"], out
    assert doc["layers"]["concrete-firmware-bench"]["sites_checked"] == 0, out
    assert doc["unwired_electrical_roles"] == [], out


def main() -> int:
    for run in CASES:
        run()
    failed = [r for r in _results if not r[1]]
    for name, ok, msg in _results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            print("     " + msg.replace("\n", "\n     "))
    print(f"{len(_results) - len(failed)}/{len(_results)} cases behave as specified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
