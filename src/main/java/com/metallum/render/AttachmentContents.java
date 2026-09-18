package com.metallum.render;

import org.jspecify.annotations.Nullable;

/**
 * What a render pass needs of one colour attachment's contents.
 * <p>
 * The public render-pass descriptor says how an attachment is loaded and nothing at all about what
 * becomes of it when the pass ends, so the two facts a tile-based GPU actually pays for have to
 * arrive beside it: whether anything reads the contents once this pass has ended, and whether this
 * pass writes every pixel of them anyway. On Apple silicon a pass begins by loading each attachment
 * into tile memory and ends by storing it back, so either fact being known is memory traffic that
 * stops happening without a shader reading anything different.
 * <p>
 * Neither field names a resource. The code that owns a pass knows which of its own attachments is
 * finished with; this is the whole of what it is allowed to say about them, and
 * {@code tools/ci-contracts.py} refuses the other direction on this side of the seam.
 * <p>
 * <strong>The default is {@link #CARRIED}.</strong> An attachment nobody has described is stored and
 * loaded, which is exactly what this backend did before either fact existed. A wrong
 * {@code DontCare} is not a slower frame, it is a wrong image that reads as a shader-pack defect, so
 * the uncertain answer has to be the one that changes nothing.
 *
 * @param readAfterwards whether anything reads the contents once this pass has ended. False skips
 *                       the store, and is only ever said from a positive lifetime fact
 * @param overwritten    whether this pass writes every pixel of the attachment. True skips the load,
 *                       and is only ever said from a draw that covers the whole attachment with a
 *                       fragment stage that cannot leave a pixel as it was
 */
public record AttachmentContents(boolean readAfterwards, boolean overwritten) {

    /**
     * What every attachment is taken to be when its pass says nothing about it: read afterwards, and
     * not assumed to be overwritten.
     */
    public static final AttachmentContents CARRIED = new AttachmentContents(true, false);

    /**
     * One answer per colour attachment slot, with {@link #CARRIED} wherever the pass said nothing.
     * <p>
     * The defaulting happens here rather than at each reader, because there are two of them and they
     * have to agree: the encoder compares one pass's answers against the next one's to decide whether
     * the two may share a Metal encoder, and the descriptor builder turns them into load and store
     * actions. Null, a short array and a null slot all mean the same thing at both.
     *
     * @param stated what the pass said, or null where it said nothing
     * @param slots  how many colour attachment slots the pass has
     */
    public static AttachmentContents[] resolve(
            @Nullable final AttachmentContents[] stated,
            final int slots
    ) {
        AttachmentContents[] resolved = new AttachmentContents[slots];
        for (int index = 0; index < slots; index++) {
            resolved[index] = stated != null && index < stated.length && stated[index] != null
                    ? stated[index]
                    : CARRIED;
        }

        return resolved;
    }
}
