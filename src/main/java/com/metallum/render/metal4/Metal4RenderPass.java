package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLIndexType;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
import com.metallum.mtl.metal4.Metal4BindingPlan;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalShaderStages;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPass;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import com.mojang.blaze3d.vertex.VertexFormat;
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
    /** Whether this pass has a depth attachment, which decides which of the artifact's two states is set. */
    private final boolean depthAttached;
    private final long targetWidth;
    private final long targetHeight;

    /** The pipeline the game set, and what the generation compiled for it. */
    @Nullable
    private RenderPipeline pipeline;
    @Nullable
    private Metal4CompiledRenderPipeline artifact;
    @Nullable
    private Metal4BindingPlan plan;
    @Nullable
    private MTL4ArgumentTable vertexTable;
    @Nullable
    private MTL4ArgumentTable fragmentTable;
    /** Whether the tables the encoder holds are the ones this pass has been filling. */
    private boolean tablesAssigned;
    /** The index buffer an indexed draw reads, as the address the new model's draw takes. */
    private long indexBufferAddress;
    private long indexBufferLength;
    private long indexTypeValue = MTLIndexType.UInt16.value;
    private int indexTypeBytes = MTLIndexType.UInt16.bytes;
    /** The scissor rectangle, applied when a draw is encoded rather than when it is asked for. */
    private boolean scissorEnabled;
    private long scissorX;
    private long scissorY;
    private long scissorWidth;
    private long scissorHeight;

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

        this.depthAttached = depth != null;
        this.targetWidth = width;
        this.targetHeight = height;

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
        releaseTables();
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

    /**
     * The pipeline this pass draws with: the game's own description, compiled by this generation.
     * <p>
     * Setting one builds the pass's binding plan and the tables that plan sizes, because both are properties of
     * the pipeline and not of a frame: a pass that sets the same pipeline twice rebuilds nothing, and one that
     * changes pipeline drops the tables the old plan filled rather than reusing them with the wrong shape.
     */
    @Override
    public void setPipeline(final @NonNull RenderPipeline pipeline) {
        if (this.pipeline == pipeline) {
            return;
        }

        Metal4CompiledRenderPipeline compiled = this.owner.compiled(pipeline);
        if (!compiled.isValid()) {
            throw new IllegalStateException("the Metal 4 pipeline " + pipeline.getLocation() + " did not compile,"
                    + " so this pass has no state to draw with");
        }

        this.pipeline = pipeline;
        this.artifact = compiled;
        this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.firstAvailableVertexBufferSlot(),
                compiled.vertexBufferCount());
        releaseTables();
        if (this.plan.usesStage(MetalShaderStages.VERTEX)) {
            this.vertexTable = MTL4ArgumentTable.create(this.owner.nativeDevice(),
                    this.plan.bufferSlots(MetalShaderStages.VERTEX),
                    this.plan.textureSlots(MetalShaderStages.VERTEX),
                    this.plan.samplerSlots(MetalShaderStages.VERTEX));
        }
        if (this.plan.usesStage(MetalShaderStages.FRAGMENT)) {
            this.fragmentTable = MTL4ArgumentTable.create(this.owner.nativeDevice(),
                    this.plan.bufferSlots(MetalShaderStages.FRAGMENT),
                    this.plan.textureSlots(MetalShaderStages.FRAGMENT),
                    this.plan.samplerSlots(MetalShaderStages.FRAGMENT));
        }
        if ((this.plan.usesStage(MetalShaderStages.VERTEX) && this.vertexTable == null)
                || (this.plan.usesStage(MetalShaderStages.FRAGMENT) && this.fragmentTable == null)) {
            releaseTables();
            this.pipeline = null;
            this.artifact = null;
            this.plan = null;
            throw new IllegalStateException("the Metal 4 tables for " + pipeline.getLocation() + " could not be"
                    + " made, so nothing this pass binds would reach a shader");
        }
        this.tablesAssigned = false;
    }

    /**
     * One resource of the pipeline's own layout, bound where the plan says the compiled MSL reads it.
     * <p>
     * A name the pipeline does not declare is a fault rather than something to skip: the layout the pack asked
     * for and the layout the shader was compiled against disagree, and dropping the binding would be the half
     * frame the migration's section 35 forbids. A binding read by both stages is filled in both tables.
     */
    @Override
    public void bindTexture(final @NonNull String name, final @NonNull GpuTextureView view,
                            final @NonNull GpuSampler sampler) {
        Metal4BindingPlan.Slot slot = require(name);
        if (slot.buffer()) {
            throw new IllegalStateException("the Metal 4 pipeline binds '" + name + "' as a buffer and the frame"
                    + " path bound a texture to it, so the two disagree about the layout");
        }
        if (!(view instanceof MetalGpuTextureView textureView) || !(sampler instanceof MetalGpuSampler metalSampler)) {
            throw new IllegalStateException("the Metal 4 pass was handed a texture or sampler that is not this"
                    + " engine's: " + view.getClass().getName() + ", " + sampler.getClass().getName());
        }

        for (int stage : new int[]{MetalShaderStages.VERTEX, MetalShaderStages.FRAGMENT}) {
            MTL4ArgumentTable table = this.tableFor(stage);
            if (table == null || !slot.readBy(stage)) {
                continue;
            }
            if (!table.texture(textureView.nativeHandle(), slot.metalIndex())
                    || (slot.sampled() && !table.sampler(metalSampler.nativeHandle(), slot.samplerMetalIndex()))) {
                throw new IllegalStateException("the Metal 4 table refused the binding '" + name + "' at texture "
                        + slot.metalIndex() + " on " + stageName(stage));
            }
        }
        this.tablesAssigned = false;
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBuffer buffer) {
        bindBuffer(name, addressOf(buffer, 0L));
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBufferSlice slice) {
        bindBuffer(name, addressOf(slice.buffer(), slice.offset()));
    }

    /** Points every table that reads this name at the buffer's GPU address, offset included. */
    private void bindBuffer(final String name, final long address) {
        Metal4BindingPlan.Slot slot = require(name);
        if (slot.texture()) {
            throw new IllegalStateException("the Metal 4 pipeline binds '" + name + "' as a texture and the frame"
                    + " path bound a buffer to it, so the two disagree about the layout");
        }
        for (int stage : new int[]{MetalShaderStages.VERTEX, MetalShaderStages.FRAGMENT}) {
            MTL4ArgumentTable table = this.tableFor(stage);
            if (table == null || !slot.readBy(stage)) {
                continue;
            }
            if (!table.address(address, slot.metalIndex())) {
                throw new IllegalStateException("the Metal 4 table refused the binding '" + name + "' at buffer "
                        + slot.metalIndex() + " on " + stageName(stage));
            }
        }
        this.tablesAssigned = false;
    }

    /**
     * A vertex layout, bound by address <em>and stride</em> at the slot the pipeline's vertex descriptor puts it
     * in. The stride is the pipeline's own vertex format, because it is the layout the shader was compiled to
     * read - a table bound without it would read a vertex per buffer rather than per vertex.
     */
    @Override
    public void setVertexBuffer(final int slot, final @NonNull GpuBufferSlice buffer) {
        Metal4BindingPlan plan = requirePlan();
        if (this.vertexTable == null) {
            throw new IllegalStateException("the Metal 4 pipeline declares no vertex stage, so vertex buffer " + slot
                    + " has nowhere to go");
        }
        if (slot < 0 || slot >= plan.vertexBufferCount()) {
            throw new IllegalStateException("the Metal 4 pipeline declares " + plan.vertexBufferCount()
                    + " vertex layouts and the frame path bound slot " + slot);
        }
        VertexFormat format = this.pipeline.getVertexFormatBinding(slot);
        long stride = format == null ? 0L : format.getVertexSize();
        long address = addressOf(buffer.buffer(), buffer.offset());
        if (!this.vertexTable.address(address, stride, plan.firstVertexBufferSlot() + slot)) {
            throw new IllegalStateException("the Metal 4 vertex table refused buffer slot " + slot + " at table"
                    + " index " + (plan.firstVertexBufferSlot() + slot));
        }
        this.tablesAssigned = false;
    }

    /**
     * The index buffer, remembered as the address the new model's indexed draw takes rather than as bound state.
     * The address arithmetic an indexed draw needs is done where the draw is encoded, because the engine's first
     * index and base vertex are per draw.
     */
    @Override
    public void setIndexBuffer(final @NonNull GpuBuffer buffer, final @NonNull IndexType type) {
        MTLIndexType indexType = MTLIndexType.from(type);
        this.indexBufferAddress = addressOf(buffer, 0L);
        this.indexBufferLength = buffer.size();
        this.indexTypeValue = indexType.value;
        this.indexTypeBytes = indexType.bytes;
    }

    @Override
    public void enableScissor(final int x, final int y, final int width, final int height) {
        this.scissorEnabled = true;
        this.scissorX = x;
        this.scissorY = y;
        this.scissorWidth = width;
        this.scissorHeight = height;
    }

    @Override
    public void disableScissor() {
        // Set to the whole attachment rather than left alone: an encoder keeps the rectangle it was last given,
        // so "no scissor" has to be said as loudly as a rectangle is.
        this.scissorEnabled = false;
        this.scissorX = 0L;
        this.scissorY = 0L;
        this.scissorWidth = this.targetWidth;
        this.scissorHeight = this.targetHeight;
    }

    @Override
    public void drawIndexed(final int indexCount, final int instanceCount, final int firstIndex,
                            final int vertexOffset, final int firstInstance) {
        if (!prepareDraw("drawIndexed")) {
            return;
        }
        long address = this.indexBufferAddress + (long) firstIndex * this.indexTypeBytes;
        long length = Math.max(0L, this.indexBufferLength - (long) firstIndex * this.indexTypeBytes);
        if (!this.encoder.drawIndexedPrimitives(this.artifact.topology().value, indexCount, this.indexTypeValue,
                address, length, instanceCount, vertexOffset)) {
            throw new IllegalStateException("the Metal 4 encoder refused an indexed draw of " + indexCount
                    + " indices");
        }
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
        if (!prepareDraw("draw")) {
            return;
        }
        if (!this.encoder.drawPrimitives(this.artifact.topology().value, firstVertex, vertexCount, instanceCount,
                firstInstance)) {
            throw new IllegalStateException("the Metal 4 encoder refused a draw of " + vertexCount + " vertices");
        }
    }

    /**
     * Everything a draw needs on the encoder: the tables the pass has been filling, the pipeline state, the
     * depth-stencil state, the culling and fill modes, and the scissor.
     * <p>
     * The tables are assigned when they have changed rather than on every draw, which is the first-version
     * compromise the migration's section 50 asks for: correctness first, and a measurement of whether the same
     * binding set could be deduplicated comes later.
     *
     * @return whether a pipeline has been set, which is what a draw without one is missing
     */
    private boolean prepareDraw(final String operation) {
        if (this.pipeline == null) {
            throw new IllegalStateException("the Metal 4 pass was asked to encode " + operation + " with no"
                    + " pipeline set, so nothing says which shaders or layout to draw with");
        }
        if (!this.tablesAssigned) {
            if (this.vertexTable != null && !this.encoder.setArgumentTable(this.vertexTable,
                    MetalShaderStages.VERTEX)) {
                throw new IllegalStateException("the Metal 4 encoder refused the vertex argument table");
            }
            if (this.fragmentTable != null && !this.encoder.setArgumentTable(this.fragmentTable,
                    MetalShaderStages.FRAGMENT)) {
                throw new IllegalStateException("the Metal 4 encoder refused the fragment argument table");
            }
            this.tablesAssigned = true;
        }
        if (!this.encoder.setRenderPipelineState(this.artifact.pipelineState(this.depthAttached))) {
            throw new IllegalStateException("the Metal 4 encoder refused the pipeline state for "
                    + this.pipeline.getLocation());
        }
        this.encoder.setDepthStencilState(this.artifact.depthStencilState());
        this.encoder.setCullMode(this.artifact.cullMode().value);
        this.encoder.setTriangleFillMode(this.artifact.fillMode().value);
        if (this.scissorEnabled || this.scissorWidth > 0L || this.scissorHeight > 0L) {
            this.encoder.setScissorRect(this.scissorX, this.scissorY, this.scissorWidth, this.scissorHeight);
        }
        return true;
    }

    /** The plan this pass is filling, refusing where no pipeline has been set. */
    private Metal4BindingPlan requirePlan() {
        if (this.plan == null) {
            throw new IllegalStateException("the Metal 4 pass was asked to bind a resource with no pipeline set,"
                    + " so which slot it belongs in is not known");
        }
        return this.plan;
    }

    /** One binding of the current pipeline's layout, by the name the pack gave it. */
    private Metal4BindingPlan.Slot require(final String name) {
        Metal4BindingPlan.Slot slot = requirePlan().slot(name);
        if (slot == null) {
            throw new IllegalStateException("the Metal 4 pipeline does not declare a binding called '" + name
                    + "', so the frame path and the shader disagree about the layout");
        }
        return slot;
    }

    /** The table the given stage reads through, or null where this pass has none for it. */
    @Nullable
    private MTL4ArgumentTable tableFor(final int stage) {
        return (stage & MetalShaderStages.VERTEX) != 0 ? this.vertexTable : this.fragmentTable;
    }

    /** The GPU address a slice of an engine buffer starts at, which is what a table binds. */
    private static long addressOf(final GpuBuffer buffer, final long offset) {
        if (!(buffer instanceof MetalGpuBuffer metal)) {
            throw new IllegalStateException("the Metal 4 pass was handed a buffer that is not this engine's: "
                    + buffer.getClass().getName());
        }
        return metal.metalBuffer().gpuAddress() + offset;
    }

    private static String stageName(final int stage) {
        return (stage & MetalShaderStages.VERTEX) != 0 ? "the vertex stage" : "the fragment stage";
    }

    /** Releases the tables a replaced pipeline filled, so a stale plan cannot be read through a new pipeline. */
    private void releaseTables() {
        if (this.vertexTable != null) {
            this.vertexTable.close();
            this.vertexTable = null;
        }
        if (this.fragmentTable != null) {
            this.fragmentTable.close();
            this.fragmentTable = null;
        }
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
