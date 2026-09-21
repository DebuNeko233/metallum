package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.CAMetalDrawable;
import com.metallum.mtl.MTLBuffer;
import com.metallum.mtl.MTLFXSpatialScalerDescriptor;
import com.metallum.mtl.MTLStorageMode;
import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.CAMetalLayer;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLTexture;
import com.metallum.objc.ObjC;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
import com.metallum.mtl.metal4.MTL4ComputeEncoder;
import com.metallum.mtl.metal4.MTL4FrameRing;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.mtl.metal4.Metal4Fx;
import com.metallum.mtl.metal4.MTL4ResidencySet;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalDestructionQueue;
import com.metallum.render.shared.MetalFrameEncoder;
import com.metallum.render.shared.MetalComputeTranslator;
import com.metallum.render.shared.MetalFrameComputeCommands;
import com.metallum.render.shared.MetalFrameExtras;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalFramePresentation;
import com.metallum.render.shared.MetalFrameResourceCommands;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalTransientMemory;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.buffers.GpuBufferSlice;
import com.mojang.blaze3d.systems.GpuQueryPool;
import com.mojang.blaze3d.systems.RenderPassBackend;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.RenderPassDescriptor;
import com.mojang.blaze3d.systems.TransientMemory;
import com.mojang.blaze3d.textures.GpuSampler;
import com.mojang.blaze3d.textures.GpuTexture;
import com.mojang.blaze3d.textures.GpuTextureView;
import com.mojang.blaze3d.buffers.GpuFence;
import org.jspecify.annotations.Nullable;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.joml.Vector4fc;
import org.jspecify.annotations.NonNull;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.JAVA_BYTE;

import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * The Metal 4 frame encoder: the object the executing generation's frame would be built from.
 * <p>
 * <strong>What exists is the frame's lifetime and the work a client frame encodes into it.</strong> This encoder
 * owns the ring {@code mtl.metal4.MTL4FrameRing} - the allocator slots, one command buffer and the shared event
 * whose values prove a slot free - the resources a frame cannot release yet, filed against the slot that will
 * prove them free, the render passes the game opens on the frame's command buffer, the clears and the copies,
 * and the present triangle drawn into the layer's next drawable. That is the migration's sections 30 to 32 asked
 * for in one object: begin a frame, choose a slot, wait for it, reset it, begin, encode, end, commit
 * <em>once</em>, retire.
 * <p>
 * <strong>What does not exist refuses by name.</strong> Every operation this path has not encoded - a timestamp,
 * a multi-draw, a clear of one colour and depth texture in one call - raises
 * {@link Metal4ExecutionProvider.Unimplemented} named for itself, or is answered by an absent contract a bridge
 * finds missing and falls back from. That is section 35's rule, and the same reason the provider's own refusals
 * carry a stage: an operation dropped in silence is a half frame, and a half frame is worse than a frame that
 * says it cannot run yet. The refusals are the work list, one per line, which is what a migration wants its gaps
 * to look like.
 * <p>
 * <strong>This class is reached only by a build that asks for it.</strong> The services hand out the provider of
 * the generation that is <em>executing</em>, and the device still states that generation as Metal 3 by default -
 * the cold capability probe has failed intermittently, which is what keeps AUTO off Metal 4 - so this encoder is
 * constructed by a forced {@code -Dmetallum.execution=metal4} session and is EXPERIMENTAL there. Its classes are
 * package-private for the same reason: the provider is the generation's public seam and the neutral interfaces
 * are what a caller holds.
 * <p>
 * <strong>Which optional contracts it carries.</strong> {@link MetalFramePresentation} is implemented, because
 * the surface asked for it by name and because the frame already owns everything a present needs: the queue, the
 * one command buffer, and the commit. {@link MetalFrameExtras} is implemented for the one question this path can
 * answer - what a pass said about its colour attachments' contents, which reaches the pass descriptor as a load
 * and a store action - and its other three members answer what is true of this generation rather than pretending:
 * the storage-image boundary it asks for is already encoded after every pass, and the scaler it asks about does
 * not exist until the Metal 4 MetalFX milestone. {@link MetalFrameResourceCommands} is carried for the same kind
 * of reason read the other way: mipmap generation is implemented on the frame's copy encoder - this command model
 * puts it there, and the texture is declared resident first - and the other two operations answer false, which is
 * the contract's own shape for a caller's fallback. {@link MetalFrameComputeCommands} is the newest of them, and
 * the one a pack's own kernels arrive through: a dispatch is a table filled from the compiled handle's bindings
 * and {@code dispatchThreadgroups:threadsPerThreadgroup:} on that same encoder - which is what closes the loop
 * that began with a storage texture having no contents. Omitting the contract altogether does not cost this path
 * those operations, it costs the capability dispatch as a whole. Measured: a pack's per-attachment statements
 * never reached this encoder, because the client decides whether to install its capability adapter from
 * {@code MetalFrameBridge.supports}, which asks whether the encoder carries <em>this</em> contract. A generation
 * that says "ask me" and answers no per operation keeps the half that does work.
 * <p>
 * <strong>The present is the frame's own.</strong> The picture is drawn into the layer's next drawable by a
 * present triangle encoded into <em>this frame's</em> command buffer, before {@link #submit()} commits it, and
 * the drawable is presented when that work has run. That is one queue, one commit and one presentation path,
 * which is what the migration's section 63 converges on: the present-only sidecar presents on a second queue and
 * orders the two with a shared event, which was the honest way to carry a picture before the frame could carry
 * one itself.
 */
@Environment(EnvType.CLIENT)
final class Metal4FrameEncoder implements MetalFrameEncoder, MetalFramePresentation, MetalFrameExtras,
        MetalFrameResourceCommands, MetalFrameComputeCommands {

    /** The zeroing kernels this frame dispatches for a storage texture, made once per device by whoever owns it. */
    private final com.metallum.mtl.metal4.MTL4StorageTexturePipelines storagePipelines;
    /**
     * The frame model the ring runs, which the migration's section 31 fixes at the present path's own depth.
     * <p>
     * Overridable with {@code -Dmetallum.metal4RingSlots=N} for one diagnostic purpose, and only that: with a
     * single slot a frame is committed only after the previous one has completed, so the commands a trace prints
     * immediately before the GPU's own fault report <em>are</em> the faulting submission's. The default is the
     * migration's number, and a session that does not ask gets it.
     */
    private static final int FRAMES_IN_FLIGHT = Math.max(1,
            Integer.getInteger("metallum.metal4RingSlots", MTL4FrameRing.FRAMES_IN_FLIGHT));

    private final MetalDevice device;
    /** The queue this encoder was given by the execution services, and which it owns and releases. */
    private MemorySegment queue = MemorySegment.NULL;
    /**
     * The presented drawable, copied out so the picture can be read where the display cannot be photographed.
     * <p>
     * {@code -Dmetallum.drawableReadback=true} turns the layer's {@code framebufferOnly} off (a drawable that is
     * framebuffer-only may not be copied from) and makes this path copy the drawable into a shared buffer after
     * the present pass. The copy belongs to the frame's own command buffer because the drawable is only valid
     * for the frame that took it, and the pixels are read at the next frame that reuses the slot - which is the
     * point the ring proved the slot's submission complete. A diagnostic, off by default, and the layer says so
     * at startup.
     */
    private final boolean drawableReadback = com.metallum.mtl.CAMetalLayer.readbackRequested();
    private final MTLBuffer[] readbackStaging;
    private final boolean[] readbackPending;
    private final long[] readbackWidth;
    private final long[] readbackHeight;
    /**
     * The other side of the same question: the picture this path's present triangle read, copied in the same
     * frame and read at the same point the drawable is.
     * <p>
     * The drawable's copy says what left the process; this one says what went in. A reading that has only the
     * drawable cannot tell a picture that was wrong from a present that changed it, and that is the whole
     * question when this road and the Metal 3 road disagree about the same frame.
     */
    private final MTLBuffer[] pictureStaging;
    private final boolean[] picturePending;
    private final long[] pictureWidth;
    private final long[] pictureHeight;
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
    /**
     * The drawables this frame presents into, taken when the surface said what it is presenting and presented by
     * {@link #submit()} once the frame is committed.
     * <p>
     * Taken, so presented: a drawable handed out by the layer and never presented is a drawable the layer cannot
     * hand out again, so every path out of this class - the commit and a close - presents what it holds. A list
     * rather than one field because the frame's commit is what makes a present legal, and a second present in one
     * frame must therefore wait for the same commit rather than present the first one early.
     */
    private final List<CAMetalDrawable> presentDrawables = new ArrayList<>();
    /** The one-texture, one-sampler table the present triangle reads the picture through, made once. */
    @Nullable
    private MTL4ArgumentTable presentTable;
    /**
     * The allocations this frame path reads <em>through addresses</em>, declared resident as they are bound.
     * <p>
     * The new command model binds buffers by GPU address - the argument table's {@code setAddress:atIndex:} and
     * the indexed draw's {@code indexBuffer} - and an address is not a reference, so nothing in the command
     * buffer keeps the allocation behind it resident. This machine's {@code MTL4RenderCommandEncoder.h} says
     * what to do: "Use an instance of {@code MTLResidencySet} to mark residency of the index buffer the
     * {@code indexBuffer} parameter references." Made on first use, owned by this encoder, released with it.
     */
    @Nullable
    private MTL4ResidencySet residency;
    /** What the set already holds, by the allocation's own address, so a frame does not add the same one twice. */
    private final Set<Long> declaredAllocations = new LinkedHashSet<>();
    /** Whether the set has been handed to the queue, which is once and not once a frame. */
    private boolean residencyAttached;
    private boolean residencyDirty;
    /** Whether a residency failure has been said already, so a device that cannot do it says so once. */
    private boolean residencyWarned;

    /**
     * What one frame cost, counted rather than guessed, and only while {@code -Dmetallum.metal4Trace} is on.
     * <p>
     * The point is to answer "why is this slow" with numbers from the path itself: passes, encoders, argument
     * tables, draws, residency declarations and the wall time between beginning a frame and submitting it. The
     * first forced Metal 4 client that rendered continuously did so at a fraction of the Metal 3 frame rate, and
     * the candidate list - a table per pass, an encoder per pass, a residency commit per frame - is exactly what
     * these counters separate.
     */
    private static final boolean TRACE = Boolean.getBoolean("metallum.metal4Trace");
    /**
     * Whether the per-frame counters are on and reported once every sixty frames.
     * <p>
     * Separate from the trace because the two answer different questions: the trace is what the frame encoded,
     * draw by draw, and this is what a frame cost. The counters are kept whenever either is on, so a trace run
     * also gets the summary.
     */
    private static final boolean STATS = Boolean.getBoolean("metallum.metal4FrameStats");
    /** Whether either diagnostic is on, which is what the counters themselves are gated on. */
    private static final boolean COUNTING = TRACE || STATS;
    private long statFrames;
    private long statPasses;
    private long statEncoders;
    private long statTables;
    private long statDraws;
    private long statIndexed;
    private long statResidency;
    private long statBeganAt;
    private long statFrameNanos;

    /** One pass ended, with what it encoded. */
    void statPass(final long draws, final long indexed) {
        if (!COUNTING) {
            return;
        }
        this.statPasses++;
        this.statDraws += draws;
        this.statIndexed += indexed;
    }

    /** One render encoder was opened, which is the descriptor-and-encoder cost a pass pays. */
    void statEncoder() {
        if (COUNTING) {
            this.statEncoders++;
        }
    }

    /** How many argument tables were made for one pass's tables. */
    void statTables(final long tables) {
        if (COUNTING) {
            this.statTables += tables;
        }
    }

    /** One allocation was added to the frame's residency set. */
    void statResidencyDeclaration() {
        if (COUNTING) {
            this.statResidency++;
        }
    }

    private boolean closed;

    /**
     * Whether this frame has already been committed, for the trace's frame-relative lines.
     * <p>
     * A copy that Vitrail asks for between frames - its contract for the history swap-back is "after the last
     * render pass of the frame" - lands in whichever command buffer is open when it is encoded, and the difference
     * between "inside the frame that needs it" and "inside the next one" is invisible in the copy itself. This flag
     * is set where the frame is committed and cleared where the next one begins, so a copy's trace line can say
     * which side of that boundary it fell on.
     */
    private boolean frameCommitted;

    /**
     * The pass currently open, so that a second {@code createRenderPass} before a {@code submitRenderPass} is a
     * named fault rather than two encoders writing into one command buffer with no order between them.
     */
    @org.jspecify.annotations.Nullable
    private Metal4RenderPass currentPass;

    /**
     * What the next pass was told about its colour attachments' contents, or null where it was told nothing.
     * <p>
     * The game's descriptor carries only clears, so these two facts arrive beside it through
     * {@link MetalFrameExtras} and are spent by the pass they were said for. Held rather than read once for the
     * same reason the Metal 3 encoder holds them: the caller states them <em>before</em> the pass exists, and
     * {@code createRenderPass} is where the statement becomes the pass's own.
     */
    @Nullable
    private AttachmentContents[] nextPassContents;

    /**
     * This generation's MetalFX spatial scaler path, or null where the device cannot have one.
     * <p>
     * Owned by the encoder rather than by a static keyed on a device, which is section 106's rule and the same
     * reason the storage pipelines beside it are: a second device in one process must not inherit the first one's
     * compiled scalers. Section 80 is the other half - the Metal 3 scalers live in their own cache and this path
     * holds nothing of theirs, because a scaler is a compiled pipeline and one generation's is not the other's.
     */
    private final Metal4Fx metalFx;

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
        this.queue = MemorySegment.ofAddress(queue);
        this.ring = MTL4FrameRing.create(nativeDevice, this.queue, FRAMES_IN_FLIGHT,
                "the Metal 4 frame encoder");
        this.transientMemory = new MetalTransientMemory(device, this.destroyQueue);
        // Owned by this encoder and not by a static keyed on a device: section 106's rule, and the reason a
        // second device in one process would otherwise inherit the first one's pipelines.
        this.storagePipelines = new com.metallum.mtl.metal4.MTL4StorageTexturePipelines(nativeDevice);
        // Asked once per session, and its answer is what `metalFxAvailable()` reports: a device that cannot make
        // a Metal 4 scaler sends the caller to its own scale road rather than to a wrong picture.
        this.metalFx = Metal4Fx.create(nativeDevice);
        this.deferred = new ArrayDeque[FRAMES_IN_FLIGHT];
        for (int slot = 0; slot < this.deferred.length; slot++) {
            this.deferred[slot] = new ArrayDeque<>();
        }
        this.readbackStaging = new MTLBuffer[FRAMES_IN_FLIGHT];
        this.readbackPending = new boolean[FRAMES_IN_FLIGHT];
        this.readbackWidth = new long[FRAMES_IN_FLIGHT];
        this.readbackHeight = new long[FRAMES_IN_FLIGHT];
        this.pictureStaging = new MTLBuffer[FRAMES_IN_FLIGHT];
        this.picturePending = new boolean[FRAMES_IN_FLIGHT];
        this.pictureWidth = new long[FRAMES_IN_FLIGHT];
        this.pictureHeight = new long[FRAMES_IN_FLIGHT];
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
            // Nothing was encoded, so there is nothing to commit - but a drawable may have been taken by a
            // present, and a drawable that is taken has to be presented whatever the frame did.
            presentAll();
            return;
        }
        commitResidency();
        if (!this.ring.endAndSubmit()) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: a frame could not be submitted - {}", this.ring.refusal());
        }
        this.frameCommitted = true;
        // The frame boundary, reported to the frame probe so that a forced Metal 4 session produces the same
        // window line a Metal 3 session does - which is what makes the two generations comparable in the
        // standard harness at all. Every counter the probe prints is fed from the places below.
        MetalFrameProbe.frameSubmitted();
        // After the commit, which is the half that comes second: the queue is told the drawable may be shown
        // once the work it just committed has run.
        presentAll();
        statFrame();
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
        long waitedFor = this.ring.submissions();
        long began = System.nanoTime();
        boolean complete = this.ring.awaitAll();
        // Said every time, and the teardown is why. This method runs on a resource reload and on the way out, so
        // two lines a cache clear is not noise - and a wait whose outcome is only reported when it fails cannot
        // answer "which wait timed out" when the same ring is waited on twice in a row and only one of them
        // fails. Measured: after `Minecraft`'s `Stopping!`, the encoder's own close-time wait was complete and
        // this one reported submission 3813 as a timeout, which is only readable at all if both say what they
        // waited for and what the ring looked like when they did.
        Metallum.LOGGER.info("Metal 4 frame encoder: waited {} ms for {} submission(s); complete={}, {}",
                (System.nanoTime() - began) / 1_000_000L, waitedFor, complete, this.ring.describe());
        if (!complete) {
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
        // This wait's own line, for the reason `waitForSubmittedGpuWork`'s has one: the device waits on the same
        // ring again straight after this returns, so a timeout in either place is only localised if both say what
        // they waited for and what the ring looked like when they did.
        long closingWaitedFor = this.ring.submissions();
        long closingBegan = System.nanoTime();
        boolean closingComplete = this.ring.awaitAll();
        Metallum.LOGGER.info("Metal 4 frame encoder: closing - waited {} ms for {} submission(s); complete={}, {}",
                (System.nanoTime() - closingBegan) / 1_000_000L, closingWaitedFor, closingComplete,
                this.ring.describe());
        if (!closingComplete) {
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
        // A drawable taken by a present is presented before the ring goes: the layer cannot hand out a drawable
        // that was never shown.
        presentAll();
        if (this.presentTable != null) {
            this.presentTable.close();
            this.presentTable = null;
        }
        this.storagePipelines.close();
        if (this.residency != null) {
            this.residency.close();
            this.residency = null;
        }
        // The scalers are compiled pipelines and the compiler is Metal 4's own object, so both go with the
        // encoder that made them rather than with a static the next device would find.
        if (this.metalFx != null) {
            this.metalFx.close();
        }
        for (int slot = 0; slot < this.readbackStaging.length; slot++) {
            if (this.readbackStaging[slot] != null) {
                ObjC.release(this.readbackStaging[slot].handle());
                this.readbackStaging[slot] = null;
            }
            if (this.pictureStaging[slot] != null) {
                ObjC.release(this.pictureStaging[slot].handle());
                this.pictureStaging[slot] = null;
            }
        }
        this.ring.close();
        // The queue came from the execution services and nothing else holds it, so this encoder is its owner and
        // releases it here - after the ring, which is the only thing that submits on it. The Metal 3 encoder does
        // the same with the queue the same seam hands it ("the queue is this encoder's own now"), and until this
        // line the Metal 4 path leaked one queue a session: measured by reading the two encoders' teardowns side
        // by side rather than by watching a number, which is what the ownership ledger is for.
        if (!ObjC.isNil(this.queue)) {
            ObjC.release(this.queue);
            this.queue = MemorySegment.NULL;
        }
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
            MetalFrameProbe.encoderOpened(1);
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
        if (STATS) {
            this.statBeganAt = System.nanoTime();
        }
        if (!this.ring.beginFrame()) {
            throw new IllegalStateException("the Metal 4 frame could not begin: " + this.ring.refusal());
        }
        this.frameCommitted = false;
        // The slot's previous submission is complete as of the wait inside beginFrame, so a drawable copied out
        // of that submission can be read now - the same fact the retire below is allowed to run on.
        reportDrawableReadback(this.ring.slot());
        reportPictureReadback(this.ring.slot());
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
        useResource(target.metalBuffer().handle());
        int length = data.remaining();
        GpuBufferSlice staging = this.transientMemory.uploadStaging(data, 4L, GpuBuffer.USAGE_COPY_SRC);
        useResource(bufferOf(staging.buffer()).metalBuffer().handle());
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
        useResource(bufferOf(staging.buffer()).metalBuffer().handle());
        useResource(texture.nativeHandle());
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
        useResource(bufferOf(source.buffer()).metalBuffer().handle());
        useResource(texture.nativeHandle());
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
        useResource(texture.nativeHandle());
        useResource(bufferOf(destination).metalBuffer().handle());
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
                                     final int mipLevel, final int destX, final int destY, final int sourceX,
                                     final int sourceY, final int width, final int height) {
        useResource(textureOf(source).nativeHandle());
        useResource(textureOf(destination).nativeHandle());
        if (TRACE) {
            Metallum.LOGGER.info("Metal 4 trace: texture copy 0x{} -> 0x{} {}x{} level {} from ({}, {}) to ({}, {})"
                            + " at frameBegun={} frameCommitted={}",
                    Long.toHexString(textureOf(source).nativeHandle().address()),
                    Long.toHexString(textureOf(destination).nativeHandle().address()), width, height, mipLevel,
                    sourceX, sourceY, destX, destY, this.ring.begun(), this.frameCommitted);
        }
        if (!copyEncoder().copyTextureRegion(textureOf(source).nativeHandle(), 0L, mipLevel, sourceX, sourceY, 0L,
                width, height, 1L, textureOf(destination).nativeHandle(), 0L, mipLevel, destX, destY, 0L)) {
            throw new IllegalStateException("the Metal 4 copy pass refused a " + width + "x" + height
                    + " texture-to-texture copy");
        }
        MetalFrameProbe.blit(width, height, textureOf(destination).pixelSize());
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

        // Taken before the pass is built, so what this pass was told cannot be read by the next one: a caller
        // that says nothing about a pass must get the pass it would have had, not the last one's answers.
        AttachmentContents[] passContents = this.nextPassContents;
        this.nextPassContents = null;

        Metal4RenderPass pass = new Metal4RenderPass(this, descriptor, passContents);
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

    // ---------------------------------------------------- what the bridges ask beyond the frame contract

    /**
     * What the pass about to be created needs of each colour attachment's contents, one answer per slot.
     * <p>
     * These are the two facts the public render-pass descriptor does not carry and a tile-based GPU pays for: a
     * pass that writes every pixel of an attachment need not have it loaded, and one whose contents nothing
     * reads afterwards need not have it stored. Only the pack side knows either, so they arrive here and are
     * spent by the pass they were said for - see {@code Metal4RenderPass}, which asks the one mapping in
     * {@code mtl.metal4.MTL4RenderEncoder} that turns them into load and store actions.
     * <p>
     * A caller that says nothing - no array, a short array, a null slot - leaves every slot {@code CARRIED},
     * the answer that changes nothing, because a wrong {@code DontCare} is a wrong image rather than a slower
     * frame.
     */
    @Override
    public void setNextPassContents(final @Nullable AttachmentContents[] contents) {
        this.nextPassContents = contents == null ? null : contents.clone();
    }

    /**
     * Whether the next pass may read a storage image written since the live encoder opened.
     * <p>
     * Accepted and already answered by construction rather than stored: every logical pass on this path ends by
     * encoding {@code barrierAfterStages:beforeQueueStages:} with the all-stages masks before its own native
     * encoder is ended, so the boundary this asks for has been encoded unconditionally by the time the next pass
     * exists. It is here because the interface asks it and a caller must not find the contract missing on the
     * road that does answer it; what it can still buy on this model is a <em>narrower</em> barrier, which is the
     * optimisation section 62 postpones until a counter says what the narrowing buys.
     */
    @Override
    public void setNextPassReadsStorageImage(final boolean reads) {
        // Deliberately empty, and not a forgotten body: the boundary this asks for is already encoded after every
        // pass by construction, so there is no state a later pass could read and no case where accepting the
        // statement changes what this path encodes.
    }

    /**
     * Whether this generation can scale with MetalFX.
     * <p>
     * The answer is the scaler path's own existence, which is Apple's class question plus a functional creation
     * of one scaler on this device (see {@link Metal4Fx#supported}). It used to be a literal false with the
     * migration's next milestone named as the reason; the reason is now the device's answer, and a device that
     * cannot is still sent to the caller's own scale road rather than to a picture nobody scaled.
     *
     * @see #scaleWithMetalFx(GpuTextureView, GpuTextureView, int, int)
     */
    @Override
    public boolean metalFxAvailable() {
        return !this.closed && this.metalFx != null;
    }

    /**
     * Encodes one MetalFX spatial upscale of a smaller picture into a larger one, on this frame's command buffer.
     * <p>
     * The scaler's encode is a command of its own rather than one of this engine's encoders, so no encoder of
     * ours may still be open when it goes in - an open one would order the upscale before work it has to follow.
     * Both textures are declared resident first, which is what the rest of this path does with anything it hands
     * over by handle.
     * <p>
     * <strong>Nothing here sets a fence, and the reason is measured rather than assumed.</strong> The Metal 3
     * path hands the scaler the frame's fence because its textures opt out of hazard tracking; Metal 4 has no
     * fence object at all in this engine - {@code Metal4Fence} says why - so what orders this encode against the
     * passes around it is the one command buffer's own encode order plus the all-stages barrier every pass ends
     * with. That claim is the frame's to test, and a render-scale session is where it is tested.
     */
    @Override
    public boolean scaleWithMetalFx(final @Nullable GpuTextureView from, final GpuTextureView to,
                                    final int contentWidth, final int contentHeight) {
        if (this.closed || this.metalFx == null || from == null || to == null
                || !(from.texture() instanceof MetalGpuTexture color)
                || !(to.texture() instanceof MetalGpuTexture output)) {
            return false;
        }

        if (this.currentPass != null) {
            submitRenderPass();
        }
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.endEncoding();
        }
        beginFrameIfNeeded();
        useResource(color.nativeHandle());
        useResource(output.nativeHandle());

        Metal4Fx.Configuration configuration = new Metal4Fx.Configuration(
                (int) MTLTexture.width(color.nativeHandle()), (int) MTLTexture.height(color.nativeHandle()),
                (int) MTLTexture.width(output.nativeHandle()), (int) MTLTexture.height(output.nativeHandle()),
                color.mtlPixelFormat().value, output.mtlPixelFormat().value,
                MTLFXSpatialScalerDescriptor.ColorProcessingMode.PERCEPTUAL);
        return this.metalFx.scale(this.ring.commandBuffer(), color.nativeHandle(), output.nativeHandle(),
                configuration, contentWidth, contentHeight);
    }

    // ------------------------------------------------- the resource operations this path has not reached

    /**
     * {@inheritDoc}
     * <p>
     * A mip chain is generated on the frame's copy encoder, which is where this command model puts it:
     * {@code MTL4ComputeCommandEncoder.h:543} declares {@code generateMipmapsForTexture:}, and the compute
     * encoder is what absorbed Metal 3's blit encoder. The texture is declared resident before the command,
     * because an undeclared resource makes a command of this kind do nothing at all rather than fail - measured,
     * with a buffer-to-texture copy and this very command.
     * <p>
     * False rather than a throw where the texture cannot have a chain generated: a texture of one level, a
     * closed one, one that is not this engine's, and a format the native command cannot filter are all answers
     * the caller's fallback is for. Answers false <em>by name</em> rather than doing nothing silently, which is
     * the same shape the rest of this class's refusals take.
     */
    @Override
    public boolean generateMipmaps(final GpuTexture texture) {
        if (this.closed || !(texture instanceof MetalGpuTexture metal) || texture.isClosed()
                || texture.getMipLevels() <= 1 || !supportsMipmapGeneration(texture.getFormat())) {
            return false;
        }
        // A pass the game still has open ends first: one encoder may be open on a command buffer, and the copy
        // encoder cannot be opened under a render pass that has not ended.
        if (this.currentPass != null) {
            submitRenderPass();
        }
        beginFrameIfNeeded();
        // The generation reads level 0, so it is ordered against everything this frame has already encoded -
        // including a copy out of staging memory that may be encoded but not yet visible.
        MTL4ComputeEncoder copies = copyEncoder();
        if (copies == null || !copies.open()) {
            return false;
        }
        useResource(metal.nativeHandle());
        boolean generated = copies.generateMipmaps(metal.nativeHandle());
        if (TRACE) {
            // Said under the diagnostic switch and not per session, because a pack may regenerate a chain every
            // frame: what this is for is answering "did the client's mipmaps go through this path at all",
            // which no counter separates from the copies the same encoder carries.
            Metallum.LOGGER.info("Metal 4 trace: generated the mip chain of a {}x{} texture: {}",
                    texture.getWidth(0), texture.getHeight(0), generated);
        }
        return generated;
    }

    /**
     * Whether the native mipmap command can filter this format.
     * <p>
     * Metal's generation requires both filtering and colour-rendering support. The list is the Apple7/M1 common
     * denominator, because this engine targets every Apple Silicon Mac and does not query the runtime GPU
     * family: full-range integer formats are colour-renderable but not filterable, and the 32-bit float formats
     * only become filterable on Apple9, so neither group is safe for the backend-wide path. The Metal 3 encoder
     * carries the same list for the same reason, and the two are kept identical by
     * {@code tools/ci-metal4-provider.py} rather than by memory.
     */
    private static boolean supportsMipmapGeneration(final com.mojang.blaze3d.GpuFormat format) {
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
     * {@inheritDoc}
     * <p>
     * A storage texture has no contents when it is made, and the client's own allocation asks for it to be
     * zeroed before anything reads it - it refuses to use an image the backend could not clear, which is exactly
     * where Vitrail's compute-storage fixture stopped on this path. The road is a typed kernel, the image in a
     * table by resource id, and a dispatch over the texture's extent: this generation has no blit fill and no
     * per-resource setter, so the dispatch the compute slice proved is what a clear is made of here.
     * <p>
     * False rather than a throw where there is nothing to clear: a closed encoder, a texture that is not this
     * engine's, a dimensionality this engine does not carry, or a kernel this device would not make.
     */
    @Override
    public boolean clearStorageTexture(final GpuTexture texture, final int dimensions) {
        if (this.closed || !(texture instanceof MetalGpuTexture metal) || texture.isClosed()
                || dimensions < 1 || dimensions > 3) {
            return false;
        }
        // A clear is a dispatch, so it gets what every dispatch gets: a table of its own and an encoder of its
        // own. The frame's clears used to share one re-pointed table in one encoder, which is the shape that
        // reads what the first clear bound.
        MTL4ArgumentTable table = MTL4ArgumentTable.create(this.executionState.device(), 0L, 1L, 0L);
        if (table == null) {
            return false;
        }
        queueForDestroy(table::close);
        MTL4ComputeEncoder copies = dispatchEncoder("the storage clear of a " + dimensions + "D texture");
        if (copies == null) {
            return false;
        }
        long width = texture.getWidth(0);
        long height = dimensions == 1 ? 1L : texture.getHeight(0);
        long depth = dimensions == 3 ? texture.getDepthOrLayers() : 1L;
        // The image is written through an address this frame hands over, so it has to stay resident - the same
        // declaration every other resource this path touches gets.
        useResource(metal.nativeHandle());
        boolean cleared;
        try {
            cleared = this.storagePipelines.clearZero(copies, table, metal.nativeHandle(),
                    zeroingKind(texture.getFormat()), dimensions, width, height, depth);
            copies.barrierForSubsequentEncoders();
        } finally {
            endDispatchEncoder(copies);
        }
        return cleared;
    }

    /**
     * Which scalar type a texture's format holds, and therefore which zeroing kernel writes it.
     * <p>
     * Read off the format's own name, which is the one place the fact exists: the format is a property of the
     * texture and not of this path, and the kernel's scalar type has to match it or the write is a type error at
     * pipeline creation rather than at the call.
     */
    private static com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind zeroingKind(
            final com.mojang.blaze3d.GpuFormat format) {
        String name = format.name();
        return name.endsWith("_UINT") ? com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind.UINT
                : name.endsWith("_SINT") ? com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind.SINT
                        : com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind.FLOAT;
    }

    /**
     * {@inheritDoc}
     * <p>
     * A dispatch on this command model is an argument table and nothing else: the new compute encoder has no
     * per-resource setters, so the bindings the shared translation numbered - buffers by address, textures and
     * samplers by resource id, each in its own kind's slot - are filled into the table the compiled handle owns,
     * the table is handed over with {@code setArgumentTable:}, and the workgroups are dispatched with
     * {@code dispatchThreadgroups:threadsPerThreadgroup:}. That last call is deliberately the one the Metal 3
     * bridge makes and not {@code dispatchThreads}: {@code groups*} are workgroup counts, as a Vulkan
     * {@code vkCmdDispatch} takes them, and the shader declares its own local size.
     * <p>
     * <strong>Everything is resolved and declared before the encoder opens.</strong> A binding the caller did not
     * provide has to be a refusal with nothing encoded, because the pipeline state and the table are handed over
     * in separate calls and a dispatch half-bound is a dispatch whose shader reads a slot nobody filled - and the
     * residency declaration is not optional on this path: an allocation this frame has not declared reads as
     * nothing at all, which the cold record measured one declaration at a time.
     * <p>
     * <strong>The frame's own compute encoder carries it.</strong> This command model has no blit encoder, so the
     * copies, the mipmap generations and the dispatches are all one encoder's commands, and within it program
     * order is the order. The two directions that are not program order are already covered where they are
     * encoded: a pass the game left open is submitted first (which barriers it), and the pass that follows this
     * dispatch barriers the copy encoder before it opens.
     */
    @Override
    public boolean dispatchCompute(final Object pipeline, final Map<String, GpuBufferSlice> buffers,
                                   final Map<String, GpuTextureView> textures,
                                   final Map<String, GpuSampler> samplers,
                                   final int groupsX, final int groupsY, final int groupsZ,
                                   final int localX, final int localY, final int localZ) {
        if (this.closed || !(pipeline instanceof Metal4ComputePipeline resource) || resource.closed()) {
            return false;
        }
        Objects.requireNonNull(buffers, "buffers");
        Objects.requireNonNull(textures, "textures");
        Objects.requireNonNull(samplers, "samplers");
        if (groupsX < 0 || groupsY < 0 || groupsZ < 0) {
            throw new IllegalArgumentException("Compute workgroup counts must not be negative");
        }
        if (localX <= 0 || localY <= 0 || localZ <= 0) {
            throw new IllegalArgumentException("Compute local size must be positive");
        }
        if (groupsX == 0 || groupsY == 0 || groupsZ == 0) {
            return true;
        }

        // One table per dispatch, and it is this dispatch's own: a table object re-pointed and handed to one
        // encoder twice is not reliably re-read - measured with the cold-probe reproducer, whose one-encoder
        // mode reads the first colour on every even round while a fresh table per dispatch is clean eight of
        // eight. The table is given back through the frame's destruction queue once this slot has completed.
        MTL4ArgumentTable table = resource.newTable(this.executionState.device());
        if (table == null) {
            return false;
        }
        queueForDestroy(table::close);
        for (MetalComputeTranslator.Binding binding : resource.bindings().values()) {
            switch (binding.kind()) {
                case UNIFORM_BUFFER, STORAGE_BUFFER -> bindDispatchBuffer(table, binding, buffers);
                case SAMPLED_IMAGE -> bindDispatchSampledImage(table, binding, textures, samplers);
                case STORAGE_IMAGE -> bindDispatchStorageImage(table, binding, textures);
                case TEXEL_BUFFER -> throw new IllegalStateException(
                        "A Metal 4 compute dispatch has no texel buffer binding: " + binding.name());
            }
        }

        MTL4ComputeEncoder compute = dispatchEncoder("the dispatch of " + resource.label());
        if (compute == null) {
            return false;
        }
        try {
            if (!compute.setComputePipelineState(resource.pipelineState())) {
                throw new IllegalStateException("The Metal 4 compute encoder would not take the pipeline for "
                        + resource.label());
            }
            // The table is handed over after it was filled: the header snapshots the resources in it when the
            // dispatch is encoded, so what this dispatch reads is what the table held at the call below.
            if (!compute.setArgumentTable(table)) {
                throw new IllegalStateException("The Metal 4 compute encoder would not take the argument table for "
                        + resource.label());
            }
            if (!compute.dispatchThreadgroups(groupsX, groupsY, groupsZ, localX, localY, localZ)) {
                throw new IllegalStateException("The Metal 4 compute encoder would not dispatch "
                        + groupsX + "x" + groupsY + "x" + groupsZ + " threadgroups for " + resource.label());
            }
            // Everything this encoder wrote has to be visible to whatever encoder follows it, and the encoder
            // that follows is a different object: this one ends here rather than being kept for the next
            // dispatch, which is the measured rule rather than a preference.
            compute.barrierForSubsequentEncoders();
        } finally {
            endDispatchEncoder(compute);
        }
        return true;
    }

    /**
     * The encoder one table-binding dispatch is encoded into, and the rule that it is a new one every time.
     * <p>
     * <strong>One encoder per dispatch, and this is measured rather than preferred.</strong> The cold probe's
     * storage-image smoke - two dispatches, a table each - loses its second dispatch in one encoder carrying
     * both (three of eight warm probes, with the copy dependency smoke in the suite), while an encoder per
     * dispatch is 93 of 93 probes in three processes and 50 of 50 in the census with every smoke green. The
     * same smoke's older re-pointed-table form had already shown the table to be the wrong unit to reuse; the
     * encoder is the unit the driver honours.
     * <p>
     * A copy encoder the frame already has open is ended here with its producer barrier, so the copies this
     * dispatch reads are ordered against it and the one-encoder-open rule holds. The encoder itself is ended by
     * {@link #endDispatchEncoder(MTL4ComputeEncoder)} and released once this frame's slot has completed: an
     * encoder released before the command buffer it encoded is committed aborts the driver (SIGSEGV in
     * {@code -[AGXG17XFamilyComputeContext_mtlnext dispatchThreads:threadsPerThreadgroup:]}), which is a
     * lifetime this path has already paid for once.
     */
    @Nullable
    private MTL4ComputeEncoder dispatchEncoder(final String which) {
        if (this.closed) {
            return null;
        }
        // A pass the game still has open ends first: one encoder may be open on a command buffer, and the
        // compute encoder cannot be opened under a render pass that has not ended.
        if (this.currentPass != null) {
            submitRenderPass();
        }
        beginFrameIfNeeded();
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.barrierForSubsequentEncoders();
            this.copyEncoder.endEncoding();
        }
        // Reported as the compute encoder it is, which is the same fact the reference arm reports before it opens
        // one. This call was missing, and the frame probe's `computeEncoders` therefore read zero on this path for
        // every frame that dispatched: Complementary Reimagined's shadow compute read as 532 encoders on the
        // reference arm against **0** here, which is a difference in the counter rather than in the frame - the
        // same shape as the indirect draws that read as an empty pass until they were counted. Nothing else in the
        // probe is fed by this call, so counting it changes what is reported and never what is encoded.
        MetalFrameProbe.encoderOpened(2);
        try {
            return MTL4ComputeEncoder.open(this.executionState.device(), this.ring.commandBuffer(), which);
        } catch (MTL4ComputeEncoder.Refused refused) {
            throw new IllegalStateException("The Metal 4 dispatch encoder could not be opened at stage "
                    + refused.stage() + ": " + refused.getMessage(), refused);
        }
    }

    /** Ends a dispatch's encoder and files its release against the slot that may still be reading it. */
    private void endDispatchEncoder(final MTL4ComputeEncoder compute) {
        compute.endEncoding();
        queueForDestroy(compute::close);
    }

    /** Binds one buffer of a dispatch by the address of the slice, which is what this command model takes. */
    private void bindDispatchBuffer(final MTL4ArgumentTable table, final MetalComputeTranslator.Binding binding,
                                    final Map<String, GpuBufferSlice> buffers) {
        GpuBufferSlice slice = requireComputeBuffer(binding, buffers);
        MetalGpuBuffer buffer = bufferOf(slice.buffer());
        useResource(buffer.metalBuffer().handle());
        if (!table.address(Metal4RenderPass.addressOf(slice.buffer(), slice.offset()), binding.bufferIndex())) {
            throw new IllegalStateException("The Metal 4 compute table would not take the buffer "
                    + binding.name() + " at slot " + binding.bufferIndex());
        }
    }

    /** Binds a sampled image and its sampler: two slots, because Metal numbers those tables separately. */
    private void bindDispatchSampledImage(final MTL4ArgumentTable table,
                                          final MetalComputeTranslator.Binding binding,
                                          final Map<String, GpuTextureView> textures,
                                          final Map<String, GpuSampler> samplers) {
        MetalGpuTextureView view = requireComputeTexture(binding, textures, "sampled image");
        MetalGpuSampler sampler = requireComputeSampler(binding, samplers);
        useResource(view.nativeHandle());
        if (!table.texture(view.nativeHandle(), binding.textureIndex())
                || !table.sampler(sampler.nativeHandle(), binding.samplerIndex())) {
            throw new IllegalStateException("The Metal 4 compute table would not take the sampled image "
                    + binding.name() + " and its sampler at slots " + binding.textureIndex() + " and "
                    + binding.samplerIndex());
        }
    }

    /**
     * Binds a storage image, which is the one binding the shader writes.
     * <p>
     * Its bookkeeping is invalidated like the Metal 3 bridge invalidates it: what a deferred clear recorded about
     * this texture is not true once a dispatch has written it, and the flag is cheap where being wrong is a
     * silently elided clear.
     */
    private void bindDispatchStorageImage(final MTL4ArgumentTable table,
                                          final MetalComputeTranslator.Binding binding,
                                          final Map<String, GpuTextureView> textures) {
        MetalGpuTextureView view = requireComputeTexture(binding, textures, "storage image");
        ((MetalGpuTexture) view.texture()).markContentsDirty();
        useResource(view.nativeHandle());
        if (!table.texture(view.nativeHandle(), binding.textureIndex())) {
            throw new IllegalStateException("The Metal 4 compute table would not take the storage image "
                    + binding.name() + " at slot " + binding.textureIndex());
        }
    }

    private static GpuBufferSlice requireComputeBuffer(final MetalComputeTranslator.Binding binding,
                                                       final Map<String, GpuBufferSlice> buffers) {
        GpuBufferSlice slice = buffers.get(binding.name());
        if (slice == null || !(slice.buffer() instanceof MetalGpuBuffer) || slice.buffer().isClosed()) {
            throw new IllegalStateException("Missing Metal 4 compute buffer " + binding.name());
        }
        return slice;
    }

    private static MetalGpuTextureView requireComputeTexture(final MetalComputeTranslator.Binding binding,
                                                             final Map<String, GpuTextureView> textures,
                                                             final String description) {
        GpuTextureView view = textures.get(binding.name());
        if (!(view instanceof MetalGpuTextureView metalView) || view.isClosed()) {
            throw new IllegalStateException("Missing Metal 4 compute " + description + " " + binding.name());
        }
        return metalView;
    }

    private static MetalGpuSampler requireComputeSampler(final MetalComputeTranslator.Binding binding,
                                                         final Map<String, GpuSampler> samplers) {
        GpuSampler sampler = samplers.get(binding.name());
        if (!(sampler instanceof MetalGpuSampler metalSampler) || metalSampler.isClosed()) {
            throw new IllegalStateException("Missing Metal 4 compute sampler " + binding.name());
        }
        return metalSampler;
    }

    /**
     * {@inheritDoc}
     * <p>
     * No: a region copy between storage textures is a 3D subresource operation, where the copies this path does
     * have are whole-texture and 2D-region moves between the game's own textures.
     */
    @Override
    public boolean copyStorageTextureRegion(final GpuTexture source, final GpuTexture destination,
                                            final int sourceX, final int sourceY, final int sourceZ,
                                            final int destinationX, final int destinationY, final int destinationZ,
                                            final int width, final int height, final int depth) {
        return refuseResourceOperation("copyStorageTextureRegion");
    }

    /**
     * What has already been said about a resource operation this path cannot perform, so each says it once.
     * <p>
     * Mipmap generation left this set when the frame's copy encoder learned the command; what is left is the two
     * operations a storage texture would need, which wait for the compute slice.
     */
    private final Set<String> refusedResourceOperations = new HashSet<>();

    /**
     * The one answer this generation can give an operation it has not implemented: false, with the reason said
     * once.
     * <p>
     * <strong>False is the contract's own fallback and not a silent drop.</strong> Every caller of these three
     * operations takes a boolean and has another road for a false - that is what the shape is for - so this says
     * "not here" where the plan's section 35 forbids saying nothing. What made carrying the contract necessary is
     * the dispatch above it rather than these operations: the client installs its capability adapter for a
     * backend that carries this contract, and it decides that from the contract's presence, so a generation that
     * omitted it lost the attachment-contents half that <em>does</em> work - measured, as a pack's stores that
     * were never elided and a bridge line that never appeared.
     */
    private boolean refuseResourceOperation(final String operation) {
        if (this.refusedResourceOperations.add(operation)) {
            Metallum.LOGGER.warn("Metal 4 frame encoder: {} is not implemented on this path yet, so the caller"
                    + " takes its own fallback. The contract is carried anyway because the capability dispatch"
                    + " asks for it whole, and the attachment-contents half of it does work here", operation);
        }
        return false;
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
     * Records the picture into the layer's next drawable, in this frame's own command buffer.
     * <p>
     * The order the API asks for is the whole of it: the drawable is taken, the queue is told which drawable the
     * command buffer about to be committed targets (<em>before</em> the commit), the present triangle is drawn
     * into the drawable's own texture, and {@link #submit()} tells the queue to signal it and presents it. A
     * driver given the signal half without the wait half refuses the signal with an unrecognised selector, which
     * is the framework saying the drawable was never registered with that queue.
     * <p>
     * The triangle is the engine's own present draw and not a copy: a whole-texture copy has no coordinates to
     * flip, and the copy road put the loading screen on screen upside down - measured, and the reason both
     * present roads draw.
     * <p>
     * A drawable the layer will not hand out leaves the caller's picture unpresented and says so: there is no
     * frame to present into, and a silent return would be a frame the player never sees with nothing in the log.
     */
    @Override
    public void presentTextureToDrawable(final @NonNull CAMetalLayer layer, final @NonNull GpuTextureView textureView) {
        if (this.closed) {
            throw new IllegalStateException("the Metal 4 frame encoder is closed, so it cannot present");
        }
        MetalGpuTexture picture = pictureOf(textureView);
        if (!this.ring.supportsDrawables()) {
            throw new IllegalStateException("the Metal 4 queue does not answer waitForDrawable: and"
                    + " signalDrawable:, so a drawable taken from the layer could not be presented - and a"
                    + " drawable taken and not presented is one the layer cannot hand out again");
        }

        CAMetalDrawable drawable = layer.nextDrawable();
        if (drawable == null) {
            throw new IllegalStateException("the Metal 4 layer would not hand out a drawable, so this frame has"
                    + " nothing to present into");
        }
        MemorySegment drawableTexture = drawable.texture();
        if (ObjC.isNil(drawableTexture)) {
            throw new IllegalStateException("the drawable the Metal 4 layer handed out has no texture");
        }

        if (this.currentPass != null) {
            submitRenderPass();
        }
        beginFrameIfNeeded();
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.barrierForSubsequentEncoders();
            this.copyEncoder.endEncoding();
        }

        // Before the commit, which is Apple's half of the order that comes first.
        if (!this.ring.waitForDrawable(drawable.handle())) {
            throw new IllegalStateException("the Metal 4 queue refused waitForDrawable:, so the drawable this"
                    + " frame presents into would not be the one the queue waits for");
        }

        long width = MTLTexture.width(drawableTexture);
        long height = MTLTexture.height(drawableTexture);
        MTL4ArgumentTable table = presentTable();
        if (table == null || !table.texture(picture.nativeHandle())
                || !table.sampler(MTLBuiltinPipelines.presentSampler(scalingTo(drawableTexture, picture.nativeHandle())))) {
            throw new IllegalStateException("the Metal 4 present table would not take the picture and its"
                    + " sampler, so nothing would be drawn into the drawable");
        }

        if (TRACE) {
            // Which texture the frame was asked to present, named the same way a pass names its own attachment.
            // It is here because "the GUI is not in the presented frame" is a question about two objects - the
            // texture the passes drew into and the texture the present sampled - and a log that names only one
            // of them cannot answer it.
            Metallum.LOGGER.info("Metal 4 trace: presenting picture 0x{} {}x{} into a drawable 0x{} {}x{}",
                    Long.toHexString(picture.nativeHandle().address()),
                    MTLTexture.width(picture.nativeHandle()), MTLTexture.height(picture.nativeHandle()),
                    Long.toHexString(drawableTexture.address()),
                    MTLTexture.width(drawableTexture), MTLTexture.height(drawableTexture));
        }

        MTL4RenderEncoder pass;
        try {
            // The present's drawable is an attachment like any other and this pass overwrites every pixel of it,
            // so it is counted with the same two facts it is opened with - the frame's attachment traffic is the
            // sum over the passes that cost it, and the present is one of them.
            MTL4RenderEncoder.Color presentAttachment = new MTL4RenderEncoder.Color(drawableTexture,
                    new AttachmentContents(true, true), null);
            MTL4RenderEncoder.countAttachment(presentAttachment, picture.pixelSize());
            pass = MTL4RenderEncoder.open(this.executionState.device(), this.ring.commandBuffer(), width, height,
                    new MTL4RenderEncoder.Color[]{presentAttachment},
                    null, "the present");
        } catch (MTL4RenderEncoder.Refused refused) {
            throw new IllegalStateException("the Metal 4 present pass could not be opened at stage "
                    + refused.stage() + ": " + refused.getMessage(), refused);
        }
        try {
            if (!pass.drawPresent(table, scalingTo(drawableTexture, picture.nativeHandle()))) {
                throw new IllegalStateException("the Metal 4 present triangle could not be drawn into the"
                        + " drawable");
            }
            pass.barrierForSubsequentEncoders();
            pass.endEncoding();
        } finally {
            pass.close();
        }
        if (this.drawableReadback) {
            // The picture first, in the same frame and the same command buffer as the drawable's copy: the two
            // lines a reading compares have to describe one frame rather than two.
            copyPictureForReadback(picture.nativeHandle(), MTLTexture.width(picture.nativeHandle()),
                    MTLTexture.height(picture.nativeHandle()));
            copyDrawableForReadback(drawableTexture, width, height);
        }
        this.presentDrawables.add(drawable);
    }

    /**
     * Copies the drawable into this slot's staging buffer, in the frame's own command buffer.
     * <p>
     * Only reachable when the layer was built with {@code framebufferOnly} off, which is what the diagnostic
     * switch does: a framebuffer-only drawable may not be the source of a copy, and the copy is the only way the
     * presented pixels reach this process at all - the display cannot be photographed here.
     */
    private void copyDrawableForReadback(final MemorySegment drawableTexture, final long width, final long height) {
        int slot = this.ring.slot();
        long bytesPerRow = com.metallum.render.shared.DrawableReadback.bytesPerRow(width);
        long bytes = bytesPerRow * height;
        MTLBuffer staging = this.readbackStaging[slot];
        if (staging == null || staging.length() < bytes) {
            if (staging != null) {
                MemorySegment retired = staging.handle();
                queueForDestroy(() -> ObjC.release(retired));
            }
            // Made on the device this frame executes on, and shared so the CPU can read what the GPU wrote.
            staging = this.executionState.device().newBuffer(bytes, MTLStorageMode.Shared.value);
            this.readbackStaging[slot] = staging;
        }
        // The address the copy writes through is an address like any other, so the allocation is declared the
        // same way: an undeclared resource makes a command of this kind do nothing at all, measured.
        useResource(staging.handle());
        MTL4ComputeEncoder copies = copyEncoder();
        if (copies == null || !copies.copyTextureToBuffer(drawableTexture, 0L, 0L, 0L, 0L, 0L, width, height, 1L,
                staging.handle(), 0L, bytesPerRow, bytesPerRow * height)) {
            Metallum.LOGGER.warn("Metal 4 drawable readback: the copy of the presented drawable could not be"
                    + " encoded, so this frame's picture is not read");
            return;
        }
        copies.barrierForSubsequentEncoders();
        this.readbackPending[slot] = true;
        this.readbackWidth[slot] = width;
        this.readbackHeight[slot] = height;
    }

    /**
     * Copies the picture this frame's present triangle read into its slot's staging buffer.
     * <p>
     * Encoded in the frame's own command buffer, beside the drawable's copy and in the same order the one
     * reading has: the picture is what the present pass sampled, and the drawable is what the pass wrote, so a
     * reading that has both can say whether the road changed the picture. The copy goes through the frame's copy
     * encoder, whose staging allocation is declared resident for the same measured reason the drawable's is.
     */
    private void copyPictureForReadback(final MemorySegment picture, final long width, final long height) {
        int slot = this.ring.slot();
        long bytesPerRow = com.metallum.render.shared.DrawableReadback.bytesPerRow(width);
        long bytes = bytesPerRow * height;
        MTLBuffer staging = this.pictureStaging[slot];
        if (staging == null || staging.length() < bytes) {
            if (staging != null) {
                MemorySegment retired = staging.handle();
                queueForDestroy(() -> ObjC.release(retired));
            }
            staging = this.executionState.device().newBuffer(bytes, MTLStorageMode.Shared.value);
            this.pictureStaging[slot] = staging;
        }
        useResource(staging.handle());
        MTL4ComputeEncoder copies = copyEncoder();
        if (copies == null || !copies.copyTextureToBuffer(picture, 0L, 0L, 0L, 0L, 0L, width, height, 1L,
                staging.handle(), 0L, bytesPerRow, bytesPerRow * height)) {
            Metallum.LOGGER.warn("Metal 4 picture readback: the copy of the presented picture could not be"
                    + " encoded, so this frame's input is not read");
            return;
        }
        copies.barrierForSubsequentEncoders();
        this.picturePending[slot] = true;
        this.pictureWidth[slot] = width;
        this.pictureHeight[slot] = height;
    }

    /**
     * Reads and reports the drawable a slot copied, once that slot's submission is known complete.
     * <p>
     * Called from {@link #beginFrameIfNeeded()} right after the ring has waited for the slot, which is the same
     * fact the deferred releases are run on. What it prints is deliberately small and structural - a five by
     * five grid of samples, top row first, and the mean of each channel - because the questions it exists to
     * answer are whether the presented image has anything in it at all, whether it is the right way up, and
     * whether it is the colour the fixture asked for. The layer is BGRA8, so the bytes are blue, green, red,
     * alpha and the report says them in that order.
     */
    private void reportDrawableReadback(final int slot) {
        if (!this.readbackPending[slot]) {
            return;
        }
        this.readbackPending[slot] = false;
        MTLBuffer staging = this.readbackStaging[slot];
        long width = this.readbackWidth[slot];
        long height = this.readbackHeight[slot];
        if (staging == null || width <= 0L || height <= 0L) {
            return;
        }
        long bytesPerRow = com.metallum.render.shared.DrawableReadback.bytesPerRow(width);
        // The reading and the wording are the shared layer's, so that this arm's line and the Metal 3 arm's line
        // are the same shape: a comparison whose two sides formatted differently compares the formatting.
        com.metallum.render.shared.DrawableReadback.report("metal4", width, height,
                staging.contents().reinterpret(bytesPerRow * height), bytesPerRow);
    }

    /**
     * Reads and reports the picture the present triangle of this slot read, at the same point its drawable is.
     * <p>
     * The label carries both the generation and the half, so one run's two lines can be read against each other
     * without either being inferred from the other.
     */
    private void reportPictureReadback(final int slot) {
        if (!this.picturePending[slot]) {
            return;
        }
        this.picturePending[slot] = false;
        MTLBuffer staging = this.pictureStaging[slot];
        long width = this.pictureWidth[slot];
        long height = this.pictureHeight[slot];
        if (staging == null || width <= 0L || height <= 0L) {
            return;
        }
        long bytesPerRow = com.metallum.render.shared.DrawableReadback.bytesPerRow(width);
        com.metallum.render.shared.DrawableReadback.reportPicture("metal4", width, height,
                staging.contents().reinterpret(bytesPerRow * height), bytesPerRow);
    }

    /**
     * Presents every drawable this frame took: the signal half of the order for each, then the presentation.
     * <p>
     * Called by {@link #submit()} after the commit and by {@link #close()} before the ring goes, because a
     * drawable that is taken and never presented is one the layer will not hand out again. The signal comes
     * first because the header says so in as many words: it "fails if you call it after any of the present
     * methods, or if you call it multiple times".
     */
    private void presentAll() {
        if (this.presentDrawables.isEmpty()) {
            return;
        }
        List<CAMetalDrawable> drawables = List.copyOf(this.presentDrawables);
        this.presentDrawables.clear();
        for (CAMetalDrawable drawable : drawables) {
            // The drawable has already been waited for, at the moment it was taken: this is the other half, and
            // it has to be sent after the commit that carries the picture and before the presentation.
            MetalFrameProbe.metal4Present();
            if (!this.ring.signalDrawable(drawable.handle())) {
                Metallum.LOGGER.warn("Metal 4 frame encoder: the queue would not signal a drawable, so the frame"
                        + " just committed may not be shown");
            }
            drawable.present();
        }
    }

    /** The one-texture, one-sampler table the present triangle reads through, made on first use. */
    private MTL4ArgumentTable presentTable() {
        if (this.presentTable == null) {
            this.presentTable = MTL4ArgumentTable.create(this.executionState.device());
        }
        return this.presentTable;
    }

    /** The picture a texture view names, as the texture the present triangle samples. */
    private static MetalGpuTexture pictureOf(final GpuTextureView textureView) {
        if (!(textureView.texture() instanceof MetalGpuTexture picture)) {
            throw new IllegalStateException("the Metal 4 pass was handed a texture that is not this engine's: "
                    + textureView.texture().getClass().getName());
        }
        return picture;
    }

    /** Whether the drawable and the picture differ in size, which is what chooses the present filter. */
    private static boolean scalingTo(final MemorySegment drawableTexture, final MemorySegment picture) {
        return MTLTexture.width(drawableTexture) != MTLTexture.width(picture)
                || MTLTexture.height(drawableTexture) != MTLTexture.height(picture);
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
                null, new int[]{color.pixelSize()}, 0,
                colorTexture.getWidth(0), colorTexture.getHeight(0));
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
                new int[]{color.pixelSize()}, depth.pixelSize(),
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
                new int[0], depth.pixelSize(),
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
                             final MTL4RenderEncoder.Depth depth, final int[] colorPixelSizes,
                             final int depthPixelSize, final long width, final long height) {
        for (MTL4RenderEncoder.Color color : colors) {
            useResource(color.texture());
        }
        if (depth != null) {
            useResource(depth.texture());
        }
        if (this.currentPass != null) {
            submitRenderPass();
        }
        beginFrameIfNeeded();
        if (this.copyEncoder != null && this.copyEncoder.open()) {
            this.copyEncoder.barrierForSubsequentEncoders();
            this.copyEncoder.endEncoding();
        }

        MetalFrameProbe.encoderOpened(3);
        // A clear's pass is attachment traffic like any other, and a counter that left it out would make a frame
        // which clears in five passes of its own look cheaper than one that folds those clears into the passes
        // that use the attachments - which is exactly the comparison these counters exist for. Counted through
        // the same mapping that opens the descriptor: a clear asks for no load, and what it wrote is stored.
        for (int index = 0; index < colors.length; index++) {
            MTL4RenderEncoder.countAttachment(colors[index], colorPixelSizes[index]);
        }
        if (depth != null) {
            MTL4RenderEncoder.countDepthAttachment(depth, depthPixelSize);
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

    /**
     * Says that this frame's work reads an allocation through an address, so it has to stay resident.
     * <p>
     * Called where the frame path binds something by address or id - an attachment, a sampled texture, a uniform
     * or vertex buffer, an index buffer, a staging block a copy reads - and it is deliberately generous: the
     * first version declares everything a frame touches rather than working out per-resource usage, which the
     * migration's sections 52 to 53 ask for and this is not. What it replaces is declaring nothing at all.
     */
    void useResource(final @Nullable MemorySegment allocation) {
        if (ObjC.isNil(allocation) || !this.declaredAllocations.add(allocation.address())) {
            return;
        }
        if (this.residency == null) {
            this.residency = MTL4ResidencySet.create(this.executionState.device(), 64L, "the frame's addresses");
        }
        if (this.residency == null || !this.residency.add(allocation)) {
            this.declaredAllocations.remove(allocation.address());
            if (!this.residencyWarned) {
                this.residencyWarned = true;
                Metallum.LOGGER.warn("Metal 4 frame encoder: the frame path cannot declare residency on this"
                        + " device, so the allocations it binds by address are only as resident as the driver"
                        + " makes them");
            }
            return;
        }
        statResidencyDeclaration();
        this.residencyDirty = true;
    }

    /**
     * Makes what the frame declared resident, before the work that reads it is committed.
     * <p>
     * The order is the header's: an added allocation is "uncommitted until commit is called", and the set is
     * handed to the queue once, so the commit is what tells the GPU about this frame's addresses and the queue
     * already holds the set that carries them.
     */
    private void commitResidency() {
        if (this.residency == null || !this.residencyDirty) {
            return;
        }
        this.residencyDirty = false;
        if (!this.residency.commit() || !this.residency.requestResidency()) {
            if (!this.residencyWarned) {
                this.residencyWarned = true;
                Metallum.LOGGER.warn("Metal 4 frame encoder: the residency set would not commit or request"
                        + " residency, so the frame's addresses are not declared");
            }
            return;
        }
        if (!this.residencyAttached) {
            this.residencyAttached = this.ring.addResidencySet(this.residency.handle());
            if (!this.residencyAttached && !this.residencyWarned) {
                this.residencyWarned = true;
                Metallum.LOGGER.warn("Metal 4 frame encoder: the queue would not take the residency set, so what"
                        + " the frame binds by address is not declared to it");
            }
        }
    }

    /** One frame's counters, said once every sixty frames so the line is a rate and not a wall of numbers. */
    private void statFrame() {
        if (!STATS) {
            return;
        }
        if (this.statBeganAt != 0L) {
            this.statFrameNanos += System.nanoTime() - this.statBeganAt;
            this.statBeganAt = 0L;
        }
        this.statFrames++;
        if (this.statFrames % 60L != 0L) {
            return;
        }
        Metallum.LOGGER.info("Metal 4 frame stats: frames={} fps={} msPerFrame={} passesPerFrame={}"
                        + " encodersPerFrame={} tablesPerFrame={} drawsPerFrame={} indexedPerFrame={}"
                        + " residencyPerFrame={}", this.statFrames,
                String.format("%.1f", 60.0 / (this.statFrameNanos / 1.0e9)),
                String.format("%.2f", this.statFrameNanos / 1.0e6 / 60.0),
                String.format("%.1f", (double) this.statPasses / 60.0),
                String.format("%.1f", (double) this.statEncoders / 60.0),
                String.format("%.1f", (double) this.statTables / 60.0),
                String.format("%.1f", (double) this.statDraws / 60.0),
                String.format("%.1f", (double) this.statIndexed / 60.0),
                String.format("%.1f", (double) this.statResidency / 60.0));
        this.statPasses = 0L;
        this.statEncoders = 0L;
        this.statTables = 0L;
        this.statDraws = 0L;
        this.statIndexed = 0L;
        this.statResidency = 0L;
        this.statFrameNanos = 0L;
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
