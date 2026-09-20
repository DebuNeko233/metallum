package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
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
 * <strong>What it does not do is execute a frame, and it says so rather than half-doing it.</strong> A queue is
 * made for real, because the probe has made one on this device many times and the queue is the provider's own
 * object. The execution state and the frame encoder do not exist, so each raises {@link Unimplemented} naming
 * its stage: section 35 of the migration plan forbids an unknown operation being silently dropped, and a
 * provider that returned a null state would move the failure twenty calls later into whatever tried to use it.
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
        throw new Unimplemented("createExecutionState",
                "no Metal 4 execution state exists yet, so the frame path is still Metal 3's");
    }

    @Override
    public MetalFrameEncoder createFrameEncoder(final MetalDevice device, final MetalExecutionState executionState,
                                                final ShaderSource defaultShaderSource) {
        throw new Unimplemented("createFrameEncoder",
                "no Metal 4 frame encoder exists yet, so the frame path is still Metal 3's");
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
