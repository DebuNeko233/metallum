package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.*;
import com.metallum.objc.ObjC;
import com.metallum.objc.ObjCBlock;
import com.metallum.render.MetalFrameProbe.EncoderEnd;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.buffers.GpuFence;
import com.mojang.blaze3d.systems.*;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.textures.GpuTextureView;
import it.unimi.dsi.fastutil.longs.Long2ObjectOpenHashMap;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4f;
import org.joml.Vector4fc;
import org.jspecify.annotations.NonNull;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.*;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

@Environment(EnvType.CLIENT)
final class MetalCommandEncoder implements CommandEncoderBackend {
    public static final int MAX_SUBMITS_IN_FLIGHT = 3;
    private static final int MAX_COLOR_ATTACHMENTS = 8;

    private final MetalDevice device;
    private long currentSubmitIndex = MAX_SUBMITS_IN_FLIGHT;
    private final InFlight[] inFlight = new InFlight[MAX_SUBMITS_IN_FLIGHT];
    private final Semaphore[] submitSemaphores = new Semaphore[MAX_SUBMITS_IN_FLIGHT];
    private final MemorySegment[] submitSignalBlocks = new MemorySegment[MAX_SUBMITS_IN_FLIGHT];
    private final MetalDestructionQueue destroyQueue = new MetalDestructionQueue(MAX_SUBMITS_IN_FLIGHT);
    private final MetalTransientMemory transientMemory;
    private final Map<MetalGpuTexture, Vector4fc> pendingColorClears = new IdentityHashMap<>();
    private final Map<MetalGpuTexture, Double> pendingDepthClears = new IdentityHashMap<>();
    private final MTLFence fence;

    /**
     * The newest submit index a command buffer was actually committed for.
     * <p>
     * {@link #currentSubmitIndex} counts submits, and a presented frame makes two of them: the frame's
     * own commit and the surface's present-time submit, which finds no command buffer and commits
     * nothing. Deriving "the newest submitted work" from that counter therefore names the submit that
     * committed nothing - an index no in-flight slot holds, which a wait has to treat as already done.
     */
    private long lastCommittedSubmitIndex = -1L;
    @Nullable
    private MetalRenderPass currentRenderPass;
    @Nullable
    private MTLCommandBuffer commandBuffer;
    @Nullable
    private MTLCommandEncoder currentEncoder;
    /**
     * What the next render pass will say about its colour attachments' contents, or null where
     * nothing has been said and every attachment is {@link AttachmentContents#CARRIED}. Read once and
     * cleared by that pass, so a pass nobody described gets the answer that changes nothing.
     */
    @Nullable
    private AttachmentContents[] nextPassContents;
    /**
     * Whether the next render pass may read a storage image written since the live encoder opened.
     * <p>
     * A graphics stage's {@code imageStore} is untracked, so anything that reads one afterwards has
     * to be ordered against it by the fence chain, and the fence is only meaningful across an
     * encoder boundary. The default is true, which is the answer that breaks the encoder: a pass
     * nobody described keeps the behaviour this backend had before the fact existed.
     */
    private boolean nextPassReadsStorageImage = true;
    /**
     * Whether a storage image has been written since the live encoder opened, with nothing ordered
     * against it yet. Held rather than acted on, because whether the boundary is owed depends on
     * what comes next and not on what has just been drawn.
     */
    private boolean storageUnordered;
    private MemorySegment[] renderColorAttachments = new MemorySegment[0];
    /**
     * What the pass the live encoder was opened for said about its attachments' contents, with the
     * default filled in. Held because it decides whether the next pass may reuse that encoder: an
     * encoder keeps the load and store actions it was created with, so a pass whose attachments
     * match but whose answers differ cannot share it without reading what the earlier one discarded.
     */
    private AttachmentContents[] renderContents = new AttachmentContents[0];
    private MemorySegment renderDepthAttachment = MemorySegment.NULL;
    private final Long2ObjectOpenHashMap<ArrayDeque<MTLBuffer>> dynamicBackingPool = new Long2ObjectOpenHashMap<>();

    MetalCommandEncoder(final MetalDevice device) {
        this.device = device;
        this.transientMemory = new MetalTransientMemory(device, this);
        fence = device.metalDevice().newFence();
        for (int slot = 0; slot < MAX_SUBMITS_IN_FLIGHT; slot++) {
            Semaphore semaphore = new Semaphore(0);
            submitSemaphores[slot] = semaphore;
            submitSignalBlocks[slot] = ObjCBlock.withRunnable(semaphore::release);
        }
    }

    MTLCommandBuffer commandBuffer() {
        if (commandBuffer != null) {
            return commandBuffer;
        }
        return commandBuffer = device.commandQueue.makeCommandBuffer(
                device.useLabels() ? "Metallum frame " + currentSubmitIndex : null
        );
    }

    MTLBlitCommandEncoder blitCommandEncoder() {
        endEncoder();
        MetalFrameProbe.encoderOpened(1);
        MTLBlitCommandEncoder encoder = commandBuffer().makeBlitCommandEncoder();
        encoder.waitForFence(fence);
        currentEncoder = encoder;
        return encoder;
    }

    MTLComputeCommandEncoder computeCommandEncoder() {
        endEncoder();
        MetalFrameProbe.encoderOpened(2);
        MTLComputeCommandEncoder encoder = commandBuffer().makeComputeCommandEncoder();
        encoder.waitForFence(fence);
        currentEncoder = encoder;
        return encoder;
    }

    /**
     * Generates all mip levels after level zero using Metal's native blit command.
     * <p>
     * This is a backend capability rather than a shader-pack concept. Metal only guarantees
     * {@code generateMipmapsForTexture:} for color-renderable, color-filterable formats, so depth
     * and stencil textures are rejected here instead of issuing an invalid native command.
     *
     * @return true when the native mipmap command was encoded, false when this texture or encoder
     *         state cannot use Metal's native mipmap path
     */
    public boolean generateMipmaps(final GpuTexture texture) {
        if (currentRenderPass != null
                || !(texture instanceof MetalGpuTexture metalTexture)
                || texture.isClosed()
                || texture.getMipLevels() <= 1
                || !supportsNativeMipmaps(texture.getFormat())) {
            return false;
        }

        flushPendingClear(metalTexture);
        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.generateMipmapsForTexture(metalTexture.nativeHandle());
        endEncoder();
        return true;
    }

    /**
     * Metal's native mipmap command requires both filtering and color-rendering support. Keep this
     * list at the Apple7/M1 common denominator because Metallum targets every Apple Silicon Mac and
     * does not yet query the runtime GPU family. Full-range integer formats are color-renderable but
     * not filterable, while R/RG/RGBA32Float only becomes filterable on Apple9, so neither group is
     * safe for the backend-wide native path.
     */
    private static boolean supportsNativeMipmaps(final com.mojang.blaze3d.GpuFormat format) {
        return switch (format) {
            case R8_UNORM, R8_SNORM,
                    R16_UNORM, R16_SNORM, R16_FLOAT,
                    RG8_UNORM, RG8_SNORM,
                    RG16_UNORM, RG16_SNORM, RG16_FLOAT,
                    RGBA8_UNORM, RGBA8_SNORM,
                    RGB10A2_UNORM, RG11B10_FLOAT,
                    RGBA16_UNORM, RGBA16_SNORM, RGBA16_FLOAT -> true;
            default -> false;
        };
    }

    /**
     * Clears a writable Metal texture to numeric zero with a typed compute kernel.
     * <p>
     * The dimensionality is supplied by the optional backend caller because Minecraft's public
     * {@link GpuTexture} facade stores true 3D depth in the same integer used for array layers.
     */
    public boolean clearStorageTexture(final GpuTexture texture, final int dimensions) {
        if (currentRenderPass != null
                || !(texture instanceof MetalGpuTexture metalTexture)
                || texture.isClosed()
                || dimensions < 1
                || dimensions > 3) {
            return false;
        }

        String formatName = texture.getFormat().name();
        MTLStorageTexturePipelines.ScalarKind scalarKind = formatName.endsWith("_UINT")
                ? MTLStorageTexturePipelines.ScalarKind.UINT
                : formatName.endsWith("_SINT")
                    ? MTLStorageTexturePipelines.ScalarKind.SINT
                    : MTLStorageTexturePipelines.ScalarKind.FLOAT;
        long width = texture.getWidth(0);
        long height = dimensions == 1 ? 1L : texture.getHeight(0);
        long depth = dimensions == 3 ? texture.getDepthOrLayers() : 1L;

        metalTexture.markContentsDirty();
        MTLComputeCommandEncoder compute = computeCommandEncoder();
        MTLStorageTexturePipelines.clearZero(
                device.metalDevice(),
                compute,
                metalTexture.nativeHandle(),
                scalarKind,
                dimensions,
                width,
                height,
                depth
        );
        endEncoder();
        return true;
    }

    /**
     * Copies one exact 1D/2D/3D region between storage textures using Metal's blit encoder.
     * Overlap is intentionally not solved here: callers that shift a texture in place must supply
     * a separate scratch texture and perform two non-overlapping copies.
     */
    public boolean copyStorageTextureRegion(
            final GpuTexture source,
            final GpuTexture destination,
            final int sourceX,
            final int sourceY,
            final int sourceZ,
            final int destinationX,
            final int destinationY,
            final int destinationZ,
            final int width,
            final int height,
            final int depth
    ) {
        if (currentRenderPass != null
                || !(source instanceof MetalGpuTexture sourceTexture)
                || !(destination instanceof MetalGpuTexture destinationTexture)
                || source.isClosed()
                || destination.isClosed()
                || width <= 0
                || height <= 0
                || depth <= 0) {
            return false;
        }

        destinationTexture.markContentsDirty();
        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromTextureToTexture(
                sourceTexture.nativeHandle(),
                0L,
                0L,
                sourceX,
                sourceY,
                sourceZ,
                width,
                height,
                depth,
                destinationTexture.nativeHandle(),
                0L,
                0L,
                destinationX,
                destinationY,
                destinationZ
        );
        endEncoder();
        return true;
    }

    void endEncoder() {
        endEncoder(null);
    }

    /**
     * Ends the current encoder and tells the frame probe why it did, for the two boundaries that are
     * a fact about the frame rather than housekeeping: a changed pass configuration, and the frame
     * boundary itself, which ends whatever encoder is still open. Every other caller ends one to
     * switch encoder kind or to materialize a clear, and passes no reason because the probe does not
     * count those.
     */
    void endEncoder(@Nullable final EncoderEnd reason) {
        if (currentEncoder != null) {
            if (reason != null) {
                MetalFrameProbe.encoderEnded(reason);
            }
            if (currentEncoder instanceof MTLRenderCommandEncoder renderEncoder) {
                renderEncoder.updateFence(fence, MTLRenderStages.VertexAndFragment);
                if (currentRenderPass != null) {
                    currentRenderPass.invalidateEncoderState();
                }
            } else if (currentEncoder instanceof MTLBlitCommandEncoder blitEncoder) {
                blitEncoder.updateFence(fence);
            } else if (currentEncoder instanceof MTLComputeCommandEncoder computeEncoder) {
                computeEncoder.updateFence(fence);
            }
            currentEncoder.endEncoding();
            currentEncoder = null;
        }
        renderColorAttachments = new MemorySegment[0];
        renderDepthAttachment = MemorySegment.NULL;
        renderContents = new AttachmentContents[0];
        storageUnordered = false;
    }

    @Override
    public @NonNull TransientMemory transientMemory() {
        return transientMemory;
    }

    @Override
    public void submit() {
        InFlight toClose = null;
        if (commandBuffer != null) {
            submitRenderPass();
            endEncoder(MetalFrameProbe.EncoderEnd.SUBMITTED);

            int slot = (int) (currentSubmitIndex % MAX_SUBMITS_IN_FLIGHT);
            submitSemaphores[slot].drainPermits();
            commandBuffer.commitWithCompletionBlock(submitSignalBlocks[slot]);

            // The frame boundary the probe counts at, and only inside this block: a commit is what
            // makes a frame, while the surface's present-time submit finds no command buffer and
            // commits nothing, so counting every submit() would count each drawn frame twice.
            MetalFrameProbe.frameSubmitted();

            lastCommittedSubmitIndex = currentSubmitIndex;
            toClose = inFlight[slot];
            inFlight[slot] = new InFlight(currentSubmitIndex, commandBuffer);
            commandBuffer = null;
        }
        currentSubmitIndex++;

        if (!awaitSubmitCompletion(currentSubmitIndex - MAX_SUBMITS_IN_FLIGHT, 5000L)) {
            throw new IllegalStateException("5s timeout reached when waiting for Metal submit completion");
        }

        if (toClose != null) {
            // A command buffer that failed completes exactly like one that drew, so the frame's own
            // outcome is read here rather than assumed: the error state and the two driver times that
            // stay at zero are the only signs a caller gets.
            String failure = toClose.buffer.errorDescription();
            if (!"none".equals(failure)) {
                Metallum.LOGGER.error("A command buffer of this frame failed: {}", failure);
            }

            // The submit this slot held three frames ago, whose semaphore the wait above has already
            // seen signalled, so the driver's own answer for how long the GPU ran it is available:
            // Apple says both times "remain 0.0 until the GPU finishes running the command buffer".
            // Asked behind the guard so that an unarmed session pays the boolean and not two messages.
            if (MetalFrameProbe.armed()) {
                MetalFrameProbe.gpuFrame(toClose.buffer.gpuMillis());
            }
            toClose.buffer.close();
        }

        transientMemory.rotate();
        destroyQueue.rotate();
    }

    MTLRenderCommandEncoder renderCommandEncoder(
            final MetalGpuTextureView[] colorTextureViews,
            @Nullable final MetalGpuTextureView depthTextureView,
            final int viewportWidth,
            final int viewportHeight,
            final Vector4fc[] clearColors,
            @Nullable final AttachmentContents[] contents,
            @Nullable final Double clearDepth
    ) {
        if (colorTextureViews.length > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalArgumentException(
                    "Metal supports at most " + MAX_COLOR_ATTACHMENTS + " color attachments, got " + colorTextureViews.length
            );
        }
        if (clearColors.length != colorTextureViews.length) {
            throw new IllegalArgumentException(
                    "Color attachment and clear-value counts differ: " + colorTextureViews.length + " != " + clearColors.length
            );
        }

        MemorySegment[] colorAttachments = new MemorySegment[colorTextureViews.length];
        boolean hasColorClear = false;
        for (int index = 0; index < colorTextureViews.length; index++) {
            MetalGpuTextureView colorTextureView = colorTextureViews[index];
            colorAttachments[index] = colorTextureView == null ? MemorySegment.NULL : colorTextureView.nativeHandle();
            hasColorClear |= clearColors[index] != null;
        }
        MemorySegment depthAttachment = depthTextureView == null ? MemorySegment.NULL : depthTextureView.nativeHandle();
        boolean hasClear = hasColorClear || clearDepth != null;
        AttachmentContents[] stated = AttachmentContents.resolve(contents, colorTextureViews.length);

        // A clear already refuses the reuse below, so the actions an encoder was created with only
        // matter for the passes that carry no clear - and for those the answers have to match too.
        if (!hasClear
                && currentEncoder instanceof MTLRenderCommandEncoder enc
                && MetalPipelineSupport.sameHandles(renderColorAttachments, colorAttachments)
                && MetalPipelineSupport.sameHandle(renderDepthAttachment, depthAttachment)
                && Arrays.equals(renderContents, stated)) {
            return enc;
        }

        endEncoder(MetalFrameProbe.EncoderEnd.PASS_CONFIGURATION_CHANGED);
        // Each attachment's byte size comes from the texture the view wraps, because the format is
        // the only place it exists and the MTL layer below holds handles rather than formats.
        int[] colorPixelSizes = new int[colorTextureViews.length];
        for (int index = 0; index < colorTextureViews.length; index++) {
            MetalGpuTextureView colorTextureView = colorTextureViews[index];
            colorPixelSizes[index] = colorTextureView == null ? 0 : ((MetalGpuTexture) colorTextureView.texture()).pixelSize();
        }
        int depthPixelSize = depthTextureView == null ? 0 : ((MetalGpuTexture) depthTextureView.texture()).pixelSize();
        MetalFrameProbe.encoderOpened(0);
        MTLRenderCommandEncoder encoder = commandBuffer().makeRenderCommandEncoder(
                colorAttachments,
                clearColors,
                stated,
                depthAttachment,
                clearDepth,
                viewportWidth,
                viewportHeight,
                colorPixelSizes,
                depthPixelSize
        );
        encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);
        currentEncoder = encoder;
        renderColorAttachments = colorAttachments.clone();
        renderDepthAttachment = depthAttachment;
        renderContents = stated;
        return encoder;
    }

    /**
     * Says what the next render pass created on this encoder needs of each of its colour
     * attachments, by slot.
     * <p>
     * The public descriptor carries how an attachment is loaded and nothing about what becomes of it
     * when the pass ends, which on a tile-based GPU is the other half of the same bill. So a pass may
     * say, per slot, whether anything reads its contents afterwards and whether the pass writes every
     * pixel of them anyway; see {@link AttachmentContents} for why the answer nobody gives is the one
     * that changes nothing.
     * <p>
     * Read once and cleared by {@code createRenderPass}, so what is set here belongs to one pass and
     * cannot leak onto the next. No Metallum pass sets it today: every render pass this backend
     * creates for itself goes through the same call and takes the default.
     *
     * @param contents one entry per colour attachment slot, or null to say nothing. A shorter array,
     *                 or a null slot in it, says nothing about the slots it does not reach
     */
    public void setNextPassContents(@Nullable final AttachmentContents[] contents) {
        this.nextPassContents = contents;
    }

    /**
     * Says whether the next render pass created on this encoder may read a storage image written
     * since the live one opened.
     * <p>
     * Read once and reset to true by {@code createRenderPass}, so a pass nobody describes asks for
     * the boundary rather than going without it - the one direction a wrong answer may not take,
     * because an unordered read of an untracked write is a wrong image rather than a slower frame.
     *
     * @param reads true where the pass reads one, or where that is not known
     */
    public void setNextPassReadsStorageImage(final boolean reads) {
        this.nextPassReadsStorageImage = reads;
    }

    @Override
    public @NonNull RenderPassBackend createRenderPass(final RenderPassDescriptor descriptor) {
        List<RenderPassDescriptor.Attachment<Optional<Vector4fc>>> colorAttachments = descriptor.colorAttachments();
        if (colorAttachments.size() > MAX_COLOR_ATTACHMENTS) {
            throw new IllegalArgumentException(
                    "Render pass declares " + colorAttachments.size()
                            + " color attachment slots, Metal supports at most " + MAX_COLOR_ATTACHMENTS
            );
        }

        GpuTextureView[] colorTextures = new GpuTextureView[colorAttachments.size()];
        Vector4fc[] colorClears = new Vector4fc[colorAttachments.size()];
        for (int index = 0; index < colorAttachments.size(); index++) {
            RenderPassDescriptor.Attachment<Optional<Vector4fc>> colorAttachment = colorAttachments.get(index);
            if (colorAttachment == null) {
                continue;
            }

            GpuTextureView colorTexture = colorAttachment.textureView();
            MetalGpuTexture colorTex = (MetalGpuTexture) colorTexture.texture();
            Vector4fc colorClear = colorAttachment.clearValue().orElse(null);
            Vector4fc pendingColor = pendingColorClears.get(colorTex);
            if (pendingColor != null && colorClear == null) {
                if (isFullTextureView(colorTexture)) {
                    pendingColorClears.remove(colorTex);
                    colorClear = pendingColor;
                } else {
                    flushPendingClear(colorTex);
                }
            } else {
                pendingColorClears.remove(colorTex);
            }
            colorTex.markContentsDirty();
            colorTextures[index] = colorTexture;
            colorClears[index] = colorClear;
        }

        RenderPassDescriptor.Attachment<OptionalDouble> depthAttachment = descriptor.depthAttachment();
        GpuTextureView depthTexture = null;
        Double depthClear = null;
        if (depthAttachment != null) {
            depthTexture = depthAttachment.textureView();
            OptionalDouble attachmentClear = depthAttachment.clearValue();
            depthClear = attachmentClear.isPresent() ? attachmentClear.getAsDouble() : null;

            MetalGpuTexture metalDepth = (MetalGpuTexture) depthTexture.texture();
            Double pendingDepth = pendingDepthClears.get(metalDepth);
            if (pendingDepth != null && depthClear == null) {
                if (isFullTextureView(depthTexture)) {
                    pendingDepthClears.remove(metalDepth);
                    depthClear = pendingDepth;
                } else {
                    flushPendingClear(metalDepth);
                }
            } else {
                pendingDepthClears.remove(metalDepth);
            }
            metalDepth.markContentsDirty();
        }

        assert descriptor.renderArea != null;
        RenderPass.RenderArea renderArea = descriptor.renderArea;
        // Taken before the pass is built, so what this pass was told cannot be read by the next one.
        AttachmentContents[] passContents = this.nextPassContents;
        this.nextPassContents = null;
        boolean readsStorageImage = this.nextPassReadsStorageImage;
        this.nextPassReadsStorageImage = true;
        // The boundary is owed here rather than at the pass that wrote, because only this pass knows
        // whether it reads what was written. Ending the encoder is what makes the fence chain order
        // the two, and a pass that reads no storage image does not need it: the whole cost of the
        // boundary - every attachment reloaded and stored again - is paid for nothing there.
        if (this.storageUnordered && readsStorageImage) {
            endEncoder();
        }

        this.storageUnordered = false;
        MetalRenderPass renderPass = new MetalRenderPass(
                device,
                this,
                descriptor.label(),
                colorTextures,
                depthTexture,
                renderArea,
                colorClears,
                passContents,
                depthClear
        );
        currentRenderPass = renderPass;
        renderPass.pushDebugGroup(descriptor.label());
        return renderPass;
    }

    @Override
    public void submitRenderPass() {
        if (currentRenderPass != null) {
            boolean graphicsStorageImageWrites = currentRenderPass.hasGraphicsStorageImageWrites();
            currentRenderPass.materializePendingClear();
            currentRenderPass.popDebugGroup();
            currentRenderPass = null;

            // Storage-image writes are untracked, so something that reads one afterwards has to be
            // ordered against it by the fence chain, and that chain is only meaningful across an
            // encoder boundary. Whether the boundary is owed is not decided here: it is owed by the
            // pass that reads, and that pass is the next one to be created.
            if (graphicsStorageImageWrites) {
                this.storageUnordered = true;
            }
        }
    }

    void presentTextureToDrawable(final CAMetalLayer layer, final GpuTextureView textureView) {
        MetalGpuTexture source = (MetalGpuTexture) textureView.texture();
        flushPendingClear(source);
        submitRenderPass();
        // The frame's own encoder ends here, not at submit(): the drawable blit below is encoded
        // through the MTL layer, so by the time the frame is submitted there is nothing left to end
        // and the probe's submit-time endEncoder() finds no encoder. Both sites carry the same
        // reason because the boundary is the frame's, not the call's.
        endEncoder(MetalFrameProbe.EncoderEnd.SUBMITTED);
        MTLCommandBuffer commandBuffer = commandBuffer();
        commandBuffer.encodePresentTextureToDrawable(layer, source.nativeHandle(), fence);
    }

    @Override
    public void clearColorTexture(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor) {
        pendingColorClears.put((MetalGpuTexture) colorTexture, new Vector4f(clearColor));
    }

    @Override
    public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final @NonNull Vector4fc clearColor, final @NonNull GpuTexture depthTexture, final double clearDepth) {
        MetalGpuTexture color = (MetalGpuTexture) colorTexture;
        MetalGpuTexture depth = (MetalGpuTexture) depthTexture;
        pendingColorClears.put(color, new Vector4f(clearColor));
        pendingDepthClears.put(depth, clearDepth);
    }

    @Override
    public void clearColorAndDepthTextures(
            final @NonNull GpuTexture colorTexture,
            final @NonNull Vector4fc clearColor,
            final @NonNull GpuTexture depthTexture,
            final double clearDepth,
            final int regionX,
            final int regionY,
            final int regionWidth,
            final int regionHeight
    ) {
        MetalGpuTexture color = (MetalGpuTexture) colorTexture;
        MetalGpuTexture depth = (MetalGpuTexture) depthTexture;
        Vector4fc clearColorCopy = new Vector4f(clearColor);
        if (isFullTextureRegion(color, depth, regionX, regionY, regionWidth, regionHeight)) {
            pendingColorClears.put(color, clearColorCopy);
            pendingDepthClears.put(depth, clearDepth);
            return;
        }
        color.markContentsDirty();
        depth.markContentsDirty();
        submitRenderPass();
        endEncoder();
        commandBuffer().clearColorDepthTexturesRegion(
                color.nativeHandle(),
                clearColorCopy,
                depth.nativeHandle(),
                clearDepth,
                regionX,
                regionY,
                regionWidth,
                regionHeight,
                fence
        );
    }

    @Override
    public void clearDepthTexture(final @NonNull GpuTexture depthTexture, final double clearDepth) {
        pendingDepthClears.put((MetalGpuTexture) depthTexture, clearDepth);
    }

    @Override
    public void writeToBuffer(final GpuBufferSlice destination, final ByteBuffer data) {
        MetalGpuBuffer buffer = (MetalGpuBuffer) destination.buffer();
        int length = data.remaining();

        if (buffer.isDynamic()) {
            orphanWrite(buffer, destination.offset(), data);
            return;
        }

        GpuBufferSlice staging = transientMemory.uploadStaging(data, 4L, GpuBuffer.USAGE_COPY_SRC);
        MetalGpuBuffer stagingBuffer = (MetalGpuBuffer) staging.buffer();

        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromBufferToBuffer(
                stagingBuffer.metalBuffer(),
                staging.offset(),
                buffer.metalBuffer(),
                destination.offset(),
                length
        );
        endEncoder();
    }

    private void orphanWrite(final MetalGpuBuffer buffer, final long offset, final ByteBuffer data) {
        long size = buffer.allocationSize();
        MTLBuffer old = buffer.metalBuffer();
        MTLBuffer fresh = acquireDynamicBacking(size, buffer.resourceOptions());
        ByteBuffer freshStorage = ObjC.byteBufferView(fresh.contents(), size).order(ByteOrder.nativeOrder());

        if (offset != 0 || data.remaining() != buffer.size()) {
            ByteBuffer previous = buffer.currentStorage();
            previous.clear();
            freshStorage.duplicate().put(previous);
        }

        ByteBuffer dst = freshStorage.duplicate().order(ByteOrder.nativeOrder());
        dst.position(Math.toIntExact(offset));
        dst.put(data.duplicate());

        buffer.swapBacking(fresh, freshStorage);
        recycleDynamicBacking(old, size);
    }

    private MTLBuffer acquireDynamicBacking(final long size, final long resourceOptions) {
        ArrayDeque<MTLBuffer> bucket = dynamicBackingPool.get(size);
        if (bucket != null && !bucket.isEmpty()) {
            return bucket.pop();
        }
        return device.metalDevice().newBuffer(size, resourceOptions);
    }

    private void recycleDynamicBacking(final MTLBuffer buffer, final long size) {
        queueForDestroy(() -> dynamicBackingPool.computeIfAbsent(size, _ -> new ArrayDeque<>()).push(buffer));
    }

    @Override
    public void copyToBuffer(final GpuBufferSlice source, final GpuBufferSlice target) {
        MetalGpuBuffer sourceBuffer = (MetalGpuBuffer) source.buffer();
        MetalGpuBuffer targetBuffer = (MetalGpuBuffer) target.buffer();
        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromBufferToBuffer(
                sourceBuffer.metalBuffer(),
                source.offset(),
                targetBuffer.metalBuffer(),
                target.offset(),
                source.length()
        );
        endEncoder();
    }

    @Override
    public void writeToTexture(
            final @NonNull GpuTexture destination,
            final @NonNull ByteBuffer source,
            final int mipLevel,
            final int depthOrLayer,
            final int destX,
            final int destY,
            final int width,
            final int height
    ) {
        MetalGpuTexture metalDst = (MetalGpuTexture) destination;
        flushPendingClearForWrite(metalDst);

        int pixelSize = metalDst.pixelSize();
        int rowBytes = width * pixelSize;
        int bytesPerImage = rowBytes * height;
        GpuBufferSlice slice = transientMemory.uploadStaging(source.duplicate().limit(bytesPerImage), pixelSize, GpuBuffer.USAGE_COPY_SRC);

        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromBufferToTexture(
                ((MetalGpuBuffer) slice.buffer()).metalBuffer(),
                slice.offset(),
                rowBytes,
                bytesPerImage,
                width,
                height,
                metalDst.nativeHandle(),
                depthOrLayer,
                mipLevel,
                destX,
                destY
        );
        endEncoder();
    }

    @Override
    public void copyBufferToTexture(
            final @NonNull GpuBufferSlice source,
            final int sourceX,
            final int sourceY,
            final int sourceWidth,
            final int sourceHeight,
            final @NonNull GpuTexture destination,
            final int destinationX,
            final int destinationY,
            final int copyWidth,
            final int copyHeight,
            final int mipLevel,
            final int arrayLayer
    ) {
        MetalGpuTexture metalDst = (MetalGpuTexture) destination;
        flushPendingClearForWrite(metalDst);

        int texelSize = destination.getFormat().blockSize();
        long skipBytes = (sourceX + (long) sourceY * sourceWidth) * texelSize;
        long rowBytes = (long) sourceWidth * texelSize;

        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromBufferToTexture(
                ((MetalGpuBuffer) source.buffer()).metalBuffer(),
                source.offset() + skipBytes,
                rowBytes,
                rowBytes * sourceHeight,
                copyWidth,
                copyHeight,
                metalDst.nativeHandle(),
                arrayLayer,
                mipLevel,
                destinationX,
                destinationY
        );
        endEncoder();
    }

    @Override
    public void copyTextureToBuffer(final @NonNull GpuTexture source, final @NonNull GpuBuffer destination, final long offset, final @NonNull Runnable callback, final int mipLevel) {
        copyTextureToBuffer(source, destination, offset, callback, mipLevel, 0, 0, source.getWidth(mipLevel), source.getHeight(mipLevel));
    }

    @Override
    public void copyTextureToBuffer(
            final @NonNull GpuTexture source,
            final @NonNull GpuBuffer destination,
            final long offset,
            final @NonNull Runnable callback,
            final int mipLevel,
            final int x,
            final int y,
            final int width,
            final int height
    ) {
        MetalGpuTexture texture = (MetalGpuTexture) source;
        flushPendingClear(texture);
        MetalGpuBuffer buffer = (MetalGpuBuffer) destination;
        int bytesPerPixel = texture.pixelSize();
        int rowBytes = width * bytesPerPixel;
        int bytesPerImage = rowBytes * height;

        MTLBlitCommandEncoder blit = blitCommandEncoder();
        blit.copyFromTextureToBuffer(
                texture.nativeHandle(),
                0,
                mipLevel,
                x,
                y,
                width,
                height,
                buffer.metalBuffer(),
                offset,
                rowBytes,
                bytesPerImage
        );

        endEncoder();
        queueForDestroy(callback);
    }

    @Override
    public void copyTextureToTexture(
            final @NonNull GpuTexture source,
            final @NonNull GpuTexture destination,
            final int mipLevel,
            final int destX,
            final int destY,
            final int sourceX,
            final int sourceY,
            final int width,
            final int height
    ) {
        MetalGpuTexture srcTexture = (MetalGpuTexture) source;
        MetalGpuTexture dstTexture = (MetalGpuTexture) destination;
        flushPendingClear(srcTexture);
        flushPendingClearForWrite(dstTexture);
        MTLBlitCommandEncoder blit = blitCommandEncoder();
        // Counted because nothing else in the probe sees a blit, and the copies a pack's kept targets
        // need at the end of a frame - the 2D texture-to-texture copies this is - are the largest
        // thing a frame moves outside a pass.
        MetalFrameProbe.blit(width, height, srcTexture.pixelSize());
        blit.copyFromTextureToTexture(
                srcTexture.nativeHandle(),
                0,
                mipLevel,
                sourceX,
                sourceY,
                width,
                height,
                dstTexture.nativeHandle(),
                0,
                mipLevel,
                destX,
                destY
        );
        endEncoder();
    }

    @Override
    public @NonNull GpuFence createFence() {
        return new MetalFence(this, currentSubmitIndex);
    }

    void queueForDestroy(final Runnable destroyAction) {
        destroyQueue.add(destroyAction);
    }

    boolean awaitSubmitCompletion(final long submitIndex, final long timeoutMs) {
        if (submitIndex == currentSubmitIndex) {
            if (timeoutMs == 0L) {
                return false;
            }
            throw new IllegalStateException("Cannot wait on a fence for the current submit");
        }
        int slot = (int) (submitIndex % MAX_SUBMITS_IN_FLIGHT);
        InFlight f = inFlight[slot];
        if (f != null && f.index == submitIndex) {
            Semaphore semaphore = submitSemaphores[slot];
            try {
                if (!semaphore.tryAcquire(Math.max(timeoutMs, 0L), TimeUnit.MILLISECONDS)) {
                    return false;
                }
                semaphore.release();
                return true;
            } catch (InterruptedException e) {
                throw new IllegalStateException("Render thread interrupted while waiting for Metal submit completion", e);
            }
        }
        return true;
    }

    void close() {
        submitRenderPass();
        endEncoder();
        for (int slot = 0; slot < inFlight.length; slot++) {
            InFlight f = inFlight[slot];
            if (f != null) {
                f.buffer.close();
                inFlight[slot] = null;
            }
        }
        if (commandBuffer != null) {
            commandBuffer.close();
            commandBuffer = null;
        }
        transientMemory.close();
        device.queueResourceRelease(fence.handle());
        destroyQueue.close();
        for (ArrayDeque<MTLBuffer> bucket : dynamicBackingPool.values()) {
            for (MTLBuffer buffer : bucket) {
                ObjC.release(buffer.handle());
            }
        }
        dynamicBackingPool.clear();
    }

    void waitForSubmittedGpuWork() {
        if (commandBuffer != null || currentRenderPass != null || currentEncoder != null) {
            submit();
        } else {
            endEncoder();
        }
        if (lastCommittedSubmitIndex >= 0L) {
            awaitSubmitCompletion(lastCommittedSubmitIndex, Long.MAX_VALUE);
        }
    }

    /**
     * Whether this device can bring a scaled picture back with MetalFX.
     * <p>
     * Asked by the pack-facing side through its own capability, and answered from the device the way
     * {@link MetalFx} answers everything: Apple's own support question, asked once, never a version.
     */
    public boolean metalFxAvailable() {
        return MetalFx.spatialSupported(device.metalDeviceHandle());
    }

    /**
     * Encodes one MetalFX spatial upscale of a smaller picture into a larger one.
     * <p>
     * The scaler's encode is a command of its own rather than a render pass, so nothing of this engine's
     * may still be open when it goes in - an encoder left open would order the upscale before work it has
     * to follow - and the scaler itself is kept by {@link MetalFx} for the configuration it was made for.
     *
     * @param from          the texture drawn at the scaled size
     * @param to            the texture the picture is brought back into
     * @param contentWidth  how much of {@code from} really holds this frame
     * @param contentHeight the same, in rows
     * @return whether the encode happened; false leaves the caller on whatever it does without this
     */
    public boolean scaleWithMetalFx(
            final @NonNull GpuTextureView from,
            final @NonNull GpuTextureView to,
            final int contentWidth,
            final int contentHeight
    ) {
        if (!(from.texture() instanceof MetalGpuTexture color)
                || !(to.texture() instanceof MetalGpuTexture output)) {
            return false;
        }

        endEncoder();
        return MetalFx.scale(device.metalDeviceHandle(), commandBuffer().handle(), fence.handle(), color,
                output, contentWidth, contentHeight);
    }

    @Override
    public void writeTimestamp(final @NonNull GpuQueryPool pool, final int index) {
        if (pool instanceof MetalGpuQueryPool metalPool && index >= 0 && index < pool.size()) {
            metalPool.setValue(index, device.getTimestampNow());
        }
    }

    private void flushPendingClearForWrite(final MetalGpuTexture texture) {
        flushPendingClear(texture);
        texture.markContentsDirty();
    }

    void flushPendingClear(final MetalGpuTexture texture) {
        Vector4fc colorClear = pendingColorClears.remove(texture);
        Double depthClear = pendingDepthClears.remove(texture);
        if (colorClear == null && depthClear == null) {
            return;
        }

        if (texture.clearIsRedundant(colorClear, depthClear)) {
            return;
        }

        endEncoder();
        MetalFrameProbe.encoderOpened(3);
        MTLRenderCommandEncoder encoder = commandBuffer().makeRenderCommandEncoder(
                colorClear != null ? texture.nativeHandle() : MemorySegment.NULL,
                colorClear,
                depthClear != null ? texture.nativeHandle() : MemorySegment.NULL,
                depthClear,
                1.0, 1.0,
                texture.pixelSize(),
                texture.pixelSize()
        );
        encoder.waitForFence(fence, MTLRenderStages.VertexAndFragment);
        currentEncoder = encoder;
        texture.recordMaterializedClear(colorClear, depthClear);
    }

    private static boolean isFullTextureView(final GpuTextureView textureView) {
        return textureView.baseMipLevel() == 0
                && textureView.mipLevels() >= textureView.texture().getMipLevels()
                && textureView.texture().getDepthOrLayers() == 1;
    }

    private static boolean isFullTextureRegion(
            final MetalGpuTexture color,
            final MetalGpuTexture depth,
            final int x,
            final int y,
            final int width,
            final int height
    ) {
        return x == 0
                && y == 0
                && width == color.getWidth(0)
                && height == color.getHeight(0)
                && width == depth.getWidth(0)
                && height == depth.getHeight(0);
    }

    private record InFlight(long index, MTLCommandBuffer buffer) {
    }
}
