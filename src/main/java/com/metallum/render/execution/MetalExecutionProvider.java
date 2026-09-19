package com.metallum.render.execution;

import com.metallum.mtl.MTLDevice;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.MetalExecutionState;
import com.metallum.render.shared.MetalFrameEncoder;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The generation-specific half of the execution services: it owns where the queue, the state and the frame
 * encoder come from.
 * <p>
 * It exists so the services stop being the composition root that names a generation. They select a provider and
 * forward to it; the Metal 3 provider lives in {@code render.metal3} with the objects it builds, and a Metal 4
 * provider can be added without the services learning any of its types. Every signature here is neutral - no
 * command type, no encoder class, no compilation type.
 */
@Environment(EnvType.CLIENT)
public interface MetalExecutionProvider {

    /** The command queue this generation submits on, as the native handle an encoder takes. */
    long commandQueue(MTLDevice device);

    /** This generation's own execution state, as the contract the device holds. */
    MetalExecutionState createExecutionState(MTLDevice device);

    /** This generation's frame encoder, made from the state the device already holds. */
    MetalFrameEncoder createFrameEncoder(MetalDevice device, MetalExecutionState executionState,
                                         ShaderSource defaultShaderSource);
}
