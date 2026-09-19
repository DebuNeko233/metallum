package com.metallum.render;

import com.metallum.render.shared.MetalFrameExtras;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;
import com.metallum.render.shared.AttachmentContents;

/**
 * The public door to the encoder's attachment-contents capability.
 *
 * <p>
 * Same reason as {@link MetalScaleBridge}: the pack-facing side reaches this backend by reflection
 * without a compile-time dependency, and a package-private declaring class refuses that however public
 * the method on it is. What crosses is still two booleans an attachment slot and never a resource name -
 * this class moves the door and changes nothing about what is behind it.
 */
@Environment(EnvType.CLIENT)
public final class MetalAttachmentBridge {

    private MetalAttachmentBridge() {
    }

    /**
     * The two facts a pass can state about its colour attachments, as the primitives the pack-facing side
     * decides them in.
     *
     * <p>
     * This is the door Vitrail uses, and it takes primitives on purpose. The value type lives in
     * {@link AttachmentContents}, which is this layer's own; the pack-facing engine neither has it on its
     * classpath nor has anything to say with it - it decided "something reads this afterwards" and "this pass
     * writes every pixel of it", and those two arrays are the whole of what it knows. Handing the record
     * across that boundary made the shape of this layer part of an ABI resolved at runtime, where a moved or
     * renamed type stops answering without failing: the string {@code com.metallum.render.AttachmentContents}
     * resolves to nothing, because the type is in {@code render.shared}, and it failed silently behind one
     * debug line for as long as it existed.
     *
     * @param readAfterwards one entry per colour attachment slot, in draw buffer order; null to say nothing
     * @param overwritten    one entry per slot, in the same order; a short or null array reads as false
     */
    public static void setNextPassContents(final Object encoder, final @Nullable boolean[] readAfterwards,
                                           final @Nullable boolean[] overwritten) {
        if (encoder instanceof MetalFrameExtras frameEncoder) {
            frameEncoder.setNextPassContents(contentsOf(readAfterwards, overwritten));
        }
    }

    /**
     * The same two facts as the value type this layer owns, one entry per slot.
     *
     * <p>
     * Nothing stated at all stays {@code null}, which is the interface's own spelling of "let the encoder
     * default them" - and that default is {@link AttachmentContents#CARRIED}, the answer that changes nothing.
     * A slot the caller did not describe is carried and not assumed overwritten, which is the same default
     * applied per slot.
     */
    private static @Nullable AttachmentContents[] contentsOf(final @Nullable boolean[] readAfterwards,
                                                             final @Nullable boolean[] overwritten) {
        int slots = Math.max(
                readAfterwards == null ? 0 : readAfterwards.length,
                overwritten == null ? 0 : overwritten.length);
        if (slots == 0) {
            return null;
        }

        AttachmentContents[] contents = new AttachmentContents[slots];
        for (int index = 0; index < slots; index++) {
            contents[index] = new AttachmentContents(
                    readAfterwards == null || index >= readAfterwards.length || readAfterwards[index],
                    overwritten != null && index < overwritten.length && overwritten[index]);
        }

        return contents;
    }

    /** @see MetalFrameExtras#setNextPassReadsStorageImage(boolean) */
    public static void setNextPassReadsStorageImage(final Object encoder, final boolean reads) {
        if (encoder instanceof MetalFrameExtras frameEncoder) {
            frameEncoder.setNextPassReadsStorageImage(reads);
        }
    }
}
