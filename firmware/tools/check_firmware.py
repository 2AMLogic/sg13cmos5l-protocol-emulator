#!/usr/bin/env python3
"""Freshness check over every committed firmware program (issue #103).

Runs, without rewriting any artifact:
  1. gen_i2c_sr.py --check   (generated .asm still matches its generator)
  2. asm.py <each firmware/asm/*.asm> --check   (hex + cycle report match)

Assembly inputs are discovered (sorted glob of firmware/asm/*.asm), so a
newly committed program is covered with no list to edit. Every check runs
even after a failure; exit 1 if any failed, 0 if all passed. Stdlib only.

    python3 firmware/tools/check_firmware.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "firmware" / "tools"


def main() -> int:
    asms = sorted((ROOT / "firmware" / "asm").glob("*.asm"))
    if not asms:
        print("check_firmware: no firmware/asm/*.asm found", file=sys.stderr)
        return 1
    cmds = [[sys.executable, str(TOOLS / "gen_i2c_sr.py"), "--check"]]
    cmds += [[sys.executable, str(TOOLS / "asm.py"), str(a), "--check"] for a in asms]
    failed = 0
    for cmd in cmds:
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            print(f"FAIL (exit {rc}): {' '.join(Path(c).name for c in cmd)}")
            failed += 1
    print(f"check_firmware: {len(asms)} assembly inputs, "
          f"{failed} failing check(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
