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


require("Metal compute pipeline", "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "newComputePipelineState(function)",
    "commandEncoder.computeCommandEncoder()",
    "compute.setComputePipelineState(pipeline.pipelineState)",
    "compute.dispatchThreadgroups(",
    "groupsX, groupsY, groupsZ,",
    "localX, localY, localZ",
    "case UNIFORM_BUFFER, STORAGE_BUFFER -> bindBuffer(compute, binding, buffers);",
    "case STORAGE_IMAGE -> bindStorageImage(compute, binding, textures);",
    "((MetalGpuTexture) view.texture()).markContentsDirty();",
    "compute.setTexture(view.nativeHandle(), binding.textureIndex);",
    "commandEncoder.flushPendingClear((MetalGpuTexture) view.texture());",
    "finally {",
    "commandEncoder.endEncoder();",
))

require("Metal compute encoder wrapper", "src/main/java/com/metallum/mtl/MTLComputeCommandEncoder.java", (
    "setComputePipelineState:",
    "setBuffer:offset:atIndex:",
    "setTexture:atIndex:",
    "dispatchThreadgroups:threadsPerThreadgroup:",
    "maxTotalThreadsPerThreadgroup",
    "if (total > this.maxTotalThreadsPerThreadgroup)",
    "updateFence:",
    "waitForFence:",
))

require("Generic compute/render/blit fence lifecycle", "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
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

require("Shader-readable/writable storage texture", "src/main/java/com/metallum/render/MetalGpuTexture.java", (
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
require("Untracked storage buffer hazards", "src/main/java/com/metallum/render/MetalGpuBuffer.java", (
    "MTLHazardTrackingMode.Untracked",
    "void zeroContents()",
))

require("Render storage resource binding", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "binding.kind() == MetalCompiledRenderPipeline.ResourceKind.STORAGE_IMAGE",
    "binding.kind() == MetalCompiledRenderPipeline.ResourceKind.STORAGE_BUFFER",
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
    "Dispatched compute composite through the active backend",
    "Dispatched compute composite_a through the active backend",
    "Dispatched 2 compute pass(es) at composite",
    "PHASE 15 Compute / Storage: PASS",
    "--verify-existing",
    "Stopping!",
):
    if needle not in launcher_text:
        raise SystemExit("PHASE 15 launcher contract missing: " + needle)

print("PHASE 15 generic Metal Compute / Storage contracts: PASS")
