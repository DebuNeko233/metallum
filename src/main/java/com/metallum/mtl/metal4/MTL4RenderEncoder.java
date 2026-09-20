package com.metallum.mtl.metal4;

import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLScissorRect;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import com.metallum.render.shared.AttachmentContents;
import com.metallum.render.shared.MetalFrameProbe;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import org.lwjgl.system.MemoryStack;

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
    private static final Msg SET_ARGUMENT_TABLE = Msg.ofVoid("setArgumentTable:atStages:", ADDRESS, JAVA_LONG);
    private static final Msg SET_PIPELINE_STATE = Msg.ofVoid("setRenderPipelineState:", ADDRESS);
    private static final Msg SET_DEPTH_STENCIL_STATE = Msg.ofVoid("setDepthStencilState:", ADDRESS);
    private static final Msg SET_CULL_MODE = Msg.ofVoid("setCullMode:", JAVA_LONG);
    private static final Msg SET_TRIANGLE_FILL_MODE = Msg.ofVoid("setTriangleFillMode:", JAVA_LONG);
    private static final Msg SET_SCISSOR_RECT = Msg.ofVoid("setScissorRect:", ADDRESS);
    private static final Msg DRAW = Msg.ofVoid(
            "drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:",
            JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);
    // The index buffer is an address on this model, and it is declared as one rather than as a long: the two are
    // the same register either way, but the header says MTLGPUAddress and the declaration should say so too.
    private static final Msg DRAW_INDEXED = Msg.ofVoid(
            "drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:"
                    + "baseInstance:",
            JAVA_LONG, JAVA_LONG, JAVA_LONG, ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);
    /**
     * An indirect indexed draw, whose arguments the GPU reads out of a buffer.
     * <p>
     * Five 32-bit members - {@code indexCount}, {@code instanceCount}, {@code indexStart}, {@code baseVertex} and
     * {@code baseInstance} - which is {@code MTLDrawIndexedPrimitivesIndirectArguments} in this machine's
     * {@code MTLRenderCommandEncoder.h} and twenty bytes. The index buffer is still an <em>address</em> here, and
     * the header asks for the same treatment as the direct form: "Use an instance of {@code MTLResidencySet} to
     * mark residency of the indirect buffer that the {@code indirectBuffer} parameter references, and of the
     * index buffer the {@code indexBuffer} parameter references."
     * <p>
     * One command is one draw, so a caller with several arguments in one buffer encodes this once per command -
     * which is what makes the caller's stride the thing that has to be right.
     */
    private static final Msg DRAW_INDEXED_INDIRECT = Msg.ofVoid(
            "drawIndexedPrimitives:indexType:indexBuffer:indexBufferLength:indirectBuffer:",
            JAVA_LONG, JAVA_LONG, ADDRESS, JAVA_LONG, ADDRESS);

    private static final long STAGE_ALL = Long.MAX_VALUE;
    private static final long VISIBILITY_DEVICE = 1L;

    @Nullable
    private MemorySegment encoder;
    @Nullable
    private MemorySegment descriptor;
    private final String which;
    private boolean ended;
    /** Why the last draw answered no, where one has been refused. */
    private String refusal;

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

    /**
     * Counts one colour attachment's traffic against the frame probe, with the actions this descriptor will be
     * opened with.
     * <p>
     * Beside {@link #loadAction} and {@link #storeAction} on purpose: a counter fed by its caller's own
     * restatement of the mapping is a reading that can drift from what Metal was actually asked for, and these
     * numbers are what the migration's attachment traffic is judged by. Every pass this path opens - the game's
     * passes, a clear's pass of its own, the present - counts through here, so the total is the frame's and not
     * a subset's.
     *
     * @param pixelSize the attachment's bytes per pixel, which lives with the texture's format and not in this
     *                  handle layer
     */
    public static void countAttachment(final Color color, final int pixelSize) {
        MetalFrameProbe.attachment(
                color.texture(),
                pixelSize,
                loadAction(color.contents(), color.clear() != null) == LOAD_LOAD,
                storeAction(color.contents()) == STORE_STORE
        );
    }

    /**
     * The depth half of {@link #countAttachment(Color, int)}.
     * <p>
     * The depth slot is the one the pack side cannot answer for, so it is counted apart from the colour totals as
     * well as inside them, and its store is always a store: a later pass reads depth, and this engine has always
     * stored it.
     */
    public static void countDepthAttachment(final Depth depth, final int pixelSize) {
        MetalFrameProbe.depthAttachment(depth.texture(), pixelSize, depth.clearDepth() == null, true);
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

    // ---------------------------------------------------------------- the commands a draw needs

    /**
     * Hands the encoder a filled table for the stages that will read it.
     * <p>
     * This is the whole binding mechanism of the new model: there is no per-resource setter, so a pass binds by
     * filling a table and assigning it. The assignment is checked rather than assumed, because an encoder that
     * answered no here would leave the draw reading whatever the last table held.
     */
    public boolean setArgumentTable(final MTL4ArgumentTable table, final long stages) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || table == null) {
            return false;
        }
        if (!responds(open, SET_ARGUMENT_TABLE.name())) {
            return false;
        }
        SET_ARGUMENT_TABLE.send(open, table.handle(), stages);
        return true;
    }

    /** The pipeline state the draws use, which comes from the compiled artifact for this pass's attachments. */
    public boolean setRenderPipelineState(final MemorySegment pipelineState) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(pipelineState)) {
            return false;
        }
        SET_PIPELINE_STATE.send(open, pipelineState);
        return true;
    }

    /** The depth-stencil state the draws use, which the compiled artifact already owns. */
    public boolean setDepthStencilState(final MemorySegment depthStencilState) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(depthStencilState)) {
            return false;
        }
        SET_DEPTH_STENCIL_STATE.send(open, depthStencilState);
        return true;
    }

    /** {@code MTLCullMode}, as the compiled pipeline's own culling answer. */
    public boolean setCullMode(final long cullMode) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            return false;
        }
        SET_CULL_MODE.send(open, cullMode);
        return true;
    }

    /** {@code MTLTriangleFillMode}, the pipeline's polygon mode taken to the encoder. */
    public boolean setTriangleFillMode(final long fillMode) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            return false;
        }
        SET_TRIANGLE_FILL_MODE.send(open, fillMode);
        return true;
    }

    /**
     * One scissor rectangle, passed the way the header declares it: {@code MTLScissorRect} is four unsigned
     * integers, which arm64 hands over as a pointer to the struct - the same shape the Metal 3 encoder sends.
     */
    public boolean setScissorRect(final long x, final long y, final long width, final long height) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            return false;
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            SET_SCISSOR_RECT.send(open, MTLScissorRect.on(stack, x, y, width, height));
        }
        return true;
    }

    /**
     * A non-indexed draw, in the shape the engine's own draws take: vertex count, instance count, where the
     * vertices start, and which instance the first one is.
     */
    public boolean drawPrimitives(final long primitiveType, final long vertexStart, final long vertexCount,
                                  final long instanceCount, final long baseInstance) {
        this.refusal = null;
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            this.refusal = "the pass " + this.which + " is not open, so there is no encoder to draw on";
            return false;
        }
        if (vertexCount <= 0L) {
            this.refusal = "the draw asks for " + vertexCount + " vertices";
            return false;
        }
        if (!responds(open, DRAW.name())) {
            this.refusal = "the encoder does not answer " + DRAW.name();
            return false;
        }
        DRAW.send(open, primitiveType, vertexStart, vertexCount, instanceCount, baseInstance);
        return true;
    }

    /**
     * An indexed draw, whose index buffer is an <em>address</em> on the new model rather than a bound buffer:
     * the engine's first index becomes an offset into that address, and the base vertex and base instance are
     * the draw's own, which is why all three are parameters here and none is state.
     * <p>
     * The selector has <strong>eight</strong> arguments, read off this machine's
     * {@code MTL4RenderCommandEncoder.h} rather than remembered: the form without {@code baseInstance:} does
     * not exist, and a declaration that is one argument short makes {@code respondsToSelector:} answer no - so
     * the guard below reports a missing selector rather than a message send with the wrong arity. The first
     * version of this method was that mistake.
     */
    public boolean drawIndexedPrimitives(final long primitiveType, final long indexCount, final long indexType,
                                         final long indexBufferAddress, final long indexBufferLength,
                                         final long instanceCount, final long baseVertex, final long baseInstance) {
        this.refusal = null;
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            this.refusal = "the pass " + this.which + " is not open, so there is no encoder to draw on";
            return false;
        }
        if (indexCount <= 0L) {
            this.refusal = "the indexed draw asks for " + indexCount + " indices";
            return false;
        }
        if (indexBufferAddress == 0L) {
            this.refusal = "the index buffer has no GPU address, so there is nothing to read " + indexCount
                    + " indices from";
            return false;
        }
        if (!responds(open, DRAW_INDEXED.name())) {
            this.refusal = "the encoder does not answer " + DRAW_INDEXED.name();
            return false;
        }
        DRAW_INDEXED.send(open, primitiveType, indexCount, indexType, MemorySegment.ofAddress(indexBufferAddress),
                indexBufferLength, instanceCount, baseVertex, baseInstance);
        return true;
    }

    /**
     * An indexed draw whose arguments come from a buffer, which is how a chunk renderer asks for many draws
     * without the CPU knowing what they are.
     * <p>
     * Same refusals as the direct form and for the same reason: a zero address is a draw with nothing to read,
     * and saying so is worth more than a draw that silently did nothing.
     */
    public boolean drawIndexedPrimitivesIndirect(final long primitiveType, final long indexType,
                                                 final long indexBufferAddress, final long indexBufferLength,
                                                 final long indirectBufferAddress) {
        this.refusal = null;
        MemorySegment open = open() ? this.encoder : null;
        if (open == null) {
            this.refusal = "the pass " + this.which + " is not open, so there is no encoder to draw on";
            return false;
        }
        if (indexBufferAddress == 0L) {
            this.refusal = "the index buffer has no GPU address, so an indirect draw has no indices to read";
            return false;
        }
        if (indirectBufferAddress == 0L) {
            this.refusal = "the indirect buffer has no GPU address, so the draw has no arguments to read";
            return false;
        }
        if (!responds(open, DRAW_INDEXED_INDIRECT.name())) {
            this.refusal = "the encoder does not answer " + DRAW_INDEXED_INDIRECT.name();
            return false;
        }
        DRAW_INDEXED_INDIRECT.send(open, primitiveType, indexType, MemorySegment.ofAddress(indexBufferAddress),
                indexBufferLength, MemorySegment.ofAddress(indirectBufferAddress));
        return true;
    }

    /**
     * The engine's own present triangle, drawn through this pass: the picture in an argument table.
     * <p>
     * The triangle is drawn and not copied because a whole-texture copy has no coordinates to flip and the
     * engine's present V convention lives in its vertex shader - the copy road put the loading screen on screen
     * upside down, measured. This is the same builtin the present sidecar draws with, so the two roads cannot
     * disagree about the convention.
     */
    public boolean drawPresent(final MTL4ArgumentTable table, final boolean scaling) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || table == null) {
            return false;
        }
        return MTLBuiltinPipelines.drawPresentWithTable(open, table.handle(), scaling);
    }

    /** Whether an object answers a selector, which is the question to ask before reaching for one. */
    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    /** The name this pass was opened under, for a message that has to say which pass it was. */
    public String which() {
        return this.which;
    }

    /**
     * Why the last draw answered no, for a caller that has to say what stopped it.
     * <p>
     * A boolean is the whole answer a caller needs but not the whole answer a reader needs: "refused an indexed
     * draw of 30 indices" says which draw and not which of the four things it could have been, and the one time
     * a client stopped here the difference was the whole investigation.
     */
    @Nullable
    public String refusal() {
        return this.refusal;
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
