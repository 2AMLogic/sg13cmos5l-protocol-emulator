# 0024: The LVS Comparison Reference, Its Provenance and Coverage, and an Audit of the Evidence Against It

Status: **Proposed 2026-11-14.** Like the other proposed records it is not bound
by the two-key (`RATIFY-KEY`) mechanism (DR [`0006`](0006-two-key-ratification-never-ran.md)).
It changes no RTL, spec value, claim or ratified text, repoints no manifest
citation and grades no item: T1 item 4 stays `unmet`. It states a contract and
audits the existing evidence against it; it does not declare the contract met.
Date: 2026-11-14
Issues: #396; signoff tracker #329 (operator ruling 2026-10-19); T1 item 3's
sibling record DR [`0023`](0023-sram-macro-nwell-drc-findings.md).

## Context

T1 item 4 (LVS clean) reads `status: unmet`, `reason: check_failed`,
`citation: null` in the verdict of record
(`verification/records/signoff-baseline/artifacts/20261108-120008-79d0aef/signoff-report.json`;
the narrative record is `verification/records/signoff-baseline/records/20261108-120008-79d0aef.md`).

Two `klt lvs` legs exist on the same layout and disagree. One is cited by the
manifest and fails; one passes and is informational only. The operator ruling
recorded on #329 (2026-10-19) settled the direction — grade physical
connectivity against an **explicitly named post-route reference**, paired with
**independent evidence connecting the original RTL to that reference** — and
authorized exactly one next step: prepare a reviewed decision record and
evidence-gap plan. It explicitly withheld permission to "simply cite the passing
alternate comparison and declare T1 item 4 met". This record is that
preparation. No tool was run for it; every number below is read from a committed
record or envelope and names the flow that produced it.

**The two flows** (`CLAUDE.md` § "Two flows, one record of truth"), because
every number in this record belongs to one of them:

* **The LibreLane flow** — `TinyTapeout/tt-gds-action@ihp-cmos5l`, LibreLane
  `3.1.0.dev3`, IHP-Open-PDK `2bbec755dc67ca3db0261c3d6163e15735d66710`,
  per the run's own `pdk.json`. It produced the routed GDS and the post-route
  gate-level netlist, from [gds run 38136727636](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38136727636)
  at `6dd0e9d`.
* **The klt flow** — klt `0.8.0` (KLayout `0.30.12`), plus Yosys `0.69` for the
  independent-synthesis reference. It produced both `klt lvs` legs, the
  extraction and the DRC result.

All hashes and file identities in this record were re-derived from `origin/main`
@ `3619c879` on 2026-11-14 with `sha256sum` and `cat`, not copied from prose.

## 1. The comparison reference, and the flow that produces it

**The reference for physical connectivity is the post-route gate-level Verilog
netlist emitted by the LibreLane flow** for the submitted GDS — the
`tt_submission` netlist of gds run 38136727636 at `6dd0e9d`,
`sha256:fbc7bc30a4987aaa47ea2633df46993ebe1ee42171edc54173e25ff343e085ba`.

Because `klt lvs`'s `gate-level-verilog` converter accepts non-ANSI port
declarations only, the file actually handed to the tool is that netlist
prefixed by the hard-macro pin-list stub
(`verification/records/librelane-gds-signoff-check/artifacts/20261001-111857-8a94265/macro-stub-RM_IHPSG13_1P_256x16_c2_bm_bist.v`,
1,128 bytes). **The concatenation is exact and mechanically re-derivable**:

```
cat macro-stub-RM_IHPSG13_1P_256x16_c2_bm_bist.v reference-asrouted.v
  == reference-asrouted-with-macro-stub.v
  == sha256:311c1c6d739d5b1a895096d9da4b7ac549deef0ed264a65dbb0d461b971221b2
  == klt-lvs-asrouted.json  environment.reference_sha256
```

(verified 2026-11-14; artifacts under
`verification/records/librelane-gds-signoff-check/artifacts/20261027-190021-1ec5186/`).

**Why this reference and not the klt/Yosys one.** The two candidate references
answer different questions, and the contract names both roles rather than
picking a winner:

* The **post-route reference** asks *does the GDS implement the netlist the
  P&R flow says it routed*. The earlier record states its limit in its own
  words: this compare "is topology-only and checks the GDS against what the
  P&R flow believes it built; it is not an independent-synthesis cross-check"
  (`verification/records/librelane-gds-signoff-check/records/20261010-041033-fb86d71.md`).
  Used **alone** it cannot detect an error introduced upstream of the netlist,
  because the netlist is the thing under test's own account of itself.
* The **klt/Yosys reference** asks *does the GDS implement the RTL, as a second
  toolchain independently synthesizes it*. That is the stronger question, and
  it is the one the manifest currently cites. It is also the one that fails.

So the post-route reference is the reference for **physical connectivity**, and
it is admissible for item 4 **only** when paired with independent
RTL-to-reference evidence under section 4. A passing post-route compare with no
such pairing is not item-4 evidence; it is a routing self-consistency check.

## 2. Provenance each reference, extraction and result must carry

For an item-4 claim, each of the following must be pinned by a hash recorded in
a committed envelope, re-derivable with `sha256sum`:

1. **The layout** — the routed GDS bytes.
2. **The extraction input and output** — which GDS was extracted, by which klt
   version, producing which netlist bytes.
3. **The reference** — the exact bytes compared, *including* any stub
   concatenation, plus the flow, tool versions and commit that produced the
   pre-concatenation netlist.
4. **The result** — the envelope's own `status`, `error_count`, counts and
   category counts, and the tool and PDK revisions that produced them.
5. **The manifest pin** — and the record must say *what the pinned hash is the
   hash of*, since `manifests/README.md` makes that envelope-dependent.

### What the existing evidence actually pins

| Link | Pinned? | Where |
|---|---|---|
| RTL source bytes | **yes**, and at the right commit — see below | record-meta `inputs`, re-derived at `6dd0e9d` |
| RTL -> LibreLane netlist | by run + commit (the synthesis step itself is not re-derivable here) | gds run 38136727636 at `6dd0e9d` |
| LibreLane netlist bytes | **yes** `sha256:fbc7bc30...` | record-meta `inputs`, and re-derived |
| Netlist -> compared reference | **yes**, exactly | `cat` identity above; `environment.reference_sha256` |
| Routed GDS bytes | **yes** `sha256:2c8fb81d18ab9d6cfd2ed0566e32f16d3cebdbbdff41520afbff29fa0e19c3af` | record-meta `inputs`, and re-derived |
| GDS -> extracted netlist | **NO** — see below | — |
| Extracted netlist bytes | **yes** `sha256:e11397622f373fea6a434c2698293408a171db217fd8f9d708b9158890ddf7f4` | `environment.layout_sha256`, both legs |
| Result | **yes** | the two envelopes |

**The RTL side is pinned at the netlist's own build commit, which is worth
stating because it is easy to assume otherwise.** The LVS record's `record-meta`
hashes five design inputs, but at *its* revision (`1ec5186`), not at the
revision the netlist was built from (`6dd0e9d`). Those are different commits, so
the hashes would attest nothing about the netlist's source unless the files are
unchanged between them. They are: re-derived 2026-11-14, all five are
byte-identical at `6dd0e9d` and `1ec5186` and equal the record-meta values —
`src/tt_um_2amlogic_protocol_emulator.v` `8c380b9165a0...`,
`rtl/protocol_core.v` `d4bab243a80a...`, `rtl/protocol_boot_rom.v`
`329ed189d457...`, `rtl/protocol_program_memory.v` `2b08865ab24d...`,
`src/config.json` `199d85202619...`. So the RTL bytes the netlist was
synthesized from *are* pinned by the item-4 record. What is not re-derivable
from committed evidence is the synthesis step between them — that rests on the
LibreLane run, which is the flow under test, and is exactly why section 4
requires independent RTL-to-reference evidence.

**The one broken link is GDS -> extracted netlist, and it is a gap in the
item-4 envelope itself.** In both legs `provenance.input` reads
`{"content_hash": "sha256:e1139762...", "role": "netlist"}` and
`environment.layout_sha256` is that same value — the **extracted SPICE
netlist**, not the GDS. `provenance.deck` is `null` and
`environment.extracted_netlist` is `null`. The GDS hash `sha256:2c8fb81d...`
appears **nowhere** in either LVS envelope. So re-hashing the item-4 citation's
pin attests the extraction *output* and says nothing about which layout it came
from; that link rests on the surrounding record's prose and on the DRC
envelope's own input pin, not on the cited evidence.

**A provenance subtlety the record must state, because it looks like an error
and is not.** The manifest pins item 4 as:

```
manifests/sg13cmos5l-protocol-emulator.json  evidence["4"]
  file:         ...artifacts/20261027-190021-1ec5186/klt-lvs-klt-netlist.json
  content_hash: sha256:e11397622f373fea6a434c2698293408a171db217fd8f9d708b9158890ddf7f4
```

That hash is **not** the hash of the cited JSON file (whose bytes are
`sha256:65a549bca8f39bc4d3edfe26d458261684aba7c3cf7b50836951ec6848c707fb`). It is
the envelope's `provenance.input.content_hash`, which is correct under
`manifests/README.md` § "Every citation pins a `content_hash`" for a *completed*
`klt lvs`: exit 3 is a mismatch, not an error, so the envelope is a completed
run and the pin is its input hash. Note that `manifests/README.md` describes
item 4's envelope parenthetically as "a `klt` error envelope", which would put it
on the other branch of that rule; that description is stale with respect to the
current citation. The manifest as committed is right; the README's aside is not.
Correcting it is out of scope here and is noted for whoever next edits that file.

## 3. Coverage required

An item-4 claim must state, for each of the four levels below, whether it is
checked, and must not let an unchecked level pass as checked.

1. **Gate-level signal connectivity** — every net and pin of the top level and
   of every standard-cell instance.
2. **Macro interiors** — whether anything inside a hard macro is compared.
3. **Device bodies** — whether each device's body/well terminal is verified
   against the substrate/well-tap convention.
4. **Device parameters** — whether device types, sizes and parameters are
   compared within a stated tolerance.

### Audit: what the two legs actually cover

Both legs, klt flow, from `klt lvs` at klt `0.8.0` in record
`verification/records/librelane-gds-signoff-check/records/20261027-190021-1ec5186.md`.

**(2) Macro interiors — not covered, by construction.** Both references are the
stub concatenation of section 1, and the stub's own header says it "is a
pin-list declaration for the LVS reference side only; it models nothing." It
declares 17 ports and no contents. Nothing inside the foundry SRAM macro
`RM_IHPSG13_1P_256x16_c2_bm_bist` is compared by either leg. This is the same
macro whose interior carries all 4,484 klt `0.8.0` DRC findings (DR 0023), so
the macro interior is unchecked by **both** T1 item 3 and T1 item 4.

**(3) Device bodies — explicitly unchecked, in the tool's own words.** Both
envelopes carry an identical `body_verification` block:

> `"status": "unchecked"`, `"device_count": 0`, `"findings": []`,
> `"reason": "no request.layout.deck was given (the pre-extracted
> request.layout.netlist form), so nothing establishes this layout's
> substrate/well-tap convention and no synthesized body net can be told apart
> from a real one -- this run verified nothing about the device bodies either
> way"`

This is the concrete form of #329 item 3's "unchecked device bodies": not a
coverage preference, and not a silent omission — the tool reports that it
verified nothing either way, and gives the cause (the pre-extracted
`layout.netlist` request form, with `provenance.deck: null`).

**(4) Device parameters — nothing compared.** `device_parameter_coverage` is
`[]` and `device_classes` is `null` in both legs, and both report
`counts.devices` of **layout 0 / reference 0 / matched 0**. The extraction
yields no devices, so no transistor-level comparison of any kind takes place.
Both references are gate-level Verilog, so there are no reference devices to
compare against either. Device-level LVS in the ordinary sense is **not
performed anywhere in the current evidence**.

**(1) Gate-level signal connectivity — attempted by both, with opposite
results.** Counts verbatim, klt flow:

| | klt/Yosys leg (cited) | post-route leg (informational) |
|---|---|---|
| envelope | `klt-lvs-klt-netlist.json` | `klt-lvs-asrouted.json` |
| `status` | **`mismatch`** (exit 3) | `match` |
| `power_connectivity.status` | `match` | `match` |
| `error_count` | **88** | 0 |
| `mismatch_count` | 108 | 114 |
| nets layout / reference / matched | 3,448 / 2,562 / **0** | 3,448 / 3,435 / 3,777 |
| pins layout / reference / matched | 45 / 43 / **0** | 45 / 43 / 385 |
| devices layout / reference / matched | 0 / 0 / 0 | 0 / 0 / 0 |
| `environment.reference_sha256` | `005295404de2...` | `311c1c6d739d...` |
| instances | 8,506 | 8,506 |

**An open question about the `matched` field, which the contract must settle
before relying on it as a coverage measure.** On the post-route leg
`counts.nets.matched` is 3,777, which exceeds both the layout population
(3,448) and the reference population (3,435); `counts.pins.matched` is 385
against populations of 45 and 43. A count of matched members cannot exceed the
set it is drawn from, so this field is evidently not "distinct nets matched"
but some pairing-event tally whose definition the envelope does not state. It is
recorded here verbatim and **not** interpreted. Until its definition is pinned,
`matched` must not be quoted as a coverage figure in any claim; `status`,
`error_count` and the category counts are the fields with stated meanings. (The
tool-side gap is a candidate for the friction protocol; filing it is not a
deliverable of this record.)

**Power connectivity, both legs.** `status: match`, `power_pins` `["VDD",
"VSS"]`, derivation rule `declared-by-every-instantiated-master`
(`corroborated: true`), `instance_count` 8,506, `findings: []`. `expected_nets`
is `null` in both — no caller declaration, so the check used its fallback
(every instance's same-named pin reaching the same net as every other's), which
is the weaker of the two modes the item-4 text describes. `master_count` differs
between the legs, 47 for the post-route reference against 26 for the klt/Yosys
one, consistent with the post-route netlist instantiating fill, decap, antenna,
tie and delay cells that an independent synthesis does not emit.

### Coverage summary

| Level | Covered? |
|---|---|
| Gate-level signal connectivity | attempted by both legs; **passes only against the non-independent reference** |
| Macro interiors | **no** — stub models nothing, both legs |
| Device bodies | **no** — `body_verification.status: unchecked`, both legs |
| Device parameters | **no** — `device_parameter_coverage: []`, devices 0/0, both legs |
| Power pin-to-net | yes, in fallback mode, both legs; not a geometric grid check |

## 4. Independent RTL-to-reference evidence required

Because the post-route reference is the design's own account of itself
(section 1), item 4 may rest on it only beside evidence that the **original
RTL** and that reference describe the same logic, produced by something other
than the flow under test. Admissible forms, strongest first:

1. **Formal equivalence** (RTL vs the post-route netlist), tool and version
   named, with its assumptions and any black-boxed module stated.
2. **An independent-synthesis structural compare** — a second synthesis of the
   same RTL compared against the netlist, i.e. what the klt/Yosys leg attempts.
3. **Functional simulation of the reference netlist** against independent
   reference models, with fault-injection negative controls proving the benches
   can fail.

A claim must state which form it rests on and that form's limits.

### Audit: what exists

**Form 3 exists, and is strong of its kind.** The gate-level cocotb regression
runs on the **same bytes** as the comparison reference — this is the single
best-attested link in the chain, and it is hash-checkable rather than argued:

```
verification/records/post-layout-sdf-regression/artifacts/20261011-114800-e5a0bae/tt_um_2amlogic_protocol_emulator.v
verification/records/librelane-gds-signoff-check/artifacts/20261027-190021-1ec5186/reference-asrouted.v
  both == sha256:fbc7bc30a4987aaa47ea2633df46993ebe1ee42171edc54173e25ff343e085ba
```

(verified 2026-11-14 @ `3619c879`. Each record independently states this file is
the `tt_submission` netlist of LibreLane gds run 38136727636 at `6dd0e9d`.)

The latest run is
`verification/records/firmware-gate-level/records/20261012-072503-243b6a4.md`
(cocotb 2.1.0, Icarus Verilog 13.0): runner exit 0, `OK: all golden runs pass
and all negative controls fail`; `summary.json` has 25 rows — 11 golden
modules, 11 stuck-at negative controls, 3 `uio_oe[3]` pad negative controls —
every one `as_required: true`. Golden: `test_firmware_uart` 3/3,
`test_firmware_uart_rx` 11/11, `test_firmware_spi` 3/3, `test_firmware_i2c`
4/4, `test_firmware_i2c_sr` 5/5, `test_control_space` 10/10, `test_boot_rom`
7/7, `test_boot_spi` 6/6, `test_primitives` 11/11, `test_boot_uart` 8/8,
`test_load_integrity` 9/9. Siblings on the same netlist:
`firmware-ws2812-gate-level` (`20261011-115014-e5a0bae`),
`firmware-ps2-gate-level` (`20261011-120015-e5a0bae`) and
`post-layout-sdf-regression` (`20261014-111000-25a41c3`).

**Its limits, which any claim resting on it must state:** zero-delay functional
simulation only (no SDF, no SRAM timing annotation, no measured baud); the
white-box bench reads are RTL-only, so on gates those modules check pins alone;
and it is coverage by testbench, not proof — it establishes that the reference
netlist satisfies the committed benches and independent protocol models, not
that it is logically equivalent to the RTL.

**Form 1 does not exist anywhere in the repository.** `grep -rni 'equivalen'
spec/ docs/` returns 4 hits (2026-11-14 @ `3619c879`), all ordinary uses of the
English word — `docs/environment.md` lines 87 and 161, and DR 0016 lines 69 and
122. There is no formal-equivalence run, tool, record or envelope. Exactly as
#329 item 2 requires, this record names that as the missing proof rather than
letting simulation stand in for it.

**Form 2 exists and fails.** It is the klt/Yosys leg: 88 errors, 0 of 3,448
layout nets matched. See the hypothesis below.

## 5. The failing comparison: both results kept, and the explanation held as a hypothesis

Both legs are preserved and cited; neither is deleted, softened or re-graded by
this record, and the manifest continues to cite the failing one.

**The prevailing explanation is a hypothesis, not a demonstrated result.** The
records attribute the klt/Yosys leg's 88 errors and 0-of-3,448 net match to the
reference being a **pre-place-and-route** netlist compared against a
**post-route** extraction — different net populations (3,448 vs 2,562),
different instance sets, no correspondence to anchor the walk. Supporting
evidence in the envelope: `category_counts` shows `hints.rejected` 43,
`topology` 45, `topology.reference_port_alias_joined` 17,
`topology.flattened` 1, `topology.power_only_pruned` 1,
`topology.top_level_pins_anchored` 1 — a profile consistent with the compare
failing to establish correspondence at all rather than finding a specific
wiring error, and the record notes no converter error occurred and
klayout-tools#3078 did not fire.

**But consistency is not proof.** As #329 item 3 puts it, "the pre-/post-route
explanation is not a proof excluding converter gaps". A converter or
abstraction defect would plausibly produce the same signature — total
correspondence failure — as a reference-vintage mismatch. Nothing committed
distinguishes the two. **Until a cited record demonstrates it, the pre-/post-route
account of the 88 errors is a hypothesis**, and no claim may describe the
failing leg as "explained" or "expected" on its strength. Discharging it needs a
compare whose reference is a post-route independent synthesis, or a tool-side
account of the rejected hints — neither of which exists today, and neither of
which this record authorizes running.

## 6. Extraction freshness

`klt extract` was **not** re-run when the klt pin moved to `0.8.0` (issue #356).
Both legs read the frozen `layout-gate-level.spice`
(`sha256:e11397622f373fea...`) extracted at the klt `f979a965` dev pin, and the
record of record says in its own words that **"extraction at 0.8.0 is
unevidenced"**. The DRC verdict for the same GDS *did* change under `0.8.0`
(clean -> 4,484 findings, DR 0023) purely because the deck widened, which is
direct evidence that a klt pin move can change a verdict on unchanged bytes. An
item-4 claim must therefore either re-extract at the pinned version or disclose
that its extraction predates the pin. The contract treats an extraction from a
different klt version than the compare as **disclosed-stale**, not as fresh.

## 7. The 114 non-error findings

The post-route leg reports `mismatch_count` 114 with `error_count` 0 — 112
`topology`, 1 `topology.power_only_pruned`, 1 `topology.top_level_pins_anchored`.
These have been carried unchanged in every record of this experiment since
2026-10-10 and **have never been adjudicated**. The contract must say whether a
`topology`-class non-error mismatch is admissible beside a `match` verdict.

**This record's position:** a `topology`-class mismatch is admissible **only
when enumerated with the claim**, never silently, because the category means
nets were paired ambiguously and resolved structurally — i.e. the compare made a
judgement the envelope does not justify net by net. T1 item 4's own text already
requires that "warnings-only mismatches must be listed with the claim"; this
record adds that 112 ambiguous pairings on a 3,448-net layout is a figure a
reviewer must see, not a detail to summarize as "0 errors".

One further caution, for honesty about what changed: the same leg's net counts
are **not** stable across records. Record `20261010-041033-fb86d71` reports
layout 1,981 / reference 1,979 nets for this compare; record
`20261027-190021-1ec5186` reports 3,448 / 3,435 with the same 114 mismatches and
the same categories. The counts nearly doubled while the findings did not move.
Nothing committed explains that, and this record does not explain it either — it
is flagged as an unresolved observation about the stability of the passing leg.

## Evidence audit: the gap list

Each row names the record or file that would have to exist. Nothing here is
authorized to be run by this record.

| # | Contract requirement | Status | What is missing / what to cite |
|---|---|---|---|
| 1 | Reference named, hash-pinned, stub concatenation exact | **met** | `sha256:fbc7bc30...`, `311c1c6d...`; `cat` identity re-derived 2026-11-14 |
| 2 | Reference's producing flow and commit named; its source RTL pinned | **met** | LibreLane `3.1.0.dev3`, gds run 38136727636 @ `6dd0e9d`; the five record-meta design-input hashes are byte-identical at `6dd0e9d` and `1ec5186` (re-derived 2026-11-14) |
| 3 | GDS bytes pinned | **met** | `sha256:2c8fb81d...` |
| 4 | GDS -> extraction link pinned *in the item-4 envelope* | **missing** | envelope pins only `role: "netlist"`; GDS hash absent from both legs. Needs an extraction envelope cited beside the LVS result, or a `klt lvs` form that records the layout it extracted |
| 5 | Extraction at the pinned klt version | **missing** | extraction at `f979a965`, compare at `0.8.0`; "extraction at 0.8.0 is unevidenced". Needs a re-extraction record, or disclosure as stale |
| 6 | Gate-level signal connectivity vs an independent reference | **failing** | klt/Yosys leg: 88 errors, 0 of 3,448 nets matched |
| 7 | Macro interior coverage | **missing by construction** | stub "models nothing"; no record compares macro internals |
| 8 | Device-body verification | **missing** | `body_verification.status: unchecked` both legs; needs a deck-form `klt lvs` request, not the pre-extracted netlist form |
| 9 | Device parameter coverage | **missing** | `device_parameter_coverage: []`, devices 0/0 both legs; no device-level LVS exists |
| 10 | Formal RTL-to-reference equivalence | **missing** | no such evidence in the repository (`grep -rni equivalen spec/ docs/`: 4 ordinary word uses) |
| 11 | Functional RTL-to-reference evidence on the reference bytes | **met, with stated limits** | `firmware-gate-level` `20261012-072503-243b6a4` + 3 siblings; zero-delay, functional, white-box reads RTL-only |
| 12 | Pre-/post-route explanation demonstrated, not assumed | **missing** | held as a hypothesis in section 5 |
| 13 | The 114 non-error findings adjudicated | **missing** | never adjudicated since 2026-10-10; position proposed in section 7 |
| 14 | `matched` field definition pinned | **missing** | `matched` exceeds its population on the passing leg; unusable as a coverage figure until defined |

**Of fourteen requirements: three are met, one is met only with limits that
forbid reading it as equivalence, one is failing outright, and nine are unmet by
any committed evidence.** On this contract T1 item 4 cannot read `met` today
under any reading, and this record does not propose that it should.

## Options (owner's choice; none is applied here)

1. **Adopt this contract as written and keep item 4 `unmet`.** Honest, cheap,
   and the only option consistent with the 2026-10-19 ruling as given. Item 4
   stays red until the gaps above are closed. Costs nothing now; closes nothing.
2. **Adopt the contract and authorize the two cheapest gap closures** —
   re-extract at klt `0.8.0` (gap 5, about an hour per the record's own
   estimate) and re-run the post-route leg in the deck form rather than the
   pre-extracted netlist form, which is what would make `body_verification`
   report something other than `unchecked` (gap 8). Neither touches the design.
   Both are new tool runs and need their own authorization; the ruling of
   2026-10-19 withheld "no new EDA campaign" authority, so this option is a
   request, not a plan.
3. **Adopt the contract, and accept the post-route leg plus the gate-level
   regression as item-4 evidence** with gaps 4, 5, 7, 8, 9, 10, 12, 13 and 14
   disclosed in the claim. This is the option the ruling specifically declined
   in advance ("do not simply cite the passing alternate comparison and declare
   T1 item 4 met"). Recorded for completeness; it should not be chosen without
   a new operator ruling that supersedes that sentence.
4. **Pursue formal equivalence** (gap 10) as the route to a strong item 4. It is
   the only form that would make the failing klt/Yosys leg's verdict
   non-blocking, because it answers the RTL-to-reference question directly
   rather than through a second synthesis. No open-source SG13CMOS5L
   equivalence flow is evidenced in this repository, so the cost is unknown and
   plausibly exceeds the time to 2027-01-18. Likely a deferral with a written
   reason rather than a plan.

## Recommendation

**Option 1 now**, with option 2 as the next step if and when a tool run is
authorized: it is the only disposition that matches the ruling that authorized
this record, and the gap list above is precisely the agenda option 2 would
work through. Option 4 is the honest long answer and is very likely to become a
written deferral under the deadline-discipline rule in `CLAUDE.md` rather than
a campaign before 2027-01-18.

Nothing is decided or applied by this record. T1 item 4 remains `unmet` with
`citation: null`, the manifest is unchanged, both LVS legs are preserved as
cited, and #329 keeps its tracker role and its park. The contract in sections
1-4 takes effect only if the owner adopts it.
