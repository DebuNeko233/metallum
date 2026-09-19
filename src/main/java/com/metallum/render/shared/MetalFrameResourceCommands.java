package com.metallum.render.shared;

import com.mojang.blaze3d.textures.GpuTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The resource operations a frame's encoder can perform, as generation-neutral vocabulary.
 * <p>
 * These three were reachable only by naming the Metal 3 encoder's class from outside its package, which is what
 * the mixin on the pack side used to do - and what broke silently when that class moved. Naming the operation
 * instead of the implementation is the difference: a caller asks "can you mipmap this texture", and whichever
 * generation is executing answers.
 */
@Environment(EnvType.CLIENT)
public interface MetalFrameResourceCommands {

    /** Generates the mip chain for a texture, answering whether this path did it. */
    boolean generateMipmaps(GpuTexture texture);

    /** Clears a storage texture, answering whether it was cleared. */
    boolean clearStorageTexture(GpuTexture texture, int dimensions);

    /** Copies a region between storage textures, answering whether it was copied. */
    boolean copyStorageTextureRegion(
            GpuTexture source,
            GpuTexture destination,
            int sourceX,
            int sourceY,
            int sourceZ,
            int destinationX,
            int destinationY,
            int destinationZ,
            int width,
            int height,
            int depth
    );
}
