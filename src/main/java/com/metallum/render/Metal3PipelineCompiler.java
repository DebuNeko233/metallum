package com.metallum.render;

import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.metallum.render.shared.MetalCrossShaderTranslator;
import com.metallum.render.shared.TranslatedRenderPipeline;
import com.metallum.render.shared.TranslationLayout;
import com.metallum.render.shared.MetalPipelineKey;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Builds a Metal 3 compiled pipeline: the generation's half of what one method used to do.
 * <p>
 * It owns what the translation must not know - which shader modules this generation asks its context for, the
 * capability that decides argument buffers, the layout policy its bindings are laid out against, the pipeline
 * key and the artifact constructor - and it owns nothing about how SPIR-V becomes MSL.
 * <p>
 * It lives in {@code com.metallum.render} for now, beside the artifact and the context it builds from, because
 * both are still package-private collaborators; it moves to {@code render.metal3} with them rather than before
 * them, which would only reintroduce visibility noise.
 */
@Environment(EnvType.CLIENT)
final class Metal3PipelineCompiler {

    /** Where this generation puts push constants in a direct-binding layout. */
    private static final int PUSH_CONSTANT_SLOT = 8;

    /** How many argument-buffer slots this generation's layout reserves. */
    private static final int ARGUMENT_BUFFER_SLOT_COUNT = 8;

    private Metal3PipelineCompiler() {
    }

    static MetalCompiledRenderPipeline compile(final Metal3CompilationContext compilation, final RenderPipeline pipeline, final ShaderSource shaderSource) {
        try {
            IntermediaryShaderModule vertexSpirv = compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX, pipeline.getShaderDefines(), shaderSource);
            IntermediaryShaderModule fragmentSpirv = compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT, pipeline.getShaderDefines(), shaderSource);
            if (vertexSpirv == IntermediaryShaderModule.INVALID || fragmentSpirv == IntermediaryShaderModule.INVALID) {
                throw new IllegalStateException("Couldn't compile shader for pipeline " + pipeline.getLocation());
            }

            boolean argumentBuffersTier2 = compilation.device().supportsArgumentBuffersTier2();
            TranslationLayout layout = new TranslationLayout(PUSH_CONSTANT_SLOT, ARGUMENT_BUFFER_SLOT_COUNT);
            TranslatedRenderPipeline translated =
                    MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, argumentBuffersTier2);

            return new MetalCompiledRenderPipeline(
                    MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), translated.usesArgumentBuffers()),
                    compilation,
                    pipeline,
                    translated.vertexMsl(),
                    translated.fragmentMsl(),
                    translated.vertexEntryPoint(),
                    translated.fragmentEntryPoint(),
                    translated.resources(),
                    translated.usesArgumentBuffers(),
                    translated.vertexArgumentBufferSets(),
                    translated.fragmentArgumentBufferSets()
            );
        } catch (ShaderCompileException e) {
            throw new IllegalStateException("Failed to compile Metal cross shader for pipeline " + pipeline.getLocation(), e);
        }
    }
}
