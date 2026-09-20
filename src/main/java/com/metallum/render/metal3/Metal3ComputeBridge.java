package com.metallum.render.metal3;

import com.metallum.mtl.metal3.MTLComputeCommandEncoder;
import com.metallum.objc.ObjC;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.util.Map;
import java.util.Objects;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.MetalComputePipelineResource;
import com.metallum.render.shared.MetalComputeTranslator;
import com.metallum.render.shared.MetalExecutionState;

/**
 * Optional-backend bridge for shader-pack compute work.
 * <p>
 * The public surface intentionally uses only JDK and Minecraft GPU-facade types. Optional clients
 * therefore do not need Metallum on their compile classpath and never receive an {@code MTLBuffer},
 * {@code MTLTexture}, command encoder, or native pipeline pointer. The opaque pipeline object is
 * owned by Metallum and must only be handed back to this class.
 * <p>
 * Shader-pack policy is deliberately absent here: callers decide which resource a declared name
 * means, which ping-pong half is current, when a dispatch belongs in the frame, and how many
 * workgroups it requests. Metallum only compiles SPIR-V to MSL, maps reflected resources onto
 * Metal's independent buffer/texture/sampler argument tables, binds the already-resolved GPU
 * resources, dispatches the requested workgroups, and applies its encoder/fence lifetime rules.
 * <p>
 * The translation itself is not this class's: SPIR-V in and MSL plus remapped bindings out is
 * {@link MetalComputeTranslator}'s, because that answer does not depend on which command API encodes the
 * dispatch. What is here is the Metal 3 half - the shared binding record onto this generation's per-resource
 * encoder calls, and the encoder lifetime a dispatch is given.
 */
@Environment(EnvType.CLIENT)
public final class Metal3ComputeBridge {
    private Metal3ComputeBridge() {
    }

    /**
     * Compiles one compute SPIR-V module into an opaque Metal compute pipeline resource.
     *
     * @param backend a Metallum {@code MetalDevice}, typed as {@link Object} for optional clients
     * @param label diagnostic label owned by the caller
     * @param spirv SPIR-V bytes whose reflected resources are remapped to native Metal arguments
     */
    public static Object compile(final MetalDevice device, final MetalExecutionState executionState,
                                 final String label, final ByteBuffer spirv) {
        Objects.requireNonNull(label, "label");
        Objects.requireNonNull(spirv, "spirv");

        try {
            MetalComputeTranslator.Translated translated = MetalComputeTranslator.translate(spirv);
            if (!(executionState instanceof Metal3ExecutionState metal3)) {
                throw new IllegalStateException("Metal compute bridge requires Metal 3 execution state");
            }

            MemorySegment function = metal3.getOrCompileFunction(translated.msl(), translated.entryPoint());
            if (ObjC.isNil(function)) {
                throw new IllegalStateException("Failed to compile Metal compute function for " + label);
            }
            MemorySegment pipelineState = device.metalDevice().newComputePipelineState(function);
            if (ObjC.isNil(pipelineState)) {
                throw new IllegalStateException("Failed to create Metal compute pipeline for " + label);
            }
            return new ComputePipeline(device, label, pipelineState, translated.bindings());
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("Failed to compile Metal compute pipeline " + label, e);
        }
    }

    /**
     * Dispatches workgroups through Metallum's normal compute encoder and fence chain.
     * <p>
     * {@code groups*} are workgroup counts, matching Vulkan {@code vkCmdDispatch}; {@code local*}
     * are the shader's threads-per-workgroup values. This method therefore uses Metal's
     * {@code dispatchThreadgroups:threadsPerThreadgroup:}, not {@code dispatchThreads}.
     */
    public static boolean dispatch(
            final Object encoderBackend,
            final Object pipelineResource,
            final Map<String, GpuBufferSlice> buffers,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers,
            final int groupsX,
            final int groupsY,
            final int groupsZ,
            final int localX,
            final int localY,
            final int localZ
    ) {
        if (!(encoderBackend instanceof MetalCommandEncoder commandEncoder)
                || !(pipelineResource instanceof ComputePipeline pipeline)
                || pipeline.closed) {
            return false;
        }
        Objects.requireNonNull(buffers, "buffers");
        Objects.requireNonNull(textures, "textures");
        Objects.requireNonNull(samplers, "samplers");
        if (groupsX < 0 || groupsY < 0 || groupsZ < 0) {
            throw new IllegalArgumentException("Compute workgroup counts must not be negative");
        }
        if (localX <= 0 || localY <= 0 || localZ <= 0) {
            throw new IllegalArgumentException("Compute local size must be positive");
        }
        if (groupsX == 0 || groupsY == 0 || groupsZ == 0) {
            return true;
        }

        // A pending texture clear is materialized with a render encoder. Resolve every resource and
        // materialize those clears before opening compute so no binding step can end the encoder it
        // is about to write into.
        prepareResources(commandEncoder, pipeline.bindings, buffers, textures, samplers);

        MTLComputeCommandEncoder compute = commandEncoder.computeCommandEncoder();
        boolean bound = false;
        try {
            compute.setComputePipelineState(pipeline.pipelineState);
            for (MetalComputeTranslator.Binding binding : pipeline.bindings.values()) {
                switch (binding.kind()) {
                    case UNIFORM_BUFFER, STORAGE_BUFFER -> bindBuffer(compute, binding, buffers);
                    case SAMPLED_IMAGE -> bindSampledImage(compute, binding, textures, samplers);
                    case STORAGE_IMAGE -> bindStorageImage(compute, binding, textures);
                }
            }
            compute.dispatchThreadgroups(
                    groupsX, groupsY, groupsZ,
                    localX, localY, localZ
            );
            bound = true;
        } finally {
            // Left open on the way out of a successful dispatch, because that encoder is where the next
            // dispatch belongs and sharing it is what takes a frame's compute encoders down; a dispatch that
            // threw mid-binding is ended here rather than carried into the next one.
            if (!bound) {
                commandEncoder.endEncoder();
            }
        }
        return true;
    }

    /** Releases an opaque pipeline returned by {@link #compile(Object, String, ByteBuffer)}. */
    public static void close(final Object pipelineResource) {
        if (pipelineResource instanceof ComputePipeline pipeline) {
            pipeline.close();
        }
    }

    private static void prepareResources(
            final MetalCommandEncoder commandEncoder,
            final Map<String, MetalComputeTranslator.Binding> bindings,
            final Map<String, GpuBufferSlice> buffers,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers
    ) {
        for (MetalComputeTranslator.Binding binding : bindings.values()) {
            switch (binding.kind()) {
                case UNIFORM_BUFFER, STORAGE_BUFFER -> requireBuffer(binding, buffers);
                case SAMPLED_IMAGE -> {
                    MetalGpuTextureView view = requireTexture(binding, textures, "sampled image");
                    requireSampler(binding, samplers);
                    commandEncoder.flushPendingClear((MetalGpuTexture) view.texture());
                }
                case STORAGE_IMAGE -> {
                    MetalGpuTextureView view = requireTexture(binding, textures, "storage image");
                    commandEncoder.flushPendingClear((MetalGpuTexture) view.texture());
                }
            }
        }
    }

    private static void bindBuffer(
            final MTLComputeCommandEncoder compute,
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuBufferSlice> buffers
    ) {
        GpuBufferSlice slice = requireBuffer(binding, buffers);
        MetalGpuBuffer buffer = (MetalGpuBuffer) slice.buffer();
        compute.setBuffer(buffer.metalBuffer(), slice.offset(), binding.bufferIndex());
    }

    private static void bindSampledImage(
            final MTLComputeCommandEncoder compute,
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers
    ) {
        MetalGpuTextureView view = requireTexture(binding, textures, "sampled image");
        MetalGpuSampler sampler = requireSampler(binding, samplers);
        compute.setTexture(view.nativeHandle(), binding.textureIndex());
        compute.setSamplerState(sampler.nativeHandle(), binding.samplerIndex());
    }

    private static void bindStorageImage(
            final MTLComputeCommandEncoder compute,
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuTextureView> textures
    ) {
        MetalGpuTextureView view = requireTexture(binding, textures, "storage image");
        ((MetalGpuTexture) view.texture()).markContentsDirty();
        compute.setTexture(view.nativeHandle(), binding.textureIndex());
    }

    private static GpuBufferSlice requireBuffer(
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuBufferSlice> buffers
    ) {
        GpuBufferSlice slice = buffers.get(binding.name());
        if (slice == null) {
            throw new IllegalStateException("Missing Metal compute buffer " + binding.name());
        }
        if (!(slice.buffer() instanceof MetalGpuBuffer) || slice.buffer().isClosed()) {
            throw new IllegalStateException("Invalid Metal compute buffer " + binding.name());
        }
        return slice;
    }

    private static MetalGpuTextureView requireTexture(
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuTextureView> textures,
            final String description
    ) {
        GpuTextureView view = textures.get(binding.name());
        if (!(view instanceof MetalGpuTextureView metalView) || view.isClosed()) {
            throw new IllegalStateException("Missing Metal compute " + description + " " + binding.name());
        }
        return metalView;
    }

    private static MetalGpuSampler requireSampler(
            final MetalComputeTranslator.Binding binding,
            final Map<String, GpuSampler> samplers
    ) {
        GpuSampler sampler = samplers.get(binding.name());
        if (!(sampler instanceof MetalGpuSampler metalSampler) || metalSampler.isClosed()) {
            throw new IllegalStateException("Missing Metal compute sampler " + binding.name());
        }
        return metalSampler;
    }

    private static final class ComputePipeline implements MetalComputePipelineResource {
        private final MetalDevice device;
        private final String label;
        private final MemorySegment pipelineState;
        private final Map<String, MetalComputeTranslator.Binding> bindings;
        private boolean closed;

        private ComputePipeline(
                final MetalDevice device,
                final String label,
                final MemorySegment pipelineState,
                final Map<String, MetalComputeTranslator.Binding> bindings
        ) {
            this.device = device;
            this.label = label;
            this.pipelineState = pipelineState;
            this.bindings = bindings;
        }

        @Override
        public void close() {
            if (this.closed) {
                return;
            }
            this.closed = true;
            this.device.queueResourceRelease(this.pipelineState);
        }

        @Override
        public String toString() {
            return "MetalComputePipeline[" + this.label + "]";
        }
    }
}
