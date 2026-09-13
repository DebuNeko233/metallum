package com.metallum.mtl;

import com.metallum.objc.Msg;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.lwjgl.system.MemoryStack;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public final class MTLComputeCommandEncoder extends MTLCommandEncoder {
    private static final Msg SET_COMPUTE_PIPELINE_STATE = Msg.ofVoid("setComputePipelineState:", ADDRESS);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:atIndex:", ADDRESS, JAVA_LONG);
    private static final Msg DISPATCH_THREADS = Msg.ofVoid("dispatchThreads:threadsPerThreadgroup:", ADDRESS, ADDRESS);
    private static final Msg UPDATE_FENCE = Msg.ofVoid("updateFence:", ADDRESS);
    private static final Msg WAIT_FOR_FENCE = Msg.ofVoid("waitForFence:", ADDRESS);

    MTLComputeCommandEncoder(final MemorySegment handle) {
        super(handle);
    }

    public void setComputePipelineState(final MemorySegment pipeline) {
        SET_COMPUTE_PIPELINE_STATE.send(handle(), pipeline);
    }

    public void setTexture(final MemorySegment texture, final long index) {
        SET_TEXTURE.send(handle(), texture, index);
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

    public void updateFence(final MTLFence fence) {
        UPDATE_FENCE.send(handle(), fence.handle());
    }

    public void waitForFence(final MTLFence fence) {
        WAIT_FOR_FENCE.send(handle(), fence.handle());
    }
}
