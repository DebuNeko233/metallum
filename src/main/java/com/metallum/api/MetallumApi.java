package com.metallum.api;

import com.metallum.config.GraphicsApiPreferenceStore;

/**
 * Narrow compatibility surface for optional integrations such as shader mods.
 */
public final class MetallumApi {
    /**
     * Increment only when this public integration contract changes incompatibly.
     */
    public static final int API_VERSION = 1;

    private MetallumApi() {
    }

    public static int apiVersion() {
        return API_VERSION;
    }

    /**
     * Returns whether the user explicitly selected Metallum's "Prefer Metal" graphics API preference.
     * This is a preference signal only; it does not imply that a Metal device was successfully created.
     */
    public static boolean isMetalPreferred() {
        return GraphicsApiPreferenceStore.isMetalPreferred();
    }

    /**
     * Returns whether this Metallum build guarantees that {@code GpuDevice.precompilePipeline}
     * may be called from a background worker while rendering continues on the render thread.
     * <p>
     * The guarantee is deliberately narrow: it covers render-pipeline compilation and the caches
     * that compilation owns. It does not make command encoding or arbitrary device operations
     * thread-safe. Optional shader integrations can use this signal to move first-use pipeline
     * compilation off the render thread without depending on Metallum implementation classes.
     */
    public static boolean supportsBackgroundPipelinePrecompile() {
        return true;
    }
}
