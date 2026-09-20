#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(label: str, rel: str, needles: tuple[str, ...]) -> None:
    source = read(rel)
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"{label}: missing " + ", ".join(missing))


def source_tree() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/main/java/com/metallum").rglob("*.java")
    )


require("Metal compute pipeline", "src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java", (
    "newComputePipelineState(function)",
    "commandEncoder.computeCommandEncoder()",
    "compute.setComputePipelineState(pipeline.pipelineState)",
    "compute.dispatchThreadgroups(",
    "groupsX, groupsY, groupsZ,",
    "localX, localY, localZ",
    "case UNIFORM_BUFFER, STORAGE_BUFFER -> bindBuffer(compute, binding, buffers);",
    "case STORAGE_IMAGE -> bindStorageImage(compute, binding, textures);",
    "((MetalGpuTexture) view.texture()).markContentsDirty();",
    "compute.setTexture(view.nativeHandle(), binding.textureIndex());",
    "commandEncoder.flushPendingClear((MetalGpuTexture) view.texture());",
    "finally {",
    "commandEncoder.endEncoder();",
))

require("Metal compute encoder wrapper", "src/main/java/com/metallum/mtl/metal3/MTLComputeCommandEncoder.java", (
    "setComputePipelineState:",
    "setBuffer:offset:atIndex:",
    "setTexture:atIndex:",
    "dispatchThreadgroups:threadsPerThreadgroup:",
    "maxTotalThreadsPerThreadgroup",
    "if (total > this.maxTotalThreadsPerThreadgroup)",
    "updateFence:",
    "waitForFence:",
))

require("Generic compute/render/blit fence lifecycle", "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "MTLBlitCommandEncoder blitCommandEncoder() {",
    "MTLComputeCommandEncoder computeCommandEncoder() {",
    "endEncoder();",
    "encoder.waitForFence(fence);",
    "encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);",
    "renderEncoder.updateFence(fence, MTLRenderStages.VertexAndFragment);",
    "blitEncoder.updateFence(fence);",
    "computeEncoder.updateFence(fence);",
    "currentEncoder.endEncoding();",
))

require("Shader-readable/writable storage texture", "src/main/java/com/metallum/render/shared/MetalGpuTexture.java", (
    "descriptor.hazardTrackingMode(MTLHazardTrackingMode.Untracked);",
    "if (shaderWrite) {",
    "result |= MTLTextureUsage.ShaderRead.value;",
    "result |= MTLTextureUsage.ShaderWrite.value;",
))

require("Storage texture allocation", "src/main/java/com/metallum/render/MetalDevice.java", (
    "public GpuTexture createStorageTextureResource(",
    "case 1 -> MTLTextureType.Type1D;",
    "case 2 -> MTLTextureType.Type2D;",
    "case 3 -> MTLTextureType.Type3D;",
    "MTLTextureType type = switch (dimensions)",
))

require("Storage buffer allocation", "src/main/java/com/metallum/render/MetalDevice.java", (
    "public Object createStorageBufferResource(final long size)",
    "buffer.zeroContents();",
))
require("Untracked storage buffer hazards", "src/main/java/com/metallum/render/shared/MetalGpuBuffer.java", (
    "MTLHazardTrackingMode.Untracked",
    "void zeroContents()",
))

require("Render storage resource binding", "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "binding.kind() == MetalResourceBinding.ResourceKind.STORAGE_IMAGE",
    "binding.kind() == MetalResourceBinding.ResourceKind.STORAGE_BUFFER",
    "RESOURCE_USAGE_READ | MTLRenderCommandEncoder.RESOURCE_USAGE_WRITE",
))

backend = source_tree().lower()
for semantic in (
    "compute-storage-contract",
    "phase15buffer",
    "phase15image",
    "phase15tex",
    "composite_a.csh",
):
    if semantic in backend:
        raise SystemExit(f"Shader-pack PHASE 15 semantic leaked into Metallum production code: {semantic}")

launcher = ROOT / "tools/run-vitrail-compute-storage-smoke.sh"
subprocess.run(["bash", "-n", str(launcher)], check=True)
launcher_text = launcher.read_text(encoding="utf-8")
for needle in (
    "compute-storage-contract",
    "VerifyComputeStorageScreenshot.java",
    "minecraft:(overworld|the_nether|the_end)",
    "Dispatched compute composite through the active backend",
    "Dispatched compute composite_a through the active backend",
    "compute programs dispatched before the pass they hang off: [composite, composite_a]",
    "PHASE 15 Compute / Storage: PASS",
    "--verify-existing",
    "Stopping!",
):
    if needle not in launcher_text:
        raise SystemExit("PHASE 15 launcher contract missing: " + needle)

# ---------------------------------------------------------------------------
# The flat facades, and the neutral interfaces they are allowed to route through.
#
# The generation-reach ledger in `ci-architecture.py` refuses a class in `com.metallum.render` that names a
# generation package; that rule says where a facade may NOT go. This is the other half: what it does
# instead, so the neutrality of the compute/depth/close path is a shape a contract can read rather than a
# property that happens to hold. Each of these is an entry point a pack-facing engine reaches by name, so
# one drifting back to a generation class is a boundary change that would otherwise be invisible until the
# class it names moved.
# ---------------------------------------------------------------------------
require("the flat compute facade is neutral", "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "import com.metallum.render.shared.MetalComputeCompiler;",
    "import com.metallum.render.shared.MetalComputePipelineResource;",
    "import com.metallum.render.shared.MetalFrameComputeCommands;",
    "device.executionState() instanceof MetalComputeCompiler compiler",
    "return compiler.compileCompute(device, label, spirv);",
    "encoderBackend instanceof MetalFrameComputeCommands commands",
    "pipelineResource instanceof MetalComputePipelineResource",
))

require("the flat depth facade is neutral", "src/main/java/com/metallum/render/MetalDepthMipmapBridge.java", (
    "import com.metallum.render.shared.MetalFrameDepthMipmaps;",
    "instanceof MetalFrameDepthMipmaps",
    "generateDepthMipmaps(",
))

# The present path is closed exactly once, at the one site that owns it. It was called from two places once,
# and a second close is a released queue being released again.
device = read("src/main/java/com/metallum/render/MetalDevice.java")
closes = device.count("services.closePresentPath()")
if closes != 1:
    raise SystemExit(
        f"the present path is closed {closes} times in MetalDevice, and the device owns exactly one of them"
    )

print("PHASE 15 generic Metal Compute / Storage contracts: PASS")
