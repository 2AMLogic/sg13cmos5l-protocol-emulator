#!/usr/bin/env python3
"""Simulator-free unit tests for `firmware_templates.py` (issue #93).

Run directly (`python3 verification/test_firmware_templates.py`) or under
pytest. Covers: determinism, prefix-stability of larger sweeps, legal
parameter bounds, clean assembly (zero warnings; exactly the one
sanctioned ACK-branch warning for I2C), image size, full cover-bin
reachability, the seed mirrored between the bench and the request, and
that the committed firmware images are still fresh.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import firmware_templates as ft  # noqa: E402

SEED = 20261009


def _all(seed=SEED, n=ft.DEFAULT_CASES):
    return {p: ft.generate(seed, p, n) for p in ft.PROTOCOLS}


def test_default_size_is_modest():
    assert ft.DEFAULT_CASES <= 20
    assert all(len(v) <= 20 for v in _all().values())


def test_deterministic_byte_for_byte():
    a, b = _all(), _all()
    for p in ft.PROTOCOLS:
        assert [c.source for c in a[p]] == [c.source for c in b[p]]
        for ca, cb in zip(a[p], b[p]):
            pa, pb = ca.assemble(), cb.assemble()
            assert pa.words == pb.words
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        for d in (d1, d2):
            assert ft.main(["--seed", str(SEED), "--out", d]) == 0
        for f in sorted(Path(d1).iterdir()):
            assert f.read_bytes() == (Path(d2) / f.name).read_bytes(), f.name


def test_different_seed_differs():
    assert [c.source for c in ft.generate(SEED, "spi", 8)] != [
        c.source for c in ft.generate(SEED + 1, "spi", 8)
    ]


def test_larger_sweep_only_appends():
    for p in ft.PROTOCOLS:
        small = [c.source for c in ft.generate(SEED, p, 5)]
        big = [c.source for c in ft.generate(SEED, p, 30)]
        assert big[:5] == small


def test_bounds_and_clean_assembly():
    for p, cases in _all().items():
        for c in cases:
            prog = c.assemble()
            assert len(prog.words) <= 256, c.name
            if p == "i2c":
                assert len(prog.warnings) == 1 and "BNZ" in prog.warnings[0], c.name
                assert ft.I2C_ADDR_MIN <= c.params["address"] <= ft.I2C_ADDR_MAX
                assert c.params["grade"] in ft.I2C_GRADES
            else:
                assert prog.warnings == [], (c.name, prog.warnings)
            if p == "uart":
                assert c.params["period"] in ft.UART_PERIODS
                assert 1 <= len(c.params["payloads"]) <= ft.UART_FRAMES_MAX
            if p == "spi":
                assert c.params["half_period"] in ft.SPI_HALF_PERIODS
                assert c.params["half_period"] >= 2  # SCLK <= f_clk/4
                assert 0 <= c.params["mode"] <= 3
                assert 1 <= len(c.params["mosi"]) <= ft.SPI_BURSTS_MAX


def test_cycle_sections_match_templates():
    """The templates' own cycle budgets (not the models'): SPI sections
    are 8 bits x 2 half-periods; UART loop bodies are the bit period."""
    for c in ft.generate(SEED, "spi", 8):
        rep = asm_report(c)
        g = c.params["half_period"]
        secs = re.findall(r"^CYCLES name=spi_rand_b\d+ .* cycles=(\d+) ", rep, re.M)
        assert secs and all(int(s) == 16 * g for s in secs), (c.name, secs)
    for c in ft.generate(SEED, "uart", 8):
        rep = asm_report(c)
        secs = re.findall(r"^CYCLES name=uart_bit_frame\d+ .* cycles=(\d+) ", rep, re.M)
        assert secs and all(int(s) == c.params["period"] for s in secs), (c.name, secs)


def asm_report(case):
    import asm

    return asm.render_cycles_report(case.assemble())


def test_mutants_differ_from_base():
    assert ft.gen_uart(SEED, 1, mistime_delta=-3).source != ft.gen_uart(SEED, 1).source
    assert ft.gen_spi(SEED, 0, flip_idle=1).source != ft.gen_spi(SEED, 0).source
    for i in (0, 1):
        m = ft.gen_i2c(SEED, i, mistime_low_delta=-10)
        assert m.source != ft.gen_i2c(SEED, i).source
        m.assemble()


def test_every_planned_bin_is_reachable_with_enough_cases():
    cov = ft.coverage([c for v in _all(n=400).values() for c in v])
    unhit = {t: [b for b, n in bins.items() if n == 0] for t, bins in cov.items()}
    assert not any(unhit.values()), unhit


def test_unhit_bins_are_listed_not_omitted():
    cov = ft.coverage(ft.generate(SEED, "i2c", 1))
    assert set(cov["i2c.grade_x_addr_x_data"]) == set(
        ft.planned_bin_universe()["i2c.grade_x_addr_x_data"]
    )
    assert sum(1 for n in cov["i2c.grade_x_addr_x_data"].values() if n == 0) > 0


def test_seed_matches_request():
    bench = (HERE / "test_random_regression.py").read_text()
    seed = int(re.search(r"^RECORDED_SEED = (\d+)$", bench, re.M).group(1))
    request = json.loads((HERE / "request-random-regression.json").read_text())
    assert request["options"]["random_seed"] == seed == SEED


def test_committed_firmware_untouched():
    for src in sorted((REPO / "firmware" / "asm").glob("*.asm")):
        r = subprocess.run(
            [sys.executable, str(REPO / "firmware" / "tools" / "asm.py"), str(src), "--check"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, (src.name, r.stdout, r.stderr)


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK:   {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL: {name}: {exc!r}")
    print("PASS" if not failures else f"FAIL: {failures} test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
