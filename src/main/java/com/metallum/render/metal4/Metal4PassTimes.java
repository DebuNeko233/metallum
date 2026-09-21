package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4CounterHeap;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The GPU's own time for each pass of this frame path, one command-buffer marker per pass boundary.
 * <p>
 * Section 88 is why this exists and the smoke that made it legal is {@code MTL4Probe.canMeasurePassGpuTime}:
 * the road, its unit and its floor were measured there before a line of this class was written. What the smoke
 * proved is that a command-buffer marker placed behind a pass's encoder reads as that pass's completion
 * ({@code MTL4CommandBuffer.h}: "captures a timestamp after work prior to this command in the command buffer is
 * complete"), that the intervals scale with the work, and that an interval below roughly two thousand ticks on
 * this device is not ordered - so a pass whose GPU time is under about two microseconds reads as noise, and the
 * report says so rather than pretending otherwise.
 * <p>
 * <strong>This is the third kind of timing and the report must keep it apart from the other two</strong>
 * (section 92): {@code PassTimings} is CPU encoding time, {@code MTL4CommitFeedback.GPUStartTime/GPUEndTime} is
 * the whole commit's driver-reported time, and these are GPU ticks between markers this path placed. They answer
 * different questions and none of them is the other two - and the first session that read all three is what made
 * that concrete: the passes below total **378 microseconds a frame** while the commit's own window is 19.4
 * milliseconds, because {@code MTL4CommandQueue}'s {@code waitForDrawable:} "schedules a wait operation on the
 * command queue to ensure the display is no longer using a specific Metal drawable" and that wait is inside the
 * commit's window. So this table is what the frame's own work is, and the commit window is not.
 * <p>
 * <strong>Off unless {@code -Dmetallum.metal4PassTimes=true}.</strong> Section 91 says instrumentation that
 * changes the workload is for a diagnostic session, so the switch is off by default and the overhead of having it
 * on is itself an A/B rather than an assumption. **Measured, that A/B is not an overhead at all**: four arms of
 * one session - off, on, off, on - read 21.79 and 21.80 ms a frame with the reader off and **19.37 and 19.45 with
 * it on, 11% faster, twice**. That is the outcome section 91's rule exists for, and it makes this table a
 * diagnostic reading and never a performance verdict; what a marker between two passes does to the driver's
 * scheduling is a question of its own.
 * <p>
 * <strong>What an interval covers, stated because the label alone would overstate it.</strong> A boundary is
 * written when a pass's encoder is closed, so the interval attributed to a pass runs from the <em>previous</em>
 * boundary to this pass's end: anything encoded between two passes - a copy-back, a dispatch - is counted with
 * the pass that follows it rather than with itself. What the table is good for is what it was built for: saying
 * which passes the GPU spends the frame's time in, and how small that time is against the frame's period.
 */
@Environment(EnvType.CLIENT)
final class Metal4PassTimes {

    /** Whether this session reads the GPU's clock between passes. Off by default; section 91's rule. */
    private static final boolean ON = Boolean.getBoolean("metallum.metal4PassTimes");

    /** One entry for the frame's start plus one per pass boundary, which is more than a pack's frame opens. */
    private static final int ENTRIES = 512;

    /**
     * How often the table is printed, in frames.
     * <p>
     * The same property the frame probe's window takes, so the two lines describe the same frames when both are
     * on: a per-pass cost read against a window of a different length would be a different measurement.
     */
    private static final int BUDGET = Integer.getInteger("metallum.frameProbeBudget", 600);

    /** How many labels the line names, heaviest first, before it says how many it left out. */
    private static final int NAMED = 8;

    private final MTL4CounterHeap[] heaps;
    private final String[][] labels;
    private final int[] written;
    /** Ticks and interval count per pass label, as this session has read them. */
    private final Map<String, long[]> totals = new LinkedHashMap<>();
    private long frames;
    private long unread;
    private boolean refused;

    private Metal4PassTimes(final MTL4CounterHeap[] heaps) {
        this.heaps = heaps;
        this.labels = new String[heaps.length][ENTRIES];
        this.written = new int[heaps.length];
    }

    /**
     * The reader for this device, or null where the switch is off or the device will not make the heaps.
     * <p>
     * Every refusal says what it was: a device without the counter-heap factory, or a heap that came back nil, is
     * a session that cannot have this table, and it is said once rather than at every pass.
     */
    @Nullable
    static Metal4PassTimes create(final MTLDevice device, final int slots) {
        if (!ON) {
            return null;
        }
        if (!device.respondsTo("newCounterHeapWithDescriptor:error:")) {
            Metallum.LOGGER.warn("Metal 4 pass times: metallum.metal4PassTimes was asked for, and this device does"
                    + " not answer newCounterHeapWithDescriptor:error:, so no pass's GPU time can be read");
            return null;
        }
        MTL4CounterHeap[] heaps = new MTL4CounterHeap[Math.max(1, slots)];
        for (int index = 0; index < heaps.length; index++) {
            heaps[index] = MTL4CounterHeap.create(device, ENTRIES);
            if (heaps[index] == null) {
                Metallum.LOGGER.warn("Metal 4 pass times: the device made no timestamp heap for slot {}, so the"
                        + " table is not read this session", index);
                for (int made = 0; made < index; made++) {
                    heaps[made].close();
                }
                return null;
            }
        }
        Metallum.LOGGER.info("Metal 4 pass times: reading the GPU's clock between passes for this session, {}"
                + " slots of {} entries, reported every {} frames - and a tick is a nanosecond on this device",
                heaps.length, ENTRIES, BUDGET);
        return new Metal4PassTimes(heaps);
    }

    /**
     * Opens a frame on this slot: reads what the slot's previous frame cost, then marks this frame's start.
     * <p>
     * The read is legal here and nowhere earlier: the ring waits for this slot's previous submission to complete
     * inside {@code beginFrame}, and the header's rule is that a CPU-timeline resolve needs the GPU work
     * finished. Entries are resolved as one range - the header says a range resolves to "tightly packed" values -
     * and an entry that resolves to zero is not a time, so its interval is dropped and counted.
     */
    void beginFrame(final int slot, final MemorySegment commandBuffer) {
        if (this.refused || slot < 0 || slot >= this.heaps.length) {
            return;
        }
        read(slot);
        this.written[slot] = 0;
        if (!this.heaps[slot].writeTimestamp(commandBuffer, 0L)) {
            this.refused = true;
            return;
        }
        this.labels[slot][0] = null;
        this.written[slot] = 1;
    }

    /** One pass boundary: the marker goes behind the pass's encoder, so it is the moment that pass's work ended. */
    void boundary(final int slot, final MemorySegment commandBuffer, final String label) {
        if (this.refused || slot < 0 || slot >= this.heaps.length) {
            return;
        }
        int at = this.written[slot];
        if (at <= 0 || at >= ENTRIES) {
            return;
        }
        if (!this.heaps[slot].writeTimestamp(commandBuffer, at)) {
            this.refused = true;
            return;
        }
        this.labels[slot][at] = label;
        this.written[slot] = at + 1;
    }

    /** One frame is over; the table is printed when the same number of frames as the probe's window has run. */
    void frameDone() {
        if (this.refused) {
            return;
        }
        this.frames++;
        if (BUDGET > 0 && this.frames % BUDGET == 0L) {
            report();
        }
    }

    /** Reads a slot's completed frame into the totals, and forgets it. */
    private void read(final int slot) {
        int count = this.written[slot];
        if (count <= 1) {
            return;
        }
        long[] stamps = this.heaps[slot].resolveRange(0L, count);
        for (int index = 1; index < count; index++) {
            String label = this.labels[slot][index];
            long delta = stamps[index] - stamps[index - 1];
            if (label == null || stamps[index] < 0L || stamps[index - 1] < 0L || delta < 0L) {
                this.unread++;
                continue;
            }
            long[] total = this.totals.computeIfAbsent(label, ignored -> new long[2]);
            total[0] += delta;
            total[1]++;
        }
    }

    /** One line: the heaviest labels by mean GPU time a frame, with the floor named rather than hidden. */
    private void report() {
        if (this.totals.isEmpty()) {
            Metallum.LOGGER.info("Metal 4 GPU pass time: {} frames and no pass interval was read ({} unread), so"
                    + " the counter road said nothing this window", this.frames, this.unread);
            return;
        }
        List<Map.Entry<String, long[]>> ranked = new ArrayList<>(this.totals.entrySet());
        ranked.sort((left, right) -> Long.compare(right.getValue()[0], left.getValue()[0]));
        StringBuilder line = new StringBuilder();
        long totalTicks = 0L;
        for (Map.Entry<String, long[]> entry : ranked) {
            totalTicks += entry.getValue()[0];
        }
        for (int index = 0; index < Math.min(NAMED, ranked.size()); index++) {
            Map.Entry<String, long[]> entry = ranked.get(index);
            double usAFrame = entry.getValue()[0] / 1000.0 / Math.max(1L, this.frames);
            if (index > 0) {
                line.append(", ");
            }
            line.append(entry.getKey()).append(' ').append(String.format(Locale.ROOT, "%.3f", usAFrame));
        }
        Metallum.LOGGER.info("Metal 4 GPU pass time (GPU ticks between markers this path placed, never the CPU's"
                        + " encode time): frames={} labels={} totalUsAFrame={} unread={} floorUs=2.0 top=[{}]{}",
                this.frames, ranked.size(), String.format(Locale.ROOT, "%.3f", totalTicks / 1000.0 / this.frames),
                this.unread, line, ranked.size() > NAMED ? " and " + (ranked.size() - NAMED) + " more" : "");
    }

    /** Releases the heaps. The session's last frames are not read, because their slots never came round again. */
    void close() {
        for (MTL4CounterHeap heap : this.heaps) {
            if (heap != null) {
                heap.close();
            }
        }
    }
}
