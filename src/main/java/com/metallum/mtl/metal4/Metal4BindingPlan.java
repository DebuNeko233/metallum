package com.metallum.mtl.metal4;

import com.metallum.render.shared.MetalArgumentBufferLayout;
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
     * @param argumentBufferSet the argument buffer that carries it, or -1 where the table carries it directly
     */
    public record Slot(MetalResourceBinding.ResourceKind kind, String name, int logicalIndex, int stageMask,
                       int metalIndex, int samplerMetalIndex, int argumentBufferSet) {

        /** Whether this slot is filled with a buffer address rather than with a resource id. */
        public boolean buffer() {
            return this.kind == MetalResourceBinding.ResourceKind.UNIFORM_BUFFER
                    || this.kind == MetalResourceBinding.ResourceKind.STORAGE_BUFFER;
        }

        /** Whether this slot is filled with a texture, which includes a texel buffer. */
        public boolean texture() {
            return !buffer();
        }

        /**
         * Whether this slot's indices are positions inside an argument buffer rather than table slots.
         * <p>
         * A wide pipeline's resources are handed over the way the reference generation hands them over - a
         * buffer an {@code MTLArgumentEncoder} wrote - and this generation's part is what carries that buffer:
         * one table slot for the argument buffer itself, at {@link MetalArgumentBufferLayout#bufferIndex()}.
         * The resource's own index is its index inside that buffer and means nothing to a table.
         */
        public boolean indirect() {
            return this.argumentBufferSet >= 0;
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
    /**
     * The same bindings, split by the kind of resource they name.
     * <p>
     * A name is not unique across kinds: one of the engine's own passes declares a texture under a name and
     * binds a uniform of the same name, and the Metal 3 pass encodes each in its own map because it keeps its
     * uniforms and its textures apart. One namespace here made the two collide, so the uniform was refused as
     * "a texture's name" - a fault that was about this plan and not about the frame.
     */
    private final Map<String, Slot> textureByName;
    private final Map<String, Slot> bufferByName;
    private final List<MetalArgumentBufferLayout> argumentBuffers;
    private final int firstVertexBufferSlot;
    private final int vertexBufferCount;

    private Metal4BindingPlan(final List<Slot> slots, final List<MetalArgumentBufferLayout> argumentBuffers,
                              final int firstVertexBufferSlot, final int vertexBufferCount) {
        this.slots = List.copyOf(slots);
        Map<String, Slot> named = new LinkedHashMap<>();
        Map<String, Slot> textures = new LinkedHashMap<>();
        Map<String, Slot> buffers = new LinkedHashMap<>();
        for (Slot slot : this.slots) {
            named.put(slot.name(), slot);
            (slot.texture() ? textures : buffers).put(slot.name(), slot);
        }
        this.byName = Map.copyOf(named);
        this.textureByName = Map.copyOf(textures);
        this.bufferByName = Map.copyOf(buffers);
        this.argumentBuffers = List.copyOf(argumentBuffers);
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
        return of(resources, List.of(), firstVertexBufferSlot, vertexBufferCount);
    }

    /**
     * The same for a pipeline the translation made wide, whose resources are carried by argument buffers.
     *
     * @param resources            what the translation said the program binds
     * @param argumentBuffers      the argument buffers those bindings are written into
     * @param firstVertexBufferSlot the first buffer slot the pipeline's vertex layouts use
     * @param vertexBufferCount    how many vertex layouts the pipeline declares
     */
    public static Metal4BindingPlan of(final List<MetalResourceBinding> resources,
                                       final List<MetalArgumentBufferLayout> argumentBuffers,
                                       final int firstVertexBufferSlot, final int vertexBufferCount) {
        List<Slot> slots = resources.stream()
                .map(resource -> new Slot(resource.kind(), resource.name(), resource.bindingIndex(),
                        resource.stageMask(), resource.metalIndex(), resource.samplerMetalIndex(),
                        resource.argumentBufferSet()))
                .toList();
        return new Metal4BindingPlan(slots, argumentBuffers, firstVertexBufferSlot, vertexBufferCount);
    }

    /**
     * The argument buffers this pipeline's resources are written into, each with the stage and buffer slot its
     * table has to cover. Empty for a pipeline whose bindings fit the table's own slots.
     */
    public List<MetalArgumentBufferLayout> argumentBuffers() {
        return this.argumentBuffers;
    }

    /** Whether any of this pipeline's bindings reach the shader through an argument buffer. */
    public boolean usesArgumentBuffers() {
        return !this.argumentBuffers.isEmpty();
    }

    /** Every named binding, in the order the translation declared them. */
    public List<Slot> slots() {
        return this.slots;
    }

    /**
     * The slot this name has for this kind of resource, or null where this pipeline has none of that kind.
     * <p>
     * Kind-aware because a layout can hold a buffer and a texture under one name; a name this pipeline declares
     * only as the other kind is a null here, and the caller decides whether that is a skip or a fault.
     */
    public Slot slot(final String name, final boolean texture) {
        return (texture ? this.textureByName : this.bufferByName).get(name);
    }

    /** Whether this pipeline declares a binding by this name at all, whichever kind it is. */
    public boolean declares(final String name) {
        return this.byName.containsKey(name);
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
     * includes the vertex layouts where the stage is the vertex one, and one slot per argument buffer the stage
     * reads.
     * <p>
     * <strong>A binding an argument buffer carries is skipped here, and the table would not fit if it were
     * not.</strong> That binding's metal index is its position <em>inside</em> the argument buffer - the
     * translation numbers them two at a time, buffer and texture, so a twenty-entry layout reaches thirty-nine -
     * and a table sized to that number would be a table of forty buffer slots, which Metal caps at thirty-one.
     * What the table has to cover for such a pipeline is the argument buffer itself, one slot at the index the
     * shared layout recorded, and that is what this adds.
     */
    public int bufferSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.buffer() && !slot.indirect() && slot.readBy(stage)) {
                highest = Math.max(highest, slot.metalIndex());
            }
        }
        for (MetalArgumentBufferLayout argumentBuffer : this.argumentBuffers) {
            if ((argumentBuffer.stageMask() & stage) != 0) {
                highest = Math.max(highest, argumentBuffer.bufferIndex());
            }
        }
        if ((stage & MetalShaderStages.VERTEX) != 0 && this.vertexBufferCount > 0) {
            highest = Math.max(highest, this.firstVertexBufferSlot + this.vertexBufferCount - 1);
        }
        return highest + 1;
    }

    /** How many texture slots the given stage's table needs, which an argument-buffer binding needs none of. */
    public int textureSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.texture() && !slot.indirect() && slot.readBy(stage)) {
                highest = Math.max(highest, slot.metalIndex());
            }
        }
        return highest + 1;
    }

    /** How many sampler slots the given stage's table needs, which is where Metal's ceiling of sixteen bites. */
    public int samplerSlots(final int stage) {
        int highest = -1;
        for (Slot slot : this.slots) {
            if (slot.sampled() && !slot.indirect() && slot.readBy(stage)) {
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
        if (!this.argumentBuffers.isEmpty()) {
            words.append(" argumentBuffers=").append(this.argumentBuffers.size());
        }
        return words.toString();
    }
}
