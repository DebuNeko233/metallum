package com.metallum.render.metal3;

import com.metallum.mtl.MTLDevice;
import com.metallum.render.shared.MetalExecutionState;
import com.metallum.render.shared.MetalFrameEncoder;
import com.mojang.blaze3d.shaders.ShaderSource;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import com.metallum.render.MetalDevice;

/**
 * The one public Metal 3 construction seam: it makes the generation's execution state and its frame encoder, and
 * every signature it exposes is neutral - {@code MTLDevice}, {@code MetalDevice}, {@code MetalExecutionState},
 * {@code MetalFrameEncoder}, {@code ShaderSource}. It never hands out {@code Metal3ExecutionState},
 * {@code MetalCommandEncoder} or any compilation type, so a caller cannot reach past it into the generation.
 * <p>
 * It is public because the execution services live in another package and must be able to construct the
 * generation's objects; everything it constructs stays package-private. It moves to {@code render.metal3} with
 * the cluster it builds, and the callers' signatures will not change when it does.
 */
@Environment(EnvType.CLIENT)
public final class Metal3ExecutionFactory {

    private Metal3ExecutionFactory() {
    }

    /** The Metal 3 session state for this device. */
    public static MetalExecutionState createState(final MTLDevice device) {
        return new Metal3ExecutionState(device);
    }

    /** The frame encoder for this device, given the state the device holds. */
    public static MetalFrameEncoder createFrameEncoder(final MetalDevice device,
                                                       final MetalExecutionState executionState,
                                                       final ShaderSource defaultShaderSource) {
        if (!(executionState instanceof Metal3ExecutionState metal3)) {
            throw new IllegalArgumentException("Metal 3 frame encoder requires Metal3ExecutionState");
        }

        return new MetalCommandEncoder(device, metal3, defaultShaderSource);
    }
}
