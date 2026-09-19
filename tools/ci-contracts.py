#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


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


def source_tree(rel: str = "src/main/java/com/metallum") -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / rel).rglob("*.java"))


device = read("src/main/java/com/metallum/render/MetalDevice.java")
encoder = read("src/main/java/com/metallum/render/MetalCommandEncoder.java")
pipeline = read("src/main/java/com/metallum/render/MetalCompiledRenderPipeline.java")
render_pass = read("src/main/java/com/metallum/render/MetalRenderPass.java")
compiler = read("src/main/java/com/metallum/render/MetalCrossShaderCompiler.java")
texture = read("src/main/java/com/metallum/render/MetalGpuTexture.java")
formats = read("src/main/java/com/metallum/mtl/MTLPixelFormat.java")
compare = read("src/main/java/com/metallum/mtl/MTLCompareFunction.java")
mtl_device = read("src/main/java/com/metallum/mtl/MTLDevice.java")
render_encoder = read("src/main/java/com/metallum/mtl/MTLRenderCommandEncoder.java")
backend = source_tree()
all_java = source_tree("src/main/java")

advertised = re.search(r"new DeviceLimits\(16, 256, 16384, maxMemoryAllocationSize, 0, (\d+)\)", device)
implemented = re.search(r"MAX_COLOR_ATTACHMENTS\s*=\s*(\d+)", encoder)
if advertised is None or implemented is None or advertised.group(1) != implemented.group(1):
    raise SystemExit("Metal MRT attachment limit metadata is not aligned")

for mapping in (
    "case R8_UNORM -> R8Unorm;",
    "case RG8_UNORM -> RG8Unorm;",
    "case RGBA16_FLOAT -> RGBA16Float;",
    "case RGB10A2_UNORM -> RGB10A2Unorm;",
    "case R32_FLOAT -> R32Float;",
    "case D32_FLOAT -> Depth32Float;",
):
    if mapping not in formats:
        raise SystemExit("Missing Metal pixel-format mapping: " + mapping)
if "case LESS_THAN_OR_EQUAL -> LessEqual;" not in compare:
    raise SystemExit("Missing forward-depth compare mapping")

require("Metal texture allocation", "src/main/java/com/metallum/render/MetalGpuTexture.java", (
    "this.mtlPixelFormat = MTLPixelFormat.from(format);",
    "descriptor.pixelFormat(this.mtlPixelFormat);",
    "if ((usage & GpuTexture.USAGE_RENDER_ATTACHMENT) != 0)",
    "result |= MTLTextureUsage.RenderTarget.value;",
    "result |= MTLTextureUsage.ShaderRead.value;",
))
require("Metal render pipeline", "src/main/java/com/metallum/render/MetalCompiledRenderPipeline.java", (
    "ColorTargetState[] colorTargets = info.getColorTargetStates();",
    "pipelineDesc.setColorAttachmentFormat(index, MTLPixelFormat.from(colorTarget.format()));",
    "long writeMask = MTLColorWriteMask.from(colorTarget.writeMask());",
    "pipelineDesc.disableBlending(index, writeMask);",
    "this.cullMode = info.isCull() ? MTLCullMode.Back : MTLCullMode.None;",
    "depthCompareOp = MTLCompareFunction.from(depthStencilState.depthTest());",
    "depthWrite = depthStencilState.writeDepth() ? 1 : 0;",
))
require("Metal MRT encoder", "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "Vector4fc[] colorClears = new Vector4fc[colorAttachments.size()];",
    "Vector4fc colorClear = colorAttachment.clearValue().orElse(null);",
    "colorTextures[index] = colorTexture;",
    "colorClears[index] = colorClear;",
    "MemorySegment[] colorAttachments = new MemorySegment[colorTextureViews.length];",
    "colorAttachments[index] = colorTextureView == null ? MemorySegment.NULL : colorTextureView.nativeHandle();",
    "MetalPipelineSupport.sameHandles(renderColorAttachments, colorAttachments)",
    "currentRenderPass.materializePendingClear();",
    "renderEncoder.updateFence(fence, MTLRenderStages.VertexAndFragment);",
    "currentEncoder.endEncoding();",
    "encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);",
))
require("Native render-pass store/clear", "src/main/java/com/metallum/mtl/MTLCommandBuffer.java", (
    "Vector4fc clearColor = clearColors == null ? null : clearColors[index];",
    "MTLRenderPassDescriptor.LOAD_ACTION_CLEAR",
    "MTLRenderPassDescriptor.STORE_ACTION_STORE",
))
require("Metal draw and direct sampling", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "enc.setRenderPipelineState(pipelineHandle);",
    "enc.drawPrimitives(primitiveType, firstVertex, vertexCount, instanceCount, firstInstance);",
    "samplers.put(name, new TextureViewAndSampler(textureView, sampler));",
    "commandEncoder.flushPendingClear((MetalGpuTexture) textureView.texture());",
    "markDescriptorDirty(name);",
    "if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.SAMPLED_IMAGE) {",
    "bindTextureAndSampler(enc, textureView.nativeHandle(), sampler.nativeHandle(), binding.bindingIndex(), binding.stageMask());",
    "enc.setFragmentTexture(texture, index);",
    "enc.setFragmentSamplerState(sampler, index);",
))
require("Direct/wide resource numbering", "src/main/java/com/metallum/render/MetalCrossShaderCompiler.java", (
    "int metalIndex = useArgumentBuffers ? index * 2 : index;",
    "int samplerIndex = useArgumentBuffers ? metalIndex + 1 : metalIndex;",
))
require("Metal invariance", "src/main/java/com/metallum/mtl/MTLCompileOptions.java", (
    "setPreserveInvariance:",
    "JAVA_BOOLEAN",
))
if "options.setPreserveInvariance(true);" not in mtl_device:
    raise SystemExit("Metal shader-library compilation does not enable preserveInvariance")
if "NEW_LIBRARY_WITH_SOURCE.sendPtr(handle, nsSource, options.handle(), errorOut)" not in mtl_device:
    raise SystemExit("Metal shader-library compilation does not pass MTLCompileOptions")
if "NEW_LIBRARY_WITH_SOURCE.sendPtr(handle, nsSource, MemorySegment.NULL, errorOut)" in mtl_device:
    raise SystemExit("Metal shader-library compilation still discards compile options")

require("Generic carried vertex ABI", "src/main/java/com/metallum/render/MetalCompiledRenderPipeline.java", (
    "long attributeIndex = 0L;",
    "int bindingCount = info.getVertexFormatBindings().length;",
    "VertexFormat format = info.getVertexFormatBinding(binding);",
    "int bufferIndex = firstAvailableBufferSlot + binding;",
    "format.getVertexSize()",
    "long stepRate = format.getStepRate();",
    "for (VertexFormatElement element : format.getElements())",
    "MTLVertexFormat vertexFormat = MTLVertexFormat.from(element.format());",
    "descriptor.setAttribute(attributeIndex, vertexFormat.value, element.offset(), bufferIndex);",
    "attributeIndex++;",
    "TEXEL_BUFFER",
    "if (format == null || format.getElements().isEmpty()) {",
))
require("Generic vertex/resource binding", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "int firstSlot = compiledPipeline.firstAvailableVertexBufferSlot();",
    "int count = compiledPipeline.vertexBufferCount();",
    "int metalSlot = firstSlot + slot;",
    "enc.setVertexBuffer(nativeVertexBuffer.metalBuffer(), vertexBuffer.offset(), metalSlot);",
    "public void bindTexture(final @NonNull String name",
    "bindTexture(enc, textureView.nativeHandle(), binding.bindingIndex(), binding.stageMask());",
    "public void setUniform(final @NonNull String name, final GpuBuffer value)",
    "uniforms.put(name, value);",
    "if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.TEXEL_BUFFER)",
    "pushDirectTexelBufferDescriptor(enc, binding);",
    "private MemorySegment createTexelBufferTexture(",
    "GpuBufferSlice texelSlice = requiredBuffer(binding);",
    "private GpuBufferSlice requiredBuffer(",
    "GpuFormat texelFormat = binding.texelBufferFormat();",
    "MTLTexture.newBufferTextureView(",
))
require("Triangle-fan conversion", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "if (primitiveType == MTLPrimitiveType.TriangleFan)",
    "drawTriangleFan(enc, firstVertex, vertexCount, instanceCount, firstInstance);",
    "private void drawTriangleFan(",
    "int triangleCount = vertexCount - 2;",
    "indices.put((short) 0)",
    ".put((short) (i + 1))",
    ".put((short) (i + 2))",
))
forbid("Sky semantics in Metallum", backend, ("gbuffers_skybasic", "gbuffers_skytextured", "CUSTOM_SKY", "end_sky.png", "celestials.png"))
forbid("Cloud semantics in Metallum", backend, ("gbuffers_clouds", "CloudInfo", "CloudFaces"))
forbid("Weather semantics in Metallum", all_java, ("gbuffers_weather", "RAIN_SNOW"))

require("Generic texture copy/mipmap", "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "public void copyTextureToTexture(",
    "flushPendingClear(srcTexture);",
    "flushPendingClearForWrite(dstTexture);",
    "MTLBlitCommandEncoder blit = blitCommandEncoder();",
    "blit.copyFromTextureToTexture(",
    "public boolean generateMipmaps(final GpuTexture texture)",
    "texture.getMipLevels() <= 1",
    "flushPendingClear(metalTexture);",
    "blit.generateMipmapsForTexture(metalTexture.nativeHandle());",
    "RGBA8_UNORM, RGBA8_SNORM,",
    "endEncoder();",
))
require("Composite render/blit fences", "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "encoder.waitForFence(fence);",
    "blitEncoder.updateFence(fence);",
    "renderEncoder.updateFence(fence, MTLRenderStages.VertexAndFragment);",
    "encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);",
))
require("Generic D32 mip bridge", "src/main/java/com/metallum/render/MetalDepthMipmapBridge.java", (
    "texture.getFormat() != GpuFormat.D32_FLOAT",
    "GpuTexture.USAGE_TEXTURE_BINDING",
    "GpuTexture.USAGE_RENDER_ATTACHMENT",
    "depth2d<float> source [[texture(0)]]",
    "source.sample(nearestSampler, in.uv)",
    "descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);",
    "descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);",
    "descriptor.mipFilter(MTLSamplerMipFilter.NotMipmapped);",
    "descriptor.setDepthStencilFormats(MTLPixelFormat.Depth32Float, MTLPixelFormat.Invalid);",
    "device.depthStencilState(MTLCompareFunction.Always, true)",
    "new MetalGpuTextureView(texture, level - 1, 1)",
    "new MetalGpuTextureView(texture, level, 1)",
    "render.setFragmentTexture(source.nativeHandle(), 0L);",
    "render.drawPrimitives(MTLPrimitiveType.Triangle, 0, 3, 1, 0);",
    "encoder.endEncoder();",
))
depth_bridge = read("src/main/java/com/metallum/render/MetalDepthMipmapBridge.java")
forbid("Depth mip bridge shader-pack neutrality", depth_bridge.lower(), ("shadowtex0", "shadowtex1", "shadowcolor0", "shadowcolor1", "shader pack"))
if "MetalDevice device()" not in texture:
    raise SystemExit("MetalGpuTexture must expose its device package-locally for generic depth mip generation")
forbid("Depth semantics in Metallum", backend, ("depthtex0", "depthtex1", "depthtex2", "pre-translucent", "pre-hand", "Vitrail depth window"))
forbid("Shadow semantics in Metallum", backend, ("shadow_entities", "shadowtex0", "shadowtex1", "shadowcolor0", "shadowcolor1", "shadow_solid", "shadow_cutout", "shadow_water"))
forbid("Deferred fixture semantics in Metallum", backend, ("deferred-mrt-contract", "deferred-mipmap-contract", "colortex0mipmapenabled"), lower=True)

require("Generic Final present entry", "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "void presentTextureToDrawable(final CAMetalLayer layer, final GpuTextureView textureView)",
    "flushPendingClear(source);",
    "submitRenderPass();",
    "commandBuffer.encodePresentTextureToDrawable(layer, source.nativeHandle(), fence);",
))
require("Generic command-buffer present", "src/main/java/com/metallum/mtl/MTLCommandBuffer.java", (
    "private static final Msg PRESENT_DRAWABLE = Msg.ofVoid(\"presentDrawable:\", ADDRESS);",
    "public void encodePresentTextureToDrawable(final CAMetalLayer layer, final MemorySegment sourceTexture, final MTLFence globalFence)",
    "PRESENT_DRAWABLE.send(handle(), drawable.handle());",
))
require("Generic CAMetalLayer presentation", "src/main/java/com/metallum/mtl/MTLBuiltinPipelines.java", (
    "CAMetalDrawable drawable = layer.nextDrawable();",
    "MemorySegment drawableTexture = drawable.texture();",
    "MTLRenderPassDescriptor.LOAD_ACTION_DONT_CARE",
    "MTLRenderPassDescriptor.STORE_ACTION_STORE",
    "encoder.setFragmentTexture(sourceTexture, 0L);",
    "encoder.drawPrimitives(MTLPrimitiveType.Triangle, 0, 3, 1, 0);",
    "commandBuffer.presentDrawable(drawable);",
))
forbid("Composite semantics in Metallum", backend, (
    "composite-flip-contract", "composite-history-contract", "composite_pre",
    "colortex0", "colortex1", "colortex2", "colortex2clear",
), lower=True)
forbid("Final semantics in Metallum", backend, ("final-direct-contract", "final-chain-contract", "phase 12 final"), lower=True)

dimension_sources = "\n".join(read(path) for path in (
    "src/main/java/com/metallum/render/MetalCommandEncoder.java",
    "src/main/java/com/metallum/mtl/MTLCommandBuffer.java",
    "src/main/java/com/metallum/mtl/MTLBuiltinPipelines.java",
))
forbid("Dimension routing semantics in Metallum", dimension_sources, (
    "dimension-convention-contract", "dimension-properties-contract", "dimension.properties",
    "world0", "world-1", "world1", "minecraft:the_nether", "minecraft:the_end", "vitrail:moon",
), lower=True)

require("Wide resource compiler", "src/main/java/com/metallum/render/MetalCrossShaderCompiler.java", (
    "DIRECT_SAMPLER_LIMIT = 16",
    "lastSamplerSlot >= DIRECT_SAMPLER_LIMIT",
    "supportsArgumentBuffersTier2()",
    "SpvcMslResourceBinding",
    "SPVC_MSL_ARGUMENT_BUFFER_BINDING",
))
require("Wide resource pipeline", "src/main/java/com/metallum/render/MetalCompiledRenderPipeline.java", (
    "private final BitSet allResources;",
    "uses Metal Argument Buffers: resources={}, sampledImages={}",
    "maxArgumentBufferSamplerCount()",
    "createArgumentBuffers(",
    "WIDE_VERTEX_BUFFER_BASE",
))
require("Wide resource draw routing", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "private final BitSet dirtyDescriptors = new BitSet();",
    "layout.encoder().setTexture(textureView.nativeHandle(), binding.metalIndex());",
    "layout.encoder().setSamplerState(sampler.nativeHandle(), binding.samplerMetalIndex());",
    "enc.useResource(",
    "RESOURCE_USAGE_SAMPLE",
    "ensureArgumentBuffersBound(enc);",
))
if "1L << binding.bindingIndex()" in render_pass or "dirtyDescriptorMask" in render_pass:
    raise SystemExit("Fixed-width descriptor dirty tracking returned")
require("MTLArgumentEncoder wrapper", "src/main/java/com/metallum/mtl/MTLArgumentEncoder.java", (
    "newArgumentEncoderWithBufferIndex:",
    "setArgumentBuffer:offset:",
    "setTexture:atIndex:",
    "setSamplerState:atIndex:",
))
if "argumentBuffersSupport" not in mtl_device or "maxArgumentBufferSamplerCount" not in mtl_device:
    raise SystemExit("Metal Argument Buffer capabilities are not queried")
if "useResource:usage:stages:" not in render_encoder:
    raise SystemExit("Indirect Argument Buffer resources are not declared resident")
forbid("Wide fixture semantics in Metallum", backend, ("wide-resources-contract", "customTexture.wide", "wide00", "wide32"))

marker = 'private static final String DEPTH_MIP_MSL = """'
start = depth_bridge.index(marker) + len(marker)
end = depth_bridge.index('""";', start)
metal = textwrap.dedent(depth_bridge[start:end]).strip() + "\n"
if sys.platform == "darwin":
    with tempfile.TemporaryDirectory(prefix="metallum-depth-mip-") as tmp:
        src = Path(tmp) / "depth-mip.metal"
        air = Path(tmp) / "depth-mip.air"
        src.write_text(metal, encoding="utf-8")
        subprocess.run(["xcrun", "-sdk", "macosx", "metal", "-c", str(src), "-o", str(air)], check=True)
        if not air.is_file() or air.stat().st_size == 0:
            raise SystemExit("Embedded D32 mip Metal shader did not compile")

check_launcher("tools/run-vitrail-smoke.sh", (
    "--mrt-fixture", "--terrain-fixture", "--gbuffer-location-fixture", "--gbuffer-format-fixture",
    "--gbuffer-clear-fixture", "--gbuffer-write-fixture", "--gbuffer-sampling-fixture", "--gbuffer-pingpong-fixture",
    "--armor-glint-fixture", "--block-entity-fixture", "--entity-fixture", "--hand-fixture", "--hand-water-fixture",
    "--hand-glint-fixture", "--hand-water-glint-fixture", "--spider-eyes-fixture",
    "gbuffer-location-contract", "gbuffer-format-contract", "gbuffer-clear-contract", "gbuffer-write-contract",
    "gbuffer-sampling-contract", "gbuffer-pingpong-contract", "VerifyMrtScreenshot.java", "VerifyTerrainScreenshot.java",
    "armor-glint-contract", "VerifyArmorGlintScreenshot.java", "block-entity-contract", "VerifyBlockEntityScreenshot.java",
    "entity-contract", "VerifyEntityScreenshot.java", "hand-contract", "hand-water-contract", "VerifyHandScreenshot.java",
    "hand-glint-contract", "hand-water-glint-contract", "VerifyHandGlintScreenshot.java", "spider-eyes-contract",
    "VerifySpiderEyesScreenshot.java", "run/logs/latest.log", "Using graphics backend Metal",
))
check_launcher("tools/run-vitrail-sky-smoke.sh", (
    "sky-contract", "VerifySkyScreenshot.java", "--overworld", "--end", "gbuffers_skybasic", "gbuffers_skytextured",
    "render stage SKY", "render stage SUNSET", "render stage CUSTOM_SKY", "minecraft:textures/atlas/celestials",
    "minecraft:textures/environment/end_sky", "[colortex1 MAIN]", "coverage mask", "Stopping!",
))
check_launcher("tools/run-vitrail-cloud-smoke.sh", (
    "clouds-contract", "VerifyCloudScreenshot.java", "gbuffers_clouds", "render stage CLOUDS", "0 samplers",
    "[colortex1 MAIN]", "Stopping!",
))
check_launcher("tools/run-vitrail-weather-smoke.sh", (
    "weather-contract", "VerifyWeatherScreenshot.java", "gbuffers_weather", "RAIN_SNOW", "[colortex1 MAIN]", "Stopping!",
), regex=(r"textures/environment/\(rain\|snow\)",))
check_launcher("tools/run-vitrail-particle-smoke.sh", (
    "--opaque", "--translucent", "particles-opaque-contract", "particles-translucent-contract", "VerifyParticleScreenshot.java",
    "Drawing the ${pass_name} particles pass with ${program} of ${fixture_name} at render stage PARTICLES",
    "minecraft:textures/atlas/particles.png", "[colortex1 MAIN]", "It also writes the coverage mask", "Stopping!",
))
check_launcher("tools/run-vitrail-depthtex0-smoke.sh", (
    "depthtex0-contract", "VerifyDepthtex0Screenshot.java", "minecraft:overworld",
    "The world's depth is converted into the pack's window in two images", "The scene's depth is kept", "Stopping!",
))
check_launcher("tools/run-vitrail-depth-batch-smoke.sh", (
    "depthtex1-contract", "depthtex2-contract", "pre-translucent-contract", "VerifyDepthBatchScreenshot.java",
    "--depthtex1", "--depthtex2", "--pre-translucent", "1 samplers this chain read the world",
    "1 more before its translucents [deferred]", "Vitrail depth window", "Stopping!",
))
check_launcher("tools/run-vitrail-depth-final-smoke.sh", (
    "pre-hand-contract", "depth-conversion-contract", "VerifyDepthFinalScreenshot.java", "HAND_SOLID",
    "The depth before the hand is converted into the pack's window in one more image",
    "The world's depth is converted into the pack's window in two images", "Stopping!",
))
check_launcher("tools/run-vitrail-shadow-terrain-smoke.sh", (
    "shadow-terrain-contract", "VerifyShadowTerrainScreenshot.java", "shadow_solid", "shadow_cutout", "shadow_water",
    "pass='shadow_translucent'", "RAW LIGHT-SPACE shadowcolor0 diagnostic", "Shadow map allocated at ",
    "minecraft:textures/atlas/blocks.png", "Stopping!",
))
check_launcher("tools/run-vitrail-shadow-batch-smoke.sh", (
    "shadow-entities-contract", "shadow-depth-contract", "shadow-color-contract", "VerifyShadowBatchScreenshot.java",
    "--entities", "--depth", "--color", "--verify-existing", "entity pass with shadow_entities",
    "shadow_translucent chunk pass with shadow", "shadowcolor0 and shadowcolor1",
    "latest completed shadow batch without launching Minecraft", "shadow mipmaps remain pending", "Stopping!",
), forbidden=("entities in the shadow map pass with shadow_entities",))
check_launcher("tools/run-vitrail-shadow-mipmap-smoke.sh", (
    "shadow-mipmap-contract", "VerifyShadowMipmapScreenshot.java", "--verify-existing", "both shadowtex0 and shadowtex1",
    "shadow_solid chunk pass with shadow", "readable generated shadow depth mips", "Stopping!",
    "and ([2-9]|[1-9][0-9]+) where it reads shadowtex1",
))
check_launcher("tools/run-vitrail-deferred-smoke.sh", (
    "deferred-contract", "VerifyDeferredScreenshot.java", "--verify-existing", "deferred writes colortex0 alt",
    "deferred1 writes colortex0 main", "deferred2 writes colortex0 alt", "final writes the game's own target", "Stopping!",
))
check_launcher("tools/run-vitrail-deferred-depth-smoke.sh", (
    "deferred-depth-contract", "VerifyDeferredDepthScreenshot.java", "--verify-existing", "deferred writes colortex0 alt",
    "deferred1 writes colortex0 main", "deferred2 writes colortex0 alt", "samplers this chain read the world's depth",
    "depthtex0", "The world's depth is converted into the pack's window in two images", "Vitrail depth window", "Stopping!",
))
check_launcher("tools/run-vitrail-deferred-tail-smoke.sh", (
    "deferred-mrt-contract", "deferred-mipmap-contract", "VerifyDeferredTailScreenshot.java", "2 targets doubled: \\[0, 1\\]",
    "level\\(s\\)", "PHASE 10 deferred MRT: PASS", "PHASE 10 deferred mipmap: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-composite-smoke.sh", (
    "composite-flip-contract", "composite-history-contract", "VerifyCompositeScreenshot.java", "--verify-existing",
    "PHASE 11 composite flip parity: PASS", "PHASE 11 composite temporal/history: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-final-smoke.sh", (
    "final-direct-contract", "final-chain-contract", "VerifyFinalScreenshot.java", "--verify-existing",
    "PHASE 12 final direct: PASS", "PHASE 12 final chain-to-screen: PASS", "Batched PHASE 12 Final: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-dimension-routing-smoke.sh", (
    "dimension-convention-contract", "dimension-properties-contract", "VerifyDimensionRoutingScreenshot.java",
    "world0 for minecraft:overworld", "world-1 for minecraft:the_nether", "world1 for minecraft:the_end",
    "surface for minecraft:overworld", "under for minecraft:the_nether", "catchall for minecraft:the_end",
    "--verify-existing", "Batched PHASE 13 Dimension Routing: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-wide-resources-smoke.sh", (
    "wide-resources-contract", "VerifyWideResourcesScreenshot.java", "sampledImages=33", "Wide resource pipeline",
    "--verify-existing", "Batched PHASE 14 Wide Resources: PASS", "Stopping!",
))

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
# A contract script that no workflow names is not a contract. `tools/ci-graphics-storage-images.py`
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

print("Consolidated Metallum CI contracts: PASS")


# ---------------------------------------------------------------------------
# Three more places where the code and Apple's documentation disagreed
#
# 1. A presented frame makes two submits - the frame's own commit and the surface's present-time one,
#    which commits nothing - so "the newest submitted work" is not `currentSubmitIndex - 1`. Derived
#    that way, the wait before a pipeline cache is cleared named an index no in-flight slot holds, and
#    a wait for an index that is not in flight returns at once: a pack reload could release pipeline
#    states while command buffers were still running them.
# 2. Metal's status machine has a state for finished and a state for failed, and both answer
#    `isCompleted`. Nothing read the error, so a failed command buffer was reported as a drawn frame.
# 3. A `CAMetalLayer` is created with an explicit +1 that only this code owns, and clearing the view
#    detaches rather than releases: the layer outlived every device made for it.
# ---------------------------------------------------------------------------
require("the wait names the newest commit and not the newest submit",
        "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "private long lastCommittedSubmitIndex = -1L;",
    "lastCommittedSubmitIndex = currentSubmitIndex;",
    "awaitSubmitCompletion(lastCommittedSubmitIndex, Long.MAX_VALUE);",
))
forbid("the wait no longer derives its index from the submit counter",
       read("src/main/java/com/metallum/render/MetalCommandEncoder.java"),
       ("currentSubmitIndex - 1L",))

require("a failed command buffer can be read", "src/main/java/com/metallum/mtl/MTLCommandBuffer.java", (
    'Msg.of("error", ADDRESS)',
    "public String errorDescription()",
))
require("the frame says when a command buffer failed",
        "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "toClose.buffer.errorDescription()",
))

require("the layer gives its own reference back", "src/main/java/com/metallum/mtl/CAMetalLayer.java", (
    "public void close() {",
    "ObjC.release(handle);",
))
require("the device releases the layer it was given",
        "src/main/java/com/metallum/render/MetalDevice.java", ("this.metalLayer.close();",))
require("a failed device creation releases the layer",
        "src/main/java/com/metallum/render/MetalBackend.java", ("metalLayer.close();",))

print("Metal and engine contracts: PASS")
