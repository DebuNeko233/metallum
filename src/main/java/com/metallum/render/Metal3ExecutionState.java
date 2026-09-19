package com.metallum.render;

import com.metallum.mtl.MTLCompareFunction;
import com.metallum.mtl.MTLDevice;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.minecraft.client.renderer.ShaderDefines;
import net.minecraft.resources.Identifier;

import java.lang.foreign.MemorySegment;
import java.util.List;
import java.util.function.Predicate;

/**
 * Everything a Metal 3 session owns while it is the generation that executes the frame: the compilation state
 * its artifacts come from, and the pipelines it has retired but cannot release yet.
 * <p>
 * It exists so the device holds **one** generation-owned object instead of two, which is the package boundary the
 * frame path's move needs: when this and the frame classes go to {@code render.metal3} together, the device keeps
 * a single field and no internal class has to be made public to satisfy it. It is not a service locator - it
 * exposes the operations the device actually performs, and nothing it owns is reachable from outside.
 * <p>
 * It deliberately owns no neutral or session state (no shader source, no selection, no present gate, no layer,
 * no debug options) and knows nothing about Metal 4. The frame encoder is not here either: this round only moves
 * compilation and lifetime ownership.
 */
@Environment(EnvType.CLIENT)
final class Metal3ExecutionState {

    private final Metal3PipelineRetirement retirement = new Metal3PipelineRetirement();
    private final Metal3CompilationContext compilation;

    Metal3ExecutionState(final MTLDevice device) {
        this.compilation = new Metal3CompilationContext(device, this.retirement);
    }

    /** The compiled artifact for this pipeline, compiling it if the cache does not hold it. */
    MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {
        return this.compilation.getOrCompilePipeline(pipeline, source);
    }

    /** The translated shader module for this stage. */
    IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type,
                                                final ShaderDefines defines, final ShaderSource shaderSource) {
        return this.compilation.getOrCompileShader(id, type, defines, shaderSource);
    }

    /** The compiled function for this MSL and entry point. */
    MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        return this.compilation.getOrCompileFunction(msl, entryPoint);
    }

    /** The depth-stencil state for the comparison and write flags. */
    MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
        return this.compilation.depthStencilState(compareFunction, writeDepth);
    }

    /** Removes the pipelines a predicate selects and answers what it removed. */
    List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        return this.compilation.evictCachedPipelines(predicate);
    }

    /**
     * Releases everything this generation may release **once the caller has established GPU completion**.
     * <p>
     * The name says the precondition because it is the whole point: this object cannot know how frames are
     * submitted, so it cannot wait. The caller waits, then calls this, and the order inside is the order the
     * artifacts depend on - retired pipelines first, then the active ones, then the modules and functions they
     * were built from.
     */
    void clearCachesAfterGpuCompletion() {
        this.retirement.releaseRetired();
        this.compilation.clearActivePipelines();
        this.compilation.clearShaderCache();
        this.compilation.clearFunctionCache();
    }

    /** Releases the compilation state itself. The cache paths have already done their part. */
    void close() {
        this.compilation.close();
    }
}
