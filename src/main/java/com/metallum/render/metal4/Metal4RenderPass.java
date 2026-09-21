package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLArgumentEncoder;
import com.metallum.mtl.MTLBuffer;
import com.metallum.mtl.MTLHazardTrackingMode;
import com.metallum.mtl.MTLIndexType;
import com.metallum.mtl.MTLResourceOptions;
import com.metallum.mtl.MTLStorageMode;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
import com.metallum.mtl.metal4.Metal4BindingPlan;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.objc.ObjC;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalArgumentBufferLayout;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalPassUniformWriter;
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
 * <strong>What it does is the pass itself and the work encoded into it.</strong> It resolves the descriptor's
 * colour and depth attachments - including the two facts the descriptor does not carry, which arrive from the
 * frame encoder through {@code MetalFrameExtras} and become this pass's load and store actions - checks that the
 * attachments agree on an extent and that the render area lies inside it, the same two rules the Metal 3 pass
 * applies because a pass that lied about either would be a wrong image rather than an error message, and opens
 * the pass through {@link MTL4RenderEncoder}, where the attachment mapping is already measured on the device.
 * The pipeline, the bindings, the scissor rectangle and the draws - direct, indexed and indexed-indirect - are
 * encoded into that encoder through the frame's binding plan and the argument tables it sizes.
 * <p>
 * <strong>A wide pipeline's bindings take one more step, and it is the same step on both generations.</strong>
 * Where a program's resources do not fit MSL's direct slots - which on this machine means a sampler index past
 * fifteen, since a table holds sixteen samplers and MSL declares one per sampled image - the compiler lays the
 * program out for an argument buffer and this pass fills one through the shader's own
 * {@link MTLArgumentEncoder}, then points a table buffer slot at it. What is Metal 4's own is that last step: the
 * reference generation hands the buffer to the encoder directly, and this one hands the table its GPU address.
 * <p>
 * <strong>What it cannot encode refuses by name.</strong> The shapes this path has not reached - a multi-draw, an
 * indirect draw whose arguments are several commands in one buffer, a storage-image bind - raise
 * {@link Metal4ExecutionProvider.Unimplemented} named for the operation, so a pack that reached one is told which
 * operation the Metal 4 path does not have rather than being handed a pass that drew nothing. The debug group is
 * the deliberate exception: it is a capture label and not work, so pushing and popping it is a no-op rather than
 * a refusal - dropping a label costs a reader nothing, while dropping a draw would be the half frame the plan
 * forbids.
 * <p>
 * <strong>The barrier is encoded at the end of every pass</strong> and before the encoder is ended. Only the
 * pass that <em>reads</em> an attachment knows whether a dependency exists, and each logical pass on this path is
 * its own native encoder, so the boundary a caller states through {@code MetalFrameExtras} - "the next pass reads
 * a storage image written since the live encoder opened" - is one this path encodes unconditionally for every
 * pass. That is the migration's rule for this stage: over-synchronise while the path is being built, and narrow
 * it when a counter says what the narrowing buys.
 */
@Environment(EnvType.CLIENT)
final class Metal4RenderPass implements RenderPassBackend, MetalPassUniformWriter {

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
    private final Map<String, GpuBufferSlice> uniformBindings = new LinkedHashMap<>();
    private final Map<String, Sampled> textureBindings = new LinkedHashMap<>();
    /** The vertex layouts by the game's own slot, which the pipeline's descriptor numbers from its own base. */
    private final Map<Integer, GpuBufferSlice> vertexBuffers = new LinkedHashMap<>();

    /**
     * The argument buffers this pass's wide pipelines write their resources into, one per descriptor set per
     * stage, made when a wide pipeline is set.
     * <p>
     * <strong>The buffer is the pass's, not the pipeline's.</strong> Its size is the layout's and its contents
     * are this pass's bindings, and two pipelines that share a descriptor set layout share the shape a draw reads
     * - so the map is keyed by the shared layout record, which carries the stage, the set and the length. It is
     * dropped when the pipeline's artifact changes, because a buffer made for another artifact's layout is the
     * wrong length for this one; the buffers themselves are not closed there, because at that moment the GPU may
     * still be reading them, and they are already filed with the frame.
     */
    private final Map<MetalArgumentBufferLayout, MTLBuffer> argumentBufferStates = new LinkedHashMap<>();

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

    /**
     * How far one indirect indexed draw's arguments are from the next: five 32-bit members, which is
     * {@code MTLDrawIndexedPrimitivesIndirectArguments} in this machine's {@code MTLRenderCommandEncoder.h}.
     */
    private static final long INDIRECT_ARGUMENTS_BYTES = 20L;

    /** The scissor rectangle, applied when a draw is encoded rather than when it is asked for. */
    private boolean scissorEnabled;
    private long scissorX;
    private long scissorY;
    private long scissorWidth;
    private long scissorHeight;

    Metal4RenderPass(final Metal4FrameEncoder owner, final RenderPassDescriptor descriptor,
                     final @Nullable AttachmentContents[] contents) {
        this.owner = owner;
        this.descriptor = descriptor;

        List<RenderPassDescriptor.Attachment<Optional<Vector4fc>>> attachments = descriptor.colorAttachments();
        if (attachments.size() > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalArgumentException("Render pass declares " + attachments.size() + " colour attachment"
                    + " slots, Metal supports at most " + MAX_COLOR_ATTACHMENTS);
        }
        // One answer per slot with the default filled in, so the loop below reads a fact rather than a null it
        // has to interpret - and the same defaulting the Metal 3 path applies, because the two generations have
        // to agree about what a pass that said nothing gets.
        AttachmentContents[] stated = AttachmentContents.resolve(contents, attachments.size());
        // Kept for the trace line below: what the pass was told about each slot, and which texture slot 0 wrote.
        // The question this answers is what the presented frame holds outside the pixels a pass covers - a sky
        // strip that is rendered on one generation and a clear colour on the other - and neither "which target"
        // nor "which load action" can be read out of a picture taken at present.
        this.statedContents = stated;
        this.colourHandles = new MemorySegment[attachments.size()];

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
            this.colourHandles[index] = attachmentTexture;
            if (index == 0) {
                this.cleared0 = clear != null;
            }
            // Declared resident, because an attachment is read and written as a resource the command buffer
            // names by object: this is the half of residency that is not about addresses, and the frame path
            // declares both from the same place.
            this.owner.useResource(attachmentTexture);
            // What this pass was told about the slot, whose two facts become the descriptor's load and store
            // actions inside the layer that opens it - and the byte counter reads the same decision there, so a
            // reading of what a frame costs cannot drift from what Metal was asked for.
            AttachmentContents slotContents = stated[index];
            MTL4RenderEncoder.Color color = new MTL4RenderEncoder.Color(attachmentTexture, slotContents,
                    clear == null ? null : new float[]{clear.x(), clear.y(), clear.z(), clear.w()});
            MTL4RenderEncoder.countAttachment(color, pixelSize(view));
            colors[index] = color;
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
            // A cleared depth attachment is handed the clear value rather than what stood there, which is the
            // one slot the pack side cannot answer for and therefore the one whose traffic has to be counted
            // from what this pass actually asked for.
            boolean depthCleared = depthAttachment.clearValue().isPresent();
            MTL4RenderEncoder.Depth depthAttachmentValue = new MTL4RenderEncoder.Depth(depthTexture,
                    depthCleared ? depthAttachment.clearValue().getAsDouble() : null);
            MTL4RenderEncoder.countDepthAttachment(depthAttachmentValue, pixelSize(view));
            depth = depthAttachmentValue;
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
            owner.statEncoder();
            MetalFrameProbe.encoderOpened(0);
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
        // Reported to the frame's counters whether or not the per-draw trace is on: the counters are what
        // answer "what did a frame cost", and a pass is the unit a cost is attributed to.
        this.owner.statPass(this.drawsEncoded, this.indexedEncoded);
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: end pass '{}' depth={} draws={} indexed={} scissor={} colours={}"
                            + " load={} store={} clear={} samples=[{}]",
                    label(), this.depthAttached, this.drawsEncoded, this.indexedEncoded, this.scissorEnabled,
                    colours(), load0(), store0(), this.cleared0, sampledTextures());
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
        // Behind the encoder, which is what makes it this pass's own completion: MTL4CommandBuffer.h says the
        // marker captures the moment prior work is complete, and the work here is this pass.
        this.owner.recordPassBoundary(label());
    }

    /** What the pass was told about each colour slot, and the texture each slot wrote, for the trace line. */
    private AttachmentContents @Nullable [] statedContents;
    private MemorySegment @Nullable [] colourHandles;
    private boolean cleared0;

    /**
     * The textures this pass *sampled*, by the name the pack bound them under, so a pass's reads and its writes can
     * be compared in one line.
     * <p>
     * This is the second half of a question the attachments alone could not answer: on a target the pack doubles
     * for history, two physical textures stand for one logical name, and a pass that samples the copy it is about
     * to write reads its own target's initial content instead of what the pass before it wrote. Attachments say
     * which copy each pass wrote; this says which copy each one read.
     */
    private String sampledTextures() {
        if (this.textureBindings.isEmpty()) {
            return "none";
        }
        StringBuilder text = new StringBuilder();
        int shown = 0;
        for (Map.Entry<String, Sampled> entry : this.textureBindings.entrySet()) {
            if (shown++ == 8) {
                text.append(",...");
                break;
            }
            if (text.length() > 0) {
                text.append(',');
            }
            text.append(entry.getKey()).append("=0x").append(Long.toHexString(entry.getValue().texture().address()));
        }
        return text.toString();
    }

    /**
     * Every colour texture this pass attached, as handles, so a reader can tell which target a pass wrote - and,
     * for a clear pass, which targets it emptied. One is not enough for the second question: a pass that clears
     * four targets is four attachments, and a pack's history target that must *not* be cleared is only visible as
     * an absence from this list.
     */
    private String colours() {
        MemorySegment[] handles = this.colourHandles;
        if (handles == null || handles.length == 0) {
            return "none";
        }
        StringBuilder text = new StringBuilder();
        for (MemorySegment handle : handles) {
            if (text.length() > 0) {
                text.append(',');
            }
            text.append(handle == null ? "-" : "0x" + Long.toHexString(handle.address()));
        }
        return text.toString();
    }

    /** The load action the pass's first colour slot was given, in the layer's own vocabulary. */
    private String load0() {
        AttachmentContents[] contents = this.statedContents;
        if (contents == null || contents.length == 0) {
            return "none";
        }
        return actionName(MTL4RenderEncoder.loadAction(contents[0], this.cleared0),
                MTL4RenderEncoder.LOAD_LOAD, MTL4RenderEncoder.LOAD_CLEAR, MTL4RenderEncoder.LOAD_DONT_CARE);
    }

    /** The store action the pass's first colour slot was given. */
    private String store0() {
        AttachmentContents[] contents = this.statedContents;
        if (contents == null || contents.length == 0) {
            return "none";
        }
        return MTL4RenderEncoder.storeAction(contents[0]) == MTL4RenderEncoder.STORE_STORE ? "store" : "dontcare";
    }

    private static String actionName(final long action, final long load, final long clear, final long dontCare) {
        if (action == load) {
            return "load";
        }
        if (action == clear) {
            return "clear";
        }
        return action == dontCare ? "dontcare" : Long.toString(action);
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
     * <p>
     * <strong>And it is said out loud, once per operation, because a thrown refusal is not the same thing as a
     * visible one.</strong> Section 35 forbids silently dropping an operation, and a throw satisfies it only for
     * a caller that lets it out: the first no-pack Metal 4 session measured this exactly - the presented frame
     * was one flat clear colour for every one of its 4958 frames, the world's `Terrain` pass ended with
     * `draws=0` on all 5316 of its traced passes, and the session's log named nothing at all, because the game's
     * terrain batching calls a multi-draw, this pass refuses it by throwing, and the caller catches the throw and
     * moves on. So the refusal is logged here, before it is thrown, with the pass it happened in.
     */
    private Metal4ExecutionProvider.Unimplemented unimplemented(final String operation) {
        if (REFUSED_OPERATIONS.add(operation)) {
            Metallum.LOGGER.warn("Metal 4 render pass '{}': {} is not encoded by this path yet, so the work that"
                            + " asked for it did not happen. This is the refusal by name section 35 asks for, said"
                            + " here as well as thrown, because a caller that catches the throw would otherwise"
                            + " drop the work with nothing in the log",
                    label(), operation);
        }
        return new Metal4ExecutionProvider.Unimplemented(operation,
                "the Metal 4 render pass does not encode " + operation + " yet: the frame path is still Metal 3's,"
                        + " and this pass refuses by name rather than drawing nothing");
    }

    /**
     * Which refusals have already been logged, so the line is one per operation per session rather than one per
     * draw: the terrain's batching asks for the same missing operation hundreds of times a frame. It holds names
     * and nothing else and no decision is taken from it.
     */
    private static final java.util.Set<String> REFUSED_OPERATIONS = java.util.concurrent.ConcurrentHashMap.newKeySet();

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
        if (this.artifact != compiled) {
            // A different layout means different argument buffers: their sizes come from the encoders this
            // artifact owns, and a buffer made for another pipeline's layout is the wrong length for this one.
            // The old buffers are not closed here - they are already filed with the frame, because at this
            // moment the GPU may still be reading them.
            this.argumentBufferStates.clear();
        }

        this.pipeline = pipeline;
        this.artifact = compiled;
        this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.argumentBufferLayouts(),
                compiled.firstAvailableVertexBufferSlot(), compiled.vertexBufferCount());
        releaseTables();
        this.owner.statTables(this.plan.usesStage(MetalShaderStages.VERTEX) ? 1L : 0L
                + (this.plan.usesStage(MetalShaderStages.FRAGMENT) ? 1L : 0L));
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
        ensureArgumentBuffers();
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
        this.uniformBindings.put(name, slice);
        Metal4BindingPlan.Slot slot = slotFor(name, false);
        if (slot != null) {
            fillAddress(name, slot, slice);
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
    private void fillAddress(final String name, final Metal4BindingPlan.Slot slot, final GpuBufferSlice slice) {
        MetalFrameProbe.bufferBound();
        if (slot.indirect()) {
            MetalGpuBuffer buffer = bufferOf(slice);
            forEachArgumentLayout(slot, layout -> {
                MTLArgumentEncoder encoder = bindArgumentBuffer(layout);
                MetalFrameProbe.argBufferBufferWrite();
                encoder.setBuffer(buffer.metalBuffer(), slice.offset(), slot.metalIndex());
            });
            return;
        }
        long address = addressOf(slice.buffer(), slice.offset());
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
        MetalFrameProbe.textureBound();
        if (slot.sampled()) {
            MetalFrameProbe.samplerBound();
        }
        if (slot.indirect()) {
            forEachArgumentLayout(slot, layout -> {
                MTLArgumentEncoder encoder = bindArgumentBuffer(layout);
                MetalFrameProbe.argBufferTextureWrite();
                encoder.setTexture(sampled.texture(), slot.metalIndex());
                if (slot.sampled()) {
                    MetalFrameProbe.argBufferSamplerWrite();
                    encoder.setSamplerState(sampled.sampler(), slot.samplerMetalIndex());
                }
            });
            return;
        }
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

    /**
     * Runs the work for every argument buffer that carries this binding, which is one per stage that reads it.
     * <p>
     * A binding read by both stages lives in both stages' sets and has to be written into both buffers, and a
     * binding whose set no layout covers is a translation and an artifact that disagree - the shape the plan
     * exists to make impossible, and a fault rather than a silently unbound resource.
     */
    private void forEachArgumentLayout(final Metal4BindingPlan.Slot slot,
                                       final java.util.function.Consumer<MetalArgumentBufferLayout> consumer) {
        boolean matched = false;
        for (Metal4CompiledRenderPipeline.ArgumentBufferLayout layout : this.artifact.argumentBuffers()) {
            if (layout.descriptorSet() != slot.argumentBufferSet()
                    || (layout.stageMask() & slot.stageMask()) == 0) {
                continue;
            }
            consumer.accept(layout.layout());
            matched = true;
        }
        if (!matched) {
            throw new IllegalStateException("no Metal 4 argument buffer carries '" + slot.name() + "' set="
                    + slot.argumentBufferSet() + " stages=" + slot.stageMask()
                    + ", so the pipeline's layout and its artifact disagree");
        }
    }

    /**
     * Makes and points every argument buffer this pipeline's tables expect, before anything is drawn.
     * <p>
     * <strong>Every layout, and not only the ones a binding has already asked for.</strong> A wide pipeline's
     * table carries one buffer slot per descriptor set, and the shader dereferences whatever address is in it -
     * so a set whose resources happen to be bound after the first draw, or not at all, would still have its slot
     * read. Allocating the layout's own buffers up front is the reference generation's order too.
     */
    private void ensureArgumentBuffers() {
        for (Metal4CompiledRenderPipeline.ArgumentBufferLayout layout : this.artifact.argumentBuffers()) {
            bindArgumentBuffer(layout.layout());
        }
    }

    /**
     * The argument buffer for one layout, made on first use and pointed at the table slot it belongs in.
     * <p>
     * The buffer is made from the device with shared storage and tracked hazards, which is what the Metal 3 pass
     * makes and for the same reason: this path writes it from the CPU between draws and the driver has to be
     * able to order those writes against the reads. The address goes into the same stage's table at the slot the
     * shared layout recorded, which is this generation's half of the mechanism - the reference generation hands
     * the buffer to the encoder directly.
     * <p>
     * The length is floored at one byte because Metal will not make a zero-length buffer and an argument buffer
     * whose layout encodes nothing is a real pipeline.
     */
    private MTLArgumentEncoder bindArgumentBuffer(final MetalArgumentBufferLayout layout) {
        Metal4CompiledRenderPipeline.ArgumentBufferLayout layoutWithEncoder = null;
        for (Metal4CompiledRenderPipeline.ArgumentBufferLayout candidate : this.artifact.argumentBuffers()) {
            if (candidate.layout().equals(layout)) {
                layoutWithEncoder = candidate;
                break;
            }
        }
        if (layoutWithEncoder == null) {
            throw new IllegalStateException("the Metal 4 pass was asked to fill argument buffer set "
                    + layout.descriptorSet() + " and the pipeline has no encoder for it");
        }

        MTLBuffer buffer = this.argumentBufferStates.get(layout);
        if (buffer == null) {
            long length = Math.max(1L, layout.encodedLength());
            MTLBuffer created = this.owner.nativeDevice().newBuffer(length,
                    MTLResourceOptions.of(MTLStorageMode.Shared, MTLHazardTrackingMode.Tracked));
            if (created == null) {
                throw new IllegalStateException("the Metal 4 pass could not make the argument buffer for set "
                        + layout.descriptorSet() + " (" + length + " bytes)");
            }
            MetalFrameProbe.argBufferAllocated(length);
            this.owner.queueForDestroy(() -> ObjC.release(created.handle()));
            this.argumentBufferStates.put(layout, created);
            buffer = created;
        }
        MetalFrameProbe.argBufferSet();
        this.owner.useResource(buffer.handle());
        layoutWithEncoder.encoder().setArgumentBuffer(buffer, 0L);

        MTL4ArgumentTable table = tableFor(layout.stageMask());
        if (table == null || !table.address(buffer.gpuAddress(), layout.bufferIndex())) {
            throw new IllegalStateException("the Metal 4 table for " + stageName(layout.stageMask())
                    + " refused the argument buffer for set " + layout.descriptorSet() + " at table index "
                    + layout.bufferIndex());
        }
        return layoutWithEncoder.encoder();
    }

    /** The engine's own buffer behind a slice, which is what an argument encoder is handed. */
    private static MetalGpuBuffer bufferOf(final GpuBufferSlice slice) {
        if (!(slice.buffer() instanceof MetalGpuBuffer metal)) {
            throw new IllegalStateException("the Metal 4 pass was handed a buffer that is not this engine's: "
                    + slice.buffer().getClass().getName());
        }
        return metal;
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
        this.uniformBindings.forEach((name, slice) -> {
            Metal4BindingPlan.Slot slot = plan.slot(name);
            if (slot != null && !slot.texture()) {
                fillAddress(name, slot, slice);
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

    /**
     * The indirect indexed form: one command per draw, each read out of the arguments buffer.
     * <p>
     * The index buffer is bound state in the game's API as it is in Metal 3, so what the arguments name is a
     * range of it, and what the caller hands over is a slice of a buffer holding one
     * {@code MTLDrawIndexedPrimitivesIndirectArguments} per draw. Twenty bytes apart, then - the same stride the
     * Metal 3 pass advances by through {@code VkDrawIndexedIndirectCommand.SIZEOF} - and the arguments buffer is
     * declared resident, because the header asks for exactly that on this command.
     * <p>
     * The index buffer's length is its whole bound length and not a per-draw remainder: {@code indexStart} lives
     * in the GPU's copy of the arguments, so the CPU does not know where the range begins - which is the point of
     * an indirect draw. The header is explicit about what happens at the end of it: indices at or beyond the
     * length are executed with a {@code vertex_id} of 0 rather than faulting.
     */
    @Override
    public void drawIndexedIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {
        if (!prepareDraw("drawIndexedIndirect")) {
            return;
        }
        if (this.indexBufferAddress == 0L) {
            throw new IllegalStateException("the Metal 4 pass was asked for an indirect indexed draw with no index"
                    + " buffer bound, so there is nothing for the arguments to index into");
        }
        declare(commands.buffer());
        long indirect = addressOf(commands.buffer(), commands.offset());
        for (int draw = 0; draw < drawCount; draw++) {
            if (!this.encoder.drawIndexedPrimitivesIndirect(this.artifact.topology().value, this.indexTypeValue,
                    this.indexBufferAddress, this.indexBufferLength, indirect)) {
                throw new IllegalStateException("the Metal 4 encoder refused an indirect indexed draw at arguments"
                        + " address " + indirect + " (draw " + draw + " of " + drawCount + "): "
                        + this.encoder.refusal());
            }
            // Counted like the direct and indexed draws, because this *is* an indexed draw and the counters are
            // what the trace line and the frame's own `drawsPerFrame` are made of. Leaving them out made the
            // world's terrain pass read `draws=0` on every one of its endings while the world was drawing
            // perfectly well through this path - Sodium batches its terrain as indirect draws - and that reading
            // sent two rounds of localisation looking for a pass that was never empty.
            this.indexedEncoded++;
            this.drawsEncoded++;
            indirect += INDIRECT_ARGUMENTS_BYTES;
        }
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
        MetalFrameProbe.pipelineBound();
        if (!this.encoder.setRenderPipelineState(this.artifact.pipelineState(this.depthAttached))) {
            throw new IllegalStateException("the Metal 4 encoder refused the pipeline state for "
                    + this.pipeline.getLocation());
        }
        this.encoder.setDepthStencilState(this.artifact.depthStencilState());
        // The bias the pipeline asked for, sent where the reference sends it: the Metal 3 pass calls
        // `setDepthBias(constant, slopeScale, 0.0f)` right after the depth-stencil state, and a generation that
        // skipped it would draw decals and shadow-offset geometry at a different depth from the reference's.
        // The clamp is zero, which the header says disables clamping.
        if (this.artifact.depthBiasConstant() != 0.0f || this.artifact.depthBiasScaleFactor() != 0.0f) {
            MetalFrameProbe.depthBiasApplied();
        }
        this.encoder.setDepthBias(this.artifact.depthBiasConstant(), this.artifact.depthBiasScaleFactor(), 0.0f);
        this.encoder.setCullMode(this.artifact.cullMode().value);
        this.encoder.setTriangleFillMode(this.artifact.fillMode().value);
        if (this.scissorEnabled || this.scissorWidth > 0L || this.scissorHeight > 0L) {
            MetalFrameProbe.scissorSet();
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
     * A mapped slice of the frame's transient arena, for a draw path that writes its own uniforms.
     * <p>
     * This is the push-constant half of the pass: the sodium chunk renderer allocates twenty bytes, writes a
     * region's camera translation and identifiers into them, and binds the slice under a name - so what it needs
     * from a pass is "somewhere to write" and "a way to bind what you wrote", which is the whole of
     * {@link MetalPassUniformWriter}. The arena is the frame's own, which is what makes the slice's lifetime the
     * frame's: it is rotated by the frame encoder once the submission that reads it has been made, and the caller
     * frees its view at the end of its own block.
     */
    @Override
    public GpuBufferSlice.MappedView allocateTransient(final long size, final long alignment, final int usage) {
        return this.owner.transientMemory().allocateGpuMapped(size, alignment, usage);
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

    /** How many bytes one pixel of this attachment is, which is what its load and store are counted in. */
    private static int pixelSize(final GpuTextureView view) {
        return view.texture() instanceof MetalGpuTexture texture ? texture.pixelSize() : 0;
    }

    /**
     * The GPU address a slice of an engine buffer starts at, which is what a table binds.
     * <p>
     * Package-private because the compute dispatch binds buffers the same way and this is the one place that says
     * what an address of a slice is: a second copy of this addition is a second chance to leave the offset out.
     */
    static long addressOf(final GpuBuffer buffer, final long offset) {
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
