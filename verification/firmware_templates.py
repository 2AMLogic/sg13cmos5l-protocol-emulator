#!/usr/bin/env python3
"""Seeded firmware templates for the constrained-random DUT regression
(issue #93, verification-plan.md section 4).

Pure Python, stdlib only, no simulator: this module turns one recorded
seed into a list of **assembler source programs** (UART TX, SPI modes 0-3,
I2C write at both speed grades, plus the issue-#104 I2C
write/repeated-START/read family with peripheral clock stretching) whose payload/mode/address are immediates
rendered into protocol-shaped templates. `test_random_regression.py` then
assembles them with the DR 0003 assembler, loads them through the real
load-phase pins and grades the pin waveform with the independent reference
models. Nothing here imports a reference model or reads RTL: the
generator knows the *firmware's* cycle budgets (what the templates are
built to meet), the models know the *protocols'* rules.

Reproducibility. Each case draws from its own `random.Random` seeded by
the string `"<seed>:<protocol>:<index>"` (Python seeds strings through
SHA-512, so this is stable across runs and platforms). A case therefore
depends only on (seed, protocol, index): growing the sweep with
`RANDOM_REGRESSION_CASES` extends the list, it never reshuffles it, and a
failing `(seed, protocol, index)` triple regenerates the identical
`.asm` byte for byte.

I2C reuses the committed programs' *instruction stream*: the unrolled
bit-engine of `firmware/asm/i2c_{std,fast}.asm` is read at generation time
and only the address and data immediates are replaced. That is the
constraint the curated issue states -- the per-phase cycle budgets (the
thing the model grades) must be preserved, not re-derived -- and it keeps
`firmware/asm/` byte-unchanged. UART and SPI are rendered from scratch.

CLI: `python3 verification/firmware_templates.py --seed S [--cases N]
--out DIR` writes every case's `.asm`, `.hex`, `.cycles.txt` (no
simulator) and the planned cover-bin table.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)
import gen_i2c_sr  # noqa: E402  (the committed read/Sr program generator)

#: Default programs per protocol per run (shared-host limit: <= 20).
DEFAULT_CASES = 20
PROTOCOLS = ("uart", "spi", "i2c", "i2c_rd")

# --- pin plans, as used by the committed programs -------------------------
#: SPI on the standard Tiny Tapeout SPI Pmod (DR 0010's target plan, issue
#: #155): uio bits, made push-pull with `WCTL UIO_DIR`; MISO is uio[2].
SPI_CS, SPI_SCLK, SPI_MOSI = 0, 3, 1
SPI_DIR = (1 << SPI_CS) | (1 << SPI_SCLK) | (1 << SPI_MOSI)

# --- UART --------------------------------------------------------------
#: Bit periods in core cycles. 50 is the committed program's; the others
#: are inside the ratified row-1 baud range (9600..1M) when read at the
#: 20 ns nominal clock (500k / 230.4k / 200k baud). Constraint: the
#: first-bit WAIT immediate (period - 4) must be <= 255.
UART_PERIODS = (50, 100, 217, 250)
UART_FRAMES_MAX = 2

# --- SPI -----------------------------------------------------------------
#: Half-period in core cycles (period = 2x). 2 is the f_clk/4 ceiling
#: (zero WAIT); anything larger is under it.
SPI_HALF_PERIODS = (2, 3, 4, 6)
SPI_BURSTS_MAX = 2  # one byte per CS-low burst

# --- I2C -----------------------------------------------------------------
I2C_GRADES = ("i2c_fast", "i2c_std")
I2C_ADDR_MIN, I2C_ADDR_MAX = 0x08, 0x77  # UM10204 non-reserved 7-bit range


def payload_class(byte: int) -> str:
    """Payload class used for cover bins: 0x00, 0xFF, alternating, random."""
    if byte == 0x00:
        return "zero"
    if byte == 0xFF:
        return "ones"
    if byte in (0x55, 0xAA):
        return "alternating"
    return "random"


_PAYLOAD_CLASSES = ("zero", "ones", "alternating", "random")


def _draw_byte(rng: random.Random, cls: str) -> int:
    if cls == "zero":
        return 0x00
    if cls == "ones":
        return 0xFF
    if cls == "alternating":
        return rng.choice((0x55, 0xAA))
    while True:  # "random": any byte that is not one of the special classes
        b = rng.randrange(256)
        if payload_class(b) == "random":
            return b


def i2c_address_class(addr: int) -> str:
    if addr in (I2C_ADDR_MIN, I2C_ADDR_MAX):
        return "bound"
    if addr & (addr - 1) == 0:
        return "power-of-two"
    return "random"


class Case:
    """One generated program plus the facts the bench grades against."""

    def __init__(self, protocol, index, seed, params, bins, source):
        self.protocol = protocol
        self.index = index
        self.seed = seed
        self.params = params
        self.bins = bins  # tuple of (table-name, bin-label)
        self.source = source

    @property
    def name(self) -> str:
        return f"{self.protocol}_{self.index:02d}"

    def assemble(self):
        return asm.assemble_text(self.source, f"{self.name}.asm")


def _rng(seed: int, protocol: str, index: int) -> random.Random:
    return random.Random(f"{seed}:{protocol}:{index}")


def _header(case_name, seed, protocol, index, params) -> str:
    return (
        f"; {case_name}.asm -- GENERATED by verification/firmware_templates.py\n"
        f"; (issue #93). seed={seed} protocol={protocol} index={index}\n"
        f"; params={json.dumps(params, sort_keys=True)}\n"
        "; Regenerate: python3 verification/firmware_templates.py --seed "
        f"{seed} --out DIR\n"
    )


# =======================================================================
# UART (8N1 TX), template = firmware/asm/uart_tx.asm with the bit period
# and the payloads as parameters
# =======================================================================


def render_uart(name, seed, index, params) -> str:
    period = params["period"]
    delta = params.get("mistime_delta", 0)  # negative control only
    w_loop = period - 7 + delta  # loop body = 7 + w cycles
    w_first = period - 4  # OUT + WAIT(w+1) + MOV + AND
    w_stop = 1  # OUT SHF SUB WAIT(w+1) BNZ WAIT(2) fixes the stop bit pitch
    assert 0 <= w_loop <= 255 and 0 <= w_first <= 255
    out = [_header(name, seed, "uart", index, params)]
    out.append(
        "        LDI   R1, 1\n"
        "        OUT   UO_OUT, R1       ; TX idles HIGH\n"
        "        WAIT  255              ; idle before the first start bit\n"
    )
    for n, payload in enumerate(params["payloads"], start=1):
        out.append(
            f"; ---- frame {n}: 0x{payload:02X}\n"
            f"        LDI   R0, 0x{payload:02X}\n"
            "        LDI   R3, 8\n"
            "        LDI   R2, 0\n"
            "        OUT   UO_OUT, R2       ; START\n"
            f"        WAIT  {w_first}\n"
            f"f{n}_bit:\n"
            f".cyclesec uart_bit_frame{n}\n"
            "        MOV   R2, R0\n"
            "        AND   R2, R1\n"
            "        OUT   UO_OUT, R2       ; data bit\n"
            "        SHF   R0, RIGHT\n"
            "        SUB   R3, R1\n"
            f"        WAIT  {w_loop}\n"
            f"        BNZ   f{n}_bit\n"
            ".endcyclesec\n"
            f"        WAIT  {w_stop}\n"
            "        OUT   UO_OUT, R1       ; STOP\n"
            "        WAIT  255\n"
        )
    out.append("        HALT\n")
    return "".join(out)


def gen_uart(seed, index, mistime_delta=0, force_payloads=None) -> Case:
    rng = _rng(seed, "uart", index)
    period = rng.choice(UART_PERIODS)
    n_frames = rng.randrange(1, UART_FRAMES_MAX + 1)
    classes = [_PAYLOAD_CLASSES[index % 4]]  # round-robin: every class hit
    classes += [rng.choice(_PAYLOAD_CLASSES) for _ in range(n_frames - 1)]
    payloads = [_draw_byte(rng, c) for c in classes]
    if force_payloads is not None:  # negative control only
        payloads = list(force_payloads)
    params = {"period": period, "payloads": payloads}
    if mistime_delta:
        params["mistime_delta"] = mistime_delta
    name = f"uart_{index:02d}"
    src = render_uart(name, seed, index, params)
    bins = tuple(("uart.byte_class", payload_class(p)) for p in payloads) + (
        ("uart.bit_period_cycles", str(period)),
    )
    return Case("uart", index, seed, params, bins, src)


def uart_run_cycles(case: Case, program) -> int:
    """Statically known execution length: the assembler counts each loop
    body once, so add (8 - 1) more bodies per frame (trip count is an
    assemble-time literal, never pin data)."""
    return program.total_cycles + 7 * case.params["period"] * len(
        case.params["payloads"]
    )


# =======================================================================
# SPI (controller, one byte per CS-low burst)
# =======================================================================


def render_spi(name, seed, index, params) -> str:
    cpol, cpha = params["cpol"], params["cpha"]
    g = params["half_period"]
    idle = cpol ^ params.get("flip_idle", 0)  # flip_idle: negative control
    active = 1 - idle
    cs_hi = 1 << SPI_CS

    def img(sclk, mosi=0):
        return (sclk << SPI_SCLK) | (mosi << SPI_MOSI)

    out = [_header(name, seed, "spi", index, params)]
    out.append(
        f"        LDI   R2, 0x{img(idle) | cs_hi:02X}      ; CS released, SCLK idle\n"
        "        OUT   UIO_OUT, R2      ; idle image before the drivers are on\n"
        f"        LDI   R3, 0x{SPI_DIR:02X}      ; CS|MOSI|SCLK\n"
        "        WCTL  UIO_DIR, R3      ; DR 0012: push-pull\n"
        "        WAIT  13\n"
    )
    pad = f"        WAIT  {g - 3}\n" if g >= 3 else ""
    for b, mosi_byte in enumerate(params["mosi"]):
        bits = [(mosi_byte >> (7 - k)) & 1 for k in range(8)]
        # CPHA=0: data rides the leading edge (R2), trailing is static (R1).
        # CPHA=1: leading is static (R1), data rides the trailing edge (R2).
        if cpha == 0:
            r1 = img(idle)
            data_img = [img(active, d) for d in bits]
            lead, trail = "R2", "R1"
        else:
            r1 = img(active)
            data_img = [img(idle, d) for d in bits]
            lead, trail = "R1", "R2"
        out.append(
            f"; ---- burst {b}: MOSI 0x{mosi_byte:02X}\n"
            f"        LDI   R2, 0x{img(idle):02X}      ; CS asserted\n"
            "        OUT   UIO_OUT, R2\n"
            "        WAIT  3\n"
            f"        LDI   R1, 0x{r1:02X}\n"
            f"        LDI   R2, 0x{data_img[0]:02X}\n"
            f".cyclesec spi_rand_b{b}\n"
        )
        for k in range(8):
            nxt = data_img[k + 1] if k < 7 else 0
            out.append(
                f"        OUT   UIO_OUT, {lead}\n"
                "        IN    R3, UIO_IN\n"
                f"{pad}"
                f"        OUT   UIO_OUT, {trail}\n"
                f"        LDI   R2, 0x{nxt:02X}\n"
                f"{pad}"
            )
        out.append(
            ".endcyclesec\n"
            "        WAIT  3\n"
            f"        LDI   R2, 0x{img(idle) | cs_hi:02X}      ; CS released\n"
            "        OUT   UIO_OUT, R2\n"
            "        WAIT  31\n"
        )
    out.append("        HALT\n")
    return "".join(out)


def gen_spi(seed, index, flip_idle=0) -> Case:
    rng = _rng(seed, "spi", index)
    mode = index % 4  # round-robin: every mode hit once per 4 cases
    cpol, cpha = mode >> 1, mode & 1  # reference_models.spi.MODES ordering
    n_bursts = rng.randrange(1, SPI_BURSTS_MAX + 1)
    classes = [_PAYLOAD_CLASSES[(index // 4) % 4]] + [
        rng.choice(_PAYLOAD_CLASSES) for _ in range(n_bursts - 1)
    ]
    mosi = [_draw_byte(rng, c) for c in classes]
    miso = [rng.randrange(256) for _ in range(n_bursts)]
    half = rng.choice(SPI_HALF_PERIODS)
    params = {
        "mode": mode,
        "cpol": cpol,
        "cpha": cpha,
        "half_period": half,
        "mosi": mosi,
        "miso": miso,
    }
    if flip_idle:
        params["flip_idle"] = 1
    name = f"spi_{index:02d}"
    src = render_spi(name, seed, index, params)
    bins = (
        ("spi.mode_x_bursts", f"mode{mode}/bursts{n_bursts}"),
        ("spi.sclk_period_cycles", str(2 * half)),
    ) + tuple(("spi.mosi_class", payload_class(p)) for p in mosi)
    return Case("spi", index, seed, params, bins, src)


# =======================================================================
# I2C write (std + fast), template = the committed programs' bit engine
# =======================================================================

_I2C_SETUP_MARK = re.compile(r"^; -{20,} setup\s*$", re.M)


def _i2c_template_text(grade: str) -> str:
    text = (REPO_ROOT / "firmware" / "asm" / f"{grade}.asm").read_text(
        encoding="utf-8"
    )
    mark = _I2C_SETUP_MARK.search(text)
    assert mark, f"{grade}.asm lost its '; --- setup' marker line"
    return text[mark.start():]


def render_i2c(name, seed, index, params) -> str:
    grade = params["grade"]
    body = _i2c_template_text(grade)
    addr_byte = params["address"] << 1  # write transfer: R/W = 0
    body, n_addr = re.subn(
        r"(?m)^(\s*LDI\s+R0,\s*)0xA0\b", rf"\g<1>0x{addr_byte:02X}", body
    )
    body, n_data = re.subn(
        r"(?m)^(\s*LDI\s+R0,\s*)0x5A\b", rf"\g<1>0x{params['data']:02X}", body
    )
    assert (n_addr, n_data) == (1, 1), (
        f"{grade}.asm no longer has exactly one address and one data "
        f"immediate to substitute ({n_addr}, {n_data})"
    )
    delta = params.get("mistime_low_delta", 0)
    if delta:  # negative control: shorten every data-clock low phase
        low_wait = {"i2c_fast": 62, "i2c_std": 232}[grade]
        body, n = re.subn(
            rf"(?m)^(\s*WAIT\s+){low_wait}\b", rf"\g<1>{low_wait + delta}", body
        )
        assert n == 16, f"expected 16 data-clock low-phase WAITs, found {n}"
    return _header(name, seed, "i2c", index, params) + (
        "; Bit engine below is firmware/asm/%s.asm byte for byte except the\n"
        "; address/data LDI R0 immediates (and, in a negative control only,\n"
        "; the low-phase WAIT literal): per-phase cycle budgets are the\n"
        "; committed program's.\n" % grade
    ) + body


def gen_i2c(seed, index, mistime_low_delta=0) -> Case:
    rng = _rng(seed, "i2c", index)
    grade = I2C_GRADES[index % 2]
    data_class = _PAYLOAD_CLASSES[(index // 2) % 4]
    addr_class = rng.choice(("bound", "power-of-two", "random"))
    if addr_class == "bound":
        address = rng.choice((I2C_ADDR_MIN, I2C_ADDR_MAX))
    elif addr_class == "power-of-two":
        address = rng.choice((0x10, 0x20, 0x40))
    else:
        while True:
            address = rng.randrange(I2C_ADDR_MIN, I2C_ADDR_MAX + 1)
            if i2c_address_class(address) == "random":
                break
    data = _draw_byte(rng, data_class)
    ack_address = rng.random() < 0.8  # NACK exercises the branch's other arm
    params = {
        "grade": grade,
        "address": address,
        "data": data,
        "ack_address": ack_address,
    }
    if mistime_low_delta:
        params["mistime_low_delta"] = mistime_low_delta
    name = f"i2c_{index:02d}"
    src = render_i2c(name, seed, index, params)
    bins = (
        (
            "i2c.grade_x_addr_x_data",
            f"{grade}/{i2c_address_class(address)}/{payload_class(data)}",
        ),
        ("i2c.address_ack", "ack" if ack_address else "nack"),
    )
    return Case("i2c", index, seed, params, bins, src)


# =======================================================================
# I2C write -> repeated START -> read, with peripheral clock stretching
# (issue #104). Template = firmware/tools/gen_i2c_sr.py, the generator of
# the committed i2c_{fast,std}_sr{,_poll}.asm programs, called with a
# different address / pointer byte. Its instruction stream (hence every
# per-phase cycle budget) is independent of those immediates.
# =======================================================================

#: Stretch sites: name -> the controller SCL-fall number after which the
#: peripheral holds SCL low (numbering of test_firmware_i2c_sr.py's
#: `drive_peripheral_sr`: 19 = low before the repeated START's rise, 29 =
#: first read-data clock, 38 = low before the STOP's rise).
I2C_RD_SITES = {"pre_sr": 19, "read_clock": 29, "pre_stop": 38}
#: Duration classes: cycles the hold lasts BEYOND the controller's own
#: t_LOW (so every drawn hold is a real stretch of that many cycles).
I2C_RD_DURATIONS = {"short": (8, 40), "medium": (41, 200), "long": (201, 400)}
#: Peripheral ACK slots (falls) and the first read-data fall, as in the
#: directed bench; the schedule artifact states them explicitly.
I2C_RD_ACK_FALLS = (9, 18, 28)
I2C_RD_FIRST_READ_FALL = 29
_I2C_RD_LOW = {"i2c_fast": gen_i2c_sr.MODES["fast"]["L"],
               "i2c_std": gen_i2c_sr.MODES["std"]["L"]}


def render_i2c_rd(name, seed, index, params) -> str:
    mode = "fast" if params["grade"] == "i2c_fast" else "std"
    _n, text, _sites = gen_i2c_sr.build(mode, params.get("poll", True))
    # The generator inverts each byte (the inverted-data trick): substitute
    # the three `LDI R0, ~byte` immediates in one pass (so a new value that
    # equals another old one cannot be re-substituted). Comments still name
    # the committed program's bytes; the header below says so.
    inv = lambda v: (~v) & 0xFF
    addr_w = (params["address"] << 1) & 0xFF
    swaps = {
        inv(gen_i2c_sr.ADDR_W): inv(addr_w),
        inv(gen_i2c_sr.PTR): inv(params["pointer"]),
        inv(gen_i2c_sr.ADDR_R): inv(addr_w | 1),
    }
    assert len(swaps) == 3
    pat = re.compile(
        r"(?m)^(\s*LDI\s+R0,\s*)0x(%s)\b"
        % "|".join(f"{k:02X}" for k in swaps)
    )
    text, n = pat.subn(lambda m: f"{m.group(1)}0x{swaps[int(m.group(2), 16)]:02X}", text)
    assert n == 3, f"expected 3 address/pointer immediates, found {n}"
    return _header(name, seed, "i2c_rd", index, params) + (
        "; Body is firmware/tools/gen_i2c_sr.py output (the committed\n"
        "; i2c_%s_sr%s.asm stream) with only the three LDI R0 (inverted\n"
        "; address-W / pointer / address-R) immediates changed; comments below\n"
        "; still name the committed program's 0x50 / 0x5A bytes. The read\n"
        "; byte and stretch schedule are driven\n"
        "; by the PERIPHERAL (see %s.schedule.json), not by this source.\n"
        % (mode, "_poll" if params.get("poll", True) else "", name)
    ) + text


def i2c_rd_schedule(case) -> dict:
    """The peripheral side of a case, as plain data (also the
    `.schedule.json` artifact): ACK slots, per-fall read bits, per-fall
    hold cycles. Pure function of the case params."""
    rb = case.params["read_byte"]
    return {
        "ack_falls": list(I2C_RD_ACK_FALLS),
        "read_byte": rb,
        "read_bits": {
            str(I2C_RD_FIRST_READ_FALL + i): (rb >> (7 - i)) & 1 for i in range(8)
        },
        "stretches": {str(s["fall"]): s["hold_cycles"] for s in case.params["stretch"]},
    }


def _draw_i2c_address(rng):
    addr_class = rng.choice(("bound", "power-of-two", "random"))
    if addr_class == "bound":
        return rng.choice((I2C_ADDR_MIN, I2C_ADDR_MAX))
    if addr_class == "power-of-two":
        return rng.choice((0x10, 0x20, 0x40))
    while True:
        a = rng.randrange(I2C_ADDR_MIN, I2C_ADDR_MAX + 1)
        if i2c_address_class(a) == "random":
            return a


def gen_i2c_rd(seed, index, poll=True) -> Case:
    rng = _rng(seed, "i2c_rd", index)
    grade = I2C_GRADES[index % 2]
    read_class = _PAYLOAD_CLASSES[(index // 2) % 4]
    address = _draw_i2c_address(rng)
    pointer = _draw_byte(rng, rng.choice(_PAYLOAD_CLASSES))
    read_byte = _draw_byte(rng, read_class)
    sites = list(I2C_RD_SITES)
    primary = sites[index % 3]  # round-robin: every site x grade, site x duration
    primary_dur = list(I2C_RD_DURATIONS)[(index // 3) % 3]
    low = _I2C_RD_LOW[grade]
    stretch = []
    for site in sites:
        if site == primary:
            dur = primary_dur
        elif rng.random() < 0.4:
            dur = rng.choice(list(I2C_RD_DURATIONS))
        else:
            continue
        lo, hi = I2C_RD_DURATIONS[dur]
        stretch.append({
            "site": site,
            "fall": I2C_RD_SITES[site],
            "duration_class": dur,
            "extra_cycles": rng.randrange(lo, hi + 1),
        })
    for s in stretch:
        s["hold_cycles"] = low + s["extra_cycles"]
    params = {
        "grade": grade,
        "address": address,
        "pointer": pointer,
        "read_byte": read_byte,
        "stretch": stretch,
    }
    if not poll:  # negative control only: the non-polling sibling program
        params["poll"] = False
    name = f"i2c_rd_{index:02d}"
    src = render_i2c_rd(name, seed, index, params)
    bins = (
        ("i2c_rd.grade_x_read_class", f"{grade}/{payload_class(read_byte)}"),
        ("i2c_rd.address_class", i2c_address_class(address)),
        ("i2c_rd.pointer_class", payload_class(pointer)),
        ("i2c_rd.stretch_count", str(len(stretch))),
    ) + tuple(
        bin_
        for s in stretch
        for bin_ in (
            ("i2c_rd.site_x_duration", f"{s['site']}/{s['duration_class']}"),
            ("i2c_rd.grade_x_site", f"{grade}/{s['site']}"),
        )
    )
    return Case("i2c_rd", index, seed, params, bins, src)


# =======================================================================
# Public entry points
# =======================================================================

_GENERATORS = {
    "uart": gen_uart, "spi": gen_spi, "i2c": gen_i2c, "i2c_rd": gen_i2c_rd,
}


def generate(seed: int, protocol: str, n: int = DEFAULT_CASES):
    return [_GENERATORS[protocol](seed, i) for i in range(n)]


def planned_bin_universe() -> dict:
    """Every cover bin the templates can produce, per table (so unhit bins
    can be listed rather than omitted)."""
    u = {
        "uart.byte_class": list(_PAYLOAD_CLASSES),
        "uart.bit_period_cycles": [str(p) for p in UART_PERIODS],
        "spi.mode_x_bursts": [
            f"mode{m}/bursts{n}"
            for m in range(4)
            for n in range(1, SPI_BURSTS_MAX + 1)
        ],
        "spi.sclk_period_cycles": [str(2 * h) for h in SPI_HALF_PERIODS],
        "spi.mosi_class": list(_PAYLOAD_CLASSES),
        "i2c.grade_x_addr_x_data": [
            f"{g}/{a}/{d}"
            for g in I2C_GRADES
            for a in ("bound", "power-of-two", "random")
            for d in _PAYLOAD_CLASSES
        ],
        "i2c.address_ack": ["ack", "nack"],
        "i2c_rd.grade_x_read_class": [
            f"{g}/{c}" for g in I2C_GRADES for c in _PAYLOAD_CLASSES
        ],
        "i2c_rd.address_class": ["bound", "power-of-two", "random"],
        "i2c_rd.pointer_class": list(_PAYLOAD_CLASSES),
        "i2c_rd.stretch_count": [str(n) for n in range(1, len(I2C_RD_SITES) + 1)],
        "i2c_rd.site_x_duration": [
            f"{s}/{d}" for s in I2C_RD_SITES for d in I2C_RD_DURATIONS
        ],
        "i2c_rd.grade_x_site": [
            f"{g}/{s}" for g in I2C_GRADES for s in I2C_RD_SITES
        ],
    }
    return u


def coverage(cases) -> dict:
    """{table: {bin: hit count}} with every universe bin present (0 = unhit)."""
    universe = planned_bin_universe()
    out = {t: {b: 0 for b in bins} for t, bins in universe.items()}
    for case in cases:
        for table, label in case.bins:
            out[table][label] += 1
    return out


def write_artifacts(case: Case, out_dir: Path) -> None:
    program = case.assemble()
    (out_dir / f"{case.name}.asm").write_text(case.source, encoding="utf-8")
    (out_dir / f"{case.name}.hex").write_text(asm.render_hex(program), encoding="utf-8")
    (out_dir / f"{case.name}.cycles.txt").write_text(
        asm.render_cycles_report(program), encoding="utf-8"
    )
    if case.protocol == "i2c_rd":  # the peripheral's side is evidence too
        (out_dir / f"{case.name}.schedule.json").write_text(
            json.dumps(i2c_rd_schedule(case), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--cases", type=int, default=DEFAULT_CASES)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    cases = []
    for protocol in PROTOCOLS:
        cases += generate(args.seed, protocol, args.cases)
    for case in cases:
        write_artifacts(case, args.out)
    print(f"wrote {len(cases)} programs to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
