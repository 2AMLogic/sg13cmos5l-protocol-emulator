#!/usr/bin/env python3
"""Direct-Yosys synthesis runner -- the `klt synthesize` workaround for the
IHP SG13 liberty-naming gap (filed at
`2AMLogic/klayout-tools#1786 <https://github.com/2AMLogic/klayout-tools/issues/1786>`_).

`klt synthesize`'s liberty resolver hardcodes a SkyWater-style
`<cell_library>__<corner>.lib` filename (double underscore between the
cell-library name and the corner) -- see
`klayout_tools.synthesize._resolve_liberty`. IHP's SG13 PDKs ship a single
underscore instead (`sg13cmos5l_stdcell_typ_1p20V_25C.lib`), so `klt
synthesize` cannot resolve *any* corner for `sg13cmos5l_stdcell` today, no
matter what `flow/synthesize-protocol-emulator.json` names in
`pdk.corner`. This script is a stopgap that reads the identical
`klt.synthesize.request/1` request document `klt synthesize` would (so it
can be retired the moment the upstream gap is fixed, by pointing back at
`klt synthesize` with zero request-file changes) and drives Yosys directly
with the same read_verilog -> hierarchy -> synth -> dfflibmap -> abc
-liberty -> clean -> stat pass sequence `klt synthesize`'s own docstring
describes, resolving the liberty path with IHP's actual (single-underscore)
naming convention instead.

This is a stopgap, not a preferred pattern -- `klt` is still the driven
entry point for synthesis per CLAUDE.md's "drive engines through klt" rule
once the gap above is fixed upstream.

Usage:
    python3 flow/run_synthesize_direct_yosys.py flow/synthesize-protocol-emulator.json \
        --pdk-root /home/ubuntu/share/pdk --out-dir /tmp/synth-out

Exit codes: 0 on a successful Yosys run (regardless of the design's cell
count), 1 on a request/liberty/Yosys-invocation error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def resolve_liberty(pdk_root: str, cell_library: str, corner: str) -> Path:
    """IHP single-underscore convention: `<lib>/lib/<lib>_<corner>.lib` --
    contrast `klt synthesize`'s hardcoded `<lib>__<corner>.lib` (double
    underscore), which does not exist for this PDK."""
    lib_dir = Path(pdk_root) / "ihp-sg13cmos5l" / "libs.ref" / cell_library / "lib"
    liberty_path = lib_dir / f"{cell_library}_{corner}.lib"
    if not liberty_path.is_file():
        raise SystemExit(
            f"error: liberty not found: {liberty_path} (looked under {lib_dir})"
        )
    return liberty_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", help="path to a klt.synthesize.request/1 JSON file")
    parser.add_argument("--pdk-root", required=True, help="PDK install root (contains ihp-sg13cmos5l/)")
    parser.add_argument("--out-dir", required=True, help="directory to write the netlist/stats/log into")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    request = json.loads(request_path.read_text())
    if request.get("schema") != "klt.synthesize.request/1":
        raise SystemExit(f"error: unexpected schema {request.get('schema')!r}")

    request_dir = request_path.parent
    sources = [str((request_dir / s).resolve()) for s in request["sources"]]
    hdl_toplevel = request["hdl_toplevel"]
    cell_library = request["pdk"]["cell_library"]
    corner = request["pdk"]["corner"]

    liberty_path = resolve_liberty(args.pdk_root, cell_library, corner)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist_path = out_dir / f"{hdl_toplevel}_synth.v"
    stats_path = out_dir / f"{hdl_toplevel}_stats.json"
    script_path = out_dir / f"{hdl_toplevel}_synth.ys"
    log_path = out_dir / f"{hdl_toplevel}_synth.log"

    script_lines = [f"read_verilog {src}" for src in sources]
    script_lines += [
        f"hierarchy -check -top {hdl_toplevel}",
        f"synth -top {hdl_toplevel}",
        f"dfflibmap -liberty {liberty_path}",
        f"abc -liberty {liberty_path}",
        "clean",
        f"tee -q -o {stats_path} stat -liberty {liberty_path} -json -top {hdl_toplevel}",
        f"write_verilog {netlist_path}",
    ]
    script_path.write_text("\n".join(script_lines) + "\n")

    proc = subprocess.run(
        ["yosys", "-Q", "-T", "-s", str(script_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr)
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"error: yosys exited {proc.returncode}; see {log_path}")

    stats = json.loads(stats_path.read_text())
    module_key = next(iter(stats["modules"]))
    num_cells = stats["modules"][module_key]["num_cells"]
    print(f"\ncell count for {hdl_toplevel} ({cell_library} {corner}): {num_cells}")
    print(f"liberty:  {liberty_path}")
    print(f"netlist:  {netlist_path}")
    print(f"stats:    {stats_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
