#!/usr/bin/env python3
"""Pins the Metal 4 cold-probe harness, because a harness that quietly stops measuring is worse than none.

The intermittent capability probe is the one thing blocking Metal 4 AUTO, and the only instrument that can
measure a per-process distribution is a process that does nothing else. Three lessons were paid for building
it, and each is a way a later edit could break the harness while it still ran:

  - the probe draws with the engine's built-in pipelines, so a standalone process has to hand their device
    over before probing. Measured: without it every probe fails at stage `exception` with
    `MTLBuiltinPipelines.device is null`, which reads as a device fault and is not one;
  - the results are a distribution over processes, so the two populations are counted apart - one probe per
    fresh JVM against repeated probes in one JVM. A harness that ran only one of them could not tell cold
    first use from anything else, which is the whole question;
  - the answer is one machine-readable line per attempt. A harness whose output has to be parsed out of a
    log is a harness nobody runs thirty times.

This file checks the shape and not the numbers: what the harness prints is data, and only the report may
claim a rate.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "metal4-cold-probe.sh"
PROBE = ROOT / "tools" / "metal4-cold-probe" / "Metal4ColdProbe.java"

for path in (SCRIPT, PROBE):
    if not path.is_file():
        raise SystemExit(f"cold-probe harness: {path.relative_to(ROOT)} is missing, so the per-process "
                         "distribution the AUTO blocker needs cannot be measured at all")

script = SCRIPT.read_text(encoding="utf-8")
probe = PROBE.read_text(encoding="utf-8")

# --- the two populations, asked for by name and defaulted to something worth running -------------------
for needle, why in (
    ("--cold-runs", "the harness cannot be told how many separate processes to probe, so the cold "
                    "population - the one the intermittent fault lives in - is not selectable"),
    ("--warm-runs", "the harness cannot be told how many probes to repeat in one process, so there is no "
                    "control for cold first use"),
    ('--mode) mode="$2"; shift 2 ;;',
     "the harness cannot be told whether to measure the fault itself (one attempt) or the path the "
     "capability record reads (with its retry), so one of the two questions goes unanswered"),
    ('--probes-per-process) probes_per_process="$2"; shift 2 ;;',
     "the harness cannot be told to run more than one probe in a cold process, so a process that is bad and a "
     "draw that went wrong cannot be told apart - which is the question a cold-only fault turns on"),
    ("--out", "the harness cannot be asked to keep its raw lines, so a run's evidence cannot be re-read"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

cold_default = re.search(r"^cold_runs=(\d+)$", script, re.MULTILINE)
warm_default = re.search(r"^warm_runs=(\d+)$", script, re.MULTILINE)
if cold_default is None or warm_default is None:
    raise SystemExit("cold-probe harness: one of the two populations has no default, so a bare run "
                     "measures something the reader cannot name")
if int(cold_default.group(1)) < 30:
    raise SystemExit(
        f"cold-probe harness: the default cold runs are {cold_default.group(1)}, and the plan asks for at "
        "least 30 processes - at two failures in seventy a smaller default would usually measure nothing"
    )
if int(warm_default.group(1)) < 20:
    raise SystemExit(
        f"cold-probe harness: the default warm runs are {warm_default.group(1)}, and the plan asks for at "
        "least 20 repeated probes in one process"
    )
if "java -cp" not in script or "runClient" in script or "gradlew runClient" in script:
    raise SystemExit("cold-probe harness: the harness is not starting a bare JVM, so it is not measuring a "
                     "cold process - a client launch is the seventy seconds this exists to avoid")

# --- the built-in pipelines, which is the lesson the first run paid for ---------------------------------
if "MTLBuiltinPipelines.init(device)" not in probe:
    raise SystemExit(
        "cold-probe harness: the probe no longer hands the built-in pipelines their device before probing, "
        "so every attempt will fail at stage `exception` with a null device field - which reads as a device "
        "fault and is an omission in the harness"
    )
if "MTLBuiltinPipelines.close()" not in probe:
    raise SystemExit("cold-probe harness: the pipelines the probe drew with are never released, so an "
                     "attempt counted as passing is not an attempt that gave its resources back")

# --- one machine-readable line per attempt, with the fields the plan names -------------------------------
if "M4_PROBE_RESULT" not in probe:
    raise SystemExit("cold-probe harness: the result is not printed as a machine-readable line, so a run of "
                     "thirty processes would need a log parser")
# The loop that gives each cold process its probes: a harness that always passed 1 would run the flag and
# ignore it, which is the shape a pin on the usage text cannot see.
if 'Metal4ColdProbe "$index" "$attempts" "$mode"' not in script:
    raise SystemExit("cold-probe harness: the mode the harness was told is never passed to the process, so "
                     "--mode is parsed and ignored and every run measures the same path")

if 'line="$(run_one "$index" "$probes_per_process")"' not in script:
    raise SystemExit("cold-probe harness: the cold loop does not pass the per-process probe count to the "
                     "process, so the flag is parsed and ignored and every process still runs one probe")

for field in ("process=", "attempt=", "mode=", "retried=", "success=", "stage=", "reason=", "epochMs=", "canMakeAndSubmit=",
              "canBindAndDraw=", "familyMetal4=", "queueSelector=", "argumentTableSelector=",
              "deviceCreation=", "deviceName=", "probeMs=", "elapsedMs="):
    if field not in probe:
        raise SystemExit(f"cold-probe harness: the result line has no {field.rstrip('=')} field, which the "
                         "plan asks every attempt to report")
# A fault that clusters in a burst of consecutive processes is a fact about the machine as much as about the
# probe, and a per-process duration cannot show a cluster: absolute time is what lines a failure up against
# whatever else was running.
for needle, why in (
    ('+ " epochMs=" + System.currentTimeMillis()',
     "the result line carries no absolute time, so a cluster of failures cannot be lined up against anything "
     "the machine was doing"),
):
    if needle not in probe:
        raise SystemExit("cold-probe harness: " + why)

if "System.exit(allPassed ? 0 : 1)" not in probe:
    raise SystemExit("cold-probe harness: the process exit code does not carry the verdict, so a failure can "
                     "only be found by reading output")

# --- the device the failures were captured on, and the stage that carries them --------------------------
if "lastFailureStage()" not in probe or "lastFailure()" not in probe:
    raise SystemExit("cold-probe harness: the probe's own stage and reason are not read, so a failure would "
                     "be reported as a bare false - which is what the capability record was already doing")
if "canMakeAndSubmit" not in probe or "canBindAndDraw" not in probe:
    raise SystemExit("cold-probe harness: the two probe stages are not both asked, so a failure cannot be "
                     "attributed to the command structure or to the binding and draw")

# --- and the fix itself, in both halves ---------------------------------------------------------------
# The retry exists because the FIRST probe of a process can fail and no later one ever has (measured: every
# failure in 160 cold processes was its first attempt, and 1100 later probes passed). Both halves are pinned
# because either one alone would leave the capability record answering from a single attempt again - and the
# harness's own mode is how the two paths are told apart, so a harness that stopped taking the retry would
# report a fault the client no longer has.
if "canBindAndDrawPersistently" not in probe:
    raise SystemExit("cold-probe harness: the harness never takes the persistent path, so --mode production "
                     "measures one attempt and reports it as the capability record's answer")
if "production ? MTL4Probe.canBindAndDrawPersistently(device)" not in probe:
    raise SystemExit("cold-probe harness: the harness knows the mode and does not choose the path by it, so "
                     "the two populations it counts are the same population")

metal4 = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "Metal4.java").read_text(encoding="utf-8")
if "MTL4Probe.canBindAndDrawPersistently(device)" not in metal4:
    raise SystemExit(
        "cold-probe harness: the capability record asks the probe once and not persistently, so the first "
        "attempt in a process can still be recorded as `this device cannot` - which is the whole of the AUTO "
        "blocker; the retry belongs on this path and not only in the harness"
    )
# The retry's own visibility: a fix whose firing cannot be seen cannot be verified, and the verification this
# milestone owes is exactly "a first attempt failed and the second answered".
if "lastRetried()" not in probe:
    raise SystemExit("cold-probe harness: the harness never reports whether the persistent path asked twice, "
                     "so a production run cannot show that the retry is what answered")
if "retried = true;" not in (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                             / "MTL4Probe.java").read_text(encoding="utf-8"):
    raise SystemExit("cold-probe harness: the persistent probe never records that it retried, so lastRetried "
                     "answers false whatever happened")

# --- the fourth render smoke's binding half --------------------------------------------------------------
# The migration plan's smoke 4 is "a sampled texture and a sampler, drawn as a fixed pattern, read back". The
# binding half is what the present sidecar exercises on the real path and what this proves in a process with no
# window in it; the draw and readback are the other half and are recorded as owed rather than implied.
probe_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "MTL4Probe.java").read_text(encoding="utf-8")
for needle, why in (
    ("public static boolean canBindSampledTexture(", "the sampled-texture smoke is gone from the probe"),
    ("MTL4ArgumentTable.create(device, 0L, 1L, 1L)",
     "the smoke does not make a table of the shape it is testing, so its answer is about some other table"),
    ("return failed(\"sampled\", \"the table refused setTexture:atIndex:",
     "a refused texture binding is not reported, so a table that took the call and dropped it would read as "
     "success"),
    ("return failed(\"sampled\", \"the table refused setSamplerState:atIndex:",
     "a refused sampler binding is not reported"),
    ("releaseIfPresent(texture);", "the smoke's source texture is never released"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
if "sampled=" not in probe:
    raise SystemExit("cold-probe harness: the harness does not report the sampled-texture smoke, so it has no "
                     "evidence from an Apple Silicon run")

# --- the fourth render smoke's drawn half ----------------------------------------------------------------
# The binding half proved a table accepts a texture and a sampler. The drawn half is the plan's own smoke -
# "drawn as a fixed pattern, read back" - and it is a sequence of its own: a pattern pass, the producer barrier
# the new command model requires of a dependency between encoders, a sampled pass through the table, one
# commit, and a readback of the same four quadrants in both textures. What the pins below are for is that each
# part of that chain is still there, because a smoke that quietly stopped drawing would still print a line.
for needle, why in (
    ("public static boolean canDrawSampledTexture(",
     "the drawn half of the sampled-texture smoke is gone from the probe, so the smoke the plan asks for is "
     "owed again"),
    ("private static final int[][] EXPECTED_PATTERN = {",
     "the drawn smoke has no expected pattern, so its readback cannot fail and cannot pass either"),
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ);",
     "the source texture no longer declares that a shader reads it, so the sampled pass reads a texture the "
     "device was never told about - the usage is part of the question and not bookkeeping"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ("BARRIER.send(encoder, STAGE_ALL, STAGE_FRAGMENT, VISIBILITY_DEVICE);",
     "the pass that fills the sampled source ends without the producer barrier, so the dependency between the "
     "two encoders is assumed rather than encoded - which is exactly what section 61 forbids while migrating"),
    ("if (!responds(encoder, BARRIER.name())) {",
     "the barrier is sent without asking the encoder for the selector first, so a device that does not "
     "implement it raises an Objective-C exception instead of reporting a stage"),
    ("encodePass(buffer, destination, sampled.handle(), STAGE_FRAGMENT, sampledPipeline, false,",
     "the sampled pass is not given the table at the fragment stage, so the table-bound texture and sampler "
     "have no stage to reach the shader on"),
    ("MTLTexture.bytes(source, pixel, 4L, x, y, 1L, 1L);",
     "the source is not read back, so a pattern that never landed is reported as a sample that never arrived"),
    ("MTLTexture.bytes(destination, pixel, 4L, x, y, 1L, 1L);",
     "the destination is not read back, so the drawn smoke claims a result it never measured"),
    ("so the sample reached the wrong place in the source",
     "a sample that landed in the wrong quadrant is not reported as one, so a flip reads as a wrong colour "
     "and the answer stops naming the fault"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

# The harness's own half: the drawn result is reported, and counted apart from the capability sequence. The
# print expressions are pinned rather than the bare field names, because the field names also appear in the
# class's own documentation - a pin that a comment can satisfy is a pin that a removed print still passes.
for needle, why in (
    ('+ " sampledDraw=" + sampledDraw',
     "the harness does not print the drawn smoke's answer, so a run of it leaves no evidence"),
    ('+ " sampledDrawReason=" + sampledDrawReason',
     "the harness prints whether the drawn smoke passed and not why it failed, which is the half that says "
     "where to look"),
):
    if needle not in probe:
        raise SystemExit("cold-probe harness: " + why)
if "MTL4Probe.canDrawSampledTexture(device)" not in probe:
    raise SystemExit("cold-probe harness: the harness never asks the drawn smoke, so the probe's answer is "
                     "measured nowhere")
# The driver counts the drawn smoke in a line of its own and fails the run on it: a smoke whose failures are
# only printed is a smoke the next reader has to notice by eye.
for needle, why in (
    ("sampled_draw_failures=\"$(grep -c ' sampledDraw=false ' \"$probe_log\" || true)\"",
     "the driver does not count the drawn smoke's failures, so a run cannot say how many there were"),
    ("if (( sampled_draw_failures > 0 )); then",
     "the driver counts the drawn smoke's failures and does not fail the run on them, so a failing smoke "
     "reports success through the harness's own exit code"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the frame's allocator rule --------------------------------------------------------------------------
# The one part of the frame's lifetime where a guess is a use-after-free, and the rule the frame encoder is
# built on: a slot is not reset until the value its own commit signalled has been observed. Measured on the
# device, the rule is load-bearing - with the wait removed, frame 0's pass never landed in five of five
# probes - so this file pins the order the two calls appear in and not merely that both exist.
#
# The pins below are the structural half of that guard and they are not the whole guard: a wait that is
# present in the text but short-circuited (`if (false && ...)`) passes every pin here, and is caught by the
# sequence itself, which asserts on the device that the ring waited exactly RING_FRAMES - FRAMES_IN_FLIGHT
# times. Structural pins and the device's own count together, and neither alone.
ring = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4FrameRing.java"
if not ring.is_file():
    raise SystemExit("cold-probe harness: MTL4FrameRing.java is gone, so the frame's allocator lifetime has no "
                     "owner and every frame path would have to grow a ring of its own")
ring_source = ring.read_text(encoding="utf-8")

wait_needle = "WAIT_UNTIL_SIGNALED.sendLong(event, awaited[next], WAIT_MILLIS)"
reset_needle = "RESET.send(allocators[next]);"
if wait_needle not in ring_source or reset_needle not in ring_source:
    raise SystemExit("cold-probe harness: the ring no longer waits for a slot's completion before resetting "
                     "it, which is the sentence MTL4CommandAllocator.h puts on the caller")
if ring_source.index(reset_needle) < ring_source.index(wait_needle):
    raise SystemExit("cold-probe harness: the ring resets the allocator BEFORE it has observed that slot's "
                     "completion value - the exact ordering MTL4CommandAllocator.h says the caller is "
                     "responsible for, and the ordering a run of this harness showed to be load-bearing")
begin_needle = "BEGIN.send(commandBuffer, allocators[next]);"
if begin_needle not in ring_source:
    raise SystemExit("cold-probe harness: the ring never begins the command buffer on the slot's allocator")
if ring_source.index(reset_needle) > ring_source.index(begin_needle):
    raise SystemExit("cold-probe harness: the ring begins encoding on the allocator and only then marks its "
                     "heaps for reuse, which would hand the memory the frame is being encoded into back to the "
                     "allocator underneath it")
for needle, why in (
    ("public boolean beginFrame()", "the ring has no begin, so nothing proves a slot is free before it is used"),
    ("awaited[slot] = ++signalled;", "a committed frame records no completion value, so its slot can never be "
                                     "proved free and would be reset blind"),
    ("SIGNAL_EVENT.send(queue, event, signalled);",
     "the commit is never signalled on the event, so no completion can be waited for at all"),
    ("public boolean awaitAll()", "the ring cannot be waited for, so a readback or a teardown has no point at "
                                  "which the GPU is known to be finished"),
    ("public void close()", "the ring has no release, so its allocators, command buffer and event leak"),
    ("MTL4CommandAllocator.h", "the header the rule comes from is no longer named where the rule is implemented"),
):
    if needle not in ring_source:
        raise SystemExit("cold-probe harness: " + why)
# Section 106's rule, as a property of the file: the frame's lifetime is device-owned, and a static native
# handle would be a second lifetime reaching across sessions. The check is on fields - a declaration that ends
# in `=` or `;` - so the factory that returns a ring is not mistaken for one. What may be static is the
# selector cache: a `Msg` holds a selector and a method handle, not a device's object.
if re.search(r"static\s+(?:final\s+)?(?:MemorySegment|MTL4FrameRing|MTL4ArgumentTable|MTLBuffer)\s+\w+\s*(?:=|;)",
             ring_source):
    raise SystemExit("cold-probe harness: the ring holds native state in a static, so a device teardown, a "
                     "reload or a second device could reach another session's allocators - which is what the "
                     "migration's section 106 forbids the production path to do")

ring_probe = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
              / "MTL4Probe.java").read_text(encoding="utf-8")
for needle, why in (
    ("public static boolean canReuseAllocatorSlots(",
     "the allocator-slot rule is measured nowhere, so the frame's ring would be built on a contract no run has "
     "answered"),
    ("MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT",
     "the proof does not use the ring's own frame depth, so it would be measuring some other lifetime"),
    ("ring.waits() != expectedWaits",
     "the proof does not check that the ring waited for an in-flight slot, so a ring that never waited would "
     "pass on whatever the pixels happened to hold"),
    ("ring.awaitAll()", "the proof reads its targets without waiting for the ring's submissions"),
    ("so a submission on a reused allocator",
     "a frame whose pixel is wrong on a reused slot is not reported as that, so the readback stops naming the "
     "fault"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

# And the harness's half: reported, and counted apart from the capability sequence.
for needle, why in (
    ('+ " ring=" + ring', "the harness does not print the allocator-slot answer, so a run of it leaves no "
                          "evidence"),
    ('+ " ringReason=" + ringReason', "the harness prints whether the ring passed and not why it failed"),
    ("MTL4Probe.canReuseAllocatorSlots(device)", "the harness never asks the allocator-slot proof"),
    ("ring_failures=\"$(grep -c ' ring=false ' \"$probe_log\" || true)\"",
     "the driver does not count the ring's failures, so a run cannot say how many there were"),
    ("if (( ring_failures > 0 )); then",
     "the driver counts the ring's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- several colour attachments, each with its own load, store and clear ---------------------------------
# The render pass is where an attachment's two lifetime facts become load and store actions, so it is the one
# place a mapping mistake is a wrong image rather than a slow frame. The smoke proves the mapping on the device
# by reading every slot back against the colour that slot was asked for, and by loading a slot a second time.
render_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4RenderEncoder.java")
if not render_encoder.is_file():
    raise SystemExit("cold-probe harness: MTL4RenderEncoder.java is gone, so the frame's render passes have no"
                     " implementation and the attachment mapping has nowhere to live")
render_encoder_source = render_encoder.read_text(encoding="utf-8")
for needle, why in (
    ("COLOR_ATTACHMENTS.sendPtr(descriptor)", "the pass descriptor's colour attachments are never reached"),
    ("ATTACHMENT_AT.sendPtr(attachments, index)",
     "only one attachment is ever described, so a second colour target has nowhere to go"),
    ("SET_LOAD_ACTION.send(attachment, loadAction(color.contents(), color.clear() != null));",
     "the load action is not the mapping's answer, so a clear and a load are the same call"),
    ("SET_STORE_ACTION.send(attachment, storeAction(color.contents()));",
     "the store action is not the mapping's answer"),
    ("return contents.overwritten() ? LOAD_DONT_CARE : LOAD_LOAD;",
     "an overwritten attachment no longer skips its load, which is the traffic the fact exists to save"),
    ("return contents.readAfterwards() ? STORE_STORE : STORE_DONT_CARE;",
     "an attachment nothing reads is still stored"),
    ("ObjC.retain(encoder)",
     "the encoder is held past the pool that made it without a retain, which is a dangling handle rather than a "
     "nil check - measured as a segfault in objc_msgSend on the first message to it"),
    ("endEncoding()", "the pass has no end, so a second pass can never be opened in the same command buffer"),
    ("MTL4RenderPass.h", "the header the attachment classes come from is no longer named"),
):
    if needle not in render_encoder_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ("public static boolean canCarryColorAttachments(",
     "the frame's multi-attachment pass is measured nowhere, so the render pass's own half of the MRT smoke is "
     "an assumption"),
    ("MTL4RenderEncoder.Color.cleared(targets[slot], attachmentColor(slot))",
     "the smoke does not describe one attachment per slot, so it cannot say which slot a clear landed in"),
    ("new MTL4RenderEncoder.Color(targets[0], AttachmentContents.CARRIED, null)",
     "the smoke never loads an attachment's existing contents, which is the half of the mapping a clear cannot "
     "prove"),
    ("new AttachmentContents(false, true)", "the discard answers are never sent to the device"),
    ("clearPass.barrierForSubsequentEncoders()",
     "the pass that loads another pass's colour is not ordered against it, which section 61 forbids"),
    ("slot 1 reads ", "a clear on a reused attachment is not compared against the colour it was given"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " attachments=" + attachments', "the harness does not print the attachment smoke's answer"),
    ('+ " attachmentsReason=" + attachmentsReason', "the harness does not print why the attachment smoke failed"),
    ("MTL4Probe.canCarryColorAttachments(device)", "the harness never asks the attachment smoke"),
    ("attachment_failures=\"$(grep -c ' attachments=false ' \"$probe_log\" || true)\"",
     "the driver does not count the attachment smoke's failures"),
    ("if (( attachment_failures > 0 )); then",
     "the driver counts the attachment smoke's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# The compilation chain's own answer, printed by the driver: the pipeline fixture every probe compiles through
# the Metal 4 chain. Not counted as a pass yet - the first device proof of the chain is what this line reports,
# and the round that makes it a counted smoke is the round that has a rate to count.
if 'echo "pipeline compile: $(grep -m1 -o \' compile=[^ ]*\' \"$probe_log\" | cut -c2-)"' not in script:
    raise SystemExit("cold-probe harness: the driver does not print what the compilation chain answered, so a "
                     "run of it leaves the chain's first device proof unread")

# --- a whole layout bound through one table a stage -----------------------------------------------------
# This is the new model's core and the thing that makes a draw possible: there is no per-resource setter, so a
# pass fills a table and assigns it. The pins below are the shape of that - a table per stage, the stride on the
# vertex buffer, the indices the shader declares, the draw's selector, and the two readings that make the smoke
# a measurement rather than a call count.
encoder_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4RenderEncoder.java").read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("setArgumentTable:atStages:", ADDRESS, JAVA_LONG)',
     "the encoder cannot be given a table, so nothing can be bound at all"),
    ('"drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:",',
     "the encoder has no draw, so a pass can bind everything and draw nothing"),
    ('"drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:",',
     "the encoder has no indexed draw, so the engine's indexed geometry has nowhere to go"),
):
    if needle is not None and needle not in encoder_source:
        raise SystemExit("cold-probe harness: " + why)
# The index buffer is an ADDRESS on this model, not a bound object: that is the whole difference from Metal 3's
# indexed draw and the thing a later port of the engine's draws has to know.
if "MemorySegment.ofAddress(indexBufferAddress)" not in encoder_source:
    raise SystemExit("cold-probe harness: the indexed draw no longer passes the index buffer as an address, so "
                     "the selector's indexBuffer argument is something else than the header declares")

for needle, why in (
    ("public static boolean canBindALayout(",
     "the layout binding is measured nowhere, so the new model's core has no run behind it"),
    # Pinned with its assignment and with the plan as the source of the sizes: the same factory call appears in
    # canBindAndDraw's own table, and a table sized from literals would stop covering the slots it is given
    # without the smoke noticing.
    ("vertexTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.VERTEX),",
     "the smoke does not make a vertex table sized from the plan, so what it proves is not the plan's mapping"),
    ("fragmentTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.FRAGMENT),",
     "the smoke does not make a fragment table sized from the plan"),
    ("vertexTable.address(vertices.gpuAddress(), 16L, plan.firstVertexBufferSlot())",
     "the vertex buffer is bound without its attribute stride, or outside the plan's vertex region, so an indexed"
     " vertex read has no layout"),
    ("layoutPass.setArgumentTable(vertexTable, STAGE_VERTEX)",
     "the vertex table is never assigned to the stage that reads it"),
    ("layoutPass.setArgumentTable(fragmentTable, STAGE_FRAGMENT)",
     "the fragment table is never assigned to the stage that reads it"),
    ("layoutPass.setScissorRect(0L, 0L, TARGET_SIZE / 2L, TARGET_SIZE)",
     "the scissor is not set, so the outside-the-rectangle reading has nothing to disagree with"),
    ("the pixel outside the scissor rectangle reads ",
     "a scissor that was accepted and ignored would not be reported as that: the reading outside the rectangle "
     "is what makes the scissor a measurement"),
    ("expected to the bindings and not to a rounding question" if False else "0.25 + 0.5 is 0.75",
     "the smoke's colours are no longer explained as exact sums, which is what keeps its expected pixel a "
     "reading of the bindings and not of rounding"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " layout=" + layout', "the harness does not print the layout smoke's answer"),
    ('+ " layoutReason=" + layoutReason', "the harness does not print why the layout smoke failed"),
    ("MTL4Probe.canBindALayout(device)", "the harness never asks the layout smoke"),
    ("layout_failures=\"$(grep -c ' layout=false ' \"$probe_log\" || true)\"",
     "the driver does not count the layout smoke's failures"),
    ("if (( layout_failures > 0 )); then",
     "the driver counts the layout smoke's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

print("Metal 4 cold-probe harness contract: PASS")
