package com.metallum.api;

import com.metallum.config.GraphicsApiPreferenceStore;
import com.metallum.render.Metal4;

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
     * Returns whether the device this session came up on has the Metal 4 core API.
     * <p>
     * For an integration that may one day take the Metal 4 path through a capability of its own, the way
     * it takes background precompilation today. The answer is the device's own - {@code supportsFamily:}
     * with {@code MTLGPUFamilyMetal4} and the Metal 4 entry point, both asked once when the device was
     * created - and it is remembered, the negative answer included, because a session cannot change its
     * GPU. False before a device has been created, and false on a device that does not have it.
     * <p>
     * Nothing in this engine renders through Metal 4 yet: this reports what the hardware offers and
     * promises nothing about what the backend does with it.
     */
    public static boolean supportsMetal4CoreApi() {
        return Metal4.isAvailable();
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
