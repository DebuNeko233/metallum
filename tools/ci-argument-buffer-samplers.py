#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "src/main/java/com/metallum/mtl/MTLSamplerDescriptor.java"
SAMPLER = ROOT / "src/main/java/com/metallum/render/shared/MetalGpuSampler.java"
COMPILER = ROOT / "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(label: str, source: str, needles: tuple[str, ...]) -> None:
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"{label}: missing " + ", ".join(missing))


descriptor = text(DESCRIPTOR)
sampler = text(SAMPLER)
compiler = text(COMPILER)

require("MTLSamplerDescriptor argument-buffer selector", descriptor, (
    'private static final Msg SET_SUPPORT_ARGUMENT_BUFFERS = Msg.ofVoid("setSupportArgumentBuffers:", JAVA_BOOLEAN);',
    "public void supportArgumentBuffers(final boolean support) {",
    "SET_SUPPORT_ARGUMENT_BUFFERS.send(handle, support);",
))

if descriptor.count('setSupportArgumentBuffers:') != 1:
    raise SystemExit("MTLSamplerDescriptor argument-buffer selector must be declared exactly once")

require("Metal sampler argument-buffer compatibility", sampler, (
    "try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {",
    "descriptor.supportArgumentBuffers(true);",
    "this.nativeHandle = device.metalDevice().newSamplerState(descriptor);",
    "return this.comparisonVariants.computeIfAbsent(compareOp, op -> new MetalGpuSampler(",
))

if sampler.count("descriptor.supportArgumentBuffers(true);") != 1:
    raise SystemExit("MetalGpuSampler must enable argument-buffer support exactly once on the shared construction path")
if "descriptor.supportArgumentBuffers(false);" in sampler:
    raise SystemExit("MetalGpuSampler disables argument-buffer support")
if sampler.count("newSamplerState(descriptor)") != 1:
    raise SystemExit("MetalGpuSampler gained a sampler-state construction path not covered by the argument-buffer flag")

support = sampler.index("descriptor.supportArgumentBuffers(true);")
create = sampler.index("this.nativeHandle = device.metalDevice().newSamplerState(descriptor);")
if support > create:
    raise SystemExit("MetalGpuSampler enables argument-buffer support after creating the native sampler state")

for forbidden in ("Photon", "photon", "colorimg", "shadowtex", "gbuffers_"):
    if forbidden in descriptor or forbidden in sampler:
        raise SystemExit(f"Sampler argument-buffer support leaked shader-pack semantics: {forbidden}")

# ---------------------------------------------------------------------------
# When a pipeline needs argument buffers at all
#
# The direct path maps an entry's own position in the layout to its Metal sampler slot, so the question
# is which slot the last sampled image lands in and not how many sampled images there are. Counting them
# put a program with sixteen images behind one uniform buffer at sampler slot sixteen, which Metal does
# not have: it is the difference between a pipeline that runs wide and one that never compiles, and it
# was found by a run of the performance harness rather than by reading this file.
#
# The decision answers with the shape it refused rather than with a boolean, because the only reader of a
# boolean is a throw whose message has to name what was too wide. The two live slots are pinned by name:
# the sampler rule is the entry index of the last sampled image, and the buffer rule is the buffer span
# against Metal's 31 buffer slots.
# ---------------------------------------------------------------------------
require("The direct-resource decision counts the last sampler slot", compiler, (
    "int lastSamplerSlot = -1;",
    "lastSamplerSlot = index;",
    "boolean samplersOverflow = lastSamplerSlot >= DIRECT_SAMPLER_LIMIT;",
    "case SAMPLED_IMAGE -> {",
    "sampledImages++;",
    "boolean buffersOverflow = entries.size() + vertexBindingSpan >= 31;",
    "String wideReason = wideReason(layoutEntries, pipeline);",
    "boolean useArgumentBuffers = wideReason != null;",
))
if "sampledImages > DIRECT_SAMPLER_LIMIT" in compiler:
    raise SystemExit(
        "the direct-resource decision counts sampled images again, which is not the slot the last one lands in"
    )
if "private static boolean needsArgumentBuffers(" in compiler:
    raise SystemExit(
        "the direct-resource decision went back to a boolean, so a refusal cannot say what the layout was"
    )

print("Metal argument-buffer sampler contract: PASS")
