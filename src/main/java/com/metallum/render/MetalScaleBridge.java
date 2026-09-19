package com.metallum.render;

import com.metallum.render.shared.MetalFrameExtras;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The public door to the encoder's MetalFX capability.
 *
 * <p>
 * The pack-facing side reaches this backend by reflection and without a compile-time dependency, and
 * reflection into a package-private class fails however public the method on it is. The other
 * capabilities already answer this the same way - one public class per capability, holding nothing but
 * static methods that take the caller's object as an argument - and this is the one for scaling, so that
 * asking for it never depends on where the encoder happens to live.
 */
@Environment(EnvType.CLIENT)
public final class MetalScaleBridge {

    private MetalScaleBridge() {
    }

    /** @see MetalFrameExtras#metalFxAvailable() */
    public static boolean available(final Object encoder) {
        return encoder instanceof MetalFrameExtras frameEncoder && frameEncoder.metalFxAvailable();
    }

    /** @see MetalFrameExtras#scaleWithMetalFx(GpuTextureView, GpuTextureView, int, int) */
    public static boolean scale(
            final Object encoder,
            final GpuTextureView from,
            final GpuTextureView to,
            final int contentWidth,
            final int contentHeight
    ) {
        return encoder instanceof MetalFrameExtras frameEncoder
                && frameEncoder.scaleWithMetalFx(from, to, contentWidth, contentHeight);
    }
}
