#!/usr/bin/env python3
"""Self-test for `scripts/check_evidence_inventories.py` (issue #83).

Builds a small throwaway tree (a manifest, an inventory with one directive of
each kind, its envelope, one recorded experiment), confirms the REAL shipped
checker passes on it, then applies one mutation per case and asserts the
checker fails naming the right thing. Nothing is monkeypatched: the checker
runs as a subprocess with `--repo-root`.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/test_check_evidence_inventories.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "check_evidence_inventories.py"
MANIFEST = "manifests/sg13cmos5l-protocol-emulator.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def bind(root: Path, item: int, inv_rel: str, env_name: str) -> None:
    """(Re)write the envelope for `inv_rel` and the manifest pin to match."""
    h = "sha256:" + sha((root / inv_rel).read_bytes())
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "t1_item": item,
        "provenance": {"input": {"path": Path(inv_rel).name, "content_hash": h}},
    }
    write(root, f"manifests/evidence/{env_name}", json.dumps(env))
    mpath = root / MANIFEST
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"evidence": {}}
    manifest["evidence"][str(item)] = {"file": f"manifests/evidence/{env_name}", "content_hash": h}
    write(root, MANIFEST, json.dumps(manifest))


def build(root: Path) -> None:
    write(root, "rtl/core.v", "module core; endmodule\n")
    os.symlink("../rtl/core.v", root / "src_core.v")
    write(root, "README.md", "# block\n\n## License\n")
    write(root, "verification/records/demo/records/.keep", "")
    inv = (
        "# design sources\n"
        f"sha256:{sha(b'module core; endmodule' + chr(10).encode())}  rtl/core.v\n"
        "link  src_core.v -> ../rtl/core.v\n"
        "file  README.md\n"
        "heading  README.md :: ## License\n"
        "experiment  demo  (bench: a prose tail is allowed)\n"
    )
    write(root, "manifests/evidence/testbenches.txt", inv)
    bind(root, 9, "manifests/evidence/testbenches.txt", "testbenches.json")


def run(root: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECKER), "--repo-root", str(root)],
        capture_output=True, text=True,
    )
    return p.returncode, p.stdout + p.stderr


def case(name, mutate, expect_rc, expect_text) -> bool:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        build(root)
        mutate(root)
        rc, out = run(root)
    ok = rc == expect_rc and expect_text in out
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n  rc={rc}\n{out}"))
    return ok


def edit_inventory(root: Path) -> None:
    p = root / "manifests/evidence/testbenches.txt"
    p.write_text(p.read_text() + "# an added prose line\n")


def edit_and_rebind(root: Path) -> None:
    write(root, "rtl/core.v", "module core2; endmodule\n")
    bind(root, 9, "manifests/evidence/testbenches.txt", "testbenches.json")


def native_cite(root: Path) -> None:
    m = json.loads((root / MANIFEST).read_text())
    m["evidence"]["10"] = {"file": "verification/records/demo/drc.json", "content_hash": "sha256:" + "0" * 64}
    write(root, MANIFEST, json.dumps(m))


def wrong_item(root: Path) -> None:
    p = root / "manifests/evidence/testbenches.json"
    env = json.loads(p.read_text())
    env["t1_item"] = 10
    p.write_text(json.dumps(env))


CASES = [
    ("clean tree passes", lambda r: None, 0, "PASS"),
    ("listed file edited", lambda r: write(r, "rtl/core.v", "module core2; endmodule\n"), 1, "`rtl/core.v` changed"),
    ("source edit not cured by re-binding the envelope alone", edit_and_rebind, 1, "`rtl/core.v` changed"),
    ("listed file removed", lambda r: (r / "README.md").unlink(), 1, "`README.md` is not a file"),
    ("symlink retargeted", lambda r: ((r / "src_core.v").unlink(), os.symlink("../x.v", r / "src_core.v")), 1, "points at `../x.v`"),
    ("heading dropped", lambda r: write(r, "README.md", "# block\n"), 1, "no longer has the line `## License`"),
    ("new experiment without a bench line", lambda r: write(r, "verification/records/new/records/.keep", ""), 1, "no `experiment new` line"),
    ("inventory edited, envelope not refreshed", edit_inventory, 1, "no longer hashes to the envelope's content_hash"),
    ("item cited through a native envelope", native_cite, 1, "item 10 is cited, but not through a valid envelope"),
    ("envelope declares another item", wrong_item, 1, "does not cite this envelope for item 10"),
]


def main() -> int:
    results = [case(*c) for c in CASES]
    print(f"{sum(results)}/{len(results)} cases as specified")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
