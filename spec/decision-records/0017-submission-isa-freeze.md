# 0017: Submission ISA Freeze

Status: **Proposed 2026-10-10.** It goes to ratification through the
two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"). That mechanism has never
run in this repository (DR [`0006`](0006-two-key-ratification-never-ran.md),
issue #44), so this record is a proposal, like DRs 0001–0005, 0007, 0008 and
0010–0016. It changes no RTL, firmware or reference model, edits no
target-spec value, relaxes nothing ratified or proposed and makes no row met.
Its enforcement check (below) runs from the moment it merges, whatever its
status. That is a lint on this repository's own files, not a ratified rule.
Date: 2026-10-10
Issues: #141 (this record is part 1; part 2 chooses and builds row 13's
protocol); #135 (control space, built); #130 and #208 (DR 0015's primitives,
built); #44 (ratification).

**Numbering note.** When this record was numbered (2026-10-10), `origin/main`
had DRs 0001–0008 and 0010–0016, and open draft PR #84 reserved 0009. This
record is 0017.

## Context

Target-spec row 13 (added 2026-10-09 after the organizers' entrant update,
issue #129) asks for at least one protocol that is not in rows 1–2 and "was
not considered when the ISA was designed", built as firmware only and graded
by an independent reference model. Its last sentence is the reason for this
record: "The choice is recorded *after* the ISA is frozen for submission, so
it cannot shape the ISA." `spec/verification-plan.md` §7 adds that "the
record states the freeze commit, so the evidence cannot have shaped the
ISA."

Issue #141 held the freeze until two things landed. Both have:

- **#135, the control space.** DR [`0012`](0012-control-space-and-runtime-pin-direction.md)
  is built in `rtl/protocol_core.v` and `rtl/protocol_program_memory.v`, with
  the runtime pin-mode logic in the top.
- **#130's verdict, DR [`0015`](0015-stretch-protocols-with-neutral-primitives.md).**
  It admits P1 (CRC/LFSR step) and P2 (NRZI + bit stuffing). Issue #208 built
  both (PR #212) at control indices `0x10`–`0x19`, recorded as dated notes in
  DR 0012 and DR 0015. `0x1A`–`0x1F` stay unassigned.

A freeze that is only a sentence ("the ISA is frozen at commit X") cannot be
checked by a reviewer of the row-13 evidence. They would have to diff every
relevant file between X and the evidence commit themselves, and a quiet edit
to the assembler or to an RTL corner case would not show up. So this record
names the files, pins each by its sha256, and adds a lint that fails when one
changes without a later record saying why.

## Decision (proposed)

### 1. The freeze commit

- **Base:** `e74d2b656de35e492e6f7b3e34cbe2266b4aeff3`, the `main` commit
  this record's PR branches from (merge of PR #167).
- **Takes effect:** at the merge commit of the PR that adds this record
  (issue #141, part 1). This PR edits none of the pinned files, so every
  pinned file at that merge commit is byte-identical to the base. The check
  verifies this: it re-derives each pin from the base commit, and it hashes
  the working tree, so a merge in which `main` had meanwhile changed a pinned
  file fails until the pins are taken from the new base.
- **Row 13 is chosen after it.** The protocol, and the reasoning for the
  choice, are recorded in a later commit, after this record has merged
  (section 6).

### 2. What is frozen: the ISA as a programmer sees it

"The ISA" here is everything a program, or the person writing it, can
observe or depend on:

- every instruction's encoding, operands, effect and cycle count;
- the registers, the flags and which instructions write them;
- the four pin ports and how they map to the Tiny Tapeout pins;
- the control space: each index, its read/write semantics, its fixed latency
  and its reset value, including P1 and P2;
- the runtime pin modes (`UIO_DIR`, `UIO_OD`) and how they make `uio_oe`;
- what a loaded program observes of loading and boot: the run-phase entry
  timing, `BOOT_STATUS`, `PM_CRC`, the boot-ROM fetch until `RUN`;
- the assembly language: mnemonics, named indices, what the assembler
  accepts and refuses.

The pins. The machine-readable copy is [`spec/isa-freeze.json`](../isa-freeze.json);
`scripts/check_isa_freeze.py` fails if the two disagree.

| File | sha256 at the freeze | Why it is pinned |
|---|---|---|
| `spec/decision-records/0001-isa.md` | `2390c030e0e6981b163dd52b85e7f97ceb3e9a9e7501bafef35183b07535a039` | The opcode table, encoding, timing model, register and pin-port model, program-memory size and serial load. Its dated notes (#85 SPI, #203) are part of it |
| `spec/decision-records/0005-program-memory-implementation.md` | `66b27c41a0bfbfab19869c79ac2db8d6aacf87bfc5b6fa888da9bed0a22685ab` | Its fetch-ahead amendment to DR 0001's timing model: branches stay 1 cycle, and run-phase entry costs a fixed +1 cycle. Both are cycle counts a program sees |
| `spec/decision-records/0012-control-space-and-runtime-pin-direction.md` | `ef64a49ca3b5982bf0844b60fa8aea3b335c314cbad7d40d9c295dd8c27ff51f` | `WCTL`/`RCTL`, the register map with per-index latency, the P1/P2 index-map note, pin modes, reset values, and the table of points the first build chose |
| `spec/decision-records/0013-program-loading.md` | `9e93b04d93ca5978faeea51ed8cb4a018d3c0035d33d2f14b788f3ef5eec98fa` | The firmware-visible boot interface: `BOOT_STATUS` bits, fetch from the boot ROM until `RUN`, the state a loaded program starts in, and the layer-1 `PM_CRC` readout on `uo_out`. The record is pinned whole (section 3 says why) |
| `spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md` | `725da38e25af06f7bf35616498a1875973b943a7881a537cbb1618ca8e636a5c` | P1 and P2's interface and the index-map note. Its tables also define row 13's exclusions (section 6), so they must not move after the freeze either |
| `spec/decision-records/0016-isa-flag-and-shift-details.md` | `a5dad34d57044e247b657c42509e75a6f33f3da3fce1109460ac478c5679f620` | `SUB` sets `C` as a borrow, `SHF` leaves `Z`, the logic ops leave `C`, `SHF` fills with 0 |
| `rtl/protocol_core.v` | `d4bab243a80af56a41b8ef730bc0ecbee889f2c02f4587311d6f9f694636437a` | The core: decode, datapath, flags, ports, the `WCTL`/`RCTL` decode and registers, the P1/P2 primitives, and the boot-ROM fetch select |
| `rtl/protocol_program_memory.v` | `2b08865ab24d6bac84b390dfa76bab6686b572ba8f19124130bfc34e93dff637` | Implements control-space behaviour: the `PM_DATA_*` port arbitration and its fixed one-cycle stall, `PM_CRC`, `BOOT_STATUS[0]`, and the serial load phase |
| `src/tt_um_2amlogic_protocol_emulator.v` | `3ac55ab264ff4c859b8f9aa852b31eb303d57327bed49e63bb12a68c5680975a` | Wires DR 0001's port table to the pins, holds the `UIO_DIR`/`UIO_OD` pin-mode logic that makes `uio_oe`, and the load-phase `PM_CRC` mux on `uo_out`. All three are pin behaviour a program sees |
| `firmware/tools/asm.py` | `4c77c41b05c94ffbac1b92ca8beadcc96d9c614f67359d5abdcbb7e98f157bc8` | The assembly language a program is written in: mnemonics, named control indices, encodings, the reserved-encoding refusals |
| `verification/reference_models/isa.py` | `7f9addaa7e5593a878de72671e2d8efd932628fe2e8799696810b6c25f60e84c` | The independent, executable statement of the ISA that the lockstep bench grades the RTL against. If it could move freely, the RTL check would move with it |

`src/protocol_core.v` and `src/protocol_program_memory.v` are symlinks to
the `rtl/` files (`rtl/README.md`), so the `rtl/` paths are pinned. The check
refuses a symlink as a pin.

### 3. What is not pinned, and why

| Not pinned | Why |
|---|---|
| The boot ROM's content: `firmware/asm/boot/boot_rom.asm`, its `.hex`, and `rtl/protocol_boot_rom.v` (generated from the `.hex`) | It is firmware written in the ISA, not the ISA. Its UART frame and its SPI-flash read are protocols that run on the core, exactly as row 13's program will. What a loaded program can observe of the boot (the `RUN` hand-over, `BOOT_STATUS`, fetch from ROM until `RUN`) is pinned through DR 0013 and `rtl/protocol_core.v`. Issue #211 (the UART frame's count byte, DR 0013 finding F8) is a change of this kind |
| Every other committed program under `firmware/asm/` and `firmware/build/` | Firmware is the evidence, not the ISA |
| `firmware/tools/gen_boot_rom.py`, `loadseq.py`, `mkflash.py`, `check_firmware.py` | Host and build tooling. They produce or check images; they do not define what an instruction does |
| DR 0003 (firmware toolchain) | It fixes the shape of the toolchain (a hand-written assembler, committed images). The language itself is pinned through `asm.py` |
| DR 0008 and DR 0010 | DR 0008's synthesis-time open-drain mask was never built, and DR 0012 replaces it; what survives of both is pin-role conventions that firmware follows. A different pin plan is a firmware choice |
| DRs 0002, 0004, 0006, 0007, 0011, 0014 | Flow, ratification, corner set, a feasibility baseline and area. None defines what an instruction does |
| `spec/target-spec.md` and `spec/gap-to-submission.md` | Living tables whose evidence columns change with every record. Row 3's guarantee (no data-dependent latency) is stated in DR 0001, which is pinned |
| The benches and the formal property files (`verification/test_*.py`, `verification/formal/`) | They check the ISA; they do not define it. A change to them changes the evidence, and the evidence has its own append-only rules (`verification/README.md`) |
| `info.yaml`, `docs/info.md`, `src/config.json`, `src/pdn_cfg.tcl`, `rtl/vendor/` | Descriptions of the design, physical-flow configuration, and the PDK's SRAM macro models. None is a choice a program can see |

**Why pinned DRs are pinned whole.** DR 0013 in particular carries long
implementation notes beyond the interface, and a dated note added later
changes the file's hash. Hashing only a section was considered and rejected:
dated notes are inserted inside sections (DR 0012's index-map note sits under
its register table), so section boundaries are not stable, and a section hash
would let a note change the interface while the check stays green. The cost
is that any edit to a pinned record, including a note that changes nothing a
program sees, needs an amendment. Section 4 keeps that cheap.

### 4. Change control after the freeze

1. **Every change to a pinned file needs an amendment.** The amendment is an
   entry appended to `amendments` in `spec/isa-freeze.json` that cites a
   decision record numbered **0018 or later**. The record must exist, must
   not itself be pinned, and must name the changed path. One record may cover
   several amendments. Pins are never edited; the entry carries
   `sha256_before` and `sha256_after`, and entries for one path form a
   chain.
2. **Each amendment says what kind of change it is** (`kind`):
   - `isa-change`: the ISA-visible behaviour changes (a new or removed
     instruction or control index, a changed latency, flag, reset value or
     assembler rule). It needs a record that decides the change, as any
     spec change does.
   - `conformance-fix`: the RTL, the reference model or the assembler is
     brought into line with the frozen records. This is allowed, and is not
     an ISA change, but the record must say it is one and name the frozen
     text the old behaviour broke. The precedence for "in line with" is the
     pinned records first, then `isa.py`, then the RTL. DR 0016's
     Consequences already rule that an RTL change to a ruled detail is a
     defect.
   - `no-behaviour-change`: nothing a program can observe changes (a comment,
     a dated note, a refactor that keeps every cycle and bit, a Status line
     flipped by ratification). The record says why, and it may be short.
3. **Each amendment says whether it invalidates row-13 evidence**
   (`invalidates_row13_evidence`, true or false, never omitted), and the
   record gives the reason. An `isa-change` made after row 13's protocol is
   chosen either invalidates that evidence or says why the protocol's program
   does not observe it. A `conformance-fix` invalidates it if the row-13
   program ran on the behaviour being fixed.
4. **Ratification is a hash change too.** When the two-key act flips a pinned
   record's Status line (draft PR #84 would do this for DR 0001), the act's
   PR adds a `no-behaviour-change` amendment citing a record numbered 0018 or
   later. PR #84 reserves 0009 for its act record; if it lands after this
   freeze, it needs that amendment as well (Open items).

### 5. Enforcement

`scripts/check_isa_freeze.py`, run by `npm run lint` with its self-test
`scripts/test_check_isa_freeze.py`. It fails when:

- a pinned file's sha256 differs from its expected hash (the pin, or the last
  amendment's `sha256_after`);
- a pinned path is untracked, missing, or a symlink;
- an amendment cites a record below 0018, a record that does not exist or is
  pinned, or one that does not name the path; breaks its path's chain; or
  leaves out `kind` or `invalidates_row13_evidence`;
- this record's pin table and the manifest disagree on any path or hash;
- a pin differs from the file at the freeze base commit. If that commit is
  not in the clone (a shallow checkout), the check prints a NOTE and skips
  only this step.

It hashes the working tree, needs only the standard library and `git`, and
never rewrites anything.

### 6. Row 13: how the protocol is chosen

- **When.** The row-13 protocol, and the reasoning for choosing it, are
  recorded in a commit after this record has merged, and that record cites
  this record's merge commit as the freeze. Nothing in this record chooses
  it.
- **What it must not be.** Row 13's primary protocol must not be any
  protocol named in DR 0015's tables. DR 0015's "Interaction with other
  records and rows" says why: those protocols were weighed against the ISA's
  primitives, "whether or not the primitive they were weighed against was
  admitted". DR 0015 also marks its prose lists for P2 and P4 "ineligible as
  row 13 evidence", so those are excluded too. The protocols are:
  - DR 0015's P1 table: USB (CRC5, CRC16); Ethernet (CRC-32); the
    CRC-16/XMODEM load check of DR 0013; 1-Wire (CRC8); SMBus (PEC);
    Modbus RTU; HDLC, PPP; SD (CRC7, CRC16); CAN (CRC15); BLE (CRC24 and
    data whitening).
  - DR 0015's P2 list: USB, HDLC/PPP/SDLC, CAN, NRZI-coded links in general.
  - DR 0015's P3 table and prose: 10BASE-T and the other 802.3 Manchester
    PHYs (10BASE5, 10BASE2); RC-5/RC-6 infrared (DR 0015 says this removes
    Manchester/IR from row 13's list); DALI; MIL-STD-1553.
  - DR 0015's P4 list: USB receive, 10BASE-T receive, RC-5 receive,
    DMX512, LIN, CAN receive, 1-Wire slot sampling, UART receive.
  - DR 0015's baseline, result and verdict tables: low-speed USB TX/RX and
    10BASE-T TX/RX.

  Rows 1–2's protocols (UART, SPI controller, I2C controller, USB, 10BASE-T)
  are excluded by row 13's own text. Of row 13's four listed candidates,
  1-Wire, DMX512 and Manchester/IR are therefore out. This record does not
  say which protocol to choose.
- **Also excluded: protocols the ISA records were designed around.** Row 13
  asks for a protocol "not considered when the ISA was designed". Three
  pinned records name protocols as reasons for their design: DR 0012's
  Context motivates runtime pin direction with 1-Wire, a target-role SPI and
  a QSPI flash on the Tiny Tapeout QSPI Pmod; DR 0013 builds a UART load
  frame and a single-bit SPI flash read (`0x03`), and its Open item 2 names
  I2C-target and SPI-target loads as "good row-13 demonstrations". So none
  of these may be row 13's **primary** protocol either. Row 13's **stretch**
  column is a different claim: it asks for a role or pin direction the core
  protocols never use and names target-role SPI or I2C and 1-Wire as
  examples. This record leaves that column as written. A stretch built on one
  of these protocols is evidence for the stretch only and cannot also count
  as the primary.
- The list is also in `spec/isa-freeze.json` (`row13_excluded_protocols`), so
  part 2 can check its choice against it.

## Alternatives considered

1. **A git tag or a sentence naming the commit, with no check.** It is
   cheapest, and it is what row 13's text literally asks for. Rejected as the
   only mechanism: nothing would notice a later edit to a pinned file, so a
   reviewer of the row-13 evidence would have to diff the tree themselves.
   The commit is still recorded (section 1).
2. **Pin the whole tree, or every file under `rtl/`, `spec/` and
   `firmware/`.** It is simpler to state and catches more. Rejected: firmware,
   evidence and living spec tables change daily for reasons unrelated to the
   ISA, so every PR would need an amendment, and amendments would become
   noise that hides the ones that matter.
3. **Pin sections of the records, not whole files.** Rejected in section 3:
   section boundaries are not stable under dated notes, and a section hash
   can miss an interface change.
4. **Freeze by ratification.** Ratifying DRs 0001, 0012, 0013, 0015 and 0016
   would bind their content, but it is not available: the two-key mechanism
   has never run (issue #44), and ratification binds text, not the RTL or the
   assembler. The freeze does not wait for it, and it does not replace it
   (Consequences).
5. **Drop part of P1 first** (`CRC_BYTE`, the readbacks or the variable
   width), which issue #141's 2026-10-10 comment raises because P1 and P2
   cost 2.4–2.9 times DR 0015's area estimate. Not done here. DR 0015's dated
   note evaluates its reopening condition 4 and keeps the full interface, at
   57.17 % placed utilization against the 60 % target. Making P1 smaller after
   this freeze is an `isa-change` amendment, and its record must say whether
   it invalidates row-13 evidence.

## Consequences

- From this record's merge, `npm run lint` fails on any unamended change to
  the eleven pinned files. CI runs the same lint.
- Row 13's protocol can be chosen, in a later commit that cites this
  record's merge commit (issue #141, part 2).
- **The freeze fixes content, not status.** DRs 0001, 0005, 0012, 0013,
  0015 and 0016 stay Proposed until the two-key act runs (#44). If a
  ratifying review changes any of them, that change is an `isa-change`
  amendment like any other, and row-13 evidence is re-judged against it.
- Behaviour that a pinned record leaves as a proposal is frozen as built.
  DR 0012's Open items (`RCTL` of `UIO_*` returns the register value; `RUN`
  is allowed outside the boot ROM) and its table of first-build points are
  frozen as the RTL implements them.
- Every DR or RTL change after the freeze that touches a pinned file costs a
  short record. That is the point: such changes should be rare and visible.

## Open items

1. **Draft PR #84 (two-key act, DR 0009).** It edits DR 0001's Status line.
   If it merges after this record, it needs a `no-behaviour-change`
   amendment citing a record numbered 0018 or later (section 4, item 4). It
   is a draft and conflicts with `main` today.
2. **Issue #211 (DR 0013 finding F8).** Its fix changes the boot ROM's UART
   frame. The ROM is not pinned, but any note it adds to DR 0013 is a
   `no-behaviour-change` amendment unless it changes what a loaded program
   observes.
