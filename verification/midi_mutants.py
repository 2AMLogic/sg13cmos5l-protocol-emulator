"""Run the MIDI bench on the golden images and a TX with a 1,700-cycle start bit."""

import subprocess
import sys

from _mutant_runner import run

ASM = "firmware/asm/midi_tx.asm"


def rebuild(tree):
    result = subprocess.run(
        [sys.executable, "firmware/tools/asm.py", ASM],
        cwd=tree,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


if __name__ == "__main__":
    sys.exit(
        run(
            __doc__,
            sys.argv[1:],
            bench="verification/test_firmware_midi.py",
            request="verification/request-firmware-midi.json",
            file=ASM,
            mutants=[
                (
                    "slow-start-bit",
                    "100 extra cycles on the start bit of each TX frame",
                    [
                        (
                            "WAIT  47            ; 48 cycles",
                            "WAIT  147           ; 148 cycles",
                            1,
                        )
                    ],
                    {"test_midi_tx"},
                )
            ],
            rebuild=rebuild,
            result_message="golden MIDI images pass and the TX timing mutant is caught",
        )
    )
