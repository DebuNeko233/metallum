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
 * It is the Metal 3 compiler's shape, and the difference between them is where the device's argument-buffer
 * answer comes from: the Metal 3 compiler asks the session's device, and so does this one. A pipeline that fits
 * MSL's direct slots is translated for direct bindings and its resources are written into the argument
 * <em>table</em>, which is this generation's binding mechanism; a pipeline that does not fit - a sampler index
 * beyond fifteen, which the table's own sixteen-slot ceiling makes unreachable - is translated into an argument
 * buffer, exactly as the reference generation translates it, and this generation's part is to carry that buffer
 * in one of the table's buffer slots. The rest - which shader modules to ask the context for, the layout policy
 * the bindings are laid out against, the pipeline key, the artifact constructor - is the same work written out
 * in this package, because {@code render.metal4} may not call into {@code render.metal3}.
 * <p>
 * The translation itself is shared and is not duplicated: how SPIR-V becomes MSL, and what resources that MSL
 * ended up declaring, is exactly the layer the plan's section 27 puts between the two generations.
 */
@Environment(EnvType.CLIENT)
final class Metal4PipelineCompiler {

    /** Where this generation puts push constants in a direct-binding layout, as Metal 3 does. */
    private static final int PUSH_CONSTANT_SLOT = 8;

    /**
     * How many argument-buffer slots the layout reserves, which is the Metal 3 compiler's own number and for the
     * same reason: it is the range of descriptor sets the pack's shaders may declare, and a generation that
     * bound the same program through a different mechanism does not get to narrow it. Too small a number here
     * is not a missed optimisation but a pipeline that refuses to compile.
     */
    private static final int ARGUMENT_BUFFER_SLOT_COUNT = 8;

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
            // The capability is the device's answer rather than this generation's opinion. It used to be a
            // literal false, on the reading that an argument buffer is the previous generation's binding
            // mechanism and that the table replaces it - and the table does replace it for everything that
            // fits, which is what keeps this path's ordinary pipelines direct. What it does not replace is the
            // *sampler* ceiling: MTL4ArgumentTable.h caps a table at sixteen sampler slots, MSL declares one
            // sampler attribute per sampled image with no way to pack them, and the Metal 3 direct API is
            // capped at the same sixteen. Photon's deferred4 reads nineteen sampled images. A wide pipeline
            // carries its resources in an argument buffer on both generations; what is Metal 4's own is how
            // that buffer is handed over - one of the table's buffer slots, filled by address - and that is
            // this path's part of it, in the plan and in the pass.
            boolean argumentBuffersTier2 = compilation.device().supportsArgumentBuffersTier2();
            TranslatedRenderPipeline translated =
                    MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout,
                            argumentBuffersTier2);
            if (translated.usesArgumentBuffers() && !argumentBuffersTier2) {
                throw new IllegalStateException("The shared translator laid " + pipeline.getLocation()
                        + " out for argument buffers and this device has no argument-buffer tier 2, so the"
                        + " buffer those resources were laid out in could not be made");
            }

            return new Metal4CompiledRenderPipeline(
                    MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(),
                            translated.usesArgumentBuffers()),
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
        } catch (ShaderCompileException failure) {
            throw new IllegalStateException("Failed to compile Metal cross shader for pipeline "
                    + pipeline.getLocation(), failure);
        }
    }
}
