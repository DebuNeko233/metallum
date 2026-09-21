package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.util.Arrays;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * A Metal 4 timestamp counter heap: the object the GPU writes timestamps into and the CPU reads them back from.
 * <p>
 * Section 88 is the reason this exists. {@code PassTimings} on this backend measures the CPU's encoding time and
 * has been read as per-pass GPU time at least once; the counter heap is the only road to the GPU's own clock, and
 * the API was read off this machine's headers before a line of it was written - {@code MTLDevice.h:1516} for the
 * factory, {@code MTL4Counters.h} for the descriptor, the heap protocol and the entry layout, and
 * {@code MTL4RenderCommandEncoder.h:645} and {@code MTL4ComputeCommandEncoder.h:832} for the two encoders that
 * can write one.
 * <p>
 * <strong>The synchronization rule is the header's and it is already this engine's.</strong>
 * {@code MTL4Counters.h} says a CPU-timeline resolve needs the app to "ensure the GPU work has completed", and
 * then states the rule: "signaling an instance of {@code MTLSharedEvent} after any workloads write counters (and
 * waiting on that signal on the CPU) is sufficient to ensure synchronization". That is exactly what the frame
 * ring does per submission - one commit, a shared event signalled with the submission's value, a wait before
 * anything the GPU wrote is read - so the first version needs no new synchronization object.
 * <p>
 * <strong>An entry is eight bytes and an unresolved one reads as zero.</strong> {@code MTL4TimestampHeapEntry} is
 * {@code { uint64_t timestamp; }}, and {@code invalidateCounterRange:} documents that invalidated entries resolve
 * as zero - so zero is not a timestamp this class may hand back as a measurement. {@link #resolve} answers -1 for
 * anything it could not read and says why, which is section 104's rule for a native object that came back
 * unusable.
 */
@Environment(EnvType.CLIENT)
public final class MTL4CounterHeap implements AutoCloseable {

    /** {@code MTL4CounterHeapTypeTimestamp}, the only type this generation declares besides Invalid. */
    public static final long TYPE_TIMESTAMP = 1L;

    /** {@code MTL4CounterHeapTypeInvalid}, which never holds anything. */
    public static final long TYPE_INVALID = 0L;

    /** What one {@code MTL4TimestampHeapEntry} is: one {@code uint64_t}. */
    public static final long ENTRY_BYTES = 8L;

    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    private static final Msg SET_TYPE = Msg.ofVoid("setType:", JAVA_LONG);
    private static final Msg SET_COUNT = Msg.ofVoid("setCount:", JAVA_LONG);
    private static final Msg NEW_HEAP =
            Msg.of("newCounterHeapWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS);
    private static final Msg RESOLVE = Msg.of("resolveCounterRange:", ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg DATA_BYTES = Msg.of("bytes", ADDRESS);
    private static final Msg DATA_LENGTH = Msg.of("length", JAVA_LONG);
    private static final Msg COUNT = Msg.of("count", JAVA_LONG);

    private final MemorySegment handle;
    private final long entries;

    private MTL4CounterHeap(final MemorySegment handle, final long entries) {
        this.handle = handle;
        this.entries = entries;
    }

    /**
     * A timestamp heap of {@code entries} entries, or null where this device will not make one.
     * <p>
     * Every way it can fail is an answer and not an exception: no device, a device that does not answer the
     * factory, a system without the descriptor class, a non-positive count, and a nil heap are five sentences,
     * each said once.
     */
    @Nullable
    public static MTL4CounterHeap create(final MTLDevice device, final long entries) {
        if (entries <= 0L) {
            Metallum.LOGGER.warn("Metal 4 counter heap: asked for {} entries, and a heap of none holds no"
                    + " timestamp", entries);
            return null;
        }
        if (device == null || ObjC.isNil(device.handle())) {
            Metallum.LOGGER.warn("Metal 4 counter heap: there is no device to make one from");
            return null;
        }
        if (!device.respondsTo("newCounterHeapWithDescriptor:error:")) {
            Metallum.LOGGER.warn("Metal 4 counter heap: this device does not answer"
                    + " newCounterHeapWithDescriptor:error:, so no GPU timestamp can be read on it");
            return null;
        }

        MemorySegment descriptor;
        try {
            descriptor = NEW_DESCRIPTOR.sendPtr(ObjC.clazz("MTL4CounterHeapDescriptor"));
        } catch (Throwable missing) {
            Metallum.LOGGER.warn("Metal 4 counter heap: MTL4CounterHeapDescriptor is not there ({})",
                    missing.getMessage());
            return null;
        }
        if (ObjC.isNil(descriptor)) {
            Metallum.LOGGER.warn("Metal 4 counter heap: MTL4CounterHeapDescriptor could not be made");
            return null;
        }

        SET_TYPE.send(descriptor, TYPE_TIMESTAMP);
        SET_COUNT.send(descriptor, entries);
        MemorySegment made = NEW_HEAP.sendPtr(device.handle(), descriptor, MemorySegment.NULL);
        ObjC.release(descriptor);
        if (ObjC.isNil(made)) {
            Metallum.LOGGER.warn("Metal 4 counter heap: the device made none for {} timestamp entries", entries);
            return null;
        }
        return new MTL4CounterHeap(made, entries);
    }

    /** How many entries this heap was made with, as this class was told and as the heap itself reports. */
    public long entries() {
        return this.entries;
    }

    /** What the heap says its own size is, which is the number a range has to stay inside. */
    public long reportedEntries() {
        return COUNT.sendLong(this.handle);
    }

    /** The object itself, which is what an encoder's timestamp call is handed. */
    public MemorySegment handle() {
        return this.handle;
    }

    /**
     * Resolves one entry on the CPU timeline, or -1 where it could not be read.
     * <p>
     * <strong>Zero is not a reading.</strong> The header documents that an invalidated entry resolves as zero, so
     * a zero here is either an entry nothing wrote or one that was invalidated - neither of which is a timestamp -
     * and this answers -1 for it with the reason in the log rather than handing a caller a number that would be
     * read as "the GPU did that in no time at all".
     * <p>
     * The caller is responsible for the header's synchronization rule before calling this: the GPU work that
     * writes the entry has to have completed, which on this engine means waiting on the ring's shared event for
     * the submission that carried it.
     */
    public long resolve(final long index) {
        if (index < 0L || index >= this.entries) {
            Metallum.LOGGER.warn("Metal 4 counter heap: entry {} is outside the {} this heap was made with",
                    index, this.entries);
            return -1L;
        }

        MemorySegment data = RESOLVE.sendPtr(this.handle, index, 1L);
        if (ObjC.isNil(data)) {
            Metallum.LOGGER.warn("Metal 4 counter heap: resolveCounterRange: answered nil for entry {}", index);
            return -1L;
        }

        long length = DATA_LENGTH.sendLong(data);
        MemorySegment bytes = DATA_BYTES.sendPtr(data);
        if (ObjC.isNil(bytes) || length < ENTRY_BYTES) {
            Metallum.LOGGER.warn("Metal 4 counter heap: entry {} resolved to {} byte(s), where one timestamp entry"
                    + " is {}", index, length, ENTRY_BYTES);
            return -1L;
        }

        long timestamp = bytes.reinterpret(length).get(JAVA_LONG, 0L);
        // A resolved-and-invalidated entry reads as zero, which is documented and is not a time.
        return timestamp == 0L ? -1L : timestamp;
    }

    /**
     * Resolves a range of entries in one call, with -1 wherever one could not be read.
     * <p>
     * The header says a range resolves to "tightly packed resolved heap counter values", so this is the road a
     * caller wants when it has several entries - and having both this and {@link #resolve} is what lets a smoke
     * check that the per-entry road reads the same numbers rather than trusting one of them.
     */
    public long[] resolveRange(final long from, final long count) {
        long[] values = new long[(int) Math.max(0L, count)];
        if (from < 0L || count <= 0L || from + count > this.entries) {
            Arrays.fill(values, -1L);
            return values;
        }

        MemorySegment data = RESOLVE.sendPtr(this.handle, from, count);
        if (ObjC.isNil(data)) {
            Arrays.fill(values, -1L);
            return values;
        }
        long length = DATA_LENGTH.sendLong(data);
        MemorySegment bytes = DATA_BYTES.sendPtr(data);
        if (ObjC.isNil(bytes) || length < count * ENTRY_BYTES) {
            Arrays.fill(values, -1L);
            return values;
        }
        MemorySegment packed = bytes.reinterpret(length);
        for (int index = 0; index < values.length; index++) {
            long value = packed.get(JAVA_LONG, index * ENTRY_BYTES);
            values[index] = value == 0L ? -1L : value;
        }
        return values;
    }

    /** Resolves every entry, with -1 wherever one could not be read. */
    public long[] resolveAll() {
        long[] values = new long[(int) this.entries];
        Arrays.setAll(values, this::resolve);
        return values;
    }

    @Override
    public void close() {
        if (!ObjC.isNil(this.handle)) {
            ObjC.release(this.handle);
        }
    }
}
