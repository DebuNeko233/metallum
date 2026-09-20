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


def body_of(source, signature):
    """The body of one Java method, from its signature to its matching closing brace.

    Several of the facts pinned below are statements whose text appears at more than one call site - a pass that
    ends a copy encoder, a depth attachment built from a caller's value - so a file-wide search would stay green
    while the one site that matters lost it. Reading a method body is what makes those pins pins.
    """
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise SystemExit(f"metal 4 provider: {signature[:40]}... has no closing brace, so its body cannot be read")


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
if "implements MetalFrameEncoder, MetalFramePresentation {" not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not implement the neutral frame contract, so the "
                     "device cannot hold it")
# Presentation is the one optional contract this path now performs, because the surface asks for it by name and
# the frame owns everything it needs (the queue, the one command buffer, the commit). The rest stay missing on
# purpose: each is an operation this path cannot perform yet, and a bridged caller must find it absent and take
# its own fallback rather than receive a do-nothing body.
for absent in ("MetalFrameExtras", "MetalFrameResourceCommands"):
    if absent in encoder.split("implements", 1)[1].split("{", 1)[0]:
        raise SystemExit("metal 4 provider: the encoder claims " + absent + ", which this path cannot perform "
                         "yet - a bridged caller must find it missing and take its own fallback rather than "
                         "receive a do-nothing body")
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
ARGUMENT_TABLE = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4ArgumentTable.java")
PASS = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4RenderPass.java"
if not PASS.is_file():
    raise SystemExit("metal 4 provider: Metal4RenderPass.java is gone, so createRenderPass has no pass object "
                     "and the frame cannot be entered at all")
pass_source = PASS.read_text(encoding="utf-8")

if "implements RenderPassBackend, MetalPassUniformWriter {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass does not implement the game's render pass contract and the "
                     "push-constant contract the sodium draw path asks it for by name")
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
    ("private void beginFrameIfNeeded() {\n        if (this.ring.begun()) {\n            return;\n        }\n",
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
    ("Metal4BindingPlan.Slot slot = this.plan.slot(name, texture);",
     "a binding is filled without looking it up in the pipeline's layout by name and kind"),
    ("if (slot != null) {\n            return slot;\n        }\n        if (TRACE && this.plan.declares(name)) {",
     "a name the pipeline does not declare is not skipped, so this path would be stricter than the Metal 3 pass "
     "it is the reference for: the engine hands every pass a fixed set of default uniforms and a given pipeline "
     "reads some of them, which the first run that got this far proved by binding Fog to the panorama pipeline; "
     "and a name the pipeline declares as the other kind is skipped for the same reason, which the cloud pass "
     "proved by the cloud pass"),
    ("private static final boolean TRACE = Boolean.getBoolean(\"metallum.metal4Trace\");",
     "the pass trace is not off unless a session asks for it, so every session would log a line per draw"),
    ('Metallum.LOGGER.info("Metal 4 trace: indexed draw {} of {} indices at {} of {} bytes, type {},"',
     "an indexed draw is not traced, so the command a GPU fault follows cannot be named"),
    ('Metallum.LOGGER.info("Metal 4 trace: draw {} of {} vertices from {}, instance {}, in \'{}\'",',
     "a draw is not traced"),
    ("this.owner.queueForDestroy(vertex::close);",
     "the vertex table is closed when the pass ends rather than when the frame that bound through it has "
     "completed, which is a release between encoding and execution"),
    ("this.owner.queueForDestroy(fragment::close);",
     "the fragment table is closed when the pass ends rather than with the frame"),
    ("this.encoder.drawIndexedPrimitives(this.artifact.topology().value, indexCount, this.indexTypeValue,\n"
     "                address, length, instanceCount, vertexOffset, firstInstance)",
     "the indexed draw does not carry the draw's own base instance, or does not pass the offset arithmetic's "
     "address and length"),
    ("this.vertexTable.address(address, stride, plan.firstVertexBufferSlot() + slot)",
     "a vertex layout is bound at the game's own slot rather than at the slot the pipeline's descriptor starts "
     "its layouts from, so it would overwrite a named vertex-stage buffer (the same expression appears in the "
     "fault's own message, which is why the pin is the call)"),
    ("if (TRACE && this.plan.declares(name)) {",
     "a name the pipeline declares as the other kind is neither skipped nor reported: the Metal 3 pass skips it "
     "and this path must agree with the reference it is compared against"),
    # And the model itself: a binding is remembered and resolved when a layout exists, which is the game's own
    # order (a pass's default uniforms are bound by name before any pipeline is set) and the Metal 3 pass's own
    # model (it keeps its uniforms and textures in maps and resolves them into the argument buffer a draw
    # builds).
    ("private final Map<String, Long> uniformAddresses = new LinkedHashMap<>();",
     "a uniform bound before the pipeline is not remembered, so the binding the game makes first would be lost"),
    ("private final Map<String, Sampled> textureBindings = new LinkedHashMap<>();",
     "a texture bound before the pipeline is not remembered"),
    ("private final Map<Integer, GpuBufferSlice> vertexBuffers = new LinkedHashMap<>();",
     "a vertex layout bound before the pipeline is not remembered"),
    ("applyBindings();", "the remembered bindings are not resolved when a pipeline arrives"),
    ("Metal4BindingPlan.Slot slot = slotFor(name, true);",
     "a texture is not resolved against the layout, or not by name"),
    ("Metal4BindingPlan.Slot slot = slotFor(name, false);",
     "a uniform is not resolved against the layout, or not by name"),
    ("if (this.pipeline == null) {\n            return null;",
     "a binding made before the pipeline has no remembered answer, so the game's default uniforms would be "
     "refused instead of resolved when a pipeline arrives"),
    ("if (slot != null && !slot.texture()) {",
     "a remembered uniform is filled for a pipeline that declares the name as a texture, so a stale binding "
     "would be written into a texture's slot"),
    ("if (slot != null && !slot.buffer()) {",
     "a remembered texture is filled for a pipeline that declares the name as a buffer"),
    ("this.vertexBuffers.put(slot, buffer);",
     "a vertex layout bound before the pipeline is not remembered with its slot"),
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
for operation in ("multiDrawIndexed", "drawMultipleIndexed", "multiDraw", "drawIndirect",
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

# The copy a frame encoded before a pass wrote something that pass may read, so the dependency is encoded in the
# pass's own opening; the same three lines appear in the clear encoder, which is a second reader of this frame's
# copies, so each site is pinned in its own body rather than once for the file.
COPY_THEN_PASS = ("if (this.copyEncoder != null && this.copyEncoder.open()) {\n"
                  "            this.copyEncoder.barrierForSubsequentEncoders();\n"
                  "            this.copyEncoder.endEncoding();")
for method, why in (
    ("public @NonNull RenderPassBackend createRenderPass(final RenderPassDescriptor descriptor) {",
     "a render pass is opened without ordering the copies the frame encoded before it, so the pass may read what "
     "a copy has not finished writing"),
    ("private void encodeClear(final String operation,",
     "a clear is encoded without ordering the copies the frame encoded before it, so it may clear over what a "
     "copy has not finished writing"),
):
    if COPY_THEN_PASS not in body_of(encoder, method):
        raise SystemExit("metal 4 provider: " + why)

# The indexed draw's selector, which is the one command whose arity was wrong: this machine's
# MTL4RenderCommandEncoder.h declares eight arguments, and the form without baseInstance: does not exist. The
# guard asks the encoder before it is sent, so a short declaration is a named refusal in a log rather than a
# message send with the wrong arity - and the smoke draws through this method rather than through a copy of it.
ENCODER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4RenderEncoder.java"
encoder_source = ENCODER.read_text(encoding="utf-8")
for needle, why in (
    ('"drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:"\n'
     '                    + "baseInstance:",',
     "the indexed draw's selector is not the eight-argument one this SDK declares, so respondsToSelector: "
     "answers no and every indexed draw refuses"),
    ("JAVA_LONG, JAVA_LONG, JAVA_LONG, ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);",
     "the indexed selector is not declared with the eight argument widths it takes"),
    ("indexBufferLength, instanceCount, baseVertex, baseInstance);",
     "the indexed draw is not sent all eight arguments"),
    ("public String refusal() {", "the encoder cannot say why a draw was refused, so a client log names the "
     "draw and not the reason"),
    ("public boolean drawPresent(final MTL4ArgumentTable table, final boolean scaling) {",
     "the encoder cannot draw the engine's present triangle, so the frame's own present has no draw"),
    ("if (indexBufferAddress == 0L) {\n"
     "            this.refusal = \"the index buffer has no GPU address, so there is nothing to read \"",
     "an index buffer with no GPU address is refused without saying so, so the one fault this milestone found "
     "would read as a draw that was asked for and did not happen"),
    ("if (indexCount <= 0L) {", "an indexed draw of no indices is refused without saying so"),
    ("public boolean drawIndexedPrimitivesIndirect(final long primitiveType, final long indexType,",
     "the encoder has no indirect indexed draw for the pass to encode through"),
    ("if (indirectBufferAddress == 0L) {\n"
     "            this.refusal = \"the indirect buffer has no GPU address, so the draw has no arguments to read\";",
     "an indirect draw with no arguments buffer is refused without saying so"),
    ('"drawIndexedPrimitives:indexType:indexBuffer:indexBufferLength:indirectBuffer:"',
     "the encoder cannot encode the indirect indexed draw: the selector is the five-argument one this SDK "
     "declares"),
):
    if needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
# The two draws' "not open" refusal is the same sentence in both methods on purpose, so it is counted rather
# than searched: a search would be satisfied by the other method's copy while one of them went silent.
if encoder_source.count('this.refusal = "the pass " + this.which + " is not open, so there is no encoder to draw'
                        ' on";') != 3:
    raise SystemExit("metal 4 provider: a closed pass is refused without saying so in one of the three draws -"
                     " the direct, the indexed and the indirect one")

if "public boolean drawIndexedPrimitives(final long primitiveType, final long indexCount, final long indexType,\n" \
        "                                         final long indexBufferAddress, final long indexBufferLength,\n" \
        "                                         final long instanceCount, final long baseVertex, final long baseInstance)" \
        not in encoder_source:
    raise SystemExit("metal 4 provider: the indexed draw does not take a base instance, which the SDK's "
                     "selector requires")

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

# The present, which the surface asks for by name: the picture drawn into the layer's next drawable by the
# engine's own present triangle, in this frame's command buffer, with Apple's two halves of the drawable order on
# either side of the commit. The present is the frame's own - one queue, one commit, one presentation path - and
# the sidecar that presents on a second queue stays where it is until this road is proven on the device.
for needle, why in (
    ("public void presentTextureToDrawable(final @NonNull CAMetalLayer layer, final @NonNull GpuTextureView textureView) {",
     "the encoder cannot be presented through, so the surface refuses it and no Metal 4 frame reaches the screen"),
    ("CAMetalDrawable drawable = layer.nextDrawable();",
     "no drawable is taken, so there is nothing to present into"),
    ("if (!this.ring.waitForDrawable(drawable.handle())) {",
     "the queue is not told which drawable the command buffer about to be committed targets - the half of "
     "Apple's order that comes first, without which signalDrawable: is an unrecognised selector"),
    ("new AttachmentContents(true, true), null)",
     "the present pass does not say that it stores the drawable and overwrites every pixel of it, so the "
     "drawable would be loaded before a triangle that covers all of it"),
    ("pass.drawPresent(table, scalingTo(drawableTexture, picture.nativeHandle()))",
     "the present is not drawn with the engine's own present triangle, so the V convention would be whatever "
     "this new road guessed - the copy road presented the loading screen upside down"),
    ("if (!this.ring.signalDrawable(drawable.handle())) {",
     "the drawable is never signalled, so nothing presents it"),
    ("            presentAll();\n            return;",
     "a drawable taken by a present is dropped when the frame encoded nothing, which leaks it"),
    ("        // After the commit, which is the half that comes second: the queue is told the drawable may be shown\n"
     "        // once the work it just committed has run.\n        presentAll();",
     "the drawable is not presented after the commit, so nothing this frame committed would ever be shown"),
    ("private final List<CAMetalDrawable> presentDrawables = new ArrayList<>();",
     "the frame does not hold the drawables it presents into, so a present that arrives before the commit that "
     "legalises it would have nowhere to wait"),
    ("this.presentDrawables.add(drawable);",
     "the drawable taken for a present is not held for the commit that makes presenting it legal"),
    ("            drawable.present();", "the drawable is never presented"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# What a no-pack frame does not need yet still refuses by name, so the gap is a list and not a silence; and the
# copies are no longer in that list, because the client asked for them by stopping there.
for operation in ("clearColorAndDepthTextures", "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder does not refuse {operation} by name, so an "
                         "operation it cannot encode would be dropped into a half frame")
for operation in ("writeToBuffer", "copyToBuffer", "writeToTexture", "copyBufferToTexture", "copyTextureToBuffer",
                  "copyTextureToTexture", "transientMemory", "clearColorTexture", "clearDepthTexture",
                  "createFence"):
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
    ("public Slot slot(final String name, final boolean texture) {",
     "the plan cannot look a binding up by name and kind, so a layout holding a buffer and a texture under one "
     "name would collide - which one of the engine's own passes does"),
    ("public boolean declares(final String name) {",
     "the plan cannot say whether a name exists at all, which is what tells a skip from a kind mismatch"),
    ("(slot.texture() ? textures : buffers).put(slot.name(), slot);",
     "the plan's per-kind maps are not filled, so the kind-aware lookup would answer nothing"),
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

# The clears: a clear is a load action, a load action belongs to a pass, so the first version opens a pass of its
# own and encodes the clear as that pass's loading. It is a real cost (one pass per clear) and it is the honest
# answer while the question is whether the path runs at all; the Metal 3 encoder folds the clear into the next
# pass that uses the attachment instead, which is a lifetime model of its own.
#
# Every needle below is looked for inside one method body and not in the file: "if (this.currentPass != null)"
# and the depth attachment's construction each appear at several call sites, so a file-wide search would be
# satisfied by a clear that lost its own ordering or its own value and stayed green.
CLEAR_ENCODER = body_of(encoder, "private void encodeClear(final String operation,")
for needle, why in (
    ("pass = MTL4RenderEncoder.open(this.executionState.device(), this.ring.commandBuffer(), width, height,\n"
     "                    colors, depth, operation);",
     "a clear is not encoded as a pass over the attachment it clears"),
    ("if (this.currentPass != null) {\n            submitRenderPass();",
     "a clear can be encoded while a pass the game owns is still open, which is two encoders on one command "
     "buffer"),
    ("pass.barrierForSubsequentEncoders()",
     "a pass that follows a clear is not ordered against it, which section 61 forbids"),
):
    if needle not in CLEAR_ENCODER:
        raise SystemExit("metal 4 provider: " + why)

CLEARS = {
    "clearColorTexture": (
        body_of(encoder, "public void clearColorTexture(final @NonNull GpuTexture colorTexture,"),
        (('encodeClear("clearColorTexture"', "the colour clear does not run through the clear encoder"),
         ("CARRIED, components(clearColor)", "the colour clear does not carry its colour and its contents"),
         ("colorTexture.getWidth(0), colorTexture.getHeight(0)",
          "the colour clear's pass is not described at the attachment's own extent, which is a wrongly-sized "
          "pass")),
    ),
    "clearColorAndDepthTextures": (
        body_of(encoder, "public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final "
                         "@NonNull Vector4fc clearColor,\n                                           final "
                         "@NonNull GpuTexture depthTexture, final double clearDepth) {"),
        (('encodeClear("clearColorAndDepthTextures"',
          "the colour-and-depth clear does not run through the clear encoder"),
         ("new MTL4RenderEncoder.Depth(depth.nativeHandle(), clearDepth)",
          "the colour-and-depth clear does not carry the depth attachment and its value, so the depth attachment "
          "would load whatever it held"),
         ("colorTexture.getWidth(0), colorTexture.getHeight(0)",
          "the colour-and-depth clear's pass is not described at the attachment's own extent")),
    ),
    "clearDepthTexture": (
        body_of(encoder, "public void clearDepthTexture(final @NonNull GpuTexture depthTexture,"),
        (('encodeClear("clearDepthTexture"', "the depth-only clear does not run through the clear encoder"),
         ("new MTL4RenderEncoder.Depth(depth.nativeHandle(), clearDepth)",
          "the depth-only clear does not carry the depth attachment and its value"),
         ("depthTexture.getWidth(0), depthTexture.getHeight(0)",
          "the depth-only clear's pass is not described at the attachment's own extent")),
    ),
}
for name, (body, needles) in CLEARS.items():
    for needle, why in needles:
        if needle not in body:
            raise SystemExit(f"metal 4 provider: {why} ({name})")

# The fence: Metal 3's fence is not an MTLFence, it is a promise about the submit index that was current when it
# was made, and the same callers read both generations. So what is pinned is that this generation answers the
# same three ways - a committed submission is waited for on the ring's event, one no commit has promised is not
# complete for a poll and is refused for a wait, and a fence between frames promises the work already submitted
# rather than a frame that does not exist.
FENCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4Fence.java"
if not FENCE.is_file():
    raise SystemExit("metal 4 provider: Metal4Fence.java is gone, so createFence has nothing to hand back")
fence = FENCE.read_text(encoding="utf-8")
for needle, why in (
    ("public final class Metal4Fence implements GpuFence {",
     "the fence does not implement the interface the game waits on"),
    ("return this.ring.awaitSubmission(this.submission, timeoutNS / 1_000_000L);",
     "the fence does not ask the ring whether its own submission completed, which is the whole promise"),
    ("if (this.closed) {", "a closed fence would still be waited on"),
):
    if needle not in fence:
        raise SystemExit("metal 4 provider: " + why)

RING = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4FrameRing.java"
ring = RING.read_text(encoding="utf-8")
for needle, why in (
    ("MTL4CommitOptions.error(feedback)", "the commit handler reads no error, so a GPU fault reaches the frame "
     "path as a completion value that never arrives instead of as the account the queue actually gave"),
    ("private static final long WAIT_MILLIS = 5000L;",
     "the ring does not wait the Metal 3 encoder's own five seconds for a slot's completion, so a legitimate "
     "stall would be reported as a lifetime fault"),
    ("public long nextSubmission() {\n        return signalled + 1L;",
     "the ring cannot say which submission the next commit will signal, or says the wrong one"),
    ("public boolean waitForDrawable(final MemorySegment drawable) {",
     "the ring cannot register a drawable with its queue, so signalDrawable: would be an unrecognised selector"),
    ("public boolean signalDrawable(final MemorySegment drawable) {",
     "the ring cannot signal a drawable, so nothing would present it"),
    ("public boolean awaitSubmission(final long submission, final long timeoutMs) {",
     "the ring cannot be asked whether a submission completed, so a fence has nothing to ask"),
    ("if (submission > signalled) {\n            if (timeoutMs == 0L) {\n                return false;\n            }\n"
     "            throw new IllegalStateException(\"Cannot wait on a fence for the current submit\");",
     "a submission no commit has promised is reported complete, or a wait for it blocks instead of being "
     "refused by name - which is how a pool recycles a buffer the GPU is still reading"),
    ("if (submission <= 0L) {\n            return true;\n        }",
     "a fence about no submission at all is reported incomplete, so a resource held from before the first "
     "frame would never be handed back"),
    ("WAIT_UNTIL_SIGNALED.sendLong(event, submission, timeoutMs)",
     "the wait does not go through the shared event the commits signal on"),
):
    if needle not in ring:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("long submission = this.ring.begun() ? this.ring.nextSubmission() : this.ring.submissions();",
     "createFence does not promise the frame being encoded when one is open, or the work already submitted "
     "when none is"),
    ("return new Metal4Fence(this.ring, submission);", "createFence does not hand back this generation's fence"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if 'throw unimplemented("createFence")' in encoder:
    raise SystemExit("metal 4 provider: the frame encoder still refuses createFence, which the client asked for "
                     "by stopping there")

# The GPU's own account of a fault, which is the one thing a Metal 4 queue says about a submission that went
# wrong: a Metal 3 command buffer carries an errorDescription, and a Metal 4 queue reports nothing unless the
# commit was given options. Without this a GPU fault reads as a lifetime fault - measured, and the reason it
# exists: the first forced Metal 4 run that reported one said MTL4CommandQueueErrorDomain error 1, which the SDK
# header names MTL4CommandQueueErrorTimeout.
COMMIT_OPTIONS = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4CommitOptions.java"
if not COMMIT_OPTIONS.is_file():
    raise SystemExit("metal 4 provider: MTL4CommitOptions.java is gone, so a commit's GPU time and its fault "
                     "have no reader")
commit_options = COMMIT_OPTIONS.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("error", ADDRESS)', "the feedback's error is not read, so a GPU fault cannot be named"),
    ("public static String error(final MemorySegment feedback) {",
     "the feedback's error is not turned into words a log can carry"),
    ('LOCALIZED_DESCRIPTION.sendPtr(failure)', "the error's own description is not read"),
):
    if needle not in commit_options:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ('Msg.ofVoid("commit:count:options:", ADDRESS, JAVA_LONG,\n            ADDRESS)',
     "the ring has no commit-with-options form, so the queue's feedback can never be asked for"),
    ("private MTL4CommitOptions commitOptions;", "the ring holds no commit options"),
    ("commitOptions.feedbackHandler(feedbackBlock);\n                COMMIT_WITH_OPTIONS.send(queue, buffers, 1L,"
     " commitOptions.handle());",
     "the commit does not carry the options, so its feedback is never delivered"),
    ("block = ObjCBlock.withConsumer(MTL4FrameRing::reportFeedback);",
     "nothing reads the feedback, so a fault is still a silent timeout"),
    ("if (!faultReported) {\n            faultReported = true;",
     "a dead GPU is reported once per commit instead of once"),
    ('Integer.getInteger("metallum.metal4RingSlots", MTL4FrameRing.FRAMES_IN_FLIGHT)',
     "the ring's depth cannot be asked for, which is how a fault is correlated with the submission that caused "
     "it: at one slot the commands a trace prints before the fault report are the faulting submission's"),
):
    if needle not in ring and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- residency, which is what the frame path's addresses are -------------------------------------------------
# The new command model binds a buffer by GPU address and an address is not a reference, so nothing but a
# residency set keeps the allocation behind it resident. This is not a nicety: the first forced Metal 4 runs
# ended in a kernel GPURestart and an MTL4CommandQueueErrorTimeout until the frame path declared what it reads,
# and the A/B is one line of wiring - with the declarations, no restart and no timeout; without them, both.
RESIDENCY = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4ResidencySet.java"
if not RESIDENCY.is_file():
    raise SystemExit("metal 4 provider: MTL4ResidencySet.java is gone, so the frame path cannot declare what its"
                     " addresses name")
residency_source = RESIDENCY.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("newResidencySetWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS)',
     "the residency set has no factory, so nothing can be declared"),
    ('Msg.ofVoid("addAllocation:", ADDRESS)', "an allocation cannot be added to the set"),
    ('Msg.ofVoid("commit")', "the set cannot be committed, so its additions never take effect"),
    ('Msg.ofVoid("requestResidency")', "residency is never requested, which is the whole point of the set"),
    ('Msg.of("allocationCount", JAVA_LONG)', "the set cannot be asked what it holds"),
    ('Msg.ofVoid("endResidency")', "the set is released without ending its residency"),
    ("public boolean add(final MemorySegment allocation) {", "the wrapper cannot add an allocation"),
    ("public boolean commit() {", "the wrapper cannot commit"),
    ("public boolean requestResidency() {", "the wrapper cannot request residency"),
):
    if needle not in residency_source:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ('Msg.ofVoid("addResidencySet:", ADDRESS)',
     "the ring cannot hand a residency set to its queue, so the frame's declarations would belong to nothing"),
    ("public boolean addResidencySet(final MemorySegment set) {", "the ring has no call that takes a set"),
    ("void useResource(final @Nullable MemorySegment allocation) {",
     "the frame encoder cannot be told what the frame reads through an address"),
    ("MTL4ResidencySet.create(this.executionState.device(), 64L,", "the frame encoder makes no residency set"),
    ("commitResidency();", "the frame's declarations are never committed before its work is"),
    ("this.residencyAttached = this.ring.addResidencySet(this.residency.handle());",
     "the set is never given to the queue, so the GPU is never told about it"),
    ("this.residency.close();", "the set is never released with the encoder"),
):
    if needle not in ring and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# Every place the frame path binds something by address or id has to declare it, which is the difference the A/B
# measured: an attachment, a sampled texture, a uniform, a vertex layout and an index buffer are five different
# call sites and each one is pinned separately, because a pin on one of them would be satisfied by the others.
for needle, why in (
    ("public void drawIndexedIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {\n"
     "        if (!prepareDraw(\"drawIndexedIndirect\")) {",
     "an indirect indexed draw is not implemented - the chunk renderer reaches its terrain through exactly that "
     "form - or is encoded without the state a draw needs"),
    ("this.encoder.drawIndexedPrimitivesIndirect(this.artifact.topology().value, this.indexTypeValue,",
     "the pass does not encode through the encoder's indirect draw, so the form would be a refusal again"),
    ("indirect += INDIRECT_ARGUMENTS_BYTES;",
     "the arguments of the next indirect draw are not twenty bytes further on, so every draw after the first "
     "would read the first one's arguments"),
    ("private static final long INDIRECT_ARGUMENTS_BYTES = 20L;",
     "the indirect arguments' stride is not the twenty bytes MTLDrawIndexedPrimitivesIndirectArguments is"),
    ("declare(commands.buffer());\n        long indirect = addressOf(commands.buffer(), commands.offset());",
     "the indirect arguments buffer is not declared resident, which is what the header asks for on this command "
     "by name"),
    ("public GpuBufferSlice.MappedView allocateTransient(final long size, final long alignment, final int usage) {",
     "a draw path that writes its own push constants has nowhere to write them, and the terrain draw asks for "
     "exactly that"),
    ("return this.owner.transientMemory().allocateGpuMapped(size, alignment, usage);",
     "the push-constant slice does not come from the frame's own arena, so its lifetime would be nobody's"),
    ("this.owner.useResource(attachmentTexture);", "a colour attachment is not declared resident"),
    ("this.owner.useResource(depthTexture);", "a depth attachment is not declared resident"),
    ("this.owner.useResource(textureView.nativeHandle());", "a sampled texture is not declared resident"),
    ("        declare(slice.buffer());", "a uniform buffer's allocation is not declared resident"),
    ("        declare(buffer.buffer());", "a vertex layout's allocation is not declared resident"),
    ("        declare(buffer);", "an index buffer's allocation is not declared resident, which is the case the"
     " header names by name"),
    ("        this.owner.useResource(metal.metalBuffer().handle());", "the declaration does not reach the"
     " allocation the address belongs to"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# The frame's own counters, which are the instrument the next question needed: the path rendered the loading
# screen at a fraction of the Metal 3 rate and the candidate list (a table a pass, an encoder a pass, a residency
# commit a frame) is exactly what these separate. Off unless a session asks, because a line every sixty frames is
# a diagnostic and not a session's log.
for needle, why in (
    ('Boolean.getBoolean("metallum.metal4FrameStats")',
     "the frame path cannot be asked what a frame cost, so a slow frame is a guess again"),
    ("private static final boolean COUNTING = TRACE || STATS;",
     "the counters are not kept when either diagnostic is on, so a trace run has no summary"),
    ("Metal 4 frame stats: frames={} fps={} msPerFrame={}", "the counters are never reported"),
    ("this.statPasses++;", "a pass is not counted"),
    ("this.statEncoders++;", "an encoder is not counted"),
    ("this.statTables += tables;", "an argument table is not counted"),
    ("this.statResidency++;", "a residency declaration is not counted"),
    ("this.statFrameNanos += System.nanoTime() - this.statBeganAt;", "a frame's wall time is not measured"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if ("owner.statPass(this.drawsEncoded, this.indexedEncoded);\n        if (TRACE) {") not in pass_source:
    raise SystemExit("metal 4 provider: a pass's draws are counted only while the per-draw trace is on, so the"
                     " counters that answer what a frame cost report passes with no draws")
if "owner.statPass(this.drawsEncoded, this.indexedEncoded);" not in pass_source:
    raise SystemExit("metal 4 provider: a pass's draws are not reported to the frame's counters")
if "owner.statEncoder();" not in pass_source:
    raise SystemExit("metal 4 provider: a pass's encoder is not reported to the frame's counters")
if "statTables(this.plan.usesStage(MetalShaderStages.VERTEX) ? 1L : 0L" not in pass_source:
    raise SystemExit("metal 4 provider: the tables a pass makes are not reported to the frame's counters")

# The argument table's unbound slots, which is a correctness fact and not a detail: the header says
# initializeBindings defaults to false, so a slot this path never fills holds whatever the driver left there, and
# a shader that reads one dereferences it. This path skips a binding by design where a layout declares it as the
# other kind of resource, and the first world frame - the first that draws the clouds - was killing the GPU with
# an MMU fault until the tables were created with their bindings initialised to nil. Nil reads as zero, which is
# what the Metal 3 pass does with a name its layout never encodes.
if "SET_INITIALIZE.send(descriptor, 1L);" not in ARGUMENT_TABLE.read_text(encoding="utf-8"):
    raise SystemExit("metal 4 provider: the argument table is not created with its bindings initialised, so a"
                     " slot this path skips by design holds undefined data and a shader that reads it faults the"
                     " GPU - measured, and the first world frame was doing exactly that")

# The frame probe, fed by the full-frame path. The probe is how the standard harness collects a run at all - it
# waits for the probe's window line - and it was fed by the Metal 3 encoder alone, so a forced Metal 4 run was
# "never collected" no matter how well it rendered. Every counter the probe prints is reported from where the
# Metal 4 path has the fact, and the frame boundary is what opens the window.
for needle, why in (
    ("MetalFrameProbe.frameSubmitted();", "the full-frame path never reports a frame boundary, so the probe's"
     " window never opens and the harness cannot collect a forced Metal 4 run"),
    ("MetalFrameProbe.encoderOpened(0);", "a render pass the full-frame path opened is not counted"),
    ("MetalFrameProbe.encoderOpened(1);", "a copy encoder is not counted"),
    ("MetalFrameProbe.encoderOpened(3);", "a clear pass is not counted"),
    ("MetalFrameProbe.attachment(attachmentTexture, pixelSize(view), true, true);",
     "a colour attachment is not counted, so the probe's load and store traffic reports nothing"),
    ("MetalFrameProbe.depthAttachment(depthTexture, pixelSize(view), true, true);",
     "a depth attachment is not counted"),
    ("MetalFrameProbe.pipelineBound();", "a pipeline bind is not counted"),
    ("MetalFrameProbe.textureBound();", "a texture bind is not counted"),
    ("MetalFrameProbe.samplerBound();", "a sampler bind is not counted"),
    ("MetalFrameProbe.bufferBound();", "a buffer bind is not counted"),
    ("MetalFrameProbe.scissorSet();", "a scissor is not counted"),
    ("MetalFrameProbe.blit(width, height, textureOf(destination).pixelSize());",
     "a texture copy is not counted as a blit"),
    ("MetalFrameProbe.metal4Present();", "a present the full-frame path made is not counted"),
    ("MetalFrameProbe.submitWindowWait(System.nanoTime() - waitBegan);",
     "the ring's slot-reuse wait is not timed, so the waits line reports nothing for this path"),
    ("MetalFrameProbe.gpuFrameMetal4(millis);", "the queue's per-commit GPU time is read but not reported to the"
     " probe, so a Metal 4 frame has no GPU time at all"),
):
    if needle not in encoder and needle not in pass_source and needle not in ring:
        raise SystemExit("metal 4 provider: " + why)
if "private static int pixelSize(final GpuTextureView view) {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass cannot say how large an attachment's pixels are, so the probe's"
                     " attachment accounting would count nothing")

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
