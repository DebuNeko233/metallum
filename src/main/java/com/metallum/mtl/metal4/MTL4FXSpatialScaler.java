package com.metallum.mtl.metal4;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * One Metal 4 MetalFX spatial scaler, held for the configuration it was made for and encoded into a frame's Metal 4
 * command buffer.
 * <p>
 * It is the same effect as the Metal 3 class one package over and a different protocol with a different encode:
 * this one takes an {@code MTL4CommandBuffer} rather than an {@code MTLCommandBuffer}, which is the whole of the
 * API difference the header declares (macOS 26's {@code MTL4FXSpatialScaler.h}). Everything else it is configured
 * with comes from the base protocol both generations share - the colour texture, the output texture and how much of
 * the input is real - so the two classes could share those four messages and do not, because a shared base
 * protocol is still reached by selector and a shared helper for four one-line sends is indirection without a
 * reader.
 * <p>
 * <strong>There is no fence here, and that is a measured difference rather than an omission.</strong> The Metal 3
 * scaler is handed the frame's fence because this engine's textures opt out of Metal's own hazard tracking, and
 * {@code MTLFXSpatialScaler.fence} is what Apple declares for exactly that case. Metal 4 has no fence object in
 * this engine at all - {@code Metal4Fence} records why: the new command model orders work with encoder barriers
 * and queue events - so what orders this scaler against the passes around it is the encode order inside the one
 * command buffer and the all-stages barrier every pass already ends with. That is a claim about the API and it is
 * tested by the frame that uses it, not asserted here.
 */
@Environment(EnvType.CLIENT)
public final class MTL4FXSpatialScaler implements AutoCloseable {

    private static final Msg SET_COLOR_TEXTURE = Msg.ofVoid("setColorTexture:", ADDRESS);
    private static final Msg SET_OUTPUT_TEXTURE = Msg.ofVoid("setOutputTexture:", ADDRESS);
    private static final Msg SET_INPUT_CONTENT_WIDTH = Msg.ofVoid("setInputContentWidth:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_HEIGHT = Msg.ofVoid("setInputContentHeight:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_ORIGIN_X = Msg.ofVoid("setInputContentOriginX:", JAVA_LONG);
    private static final Msg SET_INPUT_CONTENT_ORIGIN_Y = Msg.ofVoid("setInputContentOriginY:", JAVA_LONG);
    private static final Msg ENCODE = Msg.ofVoid("encodeToCommandBuffer:", ADDRESS);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private final MemorySegment handle;

    MTL4FXSpatialScaler(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * Encodes one upscale of the input into the output on this Metal 4 command buffer.
     * <p>
     * The order is Apple's: the textures and the content rectangle are set together and the encode is what makes
     * the scaler run. The content origin is asked for rather than assumed, because sending a selector an object
     * does not answer to is an Objective-C exception rather than a wrong number - the same reading the Metal 3
     * wrapper records, where sending it killed a session before a frame was drawn.
     */
    public void encode(
            final MemorySegment commandBuffer,
            final MemorySegment colorTexture,
            final MemorySegment outputTexture,
            final int contentWidth,
            final int contentHeight
    ) {
        SET_COLOR_TEXTURE.send(this.handle, colorTexture);
        SET_OUTPUT_TEXTURE.send(this.handle, outputTexture);
        SET_INPUT_CONTENT_WIDTH.send(this.handle, contentWidth);
        SET_INPUT_CONTENT_HEIGHT.send(this.handle, contentHeight);

        if (RESPONDS_TO_SELECTOR.sendLong(this.handle, ObjC.selector("setInputContentOriginX:")) != 0L) {
            SET_INPUT_CONTENT_ORIGIN_X.send(this.handle, 0L);
            SET_INPUT_CONTENT_ORIGIN_Y.send(this.handle, 0L);
        }

        ENCODE.send(this.handle, commandBuffer);
    }

    MemorySegment handle() {
        return this.handle;
    }

    @Override
    public void close() {
        if (!ObjC.isNil(this.handle)) {
            ObjC.release(this.handle);
        }
    }
}
