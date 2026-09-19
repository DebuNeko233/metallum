package com.metallum.render.metal3;

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
 * The Metal 3 execution provider: the generation owns its queue factory, its state and its frame encoder, and
 * the services only pick it.
 * <p>
 * The queue selector lives here rather than on the neutral interface, which is the point of the split - the
 * service no longer contains a Metal 3 selector, and a Metal 4 provider would own its own.
 */
@Environment(EnvType.CLIENT)
public final class Metal3ExecutionProvider implements MetalExecutionProvider {

    /** The Metal 3 queue factory. */
    private static final Msg NEW_COMMAND_QUEUE = Msg.of("newCommandQueue", ValueLayout.ADDRESS);

    @Override
    public long commandQueue(final MTLDevice device) {
        return NEW_COMMAND_QUEUE.sendPtr(device.handle()).address();
    }

    @Override
    public MetalExecutionState createExecutionState(final MTLDevice device) {
        return Metal3ExecutionFactory.createState(device);
    }

    @Override
    public MetalFrameEncoder createFrameEncoder(final MetalDevice device, final MetalExecutionState executionState,
                                                final ShaderSource defaultShaderSource) {
        return Metal3ExecutionFactory.createFrameEncoder(device, executionState, defaultShaderSource);
    }
}
