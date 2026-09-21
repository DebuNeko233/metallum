#!/usr/bin/env python3
"""Pins the frame probe's shape so that instrumenting this backend stays opt-in and reversible.

The probe is a measuring instrument, not a feature: it may only ever be armed by a property or a
marker file, it may only ever record counts, and it may only ever be reached from the hooks below.
Every assertion here fails the build rather than reporting a warning, for the same reason the other
`tools/ci-*.py` contracts do -- a probe that quietly stopped being armed, or that started asking
Metal for a texture width on the unarmed path, is a behaviour change nobody would see in a diff.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = "src/main/java/com/metallum/render/shared/MetalFrameProbe.java"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


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
encoder = read("src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java")
metal4_encoder = read("src/main/java/com/metallum/render/metal4/Metal4FrameEncoder.java")
command_buffer = read("src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java")
render_pass = read("src/main/java/com/metallum/render/metal3/MetalRenderPass.java")
device = read("src/main/java/com/metallum/render/MetalDevice.java")
render_encoder = read("src/main/java/com/metallum/mtl/metal3/MTLRenderCommandEncoder.java")
pipeline = read("src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java")

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
    if first != "if (!armed()) {" and not (
            (counts_unarmed and first == "metal4FeedbacksTotal.incrementAndGet();")
            or (census_unarmed and first == "if (censusClosed) {")):
        raise SystemExit(
            f"frame probe: {declaration} does not open with the armed() guard, so an unarmed call "
            "is no longer a single field read"
        )
    guarded.append(declaration)

if len(guarded) != 58:
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
        "than counts), found "
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
# `tools/ci-contracts.py` refuses these names repo-wide; this repeats it on the files the frame
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
