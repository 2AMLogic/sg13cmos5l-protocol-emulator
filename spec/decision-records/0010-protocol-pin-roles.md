# 0010: Protocol Pin Roles — `ui_in`, `uo_out` and `uio` Assignments per Firmware Profile

Status: **Proposed 2026-10-09.** It goes to ratification through the
program's two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"; DR
[`0004`](0004-target-spec-ratification.md) and
[`0006`](0006-two-key-ratification-never-ran.md)). It binds only when that
PR's history shows **two** `RATIFY-KEY` reviews, one EE key and one market
key, neither held by this record's author, and the merge commit is the
ratification act. That mechanism has never run in this repository, so for
now this record is a proposal, the same way DRs 0001–0005, 0007 and 0008 are.
It does **not** make target-spec row 5 or row 12 met, edits no spec row, and
nothing in it may be cited as though it did.
Date: 2026-10-09
Issue: #94

**Numbering note.** Issue #94 asked for "the next free number across main and
open PR reservations". At filing time main carries DRs 0001–0008 and open
PR #84 reserves 0009 (`0009-two-key-ratification-act.md`); this record is
therefore **0010**. PR #96 (UART receive profiles) adds firmware files but no
decision record.

## Context

`spec/target-spec.md` row 5 (I/O pin budget) is only structurally met, and
`spec/gap-to-submission.md` row 5 says "assigning protocol roles to specific
pins is a later decision record". This is that record. It matters now because

- [DR 0008](0008-open-drain-uio-oe-wiring.md) fixes the *mechanism* for
  open-drain `uio` pins (per-pin `uio_oe` behind a synthesis-time mask) and
  explicitly defers the mask's *value* to this record;
- the committed firmware and benches already assume a pin plan ad hoc
  (`uo_out[0]` UART TX, `uo_out[0..2]` SPI CS/SCLK/MOSI, `uio[0]` SPI MISO
  and I2C SCL, `uio[7]` I2C SDA), with nothing keeping the plan and the
  record of it in step; and
- `info.yaml` and the template `docs/info.md` pin table cannot be finalised
  for submission (row 9, due 2027-01-18) until the roles are decided.

`info.yaml` today describes the ports generically — "ISA output port 10 bit
3" — because the *silicon* does not decide what a pin means; the loaded
firmware does (DR 0001). That stays true. This record decides the **default
pin plan the shipped firmware profiles, benches and submission documents
share**, and the electrical role each physical pad must be able to play to
support it.

## Decision (proposed): preserve every current firmware allocation

No firmware pin moves. The plan below is exactly what the committed sources
already do; the new content is the electrical column, the open-drain mask and
the mechanical check.

**Update 2026-10-09 (issue #155).** The SPI and I2C profiles have moved to
the target plan ("Target pin plan" below): SPI on the standard SPI Pmod, I2C
on the standard I2C Pmod, both on the upper `uio` row. As that section said
it would, the "Run phase" table, the open-drain mask, the "today" table and
the machine-readable table are rewritten to describe the moved profiles;
what they said before is in this file's history (PRs #148, #149, #170). The UART
RX move followed in #178 (below). The Status line above is unchanged; this
record is still Proposed.

### Load phase (reset released with `ui_in[7]` high)

| Pin | Role |
|---|---|
| `ui_in[7]` | `PROG_MODE` — high at reset release enters the serial load phase; during load high = shifting, low = enter run phase |
| `ui_in[0]` | `PROG_SER` — serial program bit, MSB-first, one bit per rising clock edge |

All other pins have no load role. In the run phase `ui_in[7:0]` is ISA input
port 00; since #178 the only protocol role on it is UART RX on `ui_in[1]`.
`ui_in[0]` (`PROG_SER`) carries no protocol role in the run phase.

### Run phase, per firmware profile

| Pin | Electrical | UART TX | UART RX | UART RX result | SPI transfer | SPI result | I2C transfer | I2C result |
|---|---|---|---|---|---|---|---|---|
| `uo_out[0]` | push-pull | `TX` | unused | `RESULT[0]` | unused | `RESULT[0]` | unused | `RESULT[0]` |
| `uo_out[1..7]` | push-pull | unused | unused | `RESULT[n]` | unused | `RESULT[n]` | unused | `RESULT[n]` |
| `uio[0]` | runtime: push-pull in SPI images | unused | unused | unused | `CS` (active low) | unused | unused | unused |
| `uio[1]` | runtime: push-pull in SPI images | unused | unused | unused | `MOSI` | unused | unused | unused |
| `uio[2]` | runtime: input in SPI images, **open-drain** in I2C images | unused | unused | unused | `MISO` (sampled) | unused | `SCL` | unused |
| `uio[3]` | runtime: push-pull in SPI images, **open-drain** in I2C images | unused | unused | unused | `SCLK` (the Pmod's SCK) | unused | `SDA` | unused |
| `uio[4..7]` | input | unused | unused | unused | unused | unused | unused | unused |
| `ui_in[0]` | input (`PROG_SER` in the load phase only) | unused | unused | unused | unused | unused | unused | unused |
| `ui_in[1]` | input | unused | `RX` (sampled, idle high) | unused | unused | unused | unused | unused |
| `ui_in[2..6]` | input | unused | unused | unused | unused | unused | unused | unused |

"Result publication" is the cycle-exact convention the SPI functional burst
and the I2C read-back programs already use: the received byte is written to
`uo_out[7:0]` after the transfer so the bench can compare it, which is why
every `uo_out` bit carries a `RESULT[n]` role in those two phases. `uo_out[0]`
is therefore time-multiplexed by firmware profile (UART TX, result bit 0);
both roles are push-pull outputs, so there is no electrical conflict. SPI
writes its CS / MOSI / SCLK images to `uio_out` and samples MISO on
`uio_in[2]`. I2C open-drain intent is written to `uio_out` (SCL bit 2, SDA
bit 3, writing 1 releases) and sampled from `uio_in`; the SCL-polling
variants read the peripheral's SCL level on `uio_in[2]`.

"Runtime" is DR 0012's pin mode: a `uio` pin's electrical role is whatever
the loaded image writes to `UIO_DIR` / `UIO_OD`, so one pad can be push-pull
SCLK in an SPI image and open-drain SDA in an I2C image. Each SPI image writes
`UIO_DIR = 0x0B` (CS | MOSI | SCLK) after its idle image; each I2C image
writes `UIO_OD = 0x0C` (SCL | SDA) after releasing both lines. The UART
images write neither.

### Open-drain mask and derivation

DR 0008's three-role contract is `uio_oe = PUSH_PULL_MASK | (OPEN_DRAIN_MASK &
~uio_out)`, with both masks fixed at synthesis. Deriving them from the table
above, only pins with a *fixed* electrical role count:

| uio pin | Electrical role | Reason |
|---|---|---|
| `uio[0..3]` | runtime | SPI and I2C roles, set per image (DR 0012) |
| `uio[4..7]` | input | no protocol role |

`OPEN_DRAIN_MASK = 0x00`, `PUSH_PULL_MASK = 0x00`. A synthesis-time mask
cannot serve the moved profiles at all: `uio[3]` is push-pull for SPI and
open-drain for I2C. That is why the moves waited for DR 0012 (#135), whose
runtime registers the top level has. The per-profile register values are
declared in the table's `pin_modes` block instead:

| Profile | `UIO_DIR` | `UIO_OD` |
|---|---|---|
| UART | `0x00` | `0x00` |
| SPI | `0x0B` (CS, MOSI, SCLK) | `0x00` |
| I2C | `0x00` | `0x0C` (SCL, SDA) |

The checker recomputes both fixed masks and every `pin_modes` value from the
per-pin roles and fails if the table's declared values differ. The dedicated
outputs `uo_out[7:0]` are always driven (`push_pull`); `ui_in[7:0]` are
inputs. (Before #155 the table had `uio[0]` and `uio[7]` open-drain, mask
`0x81`.)

### Pull-up requirement

Releasing an open-drain pin is hi-Z; the line reads high only with an
external pull-up. I2C needs a pull-up on `uio[2]` (SCL) and `uio[3]` (SDA) —
typically the bus's own (an I2C Pmod usually carries them). Before #155 these
were `uio[0]` and `uio[7]`. Whether the Tiny Tapeout demo board provides pull-ups
on `uio` is **not verified** here (DR 0008 open item 1 stands); the
submission's user-facing `docs/info.md` must name the requirement.

**Update 2026-10-09 (issue #133), appended; the text above stands as
written.** DR 0008 item 1 is answered: pull-ups are external, on a Pmod, and
documented in `docs/info.md` ("External hardware"). The board is not assumed
to provide any.

### Alignment with Tiny Tapeout's recommended pinouts (issue #133)

Source: <https://tinytapeout.com/specs/pinouts/>, read 2026-10-09. The page
makes two kinds of recommendation.

**Pmod rows.** Each protocol uses one four-pin row of the `uio` Pmod,
"preferably the upper row" (`uio[0..3]`) or the lower (`uio[4..7]`):

| Protocol | Upper row | Lower row |
|---|---|---|
| UART | (CTS) `uio[0]`, TXD `uio[1]`, RXD `uio[2]`, (RTS) `uio[3]` | `uio[4..7]`, same order |
| SPI | CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]` | `uio[4..7]`, same order |
| I2C | (INT) `uio[0]`, (RESET) `uio[1]`, SCL `uio[2]`, SDA `uio[3]` | `uio[4..7]`, same order |

**UART to USB.** The demo board's MCU bridges a UART to the host's USB serial
port on dedicated pins, with no Pmod. There are two options, named from the
design's side:

| Option | RX (into the design) | TX (out of the design) |
|---|---|---|
| A | `ui_in[3]` | `uo_out[4]` |
| B | `ui_in[1]` | `uo_out[0]` |

#### Today's assignments against the recommendations

These are the pins the committed firmware, benches and the machine-readable
table below use today (rewritten by #155 for SPI and I2C and by #178 for UART RX):

| Protocol | Today | Recommended | Works unmodified? |
|---|---|---|---|
| UART | TX `uo_out[0]`, RX `ui_in[1]` (`uart_rx` phase, added by #143; moved from `ui_in[0]` by #178) | USB bridge option B: TX `uo_out[0]`, RX `ui_in[1]` | **Yes**, option B's TX and RX |
| SPI | CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCLK `uio[3]` (#155) | CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]` | **Yes**, the standard SPI Pmod, upper row |
| I2C | SCL `uio[2]`, SDA `uio[3]` (#155) | SCL `uio[2]`, SDA `uio[3]` (upper row) | **Yes**, the standard I2C Pmod, upper row (with its pull-ups) |

Consequence today: the UART profiles, transmit and receive, reach the host
over the board's USB bridge with no extra wiring, and an off-the-shelf SPI or
I2C Pmod plugs into the upper `uio` row. No firmware profile needs a jumper
wire (#178 moved UART RX).

#### Target pin plan (proposed, issue #133)

This is the decision #143 left to #133. It is Proposed, like the rest of this
record. The shipped firmware profiles **will** follow Tiny Tapeout's
recommended pinouts:

| Protocol | Target pins | Recommendation followed |
|---|---|---|
| UART | RX `ui_in[1]`, TX `uo_out[0]` | UART to USB, option B |
| SPI | CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]` | standard SPI Pmod, upper row |
| I2C | SCL `uio[2]`, SDA `uio[3]` | standard I2C Pmod, upper row |

Why these:

- **UART option B** is what DR 0013's boot ROM already uses, so the boot
  loader and the UART profiles share one RX and one TX pin. TX needs no move.
  Moving RX off `ui_in[0]` also ends its sharing with `PROG_SER`, the serial
  load pin.
- **The upper Pmod row** is the one the pinouts page prefers. SPI and I2C
  overlap on `uio[2]` and `uio[3]`, which is by the page's design: one row
  carries one protocol, and only one firmware image is loaded per run.

**Update 2026-10-09 (issue #155): SPI and I2C have moved.** The paragraph
below describes the change that recorded this plan, and is left as written.
#155 made the SPI and I2C moves in one PR, with the firmware, benches,
generator and this record's tables. **Update 2026-10-10 (issue #178): UART RX
has moved too** (`ui_in[0]` to `ui_in[1]`), with the RX firmware, its bench,
its evidence records and this record's tables in one PR.

**No pin moves in the change that records this plan.** The "Run phase" table
above, the machine-readable table and the open-drain mask all still describe
today's assignments, and the checker still holds the committed firmware and
benches to them. The moves wait for two reasons:

1. **SPI and I2C on `uio` need DR 0012's runtime pin direction (#135).**
   `uio_oe` is hardwired to `8'h00` today, so no `uio` pin can be driven: SPI
   could not drive CS, MOSI or SCK there, and I2C could not pull SCL or SDA
   low. DR 0008's mask is also fixed at synthesis, so it could not serve both
   plans. DR 0012's `UIO_DIR` and `UIO_OD` registers let each firmware image
   set its own directions.
2. **Moving UART RX from `ui_in[0]` to `ui_in[1]` changes committed firmware,
   benches and evidence.** It does not depend on #135, but it invalidates the
   UART receive evidence records, so it is done with the other moves rather
   than alone.

The moves are tracked in **#155**, which is blocked on #135. Each move edits
the firmware, its bench and the machine-readable table in one PR, so the
checker stays green. The files are listed under "Follow-up edits", items 3
to 5. When #155 lands, this section's "today" table and the "Run phase" table
are rewritten to the target plan, and the `uio[0]` sharing below goes away
(MISO moves to `uio[2]`, SCL to `uio[2]` in a different image).

### Shared pads on the upper row: `uio[2]` and `uio[3]` (since #155)

The standard SPI and I2C Pmods overlap: `uio[2]` is SPI `MISO` and I2C `SCL`,
`uio[3]` is SPI `SCLK` and I2C `SDA`. That is by Tiny Tapeout's design (one
row, one protocol) and it is electrically sound here because the pin mode is
per image (DR 0012) and one image is loaded per run:

1. **SPI images** write `UIO_DIR = 0x0B` and never `UIO_OD`: `uio[3]` is a
   push-pull SCLK, and `uio[2]` stays an input that follows the peripheral's
   MISO.
2. **I2C images** write `UIO_OD = 0x0C` and never `UIO_DIR`: both pins are
   open-drain, released on a 1, and pulled up by the Pmod.
3. Both registers reset to 0, so whatever ran before a reset, every `uio`
   pin is an input until the new image writes its own mode.

The checker holds every SPI and I2C image to its profile's `pin_modes` and
reports any pin-mode write the profile does not declare. The section below
is the analysis of the pre-#155 plan and is kept as history.

### SPI `MISO` and I2C `SCL` both on `uio[0]` — electrical compatibility (pre-#155 plan)

This is a real conflict, stated rather than hidden. DR 0008 fixes a pin's
electrical role at synthesis time, so `uio[0]` cannot be push-pull for one
firmware image and open-drain for another. The reuse is nonetheless
electrically sound when `uio[0]` is the open-drain pad:

1. **SPI never drives `uio[0]`.** No SPI profile executes an `OUT UIO_OUT`;
   `MISO` is only *sampled* (`IN Rn, UIO_IN`). With `uio_out[0] = 1` the
   open-drain pad is released and `uio_in[0]` is a plain input that follows
   whatever the SPI peripheral drives on MISO.
2. **The two protocols are never in one firmware image** (one program is
   loaded per run), so the pad is never SCL and MISO at once.
3. **External pull-up on a MISO line is benign**: a push-pull SPI peripheral
   overrides it; a tri-state one reads as a defined high between transfers.

Condition that is **not met today**: `rtl/protocol_core.v` resets
`port_uio_out` to `8'h00`. Under the 0x81 mask that value *asserts* both
`uio[0]` and `uio[7]` low from reset, so MISO would be clamped low and an I2C
bus held low until the first `OUT`. The RTL follow-up must reset the
open-drain bits of `uio_out` to 1 (released), or SPI/UART firmware must
release them first. The checker reports this as an unmet prerequisite.

A second condition is **not met today**: the UART receive programs write
`UIO_OUT` with bits 0 and 7 at 0, which re-asserts both pads after reset
whatever the reset value is. See "UART receive" below.

**Fallback if the ratifying keys reject the sharing**: move `MISO` to a
dedicated input (e.g. `ui_in[1]`), which removes the conflict at the cost of
the follow-up edits listed below. That is a different allocation; adopting it
means editing this table, and the checker fails the committed firmware and
benches until those edits land (see "Checker behaviour").

## Machine-readable table

The checker parses exactly the fenced block below (info string
`json pin-roles`); nothing is inferred from the prose. `phases` lists the
roles each phase must place exactly once. Every pin carries
`electrical_role` (`input` / `push_pull` / `open_drain`, or `runtime` for a
`uio` pin whose role the firmware image sets through DR 0012, issue #155),
`load_role`, and a `protocol_roles` entry for every phase — `"unused"` is
written explicitly. `pin_modes` declares, per profile, the `UIO_DIR` and
`UIO_OD` values the runtime pins' roles imply; the checker derives them
again and holds every SPI and I2C image to them.
`bench_debug` declares writes that are not pin roles but are still checked bit
by bit; only the `uart_rx` profile has any (see "UART receive").
`metadata_class: generic_isa_capability` records that `info.yaml`'s labels are
ISA capability descriptions, not claims that a protocol assignment is
implemented. `inventory` lists every file the checker reads and the
extraction patterns it runs on it; a pattern the script does not implement,
a missing file, or a committed `firmware/asm/*.asm` file absent from the
inventory is a hard failure.

```json pin-roles
{
  "schema": 1,
  "open_drain_mask": "0x00",
  "push_pull_mask": "0x00",
  "pin_modes": {
    "uart": {"uio_dir": "0x00", "uio_od": "0x00"},
    "spi": {"uio_dir": "0x0B", "uio_od": "0x00"},
    "i2c": {"uio_dir": "0x00", "uio_od": "0x0C"}
  },
  "bench_debug": {"uart_rx": {"port": "uio", "bits": {"SAMPLE_MARK": 1, "FRAME_ERROR": 2}}},
  "phases": {
    "uart_tx": ["TX"],
    "uart_rx": ["RX"],
    "uart_rx_result": ["RESULT[0]", "RESULT[1]", "RESULT[2]", "RESULT[3]", "RESULT[4]", "RESULT[5]", "RESULT[6]", "RESULT[7]"],
    "spi_transfer": ["CS", "SCLK", "MOSI", "MISO"],
    "spi_result": ["RESULT[0]", "RESULT[1]", "RESULT[2]", "RESULT[3]", "RESULT[4]", "RESULT[5]", "RESULT[6]", "RESULT[7]"],
    "i2c_transfer": ["SCL", "SDA"],
    "i2c_result": ["RESULT[0]", "RESULT[1]", "RESULT[2]", "RESULT[3]", "RESULT[4]", "RESULT[5]", "RESULT[6]", "RESULT[7]"]
  },
  "pins": [
    {"pin": "ui_in[0]", "port": "ui_in", "bit": 0, "electrical_role": "input", "load_role": "PROG_SER", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[1]", "port": "ui_in", "bit": 1, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "RX", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[2]", "port": "ui_in", "bit": 2, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[3]", "port": "ui_in", "bit": 3, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[4]", "port": "ui_in", "bit": 4, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[5]", "port": "ui_in", "bit": 5, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[6]", "port": "ui_in", "bit": 6, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[7]", "port": "ui_in", "bit": 7, "electrical_role": "input", "load_role": "PROG_MODE", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[0]", "port": "uo_out", "bit": 0, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "TX", "uart_rx": "unused", "uart_rx_result": "RESULT[0]", "spi_transfer": "unused", "spi_result": "RESULT[0]", "i2c_transfer": "unused", "i2c_result": "RESULT[0]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[1]", "port": "uo_out", "bit": 1, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[1]", "spi_transfer": "unused", "spi_result": "RESULT[1]", "i2c_transfer": "unused", "i2c_result": "RESULT[1]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[2]", "port": "uo_out", "bit": 2, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[2]", "spi_transfer": "unused", "spi_result": "RESULT[2]", "i2c_transfer": "unused", "i2c_result": "RESULT[2]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[3]", "port": "uo_out", "bit": 3, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[3]", "spi_transfer": "unused", "spi_result": "RESULT[3]", "i2c_transfer": "unused", "i2c_result": "RESULT[3]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[4]", "port": "uo_out", "bit": 4, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[4]", "spi_transfer": "unused", "spi_result": "RESULT[4]", "i2c_transfer": "unused", "i2c_result": "RESULT[4]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[5]", "port": "uo_out", "bit": 5, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[5]", "spi_transfer": "unused", "spi_result": "RESULT[5]", "i2c_transfer": "unused", "i2c_result": "RESULT[5]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[6]", "port": "uo_out", "bit": 6, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[6]", "spi_transfer": "unused", "spi_result": "RESULT[6]", "i2c_transfer": "unused", "i2c_result": "RESULT[6]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[7]", "port": "uo_out", "bit": 7, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "RESULT[7]", "spi_transfer": "unused", "spi_result": "RESULT[7]", "i2c_transfer": "unused", "i2c_result": "RESULT[7]"}, "shared_pin_rationale": ""},
    {"pin": "uio[0]", "port": "uio", "bit": 0, "electrical_role": "runtime", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "CS", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[1]", "port": "uio", "bit": 1, "electrical_role": "runtime", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "MOSI", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[2]", "port": "uio", "bit": 2, "electrical_role": "runtime", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "MISO", "spi_result": "unused", "i2c_transfer": "SCL", "i2c_result": "unused"}, "shared_pin_rationale": "Standard SPI and I2C Pmod rows overlap here by Tiny Tapeout's design: one row carries one protocol and one firmware image is loaded per run. The SPI images leave the pin an input (UIO_DIR bit 2 = 0, UIO_OD bit 2 = 0) and sample MISO on uio_in[2]; the I2C images make it open-drain SCL (UIO_OD bit 2). DR 0012 sets the mode per image, so no image sees the other's role."},
    {"pin": "uio[3]", "port": "uio", "bit": 3, "electrical_role": "runtime", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "SCLK", "spi_result": "unused", "i2c_transfer": "SDA", "i2c_result": "unused"}, "shared_pin_rationale": "Push-pull SCLK (SCK) in the SPI images (UIO_DIR bit 3) and open-drain SDA in the I2C images (UIO_OD bit 3): two electrical roles on one pad, legal only because DR 0012 sets the pin mode at run time per image and one image is loaded per run. Neither role exists while the other profile runs."},
    {"pin": "uio[4]", "port": "uio", "bit": 4, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[5]", "port": "uio", "bit": 5, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[6]", "port": "uio", "bit": 6, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[7]", "port": "uio", "bit": 7, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "uart_rx": "unused", "uart_rx_result": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""}
  ],
  "inventory": [
    {"file": "firmware/asm/uart_tx.asm", "profile": "uart_tx", "patterns": ["asm_ports", "uart_tx_mask"]},
    {"file": "firmware/asm/uart_tx_9600.asm", "profile": "uart_tx", "patterns": ["asm_ports", "uart_tx_mask"]},
    {"file": "firmware/asm/uart_rx.asm", "profile": "uart_rx", "patterns": ["asm_ports", "uart_rx_mask", "uart_rx_debug"]},
    {"file": "firmware/asm/uart_rx_115200.asm", "profile": "uart_rx", "patterns": ["asm_ports", "uart_rx_mask", "uart_rx_debug"]},
    {"file": "firmware/asm/uart_rx_9600.asm", "profile": "uart_rx", "patterns": ["asm_ports", "uart_rx_mask", "uart_rx_debug"]},
    {"file": "firmware/asm/spi_mode0.asm", "profile": "spi", "patterns": ["asm_ports", "spi_images", "spi_miso_mask"]},
    {"file": "firmware/asm/spi_mode1.asm", "profile": "spi", "patterns": ["asm_ports", "spi_images", "spi_miso_mask"]},
    {"file": "firmware/asm/spi_mode2.asm", "profile": "spi", "patterns": ["asm_ports", "spi_images", "spi_miso_mask"]},
    {"file": "firmware/asm/spi_mode3.asm", "profile": "spi", "patterns": ["asm_ports", "spi_images", "spi_miso_mask"]},
    {"file": "firmware/asm/i2c_fast.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks"]},
    {"file": "firmware/asm/i2c_std.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks"]},
    {"file": "firmware/asm/i2c_fast_sr.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks"]},
    {"file": "firmware/asm/i2c_fast_sr_poll.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks", "i2c_poll_mask"]},
    {"file": "firmware/asm/i2c_std_sr.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks"]},
    {"file": "firmware/asm/i2c_std_sr_poll.asm", "profile": "i2c", "patterns": ["asm_ports", "i2c_idle_start", "i2c_alu_masks", "i2c_in_masks", "i2c_poll_mask"]},
    {"file": "firmware/asm/demo_roundtrip.asm", "profile": "demo", "patterns": ["asm_ports"]},
    {"file": "firmware/tools/gen_i2c_sr.py", "profile": "i2c_gen", "patterns": ["gen_strings", "i2c_idle_start", "i2c_alu_masks", "i2c_poll_mask"]},
    {"file": "firmware/tools/asm.py", "profile": "isa_ports", "patterns": ["isa_port_table"]},
    {"file": "verification/test_firmware_uart.py", "profile": "bench_uart", "patterns": ["bench_uart_tx"]},
    {"file": "verification/test_firmware_spi.py", "profile": "bench_spi", "patterns": ["bench_spi_consts"]},
    {"file": "verification/test_firmware_i2c.py", "profile": "bench_i2c", "patterns": ["bench_i2c_consts"]},
    {"file": "verification/test_firmware_i2c_sr.py", "profile": "bench_i2c_sr", "patterns": ["bench_i2c_sr_consts"]},
    {"file": "verification/test_protocol_emulator.py", "profile": "bench_load", "patterns": ["bench_load_pins"]},
    {"file": "src/tt_um_2amlogic_protocol_emulator.v", "profile": "top", "patterns": ["top_load_wiring", "top_uio_oe", "top_port_passthrough"]},
    {"file": "rtl/protocol_core.v", "profile": "core", "patterns": ["core_uio_out_reset"]},
    {"file": "info.yaml", "profile": "info", "patterns": ["info_pinout"]}
  ]
}
```

### What each extraction pattern reads

| Pattern | Site |
|---|---|
| `asm_ports` | the set of `OUT` / `IN` port names; must match the ports of the table's pins for the profile |
| `uart_tx_mask` | first `LDI R1, imm` in `uart_tx.asm` / `uart_tx_9600.asm` (the TX bit mask and idle level) and every `LDI` immediately feeding `AND`/`OR`/`XOR` |
| `uart_rx_mask` | first `LDI R1, imm` in `uart_rx*.asm` (the RX bit mask), every `LDI` immediately feeding `AND`/`OR`/`XOR`, and, as `spi_miso_mask`, the mask of each `IN Rx, <RX port>` sample; at least one such sample site must exist |
| `uart_rx_debug` | every `OUT UIO_OUT, Rx` in `uart_rx*.asm`: the source must be an `LDI` constant, a `SUB` countdown followed by `BNZ` (zero on loop exit), or the frame-error shape `IN`/`AND`/`XOR`/`SHF LEFT` on the RX mask register. Values are limited to 0 and the two `bench_debug.uart_rx` bits, both bits must be written, and one `OUT` to the result port must carry a non-constant value |
| `spi_images` | each `LDI R2, imm` immediately followed by `OUT <port>, R2`, where `<port>` is the output port the table puts CS/SCLK/MOSI on (`UIO_OUT` since #155): the first is the idle image (CS high, SCLK at CPOL), every image may use only CS/SCLK/MOSI bits, and no constant image goes to any other port |
| `spi_miso_mask` | for `IN Rx, UIO_IN`, the nearest `LDI Ry` before the next `AND Rx, Ry` must equal the MISO bit mask |
| `i2c_idle_start` | the `LDI R3` feeding the first two `OUT UIO_OUT, R3`: bus-idle = SCL\|SDA, START = SCL |
| `i2c_alu_masks` | an `LDI Rn, imm` immediately followed by `AND`/`OR`/`XOR` using `Rn` must be the SCL or SDA mask (counter, data and timing literals are not pin masks and are not counted) |
| `i2c_in_masks` | as `spi_miso_mask`, SDA mask for ACK/read sampling, SCL mask for `pollN:` sites |
| `i2c_poll_mask` | the `LDI R3, imm` before each `pollN: IN` equals the SCL mask |
| `gen_strings` | the instruction string literals of `firmware/tools/gen_i2c_sr.py`, parsed with `ast` and the same line grammar as assembly |
| `bench_*` | the named module-level constants and capture specs of each bench (`TX_PIN/TX_BIT`, `CS_BIT…`, `MISO_PIN/MISO_BIT`, `SCL_PIN/SDA_PIN`; since issue #136 also `LINE_PIN`, `CAPTURE_SPECS`, the `i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)` wiring of the pad model, and every `pads.*` call naming a pad as `SCL_BIT`/`SDA_BIT`, in place of the removed `_RELEASED`, `_ACK_PULL`, `(sda_drive << N)` and `per_scl`/`per_sda`; since issue #155 the SPI bench's `CAPTURE_SPECS` port and bit for CS/SCLK/MOSI, `LINE_PIN`, the `spi_board(dut, cs=CS_BIT, sclk=SCLK_BIT, mosi=MOSI_BIT, miso=MISO_BIT)` wiring and its `pads.*` calls by named bit), and `load_program`'s `ui_in` assignments |
| `top_load_wiring` / `top_uio_oe` / `top_port_passthrough` | `.mode_pin(ui_in[n])`, `.serial_in(ui_in[n])`, `assign uio_oe = …;`, whole-bus `.port_*` connections |
| `core_uio_out_reset` | the `port_uio_out <= 8'hXX;` reset literal |
| `isa_port_table` | `firmware/tools/asm.py` port codes 00/01/10/11 |
| `info_pinout` | the 24 `ui[n]` / `uo[n]` / `uio[n]` keys, their direction sections and generic labels |

Coverage was originally the tree as of this record: eleven committed
assembly files (`uart_tx`, `spi_mode0–3`, `i2c_fast`, `i2c_std` and the four
`*_sr`/`*_sr_poll` variants) plus `demo_roundtrip`, the generator, and four
benches. Because the checker fails on any uninventoried `firmware/asm/*.asm`,
the UART receive and low-baud programs of issue #91 (PR #96) were added
afterwards by #143 (see "UART receive" below). The checker runs in
`npm run lint`, so the next unregistered firmware file fails its PR.

### UART receive (added by #143)

`uart_rx.asm`, `uart_rx_115200.asm` and `uart_rx_9600.asm` sample RX on
`ui_in[1]` (since #178; it was `ui_in[0]`) and write the received byte to all of `uo_out`. The table records
that as the `uart_rx` phase (`RX` on `ui_in[1]`, a sampled role) and the
`uart_rx_result` phase (`RESULT[n]` on `uo_out[n]`), checked by the `uart_rx`
profile. `uart_tx_9600.asm` is the low-baud transmitter and uses the existing
`uart_tx` profile (TX on `uo_out[0]`).

RX shares no pin with the `PROG_SER` load pin any more. #143 recorded RX on
`ui_in[0]`, shared with `PROG_SER` (the two never overlapped in time: the
loader shifts the program in while `PROG_MODE` is high, and the RX programs
sampled only after the MODE drop). The UART boot program of DR 0013 uses RX
on `ui_in[1]` (Tiny Tapeout option B). #133's target plan put RX on
`ui_in[1]` too, and #178 made the move. `ui_in[0]` is `PROG_SER` in the load
phase only; the RX programs never read it, and the bench toggles it
mid-frame to prove that.

**Register consequence of the move (#178).** `R1` is the RX bit mask and the
program's constant: it is now 2, not 1. The same register is the sample-mark
value, the XOR mask and the delay-loop decrement, so those follow it: the
debug bits are `uio_out[1]` (sample mark) and `uio_out[2]` (frame-error
flag), the outer delay counts are doubled (decrement 2), and each data-bit
sample has six `SHF LEFT` plus a `NOP` where it had seven `SHF LEFT` (bit 1
needs six shifts to reach bit 7). Word count, total cycles and every `WAIT`
count are unchanged, so the sample instants are the same.

**Bench-debug writes to `uio_out`.** The RX programs also write `UIO_OUT`: a
sample mark on `uio_out[1]` and a frame-error flag on `uio_out[2]` (they were
`uio_out[0]` and `uio_out[1]` until #178 moved RX). These are
observability aids for the bench, **not** pin roles, and the table assigns no
`uart_rx` role on `uio`. They are still checked. The table's `bench_debug`
block declares the two bits, and the `uart_rx_debug` pattern requires every
`OUT UIO_OUT` in an RX program to be one of three shapes: a constant, a
countdown register that has reached zero, or the frame-error computation. The
only values allowed are `0x00`, the mark bit and the frame-error bit. The
received byte on `UIO_OUT` fails, and at least one `OUT` to the result port
must carry a computed value, so the byte cannot be rerouted off `uo_out`.

Since #178 the two debug bits sit on the SPI profile's MOSI (`uio[1]`) and
MISO/I2C-SCL (`uio[2]`) pins. That changes nothing below: a UART RX image writes no
pin-mode register, so neither pin is driven while it runs.

**These writes drive no pad (#154, resolved by DR 0012).** The top level is
[DR 0012](0012-control-space-and-runtime-pin-direction.md)'s pin-mode rule
since #135: `uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir)`. `UIO_OD` and
`UIO_DIR` both reset to `0x00`, so every `uio` pin is an input until a program
writes one of them. The three RX programs execute no `WCTL`, so their
`uio_out` values never reach a pad, whatever bits they hold.

#154 offered three ways to deal with these writes: remove them, move them, or
rely on the runtime mask. **This record takes the third.** The debug writes
stay, no firmware changes, and the cycle-exact RX timing in
`verification/test_firmware_uart_rx.py` is untouched.

The checker holds the condition. For each RX image it reports an unmet
prerequisite under `[implementation]` if the image also writes a pin-mode
register (`WCTL UIO_OD` or `WCTL UIO_DIR`, by name or as index `0x00` /
`0x01`). An RX image that gains such a write fails `--require-implemented`.
That is the general rule of #159, section 4: a program that writes `UIO_OUT`
for bench-debug reasons is harmless only while it executes no `WCTL`.

What this replaced: under DR 0008's fixed synthesis-time mask
(`uio_oe = 8'h81 & ~uio_out`), a 0 in `uio_out[0]` or `uio_out[7]` asserts the
pad low. Every debug write leaves bit 7 at 0, and leaves bit 0 at 0 except
during a sample mark, so a loaded RX image would have held `uio[7]` (SDA) low
for the whole run and `uio[0]` (SCL / SPI MISO) low except during each sample
mark. That mask was not built. If it is ever built in place of DR 0012's
registers, the debug writes must be removed or moved first; the checker still
reports them as an unmet prerequisite for that top-level shape.

## Checker behaviour

`scripts/check_protocol_pin_roles.py` (tests:
`scripts/test_check_protocol_pin_roles.py`) reports four separate results:

1. **schema** — 24 pins, no duplicates / unknown ports / out-of-range bits,
   consistent electrical roles, declared masks equal the derived masks,
   supported extraction patterns, complete inventory.
2. **metadata-capability** — `info.yaml` keys, directions, generic labels and
   load labels, plus the top-level `PROG_MODE`/`PROG_SER` wiring. A metadata
   description that names a concrete protocol role the table does not assign
   to that pin fails. Passing here says the metadata is a correct *generic
   capability* statement; it is not evidence of any protocol implementation.
3. **concrete-firmware-bench** — every assembly variant, the generator and
   the benches use the pins the table assigns. Mismatches name the file, line
   and pin. There is no allow-mismatch switch or wildcard. If an allocation
   in this table is changed to move a pin, this result **fails** until the
   follow-up firmware and bench edits land; that is the intended outcome.
4. **implementation** — proposed electrical roles not wired in the top level
   and unmet prerequisites. On the committed tree it lists nothing. The top
   level is DR 0012's pin-mode rule (#135), so an open-drain role is wired by
   the firmware image that uses it: each I2C image releases the lines and
   then sets `UIO_OD`, and since #155 each SPI image writes its idle image
   and then sets `UIO_DIR`. The UART receive programs' bench-debug writes to
   `UIO_OUT` are not listed, because those programs write no pin-mode
   register (see "UART receive" above). They would be listed if one did.

Default success means results 1–3 agree with this Proposed record, **not**
that silicon implements every electrical role. `--require-implemented` also
fails while result 4 lists anything. It passes today.

## Follow-up edits (separate issues after the keys accept this record)

None is made by this PR; the PR touches no RTL, firmware, `info.yaml` or
target-spec row.

1. **RTL** (`src/tt_um_2amlogic_protocol_emulator.v`, `rtl/protocol_core.v`):
   `assign uio_oe = 8'h00 | (8'h81 & ~uio_out)` per DR 0008, reset the
   open-drain bits of `port_uio_out` to 1, and model the mask in the I2C
   bench so the composed bus is silicon-true. Re-measure on the flow of record
   (DR 0002), flow-attributed. **Superseded:** DR 0012 (#135) landed a
   runtime mask instead of this assign, so this follow-up is not built. Its
   prerequisite, that the UART receive programs' debug writes to `UIO_OUT`
   be removed or moved, is closed by #154 without a firmware change (see
   "UART receive" above). It applies again only if this fixed assign is built.
2. **`info.yaml`** and the template `docs/info.md`: add the protocol-profile
   pin table and the pull-up statement; these are generic ISA labels today.
3. **Done by #155.** **When SPI moves** (#155, or the `MISO` fallback above): `firmware/asm/spi_mode0–3.asm`
   (`IN … UIO_IN` and the MISO mask), `verification/test_firmware_spi.py`
   (`MISO_PIN`/`MISO_BIT`, the `dut.uio_in` driver), `firmware_templates.py`
   if it embeds the SPI template, and this table.
4. **Done by #155.** **When I2C SCL/SDA move** (#155): `firmware/asm/i2c_*.asm`,
   `firmware/tools/gen_i2c_sr.py` (and regenerate the `*_sr` files),
   `verification/test_firmware_i2c.py` (`SCL_*`/`SDA_*`; since issue
   #136 these are the only place the I2C benches name the pins --
   `verification/test_firmware_i2c_sr.py` and the pad model
   `verification/uio_pads.py` take them from there).
5. **If UART TX moves**: `firmware/asm/uart_tx.asm`,
   `firmware/asm/uart_tx_9600.asm` and `verification/test_firmware_uart.py`.
   **UART RX has moved** to `ui_in[1]` (#178): `firmware/asm/uart_rx*.asm`
   (the `LDI R1` mask, which also sets the debug bits and the delay-loop
   step) and `verification/test_firmware_uart_rx.py` (its `set_rx` driver and
   mark / flag bits). A further RX move edits those same places.
6. **If load pins move**: the top-level `.mode_pin`/`.serial_in`,
   `verification/test_protocol_emulator.py::load_program`, `info.yaml`.

## Not decided here

- Ratification (this record is Proposed; no Status line is flipped).
- The RTL change, the pad wiring, and whether the demo board has pull-ups.
- Any target-spec row's target or state; row 5 and row 12 are not edited.
- The pin moves themselves. #133 proposes the target plan ("Target pin
  plan": UART RX to `ui_in[1]`, SPI and I2C onto the upper `uio` Pmod row),
  so *whether* the pins move is no longer open. *Making* the moves is #155,
  after #135. #155 moved SPI and I2C and #178 moved UART RX to `ui_in[1]`, so
  this record's tables now carry the target plan for all three protocols.

## Cross-references

[DR 0001](0001-isa.md) (ISA, ports, timing), [DR 0004](0004-target-spec-ratification.md)
and [DR 0006](0006-two-key-ratification-never-ran.md) (ratification rules),
[DR 0008](0008-open-drain-uio-oe-wiring.md) (mechanism this record instantiates),
[DR 0012](0012-control-space-and-runtime-pin-direction.md) (runtime pin
direction the target plan needs), [DR 0013](0013-program-loading.md) (boot
UART on option B), issues #94 (this), #133 (target pin plan), #155 (the pin
moves), #135 (DR 0012 RTL), #75 (open-drain), #23 (firmware epic), #104 (I2C on the
real core; physical pad wiring explicitly out of scope there).
