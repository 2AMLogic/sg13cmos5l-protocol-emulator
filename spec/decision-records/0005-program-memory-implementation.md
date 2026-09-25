# 0005: Program-Memory Implementation vs. the Ratified Area Budget

Status: **Proposed 2026-09-25** — submitted for ratification through the
program's two-key (RATIFY-KEY) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"; precedent: DRs 0001–0004
via `0004-target-spec-ratification.md`). This record binds only when that
PR's history shows **two** `RATIFY-KEY` reviews — one EE key, one market
key, neither held by this record's author — and the merge commit is the
ratification act. Until then it is a proposal with measured evidence, not a
binding decision.
Date: 2026-09-25
Issue: #39

## Context

`spec/target-spec.md` row 7 binds an area target of **≤ 2×2 Tiny Tapeout
tiles**, against a competition maximum of 8×4. Row 6 binds a program store
of **256 × 16-bit words** with a serial load phase, and already names, as
that row's *stretch*, "program memory backed by a Tiny Tapeout SRAM macro
instead of flip-flops, **if area allows**." `0001-isa.md` sized the program
memory "without requiring a program-memory macro larger than what a ≤2×2-tile
area budget can plausibly hold (**exact bit-cell area is an open item**)."

Issue #19 implemented that memory the simplest way available — a flip-flop
array (`rtl/protocol_program_memory.v`) — and issue #21 measured it. The
open item closed badly:

- **klt/OpenROAD iteration flow** (record
  `verification/records/die-area-baseline/records/20260922-012402-420c370.md`):
  the memory **alone**, before the ISA core adds a cell, synthesizes to
  11,603 cells / **312,062.8896 µm²** of standard cells and floors at a
  **787,434 µm²** die at 40 % requested utilization, with no PDN, taps or
  fill.
- **LibreLane flow of record** (PR #38's `gds` run `35677496675`; PR-thread
  evidence, not a committed record in this repo): the full design at the
  declared `tiles: "1x1"` reports **378,066.857 µm²** of standard cells and
  OpenROAD global placement aborts with `GPL-0301: Utilization 1306.314 %`.

Issue #39 filed the consequence as a decision to be taken along one of three
axes — adopt an SRAM macro, revise the area budget, or shrink the program —
and stated the premise that the flip-flop memory "cannot fit **any** legal
Tiny Tapeout tile allocation," being 1.36× over even the 8×4 maximum.

Before choosing an axis, this record did the measurement the axes turn on
(`verification/records/program-memory-macro-feasibility/records/20260925-000359-63b10d7.md`).
It returned two results, and the second was not expected.

### Finding 1 — the macro exists, at exactly the ratified size

The IHP PDK this program targets ships a single-port SRAM macro whose
geometry is DR 0001's program memory, word for word:

| | |
|---|---|
| Macro | `RM_IHPSG13_1P_256x16_c2_bm_bist` |
| Organisation | 256 words × 16 bits, 1 port, column mux 2 |
| Footprint | 236.8 × 118.78 µm = **28,127.104 µm²** (LEF `SIZE`; liberty `area`) |
| Read | synchronous, **one-cycle data access**; `A_CLK → A_DOUT` **5.0 ns** worst case at `slow_1p08V_125C` |
| Top routing layer | **Metal4** — the CMOS5L stack's top routable metal and `tt-support-tools`' `project_top_metal_layer` for this PDK |
| Licence | Apache-2.0 (IHP PDK Authors) |
| Views shipped | `gds`, `lef`, `lib` (3 corners), `verilog`, `cdl`, datasheet |

It clears the competition's own gate mechanically: **all 27** layer/datatype
pairs in its GDS are on `tt-support-tools`' CMOS5L precheck allowlist
(`valid_layers_ihp_sg13cmos5l`), with **zero** excess. That allowlist
explicitly carries `SRAM.drawing` (25/0) and `DigiBnd.drawing` (16/0), both
of which this macro uses — the competition's precheck already anticipates an
SRAM bit-cell marker inside a CMOS5L user project. Cell names carry no `#`
or `/` (`cell_name_check`).

One caveat, recorded rather than smoothed over: in IHP-Open-PDK at the
revision the flow of record installs (`2bbec755dc67…`),
`ihp-sg13cmos5l/libs.ref/sg13cmos5l_sram` is a **symlink** to
`ihp-sg13g2/libs.ref/sg13g2_sram` (git tree mode `120000`). IHP ships **one**
SRAM macro set shared by both processes. It resolves in CI because
`tt-gds-action@ihp-cmos5l`'s `install_sg13cmos5l.sh` checks out the whole
IHP-Open-PDK tree. Whether the shuttle *admits* a user project containing
one is a question for the Tiny Tapeout / IHP organisers — see "Open items".

### Finding 2 — the tile-area constant this repo has been using is wrong

Every tile-budget comparison this repo has made used **1 tile ≈ 167 × 108 µm
= 18,036 µm²**, from the Tiny Tapeout template's own `info.yaml` comment.
Both that comment and record `20260922-012402-420c370` correctly labelled it
an order of magnitude with no inter-tile spacing or margin stated. **The flow
of record does not use it.** `tt-support-tools`'
`Project.create_user_config()` sets LibreLane's `DIE_AREA` directly from
`tech/ihp-sg13cmos5l/tile_sizes.yaml`:

| tiles | die (µm) | die area (µm²) | core area after TT margins (µm²) | vs. the 167×108 arithmetic |
|---|---|---|---|---|
| 1×1 | 202.08 × 154.98 | 31,318 | 28,941 | 1.74× |
| **2×2** (ratified) | 419.52 × 313.74 | **131,620** | **126,685** | 1.82× |
| **8×4** (competition max) | 1724.16 × 710.64 | **1,225,257** | **1,208,173** | 2.12× |

The core-area model above is not an approximation of LibreLane's — it *is*
LibreLane's: die from `tile_sizes.yaml`, inset by this repo's own
`src/config.json` margins (`LEFT/RIGHT_MARGIN_MULT = 6`,
`TOP/BOTTOM_MARGIN_MULT = 1`) times the `CoreSite` dimensions (0.48 × 3.78 µm,
read out of `sg13cmos5l_stdcell.lef`). Its validation is exact: at 1×1 it
implies a core density of **1306.3142 %** for LibreLane's reported cell area,
against the **1306.314 %** OpenROAD itself reported in `GPL-0301`.

Re-derived against the correct constants, with core density = cell area ÷
core area at this repo's own `PL_TARGET_DENSITY_PCT = 60`:

| tiles | SRAM macro (% of core) | FF memory, klt flow | FF memory, LibreLane flow |
|---|---|---|---|
| 1×1 | 97.2 % — **does not fit geometrically** | 1078.2 % | 1306.3 % |
| 2×1 / 1×2 | ~46 % | ~512–519 % | ~620–629 % |
| **2×2** (ratified) | **22.2 %** | 246.3 % | 298.4 % |
| 4×4 | 4.7 % | 52.3 % | 63.4 % |
| **8×4** (max) | **2.3 %** | **25.8 %** | **31.3 %** |

So, precisely:

- **The flip-flop memory's non-fit against the ratified ≤2×2 budget stands,
  and hardens.** It needs 2.46×–2.98× the *entire* 2×2 core area in cell area
  alone — no utilization setting, floorplan, or placement tuning rescues it.
- **Its claimed non-fit against the 8×4 competition maximum does not stand.**
  "1.36× over even the 8×4 maximum" is an artifact of the superseded
  constant. At the real die areas the flip-flop memory reaches 25.8 % / 31.3 %
  core density at 8×4 and would harden; ~5×4 is roughly its floor.

Per `CLAUDE.md`, record `20260922-012402-420c370` is **not edited** — its
measured die and cell areas stand unchanged and are reused above. The
superseding record is
`verification/records/program-memory-macro-feasibility/records/20260925-000359-63b10d7.md`,
and this decision record says why.

## Decision

**Adopt the SRAM macro. Do not revise the area budget. Do not shrink the
program.** Concretely:

1. **`rtl/protocol_program_memory.v`'s storage array is replaced by
   `RM_IHPSG13_1P_256x16_c2_bm_bist`.** DR 0001's ratified 256 × 16
   organisation, 8-bit PC, and serial load protocol are **unchanged** — this
   is an implementation decision about *what holds the bits*, not a spec
   change. Row 6's stretch item ("an SRAM macro instead of flip-flops, if
   area allows") is hereby taken: area allows, at 22.2 % of the ratified 2×2
   core.
2. **`spec/target-spec.md` row 7's ≤2×2 target is NOT revised.** The measured
   non-fit is met by changing the implementation, not the target. This is the
   outcome `CLAUDE.md`'s "agents do not relax the ratified spec to make a
   result pass" asks for, and the one both key skills' Step 5
   relax-after-measured-FAIL check exists to protect.
3. **DR 0001's program size is NOT reduced.** 256 × 16 is preserved exactly;
   no cycle-budget sketch is re-derived, because none is disturbed.
4. **DR 0001 is amended in exactly one place**, recorded in "Amendment to DR
   0001" below: the fetch stage becomes *fetch-ahead* to accommodate the
   macro's synchronous read. Every per-instruction latency in DR 0001's
   opcode table — including branch cost — is preserved, and the
   timing-determinism guarantee of row 3 is preserved **by construction**,
   not by argument.
5. **`info.yaml`'s `tiles` stays `"1x1"` in this record's PR.** The submitted
   top is still the harness-bootstrap stub. `tiles` moves when the
   implementation issue lands a real top and *measures* it — not on the
   strength of this record's arithmetic. Only that field's **comment** changes
   here, to stop restating the superseded tile constant.
6. **`spec/target-spec.md` is deliberately NOT edited.** No row's target,
   source, stretch entry, checking artifact or State changes: row 6 keeps its
   256×16 sizing and its SRAM-macro stretch (this record *takes* that stretch,
   it does not rewrite it), row 7 keeps ≤2×2 and stays "unmet; not carried as
   met", and row 3's guarantee is preserved by construction. A ratified table
   should not be touched by a decision that changes nothing in it — the
   ratification surface of this PR is DR 0005 itself.

### Why the macro, and not the other two axes

**Axis 2 — revise the area budget (up to 8×4).** Now *possible* (Finding 2
shows the flip-flop memory fits 8×4) and still **rejected**. Three reasons.
(a) It is unnecessary: the macro meets the ratified target, so revising it
would be relaxing a spec row that the design can actually hit — the precise
move the two-key review escalates. (b) `manifests/design-evidence-tiers.md`'s
AREA-EFF convention requires a *passing* efficiency read at the proposed size
before ratification; a 2×2 design whose memory occupies 22.2 % of core will
read far better than an 8×4 design that is 69–74 % empty by construction.
(c) Competition positioning: row 7's own source note says the 2×2 target was
chosen "because judging rewards verification novelty, not size." Spending the
entire allocation on flip-flops buys nothing judged.

**Axis 3 — reduce the program size.** Rejected, and it would not have
worked anyway. Reaching a 2×2 core with flip-flops requires a ≈2.98×
reduction on the flow-of-record's own number — 256 words to **≈ 86**, and
that is for the memory occupying the *whole* core with nothing left for the
ISA core datapath. DR 0001 sized 256 words so all three ratified protocols
plus a dispatch table coexist; 86 words does not survive that, so this axis
trades a ratified capability (row 1: three protocols in one loaded image) for
an area outcome the macro achieves at no capability cost. It is also the only
axis that would require superseding a ratified DR's substance rather than its
implementation.

**Axis 1 — the SRAM macro.** Taken. It is the only axis that meets the
ratified target rather than negotiating with it; it is already the ratified
row-6 stretch; it costs **28,127 µm² instead of 312,063–378,067 µm²** — an
**11.1×–13.4× reduction in the memory's area** — and it frees ~98,558 µm² of
2×2 core for the ISA core datapath, routing, PDN and fill. Its cost is
integration risk, enumerated and assigned below rather than waved at.

### Amendment to DR 0001 — fetch-ahead (the one substantive change)

`0001-isa.md`'s timing model states: *"This is a single-cycle, non-pipelined
datapath: fetch and execute happen in the same cycle for every instruction."*
That sentence assumes an asynchronous-read memory. The macro's read is
synchronous with **one-cycle data access**, so it is amended to:

> The datapath is single-cycle and non-pipelined in its *execute* stage;
> instruction fetch is one cycle ahead of execute. The address presented to
> program memory at the clock edge ending cycle *N* is the address of the
> instruction that **executes** in cycle *N+1*, and is computed
> combinationally within cycle *N* from the instruction executing in cycle
> *N* and the current flags — i.e. it is exactly DR 0001's existing next-PC
> mux, moved to the memory's address port instead of its output.

**This costs zero cycles, for every instruction in the ratified opcode
table**, and that is a property of the ISA, not luck: every control-transfer
instruction DR 0001 defines — `JMP imm8`, `BZ imm8`, `BNZ imm8` — takes its
target from an **immediate in the instruction word**, and `Z` is written by
the *previous* instruction. There is no register-indirect or computed branch,
so the next address is always combinationally available in the same cycle the
branch executes. No branch bubble exists to be taken or not taken, so branch
*cost* remains independent of data and row 3's guarantee holds by
construction. `WAIT imm8` holds the address and the fetched instruction
register for the stall; `HALT` holds both indefinitely.

Two consequences are spec-visible and are stated so they are checked, not
discovered:

- **Run-phase entry costs one additional cycle.** DR 0001 says run phase
  "begins at the next cycle" after `MODE` drops. With fetch-ahead, address 0
  is presented on that cycle and instruction 0 executes on the one after. A
  **fixed +1 cycle**, data-independent, at a single point per reset — it does
  not perturb any cycle-budget sketch, all of which count from the first
  executed instruction.
- **Load phase and run phase remain mutually exclusive**, which is why a
  **single-port** macro suffices. DR 0001 already latches `MODE` only at reset
  release and forbids mid-run re-entry, so the memory is never read and
  written in the same cycle. No dual-port macro, and no arbitration, is
  needed.

The load protocol itself is unchanged and maps onto the macro directly: the
16-bit shift register drives `A_DIN[15:0]`, the auto-incrementing write
address drives `A_ADDR[7:0]`, `A_WEN`/`A_MEN` assert on the 16th bit's own
edge, `A_BM` is all-ones (no partial writes). `A_DLY` is tied to `1` (the
datasheet's mandatory setting); the BIST port (`A_BIST_*`) is tied off with
`A_BIST_EN = 0`.

**Timing budget at the ratified 50 MHz (20 ns), stated as arithmetic to be
confirmed by STA, not as a result:** 5.0 ns `A_CLK → A_DOUT` at
`slow_1p08V_125C` plus ≈0.9 ns `A_ADDR` setup leaves ≈14 ns for decode, ALU,
flag update and next-PC selection. Row 4 remains unmet on both flows until an
STA run over the real core says otherwise.

## Consequences

- **Row 7 (≤2×2) becomes reachable rather than falsified**, and remains
  unmet-but-bound until a real top is measured. Row 6's stretch item is
  taken. Row 3's guarantee is preserved by construction under fetch-ahead.
- **Issue #18 / PR #38's blocker is resolved in principle**: the reason its
  acceptance criterion 4 ("the `gds` workflow still passes end to end") was
  unreachable was a memory that could not be placed at any legal `tiles`
  value. With the macro, `tiles: "2x2"` has 77.8 % of its core free after the
  memory. Whether that criterion actually goes green is the implementation
  issue's result to report, not this record's to assert.
- **`verification/test_program_memory.py` must be re-verified against the
  macro-backed module, not assumed to carry over.** Its readback assertions
  are written against an asynchronous fetch port; under fetch-ahead the
  fetched word arrives one cycle later. The bench's *contracts* (MSB-first
  shift, commit on the 16th bit's own edge, mid-word discard, 256-word
  saturation, no mid-run re-entry) are unchanged — only the sampling cycle
  moves. This is named explicitly because silently assuming the existing
  bench still applies is the likeliest way to ship an unverified change.
- **Gate-level and post-layout legs gain a black box.** The macro has no
  synthesizable RTL — simulation uses the PDK's behavioural model
  (`RM_IHPSG13_1P_256x16_c2_bm_bist.v`), synthesis blackboxes it against the
  LEF/liberty, and the post-route SDF regression must annotate the macro's
  own SDF or state that it does not.
- **The LibreLane flow needs macro configuration**, which Tiny Tapeout does
  permit: `tt-support-tools`' `Project.create_merged_config()` reads this
  repo's `src/config.json` **first** and overlays only the keys TT generates
  (`DESIGN_NAME`, `VERILOG_FILES`, `DIE_AREA`, `FP_DEF_TEMPLATE`, `VDD_PIN`,
  `GND_PIN`, `RT_MAX_LAYER`), so `MACROS` / `EXTRA_LEFS` / `EXTRA_LIBS` /
  `EXTRA_GDS_FILES` / `PDN_MACRO_CONNECTIONS` survive the merge. That file
  carries a "do not edit unless you know what you are doing" banner: the
  implementation PR must say what it changed and why, in the file.
- **The macro has a third supply pin.** `VDDARRAY!` (array supply) alongside
  `VDD!`/`VSS!`, against a TT project that is given `VPWR`/`VGND` with
  `FP_PDN_MULTILAYER = 0`. Connecting it is an explicit implementation step,
  not a default.
- **Two flows, one record of truth.** Every number in this record names its
  flow. The klt flow has never run place-and-route with a hard macro against
  this PDK, and klt's per-library tables still have no `sg13cmos5l_stdcell`
  entry for CTS/routing/antenna cells (record `20260922-012402-420c370`);
  a klt-side macro flow may surface a fresh tool gap, which is a
  klayout-tools issue to file under `CLAUDE.md`'s friction protocol, not a
  reason to prefer one flow's number.

## Open items (assigned, not left hanging)

1. **Shuttle admission of an SRAM macro.** Availability, layer-allowlist
   compatibility and Metal4 containment are *measured* here; whether the
   CMOS5L shuttle accepts a user project containing `sg13g2_sram`-derived
   macros is a question only the Tiny Tapeout / IHP organisers can answer.
   The implementation issue must get that answer **before** the RTL swap is
   treated as the submission path, and record it. If the answer is no, this
   record is superseded and axis 2 becomes the live option — with Finding 2
   in hand, an 8×4 flip-flop design is a real fallback rather than the
   dead end issue #39 believed it to be.
2. **A measured die area for the macro-backed design**, on both flows, to
   replace this record's arithmetic — the implementation issue's own
   `verification/records/` entry.
3. **An AREA-EFF read at 2×2** per `manifests/design-evidence-tiers.md`, once
   a macro-backed layout exists.
4. **A klt-side place-and-route flow that handles a hard macro against this
   PDK.** This repo's iteration flow has never run one, and klt's per-library
   tables still carry no `sg13cmos5l_stdcell` CTS/routing/antenna entry at the
   pinned build. If that surfaces a tool gap, it is a `2AMLogic/klayout-tools`
   issue under `CLAUDE.md`'s friction protocol — described as a tool gap, with
   this design's specifics left out.
5. **`layout/toolchain.json`'s `klt_required_commands` should grow to include
   `pdk`, `stats` and `layers`** (the feasibility runner's verbs, all verified
   live at the existing pin — see the record's "klt provenance"). It is
   *deliberately not grown here*, and the reason is a real coupling worth
   naming: that file is a provenance input of two committed records
   (`die-area-baseline/20260922-012402-420c370` and
   `sta-corner-sweep/20260922-012909-420c370`), so **any** edit to it
   invalidates their content hashes and `verification/check_records.py`
   correctly demands they be re-minted — a fresh six-corner `klt sta` sweep
   plus two `klt place-and-route` runs. The right time to pay that is the next
   run that re-mints those records anyway (the implementation issue's measured
   die area is the obvious candidate), not a decision-record PR. The runner
   enforces the contract itself in the meantime. The same coupling already
   leaves `functional-verification` off that list, so this is a standing
   property of the convention rather than a new debt.

## Alternatives considered

**Keep flip-flops and revise `tiles` to 8×4.** Rejected — see "Why the macro"
above. Recorded as the **fallback** if open item 1 returns "no macros."

**Keep flip-flops and shrink the program to ≈86 words.** Rejected: it
sacrifices a ratified capability (row 1) for an area outcome the macro
achieves at none, and it is the only axis requiring a ratified DR's substance
to be superseded.

**A dual-port macro (`RM_IHPSG13_2P_256x16_c2_bm_bist`).** Rejected as
unnecessary: DR 0001 already makes load and run phases mutually exclusive, so
the second port would buy nothing and cost area. Reconsider only if a future
ISA revision admits mid-run reprogramming.

**A smaller/larger macro from the same family** (e.g. `512x16` for headroom,
`256x8` twice). Rejected: `256x16` matches the ratified organisation exactly;
anything else either changes DR 0001's sizing or adds glue for no benefit.
The full shipped family's footprints are in the feasibility record's
artifacts, so a future revision does not need to re-derive them.

**Inferring an SRAM from RTL and letting the synthesizer map it.** Not
available: Yosys/LibreLane have no memory-macro mapping path for this PDK,
and an inferred array is exactly the flip-flop implementation already
measured.
