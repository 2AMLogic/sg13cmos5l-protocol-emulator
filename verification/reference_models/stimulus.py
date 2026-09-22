"""Constrained-random stimulus generators and deterministic negative
controls for the protocol reference models (issue #25, verification-plan.md
section 4).

Every generator takes a seeded ``random.Random`` and produces only
**legal** traffic along the constrained-random dimensions the verification
plan names per protocol:

* UART -- baud across the ratified 9,600-1,000,000 range, byte values,
  receive-side frame-timing jitter.
* SPI -- mode 0-3, transfer length, SCLK up to the f_clk/4 ceiling,
  MOSI/MISO data patterns.
* I2C -- Standard vs. Fast mode, addresses (UM10204's valid static range
  0x08-0x77), ACK/NACK per byte, peripheral clock-stretching, and (extra
  edge coverage) a repeated START.

The negative controls are deliberately **not** random: each returns a
fixed, deterministic waveform that violates exactly one rule, so the
models' failure detection is proven every run regardless of seed.
"""

from . import i2c, spi, uart
from .waveform import Signal, apply_jitter

#: The ratified row-1 baud range's named points (9,600 through 1,000,000).
UART_BAUD_LADDER = (
    9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000,
)

#: Legal SCLK dividers: SCLK = f_clk/div, div >= 4 keeps row 11's
#: SCLK <= f_clk/4 ceiling satisfied by construction.
SPI_DIVIDERS = (4, 5, 6, 8, 12, 16, 24, 32, 48, 64)


class UartCase:
    def __init__(self, data, baud, jitter_fraction):
        self.data = data
        self.baud = baud
        self.jitter_fraction = jitter_fraction


class SpiCase:
    def __init__(self, mosi, miso, mode, sclk_period_ns):
        self.mosi = mosi
        self.miso = miso
        self.mode = mode
        self.sclk_period_ns = sclk_period_ns


class I2cCase:
    def __init__(self, address, read_bit, data, acks, fast_mode, stretch_ns,
                 stretch_after_byte, repeated_start_after_byte):
        self.address = address
        self.read_bit = read_bit
        self.data = data
        self.acks = acks
        self.fast_mode = fast_mode
        self.stretch_ns = stretch_ns
        self.stretch_after_byte = stretch_after_byte
        self.repeated_start_after_byte = repeated_start_after_byte


def random_uart_case(rng):
    return UartCase(
        data=rng.randrange(256),
        baud=rng.choice(UART_BAUD_LADDER),
        jitter_fraction=rng.uniform(0.0, 0.004),
    )


def build_uart_waveform(case, rng):
    """Encode one frame and jitter its transitions with ``rng``; returns
    ``(line, jitter_amplitude_ns)``.  The caller's single seeded rng drives
    case generation *and* jitter, so a recorded seed reproduces the whole
    run.  The frame is preceded by one idle bit so the start edge sits
    strictly inside the waveform (a line that begins with the start bit
    itself has no idle to fall from)."""
    line = Signal(1, name="uart_rx")
    lead_in = uart.bit_period_ns(case.baud)
    uart.encode_frame(case.data, case.baud, line, t0=lead_in)
    amplitude = case.jitter_fraction * uart.bit_period_ns(case.baud)
    if amplitude > 0:
        apply_jitter(line, rng, amplitude)
    return line, amplitude


def random_spi_case(rng, f_clk_hz=50e6):
    length = rng.randrange(1, 17)
    mosi = [rng.randrange(256) for _ in range(length)]
    miso = [rng.randrange(256) for _ in range(length)]
    mode = spi.MODES[rng.randrange(4)]
    divider = rng.choice(SPI_DIVIDERS)
    return SpiCase(mosi, miso, mode, sclk_period_ns=divider * 1e9 / f_clk_hz)


def build_spi_waveform(case):
    sclk = Signal(case.mode.idle, name="sclk")
    mosi = Signal(0, name="mosi")
    miso = Signal(0, name="miso")
    cs = Signal(1, name="cs")
    spi.encode_burst(case.mosi, case.miso, case.mode, case.sclk_period_ns,
                     sclk, mosi, miso, cs)
    return sclk, mosi, miso, cs


def random_i2c_case(rng):
    n_bytes = rng.randrange(1, 5)
    data = [rng.randrange(256) for _ in range(n_bytes)]
    acks = [rng.random() < 0.75 for _ in range(n_bytes)]
    fast_mode = rng.random() < 0.5
    stretch_ns = None
    stretch_after = None
    if rng.random() < 0.5:
        stretch_after = rng.randrange(n_bytes)
        stretch_ns = 3.0 * i2c.minimum_ns("t_LOW", fast_mode)
    repeated_after = None
    if n_bytes >= 2 and rng.random() < 0.3:
        repeated_after = rng.randrange(n_bytes - 1)
    return I2cCase(
        address=rng.randrange(0x08, 0x78),
        read_bit=rng.random() < 0.5,
        data=data,
        acks=acks,
        fast_mode=fast_mode,
        stretch_ns=stretch_ns,
        stretch_after_byte=stretch_after,
        repeated_start_after_byte=repeated_after,
    )


def build_i2c_waveform(case):
    scl = Signal(1, name="scl")
    sda = Signal(1, name="sda")
    i2c.encode_transfer(
        case.address, case.read_bit, case.data, case.acks, case.fast_mode,
        scl, sda,
        stretch_ns=case.stretch_ns,
        stretch_after_byte=case.stretch_after_byte,
        repeated_start_after_byte=case.repeated_start_after_byte,
    )
    return scl, sda


def uart_negative_drift_case():
    """UART frame whose bit periods run 2.5% slow: cumulative per-frame
    drift 22.5% of a bit period at the last edge, far past row 10's ~2%
    bound, while the sampled byte often still decodes correctly -- exactly
    what only the timing measurement catches."""
    line = Signal(1, name="uart_rx")
    lead_in = uart.bit_period_ns(115200)
    uart.encode_slow_frame(0xA5, 115200, line, t0=lead_in, scale=1.025)
    return line


def spi_negative_ceiling_case(f_clk_hz=50e6):
    """SPI burst clocked at f_clk/3 -- over row 11's SCLK <= f_clk/4
    ceiling; everything else about the burst is legal mode-0 traffic."""
    mosi = [0x3C]
    miso = [0xC3]
    sclk = Signal(0, name="sclk")
    mosi_s = Signal(0, name="mosi")
    miso_s = Signal(0, name="miso")
    cs = Signal(1, name="cs")
    spi.encode_burst(mosi, miso, spi.MODES[0], 3 * 1e9 / f_clk_hz,
                     sclk, mosi_s, miso_s, cs)
    return sclk, mosi_s, miso_s, cs, mosi, miso


def spi_negative_wrong_mode_case():
    """Mode-0 traffic examined as mode 1: sampling on the trailing edges
    reads each bit's successor, so the deterministic 0xAA pattern must not
    round-trip -- proving the checker is actually mode-sensitive."""
    mosi = [0xAA, 0xAA]
    miso = [0x55, 0x55]
    sclk = Signal(0, name="sclk")
    mosi_s = Signal(0, name="mosi")
    miso_s = Signal(0, name="miso")
    cs = Signal(1, name="cs")
    spi.encode_burst(mosi, miso, spi.MODES[0], 200.0, sclk, mosi_s, miso_s, cs)
    return sclk, mosi_s, miso_s, cs, mosi, miso


def i2c_negative_short_stop_case():
    """Standard-mode transfer whose STOP setup is half the Table-10
    t_SU;STO minimum; every other parameter is legal, so the t_SU;STO
    violation is the only thing the checker may flag."""
    scl = Signal(1, name="scl")
    sda = Signal(1, name="sda")
    i2c.encode_transfer_with_short_stop_setup(
        0x50, False, [0x00], [True], False, scl, sda, factor=0.5
    )
    return scl, sda
