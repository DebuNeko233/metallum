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
    "selectedGeneration={}",
    "public static void gpuFrameMetal4(final double milliseconds) {",
    "metal4FeedbacksTotal.incrementAndGet();",
    "metal4Feedbacks.incrementAndGet();",
    "metal4GpuFrames.incrementAndGet();",
    "metal4GpuNanos.addAndGet((long) (milliseconds * 1_000_000.0));",
    # The arguments and the placeholders have to agree, and their order is pinned because a value added to
    # one and not the other prints every counter after it under another counter's name - which happened
    # twice while this line was being built.
    "gpuFrames,\n                metal4Feedbacks.get(),\n                metal4FeedbacksTotal.get(),\n                metal4GpuFrames.get(),",
    "MetalExecutionTelemetry.token(),",
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
    "if (!awaitSubmitCompletion(currentSubmitIndex - MAX_SUBMITS_IN_FLIGHT, 5000L))",
    "MetalFrameProbe.gpuFrame(toClose.buffer.gpuMillis());",
    "the GPU time is read before the submit it belongs to has been waited on, so the driver has not reported it yet",
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

if len(guarded) != 18:
    raise SystemExit(
        "frame probe: expected 18 guarded entry points (encoder, encoder opener, frame, gpu frame, Metal 4 "
        "gpu frame, Metal 4 frame, Metal 4 present, colour attachment, depth attachment, blit, six binding "
        "kinds, pipeline creation and the pipeline census), found "
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
require("binding counters", render_pass, (
    "MetalFrameProbe.pipelineBound();",
    "MetalFrameProbe.textureBound();",
    "MetalFrameProbe.samplerBound();",
    "MetalFrameProbe.bufferBound();",
    "MetalFrameProbe.scissorSet();",
))
require("viewport counter", render_encoder, (
    "import com.metallum.render.shared.MetalFrameProbe;",
    "MetalFrameProbe.viewportSet();",
))
if render_pass.index("MetalFrameProbe.pipelineBound();") > render_pass.index("enc.setRenderPipelineState(pipelineHandle);"):
    raise SystemExit("binding counters: the pipeline count is not taken where the pipeline is pushed")
if render_pass.index("MetalFrameProbe.scissorSet();") < render_pass.index("private void pushEffectiveScissor("):
    raise SystemExit("binding counters: the scissor count is not taken inside the scissor push")
for label, needle in (
    ("vertex buffer", "MetalFrameProbe.bufferBound();\n            enc.setVertexBuffer(nativeVertexBuffer.metalBuffer(), vertexBuffer.offset(), metalSlot);"),
    ("direct buffer", "MetalFrameProbe.bufferBound();\n        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {"),
    ("direct texture", "MetalFrameProbe.textureBound();\n        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {\n            enc.setVertexTexture(texture, index);"),
    ("sampled texture", "MetalFrameProbe.textureBound();\n        MetalFrameProbe.samplerBound();"),
):
    if needle not in render_pass:
        raise SystemExit(f"binding counters: the {label} push is not counted where it is pushed")
if render_pass.count("MetalFrameProbe.samplerBound();") != 3:
    raise SystemExit("binding counters: a sampled image carries a sampler on both the direct and the argument path")
if render_pass.count("MetalFrameProbe.textureBound();") != 6:
    raise SystemExit("binding counters: storage and texel-buffer bindings must count as textures too")
if render_pass.count("MetalFrameProbe.bufferBound();") != 5:
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

print("Metal frame-probe instrumentation contract: PASS")
