package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.MTLTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.fabricmc.loader.api.FabricLoader;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

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
 * <strong>Off unless asked for.</strong> {@code -Dmetallum.probeFrames=true} arms it, and a
 * {@code metallum/probe-frames} file in the game directory says the same thing, because a
 * launcher's arguments are a place a session cannot reach while a file in the game directory is one
 * it can. {@code -Dmetallum.frameProbeBudget=N} bounds the frames observed, six hundred by default,
 * and a line covers six hundred frames rather than one: an unbounded per-frame probe is a way to
 * fill a disk rather than a way to answer a question. The marker is asked once and the answer kept,
 * so it arms a launch rather than a frame.
 * <p>
 * Nothing here observes anything but counts. Every entry point below returns on its guard before it
 * touches an attachment, a timestamp or a texture, so an unarmed launch pays one boolean field read
 * per hook and no Metal query at all.
 */
@Environment(EnvType.CLIENT)
public final class MetalFrameProbe {

    /** Whether the flag asked for it. Read once, at class load, as every property in this package is. */
    private static final boolean FLAG = Boolean.getBoolean("metallum.probeFrames");

    /** How many frames to observe before stopping, so an armed launch cannot fill a disk by accident. */
    private static final int BUDGET = Integer.getInteger("metallum.frameProbeBudget", 600);

    /** How many frames one line covers. A line a frame would be a load test, not a reading. */
    private static final int REPORT_FRAMES = 600;

    /** The directory a marker beside the game's own files is looked for in. */
    private static final String MARKER_DIRECTORY = "metallum";

    private static final String MARKER = "probe-frames";

    /** The marker file's answer, held after the first ask: a stat per frame is not a probe cost. */
    @Nullable
    private static Boolean armedFromFile;

    /** Frames observed since the probe armed; the budget is spent when this reaches it. */
    private static int frames;

    private static boolean announced;

    /**
     * The window's counts, reset by every line so that a line describes its own frames and no
     * others. They are read and written from the render thread alone, like the encoder state they
     * describe.
     */
    private static int windowFrames;
    private static int encoders;
    private static int passChanged;
    private static int submitEnds;
    private static long loadedBytes;
    private static long storedBytes;
    private static int pipelines;
    private static int textures;
    private static int samplers;
    private static int buffers;
    private static int viewports;
    private static int scissors;

    /** Session totals: pipeline creation is not a per-frame event, so it is read as a session cost. */
    private static int compiles;
    private static long compileNanos;

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
     * one per binding.
     */
    public static void frameSubmitted() {
        if (!armed()) {
            return;
        }

        frames++;
        windowFrames++;
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
    public static void pipelineCompiled(final long nanos) {
        if (!armed()) {
            return;
        }

        compiles++;
        compileNanos += nanos;
    }

    /**
     * Writes the window and starts the next one. The last frame of the budget writes the final line
     * and turns the probe off for good, so an armed launch stops by itself.
     */
    private static void report() {
        Metallum.LOGGER.info(
                "frame-probe {}/{} windowFrames={} encoders={} passChanged={} submit={} loadedMiB={} storedMiB={} "
                        + "pipeline={} texture={} sampler={} buffer={} viewport={} scissor={} compiles={} compileMs={}",
                frames,
                BUDGET,
                windowFrames,
                encoders,
                passChanged,
                submitEnds,
                mebibytes(loadedBytes),
                mebibytes(storedBytes),
                pipelines,
                textures,
                samplers,
                buffers,
                viewports,
                scissors,
                compiles,
                millis(compileNanos)
        );
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
        encoders = 0;
        passChanged = 0;
        submitEnds = 0;
        loadedBytes = 0L;
        storedBytes = 0L;
        pipelines = 0;
        textures = 0;
        samplers = 0;
        buffers = 0;
        viewports = 0;
        scissors = 0;
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

    private static String millis(final long nanos) {
        return String.format(Locale.ROOT, "%.2f", nanos / 1_000_000.0);
    }
}
