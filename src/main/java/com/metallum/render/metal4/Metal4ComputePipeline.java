package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
import com.metallum.objc.ObjC;
import com.metallum.render.MetalDevice;
import com.metallum.render.shared.MetalComputePipelineResource;
import com.metallum.render.shared.MetalComputeTranslator;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.util.Map;
import java.util.Objects;

/**
 * A compiled Metal 4 compute kernel: the pipeline state a dispatch runs, the bindings it reads through, and the
 * argument table those bindings are filled into.
 * <p>
 * <strong>The handle holds the state it dispatches with, and describes the table a dispatch is bound
 * through.</strong> A Metal 4 dispatch is bound by {@code setArgumentTable:} and nothing else - there are no
 * per-resource setters on the new compute encoder - so every dispatch needs a table sized to the argument counts
 * the translation gave its kernel. That table is made per dispatch and not kept here: one table object
 * re-pointed and handed to the same encoder twice is not reliably re-read, which
 * {@link #newTable(MTLDevice)} records as the measured rule it is. The pipeline state is a compiled object with no per-dispatch state, so the compilation
 * context caches one per kernel and every handle to that kernel shares it; but <em>shared</em> is a refcount and
 * not a hand-over, which is why the constructor retains the state and {@link #close()} hands that reference to
 * the device's deferred release instead of dropping it where it stands. Without the retain this handle would be
 * a borrowed pointer into a cache somebody else may clear: the context releases its own reference in
 * {@code clearCachesAfterGpuCompletion()}, which the game calls on every resource reload (F3+T), and a handle
 * whose state had been freed under it would hand a dangling pointer to the encoder on its next dispatch. With
 * it, a clear takes the context's reference and the handle keeps dispatching exactly as the Metal 3 handle - the
 * one that owns its state outright - does.
 * <p>
 * <p>
 * The bindings are the shared translator's record: one kind of resource each, with the slot that kind's table
 * reads it from. That is all a dispatch needs, and it is why this class holds no switch of its own.
 */
@Environment(EnvType.CLIENT)
final class Metal4ComputePipeline implements MetalComputePipelineResource {

    private final MetalDevice device;
    private final String label;
    private final String entryPoint;
    private final MemorySegment pipelineState;
    private final Map<String, MetalComputeTranslator.Binding> bindings;
    private final long bufferSlots;
    private final long textureSlots;
    private final long samplerSlots;

    private boolean closed;

    Metal4ComputePipeline(final MetalDevice device, final String label, final String entryPoint,
                          final MemorySegment pipelineState,
                          final Map<String, MetalComputeTranslator.Binding> bindings) {
        this.device = Objects.requireNonNull(device, "device");
        this.label = Objects.requireNonNull(label, "label");
        this.entryPoint = Objects.requireNonNull(entryPoint, "entryPoint");
        // The handle's own reference, so the context's cache clear cannot free the object out from under it.
        this.pipelineState = ObjC.retain(Objects.requireNonNull(pipelineState, "pipelineState"));
        this.bindings = Map.copyOf(bindings);

        // The table's limits are the translation's own counts, and not a fixed maximum: an argument table is made
        // for what a kernel uses, and reserving slots for resources the kernel never declared is memory the
        // driver cannot then use for anything else.
        long buffers = 0L;
        long textures = 0L;
        long samplers = 0L;
        for (MetalComputeTranslator.Binding binding : this.bindings.values()) {
            if (binding.bufferIndex() >= 0) {
                buffers = Math.max(buffers, binding.bufferIndex() + 1L);
            }
            if (binding.textureIndex() >= 0) {
                textures = Math.max(textures, binding.textureIndex() + 1L);
            }
            if (binding.samplerIndex() >= 0) {
                samplers = Math.max(samplers, binding.samplerIndex() + 1L);
            }
        }
        this.bufferSlots = buffers;
        this.textureSlots = textures;
        this.samplerSlots = samplers;
    }

    String label() {
        return this.label;
    }

    String entryPoint() {
        return this.entryPoint;
    }

    MemorySegment pipelineState() {
        return this.pipelineState;
    }

    Map<String, MetalComputeTranslator.Binding> bindings() {
        return this.bindings;
    }

    /**
     * A table for one dispatch, sized to what this kernel binds.
     * <p>
     * <strong>One table per dispatch, and this is a measured rule rather than a preference.</strong> A table
     * object handed to one compute encoder, re-pointed, and handed over again is not reliably re-read: the
     * second dispatch reads what the table held when it was first handed over. That was measured with the
     * cold-probe reproducer (`tools/metal4-cold-probe.sh --repro 8 --own one-encoder`): two dispatches through
     * one re-pointed table read the first colour on every even round, while a fresh table for the second
     * dispatch - or an encoder or a commit per dispatch - is clean eight rounds of eight. So the handle keeps
     * no table at all: the frame path makes one where it dispatches and gives it back when the slot that used
     * it has completed.
     *
     * @return a table for one dispatch, or null where this device will not make one
     */
    @Nullable
    MTL4ArgumentTable newTable(final MTLDevice device) {
        return MTL4ArgumentTable.create(device, this.bufferSlots, this.textureSlots, this.samplerSlots);
    }

    boolean closed() {
        return this.closed;
    }

    /**
     * Hands this handle's reference to the state back and marks the handle spent.
     * <p>
     * There is no table to release: the tables belong to the dispatches that filled them, and the frame path
     * gives each one back through its destruction queue.
     * <p>
     * The state is shared, so this releases <em>this handle's reference</em> and not the object: the context
     * holds one of its own, and another handle to the same kernel may hold one too, and the refcount is what
     * makes the sharing safe rather than a way to free somebody else's object early. The release is deferred
     * through the device's destruction queue because work already encoded may still read the state - which is
     * exactly what the Metal 3 handle does with the state it owns outright, and the reason neither generation
     * releases one where it stands.
     */
    @Override
    public void close() {
        if (this.closed) {
            return;
        }
        this.closed = true;
        this.device.queueResourceRelease(this.pipelineState);
    }

    @Override
    public String toString() {
        return "Metal4ComputePipeline[" + this.label + "]";
    }
}
