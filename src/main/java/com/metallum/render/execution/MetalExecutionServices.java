package com.metallum.render.execution;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * What the frame asks for when it needs a command path, so that the choice of generation is one seam and not
 * a question asked in fifty places.
 * <p>
 * <strong>This is the milestone's skeleton and not the architecture's final shape.</strong> The selector can
 * already answer "which generation", and on a device that satisfies the Metal 4 contract the answer is
 * Metal 4 - while the frame is still encoded through Metal 3's command buffer, because moving it is later
 * work. So the services say both things and never one without the other: {@link #executing()} is what is
 * really running, and {@link #isReferenceShell()} is true while the selected generation has no frame path of
 * its own yet. A caller that needs a frame path asks {@link #framePathReady()} and gets a truthful no rather
 * than a path that pretends.
 */
@Environment(EnvType.CLIENT)
public interface MetalExecutionServices {

    /** The generation this session was selected to execute. */
    MetalApiGeneration selected();

    /** The generation that is really encoding the frame today. */
    MetalApiGeneration executing();

    /** Whether {@link #executing()} is the selected generation's own path, or a provisional stand-in. */
    boolean isReferenceShell();

    /** Whether the selected generation can encode a frame yet. */
    default boolean framePathReady() {
        return !isReferenceShell() && this.selected() == this.executing();
    }

    /**
     * The services as they stand: the selected generation from the selector, and Metal 3 encoding the frame
     * until the new path has one of its own.
     */
    static MetalExecutionServices of(final MetalApiGeneration selected) {
        return new MetalExecutionServices() {
            @Override
            public MetalApiGeneration selected() {
                return selected;
            }

            @Override
            public MetalApiGeneration executing() {
                return MetalApiGeneration.METAL3;
            }

            @Override
            public boolean isReferenceShell() {
                return selected != MetalApiGeneration.METAL3;
            }
        };
    }
}
