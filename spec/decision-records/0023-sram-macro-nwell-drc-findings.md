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
classifies them: the PDK's own KLayout runset reports 0 on the same GDS but
implements only `NW.b1` (the counterpart of `nwell.space.2`) and has no
counterpart for the enclosure rule, so real-vs-artifact is **undetermined**.

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
