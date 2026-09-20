package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4ComputeEncoder;
import com.metallum.mtl.metal4.MTL4FrameRing;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalDestructionQueue;
import com.metallum.render.shared.MetalFrameEncoder;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalTransientMemory;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.TransientMemory;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.buffers.GpuFence;
import org.jspecify.annotations.Nullable;
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
    private final com.mojang.blaze3d.shaders.ShaderSource defaultShaderSource;
    private final MTL4FrameRing ring;

    /**
     * What could not be released when it was replaced, per ring slot.
     * <p>
     * A slot's bucket is emptied when that slot is next begun, which is the moment the ring has just proved the
     * slot's previous submission complete - and never before, because a resource released while the GPU is
     * still reading what it fed is the corruption the ring exists to prevent.
     */
    private final ArrayDeque<Runnable>[] deferred;

    /**
     * The frame's staging arena and the releases that go with it.
     * <p>
     * A texture upload and a buffer write are copies from memory this engine owns, and that memory is rotated
     * per submitted frame for the same reason the ring's slots are: a staging buffer handed back while the GPU
     * is still reading it is the corruption the rotation exists to prevent.
     */
    private final MetalDestructionQueue destroyQueue = new MetalDestructionQueue(FRAMES_IN_FLIGHT);
    private final MetalTransientMemory transientMemory;

    /** The compute encoder the copies are encoded into, opened on demand and ended with the frame. */
    @Nullable
    private MTL4ComputeEncoder copyEncoder;

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
        this.defaultShaderSource = defaultShaderSource;
        MTLDevice nativeDevice = executionState.device();
        // The queue is the generation's own object and the address comes from the execution services, which is
        // the seam the frame path's isolation turns on - the same seam the Metal 3 encoder builds its queue
        // through, so neither generation owns the device's queue factory.
        long queue = device.executionServices().commandQueue(nativeDevice);
        this.ring = MTL4FrameRing.create(nativeDevice, MemorySegment.ofAddress(queue), FRAMES_IN_FLIGHT,
                "the Metal 4 frame encoder");
        this.transientMemory = new MetalTransientMemory(device, this.destroyQueue);
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
        if (this.copyEncoder != null) {
            this.copyEncoder.endEncoding();
        }
        if (!this.ring.begun()) {
            return;
        }
        if (!this.ring.endAndSubmit()) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: a frame could not be submitted - {}", this.ring.refusal());
        }
        // The arena's blocks are rotated here and not earlier: the submission that reads them has just been
        // made, and the slot that owns them is the one the ring will prove complete before reusing it.
        this.transientMemory.rotate();
        this.destroyQueue.rotate();
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
        if (this.copyEncoder != null) {
            this.copyEncoder.close();
            this.copyEncoder = null;
        }
        for (int slot = 0; slot < this.deferred.length; slot++) {
            retire(slot);
        }
        this.transientMemory.close();
        this.destroyQueue.close();
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

    /**
     * The encoder's staging arena: the memory a texture upload or a buffer write is copied out of.
     * <p>
     * It is the engine's own arena class rather than a new one, because what it has to be is the same on both
     * paths - a rotating block allocator whose retired blocks are released on the frame's own rotation - and it
     * is handed this encoder's destruction queue so that rotation is the frame's and not a second one's.
     */
    @Override
    public @NonNull TransientMemory transientMemory() {
        return this.transientMemory;
    }

    /**
     * The compute encoder the frame's copies are encoded into, opened on demand.
     * <p>
     * This command model has no blit encoder, so every copy - an upload, a download, a region copy - is a
     * compute encoder command. Only one encoder may be open on a command buffer at a time, so a render pass the
     * game still has open is ended first: its work is already encoded, and the pass's own submit becomes a
     * no-op rather than a second ending.
     */
    private MTL4ComputeEncoder copyEncoder() {
        if (this.currentPass != null) {
            submitRenderPass();
        }
        if (this.copyEncoder == null || !this.copyEncoder.open()) {
            // A copy that arrives before any pass still needs a frame: the command buffer has to be begun before
            // anything can be encoded into it, and beginning it is also where the slot's completion is proved.
            beginFrameIfNeeded();
            this.copyEncoder = MTL4ComputeEncoder.open(this.executionState.device(), this.ring.commandBuffer(),
                    "the frame's copies");
        }
        return this.copyEncoder;
    }

    /**
     * Begins the frame where it has not been: the ring's slot is chosen, its previous submission is waited for,
     * and the releases filed against it are run.
     * <p>
     * Both the first pass and the first copy need this, and it is one method because it is one thing - a frame
     * begins at whatever encodes into it first, and nothing else may begin one underneath it.
     */
    private void beginFrameIfNeeded() {
        if (this.ring.begun()) {
            return;
        }
        if (!this.ring.beginFrame()) {
            throw new IllegalStateException("the Metal 4 frame could not begin: " + this.ring.refusal());
        }
        // The wait inside beginFrame is what makes this legal: the slot's previous submission has completed, so
        // everything filed against it can be released now.
        retire(this.ring.slot());
    }

    /**
     * Uploads bytes into a slice of GPU memory: stage them in the frame's arena, then copy buffer to buffer.
     * <p>
     * The Metal 3 encoder writes a dynamic buffer's backing store directly instead, which is faster and is a
     * mechanism of its own; this path stages and copies for both, which is the slower and simpler answer and the
     * right one while the question is whether the path runs at all.
     */
    @Override
    public void writeToBuffer(final @NonNull GpuBufferSlice destination, final @NonNull ByteBuffer data) {
        MetalGpuBuffer target = bufferOf(destination.buffer());
        int length = data.remaining();
        GpuBufferSlice staging = this.transientMemory.uploadStaging(data, 4L, GpuBuffer.USAGE_COPY_SRC);
        if (!copyEncoder().copyBufferToBuffer(bufferOf(staging.buffer()).nativeHandle(),
                staging.offset(), target.nativeHandle(), destination.offset(), length)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a " + length + "-byte buffer write");
        }
    }

    /** Copies bytes between two slices of GPU memory. */
    @Override
    public void copyToBuffer(final @NonNull GpuBufferSlice source, final @NonNull GpuBufferSlice target) {
        if (!copyEncoder().copyBufferToBuffer(bufferOf(source.buffer()).nativeHandle(), source.offset(),
                bufferOf(target.buffer()).nativeHandle(), target.offset(), source.length())) {
            throw new IllegalStateException("the Metal 4 copy pass refused a " + source.length() + "-byte buffer"
                    + " copy");
        }
    }

    /**
     * Uploads bytes into a texture: staged in the frame's arena, then copied buffer to texture.
     * <p>
     * The row arithmetic is the engine's own - a row is the width times the texture's pixel size - because the
     * command takes the layout of the memory it is reading, and getting it wrong is a sheared image rather than
     * an error.
     */
    @Override
    public void writeToTexture(final @NonNull GpuTexture destination, final @NonNull ByteBuffer data,
                               final int mipLevel, final int depthOrLayer, final int x, final int y,
                               final int width, final int height) {
        MetalGpuTexture texture = textureOf(destination);
        int pixelSize = texture.pixelSize();
        int rowBytes = width * pixelSize;
        int bytesPerImage = rowBytes * height;
        GpuBufferSlice staging = this.transientMemory.uploadStaging(
                data.duplicate().limit(bytesPerImage), pixelSize, GpuBuffer.USAGE_COPY_SRC);
        if (!copyEncoder().copyBufferToTexture(bufferOf(staging.buffer()).nativeHandle(), staging.offset(), rowBytes,
                bytesPerImage, width, height, 1L, texture.nativeHandle(), depthOrLayer, mipLevel, x, y, 0L)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a texture write of " + width + "x"
                    + height + " at (" + x + ", " + y + ")");
        }
    }

    /** Copies a region of a buffer into a texture, which is the engine's other upload shape. */
    @Override
    public void copyBufferToTexture(final @NonNull GpuBufferSlice source, final int sourceX, final int sourceY,
                                    final int sourceWidth, final int sourceHeight,
                                    final @NonNull GpuTexture destination, final int destinationX,
                                    final int destinationY, final int copyWidth, final int copyHeight,
                                    final int mipLevel, final int arrayLayer) {
        MetalGpuTexture texture = textureOf(destination);
        int texelSize = texture.pixelSize();
        long skipBytes = (sourceX + (long) sourceY * sourceWidth) * texelSize;
        long rowBytes = (long) sourceWidth * texelSize;
        if (!copyEncoder().copyBufferToTexture(bufferOf(source.buffer()).nativeHandle(),
                source.offset() + skipBytes, rowBytes, rowBytes * sourceHeight, copyWidth, copyHeight, 1L,
                texture.nativeHandle(), arrayLayer, mipLevel, destinationX, destinationY, 0L)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a " + copyWidth + "x" + copyHeight
                    + " texture region copy");
        }
    }

    /**
     * Copies a texture's region out into a buffer, and files the caller's callback with the frame's releases.
     * <p>
     * The callback is not run here and not run on the GPU: it is filed against the ring slot whose completion
     * makes the bytes valid, so it fires once that slot has been proved complete. The Metal 3 path hangs the same
     * callback on the command buffer's completion block, which is more immediate; this is the first version's
     * answer and the difference is written down rather than implied - the bytes are ordered correctly, the
     * callback may arrive a frame later.
     */
    @Override
    public void copyTextureToBuffer(final @NonNull GpuTexture source, final @NonNull GpuBuffer destination,
                                    final long destinationOffset, final @NonNull Runnable callback,
                                    final int mipLevel) {
        copyTextureToBuffer(source, destination, destinationOffset, callback, mipLevel, 0, 0,
                (int) source.getWidth(mipLevel), (int) source.getHeight(mipLevel));
    }

    @Override
    public void copyTextureToBuffer(final @NonNull GpuTexture source, final @NonNull GpuBuffer destination,
                                    final long destinationOffset, final @NonNull Runnable callback,
                                    final int mipLevel, final int x, final int y, final int width,
                                    final int height) {
        MetalGpuTexture texture = textureOf(source);
        int rowBytes = width * texture.pixelSize();
        int bytesPerImage = rowBytes * height;
        if (!copyEncoder().copyTextureToBuffer(texture.nativeHandle(), 0L, mipLevel, x, y, 0L, width, height, 1L,
                bufferOf(destination).nativeHandle(), destinationOffset, rowBytes, bytesPerImage)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a readback of " + width + "x" + height);
        }
        queueForDestroy(callback);
    }

    /** Copies a region of one texture into another, which is the copy a frame makes most of. */
    @Override
    public void copyTextureToTexture(final @NonNull GpuTexture source, final @NonNull GpuTexture destination,
                                     final int mipLevel, final int x, final int y, final int width, final int height,
                                     final int destinationX, final int destinationY) {
        if (!copyEncoder().copyTextureRegion(textureOf(source).nativeHandle(), 0L, mipLevel, x, y, 0L, width,
                height, 1L, textureOf(destination).nativeHandle(), 0L, mipLevel, destinationX, destinationY, 0L)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a " + width + "x" + height
                    + " texture-to-texture copy");
        }
    }

    /** The engine's buffer wrapper, or a named fault where something else was handed over. */
    private static MetalGpuBuffer bufferOf(final GpuBuffer buffer) {
        if (!(buffer instanceof MetalGpuBuffer metal)) {
            throw new IllegalStateException("the Metal 4 encoder was handed a buffer that is not this engine's: "
                    + buffer.getClass().getName());
        }
        return metal;
    }

    /** The engine's texture wrapper, or a named fault where something else was handed over. */
    private static MetalGpuTexture textureOf(final GpuTexture texture) {
        if (!(texture instanceof MetalGpuTexture metal)) {
            throw new IllegalStateException("the Metal 4 encoder was handed a texture that is not this engine's: "
                    + texture.getClass().getName());
        }
        return metal;
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
        // A copy the frame encoded before this pass wrote something this pass may read, so the dependency is
        // encoded here - the same over-synchronisation the pass itself ends with, in the other direction.
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.barrierForSubsequentEncoders();
            this.copyEncoder.endEncoding();
        }
        beginFrameIfNeeded();

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

    /** The generation state this encoder compiles through, for the pass that sets a pipeline. */
    Metal4ExecutionState state() {
        return this.executionState;
    }

    /** The session's shader source, which the state needs before it can compile anything. */
    com.mojang.blaze3d.shaders.ShaderSource shaderSource() {
        return this.defaultShaderSource;
    }

    /**
     * The compiled artifact for a pipeline, compiling it if this state does not hold it.
     * <p>
     * It is the pass that asks, because it is the pass that sets a pipeline; the cast is safe by construction -
     * the state this encoder was made with is this generation's, and its compile path returns this generation's
     * artifact.
     */
    Metal4CompiledRenderPipeline compiled(final com.mojang.blaze3d.pipeline.RenderPipeline pipeline) {
        return (Metal4CompiledRenderPipeline) this.executionState.getOrCompilePipeline(pipeline,
                this.defaultShaderSource);
    }

    /** The command buffer the frame is being encoded into, for the pass that opens on it. */
    MemorySegment commandBuffer() {
        return this.ring.commandBuffer();
    }

    /** The device this frame's passes are described on. */
    MTLDevice nativeDevice() {
        return this.executionState.device();
    }

    /**
     * Clears a colour attachment by opening a pass that loads it cleared and stores it, with no draw in it.
     * <p>
     * A clear is a load action on this API, and a load action belongs to a pass - so the honest first version is
     * a pass of its own. The Metal 3 encoder instead records the clear and folds it into the next pass that uses
     * that attachment, which is cheaper (no pass, and the attachment is never loaded) and is a lifetime model of
     * its own. This one is the simpler answer while the question is whether the path runs at all, and the extra
     * pass is what it costs.
     */
    @Override
    public void clearColorTexture(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor) {
        MetalGpuTexture color = textureOf(colorTexture);
        encodeClear("clearColorTexture",
                new MTL4RenderEncoder.Color[]{new MTL4RenderEncoder.Color(color.nativeHandle(),
                        AttachmentContents.CARRIED, components(clearColor))},
                null, colorTexture.getWidth(0), colorTexture.getHeight(0));
    }

    /** Clears a colour attachment and a depth attachment in one pass, which is one pass and not two. */
    @Override
    public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor,
                                           final @NonNull GpuTexture depthTexture, final double clearDepth) {
        MetalGpuTexture color = textureOf(colorTexture);
        MetalGpuTexture depth = textureOf(depthTexture);
        encodeClear("clearColorAndDepthTextures",
                new MTL4RenderEncoder.Color[]{new MTL4RenderEncoder.Color(color.nativeHandle(),
                        AttachmentContents.CARRIED, components(clearColor))},
                new MTL4RenderEncoder.Depth(depth.nativeHandle(), clearDepth),
                colorTexture.getWidth(0), colorTexture.getHeight(0));
    }

    @Override
    public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor,
                                           final @NonNull GpuTexture depthTexture, final double clearDepth,
                                           final int scissorX, final int scissorY, final int scissorWidth,
                                           final int scissorHeight) {
        throw unimplemented("clearColorAndDepthTextures");
    }

    /** Clears a depth attachment on its own, in a pass whose only attachment is that one. */
    @Override
    public void clearDepthTexture(final @NonNull GpuTexture depthTexture, final double clearDepth) {
        MetalGpuTexture depth = textureOf(depthTexture);
        encodeClear("clearDepthTexture", new MTL4RenderEncoder.Color[0],
                new MTL4RenderEncoder.Depth(depth.nativeHandle(), clearDepth),
                depthTexture.getWidth(0), depthTexture.getHeight(0));
    }

    /**
     * A fence promised about a submission, which on this command model is the ring's own completion value.
     * <p>
     * Which submission is the only decision here, and it is the caller's question read back: the game makes a
     * fence from inside a frame ({@code MappableRingBuffer.rotate}, at the end of a frame's encoding, and
     * {@code StagedVertexBuffer}'s pool at the end of a frame) and waits on it a few frames later before it
     * hands the buffer back to the CPU. A frame that is open will be committed as the ring's next submission, so
     * that is what the fence promises; made between frames there is no open frame to be about, so it promises
     * the work already submitted - the frame that just ended.
     */
    @Override
    public @NonNull GpuFence createFence() {
        long submission = this.ring.begun() ? this.ring.nextSubmission() : this.ring.submissions();
        return new Metal4Fence(this.ring, submission);
    }

    /**
     * Encodes one clear as a pass of its own.
     * <p>
     * Everything it depends on is already in place: a frame is begun if none is, a pass the game still has open
     * is ended first because only one encoder may be open on a command buffer, a copy pass is ended and ordered
     * against this one, and the clear's pass ends with the producer barrier so that whatever reads the cleared
     * attachment afterwards has an encoded dependency on it.
     */
    private void encodeClear(final String operation, final MTL4RenderEncoder.Color[] colors,
                             final MTL4RenderEncoder.Depth depth, final long width, final long height) {
        if (this.currentPass != null) {
            submitRenderPass();
        }
        beginFrameIfNeeded();
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.barrierForSubsequentEncoders();
            this.copyEncoder.endEncoding();
        }

        MTL4RenderEncoder pass;
        try {
            pass = MTL4RenderEncoder.open(this.executionState.device(), this.ring.commandBuffer(), width, height,
                    colors, depth, operation);
        } catch (MTL4RenderEncoder.Refused refused) {
            throw new IllegalStateException(operation + " could not be encoded at stage " + refused.stage() + ": "
                    + refused.getMessage(), refused);
        }
        try {
            if (!pass.barrierForSubsequentEncoders()) {
                Metallum.LOGGER.warn("Metal 4 frame encoder: {}'s pass does not answer the producer barrier, so a"
                        + " later pass that reads the cleared attachment has no encoded dependency", operation);
            }
            pass.endEncoding();
        } finally {
            pass.close();
        }
    }

    /** A clear colour as the descriptor's four components. */
    private static float[] components(final Vector4fc color) {
        return new float[]{color.x(), color.y(), color.z(), color.w()};
    }

    /** Timestamps are the counter path, which the migration puts after correctness, not beside it. */
    @Override
    public void writeTimestamp(final @NonNull GpuQueryPool pool, final int index) {
        throw unimplemented("writeTimestamp");
    }
}
