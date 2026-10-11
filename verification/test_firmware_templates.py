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
            elif p == "i2c_rd":
                # poll variant: one sanctioned BZ warning per polled rise
                assert len(prog.warnings) == 10, (c.name, prog.warnings)
                assert all(" BZ " in w for w in prog.warnings), c.name
                assert ft.I2C_ADDR_MIN <= c.params["address"] <= ft.I2C_ADDR_MAX
                assert 1 <= len(c.params["stretch"]) <= len(ft.I2C_RD_SITES)
                for st in c.params["stretch"]:
                    lo, hi = ft.I2C_RD_DURATIONS[st["duration_class"]]
                    assert lo <= st["extra_cycles"] <= hi
                    assert st["fall"] == ft.I2C_RD_SITES[st["site"]]
            elif p == "uart_rx":
                # the committed receivers' three sanctioned handshake branches
                assert len(prog.warnings) == 3, (c.name, prog.warnings)
            else:
                assert prog.warnings == [], (c.name, prog.warnings)
            if p == "uart_rx":
                assert c.params["rx_pin"] == "ui_in[1]"
                assert c.params["program"] in ft.UART_RX_PROFILES
                assert c.params["period"] == ft.UART_RX_PROFILES[c.params["program"]]
                assert c.params["variation"] in ft.UART_RX_VARIATIONS
                assert 1 <= len(c.params["frames"]) <= ft.UART_RX_FRAMES_MAX
                datas = [f["data"] for f in c.params["frames"]]
                assert datas[0] != 0x00 and all(0 <= d <= 255 for d in datas)
                assert all(a != b for a, b in zip(datas, datas[1:])), c.name
                assert all(f["gap_bits"] in ft.UART_RX_GAPS for f in c.params["frames"])
                assert abs(c.params["scale"] - 1.0) <= 0.02 + 1e-9
                assert 0.0 <= c.params["jitter_frac"] <= 0.10
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
        m = ft.gen_i2c(SEED, i, mistime_low_delta=-30)
        assert m.source != ft.gen_i2c(SEED, i).source
        m.assemble()


def test_every_planned_bin_is_reachable_with_enough_cases():
    cov = ft.coverage([c for v in _all(n=400).values() for c in v])
    unhit = {t: [b for b, n in bins.items() if n == 0] for t, bins in cov.items()}
    assert not any(unhit.values()), unhit


def test_i2c_rd_schedule_and_image_reproducible_and_cycles_unchanged():
    """Same seed -> same source, image, cycle report and peripheral
    schedule; the budgets are the committed polling program's (the
    generator's defaults still reproduce the committed .asm)."""
    import asm

    a = ft.generate(SEED, "i2c_rd", 12)
    b = ft.generate(SEED, "i2c_rd", 12)
    for ca, cb in zip(a, b):
        assert ca.source == cb.source
        assert asm.render_cycles_report(ca.assemble()) == asm.render_cycles_report(
            cb.assemble()
        )
        assert ft.i2c_rd_schedule(ca) == ft.i2c_rd_schedule(cb)
    committed = {
        g: asm.assemble_file(REPO / "firmware" / "asm" / f"i2c_{g}_sr_poll.asm")
        for g in ("fast", "std")
    }
    for c in a:
        g = "fast" if c.params["grade"] == "i2c_fast" else "std"
        got = [(s.name, s.cycles) for s in c.assemble().sections]
        assert got == [(s.name, s.cycles) for s in committed[g].sections], c.name
        assert len(c.assemble().words) == len(committed[g].words)


def test_i2c_rd_non_polling_control_assembles_without_warnings():
    c = ft.gen_i2c_rd(SEED, 0, poll=False)
    assert c.assemble().warnings == []
    assert c.source != ft.gen_i2c_rd(SEED, 0).source


def test_uart_rx_uses_committed_programs_byte_for_byte():
    """Image selection: every case assembles to exactly the committed
    firmware/build image of its profile, and the period matches the program's
    own BIT-PERIOD-CYCLES header."""
    import asm

    for stem, period in ft.UART_RX_PROFILES.items():
        text = (REPO / "firmware" / "asm" / f"{stem}.asm").read_text()
        assert int(re.search(r"^; BIT-PERIOD-CYCLES (\d+)$", text, re.M).group(1)) == period
    seen = set()
    for c in ft.generate(SEED, "uart_rx", 9):
        committed = asm.assemble_file(REPO / "firmware" / "asm" / f"{c.params['program']}.asm")
        assert c.assemble().words == committed.words, c.name
        seen.add(c.params["period"])
    assert seen == {50, 434, 5208}


def test_uart_rx_default_sweep_covers_profiles_and_listed_unhit_bins():
    cov = ft.coverage(ft.generate(SEED, "uart_rx", ft.DEFAULT_CASES))
    assert all(n > 0 for n in cov["uart_rx.profile_cycles"].values())
    assert all(n > 0 for n in cov["uart_rx.profile_x_variation"].values())
    assert all(n > 0 for n in cov["uart_rx.byte_class"].values())
    assert set(cov["uart_rx.frame_spacing"]) == {"single", "gap1.0b", "gap2.5b"}


def test_uart_rx_mutants_and_replay():
    base = ft.gen_uart_rx(SEED, 0)
    mut = ft.gen_uart_rx(SEED, 0, mistime_wait_delta=2)
    assert mut.source != base.source and mut.params["frames"] == base.params["frames"]
    assert mut.assemble().words != base.assemble().words
    ctl = ft.gen_uart_rx(SEED, 0, force_frames=[0x80, 0x01], force_scale=1.10)
    assert ctl.params["scale"] == 1.10 and len(ctl.params["frames"]) == 2
    # replay from (seed, protocol, index) alone is byte-identical
    assert ft.gen_uart_rx(SEED, 7).source == ft.generate(SEED, "uart_rx", 20)[7].source
    assert ft.gen_uart_rx(SEED, 7).params == ft.generate(SEED, "uart_rx", 40)[7].params


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
