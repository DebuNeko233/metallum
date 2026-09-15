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
}
