"""Repository-root discovery shared by the firmware benches.

`klt functional-verification` may run a bench module from a scratch
directory, so the caller's file anchor is searched first, then the cwd.
A root is any ancestor holding both `firmware/tools/asm.py` and
`spec/target-spec.md`.
"""

from pathlib import Path


def find_repo_root(anchor=None) -> Path:
    """Return the repo root, searching `anchor` (the caller's `__file__`,
    or None if unavailable) and then the cwd, each with its ancestors."""
    starts = []
    if anchor is not None:
        starts.append(Path(anchor).resolve().parent)
    starts.append(Path.cwd())
    for start in starts:
        for probe in [start, *start.parents]:
            if (probe / "firmware" / "tools" / "asm.py").exists() and (
                probe / "spec" / "target-spec.md"
            ).exists():
                return probe
    raise RuntimeError(
        "cannot locate the repo root (needed for firmware/ and the "
        "committed build artifacts); run via klt functional-verification "
        "from the repository, or from any directory inside it "
        f"(searched from: {', '.join(str(s) for s in starts)})"
    )
