#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "src/main/java/com/metallum/mtl/MTLSamplerDescriptor.java"
SAMPLER = ROOT / "src/main/java/com/metallum/render/MetalGpuSampler.java"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(label: str, source: str, needles: tuple[str, ...]) -> None:
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"{label}: missing " + ", ".join(missing))


descriptor = text(DESCRIPTOR)
sampler = text(SAMPLER)

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

print("Metal argument-buffer sampler contract: PASS")
