package com.metallum.render;

import com.metallum.mtl.CAMetalLayer;
import java.lang.foreign.MemorySegment;
import com.metallum.render.shared.MetalFramePresentGate;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The present-only Metal 4 road, expressed as the frame's gate.
 * <p>
 * This is the one file outside the Metal 4 path that names it, and it exists so that no Metal 3 implementation
 * has to: the encoder asks the gate, the services choose the gate, and this is the adapter. It is also where
 * that road's readiness and policy are consulted, so the encoder cannot reach either by accident.
 */
@Environment(EnvType.CLIENT)
public final class Metal4PresentGate implements MetalFramePresentGate {

    /** Starts the road, if the device can carry it, and answers the gate for it. */
    public static MetalFramePresentGate start(final com.metallum.mtl.MTLDevice device) {
        return Metal4Path.start(device)
                ? new Metal4PresentGate()
                : MetalFramePresentGate.NONE;
    }

    /** Releases the road. Called once, by the services, when the device closes. */
    public static void close() {
        Metal4Path.close();
    }

    @Override
    public void beforeCommit(final MemorySegment frameCommandBuffer) {
        Metal4Path.frameSignal(frameCommandBuffer);
    }

    @Override
    public void afterCommit() {
        Metal4Path.presentFrame();
    }

    @Override
    public boolean takesPicture(final CAMetalLayer layer, final MemorySegment picture) {
        return Metal4Path.presenting(layer, picture);
    }
}
