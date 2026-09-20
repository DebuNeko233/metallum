package com.metallum.mtl.metal3;

import com.metallum.mtl.MTLTexture;

import com.metallum.mtl.MTLRenderPassDescriptor;

import com.metallum.mtl.MTLPixelFormat;

import com.metallum.mtl.MTLFence;

import com.metallum.mtl.MTLBuiltinPipelines;

import com.metallum.mtl.CAMetalLayer;

import com.metallum.mtl.CAMetalDrawable;

import com.metallum.mtl.MTLDevice;

import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalFrameProbe;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4fc;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public final class MTLCommandBuffer {
    private static final int MAX_COLOR_ATTACHMENTS = 8;
    private static final long STATUS_COMPLETED = 4;
    private static final long STATUS_ERROR = 5;

    private static final Msg BLIT_COMMAND_ENCODER = Msg.of("blitCommandEncoder", ADDRESS);
    private static final Msg COMPUTE_COMMAND_ENCODER = Msg.of("computeCommandEncoder", ADDRESS);
    private static final Msg RENDER_COMMAND_ENCODER = Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg PRESENT_DRAWABLE = Msg.ofVoid("presentDrawable:", ADDRESS);
    private static final Msg COMMIT = Msg.ofVoid("commit");
    private static final Msg ADD_COMPLETED_HANDLER = Msg.ofVoid("addCompletedHandler:", ADDRESS);
    private static final Msg ENCODE_SIGNAL_EVENT = Msg.ofVoid("encodeSignalEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg ERROR = Msg.of("error", ADDRESS);
    private static final Msg LOCALIZED_DESCRIPTION = Msg.of("localizedDescription", ADDRESS);
    private static final Msg STATUS = Msg.of("status", JAVA_LONG);
    private static final Msg GPU_START_TIME = Msg.of("GPUStartTime", JAVA_DOUBLE);
    private static final Msg GPU_END_TIME = Msg.of("GPUEndTime", JAVA_DOUBLE);
    private static final Msg WAIT_UNTIL_COMPLETED = Msg.ofVoid("waitUntilCompleted", true);
    private static final Msg PUSH_DEBUG_GROUP = Msg.ofVoid("pushDebugGroup:", ADDRESS);
    private static final Msg POP_DEBUG_GROUP = Msg.ofVoid("popDebugGroup");

    private MemorySegment handle;

    MTLCommandBuffer(final MemorySegment handle) {
        this.handle = handle;
    }

    public MTLBlitCommandEncoder makeBlitCommandEncoder() {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment encoder = BLIT_COMMAND_ENCODER.sendPtr(handle());
            if (ObjC.isNil(encoder)) {
                throw new IllegalStateException("Failed to create MTLBlitCommandEncoder");
            }
            return new MTLBlitCommandEncoder(ObjC.retain(encoder));
        }
    }

    public MTLComputeCommandEncoder makeComputeCommandEncoder() {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment encoder = COMPUTE_COMMAND_ENCODER.sendPtr(handle());
            if (ObjC.isNil(encoder)) {
                throw new IllegalStateException("Failed to create MTLComputeCommandEncoder");
            }
            return new MTLComputeCommandEncoder(ObjC.retain(encoder));
        }
    }

    public MTLRenderCommandEncoder makeRenderCommandEncoder(final MTLRenderPassDescriptor descriptor) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment encoder = RENDER_COMMAND_ENCODER.sendPtr(handle(), descriptor.handle());
            if (ObjC.isNil(encoder)) {
                throw new IllegalStateException("Failed to create MTLRenderCommandEncoder");
            }
            return new MTLRenderCommandEncoder(ObjC.retain(encoder));
        }
    }

    public MTLRenderCommandEncoder makeRenderCommandEncoder(
            final MemorySegment colorTexture,
            @Nullable final Vector4fc clearColor,
            final MemorySegment depthTexture,
            @Nullable final Double clearDepth,
            final double viewportWidth,
            final double viewportHeight,
            final int colorPixelSize,
            final int depthPixelSize
    ) {
        MemorySegment[] colorTextures = ObjC.isNil(colorTexture)
                ? new MemorySegment[0]
                : new MemorySegment[]{colorTexture};
        Vector4fc[] clearColors = ObjC.isNil(colorTexture)
                ? new Vector4fc[0]
                : new Vector4fc[]{clearColor};
        int[] colorPixelSizes = ObjC.isNil(colorTexture)
                ? new int[0]
                : new int[]{colorPixelSize};
        return makeRenderCommandEncoder(
                colorTextures,
                clearColors,
                null,
                depthTexture,
                clearDepth,
                viewportWidth,
                viewportHeight,
                colorPixelSizes,
                depthPixelSize
        );
    }

    /**
     * Builds the attachment descriptor and the encoder that encodes into it.
     *
     * @param attachmentContents what the pass said about each colour attachment's contents, by slot,
     *                           or null where it said nothing and every slot is
     *                           {@link AttachmentContents#CARRIED}. Shorter than the attachment list
     *                           is the same as saying nothing about the slots past its end
     * @param colorPixelSizes   bytes per pixel of each color attachment, in attachment order, and zero
     *                          where the caller could not determine it; the frame probe counts an
     *                          attachment it cannot size as nothing rather than as a guess
     * @param depthPixelSize    bytes per pixel of the depth attachment, or zero when it cannot be
     *                          determined
     */
    public MTLRenderCommandEncoder makeRenderCommandEncoder(
            final MemorySegment[] colorTextures,
            @Nullable final Vector4fc[] clearColors,
            @Nullable final AttachmentContents[] attachmentContents,
            final MemorySegment depthTexture,
            @Nullable final Double clearDepth,
            final double viewportWidth,
            final double viewportHeight,
            final int[] colorPixelSizes,
            final int depthPixelSize
    ) {
        if (colorTextures.length > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalArgumentException(
                    "Metal supports at most " + MAX_COLOR_ATTACHMENTS + " color attachments, got " + colorTextures.length
            );
        }
        if (clearColors != null && clearColors.length != colorTextures.length) {
            throw new IllegalArgumentException(
                    "Color attachment and clear-value counts differ: " + colorTextures.length + " != " + clearColors.length
            );
        }
        if (colorPixelSizes.length != colorTextures.length) {
            throw new IllegalArgumentException(
                    "Color attachment and pixel-size counts differ: " + colorTextures.length + " != " + colorPixelSizes.length
            );
        }

        // One answer per slot with the default filled in, so the loop below reads a fact rather
        // than a null it has to interpret.
        AttachmentContents[] stated = AttachmentContents.resolve(attachmentContents, colorTextures.length);

        boolean hasColorAttachment = false;
        for (MemorySegment colorTexture : colorTextures) {
            if (!ObjC.isNil(colorTexture)) {
                hasColorAttachment = true;
                break;
            }
        }
        if (!hasColorAttachment && ObjC.isNil(depthTexture)) {
            throw new IllegalStateException("Render pass requires a color or depth attachment");
        }

        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MTLRenderCommandEncoder encoder;
            MetalFrameProbe.passDescriptorCreated();
            try (MTLRenderPassDescriptor renderPass = new MTLRenderPassDescriptor()) {
                for (int index = 0; index < colorTextures.length; index++) {
                    MemorySegment colorTexture = colorTextures[index];
                    if (ObjC.isNil(colorTexture)) {
                        continue;
                    }
                    Vector4fc clearColor = clearColors == null ? null : clearColors[index];
                    // What the pass said about this attachment, or the answer that changes nothing:
                    // contents read afterwards, and not assumed to be overwritten. A clear already
                    // beats the load question, because a pass that asked to be handed a colour is
                    // not asking to be handed what stood there.
                    AttachmentContents contents = stated[index];
                    long loadAction = clearColor != null
                            ? MTLRenderPassDescriptor.LOAD_ACTION_CLEAR
                            : contents.overwritten()
                                    ? MTLRenderPassDescriptor.LOAD_ACTION_DONT_CARE
                                    : MTLRenderPassDescriptor.LOAD_ACTION_LOAD;
                    long storeAction = contents.readAfterwards()
                            ? MTLRenderPassDescriptor.STORE_ACTION_STORE
                            : MTLRenderPassDescriptor.STORE_ACTION_DONT_CARE;
                    // The probe is handed the attachment itself rather than a byte count, so that an
                    // unarmed launch pays one field read here and never asks Metal for a width.
                    MetalFrameProbe.attachment(
                            colorTexture,
                            colorPixelSizes[index],
                            loadAction == MTLRenderPassDescriptor.LOAD_ACTION_LOAD,
                            storeAction == MTLRenderPassDescriptor.STORE_ACTION_STORE
                    );
                    renderPass.colorAttachment(index, colorTexture, loadAction, storeAction, clearColor);
                }
                if (!ObjC.isNil(depthTexture)) {
                    long loadAction = clearDepth != null
                            ? MTLRenderPassDescriptor.LOAD_ACTION_CLEAR
                            : MTLRenderPassDescriptor.LOAD_ACTION_LOAD;
                    long storeAction = MTLRenderPassDescriptor.STORE_ACTION_STORE;
                    // Counted apart from the colour attachments as well as inside their totals: this
                    // slot is the one the pack side cannot say anything about, so how much of a frame
                    // it is decides whether teaching it to answer is worth doing.
                    MetalFrameProbe.depthAttachment(
                            depthTexture,
                            depthPixelSize,
                            loadAction == MTLRenderPassDescriptor.LOAD_ACTION_LOAD,
                            storeAction == MTLRenderPassDescriptor.STORE_ACTION_STORE
                    );
                    renderPass.depthAttachment(depthTexture, loadAction, storeAction, clearDepth);
                    if (MTLPixelFormat.hasStencil(MTLTexture.pixelFormat(depthTexture))) {
                        renderPass.stencilAttachment(
                                depthTexture,
                                MTLRenderPassDescriptor.LOAD_ACTION_DONT_CARE,
                                MTLRenderPassDescriptor.STORE_ACTION_DONT_CARE
                        );
                    }
                }
                encoder = makeRenderCommandEncoder(renderPass);
            }
            encoder.setViewport(0.0, 0.0, viewportWidth, viewportHeight, 0.0, 1.0);
            return encoder;
        }
    }

    public void clearColorDepthTexturesRegion(
            final MemorySegment colorTexture,
            final Vector4fc clearColor,
            final MemorySegment depthTexture,
            final double clearDepth,
            final int regionX,
            final int regionY,
            final int regionWidth,
            final int regionHeight,
            final MTLFence globalFence
    ) {
        MTLBuiltinPipelines.clearColorDepthTexturesRegion(
                this,
                colorTexture,
                clearColor,
                depthTexture,
                clearDepth,
                regionX,
                regionY,
                regionWidth,
                regionHeight,
                globalFence
        );
    }

    /**
     * Draws the picture into the layer's next drawable and presents it, answering the drawable's texture so a
     * caller that wants to read what was presented can - the drawable is valid for this command buffer alone.
     */
    public MemorySegment encodePresentTextureToDrawable(final CAMetalLayer layer, final MemorySegment sourceTexture,
                                                        final MTLFence globalFence) {
        return MTLBuiltinPipelines.encodePresentTextureToDrawable(this, layer, sourceTexture, globalFence);
    }

    public void presentDrawable(final CAMetalDrawable drawable) {
        PRESENT_DRAWABLE.send(handle(), drawable.handle());
    }

    /**
     * Makes this command buffer signal a shared event once the GPU has finished its work.
     * <p>
     * How one queue tells another that the resources it wrote are ready: the event crosses the two queues,
     * where a fence does not.
     */
    public void encodeSignalEvent(final MemorySegment event, final long value) {
        ENCODE_SIGNAL_EVENT.send(handle(), event, value);
    }

    public void commit() {
        COMMIT.send(handle());
    }

    public void commitWithCompletionBlock(final MemorySegment completedHandlerBlock) {
        ADD_COMPLETED_HANDLER.send(handle(), completedHandlerBlock);
        COMMIT.send(handle());
    }

    /**
     * What went wrong, or {@code none}.
     * <p>
     * Apple's status machine has a state for a finished command buffer and a state for a failed one, and
     * both answer {@code isCompleted} - so a frame that failed and a frame that drew look the same to
     * every caller unless this is read. The two driver times stay 0.0 on a failure, which is the other
     * symptom: a frame probe reporting no GPU time at all.
     *
     * @return the error's own description, or {@code none}
     */
    public String errorDescription() {
        if (ObjC.isNil(handle) || STATUS.sendLong(handle) != STATUS_ERROR) {
            return "none";
        }

        MemorySegment error = ERROR.sendPtr(handle);
        return ObjC.isNil(error) ? "a failed command buffer that carried no error object"
                : ObjC.javaString(LOCALIZED_DESCRIPTION.sendPtr(error));
    }

    public boolean isCompleted() {
        if (ObjC.isNil(handle)) {
            return true;
        }
        long status = STATUS.sendLong(handle);
        return status == STATUS_COMPLETED || status == STATUS_ERROR;
    }

    public boolean waitUntilCompleted(final long timeoutMs) {
        if (ObjC.isNil(handle)) {
            return true;
        }
        if (isCompleted()) {
            return true;
        }
        if (timeoutMs <= 0L) {
            return false;
        }
        WAIT_UNTIL_COMPLETED.send(handle);
        return isCompleted();
    }

    public void pushDebugGroup(final String label) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment nsLabel = ObjC.nsString(label == null ? "" : label);
            PUSH_DEBUG_GROUP.send(handle(), nsLabel);
            ObjC.release(nsLabel);
        }
    }

    public void popDebugGroup() {
        POP_DEBUG_GROUP.send(handle());
    }

    /**
     * How long the GPU spent running this command buffer, in milliseconds, or nought when the driver
     * has not reported it.
     * <p>
     * Apple documents the two times as "the host time, in seconds, when the GPU starts command buffer
     * execution" and the same for its end, both "relative to system mach time", and says plainly that
     * they "remain 0.0 until the GPU finishes running the command buffer" and that they are to be read
     * after {@code waitUntilCompleted} returns or inside a completion handler. That is the only reading
     * of GPU time this backend has: the query pool the pack side writes timestamps into is filled from
     * the host clock at encode time, which measures encoding and not execution.
     */
    public double gpuMillis() {
        if (ObjC.isNil(handle)) {
            return 0.0;
        }
        double start = GPU_START_TIME.sendDouble(handle);
        double end = GPU_END_TIME.sendDouble(handle);
        return end > start ? (end - start) * 1000.0 : 0.0;
    }

    public void close() {
        if (ObjC.isNil(handle)) {
            return;
        }
        ObjC.release(handle);
        handle = MemorySegment.NULL;
    }

    public MemorySegment handle() {
        if (ObjC.isNil(handle)) {
            throw new IllegalStateException("MTLCommandBuffer is closed");
        }
        return handle;
    }
}
