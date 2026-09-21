package com.metallum.render.shared;

import com.metallum.render.MetalExecutionTelemetry;

import com.metallum.Metallum;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.systems.RenderSystem;
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
     * Client ticks counted since this process started, and the value the window opened at.
     * <p>
     * <strong>Why the window needs a tick count at all.</strong> A window is a fixed *frame* count, and this
     * client's frame is not the same work on every frame: measured on the no-pack scene, a frame is 7 render
     * passes in the steady state, **13 on the frame that coincides with a 20 Hz client tick** and 5 in one
     * stretch - so a window's content totals are `a*frames + b*ticks`, and two arms whose frame rates differ put
     * a different number of tick frames into the same 600-frame window. `run/drift-nopack` is why that matters:
     * the reference's three arms read `depthAttachments 1800` exactly (its frame rate is constant, so its tick
     * count is), while this path's differed by 9% and the content guard named it as scene drift. The tick count
     * is the missing fact that lets a reader tell a window that sampled a different slice of the client's life
     * from a window that drew a different world.
     */
    private static long ticks;
    private static long windowStartedAtTick;

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
    /**
     * The same, for the Metal 4 queue's per-commit feedback.
     * <p>
     * A second set rather than one, because the two sums already carry generation names (`gpuM3Ms` and
     * `gpuM4Ms`) and a percentile read off a mixed set would describe neither. The first forced Metal 4 run the
     * harness collected reported `gpuM4Ms=62.65` over thirty frames with every `gpuP*` at zero, which is this
     * gap: the sum was accumulated and the samples were not.
     */
    private static final double[] gpuM4Times = new double[BUDGET + 1];
    private static int gpuM4Samples;
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
     * The frame's two pacing waits, in milliseconds, as their own distributions.
     * <p>
     * An Unlimited-FPS session that is not unlimited is waiting somewhere, and there are two candidates on this
     * path: the drawable the frame cannot start without, and the in-flight window the submit tail waits on. They
     * are kept apart because they are different fixes - one is present-mode mapping, the other is the submission
     * window - and a single "wait ms" would not say which. Explicit teardown waits are deliberately not here:
     * they happen once, on the close path, and would read as pacing.
     */
    private static double[] drawableWaitTimes = new double[64];
    private static int drawableWaits;
    private static double drawableWaitTotal;

    private static double[] submitWindowWaitTimes = new double[64];
    private static int submitWindowWaits;
    private static double submitWindowWaitTotal;

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
    /** Clears the frame deferred and the next pass carried as a load action, and those it had to encode. */
    private static int clearDeferred;
    private static int clearFolded;
    /** Phase F's upload census: by road, and the whole cost. */
    private static long uploadCalls;
    private static long uploadBytes;
    private static long uploadNanos;
    private static long uploadsToBuffer;
    private static long uploadedToBufferBytes;
    private static long uploadCopiesToBuffer;
    private static long uploadedCopyBytes;
    private static long uploadsToTexture;
    private static long uploadedToTextureBytes;

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
    /** Pipelines whose non-zero depth bias was applied to an encoder, which section 58 needs a reading of. */
    private static int depthBiases;

    /** Session totals: pipeline creation is not a per-frame event, so it is read as a session cost. */
    private static int compiles;
    private static long compileNanos;

    /**
     * The same work counted OUTSIDE a window - a pack's load, and the world's first seconds - which is where
     * the question F4 has about a load actually lives.
     * <p>
     * The two sets are kept apart on purpose. Everything above is measured between the probe's arm and its
     * report, which the harness opens after the pack's first full frame and a 25 second settle; a compile that
     * happens before that is invisible to it by construction, and reading {@code compiles=0} off a window in
     * which 187 units were built is the misreading this pair exists to prevent.
     * <p>
     * <strong>The split by thread is the answer and not a detail.</strong> A pipeline built on a warm-up worker
     * is work overlapped with the load; a pipeline built on the <em>render thread</em> is a draw that asked for
     * one before the warm-up reached it, which is the hitch the warm-up exists to prevent and the only part of
     * a load's compiling an archive could turn into a read.
     */
    private static final java.util.concurrent.atomic.AtomicInteger unarmedCompiles =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicLong unarmedCompileNanos =
            new java.util.concurrent.atomic.AtomicLong();
    /** The worst single compile outside a window, which is the spike F1 asks for and no total shows. */
    private static final java.util.concurrent.atomic.AtomicLong unarmedCompileMaxNanos =
            new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicInteger unarmedRenderCompiles =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicLong unarmedRenderCompileNanos =
            new java.util.concurrent.atomic.AtomicLong();

    /**
     * The other half of the same question: the Metal function compile, which turns the MSL this engine
     * generated into something the device can build a pipeline from.
     * <p>
     * <strong>It was the unmeasured half and it is the one that decides F4.</strong> A pipeline's creation is
     * two Metal calls - a function per stage and the pipeline state over them - and only the second was timed,
     * which made a launch's whole Metal compilation look like the 25 milliseconds the pipeline states cost. What
     * the engine reports as "N of M leftover pipelines compiled ahead of their first draw, Z ms of background
     * work" is the WALL of the background job across three threads, translation and module building included,
     * and it was being read as if it were this.
     */
    private static final java.util.concurrent.atomic.AtomicInteger unarmedFunctions =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicLong unarmedFunctionNanos =
            new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicLong unarmedFunctionMaxNanos =
            new java.util.concurrent.atomic.AtomicLong();
    private static final java.util.concurrent.atomic.AtomicInteger unarmedRenderFunctions =
            new java.util.concurrent.atomic.AtomicInteger();
    private static final java.util.concurrent.atomic.AtomicLong unarmedRenderFunctionNanos =
            new java.util.concurrent.atomic.AtomicLong();
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

    /**
     * The Metal 3 argument-buffer path, counted so that its cost can be attributed rather than guessed.
     * <p>
     * An indirect descriptor is written into a native {@code MTLBuffer} the render pass allocates the first
     * time a wide layout is needed, and that buffer is handed to the compiled pipeline's
     * {@code MTLArgumentEncoder} before each descriptor write. Two different costs hide behind one total:
     * allocating the native buffer, and the per-binding calls that follow. They are counted apart because they
     * have different fixes - an arena for the first, a binding-state check for the second - and a single
     * "argumentBufferCalls" number could not say which of the two was worth removing.
     * <p>
     * {@code argBufferSetCalls} counts every call the current control flow makes, and
     * {@code argBufferSetChanges} the subset where the encoder's target buffer actually differs from the one it
     * was last handed; the difference between the two is exactly what a state shadow could remove.
     */
    private static long argBufferPasses;
    private static long argBufferLayouts;
    private static long argBufferAllocations;
    private static long argBufferAllocationBytes;
    private static long argBufferSetCalls;
    private static long argBufferSetSkipped;
    private static long argBufferTextureWrites;
    private static long argBufferSamplerWrites;
    private static long argBufferBufferWrites;
    private static long argBufferUseResourceCalls;
    private static long argBufferDraws;

    /**
     * Texel-buffer texture views made, and native render-pass descriptors made.
     * <p>
     * The first is the Phase 6 question in its smallest form: a view is a native object created per descriptor
     * push and released through the destruction queue, so a workload that uses no texel buffer at all answers
     * the phase with a nought and needs no cache. The second is the Phase 5 question, and it is recorded rather
     * than inferred because it is meant to equal the render encoders opened and a number that only equals
     * another number is worth reading from the source it is claimed to equal.
     */
    private static long texelViews;
    private static long passDescriptors;

    /**
     * The Metal 3 native-call census: what a frame asks the encoder for, how many native setter calls that
     * becomes, and how many of them carry a value the slot already has.
     * <p>
     * <strong>Why a shadow and not a counter.</strong> A count of binds says how much a frame does; it does not
     * say how much of it is work. Every one of these calls ends in an {@code objc_msgSend} through a downcall
     * handle, so the question the long-term plan asks - how much CPU this backend spends on calls whose answer
     * the encoder already knows - can only be answered by comparing each call against what the slot holds, which
     * means keeping that state. The shadow is kept <em>here</em> and not in the encoder because it must measure
     * the opportunity without taking it: nothing below changes what is sent, so a session with the census on is
     * the same frame with one more number.
     * <p>
     * It belongs to the native encoder rather than to the frame: a fresh encoder holds nothing, so
     * {@link #renderEncoderRecreated} clears it - the one hook that already knows an encoder was made - while a
     * reused encoder keeps its bindings and the shadow survives {@link #renderEncoderReused}. That distinction
     * is most of what the number means, because a logical pass that joins an open encoder inherits every slot it
     * does not rebind.
     * <p>
     * Off by default and read once, because it is a diagnostic: with {@code -Dmetallum.m3CallCensus} unset the
     * call sites below are one boolean test and the shadow is never touched.
     */
    private static final boolean CENSUS = Boolean.getBoolean("metallum.m3CallCensus");
    /** Vertex and fragment: the two stages a render encoder binds to, and the two a bind can reach. */
    private static final int CENSUS_STAGES = 2;
    /**
     * Slots the shadow covers. The texture count is above Metal's own limit for the direct path because a wide
     * pipeline reaches more through its argument buffer, and a slot outside these arrays is counted as a send
     * rather than as a repeat: a census may not guess.
     */
    private static final int CENSUS_BUFFER_SLOTS = 32;
    private static final int CENSUS_TEXTURE_SLOTS = 64;
    private static final int CENSUS_SAMPLER_SLOTS = 16;
    private static long[] censusBuffers;
    private static long[] censusTextures;
    private static long[] censusSamplers;
    private static long censusPipeline;
    private static long censusDepthStencil;
    private static long censusCull = -1L;
    private static long censusFill = -1L;
    private static long censusWinding = -1L;
    private static long censusBias = Long.MIN_VALUE;
    private static long censusViewport = Long.MIN_VALUE;
    private static long censusScissor = Long.MIN_VALUE;
    /**
     * What the frame cost the CPU, and what it allocated.
     * <p>
     * The plan's first-phase question is whether this path is CPU-bound at all, and the two readings that answer
     * it are cheap enough to take every window with no profiler in the process: the render thread's own CPU time
     * and the bytes it allocated, both from the JDK's thread MXBean, read once when the window opens and once
     * when it closes. A profiler is the wrong instrument here and this project measured why - JFR started with
     * `-XX:StartFlightRecording` ended the client with SIGABRT (exit 134) in the four-arm test that was meant to
     * price it, twice, and left two zero-byte recordings - so the census the plan falls back to is this: two
     * readings that cannot change the frame they measure.
     */
    private static com.sun.management.ThreadMXBean threadMx;
    private static long windowAllocatedStart;
    private static long windowAllocatedBytes;
    private static long windowCpuStart;

    /** Bind operations asked for, native setter calls sent, and native calls whose value the slot already had. */
    private static long censusCalls;
    private static long censusNative;
    private static long censusPipelineCalls;
    private static long censusPipelineSame;
    private static long censusDepthStencils;
    private static long censusDepthStencilsSame;
    private static long censusCulls;
    private static long censusCullsSame;
    private static long censusFills;
    private static long censusFillsSame;
    private static long censusWindings;
    private static long censusWindingsSame;
    private static long censusBiases;
    private static long censusBiasesSame;
    private static long censusViewports;
    private static long censusViewportsSame;
    private static long censusScissors;
    private static long censusScissorsSame;
    private static long censusVertexBuffers;
    private static long censusFragmentBuffers;
    private static long censusBufferSame;
    private static long censusVertexTextures;
    private static long censusFragmentTextures;
    private static long censusTextureSame;
    private static long censusVertexSamplers;
    private static long censusFragmentSamplers;
    private static long censusSamplerSame;
    private static long censusDraws;
    private static long censusDrawsIndexed;
    private static long censusDrawsIndirect;
    private static long censusFenceUpdates;
    private static long censusFenceWaits;
    /**
     * Render passes by the size of the target they draw into, against the largest target the window used.
     * <p>
     * The plan's C1 asks which of a frame's passes are full-resolution and which follow a scaled world, and
     * nothing counted it: a frame at 55 per cent draws most of its passes at 1056x660 and some - the interface,
     * a shadow map, a post pass - at the window's own size, and the split is what C3's audit needs. The largest
     * target in the window is taken as the window's own size, because at 100 per cent every pass is at it and a
     * session that never scales has one bucket.
     */
    private static long passLargestWidth;
    private static long passLargestHeight;
    /** Keyed by `width << 32 | height`, because a size is a pair and an area can be factored twice. */
    private static final java.util.LinkedHashMap<Long, Long> passSizes = new java.util.LinkedHashMap<>();
    /**
     * The indirect-draw loops: how many the frame ran, how many commands they carried, and what the loop itself
     * cost the CPU.
     * <p>
     * This is the one road the census prices rather than counts. The count alone says the indirect road is the
     * largest native-call volume in every scene measured - thousands a frame against hundreds of binds - and a
     * count cannot say whether that is a cost or a curiosity: the calls are all necessary (one per visible
     * terrain section), so what has to be known is what they cost, and the only honest reading is the loop's own
     * span. Timed once per loop rather than once per call, because a clock read per call would be measuring the
     * instrument.
     */
    private static long censusIndirectLoops;
    private static long censusIndirectCommands;
    private static long censusIndirectNanos;

    /**
     * Why a logical render pass could not join the native render encoder already open, counted once per
     * attempt so that the share of reuses is read and not assumed.
     * <p>
     * The four causes are the four halves of the reuse condition, and each is a different answer to the same
     * question: a clear action cannot be joined to an encoder that was opened without one, and the other three
     * say the encoder would be recording into different attachments or leaving them in a different state. A
     * single pass can fail several of them at once, so the causes are counted as a bitmask AND classified once
     * into a mutually exclusive bucket - the bitmask says which conditions the frame is up against, the bucket
     * says what one pass costs, and only the second one sums to the number of encoders.
     */
    private static long encReuseAttempts;
    private static long encReuseReused;
    private static long encReuseNoEncoder;
    private static long encReuseClear;
    private static long encReuseColor;
    private static long encReuseDepth;
    private static long encReuseContents;
    private static long encReuseSingleClear;
    private static long encReuseSingleColor;
    private static long encReuseSingleDepth;
    private static long encReuseSingleContents;
    private static long encReuseSingleNoEncoder;
    private static long encReuseMultiple;

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
     * One logical pass reached the point where its argument buffers are bound. Counted once per pass that has
     * any wide layout at all, which is what a per-frame "wide pipeline passes" reading needs.
     */
    public static void argBufferPass() {
        if (!armed()) {
            return;
        }

        argBufferPasses++;
    }

    /** One wide layout served for a pass, which is one binding of a native argument buffer. */
    public static void argBufferLayout() {
        if (!armed()) {
            return;
        }

        argBufferLayouts++;
    }

    /** One native argument buffer allocated, and how many bytes it asked the device for. */
    public static void argBufferAllocated(final long bytes) {
        if (!armed()) {
            return;
        }

        argBufferAllocations++;
        argBufferAllocationBytes += bytes;
    }

    /**
     * One {@code MTLArgumentEncoder.setArgumentBuffer} call the control flow really made, which after the
     * binding-state shadow is one that retargets the encoder.
     */
    public static void argBufferSet() {
        if (!armed()) {
            return;
        }

        argBufferSetCalls++;
    }

    /**
     * One such call the binding-state shadow did NOT make, because the encoder already held the buffer it was
     * about to be handed.
     * <p>
     * Counted apart from the calls that were made because the two are the two halves of the same finding: the
     * census before the shadow read 14400 calls against 1200 changes a window, and the reading after it is 1200
     * calls against 13200 skips, which is the same frame described from the other side.
     */
    public static void argBufferSetSkipped() {
        if (!armed()) {
            return;
        }

        argBufferSetSkipped++;
    }

    /** One texture descriptor written into an argument buffer. */
    public static void argBufferTextureWrite() {
        if (!armed()) {
            return;
        }

        argBufferTextureWrites++;
    }

    /** One sampler descriptor written into an argument buffer. */
    public static void argBufferSamplerWrite() {
        if (!armed()) {
            return;
        }

        argBufferSamplerWrites++;
    }

    /** One buffer descriptor written into an argument buffer. */
    public static void argBufferBufferWrite() {
        if (!armed()) {
            return;
        }

        argBufferBufferWrites++;
    }

    /**
     * One {@code useResource} call on an encoder, which the argument path makes per resource per layout because
     * the resource is resident in a buffer Metal cannot see through.
     */
    public static void argBufferUseResource() {
        if (!armed()) {
            return;
        }

        argBufferUseResourceCalls++;
    }

    /** One draw whose compiled pipeline has at least one argument buffer. */
    public static void argBufferDraw() {
        if (!armed()) {
            return;
        }

        argBufferDraws++;
    }

    /** One texel-buffer texture view created for a descriptor push. */
    public static void texelViewCreated() {
        if (!armed()) {
            return;
        }

        texelViews++;
    }

    /** One native render-pass descriptor created, which is one render encoder being opened. */
    /**
     * One render pass, with the size of the target it draws into.
     * <p>
     * Read from the pass's own render area at construction, which is the size the encoder is given rather than
     * the size of any one attachment - a pass can draw into a view of a larger texture, and what the plan asks
     * about is the target it covers.
     */
    public static void passTarget(final int width, final int height) {
        if (!armed()) {
            return;
        }

        if ((long) width * height > passLargestWidth * passLargestHeight) {
            passLargestWidth = width;
            passLargestHeight = height;
        }
        passSizes.merge(((long) width << 32) | (height & 0xFFFFFFFFL), 1L, Long::sum);
    }

    public static void passDescriptorCreated() {
        if (!armed()) {
            return;
        }

        passDescriptors++;
    }

    /** A logical render pass took the native render encoder already open. */
    public static void renderEncoderReused() {
        if (!armed()) {
            return;
        }

        encReuseAttempts++;
        encReuseReused++;
    }

    /**
     * A logical render pass could not join the open encoder, and which halves of the condition refused it.
     * <p>
     * The causes are passed one at a time rather than as a bitmask so that every entry point here opens with
     * the armed guard: a {@code public static} constant that opens no body is read by this file's own contract
     * as an unguarded entry point, and it was right to refuse it.
     *
     * @param noEncoder what is open is not a render encoder at all
     * @param clear     the pass carries a clear, which an encoder opened without one cannot take
     * @param color     the colour attachment handles differ
     * @param depth     the depth attachment handle differs
     * @param contents  the declared attachment contents differ
     */
    public static void renderEncoderRecreated(final boolean noEncoder, final boolean clear, final boolean color,
            final boolean depth, final boolean contents) {
        if (!armed()) {
            return;
        }

        // A new native encoder holds no bindings, so the census's shadow of the old one is not a fact about this
        // one. Cleared here rather than at the pass boundary, because a pass that joins the open encoder keeps
        // everything the shadow holds and only this hook says an encoder was made instead of joined.
        clearBindingShadow();
        encReuseAttempts++;
        int counted = 0;
        if (noEncoder) {
            encReuseNoEncoder++;
            counted++;
        }
        if (clear) {
            encReuseClear++;
            counted++;
        }
        if (color) {
            encReuseColor++;
            counted++;
        }
        if (depth) {
            encReuseDepth++;
            counted++;
        }
        if (contents) {
            encReuseContents++;
            counted++;
        }

        // The exclusive bucket, so that these sum to the encoders the frame really built and cannot
        // double-count a pass that failed two conditions at once.
        if (counted > 1) {
            encReuseMultiple++;
        } else if (clear) {
            encReuseSingleClear++;
        } else if (color) {
            encReuseSingleColor++;
        } else if (depth) {
            encReuseSingleDepth++;
        } else if (contents) {
            encReuseSingleContents++;
        } else {
            encReuseSingleNoEncoder++;
        }
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
            windowStartedAtTick = ticks;
            windowAllocatedStart = currentThreadAllocatedBytes();
            windowCpuStart = currentThreadCpuNanos();
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
        if (gpuM4Samples < gpuM4Times.length) {
            gpuM4Times[gpuM4Samples++] = milliseconds;
        }
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

    /**
     * One upload the frame's copy encoder carried, classified by the road it came in on.
     * <p>
     * Phase F's census, and the counter that decides whether the road is worth anything: this generation moves
     * every CPU-written byte through a staging buffer and a copy - `writeToBuffer`, `copyToBuffer` and
     * `writeToTexture` - where the reference generation writes a mapped buffer's contents directly, and the two
     * are only comparable if the calls, the bytes and the CPU time they take are readable. The time is the
     * caller's own span, because that is what a frame's gap between encoders is made of.
     * <p>
     * The classification is by road rather than by caller: a dynamic uniform, a chunk mesh and a GUI vertex
     * buffer all arrive through the same three calls, and who is calling is not a fact this layer is allowed to
     * know.
     */
    public static void uploadedToBuffer(final long bytes, final long nanos) {
        if (!armed()) {
            return;
        }

        uploadsToBuffer++;
        uploadedToBufferBytes += bytes;
        uploadCalls++;
        uploadBytes += bytes;
        uploadNanos += nanos;
    }

    /** And the same for the game's staged vertex move, which is a copy between two engine buffers. */
    public static void uploadedCopyingBuffer(final long bytes, final long nanos) {
        if (!armed()) {
            return;
        }

        uploadCopiesToBuffer++;
        uploadedCopyBytes += bytes;
        uploadCalls++;
        uploadBytes += bytes;
        uploadNanos += nanos;
    }

    /** And for a staged texture write, which is the third road CPU bytes take into this frame. */
    public static void uploadedToTexture(final long bytes, final long nanos) {
        if (!armed()) {
            return;
        }

        uploadsToTexture++;
        uploadedToTextureBytes += bytes;
        uploadCalls++;
        uploadBytes += bytes;
        uploadNanos += nanos;
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
    /**
     * The render thread's cumulative allocated bytes, or 0 where the JVM does not answer.
     * <p>
     * `com.sun.management.ThreadMXBean` is the only way to ask a HotSpot JVM what one thread has allocated
     * without a profiler, and it is asked twice a window: the difference is what a frame allocates, which is the
     * number that decides whether object churn on this path is worth pooling. A JVM that does not implement it
     * answers 0, and the line then says 0 rather than making a claim.
     */
    /**
     * The render thread's own CPU time, or 0 where the JVM does not answer.
     * <p>
     * `System.nanoTime()` around a window is the window's *wall* time and was the first thing this reading got
     * wrong: a frame whose CPU is a fraction of its wall would have read as a busy thread. What is wanted is the
     * thread's CPU, which the same MXBean answers, and the difference between the two is the whole point of the
     * reading - a render thread that waits for its drawable is not a thread that is working.
     */
    private static long currentThreadCpuNanos() {
        try {
            java.lang.management.ThreadMXBean bean = java.lang.management.ManagementFactory.getThreadMXBean();
            if (!bean.isCurrentThreadCpuTimeSupported()) {
                return 0L;
            }
            return bean.getCurrentThreadCpuTime();
        } catch (RuntimeException | LinkageError unsupported) {
            return 0L;
        }
    }

    private static long currentThreadAllocatedBytes() {
        try {
            if (threadMx == null) {
                java.lang.management.ThreadMXBean bean = java.lang.management.ManagementFactory.getThreadMXBean();
                if (bean instanceof com.sun.management.ThreadMXBean sun) {
                    if (!sun.isThreadAllocatedMemoryEnabled()) {
                        sun.setThreadAllocatedMemoryEnabled(true);
                    }
                    threadMx = sun;
                }
            }
            return threadMx == null ? 0L : threadMx.getThreadAllocatedBytes(Thread.currentThread().getId());
        } catch (RuntimeException | LinkageError unsupported) {
            return 0L;
        }
    }

    /**
     * One client tick, which the client's own tick method reports.
     * <p>
     * The count is per process and per window: what a window's content can be normalised by is how many of the
     * client's ticks it covered, so the value at the window's first frame is kept and the difference is reported.
     * <p>
     * No marker check here, unlike the frame boundary: the frame is the one place this class asks again, so that
     * no counter's guard can open a window of its own, and an unarmed tick is therefore a single field read.
     */
    public static void gameTick() {
        if (!armed()) {
            return;
        }

        ticks++;
    }

    public static void scissorSet() {
        if (!armed()) {
            return;
        }

        scissors++;
    }

    /**
     * One pipeline whose depth-stencil state asked for a non-zero depth bias, applied to the encoder.
     * <p>
     * Section 58's question is whether this generation applies a pipeline's depth bias at all, and a count is
     * the reading that answers it on a real frame: the artifact has carried the two bias fields since it was
     * written, so "the fields exist" says nothing, and "the encoder was told" is what a decal or a shadow-offset
     * pipeline depends on. Zero here on a scene that uses one would be the defect this counter exists to catch;
     * a non-zero count is what says the road is reached by real geometry rather than by a smoke.
     */
    public static void depthBiasApplied() {
        if (!armed()) {
            return;
        }

        depthBiases++;
    }

    // ---------------------------------------------------------------- the native-call census, per operation
    //
    // One entry point per kind of call a render encoder takes, each taking the value the call carries so the
    // shadow above can say whether the slot already holds it. The aggregate counters the window line has always
    // printed are incremented here too - once per *operation*, exactly as the zero-argument versions did - so a
    // session with the census on and one with it off report the same `buffer=`, `texture=` and `sampler=`, and
    // the census adds a reading rather than replacing one.

    /**
     * A buffer was bound to a slot at an offset, for one or both stages.
     * <p>
     * The shadow is keyed by handle <em>and</em> offset, because a bind with the same buffer at a different
     * offset is a different binding and the native call is not removable.
     */
    public static void bufferBound(final long handle, final long offset, final int slot,
                                   final boolean vertex, final boolean fragment) {
        if (!armed()) {
            return;
        }
        buffers++;
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        if (vertex) {
            censusVertexBuffers++;
            censusNative++;
            if (sameBuffer(0, slot, handle, offset)) {
                censusBufferSame++;
            }
        }
        if (fragment) {
            censusFragmentBuffers++;
            censusNative++;
            if (sameBuffer(1, slot, handle, offset)) {
                censusBufferSame++;
            }
        }
    }

    /** A texture was bound to a slot, for one or both stages. */
    public static void textureBound(final long handle, final int slot, final boolean vertex,
                                    final boolean fragment) {
        if (!armed()) {
            return;
        }
        textures++;
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        if (vertex) {
            censusVertexTextures++;
            censusNative++;
            if (sameHandle(censusTextures, 0, CENSUS_TEXTURE_SLOTS, slot, handle)) {
                censusTextureSame++;
            }
        }
        if (fragment) {
            censusFragmentTextures++;
            censusNative++;
            if (sameHandle(censusTextures, 1, CENSUS_TEXTURE_SLOTS, slot, handle)) {
                censusTextureSame++;
            }
        }
    }

    /** A sampler was bound to a slot, for one or both stages. */
    public static void samplerBound(final long handle, final int slot, final boolean vertex,
                                    final boolean fragment) {
        if (!armed()) {
            return;
        }
        samplers++;
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        if (vertex) {
            censusVertexSamplers++;
            censusNative++;
            if (sameHandle(censusSamplers, 0, CENSUS_SAMPLER_SLOTS, slot, handle)) {
                censusSamplerSame++;
            }
        }
        if (fragment) {
            censusFragmentSamplers++;
            censusNative++;
            if (sameHandle(censusSamplers, 1, CENSUS_SAMPLER_SLOTS, slot, handle)) {
                censusSamplerSame++;
            }
        }
    }

    /** A render pipeline state was set. */
    public static void pipelineBound(final long handle) {
        if (!armed()) {
            return;
        }
        pipelines++;
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusPipelineCalls++;
        censusNative++;
        if (censusPipeline == handle) {
            censusPipelineSame++;
        } else {
            censusPipeline = handle;
        }
    }

    /** A depth-stencil state was set. */
    public static void depthStencilBound(final long handle) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusDepthStencils++;
        censusNative++;
        if (censusDepthStencil == handle) {
            censusDepthStencilsSame++;
        } else {
            censusDepthStencil = handle;
        }
    }

    /** The cull mode, the fill mode or the winding order was set. */
    public static void cullSet(final long mode) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusCulls++;
        censusNative++;
        if (censusCull == mode) {
            censusCullsSame++;
        } else {
            censusCull = mode;
        }
    }

    /** The triangle fill mode was set. */
    public static void fillSet(final long mode) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusFills++;
        censusNative++;
        if (censusFill == mode) {
            censusFillsSame++;
        } else {
            censusFill = mode;
        }
    }

    /** The front-facing winding order was set. */
    public static void windingSet(final long mode) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusWindings++;
        censusNative++;
        if (censusWinding == mode) {
            censusWindingsSame++;
        } else {
            censusWinding = mode;
        }
    }

    /** A depth bias was set, with the two floats packed so a comparison is one test. */
    public static void depthBiasSet(final float constant, final float scaleFactor) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        final long packed = ((long) Float.floatToIntBits(constant) << 32)
                | (Float.floatToIntBits(scaleFactor) & 0xFFFFFFFFL);
        censusCalls++;
        censusBiases++;
        censusNative++;
        if (censusBias == packed) {
            censusBiasesSame++;
        } else {
            censusBias = packed;
        }
    }

    /** A viewport was set: six doubles packed into the one long the shadow compares. */
    public static void viewportSet(final double originX, final double originY, final double width,
                                   final double height, final double near, final double far) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        final long packed = Double.doubleToLongBits(originX) * 31L + Double.doubleToLongBits(originY) * 17L
                + Double.doubleToLongBits(width) * 13L + Double.doubleToLongBits(height) * 7L
                + Double.doubleToLongBits(near) * 3L + Double.doubleToLongBits(far);
        censusCalls++;
        censusViewports++;
        censusNative++;
        if (censusViewport == packed) {
            censusViewportsSame++;
        } else {
            censusViewport = packed;
        }
    }

    /** A scissor rect was set, packed into the one long the shadow compares. */
    public static void scissorSet(final long x, final long y, final long width, final long height) {
        if (!armed()) {
            return;
        }
        scissors++;
        if (!CENSUS) {
            return;
        }

        final long packed = ((x * 31L + y) * 31L + width) * 31L + height;
        censusCalls++;
        censusScissors++;
        censusNative++;
        if (censusScissor == packed) {
            censusScissorsSame++;
        } else {
            censusScissor = packed;
        }
    }

    /** An indexed draw reached the encoder. */
    public static void drawIndexedPrimitives(final long indexCount, final long instanceCount) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusDrawsIndexed++;
    }

    /** A non-indexed draw reached the encoder. */
    public static void drawPrimitives(final long vertexCount, final long instanceCount) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusDraws++;
    }

    /** One loop over the game's indirect commands, with what it carried and what the loop cost. */
    public static void indirectDrawLoop(final int commands, final long nanos) {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusIndirectLoops++;
        censusIndirectCommands += commands;
        censusIndirectNanos += nanos;
    }

    /** An indirect draw reached the encoder. */
    public static void drawIndirectPrimitives() {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusDrawsIndirect++;
    }

    /** A fence was updated by an encoder. */
    public static void fenceUpdated() {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusFenceUpdates++;
    }

    /** An encoder waited on a fence. */
    public static void fenceWaited() {
        if (!armed()) {
            return;
        }
        if (!CENSUS) {
            return;
        }

        censusCalls++;
        censusFenceWaits++;
    }

    /** Whether a buffer slot already holds this handle and offset, and stores it when it does not. */
    private static boolean sameBuffer(final int stage, final int slot, final long handle, final long offset) {
        if (censusBuffers == null) {
            censusBuffers = new long[CENSUS_STAGES * CENSUS_BUFFER_SLOTS];
            censusTextures = new long[CENSUS_STAGES * CENSUS_TEXTURE_SLOTS];
            censusSamplers = new long[CENSUS_STAGES * CENSUS_SAMPLER_SLOTS];
        }
        if (slot < 0 || slot >= CENSUS_BUFFER_SLOTS) {
            return false;
        }
        final long packed = handle ^ (offset << 1);
        final int index = stage * CENSUS_BUFFER_SLOTS + slot;
        if (censusBuffers[index] == packed) {
            return true;
        }
        censusBuffers[index] = packed;
        return false;
    }

    /** Whether a handle-keyed slot already holds this handle, and stores it when it does not. */
    private static boolean sameHandle(final long[] shadow, final int stage, final int slots, final int slot,
                                      final long handle) {
        if (censusTextures == null) {
            censusBuffers = new long[CENSUS_STAGES * CENSUS_BUFFER_SLOTS];
            censusTextures = new long[CENSUS_STAGES * CENSUS_TEXTURE_SLOTS];
            censusSamplers = new long[CENSUS_STAGES * CENSUS_SAMPLER_SLOTS];
        }
        if (slot < 0 || slot >= slots) {
            return false;
        }
        final int index = stage * slots + slot;
        if (shadow[index] == handle) {
            return true;
        }
        shadow[index] = handle;
        return false;
    }

    /**
     * Forgets every binding the shadow holds, because a new native encoder holds none.
     * <p>
     * Called from {@link #renderEncoderRecreated}, which is the one place that knows an encoder was made rather
     * than joined. A missed clear would read a frame's first bind as a repeat of the last encoder's, which is
     * the one way this census can overstate what could be removed.
     */
    private static void clearBindingShadow() {
        if (censusBuffers == null) {
            return;
        }
        java.util.Arrays.fill(censusBuffers, 0L);
        java.util.Arrays.fill(censusTextures, 0L);
        java.util.Arrays.fill(censusSamplers, 0L);
        censusPipeline = 0L;
        censusDepthStencil = 0L;
        censusCull = -1L;
        censusFill = -1L;
        censusWinding = -1L;
        censusBias = Long.MIN_VALUE;
        censusViewport = Long.MIN_VALUE;
        censusScissor = Long.MIN_VALUE;
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
            // Counted rather than dropped, and split by the thread that paid for it: see the fields above for
            // why a load's compile is the number F4 needs and why a render-thread one is not the same as a
            // worker's. Atomics because the warm-up compiles from three worker threads while the render
            // thread may compile a first draw at the same moment.
            unarmedCompiles.incrementAndGet();
            unarmedCompileNanos.addAndGet(nanos);
            unarmedCompileMaxNanos.accumulateAndGet(nanos, Math::max);

            if (RenderSystem.isOnRenderThread()) {
                unarmedRenderCompiles.incrementAndGet();
                unarmedRenderCompileNanos.addAndGet(nanos);
            }

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
    /** Passes whose target is the largest one this window used, which is the window's own size. */
    private static long fullSizePasses() {
        return passSizes.getOrDefault((passLargestWidth << 32) | (passLargestHeight & 0xFFFFFFFFL), 0L);
    }

    private static long passesTotal() {
        long total = 0L;
        for (long count : passSizes.values()) {
            total += count;
        }
        return total;
    }

    /** The sizes a window drew into, largest first, as `WxH:count` - said rather than summarised. */
    private static String passSizeBreakdown() {
        if (passSizes.isEmpty()) {
            return "none";
        }
        java.util.List<java.util.Map.Entry<Long, Long>> entries = new java.util.ArrayList<>(passSizes.entrySet());
        entries.sort((left, right) -> Long.compare(right.getKey(), left.getKey()));
        StringBuilder out = new StringBuilder();
        for (java.util.Map.Entry<Long, Long> entry : entries) {
            long width = entry.getKey() >>> 32;
            long height = entry.getKey() & 0xFFFFFFFFL;
            out.append(out.length() == 0 ? "" : ",").append(width).append('x').append(height)
                    .append(':').append(entry.getValue());
        }
        return out.toString();
    }

    /** One clear the frame recorded instead of encoding, because the next pass may carry it. */
    public static void clearDeferred() {
        if (!armed()) {
            return;
        }
        clearDeferred++;
    }

    /**
     * One deferred clear a render pass carried as its own load action.
     * <p>
     * Counted apart from the encoders so the trade this makes is readable: a fold removes a clear pass and turns
     * a load into a clear, and the two counters together say how many of a frame's clears took each road.
     */
    public static void clearFolded() {
        if (!armed()) {
            return;
        }
        clearFolded++;
    }

    private static void report() {
        // Read before reset(), which clears the window's first frame along with its counts.
        long windowNanos = System.nanoTime() - windowStartedAt;
        long windowCpuNanos = Math.max(0L, currentThreadCpuNanos() - windowCpuStart);
        windowAllocatedBytes = currentThreadAllocatedBytes() - windowAllocatedStart;
        Metallum.LOGGER.info(
                "frame-probe openers renderPasses={} blitEncoders={} computeEncoders={} clearEncoders={} "
                        + "clearDeferred={} clearFolds={} "
                        + "metal4Frames={} metal4Us={} metal4Draws={} metal4Presents={}",
                renderPassOpeners,
                blitOpeners,
                computeOpeners,
                clearOpeners,
                clearDeferred,
                clearFolded,
                metal4Frames,
                String.format(Locale.ROOT, "%.1f", metal4Frames == 0 ? 0.0 : metal4Nanos / 1000.0 / metal4Frames),
                metal4Draws,
                metal4Presents
        );
        Metallum.LOGGER.info(
                "frame-probe {}/{} windowFrames={} windowMs={} gpuFrames={} gpuM4Feedbacks={} gpuM4FeedbacksTotal={} gpuM4Frames={} gpuM3Ms={} gpuM4Ms={} gpuMs={} "
                        + "selectedGeneration={} executingGeneration={} encoders={} passChanged={} submit={} loadedMiB={} storedMiB={} "
                        + "depthAttachments={} depthLoadedMiB={} depthStoredMiB={} blits={} blittedMiB={} "
                        + "pipeline={} texture={} sampler={} buffer={} viewport={} scissor={} depthBias={} "
                        + "compiles={} compileMs={} "
                        + "unarmedCompiles={} unarmedCompileMs={} unarmedCompileMaxMs={} "
                        + "unarmedRenderCompiles={} unarmedRenderCompileMs={} "
                        + "unarmedFunctions={} unarmedFunctionMs={} unarmedFunctionMaxMs={} "
                        + "unarmedRenderFunctions={} unarmedRenderFunctionMs={} "
                        + "pipelineIdentities={} pipelineKeys={} "
                        + "wallP50={} wallP95={} wallP99={} wallMax={} wallMaxAt={} gpuP50={} gpuP95={} gpuP99={} gpuMax={} "
                        + "gpuM4P50={} gpuM4P95={} gpuM4P99={} gpuM4Max={} "
                        + "windowTicks={} framesPerTick={} frameCpuMs={} allocKiB={} "
                        + "passFullSize={} passSmaller={} passSizes={}",
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
                depthBiases,
                compiles,
                millis(compileNanos),
                unarmedCompiles.get(),
                millis(unarmedCompileNanos.get()),
                String.format(Locale.ROOT, "%.2f", unarmedCompileMaxNanos.get() / 1_000_000.0),
                unarmedRenderCompiles.get(),
                millis(unarmedRenderCompileNanos.get()),
                unarmedFunctions.get(),
                millis(unarmedFunctionNanos.get()),
                String.format(Locale.ROOT, "%.2f", unarmedFunctionMaxNanos.get() / 1_000_000.0),
                unarmedRenderFunctions.get(),
                millis(unarmedRenderFunctionNanos.get()),
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
                percentile(gpuTimes, gpuSamples, 1.00),
                percentile(gpuM4Times, gpuM4Samples, 0.50),
                percentile(gpuM4Times, gpuM4Samples, 0.95),
                percentile(gpuM4Times, gpuM4Samples, 0.99),
                percentile(gpuM4Times, gpuM4Samples, 1.00),
                ticks - windowStartedAtTick,
                String.format(Locale.ROOT, "%.2f",
                        windowFrames / (double) Math.max(1L, ticks - windowStartedAtTick)),
                String.format(Locale.ROOT, "%.2f", windowCpuNanos / 1_000_000.0),
                String.format(Locale.ROOT, "%.1f", windowAllocatedBytes / 1024.0),
                fullSizePasses(),
                passSizes.size() == 0 ? 0L : passesTotal() - fullSizePasses(),
                passSizeBreakdown()
        );
        if (argBufferPasses > 0 || argBufferAllocations > 0 || argBufferSetCalls > 0
                || texelViews > 0 || passDescriptors > 0) {
            Metallum.LOGGER.info(
                    "frame-probe m3cost passes={} layouts={} allocations={} allocationMiB={} "
                            + "setCalls={} setSkipped={} textureWrites={} samplerWrites={} bufferWrites={} "
                            + "useResourceCalls={} draws={} texelViews={} passDescriptors={}",
                    argBufferPasses,
                    argBufferLayouts,
                    argBufferAllocations,
                    String.format(Locale.ROOT, "%.3f", argBufferAllocationBytes / (1024.0 * 1024.0)),
                    argBufferSetCalls,
                    argBufferSetSkipped,
                    argBufferTextureWrites,
                    argBufferSamplerWrites,
                    argBufferBufferWrites,
                    argBufferUseResourceCalls,
                    argBufferDraws,
                    texelViews,
                    passDescriptors
            );
        }
        if (CENSUS && censusCalls > 0) {
            // The native-call census: what the frame asked for, what that became in native setter calls, and how
            // many of those calls carried a value the slot already had. `repeated` is the whole point - it is the
            // share of this backend's call volume that A2 could remove without changing a pixel, and it is
            // measured against the encoder's own shadow rather than argued from the call count.
            Metallum.LOGGER.info(
                    "frame-probe m3native calls={} native={} repeated={} "
                            + "pipeline={} pipelineSame={} depthStencil={} depthStencilSame={} "
                            + "cull={} cullSame={} fill={} fillSame={} winding={} windingSame={} "
                            + "depthBias={} depthBiasSame={} viewport={} viewportSame={} scissor={} scissorSame={} "
                            + "vertexBuffer={} fragmentBuffer={} bufferSame={} "
                            + "vertexTexture={} fragmentTexture={} textureSame={} "
                            + "vertexSampler={} fragmentSampler={} samplerSame={} "
                            + "argBufferSet={} argBufferSkipped={} draws={} drawsIndexed={} drawsIndirect={} "
                            + "indirectLoops={} indirectCommands={} indirectCpuMs={} "
                            + "fencesUpdated={} fencesWaited={}",
                    censusCalls,
                    censusNative,
                    censusTextureSame + censusSamplerSame + censusBufferSame
                            + censusPipelineSame + censusDepthStencilsSame + censusCullsSame + censusFillsSame
                            + censusWindingsSame + censusBiasesSame + censusViewportsSame + censusScissorsSame,
                    censusPipelineCalls,
                    censusPipelineSame,
                    censusDepthStencils,
                    censusDepthStencilsSame,
                    censusCulls,
                    censusCullsSame,
                    censusFills,
                    censusFillsSame,
                    censusWindings,
                    censusWindingsSame,
                    censusBiases,
                    censusBiasesSame,
                    censusViewports,
                    censusViewportsSame,
                    censusScissors,
                    censusScissorsSame,
                    censusVertexBuffers,
                    censusFragmentBuffers,
                    censusBufferSame,
                    censusVertexTextures,
                    censusFragmentTextures,
                    censusTextureSame,
                    censusVertexSamplers,
                    censusFragmentSamplers,
                    censusSamplerSame,
                    argBufferSetCalls,
                    argBufferSetSkipped,
                    censusDraws,
                    censusDrawsIndexed,
                    censusDrawsIndirect,
                    censusIndirectLoops,
                    censusIndirectCommands,
                    String.format(Locale.ROOT, "%.2f", censusIndirectNanos / 1_000_000.0),
                    censusFenceUpdates,
                    censusFenceWaits
            );
        }
        if (uploadCalls > 0) {
            // Said when the frame uploaded anything at all: a scene that does not is not asked the question, and
            // one that does gets the three roads apart - which is the census Phase F is written on.
            //
            // Every field is named for what it counts rather than for its unit, because the comparison reads this
            // line with the same `name=number` scan it reads the window line with, and a field called `MiB` or
            // `cpuMs` would be a number nothing could attribute to a road.
            Metallum.LOGGER.info(
                    "frame-probe uploads uploadCalls={} uploadMiB={} uploadCpuMs={} uploadsToBuffer={}"
                            + " toBufferMiB={} uploadsCopyingBuffer={} copyMiB={} uploadsToTexture={}"
                            + " textureMiB={}",
                    uploadCalls,
                    String.format(Locale.ROOT, "%.3f", uploadBytes / (1024.0 * 1024.0)),
                    String.format(Locale.ROOT, "%.2f", uploadNanos / 1_000_000.0),
                    uploadsToBuffer,
                    String.format(Locale.ROOT, "%.3f", uploadedToBufferBytes / (1024.0 * 1024.0)),
                    uploadCopiesToBuffer,
                    String.format(Locale.ROOT, "%.3f", uploadedCopyBytes / (1024.0 * 1024.0)),
                    uploadsToTexture,
                    String.format(Locale.ROOT, "%.3f", uploadedToTextureBytes / (1024.0 * 1024.0))
            );
        }
        if (encReuseAttempts > 0) {
            Metallum.LOGGER.info(
                    "frame-probe encoderreuse attempts={} reused={} recreated={} reusePercent={} "
                            + "noEncoder={} clear={} color={} depth={} contents={} multiple={} "
                            + "onlyClear={} onlyColor={} onlyDepth={} onlyContents={} onlyNoEncoder={}",
                    encReuseAttempts,
                    encReuseReused,
                    encReuseAttempts - encReuseReused,
                    String.format(Locale.ROOT, "%.1f", 100.0 * encReuseReused / encReuseAttempts),
                    encReuseNoEncoder,
                    encReuseClear,
                    encReuseColor,
                    encReuseDepth,
                    encReuseContents,
                    encReuseMultiple,
                    encReuseSingleClear,
                    encReuseSingleColor,
                    encReuseSingleDepth,
                    encReuseSingleContents,
                    encReuseSingleNoEncoder
            );
        }
        censusClosed = true;
        reset();

        if (frames >= BUDGET) {
            Metallum.LOGGER.info(
                    "Metal frame probe wrote its {} frame(s) and is off; the log holds the run it was armed for",
                    BUDGET
            );
            // Said once, at the end, and never in a window line: these are the two waits a frame's rate is
            // made of, and neither moves frame to frame in a way an average would hide. Read through the
            // empty-safe percentile: a line that can fail to appear is a line whose absence reads as "no
            // wait", which is the one reading this measurement may not produce.
            Metallum.LOGGER.info(
                    "frame-probe waits drawable calls={} p50={}ms p95={}ms max={}ms total={}ms; "
                            + "submitWindow calls={} p50={}ms p95={}ms max={}ms total={}ms",
                    drawableWaits,
                    emptySafePercentile(drawableWaitTimes, drawableWaits, 0.50),
                    emptySafePercentile(drawableWaitTimes, drawableWaits, 0.95),
                    emptySafePercentile(drawableWaitTimes, drawableWaits, 1.00),
                    String.format(Locale.ROOT, "%.2f", drawableWaitTotal),
                    submitWindowWaits,
                    emptySafePercentile(submitWindowWaitTimes, submitWindowWaits, 0.50),
                    emptySafePercentile(submitWindowWaitTimes, submitWindowWaits, 0.95),
                    emptySafePercentile(submitWindowWaitTimes, submitWindowWaits, 1.00),
                    String.format(Locale.ROOT, "%.2f", submitWindowWaitTotal)
            );
        }
    }

    /** One drawable acquisition, in nanoseconds: the wait before a frame can be drawn at all. */
    public static void drawableWait(final long nanos) {
        if (!armed()) {
            return;
        }
        drawableWaitTimes = record(drawableWaitTimes, drawableWaits, nanos / 1_000_000.0);
        drawableWaits++;
        drawableWaitTotal += nanos / 1_000_000.0;
    }

    /** One frame-tail wait on the in-flight submission window, in nanoseconds. */
    public static void submitWindowWait(final long nanos) {
        if (!armed()) {
            return;
        }
        submitWindowWaitTimes = record(submitWindowWaitTimes, submitWindowWaits, nanos / 1_000_000.0);
        submitWindowWaits++;
        submitWindowWaitTotal += nanos / 1_000_000.0;
    }

    /** The percentile of a sample set that may be empty, because an absent line reads as "no wait". */
    private static String emptySafePercentile(final double[] samples, final int count, final double quantile) {
        return count == 0 ? "0.00" : percentile(samples, count, quantile);
    }

    private static double[] record(double[] samples, final int count, final double value) {
        double[] grown = count == samples.length ? java.util.Arrays.copyOf(samples, samples.length * 2) : samples;
        grown[count] = value;
        return grown;
    }

    /**
     * One Metal function compile, timed around the device call alone, counted exactly as a pipeline is.
     * <p>
     * Called from the Metal 3 road's function cache, which is the only place a function is made. Metal 4's is
     * left alone deliberately: that generation is frozen, and a counter on it would be work done for a path no
     * decision here is about.
     */
    public static void functionCompiled(final long nanos) {
        unarmedFunctions.incrementAndGet();
        unarmedFunctionNanos.addAndGet(nanos);
        unarmedFunctionMaxNanos.accumulateAndGet(nanos, Math::max);

        if (RenderSystem.isOnRenderThread()) {
            unarmedRenderFunctions.incrementAndGet();
            unarmedRenderFunctionNanos.addAndGet(nanos);
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
        clearDeferred = 0;
        clearFolded = 0;
        uploadCalls = 0;
        uploadBytes = 0L;
        uploadNanos = 0L;
        uploadsToBuffer = 0;
        uploadedToBufferBytes = 0L;
        uploadCopiesToBuffer = 0;
        uploadedCopyBytes = 0L;
        uploadsToTexture = 0;
        uploadedToTextureBytes = 0L;
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
        depthBiases = 0;
        // The tick counter is *not* reset: it is a per-process count and a window's span is a difference of two
        // of its values, so clearing it here would make a second window's first frame its own zero.
        argBufferPasses = 0;
        argBufferLayouts = 0;
        argBufferAllocations = 0;
        argBufferAllocationBytes = 0L;
        argBufferSetCalls = 0;
        argBufferSetSkipped = 0;
        argBufferTextureWrites = 0;
        argBufferSamplerWrites = 0;
        argBufferBufferWrites = 0;
        argBufferUseResourceCalls = 0;
        argBufferDraws = 0;
        texelViews = 0;
        passDescriptors = 0;
        encReuseAttempts = 0;
        encReuseReused = 0;
        encReuseNoEncoder = 0;
        encReuseClear = 0;
        encReuseColor = 0;
        encReuseDepth = 0;
        encReuseContents = 0;
        encReuseSingleClear = 0;
        encReuseSingleColor = 0;
        encReuseSingleDepth = 0;
        encReuseSingleContents = 0;
        encReuseSingleNoEncoder = 0;
        encReuseMultiple = 0;
        // The census's counters reset with the window; its *shadow* does not, because the shadow is a fact about
        // the native encoder still open and the next window's first bind has to be compared against it.
        censusCalls = 0;
        censusNative = 0;
        censusPipelineCalls = 0;
        censusPipelineSame = 0;
        censusDepthStencils = 0;
        censusDepthStencilsSame = 0;
        censusCulls = 0;
        censusCullsSame = 0;
        censusFills = 0;
        censusFillsSame = 0;
        censusWindings = 0;
        censusWindingsSame = 0;
        censusBiases = 0;
        censusBiasesSame = 0;
        censusViewports = 0;
        censusViewportsSame = 0;
        censusScissors = 0;
        censusScissorsSame = 0;
        censusVertexBuffers = 0;
        censusFragmentBuffers = 0;
        censusBufferSame = 0;
        censusVertexTextures = 0;
        censusFragmentTextures = 0;
        censusTextureSame = 0;
        censusVertexSamplers = 0;
        censusFragmentSamplers = 0;
        censusSamplerSame = 0;
        censusDraws = 0;
        censusDrawsIndexed = 0;
        censusDrawsIndirect = 0;
        censusFenceUpdates = 0;
        censusFenceWaits = 0;
        passLargestWidth = 0L;
        passLargestHeight = 0L;
        passSizes.clear();
        censusIndirectLoops = 0;
        censusIndirectCommands = 0;
        censusIndirectNanos = 0L;
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
