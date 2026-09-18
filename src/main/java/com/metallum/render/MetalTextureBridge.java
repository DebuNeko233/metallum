package com.metallum.render;

import com.mojang.blaze3d.GpuFormat;
import com.mojang.blaze3d.textures.GpuTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Optional-backend bridge for ordinary Minecraft textures that also need shader-write access.
 * <p>
 * Minecraft 26.2 exposes no storage-image bit in {@link GpuTexture}'s public usage mask. Optional
 * clients can therefore request exactly that missing allocation fact here while keeping the result
 * inside the normal Minecraft texture facade. Shader-pack naming, target selection, ping-pong
 * policy and dispatch timing remain outside Metallum.
 */
@Environment(EnvType.CLIENT)
public final class MetalTextureBridge {
    private MetalTextureBridge() {
    }

    /**
     * Creates an otherwise ordinary Metal texture with {@code MTLTextureUsageShaderWrite} added.
     *
     * @param backend a Metallum {@code MetalDevice}, typed as {@link Object} for optional clients
     */
    public static GpuTexture createShaderWritable(
            final Object backend,
            final String label,
            @GpuTexture.Usage final int usage,
            final GpuFormat format,
            final int width,
            final int height,
            final int depthOrLayers,
            final int mipLevels
    ) {
        if (!(backend instanceof MetalDevice device)) {
            throw new IllegalArgumentException("Not a Metallum MetalDevice backend: " + backend);
        }
        return new MetalGpuTexture(
                device,
                usage,
                label == null ? "" : label,
                format,
                width,
                height,
                depthOrLayers,
                mipLevels,
                null,
                true
        );
    }
}
