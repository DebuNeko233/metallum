package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.*;
import com.metallum.objc.ObjC;
import com.mojang.blaze3d.GpuFormat;
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
import java.util.ArrayList;
import java.util.BitSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalResourceBinding;
import com.metallum.render.shared.MetalArgumentBufferLayout;

@Environment(EnvType.CLIENT)
final class MetalCompiledRenderPipeline implements CompiledRenderPipeline, AutoCloseable {
    private static final int MAX_COLOR_ATTACHMENTS = 8;
    static final int ARGUMENT_BUFFER_SLOT_COUNT = 8;
    static final int PUSH_CONSTANT_BUFFER_SLOT = 8;
    private static final int WIDE_VERTEX_BUFFER_BASE = 9;

    static final int STAGE_VERTEX = 1;
    static final int STAGE_FRAGMENT = 2;
    static final int STAGE_ALL = STAGE_VERTEX | STAGE_FRAGMENT;

    /**
     * One argument buffer this pipeline declares: where it lands, which the shared layer records, and the
     * encoder that fills it, which is Metal 3's own mechanism and stays here.
     */
    record ArgumentBufferLayout(MetalArgumentBufferLayout layout, MTLArgumentEncoder encoder) {

        int stageMask() {
            return this.layout.stageMask();
        }

        int descriptorSet() {
            return this.layout.descriptorSet();
        }

        int bufferIndex() {
            return this.layout.bufferIndex();
        }

        long encodedLength() {
            return this.layout.encodedLength();
        }
    }

    private final List<MetalResourceBinding> resources;
    private final Map<String, MetalResourceBinding> resourcesByName;
    private final BitSet allResources;
    private final boolean usesArgumentBuffers;
    private final List<ArgumentBufferLayout> argumentBuffers;
    private final int firstAvailableVertexBufferSlot;
    private final MTLCullMode cullMode;
    private final MTLTriangleFillMode fillMode;
    private final float depthBiasScaleFactor;
    private final float depthBiasConstant;
    private final MTLPrimitiveType topology;
    private final int vertexBufferCount;

    private final MemorySegment depthStencilState;
    private final MemorySegment withDepthPipeline;
    private final MemorySegment withoutDepthPipeline;

    MetalCompiledRenderPipeline(
            final MetalDevice device,
            final RenderPipeline info,
            final String vertexMsl,
            final String fragmentMsl,
            final String vertexEntryPoint,
            final String fragmentEntryPoint,
            final List<MetalResourceBinding> resources,
            final boolean usesArgumentBuffers,
            final Set<Integer> vertexArgumentBufferSets,
            final Set<Integer> fragmentArgumentBufferSets
    ) {
        this.resources = List.copyOf(resources);
        this.resourcesByName = resources.stream().collect(Collectors.toUnmodifiableMap(MetalResourceBinding::name, binding -> binding));
        this.usesArgumentBuffers = usesArgumentBuffers;

        BitSet resourceBits = new BitSet();
        for (MetalResourceBinding binding : resources) {
            if (binding.bindingIndex() < 0) {
                throw new IllegalStateException(
                        "Pipeline " + info.getLocation() + " has negative logical binding index " + binding.bindingIndex()
                );
            }
            resourceBits.set(binding.bindingIndex());
        }
        this.allResources = resourceBits;

        this.firstAvailableVertexBufferSlot = usesArgumentBuffers
                ? WIDE_VERTEX_BUFFER_BASE
                : firstAvailableVertexBufferSlot(resources);
        this.cullMode = info.isCull() ? MTLCullMode.Back : MTLCullMode.None;
        this.fillMode = info.getPolygonMode() == PolygonMode.WIREFRAME ? MTLTriangleFillMode.Lines : MTLTriangleFillMode.Fill;
        this.topology = MTLPrimitiveType.from(info.getPrimitiveTopology());
        this.vertexBufferCount = info.getVertexFormatBindings().length;

        if (this.firstAvailableVertexBufferSlot + this.vertexBufferCount > 31) {
            throw new IllegalStateException(
                    "Pipeline " + info.getLocation() + " requires vertex buffer slot "
                            + (this.firstAvailableVertexBufferSlot + this.vertexBufferCount - 1)
                            + ", beyond Metal's 0..30 buffer table"
            );
        }

        if (usesArgumentBuffers) {
            long samplerCount = resources.stream().filter(binding -> binding.kind() == MetalResourceBinding.ResourceKind.SAMPLED_IMAGE).count();
            long samplerLimit = device.metalDevice().maxArgumentBufferSamplerCount();
            if (samplerLimit > 0 && samplerCount > samplerLimit) {
                throw new IllegalStateException(
                        "Pipeline " + info.getLocation() + " needs " + samplerCount
                                + " samplers, beyond Metal argument-buffer limit " + samplerLimit
                );
            }
            Metallum.LOGGER.info(
                    "[metallum] Wide resource pipeline {} uses Metal Argument Buffers: resources={}, sampledImages={}, vertexSets={}, fragmentSets={}",
                    info.getLocation(), resources.size(), samplerCount, vertexArgumentBufferSets, fragmentArgumentBufferSets
            );
        }

        MTLCompareFunction depthCompareOp;
        int depthWrite;
        var depthStencilState = info.getDepthStencilState();
        if (depthStencilState == null) {
            depthCompareOp = MTLCompareFunction.Always;
            depthWrite = 0;
            this.depthBiasScaleFactor = 0.0f;
            this.depthBiasConstant = 0.0f;
        } else {
            depthCompareOp = MTLCompareFunction.from(depthStencilState.depthTest());
            depthWrite = depthStencilState.writeDepth() ? 1 : 0;
            this.depthBiasScaleFactor = depthStencilState.depthBiasScaleFactor();
            this.depthBiasConstant = depthStencilState.depthBiasConstant();
        }
        this.depthStencilState = device.depthStencilState(depthCompareOp, depthWrite != 0);

        ColorTargetState[] colorTargets = info.getColorTargetStates();
        if (colorTargets.length > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalStateException(
                    "Pipeline " + info.getLocation() + " declares " + colorTargets.length
                            + " color targets, Metal supports at most " + MAX_COLOR_ATTACHMENTS
            );
        }

        MemorySegment vertexFunction = device.getOrCompileFunction(vertexMsl, vertexEntryPoint);
        MemorySegment fragmentFunction = device.getOrCompileFunction(fragmentMsl, fragmentEntryPoint);
        this.argumentBuffers = usesArgumentBuffers
                ? createArgumentBuffers(vertexFunction, fragmentFunction, vertexArgumentBufferSets, fragmentArgumentBufferSets)
                : List.of();

        try (MTLVertexDescriptor vertexDescriptor = buildVertexDescriptor(info, this.firstAvailableVertexBufferSlot)) {
            this.withDepthPipeline = createPipeline(
                    device, info, vertexFunction, fragmentFunction, vertexDescriptor, colorTargets, MTLPixelFormat.Depth32Float
            );
            this.withoutDepthPipeline = createPipeline(
                    device, info, vertexFunction, fragmentFunction, vertexDescriptor, colorTargets, MTLPixelFormat.Invalid
            );
        }
    }

    private static List<ArgumentBufferLayout> createArgumentBuffers(
            final MemorySegment vertexFunction,
            final MemorySegment fragmentFunction,
            final Set<Integer> vertexSets,
            final Set<Integer> fragmentSets
    ) {
        List<ArgumentBufferLayout> layouts = new ArrayList<>(vertexSets.size() + fragmentSets.size());
        if (!ObjC.isNil(vertexFunction)) {
            for (int set : vertexSets) {
                MTLArgumentEncoder encoder = MTLArgumentEncoder.forFunction(vertexFunction, set);
                layouts.add(new ArgumentBufferLayout(
                        new MetalArgumentBufferLayout(STAGE_VERTEX, set, set, encoder.encodedLength()), encoder));
            }
        }
        if (!ObjC.isNil(fragmentFunction)) {
            for (int set : fragmentSets) {
                MTLArgumentEncoder encoder = MTLArgumentEncoder.forFunction(fragmentFunction, set);
                layouts.add(new ArgumentBufferLayout(
                        new MetalArgumentBufferLayout(STAGE_FRAGMENT, set, set, encoder.encodedLength()), encoder));
            }
        }
        return List.copyOf(layouts);
    }

    private static MemorySegment createPipeline(
            final MetalDevice device,
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
        try (MTLRenderPipelineDescriptor pipelineDesc = new MTLRenderPipelineDescriptor()) {
            pipelineDesc.setCompiledFunctions(vertexFunction, fragmentFunction);
            pipelineDesc.setVertexDescriptor(vertexDescriptor);
            pipelineDesc.setDepthStencilFormats(depthFormat, MTLPixelFormat.Invalid);
            for (int index = 0; index < colorTargets.length; index++) {
                ColorTargetState colorTarget = colorTargets[index];
                if (colorTarget == null) {
                    pipelineDesc.setColorAttachmentFormat(index, MTLPixelFormat.Invalid);
                    pipelineDesc.disableBlending(index, MTLColorWriteMask.None.value);
                    continue;
                }
                pipelineDesc.setColorAttachmentFormat(index, MTLPixelFormat.from(colorTarget.format()));
                Optional<BlendFunction> blendFunction = colorTarget.blendFunction();
                long writeMask = MTLColorWriteMask.from(colorTarget.writeMask());
                if (blendFunction.isPresent()) {
                    var function = blendFunction.get();
                    pipelineDesc.setBlendState(
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
                    pipelineDesc.disableBlending(index, writeMask);
                }
            }
            // Timed around the Metal call alone: building the descriptor above is this backend's
            // own work, and what the frame probe reports is what the driver was asked to do.
            long startNanos = System.nanoTime();
            MemorySegment pipeline = device.metalDevice().newRenderPipelineState(pipelineDesc);
            MetalFrameProbe.pipelineCompiled(System.nanoTime() - startNanos);
            if (ObjC.isNil(pipeline)) {
                Metallum.LOGGER.error(
                        "[metallum] Pipeline {} failed to build with {} color target slots and depth format {}",
                        info.getLocation(), colorTargets.length, depthFormat
                );
            }
            return pipeline;
        }
    }

    @Override
    public boolean isValid() {
        return !ObjC.isNil(this.withDepthPipeline);
    }

    List<MetalResourceBinding> resources() {
        return this.resources;
    }

    BitSet allResources() {
        return (BitSet) this.allResources.clone();
    }

    boolean usesArgumentBuffers() {
        return this.usesArgumentBuffers;
    }

    List<ArgumentBufferLayout> argumentBuffers() {
        return this.argumentBuffers;
    }

    @Nullable
    MetalResourceBinding resource(final String name) {
        return this.resourcesByName.get(name);
    }

    int firstAvailableVertexBufferSlot() {
        return this.firstAvailableVertexBufferSlot;
    }

    float depthBiasScaleFactor() {
        return this.depthBiasScaleFactor;
    }

    float depthBiasConstant() {
        return this.depthBiasConstant;
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

    int vertexBufferCount() {
        return this.vertexBufferCount;
    }

    MemorySegment getNativePipeline(final boolean depth) {
        return depth ? this.withDepthPipeline : this.withoutDepthPipeline;
    }

    MemorySegment getDepthStencilState() {
        return this.depthStencilState;
    }

    @Override
    public void close() {
        for (ArgumentBufferLayout layout : this.argumentBuffers) {
            layout.encoder().close();
        }
        if (!ObjC.isNil(this.withDepthPipeline)) {
            ObjC.release(this.withDepthPipeline);
        }
        if (!ObjC.isNil(this.withoutDepthPipeline)) {
            ObjC.release(this.withoutDepthPipeline);
        }
    }

    private static int firstAvailableVertexBufferSlot(final List<MetalResourceBinding> resources) {
        int maxVertexBufferBinding = -1;
        for (MetalResourceBinding resource : resources) {
            if ((resource.kind() == MetalResourceBinding.ResourceKind.UNIFORM_BUFFER || resource.kind() == MetalResourceBinding.ResourceKind.STORAGE_BUFFER)
                    && (resource.stageMask() & STAGE_VERTEX) != 0) {
                maxVertexBufferBinding = Math.max(maxVertexBufferBinding, resource.metalIndex());
            }
        }
        return maxVertexBufferBinding + 1;
    }

    private static MTLVertexDescriptor buildVertexDescriptor(
            final RenderPipeline info,
            final int firstAvailableBufferSlot
    ) {
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
}
