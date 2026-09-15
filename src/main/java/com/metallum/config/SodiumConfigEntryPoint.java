package com.metallum.config;

import net.caffeinemc.mods.sodium.api.config.ConfigEntryPoint;
import net.caffeinemc.mods.sodium.api.config.option.OptionFlag;
import net.caffeinemc.mods.sodium.api.config.structure.ConfigBuilder;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;

/**
 * Replaces Sodium's graphics API option through its public Config API.
 */
public final class SodiumConfigEntryPoint implements ConfigEntryPoint {
    private static final Identifier GRAPHICS_API_OPTION =
            Identifier.fromNamespaceAndPath("sodium", "general.graphics_api");

    @Override
    public void registerConfigLate(ConfigBuilder builder) {
        var options = Minecraft.getInstance().options;
        if (options == null) {
            return;
        }

        var replacement = builder.createEnumOption(GRAPHICS_API_OPTION, GraphicsApiPreference.class)
                .setStorageHandler(options::save)
                .setName(Component.translatable("options.graphicsApi"))
                .setTooltip(value -> value == GraphicsApiPreference.VULKAN
                        ? Component.translatable("options.graphicsApi.tooltip.vulkan")
                        : Component.translatable("options.graphicsApi.tooltip"))
                .setElementNameProvider(GraphicsApiPreference::caption)
                .setDefaultValue(GraphicsApiPreference.DEFAULT)
                .setFlags(OptionFlag.REQUIRES_GAME_RESTART)
                .setBinding(
                        value -> MetallumGraphicsOptions.apply(value, options),
                        () -> MetallumGraphicsOptions.current(options)
                );

        builder.registerOwnModOptions()
                .registerOptionReplacement(GRAPHICS_API_OPTION, replacement, 100);
    }
}
