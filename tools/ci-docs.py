#!/usr/bin/env python3
"""The contract for the documentation's own index.

`docs/README.md` is the router: it says which page owns what, so a reader arriving at the repository can find the
result of the long-term programme instead of `ls`-ing fourteen files. Its value is that it is complete and its risk
is that nothing notices when it stops being - a page added and not listed is a page nobody reads, and a page
renamed out from under a link is a reader who lands on a 404 in the one place they went for directions.

So the index is checked BOTH ways, the same way `ci-summary.py` checks the summary's figures: every document in
`docs/` is named in it, and nothing in it is named that is not there. Every relative link in every document is
resolved as well, because a broken link is the same failure one step further out and nothing else looks for one.

A contract script that no workflow names asserts nothing, which is why `ci.yml` runs this one; `--self-test` proves
the checks can fail rather than trusting that they would, which is what `ci-architecture.py --self-test` is for.
"""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"

# `](path.md)` and `](path.md#anchor)`: an absolute URL carries a scheme and is none of this contract's business.
LINK = re.compile(r"\]\(([^)\s]+?)(?:#[^)\s]*)?\)")


def relative_links(text: str) -> list[str]:
    """Every link in a document that points at a file in this repository."""
    found = []
    for target in LINK.findall(text):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        found.append(target)
    return found


def resolves(source: Path, target: str) -> bool:
    """A link is relative to the document that carries it, or to the repository root when it starts with one."""
    for base in (source.parent, ROOT):
        if (base / target).exists():
            return True
    return False


def check(docs: Path, index: Path) -> list[str]:
    """Every problem with the index, as lines a failure can print."""
    problems: list[str] = []
    if not index.is_file():
        return [f"the documentation index is missing: {index} - the pages have no router"]

    index_text = index.read_text(encoding="utf-8")
    pages = sorted(path for path in docs.glob("*.md") if path != index)

    # Both directions, which is what makes it a check rather than a word count.
    for page in pages:
        if f"({page.name})" not in index_text and f"/{page.name})" not in index_text:
            problems.append(f"{page.name} is in docs/ and is named nowhere in the index, so nothing routes to it")

    for source, text in [(index, index_text)] + [(p, p.read_text(encoding="utf-8")) for p in pages]:
        for target in relative_links(text):
            if not resolves(source, target):
                problems.append(f"{source.name} links to {target}, which does not exist")
    return problems


def self_test() -> int:
    """Prove the two checks fail on a tree that is wrong in exactly those two ways."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        docs = root / "docs"
        docs.mkdir()
        (docs / "listed.md").write_text("# Listed\n", encoding="utf-8")
        (docs / "unlisted.md").write_text("# Unlisted\n", encoding="utf-8")
        index = docs / "README.md"
        index.write_text("# Index\n\n[listed](listed.md)\n[gone](vanished.md)\n", encoding="utf-8")

        problems = check(docs, index)
        # `vanished.md` is a page the index names and does not have; `listed.md` is in the index, so `unlisted.md`
        # is the one that must be reported as unrouted. Anything else means the check is answering another question.
        if len(problems) != 2 or not any("unlisted.md" in one for one in problems) \
                or not any("vanished.md" in one for one in problems):
            for one in problems:
                print(f"  {one}", file=sys.stderr)
            raise SystemExit(f"documentation self-test: the checks found {len(problems)} problems in a tree with "
                             f"exactly two, so one of them is measuring something else")

        # And the good case passes, or a check that fails everything would pass this test too.
        (docs / "unlisted.md").unlink()
        index.write_text("# Index\n\n[listed](listed.md)\n", encoding="utf-8")
        if check(docs, index):
            raise SystemExit(f"documentation self-test: a complete index with a resolving link was refused: "
                             f"{check(docs, index)}")

    print("documentation index self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()

    problems = check(DOCS, INDEX)
    if problems:
        raise SystemExit("documentation index: " + "; ".join(problems))
    pages = len([p for p in DOCS.glob("*.md") if p != INDEX])
    print(f"documentation index: PASS ({pages} pages routed, every link in docs/ resolves)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
