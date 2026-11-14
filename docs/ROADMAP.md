# Roadmap

A tiny protocol-emulation CPU on IHP SG13CMOS5L whose UART, SPI and I2C are
firmware, built for the Protocol Emulator ASIC Competition (submission due
2027-01-18).

Status as of 2026-11-13, `main` @ `3619c879`.

## Where it stands

**Design.** The ISA core, the SRAM-macro-backed 256×16 program memory, DR 0012's
control space and DR 0013's boot ROM are in `rtl/` and wired to the Tiny Tapeout
top. The LibreLane flow of record routes it in a 2×2 die with `gds`, `precheck`,
`gl_test` and `viewer` passing (`verification/records/librelane-pdn-bridge/`).
Firmware for UART, SPI modes 0–3, I2C Standard/Fast, WS2812 and a PS/2 device is
committed with benches against independent reference models.

**Spec.** Rows 1–12 of `spec/target-spec.md` and DRs 0001–0004 are ratified
(PR #242, DR 0009). Rows 13 and 14 and DRs 0005, 0007, 0008, 0010–0018 and
0020–0023 are `Proposed`; the next act is prepared in
[`spec/ratification-batch-2.md`](../spec/ratification-batch-2.md).

**Spec rows** (digest in [`spec/gap-to-submission.md`](../spec/gap-to-submission.md),
which wins over this file on any disagreement): rows 5 and 9 are `met`;
rows 2, 13 and 14 `proposed`; the other nine `unmet`. Most of those reasons are
limits no simulation closes (no silicon clock, no pad characterization). Work
can move row 4 (50 MHz closes on 3 of 6 corners on LibreLane; the klt netlist
estimate closes setup but fails hold), row 12 (stale gate-level and SDF records
for the Fast-mode I2C images) and row 7 (klt place-and-route not run).

**T1 checklist** (`klt signoff`, record
`verification/records/signoff-baseline/records/20261108-120008-79d0aef.md`,
klt 0.8.0): **4 of 11 met**.

| Item | Verdict | What moves it |
|---|---|---|
| 1 Design sources, 2 Layout, 9 Testbenches, 10 Hygiene | met | — |
| 3 DRC clean | unmet, `check_failed` (4,484 findings, all inside the foundry SRAM macro) | #365, after #371 |
| 4 LVS clean | unmet, `check_failed` | #329: evidence contract not yet written |
| 5 Full corner verification | unmet, `no_evidence` | no open issue; see Later |
| 6 Monte Carlo | unmet, `no_evidence` | #348 (record "not applicable") |
| 7 Post-layout verification | unmet, `unverifiable_provenance` | re-grade after #371 |
| 8 Characterization report | unmet, `check_failed` | follows the unmet spec rows |
| 11 Power delivery | unmet, `no_evidence` | #350; LVS half waits on #329 |

The body of #351 predates the klt 0.8.0 deck: it ticks item 3 and points items
5, 7 and 8 at issues since closed (#20, #330, #349). Read the table above.

## Now

- **Move off the per-repo klayout-tools pin (#371, in progress).** Done when
  `npm run lint` and `scripts/signoff-report.sh --check-latest` pass on the
  merged change. Most of Next waits on this.
- **Draft the item 4 evidence contract (#329; no drafting issue yet).** The
  ruling on #329 authorizes preparing a decision record naming the post-route
  reference for physical connectivity and the independent RTL-to-reference
  evidence required beside it. Done when a `Proposed` DR is in
  `spec/decision-records/` and listed in `spec/ratification-batch-2.md`, with
  item 4 still `unmet`. Needs no tool run.
- **Reconcile digest rows 7 and 11 (no issue yet).** Row 11 still says
  multi-byte bursts under one CS are untested, though #286 landed that bench;
  row 7 still names klayout-tools#2635, closed upstream on 2026-10-27. Done
  when both rows carry a dated note, `scripts/check_gap_digest.py` passes and
  the characterization report and signoff baseline are re-minted (as in #386).
- **Correct the "klt STA is blocked and claims nothing" statements (no issue
  yet).** `README.md`, `docs/submission/verification.md` and
  `docs/submission/ai-use.md` say so, but a macro-backed `klt sta` record
  exists (`sta-corner-sweep/records/20261101-032923-c606644.md`, PR #370). Done
  when each states that record's result and
  `python3 verification/check_docs_records.py` passes.

## Next

Unblocked once #371 lands:

- **Item 3 (#365).** Cite the foundry-cell DRC exception for the SRAM macro.
  A branch already grades it `met` at klt 0.9.0 and stopped because the pin
  change staled nine records. Done when a signoff baseline reads item 3 `met`
  with the exception listed. The same branch note reports item 7 `met` at
  0.9.0, not investigated: the baseline must say why it changed.
- **Item 6 (#348).** Commit the hash-bound "not applicable" statement for the
  ratified rows 1–12. Done when a baseline reads item 6 `not_applicable`.
- **klt STA re-run (#394).** Done when a new `sta-corner-sweep` record names
  the exact PDK commit and quotes the live LibreLane hold figure.
- **klt place-and-route, signoff-check and ERC re-mints (#389).** Done when
  `die-area-baseline`, `librelane-gds-signoff-check` and `librelane-erc` each
  have a record at the new version.
- **Item 11 (#350).** ERC supply report landed (PR #354); the PDN half follows
  #389 and the LVS half #329.

Unblocked once the netlist evidence refresh (#265) lands and PR #263 merges:

- #262 and #275: one firmware gate-level and SDF run on the 70/55 Fast-mode
  I2C images; then #272 / PR #274 can merge and row 12's stale clause goes.
- #304: pull-up rise time in the I2C pad model (`verification/uio_pads.py` is a
  hashed input of the gate-level and SDF records, so it rides the same run).
- #278 / #290: re-run the klt-flow evidence on IHP-Open-PDK `f7bca326`; #324
  deletes `verification/_dut.py` at the same re-mint.

## Later

- **Item 5, full corner verification.** Which corner set binds row 4: the six
  declared, or DR 0007's three macro-characterized corners (`Proposed`)? Does a
  post-route klt run close the hold the netlist estimate fails?
- **Final submission run (D1).** Which commit is the final top? No `gds` run is
  linked from the README as the run of record; it should follow PR #263.
- **Stretch protocols (row 2).** Is DR 0015 ratified in time for low-speed USB
  transmit to reach the submitted design?

## Blocked and waiting

- **Attended evidence refresh (#265, PR #263).** The A_DOUT buffer change
  (#261) needs every netlist-dependent record re-run; three agent attempts died
  on the long tool runs and the 2026-10-15 ruling reserves it for an attended
  session. It heads the chain #265 → PR #263 → #262 / #275 → #272 → #304, #290.
- **Tile size (#273).** Whether `info.yaml` must declare 6×4 or may stay 2×2 is
  a question for the organizers; no agent can send it. Gates row 7, DR 0014.
- **Item 4 acceptance (#329)** waits on review of the contract and evidence.
- **Second ratification act.** Rows 13 and 14 and the `Proposed` DRs wait for
  two `RATIFY-KEY` reviews on `spec/ratification-batch-2.md`.

Dispatchable today: the three unissued Now items. Every other open issue is in
progress (#371), waits on #371, or sits behind the attended refresh.

## Not planned

Fixed-function UART, SPI or I2C peripherals in RTL (CLAUDE.md); 10BASE-T
transmit and all stretch-protocol receive (deferred by DR 0015); a die larger
than 2×2 unless #273's answer forces it (DR 0014); a two-flop input
synchronizer (deferred in DR 0021); silicon measurements before a chip exists.
