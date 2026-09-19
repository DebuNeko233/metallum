package com.metallum.render.shared;

import com.mojang.blaze3d.GpuFormat;
import org.jspecify.annotations.Nullable;

/**
 * One binding a compiled pipeline declares: what it is, what the pack called it, and where it lands.
 * <p>
 * This is the neutral half of what used to be a nested record inside the Metal 3 pipeline object, and it
 * is here for the reason the shared layer exists: two command generations bind the same resources, and the
 * only part of a binding that belongs to a generation is <em>how</em> it is handed over - an argument buffer
 * on one, a table slot on the other - which is what the version-specific fields beside this record carry.
 * <p>
 * The indices are the ones the shader was compiled against and therefore belong to no generation: a
 * {@code metalIndex} means the same slot number whichever way the encoder is told about it.
 *
 * @param kind                what kind of resource this is
 * @param name                the name the pack declared, which is how diagnostics name it
 * @param bindingIndex        the index in the pack's own binding layout
 * @param stageMask           which stages read it
 * @param texelBufferFormat   the format where this is a texel buffer, which Metal needs at bind time
 * @param metalIndex          the slot the compiled MSL reads this resource from
 * @param samplerMetalIndex   the slot its sampler is read from, where it has one
 * @param argumentBufferSet   the argument buffer this binding is carried by, or {@code -1} where it is bound
 *                            directly
 */
public record MetalResourceBinding(
        ResourceKind kind,
        String name,
        int bindingIndex,
        int stageMask,
        @Nullable GpuFormat texelBufferFormat,
        int metalIndex,
        int samplerMetalIndex,
        int argumentBufferSet
) {

    /** Whether this binding reaches the encoder through an argument buffer rather than directly. */
    public boolean indirect() {
        return this.argumentBufferSet >= 0;
    }

    /** What kind of resource a binding names, in the engine's own terms rather than Metal's. */
    public enum ResourceKind {
        UNIFORM_BUFFER,
        SAMPLED_IMAGE,
        STORAGE_IMAGE,
        TEXEL_BUFFER,
        STORAGE_BUFFER
    }
}
