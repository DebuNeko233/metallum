package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.MTLFXSpatialScaler;
import com.metallum.mtl.MTLFXSpatialScalerDescriptor;
import com.metallum.mtl.MTLPixelFormat;
import com.metallum.mtl.MTLTexture;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.util.LinkedHashMap;
import java.util.Map;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * MetalFX spatial scaling: whether this system and this device can do it, and the one scaler per
 * configuration that does.
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
 * answer are the two other ways this returns false. The answer is asked once per device and kept, and it
 * is said out loud, because "this Mac cannot do it" and "this build cannot do it" are different
 * sentences and the log is where a reader is owed the right one.
 *
 * <p>
 * <strong>One scaler per configuration, not one per frame.</strong> Making a scaler compiles its own
 * pipeline, so the cache is keyed by everything that would make a different one - both sizes, both pixel
 * formats and the colour processing mode - and a configuration whose scaler could not be made is
 * remembered as refused rather than attempted again every frame.
 */
@Environment(EnvType.CLIENT)
public final class MetalFx {

    /** The framework's image, and whether the system has one at all. */
    private static final boolean LOADED =
            ObjC.optionalLibrary("/System/Library/Frameworks/MetalFX.framework/MetalFX") != null;

    private static final Msg SUPPORTS_DEVICE = Msg.of("supportsDevice:", JAVA_LONG, ADDRESS);

    /** The descriptor class, once the framework is loaded, or null where it is not there. */
    private static MemorySegment scalerClass;

    /** What one cached scaler was made for. Every field changes what the scaler is. */
    private record Configuration(
            int inputWidth,
            int inputHeight,
            int outputWidth,
            int outputHeight,
            long colorFormat,
            long outputFormat,
            MTLFXSpatialScalerDescriptor.ColorProcessingMode colorProcessingMode
    ) {
    }

    private static final Map<Configuration, MTLFXSpatialScaler> scalers = new LinkedHashMap<>();
    private static final Map<Configuration, Boolean> refused = new LinkedHashMap<>();

    private static boolean asked;
    private static boolean supported;
    private static String reason = "not asked yet";

    private MetalFx() {
    }

    /**
     * Whether the spatial scaler can be made on this device. Asked once, at device creation.
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
        if (!supported) {
            reason = "the device does not support the spatial scaler";
            Metallum.LOGGER.info("MetalFX spatial scaling: unavailable, {}", reason);
            return false;
        }

        // A device that answers yes can still refuse a scaler, and the two are worth telling apart before
        // a frame depends on either: this makes one for a plausible configuration, says which spelling the
        // factory answered to, and lets it go. It is the one place the selector question is answered, and
        // a wrong selector is a nil scaler with no error anywhere rather than a failure to notice.
        reason = "the device supports it";
        try (MTLFXSpatialScalerDescriptor probe = MTLFXSpatialScalerDescriptor.create(
                scalerClass, 1280, 720, 1920, 1080,
                MTLPixelFormat.RGBA8Unorm.value, MTLPixelFormat.RGBA8Unorm.value,
                MTLFXSpatialScalerDescriptor.ColorProcessingMode.PERCEPTUAL)) {
            String factory = probe == null ? "" : probe.factorySelector();
            if (factory.isEmpty()) {
                supported = false;
                reason = "the descriptor answers to neither spelling of its factory";
                Metallum.LOGGER.warn("MetalFX spatial scaling: unavailable, {}", reason);
                return false;
            }

            MTLFXSpatialScaler made = probe.makeSpatialScaler(device);
            if (made == null) {
                supported = false;
                reason = "a scaler for a plain colour pair could not be made";
                Metallum.LOGGER.warn("MetalFX spatial scaling: unavailable, {}", reason);
                return false;
            }
            made.close();
            Metallum.LOGGER.info("MetalFX spatial scaling: available, {}, factory {}", reason, factory);
        }

        return true;
    }

    /**
     * Encodes one spatial upscale of {@code color} into {@code output} on this command buffer.
     * <p>
     * The content rectangle is how much of the input texture really holds this frame: the texture is
     * allocated for the largest size asked for and the scale in force can be smaller. Every failure -
     * no scaler for this configuration, a refused one, a scaler that cannot be made now - answers false
     * and leaves the caller on whatever it does without this, because a frame is never left half scaled.
     *
     * @param device        the Metal device handle
     * @param commandBuffer the frame's command buffer
     * @param color         the texture drawn at the scaled size
     * @param output        the texture the picture is brought back into
     * @return whether the encode happened
     */
    public static boolean scale(
            final MemorySegment device,
            final MemorySegment commandBuffer,
            final MetalGpuTexture color,
            final MetalGpuTexture output,
            final int contentWidth,
            final int contentHeight
    ) {
        if (!spatialSupported(device) || ObjC.isNil(commandBuffer)) {
            return false;
        }

        Configuration configuration = new Configuration(
                (int) MTLTexture.width(color.nativeHandle()), (int) MTLTexture.height(color.nativeHandle()),
                (int) MTLTexture.width(output.nativeHandle()), (int) MTLTexture.height(output.nativeHandle()),
                color.mtlPixelFormat().value, output.mtlPixelFormat().value,
                MTLFXSpatialScalerDescriptor.ColorProcessingMode.PERCEPTUAL);

        if (Boolean.TRUE.equals(refused.get(configuration))) {
            return false;
        }

        MTLFXSpatialScaler scaler = scalers.get(configuration);
        if (scaler == null) {
            try (MTLFXSpatialScalerDescriptor descriptor = MTLFXSpatialScalerDescriptor.create(
                    scalerClass,
                    configuration.inputWidth(), configuration.inputHeight(),
                    configuration.outputWidth(), configuration.outputHeight(),
                    configuration.colorFormat(), configuration.outputFormat(),
                    configuration.colorProcessingMode())) {
                scaler = descriptor == null ? null : descriptor.makeSpatialScaler(device);
            }

            if (scaler == null) {
                refused.put(configuration, Boolean.TRUE);
                Metallum.LOGGER.warn("MetalFX spatial scaling: the device refused a scaler for {}x{} to "
                                + "{}x{}, formats {} and {}; the frame keeps its other road",
                        configuration.inputWidth(), configuration.inputHeight(),
                        configuration.outputWidth(), configuration.outputHeight(),
                        configuration.colorFormat(), configuration.outputFormat());
                return false;
            }

            scalers.put(configuration, scaler);
        }

        scaler.encode(commandBuffer, color.nativeHandle(), output.nativeHandle(), contentWidth, contentHeight);
        return true;
    }

    /** Releases every cached scaler. Called where the device is being taken down. */
    public static void close() {
        for (MTLFXSpatialScaler scaler : scalers.values()) {
            scaler.close();
        }
        scalers.clear();
        refused.clear();
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
