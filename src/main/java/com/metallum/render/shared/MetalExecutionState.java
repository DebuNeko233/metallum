package com.metallum.render.shared;

import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.util.List;
import java.util.function.Predicate;

/**
 * What the device may ask the generation that owns a session's execution state: four operations and nothing else.
 * <p>
 * It exists so the frame path can move to its own package without the device reaching into it. The device used to
 * call nine members of the generation-owned aggregate, which is exactly nine members that would have to be made
 * public at the package boundary; this contract is the boundary instead, and the operations left out of it -
 * shader and function lookup, depth-stencil states - stay where they belong, with the generation.
 * <p>
 * It therefore names no generation and no native type: no Metal 3 or Metal 4 class, no command queue, no frame
 * encoder, no present gate, no {@code MTL} type, no {@code MemorySegment}, no compiled-artifact implementation.
 * A contract in {@code tools/ci-contracts.py} reads the file and fails if any of those appear.
 */
@Environment(EnvType.CLIENT)
public interface MetalExecutionState extends AutoCloseable {

    /** The compiled artifact for this pipeline, compiling it if the state does not already hold it. */
    CompiledRenderPipeline getOrCompilePipeline(RenderPipeline pipeline, ShaderSource source);

    /** Removes the pipelines a predicate selects and answers what it removed. */
    List<RenderPipeline> evictCachedPipelines(Predicate<RenderPipeline> predicate);

    /**
     * Releases generation-owned cache and lifetime state.
     * <p>
     * The caller must already have established GPU completion: a state cannot know how frames are submitted, so
     * it cannot wait, and a method that waited would have taken over the execution lifecycle.
     */
    void clearCachesAfterGpuCompletion();

    /** Releases the state itself. The cache paths have already done their part. */
    @Override
    void close();
}
