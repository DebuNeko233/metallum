package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalGpuTextureView;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPass;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4fc;
import org.jspecify.annotations.NonNull;
import org.jspecify.annotations.Nullable;

import com.mojang.blaze3d.IndexType;
import org.lwjgl.PointerBuffer;

import java.nio.IntBuffer;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.OptionalDouble;
import java.util.function.Supplier;

/**
 * One Metal 4 render pass as the game's own render path sees it: the descriptor's attachments turned into a
 * Metal 4 pass descriptor, and the encoder that pass is encoded into.
 * <p>
 * <strong>What it does is the pass itself.</strong> It resolves the descriptor's colour and depth attachments,
 * checks that they agree on an extent and that the render area lies inside it - the same two rules the Metal 3
 * pass applies, because a pass that lied about either would be a wrong image rather than an error message - and
 * opens the pass through {@link MTL4RenderEncoder}, which is where the load and store actions are decided and
 * where the attachment mapping is already measured on the device.
 * <p>
 * <strong>What it does not do is draw.</strong> Every command that would bind a resource or issue work refuses
 * by name, so a pack that reached this pass would be told which operation the Metal 4 path does not have rather
 * than being handed a pass that drew nothing. The one exception is the debug group: it is a capture label and
 * not work, so pushing and popping it is a no-op rather than a refusal - dropping a label costs a reader
 * nothing, while dropping a draw would be the half frame the plan forbids.
 * <p>
 * <strong>The barrier is encoded at the end of every pass</strong> and before the encoder is ended. Only the
 * pass that *reads* an attachment knows whether a dependency exists, and that fact does not reach this class
 * yet (the Metal 3 pass learns it through {@code MetalFrameExtras}, which this generation does not implement),
 * so the migration's rule for this stage applies: over-synchronise while the path is being built, and narrow it
 * when a counter says what the narrowing buys.
 */
@Environment(EnvType.CLIENT)
final class Metal4RenderPass implements RenderPassBackend {

    /** The game's descriptor for this pass, kept for the label and the area a later slice will need. */
    private final RenderPassDescriptor descriptor;
    private final Metal4FrameEncoder owner;
    private final MTL4RenderEncoder encoder;

    Metal4RenderPass(final Metal4FrameEncoder owner, final RenderPassDescriptor descriptor) {
        this.owner = owner;
        this.descriptor = descriptor;

        List<RenderPassDescriptor.Attachment<Optional<Vector4fc>>> attachments = descriptor.colorAttachments();
        if (attachments.size() > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalArgumentException("Render pass declares " + attachments.size() + " colour attachment"
                    + " slots, Metal supports at most " + MAX_COLOR_ATTACHMENTS);
        }

        int width = -1;
        int height = -1;
        MTL4RenderEncoder.Color[] colors = new MTL4RenderEncoder.Color[attachments.size()];
        for (int index = 0; index < attachments.size(); index++) {
            RenderPassDescriptor.Attachment<Optional<Vector4fc>> attachment = attachments.get(index);
            if (attachment == null) {
                // An unused slot is a slot the game reserved and did not fill: it is not attached, rather than
                // attached to nothing, which is the same distinction the Metal 3 pass makes.
                continue;
            }
            GpuTextureView view = attachment.textureView();
            if (width < 0) {
                width = view.getWidth(0);
                height = view.getHeight(0);
            } else if (width != view.getWidth(0) || height != view.getHeight(0)) {
                throw new IllegalArgumentException("Metal render-pass colour attachment " + index + " is "
                        + view.getWidth(0) + "x" + view.getHeight(0) + ", expected " + width + "x" + height);
            }
            Vector4fc clear = attachment.clearValue().orElse(null);
            colors[index] = new MTL4RenderEncoder.Color(nativeHandle(view), AttachmentContents.CARRIED,
                    clear == null ? null : new float[]{clear.x(), clear.y(), clear.z(), clear.w()});
        }

        RenderPassDescriptor.Attachment<OptionalDouble> depthAttachment = descriptor.depthAttachment();
        MTL4RenderEncoder.Depth depth = null;
        if (depthAttachment != null) {
            GpuTextureView view = depthAttachment.textureView();
            if (width < 0) {
                width = view.getWidth(0);
                height = view.getHeight(0);
            } else if (width != view.getWidth(0) || height != view.getHeight(0)) {
                throw new IllegalArgumentException("Metal render-pass depth attachment is " + view.getWidth(0) + "x"
                        + view.getHeight(0) + ", expected " + width + "x" + height);
            }
            depth = new MTL4RenderEncoder.Depth(nativeHandle(view),
                    depthAttachment.clearValue().isPresent() ? depthAttachment.clearValue().getAsDouble() : null);
        }

        if (width <= 0 || height <= 0) {
            throw new IllegalArgumentException("Metal render pass requires at least one colour or depth"
                    + " attachment");
        }
        RenderPass.RenderArea area = descriptor.renderArea;
        if (area == null) {
            throw new IllegalArgumentException("Metal render pass has no render area, and the pass extent is not a"
                    + " substitute for one");
        }
        if (area.x() < 0 || area.y() < 0 || area.width() <= 0 || area.height() <= 0
                || area.x() + area.width() > width || area.y() + area.height() > height) {
            throw new IllegalArgumentException("Render area " + area + " is outside Metal attachment extent "
                    + width + "x" + height);
        }

        try {
            this.encoder = MTL4RenderEncoder.open(owner.nativeDevice(), owner.commandBuffer(), width, height,
                    colors, depth, label());
        } catch (MTL4RenderEncoder.Refused refused) {
            // Named here as well as at the layer below, because this is the call the frame makes and the place a
            // reader of the log is looking: the pass that could not open is this pass.
            throw new IllegalStateException("the Metal 4 render pass could not be opened at stage "
                    + refused.stage() + ": " + refused.getMessage(), refused);
        }
    }

    /** How many colour attachments Metal accepts on a pass, as the Metal 3 pass states it too. */
    private static final int MAX_COLOR_ATTACHMENTS = 8;

    /** The texture a view names, as the descriptor takes it. A view that is not this engine's is a fault. */
    private static java.lang.foreign.MemorySegment nativeHandle(final GpuTextureView view) {
        if (!(view instanceof MetalGpuTextureView metal)) {
            throw new IllegalArgumentException("Metal render pass was handed a texture view that is not this"
                    + " engine's: " + view.getClass().getName());
        }
        return metal.nativeHandle();
    }

    /** What the game called this pass, as the descriptor's label answers it. */
    private String label() {
        Supplier<String> label = this.descriptor.label();
        String words = label == null ? null : label.get();
        return words == null ? "Metal 4 pass" : words;
    }

    /**
     * Ends this pass: the producer barrier first, then the encoder.
     * <p>
     * Called by the frame encoder when the game submits the pass. Ending twice is harmless, because the ring's
     * command buffer may be ended once and a caller may reach this on more than one path.
     */
    void finish() {
        if (!this.encoder.open()) {
            return;
        }
        if (!this.encoder.barrierForSubsequentEncoders()) {
            Metallum.LOGGER.warn("Metal 4 render pass '{}': the encoder does not answer the producer barrier, so"
                    + " a later pass that reads what this one wrote has no encoded dependency", label());
        }
        this.encoder.close();
    }

    /** Whether this pass is still open, for the frame encoder's own bookkeeping. */
    boolean open() {
        return this.encoder.open();
    }

    /**
     * The one shape every operation this path cannot perform takes: a refusal named for the operation.
     * <p>
     * The name is the migration plan's own vocabulary, so a log line and the plan's remaining work can be read
     * against each other.
     */
    private static Metal4ExecutionProvider.Unimplemented unimplemented(final String operation) {
        return new Metal4ExecutionProvider.Unimplemented(operation,
                "the Metal 4 render pass does not encode " + operation + " yet: the frame path is still Metal 3's,"
                        + " and this pass refuses by name rather than drawing nothing");
    }

    // ---------------------------------------------------------------- the pass's own bookkeeping

    /**
     * A capture label and not work: dropping it costs a reader of a GPU capture something, while a pass that
     * refused it would break a frame for no correctness reason.
     */
    @Override
    public void pushDebugGroup(final @NonNull Supplier<String> label) {
    }

    @Override
    public void popDebugGroup() {
    }

    // ---------------------------------------------------------------- and the operations that do not exist

    @Override
    public void setPipeline(final @NonNull RenderPipeline pipeline) {
        throw unimplemented("setPipeline");
    }

    @Override
    public void bindTexture(final @NonNull String name, final @NonNull GpuTextureView view,
                            final @NonNull GpuSampler sampler) {
        throw unimplemented("bindTexture");
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBuffer buffer) {
        throw unimplemented("setUniform");
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBufferSlice slice) {
        throw unimplemented("setUniform");
    }

    @Override
    public void enableScissor(final int x, final int y, final int width, final int height) {
        throw unimplemented("enableScissor");
    }

    @Override
    public void disableScissor() {
        throw unimplemented("disableScissor");
    }

    @Override
    public void setVertexBuffer(final int slot, final @NonNull GpuBufferSlice buffer) {
        throw unimplemented("setVertexBuffer");
    }

    @Override
    public void setIndexBuffer(final @NonNull GpuBuffer buffer, final @NonNull IndexType type) {
        throw unimplemented("setIndexBuffer");
    }

    @Override
    public void drawIndexed(final int indexCount, final int instanceCount, final int firstIndex,
                            final int vertexOffset, final int firstInstance) {
        throw unimplemented("drawIndexed");
    }

    @Override
    public void multiDrawIndexed(final @NonNull IntBuffer indices, final int instanceCount, final int firstIndex,
                                 final int vertexOffset) {
        throw unimplemented("multiDrawIndexed");
    }

    @Override
    public void multiDrawIndexed(final @NonNull PointerBuffer firstIndices,
                                 final @NonNull IntBuffer indexCounts, final @NonNull IntBuffer vertexOffsets,
                                 final int firstInstance) {
        throw unimplemented("multiDrawIndexed");
    }

    @Override
    public void drawIndexedIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {
        throw unimplemented("drawIndexedIndirect");
    }

    @Override
    public <T> void drawMultipleIndexed(final @NonNull Collection<RenderPass.Draw<T>> draws,
                                        final @NonNull GpuBuffer indexBuffer, final @NonNull IndexType indexType,
                                        final @NonNull Collection<String> uniformNames, final @NonNull T pushConstant) {
        throw unimplemented("drawMultipleIndexed");
    }

    @Override
    public void draw(final int vertexCount, final int instanceCount, final int firstVertex,
                     final int firstInstance) {
        throw unimplemented("draw");
    }

    @Override
    public void multiDraw(final @NonNull IntBuffer firstVertices, final int vertexCount, final int instanceCount,
                          final int firstVertex) {
        throw unimplemented("multiDraw");
    }

    @Override
    public void multiDraw(final @NonNull IntBuffer firstVertices, final @NonNull IntBuffer vertexCounts,
                          final int firstInstance) {
        throw unimplemented("multiDraw");
    }

    @Override
    public void drawIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {
        throw unimplemented("drawIndirect");
    }

    /** Timestamps are the counter path, which the migration puts after correctness, not beside it. */
    @Override
    public void writeTimestamp(final @NonNull GpuQueryPool pool, final int index) {
        throw unimplemented("writeTimestamp");
    }
}
