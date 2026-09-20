package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.render.shared.MetalExecutionState;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.util.List;
import java.util.function.Predicate;

/**
 * The Metal 4 generation's session state: the device it executes on, and the caches a Metal 4 compilation chain
 * will fill.
 * <p>
 * <strong>It owns the device and no cache yet, and it says so where a cache would be.</strong> The neutral
 * state's four operations are asked of it, and three of them are already true answers rather than refusals -
 * nothing is cached, so removing a selection removes nothing, clearing after GPU completion clears nothing, and
 * closing releases nothing. The fourth, {@link #getOrCompilePipeline}, is the one that cannot be answered: the
 * Metal 4 compilation chain does not exist, and a state that answered it with a Metal 3 artifact would be a
 * Metal 4 path silently running Metal 3's pipelines. It refuses by name instead, which is section 35's rule and
 * the same shape the provider's own refusals have.
 * <p>
 * The device is held rather than passed around because the state is per-device by construction: the frame
 * encoder asks it for the device its ring is made on, so there is one place that says which device a Metal 4
 * session is executing on.
 */
@Environment(EnvType.CLIENT)
final class Metal4ExecutionState implements MetalExecutionState {

    private final MTLDevice device;

    Metal4ExecutionState(final MTLDevice device) {
        this.device = device;
    }

    /** The device this state, and the frame encoder made from it, belong to. */
    MTLDevice device() {
        return this.device;
    }

    /**
     * There is no Metal 4 compilation chain yet, so this is the one operation the state cannot answer.
     * <p>
     * It refuses before touching either argument, so the refusal names the operation rather than whatever the
     * caller happened to pass - which is the difference between "this generation cannot compile yet" and "the
     * caller gave me nothing".
     */
    @Override
    public CompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {
        throw new Metal4ExecutionProvider.Unimplemented("getOrCompilePipeline",
                "no Metal 4 compilation chain exists yet, so this state holds no compiled artifact - the frame"
                        + " path it belongs to is still Metal 3's, and a Metal 3 artifact returned here would be"
                        + " a Metal 4 path running Metal 3's pipelines");
    }

    /**
     * Nothing is cached, so a predicate selects nothing.
     * <p>
     * This is a real answer and not a refusal: the frame path asks it when a pack is reloaded, and an empty list
     * is the truth about a cache that was never filled.
     */
    @Override
    public List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        return List.of();
    }

    /** Nothing is cached after GPU completion either, for the same reason and with the same honesty. */
    @Override
    public void clearCachesAfterGpuCompletion() {
    }

    /** Releases nothing: this state has no cache, no queue and no command buffer to give back. */
    @Override
    public void close() {
    }
}
