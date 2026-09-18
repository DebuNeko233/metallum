package com.metallum.config;

import com.mojang.serialization.Codec;
import net.minecraft.client.PreferredGraphicsApi;
import net.minecraft.network.chat.Component;

import java.util.Locale;

public enum GraphicsApiPreference {
    DEFAULT,
    OPENGL,
    VULKAN,
    METAL;

    public static final Codec<GraphicsApiPreference> CODEC = Codec.STRING.xmap(
            GraphicsApiPreference::fromSerializedName,
            GraphicsApiPreference::serializedName
    );

    public Component caption() {
        return switch (this) {
            case DEFAULT -> Component.translatable("options.graphicsApi.default");
            case OPENGL -> Component.translatable("options.graphicsApi.opengl");
            case VULKAN -> Component.translatable("options.graphicsApi.vulkan");
            case METAL -> Component.literal("Prefer Metal");
        };
    }

    public PreferredGraphicsApi vanillaPreference() {
        return switch (this) {
            case OPENGL -> PreferredGraphicsApi.OPENGL;
            case VULKAN -> PreferredGraphicsApi.VULKAN;
            case DEFAULT, METAL -> PreferredGraphicsApi.DEFAULT;
        };
    }

    public static GraphicsApiPreference fromVanilla(PreferredGraphicsApi preference) {
        return switch (preference) {
            case OPENGL -> OPENGL;
            case VULKAN -> VULKAN;
            case DEFAULT -> DEFAULT;
        };
    }

    private String serializedName() {
        return name().toLowerCase(Locale.ROOT);
    }

    private static GraphicsApiPreference fromSerializedName(String value) {
        try {
            return valueOf(value.toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            return DEFAULT;
        }
    }
}
