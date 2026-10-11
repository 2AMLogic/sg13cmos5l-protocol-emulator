#!/usr/bin/env python3
"""Tests for scripts/check_architecture.py (issue #230). Stdlib only.

Every failure mode is qualified on an independently mutated temporary copy
of the committed document; the committed document, the assembler and the
reference model are only read.

    python3 scripts/test_check_architecture.py
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_architecture as ca  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / ca.DOC_REL
ASM, ISA = ca.load_sources(REPO)
TEXT = DOC.read_text(encoding="utf-8")


def row_line(prefix: str) -> str:
    """The committed document's one line starting with `prefix`."""
    hits = [ln for ln in TEXT.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


class ArchitectureDrift(unittest.TestCase):
    def run_check(self, text):
        return ca.check_text(text, ASM, ISA, DOC.parent)

    def mutate(self, old, new, count=1):
        self.assertEqual(TEXT.count(old), count, f"fixture anchor not unique: {old!r}")
        return TEXT.replace(old, new)

    def assertFails(self, text, *needles):
        errs = self.run_check(text)
        self.assertTrue(errs, "expected a failure, the check passed")
        for needle in needles:
            self.assertTrue(any(needle in e for e in errs), f"no error mentions {needle!r}: {errs}")
        return errs

    # --- the committed document ------------------------------------------
    def test_committed_document_passes(self):
        self.assertEqual(self.run_check(TEXT), [])

    def test_cli_on_committed_tree_exits_zero(self):
        self.assertEqual(ca.main(["--root", str(REPO)]), 0)

    def test_cli_on_mutated_copy_exits_one(self):
        # A temporary copy beside the real one, so its relative links resolve.
        with tempfile.TemporaryDirectory(dir=DOC.parent) as tmp:
            doc = Path(tmp) / "architecture.md"
            text = TEXT.replace(row_line("| `ADD` |") + "\n", "").replace("](../../", "](../../../")
            text = text.replace("](../info.md", "](../../info.md").replace("](verification.md", "](../verification.md")
            doc.write_text(text, encoding="utf-8")
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                code = ca.main(["--root", str(REPO), "--doc", str(doc)])
            self.assertEqual(code, 1)
            self.assertIn("missing row for mnemonic `ADD`", err.getvalue())
            self.assertNotIn("does not exist", err.getvalue())  # links resolved
            self.assertNotIn(" 0 drift error(s)", out.getvalue())

    # --- rows: missing, duplicate, unknown ---------------------------------
    def test_missing_opcode_row(self):
        self.assertFails(TEXT.replace(row_line("| `ADD` |") + "\n", ""),
                         "missing row for mnemonic `ADD`")

    def test_missing_alias_row(self):
        self.assertFails(TEXT.replace(row_line("| `WCTL` |") + "\n", ""),
                         "missing row for mnemonic `WCTL`")
        self.assertFails(TEXT.replace(row_line("| `RCTL` |") + "\n", ""),
                         "missing row for mnemonic `RCTL`")

    def test_duplicate_opcode_row(self):
        line = row_line("| `LDI` |")
        self.assertFails(self.mutate(line, line + "\n" + line), "duplicate row 'LDI'")

    def test_unknown_opcode_row(self):
        line = row_line("| `HALT` |")
        extra = line.replace("`HALT`", "`SLEEP`")
        self.assertFails(self.mutate(line, line + "\n" + extra), "row 'SLEEP': unknown mnemonic")

    def test_missing_control_row(self):
        self.assertFails(TEXT.replace(row_line("| `0x14` |") + "\n", ""),
                         "missing row for control register `CRC_BYTE`")

    def test_duplicate_control_row(self):
        line = row_line("| `0x08` |")
        self.assertFails(self.mutate(line, line + "\n" + line), "duplicate row 'BOOT_STATUS'")

    def test_unknown_control_row(self):
        line = row_line("| `0x19` |")
        extra = "| `0x1A` | `MANCH` | yes | no | 1 | reserved | not built |"
        self.assertFails(self.mutate(line, line + "\n" + extra), "row 'MANCH': unknown control register")

    def test_missing_port_and_shift_rows(self):
        self.assertFails(TEXT.replace(row_line("| `UIO_IN` |") + "\n", ""),
                         "missing row for port `UIO_IN`")
        self.assertFails(TEXT.replace(row_line("| `RIGHT` |") + "\n", ""),
                         "missing row for `RIGHT`")

    # --- tables and columns ----------------------------------------------
    def test_missing_table_marker(self):
        self.assertFails(self.mutate("<!-- arch-table:control:begin -->\n", ""),
                         "table 'control': expected exactly one")

    def test_missing_column(self):
        header = row_line("| Mnemonic |")
        self.assertFails(self.mutate(header, header.replace("| Cycles |", "| Cost |")),
                         "missing column(s) 'Cycles'")

    def test_broken_separator_and_cell_count(self):
        sep = "|---|---|---|---|---|---|---|---|---|"
        self.assertFails(self.mutate(sep, sep.replace("---", "x", 1)), "not a separator row")
        line = row_line("| `MOV` |")
        self.assertFails(self.mutate(line, line + " extra |"), "cells, header has")

    # --- malformed cells -------------------------------------------------
    def test_malformed_opcode(self):
        line = row_line("| `ADD` |")
        self.assertFails(self.mutate(line, line.replace("`0x3`", "`0xG`")),
                         "row 'ADD': Opcode '0xG' is malformed")

    def test_malformed_index_and_cycles(self):
        line = row_line("| `0x02` |")
        self.assertFails(self.mutate(line, line.replace("`0x02`", "`0xZZ`")),
                         "row 'PM_ADDR': k '0xZZ' is malformed")
        line = row_line("| `0x03` |")
        self.assertFails(self.mutate(line, line.replace("| 1 | 2 |", "| 1 | two |")),
                         "row 'PM_DATA_HI': Read cycles 'two' is malformed")

    def test_malformed_cycle_formula(self):
        line = row_line("| `WAIT` |")
        self.assertFails(self.mutate(line, line.replace("| imm8 + 1 |", "| imm8 plus 1 |")),
                         "row 'WAIT': Cycles 'imm8 plus 1' is malformed")

    def test_malformed_encoding(self):
        line = row_line("| `LDI` |")
        self.assertFails(self.mutate(line, line.replace("`0001 dd 00 iiiiiiii`", "`0001 dd 00 iiiiiii`")),
                         "row 'LDI': Encoding '0001 dd 00 iiiiiii' is malformed")

    def test_malformed_flag_and_permission(self):
        line = row_line("| `ADD` |")
        self.assertFails(self.mutate(line, line.replace("| zero | carry |", "| maybe | carry |")),
                         "row 'ADD': Z 'maybe' is malformed")
        line = row_line("| `0x09` |")
        self.assertFails(self.mutate(line, line.replace("| no | yes |", "| nope | yes |")),
                         "row 'HW_ID': W 'nope'")

    # --- drift: opcode, kind, encoding, cycles ----------------------------
    def test_wrong_opcode_and_kind(self):
        line = row_line("| `ADD` |")
        self.assertFails(self.mutate(line, line.replace("`0x3`", "`0x4`")),
                         "row 'ADD': Opcode 0x4 but the assembler has 0x3")
        line = row_line("| `JMP` |")
        self.assertFails(self.mutate(line, line.replace("`branch`", "`wait`")),
                         "row 'JMP': Kind 'wait'")

    def test_wrong_encoding_field_position(self):
        # LDI with Rd and the port slot swapped: every sample assembles differently.
        line = row_line("| `LDI` |")
        self.assertFails(self.mutate(line, line.replace("`0001 dd 00 iiiiiiii`", "`0001 00 dd iiiiiiii`")),
                         "row 'LDI': documented encoding gives")

    def test_wrong_out_source_field(self):
        # OUT's source register rides [11:10], not [9:8].
        line = row_line("| `OUT` |")
        self.assertFails(self.mutate(line, line.replace("`1010 ss pp 00000000`", "`1010 pp ss 00000000`")),
                         "row 'OUT': documented encoding gives")

    def test_wrong_control_port_bits(self):
        line = row_line("| `RCTL` |")
        self.assertFails(self.mutate(line, line.replace("`1001 dd 10 kkkkkkkk`", "`1001 dd 11 kkkkkkkk`")),
                         "row 'RCTL': documented encoding gives")

    def test_wait_boundaries(self):
        # 'imm8' alone is off by one at WAIT 0 and at WAIT 255.
        line = row_line("| `WAIT` |")
        errs = self.assertFails(self.mutate(line, line.replace("| imm8 + 1 |", "| imm8 + 0 |")),
                                "`WAIT 0`, the assembler counts 1")
        self.assertTrue(any("`WAIT 255`, the assembler counts 256" in e for e in errs), errs)

    def test_wrong_fixed_cycles(self):
        line = row_line("| `BZ` |")
        self.assertFails(self.mutate(line, line.replace("| 1 | unchanged | unchanged |", "| 2 | unchanged | unchanged |")),
                         "row 'BZ': documented cycles 2")

    # --- drift: control space ---------------------------------------------
    def test_wrong_control_latency(self):
        line = row_line("| `0x14` |")
        self.assertFails(self.mutate(line, line.replace("| 9 | reserved |", "| 8 | reserved |")),
                         "row 'CRC_BYTE': Write cycles 8 but the assembler's CTL_REGS has 9")
        line = row_line("| `0x03` |")
        errs = self.assertFails(self.mutate(line, line.replace("| 1 | 2 |", "| 1 | 1 |")),
                                "row 'PM_DATA_HI': Read cycles 1 but the assembler's CTL_REGS has 2")
        # ...and the RCTL row, which reads its cycles from this table, notices too.
        self.assertTrue(any("row 'RCTL'" in e and "PM_DATA_HI" in e for e in errs), errs)

    def test_wrong_control_permission(self):
        line = row_line("| `0x08` |")
        self.assertFails(self.mutate(line, line.replace("| no | yes | reserved | 1 |", "| yes | yes | 1 | 1 |")),
                         "row 'BOOT_STATUS': W 'yes' but the assembler's CTL_REGS says no")
        line = row_line("| `0x05` |")
        self.assertFails(self.mutate(line, line.replace("| 2 | reserved |", "| 2 | 1 |")),
                         "row 'RUN': Read cycles '1' but that direction is unassigned")

    def test_wrong_control_index(self):
        line = row_line("| `0x10` |")
        self.assertFails(self.mutate(line, line.replace("`0x10`", "`0x1A`")),
                         "row 'CRC_CFG': k 0x1A but the assembler has 0x10")

    # --- drift: flags (against the independent model) ----------------------
    def test_sub_documented_as_carry(self):
        line = row_line("| `SUB` |")
        self.assertFails(self.mutate(line, line.replace("| zero | borrow |", "| zero | carry |")),
                         "row 'SUB'", "C documented 'carry'")

    def test_add_without_z(self):
        line = row_line("| `ADD` |")
        self.assertFails(self.mutate(line, line.replace("| zero | carry |", "| unchanged | carry |")),
                         "row 'ADD'", "Z documented unchanged, the model writes Z")

    def test_logic_documented_as_writing_c(self):
        line = row_line("| `AND` |")
        self.assertFails(self.mutate(line, line.replace("| zero | unchanged |", "| zero | carry |")),
                         "row 'AND'", "the model leaves C unchanged")

    def test_shf_documented_as_writing_z(self):
        line = row_line("| `SHF` |")
        self.assertFails(self.mutate(line, line.replace("| unchanged | shift-out |", "| zero | shift-out |")),
                         "row 'SHF'", "the model leaves Z unchanged")

    def test_mov_documented_as_writing_c(self):
        line = row_line("| `MOV` |")
        self.assertFails(self.mutate(line, line.replace("| unchanged | unchanged |", "| unchanged | carry |")),
                         "row 'MOV'", "the model leaves C unchanged")

    def test_shift_fill_and_direction(self):
        line = row_line("| `LEFT` |")
        self.assertFails(self.mutate(line, line.replace("| 1 | 0 | `Rd[7]` |", "| 1 | 1 | `Rd[7]` |")),
                         "row 'LEFT': Fill 1")
        self.assertFails(self.mutate(line, line.replace("| 1 | 0 | `Rd[7]` |", "| 0 | 0 | `Rd[7]` |")),
                         "row 'LEFT': Rs[0] 0")
        line = row_line("| `RIGHT` |")
        self.assertFails(self.mutate(line, line.replace("`Rd[0]`", "`Rd[7]`")),
                         "row 'RIGHT': C is Rd[7]")

    # --- drift: ports and reserved encodings -------------------------------
    def test_wrong_port(self):
        line = row_line("| `UIO_IN` |")
        self.assertFails(self.mutate(line, line.replace("| yes | no |", "| yes | yes |")),
                         "row 'UIO_IN': OUT 'yes'")
        self.assertFails(self.mutate(line, line.replace("`01`", "`11`", 1)),
                         "row 'UIO_IN': Code 11")

    def test_reserved_distinction(self):
        line = row_line("| `WCTL 0x1A, R0` |")
        self.assertFails(self.mutate(line, line.replace("| error | 1 |", "| 1 | 1 |")),
                         "Default says 1 cycle(s), but the assembler refuses it")
        self.assertFails(self.mutate(line, line.replace("| error | 1 |", "| error | error |")),
                         "With --allow-reserved says error, but the assembler accepts it")
        line = row_line("| `OUT UIO_IN, R0` |")
        self.assertFails(self.mutate(line, line.replace("| error | error |", "| error | 1 |")),
                         "With --allow-reserved says 1 cycle(s), but the assembler refuses it")

    def test_reserved_case_not_covered(self):
        self.assertFails(TEXT.replace(row_line("| `RCTL R0, RUN` |") + "\n", ""),
                         "no example row for the case 'read of a write-only register'")
        self.assertFails(TEXT.replace(row_line("| `IN R0, UIO_OUT` |") + "\n", ""),
                         "no example row for the case 'IN from port 11'")

    # --- links -------------------------------------------------------------
    def test_broken_link(self):
        self.assertFails(self.mutate("(../../verification/records/isa-lockstep/)",
                                     "(../../verification/records/isa-lockstep-gone/)"),
                         "link target ../../verification/records/isa-lockstep-gone/ does not exist")

    def test_prose_outside_tables_is_free(self):
        text = TEXT.replace("## Timing model", "## Timing model\n\n| a | b |\n|---|---|\n| free | table |")
        self.assertEqual(self.run_check(text), [])


if __name__ == "__main__":
    unittest.main()
