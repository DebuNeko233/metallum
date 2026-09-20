package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjCBlock;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * The frame's allocator ring: the slots a Metal 4 command buffer is encoded on, and the completion value each
 * slot's commit signalled.
 * <p>
 * This is the one part of the frame's lifetime where a guess is a use-after-free, so the rule is written down
 * once, here, and every caller rotates through this object rather than keeping a ring of its own. The SDK says
 * it in two places, both read off this machine's headers rather than remembered:
 * <ul>
 *   <li>{@code MTL4CommandAllocator.h}: {@code reset} "marks the command allocator's heaps for reuse", and the
 *       caller "is responsible to ensure that all command buffers with memory originating from this allocator
 *       instance are complete before calling resetting it" - the proof is the caller's, not the framework's;</li>
 *   <li>{@code MTL4CommandBuffer.h}: an allocator "only service[s] a single command buffer at a time", it may
 *       be reused once the buffer has been ended, and a command buffer is re-begun for the next frame.</li>
 * </ul>
 * So: <strong>a slot is never reset until the value its own commit signalled has been observed</strong>, and
 * that wait happens in {@link #beginFrame()} at the moment the slot is about to be reused - the only place it
 * can be proved, because it is the only place that knows the slot is about to be handed back to the GPU.
 * <p>
 * <strong>What this object owns and what it does not.</strong> It owns the allocators, the command buffer and
 * the shared event, and it releases them in {@link #close()}. It does <em>not</em> own the queue: the queue
 * belongs to the generation that made it, and the ring is given its handle. Nothing here is static - the ring
 * is a device-owned object, so a device teardown, a reload or a second device cannot reach another session's
 * allocators, which is the lifetime rule the migration's section 106 asks the production path to keep.
 * <p>
 * The frame model it realises is the conservative one the present sidecar already runs
 * ({@code Metal4Path.java:371-381}) and the migration's section 31 asks not to duplicate: three slots, one
 * command buffer, one commit a frame, and the incoming slot's own completion value awaited before its
 * allocator is reset.
 */
@Environment(EnvType.CLIENT)
public final class MTL4FrameRing implements AutoCloseable {

    /**
     * Three, "the shape the sample code ships": one allocator per frame in flight. The presenting sidecar
     * already runs this depth and the migration's section 31 says to start from the proven number rather than
     * to optimise in-flight depth while migrating.
     */
    public static final int FRAMES_IN_FLIGHT = 3;

    /**
     * What one slot's reuse may wait for the GPU to finish before the ring gives up on it.
     * <p>
     * Five seconds, which is the Metal 3 encoder's own patience at the same site ({@code
     * awaitSubmitCompletion(currentSubmitIndex - MAX_SUBMITS_IN_FLIGHT, 5000L)}). The number is the reference
     * path's rather than a guess.
     * <p>
     * <strong>Why it was looked at.</strong> The first forced Metal 4 client run that presented reached
     * submission 29 and then waited more than two seconds for it while it loaded a world, so the ring's two
     * seconds were raised to the Metal 3 five. The raise did not fix that run, and the reason is worth writing
     * down: the submission never completed because the GPU had stopped - the kernel logged a
     * {@code GPURestart} for that process's channel at that moment. A wait that times out is not evidence of a
     * slow path until the machine's own log has been asked.
     */
    private static final long WAIT_MILLIS = 5000L;

    private static final Msg NEW_ALLOCATOR = Msg.of("newCommandAllocator", ADDRESS);
    private static final Msg NEW_COMMAND_BUFFER = Msg.of("newCommandBuffer", ADDRESS);
    private static final Msg NEW_SHARED_EVENT = Msg.of("newSharedEvent", ADDRESS);
    private static final Msg BEGIN = Msg.ofVoid("beginCommandBufferWithAllocator:", ADDRESS);
    private static final Msg END = Msg.ofVoid("endCommandBuffer");
    private static final Msg RESET = Msg.ofVoid("reset");
    private static final Msg COMMIT = Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG);
    private static final Msg COMMIT_WITH_OPTIONS = Msg.ofVoid("commit:count:options:", ADDRESS, JAVA_LONG,
            ADDRESS);
    private static final Msg SIGNAL_EVENT = Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg WAIT_DRAWABLE = Msg.ofVoid("waitForDrawable:", ADDRESS);
    private static final Msg SIGNAL_DRAWABLE = Msg.ofVoid("signalDrawable:", ADDRESS);
    private static final Msg WAIT_UNTIL_SIGNALED =
            Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    /** The queue this ring submits on, which it does not own: the generation that made it releases it. */
    private final MemorySegment queue;

    @Nullable
    private MemorySegment event;
    @Nullable
    private MemorySegment commandBuffer;
    private final MemorySegment[] allocators;
    private final long[] awaited;
    private long signalled;
    private long waits;
    private int slot = -1;
    private boolean begun;
    private boolean closed;

    /**
     * The commit feedback this ring asks for where the queue offers it, and the block Metal calls with it.
     * <p>
     * The one account of a submission that went wrong: a Metal 4 queue reports nothing back to the caller, and
     * the feedback object's {@code error} is "a description of an error when the GPU encounters an issue as it
     * runs the committed command buffers". Without it a GPU fault reaches the frame path as a completion value
     * that never arrives, which reads as a lifetime fault on a machine that has actually restarted its GPU -
     * measured, and the reason this exists.
     */
    @Nullable
    private MTL4CommitOptions commitOptions;
    @Nullable
    private MemorySegment feedbackBlock;
    /** Whether a GPU fault has already been reported, so a dead GPU is one line and not one a commit. */
    private static volatile boolean faultReported;

    @Nullable
    private String refusal;

    private MTL4FrameRing(final MemorySegment queue, final MemorySegment event, final MemorySegment commandBuffer,
                          final MemorySegment[] allocators) {
        this.queue = queue;
        this.event = event;
        this.commandBuffer = commandBuffer;
        this.allocators = allocators;
        this.awaited = new long[allocators.length];
    }

    /**
     * A ring of {@code slots} allocators on a queue the caller owns.
     *
     * @param device the device the allocators, the command buffer and the event come from
     * @param queue  the queue the frame's command buffer is committed to, which this ring never releases
     * @param slots  how many frames in flight the ring bounds; at least one
     * @param what   what the ring is for, so a refusal names the path that wanted it
     * @throws Refused when the device will not make one of the objects, naming the stage that came back nil
     */
    public static MTL4FrameRing create(final MTLDevice device, final MemorySegment queue, final int slots,
                                       final String what) {
        if (slots < 1) {
            throw new Refused("slots", what + " asked for " + slots + " allocator slots, and a ring needs at"
                    + " least one");
        }
        if (ObjC.isNil(queue)) {
            throw new Refused("queue", what + " was given no queue to submit on");
        }

        MemorySegment[] allocators = new MemorySegment[slots];
        MemorySegment commandBuffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        try {
            for (int index = 0; index < slots; index++) {
                MemorySegment allocator = NEW_ALLOCATOR.sendPtr(device.handle());
                if (ObjC.isNil(allocator) || !responds(allocator, "reset")) {
                    ObjC.release(allocator);
                    throw new Refused("allocator", what + " could not make allocator slot " + index + " of "
                            + slots + " (or the allocator it made does not answer reset)");
                }
                allocators[index] = allocator;
            }

            commandBuffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            if (ObjC.isNil(commandBuffer) || !responds(commandBuffer, "beginCommandBufferWithAllocator:")
                    || !responds(commandBuffer, "endCommandBuffer")) {
                throw new Refused("commandBuffer", what + " could not make a command buffer to re-begin each"
                        + " frame");
            }

            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(event) || !responds(event, "waitUntilSignaledValue:timeoutMS:")) {
                throw new Refused("event", what + " could not make the shared event its slots' completion is"
                        + " proved with");
            }

            // Asked for, and made where the queue has it: a submission's own account of a fault is worth one
            // extra message per commit, and a queue without the options form commits exactly as before.
            MTL4CommitOptions options = null;
            MemorySegment block = MemorySegment.NULL;
            if (responds(queue, "commit:count:options:")) {
                options = MTL4CommitOptions.create();
                if (options != null) {
                    block = ObjCBlock.withConsumer(MTL4FrameRing::reportFeedback);
                    if (!options.feedbackHandler(block)) {
                        options.close();
                        options = null;
                    }
                }
            }

            MTL4FrameRing ring = new MTL4FrameRing(queue, event, commandBuffer, allocators);
            ring.commitOptions = options;
            ring.feedbackBlock = block;
            return ring;
        } catch (Refused refused) {
            releaseIfPresent(commandBuffer);
            releaseIfPresent(event);
            for (MemorySegment allocator : allocators) {
                releaseIfPresent(allocator);
            }
            throw refused;
        }
    }

    /**
     * Begins the next frame: picks the next slot, waits for that slot's own completion value where it has one,
     * resets its allocator, and begins the command buffer on it.
     * <p>
     * The wait is the whole rule. It is placed here rather than in a separate call so that no caller can hold a
     * begun frame on a slot whose previous work is still running: by the time this returns true, the slot's
     * previous submission has completed and its heaps have been marked for reuse.
     *
     * @return whether the frame was begun; a false answer leaves {@link #refusal()} saying where it stopped
     */
    public boolean beginFrame() {
        refusal = null;
        if (closed) {
            refusal = "the ring is closed";
            return false;
        }
        if (begun) {
            refusal = "a frame is already begun on slot " + slot + "; a ring holds one frame at a time";
            return false;
        }

        int next = (slot + 1) % allocators.length;
        if (awaited[next] != 0L) {
            if (WAIT_UNTIL_SIGNALED.sendLong(event, awaited[next], WAIT_MILLIS) == 0L) {
                refusal = "slot " + next + "'s completion value " + awaited[next] + " did not arrive within "
                        + WAIT_MILLIS + " ms, so its allocator is not known to be free and is not reset";
                return false;
            }
            waits++;
        }

        RESET.send(allocators[next]);
        BEGIN.send(commandBuffer, allocators[next]);
        slot = next;
        begun = true;
        return true;
    }

    /** The command buffer the current frame is encoded into. Only valid between begin and submit. */
    public MemorySegment commandBuffer() {
        return commandBuffer == null ? MemorySegment.NULL : commandBuffer;
    }

    /**
     * Ends the frame, commits it once, and signals the slot's completion value on the shared event.
     * <p>
     * One commit a frame is the migration's own target (section 30) and the reason this object exists: a second
     * submission is a second lifetime to retire.
     *
     * @return whether the frame was ended and committed
     */
    public boolean endAndSubmit() {
        refusal = null;
        if (!begun) {
            refusal = "no frame is begun, so there is nothing to submit";
            return false;
        }

        END.send(commandBuffer);
        try (Arena arena = Arena.ofConfined()) {
            MemorySegment buffers = arena.allocate(ADDRESS, 1);
            buffers.set(ADDRESS, 0L, commandBuffer);
            if (commitOptions != null) {
                // Registered for every commit, because the handler is taken once: measured on the present
                // sidecar, where a handler given to one commit was called for that commit and never again.
                commitOptions.feedbackHandler(feedbackBlock);
                COMMIT_WITH_OPTIONS.send(queue, buffers, 1L, commitOptions.handle());
            } else {
                COMMIT.send(queue, buffers, 1L);
            }
        }
        awaited[slot] = ++signalled;
        SIGNAL_EVENT.send(queue, event, signalled);
        begun = false;
        return true;
    }

    /**
     * Waits for every submission this ring has made, which is the wait a teardown or a readback needs before it
     * touches anything the GPU wrote.
     * <p>
     * The last value is enough: the queue orders its own submissions, so the completion of the newest one is
     * the completion of all of them.
     */
    public boolean awaitAll() {
        refusal = null;
        if (signalled == 0L) {
            return true;
        }
        if (WAIT_UNTIL_SIGNALED.sendLong(event, signalled, WAIT_MILLIS) == 0L) {
            refusal = "the last signalled value " + signalled + " did not arrive within " + WAIT_MILLIS + " ms";
            return false;
        }
        return true;
    }

    /** The value slot {@code index}'s commit signalled, or zero where that slot has never been used. */
    public long awaited(final int index) {
        return awaited[index];
    }

    /** How many submissions this ring has made. */
    public long submissions() {
        return signalled;
    }

    /**
     * The value the next commit will signal, which is the submission a fence made while a frame is open is
     * about.
     */
    public long nextSubmission() {
        return signalled + 1L;
    }

    /**
     * Whether this queue answers both halves of the drawable order, which is the whole of what presenting
     * through a layer needs from the API: the wait says which drawable the work about to be committed targets,
     * and the signal says the drawable may be shown once that work has run.
     */
    public boolean supportsDrawables() {
        return responds(queue, "waitForDrawable:") && responds(queue, "signalDrawable:");
    }

    /**
     * Tells the queue which drawable the command buffer it is about to commit targets.
     * <p>
     * Apple's order has this half <em>before</em> the commit and the signal half after it, and a driver that is
     * given only the signal half says so with
     * {@code -[AGXG17XFamilyRenderContext_mtlnext signalOnCommandQueue:]: unrecognized selector} - the
     * framework asking a drawable that was never registered with this queue to register itself on it.
     */
    public boolean waitForDrawable(final MemorySegment drawable) {
        if (closed || ObjC.isNil(drawable) || !responds(queue, "waitForDrawable:")) {
            return false;
        }
        WAIT_DRAWABLE.send(queue, drawable);
        return true;
    }

    /** The other half: the drawable may be presented once the committed work has run. */
    public boolean signalDrawable(final MemorySegment drawable) {
        if (closed || ObjC.isNil(drawable) || !responds(queue, "signalDrawable:")) {
            return false;
        }
        SIGNAL_DRAWABLE.send(queue, drawable);
        return true;
    }

    /**
     * Waits for the submission with this value to complete, which is what a fence promises.
     * <p>
     * The three answers mirror the Metal 3 encoder's own fence wait, because the two generations hand the same
     * object to the same callers and a fence that means something else on one path is a bug the caller cannot
     * see:
     * <ul>
     *   <li>a submission that has been committed ({@code value <= signalled}) is waited for on the shared event,
     *       with {@code timeoutMs == 0} asking the question without waiting - that is the poll
     *       {@code MappableRingBuffer} and {@code StagedVertexBuffer}'s pool both use;</li>
     *   <li>a submission that has <em>not</em> been committed is the submit being recorded, and Metal 3 answers
     *       it the same way: {@code false} for a poll, and a named refusal for a wait, because a wait would
     *       block on a signal no commit has promised yet;</li>
     *   <li>a value of zero is "nothing has been submitted", which is complete by definition.</li>
     * </ul>
     * A closed ring answers true for everything: {@link #close()} released the event, and what a teardown can
     * still be waiting for is nothing.
     *
     * @param submission the value {@code signalEvent:value:} carried for the submission being waited for
     * @param timeoutMs  how long to wait; zero asks without waiting
     * @return whether the submission has completed
     */
    public boolean awaitSubmission(final long submission, final long timeoutMs) {
        refusal = null;
        if (closed) {
            return true;
        }
        if (submission <= 0L) {
            return true;
        }
        if (submission > signalled) {
            if (timeoutMs == 0L) {
                return false;
            }
            throw new IllegalStateException("Cannot wait on a fence for the current submit");
        }
        if (WAIT_UNTIL_SIGNALED.sendLong(event, submission, timeoutMs) == 0L) {
            refusal = "submission " + submission + " had not completed within " + timeoutMs + " ms";
            return false;
        }
        return true;
    }

    /**
     * One commit's feedback, on the dispatch queue Metal owns: the fault it reports, where it reports one.
     * <p>
     * Reported once and not once a commit: a GPU that has faulted reports it for every submission after it, and
     * a log that repeats the same sentence per frame is a log nobody reads.
     */
    private static void reportFeedback(final MemorySegment feedback) {
        String error = MTL4CommitOptions.error(feedback);
        if (error == null) {
            return;
        }
        if (!faultReported) {
            faultReported = true;
            Metallum.LOGGER.error("Metal 4 frame: the GPU reported a fault in a committed submission - {}. The"
                    + " submissions after it will not complete either, so a completion value that never arrives"
                    + " is this and not a lifetime fault", error);
        }
    }

    /** How many times a slot was found still in flight and waited for before it was reset. */
    public long waits() {
        return waits;
    }

    /** The slot the last begun frame used, or -1 before the first frame. */
    public int slot() {
        return slot;
    }

    /**
     * The slot the next {@link #beginFrame()} will use.
     * <p>
     * Exposed because a resource that cannot be released yet has to be filed against the frame that will prove
     * its slot free, and that frame is the next one on this slot - so the owner needs to know which slot it is
     * before it begins.
     */
    public int nextSlot() {
        return (slot + 1) % allocators.length;
    }

    /** Whether a frame is begun and not yet submitted. */
    public boolean begun() {
        return begun;
    }

    /** Why the last call answered no, for a caller that has to say what stopped it. */
    @Nullable
    public String refusal() {
        return refusal;
    }

    /**
     * Releases the allocators, the command buffer and the event, and nothing the GPU may still be reading.
     * <p>
     * The caller owns that ordering because it owns the queue: this object cannot wait for a submission whose
     * completion value it has already been asked to forget, and a close that waited would have taken over the
     * execution lifecycle the frame encoder owns.
     */
    @Override
    public void close() {
        if (closed) {
            return;
        }
        closed = true;
        if (commitOptions != null) {
            commitOptions.close();
            commitOptions = null;
        }
        releaseIfPresent(commandBuffer);
        releaseIfPresent(event);
        commandBuffer = MemorySegment.NULL;
        event = MemorySegment.NULL;
        for (int index = 0; index < allocators.length; index++) {
            releaseIfPresent(allocators[index]);
            allocators[index] = MemorySegment.NULL;
            awaited[index] = 0L;
        }
    }

    /** Whether an object answers a selector, which is the question to ask before reaching for one. */
    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    private static void releaseIfPresent(final @Nullable MemorySegment object) {
        if (object != null && !ObjC.isNil(object)) {
            ObjC.release(object);
        }
    }

    /**
     * Why a ring could not be made, carrying the stage that failed - the same shape the execution provider's
     * own refusal has, and for the same reason: "not implemented" cannot be told from "the device said no"
     * unless the refusal says which object it was.
     */
    public static final class Refused extends RuntimeException {

        private final String stage;

        Refused(final String stage, final String why) {
            super(why);
            this.stage = stage;
        }

        /** One of {@code slots}, {@code queue}, {@code allocator}, {@code commandBuffer} or {@code event}. */
        public String stage() {
            return stage;
        }
    }
}
