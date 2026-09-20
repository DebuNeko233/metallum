#!/usr/bin/env python3
"""Pins the Metal 4 execution provider's skeleton: what it owns, what it refuses, and how it is reached.

Phase 2 asks for a generation-specific provider and only a skeleton of one. Two things about that are easy to
undo by accident and expensive to notice:

  - the provider must stay reachable through the NEUTRAL interface, so the services can hand it out for the
    executing generation without learning a Metal 4 type. A provider that grew a Metal 4 command type in a
    signature would put a generation into the shared seam;
  - its unimplemented halves must fail by name. A provider that returned null would move the failure into
    whatever first used the state, twenty calls later, which section 35 of the migration plan forbids and
    which is exactly the distortion the capability probe was rebuilt to remove.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ExecutionProvider.java"
SERVICES = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "execution" / "MetalExecutionServices.java"
HARNESS = ROOT / "tools" / "metal4-cold-probe" / "Metal4ColdProbe.java"

for path in (PROVIDER, SERVICES, HARNESS):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.relative_to(ROOT)} is missing")

provider = PROVIDER.read_text(encoding="utf-8")
services = SERVICES.read_text(encoding="utf-8")
harness = HARNESS.read_text(encoding="utf-8")

# --- it is the neutral interface's implementation, and no generation type leaks into it -----------------
if "implements MetalExecutionProvider" not in provider:
    raise SystemExit("metal 4 provider: the provider does not implement the neutral execution interface, so "
                     "the services cannot hand it out without naming a Metal 4 type")
for signature in ("public long commandQueue(final MTLDevice device)",
                  "public MetalExecutionState createExecutionState(final MTLDevice device)",
                  "public MetalFrameEncoder createFrameEncoder("):
    if signature not in provider:
        raise SystemExit(f"metal 4 provider: the neutral signature '{signature}' is gone, so the provider no "
                         "longer honours the interface a generation-neutral caller uses")
for forbidden in ("render.metal3", "mtl.metal3"):
    if forbidden in provider:
        raise SystemExit(f"metal 4 provider: the provider imports {forbidden}, which the migration plan's "
                         "architecture rules forbid: a Metal 4 implementation must not depend on a Metal 3 one")

# --- the queue is real and a nil one is named -----------------------------------------------------------
if 'Msg.of("newMTL4CommandQueue"' not in provider:
    raise SystemExit("metal 4 provider: the queue factory is not the SDK's own selector, so the provider does "
                     "not own the queue it claims to")
if "throw new Unimplemented(\"commandQueue\"" not in provider:
    raise SystemExit("metal 4 provider: a nil queue is not refused by name, so a device that cannot make one "
                     "would be reported as a process that made nothing")

# --- the state and the encoder exist, and the refusals moved inside them ---------------------------------
# Phase 4 asked for the frame encoder and its state. Both are real objects now, so the pins moved with them:
# what used to be "the provider refuses by name" is now "the provider returns this generation's objects, and
# each object refuses, by name, exactly the operations it does not have". The reason is unchanged - section 35
# forbids an unknown operation being dropped into a half frame - and a provider that returned null for either
# half would still move the failure twenty calls later.
STATE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ExecutionState.java"
ENCODER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4FrameEncoder.java"
for path in (STATE, ENCODER):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so one half of the provider's frame path "
                         "has no implementation at all")

state = STATE.read_text(encoding="utf-8")
encoder = ENCODER.read_text(encoding="utf-8")

if "return new Metal4ExecutionState(device);" not in provider:
    raise SystemExit("metal 4 provider: createExecutionState no longer returns this generation's state")
if "return new Metal4FrameEncoder(device, metal4, defaultShaderSource);" not in provider:
    raise SystemExit("metal 4 provider: createFrameEncoder no longer returns this generation's encoder")
if "instanceof Metal4ExecutionState metal4" not in provider:
    raise SystemExit("metal 4 provider: the encoder is built from a state that was not checked to be this "
                     "generation's, so a Metal 3 state could be handed to a Metal 4 encoder")

# The state: the three operations that are true answers for a cache that holds nothing, and the one that is a
# refusal - which has to carry the operation's name, because "cannot compile yet" and "the caller passed
# nothing" are different facts about the frame path.
for needle, why in (
    ("implements MetalExecutionState", "the state no longer implements the neutral contract the device holds"),
    ("return this.compilation.getOrCompilePipeline(pipeline, source);",
     "the state does not compile through this generation's own chain, so a Metal 4 session would be handed "
     "something built somewhere else"),
    ("return this.compilation.evictCachedPipelines(predicate);",
     "eviction no longer reaches the compilation state, so a pack reload would evict nothing"),
    ("return this.compilation.clearCachesAfterGpuCompletion();" if False else
     "this.compilation.clearCachesAfterGpuCompletion();",
     "the cache clear is gone, so a pack reload or a teardown has no answer"),
    ("this.compilation.close();", "the state has no release, so a teardown has nothing to call"),
):
    if needle not in state:
        raise SystemExit("metal 4 provider: " + why)

# The encoder: the neutral contract, the ring it owns, and a named refusal for every operation it lacks.
if "implements MetalFrameEncoder {" not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not implement the neutral frame contract, so the "
                     "device cannot hold it")
if "implements MetalFrameEncoder, " in encoder:
    raise SystemExit("metal 4 provider: the encoder claims a second contract, and each of the bridges' optional "
                     "contracts is an operation this path cannot perform yet - a bridged caller must find it "
                     "missing and take its own fallback rather than receive a do-nothing body")
for needle, why in (
    ("MTL4FrameRing.create(nativeDevice, MemorySegment.ofAddress(queue), FRAMES_IN_FLIGHT,",
     "the encoder does not make the frame's ring, so the frame's allocator lifetime has no owner"),
    ("device.executionServices().commandQueue(nativeDevice)",
     "the queue no longer comes from the execution services, which is the seam the frame path's isolation "
     "turns on - a generation that made its own queue would put a generation back inside the device"),
    ("private static Metal4ExecutionProvider.Unimplemented unimplemented(final String operation)",
     "the refusals no longer run through one helper, so a new operation can be dropped in without a name"),
    ("this.deferred[slot].add(destroyAction);",
     "a queued release is not filed against a ring slot, so nothing proves the GPU is done with it"),
    ("this.ring.awaitAll()", "the encoder does not wait for the ring before it releases what the GPU may be "
                             "reading"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- the render pass, which is the object a client frame would enter through -----------------------------
# The pass's attachment mapping is measured on the device in the cold probe (four colour attachments, per-slot
# clears, a load across a pass boundary), so what is pinned here is the object over it: that it is the neutral
# contract and only that contract, that it resolves the game's attachments and opens through the measured
# layer, and that every operation it cannot perform refuses by name rather than drawing nothing.
PASS = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4RenderPass.java"
if not PASS.is_file():
    raise SystemExit("metal 4 provider: Metal4RenderPass.java is gone, so createRenderPass has no pass object "
                     "and the frame cannot be entered at all")
pass_source = PASS.read_text(encoding="utf-8")

if "implements RenderPassBackend {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass does not implement the game's render pass contract")
if "implements RenderPassBackend, " in pass_source:
    raise SystemExit("metal 4 provider: the pass claims a second contract, and each of the bridges' optional "
                     "contracts is an operation this path cannot perform yet")
for needle, why in (
    ("MTL4RenderEncoder.open(owner.nativeDevice(), owner.commandBuffer(), width, height,",
     "the pass does not open through the layer whose attachment mapping is measured on the device, so what ran "
     "in the cold probe is not what a frame runs"),
    ("MetalGpuTextureView metal", "the pass does not read the native texture a view names"),
    ("attachment.clearValue().orElse(null)", "the descriptor's clear value is ignored, so a cleared attachment "
                                            "would load what stood there instead"),
    ("descriptor.renderArea", "the render area is not read, so a pass could be opened over an area outside its "
                              "attachments"),
    ("is outside Metal attachment extent", "an area outside the attachments is not refused"),
    ("barrierForSubsequentEncoders()",
     "the pass ends without the producer barrier, so a later pass that reads what it wrote has no encoded "
     "dependency - which section 61 forbids"),
    ("public void pushDebugGroup(final @NonNull Supplier<String> label) {\n    }",
     "the debug group is no longer a no-op: it is a capture label and not work, and refusing it would break a "
     "frame for no correctness reason"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# The no-pack subset is implemented now, so this list is what a no-pack frame does NOT need yet - the multi
# and indirect draw forms, and the counters. They refuse by name rather than disappearing, which is what keeps
# the pass's gaps a list.
for operation in ("setPipeline", "bindTexture", "setUniform", "enableScissor", "disableScissor",
                  "setVertexBuffer", "setIndexBuffer", "draw", "drawIndexed"):
    if f'public void {operation}(' not in pass_source:
        raise SystemExit(f"metal 4 provider: the render pass no longer implements {operation}, which a no-pack "
                         "frame needs")

for needle, why in (
    # Pinned with its body, because the same `begun` test appears in submit() and a bare test would be satisfied
    # by the other occurrence while the frame stopped being begun at all. It is one method now, because the first
    # pass and the first copy both need it.
    ("private void beginFrameIfNeeded() {\n        if (this.ring.begun()) {\n            return;\n        }\n"
     "        if (!this.ring.beginFrame()) {",
     "the frame is not begun at the first pass, so a pass has no command buffer"),
    ("retire(this.ring.slot());", "the slot's filed releases are not run once its completion has been observed"),
    ("retire(this.ring.slot());", "the slot's filed releases are not run once its completion has been observed"),
    ("this.currentPass = pass;", "the open pass is not remembered, so nothing can end it"),
    ("pass.finish();", "submitRenderPass does not end the pass"),
    ("if (this.currentPass != null) {", "a second pass can be opened while one is still open, which is two "
                                        "encoders in one command buffer with no order between them"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- the compilation chain, which is what a draw needs before it needs anything else ---------------------
# The state now compiles Metal 4 artifacts rather than refusing: the game's GLSL compiler turns a pack's source
# into SPIR-V, the SHARED translator turns that into MSL and names the resources, and this generation builds its
# own native pipeline states from it. Nothing Metal 3's is reached - which is the whole point, and the reason
# these classes exist rather than a call into the reference implementation.
CONTEXT = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4CompilationContext.java"
COMPILER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4PipelineCompiler.java"
ARTIFACT = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
            / "Metal4CompiledRenderPipeline.java")
for path in (CONTEXT, COMPILER, ARTIFACT):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so the generation has no compilation chain")
context = CONTEXT.read_text(encoding="utf-8")
compiler = COMPILER.read_text(encoding="utf-8")
artifact = ARTIFACT.read_text(encoding="utf-8")

if "new Metal4CompilationContext(device)" not in state:
    raise SystemExit("metal 4 provider: the state owns no compilation context, so it can compile nothing")
# Imports, not mentions: these files explain in prose which package they may not depend on, and a pin that a
# comment can fail is a pin that pushes the explanation out of the code.
for source, name in ((context, "context"), (compiler, "compiler"), (artifact, "artifact")):
    if re.search(r"^import\s+.*(render\.metal3|mtl\.metal3)", source, re.MULTILINE):
        raise SystemExit(f"metal 4 provider: the {name} imports a Metal 3 package, which the architecture rules"
                         " forbid: the new generation may not depend on the reference one")

for needle, why in (
    ("Metal4PipelineCompiler.compile(this, p, source)",
     "the cache does not compile through this generation's compiler"),
    # The profile is part of every cache key for the same reason it is in the Metal 3 context: a module or a
    # function translated for one profile is not the one another profile needs.
    ("new ShaderCompilationKey(id, type, defines,\n                MetalShaderLanguageProfile.selected().token())",
     "a translated module is keyed without the MSL profile, so a session that changed profile could be handed "
     "the other one's module"),
    ("new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token())",
     "a compiled function is keyed without the MSL profile"),
    ("this.retired.add(held);", "a replaced artifact is not retired, so it would either leak or be closed while "
                                "work naming it is still in flight"),
    ("this.retired.poll().close();",
     "retired artifacts are not released where the contract says GPU completion has been established"),
    ("GlslCommentStripper.strip(source).stripLeading()",
     "the GLSL preparation no longer strips comments, which the Metal 3 path paid for: independent comment "
     "regexes leave a live slash behind on a pack's toggle block"),
):
    if needle not in context and needle not in artifact and needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, false);",
     "the compiler no longer asks the SHARED translator for direct bindings, so either the translation is "
     "duplicated here or the generation asked for argument buffers - Metal 3's binding mechanism"),
    ("if (translated.usesArgumentBuffers()) {",
     "a translation that came back with argument buffers is accepted, so the shader would be compiled against a "
     "binding path this generation does not fill"),
    ("MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), false)",
     "the artifact's key does not name the profile and the direct-binding decision"),
):
    if needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("implements CompiledRenderPipeline, MetalCompiledArtifact, AutoCloseable",
     "the artifact is not both the game's compiled pipeline and a keyed neutral artifact"),
    ("compilation.device().newRenderPipelineState(descriptor)",
     "the artifact does not build its own native pipeline state through the compiled functions"),
    ("MTLPixelFormat.Depth32Float", "no depth variant is built, so a pass with a depth attachment has no state"),
    ("private static MTLVertexDescriptor buildVertexDescriptor(",
     "the vertex layouts are not described, so a vertex-buffer draw has no attribute mapping"),
    ("return highest + 1;",
     "the vertex layouts no longer start past the named vertex-stage buffers, so they would overwrite them"),
    ("BitSet allResources()", "the artifact does not publish the binding footprint a pass has to fill"),
):
    if needle not in artifact:
        raise SystemExit("metal 4 provider: " + why)

# The no-pack binding subset is implemented now, so the pins describe what the pass does rather than that it
# refuses: the pipeline is compiled through this generation, the binding plan comes from the artifact's own
# footprint, the tables are sized from that plan, a name the pipeline does not declare is a fault, and the
# vertex stride is the pipeline's own.
for needle, why in (
    ("Metal4CompiledRenderPipeline compiled = this.owner.compiled(pipeline);",
     "the pass does not compile through this generation's own path, so a Metal 4 pass would draw with something "
     "built elsewhere"),
    ("this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.firstAvailableVertexBufferSlot(),",
     "the binding plan is not built from the artifact's own footprint, so the slots it fills are guesses"),
    ("this.plan.bufferSlots(MetalShaderStages.VERTEX)",
     "the vertex table is not sized from the plan, so it may not cover the slots it is given"),
    ("this.plan.bufferSlots(MetalShaderStages.FRAGMENT)",
     "the fragment table is not sized from the plan"),
    ("Metal4BindingPlan.Slot slot = requirePlan().slot(name);",
     "a binding is filled without looking it up in the pipeline's layout"),
    ('throw new IllegalStateException("the Metal 4 pipeline does not declare a binding called \'" + name',
     "a name the pipeline does not declare is not refused, so a layout mismatch would be a silently dropped "
     "binding - the half frame section 35 forbids"),
    ("if (slot.buffer()) {", "a texture bound to a buffer's name is not refused"),
    ("if (slot.texture()) {", "a buffer bound to a texture's name is not refused"),
    ("long stride = format == null ? 0L : format.getVertexSize();",
     "the vertex stride is not the pipeline's own vertex format, so a layout would be read per buffer rather "
     "than per vertex"),
    ("this.indexBufferAddress + (long) firstIndex * this.indexTypeBytes",
     "the indexed draw does not turn the engine's first index into an address offset, which is the one thing "
     "Metal 4's indexed draw does differently"),
    ("this.scissorWidth = this.targetWidth;",
     "disableScissor does not set the whole attachment, so the last rectangle would stay in force"),
    ("if (!this.tablesAssigned) {",
     "the tables are assigned on every draw rather than when they changed, which is the first-version "
     "compromise section 50 asks for"),
    ("throw new IllegalStateException(\"the Metal 4 pass was asked to encode \" + operation + \" with no\"",
     "a draw without a pipeline is not a named fault"),
    ("private void releaseTables() {", "a replaced pipeline's tables are not released at all"),
    ("        this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.firstAvailableVertexBufferSlot(),\n"
     "                compiled.vertexBufferCount());\n        releaseTables();",
     "a replaced pipeline's tables are not released, so a stale plan could be read through a new pipeline"),
    # Pinned with the condition that guards them, because a table assignment short-circuited away still contains
    # the call: this is the shape a text pin cannot see on its own, and it is recorded here rather than left to
    # look like a pin that covers it.
    ("if (this.vertexTable != null && !this.encoder.setArgumentTable(this.vertexTable,",
     "the vertex table is never assigned to the encoder"),
    ("if (this.fragmentTable != null && !this.encoder.setArgumentTable(this.fragmentTable,",
     "the fragment table is never assigned to the encoder"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# What a no-pack frame does not need yet still refuses by name, so the gap is a list and not a silence.
for operation in ("multiDrawIndexed", "drawIndexedIndirect", "drawMultipleIndexed", "multiDraw", "drawIndirect",
                  "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in pass_source:
        raise SystemExit(f"metal 4 provider: the render pass does not refuse {operation} by name, so an "
                         "operation it cannot encode would be dropped into a half frame")

# --- the engine side of the copies, which is what the client's first gap asked for -------------------------
# The native layer was measured first (MTL4ComputeEncoder: the region and whole copies, 50 of 50 probes); this is
# the frame encoder's use of it, and the pieces that make an upload possible at all - the staging arena, the
# rotation that hands its blocks back only after the frame that reads them is proved complete, and the compute
# encoder the copies are encoded into. A copy that arrives before any pass also begins the frame, because a
# command buffer has to be begun before anything can be encoded into it.
for needle, why in (
    ("private final MetalTransientMemory transientMemory;",
     "the encoder has no staging arena, so nothing can be uploaded"),
    ("this.transientMemory = new MetalTransientMemory(device, this.destroyQueue);",
     "the arena is not the engine's own, or is not handed this encoder's destruction queue, so its blocks would "
     "be released on a second rotation"),
    ("return this.transientMemory;", "transientMemory() no longer answers with the arena"),
    ("this.transientMemory.rotate();",
     "the arena is never rotated, so a staged block would be reused while the frame that reads it may still be in "
     "flight"),
    ("this.transientMemory.close();", "the arena is never released"),
    ("private MTL4ComputeEncoder copyEncoder() {",
     "the copies have no encoder of their own, and this command model has no blit encoder to fall back on"),
    ("if (this.copyEncoder == null || !this.copyEncoder.open()) {",
     "the copy encoder is not re-opened when it has been ended, so a second copy in a frame would be encoded "
     "into a closed encoder"),
    ("this.transientMemory.uploadStaging(data, 4L, GpuBuffer.USAGE_COPY_SRC);",
     "a buffer write is not staged, so it has nothing to copy from"),
    ("int rowBytes = width * pixelSize;",
     "a texture upload does not compute the row layout the command copies with, which is a sheared image rather "
     "than an error"),
    ("source.offset() + skipBytes", "a buffer-to-texture copy ignores the source origin's byte offset"),
    ("queueForDestroy(callback);",
     "a readback's callback is not filed against the frame whose completion makes its bytes valid"),
    ("this.copyEncoder.barrierForSubsequentEncoders();",
     "a pass that follows a copy is not ordered against it, which section 61 forbids"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# The copies have to be there as implementations and not only absent from the refusal list: a method that was
# renamed away would leave the refusal check passing and the frame path with nowhere to upload a texture.
for implementation in ("public void writeToBuffer(final @NonNull GpuBufferSlice destination",
                       "public void copyToBuffer(final @NonNull GpuBufferSlice source",
                       "public void writeToTexture(final @NonNull GpuTexture destination",
                       "public void copyBufferToTexture(final @NonNull GpuBufferSlice source",
                       "public void copyTextureToBuffer(final @NonNull GpuTexture source",
                       "public void copyTextureToTexture(final @NonNull GpuTexture source"):
    if implementation not in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder does not implement {implementation.split()[2]}, "
                         "which the client asked for by stopping there")

# What a no-pack frame does not need yet still refuses by name, so the gap is a list and not a silence; and the
# copies are no longer in that list, because the client asked for them by stopping there.
for operation in ("clearColorTexture", "clearColorAndDepthTextures", "clearDepthTexture", "createFence",
                  "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder does not refuse {operation} by name, so an "
                         "operation it cannot encode would be dropped into a half frame")
for operation in ("writeToBuffer", "copyToBuffer", "writeToTexture", "copyBufferToTexture", "copyTextureToBuffer",
                  "copyTextureToTexture", "transientMemory"):
    if f'throw unimplemented("{operation}")' in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder still refuses {operation}, which the client asked "
                         "for by stopping there")

# And the binding plan itself: the mapping the device proof drives.
PLAN = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "Metal4BindingPlan.java"
if not PLAN.is_file():
    raise SystemExit("metal 4 provider: Metal4BindingPlan.java is gone, so the tables the pass fills have no "
                     "shape to be built from")
plan_source = PLAN.read_text(encoding="utf-8")
for needle, why in (
    ("public int bufferSlots(final int stage) {",
     "the plan does not answer how many buffer slots a stage's table needs"),
    ("highest = Math.max(highest, this.firstVertexBufferSlot + this.vertexBufferCount - 1);",
     "the plan's buffer count does not account for the vertex layouts, so a table could be made too small for "
     "the slots it is given"),
    ("public int textureSlots(final int stage) {", "the plan does not answer a stage's texture slots"),
    ("public int samplerSlots(final int stage) {", "the plan does not answer a stage's sampler slots"),
    ("return this.byName.get(name);", "the plan does not look a binding up by the name the pack gave it"),
    ("public boolean sampled() {", "a slot does not say whether it has a sampler beside it"),
):
    if needle not in plan_source:
        raise SystemExit("metal 4 provider: " + why)
# And the probe drives the plan rather than literals, which is what makes the device proof a proof of this class.
probe_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "MTL4Probe.java").read_text(encoding="utf-8")
for needle, why in (
    ("Metal4BindingPlan.of(List.of(", "the layout smoke does not build a plan, so the plan is not what runs"),
    ("plan.bufferSlots(MetalShaderStages.VERTEX)", "the smoke does not size its tables from the plan"),
    ("plan.slot(\"tint\")", "the smoke does not look its bindings up in the plan"),
    ("plan.firstVertexBufferSlot()", "the smoke does not take the vertex slot from the plan"),
):
    if needle not in probe_source:
        raise SystemExit("metal 4 provider: " + why)

# --- what EXECUTES is a decision with a gate of its own ---------------------------------------------------
# The selector answers which generation the session is for; this answers which one encodes today, and the two
# are deliberately different facts. AUTO must not promote a frame path the migration has not finished (section
# 74's readiness gate), and a forced Metal 3 session stays Metal 3 whatever was selected - so the only way Metal
# 4 executes is a launch that asked for it by name.
DEVICE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device = DEVICE.read_text(encoding="utf-8")
for needle, why in (
    ("decision.preference() == MetalExecutionPreference.FORCE_METAL4",
     "the executing generation is not decided from the preference, so either AUTO could promote an unfinished "
     "frame path or a forced Metal 4 launch would still execute Metal 3"),
    ("MetalExecutionServices.of(decision.selected(), executesToday);",
     "the services are not built from both facts, so the selection and what executes could disagree again"),
    ("executing == MetalApiGeneration.METAL4" if False else "executesToday == MetalApiGeneration.METAL4",
     "a session that executes Metal 4 is not named as experimental, which is the one thing a reader of its "
     "numbers has to know"),
    ("Metal 4 EXECUTES this session", "the experimental warning does not say that Metal 4 is what runs"),
):
    if needle not in device:
        raise SystemExit("metal 4 provider: " + why)
# And the gate itself: AUTO must not be able to reach Metal 4 by the executing-generation line.
if "case AUTO -> MetalApiGeneration.METAL4" in device or "preference() == MetalExecutionPreference.AUTO" in device:
    raise SystemExit("metal 4 provider: AUTO can reach the executing Metal 4 path, which is the readiness gate "
                     "section 74 puts before it")


# --- and it is reached by the EXECUTING generation, not by a constant ------------------------------------
if "switch (executing)" not in services:
    raise SystemExit("metal 4 provider: the services do not choose the provider by the executing generation, "
                     "so a session that executes Metal 4 would be built from Metal 3 objects - or the choice "
                     "is a constant again and this provider is dead code")
if "case METAL4 -> new com.metallum.render.metal4.Metal4ExecutionProvider();" not in services:
    raise SystemExit("metal 4 provider: the executing generation's Metal 4 case does not name this provider")

# --- and the skeleton has real-device evidence -----------------------------------------------------------
if "provider=" not in harness or "Metal4ExecutionProvider" not in harness:
    raise SystemExit("metal 4 provider: the harness does not ask the provider on the real device, so the "
                     "skeleton has no evidence from an Apple Silicon run")
for needle, why in (
    ("MetalExecutionState state = metal4.createExecutionState(probeDevice);",
     "the harness does not make the state on the real device, so nothing reports what the state answers"),
    ("+ \" compile=\" + compile.replace(' ', '_')",
     "the harness does not report what the compilation chain answered, so the chain has no evidence from an "
     "Apple Silicon run"),
    ("RenderPipeline.builder()",
     "the harness does not build a pipeline description, so the compile is not reachable at all"),
    ("compileState.getOrCompilePipeline(compileFixture, compileSource)",
     "the harness never asks the state to compile through the chain"),
    ("new ColorTargetState(Optional.empty(), GpuFormat.RGBA8_UNORM,",
     "the fixture declares no colour target, and the pipeline builder refuses one without"),
    ("state.evictCachedPipelines(pipeline -> false)",
     "the harness does not ask the state to evict, so an empty cache's answer is assumed rather than measured"),
    ("state.clearCachesAfterGpuCompletion()", "the harness does not ask the state to clear its caches"),
    ("state.close()", "the harness does not release the state, so a run is not a run that gave its objects back"),
    ('",stateMethods=" + stateMethods', "the harness does not report what the state's operations answered"),
    ('",encoder=not-asked(needs-the-engine-device)"',
     "the harness no longer says why the encoder is not asked, so a reader cannot tell a deliberate omission "
     "from a missing answer"),
):
    if needle not in harness:
        raise SystemExit("metal 4 provider: " + why)

print("Metal 4 execution provider contract: PASS")
