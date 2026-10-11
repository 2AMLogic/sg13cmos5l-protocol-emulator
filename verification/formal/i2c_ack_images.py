#!/usr/bin/env python3
"""Image and parameter generator for the `i2c_ack_window` formal runner
(issue #259). Pure Python, no PDK, no simulator.

For one speed grade (`i2c_fast` or `i2c_std`) it writes, under <out-dir>,
the golden image and every firmware mutant as:

    <name>.asm        the (mutated) assembler source
    <name>.hex        assembled with the repository's own assembler
    <name>.cycles.txt its cycle report
    <name>.rom.v      `i2c_image_rom`, the 256-word combinational ROM the
                      formal harness instantiates (unused words 0000)

and a `manifest.json` listing sha256 of every file plus, per mutant, the
assertion label(s) the monitor must fire first (`expect`). The golden image
is checked byte for byte against the committed firmware/build/<grade>.hex
(a stale committed image is an error, not a quiet pass).

Mutants are text substitutions on a COPY of the committed assembler source;
firmware/ is never edited. Every substitution must apply exactly once (the
`early_orig_*` ones replace one ACK slot with its pre-#258 text from git);
a missing anchor is a hard error, so a mutant can never silently become a
second golden run. All mutants are assembled to fresh images with the
repository assembler, so each carries its own hash.

    i2c_ack_images.py params <grade>         # -D flags for the monitor
    i2c_ack_images.py gen <grade> <out-dir>  # images + manifest.json
    i2c_ack_images.py list|table <manifest>; field <manifest> <image|-> <key>
    i2c_ack_images.py stim <cex.aiw> <design.ywb> <out.hex>   # replay stimulus
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402

GRADES = ("i2c_fast", "i2c_std")

#: t_SU;DAT in core cycles at the bench's nominal 20 ns clock (UM10204
#: Table 10: 100 ns Fast, 250 ns Standard; Standard rounds 12.5 up).
SU_CYC = {"i2c_fast": 5, "i2c_std": 13}

#: Last revision whose ACK slots sampled in the low phase (issue #258).
ORIGINAL_REV = "b76ec6d4cce124c4a861166029c4707c00276978"

SLOTS = {
    "addr": re.compile(r"^\.cyclesec i2c_ack1_low\n.*?^        BNZ   stop_from_addr", re.S | re.M),
    "data": re.compile(r"^\.cyclesec i2c_ack2_low\n.*?^\.cyclesec i2c_ack2_high\n.*?^\.endcyclesec[^\n]*\n",
                       re.S | re.M),
}
HIGH = {
    "addr": re.compile(r"^\.cyclesec i2c_ack1_high\n.*?^        BNZ   stop_from_addr[^\n]*\n", re.S | re.M),
    "data": re.compile(r"^\.cyclesec i2c_ack2_high\n.*?^\.endcyclesec[^\n]*\n", re.S | re.M),
}
RELEASE_MOV = "        MOV   R3, R1          ; 0x08: SDA released for the ACK slot\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_cycles(grade: str) -> dict:
    sections = {}
    for line in (REPO_ROOT / "firmware" / "build" / f"{grade}.cycles.txt").read_text().splitlines():
        m = re.match(r"CYCLES name=(\S+) start=\d+ end=\d+ cycles=(\d+)", line)
        if m:
            sections[m.group(1)] = int(m.group(2))
        m = re.match(r"TOTAL-CYCLES (\d+)", line)
        if m:
            sections["__total__"] = int(m.group(1))
    return sections


def former_offset(grade: str) -> int:
    tree = ast.parse((REPO_ROOT / "verification" / "test_firmware_i2c_ack.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FORMER_LOW_PHASE_IN_OFFSET" for t in node.targets
        ):
            return ast.literal_eval(node.value)[grade]
    raise SystemExit("test_firmware_i2c_ack.py has no FORMER_LOW_PHASE_IN_OFFSET")


def params(grade: str) -> dict:
    s = read_cycles(grade)
    stop = max(s["i2c_stop_addr_low"] + s["i2c_stop_addr"], s["i2c_stop_data_low"] + s["i2c_stop_data"])
    # FORMER_AGE: the pre-#258 IN sat `offset` cycles after the OUT that
    # lowers SCL; the lowered line is visible one cycle after the OUT, so
    # that IN read the bus at age `offset - 1` of the observed low phase.
    return {"SU_CYC": SU_CYC[grade], "STOP_BOUND": stop, "FORMER_AGE": former_offset(grade) - 1,
            "TOTAL_CYCLES": s["__total__"]}


def original_source(grade: str) -> str:
    return subprocess.run(["git", "show", f"{ORIGINAL_REV}:firmware/asm/{grade}.asm"],
                          cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def once(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"mutant anchor for {what} matched {text.count(old)}x (need exactly 1)")
    return text.replace(old, new, 1)


def sub_slot(text: str, rx: "re.Pattern[str]", fn, what: str) -> str:
    hits = rx.findall(text)
    if len(hits) != 1:
        raise SystemExit(f"mutant region for {what} matched {len(hits)}x (need exactly 1)")
    return text.replace(hits[0], fn(hits[0]), 1)


def wait_split(m: "re.Match[str]") -> str:
    n = int(m.group(1))
    a = (n - 2) // 2
    b = n - 2 - a
    return (f"WAIT  {a}\n        IN    R3, UIO_IN\n        WAIT  {b}")


# --- the mutants ----------------------------------------------------------
def m_early_orig(slot):
    def f(grade, text):
        orig = SLOTS[slot].findall(original_source(grade))
        if len(orig) != 1:
            raise SystemExit("original slot not found in git history")
        return sub_slot(text, SLOTS[slot], lambda cur: orig[0], f"early_orig_{slot}")
    return f


def m_at_rise(slot):
    def f(grade, text):
        def fn(sec):
            waits = re.findall(r"^        WAIT\s+(\d+)", sec, re.M)
            first = re.search(r"^        WAIT\s+\d+[^\n]*\n", sec, re.M).group(0)
            # drop the first WAIT, sample straight after the rise OUT (the
            # rise cycle itself) and fold the removed delay into the last WAIT
            sec = once(sec, first, "", "at_rise first wait")
            total = int(waits[0]) + int(waits[-1]) + 1
            if total > 255:
                raise SystemExit("at_rise: folded wait exceeds 255")
            idx = sec.rfind("WAIT")
            end = sec.index("\n", idx)
            sec = sec[:idx] + f"WAIT  {total}" + sec[end:]
            # move the (now second-from-OUT) IN+AND up: they already follow the OUT
            return sec
        return sub_slot(text, HIGH[slot], fn, f"at_rise_{slot}")
    return f


def m_late(slot):
    def f(grade, text):
        if slot == "addr":
            def fn(sec):
                head = sec.split("\n", 1)[0] + "\n"
                waits = re.findall(r"^        WAIT\s+(\d+)", sec, re.M)
                wait = int(waits[0]) + int(waits[1]) + 1
                return (head + "        OUT   UIO_OUT, R3\n" + f"        WAIT  {wait}\n"
                        "        LDI   R3, 0x08\n"
                        "        OUT   UIO_OUT, R3     ; MUTANT: SCL falls before the sample\n"
                        "        IN    R3, UIO_IN\n        AND   R3, R1\n"
                        "        BNZ   stop_from_addr\n")
            return sub_slot(text, HIGH["addr"], fn, "late_addr")

        def fn2(sec):
            sec = re.sub(r"^        IN    R3, UIO_IN[^\n]*\n", "", sec, count=1, flags=re.M)
            return re.sub(r"^        AND   R3, R1[^\n]*\n", "", sec, count=1, flags=re.M)
        text = sub_slot(text, HIGH["data"], fn2, "late_data")
        old = ".cyclesec i2c_stop_data_low\n        OUT   UIO_OUT, R3     ; SCL falls; SDA still released\n"
        return once(text, old, old + "        IN    R3, UIO_IN      ; MUTANT: sampled after the ninth fall\n"
                    "        AND   R3, R1\n", "late_data stop section")
    return f


def m_missing(slot):
    def f(grade, text):
        return sub_slot(text, HIGH[slot],
                        lambda sec: re.sub(r"^        IN    R3, UIO_IN", "        NOP", sec, count=1, flags=re.M),
                        f"missing_{slot}")
    return f


def m_extra(slot):
    def f(grade, text):
        return sub_slot(text, HIGH[slot],
                        lambda sec: re.sub(r"WAIT\s+(\d+)", wait_split, sec, count=1),
                        f"extra_{slot}")
    return f


def m_sda_driven(slot):
    def f(grade, text):
        parts = text.split(RELEASE_MOV)
        if len(parts) != 3:
            raise SystemExit(f"sda_driven: release MOV found {len(parts) - 1}x (need 2)")
        drive = "        LDI   R3, 0x00        ; MUTANT: SDA stays driven low in the ACK slot\n"
        return parts[0] + (drive if slot == "addr" else RELEASE_MOV) + parts[1] + \
            (drive if slot == "data" else RELEASE_MOV) + parts[2]
    return f


def m_nack_ignored(grade, text):
    return once(text, "        BNZ   stop_from_addr  ;", "        NOP                   ;", "nack_ignored BNZ")


MUTANTS = [
    # name, builder, assertion label(s) one of which must fire first, description
    ("early_orig_addr", m_early_orig("addr"), ["a2_in_window"], "original low-phase schedule, address slot (pre-#258 text from git)"),
    ("early_orig_data", m_early_orig("data"), ["a2_in_window"], "original low-phase schedule, data slot (pre-#258 text from git)"),
    ("at_rise_addr", m_at_rise("addr"), ["a2_in_window"], "address IN in the ninth rise cycle itself (not strictly after)"),
    ("at_rise_data", m_at_rise("data"), ["a2_in_window"], "data IN in the ninth rise cycle itself (not strictly after)"),
    ("late_addr", m_late("addr"), ["a2_in_window", "a3_missing_sample"], "address IN after the ninth fall"),
    ("late_data", m_late("data"), ["a2_in_window", "a3_missing_sample"], "data IN after the ninth fall"),
    ("missing_addr", m_missing("addr"), ["a3_missing_sample"], "no address-slot sample"),
    ("missing_data", m_missing("data"), ["a3_missing_sample"], "no data-slot sample"),
    ("extra_addr", m_extra("addr"), ["a3_extra_sample"], "two address-slot samples"),
    ("extra_data", m_extra("data"), ["a3_extra_sample"], "two data-slot samples"),
    ("sda_driven_addr", m_sda_driven("addr"), ["a1_sda_released"], "SDA driven low in the address ACK slot"),
    ("sda_driven_data", m_sda_driven("data"), ["a1_sda_released"], "SDA driven low in the data ACK slot"),
    ("nack_ignored", m_nack_ignored, ["a4_no_data_after_nack", "a6_stop_bound"], "address NACK does not branch to STOP (data byte sent)"),
]


def rom_verilog(words: list) -> str:
    out = ["// generated by i2c_ack_images.py -- constant image ROM for formal_top_i2c_ack",
           "module i2c_image_rom (input wire [7:0] addr, output reg [15:0] word);",
           "  always @* begin", "    case (addr)"]
    for a, w in enumerate(words):
        out.append(f"      8'd{a}: word = 16'h{w:04X};")
    out += ["      default: word = 16'h0000;", "    endcase", "  end", "endmodule", ""]
    return "\n".join(out)


def build(grade: str, name: str, text: str, out: Path) -> dict:
    src = out / f"{name}.asm"
    src.write_text(text, encoding="utf-8")
    try:
        prog = asm.assemble_file(src)
    except asm.AsmError as err:
        raise SystemExit(f"{name}: assembler error line {err.line_no}: {err.message}")
    hexs = asm.render_hex(prog)
    (out / f"{name}.hex").write_text(hexs, encoding="utf-8")
    (out / f"{name}.cycles.txt").write_text(asm.render_cycles_report(prog), encoding="utf-8")
    words = list(prog.words)
    if len(words) > 256:
        raise SystemExit(f"{name}: {len(words)} words")
    (out / f"{name}.rom.v").write_text(rom_verilog(words), encoding="utf-8")
    return {"asm_sha256": sha256(src.read_bytes()), "hex_sha256": sha256(hexs.encode()),
            "rom_sha256": sha256((out / f"{name}.rom.v").read_bytes()), "words": len(words),
            "total_cycles": prog.total_cycles}


def gen(grade: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    committed_asm = (REPO_ROOT / "firmware" / "asm" / f"{grade}.asm").read_text(encoding="utf-8")
    committed_hex = (REPO_ROOT / "firmware" / "build" / f"{grade}.hex").read_bytes()
    man = {"grade": grade, "params": params(grade), "original_rev": ORIGINAL_REV,
           "committed_asm_sha256": sha256(committed_asm.encode()),
           "committed_hex_sha256": sha256(committed_hex), "images": {}}
    gold = build(grade, "golden", committed_asm, out)
    if (out / "golden.hex").read_bytes() != committed_hex:
        raise SystemExit(f"{grade}: firmware/build/{grade}.hex is stale against its source")
    man["images"]["golden"] = {**gold, "kind": "golden"}
    for name, fn, expect, desc in MUTANTS:
        mutated = fn(grade, committed_asm)
        if mutated == committed_asm:
            raise SystemExit(f"{name}: identical to the committed source")
        info = build(grade, name, mutated, out)
        if info["hex_sha256"] == gold["hex_sha256"]:
            raise SystemExit(f"{name}: assembled image identical to golden")
        # Legs (address outcome ADDR_OUTCOME: 1 = ACK, 0 = NACK) on which the
        # mutated code executes at all: the data slot is only reached after
        # an address ACK; the ignored-NACK defect only shows on a NACK.
        legs = [0] if name == "nack_ignored" else ([1] if name.endswith("_data") else [1, 0])
        man["images"][name] = {**info, "kind": "mutant", "expect": expect, "description": desc,
                               "legs": legs}
    hs = [v["hex_sha256"] for v in man["images"].values()]
    if len(set(hs)) != len(hs):
        raise SystemExit("two images share a hash")
    (out / "manifest.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")


def main(argv) -> int:
    if len(argv) >= 2 and argv[0] == "params" and argv[1] in GRADES:
        p = params(argv[1])
        print(f"-D SU_CYC={p['SU_CYC']} -D STOP_BOUND={p['STOP_BOUND']} -D FORMER_AGE={p['FORMER_AGE']}")
        return 0
    if len(argv) == 3 and argv[0] == "gen" and argv[1] in GRADES:
        gen(argv[1], Path(argv[2]))
        return 0
    if len(argv) == 4 and argv[0] == "stim":
        # stim <cex.aiw> <design.ywb> <out.hex>: the per-frame (ack_raw, ui_in)
        # of an ABC counterexample (AIGER 1.9 witness), one hex word per frame,
        # {ack_raw, ui_in[7:0]}, for the Icarus replay testbench.
        lines = Path(argv[1]).read_text().split("\n")
        ywb = json.load(open(argv[2]))
        pos = {}
        for e in ywb["inputs"]:
            nm = e["path"][0].lstrip("\\")
            if nm in ("ack_raw", "ui_in"):
                pos[(nm, e["offset"])] = e["input"]
        frames = [ln for ln in lines[1:] if ln and set(ln) <= {"0", "1", "x"}]
        out = []
        for ln in frames:
            ui = sum((ln[pos[("ui_in", b)]] == "1") << b for b in range(8) if ("ui_in", b) in pos)
            ack = int(ln[pos[("ack_raw", 0)]] == "1")
            out.append(f"{(ack << 8) | ui:03X}")
        Path(argv[3]).write_text("\n".join(out) + "\n")
        print(len(out))
        return 0
    if len(argv) >= 2 and argv[0] == "list":
        m = json.load(open(argv[1]))
        print(" ".join(k for k, v in m["images"].items() if v["kind"] == "mutant"))
        return 0
    if len(argv) == 4 and argv[0] == "field":
        m = json.load(open(argv[1]))
        v = m["images"][argv[2]] if argv[2] != "-" else m["params"]
        v = v[argv[3]]
        print(" ".join(str(x) for x in v) if isinstance(v, list) else v)
        return 0
    if len(argv) == 2 and argv[0] == "table":
        m = json.load(open(argv[1]))
        for k, v in m["images"].items():
            print(f"  image {k:18s} hex {v['hex_sha256'][:16]} rom {v['rom_sha256'][:16]} words {v['words']}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
