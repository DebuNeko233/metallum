package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * One MetalFX spatial scaler, held for the configuration it was made for and encoded into a frame's
 * command buffer.
 * <p>
 * The scaler is a protocol rather than a class, so it is reached entirely by selector and this layer
 * needs nothing new to talk to it. Three things are set per frame - the colour texture, the output
 * texture and how much of the input is real - and the encode is one message. Apple's own description of
 * the order is the order here, and it matters: the textures are set together, and the encode is what
 * makes the scaler run.
 * <p>
 * <strong>Hold one per configuration, not one per frame.</strong> The scaler compiles its own pipeline
 * when it is made, so a scaler per frame would be a per-frame pipeline compile; the caller is
 * {@link com.metallum.render.MetalFx}, which caches them by size and format and closes them with the
 * device.
 */
@Environment(EnvType.CLIENT)
public final class MTLFXSpatialScaler implements AutoCloseable {

    private static final Msg SET_COLOR_TEXTURE = Msg.ofVoid("setColorTexture:", ADDRESS);
    private static final Msg SET_OUTPUT_TEXTURE = Msg.ofVoid("setOutputTexture:", ADDRESS);
    private static final Msg SET_INPUT_CONTENT_WIDTH = Msg.ofVoid("setInputContentWidth:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_HEIGHT = Msg.ofVoid("setInputContentHeight:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_ORIGIN_X = Msg.ofVoid("setInputContentOriginX:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_ORIGIN_Y = Msg.ofVoid("setInputContentOriginY:", JAVA_LONG);
    private static final Msg ENCODE = Msg.ofVoid("encodeToCommandBuffer:", ADDRESS);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private final MemorySegment handle;

    MTLFXSpatialScaler(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * Encodes one upscale of the input into the output on this command buffer.
     * <p>
     * The content rectangle is the part of the input texture that really holds this frame: the texture
     * is allocated for the largest size the setting has asked for, and the scale in force can be
     * smaller, which is what {@code inputContentWidth} exists to say. Its origin is the corner, so a
     * frame that renders into the middle of a larger texture - which this engine does not - would say
     * so here.
     */
    public void encode(
            final MemorySegment commandBuffer,
            final MemorySegment colorTexture,
            final MemorySegment outputTexture,
            final int contentWidth,
            final int contentHeight
    ) {
        SET_COLOR_TEXTURE.send(handle, colorTexture);
        SET_OUTPUT_TEXTURE.send(handle, outputTexture);
        SET_INPUT_CONTENT_WIDTH.send(handle, contentWidth);
        SET_INPUT_CONTENT_HEIGHT.send(handle, contentHeight);

        // Asked for and not assumed, because sending a selector an object does not answer to is not a
        // wrong number - it is an Objective-C exception, and one of those ends the process. This scaler
        // answers to no origin: the documentation lists that pair on the other MetalFX effects, and
        // sending it here killed a session before a frame was drawn rather than doing nothing.
        if (RESPONDS_TO_SELECTOR.sendLong(handle, ObjC.selector("setInputContentOriginX:")) != 0L) {
            SET_INPUT_CONTENT_ORIGIN_X.send(handle, 0L);
            SET_INPUT_CONTENT_ORIGIN_Y.send(handle, 0L);
        }

        ENCODE.send(handle, commandBuffer);
    }

    @Override
    public void close() {
        ObjC.release(handle);
    }
}
