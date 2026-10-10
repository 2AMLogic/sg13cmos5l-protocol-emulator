# How this design was verified

Status: **current report, written before the final ISA freeze.** Deliverable D4
of [`docs/submission/README.md`](README.md). Issue #214.

- **Reviewed commit:** `main` @ `9fb7815` (2026-10-10). Every record cited below
  is a file at that commit. Nothing here is a new measurement: this document
  reads the existing evidence, it does not run anything.
- **Not frozen.** DR 0012 (control space) and DR 0013 (program loading) are
  implemented but **Proposed**; the submission ISA is not frozen (#135), and
  DR 0013's UART load has an open finding (F8, #211). A change to the RTL
  makes the records for it stale, and they are then re-minted, not edited.
- **Provisional governance.** The target spec and DRs 0001-0004 are **Proposed,
  not ratified**: the two-key ratification never ran
  ([DR 0006](../../spec/decision-records/0006-two-key-ratification-never-ran.md),
  #44). Every "pass" below is evidence against a proposed contract. No spec
  row was relaxed to obtain a result, and no row's grade is changed by this
  document (see [Spec grades](#spec-grades-are-unchanged)).
- **No silicon.** Nothing has been taped out or measured. Every figure is a
  simulation, a formal proof over a stated model, or a tool report.

If you read one section, read [What this does not show](#what-this-does-not-show).

## 1. The method in one page

The ISA is the product: UART, SPI and I2C are **firmware** on one core, and no
protocol has a dedicated block in RTL. So the evidence has to show two
things: (1) the core obeys its timing contract, and (2) real firmware, run on
that core, produces waveforms that an *independent* checker accepts.

| Layer | What it is | Oracle (written independently of the RTL) |
|---|---|---|
| Instruction level | Every opcode and control-space register, per clock edge | A table-driven ISA simulator written from DR 0001/0012 (`verification/reference_models/isa.py`), compared in lockstep |
| Timing contract | No data-dependent latency; pin writes land one cycle after the `OUT` | Formal monitors (SVA) written from DR 0001's text, checked with Yosys/ABC/Z3 |
| Protocol level | Committed firmware drives pins; a model grades the waveform | `verification/reference_models/{uart,spi,i2c,spi_flash}.py`, validated on their own (11/11, `protocol-reference-models`) |
| Load and boot | Serial load, boot ROM, SPI-flash and UART boot, reset/power-up | An independent UART host (`uart_boot_host.py`), SPI-flash model, CRC-16/XMODEM from `binascii`, and a reset-coverage listing |
| Netlist level | The same benches on the LibreLane routed netlist | The same oracles; zero-delay, then SDF-annotated for the core bench |

Two rules make a pass worth citing:

- **A bench that cannot fail proves nothing.** Every family below has
  fault-injected negative controls (mutated firmware, mutated RTL, stuck-at
  netlist faults), each required to be *rejected* by the same oracle. The
  controls are listed in section 3.
- **Records are append-only.** A result is superseded by a later record that
  says why, never edited. `python3 verification/check_records.py` (in
  `npm run lint`) enforces append-only against `origin/main` and recomputes
  the hash of every input cited by every live record, so a record whose
  source has since changed fails the lint. At `9fb7815` it reports
  `PASS: all records valid` (run for this document).

## 2. Which flow produced which evidence

Per project rules, a number is never reported without its flow. The levels are
not interchangeable, so the matrix in section 3 names one for every row.

| Level | Flow | Delays | What it can and cannot show |
|---|---|---|---|
| **RTL simulation** | Icarus 13.0 + cocotb 2.1.0, via `klt functional-verification` | none | Function and cycle counts. No synthesis or timing information. |
| **Formal** | Yosys + `yosys-smtbmc`/Z3, and `yosys-abc` (`scorr` + `pdr`) | none | Proofs hold for the *harness model* only (section 4). |
| **Zero-delay gate level** | Icarus + cocotb on the **LibreLane** routed netlist (`flow/run-firmware-gate-level.sh`, `flow/run-reset-power-up-gate-level.sh`) | none | Catches synthesis divergence (X-propagation, inferred state). Says nothing about timing. |
| **SDF-annotated routed simulation** | Same netlist with the LibreLane post-route SDF, three PVT corners (`flow/run-post-layout-sdf.sh`) | back-annotated, with omissions (section 5) | Does the core bench's outcome change with real delay. Core bench only. |
| **STA** | **LibreLane** post-route OpenSTA, 20 ns clock, three corners | n/a | LibreLane numbers only. The klt STA leg is blocked by klayout-tools#2635 and claims nothing. |
| **Physical signoff** | The Tiny Tapeout `gds`/`precheck` workflow (LibreLane); klt DRC/extract/LVS as a second opinion | n/a | See section 6. |
| **Synthesis area** | **klt/Yosys** flow (`synthesis-baseline`) and, separately, LibreLane's own synthesis | n/a | Two flows, two numbers, never merged. |

The pad model used by the I2C and SPI evidence is **logical and zero-delay**
(`verification/uio_pads.py`). Per pin, `uio_oe` and `uio_out` drive a resolved
line with an optional pull-up, and `uio_in` reads the resolved line. It is
useful because it exercises the design's own `uio_oe`; it says nothing about
pull-up rise time or pad drive strength.

## 3. Claim matrix

Records are the latest live ones at `9fb7815`. "Repro" is the exact command from
the record's *Run configuration*; the one-line cold start for the RTL benches is
`scripts/run-rtl-benches.sh` after `./scripts/setup-env.sh`. The index of every
command, bench and pinned tool is
[`manifests/evidence/testbenches.txt`](../../manifests/evidence/testbenches.txt).

### 3.1 Instruction set and timing contract

| Claim | Oracle | Level / flow | Record | Repro | Limits |
|---|---|---|---|---|---|
| All 16 opcodes and the DR 0012 control space match the ISS on every edge of 400 seeded programs (27,983 edges); counted coverage gate met | `reference_models/isa.py` | RTL, Icarus | [isa-lockstep 20261010-132631](../../verification/records/isa-lockstep/records/20261010-132631-8372c57.md): PASS 4/4 | `klt functional-verification verification/request-isa-lockstep.json --format json` | Programs run from program memory after a serial load; boot-ROM fetch is not in scope. Reads RTL hierarchy, so no gate-level lockstep. The four details DR 0001 leaves open are ruled by DR 0016, which is **Proposed**. |
| ISS lockstep catches single-defect cores | Ten mutant cores (`isa_lockstep_mutants.py`) | RTL | same record | `python3 verification/isa_lockstep_mutants.py --out <dir>` | The mutant list is the record's; a defect outside it is not claimed. |
| Control space: reset values, readback, reserved indices, fixed stalls, I2C images use `UIO_OD` open-drain | Bench plus mutants | RTL | [control-space 20261010-132618](../../verification/records/control-space/records/20261010-132618-8372c57.md): PASS 9/9 | `klt functional-verification verification/request-control-space.json --format json`; `python3 verification/control_space_mutants.py --out <dir>` | Zero-delay; gate-level copy in 3.5. |
| `no_data_dependent_latency` holds on the shipped core, from either instruction source | Independent SVA monitor over DR 0001's latency table | **Formal**, bounded (BMC depth 30) | [no-data-dependent-latency 20261009-215419](../../verification/records/no-data-dependent-latency/records/20261009-215419-1dc1842.md): PASS, 13 covers reached | `./verification/formal/run-no-data-dependent-latency.sh <dir>`; `verification/formal/test-mutant-gate.sh` | **Bounded, not unbounded**: k-induction did not close (the record says why). The harness quantifies over a free 8-word program table and an 8-word ROM table, with `serial_loaded` a constant per trace. |
| `pin_write_latency`: an `OUT` is visible one cycle later, never earlier, nothing else moves an output | Independent shadow-ISA monitor | **Formal**, ABC `scorr`+`pdr` | [pin-write-latency 20261009-214736](../../verification/records/pin-write-latency/records/20261009-214736-1dc1842.md): 6/6 (EDGE) and 8/8 (FINE) proved; 15 of 15 mutants rejected | `./verification/formal/run-pin-write-latency.sh <dir>` | **Unbounded only within the harness model**, and resting on one engine; the scorr-independent bounded cross-check reached only 9 cycles (EDGE) and 14 samples (FINE). Serial shift-in is not modelled. |

### 3.2 Protocol firmware, directed benches

Each bench loads a committed program over the real serial load pins, runs it on
`tt_um_2amlogic_protocol_emulator`, and hands the captured pin waveform to an
independent model.

| Claim | Oracle | Record | Repro | Limits |
|---|---|---|---|---|
| UART TX (three rates) | `reference_models/uart.py` | [firmware-uart 20261010-132629](../../verification/records/firmware-uart/records/20261010-132629-8372c57.md): PASS 3/3 | `klt functional-verification verification/request-firmware-uart.json --format json` | Cycles, not baud: the clock is unconfirmed (row 4). |
| UART RX (50 / 434 / 5,208 cycles per bit) on `ui_in[1]`, bounded jitter and ±2 % rate error, cycle-exact sample spacing; `ui_in[0]` has no effect | The model's encoder/decoder | [firmware-uart-rx 20261010-141633](../../verification/records/firmware-uart-rx/records/20261010-141633-5bd61ad.md): PASS 10/10 | `... request-firmware-uart-rx.json ...` | RTL, cycles not baud. |
| SPI modes 0-3, CS/MOSI/SCLK on `uio[0]/[1]/[3]`, MISO `uio[2]` | `reference_models/spi.py` | [firmware-spi 20261010-132628](../../verification/records/firmware-spi/records/20261010-132628-8372c57.md): PASS 3/3 | `... request-firmware-spi.json ...` | Pad model is logical, zero-delay. |
| I2C Standard and Fast, write; write / repeated START / read with clock stretching | `reference_models/i2c.py` (checks against NXP UM10204 AC limits) | [firmware-i2c 20261010-132625](../../verification/records/firmware-i2c/records/20261010-132625-8372c57.md): PASS 4/4; [Sr/stretch 20261010-132626](../../verification/records/firmware-i2c/records/20261010-132626-8372c57.md): PASS 5/5 | `... request-firmware-i2c.json ...`, `... request-firmware-i2c-sr.json ...` | Runs through the design's own `uio_oe` (issue #136). Standard mode uses 435 cycles per ordinary clock (about 114.9 kHz at a *nominal* 50 MHz) against the proposed 100 kHz target; the ruling is open (#125). |
| Reference models are sound on their own, including a 2.5 %-slow UART negative control and frame-pitch grading | Self-validation with random stimulus | [protocol-reference-models 20261010-002540](../../verification/records/protocol-reference-models/records/20261010-002540-b63cb8f.md): PASS 11/11 | `... request-protocol-models.json ...` | UART model documents an isolated-frame blind spot, asserted by a test. |
| Pad model resolves the real `uio_oe`/`uio_out`; five pad-path RTL defects are caught by both I2C benches | `verification/uio_pads.py` + `test_uio_pad_resolution.py` | [uio-pad-model 20261010-132636](../../verification/records/uio-pad-model/records/20261010-132636-8372c57.md): 5/5, 4/4, 5/5 | `... request-uio-pads.json ...`; `python3 verification/uio_pad_mutants.py --out <dir>` | **Logical, zero-delay pad model**: no electrical behaviour. |

### 3.3 Constrained-random regression

| Claim | Oracle | Record | Repro | Limits |
|---|---|---|---|---|
| One recorded seed, `20261009`: 20 generated programs per family for UART TX, SPI, I2C write, I2C write/Sr/read with seeded stretching, and UART RX, each assembled with the DR 0003 assembler and graded by the independent models | `reference_models/{uart,spi,i2c}.py` | [random-regression 20261010-141815](../../verification/records/random-regression/records/20261010-141815-5bd61ad.md): PASS 10/10 (chain 1 of 3 identical re-mints; see the note below) | `klt functional-verification verification/request-random-regression.json --format json` | RTL only. **Not run on gates or with SDF.** 20 cases per family is the shared-host default; `RANDOM_REGRESSION_CASES=<n>` appends more. |

Note on the record text: the *Claim* prose of that record was carried forward
from before the UART RX family (#192) and does not name it, while its *Result*
(10 tests, listed in `results_icarus.xml`) includes `test_uart_rx_random_programs`
and `test_uart_rx_negative_controls`. The family is in the bench
(`verification/test_random_regression.py`) and was introduced by the earlier
re-mint `20261010-122206-ff79ed0`, whose *Supersedes* note describes it. It is
not claimed beyond that. Claims are not edited; this paragraph is the
correction.

**Deterministic seed replay.** `RECORDED_SEED` is mirrored into the request's
`random_seed` and asserted equal by the first test. Each case draws from its own
RNG seeded by `seed:protocol:index`, so case *i* of a larger sweep is
byte-identical to case *i* of the default one. Every failure message leads
with `seed=<S> protocol=<p> index=<i>`, and
`python3 verification/firmware_templates.py --seed S --out DIR` regenerates the
failing `.asm` byte for byte.

### 3.4 Load, boot and reset

| Claim | Oracle | Record | Repro | Limits |
|---|---|---|---|---|
| Serial program-load path and loader pin sequence | CRC-16/XMODEM from `binascii`; loader generator tests | [firmware-loadseq 20261010-132627](../../verification/records/firmware-loadseq/records/20261010-132627-8372c57.md): 6/6 and 3/3 | `... request-loadseq.json ...`, `... request-loadseq-top.json ...`; `python3 firmware/tools/test_loadseq.py` | The `PM_CRC` readout on `uo_out` (DR 0013 layer 1) is not built (#167 open). |
| Boot ROM: with `MODE` low the core runs the ROM and never decodes program memory unless a boot program verified the image; warm start refuses signature `0x0000` | Independent ISA prediction of the idle state; ROM mutants | [boot-rom 20261010-132615](../../verification/records/boot-rom/records/20261010-132615-8372c57.md): PASS 7/7, 13 of 13 mutants caught | `... request-boot-rom.json ...`; `python3 verification/boot_rom_mutants.py --out <dir>` | RTL. DR 0013 is Proposed. |
| SPI-flash boot reads one clean mode-0 `0x03` transaction, runs only a signed image, blank/zero/corrupt flash never reaches `RUN` | `reference_models/spi_flash.py` | [boot-spi 20261010-132616](../../verification/records/boot-spi/records/20261010-132616-8372c57.md): PASS 6/6, 12 of 12 mutants caught | `... request-boot-spi.json ...`; `python3 verification/boot_spi_mutants.py --out <dir>` | RTL. A model of one flash behaviour, not a part datasheet. |
| UART load at nominal rate and ±2 %, corrupted payloads, bad CRCs and a wrong magic never reach `RUN`; a loaded `uart_tx` program is graded by its own model | `uart_boot_host.py` | [boot-uart 20261010-132617](../../verification/records/boot-uart/records/20261010-132617-8372c57.md): PASS 8/8, 7 of 7 ROM mutants caught | `... request-boot-uart.json ...`; `python3 verification/boot_uart_mutants.py --out <dir>` | **Open finding F8**, next row. |
| **Finding, not a pass claim:** the UART load's count byte is outside the CRC; a constructed image whose truncated prefix CRC equals the next word is accepted after a single count-bit flip and reaches `RUN` | The bench asserts the observed (undesirable) behaviour | [boot-uart count alias 20261010-164351](../../verification/records/boot-uart/records/20261010-164351-57c5c8c.md); DR 0013 finding F8 | `klt functional-verification verification/request-boot-uart-count-alias.json --format json` | RTL only, not on gates. Probability about 1 in 65,536 for an arbitrary image, 1 for the constructed one. "A bad length never reaches `RUN`" therefore holds for the tested cases only. Tracked in #211. No spec was relaxed. |
| Reset and power-up (row 14 a, b, c) on the LibreLane netlist: every flop's `RESET_B` is `rst_n` alone (178 flops; one SRAM macro unreset, justified); X and seeded random power-up states agree; reselect reproduces the first run | Reset-coverage listing; the same bench across seeds | [reset-power-up 20261010-133700](../../verification/records/reset-power-up/records/20261010-133700-a0f91e3.md): 5/5, all three negative controls fail as required | `PDK_ROOT=<pdk> ./flow/run-reset-power-up-gate-level.sh` | Zero-delay. The host's reload obligation after deselect is in `verification/README.md`. |

### 3.5 Gate level and post-route

| Claim | Oracle | Level / flow | Record | Repro | Limits |
|---|---|---|---|---|---|
| The directed firmware benches (UART TX 3, UART RX 10, SPI 3, I2C 4, I2C Sr 5), control space (9), boot ROM (7), SPI boot (6) and UART boot (8) pass on the routed netlist; each of nine modules fails on its own stuck-at fault (and the SPI/I2C modules on a `uio_oe[3]` stuck-at-0) | The same oracles as RTL | **Zero-delay**, LibreLane netlist of gds run 38054423540 (`a0f91e3`) | [firmware-gate-level 20261010-161300](../../verification/records/firmware-gate-level/records/20261010-161300-a0f91e3.md): 21 rows, `as_required` on every row | `PDK_ROOT=<pdk> ./flow/run-firmware-gate-level.sh --full --control-space --boot-rom --boot-spi --boot-uart` | `test_boot_uart` is pin-only on gates (white-box reads and two long runs are skipped). No SDF, no SRAM timing, no pad characterization. Not the constrained-random regression. |
| The core bench (12 pin-observing tests) passes at all three corners with real post-route delay | Same bench file, drive/sample aligned to the SDC (`verification/sdf_alignment.py`) | **SDF-annotated**, LibreLane netlist + SDF | [post-layout-sdf-regression 20261010-133000](../../verification/records/post-layout-sdf-regression/records/20261010-133000-a0f91e3.md): 12 passed, 0 failed, 1 skipped at each corner | `KLT_BIN=<klt> PDK_ROOT=<pdk> ./flow/run-post-layout-sdf.sh --run-id 38054423540` (or `--from <dir>`) | Section 5. The skipped test is white-box and is *skipped, not passed*. |

The `a0f91e3` netlist is current for the design: `git diff a0f91e3..9fb7815 --
src rtl info.yaml firmware/build/boot` is empty.

One inconsistency inside the cited gate-level records is left visible rather
than corrected: their *Design provenance* bullet names the older `704a3fb`
netlist path, while their *Claim*, the runner's `NETLIST` default
(`flow/run-firmware-gate-level.sh`) and `testbenches.txt` all name the
`a0f91e3` frozen copy. The runner default is the authority for what ran.

### 3.6 Timing, area and signoff (numbers, by flow)

| Figure | Flow | Record |
|---|---|---|
| 20 ns (50 MHz) closes at all three corners, 0 setup and 0 hold violations. Worst setup +3.631 ns (`nom_slow_1p08V_125C`), worst hold +0.1043 ns (`nom_fast_1p32V_m40C`). Max-slew violation on the SRAM macro's `A_WEN`: 1 per corner (#201). | **LibreLane**, post-route OpenSTA | [librelane-corner-timing 20261010-133200](../../verification/records/librelane-corner-timing/records/20261010-133200-a0f91e3.md) |
| Top: 1,614 instances, 23,729.0 um^2 | **klt/Yosys** synthesis (typ corner deck, 20 ns recipe) | [synthesis-baseline 20261010-133300](../../verification/records/synthesis-baseline/records/20261010-133300-a0f91e3.md) |
| Placed standard-cell area 30,745.0 um^2 (2,210 instances) | **LibreLane** | the corner-timing record above |
| klt STA over six corners | klt | [sta-corner-sweep 20261010-133400](../../verification/records/sta-corner-sweep/records/20261010-133400-a0f91e3.md): **BLOCKED**, 0 of 6 corners, klayout-tools#2635. No number. |

The two area numbers come from different synthesis tools and are reported side
by side; a mismatch is a finding, not a figure to choose between.

## 4. Formal scope, stated plainly

- **Which engine proves what.** `pin_write_latency`: ABC `scorr` + `pdr` proves
  the properties for the harness model without a depth bound. The
  `scorr`-independent bounded cross-check is shallow (9 cycles EDGE, 14
  samples FINE). So the *unbounded* claim rests on one engine and on the
  harness being faithful. `no_data_dependent_latency` is **bounded** (BMC depth
  30); its k-induction did not close, and the record gives the reason.
- **What the harness is.** A free 8-word program table behind a registered
  fetch (plus a free 8-word ROM table), a mode-pin phase model with a
  free-length load window, reset synchronised to the clock. It does not model
  the serial shift-in, and it does not model the real 256-word macro.
- **Property teeth.** Mutants of the real core are rejected, including a
  falling-edge variant that passes the once-per-cycle model and fails only the
  between-edge model, which is why a once-per-cycle result is not a claim about
  behaviour between edges.
- **What was not written.** The ACK-window property row 12 names does not exist,
  and nothing claims it. The formal properties are about the core's timing
  contract, not about any protocol.

## 5. SDF-annotated run: what the annotation does and does not cover

From [`post-layout-sdf-regression 20261010-133000`](../../verification/records/post-layout-sdf-regression/records/20261010-133000-a0f91e3.md)
and the header of `flow/run-post-layout-sdf.sh`:

- **SRAM timing is omitted.** The macro runs as a zero-delay `FUNCTIONAL`
  model; the runner removes its SDF `CELL` block. Its read timing is
  LibreLane STA evidence only.
- **Timing checks are not applied.** Icarus does not apply SDF `TIMINGCHECK`
  entries (`partial: true`, 178 dropped per corner), so the cell models'
  `$setuphold` checks run against their 0 ns placeholders.
- **Only the core bench runs.** The firmware benches, boot programs and the
  constrained-random regression have no SDF run (#217 asks for the protocol
  waveforms on the routed corners).
- **C-flag semantics** have no post-layout evidence: the white-box test is
  skipped.
- **Stimulus alignment.** The bench is not run raw; it is re-timed to the SDC's
  period and its input/output delays (4 ns each of a 20 ns period), derived from
  the run's own SDC.
- **A tool workaround** (line-buffered simulator stdout, klayout-tools#2996) is
  disclosed in the record and changes nothing in the simulation.
- The grader still renders T1 item 7 unmet on a provenance-binding limit (see
  `manifests/README.md`), even though the regression passes.

## 6. Physical signoff and its limits

- The Tiny Tapeout `gds` workflow (LibreLane) is the flow of record for the
  submitted GDS (DR 0002). All four jobs (`gds`, `precheck`, `gl_test`,
  `viewer`) were green on run 38054423540 at `a0f91e3`, as cited by the
  records above. D1 in the tracker still says "not on the final top".
- The klt DRC is `clean` on that GDS; the klt-flow LVS check against the
  klt/Yosys reference is `unmet / check_errored` (klayout-tools#2941); the
  compare against the run's own post-route netlist is `match`
  ([librelane-gds-signoff-check 20261010-133100](../../verification/records/librelane-gds-signoff-check/records/20261010-133100-a0f91e3.md)).
- The T1 verdict of record is `tier: null`, **5 of 11 items met**
  ([signoff-baseline 20261010-133500](../../verification/records/signoff-baseline/records/20261010-133500-a0f91e3.md)).
  This document does not move that.
- The template's `gl_test` job checks results with `! grep failure results.xml`
  on the `ihp-cmos5l` branch, which would not match an `<error>` element; the
  repository-owned validation is tracked in #215 and #216 and is not yet in
  that job (tracker risk R2).

## What this does not show

- No measured silicon, no electrical pad characterization, no measured
  wall-clock baud. Cycle counts are exact; baud and frequency are arithmetic at
  a *nominal* 50 MHz that target-spec row 4 does not confirm.
- The constrained-random regression is RTL-only. Gate-level and SDF runs use
  the directed benches.
- Firmware benches have no SDF-annotated run, and the SRAM macro is simulated
  without its timing.
- The bounded versus unbounded split in section 4. Neither formal property
  covers a protocol.
- The UART load can be fooled by a one-bit count flip on a constructed image
  (F8, #211). The zero-filler recovery behaviour (F6) is an exact consequence
  of the CRC, documented in DR 0013.
- Row 14 is graded **unmet** in `spec/target-spec.md`; its dated notes pre-date
  the gate-level reset bench. The records show (a), (b) and the reselect cycle
  passing on the routed netlist, but this document does not upgrade the row.
- Standard-mode I2C runs at 435 cycles per clock (#125, open decision).
- No unplanned-protocol firmware exists yet (row 13 / D6, blocked on #135).
- No stretch protocol (low-speed USB, 10BASE-T) is designed or tested.
- The specification is Proposed (DR 0006). Two-key ratification never ran.
- The STA and die-area legs of the klt flow are blocked
  (klayout-tools#2635) and claim nothing.

## Spec grades are unchanged

This document cites evidence; it does not regrade. In particular
`spec/target-spec.md` rows 1, 3, 4, 8 and 14 are still worded **unmet** or
**partially realized** there, and some of that wording predates the records
(`testbenches.txt` notes the same for rows 3 and 14). Updating spec wording is a
spec change and goes through a decision record.

## Reproducing

```bash
./scripts/setup-env.sh                  # klt at the layout/toolchain.json pin, cocotb 2.1.0
scripts/run-rtl-benches.sh              # every PDK-free RTL bench
python3 verification/check_records.py   # append-only + hash-freshness lint of all records
npm run lint                            # the full set of record and inventory checks
scripts/signoff-report.sh --check-latest
```

PDK legs take `PDK_ROOT` at IHP-Open-PDK `2bbec755dc67`; the formal legs need
the OSS CAD Suite release pinned in `.github/workflows/ci.yml`. The SDF and
LibreLane legs start from a `gds` run's artifacts (`gh run download`). The
multi-corner and Monte Carlo SPICE grids that fleet hosts must not run locally
do not occur in this document's evidence: nothing here is a SPICE result.

## Outstanding work

- Freeze the submission ISA (#135, DR 0012/0013), then re-run and re-mint the
  affected records and re-link the final `gds` run (D1).
- Close or accept DR 0013 F8 (#211) and the `PM_CRC` readout (#167).
- SDF-annotated protocol waveforms on the routed corners (#217).
- Run the constrained-random regression at gate level.
- Decide the Standard-mode I2C allocation (#125).
- Row 13 unplanned-protocol firmware (#141) with its own independent model.
- Ratification (#44).
- `spec/verification-plan.md` still says "None of the artifacts described below
  exist yet"; its dated notes are the history, and this document is the
  current reading of them.
