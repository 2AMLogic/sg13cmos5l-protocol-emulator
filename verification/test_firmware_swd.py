"""DUT-facing SWD probe firmware bench (multi-protocol extra credit, issue
#452; the protocol choice is the dated note of 2026-11-19 in DR 0018, fourth
revision).

The claim: the committed program `firmware/asm/swd_probe.asm` (image
`firmware/build/swd_probe.hex`), loaded over the real serial load-phase pins
onto the real top and run by the ISA core, acts as an SWD **probe** (host) on
SWCLK = `uio[2]` and SWDIO = `uio[3]`: it brings a target up (line reset,
0xE79E JTAG-to-SWD switch, second line reset, idle clocks), reads the DP
IDCODE (request 0xA5) and a second DP register (request 0xBD) through the
turnaround cycles, and reports every response sample on `uo_out` as the
masked SWDIO byte. The target here is the independent model side
(`verification/reference_models/swd.py`, written from Arm's ADIv5
description and pyOCD's observable connection shape alone, constants marked
"confirm" as DR 0018 records). The bench never tells the model what the
waveform looks like; the model drives SWDIO back at the probe with
zero-delay, aggressive-but-legal timing (IHI 0031 B4.3.1: a target may change
or release SWDIO on any rising edge), which is exactly the timing that
catches a probe that samples after the rise instead of before it.

What is graded, and by whom
---------------------------
1. **The lines.** The pad model (`verification/uio_pads.py`) resolves
   SWCLK/SWDIO from the design's own `uio_out`/`uio_oe` and the target's
   driver, with a pull-up on SWDIO (ADIv5 requires it) and SWCLK pulled low
   so it rests defined while the probe pad is off. The six other `uio` lines
   are tied low, so a program that drove one would be reported as
   contention. A probe that keeps SWDIO driven into a response phase fights
   the target's driver and the pad model reports the contention.
2. **The protocol.** The model grades everything it is shown: the 50-clock
   line resets, the 0xE79E switch, the two idle clocks, each request frame
   field by field (start/stop/park and the even request parity), the
   turnaround releases and re-drives, the response parity it drives itself,
   host SWDIO stability across rising edges, and the eight trailing idle
   clocks.
3. **The bytes.** The 72 `uo_out` report samples the bench captures (one per
   response slot, taken at the SWCLK rising edge of each slot, where the
   write has retired) must decode, LSB first, to ACK OK (wire order 1,0,0; numeric
   0b001 sent LSB first) then the IDCODE
   0x4BA00477 with even parity, and ACK OK then the model's second value
   0x12345678 with even parity -- byte for byte what the model drove.
4. **The cycle figures.** SWCLK high/low widths are measured per phase in
   core cycles (the model's ns over the 20 ns simulation clock, which *names*
   target-spec row 4's unconfirmed 50 MHz target) and held against the
   figures DR 0018 records and `firmware/README.md` table: reset 1/3, switch
   and request 2/2, response high 1. 218 SWCLK rising edges in total.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Five mutant programs, each assembled in memory from the committed source with
one defect, run on the same DUT and target and must be rejected for the
defect's own reason: a 49-clock first line reset (the target stays dormant,
`line-reset-short`), a flipped switch bit (`switch-sequence`), a missing
turnaround release (`no-release`, and the pad model reports the two drivers'
contention), a wrong request parity bit (`request-parity`, no response: the
probe reads the pull-up), and a 3-clock trailing idle (`trailing-idle-short`).
Model-configured runs exercise the ACK values a real target may answer with
on a request that can legally fail (the second, RDBUFF): WAIT (wire 0,1,0) and
FAULT (0,0,1) end after the ACK and turnaround (ORUNDETECT = 0), and the probe
reports the ACK, releases the return turnaround, re-drives SWDIO low and idles,
with no retry. Two more negative controls: the ACK branch removed (data slots
clocked after a WAIT) and SWDIO driven on the return turnaround cycle.

Driven by `klt functional-verification` (`verification/request-firmware-
swd.json`) at RTL. No gate-level run is claimed by this bench.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import First, ReadOnly, RisingEdge, Timer, ValueChange
from cocotb.utils import get_sim_time

from reference_models.swd import (
    ACK_FAULT,
    ACK_OK,
    ACK_WAIT,
    REQUEST_BITS,
    RESET_MIN_CYCLES,
    RESPONSE_BITS,
    SWITCH_CODE,
    SwdTarget,
    read_value_parity,
)
from uio_pads import UioPads

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)
from firmware_artifacts import parse_hex_image  # noqa: E402

# The load-phase driver is the one every other bench uses.
from test_protocol_emulator import load_program  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "swd_probe.asm"
HEX = REPO_ROOT / "firmware" / "build" / "swd_probe.hex"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: The lines (DR 0010's swd phase): SWCLK and SWDIO on the I2C Pmod row.
SWCLK_BIT, SWDIO_BIT = 2, 3
SWD_MASK = (1 << SWCLK_BIT) | (1 << SWDIO_BIT)

#: The committed figures DR 0018's note records for this program (core cycles).
EXPECTED_RISES = 218
#: per-phase SWCLK high/low widths in cycles, as measured on the pads and
#: recorded in firmware/README.md's table (boundary transitions included).
EXPECTED_WIDTHS = {
    "reset1": {"high": (1.0, 1.0), "low": (3.0, 6.0)},
    "switch": {"high": (2.0, 2.0), "low": (2.0, 2.0)},
    "reset2": {"high": (1.0, 1.0), "low": (3.0, 6.0)},
    "idle": {"high": (2.0, 2.0), "low": (2.0, 4.0)},
    "request": {"high": (2.0, 2.0), "low": (2.0, 2.0)},
    "response": {"high": (1.0, 1.0), "low": (4.0, 7.0)},
}

#: response slots per transaction (3 ACK + 32 data + 1 parity; DR 0018)
RESPONSE_SLOTS = RESPONSE_BITS
#: request frame bits on the wire (DR 0018)
REQUEST_FRAME_BITS = REQUEST_BITS

IDCODE = 0x4BA00477
SECOND_VALUE = 0x12345678


# =======================================================================
# The board and the target
# =======================================================================


def swd_board(dut):
    """Pads as an SWD board: a pull-up on SWDIO (ADIv5 requires one; the
    probe releases the line for turnaround and response phases), SWCLK
    pulled low so the line rests defined while the probe pad is off, the six
    other `uio` lines tied low. Not started."""
    return UioPads(
        dut,
        pulls={SWCLK_BIT: "down", SWDIO_BIT: "up"},
        tie={p: 0 for p in range(8) if p not in (SWCLK_BIT, SWDIO_BIT)},
        name="swd-board",
    )


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


class TargetAgent:
    """Wires `SwdTarget` to the pads: on every settled change of the resolved
    lines or the design's SWDIO output-enable, shows the model the lines,
    then applies the model's `drive` to the SWDIO pad. The application lands
    one simulation nanosecond after the observation -- cocotb forbids writes
    in the ReadOnly phase where the settled lines are read, and the pad model
    resolves the applied drive immediately at that instant, still within the
    same 20 ns clock cycle and always two or more edges before the probe's
    next `IN` samples the line. That is the zero-delay, aggressive-but-legal
    B4.3.1 timing (a target may change SWDIO on any rising edge), and it
    means the line the model itself observes at a rise is always the
    pre-advance bit. A line the two drivers fight reads 'x'; the agent keeps
    the last known level for the model's protocol view and lets the pad
    model record the contention."""

    def __init__(self, dut, pads, model):
        self.dut = dut
        self.pads = pads
        self.model = model
        self._dio = 1  # pull-up at rest
        self._task = None
        self.unknown = 0

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self):
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self):
        while True:
            await First(ValueChange(self.dut.uio_in), ValueChange(self.dut.uio_oe))
            await ReadOnly()
            clk = self.pads.levels[SWCLK_BIT]
            dio = self.pads.levels[SWDIO_BIT]
            if dio not in ("0", "1"):
                self.unknown += 1
            else:
                self._dio = int(dio)
            if clk in ("0", "1"):
                oe = int(self.dut.uio_oe.value)
                self.model.on_pad(
                    float(get_sim_time("ns")),
                    int(clk),
                    self._dio,
                    bool((oe >> SWDIO_BIT) & 1),
                )
            await Timer(1, unit="ns")  # out of ReadOnly; writes are legal again
            # apply the model's line ownership (resolves at this instant)
            if self.model.drive is None:
                self.pads.release(SWDIO_BIT)
            else:
                self.pads.drive(SWDIO_BIT, self.model.drive)


# =======================================================================
# Running a program and grading it
# =======================================================================


def committed_words():
    return parse_hex_image(HEX)


async def run_probe(dut, words, model, *, cycles):
    """Load `words`, run the probe against `model` for `cycles` clock edges,
    capturing `uo_out`, the resolved `uio` lines and `uio_oe` at every edge.
    Returns (trace, model, pads, agent): trace is a list of per-edge dicts
    with `uo` (binstr), `clk` / `dio` ('0'/'1'/'x'), `oe` (int)."""
    pads = swd_board(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"uio pads 0x{pads.oe_seen:02x} enabled between reset release and "
        "the end of the load"
    )
    agent = TargetAgent(dut, pads, model).start()
    await ReadOnly()
    trace = [{
        "uo": uo_binstr(dut), "clk": pads.levels[SWCLK_BIT],
        "dio": pads.levels[SWDIO_BIT], "oe": int(dut.uio_oe.value),
    }]
    await Timer(1, unit="ns")
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        trace.append({
            "uo": uo_binstr(dut), "clk": pads.levels[SWCLK_BIT],
            "dio": pads.levels[SWDIO_BIT], "oe": int(dut.uio_oe.value),
        })
        await Timer(1, unit="ns")
    agent.stop()
    pads.stop()
    model.finish(float(get_sim_time("ns")))
    return trace, model, pads, agent


def uo_binstr(dut):
    """`uo_out` as a binary string, 'x' bits preserved (the contention
    mutants write x samples; the golden run never does)."""
    return dut.uo_out.value.binstr


def rises_of(trace):
    """Edge indices (1-based over `trace`) of SWCLK rising edges."""
    out = []
    prev = trace[0]["clk"]
    for i, row in enumerate(trace[1:], start=1):
        if row["clk"] == "1" and prev == "0":
            out.append(i)
        prev = row["clk"]
    return out


def response_samples(trace, model):
    """The probe's report bytes: `uo_out` at the SWCLK rising edge of each
    sample slot of every transaction (36 for an OK, 3 for a WAIT / FAULT) (the sample write retires
    one edge before that edge). The slots are located from the model's
    per-rise phase labels: every complete request frame is a run of exactly
    8 `request` rises, the next rise is the clocked turnaround cycle, and
    the 36 after it are the sample slots -- whether the target answered
    (OK, WAIT, FAULT) or rejected the frame and left the line pulled up."""
    edges = rises_of(trace)
    phases = [ph for ph, _ in model.wire]
    assert len(edges) == len(phases), (len(edges), len(phases))
    out = []
    i = 0
    while i < len(phases):
        if phases[i] == "request":
            run = 1
            while i + run < len(phases) and phases[i + run] == "request":
                run += 1
            if run >= REQUEST_FRAME_BITS:
                start = i + run + 1  # skip the turnaround rise
                if start < len(phases) and phases[start] == "response":
                    # a target that answered: WAIT / FAULT end after the
                    # 3 ACK slots, an OK runs to 36
                    n = 0
                    while start + n < len(phases) and phases[start + n] == "response":
                        n += 1
                else:
                    n = RESPONSE_SLOTS
                span = phases[start : start + n]
                assert len(span) == n, "run ended inside a response"
                out.extend(trace[edges[k]]["uo"] for k in range(start, start + n))
                i = start + n
                continue
        i += 1
    return out


def samples_bits(samples):
    """The masked SWDIO bit of each report byte, 'x' preserved."""
    bits = []
    for s in samples:
        assert len(s) == 8
        bits.append(1 if s[7 - SWDIO_BIT] == "1" else (0 if s[7 - SWDIO_BIT] == "0" else "x"))
    return bits


def value_of(bits):
    return sum(b << i for i, b in enumerate(bits))


def wire_bits(trace, model, phase):
    """SWDIO at every rise of `phase`, from the trace (not the model)."""
    edges = rises_of(trace)
    phases = [ph for ph, _ in model.wire]
    return [int(trace[e]["dio"]) for e, ph in zip(edges, phases) if ph == phase]


def bits_of(value, n):
    return [(value >> i) & 1 for i in range(n)]


def kinds(model):
    return sorted({v.kind for v in model.violations})


def assert_only_driven_swd_pins(pads, tag):
    """After a run: no contention, no unknown `uio_oe`, and the design drove
    only SWCLK and SWDIO (SWDIO released during response phases)."""
    pads.assert_no_contention()
    assert pads.oe_unknown == 0, f"{tag}: uio_oe unknown on pins 0x{pads.oe_unknown:02x}"
    assert pads.oe_seen & ~SWD_MASK == 0, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen & ~SWD_MASK:02x} "
        f"outside SWCLK|SWDIO"
    )
    assert pads.oe_seen == SWD_MASK, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen:02x}; an SWD probe "
        f"drives SWCLK|SWDIO = 0x{SWD_MASK:02x}"
    )


def report(dut, tag, model):
    info = model.report()
    dut._log.info(
        f"[{tag}] connected={info['connected']} rises={info['rises']} "
        f"acks={info['acks']} trailing_idle={info['trailing_idle_low']} "
        f"high_cycles={info['swclk_high_cycles']} "
        f"low_cycles={info['swclk_low_cycles']}"
    )
    for v in model.violations[:10]:
        dut._log.error(f"[{tag}] {v}")
    return info


def mutate(text, old, new):
    assert text.count(old) == 1, f"mutation site {old!r} found {text.count(old)} times"
    return text.replace(old, new)


def mutant_words(name, text):
    return asm.assemble_text(text, source_name=f"<mutant {name}>").words


async def run_mutant(dut, name, text, model, cycles=1300):
    start_clock(dut)
    return await run_probe(dut, mutant_words(name, text), model, cycles=cycles)


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source; the program fits; the
    assembler's data-dependent-latency lint is silent; the pin-mode setup is
    the documented shape (push-pull SWCLK|SWDIO after the idle image, and
    UIO_OD never written)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    # exactly the two ACK handshake branches (one per transaction) read
    # IN-sampled data; the lint documents that case as legitimate
    assert len(program.warnings) == 2 and all(
        "BZ branches on flags set by AND" in w for w in program.warnings
    ), program.warnings
    assert len(program.words) <= 256
    assert len(program.words) == 227, (
        f"{len(program.words)} words; the ACK-branching revision is 227"
    )
    text = SRC.read_text(encoding="utf-8")
    code = re.sub(r";.*", "", text)
    assert "WCTL  UIO_OD" not in code, "an SWD probe drives push-pull; UIO_OD must never be written"
    first_dir = code.find("WCTL  UIO_DIR")
    assert first_dir != -1
    ldi = [m for m in re.finditer(r"LDI\s+R1,\s+(0x[0-9A-Fa-f]+)", code) if m.start() < first_dir]
    assert ldi and int(ldi[-1].group(1), 16) == SWD_MASK, (
        "the first WCTL UIO_DIR must write the push-pull SWCLK|SWDIO mask"
    )
    assert code.find("OUT   UIO_OUT") < first_dir, (
        "the idle image must be written before any pad is enabled (uio_out "
        "resets to 0)"
    )
    dut._log.info(f"{len(program.words)} words, 0 lint warnings")


@cocotb.test()
async def test_probe_reads_idcode_and_dp_register(dut):
    """The golden run: the model connects, decodes both request frames
    (0xA5 then 0xBD, both even-parity DP reads), answers OK twice, and the
    probe's 72 report bytes decode to ACK OK (1,0,0), the IDCODE 0x4BA00477 and its
    even parity, then ACK OK, the second value 0x12345678 and its parity."""
    start_clock(dut)
    model = SwdTarget(reads=[(ACK_OK, IDCODE), (ACK_OK, SECOND_VALUE)])
    trace, model, pads, agent = await run_probe(
        dut, committed_words(), model, cycles=1300
    )
    info = report(dut, "golden", model)
    assert_only_driven_swd_pins(pads, "golden")
    assert agent.unknown == 0, "a golden-run line read unknown"
    assert model.violations == [], f"golden: {[str(v) for v in model.violations]}"
    assert info["connected"] and info["acks"] == [ACK_OK, ACK_OK]
    assert [f.byte for f in model.requests] == [0xA5, 0xBD]
    assert all(f.ok for f in model.requests)

    # the wire, from the trace: switch and request bits bit-exact, LSB first
    assert wire_bits(trace, model, "switch") == bits_of(SWITCH_CODE, 16)
    assert wire_bits(trace, model, "request") == bits_of(0xA5, 8) + bits_of(0xBD, 8)
    # the report bytes: ACK OK, data LSB first, parity
    bits = samples_bits(response_samples(trace, model))
    assert len(bits) == 72 and "x" not in bits
    ack1, data1, par1 = bits[0:3], bits[3:35], bits[35]
    ack2, data2, par2 = bits[36:39], bits[39:71], bits[71]
    # OK is numeric 0b001 sent LSB first: 1,0,0 in time order
    assert ack1 == [1, 0, 0] and ack2 == [1, 0, 0], (ack1, ack2)
    assert value_of(data1) == IDCODE and par1 == read_value_parity(IDCODE)
    assert value_of(data2) == SECOND_VALUE and par2 == read_value_parity(SECOND_VALUE)
    # cycle figures: DR 0018's recorded counts and widths
    assert info["rises"] == EXPECTED_RISES, info["rises"]
    assert len(rises_of(trace)) == EXPECTED_RISES
    assert info["trailing_idle_low"] == 8
    for phase, want in EXPECTED_WIDTHS.items():
        got_h = info["swclk_high_cycles"].get(phase)
        got_l = info["swclk_low_cycles"].get(phase)
        assert got_h == want["high"], (phase, "high", got_h, want["high"])
        assert got_l == want["low"], (phase, "low", got_l, want["low"])
    # SWDIO direction: the probe released SWDIO at every turnaround and
    # response slot and drove it at every request bit
    edges = rises_of(trace)
    phases = [ph for ph, _ in model.wire]
    prev_ph = None
    returns = 0
    for e, ph in zip(edges, phases):
        oe_bit = (trace[e]["oe"] >> SWDIO_BIT) & 1
        if ph in ("response", "await-turnaround"):
            assert oe_bit == 0, f"SWDIO still driven at {ph} rise, edge {e}"
        elif ph == "request":
            assert oe_bit == 1, f"SWDIO not driven at request rise, edge {e}"
        elif ph == "post-response" and prev_ph == "response":
            # the return turnaround cycle after the last response bit
            returns += 1
            assert oe_bit == 0, f"SWDIO driven on the return turnaround, edge {e}"
        prev_ph = ph
    assert returns == 2, f"{returns} return-turnaround rises graded, wanted 2"
    dut._log.info(
        f"golden: 218 rises, idcode {IDCODE:#010x} + parity, "
        f"second {SECOND_VALUE:#010x} + parity, 8 trailing idle clocks"
    )


@cocotb.test()
async def test_wait_and_fault_end_the_transfer_cleanly(dut):
    """The first request (DPIDR) is answered OK. The second request (RDBUFF),
    which can legally fail, is answered WAIT (wire 0,1,0) or FAULT (0,0,1).
    With CTRL/STAT.ORUNDETECT = 0 (power-up) the target ends after the ACK
    and the turnaround: the probe reports the three ACK samples, leaves the
    return turnaround released, re-drives SWDIO low and clocks eight trailing
    idles -- no data slots, no violation, no retry."""
    for ack, wire in ((ACK_WAIT, [0, 1, 0]), (ACK_FAULT, [0, 0, 1])):
        start_clock(dut)
        model = SwdTarget(reads=[(ACK_OK, IDCODE), (ack, 0)])
        trace, model, pads, _a = await run_probe(
            dut, committed_words(), model, cycles=1300
        )
        info = report(dut, f"{ack.lower()}", model)
        assert_only_driven_swd_pins(pads, ack.lower())
        assert model.violations == [], f"{ack}: {[str(v) for v in model.violations]}"
        assert info["acks"] == [ACK_OK, ack]
        assert [f.byte for f in model.requests] == [0xA5, 0xBD]
        bits = samples_bits(response_samples(trace, model))
        assert len(bits) == 36 + 3, len(bits)
        assert bits[0:3] == [1, 0, 0]
        assert value_of(bits[3:35]) == IDCODE
        assert bits[36:39] == wire, (ack, bits[36:39])
        assert info["trailing_idle_low"] == 8
        # the return turnaround after the ACK is released, then SWDIO is
        # driven (low) for the idle clocks
        edges = rises_of(trace)
        phases = [ph for ph, _ in model.wire]
        prev_ph, returns = None, 0
        for e, ph in zip(edges, phases):
            if ph == "post-response" and prev_ph == "response":
                returns += 1
                assert (trace[e]["oe"] >> SWDIO_BIT) & 1 == 0
            prev_ph = ph
        assert returns == 2, returns
        dut._log.info(f"{ack}: ACK {wire} reported, transfer ended, no data slots")


@cocotb.test()
async def test_first_request_error_ends_before_the_second(dut):
    """An error ACK on the very first request ends the run there: one
    request, three ACK samples, eight trailing idles."""
    start_clock(dut)
    model = SwdTarget(reads=[(ACK_FAULT, 0)])
    trace, model, pads, _a = await run_probe(dut, committed_words(), model, cycles=1300)
    assert_only_driven_swd_pins(pads, "first-fault")
    assert model.violations == [], [str(v) for v in model.violations]
    assert [f.byte for f in model.requests] == [0xA5]
    assert samples_bits(response_samples(trace, model)) == [0, 0, 1]
    assert model.report()["trailing_idle_low"] == 8


@cocotb.test()
async def test_negative_error_ack_still_clocks_data_slots(dut):
    """The second transaction's ACK branch removed: after a WAIT the probe
    clocks the full 36 slots with SWDIO released, the old behaviour. The
    model reports the released line after the transfer ended."""
    text = SRC.read_text(encoding="utf-8")
    k = text.rindex("        BZ    ackerr")
    text = text[:k] + "        NOP                    ; (mutant) no ACK branch" + text[k + len("        BZ    ackerr"):]
    start_clock(dut)
    model = SwdTarget(reads=[(ACK_OK, IDCODE), (ACK_WAIT, 0)])
    _t, model, pads, _a = await run_mutant(dut, "no-ack-branch", text, model)
    assert "line-released-after-transfer" in kinds(model), kinds(model)


@cocotb.test()
async def test_negative_return_turnaround_driven(dut):
    """The probe re-drives SWDIO before the return turnaround cycle after
    the first read parity: the target is released from the line one cycle
    early. The model reports `return-turnaround-driven` and nothing else."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "; -------- turnaround after the read parity + re-drive SWDIO (4)\n",
        "; -------- turnaround after the read parity + re-drive SWDIO (4)\n"
        "        LDI   R3, 0x0C         ; (mutant) re-drive before the turnaround\n"
        "        WCTL  UIO_DIR, R3\n",
    )
    _t, model, pads, _a = await run_mutant(dut, "turn-driven", text, SwdTarget())
    assert kinds(model) == ["return-turnaround-driven"], kinds(model)


@cocotb.test()
async def test_negative_line_reset_49(dut):
    """49 SWCLK cycles of SWDIO high before the switch: one short of the 50
    the connection requires. The target stays dormant (`line-reset-short`)
    and the probe reads the pull-up through every response phase."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "LDI   R2, 50\nlr1:", "LDI   R2, 49\nlr1:")
    trace, model, pads, _a = await run_mutant(dut, "reset-49", text, SwdTarget())
    assert "line-reset-short" in kinds(model)
    assert not model.connected
    assert_only_driven_swd_pins(pads, "reset-49")
    bits = samples_bits(response_samples(trace, model))
    assert bits == [] or all(b == 1 for b in bits), (
        "a dormant target leaves SWDIO pulled up through every response slot"
    )


@cocotb.test()
async def test_negative_switch_bit_flipped(dut):
    """One switch bit flipped (both its pin images, so the wire still changes
    only while SWCLK is low -- a value error, not a timing error): the 16
    bits are not 0xE79E, the target reports `switch-sequence` and never
    connects."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "        LDI   R3, 0x08         ; bit 1 = 1\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x0C\n",
        "        LDI   R3, 0x00         ; (mutant) bit 1 = 0\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x04\n",
    )
    trace, model, pads, _a = await run_mutant(dut, "switch-bit", text, SwdTarget())
    # the flipped bit is rejected as `switch-sequence`; once the target has
    # refused to connect, the rest of the probe's schedule (second reset,
    # idle, requests) is re-read as reset attempts and can only pile up
    # `line-reset-short` fallout -- nothing else.
    got = kinds(model)
    assert "switch-sequence" in got, got
    assert set(got) <= {"switch-sequence", "line-reset-short"}, got
    assert not model.connected
    assert_only_driven_swd_pins(pads, "switch-bit")
    assert samples_bits(response_samples(trace, model)) == [], (
        "a target that never connected drives no response slots"
    )


@cocotb.test()
async def test_negative_no_turnaround_release(dut):
    """The release WCTL removed: the probe still drives SWDIO into the
    response phase. The model reports `no-release` and the pad model reports
    the two drivers fighting (contention) -- the electrical statement of the
    same defect."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "        LDI   R3, 0x04         ; direction: SWCLK only\n"
        "        WCTL  UIO_DIR, R3      ; release SWDIO for the target\n",
        "        NOP                    ; (mutant) no release: SWDIO stays driven\n"
        "        NOP                    ; (mutant)\n",
    )
    _t, model, pads, _a = await run_mutant(dut, "no-release", text, SwdTarget())
    assert "no-release" in kinds(model)
    assert pads.contention, (
        "NEGATIVE CONTROL FAILED TO FAIL: the pad model saw no contention "
        "although probe and target both drove SWDIO"
    )


@cocotb.test()
async def test_negative_wrong_request_parity(dut):
    """The second request's parity bit inverted (both its pin images, so the
    wire still changes only while SWCLK is low): the frame fails its parity
    field, the target sends no response for it, and the probe clocks the
    pull-up through that transaction (ACK 111). The first transaction is
    unaffected -- the rejection is the parity's own."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "        LDI   R3, 0x08         ; A3 = 1\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x0C\n"
        "        OUT   UIO_OUT, R3      ; rise\n"
        "        LDI   R3, 0x08         ; parity = 1\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x0C\n",
        "        LDI   R3, 0x08         ; A3 = 1\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x0C\n"
        "        OUT   UIO_OUT, R3      ; rise\n"
        "        LDI   R3, 0x00         ; (mutant) parity = 0\n"
        "        OUT   UIO_OUT, R3\n"
        "        LDI   R3, 0x04\n",
    )
    trace, model, pads, _a = await run_mutant(dut, "req-parity", text, SwdTarget())
    assert kinds(model) == ["request-parity"], kinds(model)
    assert model.connected
    assert [f.ok for f in model.requests] == [True, False]
    assert_only_driven_swd_pins(pads, "req-parity")
    bits = samples_bits(response_samples(trace, model))
    assert bits[0:3] == [1, 0, 0], "the first transaction is unaffected"
    assert bits[36:72] == [1] * 36, "a rejected request gets all pull-up bits"
    dut._log.info("mutant req-parity: first read clean, second clocks the pull-up")


@cocotb.test()
async def test_negative_short_trailing_idle(dut):
    """Three trailing idle clocks instead of eight: everything else clean,
    `trailing-idle-short` at the end -- its own reason."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "LDI   R2, 8", "LDI   R2, 3")
    _t, model, pads, _a = await run_mutant(dut, "short-tail", text, SwdTarget())
    assert kinds(model) == ["trailing-idle-short"], kinds(model)
    assert model.report()["acks"] == [ACK_OK, ACK_OK]
    assert_only_driven_swd_pins(pads, "short-tail")
    assert model.report()["trailing_idle_low"] == 3
