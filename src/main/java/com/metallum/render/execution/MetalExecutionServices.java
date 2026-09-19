package com.metallum.render.execution;

import com.metallum.mtl.MTLDevice;
import com.metallum.render.shared.MetalFrameEncoder;
import com.metallum.render.shared.MetalFramePresentGate;
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

    /**
     * The gate the frame's encoder asks while it draws a frame: signal before the commit, present after it, and
     * say whether this road takes the picture. It is a contract rather than the present path itself, so the
     * generation that encodes the frame never names the generation that presents it.
     */
    /**
     * The frame's encoder, made here so that the device holds a contract rather than a generation's class.
     * <p>
     * The Metal 3 implementation is still the only one - the selected generation's own frame path is what M4
     * builds - so this answers with the same generation {@link #executing()} names, and the day there is a
     * second implementation is the day this method gains a second answer.
     */
    MetalFrameEncoder createFrameEncoder(com.metallum.render.MetalDevice device);

    /**
     * Starts whatever presenting needs and returns the gate the frame's encoder will ask. Neutral: the device
     * asks for a gate, and only the road that presents knows what starting it means.
     */
    default MetalFramePresentGate startPresentPath(final MTLDevice device) {
        return MetalFramePresentGate.NONE;
    }

    /** Releases what {@link #startPresentPath(MTLDevice)} started. A road that started nothing does nothing. */
    default void closePresentPath() {
    }

    default com.metallum.render.shared.MetalFramePresentGate presentGate() {
        return com.metallum.render.shared.MetalFramePresentGate.NONE;
    }

    /** Whether the selected generation can encode a frame yet. */
    default boolean framePathReady() {
        return !isReferenceShell() && this.selected() == this.executing();
    }

    /**
     * The services as they stand: which generation was selected, and which one really encodes the frame.
     * <p>
     * Both are parameters rather than one parameter and one literal, because the literal was the bug next door:
     * `selected()` was a constant `METAL3` until it was made the selection, and `executing()` was a constant
     * for as long as the answer happened to be Metal 3. A caller that passes the executing generation has to
     * know why it is passing it, and the day a Metal 4 frame path runs, this is the one line that changes.
     */
    static MetalExecutionServices of(final MetalApiGeneration selected, final MetalApiGeneration executing) {
        return new MetalExecutionServices() {
            @Override
            public MetalApiGeneration selected() {
                return selected;
            }

            @Override
            public MetalApiGeneration executing() {
                return executing;
            }

            @Override
            public boolean isReferenceShell() {
                // The selection has no frame path of its own while something else executes for it. It used to be
                // asked as "is the selection not Metal 3", which gave the right answer for the wrong reason: the
                // question is not what was selected but whether the selected generation is the one running.
                return executing != selected;
            }

            @Override
            public MetalFrameEncoder createFrameEncoder(final com.metallum.render.MetalDevice device) {
                return new com.metallum.render.MetalCommandEncoder(device);
            }

            private com.metallum.render.shared.MetalFramePresentGate presentGate =
                    com.metallum.render.shared.MetalFramePresentGate.NONE;

            @Override
            public com.metallum.render.shared.MetalFramePresentGate startPresentPath(final MTLDevice device) {
                // Chosen once, here, from the same policy the encoder used to ask per frame, and kept: which road
                // presents is a property of the session, not of a frame.
                this.presentGate = presentsThroughMetal4()
                        ? com.metallum.render.Metal4PresentGate.start(device)
                        : com.metallum.render.shared.MetalFramePresentGate.NONE;
                return this.presentGate;
            }

            @Override
            public void closePresentPath() {
                if (presentsThroughMetal4()) {
                    com.metallum.render.Metal4PresentGate.close();
                }
            }

            @Override
            public com.metallum.render.shared.MetalFramePresentGate presentGate() {
                return this.presentGate;
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
