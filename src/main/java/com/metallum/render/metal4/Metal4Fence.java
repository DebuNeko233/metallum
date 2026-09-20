package com.metallum.render.metal4;

import com.metallum.mtl.metal4.MTL4FrameRing;
import com.mojang.blaze3d.buffers.GpuFence;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * A Metal 4 fence: a promise about one of the frame's submissions, waited for through the ring's shared event.
 * <p>
 * Metal 3's fence is the same object with the same meaning and it is deliberately not an {@code MTLFence}: it
 * holds the encoder and the submit index that was current when it was made, and {@code awaitCompletion} asks the
 * encoder whether that submission has completed. Metal 4 has no fence object to wrap - the new command model
 * orders work with barriers and queue events - and the event the ring already signals per submission is exactly
 * the object the same question is asked of here. So this class is the translation of the <em>meaning</em> and not
 * of the class: a fence made while a frame is open is about that frame's submission, one made between frames is
 * about the work already submitted, and both answer a poll and a wait the way the Metal 3 fence does.
 * <p>
 * Nothing here is static and nothing outlives the ring it was made from: a fence is a value plus the device-owned
 * ring, so a reload or a second session cannot make one session's fence wait on another's event.
 */
@Environment(EnvType.CLIENT)
public final class Metal4Fence implements GpuFence {

    private final MTL4FrameRing ring;
    /** The submission value this fence promises, as the commit of that frame signalled it. */
    private final long submission;
    private boolean closed;

    Metal4Fence(final MTL4FrameRing ring, final long submission) {
        this.ring = ring;
        this.submission = submission;
    }

    /** The submission this fence is about, which is what a test or a log line can name. */
    public long submission() {
        return this.submission;
    }

    @Override
    public void close() {
        this.closed = true;
    }

    @Override
    public boolean awaitCompletion(final long timeoutNS) {
        // Closed first, and the same answer Metal 3's fence gives: a fence its owner has let go is not a reason
        // to wait for anything.
        if (this.closed) {
            return true;
        }
        return this.ring.awaitSubmission(this.submission, timeoutNS / 1_000_000L);
    }
}
