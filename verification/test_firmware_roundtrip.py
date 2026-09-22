"""cocotb round-trip bench: assembler output through the program-memory
load path (issue #22, `spec/decision-records/0003-firmware-toolchain.md`).

The claim this bench substantiates is the firmware toolchain's round trip:
a `.asm` source program, assembled by `firmware/tools/asm.py`, loads
serially through `rtl/protocol_program_memory.v`'s DR 0001 load phase and
reads back byte-for-byte through the fetch port the ISA core will execute
from -- the assembler's encoding and the RTL agreeing on every word, which
is the actual claim, not either side alone. The committed image
(`firmware/build/demo_roundtrip.hex`) is checked for freshness against the
committed source here too, so a stale build artifact fails this bench
rather than silently re-proving an old program.

Scope note: the ISA core datapath (issue #18) does not exist yet, so
"executes correctly in the bench" here means the program-memory path the
core's fetch will drive -- the same out-of-band readback stance as
`verification/test_program_memory.py`, per DR 0001's "no readback
instruction" constraint (the 16-opcode table is exactly full). When #18
lands, executing assembled programs on the core itself becomes that
issue's bench.

Driven by `klt functional-verification` (see
`verification/request-firmware-roundtrip.json`) against
`rtl/protocol_program_memory.v`. Like `test_program_memory.py`, this file
is *input* to `klt functional-verification`, not a pytest module.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

CLK_PERIOD_NS = 10  # matches the 1ns/1ps timescale and a 50 MHz nominal


def _find_repo_root() -> Path:
    """Locate the repo root from this bench's file location or the cwd.

    `klt functional-verification` may run the testbench module from a
    scratch directory, so both anchors are tried; the marker is the
    committed toolchain layout (`firmware/tools/asm.py` next to
    `spec/target-spec.md`)."""
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent)
    except NameError:  # pragma: no cover - defensive
        pass
    candidates.append(Path.cwd())
    for start in candidates:
        for probe in [start, *start.parents]:
            if (probe / "firmware" / "tools" / "asm.py").exists() and (
                probe / "spec" / "target-spec.md"
            ).exists():
                return probe
    raise RuntimeError(
        "cannot locate the repo root (needed for firmware/ and the "
        "committed build artifacts); run via klt functional-verification "
        "from the repository, or from any directory inside it"
    )


REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

DEMO_SRC = REPO_ROOT / "firmware" / "asm" / "demo_roundtrip.asm"
DEMO_HEX = REPO_ROOT / "firmware" / "build" / "demo_roundtrip.hex"
DEMO_CYCLES = REPO_ROOT / "firmware" / "build" / "demo_roundtrip.cycles.txt"


def load_committed_image() -> list:
    """Parse the committed hex image (one 4-hex-digit word per line)."""
    words = []
    for line in DEMO_HEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        words.append(int(line, 16))
    assert words, "committed image is empty"
    return words


def decode_cycles_independently(words: list) -> int:
    """Recompute the fall-through cycle count straight from the image.

    Deliberately independent of the assembler's own accounting: this
    decodes each 16-bit word's opcode per DR 0001's table (all 1 cycle
    except WAIT, opcode 0xB, which is imm8 + 1) so the bench cross-checks
    the committed cycle report rather than trusting it.
    """
    total = 0
    for word in words:
        opcode = (word >> 12) & 0xF
        if opcode == 0xB:
            total += (word & 0xFF) + 1
        else:
            total += 1
    return total


def parse_cycle_sections() -> dict:
    """Parse `CYCLES name=... start=... end=... cycles=...` report lines."""
    sections = {}
    pattern = re.compile(
        r"^CYCLES name=(\S+) start=(\d+) end=(\d+) cycles=(\d+) branches=(\S+)$"
    )
    for line in DEMO_CYCLES.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            name, start, end, cycles, _branches = match.groups()
            sections[name] = (int(start), int(end), int(cycles))
    return sections


async def reset_release(dut, mode, settle_cycles=0):
    """Reset release with `mode` pre-driven (same sequencing contract as
    `test_program_memory.py`: the next rising edge after release is the
    mode-sampling edge and shifts nothing)."""
    dut.mode_pin.value = mode
    dut.serial_in.value = 0
    dut.fetch_addr.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge
    if settle_cycles:
        await ClockCycles(dut.clk, settle_cycles)


async def load_words(dut, words):
    """Shift `words` MSB-first, one bit per rising edge with MODE high,
    then drop MODE on its own edge (DR 0001 load phase)."""
    dut.mode_pin.value = 1
    for word in words:
        for b in range(15, -1, -1):
            dut.serial_in.value = (word >> b) & 1
            await RisingEdge(dut.clk)
    dut.mode_pin.value = 0
    await RisingEdge(dut.clk)  # the MODE-drop edge: exit to run phase


async def fetch_word(dut, addr):
    """Combinational fetch read -- the same-cycle instruction path the
    core's fetch-and-execute will drive."""
    dut.fetch_addr.value = addr
    await Timer(1, unit="ns")
    return int(dut.instr_word.value)


async def read_reg(dut, name):
    """Read a registered output post-NBA (see test_program_memory.py's
    note on this cocotb/Icarus read region)."""
    await ReadOnly()
    return int(getattr(dut, name).value)


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source:
    re-assembling `demo_roundtrip.asm` with the committed assembler must
    reproduce `firmware/build/demo_roundtrip.hex` and `.cycles.txt`
    byte-for-byte (DR 0003: committed, not regenerated ad hoc)."""
    program = asm.assemble_file(DEMO_SRC)
    drift = asm.check_against(program, DEMO_HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert program.warnings == [], "committed demo program must be lint-clean"


@cocotb.test()
async def test_assembled_program_loads_through_program_memory(dut):
    """The round trip itself: the committed assembler image serially
    loads (MSB-first, one bit per clock, MODE-gated per DR 0001's load
    protocol) into `protocol_program_memory` and every word reads back
    exactly through the fetch port. Also pins the load timing in cycles:
    1 sampling + 16*N bit + 1 exit edges, the same cycle-exact contract
    `test_program_memory.py` established for the module."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = load_committed_image()
    assert len(words) <= 256

    await reset_release(dut, 1)
    t_sampled_ns = get_sim_time("ns")  # right after the mode-sampling edge
    assert await read_reg(dut, "run_phase") == 0, "load phase must be active"
    # Leave the read-only region with a mid-period timer hop -- an extra
    # clock edge here would itself shift a data bit (the RTL shifts one bit
    # on EVERY load-phase edge, by contract; test_program_memory.py's
    # single-word test pins why no edge may pass here).
    await Timer(1, unit="ns")

    await load_words(dut, words)
    t_exit_ns = get_sim_time("ns")

    want_edges = 16 * len(words) + 1
    assert t_exit_ns - t_sampled_ns == want_edges * CLK_PERIOD_NS, (
        f"load span {t_exit_ns - t_sampled_ns} ns, want {want_edges} edges "
        f"= {want_edges * CLK_PERIOD_NS} ns"
    )
    assert await read_reg(dut, "run_phase") == 1, "MODE drop must begin run phase"
    await RisingEdge(dut.clk)  # leave the read-only region before writing

    for addr, want in enumerate(words):
        got = await fetch_word(dut, addr)
        assert got == want, (
            f"fetch[{addr}] = {got:#06x}, want {want:#06x} -- assembler "
            "image and RTL program memory disagree"
        )


@cocotb.test()
async def test_cycle_report_cross_checks_against_image(dut):
    """The committed cycle-accounting report agrees with cycle arithmetic
    recomputed independently from the image words (opcode 0xB stalls
    imm8+1; everything else is 1 cycle per DR 0001's opcode table), and
    the banner section's exact entry->exit count equals the same sum over
    its address range."""
    words = load_committed_image()

    match = re.search(r"^WORDS (\d+)$", DEMO_CYCLES.read_text(encoding="utf-8"), re.M)
    assert match, "report missing a WORDS line"
    assert int(match.group(1)) == len(words)

    per_word = decode_cycles_independently(words)
    match = re.search(
        r"^TOTAL-CYCLES (\d+)$", DEMO_CYCLES.read_text(encoding="utf-8"), re.M
    )
    assert match, "report missing a TOTAL-CYCLES line"
    assert int(match.group(1)) == per_word, (
        "committed TOTAL-CYCLES disagrees with image-decoded arithmetic"
    )

    sections = parse_cycle_sections()
    assert "banner" in sections, "demo program must carry its banner cyclesec"
    start, end, cycles = sections["banner"]
    recomputed = decode_cycles_independently(words[start : end + 1])
    assert cycles == recomputed, (
        f"banner section claims {cycles} cycles, image decoding says {recomputed}"
    )
