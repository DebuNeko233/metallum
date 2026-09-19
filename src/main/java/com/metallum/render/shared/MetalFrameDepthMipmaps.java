package com.metallum.render.shared;

import com.mojang.blaze3d.textures.GpuTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The depth-mip chain a frame's encoder can build when the generic mipmap path will not take a D32 texture.
 * <p>
 * It is a separate capability from {@link MetalFrameResourceCommands} because it is a different promise: one says
 * "I can mipmap", this one says "I can mipmap a depth texture, by the progressive nearest fallback". A pack that
 * needs the second must ask for the second.
 */
@Environment(EnvType.CLIENT)
public interface MetalFrameDepthMipmaps {

    /** Builds the depth mip chain for a D32 texture, answering whether it was built. */
    boolean generateDepthMipmaps(GpuTexture texture);
}
