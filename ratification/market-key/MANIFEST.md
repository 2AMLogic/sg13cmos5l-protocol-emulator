# MANIFEST — generated canary variant

Generated 2026-08-27 by an internal, private-repo-only generation tool. Do not hand-edit; regenerate instead.

## Skill files

- `SKILL.md`
- `comp-table-format.md`
- `rubric.md`

## Comp data

None. This block's class (`protocol-emulator`) has no seeded comp-library
entry as of this install (2026-09-21), and `comps/` is generated per class
anyway — it is the one part of the tree that is *not* a straight copy for a
class the upstream library does not cover. The market key is fully
functional without it: per `SKILL.md`'s "Two operating modes" (installed
mode, Step 0), a bundled entry that does not match (or is absent for) the
block's class means the key researches comps from public sources from
scratch. Seeding the upstream class entry so a later regeneration can
bundle `comps/protocol-emulator.md` is tracked as follow-up work (see the
installing PR's body).

This directory tree is meant to be copied as a unit into a canary repo — see the generation tool's own documentation for the exact install layout and for the process this manifest is the output of.
