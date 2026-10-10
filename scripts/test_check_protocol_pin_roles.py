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

import json
import re
import shutil
import subprocess
import sys
import tempfile
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


# ---------------------------------------------------------------- baseline
# Issue #135 (DR 0012): the committed top level now derives uio_oe from the
# core's UIO_OD / UIO_DIR control registers, and the committed I2C programs
# set the table's open-drain mask with `WCTL UIO_OD`. So the committed tree
# is implementation-COMPLETE, and the cases that used to start from
# `assign uio_oe = 8'h00;` first put that synthesis-time shape back.
TOP = "src/tt_um_2amlogic_protocol_emulator.v"
RUNTIME_OE = "assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);"


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


@case("runtime pin mode: a top-level uio_oe that is not DR 0012's rule fails")
def _(fx):
    # open-drain no longer wins over push-pull
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = (uio_od & ~uio_out) | uio_dir;")
    expect_fail(fx, "is not DR 0012's pin-mode rule", "concrete-firmware-bench")


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


@case("load CRC readout: a direct core-to-uo_out connection is still accepted")
def _(fx):
    # the top as it was before issue #137: no mux, the port straight on the pins
    fx.mutate(TOP, ".port_uo_out (core_uo_out),", ".port_uo_out (uo_out),")
    fx.mutate(TOP, UO_MUX_HEAD, "wire [7:0] unused_readout = run_phase ? core_uo_out :")
    code, out = fx.run()
    assert code == 0 and "[metadata-capability] PASS" in out, out


@case("load CRC readout: a mux not selected by run_phase fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = !ui_in[7] ? core_uo_out :")
    expect_fail(fx, "core port_uo_out is not connected to the whole uo_out bus in run phase",
                "metadata-capability")


@case("load CRC readout: a run-phase arm that is not the core's port fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = run_phase ? (core_uo_out & 8'h7F) :")
    expect_fail(fx, "core port_uo_out is not connected to the whole uo_out bus in run phase",
                "metadata-capability")


@case("load CRC readout: the core's port left off uo_out altogether fails")
def _(fx):
    fx.mutate(TOP, UO_MUX_HEAD, "assign uo_out = run_phase ? pm_crc[7:0] :")
    expect_fail(fx, "core port_uo_out is not connected to the whole uo_out bus in run phase",
                "metadata-capability")


@case("runtime pin mode: a pin-mode register that does not reset to 0 fails")
def _(fx):
    fx.mutate("rtl/protocol_core.v", "uio_od       <= 8'h00;", "uio_od       <= 8'h81;")
    expect_fail(fx, "uio_od resets to 8'h81", "concrete-firmware-bench")


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


@case("a top-level uio_oe that drives a table input pin fails")
def _(fx):
    fx.mutate(TOP, RUNTIME_OE, "assign uio_oe = 8'h10;")
    expect_fail(fx, "uio[4] is an input in the table", "concrete-firmware-bench")


@case("no broad allow-mismatch switch exists")
def _(fx):
    fx.mutate("firmware/asm/uart_tx.asm", "LDI   R1, 1 ", "LDI   R1, 2 ")
    for flag in ("--allow-mismatch", "--ignore-mismatch", "--allow"):
        code, out = fx.run(flag)
        assert code == 2, f"{flag} should be a usage error, got {code}"


# ----------------------------------------------- concrete: assembly sites
@case("UART TX mask LDI mutated")
def _(fx):
    fx.mutate("firmware/asm/uart_tx.asm", "LDI   R1, 1 ", "LDI   R1, 2 ")
    expect_fail(fx, "firmware/asm/uart_tx.asm", "concrete-firmware-bench")


@case("UART program gains an OUT to uio_out")
def _(fx):
    fx.mutate("firmware/asm/uart_tx.asm", "OUT   UO_OUT, R1       ; TX idles HIGH",
              "OUT   UIO_OUT, R1       ; TX idles HIGH")
    expect_fail(fx, "OUT to port UIO_OUT", "concrete-firmware-bench")


@case("UART RX mask LDI mutated in each RX program")
def _(fx):
    for stem in ("uart_rx", "uart_rx_115200", "uart_rx_9600"):
        f = Fixture()
        try:
            f.mutate(f"firmware/asm/{stem}.asm", "LDI   R1, 2", "LDI   R1, 1")
            expect_fail(f, f"firmware/asm/{stem}.asm", "concrete-firmware-bench")
        finally:
            f.close()


@case("UART RX sampled from the wrong port")
def _(fx):
    fx.mutate("firmware/asm/uart_rx.asm", "IN    R2, UI_IN        ; SAMPLE (bit centre)",
              "IN    R2, UIO_IN        ; SAMPLE (bit centre)")
    expect_fail(fx, "IN from port UIO_IN", "concrete-firmware-bench")


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


@case("UART RX received byte copied to uio_out as well as uo_out")
def _(fx):
    fx.mutate("firmware/asm/uart_rx.asm", "OUT   UO_OUT, R0       ; emit the received byte",
              "OUT   UO_OUT, R0       ; emit the received byte\n        OUT   UIO_OUT, R0")
    expect_fail(fx, "OUT UIO_OUT, R0 is not a recognised bench-debug write", "concrete-firmware-bench")


@case("UART RX arbitrary constant written to uio_out")
def _(fx):
    fx.mutate("firmware/asm/uart_rx.asm", "LDI   R3, 0\n", "LDI   R3, 0x7E\n")
    expect_fail(fx, "OUT UIO_OUT, R3 writes 0x7E; bench_debug.uart_rx allows only 0, "
                    "SAMPLE_MARK 0x02 and FRAME_ERROR 0x04", "concrete-firmware-bench")


@case("UART RX frame-error flag shifted onto an undeclared uio_out bit")
def _(fx):
    fx.mutate("firmware/asm/uart_rx.asm",
              "SHF   R2, LEFT         ; -> UIO_OUT bit 2 (SHF leaves Z alone)",
              "SHF   R2, RIGHT        ; -> UIO_OUT bit 2 (SHF leaves Z alone)")
    expect_fail(fx, "is not a recognised bench-debug write", "concrete-firmware-bench")


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


@case("UART TX 9600 mask LDI mutated")
def _(fx):
    fx.mutate("firmware/asm/uart_tx_9600.asm", "LDI   R1, 1", "LDI   R1, 2")
    expect_fail(fx, "firmware/asm/uart_tx_9600.asm", "concrete-firmware-bench")


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


@case("SPI MISO mask LDI mutated")
def _(fx):
    fx.mutate("firmware/asm/spi_mode0.asm", "LDI   R1, 0x04            ; MISO mask (uio_in bit 2)",
              "LDI   R1, 0x01            ; MISO mask (uio_in bit 2)")
    expect_fail(fx, "firmware/asm/spi_mode0.asm", "concrete-firmware-bench")


@case("SPI pin image written to uo_out instead of uio_out")
def _(fx):
    fx.mutate("firmware/asm/spi_mode0.asm", "OUT   UIO_OUT, R2          ; CS falls",
              "OUT   UO_OUT, R2          ; CS falls")
    expect_fail(fx, "constant pin image 0x00 written to UO_OUT", "concrete-firmware-bench")


@case("SPI MISO sampled from the wrong port")
def _(fx):
    fx.mutate("firmware/asm/spi_mode1.asm", "IN    R3, UIO_IN", "IN    R3, UI_IN", count=100)
    expect_fail(fx, "IN from port UI_IN", "concrete-firmware-bench")


@case("I2C idle image mutated (SDA moved)")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast.asm", "LDI   R3, 0x0C        ; both lines released",
              "LDI   R3, 0x0A        ; both lines released")
    expect_fail(fx, "bus-idle image", "concrete-firmware-bench")


@case("I2C SDA mask register LDI mutated")
def _(fx):
    fx.mutate("firmware/asm/i2c_std.asm", "LDI   R1, 0x08", "LDI   R1, 0x40")
    expect_fail(fx, "firmware/asm/i2c_std.asm", "concrete-firmware-bench")


@case("I2C SCL poll mask mutated in a poll variant")
def _(fx):
    fx.mutate("firmware/asm/i2c_fast_sr_poll.asm", "LDI   R3, 0x04       ; poll mask",
              "LDI   R3, 0x02       ; poll mask")
    expect_fail(fx, "SCL poll mask", "concrete-firmware-bench")


@case("I2C generator string literal mutated")
def _(fx):
    fx.mutate("firmware/tools/gen_i2c_sr.py", '"LDI   R3, 0x04       ; poll mask"',
              '"LDI   R3, 0x02       ; poll mask"')
    expect_fail(fx, "firmware/tools/gen_i2c_sr.py", "concrete-firmware-bench")


# ------------------------------------------------- concrete: bench sites
@case("SPI bench CS/SCLK swap")
def _(fx):
    fx.mutate("verification/test_firmware_spi.py", "CS_BIT, SCLK_BIT, MOSI_BIT = 0, 3, 1",
              "CS_BIT, SCLK_BIT, MOSI_BIT = 3, 0, 1")
    expect_fail(fx, "verification/test_firmware_spi.py", "concrete-firmware-bench")


@case("SPI bench MISO pin/bit mutated")
def _(fx):
    fx.mutate("verification/test_firmware_spi.py", 'MISO_PIN, MISO_BIT = "uio_in", 2',
              'MISO_PIN, MISO_BIT = "uio_in", 3')
    expect_fail(fx, "MISO_PIN/MISO_BIT", "concrete-firmware-bench")


@case("SPI bench grades a line captured on uo_out")
def _(fx):
    fx.mutate("verification/test_firmware_spi.py", '"sclk": (LINE_PIN, SCLK_BIT)',
              '"sclk": ("uo_out", SCLK_BIT)')
    expect_fail(fx, "SCLK_BIT (captured on uo_out) is uo_out[3]", "concrete-firmware-bench")


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


@case("UART bench TX pin mutated")
def _(fx):
    fx.mutate("verification/test_firmware_uart.py", 'TX_PIN, TX_BIT = "uo_out", 0',
              'TX_PIN, TX_BIT = "uo_out", 4')
    expect_fail(fx, "TX_PIN/TX_BIT", "concrete-firmware-bench")


@case("I2C bench SCL/SDA constants mutated")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", 'SDA_PIN, SDA_BIT = "uio_out", 3',
              'SDA_PIN, SDA_BIT = "uio_out", 6')
    expect_fail(fx, "SDA_PIN/SDA_BIT", "concrete-firmware-bench")


@case("I2C bench line read on the wrong port")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", 'LINE_PIN = "uio_in"', 'LINE_PIN = "uio_out"')
    expect_fail(fx, "LINE_PIN", "concrete-firmware-bench")


@case("I2C bench grades a line captured on the wrong bit")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", '"sda": (LINE_PIN, SDA_BIT)',
              '"sda": (LINE_PIN, 6)')
    expect_fail(fx, '"sda": (LINE_PIN, SDA_BIT) capture spec', "concrete-firmware-bench")


@case("I2C bench board wired with a literal pin")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", "i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)",
              "i2c_board(dut, scl=SCL_BIT, sda=6)")
    expect_fail(fx, "i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)", "concrete-firmware-bench")


@case("I2C bench peripheral names a pad by literal")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", "pads.pull_low(SDA_BIT)", "pads.pull_low(6)")
    expect_fail(fx, "pads.pull_low(6, ...)", "concrete-firmware-bench")


@case("I2C bench bypasses the pad model by writing uio_in")
def _(fx):
    fx.mutate("verification/test_firmware_i2c.py", "                pads.pull_low(SDA_BIT)",
              "                pads.pull_low(SDA_BIT)\n                dut.uio_in.value = 0x01")
    expect_fail(fx, "writes dut.uio_in directly", "concrete-firmware-bench")


@case("I2C SR bench peripheral drives a pad named by literal")
def _(fx):
    fx.mutate("verification/test_firmware_i2c_sr.py", "pads.set_open_drain(SDA_BIT, sda_drive)",
              "pads.set_open_drain(6, sda_drive)")
    expect_fail(fx, "pads.set_open_drain(6, ...)", "concrete-firmware-bench")


@case("I2C SR bench wires its own board")
def _(fx):
    fx.mutate("verification/test_firmware_i2c_sr.py", "    pads = i2c_pads(dut).start()",
              "    pads = i2c_board(dut, scl=0, sda=6).start()")
    expect_fail(fx, "i2c_pads(dut)", "concrete-firmware-bench")


@case("I2C SR bench does not import the capture specs")
def _(fx):
    fx.mutate("verification/test_firmware_i2c_sr.py", "    CAPTURE_SPECS,\n", "")
    expect_fail(fx, "does not import CAPTURE_SPECS", "concrete-firmware-bench")


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


@case("ISA port table code mutated")
def _(fx):
    fx.mutate("firmware/tools/asm.py", '"UO_OUT":  (0b10,', '"UO_OUT":  (0b11,')
    expect_fail(fx, "ISA port UO_OUT", "concrete-firmware-bench")


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
        pin(t, "uio[2]")["shared_pin_rationale"] = ""
        pin(t, "ui_in[1]")["protocol_roles"]["spi_transfer"] = "MISO"
    fx.mutate_table(f)
    code, out = fx.run()
    assert code == 1 and "[schema] PASS" in out, out
    assert "MISO" in out and "spi_mode3.asm" in out, out


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
