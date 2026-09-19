package com.metallum.render.shared;

import com.metallum.mtl.CAMetalLayer;
import java.lang.foreign.MemorySegment;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The three points in a frame where the road that presents has to be asked something, expressed without naming
 * any road.
 * <p>
 * A frame signals an event before its commit, presents after it, and - before any of that - the picture's owner
 * says whether it is taking the picture itself. Metal 3 answers the first two with nothing and the third with
 * "no, I present by blit"; the Metal 4 present path answers them with its own event, its own present and a yes.
 * The Metal 3 encoder used to ask that path directly, which made a Metal 3 implementation depend on a Metal 4
 * one; it asks this instead, and the services hand it whichever road is configured.
 */
@Environment(EnvType.CLIENT)
public interface MetalFramePresentGate {

    /** The gate for a session whose frame presents itself: every answer is the do-nothing one. */
    MetalFramePresentGate NONE = new MetalFramePresentGate() {
        @Override
        public void beforeCommit(final MemorySegment frameCommandBuffer) {
        }

        @Override
        public void afterCommit() {
        }

        @Override
        public boolean takesPicture(final CAMetalLayer layer, final MemorySegment picture) {
            return false;
        }
    };

    /** Before the frame's commit, with the frame's command buffer as the native handle no generation owns. */
    void beforeCommit(final MemorySegment frameCommandBuffer);

    /** After the frame's commit, once the work it ordered is on its way. */
    void afterCommit();

    /** Whether this gate takes the picture itself, recording it for its present if it does. */
    boolean takesPicture(final CAMetalLayer layer, final MemorySegment picture);
}
