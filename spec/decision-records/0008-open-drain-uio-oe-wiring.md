# 0008: Silicon-True Open-Drain I2C Pins — Per-Pin `uio_oe` Wiring Behind a Synthesis-Time Mask

Status: **Proposed 2026-10-03.** It goes to ratification through the
program's two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"). It binds only when that
PR's history shows **two** `RATIFY-KEY` reviews, one EE key and one market
key, neither held by this record's author, and the merge commit is the
ratification act. As
[`0006-two-key-ratification-never-ran.md`](0006-two-key-ratification-never-ran.md)
records, that mechanism has never run in this repository (issue #44), so for
now this record is a proposal, the same way DRs 0001–0005 and 0007 are
(DR 0006 is a finding of fact that binds nothing, not a proposal awaiting
keys). It does **not** make target-spec row 12 met, and nothing in it may be
cited as though it did.
Date: 2026-10-03
Issue: #75

**Numbering note.** Issue #75's curation (2026-10-02, verified against
`origin/main` @ `1ac293c`) named the deliverable "`0007-<slug>.md` (next
free number; 0001–0006 exist)". DR
[`0007-row4-corner-set-under-the-macro.md`](0007-row4-corner-set-under-the-macro.md)
(issue #69) merged after that verification, so the next free number at
filing time is **0008**. The operative instruction was "next free number";
this record follows it.

## Context

### What the I2C firmware does, and what silicon does with it

The I2C firmware (issue #73, `firmware/asm/i2c_{fast,std}.asm`) drives its
open-drain intent on `uio_out`: SCL on bit 0, SDA on bit 7, with the
open-drain convention **writing 1 releases the line (pull-up wins) and
writing 0 asserts it low**. The DUT-facing bench composes the wired-AND bus
the independent reference model grades from the two intent signals
(`line = uio_out AND uio_in`, per bit): honest for firmware/ISA
verification, because the firmware's phase timing and protocol structure
are exactly what the committed programs claim — but **not silicon-true**,
because the top level fixes

```verilog
assign uio_oe = 8'h00;   // src/tt_um_2amlogic_protocol_emulator.v:108
```

so on silicon no firmware drive ever reaches a physical bidirectional pin:
every `uio` pad stays an input and `uio_out` is a don't-care downstream.
The evidence record
(`verification/records/firmware-i2c/records/20261002-212508-25a0237.md`,
"the open-drain bus is bench-composed" bullet) records exactly this and
names this decision record as the raise.

### DR 0001's own flagged open question

DR 0001 § ISA pins (port table, port code `11`):

> `uio_out[7:0]` / `uio_oe[7:0]` — bidirectional port; `OUT` to this port
> writes `uio_out`, direction (`uio_oe`) is fixed at synthesis time per
> protocol pin plan, not runtime-programmable in this ISA revision (see
> Consequences)

DR 0001 § Consequences:

> `uio_oe` direction is fixed per protocol at synthesis/build time (an
> `OUT` to port `11` only ever targets `uio_out`, never toggles direction
> at runtime). A future ISA revision could add a fifth port code for
> runtime `uio_oe` control if a protocol needs it (e.g., I2C's SDA line
> changing direction mid-transaction for open-drain ACK sampling really
> needs this — flagged as a real open question for the I2C firmware issue,
> not resolved here; this decision record only commits to the pin-port
> *addressing* scheme, not to every protocol's full firmware design).

`rtl/protocol_core.v`'s header carries the same contract ("the top level
fixes `uio_oe` at synthesis time"). Issue #73's scope said to raise the
open-drain gap explicitly rather than work around it silently; this record
is that raise.

### Constraints any option must respect

- **The Tiny Tapeout pin budget** (target-spec row 5, ratified [DR-4]):
  8 dedicated inputs, 8 dedicated outputs, 8 bidirectional — fixed by the
  template, not negotiable. Whichever pins the still-open **pin-role
  decision record** assigns to I2C, the firmware's current
  `uio[0] = SCL` / `uio[7] = SDA` is a *program-level* plan only.
- **Cycle-exact timing is the product** (DR 0001's timing-determinism
  guarantee): the choice is wiring, not timing. Any option that adds a
  cycle, or makes latency data-dependent, is unacceptable.
- **The ISA is the product** (`CLAUDE.md`): no fixed-function I2C
  peripheral. Whatever is chosen, UART/SPI/I2C stay firmware.
- **Two flows, one record of truth** (`CLAUDE.md`): no synthesis or timing
  number is claimed by this record — none was measured for it. The
  follow-up that changes RTL measures on the flow of record (DR 0002) and
  reports flow-attributed.
- **Agents do not relax the ratified spec** (`CLAUDE.md`): this record
  changes no spec row's target and closes no row; it proposes a mechanism.

## What is being decided — and what is not

Decided here: **the mechanism** by which `uio_oe` is driven for open-drain
protocol pins, and the recommendation the operator is asked to ratify.

Explicitly **not** decided here:

1. **The mask's value** (which physical pins are SCL/SDA). That belongs to
   the pin-role decision record target-spec row 5 already names as "a later
   decision record". This record defines the mechanism that record
   instantiates.
2. **The RTL change.** `assign uio_oe = 8'h00` is a follow-up issue opened
   *after* ratification, per this repo's rules — nothing in this record's
   PR touches `src/`, `rtl/`, or `firmware/`.
3. **The firmware.** The committed I2C programs already write the right
   levels under the open-drain convention; that is the point. No `.asm`
   changes.
4. **Existing records.** DR 0001 is not edited; this record is the
   "flagged as a real open question" resolution path DR 0001 itself
   anticipated, and DR 0001's status (`Proposed`, DR 0006/#44) is unchanged.

## Decision (proposed)

**Option 1: per-pin combinational open-drain wiring behind a
synthesis-time per-pin mask. No ISA change.**

For each `uio` pin, the pin-role record assigns exactly one of three
roles, and `uio_oe` is driven combinationally from the role and the
existing `uio_out` output register:

| Pin role | `uio_oe[pin]` | Meaning |
|---|---|---|
| open-drain | `~uio_out[pin]` | writing 0 asserts low (pad drives); writing 1 releases (hi-Z, external pull-up wins) — wired-AND semantics |
| push-pull | `1` | pad drives both levels (never hi-Z) — for any future push-pull protocol assigned to `uio` |
| unused / input | `0` | pad stays an input, exactly as today |

Illustrative shape (the actual RTL edit is the post-ratification
follow-up, not this PR):

```verilog
// per-pin roles, fixed at synthesis time by the pin-role decision record
// (target-spec row 5). open-drain emulation: masked pins assert low when
// the firmware writes 0 and release to hi-Z when it writes 1.
assign uio_oe = ({8{PUSH_PULL_MASK}}) | (OPEN_DRAIN_MASK & ~uio_out);
```

Properties of this choice:

- **Per-pin, never blanket.** A blanket `uio_oe = ~uio_out` would force
  *every* bidirectional pin open-drain: any push-pull protocol assigned to
  `uio` (UART TX, SPI SCLK/MOSI/CS if a pin-role record ever put them
  there) would lose its driven-high level (hi-Z on a written 1), and
  unused pins would become level-dependent drivers for no benefit. The
  mask keeps push-pull pins at `oe = 1`, open-drain pins at
  `oe = ~uio_out[pin]`, and everything else an input. Today's committed
  UART/SPI firmware is unaffected regardless: it drives `uo_out` (UART TX
  on `uo_out[0]`; SPI CS/SCLK/MOSI on `uo_out[0..2]`) and reads `uio_in`
  (SPI MISO on `uio_in[0]`) — no `uio` output is used by any non-I2C
  program, so the I2C mask bits are the only non-zero legs.
- **Synthesis-time mapping, runtime level.** Which pins carry which role
  is a build-time constant (the mask); the asserted/released level is the
  firmware's runtime data, which is exactly what open-drain *is*.
- **No ISA change.** `OUT` to port `11` still only ever writes `uio_out`;
  `IN` from port `01` still samples `uio_in`. The instruction encoding,
  opcode set, and DR 0001's latency table are untouched.
- **Cycle timing: unchanged by construction.** `uio_oe` becomes a
  combinational function of the *existing* `port_uio_out` output register
  — the same register, on the same retiring edge, with the same one-cycle
  pin-visibility delay. No pipeline stage, no extra cycle, no new
  data-dependent path. The post-ratification follow-up re-runs the I2C
  bench to confirm this on the flow of record rather than assuming it.
- **Conformance: full wired-AND on shared lines, silicon-true.** ACK
  sampling: the controller releases SDA (writes 1 → hi-Z), the peripheral
  asserts or the pull-up wins, and the core samples the composed line
  level through its real `IN` path — the same handshake the committed
  firmware already drives and the bench already grades. Clock stretching:
  the controller releases SCL and samples `uio_in[0]`; a stretching
  peripheral holds the line low and the firmware's sanctioned
  data-dependent branch (the ACK-wait pattern, DR 0001's one explicitly
  permitted data-dependent branch) waits it out. Neither is possible
  under `uio_oe = 0`, where the controller's drive never reaches the pad
  at all.
- **Area: a few gates.** One inverter leg and one AND leg per open-drain
  pin, zero for masked-out pins. No area or timing number is claimed here;
  the follow-up measures and records it on the flow of record per DR 0002.

### What the operator is asked to ratify

That option 1 is the adopted mechanism: per-pin `uio_oe` wiring behind a
synthesis-time mask, with the three-role table above as the contract the
pin-role record instantiates. Ratifying this record does **not** ratify
the mask value (the pin-role record's job), does not itself change RTL
(the follow-up issue's job, after ratification), and does not make
target-spec row 12 met (the follow-up's re-verification against
silicon-true `oe` semantics does, once it exists and passes).

### DR 0001 letter vs spirit, stated plainly

- **Letter: fits.** DR 0001's port table says direction "is fixed at
  synthesis time per protocol pin plan" — under option 1 the *pin plan*
  (the mask/role mapping) is fixed at synthesis time; what varies at
  runtime is the level, which DR 0001 already commits to runtime firmware
  control. The Consequences sentence "`OUT` to port `11` only ever
  targets `uio_out`, never toggles direction at runtime" is also
  satisfied: no instruction toggles direction; the pad's drive enable
  follows the level combinationally, as pull-strength wiring, not as an
  addressable ISA resource.
- **Spirit: arguable, which is why this is a decision record.** DR 0001
  clearly imagined `uio_oe` as a build-time constant and reserved runtime
  direction control for a future ISA revision (its own "fifth port code"
  suggestion). Option 1 makes the pad's *enable* a function of runtime
  data on masked pins. An operator can read that as outside DR 0001's
  intent; the ratification question is precisely whether the program
  adopts that reading. This record does not edit DR 0001; if the keys
  ratify option 1, a dated note on DR 0001 (added by the follow-up, in
  this directory's append-only style) should record that the open
  question was resolved by wiring rather than by an ISA revision.

## Options considered

Each option is evaluated against the five axes the issue names: ISA
impact, DR 0001 letter-vs-spirit, area, cycle-timing impact, and
conformance (ACK/clock-stretch receive on shared lines).

### Option 1 — per-pin combinational wiring behind a synthesis-time mask

**Proposed** (§ Decision above).

- ISA impact: none.
- DR 0001: letter fits, spirit arguable (above) — decided by ratification,
  not asserted.
- Area: a few gates on masked pins only; no number claimed.
- Cycle timing: none, by construction (same register, same edge,
  combinational enable); confirmed by the follow-up's re-run.
- Conformance: silicon-true wired-AND, ACK and clock-stretch receive work
  on shared lines.

Cost paid openly: runtime pad-enable follows firmware data on masked
pins, which DR 0001 did not enumerate; and hi-Z release requires external
pull-ups (open item 1).

### Option 2 — a fifth port code / ISA revision adding runtime `uio_oe` control

DR 0001's own suggested future revision. **Rejected for now — and
structurally gated:** DR 0001 is itself `Status: **Proposed**` and the
two-key mechanism has never run (DR 0006, issue #44). Revising an
unratified ISA compounds the governance debt rather than resolving it:
there would then be two unratified ISA generations to ratify
simultaneously, and every committed firmware image (`uart_tx`,
`spi_mode{0..3}`, `i2c_{fast,std}`) plus every evidence record keyed to
the current encoding would need re-verification against the revised one.

- ISA impact: maximal — a new addressable port means re-encoding
  instruction fields (all four 2-bit port codes are used) or widening
  them, touching the decoder and every firmware program.
- DR 0001: this is the letter's own escape hatch ("a future ISA revision
  could add a fifth port code"), so letter and spirit both fit — but the
  revision it contemplates is downstream of ratification, which has not
  happened.
- Area: a wider decoder and a new output register; strictly more than
  option 1.
- Cycle timing: an `OUT` to a direction port would cost its 1 cycle like
  any `OUT` — meaning open-drain turns would *consume instruction
  bandwidth* the cycle-exact I2C phase budgets (65/60 and 235/200 cycles,
  graded to the UM10204 floors) do not have spare, or the per-bit
  instruction streams grow past the four-register pressure the evidence
  record already documents as binding.
- Conformance: full runtime direction control on any pin — the most
  flexible option, and flexibility no ratified protocol needs: only I2C
  is open-drain.

Recorded as the fallback if a future ratified protocol genuinely needs
arbitrary runtime direction, and as the path DR 0001 itself predicted.

### Option 3 — dedicated push-pull pins only

Declare I2C emulation bench/silicon-limited to a push-pull variant on
dedicated outputs. **Rejected.**

- ISA impact: none; area: none.
- Cycle timing: none.
- Conformance: **this is where it fails.** Push-pull means the controller
  drives SDA/SCL at both levels. An open-drain peripheral's ACK (asserting
  low against a driven high) becomes electrical contention rather than a
  readable wired-AND, the controller cannot distinguish "released" from
  "driven high" so ACK sampling and clock stretching are unreadable on
  shared lines, and a stretching peripheral fights the controller's driven
  SCL. Likely insufficient for a conformant controller — the UM10204
  bus-model the reference model implements is definitionally wired-AND.
- DR 0001: neither letter nor spirit contemplates contention driving.

## Consequences

- **Firmware: unchanged.** The committed I2C programs already write
  release/assert levels under the open-drain convention; that convention
  was chosen in #73 in anticipation of exactly this decision.
- **Verification: unchanged in this PR.** The bench's wired-AND
  composition remains the honest model of the current RTL. The
  post-ratification RTL follow-up re-runs the I2C bench with the mask
  modeled, so the composed line the reference model grades matches the
  silicon's composed line, and appends its own evidence record.
- **`spec/gap-to-submission.md` row 12** gets a dated note (this PR)
  pointing here; the row stays unmet. Row 5 is **not** edited — pin-role
  assignment remains "a later decision record", which is still true; this
  record is consumed *by* that record, not a substitute for it.
- **#72 (SPI) and future pin-role records consume this as follows.** The
  three-role per-pin table (open-drain / push-pull / unused) is the
  contract: a pin-role record that assigns I2C's SCL/SDA to specific
  `uio` pins sets the mask's open-drain bits; one that assigns push-pull
  protocol pins to `uio` (none does today — UART/SPI live on
  `uo_out`/`uio_in`) sets push-pull bits that keep `oe = 1`; everything
  else stays an input. `uio_oe` wiring is thereby fixed for every pin by
  role, never by protocol-specific logic — still no fixed-function
  peripheral anywhere.
- **No spec row's target changes.** Row 12's unmet reasons (a)
  (t_SU;STA unexercised) and (b) (bench-composed bus) stand; this record
  proposes the mechanism that lets a *future* verified change close (b)'s
  silicon-truth half, and nothing else.
- **Two flows, one record of truth.** This record claims no synthesis or
  timing number. The RTL follow-up reports any area/timing delta
  flow-attributed per DR 0002, and a klt-vs-LibreLane mismatch there is a
  finding to record, not a number to pick from.

## Open items (assigned, not left hanging)

1. **External pull-up assumption — unverified.** Hi-Z release reads high
   only if the board provides pull-ups on the masked `uio` pins.
   **Not verified** whether the Tiny Tapeout demo board provides pull-ups
   on `uio`; no source in this repository answers it (`info.yaml` and
   `docs/` carry no pull-up statement). Before the RTL follow-up signs
   off, confirm from Tiny Tapeout board documentation or name the
   external pull-up requirement in the submission's user-facing docs.
   **Update 2026-10-09 (issue #133), appended; the text above stands as
   written.** The organizers' 2026-10-09 entrant update answers it: the
   chip has only digital pins (3.3 V I/O on the demo board), and "things
   like pull-ups, transceivers or level shifting go on a Pmod ... Please
   document anything your design needs." So the pull-ups on the masked
   open-drain `uio` pins are **external, on a Pmod, not on the board**, and
   the submission must document them: `docs/info.md` now carries a
   required-external-parts section. The board is still not verified to
   provide any `uio` pull-up, and none is assumed.
2. **The pin-role decision record sets the mask value** (row 5's "later
   decision record"; also consumes the SCL/SDA pin choice the firmware's
   `uio[0]`/`uio[7]` plan proposes).
3. **The RTL follow-up** (post-ratification): change `assign uio_oe`,
   model the mask in the I2C bench, re-run
   `verification/records/firmware-i2c/`-style evidence flow-attributed,
   and add DR 0001's dated note resolving its flagged open question.
4. **Ratification.** This record, DRs 0001–0005 and 0007, and
   `spec/target-spec.md` wait on the same two-key act (DR 0006 § "How this
   gets closed"; #44, #45).

## Cross-references

- #75 (this record's issue), #73 (the I2C firmware that surfaced the gap
  and whose scope required this raise), #23 (the parent firmware epic).
- #44 / #45 (ratification never ran; the mechanism and its gate) — the
  gate that conditions option 2.
- #72 (SPI): consumes the three-role per-pin table; unaffected today.
- [`0007-row4-corner-set-under-the-macro.md`](0007-row4-corner-set-under-the-macro.md):
  the numbering-precedent and format sibling, otherwise unrelated.
