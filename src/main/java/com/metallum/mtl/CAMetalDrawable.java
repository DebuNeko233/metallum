package com.metallum.mtl;

import com.metallum.objc.Msg;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;

@Environment(EnvType.CLIENT)
public record CAMetalDrawable(MemorySegment handle) {
    private static final Msg TEXTURE = Msg.of("texture", ADDRESS);
    private static final Msg PRESENT = Msg.ofVoid("present");

    /**
     * Schedules this drawable's presentation.
     * <p>
     * The frame's own road presents through the command buffer that drew it; a frame presented by another
     * queue has no such command buffer to hang the presentation on, so the drawable is told directly, after
     * the queue has been told to signal it.
     */
    public void present() {
        PRESENT.send(handle());
    }

    public MemorySegment texture() {
        return TEXTURE.sendPtr(handle);
    }
}
