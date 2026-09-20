package com.metallum.render.shared;

import com.metallum.render.execution.MetalShaderLanguageProfile;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.lwjgl.PointerBuffer;
import org.lwjgl.system.MemoryStack;
import org.lwjgl.system.MemoryUtil;
import org.lwjgl.util.spvc.Spv;
import org.lwjgl.util.spvc.Spvc;
import org.lwjgl.util.spvc.SpvcMslResourceBinding2;
import org.lwjgl.util.spvc.SpvcReflectedResource;

import java.nio.ByteBuffer;
import java.nio.IntBuffer;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The compute half of the shared translation layer: one SPIR-V kernel module in, MSL and the reflected bindings
 * out.
 * <p>
 * It sits beside {@link MetalCrossShaderTranslator} for the reason that class exists: what a shader means does not
 * depend on which command API encodes it. Both generations run compute through this, and what each does with the
 * answer is the generation's own business - Metal 3 hands the bindings to {@code setBuffer:offset:atIndex:} and
 * friends, Metal 4 fills an argument table by resource id - so nothing here names an encoder, a table, or a
 * generation. The binding indices are the shader's, and they mean the same slot number either way.
 * <p>
 * <strong>The slots are allocated per kind and the shader is told about them.</strong> Metal's buffer, texture
 * and sampler argument tables are independent, so a kernel's resources are numbered within their own kind, and
 * {@code spvc_compiler_msl_add_resource_binding_2} writes that numbering into the emitted
 * {@code [[buffer(n)]]}/{@code [[texture(n)]]}/{@code [[sampler(n)]]} attributes. A caller therefore binds by the
 * index this class hands back and not by the pack's own binding numbers: the remap is what makes the two agree.
 * <p>
 * <strong>The profile is part of the translation, as it is for a render pipeline.</strong> The MSL version comes
 * from {@link MetalShaderLanguageProfile#selected()}, and a caller that caches the emitted MSL without keying on
 * that profile would be safe by accident.
 */
@Environment(EnvType.CLIENT)
public final class MetalComputeTranslator {

    /**
     * Metal's own argument-table limits, and the bound this allocator refuses past rather than wrapping.
     * <p>
     * The numbers are the framework's: an argument table takes at most 31 buffers, 128 textures and 16 samplers.
     * A kernel that asks for more than its device has slots cannot be bound at all, so the refusal happens here,
     * where the offending resource can be named, rather than at the encoder.
     */
    private static final int MAX_BUFFER_ARGUMENTS = 31;
    private static final int MAX_TEXTURE_ARGUMENTS = 128;
    private static final int MAX_SAMPLER_ARGUMENTS = 16;

    /**
     * The kernel entry point in emitted MSL, which SPIRV-Cross writes as {@code kernel void name(...)}.
     * <p>
     * Read off the text rather than assumed to be {@code main0}: the fallback is there for a module whose entry
     * point the pattern does not catch, but a name taken from the source is the one that exists.
     */
    private static final Pattern KERNEL_ENTRY_PATTERN = Pattern.compile("\\bkernel\\s+\\w+\\s+(\\w+)\\s*\\(");

    private MetalComputeTranslator() {
    }

    /**
     * A kernel's translated MSL, its entry point, and where each of its resources lands.
     *
     * @param msl        the emitted Metal Shading Language source
     * @param entryPoint the kernel function's name in that source
     * @param bindings   the reflected resources by the name the pack declared, in reflection order
     */
    public record Translated(String msl, String entryPoint, Map<String, Binding> bindings) {
    }

    /**
     * One reflected resource: what it is, what the pack called it, and the slot each kind's table reads it from.
     * <p>
     * A binding is one kind of resource, so exactly one of the three indices is meaningful for it and the other
     * two are {@code -1}. They are separate fields rather than one index because Metal's three argument tables
     * are numbered independently: the third buffer and the third texture are both slot 2, and a caller binding
     * one for the other would be a resource in the wrong table rather than a wrong number.
     *
     * @param name         the name the pack declared, which is how a missing binding is reported
     * @param kind         the kind of resource, in the engine's own terms
     * @param bufferIndex  its buffer slot, or {@code -1} where it is not a buffer
     * @param textureIndex its texture slot, or {@code -1} where it is not a texture
     * @param samplerIndex its sampler slot, or {@code -1} where it has no sampler
     */
    public record Binding(
            String name,
            MetalResourceBinding.ResourceKind kind,
            int bufferIndex,
            int textureIndex,
            int samplerIndex
    ) {
    }

    /**
     * Translates one compute SPIR-V module, remapping its resources onto Metal's argument slots.
     *
     * @param spirvBytes the SPIR-V module, as the game's compiler produced it
     * @throws IllegalStateException where SPIRV-Cross refuses a stage, or the module uses something this
     *                               translation has no answer for yet
     */
    public static Translated translate(final ByteBuffer spirvBytes) {
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
                return new Translated(msl, entryPoint, Map.copyOf(bindings));
            } finally {
                Spvc.spvc_context_destroy(context);
            }
        }
    }

    /** The MSL options a compute module is translated under: this platform, the selected profile, native texel buffers. */
    private static void installMslOptions(final MemoryStack stack, final long compiler) {
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

    /** The module's resources, each allocated a slot of its own kind and remapped onto it in the emitted MSL. */
    private static Map<String, Binding> reflectAndRemapBindings(
            final MemoryStack stack,
            final long compiler
    ) {
        PointerBuffer pResources = stack.mallocPointer(1);
        checkSpvc(
                Spvc.spvc_compiler_create_shader_resources(compiler, pResources),
                "spvc_compiler_create_shader_resources"
        );
        long resources = pResources.get(0);
        LinkedHashMap<String, Binding> bindings = new LinkedHashMap<>();
        ArgumentSlots slots = new ArgumentSlots();
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_UNIFORM_BUFFER,
                MetalResourceBinding.ResourceKind.UNIFORM_BUFFER, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER,
                MetalResourceBinding.ResourceKind.STORAGE_BUFFER, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_SAMPLED_IMAGE,
                MetalResourceBinding.ResourceKind.SAMPLED_IMAGE, bindings, slots);
        collectBindings(stack, compiler, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE,
                MetalResourceBinding.ResourceKind.STORAGE_IMAGE, bindings, slots);
        return bindings;
    }

    private static void collectBindings(
            final MemoryStack stack,
            final long compiler,
            final long resources,
            final int resourceType,
            final MetalResourceBinding.ResourceKind kind,
            final Map<String, Binding> bindings,
            final ArgumentSlots slots
    ) {
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

    /** Tells SPIRV-Cross which slot the emitted MSL reads this resource from, by its own descriptor set and binding. */
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
        if (binding.bufferIndex() >= 0) {
            remap.msl_buffer(binding.bufferIndex());
        }
        if (binding.textureIndex() >= 0) {
            remap.msl_texture(binding.textureIndex());
        }
        if (binding.samplerIndex() >= 0) {
            remap.msl_sampler(binding.samplerIndex());
        }
        checkSpvc(
                Spvc.spvc_compiler_msl_add_resource_binding_2(compiler, remap),
                "spvc_compiler_msl_add_resource_binding_2(" + binding.name() + ")"
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

    /**
     * The slot allocator: one counter per argument table, refusing rather than wrapping past what Metal has.
     * <p>
     * The counts are per kind because the tables are: a kernel with one buffer and one texture uses slot 0 of
     * each, and the two are not competing for the same number.
     */
    private static final class ArgumentSlots {
        private int buffers;
        private int textures;
        private int samplers;

        private Binding allocate(final String name, final MetalResourceBinding.ResourceKind kind) {
            return switch (kind) {
                case UNIFORM_BUFFER, STORAGE_BUFFER ->
                        new Binding(name, kind, nextBuffer(name), -1, -1);
                case SAMPLED_IMAGE ->
                        new Binding(name, kind, -1, nextTexture(name), nextSampler(name));
                case STORAGE_IMAGE ->
                        new Binding(name, kind, -1, nextTexture(name), -1);
                case TEXEL_BUFFER -> throw new IllegalStateException(
                        "Metal compute texel buffers are not yet supported: " + name);
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
}
