# 0014: What Area Beyond 2x2 Buys — Candidate Uses and a Tile Recommendation

Status: **Proposed 2026-10-09.** It goes to ratification through the
two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`). That mechanism has never run here (DR 0006, issue #44),
so this is a proposal like DRs 0001–0005, 0007, 0008, 0010, 0012 and 0013. It
relaxes no ratified row and makes no target-spec row met. DR 0011 (PR #128,
since merged) holds its number; 0009 was never used; this record is 0014.
Date: 2026-10-09
Issues: #129 (this decision); #130 (protocol-neutral ISA assists); #134
(submission, the 6-hour Actions limit). Revisits target-spec row 7 and DR
[`0005`](0005-program-memory-implementation.md) "Axis 2".

## Context

Row 7 says "≤ 2×2 tiles", `info.yaml` says `tiles: "2x2"`, and DR 0005 Axis 2
rejected growing toward 8×4 because a larger flip-flop design would be "69–74 %
empty by construction" and because the row's source note said judging
"rewards verification novelty, not size". That argument was against growing
*only the memory*. It never weighed what the extra area could buy against the
criteria the organizers have since spelled out in their 2026-10-09 entrant
update (quoted verbatim in issue #129):

- "Design to 6x4 until the 8x4 template is out." 8×4 is "expected around
  mid-October" and is "an upgrade".
- "Flexibility is the main thing: can the chip be reprogrammed to support
  protocols it wasn't designed for?"
- "Running protocols concurrently, or supporting both controller and target
  roles, is a plus but not required."
- Several SRAM macros are allowed if they fit and pass precheck.
- "A design with fewer protocols but a strong architecture and verification
  approach can definitely be competitive."
- GitHub Actions have a 6 hour limit, "and a design that's close to full can
  hit it" (issue #134).

So the row-7 rationale "not size" is stale in wording, but its conclusion may
still hold. This record tests that, with numbers.

## Measured inputs (and which flow produced them)

Every figure below is quoted, not new. No synthesis, place-and-route or
simulation was run for this record.

| Input | Value | Source | Flow |
|---|---|---|---|
| Standard cells, whole top | 10,323.2556 µm² (567 cells) | `info.yaml` `tiles` note (b) | **klt/Yosys** cell area, not placed die area |
| 256×16 SRAM macro | 28,127.104 µm² (236.8 × 118.78) | DR 0005 Finding 1 | macro LEF/liberty |
| Cells + macro | 38,450.4 µm² (30.4 % of 2×2 core) | `info.yaml` `tiles` note (b) | klt/Yosys cells + LEF macro |
| Core area after TT margins | 2×2: 126,685; 3×2: 193,261; 3×4: 443,784; 4×4: 596,662; 6×4: 902,417; 8×4: 1,208,173 µm² | DR 0005 Finding 2 table; per-size figures from `verification/records/program-memory-macro-feasibility/artifacts/20261001-091536-8639b95/sram-macro-feasibility-results.json` (`tile_budget.per_tiles`), from `tile_sizes.yaml` as retrieved 2026-09-24 | **LibreLane die/margin model**, validated at 1×1 against OpenROAD `GPL-0301` |
| Larger single-port macros | 512×16: 45,309 µm²; 1024×16: 79,674 µm²; 256×32: 49,488 µm² | same artifact, `macro_family_1p` | macro LEF |

The `tile_sizes.yaml` behind the 6×4 and 8×4 core areas is the one retrieved on
2026-09-24 from `tt-support-tools` ref `ihp-sg13cmos5l`. The organizers say an
8×4 template is not out yet; those figures are for the *planned* maximum and
must be re-pulled (see Decision 3).

Current design against each size, as a share of core (cells + macro, 38,450 µm²,
mixed klt cells and macro LEF, so a floor for a placed design, not a placed
number): 2×2 **30.4 %**; 3×2 19.9 %; 6×4 **4.3 %**; 8×4 3.2 %. The
percentages are arithmetic on the table above. The repo's own
`PL_TARGET_DENSITY_PCT` is 60.

## Candidate uses of area

Costs are rough and say what they are built from. "Estimate" means no tool
produced it; it is a bound or a sum of measured parts.

**A. Second engine with its own program memory (concurrency).** Serves the
organizers' "running protocols concurrently" plus, indirectly, flexibility
(two roles at once). A second copy of the ISA core and a second 256×16 macro
costs at most 10,323 + 28,127 = **38,450 µm² (estimate: upper bound, assuming
the whole klt cell total were duplicated; a duplicate would share the load
logic, so the real number is lower)**. Two engines is then ≤ 76,901 µm² =
**60.7 % of the 2×2 core** — at, not under, the 60 % density target — and 39.8 %
of a 3×2 core. Open costs this record does not price: pin arbitration (the
pin budget is fixed at 8+8+8 by row 5, template-fixed), a way to say which
engine owns which pin, and the formal property `no_data_dependent_latency`
needing re-proof per engine and for the interaction. Honest caveat: with a
single 8-bit input port, two engines running two protocols *at once* on 24
pins is a pin-assignment problem before it is an area problem.

**B. More SRAM (more or longer programs).** Serves "controller and target
roles coexist" (more firmware images resident) and DR 0013's boot-ROM images.
A 512×16 macro is +17,182 µm² over today's macro (45,309 − 28,127); 1024×16 is
+51,547 µm². Using more words needs a PC wider than the DR 0001 8-bit PC, which
is an ISA change, not an area change. Also there is no evidence today that 256
words is the binding constraint: the committed UART, SPI and I2C images and the
DR 0013 boot images have not been shown not to fit. Without such a measurement
this candidate does not earn its area. The cheaper route to "both roles" is two
images selected by DR 0013's boot path, in the existing 256 words.

**C. Protocol-neutral ISA assists (#130: CRC/LFSR, NRZI and bit-stuffing,
Manchester, clock recovery).** Serves the organizers' statement that for USB
and Ethernet "the more of the protocol work (line coding, CRC, clock recovery)
your chip does itself, the better" — a stretch-protocol credit, and flexibility
because the assists are protocol-neutral. Cost: **not measured.** These are
small combinational/sequential blocks next to a core whose entire standard-cell
total is 10,323 µm² (klt), so the expectation (estimate) is a modest fraction of
that figure, not a tile. They fit in 2×2 and are paid for in ISA and
verification effort, not in area. This record takes no position on which
assists to build; that is #130. The one rule that is already law: no
fixed-function protocol peripheral (CLAUDE.md) — an assist is an ISA primitive
the firmware composes, never a UART/SPI/I2C/USB/Ethernet block.

**D. Controller + target coexistence.** Serves "both controller and target
roles". Mostly *firmware* (and DR 0012's runtime pin direction): no area is
needed beyond existing program memory unless B above is shown to bind. It is
listed because it is the cheapest of the organizers' "plus" items.

**E. More area only to spread the existing design.** Rejected, as in DR 0005
Axis 2: at 6×4 the current design is 4.3 % of core, nothing judged.

## Decision (proposed)

1. **Keep `tiles: "2x2"` as the submission target for now.** On the numbers
   above, B and D earn no area, C earns none in tile terms, and only A (two
   engines) comes near the 2×2 limit — and A is gated by pins and verification
   effort rather than silicon. Nothing in the current candidate list *earns*
   tiles beyond 2×2. This is not "area is irrelevant": it is that today
   area is not the binding resource. Row 7's "not size" wording is stale, but its
   ≤ 2×2 number stands.
2. **If a multi-engine decision record is later admitted, the next step is
   3×2, not 6×4 or 8×4.** 3×2 (core 193,261 µm²) holds A at 39.8 % with margin
   and the extra tile area is what DR 0005's "AREA-EFF" convention could defend.
   Anything larger needs a record that names the feature that needs it. A
   record admitting a multi-engine design must also state the pin-arbitration
   scheme and re-state the formal properties per engine.
3. **Do not commit `tiles` past 6x4 before the 8x4 template lands.** The
   organizers' own guidance is to design to 6×4 and treat 8×4 as an upgrade.
   When the 8×4 CMOS5L template is out (expected mid-October 2026): re-pull
   `tech/ihp-sg13cmos5l/tile_sizes.yaml` from `tt-support-tools`, refresh the
   `per_tiles` figures above, and re-confirm whether the LibreLane `DIE_AREA`
   path (DR 0005 Finding 2) is unchanged. That follow-up is a new issue; nothing
   is committed to `info.yaml` here.
4. **Row 7 and DR 0005 Axis 2 are annotated, not rewritten.** Target-spec row 7
   gets a dated pointer to this record (its Target column unchanged); DR 0005
   Axis 2 gets an appended pointer. The Status stays Proposed because the spec
   is unratified (DR 0006).

## The 6-hour Actions runtime risk (#134)

The organizers say a design "close to full" can hit the 6-hour GitHub Actions
limit and that the fallback is the same Tiny Tapeout flow run locally (their
local-hardening guide). Consequences for this record:

- The LibreLane `gds` run for the current 2×2 design is not timed in this
  record, and no figure is invented for it. The CI wall-clock of the existing
  runs (for example run 36837745318) is the baseline to read before any growth.
- Placement and routing time grows with cell count and with density, and each
  additional macro adds macro-halo and routing constraints. A two-engine design
  at 60.7 % of a 2×2 core (candidate A) is exactly the "close to full" case; at
  3×2 it is 39.8 %. That is a reason to take Decision 2's 3×2, not 2×2, if A
  is ever built.
- Mitigation is process, not area: record the `gds` wall-clock in the evidence
  record of any run, and rehearse the local-hardening path before the
  2027-01-18 deadline if a design is above roughly half of core. Tracked with
  #134.

## Consequences

- No RTL, `info.yaml`, flow or testbench change. Docs only.
- The "draft 2×2 is a verification-novelty choice" rationale is superseded in
  wording by the organizers' judging description; the budget is unchanged.
- Candidate C remains #130's decision; candidate A would need its own record,
  and per CLAUDE.md "ISA is the product" it stays an engine-count question
  (more cores), never a hardware protocol block.
- Any area number later added to the record must name its flow (klt/Yosys or
  LibreLane), per CLAUDE.md's two-flows rule; the cell figures here are klt
  cell area, the die/core figures are the LibreLane model.

## Open items

1. Re-pull `tile_sizes.yaml` when the 8×4 template lands; refresh the table.
2. Measure, on the klt flow, the cell cost of one #130 assist once it is
   specified, replacing the estimate under C.
3. Read the CI wall-clock of the existing `gds` runs and record it (#134).
4. Show or refute that 256 words binds once the DR 0013 boot images exist
   (candidate B).

## Alternatives considered

- **Move to 6×4 now.** Rejected: nothing in the candidate list uses it
  (4.3 % of core), it raises the 6-hour run risk for no judged benefit, and the
  8×4 template may change the numbers.
- **Move to 8×4 on arrival.** Rejected for the same reasons; "an upgrade" is
  not a reason.
- **Say nothing until an area-hungry feature exists.** Rejected: the organizers
  answered the question this repo had left open, and the recommendation is
  cheap to state.
