package com.metallum.render.execution;

import com.metallum.mtl.MTLDevice;
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

    /**
     * The Metal 3 queue factory, for the reference shell below: the shell is the seam until the generation
     * packages own their own services, and it must not import a Metal 3 wrapper to do its job.
     */
    com.metallum.objc.Msg MTL3_QUEUE = com.metallum.objc.Msg.of("newCommandQueue",
            java.lang.foreign.ValueLayout.ADDRESS);

    /** The generation this session was selected to execute. */
    MetalApiGeneration selected();

    /** The generation that is really encoding the frame today. */
    MetalApiGeneration executing();

    /** Whether {@link #executing()} is the selected generation's own path, or a provisional stand-in. */
    boolean isReferenceShell();

    /**
     * The command queue this generation submits on, as the native handle a command encoder takes.
     * <p>
     * This is the seam the frame path's isolation turns on: the device used to make its own Metal 3 queue,
     * which is the one thing that made "the device belongs to shared and the generation belongs to its own
     * package" impossible to write down. The handle is a plain foreign address rather than a wrapper class,
     * because a wrapper would put a generation's type in a version-neutral interface.
     */
    long commandQueue(MTLDevice device);

    /**
     * Whether a frame that is ready to present through the Metal 4 path should.
     * <p>
     * This is the **policy** half of the present decision and only that half. Readiness - a queue, a command
     * buffer, a frame event with a value, an argument table and the selectors the present consults - stays
     * with the present path, which is the only thing that knows whether its objects exist. The two were
     * conjoined in one condition inside the present path itself, which put a policy about generations in a
     * place that builds them.
     * <p>
     * Today the policy is read from {@code -Dmetallum.metal4Present} here and nowhere else, because the
     * present-only Metal 4 path is still a probe rather than the frame's road: the property is the interlock,
     * and this method is where it lives so that removing it is one edit in one file. It deliberately does
     * **not** yet consult {@link #selected()}: that would silently change which road a forced-Metal-3 session
     * presents through, and the change that ties the policy to the selection is the one that makes the Metal 4
     * frame path the frame's own road.
     */
    default boolean presentsThroughMetal4() {
        return false;
    }

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

            @Override
            public boolean presentsThroughMetal4() {
                return Boolean.parseBoolean(System.getProperty("metallum.metal4Present", "false"));
            }

            @Override
            public long commandQueue(final MTLDevice device) {
                // The reference shell submits on the generation that executes, which is Metal 3 until the new
                // path has a frame of its own - the same answer `executing()` gives, so the two cannot drift.
                return MTL3_QUEUE.sendPtr(device.handle()).address();
            }
        };
    }
}
