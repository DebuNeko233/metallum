package com.metallum.render;

import com.metallum.render.metal3.Metal3DepthMipmapBridge;
import com.mojang.blaze3d.textures.GpuTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The depth-mipmap entry point an optional client calls, delegating to the Metal 3 implementation.
 * <p>
 * The mip chain is encoded with the generation's own render encoder internals, which stay package-private in
 * {@code render.metal3}; this class keeps the name and the signature callers already use.
 */
@Environment(EnvType.CLIENT)
public final class MetalDepthMipmapBridge {

    private MetalDepthMipmapBridge() {
    }

    /** Builds the depth mip chain for a D32 texture, answering whether it was encoded. */
    public static boolean generate(final Object encoderBackend, final GpuTexture texture) {
        return Metal3DepthMipmapBridge.generate(encoderBackend, texture);
    }
}
