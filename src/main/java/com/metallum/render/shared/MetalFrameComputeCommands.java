package com.metallum.render.shared;

import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.util.Map;

/**
 * Dispatching compute work, as generation-neutral vocabulary: a pipeline resource the caller owns, the bindings
 * and the workgroup counts. No encoder type and no command type appears, so a caller never has to know which
 * generation encodes the dispatch.
 */
@Environment(EnvType.CLIENT)
public interface MetalFrameComputeCommands {

    /** Dispatches workgroups, answering whether the dispatch was encoded. */
    boolean dispatchCompute(
            Object pipeline,
            Map<String, GpuBufferSlice> buffers,
            Map<String, GpuTextureView> textures,
            Map<String, GpuSampler> samplers,
            int groupsX,
            int groupsY,
            int groupsZ,
            int localX,
            int localY,
            int localZ
    );
}
