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

    /** @see MetalFrameExtras#setNextPassContents(AttachmentContents[]) */
    public static void setNextPassContents(final Object encoder, final @Nullable AttachmentContents[] contents) {
        if (encoder instanceof MetalFrameExtras frameEncoder) {
            frameEncoder.setNextPassContents(contents);
        }
    }

    /** @see MetalFrameExtras#setNextPassReadsStorageImage(boolean) */
    public static void setNextPassReadsStorageImage(final Object encoder, final boolean reads) {
        if (encoder instanceof MetalFrameExtras frameEncoder) {
            frameEncoder.setNextPassReadsStorageImage(reads);
        }
    }
}
