package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.MTL4Probe;
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

        available = Boolean.TRUE;
        reason = "the device has the family, answers to " + QUEUE_SELECTOR
                + ", and a queue, an allocator and a command buffer carrying a render pass were made, "
                + "encoded, submitted and released";
        Metallum.LOGGER.info("Metal 4 core API: available, {}", reason);
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

    /** Why the last answer came out the way it did, for a log line or a report. */
    public static String reason() {
        return reason;
    }
}
