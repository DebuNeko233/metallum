package com.metallum.render;

import com.metallum.Metallum;
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

    /** The entry point to the new command structure, as the SDK's {@code MTLDevice.h} spells it. */
    private static final String QUEUE_SELECTOR = "newMTL4CommandQueue";

    private static Boolean available;
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

        available = Boolean.TRUE;
        reason = "the device has the family and answers to " + QUEUE_SELECTOR;
        Metallum.LOGGER.info("Metal 4 core API: available, {}", reason);
        return true;
    }

    /** Why the last answer came out the way it did, for a log line or a report. */
    public static String reason() {
        return reason;
    }
}
