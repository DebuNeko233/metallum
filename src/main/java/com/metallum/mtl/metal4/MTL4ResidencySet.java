package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * A Metal 4 residency set: the allocations the GPU is told to keep resident while it runs this queue's work.
 * <p>
 * <strong>Why this exists at all.</strong> The new command model binds a buffer by <em>GPU address</em> rather
 * than by object - the argument table's {@code setAddress:atIndex:} and the indexed draw's {@code indexBuffer}
 * both take one - and an address is not a reference: nothing in the command buffer keeps the allocation behind
 * it alive or resident. This machine's {@code MTL4RenderCommandEncoder.h} says what to do about that on the very
 * methods this path uses: "Use an instance of {@code MTLResidencySet} to mark residency of the index buffer the
 * {@code indexBuffer} parameter references." A frame that draws through addresses without declaring residency is
 * asking the driver to guess, and a guess that comes out wrong is an MMU fault, which on this machine arrives as
 * a kernel {@code GPURestart} and, at the API, as {@code MTL4CommandQueueErrorTimeout} - a submission that never
 * finishes rather than one that is refused.
 * <p>
 * The set is a plain object with four moves: allocations are <em>added</em> (uncommitted), <em>committed</em> so
 * the additions take effect, <em>requested</em> to ask that they be made resident, and the set itself is handed
 * to the command queue once. Nothing here is static and nothing outlives the device: the frame encoder owns its
 * set, so a reload, a teardown or a second device cannot leave one session's allocations on another's queue
 * (section 106).
 */
@Environment(EnvType.CLIENT)
public final class MTL4ResidencySet implements AutoCloseable {

    /** The class this wraps, as the SDK names it. */
    private static final String CLASS = "MTLResidencySet";
    private static final String DESCRIPTOR_CLASS = "MTLResidencySetDescriptor";

    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    private static final Msg SET_LABEL = Msg.ofVoid("setLabel:", ADDRESS);
    private static final Msg SET_INITIAL_CAPACITY = Msg.ofVoid("setInitialCapacity:", JAVA_LONG);
    private static final Msg NEW_SET_WITH_ERROR =
            Msg.of("newResidencySetWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS);
    private static final Msg NEW_SET = Msg.of("newResidencySetWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg ADD_ALLOCATION = Msg.ofVoid("addAllocation:", ADDRESS);
    private static final Msg COMMIT = Msg.ofVoid("commit");
    private static final Msg REQUEST_RESIDENCY = Msg.ofVoid("requestResidency");
    private static final Msg END_RESIDENCY = Msg.ofVoid("endResidency");
    private static final Msg ALLOCATION_COUNT = Msg.of("allocationCount", JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private MemorySegment handle;

    private MTL4ResidencySet(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * Makes a residency set on this device, or null where it makes none.
     * <p>
     * Every selector is asked for first and every failure is named, which is section 104's rule: a device
     * without the class, a descriptor that will not set a capacity and a factory that answers nil are three
     * different faults and read the same way in a log otherwise.
     *
     * @param device   the device that owns the set
     * @param capacity how many allocations it is expected to hold, which is a hint and not a limit
     * @param what     what the set is for, so the line names the path that asked
     * @return the set, or null
     */
    @Nullable
    public static MTL4ResidencySet create(final MTLDevice device, final long capacity, final String what) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment descriptor;
            try {
                descriptor = NEW_DESCRIPTOR.sendPtr(ObjC.clazz(DESCRIPTOR_CLASS));
            } catch (Throwable missing) {
                Metallum.LOGGER.warn("Metal 4 residency: {} is not there ({}), so {} cannot declare what it"
                        + " draws through", DESCRIPTOR_CLASS, missing.getMessage(), what);
                return null;
            }
            if (ObjC.isNil(descriptor)) {
                return null;
            }

            SET_INITIAL_CAPACITY.send(descriptor, capacity);

            boolean withError = device.respondsTo("newResidencySetWithDescriptor:error:");
            MemorySegment made = withError
                    ? NEW_SET_WITH_ERROR.sendPtr(device.handle(), descriptor, MemorySegment.NULL)
                    : NEW_SET.sendPtr(device.handle(), descriptor);
            ObjC.release(descriptor);
            if (ObjC.isNil(made)) {
                Metallum.LOGGER.warn("Metal 4 residency: the device made no {} for {} (asked with {})", CLASS, what,
                        withError ? "the error slot" : "no error slot");
                return null;
            }
            if (!responds(made, "addAllocation:") || !responds(made, "commit")
                    || !responds(made, "requestResidency")) {
                ObjC.release(made);
                Metallum.LOGGER.warn("Metal 4 residency: the {} for {} does not answer addAllocation:, commit and"
                        + " requestResidency, so it could not declare anything", CLASS, what);
                return null;
            }
            return new MTL4ResidencySet(made);
        }
    }

    /**
     * Adds one allocation to the set, uncommitted until {@link #commit()}.
     *
     * @param allocation a buffer, a texture or a heap, as the object the engine made
     * @return whether it was added
     */
    public boolean add(final MemorySegment allocation) {
        if (this.handle == null || ObjC.isNil(allocation)) {
            return false;
        }
        ADD_ALLOCATION.send(this.handle, allocation);
        return true;
    }

    /**
     * Makes the additions and removals since the last commit take effect.
     * <p>
     * Asked for before the work that uses them is committed: the header leaves an added allocation "uncommitted
     * until commit is called", and a set handed to a queue with uncommitted members is a residency the GPU was
     * never told about.
     */
    public boolean commit() {
        if (this.handle == null || !responds(this.handle, "commit")) {
            return false;
        }
        COMMIT.send(this.handle);
        return true;
    }

    /** Asks that the committed allocations be made resident, which is the request the queue's work relies on. */
    public boolean requestResidency() {
        if (this.handle == null || !responds(this.handle, "requestResidency")) {
            return false;
        }
        REQUEST_RESIDENCY.send(this.handle);
        return true;
    }

    /** How many allocations the set holds, which is what a device proof can count. */
    public long allocationCount() {
        return this.handle == null ? 0L : ALLOCATION_COUNT.sendLong(this.handle);
    }

    /** The set as the object the command queue is handed. */
    public MemorySegment handle() {
        return this.handle;
    }

    @Override
    public void close() {
        MemorySegment held = this.handle;
        this.handle = null;
        if (ObjC.isNil(held)) {
            return;
        }
        // Ended before it is let go: a set still holding residency on the way out is memory the device keeps
        // for a frame path that no longer exists.
        if (responds(held, "endResidency")) {
            END_RESIDENCY.send(held);
        }
        ObjC.release(held);
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }
}
