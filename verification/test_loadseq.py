"""cocotb RTL replay of the host-side load sequence (issue #118).

Claim: the operations `firmware/tools/loadseq.py` generates for an image,
played through the adapter contract of `firmware/tools/loadseq_playback.py`
(`iter_ops`), load that image into `rtl/protocol_program_memory.v` word for
word, read back through the fetch port the core executes from.

Independence: the clock, the pin driving and the readback below are written
from the load-phase contract in the RTL header and `docs/info.md`; this file
deliberately does NOT use `_dut.load_program`, `test_protocol_emulator.
load_program` or `test_firmware_roundtrip.reset_release/load_words`. The
clock is driven *by the generated operations* (`set_clk`, `wait_us`; one
unit of `wait_us` is simulated as 1 ns here), not by a cocotb `Clock`.

Discriminating power is demonstrated in-bench: byte-swapped words, a missing
MODE-latching edge (a one-bit slip) and a bit-reversed word are each replayed
and must read back as exactly what the mutant encodes, never as the image.

Cross-check against the existing helpers (reported, not reconciled): the
generated sequence has the same shape as `test_protocol_emulator.load_program`
(ten reset clocks; one latch edge; 16 MSB-first edges per word; a separate
MODE-drop edge) and as `test_firmware_roundtrip` (`reset_release` +
`load_words`: 1 + 16N + 1 edges after the reset pulse). No disagreement was
found; `test_generated_sequence_matches_existing_helper_shape` pins the edge
counts so a future divergence is a recorded finding.

Driven by `klt functional-verification` (see `request-loadseq.json`).
Input to klt, not a pytest module. Fixed inputs only: byte-reproducible.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

try:
    from repo_root import find_repo_root
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import loadseq  # noqa: E402
import loadseq_playback as pb  # noqa: E402

SETUP, HIGH, LOW = 2, 5, 3  # "microseconds" of the adapter contract == ns here


def committed_images():
    """Every application image (not the boot ROM under build/boot/)."""
    return sorted((REPO_ROOT / "firmware" / "build").glob("*.hex"))


def asymmetric_words(n):
    """Distinct, non-palindromic words: distinguishes byte/bit reversal and
    off-by-one slips (no word equals its byte swap or reversal by design
    except by chance, which the bench checks for the 1-word case)."""
    return [((i * 0x9E37) ^ 0x1234 ^ (i << 8)) & 0xFFFF for i in range(n)]


class ModuleAdapter:
    """Maps the playback contract onto `protocol_program_memory` ports."""

    def __init__(self, dut):
        self.dut = dut

    def set_ui_in(self, byte):
        assert byte & 0x7E == 0, "load sequence must only use ui_in[7] and ui_in[0]"
        self.dut.mode_pin.value = (byte >> 7) & 1
        self.dut.serial_in.value = byte & 1

    def set_uio_in(self, byte):
        assert byte == 0

    def set_ena(self, value):
        assert value == 1

    def set_rst_n(self, value):
        self.dut.rst_n.value = value

    def set_clk(self, value):
        self.dut.clk.value = value


def tie_off(dut):
    dut.pm_we.value = 0
    dut.pm_re.value = 0
    dut.pm_addr.value = 0
    dut.pm_wdata.value = 0
    dut.pm_crc_clr.value = 0
    dut.fetch_addr.value = 0
    dut.fetch_en.value = 1  # read the array through the fetch port


async def replay(dut, steps):
    adapter = ModuleAdapter(dut)
    for name, arg in pb.iter_ops(steps, SETUP, HIGH, LOW):
        if name == "wait_us":
            await Timer(arg, unit="ns")
        else:
            getattr(adapter, name)(arg)


async def fetch(dut, addr):
    """One manual clock: present addr, edge captures, word valid after it."""
    dut.fetch_addr.value = addr
    await Timer(1, unit="ns")
    dut.clk.value = 1
    await Timer(2, unit="ns")
    value = int(dut.instr_word.value)
    await Timer(3, unit="ns")
    dut.clk.value = 0
    await Timer(4, unit="ns")
    return value


async def readback(dut, n):
    return [await fetch(dut, a) for a in range(n)]


async def load_and_readback(dut, words, steps=None):
    tie_off(dut)
    await replay(dut, loadseq.generate_steps(words) if steps is None else steps)
    assert int(dut.run_phase.value) == 1, "MODE drop must begin the run phase"
    return await readback(dut, len(words))


def assert_equal_words(got, want, what):
    for addr, (g, w) in enumerate(zip(got, want)):
        assert g == w, f"{what}: fetch[{addr}] = {g:#06x}, want {w:#06x}"


@cocotb.test()
async def test_committed_images_load_word_for_word(dut):
    """Every committed application image (UART, SPI, I2C, demo) reads back
    identically from the RTL after replaying its generated sequence."""
    images = committed_images()
    assert len(images) >= 16, images
    for hexfile in images:
        words = loadseq.parse_words(hexfile.read_text(encoding="utf-8"), str(hexfile))
        got = await load_and_readback(dut, words)
        assert_equal_words(got, words, hexfile.name)
        dut._log.info(f"{hexfile.name}: {len(words)} words read back identically")


@cocotb.test()
async def test_asymmetric_one_word_and_full_256(dut):
    one = [0xA5C3]
    assert one[0] != int(f"{one[0]:016b}"[::-1], 2) and one[0] != ((one[0] & 0xFF) << 8 | one[0] >> 8)
    assert_equal_words(await load_and_readback(dut, one), one, "1-word")
    for words in ([0x0001, 0x8000, 0x1234, 0x00FF, 0xFF00, 0x0100, 0x0080],
                  asymmetric_words(256)):
        got = await load_and_readback(dut, words)
        assert len(got) == len(words)
        assert_equal_words(got, words, f"{len(words)}-word")


@cocotb.test()
async def test_reset_reload_replays_the_same_initial_sequence(dut):
    """Re-select model: SRAM contents are not assumed to survive, so a
    reload is the whole sequence again. Full 256 words, then a 1-word image
    and a different 3-word image reload cleanly (word 0 is the new word)."""
    first = asymmetric_words(256)
    assert_equal_words(await load_and_readback(dut, first), first, "first load")
    for words in ([0xDEAD], [0x0F1E, 0x2D3C, 0x4B5A]):
        got = await load_and_readback(dut, words)
        assert_equal_words(got, words, "reload")
        assert got[0] != first[0]


@cocotb.test()
async def test_mode_drop_is_its_own_edge(dut):
    """run_phase stays low through the latch edge and every data edge and
    rises only on the final, separate MODE-drop step."""
    tie_off(dut)
    steps = loadseq.generate_steps([0x1234, 0x5678])
    await replay(dut, steps[:-1])
    assert int(dut.run_phase.value) == 0, "run phase began before MODE drop"
    await replay(dut, steps[-1:])
    assert int(dut.run_phase.value) == 1


@cocotb.test()
async def test_mutants_read_back_as_mutated_not_as_image(dut):
    """The readback can tell the failure modes apart, so a pass is evidence."""
    words = asymmetric_words(5)
    steps = loadseq.generate_steps(words)

    swapped = [((w & 0xFF) << 8) | (w >> 8) for w in words]
    got = await load_and_readback(dut, words, loadseq.generate_steps(swapped))
    assert got == swapped and got != words, "byte-swap mutant not distinguished"

    reversed_ = [int(f"{w:016b}"[::-1], 2) for w in words]
    got = await load_and_readback(dut, words, loadseq.generate_steps(reversed_))
    assert got == reversed_ and got != words, "bit-reversal mutant not distinguished"

    # Missing latch edge: the first data bit lands on the MODE-sampling edge
    # (consumed, shifting nothing), so every word is slipped by one bit.
    slipped = steps[:10] + steps[11:]
    tie_off(dut)
    await replay(dut, slipped)
    got = await readback(dut, 3)
    assert got != words[:3], "one-bit slip (no latch edge) was not detected"


@cocotb.test()
async def test_generated_sequence_matches_existing_helper_shape(dut):
    """Edge-count cross-check against the two existing loaders: reset pulse
    10 clocks, then 1 latch + 16N data + 1 drop (round-trip bench span
    16N+1 after the sampling edge), i.e. 12 + 16N steps in total."""
    for n in (1, 7, 256):
        steps = loadseq.generate_steps(asymmetric_words(n))
        assert sum(1 for s in steps if s[2] == 0) == 10
        assert len(steps) - 10 == 1 + 16 * n + 1
