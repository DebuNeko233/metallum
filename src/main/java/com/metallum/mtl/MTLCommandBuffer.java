package com.metallum.mtl;

import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import com.metallum.render.AttachmentContents;
import com.metallum.render.MetalFrameProbe;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4fc;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
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
    private static final Msg STATUS = Msg.of("status", JAVA_LONG);
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

    MTLRenderCommandEncoder makeRenderCommandEncoder(final MTLRenderPassDescriptor descriptor) {
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
                    AttachmentContents contents = contentsOf(attachmentContents, index);
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
                    MetalFrameProbe.attachment(
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

    /**
     * What a pass said about one colour attachment, or what it is taken to mean when it said nothing.
     * <p>
     * Null, a short array and a null slot answer the same way, because all three are a caller with
     * nothing to say about that slot rather than one that said its contents are finished with.
     */
    private static AttachmentContents contentsOf(
            @Nullable final AttachmentContents[] contents,
            final int index
    ) {
        if (contents == null || index >= contents.length || contents[index] == null) {
            return AttachmentContents.CARRIED;
        }

        return contents[index];
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

    public void encodePresentTextureToDrawable(final CAMetalLayer layer, final MemorySegment sourceTexture, final MTLFence globalFence) {
        MTLBuiltinPipelines.encodePresentTextureToDrawable(this, layer, sourceTexture, globalFence);
    }

    void presentDrawable(final CAMetalDrawable drawable) {
        PRESENT_DRAWABLE.send(handle(), drawable.handle());
    }

    public void commit() {
        COMMIT.send(handle());
    }

    public void commitWithCompletionBlock(final MemorySegment completedHandlerBlock) {
        ADD_COMPLETED_HANDLER.send(handle(), completedHandlerBlock);
        COMMIT.send(handle());
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
