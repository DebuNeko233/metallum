#!/usr/bin/env python3
"""Contracts for the Metal 3 generation and the shared render seam.

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

# ==================== was tools/ci-contracts.py ====================














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

require("Metal mapped-buffer allocation", "src/main/java/com/metallum/render/shared/MetalGpuBuffer.java", (
    # The invariant a mapped upload rests on, and the reason the cloud's face data needs no copy at all: a
    # buffer the CPU writes is the buffer the GPU reads - one shared allocation, handed out as a view of its own
    # storage, with nothing to encode on close. A staging path here would put a copy between the two, and a
    # copy that is encoded but not resident is one the engine has already been bitten by once (the GUI road).
    "MTLStorageMode storageMode = isCpuAccessible(usage) || isDynamic(usage) ? MTLStorageMode.Shared "
    ": MTLStorageMode.Private;",
    "ByteBuffer mapped = this.sliceStorage(offset, length);",
    "return new GpuBufferSlice.MappedView(this.slice(offset, length), mapped, () -> {",
    "this.sliceStorage(offset, data.remaining()).put(data.duplicate());",
))
require("Generation-specific persistent mapping", "src/main/java/com/metallum/render/MetalDevice.java", (
    # The device-level answer that made one generation's workaround decide the other's upload road, and the
    # audit's first task: Sodium stages its chunk meshes through a persistently mapped buffer when this flag is
    # advertised, so the flag decides which upload road a generation takes. It was withdrawn for the whole device
    # by ab741fc, when the mapped road lost every mesh on Metal 4 - a fact about that generation, not about the
    # device - and Metal 3, which had advertised it since the backend existed, paid for it.
    "persistentMappingFor(this.services.executing())",
    'static final String PERSISTENT_MAPPING_PROPERTY = "metallum.persistentMapping";',
    "boolean advertised = asked != null ? asked : executing == MetalApiGeneration.METAL3;",
    "Metal device: persistentMapping={} ({} executes the frame{}, from {})",
))
# And the shape it replaced is refused by name: a literal in the feature list would put the device back in
# charge of a generation's answer, which is the leak this pin exists to keep closed. The proof is a mutation -
# restoring the old literal fails this file.
forbid("Device-wide persistent mapping", read("src/main/java/com/metallum/render/MetalDevice.java"), (
    "new DeviceFeatures(false, false, true, true, true, false, false)",
))
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


# ==================== was tools/ci-frame-probe.py ====================
"""Pins the frame probe's shape so that instrumenting this backend stays opt-in and reversible.

The probe is a measuring instrument, not a feature: it may only ever be armed by a property or a
marker file, it may only ever record counts, and it may only ever be reached from the hooks below.
Every assertion here fails the build rather than reporting a warning, for the same reason the other
`tools/ci-*.py` contracts do -- a probe that quietly stopped being armed, or that started asking
Metal for a texture width on the unarmed path, is a behaviour change nobody would see in a diff.
"""

PROBE_PATH = "src/main/java/com/metallum/render/shared/MetalFrameProbe.java"




def require(label: str, text: str, needles: tuple[str, ...]) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise SystemExit(f"{label}: missing " + ", ".join(missing))


def order(text: str, first: str, second: str, why: str) -> None:
    """Refuse unless both are present and `first` comes before `second`.

    Presence is checked rather than left to `str.index`, so a token an edit deleted is reported as
    the defect it is instead of as a traceback from this file.
    """
    for needle in (first, second):
        if needle not in text:
            raise SystemExit(f"{why} -- {needle!r} is not in the shape at all")
    if not text.index(first) < text.index(second):
        raise SystemExit(why)


probe = read(PROBE_PATH)
metal4_encoder = read("src/main/java/com/metallum/render/metal4/Metal4FrameEncoder.java")
command_buffer = read("src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java")

# ---------------------------------------------------------------------------
# Off unless asked for, and a window can be opened late
#
# The property is read once at class load. The marker decides a window rather than a launch, because
# the frames worth counting are the ones the whole render path is in force for and a launch cannot
# know when that starts; it sits in the game directory because that is a place a session can reach
# while the launcher's arguments are not. Nothing here may throw on an unreadable answer: a probe may
# never be the reason a session does not start.
# ---------------------------------------------------------------------------
require("frame-probe arming", probe, (
    "package com.metallum.render.shared;",
    "public final class MetalFrameProbe {",
    "private MetalFrameProbe() {",
    'Boolean.getBoolean("metallum.probeFrames")',
    'Integer.getInteger("metallum.frameProbeBudget", 600)',
    'private static final String MARKER_DIRECTORY = "metallum";',
    'private static final String MARKER = "probe-frames";',
    "FabricLoader.getInstance().getGameDir()",
    "armedFromFile = markerPresent();",
    "catch (RuntimeException exception)",
))
if "if (!FLAG && !marker()) {" not in probe:
    raise SystemExit("frame probe: the property and the marker are not both asked before arming")
if probe.index("if (armedFromFile == null) {") > probe.index("armedFromFile = markerPresent();"):
    raise SystemExit("frame probe: the marker answer is not cached behind a single ask")

# ---------------------------------------------------------------------------
# A window opens on the marker's return, and nowhere else can open one
#
# One ask site, reached from the unarmed path of the frame boundary alone, skipped when the property
# already answered for the launch, and gated on the answer changing rather than on the marker being
# there -- a marker left in place after its window would otherwise arm window after window and fill a
# disk, which is the one thing the budget exists to prevent.
#
# These are orderings and not appearances on purpose. Every property below is a claim about which
# branch runs, and every one of them can be broken by an edit that keeps each token exactly where a
# substring search wants it: dropping the interval's reset makes it ask on every frame, moving the
# call onto the counting path makes a running window end silently and a late marker never arm, and
# hoisting the reset above the transition opens a window every interval for the rest of the session.
# Each of those was written, seen to pass this file as it stood, and is refused below.
# ---------------------------------------------------------------------------
if probe.count("askAgain();") != 1:
    raise SystemExit(
        "frame probe: the marker must be asked again from one place, so that no counter's guard can "
        "open a window"
    )
frame_start = probe.index("public static void frameSubmitted() {")
frame_body = probe[frame_start:probe.index("public static void attachment(", frame_start)]
# Whitespace is not part of the contract, but the branch is: the ask has to be the first thing the
# unarmed path does and it has to return, not sit somewhere between the guard and the counting.
if "if (!armed()) { askAgain(); return;" not in " ".join(frame_body.split()):
    raise SystemExit(
        "frame probe: the frame boundary does not ask the marker and return when the probe is off, "
        "so a marker that appears late never arms, or a running window is cut short with its counts "
        "stranded"
    )
if probe.count("private static void askAgain() {") != 1:
    raise SystemExit("frame probe: there is no single method that opens a window")
ask_start = probe.index("private static void askAgain() {")
ask_body = probe[ask_start:probe.index("\n    }", ask_start)]
order(
    ask_body,
    "if (FLAG) {",
    "markerPresent()",
    "frame probe: an armed launch asks the marker, which the property already answered for it",
)

# The interval: counted, gated, reset, and about a second. A constant nobody resets is a gate that is
# true once and open forever after, which is a stat per frame rather than the documented one a second.
interval = re.search(r"private static final int ASK_EVERY_FRAMES = (\d+);", probe)
if interval is None:
    raise SystemExit("frame probe: the interval the marker is asked on while off is not a named constant")
if not 30 <= int(interval.group(1)) <= 600:
    raise SystemExit(
        "frame probe: the marker is not asked about once a second -- the interval is "
        f"{interval.group(1)} frames, which is a frame's work or a minute's"
    )
order(
    ask_body,
    "++framesSinceAsk < ASK_EVERY_FRAMES",
    "framesSinceAsk = 0;",
    "frame probe: the ask interval is counted but never reset, so the gate is true once and the "
    "marker is asked on every frame after it",
)

# The answer is read, compared with the one held, and only then held. Comparing after the overwrite
# is always true and opens no window ever; holding without comparing opens one on the marker simply
# being there, which is the whole defect this shape replaces.
order(
    ask_body,
    "markerPresent()",
    "if (present == marker()) {",
    "frame probe: the marker's answer is not read before it is compared with the one held",
)
order(
    ask_body,
    "if (present == marker()) {",
    "armedFromFile = present;",
    "frame probe: the answer is held before it is compared with the one held, so the comparison is "
    "always true and no window ever opens",
)

# A window's reset lives behind that comparison. Above it, a marker left in place opens a window
# every interval for the whole session, which is the disk the budget exists to protect.
order(
    ask_body,
    "if (present == marker()) {",
    "frames = 0;",
    "frame probe: a window's budget is reset without the marker having changed, so a marker left in "
    "place opens window after window",
)
order(
    ask_body,
    "if (present == marker()) {",
    "if (present) {",
    "frame probe: a window is opened without the marker having come back first",
)
order(
    ask_body,
    "if (present) {",
    "frames = 0;",
    "frame probe: a window's budget is reset outside the branch that opens it",
)
order(
    ask_body,
    "if (present) {",
    "announced = false;",
    "frame probe: the announcement is cleared outside the window being opened",
)

# The budget is what keeps an armed launch from filling a disk, and the line is a window rather
# than a frame, so the two are both pinned.
require("frame-probe budget", probe, (
    "frames >= BUDGET",
    "frames % REPORT_FRAMES == 0 || frames >= BUDGET",
    "Metal frame probe wrote its {} frame(s) and is off",
    "Metal frame probe armed",
))

# ---------------------------------------------------------------------------
# A window carries what it cost in time
#
# A count of bytes is not a performance reading until something says what the bytes were worth, and
# that is the second thing every measurement in the companion backend was missing. The time is read
# from the window's own first frame: measuring from the previous line would carry whatever the
# session did between the two, which for the first window is the pack load the window exists to
# exclude.
# ---------------------------------------------------------------------------
require("frame-probe window time", probe, (
    "windowMs={}",
    "if (windowFrames == 1) {",
    "windowStartedAt = now;",
    "long windowNanos = System.nanoTime() - windowStartedAt;",
    "windowStartedAt = 0L;",
))
# And the distribution the mean hides, taken from the same frames: a window is now reported as its own
# percentiles as well, because the frame that stutters is what a player feels and a mean cannot show it.
# The two generations' GPU time, and the sum, because a Metal 4 submission is invisible to the Metal 3
# reading: the present moving to the new queue made `gpuMs` fall by a quarter while the wall clock did not
# move, which is a measurement that flatters the change it is supposed to judge.
require("frame-probe generation GPU time", probe, (
    "gpuFrames={} gpuM4Feedbacks={} gpuM4FeedbacksTotal={} gpuM4Frames={} gpuM3Ms={} gpuM4Ms={} gpuMs={}",
    "selectedGeneration={} executingGeneration={}",
    "public static void gpuFrameMetal4(final double milliseconds) {",
    "metal4FeedbacksTotal.incrementAndGet();",
    "metal4Feedbacks.incrementAndGet();",
    "metal4GpuFrames.incrementAndGet();",
    "metal4GpuNanos.addAndGet((long) (milliseconds * 1_000_000.0));",
    # The arguments and the placeholders have to agree, and their order is pinned because a value added to
    # one and not the other prints every counter after it under another counter's name - which happened
    # twice while this line was being built.
    "gpuFrames,\n                metal4Feedbacks.get(),\n                metal4FeedbacksTotal.get(),\n                metal4GpuFrames.get(),",
    # Both facts, in the order the placeholders name them: a probe line carrying only the selection is what
    # let a Metal 3 frame be read as Metal 4.
    "MetalExecutionTelemetry.selectedToken(),\n                MetalExecutionTelemetry.executingToken(),",
))
require("frame-probe pipeline census", probe, (
    "pipelineIdentities={} pipelineKeys={}",
    "public static void pipelineRequested(final RenderPipeline pipeline, final MetalPipelineKey key) {",
    "if (!pipelineIdentities.add(pipeline)) {",
    "if (pipelineKeys.add(key)) {",
    "Collections.newSetFromMap(new IdentityHashMap<>())",
    "censusClosed = true;",
))
# The census counts belong with the counters and ahead of the pacing values: a number inserted between the
# percentiles would print every distribution value under another name, and one inserted before compileMs
# would report the census as a compile.
if probe.index("keyCount,") > probe.index("percentile(wallTimes, wallSamples, 0.50)"):
    raise SystemExit("frame probe: the pipeline census arguments are behind the pacing values")
if probe.index("identityCount,") < probe.index("millis(compileNanos),"):
    raise SystemExit("frame probe: the pipeline census arguments are ahead of the compile counters")

require("frame-probe pacing", probe, (
    "wallP50={} wallP95={} wallP99={} wallMax={} wallMaxAt={} gpuP50={} gpuP95={} gpuP99={} gpuMax={}",
    "wallTimes[wallSamples] = (now - lastFrameAt) / 1_000_000.0;",
    "worstWallFrame = wallSamples;",
    "gpuTimes[gpuSamples++] = milliseconds;",
    # The Metal 4 queue's own samples, which had no percentile path at all: the first forced Metal 4 run the
    # harness collected reported gpuM4Ms with every gpuP* at zero, and a comparison between the generations is
    # made of exactly these four numbers.
    "private static final double[] gpuM4Times = new double[BUDGET + 1];",
    "gpuM4Times[gpuM4Samples++] = milliseconds;",
    "gpuM4P50={} gpuM4P95={} gpuM4P99={} gpuM4Max={}",
    "percentile(gpuM4Times, gpuM4Samples, 0.50),",
    "private static String percentile(final double[] times, final int count, final double fraction) {",
    "java.util.Arrays.sort(sorted);",
    "int rank = (int) Math.ceil(fraction * count) - 1;",
))
# The distribution's arguments belong at the end of the report's argument list: put anywhere else they
# shift every counter that follows into another counter's name, which is exactly what one run printed -
# `encoders=1.75` where a count belongs and `wallP50=7627` where a binding count does.
if probe.index("percentile(wallTimes, wallSamples, 0.50)") < probe.index("millis(compileNanos)"):
    raise SystemExit(
        "frame probe: the pacing arguments are not the last of the report's arguments, so every counter "
        "printed after them is another counter's value"
    )
if probe.index("long windowNanos = System.nanoTime() - windowStartedAt;") > probe.index("reset();"):
    raise SystemExit("frame probe: the window's time is read after the window's counters are cleared")

# ---------------------------------------------------------------------------
# The depth attachment is a share of the totals and not a replacement for them
#
# The depth slot is the one attachment the pack side cannot currently answer for: the lifetime
# capability carries one flag a slot and the depth slot is not one of them, so a depth load is
# clear-or-load and a depth store is always a store. A frame's depth is its largest single
# attachment, so its share decides whether teaching that slot to answer is worth doing - and the
# share has to be read beside the totals and not instead of them, or a comparison against the totals
# already recorded here would silently be a comparison against something else.
# ---------------------------------------------------------------------------
require("frame-probe depth split", probe, (
    "depthAttachments={} depthLoadedMiB={} depthStoredMiB={}",
    "public static void depthAttachment(",
    "depthAttachments++;",
    "depthLoadedBytes += bytes;",
    "depthStoredBytes += bytes;",
    "depthAttachments = 0;",
    "depthLoadedBytes = 0L;",
    "depthStoredBytes = 0L;",
))
if probe.count("loadedBytes += bytes;") != 2 or probe.count("storedBytes += bytes;") != 2:
    raise SystemExit(
        "frame probe: the depth attachment is no longer counted inside the totals, so the share and the whole are not one reading"
    )

# ---------------------------------------------------------------------------
# What a frame moves outside a pass
#
# The copy-backs a pack's kept targets need at the end of a frame are blits, and every other counter
# here counts an attachment, an encoder or a binding: without this one they are inside the frame's GPU
# time and invisible in its decomposition. The size arrives as two integers and a pixel size rather
# than as a texture, so an unarmed session pays the guard and no question is asked of Metal.
# ---------------------------------------------------------------------------
require("the encoder split", probe, (
    "private static int renderPassOpeners;",
    "public static void encoderOpened(final int kind) {",
    "frame-probe openers renderPasses={} blitEncoders={} computeEncoders={} clearEncoders={} ",
    "metal4Frames={} metal4Us={}",
))

# Phase F's upload census: the three roads CPU bytes take into a Metal 4 frame, each counted and timed where
# the road is, and reported together. The counter is what decides whether the staging-and-copy shape this
# generation uses for every CPU-written buffer is worth replacing with the reference generation's direct write -
# a question with a number in it only if the calls, the bytes and the CPU time are readable. The entry points
# live in the shared probe, but the roads that reach them are this generation's own encoder: Metal 3 writes its
# buffers directly and has none of these three call sites, so pinning the roads against the Metal 3 encoder
# would be pinning an absence.
# Phase A1's native-call census: the shadow that says whether a call could have been skipped, the line that
# reports it, and the one hook that clears the shadow. The census's whole value is the `repeated` figure - the
# share of this backend's call volume that carries a value the slot already holds - and every one of these
# pieces is what makes that figure mean anything: the shadow because nothing else knows what the slot holds,
# the clear because a new native encoder holds nothing, and the opt-in property because a diagnostic may not
# change what a session that did not ask for it does.
require("native call census", probe, (
    'Boolean.getBoolean("metallum.m3CallCensus")',
    "frame-probe m3native calls={} native={} repeated={} ",
    "public static void bufferBound(final long handle, final long offset, final int slot,",
    "public static void textureBound(final long handle, final int slot, final boolean vertex,",
    "public static void samplerBound(final long handle, final int slot, final boolean vertex,",
    "public static void pipelineBound(final long handle) {",
    "public static void depthStencilBound(final long handle) {",
    "public static void cullSet(final long mode) {",
    "public static void fillSet(final long mode) {",
    "public static void windingSet(final long mode) {",
    "public static void depthBiasSet(final float constant, final float scaleFactor) {",
    "public static void viewportSet(final double originX, final double originY, final double width,",
    "public static void scissorSet(final long x, final long y, final long width, final long height) {",
    "public static void drawIndexedPrimitives(final long indexCount, final long instanceCount) {",
    "public static void drawPrimitives(final long vertexCount, final long instanceCount) {",
    "public static void drawIndirectPrimitives() {",
    "public static void indirectDrawLoop(final int commands, final long nanos) {",
    "indirectLoops={} indirectCommands={} indirectCpuMs={} ",
    "public static void fenceUpdated() {",
    "public static void fenceWaited() {",
    "private static void clearBindingShadow() {",
    "censusCalls = 0;",
))
require("native call census's shadow clear", probe, ("clearBindingShadow();",))
# The pass-size census, which is C1's split and C3's question: a frame at 55 per cent draws most of its passes
# into the scaled world target and some - the interface, a shadow map, a post pass - into the window's own, and
# the only place that knows which is the pass's own render area at construction. Pinned with the road that
# reaches it, because a counter nothing calls reads zero and zero looks like a scene with no full-size passes.
require("pass size census", probe, (
    "public static void passTarget(final int width, final int height) {",
    "passFullSize={} passSmaller={} passSizes={}",
    "passSizes.merge(((long) width << 32) | (height & 0xFFFFFFFFL), 1L, Long::sum);",
    "passSizes.clear();",
))
require("pass size census is reached from the pass", render_pass, (
    "MetalFrameProbe.passTarget(width, height);",
))
if probe.index("clearBindingShadow();") < probe.index("public static void renderEncoderRecreated("):
    raise SystemExit(
        "native call census: the binding shadow is not cleared where a native encoder is made, so the first "
        "bind of a frame would be read as a repeat of the last encoder's - the one way this census can "
        "overstate what could be removed"
    )
if probe.count("clearBindingShadow();") != 1:
    raise SystemExit(
        "native call census: the shadow is cleared somewhere other than the one hook that knows an encoder was "
        "made rather than joined"
    )
require("upload census", probe, (
    "public static void uploadedToBuffer(final long bytes, final long nanos) {",
    "public static void uploadedCopyingBuffer(final long bytes, final long nanos) {",
    "public static void uploadedToTexture(final long bytes, final long nanos) {",
    # Each road's whole accounting is pinned as one block rather than as loose lines, because the loose lines
    # appear three times over and a census that stopped adding one road's time up would still show the other
    # two - which is exactly the defect that reads as a cheap road: measured, a road's own accumulator was
    # deleted and every loose-line pin still passed.
    "        uploadsToBuffer++;\n        uploadedToBufferBytes += bytes;\n        uploadCalls++;\n"
    "        uploadBytes += bytes;\n        uploadNanos += nanos;",
    "        uploadCopiesToBuffer++;\n        uploadedCopyBytes += bytes;\n        uploadCalls++;\n"
    "        uploadBytes += bytes;\n        uploadNanos += nanos;",
    "        uploadsToTexture++;\n        uploadedToTextureBytes += bytes;\n        uploadCalls++;\n"
    "        uploadBytes += bytes;\n        uploadNanos += nanos;",
    "if (uploadCalls > 0) {",
    "uploadNanos / 1_000_000.0",
    "uploadCalls = 0;",
    "uploadNanos = 0L;",
    "windowTicks={} framesPerTick={} frameCpuMs={} allocKiB={}",
    "com.sun.management.ThreadMXBean",
    # The id the bytes are asked of is named by `threadId()`, the same number as `getId()` and the only one of
    # the two this module may keep: it compiles at `options.release = 25`, where `getId()` is deprecated for
    # removal, so the pin follows the spelling the source has to use rather than the one it used to.
    "getThreadAllocatedBytes(Thread.currentThread().threadId())",
    "windowCpuStart = currentThreadCpuNanos();",
    "getCurrentThreadCpuTime();",
    "frame-probe uploads uploadCalls={} uploadMiB={} uploadCpuMs={} uploadsToBuffer={}",
    "toBufferMiB={} uploadsCopyingBuffer={} copyMiB={} uploadsToTexture={}",
    "textureMiB={}",
))
require("upload census is reached from the upload roads", metal4_encoder, (
    "MetalFrameProbe.uploadedToBuffer(length, System.nanoTime() - began);",
    "MetalFrameProbe.uploadedCopyingBuffer(source.length(), System.nanoTime() - began);",
    "MetalFrameProbe.uploadedToTexture(bytesPerImage, System.nanoTime() - began);",
))
require("blit counter", probe, (
    "blits={} blittedMiB={}",
    "public static void blit(final int width, final int height, final int pixelSize) {",
    "blits++;",
    "blittedBytes += (long) width * height * pixelSize;",
    "blits = 0;",
    "blittedBytes = 0L;",
))
require("blit counter is reached from the blit", encoder, (
    "MetalFrameProbe.blit(width, height, srcTexture.pixelSize());",
))
order(
    encoder,
    "MTLBlitCommandEncoder blit = blitCommandEncoder();",
    "MetalFrameProbe.blit(width, height, srcTexture.pixelSize());",
    "the blit is counted after the encoder is opened rather than at the decision",
)

# ---------------------------------------------------------------------------
# The one reading of GPU time in the session
#
# Apple documents the two times as "the host time, in seconds, when the GPU starts command buffer
# execution" and the same for its end, and says both "remain 0.0 until the GPU finishes running the
# command buffer" and are to be read after the wait or inside a completion handler. So they are read
# here after the submit they belong to has been waited on and before its buffer is released, which is
# what makes the number an answer about a finished frame rather than a guess about a running one.
# ---------------------------------------------------------------------------
require("gpu frame time", command_buffer, (
    'Msg.of("GPUStartTime", JAVA_DOUBLE)',
    'Msg.of("GPUEndTime", JAVA_DOUBLE)',
    "public double gpuMillis() {",
    "return end > start ? (end - start) * 1000.0 : 0.0;",
))
require("gpu frame time is taken from the completed submit", encoder, (
    "MetalFrameProbe.gpuFrame(toClose.buffer.gpuMillis());",
))
order(
    encoder,
    "boolean windowOpen = awaitSubmitCompletion(currentSubmitIndex - MAX_SUBMITS_IN_FLIGHT, 5000L);",
    "MetalFrameProbe.gpuFrame(toClose.buffer.gpuMillis());",
    "the GPU time is read before the submit it belongs to has been waited on, so the driver has not reported it yet",
)
# The in-flight window's wait is measured at the frame tail and nowhere else. The same fence method is called
# on the close path, whose wait is explicit teardown: counted together, teardown would read as frame pacing,
# which is the one thing this measurement exists to decide.
require("the submit-window wait is measured, frame tail only", encoder, (
    "MetalFrameProbe.submitWindowWait(System.nanoTime() - windowWaitBegan);",
    "boolean frameTailArmed = MetalFrameProbe.armed();",
    "awaitSubmitCompletion(lastCommittedSubmitIndex, Long.MAX_VALUE);",
))
if encoder.count("MetalFrameProbe.submitWindowWait(") != 1:
    raise SystemExit(
        "the submit-window wait is recorded "
        + str(encoder.count("MetalFrameProbe.submitWindowWait("))
        + " times, and only the frame tail's wait is frame pacing - the close path's wait is teardown"
    )
order(
    encoder,
    "MetalFrameProbe.gpuFrame(toClose.buffer.gpuMillis());",
    "toClose.buffer.close();",
    "the GPU time is read after the command buffer is released",
)
require("frame-probe gpu window", probe, (
    "gpuFrames={} gpuM4Feedbacks={} gpuM4FeedbacksTotal={} gpuM4Frames={} gpuM3Ms={} gpuM4Ms={} gpuMs={}",
    "public static void gpuFrame(final double milliseconds) {",
    "gpuFrames++;",
    "gpuMillis += milliseconds;",
    "gpuFrames = 0;",
    "gpuMillis = 0.0;",
))

# ---------------------------------------------------------------------------
# The per-pass report is the host clock, and this says so out loud
#
# The pack side reads its query pool as GPU ticks. The API that would make that true is a counter
# sample buffer - `sampleCounters(sampleBuffer:sampleIndex:barrier:)`, where "A barrier ensures that the
# commands you encode before this one complete before the GPU samples the hardware counters" - and
# neither encoder implements one: both fill the pool from `device.getTimestampNow()` at encode time,
# and that is `System.nanoTime()`. So `-Dvitrail.passTimings` prints what encoding the passes cost the
# CPU and nothing about the GPU, and this assertion exists so that a future change cannot quietly
# change what the table means: implementing counter sample buffers has to fail this line on purpose.
# ---------------------------------------------------------------------------
require("the pass-timing pool is the host clock", encoder + render_pass + device, (
    "metalPool.setValue(index, device.getTimestampNow());",
    "return System.nanoTime();",
))

# ---------------------------------------------------------------------------
# The unarmed path is one field read
#
# Every public entry point opens with the armed() guard, so an unarmed launch pays a boolean field
# read and nothing else: no texture query, no timestamp, no counter. `armed()` itself is the guard
# and is exempt.
# ---------------------------------------------------------------------------
lines = probe.splitlines()
guarded = []
for index, line in enumerate(lines):
    # Leading whitespace is not part of the contract: this file and the rest of the repository were
    # written with different indentation at different times, and a check that pinned one of them
    # would fail on a reformat rather than on a missing guard.
    if not line.lstrip().startswith("public static"):
        continue
    end = index
    while end < len(lines) and not lines[end].rstrip().endswith("{"):
        end += 1
    if end + 1 >= len(lines):
        raise SystemExit(f"frame probe: unterminated entry point at {PROBE_PATH}:{index + 1}")
    declaration = " ".join(part.strip() for part in lines[index:end + 1])
    if "boolean armed(" in declaration:
        continue
    first = lines[end + 1].strip()
    # One entry point counts whether or not a window is open, on purpose, and this is where that is allowed
    # rather than overlooked: a Metal 4 commit feedback that arrives after the report is a feedback no
    # window can count, and "the queue never called back" and "it called back too late" are different
    # repairs. It is one atomic increment per commit and only while the new path is presenting, which is
    # not the per-encoder frame work this rule exists to keep free.
    counts_unarmed = "gpuFrameMetal4" in declaration
    # The second door, opened here rather than left ajar: the pipeline census has to count whether or not a
    # window is open, because pipelines are compiled while the game starts and a census that began at the
    # marker would report almost nothing. It is one identity-set insertion per pipeline request - the same
    # hash the cache lookup beside it just did - and the key, which reads seven strings, is hashed only when
    # the identity is new.
    census_unarmed = "pipelineRequested" in declaration
    # The third door, and the same reason as the census's: a function compile belongs to a launch, and a
    # window opens long after the load that made them, so a counter gated on the marker reports zero on a pack
    # that built hundreds. It is three atomic increments per distinct MSL and entry point - not per frame, and
    # not per draw - and it is what makes the other half of a pipeline's creation visible at all.
    functions_unarmed = "functionCompiled" in declaration
    if first != "if (!armed()) {" and not (
            (counts_unarmed and first == "metal4FeedbacksTotal.incrementAndGet();")
            or (census_unarmed and first == "if (censusClosed) {")
            or (functions_unarmed and first == "unarmedFunctions.incrementAndGet();")):
        raise SystemExit(
            f"frame probe: {declaration} does not open with the armed() guard, so an unarmed call "
            "is no longer a single field read"
        )
    guarded.append(declaration)

if len(guarded) != 60:
    raise SystemExit(
        "frame probe: expected 38 guarded entry points (encoder, encoder opener, frame, gpu frame, Metal 4 "
        "gpu frame, Metal 4 frame, Metal 4 present, colour attachment, depth attachment, blit, six binding "
        "kinds, pipeline creation, the pipeline census, the drawable wait, the submit-window wait, and the "
        "fourteen the Metal 3 backend-cost census added: twelve for the argument-buffer path - a pass, a layout, an "
        "allocation, a set call, a set skipped, a texture write, a sampler write, a buffer write, a useResource "
        "call, a draw, a texel view and a pass descriptor - and two for the render-encoder reuse census, one for "
        "the reuse taken and one for the recreation with its causes - and one for the client tick, which is what "
        "a window's content can be normalised by; "
        "the reuse taken and one for the recreation with its causes - one for section 58's depth bias, which is "
        "the only counter that says whether a real pipeline reaches the road the artifact had carried and nothing "
        "ever sent, and one for the client tick, and two for the clear-folding census - one for a clear the "
        "frame deferred and one for a deferred clear a pass carried as its own load action - and three for "
        "Phase F's upload census, one per road CPU bytes take into a frame: a staged buffer write, a buffer "
        "copy and a staged texture write - and sixteen for the Metal 3 native-call census, which is the one "
        "reading the long-term plan starts from: a buffer bind, a texture bind, a sampler bind, the pipeline "
        "state, the depth-stencil state, the cull mode, the fill mode, the winding order, the depth bias, the "
        "viewport, the scissor, three draw forms - primitives, indexed and indirect - and the two fence "
        "operations - and one for the indirect-draw loop, which is the only road the census prices rather "
        "than counts - and one for a pass's own target size, which is C1's split between the "
        "passes that follow a scaled world and the ones still at the window's size - and one for the MSL to "
        "function compile, which with the pipeline state is the whole of what a launch asks the Metal compiler "
        "for and was the half with no clock at all), found "
        f"{len(guarded)}: " + "; ".join(guarded)
    )
if probe.count("MTLTexture.width(texture) * MTLTexture.height(texture) * pixelSize") != 2:
    raise SystemExit(
        "frame probe: the colour and depth entry points no longer size their attachments the same way"
    )
if probe.index("MTLTexture.width(texture)") < probe.index("public static void attachment("):
    raise SystemExit("frame probe: the attachment byte size is computed outside its entry point")

# ---------------------------------------------------------------------------
# Counter 1: encoder boundaries per frame, split by why the encoder ended
#
# Two call sites, and only two: the pass whose configuration changed, and the frame's own submit.
# Every other endEncoder() in this backend ends one to switch encoder kind or to materialize a
# clear, and passes no reason.
# ---------------------------------------------------------------------------
require("encoder boundary counter", encoder, (
    "void endEncoder() {",
    "endEncoder(null);",
    "void endEncoder(@Nullable final EncoderEnd reason)",
    "MetalFrameProbe.encoderEnded(reason);",
    "endEncoder(MetalFrameProbe.EncoderEnd.SUBMITTED);",
    "endEncoder(MetalFrameProbe.EncoderEnd.PASS_CONFIGURATION_CHANGED);",
    "MetalFrameProbe.frameSubmitted();",
))
if encoder.count("MetalFrameProbe.EncoderEnd.PASS_CONFIGURATION_CHANGED);") != 1:
    raise SystemExit("encoder boundary counter: exactly one site ends an encoder because the pass configuration changed")
# The frame's encoder ends at the drawable blit, not at the submit: by submit() time the MTL layer
# has already ended it, so the reason is offered at both sites and only the real teardown is counted.
if encoder.count("MetalFrameProbe.EncoderEnd.SUBMITTED);") != 2:
    raise SystemExit("encoder boundary counter: the frame boundary must offer its reason at both places the frame's encoder can end")
submit = encoder.index("public void submit()")
submit_body = encoder[submit:encoder.index("MTLRenderCommandEncoder renderCommandEncoder(", submit)]
present = encoder.index("void presentTextureToDrawable(")
present_body = encoder[present:encoder.index("public void clearColorTexture(", present)]
if "MetalFrameProbe.EncoderEnd.SUBMITTED);" not in submit_body:
    raise SystemExit("encoder boundary counter: submit() does not record the frame boundary's encoder end")
if "MetalFrameProbe.EncoderEnd.SUBMITTED);" not in present_body:
    raise SystemExit("encoder boundary counter: the present-time teardown does not record the frame boundary's encoder end")
committed = submit_body.index("commandBuffer.commitWithCompletionBlock(submitSignalBlocks[slot]);")
counted = submit_body.index("MetalFrameProbe.frameSubmitted();")
advanced = submit_body.index("currentSubmitIndex++;")
if not committed < counted < advanced:
    raise SystemExit(
        "encoder boundary counter: the frame boundary must be the commit itself -- the surface's "
        "present-time submit() finds no command buffer, so counting every submit() counts each drawn "
        "frame twice"
    )
configured = encoder.index("MetalFrameProbe.EncoderEnd.PASS_CONFIGURATION_CHANGED);")
if configured < encoder.index("MetalPipelineSupport.sameHandles(renderColorAttachments, colorAttachments)"):
    raise SystemExit("encoder boundary counter: the pass configuration change is not recorded where reused encoders are refused")

# ---------------------------------------------------------------------------
# Counter 2: bytes loaded and stored per frame
#
# The load and store actions are chosen in the MTLCommandBuffer attachment loop, so that is where
# the attachment is handed over. The size itself is a property of the caller's format, which the
# MTL layer does not hold, so it arrives as a bytes-per-pixel figure per attachment.
# ---------------------------------------------------------------------------
require("attachment byte counter", command_buffer, (
    "final int[] colorPixelSizes",
    "final int depthPixelSize",
    "Color attachment and pixel-size counts differ",
))
if command_buffer.count("MetalFrameProbe.attachment(") != 1 or command_buffer.count("MetalFrameProbe.depthAttachment(") != 1:
    raise SystemExit(
        "attachment byte counter: the colour and the depth attachment must each reach the probe, and the "
        "depth one must reach it through the entry point that counts it apart from the totals"
    )
color_loop = command_buffer.index("for (int index = 0; index < colorTextures.length; index++)")
depth_block = command_buffer.index("if (!ObjC.isNil(depthTexture)) {", color_loop)
color_probe = command_buffer.index("MetalFrameProbe.attachment(", color_loop)
depth_probe = command_buffer.index("MetalFrameProbe.depthAttachment(", depth_block)
if not color_loop < color_probe < depth_block < depth_probe:
    raise SystemExit("attachment byte counter: neither attachment is counted beside its own load/store decision")
for action in (
    "loadAction == MTLRenderPassDescriptor.LOAD_ACTION_LOAD",
    "storeAction == MTLRenderPassDescriptor.STORE_ACTION_STORE",
):
    if action not in command_buffer:
        raise SystemExit("attachment byte counter: the load/store action is no longer the decision that is counted: " + action)
require("attachment byte source", encoder, (
    "int[] colorPixelSizes = new int[colorTextureViews.length];",
    "((MetalGpuTexture) colorTextureView.texture()).pixelSize()",
    "((MetalGpuTexture) depthTextureView.texture()).pixelSize()",
))
if "MetalGpuTexture" in command_buffer:
    raise SystemExit("attachment byte counter: the MTL layer must stay a handle layer and not learn Minecraft texture types")

# ---------------------------------------------------------------------------
# What a pass may say about an attachment's contents
#
# The two actions above are a decision rather than a constant, and the decision is reached from two
# facts the caller may state per attachment: whether anything reads its contents afterwards, and
# whether this pass writes every pixel of them anyway. The public descriptor carries neither, which
# is why the capability exists at all.
#
# The direction that matters is the fallback. A wrong DontCare is not a slower frame, it is a wrong
# image that reads as a shader-pack defect, so every answer nobody gave - no array, a short array, a
# null slot - has to come back as the one that changes nothing.
# ---------------------------------------------------------------------------
contents_record = read("src/main/java/com/metallum/render/shared/AttachmentContents.java")
require("attachment contents", command_buffer, (
    "AttachmentContents[] stated = AttachmentContents.resolve(attachmentContents, colorTextures.length);",
    "AttachmentContents contents = stated[index];",
    ": contents.overwritten()",
    "? MTLRenderPassDescriptor.LOAD_ACTION_DONT_CARE",
    "long storeAction = contents.readAfterwards()",
    "? MTLRenderPassDescriptor.STORE_ACTION_STORE",
    ": MTLRenderPassDescriptor.STORE_ACTION_DONT_CARE",
))
if "stated != null && index < stated.length && stated[index] != null" not in contents_record:
    raise SystemExit(
        "attachment contents: a caller that said nothing about a slot is not answered with the "
        "default, which is the one direction this capability may not get wrong"
    )
if "public static final AttachmentContents CARRIED = new AttachmentContents(true, false);" not in contents_record:
    raise SystemExit("attachment contents: the default is no longer the answer that changes nothing")
require("attachment contents fact", encoder, (
    "private AttachmentContents[] nextPassContents;",
    "public void setNextPassContents(@Nullable final AttachmentContents[] contents)",
))
read_facts = encoder.index("AttachmentContents[] passContents = this.nextPassContents;")
cleared = encoder.index("this.nextPassContents = null;", read_facts)
built = encoder.index("new MetalRenderPass(", read_facts)
if not read_facts < cleared < built:
    raise SystemExit(
        "attachment contents: what one pass was told is not read and cleared before that pass is "
        "built, so it would leak onto the next"
    )

# An encoder keeps the load and store actions it was created with, so two passes may only share one
# when their answers agree. Without this a pass that discarded its contents could hand its encoder to
# a pass that reads them, and the second would read memory nobody wrote - a wrong image rather than a
# slower frame, and one nothing in a log would name.
if "&& Arrays.equals(renderContents, stated)) {" not in encoder:
    raise SystemExit(
        "attachment contents: the encoder-reuse decision ignores what each pass said about its "
        "attachments, so a pass can inherit another pass's discarded contents"
    )
if "renderContents = stated;" not in encoder:
    raise SystemExit("attachment contents: the answers the live encoder was opened with are not remembered")
if "renderContents = new AttachmentContents[0];" not in encoder:
    raise SystemExit("attachment contents: the answers outlive the encoder they described")

# ---------------------------------------------------------------------------
# Counter 3: bindings per frame, split by kind
#
# One increment per resource or state pushed at the moment it reaches Metal, so a direct bind, an
# argument-buffer write and a vertex buffer all count once in their own kind.
# ---------------------------------------------------------------------------
# The Metal 3 roads carry the census's own entry points now: each takes the value the call carries, so the
# shadow in the probe can say whether the slot already holds it. The zero-argument versions stay, because the
# Metal 4 pass still calls them and a generation that is frozen may not be edited to suit a census.
require("binding counters", render_pass, (
    "MetalFrameProbe.pipelineBound(pipelineHandle.address());",
    "MetalFrameProbe.textureBound(texture.address(), (int) index,",
    "MetalFrameProbe.samplerBound(sampler.address(), (int) index, vertex, fragment);",
    "MetalFrameProbe.bufferBound(buffer.handle().address(), offset, (int) index,",
    "MetalFrameProbe.scissorSet(x, y, width, height);",
))
require("the census's state roads", render_pass, (
    "MetalFrameProbe.depthStencilBound(depthState.address());",
    "MetalFrameProbe.cullSet(compiledPipeline.cullMode().value);",
    "MetalFrameProbe.fillSet(compiledPipeline.fillMode().value);",
    "MetalFrameProbe.windingSet(MTLWinding.Clockwise.value);",
    "MetalFrameProbe.depthBiasSet(compiledPipeline.depthBiasConstant(),",
    "MetalFrameProbe.drawPrimitives(vertexCount, instanceCount);",
    "MetalFrameProbe.drawIndexedPrimitives(indexCount, instanceCount);",
    "MetalFrameProbe.drawIndirectPrimitives();",
))
require("viewport counter", render_encoder, (
    "import com.metallum.render.shared.MetalFrameProbe;",
    "MetalFrameProbe.viewportSet(originX, originY, width, height, znear, zfar);",
))
require("fence counters", encoder, (
    "MetalFrameProbe.fenceUpdated();",
    "MetalFrameProbe.fenceWaited();",
))
if render_pass.index("MetalFrameProbe.pipelineBound(pipelineHandle.address());") > render_pass.index("enc.setRenderPipelineState(pipelineHandle);"):
    raise SystemExit("binding counters: the pipeline count is not taken where the pipeline is pushed")
if render_pass.index("MetalFrameProbe.scissorSet(x, y, width, height);") < render_pass.index("private static void setScissor("):
    raise SystemExit("binding counters: the scissor count is not taken inside the one road that sets a scissor")
if render_pass.count("enc.setScissorRect(") != 1:
    raise SystemExit("binding counters: a scissor reaches the encoder on a road the census does not count")
for label, needle in (
    ("vertex buffer", "MetalFrameProbe.bufferBound(nativeVertexBuffer.metalBuffer().handle().address(),"),
    ("direct buffer", "MetalFrameProbe.bufferBound(buffer.handle().address(), offset, (int) index,"),
    ("direct texture", "MetalFrameProbe.textureBound(texture.address(), (int) index,"),
    ("sampled texture", "MetalFrameProbe.textureBound(texture.address(), (int) index, vertex, fragment);"),
):
    if needle not in render_pass:
        raise SystemExit(f"binding counters: the {label} push is not counted where it is pushed")
# Counted by the entry point's name rather than by one of its two forms, because the census added a form that
# carries the value and the argument-buffer road keeps the one that does not: what the counts below assert is
# that every road into each kind is still counted, whichever form it takes.
if render_pass.count("MetalFrameProbe.samplerBound(") != 3:
    raise SystemExit("binding counters: a sampled image carries a sampler on both the direct and the argument path")
if render_pass.count("MetalFrameProbe.textureBound(") != 6:
    raise SystemExit("binding counters: storage and texel-buffer bindings must count as textures too")
if render_pass.count("MetalFrameProbe.bufferBound(") != 5:
    raise SystemExit("binding counters: vertex, uniform, storage and argument buffers must all count as buffers")

# ---------------------------------------------------------------------------
# Counter 4: pipeline compiles per session
#
# One creation site in the named file, timed around the Metal call alone. The descriptor built
# above it is this backend's own work and is not what a driver cost is measured as.
# ---------------------------------------------------------------------------
require("pipeline compile counter", pipeline, (
    "long startNanos = System.nanoTime();",
    "MetalFrameProbe.pipelineCompiled(System.nanoTime() - startNanos);",
))
start = pipeline.index("long startNanos = System.nanoTime();")
created = pipeline.index("compilation.device().newRenderPipelineState(pipelineDesc)")
stopped = pipeline.index("MetalFrameProbe.pipelineCompiled(System.nanoTime() - startNanos);")
if not start < created < stopped:
    raise SystemExit("pipeline compile counter: the Metal pipeline creation is not wrapped by the two timestamps")
if pipeline.count("newRenderPipelineState(") != 1:
    raise SystemExit("pipeline compile counter: a second creation site in this file must be counted as well")

# Counter 5: the same compiles counted OUTSIDE a window, and split by the thread that paid for them.
#
# The window the harness counts opens after the pack's first full frame and a 25 second settle, so every
# compile a load does is invisible to the two counters above - a session whose pack built 187 units reads
# `compiles=0 compileMs=0.00`, which is correct and is the misreading this pair exists to prevent. The split
# by thread is the answer: a worker's compile is work overlapped with the load, a render thread's is a draw
# that asked for a pipeline before the warm-up reached it.
require("frame-probe unarmed compile census", probe, (
    "private static final java.util.concurrent.atomic.AtomicInteger unarmedCompiles =",
    "private static final java.util.concurrent.atomic.AtomicLong unarmedCompileMaxNanos =",
    "private static final java.util.concurrent.atomic.AtomicInteger unarmedRenderCompiles =",
    "unarmedCompiles.incrementAndGet();",
    "unarmedCompileNanos.addAndGet(nanos);",
    "unarmedCompileMaxNanos.accumulateAndGet(nanos, Math::max);",
    "if (RenderSystem.isOnRenderThread()) {",
    "unarmedRenderCompiles.incrementAndGet();",
    "unarmedRenderCompileNanos.addAndGet(nanos);",
    '"unarmedCompiles={} unarmedCompileMs={} unarmedCompileMaxMs={} "',
    '"unarmedRenderCompiles={} unarmedRenderCompileMs={} "',
    "unarmedCompiles.get(),",
    "unarmedRenderCompiles.get(),",
))
# And the other half of a launch's Metal work, which had no clock at all: the MSL to function compile. A
# pipeline is two Metal calls - a function per stage and the pipeline state over them - and timing only the
# second made a whole launch's compilation look like the 25 ms the states cost.
require("frame-probe function compile census", probe, (
    "public static void functionCompiled(final long nanos) {",
    "unarmedFunctions.incrementAndGet();",
    "unarmedFunctionNanos.addAndGet(nanos);",
    "unarmedFunctionMaxNanos.accumulateAndGet(nanos, Math::max);",
    "unarmedRenderFunctions.incrementAndGet();",
    '"unarmedFunctions={} unarmedFunctionMs={} unarmedFunctionMaxMs={} "',
    '"unarmedRenderFunctions={} unarmedRenderFunctionMs={} "',
    "unarmedFunctions.get(),",
    "unarmedRenderFunctions.get(),",
))
metal3 = (ROOT / "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java").read_text(encoding="utf-8")
require("function compile call site", metal3, (
    "long startNanos = System.nanoTime();",
    "MemorySegment function = this.device.newFunction(key.msl(), key.entryPoint());",
    "MetalFrameProbe.functionCompiled(System.nanoTime() - startNanos);",
))
order(
    metal3,
    "MemorySegment function = this.device.newFunction(key.msl(), key.entryPoint());",
    "MetalFrameProbe.functionCompiled(System.nanoTime() - startNanos);",
    "function compile census: the Metal call is not the span the counter is given",
)
if "MetalFrameProbe.functionCompiled" in (
        ROOT / "src/main/java/com/metallum/render/metal4/Metal4CompilationContext.java").read_text(encoding="utf-8"):
    raise SystemExit(
        "function compile census: Metal 4 is frozen and its function cache is left alone on purpose; a "
        "counter added there is work done for a path no decision in the plan is about"
    )
# The split is only real if the unarmed branch stops returning silently: a counter added beside the old
# `return;` and never reached is a field nobody fills, which reads as zero on every pack in the world.
compiled_at = probe.index("public static void pipelineCompiled(final long nanos) {")
unarmed = probe.index("if (!armed()) {", compiled_at)
counter = probe.index("unarmedCompiles.incrementAndGet();", compiled_at)
plain_return = probe.index("return;", unarmed)
if counter < unarmed or counter > plain_return:
    raise SystemExit(
        "frame-probe unarmed compile census: the counter is not inside the branch that runs when the probe "
        "is unarmed, so a load's compiles are still dropped"
    )

# ---------------------------------------------------------------------------
# The argument-buffer binding state shadow
#
# `MetalRenderPass.setArgumentBuffer` skips `MTLArgumentEncoder.setArgumentBuffer` when the encoder
# already holds the buffer it was about to be handed, which the census read as 14400 calls against
# 1200 real changes in one window. The skip is only correct while three facts hold, and each one is
# a way somebody could reasonably break it while the frame still looked right:
#
#   - one MetalRenderPass per logical pass, so the shadow starts empty and cannot outlive its pass;
#   - the layout's buffer is allocated once per pass and never replaced under the shadow;
#   - a pipeline change clears the shadow, because the MTLArgumentEncoder objects belong to the
#     compiled pipeline and are shared between the passes that use it.
#
# This is the mutation the contract was written against: make the map survive a pass (hoist it to a
# static, or drop the per-pass construction) and a stale target would be read by the next pass.
# ---------------------------------------------------------------------------
if render_pass.count("argEncoderTargets.get(") != 1:
    raise SystemExit(
        "argument-buffer binding state: the skip is not decided in exactly one place, so a second "
        "site could skip a set the encoder really needed"
    )
order(
    render_pass,
    "layout.encoder().setArgumentBuffer(buffer, 0L);",
    "argEncoderTargets.put(layout.encoder(), buffer);",
    "argument-buffer binding state: the map records the buffer before the encoder is told about it, "
    "so a throw between the two leaves a map claiming a binding the encoder never took",
)
if "private final java.util.IdentityHashMap<Object, MTLBuffer> argEncoderTargets" not in render_pass:
    raise SystemExit(
        "argument-buffer binding state: the shadow is not an instance field of the pass, so it "
        "survives the pass that recorded it and the next pass reads a target it never set"
    )
if render_pass.count("argEncoderTargets.clear();") != 1:
    raise SystemExit(
        "argument-buffer binding state: the shadow is not cleared exactly once, where the pipeline "
        "changes -- an argument encoder belongs to a compiled pipeline and is shared by every pass "
        "that uses it, so a shadow kept across a pipeline change is a buffer the encoder no longer has"
    )
order(
    render_pass,
    "this.argumentBufferStates.clear();",
    "this.argEncoderTargets.clear();",
    "argument-buffer binding state: the shadow is cleared before the buffers it names, so the two "
    "halves of one pipeline change are cleared in an order nothing pins",
)
if encoder.count("MetalRenderPass renderPass = new MetalRenderPass(") != 1:
    raise SystemExit(
        "argument-buffer binding state: the pass is no longer built fresh for every logical pass -- a "
        "pooled or reused pass carries the shadow of the pass before it, and the encoder it names holds "
        "another pass's buffer"
    )
if render_pass.count(".setArgumentBuffer(") != 1:
    raise SystemExit(
        "argument-buffer binding state: a second call to MTLArgumentEncoder.setArgumentBuffer exists "
        "in this file, which the shadow does not track"
    )

# ---------------------------------------------------------------------------
# No shader-pack vocabulary
#
# The backend describes Metal, and a probe that named a shader-pack concept would move the seam.
# The repo-wide refusal is in this file, above; this repeats it on the files the frame
# probe touches so the reason travels with the contract. The names are spelled in full because
# `colortex0` is forbidden while `colorTexture` is the backend's own word for an attachment.
# ---------------------------------------------------------------------------
forbidden_vocabulary = (
    "colortex0", "colortex1", "colortex2", "colortex2clear",
    "shadowtex0", "shadowtex1", "shadowcolor0", "shadowcolor1",
    "gbuffers_", "depthtex0", "depthtex1", "depthtex2",
)
for forbidden in forbidden_vocabulary:
    for name, text in (
        (PROBE_PATH, probe),
        ("MetalCommandEncoder.java", encoder),
        ("MTLCommandBuffer.java", command_buffer),
        ("MetalRenderPass.java", render_pass),
        ("MTLRenderCommandEncoder.java", render_encoder),
        ("MetalCompiledRenderPipeline.java", pipeline),
    ):
        if forbidden in text.lower():
            raise SystemExit(f"frame probe contract leaked shader-pack semantics into {name}: {forbidden}")

# --- the per-frame pacing analysis, which is what classifies a window's populations ------------------------
# The frame path writes one `M4_FRAME` line a frame and one `M4_FRAME_COMMIT` a submission, and
# `tools/metal4-pacing-analysis.py` reads them and splits the frames by what they waited on. Two properties
# matter and both are pinned here rather than trusted: the analyser must need every field the line carries (a
# field dropped from the regex would silently stop being classified), and it must refuse rather than print
# numbers for a session whose arms never wrote a line.
PACING = ROOT / "tools" / "metal4-pacing-analysis.py"
if not PACING.is_file():
    raise SystemExit("frame probe contract: the per-frame pacing analyser is gone, so a window whose periods "
                     "fall into two populations cannot be told from one that is merely wide")
pacing = PACING.read_text(encoding="utf-8")
for field in ("frame", "slots", "slot", "submission", "wallUs", "slotWaitUs", "drawableWaitUs", "encodeUs",
              "passes", "encoders", "tables", "draws"):
    if f'"{field}"' not in pacing.split("FRAME_RE")[0]:
        raise SystemExit(f"frame probe contract: the pacing analyser no longer reads the {field} field, so a "
                         "classification built on the line would be built on some of it")
if "no M4_FRAME lines - is -Dmetallum.metal4FrameTrace=true in that arm?" not in pacing:
    raise SystemExit("frame probe contract: the pacing analyser no longer says which switch a session is "
                     "missing, so an arm that was never traced reads as an arm with no frames")
if "pacing analysis: no arm in this session wrote a per-frame line" not in pacing:
    raise SystemExit("frame probe contract: the pacing analyser would print a table for a session with no "
                     "per-frame lines at all")
for needle, why in (
    ("M4_FRAME frame={} slots={} slot={} submission={} wallUs={} slotWaitUs={}",
     "the per-frame line is gone, so the analyser has nothing to read"),
    ("public int slots() {", "the ring cannot say how deep it is, so a pooled line could not be read across "
                            "depths"),
    ("public long lastSlotWaitNanos() {", "the ring no longer keeps the frame's own slot wait"),
):
    metal4_encoder = read("src/main/java/com/metallum/render/metal4/Metal4FrameEncoder.java")
    metal4_ring = read("src/main/java/com/metallum/mtl/metal4/MTL4FrameRing.java")
    if needle not in metal4_encoder and needle not in metal4_ring:
        raise SystemExit("frame probe contract: " + why)

# --- the client tick, which is what a window's content is normalised by --------------------------------
# A window is a fixed frame count and this client's frame is not the same work every frame: the no-pack frame is
# 7 passes in the steady state and 13 on a client tick, so content is `a*frames + b*ticks` and two arms whose
# frame rates differ sample different numbers of ticks. The mixin is the only road from the client's own clock
# into the probe, and its absence would leave the drift unexplained rather than explained.
TICK_MIXIN = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mixin" / "render" / "ClientTickProbeMixin.java"
MIXINS_JSON = ROOT / "src" / "main" / "resources" / "metallum.mixins.json"
if not TICK_MIXIN.is_file():
    raise SystemExit("frame probe: the client-tick mixin is gone, so no window can say how many of the client's "
                     "ticks it covered")
tick_mixin = TICK_MIXIN.read_text(encoding="utf-8")
for needle, why in (
    ('@Inject(method = "tick()V", at = @At("HEAD"))',
     "the mixin no longer injects at the client's own tick, so the count would be of something else"),
    ("MetalFrameProbe.gameTick();", "the client tick is no longer reported to the probe"),
):
    if needle not in tick_mixin:
        raise SystemExit("frame probe: " + why)
if '"render.ClientTickProbeMixin"' not in MIXINS_JSON.read_text(encoding="utf-8"):
    raise SystemExit("frame probe: the client-tick mixin is not registered, so it never loads and every window "
                     "would report no ticks")
for needle, why in (
    ("public static void gameTick() {", "the probe has no client-tick entry point"),
    ("windowTicks={} framesPerTick={}", "the window line no longer carries the tick count, so the sampling "
                                       "difference the drift is made of cannot be read"),
    ("                ticks - windowStartedAtTick,",
     "the reported tick count is not the window's own span, so a window would report the process's ticks rather "
     "than the ones it covered"),
):
    if needle not in probe:
        raise SystemExit("frame probe: " + why)

# --- the depth-bias census, which has to exist on both passes --------------------------------------------
# `run/sign-nopack3` reads `depthBias=600` on both generations, and that symmetry is the whole reading: the
# Metal 3 pass counts the same non-zero bias the Metal 4 pass does, so "the reference applied it too" is a
# measurement rather than an assumption. The Metal 4 pass has counted since the call was bound; the Metal 3
# pass counts now, in the same place and under the same condition, and a regression that dropped either side
# would leave the parity claim resting on one arm.
for needle, why in (
    ("compiledPipeline.depthBiasConstant() != 0.0f", "the Metal 3 pass no longer asks whether the pipeline it "
     "just bound carries a depth bias, so a live frame that asks for one is no longer counted on the reference"),
    ("MetalFrameProbe.depthBiasApplied();", "the Metal 3 pass no longer reports the bias it applies, so "
     "`depthBias=` in a window line is the Metal 4 path's count alone and the two generations cannot be "
     "compared on a biased frame"),
):
    if needle not in render_pass:
        raise SystemExit("frame probe: " + why)
if render_pass.index("compiledPipeline.depthBiasConstant() != 0.0f") > render_pass.index(
        "MetalFrameProbe.depthBiasApplied();"):
    raise SystemExit("frame probe: the Metal 3 pass counts the bias before it has read the pipeline's values, so "
                     "the count is not the pipelines that actually asked for one")

print("Metal frame-probe instrumentation contract: PASS")

# ==================== was tools/ci-compute-storage.py ====================






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
# The generation-reach ledger in `ci-repo.py` refuses a class in `com.metallum.render` that names a
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
closes = device.count("services.closePresentPath()")
if closes != 1:
    raise SystemExit(
        f"the present path is closed {closes} times in MetalDevice, and the device owns exactly one of them"
    )

print("PHASE 15 generic Metal Compute / Storage contracts: PASS")

# ==================== was tools/ci-graphics-storage-images.py ====================

render = (ROOT / "src/main/java/com/metallum/render/metal3/MetalRenderPass.java").read_text(encoding="utf-8")
command = (ROOT / "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java").read_text(encoding="utf-8")
compute = (ROOT / "src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java").read_text(encoding="utf-8")

if render.count("noteGraphicsStorageImageWrite(textureView);") != 2:
    raise SystemExit("direct and argument-buffer graphics storage-image paths must both invalidate ownership state")
for needle in (
    "((MetalGpuTexture) textureView.texture()).markContentsDirty();",
    "this.graphicsStorageImageWrites = true;",
    "boolean hasGraphicsStorageImageWrites()",
):
    if needle not in render:
        raise SystemExit("missing graphics storage-image ownership contract: " + needle)
if "((MetalGpuTexture) view.texture()).markContentsDirty();" not in compute:
    raise SystemExit("compute storage-image writes no longer invalidate texture clear state")

# The boundary an imageStore owes is decided by the pass that READS it, not by the pass that wrote
# it. Breaking the encoder at the write pays the whole boundary - every attachment of the next pass
# reloaded and stored again - on passes that read no storage image at all. What keeps that honest is
# the default: a pass nobody described asks for the boundary rather than going without one, because
# an unordered read of an untracked write is a wrong image and not a slower frame.
submit = command.index("public void submitRenderPass()")
flag = command.index("currentRenderPass.hasGraphicsStorageImageWrites()", submit)
closed = command.index("currentRenderPass = null;", flag)
if "this.storageUnordered = true;" not in command:
    raise SystemExit("graphics storage-image writes are no longer remembered for the pass that reads them")
remembered = command.index("this.storageUnordered = true;", closed)
if not submit < flag < closed < remembered:
    raise SystemExit("graphics storage-image writes are no longer remembered for the pass that reads them")
if "if (this.storageUnordered && readsStorageImage) {" not in command:
    raise SystemExit("the graphics storage-image boundary is not owed by the pass that reads")
create = command.index("public @NonNull RenderPassBackend createRenderPass(")
submit_at = command.index("public void submitRenderPass()")
if not create < command.index("this.storageUnordered && readsStorageImage") < submit_at:
    raise SystemExit(
        "the boundary a storage write owes is not decided where the pass that reads it is built"
    )
if "private boolean nextPassReadsStorageImage = true;" not in command:
    raise SystemExit("a pass nobody described no longer asks for the storage-image boundary")
if "this.nextPassReadsStorageImage = true;" not in command:
    raise SystemExit("one pass's storage-image answer is not reset before the next pass")
if command.count("storageUnordered = false;") != 2:
    raise SystemExit("the boundary a storage write owes does not leave with the encoder it was owed to")

for forbidden in ("Photon", "photon", "colorimg", "gbuffers_", "shadowtex"):
    if forbidden in render or forbidden in command:
        raise SystemExit("graphics storage-image backend contract leaked shader-pack semantics: " + forbidden)

print("Metal graphics storage-image ownership/synchronization contract: PASS")

# ==================== was tools/ci-argument-buffer-samplers.py ====================

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

# ==================== was tools/ci-shader-diagnostics.py ====================

DEVICE = ROOT / "src/main/java/com/metallum/render/MetalDevice.java"
COMPILATION = ROOT / "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java"
CROSS = ROOT / "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java"
# The stripper moved to the shared layer with the Metal 4 compilation chain: two generations prepare
# GLSL the same way, and neither may reach into the other's package for the helper.
STRIPPER = ROOT / "src/main/java/com/metallum/render/shared/GlslCommentStripper.java"
STRIPPER_PACKAGE = "com.metallum.render.shared"
source = COMPILATION.read_text(encoding="utf-8")
cross_source = CROSS.read_text(encoding="utf-8")

required = (
    'Pattern.compile("\\\\b\\\\d+:(\\\\d+):")',
    "shaderCompileFailure(k.id(), sourceWithDefines, e)",
    'new StringBuilder("GLSL source around line ")',
    'line == failingLine ? ">> " : "   "',
    'String.format(Locale.ROOT, "%5d | %s", line, lines[line - 1])',
    "GlslCommentStripper.strip(source).stripLeading()",
)
missing = [needle for needle in required if needle not in source]
if missing:
    raise SystemExit("shader compile diagnostic contract missing: " + ", ".join(missing))

if 'new IllegalStateException(shaderCompileFailure(k.id(), sourceWithDefines, e), e)' not in source:
    raise SystemExit("shader compile diagnostics must preserve ShaderCompileException as the cause")
if "BLOCK_COMMENTS" in source or "LINE_COMMENTS" in source:
    raise SystemExit("shader preparation must not use independent block/line comment regexes")

pad_option = "Spvc.SPVC_COMPILER_OPTION_MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS"
pad_index = cross_source.find(pad_option)
if pad_index < 0:
    raise SystemExit("Metal fragment outputs must enable SPIRV-Cross component padding")
if cross_source.count(pad_option) != 1:
    raise SystemExit("Metal fragment-output padding option must be configured exactly once")
fragment_gate = "if (executionModel == Spv.SpvExecutionModelFragment)"
gate_index = cross_source.rfind(fragment_gate, 0, pad_index)
if gate_index < 0 or pad_index - gate_index > 300:
    raise SystemExit("Metal fragment-output padding must be scoped to fragment MSL compilation")
if '"spvc_compiler_options_set_bool(MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS)"' not in cross_source:
    raise SystemExit("Metal fragment-output padding must retain a named SPIRV-Cross failure stage")

harness = textwrap.dedent(
    r'''
    package com.metallum.render.shared;

    public final class GlslCommentStripperContract {
        public static void main(String[] args) {
            String toggle = "//*\nfloat active = 1.0;\n//*/\n";
            String toggleOut = stripSameLines("toggle-active", toggle);
            require("toggle-active", toggleOut.contains("float active = 1.0;"));
            require("toggle-active", toggleOut.lines().noneMatch(line -> line.strip().equals("/")));

            String disabled = "/*\nfloat hidden = 1.0;\n//*/\nfloat active = 2.0;\n";
            String disabledOut = stripSameLines("toggle-disabled", disabled);
            require("toggle-disabled", !disabledOut.contains("float hidden"));
            require("toggle-disabled", disabledOut.contains("float active = 2.0;"));

            String lineWithBlockText = "float a = 1.0; // mention /* without close\nfloat b = 2.0;\n";
            String lineWithBlockTextOut = stripSameLines("line-block-text", lineWithBlockText);
            require("line-block-text", lineWithBlockTextOut.contains("float a = 1.0;"));
            require("line-block-text", lineWithBlockTextOut.contains("float b = 2.0;"));
            require("line-block-text", !lineWithBlockTextOut.contains("mention"));

            String blockWithLineText = "float a = 1.0; /* // text */ float b = 2.0;\n";
            String blockWithLineTextOut = stripSameLines("block-line-text", blockWithLineText);
            require("block-line-text", blockWithLineTextOut.contains("float a = 1.0;"));
            require("block-line-text", blockWithLineTextOut.contains("float b = 2.0;"));
            require("block-line-text", !blockWithLineTextOut.contains("text"));

            String splice = "float a = 1.0; // continued " + '\\' + "\n/ still comment\nfloat b = 2.0;\n";
            String spliceOut = stripSameLines("splice", splice);
            require("splice", !spliceOut.contains("still comment"));
            require("splice", spliceOut.contains("float b = 2.0;"));
            require("splice", spliceOut.lines().noneMatch(line -> line.strip().equals("/")));

            checkExact("division", "float c = a / b;\n", "float c = a / b;\n");
            String separation = GlslCommentStripper.strip("int value = a/**/b;\n");
            require("token-separation", separation.matches("(?s).*a\\s+b;.*"));

            String unterminated = "float a; /* keep compiler error";
            checkExact("unterminated", unterminated, unterminated);
        }

        private static String stripSameLines(String label, String source) {
            String actual = GlslCommentStripper.strip(source);
            long before = source.chars().filter(c -> c == '\n').count();
            long after = actual.chars().filter(c -> c == '\n').count();
            if (before != after) {
                throw new AssertionError(label + ": line count changed from " + before + " to " + after);
            }
            return actual;
        }

        private static void checkExact(String label, String source, String expected) {
            String actual = GlslCommentStripper.strip(source);
            if (!expected.equals(actual)) {
                throw new AssertionError(label + " expected [" + expected + "] but got [" + actual + "]");
            }
        }

        private static void require(String label, boolean condition) {
            if (!condition) {
                throw new AssertionError(label);
            }
        }
    }
    '''
).strip() + "\n"

with tempfile.TemporaryDirectory(prefix="metallum-shader-comments-") as tmp:
    root = Path(tmp)
    package_dir = root / STRIPPER_PACKAGE.replace(".", "/")
    package_dir.mkdir(parents=True)
    contract = package_dir / "GlslCommentStripperContract.java"
    contract.write_text(harness, encoding="utf-8")
    out = root / "out"
    subprocess.run(["javac", "-d", str(out), str(STRIPPER), str(contract)], check=True)
    subprocess.run(
        ["java", "-cp", str(out), STRIPPER_PACKAGE + ".GlslCommentStripperContract"],
        check=True,
    )

print("shader compile diagnostic/comment/fragment-output contract: PASS")

# ==================== was tools/ci-metalfx.py ====================
"""Pins how this backend finds out whether it can scale a frame with MetalFX.

MetalFX is a framework of its own rather than a part of Metal, and this backend reaches Objective-C
through `objc_getClass`, which sees only the images that are already loaded. So the availability question
has three ways to come out false - no framework, a framework without the class, or a device that cannot
run the scaler - and every one of them has to be an answer rather than an exception, because a system
without MetalFX is a system this engine runs on. Availability is asked of Apple's own question on the
device and never of a version number, and the answer is said out loud, because "this Mac cannot do it"
and "this build cannot do it" are different sentences.
"""

METAL_FX = ROOT / "src/main/java/com/metallum/render/MetalFx.java"
OBJC = ROOT / "src/main/java/com/metallum/objc/ObjC.java"
CI = ROOT / ".github/workflows/ci.yml"

metal_fx = METAL_FX.read_text(encoding="utf-8")
objc = OBJC.read_text(encoding="utf-8")
device = DEVICE.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# The image is loaded, and its absence is an answer
#
# `SymbolLookup.libraryLookup` is the dlopen, and it is what makes the classes visible at all. On a
# system without MetalFX it throws, so this framework alone is asked for through the optional road: an
# engine that cannot run one optional effect must not fail to start because of it.
# ---------------------------------------------------------------------------
if "public static SymbolLookup optionalLibrary(final String path)" not in objc:
    raise SystemExit("the runtime interface no longer has a road for a framework an engine can live without")
if "catch (IllegalArgumentException | UnsatisfiedLinkError missing)" not in objc:
    raise SystemExit("the optional framework road does not catch the two ways a missing image reports itself")
if 'ObjC.optionalLibrary("/System/Library/Frameworks/MetalFX.framework/MetalFX")' not in metal_fx:
    raise SystemExit("MetalFX's image is not loaded through the optional road")
if "SymbolLookup.libraryLookup(LOAD" in metal_fx or "METAL_FX.findOrThrow" in metal_fx:
    raise SystemExit("MetalFX is loaded or looked up in a way that throws when the system has no such framework")

# ---------------------------------------------------------------------------
# Availability is asked of the device, never of a version
#
# Apple's own question is `+[MTLFXSpatialScalerDescriptor supportsDevice:]`, and it is false on a GPU
# that cannot run the scaler whatever the system says. A version table here would be a second opinion
# that goes stale on the next system and cannot see the hardware at all.
# ---------------------------------------------------------------------------
if 'Msg.of("supportsDevice:", JAVA_LONG, ADDRESS)' not in metal_fx:
    raise SystemExit("the device is not asked Apple's own support question")
if "SUPPORTS_DEVICE.sendLong(scalerClass, device)" not in metal_fx:
    raise SystemExit("the support question is not asked of the scaler's own class object")
for forbidden in ("os.version", "System.getProperty(\"os", "MACOS_VERSION", "isAtLeast"):
    if forbidden in metal_fx:
        raise SystemExit(f"MetalFX availability is decided by {forbidden} rather than by asking the device")

# ---------------------------------------------------------------------------
# A class this backend only asks about is not a class it requires
#
# `ObjC.clazz` throws for a name nothing answers to, which is right for Metal and wrong for a framework
# that may not be installed.
# ---------------------------------------------------------------------------
if "private static MemorySegment classOrNull(final String name)" not in metal_fx:
    raise SystemExit("the descriptor class is fetched without a road for it being absent")
if "return ObjC.clazz(name);" not in metal_fx or "catch (Throwable missing)" not in metal_fx:
    raise SystemExit("the descriptor class is asked for in a way that throws when nothing answers")

# ---------------------------------------------------------------------------
# Asked once, kept, and said out loud
#
# The answer is a fact about the device and the system rather than about a frame, so it is asked at
# device creation and remembered; and it is logged either way, because the reason is what a reader needs
# when a session cannot scale.
# ---------------------------------------------------------------------------
if "if (asked) {" not in metal_fx or "asked = true;" not in metal_fx:
    raise SystemExit("the availability answer is asked more than once, or not kept")
if "public static String reason()" not in metal_fx:
    raise SystemExit("the reason for the answer is not available to a caller or a screen")
if 'Metallum.LOGGER.info("MetalFX spatial scaling: available, {}, factory {}"' not in metal_fx:
    raise SystemExit("availability is decided silently")
if 'Metallum.LOGGER.info("MetalFX spatial scaling: unavailable, {}"' not in metal_fx:
    raise SystemExit("a system that cannot scale is not told why")
if "MetalFx.spatialSupported(metalDeviceHandle);" not in device:
    raise SystemExit("the device never asks whether it can scale, so the answer is never reached")

# ---------------------------------------------------------------------------
# A scaler per configuration, and the selector is asked for rather than assumed
#
# Making a scaler compiles its own pipeline, so one a frame would be a per-frame compile: the cache is
# keyed by everything that would make a different scaler, and a configuration the device refused is
# remembered as refused rather than retried every frame. The factory's Objective-C selector is asked of
# the class, because the documentation names it in Swift and a wrong guess is a silent nil.
# ---------------------------------------------------------------------------
require = lambda label, source, needles: [
    needle for needle in needles if needle not in source
] and (_ for _ in ()).throw(SystemExit(f"{label}: missing " + ", ".join(
    needle for needle in needles if needle not in source)))

descriptor = (ROOT / "src/main/java/com/metallum/mtl/MTLFXSpatialScalerDescriptor.java").read_text(encoding="utf-8")
scaler = (ROOT / "src/main/java/com/metallum/mtl/MTLFXSpatialScaler.java").read_text(encoding="utf-8")

require("the factory is asked for, not assumed", descriptor, (
    '"newSpatialScalerWithDevice:"',
    '"makeSpatialScalerWithDevice:"',
    'RESPONDS_TO_SELECTOR.sendLong(scalerClass, ObjC.selector(selector))',
))
if "Msg.of(selector, ADDRESS, ADDRESS).sendPtr(handle, device)" not in descriptor:
    raise SystemExit("the factory is not the selector the class answered to")

require("the scaler is encoded in Apple's order", scaler, (
    'Msg.ofVoid("setColorTexture:", ADDRESS)',
    'Msg.ofVoid("setOutputTexture:", ADDRESS)',
    'Msg.ofVoid("setInputContentWidth:", JAVA_LONG)',
    'Msg.ofVoid("setInputContentHeight:", JAVA_LONG)',
    'Msg.ofVoid("encodeToCommandBuffer:", ADDRESS)',
))

require("one scaler per configuration", metal_fx, (
    "private record Configuration(",
    "private static final Map<Configuration, MTLFXSpatialScaler> scalers = new LinkedHashMap<>();",
    "private static final Map<Configuration, Boolean> refused = new LinkedHashMap<>();",
    "refused.put(configuration, Boolean.TRUE);",
    "scalers.put(configuration, scaler);",
    "public static void close() {",
))
if "MetalFx.close();" not in device:
    raise SystemExit("the cached scalers are not released when the device goes down")

# The per-file "is this script named by ci.yml" guard that stood here is now one guard over
# every tools/ci-*.py in ci-repo.py: the same claim, made once and over all of them.

# ---------------------------------------------------------------------------
# The door reflection can enter, and no selector sent blind
#
# Two faults found by running it. The pack-facing side reflects into this backend, and reflection cannot
# enter a package-private class however public the method on it is: the capabilities that already worked
# exposed a public class of their own, and so do these two. And a selector an object does not answer to
# is not a wrong number - it is an Objective-C exception that ends the process, which is what
# setInputContentOriginX: did when the spatial scaler was asked to move its content rectangle it does not
# have. Both rules are pinned here so a later edit cannot quietly unlearn them.
#
# A third fault was found the same way, and it is the reason the attachment door takes primitives. It used
# to take this layer's own value type, which the pack-facing side built by reflection from a class name -
# `com.metallum.render.AttachmentContents`, a path that does not exist, because the type is in
# `render.shared`. The lookup threw, every call was caught, and every pass silently kept its default for as
# long as the name was wrong. A name resolved at runtime is not an ABI; two arrays of booleans are.
# ---------------------------------------------------------------------------
require("the MetalFX door is public", (ROOT / "src/main/java/com/metallum/render/MetalScaleBridge.java").read_text(encoding="utf-8"), (
    "public final class MetalScaleBridge {",
    "public static boolean available(final Object encoder)",
    "public static boolean scale(",
))
attachment_door = (ROOT / "src/main/java/com/metallum/render/MetalAttachmentBridge.java").read_text(encoding="utf-8")
require("the attachment door is public", attachment_door, (
    "public final class MetalAttachmentBridge {",
    "public static void setNextPassContents(final Object encoder, final @Nullable boolean[] readAfterwards,",
    "final @Nullable boolean[] overwritten) {",
    "public static void setNextPassReadsStorageImage(final Object encoder",
))
if "setNextPassContents(final Object encoder, final @Nullable AttachmentContents[]" in attachment_door:
    raise SystemExit(
        "the attachment door hands this layer's own value type across a repository boundary, where it can only "
        "be resolved by name - and a name that moves stops answering without failing, which is the fault this "
        "door already had once"
    )
if "RESPONDS_TO_SELECTOR.sendLong(handle, ObjC.selector(\"setInputContentOriginX:\"))" not in scaler:
    raise SystemExit(
        "the scaler sends a selector it may not answer to; an unrecognized one is an Objective-C exception and ends the process"
    )

# ---------------------------------------------------------------------------
# The fence Apple documents for a resource Metal does not track
#
# Every texture this backend creates opts out of hazard tracking, which the documentation allows only
# on its own terms - the app then synchronises through a fence. The scaler is the one encoder in a
# frame that is not one of this engine's own, and MetalFX declares the property for exactly that case:
# `MTLFXSpatialScaler.fence` is the fence "this scaler waits for and updates". Without it the upscale's
# read of the input and write of the output sit in no part of the engine's fence chain, so a frame can
# sample an input that is still being stored or an output the scaler has not written yet. The binding
# still asks before it sends, for the reason above: an unrecognised selector ends the process.
# ---------------------------------------------------------------------------
require("the scaler takes a fence", scaler, (
    'Msg.ofVoid("setFence:", ADDRESS)',
    'ObjC.selector("setFence:")',
    "SET_FENCE.send(handle, fence)",
))
require("the encoder hands the frame's fence to the scaler",
        (ROOT / "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java").read_text(encoding="utf-8"), (
    "MetalFx.scale(device.metalDeviceHandle(), commandBuffer().handle(), fence.handle(), color,",
))
require("the scaler is given it before it encodes", (ROOT / "src/main/java/com/metallum/render/MetalFx.java").read_text(encoding="utf-8"), (
    "if (!scaler.fence(fence) && !fenceRefused) {",
))

# ---------------------------------------------------------------------------
# The Metal 4 scaler is a second path and not a parameter of the first
#
# Section 80: the logical configuration key may be shared, the native objects may not, because a scaler compiles
# its own pipeline and one generation's compiled pipeline is not the other's. So the Metal 4 path has its own
# class, its own cache and its own factory - and the factory needs a compiler object, which is the whole of the
# API difference the header declares (macOS 26's MTL4FXSpatialScaler.h takes an MTL4CommandBuffer, and the
# descriptor's Metal 4 spelling is `newSpatialScalerWithDevice:compiler:`).
#
# Its availability question is a functional one on purpose. `+supportsMetal4FX:` is Apple's own gate, and a
# device that answers yes can still refuse a scaler - so the answer reported to the capability record is the one
# that actually made a scaler and let it go. A `respondsTo`-only answer would tell the record that choosing
# Metal 4 keeps the render-scale setting while the device refuses every scaler it is asked for.
#
# And there is no fence on this path, which is a difference the two generations' APIs force rather than a
# preference: Metal 4 has no fence object in this engine at all - Metal4Fence records that the new command model
# orders work with encoder barriers and queue events - so what orders the scaler against the passes around it is
# the one command buffer's encode order. The pin holds that the Metal 4 scaler is never handed a Metal 3 fence.
# ---------------------------------------------------------------------------
METAL4_FX = ROOT / "src/main/java/com/metallum/mtl/metal4/Metal4Fx.java"
M4_SCALER = ROOT / "src/main/java/com/metallum/mtl/metal4/MTL4FXSpatialScaler.java"
M4_COMPILER = ROOT / "src/main/java/com/metallum/mtl/metal4/MTL4Compiler.java"
for path in (METAL4_FX, M4_SCALER, M4_COMPILER):
    if not path.is_file():
        raise SystemExit(f"the Metal 4 MetalFX path is missing {path.name}, so one generation of the scaler "
                         "has no implementation")

metal4_fx = METAL4_FX.read_text(encoding="utf-8")
m4_scaler = M4_SCALER.read_text(encoding="utf-8")
m4_compiler = M4_COMPILER.read_text(encoding="utf-8")
m4_encoder = (ROOT / "src/main/java/com/metallum/render/metal4/Metal4FrameEncoder.java").read_text(encoding="utf-8")

require("the Metal 4 scaler asks Apple's Metal 4 gate", metal4_fx, (
    'Msg.of("supportsMetal4FX:", JAVA_LONG, ADDRESS)',
    "if (!MTL4Probe.respondsTo(scalerClass, \"supportsMetal4FX:\")) {",
    "SUPPORTS_METAL4_FX.sendLong(scalerClass, device) == 0L",
))
require("the Metal 4 factory is the header's", metal4_fx, (
    'Msg.of("newSpatialScalerWithDevice:compiler:", ADDRESS, ADDRESS, ADDRESS)',
    'MTL4Probe.respondsTo(descriptor.handle(),\n                    "newSpatialScalerWithDevice:compiler:")',
    "NEW_SCALER_WITH_COMPILER.sendPtr(descriptor.handle(), device,",
))
require("availability is a functional question", metal4_fx, (
    "MTL4Compiler probeCompiler = MTL4Compiler.create(new MTLDevice(device));",
    "MTL4FXSpatialScaler probe = makeScaler(device, probeCompiler, new Configuration(1280, 720, 1920, 1080,",
    "supported = true;",
))
require("the Metal 4 path keeps its own scalers", metal4_fx, (
    "private final Map<Configuration, MTL4FXSpatialScaler> scalers = new LinkedHashMap<>();",
    "private final Map<Configuration, Boolean> refused = new LinkedHashMap<>();",
    "this.scalers.put(configuration, scaler);",
))
if "MetalFx." in metal4_fx or "MTLFXSpatialScaler " in metal4_fx:
    raise SystemExit(
        "the Metal 4 scaler path names the Metal 3 one, so the two generations share a native scaler - section 80 "
        "forbids it, and a shared compiled pipeline is the shape that would make it look fine until a resize"
    )
require("the Metal 4 scaler encodes into a Metal 4 command buffer", m4_scaler, (
    'Msg.ofVoid("encodeToCommandBuffer:", ADDRESS)',
    "ENCODE.send(this.handle, commandBuffer);",
    'RESPONDS_TO_SELECTOR.sendLong(this.handle, ObjC.selector("setInputContentOriginX:"))',
))
if "setFence:" in m4_scaler:
    raise SystemExit(
        "the Metal 4 scaler is handed a fence, and Metal 4 has no fence object in this engine: the ordering it "
        "would be given does not exist on this path"
    )
require("the compiler factory is the header's and every failure is an answer", m4_compiler, (
    'Msg.of("newCompilerWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS)',
    'device.respondsTo("newCompilerWithDescriptor:error:")',
    "if (ObjC.isNil(made)) {",
))
# A scaler is made on a cache miss and a miss is a rare event - the configuration changed - which makes one
# line per configuration the only evidence a resize or a render-scale change leaves. Measured: a 55% session with
# a mid-session resize logs `made a scaler for 1408x792 to 2560x1440 ... 1 in the cache` and then
# `1760x990 to 3200x1800 ... 2 in the cache`, which is section 81's identity separating two configurations and
# section 124's resize rebuild happening rather than an old scaler being reused. The pin holds the line, because
# nothing else in the log can show it and an edit that dropped it would leave the claim unreadable.
require("a scaler's creation is said once per configuration", metal4_fx, (
    "Metal 4 MetalFX spatial scaling: made a scaler for {}x{} to {}x{} with colour",
    "this.scalers.size());",
    "configuration.inputWidth(), configuration.inputHeight(), configuration.outputWidth(),",
))

require("the frame path uses its own scaler and no fence", m4_encoder, (
    "this.metalFx = Metal4Fx.create(nativeDevice);",
    "return !this.closed && this.metalFx != null;",
    "return this.metalFx.scale(this.ring.commandBuffer(), color.nativeHandle(), output.nativeHandle(),",
    "if (this.metalFx != null) {\n            this.metalFx.close();",
))
if "MetalFx.scale(" in m4_encoder:
    raise SystemExit(
        "the Metal 4 frame path calls the Metal 3 scaler's encode, which takes an MTLCommandBuffer - the wrong "
        "object for this command model"
    )

# And the diagnostic that makes this generation answer "no" about the scaler, which is what turned section 124's
# missing fallback reading into a measured shape: with it set, the Metal 4 core contract is untouched (the
# scaler is an optional capability and not a clause of it) and the session runs Metal 4 with
# `metalFxAvailable()` false - so the reachable road is the pack host's own fallback below 100 per cent, which is
# the road section 124 asked about. Until the post-M4 regression audit the clause was in eligibility and the
# diagnostic refused the generation before a frame was drawn; the contract now pins that clause's absence.
fx = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "Metal4Fx.java"
      ).read_text(encoding="utf-8")
for needle, why in (
    ('Boolean.getBoolean("metallum.probeNoMetalFx")',
     "the MetalFX refusal probe is gone, so the eligibility clause of the Metal 4 gate can no longer be measured"),
    ("so this session answers as a device without Metal FX",
     "the refusal probe no longer says which answer was given, so a session that refused the generation cannot "
     "be told from one whose device really lacks the scaler"),
):
    if needle not in fx:
        raise SystemExit("MetalFX availability contract: " + why)

# ---------------------------------------------------------------------------
# Section 124's live-frame half: the asymmetric fixture, and how a configuration is separated
#
# The orientation of the scaler's output cannot be read from a symmetric pattern - a flat colour, a gradient,
# two halves - because such a pattern can come back flipped, cropped or channel-swapped and still look right.
# `tools/fixtures/metalfx-quadrant` is the fixture that can tell them apart: four quadrants split at the middle
# of both axes, four different colours AND four different alphas, so a flip on either axis, a crop or a channel
# swap changes the arrangement. The pins below are what make that property a contract rather than a comment: a
# later edit that made the pattern symmetric, or that dropped the per-quadrant alpha, would leave the live-frame
# reading passing while measuring nothing.
#
# The second half is section 40's transitions. A cache hit makes no scaler and logs nothing, so what the log can
# show is a *miss* - one line a configuration, with the cache size - and what the code has to guarantee is that
# the lookup is by the whole configuration record and that creation is behind the miss. Both are pinned.
# ---------------------------------------------------------------------------
FIXTURE = ROOT / "tools/fixtures/metalfx-quadrant"
FIXTURE_FRAGMENT = FIXTURE / "shaders/final.fsh"
FIXTURE_README = FIXTURE / "README.md"
for path in (FIXTURE / "shaders/final.vsh", FIXTURE_FRAGMENT, FIXTURE_README):
    if not path.is_file():
        raise SystemExit(f"MetalFX availability contract: the asymmetric fixture is missing {path.name}, so the "
                         "scaler's live-frame orientation cannot be read from a frame at all")
fragment = FIXTURE_FRAGMENT.read_text(encoding="utf-8")
if "texcoord.x > 0.5" not in fragment or "texcoord.y > 0.5" not in fragment:
    raise SystemExit("MetalFX availability contract: the fixture no longer splits both axes, so a flip on one "
                     "axis would be invisible in the frame it paints")
import re as _re

assignments = _re.findall(r"colour = vec4\(([^)]*)\);", fragment)
components = [tuple(part.strip() for part in assignment.split(",")) for assignment in assignments]
if len(components) != 4 or any(len(parts) != 4 for parts in components):
    raise SystemExit("MetalFX availability contract: the fixture no longer assigns four rgba colours, so the "
                     "quadrant count the orientation reading depends on is not fixed by the file")
values = [tuple(float(part.rstrip("fF")) for part in parts) for parts in components]
if len({parts[:3] for parts in values}) != 4:
    raise SystemExit("MetalFX availability contract: the fixture's four quadrants are no longer four different "
                     "colours, which is what makes a channel swap or a crop visible")
if len({parts[3] for parts in values}) != 4:
    raise SystemExit("MetalFX availability contract: the fixture's quadrants no longer carry four different "
                     "alphas, so whether the scaler preserves alpha cannot be read from the frame")
README = FIXTURE_README.read_text(encoding="utf-8")
for needle, why in (
    ("top left red", "the fixture no longer states which corner is which, so the arrangement in the frame is "
                     "not fixed by the file that paints it"),
    ("--renderscale 55", "the fixture no longer says it is run below native, which is what puts the scaler on "
                         "the path and makes input and output resolutions differ"),
    ("drawableReadback", "the fixture no longer says which instrument reads it"),
):
    if needle not in README:
        raise SystemExit("MetalFX availability contract: " + why)

for needle, why in (
    ("MTL4FXSpatialScaler scaler = this.scalers.get(configuration);",
     "the scaler is no longer looked up by the whole configuration, so a resize or a render-scale change could "
     "be served by an old-size scaler"),
    ("if (scaler == null) {\n            scaler = makeScaler(this.device, this.compiler, configuration);",
     "a scaler is made without a cache miss, so a frame could be scaled by an object built for another size"),
    ("made a scaler for {}x{} to {}x{} with colour",
     "a cache miss no longer says which configuration it built, so a resize leaves no evidence and section "
     "40's transition reading has nothing to read"),
    ("{} in the cache", "a cache miss no longer says how many configurations are cached, so the line cannot "
                        "show that a later use of the first one was a hit rather than a third scaler"),
):
    if needle not in metal4_fx:
        raise SystemExit("MetalFX availability contract: " + why)

print("MetalFX availability contract: PASS")
