package com.metallum.render.shared;

import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

/**
 * What the engine asks the frame's encoder for beyond {@code CommandEncoderBackend}: the two answers a pass
 * has to hand the next one, and the scaler.
 * <p>
 * These four methods are the whole of what a bridge outside the encoder's own package reaches for today, and
 * they are here rather than on the encoder because of what an {@code instanceof} check means: the bridges ask
 * "are you this frame's encoder, and if so do this", and the only thing that has to be true for that question
 * is that the answer is a contract rather than a class. Naming the class from the neutral layer is what the
 * layer rules exist to stop, and it is also what the three attempts to move the frame path ran into - every
 * member a caller outside the package needed had to be opened by hand, one "not public" error at a time.
 * <p>
 * <strong>What is deliberately not here.</strong> {@code MTLComputeCommandEncoder}, {@code MTLBlitCommandEncoder}
 * and {@code MTLRenderCommandEncoder} are a generation's encoders, so no neutral interface can hand them out -
 * and the two bridges that drive them ({@code MetalComputeBridge}, {@code MetalDepthMipmapBridge}) encode
 * compute and render passes rather than asking questions, which makes them Metal 3's own code. They move to
 * {@code render.metal3} with the encoder and get a Metal 4 sibling; putting their encoders behind an
 * interface here would be the split undone in the name of the split.
 */
@Environment(EnvType.CLIENT)
public interface MetalFrameExtras {

    /** The load and store answers the next pass will be created with, or null to let the encoder default them. */
    void setNextPassContents(final @Nullable AttachmentContents[] contents);

    /** Whether the next pass reads the storage image it is also attached as, which decides its layout. */
    void setNextPassReadsStorageImage(final boolean reads);

    /** Whether this frame's encoder can scale, which is a property of the device rather than of the call. */
    boolean metalFxAvailable();

    /** Scales a drawn picture into the window's size, answering whether it did. */
    boolean scaleWithMetalFx(
            final @Nullable GpuTextureView from,
            final GpuTextureView to,
            final int contentWidth,
            final int contentHeight
    );
}
