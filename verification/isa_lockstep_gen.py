"""Seeded, terminating instruction-stream generator and coverage gate for the
ISA lockstep bench (issue #152).  Pure Python: no simulator, no cocotb, so
`verification/test_isa_model.py` can exercise it (and the whole coverage
gate, through the ISS) without Icarus.

Termination by construction
---------------------------
A program is a top-level sequence of *units* (one instruction, or an atomic
macro such as a bounded loop) ending in `HALT`.  Control transfers are
FORWARD ONLY at unit boundaries (`JMP`/`BZ`/`BNZ`/`WCTL RUN` never target an
earlier address and never the inside of a loop), and the only backward edge
is the bounded loop: `LDI Ro,1; LDI Rc,k; top: body; SUB Rc,Ro; BNZ top`
with `1 <= k <= 6`, where the body never writes the counter `Rc` or the
step register `Ro`, never contains `HALT`/`RUN`/`JMP`, and branches only
forward to a boundary inside the body.  Every program therefore reaches
its final `HALT`.  `Generated.max_edges` is a static upper bound on its
length in clock edges; running past it is a generator bug and the bench
fails on it (it is never a pass).

Program memory discipline (so the ISS never has to guess at unloaded
words): the serial image is `code + pad`, where `pad` is a small block of
random data words that code never executes.  Program-memory reads address
the image only; program-memory writes address the pad only; the one
exception is the "run written code" tail, which writes a short
straight-line routine ending in `HALT` just past the image and `RUN`s to
it.

Everything is drawn from `random.Random(f"{seed}:{index}")`, so program
`index` of seed `seed` is reproducible byte for byte, alone.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from reference_models import isa  # noqa: E402

PAD_WORDS = 8
MAX_CODE_WORDS = 110
IDLE_AFTER_HALT = 6          # edges checked after HALT retires: state must hold
LOOP_MAX_ITERS = 6
UNASSIGNED_K = [0x0A, 0x0B, 0x0F, 0x1A, 0x1B, 0x1F, 0x20, 0x7F, 0x80, 0xFE, 0xFF]
P1_K = [0x10, 0x11, 0x12, 0x13, 0x14, 0x15]   # DR 0015 P1 (issue #208)
P2_K = [0x16, 0x17, 0x18, 0x19]               # DR 0015 P2
PORT_NAME = {0: "UI_IN", 1: "UIO_IN", 2: "UO_OUT", 3: "UIO_OUT"}
INTERESTING = [0x00, 0x01, 0x02, 0x7F, 0x80, 0x81, 0xFE, 0xFF]

# Item = callable(labels) -> (word, asm_text, raw).  raw=True: the assembler
# cannot express this encoding (reserved no-ops); its text is a NOP stand-in
# and the word differs from the assembler's on purpose.


def _it(word, text, raw=False):
    return lambda L: (word, text, raw)


def i_ldi(rd, v):
    return _it(isa.encode("LDI", rd=rd, imm=v), f"LDI R{rd}, {v:#04x}")


def i_rr(mn, rd, rs):
    return _it(isa.encode(mn, rd=rd, rs=rs), f"{mn} R{rd}, R{rs}")


def i_shf(rd, left):
    return _it(isa.encode("SHF", rd=rd, rs=left), f"SHF R{rd}, {'LEFT' if left else 'RIGHT'}")


def i_nop():
    return _it(isa.encode("NOP"), "NOP")


def i_halt():
    return _it(isa.encode("HALT"), "HALT")


def i_wait(n):
    return _it(isa.encode("WAIT", imm=n), f"WAIT {n}")


def i_in(rd, port, junk=0):
    if port == isa.PORT_UO_OUT:
        raise ValueError("IN port 10 is RCTL; use i_rctl")
    if port == isa.PORT_UIO_OUT:  # reserved no-op; imm8 is unused
        return _it(isa.encode("IN", rd=rd, port=port, imm=junk), "NOP", raw=True)
    return _it(isa.encode("IN", rd=rd, port=port), f"IN R{rd}, {PORT_NAME[port]}")


def i_out(src, port, junk=0):
    if port == isa.PORT_UI_IN:
        raise ValueError("OUT port 00 is WCTL; use i_wctl")
    if port == isa.PORT_UIO_IN:  # reserved no-op; imm8 is unused
        return _it(isa.encode("OUT", rd=src, port=port, imm=junk), "NOP", raw=True)
    return _it(isa.encode("OUT", rd=src, port=port), f"OUT {PORT_NAME[port]}, R{src}")


def i_wctl(k, src):
    return _it(isa.wctl(k, src), f"WCTL {k:#04x}, R{src}")


def i_rctl(rd, k):
    return _it(isa.rctl(rd, k), f"RCTL R{rd}, {k:#04x}")


def i_br(mn, label):
    return lambda L: (isa.encode(mn, imm=L[label]), f"{mn} {L[label]:#04x}", False)


def i_ldi_label(rd, label, offset=0):
    return lambda L: (isa.encode("LDI", rd=rd, imm=L[label] + offset),
                      f"LDI R{rd}, {(L[label] + offset) & 0xFF:#04x}", False)


def i_ldi_fn(rd, fn):
    """LDI with a value computed from the final layout (`fn(L) -> 0..255`)."""
    return lambda L: (isa.encode("LDI", rd=rd, imm=fn(L)), f"LDI R{rd}, {fn(L):#04x}", False)


def lab(name):
    return ("label", name)


@dataclass
class Generated:
    seed: object
    index: int
    kind: str
    name: str
    code: list            # code words (ends in HALT)
    text: str             # assembler source for the code (reserved encodings as NOP)
    raw: set              # code indices whose assembler word is a NOP stand-in
    pad: list             # data words after the code
    max_edges: int        # static bound on edges until HALT retires
    straight_line: bool   # no branch / loop / RUN: assembler total_cycles applies exactly
    pins: list = field(default_factory=list)   # pins[e-1] = (ui_in, uio_in) on edge e

    @property
    def image(self):
        return list(self.code) + list(self.pad)

    def inputs(self, edge):
        return self.pins[edge - 1]


def layout(items):
    """Resolve labels.  Returns (words, text_lines, raw_indices, labels)."""
    L, n = {}, 0
    for it in items:
        if isinstance(it, tuple):
            L[it[1]] = n
        else:
            n += 1
    L["__code_len"] = n
    words, lines, raw = [], [], set()
    for it in items:
        if isinstance(it, tuple):
            continue
        w, t, r = it(L)
        if r:
            raw.add(len(words))
        words.append(w)
        lines.append(t)
    return words, lines, raw, L


class _Gen:
    def __init__(self, rng, pad):
        self.rng = rng
        self.pad = pad
        self.nlabel = 0

    def newlabel(self, stem):
        self.nlabel += 1
        return f"{stem}{self.nlabel}"

    def value(self):
        r = self.rng
        return r.choice(INTERESTING) if r.random() < 0.45 else r.randrange(256)

    # -- single units ---------------------------------------------------------
    def u_alu(self, free):
        r = self.rng
        mn = r.choice(["ADD", "SUB", "AND", "OR", "XOR", "ADD", "SUB", "AND", "OR", "XOR"])
        rd = r.choice(free)
        rs = rd if r.random() < 0.15 else r.randrange(4)
        return [i_rr(mn, rd, rs)]

    def u_ldi(self, free):
        return [i_ldi(self.rng.choice(free), self.value())]

    def u_mov(self, free):
        return [i_rr("MOV", self.rng.choice(free), self.rng.randrange(4))]

    def u_shf(self, free):
        return [i_shf(self.rng.choice(free), self.rng.randrange(2))]

    def u_in(self, free):
        r = self.rng
        port = r.choice([0, 0, 1, 1, 3])
        return [i_in(r.choice(free), port, junk=r.randrange(256))]

    def u_out(self, free):
        r = self.rng
        port = r.choice([2, 2, 3, 3, 1])
        return [i_out(r.randrange(4), port, junk=r.randrange(256))]

    def u_wait(self, free, small=False):
        r = self.rng
        if small:
            n = r.choice([0, 1, 2, 3, 6])
        else:
            n = r.choice([0, 0, 1, 1, 2, 3, 7, 20, r.randrange(2, 255), 255, 255])
        return [i_wait(n)]

    def u_nop(self, free):
        return [i_nop()]

    def u_ctl_write(self, free):
        r = self.rng
        # P1/P2 indices come with their own units (u_p1 / u_p2); here they
        # are drawn a quarter of the time so DR 0012's buckets keep their share.
        if r.random() < 0.25:
            return [i_wctl(r.choice(P1_K + P2_K), r.randrange(4))]
        k = r.choice([0x00, 0x01, 0x02, 0x03, 0x06, 0x07, 0x08, 0x09] + UNASSIGNED_K)
        return [i_wctl(k, r.randrange(4))]

    def u_ctl_read(self, free):
        r = self.rng
        if r.random() < 0.25:
            return [i_rctl(r.choice(free), r.choice(P1_K + P2_K))]
        k = r.choice([0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09] + UNASSIGNED_K)
        return [i_rctl(r.choice(free), k)]

    def u_p1(self, free):
        """DR 0015 P1 in use: a configuration, poly / state bytes, a few
        steps (bit and byte), and reads into a register, so CRC reads
        return live, non-zero values the lockstep compares."""
        r = self.rng
        t = r.choice(free)
        items = [i_ldi(t, r.randrange(128)), i_wctl(0x10, t)]
        for k in (0x11, 0x12):
            for _ in range(r.choice([1, 2, 4])):
                items += [i_ldi(t, self.value()), i_wctl(k, t)]
        for _ in range(r.randrange(1, 4)):
            items += [i_ldi(t, self.value()), i_wctl(r.choice([0x13, 0x14, 0x14]), t)]
        for _ in range(r.randrange(1, 3)):
            items.append(i_rctl(r.choice(free), r.choice([0x10, 0x11, 0x12, 0x15, 0x15])))
        return items

    def u_p2(self, free):
        """DR 0015 P2 in use: a configuration (stuffing usually on, small
        N so stuff slots happen), several LINE_PUTs, reads."""
        r = self.rng
        t = r.choice(free)
        cfg = r.randrange(4) | r.choice([1, 2, 2, 0]) << 2 | r.randrange(4) << 4 | r.randrange(2) << 7
        items = [i_ldi(t, cfg), i_wctl(0x16, t)]
        for _ in range(r.randrange(2, 9)):
            items += [i_ldi(t, r.choice([0x00, 0x01, 0xFF, 0xFE])), i_wctl(0x17, t)]
            if r.random() < 0.4:
                items.append(i_rctl(r.choice(free), r.choice([0x18, 0x19])))
        items.append(i_rctl(r.choice(free), r.choice([0x16, 0x18, 0x19, 0x19])))
        return items

    def u_pm_write(self, free):
        r = self.rng
        t = r.choice(free)
        frac, hi, lo = r.random(), self.value(), self.value()
        pad = len(self.pad)
        return [
            i_ldi_fn(t, lambda L, frac=frac, pad=pad: L["__code_len"] + int(frac * pad)),
            i_wctl(0x02, t),
            i_ldi(t, hi), i_wctl(0x03, t),
            i_ldi(t, lo), i_wctl(0x04, t),
        ]

    def u_pm_read(self, free):
        r = self.rng
        t, x, y = r.choice(free), r.choice(free), r.choice(free)
        frac, pad = r.random(), len(self.pad)
        return [
            i_ldi_fn(t, lambda L, frac=frac, pad=pad: int(frac * (L["__code_len"] + pad))),
            i_wctl(0x02, t),
            i_rctl(x, 0x03),
            i_rctl(y, 0x04),
        ]

    def u_crc(self, free):
        r = self.rng
        if r.random() < 0.3:
            return [i_wctl(r.choice([0x06, 0x07]), r.randrange(4))]
        return [i_rctl(r.choice(free), r.choice([0x06, 0x07]))]

    # -- sequences --------------------------------------------------------------
    def seq(self, n, free, allow_loop, in_loop, prefix):
        """Items for `n` units plus the end label `<prefix>end`; forward-only
        branches target the boundary before unit j (labels `<prefix>j`) or the
        end label (j == n)."""
        r = self.rng
        items = []
        kinds = ["alu"] * 24 + ["ldi"] * 12 + ["mov"] * 9 + ["shf"] * 10 + ["in"] * 7 + ["out"] * 6 \
            + ["wait"] * 5 + ["nop"] * 10 + ["cw"] * 8 + ["cr"] * 10 + ["pmw"] * 2 + ["pmr"] * 2 \
            + ["crc"] * 2 + ["p1"] * 3 + ["p2"] * 3 + ["br"] * 14
        if allow_loop:
            kinds += ["loop"] * 4 + ["runfwd"] * 1 + ["jmp"] * 14
        for i in range(n):
            items.append(lab(f"{prefix}{i}"))
            k = r.choice(kinds)
            if k == "alu":
                items += self.u_alu(free)
            elif k == "ldi":
                items += self.u_ldi(free)
            elif k == "mov":
                items += self.u_mov(free)
            elif k == "shf":
                items += self.u_shf(free)
            elif k == "in":
                items += self.u_in(free)
            elif k == "out":
                items += self.u_out(free)
            elif k == "wait":
                items += self.u_wait(free, small=in_loop)
            elif k == "nop":
                items += self.u_nop(free)
            elif k == "cw":
                items += self.u_ctl_write(free)
            elif k == "cr":
                items += self.u_ctl_read(free)
            elif k == "pmw":
                items += self.u_pm_write(free)
            elif k == "pmr":
                items += self.u_pm_read(free)
            elif k == "crc":
                items += self.u_crc(free)
            elif k == "p1":
                items += self.u_p1(free)
            elif k == "p2":
                items += self.u_p2(free)
            elif k == "br":
                # a flag-setting instruction right before the branch, so both
                # outcomes are common; target a later boundary (or the end).
                items += self.u_alu(free)
                tgt = r.randrange(i + 1, n + 1)
                items.append(i_br(r.choice(["BZ", "BZ", "BNZ"]), f"{prefix}{tgt}" if tgt < n else f"{prefix}end"))
            elif k == "jmp":
                tgt = r.randrange(i + 1, n + 1)
                items.append(i_br("JMP", f"{prefix}{tgt}" if tgt < n else f"{prefix}end"))
            elif k == "runfwd":
                tgt = r.randrange(i + 1, n + 1)
                t = r.randrange(4)
                items.append(i_ldi_label(t, f"{prefix}{tgt}" if tgt < n else f"{prefix}end"))
                items.append(i_wctl(0x05, t))
            elif k == "loop":
                items += self.u_loop()
        items.append(lab(f"{prefix}end"))
        return items

    def u_loop(self):
        r = self.rng
        rc, ro = r.sample(range(4), 2)
        free = [x for x in range(4) if x not in (rc, ro)]
        top, pre = self.newlabel("top"), self.newlabel("lb")
        body = self.seq(r.randrange(1, 5), free, allow_loop=False, in_loop=True, prefix=pre)
        return [
            i_ldi(ro, 1), i_ldi(rc, r.randrange(1, LOOP_MAX_ITERS + 1)),
            lab(top), *body,
            i_rr("SUB", rc, ro),
            i_br("BNZ", top),
        ]

    def run_written_tail(self):
        """Write a short routine just past the image through PM_DATA_*, then
        `WCTL RUN` into it.  The routine is straight-line and ends in HALT."""
        r = self.rng
        k = r.randrange(1, 5)
        routine = []
        for _ in range(k):
            routine.append(r.choice([
                isa.encode("LDI", rd=r.randrange(4), imm=self.value()),
                isa.encode("ADD", rd=r.randrange(4), rs=r.randrange(4)),
                isa.encode("SUB", rd=r.randrange(4), rs=r.randrange(4)),
                isa.encode("XOR", rd=r.randrange(4), rs=r.randrange(4)),
                isa.encode("SHF", rd=r.randrange(4), rs=r.randrange(2)),
                isa.encode("OUT", rd=r.randrange(4), port=2),
                isa.encode("NOP"),
            ]))
        routine.append(isa.encode("HALT"))
        t = r.randrange(4)
        pad = len(self.pad)
        scratch = lambda L: L["__code_len"] + pad  # noqa: E731
        items = [i_ldi_fn(t, scratch), i_wctl(0x02, t)]
        for w in routine:
            items += [i_ldi(t, w >> 8), i_wctl(0x03, t), i_ldi(t, w & 0xFF), i_wctl(0x04, t)]
        items += [i_ldi_fn(t, scratch), i_wctl(0x05, t)]
        return items, len(routine)


def _bound(items):
    """Upper bound on edges: the static cost of every instruction, with each
    bounded loop's region counted LOOP_MAX_ITERS times.  A backward `BNZ` is
    the loop edge (the only backward transfer the generator emits)."""
    words, _, _, _ = layout(items)
    cost = [isa.static_cost(w) for w in words]
    mult = [1] * len(words)
    for a, w in enumerate(words):
        if w >> 12 == 0xE and (w & 0xFF) <= a:
            for b in range(w & 0xFF, a + 1):
                mult[b] *= LOOP_MAX_ITERS
    return sum(c * m for c, m in zip(cost, mult))


def _pins(seed, index, n):
    r = random.Random(f"{seed}:{index}:pins")
    return [(r.randrange(256), r.randrange(256)) for _ in range(n)]


def _build(seed, index, kind, name, items, pad, straight, extra=0):
    words, lines, raw, _ = layout(items)
    if len(words) > isa.WORDS - len(pad) - 16:
        raise ValueError("generated program too long")
    max_edges = 2 + _bound(items) + extra + 8
    return Generated(
        seed=seed, index=index, kind=kind, name=name, code=words,
        text="\n".join(lines) + "\n", raw=raw, pad=list(pad), max_edges=max_edges,
        straight_line=straight,
        pins=_pins(seed, index, max_edges + IDLE_AFTER_HALT + 4),
    )


# ---------------------------------------------------------------------------
# Directed programs (the issue's edge cases), always first in every seed set.
# ---------------------------------------------------------------------------
def _directed(seed):
    out = []

    def pad_for(i):
        r = random.Random(f"{seed}:d{i}:pad")
        return [r.randrange(65536) for _ in range(PAD_WORDS)]

    def add(name, items, straight, extra=0):
        i = len(out)
        out.append(_build(seed, i, "directed", name, items, pad_for(i), straight, extra))

    add("halt-first", [i_halt()], True)
    add("wait255-then-bz", [
        i_ldi(0, 5), i_ldi(1, 5), i_rr("SUB", 0, 1),            # Z = 1
        i_wait(255), i_br("BZ", "t1"), i_ldi(2, 0xEE), lab("t1"), i_ldi(3, 0x11), i_halt()], False)
    add("wait255-then-bnz", [
        i_ldi(0, 5), i_ldi(1, 5), i_rr("ADD", 0, 1),            # Z = 0
        i_wait(255), i_br("BNZ", "t1"), i_ldi(2, 0xEE), lab("t1"), i_ldi(3, 0x11), i_halt()], False)
    add("wait-values", [i_wait(0), i_wait(1), i_wait(2), i_wait(37), i_wait(255), i_wait(0), i_halt()], True)
    add("back-to-back-ctl", [
        i_ldi(0, 0xFF), i_wctl(0x00, 0), i_wctl(0x01, 0), i_rctl(1, 0x00), i_rctl(2, 0x01),
        i_ldi(3, 0), i_wctl(0x02, 3), i_ldi(0, 0xAB), i_wctl(0x03, 0), i_ldi(1, 0xCD),
        i_wctl(0x04, 1), i_wctl(0x04, 1), i_rctl(2, 0x02), i_rctl(3, 0x06), i_rctl(0, 0x07),
        i_wctl(0x06, 0), i_rctl(1, 0x06), i_rctl(2, 0x08), i_rctl(3, 0x09), i_rctl(0, 0x05),
        i_halt()], True)
    add("pm-read-image", [
        i_ldi(0, 0), i_wctl(0x02, 0), i_rctl(1, 0x03), i_rctl(2, 0x04), i_rctl(3, 0x04),
        i_rctl(1, 0x02), i_rctl(2, 0x03), i_rctl(3, 0x04), i_halt()], True)
    add("all-ports", [
        i_ldi(0, 0x5A), i_in(1, 0), i_in(2, 1), i_in(3, 3, junk=0x77), i_out(0, 2), i_out(1, 3),
        i_out(2, 1, junk=0x33), i_wctl(0x08, 0), i_rctl(3, 0x05), i_rctl(2, 0x77), i_wctl(0x77, 1),
        i_ldi(0, 0x81), i_wctl(0x01, 0), i_out(0, 3), i_ldi(0, 0x00), i_out(0, 3), i_halt()], True)
    add("sub-borrow-cases", [
        i_ldi(0, 3), i_ldi(1, 5), i_rr("SUB", 0, 1), i_ldi(0, 5), i_rr("SUB", 0, 1),
        i_ldi(0, 7), i_rr("SUB", 0, 1), i_ldi(0, 0), i_ldi(1, 1), i_rr("SUB", 0, 1), i_halt()], True)
    add("bounded-loop", [
        i_ldi(3, 1), i_ldi(2, 4), lab("top"), i_rr("ADD", 0, 3), i_shf(1, 1), i_rr("SUB", 2, 3),
        i_br("BNZ", "top"), i_halt()], False)
    add("shf-all", [
        i_ldi(0, 0x81), i_shf(0, 1), i_shf(0, 1), i_ldi(1, 0x81), i_shf(1, 0), i_shf(1, 0),
        i_ldi(2, 0xFF), i_shf(2, 1), i_shf(2, 0), i_halt()], True)

    # RUN to words just written (two shapes: run at once; run after a stall chain).
    for variant in range(2):
        i = len(out)
        g = _Gen(random.Random(f"{seed}:d{i}"), pad_for(i))
        tail, k = g.run_written_tail()
        pre = [i_ldi(0, 0x42), i_rr("ADD", 0, 0)] if variant else []
        add(f"run-written-{variant}", pre + tail + [i_halt()], False, extra=6 * k + 8)
    # DR 0015 P1 / P2 (issue #208): CRC-16/USB-style reflected setup, byte
    # and bit steps, every read; then USB-style NRZI + stuffing over a run
    # of 1s long enough to stuff.
    add("primitives", [
        i_ldi(0, 0x6F), i_wctl(0x10, 0), i_ldi(1, 0x01), i_wctl(0x11, 1), i_ldi(1, 0xA0),
        i_wctl(0x11, 1), i_ldi(1, 0xFF), i_wctl(0x12, 1), i_wctl(0x12, 1), i_wctl(0x10, 0),
        i_ldi(2, 0x31), i_wctl(0x14, 2), i_wctl(0x13, 2), i_wctl(0x14, 2), i_rctl(3, 0x15),
        i_rctl(3, 0x15), i_rctl(1, 0x12), i_rctl(2, 0x11), i_rctl(0, 0x10), i_rctl(1, 0x13),
        i_ldi(0, 0x95), i_wctl(0x16, 0), i_ldi(1, 1), i_wctl(0x17, 1), i_wctl(0x17, 1),
        i_wctl(0x17, 1), i_wctl(0x17, 1), i_wctl(0x17, 1), i_rctl(2, 0x19), i_rctl(3, 0x18),
        i_rctl(0, 0x16), i_rctl(2, 0x17), i_halt()], True)
    return out


def generate(seed, count):
    """The first `count` programs of `seed`: the directed set, then random."""
    progs = _directed(seed)[:count]
    index = len(_directed(seed))
    while len(progs) < count:
        progs.append(random_program(seed, index))
        index += 1
    return progs


def random_program(seed, index):
    """Program `index` of `seed`; if a draw is too long for the 256-word
    memory, the same stream is redrawn with fewer units (still deterministic)."""
    for shrink in range(8):
        try:
            return _random_program(seed, index, shrink)
        except ValueError:
            continue
    raise ValueError(f"cannot fit program {index} of seed {seed}")


def _random_program(seed, index, shrink):
    rng = random.Random(f"{seed}:{index}:{shrink}")
    pad = [rng.randrange(65536) for _ in range(PAD_WORDS)]
    g = _Gen(rng, pad)
    simple = rng.random() < 0.25
    n = max(2, rng.randrange(6, 30) >> shrink)
    kind = "random-straight" if simple else "random"
    if simple:
        free = [0, 1, 2, 3]
        items = []
        for _ in range(n):
            u = rng.choice([g.u_alu, g.u_alu, g.u_ldi, g.u_mov, g.u_shf, g.u_in, g.u_out,
                            g.u_ctl_write, g.u_ctl_read, g.u_pm_write, g.u_pm_read, g.u_crc,
                            g.u_p1, g.u_p2,
                            lambda f: g.u_wait(f, small=False)])
            items += u(free)
        items.append(i_halt())
        return _build(seed, index, kind, f"{kind}-{index}", items, pad, True)
    items = g.seq(n, [0, 1, 2, 3], allow_loop=True, in_loop=False, prefix="t")
    extra = 0
    if rng.random() < 0.12:
        tail, k = g.run_written_tail()
        items += tail
        extra = 6 * k + 8
    items.append(i_halt())
    return _build(seed, index, kind, f"{kind}-{index}", items, pad, False, extra)


# ---------------------------------------------------------------------------
# Coverage buckets, counted from the ISS event stream.
# ---------------------------------------------------------------------------
def coverage_buckets():
    """All bucket names, with the minimum each must reach (retire buckets use
    the request's `min_retire`; every other bucket uses `min_bucket`)."""
    b = [f"retire:{o.mnemonic}" for o in isa.OPCODES]
    b += [f"{m}:{x}" for m in ("ADD", "SUB") for x in ("c0", "c1", "zero", "nonzero")]
    b += [f"SHF:{d}:out{o}" for d in ("left", "right") for o in (0, 1)]
    b += [f"{m}:{t}" for m in ("BZ", "BNZ") for t in ("taken", "not-taken")]
    b += ["WAIT:0", "WAIT:1", "WAIT:mid", "WAIT:255"]
    b += [f"IN:port{p:02b}" for p in range(4)] + [f"OUT:port{p:02b}" for p in range(4)]
    for k, c in sorted(isa.CONTROL.items()):
        if c.readable:
            b.append(f"RCTL:{c.name}")
        if c.writable:
            b.append(f"WCTL:{c.name}")
    b += ["WCTL:unassigned", "RCTL:unassigned", "WCTL:read-only", "RCTL:write-only"]
    return b


def _classify(ev):
    mn, w, info = ev.mnemonic, ev.word, ev.info
    yield f"retire:{mn}"
    if mn == "ADD":
        yield f"ADD:c{info['c']}"
        yield "ADD:zero" if info["z"] else "ADD:nonzero"
    elif mn == "SUB":
        yield f"SUB:c{info['borrow']}"          # bucket on the borrow, polarity-free
        yield "SUB:zero" if info["z"] else "SUB:nonzero"
    elif mn == "SHF":
        yield f"SHF:{'left' if info['left'] else 'right'}:out{info['out']}"
    elif mn in ("BZ", "BNZ"):
        yield f"{mn}:{'taken' if info['taken'] else 'not-taken'}"
    elif mn == "WAIT":
        n = info["n"]
        yield f"WAIT:{n}" if n in (0, 1, 255) else "WAIT:mid"
    elif mn in ("IN", "OUT"):
        port = (w >> 8) & 3
        yield f"{mn}:port{port:02b}"
        if (mn == "OUT" and port == 0) or (mn == "IN" and port == 2):
            op = "WCTL" if mn == "OUT" else "RCTL"
            yield f"{op}:{info['kind']}" if info.get("noop") else f"{op}:{info['name']}"


def tally(events_by_program):
    """Bucket -> count over every program's ISS events."""
    counts = {b: 0 for b in coverage_buckets()}
    for events in events_by_program:
        for ev in events:
            for b in _classify(ev):
                if b in counts:
                    counts[b] += 1
    return counts


def gate(counts, min_retire, min_bucket):
    """Return the list of (bucket, got, need) that fall short; empty = pass."""
    short = []
    for b, n in counts.items():
        need = min_retire if b.startswith("retire:") else min_bucket
        if n < need:
            short.append((b, n, need))
    return short


# ---------------------------------------------------------------------------
# Three-way cycle cross-check: ISS vs the DR 0003 assembler (and, in the
# bench, the RTL trace).  The assembler is used here only as a second,
# independent statement of the encoding and of the static per-instruction
# cycle counts; the ISS never imports it.
# ---------------------------------------------------------------------------
def assembler_crosscheck(prog, machine):
    """Problems (empty = agreement) between the assembler and the ISS run
    `machine` of `prog`: assembled words equal the generator's encoding
    (except the reserved no-ops the assembler refuses, which it is given as
    NOP), each retired instruction's cost equals the assembler's static
    per-instruction cycles, and a straight-line program's `total_cycles`
    equals the ISS's edge count from first execute to HALT."""
    sys.path.insert(0, str(HERE.parent / "firmware" / "tools"))
    import asm  # noqa: E402

    problems = []
    p = asm.assemble_text(prog.text, allow_reserved=True)
    if len(p.words) != len(prog.code):
        return [f"assembler produced {len(p.words)} words, generator {len(prog.code)}"]
    for i, (a, w) in enumerate(zip(p.words, prog.code)):
        want = isa.encode("NOP") if i in prog.raw else w
        if a != want:
            problems.append(f"word {i}: assembler {a:#06x} != ISS-side encoding {want:#06x}")
    cycles = [ins.cycles for ins in p.instructions]
    for ev in machine.events:
        if ev.pc < len(prog.code) and ev.word == prog.code[ev.pc] and ev.cost != cycles[ev.pc]:
            problems.append(f"pc {ev.pc:#04x} {isa.disasm(ev.word)}: ISS cost {ev.cost} "
                            f"!= assembler {cycles[ev.pc]}")
    if prog.straight_line:
        halt = [ev for ev in machine.events if ev.mnemonic == "HALT"]
        if len(halt) != 1:
            problems.append("straight-line program did not retire exactly one HALT")
        else:
            span = halt[0].edge - 1   # first instruction executes on edge 2
            if span != p.total_cycles:
                problems.append(f"straight-line: ISS {span} cycles != assembler total_cycles "
                                f"{p.total_cycles}")
    return problems
