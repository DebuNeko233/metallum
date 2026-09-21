#!/usr/bin/env python3
"""The contract for the long-term plan's summary page.

`docs/long-term-performance-summary.md` is the one page a reader gets the whole programme from: each track's
decision, the number that decided it, the success criteria audited, and what is left open. Its value is that every
figure on it is the figure the track document owns - and its risk is exactly the same thing. A summary is copied
prose: change 9.8 per cent to 8.9 in `docs/vitrail-gpu-performance.md` and the summary goes on saying 9.8, in the
one document most likely to be read alone.

So the figures below are checked BOTH ways - stated on the summary page, and present in the document the summary
names beside them - and the pair is what makes the check meaningful. A figure that drifts out of its track document
is a summary that is wrong; a figure that leaves the summary is a reader who no longer sees it.

The comparison is on the figure and not on the phrasing: the summary writes "per cent" where a track document
writes "%", and rounds where the document does not, so each entry carries both spellings. Adding a claim to the
summary does not need an entry here; changing one that is here does.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "docs/long-term-performance-summary.md"

# label, as the summary states it, as the owning document states it, the document
CLAIMS = (
    ("A1's redundant share", "0.1-0.3 per cent", "0.1-0.3 %", "metal3-performance-round2.md"),
    ("A1's bind calls", "226 to\n831 bind operations", "830.7", "metal3-performance-round2.md"),
    ("A1's indirect draws", "2425-3759", "2425", "metal3-performance-round2.md"),
    ("B1's allocation", "71-183 KiB", "71.3 KiB", "vitrail-cpu-performance.md"),
    ("D1's seam", "0.066-0.70 per cent", "0.066", "bridge-overhead.md"),
    ("D1's resolution caching", "2 lookups since launch", "2 lookups since launch", "bridge-overhead.md"),
    ("E2's gain on the lightest pack", "1.19x", "1.19x", "metalfx-performance.md"),
    ("F3's cold build", "187 units", "187", "startup-and-cache.md"),
    ("F4's Metal calls", "874 calls", "874", "startup-and-cache.md"),
    ("F4's worst compile", "10.87", "10.87", "startup-and-cache.md"),
    ("C2's shipped reuse", "9.8 per cent", "9.8 per cent", "vitrail-gpu-performance.md"),
    ("C2's interval on the second pack", "3.0 per cent", "3.0 per cent", "vitrail-gpu-performance.md"),
    ("C3's scaled size", "1056x660", "1056x660", "vitrail-gpu-performance.md"),
    ("C4's elided bytes", "17.6 MiB", "17.6 MiB", "vitrail-gpu-performance.md"),
    ("C7's traffic fall", "38.1 per cent", "38.1 per cent", "vitrail-gpu-performance.md"),
    ("G3's readback stall", "273 ms inside", "273", "performance-testing.md"),
)

# The one line the page is for: the success criteria, and the one that is not met.
CRITERIA = (
    "1.  Metal 3 has no visible regression          MET",
    "5.  A batch of low-risk CPU optimisations      NOT MET",
    "11. Metal 4 stays compilable and runnable      MET",
)


def main() -> int:
    if not SUMMARY.is_file():
        raise SystemExit("the summary page is missing: the programme has no single page stating what it proved")

    summary = SUMMARY.read_text(encoding="utf-8")
    for label, stated, _owned, _source in CLAIMS:
        if stated not in summary:
            raise SystemExit(f"the summary no longer states {label} ({stated!r}), so a reader loses the number "
                             f"that decided its track")

    for label, _stated, owned, source in CLAIMS:
        document = ROOT / "docs" / source
        if not document.is_file():
            raise SystemExit(f"the summary names {source}, which is not in docs/")
        if owned not in document.read_text(encoding="utf-8"):
            raise SystemExit(f"the summary states {label} from {source} and {source} no longer carries "
                             f"{owned!r} - the summary is now the only place that number exists")

    for line in CRITERIA:
        if line not in summary:
            raise SystemExit(f"the summary's criteria audit no longer carries {line!r}")

    # `NOT MET` contains `MET`, so a plain count reads eleven criteria met out of eleven and would not notice
    # the one that is not - which is the line a reader most needs to be true.
    met = len(re.findall(r"(?<!NOT )\bMET\b", summary))
    if met != 10:
        raise SystemExit(f"the summary's criteria audit marks {met} criteria MET, and section 61 has eleven of "
                         f"which exactly one is not")
    if "E4, dynamic resolution, is not started" not in summary:
        raise SystemExit("the summary no longer states that E4 has not been started, which is what an owner "
                         "reading it needs to know")
    if "the shadow map's default" not in summary:
        raise SystemExit("the summary no longer names the open decision about the shadow map's default")

    print(f"long-term summary contract: PASS ({len(CLAIMS)} figures traced both ways, {met} criteria marked MET)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
