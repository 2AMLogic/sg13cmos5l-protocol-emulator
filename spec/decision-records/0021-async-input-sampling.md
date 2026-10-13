# 0021: Direct (Unsynchronized) Sampling of Asynchronous Pins by `IN` — Accept, Mitigate in Firmware Where a Branch Is Single-Shot, Defer the Synchronizer

Status: **Proposed 2026-10-13.** Like DRs 0001–0005, 0007, 0008 and 0010–0020,
this record is a proposal. The two-key (`RATIFY-KEY`) mechanism has not bound
it (DR [`0006`](0006-two-key-ratification-never-ran.md), issue #44). It
records an existing, previously undocumented property of the frozen design. It
changes no RTL, no instruction, latency, flag, reset value or assembler rule,
edits no pinned record (DR 0017 section 3) and no target-spec value, relaxes
no ratified text, and makes no row met.
Date: 2026-10-13
Issues: #303 (the finding); #44 (ratification).

**Numbering note.** When this record was numbered (2026-10-13), `origin/main`
had DRs 0001–0018 and 0020. Two remote branches carry a record numbered 0019
(`0019-boot-rom-timing-watch.md` and `0019-open-drain-pad-data-held-low.md`;
their PRs #254 and #256 are closed). This record is **0021** so that it
collides with neither, as DR 0020 stepped over 0009 and 0019. It depends on
neither.

## Context

### 1. What the design does today

`IN Rd, port` copies a pin byte into a register on the retiring edge, with no
register stage in front of it:

- `rtl/protocol_core.v:459`:
  `wire [7:0] in_val = (rs == PORT_UI_IN) ? port_ui_in : port_uio_in;`, a
  2-way mux from the port inputs and nothing else.
- `rtl/protocol_core.v:743` (`OP_IN`): `regs[rd] <= in_val;`. The capture
  flop is the destination register itself.
- `src/tt_um_2amlogic_protocol_emulator.v:174-175`:
  `.port_ui_in (ui_in), .port_uio_in (uio_in)`. The template's input pins
  reach the core ports by direct wiring.

So `IN` is 1 cycle (DR 0001's latency table) because there is no
synchronizer. There is none anywhere on the path. Every input a program is
meant to read is asynchronous to `clk` (UART RX, SPI MISO, I2C SDA and SCL
including a stretching peripheral's SCL release, PS/2 clock and data, and the
boot-time strap pins). A transition inside the setup/hold window of the
capturing flop can leave that flop metastable. It resolves to 0 or 1 after an
unbounded (but exponentially unlikely to be long) time, and in the meantime
the register bit fans out to the ALU, the flag logic and the output port
muxes, which can see it differently. Mean time between failures is a
property of the cells and the clock; this record does not compute it (see
Limits).

Nothing in `spec/` or `docs/` decided this. DR
[`0015`](0015-stretch-protocols-with-neutral-primitives.md) costs a two-flop
synchronizer for its *proposed, unbuilt* sampler primitive ("about 70 flops
(two-flop input synchronizer, ...)", "adds a fixed two-cycle latency"); it
says nothing about the shipped `IN` path.

### 2. Why no bench shows it

`verification/uio_pads.py` ("Timing") resolves the pads combinationally with
zero delay, and the benches sample at the `ReadOnly` phase of a settled time
step. An RTL, zero-delay gate-level or SDF simulation therefore always
captures a clean 0 or 1, and the pad model cannot make a flop metastable. The
property is invisible to every existing bench by construction.

### 3. Survey of the shipped firmware

Read from `firmware/asm/` (every image that contains an `IN`; the
`random-regression` artifact copies are generated from the same templates and
not listed). For each: what the single sample feeds, and what a wrong or
late-resolving sample costs. "Wrong" means the sample returns the other
side of a transition that is within the capture window; a stable line is
never mis-sampled by this mechanism.

| Firmware | What branches on or consumes one `IN` | Cost of a wrong / metastable sample |
|---|---|---|
| `uart_rx.asm`, `uart_rx_115200.asm`, `uart_rx_9600.asm`: `poll` (start-edge detect, `IN`/`AND`/`BNZ`, a 3-cycle loop) and `sync` (wait for idle high) | A pin-dependent branch, **re-read every 3 cycles** | **Tolerant.** A sample taken at the falling edge reads either side; the start is seen one poll earlier or later, i.e. the edge is located "to within 3 cycles", which the file already counts in its +-1.5-cycle bit-0 placement. A wrong sample on a stable line cannot occur. |
| the same images, 8 data samples and the stop-bit sample | Not a branch: the byte is accumulated by `SHF`/`OR`; only the stop-bit sample reaches a branch (`BZ poll` or `JMP sync`) | **Tolerant.** Each is taken at the bit centre (25 cycles from an edge at 50 cycles/bit, 217 at 434, 2,604 at 5,208), so an edge in the capture window needs a bit-rate error far outside the +-4 % the bench measured (`verification/records/firmware-uart-rx/records/20261009-084132-d79b51d.md`). One bad data sample flips one data bit of one frame; the stop-bit sample can raise a false framing error, which re-syncs. |
| `spi_mode0..3.asm`, functional burst (10 cycles/bit): `IN` MISO, `AND`, `SHF`, `OR` into `R0` | No branch; the code is straight-line | **A flipped bit in one received byte; no control-flow effect.** Mode 0 and 2: MISO was launched at the previous trailing edge and is stable at the `IN`. **Mode 1 and 3: the `IN` retires one core cycle after the leading-edge `OUT`, which is the edge the peripheral launches MISO on** (the file's own order: `OUT` leading edge, then `IN`, then the trailing `OUT` four instructions later). That is the one place in the shipped set where a sample sits next to an asynchronous edge by design rather than by chance, so it is a setup-margin item first and a metastability item second. See Open items. |
| `spi_mode0..3.asm` ceiling burst and `spi_mode0_burst3.asm` | `IN` result is not extracted (ceiling) or is an `IN` in a straight line | **No effect on control flow**; the ceiling burst's sample is not used for the checked byte. |
| `i2c_fast_sr_poll.asm`, `i2c_std_sr_poll.asm`: `pollN: IN`, `AND`, `BZ pollN` after each SCL rise | A pin-dependent branch, re-read every 3 cycles; the line is SCL, the controller's own released line, which a stretching peripheral may hold low | **Tolerant.** A wrong low costs one more 3-cycle iteration. A wrong high happens only inside the same one-sample window of the real rise, so the program proceeds at most one poll period (3 cycles) before it would have: the hold that follows is counted from the `IN`, so the hold after the real rise is up to 3 cycles shorter than its budget in that single phase. The file states the unstretched rise phase is budget + 2 cycles, which is the only slack. |
| `i2c_*_sr.asm` and the same poll images: the read-data sample (`IN` "sample the bus", 8 per read byte) | Not a branch; ORed into `R0` | **A flipped bit in the one read byte.** SDA is launched by the peripheral after SCL falls and the sample is taken after the SCL-high poll, hundreds of cycles later, so a conforming peripheral is stable (UM10204 data valid time). |
| `i2c_fast.asm` (`ack1_high`, `ack2_high`) and `i2c_std.asm` (offset 121 of the high phase): address-ACK sample, followed by `AND` and `BNZ stop_from_addr`; offset 30 in the fast image | **A single-shot branch.** One `IN`, no re-read | **Not tolerant by construction.** A wrong ACK sample takes the NACK path: the controller issues a STOP and abandons the transfer (`i2c_fast.asm`, address ACK). It is not retried inside the program. Protocol-stable in practice: the peripheral pulls SDA low during SCL low and holds it for the whole high phase, so the sample at offset 30 of a 60-cycle high is 30 cycles from the nearest legal change. The risk exists only for a non-conforming peripheral or a noisy edge, and is a spurious abort of one transfer. The data-ACK sample in `i2c_fast.asm` (`ack2_high`) feeds the `Z` flag only and no branch reads it. |
| `ps2_device.asm`: bus-state poll (`tw_poll`, `idle_wait`), CLK-inhibit check at `w_mid`, data read at `rx_action` | Bus-state polls are re-read every ~20 cycles; the inhibit check and `rx_action` read once per clock pulse | **Tolerant or self-correcting.** The PS/2 timing is tens of microseconds (about 1,000 to 2,000 cycles per phase, `ps2_device.asm` header table); a sample within a cycle of a transition is far from the bit's sampling instant. A wrong inhibit read causes a spurious retransmit; the device retries by protocol (`tx_wait`). A wrong data read in `rx_action` becomes a parity error, which the device answers with `0xFE` (resend). |
| `boot/boot_rom.asm`: strap read (`IN R0, UI_IN`, `ui_in[6:5]`) and the UART load (`rx_poll`, `rx_bit`, same shape as UART RX above) | The strap read is a **single-shot branch** that selects warm start, SPI-flash boot or UART load; the UART load is as the UART RX rows | The strap pins are static configuration, stable long before and after the read; the exposure is a strap that is changing at reset release, which the operator controls. A wrong read selects the wrong boot source; recoverable by reset. The UART load polls and samples as UART RX does. |
| `demo_roundtrip.asm` | One `IN UI_IN` of bench-held pins | None (bench-driven static value). |
| `uart_tx*.asm`, `ws2812.asm` | No `IN` | Not applicable. |

Verified by reading the code at the line of each `IN` named above, not by
simulation. Counts of pin-dependent branches in the poll images are stated by
the files themselves (`BZ poll` is the only data-dependent branch per polled
rise).

**Result of the survey.** Every re-reading loop (UART start-edge poll, I2C SCL
poll, PS/2 bus poll) is tolerant: a wrong sample costs 3 to ~20 cycles in a
loop that is already running. Every data sample that is accumulated rather than
branched on costs one flipped bit in a received byte, which the protocol layer
(UART framing, PS/2 parity, I2C ACK) can detect or retry in some cases and
cannot in others. Exactly **one** branch is single-shot and state-changing in
the shipped protocol firmware: the I2C fast-mode address-ACK branch. The
boot-strap branch is also single-shot but reads a static pin.

## Decision (proposed)

### 4. Options

| | Description | Cost |
|---|---|---|
| (a) Accept and document | `IN` stays a direct capture; this record is the documentation | No RTL, no firmware, no cycle change. Residual risk: an asynchronous edge in the capture window leaves one `IN` bit unresolved for a time; per the survey the exposure is one flipped bit in one frame, or one aborted I2C transfer. No evidence either way (see Limits). |
| (b) Firmware mitigation | Where a single `IN` decides control flow, take two `IN`s a few cycles apart and branch only on agreement (retry or take the safe path on disagreement), or a three-sample majority. | Costs cycles only in the image that adopts it, and only where there is slack. The I2C fast ACK sample sits inside a 60-cycle high phase between `WAIT 28` and `WAIT 19`; a second `IN` and compare fit inside those waits by shortening them, so the `BNZ` keeps its offset (the file already uses this technique when it moved the sample). No RTL, no pin, no ISA change. A double `IN` does **not** remove metastability (two samples of one flop-capture can both be unresolved) but turns a single coin flip into an agreement test across independent capture events, which is the usual firmware-level mitigation; it is not a proof of a bound. Re-opens the byte-for-byte firmware evidence for any image it changes. |
| (c) Hardware two-flop synchronizer | Register `ui_in`/`uio_in` through two flops before `in_val` | `IN` becomes 3 cycles instead of 1 (+2 cycles; DR 0015 costs the same for its primitive). That changes the ratified latency table (DR 0001), the `no_data_dependent_latency` argument (row 3) and every firmware cycle budget that counts an `IN`: every image with an `IN` listed in the survey (17 `.asm` files under `firmware/asm/`), the SPI ceiling burst (no room: 4 cycles/bit), and the I2C/UART phase literals. It changes `rtl/protocol_core.v` and the top, which are pinned by DR 0017: it needs an `isa-change` amendment and a record, and invalidates the committed evidence (formal proof, gate-level, SDF, random regression). It adds about 16 flops for the two 8-bit ports (arithmetic, not a synthesis result). It reopens the DR 0017 freeze for a risk the survey rates as bounded. |

### 5. Recommendation

1. **(a) for every line the survey found tolerant**: the UART RX, the I2C SCL
   poll and read data, the PS/2 device, the SPI data path and the boot UART
   load. This record is their documentation. No firmware change.
2. **(b) for the one single-shot state-changing branch the survey found, the
   I2C fast-mode address-ACK branch** (`i2c_fast.asm`, and `i2c_std.asm`, which has the same branch at a longer offset; the `_sr` and `_sr_poll` images do not
   branch on the ACK): optionally, as a firmware-only
   change in its own issue, double-`IN` with agreement, using existing wait
   slack so no phase literal moves. Not done here, because a firmware change
   re-pins that image's evidence, and the exposure it covers needs a
   non-conforming peripheral. The boot-strap branch is left as is: static
   pins, recoverable by reset, and the boot ROM is a hardware ROM image that
   would need a regenerate.
3. **(c) deferred**, not rejected: it is the correct engineering answer for
   an ASIC that is meant to read arbitrary pins, and it is the first thing
   to do if the design is respun after the 2027-01-18 submission. It is
   listed in `spec/gap-to-submission.md` as a deferral. Per the deadline-
   discipline rule, a change that reopens DR 0017 and moves every cycle
   budget is deferred unless the direct-sampling design is shown unsafe, and
   the survey does not show that.

Judges who know silicon will ask. The honest statement is: the design samples
asynchronous pins directly; every shipped firmware loop either re-reads or is
protocol-stable at its sample instant; one single-shot branch is exposed to
a non-conforming peripheral; and no result in this repository can show the
opposite.

## Limits — what stays unverified

- **No bench shows metastability.** Every simulation here (RTL, zero-delay
  gate-level, SDF-annotated) uses a deterministic input model
  (`verification/uio_pads.py`) that cannot produce an unresolved sample. This
  record is a reading of the RTL and the firmware, not a measurement.
- **Static timing does not cover this as a synchronization crossing.** STA
  checks the pad-to-flop path as an ordinary setup/hold path against whatever
  input delay the constraints give it; it does not report metastability
  likelihood, MTBF, or the number of synchronizer stages required for an
  asynchronous crossing. This record did not inspect the input-delay
  constraints in the template's SDC and makes no claim about them.
- **Which flow would have to report it.** The flow of record is the Tiny
  Tapeout LibreLane flow (DR 0002; `spec/target-spec.md` row 4,
  "flow of record per DR 0002"). Any pad-to-flop timing number or MTBF
  argument belongs to that flow, with its corners. The `klt` flow has no
  timing evidence for any of the 6 declared corners (0 of 6, blocked on
  `2AMLogic/klayout-tools#2635`; `spec/target-spec.md`, row 4 and the klt
  note at line 255; issue #20). No number is cited in this record from either
  flow. The cycle counts above are core cycles read from the assembly, not a
  flow result.
- **Capture-flop cells and clock period** are the template's and
  LibreLane's; the unconfirmed row 4 clock is not assumed here.
- **The program-load pins** (`ui_in[0]` serial data and the load phase's
  other pins) are also asynchronous inputs and were not surveyed. They are
  sampled by hardware, not by `IN`.

## Alternatives considered

- **Do nothing and say nothing.** Rejected: the reason this record exists.
- **Make (c) the default now.** Rejected for the reasons in option (c): it
  reopens DR 0017, moves the ratified 1-cycle `IN`, and invalidates the
  evidence set for a risk the survey bounds.
- **Add a synchronizer only on `uio_in[2]`/`uio_in[3]`.** Rejected: the same
  latency and freeze cost, with a per-pin special case in the otherwise
  uniform `IN`.

## Consequences

- The design's input-sampling property is on record, with a survey a
  reviewer can re-check by reading `firmware/asm/`.
- No RTL, firmware, pinned-file hash, `spec/isa-freeze.json` entry or row
  status moves. `scripts/check_isa_freeze.py` is unaffected (this record is
  not a pinned file).
- A future `IN`-latency change, or any new image that branches once on an
  asynchronous sample, must cite this record.

## Open items

- **SPI modes 1 and 3: MISO sample one core cycle after the peripheral's
  launch edge.** Whether a real peripheral's clock-to-MISO delay fits inside
  one core cycle is a setup-margin question, separate from metastability. The
  bench peripheral drives MISO within the same clock (`drive_miso`, "1 ns"
  after the clock edge). A margin review, and a later `IN` position if there
  is slack in the 10-cycle bit, are for a follow-up issue; not done here.
- **The optional I2C fast-ACK double-`IN`** (recommendation 2), as its own
  firmware issue if the operator wants it.
- **The synchronizer (option c)** for a post-submission respin.
- **The LibreLane constraints** for the input pins (input delays) were not
  read for this record.
