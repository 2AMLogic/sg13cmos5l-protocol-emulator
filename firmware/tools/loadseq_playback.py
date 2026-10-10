"""Pin-sequence playback for the direct MODE-high program load (issue #118).

MicroPython-compatible on purpose: no typing, no dataclasses, no f-strings,
no pathlib, no stdlib module beyond what every MicroPython port has (this
file imports nothing). It only turns a step list into adapter calls; the
step list itself comes from `loadseq.py` (host side), either imported or
as the `--format python` output (`VERSION`, `STEPS`).

Nothing here talks to a board. A board binding is an *adapter* object with
exactly these methods (a concrete SDK binding is out of scope):

    set_ui_in(byte)    drive ui_in[7:0]
    set_uio_in(byte)   drive uio_in[7:0]
    set_rst_n(value)   drive rst_n (0 or 1)
    set_ena(value)     drive ena (0 or 1)
    set_clk(value)     drive clk (0 or 1)
    wait_us(duration)  block for `duration` microseconds

Prerequisite the adapter's owner must satisfy: the board's automatic clock
must be stopped before `play()` and manual clock control (`set_clk`) kept
through the MODE-drop step, which is the last step. The load protocol shifts
one bit on *every* clock edge, so a free-running clock would corrupt it.

Per step (one clock cycle), with clk low: set ena, uio_in, ui_in, rst_n;
wait `setup_us`; clk high; wait `high_us`; clk low; wait `low_us`. `play()`
first drives clk low. A rejected argument or step raises ValueError before
any adapter call is made.

After a re-select of the chip, SRAM contents are not assumed to survive:
replay the same sequence from the start (it begins with the reset pulse).
"""

VERSION = 1
STEP_BYTES = 4  # ui_in, uio_in, rst_n, ena


def decode_steps(blob):
    """bytes (4 per step: ui_in, uio_in, rst_n, ena) -> list of tuples."""
    if len(blob) % STEP_BYTES:
        raise ValueError("step blob length is not a multiple of 4")
    return [tuple(blob[i:i + STEP_BYTES]) for i in range(0, len(blob), STEP_BYTES)]


def encode_steps(steps):
    out = bytearray()
    for step in steps:
        out.extend(bytes(step))
    return bytes(out)


def _check_steps(steps):
    if not steps:
        raise ValueError("empty step list")
    for n, step in enumerate(steps):
        if len(step) != STEP_BYTES:
            raise ValueError("step %d: want 4 fields" % n)
        ui_in, uio_in, rst_n, ena = step
        if not (0 <= ui_in <= 255 and 0 <= uio_in <= 255):
            raise ValueError("step %d: ui_in/uio_in out of byte range" % n)
        if rst_n not in (0, 1) or ena not in (0, 1):
            raise ValueError("step %d: rst_n/ena must be 0 or 1" % n)


def _check_us(name, value):
    if not (value > 0):
        raise ValueError("%s must be positive, got %r" % (name, value))


def iter_ops(steps, setup_us=10, high_us=10, low_us=10):
    """Yield (method_name, argument) operations in playback order."""
    _check_steps(steps)
    _check_us("setup_us", setup_us)
    _check_us("high_us", high_us)
    _check_us("low_us", low_us)
    return _ops(steps, setup_us, high_us, low_us)


def _ops(steps, setup_us, high_us, low_us):
    yield ("set_clk", 0)
    for ui_in, uio_in, rst_n, ena in steps:
        yield ("set_ena", ena)
        yield ("set_uio_in", uio_in)
        yield ("set_ui_in", ui_in)
        yield ("set_rst_n", rst_n)
        yield ("wait_us", setup_us)
        yield ("set_clk", 1)
        yield ("wait_us", high_us)
        yield ("set_clk", 0)
        yield ("wait_us", low_us)


def play(adapter, steps, setup_us=10, high_us=10, low_us=10):
    """Play `steps` on `adapter`. Validates everything before the first call."""
    for name, arg in iter_ops(steps, setup_us, high_us, low_us):
        getattr(adapter, name)(arg)


class MockAdapter:
    """Records every call as (method_name, argument); the example adapter."""

    def __init__(self):
        self.calls = []

    def set_ui_in(self, byte):
        self.calls.append(("set_ui_in", byte))

    def set_uio_in(self, byte):
        self.calls.append(("set_uio_in", byte))

    def set_rst_n(self, value):
        self.calls.append(("set_rst_n", value))

    def set_ena(self, value):
        self.calls.append(("set_ena", value))

    def set_clk(self, value):
        self.calls.append(("set_clk", value))

    def wait_us(self, duration):
        self.calls.append(("wait_us", duration))
