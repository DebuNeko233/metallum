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

import java.lang.foreign.MemorySegment;
import java.nio.IntBuffer;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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

    /**
     * The bindings the frame path has made <strong>by name</strong>, kept so a pipeline set later can resolve
     * them.
     * <p>
     * This is the game's own order and not an accommodation: a pass is created, {@code bindDefaultUniforms}
     * binds its default uniforms by name, and the pipeline that turns a name into a slot is set per draw
     * afterwards. The Metal 3 pass keeps its uniforms and textures in maps and resolves them into the argument
     * buffer a draw builds, so the two generations have to agree about the model or the same frame would work on
     * one path and not on the other.
     */
    private final Map<String, Long> uniformAddresses = new LinkedHashMap<>();
    private final Map<String, Sampled> textureBindings = new LinkedHashMap<>();
    /** The vertex layouts by the game's own slot, which the pipeline's descriptor numbers from its own base. */
    private final Map<Integer, GpuBufferSlice> vertexBuffers = new LinkedHashMap<>();

    /** One texture and the sampler that goes with it, as the frame path bound them. */
    private record Sampled(MemorySegment texture, MemorySegment sampler) {
    }
    /** The index buffer an indexed draw reads, as the address the new model's draw takes. */
    private long indexBufferAddress;
    private long indexBufferLength;
    private long indexTypeValue = MTLIndexType.UInt16.value;
    private int indexTypeBytes = MTLIndexType.UInt16.bytes;
    /**
     * Whether this pass says what it encodes, one line per draw.
     * <p>
     * Off unless {@code -Dmetallum.metal4Trace=true} is set, because a session's log is a session's and a
     * per-draw line is a diagnostic. It exists because the first world frame this path encoded stopped the GPU
     * dead, and a frame-level sentence is not enough to find out which command did it: the last line this prints
     * before the machine's log says the GPU restarted is the pass and the draw to look at.
     */
    private static final boolean TRACE = Boolean.getBoolean("metallum.metal4Trace");
    /** How many draws this pass encoded, which the trace reports and nothing else reads. */
    private long drawsEncoded;
    private long indexedEncoded;

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
            MemorySegment attachmentTexture = nativeHandle(view);
            // Declared resident, because an attachment is read and written as a resource the command buffer
            // names by object: this is the half of residency that is not about addresses, and the frame path
            // declares both from the same place.
            this.owner.useResource(attachmentTexture);
            colors[index] = new MTL4RenderEncoder.Color(attachmentTexture, AttachmentContents.CARRIED,
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
            MemorySegment depthTexture = nativeHandle(view);
            this.owner.useResource(depthTexture);
            depth = new MTL4RenderEncoder.Depth(depthTexture,
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
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: end pass '{}' depth={} draws={} indexed={} scissor={}",
                    label(), this.depthAttached, this.drawsEncoded, this.indexedEncoded, this.scissorEnabled);
        }
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
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: pipeline {} in '{}'", pipeline.getLocation(), label());
        }
        // The tables are new, so everything this pass has been told to bind is resolved against them: the
        // bindings that arrived before this pipeline - the game's default uniforms, a vertex layout - are
        // applied here, and the ones already filled above are filled again into these tables.
        applyBindings();
    }

    /**
     * One texture and its sampler, recorded by name and filled into the layout the pipeline gives that name.
     * <p>
     * <strong>When a name is missing from the pipeline that is set, the answer depends on when it was
     * bound.</strong> A binding made while a pipeline is set is a claim about that pipeline's layout, so a name
     * that pipeline does not declare is the disagreement the migration's section 35 forbids and is refused by
     * name. A binding made before any pipeline in this pass is a claim about the pass's own bindings, which a
     * given pipeline may or may not read - the GUI is handed every default uniform and most of its pipelines use
     * some of them - so it is remembered and applied to each later pipeline that declares it.
     * <p>
     * A binding read by both stages is filled in both tables.
     */
    @Override
    public void bindTexture(final @NonNull String name, final @NonNull GpuTextureView view,
                            final @NonNull GpuSampler sampler) {
        if (!(view instanceof MetalGpuTextureView textureView) || !(sampler instanceof MetalGpuSampler metalSampler)) {
            throw new IllegalStateException("the Metal 4 pass was handed a texture or sampler that is not this"
                    + " engine's: " + view.getClass().getName() + ", " + sampler.getClass().getName());
        }
        Sampled sampled = new Sampled(textureView.nativeHandle(), metalSampler.nativeHandle());
        this.owner.useResource(textureView.nativeHandle());
        this.textureBindings.put(name, sampled);
        Metal4BindingPlan.Slot slot = slotFor(name, true);
        if (slot != null) {
            fillTexture(name, slot, sampled);
        }
        this.tablesAssigned = false;
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBuffer buffer) {
        setUniform(name, buffer.slice());
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBufferSlice slice) {
        declare(slice.buffer());
        long address = addressOf(slice.buffer(), slice.offset());
        this.uniformAddresses.put(name, address);
        Metal4BindingPlan.Slot slot = slotFor(name, false);
        if (slot != null) {
            fillAddress(name, slot, address);
        }
        this.tablesAssigned = false;
    }

    /**
     * A vertex layout, bound by address <em>and stride</em> at the slot the pipeline's vertex descriptor puts it
     * in. The stride is the pipeline's own vertex format, because it is the layout the shader was compiled to
     * read - a table bound without it would read a vertex per buffer rather than per vertex. A slot bound before
     * the pipeline is remembered with it and filled when the descriptor is known, the same way a named binding
     * is.
     */
    @Override
    public void setVertexBuffer(final int slot, final @NonNull GpuBufferSlice buffer) {
        declare(buffer.buffer());
        this.vertexBuffers.put(slot, buffer);
        Metal4BindingPlan plan = this.plan;
        if (plan != null) {
            fillVertexBuffer(plan, slot, buffer);
        }
        this.tablesAssigned = false;
    }

    /**
     * The slot the current pipeline gives this name for this kind of resource, or null where there is none.
     * <p>
     * <strong>A name the pipeline does not declare is skipped, and that is the game's own contract.</strong> The
     * engine hands every pass a fixed set of default uniforms - projection, model view, fog and the rest - and a
     * given pipeline reads some of them: the first forced Metal 4 run that got this far bound {@code Fog} while
     * the panorama pipeline was set, and that pipeline has no fog. The Metal 3 pass is built for exactly this: a
     * name goes into a map, a draw encodes the names the pipeline's argument buffer declares, and the others are
     * never encoded. Faulting instead made this path stricter than the reference it is being compared against,
     * which is a bug in the guard and not in the frame.
     * <p>
     * A name the pipeline declares as the <em>other kind</em> of resource is skipped for the same reason, and
     * that was measured too: one of the engine's own passes binds a uniform under a name whose pipeline declares
     * a texture, and the Metal 3 pass simply never encodes that buffer. Faulting made this path stricter than
     * the reference; the skip is reported under {@code -Dmetallum.metal4Trace} instead, so a pack bug is visible
     * to anyone looking rather than fatal to everyone rendering.
     */
    private Metal4BindingPlan.@Nullable Slot slotFor(final String name, final boolean texture) {
        if (this.pipeline == null) {
            return null;
        }
        Metal4BindingPlan.Slot slot = this.plan.slot(name, texture);
        if (slot != null) {
            return slot;
        }
        if (TRACE && this.plan.declares(name)) {
            Metallum.LOGGER.info("Metal 4 trace: '{}' is a {} in the frame path's binding and a {} in the"
                            + " pipeline's layout, so it is not encoded - the Metal 3 pass does the same",
                    name, texture ? "texture" : "buffer", texture ? "buffer" : "texture");
        }
        return null;
    }

    /** Points every table that reads this name at the buffer's GPU address, offset included. */
    private void fillAddress(final String name, final Metal4BindingPlan.Slot slot, final long address) {
        for (int stage : new int[]{MetalShaderStages.VERTEX, MetalShaderStages.FRAGMENT}) {
            MTL4ArgumentTable table = tableFor(stage);
            if (table == null || !slot.readBy(stage)) {
                continue;
            }
            if (!table.address(address, slot.metalIndex())) {
                throw new IllegalStateException("the Metal 4 table refused the binding '" + name + "' at buffer "
                        + slot.metalIndex() + " on " + stageName(stage));
            }
        }
    }

    /** The same for a texture and, where the plan has one beside it, the sampler that goes with it. */
    private void fillTexture(final String name, final Metal4BindingPlan.Slot slot, final Sampled sampled) {
        for (int stage : new int[]{MetalShaderStages.VERTEX, MetalShaderStages.FRAGMENT}) {
            MTL4ArgumentTable table = tableFor(stage);
            if (table == null || !slot.readBy(stage)) {
                continue;
            }
            if (!table.texture(sampled.texture(), slot.metalIndex())
                    || (slot.sampled() && !table.sampler(sampled.sampler(), slot.samplerMetalIndex()))) {
                throw new IllegalStateException("the Metal 4 table refused the binding '" + name + "' at texture "
                        + slot.metalIndex() + " on " + stageName(stage));
            }
        }
    }

    /** One remembered vertex layout into the table the current plan sized, by the pipeline's own stride. */
    private void fillVertexBuffer(final Metal4BindingPlan plan, final int slot, final GpuBufferSlice buffer) {
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
    }

    /**
     * Fills every remembered binding the new pipeline declares.
     * <p>
     * Called when a pipeline arrives, because the plan - and with it the tables - is what a remembered name is
     * resolved against. A remembered name this pipeline does not declare is skipped and not a fault: it was a
     * claim about an earlier layout or about the pass's own bindings, and a pipeline that does not read it has
     * nothing to say about it. A name this pipeline declares as the other kind of resource is skipped for the
     * same reason - the remembered value is stale for this layout, and whatever this pipeline reads is bound
     * when the frame path binds it.
     */
    private void applyBindings() {
        Metal4BindingPlan plan = this.plan;
        if (plan == null) {
            return;
        }
        this.uniformAddresses.forEach((name, address) -> {
            Metal4BindingPlan.Slot slot = plan.slot(name);
            if (slot != null && !slot.texture()) {
                fillAddress(name, slot, address);
            }
        });
        this.textureBindings.forEach((name, sampled) -> {
            Metal4BindingPlan.Slot slot = plan.slot(name);
            if (slot != null && !slot.buffer()) {
                fillTexture(name, slot, sampled);
            }
        });
        this.vertexBuffers.forEach((slot, buffer) -> fillVertexBuffer(plan, slot, buffer));
    }

    /**
     * The index buffer, remembered as the address the new model's indexed draw takes rather than as bound state.
     * The address arithmetic an indexed draw needs is done where the draw is encoded, because the engine's first
     * index and base vertex are per draw.
     */
    @Override
    public void setIndexBuffer(final @NonNull GpuBuffer buffer, final @NonNull IndexType type) {
        // The indexed draw's index buffer is an address, which is the case the header names by name: "Use an
        // instance of MTLResidencySet to mark residency of the index buffer the indexBuffer parameter
        // references."
        declare(buffer);
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
        this.indexedEncoded++;
        this.drawsEncoded++;
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: indexed draw {} of {} indices at {} of {} bytes, type {},"
                            + " instance {} base vertex {} in '{}'", this.indexedEncoded, indexCount, address,
                    length, this.indexTypeValue, instanceCount, vertexOffset, label());
        }
        if (!this.encoder.drawIndexedPrimitives(this.artifact.topology().value, indexCount, this.indexTypeValue,
                address, length, instanceCount, vertexOffset, firstInstance)) {
            throw new IllegalStateException("the Metal 4 encoder refused an indexed draw of " + indexCount
                    + " indices at address " + address + " of " + length + " bytes, type " + this.indexTypeValue
                    + ": " + this.encoder.refusal());
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
        this.drawsEncoded++;
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: draw {} of {} vertices from {}, instance {}, in '{}'",
                    this.drawsEncoded, vertexCount, firstVertex, instanceCount, label());
        }
        if (!this.encoder.drawPrimitives(this.artifact.topology().value, firstVertex, vertexCount, instanceCount,
                firstInstance)) {
            throw new IllegalStateException("the Metal 4 encoder refused a draw of " + vertexCount + " vertices: "
                    + this.encoder.refusal());
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

    /** The table the given stage reads through, or null where this pass has none for it. */
    @Nullable
    private MTL4ArgumentTable tableFor(final int stage) {
        return (stage & MetalShaderStages.VERTEX) != 0 ? this.vertexTable : this.fragmentTable;
    }

    /**
     * Declares the allocation behind an engine buffer, because the address this pass binds names it.
     * <p>
     * The address is what the table and the draw selector take; the allocation is what has to stay resident.
     */
    private void declare(final @NonNull GpuBuffer buffer) {
        if (buffer instanceof MetalGpuBuffer metal) {
            this.owner.useResource(metal.metalBuffer().handle());
        }
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
        MTL4ArgumentTable vertex = this.vertexTable;
        MTL4ArgumentTable fragment = this.fragmentTable;
        this.vertexTable = null;
        this.fragmentTable = null;
        // Filed with the frame rather than closed here. A table's contents are what the GPU reads when it runs
        // the command buffer, and at the moment a pass ends this path does not know the frame has even been
        // committed - so the honest lifetime is the frame's, which is the one the frame encoder can prove: a
        // slot's releases run only once that slot's submission has been observed complete. Closing a table here
        // was releasing it between encoding and execution.
        if (vertex != null) {
            this.owner.queueForDestroy(vertex::close);
        }
        if (fragment != null) {
            this.owner.queueForDestroy(fragment::close);
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
