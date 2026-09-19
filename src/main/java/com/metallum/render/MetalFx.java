package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * Whether this device can scale a frame with MetalFX, and why not when it cannot.
 *
 * <p>
 * MetalFX is a framework of its own rather than a part of Metal, and this backend reaches Objective-C
 * through {@code objc_getClass}, which sees only the images that are already loaded. Loading the image
 * is therefore what makes the classes visible at all - the same {@code dlopen} the runtime-interface
 * package already performs for Metal, Foundation and QuartzCore, asked through
 * {@link ObjC#optionalLibrary} because a system without MetalFX is a system this engine runs on rather
 * than a failure.
 *
 * <p>
 * <strong>Availability is asked of the API and never of a version.</strong> Apple's own question is
 * {@code +[MTLFXSpatialScalerDescriptor supportsDevice:]}, which is false on a GPU that cannot run the
 * scaler whatever the system version says; a framework that is not installed and a class that does not
 * answer are the two other ways this returns false. The answer is asked once per device and kept, and
 * it is said out loud, because "this Mac cannot do it" and "this build cannot do it" are different
 * sentences and the log is where a reader is owed the right one.
 *
 * <p>
 * Nothing here decides whether MetalFX is <em>used</em>: that is the pack-facing side's choice, made
 * through the capability it asks this backend for. What this class answers is the hardware question
 * alone.
 */
@Environment(EnvType.CLIENT)
public final class MetalFx {

    /** The framework's image. Null where the system does not have one. */
    private static final boolean LOADED =
            ObjC.optionalLibrary("/System/Library/Frameworks/MetalFX.framework/MetalFX") != null;

    private static final Msg SUPPORTS_DEVICE = Msg.of("supportsDevice:", JAVA_LONG, ADDRESS);

    /** The descriptor class, once the framework is loaded, or null where it is not there. */
    private static MemorySegment scalerClass;

    private static boolean asked;
    private static boolean supported;
    private static String reason = "not asked yet";

    private MetalFx() {
    }

    /**
     * Whether the spatial scaler can be made on this device.
     *
     * @param device the Metal device handle, which is the argument Apple's own question takes
     */
    public static boolean spatialSupported(final MemorySegment device) {
        if (asked) {
            return supported;
        }

        asked = true;
        if (!LOADED) {
            reason = "MetalFX.framework is not installed on this system";
            return false;
        }

        scalerClass = classOrNull("MTLFXSpatialScalerDescriptor");
        if (ObjC.isNil(scalerClass)) {
            reason = "MetalFX.framework is loaded and has no MTLFXSpatialScalerDescriptor";
            return false;
        }

        if (ObjC.isNil(device)) {
            reason = "there is no device to ask";
            return false;
        }

        supported = SUPPORTS_DEVICE.sendLong(scalerClass, device) != 0L;
        reason = supported ? "the device supports it" : "the device does not support the spatial scaler";
        Metallum.LOGGER.info("MetalFX spatial scaling: {}, {}",
                supported ? "available" : "unavailable", reason);

        return supported;
    }

    /** Why the last answer came out the way it did, for a log line or a settings screen. */
    public static String reason() {
        return reason;
    }

    /**
     * A class by name, or nil. {@code ObjC.clazz} throws for a name nothing answers to, which is right
     * for the classes this backend cannot work without and wrong for one it is only asking about.
     */
    private static MemorySegment classOrNull(final String name) {
        try {
            return ObjC.clazz(name);
        } catch (Throwable missing) {
            return MemorySegment.NULL;
        }
    }
}
