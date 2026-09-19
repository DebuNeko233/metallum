package com.metallum.render;

import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.mojang.blaze3d.GpuFormat;
import com.mojang.blaze3d.pipeline.BindGroupLayout;
import com.mojang.blaze3d.pipeline.BindGroupLayout.UniformDescription;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vertex.VertexFormat;
import com.mojang.blaze3d.vertex.VertexFormatElement;
import com.mojang.blaze3d.vulkan.VulkanBindGroupLayout;
import com.mojang.blaze3d.vulkan.VulkanBindGroupLayout.VulkanBindGroupEntryType;
import com.mojang.blaze3d.vulkan.glsl.*;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;
import org.lwjgl.PointerBuffer;
import org.lwjgl.system.MemoryStack;
import org.lwjgl.system.MemoryUtil;
import org.lwjgl.util.spvc.Spv;
import org.lwjgl.util.spvc.Spvc;
import org.lwjgl.util.spvc.SpvcMslResourceBinding;
import org.lwjgl.util.spvc.SpvcMslShaderInterfaceVar2;
import org.lwjgl.util.spvc.SpvcReflectedResource;

import java.nio.ByteBuffer;
import java.nio.IntBuffer;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import com.metallum.render.shared.MetalPipelineSupport;
import com.metallum.render.shared.MetalResourceBinding;
import com.metallum.render.shared.MetalPipelineKey;

@Environment(EnvType.CLIENT)
final class MetalCrossShaderCompiler {
    private static final Set<String> BUILT_IN_UNIFORMS = Set.of("Projection", "Lighting", "Fog", "Globals");
    private static final int DIRECT_SAMPLER_LIMIT = 16;
    private static final Pattern VERTEX_ENTRY_PATTERN = Pattern.compile("\\bvertex\\s+\\w+\\s+(\\w+)\\s*\\(");
    private static final Pattern FRAGMENT_ENTRY_PATTERN = Pattern.compile("\\bfragment\\s+\\w+\\s+(\\w+)\\s*\\(");
    private static final int[] ARGUMENT_RESOURCE_TYPES = {
            Spvc.SPVC_RESOURCE_TYPE_UNIFORM_BUFFER,
            Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER,
            Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE,
            Spvc.SPVC_RESOURCE_TYPE_SAMPLED_IMAGE,
            Spvc.SPVC_RESOURCE_TYPE_SEPARATE_IMAGE,
            Spvc.SPVC_RESOURCE_TYPE_SEPARATE_SAMPLERS
    };

    private MetalCrossShaderCompiler() {
    }

    static MetalCompiledRenderPipeline compile(final Metal3CompilationContext compilation, final RenderPipeline pipeline, final ShaderSource shaderSource) {
        try {
            IntermediaryShaderModule vertexSpirv = compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX, pipeline.getShaderDefines(), shaderSource);
            IntermediaryShaderModule fragmentSpirv = compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT, pipeline.getShaderDefines(), shaderSource);
            if (vertexSpirv == IntermediaryShaderModule.INVALID || fragmentSpirv == IntermediaryShaderModule.INVALID) {
                throw new IllegalStateException("Couldn't compile shader for pipeline " + pipeline.getLocation());
            }

            Set<String> storageBuffers = new LinkedHashSet<>();
            storageBuffers.addAll(resourceNames(vertexSpirv.spirv(), Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER));
            storageBuffers.addAll(resourceNames(fragmentSpirv.spirv(), Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER));
            Set<String> storageImages = new LinkedHashSet<>();
            storageImages.addAll(resourceNames(vertexSpirv.spirv(), Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE));
            storageImages.addAll(resourceNames(fragmentSpirv.spirv(), Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE));

            List<VulkanBindGroupLayout.Entry> layoutEntries = new ArrayList<>();
            addToBindGroup(layoutEntries, vertexSpirv, pipeline, storageImages);
            addToBindGroup(layoutEntries, fragmentSpirv, pipeline, storageImages);
            addStorageBufferPlaceholders(layoutEntries, storageBuffers, pipeline);
            addStorageImagePlaceholders(layoutEntries, storageImages, pipeline);
            List<String> vertexOutputs = extractVariableNames(vertexSpirv.outputs());

            boolean useArgumentBuffers = needsArgumentBuffers(layoutEntries, pipeline);
            if (useArgumentBuffers && !compilation.device().supportsArgumentBuffersTier2()) {
                throw new IllegalStateException(
                        "Pipeline " + pipeline.getLocation() + " requires wide Metal resources, but Argument Buffer Tier 2 is unavailable"
                );
            }
            int pushConstantBinding = useArgumentBuffers
                    ? MetalCompiledRenderPipeline.PUSH_CONSTANT_BUFFER_SLOT
                    : layoutEntries.size();

            vertexSpirv.rebind(tolerateUnprovidedInputs(MetalPipelineSupport.vertexAttributeNames(pipeline), vertexSpirv.inputs()), layoutEntries);
            rebindStorageResources(vertexSpirv.spirv(), storageBuffers, layoutEntries,
                    Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER, "storage buffer");
            rebindStorageResources(vertexSpirv.spirv(), storageImages, layoutEntries,
                    Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE, "storage image");
            MslShader vertexMsl = spirvToMsl(
                    vertexSpirv.spirv(),
                    pushConstantBinding,
                    vertexAttributeFormats(pipeline),
                    true,
                    Spv.SpvExecutionModelVertex,
                    useArgumentBuffers,
                    layoutEntries
            );

            boolean enableFragDepth = pipeline.getDepthStencilState() != null;
            fragmentSpirv.rebind(tolerateUnprovidedInputs(vertexOutputs, fragmentSpirv.inputs()), layoutEntries);
            rebindStorageResources(fragmentSpirv.spirv(), storageBuffers, layoutEntries,
                    Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER, "storage buffer");
            rebindStorageResources(fragmentSpirv.spirv(), storageImages, layoutEntries,
                    Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE, "storage image");
            MslShader fragmentMsl = spirvToMsl(
                    fragmentSpirv.spirv(),
                    pushConstantBinding,
                    Map.of(),
                    enableFragDepth,
                    Spv.SpvExecutionModelFragment,
                    useArgumentBuffers,
                    layoutEntries
            );

            String vertexEntryPoint = extractEntryPoint(vertexMsl.source(), VERTEX_ENTRY_PATTERN, "main0");
            String fragmentEntryPoint = extractEntryPoint(fragmentMsl.source(), FRAGMENT_ENTRY_PATTERN, "main0");
            List<MetalResourceBinding> resources = buildResourceBindings(
                    layoutEntries,
                    storageBuffers,
                    storageImages,
                    vertexMsl,
                    fragmentMsl,
                    useArgumentBuffers,
                    pushConstantBinding
            );
            return new MetalCompiledRenderPipeline(
                    MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), useArgumentBuffers),
                    compilation,
                    pipeline,
                    vertexMsl.source(),
                    fragmentMsl.source(),
                    vertexEntryPoint,
                    fragmentEntryPoint,
                    resources,
                    useArgumentBuffers,
                    vertexMsl.argumentBufferSets(),
                    fragmentMsl.argumentBufferSets()
            );
        } catch (ShaderCompileException e) {
            throw new IllegalStateException("Failed to compile Metal cross shader for pipeline " + pipeline.getLocation(), e);
        }
    }

    private static boolean needsArgumentBuffers(
            final List<VulkanBindGroupLayout.Entry> entries,
            final RenderPipeline pipeline
    ) {
        // A sampled image's sampler slot is the entry's own position in this list and not a count of
        // the sampled images before it. The uniform buffer sits at the front of every one of these
        // layouts, so sixteen sampled images behind it end at position sixteen while Metal has sixteen
        // sampler slots, nought to fifteen. Counting the images let that last one ask for a slot that
        // does not exist, and the cost of that is not a pipeline that runs slowly but one that does not
        // compile at all: photon's deferred4 at the pack's own defaults is exactly sixteen images
        // behind one buffer, and every one of its draws failed at the sixteenth sampler.
        int lastSamplerSlot = -1;
        for (int index = 0; index < entries.size(); index++) {
            if (entries.get(index).type() == VulkanBindGroupEntryType.SAMPLED_IMAGE) {
                lastSamplerSlot = index;
            }
        }
        int vertexBindingSpan = 0;
        VertexFormat[] vertexBindings = pipeline.getVertexFormatBindings();
        for (int index = vertexBindings.length - 1; index >= 0; index--) {
            if (vertexBindings[index] != null) {
                vertexBindingSpan = index + 1;
                break;
            }
        }
        // Minecraft 26.2 returns a fixed 16-slot array here. Null slots do not consume Metal
        // vertex-buffer table entries, so counting the array length promotes ordinary fullscreen
        // pipelines to Argument Buffers even when their live resources fit the direct tables.
        return lastSamplerSlot >= DIRECT_SAMPLER_LIMIT
                || entries.size() + vertexBindingSpan >= 31;
    }

    private static void addToBindGroup(
            final List<VulkanBindGroupLayout.Entry> entries,
            final IntermediaryShaderModule shader,
            final RenderPipeline pipeline,
            final Set<String> storageImages
    ) throws ShaderCompileException {
        List<UniformDescription> uniforms = BindGroupLayout.flattenUniforms(pipeline.getBindGroupLayouts());
        List<String> samplers = BindGroupLayout.flattenSamplers(pipeline.getBindGroupLayouts());
        for (SpvUniformBuffer buffer : shader.uniformBuffers()) {
            String name = buffer.name();
            if (findUniform(uniforms, name) == null && !BUILT_IN_UNIFORMS.contains(name)) {
                throw new ShaderCompileException("Unable to find shader defined uniform (" + name + ")");
            }
            addBindingIfAbsent(entries, VulkanBindGroupEntryType.UNIFORM_BUFFER, name, null);
        }

        for (SpvSampler sampler : shader.samplers()) {
            String name = sampler.name();
            UniformDescription uniform = findUniform(uniforms, name);
            int dimensions = sampler.dimensions();
            if (storageImages.contains(name)) {
                if (!samplers.contains(name)) {
                    throw new ShaderCompileException("Unable to find shader defined storage image (" + name + ")");
                }
                if (!supportedTextureDimension(dimensions)) {
                    throw new ShaderCompileException("Storage image (" + name + ") has unsupported dimension " + dimensions);
                }
                addBindingIfAbsent(entries, VulkanBindGroupEntryType.SAMPLED_IMAGE, name, null);
            } else if (uniform != null) {
                if (dimensions != Spv.SpvDimBuffer) {
                    throw new ShaderCompileException("UTB (" + name + ") must have type of SpvDimBuffer");
                }
                addBindingIfAbsent(entries, VulkanBindGroupEntryType.TEXEL_BUFFER, name, uniform.gpuFormat());
            } else {
                if (!samplers.contains(name)) {
                    throw new ShaderCompileException("Unable to find shader defined uniform (" + name + ")");
                }
                if (!supportedTextureDimension(dimensions) && dimensions != Spv.SpvDimCube) {
                    throw new ShaderCompileException("Sampled texture (" + name + ") has unsupported dimension " + dimensions);
                }
                addBindingIfAbsent(entries, VulkanBindGroupEntryType.SAMPLED_IMAGE, name, null);
            }
        }
    }

    private static boolean supportedTextureDimension(final int dimensions) {
        return dimensions == Spv.SpvDim1D || dimensions == Spv.SpvDim2D || dimensions == Spv.SpvDim3D;
    }

    private static void addStorageBufferPlaceholders(
            final List<VulkanBindGroupLayout.Entry> entries,
            final Set<String> storageBuffers,
            final RenderPipeline pipeline
    ) throws ShaderCompileException {
        if (storageBuffers.isEmpty()) {
            return;
        }
        List<UniformDescription> uniforms = BindGroupLayout.flattenUniforms(pipeline.getBindGroupLayouts());
        for (String name : storageBuffers) {
            if (findUniform(uniforms, name) == null) {
                throw new ShaderCompileException("Unable to find shader defined storage buffer (" + name + ")");
            }
            addBindingIfAbsent(entries, VulkanBindGroupEntryType.UNIFORM_BUFFER, name, null);
        }
    }

    private static void addStorageImagePlaceholders(
            final List<VulkanBindGroupLayout.Entry> entries,
            final Set<String> storageImages,
            final RenderPipeline pipeline
    ) throws ShaderCompileException {
        if (storageImages.isEmpty()) {
            return;
        }
        List<String> samplers = BindGroupLayout.flattenSamplers(pipeline.getBindGroupLayouts());
        for (String name : storageImages) {
            if (!samplers.contains(name)) {
                throw new ShaderCompileException("Unable to find shader defined storage image (" + name + ")");
            }
            addBindingIfAbsent(entries, VulkanBindGroupEntryType.SAMPLED_IMAGE, name, null);
        }
    }

    private static Set<String> resourceNames(final ByteBuffer spirvBytes, final int resourceType) throws ShaderCompileException {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            PointerBuffer pContext = stack.mallocPointer(1);
            checkSpvc(Spvc.spvc_context_create(pContext), "spvc_context_create");
            long context = pContext.get(0);
            try {
                PointerBuffer pIr = stack.mallocPointer(1);
                IntBuffer words = spirvBytes.asIntBuffer();
                checkSpvc(Spvc.spvc_context_parse_spirv(context, words, words.remaining(), pIr), "spvc_context_parse_spirv");
                PointerBuffer pCompiler = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_context_create_compiler(
                        context, Spvc.SPVC_BACKEND_NONE, pIr.get(0), Spvc.SPVC_CAPTURE_MODE_COPY, pCompiler),
                        "spvc_context_create_compiler");
                long compiler = pCompiler.get(0);
                PointerBuffer pResources = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_create_shader_resources(compiler, pResources), "spvc_context_create_shader_resources");
                PointerBuffer pList = stack.mallocPointer(1);
                PointerBuffer pCount = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(pResources.get(0), resourceType, pList, pCount),
                        "spvc_resources_get_resource_list_for_type");
                int count = (int) pCount.get(0);
                if (count == 0) {
                    return Set.of();
                }
                LinkedHashSet<String> names = new LinkedHashSet<>();
                SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
                for (int i = 0; i < count; i++) {
                    String name = resourceName(compiler, list.get(i));
                    if (!name.isEmpty()) {
                        names.add(name);
                    }
                }
                return names;
            } finally {
                Spvc.spvc_context_destroy(context);
            }
        }
    }

    private static void rebindStorageResources(
            final ByteBuffer spirvBytes,
            final Set<String> names,
            final List<VulkanBindGroupLayout.Entry> entries,
            final int resourceType,
            final String description
    ) throws ShaderCompileException {
        if (names.isEmpty()) {
            return;
        }
        Map<String, Integer> byName = new HashMap<>();
        for (int index = 0; index < entries.size(); index++) {
            String name = entries.get(index).name();
            if (names.contains(name)) {
                byName.put(name, index);
            }
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            IntBuffer words = spirvBytes.asIntBuffer();
            PointerBuffer pContext = stack.mallocPointer(1);
            checkSpvc(Spvc.spvc_context_create(pContext), "spvc_context_create");
            long context = pContext.get(0);
            try {
                PointerBuffer pIr = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_context_parse_spirv(context, words, words.remaining(), pIr), "spvc_context_parse_spirv");
                PointerBuffer pCompiler = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_context_create_compiler(
                        context, Spvc.SPVC_BACKEND_NONE, pIr.get(0), Spvc.SPVC_CAPTURE_MODE_COPY, pCompiler),
                        "spvc_context_create_compiler");
                long compiler = pCompiler.get(0);
                PointerBuffer pResources = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_create_shader_resources(compiler, pResources), "spvc_context_create_shader_resources");
                PointerBuffer pList = stack.mallocPointer(1);
                PointerBuffer pCount = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(pResources.get(0), resourceType, pList, pCount),
                        "spvc_resources_get_resource_list_for_type(" + description + ")");
                int count = (int) pCount.get(0);
                if (count == 0) {
                    return;
                }
                SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
                IntBuffer offset = stack.mallocInt(1);
                for (int i = 0; i < count; i++) {
                    SpvcReflectedResource resource = list.get(i);
                    Integer index = byName.get(resourceName(compiler, resource));
                    if (index == null) {
                        continue;
                    }
                    offset.clear();
                    if (!Spvc.spvc_compiler_get_binary_offset_for_decoration(
                            compiler, resource.id(), Spv.SpvDecorationBinding, offset)) {
                        throw new ShaderCompileException("Couldn't find binding decoration for " + description + " " + resourceName(compiler, resource));
                    }
                    words.put(offset.get(0), index);
                }
            } finally {
                Spvc.spvc_context_destroy(context);
            }
        }
    }

    private static String resourceName(final long compiler, final SpvcReflectedResource resource) {
        String name = resource.nameString();
        if (name != null && !name.isEmpty()) {
            return name;
        }
        String fromId = Spvc.spvc_compiler_get_name(compiler, resource.id());
        if (fromId != null && !fromId.isEmpty()) {
            return fromId;
        }
        String fromType = Spvc.spvc_compiler_get_name(compiler, resource.type_id());
        return fromType == null ? "" : fromType;
    }

    @Nullable
    private static UniformDescription findUniform(final List<UniformDescription> uniforms, final String name) {
        for (UniformDescription uniform : uniforms) {
            if (uniform.name().equals(name)) {
                return uniform;
            }
        }
        return null;
    }

    private static void addBindingIfAbsent(
            final List<VulkanBindGroupLayout.Entry> entries,
            final VulkanBindGroupEntryType type,
            final String name,
            @Nullable final GpuFormat texelBufferFormat
    ) {
        for (VulkanBindGroupLayout.Entry entry : entries) {
            if (entry.type() == type && entry.name().equals(name)) {
                return;
            }
        }
        entries.add(new VulkanBindGroupLayout.Entry(type, name, texelBufferFormat));
    }

    private static List<String> tolerateUnprovidedInputs(final List<String> provided, final List<SpvVariable> shaderInputs) {
        List<String> result = null;
        for (SpvVariable input : shaderInputs) {
            String name = input.name();
            if (!provided.contains(name)) {
                if (result == null) {
                    result = new ArrayList<>(provided);
                }
                if (!result.contains(name)) {
                    result.add(name);
                }
            }
        }
        return result == null ? provided : result;
    }

    private static List<String> extractVariableNames(final List<SpvVariable> variables) {
        List<String> names = new ArrayList<>(variables.size());
        for (SpvVariable variable : variables) {
            names.add(variable.name());
        }
        return names;
    }

    private static String extractEntryPoint(final String msl, final Pattern pattern, final String fallback) {
        Matcher matcher = pattern.matcher(msl);
        return matcher.find() ? matcher.group(1) : fallback;
    }

    private static List<MetalResourceBinding> buildResourceBindings(
            final List<VulkanBindGroupLayout.Entry> entries,
            final Set<String> storageBuffers,
            final Set<String> storageImages,
            final MslShader vertexMsl,
            final MslShader fragmentMsl,
            final boolean useArgumentBuffers,
            final int pushConstantBinding
    ) {
        List<MetalResourceBinding> resources = new ArrayList<>(entries.size() + 1);
        for (int index = 0; index < entries.size(); index++) {
            VulkanBindGroupLayout.Entry entry = entries.get(index);
            MetalResourceBinding.ResourceKind kind = switch (entry.type()) {
                case UNIFORM_BUFFER -> storageBuffers.contains(entry.name())
                        ? MetalResourceBinding.ResourceKind.STORAGE_BUFFER
                        : MetalResourceBinding.ResourceKind.UNIFORM_BUFFER;
                case SAMPLED_IMAGE -> storageImages.contains(entry.name())
                        ? MetalResourceBinding.ResourceKind.STORAGE_IMAGE
                        : MetalResourceBinding.ResourceKind.SAMPLED_IMAGE;
                case TEXEL_BUFFER -> MetalResourceBinding.ResourceKind.TEXEL_BUFFER;
            };
            GpuFormat texelFormat = entry.type() == VulkanBindGroupEntryType.TEXEL_BUFFER ? entry.texelBufferFormat() : null;
            int argumentSet = useArgumentBuffers ? descriptorSet(entry.name(), vertexMsl, fragmentMsl) : -1;
            int metalIndex = useArgumentBuffers ? index * 2 : index;
            int samplerIndex = useArgumentBuffers ? metalIndex + 1 : metalIndex;
            resources.add(new MetalResourceBinding(
                    kind,
                    entry.name(),
                    index,
                    stageMask(entry.name(), vertexMsl, fragmentMsl),
                    texelFormat,
                    metalIndex,
                    samplerIndex,
                    argumentSet
            ));
        }

        int pushConstantStageMask = (vertexMsl.hasPushConstants() ? MetalCompiledRenderPipeline.STAGE_VERTEX : 0)
                | (fragmentMsl.hasPushConstants() ? MetalCompiledRenderPipeline.STAGE_FRAGMENT : 0);
        if (pushConstantStageMask != 0) {
            resources.add(new MetalResourceBinding(
                    MetalResourceBinding.ResourceKind.UNIFORM_BUFFER,
                    "push_constants",
                    entries.size(),
                    pushConstantStageMask,
                    null,
                    pushConstantBinding,
                    pushConstantBinding,
                    -1
            ));
        }
        return resources;
    }

    private static int descriptorSet(final String name, final MslShader vertexMsl, final MslShader fragmentMsl) {
        Integer vertex = vertexMsl.descriptorSets().get(name);
        Integer fragment = fragmentMsl.descriptorSets().get(name);
        if (vertex != null && fragment != null && !vertex.equals(fragment)) {
            throw new IllegalStateException("Resource " + name + " moved descriptor sets between shader stages: " + vertex + " != " + fragment);
        }
        Integer set = vertex != null ? vertex : fragment;
        if (set == null) {
            throw new IllegalStateException("Argument-buffer resource " + name + " has no descriptor set");
        }
        return set;
    }

    private static int stageMask(final String name, final MslShader vertexMsl, final MslShader fragmentMsl) {
        int mask = 0;
        if (vertexMsl.activeResources().contains(name)) {
            mask |= MetalCompiledRenderPipeline.STAGE_VERTEX;
        }
        if (fragmentMsl.activeResources().contains(name)) {
            mask |= MetalCompiledRenderPipeline.STAGE_FRAGMENT;
        }
        return mask == 0 ? MetalCompiledRenderPipeline.STAGE_ALL : mask;
    }

    private static Map<String, GpuFormat> vertexAttributeFormats(final RenderPipeline pipeline) {
        Map<String, GpuFormat> formats = new LinkedHashMap<>();
        for (VertexFormat binding : pipeline.getVertexFormatBindings()) {
            if (binding != null) {
                for (VertexFormatElement element : binding.getElements()) {
                    formats.putIfAbsent(element.name(), element.format());
                }
            }
        }
        return formats;
    }

    private static void registerIntegerInputConversions(
            final MemoryStack stack,
            final long compiler,
            final Map<String, GpuFormat> attributeFormats
    ) throws ShaderCompileException {
        if (attributeFormats.isEmpty()) {
            return;
        }
        PointerBuffer pResources = stack.mallocPointer(1);
        checkSpvc(Spvc.spvc_compiler_create_shader_resources(compiler, pResources), "spvc_compiler_create_shader_resources");
        PointerBuffer pList = stack.mallocPointer(1);
        PointerBuffer pCount = stack.mallocPointer(1);
        checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(
                pResources.get(0), Spvc.SPVC_RESOURCE_TYPE_STAGE_INPUT, pList, pCount),
                "spvc_resources_get_resource_list_for_type(STAGE_INPUT)");
        int count = (int) pCount.get(0);
        if (count == 0) {
            return;
        }
        SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
        for (int i = 0; i < count; i++) {
            SpvcReflectedResource input = list.get(i);
            GpuFormat format = attributeFormats.get(input.nameString());
            if (format == null || !format.name().endsWith("_UINT")) {
                continue;
            }
            int width = format.name().contains("8") ? Spvc.SPVC_MSL_SHADER_VARIABLE_FORMAT_UINT8
                    : format.name().contains("16") ? Spvc.SPVC_MSL_SHADER_VARIABLE_FORMAT_UINT16
                    : Spvc.SPVC_MSL_SHADER_VARIABLE_FORMAT_OTHER;
            if (width == Spvc.SPVC_MSL_SHADER_VARIABLE_FORMAT_OTHER) {
                continue;
            }
            long typeHandle = Spvc.spvc_compiler_get_type_handle(compiler, input.type_id());
            int baseType = Spvc.spvc_type_get_basetype(typeHandle);
            if (baseType != Spvc.SPVC_BASETYPE_INT8 && baseType != Spvc.SPVC_BASETYPE_INT16
                    && baseType != Spvc.SPVC_BASETYPE_INT32 && baseType != Spvc.SPVC_BASETYPE_INT64) {
                continue;
            }
            SpvcMslShaderInterfaceVar2 var = SpvcMslShaderInterfaceVar2.malloc(stack);
            Spvc.spvc_msl_shader_interface_var_init_2(var);
            var.location(Spvc.spvc_compiler_get_decoration(compiler, input.id(), Spv.SpvDecorationLocation));
            var.vecsize(Spvc.spvc_type_get_vector_size(typeHandle));
            var.format(width);
            var.rate(Spvc.SPVC_MSL_SHADER_VARIABLE_RATE_PER_VERTEX);
            checkSpvc(Spvc.spvc_compiler_msl_add_shader_input_2(compiler, var), "spvc_compiler_msl_add_shader_input_2");
        }
    }

    private static MslShader spirvToMsl(
            final ByteBuffer spirvBytes,
            final int pushConstantBinding,
            final Map<String, GpuFormat> attributeFormats,
            final boolean enableFragDepth,
            final int executionModel,
            final boolean useArgumentBuffers,
            final List<VulkanBindGroupLayout.Entry> layoutEntries
    ) throws ShaderCompileException {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            IntBuffer spirvWords = spirvBytes.asIntBuffer();
            PointerBuffer pContext = stack.mallocPointer(1);
            checkSpvc(Spvc.spvc_context_create(pContext), "spvc_context_create");
            long context = pContext.get(0);
            try {
                PointerBuffer pIr = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_context_parse_spirv(context, spirvWords, spirvWords.remaining(), pIr), "spvc_context_parse_spirv");
                PointerBuffer pCompiler = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_context_create_compiler(
                        context, Spvc.SPVC_BACKEND_MSL, pIr.get(0), Spvc.SPVC_CAPTURE_MODE_COPY, pCompiler),
                        "spvc_context_create_compiler");
                long compiler = pCompiler.get(0);

                PointerBuffer pOptions = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_create_compiler_options(compiler, pOptions), "spvc_compiler_create_compiler_options");
                long options = pOptions.get(0);
                checkSpvc(Spvc.spvc_compiler_options_set_uint(options, Spvc.SPVC_COMPILER_OPTION_MSL_PLATFORM, Spvc.SPVC_MSL_PLATFORM_MACOS),
                        "spvc_compiler_options_set_uint(MSL_PLATFORM)");
                checkSpvc(Spvc.spvc_compiler_options_set_uint(options, Spvc.SPVC_COMPILER_OPTION_MSL_VERSION,
                                MetalShaderLanguageProfile.selected().spirvCrossMslVersion()),
                        "spvc_compiler_options_set_uint(MSL_VERSION)");
                checkSpvc(Spvc.spvc_compiler_options_set_bool(
                        options, Spvc.SPVC_COMPILER_OPTION_MSL_ENABLE_DECORATION_BINDING, !useArgumentBuffers),
                        "spvc_compiler_options_set_bool(MSL_ENABLE_DECORATION_BINDING)");
                checkSpvc(Spvc.spvc_compiler_options_set_bool(options, Spvc.SPVC_COMPILER_OPTION_MSL_TEXTURE_BUFFER_NATIVE, true),
                        "spvc_compiler_options_set_bool(MSL_TEXTURE_BUFFER_NATIVE)");
                checkSpvc(Spvc.spvc_compiler_options_set_bool(options, Spvc.SPVC_COMPILER_OPTION_FLIP_VERTEX_Y, true),
                        "spvc_compiler_options_set_bool(FLIP_VERTEX_Y)");
                if (executionModel == Spv.SpvExecutionModelFragment) {
                    checkSpvc(Spvc.spvc_compiler_options_set_bool(
                            options, Spvc.SPVC_COMPILER_OPTION_MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS, true),
                            "spvc_compiler_options_set_bool(MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS)");
                }
                if (useArgumentBuffers) {
                    checkSpvc(Spvc.spvc_compiler_options_set_bool(options, Spvc.SPVC_COMPILER_OPTION_MSL_ARGUMENT_BUFFERS, true),
                            "spvc_compiler_options_set_bool(MSL_ARGUMENT_BUFFERS)");
                    checkSpvc(Spvc.spvc_compiler_options_set_uint(options, Spvc.SPVC_COMPILER_OPTION_MSL_ARGUMENT_BUFFERS_TIER, 1),
                            "spvc_compiler_options_set_uint(MSL_ARGUMENT_BUFFERS_TIER)");
                }
                if (!enableFragDepth) {
                    checkSpvc(Spvc.spvc_compiler_options_set_bool(options, Spvc.SPVC_COMPILER_OPTION_MSL_ENABLE_FRAG_DEPTH_BUILTIN, false),
                            "spvc_compiler_options_set_bool(MSL_ENABLE_FRAG_DEPTH_BUILTIN)");
                }
                checkSpvc(Spvc.spvc_compiler_install_compiler_options(compiler, options), "spvc_compiler_install_compiler_options");

                registerIntegerInputConversions(stack, compiler, attributeFormats);

                PointerBuffer pActiveSet = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_get_active_interface_variables(compiler, pActiveSet), "spvc_compiler_get_active_interface_variables");
                long activeSet = pActiveSet.get(0);
                checkSpvc(Spvc.spvc_compiler_set_enabled_interface_variables(compiler, activeSet), "spvc_compiler_set_enabled_interface_variables");
                Set<String> activeResources = collectActiveResourceNames(stack, compiler, activeSet);

                Map<String, Integer> descriptorSets = useArgumentBuffers
                        ? registerArgumentBufferBindings(stack, compiler, executionModel, layoutEntries)
                        : Map.of();
                Set<Integer> argumentBufferSets = new TreeSet<>();
                if (useArgumentBuffers) {
                    for (Map.Entry<String, Integer> entry : descriptorSets.entrySet()) {
                        if (activeResources.contains(entry.getKey())) {
                            argumentBufferSets.add(entry.getValue());
                        }
                    }
                }

                PointerBuffer pResources = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_create_shader_resources(compiler, pResources), "spvc_compiler_create_shader_resources");
                long resources = pResources.get(0);
                PointerBuffer pList = stack.mallocPointer(1);
                PointerBuffer pCount = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(
                        resources, Spvc.SPVC_RESOURCE_TYPE_PUSH_CONSTANT, pList, pCount),
                        "spvc_resources_get_resource_list_for_type(PUSH_CONSTANT)");
                boolean hasPushConstants = pCount.get(0) > 0;
                if (hasPushConstants) {
                    SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), 1);
                    Spvc.spvc_compiler_set_decoration(compiler, list.get(0).id(), Spv.SpvDecorationBinding, pushConstantBinding);
                    if (useArgumentBuffers) {
                        SpvcMslResourceBinding pushConstant = SpvcMslResourceBinding.malloc(stack);
                        Spvc.spvc_msl_resource_binding_init(pushConstant);
                        pushConstant.stage(executionModel);
                        pushConstant.desc_set(Spvc.SPVC_MSL_PUSH_CONSTANT_DESC_SET);
                        pushConstant.binding(Spvc.SPVC_MSL_PUSH_CONSTANT_BINDING);
                        pushConstant.msl_buffer(pushConstantBinding);
                        pushConstant.msl_texture(0);
                        pushConstant.msl_sampler(0);
                        checkSpvc(Spvc.spvc_compiler_msl_add_resource_binding(compiler, pushConstant),
                                "spvc_compiler_msl_add_resource_binding(push constant)");
                    }
                }

                PointerBuffer pSource = stack.mallocPointer(1);
                checkSpvc(Spvc.spvc_compiler_compile(compiler, pSource), "spvc_compiler_compile");
                return new MslShader(
                        MemoryUtil.memUTF8(pSource.get(0)),
                        hasPushConstants,
                        activeResources,
                        Map.copyOf(descriptorSets),
                        Set.copyOf(argumentBufferSets)
                );
            } finally {
                Spvc.spvc_context_destroy(context);
            }
        }
    }

    private static Map<String, Integer> registerArgumentBufferBindings(
            final MemoryStack stack,
            final long compiler,
            final int executionModel,
            final List<VulkanBindGroupLayout.Entry> layoutEntries
    ) throws ShaderCompileException {
        Map<String, Integer> logicalBindings = new HashMap<>();
        for (int i = 0; i < layoutEntries.size(); i++) {
            logicalBindings.put(layoutEntries.get(i).name(), i);
        }

        Map<String, Integer> descriptorSets = new HashMap<>();
        Set<Integer> sets = new TreeSet<>();
        PointerBuffer pResources = stack.mallocPointer(1);
        checkSpvc(Spvc.spvc_compiler_create_shader_resources(compiler, pResources), "spvc_compiler_create_shader_resources(argument buffers)");
        long resources = pResources.get(0);

        for (int resourceType : ARGUMENT_RESOURCE_TYPES) {
            PointerBuffer pList = stack.mallocPointer(1);
            PointerBuffer pCount = stack.mallocPointer(1);
            checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(resources, resourceType, pList, pCount),
                    "spvc_resources_get_resource_list_for_type(argument buffer)");
            int count = (int) pCount.get(0);
            if (count == 0) {
                continue;
            }
            SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
            for (int i = 0; i < count; i++) {
                SpvcReflectedResource resource = list.get(i);
                String name = resourceName(compiler, resource);
                Integer logicalIndex = logicalBindings.get(name);
                if (logicalIndex == null) {
                    continue;
                }
                int descriptorSet = Spvc.spvc_compiler_get_decoration(compiler, resource.id(), Spv.SpvDecorationDescriptorSet);
                int descriptorBinding = Spvc.spvc_compiler_get_decoration(compiler, resource.id(), Spv.SpvDecorationBinding);
                if (descriptorSet < 0 || descriptorSet >= MetalCompiledRenderPipeline.ARGUMENT_BUFFER_SLOT_COUNT) {
                    throw new ShaderCompileException(
                            "Metal argument-buffer descriptor set " + descriptorSet + " for " + name + " is outside supported 0.."
                                    + (MetalCompiledRenderPipeline.ARGUMENT_BUFFER_SLOT_COUNT - 1)
                    );
                }
                Integer previous = descriptorSets.putIfAbsent(name, descriptorSet);
                if (previous != null && previous != descriptorSet) {
                    throw new ShaderCompileException("Resource " + name + " appears in multiple descriptor sets");
                }
                sets.add(descriptorSet);
                int primary = logicalIndex * 2;
                SpvcMslResourceBinding mapping = SpvcMslResourceBinding.malloc(stack);
                Spvc.spvc_msl_resource_binding_init(mapping);
                mapping.stage(executionModel);
                mapping.desc_set(descriptorSet);
                mapping.binding(descriptorBinding);
                mapping.msl_buffer(primary);
                mapping.msl_texture(primary);
                mapping.msl_sampler(primary + 1);
                checkSpvc(Spvc.spvc_compiler_msl_add_resource_binding(compiler, mapping), "spvc_compiler_msl_add_resource_binding(resource)");
            }
        }

        for (int descriptorSet : sets) {
            SpvcMslResourceBinding argumentBuffer = SpvcMslResourceBinding.malloc(stack);
            Spvc.spvc_msl_resource_binding_init(argumentBuffer);
            argumentBuffer.stage(executionModel);
            argumentBuffer.desc_set(descriptorSet);
            argumentBuffer.binding(Spvc.SPVC_MSL_ARGUMENT_BUFFER_BINDING);
            argumentBuffer.msl_buffer(descriptorSet);
            argumentBuffer.msl_texture(0);
            argumentBuffer.msl_sampler(0);
            checkSpvc(Spvc.spvc_compiler_msl_add_resource_binding(compiler, argumentBuffer),
                    "spvc_compiler_msl_add_resource_binding(argument buffer)");
        }
        return descriptorSets;
    }

    record MslShader(
            String source,
            boolean hasPushConstants,
            Set<String> activeResources,
            Map<String, Integer> descriptorSets,
            Set<Integer> argumentBufferSets
    ) {
    }

    private static Set<String> collectActiveResourceNames(
            final MemoryStack stack,
            final long compiler,
            final long activeSet
    ) throws ShaderCompileException {
        PointerBuffer pResources = stack.mallocPointer(1);
        checkSpvc(Spvc.spvc_compiler_create_shader_resources_for_active_variables(compiler, pResources, activeSet),
                "spvc_compiler_create_shader_resources_for_active_variables");
        long resources = pResources.get(0);
        Set<String> names = new HashSet<>();
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_UNIFORM_BUFFER, names);
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_BUFFER, names);
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_STORAGE_IMAGE, names);
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_SAMPLED_IMAGE, names);
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_SEPARATE_IMAGE, names);
        collectResourceNames(stack, resources, Spvc.SPVC_RESOURCE_TYPE_SEPARATE_SAMPLERS, names);
        return names;
    }

    private static void collectResourceNames(
            final MemoryStack stack,
            final long resources,
            final int resourceType,
            final Set<String> out
    ) throws ShaderCompileException {
        PointerBuffer pList = stack.mallocPointer(1);
        PointerBuffer pCount = stack.mallocPointer(1);
        checkSpvc(Spvc.spvc_resources_get_resource_list_for_type(resources, resourceType, pList, pCount),
                "spvc_resources_get_resource_list_for_type");
        int count = (int) pCount.get(0);
        if (count == 0) {
            return;
        }
        SpvcReflectedResource.Buffer list = SpvcReflectedResource.create(pList.get(0), count);
        for (int i = 0; i < count; i++) {
            String name = resourceNameForActiveResource(list.get(i));
            if (!name.isEmpty()) {
                out.add(name);
            }
        }
    }

    private static String resourceNameForActiveResource(final SpvcReflectedResource resource) {
        String name = resource.nameString();
        return name == null ? "" : name;
    }

    private static void checkSpvc(final int result, final String stage) throws ShaderCompileException {
        if (result != Spvc.SPVC_SUCCESS) {
            throw new ShaderCompileException("SPIRV-Cross error at " + stage + ": " + result);
        }
    }
}
