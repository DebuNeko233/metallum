package com.metallum.render;

import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.metallum.mtl.metal3.MTLComputeCommandEncoder;
import com.metallum.objc.ObjC;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.lwjgl.PointerBuffer;
import org.lwjgl.system.MemoryStack;
import org.lwjgl.system.MemoryUtil;
import org.lwjgl.util.spvc.Spv;
import org.lwjgl.util.spvc.Spvc;
import org.lwjgl.util.spvc.SpvcMslResourceBinding2;
import org.lwjgl.util.spvc.SpvcReflectedResource;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.nio.IntBuffer;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalGpuSampler;

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
 */
@Environment(EnvType.CLIENT)
public final class MetalComputeBridge {
    private static final int MAX_BUFFER_ARGUMENTS = 31;
    private static final int MAX_TEXTURE_ARGUMENTS = 128;
    private static final int MAX_SAMPLER_ARGUMENTS = 16;
    private static final Pattern KERNEL_ENTRY_PATTERN = Pattern.compile("\\bkernel\\s+\\w+\\s+(\\w+)\\s*\\(");

    private MetalComputeBridge() {
    }

    /**
     * Compiles one compute SPIR-V module into an opaque Metal compute pipeline resource.
     *
     * @param backend a Metallum {@code MetalDevice}, typed as {@link Object} for optional clients
     * @param label diagnostic label owned by the caller
     * @param spirv SPIR-V bytes whose reflected resources are remapped to native Metal arguments
     */
    public static Object compile(final Object backend, final String label, final ByteBuffer spirv) {
        if (!(backend instanceof MetalDevice device)) {
            throw new IllegalArgumentException("Not a Metallum MetalDevice backend: " + backend);
        }
        Objects.requireNonNull(label, "label");
        Objects.requireNonNull(spirv, "spirv");

        try {
            Reflected reflected = reflectAndCompile(spirv);
            MemorySegment function = device.getOrCompileFunction(reflected.msl(), reflected.entryPoint());
            if (ObjC.isNil(function)) {
                throw new IllegalStateException("Failed to compile Metal compute function for " + label);
            }
            MemorySegment pipelineState = device.metalDevice().newComputePipelineState(function);
            if (ObjC.isNil(pipelineState)) {
                throw new IllegalStateException("Failed to create Metal compute pipeline for " + label);
            }
            return new ComputePipeline(device, label, pipelineState, reflected.bindings());
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
            for (Binding binding : pipeline.bindings.values()) {
                switch (binding.kind) {
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
            final Map<String, Binding> bindings,
            final Map<String, GpuBufferSlice> buffers,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers
    ) {
        for (Binding binding : bindings.values()) {
            switch (binding.kind) {
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
            final Binding binding,
            final Map<String, GpuBufferSlice> buffers
    ) {
        GpuBufferSlice slice = requireBuffer(binding, buffers);
        MetalGpuBuffer buffer = (MetalGpuBuffer) slice.buffer();
        compute.setBuffer(buffer.metalBuffer(), slice.offset(), binding.bufferIndex);
    }

    private static void bindSampledImage(
            final MTLComputeCommandEncoder compute,
            final Binding binding,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers
    ) {
        MetalGpuTextureView view = requireTexture(binding, textures, "sampled image");
        MetalGpuSampler sampler = requireSampler(binding, samplers);
        compute.setTexture(view.nativeHandle(), binding.textureIndex);
        compute.setSamplerState(sampler.nativeHandle(), binding.samplerIndex);
    }

    private static void bindStorageImage(
            final MTLComputeCommandEncoder compute,
            final Binding binding,
            final Map<String, GpuTextureView> textures
    ) {
        MetalGpuTextureView view = requireTexture(binding, textures, "storage image");
        ((MetalGpuTexture) view.texture()).markContentsDirty();
        compute.setTexture(view.nativeHandle(), binding.textureIndex);
    }

    private static GpuBufferSlice requireBuffer(
            final Binding binding,
            final Map<String, GpuBufferSlice> buffers
    ) {
        GpuBufferSlice slice = buffers.get(binding.name);
        if (slice == null) {
            throw new IllegalStateException("Missing Metal compute buffer " + binding.name);
        }
        if (!(slice.buffer() instanceof MetalGpuBuffer) || slice.buffer().isClosed()) {
            throw new IllegalStateException("Invalid Metal compute buffer " + binding.name);
        }
        return slice;
    }

    private static MetalGpuTextureView requireTexture(
            final Binding binding,
            final Map<String, GpuTextureView> textures,
            final String description
    ) {
        GpuTextureView view = textures.get(binding.name);
        if (!(view instanceof MetalGpuTextureView metalView) || view.isClosed()) {
            throw new IllegalStateException("Missing Metal compute " + description + " " + binding.name);
        }
        return metalView;
    }

    private static MetalGpuSampler requireSampler(
            final Binding binding,
            final Map<String, GpuSampler> samplers
    ) {
        GpuSampler sampler = samplers.get(binding.name);
        if (!(sampler instanceof MetalGpuSampler metalSampler) || metalSampler.isClosed()) {
            throw new IllegalStateException("Missing Metal compute sampler " + binding.name);
        }
        return metalSampler;
    }

    private static Reflected reflectAndCompile(final ByteBuffer spirvBytes) throws Exception {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            IntBuffer words = spirvBytes.duplicate().asIntBuffer();
            PointerBuffer pContext = stack.mallocPointer(1);
            checkSpvc(Spvc.spvc_context_create(pContext), "spvc_context_create");
            long context = pContext.get(0);
            try {
                PointerBuffer pIr = stack.mallocPointer(1);
                checkSpvc(
                        Spvc.spvc_context_parse_spirv(context, words, words.remaining(), pIr),
                        "spvc_context_parse_spirv"
                );

                PointerBuffer pCompiler = stack.mallocPointer(1);
                checkSpvc(
                        Spvc.spvc_context_create_compiler(
                                context,
                                Spvc.SPVC_BACKEND_MSL,
                                pIr.get(0),
                                Spvc.SPVC_CAPTURE_MODE_COPY,
                                pCompiler
                        ),
                        "spvc_context_create_compiler"
                );
                long compiler = pCompiler.get(0);
                installMslOptions(stack, compiler);

                Map<String, Binding> bindings = reflectAndRemapBindings(stack, compiler);

                PointerBuffer pSource = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_compile(compiler, pSource), "spvc_compiler_compile");
                String msl = MemoryUtil.memUTF8(pSource.get(0));
                Matcher entry = KERNEL_ENTRY_PATTERN.matcher(msl);
                String entryPoint = entry.find() ? entry.group(1) : "main0";
                return new Reflected(msl, entryPoint, Map.copyOf(bindings));
            } finally {
                Spvc.spvc_context_destroy(context);
            }
        }
    }

    private static void installMslOptions(final MemoryStack stack, final long compiler) throws Exception {
        PointerBuffer pOptions = stack.mallocPointer(1);
        checkSpvc(
                Spvc.spvc_compiler_create_compiler_options(compiler, pOptions),
                "spvc_compiler_create_compiler_options"
        );
        long options = pOptions.get(0);
        checkSpvc(
                Spvc.spvc_compiler_options_set_uint(
                        options,
                        Spvc.SPVC_COMPILER_OPTION_MSL_PLATFORM,
                        Spvc.SPVC_MSL_PLATFORM_MACOS
                ),
                "spvc_compiler_options_set_uint(MSL_PLATFORM)"
        );
        checkSpvc(
                Spvc.spvc_compiler_options_set_uint(
                        options,
                        Spvc.SPVC_COMPILER_OPTION_MSL_VERSION,
                        MetalShaderLanguageProfile.selected().spirvCrossMslVersion()),
                "spvc_compiler_options_set_uint(MSL_VERSION)"
        );
        checkSpvc(
                Spvc.spvc_compiler_options_set_bool(
                        options,
                        Spvc.SPVC_COMPILER_OPTION_MSL_TEXTURE_BUFFER_NATIVE,
                        true
                ),
                "spvc_compiler_options_set_bool(MSL_TEXTURE_BUFFER_NATIVE)"
        );
        checkSpvc(
                Spvc.spvc_compiler_install_compiler_options(compiler, options),
                "spvc_compiler_install_compiler_options"
        );
    }

    private static Map<String, Binding> reflectAndRemapBindings(
            final MemoryStack stack,
            final long compiler
    ) throws Exception {
        PointerBuffer pResources = stack.mallocPointer(1);
        checkSpvc(
                Spvc.spvc_compiler_create_shader_resources(compiler, pResources),
                "spvc_compiler_create_shader_resources"
        );
        long resources = pResources.get(0);
        LinkedHashMap<String, Binding> bindings = new LinkedHashMap<>();
        ArgumentSlots slots = new ArgumentSlots();
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_UNIFORM_BUFFER,
                Kind.UNIFORM_BUFFER, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER,
                Kind.STORAGE_BUFFER, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_SAMPLED_IMAGE,
                Kind.SAMPLED_IMAGE, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE,
                Kind.STORAGE_IMAGE, bindings, slots);
        return bindings;
    }

    private static void collectBindings(
            final MemoryStack stack,
            final long compiler,
            final long resources,
            final int resourceType,
            final Kind kind,
            final Map<String, Binding> bindings,
            final ArgumentSlots slots
    ) throws Exception {
        PointerBuffer pList = stack.mallocPointer(1);
        PointerBuffer pCount = stack.mallocPointer(1);
        checkSpvc(
                Spvc.spvc_resources_get_resource_list_for_type(resources, resourceType, pList, pCount),
                "spvc_resources_get_resource_list_for_type(" + kind + ")"
        );
        int count = (int) pCount.get(0);
        if (count == 0) {
            return;
        }

        SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
        for (int i = 0; i < count; i++) {
            SpvcReflectedResource resource = list.get(i);
            String name = resourceName(compiler, resource);
            if (name.isEmpty()) {
                continue;
            }
            long type = Spvc.spvc_compiler_get_type_handle(compiler, resource.type_id());
            if (Spvc.spvc_type_get_num_array_dimensions(type) != 0) {
                throw new IllegalStateException(
                        "Metal compute resource arrays are not yet supported: " + name
                );
            }
            if (bindings.containsKey(name)) {
                throw new IllegalStateException("Metal compute resource name is ambiguous: " + name);
            }

            Binding binding = slots.allocate(name, kind);
            remapBinding(stack, compiler, resource, binding);
            bindings.put(name, binding);
        }
    }

    private static void remapBinding(
            final MemoryStack stack,
            final long compiler,
            final SpvcReflectedResource resource,
            final Binding binding
    ) {
        SpvcMslResourceBinding2 remap = SpvcMslResourceBinding2.calloc(stack);
        Spvc.spvc_msl_resource_binding_init_2(remap);
        remap.stage(Spvc.spvc_compiler_get_execution_model(compiler));
        remap.desc_set(Spvc.spvc_compiler_get_decoration(
                compiler, resource.id(), Spv.SpvDecorationDescriptorSet));
        remap.binding(Spvc.spvc_compiler_get_decoration(
                compiler, resource.id(), Spv.SpvDecorationBinding));
        remap.count(1);
        if (binding.bufferIndex >= 0) {
            remap.msl_buffer(binding.bufferIndex);
        }
        if (binding.textureIndex >= 0) {
            remap.msl_texture(binding.textureIndex);
        }
        if (binding.samplerIndex >= 0) {
            remap.msl_sampler(binding.samplerIndex);
        }
        checkSpvc(
                Spvc.spvc_compiler_msl_add_resource_binding_2(compiler, remap),
                "spvc_compiler_msl_add_resource_binding_2(" + binding.name + ")"
        );
    }

    private static String resourceName(final long compiler, final SpvcReflectedResource resource) {
        String direct = resource.nameString();
        if (direct != null && !direct.isEmpty()) {
            return direct;
        }
        String fromId = Spvc.spvc_compiler_get_name(compiler, resource.id());
        if (fromId != null && !fromId.isEmpty()) {
            return fromId;
        }
        String fromType = Spvc.spvc_compiler_get_name(compiler, resource.type_id());
        return fromType == null ? "" : fromType;
    }

    private static void checkSpvc(final int result, final String stage) {
        if (result != Spvc.SPVC_SUCCESS) {
            throw new IllegalStateException("SPIRV-Cross error at " + stage + ": " + result);
        }
    }

    private enum Kind {
        UNIFORM_BUFFER,
        STORAGE_BUFFER,
        SAMPLED_IMAGE,
        STORAGE_IMAGE
    }

    private record Binding(
            String name,
            Kind kind,
            int bufferIndex,
            int textureIndex,
            int samplerIndex
    ) {
    }

    private static final class ArgumentSlots {
        private int buffers;
        private int textures;
        private int samplers;

        private Binding allocate(final String name, final Kind kind) {
            return switch (kind) {
                case UNIFORM_BUFFER, STORAGE_BUFFER ->
                        new Binding(name, kind, nextBuffer(name), -1, -1);
                case SAMPLED_IMAGE ->
                        new Binding(name, kind, -1, nextTexture(name), nextSampler(name));
                case STORAGE_IMAGE ->
                        new Binding(name, kind, -1, nextTexture(name), -1);
            };
        }

        private int nextBuffer(final String name) {
            if (this.buffers >= MAX_BUFFER_ARGUMENTS) {
                throw new IllegalStateException(
                        "Metal compute buffer argument limit exceeded while binding " + name
                                + ": limit=" + MAX_BUFFER_ARGUMENTS
                );
            }
            return this.buffers++;
        }

        private int nextTexture(final String name) {
            if (this.textures >= MAX_TEXTURE_ARGUMENTS) {
                throw new IllegalStateException(
                        "Metal compute texture argument limit exceeded while binding " + name
                                + ": limit=" + MAX_TEXTURE_ARGUMENTS
                );
            }
            return this.textures++;
        }

        private int nextSampler(final String name) {
            if (this.samplers >= MAX_SAMPLER_ARGUMENTS) {
                throw new IllegalStateException(
                        "Metal compute sampler argument limit exceeded while binding " + name
                                + ": limit=" + MAX_SAMPLER_ARGUMENTS
                );
            }
            return this.samplers++;
        }
    }

    private record Reflected(String msl, String entryPoint, Map<String, Binding> bindings) {
    }

    private static final class ComputePipeline implements AutoCloseable {
        private final MetalDevice device;
        private final String label;
        private final MemorySegment pipelineState;
        private final Map<String, Binding> bindings;
        private boolean closed;

        private ComputePipeline(
                final MetalDevice device,
                final String label,
                final MemorySegment pipelineState,
                final Map<String, Binding> bindings
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
