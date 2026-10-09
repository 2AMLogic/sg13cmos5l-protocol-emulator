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

### Load phase (reset released with `ui_in[7]` high)

| Pin | Role |
|---|---|
| `ui_in[7]` | `PROG_MODE` — high at reset release enters the serial load phase; during load high = shifting, low = enter run phase |
| `ui_in[0]` | `PROG_SER` — serial program bit, MSB-first, one bit per rising clock edge |

All other pins have no load role. In the run phase `ui_in[7:0]` is ISA input
port 00 and carries no protocol role in any current profile.

### Run phase, per firmware profile

| Pin | Electrical | UART TX | SPI transfer | SPI result | I2C transfer | I2C result |
|---|---|---|---|---|---|---|
| `uo_out[0]` | push-pull | `TX` | `CS` (active low) | `RESULT[0]` | unused | `RESULT[0]` |
| `uo_out[1]` | push-pull | unused | `SCLK` | `RESULT[1]` | unused | `RESULT[1]` |
| `uo_out[2]` | push-pull | unused | `MOSI` | `RESULT[2]` | unused | `RESULT[2]` |
| `uo_out[3..7]` | push-pull | unused | unused | `RESULT[n]` | unused | `RESULT[n]` |
| `uio[0]` | **open-drain** | unused | `MISO` (sampled) | unused | `SCL` | unused |
| `uio[7]` | **open-drain** | unused | unused | unused | `SDA` | unused |
| `uio[1..6]` | input | unused | unused | unused | unused | unused |
| `ui_in[1..6]` | input | unused | unused | unused | unused | unused |

"Result publication" is the cycle-exact convention the SPI functional burst
and the I2C read-back programs already use: the received byte is written to
`uo_out[7:0]` after the transfer so the bench can compare it, which is why
every `uo_out` bit carries a `RESULT[n]` role in those two phases. `uo_out[0]`
is therefore time-multiplexed by firmware profile (UART TX, SPI CS, result
bit 0); all of its roles are push-pull outputs, so there is no electrical
conflict. I2C open-drain intent is written to `uio_out` (SCL bit 0, SDA bit 7,
writing 1 releases) and sampled from `uio_in`; the SCL-polling variants read
the peripheral's SCL level on `uio_in[0]`.

### Open-drain mask and derivation

DR 0008's three-role contract is `uio_oe = PUSH_PULL_MASK | (OPEN_DRAIN_MASK &
~uio_out)`. Deriving the masks from the table above:

| uio pin | Electrical role | Reason |
|---|---|---|
| `uio[0]` | open-drain | I2C `SCL` |
| `uio[7]` | open-drain | I2C `SDA` |
| `uio[1..6]` | input | no protocol role |

`OPEN_DRAIN_MASK = (1<<0) | (1<<7) = 0x81`, `PUSH_PULL_MASK = 0x00`, i.e.

```verilog
assign uio_oe = 8'h00 | (8'h81 & ~uio_out);
```

The checker recomputes both masks from the per-pin electrical roles and fails
if the table's declared values differ. The dedicated outputs `uo_out[7:0]`
are always driven (`push_pull`); `ui_in[7:0]` are inputs.

### Pull-up requirement

Releasing an open-drain pin is hi-Z; the line reads high only with an
external pull-up. I2C needs a pull-up on `uio[0]` (SCL) and `uio[7]` (SDA) —
typically the bus's own. Whether the Tiny Tapeout demo board provides pull-ups
on `uio` is **not verified** here (DR 0008 open item 1 stands); the
submission's user-facing `docs/info.md` must name the requirement.

**Update 2026-10-09 (issue #133), appended; the text above stands as
written.** DR 0008 item 1 is answered: pull-ups are external, on a Pmod, and
documented in `docs/info.md` ("External hardware"). The board is not assumed
to provide any.

### Alignment with Tiny Tapeout's recommended Pmod pinouts (issue #133)

Source: <https://tinytapeout.com/specs/pinouts/>, read 2026-10-09. Each
protocol uses one four-pin row of the `uio` Pmod, "preferably the upper row"
(`uio[0..3]`) or the lower (`uio[4..7]`):

| Protocol | Upper row | Lower row |
|---|---|---|
| UART | (CTS) `uio[0]`, TXD `uio[1]`, RXD `uio[2]`, (RTS) `uio[3]` | `uio[4..7]`, same order |
| SPI | CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]` | `uio[4..7]`, same order |
| I2C | (INT) `uio[0]`, (RESET) `uio[1]`, SCL `uio[2]`, SDA `uio[3]` | `uio[4..7]`, same order |

Compared with this record's plan, **the plan does not match**, and this
record deliberately does not move any pin (the ratification state, firmware
images, benches and the `check_protocol_pin_roles` inventory all assume the
current plan, and the DR 0008 mask is a synthesis-time constant):

| Protocol | This plan | Recommended Pmod | Plugs in unmodified? |
|---|---|---|---|
| UART | TX `uo_out[0]`; RX not assigned in this table | TXD/RXD on `uio` | No: TX is on a dedicated output |
| SPI | CS, SCLK, MOSI on `uo_out[0..2]`; MISO `uio[0]` | CS/MOSI/MISO/SCK on one `uio` row | No |
| I2C | SCL `uio[0]`, SDA `uio[7]` | SCL `uio[2]`/`uio[6]`, SDA `uio[3]`/`uio[7]` | SDA matches the lower row; SCL does not (`uio[0]` vs `uio[6]`) |

Consequence: until a pin plan that follows the Pmod rows is admitted, a
user connects these protocols with a jumper-wire adapter board, not an
off-the-shelf Tiny Tapeout Pmod, and `docs/info.md` says so. Output-capable
`uio` roles also need DR 0012's runtime pin direction, since DR 0008's mask is
fixed at synthesis. Re-plumbing to the recommended rows is a **deferred
option**, not a decision: it touches the firmware, four benches and the
checker's table, and is worth doing only if a decision record admits it
before the 2027-01-18 deadline. The deviation is recorded here as the
deliberate choice of the unratified plan, not as an oversight.

### SPI `MISO` and I2C `SCL` both on `uio[0]` — electrical compatibility

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

**Fallback if the ratifying keys reject the sharing**: move `MISO` to a
dedicated input (e.g. `ui_in[1]`), which removes the conflict at the cost of
the follow-up edits listed below. That is a different allocation; adopting it
means editing this table, and the checker fails the committed firmware and
benches until those edits land (see "Checker behaviour").

## Machine-readable table

The checker parses exactly the fenced block below (info string
`json pin-roles`); nothing is inferred from the prose. `phases` lists the
roles each phase must place exactly once. Every pin carries
`electrical_role` (`input` / `push_pull` / `open_drain`), `load_role`, and a
`protocol_roles` entry for every phase — `"unused"` is written explicitly.
`metadata_class: generic_isa_capability` records that `info.yaml`'s labels are
ISA capability descriptions, not claims that a protocol assignment is
implemented. `inventory` lists every file the checker reads and the
extraction patterns it runs on it; a pattern the script does not implement,
a missing file, or a committed `firmware/asm/*.asm` file absent from the
inventory is a hard failure.

```json pin-roles
{
  "schema": 1,
  "open_drain_mask": "0x81",
  "push_pull_mask": "0x00",
  "phases": {
    "uart_tx": ["TX"],
    "spi_transfer": ["CS", "SCLK", "MOSI", "MISO"],
    "spi_result": ["RESULT[0]", "RESULT[1]", "RESULT[2]", "RESULT[3]", "RESULT[4]", "RESULT[5]", "RESULT[6]", "RESULT[7]"],
    "i2c_transfer": ["SCL", "SDA"],
    "i2c_result": ["RESULT[0]", "RESULT[1]", "RESULT[2]", "RESULT[3]", "RESULT[4]", "RESULT[5]", "RESULT[6]", "RESULT[7]"]
  },
  "pins": [
    {"pin": "ui_in[0]", "port": "ui_in", "bit": 0, "electrical_role": "input", "load_role": "PROG_SER", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[1]", "port": "ui_in", "bit": 1, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[2]", "port": "ui_in", "bit": 2, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[3]", "port": "ui_in", "bit": 3, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[4]", "port": "ui_in", "bit": 4, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[5]", "port": "ui_in", "bit": 5, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[6]", "port": "ui_in", "bit": 6, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "ui_in[7]", "port": "ui_in", "bit": 7, "electrical_role": "input", "load_role": "PROG_MODE", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[0]", "port": "uo_out", "bit": 0, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "TX", "spi_transfer": "CS", "spi_result": "RESULT[0]", "i2c_transfer": "unused", "i2c_result": "RESULT[0]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[1]", "port": "uo_out", "bit": 1, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "SCLK", "spi_result": "RESULT[1]", "i2c_transfer": "unused", "i2c_result": "RESULT[1]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[2]", "port": "uo_out", "bit": 2, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "MOSI", "spi_result": "RESULT[2]", "i2c_transfer": "unused", "i2c_result": "RESULT[2]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[3]", "port": "uo_out", "bit": 3, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "RESULT[3]", "i2c_transfer": "unused", "i2c_result": "RESULT[3]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[4]", "port": "uo_out", "bit": 4, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "RESULT[4]", "i2c_transfer": "unused", "i2c_result": "RESULT[4]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[5]", "port": "uo_out", "bit": 5, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "RESULT[5]", "i2c_transfer": "unused", "i2c_result": "RESULT[5]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[6]", "port": "uo_out", "bit": 6, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "RESULT[6]", "i2c_transfer": "unused", "i2c_result": "RESULT[6]"}, "shared_pin_rationale": ""},
    {"pin": "uo_out[7]", "port": "uo_out", "bit": 7, "electrical_role": "push_pull", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "RESULT[7]", "i2c_transfer": "unused", "i2c_result": "RESULT[7]"}, "shared_pin_rationale": ""},
    {"pin": "uio[0]", "port": "uio", "bit": 0, "electrical_role": "open_drain", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "MISO", "spi_result": "unused", "i2c_transfer": "SCL", "i2c_result": "unused"}, "shared_pin_rationale": "SPI firmware never writes uio_out, so with uio_out[0] = 1 the open-drain pad is released (hi-Z) and MISO is read on uio_in[0] as a plain input; I2C and SPI are never in one firmware image. Requires uio_out[0] = 1 before SPI runs (reset value change, DR 0010 follow-up) and tolerates the SCL pull-up on MISO."},
    {"pin": "uio[1]", "port": "uio", "bit": 1, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[2]", "port": "uio", "bit": 2, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[3]", "port": "uio", "bit": 3, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[4]", "port": "uio", "bit": 4, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[5]", "port": "uio", "bit": 5, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[6]", "port": "uio", "bit": 6, "electrical_role": "input", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "unused", "i2c_result": "unused"}, "shared_pin_rationale": ""},
    {"pin": "uio[7]", "port": "uio", "bit": 7, "electrical_role": "open_drain", "load_role": "none", "metadata_class": "generic_isa_capability", "protocol_roles": {"uart_tx": "unused", "spi_transfer": "unused", "spi_result": "unused", "i2c_transfer": "SDA", "i2c_result": "unused"}, "shared_pin_rationale": ""}
  ],
  "inventory": [
    {"file": "firmware/asm/uart_tx.asm", "profile": "uart_tx", "patterns": ["asm_ports", "uart_tx_mask"]},
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
| `uart_tx_mask` | first `LDI R1, imm` in `uart_tx.asm` (the TX bit mask and idle level) and every `LDI` immediately feeding `AND`/`OR`/`XOR` |
| `spi_images` | each `LDI R2, imm` immediately followed by `OUT UO_OUT, R2`: the first is the idle image (CS high, SCLK at CPOL), every image may use only CS/SCLK/MOSI bits |
| `spi_miso_mask` | for `IN Rx, UIO_IN`, the nearest `LDI Ry` before the next `AND Rx, Ry` must equal the MISO bit mask |
| `i2c_idle_start` | the `LDI R3` feeding the first two `OUT UIO_OUT, R3`: bus-idle = SCL\|SDA, START = SCL |
| `i2c_alu_masks` | an `LDI Rn, imm` immediately followed by `AND`/`OR`/`XOR` using `Rn` must be the SCL or SDA mask (counter, data and timing literals are not pin masks and are not counted) |
| `i2c_in_masks` | as `spi_miso_mask`, SDA mask for ACK/read sampling, SCL mask for `pollN:` sites |
| `i2c_poll_mask` | the `LDI R3, imm` before each `pollN: IN` equals the SCL mask |
| `gen_strings` | the instruction string literals of `firmware/tools/gen_i2c_sr.py`, parsed with `ast` and the same line grammar as assembly |
| `bench_*` | the named module-level constants and capture specs of each bench (`TX_PIN/TX_BIT`, `CS_BIT…`, `MISO_PIN/MISO_BIT`, `SCL_PIN/SDA_PIN`, `_RELEASED`, `_ACK_PULL`, `(sda_drive << N)`, `per_scl`/`per_sda`), and `load_program`'s `ui_in` assignments |
| `top_load_wiring` / `top_uio_oe` / `top_port_passthrough` | `.mode_pin(ui_in[n])`, `.serial_in(ui_in[n])`, `assign uio_oe = …;`, whole-bus `.port_*` connections |
| `core_uio_out_reset` | the `port_uio_out <= 8'hXX;` reset literal |
| `isa_port_table` | `firmware/tools/asm.py` port codes 00/01/10/11 |
| `info_pinout` | the 24 `ui[n]` / `uo[n]` / `uio[n]` keys, their direction sections and generic labels |

Coverage is the tree as of this record: eleven committed assembly files
(`uart_tx`, `spi_mode0–3`, `i2c_fast`, `i2c_std` and the four `*_sr`/`*_sr_poll`
variants) plus `demo_roundtrip`, the generator, and four benches. UART receive
and low-baud files that PR #96 adds are **not** claimed; because the checker
fails on any uninventoried `firmware/asm/*.asm`, whoever merges them second
must add them to the inventory (and to the table's phases if they use new
pins).

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
   and unmet prerequisites. On the committed tree: `uio[0]` and `uio[7]`
   open-drain are unwired (`assign uio_oe = 8'h00;`) and `port_uio_out`
   resets to `8'h00` rather than releasing the masked pins.

Default success means results 1–3 agree with this Proposed record, **not**
that silicon implements every electrical role. `--require-implemented` also
fails while result 4 lists anything, so it fails today.

## Follow-up edits (separate issues after the keys accept this record)

None is made by this PR; the PR touches no RTL, firmware, `info.yaml` or
target-spec row.

1. **RTL** (`src/tt_um_2amlogic_protocol_emulator.v`, `rtl/protocol_core.v`):
   `assign uio_oe = 8'h00 | (8'h81 & ~uio_out)` per DR 0008, reset the
   open-drain bits of `port_uio_out` to 1, and model the mask in the I2C
   bench so the composed bus is silicon-true. Re-measure on the flow of record
   (DR 0002), flow-attributed.
2. **`info.yaml`** and the template `docs/info.md`: add the protocol-profile
   pin table and the pull-up statement; these are generic ISA labels today.
3. **If `MISO` moves** (fallback above): `firmware/asm/spi_mode0–3.asm`
   (`IN … UIO_IN` and the MISO mask), `verification/test_firmware_spi.py`
   (`MISO_PIN`/`MISO_BIT`, the `dut.uio_in` driver), `firmware_templates.py`
   if it embeds the SPI template, and this table.
4. **If I2C SCL/SDA move**: `firmware/asm/i2c_*.asm`,
   `firmware/tools/gen_i2c_sr.py` (and regenerate the `*_sr` files),
   `verification/test_firmware_i2c.py` (`SCL_*`/`SDA_*`, `_RELEASED`,
   `_ACK_PULL`) and `verification/test_firmware_i2c_sr.py`.
5. **If UART TX moves**: `firmware/asm/uart_tx.asm` and
   `verification/test_firmware_uart.py`.
6. **If load pins move**: the top-level `.mode_pin`/`.serial_in`,
   `verification/test_protocol_emulator.py::load_program`, `info.yaml`.

## Not decided here

- Ratification (this record is Proposed; no Status line is flipped).
- The RTL change, the pad wiring, and whether the demo board has pull-ups.
- Any target-spec row's target or state; row 5 and row 12 are not edited.
- The UART RX pin (PR #96): to be added to this table when that PR lands.

## Cross-references

[DR 0001](0001-isa.md) (ISA, ports, timing), [DR 0004](0004-target-spec-ratification.md)
and [DR 0006](0006-two-key-ratification-never-ran.md) (ratification rules),
[DR 0008](0008-open-drain-uio-oe-wiring.md) (mechanism this record instantiates),
issues #94 (this), #75 (open-drain), #23 (firmware epic), #104 (I2C on the
real core; physical pad wiring explicitly out of scope there).
