package com.metallum.render;

import com.metallum.render.shared.MetalFrameResourceCommands;
import com.mojang.blaze3d.textures.GpuTexture;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

/**
 * The stable frame-resource surface an optional client addresses: does this encoder support the operations, and
 * if so, do them.
 * <p>
 * It is the flat counterpart of {@code MetalFrameResourceCommands}, and it exists so that no client has to name
 * the class that implements them. Every parameter is {@code Object} or a Minecraft type, it names no generation
 * package, and a generation that cannot do the work answers {@code false} rather than being reached for.
 */
@Environment(EnvType.CLIENT)
public final class MetalFrameBridge {

    private MetalFrameBridge() {
    }

    /** Whether this encoder can be asked for frame-resource operations at all. */
    public static boolean supports(final @Nullable Object encoder) {
        return encoder instanceof MetalFrameResourceCommands;
    }

    /** Generates the mip chain, answering whether the encoder did it. */
    public static boolean generateMipmaps(final @Nullable Object encoder, final GpuTexture texture) {
        return encoder instanceof MetalFrameResourceCommands commands && commands.generateMipmaps(texture);
    }

    /** Clears a storage texture, answering whether the encoder did it. */
    public static boolean clearStorageTexture(final @Nullable Object encoder, final GpuTexture texture,
                                              final int dimensions) {
        return encoder instanceof MetalFrameResourceCommands commands
                && commands.clearStorageTexture(texture, dimensions);
    }

    /** Copies a storage-texture region, answering whether the encoder did it. */
    public static boolean copyStorageTextureRegion(
            final @Nullable Object encoder,
            final GpuTexture source,
            final GpuTexture destination,
            final int sourceX,
            final int sourceY,
            final int sourceZ,
            final int destinationX,
            final int destinationY,
            final int destinationZ,
            final int width,
            final int height,
            final int depth
    ) {
        return encoder instanceof MetalFrameResourceCommands commands
                && commands.copyStorageTextureRegion(source, destination, sourceX, sourceY, sourceZ,
                        destinationX, destinationY, destinationZ, width, height, depth);
    }
}
