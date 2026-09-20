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
    ("if (color == null || ObjC.isNil(color.texture())) {",
     "a colour slot the caller did not fill is not recognised as unused, so the loop dereferences a null Color "
     "- measured: this was a NullPointerException that killed the whole frame on Vitrail's MRT fixture, whose "
     "coverage path hands the backend unused slots before the attachment it does write"),
    ("                    continue;\n                }\n                MemorySegment attachment = ATTACHMENT_AT",
     "an unused colour slot is not left empty at its own index, so the attachments that are there would move to "
     "other slots' numbers"),
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
    # The drawn half of the MRT smoke, counted apart from the pass half because the two fail independently.
    ('+ " multiTarget=" + multiTarget', "the harness does not print the multi-target draw smoke's answer"),
    ('+ " multiTargetReason=" + multiTargetReason',
     "the harness does not print why the multi-target draw smoke failed"),
    ("MTL4Probe.canDrawMultipleTargets(device)", "the harness never asks the multi-target draw smoke"),
    ("multi_target_failures=\"$(grep -c ' multiTarget=false ' \"$probe_log\" || true)\"",
     "the driver does not count the multi-target draw smoke's failures"),
    ("if (( multi_target_failures > 0 )); then",
     "the driver counts the multi-target draw smoke's failures and does not fail the run on them"),
    # The depth DRAW smoke, counted apart from the depth clear: a pass that carries a depth attachment and
    # clears it says nothing about a compare function or a write.
    ('+ " depthDraw=" + depthDraw', "the harness does not print the depth draw smoke's answer"),
    ('+ " depthDrawReason=" + depthDrawReason', "the harness does not print why the depth draw smoke failed"),
    ("MTL4Probe.canDrawWithDepth(device)", "the harness never asks the depth draw smoke"),
    ("depth_draw_failures=\"$(grep -c ' depthDraw=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth draw smoke's failures"),
    ("if (( depth_draw_failures > 0 )); then",
     "the driver counts the depth draw smoke's failures and does not fail the run on them"),
    # And the sampling half of depth, counted apart from the draw.
    ('+ " depthSample=" + depthSample', "the harness does not print the depth sampling smoke's answer"),
    ('+ " depthSampleReason=" + depthSampleReason',
     "the harness does not print why the depth sampling smoke failed"),
    ("MTL4Probe.canSampleDepth(device)", "the harness never asks the depth sampling smoke"),
    ("depth_sample_failures=\"$(grep -c ' depthSample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth sampling smoke's failures"),
    ("if (( depth_sample_failures > 0 )); then",
     "the driver counts the depth sampling smoke's failures and does not fail the run on them"),
    # And the mip chain, counted on its own.
    ('+ " mipmaps=" + mipmaps', "the harness does not print the mipmap smoke's answer"),
    ('+ " mipmapsReason=" + mipmapsReason', "the harness does not print why the mipmap smoke failed"),
    ("MTL4Probe.canGenerateMipmaps(device)", "the harness never asks the mipmap smoke"),
    ("mipmap_failures=\"$(grep -c ' mipmaps=false ' \"$probe_log\" || true)\"",
     "the driver does not count the mipmap smoke's failures"),
    ("if (( mipmap_failures > 0 )); then",
     "the driver counts the mipmap smoke's failures and does not fail the run on them"),
    # And the dispatch, counted on its own.
    ('+ " compute=" + compute', "the harness does not print the compute smoke's answer"),
    ('+ " computeReason=" + computeReason', "the harness does not print why the compute smoke failed"),
    ("MTL4Probe.canDispatchCompute(device)", "the harness never asks the compute smoke"),
    ("compute_failures=\"$(grep -c ' compute=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute smoke's failures"),
    ("if (( compute_failures > 0 )); then",
     "the driver counts the compute smoke's failures and does not fail the run on them"),
    # And a kernel writing a texture, counted on its own.
    ('+ " storageImage=" + storageImage', "the harness does not print the storage-image smoke's answer"),
    ('+ " storageImageReason=" + storageImageReason',
     "the harness does not print why the storage-image smoke failed"),
    ("MTL4Probe.canWriteStorageImage(device)", "the harness never asks the storage-image smoke"),
    ("storage_image_failures=\"$(grep -c ' storageImage=false ' \"$probe_log\" || true)\"",
     "the driver does not count the storage-image smoke's failures"),
    ("if (( storage_image_failures > 0 )); then",
     "the driver counts the storage-image smoke's failures and does not fail the run on them"),
    # And the two cross-encoder dependencies, each counted on its own: a dispatch and a copy that both work say
    # nothing about whether a later encoder of another kind can see what the dispatch wrote.
    ('+ " computeSample=" + computeSample', "the harness does not print the compute-to-pass smoke's answer"),
    ('+ " computeSampleReason=" + computeSampleReason',
     "the harness does not print why the compute-to-pass smoke failed"),
    ("MTL4Probe.canSampleComputeOutput(device)", "the harness never asks the compute-to-pass smoke"),
    ("compute_sample_failures=\"$(grep -c ' computeSample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-pass smoke's failures"),
    ("if (( compute_sample_failures > 0 )); then",
     "the driver counts the compute-to-pass smoke's failures and does not fail the run on them"),
    ('+ " computeVertex=" + computeVertex', "the harness does not print the compute-to-draw smoke's answer"),
    ('+ " computeVertexReason=" + computeVertexReason',
     "the harness does not print why the compute-to-draw smoke failed"),
    ("MTL4Probe.canDrawFromComputeWrittenBuffer(device)", "the harness never asks the compute-to-draw smoke"),
    ("compute_vertex_failures=\"$(grep -c ' computeVertex=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-draw smoke's failures"),
    ("if (( compute_vertex_failures > 0 )); then",
     "the driver counts the compute-to-draw smoke's failures and does not fail the run on them"),
    # The three dependency smokes wired after that one: the copy's two boundaries and the two producers a
    # dispatch reads. Each needs its field, its invocation and a counted failure, or a run that fails one would
    # print it and exit zero.
    ('+ " copySample=" + copySample', "the harness does not print the copy-to-pass smoke's answer"),
    ('+ " copySampleReason=" + copySampleReason',
     "the harness does not print why the copy-to-pass smoke failed"),
    ("MTL4Probe.canSampleAfterCopy(device)", "the harness never asks the copy-to-pass smoke"),
    ("copy_sample_failures=\"$(grep -c ' copySample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy-to-pass smoke's failures"),
    ("if (( copy_sample_failures > 0 )); then",
     "the driver counts the copy-to-pass smoke's failures and does not fail the run on them"),
    ('+ " copyDispatch=" + copyDispatch', "the harness does not print the copy-to-dispatch smoke's answer"),
    ('+ " copyDispatchReason=" + copyDispatchReason',
     "the harness does not print why the copy-to-dispatch smoke failed"),
    ("MTL4Probe.canDispatchSampledCopy(device)", "the harness never asks the copy-to-dispatch smoke"),
    ("copy_dispatch_failures=\"$(grep -c ' copyDispatch=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy-to-dispatch smoke's failures"),
    ("if (( copy_dispatch_failures > 0 )); then",
     "the driver counts the copy-to-dispatch smoke's failures and does not fail the run on them"),
    ('+ " renderDispatch=" + renderDispatch',
     "the harness does not print the render-to-dispatch smoke's answer"),
    ('+ " renderDispatchReason=" + renderDispatchReason',
     "the harness does not print why the render-to-dispatch smoke failed"),
    ("MTL4Probe.canDispatchSampledRender(device)", "the harness never asks the render-to-dispatch smoke"),
    ("render_dispatch_failures=\"$(grep -c ' renderDispatch=false ' \"$probe_log\" || true)\"",
     "the driver does not count the render-to-dispatch smoke's failures"),
    ("if (( render_dispatch_failures > 0 )); then",
     "the driver counts the render-to-dispatch smoke's failures and does not fail the run on them"),
    # And the chain of two dispatches, which is a different question from either producer above.
    ('+ " computeChain=" + computeChain', "the harness does not print the compute-to-compute smoke's answer"),
    ('+ " computeChainReason=" + computeChainReason',
     "the harness does not print why the compute-to-compute smoke failed"),
    ("MTL4Probe.canDispatchAfterDispatch(device)", "the harness never asks the compute-to-compute smoke"),
    ("compute_chain_failures=\"$(grep -c ' computeChain=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-compute smoke's failures"),
    ("if (( compute_chain_failures > 0 )); then",
     "the driver counts the compute-to-compute smoke's failures and does not fail the run on them"),
    # And the third direction, whose failure is a write that overtook a read.
    ('+ " writeAfterRead=" + writeAfterRead',
     "the harness does not print the write-after-read smoke's answer"),
    ('+ " writeAfterReadReason=" + writeAfterReadReason',
     "the harness does not print why the write-after-read smoke failed"),
    ("MTL4Probe.canWriteAfterRead(device)", "the harness never asks the write-after-read smoke"),
    ("write_after_read_failures=\"$(grep -c ' writeAfterRead=false ' \"$probe_log\" || true)\"",
     "the driver does not count the write-after-read smoke's failures"),
    ("if (( write_after_read_failures > 0 )); then",
     "the driver counts the write-after-read smoke's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the drawn half of MRT, where the probe's own contract is the readback -------------------------------
# The pass half describes four attachments and reads them back slot by slot after four clears. What it cannot
# say is whether one draw's four fragment outputs are routed to the four slots the pass describes: a pipeline
# that carried the stage as one output, and a slot order that is permuted, both pass the clear smoke. So the
# drawn smoke is pinned on the three things that make it a measurement rather than a call count - four formats
# on the pipeline, one draw, and an exact per-slot comparison of both corners.
engine_probe = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "MTL4Probe.java")
if not engine_probe.is_file():
    raise SystemExit("cold-probe harness: MTL4Probe.java is gone, so the smoke the harness prints an answer for "
                     "does not exist")
engine_probe_source = engine_probe.read_text(encoding="utf-8")
if "public static boolean canDrawMultipleTargets(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the multi-target draw smoke is gone, so the harness's multiTarget field "
                     "would report a call that is not there")
mrt_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawMultipleTargets("):]
mrt_probe = mrt_probe[:mrt_probe.index("private static float[] mrtClearColor()")]
for needle, why in (
    ("MTLBuiltinPipelines.buildPipelineForProbe(MULTI_TARGET_MSL, \"metallum_mrt_probe_vs\",",
     "the multi-target smoke no longer builds its pipeline from the four-output MSL"),
    ("\"metallum_mrt_probe_fs\", formats)",
     "the multi-target smoke builds a pipeline with something other than one format per slot"),
    ("long[] formats = new long[slots];", "the pipeline is given no format a slot"),
    ("BEGIN.send(buffer, allocator);",
     "the multi-target smoke never begins its command buffer, and a render encoder created on a buffer that "
     "was not begun is a SIGSEGV inside IOGPU's own IOGPUDeviceGetNextGlobalTraceId rather than a refused call "
     "- measured, and it is the fault this smoke was first written with"),
    ("DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L)",
     "the multi-target smoke does not draw the fullscreen triangle, which is the only thing that can put a "
     "value in a slot"),
    ("for (long[] at : new long[][]{{0L, 0L}, {last, last}})",
     "only one pixel a slot is read, so a draw that covered part of a target passes"),
    ("if (!matches(pixel, EXPECTED_MRT_PIXELS[slot]))",
     "the multi-target readback is not compared against the value that slot's fragment output writes"),
):
    if needle not in mrt_probe:
        raise SystemExit("cold-probe harness: " + why)
if "DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L, 1L, 0L)" in mrt_probe:
    raise SystemExit("cold-probe harness: the multi-target smoke draws with the engine encoder's five-argument "
                     "selector, which this probe's drawPrimitives:vertexStart:vertexCount: is not - the extra "
                     "arguments land in registers the selector never reads")
for needle, why in (
    ("MTL4RenderEncoder.Color[] withUnused = {", "the attachment smoke no longer describes an unused slot"),
    ("                    null,\n", "the attachment smoke has no unused slot in the array it describes"),
    ('"the unused-slot pass"', "the attachment smoke's unused-slot pass has no name, so a refusal from it would "
                               "not say which pass"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canDrawWithDepth(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the depth draw smoke is gone, so the harness's depthDraw field would "
                     "report a call that is not there")
depth_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawWithDepth("):]
depth_probe = depth_probe[:depth_probe.index("private static float[] depthClearColor()")]
for needle, why in (
    ("MTLBuiltinPipelines.depthStencilStateForProbe(MTLCompareFunction.Less, true)",
     "the depth smoke no longer asks for a less-than compare with writing enabled, so a depth buffer that "
     "rejected everything or wrote nothing would pass it"),
    ("setDepthStencilState(depthState)",
     "the depth smoke never assigns the depth-stencil state to the encoder, so the compare it asks for is "
     "never applied"),
    ("new MTL4RenderEncoder.Depth(depth, 1.0)", "the depth smoke's pass carries no depth attachment"),
    ("DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L);\n            "
     "DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 3L, 3L);",
     "the depth smoke no longer draws the near triangle before the far one, and the order is what makes the "
     "overlap a test of the compare rather than of the draw order"),
    ("MTLTexture.bytes(target, pixel, 4L, 8L, 32L, 1L, 1L);",
     "the overlap pixel is not the one inside both triangles - the failure this smoke was first written with, "
     "which reported a depth compare that had never been asked to reject anything"),
    ("float overlapDepth = pixel.get(JAVA_FLOAT, 0L);",
     "the depth buffer is not read at the overlap, so a compare that rejected the later draw without writing "
     "the winner would pass"),
    ("float farDepth = pixel.get(JAVA_FLOAT, 0L);",
     "the depth buffer is not read where only the far triangle is, so a pass whose compare rejected everything "
     "would pass"),
    ("MTLPixelFormat.Depth32Float.value)",
     "the depth smoke's pipeline declares no depth format, and a pipeline that declares none has no depth test "
     "to apply whatever state the encoder is given"),
):
    if needle not in depth_probe:
        raise SystemExit("cold-probe harness: " + why)
if "releaseIfPresent(depthState);" in depth_probe:
    raise SystemExit("cold-probe harness: the depth smoke releases the depth-stencil state, which is cached and "
                     "shared with the engine's own clears - measured as a SIGSEGV inside objc_msgSend with the "
                     "selector `release` on the next probe of a warm process, which is the fault only the "
                     "repeated-probe population can see")
if "The depth-stencil state is NOT released" not in depth_probe:
    raise SystemExit("cold-probe harness: the reason the depth-stencil state is not released is not written "
                     "down, so the next reader will release it again")
# And the state itself: the compare and the write decision have to be the caller's, all the way to the
# descriptor. A probe whose state silently wrote nothing would pass a smoke that only reads colour back.
builtin = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "MTLBuiltinPipelines.java")
if not builtin.is_file():
    raise SystemExit("cold-probe harness: MTLBuiltinPipelines.java is gone, so the probe has no built-in "
                     "pipelines and no depth-stencil state factory")
builtin_source = builtin.read_text(encoding="utf-8")
for needle, why in (
    ("return ensureDepthStencilState(compareFunction, writeDepth);",
     "the probe's depth-stencil state factory does not forward the caller's compare and write decision"),
    ("descriptor.depthWriteEnabled(writeDepth);",
     "the depth-stencil state is built without the write decision, so a caller asking for depth writes gets a "
     "state that writes nothing"),
    ("descriptor.depthCompareFunction(compareOp);",
     "the depth-stencil state is built without the caller's compare function"),
):
    if needle not in builtin_source:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canSampleDepth(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the depth sampling smoke is gone, so the harness's depthSample field "
                     "would report a call that is not there")
sample_probe = engine_probe_source[engine_probe_source.index("public static boolean canSampleDepth("):]
sample_probe = sample_probe[:sample_probe.index("private static float[] depthClearColor()")]
for needle, why in (
    ("newSampledDepthTarget(device)",
     "the depth the reader samples is created without the ShaderRead bit, and a texture with only the "
     "render-target bit is refused as a sample source by the driver"),
    ("new MTL4RenderEncoder.Depth(depth, SAMPLE_DEPTH_CLEAR)",
     "the writer does not clear the depth attachment it is about to draw over"),
    ("barrierForSubsequentEncoders()",
     "the whole point of the smoke is a dependency between two passes and no barrier is encoded, so the reader "
     "has nothing ordering it against the writer"),
    ("table = MTL4ArgumentTable.create(device, 0L, 1L, 1L);",
     "the reader has no one-texture, one-sampler table to sample the depth through"),
    ("table.texture(depth)", "the depth texture is never put in the reader's table"),
    ("setArgumentTable(table, STAGE_FRAGMENT)",
     "the reader's table is never assigned to the fragment stage"),
    ("MTLTexture.bytes(depth, pixel, 4L, x, y, 1L, 1L);",
     "the depth buffer's own value is not read, so a failure cannot say what the pass wrote"),
    ("MTLTexture.bytes(readerTarget, pixel, 4L, x, y, 1L, 1L);",
     "the value the reader's shader wrote is not read back, so the smoke is about the buffer and not about "
     "sampling it"),
    ("Math.abs(read - expectedPixel) > 1",
     "the sampled depth is compared with no tolerance at all, which the eight-bit conversion of a float depth "
     "cannot meet - or with a tolerance wide enough to hide the quarter-range difference the smoke looks for"),
    ("releaseIfPresent(sampler);",
     "the sampler the smoke makes is never released, so a session of probes leaks one sampler each time"),
):
    if needle not in sample_probe:
        raise SystemExit("cold-probe harness: " + why)
# Scoped to the helper, because the same two bits are set by another smoke's source texture: a pin that read the
# whole file would be satisfied by that call site while the depth texture lost its readability.
if "private static MemorySegment newSampledDepthTarget(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the shader-readable depth target helper is gone, so the smoke's depth "
                     "texture is whatever the writer's helper makes - which has no ShaderRead bit")
sampled_depth_helper = engine_probe_source[
    engine_probe_source.index("private static MemorySegment newSampledDepthTarget("):]
sampled_depth_helper = sampled_depth_helper[:sampled_depth_helper.index("/**")]
for needle, why in (
    ("descriptor.pixelFormat(MTLPixelFormat.Depth32Float);",
     "the sampled depth target is not a Depth32Float texture"),
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ);",
     "the sampled depth target's usage bits are not both set, so the texture a pass wrote cannot be sampled by "
     "the pass after it"),
):
    if needle not in sampled_depth_helper:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canGenerateMipmaps(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the mipmap smoke is gone, so the harness's mipmaps field would report "
                     "a call that is not there")
mip_probe = engine_probe_source[engine_probe_source.index("public static boolean canGenerateMipmaps("):]
mip_probe = mip_probe[:mip_probe.index("/** The depth smoke's colour clear")]
for needle, why in (
    ("newMipmappedTarget(device)", "the mipmap smoke's texture is not one with a chain to generate"),
    ("resident.add(checker.handle())", "the source buffer is not declared resident before the copy"),
    ("resident.add(mips)", "the destination texture is not declared resident before the copy"),
    ("ADD_RESIDENCY_SET.send(queue, resident.handle());",
     "the residency set is never handed to the queue, so nothing declares what the copy touches"),
    ("resident.close()", "the residency set the smoke makes is never released"),
    ("copies.copyBufferToTexture(checker.handle(), 0L, row, row * TARGET_SIZE, TARGET_SIZE,",
     "level 0 is not filled from the checkerboard, so the chain has nothing to be generated from"),
    ("mips, 0L, 1L, 0L, 0L, 0L)", "level 1 is not pre-filled, so a generation that did nothing would pass"),
    ("mips, 0L, 2L, 0L, 0L, 0L)", "level 2 is not pre-filled, so a generation that did nothing would pass"),
    ("copies.generateMipmaps(mips)",
     "the generation is never asked for, so the smoke would read levels nobody wrote"),
    ("MTLTexture.bytes(mips, pixel, 4L, at / 2L, at / 2L, 1L, 1L, level);",
     "the levels above 0 are not read from their own mip level, so the smoke cannot see a chain at all"),
    ("Math.abs(red - CHECKER_AVERAGE) > 1 || Math.abs(blue - CHECKER_AVERAGE) > 1",
     "a generated level is not compared against the box average of the level below it"),
    ("if (red == MIP_PREFILLED) {",
     "the value the level was pre-filled with is not refused, so a generation that did nothing could pass on a"
     " coincidence"),
    ("MTLTexture.bytes(mips, pixel, 4L, 33L, 32L, 1L, 1L, 0L);",
     "the checkerboard's neighbouring texel is not read, so the two values the average comes from are not both"
     " proven to be there"),
):
    if needle not in mip_probe:
        raise SystemExit("cold-probe harness: " + why)
# The texture's own level count, scoped to its helper: it is the property the smoke exists for.
if "private static MemorySegment newMipmappedTarget(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the mipmapped target helper is gone, so the smoke's texture is one with"
                     " no chain whatever it asks for")
mip_helper = engine_probe_source[engine_probe_source.index("private static MemorySegment newMipmappedTarget("):]
mip_helper = mip_helper[:mip_helper.index("/**")]
if "descriptor.mipmapLevelCount(MIP_LEVELS);" not in mip_helper:
    raise SystemExit("cold-probe harness: the texture the mipmap smoke generates has one level, so there is no"
                     " chain to generate")
# --- the dispatch itself, where the probe's own kernel is the contract ----------------------------------
if "public static boolean canDispatchCompute(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the compute dispatch smoke is gone, so the harness's compute field "
                     "would report a call that is not there")
compute_probe = engine_probe_source[engine_probe_source.index("public static boolean canDispatchCompute("):]
compute_probe = compute_probe[:compute_probe.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ('device.newFunction(COMPUTE_MSL, "metallum_compute_probe")',
     "the dispatch smoke builds no pipeline from the probe's own kernel"),
    ("device.newComputePipelineState(function)",
     "the kernel is never made into a compute pipeline, so there is nothing to dispatch"),
    ("table.address(out.gpuAddress(), 0L)", "the output buffer is not bound by address"),
    ("table.address(bias.gpuAddress(), 1L)", "the uniform the kernel adds is not bound by address"),
    ("resident.add(out.handle())", "the output buffer is not declared resident before the dispatch"),
    ("resident.add(bias.handle())", "the uniform buffer is not declared resident before the dispatch"),
    ("dispatch.setComputePipelineState(pipeline)", "the pipeline is never handed to the encoder"),
    ("dispatch.setArgumentTable(table)", "the table is never handed to the encoder"),
    ("dispatch.dispatchThreadgroups(1L, 1L, 1L, COMPUTE_THREADS, 1L, 1L)",
     "the dispatch is never encoded, so nothing runs"),
    ("outWords.set(JAVA_INT, index * 4L, COMPUTE_SENTINEL);",
     "the output buffer is not pre-filled with a sentinel, so a dispatch that did nothing could pass on"
     " whatever a fresh buffer holds"),
    ("if (read == COMPUTE_SENTINEL) {",
     "the sentinel is not refused afterwards, so the pre-fill proves nothing"),
    ("int expected = (int) (index * 2L) + COMPUTE_BIAS;",
     "each thread's output is not compared against its own index's formula, so a grid of the wrong shape or one"
     " thread's answer repeated could pass"),
):
    if needle not in compute_probe:
        raise SystemExit("cold-probe harness: " + why)
# --- a kernel writing a texture, where a table per dispatch is the mechanism ------------------------------
if "public static boolean canWriteStorageImage(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the storage-image smoke is gone, so the harness's storageImage field "
                     "would report a call that is not there")
storage_probe = engine_probe_source[engine_probe_source.index("public static boolean canWriteStorageImage("):]
storage_probe = storage_probe[:storage_probe.index("private static void writeColor(")]
for needle, why in (
    ("descriptor.usage(USAGE_SHADER_WRITE | USAGE_SHADER_READ);",
     "the storage smoke's texture has no shader-write bit, so the driver refuses it as a storage image"),
    ("table.texture(texture, 0L)", "the image is not bound through the table by resource id"),
    ("table.address(first.gpuAddress(), 0L)", "the first colour is not bound by address"),
    ("secondTable = MTL4ArgumentTable.create(device, 1L, 1L, 0L);",
     "the second dispatch has no table of its own, so the smoke is back on the re-pointed shape whose green is"
     " phase-dependent - measured"),
    ("if (secondTable == null || !secondTable.texture(texture, 0L)\n"
     "                    || !secondTable.address(second.gpuAddress(), 0L)",
     "the second dispatch's table is not given the image by resource id and the second colour by address"),
    ("secondDispatch = MTL4ComputeEncoder.open(device, buffer, \"the storage smoke's second dispatch\");",
     "the second dispatch has no encoder of its own, which is the measured safe shape: a second table handed to"
     " the same encoder is not reliably honoured, and with the copy dependency smoke in the suite the smoke then"
     " failed on alternate warm probes"),
    ("|| !secondDispatch.setComputePipelineState(pipeline)\n"
     "                    || !secondDispatch.setArgumentTable(secondTable)) {",
     "the second dispatch's own encoder is not given the pipeline and its table, so the smoke would measure"
     " nothing"),
    ("secondDispatch.endEncoding();",
     "the second dispatch's encoder is never ended, so its work would not be submitted"),
    ("if (secondDispatch != null) {",
     "the second dispatch's encoder is never released, so every probe leaks one - and releasing one before the"
     " commit is what crashed the driver when that was tried"),
    ("if (secondTable != null) {",
     "the second dispatch's table is never released, so every probe of this smoke leaks one"),
    ("for (long[] at : new long[][]{{0L, 0L}, {STORAGE_EDGE - 1L, STORAGE_EDGE - 1L}, {1L, 3L}})",
     "the readback does not cover the corners and the middle, so a dispatch that wrote one texel could pass"),
    ("if (!matches(pixel, STORAGE_SECOND_PIXEL)) {",
     "the readback is not compared against the colour the second dispatch wrote"),
):
    if needle not in storage_probe:
        raise SystemExit("cold-probe harness: " + why)
# The kernel itself lives above the method, so it is pinned against the file rather than the slice.
for needle, why in (
    ("kernel void metallum_storage_write_probe(texture2d<float, access::write> image [[texture(0)]],",
     "the storage kernel takes no writable image at the texture slot the table binds"),
    ("constant float4& colour [[buffer(0)]]",
     "the storage kernel does not read its colour from a buffer, so the reading cannot say which buffer the table"
     " held"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

# --- the two cross-encoder dependencies, where the API's ordering is what the smoke proves ----------------
# Both are new kinds of question: every smoke above establishes one encoder's own capability, and these two ask
# whether what one encoder wrote is visible to an encoder of another kind in the same command buffer. The
# producer barrier is the answer, so a pin checks it is encoded rather than inferred from "one command buffer".
for smoker, stage, why_gone in (
    ("canSampleComputeOutput", "computeSample",
     "the compute-to-pass dependency smoke is gone, so the harness's computeSample field would report a call"
     " that is not there"),
    ("canDrawFromComputeWrittenBuffer", "computeVertex",
     "the compute-to-draw dependency smoke is gone, so the harness's computeVertex field would report a call"
     " that is not there"),
):
    if "public static boolean " + smoker + "(" not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why_gone)

sample_probe = engine_probe_source[engine_probe_source.index("public static boolean canSampleComputeOutput("):]
sample_probe = sample_probe[:sample_probe.index("public static boolean canDrawFromComputeWrittenBuffer(")]
for needle, why in (
    ("dispatch.barrierForSubsequentEncoders()",
     "the compute-to-pass smoke samples what a dispatch wrote without encoding the producer barrier, so it would"
     " be proving that one command buffer happened to be enough - which section 61 forbids"),
    ("if (!dispatch.barrierForSubsequentEncoders()) {",
     "the producer barrier is sent without asking whether the encoder answers it"),
    ("if (!dispatch.dispatchThreads(STORAGE_EDGE, STORAGE_EDGE, 1L, STORAGE_EDGE, STORAGE_EDGE, 1L)) {",
     "the dispatch into the storage image is not encoded, so the pass has nothing to see"),
    ("descriptor.usage(USAGE_SHADER_WRITE | USAGE_SHADER_READ);",
     "the image both encoders touch does not declare both usages, so one of them would be refused"),
    ("!sampledTable.texture(image, 0L)", "the image is not bound to the pass's table by resource id"),
    ("!sampledTable.sampler(sampler, 0L)", "the sampler is not bound to the pass's table"),
    ("MTLTexture.bytes(image, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the dispatch's own output is not read back, so a kernel that never wrote and a sample that never arrived"
     " would be one failure"),
    ("if (!matches(pixel, COMPUTE_IMAGE_PIXEL)) {",
     "the image is not compared against the colour the dispatch wrote"),
    ("if (matches(pixel, CLEAR_PIXEL)) {",
     "a target holding the pass's clear colour is not named as the dependency failure it is, so an unordered"
     " sample would read as a wrong colour"),
    ("for (long[] at : new long[][]{{0L, 0L}, {TARGET_SIZE - 1L, TARGET_SIZE - 1L}, {17L, 41L}})",
     "the target is read at one place only, so a sample that landed in one corner could pass"),
):
    if needle not in sample_probe:
        raise SystemExit("cold-probe harness: " + why)

vertex_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawFromComputeWrittenBuffer("):]
vertex_probe = vertex_probe[:vertex_probe.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("sentinel.set(JAVA_FLOAT, word * 4L, 0.0f);",
     "the vertex buffer is not pre-filled with a degenerate triangle, so a draw that ran before the dispatch's"
     " data arrived could still paint pixels"),
    ("dispatch.barrierForSubsequentEncoders()",
     "the compute-to-draw smoke draws what a dispatch wrote without encoding the producer barrier"),
    ("if (!dispatch.dispatchThreadgroups(1L, 1L, 1L, COMPUTE_THREADS, 1L, 1L)) {",
     "the dispatch that fills the vertex buffer is not encoded"),
    ("|| !computeTable.address(vertices.gpuAddress(), 0L)",
     "the same buffer is not bound to the dispatch's table by address"),
    ("|| !vertexTable.address(vertices.gpuAddress(), 16L, 0L)) {",
     "the same buffer is not bound to the draw's table as vertex data with its stride, so the draw could not"
     " read what the dispatch wrote"),
    ("pass.setArgumentTable(vertexTable, STAGE_VERTEX)",
     "the vertex table is not handed to the drawing pass"),
    ("float firstX = written.get(JAVA_FLOAT, 0L);",
     "the buffer is not read back on the CPU, so a dispatch that never wrote and a draw that never read would"
     " be one failure"),
    ("if (!matches(pixel, EXPECTED_VERTEX_PIXEL)) {",
     "the drawn pixel is not compared against the colour that comes out of the buffer's own components"),
):
    if needle not in vertex_probe:
        raise SystemExit("cold-probe harness: " + why)
# The kernel that fills the buffer, pinned against the file: it writes the same three corners the vertex smoke's
# own literal uses, so the colour the draw passes through is read from the buffer and not from the shader.
for needle, why in (
    ("kernel void metallum_vertex_write_probe(device float4* vertices [[buffer(0)]],",
     "the vertex-writing kernel takes no device buffer at the slot the table binds"),
    ("vertices[id] = float4(corners[id], 0.25, 0.5);",
     "the kernel does not write the colour the vertex stage carries through, so a pixel could not say the draw"
     " read this buffer"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

# --- the reproducer, which is a mode of this harness and a laboratory rather than a smoke -----------------
# Round 41's fault - a later dispatch through a table reading the first dispatch's colour after a texture copy -
# has a deterministic reproducer: round 41 measured it in the suite, and this artifact is what keeps it
# runnable without the suite. It is compiled against the same classpath and run by the same script, so it
# cannot measure another branch's classes and needs no second build path.
for needle, why in (
    ("--repro) repro_rounds=\"$2\"; shift 2 ;;", "the harness has no reproducer mode"),
    ("--variant) variant=\"$2\"; shift 2 ;;", "the harness cannot select a variant of the reproducer"),
    ("CopyThenDispatchRepro.java", "the reproducer is not compiled, so the mode would run nothing"),
    ("CopyThenDispatchRepro \"$repro_rounds\" \"$variant\"",
     "the reproducer is run without its rounds or its variant, so a run could not say which shape it asked"),
    ("variant $variant", "the harness does not say which variant it ran"),
    ("if grep -q 'storageFailures=0 ' \"$repro_out\"; then",
     "the reproducer's answer is not read, so a run's exit code could not say whether it reproduced"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

REPRO = ROOT / "tools" / "metal4-cold-probe" / "CopyThenDispatchRepro.java"
if not REPRO.is_file():
    raise SystemExit("cold-probe harness: the copy-then-dispatch reproducer is gone, so the fault it made "
                     "deterministic has no artifact again")
repro = REPRO.read_text(encoding="utf-8")
for needle, why in (
    ("boolean storage = MTL4Probe.canWriteStorageImage(device);",
     "the reproducer does not run the victim smoke, so it is not reproducing the measured fault"),
    ("boolean storageAgain = MTL4Probe.canWriteStorageImage(device);",
     "the reproducer does not run the victim twice, so a state a second call clears cannot be told from one "
     "that persists"),
    ("String copyReason = trigger(device, shape);",
     "the reproducer never runs the trigger, so every variant would be clean and mean nothing"),
    ("copy.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, HALF, HALF, 1L,\n"
     "                                        into, 0L, 0L, HALF, 0L, 0L);",
     "the trigger's texture-to-texture region copy is gone, and that copy is what every variant measures"),
    ("case \"no-copy\" ->", "the variant that removes the copy command is gone, so the one control that "
     "separates the copy from its surroundings cannot be run"),
    ("case \"buffer-copy\" ->", "the variant that copies buffers instead of textures is gone, so nothing "
     "separates a texture copy from a copy of any kind"),
    ("case \"separate-commit\" ->", "the variant that gives the copy its own command buffer is gone, so "
     "\"one command buffer\" cannot be ruled out"),
    ("case \"copy-to-unbound\" ->", "the variant whose copy target no table names is gone, so the copy's "
     "destination being a bound resource cannot be ruled out"),
    ("case \"no-residency\" ->", "the variant that declares nothing is gone, so residency cannot be ruled out"),
    ("case \"textures-released-last\" ->", "the variant that hands the textures back after the command buffer "
     "is gone, so a release-order fault cannot be ruled out"),
    ("case \"plain-destination\" ->", "the variant whose textures are not render targets is gone, so the usage "
     "bits cannot be ruled out"),
    ("M4_REPRO SUMMARY variant=", "the reproducer prints no summary, so a shell cannot read its answer"),
):
    if needle not in repro:
        raise SystemExit("cold-probe harness: " + why)
# The two release orders have to be different code, or the variant is a comment.
release_orders = repro.split("if (shape.texturesReleasedLast()) {")
if len(release_orders) != 2 or release_orders[1].index("release(source);") > \
        release_orders[1].index("} else {"):
    raise SystemExit("cold-probe harness: the reproducer's two release orders are the same code, so the "
                     "variant that reorders them measures nothing")

# The own victim and its modes: the mechanism this artifact exists to measure is "one table object re-pointed
# and handed to the same encoder twice", so a pin checks the victim can be asked in that shape and in the two
# shapes that are safe, or the measured answer would be unfalsifiable.
for needle, why in (
    ("private static String ownVictim(final MTLDevice device, final String ownMode)",
     "the reproducer has no victim of its own, so the phase sensitivity it exposed cannot be measured apart "
     "from the probe's smoke"),
    ("if (ownMode.equals(\"one-encoder\")) {",
     "the unsafe shape - one encoder, one table re-pointed - cannot be asked for"),
    ("} else if (ownMode.equals(\"fresh-table\")) {",
     "the fresh-table control is gone, so the workaround this round measured has no experiment"),
    ("if (ownMode.equals(\"two-commits\") && index == 1) {",
     "the commit-per-dispatch control is gone"),
    ("private static boolean repoint(final MTL4ComputeEncoder dispatch, final MTL4ArgumentTable table,",
     "the re-point is not a step of its own, so the fault's shape is not expressible"),
    ("long signalled = 0L;",
     "the own victim signals one event value for two commits, so its second wait returns immediately and its "
     "readback is a race rather than a measurement"),
    ("if (matches(seen, OWN_COLOURS[0])) {",
     "the own victim does not say which colour survived, so a stale binding and a dropped command read alike"),
):
    if needle not in repro:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ("--own) own_mode=\"$2\"; shift 2 ;;", "the harness cannot select the own victim's mode"),
    ("CopyThenDispatchRepro \"$repro_rounds\" \"$variant\" \"$own_mode\"",
     "the own victim's mode does not reach the reproducer"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the dependency smokes wired after the compute ones: the copy's boundaries and the read side ------------
# `canSampleAfterCopy` (a pass, a copy, a pass that samples), `canDispatchSampledCopy` and
# `canDispatchSampledRender` (a dispatch that samples what a pass or a copy wrote) were wired into the harness
# before they had pins. What is pinned here is what makes each of them a measurement: the barriers at every
# boundary, the readbacks that separate "never wrote" from "never read", and - for the two dispatch smokes - the
# safe shape the storage smoke measured, a table AND an encoder for the dispatch itself.
for smoker, why in (
    ("canSampleAfterCopy", "the copy-to-pass smoke is gone, so its harness field would report a call that is not"
     " there"),
    ("canDispatchSampledCopy", "the copy-to-dispatch smoke is gone"),
    ("canDispatchSampledRender", "the render-to-dispatch smoke is gone"),
):
    if "public static boolean " + smoker + "(" not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

copy_boundaries = engine_probe_source[engine_probe_source.index("public static boolean canSampleAfterCopy("):]
copy_boundaries = copy_boundaries[:copy_boundaries.index("private static float[] colorOf(")]
for needle, why in (
    ("copy.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, COPY_HALF, COPY_HALF, 1L,\n"
     "                    destination, 0L, 0L, COPY_HALF, 0L, 0L)",
     "the copy smoke does not encode the region it reads back"),
    ("if (!copy.barrierForSubsequentEncoders()) {",
     "the copy smoke's copy does not barrier before the pass that samples its output"),
    ("MTLTexture.bytes(destination, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the copy smoke does not read the destination's untouched half, so a copy that overwrote everything would"
     " pass"),
    ("MTLTexture.bytes(target, pixel, 4L, COPY_HALF + 8L, 8L, 1L, 1L);",
     "the copy smoke never reads the copied half through the sampler, which is the dependency it exists for"),
):
    if needle not in copy_boundaries:
        raise SystemExit("cold-probe harness: " + why)

sampled = engine_probe_source[engine_probe_source.index("private static boolean sampledProducer("):]
sampled = sampled[:sampled.index("/** How many levels the mipmap smoke asks for")]
# The kernel lives above the method, so it is pinned against the file rather than the slice.
for needle, why in (
    ("kernel void metallum_sampling_probe(texture2d<float, access::sample> source [[texture(0)]],",
     "the sampling kernel does not take the texture it reads at the slot the table binds"),
    ("sampler nearest [[sampler(0)]],", "the sampling kernel has no sampler, so it cannot sample"),
    ("device float4* out [[buffer(0)]],", "the sampling kernel writes nowhere the smoke can read back"),
    ("source.sample(", "the kernel does not sample, so the smoke measures no read at all"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ("resident.add(out.handle())", "the dispatch's output buffer is not declared resident, and an undeclared"
     " resource makes a dispatch do nothing at all - measured"),
    ("|| !table.address(out.gpuAddress(), 0L)) {",
     "the output buffer is not bound to the dispatch's table by address"),
    ("if (!pass.barrierForSubsequentEncoders()) {",
     "the producer pass does not barrier before the encoder that reads its output"),
    ("dispatch = MTL4ComputeEncoder.open(device, buffer, \"the \" + stage + \" smoke's dispatch\");",
     "the sampling dispatch has no encoder of its own, which is the measured safe shape"),
    ("if (!dispatch.barrierForSubsequentEncoders()) {",
     "the dispatch's encoder does not barrier, so whatever encoder follows it has no encoded dependency"),
    ("words.set(JAVA_FLOAT, slot * 16L + channel * 4L, SAMPLING_SENTINEL);",
     "the output buffer is not pre-filled with a sentinel, so a dispatch that never ran could pass on whatever"
     " a fresh buffer holds"),
    ("still holds the sentinel it was", "the sentinel is not refused afterwards, so the pre-fill proves nothing"),
    ("MemorySegment written = out.contents().reinterpret(SAMPLING_SLOTS * 16L);\n"
     "            for (long slot = 0; slot < SAMPLING_SLOTS; slot++) {",
     "the readback does not cover every sample the dispatch wrote - and the needle carries the line above it,"
     " because the pre-fill loop is the same text and would satisfy a bare one"),
    ("if (!matches(seen, COPY_SOURCE_PIXEL)) {",
     "the samples are not compared against the colour the producer wrote, so a wrong read could pass"),
):
    if needle not in sampled:
        raise SystemExit("cold-probe harness: " + why)
if "return sampledProducer(device, true, \"copyDispatch\");" not in engine_probe_source \
        or "return sampledProducer(device, false, \"renderDispatch\");" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the two producer-to-dispatch smokes no longer differ in their producer,"
                     " so one of section 60's cases is measured twice and the other not at all")

# --- the chain of two dispatches, which is the shape a pack's own compute chain is made of -------------------
if "public static boolean canDispatchAfterDispatch(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the compute-to-compute smoke is gone, so the harness's computeChain "
                     "field would report a call that is not there")
chain = engine_probe_source[engine_probe_source.index("public static boolean canDispatchAfterDispatch("):]
chain = chain[:chain.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("writerFunction = device.newFunction(STORAGE_WRITE_MSL, \"metallum_storage_write_probe\");",
     "the writing dispatch does not use the storage-write kernel, so nothing writes the image"),
    ("readerFunction = device.newFunction(SAMPLING_DISPATCH_MSL, \"metallum_sampling_probe\");",
     "the reading dispatch does not sample, so the chain measures no read"),
    ("!writerTable.address(colour.gpuAddress(), 0L) || !writerTable.texture(image, 0L)",
     "the writer's table is not given the colour and the image"),
    ("|| !readerTable.address(out.gpuAddress(), 0L) || !readerTable.texture(image, 0L)",
     "the reader's table is not given its output buffer and the same image"),
    ("|| !resident.add(out.handle())", "the reader's output buffer is not declared resident"),
    ("writer = MTL4ComputeEncoder.open(device, buffer, \"the compute chain's writer\");",
     "the writing dispatch has no encoder of its own"),
    ("reader = MTL4ComputeEncoder.open(device, buffer, \"the compute chain's reader\");",
     "the reading dispatch has no encoder of its own, so the two share one - the shape that loses a dispatch"),
    ("if (!writer.barrierForSubsequentEncoders()) {",
     "the writer does not barrier, so the reader has no encoded dependency on it"),
    ("if (!reader.barrierForSubsequentEncoders()) {",
     "the reader does not barrier before whatever follows the chain"),
    ("if (!matches(seen, COPY_SOURCE_PIXEL)) {",
     "the samples are not compared against the colour the other dispatch wrote"),
    ('" still holds the"', "the sentinel is not refused, so a chain that never ran could pass"),
):
    if needle not in chain:
        raise SystemExit("cold-probe harness: " + why)

# --- write-after-read, the direction whose failure is a write that overtook a read --------------------------
if "public static boolean canWriteAfterRead(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the write-after-read smoke is gone, so the harness's writeAfterRead "
                     "field would report a call that is not there")
war = engine_probe_source[engine_probe_source.index("public static boolean canWriteAfterRead("):]
war = war[:war.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ | USAGE_SHADER_WRITE);",
     "the texture the reader samples and the writer writes does not declare all three usages, so one of the two"
     " would be refused"),
    ("|| !sampledTable.texture(texture, 0L) || !sampledTable.sampler(sampler, 0L)",
     "the reader's table is not given the texture and its sampler"),
    ("|| !writerTable.address(colour.gpuAddress(), 0L) || !writerTable.texture(texture, 0L)) {",
     "the writer's table is not given the colour and the same texture"),
    ("if (!pass.barrierForSubsequentEncoders()) {\n                    END.send(buffer);\n"
     "                    return failed(\"writeAfterRead\", \"the reader does not answer the producer barrier",
     "the reader does not barrier, so the write after it has no encoded dependency on the read"),
    ('writer = MTL4ComputeEncoder.open(device, buffer, "the write-after-read smoke\'s writer");',
     "the writing dispatch has no encoder of its own"),
    ("if (matches(pixel, WAR_WRITE_PIXEL)) {",
     "the reader's target is not checked against the colour the later write put in, which is the ordering failure"
     " this fixture exists for"),
    ("so the write was ordered before", "the ordering failure is not named as itself"),
    ("if (!matches(pixel, WAR_READ_PIXEL)) {",
     "the reader's target is not compared against what the texture held before the write"),
    ("if (!matches(pixel, WAR_WRITE_PIXEL)) {\n                    return failed(\"writeAfterRead\", \"the texture reads ",
     "the texture is not read back, so a write that never landed would pass"),
):
    if needle not in war:
        raise SystemExit("cold-probe harness: " + why)

# And the native calls themselves, where the commands live.
compute_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                   / "MTL4ComputeEncoder.java")
if not compute_encoder.is_file():
    raise SystemExit("cold-probe harness: MTL4ComputeEncoder.java is gone, so a mip chain has no command to be"
                     " generated by")
compute_source = compute_encoder.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("generateMipmapsForTexture:", ADDRESS)',
     "the mip generation selector is not the one this SDK's MTL4ComputeCommandEncoder.h:543 declares"),
    ("if (open == null || ObjC.isNil(texture) || !responds(open, GENERATE_MIPMAPS.name())) {",
     "the generation is sent without asking whether the encoder answers it, so an encoder that does not would"
     " take the command and do nothing"),
    # The dispatch's three calls and their selectors, read off MTL4ComputeCommandEncoder.h.
    ('Msg.ofVoid("setComputePipelineState:", ADDRESS)',
     "the compute pipeline selector is not the one MTL4ComputeCommandEncoder.h:51 declares"),
    ('Msg.ofVoid("setArgumentTable:", ADDRESS)',
     "the compute argument table selector is not the one MTL4ComputeCommandEncoder.h:661 declares - and it takes"
     " no stage mask, because a dispatch has one stage"),
    ('Msg.ofVoid("dispatchThreadgroups:threadsPerThreadgroup:", ADDRESS, ADDRESS)',
     "the dispatch selector is not the one MTL4ComputeCommandEncoder.h:87 declares"),
    ("MTLSize.on(stack, groupsX, groupsY, groupsZ)",
     "the workgroup counts are not passed as an MTLSize, which is how the header declares them"),
    ("MTLSize.on(stack, localX, localY, localZ)",
     "the threads-per-threadgroup counts are not passed as an MTLSize"),
    ("if (open == null || groupsX <= 0L || groupsY <= 0L || groupsZ <= 0L",
     "a dispatch with an empty grid is sent rather than refused"),
    ("if (!responds(open, DISPATCH_THREADGROUPS.name())) {",
     "the dispatch is sent without asking whether the encoder answers it"),
    ('Msg.ofVoid("dispatchThreads:threadsPerThreadgroup:", ADDRESS, ADDRESS)',
     "the open-grid dispatch selector is not the one MTL4ComputeCommandEncoder.h:77 declares, and a texture clear"
     " whose extent is not a multiple of its threadgroup needs that form"),
    ("if (!responds(open, DISPATCH_THREADS.name())) {",
     "the open-grid dispatch is sent without asking whether the encoder answers it"),
):
    if needle not in compute_source:
        raise SystemExit("cold-probe harness: " + why)
if "EXPECTED_MRT_PIXELS = {" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the multi-target smoke has no table of the values its slots are "
                     "compared against, so the readback is a claim about nothing")
if "float4 slot3 [[color(3)]]" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the four-output fragment stage no longer declares a fourth color(n) "
                     "output, so the smoke cannot tell four targets from one")
if "SET_RENDER_PIPELINE_STATE.send(pass.encoder(), pipeline);" not in mrt_probe:
    raise SystemExit("cold-probe harness: the four-output pipeline is never assigned to the pass's encoder, so "
                     "the draw would run the previous pipeline")

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
    ('"drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:"',
     "the encoder has no indexed draw, so the engine's indexed geometry has nowhere to go"),
    ('                    + "baseInstance:",',
     "the indexed draw's selector is one argument short of the eight this SDK declares, so respondsToSelector: "
     "answers no and every indexed draw refuses - the fault a forced Metal 4 client stopped on"),
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

# --- the copy path, which is where this command model puts its blits ------------------------------------
# Metal 4 has no blit encoder: a copy is a compute encoder command, so the smoke and the wrapper are the only
# path a texture upload, download or region copy can take. The pins cover the selectors, the region's four
# coordinates, and the two readings that make the smoke a measurement.
compute_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4ComputeEncoder.java").read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("computeCommandEncoder", ADDRESS)',
     "the copies are not made on the command model's compute encoder, which is where they live"),
    ('"copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:"',
     "the region copy selector is gone, so a subregion copy has no command"),
    ('"copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:"',
     "the texture-to-buffer selector is gone, so the engine cannot read a texture back"),
    ('"copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:"',
     "the buffer-to-texture selector is gone, so the engine cannot upload one"),
    # The three structs are pinned with the send they belong to, because the same helpers build the origins and
    # sizes of the texture-to-buffer copy too - a bare pin would be satisfied by that call while the region copy
    # stopped passing the coordinates it was given.
    ("COPY_TEXTURE_REGION_TO_TEXTURE.send(open, source, sourceSlice, sourceLevel, origin, size, destination,\n"
     "                    destinationSlice, destinationLevel, destinationOrigin);",
     "the region copy does not send the coordinates it was given"),
    ("MemorySegment origin = MTLOrigin.on(stack, sourceX, sourceY, sourceZ);\n"
     "            MemorySegment size = MTLSize.on(stack, width, height, depth);\n"
     "            MemorySegment destinationOrigin = MTLOrigin.on(stack, destinationX, destinationY, destinationZ);",
     "the region's source origin, its size or its destination origin is not passed as the header's structs - the "
     "three together, because each helper also builds another copy's struct and a bare pin would be satisfied "
     "there"),
    ("ObjC.retain(encoder)", "the encoder is held past its autorelease pool without a retain"),
    ("barrierForSubsequentEncoders()", "a copy that reads what a pass wrote has no way to say so"),
):
    if needle not in compute_source:
        raise SystemExit("cold-probe harness: " + why)
# The declaration and the call have to agree: a selector declared with one argument too many makes the handle
# throw on invocation, which reads as "objc_msgSend failed" rather than as a nil - measured while writing this.
if 'Msg.ofVoid("copyFromTexture:toTexture:", ADDRESS, ADDRESS, ADDRESS)' in compute_source:
    raise SystemExit("cold-probe harness: the whole-texture copy selector is declared with three arguments where "
                     "the header has two, so the handle is invoked with the wrong arity")

for needle, why in (
    ("public static boolean canCopyTextureRegions(",
     "the copy path is measured nowhere, so the only route a texture upload can take has no run behind it"),
    ("copies.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, PATTERN_EDGE, PATTERN_EDGE, 1L,",
     "the smoke does not copy a subregion from a non-zero-sized source, so the four coordinates a region copy "
     "can be wrong about are not exercised"),
    ("copies.copyTextureToTexture(source, wholeTarget)", "the smoke does not make a whole-texture copy"),
    ("the region copy also wrote ", "a copy that wrote outside its region is not reported as that"),
    ("the whole-texture copy reads ", "a whole copy that lost a quadrant is not reported as that"),
):
    # The probe's own source, not the harness's: the smoke lives in MTL4Probe and the harness only asks it.
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " copy=" + copy', "the harness does not print the copy smoke's answer"),
    ('+ " copyReason=" + copyReason', "the harness does not print why the copy smoke failed"),
    ("MTL4Probe.canCopyTextureRegions(device)", "the harness never asks the copy smoke"),
    ("copy_failures=\"$(grep -c ' copy=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy smoke's failures"),
    ("if (( copy_failures > 0 )); then", "the driver counts the copy smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the depth attachment, which is the half of a frame's clears the attachments smoke does not reach -------
# The plan's depth phase is two overlapping triangles with a known winner; that needs a pipeline and a draw.
# What is pinned here is the step before it: a pass whose attachments are a colour target and a depth target,
# both loaded as cleared and both stored, and the depth texture read back as the number it was given.
for needle, why in (
    ("public static boolean canClearDepth(",
     "the depth attachment and its clear are measured nowhere, so the first thing a depth pass needs has no run"),
    ("descriptor.pixelFormat(MTLPixelFormat.Depth32Float);",
     "the smoke's depth target is not the format a frame's depth attachment is"),
    ("new MTL4RenderEncoder.Depth(depth, CLEAR_DEPTH)",
     "the smoke does not clear the depth attachment to a known value"),
    ("MTLTexture.bytes(depth, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the depth texture is never read back, so the clear is asserted nowhere"),
    ("if (!(Math.abs(read - (float) CLEAR_DEPTH) <= 0.0001f)) {",
     "the depth comparison is written so that a NaN readback counts as the value that was asked for, which is a "
     "check a broken clear could pass"),
    ("the depth attachment reads ", "a depth clear that did not land is not reported as that"),
    ("return failed(\"depth\", \"a pass carrying a depth attachment could not be opened at stage \"",
     "a depth pass that could not be opened is reported under the colour-attachment smoke's stage, so the line "
     "would say the attachments smoke failed while the same line says it passed"),
    ("return failed(\"depth\", \"the depth-carrying pass did not open and did not say why\");",
     "a depth pass that came back null fails the smoke without saying anything, which reads as a smoke that "
     "passed for a reason no one can see"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " depth=" + depth', "the harness does not print the depth smoke's answer"),
    ('+ " depthReason=" + depthReason', "the harness does not print why the depth smoke failed"),
    ("MTL4Probe.canClearDepth(device)", "the harness never asks the depth smoke"),
    ("depth_failures=\"$(grep -c ' depth=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth smoke's failures"),
    ("if (( depth_failures > 0 )); then", "the driver counts the depth smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- a fence is a promise about one submission, and the client asked for it by stopping at createFence -------
# The contract of a fence is three answers, because that is what the Metal 3 fence answers and the same callers
# read both: a committed submission can be waited for, a submission no commit has promised is not complete (a
# pool that believed otherwise would hand a buffer back to the CPU while the GPU read it), and asking to wait
# for it says so rather than blocking on a signal nothing promised.
for needle, why in (
    ("public static boolean canAwaitSubmissions(", "nothing measures whether a submission's value can be waited for"),
    ("if (!ring.awaitSubmission(1L, 2000L)) {", "the smoke never waits for a submission that was committed"),
    ("if (!ring.awaitSubmission(2L, 2000L)) {", "the smoke never waits for the newest committed submission"),
    ("if (ring.awaitSubmission(3L, 0L)) {", "the smoke never polls the value no commit has promised, or polls "
     "it in a way a true answer would not fail"),
    ("ring.awaitSubmission(3L, 50L);", "the smoke never asks to wait for a submission no commit has promised"),
    ("} catch (IllegalStateException refused) {",
     "the smoke catches every runtime fault as the expected refusal, so a real defect inside the wait would be "
     "reported as the contract holding"),
    ("return ring.awaitSubmission(0L, 0L);",
     "the smoke does not check that a fence for no submission at all is complete"),
    ("ring.nextSubmission() != 3L",
     "the smoke does not check that the next commit's value is the one a fence made inside a frame would promise"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " fence=" + fence', "the harness does not print the fence smoke's answer"),
    ('+ " fenceReason=" + fenceReason', "the harness does not print why the fence smoke failed"),
    ("MTL4Probe.canAwaitSubmissions(device)", "the harness never asks the fence smoke"),
    ("fence_failures=\"$(grep -c ' fence=false ' \"$probe_log\" || true)\"",
     "the driver does not count the fence smoke's failures"),
    ("if (( fence_failures > 0 )); then", "the driver counts the fence smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the indexed draw, which is the one command the client stopped on twice --------------------------------
# The proof is built so the index buffer's contents are the only way to the expected pixel: two covering
# triangles of different flat colour, all six indices listed, and the same pass encoded at index 0 and at
# index 3 - which is six bytes in and must draw the second triangle. A first index that never becomes an
# offset draws the first triangle twice and the second reading fails.
for needle, why in (
    ("public static boolean canDrawIndexed(", "nothing measures an indexed draw, which the client reached by "
     "stopping there"),
    ("private static final int[] EXPECTED_INDEXED_PIXEL = {64, 128, 128, 255};",
     "the indexed smoke's first expected pixel is gone or is not exact in eight bits"),
    ("private static final int[] EXPECTED_INDEXED_OFSET_PIXEL = {128, 64, 128, 255};",
     "the indexed smoke's second expected pixel is gone, so a first index that never becomes an offset would "
     "pass"),
    ("indexData.set(JAVA_SHORT, index * 2L, (short) index);",
     "the index buffer is not filled with the six indices the draw selects"),
    ("long address = indexAddress + firstIndex * INDEX_TYPE_BYTES;",
     "the first index does not become a byte offset into the index buffer's address"),
    ("MTLTexture.bytes(targets[1], pixel, 4L, 0L, 0L, 1L, 1L);\n"
     "                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {",
     "the second frame's pixel is not read and compared, so the offset arithmetic is asserted nowhere (the read "
     "alone appears in the allocator-ring smoke too, which is why the pin is the pair)"),
    ("indices.gpuAddress(), frame * 3)",
     "both indexed frames start at the same index, so the offset arithmetic is never exercised"),
    ("pass.drawIndexedPrimitives(MTLPrimitiveType.Triangle.value, 3L, MTLIndexType.UInt16.value,",
     "the smoke does not draw through the production encoder's indexed draw, so the proof is of a copy"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " index=" + indexed', "the harness does not print the indexed smoke's answer"),
    ('+ " indexReason=" + indexedReason', "the harness does not print why the indexed smoke failed"),
    ("MTL4Probe.canDrawIndexed(device)", "the harness never asks the indexed smoke"),
    ("index_failures=\"$(grep -c ' index=false ' \"$probe_log\" || true)\"",
     "the driver does not count the indexed smoke's failures"),
    ("if (( index_failures > 0 )); then", "the driver counts the indexed smoke's failures and does not fail the "
     "run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- residency, which is what the frame path's addresses depend on -----------------------------------------
# The new command model binds buffers by GPU address, and an address is not a reference: this machine's
# MTL4RenderCommandEncoder.h says to use a residency set for "the index buffer the indexBuffer parameter
# references". What the smoke can prove is the objects: allocations go in, they are counted, the set commits and
# requests residency, and the queue answers the call that makes the set part of its work.
for needle, why in (
    ("public static boolean canDeclareResidency(", "nothing measures whether this device can be told what has to"
     " stay resident, which is the model the frame path's addresses depend on"),
    ("set = MTL4ResidencySet.create(device, 4L, \"the residency proof\");",
     "the smoke never makes a residency set"),
    ("if (!set.add(buffer.handle()) || !set.add(texture)) {",
     "the smoke never adds an allocation, so nothing is declared"),
    ("if (!set.commit() || !set.requestResidency()) {",
     "the smoke does not commit and request, which is what makes an added allocation effective"),
    ("if (set.allocationCount() != 2L) {",
     "the smoke does not check that what the set holds is what was put in it"),
    ('if (!responds(queue, "addResidencySet:")) {',
     "the smoke does not ask whether the queue takes a residency set at all"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " residency=" + residency', "the harness does not print the residency smoke's answer"),
    ('+ " residencyReason=" + residencyReason', "the harness does not print why the residency smoke failed"),
    ("MTL4Probe.canDeclareResidency(device)", "the harness never asks the residency smoke"),
    ("residency_failures=\"$(grep -c ' residency=false ' \"$probe_log\" || true)\"",
     "the driver does not count the residency smoke's failures"),
    ("if (( residency_failures > 0 )); then", "the driver counts the residency smoke's failures and does not "
     "fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the indirect indexed form, which is how a chunk renderer reaches its terrain ---------------------------
# The arguments live in a buffer the GPU reads, so what the smoke proves is that they are read as arguments: the
# same two-triangle shape as the indexed smoke, with the arguments' own indexStart choosing the triangle. The
# smoke also had to learn the lifetime rule the hard way - its first version wrote one shared arguments buffer
# for both frames and the first frame read the second's arguments - so the pins include one buffer per frame.
for needle, why in (
    ("public static boolean canDrawIndexedIndirect(", "nothing measures the indirect indexed draw, which the"
     " chunk renderer reaches its terrain through"),
    ("private static final long INDIRECT_ARGUMENTS_BYTES = 20L;",
     "the smoke does not say how big MTLDrawIndexedPrimitivesIndirectArguments is"),
    ("data.set(JAVA_INT, 8L, frame == 0 ? 3 : 0);   // indexStart",
     "the smoke does not vary the arguments' own indexStart, so arguments that are ignored would pass"),
    ("MemorySegment[] argumentData = new MemorySegment[2];",
     "the smoke shares one arguments buffer between frames, so a CPU write can race a submitted read - measured,"
     " and the first version of this smoke drew the wrong triangle because of it"),
    ("pass.drawIndexedPrimitivesIndirect(MTLPrimitiveType.Triangle.value, MTLIndexType.UInt16.value,",
     "the smoke does not draw through the production encoder's indirect form, so the proof is of a copy"),
    ("MTLTexture.bytes(targets[0], pixel, 4L, 0L, 0L, 1L, 1L);\n"
     "                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {",
     "the first frame's pixel is not read and compared with the triangle its arguments asked for (the read"
     " appears in the indexed smoke too, which is why the pin is the pair)"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " indirect=" + indirect', "the harness does not print the indirect smoke's answer"),
    ('+ " indirectReason=" + indirectReason', "the harness does not print why the indirect smoke failed"),
    ("MTL4Probe.canDrawIndexedIndirect(device)", "the harness never asks the indirect smoke"),
    ("indirect_failures=\"$(grep -c ' indirect=false ' \"$probe_log\" || true)\"",
     "the driver does not count the indirect smoke's failures"),
    ("if (( indirect_failures > 0 )); then", "the driver counts the indirect smoke's failures and does not fail "
     "the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

print("Metal 4 cold-probe harness contract: PASS")
