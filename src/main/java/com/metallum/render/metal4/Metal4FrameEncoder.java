package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4FrameRing;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.MetalFrameEncoder;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.TransientMemory;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.buffers.GpuFence;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4fc;
import org.jspecify.annotations.NonNull;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.util.ArrayDeque;

/**
 * The Metal 4 frame encoder: the object the executing generation's frame would be built from.
 * <p>
 * <strong>What exists is the frame's lifetime, and nothing else.</strong> This encoder owns the ring
 * {@code mtl.metal4.MTL4FrameRing} - the allocator slots, one command buffer and the shared event whose values
 * prove a slot free - and it owns the resources a frame cannot release yet, filed against the slot that will
 * prove them free. That is the half of the frame path where being wrong is a use-after-free, and it is the half
 * the migration's sections 30 to 32 ask for first: begin a frame, choose a slot, wait for it, reset it, begin,
 * encode, end, commit <em>once</em>, retire.
 * <p>
 * <strong>What does not exist refuses by name.</strong> Every operation that would render, copy, clear or
 * measure raises {@link Metal4ExecutionProvider.Unimplemented} named for itself - section 35's rule, and the
 * same reason the provider's own refusals carry a stage: an operation dropped in silence is a half frame, and a
 * half frame is worse than a frame that says it cannot run yet. The refusals are the work list, one per line,
 * which is what a migration wants its gaps to look like.
 * <p>
 * <strong>Nothing reaches this class yet.</strong> The services hand out the provider of the generation that is
 * <em>executing</em>, and the device states that generation as Metal 3 until a Metal 4 frame path is ready - so
 * this encoder is constructed only by a build that says Metal 4 executes, and today it is the object that would
 * own the frame rather than the object that owns one. Its classes are package-private for the same reason: the
 * provider is the generation's public seam and the neutral interfaces are what a caller holds.
 * <p>
 * <strong>What it deliberately does not do</strong>: it does not implement the bridges' optional contracts
 * ({@code MetalFrameExtras}, {@code MetalFrameResourceCommands}, {@code MetalFramePresentation}), because each
 * of them is an operation this path cannot perform yet - a bridged caller finds the contract missing and takes
 * its own fallback, which is the explicit answer, and implementing them with do-nothing bodies would be the
 * silent drop the plan forbids.
 */
@Environment(EnvType.CLIENT)
final class Metal4FrameEncoder implements MetalFrameEncoder {

    /** The frame model the ring runs, which the migration's section 31 fixes at the present path's own depth. */
    private static final int FRAMES_IN_FLIGHT = MTL4FrameRing.FRAMES_IN_FLIGHT;

    private final MetalDevice device;
    private final Metal4ExecutionState executionState;
    private final MTL4FrameRing ring;

    /**
     * What could not be released when it was replaced, per ring slot.
     * <p>
     * A slot's bucket is emptied when that slot is next begun, which is the moment the ring has just proved the
     * slot's previous submission complete - and never before, because a resource released while the GPU is
     * still reading what it fed is the corruption the ring exists to prevent.
     */
    private final ArrayDeque<Runnable>[] deferred;

    private boolean closed;

    /**
     * The pass currently open, so that a second {@code createRenderPass} before a {@code submitRenderPass} is a
     * named fault rather than two encoders writing into one command buffer with no order between them.
     */
    @org.jspecify.annotations.Nullable
    private Metal4RenderPass currentPass;

    /**
     * @param device             the engine's device, which is where the queue address comes from
     * @param executionState     this generation's state, whose device the ring is made on
     * @param defaultShaderSource the session's shader source; held by the compilation chain when that lands,
     *                           which is why it is taken here and not used yet
     */
    @SuppressWarnings("unchecked")
    Metal4FrameEncoder(final MetalDevice device, final Metal4ExecutionState executionState,
                       final com.mojang.blaze3d.shaders.ShaderSource defaultShaderSource) {
        this.device = device;
        this.executionState = executionState;
        MTLDevice nativeDevice = executionState.device();
        // The queue is the generation's own object and the address comes from the execution services, which is
        // the seam the frame path's isolation turns on - the same seam the Metal 3 encoder builds its queue
        // through, so neither generation owns the device's queue factory.
        long queue = device.executionServices().commandQueue(nativeDevice);
        this.ring = MTL4FrameRing.create(nativeDevice, MemorySegment.ofAddress(queue), FRAMES_IN_FLIGHT,
                "the Metal 4 frame encoder");
        this.deferred = new ArrayDeque[FRAMES_IN_FLIGHT];
        for (int slot = 0; slot < this.deferred.length; slot++) {
            this.deferred[slot] = new ArrayDeque<>();
        }
    }

    /** The state this encoder was made from, for the helpers that will be handed it rather than the device. */
    Metal4ExecutionState executionState() {
        return this.executionState;
    }

    /**
     * Ends and commits the frame, once.
     * <p>
     * A frame with nothing encoded into it is not committed: one commit a frame is the target, and a commit that
     * carries no work is a submission the frame never asked for. The frame's own begin belongs to whatever first
     * encodes into it, which is the render-pass path this class does not have yet - so today this method finds
     * no frame and does nothing, and that is a fact about the migration's stage rather than a licence to skip
     * the commit.
     */
    @Override
    public void submit() {
        if (this.closed) {
            return;
        }
        // A pass still open when the frame is submitted is a pass the game did not end: it is ended here, which
        // is what the Metal 3 encoder does, because the alternative is a command buffer ended with an encoder
        // still open and no image at all.
        if (this.currentPass != null) {
            submitRenderPass();
        }
        if (!this.ring.begun()) {
            return;
        }
        if (!this.ring.endAndSubmit()) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: a frame could not be submitted - {}", this.ring.refusal());
        }
    }

    /**
     * Waits for the work submitted so far, and then releases what was waiting on it.
     * <p>
     * The order is the whole method: the destroys filed per slot are only legal once the GPU is done with what
     * they describe, and a wait that ran after the release would be a wait that proves nothing.
     */
    @Override
    public void waitForSubmittedGpuWork() {
        if (!this.ring.awaitAll()) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: the submitted work was not observed complete within the"
                    + " ring's own timeout - {}", this.ring.refusal());
        }
        for (int slot = 0; slot < this.deferred.length; slot++) {
            retire(slot);
        }
    }

    /**
     * Files a release against the frame whose completion will make it safe.
     * <p>
     * While a frame is begun the resource belonged to that frame's slot and is retired when that slot comes
     * round again; with no frame begun it is filed against the next slot, which is the earliest point at which
     * this encoder can know the GPU is done with the frame that replaced it.
     */
    @Override
    public void queueForDestroy(final Runnable destroyAction) {
        int slot = this.ring.begun() ? this.ring.slot() : this.ring.nextSlot();
        this.deferred[slot].add(destroyAction);
    }

    /** Runs one slot's filed releases, which the caller may only do once that slot's work has completed. */
    private void retire(final int slot) {
        ArrayDeque<Runnable> bucket = this.deferred[slot];
        while (!bucket.isEmpty()) {
            bucket.poll().run();
        }
    }

    /**
     * Releases the frame's ring and everything filed against it.
     * <p>
     * The wait is best-effort and comes first, for the reason the whole class exists: allocators may only be
     * released and reset once the work encoded on them has completed.
     */
    @Override
    public void close() {
        if (this.closed) {
            return;
        }
        this.closed = true;
        if (this.currentPass != null) {
            submitRenderPass();
        }
        if (!this.ring.awaitAll()) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: closing with work that was not observed complete - {}",
                    this.ring.refusal());
        }
        for (int slot = 0; slot < this.deferred.length; slot++) {
            retire(slot);
        }
        this.ring.close();
    }

    // ---------------------------------------------------------------- and the operations that do not exist

    /**
     * The one shape every unimplemented operation takes: a refusal named for the operation.
     * <p>
     * The name is the stage the migration plan's own list would use, so a log line and the plan's remaining
     * work can be read against each other, and so a caller that catches the failure knows which operation it
     * asked for even where it asked for several.
     */
    private static Metal4ExecutionProvider.Unimplemented unimplemented(final String operation) {
        return new Metal4ExecutionProvider.Unimplemented(operation,
                "the Metal 4 frame encoder does not encode " + operation + " yet: the frame path is still Metal"
                        + " 3's, and this path refuses by name rather than dropping the operation into a half"
                        + " frame");
    }

    /** Transient memory is the encoder's staging arena, which arrives with the first operation that needs it. */
    @Override
    public @NonNull TransientMemory transientMemory() {
        throw unimplemented("transientMemory");
    }

    /**
     * Opens a render pass on this frame's command buffer, beginning the frame at the first one.
     * <p>
     * The frame's begin belongs here rather than to the game's frame loop, because the first thing that encodes
     * into a frame is the first pass that encodes into it: a frame begun for a frame nothing encoded would be an
     * empty commit a frame, and a frame begun late would be a pass with nowhere to go. Beginning it is also where
     * the slot's previous submission is proved complete - the ring waits in {@code beginFrame} - so this is the
     * one place a slot's filed releases may be run.
     */
    @Override
    public @NonNull RenderPassBackend createRenderPass(final RenderPassDescriptor descriptor) {
        if (this.closed) {
            throw new IllegalStateException("the Metal 4 frame encoder is closed");
        }
        if (this.currentPass != null) {
            throw new IllegalStateException("a Metal 4 render pass is already open; submitRenderPass() ends it,"
                    + " and two open passes would encode into one command buffer with no order between them");
        }
        if (!this.ring.begun()) {
            if (!this.ring.beginFrame()) {
                throw new IllegalStateException("the Metal 4 frame could not begin: " + this.ring.refusal());
            }
            // The wait inside beginFrame is what makes this legal: the slot's previous submission has completed,
            // so everything filed against it can be released now.
            retire(this.ring.slot());
        }

        Metal4RenderPass pass = new Metal4RenderPass(this, descriptor);
        this.currentPass = pass;
        return pass;
    }

    /**
     * Ends the pass the frame is encoding.
     * <p>
     * The barrier that lets a later pass read what this one wrote is encoded by the pass itself, before its
     * encoder ends - the migration's section 61 rule, applied conservatively because whether a dependency exists
     * is a fact about the pass that reads and that fact does not reach this generation yet.
     */
    @Override
    public void submitRenderPass() {
        Metal4RenderPass pass = this.currentPass;
        if (pass == null) {
            return;
        }
        this.currentPass = null;
        pass.finish();
    }

    /** The command buffer the frame is being encoded into, for the pass that opens on it. */
    MemorySegment commandBuffer() {
        return this.ring.commandBuffer();
    }

    /** The device this frame's passes are described on. */
    MTLDevice nativeDevice() {
        return this.executionState.device();
    }

    @Override
    public void clearColorTexture(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor) {
        throw unimplemented("clearColorTexture");
    }

    @Override
    public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor,
                                           final @NonNull GpuTexture depthTexture, final double clearDepth) {
        throw unimplemented("clearColorAndDepthTextures");
    }

    @Override
    public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor,
                                           final @NonNull GpuTexture depthTexture, final double clearDepth,
                                           final int scissorX, final int scissorY, final int scissorWidth,
                                           final int scissorHeight) {
        throw unimplemented("clearColorAndDepthTextures");
    }

    @Override
    public void clearDepthTexture(final @NonNull GpuTexture depthTexture, final double clearDepth) {
        throw unimplemented("clearDepthTexture");
    }

    @Override
    public void writeToBuffer(final @NonNull GpuBufferSlice destination, final @NonNull ByteBuffer data) {
        throw unimplemented("writeToBuffer");
    }

    @Override
    public void copyToBuffer(final @NonNull GpuBufferSlice source, final @NonNull GpuBufferSlice target) {
        throw unimplemented("copyToBuffer");
    }

    @Override
    public void writeToTexture(final @NonNull GpuTexture destination, final @NonNull ByteBuffer data,
                               final int mipLevel, final int depthOrLayer, final int x, final int y,
                               final int width, final int height) {
        throw unimplemented("writeToTexture");
    }

    @Override
    public void copyBufferToTexture(final @NonNull GpuBufferSlice source, final int sourceX, final int sourceY,
                                    final int sourceWidth, final int sourceHeight,
                                    final @NonNull GpuTexture destination, final int destinationX,
                                    final int destinationY, final int copyWidth, final int copyHeight,
                                    final int mipLevel, final int arrayLayer) {
        throw unimplemented("copyBufferToTexture");
    }

    @Override
    public void copyTextureToBuffer(final @NonNull GpuTexture source, final @NonNull GpuBuffer destination,
                                    final long destinationOffset, final @NonNull Runnable callback,
                                    final int mipLevel) {
        throw unimplemented("copyTextureToBuffer");
    }

    @Override
    public void copyTextureToBuffer(final @NonNull GpuTexture source, final @NonNull GpuBuffer destination,
                                    final long destinationOffset, final @NonNull Runnable callback,
                                    final int mipLevel, final int x, final int y, final int width,
                                    final int height) {
        throw unimplemented("copyTextureToBuffer");
    }

    @Override
    public void copyTextureToTexture(final @NonNull GpuTexture source, final @NonNull GpuTexture destination,
                                     final int mipLevel, final int x, final int y, final int width, final int height,
                                     final int destinationX, final int destinationY) {
        throw unimplemented("copyTextureToTexture");
    }

    /**
     * A fence is a Metal 3 dependency object; the new command model orders work with barriers and queue events,
     * so this refuses rather than handing back something the caller would wait on for the wrong reason.
     */
    @Override
    public @NonNull GpuFence createFence() {
        throw unimplemented("createFence");
    }

    /** Timestamps are the counter path, which the migration puts after correctness, not beside it. */
    @Override
    public void writeTimestamp(final @NonNull GpuQueryPool pool, final int index) {
        throw unimplemented("writeTimestamp");
    }
}
