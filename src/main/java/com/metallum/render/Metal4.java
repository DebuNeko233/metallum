package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.metal4.MTL4Probe;
import com.metallum.mtl.MTLDevice;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Whether this device has the Metal 4 core API, asked once and remembered.
 * <p>
 * Metal 4 is a parallel API surface rather than a replacement: the {@code MTL4}-prefixed types sit beside
 * the ones this backend uses today, Apple supports it from M1 and A14 onward, and the framework's own
 * guidance is to detect support, use the new objects where they exist and fall back otherwise. This class
 * is that detection and nothing else - no frame path depends on it, and the answer is a fact about the
 * device rather than a preference.
 * <p>
 * Two questions, both asked of the device, because Apple documents both and neither is a version table:
 * <ul>
 *   <li>{@code supportsFamily:} with {@code MTLGPUFamilyMetal4}, whose value 5002 is the SDK's own
 *       ({@code MTLDevice.h}: {@code MTLGPUFamilyMetal4 API_AVAILABLE(macos(26.0), ios(26.0)) = 5002});</li>
 *   <li>whether the device answers to the Metal 4 entry point {@code newMTL4CommandQueue}, asked with
 *       {@code respondsToSelector:} for the reason above.</li>
 * </ul>
 * A negative answer is cached like a positive one: this is asked at device creation, and a session cannot
 * change its GPU.
 */
@Environment(EnvType.CLIENT)
public final class Metal4 {

    /** {@code MTLGPUFamilyMetal4}, as this machine's SDK defines it. */
    private static final long FAMILY_METAL4 = 5002L;

    /** {@code MTLGPUFamilyMetal3}, as the SDK defines it. */
    private static final long FAMILY_METAL3 = 5001L;

    /** The entry point to the new command structure, as the SDK's {@code MTLDevice.h} spells it. */
    private static final String QUEUE_SELECTOR = "newMTL4CommandQueue";

    private static Boolean available;

    /** The two things the startup probe proved, kept for the capability record. */
    private static boolean makeAndSubmit;
    private static boolean bindAndDraw;
    private static boolean metal3;
    private static String reason = "not asked yet";

    private Metal4() {
    }

    /**
     * Asks the device whether it has the Metal 4 core API, and remembers the answer.
     *
     * @param device the device binding, which is what both questions are asked of
     * @return whether the new types can be used
     */
    public static boolean available(final MTLDevice device) {
        if (available != null) {
            return available;
        }

        if (device == null) {
            available = Boolean.FALSE;
            reason = "there is no device to ask";
            return false;
        }

        // Asked either way, because the answer is worth a line of its own where the Metal 4 answer is no:
        // a reader wants to know which generation of the API this device runs, not only that it is not the
        // newest one.
        metal3 = device.supportsFamily(FAMILY_METAL3);

        if (!device.supportsFamily(FAMILY_METAL4)) {
            available = Boolean.FALSE;
            reason = "the device does not have the Metal 4 family";
            Metallum.LOGGER.info("Metal 4 core API: unavailable, {}", reason);
            return false;
        }

        if (!device.respondsTo(QUEUE_SELECTOR)) {
            available = Boolean.FALSE;
            reason = "the device has the family but answers to no " + QUEUE_SELECTOR;
            Metallum.LOGGER.warn("Metal 4 core API: unavailable, {}", reason);
            return false;
        }

        // A device that answers yes can still refuse to make the objects, so one of each is made and let
        // go here - the queue, an allocator and a command buffer begun on it - which is what makes this a
        // skeleton rather than a support query. Nothing in a frame path creates one.
        if (!MTL4Probe.canMakeAndSubmit(device)) {
            available = Boolean.FALSE;
            reason = "the device has the family but would not make and take the new command objects";
            Metallum.LOGGER.warn("Metal 4 core API: unavailable, {}", reason);
            return false;
        }

        // And the question the migration of the frame's own passes turns on: a Metal 4 encoder has no
        // binding methods, so a pass reads a buffer through an argument table, and the table binds a buffer
        // by address. The engine's own clear pass is drawn on the new path with its uniform bound that way
        // and the pixel it produced is read back, so this is whether the pass *used* the binding rather
        // than whether the calls were accepted.
        // Asked once and once more if the first answer is no, because the first probe of a process can fail
        // at stage `pixel` and no later one ever has (measured: every failure in 160 cold processes was its
        // first attempt, and 1100 later probes passed). The capability record is a fact about the device, and
        // the first attempt is logged by the probe whether or not the retry succeeds.
        boolean binding = MTL4Probe.canBindAndDrawPersistently(device);

        // The cold/warm question needs the probe called more than once in one process, which is the one thing
        // the client never does: the answer is cached here and every capability record reads the cache. With
        // `-Dmetallum.probeRepeat=N` the probe is run N more times and each answer is written out with its
        // stage, so "the first call in a process" and "the calls after it" become comparable without a
        // 600-frame arm - and the intermittent false negative this is chasing (two observations in fourteen
        // arms, both on a session's first arm) either shows up in the first position or it does not.
        String repeat = System.getProperty("metallum.probeRepeat", "0");
        int repeats = Integer.parseInt(repeat);
        for (int attempt = 1; attempt <= repeats; attempt++) {
            boolean answer = MTL4Probe.canBindAndDraw(device);
            Metallum.LOGGER.info("Metal 4 probe repeat {}/{}: answer={} stage={} reason={}",
                    attempt, repeats, answer, MTL4Probe.lastFailureStage(), MTL4Probe.lastFailure());
        }
        makeAndSubmit = true;
        bindAndDraw = binding;

        available = Boolean.TRUE;
        reason = "the device has the family, answers to " + QUEUE_SELECTOR
                + ", and a queue, an allocator and a command buffer carrying a render pass were made, "
                + "encoded, submitted and released"
                + (binding
                ? ", and two passes whose resources were bound through argument tables drew what they were "
                        + "told to - a uniform by GPU address, and a vertex buffer by address and stride"
                : ", but a pass whose resources were bound through an argument table did not draw what it was "
                        + "told to: " + "at stage " + MTL4Probe.lastFailureStage() + ": " + MTL4Probe.lastFailure());
        Metallum.LOGGER.info("Metal 4 core API: available, {}", reason);
        if (binding) {
            Metallum.LOGGER.info("Metal 4 sampler ceiling: {}", MTL4Probe.samplerCeiling(device));
        }

        return true;
    }

    /**
     * The cached answer, for a caller that has no device to hand.
     * <p>
     * False before the question has been asked, which is the failing-closed direction: a capability a
     * caller may act on is never reported before the device has said so.
     *
     * @return whether the device creation that ran answered yes
     */
    public static boolean isAvailable() {
        return Boolean.TRUE.equals(available);
    }

    /**
     * The generation of the Metal API this device runs, as one word.
     * <p>
     * Apple has no "API version" to ask for: what a device can run is expressed as families, so the newest
     * family it answers for is the generation. Empty before a device has been asked, which is what a reader
     * with no device should see rather than a guess.
     *
     * @return {@code Metal 4}, {@code Metal 3}, {@code Metal} or the empty string
     */
    public static String generation() {
        if (Boolean.TRUE.equals(available)) {
            return "Metal 4";
        }
        if (available == null) {
            return "";
        }
        return metal3 ? "Metal 3" : "Metal";
    }

    /** Whether the device that was asked made a queue, an allocator and a command buffer and submitted one. */
    public static boolean canMakeAndSubmit() {
        return makeAndSubmit;
    }

    /** Whether the same device bound a uniform by address through a table and drew what it was told to. */
    public static boolean canBindAndDraw() {
        return bindAndDraw;
    }

    /** Why the last answer came out the way it did, for a log line or a report. */
    public static String reason() {
        return reason;
    }
}
