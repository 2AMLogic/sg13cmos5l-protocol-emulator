# Statistical claims — not applicable (T1 item 6)

Status: **recorded 2026-11-19** (issue #348). This is the recorded **"not
applicable"** for `klt signoff`'s T1 item 6 (statistical claims / Monte
Carlo): this block is a digital partition (block manifest
`kind: "digital"`, no analog half), its ratified target spec has **no
statistical row**, and the checklist's own text says such a block "must say
so explicitly rather than omitting the item". Since klayout-tools #2865
(in the pinned `klayout-tools==0.8.0`) the honest form is exactly this
statement plus the manifest citation that binds it — `klt signoff` renders
the item `not_applicable`, never `met`, and counts it toward T1 separately
(`t1_not_applicable_count`, never folded into `t1_met_count`).

## What is bound, and by what

- The **machine-bound pair** is two JSON documents cited by the block
  manifest's item 6 in the `not_applicable` form, each pinned by content
  hash:
  - [`target-spec-ratified.json`](target-spec-ratified.json) — the spec
    companion: `status: "ratified"` and one row per **ratified** spec row.
    It carries **ids only** (`"1"` … `"12"`), never row titles: the
    grader's conservative statistical scan refuses a spec row that so much
    as *mentions* accuracy, matching, offset, yield, sigma or Monte Carlo,
    and row 10 is titled "UART bit-timing accuracy".
  - [`statistical-claims-na.json`](statistical-claims-na.json) — the
    statement: one `id` / `class` / `reason` entry per ratified row.
  - This markdown is the **human-readable half**. The statement JSON embeds
    its sha256 (`statement_content_hash`) and the spec markdown's sha256
    (`spec_markdown_content_hash` — the same value
    `target-spec-ratified.json` carries as `source_content_hash`), and
    [`scripts/check_statistical_claims_na.py`](../scripts/check_statistical_claims_na.py)
    (`npm run lint`, CI's records job) fails if either embed drifts.
- **Coverage is the ratified rows 1–12**, exactly as
  [`decision-records/0004`](decision-records/0004-target-spec-ratification.md)
  registers them and
  [`decision-records/0009`](decision-records/0009-two-key-ratification-act.md)
  binds them (the two `RATIFY-KEY` reviews on PR #242). **Rows 13 and 14
  are not covered by the hash-bound claim**: they were added 2026-10-09,
  are not in DR 0004's register, and stay `Proposed` until an act of their
  own binds them. When one ratifies, extend both JSON companions — the
  grader requires the statement to account for *exactly* the spec
  companion's rows — and re-mint the signoff baseline; the row-class walk
  below already includes them, so the next mint has a text to start from.
- **The claim freezes [`target-spec.md`](target-spec.md).** Any edit to it —
  including a dated note that changes no Target — invalidates this claim:
  the embedded hashes go stale (lint fails), updating the companions moves
  both content hashes the manifest pins (`klt signoff --check` drift,
  re-mint), and the live `signoff-baseline` records pin the markdown
  directly. That is deliberate: "editing either invalidates the claim" is
  the form's own contract.

## The walk — every row, and why its class is not statistical

Verified against `spec/target-spec.md` as of this filing (14 table rows;
the ratification binds 1–12). Every row is a deterministic functional,
timing, budget, coverage or process requirement; none claims a
distribution, a spread, or a per-part sample.

| Row | Class | Why its row class is not statistical |
|---|---|---|
| 1 — Protocols emulated in firmware | functional | UART, SPI and I2C run as firmware on the ISA core and are graded by deterministic benches — directed, constrained-random (seeded) and gate-level cocotb runs against independent reference models. Every rate is a core-cycle count at row 4's clock target; pass/fail verdicts, no sampled quantity. |
| 2 — Stretch protocols | functional (aim) | Binds no number at all: the row's own entry condition is a deterministic instruction-cycle budget sketch (DR 0011 / DR 0015 hand counts, stated as such). Nothing distributional is claimed or budgeted. |
| 3 — Timing determinism | deterministic latency | No instruction's cycle latency depends on its data; checked by formal properties (`no_data_dependent_latency`, `pin_write_latency`). Latency is fixed by the instruction word — the opposite of a sampled timing figure. |
| 4 — Core clock | corner-bounded timing | Timing closure is STA at the PDK's characterised corners (DR 0007's proposed corner set): a per-corner worst setup/hold slack with a pass/fail reading, on each flow of record (klt flow: netlist-estimate stage; LibreLane flow: post-route). The two flows' figures are recorded side by side and their disagreement is a finding, not merged. No distribution, spread or margin-statistics term appears in the row. |
| 5 — I/O pin budget | pin budget | A fixed wiring fact of the Tiny Tapeout template (8 in, 8 out, 8 bidirectional plus clk/rst_n/ena), checked by the functional suite instantiating the wrapper as the template defines it. Not a measured quantity. |
| 6 — Program storage | functional | 256 × 16-bit words on the SRAM macro, serial load and boot-ROM paths checked by the deterministic load-phase and boot-ROM cocotb benches (fixed edge counts, CRC gate). Sizes are word counts. |
| 7 — Area | area budget | An upper bound in Tiny Tapeout tiles. Evidence is flow-attributed die-area figures and cell counts from synthesis / place-and-route — deterministic per-run outputs of a fixed netlist, not per-die samples; no yield or density-per-part term is claimed. |
| 8 — Verification | verification suite | Requirements on benches, cover bins, negative controls, formal properties and independent reference models — all deterministic pass/fail checks. |
| 9 — Submission | process | Licence (Apache-2.0), the CMOS5L template, and the 2027-01-18 deadline. No measurement of the design at all. |
| 10 — UART bit-timing accuracy | deterministic cycle-count bound | The bound is cumulative per-frame drift of at most 2 % of the nominal bit period, and it is a **whole-cycle count**: transmitter edges land on whole multiples of the bit period in core cycles, measured from the cocotb waveform by the reference model. Receiver tolerance is exercised at a fixed ±2 % per-bit rate error — a chosen stimulus, not a claimed distribution. No clock spread, jitter, ppm ageing or per-lot term is claimed or budgeted; the 2 % figure is a deterministic design margin placed inside a published link budget (Maxim tutorial 2141). The word "accuracy" in the row's title denotes this deterministic bound; the row's class is not statistical. |
| 11 — SPI clock ceiling and modes | deterministic cycle ratio | The ceiling is a fixed instruction-cost ratio (f_clk/4 for transfers that take the sample without keeping it, f_clk/10 for keeping transfers on DR 0010's pin plan), plus four fixed polarity/phase configurations, decoded byte-exact by the reference model. |
| 12 — I2C timing | deterministic phase minimums | t_LOW / t_HIGH / t_HD;STA / t_SU;STA / t_SU;STO met as core-cycle counts against UM10204 Table 11's minimums, with a bounded SCL period per grade; pacing is fixed by the committed firmware images and graded cycle by cycle. |
| 13 — Reprogrammability beyond the designed set | **not covered — unratified** | Added 2026-10-09, `Proposed`, not in DR 0004's register. Its evidence bar (firmware only, independent reference model, timing checked) is functional-class like row 1, but the row is outside this hash-bound claim until an act binds it; re-mint then. |
| 14 — Reset, power-up and reselect behaviour | **not covered — unratified** | Added 2026-10-09, `Proposed`, not in DR 0004's register. Its checks (gate-level random-initial-state and X-propagation regression, reset-coverage listing, STA recovery/removal at fixed corners) are deterministic functional/corner checks, but the row is outside this hash-bound claim until an act binds it; re-mint then. |

**Stop condition, checked**: no row of the ratified table is statistical.
Had any row been one — an accuracy, offset, matching or yield figure, or a
sigma / Cpk / 3σ bound — this statement would not have been filed; the item
would need `klt yield` evidence for that row instead (issue #348's stop
condition, which parks the issue rather than relaxing the row).
