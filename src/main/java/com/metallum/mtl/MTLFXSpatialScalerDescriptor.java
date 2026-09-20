package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * The descriptor a MetalFX spatial scaler is configured with, and the factory that makes one.
 * <p>
 * Everything the scaler needs to know before it exists is set here: how large the input is, how large
 * the output is, and the pixel format on each side. The colour processing mode is the one setting that
 * is about meaning rather than size - it tells the scaler which space the samples are in - and it is the
 * only value here that a picture has to be looked at to choose.
 * <p>
 * <strong>The factory's selector is asked for, not assumed.</strong> Apple's documentation names it in
 * Swift, and the Objective-C selector is the {@code new}-prefixed spelling of the same call; asking the
 * class which it responds to costs one message and turns a silent nil - which is what a wrong selector
 * gives, with no error anywhere - into an answer this code can read.
 */
@Environment(EnvType.CLIENT)
public final class MTLFXSpatialScalerDescriptor implements AutoCloseable {

    /** The two spellings of the factory, in the order they are asked about. */
    private static final String[] FACTORY_SELECTORS = {
            "newSpatialScalerWithDevice:",
            "makeSpatialScalerWithDevice:",
    };

    private static final Msg NEW = Msg.of("new", ADDRESS);
    private static final Msg SET_INPUT_WIDTH = Msg.ofVoid("setInputWidth:", JAVA_LONG);
    private static final Msg SET_INPUT_HEIGHT = Msg.ofVoid("setInputHeight:", JAVA_LONG);
    private static final Msg SET_OUTPUT_WIDTH = Msg.ofVoid("setOutputWidth:", JAVA_LONG);
    private static final Msg SET_OUTPUT_HEIGHT = Msg.ofVoid("setOutputHeight:", JAVA_LONG);
    private static final Msg SET_COLOR_TEXTURE_FORMAT = Msg.ofVoid("setColorTextureFormat:", JAVA_LONG);
    private static final Msg SET_OUTPUT_TEXTURE_FORMAT = Msg.ofVoid("setOutputTextureFormat:", JAVA_LONG);
    private static final Msg SET_COLOR_PROCESSING_MODE = Msg.ofVoid("setColorProcessingMode:", JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    /** The spatial scaler's colour processing modes, which are the three spaces it can be handed. */
    public enum ColorProcessingMode {
        /** Display-referred samples, which is what an eight-bit colour texture holds. */
        PERCEPTUAL(0L),
        /** Linear samples. */
        LINEAR(1L),
        /** High dynamic range samples, for a float target that has not been tonemapped yet. */
        HDR(2L);

        final long value;

        ColorProcessingMode(final long value) {
            this.value = value;
        }
    }

    private final MemorySegment handle;
    private final MemorySegment scalerClass;

    private MTLFXSpatialScalerDescriptor(final MemorySegment handle, final MemorySegment scalerClass) {
        this.handle = handle;
        this.scalerClass = scalerClass;
    }

    /**
     * A descriptor for one configuration, or null where the class cannot be asked to make a scaler at
     * all. The caller owns what comes back and closes it.
     */
    public static MTLFXSpatialScalerDescriptor create(
            final MemorySegment scalerClass,
            final int inputWidth,
            final int inputHeight,
            final int outputWidth,
            final int outputHeight,
            final long colorTextureFormat,
            final long outputTextureFormat,
            final ColorProcessingMode colorProcessingMode
    ) {
        MemorySegment handle = NEW.sendPtr(scalerClass);
        if (ObjC.isNil(handle)) {
            return null;
        }

        MTLFXSpatialScalerDescriptor descriptor =
                new MTLFXSpatialScalerDescriptor(handle, scalerClass);
        SET_INPUT_WIDTH.send(handle, inputWidth);
        SET_INPUT_HEIGHT.send(handle, inputHeight);
        SET_OUTPUT_WIDTH.send(handle, outputWidth);
        SET_OUTPUT_HEIGHT.send(handle, outputHeight);
        SET_COLOR_TEXTURE_FORMAT.send(handle, colorTextureFormat);
        SET_OUTPUT_TEXTURE_FORMAT.send(handle, outputTextureFormat);
        SET_COLOR_PROCESSING_MODE.send(handle, colorProcessingMode.value);

        return descriptor;
    }

    /**
     * A scaler for this configuration, or null where the device refused it or the descriptor answers to
     * none of the spellings this class knows.
     * <p>
     * The question is asked of this <strong>instance</strong> and not of its class. Making a scaler is
     * something a descriptor does, so the selector is an instance method and a class object answers no
     * to it - which is exactly what the first version of this asked, and what the log said when it did.
     */
    public MTLFXSpatialScaler makeSpatialScaler(final MemorySegment device) {
        String selector = factorySelector();
        if (selector.isEmpty()) {
            return null;
        }

        MemorySegment scaler = Msg.of(selector, ADDRESS, ADDRESS).sendPtr(handle, device);
        return ObjC.isNil(scaler) ? null : new MTLFXSpatialScaler(scaler);
    }

    /**
     * Which spelling of the factory this descriptor answers to, or empty where it answers to none. Said
     * in the log because a wrong selector is a nil scaler with no error anywhere.
     */
    public String factorySelector() {
        for (String selector : FACTORY_SELECTORS) {
            if (RESPONDS_TO_SELECTOR.sendLong(handle, ObjC.selector(selector)) != 0L) {
                return selector;
            }
        }

        for (String selector : FACTORY_SELECTORS) {
            if (RESPONDS_TO_SELECTOR.sendLong(scalerClass, ObjC.selector(selector)) != 0L) {
                return selector;
            }
        }

        return "";
    }

    /**
     * The descriptor object itself, which is what the Metal 4 factory is sent to.
     * <p>
     * Exposed because the Metal 4 scaler is made by a selector this class does not carry - the compiler argument
     * belongs to that generation's API - and the object a factory is sent to is the descriptor, not its class.
     * The alternative was a second copy of the descriptor's configuration inside the Metal 4 layer, which is two
     * places for one configuration to be wrong.
     */
    public MemorySegment handle() {
        return this.handle;
    }

    @Override
    public void close() {
        ObjC.release(handle);
    }
}
