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
    ('throw new Metal4ExecutionProvider.Unimplemented("getOrCompilePipeline"',
     "the state no longer refuses compiling by name, so a Metal 4 session would be handed an artifact whose "
     "first use fails somewhere else"),
    ("return List.of();", "evictCachedPipelines no longer answers with the truth about an empty cache"),
    ("public void clearCachesAfterGpuCompletion() {", "the cache clear is gone, so a pack reload has no answer"),
    ("public void close() {", "the state has no release, so a teardown has nothing to call"),
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

# Every operation the game can ask for and this path cannot perform is refused by name. The list is the
# migration's own remaining work, one line per operation.
for operation in ("transientMemory", "createRenderPass", "submitRenderPass", "clearColorTexture",
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
    ("state.getOrCompilePipeline(null, null)",
     "the harness does not ask the state to compile, so the one refusal that matters goes unmeasured"),
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
