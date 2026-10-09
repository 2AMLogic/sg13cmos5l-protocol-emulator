"""cocotb bench for the load-phase CRC readout on
`tt_um_2amlogic_protocol_emulator` (issue #137).

`spec/decision-records/0013-program-loading.md` section "Layer 1" adds an
integrity check to DR 0001's serial load: while the design is still in
the load phase, `uo_out` presents the running `PM_CRC` (DR 0012's
CRC-16/XMODEM over every committed word) -- the low byte when
`ui_in[1] = 0`, the high byte when `ui_in[1] = 1`. The host reads both
bytes before it drops `MODE`, compares them with its own CRC of the
image, and runs the image only on a match. This bench is
`spec/verification-plan.md` section 7's "Load integrity" obligation.

What is checked, all of it at the pins:

- **the readout is the image's CRC**: for random images of several
  lengths (1 word to the full 256), the two bytes read on `uo_out` equal
  `binascii.crc_hqx(image_bytes, 0)` -- Python's standard library, not
  this repository's arithmetic -- with the image taken as big-endian
  bytes;
- **it is the running CRC**: after every committed word the readout
  equals the CRC of the words committed so far, and it does not move on
  the 15 edges between commits;
- **the byte select is `ui_in[1]` and nothing else**, it needs no clock
  edge, and the serial data pin does not disturb it;
- **a bad load mismatches**: a truncated load, a load with one clock
  edge dropped, and a load with one clock edge doubled each read back a
  CRC different from the image's, whenever memory ends up holding
  something other than the image. Every single-edge fault position of a
  small image is tried, plus seeded random positions in larger images.
  The readout is also checked against what such a fault really commits,
  computed here bit by bit, so "mismatch" is not satisfied by a readout
  that is merely wrong. One doubled-edge case leaves memory correct (the
  repeated bit is in a run of equal bits reaching the end of the image);
  there the readout must match, and the bench says so;
- **the load protocol is unchanged**: a host that performs the readout
  -- with the clock stopped, or with it still running -- and then drops
  `MODE` gets the program executing on exactly the edges it would
  without the readout, the partial word shifted in during a running-clock
  readout is discarded, and `BOOT_STATUS[0]` reads 1;
- **outside the load phase the readout is gone**: `uo_out` is 0 while
  reset is held and on the mode-sampling cycle, whatever `ui_in[1]` is;
  from the `MODE`-drop edge on `uo_out` is the core's port register, and
  neither `ui_in[1]` nor a `MODE` raised again reaches it;
- **saturation**: after 256 words the CRC, like the memory, stops
  moving.

What a 16-bit CRC cannot promise is said where the fault tests are: the
"must mismatch" results below are facts about the seeded images used
here, each asserted, not a proof for every image. Two images in every
65,536 share a CRC, and an all-zero image reads 0x0000 at any length (the
CRC starts at 0), so no edge fault or truncation of it is visible.

Every check is pin-only, so the bench also runs unmodified on a
gate-level netlist (`GATES=yes`).

All images come from `random.Random` with the literal seeds below, so
every run is byte-reproducible.
"""

import binascii
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))

import asm  # noqa: E402  (the DR 0003 assembler)

CLK_PERIOD_NS = 10
RUN_ENTRY_EDGES = 2  # DR 0005: edge 1 primes the fetch, edge 2 retires pc=0

MODE = 0x80      # ui_in[7]
CRC_SEL = 0x02   # ui_in[1]: 0 = low byte, 1 = high byte
BOOT_STATUS = 0x08


def image_bytes(words):
    """The image as the host holds it: big-endian bytes, word 0 first."""
    return b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)


def host_crc(words):
    """The host's own CRC of an image -- the independent reference DR 0013
    names. Nothing here shares code with the RTL."""
    return binascii.crc_hqx(image_bytes(words), 0)


def bits_of(words):
    """The serial stream of an image: MSB of word 0 first."""
    return [(w >> b) & 1 for w in words for b in range(15, -1, -1)]


def committed(bits):
    """What a load phase that saw `bits` commits: complete 16-bit groups,
    at most 256 of them (DR 0001). Written from the DR, not from the RTL."""
    n = min(len(bits) // 16, 256)
    out = []
    for i in range(n):
        word = 0
        for bit in bits[16 * i:16 * i + 16]:
            word = (word << 1) | bit
        out.append(word)
    return out


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


async def pins(dut):
    """Sample uo_out once the cycle has settled."""
    await ReadOnly()
    value = int(dut.uo_out.value)
    await Timer(1, unit="ns")
    return value


async def enter_load(dut):
    """Reset with MODE high and take the mode-sampling edge."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = MODE
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge


async def shift_bits(dut, bits, sel=0):
    """One clock edge per bit, MODE high. `sel` is held on ui_in[1]."""
    for bit in bits:
        dut.ui_in.value = MODE | sel | bit
        await RisingEdge(dut.clk)


async def read_crc(dut, data_bit=0):
    """The host's readout, with no clock edge: select the low byte, read
    uo_out; select the high byte, read uo_out. MODE stays high. Must be
    called between clock edges (it advances time by 2 ns)."""
    dut.ui_in.value = MODE | data_bit
    await Timer(1, unit="ns")
    lo = int(dut.uo_out.value)
    dut.ui_in.value = MODE | CRC_SEL | data_bit
    await Timer(1, unit="ns")
    hi = int(dut.uo_out.value)
    return (hi << 8) | lo


async def load_and_read(dut, bits):
    """Reset into the load phase, clock `bits` in, and read the CRC."""
    await enter_load(dut)
    await shift_bits(dut, bits)
    return await read_crc(dut)


def random_image(rng, n):
    return [rng.randrange(0x10000) for _ in range(n)]


# ---------------------------------------------------------------------------
@cocotb.test()
async def test_readout_equals_crc_hqx_for_random_images(dut):
    """Random images of 1, 2, 3, 16, 97 and 256 words, three seeds each:
    after the last bit, uo_out reads the low then the high byte of
    `binascii.crc_hqx(image_bytes, 0)`."""
    start_clock(dut)
    # Known-answer anchor for the reference itself (CRC-16/XMODEM check value).
    assert binascii.crc_hqx(b"123456789", 0) == 0x31C3
    distinct = set()
    for seed in (0x137A, 0x137B, 0x137C):
        rng = random.Random(seed)
        for n in (1, 2, 3, 16, 97, 256):
            image = random_image(rng, n)
            want = host_crc(image)
            got = await load_and_read(dut, bits_of(image))
            assert got == want, (
                f"seed {seed:#x}, {n} words: uo_out read {got:#06x}, "
                f"binascii.crc_hqx says {want:#06x}"
            )
            distinct.add(want)
    assert len(distinct) >= 16, "test premise: the images have different CRCs"
    assert any((c >> 8) != (c & 0xFF) for c in distinct), (
        "test premise: some CRC has different high and low bytes"
    )


@cocotb.test()
async def test_readout_is_the_running_crc_and_only_moves_on_a_commit(dut):
    """Through a 24-word load: after each word's 16th edge the readout is
    the CRC of the words so far; on the 15 edges before it the readout is
    still the previous CRC (sampled on both byte selects)."""
    start_clock(dut)
    rng = random.Random(0x0137)
    image = random_image(rng, 24)
    await enter_load(dut)
    assert await read_crc(dut) == 0x0000, "the CRC must read 0 before any word is committed"
    previous = 0x0000
    for index, word in enumerate(image):
        word_bits = bits_of([word])
        for k, bit in enumerate(word_bits[:15]):
            sel = CRC_SEL if (k + index) % 2 else 0
            dut.ui_in.value = MODE | sel | bit
            await RisingEdge(dut.clk)
            got = await pins(dut)
            want = (previous >> 8) if sel else (previous & 0xFF)
            assert got == want, (
                f"word {index}, bit {k}: readout moved before the commit edge "
                f"({got:#04x}, want {want:#04x})"
            )
        dut.ui_in.value = MODE | word_bits[15]
        await RisingEdge(dut.clk)  # the commit edge
        await Timer(1, unit="ns")
        want = host_crc(image[:index + 1])
        got = await read_crc(dut)
        assert got == want, (
            f"after word {index}: readout {got:#06x}, CRC of the first "
            f"{index + 1} words is {want:#06x}"
        )
        assert want != previous, "test premise: every word moves the CRC"
        previous = want


@cocotb.test()
async def test_byte_select_is_ui_in_1_alone_and_needs_no_clock(dut):
    """With the clock between edges, uo_out follows ui_in[1] back and
    forth, and no other ui_in pin (the serial data pin included) or uio_in
    pin changes what is read. MODE is held high throughout."""
    start_clock(dut)
    rng = random.Random(0x5E1E)
    image = random_image(rng, 8)
    crc = host_crc(image)
    lo, hi = crc & 0xFF, crc >> 8
    assert lo != hi, "test premise: the two bytes differ"
    await enter_load(dut)
    await shift_bits(dut, bits_of(image))
    await Timer(1, unit="ns")
    for other in (0x00, 0x01, 0x04, 0x08, 0x10, 0x20, 0x40, 0x7D):
        for uio in (0x00, 0xFF, 0xA5):
            dut.uio_in.value = uio
            for sel in (0, 1, 0, 1):
                ui = MODE | (other & ~CRC_SEL) | (CRC_SEL if sel else 0)
                dut.ui_in.value = ui
                await Timer(0.1, unit="ns")
                got = int(dut.uo_out.value)
                want = hi if sel else lo
                assert got == want, (
                    f"ui_in {ui:#04x}, uio_in {uio:#04x}: uo_out {got:#04x}, "
                    f"want the {'high' if sel else 'low'} byte {want:#04x}"
                )


@cocotb.test()
async def test_truncated_load_mismatches(dut):
    """A host that stops early -- a whole number of words short, or part
    way through a word -- reads the CRC of what was committed, which is
    not the image's CRC."""
    start_clock(dut)
    rng = random.Random(0x7C07)
    for n in (2, 16, 64):
        image = random_image(rng, n)
        want = host_crc(image)
        bits = bits_of(image)
        cuts = sorted({16 * (n - 1), 16 * (n - 1) + 9, 16 * n - 1, 16 * (n // 2), 16, 5, 0})
        for cut in cuts:
            got = await load_and_read(dut, bits[:cut])
            landed = host_crc(committed(bits[:cut]))
            assert got == landed, (
                f"{n} words cut at bit {cut}: readout {got:#06x}, the "
                f"committed words' CRC is {landed:#06x}"
            )
            assert got != want, (
                f"{n} words cut at bit {cut}: a truncated load read the full "
                f"image's CRC {want:#06x}"
            )


async def edge_fault_case(dut, image, position, kind):
    """Load `image` with one clock edge dropped (the design never sees bit
    `position`) or doubled (it sees bit `position` twice). Returns
    (readout, CRC of what that really commits)."""
    bits = bits_of(image)
    if kind == "dropped":
        seen = bits[:position] + bits[position + 1:]
    else:
        seen = bits[:position + 1] + bits[position:]
    got = await load_and_read(dut, seen)
    return got, committed(seen)


@cocotb.test()
async def test_dropped_clock_edge_mismatches(dut):
    """One clock edge lost anywhere in the load: every position of a
    4-word image, and seeded random positions in 16- and 256-word images.
    Every later bit lands one place early and the last word never
    completes; the readout differs from the image's CRC."""
    start_clock(dut)
    rng = random.Random(0xD809)
    cases = []
    small = random_image(rng, 4)
    cases += [(small, pos) for pos in range(64)]
    medium = random_image(rng, 16)
    cases += [(medium, rng.randrange(256)) for _ in range(12)]
    large = random_image(rng, 256)
    cases += [(large, pos) for pos in (0, 4095, rng.randrange(4096), rng.randrange(4096))]
    for image, position in cases:
        want = host_crc(image)
        got, landed = await edge_fault_case(dut, image, position, "dropped")
        assert len(landed) == len(image) - 1, "a dropped edge always loses the last word"
        assert got == host_crc(landed), (
            f"{len(image)} words, edge {position} dropped: readout {got:#06x}, "
            f"the committed words' CRC is {host_crc(landed):#06x}"
        )
        assert got != want, (
            f"{len(image)} words, edge {position} dropped: the readout still "
            f"equals the image's CRC {want:#06x}"
        )


@cocotb.test()
async def test_doubled_clock_edge_mismatches(dut):
    """One clock edge seen twice anywhere in the load: every position of a
    4-word image, and seeded random positions in 16- and 255-word images.
    Every later bit lands one place late, and wherever that leaves memory
    holding something other than the image, the readout differs from the
    image's CRC. The one case where memory is still right -- the repeated
    bit sits in a run of equal bits that reaches the end of the image, so
    nothing moved and the spare bit is a discarded partial word -- must
    read as a match, and is counted. A full 256-word image is included:
    there the 257th group never commits, but the shifted words still do."""
    start_clock(dut)
    rng = random.Random(0xD0B1)
    cases = []
    small = random_image(rng, 4)
    cases += [(small, pos) for pos in range(64)]
    medium = random_image(rng, 16)
    cases += [(medium, rng.randrange(256)) for _ in range(12)]
    large = random_image(rng, 255)
    cases += [(large, pos) for pos in (0, 4079, rng.randrange(4080), rng.randrange(4080))]
    full = random_image(rng, 256)
    cases += [(full, pos) for pos in (0, 4095, rng.randrange(4096))]
    harmless = 0
    for image, position in cases:
        want = host_crc(image)
        got, landed = await edge_fault_case(dut, image, position, "doubled")
        assert got == host_crc(landed), (
            f"{len(image)} words, edge {position} doubled: readout {got:#06x}, "
            f"the committed words' CRC is {host_crc(landed):#06x}"
        )
        if landed == image:
            # The repeated bit only lengthened a run of equal bits that
            # reaches the end of the image: every word landed intact and the
            # one bit left over is a partial word, discarded at MODE drop.
            # Memory holds the image, so a match is the right answer.
            assert all(b == bits_of(image)[position] for b in bits_of(image)[position:])
            assert got == want
            harmless += 1
            continue
        assert got != want, (
            f"{len(image)} words, edge {position} doubled: memory does not hold "
            f"the image, but the readout equals its CRC {want:#06x}"
        )
    # Guard the guard: the harmless branch must stay the rare tail case it
    # is (the last bit of each image at least), not swallow the test.
    assert 1 <= harmless <= 8, f"{harmless} of {len(cases)} doubled-edge cases were harmless"


def marker_program(pad_words):
    """A program whose pin activity dates it: 0xA5 on uo_out, then
    BOOT_STATUS, then 0x3C, then HALT. Followed by `pad_words` so the
    image's CRC covers more than the program."""
    program = asm.assemble_text(
        "LDI R1, 0xA5\n"
        "OUT UO_OUT, R1\n"
        f"RCTL R0, {BOOT_STATUS:#04x}\n"
        "OUT UO_OUT, R0\n"
        "LDI R2, 0x3C\n"
        "OUT UO_OUT, R2\n"
        "HALT\n"
    )
    assert program.warnings == [], program.warnings
    return list(program.words) + list(pad_words)


# After the MODE-drop edge (edge 0): run entry costs 2 edges (DR 0005), and
# each of these instructions is 1 cycle (DR 0001; RCTL BOOT_STATUS is a
# 1-cycle access, DR 0012). Instruction index i retires on edge
# RUN_ENTRY_EDGES + i, so an OUT at index i is on the pins after that edge.
MARKER_TRACE = (
    [0x00] * (RUN_ENTRY_EDGES + 1)   # after edges 0..2: nothing driven yet
    + [0xA5, 0xA5]                   # after edges 3, 4: OUT at index 1
    + [0x01, 0x01]                   # after edges 5, 6: BOOT_STATUS (bit 0 set)
    + [0x3C] * 6                     # after edge 7 on: OUT at index 5, then HALT
)


async def run_and_trace(dut, n_edges, wiggle_sel=False):
    """Drop MODE and return uo_out after edges 0..n_edges-1. With
    `wiggle_sel`, ui_in[1] toggles every cycle of the run, and from edge 1
    on MODE is raised again mid-cycle with both select values: MODE is
    latched at reset release (DR 0001), so in the run phase neither pin
    may reach uo_out. (MODE is low at every clock edge here, so the
    program's own timing is that of a plain run.)"""
    trace = []
    for e in range(n_edges):
        dut.ui_in.value = CRC_SEL if (wiggle_sel and e % 2) else 0x00
        await RisingEdge(dut.clk)
        trace.append(await pins(dut))
        if wiggle_sel:
            others = [0x00 if (e % 2) else CRC_SEL]
            if e >= 1:
                others += [MODE, MODE | CRC_SEL]
            for ui in others:
                dut.ui_in.value = ui
                await Timer(1, unit="ns")
                assert int(dut.uo_out.value) == trace[-1], (
                    f"ui_in {ui:#04x} reached uo_out in the run phase (after edge {e}): "
                    f"{int(dut.uo_out.value):#04x}, was {trace[-1]:#04x}"
                )
    return trace


@cocotb.test()
async def test_load_protocol_unchanged_by_the_readout(dut):
    """The same image, loaded three ways, runs on the same edges:
    (a) no readout at all (DR 0001's host);
    (b) the readout with the clock stopped, then MODE dropped;
    (c) the readout with the clock running -- 15 more edges with MODE
        high, the readout stable on every one of them -- then MODE dropped;
        the 15 stray bits are a partial word and are discarded.
    In each case uo_out is 0x00 from the MODE-drop edge until the program's
    first OUT, even though the CRC on it a moment earlier was not, and
    BOOT_STATUS reads 0x01."""
    start_clock(dut)
    rng = random.Random(0xB007)
    image = marker_program(random_image(rng, 9))
    crc = host_crc(image)
    assert (crc & 0xFF) not in (0x00, 0xA5, 0x01, 0x3C), "test premise: CRC low byte is distinctive"
    n = len(MARKER_TRACE)

    # (a) no readout
    await enter_load(dut)
    await shift_bits(dut, bits_of(image))
    trace_a = await run_and_trace(dut, n)
    assert trace_a == MARKER_TRACE, f"plain load: uo_out trace {[hex(v) for v in trace_a]}"

    # (b) readout with the clock stopped
    got = await load_and_read(dut, bits_of(image))
    assert got == crc
    trace_b = await run_and_trace(dut, n, wiggle_sel=True)
    assert trace_b == MARKER_TRACE, f"readout then run: uo_out trace {[hex(v) for v in trace_b]}"

    # (c) readout with the clock running
    await enter_load(dut)
    await shift_bits(dut, bits_of(image))
    for k in range(15):
        sel = CRC_SEL if k % 2 else 0
        dut.ui_in.value = MODE | sel | 1          # stray data bits: all ones
        await RisingEdge(dut.clk)
        got = await pins(dut)
        want = (crc >> 8) if sel else (crc & 0xFF)
        assert got == want, (
            f"readout moved on stray edge {k + 1} of 15 after the last word: "
            f"{got:#04x}, want {want:#04x}"
        )
    trace_c = await run_and_trace(dut, n)
    assert trace_c == MARKER_TRACE, (
        f"running-clock readout then run: uo_out trace {[hex(v) for v in trace_c]}"
    )


@cocotb.test()
async def test_no_readout_outside_the_load_phase(dut):
    """uo_out is 0x00 while reset is held and on the mode-sampling cycle,
    for either value of ui_in[1] and of MODE -- including a reset taken
    straight after a load that left a non-zero CRC. A second reset clears
    the CRC: the next load's readout starts from 0 again."""
    start_clock(dut)
    rng = random.Random(0x0FF5)
    image = random_image(rng, 6)
    crc = host_crc(image)
    assert (crc & 0xFF) and (crc >> 8), "test premise: both CRC bytes are non-zero"
    got = await load_and_read(dut, bits_of(image))
    assert got == crc

    for mode in (MODE, 0x00):
        dut.ui_in.value = mode
        dut.rst_n.value = 0
        await Timer(1, unit="ns")  # asynchronous reset: no edge needed
        for sel in (0, CRC_SEL, 0, CRC_SEL):
            dut.ui_in.value = mode | sel
            await Timer(1, unit="ns")
            assert int(dut.uo_out.value) == 0x00, (
                f"uo_out is {int(dut.uo_out.value):#04x} in reset "
                f"(MODE {'high' if mode else 'low'}, ui_in[1]={1 if sel else 0})"
            )
            await RisingEdge(dut.clk)
        # release; the cycle before the mode-sampling edge
        dut.ui_in.value = mode
        await Timer(1, unit="ns")
        dut.rst_n.value = 1
        for sel in (0, CRC_SEL):
            dut.ui_in.value = mode | sel
            await Timer(1, unit="ns")
            assert int(dut.uo_out.value) == 0x00, (
                f"uo_out is {int(dut.uo_out.value):#04x} before the mode-sampling "
                f"edge (MODE {'high' if mode else 'low'})"
            )
        if mode:
            # Into the load phase again: the CRC restarted from 0.
            dut.ui_in.value = mode
            await RisingEdge(dut.clk)  # the mode-sampling edge
            await Timer(1, unit="ns")
            assert await read_crc(dut) == 0x0000, "a reset must clear the CRC"
            await shift_bits(dut, bits_of(image[:2]))
            await Timer(1, unit="ns")
            assert await read_crc(dut) == host_crc(image[:2])


@cocotb.test()
async def test_readout_holds_at_saturation(dut):
    """After 256 words the load saturates (DR 0001): further bits commit
    nothing, and the readout stays at the 256-word image's CRC through two
    more words' worth of edges."""
    start_clock(dut)
    rng = random.Random(0x5A70)
    image = random_image(rng, 256)
    crc = host_crc(image)
    got = await load_and_read(dut, bits_of(image))
    assert got == crc
    extra = bits_of(random_image(rng, 2))
    for k, bit in enumerate(extra):
        dut.ui_in.value = MODE | bit
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        got = await read_crc(dut, data_bit=bit)
        assert got == crc, (
            f"readout moved to {got:#06x} on edge {k + 1} past saturation "
            f"(want {crc:#06x})"
        )
