#!/usr/bin/env python3
"""Freshness check over every committed firmware program (issue #103).

Runs, without rewriting any artifact:
  1. gen_i2c_sr.py --check   (generated .asm still matches its generator)
  2. asm.py <each firmware/asm/*.asm> --check   (hex + cycle report match)
  3. asm.py <each firmware/asm/boot/*.asm> --out-dir firmware/build/boot
     --check   (the boot ROM image matches its source; issue #138)
  4. gen_boot_rom.py --check   (rtl/protocol_boot_rom.v matches that image)

Steps 3 and 4 are the two links of DR 0013 layer 2's chain, source -> hex
-> generated Verilog: a boot ROM that no longer matches the committed boot
program fails here, at whichever link went stale.

Assembly inputs are discovered (sorted globs), so a newly committed
program is covered with no list to edit. Every check runs even after a
failure; exit 1 if any failed, 0 if all passed. Stdlib only.

    python3 firmware/tools/check_firmware.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "firmware" / "tools"
BOOT_BUILD = ROOT / "firmware" / "build" / "boot"


def main() -> int:
    asms = sorted((ROOT / "firmware" / "asm").glob("*.asm"))
    boot_asms = sorted((ROOT / "firmware" / "asm" / "boot").glob("*.asm"))
    if not asms:
        print("check_firmware: no firmware/asm/*.asm found", file=sys.stderr)
        return 1
    if not boot_asms:
        print("check_firmware: no firmware/asm/boot/*.asm found", file=sys.stderr)
        return 1
    cmds = [[sys.executable, str(TOOLS / "gen_i2c_sr.py"), "--check"]]
    cmds += [[sys.executable, str(TOOLS / "asm.py"), str(a), "--check"] for a in asms]
    cmds += [[sys.executable, str(TOOLS / "asm.py"), str(a),
              "--out-dir", str(BOOT_BUILD), "--check"] for a in boot_asms]
    cmds += [[sys.executable, str(TOOLS / "gen_boot_rom.py"), "--check"]]
    failed = 0
    for cmd in cmds:
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            print(f"FAIL (exit {rc}): {' '.join(Path(c).name for c in cmd)}")
            failed += 1
    print(f"check_firmware: {len(asms)} assembly inputs, "
          f"{len(boot_asms)} boot assembly input(s), 1 generated ROM, "
          f"{failed} failing check(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
