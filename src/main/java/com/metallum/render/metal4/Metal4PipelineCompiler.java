package com.metallum.render.metal4;

import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.metallum.render.shared.MetalCrossShaderTranslator;
import com.metallum.render.shared.MetalPipelineKey;
import com.metallum.render.shared.TranslatedRenderPipeline;
import com.metallum.render.shared.TranslationLayout;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Builds a Metal 4 compiled pipeline: this generation's half of what one method used to do.
 * <p>
 * It is the Metal 3 compiler's shape, and the difference between them is one argument. The Metal 3 compiler asks
 * the translator for an argument-buffer layout where the device supports one; this one asks for direct bindings
 * and says why: Metal 4's binding mechanism is the argument <em>table</em>, so a pipeline translated for
 * argument buffers would be handed the previous generation's mechanism inside the new path. Everything else -
 * which shader modules to ask the context for, the layout policy the bindings are laid out against, the pipeline
 * key, the artifact constructor - is the same work written out in this package, because
 * {@code render.metal4} may not call into {@code render.metal3}.
 * <p>
 * The translation itself is shared and is not duplicated: how SPIR-V becomes MSL, and what resources that MSL
 * ended up declaring, is exactly the layer the plan's section 27 puts between the two generations.
 */
@Environment(EnvType.CLIENT)
final class Metal4PipelineCompiler {

    /** Where this generation puts push constants in a direct-binding layout, as Metal 3 does. */
    private static final int PUSH_CONSTANT_SLOT = 8;

    /**
     * How many argument-buffer slots the layout reserves. Zero because this generation does not use argument
     * buffers at all: the parameter is still passed to the shared layout so that a binding's argument-buffer set
     * is what the translator says it is rather than what this class hopes.
     */
    private static final int ARGUMENT_BUFFER_SLOT_COUNT = 0;

    private Metal4PipelineCompiler() {
    }

    static Metal4CompiledRenderPipeline compile(final Metal4CompilationContext compilation,
                                                final RenderPipeline pipeline,
                                                final ShaderSource shaderSource) {
        try {
            IntermediaryShaderModule vertexSpirv = compilation.getOrCompileShader(pipeline.getVertexShader(),
                    ShaderType.VERTEX, pipeline.getShaderDefines(), shaderSource);
            IntermediaryShaderModule fragmentSpirv = compilation.getOrCompileShader(pipeline.getFragmentShader(),
                    ShaderType.FRAGMENT, pipeline.getShaderDefines(), shaderSource);
            if (vertexSpirv == IntermediaryShaderModule.INVALID || fragmentSpirv == IntermediaryShaderModule.INVALID) {
                throw new IllegalStateException("Couldn't compile shader for pipeline " + pipeline.getLocation());
            }

            TranslationLayout layout = new TranslationLayout(PUSH_CONSTANT_SLOT, ARGUMENT_BUFFER_SLOT_COUNT);
            // The false is the design decision this class exists for: direct bindings, because the table is this
            // generation's binding mechanism and an argument buffer is the previous generation's.
            TranslatedRenderPipeline translated =
                    MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, false);
            if (translated.usesArgumentBuffers()) {
                throw new IllegalStateException("The shared translator produced an argument-buffer layout for "
                        + pipeline.getLocation() + " where Metal 4 asked for direct bindings, so the binding"
                        + " path this generation would fill is not the one the shader was compiled against");
            }

            return new Metal4CompiledRenderPipeline(
                    MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), false),
                    compilation,
                    pipeline,
                    translated.vertexMsl(),
                    translated.fragmentMsl(),
                    translated.vertexEntryPoint(),
                    translated.fragmentEntryPoint(),
                    translated.resources()
            );
        } catch (ShaderCompileException failure) {
            throw new IllegalStateException("Failed to compile Metal cross shader for pipeline "
                    + pipeline.getLocation(), failure);
        }
    }
}
