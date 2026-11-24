"""DUT-facing SWD probe firmware bench (multi-protocol extra credit, issues
#452 and #500; the protocol choice and the counted cost model are the dated
notes in DR 0018).

The claim: the committed program `firmware/asm/swd_probe.asm` (image
`firmware/build/swd_probe.hex`), loaded over the real serial load-phase pins
onto the real top and run by the ISA core, acts as an SWD **probe** (host) on
SWCLK = `uio[2]` and SWDIO = `uio[3]` and reads **one word of AP memory**: it
brings a target up (line reset, 0xE79E JTAG-to-SWD switch, second line reset,
idle clocks), reads the DP IDCODE (request 0xA5), writes DP SELECT (0xB1) and
the MEM-AP's TAR (0x8B), issues the *posted* AP DRW read (0x9F) and fetches
the addressed word through DP RDBUFF (0xBD) -- five transactions, two of them
probe-driven writes with a 33-bit data phase. It reports every response
sample on `uo_out` as it is taken: the masked SWDIO byte (0x08 or 0x00), in
transaction order. The target is the independent model side
(`verification/reference_models/swd.py`, written from Arm's ADIv5 description
and pyOCD's observable connection shape alone, constants marked "confirm" as
DR 0018 records). The bench never tells the model what the waveform looks
like; the model drives SWDIO back at the probe with zero-delay,
aggressive-but-legal timing (IHI 0031 B4.3.1), exactly the timing that
catches a probe that samples after the rise instead of before it.

What is graded, and by whom
---------------------------
1. **The lines.** The pad model (`verification/uio_pads.py`) resolves
   SWCLK/SWDIO from the design's own `uio_out`/`uio_oe` and the target's
   driver, with a pull-up on SWDIO (ADIv5 requires it) and SWCLK pulled low
   so it rests defined while the probe pad is off. The six other `uio` lines
   are tied low. A probe that keeps SWDIO driven into a response phase, or
   releases it into a write-data phase, is reported by the model; contention
   is reported by the pad model.
2. **The protocol.** The model grades the line resets, the switch, the idle
   clocks, each request frame, the turnarounds, the 33-bit write data (value
   and even parity), SWDIO ownership, and the trailing idle; it decodes the
   requests against its DP and MEM-AP (`MemAp`): SELECT and TAR must be
   written before DRW is read, a DRW read is *posted* (it returns the read
   buffer's previous value, deliberately different from the addressed word),
   and only a DP RDBUFF read returns the addressed word.
3. **The reported result.** From the retired `uo_out` bytes: the DRW read's
   data (the stale buffer value), then the RDBUFF read's data (the fixture
   word at TAR), each with its ACK and even parity, byte for byte what the
   model drove.
4. **The cycle figures.** Image size (245 stored words of 256), rising-edge
   count, and the SWCLK high/low widths per phase are measured and held
   against the figures `firmware/README.md` records.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Mutant programs, each assembled in memory from the committed source with one
defect, run on the same DUT and target and must be rejected for the defect's
own reason: a 49-clock first line reset (`line-reset-short`), a flipped
switch bit (`switch-sequence`), a missing turnaround release (`no-release` and
pad contention), a wrong request parity bit (`request-parity`), a flipped
SELECT or TAR write-data parity bit (`write-parity`, the write discarded so
the later accesses fail for it), a broken ACK-to-write-data handoff
(`write-data-not-driven`), a 3-clock trailing idle (`trailing-idle-short`),
the ACK branch removed, and SWDIO driven on the return turnaround. Model-
configured runs answer WAIT or FAULT on each of the five transactions
(ORUNDETECT = 0: no data phase): a rejected write changes no model state and
no memory word is ever read.

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
    ACK_BAD,
    ACK_FAULT,
    ACK_NONE,
    ACK_OK,
    ACK_WAIT,
    REQUEST_BITS,
    RESET_MIN_CYCLES,
    RESPONSE_BITS,
    SWITCH_CODE,
    WRITE_BITS,
    MemAp,
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

#: The committed figures for this program (core cycles; the measured values
#: `firmware/README.md` records).
EXPECTED_WORDS = 256
#: clock edges per run: the committed run is well under this; the slack is HALT
CYCLES = 3200
EXPECTED_RISES = 356
#: the core edge (counted from the run-phase entry) of the last SWCLK fall
EXPECTED_LAST_FALL = 2615
#: per-phase SWCLK high/low widths in cycles, as measured on the pads
#: (boundary transitions included).
EXPECTED_WIDTHS = {
    "reset1": {"high": (1.0, 1.0), "low": (3.0, 11.0)},
    "switch": {"high": (7.0, 7.0), "low": (2.0, 2.0)},
    "reset2": {"high": (1.0, 1.0), "low": (2.0, 6.0)},
    "idle": {"high": (2.0, 2.0), "low": (2.0, 11.0)},
    "request": {"high": (7.0, 7.0), "low": (2.0, 2.0)},
    "response": {"high": (1.0, 1.0), "low": (4.0, 7.0)},
    "write-data": {"high": (1.0, 7.0), "low": (2.0, 2.0)},
}

#: response slots per read transaction (3 ACK + 32 data + 1 parity; DR 0018)
RESPONSE_SLOTS = RESPONSE_BITS
#: request frame bits on the wire (DR 0018)
REQUEST_FRAME_BITS = REQUEST_BITS
#: write data bits on the wire (32 + even parity)
WRITE_FRAME_BITS = WRITE_BITS

#: the five transactions, in order: request byte, name, is a write
SEQUENCE = [
    (0xA5, "DPIDR read", False),
    (0xB1, "DP SELECT write", True),
    (0x8B, "AP TAR write", True),
    (0x9F, "AP DRW read", False),
    (0xBD, "DP RDBUFF read", False),
]
REQUEST_BYTES = [b for b, _n, _w in SEQUENCE]

IDCODE = 0x4BA00477
#: What the probe writes (the firmware's table; the bench holds the wire to it)
SELECT_VALUE = 0x00000000
TAR_VALUE = 0x20000004
#: The modeled memory: the word at TAR is the answer; the neighbours differ
MEM = {0x20000000: 0x11111111, 0x20000004: 0xCAFEF00D, 0x20000008: 0x55555555}
WORD = MEM[TAR_VALUE]
POSTED_INITIAL = 0xA5A5C3C3


def ap_target(**kw):
    """A fresh MEM-AP target. `kw` goes to `SwdTarget` (e.g. `acks=`)."""
    return SwdTarget(ap=MemAp(idcode=IDCODE, mem=MEM, posted_initial=POSTED_INITIAL), **kw)


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
    """The retired report byte at each response-slot rise, all transactions
    concatenated (see `transactions`)."""
    out = []
    for t in transactions(trace, model):
        out.extend(t["samples"])
    return out


def transactions(trace, model):
    """Split the run into its transactions, from the model's wire phases and
    the DUT trace. Each entry: `request` (the model's decoded byte), `samples`
    (the `uo_out` bytes at the response slots), `wdata` (SWDIO at each
    write-data rise, from the trace). After the request and turnaround, the
    model labels 36 response slots for an OK read and three for an OK write or
    a WAIT / FAULT. A rejected frame leaves SWDIO pulled high, so the probe
    takes its full-length path (36 read slots, 3 write slots)."""
    edges = rises_of(trace)
    phases = [ph for ph, _ in model.wire]
    assert len(edges) == len(phases), (len(edges), len(phases))
    out = []
    i = 0
    k = 0
    while i < len(phases):
        if phases[i] == "request":
            run = 1
            while i + run < len(phases) and phases[i + run] == "request":
                run += 1
            if run >= REQUEST_FRAME_BITS:
                req = model.requests[k] if k < len(model.requests) else None
                k += 1
                start = i + run + 1  # skip the turnaround rise
                if start < len(phases) and phases[start] == "response":
                    n = 0
                    while start + n < len(phases) and phases[start + n] == "response":
                        n += 1
                else:
                    n = 3 if (req is not None and req.rn_w == 0) else RESPONSE_SLOTS
                span = phases[start : start + n]
                assert len(span) == n, "run ended inside a response"
                samples = [trace[edges[j]]["uo"] for j in range(start, start + n)]
                j = start + n
                wdata = []
                while j < len(phases) and phases[j] in ("post-response",):
                    j += 1
                    break
                while j < len(phases) and phases[j] == "write-data":
                    wdata.append(int(trace[edges[j]]["dio"]))
                    j += 1
                out.append({"request": req.byte if req else None, "samples": samples,
                            "wdata": wdata})
                i = j
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


async def run_mutant(dut, name, text, model, cycles=CYCLES):
    start_clock(dut)
    return await run_probe(dut, mutant_words(name, text), model, cycles=cycles)


# =======================================================================
# Tests
# =======================================================================

def mutate_nth(text, old, new, n):
    """Replace the `n`th (0-based) occurrence of `old`."""
    idx = -1
    for _ in range(n + 1):
        idx = text.index(old, idx + 1)
    return text[:idx] + new + text[idx + len(old):]


def read_fields(samples):
    """(ack bits, value, parity bit) of a read transaction's 36 report bytes."""
    bits = samples_bits(samples)
    assert len(bits) == RESPONSE_SLOTS and "x" not in bits, bits
    return bits[0:3], value_of(bits[3:35]), bits[35]


def write_payload(value):
    return bits_of(value, 32) + [read_value_parity(value)]


def read_log(model):
    return [e for e in model.ap.log if e[0] == "read"]


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source; the program fits; the
    assembler's data-dependent-latency lint reports exactly the documented
    branches; the pin-mode setup is the documented shape (push-pull
    SWCLK|SWDIO after the idle image, and UIO_OD never written)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    # The lint flags nine branches. Three read the target's ACK from the pin
    # (the sanctioned handshake branches: BZ ackerr after the first ACK bit,
    # BNZ ackbad after each of the other two). The other six branch on a table
    # byte or on a count that was read from the table (the program's own
    # constant data, the NEC IR program's shape): the BNZ tail / BNZ txn words,
    # BZ ret (a write has no target data), BNZ txq, and the SUB loop counters.
    assert len(program.warnings) == 9, program.warnings
    assert sum("BZ branches on flags set by AND" in w for w in program.warnings) == 2
    assert len(program.words) <= 256
    assert len(program.words) == EXPECTED_WORDS, (
        f"{len(program.words)} words; the table-driven AP-read image is "
        f"{EXPECTED_WORDS}"
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
    dut._log.info(f"{len(program.words)} words, {len(program.warnings)} lint warnings")


@cocotb.test()
async def test_probe_reads_one_ap_memory_word(dut):
    """The golden run: connect, read IDCODE, write DP SELECT and AP TAR, issue
    the posted AP DRW read, and fetch the addressed word through DP RDBUFF.
    The independent model decodes the five requests against its DP and
    MEM-AP; the result is graded from the probe's own report bytes."""
    start_clock(dut)
    model = ap_target()
    trace, model, pads, agent = await run_probe(dut, committed_words(), model, cycles=CYCLES)
    info = report(dut, "golden", model)
    assert_only_driven_swd_pins(pads, "golden")
    assert agent.unknown == 0, "a golden-run line read unknown"
    assert model.violations == [], f"golden: {[str(v) for v in model.violations]}"
    assert info["connected"] and info["acks"] == [ACK_OK] * 5
    assert [f.byte for f in model.requests] == REQUEST_BYTES
    assert all(f.ok for f in model.requests)

    # what the model's DP and MEM-AP saw, in transaction order
    assert model.ap.log == [
        ("read", "DPIDR", IDCODE),
        ("write", "SELECT", SELECT_VALUE),
        ("write", "TAR", TAR_VALUE),
        ("read", "DRW", POSTED_INITIAL),
        ("read", "RDBUFF", WORD),
    ], model.ap.log
    assert model.ap.select == SELECT_VALUE and model.ap.tar == TAR_VALUE

    # the wire, from the trace (not the model): the switch and every request
    # bit-exact, LSB first
    assert wire_bits(trace, model, "switch") == bits_of(SWITCH_CODE, 16)
    assert wire_bits(trace, model, "request") == sum((bits_of(b, 8) for b in REQUEST_BYTES), [])
    txs = transactions(trace, model)
    assert [t["request"] for t in txs] == REQUEST_BYTES
    # the write payloads, from the pads: 32 data bits LSB first and even parity
    assert txs[1]["wdata"] == write_payload(SELECT_VALUE), txs[1]["wdata"]
    assert txs[2]["wdata"] == write_payload(TAR_VALUE), txs[2]["wdata"]
    assert len(txs[1]["wdata"]) == len(txs[2]["wdata"]) == WRITE_FRAME_BITS
    assert txs[0]["wdata"] == txs[3]["wdata"] == txs[4]["wdata"] == []

    # the report bytes: every ACK is OK (1,0,0), the writes carry no data
    for k in (1, 2):
        assert samples_bits(txs[k]["samples"]) == [1, 0, 0], (k, txs[k]["samples"])
    ack, idcode, par = read_fields(txs[0]["samples"])
    assert ack == [1, 0, 0] and idcode == IDCODE and par == read_value_parity(IDCODE)
    # the posted read: its data is the read buffer's PREVIOUS value ...
    ack, posted, par = read_fields(txs[3]["samples"])
    assert ack == [1, 0, 0] and par == read_value_parity(posted)
    assert posted == POSTED_INITIAL and posted != WORD, (
        "the DRW read must return the stale buffer, not the addressed word"
    )
    # ... and the addressed word comes through RDBUFF
    ack, word, par = read_fields(txs[4]["samples"])
    assert ack == [1, 0, 0] and par == read_value_parity(word)
    assert word == WORD, f"RDBUFF reported {word:#010x}, wanted {WORD:#010x}"

    # cycle figures: stored words, rising edges, per-phase widths
    assert info["rises"] == EXPECTED_RISES, info["rises"]
    assert len(rises_of(trace)) == EXPECTED_RISES
    assert info["trailing_idle_low"] == 8
    last_fall = max(i for i, row in enumerate(trace[1:], start=1)
                    if row["clk"] == "0" and trace[i - 1]["clk"] == "1")
    assert last_fall == EXPECTED_LAST_FALL, last_fall
    for phase, want in EXPECTED_WIDTHS.items():
        got_h = info["swclk_high_cycles"].get(phase)
        got_l = info["swclk_low_cycles"].get(phase)
        assert got_h == want["high"], (phase, "high", got_h, want["high"])
        assert got_l == want["low"], (phase, "low", got_l, want["low"])

    # SWDIO ownership at the pads: driven for every request and write-data
    # bit; released for every turnaround and response slot, including the
    # return turnaround cycle after each response
    edges = rises_of(trace)
    phases = [ph for ph, _ in model.wire]
    prev_ph, returns, wdata_rises = None, 0, 0
    for e, ph in zip(edges, phases):
        oe_bit = (trace[e]["oe"] >> SWDIO_BIT) & 1
        if ph in ("response", "await-turnaround"):
            assert oe_bit == 0, f"SWDIO still driven at {ph} rise, edge {e}"
        elif ph in ("request", "write-data"):
            assert oe_bit == 1, f"SWDIO not driven at {ph} rise, edge {e}"
            wdata_rises += ph == "write-data"
        elif ph == "post-response" and prev_ph == "response":
            returns += 1
            assert oe_bit == 0, f"SWDIO driven on the return turnaround, edge {e}"
        prev_ph = ph
    assert returns == 5, f"{returns} return-turnaround rises graded, wanted 5"
    assert wdata_rises == 2 * WRITE_FRAME_BITS
    dut._log.info(
        f"golden: {EXPECTED_RISES} rises, word {word:#010x} via RDBUFF after the "
        f"posted read returned {posted:#010x}, SELECT {SELECT_VALUE:#010x} and "
        f"TAR {TAR_VALUE:#010x} written, 8 trailing idle clocks"
    )


@cocotb.test()
async def test_wait_and_fault_end_the_transfer_cleanly(dut):
    """Any one of the five transactions is answered WAIT (wire 0,1,0) or FAULT
    (0,0,1). With CTRL/STAT.ORUNDETECT = 0 the target ends after the ACK and
    the turnaround: the probe reports the three ACK samples, leaves the return
    turnaround released, re-drives SWDIO low and clocks eight trailing idles --
    no data phase, no retry, no violation. A rejected write changes no model
    state, and once any transaction is rejected no later memory read happens:
    the addressed word never appears on `uo_out`."""
    wires = {ACK_WAIT: [0, 1, 0], ACK_FAULT: [0, 0, 1]}
    for n in range(1, 6):
        for ack, wire in wires.items():
            start_clock(dut)
            model = ap_target(acks={n: ack})
            trace, model, pads, _a = await run_probe(
                dut, committed_words(), model, cycles=CYCLES
            )
            tag = f"txn{n}-{ack.lower()}"
            info = report(dut, tag, model)
            assert_only_driven_swd_pins(pads, tag)
            assert model.violations == [], f"{tag}: {[str(v) for v in model.violations]}"
            assert info["acks"] == [ACK_OK] * (n - 1) + [ack], info["acks"]
            assert [f.byte for f in model.requests] == REQUEST_BYTES[:n]
            txs = transactions(trace, model)
            assert len(txs) == n
            assert samples_bits(txs[-1]["samples"]) == wire, (tag, txs[-1]["samples"])
            assert txs[-1]["wdata"] == [], "a rejected write must get no data phase"
            assert info["trailing_idle_low"] == 8, tag
            # state: only what was accepted before the rejection
            kinds_done = [(k, r) for k, r, _v in model.ap.log]
            want = [("read", "DPIDR"), ("write", "SELECT"), ("write", "TAR"),
                    ("read", "DRW"), ("read", "RDBUFF")][: n - 1]
            assert kinds_done == want, (tag, kinds_done)
            if n <= 2:
                assert model.ap.select is None, f"{tag}: SELECT changed by a rejected write"
            if n <= 3:
                assert model.ap.tar is None, f"{tag}: TAR changed by a rejected write"
            for t in txs:
                if len(t["samples"]) == RESPONSE_SLOTS:
                    assert read_fields(t["samples"])[1] != WORD, (
                        f"{tag}: the memory word was read after a rejection")
            # returns: one per transaction that got a response, all released
            edges = rises_of(trace)
            phases = [ph for ph, _ in model.wire]
            prev_ph, returns = None, 0
            for e, ph in zip(edges, phases):
                if ph == "post-response" and prev_ph == "response":
                    returns += 1
                    assert (trace[e]["oe"] >> SWDIO_BIT) & 1 == 0
                prev_ph = ph
            assert returns == n, (tag, returns)
            dut._log.info(f"{tag}: ACK {wire} reported, transfer ended")


@cocotb.test()
async def test_bad_ack_keeps_swdio_released_and_ends_the_run(dut):
    """A target that does not answer a write (SWDIO left to the pull-up: ACK
    1,1,1) or answers 1,0,1 -- neither is an OK (1,0,0) -- on DP SELECT or on
    AP TAR. The probe must not drive the write data: SWDIO stays released
    through the possible 33-bit data phase after the turnaround, no further
    request is issued, and the run ends with the eight trailing idle clocks.
    Nothing is written to the model."""
    for n, name in ((2, "DP SELECT"), (3, "AP TAR")):
        for ack in (ACK_NONE, ACK_BAD):
            start_clock(dut)
            model = ap_target(acks={n: ack})
            trace, model, pads, _a = await run_probe(
                dut, committed_words(), model, cycles=CYCLES)
            tag = f"txn{n}-{ack.lower()}"
            info = report(dut, tag, model)
            assert_only_driven_swd_pins(pads, tag)
            assert model.violations == [], f"{tag}: {[str(v) for v in model.violations]}"
            assert info["acks"] == [ACK_OK] * (n - 1) + [ack], info["acks"]
            assert [f.byte for f in model.requests] == REQUEST_BYTES[:n], (
                f"{tag}: the probe issued a request after the bad ACK")
            assert info["trailing_idle_low"] == 8, tag
            assert model.ap.select is None or n == 3
            assert model.ap.tar is None, f"{tag}: TAR written after a bad ACK"
            edges = rises_of(trace)
            phases = [ph for ph, _ in model.wire]
            backoff = [e for e, ph in zip(edges, phases) if ph == "ack-backoff"]
            assert len(backoff) == WRITE_FRAME_BITS, (tag, len(backoff))
            for e in backoff:
                assert (trace[e]["oe"] >> SWDIO_BIT) & 1 == 0, (
                    f"{tag}: SWDIO driven in the possible data phase, edge {e}")
            # only the accepted SELECT's data phase is ever driven
            assert phases.count("write-data") == (WRITE_FRAME_BITS if n == 3 else 0), tag
            dut._log.info(f"{tag}: SWDIO released for the data phase, run ended")


@cocotb.test()
async def test_negative_bad_ack_accepted_as_ok(dut):
    """The second and third ACK bits not checked (the ACK loop's branch
    removed): a silent target's pull-up (1,1,1) passes as OK and the probe
    drives the SELECT write data into the line nobody acknowledged. The
    model reports `driven-after-bad-ack`."""
    text = SRC.read_text(encoding="utf-8")
    k = text.index("        BNZ   ackbad")
    text = text[:k] + "        NOP                    ; (mutant) ACK slots 1 and 2 unchecked" \
        + text[k + len("        BNZ   ackbad"):]
    start_clock(dut)
    model = ap_target(acks={2: ACK_NONE})
    _t, model, pads, _a = await run_mutant(dut, "bad-ack-accepted", text, model)
    assert "driven-after-bad-ack" in kinds(model), kinds(model)


@cocotb.test()
async def test_negative_error_ack_still_clocks_data_slots(dut):
    """The ACK branch removed: after a WAIT to the last read the probe clocks
    the full 36 slots with SWDIO released, the old behaviour. The model
    reports the released line after the transfer ended."""
    text = SRC.read_text(encoding="utf-8")
    k = text.rindex("        BZ    ackerr")
    text = text[:k] + "        NOP                    ; (mutant) no ACK branch" + text[k + len("        BZ    ackerr"):]
    start_clock(dut)
    model = ap_target(acks={5: ACK_WAIT})
    _t, model, pads, _a = await run_mutant(dut, "no-ack-branch", text, model)
    assert "line-released-after-transfer" in kinds(model), kinds(model)


@cocotb.test()
async def test_negative_return_turnaround_driven(dut):
    """The probe re-drives SWDIO before the return turnaround cycle after each
    response: the target is released from the line one cycle early. The model
    reports `return-turnaround-driven` and nothing else."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "        OUT   UIO_OUT, R1      ; the return turnaround cycle (rise)\n"
        "        OUT   UIO_OUT, R0      ; fall\n"
        "        LDI   R3, 0x0C\n"
        "        WCTL  UIO_DIR, R3      ; re-drive SWDIO push-pull\n"
        "\n; ---- R2 = 33 after a write",
        "        LDI   R3, 0x0C         ; (mutant) re-drive before the turnaround\n"
        "        WCTL  UIO_DIR, R3\n"
        "        OUT   UIO_OUT, R1      ; the return turnaround cycle (rise)\n"
        "        OUT   UIO_OUT, R0      ; fall\n"
        "\n; ---- R2 = 33 after a write",
    )
    _t, model, pads, _a = await run_mutant(dut, "turn-driven", text, ap_target())
    assert kinds(model) == ["return-turnaround-driven"], kinds(model)


@cocotb.test()
async def test_negative_line_reset_49(dut):
    """49 SWCLK cycles of SWDIO high before the switch: one short of the 50
    the connection requires. The target stays dormant (`line-reset-short`)
    and the probe reads the pull-up through every response phase."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "        LDI   R2, 50\n\n; ------------------------- line reset",
                  "        LDI   R2, 49\n\n; ------------------------- line reset")
    trace, model, pads, _a = await run_mutant(dut, "reset-49", text, ap_target())
    assert "line-reset-short" in kinds(model)
    assert not model.connected
    assert_only_driven_swd_pins(pads, "reset-49")
    bits = samples_bits(response_samples(trace, model))
    assert bits == [] or all(b == 1 for b in bits), (
        "a dormant target leaves SWDIO pulled up through every response slot"
    )


@cocotb.test()
async def test_negative_switch_bit_flipped(dut):
    """One switch bit flipped (its table entry: the wire still changes only
    while SWCLK is low -- a value error, not a timing error): the 16 bits are
    not 0xE79E, the target reports `switch-sequence` and never connects."""
    text = mutate(
        SRC.read_text(encoding="utf-8"),
        "        LDI   R2, 0x0C         ; switch bit 1 = 1  (word 0x180C)\n",
        "        LDI   R0, 0x04         ; (mutant) switch bit 1 = 0\n",
    )
    trace, model, pads, _a = await run_mutant(dut, "switch-bit", text, ap_target())
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
    _t, model, pads, _a = await run_mutant(dut, "no-release", text, ap_target())
    assert "no-release" in kinds(model)
    assert pads.contention, (
        "NEGATIVE CONTROL FAILED TO FAIL: the pad model saw no contention "
        "although probe and target both drove SWDIO"
    )


@cocotb.test()
async def test_negative_wrong_request_parity(dut):
    """The last request's parity bit inverted (its table entry: the wire still
    changes only while SWCLK is low): the frame fails its parity field, the
    target sends no response for it, and the probe clocks the pull-up through
    that transaction (ACK 111). The four earlier transactions are
    unaffected -- the rejection is the parity's own."""
    text = SRC.read_text(encoding="utf-8")
    old = "        LDI   R2, 0x0C         ; request bit 5 = 1  (word 0x180C)\n"
    new = "        LDI   R0, 0x04         ; (mutant) parity = 0\n"
    text = mutate_nth(text, old, new, text.count(old) - 1)
    trace, model, pads, _a = await run_mutant(dut, "req-parity", text, ap_target())
    assert kinds(model) == ["request-parity"], kinds(model)
    assert model.connected
    assert [f.ok for f in model.requests] == [True] * 4 + [False]
    assert_only_driven_swd_pins(pads, "req-parity")
    txs = transactions(trace, model)
    assert len(txs) == 5
    assert samples_bits(txs[3]["samples"])[0:3] == [1, 0, 0], "the DRW read is unaffected"
    assert samples_bits(txs[4]["samples"]) == [1] * 36, "a rejected request gets all pull-up bits"


@cocotb.test()
async def test_negative_write_parity_flipped(dut):
    """One write's parity bit inverted (its table entry), SELECT's in one run
    and TAR's in the other: the model reports `write-parity` and discards
    that write, so the register it carried keeps no value and the later
    accesses fail for exactly that reason (`ap-not-selected` after SELECT,
    `tar-unset` after TAR). No memory word is ever returned."""
    old = "        LDI   R0, 0x04         ; data parity = 0  (word 0x1004)\n"
    new = "        LDI   R2, 0x0C         ; (mutant) data parity = 1\n"
    base = SRC.read_text(encoding="utf-8")
    for which, name, follow in ((0, "SELECT", "ap-not-selected"), (1, "TAR", "tar-unset")):
        text = mutate_nth(base, old, new, which)
        start_clock(dut)
        trace, model, pads, _a = await run_mutant(
            dut, f"write-parity-{name}", text, ap_target())
        got = kinds(model)
        assert got == sorted(["write-parity", follow]), (name, got)
        assert model.violations[0].kind == "write-parity", [str(v) for v in model.violations]
        assert_only_driven_swd_pins(pads, f"write-parity-{name}")
        if which == 0:
            assert model.ap.select is None
        else:
            assert model.ap.tar is None
        txs = transactions(trace, model)
        _ack, last, _par = read_fields(txs[4]["samples"])
        assert last != WORD, "a discarded write must not produce the memory word"


@cocotb.test()
async def test_negative_write_ack_to_data_handoff(dut):
    """The ACK-to-write-data handoff broken on TAR: one extra response slot is
    clocked after the three ACK bits, so the probe's turnaround rise lands
    where the first write-data bit belongs and the data phase starts out of
    step with the target. The model reports `write-data-not-driven`; TAR is
    never written and no memory word is returned."""
    base = SRC.read_text(encoding="utf-8")
    k = base.index("; ---- AP TAR write")
    old = "        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit\n"
    new = "        LDI   R0, 3            ; (mutant) one slot too many\n"
    text = base[:k] + mutate_nth(base[k:], old, new, 0)
    trace, model, pads, _a = await run_mutant(dut, "handoff", text, ap_target())
    got = kinds(model)
    assert "write-data-not-driven" in got, got
    assert model.ap.tar != TAR_VALUE, "the misaligned write must not land"
    txs = transactions(trace, model)
    assert all(WORD not in [read_fields(t["samples"])[1]] for t in txs
               if len(t["samples"]) == RESPONSE_SLOTS and samples_bits(t["samples"])[0:3] == [1, 0, 0])


@cocotb.test()
async def test_negative_short_trailing_idle(dut):
    """Three trailing idle clocks instead of eight: everything else clean,
    `trailing-idle-short` at the end -- its own reason."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "        LDI   R2, 8\n        LDI   R3, 1\nidle:",
                  "        LDI   R2, 3\n        LDI   R3, 1\nidle:")
    _t, model, pads, _a = await run_mutant(dut, "short-tail", text, ap_target())
    assert kinds(model) == ["trailing-idle-short"], kinds(model)
    assert model.report()["acks"] == [ACK_OK] * 5
    assert_only_driven_swd_pins(pads, "short-tail")
    assert model.report()["trailing_idle_low"] == 3
