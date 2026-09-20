package com.metallum.render.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
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
 * <strong>The table is this handle's, the state is the context's.</strong> A Metal 4 dispatch is bound by
 * {@code setArgumentTable:} and nothing else - there are no per-resource setters on the new compute encoder - so
 * a kernel has to carry the table it is dispatched through, sized to the argument counts the translation gave it.
 * The pipeline state itself is a compiled object with no per-dispatch state, so it is cached by the compilation
 * context and shared by every handle to the same kernel, and it is released there rather than here.
 * <p>
 * <strong>One table is enough for any number of dispatches.</strong> The header says the table is snapshotted when
 * a dispatch is encoded, which the cold record measured with one table re-pointed between two dispatches - so a
 * kernel re-pointing its table per dispatch is the design, and a second table would be another object with no
 * question of its own to answer.
 * <p>
 * The bindings are the shared translator's record: one kind of resource each, with the slot that kind's table
 * reads it from. That is all a dispatch needs, and it is why this class holds no switch of its own.
 */
@Environment(EnvType.CLIENT)
final class Metal4ComputePipeline implements MetalComputePipelineResource {

    private final String label;
    private final String entryPoint;
    private final MemorySegment pipelineState;
    private final Map<String, MetalComputeTranslator.Binding> bindings;
    private final long bufferSlots;
    private final long textureSlots;
    private final long samplerSlots;

    private boolean closed;
    private boolean tableAsked;
    @Nullable
    private MTL4ArgumentTable table;

    Metal4ComputePipeline(final String label, final String entryPoint, final MemorySegment pipelineState,
                          final Map<String, MetalComputeTranslator.Binding> bindings) {
        this.label = Objects.requireNonNull(label, "label");
        this.entryPoint = Objects.requireNonNull(entryPoint, "entryPoint");
        this.pipelineState = Objects.requireNonNull(pipelineState, "pipelineState");
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
     * The table this kernel's resources are filled into, made on first use.
     * <p>
     * Asked once: a device that will not make one will not make one on the next dispatch either, and the answer
     * is null for the caller to refuse rather than to retry - which is the same shape the storage clear takes
     * when it cannot get a table.
     */
    @Nullable
    MTL4ArgumentTable table(final MTLDevice device) {
        if (!this.tableAsked) {
            this.tableAsked = true;
            this.table = MTL4ArgumentTable.create(device, this.bufferSlots, this.textureSlots, this.samplerSlots);
        }
        return this.table;
    }

    boolean closed() {
        return this.closed;
    }

    /**
     * Releases the table this handle owns and marks the handle spent.
     * <p>
     * The pipeline state is not released here, and that is the difference from the Metal 3 resource: this
     * generation's state is shared by every handle to the same kernel and belongs to the compilation context,
     * which releases it once GPU completion is established. Releasing it from a handle would free an object
     * another handle is still dispatching through.
     */
    @Override
    public void close() {
        if (this.closed) {
            return;
        }
        this.closed = true;
        if (this.table != null) {
            this.table.close();
            this.table = null;
        }
    }

    @Override
    public String toString() {
        return "Metal4ComputePipeline[" + this.label + "]";
    }
}
