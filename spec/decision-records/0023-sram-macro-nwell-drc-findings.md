# 0023: SRAM Macro NWell DRC Findings Under the klt 0.8.0 Deck: Waiver Options

Status: **Proposed 2026-10-28.** Like the other proposed records it is not bound
by the two-key (`RATIFY-KEY`) mechanism (DR [`0006`](0006-two-key-ratification-never-ran.md)).
It changes no RTL, spec value, claim or ratified text, and applies no waiver.
Date: 2026-10-28
Issues: #360; tracker #351; upstream 2AMLogic/klayout-tools#4520.

## Context

T1 item 3 (DRC clean) went `met` -> `unmet` when the klt pin moved to 0.8.0: the
unchanged GDS (`sha256:2c8fb81d...`) now reads 4,484 findings, all inside the
foundry SRAM macro `RM_IHPSG13_1P_256x16_c2_bm_bist` (4,352
`nwell.enclosing.pactiv.1` in the bit-cell sub-cells, 132 `nwell.space.2` in the
matrix/column sub-cells), none in logic or routing. Record
`verification/records/librelane-gds-signoff-check/records/20261028-182000-18198b7.md`
classifies them. Every finding lies fully inside the macro's SRAM marker layer
(25/0). The PDK's own KLayout runset (pinned PDK `2bbec755dc67`, KLayout 0.30.12)
reports 0 on the same GDS for both rules, but for the enclosure rule (`NW.c`, in
the PDK's `sg13cmos5l_maximal.drc`) it checks NWell *minus* the SRAM marker, a
scoping the klt deck does not apply, so the 4,352 enclosure findings are a
deck-scoping difference. The 132 `nwell.space.2` findings (runset `NW.b1`, no
SRAM scoping) are an unexplained klt-vs-runset disagreement. Real-vs-artifact
against a foundry rule document remains **undetermined**.

## Options (owner's choice; none is applied here)

1. **Waive the macro cell** with a `klt drc --waivers` file scoped to
   `RM_IHPSG13_1P_256x16_c2_bm_bist` and these two rules. Item 3 can then read
   `met` with the waiver and the unwaived count (0) disclosed. Cheapest; rests on
   the assumption that foundry macro layout is signed off by the foundry, which
   this record has not verified against a foundry document.
2. **Wait for upstream** (klayout-tools#4520): keep item 3 `unmet`, honestly, until
   the deck's net handling / macro scoping is clarified. No design risk; item 3
   stays red on the dashboard until then.
3. **Change the macro or placement** (a different macro size/instance). Does not
   obviously help: the findings are in repeated bit-cell geometry that any
   instance of this macro family shares. Costs area and re-verification; not
   recommended without evidence the findings are placement-dependent.

## Recommendation

Option 2 now, option 1 if the owner accepts foundry sign-off of the macro as the
basis (and the deadline, 2027-01-18, nears without an upstream answer). Nothing
is decided or applied by this record.

## Update 2026-10-29: operator ruling (klayout-tools#4530)

The operator ruled on 2026-10-28 that DRC violations inside unmodified foundry
cells are a **disclosed T1 item-3 exception** when they reproduce on the bare
cell, are pinned to the cell's content hash with their rules and counts, and are
disclosed in the claim. Option 1 above is therefore replaced by that rule: no
per-block waiver file and no per-block decision are needed. Condition 1 is
measured in record `20261029-041827-063c7fd`: the bare macro alone reports the
same 4,352 `nwell.enclosing.pactiv.1` and 132 `nwell.space.2` findings, and its
geometry digest is identical bare and in the block. Grading it mechanically is
blocked on klayout-tools#4582 (the grader rejects sub-cell attribution) and on a
klt release carrying the exception grading; until then item 3 stays `unmet` and
the manifest is not re-pointed. Options 2 and 3 are not pursued.
