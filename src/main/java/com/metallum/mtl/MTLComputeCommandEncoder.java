package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.lwjgl.system.MemoryStack;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public final class MTLComputeCommandEncoder extends MTLCommandEncoder {
    private static final Msg SET_COMPUTE_PIPELINE_STATE = Msg.ofVoid("setComputePipelineState:", ADDRESS);
    private static final Msg SET_BUFFER = Msg.ofVoid("setBuffer:offset:atIndex:", ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:atIndex:", ADDRESS, JAVA_LONG);
    private static final Msg SET_SAMPLER_STATE = Msg.ofVoid("setSamplerState:atIndex:", ADDRESS, JAVA_LONG);
    private static final Msg DISPATCH_THREADS = Msg.ofVoid("dispatchThreads:threadsPerThreadgroup:", ADDRESS, ADDRESS);
    private static final Msg DISPATCH_THREADGROUPS = Msg.ofVoid("dispatchThreadgroups:threadsPerThreadgroup:", ADDRESS, ADDRESS);
    private static final Msg UPDATE_FENCE = Msg.ofVoid("updateFence:", ADDRESS);
    private static final Msg WAIT_FOR_FENCE = Msg.ofVoid("waitForFence:", ADDRESS);

    MTLComputeCommandEncoder(final MemorySegment handle) {
        super(handle);
    }

    public void setComputePipelineState(final MemorySegment pipeline) {
        SET_COMPUTE_PIPELINE_STATE.send(handle(), pipeline);
    }

    public void setBuffer(final MTLBuffer buffer, final long offset, final long index) {
        SET_BUFFER.send(handle(), buffer == null ? MemorySegment.NULL : buffer.handle(), offset, index);
    }

    public void setTexture(final MemorySegment texture, final long index) {
        SET_TEXTURE.send(handle(), ObjC.orNil(texture), index);
    }

    public void setSamplerState(final MemorySegment sampler, final long index) {
        SET_SAMPLER_STATE.send(handle(), ObjC.orNil(sampler), index);
    }

    public void dispatchThreads(
            final long width,
            final long height,
            final long depth,
            final long threadsPerGroupWidth,
            final long threadsPerGroupHeight,
            final long threadsPerGroupDepth
    ) {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            DISPATCH_THREADS.send(
                    handle(),
                    MTLSize.on(stack, width, height, depth),
                    MTLSize.on(stack, threadsPerGroupWidth, threadsPerGroupHeight, threadsPerGroupDepth)
            );
        }
    }

    /**
     * Dispatches an exact number of workgroups, matching Vulkan {@code vkCmdDispatch} semantics.
     * The first size is the workgroup grid; the second is the shader's local workgroup size.
     */
    public void dispatchThreadgroups(
            final long groupsWidth,
            final long groupsHeight,
            final long groupsDepth,
            final long threadsPerGroupWidth,
            final long threadsPerGroupHeight,
            final long threadsPerGroupDepth
    ) {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            DISPATCH_THREADGROUPS.send(
                    handle(),
                    MTLSize.on(stack, groupsWidth, groupsHeight, groupsDepth),
                    MTLSize.on(stack, threadsPerGroupWidth, threadsPerGroupHeight, threadsPerGroupDepth)
            );
        }
    }

    public void updateFence(final MTLFence fence) {
        UPDATE_FENCE.send(handle(), fence.handle());
    }

    public void waitForFence(final MTLFence fence) {
        WAIT_FOR_FENCE.send(handle(), fence.handle());
    }
}
