package com.metallum.mtl.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import com.metallum.render.shared.AttachmentContents;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * One Metal 4 render pass: the descriptor its attachments are described on, and the encoder opened from it.
 * <p>
 * This is where the engine's two facts about an attachment - whether anything reads it afterwards, and whether
 * this pass writes every pixel of it - become the load and store actions a tile-based GPU actually pays for.
 * The mapping is the Metal 3 one, kept deliberately identical because the images have to be identical:
 * <ul>
 *   <li>a clear beats the load question, because a pass that asked to be handed a colour is not asking to be
 *       handed what stood there;</li>
 *   <li>otherwise an attachment this pass overwrites entirely is loaded {@code DontCare}, and one it does not
 *       is loaded - the default being the answer that changes nothing;</li>
 *   <li>an attachment nothing reads afterwards is stored {@code DontCare}, and one something reads is stored.
 *       </li>
 * </ul>
 * The Metal 3 layer does this in {@code MTLCommandBuffer}; it is here rather than in the pass object because the
 * actions are the descriptor's own shape, and because a pass object that computed them would be a second place
 * the same two facts could be read differently.
 * <p>
 * <strong>The descriptor's classes are Metal 3's.</strong> Read off this machine's SDK rather than assumed:
 * {@code MTL4RenderPass.h:33} declares {@code colorAttachments} as an
 * {@code MTLRenderPassColorAttachmentDescriptorArray} and line 36 declares {@code depthAttachment} as a
 * {@code MTLRenderPassDepthAttachmentDescriptor}, so the attachment objects - and their clear colours and clear
 * depth - are the ones the engine already sets on its Metal 3 passes.
 * <p>
 * The pass is opened, used and ended; it owns nothing the frame owns. Its lifetime is one pass, and the
 * command buffer it writes into belongs to the caller.
 */
@Environment(EnvType.CLIENT)
public final class MTL4RenderEncoder implements AutoCloseable {

    /** {@code MTLLoadActionLoad}: the attachment's contents are handed to the pass. */
    public static final long LOAD_LOAD = 1L;
    /** {@code MTLLoadActionClear}: the pass is handed the clear colour instead, and {@link #LOAD_LOAD} is moot. */
    public static final long LOAD_CLEAR = 2L;
    /** {@code MTLLoadActionDontCare}: the contents are undefined to the pass, which is what skipping a load buys. */
    public static final long LOAD_DONT_CARE = 0L;
    /** {@code MTLStoreActionStore}: the pass's result is written back for whatever reads it next. */
    public static final long STORE_STORE = 1L;
    /** {@code MTLStoreActionDontCare}: nothing reads it, so the tile memory need not be written back. */
    public static final long STORE_DONT_CARE = 0L;

    private static final Msg NEW_RENDER_PASS = Msg.of("new", ADDRESS);
    private static final Msg SET_TARGET_WIDTH = Msg.ofVoid("setRenderTargetWidth:", JAVA_LONG);
    private static final Msg SET_TARGET_HEIGHT = Msg.ofVoid("setRenderTargetHeight:", JAVA_LONG);
    private static final Msg COLOR_ATTACHMENTS = Msg.of("colorAttachments", ADDRESS);
    private static final Msg DEPTH_ATTACHMENT = Msg.of("depthAttachment", ADDRESS);
    private static final Msg ATTACHMENT_AT = Msg.of("objectAtIndexedSubscript:", ADDRESS, JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:", ADDRESS);
    private static final Msg SET_LOAD_ACTION = Msg.ofVoid("setLoadAction:", JAVA_LONG);
    private static final Msg SET_STORE_ACTION = Msg.ofVoid("setStoreAction:", JAVA_LONG);
    private static final Msg SET_CLEAR_COLOR = Msg.ofVoid("setClearColor:",
            JAVA_DOUBLE, JAVA_DOUBLE, JAVA_DOUBLE, JAVA_DOUBLE);
    private static final Msg SET_CLEAR_DEPTH = Msg.ofVoid("setClearDepth:", JAVA_DOUBLE);
    private static final Msg RENDER_ENCODER = Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg END_ENCODING = Msg.ofVoid("endEncoding");
    /** The producer barrier, and the two masks it is encoded with: everything, and visible device-wide. */
    private static final Msg BARRIER = Msg.ofVoid("barrierAfterStages:beforeQueueStages:visibilityOptions:",
            JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);
    private static final long STAGE_ALL = Long.MAX_VALUE;
    private static final long VISIBILITY_DEVICE = 1L;

    @Nullable
    private MemorySegment encoder;
    @Nullable
    private MemorySegment descriptor;
    private final String which;
    private boolean ended;

    private MTL4RenderEncoder(final MemorySegment descriptor, final MemorySegment encoder, final String which) {
        this.descriptor = descriptor;
        this.encoder = encoder;
        this.which = which;
    }

    /**
     * What one colour attachment needs: the texture, and the two facts about its contents.
     *
     * @param texture  the colour attachment, as the texture the view wraps
     * @param contents what the pass said about this attachment's lifetime, or {@link AttachmentContents#CARRIED}
     * @param clear    the colour to clear to, or null where the pass loads what stood there
     */
    public record Color(MemorySegment texture, AttachmentContents contents, @Nullable float[] clear) {

        /** The same, for an attachment this pass clears, which is the one fact that needs no contents. */
        public static Color cleared(final MemorySegment texture, final float[] color) {
            return new Color(texture, AttachmentContents.CARRIED, color);
        }
    }

    /**
     * What the depth attachment needs: the texture, the depth to clear to, and whether it is cleared at all.
     *
     * @param texture the depth attachment
     * @param clearDepth the depth to clear to, or null where the pass loads what stood there
     */
    public record Depth(MemorySegment texture, @Nullable Double clearDepth) {
    }

    /**
     * Opens a render pass over the attachments it is handed.
     * <p>
     * Every attachment is asked for by name before it is sent, and each step that can come back nil is named:
     * a descriptor the device will not make and an encoder that will not open read the same way in a log
     * otherwise, and they are different faults.
     *
     * @throws Refused when the descriptor or the encoder could not be made, naming the stage
     */
    public static MTL4RenderEncoder open(final MTLDevice device, final MemorySegment commandBuffer,
                                         final long width, final long height, final Color[] colors,
                                         final @Nullable Depth depth, final String which) {
        if (ObjC.isNil(commandBuffer)) {
            throw new Refused("commandBuffer", which + " was given no command buffer to encode into");
        }

        MemorySegment descriptor = MemorySegment.NULL;
        MemorySegment encoder = MemorySegment.NULL;
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            descriptor = NEW_RENDER_PASS.sendPtr(ObjC.clazz("MTL4RenderPassDescriptor"));
            if (ObjC.isNil(descriptor)) {
                throw new Refused("descriptor", which + " could not make an MTL4RenderPassDescriptor");
            }
            SET_TARGET_WIDTH.send(descriptor, width);
            SET_TARGET_HEIGHT.send(descriptor, height);

            MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(descriptor);
            if (ObjC.isNil(attachments) && colors.length > 0) {
                throw new Refused("colorAttachments", which + " asked for " + colors.length + " colour"
                        + " attachments and the descriptor answered none");
            }
            for (int index = 0; index < colors.length; index++) {
                Color color = colors[index];
                if (ObjC.isNil(color.texture())) {
                    throw new Refused("colorAttachment", which + "'s colour attachment " + index + " is nil, and a"
                            + " pass cannot be described around a texture that is not there");
                }
                MemorySegment attachment = ATTACHMENT_AT.sendPtr(attachments, index);
                if (ObjC.isNil(attachment)) {
                    throw new Refused("colorAttachment", which + "'s descriptor gave no colour attachment at index "
                            + index);
                }
                SET_TEXTURE.send(attachment, color.texture());
                SET_LOAD_ACTION.send(attachment, loadAction(color.contents(), color.clear() != null));
                SET_STORE_ACTION.send(attachment, storeAction(color.contents()));
                if (color.clear() != null) {
                    float[] clear = color.clear();
                    SET_CLEAR_COLOR.send(attachment, clear[0], clear[1], clear[2], clear[3]);
                }
            }

            if (depth != null) {
                if (ObjC.isNil(depth.texture())) {
                    throw new Refused("depthAttachment", which + " was handed a depth attachment that is nil");
                }
                MemorySegment attachment = DEPTH_ATTACHMENT.sendPtr(descriptor);
                if (ObjC.isNil(attachment)) {
                    throw new Refused("depthAttachment", which + "'s descriptor gave no depth attachment");
                }
                SET_TEXTURE.send(attachment, depth.texture());
                SET_LOAD_ACTION.send(attachment, depth.clearDepth() != null ? LOAD_CLEAR : LOAD_LOAD);
                // Depth is never discarded: a later pass reads it, and the engine's own Metal 3 path has always
                // stored it. A depth attachment nobody reads is a question for a counter, not for a guess.
                SET_STORE_ACTION.send(attachment, STORE_STORE);
                if (depth.clearDepth() != null) {
                    SET_CLEAR_DEPTH.send(attachment, depth.clearDepth());
                }
            }

            encoder = RENDER_ENCODER.sendPtr(commandBuffer, descriptor);
            if (ObjC.isNil(encoder)) {
                throw new Refused("encoder", which + "'s render command encoder could not be opened on the"
                        + " Metal 4 command buffer");
            }
            // The command buffer autoreleases the encoder and the pool this method pushed is about to drain, so
            // it is retained here and released by close(). Measured the hard way: without the retain the first
            // message to the encoder is a segfault in objc_msgSend rather than a nil check, because the object
            // the handle names has already gone back.
            return new MTL4RenderEncoder(descriptor, ObjC.retain(encoder), which);
        }
    }

    /**
     * The load action an attachment's contents ask for, with a clear beating the load question.
     * <p>
     * Public because it is the mapping itself, and a mapping that can only be read inside the call that uses it
     * is a mapping no run can answer separately from the pass it was part of.
     */
    public static long loadAction(final AttachmentContents contents, final boolean cleared) {
        if (cleared) {
            return LOAD_CLEAR;
        }
        return contents.overwritten() ? LOAD_DONT_CARE : LOAD_LOAD;
    }

    /** The store action an attachment's contents ask for: stored where something reads it, discarded otherwise. */
    public static long storeAction(final AttachmentContents contents) {
        return contents.readAfterwards() ? STORE_STORE : STORE_DONT_CARE;
    }

    /** The native encoder, for the commands that will be encoded into it. */
    public MemorySegment encoder() {
        return this.encoder == null ? MemorySegment.NULL : this.encoder;
    }

    /**
     * Encodes the producer barrier: everything this pass has written becomes visible to the encoders that
     * follow it in the same command buffer.
     * <p>
     * The new command model does not order two encoders for the caller - {@code MTL4CommandEncoder.h} documents
     * the barrier as the mechanism, and a pass that reads what an earlier pass wrote has to say so. Both
     * stage masks are {@code MTLStageAll}, which is more than a colour attachment needs and is the answer the
     * migration's section 62 asks for while the frame path is being built: over-synchronise until a counter
     * says what the narrowing would buy.
     *
     * @return whether the barrier was encoded; false where the encoder does not answer the selector, which the
     *         caller has to treat as a missing dependency rather than as a satisfied one
     */
    public boolean barrierForSubsequentEncoders() {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            return false;
        }
        if (!responds(open, BARRIER.name())) {
            return false;
        }
        BARRIER.send(open, STAGE_ALL, STAGE_ALL, VISIBILITY_DEVICE);
        return true;
    }

    /** Whether this pass is still open. */
    public boolean open() {
        return this.encoder != null && !this.ended;
    }

    /** Ends the pass. Ending it twice is a no-op rather than an error, because a caller may end it on any path. */
    public void endEncoding() {
        if (this.ended || this.encoder == null) {
            return;
        }
        this.ended = true;
        END_ENCODING.send(this.encoder);
    }

    /** Whether an object answers a selector, which is the question to ask before reaching for one. */
    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    /** The name this pass was opened under, for a message that has to say which pass it was. */
    public String which() {
        return this.which;
    }

    /** Ends the pass where it is still open, then releases the encoder and the descriptor. */
    @Override
    public void close() {
        endEncoding();
        MemorySegment held = this.encoder;
        this.encoder = null;
        if (held != null) {
            ObjC.release(held);
        }
        MemorySegment made = this.descriptor;
        this.descriptor = null;
        if (made != null) {
            ObjC.release(made);
        }
    }

    /**
     * Why a pass could not be opened, carrying the stage that failed - the descriptor's own shape, the
     * attachments' handles, or the encoder itself.
     */
    public static final class Refused extends RuntimeException {

        private final String stage;

        Refused(final String stage, final String why) {
            super(why);
            this.stage = stage;
        }

        /** Which object came back nil, as the probe's stage names are spelled. */
        public String stage() {
            return this.stage;
        }
    }
}
