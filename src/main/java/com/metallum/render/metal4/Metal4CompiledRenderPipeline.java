package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLBlendFactor;
import com.metallum.mtl.MTLBlendOperation;
import com.metallum.mtl.MTLColorWriteMask;
import com.metallum.mtl.MTLCompareFunction;
import com.metallum.mtl.MTLCullMode;
import com.metallum.mtl.MTLPixelFormat;
import com.metallum.mtl.MTLPrimitiveType;
import com.metallum.mtl.MTLRenderPipelineDescriptor;
import com.metallum.mtl.MTLTriangleFillMode;
import com.metallum.mtl.MTLVertexDescriptor;
import com.metallum.mtl.MTLVertexFormat;
import com.metallum.mtl.MTLVertexStepFunction;
import com.metallum.objc.ObjC;
import com.metallum.render.shared.MetalCompiledArtifact;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalPipelineKey;
import com.metallum.render.shared.MetalResourceBinding;
import com.metallum.render.shared.MetalShaderStages;
import com.mojang.blaze3d.pipeline.BlendFunction;
import com.mojang.blaze3d.pipeline.ColorTargetState;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.platform.PolygonMode;
import com.mojang.blaze3d.vertex.VertexFormat;
import com.mojang.blaze3d.vertex.VertexFormatElement;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.util.BitSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * A compiled Metal 4 pipeline: the native pipeline states this generation draws with, and the binding facts the
 * pass will need to fill an argument table.
 * <p>
 * <strong>It is the generation's own artifact.</strong> The resources, the key and the pipeline's rendering state
 * come from the shared translation, which is generation-neutral by construction; the pipeline states, the vertex
 * descriptor and the depth-stencil state are Metal's, and they are made here rather than borrowed from the Metal
 * 3 artifact - {@code render.metal4} may not import {@code render.metal3}.
 * <p>
 * <strong>One deliberate difference from the Metal 3 artifact: no argument buffers.</strong> The Metal 3 path
 * can carry a wide pipeline's resources in an argument buffer, and the shared translator will emit that shape
 * when it is asked to. This generation asks it not to: Metal 4's binding mechanism is the argument <em>table</em>,
 * and a pipeline translated for argument buffers would be handed the Metal 3 mechanism inside the new path. That
 * leaves the sampler ceiling as the open question it already is (the probe measured the by-id alternative), and
 * it makes {@link #resources()} a list of direct bindings, each with the metal index the MSL was compiled
 * against - which is what a table slot is filled from.
 * <p>
 * Two pipeline states are built, with and without a depth format, for the same reason the Metal 3 artifact keeps
 * two: a Metal pipeline state names its depth format at creation, and a pass that has no depth attachment is not
 * a pass that can use the one made for depth.
 */
@Environment(EnvType.CLIENT)
final class Metal4CompiledRenderPipeline implements CompiledRenderPipeline, MetalCompiledArtifact, AutoCloseable {

    private static final int MAX_COLOR_ATTACHMENTS = 8;

    private final MetalPipelineKey pipelineKey;
    private final List<MetalResourceBinding> resources;
    private final Map<String, MetalResourceBinding> resourcesByName;
    private final BitSet allResources;
    private final int firstAvailableVertexBufferSlot;
    private final int vertexBufferCount;
    private final MTLCullMode cullMode;
    private final MTLTriangleFillMode fillMode;
    private final MTLPrimitiveType topology;
    private final float depthBiasScaleFactor;
    private final float depthBiasConstant;
    private final MemorySegment depthStencilState;
    private final MemorySegment withDepthPipeline;
    private final MemorySegment withoutDepthPipeline;

    Metal4CompiledRenderPipeline(
            final MetalPipelineKey pipelineKey,
            final Metal4CompilationContext compilation,
            final RenderPipeline info,
            final String vertexMsl,
            final String fragmentMsl,
            final String vertexEntryPoint,
            final String fragmentEntryPoint,
            final List<MetalResourceBinding> resources
    ) {
        this.pipelineKey = pipelineKey;
        this.resources = List.copyOf(resources);
        this.resourcesByName = this.resources.stream().collect(Collectors.toUnmodifiableMap(
                MetalResourceBinding::name, binding -> binding));

        BitSet resourceBits = new BitSet();
        for (MetalResourceBinding binding : this.resources) {
            if (binding.bindingIndex() < 0) {
                throw new IllegalStateException("Pipeline " + info.getLocation() + " has negative logical binding"
                        + " index " + binding.bindingIndex());
            }
            resourceBits.set(binding.bindingIndex());
        }
        this.allResources = resourceBits;

        // Where the vertex buffers start in the buffer table: past every buffer the shader binds by name, which
        // is what the shared translation decided when it numbered them.
        this.firstAvailableVertexBufferSlot = firstAvailableVertexBufferSlot(this.resources);
        this.vertexBufferCount = info.getVertexFormatBindings().length;
        if (this.firstAvailableVertexBufferSlot + this.vertexBufferCount > 31) {
            throw new IllegalStateException("Pipeline " + info.getLocation() + " requires vertex buffer slot "
                    + (this.firstAvailableVertexBufferSlot + this.vertexBufferCount - 1)
                    + ", beyond Metal's 0..30 buffer table");
        }

        this.cullMode = info.isCull() ? MTLCullMode.Back : MTLCullMode.None;
        this.fillMode = info.getPolygonMode() == PolygonMode.WIREFRAME
                ? MTLTriangleFillMode.Lines
                : MTLTriangleFillMode.Fill;
        this.topology = MTLPrimitiveType.from(info.getPrimitiveTopology());

        var depthStencil = info.getDepthStencilState();
        MTLCompareFunction depthCompareOp;
        int depthWrite;
        if (depthStencil == null) {
            depthCompareOp = MTLCompareFunction.Always;
            depthWrite = 0;
            this.depthBiasScaleFactor = 0.0f;
            this.depthBiasConstant = 0.0f;
        } else {
            depthCompareOp = MTLCompareFunction.from(depthStencil.depthTest());
            depthWrite = depthStencil.writeDepth() ? 1 : 0;
            this.depthBiasScaleFactor = depthStencil.depthBiasScaleFactor();
            this.depthBiasConstant = depthStencil.depthBiasConstant();
        }
        this.depthStencilState = compilation.depthStencilState(depthCompareOp, depthWrite != 0);

        ColorTargetState[] colorTargets = info.getColorTargetStates();
        if (colorTargets.length > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalStateException("Pipeline " + info.getLocation() + " declares " + colorTargets.length
                    + " colour targets, Metal supports at most " + MAX_COLOR_ATTACHMENTS);
        }

        MemorySegment vertexFunction = compilation.getOrCompileFunction(vertexMsl, vertexEntryPoint);
        MemorySegment fragmentFunction = compilation.getOrCompileFunction(fragmentMsl, fragmentEntryPoint);
        try (MTLVertexDescriptor vertexDescriptor = buildVertexDescriptor(info,
                this.firstAvailableVertexBufferSlot)) {
            this.withDepthPipeline = createPipeline(compilation, info, vertexFunction, fragmentFunction,
                    vertexDescriptor, colorTargets, MTLPixelFormat.Depth32Float);
            this.withoutDepthPipeline = createPipeline(compilation, info, vertexFunction, fragmentFunction,
                    vertexDescriptor, colorTargets, MTLPixelFormat.Invalid);
        }
    }

    /**
     * Builds one native pipeline state.
     * <p>
     * The descriptor is filled exactly as the Metal 3 artifact fills it - colour formats slot by slot, blend or
     * no blend with the pipeline's write mask, the vertex descriptor, the depth format - because these are the
     * pipeline's own facts and a generation does not get to reinterpret them.
     */
    private static MemorySegment createPipeline(
            final Metal4CompilationContext compilation,
            final RenderPipeline info,
            final MemorySegment vertexFunction,
            final MemorySegment fragmentFunction,
            final MTLVertexDescriptor vertexDescriptor,
            final ColorTargetState[] colorTargets,
            final MTLPixelFormat depthFormat
    ) {
        if (ObjC.isNil(vertexFunction) || ObjC.isNil(fragmentFunction)) {
            return MemorySegment.NULL;
        }
        try (MTLRenderPipelineDescriptor descriptor = new MTLRenderPipelineDescriptor()) {
            descriptor.setCompiledFunctions(vertexFunction, fragmentFunction);
            descriptor.setVertexDescriptor(vertexDescriptor);
            descriptor.setDepthStencilFormats(depthFormat, MTLPixelFormat.Invalid);
            for (int index = 0; index < colorTargets.length; index++) {
                ColorTargetState colorTarget = colorTargets[index];
                if (colorTarget == null) {
                    descriptor.setColorAttachmentFormat(index, MTLPixelFormat.Invalid);
                    descriptor.disableBlending(index, MTLColorWriteMask.None.value);
                    continue;
                }
                descriptor.setColorAttachmentFormat(index, MTLPixelFormat.from(colorTarget.format()));
                Optional<BlendFunction> blendFunction = colorTarget.blendFunction();
                long writeMask = MTLColorWriteMask.from(colorTarget.writeMask());
                if (blendFunction.isPresent()) {
                    var function = blendFunction.get();
                    descriptor.setBlendState(
                            index,
                            MTLBlendFactor.from(function.color().sourceFactor()),
                            MTLBlendFactor.from(function.color().destFactor()),
                            MTLBlendOperation.from(function.color().op()),
                            MTLBlendFactor.from(function.alpha().sourceFactor()),
                            MTLBlendFactor.from(function.alpha().destFactor()),
                            MTLBlendOperation.from(function.alpha().op()),
                            writeMask
                    );
                } else {
                    descriptor.disableBlending(index, writeMask);
                }
            }

            long startNanos = System.nanoTime();
            MemorySegment pipeline = compilation.device().newRenderPipelineState(descriptor);
            MetalFrameProbe.pipelineCompiled(System.nanoTime() - startNanos);
            if (ObjC.isNil(pipeline)) {
                Metallum.LOGGER.error("[metallum] Metal 4 pipeline {} failed to build with {} colour target slots"
                        + " and depth format {}", info.getLocation(), colorTargets.length, depthFormat);
            }
            return pipeline;
        }
    }

    /** The vertex layouts the pipeline declares, in the buffer slots the shared translation left free. */
    private static MTLVertexDescriptor buildVertexDescriptor(final RenderPipeline info,
                                                             final int firstAvailableBufferSlot) {
        MTLVertexDescriptor descriptor = new MTLVertexDescriptor();
        long attributeIndex = 0L;
        int bindingCount = info.getVertexFormatBindings().length;
        for (int binding = 0; binding < bindingCount; binding++) {
            VertexFormat format = info.getVertexFormatBinding(binding);
            if (format == null || format.getElements().isEmpty()) {
                continue;
            }
            int bufferIndex = firstAvailableBufferSlot + binding;
            long stepRate = format.getStepRate();
            MTLVertexStepFunction stepFunction =
                    stepRate > 0 ? MTLVertexStepFunction.PerInstance : MTLVertexStepFunction.PerVertex;
            descriptor.setLayout(bufferIndex, format.getVertexSize(), stepFunction, stepRate > 0 ? stepRate : 1L);
            for (VertexFormatElement element : format.getElements()) {
                MTLVertexFormat vertexFormat = MTLVertexFormat.from(element.format());
                if (vertexFormat == MTLVertexFormat.Invalid) {
                    throw new IllegalStateException("Unsupported vertex attribute format: " + element.format());
                }
                descriptor.setAttribute(attributeIndex, vertexFormat.value, element.offset(), bufferIndex);
                attributeIndex++;
            }
        }
        return descriptor;
    }

    /** The first buffer slot no named vertex-stage buffer uses, which is where the vertex layouts begin. */
    private static int firstAvailableVertexBufferSlot(final List<MetalResourceBinding> resources) {
        int highest = -1;
        for (MetalResourceBinding resource : resources) {
            if ((resource.kind() == MetalResourceBinding.ResourceKind.UNIFORM_BUFFER
                    || resource.kind() == MetalResourceBinding.ResourceKind.STORAGE_BUFFER)
                    && (resource.stageMask() & MetalShaderStages.VERTEX) != 0) {
                highest = Math.max(highest, resource.metalIndex());
            }
        }
        return highest + 1;
    }

    @Override
    public boolean isValid() {
        return !ObjC.isNil(this.withDepthPipeline);
    }

    /** What this pipeline is, as the identity the cache and the probe key it by. */
    @Override
    public MetalPipelineKey pipelineKey() {
        return this.pipelineKey;
    }

    /** Every binding the pipeline declares, with the metal index the MSL reads it from. */
    List<MetalResourceBinding> resources() {
        return this.resources;
    }

    /** One binding by the name the pack gave it, or null where the pipeline does not declare it. */
    @Nullable
    MetalResourceBinding resource(final String name) {
        return this.resourcesByName.get(name);
    }

    /** The set of logical binding indices this pipeline uses, as the pipeline's own footprint. */
    BitSet allResources() {
        return (BitSet) this.allResources.clone();
    }

    /** The state to set on a pass that has a depth attachment, or nil where the pipeline did not build. */
    MemorySegment pipelineState(final boolean depthAttached) {
        return depthAttached ? this.withDepthPipeline : this.withoutDepthPipeline;
    }

    MemorySegment depthStencilState() {
        return this.depthStencilState;
    }

    MTLCullMode cullMode() {
        return this.cullMode;
    }

    MTLTriangleFillMode fillMode() {
        return this.fillMode;
    }

    MTLPrimitiveType topology() {
        return this.topology;
    }

    float depthBiasScaleFactor() {
        return this.depthBiasScaleFactor;
    }

    float depthBiasConstant() {
        return this.depthBiasConstant;
    }

    int firstAvailableVertexBufferSlot() {
        return this.firstAvailableVertexBufferSlot;
    }

    int vertexBufferCount() {
        return this.vertexBufferCount;
    }

    /**
     * Releases both pipeline states.
     * <p>
     * The depth-stencil state is not released here: it belongs to the compilation context that cached it, which
     * releases it once, with the rest of the context.
     */
    @Override
    public void close() {
        releaseIfPresent(this.withDepthPipeline);
        releaseIfPresent(this.withoutDepthPipeline);
    }

    private static void releaseIfPresent(final MemorySegment object) {
        if (!ObjC.isNil(object)) {
            ObjC.release(object);
        }
    }
}
