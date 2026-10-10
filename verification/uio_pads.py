"""Silicon-true `uio` pad model for the cocotb benches (issue #136; DR
0012 § Consequences, `spec/verification-plan.md` § 7).

What it models
--------------
A Tiny Tapeout bidirectional pin is three wires on the design side --
`uio_out[n]`, `uio_oe[n]`, `uio_in[n]` -- and one line on the board side.
The pad drives the line with `uio_out[n]` while `uio_oe[n]` is 1 and
leaves it alone while `uio_oe[n]` is 0; `uio_in[n]` always reads the
line. Whatever else sits on the line (a pull resistor, a peripheral)
decides its level whenever the pad is not driving.

Per pin this model keeps the three things that can set the line:

* the **design**: drives `uio_out[n]` iff `uio_oe[n]` is 1 (both read
  from the simulation, never assumed);
* an **external driver** (the peripheral model): drives 0, drives 1, or
  is released (`drive()` / `pull_low()` / `release()`);
* a **pull**: `"up"`, `"down"` or none. A pull only decides the level
  when nobody drives.

and resolves them into one level per pin, which it writes back on
`uio_in`. `resolve_pin()` is the whole rule and is a pure function, so
`test_uio_pad_resolution.py` checks its truth table without a simulator
(`npm run lint`); `test_uio_pads.py` checks the model on the real top.

    design drives, external released     -> design's value
    design released, external drives     -> external's value
    both drive the same value            -> that value
    both drive opposite values           -> 'x', and CONTENTION is recorded
    nobody drives, pull up / pull down   -> '1' / '0'
    nobody drives, no pull               -> 'z' (a floating input)
    `uio_oe` or a driven `uio_out` is x/z -> 'x' unless every reading of
                                            the unknown gives the same level

What this replaces
------------------
The I2C benches used to compose the bus themselves: `line = uio_out AND
uio_in`, with the peripheral's intent on `uio_in` and `uio_oe` never
read (DR 0008 § Context). That composition is what an open-drain bus
does *if* the pads implement open-drain, so it could not tell a chip
that drives the line from one that cannot -- and before DR 0012 the top
had `uio_oe = 8'h00`, i.e. it could not. Here the wired-AND is not
assumed anywhere: a line goes low only because some driver the model
knows about is enabled and driving 0.

Timing
------
The pad is combinational with zero delay. After any change of `uio_out`,
`uio_oe` or `uio_in` the model waits for the `ReadWrite` phase of the
same time step -- by then every delta cycle of that step has settled,
including the combinational `uio_oe` that follows `uio_out` one delta
later, and at gate level the whole clock tree -- and resolves once on the
settled values. So contention is judged on settled values only, never on
a delta-cycle glitch, and a level the design changes at a clock edge is
on `uio_in` before that time step's `ReadOnly` phase, where the benches
sample. External drivers change the line at the moment they call
`drive()` / `release()`.

Zero delay is a deliberate limit: this model says nothing about pad
propagation delay, slew, pull-up RC rise time or drive strength (the
pull-up always wins instantly against nothing, and loses instantly
against any driver). Those are electrical questions for the pad cells'
own characterisation, not for a functional bench.

Reset
-----
What a previous program left enabled is not a fact about the next run, so
the model starts its record afresh each time `rst_n` is released: the
contention log and the `oe_seen` / `drove_*` / `oe_unknown` masks then
describe the time since that release, beginning with the state at the
release instant itself, and `resets` counts the releases seen. A bench
that loads a program therefore reads "no pad enabled since reset" as
`resets == 1 and oe_seen == 0` right after the load. The interval while
`rst_n` is low is not covered by these masks (it would carry over
whatever the previous program was doing when reset was asserted);
`test_control_space.py` asserts `uio_oe == 0` in reset directly.

The model owns `uio_in` while it runs: a write from anywhere else (for
example the `uio_in = 0` in `test_protocol_emulator.load_program`) is
overwritten with the resolved value in the same time step.

Plain helper module -- no `@cocotb.test()` here, so cocotb registers
nothing from importing it. cocotb itself is imported lazily, so the
resolver stays importable where cocotb is not installed (`npm run lint`).
"""

from __future__ import annotations

from dataclasses import dataclass

PINS = 8

#: Levels a line (or a design-side bit) can take.
LEVELS = ("0", "1", "x", "z")


def _design_candidates(oe: str, out: str) -> list:
    """Every drive the design might be applying, given possibly-unknown
    `uio_oe` / `uio_out` bits: None = not driving, '0'/'1' = driving that
    level, 'x' = driving an unknown level."""
    if oe == "0":
        return [None]
    driven = out if out in ("0", "1") else "x"
    if oe == "1":
        return [driven]
    return [None, driven]  # oe is x/z: it may or may not be driving


def _resolve_known(design, ext, pull):
    """(level, contention) for one definite design drive."""
    ext_level = None if ext is None else str(ext)
    if design is None:
        if ext_level is not None:
            return ext_level, False
        if pull == "up":
            return "1", False
        if pull == "down":
            return "0", False
        return "z", False
    if ext_level is None:
        return design, False
    if design == "x":
        return "x", False  # unknown drive against a driver: unknown line
    if design == ext_level:
        return design, False
    return "x", True


def resolve_pin(oe: str, out: str, ext, pull) -> tuple:
    """Resolve one pad. `oe` / `out` are the design's `uio_oe[n]` and
    `uio_out[n]` as one of '0', '1', 'x', 'z'; `ext` is the external
    driver (None = released, 0 or 1 = driving); `pull` is "up", "down" or
    None. Returns `(level, contention)`: the line level as one of
    '0', '1', 'x', 'z', and whether the design and the external driver
    are definitely driving opposite values.

    Contention is only ever reported for *known* opposite drives. An
    unknown `uio_oe` yields an 'x' line when the two readings disagree,
    but is not called contention -- before reset every design-side bit is
    'x', and flagging that would make the detector useless."""
    if oe not in LEVELS or out not in LEVELS:
        raise ValueError(f"oe/out must be one of {LEVELS}, got {oe!r}/{out!r}")
    if ext not in (None, 0, 1):
        raise ValueError(f"ext must be None, 0 or 1, got {ext!r}")
    if pull not in (None, "up", "down"):
        raise ValueError(f"pull must be None, 'up' or 'down', got {pull!r}")
    results = [_resolve_known(d, ext, pull) for d in _design_candidates(oe, out)]
    if len(results) == 1:
        return results[0]
    levels = {level for level, _ in results}
    if len(levels) == 1:
        return levels.pop(), False
    return "x", False


@dataclass(frozen=True)
class Contention:
    """One episode of the design and the external driver fighting."""

    t_ns: float
    pin: int
    design_level: int
    external_level: int

    def __str__(self) -> str:
        return (
            f"uio[{self.pin}] contention at {self.t_ns} ns: design drives "
            f"{self.design_level}, external drives {self.external_level}"
        )


class PadContention(AssertionError):
    """Raised by `UioPads.assert_no_contention()`."""


def _bits(value) -> str:
    """A cocotb LogicArray (or anything whose `str()` is its binary
    string, MSB first) as 8 lower-case level characters."""
    text = str(value).lower()
    if len(text) != PINS or any(c not in LEVELS for c in text):
        # weak/unknown strengths ('u', 'w', 'l', 'h', '-') are not levels
        # this model can resolve; treat them as unknown
        text = "".join(c if c in LEVELS else "x" for c in text).rjust(PINS, "x")
    return text


class UioPads:
    """The eight `uio` pads of the Tiny Tapeout top (or of `test/tb.v`,
    which exposes the same three names for a gate-level run).

    `pulls` maps a pin number to "up" or "down". `tie` maps a pin number
    to a level the external side drives from the start (how a board ties
    an unused pin off). Both default to nothing, i.e. floating lines.
    """

    def __init__(self, dut, pulls=None, tie=None, name="uio"):
        self.dut = dut
        self.name = name
        self.pulls = [None] * PINS
        for pin, pull in (pulls or {}).items():
            self._check_pin(pin)
            if pull not in ("up", "down"):
                raise ValueError(f"pull for uio[{pin}] must be 'up' or 'down'")
            self.pulls[pin] = pull
        self.ext = [None] * PINS
        for pin, level in (tie or {}).items():
            self._check_pin(pin)
            if level not in (0, 1):
                raise ValueError(f"tie level for uio[{pin}] must be 0 or 1")
            self.ext[pin] = level
        self.levels = ["x"] * PINS
        self.contention = []
        self._contending = [False] * PINS
        self._tasks = []
        #: releases of `rst_n` seen while running (see "Reset" above)
        self.resets = 0
        self.clear_stats()

    # ---- statistics: what the design's pads were seen doing -----------

    def clear_stats(self) -> None:
        """Forget what has been observed so far (not the contention log).
        The model does this itself, and clears the contention log too, at
        every release of `rst_n`."""
        #: pins the design was seen driving at all (`uio_oe[n]` = 1)
        self.oe_seen = 0
        #: pins the design was seen driving low / high
        self.drove_low = 0
        self.drove_high = 0
        #: pins whose `uio_oe` was seen unknown (x/z)
        self.oe_unknown = 0
        #: number of resolutions performed
        self.resolutions = 0

    # ---- external side -------------------------------------------------

    @staticmethod
    def _check_pin(pin) -> None:
        if not isinstance(pin, int) or not 0 <= pin < PINS:
            raise ValueError(f"uio pin must be 0..{PINS - 1}, got {pin!r}")

    def drive(self, pin: int, level: int) -> None:
        """External driver on `pin` drives `level` (push-pull)."""
        self._check_pin(pin)
        if level not in (0, 1):
            raise ValueError(f"level must be 0 or 1, got {level!r}")
        if self.ext[pin] != level:
            self.ext[pin] = level
            self._refresh()

    def release(self, pin: int) -> None:
        """External driver on `pin` stops driving."""
        self._check_pin(pin)
        if self.ext[pin] is not None:
            self.ext[pin] = None
            self._refresh()

    def pull_low(self, pin: int) -> None:
        """An open-drain peripheral asserting the line: drive 0."""
        self.drive(pin, 0)

    def set_open_drain(self, pin: int, level: int) -> None:
        """An open-drain peripheral's output: 0 pulls low, 1 releases."""
        if level:
            self.release(pin)
        else:
            self.pull_low(pin)

    # ---- the line --------------------------------------------------------

    def line(self, pin: int) -> str:
        """The resolved line as '0', '1', 'x' or 'z'."""
        self._check_pin(pin)
        return self.levels[pin]

    def level(self, pin: int) -> int:
        """The resolved line as 0 or 1. Raises if it is 'x' or 'z': a
        caller that asks for a logic level has a pull or a driver on the
        line, so anything else is a bench or design fault worth stopping
        on."""
        value = self.line(pin)
        if value not in ("0", "1"):
            raise ValueError(
                f"{self.name}[{pin}] is {value!r}, not a logic level "
                f"(contention so far: {[str(c) for c in self.contention]})"
            )
        return int(value)

    def assert_no_contention(self) -> None:
        if self.contention:
            raise PadContention(
                f"{len(self.contention)} contention episode(s): "
                + "; ".join(str(c) for c in self.contention)
            )

    # ---- running ---------------------------------------------------------

    def start(self):
        """Resolve once now and keep `uio_in` resolved until `stop()`.
        Must not be called in the ReadOnly phase (it writes `uio_in`)."""
        import cocotb

        if self._tasks:
            raise RuntimeError("pad model already running")
        self._refresh()
        self._tasks = [
            cocotb.start_soon(self._run()),
            cocotb.start_soon(self._watch_reset()),
        ]
        return self

    def stop(self) -> None:
        """Stop resolving. `uio_in` keeps its last value."""
        for task in self._tasks:
            # `kill()`, as the sibling benches stop their drivers: under
            # cocotb 2.1 `cancel()` on a task parked in `First(...)` is
            # reported as "cancelled, but continued running".
            task.kill()
        self._tasks = []

    async def _run(self):
        from cocotb.triggers import First, ReadWrite, ValueChange

        dut = self.dut
        while True:
            await First(
                ValueChange(dut.uio_out),
                ValueChange(dut.uio_oe),
                ValueChange(dut.uio_in),
            )
            # Every delta cycle of this time step has run by ReadWrite:
            # resolve once, on settled values.
            await ReadWrite()
            self._refresh()

    async def _watch_reset(self):
        from cocotb.triggers import ReadWrite, RisingEdge

        while True:
            await RisingEdge(self.dut.rst_n)
            await ReadWrite()
            self.resets += 1
            self.contention = []
            self._contending = [False] * PINS
            self.clear_stats()
            self._refresh()  # the release instant is part of the record

    def _refresh(self) -> None:
        from cocotb.types import LogicArray
        from cocotb.utils import get_sim_time

        dut = self.dut
        oe = _bits(dut.uio_oe.value)
        out = _bits(dut.uio_out.value)
        self.resolutions += 1
        levels = []
        for pin in range(PINS):
            o, v = oe[PINS - 1 - pin], out[PINS - 1 - pin]
            if o == "1":
                self.oe_seen |= 1 << pin
                if v == "0":
                    self.drove_low |= 1 << pin
                elif v == "1":
                    self.drove_high |= 1 << pin
            elif o != "0":
                self.oe_unknown |= 1 << pin
            level, fight = resolve_pin(o, v, self.ext[pin], self.pulls[pin])
            if fight and not self._contending[pin]:
                event = Contention(
                    float(get_sim_time("ns")), pin, int(v), self.ext[pin]
                )
                self.contention.append(event)
                dut._log.error(f"pad model: {event}")
            self._contending[pin] = fight
            levels.append(level)
        self.levels = levels
        resolved = "".join(reversed(levels))
        if _bits(dut.uio_in.value) != resolved:
            dut.uio_in.value = LogicArray(resolved)


# ---------------------------------------------------------------------------
# The I2C board: what the I2C benches hang on the pads
# ---------------------------------------------------------------------------


def i2c_board(dut, scl: int, sda: int) -> UioPads:
    """Pads as an I2C board wires them: a pull-up on the SCL line and on
    the SDA line, and the six other `uio` lines tied low. The tie-off is
    a strong driver, so firmware that drove any of them high would be
    reported as contention rather than pass unnoticed. Not started.

    Which pins are SCL and SDA is the caller's to say, and this module
    deliberately holds no copy: the pin plan lives in DR 0010's table and
    in `test_firmware_i2c.py`'s `SCL_BIT` / `SDA_BIT`, which
    `scripts/check_protocol_pin_roles.py` checks against each other."""
    UioPads._check_pin(scl)
    UioPads._check_pin(sda)
    if scl == sda:
        raise ValueError("SCL and SDA must be different pins")
    pads = UioPads(
        dut,
        pulls={scl: "up", sda: "up"},
        tie={pin: 0 for pin in range(PINS) if pin not in (scl, sda)},
        name="i2c-board",
    )
    #: `UIO_OD` value an I2C program must have written: SCL | SDA.
    pads.i2c_mask = (1 << scl) | (1 << sda)
    return pads


def assert_i2c_open_drain(pads: UioPads, tag: str) -> None:
    """After an I2C run on `i2c_board()`: the design drove exactly SCL and
    SDA, only ever low (that is what open-drain means at a pad), with no
    unknown `uio_oe` and no contention."""
    mask = pads.i2c_mask
    pads.assert_no_contention()
    assert pads.oe_unknown == 0, (
        f"{tag}: uio_oe was unknown on pins 0x{pads.oe_unknown:02x} during the run"
    )
    assert pads.oe_seen == mask, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen:02x}; an I2C "
        f"controller must drive exactly SCL|SDA = 0x{mask:02x} "
        "(0x00 means UIO_OD was never written: the chip cannot pull a line low)"
    )
    assert pads.drove_high == 0, (
        f"{tag}: the design drove uio pins 0x{pads.drove_high:02x} HIGH; "
        "open-drain pads only ever pull low"
    )
    assert pads.drove_low == mask, (
        f"{tag}: the design pulled pins 0x{pads.drove_low:02x} low, expected "
        f"both SCL and SDA (0x{mask:02x})"
    )


# ---------------------------------------------------------------------------
# The SPI board: what the SPI benches hang on the pads (issue #155)
# ---------------------------------------------------------------------------


def spi_board(dut, cs: int, sclk: int, mosi: int, miso: int) -> UioPads:
    """Pads as an SPI peripheral board wires them: the controller's CS,
    SCLK and MOSI lines are the design's to drive (push-pull, DR 0012's
    `UIO_DIR`), MISO is driven by the peripheral (the caller's coroutine,
    through `drive()`), and the other four `uio` lines are tied low. CS
    carries a pull-up and SCLK / MOSI pull-downs, so each line has a level
    before the program enables its drivers: an undriven CS reads
    deasserted, which is how a chip-select line is normally biased. The
    tie-off is a strong driver, so firmware that drove any other pin high
    is reported as contention. MISO starts driven low. Not started.

    Which pins are which is the caller's to say, and this module holds no
    copy: the pin plan lives in DR 0010's table and in
    `test_firmware_spi.py`'s `CS_BIT` / `SCLK_BIT` / `MOSI_BIT` /
    `MISO_BIT`, which `scripts/check_protocol_pin_roles.py` checks."""
    pins = (cs, sclk, mosi, miso)
    for pin in pins:
        UioPads._check_pin(pin)
    if len(set(pins)) != 4:
        raise ValueError("CS, SCLK, MOSI and MISO must be four different pins")
    tie = {pin: 0 for pin in range(PINS) if pin not in (cs, sclk, mosi)}
    pads = UioPads(
        dut,
        pulls={cs: "up", sclk: "down", mosi: "down"},
        tie=tie,  # includes MISO: the peripheral's output, low until it drives
        name="spi-board",
    )
    #: `UIO_DIR` value an SPI controller program must have written.
    pads.spi_mask = (1 << cs) | (1 << sclk) | (1 << mosi)
    #: Pins every transfer drives both high and low.
    pads.spi_toggled = (1 << cs) | (1 << sclk)
    return pads


def assert_spi_push_pull(pads: UioPads, tag: str) -> None:
    """After an SPI run on `spi_board()`: the design drove exactly CS,
    SCLK and MOSI (push-pull: CS and SCLK seen driven both high and low),
    never MISO or a tied pin, with no unknown `uio_oe` and no
    contention."""
    mask = pads.spi_mask
    pads.assert_no_contention()
    assert pads.oe_unknown == 0, (
        f"{tag}: uio_oe was unknown on pins 0x{pads.oe_unknown:02x} during the run"
    )
    assert pads.oe_seen == mask, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen:02x}; an SPI "
        f"controller must drive exactly CS|SCLK|MOSI = 0x{mask:02x} "
        "(0x00 means UIO_DIR was never written: no line reaches the peripheral)"
    )
    both = pads.spi_toggled
    assert pads.drove_high & both == both and pads.drove_low & both == both, (
        f"{tag}: the design drove pins 0x{pads.drove_high:02x} high and "
        f"0x{pads.drove_low:02x} low; CS and SCLK (0x{both:02x}) must each be "
        "driven both ways in any transfer (MOSI only if the payload has both "
        "bit values)"
    )
