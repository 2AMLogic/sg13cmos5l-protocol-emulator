"""cocotb lockstep co-simulation of the core against the independent ISA
reference simulator (issue #152; verification-plan section 4.1).

`reference_models/isa.py` (a table-driven ISS written from DR 0001 and
DR 0012, importing nothing from `rtl/`) executes the same seeded random
program that the real design runs, and this bench compares them on
EVERY clock edge of the run phase:

    pc, R0..R3, Z, C, halted      via hierarchy, `dut.u_core.*` (RTL only)
    uo_out, uio_out, uio_oe       at the pins

plus the clock-edge count (the ISS emits one row per edge, including every
stall edge of `WAIT n` = n+1 edges, every two-cycle control access and the
idle edges after `HALT`, which must hold).  A mismatch prints
`seed / program index / edge / field / both values`, plus the instruction
the ISS was executing; `ISA_LOCKSTEP_SEED=<s> ISA_LOCKSTEP_ONLY=<i>[,<j>]`
re-runs exactly those programs.

Scope (stated, not implied)
---------------------------
* Execution entry: programs are loaded over the REAL serial load phase and
  run from program memory (`serial_loaded = 1`, `fetch_rom = 0`), like
  `test_control_space.py`.  Boot-ROM fetch, warm start and the SPI boot
  path (DR 0013 layer 2) are OUT OF SCOPE here: `test_boot_rom.py` and
  `test_boot_spi.py` own them.
* RTL only.  The compare reads internal state (`flag_c` is write-only state
  that synthesis may drop; flop names are flattened), so a gate-level
  lockstep is deferred, not built.  Under `GATES=yes` this bench skips.
* The instruction set is exactly DR 0001's 16 opcodes plus DR 0012's
  control space as implemented today.  The ISS opcode / control tables are
  data: a future DR that adds an encoding is a table row plus a record, and
  this bench failing on new RTL behaviour is the signal that the table was
  not updated.
* The ISS is not a copy of the RTL.  Where DR 0001 is silent it names the
  choice (`isa.OPEN_DETAILS`).  The SUB `C` polarity is such a case: the ISS
  carries the RTL's documented borrow convention as an explicit pin, and a
  `C` mismatch after a SUB is reported as "OPEN DETAIL: SUB C polarity (an
  RTL pin, DR 0001 is silent)", separately from a spec disagreement; the
  pin itself is also checked in `test_sub_carry_polarity_pin`.  Nothing in
  the spec is relaxed to make a mismatch pass.

Coverage is a counted gate: `test_coverage_gate_and_generator` runs the ISS
over the committed seed set and fails if any bucket (every opcode >=
`min_retire` retires; carry/borrow/zero; both SHF directions and shifted-out
bits; branches taken and not; WAIT 0/1/mid/255; every IN/OUT port including
the reserved no-ops; every control index read and written; unassigned,
read-only and write-only indices; `WCTL RUN`) is under its minimum.  The
same test cross-checks every generated program three ways: ISS cost per
retired instruction vs the DR 0003 assembler's static cycle count, and a
straight-line program's assembler `total_cycles` vs the ISS's span.  The
RTL leg of that three-way check is the per-edge compare below (the RTL
trace has the ISS's length, pc for pc).

A program that exceeds its static cap is a generator bug and fails the
bench; it is never a pass.
"""

import hashlib
import json
import os
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

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "verification"))
from reference_models import isa  # noqa: E402
import isa_lockstep_gen as gen  # noqa: E402

CLK_PERIOD_NS = 10
GATE_LEVEL = os.environ.get("GATES") == "yes"

#: Mirrored into `request-isa-lockstep.json` (`options.random_seed` and
#: `options.isa_lockstep`); `test_recorded_parameters_match_request` asserts
#: they agree, so the request is the record of what ran.
RECORDED_SEED = 20261010
PROGRAMS = 400
MIN_RETIRE = 200
MIN_BUCKET = 10

_REQUEST = REPO_ROOT / "verification" / "request-isa-lockstep.json"
SEED = int(os.environ.get("ISA_LOCKSTEP_SEED", RECORDED_SEED))
ONLY = [int(x) for x in os.environ.get("ISA_LOCKSTEP_ONLY", "").split(",") if x.strip()]

OPEN_DETAIL_C = ("OPEN DETAIL: SUB C polarity -- an RTL pin; DR 0001 says only 'sets Z, C' "
                 "(see isa.OPEN_DETAILS['sub-c-polarity'])")


def programs():
    progs = gen.generate(SEED, PROGRAMS)
    return [p for p in progs if not ONLY or p.index in ONLY]


def iss_run(prog):
    return isa.run(prog.image, prog.inputs, prog.max_edges, gen.IDLE_AFTER_HALT)


# ---------------------------------------------------------------------------
# DUT plumbing
# ---------------------------------------------------------------------------
async def load_image(dut, words):
    """Reset with MODE high, shift `words` in MSB-first on ui_in[0], drop
    MODE.  Returns right after the MODE-drop edge (edge 0)."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge
    for word in words:
        for bit in range(15, -1, -1):
            dut.ui_in.value = 0x80 | ((word >> bit) & 1)
            await RisingEdge(dut.clk)
    dut.ui_in.value = 0x00  # MODE drop
    await RisingEdge(dut.clk)  # edge 0


async def sample(dut):
    """State after the edge just taken, as an isa.Row-shaped tuple."""
    await ReadOnly()
    c = dut.u_core
    row = isa.Row(
        pc=int(c.pc.value),
        regs=tuple(int(c.regs[i].value) for i in range(4)),
        z=int(c.flag_z.value),
        c=int(c.flag_c.value),
        halted=int(c.halted.value),
        uo_out=int(dut.uo_out.value),
        uio_out=int(dut.uio_out.value),
        uio_oe=int(dut.uio_oe.value),
    )
    await Timer(1, unit="ns")
    return row


def drive(dut, pins):
    dut.ui_in.value, dut.uio_in.value = pins


def diff(rtl, iss):
    return [f for f in isa.ROW_FIELDS if getattr(rtl, f) != getattr(iss, f)]


def fmt(field, v):
    if field == "regs":
        return "[" + ", ".join(f"{x:#04x}" for x in v) + "]"
    if field in ("pc", "uo_out", "uio_out", "uio_oe"):
        return f"{v:#04x}"
    return str(v)


async def lockstep(dut, prog, digest):
    """Run `prog` on the DUT against its ISS trace.  Returns the number of
    edges compared; raises AssertionError on the first mismatch."""
    rows, machine = iss_run(prog)
    await load_image(dut, prog.image)
    for edge in range(0, len(rows)):
        if edge:
            await RisingEdge(dut.clk)
        rtl = await sample(dut)
        iss = rows[edge]
        digest.update(repr((prog.index, edge, rtl)).encode())
        bad = diff(rtl, iss)
        if bad:
            ctx = rows[edge - 1] if edge else iss
            ins = machine.pm.get(ctx.pc)
            doing = f"{isa.disasm(ins)} @pc={ctx.pc:#04x}" if ins is not None else "n/a"
            lines = [f"ISA LOCKSTEP MISMATCH seed={SEED} program={prog.index} ({prog.name}) "
                     f"edge={edge}   [replay: ISA_LOCKSTEP_SEED={SEED} ISA_LOCKSTEP_ONLY={prog.index}]",
                     f"  ISS was executing (previous row): {doing}"]
            for f in bad:
                lines.append(f"  field {f}: rtl={fmt(f, getattr(rtl, f))} iss={fmt(f, getattr(iss, f))}")
            if "c" in bad and machine.c_src_log[edge] == "sub":
                lines.append("  " + OPEN_DETAIL_C)
            raise AssertionError("\n".join(lines))
        if edge < len(rows) - 1:
            drive(dut, prog.inputs(edge + 1))  # pins present on the next edge
    return len(rows)


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def skip_if_gates(dut):
    if GATE_LEVEL:
        dut._log.warning("GATES=yes: lockstep reads RTL hierarchy; skipped (gate-level lockstep is deferred)")
        return True
    return False


# ---------------------------------------------------------------------------
@cocotb.test()
async def test_recorded_parameters_match_request(dut):
    """The seed and the gate's thresholds are recorded in the request, not
    just in source."""
    opts = json.loads(_REQUEST.read_text())["options"]
    want = {"programs": PROGRAMS, "min_retire": MIN_RETIRE, "min_bucket": MIN_BUCKET}
    assert opts["random_seed"] == RECORDED_SEED, (opts["random_seed"], RECORDED_SEED)
    assert opts["isa_lockstep"] == want, (opts["isa_lockstep"], want)
    if SEED != RECORDED_SEED or ONLY:
        dut._log.warning(f"REPLAY/OVERRIDE: seed={SEED} only={ONLY or 'all'} (recorded seed {RECORDED_SEED})")
    dut._log.info(f"seed={SEED} programs={PROGRAMS} min_retire={MIN_RETIRE} min_bucket={MIN_BUCKET}")


@cocotb.test()
async def test_coverage_gate_and_generator(dut):
    """ISS-side gate over the whole committed seed set: every program
    terminates within its static cap, ISS / assembler cycle counts agree,
    and no coverage bucket is under its minimum.  Always the full set, so a
    replay of one program cannot weaken it."""
    events, total_edges, problems = [], 0, []
    for prog in gen.generate(SEED, PROGRAMS):
        rows, m = iss_run(prog)       # ModelError (no HALT in cap) fails the test
        assert m.halted and len(rows) - 1 <= prog.max_edges + gen.IDLE_AFTER_HALT, prog.name
        problems += [f"program {prog.index} ({prog.name}): {p}" for p in gen.assembler_crosscheck(prog, m)]
        events.append(m.events)
        total_edges += len(rows) - 1
    assert not problems, "ISS vs assembler disagreement(s):\n" + "\n".join(problems[:20])
    counts = gen.tally(events)
    short = gen.gate(counts, MIN_RETIRE, MIN_BUCKET)
    for b, n in sorted(counts.items()):
        dut._log.info(f"bucket {b:28s} {n}")
    dut._log.info(f"programs={PROGRAMS} iss_edges={total_edges}")
    assert not short, "coverage buckets under their minimum: " + ", ".join(
        f"{b} {n}<{need}" for b, n, need in short)


@cocotb.test()
async def test_isa_lockstep_random_programs(dut):
    """Every program of the seed set, compared edge by edge.  A pass
    means: every compared field of every row of every program matched."""
    if skip_if_gates(dut):
        return
    start_clock(dut)
    digest, edges, ran = hashlib.sha256(), 0, 0
    for prog in programs():
        edges += await lockstep(dut, prog, digest)
        ran += 1
    dut._log.info(f"lockstep: seed={SEED} programs={ran} edges_compared={edges} "
                  f"trace_sha256={digest.hexdigest()}")
    assert ran, "no program selected"


@cocotb.test()
async def test_sub_carry_polarity_pin(dut):
    """The SUB `C` polarity is an OPEN DETAIL of DR 0001 (it says only
    'sets Z, C'; no instruction reads C).  The ISS carries the borrow
    convention as an explicit pin; this checks the core against that pin on
    its own, so a disagreement is reported as a polarity finding and not as
    a general ISA mismatch.  `flag_c` is white-box state (RTL only)."""
    if skip_if_gates(dut):
        return
    start_clock(dut)
    prog = next(p for p in gen.generate(SEED, PROGRAMS) if p.name == "sub-borrow-cases")
    rows, machine = iss_run(prog)
    await load_image(dut, prog.image)
    seen = []
    for edge in range(len(rows)):
        if edge:
            await RisingEdge(dut.clk)
        rtl = await sample(dut)
        if edge < len(rows) - 1:
            drive(dut, prog.inputs(edge + 1))
        seen.append(rtl.c)
    subs = [e for e in machine.events if e.mnemonic == "SUB"]
    assert len(subs) >= 4
    for e in subs:
        got, want = seen[e.edge], rows[e.edge].c
        assert got == want, (
            f"{OPEN_DETAIL_C}: after SUB at edge {e.edge} (pc={e.pc:#04x}) RTL C={got}, "
            f"model C={want} (borrow={e.info['borrow']})")
