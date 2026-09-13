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
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Environment(EnvType.CLIENT)
final class MetalCompiledRenderPipeline implements CompiledRenderPipeline, AutoCloseable {
    private static final int MAX_COLOR_ATTACHMENTS = 8;

    enum ResourceKind {
        UNIFORM_BUFFER,
        STORAGE_BUFFER,
        SAMPLED_IMAGE,
        STORAGE_IMAGE,
        TEXEL_BUFFER
    }

    static final int STAGE_VERTEX = 1;
    static final int STAGE_FRAGMENT = 2;
    static final int STAGE_ALL = STAGE_VERTEX | STAGE_FRAGMENT;

    record ResourceBinding(ResourceKind kind, String name, int bindingIndex, int stageMask,
                           @Nullable GpuFormat texelBufferFormat) {
    }

    private final List<ResourceBinding> resources;
    private final Map<String, ResourceBinding> resourcesByName;
    private final long allResourceMask;
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
            final List<ResourceBinding> resources
    ) {
        this.resources = resources;
        this.resourcesByName = resources.stream().collect(java.util.stream.Collectors.toUnmodifiableMap(ResourceBinding::name, binding -> binding));

        int maxBindingIndex = -1;
        long resourceMask = 0L;
        for (ResourceBinding binding : resources) {
            maxBindingIndex = Math.max(maxBindingIndex, binding.bindingIndex());
            resourceMask |= 1L << binding.bindingIndex();
        }
        if (maxBindingIndex >= Long.SIZE) {
            throw new IllegalStateException("Pipeline " + info.getLocation() + " has binding index " + maxBindingIndex + ", limit is " + (Long.SIZE - 1));
        }
        this.allResourceMask = resourceMask;

        this.firstAvailableVertexBufferSlot = firstAvailableVertexBufferSlot(resources);
        this.cullMode = info.isCull() ? MTLCullMode.Back : MTLCullMode.None;
        this.fillMode = info.getPolygonMode() == PolygonMode.WIREFRAME ? MTLTriangleFillMode.Lines : MTLTriangleFillMode.Fill;
        this.topology = MTLPrimitiveType.from(info.getPrimitiveTopology());
        this.vertexBufferCount = info.getVertexFormatBindings().length;

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

        try (MTLVertexDescriptor vertexDescriptor = buildVertexDescriptor(info, this.firstAvailableVertexBufferSlot)) {
            this.withDepthPipeline = createPipeline(
                    device,
                    info,
                    vertexFunction,
                    fragmentFunction,
                    vertexDescriptor,
                    colorTargets,
                    MTLPixelFormat.Depth32Float
            );
            this.withoutDepthPipeline = createPipeline(
                    device,
                    info,
                    vertexFunction,
                    fragmentFunction,
                    vertexDescriptor,
                    colorTargets,
                    MTLPixelFormat.Invalid
            );
        }
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

            MemorySegment pipeline = device.metalDevice().newRenderPipelineState(pipelineDesc);
            if (ObjC.isNil(pipeline)) {
                Metallum.LOGGER.error(
                        "[metallum] Pipeline {} failed to build with {} color target slots and depth format {}",
                        info.getLocation(),
                        colorTargets.length,
                        depthFormat
                );
            }
            return pipeline;
        }
    }

    @Override
    public boolean isValid() {
        return !ObjC.isNil(this.withDepthPipeline);
    }

    List<ResourceBinding> resources() {
        return this.resources;
    }

    long allResourceMask() {
        return this.allResourceMask;
    }

    @Nullable
    ResourceBinding resource(final String name) {
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
        if (!ObjC.isNil(this.withDepthPipeline)) {
            ObjC.release(this.withDepthPipeline);
        }
        if (!ObjC.isNil(this.withoutDepthPipeline)) {
            ObjC.release(this.withoutDepthPipeline);
        }
    }

    private static int firstAvailableVertexBufferSlot(final List<ResourceBinding> resources) {
        int maxVertexBufferBinding = -1;
        for (ResourceBinding resource : resources) {
            if ((resource.kind() == ResourceKind.UNIFORM_BUFFER || resource.kind() == ResourceKind.STORAGE_BUFFER)
                    && (resource.stageMask() & STAGE_VERTEX) != 0) {
                maxVertexBufferBinding = Math.max(maxVertexBufferBinding, resource.bindingIndex());
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
            descriptor.setLayout(
                    bufferIndex,
                    format.getVertexSize(),
                    stepFunction,
                    stepRate > 0 ? stepRate : 1L
            );

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
