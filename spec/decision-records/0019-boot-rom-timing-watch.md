# 0019: Boot-ROM Growth and the Slow-Corner Fetch Path — Accept and Watch

Status: **Proposed 2026-10-11.** Like the other records since DR 0001, this
is a proposal; the two-key (`RATIFY-KEY`) mechanism has not run (DR
[`0006`](0006-two-key-ratification-never-ran.md), issue #44). It changes no
RTL, no pinned file of DR 0017's freeze, no `src/config.json` value and no
target-spec value. It makes no row met.
Date: 2026-10-11
Issues: #246 (this finding); #211 (the boot-ROM change that exposed it);
#139 (program loading); #173, #208, #201 (earlier macro-pin slew repairs).

## Context

Issue #211 grew the boot ROM from 223 to 232 words (the UART load's
count-complement check; DR [`0013`](0013-program-loading.md), entry of
2026-10-11). The LibreLane gds run
[38108543866](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/actions/runs/38108543866)
at `f1b21df` was green at all three corners, and moved two numbers against
the 223-word run 38083802720. Both are LibreLane post-route OpenSTA numbers
at the 20 ns constraint (flow: **LibreLane CI**; the klt flow has no timing
for this design, klayout-tools#2635, so there is no second flow to compare):

| | 223-word ROM | 232-word ROM |
|---|---|---|
| Worst setup slack, slow / typ / fast | +3.527 / +9.806 / +11.167 ns | +1.925 / +8.796 / +11.109 ns |
| Worst hold slack, fast | +0.1399 ns | +0.1291 ns |
| Max-slew violations, slow / typ / fast | 0 / 0 / 0 | 2 / 0 / 0 |
| Max-cap violations | 0 / 0 / 0 | 0 / 0 / 0 |

The evidence record is
[`verification/records/librelane-corner-timing/records/20261011-040000-1c19c24.md`](../../verification/records/librelane-corner-timing/records/20261011-040000-1c19c24.md);
DR 0013's 2026-10-11 entry states the same numbers.

The binding slow-corner path is the program SRAM read (`u_prog_mem.u_sram`
`A_DOUT[9]`) through `exec_word = fetch_rom ? rom_word : instr_word` into a
flop; the ROM feeds the same mux, so ROM growth lands on this path. The two
slew violations are one internal net (`_3962_/Y`, a `nor3_1`, driving
`_3965_/B`, a `nor4_1`): 2.99 ns against a 2.51 ns limit at
`nom_slow_1p08V_125C`. It is not an SRAM macro pin (that class was #201) and
the flow does not fail on it.

Not known: whether the 1.6 ns of slow-corner setup loss is the nine ROM words
or placement variation (one run per design, no seed sweep), and what the
violating net's logic is.

## Decision (proposed)

1. **Option 1 of issue #246 is taken: accept and watch.** Setup and hold are
   met at every corner with margin, and the slew violation is not a failing
   check. Nothing in the design or the flow changes.
2. **Option 2 (flow repair in `src/config.json`) is not taken now.** A
   max-slew or design-repair setting can only be shown to work by a LibreLane
   run, which this record's author cannot make, and an unverified flow change
   that moves placement could erode the +1.9 ns margin it is not meant to
   touch. It stays open as the first remedy if the slew count grows or if
   the net is traced to something a setting can fix.
3. **Option 3 (register the ROM output or the fetch mux) is deferred.** It
   changes fetch timing, so it is an architecture change under DR
   [`0017`](0017-submission-isa-freeze.md)'s freeze and would need its own
   record saying whether it invalidates evidence. It is not needed while
   setup margin is positive.
4. **Re-measure before further ROM growth.** Any change that adds boot-ROM
   words (24 are left) or otherwise touches the `exec_word` mux path must,
   in the same PR or the one that follows, cite a LibreLane gds run showing
   the slow-corner worst setup slack and the slow-corner max-slew count, and
   state them against this record's 232-word row. Trigger for escalating to
   option 2 or 3: slow-corner worst setup slack below +1.0 ns, any setup
   violation at any corner, or more than the current 2 slew violations.
5. **No claim is made about a post-change number.** This record adds no new
   timing measurement. Target-spec row 4 is not met by the LibreLane numbers
   alone; that stays true.

## What would settle the unknowns

A LibreLane run of the 223-word design at a second seed, and one of the
232-word design at a second seed, would separate ROM growth from placement
variation. Tracing `_3962_`/`_3965_` back to RTL in the run's netlist would
say whether it is ROM or decode logic. Neither is required by this record.
