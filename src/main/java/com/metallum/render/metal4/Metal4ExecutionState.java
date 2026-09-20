package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.objc.ObjC;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.MetalComputeCompiler;
import com.metallum.render.shared.MetalComputeTranslator;
import com.metallum.render.shared.MetalExecutionState;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.Objects;
import java.util.function.Predicate;

/**
 * The Metal 4 generation's session state: the device it executes on, and the caches a Metal 4 compilation chain
 * will fill.
 * <p>
 * <strong>It owns the device and this generation's compilation state</strong>: the SPIR-V module cache, the
 * native function cache, the depth-stencil cache and the compiled-artifact cache, all of which the neutral
 * state's four operations are answered from. Nothing here is Metal 3's: the artifacts come from
 * {@code Metal4PipelineCompiler}, which asks the shared translator for direct bindings rather than argument
 * buffers and builds its own native pipeline states - so a Metal 4 session compiles Metal 4 pipelines rather
 * than being handed the reference generation's.
 * <p>
 * <strong>It answers the neutral compute compile as well</strong>, because that is the same question asked
 * about a kernel: a shared translation, a native function for the MSL, and a native pipeline state - and the
 * state a dispatch runs is kept by the same context that keeps the function it was made from.
 * <p>
 * The device is held rather than passed around because the state is per-device by construction: the frame
 * encoder asks it for the device its ring is made on, so there is one place that says which device a Metal 4
 * session is executing on. That is also why {@link #compileCompute} compiles against the device this state
 * owns rather than the facade it was handed: the facade is how the caller reached this state, and this state
 * is the thing that knows which device its session is on.
 */
@Environment(EnvType.CLIENT)
final class Metal4ExecutionState implements MetalExecutionState, MetalComputeCompiler {

    private final MTLDevice device;
    private final Metal4CompilationContext compilation;

    Metal4ExecutionState(final MTLDevice device) {
        this.device = device;
        this.compilation = new Metal4CompilationContext(device);
    }

    /** The device this state, and the frame encoder made from it, belong to. */
    MTLDevice device() {
        return this.device;
    }

    /**
     * The compiled artifact for this pipeline, through this generation's own chain: the game's GLSL compiler, the
     * shared SPIR-V-to-MSL translator, and this generation's native pipeline construction. Nothing Metal 3's is
     * reached, which is what makes the artifact a Metal 4 one rather than a Metal 3 artifact wearing a different
     * owner's name.
     */
    @Override
    public CompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {
        return this.compilation.getOrCompilePipeline(pipeline, source);
    }

    /**
     * Compiles one compute kernel: the shared translation, this generation's function for the MSL it emits,
     * and this generation's native compute pipeline state.
     * <p>
     * The translation is not duplicated here - SPIR-V in and MSL plus remapped bindings out is
     * {@link MetalComputeTranslator}'s on both generations - and neither is the function cache: the compilation
     * context already keys a native function by (MSL, entry point, profile), and a compute pipeline state is
     * keyed by exactly that, so the two caches are one shape and the state is shared by every handle to the
     * same kernel.
     * <p>
     * The label is the caller's and it is what a failure names, because the caller is the one that knows which
     * pack shader this is.
     *
     * @param device the device facade the caller holds, which is how it reached this state
     */
    @Override
    public Object compileCompute(final MetalDevice device, final String label, final ByteBuffer spirv) {
        Objects.requireNonNull(label, "label");
        Objects.requireNonNull(spirv, "spirv");

        MetalComputeTranslator.Translated translated = MetalComputeTranslator.translate(spirv);
        MemorySegment pipelineState = this.compilation.getOrCompileComputePipeline(
                translated.msl(), translated.entryPoint());
        if (ObjC.isNil(pipelineState)) {
            throw new IllegalStateException("Failed to create Metal compute pipeline for " + label);
        }
        return new Metal4ComputePipeline(label, translated.entryPoint(), pipelineState, translated.bindings());
    }

    /**
     * Nothing is cached, so a predicate selects nothing.
     * <p>
     * This is a real answer and not a refusal: the frame path asks it when a pack is reloaded, and an empty list
     * is the truth about a cache that was never filled.
     */
    @Override
    public List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        return this.compilation.evictCachedPipelines(predicate);
    }

    /**
     * Releases what the caches hold, once the caller has established GPU completion.
     * <p>
     * The precondition is the contract's, and it is the reason the retired artifacts can be released here at
     * all: an artifact that was evicted while work naming it was still in flight is exactly what this cannot
     * release on its own.
     */
    @Override
    public void clearCachesAfterGpuCompletion() {
        this.compilation.clearCachesAfterGpuCompletion();
    }

    /** Releases the compilation state: the artifacts, the functions, the modules and the depth-stencil states. */
    @Override
    public void close() {
        this.compilation.close();
    }
}
