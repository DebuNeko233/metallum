package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.render.execution.MetalApiGeneration;

/**
 * Which generation was <em>selected</em> and which one <em>executes</em>, said once and remembered.
 * <p>
 * <strong>The two are not the same fact, and this class used to hold only one of them.</strong> Choosing
 * between Metal 3 and Metal 4 from device capabilities, Objective-C selectors and MetalFX parity is the
 * runtime selector's work; the executing generation is the one whose frame path actually carries the frames,
 * and until Metal 4 has a frame path the answer to that one is Metal 3 whatever was selected. A single field
 * named as the executing generation but written with the selection is how a session encoding every frame
 * through Metal 3's command buffer came to be reported as Metal 4: a reader asking "which API is in use" was
 * answered with "which API the device could use".
 * <p>
 * Both facts are recorded at the one place that knows both - the device, after the execution services have
 * been built from the decision - rather than by the selector, which decides and cannot know what executes.
 * <p>
 * Nothing here reads a chip name. Apple Silicon reports the same families across its generations, so a
 * selector that keyed off "M4" or "M5" would be a table of hardware this engine has never run on.
 */
public final class MetalExecutionTelemetry {

    /** Null until a device has recorded one, so a reader with no device shows nothing rather than a guess. */
    private static volatile MetalApiGeneration selected;

    private static volatile MetalApiGeneration executing;

    private static volatile String reason =
            "the frame is encoded through Metal 3's command buffer; the runtime selector owns this choice";

    private static volatile boolean said;

    private MetalExecutionTelemetry() {
    }

    /**
     * Records what was selected, what executes, and why. Said once, the first time it is recorded.
     *
     * @param selected  the generation the selector chose
     * @param executing the generation whose frame path is carrying this session's frames
     * @param why       the selector's own sentence, printed with both facts
     */
    public static void record(final MetalApiGeneration selected, final MetalApiGeneration executing,
                              final String why) {
        MetalExecutionTelemetry.selected = selected;
        MetalExecutionTelemetry.executing = executing;
        reason = why;
        if (!said) {
            said = true;
            say();
        }
    }

    /** The one line, deterministic and grep-able, which a run's log carries whether or not F3 is pressed. */
    public static void say() {
        Metallum.LOGGER.info("Metal execution: {} selected, {} executes ({})",
                selectedToken(), executingToken(), reason);
    }

    /** The generation the selector chose, or null before one has been recorded. */
    public static MetalApiGeneration selected() {
        return selected;
    }

    /** The generation whose frame path carries the frames, or null before one has been recorded. */
    public static MetalApiGeneration executing() {
        return executing;
    }

    /** The selected generation's token, or the empty string before one has been recorded. */
    public static String selectedToken() {
        MetalApiGeneration known = selected;
        return known == null ? "" : known.token();
    }

    /** The executing generation's token, or the empty string before one has been recorded. */
    public static String executingToken() {
        MetalApiGeneration known = executing;
        return known == null ? "" : known.token();
    }

    public static String reason() {
        return reason;
    }
}
