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

for operation in ("setPipeline", "bindTexture", "setUniform", "enableScissor", "disableScissor",
                  "setVertexBuffer", "setIndexBuffer", "drawIndexed", "multiDrawIndexed", "drawIndexedIndirect",
                  "drawMultipleIndexed", "draw", "multiDraw", "drawIndirect", "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in pass_source:
        raise SystemExit(f"metal 4 provider: the render pass does not refuse {operation} by name, so that "
                         "operation would be dropped into a pass that draws nothing")

for needle, why in (
    # Pinned with its body, because the same `begun` test appears in submit() and a bare test would be satisfied
    # by the other occurrence while the pass path stopped beginning frames.
    ("if (!this.ring.begun()) {\n            if (!this.ring.beginFrame()) {",
     "the frame is not begun at the first pass, so a pass has no command buffer"),
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

# Every operation the game can ask for and this path cannot perform is refused by name. The list is the
# migration's own remaining work, one line per operation.
# createRenderPass and submitRenderPass are deliberately NOT in this list any more: they are implemented, and
# the block below pins what they do. Everything here is still a named refusal.
for operation in ("transientMemory", "clearColorTexture",
                  "clearColorAndDepthTextures", "clearDepthTexture", "writeToBuffer", "copyToBuffer",
                  "writeToTexture", "copyBufferToTexture", "copyTextureToBuffer", "copyTextureToTexture",
                  "createFence", "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in encoder:
        raise SystemExit(f"metal 4 provider: the encoder does not refuse {operation} by name, so that operation "
                         "would be dropped into a half frame - which section 35 forbids")
for forbidden in ("render.metal3", "mtl.metal3"):
    if forbidden in encoder or forbidden in state:
        raise SystemExit(f"metal 4 provider: a Metal 4 implementation names {forbidden}, which the architecture "
                         "rules forbid")
if re.search(r"static\s+(?:final\s+)?(?:MemorySegment|MTL4FrameRing|MetalFrameEncoder)\s+\w+\s*(?:=|;)",
             encoder):
    raise SystemExit("metal 4 provider: the encoder holds native state in a static, so a teardown, a reload or a "
                     "second device could reach another session's frame - which section 106 forbids")
if "public String stage()" not in provider:
    raise SystemExit("metal 4 provider: the refusal does not carry its stage, so a log line cannot say which "
                     "operation was asked for")
if "throw new Unimplemented(\"createFrameEncoder\", \"the frame's ring could not be made at stage \"" not in provider:
    raise SystemExit("metal 4 provider: a ring the device will not make is not refused by name, so a device "
                     "that cannot run this path would be reported as one that can")

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
