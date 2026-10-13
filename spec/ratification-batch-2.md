# Second ratification batch (preparation)

Status: **Recorded 2026-10-13** (issue #299) -- a worksheet for the next
two-key act, not a decision and not a ratification. It flips no `Status:`
line, relaxes nothing ratified and changes no RTL. The act itself stays a
human two-key act (`docs/ratification-gate.md`; the first one is
[`decision-records/0009-two-key-ratification-act.md`](decision-records/0009-two-key-ratification-act.md),
which bound rows 1-12 and DRs 0001-0004 only).

Submission is due **2027-01-18**. Two keys need calendar time (the first act
ran from 2026-09-26, issue #44, to 2026-10-11), so this list exists now.

## How to read it

* One line per still-`Proposed` decision record and per unratified row.
  `Status today` is read from the record's own `Status:` line.
* `Recommendation` is advice to the keys, never a decision. It is one of:
  **ratify** (bind as written), **amend first** (a dated note or edit is
  needed before it can be bound as written), **defer** (leave `Proposed` past
  2027-01-18; the deferral is then written into the record itself, per the
  deadline-discipline rule in `CLAUDE.md`).
* `Last dated note` is the latest date that appears in the record (rows:
  in `gap-to-submission.md`'s row cell). `Open blockers` lists issues that
  were open when this file was written; `scripts/check_docs_issue_states.py`
  is the on-demand check for issue states.
* `scripts/check_ratification_batch.py` (in `npm run lint`) fails when a
  decision record cited by number in `rtl/` or `src/` is neither `Ratified`
  nor listed below, when any `Proposed` record is missing from the table, or
  when a recommendation is not one of the three words above. It does not
  check that the prose in the cells is true; the reviewer does.
* Dependencies between records matter for the order of the act: DR 0012
  before DRs 0013, 0015 and 0020; DR 0017 before DRs 0018 and 0020; DR 0005
  before DR 0007.

## Decision records

| Item | Status today | Shipped design depends on it | Last dated note | Open blockers | Recommendation |
|---|---|---|---|---|---|
| DR 0005 | Proposed 2026-09-25 | `rtl/protocol_program_memory.v` is backed by the PDK `RM_IHPSG13_1P_256x16_c2_bm_bist` SRAM macro (`rtl/vendor/`), with DR 0005's fetch-ahead; `src/config.json` carries the macro configuration. Rows 6 and 7 name it as the reason they are unmet | 2026-10-09 (pointer, issue #129) | #261, #265 (A_DOUT evidence), #273 (tiles, row 7); klayout-tools#2635 (klt leg) | ratify |
| DR 0007 | Proposed 2026-10-02 | Row 4's corner set under the macro (3 of 6 corners); no RTL. Row 4 has no ratified corner set without it | 2026-10-11 (issue #85, item 4) | klayout-tools#2635 (klt has timing evidence for 0 of 6 corners); #20; its open items 1 and 2 (fast-corner hold path, shuttle core supply) are unanswered in the record | amend first |
| DR 0008 | Proposed 2026-10-03 | Cited only in `src/tt_um_2amlogic_protocol_emulator.v` as the synthesis-time open-drain mask "never built"; DR 0012 keeps its wired-AND semantics with the mask in a register. `verification/uio_pads.py` and `verification/test_firmware_i2c.py` cite it | 2026-10-09 (issue #133) | none | amend first |
| DR 0010 | Proposed 2026-10-09 | `scripts/check_protocol_pin_roles.py` (in `npm run lint`) holds the pin roles in the record to the firmware; firmware headers and `info.yaml`'s pinout comments cite it | 2026-10-11 | none | ratify |
| DR 0011 | Proposed baseline 2026-10-09 | Nothing shipped: hand-counted current-ISA USB-LS and 10BASE-T baselines, no verdict (DR 0015 gives it). Cited in `docs/info.md` and by row 2's deferral | 2026-10-09 | none | defer |
| DR 0012 | Proposed 2026-10-09 | Control space, runtime `uio` direction and program-memory access are in `rtl/protocol_core.v`, `rtl/protocol_program_memory.v` and the top (`src/tt_um_2amlogic_protocol_emulator.v`); row 5 and DR 0001's ratified run-time `uio` amendment rest on it | 2026-10-10 | none | ratify |
| DR 0013 | Proposed 2026-10-09 | Serial-load CRC readout and the boot ROM (`rtl/protocol_boot_rom.v`, UART load, SPI-flash boot, verified warm start) are in RTL; row 14 (c) rests on it. Depends on DR 0012 | 2026-10-11 (issue #211) | none | ratify |
| DR 0014 | Proposed 2026-10-09 | No RTL. `src/config.json` cites its 60 % utilization target in a comment; its tile recommendation (keep 2x2) is the question #273 puts to the organizers | 2026-10-09 | #273 | amend first |
| DR 0015 | Proposed 2026-10-09 | Primitives P1 (CRC / LFSR) and P2 (NRZI + bit stuffing) are in `rtl/protocol_core.v` (control indices 0x10-0x19). Its low-speed USB TX and 10BASE-T parts have no RTL or firmware. Depends on DR 0012 | 2026-10-10 (issue #208) | none | amend first |
| DR 0016 | Proposed 2026-10-10 | Four flag and shift details (`SUB` borrow, `SHF` and `Z`, logic ops and `C`, `SHF` fill) as the RTL already behaves; `verification/test_isa_lockstep.py` and the ISA model check them; DR 0001 already relies on them | 2026-10-10 | none | ratify |
| DR 0017 | Proposed 2026-10-10 | `spec/isa-freeze.json` pins the ISA files and `scripts/check_isa_freeze.py` (in `npm run lint`) enforces it; DRs 0018 and 0020 act under its change control | 2026-10-11 (issue #44) | none | ratify |
| DR 0018 | Proposed 2026-10-10 | Row 13's protocol choice (WS2812): `firmware/asm/ws2812.asm`, its reference model and RTL and gate-level benches; its 2026-10-11 note names the PS/2 device (`firmware/asm/ps2_device.asm`). Depends on DR 0017 | 2026-10-11 (issue #235) | none | ratify |
| DR 0020 | Proposed 2026-10-11 | The top ties an open-drain pin's pad data low (`src/tt_um_2amlogic_protocol_emulator.v`, issue #244), a conformance fix to DR 0012 under DR 0017 section 4 | 2026-10-11 | none | ratify |

DRs 0006 and 0009 are `Recorded` (a finding and an act record, not decisions)
and need no key. DR 0019 does not exist in `spec/decision-records/`.

## Rows

| Item | Status today | Shipped design depends on it | Last dated note | Open blockers | Recommendation |
|---|---|---|---|---|---|
| row 13 | Not in DR 0004's register; digest state `proposed`, gap state "Not started" in the row's State cell (the cell's evidence notes are what the digest reads) | WS2812 firmware passes its independent model at RTL and on the LibreLane netlist, zero-delay; the PS/2 device is the stretch column. Rests on DRs 0017 and 0018, and on DR 0012 for the pixel table read | 2026-10-11 (DR 0018 note, issue #235) | none | ratify |
| row 14 | Not in DR 0004's register; digest state `proposed` | Reset coverage and reselect pass on the LibreLane netlist, zero-delay; (c) rests on DR 0013. Not covered: reset release under real delays, the pads | 2026-10-10 (issue #140, PR #188) | #300 (rst_n release timing) | ratify |

Ratifying a row binds its target text; it does not make the row met. Both rows
stay `unmet` or `proposed` in the tracker's evidence column until their
measurements say otherwise.
