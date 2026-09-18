package com.metallum.render;

import com.metallum.mtl.*;
import com.metallum.objc.ObjC;
import com.mojang.blaze3d.GpuFormat;
import com.mojang.blaze3d.IndexType;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPass;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.ScissorState;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.minecraft.SharedConstants;
import org.joml.Vector4fc;
import org.jspecify.annotations.NonNull;
import org.jspecify.annotations.Nullable;
import org.lwjgl.PointerBuffer;
import org.lwjgl.vulkan.VkDrawIndexedIndirectCommand;
import org.lwjgl.vulkan.VkDrawIndirectCommand;

import java.lang.foreign.MemorySegment;
import java.lang.foreign.ValueLayout;
import java.nio.IntBuffer;
import java.nio.ShortBuffer;
import java.util.Arrays;
import java.util.BitSet;
import java.util.Collection;
import java.util.HashMap;
import java.util.function.Supplier;

@Environment(EnvType.CLIENT)
final class MetalRenderPass implements RenderPassBackend {
    static final boolean VALIDATION = SharedConstants.IS_RUNNING_IN_IDE;
    static final int MAX_VERTEX_BUFFERS = RenderPass.MAX_VERTEX_BUFFERS;

    private final MetalDevice device;
    private final MetalCommandEncoder commandEncoder;
    @Nullable
    private final String label;
    private final GpuTextureView[] colorTextures;
    @Nullable
    private final GpuTextureView depthTexture;
    private final RenderPass.RenderArea renderArea;
    private final int targetWidth;
    private final int targetHeight;
    private final Vector4fc[] clearColors;
    @Nullable
    private Double clearDepth;
    private final ScissorState scissorState = new ScissorState();
    private final GpuBufferSlice[] vertexBuffers = new GpuBufferSlice[MAX_VERTEX_BUFFERS];
    private final HashMap<String, GpuBufferSlice> uniforms = new HashMap<>();
    private final HashMap<String, TextureViewAndSampler> samplers = new HashMap<>();
    private final BitSet dirtyDescriptors = new BitSet();
    private final HashMap<MetalCompiledRenderPipeline.ArgumentBufferLayout, MTLBuffer> argumentBufferStates = new HashMap<>();
    @Nullable
    private MetalCompiledRenderPipeline compiledPipeline;
    @Nullable
    private GpuBuffer indexBuffer;
    private MTLIndexType indexType = MTLIndexType.UInt16;
    private int pushedDebugGroups = 0;
    private boolean scissorDirty = true;
    private boolean vertexBuffersDirty = true;
    private boolean pipelineDirty = true;

    /**
     * A draw in this logical pass bound a writable storage image. Metal textures use untracked
     * hazard tracking, so the logical pass boundary must end the native render encoder and let the
     * existing fence chain make those shader writes visible to a later pass. This does not claim
     * ordering between dependent draws inside the same logical RenderPass.
     */
    private boolean graphicsStorageImageWrites;

    MetalRenderPass(
            final MetalDevice device,
            final MetalCommandEncoder encoder,
            final Supplier<String> label,
            final GpuTextureView[] colorTextures,
            @Nullable final GpuTextureView depthTexture,
            final RenderPass.RenderArea renderArea,
            final Vector4fc[] clearColors,
            @Nullable final Double clearDepth
    ) {
        if (colorTextures.length != clearColors.length) {
            throw new IllegalArgumentException(
                    "Color attachment and clear-value counts differ: " + colorTextures.length + " != " + clearColors.length
            );
        }
        this.device = device;
        this.commandEncoder = encoder;
        this.label = device.useLabels() ? label.get() : null;
        this.colorTextures = colorTextures.clone();
        this.depthTexture = depthTexture;
        this.renderArea = renderArea;
        this.clearColors = clearColors.clone();
        this.clearDepth = clearDepth;

        int width = -1;
        int height = -1;
        for (int index = 0; index < this.colorTextures.length; index++) {
            GpuTextureView colorTexture = this.colorTextures[index];
            if (colorTexture == null) {
                continue;
            }
            int attachmentWidth = colorTexture.getWidth(0);
            int attachmentHeight = colorTexture.getHeight(0);
            if (width < 0) {
                width = attachmentWidth;
                height = attachmentHeight;
            } else if (width != attachmentWidth || height != attachmentHeight) {
                throw new IllegalArgumentException(
                        "Metal render-pass color attachment " + index + " is " + attachmentWidth + "x" + attachmentHeight
                                + ", expected " + width + "x" + height
                );
            }
        }
        if (depthTexture != null) {
            int depthWidth = depthTexture.getWidth(0);
            int depthHeight = depthTexture.getHeight(0);
            if (width < 0) {
                width = depthWidth;
                height = depthHeight;
            } else if (width != depthWidth || height != depthHeight) {
                throw new IllegalArgumentException(
                        "Metal render-pass depth attachment is " + depthWidth + "x" + depthHeight
                                + ", expected " + width + "x" + height
                );
            }
        }
        if (width < 0 || height < 0) {
            throw new IllegalArgumentException("Metal render pass requires at least one color or depth attachment");
        }
        if (renderArea.x() < 0
                || renderArea.y() < 0
                || renderArea.width() <= 0
                || renderArea.height() <= 0
                || renderArea.x() + renderArea.width() > width
                || renderArea.y() + renderArea.height() > height) {
            throw new IllegalArgumentException(
                    "Render area " + renderArea + " is outside Metal attachment extent " + width + "x" + height
            );
        }
        this.targetWidth = width;
        this.targetHeight = height;
    }

    @Override
    public void pushDebugGroup(final @NonNull Supplier<String> label) {
        pushedDebugGroups++;
        if (device.useLabels()) {
            commandEncoder.commandBuffer().pushDebugGroup(label.get());
        }
    }

    @Override
    public void popDebugGroup() {
        if (pushedDebugGroups == 0) {
            throw new IllegalStateException("Can't pop more debug groups than was pushed!");
        }
        pushedDebugGroups--;
        if (device.useLabels()) {
            commandEncoder.commandBuffer().popDebugGroup();
        }
    }

    @Override
    public void setPipeline(final @NonNull RenderPipeline pipeline) {
        MetalCompiledRenderPipeline compiled = device.getOrCompilePipeline(pipeline);
        if (this.compiledPipeline != compiled) {
            this.compiledPipeline = compiled;
            this.argumentBufferStates.clear();
            vertexBuffersDirty = true;
            pipelineDirty = true;
        }
    }

    @Override
    public void bindTexture(final @NonNull String name, @Nullable final GpuTextureView textureView, @Nullable final GpuSampler sampler) {
        if (textureView != null && sampler != null) {
            samplers.put(name, new TextureViewAndSampler(textureView, sampler));
            commandEncoder.flushPendingClear((MetalGpuTexture) textureView.texture());
            markDescriptorDirty(name);
        } else if (textureView == null && sampler == null) {
            samplers.remove(name);
            markDescriptorDirty(name);
        } else {
            throw new IllegalArgumentException();
        }
    }

    @Override
    public void setUniform(final @NonNull String name, final GpuBuffer value) {
        setUniform(name, value.slice());
    }

    @Override
    public void setUniform(final @NonNull String name, final @NonNull GpuBufferSlice value) {
        uniforms.put(name, value);
        markDescriptorDirty(name);
    }

    @Override
    public void enableScissor(final int x, final int y, final int width, final int height) {
        if (scissorState.enabled()
                && scissorState.x() == x
                && scissorState.y() == y
                && scissorState.width() == width
                && scissorState.height() == height) {
            return;
        }
        scissorState.enable(x, y, width, height);
        scissorDirty = true;
    }

    @Override
    public void disableScissor() {
        if (!scissorState.enabled()) {
            return;
        }
        scissorState.disable();
        scissorDirty = true;
    }

    @Override
    public void setVertexBuffer(final int slot, @Nullable final GpuBufferSlice vertexBuffer) {
        if (slot < 0 || slot >= MAX_VERTEX_BUFFERS) {
            throw new IllegalArgumentException("Unsupported Metal vertex buffer slot: " + slot);
        }
        if (!sameSlice(vertexBuffers[slot], vertexBuffer)) {
            vertexBuffers[slot] = vertexBuffer;
            vertexBuffersDirty = true;
        }
    }

    @Override
    public void setIndexBuffer(@Nullable final GpuBuffer indexBuffer, final @NonNull IndexType indexType) {
        setIndexBuffer(indexBuffer, MTLIndexType.from(indexType));
    }

    private void setIndexBuffer(@Nullable final GpuBuffer indexBuffer, final MTLIndexType indexType) {
        if (this.indexBuffer != indexBuffer || this.indexType != indexType) {
            this.indexBuffer = indexBuffer;
            this.indexType = indexType;
        }
    }

    @Override
    public void drawIndexed(final int indexCount, final int instanceCount, final int firstIndex, final int vertexOffset, final int firstInstance) {
        MetalGpuBuffer nativeIndexBuffer = (MetalGpuBuffer) indexBuffer;
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        drawIndexedNative(enc, nativeIndexBuffer, firstIndex, indexCount, vertexOffset, instanceCount, indexType, firstInstance);
    }

    @Override
    public void multiDrawIndexed(@NonNull IntBuffer drawParameters, int instanceCount, int firstInstance, int drawCount) {
        MetalGpuBuffer nativeIndexBuffer = (MetalGpuBuffer) indexBuffer;
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        for (int i = 0; i < drawCount; i++) {
            int firstIndex = drawParameters.get(i * 3);
            int indexCount = drawParameters.get(i * 3 + 1);
            int baseVertex = drawParameters.get(i * 3 + 2);
            if (indexCount > 0) {
                drawIndexedNative(enc, nativeIndexBuffer, firstIndex, indexCount, baseVertex, instanceCount, indexType, firstInstance);
            }
        }
    }

    @Override
    public void multiDrawIndexed(@NonNull PointerBuffer firstIndexOffsets, @NonNull IntBuffer indexCounts, @NonNull IntBuffer vertexOffsets, int drawCount) {
        MTLPrimitiveType primitiveType = primitiveTopology();
        if (primitiveType == MTLPrimitiveType.TriangleFan) {
            throw new UnsupportedOperationException("Metal backend does not support triangle fan multiDrawIndexed");
        }
        MetalGpuBuffer nativeIndexBuffer = (MetalGpuBuffer) indexBuffer;
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        MTLBuffer indexBufferHandle = nativeIndexBuffer.metalBuffer();
        MemorySegment offsets = MemorySegment.ofAddress(org.lwjgl.system.MemoryUtil.memAddress(firstIndexOffsets)).reinterpret(drawCount * 8L);
        MemorySegment counts = MemorySegment.ofAddress(org.lwjgl.system.MemoryUtil.memAddress(indexCounts)).reinterpret(drawCount * 4L);
        MemorySegment vertices = MemorySegment.ofAddress(org.lwjgl.system.MemoryUtil.memAddress(vertexOffsets)).reinterpret(drawCount * 4L);
        for (int i = 0; i < drawCount; i++) {
            int indexCount = counts.get(ValueLayout.JAVA_INT, i * 4L);
            if (indexCount <= 0) {
                continue;
            }
            long firstIndexOffset = offsets.get(ValueLayout.JAVA_LONG, i * 8L);
            int baseVertex = vertices.get(ValueLayout.JAVA_INT, i * 4L);
            enc.drawIndexedPrimitives(primitiveType, indexCount, indexType, indexBufferHandle, firstIndexOffset, 1, baseVertex, 0);
        }
    }

    @Override
    public void drawIndexedIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {
        MTLPrimitiveType primitiveType = primitiveTopology();
        if (primitiveType == MTLPrimitiveType.TriangleFan) {
            throw new UnsupportedOperationException("Metal backend does not support triangle fan indirect draws");
        }
        MetalGpuBuffer nativeIndexBuffer = (MetalGpuBuffer) indexBuffer;
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        MTLBuffer indexBufferHandle = nativeIndexBuffer.metalBuffer();
        MTLBuffer indirectBuffer = ((MetalGpuBuffer) commands.buffer()).metalBuffer();
        long indirectOffset = commands.offset();
        for (int i = 0; i < drawCount; i++) {
            enc.drawIndexedPrimitivesIndirect(primitiveType, indexType, indexBufferHandle, indirectBuffer, indirectOffset);
            indirectOffset += VkDrawIndexedIndirectCommand.SIZEOF;
        }
    }

    @Override
    public <T> void drawMultipleIndexed(
            final Collection<RenderPass.Draw<T>> draws,
            @Nullable final GpuBuffer defaultIndexBuffer,
            @Nullable final IndexType defaultIndexType,
            final @NonNull Collection<String> dynamicUniforms,
            final @NonNull T uniformArgument
    ) {
        IndexType fallbackIndexType = defaultIndexType == null ? IndexType.SHORT : defaultIndexType;
        for (RenderPass.Draw<T> draw : draws) {
            MTLIndexType drawIndexType = MTLIndexType.from(draw.indexType() == null ? fallbackIndexType : draw.indexType());
            GpuBuffer currentIndexBuffer = draw.indexBuffer() == null ? defaultIndexBuffer : draw.indexBuffer();
            setIndexBuffer(currentIndexBuffer, drawIndexType);
            setVertexBuffer(draw.slot(), draw.vertexBuffer().slice());
            if (draw.uniformUploaderConsumer() != null) {
                draw.uniformUploaderConsumer().accept(uniformArgument, this::setUniform);
            }
            MTLRenderCommandEncoder enc = renderEncoder();
            if (scissorDirty || vertexBuffersDirty || !dirtyDescriptors.isEmpty() || pipelineDirty) {
                bindDrawState(enc);
            }
            MetalGpuBuffer nativeIndexBuffer = (MetalGpuBuffer) indexBuffer;
            drawIndexedNative(enc, nativeIndexBuffer, draw.firstIndex(), draw.indexCount(), draw.baseVertex(), 1, drawIndexType, 0);
        }
    }

    @Override
    public void draw(final int vertexCount, final int instanceCount, final int firstVertex, final int firstInstance) {
        MTLPrimitiveType primitiveType = primitiveTopology();
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        if (primitiveType == MTLPrimitiveType.TriangleFan) {
            drawTriangleFan(enc, firstVertex, vertexCount, instanceCount, firstInstance);
        } else {
            enc.drawPrimitives(primitiveType, firstVertex, vertexCount, instanceCount, firstInstance);
        }
    }

    @Override
    public void multiDraw(@NonNull IntBuffer drawParameters, int instanceCount, int firstInstance, int drawCount) {
        throw new UnsupportedOperationException();
    }

    @Override
    public void multiDraw(@NonNull IntBuffer firstVertices, @NonNull IntBuffer vertexCounts, int drawCount) {
        throw new UnsupportedOperationException();
    }

    @Override
    public void drawIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {
        MTLPrimitiveType primitiveType = primitiveTopology();
        if (primitiveType == MTLPrimitiveType.TriangleFan) {
            throw new UnsupportedOperationException("Metal backend does not support triangle fan indirect draws");
        }
        MTLRenderCommandEncoder enc = renderEncoder();
        bindDrawState(enc);
        MTLBuffer indirectBuffer = ((MetalGpuBuffer) commands.buffer()).metalBuffer();
        long indirectOffset = commands.offset();
        for (int i = 0; i < drawCount; i++) {
            enc.drawPrimitivesIndirect(primitiveType, indirectBuffer, indirectOffset);
            indirectOffset += VkDrawIndirectCommand.SIZEOF;
        }
    }

    @Override
    public void writeTimestamp(final @NonNull GpuQueryPool pool, final int index) {
        if (pool instanceof MetalGpuQueryPool metalPool && index >= 0 && index < pool.size()) {
            metalPool.setValue(index, device.getTimestampNow());
        }
    }

    MTLPixelFormat depthAttachmentFormat() {
        if (depthTexture == null) {
            return MTLPixelFormat.Invalid;
        }
        return ((MetalGpuTexture) depthTexture.texture()).mtlPixelFormat();
    }

    MTLPixelFormat stencilAttachmentFormat() {
        if (depthTexture == null) {
            return MTLPixelFormat.Invalid;
        }
        return ((MetalGpuTexture) depthTexture.texture()).mtlStencilPixelFormat();
    }

    void materializePendingClear() {
        if (hasPendingColorClear() || clearDepth != null) {
            renderEncoder();
        }
    }

    private boolean hasPendingColorClear() {
        for (Vector4fc clearColor : clearColors) {
            if (clearColor != null) {
                return true;
            }
        }
        return false;
    }

    private MTLRenderCommandEncoder renderEncoder() {
        MetalGpuTextureView[] colorTextureViews = new MetalGpuTextureView[colorTextures.length];
        for (int index = 0; index < colorTextures.length; index++) {
            GpuTextureView colorTexture = colorTextures[index];
            colorTextureViews[index] = colorTexture == null ? null : (MetalGpuTextureView) colorTexture;
        }
        MetalGpuTextureView depthTextureView = depthTexture == null ? null : (MetalGpuTextureView) depthTexture;
        MTLRenderCommandEncoder encoder = commandEncoder.renderCommandEncoder(
                colorTextureViews, depthTextureView, targetWidth, targetHeight, clearColors, clearDepth
        );
        Arrays.fill(clearColors, null);
        clearDepth = null;
        return encoder;
    }

    void invalidateEncoderState() {
        pipelineDirty = true;
        scissorDirty = true;
        vertexBuffersDirty = true;
    }

    GpuBufferSlice.MappedView allocateTransient(final long size, final long alignment, @GpuBuffer.Usage final int usage) {
        return commandEncoder.transientMemory().allocateGpuMapped(size, alignment, usage);
    }

    private void pushVertexBuffers(final MTLRenderCommandEncoder enc) {
        int firstSlot = compiledPipeline.firstAvailableVertexBufferSlot();
        int count = compiledPipeline.vertexBufferCount();
        for (int slot = 0; slot < count; slot++) {
            GpuBufferSlice vertexBuffer = vertexBuffers[slot];
            if (vertexBuffer == null) {
                continue;
            }
            if (VALIDATION && vertexBuffer.buffer().isClosed()) {
                throw new IllegalStateException("Vertex buffer at slot " + slot + " has been closed");
            }
            MetalGpuBuffer nativeVertexBuffer = (MetalGpuBuffer) vertexBuffer.buffer();
            int metalSlot = firstSlot + slot;
            enc.setVertexBuffer(nativeVertexBuffer.metalBuffer(), vertexBuffer.offset(), metalSlot);
        }
    }

    private void drawTriangleFan(MTLRenderCommandEncoder encoder, final int firstVertex, final int vertexCount, final int instanceCount, final int baseInstance) {
        int triangleCount = vertexCount - 2;
        int indexCount = triangleCount * 3;
        MTLIndexType fanIndexType = vertexCount - 1 <= 0xFFFF ? MTLIndexType.UInt16 : MTLIndexType.UInt32;
        try (GpuBufferSlice.MappedView mapped = commandEncoder.transientMemory().allocateGpuMapped(
                (long) indexCount * fanIndexType.bytes, fanIndexType.bytes, GpuBuffer.USAGE_INDEX)) {
            if (fanIndexType == MTLIndexType.UInt16) {
                ShortBuffer indices = mapped.data().asShortBuffer();
                for (int i = 0; i < triangleCount; i++) {
                    indices.put((short) 0).put((short) (i + 1)).put((short) (i + 2));
                }
            } else {
                IntBuffer indices = mapped.data().asIntBuffer();
                for (int i = 0; i < triangleCount; i++) {
                    indices.put(0).put(i + 1).put(i + 2);
                }
            }
            GpuBufferSlice slice = mapped.slice();
            encoder.drawIndexedPrimitives(
                    MTLPrimitiveType.Triangle, indexCount, fanIndexType,
                    ((MetalGpuBuffer) slice.buffer()).metalBuffer(), slice.offset(), instanceCount, firstVertex, baseInstance
            );
        }
    }

    private void drawIndexedNative(
            final MTLRenderCommandEncoder enc,
            final MetalGpuBuffer nativeIndexBuffer,
            final int firstIndex,
            final int indexCount,
            final int baseVertex,
            final int instanceCount,
            final MTLIndexType indexType,
            final int baseInstance
    ) {
        MTLPrimitiveType primitiveType = primitiveTopology();
        long indexOffsetBytes = (long) firstIndex * indexType.bytes;
        if (primitiveType == MTLPrimitiveType.TriangleFan) {
            if (indexCount < 3) {
                return;
            }
            int generatedIndexCount = (indexCount - 2) * 3;
            try (GpuBufferSlice.MappedView mapped = commandEncoder.transientMemory().allocateGpuMapped(
                    (long) generatedIndexCount * Integer.BYTES, Integer.BYTES, GpuBuffer.USAGE_INDEX)) {
                expandTriangleFan(mapped.data().asIntBuffer(), nativeIndexBuffer.metalBuffer(), indexOffsetBytes, indexCount, indexType);
                GpuBufferSlice slice = mapped.slice();
                enc.drawIndexedPrimitives(
                        MTLPrimitiveType.Triangle, generatedIndexCount, MTLIndexType.UInt32,
                        ((MetalGpuBuffer) slice.buffer()).metalBuffer(), slice.offset(), instanceCount, baseVertex, baseInstance
                );
            }
        } else {
            enc.drawIndexedPrimitives(primitiveType, indexCount, indexType, nativeIndexBuffer.metalBuffer(), indexOffsetBytes, instanceCount, baseVertex, baseInstance);
        }
    }

    private static void expandTriangleFan(
            final IntBuffer out,
            final MTLBuffer indexBuffer,
            final long indexOffsetBytes,
            final int indexCount,
            final MTLIndexType indexType
    ) {
        MemorySegment indices = indexBuffer.contents()
                .reinterpret(indexOffsetBytes + (long) indexCount * indexType.bytes)
                .asSlice(indexOffsetBytes);
        int center = readIndex(indices, 0, indexType);
        for (int i = 1; i < indexCount - 1; i++) {
            out.put(center).put(readIndex(indices, i, indexType)).put(readIndex(indices, i + 1, indexType));
        }
    }

    private static void bindBuffer(
            final MTLRenderCommandEncoder enc,
            final MTLBuffer buffer,
            final long offset,
            final long index,
            final int stageMask
    ) {
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {
            enc.setVertexBuffer(buffer, offset, index);
        }
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_FRAGMENT) != 0) {
            enc.setFragmentBuffer(buffer, offset, index);
        }
    }

    private static void bindTexture(
            final MTLRenderCommandEncoder enc,
            final MemorySegment texture,
            final long index,
            final int stageMask
    ) {
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {
            enc.setVertexTexture(texture, index);
        }
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_FRAGMENT) != 0) {
            enc.setFragmentTexture(texture, index);
        }
    }

    private static void bindTextureAndSampler(
            final MTLRenderCommandEncoder enc,
            final MemorySegment texture,
            final MemorySegment sampler,
            final long index,
            final int stageMask
    ) {
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {
            enc.setVertexTexture(texture, index);
            enc.setVertexSamplerState(sampler, index);
        }
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_FRAGMENT) != 0) {
            enc.setFragmentTexture(texture, index);
            enc.setFragmentSamplerState(sampler, index);
        }
    }

    private static void bindTextureAndSampler(
            final MTLRenderCommandEncoder enc,
            final MemorySegment texture,
            final MemorySegment sampler,
            final long textureIndex,
            final long samplerIndex,
            final int stageMask
    ) {
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_VERTEX) != 0) {
            enc.setVertexTexture(texture, textureIndex);
            enc.setVertexSamplerState(sampler, samplerIndex);
        }
        if ((stageMask & MetalCompiledRenderPipeline.STAGE_FRAGMENT) != 0) {
            enc.setFragmentTexture(texture, textureIndex);
            enc.setFragmentSamplerState(sampler, samplerIndex);
        }
    }

    private static int readIndex(final MemorySegment indices, final int index, final MTLIndexType indexType) {
        if (indexType == MTLIndexType.UInt16) {
            return Short.toUnsignedInt(indices.get(ValueLayout.JAVA_SHORT_UNALIGNED, index * 2L));
        }
        return indices.get(ValueLayout.JAVA_INT_UNALIGNED, index * 4L);
    }

    private void bindDrawState(final MTLRenderCommandEncoder enc) {
        if (compiledPipeline == null) {
            throw new IllegalStateException("Pipeline is missing");
        }
        if (pipelineDirty) {
            boolean useDepth = depthAttachmentFormat().value != MTLPixelFormat.Invalid.value;
            MemorySegment pipelineHandle = compiledPipeline.getNativePipeline(useDepth);
            if (ObjC.isNil(pipelineHandle)) {
                throw new IllegalStateException("Native pipeline is unavailable");
            }
            enc.setRenderPipelineState(pipelineHandle);
            pipelineDirty = false;
            if (useDepth) {
                MemorySegment depthState = compiledPipeline.getDepthStencilState();
                if (ObjC.isNil(depthState)) {
                    throw new IllegalStateException("Native depth state is unavailable");
                }
                enc.setDepthStencilState(depthState);
                enc.setDepthBias(compiledPipeline.depthBiasConstant(), compiledPipeline.depthBiasScaleFactor(), 0.0f);
            }
            enc.setFrontFacingWinding(MTLWinding.Clockwise);
            enc.setCullMode(compiledPipeline.cullMode());
            enc.setTriangleFillMode(compiledPipeline.fillMode());
            dirtyDescriptors.or(compiledPipeline.allResources());
        }

        if (scissorDirty) {
            pushEffectiveScissor(enc);
            scissorDirty = false;
        }
        if (vertexBuffersDirty) {
            pushVertexBuffers(enc);
            vertexBuffersDirty = false;
        }
        if (!dirtyDescriptors.isEmpty()) {
            if (compiledPipeline.usesArgumentBuffers()) {
                ensureArgumentBuffersBound(enc);
            }
            for (MetalCompiledRenderPipeline.ResourceBinding binding : compiledPipeline.resources()) {
                if (dirtyDescriptors.get(binding.bindingIndex())) {
                    pushDescriptor(enc, binding);
                }
            }
        }
        dirtyDescriptors.clear();
    }

    private MTLPrimitiveType primitiveTopology() {
        if (compiledPipeline == null) {
            throw new IllegalStateException("Pipeline is missing");
        }
        return compiledPipeline.topology();
    }

    private void pushEffectiveScissor(final MTLRenderCommandEncoder enc) {
        int areaLeft = renderArea.x();
        int areaTop = renderArea.y();
        if (!scissorState.enabled()) {
            if (renderArea.x() == 0 && renderArea.y() == 0
                    && renderArea.width() == targetWidth && renderArea.height() == targetHeight) {
                enc.setScissorRect(0L, 0L, targetWidth, targetHeight);
                return;
            }
            enc.setScissorRect(areaLeft, areaTop, renderArea.width(), renderArea.height());
            return;
        }
        int areaRight = areaLeft + renderArea.width();
        int areaBottom = areaTop + renderArea.height();
        int left = Math.max(areaLeft, scissorState.x());
        int top = Math.max(areaTop, scissorState.y());
        int right = Math.min(areaRight, scissorState.x() + scissorState.width());
        int bottom = Math.min(areaBottom, scissorState.y() + scissorState.height());
        if (right <= left || bottom <= top) {
            enc.setScissorRect(0, 0, 0, 0);
        } else {
            enc.setScissorRect(left, top, right - left, bottom - top);
        }
    }

    private void markDescriptorDirty(final String name) {
        if (compiledPipeline != null) {
            MetalCompiledRenderPipeline.ResourceBinding binding = compiledPipeline.resource(name);
            if (binding != null) {
                dirtyDescriptors.set(binding.bindingIndex());
            }
        }
    }

    private void ensureArgumentBuffersBound(final MTLRenderCommandEncoder enc) {
        for (MetalCompiledRenderPipeline.ArgumentBufferLayout layout : compiledPipeline.argumentBuffers()) {
            MTLBuffer buffer = argumentBufferStates.get(layout);
            if (buffer == null) {
                long length = Math.max(1L, layout.encodedLength());
                MTLBuffer created = device.metalDevice().newBuffer(
                        length,
                        MTLResourceOptions.of(MTLStorageMode.Shared, MTLHazardTrackingMode.Tracked)
                );
                commandEncoder.queueForDestroy(() -> ObjC.release(created.handle()));
                argumentBufferStates.put(layout, created);
                buffer = created;
            }
            layout.encoder().setArgumentBuffer(buffer, 0L);
            if (layout.stageMask() == MetalCompiledRenderPipeline.STAGE_VERTEX) {
                enc.setVertexBuffer(buffer, 0L, layout.bufferIndex());
            } else if (layout.stageMask() == MetalCompiledRenderPipeline.STAGE_FRAGMENT) {
                enc.setFragmentBuffer(buffer, 0L, layout.bufferIndex());
            } else {
                throw new IllegalStateException("Argument buffer layout has invalid stage mask " + layout.stageMask());
            }
        }
    }

    private void pushDescriptor(
            final MTLRenderCommandEncoder enc,
            final MetalCompiledRenderPipeline.ResourceBinding binding
    ) {
        if (binding.indirect()) {
            pushArgumentDescriptor(enc, binding);
        } else {
            pushDirectDescriptor(enc, binding);
        }
    }

    private void pushDirectDescriptor(
            final MTLRenderCommandEncoder enc,
            final MetalCompiledRenderPipeline.ResourceBinding binding
    ) {
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.SAMPLED_IMAGE) {
            TextureViewAndSampler textureBinding = samplers.get(binding.name());
            if (textureBinding == null) {
                throw new IllegalStateException("Missing sampler " + binding.name());
            }
            MetalGpuTextureView textureView = (MetalGpuTextureView) textureBinding.textureView();
            MetalGpuSampler sampler = (MetalGpuSampler) textureBinding.sampler();
            bindTextureAndSampler(enc, textureView.nativeHandle(), sampler.nativeHandle(), binding.bindingIndex(), binding.stageMask());
            return;
        }
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.STORAGE_IMAGE) {
            TextureViewAndSampler textureBinding = samplers.get(binding.name());
            if (textureBinding == null) {
                throw new IllegalStateException("Missing storage image " + binding.name());
            }
            MetalGpuTextureView textureView = (MetalGpuTextureView) textureBinding.textureView();
            noteGraphicsStorageImageWrite(textureView);
            bindTexture(enc, textureView.nativeHandle(), binding.bindingIndex(), binding.stageMask());
            return;
        }
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.TEXEL_BUFFER) {
            pushDirectTexelBufferDescriptor(enc, binding);
            return;
        }
        GpuBufferSlice uniformSlice = requiredBuffer(binding);
        MetalGpuBuffer uniformBuffer = (MetalGpuBuffer) uniformSlice.buffer();
        bindBuffer(enc, uniformBuffer.metalBuffer(), uniformSlice.offset(), binding.bindingIndex(), binding.stageMask());
    }

    private void pushArgumentDescriptor(
            final MTLRenderCommandEncoder enc,
            final MetalCompiledRenderPipeline.ResourceBinding binding
    ) {
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.SAMPLED_IMAGE) {
            TextureViewAndSampler textureBinding = requiredTexture(binding.name(), "sampler");
            MetalGpuTextureView textureView = (MetalGpuTextureView) textureBinding.textureView();
            MetalGpuSampler sampler = (MetalGpuSampler) textureBinding.sampler();
            forEachArgumentLayout(binding, layout -> {
                MTLBuffer argumentBuffer = requireArgumentBuffer(layout);
                layout.encoder().setArgumentBuffer(argumentBuffer, 0L);
                layout.encoder().setTexture(textureView.nativeHandle(), binding.metalIndex());
                layout.encoder().setSamplerState(sampler.nativeHandle(), binding.samplerMetalIndex());
                enc.useResource(
                        textureView.nativeHandle(),
                        MTLRenderCommandEncoder.RESOURCE_USAGE_READ | MTLRenderCommandEncoder.RESOURCE_USAGE_SAMPLE,
                        renderStage(layout.stageMask())
                );
            });
            return;
        }
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.STORAGE_IMAGE) {
            TextureViewAndSampler textureBinding = requiredTexture(binding.name(), "storage image");
            MetalGpuTextureView textureView = (MetalGpuTextureView) textureBinding.textureView();
            noteGraphicsStorageImageWrite(textureView);
            forEachArgumentLayout(binding, layout -> {
                MTLBuffer argumentBuffer = requireArgumentBuffer(layout);
                layout.encoder().setArgumentBuffer(argumentBuffer, 0L);
                layout.encoder().setTexture(textureView.nativeHandle(), binding.metalIndex());
                enc.useResource(
                        textureView.nativeHandle(),
                        MTLRenderCommandEncoder.RESOURCE_USAGE_READ | MTLRenderCommandEncoder.RESOURCE_USAGE_WRITE,
                        renderStage(layout.stageMask())
                );
            });
            return;
        }
        if (binding.kind() == MetalCompiledRenderPipeline.ResourceKind.TEXEL_BUFFER) {
            pushArgumentTexelBufferDescriptor(enc, binding);
            return;
        }

        GpuBufferSlice uniformSlice = requiredBuffer(binding);
        MetalGpuBuffer uniformBuffer = (MetalGpuBuffer) uniformSlice.buffer();
        long usage = binding.kind() == MetalCompiledRenderPipeline.ResourceKind.STORAGE_BUFFER
                ? MTLRenderCommandEncoder.RESOURCE_USAGE_READ | MTLRenderCommandEncoder.RESOURCE_USAGE_WRITE
                : MTLRenderCommandEncoder.RESOURCE_USAGE_READ;
        forEachArgumentLayout(binding, layout -> {
            MTLBuffer argumentBuffer = requireArgumentBuffer(layout);
            layout.encoder().setArgumentBuffer(argumentBuffer, 0L);
            layout.encoder().setBuffer(uniformBuffer.metalBuffer(), uniformSlice.offset(), binding.metalIndex());
            enc.useResource(uniformBuffer.nativeHandle(), usage, renderStage(layout.stageMask()));
        });
    }

    private void pushDirectTexelBufferDescriptor(
            final MTLRenderCommandEncoder enc,
            final MetalCompiledRenderPipeline.ResourceBinding binding
    ) {
        MemorySegment texelTexture = createTexelBufferTexture(binding);
        bindTexture(enc, texelTexture, binding.bindingIndex(), binding.stageMask());
    }

    private void pushArgumentTexelBufferDescriptor(
            final MTLRenderCommandEncoder enc,
            final MetalCompiledRenderPipeline.ResourceBinding binding
    ) {
        MemorySegment texelTexture = createTexelBufferTexture(binding);
        forEachArgumentLayout(binding, layout -> {
            MTLBuffer argumentBuffer = requireArgumentBuffer(layout);
            layout.encoder().setArgumentBuffer(argumentBuffer, 0L);
            layout.encoder().setTexture(texelTexture, binding.metalIndex());
            enc.useResource(
                    texelTexture,
                    MTLRenderCommandEncoder.RESOURCE_USAGE_READ | MTLRenderCommandEncoder.RESOURCE_USAGE_SAMPLE,
                    renderStage(layout.stageMask())
            );
        });
    }

    private MemorySegment createTexelBufferTexture(final MetalCompiledRenderPipeline.ResourceBinding binding) {
        GpuBufferSlice texelSlice = requiredBuffer(binding);
        GpuFormat texelFormat = binding.texelBufferFormat();
        if (texelFormat == null) {
            throw new IllegalStateException("Texel buffer " + binding.name() + " is missing a format");
        }
        MetalGpuBuffer texelBuffer = (MetalGpuBuffer) texelSlice.buffer();
        long pixelFormat = MTLPixelFormat.from(texelFormat).value;
        int pixelSize = texelFormat.blockSize();
        long texelByteLength = texelSlice.length();
        if (texelByteLength <= 0L || texelByteLength % pixelSize != 0L) {
            throw new IllegalStateException(
                    "Texel buffer " + binding.name() + " length " + texelByteLength + " is not a valid " + texelFormat + " range"
            );
        }
        long texelCount = texelByteLength / pixelSize;
        MemorySegment texelTexture = MTLTexture.newBufferTextureView(
                texelBuffer.nativeHandle(), pixelFormat, texelSlice.offset(), texelCount, texelByteLength
        );
        if (ObjC.isNil(texelTexture)) {
            throw new IllegalStateException("Failed to create Metal texel buffer texture for " + binding.name());
        }
        commandEncoder.queueForDestroy(() -> ObjC.release(texelTexture));
        return texelTexture;
    }

    private void noteGraphicsStorageImageWrite(final MetalGpuTextureView textureView) {
        // Compute storage-image writes invalidate this cache in MetalComputeBridge. Graphics
        // imageStore has the same ownership effect: an old materialized clear no longer describes
        // the texture and must not suppress a later clear of the same numeric value.
        ((MetalGpuTexture) textureView.texture()).markContentsDirty();
        this.graphicsStorageImageWrites = true;
    }

    boolean hasGraphicsStorageImageWrites() {
        return this.graphicsStorageImageWrites;
    }

    private TextureViewAndSampler requiredTexture(final String name, final String description) {
        TextureViewAndSampler textureBinding = samplers.get(name);
        if (textureBinding == null) {
            throw new IllegalStateException("Missing " + description + " " + name);
        }
        return textureBinding;
    }

    private GpuBufferSlice requiredBuffer(final MetalCompiledRenderPipeline.ResourceBinding binding) {
        GpuBufferSlice slice = uniforms.get(binding.name());
        if (slice == null) {
            throw new IllegalStateException("Missing uniform " + binding.name());
        }
        if (VALIDATION && slice.buffer().isClosed()) {
            throw new IllegalStateException("Uniform " + binding.name() + " buffer has been closed");
        }
        return slice;
    }

    private MTLBuffer requireArgumentBuffer(final MetalCompiledRenderPipeline.ArgumentBufferLayout layout) {
        MTLBuffer buffer = argumentBufferStates.get(layout);
        if (buffer == null) {
            throw new IllegalStateException(
                    "Argument buffer set " + layout.descriptorSet() + " for stage " + layout.stageMask() + " was not allocated"
            );
        }
        return buffer;
    }

    private void forEachArgumentLayout(
            final MetalCompiledRenderPipeline.ResourceBinding binding,
            final java.util.function.Consumer<MetalCompiledRenderPipeline.ArgumentBufferLayout> consumer
    ) {
        boolean matched = false;
        for (MetalCompiledRenderPipeline.ArgumentBufferLayout layout : compiledPipeline.argumentBuffers()) {
            if (layout.descriptorSet() != binding.argumentBufferSet()) {
                continue;
            }
            if ((layout.stageMask() & binding.stageMask()) == 0) {
                continue;
            }
            consumer.accept(layout);
            matched = true;
        }
        if (!matched) {
            throw new IllegalStateException(
                    "No Metal argument buffer layout for resource " + binding.name()
                            + " set=" + binding.argumentBufferSet() + " stages=" + binding.stageMask()
            );
        }
    }

    private static MTLRenderStages renderStage(final int stageMask) {
        return switch (stageMask) {
            case MetalCompiledRenderPipeline.STAGE_VERTEX -> MTLRenderStages.Vertex;
            case MetalCompiledRenderPipeline.STAGE_FRAGMENT -> MTLRenderStages.Fragment;
            case MetalCompiledRenderPipeline.STAGE_ALL -> MTLRenderStages.VertexAndFragment;
            default -> throw new IllegalArgumentException("Unknown Metal stage mask " + stageMask);
        };
    }

    record TextureViewAndSampler(GpuTextureView textureView, GpuSampler sampler) {
    }

    private static boolean sameSlice(@Nullable final GpuBufferSlice left, @Nullable final GpuBufferSlice right) {
        if (left == null || right == null) {
            return left == right;
        }
        return left.buffer() == right.buffer()
                && left.offset() == right.offset()
                && left.length() == right.length();
    }
}
