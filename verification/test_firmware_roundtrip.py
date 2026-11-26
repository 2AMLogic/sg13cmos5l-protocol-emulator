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

The pin driver (`reset_release`, `load_words`, `fetch_word`, `read_reg`)
is `verification/program_memory_driver.py`, shared with the load-phase
bench (issue #486) -- the same routines that lived here as duplicate
copies, moved unchanged; this bench's assertions (image freshness, the
round trip itself, the cycle-report cross-check) stay below.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time

CLK_PERIOD_NS = 10  # matches the 1ns/1ps timescale and a 50 MHz nominal


try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

try:
    from program_memory_driver import (
        fetch_word,
        load_words,
        read_reg,
        reset_release,
    )
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from program_memory_driver import (
        fetch_word,
        load_words,
        read_reg,
        reset_release,
    )

REPO_ROOT = find_repo_root(globals().get("__file__"))

try:
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

DEMO_SRC = REPO_ROOT / "firmware" / "asm" / "demo_roundtrip.asm"
DEMO_HEX = REPO_ROOT / "firmware" / "build" / "demo_roundtrip.hex"
DEMO_CYCLES = REPO_ROOT / "firmware" / "build" / "demo_roundtrip.cycles.txt"


def load_committed_image() -> list:
    """Parse the committed hex image (one 4-hex-digit word per line)."""
    return parse_hex_image(DEMO_HEX)


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
    """Parse `CYCLES ...` report lines into (start, end, cycles) triples."""
    shared = _parse_sections(DEMO_CYCLES.read_text(encoding="utf-8"))
    return {name: fields[:3] for name, fields in shared.items()}


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
    assert total_cycles(DEMO_CYCLES.read_text(encoding="utf-8")) == per_word, (
        "committed TOTAL-CYCLES disagrees with image-decoded arithmetic"
    )

    sections = parse_cycle_sections()
    assert "banner" in sections, "demo program must carry its banner cyclesec"
    start, end, cycles = sections["banner"]
    recomputed = decode_cycles_independently(words[start : end + 1])
    assert cycles == recomputed, (
        f"banner section claims {cycles} cycles, image decoding says {recomputed}"
    )
