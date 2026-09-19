package com.metallum.render;

import com.metallum.render.shared.MetalComputeCompiler;
import com.metallum.render.shared.MetalComputePipelineResource;
import com.metallum.render.shared.MetalFrameComputeCommands;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.nio.ByteBuffer;
import java.util.Map;

/**
 * The optional client's compute entry point: the name and the three signatures it has always had, delegating to
 * the Metal 3 implementation in {@code render.metal3}.
 * <p>
 * The body it used to hold needs the generation's encoder internals and its execution state, which stay
 * package-private where they belong. What stays here is the API an optional client compiles against, and the one
 * thing it does beyond forwarding is hand the implementation the execution state - because that call receives the
 * device rather than an encoder, which is why {@link MetalDevice#executionState()} exists.
 */
@Environment(EnvType.CLIENT)
public final class MetalComputeBridge {

    private MetalComputeBridge() {
    }

    /** Compiles a compute pipeline from SPIR-V, answering an opaque resource for {@link #dispatch}. */
    public static Object compile(final Object backend, final String label, final ByteBuffer spirv) {
        if (!(backend instanceof MetalDevice device)) {
            throw new IllegalArgumentException("Not a Metallum MetalDevice backend: " + backend);
        }

        if (!(device.executionState() instanceof MetalComputeCompiler compiler)) {
            throw new IllegalStateException("Active Metal execution state does not support compute");
        }

        return compiler.compileCompute(device, label, spirv);
    }

    /** Dispatches workgroups, answering whether the dispatch was encoded. */
    public static boolean dispatch(
            final Object encoderBackend,
            final Object pipelineResource,
            final Map<String, GpuBufferSlice> buffers,
            final Map<String, GpuTextureView> textures,
            final Map<String, GpuSampler> samplers,
            final int groupsX,
            final int groupsY,
            final int groupsZ,
            final int localX,
            final int localY,
            final int localZ
    ) {
        return encoderBackend instanceof MetalFrameComputeCommands commands
                && commands.dispatchCompute(pipelineResource, buffers, textures, samplers,
                        groupsX, groupsY, groupsZ, localX, localY, localZ);
    }

    /** Releases an opaque pipeline returned by {@link #compile(Object, String, ByteBuffer)}. */
    public static void close(final Object pipelineResource) {
        if (pipelineResource instanceof MetalComputePipelineResource resource) {
            resource.close();
        }
    }
}
