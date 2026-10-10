"""Top-level MODE/run transition for the generated load sequence (issue #118).

`test_loadseq.py` proves the memory contents module-level. This bench plays
the same generated operations (`loadseq_playback.iter_ops`, one `wait_us`
unit simulated as 1 ns, clock driven by the operations themselves) on the
submitted top `tt_um_2amlogic_protocol_emulator`, through its real pins, and
checks that the transition is right at the pins:

- while the sequence is loading (everything before the final step) the core
  does not run: `uo_out` stays 0 and no pin is driven by firmware;
- the final, separate MODE-drop step is edge 0; the first instruction
  retires at edge 2 and the OUT shows at edge 3 (DR 0005 fetch-ahead,
  the same numbering `test_protocol_emulator.py` documents);
- a sequence stripped of its MODE-drop step never runs the program, however
  many clocks follow;
- the same sequence replayed again after the program ran (re-select style
  reload) restarts it from word 0.

Independent of `_dut.load_program` and the module-bench helpers. Driven by
`klt functional-verification` (see `request-loadseq-top.json`).
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

SETUP, HIGH, LOW = 2, 5, 3

# DR 0001 encoding, written out by hand (not via the assembler):
#   LDI R0,0xA5 = 1<<12 | 0<<10 | 0<<8 | 0xA5
#   OUT uo_out,R0 = 0xA<<12 | R0<<10 | port 2<<8
#   HALT = 0xF000
PROGRAM = [0x10A5, 0xA200, 0xF000]


class TopAdapter:
    def __init__(self, dut):
        self.dut = dut

    def set_ui_in(self, byte):
        self.dut.ui_in.value = byte

    def set_uio_in(self, byte):
        self.dut.uio_in.value = byte

    def set_rst_n(self, value):
        self.dut.rst_n.value = value

    def set_ena(self, value):
        self.dut.ena.value = value

    def set_clk(self, value):
        self.dut.clk.value = value


async def replay(dut, steps):
    adapter = TopAdapter(dut)
    for name, arg in pb.iter_ops(steps, SETUP, HIGH, LOW):
        if name == "wait_us":
            await Timer(arg, unit="ns")
        else:
            getattr(adapter, name)(arg)


async def edge(dut):
    """One manual rising edge; returns uo_out sampled after it settles."""
    dut.clk.value = 1
    await Timer(2, unit="ns")
    value = int(dut.uo_out.value)
    await Timer(3, unit="ns")
    dut.clk.value = 0
    await Timer(5, unit="ns")
    return value


@cocotb.test()
async def test_program_stays_idle_until_mode_drop_then_runs(dut):
    steps = loadseq.generate_steps(PROGRAM)
    await replay(dut, steps[:-1])  # reset, latch, 48 data edges; MODE still high
    assert int(dut.uo_out.value) == 0
    await replay(dut, steps[-1:])  # the MODE-drop step: edge 0
    assert int(dut.uo_out.value) == 0
    seen = [await edge(dut) for _ in range(1, 6)]  # edges 1..5
    assert seen[0] == 0, f"edge 1 (fetch-ahead priming) uo_out={seen[0]:#04x}"
    assert seen[1] == 0, f"edge 2 (LDI retires) uo_out={seen[1]:#04x}"
    assert seen[2] == 0xA5, f"edge 3 (OUT retires) uo_out={seen[2]:#04x}"
    assert seen[3:] == [0xA5, 0xA5], "HALT must hold the output"


@cocotb.test()
async def test_without_mode_drop_the_program_never_runs(dut):
    steps = loadseq.generate_steps(PROGRAM)[:-1]
    await replay(dut, steps)
    for _ in range(20):
        assert await edge(dut) == 0, "ran without a MODE drop"


@cocotb.test()
async def test_reload_after_run_restarts_from_word_zero(dut):
    steps = loadseq.generate_steps(PROGRAM)
    await replay(dut, steps)
    for _ in range(5):
        await edge(dut)
    assert int(dut.uo_out.value) == 0xA5
    other = [0x1033, 0xA200, 0xF000]  # LDI R0,0x33 ; OUT ; HALT
    await replay(dut, loadseq.generate_steps(other))
    assert int(dut.uo_out.value) == 0, "reset did not clear the output register"
    seen = [await edge(dut) for _ in range(1, 4)]
    assert seen == [0, 0, 0x33], seen
