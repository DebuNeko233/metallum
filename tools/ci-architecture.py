#!/usr/bin/env python3
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

from __future__ import annotations

import re
import sys
from pathlib import Path

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
    # Still called from `render` rather than from a generation package, so it is debt today and becomes one of
    # the delegations above on the day the encoder moves - and this ledger is where that shows up.
    "com/metallum/render/MetalCommandEncoder.java": ("MTLBlitCommandEncoder", "MTLCommandBuffer", "MTLCommandEncoder", "MTLComputeCommandEncoder", "MTLRenderCommandEncoder", "MetalRenderPass",),
    "com/metallum/render/MetalComputeBridge.java": ("MTLComputeCommandEncoder", "MetalCommandEncoder",),
    "com/metallum/render/MetalDepthMipmapBridge.java": ("MTLRenderCommandEncoder", "MetalCommandEncoder",),
    "com/metallum/render/MetalDevice.java": ("MTLCommandQueue", "Metal4Path",),
    "com/metallum/render/MetalRenderPass.java": ("MTLRenderCommandEncoder", "MetalCommandEncoder",),
    "com/metallum/render/Metal4PresentGate.java": ("Metal4Path",),
    # The services construct the frame encoder: a generation's own factory belongs with the generation, and
    # the facade asks for the contract. This line becomes an allowed delegation when the class and its
    # factory move into render.metal3 together.
    "com/metallum/render/execution/MetalExecutionServices.java": ("MetalCommandEncoder",),
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


def self_test() -> None:
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

    if failures:
        raise SystemExit("architecture guard self-test failed: " + "; ".join(failures))

    print(
        f"architecture guard self-test: PASS ({len(cases)} rules fire, a compliant file passes, "
        "the debt ledger fires both ways)"
    )


def main() -> int:
    if "--self-test" in sys.argv:
        self_test()
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
        f"{len(WRAPPER_DELEGATIONS)} the other way)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
