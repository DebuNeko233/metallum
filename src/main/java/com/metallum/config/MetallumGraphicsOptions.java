package com.metallum.config;

import net.minecraft.client.OptionInstance;
import net.minecraft.client.Options;
import net.minecraft.client.PreferredGraphicsApi;
import net.minecraft.network.chat.Component;

import java.util.List;

/**
 * Shared binding used by vanilla and Sodium graphics API selectors.
 */
public final class MetallumGraphicsOptions {
    private MetallumGraphicsOptions() {
    }

    public static GraphicsApiPreference current(Options options) {
        if (GraphicsApiPreferenceStore.isMetalPreferred()) {
            return GraphicsApiPreference.METAL;
        }
        return GraphicsApiPreference.fromVanilla(options.preferredGraphicsBackend().get());
    }

    public static void apply(GraphicsApiPreference preference, Options options) {
        boolean metal = preference == GraphicsApiPreference.METAL;
        GraphicsApiPreferenceStore.setMetalPreferred(metal);
        options.preferredGraphicsBackend().set(preference.vanillaPreference());
    }

    public static OptionInstance<GraphicsApiPreference> createVanillaOption(Options options) {
        return new OptionInstance<>(
                "options.graphicsApi",
                OptionInstance.cachedConstantTooltip(Component.translatable("options.graphicsApi.tooltip")),
                (caption, value) -> Options.genericValueLabel(caption, value.caption()),
                new OptionInstance.Enum<>(List.of(GraphicsApiPreference.values()), GraphicsApiPreference.CODEC),
                current(options),
                value -> apply(value, options)
        );
    }
}
