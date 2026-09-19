package com.metallum.render.shared;

import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.systems.CommandEncoderBackend;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.nio.ByteBuffer;

/**
 * The frame's encoder as the device and the public bridges know it: the game's own {@code CommandEncoderBackend}
 * contract, plus the four operations the frame path's owner performs on it.
 * <p>
 * It exists so that the thing holding the frame's encoder does not have to name which generation encodes it.
 * The type is deliberately as wide as the game's interface and no wider: everything a pass or a bridge needs
 * beyond it is already a separate, narrower contract - {@link MetalFrameExtras}, {@link MetalFramePresentation},
 * {@link MetalPassUniformWriter} - and the four members here are the ones the device itself calls while it owns
 * the frame's lifetime.
 * <p>
 * <strong>No generation type may appear in this interface.</strong> Not a command buffer, not a render, compute
 * or blit encoder, not a Metal 4 queue or command buffer, not the present path's scaffolding: a signature that
 * named one would make the neutral layer the place the isolation is undone, which is what the layer rules in
 * {@code tools/ci-architecture.py} fail on.
 */
@Environment(EnvType.CLIENT)
public interface MetalFrameEncoder extends CommandEncoderBackend {

    /** Writes bytes into a slice of GPU-visible memory, waiting for room if the queue is full. */
    void writeToBuffer(final GpuBufferSlice destination, final ByteBuffer data);

    /** Releases what this encoder owns. Called once, by the device that made it. */
    void close();

    /** Blocks until the work submitted so far has completed, for the paths that must not race a teardown. */
    void waitForSubmittedGpuWork();

    /** Retires an already-encoded resource on the same rotation the encoder's own destructions use. */
    void queueForDestroy(final Runnable destroyAction);
}
