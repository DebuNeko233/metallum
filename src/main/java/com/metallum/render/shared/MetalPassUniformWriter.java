package com.metallum.render.shared;

import com.mojang.blaze3d.buffers.GpuBufferSlice;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.NonNull;

/**
 * What a producer of push constants needs from the pass it is drawing into: somewhere to write them, and a
 * way to bind what it wrote.
 * <p>
 * This is a contract rather than a class for the same reason {@link MetalFrameExtras} is: the caller asks the
 * backend a question, and the question is the whole of the dependency. The sodium draw path reaches its pass
 * through the game's own {@code RenderPass}, so naming the pass's class from the outside is what the split is
 * trying to remove - and the two members here are exactly what that path uses, read off the call site rather
 * than guessed.
 */
@Environment(EnvType.CLIENT)
public interface MetalPassUniformWriter {

    /** A mapped slice of transient memory, alive for the caller's try-with-resources and freed by it. */
    GpuBufferSlice.MappedView allocateTransient(final long size, final long alignment, final int usage);

    /** Binds that slice under a name the shader knows. */
    void setUniform(final @NonNull String name, final @NonNull GpuBufferSlice value);
}
