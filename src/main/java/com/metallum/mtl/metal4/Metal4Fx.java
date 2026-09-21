package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLFXSpatialScalerDescriptor;
import com.metallum.mtl.MTLPixelFormat;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.util.LinkedHashMap;
import java.util.Map;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * Metal 4's own MetalFX spatial scaler: whether this device can run one, the one scaler per configuration it keeps,
 * and the encode that runs it on a Metal 4 command buffer.
 * <p>
 * <strong>This is a second scaler path and not a parameter of the first.</strong> The Metal 3 class one package
 * over is a different protocol with a different factory - {@code newSpatialScalerWithDevice:compiler:}, because a
 * Metal 4 pipeline comes from a compiler object rather than from the device - and its encode takes an
 * {@code MTL4CommandBuffer}. Section 80 asks for exactly this split: the logical configuration key may be shared,
 * the native objects may not, because a scaler is a compiled pipeline and one generation's pipeline is not the
 * other's. So the cache here is keyed the same way the Metal 3 one is and holds nothing the Metal 3 one holds.
 * <p>
 * <strong>Availability is a functional question.</strong> Apple's own gate is
 * {@code +[MTLFXSpatialScalerDescriptor supportsMetal4FX:]}, and a system that answers yes can still refuse a
 * scaler - so this asks the class question and then <em>makes</em> one for a plausible configuration and lets it
 * go. That matters beyond tidiness: the capability record uses this answer to decide whether choosing Metal 4
 * would cost the player the render-scale setting, and a {@code respondsTo}-only answer would report a scaler that
 * does not exist as one that does.
 * <p>
 * The framework is loaded the way the Metal 3 path loads it, through {@link ObjC#optionalLibrary}, because a
 * system without MetalFX is a system this engine runs on rather than a failure to start.
 */
@Environment(EnvType.CLIENT)
public final class Metal4Fx implements AutoCloseable {

    /** What one cached Metal 4 scaler was made for. Every field changes what the scaler is. */
    public record Configuration(
            int inputWidth,
            int inputHeight,
            int outputWidth,
            int outputHeight,
            long colorFormat,
            long outputFormat,
            MTLFXSpatialScalerDescriptor.ColorProcessingMode colorProcessingMode
    ) {
    }

    private static final boolean LOADED =
            ObjC.optionalLibrary("/System/Library/Frameworks/MetalFX.framework/MetalFX") != null;

    /** The class question macOS 26 declares for the Metal 4 effect. */
    private static final Msg SUPPORTS_METAL4_FX = Msg.of("supportsMetal4FX:", JAVA_LONG, ADDRESS);
    /** The Metal 4 factory, whose second argument is the compiler object this generation's API needs. */
    private static final Msg NEW_SCALER_WITH_COMPILER =
            Msg.of("newSpatialScalerWithDevice:compiler:", ADDRESS, ADDRESS, ADDRESS);

    private static boolean asked;
    private static boolean supported;
    private static String reason = "not asked yet";

    /** The device the compiler and every scaler below belong to, kept because the factory takes one. */
    private final MemorySegment device;
    private final MTL4Compiler compiler;
    private final Map<Configuration, MTL4FXSpatialScaler> scalers = new LinkedHashMap<>();
    private final Map<Configuration, Boolean> refused = new LinkedHashMap<>();

    private Metal4Fx(final MemorySegment device, final MTL4Compiler compiler) {
        this.device = device;
        this.compiler = compiler;
    }

    /**
     * Whether this device can scale a frame with Metal 4's spatial scaler. Asked once, and the answer is said out
     * loud, because "this Mac cannot do it" and "this build cannot do it" are different sentences.
     *
     * @param device the Metal device handle
     */
    public static boolean supported(final MemorySegment device) {
        // Diagnostic, off unless asked for: answer no as if the device had, so the road this path takes when a
        // scaler is not available is a measurement rather than a reading of the code. It never weakens the real
        // answer - the property is asked first and the device is not consulted at all when it is set - and the
        // reason string says which of the two answered.
        if (Boolean.getBoolean("metallum.probeNoMetalFx")) {
            asked = true;
            supported = false;
            reason = "metallum.probeNoMetalFx was asked for, so this session answers as a device without Metal FX";
            return false;
        }

        if (asked) {
            return supported;
        }
        asked = true;

        if (!LOADED) {
            reason = "MetalFX.framework is not installed on this system";
            return false;
        }

        MemorySegment scalerClass = classOrNull("MTLFXSpatialScalerDescriptor");
        if (ObjC.isNil(scalerClass)) {
            reason = "MetalFX.framework is loaded and has no MTLFXSpatialScalerDescriptor";
            return false;
        }
        if (ObjC.isNil(device)) {
            reason = "there is no device to ask";
            return false;
        }
        if (!MTL4Probe.respondsTo(scalerClass, "supportsMetal4FX:")) {
            reason = "this system's MTLFXSpatialScalerDescriptor does not answer supportsMetal4FX:, so it has no"
                    + " Metal 4 spatial scaler at all";
            Metallum.LOGGER.info("Metal 4 MetalFX spatial scaling: unavailable, {}", reason);
            return false;
        }
        if (SUPPORTS_METAL4_FX.sendLong(scalerClass, device) == 0L) {
            reason = "the device does not support the Metal 4 spatial scaler";
            Metallum.LOGGER.info("Metal 4 MetalFX spatial scaling: unavailable, {}", reason);
            return false;
        }

        // A device that answers yes can still refuse a scaler, and a class question cannot see that. This makes
        // one for a plain colour pair, which is the only way to know the factory works, and lets both objects go.
        MTL4Compiler probeCompiler = MTL4Compiler.create(new MTLDevice(device));
        if (probeCompiler == null) {
            reason = "the device makes no Metal 4 compiler, which the Metal 4 scaler factory needs";
            Metallum.LOGGER.warn("Metal 4 MetalFX spatial scaling: unavailable, {}", reason);
            return false;
        }
        try {
            MTL4FXSpatialScaler probe = makeScaler(device, probeCompiler, new Configuration(1280, 720, 1920, 1080,
                    MTLPixelFormat.RGBA8Unorm.value,
                    MTLPixelFormat.RGBA8Unorm.value,
                    MTLFXSpatialScalerDescriptor.ColorProcessingMode.PERCEPTUAL));
            if (probe == null) {
                reason = "a scaler for a plain colour pair could not be made with a compiler";
                Metallum.LOGGER.warn("Metal 4 MetalFX spatial scaling: unavailable, {}", reason);
                return false;
            }
            probe.close();
        } finally {
            probeCompiler.close();
        }

        supported = true;
        reason = "the device supports it and made one";
        Metallum.LOGGER.info("Metal 4 MetalFX spatial scaling: available, {}", reason);
        return true;
    }

    /** Why the last answer came out the way it did, for a log line or a settings screen. */
    public static String reason() {
        return reason;
    }

    /**
     * The scaler path for this device, or null where it cannot have one.
     * <p>
     * One object per device and not one per frame: the cache below is what keeps a scaler per configuration, and a
     * scaler compiles its own pipeline when it is made.
     */
    @Nullable
    public static Metal4Fx create(final MTLDevice device) {
        if (device == null || !supported(device.handle())) {
            return null;
        }
        MTL4Compiler compiler = MTL4Compiler.create(device);
        if (compiler == null) {
            return null;
        }
        return new Metal4Fx(device.handle(), compiler);
    }

    /**
     * Encodes one spatial upscale of {@code color} into {@code output} on this command buffer.
     * <p>
     * Every failure answers false and leaves the caller on whatever it does without this, because a frame is never
     * left half scaled: no scaler for this configuration, a refused one, and a scaler that could not be made now
     * are all the same answer.
     *
     * @param commandBuffer the frame's Metal 4 command buffer handle
     * @param color         the texture drawn at the scaled size
     * @param output        the texture the picture is brought back into
     * @return whether the encode happened
     */
    public boolean scale(
            final MemorySegment commandBuffer,
            final MemorySegment color,
            final MemorySegment output,
            final Configuration configuration,
            final int contentWidth,
            final int contentHeight
    ) {
        if (ObjC.isNil(commandBuffer) || ObjC.isNil(color) || ObjC.isNil(output)) {
            return false;
        }
        if (Boolean.TRUE.equals(this.refused.get(configuration))) {
            return false;
        }

        MTL4FXSpatialScaler scaler = this.scalers.get(configuration);
        if (scaler == null) {
            scaler = makeScaler(this.device, this.compiler, configuration);
            if (scaler == null) {
                this.refused.put(configuration, Boolean.TRUE);
                Metallum.LOGGER.warn("Metal 4 MetalFX spatial scaling: the device refused a scaler for {}x{} to "
                                + "{}x{}, formats {} and {}; the frame keeps its other road",
                        configuration.inputWidth(), configuration.inputHeight(), configuration.outputWidth(),
                        configuration.outputHeight(), configuration.colorFormat(), configuration.outputFormat());
                return false;
            }
            this.scalers.put(configuration, scaler);
            // Said once per configuration and not once a frame, because a scaler is made on a cache miss and a
            // miss is a rare event: the configuration changed. That makes this line the evidence a resize or a
            // render-scale change leaves - two lines with different sizes in one session say the identity
            // separated them and a new scaler was built rather than an old one reused - which is what section 81
            // and section 124 ask for and what nothing else in the log could show.
            Metallum.LOGGER.info("Metal 4 MetalFX spatial scaling: made a scaler for {}x{} to {}x{} with colour"
                            + " format {} and output format {}, {} in the cache",
                    configuration.inputWidth(), configuration.inputHeight(), configuration.outputWidth(),
                    configuration.outputHeight(), configuration.colorFormat(), configuration.outputFormat(),
                    this.scalers.size());
        }

        scaler.encode(commandBuffer, color, output, contentWidth, contentHeight);
        return true;
    }

    /** One scaler for one configuration, or null where the descriptor or the device would not make it. */
    private static MTL4FXSpatialScaler makeScaler(final MemorySegment device, final MTL4Compiler compiler,
                                                  final Configuration configuration) {
        MemorySegment scalerClass = classOrNull("MTLFXSpatialScalerDescriptor");
        if (ObjC.isNil(scalerClass) || ObjC.isNil(device) || compiler == null
                || ObjC.isNil(compiler.handle())) {
            return null;
        }
        try (MTLFXSpatialScalerDescriptor descriptor = MTLFXSpatialScalerDescriptor.create(
                scalerClass,
                configuration.inputWidth(), configuration.inputHeight(),
                configuration.outputWidth(), configuration.outputHeight(),
                configuration.colorFormat(), configuration.outputFormat(),
                configuration.colorProcessingMode())) {
            if (descriptor == null || !MTL4Probe.respondsTo(descriptor.handle(),
                    "newSpatialScalerWithDevice:compiler:")) {
                return null;
            }
            MemorySegment made = NEW_SCALER_WITH_COMPILER.sendPtr(descriptor.handle(), device,
                    compiler.handle());
            return ObjC.isNil(made) ? null : new MTL4FXSpatialScaler(made);
        }
    }

    /**
     * A class by name, or nil. {@code ObjC.clazz} throws for a name nothing answers to, which is right for a class
     * this backend cannot work without and wrong for one it is only asking about.
     */
    private static MemorySegment classOrNull(final String name) {
        try {
            return ObjC.clazz(name);
        } catch (Throwable missing) {
            return MemorySegment.NULL;
        }
    }

    /** Releases every cached scaler and the compiler they were made with. */
    @Override
    public void close() {
        for (MTL4FXSpatialScaler scaler : this.scalers.values()) {
            scaler.close();
        }
        this.scalers.clear();
        this.refused.clear();
        this.compiler.close();
    }
}
