#!/usr/bin/env python3
"""Contracts for the repository's own invariants.

This file is the merge of the contract scripts that used to guard this subject separately, so that
the pull-request surface is one script a subject rather than one a rule. Every check below is the
check it was, at the point it was: the merge moved code between files, it did not reword any of it.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_common import ROOT, check_launcher, forbid, read, require, source_tree  # noqa: E402

# Each merged member that used to end in `if __name__ == "__main__": raise SystemExit(main())`
# appends its own status here instead, because a `raise` after the first one would skip the
# rest of the file - and the file is several contracts now.

# Each merged member that used to end in `if __name__ == "__main__": raise SystemExit(main())`
# appends its own status here instead, because a `raise` after the first one would skip the
# rest of the file - and the file is several contracts now.
_MAIN_STATUS: list[int] = []


# ==================== was tools/ci-contracts.py ====================
# ---------------------------------------------------------------------------
# Repository-write guard
#
# CI runs with a token that can write to this repository, and a workflow that commits becomes an
# author on a branch. `.github/workflows/apply-graphics-storage-image-fix.yml` did exactly that: it
# rewrote two source files, committed them and pushed the result back to the branch that triggered
# it, so every later push re-ran it against sources it had already patched. It is deleted, and this
# refuses the shape rather than the file, because the next one would be written the same way.
#
# The guard reads each workflow instead of matching one spelling of the incident. `contents: write`
# is not the only way to hold repository write -- `permissions: write-all` grants it without naming
# contents, and a quoted value or a trailing comment defeats an anchored literal -- and a commit
# does not have to be written `git commit`: `git -c user.email=... commit`, a run of spaces or a `\`
# continuation runs the same command. A guard that knew only the literal spellings would report PASS
# on the very file it exists to refuse.
#
# `release.yml` is the only workflow allowed repository content write, since creating a GitHub
# release needs it; it is pinned to `v*` tags and authors no commit. Every workflow must also state
# its `permissions:` explicitly, so none can inherit a repository default that happens to allow
# writes. The pull-request surface stays exactly `ci.yml`, as `.github/CI_CONSOLIDATION.md` says, so
# acceptance coverage cannot quietly multiply into another check.
# ---------------------------------------------------------------------------
workflow_dir = ROOT / ".github/workflows"
workflows = {path.name: path.read_text(encoding="utf-8") for path in sorted(workflow_dir.glob("*.y*ml"))}
if not workflows:
    raise SystemExit("repository-write guard: no workflow files found under .github/workflows")

# The git options that take a separate value, so that `git -c user.name=x commit` still reaches and
# reports `commit` rather than stopping at the option's value.
GIT_OPTIONS_WITH_VALUES = ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path")
COMMITTING_SUBCOMMANDS = ("commit", "push")
# Any published action that commits, pushes or opens a request on the workflow's own behalf, under
# any owner. Naming two actions would have missed the third.
COMMITTING_ACTION = re.compile(r"(?i)\buses:\s*[^\s#]*(commit|push|create-pull-request|add-and-commit|git-auto)")


def unquote(value: str) -> str:
    """Drop a trailing comment and the quoting a YAML scalar is allowed to carry."""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip().strip("'\"")


def without_comments(text: str) -> str:
    """The live lines of a workflow, with continuations joined.

    Workflow prose explains commands it does not run: `prefix.yml` documents the hazard it detects
    as `git push origin origin/dev:main` in a comment, which is documentation of the gesture rather
    than the gesture. A `\\` continuation splits one command across two lines, so it is joined here
    as well; a line-by-line scan would otherwise see neither half as a command.
    """
    joined = text.replace("\\\n", " ")
    return "\n".join(line for line in joined.splitlines() if not line.lstrip().startswith("#"))


def git_subcommands(line: str) -> list[str]:
    """The git subcommand each `git` invocation on this line actually runs."""
    found = []
    for match in re.finditer(r"\bgit\b", line):
        tokens = line[match.end():].split()
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in GIT_OPTIONS_WITH_VALUES:
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            found.append(token.strip("'\";|&()"))
            break
    return found


def declared_permissions(text: str) -> dict[str, str] | None:
    """The workflow-level `permissions:` mapping, or None when a workflow declares none."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^permissions:", line) is None:
            continue
        inline = unquote(line.split(":", 1)[1])
        if inline:
            if inline in ("{}", "read-all"):
                return {}
            if inline == "write-all":
                # Every scope, contents included, without ever naming `contents`.
                return {"contents": "write"}
            raise SystemExit(f"repository-write guard: unrecognised `permissions: {inline}`")
        granted = {}
        for follower in lines[index + 1:]:
            if follower.strip() and follower[:1] not in (" ", "\t"):
                break
            key, separator, value = follower.strip().partition(":")
            if separator and key.strip():
                granted[key.strip()] = unquote(value)
        return granted
    return None


live = {name: without_comments(text) for name, text in workflows.items()}
permissions = {name: declared_permissions(text) for name, text in workflows.items()}

missing_permissions = sorted(name for name, granted in permissions.items() if granted is None)
if missing_permissions:
    raise SystemExit(
        "repository-write guard: every workflow must declare `permissions:` explicitly so it cannot "
        "inherit a repository default that permits writes; missing in: " + ", ".join(missing_permissions)
    )

for name, body in live.items():
    for line in body.splitlines():
        committed = [subcommand for subcommand in git_subcommands(line) if subcommand in COMMITTING_SUBCOMMANDS]
        if committed:
            raise SystemExit(
                f"{name}: CI must not author commits, found `git {'` and `git '.join(committed)}` in "
                f"`{line.strip()}`. Delete the workflow instead of letting Actions write to a branch."
            )
    action = COMMITTING_ACTION.search(body)
    if action is not None:
        raise SystemExit(
            f"{name}: CI must not author commits, found `{action.group().strip()}`, which commits or "
            "opens a request on this workflow's behalf. Delete it instead."
        )

writers = sorted(name for name, granted in permissions.items() if granted.get("contents") == "write")
if writers != ["release.yml"]:
    raise SystemExit(
        "repository-write guard: repository content write is reserved for release.yml, found: "
        + (", ".join(writers) if writers else "none")
    )

pull_request_surface = sorted(name for name, text in workflows.items() if re.search(r"^\s+pull_request:", text, re.MULTILINE))
if pull_request_surface != ["ci.yml"]:
    raise SystemExit(
        "repository-write guard: `.github/CI_CONSOLIDATION.md` keeps the pull-request surface to ci.yml, found: "
        + (", ".join(pull_request_surface) if pull_request_surface else "none")
    )

print(f"Repository-write guard: PASS ({len(workflows)} workflows, pull-request surface ci.yml, no CI-authored commits)")

# ---------------------------------------------------------------------------
# Contract-runner guard
#
# A contract script that no workflow names is not a contract. `tools/ci-metal3.py`
# was reached only by a one-shot workflow, so deleting that workflow left the script in the tree
# asserting nothing -- still reviewed, still green when run by hand, and enforcing nothing. Every
# `tools/ci-*.py` must be named by the workflow that runs the pull-request contracts.
# ---------------------------------------------------------------------------
ci_workflow = read(".github/workflows/ci.yml")
contract_scripts = sorted(path.name for path in sorted((ROOT / "tools").glob("ci-*.py")))
unnamed_contracts = [name for name in contract_scripts if f"tools/{name}" not in ci_workflow]
if unnamed_contracts:
    raise SystemExit(
        "contract-runner guard: these contract scripts are named by no workflow, so they assert "
        "nothing: " + ", ".join(unnamed_contracts) + ". Name each in ci.yml or delete it."
    )

print(f"Contract-runner guard: PASS ({len(contract_scripts)} contract scripts, all named by ci.yml)")


# ==================== was tools/ci-docs.py ====================
"""The contract for the documentation's own index.

`docs/README.md` is the router: it says which page owns what, so a reader arriving at the repository can find the
result of the long-term programme instead of `ls`-ing fourteen files. Its value is that it is complete and its risk
is that nothing notices when it stops being - a page added and not listed is a page nobody reads, and a page
renamed out from under a link is a reader who lands on a 404 in the one place they went for directions.

So the index is checked BOTH ways, the same way `ci-harness.py` checks the summary's figures: every document in
`docs/` is named in it, and nothing in it is named that is not there. Every relative link in every document is
resolved as well, because a broken link is the same failure one step further out and nothing else looks for one.

A contract script that no workflow names asserts nothing, which is why `ci.yml` runs this one; `--self-test` proves
the checks can fail rather than trusting that they would, which is what `ci-repo.py --self-test` is for.
"""

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


def docs_self_test() -> int:
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


def docs_main() -> int:
    if "--self-test" in sys.argv[1:]:
        return docs_self_test()

    problems = check(DOCS, INDEX)
    if problems:
        raise SystemExit("documentation index: " + "; ".join(problems))
    pages = len([p for p in DOCS.glob("*.md") if p != INDEX])
    print(f"documentation index: PASS ({pages} pages routed, every link in docs/ resolves)")
    return 0



_MAIN_STATUS.append(docs_main())

# ==================== was tools/ci-architecture.py ====================
"""The architecture guard for the Metal 3 / Metal 4 split.

Metallum is being split into a version-neutral core and two execution generations, and the split is only
real if the dependencies point one way. This is the contract that says so: it is a static scan of the
source tree, it runs in CI beside the other `tools/ci-*.py` contracts, and every rule below is one the
final architecture needs rather than one that happens to hold today.

The rules
---------

    com.metallum.render.shared   must not import  render.metal3, render.metal4, mtl.metal3, mtl.metal4
    com.metallum.render.metal3   must not import  render.metal4, mtl.metal4
    com.metallum.render.metal4   must not import  render.metal3, mtl.metal3
    com.metallum.mtl.metal3      must not import  mtl.metal4
    com.metallum.mtl.metal4      must not import  mtl.metal3

and one rule that has to hold in every layout, including the flat one this tree still has:

    no single source file may name both a Metal 3 command type and a Metal 4 command type

That last rule is the reason this guard is worth having before the packages exist. The target packages are
work for later milestones, so on their own the import rules would pass vacuously - but a file that mixes
`MTLCommandBuffer` with `MTL4CommandBuffer` is a file mixing two command APIs, which is exactly what the
split exists to prevent, and there is such a shape to catch in the tree as it stands.

What a rule is allowed to see
-----------------------------

A comment or a javadoc may name anything: `Metal4Path`'s own javadoc says `MTL4CommandBuffer` on purpose,
and the point of a comment is to explain. So every scan reads the file with comments and string literals
removed, which is also what keeps a reflection string like `"metalApiGeneration"` from looking like a type.
"""



ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "src/main/java"

PACKAGE_PREFIX = "com.metallum"

# The layers, and what each of them may not reach. Written as package prefixes because that is what the
# import lines carry: the rule is between packages, not between files.
LAYERS: dict[str, tuple[str, ...]] = {
    # The neutral layer is the newest and the strictest: it is what both generations speak in, so it may not
    # name either generation's command path - not the engine's, not the bindings'. It was added to this table
    # the moment it existed, because a shared layer that quietly imports one generation is the split undone.
    "com.metallum.render.shared": (
        "com.metallum.render.metal3",
        "com.metallum.render.metal4",
        "com.metallum.mtl.metal3",
        "com.metallum.mtl.metal4",
    ),
    "com.metallum.render.metal3": (
        "com.metallum.render.metal4",
        "com.metallum.mtl.metal4",
    ),
    "com.metallum.render.metal4": (
        "com.metallum.render.metal3",
        "com.metallum.mtl.metal3",
    ),
    "com.metallum.mtl.metal3": ("com.metallum.mtl.metal4",),
    "com.metallum.mtl.metal4": ("com.metallum.mtl.metal3",),
}

# The command-generation types. Resources (`MTLTexture`, `MTLBuffer`, `MTLSamplerState`, a pipeline state,
# a fence, a layer, a drawable) are shared by both generations and are deliberately absent from both lists.
METAL3_COMMAND_TYPES = (
    "MTLCommandQueue",
    "MTLCommandBuffer",
    "MTLCommandEncoder",
    "MTLRenderCommandEncoder",
    "MTLComputeCommandEncoder",
    "MTLBlitCommandEncoder",
)

METAL4_COMMAND_TYPES = (
    "MTL4CommandQueue",
    "MTL4CommandBuffer",
    "MTL4CommandAllocator",
    "MTL4CommandEncoder",
    "MTL4RenderCommandEncoder",
    "MTL4ComputeCommandEncoder",
    "MTL4ArgumentTable",
    "MTL4CommitOptions",
    "MTL4CommitFeedback",
)

_COMMENT_AND_LITERAL = re.compile(
    r"//[^\n]*"
    r"|/\*.*?\*/"
    r'|"(?:\\.|[^"\\])*"',
    re.DOTALL,
)


def code_only(source: str) -> str:
    """The file without comments and string literals, so a rule reads only what the compiler reads."""
    stripped = _COMMENT_AND_LITERAL.sub(lambda match: "\n" * match.group(0).count("\n"), source)
    # A javadoc line that named a type would otherwise leave a blank line where the type was, which is fine;
    # what must not survive is the text.
    return stripped


def package_of(source: str) -> str:
    match = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.MULTILINE)
    return "" if match is None else match.group(1)


def imports_of(source: str) -> list[str]:
    return re.findall(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", source, re.MULTILINE)


def mentions(source: str, types: tuple[str, ...]) -> list[str]:
    """Which of these type names the code names, by identifier and not by substring."""
    code = code_only(source)
    return [name for name in types if re.search(rf"\b{re.escape(name)}\b", code)]


def violations(root: Path) -> list[str]:
    """Every rule broken under this source root, as `path: rule: detail` lines."""
    found: list[str] = []
    for path in sorted(root.rglob("*.java")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        package = package_of(source)

        for layer, forbidden in LAYERS.items():
            if package != layer and not package.startswith(layer + "."):
                continue
            for name in imports_of(source):
                for target in forbidden:
                    if name == target or name.startswith(target + "."):
                        found.append(f"{relative}: {layer} imports {name}, which lives in {target}")

        metal3 = mentions(source, METAL3_COMMAND_TYPES)
        metal4 = mentions(source, METAL4_COMMAND_TYPES)
        if metal3 and metal4:
            found.append(
                f"{relative}: one file names both command generations "
                f"({', '.join(metal3)} with {', '.join(metal4)})"
            )

    return found


# ---------------------------------------------------------------------------
# The debt the frame path's isolation still owes, frozen so it can only shrink.
#
# The rule above stops a file naming *both* generations. It cannot say how much of one generation is still
# named from outside its package, and that amount is exactly what "the device stops knowing a concrete
# generation" has to remove. So it is written down here, file by file, and the checker requires the ledger
# and the tree to agree in both directions: a new coupling fails, and removing one without deleting its line
# also fails, because an unmaintained ledger stops being evidence.
#
# A file in a generation package (`render.metal3`, `render.metal4`, `mtl.metal3`, `mtl.metal4`) is where these
# names belong and is not listed. Everything else is.
FRAME_PATH_DEBT: dict[str, tuple[str, ...]] = {
    # The generation factory constructs the Metal 3 frame encoder, which the services used to do. It is debt
    # rather than a delegation because it still lives in the flat package; it moves with the cluster, and this
    # line goes with it.
    # Still called from `render` rather than from a generation package, so it is debt today and becomes one of
    # the delegations above on the day the encoder moves - and this ledger is where that shows up.
    "com/metallum/render/Metal4PresentGate.java": ("Metal4Path",),
}
_GENERATION_PACKAGES = (
    "com.metallum.render.metal3",
    "com.metallum.render.metal4",
    "com.metallum.mtl.metal3",
    "com.metallum.mtl.metal4",
)

_FRAME_PATH_TYPES = METAL3_COMMAND_TYPES + ("MetalCommandEncoder", "MetalRenderPass", "Metal4Path")


# ---------------------------------------------------------------------------
# The bindings-side built-ins, which name a generation's encoder *on purpose*.
#
# The debt rule is textual and cannot tell a coupling somebody has to remove from the one direction that is
# the design: `MTLBuiltinPipelines` and `MTLStorageTexturePipelines` are the neutral home of the built-in
# pipelines - the present pipeline lives there once, drawn by Metal 3 through `MTLCommandBuffer` and by Metal 4
# through `drawPresentWithTable` - and the Metal 3 wrappers call into them from their own convenience methods.
# Wrapper calls neutral is the direction that removes a generation from the engine; the reverse would be the
# debt. Counting them as work pushed towards moving encode bodies into the wrappers, which is what the split
# is against, so they are listed separately and the checker requires the delegation to still be a delegation:
# each class here must be called from inside a generation package.
WRAPPER_DELEGATIONS: dict[str, tuple[str, ...]] = {
    "com/metallum/mtl/MTLBuiltinPipelines.java": ("MTLCommandBuffer", "MTLRenderCommandEncoder"),
}


def undelivered_delegations(root: Path) -> list[str]:
    """The pinned delegations whose neutral class nothing in a generation package calls."""
    missing = []
    for relative in WRAPPER_DELEGATIONS:
        name = Path(relative).stem
        called = False
        for path in root.rglob("*.java"):
            source = path.read_text(encoding="utf-8")
            package = package_of(source)
            if not any(package == gen or package.startswith(gen + ".") for gen in _GENERATION_PACKAGES):
                continue
            if f"{name}." in source:
                called = True
                break
        if not called:
            missing.append(relative)
    return missing


# ---------------------------------------------------------------------------
# The flat surface's reach into a generation package, frozen the same way.
#
# The rule above the ledger stops one file naming *both* generations, and the debt ledger counts the names of
# the frame path's concrete classes. Neither says anything about the direction this phase is built around:
# `com.metallum.render.*` and `com.metallum.mtl.*` are the surface a pack-facing engine is allowed to know, so
# a class there that reaches into `render.metal3`, `render.metal4`, `mtl.metal3` or `mtl.metal4` has put a
# generation back on that surface - the thing the split exists to prevent, and the one shape no rule here could
# see. A flat bridge that routes through `render.shared.MetalFrameComputeCommands` is the design; one that
# imports `render.metal3.Metal3ComputeBridge` is the fault, and it would have passed every other check.
#
# Writing the crossings down is what makes the goal measurable: the count below is the work left, it can only
# go down, and the checker requires the ledger and the tree to agree in both directions. Each line says which
# kind of crossing it is - the composition root that has to name a provider, the device's capability probe,
# the Metal 4 skeleton the earlier milestones left, and the one that is simply work.
#
# A file in `WRAPPER_DELEGATIONS` is not listed here even when it names a generation package: that ledger
# already counts it, in the direction the design allows, and two ledgers would count one coupling twice.
GENERATION_REACH: dict[str, tuple[str, ...]] = {
    # The composition root. Choosing a generation means naming one; this is the seam the choice is made at,
    # and it is the only place a provider is constructed. Two names since the Metal 4 provider skeleton
    # landed: the switch reads the EXECUTING generation, so both cases have to be written here, and this
    # ledger is what makes that growth a decision with a count rather than a drift. The neutral interface is
    # still the only type either arm is used as.
    "com/metallum/render/execution/MetalExecutionServices.java": (
        "com.metallum.render.metal3.Metal3ExecutionProvider",
        "com.metallum.render.metal4.Metal4ExecutionProvider",
    ),
    # The device's own capability question, which is what the selector asks before a generation is chosen. The
    # MetalFX clause joined the probe when the Metal 4 scaler landed: the record has to ask whether THIS
    # generation can scale, and the answer is the Metal 4 path's own functional question - the Metal 3 answer is
    # a different class, a different factory and a different encode (section 80). One more name on a line that
    # already crossed is the honest way to record it: the alternative was to leave the record asking a
    # `respondsTo` and report a scaler that does not exist as one that does.
    "com/metallum/render/execution/MetalDeviceCapabilities.java": (
        "com.metallum.mtl.metal4.MTL4Probe",
        "com.metallum.mtl.metal4.Metal4Fx",
    ),
    # The Metal 4 skeleton the earlier milestones left in place: the capability advertisement, its probe at
    # device creation, and the present path behind its developer switch.
    "com/metallum/render/Metal4.java": ("com.metallum.mtl.metal4.MTL4Probe",),
    "com/metallum/render/MetalFx.java": ("com.metallum.mtl.metal4.MTL4Probe",),
    "com/metallum/render/Metal4Path.java": (
        "com.metallum.mtl.metal4.MTL4ArgumentTable",
        "com.metallum.mtl.metal4.MTL4CommitOptions",
        "com.metallum.mtl.metal4.MTL4Probe",
    ),
    # The bindings library asking the same capability question of the same device.
    "com/metallum/mtl/MTLBuffer.java": ("com.metallum.mtl.metal4.MTL4Probe",),
    # Work: a flat facade reaching a Metal 3 class for a pipeline the neutral layer should own, in the shape
    # `MTLBuiltinPipelines` already has. The line is here so the crossing is a decision with a number rather
    # than a habit nobody has looked at.
    "com/metallum/render/MetalDevice.java": ("com.metallum.mtl.metal3.MTLStorageTexturePipelines",),
}

_GENERATION_NAME = re.compile(
    r"\b(com\.metallum\.(?:render|mtl)\.(?:metal3|metal4)\.[A-Za-z0-9_]+)"
)


def generation_reach(root: Path) -> dict[str, tuple[str, ...]]:
    """Which files outside the generation packages name a class inside one, by import or by use."""
    reach: dict[str, tuple[str, ...]] = {}
    for path in sorted(root.rglob("*.java")):
        source = path.read_text(encoding="utf-8")
        package = package_of(source)
        if any(package == gen or package.startswith(gen + ".") for gen in _GENERATION_PACKAGES):
            continue
        relative = str(path.relative_to(root))
        if relative in WRAPPER_DELEGATIONS:
            continue
        named = tuple(sorted(set(_GENERATION_NAME.findall(code_only(source)))))
        if named:
            reach[relative] = named
    return reach


def frame_path_debt(root: Path) -> dict[str, tuple[str, ...]]:
    """Which files outside the generation packages still name the frame path's concrete generations."""
    debt: dict[str, tuple[str, ...]] = {}
    for path in sorted(root.rglob("*.java")):
        source = path.read_text(encoding="utf-8")
        package = package_of(source)
        if any(package == gen or package.startswith(gen + ".") for gen in _GENERATION_PACKAGES):
            continue
        # A file naming its own class is not a coupling: `MetalRenderPass` declaring `MetalRenderPass` says
        # nothing about which generation the frame path reaches for, and counting it would make the number
        # larger than the work without making the work smaller.
        own_name = path.stem
        named = tuple(sorted(set(mentions(source, _FRAME_PATH_TYPES)) - {own_name}))
        if named:
            debt[str(path.relative_to(root))] = named
    return debt


def architecture_self_test() -> None:
    """Prove every rule fires, because a guard that cannot fail is a guard that is not there.

    Each case below is a synthetic source written into a temporary tree and scanned by the same code the
    real tree goes through, so what is being tested is the rule and not a copy of it.
    """
    import tempfile

    cases = [
        (
            "a version-neutral core that reaches into Metal 3",
            "com/metallum/render/shared/MetalFrameStats.java",
            "package com.metallum.render.shared;\nimport com.metallum.render.metal3.Metal3FrameSubmission;\n"
            "public final class MetalFrameStats {}\n",
        ),
        (
            "a version-neutral core that reaches into Metal 4",
            "com/metallum/render/shared/MetalPassPlan.java",
            "package com.metallum.render.shared;\nimport com.metallum.mtl.metal4.MTL4ArgumentTable;\n"
            "public final class MetalPassPlan {}\n",
        ),
        (
            "Metal 3 reaching into Metal 4",
            "com/metallum/render/metal3/Metal3Execution.java",
            "package com.metallum.render.metal3;\nimport com.metallum.mtl.metal4.MTL4CommandQueue;\n"
            "public final class Metal3Execution {}\n",
        ),
        (
            "Metal 4 reaching into Metal 3",
            "com/metallum/ml4/Metal4Execution.java",
            "package com.metallum.render.metal4;\nimport com.metallum.mtl.metal3.MTLCommandBuffer;\n"
            "public final class Metal4Execution {}\n",
        ),
        (
            "one file naming both command generations",
            "com/metallum/render/Mixed.java",
            "package com.metallum.render;\n"
            "public final class Mixed {\n"
            "    private MTLCommandBuffer metal3;\n"
            "    private MTL4CommandBuffer metal4;\n"
            "}\n",
        ),
    ]

    failures = []
    with tempfile.TemporaryDirectory() as directory:
        for index, (name, relative, source) in enumerate(cases):
            root = Path(directory) / f"case{index}"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            if not violations(root):
                failures.append(name)

    # And the other direction: a file that names a shape both generations may use, and a comment that names
    # a command type without using one, must pass. A guard that fails on those would be turned off.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clean = root / "com/metallum/render/shared/MetalGpuTexture.java"
        clean.parent.mkdir(parents=True, exist_ok=True)
        clean.write_text(
            "package com.metallum.render.shared;\n"
            "import com.metallum.mtl.MTLTexture;\n"
            "/** Built from an MTL4CommandBuffer on the new path and an MTLCommandBuffer on the old one. */\n"
            'public final class MetalGpuTexture {\n    private MTLTexture texture;\n}\n',
            encoding="utf-8",
        )
        stray = violations(root)
        if stray:
            failures.append(f"a compliant file was reported: {stray[0]}")

    # And the debt rule fires in both directions: a new coupling, and a ledger line for a coupling that is
    # gone. Without this the ledger could silently stop being compared.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        newcomer = root / "com/metallum/render/MetalNewcomer.java"
        newcomer.parent.mkdir(parents=True, exist_ok=True)
        newcomer.write_text(
            "package com.metallum.render;\npublic final class MetalNewcomer { MTLCommandBuffer b; }\n",
            encoding="utf-8",
        )
        if "com/metallum/render/MetalNewcomer.java" not in frame_path_debt(root):
            failures.append("a new coupling to the frame path's generation was not recorded as debt")
        stale = root / "com/metallum/render/MetalSettled.java"
        stale.write_text(
            "package com.metallum.render;\npublic final class MetalSettled { int free; }\n",
            encoding="utf-8",
        )
        global FRAME_PATH_DEBT
        kept = FRAME_PATH_DEBT
        FRAME_PATH_DEBT = {"com/metallum/render/MetalSettled.java": ("MTLCommandBuffer",)}
        try:
            ledger_found = []
            debt = frame_path_debt(root)
            for path in sorted(set(debt) | set(FRAME_PATH_DEBT)):
                if debt.get(path) != FRAME_PATH_DEBT.get(path):
                    ledger_found.append(path)
            if "com/metallum/render/MetalSettled.java" not in ledger_found:
                failures.append("a ledger line for a coupling that is gone was not reported")
        finally:
            FRAME_PATH_DEBT = kept

    # And the flat surface's reach into a generation package, in both directions: a facade that starts
    # reaching one is reported, and a ledger line for a reach that is gone is reported too.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        facade = root / "com/metallum/render/MetalFrameBridge.java"
        facade.parent.mkdir(parents=True, exist_ok=True)
        facade.write_text(
            "package com.metallum.render;\nimport com.metallum.render.metal3.Metal3ComputeBridge;\n"
            "public final class MetalFrameBridge { Metal3ComputeBridge bridge; }\n",
            encoding="utf-8",
        )
        if "com/metallum/render/MetalFrameBridge.java" not in generation_reach(root):
            failures.append("a flat facade reaching a generation package was not recorded as reach")

        settled = root / "com/metallum/render/MetalSettledReach.java"
        settled.write_text(
            "package com.metallum.render;\npublic final class MetalSettledReach { int free; }\n",
            encoding="utf-8",
        )
        global GENERATION_REACH
        kept_reach = GENERATION_REACH
        GENERATION_REACH = {
            "com/metallum/render/MetalSettledReach.java": ("com.metallum.render.metal3.Metal3ComputeBridge",)
        }
        try:
            reach = generation_reach(root)
            reach_found = [
                path
                for path in sorted(set(reach) | set(GENERATION_REACH))
                if reach.get(path) != GENERATION_REACH.get(path)
            ]
            if "com/metallum/render/MetalSettledReach.java" not in reach_found:
                failures.append("a ledger line for a generation reach that is gone was not reported")
        finally:
            GENERATION_REACH = kept_reach

    if failures:
        raise SystemExit("architecture guard self-test failed: " + "; ".join(failures))

    print(
        f"architecture guard self-test: PASS ({len(cases)} rules fire, a compliant file passes, "
        "both ledgers fire in both directions)"
    )


def architecture_main() -> int:
    if "--self-test" in sys.argv:
        architecture_self_test()
        return 0

    found = violations(SOURCE_ROOT)
    scanned = len(list(SOURCE_ROOT.rglob("*.java")))

    # The debt ledger, checked in both directions. A file that starts naming the frame path's concrete
    # generation is a regression and fails; a file that stops doing so must have its line removed in the
    # same commit, because a ledger nobody prunes reports work that is already done - and the point of this
    # number is that it can only go down. Nothing generation-specific was added to it since the day it was
    # written; if that changes, the diff says so.
    debt = frame_path_debt(SOURCE_ROOT)
    for path in sorted(set(debt) | set(FRAME_PATH_DEBT) | set(WRAPPER_DELEGATIONS)):
        actual = debt.get(path)
        if path in WRAPPER_DELEGATIONS:
            if actual != WRAPPER_DELEGATIONS[path]:
                found.append(
                    f"{path}: the delegation ledger records {', '.join(WRAPPER_DELEGATIONS[path])} and the "
                    f"file names {'nothing' if actual is None else ', '.join(actual)}"
                )
            continue
        recorded = FRAME_PATH_DEBT.get(path)
        if actual == recorded:
            continue
        if recorded is None:
            found.append(f"{path}: names the frame path's concrete generation ({', '.join(actual)}) and is not in the debt ledger, which may only shrink")
        elif actual is None:
            found.append(f"{path}: the debt ledger still lists {', '.join(recorded)}, and the file no longer names them; remove the line, the ledger records work that is left")
        else:
            found.append(f"{path}: the debt ledger records {', '.join(recorded)} and the file names {', '.join(actual)}")
    overlap = set(FRAME_PATH_DEBT) & set(WRAPPER_DELEGATIONS)
    if overlap:
        found.append(
            "the same file is in the debt ledger and the delegation ledger, so one of the two numbers is "
            "counting it twice: " + ", ".join(sorted(overlap))
        )

    # The flat surface's reach into a generation package, on the same both-ways terms. This is the number the
    # phase can actually move: the rule above stops a file mixing two generations, and this one says how much
    # of one generation is still named from the surface a pack-facing engine is allowed to know.
    reach = generation_reach(SOURCE_ROOT)
    for path in sorted(set(reach) | set(GENERATION_REACH)):
        actual = reach.get(path)
        recorded = GENERATION_REACH.get(path)
        if actual == recorded:
            continue
        if recorded is None:
            found.append(
                f"{path}: names a class inside a generation package ({', '.join(actual)}) from outside one, so "
                "the flat surface has reached past the neutral layer; route it through render.shared or record "
                "the crossing in GENERATION_REACH with the reason"
            )
        elif actual is None:
            found.append(
                f"{path}: the generation-reach ledger still lists {', '.join(recorded)} and the file names them "
                "nowhere; remove the line, the ledger records work that is left"
            )
        else:
            found.append(
                f"{path}: the generation-reach ledger records {', '.join(recorded)} and the file names "
                f"{', '.join(actual)}"
            )
    counted_twice = set(GENERATION_REACH) & (set(FRAME_PATH_DEBT) | set(WRAPPER_DELEGATIONS))
    if counted_twice:
        found.append(
            "the same file is in the generation-reach ledger and in another one, so a coupling is counted "
            "twice: " + ", ".join(sorted(counted_twice))
        )
    couplings = sum(len(names) for names in FRAME_PATH_DEBT.values())
    stray_delegations = undelivered_delegations(SOURCE_ROOT)
    for relative in stray_delegations:
        found.append(
            f"{relative}: listed as a wrapper delegation and nothing in a generation package calls it, so it "
            "is not a delegation any more"
        )
    if scanned == 0:
        raise SystemExit(f"no sources under {SOURCE_ROOT}, so nothing was checked")

    if found:
        for line in found:
            print(line, file=sys.stderr)
        raise SystemExit(f"architecture guard: {len(found)} violation(s)")

    print(
        f"architecture guard: PASS ({scanned} sources, {len(LAYERS)} package rules, one mixing rule; "
        f"the frame path's isolation still owes {couplings} couplings in {len(FRAME_PATH_DEBT)} files, and "
        f"{len(WRAPPER_DELEGATIONS)} the other way; the flat surface still reaches "
        f"{sum(len(names) for names in GENERATION_REACH.values())} generation class(es) in "
        f"{len(GENERATION_REACH)} file(s))"
    )
    return 0



_MAIN_STATUS.append(architecture_main())

raise SystemExit(max(_MAIN_STATUS) if _MAIN_STATUS else 0)
