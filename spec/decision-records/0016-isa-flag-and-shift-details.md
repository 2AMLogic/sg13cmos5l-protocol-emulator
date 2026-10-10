# 0016: Four ISA Details DR 0001 Leaves Open — `SUB`'s `C` Polarity, `SHF` and `Z`, Logic Ops and `C`, the `SHF` Fill Bit

Status: **Proposed 2026-10-10.** It goes to ratification through the
two-key (`RATIFY-KEY`) mechanism on the PR that carries it (`spec/README.md`,
"How ratification works here"). That mechanism has never run in this
repository (DR [`0006`](0006-two-key-ratification-never-ran.md), issue #44),
so this record is a proposal, like DRs 0001–0005, 0007, 0008 and 0010–0015.
It changes no RTL, edits no target-spec value, relaxes nothing ratified or
proposed and makes no row met.
Date: 2026-10-10
Issues: #203 (this decision); #152 (the ISA lockstep work that named the four
details); #44 (ratification).

**Numbering note.** When this record was numbered (2026-10-10), `origin/main`
had DRs 0001–0008 and 0010–0015, and open PR #84 reserved 0009. This record
is 0016.

**Why a new record and not an edit of DR 0001.** `spec/README.md` routes
every spec change through a decision record, and the precedent for adding to
DR 0001 is a new record plus a dated pointer note: DR 0012 added the control
space and DR 0013 the loader that way, and DR 0001 keeps its own text. DR
0001 is also the review object of the pending two-key ceremony (PR #84), so
its decided text is left as written. DR 0001 gets one dated note that points
here. This record **adds** definitions where DR 0001 is silent or ambiguous;
it does not change anything DR 0001 states.

## Context

The independent ISA reference simulator
(`verification/reference_models/isa.py`, issue #152) was written from DR
0001 and DR 0012 and compared with the core on every clock edge. It found no
disagreement between the RTL and the records. It did have to name four
choices that DR 0001 does not make. The model carried the RTL's choice for
each one, labelled as an open detail (`isa.OPEN_DETAILS`) rather than
silently matched:

1. **`SUB`'s `C` polarity.** DR 0001's opcode table says `SUB` "sets `Z`,
   `C`" and nothing more. `rtl/protocol_core.v` sets `C` as a borrow.
2. **`SHF` and `Z`.** DR 0001's prose says the flag register is "written by
   `ADD`, `SUB`, `AND`, `OR`, `XOR`, and `SHF`". Its opcode table gives `SHF`
   only "shifted-out bit -> `C`". The RTL leaves `Z` unchanged.
3. **`AND`/`OR`/`XOR` and `C`.** The table says "sets `Z`" only. The RTL
   leaves `C` unchanged.
4. **The `SHF` fill bit.** DR 0001 does not name it. The RTL shifts in 0. A
   dated note in DR 0001 (2026-10-10, issue #85) already relies on that.

While these stay open, the lockstep bench can only say "the RTL changed",
not "the RTL is wrong". Row 13 (#141) and the stretch-protocol primitives
(#130, DR 0015) will run new firmware on a frozen ISA, so the record has to
say which behaviour is intended.

For each detail the choice is one of two: **this is the behaviour**, or
**unspecified; firmware must not depend on it**. "Unspecified" would let a
later RTL change pass the bench by relabelling it. That only makes sense
for a detail nothing observes and nothing is ever likely to observe. None of
the four qualifies. Details 2 and 4 are already relied on by committed
firmware. Detail 3 decides whether a shifted-out bit survives a mask. Detail 1
is the definition any later instruction that reads `C` would inherit. So
all four are ruled as behaviour.

## Decision (proposed)

Notation: `Rd` and `Rs` are the register values **before** the instruction;
the 9-bit forms are `{0, Rd} + {0, Rs}` and `{0, Rd} - {0, Rs}`.

### Ruling 1 — `SUB` sets `C` as a borrow

**`SUB Rd, Rs` sets `C = 1` exactly when `Rd < Rs` as unsigned 8-bit
values**, i.e. when the subtraction borrows. Equivalently, `C` is bit 8 of
the 9-bit difference `{0, Rd} - {0, Rs}`. `Z = 1` exactly when the 8-bit
result is 0, as DR 0001 already says.

For completeness: `ADD`'s `C` is bit 8 of the 9-bit sum (the carry out),
which DR 0001's "carry" already names. It is restated here only so that both
definitions sit in one place.

Why borrow, and not the inverse ("carry = NOT borrow", as on the 6502 and
ARM):

- **It is what the arithmetic produces.** The 9-bit subtract's MSB is the
  borrow, with no inverter. The RTL takes `C` from that bit
  (`flag_c <= sub_diff[8]`), and the model has always pinned the same choice.
- **One meaning of `C` across both arithmetic ops.** With borrow polarity,
  `C = 1` after `ADD` or `SUB` means the same thing: the true unsigned
  result left the range 0–255 (above it for `ADD`, below it for `SUB`). That
  is the reading a later branch-on-carry would want for a range or
  comparison test.
- **The 6502 reason does not apply here.** The 6502 inverts the borrow
  because its `SBC` is built as `ADC` of the complement with the carry fed
  in, so "carry set" has to mean "no borrow" for multi-byte chains to work.
  This ISA has no carry-in and no add- or subtract-with-carry. No chain
  needs the inversion. (x86, the 8080/Z80 and AVR also set `C` on a
  borrow, so this is not an unusual convention.)
- **Nothing depends on the other polarity.** No instruction reads `C` today
  (`BZ`/`BNZ` read `Z`), so no committed program can observe the polarity.
  Fixing it now costs nothing and closes the question before something can
  depend on it.

**Consequence for later revisions.** Any later instruction that reads `C`
(a branch on carry, a shift or rotate through carry, an add- or
subtract-with-carry) **uses this definition**. A revision that wants the
inverse polarity supersedes this ruling in its own decision record, and the
RTL, the ISS table and this record change in the same PR.

### Ruling 2 — `SHF` leaves `Z` unchanged

**`SHF` writes `C` (the shifted-out bit) and does not write `Z`.**

Why:

- **The table is the specific statement.** DR 0001's prose sentence is about
  the 2-bit flag register as a whole. `SHF` satisfies it by writing `C`. The
  opcode table says per instruction which flags each one sets, and for `SHF`
  it names only `C`. Where the two differ, this record follows the table.
- **Committed firmware relies on it.** `firmware/asm/uart_rx.asm`,
  `uart_rx_115200.asm` and `uart_rx_9600.asm` compute the framing-error bit
  with `XOR`, move it with `SHF ... LEFT` ("SHF leaves Z alone"), and then
  `BZ` on the `Z` the `XOR` set. The boot ROM's hand-over to a loaded image
  (`firmware/asm/boot/boot_rom.asm`, `run_image`) sets `Z = 0` with
  `OR R3, R3`, then clears `C` with `SHF` of a zero register. If `SHF`
  wrote `Z`, that shift of 0x00 would set `Z = 1` and break the
  reset-equivalent state the ROM promises.
- **It costs firmware little.** A program that wants `Z` from a shifted
  value adds `OR Rd, Rd` (1 cycle, `Rd` unchanged, sets `Z`).

### Ruling 3 — `AND`, `OR` and `XOR` leave `C` unchanged

**`AND`, `OR` and `XOR` write `Z` and do not write `C`.**

Why:

- **It is what the table says.** "Sets `Z`" is a complete list for these
  three. Nothing in DR 0001 says they touch `C`.
- **It keeps a shifted-out bit alive across a mask.** The usual pattern
  shifts a bit out into `C` and then masks or merges with the logic ops.
  Clearing `C` on a logic op (as x86 does) would destroy that bit before a
  later carry-reading instruction could use it. It would also add logic and
  change the RTL, which this issue does not do.
- No instruction reads `C` today, so no committed program observes this. It
  is defined anyway so that a later instruction that reads `C` inherits a
  definition, not a guess (Ruling 1, "Consequence for later revisions").

### Ruling 4 — `SHF` fills the vacated bit with 0

**`SHF` is a logical shift in both directions: a right shift moves 0 into
bit 7, a left shift moves 0 into bit 0.** The shifted-out bit goes to `C`
(DR 0001). It is not an arithmetic (sign-fill) shift, a rotate, or a shift
through carry.

Why:

- **DR 0001 already relies on it.** The 2026-10-10 dated note (issue #85)
  explains why the SPI sketch cannot be written with the real `SHF`, and
  states that the core fills with 0.
- **Committed firmware relies on it.** The SPI full-duplex loops
  (`firmware/asm/spi_mode{0..3}.asm`) and the boot ROM's SPI reader shift an
  accumulator left and `OR` the received bit into bit 0, and the UART
  receivers shift right to "make room at bit 7" before an `OR`. Both need a
  0 in the vacated bit.
- **The alternatives are new behaviour, not readings of DR 0001.** This ISA
  has no signed arithmetic, so a sign-fill right shift has no use. A shift
  that fills from `C` (or merges a sampled bit) is exactly the "shift that
  merges a bit" DR 0001's dated note names as a question for a new decision
  record. It would be a new instruction, not a definition of `SHF`.

### What this record does not decide

- No instruction that reads `C` is added. Ruling 1 fixes the meaning any
  such instruction would use; whether to add one is a separate decision
  (DR 0001's dated note and DR 0015 hold the related questions).
- No RTL or ISS behaviour changes. All four rulings describe what
  `rtl/protocol_core.v` and `verification/reference_models/isa.py` already
  do.

## Alternatives considered

1. **Mark all four "unspecified; firmware must not depend on it".**
   Rejected. Committed firmware already depends on rulings 2 and 4, so
   "must not depend" would make those programs non-conforming. For rulings 1
   and 3 it would let a later RTL change slip through the lockstep bench as
   "unspecified", which is the gap issue #203 was filed to close.
2. **Carry polarity for `SUB` (`C = 1` when no borrow, 6502/ARM style).**
   Rejected (Ruling 1): it needs an inverter for no benefit in an ISA with no
   carry chain, and it gives `C` different meanings after `ADD` and `SUB`.
3. **`SHF` sets `Z` from its result (reading DR 0001's prose literally).**
   Rejected (Ruling 2): it breaks three committed UART receivers and the
   boot ROM's hand-over, for a convenience firmware can get from one `OR`.
4. **Logic ops clear `C`.** Rejected (Ruling 3): it loses a shifted-out bit
   across a mask and changes the RTL.

## Consequences

- With this record ratified, all four become ISA behaviour. An RTL change to
  any of them is a defect unless a superseding decision record changes the
  ruling, and the RTL, the ISS table and that record change together in one
  PR.
- **How it is checked.** `verification/test_isa_lockstep.py` compares `Z`
  and `C` (white-box, RTL only) with the ISS on every edge of 400 seeded
  programs; `test_sub_carry_polarity_pin` checks Ruling 1 on its own. The
  generator's coverage gate requires `SUB` with borrow 0 and 1 and `SHF` in
  both directions with shifted-out bit 0 and 1.
  `verification/isa_lockstep_mutants.py` gives each ruling at least one
  single-defect copy of the core that the bench must catch: SUB carry
  polarity flipped (Ruling 1), `SHF` writes `Z` (Ruling 2), `AND` clears
  `C` (Ruling 3), and `SHF` fills from `C` (Ruling 4).
- **Until ratification (issue #44)** these are proposed behaviour, like the
  rest of DR 0001. The model's labels (`isa.OPEN_DETAILS`) now cite this
  record and keep saying that the rulings are proposed, so a mismatch is
  reported as a disagreement with a proposed ruling, not with a ratified
  one. Once this record is ratified the labels can say so. The bench's
  pass/fail behaviour does not depend on the labels.
- `C` remains write-only state in this ISA revision. It is observable only
  as the internal `flag_c` register. A gate-level lockstep is still deferred
  (`spec/verification-plan.md` §4.1), and synthesis may remove `flag_c`
  while nothing reads it. That does not change the rulings: they bind the
  architectural behaviour any future reader of `C` will see.
