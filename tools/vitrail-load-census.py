#!/usr/bin/env python3
"""Track F's load census, read out of one session's arms.

The engine prints the numbers this reads; what it adds is the table. Every arm of a session is a fresh
launch of the same build, so a session with `--cold-cache` on its first arm is a reload experiment:
arm one builds, the arms behind it serve, and the difference between them is what the disk caches are
worth. Nothing here measures anything - it reads three lines the engine already writes and the two
timestamps that bound a load:

    Module cache: N units served, M built by the compiler, ... since this launch, X MB in <dir>
    A of B leftover pipelines compiled ahead of their first draw, C ms of background work
    With the families in, flattening the chain's units cost D ms over E of them with F more handed
      back, translating cost G ms over H translator calls with I programs served from the translation
      cache and J translated, and making modules cost K ms over L modules, shaderc and SPIRV-Cross
      together
    [hh:mm:ss] ... This pack's first full frame opened

Usage: vitrail-load-census.py <session output directory>
"""
import datetime
import re
import sys
from pathlib import Path

MODULE = re.compile(r"Module cache: (\d+) units served, (\d+) built by the compiler, "
                    r"(\d+) and (\d+) since this launch, ([\d.]+) MB")
WARM = re.compile(r"(\d+) of (\d+) leftover pipelines compiled ahead of their first draw, (\d+) ms")
CLOCK = re.compile(r"flattening the chain's units cost (\d+) ms over (\d+) of them with (\d+) more handed back, "
                   r"translating cost (\d+) ms over (\d+) translator calls with (\d+) programs served from the "
                   r"translation cache and (\d+) translated, and making modules cost (\d+) ms over (\d+) modules")
STAMP = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]")


def census(out):
    """One row per arm: what the load served, what it built, and how long it took to get a frame."""
    print(f"{'arm':<10} {'lookups':>8} {'built':>6} {'translations':>13} {'expand':>12} "
          f"{'translate':>13} {'modules':>13} {'warmup':>11} {'load':>6}")
    for arm in sorted(p for p in out.iterdir() if p.is_dir()):
        log = arm / "latest.log"
        if not log.is_file():
            continue

        text = " ".join(log.read_text(errors="replace").split())
        module = MODULE.search(text)
        warm = WARM.search(text)
        clock = CLOCK.search(text)
        if not (module or warm or clock):
            continue

        lookups = str(int(module.group(1)) + int(module.group(2))) if module else "-"
        built = module.group(2) if module else "-"
        translations = f"{clock.group(6)}/{clock.group(7)}" if clock else "-"
        expand = f"{clock.group(1)} ms/{clock.group(2)}" if clock else "-"
        translate = f"{clock.group(4)} ms/{clock.group(5)}" if clock else "-"
        modules = f"{clock.group(8)} ms/{clock.group(9)}" if clock else "-"
        warmup = f"{warm.group(1)}/{warm.group(2)} {warm.group(3)} ms" if warm else "-"

        first = last = None
        for line in log.read_text(errors="replace").splitlines():
            found = STAMP.match(line)
            if not found:
                continue
            seconds = int(found.group(1)) * 3600 + int(found.group(2)) * 60 + int(found.group(3))
            if first is None:
                first = seconds
            if "first full frame opened" in line:
                last = seconds
                break

        wall = f"{last - first} s" if first is not None and last is not None else "-"
        print(f"{arm.name:<10} {lookups:>8} {built:>6} {translations:>13} {expand:>12} "
              f"{translate:>13} {modules:>13} {warmup:>11} {wall:>6}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)

    census(Path(sys.argv[1]))
