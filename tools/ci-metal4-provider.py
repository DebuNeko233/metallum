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

# The queue the services hand the encoder is the encoder's to release: the ring explicitly does not own it, and
# the Metal 3 encoder releases the one the same seam gives it. Pinned because the two encoders' teardowns are
# where the difference is visible and nowhere else - this was a queue leaked once a session until the ledger.
if "this.queue = MemorySegment.ofAddress(queue);" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder does not keep the queue it was given, so it cannot"
                     " release it")
if "ObjC.release(this.queue);" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder never releases its queue, and the ring does not own"
                     " it - the Metal 3 encoder releases the queue the same seam hands it")

# The encoder: the neutral contract, the ring it owns, and a named refusal for every operation it lacks.
if "implements MetalFrameEncoder, MetalFramePresentation, MetalFrameExtras,\n        MetalFrameResourceCommands, MetalFrameComputeCommands {" \
        not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not implement the neutral frame contract, so the "
                     "device cannot hold it")
# Which optional contracts this path carries, and what each one is here for. Presentation is the surface's own
# request. MetalFrameExtras carries the attachment-contents question, which the pack side asks before every pass
# and which this path answers in full. MetalFrameResourceCommands is carried with three honest refusals, and the
# *carrying* is the part that matters: the client installs its capability adapter for a backend that carries this
# contract, so a generation that omitted it lost the attachment half that does work here - measured, a pack's
# stores were never elided on Metal 4 and the attachment bridge's "the backend was told" line never appeared.
if "MetalFrameResourceCommands" not in encoder.split("implements", 1)[1].split("{", 1)[0]:
    raise SystemExit("metal 4 provider: the encoder dropped MetalFrameResourceCommands, which does not cost it "
                     "three unimplemented operations but the whole capability dispatch - the attachment-contents "
                     "half included, which is measured to stop arriving when the contract is absent")
for needle, why in (
    # Mipmap generation is implemented now rather than refused, and what is pinned is the whole road: the
    # texture has to be one a chain can be generated for, the command goes on the frame's copy encoder, and the
    # texture is declared resident first.
    ("|| texture.getMipLevels() <= 1 || !supportsMipmapGeneration(texture.getFormat())",
     "mipmap generation no longer refuses a texture with one level or a format the native command cannot filter,"
     " so a caller would be told a chain was built"),
    ("boolean generated = copies.generateMipmaps(metal.nativeHandle());",
     "the frame path does not send the mipmap command, so the operation is still a refusal with a longer body"),
    ("Metal 4 trace: generated the mip chain of a {}x{} texture: {}",
     "a generated chain is not said under the trace switch, so nothing on a device run can show that a pack's"
     " mipmaps went through this path"),
    ("useResource(metal.nativeHandle());\n        boolean generated = copies.generateMipmaps(",
     "the texture is not declared resident before its chain is generated, and an undeclared resource makes a"
     " command of this kind do nothing at all - measured"),
    ("private static boolean supportsMipmapGeneration(final com.mojang.blaze3d.GpuFormat format) {",
     "the format list the native mipmap command needs is gone, so a texture it cannot filter would be sent"),
    # A storage texture is cleared by a typed kernel through a table now, not refused. What is pinned is the
    # whole road: the shape checks, the table, the residency declaration, and the dispatch the helper encodes.
    ("|| dimensions < 1 || dimensions > 3) {\n            return false;",
     "clearing a storage texture no longer refuses a dimensionality this engine does not carry"),
    ("cleared = this.storagePipelines.clearZero(copies, table, metal.nativeHandle(),",
     "the frame path does not dispatch the zeroing kernel, so the operation is still a refusal with a longer"
     " body"),
    ("MTL4ComputeEncoder copies = dispatchEncoder(\"the storage clear of a \" + dimensions + \"D texture\");",
     "the storage clear shares the frame's copy encoder instead of getting one of its own - the shape that lost"
     " a dispatch in the probe"),
    ("useResource(metal.nativeHandle());\n        boolean cleared;",
     "the image is not declared resident before it is written by a kernel, and an undeclared resource makes a"
     " command of this kind do nothing at all - measured"),
    ("MTL4ArgumentTable table = MTL4ArgumentTable.create(this.executionState.device(), 0L, 1L, 0L);",
     "there is no table for a storage dispatch to bind its image through, and this command model has no"
     " per-resource setter on the encoder"),
    ("queueForDestroy(table::close);\n        MTL4ComputeEncoder copies = dispatchEncoder(",
     "the clear's table is not given back through the frame's destruction queue, so it would outlive the slot"
     " that may still read it - or leak"),
    ("name.endsWith(\"_UINT\") ? com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind.UINT",
     "the zeroing kernel's scalar type is not read from the texture's own format, so a uint image would be zeroed"
     " by the float kernel and the pipeline would not build or would write the wrong bits"),
    ("return refuseResourceOperation(\"copyStorageTextureRegion\");",
     "a storage-texture region copy no longer refuses by name, so a caller would be told it was copied"),
    ("private boolean refuseResourceOperation(final String operation) {",
     "the remaining resource refusals no longer run through one helper, so one of them can be answered without a "
     "name or without a line in the log"),
    ("this.refusedResourceOperations.add(operation)",
     "a resource refusal is not remembered, so an operation called every frame would fill the log"),
    ("Metal 4 frame encoder: {} is not implemented on this path yet, so the caller",
     "the resource refusal no longer names the operation it refused"),
    ("+ \" takes its own fallback.",
     "the resource refusal no longer says what the caller does instead of the operation"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
# What a pass said about its attachments reaches the pass and not the encoder that outlives it: the statement is
# taken and cleared before the pass is built, exactly as the Metal 3 encoder takes it, so a pass nobody described
# cannot inherit the last described pass's answers. A wrong DontCare is a wrong image rather than a slower frame,
# which is why this half is pinned with its order and not only its presence.
if "private AttachmentContents[] nextPassContents;" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder has nowhere to keep what the next pass was told about "
                     "its attachments, so every pass keeps the load and store actions it would have had and the "
                     "measurement is of nothing")
for needle, why in (
    ("public void setNextPassContents(final @Nullable AttachmentContents[] contents) {",
     "the encoder does not accept the attachment-contents statement the pack side makes before every pass"),
    ("this.nextPassContents = contents == null ? null : contents.clone();",
     "the statement is kept by reference, so a caller that reuses its arrays would rewrite a pass's answers"),
    ("Metal4RenderPass pass = new Metal4RenderPass(this, descriptor, passContents);",
     "the pass is still created without the facts stated for it, so the descriptor's load and store actions "
     "ignore what the pack side knows"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
read_facts = encoder.index("AttachmentContents[] passContents = this.nextPassContents;")
# Presence before position, so a line an edit deleted is reported as the defect it is instead of as a traceback
# from this file - the same rule the other contracts here follow.
if "this.nextPassContents = null;" not in encoder[read_facts:]:
    raise SystemExit("metal 4 provider: what the next pass was told is never cleared when it is taken, so a pass "
                     "nobody described would inherit the last described pass's answers")
cleared = encoder.index("this.nextPassContents = null;", read_facts)
built = encoder.index("new Metal4RenderPass(", read_facts)
if not read_facts < cleared < built:
    raise SystemExit("metal 4 provider: what one pass was told is read and cleared after that pass is built, so it "
                     "would leak onto the next")
# The other three members of the contract answer what is true of this generation. The storage-image boundary is
# already encoded after every pass on this path, so accepting the flag is not a silent drop. The scaler used to be
# a literal `false` with the Metal 4 MetalFX milestone named as the reason; that milestone has landed, so the pins
# moved to the invariants that make the answer honest: the capability is the scaler path's own existence - the
# device's functional answer, never a literal - and the scale is the generation's own object rather than a
# borrowed one, which is section 80's split and the reason a Metal 4 frame cannot be handed a Metal 3 scaler.
if "public void setNextPassReadsStorageImage(final boolean reads) {" not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not accept the storage-image boundary statement, so a "
                     "caller finds the contract incomplete on the road that does answer the attachment half of "
                     "it and falls back from both")
if "return !this.closed && this.metalFx != null;" not in body_of(encoder, "public boolean metalFxAvailable() {"):
    raise SystemExit("metal 4 provider: the MetalFX answer is no longer the scaler path's own existence, so a "
                     "session would either claim a scaled road it cannot take or refuse one it has")
for needle, why in (
    ("this.metalFx = Metal4Fx.create(nativeDevice);",
     "the encoder does not make this generation's own MetalFX path, so the answer cannot be its existence"),
    ("return this.metalFx.scale(this.ring.commandBuffer(), color.nativeHandle(), output.nativeHandle(),",
     "the scale is not encoded on this frame's own Metal 4 command buffer through this generation's scaler"),
    ("if (this.copyEncoder != null && this.copyEncoder.open()) {\n            this.copyEncoder.endEncoding();",
     "an encoder of ours may still be open when the scaler encodes, which orders the upscale before work it has "
     "to follow"),
    ("if (this.metalFx != null) {\n            this.metalFx.close();",
     "the scalers and their compiler are not released with the encoder that made them, so a second device in one "
     "process could be handed the first one's compiled pipelines"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("MTL4FrameRing.create(nativeDevice, this.queue, FRAMES_IN_FLIGHT,",
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

# The pass spends the facts the frame path stated for it. The one thing that may not drift is the agreement
# between the two readers of those facts: the descriptor that is opened and the probe that counts the traffic.
# They are pinned through the single mapping that decides them, so a pass that counted a load it did not ask for
# (or a store it discarded) fails here rather than turning into a wrong reading of what a frame costs.
for needle, why in (
    ("MTL4RenderEncoder.Color[] colors = new MTL4RenderEncoder.Color[attachments.size()];",
     "the pass no longer describes one colour slot per attachment the descriptor has, so an unused slot would "
     "be compacted away and every attachment after it would sit at another slot's number - measured on "
     "Vitrail's MRT fixture, whose unused slots come before the attachment that is written"),
    ("final @Nullable AttachmentContents[] contents) {",
     "the pass constructor no longer takes what the frame path stated for it, so nothing can reach the "
     "descriptor's load and store actions"),
    ("AttachmentContents[] stated = AttachmentContents.resolve(contents, attachments.size());",
     "the pass does not default the statement per slot, so a caller that said nothing about a slot is not "
     "answered with the answer that changes nothing"),
    ("AttachmentContents slotContents = stated[index];",
     "the statement is not read per slot, so every attachment would be opened with the same answer"),
    ("MTL4RenderEncoder.Color color = new MTL4RenderEncoder.Color(attachmentTexture, slotContents,",
     "the pass no longer builds the attachment from the slot's own facts, so what the descriptor is opened "
     "with is not what the counter is given"),
    ("MTL4RenderEncoder.countAttachment(color, pixelSize(view));",
     "the pass states one set of facts to the counter and another to the descriptor, which makes the two "
     "readings incomparable"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
if "boolean depthCleared = depthAttachment.clearValue().isPresent();" not in pass_source:
    raise SystemExit("metal 4 provider: the depth load the pass asks for is not read from the descriptor, so the "
                     "counted depth load is a guess")
if "MTL4RenderEncoder.countDepthAttachment(depthAttachmentValue, pixelSize(view));" not in pass_source:
    raise SystemExit("metal 4 provider: the pass counts no depth traffic, or counts it from a restatement of the "
                     "descriptor rather than from the attachment it opens")

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

# --- the diagnostic drawable-wait switch, which must stay a diagnostic ------------------------------------
# The switch exists for one question - what the encoded `waitForDrawable:` contributes to the interval
# `MTL4CommitFeedback.GPUStartTime/GPUEndTime` reports - and the risk it carries is that a session which
# measures a faster number adopts it. So the pins say three things: it is off unless the property is set, it is
# consulted at exactly one place and that place still encodes the wait when it is off, and a session that sets
# it says so in its own log, because an arm has to be able to prove which submission it measured.
if 'Boolean.getBoolean("metallum.metal4NoDrawableWait")' not in encoder:
    raise SystemExit("metal 4 provider: the drawable-wait diagnostic switch is gone, so the wait inside the "
                     "commit window can no longer be priced by an experiment")
if "if (!NO_DRAWABLE_WAIT && !this.ring.waitForDrawable(drawable.handle())) {" not in encoder:
    raise SystemExit("metal 4 provider: the drawable wait is no longer encoded when the switch is off, which is "
                     "the production path - a diagnostic that also removed the wait by default would ship the "
                     "diagnostic")
if "metallum.metal4NoDrawableWait is ON" not in encoder:
    raise SystemExit("metal 4 provider: a session that leaves the drawable wait out no longer says so in its "
                     "log, so the arm that measured a different submission cannot be identified from its own "
                     "evidence")
if len([line for line in encoder.splitlines()
        if "NO_DRAWABLE_WAIT" in line and not line.strip().startswith(("*", "//", "/*"))]) != 3:
    raise SystemExit("metal 4 provider: the drawable-wait switch is read in {} code lines where it must be read "
                     "in three - its declaration, the present that consults it and the log line that reports it - "
                     "so a production path may have grown a way to reach it".format(
                         len([line for line in encoder.splitlines()
                              if "NO_DRAWABLE_WAIT" in line
                              and not line.strip().startswith(("*", "//", "/*"))])))
if "|| NO_DRAWABLE_WAIT" in encoder or "NO_DRAWABLE_WAIT = true" in encoder:
    raise SystemExit("metal 4 provider: the drawable-wait switch can be on without the property being set, "
                     "which would make a diagnostic the default submission")

# --- the pipeline's depth bias, which section 58 found carried but never sent -----------------------------
# The artifact has held `depthBiasConstant` and `depthBiasScaleFactor` since it was written and nothing on this
# path ever handed them to an encoder, so a pipeline that asks for a bias - a decal, a shadow-map offset - drew
# unbiased here and biased on the reference. The three pins are the selector with the floats the header declares,
# the call site where the Metal 3 pass makes it, and the counter that lets a live frame say whether any real
# scene reaches it.
ENCODER_FILE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4RenderEncoder.java"
metal4_encoder_source = ENCODER_FILE.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("setDepthBias:slopeScale:clamp:",', "the encoder cannot be told a pipeline's depth bias, so a "
     "biased pipeline draws at a different depth here than on the reference"),
    ("Msg.ofVoid(\"setDepthBias:slopeScale:clamp:\",\n            JAVA_FLOAT, JAVA_FLOAT, JAVA_FLOAT)",
     "the depth-bias selector's three floats are not declared in the header's order, so a swapped bias and "
     "slope-scale would compile and send the wrong adjustment"),
    ("public boolean setDepthBias(final float constant, final float slopeScale, final float clamp) {",
     "the encoder's depth-bias entry point is gone"),
):
    if needle not in metal4_encoder_source and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("this.encoder.setDepthBias(this.artifact.depthBiasConstant(), this.artifact.depthBiasScaleFactor(), 0.0f);",
     "the pass no longer applies the pipeline's depth bias, which is the gap section 58 found"),
    ("MetalFrameProbe.depthBiasApplied();",
     "a non-zero depth bias is no longer counted, so no live frame can say whether real geometry reaches the "
     "road - and 'the fields exist' is not the same reading as 'the encoder was told'"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
PROBE_SOURCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "shared" / "MetalFrameProbe.java"
probe_source = PROBE_SOURCE.read_text(encoding="utf-8")
for needle, why in (
    ("public static void depthBiasApplied() {", "the probe cannot count an applied depth bias"),
    ("depthBias={}", "the window line does not report the depth-bias count, so a session cannot say whether "
                     "any pipeline in it asked for a bias"),
):
    if needle not in probe_source:
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
PLAN = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "Metal4BindingPlan.java")
for path in (CONTEXT, COMPILER, ARTIFACT, PLAN):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so the generation has no compilation chain")
context = CONTEXT.read_text(encoding="utf-8")
compiler = COMPILER.read_text(encoding="utf-8")
artifact = ARTIFACT.read_text(encoding="utf-8")
plan = PLAN.read_text(encoding="utf-8")

# The plan's half of the wide path, and the two mistakes that would make a wide pipeline's table unfittable: a
# binding an argument buffer carries has an argument index and not a table slot, so counting it would size the
# table past Metal's thirty-one buffer slots; and the argument buffer itself has to be counted, or the table
# would not cover the slot the pass writes its address into.
for needle, why in (
    ("if (slot.buffer() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer binding's index as a table slot, so a wide pipeline's table would be "
     "sized to the argument index space and refused for exceeding Metal's thirty-one buffer slots"),
    ("if (slot.texture() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer texture's index as a table slot"),
    ("if (slot.sampled() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer sampler's index as a table slot, which is the sixteen-slot ceiling the "
     "wide path exists to get around"),
    ("highest = Math.max(highest, argumentBuffer.bufferIndex());",
     "the plan does not count the argument buffer's own buffer slot, so the table would not cover the slot the "
     "pass has to write its address into"),
    ("public boolean indirect() {", "the plan does not say whether a slot is carried by an argument buffer"),
    ("public boolean usesArgumentBuffers() {", "the plan does not say whether it is a wide one"),
):
    if needle not in plan:
        raise SystemExit("metal 4 provider: " + why)

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

# The wide-pipeline boundary, which moved on a measurement rather than on taste. This generation first asked the
# shared translator for direct bindings unconditionally, on the reading that an argument buffer is Metal 3's
# mechanism and the table replaces it. The table replaces it for everything that fits; what it cannot replace is
# the sampler ceiling, because MTL4ArgumentTable.h caps a table at sixteen sampler slots and MSL declares one
# sampler attribute per sampled image. Photon's deferred4 reads nineteen. So the compiler hands the translator the
# DEVICE's argument-buffer answer, and the invariant that keeps this safe is that a wide translation is refused
# where the device has no tier 2 to hold it. The pin therefore moved from "always false" to the capability being
# the device's plus the guard, and it still forbids the translation from being duplicated here.
for needle, why in (
    ("boolean argumentBuffersTier2 = compilation.device().supportsArgumentBuffersTier2();",
     "the compiler does not ask the DEVICE for the argument-buffer answer, so the wide shape is decided by a "
     "literal again"),
    ("MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout,\n"
     "                            argumentBuffersTier2);",
     "the compiler no longer asks the SHARED translator for the layout, so either the translation is duplicated "
     "here or it is asked with an answer that is not the device's"),
    ("if (translated.usesArgumentBuffers() && !argumentBuffersTier2) {",
     "a translation that came back wide is accepted on a device with no argument-buffer tier 2, so the resources "
     "would be laid out in a buffer that could not be made"),
    ("translated.usesArgumentBuffers()",
     "the artifact is not told whether its resources are carried by an argument buffer"),
    ("translated.vertexArgumentBufferSets()",
     "the compiler does not pass the vertex stage's argument-buffer sets to the artifact"),
    ("translated.fragmentArgumentBufferSets()",
     "the compiler does not pass the fragment stage's argument-buffer sets to the artifact"),
    ("MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(),\n"
     "                            translated.usesArgumentBuffers())",
     "the artifact's key does not name the profile and the binding-shape decision, so a direct artifact and a "
     "wide one could collide"),
):
    if needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

if "translate(vertexSpirv, fragmentSpirv, pipeline, layout, false)" in compiler:
    raise SystemExit(
        "metal 4 provider: the compiler asks for direct bindings by literal again, so a wide pipeline would be "
        "refused rather than carried through the table"
    )

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
    # The wide shape's own half: an encoder asked of the stage's own function, one layout per set per stage, and
    # the pack's own vertex-buffer base because an argument index is not a table slot.
    ("MTLArgumentEncoder.forFunction(vertexFunction, set)",
     "the artifact does not ask the vertex stage's own function for an argument encoder, so the buffer length "
     "would be a number this class guessed rather than the shader's layout"),
    ("MTLArgumentEncoder.forFunction(fragmentFunction, set)",
     "the artifact does not ask the fragment stage's own function for an argument encoder"),
    ("new MetalArgumentBufferLayout(MetalShaderStages.VERTEX, set, set,",
     "the vertex stage's argument buffer is not given the shared layout a plan is written against"),
    ("new MetalArgumentBufferLayout(MetalShaderStages.FRAGMENT, set, set,",
     "the fragment stage's argument buffer is not given the shared layout a plan is written against"),
    ("private static final int WIDE_VERTEX_BUFFER_BASE = 9;",
     "a wide pipeline has no fixed vertex-buffer base, so its vertex layouts would land in the argument index "
     "space the named bindings numbered"),
    ("? WIDE_VERTEX_BUFFER_BASE", "the wide vertex-buffer base is not the one the artifact uses"),
    ("layout.encoder().close();", "the argument encoders are not released with the artifact"),
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
    ("this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.argumentBufferLayouts(),",
     "the binding plan is not built with the artifact's argument buffers, so a wide pipeline's table would not "
     "cover the slot its argument buffer lands in"),
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
    # The wide pipeline's binding path, which is the whole of what this generation adds to the reference one: the
    # resources are written into a buffer by the shader's own argument encoder, and what the table carries is
    # that buffer's address at the slot the shared layout recorded. The two pins that matter for correctness are
    # the fault when no layout covers a binding, and the allocation of every layout up front - a wide pipeline's
    # table has a buffer slot per set and the shader dereferences whatever is in it.
    ("if (slot.indirect()) {\n            MetalGpuBuffer buffer = bufferOf(slice);",
     "an argument-buffer binding is written straight into the table, where its index is an argument index and "
     "not a table slot"),
    ("encoder.setBuffer(buffer.metalBuffer(), slice.offset(), slot.metalIndex());",
     "the argument buffer is not written with the buffer and offset the frame path bound, so the shader would "
     "read the wrong bytes"),
    ("encoder.setTexture(sampled.texture(), slot.metalIndex());",
     "a sampled image is not written into the argument buffer at the index the MSL declares"),
    ("encoder.setSamplerState(sampled.sampler(), slot.samplerMetalIndex());",
     "the sampler is not written into the argument buffer, so a sampled image would read one that is not there"),
    ("MTLArgumentEncoder encoder = bindArgumentBuffer(layout);",
     "the encoder is not asked of the pass's own argument buffer, so the write would go to a different buffer "
     "than the table slot points at"),
    ("MTLResourceOptions.of(MTLStorageMode.Shared, MTLHazardTrackingMode.Tracked)",
     "the argument buffer is not made with the storage and hazard tracking a CPU-written, GPU-read buffer needs"),
    ("this.owner.queueForDestroy(() -> ObjC.release(created.handle()));",
     "the argument buffer is not filed with the frame, so it would be released between encoding and execution"),
    ("table.address(buffer.gpuAddress(), layout.bufferIndex())",
     "the argument buffer's address does not reach the table slot the shared layout recorded, so nothing the "
     "shader dereferences would be the buffer this pass filled"),
    ("private void ensureArgumentBuffers() {",
     "the argument buffers are not all made when the pipeline is set, so a set whose resources are bound late "
     "would leave the shader dereferencing an address the table holds as nil"),
    ("        this.tablesAssigned = false;\n        ensureArgumentBuffers();",
     "the argument buffers are not made when the pipeline is set, so a wide pipeline's table buffer slots would "
     "still hold nil when the first draw reads them"),
    ("throw new IllegalStateException(\"no Metal 4 argument buffer carries '\" + slot.name() + \"' set=\"",
     "a binding no argument buffer carries is silently dropped rather than named as the disagreement between the "
     "translation and the artifact that it is"),
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
    ("private final Map<String, GpuBufferSlice> uniformBindings = new LinkedHashMap<>();",
     "a uniform bound before the pipeline is not remembered, so the binding the game makes first would be lost. "
     "The remembered value is the slice and not a resolved address, because an argument buffer needs the buffer "
     "and the offset the frame path bound rather than an addition of them"),
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
    ("        this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.argumentBufferLayouts(),\n"
     "                compiled.firstAvailableVertexBufferSlot(), compiled.vertexBufferCount());\n"
     "        releaseTables();",
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
    ("if (!NO_DRAWABLE_WAIT && !this.ring.waitForDrawable(drawable.handle())) {",
     "the queue is not told which drawable the command buffer about to be committed targets - the half of "
     "Apple's order that comes first, without which signalDrawable: is an unrecognised selector - except under "
     "the diagnostic switch that exists to price exactly this call"),
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
    ("M4_FRAME_COMMIT submission={} commitMs={}",
     "a submission's own GPU interval is no longer paired with the ordinal of the frame that submitted it, so a "
     "per-frame pacing trace has no GPU time in it and the populations cannot be read against it"),
    ("public long lastSlotWaitNanos() {",
     "the ring no longer keeps the frame's own slot wait, so a per-frame line cannot say what a frame waited on"),
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
    ("private static final boolean COUNTING = TRACE || STATS || FRAME_TRACE;",
     "the counters are not kept when any diagnostic is on - the trace, the summary or the per-frame pacing line "
     "- so a diagnostic run would report passes, tables and draws of zero"),
    ('Boolean.getBoolean("metallum.metal4FrameTrace")',
     "the per-frame pacing line cannot be asked for, so a window's populations cannot be classified from what "
     "each frame waited on"),
    ("M4_FRAME frame={} slots={} slot={} submission={} wallUs={} slotWaitUs={}",
     "the per-frame line no longer carries the frame's own waits, which is what the classification reads"),
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

# The mipmap format list is the Metal 3 encoder's list, and the two are compared here rather than trusted: a
# format Metal 3 will generate a chain for and Metal 4 refuses is a difference between the generations, and one
# that would only show up as a blurry texture.
def mipmap_formats(source: str, marker: str) -> set[str]:
    """The format names one mipmap-support switch lists, read as identifiers rather than as text.

    Reading them as text picked up the method's own signature - the switch's opening line ends in a parameter
    named `format`, and a split on commas happily returned `... GpuFormat format) { return switch (format) {
    R8_UNORM` as one entry. An identifier scan over the switch body cannot do that.
    """
    at = source.index(marker)
    body = source[source.index("return switch (format) {", at):source.index("default -> false;", at)]
    return set(re.findall(r"[A-Z][A-Z0-9_]*", body))


metal3_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal3"
                  / "MetalCommandEncoder.java")
if not metal3_encoder.is_file():
    raise SystemExit("metal 4 provider: MetalCommandEncoder.java is gone, so there is no reference list of the"
                     " formats a native mipmap command can filter")
metal3_source = metal3_encoder.read_text(encoding="utf-8")
m3_formats = mipmap_formats(metal3_source, "private static boolean supportsNativeMipmaps(")
m4_formats = mipmap_formats(encoder, "private static boolean supportsMipmapGeneration(")
if not m3_formats or m3_formats != m4_formats:
    raise SystemExit("metal 4 provider: the mipmap formats the two generations will generate a chain for differ:"
                     f" metal 3 {sorted(m3_formats)} against metal 4 {sorted(m4_formats)}")

# The zeroing kernels this generation dispatches, which are its own copy and its own cache.
storage_pipelines = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                     / "MTL4StorageTexturePipelines.java")
if not storage_pipelines.is_file():
    raise SystemExit("metal 4 provider: MTL4StorageTexturePipelines.java is gone, so a storage texture has no"
                     " kernel to be zeroed by")
storage_source = storage_pipelines.read_text(encoding="utf-8")
for needle, why in (
    ("public enum ScalarKind {", "the kernels are not split by scalar type, so a uint image has no kernel"),
    ("texture2d<float, access::write> image [[texture(0)]]",
     "the zeroing kernel does not take a writable 2D image"),
    ("public boolean clearZero(final MTL4ComputeEncoder encoder, final MTL4ArgumentTable table,",
     "the zeroing call does not take the table the image is bound through"),
    ("if (!table.texture(texture, 0L) || !encoder.setArgumentTable(table)) {",
     "the image is not put in the table and the table is not handed to the encoder, which is the whole difference"
     " between this generation's clear and Metal 3's"),
    ("case 2 -> encoder.dispatchThreads(width, height, 1L, 8L, 8L, 1L);",
     "the 2D clear does not dispatch over the texture's own extent"),
    ("private final Map<String, MemorySegment> pipelines = new HashMap<>();",
     "the pipelines are cached statically rather than owned by the encoder that made them, so a second device in"
     " one process would inherit the first one's"),
    ("public void close() {", "the pipelines this object made are never released"),
):
    if needle not in storage_source:
        raise SystemExit("metal 4 provider: " + why)
# An import or a use of the Metal 3 class, and not the class's own prose: the javadoc says in as many words which
# layer it is not reaching into, and a pin that read the whole file would refuse its own explanation.
for forbidden in ("import com.metallum.mtl.metal3", "com.metallum.mtl.metal3.MTLStorageTexturePipelines",
                  "metal3.MTLComputeCommandEncoder"):
    if forbidden in storage_source:
        raise SystemExit(f"metal 4 provider: the Metal 4 storage pipelines reach into the Metal 3 layer"
                         f" ({forbidden}), which is the cross-generation import the architecture law forbids")

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
    ("MetalFrameProbe.attachment(",
     "a colour attachment is not counted, so the probe's load and store traffic reports nothing"),
    ("MetalFrameProbe.depthAttachment(", "a depth attachment is not counted"),
    ("MetalFrameProbe.pipelineBound();", "a pipeline bind is not counted"),
    ("MetalFrameProbe.textureBound();", "a texture bind is not counted"),
    ("MetalFrameProbe.samplerBound();", "a sampler bind is not counted"),
    ("MetalFrameProbe.bufferBound();", "a buffer bind is not counted"),
    ("MetalFrameProbe.scissorSet();", "a scissor is not counted"),
    ("MetalFrameProbe.blit(width, height, textureOf(destination).pixelSize());",
     "a texture copy is not counted as a blit"),
    ("MetalFrameProbe.metal4Present();", "a present the full-frame path made is not counted"),
    ("long waited = System.nanoTime() - waitBegan;\n            this.lastSlotWaitNanos = waited;\n"
     "            MetalFrameProbe.submitWindowWait(waited);",
     "the ring's slot-reuse wait is not timed, so the waits line reports nothing for this path - and the "
     "per-frame trace, which reads the same wait out of this field, would report no wait at all"),
    ("MetalFrameProbe.gpuFrameMetal4(millis);", "the queue's per-commit GPU time is read but not reported to the"
     " probe, so a Metal 4 frame has no GPU time at all"),
):
    if needle not in encoder and needle not in pass_source and needle not in ring \
            and needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
if "private static int pixelSize(final GpuTextureView view) {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass cannot say how large an attachment's pixels are, so the probe's"
                     " attachment accounting would count nothing")

# Which passes that traffic is counted for. The counter has to cover every pass this path opens, or a frame that
# clears in passes of its own reads as cheaper than one that folds those clears into the passes that use the
# attachments - a comparison of two designs on a number that only one of them is paying into. The counter is
# also fed from the mapping that opens the descriptor and not from a caller's restatement of it, so the two
# cannot drift.
for needle, why in (
    ("public static void countAttachment(final Color color, final int pixelSize) {",
     "the attachment counter is not a function of the attachment the descriptor is opened with, so a caller "
     "restating the mapping could count traffic Metal was never asked for"),
    ("loadAction(color.contents(), color.clear() != null) == LOAD_LOAD",
     "the counter no longer asks the load mapping, so a cleared or discarded load would still be counted"),
    ("storeAction(color.contents()) == STORE_STORE",
     "the counter no longer asks the store mapping, so a discarded store would still be counted"),
    ("public static void countDepthAttachment(final Depth depth, final int pixelSize) {",
     "the depth attachment has no counter of its own, so the slot the pack side cannot answer for is uncounted"),
    ("depth.clearDepth() == null", "the counted depth load is not read from the attachment the pass is opened "
                                   "with"),
):
    if needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
if encoder_source.count("MetalFrameProbe.attachment(") != 1 \
        or encoder_source.count("MetalFrameProbe.depthAttachment(") != 1:
    raise SystemExit("metal 4 provider: the counter no longer has exactly one colour and one depth entry point, "
                     "so some attachment traffic is counted somewhere the mapping does not reach")
for needle, why in (
    ("MTL4RenderEncoder.countAttachment(color, pixelSize(view));",
     "the game's own passes are no longer counted, so the frame's traffic has a hole in it"),
    ("MTL4RenderEncoder.countDepthAttachment(depthAttachmentValue, pixelSize(view));",
     "the game's own passes count no depth traffic"),
    ("MTL4RenderEncoder.countAttachment(colors[index], colorPixelSizes[index]);",
     "a clear's pass of its own is not counted, so clearing the way this path does reads as free"),
    ("MTL4RenderEncoder.countDepthAttachment(depth, depthPixelSize);",
     "a clear's depth attachment is not counted"),
    ("MTL4RenderEncoder.countAttachment(presentAttachment, picture.pixelSize());",
     "the present pass is not counted, so the drawable it overwrites is missing from the frame's traffic"),
):
    if needle not in pass_source and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- what EXECUTES is a decision with a gate of its own ---------------------------------------------------
# The selector answers which generation the session is for; this answers which one encodes today, and the two
# are deliberately different facts. The two opt-in preferences execute what they selected - the player's
# `prefer-metal4`, which falls back to Metal 3 where the device cannot run Metal 4, and the developer's
# `metal4`, which the selector refuses to select as anything else - while AUTO and FORCE_METAL3 execute Metal 3
# whatever was selected: AUTO must not promote a frame path the migration has not finished (section 74's
# readiness gate), and a forced Metal 3 session stays Metal 3.
DEVICE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device = DEVICE.read_text(encoding="utf-8")
for needle, why in (
    ("case PREFER_METAL4, FORCE_METAL4 -> decision.selected();",
     "the executing generation is not decided from the preference, so either the player's opt-in would not run "
     "the path it asked for, or AUTO could promote an unfinished frame path"),
    ("MetalExecutionServices.of(decision.selected(), executesToday);",
     "the services are not built from both facts, so the selection and what executes could disagree again"),
    ("executing == MetalApiGeneration.METAL4" if False else "executesToday == MetalApiGeneration.METAL4",
     "a session that executes Metal 4 is not named as experimental, which is the one thing a reader of its "
     "numbers has to know"),
    ("Metal 4 EXECUTES this session", "the experimental warning does not say that Metal 4 is what runs"),
):
    if needle not in device:
        raise SystemExit("metal 4 provider: " + why)
# And the gate itself: AUTO must not be able to reach Metal 4 by the executing-generation line, and a player's
# preference must not be able to execute Metal 4 by a road that does not also carry the developer's strict one.
if "case AUTO -> MetalApiGeneration.METAL4" in device or "preference() == MetalExecutionPreference.AUTO" in device:
    raise SystemExit("metal 4 provider: AUTO can reach the executing Metal 4 path, which is the readiness gate "
                     "section 74 puts before it")
if "case AUTO, FORCE_METAL3 -> MetalApiGeneration.METAL3;" not in device:
    raise SystemExit("metal 4 provider: the executing-generation decision no longer names both generations that "
                     "must stay on the reference path, so a preference could promote a frame path the migration "
                     "has not finished")


# --- and it is reached by the EXECUTING generation, not by a constant ------------------------------------
if "switch (executing)" not in services:
    raise SystemExit("metal 4 provider: the services do not choose the provider by the executing generation, "
                     "so a session that executes Metal 4 would be built from Metal 3 objects - or the choice "
                     "is a constant again and this provider is dead code")
if "case METAL4 -> new com.metallum.render.metal4.Metal4ExecutionProvider();" not in services:
    raise SystemExit("metal 4 provider: the executing generation's Metal 4 case does not name this provider")

# --- and the present road is not started beside a frame path that already presents -------------------------
# Measured before it was written down: a forced Metal 4 session with `-Dmetallum.metal4Present=true` started the
# sidecar as well as the frame encoder's ring - two Metal 4 submission structures in one session, two
# commit-feedback registrations, one frame retirement model each - while only the frame encoder ever presented
# (1964 readbacks labelled with this generation's name, and none from the Metal 3 present road). Section 38
# forbids that shape by name and section 63 asks the migration to converge out of it, so the sidecar is started
# only for a session whose frame is encoded by a generation that does not present for itself, and its close asks
# the question its start asked.
for needle, why in (
    ("private boolean presentingThroughTheSidecar() {",
     "the present road is chosen from the policy alone, so a session that executes Metal 4 would start a second "
     "Metal 4 submission structure beside the frame encoder's own"),
    ("return presentsThroughMetal4() && executing != MetalApiGeneration.METAL4;",
     "the present road does not consider which generation executes, which is the fact that decides whether the "
     "sidecar is this session's present or a second one"),
    ("this.presentGate = presentingThroughTheSidecar()",
     "the present road is started without asking the question the helper states"),
    ("if (presentingThroughTheSidecar()) {",
     "the present road's close does not ask the question its start did, so a road that was never started could "
     "be closed, or a started one left behind"),
):
    if needle not in services:
        raise SystemExit("metal 4 provider: " + why)

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


# --- the compute road, which is the door the client's compute fixture reaches ------------------------------
# Vitrail's `compute-storage-contract` stopped on this path at "Active Metal execution state does not support
# compute", which is the neutral bridge asking its question and getting no. So this generation's state answers
# it now, and what is pinned here is the shape of that answer: the translation is the SHARED one, the pipeline
# state is cached by the context that caches the function it was made from, and the handle owns a table without
# owning the state.
COMPUTE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ComputePipeline.java"
CONTEXT = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4CompilationContext.java"
for path in (COMPUTE, CONTEXT):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so the compute road has no implementation")

compute = COMPUTE.read_text(encoding="utf-8")
context = CONTEXT.read_text(encoding="utf-8")


def without_comments(source: str) -> str:
    """The source with comments and string literals removed, so a rule reads what a compiler reads."""
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", source)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)


for needle, why in (
    ("implements MetalExecutionState, MetalComputeCompiler",
     "the Metal 4 state does not answer the neutral compute-compile question, which is the one Vitrail's "
     "fixture asks"),
    ("public Object compileCompute(final MetalDevice device, final String label, final ByteBuffer spirv)",
     "the compute compile's neutral signature is gone"),
    ("MetalComputeTranslator.translate(spirv)",
     "the state does not translate through the shared layer, so this generation has grown its own SPIR-V "
     "reflection or has none"),
    ("return new Metal4ComputePipeline(device, label, translated.entryPoint(), pipelineState,",
     "the compile does not answer this generation's pipeline resource, so a dispatch has nothing to name"),
):
    if needle not in state:
        raise SystemExit("metal 4 provider: " + why)

# One translation, two generations: the Metal 4 compute path may not carry SPIRV-Cross of its own.
for name, source in (("Metal4ExecutionState", state), ("Metal4ComputePipeline", compute)):
    if "spvc_" in without_comments(source):
        raise SystemExit(f"metal 4 provider: {name} carries its own SPIRV-Cross calls, so the compute "
                         "translation is duplicated rather than shared")

for needle, why in (
    ("synchronized MemorySegment getOrCompileComputePipeline(final String msl, final String entryPoint)",
     "the context does not compile a compute pipeline state, so every handle makes its own"),
    ("MemorySegment function = getOrCompileFunction(key.msl(), key.entryPoint());",
     "the pipeline state is not made from the cached native function, so the function cache is bypassed"),
    ("this.computePipelineCache.clear();",
     "the compute pipeline states are never released, so a session leaks one per kernel"),
):
    if needle not in context:
        raise SystemExit("metal 4 provider: " + why)
if context.index("for (MemorySegment pipeline : this.computePipelineCache.values())") > \
        context.index("this.computePipelineCache.clear();"):
    raise SystemExit("metal 4 provider: the compute pipeline cache is cleared before it is released")
# Read inside the method, not file-wide: the function cache's key is the same text, and a file-wide search would
# stay green while this cache lost the profile from its own.
compile_pipeline_body = body_of(context, "synchronized MemorySegment getOrCompileComputePipeline(")
if "new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token())" \
        not in compile_pipeline_body:
    raise SystemExit("metal 4 provider: the compute pipeline cache is not keyed by the profile, so a state "
                     "compiled for one MSL profile would be handed to a session on another")
if "this.computePipelineCache.clear();" not in body_of(context, "synchronized void clearCachesAfterGpuCompletion()"):
    raise SystemExit("metal 4 provider: the compute pipeline cache is not released with the caches, so it "
                     "outlives the completion that made the release legal")

for needle, why in (
    ("MTL4ArgumentTable newTable(final MTLDevice device) {",
     "the compute handle no longer makes a table for a dispatch, and every dispatch needs one sized to that"
     " kernel's argument counts - a cached one is the shape that reads what the first dispatch bound"),
    ("private final Map<String, MetalComputeTranslator.Binding> bindings;",
     "the handle does not store the shared translation's bindings, so a dispatch would have to re-reflect"),
    ("Map<String, MetalComputeTranslator.Binding> bindings() {",
     "the handle does not answer with its bindings, so a dispatch cannot fill a table from them"),
    ("MTL4ArgumentTable.create(device, this.bufferSlots, this.textureSlots, this.samplerSlots)",
     "the handle's table is not sized to the argument counts the translation gave it"),
):
    if needle not in compute:
        raise SystemExit("metal 4 provider: " + why)
# The state is SHARED, so a handle holds a reference rather than the object: it retains one of its own, and its
# close hands that reference to the device's deferred release. Both halves are pinned, because either one alone
# is a lifetime fault - no retain means a borrowed pointer into a cache the game clears on every resource reload
# (F3+T reaches `clearCachesAfterGpuCompletion`), and a direct `ObjC.release` means a handle that frees an object
# another handle is still dispatching through, or frees its own while encoded work may still name it.
for needle, why in (
    ("this.pipelineState = ObjC.retain(Objects.requireNonNull(pipelineState, \"pipelineState\"));",
     "the handle holds the pipeline state without a reference of its own, so a cache clear frees an object it "
     "is still dispatching with"),
    ("this.device.queueResourceRelease(this.pipelineState);",
     "the handle never gives its reference back, so every compiled kernel leaks its state"),
):
    if needle not in compute:
        raise SystemExit("metal 4 provider: " + why)
if "ObjC.release" in without_comments(compute):
    raise SystemExit("metal 4 provider: the compute pipeline handle releases a native object where it stands, "
                     "but work already encoded may still name it - the release belongs on the device's "
                     "destruction queue")
if "queueResourceRelease(" not in body_of(compute, "public void close()"):
    raise SystemExit("metal 4 provider: the handle's close does not hand its reference to the state back, so a "
                     "dispatched kernel's state outlives every handle to it")

# And the nil a refused function answers with never reaches the pipeline factory: Metal asserts on
# `computeFunction must not be nil` and kills the process, which is not a compile the client can fall back from.
compile_pipeline = body_of(context, "synchronized MemorySegment getOrCompileComputePipeline(")
if "ObjC.isNil(function)" not in compile_pipeline or "MemorySegment.NULL" not in compile_pipeline:
    raise SystemExit("metal 4 provider: the compute pipeline cache asks the factory to build a state from a "
                     "function it has not checked, and a nil function aborts the process instead of failing the "
                     "compile")
if "Failed to compile Metal compute function for " not in state:
    raise SystemExit("metal 4 provider: a refused function is not named as itself, so a caller cannot tell a "
                     "kernel this device would not compile from a pipeline it would not make")


# --- and the dispatch, which is the half after the compile -------------------------------------------------
# The Metal 3 bridge's dispatch is per-resource encoder calls; this one is a table, and the facts that matter are
# the ones the new command model changed: the bindings are filled before the encoder opens, every allocation is
# declared resident, and the table is handed over before the dispatch that snapshots it.
dispatch_body = body_of(encoder, "public boolean dispatchCompute(")

if "MetalFrameResourceCommands, MetalFrameComputeCommands {" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder does not carry the neutral compute contract, so the "
                     "flat bridge's capability check answers no and the client never dispatches here")

for needle, why in (
    ("pipeline instanceof Metal4ComputePipeline resource", "the dispatch does not recognise this generation's "
     "pipeline resource, so it would answer false for its own handles"),
    ("MTL4ArgumentTable table = resource.newTable(this.executionState.device());",
     "the dispatch does not make a table for itself, and a table object re-pointed and handed to one encoder"
     " twice is not reliably re-read - measured in the cold-probe reproducer's one-encoder mode"),
    ("queueForDestroy(table::close);",
     "the dispatch's table is not given back through the frame's destruction queue, so it would outlive the"
     " slot that may still read it - or leak"),
    ("case UNIFORM_BUFFER, STORAGE_BUFFER -> bindDispatchBuffer(table, binding, buffers);",
     "buffers are not bound by address through the table"),
    ("case SAMPLED_IMAGE -> bindDispatchSampledImage(table, binding, textures, samplers);",
     "sampled images are not bound with their samplers"),
    ("case STORAGE_IMAGE -> bindDispatchStorageImage(table, binding, textures);",
     "storage images are not bound, so a kernel that writes one writes nothing"),
    ("MTL4ComputeEncoder compute = dispatchEncoder(\"the dispatch of \" + resource.label());",
     "the dispatch does not open an encoder of its own, and one encoder carrying two dispatches is the shape"
     " that lost the second one in the probe"),
    ("compute.setComputePipelineState(resource.pipelineState())",
     "the dispatch never hands the encoder the pipeline"),
    ("compute.setArgumentTable(table)", "the dispatch never hands the encoder the table it filled"),
    ("compute.dispatchThreadgroups(groupsX, groupsY, groupsZ, localX, localY, localZ)",
     "the dispatch is not encoded as workgroups, which is the shape a pack's vkCmdDispatch has"),
    ("compute.barrierForSubsequentEncoders();",
     "the dispatch's encoder ends without its producer barrier, so whatever encoder follows it - and an encoder"
     " per dispatch means something always does - may not see what the dispatch wrote"),
):
    if needle not in dispatch_body:
        raise SystemExit("metal 4 provider: " + why)

# The order of the three encoder calls is the API's: a pipeline, then the table it reads through, then the
# dispatch that snapshots it. Any other order encodes a dispatch the driver has nothing to run or nothing to
# bind, which is why this is a position check and not three presence checks.
# The one-encoder-per-dispatch rule lives in two helpers beside the dispatch, so it is pinned against the file.
for needle, why in (
    ("private MTL4ComputeEncoder dispatchEncoder(final String which) {",
     "there is no one place that says a table-binding dispatch gets a new encoder, so the rule could be lost"
     " one call site at a time"),
    ("private void endDispatchEncoder(final MTL4ComputeEncoder compute) {",
     "a dispatch encoder is not ended and filed for release in one place, so one of the two could be missed"),
    ("queueForDestroy(compute::close);",
     "a dispatch's encoder is released where it stands, and an encoder released before its command buffer is"
     " committed aborts the driver - measured"),
    ("this.copyEncoder.barrierForSubsequentEncoders();\n            this.copyEncoder.endEncoding();",
     "a copy encoder left open is not ended with its barrier before a dispatch opens its own, so the copies the"
     " dispatch reads are not ordered against it - or two encoders end up open at once"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

_pipeline_at = dispatch_body.index("compute.setComputePipelineState(resource.pipelineState())")
_table_at = dispatch_body.index("compute.setArgumentTable(table)")
_dispatch_at = dispatch_body.index("compute.dispatchThreadgroups(groupsX, groupsY, groupsZ, localX, localY, localZ)")
if not _pipeline_at < _table_at < _dispatch_at:
    raise SystemExit("metal 4 provider: the dispatch hands over the pipeline, the table and the workgroups in "
                     "an order the API does not allow")

# The residency declaration is not decoration on this path: an undeclared allocation reads as nothing at all,
# which the cold record measured one declaration at a time.
for helper in ("bindDispatchBuffer", "bindDispatchSampledImage", "bindDispatchStorageImage"):
    helper_body = body_of(encoder, f"private void {helper}(")
    if "useResource(" not in helper_body:
        raise SystemExit(f"metal 4 provider: {helper} binds a resource without declaring it resident, and an "
                         "undeclared allocation reads as nothing at all on this path")
# And every binding is resolved before the encoder is opened, so a caller's missing binding is a refusal with
# nothing encoded rather than a half-bound dispatch.
if "((MetalGpuTexture) view.texture()).markContentsDirty();" \
        not in body_of(encoder, "private void bindDispatchStorageImage("):
    raise SystemExit("metal 4 provider: the storage image's bookkeeping is not invalidated, so a clear the "
                     "engine recorded as materialized would be elided over contents a dispatch overwrote")

_first_binding = min(dispatch_body.index(call) for call in
                     ("bindDispatchBuffer(", "bindDispatchSampledImage(", "bindDispatchStorageImage("))
if dispatch_body.index("dispatchEncoder(") < _first_binding:
    raise SystemExit("metal 4 provider: the dispatch opens its encoder before the bindings are resolved, so a "
                     "missing binding would be found with the pipeline already set")
# The address of a slice is one addition, and it is not this class's to repeat.
if "Metal4RenderPass.addressOf(slice.buffer(), slice.offset())" not in body_of(encoder, "private void bindDispatchBuffer("):
    raise SystemExit("metal 4 provider: the dispatch computes a buffer's GPU address itself instead of using "
                     "the one helper that adds the slice offset")
# The kind this generation cannot bind is refused rather than dropped.
if "case TEXEL_BUFFER -> throw new IllegalStateException(" not in dispatch_body:
    raise SystemExit("metal 4 provider: a binding kind the dispatch cannot fill is dropped in silence")


# --- and a refusal by name is said out loud as well as thrown ----------------------------------------------
# Measured on the first no-pack Metal 4 session that was read rather than counted: the presented frame was one
# flat clear colour (`00b8d2ff` at all twenty-five samples of all 4958 readbacks), the world's `Terrain` pass ended
# with `draws=0` on every one of its 5316 traced passes, and the log said nothing - because the game's terrain
# batching asks for a multi-draw, the Metal 4 pass refuses it by throwing, and the caller catches the throw.
# Section 35 forbids a silent drop, and a throw alone is not enough when the caller swallows it: the refusal is
# logged where it is made, naming the pass, once per operation rather than once per draw.
if ("Metal 4 render pass '{}': {} is not encoded by this path yet, so the work that" not in pass_source):
    raise SystemExit("metal 4 provider: a refused operation is not said out loud, so a caller that catches the "
                     "throw drops the work with nothing in the log - measured as a world missing from a frame whose "
                     "session reported no fault")
for needle, why in (
    ("if (REFUSED_OPERATIONS.add(operation)) {",
     "the refusal line is not de-duplicated, so a refused multi-draw asked for every frame would fill a session's "
     "log"),
    ("private static final java.util.Set<String> REFUSED_OPERATIONS",
     "the refusal names are not kept anywhere, so the once-per-operation line has nothing to check"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- the drawable readback, which is the only way this machine can see the picture -------------------------
# The display cannot be photographed here and a drawable that is framebuffer-only cannot be copied from, so the
# picture column of every session has been empty for a reason about the *observation* rather than the frame.
# `-Dmetallum.drawableReadback=true` turns the layer's framebufferOnly off and copies the presented drawable into
# a shared buffer, where it can be read. It is a diagnostic and it is pinned as one: off by default, said out
# loud when on, asked for through one accessor, and released with the frame.
LAYER = ROOT / "src/main/java/com/metallum/mtl/CAMetalLayer.java"
if not LAYER.is_file():
    raise SystemExit("metal 4 provider: CAMetalLayer.java is gone, so framebufferOnly is nowhere")
layer = LAYER.read_text(encoding="utf-8")
for needle, why in (
    ('System.getProperty("metallum.drawableReadback", "false")',
     "the drawable readback is not asked for by one property with a default of off"),
    ("SET_FRAMEBUFFER_ONLY.send(this.handle, !READBACK);",
     "the layer is framebuffer-only whatever the diagnostic says, so the copy it exists for would be refused -"
     " or it is off without anyone asking"),
    ("public static boolean readbackRequested() {",
     "the frame path cannot ask the layer whether the drawable may be read, so the property would be read twice"
     " and could disagree with itself"),
    ("framebufferOnly is OFF because", "a session that changes the layer's contract does not say so"),
):
    if needle not in layer:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("private final boolean drawableReadback = com.metallum.mtl.CAMetalLayer.readbackRequested();",
     "the frame encoder does not ask whether the drawable may be read"),
    ("copyDrawableForReadback(drawableTexture, width, height);",
     "the presented drawable is never copied out, so the picture is still unreadable"),
    ("staging = this.executionState.device().newBuffer(bytes, MTLStorageMode.Shared.value);",
     "the readback's staging buffer is not a shared buffer on this generation's device, so the CPU could not read"
     " what the GPU wrote"),
    ("useResource(staging.handle());",
     "the readback's staging buffer is not declared resident, and an undeclared resource makes a copy do nothing"
     " at all - measured"),
    ("copies.copyTextureToBuffer(drawableTexture, 0L, 0L, 0L, 0L, 0L, width, height, 1L,",
     "the drawable is not copied into the buffer the report reads"),
    ("reportDrawableReadback(this.ring.slot());",
     "the copied drawable is never read, or it is read before the slot's submission is known complete"),
    ("com.metallum.render.shared.DrawableReadback.report(\"metal4\", width, height,",
     "the frame path does not read its copied drawable through the shared formatter, so the two arms' lines"
     " would not be comparable"),
    ("copyPictureForReadback(picture.nativeHandle(), MTLTexture.width(picture.nativeHandle()),",
     "the picture this path's present triangle read is never copied out, so a wrong picture and a present that"
     " changed it would read the same"),
    ("reportPictureReadback(this.ring.slot());",
     "the copied picture is never read, or it is read before the slot's submission is known complete"),
    ("com.metallum.render.shared.DrawableReadback.reportPicture(\"metal4\", width, height,",
     "the frame path does not read its copied picture through the shared formatter, so the two arms' halves would"
     " not be comparable"),
    ("ObjC.release(this.pictureStaging[slot].handle());",
     "the picture readback's staging buffers are never released with the encoder"),
    ("com.metallum.render.shared.DrawableReadback.bytesPerRow(width);",
     "the readback's row stride is computed here rather than by the shared helper the other arm uses"),
    ("ObjC.release(this.readbackStaging[slot].handle());",
     "the readback's staging buffers are never released with the encoder"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)


# And the same readback on the reference arm, because a comparison needs both sides: the Metal 3 present road's
# helper answers the drawable it drew into, the encoder copies it in the same command buffer and reads it where
# that arm already waits - and both arms format through the shared layer.
SHARED_READBACK = ROOT / "src/main/java/com/metallum/render/shared/DrawableReadback.java"
if not SHARED_READBACK.is_file():
    raise SystemExit("metal 4 provider: the shared drawable formatter is gone, so the two arms would format"
                     " their own lines and a comparison would compare the formatting")
shared_readback = SHARED_READBACK.read_text(encoding="utf-8")
for needle, why in (
    ("public static void report(final String which, final long width, final long height,",
     "the shared formatter does not take which arm read the drawable, so the two lines could not be told apart"),
    ("rows(top first)=[{}] meanBGRA=",
     "the shared formatter prints nothing structural, so a reader could not tell a black drawable from a wrong"
     " one"),
    ("public static long bytesPerRow(final long width) {",
     "the row stride is not shared, so the two arms could disagree about it"),
    ("public static void reportPicture(final String which, final long width, final long height,",
     "the shared formatter cannot read the picture a present road sampled, so a reading could not tell a picture"
     " that was wrong from a present that changed it"),
    ('read("picture", which, width, height, pixels, bytesPerRow);',
     "the picture's line is not labelled apart from the drawable's, so one run's two halves would read as two"
     " frames"),
):
    if needle not in shared_readback:
        raise SystemExit("metal 4 provider: " + why)

M3_ENCODER = ROOT / "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java"
if not M3_ENCODER.is_file():
    raise SystemExit("metal 4 provider: MetalCommandEncoder.java is gone, so the reference arm has no drawable"
                     " readback and the comparison has one side")
m3 = M3_ENCODER.read_text(encoding="utf-8")
for needle, why in (
    ("private final boolean drawableReadback = com.metallum.mtl.CAMetalLayer.readbackRequested();",
     "the reference arm does not ask whether the drawable may be read"),
    ("MemorySegment drawableTexture =\n                    commandBuffer.encodePresentTextureToDrawable(",
     "the reference arm's present road does not take back the drawable it drew into, so it cannot be read"),
    ("blitCommandEncoder().copyFromTextureToBuffer(drawableTexture, 0L, 0L, 0L, 0L, width, height, staging, 0L,",
     "the reference arm never copies its drawable out"),
    ("reportDrawableReadback((int) (currentSubmitIndex % MAX_SUBMITS_IN_FLIGHT));",
     "the reference arm never reads what it copied, or reads it before the slot's submission is known complete"),
    ('com.metallum.render.shared.DrawableReadback.report("metal3", width, height,',
     "the reference arm does not read through the shared formatter"),
    ("copyPictureForReadback(source.nativeHandle());",
     "the reference arm never copies the picture its present triangle read, so the two halves of a comparison"
     " could only come from two runs"),
    ("reportPictureReadback((int) (currentSubmitIndex % MAX_SUBMITS_IN_FLIGHT));",
     "the reference arm's copied picture is never read, or it is read before the slot's submission is known"
     " complete"),
    ('com.metallum.render.shared.DrawableReadback.reportPicture("metal3", width, height,',
     "the reference arm does not read its picture through the shared formatter"),
    ("ObjC.release(this.pictureStaging[slot].handle());",
     "the reference arm's picture staging buffers are never released with the encoder"),
):
    if needle not in m3:
        raise SystemExit("metal 4 provider: " + why)

# --- and what buffers a session made can be named, because a missing world asked for it --------------------
# The no-pack Metal 4 frame is one flat clear and its terrain passes encode no draws; the three candidates left
# (no section visible, no GPU slice for a visible one, or no mesh at all) are told apart by whether the terrain's
# own buffers are created and how large they are - a question about the device, not about any pass. Off unless
# asked for, and one line per allocation.
DEVICE_SOURCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device_source = DEVICE_SOURCE.read_text(encoding="utf-8")
for needle, why in (
    ('Boolean.getBoolean("metallum.logBuffers")',
     "the buffer diagnostic is not asked for by one property, so it could not be off by default"),
    ('com.metallum.Metallum.LOGGER.info("Metal buffer: {} bytes, usage {} - {}", size, usage,',
     "an allocation is not named, so a missing terrain mesh and an unbound one read the same"),
):
    if needle not in device_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and the device does not claim what this path has not delivered ------------------------------------------
# Measured with one variable changed. With `persistentMapping` advertised true, Sodium stages its chunk meshes
# through a persistently mapped buffer - `MojangStagingBuffer`'s constructor picks `MappedStagingBuffer` on that
# flag and the engine-staged path otherwise - and on this path not one of them arrives: a no-pack Metal 4 session
# presented one flat sky-blue clear for all 4958 readbacks of a 40 s window (and again after 90 s), Sodium's own
# upload step reported build results every frame, and the geometry arena that would mean a mesh was accepted was
# never allocated, on either arm's log. With the flag withdrawn the same launch draws the world - the sampled
# terrain cells are the Metal 3 arm's own, cell for cell - and a Metal 3 launch is byte for byte unchanged. Where
# the mapped path loses the data is not localised, so the claim stays withdrawn until it is: the engine-staged
# path this selects instead goes through `writeToBuffer`, which both generations implement.
#
# The withdrawal was written for the whole device, though, and the flag is a fact about a generation: Metal 3
# advertised it since the backend existed and its frames were never the ones losing meshes, so the device-level
# answer made one generation's workaround decide the other generation's upload road. It is derived from what
# executes now, and what this pin refuses is the shape that leaked: a literal here would put the device - which
# knows nothing about the frame path - back in charge of a generation's answer. `tools/ci-contracts.py` holds
# the other half of the rule, including the generation test itself.
if "new DeviceFeatures(false, false, true, true, true, false, false)," in device_source:
    raise SystemExit("metal 4 provider: the device advertises persistently mapped buffers again as a device-wide "
                     "literal, so one generation's workaround would decide the other generation's staging road - "
                     "and on this path a session that stages through a mapped buffer loses the world's geometry: "
                     "measured as a no-pack frame that is one flat clear while Sodium's arena is never allocated")
if "persistentMappingFor(this.services.executing())" not in device_source:
    raise SystemExit("metal 4 provider: persistentMapping is not answered from what executes, so Metal 4's "
                     "engine-staged road and Metal 3's own could not be told apart")

# --- and a draw is counted by every path that encodes one -----------------------------------------------
# The pass's counters are what its own trace line and the frame's `drawsPerFrame` are made of. The indirect
# indexed path did not increment them, and the world's terrain pass - which Sodium batches as indirect draws -
# therefore read `draws=0` on every one of 22836 endings in a frame that was drawing the world correctly. That
# single false reading sent two rounds of localisation after a pass that was never empty, so the count is pinned
# where the encoders are, not where the numbers are printed.
for needle, why in (
    ("            this.indexedEncoded++;\n            this.drawsEncoded++;\n            indirect +=",
     "the indirect indexed draw is not counted, so a pass that draws through it reads as an empty pass - measured "
     "as a terrain pass reporting zero draws while the world rendered"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and the trace says what a pass read as well as what it wrote -------------------------------------------
# A pass's attachments alone cannot answer the history question: on a target the pack doubles for history, two
# physical textures stand for one logical name, and "the pass read the copy it is about to write" and "the pass read
# the right copy whose write did not land" look identical from the write side. Measured with this line: every
# history pass samples exactly the copy the pass before it wrote (composite writes 0x..de00 and samples 0x..db80,
# composite1 writes 0x..db80 and samples 0x..de00, composite2 writes 0x..de00 and samples 0x..db80), in all 1783
# endings of the run - so the binding is not what breaks the chain, and the round that added this stopped having to
# argue about it.
for needle, why in (
    ("private String sampledTextures() {",
     "the trace cannot say which texture a pass sampled, so a wrong copy and an unlanded write read the same"),
    ("samples=[{}]", "the sampled textures are not printed on the pass's own line"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and a copy's rectangle is read in the contract's order, not the implementation's ----------------------
# Measured as a failing history chain and found in one trace line. The shared contract is
# `copyTextureToTexture(source, destination, mipLevel, destX, destY, sourceX, sourceY, width, height)`; this path's
# override declared `(source, destination, mipLevel, x, y, width, height, destinationX, destinationY)`, so a correct
# caller - Vitrail's history swap-back passes zero offsets and the target's width and height, as the contract asks -
# was read as a rectangle of **0 by 0** at destination (width, height). Metal accepts a zero-sized copy without
# complaint, so every texture-to-texture copy on this path moved nothing and said nothing: the trace line printed
# `texture copy 0x.. -> 0x.. 0x0 level 0`, and the history fixture's chain, which depends on that copy bringing the
# alternate half back over the main one, latched to magenta on its first frame and stayed there for the whole run.
# The override now reads the contract's order and passes the two origins where the native selector wants them.
for needle, why in (
    ("final int destX, final int destY, final int sourceX,\n                                     final int sourceY,"
     " final int width, final int height) {",
     "the override's parameters are not in the shared contract's order, so a correct caller's rectangle is read as"
     " the wrong region - measured as a zero-sized copy that moved nothing"),
    ("copyTextureRegion(textureOf(source).nativeHandle(), 0L, mipLevel, sourceX, sourceY, 0L,\n"
     "                width, height, 1L, textureOf(destination).nativeHandle(), 0L, mipLevel, destX, destY, 0L)",
     "the source origin is not the caller's source origin, or the destination origin is not the caller's"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- and a compute encoder is reported as one ---------------------------------------------------------------
# The frame probe's counters are the only way the two arms' encoder kinds are compared, and this path reported
# render, blit and clear but never compute: Complementary Reimagined's shadow compute read as **532** compute
# encoders over 600 frames on the reference arm against **0** here, which is a difference in the counter and not in
# the frame. The call is made where the dispatch encoder is opened, which is the same place the reference arm makes
# it, and nothing else in the probe is fed by it.
for needle, why in (
    ("        MetalFrameProbe.encoderOpened(2);\n        try {\n            return MTL4ComputeEncoder.open(",
     "a dispatched compute encoder is not reported to the frame probe, so this path's compute counts read as zero "
     "however much it dispatches - measured against the reference arm's 532"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- and a per-pass creation event is not printed per pass -----------------------------------------------
# This path makes an argument table per pass, so a Photon session wrote 525893 lines to its log and 105187 of them
# were that one line, one per table per pass. The line is now said under the trace switch, which is the same
# property the per-pass trace uses, and the routine fact stays with the frame probe's `tablesPerFrame`, which
# counts every table without printing any. **It is hygiene and not a fix**: gating it was first tried as the
# explanation for a pack load that stopped, and it changed that session's outcome by nothing - the same 251 pack
# units served at the same twelve seconds, before and after. The pin holds the gating; it does not claim a cause.
ARGUMENT_TABLE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4ArgumentTable.java"
table_source = ARGUMENT_TABLE.read_text(encoding="utf-8")
for needle, why in (
    ('private static final boolean TRACE = Boolean.getBoolean("metallum.metal4Trace");',
     "the table's creation line is not gated on the trace switch, so a pack with many passes prints a line per"
     " table per frame - measured as 105187 of 525893 lines and a load that served 251 units in 300 seconds"),
    ("            if (TRACE) {\n                Metallum.LOGGER.info(\"Metal 4 argument table: made for",
     "the creation line is printed unconditionally again"),
):
    if needle not in table_source:
        raise SystemExit("metal 4 provider: " + why)

# --- the device waits for completion once, and not again on a ring the encoder has released -----------------
# Section 71's lifecycle gate had never run, because every session so far was *stopped* rather than quit. Driving
# the quit from inside the client gave the teardown its first real-device reading, and the reading was a false
# alarm: `MetalDevice.close()` waited for submitted work, closed the frame encoder - which submits any open pass,
# waits, and releases the ring - and then cleared the pipeline cache, whose own wait landed on that released ring.
# Measured after `Minecraft`'s `Stopping!`: the encoder's wait proved submission 3813 complete in 0 ms with
# `awaited=[3811, 3812, 3813]`, and the next wait read the same value as a timeout while the ring said
# `awaited=[0, 0, 0]`. The clear was also redundant - `executionState.close()` clears the same caches at the end -
# so the pin is the order: the device's close waits, closes the encoder, and does not clear the caches itself.
DEVICE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device_source = DEVICE.read_text(encoding="utf-8")
device_close = body_of(device_source, "public synchronized void close()")
if device_close is None:
    raise SystemExit("metal 4 provider: MetalDevice.close() was not found, so the teardown that runs once a "
                     "session is not pinned at all")
waited_at = device_close.find("this.waitForSubmittedGpuWork();")
encoder_at = device_close.find("this.commandEncoder.close();")
state_at = device_close.find("this.executionState.close();")
if min(waited_at, encoder_at, state_at) < 0 or not waited_at < encoder_at < state_at:
    raise SystemExit("metal 4 provider: the device's teardown no longer waits for submitted work, closes the "
                     "encoder that releases the ring, and releases the state that owns the caches - in that order")
if "this.clearPipelineCache();" in device_close:
    raise SystemExit("metal 4 provider: the device's teardown clears the pipeline cache after the encoder's close, "
                     "so the wait inside that clear lands on a released ring and reports a completion that already "
                     "arrived as a timeout - measured as submission 3813 with awaited=[0, 0, 0]")
# ---------------------------------------------------------------------------
# Section 88's per-pass GPU time: the frame path reads the GPU's clock behind its own pass boundaries
#
# The road was proven by the cold probe's counter smoke before any of this existed (its intervals scale with
# the work, its unit is a nanosecond, and an interval below about two thousand ticks is not ordered). What this
# pins is the frame path's use of it, because every one of these properties is a way the table would quietly
# stop being a measurement: a marker written before the pass ended, a read taken before the ring's wait, a
# second sampling form, a report that hides the floor, or a heap that outlives the encoder whose slot it
# describes.
# ---------------------------------------------------------------------------
pass_times = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
              / "Metal4PassTimes.java")
if not pass_times.is_file():
    raise SystemExit("metal 4 provider: Metal4PassTimes is missing, so the frame path has no per-pass GPU time "
                     "at all and section 92's third kind of timing is an assertion rather than a reading")
pass_times = pass_times.read_text(encoding="utf-8")
for needle, why in (
    ('Boolean.getBoolean("metallum.metal4PassTimes")',
     "the per-pass reader has no switch, so it either never runs or always does - and section 91 says "
     "instrumentation is off by default unless its overhead has been measured"),
    ("floorUs=2.0", "the report does not name the road's resolution floor, so a pass under it reads as a fast "
     "pass rather than as noise"),
    ("never the CPU's", "the line does not say which of section 92's three kinds of timing it is, so a reader "
     "cannot tell a GPU interval from the CPU's encode time"),
    ("resolveRange(0L, count)", "the slot's own frame is not read as one range, so the reading is of entries "
     "resolved one at a time rather than of the packed range the header promises"),
    ("this.totals.computeIfAbsent(label", "the intervals are not attributed to the pass that ended at the "
     "marker, so the table cannot say which pass cost what"),
    ("this.heaps[slot].writeTimestamp(commandBuffer, at)", "the boundary markers are not written into the "
     "slot's own heap at its own index"),
):
    if needle not in pass_times:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("this.passTimes = Metal4PassTimes.create(nativeDevice, FRAMES_IN_FLIGHT);",
     "the reader is not made once per encoder with one heap per slot, so its heaps would outlive or lag the "
     "ring they describe"),
    ("this.passTimes.beginFrame(this.ring.slot(), this.ring.commandBuffer());",
     "the slot's previous frame is not read where the ring has already waited for it, which is the header's own "
     "condition for resolving a heap on the CPU timeline"),
    ("this.passTimes.boundary(this.ring.slot(), this.ring.commandBuffer(), label);",
     "the pass boundary is not written from one place, so a pass can end without a marker"),
    ('recordPassBoundary("the present");',
     "the present is not counted with the passes, though it is a pass of the frame's own command buffer"),
    ("this.passTimes.close();", "the heaps are not released with the encoder that made them"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if "this.owner.recordPassBoundary(label());" not in pass_source:
    raise SystemExit("metal 4 provider: a render pass no longer records its own boundary when it ends, so the "
                     "marker would be placed somewhere other than behind the pass")

for needle, why in (
    ("this.ring.describe()",
     "the ring's state is not printed, so a wait that times out cannot say which value it waited for"),
    ("public String describe() {", "the ring has no state description to print"),
):
    if needle not in encoder and needle not in (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl"
                                                / "metal4" / "MTL4FrameRing.java").read_text(encoding="utf-8"):
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ('Metallum.LOGGER.info("Metal 4 frame encoder: waited {} ms for {} submission(s); complete={}, {}",',
     "the device-side wait reports nothing when it succeeds, so two waits on one ring cannot be told apart"),
    ('Metallum.LOGGER.info("Metal 4 frame encoder: closing - waited {} ms for {} submission(s); complete={}, {}",',
     "the encoder's close-time wait reports nothing when it succeeds"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# And the present names the texture it samples. "The GUI is not in the presented frame" is a question about two
# objects - the texture the passes drew into and the texture the present read - and a log that names one of them
# cannot answer it. Measured with this line: on a forced Metal 4 title screen the GUI's own pass and the present's
# picture are the same texture, so the missing GUI is not a mis-picked attachment.
if 'Metal 4 trace: presenting picture 0x{} {}x{} into a drawable 0x{} {}x{}' not in encoder:
    raise SystemExit("metal 4 provider: the present does not name the picture it samples and the drawable it "
                     "writes, so a frame with content missing cannot be told from a present that read another "
                     "texture")

# And every road that moves bytes declares both of its ends resident.
#
# This is the shape a whole interface's absence took. The Metal 4 header asks a copy's resources to be marked in an
# MTLResidencySet, this engine's model declares them with useResource, and an undeclared resource makes a copy do
# nothing on this API - silently, with no error and no fault. copyToBuffer was the one road that declared neither
# end, and it is the road Minecraft's own staged vertex buffer uses: the GUI's, the particles' and the entities'
# vertices arrived as zeros, every triangle collapsed to a point, and the draws were encoded, correctly bound,
# correctly stated and invisible on a frame whose world (drawn from Sodium's own buffers) was perfect. Measured on
# a forced Metal 4 title screen: the picture readback's mean went from (19, 17, 11) with no GUI in it to
# (40, 39, 33) with the buttons and the logo sampled, against Metal 3's own (40, 39, 33) on the same screen.
COPIERS = (
    "writeToBuffer", "copyToBuffer", "writeToTexture", "copyBufferToTexture", "copyTextureToTexture",
    "copyTextureToBuffer",
)
for name in COPIERS:
    signature = "void " + name + "("
    found = 0
    encoding = 0
    at = 0
    while True:
        start = encoder.find(signature, at)
        if start < 0:
            break
        at = start + 1
        found += 1
        body = encoder[start:encoder.find("\n    }", start)]
        # An overload that only hands its arguments to another overload encodes nothing and declares nothing, and
        # that is not the road this rule is about; the one that talks to the encoder is.
        if "copyEncoder()" not in body and ".copy" not in body.split("copyEncoder()")[0]:
            continue
        if "copyEncoder()" not in body:
            continue
        encoding += 1
        if "useResource" not in body:
            raise SystemExit("metal 4 provider: " + name + " encodes a copy without declaring either end resident,"
                             " and this engine's model makes an undeclared resource a copy that does nothing -"
                             " measured as the whole of Minecraft's GUI, particles and entities missing from a"
                             " frame whose world was correct")
    if found == 0 or encoding == 0:
        raise SystemExit("metal 4 provider: " + name + " is not an encoding road in the frame encoder any more, so"
                         " the road this contract is about has moved and the check is stale")

# And the rasterizer probe stays available, because it is what separated "this draw wrote nothing" from "this draw
# wrote something that looks like its background" - the reading that ended the hunt for Minecraft's GUI.
compiler = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
            / "Metal4PipelineCompiler.java").read_text(encoding="utf-8")
for needle, why in (
    ('System.getProperty("metallum.probeForceColour")',
     "the forced-colour probe is gone, so a draw that produces no pixel can no longer be told from one whose pixel "
     "matches its background"),
    ("out.fragColor = float4(1.0, 0.0, 1.0, 1.0);",
     "the forced-colour probe no longer forces a colour, so it probes nothing"),
):
    if needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

# And a Metal device that refuses to initialize says that the reference path is skipped too.
#
# Measured under Metal API validation: forcing -Dmetallum.execution=metal4 on a device that does not satisfy the
# contract fails backend creation, and the backend the game picks afterwards is OpenGL - not the Metal 3
# reference every comparison in this programme is against. Nothing in the session said so, which is how a
# developer ends up measuring neither generation.
backend = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalBackend.java"
           ).read_text(encoding="utf-8")
if "will not run the Metal 3" not in backend:
    raise SystemExit("Metal 4 execution provider contract: a Metal device that refuses to initialize does not say "
                     "that the Metal 3 reference path is skipped as well, so a forced Metal 4 session on a device "
                     "that cannot take it measures OpenGL with nothing in the log saying so")

# --- a buffer the shader reads as a texture ---------------------------------------------------------------
# The frame path can bind a `GpuBuffer` by name, and a shader may read it either as a buffer (a uniform or
# storage buffer) or as a texture (a texel buffer, which Metal presents as a view over the buffer's memory).
# Asking for a buffer slot alone dropped every texel buffer in silence, and the game's own cloud is drawn from
# exactly that shape: its face data is a texel buffer bound through `setUniform`, so the vertex stage read a
# slot nothing had filled and every face collapsed toward one point - clouds piled up over the camera. The plan
# has to carry the format for it, the pass has to ask for the texel kind *before* the buffer kind, the view has
# to be created over the buffer's memory, and it has to be released with the pass's other transients.
BINDING_PLAN = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "Metal4BindingPlan.java").read_text(encoding="utf-8")

for needle, why in (
    ("public @Nullable Slot texelBuffer(final String name)",
     "the binding plan cannot be asked for the texel buffer a name declares, so the frame path has only the "
     "buffer-slot question and a texel buffer is dropped again"),
    ("@Nullable GpuFormat texelBufferFormat) {",
     "the plan's slot no longer carries the format a texel buffer is read as, and a view made without it would "
     "read the buffer at the wrong stride"),
    ("resource.argumentBufferSet(), resource.texelBufferFormat()))",
     "the plan is built without the binding's texel format, so every texel buffer would be refused as missing "
     "one"),
):
    if needle not in BINDING_PLAN:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("Metal4BindingPlan.Slot texel = plan == null ? null : plan.texelBuffer(name);",
     "the Metal 4 pass asks only for a buffer slot when a buffer is bound by name, which is how a texel "
     "buffer - a buffer the shader reads as a texture - was dropped without a word"),
    ("fillTexelBuffer(name, texel, slice);",
     "nothing builds a texture view over the buffer a texel-buffer binding names"),
    ("MTLTexture.newBufferTextureView(",
     "the texel-buffer view is no longer a Metal texture created over the buffer's memory, which is the only "
     "way a `texture_buffer` argument can be read"),
    ("this.owner.queueForDestroy(() -> ObjC.release(view));",
     "the texel-buffer view is never released, so every frame with a texel buffer leaks one"),
    ("Metal4BindingPlan.Slot texel = plan.texelBuffer(name);",
     "a texel buffer bound before its pipeline arrives is never re-applied, so the first frame of such a pass "
     "reads an unbound slot"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

print("Metal 4 execution provider contract: PASS")
