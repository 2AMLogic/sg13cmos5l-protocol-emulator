"""Gate-level cocotb bench for target-spec row 14 / `spec/verification-plan.md`
section 8: reset, power-up and reselect (issue #131).

The organizers' 2026-10-09 entrant update: "flops don't start at 0, so your
design needs to use the reset signal (rst_n) to get into a known state ...
When your design is deselected it's powered down and loses its state, so
plan to reload the program after it's selected again." Zero-initialized
simulation and a reset driven from time 0 can both hide a flop that is
never reset, so this bench does not trust either: it **puts every flip-flop
of the netlist into a chosen state first** -- all X, or a seeded random
value -- and lets the design run on that state before `rst_n` is applied.

Flow attribution. This bench runs only on the **LibreLane gate-level
netlist** (the Tiny Tapeout `gds` workflow's `tt_submission` netlist, the
flow of record), zero-delay, under Icarus + cocotb through the template's
`test/Makefile` `GATES=yes` plumbing; `flow/run-reset-power-up-gate-level.sh`
drives it and names the netlist in `RESET_POWER_UP_NETLIST`. It produces no
synthesis or timing number of either flow.

How the initial state is set, without editing the netlist. The state of a
`sg13cmos5l_dfrbpq_1` lives in its PDK UDP, which no VPI write reaches
directly. So the bench uses the cell itself: with `rst_n` high it forces
every flop's `D` pin to the chosen value (a random bit, or `x`), takes one
real clock edge -- the UDP captures `D` exactly as it would on silicon --
and releases every force. The SRAM macro model's 256-word array and its
registered read port (`dr_r`, the core's `instr_word`) are written
directly, to random words or X. The netlist file is the frozen artifact,
byte for byte. Then `PRE_RESET_CYCLES` clock edges run with `rst_n` still
high, so the arbitrary state executes (and may write the SRAM) before reset
-- the case of a design that is clocked before anyone presses reset. Only
then is `rst_n` pulsed. Which flops exist is not hand-listed here: they are
parsed from the netlist by `verification/reset_coverage.py`, the same
parser that grades the reset-coverage listing.

What is checked, per sample (every clock edge, in reset and after), with
every violation of a sample reported together and tagged with the row-14
clause it breaks:

- **[row14-b] pins**: `uo_out`, `uio_out`, `uio_oe` are free of X/Z and
  equal the documented reset state (all 0x00: every `uio` pin an input,
  DR 0012) -- from the first edge in reset to the end of the window;
- **[row14-a] state**: in reset, every flop holds its documented reset
  value (0: every register in `rtl/` resets to 0, and every
  `sg13cmos5l_dfrbpq_1` resets to 0); after reset, no flop is X;
- **[row14-c] fetch source**: the core never leaves the boot ROM
  (`u_core.rom_exit` and `serial_loaded` stay 0, so `fetch_rom` = 1), and
  the SRAM is read (`A_REN`) only as many times as the independent
  `BootModel` of `test_boot_rom.py` says the boot program reads program
  memory as data (0 for the stub straps, 256 for the warm-start check);
  at the end of the window the core is halted at the stub DR 0013's strap
  table names. That is "decodes nothing from program memory" checked on
  the PC and the macro's read strobe, not only on the pins.

And across runs: for the stub straps the **whole flop trace** -- every flop,
every edge -- is bit-identical across the all-X run and every seed; for the
warm-start strap, whose registers carry the SRAM's (random) data by design,
every flop except the data registers is bit-identical and the pins are.

X and the warm start. Strap 10 reads all 256 words and branches on their
CRC. With an X array, Icarus turns that into an X branch and an X PC, which
is the simulator's pessimism (silicon cells hold *some* value) and is what
the seeded runs cover. So the all-X run starts every flop at X for every
strap, and gives the SRAM an X array for the three stub straps (which never
read it) and a seeded random array for strap 10. This is the same carve-out
`test_boot_rom.py` documents.

Seeds are literals below and every image is drawn from `random.Random` on
them, so every run is byte-reproducible. Results go to the cocotb log and,
when `RESET_POWER_UP_SUMMARY` is set, to a JSON summary for the record.
"""

import functools
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer
from cocotb.types import LogicArray

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reset_coverage  # noqa: E402  (the netlist parser the listing uses)
import test_boot_rom as boot  # noqa: E402  (BootModel, the canary, the loaders)
from firmware_artifacts import parse_hex_image, total_cycles  # noqa: E402

GATE_LEVEL = os.environ.get("GATES") == "yes"
NETLIST = os.environ.get("RESET_POWER_UP_NETLIST")
SUMMARY = os.environ.get("RESET_POWER_UP_SUMMARY")

CLK_PERIOD_NS = 10
RESET_CYCLES = 10           # the rst_n pulse every bench in this repo uses
PRE_RESET_CYCLES = 8        # the arbitrary state runs this long before reset
WINDOW_TAIL = 64            # edges observed after the boot program stops
DOCUMENTED_RESET_VALUE = 0  # rtl/*.v: every register resets to 0
PINS = ("uo_out", "uio_out", "uio_oe")
SRAM_CELL = "RM_IHPSG13_1P_256x16_c2_bm_bist"
SRAM_CORE = "i_SRAM_1P_behavioral_bm_bist"

# The recorded seeds (>= 8, issue #131). Never edit one: add a new one.
SEEDS = (0x131, 0x1310, 0xC0FFEE, 0x5EED0001, 0x5EED0002, 0x0DEC1DE, 0xB007, 0x2027_0118)
RESELECT_SEEDS = (0x131, 0x5EED0002)
X_RUN_WARM_SEED = 0x131_10  # the strap-10 SRAM array of the all-X run

# Flops whose value is program-memory *data* during the warm-start check
# (R0..R3, the PM_DATA latches, PM_CRC): they legitimately differ when the
# SRAM's random contents differ, so the strap-10 cross-run comparison
# leaves them out. Prefixes of the netlist's flop output nets.
DATA_FLOPS = ("u_core.regs", "u_core.pm_lo", "pm_wdata", "pm_crc")

UART_TX_HEX = boot.REPO_ROOT / "firmware" / "build" / "uart_tx.hex"
UART_TX_CYCLES = total_cycles(
    (boot.REPO_ROOT / "firmware" / "build" / "uart_tx.cycles.txt").read_text(encoding="utf-8"))

_RESULTS = {"x": {}, "seeds": {}, "uninitialised": [], "reselect": [], "failures": {}}
_REFERENCE = {}  # straps -> the first full run (all-X if it ran): the cross-run reference


def _write_summary():
    if SUMMARY:
        Path(SUMMARY).write_text(json.dumps(_RESULTS, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recorded(test):
    """Copy a failing test's assertion message into the summary (the
    negative-control runner checks *which* row-14 clause failed), then
    re-raise it unchanged."""
    @functools.wraps(test)
    async def wrapper(dut):
        try:
            await test(dut)
        except AssertionError as exc:
            _RESULTS["failures"][test.__name__] = str(exc)
            _write_summary()
            raise
    return wrapper


def _digest(trace):
    return hashlib.sha256("\n".join(trace).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The netlist's state elements, as handles
# ---------------------------------------------------------------------------
class Handles:
    """Every flop of the netlist (from `reset_coverage.classify`) with its
    D/Q handles, and the SRAM model's array, read register and A_REN."""

    def __init__(self, dut):
        assert GATE_LEVEL, "test_reset_power_up is a gate-level bench: run it with GATES=yes"
        assert NETLIST, "RESET_POWER_UP_NETLIST must name the netlist under test"
        cells = reset_coverage.parse_cell_library(
            reset_coverage.default_stdcell_model().read_text(encoding="utf-8"))
        netlist = reset_coverage.parse_netlist(Path(NETLIST).read_text(encoding="utf-8"))
        self.elements = reset_coverage.classify(netlist, cells)
        flops = sorted((e for e in self.elements if e["kind"] == "flop"), key=lambda e: e["element"])
        self.names = [e["element"] for e in flops]
        up = dut.user_project
        self.flops = []
        for e in flops:
            inst = up._id(e["instance"], extended=False)
            self.flops.append((inst.D, inst.Q))
        self.index = {name: i for i, name in enumerate(self.names)}
        sram = [c for c in up if type(c).__name__ == "HierarchyObject"
                and getattr(c, "_def_name", None) == SRAM_CELL]
        assert len(sram) == 1, f"expected one {SRAM_CELL} instance, found {len(sram)}"
        ports = {c._name: c for c in sram[0]}
        self.a_ren = ports["A_REN"]
        core = {c._name: c for c in ports[SRAM_CORE]}
        self.memory = core["memory"]
        self.dr_r = core["dr_r"]
        self.pc_bits = [self.index[f"u_core.pc[{i}]"] for i in range(8)]
        self.halted = self.index["u_core.halted"]
        self.rom_exit = self.index["u_core.rom_exit"]
        self.serial_loaded = self.index["serial_loaded"]
        self.control = [i for i, n in enumerate(self.names) if not n.startswith(DATA_FLOPS)]

    def state(self):
        """The flop vector as a string, one character per flop (0/1/x/z)."""
        return "".join(str(q.value).lower() for _d, q in self.flops)

    def read_memory(self):
        words = []
        for i in range(boot.PM_WORDS):
            v = self.memory[i].value
            words.append(int(v) if v.is_resolvable else None)
        return words

    def pc(self, state):
        bits = [state[i] for i in self.pc_bits]
        return int("".join(reversed(bits)), 2) if all(b in "01" for b in bits) else None


_HANDLES = None


def handles(dut):
    global _HANDLES
    if _HANDLES is None:
        _HANDLES = Handles(dut)
    return _HANDLES


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


# ---------------------------------------------------------------------------
# Power-down / power-up
# ---------------------------------------------------------------------------
async def power_up(dut, h, flops, memory, label):
    """Give every flop an arbitrary state and the SRAM arbitrary contents,
    then run `PRE_RESET_CYCLES` edges on it with rst_n high.

    `flops`: "x", or a list of bits (one per `h.names` entry).
    `memory`: "x", or 256 words. The dr_r register gets X or word 0's
    complement (any value; it is not a fetched word).
    """
    await FallingEdge(dut.clk)
    dut.ena.value = 1
    dut.rst_n.value = 1
    for i, (d, _q) in enumerate(h.flops):
        d.value = Force(LogicArray("x") if flops == "x" else LogicArray(str(flops[i])))
    await RisingEdge(dut.clk)
    await ReadOnly()
    got = h.state()
    want = "x" * len(h.flops) if flops == "x" else "".join(str(b) for b in flops)
    assert got == want, f"{label}: the forced power-up state did not take ({got} vs {want})"
    await FallingEdge(dut.clk)
    for d, _q in h.flops:
        d.value = Release()
    for i in range(boot.PM_WORDS):
        h.memory[i].value = LogicArray("x" * 16) if memory == "x" else memory[i]
    h.dr_r.value = LogicArray("x" * 16) if memory == "x" else (~memory[0]) & 0xFFFF
    await ClockCycles(dut.clk, PRE_RESET_CYCLES)


def random_state(h, rng):
    return [rng.getrandbits(1) for _ in h.names], [rng.randrange(0x10000) for _ in range(boot.PM_WORDS)]


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
async def sample(dut, h, label, in_reset, violations_out=None):
    """One sample, after the edge just taken. Returns (pins, state, a_ren).
    Every violation is collected and asserted together, tagged."""
    await ReadOnly()
    v = []
    pins = {}
    for name in PINS:
        value = getattr(dut, name).value
        if not value.is_resolvable:
            v.append(f"[row14-b] {name} = {value} (X/Z on a pin)")
            pins[name] = str(value)
        else:
            pins[name] = int(value)
            if pins[name] != 0:
                v.append(f"[row14-b] {name} = {pins[name]:#04x}, documented reset state is 0x00")
    state = h.state()
    if in_reset:
        bad = [h.names[i] for i, c in enumerate(state) if c != str(DOCUMENTED_RESET_VALUE)]
        if bad:
            v.append(f"[row14-a] in reset, {len(bad)} flop(s) not at their documented reset "
                     f"value {DOCUMENTED_RESET_VALUE}: {bad[:8]}")
    else:
        bad = [h.names[i] for i, c in enumerate(state) if c not in "01"]
        if bad:
            v.append(f"[row14-a] {len(bad)} flop(s) X/Z after reset: {bad[:8]}")
    if state[h.rom_exit] != "0" or state[h.serial_loaded] != "0":
        v.append(f"[row14-c] fetch source left the boot ROM (rom_exit={state[h.rom_exit]}, "
                 f"serial_loaded={state[h.serial_loaded]})")
    ren = h.a_ren.value
    a_ren = int(ren) if ren.is_resolvable else None
    if a_ren is None:
        v.append(f"[row14-c] SRAM A_REN is {ren}")
    elif in_reset and a_ren:
        v.append("[row14-c] SRAM read enabled during reset")
    assert not v, f"{label}: " + "; ".join(v)
    await Timer(1, unit="ns")
    return pins, state, a_ren


async def reset_and_observe(dut, h, straps, label):
    """Pulse rst_n with MODE low and `straps` on ui_in[6:5]; observe every
    edge of the pulse, then edge 0 (the mode-sampling edge) to the end of
    the boot program plus `WINDOW_TAIL`. Returns a dict for the summary."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = (straps & 3) << 5
    dut.rst_n.value = 0
    await Timer(1, unit="ns")  # rst_n is asynchronous: the reset holds now
    await sample(dut, h, f"{label}, rst_n asserted", in_reset=True)
    for e in range(RESET_CYCLES):
        await RisingEdge(dut.clk)
        await sample(dut, h, f"{label}, reset edge {e + 1}", in_reset=True)
    image = h.read_memory()
    result, model = boot.boot_outcome(straps, image)
    stub = boot.expected_stub(straps, result)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # edge 0: the mode-sampling edge
    edges = boot.RUN_ENTRY_EDGES + result["cycles"] + WINDOW_TAIL
    trace, pins_trace, reads = [], [], 0
    for e in range(edges + 1):
        if e:
            await RisingEdge(dut.clk)
        pins, state, a_ren = await sample(dut, h, f"{label}, edge {e}", in_reset=False)
        trace.append(state)
        pins_trace.append(f"{pins['uo_out']:02x}{pins['uio_out']:02x}{pins['uio_oe']:02x}")
        reads += a_ren
    end = trace[-1]
    pc, halted = h.pc(end), end[h.halted]
    assert halted == "1" and pc == stub, (
        f"{label}: [row14-c] the boot program did not stop in the stub DR 0013's strap table "
        f"names: halted={halted} pc={pc} (expected HALT at {stub:#04x})"
    )
    assert reads == model.pm_reads, (
        f"{label}: [row14-c] the SRAM was read {reads} time(s); the boot program reads program "
        f"memory as data {model.pm_reads} time(s), so {reads - model.pm_reads} read(s) were fetches"
    )
    after = h.read_memory()
    assert after == image, f"{label}: [row14-c] program memory changed while the boot ROM ran"
    return {
        "straps": f"{straps:02b}", "edges_after_reset": edges, "stub_pc": stub,
        "sram_reads": reads, "sram_x_words": sum(w is None for w in image),
        "flop_trace_sha256": _digest(trace),
        "control_trace_sha256": _digest(["".join(s[i] for i in h.control) for s in trace]),
        "pin_trace_sha256": _digest(pins_trace),
        "_trace": trace, "_pins": pins_trace,
    }


def _public(run):
    return {k: v for k, v in run.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
@cocotb.test()
@recorded
async def test_netlist_state_elements(dut):
    """The bench's flop list is the netlist's (parsed by reset_coverage.py,
    which also grades the reset-coverage listing), every flop is reached
    by a D force, and the SRAM model's array is reachable. No claim about
    the design yet; this pins what the other tests force and observe."""
    start_clock(dut)
    h = handles(dut)
    flops = [e for e in h.elements if e["kind"] == "flop"]
    macros = [e for e in h.elements if e["kind"] == "macro"]
    dut._log.info(f"{len(flops)} flops, {len(macros)} macro(s): {[m['element'] for m in macros]}")
    assert len(h.flops) == len(flops) > 0
    wrong = [e["element"] for e in flops if e["reset"] and e["reset_value"] != DOCUMENTED_RESET_VALUE]
    assert not wrong, f"flops whose cell resets them to other than the documented value: {wrong}"
    assert [m["cell"] for m in macros] == [SRAM_CELL], macros
    assert len(h.memory) == boot.PM_WORDS
    _RESULTS["netlist"] = {"path": NETLIST, "flops": len(flops),
                           "macros": [m["element"] for m in macros],
                           "flop_order": h.names}
    _write_summary()
    await ClockCycles(dut.clk, 2)


@cocotb.test()
@recorded
async def test_power_up_all_x(dut):
    """Every flop starts at X (and the SRAM array at X for the stub straps,
    see the module docstring for strap 10). rst_n alone brings every flop
    to 0 in reset; afterwards no pin is X or leaves its reset value, no
    flop is X, and the core stays in the boot ROM and halts in its stub."""
    start_clock(dut)
    h = handles(dut)
    for straps in boot.STRAPS:
        label = f"all-X power-up, straps {straps:02b}"
        if straps == boot.STRAP_WARM:
            _bits, memory = random_state(h, random.Random(X_RUN_WARM_SEED))
        else:
            memory = "x"
        await power_up(dut, h, "x", memory, label)
        run = await reset_and_observe(dut, h, straps, label)
        _REFERENCE[run["straps"]] = dict(run, source="all-X run")
        _RESULTS["x"][run["straps"]] = _public(run)
        dut._log.info(f"{label}: {_public(run)}")
    _write_summary()


@cocotb.test()
@recorded
async def test_power_up_random_seeds(dut):
    """For each recorded seed: every flop and every SRAM word starts at a
    seeded random value, then the same checks as the all-X run. Across the
    all-X run and every seed, the flop trace after reset is bit-identical
    (strap 10: every flop but the data registers), and so are the pins."""
    start_clock(dut)
    h = handles(dut)
    assert len(SEEDS) >= 8 and len(set(SEEDS)) == len(SEEDS)
    seen_states = set()
    for seed in SEEDS:
        rng = random.Random(seed)
        runs = {}
        for straps in boot.STRAPS:
            label = f"seed {seed:#x}, straps {straps:02b}"
            bits, memory = random_state(h, rng)
            seen_states.add(tuple(bits))
            await power_up(dut, h, bits, memory, label)
            run = await reset_and_observe(dut, h, straps, label)
            runs[run["straps"]] = run
            ref = _REFERENCE.setdefault(run["straps"], dict(run, source=f"seed {seed:#x}"))
            if ref is not run:
                key = "control_trace_sha256" if straps == boot.STRAP_WARM else "flop_trace_sha256"
                if run[key] != ref[key]:
                    trace_key = "_trace"
                    for e, (a, b) in enumerate(zip(ref[trace_key], run[trace_key])):
                        cols = [i for i in range(len(a)) if a[i] != b[i]
                                and (straps != boot.STRAP_WARM or i in h.control)]
                        if cols:
                            raise AssertionError(
                                f"{label}: [row14-a] state after reset depends on the power-up "
                                f"state: edge {e} differs from the {ref['source']} in "
                                f"{[h.names[i] for i in cols][:8]}")
                assert run["pin_trace_sha256"] == ref["pin_trace_sha256"], (
                    f"{label}: [row14-b] pin trace differs from the {ref['source']}")
            dut._log.info(f"{label}: {_public(run)}")
        _RESULTS["seeds"][f"{seed:#x}"] = {k: _public(v) for k, v in runs.items()}
        _write_summary()
    assert len(seen_states) == len(SEEDS) * len(boot.STRAPS), "premise: the power-up states differ"


@cocotb.test()
@recorded
async def test_uninitialised_program_memory(dut):
    """Row 14 (c), with a live detector. The SRAM holds the canary image of
    test_boot_rom.py -- one that drives uo_out and every uio enable within
    five instructions of entry at ANY address -- and the flops a seeded
    random state; MODE is low at reset. For every strap the core runs the
    boot ROM, the macro is never read for a fetch, and the canary never
    runs (no pin moves). The canary is first shown driving the pins when
    it is serial-loaded, so a core that fetched it would be seen."""
    start_clock(dut)
    h = handles(dut)
    canary = boot.canary_image()
    await boot.serial_load(dut, canary)
    for _ in range(12):
        await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.uo_out.value) == 0xFF and int(dut.uio_oe.value) == 0xFF, (
        "premise: the canary does not drive the pins when it runs")
    await Timer(1, unit="ns")
    rng = random.Random(0x131C)
    for straps in boot.STRAPS:
        label = f"canary SRAM, random flops, straps {straps:02b}"
        bits, _memory = random_state(h, rng)
        await power_up(dut, h, bits, canary, label)
        run = await reset_and_observe(dut, h, straps, label)
        _RESULTS["uninitialised"].append(_public(run))
        dut._log.info(f"{label}: {_public(run)}")
    _write_summary()


async def run_loaded(dut, h, words, edges, label):
    """Serial-load `words` (DR 0001 layer 1, MODE high at reset) and record
    the pins and the flop vector for `edges` edges after the MODE drop."""
    await boot.serial_load(dut, words)
    pins_trace, trace = [], []
    for e in range(edges + 1):
        if e:
            await RisingEdge(dut.clk)
        await ReadOnly()
        values = [getattr(dut, n).value for n in PINS]
        assert all(v.is_resolvable for v in values), f"{label}: edge {e}: X/Z on a pin {values}"
        pins_trace.append("".join(f"{int(v):02x}" for v in values))
        trace.append(h.state())
        await Timer(1, unit="ns")
    return pins_trace, trace


@cocotb.test()
@recorded
async def test_reselect(dut):
    """The organizers' deselect/reselect cycle. Load the committed UART TX
    firmware and run it; power-cycle (every flop and SRAM word random);
    reset with MODE low and no reload -- the core must sit in a safe idle
    (the checks above: boot ROM only, stub HALT, no pin moves, no fetch
    from the SRAM); power-cycle again; reload the same image and run it.
    The second run's pins and flop trace equal the first's, edge for edge.
    The host's side of this (reload after every select) is issue #118."""
    start_clock(dut)
    h = handles(dut)
    image = parse_hex_image(UART_TX_HEX)
    edges = UART_TX_CYCLES + boot.RUN_ENTRY_EDGES + 16
    for seed in RESELECT_SEEDS:
        rng = random.Random(seed ^ 0x5E1EC7)
        bits, memory = random_state(h, rng)
        await power_up(dut, h, bits, memory, f"reselect {seed:#x}: first power-up")
        first_pins, first = await run_loaded(dut, h, image, edges, f"reselect {seed:#x}: first run")
        moves = sum(1 for a, b in zip(first_pins, first_pins[1:]) if a != b)
        assert moves >= 8, f"premise: the UART TX run moved the pins only {moves} time(s)"

        bits, memory = random_state(h, rng)
        label = f"reselect {seed:#x}: reset without reload"
        await power_up(dut, h, bits, memory, label)
        idle = await reset_and_observe(dut, h, boot.STRAP_UART, label)

        bits, memory = random_state(h, rng)
        await power_up(dut, h, bits, memory, f"reselect {seed:#x}: second power-up")
        second_pins, second = await run_loaded(dut, h, image, edges, f"reselect {seed:#x}: second run")
        for e, (a, b) in enumerate(zip(first_pins, second_pins)):
            assert a == b, f"reselect {seed:#x}: pins differ at edge {e}: first {a}, second {b}"
        for e, (a, b) in enumerate(zip(first, second)):
            if a != b:
                cols = [h.names[i] for i in range(len(a)) if a[i] != b[i]]
                raise AssertionError(f"reselect {seed:#x}: flop state differs at edge {e}: {cols[:8]}")
        entry = {"seed": f"{seed:#x}", "firmware": "firmware/build/uart_tx.hex",
                 "edges_after_mode_drop": edges, "pin_moves": moves,
                 "pin_trace_sha256": _digest(first_pins), "flop_trace_sha256": _digest(first),
                 "idle_without_reload": _public(idle)}
        _RESULTS["reselect"].append(entry)
        dut._log.info(f"reselect {seed:#x}: {entry}")
    _write_summary()
