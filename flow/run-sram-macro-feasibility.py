#!/usr/bin/env python3
"""flow/run-sram-macro-feasibility.py -- answer the question issue #39 asks
first: *does a program-memory SRAM macro exist for this PDK at all, and does
it fit a legal Tiny Tapeout CMOS5L tile allocation?*

This is deliberately a **measurement**, not an opinion. It:

  1. resolves the `ihp-sg13cmos5l` PDK with `klt pdk find` and reports
     whether `libs.ref/sg13cmos5l_sram` exists and how (real directory vs.
     symlink, and to what -- the answer is load-bearing, see the record);
  2. enumerates the single-port macro family from its LEF `SIZE` statements
     (the authoritative footprint the placer honours);
  3. runs `klt stats` (drawn bbox) and `klt layers` (layer/datatype
     inventory) over the selected macro's GDS;
  4. cross-checks that inventory against the Tiny Tapeout CMOS5L precheck's
     own layer allowlist (vendored with provenance in
     `flow/tt-cmos5l-reference.json`), resolved through the PDK's own
     KLayout `.lyp` exactly as `precheck.load_layers()` does -- i.e. it
     answers "would the competition's precheck reject this macro's
     geometry?" mechanically rather than by assertion;
  5. re-derives the tile-budget arithmetic for every legal `tiles` value
     from the flow-of-record's own `tile_sizes.yaml` DIE_AREA table, for
     three candidate program-memory implementations: the SRAM macro, and
     the flip-flop array as measured by each of the two flows.

Every number it emits is either read out of the PDK / the vendored upstream
tables, or arithmetic over those. It runs no synthesis and no place-and-route
and therefore claims no utilization, timing, or routability result -- those
belong to the implementation issue, not to this feasibility probe.

Usage:
    ./flow/run-sram-macro-feasibility.py
    KLT_BIN=.venv/bin/klt ./flow/run-sram-macro-feasibility.py
    ./flow/run-sram-macro-feasibility.py --out flow/sram-macro-feasibility-results.json

Exits non-zero if the PDK cannot be resolved, the SRAM library is absent, or
any `klt` invocation fails. A macro that FAILS the layer cross-check is a
reported result, not a crash -- that is the finding the run exists to make.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_JSON = REPO_ROOT / "flow" / "tt-cmos5l-reference.json"
DEFAULT_OUT = REPO_ROOT / "flow" / "sram-macro-feasibility-results.json"

PDK_NAME = "ihp-sg13cmos5l"
SRAM_LIB = "sg13cmos5l_sram"
STDCELL_LIB = "sg13cmos5l_stdcell"

# The macro this repo actually needs: DR 0001's ratified program memory is
# 256 words x 16 bits, single-ported (load phase and run phase are mutually
# exclusive by that record's own construction, so one port suffices).
TARGET_MACRO = "RM_IHPSG13_1P_256x16_c2_bm_bist"

# The competition's stated ceiling (Jane Street post; spec/target-spec.md
# row 7) and this repo's ratified target (same row).
COMPETITION_MAX_TILES = "8x4"
RATIFIED_BUDGET_TILES = "2x2"


def die(msg: str) -> "None":
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


# Verbs this runner invokes, checked the way layout/toolchain.json's contract
# asks: look each one up in `klt --help` before doing anything, and fail loudly
# naming the missing verb rather than skipping the check silently.
#
# These three are deliberately NOT added to that file's
# `klt_required_commands` list by this issue: `layout/toolchain.json` is a
# provenance input of two already-committed records
# (`die-area-baseline/20260922-012402-420c370`,
# `sta-corner-sweep/20260922-012909-420c370`), so editing it invalidates their
# content hashes and `verification/check_records.py` correctly demands those
# records be re-minted -- i.e. a fresh multi-corner `klt sta` sweep and two
# `klt place-and-route` runs, which is not this issue's scope. Tracked as an
# open item in `spec/decision-records/0005-program-memory-implementation.md`.
REQUIRED_KLT_COMMANDS = ("pdk", "stats", "layers")


def klt_bin() -> str:
    binary = os.environ.get("KLT_BIN") or shutil.which("klt")
    if not binary:
        die("`klt` not found on PATH and KLT_BIN is unset (see docs/environment.md)")
    return binary


def assert_klt_commands() -> None:
    help_text = subprocess.run(
        [klt_bin(), "--help"], capture_output=True, text=True
    ).stdout
    for verb in REQUIRED_KLT_COMMANDS:
        if not re.search(rf"^\s+{re.escape(verb)}\b", help_text, re.M):
            die(
                f"`{klt_bin()} --help` does not list '{verb}' -- this install lacks a "
                "verb this runner needs (layout/toolchain.json's "
                "klt_required_commands contract)"
            )


def run_klt(args: list[str]) -> dict:
    cmd = [klt_bin(), *args, "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"`{' '.join(cmd)}` failed ({proc.returncode}):\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - tool contract break
        die(f"`{' '.join(cmd)}` did not emit JSON: {exc}")
    return {}  # unreachable; keeps type checkers quiet


def lef_size(lef_path: Path) -> tuple[float, float]:
    """Return (width_um, height_um) from a LEF MACRO's SIZE statement."""
    text = lef_path.read_text(errors="replace")
    match = re.search(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", text, re.M)
    if not match:
        die(f"no SIZE statement found in {lef_path}")
    return float(match.group(1)), float(match.group(2))


def lef_site_size(lef_path: Path) -> tuple[float, float]:
    """Return the standard-cell SITE (width_um, height_um)."""
    text = lef_path.read_text(errors="replace")
    match = re.search(
        r"^SITE\s+\S+.*?SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", text, re.M | re.S
    )
    if not match:
        die(f"no SITE SIZE statement found in {lef_path}")
    return float(match.group(1)), float(match.group(2))


def lyp_layer_map(lyp_path: Path) -> dict[str, tuple[int, int]]:
    """Resolve layer *names* to (layer, datatype), as precheck.load_layers does."""
    text = lyp_path.read_text(errors="replace")
    mapping: dict[str, tuple[int, int]] = {}
    for block in re.findall(r"<properties>(.*?)</properties>", text, re.S):
        source = re.search(r"<source>([^<]+)</source>", block)
        name = re.search(r"<name>([^<]*)</name>", block)
        if not (source and name):
            continue
        spec = source.group(1).split("@")[0].strip()
        if "/" not in spec:
            continue
        layer, _, datatype = spec.partition("/")
        try:
            mapping[name.group(1)] = (int(layer), int(datatype))
        except ValueError:
            continue
    return mapping


def describe_sram_lib(libs_ref: Path) -> dict:
    entry = libs_ref / SRAM_LIB
    info: dict = {
        "path": str(entry),
        "exists": entry.exists(),
        "is_symlink": entry.is_symlink(),
        "symlink_target": os.readlink(entry) if entry.is_symlink() else None,
    }
    if not entry.exists():
        die(
            f"{entry} does not exist -- this PDK install carries no SRAM library, "
            "so the macro option cannot be evaluated against it"
        )
    info["resolved_path"] = str(entry.resolve())
    return info


def tile_geometry(reference: dict) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for tiles, box in reference["tile_sizes"]["die_area"].items():
        llx, lly, urx, ury = box
        out[tiles] = (round(urx - llx, 4), round(ury - lly, 4))
    return out


def core_box(die_w: float, die_h: float, site: tuple[float, float], margins: dict):
    """LibreLane insets the core from the die by MARGIN_MULT * site dimension."""
    sw, sh = site
    return (
        round(die_w - (margins["LEFT_MARGIN_MULT"] + margins["RIGHT_MARGIN_MULT"]) * sw, 4),
        round(die_h - (margins["TOP_MARGIN_MULT"] + margins["BOTTOM_MARGIN_MULT"]) * sh, 4),
    )


def fits(macro_w: float, macro_h: float, core_w: float, core_h: float) -> dict:
    """A hard macro fits a core box in its own orientation or rotated 90 degrees."""
    upright = macro_w <= core_w and macro_h <= core_h
    rotated = macro_h <= core_w and macro_w <= core_h
    return {
        "fits_upright": upright,
        "fits_rotated_r90": rotated,
        "fits": upright or rotated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--macro", default=TARGET_MACRO)
    args = parser.parse_args()

    assert_klt_commands()
    reference = json.loads(REFERENCE_JSON.read_text())

    pdk = run_klt(["pdk", "find", "--pdk", PDK_NAME])
    pdk_root = Path(pdk["root"]) / pdk["variant"]
    libs_ref = Path(pdk["assets"]["libs_ref"])

    sram_lib = describe_sram_lib(libs_ref)
    sram_dir = Path(sram_lib["resolved_path"])

    # (2) the single-port macro family, from LEF SIZE.
    family = {}
    for lef in sorted((sram_dir / "lef").glob("RM_IHPSG13_1P_*.lef")):
        w, h = lef_size(lef)
        family[lef.stem] = {
            "lef": str(lef),
            "width_um": w,
            "height_um": h,
            "area_um2": round(w * h, 4),
        }
    if args.macro not in family:
        die(f"{args.macro} not present in {sram_dir/'lef'} (have: {sorted(family)})")
    macro = family[args.macro]

    # (3) drawn geometry + layer inventory, measured by klt.
    gds = sram_dir / "gds" / f"{args.macro}.gds"
    stats = run_klt(["stats", str(gds)])
    layers = run_klt(["layers", str(gds)])
    used = sorted({(entry["layer"], entry["datatype"]) for entry in layers["layers"]})

    # (4) cross-check against the flow-of-record precheck allowlist.
    lyp = Path(pdk["assets"]["klayout"]) / "tech" / f"{PDK_NAME.split('-')[-1]}.lyp"
    if not lyp.exists():
        candidates = sorted((Path(pdk["assets"]["klayout"]) / "tech").glob("*.lyp"))
        if not candidates:
            die(f"no KLayout .lyp layer map under {pdk['assets']['klayout']}/tech")
        lyp = candidates[0]
    name_to_ld = lyp_layer_map(lyp)
    allow_names = reference["precheck_valid_layers"]["layer_names"]
    unresolved = [n for n in allow_names if n not in name_to_ld]
    allowed = {name_to_ld[n] for n in allow_names if n in name_to_ld}
    reverse = {v: k for k, v in name_to_ld.items()}
    excess = [ld for ld in used if ld not in allowed]

    # (5) tile-budget arithmetic against the flow-of-record's DIE_AREA table.
    site = lef_site_size(libs_ref / STDCELL_LIB / "lef" / f"{STDCELL_LIB}.lef")
    margins = reference["librelane_margins"]
    density = margins["PL_TARGET_DENSITY_PCT"] / 100.0
    ff = reference["committed_ff_memory_measurements"]

    tiles_report = {}
    for tiles, (die_w, die_h) in sorted(tile_geometry(reference).items()):
        core_w, core_h = core_box(die_w, die_h, site, margins)
        core_area = round(core_w * core_h, 4)
        entry = {
            "die_um": [die_w, die_h],
            "die_area_um2": round(die_w * die_h, 4),
            "core_um": [core_w, core_h],
            "core_area_um2": core_area,
            "sram_macro": {
                **fits(macro["width_um"], macro["height_um"], core_w, core_h),
                "macro_fraction_of_core_area_pct": round(
                    100.0 * macro["area_um2"] / core_area, 2
                )
                if core_area > 0
                else None,
            },
            "ff_memory_cell_area_vs_core": {},
        }
        for flow_key, meas in ff.items():
            if flow_key.startswith("_"):
                continue
            cell_area = meas["cell_area_um2"]
            entry["ff_memory_cell_area_vs_core"][flow_key] = {
                "cell_area_um2": cell_area,
                "required_core_area_at_target_density_um2": round(cell_area / density, 4),
                "implied_core_density_pct": round(100.0 * cell_area / core_area, 2)
                if core_area > 0
                else None,
                "fits_at_target_density": cell_area / density <= core_area,
            }
        tiles_report[tiles] = entry

    result = {
        "schema_version": 1,
        "question": (
            "Is there an SRAM macro for ihp-sg13cmos5l that implements DR 0001's "
            "ratified 256x16 program memory, and does it fit a legal Tiny Tapeout "
            "CMOS5L tile allocation?"
        ),
        "what_this_run_does_not_claim": [
            "No synthesis, place-and-route, STA, DRC or LVS was run.",
            "No utilization, timing-closure or routability result is claimed.",
            "Macro fit is a geometric/area feasibility check, not an implementation.",
        ],
        "pdk": {
            "name": pdk["variant"],
            "root": str(pdk_root),
            "version": pdk.get("version"),
            "resolved_via": pdk.get("resolved_via"),
        },
        "sram_library": sram_lib,
        "macro_family_1p": family,
        "selected_macro": {
            "name": args.macro,
            **macro,
            "drawn_bbox_um": stats.get("bbox_um"),
            "layer_inventory": [
                {"layer": l, "datatype": d, "name": reverse.get((l, d))} for l, d in used
            ],
        },
        "tt_precheck_layer_check": {
            "allowlist_source": reference["precheck_valid_layers"]["vendored"],
            "layer_names_unresolved_in_pdk_lyp": unresolved,
            "lyp_used": str(lyp),
            "layers_used": len(used),
            "layers_not_allowed": [
                {"layer": l, "datatype": d, "name": reverse.get((l, d))} for l, d in excess
            ],
            "verdict": "pass" if not excess else "fail",
        },
        "site_um": {"width": site[0], "height": site[1]},
        "tile_budget": {
            "die_area_source": reference["tile_sizes"]["vendored"],
            "ratified_budget_tiles": RATIFIED_BUDGET_TILES,
            "competition_max_tiles": COMPETITION_MAX_TILES,
            "per_tiles": tiles_report,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")

    verdict = result["tt_precheck_layer_check"]["verdict"]
    budget = tiles_report[RATIFIED_BUDGET_TILES]
    print(f"PDK:            {result['pdk']['name']} at {result['pdk']['root']}")
    print(
        f"SRAM library:   {sram_lib['path']}"
        + (f" -> {sram_lib['symlink_target']}" if sram_lib["is_symlink"] else "")
    )
    print(
        f"Macro:          {args.macro}  "
        f"{macro['width_um']} x {macro['height_um']} um = {macro['area_um2']} um^2"
    )
    print(f"Precheck layers: {verdict} ({len(used)} layer/datatype pairs checked)")
    print(
        f"Ratified {RATIFIED_BUDGET_TILES} core: {budget['core_um'][0]} x "
        f"{budget['core_um'][1]} um = {budget['core_area_um2']} um^2; macro uses "
        f"{budget['sram_macro']['macro_fraction_of_core_area_pct']}% of it "
        f"(fits={budget['sram_macro']['fits']})"
    )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
