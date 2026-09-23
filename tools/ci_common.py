"""The helpers every consolidated contract shares.

They were defined once per contract script before the merge - fifteen copies of `read`, four
different `require`s under one name - so they live here now, and a merged script imports them.
A contract may still define its own: `ci-metal3.py` carries the frame probe's text-taking
`require` beside this file's path-taking one, and each shadows the other where it is used.

The name is spelled with an underscore on purpose. `ci-repo.py`'s contract-runner guard globs
`tools/ci-*.py` and refuses any of those that `ci.yml` does not name, and this file asserts
nothing - it is what the contracts assert through - so it must not be caught by that glob.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def source_tree(rel: str = "src/main/java/com/metallum") -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / rel).rglob("*.java"))


def require(label: str, rel: str, needles: tuple[str, ...] | list[str]) -> None:
    text = read(rel)
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise SystemExit(f"{label}: missing " + ", ".join(missing))


def forbid(label: str, text: str, needles: tuple[str, ...] | list[str], *, lower: bool = False) -> None:
    haystack = text.lower() if lower else text
    leaked = []
    for needle in needles:
        probe = needle.lower() if lower else needle
        if probe in haystack:
            leaked.append(needle)
    if leaked:
        raise SystemExit(f"{label}: forbidden semantic leakage: " + ", ".join(leaked))


def check_launcher(rel: str, required: tuple[str, ...] | list[str], *, forbidden=(), regex=()) -> None:
    path = ROOT / rel
    subprocess.run(["bash", "-n", str(path)], check=True)
    text = path.read_text(encoding="utf-8")
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise SystemExit(f"{rel}: missing launcher contract: " + ", ".join(missing))
    present = [needle for needle in forbidden if needle in text]
    if present:
        raise SystemExit(f"{rel}: forbidden launcher contract returned: " + ", ".join(present))
    for pattern in regex:
        if re.search(pattern, text, re.MULTILINE) is None:
            raise SystemExit(f"{rel}: missing launcher regex: {pattern}")



