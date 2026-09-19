package com.metallum.render;

import com.metallum.Metallum;

/**
 * Which execution generation this session is running, said once and remembered.
 * <p>
 * <strong>This records a decision; it does not make one.</strong> Choosing between Metal 3 and Metal 4 from
 * device capabilities, Objective-C selectors and MetalFX parity is the runtime selector's work, and until
 * that exists there is one honest answer: the frame is encoded through Metal 3's command buffer, and the
 * new path carries the present when it is asked to. The point of the recorder is that the answer is said
 * out loud, in one deterministic line, and that the frame probe can print it beside the numbers - a run
 * whose profile does not say which generation produced it cannot be compared with anything.
 * <p>
 * Nothing here reads a chip name. Apple Silicon reports the same families across its generations, so a
 * selector that keyed off "M4" or "M5" would be a table of hardware this engine has never run on.
 */
public final class MetalExecutionTelemetry {

    private static volatile MetalExecutionGeneration generation = MetalExecutionGeneration.METAL_3;

    private static volatile String reason =
            "the frame is encoded through Metal 3's command buffer; the runtime selector owns this choice";

    private static volatile boolean said;

    private MetalExecutionTelemetry() {
    }

    /** Records which generation executes, and why, where something knows. Said once, the first time. */
    public static void selected(final MetalExecutionGeneration selected, final String why) {
        generation = selected;
        reason = why;
        if (!said) {
            said = true;
            say();
        }
    }

    /** The one line, deterministic and grep-able, which a run's log carries whether or not F3 is pressed. */
    public static void say() {
        Metallum.LOGGER.info("Metal execution: {} selected ({})", generation.token(), reason);
    }

    public static MetalExecutionGeneration generation() {
        return generation;
    }

    /** The same token the probe line carries. */
    public static String token() {
        return generation.token();
    }

    public static String reason() {
        return reason;
    }
}
