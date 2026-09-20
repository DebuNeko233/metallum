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
encoder = read("src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java")
pipeline = read("src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java")
render_pass = read("src/main/java/com/metallum/render/metal3/MetalRenderPass.java")
compiler = read("src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java")
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
require("Metal render pipeline", "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "ColorTargetState[] colorTargets = info.getColorTargetStates();",
    "pipelineDesc.setColorAttachmentFormat(index, MTLPixelFormat.from(colorTarget.format()));",
    "long writeMask = MTLColorWriteMask.from(colorTarget.writeMask());",
    "pipelineDesc.disableBlending(index, writeMask);",
    "this.cullMode = info.isCull() ? MTLCullMode.Back : MTLCullMode.None;",
    "depthCompareOp = MTLCompareFunction.from(depthStencilState.depthTest());",
    "depthWrite = depthStencilState.writeDepth() ? 1 : 0;",
))
require("Metal MRT encoder", "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
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
require("Metal draw and direct sampling", "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "enc.setRenderPipelineState(pipelineHandle);",
    "enc.drawPrimitives(primitiveType, firstVertex, vertexCount, instanceCount, firstInstance);",
    "TextureViewAndSampler requested = new TextureViewAndSampler(textureView, sampler);",
    "commandEncoder.flushPendingClear((MetalGpuTexture) textureView.texture());",
    "if (!sameBinding(samplers.put(name, requested), requested)) {",
    "markDescriptorDirty(name);",
    "if (binding.kind() == MetalResourceBinding.ResourceKind.SAMPLED_IMAGE) {",
    "bindTextureAndSampler(enc, textureView.nativeHandle(), sampler.nativeHandle(), binding.bindingIndex(), binding.stageMask());",
    "enc.setFragmentTexture(texture, index);",
    "enc.setFragmentSamplerState(sampler, index);",
))
require("Direct/wide resource numbering", "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
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

require("Generic carried vertex ABI", "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
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
    "MetalResourceBinding",
    "if (format == null || format.getElements().isEmpty()) {",
))
require("Generic vertex/resource binding", "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "int firstSlot = compiledPipeline.firstAvailableVertexBufferSlot();",
    "int count = compiledPipeline.vertexBufferCount();",
    "int metalSlot = firstSlot + slot;",
    "enc.setVertexBuffer(nativeVertexBuffer.metalBuffer(), vertexBuffer.offset(), metalSlot);",
    "public void bindTexture(final @NonNull String name",
    "bindTexture(enc, textureView.nativeHandle(), binding.bindingIndex(), binding.stageMask());",
    "public void setUniform(final @NonNull String name, final GpuBuffer value)",
    "setUniform(name, value.slice());",
    "if (!sameSlice(uniforms.put(name, value), value)) {",
    "if (binding.kind() == MetalResourceBinding.ResourceKind.TEXEL_BUFFER)",
    "pushDirectTexelBufferDescriptor(enc, binding);",
    "private MemorySegment createTexelBufferTexture(",
    "GpuBufferSlice texelSlice = requiredBuffer(binding);",
    "private GpuBufferSlice requiredBuffer(",
    "GpuFormat texelFormat = binding.texelBufferFormat();",
    "MTLTexture.newBufferTextureView(",
))
require("Triangle-fan conversion", "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
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

require("Generic texture copy/mipmap", "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
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
require("Composite render/blit fences", "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "encoder.waitForFence(fence);",
    "blitEncoder.updateFence(fence);",
    "renderEncoder.updateFence(fence, MTLRenderStages.VertexAndFragment);",
    "encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);",
))
require("Generic D32 mip bridge", "src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java", (
    "texture.getFormat() != GpuFormat.D32_FLOAT",
    "GpuTexture.USAGE_TEXTURE_BINDING",
    "GpuTexture.USAGE_RENDER_ATTACHMENT",
    "depth2d<float> source [[texture(0)]]",
    "source.sample(nearestSampler, in.uv)",
    "descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);",
    "descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);",
    "descriptor.mipFilter(MTLSamplerMipFilter.NotMipmapped);",
    "descriptor.setDepthStencilFormats(MTLPixelFormat.Depth32Float, MTLPixelFormat.Invalid);",
    "metal3.depthStencilState(MTLCompareFunction.Always, true)",
    "new MetalGpuTextureView(texture, level - 1, 1)",
    "new MetalGpuTextureView(texture, level, 1)",
    "render.setFragmentTexture(source.nativeHandle(), 0L);",
    "render.drawPrimitives(MTLPrimitiveType.Triangle, 0, 3, 1, 0);",
    "encoder.endEncoder();",
))
depth_bridge = read("src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java")
forbid("Depth mip bridge shader-pack neutrality", depth_bridge.lower(), ("shadowtex0", "shadowtex1", "shadowcolor0", "shadowcolor1", "shader pack"))
if "MetalDevice device()" not in texture:
    raise SystemExit("MetalGpuTexture must expose its device package-locally for generic depth mip generation")
forbid("Depth semantics in Metallum", backend, ("depthtex0", "depthtex1", "depthtex2", "pre-translucent", "pre-hand", "Vitrail depth window"))
forbid("Shadow semantics in Metallum", backend, ("shadow_entities", "shadowtex0", "shadowtex1", "shadowcolor0", "shadowcolor1", "shadow_solid", "shadow_cutout", "shadow_water"))
forbid("Deferred fixture semantics in Metallum", backend, ("deferred-mrt-contract", "deferred-mipmap-contract", "colortex0mipmapenabled"), lower=True)

require("Generic Final present entry", "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "void presentTextureToDrawable(final CAMetalLayer layer, final GpuTextureView textureView)",
    "flushPendingClear(source);",
    "submitRenderPass();",
    "commandBuffer.encodePresentTextureToDrawable(layer, source.nativeHandle(), fence);",
))
require("Generic command-buffer present", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
    "private static final Msg PRESENT_DRAWABLE = Msg.ofVoid(\"presentDrawable:\", ADDRESS);",
    "public MemorySegment encodePresentTextureToDrawable(final CAMetalLayer layer, final MemorySegment sourceTexture,",
    "PRESENT_DRAWABLE.send(handle(), drawable.handle());",
))
require("Generic CAMetalLayer presentation", "src/main/java/com/metallum/mtl/MTLBuiltinPipelines.java", (
    "CAMetalDrawable drawable = layer.nextDrawable();",
    # The drawable is valid for the command buffer that took it, so the helper answers it: a diagnostic that
    # wants to read what was presented can only do so from here.
    "public static MemorySegment encodePresentTextureToDrawable(",
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
    "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java",
    "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java",
    "src/main/java/com/metallum/mtl/MTLBuiltinPipelines.java",
))
forbid("Dimension routing semantics in Metallum", dimension_sources, (
    "dimension-convention-contract", "dimension-properties-contract", "dimension.properties",
    "world0", "world-1", "world1", "minecraft:the_nether", "minecraft:the_end", "vitrail:moon",
), lower=True)

require("Wide resource compiler", "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
    "DIRECT_SAMPLER_LIMIT = 16",
    "lastSamplerSlot >= DIRECT_SAMPLER_LIMIT",
    "requires wide Metal resources, but Argument Buffer Tier 2 is unavailable",
    "SpvcMslResourceBinding",
    "SPVC_MSL_ARGUMENT_BUFFER_BINDING",
))
# The capability question belongs to the Metal 3 compiler now: the translator is handed the answer, which is
# what keeps MTLDevice out of it. Pinned separately so the split cannot quietly put the query back.
require("the argument-buffer capability is asked by the Metal 3 compiler",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "compilation.device().supportsArgumentBuffersTier2()",
    "boolean argumentBuffersTier2 = ",
))
require("Wide resource pipeline", "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "private final BitSet allResources;",
    "uses Metal Argument Buffers: resources={}, sampledImages={}",
    "maxArgumentBufferSamplerCount()",
    "createArgumentBuffers(",
    "WIDE_VERTEX_BUFFER_BASE",
))
require("Wide resource draw routing", "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
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

# ---------------------------------------------------------------------------
# The mixin surface: two rules, and both were paid for.
#
# The mixin config names the classes Mixin may transform, and the config plugin is a second gate over them - a
# mixin in the config that the plugin does not name is never applied, silently: the session runs, the property
# has no effect, and the log carries no line to say why. That cost a measurement round, so the two lists have to
# agree.
#
# The second rule is the one that cost a build. Mixin transforms every class in its configured package, so a
# plain helper placed beside a mixin rather than inside it ends in
# `ExceptionInInitializerError: Mixin transformation of ... failed` before the client loads. Every source file
# under the mixin package therefore has to be a mixin the config names - there is no such thing as a non-mixin
# class in that package.
# ---------------------------------------------------------------------------
import json as _json  # noqa: E402  (the rules above do not need it; this one reads a config)

mixin_config = _json.loads(
    (ROOT / "src/main/resources/metallum.mixins.json").read_text(encoding="utf-8")
)
declared = {name.rsplit(".", 1)[-1] for name in mixin_config.get("client", []) + mixin_config.get("mixins", [])}
# The plugin is in the package and is not a mixin: the config names it as its `plugin`, which is how Mixin reads
# it too, so it is the one file beside the mixins that is allowed not to be one.
plugin_class = str(mixin_config.get("plugin", "")).rsplit(".", 1)[-1]
mixin_root = ROOT / "src/main/java/com/metallum/mixin"
mixin_sources = sorted(path for path in mixin_root.rglob("*.java"))
unlisted = [path.name for path in mixin_sources if path.stem not in declared and path.stem != plugin_class]
if unlisted:
    raise SystemExit(
        "the mixin package holds source files that are not mixins the config names, so Mixin would transform "
        "them and the client would fail to load: " + ", ".join(unlisted)
    )
for name in sorted(declared):
    if not any(path.stem == name for path in mixin_sources):
        raise SystemExit(f"the mixin config names {name}, which no source file in the mixin package provides")

plugin_source = read("src/main/java/com/metallum/mixin/MetallumMixinConfigPlugin.java")
# Admission is read as the plugin's own code and not as the presence of a string: naming a constant whose value
# holds the mixin's class name is not admitting it, and that was the first version of this rule's mistake - a
# plugin that declares `LIFECYCLE_PROBE_MIXIN = "com.metallum.mixin.render.LifecycleProbeMixin"` and then never
# compares it still contains the name.
plugin_constants = dict(re.findall(r'String\s+(\w+)\s*=\s*\n?\s*"([\w.]+)"', plugin_source))
admitted = {
    constant
    for constant, qualified in plugin_constants.items()
    if f"{constant}.equals(mixinClassName)" in plugin_source
}
configured = mixin_config.get("client", []) + mixin_config.get("mixins", [])
for entry in configured:
    name = entry.rsplit(".", 1)[-1]
    group = entry.rsplit(".", 2)[-2] if "." in entry else ""
    by_constant = any(
        constant in admitted and qualified.rsplit(".", 1)[-1] == name
        for constant, qualified in plugin_constants.items()
    )
    # The sodium diagnostics are admitted as one group, by a `contains` test on the package they sit in - and the
    # test itself is what is looked for, because the constant declarations also spell `.mixin.render.` out and a
    # rule that accepted that would admit every mixin in the package it names.
    by_group = bool(group) and f'mixinClassName.contains(".mixin.{group}.")' in plugin_source
    if by_constant or by_group:
        continue
    raise SystemExit(
        f"the mixin config names {entry} and the config plugin admits neither {name} nor the {group} group, so "
        "it is configured but never applied - and the failure is silent"
    )

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
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "private long lastCommittedSubmitIndex = -1L;",
    "lastCommittedSubmitIndex = currentSubmitIndex;",
    "awaitSubmitCompletion(lastCommittedSubmitIndex, Long.MAX_VALUE);",
))
forbid("the wait no longer derives its index from the submit counter",
       read("src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java"),
       ("currentSubmitIndex - 1L",))

require("a failed command buffer can be read", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
    'Msg.of("error", ADDRESS)',
    "public String errorDescription()",
))
require("the frame says when a command buffer failed",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
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
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "private static boolean sameBinding(@Nullable final TextureViewAndSampler left,",
    "leftView.texture() == rightView.texture()",
    "leftView.baseMipLevel() == rightView.baseMipLevel()",
    "if (!sameBinding(samplers.put(name, requested), requested)) {",
))
require("a uniform is compared before the descriptor is marked",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "if (!sameSlice(uniforms.put(name, value), value)) {",
))
require("an absent sampler is not marked dirty again",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
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
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLBlitCommandEncoder open) {",
    "        // A blit already open is where the next blit belongs.",
))

require("a compute dispatch shares it the same way",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLComputeCommandEncoder open) {",
))
require("a half-bound dispatch is still ended where it was opened",
        "src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java", (
    "boolean bound = false;",
    "if (!bound) {",
    "commandEncoder.endEncoder();",
))

# ---------------------------------------------------------------------------
# The two questions an F3 line reads, and they are two questions
#
# "Which API is running" and "which API could the device run" are different facts, and one name answering
# both is what put "Metal 4" on the F3 screen of a session encoding every frame through Metal 3's command
# buffer. So the integration surface carries both, named for which one each answers: `metalApiGeneration()`
# is the executing one - read off the telemetry the device records, never off the family probe - and
# `deviceMetalApiGeneration()` is the hardware's newest family. Apple has no API version to query, and the
# upscaler's sentence is the same one it logs. All of them are narrow strings, because the pack-facing side
# reads them by reflection and may not see a Metal type.
# ---------------------------------------------------------------------------
require("the API generation in use is named", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static String metalApiGeneration() {",
    "MetalApiGeneration executing = MetalExecutionTelemetry.executing();",
    "return executing == null ? \"\" : executing.label();",
))
require("what the device could run is a separate answer", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static String deviceMetalApiGeneration() {",
    "return Metal4.generation();",
))
require("the generation is a family answer, not a version table",
        "src/main/java/com/metallum/render/Metal4.java", (
    "private static final long FAMILY_METAL3 = 5001L;",
    "metal3 = device.supportsFamily(FAMILY_METAL3);",
    'return "Metal 4";',
    'return metal3 ? "Metal 3" : "Metal";',
))
# And the executing fact may not be sourced from the hardware probe again: this is the regression, stated as
# a rule, because the two readings differ on exactly the machine this engine is developed on.
_api_text = read("src/main/java/com/metallum/api/MetallumApi.java")
_in_use_body = _api_text.split("public static String metalApiGeneration() {", 1)[1].split("}", 1)[0]
if "Metal4.generation()" in _in_use_body:
    raise SystemExit(
        "the generation in use is answered from the device's family probe, which is a different question: "
        "that is what reported Metal 4 for a session whose every frame is Metal 3's"
    )
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
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "presentGate.afterCommit();",
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
require("the selected and executing generations are recorded as two facts and said in one line",
        "src/main/java/com/metallum/render/MetalExecutionTelemetry.java", (
    '"Metal execution: {} selected, {} executes ({})"',
    "public static void record(final MetalApiGeneration selected, final MetalApiGeneration executing,",
    "public static MetalApiGeneration executing() {",
    "public static MetalApiGeneration selected() {",
    "public static String executingToken() {",
))
# One field for two facts is the fault, stated as a rule: the selector decides and cannot know what executes,
# so the record is written where both are known, and it is the device that holds the executing generation.
_selector_text = read("src/main/java/com/metallum/render/execution/MetalExecutionSelector.java")
forbid("the selector does not write the session's record", _selector_text, (
    "MetalExecutionTelemetry.selected(",
    "MetalExecutionTelemetry.record(",
))
require("the device records both, where both are known",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "MetalExecutionTelemetry.record(decision.selected(), this.services.executing(), decision.reason());",
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
        "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the compute translator reads the same one",
        "src/main/java/com/metallum/render/shared/MetalComputeTranslator.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the library is compiled for the profile the translator emitted",
        "src/main/java/com/metallum/mtl/MTLDevice.java", (
    "options.setLanguageVersion(",
    "MetalShaderLanguageProfile.selected().metalLanguageVersion()",
))
require("a compiled function's identity names the profile",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "new MslFunctionKey(msl, entryPoint,",
    "private record MslFunctionKey(String msl, String entryPoint, String profile) {",
    "MetalShaderLanguageProfile.selected().token()",
))
require("the selection is made from capability and nothing else",
        "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java", (
    "public static Decision decide(final MetalExecutionPreference preference,",
    '"metallum.execution=metal4 was asked for, and this device does not satisfy the "',
    "throw new UnsatisfiedPreferenceException(",
    "capabilities.metalFxParityForMetal4()",
    # The selector decides; the record of what executes is written where both facts are known. A selector
    # that writes it is a selector that can only write the selection - which is the fault this pins.
    "return decide(preference, capabilities);",
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
    # The Metal 4 scaler's clause is the Metal 4 path's own question, and a functional one: the class
    # question plus a scaler actually made with a compiler and released. It is not Metal 3's answer and not
    # Metal 3's object - section 80 - and the record asks it because the answer decides whether choosing
    # Metal 4 would cost the player the render-scale setting.
    'Metal4Fx.supported(device.handle())',
))
# The device used to make its own Metal 3 queue, and that one line is what made "the device belongs to
# shared" impossible to write down. The queue now comes through the execution services, whose first consumer
# this is; the handle crosses as an address rather than as a wrapper class, so a version-neutral interface
# never names a generation's type.
# M2: a translated module belongs to one MSL profile. The function cache always named the profile; the module
# cache did not, which made the reuse of a Metal 3 module by a Metal 4 session a thing that merely did not
# happen rather than a thing that could not. Both halves are pinned, because a key that forgot the profile again
# would compile cleanly and pass every other test in this file.
# M2: no compilation artifact may be reused across MSL profiles. The module and function caches name the profile
# in their keys; the pipeline cache cannot (its key is the game's pipeline identity, deliberately), so it is
# guarded on every hit instead. Pinned because the guard is one comparison that no other test would notice losing.
# M3 step B/C: the frame's encoder is known as a contract, and that contract carries no generation type. The
# interface is pinned against the four members the device needs and against the game interface it extends, and the
# device is pinned against naming the concrete class in its field and in the accessor it hands out.
require("the frame's encoder is held as a neutral contract, not as a class",
        "src/main/java/com/metallum/render/shared/MetalFrameEncoder.java", (
    "public interface MetalFrameEncoder extends CommandEncoderBackend {",
    "void writeToBuffer(final GpuBufferSlice destination, final ByteBuffer data);",
    "void waitForSubmittedGpuWork();",
    "void queueForDestroy(final Runnable destroyAction);",
))
require("the device hands out the frame encoder as that contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "private final MetalFrameEncoder commandEncoder;",
    "public @NonNull MetalFrameEncoder createCommandEncoder() {",
))
require("a compiled pipeline is recompiled when its profile is not the session's",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private MetalCompiledRenderPipeline compiledFor(final RenderPipeline pipeline, final ShaderSource source) {",
    "held.pipelineKey().shaderProfile().equals(MetalShaderLanguageProfile.selected().token())",
    "this.compiledPipelines.remove(pipeline);",
    "this.retirement.retire(held);",
))
require("a translated shader module is keyed by its MSL profile",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private static final Pattern GLSL_ERROR_LINE",
    "private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines,",
    "String shaderProfile) {",
    "new ShaderCompilationKey(id, type, defines,",
    "MetalShaderLanguageProfile.selected().token());",
    "synchronized void clearShaderCache() {",
    "this.shaderCache.values().forEach(IntermediaryShaderModule::close);",
))
# M3 seam: what a generation's encoder may ask the device. MetalCommandEncoder read these through package
# access, which is why moving it needed widening; the contract says what it may ask instead.
require("the translator knows no generation type",
        "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
    "public static TranslatedRenderPipeline translate(",
    "TranslatedRenderPipeline(",
    "MetalShaderStages.VERTEX",
    "layout.pushConstantSlot()",
    "layout.argumentBufferSlotCount()",
))
import pathlib as _p

_root = _p.Path(__file__).resolve().parent.parent
_translator = (_root / "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java").read_text(encoding="utf-8")
for _forbidden in ("Metal3CompilationContext", "MetalCompiledRenderPipeline", "MetalDevice",
                   "MetalCommandEncoder", "com.metallum.mtl.metal3", "MTLCommand"):
    if _forbidden in _translator:
        raise SystemExit(f"the translator still names {_forbidden}")

require("the Metal 3 compiler owns lookup, translation, key and artifact",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX,",
    "compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT,",
    "compilation.device().supportsArgumentBuffersTier2()",
    "MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, argumentBuffersTier2)",
    "new TranslationLayout(PUSH_CONSTANT_SLOT, ARGUMENT_BUFFER_SLOT_COUNT)",
    "new MetalCompiledRenderPipeline(",
))
require("the cache miss path asks the Metal 3 compiler",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "pipeline, p -> Metal3PipelineCompiler.compile(this, p, source));",
))
require("the translation result carries every field a pipeline needs",
        "src/main/java/com/metallum/render/shared/TranslatedRenderPipeline.java", (
    "String vertexMsl,", "String fragmentMsl,", "String vertexEntryPoint,", "String fragmentEntryPoint,",
    "List<MetalResourceBinding> resources,", "boolean usesArgumentBuffers,",
    "Set<Integer> vertexArgumentBufferSets,", "Set<Integer> fragmentArgumentBufferSets",
))
# stage masks are shared vocabulary; the two binding slots are Metal 3 layout policy and live with the compiler.
require("the stage masks are shared vocabulary",
        "src/main/java/com/metallum/render/shared/MetalShaderStages.java", (
    "public static final int VERTEX = 1;", "public static final int FRAGMENT = 2;",
    "public static final int ALL = VERTEX | FRAGMENT;",
))
_m3c = (_root / "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java").read_text(encoding="utf-8")
_art = (_root / "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java").read_text(encoding="utf-8")
for _const in ("PUSH_CONSTANT_SLOT", "ARGUMENT_BUFFER_SLOT_COUNT"):
    if _const not in _m3c:
        raise SystemExit(f"the Metal 3 layout policy {_const} is not the compiler's")
if "ARGUMENT_BUFFER_SLOT_COUNT" in _art or "PUSH_CONSTANT_BUFFER_SLOT" in _art:
    raise SystemExit("a Metal 3 binding slot is still declared on the compiled artifact")

require("an encoder answers for the state it was handed",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "Metal3ExecutionState executionState() {",
    "return this.executionState;",
))
require("the depth bridge asks the encoder, not the device",
        "src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java", (
    "Metal3ExecutionState metal3 = encoder.executionState();",
))
import pathlib as _dp
import re as _dr

_root5 = _dp.Path(__file__).resolve().parent.parent


def _code5(path):
    text = (_root5 / path).read_text(encoding="utf-8")
    text = _dr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _dr.sub(r"//[^\n]*", "", text)
    return _dr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


if "device.executionState()" in _code5("src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java"):
    raise SystemExit("the depth bridge still reaches the device for the execution state")

# One caller cannot be rerouted and is allowed by name: compute bridge compile(Object backend, ...) holds the
# device, not an encoder, so the device accessor stays until the bridge's body moves into render.metal3.
# The accessor's one caller is the flat facade now: the implementation takes the state as a parameter.
_compute = _code5("src/main/java/com/metallum/render/MetalComputeBridge.java")
if _compute.count("device.executionState()") != 1:
    raise SystemExit("the compute bridge's use of the device accessor changed shape")

require("the device holds the generation state as the shared contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "private final MetalExecutionState executionState;",
    "MetalExecutionState executionState() {",
    "this.executionState = this.services.createExecutionState(this.metalDevice);",
    "this.commandEncoder = this.services.createFrameEncoder(this, this.executionState, this.defaultShaderSource);",
    "this.executionState.clearCachesAfterGpuCompletion();",
))
import pathlib as _wp
import re as _wr

_root4 = _wp.Path(__file__).resolve().parent.parent


def _code4(path):
    text = (_root4 / path).read_text(encoding="utf-8")
    text = _wr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _wr.sub(r"//[^\n]*", "", text)
    return _wr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


_dev4 = _code4("src/main/java/com/metallum/render/MetalDevice.java")
for _forbidden in ("Metal3ExecutionState", "Metal3CompilationContext", "Metal3PipelineRetirement",
                   "MetalCompiledRenderPipeline", "new MetalCommandEncoder("):
    if _forbidden in _dev4:
        raise SystemExit(f"the device still names {_forbidden}")
for _gone in ("synchronized MetalCompiledRenderPipeline getOrCompilePipeline(",
              "synchronized MemorySegment getOrCompileFunction(", "synchronized MemorySegment depthStencilState("):
    if _gone in _dev4:
        raise SystemExit(f"a Metal 3 migration delegate is still on the device: {_gone}")

# The factory is the only public construction seam, and its signatures are neutral.
_factory = _code4("src/main/java/com/metallum/render/metal3/Metal3ExecutionFactory.java")
for _leak in ("Metal3ExecutionState createState", "MetalCommandEncoder createFrameEncoder",
              "Metal3CompilationContext create", "Metal3PipelineRetirement create"):
    if _leak in _factory:
        raise SystemExit(f"the generation factory hands out an implementation type: {_leak}")
for _needed in ("MetalExecutionState createState(final MTLDevice device)",
                "MetalFrameEncoder createFrameEncoder(final MetalDevice device,",
                "final MetalExecutionState executionState,"):
    if _needed not in _factory:
        raise SystemExit(f"the generation factory signature changed shape: {_needed}")

# The services select a generation factory; they no longer construct the frame implementation.
_services = _code4("src/main/java/com/metallum/render/execution/MetalExecutionServices.java")
if "MetalCommandEncoder" in _services:
    raise SystemExit("the execution services still name the Metal 3 frame encoder")

require("the render pass compiles through the state it was given",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "this.executionState = executionState;",
    "this.defaultShaderSource = defaultShaderSource;",
    "this.executionState.getOrCompilePipeline(pipeline, this.defaultShaderSource);",
))
for _bridge in ("src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java",
                "src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java"):
    _src = _code4(_bridge)
    for _gone in ("device.getOrCompileFunction", "device.depthStencilState"):
        if _gone in _src:
            raise SystemExit(f"{_bridge} still reaches the device for {_gone}")

require("the frame-resource capability is generation-neutral vocabulary",
        "src/main/java/com/metallum/render/shared/MetalFrameResourceCommands.java", (
    "public interface MetalFrameResourceCommands {",
    "boolean generateMipmaps(GpuTexture texture);",
    "boolean clearStorageTexture(GpuTexture texture, int dimensions);",
    "boolean copyStorageTextureRegion(",
))
require("the flat frame bridge reaches implementations only through capabilities",
        "src/main/java/com/metallum/render/MetalFrameBridge.java", (
    "public static boolean supports(final @Nullable Object encoder) {",
    "return encoder instanceof MetalFrameResourceCommands;",
    "return encoder instanceof MetalFrameResourceCommands commands && commands.generateMipmaps(texture);",
    "commands.copyStorageTextureRegion(source, destination, sourceX, sourceY, sourceZ,",
))
import pathlib as _fp2
import re as _fr2

_root7 = _fp2.Path(__file__).resolve().parent.parent


def _code7(path):
    text = (_root7 / path).read_text(encoding="utf-8")
    text = _fr2.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _fr2.sub(r"//[^\n]*", "", text)
    return _fr2.sub(r'"(?:\\.|[^"\\])*"', '""', text)


for _facade in ("MetalFrameBridge", "MetalAttachmentBridge", "MetalComputeBridge", "MetalDepthMipmapBridge"):
    _src = _code7(f"src/main/java/com/metallum/render/{_facade}.java")
    for _forbidden in ("render.metal3", "render.metal4", "mtl.metal3", "mtl.metal4"):
        if _forbidden in _src:
            raise SystemExit(f"the flat {_facade} names {_forbidden}")

require("the Metal 3 encoder answers the resource capabilities it owns",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "MetalFrameResourceCommands, MetalFrameDepthMipmaps, MetalFrameComputeCommands {",
    "public boolean generateDepthMipmaps(final GpuTexture texture) {",
    "public boolean dispatchCompute(final Object pipeline,",
    "Metal3ComputeBridge.dispatch(this, pipeline, buffers, textures, samplers,",
))

# One compute translation, not one per generation: the bridge that dispatches keeps the encoder half and the
# shared layer keeps the SPIR-V half, so a second copy of the reflection growing back here is the fault. The
# needle is the SPIRV-Cross entry point every copy of that code has to call, and comments cannot satisfy it
# because the scan reads the source with them stripped.
_compute_bridge_source = _code7("src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java")
if "spvc_context_create" in _compute_bridge_source:
    raise SystemExit("the Metal 3 compute bridge has grown its own SPIRV-Cross reflection back")

require("the flat compute facade is neutral and forwards",
        "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "public static Object compile(final Object backend, final String label, final ByteBuffer spirv) {",
    "if (!(device.executionState() instanceof MetalComputeCompiler compiler)) {",
    "return compiler.compileCompute(device, label, spirv);",
    "return encoderBackend instanceof MetalFrameComputeCommands commands",
    "commands.dispatchCompute(pipelineResource, buffers, textures, samplers,",
    "if (pipelineResource instanceof MetalComputePipelineResource resource) {",
))
require("the flat depth-mipmap facade is neutral and forwards",
        "src/main/java/com/metallum/render/MetalDepthMipmapBridge.java", (
    "public static boolean generate(final Object encoderBackend, final GpuTexture texture) {",
    "return encoderBackend instanceof MetalFrameDepthMipmaps depth && depth.generateDepthMipmaps(texture);",
))
import pathlib as _fp
import re as _fr

_root6 = _fp.Path(__file__).resolve().parent.parent


def _code6(path):
    text = (_root6 / path).read_text(encoding="utf-8")
    text = _fr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _fr.sub(r"//[^\n]*", "", text)
    return _fr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


# The facades keep the API and nothing else: the ledger counts names, these check the files themselves, so a
# generation name that the ledger happens to allow still fails here.
for _facade, _forbidden in (
        ("src/main/java/com/metallum/render/MetalComputeBridge.java",
         ("MetalCommandEncoder", "Metal3ExecutionState", "MTLComputeCommandEncoder", "MTLCommandBuffer",
          "com.metallum.mtl.metal3")),
        ("src/main/java/com/metallum/render/MetalDepthMipmapBridge.java",
         ("MetalCommandEncoder", "Metal3ExecutionState", "MTLRenderCommandEncoder", "com.metallum.mtl.metal3")),
):
    _src = _code6(_facade)
    for _name in _forbidden:
        if _name in _src:
            raise SystemExit(f"{_facade} names {_name}; a flat facade must not know the generation")

# The cluster lives under render.metal3, and the flat paths are gone: a half-move that left a file behind would
# otherwise compile from two places at once.
for _name in ("Metal3ExecutionFactory", "Metal3ExecutionState", "Metal3CompilationContext",
              "Metal3PipelineRetirement", "Metal3PipelineCompiler", "MetalCompiledRenderPipeline",
              "MetalCommandEncoder", "MetalRenderPass"):
    if not (_root6 / f"src/main/java/com/metallum/render/metal3/{_name}.java").is_file():
        raise SystemExit(f"{_name} is not under render.metal3")
    if (_root6 / f"src/main/java/com/metallum/render/{_name}.java").is_file():
        raise SystemExit(f"{_name} still exists in the flat package as well")

require("the shared execution boundary has four operations",
        "src/main/java/com/metallum/render/shared/MetalExecutionState.java", (
    "public interface MetalExecutionState extends AutoCloseable {",
    "CompiledRenderPipeline getOrCompilePipeline(RenderPipeline pipeline, ShaderSource source);",
    "List<RenderPipeline> evictCachedPipelines(Predicate<RenderPipeline> predicate);",
    "void clearCachesAfterGpuCompletion();",
    "void close();",
))
import pathlib as _bp
import re as _re

_root3 = _bp.Path(__file__).resolve().parent.parent


def _code(path):
    """The file's code with comments and strings removed: a leak in prose is not a leak."""
    text = (_root3 / path).read_text(encoding="utf-8")
    text = _re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _re.sub(r"//[^\n]*", "", text)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


_boundary = _code("src/main/java/com/metallum/render/shared/MetalExecutionState.java")
for _forbidden in ("Metal3", "Metal4", "MTL", "MemorySegment", "MetalCompiledRenderPipeline",
                   "Metal3CompilationContext", "Metal3PipelineRetirement", "MetalCommandEncoder",
                   "MetalRenderPass"):
    if _forbidden in _boundary:
        raise SystemExit(f"the shared execution boundary names {_forbidden} in code")

require("the Metal 3 aggregate implements the boundary without widening its internals",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java", (
    "final class Metal3ExecutionState implements MetalExecutionState, MetalComputeCompiler {",
    "public MetalCompiledRenderPipeline getOrCompilePipeline(",
    "public List<RenderPipeline> evictCachedPipelines(",
    "public void clearCachesAfterGpuCompletion() {",
    "public void close() {",
))
_state_code = _code("src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java")
for _forbidden in ("public MemorySegment getOrCompileFunction", "public MemorySegment depthStencilState",
                   "public IntermediaryShaderModule getOrCompileShader"):
    if _forbidden in _state_code:
        raise SystemExit(f"the boundary widened an implementation internal: {_forbidden}")

# The shader module delegate is dead: the compiler asks the context directly, and nothing else asks anyone.
for _path in ("src/main/java/com/metallum/render/MetalDevice.java",
              "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java"):
    if "getOrCompileShader(" in _code(_path):
        raise SystemExit(f"{_path} still carries the shader module delegate")
require("shader module lookup happens where the modules are",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX,",
    "compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT,",
))

require("the Metal 3 execution aggregate owns the compilation state and the retirement queue",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java", (
    "private final Metal3PipelineRetirement retirement = new Metal3PipelineRetirement();",
    "private final Metal3CompilationContext compilation;",
    "this.compilation = new Metal3CompilationContext(device, this.retirement);",
    "void clearCachesAfterGpuCompletion() {",
    "void close() {",
))
import pathlib as _pp

_root2 = _pp.Path(__file__).resolve().parent.parent
_dev2 = (_root2 / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
for _forbidden in ("Metal3CompilationContext compilation", "Metal3PipelineRetirement retirement",
                   "this.compilation", "this.retirement"):
    if _forbidden in _dev2:
        raise SystemExit(f"the device still owns {_forbidden}; it belongs to Metal3ExecutionState")

# Exactly one construction of each: the aggregate makes them, nobody else does.
_sources = "\n".join(p.read_text(encoding="utf-8")
                     for p in (_root2 / "src/main/java").rglob("*.java"))
if _sources.count("new Metal3PipelineRetirement()") != 1:
    raise SystemExit("Metal3PipelineRetirement is constructed somewhere other than the aggregate")
if _sources.count("new Metal3CompilationContext(") != 1:
    raise SystemExit("Metal3CompilationContext is constructed somewhere other than the aggregate")

require("the active pipeline cache belongs to the compilation context",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private final Map<RenderPipeline, MetalCompiledRenderPipeline> compiledPipelines = new IdentityHashMap<>();",
    "synchronized MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {",
    "synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {",
    "synchronized void clearActivePipelines() {",
    "this.retirement.retire(entry.getValue());",
))
# The ownership is a negative fact as much as a positive one: the device must not keep the active cache, and the
# teardown order is control flow, not the presence of three lines - a frame-probe contract already showed that
# presence is not order.
import pathlib as _pathlib

_root = _pathlib.Path(__file__).resolve().parent.parent
_dev = (_root / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
_ctx = (_root / "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java").read_text(encoding="utf-8")
_ret = (_root / "src/main/java/com/metallum/render/metal3/Metal3PipelineRetirement.java").read_text(encoding="utf-8")

if "compiledPipelines = new IdentityHashMap" in _dev:
    raise SystemExit("the active pipeline cache is declared on MetalDevice as well as on the context")

_state = (_root / "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java").read_text(encoding="utf-8")
# The device waits, then hands over: the wait must come first, and the aggregate must not know how to wait.
if _dev.index("this.waitForSubmittedGpuWork();") > _dev.index("this.executionState.clearCachesAfterGpuCompletion();"):
    raise SystemExit("clearPipelineCache releases the caches before the GPU wait")

_order = (
    "this.retirement.releaseRetired();",
    "this.compilation.clearActivePipelines();",
    "this.compilation.clearShaderCache();",
    "this.compilation.clearFunctionCache();",
)
_positions = [_state.index(_line) for _line in _order]
if _positions != sorted(_positions):
    raise SystemExit(
        "the aggregate no longer releases in the order retired, active, shaders, functions: "
        + str(list(zip(_order, _positions)))
    )
for _forbidden in ("waitForSubmittedGpuWork", "MetalCommandEncoder", "MetalFrameEncoder"):
    if _forbidden in _state:
        raise SystemExit(f"the Metal 3 execution aggregate must not know about {_forbidden}")
for _forbidden in ("Metal4", "MTL4", "Metal4PresentGate", "Metal4Path"):
    if _forbidden in _state:
        raise SystemExit(f"the Metal 3 execution aggregate must not know about {_forbidden}")

for _forbidden in ("waitForSubmittedGpuWork", "MetalCommandEncoder", "MetalFrameEncoder", "MetalDevice"):
    if _forbidden in _ret:
        raise SystemExit(f"the retirement owner must not know about {_forbidden}")

require("the pipeline cache asks the artifact one question through a contract",
        "src/main/java/com/metallum/render/shared/MetalCompiledArtifact.java", (
    "public interface MetalCompiledArtifact {",
    "MetalPipelineKey pipelineKey();",
))
require("the Metal 3 artifact answers it",
        "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "implements CompiledRenderPipeline, MetalCompiledArtifact, AutoCloseable {",
    "public MetalPipelineKey pipelineKey() {",
))
require("a generation's encoder asks the device through a contract",
        "src/main/java/com/metallum/render/shared/MetalDeviceFacts.java", (
    "public interface MetalDeviceFacts {",
    "boolean useLabels();",
    "MemorySegment metalDeviceHandle();",
))
require("the execution services are a facade fact, not package access",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "public MetalExecutionServices executionServices() {",
))
require("the device answers that contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "public final class MetalDevice implements GpuDeviceBackend, MetalDeviceFacts {",
    "public boolean useLabels() {",
))
require("the frame's queue comes from the execution services",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    # The constants are gone: the services are built from BOTH facts - what was selected and what executes -
    # because a forced Metal 4 launch executes Metal 4 while AUTO still executes the reference path.
    "this.services = MetalExecutionServices.of(decision.selected(), executesToday);",
    "this.commandEncoder = this.services.createFrameEncoder(this, this.executionState, this.defaultShaderSource);",
    "this.presentGate = this.services.startPresentPath(this.metalDevice);",
))
# The queue itself is the Metal 3 implementation's object: the address still comes from the services, but the
# type and its teardown live where the generation does, so the facade names no command-generation type for the
# sake of one caller.
require("the frame's queue belongs to the generation that encodes the frame",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "private final com.metallum.mtl.metal3.MTLCommandQueue commandQueue;",
    "device.executionServices().commandQueue(device.metalDevice())",
    "return commandBuffer = this.commandQueue.makeCommandBuffer(",
    "this.commandQueue.close();",
))
# The only observation of the seam's own answer. It exists because the claim "the services carry the selection
# and not a constant" had nothing to read it with: `selectedGeneration` in the frame probe comes from the
# telemetry, so before this line an AUTO launch that chose Metal 4 and a forced Metal 3 launch printed the same
# thing at this seam. Pinned because a log line nobody guards is a log line somebody deletes.
require("the seam prints the generation the services themselves carry",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    '"Metal execution seam: selectedGeneration={} executingGeneration={} mode={} referenceShell={} framePathReady={}"',
    "this.services.selected().token(), this.services.executing().token(),",
    "this.services.framePathReady() ? \"own-path\" : \"reference-shell\",",
    "this.services.isReferenceShell(), this.services.framePathReady());",
))
require("the generation owns the queue factory, behind a neutral signature",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionProvider.java", (
    'Msg.of("newCommandQueue"',
    "return NEW_COMMAND_QUEUE.sendPtr(device.handle()).address();",
    "public MetalExecutionState createExecutionState(final MTLDevice device) {",
))
require("the services hold a provider and name no generation",
        "src/main/java/com/metallum/render/execution/MetalExecutionServices.java", (
    "long commandQueue(MTLDevice device);",
    "private final MetalExecutionProvider provider =",
    "return this.provider.commandQueue(device);",
    "return this.provider.createExecutionState(device);",
    "return this.provider.createFrameEncoder(device, executionState, defaultShaderSource);",
))
device_source = (ROOT / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
if "this.metalDevice.newCommandQueue()" in device_source:
    raise SystemExit(
        "the device makes its own command queue again, which puts a generation inside the device and is what "
        "the execution-services seam exists to prevent"
    )
require("the services say what executes, not only what was chosen",
        "src/main/java/com/metallum/render/execution/MetalExecutionServices.java", (
    "MetalApiGeneration selected();",
    "MetalApiGeneration executing();",
    "boolean isReferenceShell();",
    # The pin used to require the literal, which recorded the shape rather than the design: what it is
    # about is that the services answer with what executes, so it now requires the parameter.
    "return executing;",
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
# The compiled pipeline's identity, introduced beside the cache and not yet used by it: the cache is keyed
# by the game's pipeline object, which answers "have I compiled this object" and not "is this the same work",
# and a cache that spans two generations needs the second question answered. The profile is part of the key
# so that a Metal 3 artifact cannot be handed to a Metal 4 session, and every compiled pipeline carries its
# own key so the step that moves the cache has something to move it to.
require("a compiled pipeline carries what it is, not only the object it was asked for",
        "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "private final MetalPipelineKey pipelineKey;",
    "MetalPipelineKey pipelineKey() {",
    "this.pipelineKey = pipelineKey;",
))
require("the identity is read from the game's description plus the session's own two facts",
        "src/main/java/com/metallum/render/shared/MetalPipelineKey.java", (
    "pipeline.getLocation().toString()",
    "pipeline.getVertexShader().toString()",
    "pipeline.getFragmentShader().toString()",
    "pipeline.getShaderDefines().asSourceDirectives()",
    "MetalPipelineKey of(final RenderPipeline pipeline, final String shaderProfile,",
))
require("the key is built where the pipeline is compiled",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), translated.usesArgumentBuffers())",
    "MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, argumentBuffersTier2)",
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
    # The texture binding moved from a hard-coded slot zero to the slot the layout names, because the
    # sampled-texture smoke samples through one slot while the frame's own layouts bind more than one: the
    # pin follows the call and keeps what it was watching, which is the resource id and the header's selector.
    "public boolean texture(final MemorySegment textureHandle, final long index) {",
    "SET_TEXTURE.send(handle, RESOURCE_ID.sendLong(textureHandle), index);",
    # Asked for with one and not zero, which this contract used to pin the other way round. The header says
    # `initializeBindings` defaults to false, so a table created with the default leaves a slot this path never
    # fills holding whatever the driver left there - and this path skips a binding by design where a layout
    # declares it as the other kind of resource. The first world frame, the first frame that draws the clouds,
    # read one of those slots and killed the GPU; with the bindings initialised to nil it renders.
    "SET_INITIALIZE.send(descriptor, 1L);",
))
require("a missing table is said out loud rather than hidden",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    "not carrying the present, because this device makes",
    "private static boolean refuse(final String why) {",
))

print("Metal and engine contracts: PASS")
