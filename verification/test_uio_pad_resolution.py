#!/usr/bin/env python3
"""Simulator-free unit tests for the pad model's resolution rule
(`uio_pads.resolve_pin`, issue #136).

Run directly (`python3 verification/test_uio_pad_resolution.py`, as `npm
run lint` does) or under pytest. `uio_pads.py` imports cocotb lazily, so
this needs nothing but Python 3.

The truth table below is written out by hand from the module docstring
of `uio_pads.py`, case by case, rather than computed: a table derived
from the function it checks would agree with it by construction.
"""

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uio_pads  # noqa: E402
from uio_pads import resolve_pin  # noqa: E402

UP, DOWN = "up", "down"

#: (oe, out, ext, pull) -> (level, contention), every known-drive case.
KNOWN = {
    # pad is an input: the board decides; uio_out is irrelevant
    ("0", "0", None, None): ("z", False),
    ("0", "1", None, None): ("z", False),
    ("0", "0", None, UP): ("1", False),
    ("0", "1", None, UP): ("1", False),
    ("0", "0", None, DOWN): ("0", False),
    ("0", "1", None, DOWN): ("0", False),
    ("0", "0", 0, None): ("0", False),
    ("0", "1", 0, None): ("0", False),
    ("0", "0", 1, None): ("1", False),
    ("0", "1", 1, None): ("1", False),
    # an external driver beats either pull
    ("0", "1", 0, UP): ("0", False),
    ("0", "0", 0, UP): ("0", False),
    ("0", "0", 1, DOWN): ("1", False),
    ("0", "1", 1, DOWN): ("1", False),
    ("0", "0", 1, UP): ("1", False),
    ("0", "1", 1, UP): ("1", False),
    ("0", "0", 0, DOWN): ("0", False),
    ("0", "1", 0, DOWN): ("0", False),
    # pad drives, nothing else does: the pad's value, whatever the pull
    ("1", "0", None, None): ("0", False),
    ("1", "1", None, None): ("1", False),
    ("1", "0", None, UP): ("0", False),
    ("1", "1", None, UP): ("1", False),
    ("1", "0", None, DOWN): ("0", False),
    ("1", "1", None, DOWN): ("1", False),
    # both drive the same level
    ("1", "0", 0, None): ("0", False),
    ("1", "1", 1, None): ("1", False),
    ("1", "0", 0, UP): ("0", False),
    ("1", "1", 1, UP): ("1", False),
    ("1", "0", 0, DOWN): ("0", False),
    ("1", "1", 1, DOWN): ("1", False),
    # both drive, opposite levels: contention, whatever the pull
    ("1", "0", 1, None): ("x", True),
    ("1", "1", 0, None): ("x", True),
    ("1", "0", 1, UP): ("x", True),
    ("1", "1", 0, UP): ("x", True),
    ("1", "0", 1, DOWN): ("x", True),
    ("1", "1", 0, DOWN): ("x", True),
}


def test_known_drive_truth_table_is_complete_and_holds():
    cases = set(itertools.product("01", "01", (None, 0, 1), (None, UP, DOWN)))
    assert cases == set(KNOWN), "the hand-written table must cover every case"
    for (oe, out, ext, pull), want in KNOWN.items():
        got = resolve_pin(oe, out, ext, pull)
        assert got == want, f"oe={oe} out={out} ext={ext} pull={pull}: {got} != {want}"


def test_open_drain_bus_is_a_wired_and():
    """The property the I2C benches used to assume, derived here from the
    pad rule instead: with a pull-up, a design pad in DR 0012's open-drain
    mode (`uio_oe = ~uio_out`) and an open-drain peripheral (drives 0 or
    lets go), the line is `design AND peripheral` and nobody can contend."""
    for design, peripheral in itertools.product((0, 1), repeat=2):
        oe, out = ("1", "0") if design == 0 else ("0", "1")
        ext = 0 if peripheral == 0 else None
        level, fight = resolve_pin(oe, out, ext, UP)
        assert level == str(design & peripheral) and not fight


def test_without_output_enable_the_design_cannot_pull_low():
    """`uio_oe = 0` (UIO_OD and UIO_DIR at reset): whatever `uio_out`
    says, the pulled-up line stays high. This is the case the
    bench-composed bus (`line = uio_out AND uio_in`) got wrong."""
    for out in "01":
        assert resolve_pin("0", out, None, UP) == ("1", False)


def test_unknown_design_side():
    # oe unknown: 'x' when the two readings disagree, never contention
    assert resolve_pin("x", "0", None, UP) == ("x", False)
    assert resolve_pin("z", "0", None, UP) == ("x", False)
    assert resolve_pin("x", "1", None, None) == ("x", False)
    assert resolve_pin("x", "1", 0, None) == ("x", False)
    # ... and the common level when they agree
    assert resolve_pin("x", "1", None, UP) == ("1", False)
    assert resolve_pin("x", "0", None, DOWN) == ("0", False)
    assert resolve_pin("x", "0", 0, UP) == ("0", False)
    # power-up: everything unknown, pulled-up line is unknown, no contention
    assert resolve_pin("x", "x", None, UP) == ("x", False)
    assert resolve_pin("x", "x", 0, None) == ("x", False)
    # driving an unknown value
    assert resolve_pin("1", "x", None, UP) == ("x", False)
    assert resolve_pin("1", "z", 1, None) == ("x", False)
    # an input pad does not care what uio_out is
    assert resolve_pin("0", "x", None, UP) == ("1", False)
    assert resolve_pin("0", "x", 0, UP) == ("0", False)
    assert resolve_pin("0", "x", None, None) == ("z", False)


def test_contention_is_only_ever_known_opposite_drives():
    for oe, out, ext, pull in itertools.product(
        "01xz", "01xz", (None, 0, 1), (None, UP, DOWN)
    ):
        level, fight = resolve_pin(oe, out, ext, pull)
        assert level in uio_pads.LEVELS
        opposite = oe == "1" and out in "01" and ext is not None and int(out) != ext
        assert fight == opposite, (oe, out, ext, pull, level, fight)
        if fight:
            assert level == "x"


def test_bad_arguments_are_rejected():
    for args in (("2", "0", None, None), ("0", "q", None, None),
                 ("0", "0", 2, None), ("0", "0", "0", None),
                 ("0", "0", None, "sideways")):
        try:
            resolve_pin(*args)
        except ValueError:
            continue
        raise AssertionError(f"resolve_pin{args} did not raise")


def test_constructor_and_external_side_validate():
    for kwargs in ({"pulls": {8: "up"}}, {"pulls": {0: "sideways"}},
                   {"tie": {0: 2}}, {"tie": {-1: 0}}):
        try:
            uio_pads.UioPads(None, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"UioPads(**{kwargs}) did not raise")
    pads = uio_pads.UioPads(None, pulls={0: "up"}, tie={3: 1})
    assert pads.pulls[0] == "up" and pads.ext[3] == 1 and pads.ext[0] is None
    for call in (lambda: pads.drive(8, 0), lambda: pads.drive(0, 2),
                 lambda: pads.release(-1), lambda: pads.line(9)):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("an out-of-range pad call did not raise")


def test_i2c_board_wiring():
    board = uio_pads.i2c_board(None, scl=0, sda=7)
    assert board.pulls == ["up", None, None, None, None, None, None, "up"]
    assert board.ext == [None, 0, 0, 0, 0, 0, 0, None]
    assert board.i2c_mask == 0x81
    # the pins are the caller's: nothing in the module assumes 0 and 7
    board = uio_pads.i2c_board(None, scl=3, sda=2)
    assert board.pulls == [None, None, "up", "up", None, None, None, None]
    assert board.ext == [0, 0, None, None, 0, 0, 0, 0]
    assert board.i2c_mask == 0x0C
    for scl, sda in ((0, 0), (8, 1), (0, -1)):
        try:
            uio_pads.i2c_board(None, scl=scl, sda=sda)
        except ValueError:
            continue
        raise AssertionError(f"i2c_board(scl={scl}, sda={sda}) did not raise")


def test_bits_normalisation():
    assert uio_pads._bits("0000ZzXx") == "0000zzxx"
    assert uio_pads._bits("10101010") == "10101010"
    assert uio_pads._bits("1010UW-H") == "1010xxxx"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"PASS: {len(tests)} pad-resolution tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
