package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * The options a Metal 4 commit carries, which is where a commit's own GPU timing comes from.
 * <p>
 * A Metal 4 queue reports nothing back to the caller: {@code commit:count:} returns void, the completion
 * semantics a Metal 3 command buffer carries do not exist, and the only account of when the GPU ran a
 * submission is the feedback handler this object is given - {@code addFeedbackHandler:} takes a block
 * Metal invokes with an {@code MTL4CommitFeedback}, whose {@code GPUStartTime} and {@code GPUEndTime} are
 * the same two host times the Metal 3 road reads from {@code MTLCommandBuffer}. Without this, a Metal 4
 * frame's GPU time is invisible to the frame probe and the two paths cannot be compared at all.
 * <p>
 * Every selector is asked for first, like the rest of the new path: a factory is an error, not a nil, when
 * an object does not implement it.
 */
@Environment(EnvType.CLIENT)
public final class MTL4CommitOptions implements AutoCloseable {

    /** The class this wraps, as the SDK names it. */
    private static final String CLASS = "MTL4CommitOptions";

    private static final Msg NEW = Msg.of("new", ADDRESS);
    private static final Msg ADD_FEEDBACK_HANDLER = Msg.ofVoid("addFeedbackHandler:", ADDRESS);
    private static final Msg GPU_START_TIME = Msg.of("GPUStartTime", JAVA_DOUBLE);
    private static final Msg GPU_END_TIME = Msg.of("GPUEndTime", JAVA_DOUBLE);
    private static final Msg ERROR = Msg.of("error", ADDRESS);
    private static final Msg LOCALIZED_DESCRIPTION = Msg.of("localizedDescription", ADDRESS);
    private static final Msg CODE = Msg.of("code", JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private final MemorySegment handle;

    private MTL4CommitOptions(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * Makes the options, or null where this device has no such class.
     *
     * @return the options, or null
     */
    @Nullable
    public static MTL4CommitOptions create() {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment made;
            try {
                made = NEW.sendPtr(ObjC.clazz(CLASS));
            } catch (Throwable missing) {
                Metallum.LOGGER.warn("Metal 4 commit options: {} is not there ({})", CLASS, missing.getMessage());
                return null;
            }

            if (ObjC.isNil(made) || !responds(made, "addFeedbackHandler:")) {
                ObjC.release(made);
                return null;
            }

            return new MTL4CommitOptions(made);
        }
    }

    /**
     * Registers the block Metal calls with this commit's feedback.
     *
     * @param block a block made by {@code ObjCBlock}, whose argument is the feedback object
     * @return whether the handler was registered
     */
    public boolean feedbackHandler(final MemorySegment block) {
        if (ObjC.isNil(block)) {
            return false;
        }

        ADD_FEEDBACK_HANDLER.send(handle, block);
        return true;
    }

    /** One commit's GPU time in milliseconds, read from the feedback the handler was given. */
    public static double gpuMillis(final MemorySegment feedback) {
        if (ObjC.isNil(feedback) || !responds(feedback, "GPUStartTime") || !responds(feedback, "GPUEndTime")) {
            return 0.0;
        }

        double started = GPU_START_TIME.sendDouble(feedback);
        double ended = GPU_END_TIME.sendDouble(feedback);
        // Apple: both are "0.0 until the GPU finishes running the command buffer", so a pair of zeroes is a
        // reading that has not happened rather than a frame that took no time.
        if (started <= 0.0 || ended <= started) {
            return 0.0;
        }

        return (ended - started) * 1000.0;
    }

    /**
     * The GPU's own account of a submission that went wrong, or null where it reported none.
     * <p>
     * This is the one place the new command model says anything about a fault. A Metal 3 command buffer carries
     * an {@code errorDescription} the caller can read after it completes; a Metal 4 queue reports nothing back
     * unless the commit was given options, and then this field is the account: "A description of an error when
     * the GPU encounters an issue as it runs the committed command buffers". Without it a GPU fault reaches the
     * frame path as a completion value that never arrives - a lifetime sentence for a machine-level fault, which
     * is what a forced Metal 4 run reported until this existed.
     */
    @Nullable
    public static String error(final MemorySegment feedback) {
        if (ObjC.isNil(feedback) || !responds(feedback, "error")) {
            return null;
        }
        MemorySegment failure = ERROR.sendPtr(feedback);
        if (ObjC.isNil(failure)) {
            return null;
        }
        String words = ObjC.javaString(LOCALIZED_DESCRIPTION.sendPtr(failure));
        return words + " (code " + CODE.sendLong(failure) + ")";
    }

    public MemorySegment handle() {
        return handle;
    }

    @Override
    public void close() {
        if (!ObjC.isNil(handle)) {
            ObjC.release(handle);
        }
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }
}
