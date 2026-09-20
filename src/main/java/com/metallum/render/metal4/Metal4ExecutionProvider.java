package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4FrameRing;
import com.metallum.objc.Msg;
import com.metallum.render.MetalDevice;
import com.metallum.render.execution.MetalExecutionProvider;
import com.metallum.render.shared.MetalExecutionState;
import com.metallum.render.shared.MetalFrameEncoder;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.ValueLayout;

/**
 * The Metal 4 execution provider: the generation owns its queue, its state and its frame encoder, as the Metal 3
 * one does - and only the first of the three exists yet.
 * <p>
 * <strong>This is the skeleton Phase 2 asks for and nothing more.</strong> Metal 4 has been a present sidecar:
 * a queue, a command buffer and a present triangle, chosen by {@code -Dmetallum.metal4Present} and never the
 * frame's own road. What was missing is the generation-specific object ownership the Metal 3 path has had for a
 * while, and that is what this class gives it - a provider the services can hand out for the executing
 * generation, with the same neutral signatures and no generation type in any of them.
 * <p>
 * <strong>All three of its objects now exist, and the refusals have moved inside them.</strong> A queue is made
 * for real; the execution state owns the device and refuses the one operation it cannot answer - compiling a
 * Metal 4 pipeline - by name; and the frame encoder owns the frame's allocator ring and the resources a frame
 * cannot release yet, refusing each operation the new path does not encode. Section 35 of the migration plan
 * forbids an unknown operation being silently dropped, and a provider that returned a null object would move the
 * failure twenty calls later into whatever tried to use it: the refusals are one level deeper, and each still
 * names what it refused. The only refusal left here is a ring the device will not make, which is a device answer
 * rather than a gap in the implementation.
 * <p>
 * <strong>And it cannot be reached by accident.</strong> The services hand out the provider of the generation
 * that is <em>executing</em>, and the device states that generation as Metal 3 until a Metal 4 frame path is
 * ready - so selecting Metal 4 today still executes Metal 3, with {@code referenceShell} true, exactly as
 * section 19 requires. Nothing here changes which road a frame takes; it changes which object would own it.
 */
@Environment(EnvType.CLIENT)
public final class Metal4ExecutionProvider implements MetalExecutionProvider {

    /**
     * {@code newMTL4CommandQueue}, the entry point the SDK's {@code MTLDevice.h} declares and the one the
     * capability probe already asks for with {@code respondsToSelector:} before anything sends it.
     */
    private static final Msg NEW_COMMAND_QUEUE = Msg.of("newMTL4CommandQueue", ValueLayout.ADDRESS);

    @Override
    public long commandQueue(final MTLDevice device) {
        long queue = NEW_COMMAND_QUEUE.sendPtr(device.handle()).address();
        if (queue == 0L) {
            // Named rather than returned as nought: a queue that is not there is the difference between "this
            // device cannot" and "this device was never asked", and only one of those is the device's fault.
            throw new Unimplemented("commandQueue", "newMTL4CommandQueue answered nil on this device");
        }

        return queue;
    }

    @Override
    public MetalExecutionState createExecutionState(final MTLDevice device) {
        // A real object now, and an honest one: it owns the device this generation executes on and refuses the
        // one operation it cannot answer - compiling a Metal 4 pipeline - by name, rather than returning a state
        // whose first use would fail somewhere else.
        return new Metal4ExecutionState(device);
    }

    @Override
    public MetalFrameEncoder createFrameEncoder(final MetalDevice device, final MetalExecutionState executionState,
                                                final ShaderSource defaultShaderSource) {
        if (!(executionState instanceof Metal4ExecutionState metal4)) {
            throw new IllegalArgumentException("Metal 4 frame encoder requires Metal4ExecutionState");
        }

        try {
            return new Metal4FrameEncoder(device, metal4, defaultShaderSource);
        } catch (MTL4FrameRing.Refused refused) {
            // The ring is the frame's lifetime and cannot be made without its allocators, its command buffer and
            // its event - so a device that will not give them is a device this path cannot run on, and the
            // refusal names the object that came back nil rather than leaving a half-made encoder behind.
            throw new Unimplemented("createFrameEncoder", "the frame's ring could not be made at stage "
                    + refused.stage() + ": " + refused.getMessage());
        }
    }

    /**
     * Raised where a Metal 4 execution entry point exists and its implementation does not.
     * <p>
     * It carries the stage, so a reader of a log knows which half of the provider was asked for - the same
     * discipline the capability probe's {@code lastFailureStage()} follows, and for the same reason: a failure
     * that says only "not implemented" cannot be told from a build where the whole provider is missing.
     */
    public static final class Unimplemented extends UnsupportedOperationException {

        private final String stage;

        Unimplemented(final String stage, final String reason) {
            super(stage + ": " + reason);
            this.stage = stage;
        }

        /** Which entry point refused, as the probe's stage names are spelled. */
        public String stage() {
            return this.stage;
        }
    }
}
