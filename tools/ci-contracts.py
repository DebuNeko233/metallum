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
texture = read("src/main/java/com/metallum/render/shared/MetalGpuTexture.java")
formats = read("src/main/java/com/metallum/mtl/MTLPixelFormat.java")
compare = read("src/main/java/com/metallum/mtl/MTLCompareFunction.java")
mtl_device = read("src/main/java/com/metallum/mtl/MTLDevice.java")
render_encoder = read("src/main/java/com/metallum/mtl/metal3/MTLRenderCommandEncoder.java")
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

require("Metal texture allocation", "src/main/java/com/metallum/render/shared/MetalGpuTexture.java", (
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
require("Native render-pass store/clear", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
    "Vector4fc clearColor = clearColors == null ? null : clearColors[index];",
    "MTLRenderPassDescriptor.LOAD_ACTION_CLEAR",
    "MTLRenderPassDescriptor.STORE_ACTION_STORE",
))
require("Metal draw and direct sampling", "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "enc.setRenderPipelineState(pipelineHandle);",
    "enc.drawPrimitives(primitiveType, firstVertex, vertexCount, instanceCount, firstInstance);",
    "TextureViewAndSampler requested = new TextureViewAndSampler(textureView, sampler);",
    "commandEncoder.flushPendingClear((MetalGpuTexture) textureView.texture());",
    "if (!sameBinding(samplers.put(name, requested), requested)) {",
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
    "setUniform(name, value.slice());",
    "if (!sameSlice(uniforms.put(name, value), value)) {",
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
require("Generic command-buffer present", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
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
    "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java",
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

require("a failed command buffer can be read", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
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

# ---------------------------------------------------------------------------
# P2: a descriptor already holding a value is not set to it again
#
# The vertex and index paths compared their values from the start; the texture and uniform paths marked
# the descriptor dirty on every call, which is a GPU-facing call for a value that has not moved. The
# comparison is deliberately conservative - a buffer slice by its buffer, offset and length, a texture
# view by its texture and mip range, a sampler by identity - because a comparison that is too keen skips
# a call that was needed and the picture changes, while one that is too dull only sets a descriptor
# again. Measured on the pack in the plan, this removes almost nothing (each image is bound about once a
# pass) and it is kept for the surface P5 binds through, not for a number it produced.
# ---------------------------------------------------------------------------
require("a texture binding is compared before the descriptor is marked",
        "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "private static boolean sameBinding(@Nullable final TextureViewAndSampler left,",
    "leftView.texture() == rightView.texture()",
    "leftView.baseMipLevel() == rightView.baseMipLevel()",
    "if (!sameBinding(samplers.put(name, requested), requested)) {",
))
require("a uniform is compared before the descriptor is marked",
        "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "if (!sameSlice(uniforms.put(name, value), value)) {",
))
require("an absent sampler is not marked dirty again",
        "src/main/java/com/metallum/render/MetalRenderPass.java", (
    "if (samplers.remove(name) != null) {",
))

# ---------------------------------------------------------------------------
# P5's first step: Metal 4 is detected, not assumed
#
# Metal 4 is a parallel API surface - MTL4-prefixed types beside the ones in use - so adopting it is a
# runtime choice, and the framework's own guidance is to detect support and fall back. Two rules follow,
# and both are here because guessing either one is how this project has been burned before: the
# availability question is the device's own (`supportsFamily:` with MTLGPUFamilyMetal4, whose value is
# the SDK's 5002 at MTLDevice.h, not a version table), and reaching the new entry point is asked for with
# `respondsToSelector:` because a selector an object does not implement is an Objective-C exception that
# ends the process rather than a nil. The answer is cached, the negative one included, because a session
# cannot change its GPU.
# ---------------------------------------------------------------------------
require("Metal 4's availability is Apple's own question", "src/main/java/com/metallum/render/Metal4.java", (
    "private static final long FAMILY_METAL4 = 5002L;",
    "if (!device.supportsFamily(FAMILY_METAL4)) {",
    'private static final String QUEUE_SELECTOR = "newMTL4CommandQueue";',
    "if (!device.respondsTo(QUEUE_SELECTOR)) {",
    "if (available != null) {",
))
require("the device is the one asked", "src/main/java/com/metallum/mtl/MTLDevice.java", (
    'Msg.of("supportsFamily:", JAVA_LONG, JAVA_LONG)',
    'Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS)',
    "public boolean supportsFamily(final long family) {",
    "public boolean respondsTo(final String name) {",
))
require("it is asked once, at device creation", "src/main/java/com/metallum/render/MetalDevice.java", (
    "Metal4.available(this.metalDevice);",
))

require("Metal 4's answer is advertised, not only logged", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static boolean supportsMetal4CoreApi() {",
    "return Metal4.isAvailable();",
))
require("a capability nobody has asked about is false", "src/main/java/com/metallum/render/Metal4.java", (
    "public static boolean isAvailable() {",
    "return Boolean.TRUE.equals(available);",
))

# ---------------------------------------------------------------------------
# Every Metal 4 selector is asked for before it is sent
#
# Learned the hard way, and it cost a session: the device supports the Metal 4 family and answers to
# `newMTL4CommandQueue`, and it does **not** implement `newCommandAllocatorWithDescriptor:` even though
# this machine's SDK declares it. Sending it raised NSInvalidArgumentException and the process died with
# SIGABRT. A device implements a subset of the factory surface its header describes, so the rule the
# scaler already lived under extends to every selector of the new path - and to the buffer's own
# protocol, which is as much a subset as the device's is.
# ---------------------------------------------------------------------------
require("the Metal 4 factories are asked for before they are sent",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    'device.respondsTo("newMTL4CommandQueue")',
    'device.respondsTo("newCommandAllocator")',
    'device.respondsTo("newCommandAllocatorWithDescriptor:")',
    'device.respondsTo("newCommandBuffer")',
    'responds(buffer, "beginCommandBufferWithAllocator:")',
    'responds(buffer, "endCommandBuffer")',
    'Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS)',
    "public static boolean canMakeAndSubmit(final MTLDevice device) {",
))

require("the Metal 4 submission is proven by the queue's own signal",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    'Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG)',
    'Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG)',
    'Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG)',
    'responds(queue, "commit:count:")',
    'responds(event, "waitUntilSignaledValue:timeoutMS:")',
    "boolean ran = WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) != 0L;",
    'Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS)',
    'Msg.ofVoid("setLoadAction:", JAVA_LONG)',
    'Msg.ofVoid("setStoreAction:", JAVA_LONG)',
    'END_ENCODING.send(encoder);',
    'ObjC.clazz("MTL4RenderPassDescriptor")',
))

# ---------------------------------------------------------------------------
# A blit already open is where the next blit belongs
#
# Every copy method ended its blit encoder on the way out, so consecutive copies could never share one:
# fifteen blit encoders a frame on this pack, measured. Sharing them is worth ten encoders a frame for
# exactly the same bytes moved, and the rule is here because the shape that made it impossible is one line
# at the end of eight methods - the kind of thing a later refactor puts back without noticing.
# ---------------------------------------------------------------------------
require("a blit shares the encoder that is already open",
        "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLBlitCommandEncoder open) {",
    "        // A blit already open is where the next blit belongs.",
))

require("a compute dispatch shares it the same way",
        "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLComputeCommandEncoder open) {",
))
require("a half-bound dispatch is still ended where it was opened",
        "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "boolean bound = false;",
    "if (!bound) {",
    "commandEncoder.endEncoder();",
))

# ---------------------------------------------------------------------------
# The two facts an F3 line and the log both read
#
# Which generation of the Metal API is running, and what the upscaler made of the device. Apple has no
# API version to query, so the generation is the newest family the device answers for; the scaler's
# sentence is the same one it logs. Both are narrow strings on the integration surface, because the
# pack-facing side reads them by reflection and may not see a Metal type.
# ---------------------------------------------------------------------------
require("the API generation is named", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static String metalApiGeneration() {",
))
require("the generation is a family answer, not a version table",
        "src/main/java/com/metallum/render/Metal4.java", (
    "private static final long FAMILY_METAL3 = 5001L;",
    "metal3 = device.supportsFamily(FAMILY_METAL3);",
    'return "Metal 4";',
    'return metal3 ? "Metal 3" : "Metal";',
))
# ---------------------------------------------------------------------------
# The Metal 4 path presents the frame through its own queue, one commit a frame
#
# Apple's order for a Metal 4 game ("Explore Metal 4 games", WWDC25): `nextDrawable`, `waitForDrawable:`,
# encode, `commit:count:`, `signalDrawable:`, `present` - and one command buffer and one commit a frame.
# Three rules are pinned because each of them was learned here: every selector is asked for first (an
# unimplemented one is an Objective-C exception, not a nil), the present is carried out where a frame is
# *committed* rather than where the surface asks (the picture is only the frame's once that commit has
# happened, and a present encoded before it samples a frame that frame has not drawn), and every release
# goes through the guard, because the first version threw a NullPointerException out of its own cleanup and
# took the whole Metal device down with it.
# ---------------------------------------------------------------------------
require("the Metal 4 present is guarded, ordered and carried at the frame boundary",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    "public static boolean start(final MTLDevice device) {",
    'device.respondsTo("newMTL4CommandQueue")',
    'device.respondsTo("newSharedEvent")',
    "public static boolean presenting(final CAMetalLayer layer, final MemorySegment picture) {",
    "public static void presentFrame() {",
    "WAIT_DRAWABLE.send(queue, drawable.handle());",
    "SIGNAL_DRAWABLE.send(queue, drawable.handle());",
    "awaited[slot] = ++signalled;",
    "private static void releaseIfPresent(final @Nullable MemorySegment object) {",
    'System.getProperty("metallum.metal4Frame", "true")',
))
require("the present is carried where a frame is committed",
        "src/main/java/com/metallum/render/MetalCommandEncoder.java", (
    "Metal4Path.presentFrame();",
))

# The two binding shapes a Metal 4 encoder needs, proven at device creation against the engine's own
# pipelines and a pixel read back: a uniform by GPU address, and a vertex buffer by address and stride.
# Without the second one the terrain and entity draws have no way to reach an encoder of the new kind,
# and without the readback a table that was accepted would read the same as a table that was used.
# ---------------------------------------------------------------------------
# Which generation executes, said once, and the feedback a Metal 4 commit is timed by
#
# A run whose log does not name the generation that produced it cannot be compared with another; and a
# Metal 4 queue returns nothing to its caller, so a submission's GPU time exists only in the commit
# feedback - without it, moving work to the new queue makes the frame probe read *faster*.
# ---------------------------------------------------------------------------
require("the executing generation is recorded and said in one line",
        "src/main/java/com/metallum/render/MetalExecutionTelemetry.java", (
    '"Metal execution: {} selected ({})"',
    "public static void selected(final MetalApiGeneration selected, final String why) {",
    "public static String token() {",
))
require("the generations are the two API surfaces and nothing else",
        "src/main/java/com/metallum/render/execution/MetalApiGeneration.java", (
    'METAL3("metal3", "Metal 3")',
    'METAL4("metal4", "Metal 4")',
))
# The selector's rules, and the one input it may not use. A chip name is not a capability: Apple Silicon
# reports the same families across its generations, so a decision keyed off "M4" or "M5" would be a table of
# hardware rather than a question about the device - and it would be wrong on the first chip it had not seen.
# ---------------------------------------------------------------------------
# The shader profile is chosen with the generation, and the two halves of it agree
#
# A session whose translator emits MSL 4.0 while Metal is told to accept 3.2 has pipelines that do not
# compile, or worse, compile into something neither side intended; and a Metal 3 session that emits 4.0
# works on the systems this engine is developed on and fails on the older one the path exists for. So the
# profile is one record with both numbers, it is probed rather than assumed, and it is named in the cache
# identity rather than only implied by the text.
# ---------------------------------------------------------------------------
require("the MSL profile pairs the translator's version with the compiler's",
        "src/main/java/com/metallum/render/execution/MetalShaderLanguageProfile.java", (
    "public record MetalShaderLanguageProfile(int spirvCrossMslVersion, long metalLanguageVersion, String token) {",
    'MSL_3_2 =\n            new MetalShaderLanguageProfile(0x030200, (3L << 16) + 2L, "msl3.2")',
    'MSL_4_0 =\n            new MetalShaderLanguageProfile(0x040000, (4L << 16) + 0L, "msl4.0")',
    "public static final List<MetalShaderLanguageProfile> METAL3_LADDER =",
    "public static void select(final MetalShaderLanguageProfile profile, final String why) {",
))
require("the Metal 3 profile is probed by compiling, newest first",
        "src/main/java/com/metallum/render/execution/MetalShaderLanguageProbe.java", (
    "public static MetalShaderLanguageProfile newestMetal3Profile(final MTLDevice device) {",
    "for (MetalShaderLanguageProfile candidate : MetalShaderLanguageProfile.METAL3_LADDER) {",
    "options.setLanguageVersion(profile.metalLanguageVersion());",
    "NEW_LIBRARY_WITH_SOURCE.sendPtr(device.handle(), source, options.handle(), errorOut)",
))
require("both translators read the session's profile",
        "src/main/java/com/metallum/render/MetalCrossShaderCompiler.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the compute translator reads the same one",
        "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the library is compiled for the profile the translator emitted",
        "src/main/java/com/metallum/mtl/MTLDevice.java", (
    "options.setLanguageVersion(",
    "MetalShaderLanguageProfile.selected().metalLanguageVersion()",
))
require("a compiled function's identity names the profile",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "new MslFunctionKey(msl, entryPoint,",
    "private record MslFunctionKey(String msl, String entryPoint, String profile) {",
    "MetalShaderLanguageProfile.selected().token()",
))
require("the selection is made from capability and said out loud",
        "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java", (
    "public static Decision decide(final MetalExecutionPreference preference,",
    '"metallum.execution=metal4 was asked for, and this device does not satisfy the "',
    "throw new UnsatisfiedPreferenceException(",
    "capabilities.metalFxParityForMetal4()",
    "MetalExecutionTelemetry.selected(decision.selected(), decision.reason());",
))
selector_source = (ROOT / "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java"
                   ).read_text(encoding="utf-8")
for forbidden in ("deviceName", "system().deviceName", 'contains("M1")', 'contains("M4")'):
    if forbidden in selector_source:
        raise SystemExit(
            f"the selector reads {forbidden!r}, and a device name is not a capability: the choice has to come "
            "from the family, the selectors and the probes"
        )
require("the capability record asks every clause of the minimum contract",
        "src/main/java/com/metallum/render/execution/MetalDeviceCapabilities.java", (
    "public boolean metal4MinimumContract() {",
    "public boolean metal3MinimumContract() {",
    "public boolean metalFxParityForMetal4() {",
    "device.supportsFamily(FAMILY_METAL4)",
    "device.respondsTo(\"newMTL4CommandQueue\")",
    'MetalFx.metal4SpatialSupported(device.handle())',
))
require("the services say what executes, not only what was chosen",
        "src/main/java/com/metallum/render/execution/MetalExecutionServices.java", (
    "MetalApiGeneration selected();",
    "MetalApiGeneration executing();",
    "boolean isReferenceShell();",
    "return MetalApiGeneration.METAL3;",
))
require("the preference is one property with three words",
        "src/main/java/com/metallum/render/execution/MetalExecutionPreference.java", (
    'public static final String PROPERTY = "metallum.execution";',
    'AUTO("auto")',
    'FORCE_METAL3("metal3")',
    'FORCE_METAL4("metal4")',
))
require("the device records capabilities and selects once",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "MetalDeviceCapabilities capabilities =",
    "MetalExecutionSelector.say(capabilities);",
    "MetalExecutionSelector.select(MetalExecutionPreference.read(), capabilities);",
))
require("a Metal 4 commit carries the options its feedback arrives through",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    'Msg.ofVoid("commit:count:options:", ADDRESS, JAVA_LONG, ADDRESS)',
    "commitOptions = MTL4CommitOptions.create();",
    "feedbackBlock = ObjCBlock.withConsumer(Metal4Path::reportCommitFeedback);",
    "double millis = MTL4CommitOptions.gpuMillis(feedback);",
    "MetalFrameProbe.gpuFrameMetal4(millis);",
    "if (commitOptions != null) {",
    "commitOptions.feedbackHandler(feedbackBlock);",
    "COMMIT_WITH_OPTIONS.send(queue, buffers, 1L, commitOptions.handle());",
))
require("the feedback object is the only place a Metal 4 submission's timing is read",
        "src/main/java/com/metallum/mtl/metal4/MTL4CommitOptions.java", (
    'Msg.ofVoid("addFeedbackHandler:", ADDRESS)',
    'Msg.of("GPUStartTime", JAVA_DOUBLE)',
    'Msg.of("GPUEndTime", JAVA_DOUBLE)',
    "return (ended - started) * 1000.0;",
))
require("a block can hand its argument to a Java method",
        "src/main/java/com/metallum/objc/ObjCBlock.java", (
    "public static MemorySegment withConsumer(final Consumer<MemorySegment> action) {",
    "private static void invokeConsumer(final Consumer<MemorySegment> action, final MemorySegment block,",
))
require("the Metal 4 binding shapes are proven, not assumed",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    "public static boolean canBindAndDraw(final MTLDevice device) {",
    "uniformBuffer.gpuAddress() == 0L",
    "table.address(uniformBuffer.gpuAddress(), 1L)",
    "verticesTable.address(vertexBuffer.gpuAddress(), 16L, 0L)",
    "MTLTexture.bytes(target, pixel, 4L, 0L, 0L, 1L, 1L);",
    "EXPECTED_VERTEX_PIXEL",
))
# The ceiling question that decides whether every program can move: asked of the compiler rather than
# assumed from the header, because the header's "maximum 16 sampler slots" is not what the runtime
# enforces and the compiler's own limit is what a shader has to live inside.
require("the sampler ceiling is asked of the compiler",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    "public static String samplerCeiling(final MTLDevice device) {",
    "seventeenSamplersMsl()",
    'device.newFunction(ID_SAMPLER_MSL, "probe_id_sampler")',
    "MTL4ArgumentTable.create(device, 0L, 0L, 20L)",
))
require("a buffer's Metal 4 address is asked for rather than assumed",
        "src/main/java/com/metallum/mtl/MTLBuffer.java", (
    'MTL4Probe.respondsTo(handle, "gpuAddress")',
))
require("the argument table is asked for by the selector its header declares",
        "src/main/java/com/metallum/mtl/metal4/MTL4ArgumentTable.java", (
    'device.respondsTo("newArgumentTableWithDescriptor:error:")',
    "NEW_TABLE_WITH_ERROR.sendPtr(device.handle(), descriptor, MemorySegment.NULL)",
    "SET_TEXTURE.send(handle, RESOURCE_ID.sendLong(textureHandle), 0L);",
    "SET_INITIALIZE.send(descriptor, 0L);",
))
require("a missing table is said out loud rather than hidden",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    "not carrying the present, because this device makes",
    "private static boolean refuse(final String why) {",
))

print("Metal and engine contracts: PASS")
