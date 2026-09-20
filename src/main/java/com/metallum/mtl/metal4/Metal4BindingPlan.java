package com.metallum.mtl.metal4;

import com.metallum.render.shared.MetalResourceBinding;
import com.metallum.render.shared.MetalShaderStages;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Where a compiled pipeline's resources are read from: the table slot and the stage for every binding the
 * translation named.
 * <p>
 * This is the Metal 4 half of the binding question. The shared translation already decided <em>what</em> a program
 * binds and what the MSL calls each one - the metal index of a buffer, the texture and sampler indices of a
 * sampled image - and this class turns that into the shape a table is filled in: which stage's table a resource
 * belongs to, which slot in it, and how many slots each stage's table needs. It exists so that filling a table
 * per frame is a lookup and not a discovery: the plan is built once, when a pipeline is compiled.
 * <p>
 * <strong>It is in the bindings layer rather than the frame path because it is the table's own shape.</strong>
 * {@link MTL4ArgumentTable} is here too, and the one thing a plan produces is the arguments to that class's
 * factory - which is also what lets the cold probe measure a plan on the device without a window in it.
 * <p>
 * <strong>Vertex buffers are not in {@link #slots()}.</strong> A vertex buffer is not a resource a shader names;
 * it is a layout the pipeline's vertex descriptor describes, and it is bound by address and stride at the buffer
 * slots after the ones the named bindings use. The plan carries that region - {@link #firstVertexBufferSlot()}
 * and {@link #vertexBufferCount()} - and {@link #bufferSlots(int)} accounts for it, because a table has to cover
 * the highest index it will be given rather than the number of names.
 */
@Environment(EnvType.CLIENT)
public final class Metal4BindingPlan {

    /**
     * One named resource's place: what it is, which stage reads it, and the indices the MSL was compiled
     * against.
     *
     * @param kind              what kind of resource this is
     * @param name              the name the pack declared, which is how the frame path looks it up
     * @param logicalIndex      the index in the pack's own binding layout, kept for diagnostics
     * @param stageMask         which stages read it, as {@link MetalShaderStages} masks
     * @param metalIndex        the buffer or texture slot the compiled MSL reads it from
     * @param samplerMetalIndex the slot its sampler is read from, or -1 where it has none
     */
    public record Slot(MetalResourceBinding.ResourceKind kind, String name, int logicalIndex, int stageMask,
                       int metalIndex, int samplerMetalIndex) {

        /** Whether this slot is filled with a buffer address rather than with a resource id. */
        public boolean buffer() {
            return this.kind == MetalResourceBinding.ResourceKind.UNIFORM_BUFFER
                    || this.kind == MetalResourceBinding.ResourceKind.STORAGE_BUFFER;
        }

        /** Whether this slot is filled with a texture, which includes a texel buffer. */
        public boolean texture() {
            return !buffer();
        }

        /** Whether this slot has a sampler beside it. */
        public boolean sampled() {
            return this.samplerMetalIndex >= 0;
        }

        /** Whether this resource is read by the given stage. */
        public boolean readBy(final int stage) {
            return (this.stageMask & stage) != 0;
        }
    }

    private final List<Slot> slots;
    private final Map<String, Slot> byName;
    private final int firstVertexBufferSlot;
    private final int vertexBufferCount;

    private Metal4BindingPlan(final List<Slot> slots, final int firstVertexBufferSlot, final int vertexBufferCount) {
        this.slots = List.copyOf(slots);
        Map<String, Slot> named = new LinkedHashMap<>();
        for (Slot slot : this.slots) {
            named.put(slot.name(), slot);
        }
        this.byName = Map.copyOf(named);
        this.firstVertexBufferSlot = firstVertexBufferSlot;
        this.vertexBufferCount = vertexBufferCount;
    }

    /**
     * The plan for a compiled pipeline's bindings.
     *
     * @param resources            what the translation said the program binds
     * @param firstVertexBufferSlot the first buffer slot the pipeline's vertex layouts use
     * @param vertexBufferCount    how many vertex layouts the pipeline declares
     */
    public static Metal4BindingPlan of(final List<MetalResourceBinding> resources, final int firstVertexBufferSlot,
                                       final int vertexBufferCount) {
        List<Slot> slots = resources.stream()
                .map(resource -> new Slot(resource.kind(), resource.name(), resource.bindingIndex(),
                        resource.stageMask(), resource.metalIndex(), resource.samplerMetalIndex()))
                .toList();
        return new Metal4BindingPlan(slots, firstVertexBufferSlot, vertexBufferCount);
    }

    /** Every named binding, in the order the translation declared them. */
    public List<Slot> slots() {
        return this.slots;
    }

    /** One binding by the name the pack gave it, or null where the pipeline does not declare it. */
    @Nullable
    public Slot slot(final String name) {
        return this.byName.get(name);
    }

    /** The first buffer slot this pipeline's vertex layouts use in the vertex stage's table. */
    public int firstVertexBufferSlot() {
        return this.firstVertexBufferSlot;
    }

    /** How many vertex layouts the pipeline declares. */
    public int vertexBufferCount() {
        return this.vertexBufferCount;
    }

    /**
     * How many buffer slots the given stage's table needs: one past the highest index the stage is given, which
     * includes the vertex layouts where the stage is the vertex one.
     */
    public int bufferSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.buffer() && slot.readBy(stage)) {
                highest = Math.max(highest, slot.metalIndex());
            }
        }
        if ((stage & MetalShaderStages.VERTEX) != 0 && this.vertexBufferCount > 0) {
            highest = Math.max(highest, this.firstVertexBufferSlot + this.vertexBufferCount - 1);
        }
        return highest + 1;
    }

    /** How many texture slots the given stage's table needs. */
    public int textureSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.texture() && slot.readBy(stage)) {
                highest = Math.max(highest, slot.metalIndex());
            }
        }
        return highest + 1;
    }

    /** How many sampler slots the given stage's table needs. */
    public int samplerSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.sampled() && slot.readBy(stage)) {
                highest = Math.max(highest, slot.samplerMetalIndex());
            }
        }
        return highest + 1;
    }

    /** Whether the given stage reads anything at all through a table. */
    public boolean usesStage(final int stage) {
        if ((stage & MetalShaderStages.VERTEX) != 0 && this.vertexBufferCount > 0) {
            return true;
        }
        for (Slot slot : this.slots) {
            if (slot.readBy(stage)) {
                return true;
            }
        }
        return false;
    }

    /** One line describing the plan, for the log a session keeps about what a pack's pipelines bind. */
    public String describe() {
        StringBuilder words = new StringBuilder();
        words.append("buffers(v=").append(bufferSlots(MetalShaderStages.VERTEX))
                .append(",f=").append(bufferSlots(MetalShaderStages.FRAGMENT))
                .append(") textures(v=").append(textureSlots(MetalShaderStages.VERTEX))
                .append(",f=").append(textureSlots(MetalShaderStages.FRAGMENT))
                .append(") samplers(v=").append(samplerSlots(MetalShaderStages.VERTEX))
                .append(",f=").append(samplerSlots(MetalShaderStages.FRAGMENT))
                .append(") vertexLayouts=").append(this.vertexBufferCount)
                .append(" from slot ").append(this.firstVertexBufferSlot);
        return words.toString();
    }
}
