package com.metallum.render.shared;

import com.metallum.render.MetalExecutionTelemetry;

import com.metallum.Metallum;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.metallum.mtl.MTLTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.fabricmc.loader.api.FabricLoader;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Locale;
import java.util.Set;

/**
 * One line every six hundred frames about what a frame asked Metal to encode, for as long as it is
 * armed. A developer probe, and the cheapest reading of a question the backend cannot answer by
 * inspection.
 * <p>
 * It exists because the costs a Metal frame is judged on are each decided in a different class of
 * this backend and are invisible from any of them: how often an encoder is torn down and rebuilt,
 * how many bytes of attachment are loaded and stored, how many bindings a draw state pushes, and
 * what pipeline creation costs. A frame that is slow for one of those reasons cannot be told from a
 * frame that is slow for another without counting all four on the frames that are actually drawn.
 * <p>
 * A window also carries the wall-clock it took, because a count of bytes is not a performance
 * reading until something says what those bytes were worth: a fall in traffic that does not move the
 * frame rate is a fall in a number and not in the cost of a frame. The time is taken from the
 * frame boundary, which is where the command buffer is committed and the drawable presented, so it
 * is the rate a player sees rather than a rate one stage of the pipeline ran at.
 * <p>
 * <strong>Off unless asked for.</strong> {@code -Dmetallum.probeFrames=true} arms it, and a
 * {@code metallum/probe-frames} file in the game directory says the same thing, because a
 * launcher's arguments are a place a session cannot reach while a file in the game directory is one
 * it can. {@code -Dmetallum.frameProbeBudget=N} bounds the frames observed, six hundred by default,
 * and a line covers six hundred frames rather than one: an unbounded per-frame probe is a way to
 * fill a disk rather than a way to answer a question. The marker decides a window rather than a
 * launch: it is asked while the probe is off, at most once a second, so a session can be told to
 * start counting once the render path it is meant to measure is the one in force. A window opens on
 * the marker's return and not on its presence, so a file left behind arms the window that read it
 * and no other.
 * <p>
 * Nothing here observes anything but counts. Every entry point below returns on its guard before it
 * touches an attachment, a timestamp or a texture, so an unarmed launch pays one boolean field read
 * per hook, an increment a frame, and one stat a second.
 */
@Environment(EnvType.CLIENT)
public final class MetalFrameProbe {

    /** Whether the flag asked for it. Read once, at class load, as every property in this package is. */
    private static final boolean FLAG = Boolean.getBoolean("metallum.probeFrames");

    /** How many frames to observe before stopping, so an armed launch cannot fill a disk by accident. */
    private static final int BUDGET = Integer.getInteger("metallum.frameProbeBudget", 600);

    /** How many frames one line covers. A line a frame would be a load test, not a reading. */
    private static final int REPORT_FRAMES = 600;

    /**
     * Frames between two asks of the marker while the probe is off. A second of a played session,
     * which is often enough to arm a window while the work worth counting is still running and rare
     * enough that asking cannot be what an unarmed session is spending its time on.
     */
    private static final int ASK_EVERY_FRAMES = 60;

    /** The directory a marker beside the game's own files is looked for in. */
    private static final String MARKER_DIRECTORY = "metallum";

    private static final String MARKER = "probe-frames";

    /** The marker file's answer as last asked, held so that asking is a frame's step and not a hook's. */
    @Nullable
    private static Boolean armedFromFile;

    /** Frames since the marker was last asked, so that an unarmed session asks a second and not a frame. */
    private static int framesSinceAsk;

    /** Frames observed since the probe armed; the budget is spent when this reaches it. */
    private static int frames;

    private static boolean announced;

    /**
     * The window's counts, reset by every line so that a line describes its own frames and no
     * others. They are read and written from the render thread alone, like the encoder state they
     * describe.
     */
    private static int windowFrames;

    /**
     * When this window's first frame was submitted, so that a line can carry the wall-clock the
     * window took. A window is the frames between two markers, so its length is read from its own
     * first frame rather than from the last line, which would include whatever the session did
     * between the two.
     */
    private static long windowStartedAt;

    /**
     * Every frame's own wall time and GPU time, so a window can be read as a distribution and not only
     * as a mean. A mean hides exactly what a player feels: the frame that took four times the others is
     * four hundred frames of average away and one visible stutter. Sized by the budget because a window
     * is bounded by it, and a frame past the cap is dropped rather than resizing an array in a frame path.
     */
    private static final double[] wallTimes = new double[BUDGET + 1];
    private static final double[] gpuTimes = new double[BUDGET + 1];
    private static int wallSamples;
    private static int gpuSamples;
    private static long lastFrameAt;
    private static int worstWallFrame;

    /**
     * What the driver said the GPU spent on the frames of this window, summed, and how many frames it
     * answered for. The window's wall-clock says how fast frames arrive; this says how much of that the
     * GPU was running, and the difference between the two is what the CPU and the presentation cost.
     * It is also the yardstick the pack side's own per-pass report needs: that report is filled from the
     * host clock, so this is the only GPU time in the session.
     */
    private static int gpuFrames;
    private static double gpuMillis;

    /**
     * The same two numbers for the Metal 4 queue, which reports them differently and on another thread.
     * <p>
     * A Metal 3 command buffer answers {@code GPUStartTime}/{@code GPUEndTime} when its completion block
     * runs; a Metal 4 queue reports a submission through commit feedback, which arrives on a dispatch queue
     * Metal owns. So this half is written from a thread that is not the render thread, and it is counted in
     * atomics for that reason - a race here would be a window whose GPU time is quietly short.
     * <p>
     * The two halves are what makes a Metal 4 submission visible at all: {@code gpuMillis} used to be the
     * Metal 3 road alone, so a frame whose present moved to the new queue *lost* GPU time from the report
     * and read as if it had got cheaper. Summing them is the frame's whole GPU time, and each is reported
     * separately so the two paths can still be compared with each other.
     */
    private static final java.util.concurrent.atomic.AtomicInteger metal4Feedbacks =
            new java.util.concurrent.atomic.AtomicInteger();

    /**
     * Every commit feedback this session has had, whether or not a window was open.
     * <p>
     * The window's own count answers "how much of this window's GPU time do I know"; this one answers
     * "does the queue call back at all", and the two being different is a fact about delivery rather than
     * about the path: a feedback that arrives after the report is a feedback no window can count, and a
     * number that never rises is a handler Metal never accepted.
     */
    private static final java.util.concurrent.atomic.AtomicInteger metal4FeedbacksTotal =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicInteger metal4GpuFrames =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicLong metal4GpuNanos =
            new java.util.concurrent.atomic.AtomicLong();
    private static int encoders;
    private static int passChanged;
    private static int submitEnds;
    private static long loadedBytes;
    private static long storedBytes;

    /**
     * The depth attachment's share of the two above, and how many passes attached one. Kept apart
     * because the depth slot is the one attachment the pack side cannot currently say anything about,
     * and because a frame's depth is the largest single attachment in it.
     */
    private static int depthAttachments;
    private static long depthLoadedBytes;
    private static long depthStoredBytes;

    /**
     * How much a frame moved by blitting one texture into another, and how many blits that was. The
     * copy-backs a pack's kept targets need at the end of every frame are blits, and every other
     * counter here counts an attachment, an encoder or a binding, so without this they are inside the
     * frame's GPU time and invisible in its decomposition.
     */
    private static int blits;
    private static long blittedBytes;

    /**
     * Encoders opened by kind, which is the decomposition {@code passChanged} never had.
     * <p>
     * {@code encoders} counts encoder *ends* and {@code passChanged} counts those that ended because the
     * pass configuration changed - and an encoder the engine itself opened to copy a texture, materialise
     * a clear or build a depth mip ends that way too. So the number the phase's exit criterion wants to
     * move has never been split into "the pack's passes" and "this engine's own switches", and these four
     * are that split, counted where each encoder is created.
     */
    private static int renderPassOpeners;
    private static int blitOpeners;
    private static int computeOpeners;
    private static int clearOpeners;

    /** Frames carried through the Metal 4 command structure, and what that path cost on the CPU. */
    private static int metal4Frames;
    private static long metal4Nanos;
    private static int metal4Draws;
    private static int metal4Presents;
    private static int pipelines;
    private static int textures;
    private static int samplers;
    private static int buffers;
    private static int viewports;
    private static int scissors;

    /** Session totals: pipeline creation is not a per-frame event, so it is read as a session cost. */
    private static int compiles;
    private static long compileNanos;
    /** Pipeline identities and descriptions seen since process start, for the cache question. */
    private static final Set<RenderPipeline> pipelineIdentities = Collections.newSetFromMap(new IdentityHashMap<>());
    private static final Set<MetalPipelineKey> pipelineKeys = new java.util.HashSet<>();
    private static int identityCount;
    private static int keyCount;
    /**
     * Set when the census is first reported. Pipelines are built during startup and the report is the
     * measurement, so everything the number is about has happened by then; closing the census there is what
     * keeps it a diagnostic instead of a session-long retention of every pipeline object the game built -
     * which would defeat the eviction the caches do on purpose.
     */
    private static boolean censusClosed;

    private MetalFrameProbe() {
    }

    /**
     * Why a native encoder ended. These are the two boundaries that say something about the frame,
     * so they are counted apart from each other. A reason is passed wherever the frame may end, and
     * only an encoder that was actually open is counted, so a reason offered at two sites still
     * yields one boundary.
     */
    public enum EncoderEnd {
        /** The attachment set or its clear values changed, so the next pass needs its own encoder. */
        PASS_CONFIGURATION_CHANGED,
        /** The frame's encoding is over: its drawable is being blitted, presented and submitted. */
        SUBMITTED
    }

    /**
     * Whether the probe is to record what happens next. One field read when the answer is no, which
     * is the whole of what an unarmed launch may pay here.
     */
    public static boolean armed() {
        if (!FLAG && !marker()) {
            return false;
        }

        if (frames >= BUDGET) {
            return false;
        }

        if (!announced) {
            announced = true;
            Metallum.LOGGER.info(
                    "Metal frame probe armed: one line every {} frames, at most {} frames of counting",
                    REPORT_FRAMES,
                    BUDGET
            );
        }

        return true;
    }

    /**
     * An encoder ended, and why. The two reasons are counted apart because they say different
     * things: a pass whose attachments changed forces Metal to build a new render encoder, while the
     * frame boundary ends whatever encoder is still open, which a presented frame does when its
     * drawable is blitted rather than a moment later when the command buffer is submitted.
     */
    public static void encoderEnded(final EncoderEnd reason) {
        if (!armed()) {
            return;
        }

        encoders++;
        if (reason == EncoderEnd.PASS_CONFIGURATION_CHANGED) {
            passChanged++;
        } else {
            submitEnds++;
        }
    }

    /**
     * The frame boundary: the command buffer has been committed. The window is summed and the line
     * written here rather than at each counter, so that a frame costs one logging decision and not
     * one per binding. This is also the one place the marker is asked again, because a frame is the
     * only thing an unarmed session is known to do exactly once.
     */
    public static void frameSubmitted() {
        if (!armed()) {
            askAgain();
            return;
        }

        frames++;
        windowFrames++;
        long now = System.nanoTime();
        if (windowFrames == 1) {
            windowStartedAt = now;
        } else if (wallSamples < wallTimes.length) {
            wallTimes[wallSamples] = (now - lastFrameAt) / 1_000_000.0;
            if (wallSamples == 0 || wallTimes[wallSamples] >= wallTimes[worstWallFrame]) {
                worstWallFrame = wallSamples;
            }
            wallSamples++;
        }
        lastFrameAt = now;
        if (frames % REPORT_FRAMES == 0 || frames >= BUDGET) {
            report();
        }
    }

    /**
     * One render-pass attachment, as the encoder is about to decide whether Metal loads or stores
     * it. The texture and its pixel size are handed over instead of a byte count because an unarmed
     * probe must not make its caller ask Metal for a width or a height: those two queries sit below
     * the guard, and an attachment whose owner could not determine its pixel size counts nothing
     * rather than a guess.
     */
    public static void attachment(final MemorySegment texture, final int pixelSize, final boolean loaded, final boolean stored) {
        if (!armed()) {
            return;
        }

        if (pixelSize <= 0) {
            return;
        }

        long bytes = MTLTexture.width(texture) * MTLTexture.height(texture) * pixelSize;
        if (loaded) {
            loadedBytes += bytes;
        }
        if (stored) {
            storedBytes += bytes;
        }
    }

    /**
     * One command buffer finished, and the driver's own answer for how long the GPU ran it. Called
     * once a frame, a few frames behind the frame it describes, because Apple's two times "remain 0.0
     * until the GPU finishes running the command buffer" - so this is a reading of a completed frame
     * rather than of the frame being encoded, which is the whole difference between this and the
     * pack side's per-pass report.
     */
    public static void gpuFrame(final double milliseconds) {
        if (!armed()) {
            return;
        }

        if (milliseconds <= 0.0) {
            return;
        }

        gpuFrames++;
        gpuMillis += milliseconds;
        if (gpuSamples < gpuTimes.length) {
            gpuTimes[gpuSamples++] = milliseconds;
        }
    }

    /**
     * One commit's own GPU time from the Metal 4 queue's commit feedback, in milliseconds.
     * <p>
     * The reading is of a completed submission and not a shape: a feedback with no times - both are zero
     * until the GPU has finished - is dropped rather than counted as a fast frame, which is what makes a
     * handler that is never called look different from a frame that took no time.
     */
    public static void gpuFrameMetal4(final double milliseconds) {
        metal4FeedbacksTotal.incrementAndGet();
        if (!armed()) {
            return;
        }

        // Two counts and not one, because "the queue called back and the times were zero" and "the queue
        // never called back" are different repairs behind the same silent window: the first is a reading
        // taken too early, the second is a handler that was never installed or never accepted.
        metal4Feedbacks.incrementAndGet();
        if (milliseconds <= 0.0) {
            return;
        }

        metal4GpuFrames.incrementAndGet();
        metal4GpuNanos.addAndGet((long) (milliseconds * 1_000_000.0));
    }

    /**
     * A blit moved a rectangle of one texture into another, as its pixel size. The caller hands the
     * size over rather than the texture so that an unarmed session pays the guard and nothing else -
     * the size is a number the caller already has, not a question asked of Metal.
     */
    /**
     * One frame carried through the Metal 4 command structure, and how long the CPU spent carrying it.
     * <p>
     * The path is beside the frame rather than in it, so the number to read is the cost of carrying it: on
     * the GPU it is a 64x64 pass, and on the CPU it is the messages a frame-shaped submission takes.
     */
    public static void metal4Frame(final long nanos, final boolean drawn) {
        if (!armed()) {
            return;
        }

        metal4Frames++;
        metal4Nanos += nanos;
        if (drawn) {
            metal4Draws++;
        }
    }

    /**
     * One present carried by the Metal 4 queue, which is one drawable taken and presented.
     * <p>
     * Counted apart from the submission above because the two are different questions: that one says the new
     * command structure ran a frame's submission and whether it drew, this one says the picture the player
     * sees came through the new queue. They agree frame for frame unless a frame was presented by the
     * engine's own road, and `metal4Draws` belongs to the submission above so that a draw is counted once.
     */
    public static void metal4Present() {
        if (!armed()) {
            return;
        }

        metal4Presents++;
    }

    /** An encoder the engine itself opened, by the work it was opened for. */
    public static void encoderOpened(final int kind) {
        if (!armed()) {
            return;
        }

        switch (kind) {
            case 0 -> renderPassOpeners++;
            case 1 -> blitOpeners++;
            case 2 -> computeOpeners++;
            default -> clearOpeners++;
        }
    }

    public static void blit(final int width, final int height, final int pixelSize) {
        if (!armed()) {
            return;
        }

        if (width <= 0 || height <= 0 || pixelSize <= 0) {
            return;
        }

        blits++;
        blittedBytes += (long) width * height * pixelSize;
    }

    /**
     * The depth attachment of a render pass, counted apart from the colour ones as well as inside the
     * totals.
     * <p>
     * It is counted apart because it is the one attachment no answer of the pack side can currently
     * reach: the lifetime capability that crosses the seam carries one flag an attachment slot and the
     * depth slot is not one of them, so a depth load is clear-or-load and a depth store is a store,
     * always. A frame's depth is also the largest single attachment in it, so how much of the totals
     * this is decides whether teaching the depth slot to answer is worth doing - which is a question
     * for a measurement rather than for an estimate.
     */
    public static void depthAttachment(final MemorySegment texture, final int pixelSize, final boolean loaded, final boolean stored) {
        if (!armed()) {
            return;
        }

        if (pixelSize <= 0) {
            return;
        }

        long bytes = MTLTexture.width(texture) * MTLTexture.height(texture) * pixelSize;
        depthAttachments++;
        if (loaded) {
            depthLoadedBytes += bytes;
            loadedBytes += bytes;
        }
        if (stored) {
            depthStoredBytes += bytes;
            storedBytes += bytes;
        }
    }

    /** A pipeline state was pushed onto a render encoder. */
    public static void pipelineBound() {
        if (!armed()) {
            return;
        }

        pipelines++;
    }

    /** A texture reached a stage, directly or through an argument buffer. */
    public static void textureBound() {
        if (!armed()) {
            return;
        }

        textures++;
    }

    /** A sampler reached a stage, which a texture bind with a non-null sampler always does too. */
    public static void samplerBound() {
        if (!armed()) {
            return;
        }

        samplers++;
    }

    /** A buffer reached a stage: vertex, fragment, uniform, storage or argument buffer. */
    public static void bufferBound() {
        if (!armed()) {
            return;
        }

        buffers++;
    }

    /** A viewport was set. Metal sets one per render encoder, so this is per encoder and not per draw. */
    public static void viewportSet() {
        if (!armed()) {
            return;
        }

        viewports++;
    }

    /** A scissor rect was pushed, once per state change rather than once per draw. */
    public static void scissorSet() {
        if (!armed()) {
            return;
        }

        scissors++;
    }

    /**
     * A render pipeline state was created, which happens off the frame path and is therefore read as
     * a session cost beside the per-frame counts.
     *
     * @param nanos how long the Metal call took
     */
    /**
     * Counts the pipeline identities and the pipeline descriptions the device has been asked for, from
     * process start rather than from arming: pipelines are compiled while the game starts, so a census
     * that began when the marker appeared would report almost nothing.
     * <p>
     * It exists to answer one question with a number instead of an opinion - whether the identity cache
     * and a cache keyed by description would hold the same number of entries. If they hold the same
     * number, moving the cache onto the key buys nothing and costs the eviction contract; if the key
     * count is lower, the difference is the pipeline compilations the move would save.
     * <p>
     * The census closes at its first report: everything it counts is built during startup and settling, and
     * a set that kept growing afterwards would hold pipeline objects the caches are entitled to release.
     * <p>
     * The identity test comes first and the key is only hashed when the identity is new, because this is
     * reached wherever a pipeline is asked for and the key's hash reads seven strings. That is still the
     * whole question: a second identity carrying a key already seen is exactly the deduplication the move
     * would buy, and it is counted when that second identity appears.
     */
    public static void pipelineRequested(final RenderPipeline pipeline, final MetalPipelineKey key) {
        if (censusClosed) {
            return;
        }

        if (!pipelineIdentities.add(pipeline)) {
            return;
        }

        identityCount++;

        if (pipelineKeys.add(key)) {
            keyCount++;
        }
    }

    public static void pipelineCompiled(final long nanos) {
        if (!armed()) {
            return;
        }

        compiles++;
        compileNanos += nanos;
    }

    /**
     * Writes the window and starts the next one. The last frame of the budget writes the final line
     * and turns the probe off, so an armed session stops by itself; only a marker that goes away and
     * comes back opens another window.
     */
    private static void report() {
        // Read before reset(), which clears the window's first frame along with its counts.
        long windowNanos = System.nanoTime() - windowStartedAt;
        Metallum.LOGGER.info(
                "frame-probe openers renderPasses={} blitEncoders={} computeEncoders={} clearEncoders={} "
                        + "metal4Frames={} metal4Us={} metal4Draws={} metal4Presents={}",
                renderPassOpeners,
                blitOpeners,
                computeOpeners,
                clearOpeners,
                metal4Frames,
                String.format(Locale.ROOT, "%.1f", metal4Frames == 0 ? 0.0 : metal4Nanos / 1000.0 / metal4Frames),
                metal4Draws,
                metal4Presents
        );
        Metallum.LOGGER.info(
                "frame-probe {}/{} windowFrames={} windowMs={} gpuFrames={} gpuM4Feedbacks={} gpuM4FeedbacksTotal={} gpuM4Frames={} gpuM3Ms={} gpuM4Ms={} gpuMs={} "
                        + "selectedGeneration={} executingGeneration={} encoders={} passChanged={} submit={} loadedMiB={} storedMiB={} "
                        + "depthAttachments={} depthLoadedMiB={} depthStoredMiB={} blits={} blittedMiB={} "
                        + "pipeline={} texture={} sampler={} buffer={} viewport={} scissor={} compiles={} compileMs={} "
                        + "pipelineIdentities={} pipelineKeys={} "
                        + "wallP50={} wallP95={} wallP99={} wallMax={} wallMaxAt={} gpuP50={} gpuP95={} gpuP99={} gpuMax={}",
                frames,
                BUDGET,
                windowFrames,
                millis(windowNanos),
                gpuFrames,
                metal4Feedbacks.get(),
                metal4FeedbacksTotal.get(),
                metal4GpuFrames.get(),
                String.format(Locale.ROOT, "%.2f", gpuMillis),
                String.format(Locale.ROOT, "%.2f", metal4GpuNanos.get() / 1_000_000.0),
                String.format(Locale.ROOT, "%.2f", gpuMillis + metal4GpuNanos.get() / 1_000_000.0),
                MetalExecutionTelemetry.selectedToken(),
                MetalExecutionTelemetry.executingToken(),
                encoders,
                passChanged,
                submitEnds,
                mebibytes(loadedBytes),
                mebibytes(storedBytes),
                depthAttachments,
                mebibytes(depthLoadedBytes),
                mebibytes(depthStoredBytes),
                blits,
                mebibytes(blittedBytes),
                pipelines,
                textures,
                samplers,
                buffers,
                viewports,
                scissors,
                compiles,
                millis(compileNanos),
                identityCount,
                keyCount,
                percentile(wallTimes, wallSamples, 0.50),
                percentile(wallTimes, wallSamples, 0.95),
                percentile(wallTimes, wallSamples, 0.99),
                percentile(wallTimes, wallSamples, 1.00),
                worstWallFrame + 1,
                percentile(gpuTimes, gpuSamples, 0.50),
                percentile(gpuTimes, gpuSamples, 0.95),
                percentile(gpuTimes, gpuSamples, 0.99),
                percentile(gpuTimes, gpuSamples, 1.00)
        );
        censusClosed = true;
        reset();

        if (frames >= BUDGET) {
            Metallum.LOGGER.info(
                    "Metal frame probe wrote its {} frame(s) and is off; the log holds the run it was armed for",
                    BUDGET
            );
        }
    }

    private static void reset() {
        windowFrames = 0;
        windowStartedAt = 0L;
        lastFrameAt = 0L;
        wallSamples = 0;
        worstWallFrame = 0;
        gpuSamples = 0;
        gpuFrames = 0;
        metal4Feedbacks.set(0);
        metal4GpuFrames.set(0);
        metal4GpuNanos.set(0L);
        gpuMillis = 0.0;
        encoders = 0;
        passChanged = 0;
        submitEnds = 0;
        loadedBytes = 0L;
        storedBytes = 0L;
        depthAttachments = 0;
        depthLoadedBytes = 0L;
        depthStoredBytes = 0L;
        blits = 0;
        blittedBytes = 0L;
        renderPassOpeners = 0;
        blitOpeners = 0;
        computeOpeners = 0;
        clearOpeners = 0;
        metal4Frames = 0;
        metal4Nanos = 0L;
        metal4Draws = 0;
        metal4Presents = 0;
        pipelines = 0;
        textures = 0;
        samplers = 0;
        buffers = 0;
        viewports = 0;
        scissors = 0;
    }

    /**
     * Asks the marker again, at most once a second and only while nothing is being counted. The
     * frames worth counting are the ones a session spends with its whole render path in force, and
     * the launch cannot know when that begins: a marker read at the first frame spends the budget on
     * whatever was drawn before it. So a window opens on the marker's return and not on its
     * presence, and the file a finished window was armed by arms that window alone -- otherwise a
     * marker left in place would arm window after window and fill a disk, which is the one thing the
     * budget exists to prevent. The property is not asked again: it answered for the launch and
     * cannot change under it.
     */
    private static void askAgain() {
        if (FLAG) {
            return;
        }

        if (++framesSinceAsk < ASK_EVERY_FRAMES) {
            return;
        }

        framesSinceAsk = 0;
        final boolean present = markerPresent();
        if (present == marker()) {
            return;
        }

        armedFromFile = present;
        if (present) {
            frames = 0;
            announced = false;
        }
    }

    private static boolean marker() {
        if (armedFromFile == null) {
            armedFromFile = markerPresent();
        }

        return armedFromFile;
    }

    /**
     * Whether the marker file is there. A game directory that cannot be asked, or cannot be read, is
     * an unarmed launch rather than a failed one: a probe may never be the reason a session does not
     * start.
     */
    private static boolean markerPresent() {
        try {
            Path gameDirectory = FabricLoader.getInstance().getGameDir();
            return gameDirectory != null
                    && Files.isRegularFile(gameDirectory.resolve(MARKER_DIRECTORY).resolve(MARKER));
        } catch (RuntimeException exception) {
            return false;
        }
    }

    private static String mebibytes(final long bytes) {
        return String.format(Locale.ROOT, "%.1f", bytes / (1024.0 * 1024.0));
    }

    /**
     * One percentile of a window's samples, as a formatted number of milliseconds.
     * <p>
     * Sorted on a copy so the samples stay in arrival order for whatever reads them next, and taken by
     * nearest rank rather than by interpolation: a percentile of a frame-time distribution is one of the
     * frames that happened, and an interpolated number between two of them is a frame that did not.
     */
    private static String percentile(final double[] times, final int count, final double fraction) {
        if (count <= 0) {
            return String.format(Locale.ROOT, "%.2f", 0.0);
        }

        double[] sorted = java.util.Arrays.copyOf(times, count);
        java.util.Arrays.sort(sorted);
        int rank = (int) Math.ceil(fraction * count) - 1;
        if (rank < 0) {
            rank = 0;
        }
        if (rank >= count) {
            rank = count - 1;
        }
        return String.format(Locale.ROOT, "%.2f", sorted[rank]);
    }

    private static String millis(final long nanos) {
        return String.format(Locale.ROOT, "%.2f", nanos / 1_000_000.0);
    }
}
