package com.metallum.mtl.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLOrigin;
import com.metallum.mtl.MTLSize;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;
import org.lwjgl.system.MemoryStack;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * One Metal 4 compute pass, and the copies the engine's frame path makes in it.
 * <p>
 * The new command model has no blit encoder: the compute encoder absorbed it, so a texture upload, a texture
 * download, a region copy and a mip generation are all commands here rather than on an encoder of their own.
 * That is the shape this class wraps, and the reason a Metal 4 port cannot leave copies until after it has
 * drawn anything: the game's first dynamic texture is uploaded while its texture manager is constructed, which
 * a forced Metal 4 client launch measured by stopping there.
 * <p>
 * <strong>The regions are Metal's own structs, passed the way the header declares them.</strong>
 * {@code MTLOrigin} and {@code MTLSize} are three unsigned integers each, which arm64 hands over as pointers to
 * the struct - the same helpers and the same calling shape the Metal 3 layer uses, so a region means the same
 * thing on both paths.
 * <p>
 * What this does <em>not</em> carry yet is the compute pipeline itself - a dispatch, a table of buffers and
 * storage images. Copies are what the frame path needs first, and a dispatch waits until a frame asks for one
 * (section 34's rule: do not build what the current slice does not use).
 */
@Environment(EnvType.CLIENT)
public final class MTL4ComputeEncoder implements AutoCloseable {

    private static final Msg COMPUTE_ENCODER = Msg.of("computeCommandEncoder", ADDRESS);
    private static final Msg END_ENCODING = Msg.ofVoid("endEncoding");
    private static final Msg COPY_TEXTURE_TO_TEXTURE = Msg.ofVoid("copyFromTexture:toTexture:", ADDRESS, ADDRESS);
    private static final Msg COPY_TEXTURE_REGION_TO_TEXTURE = Msg.ofVoid(
            "copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:"
                    + "destinationLevel:destinationOrigin:",
            ADDRESS, JAVA_LONG, JAVA_LONG, ADDRESS, ADDRESS, ADDRESS, JAVA_LONG, JAVA_LONG, ADDRESS);
    private static final Msg COPY_TEXTURE_TO_BUFFER = Msg.ofVoid(
            "copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:"
                    + "destinationBytesPerRow:destinationBytesPerImage:",
            ADDRESS, JAVA_LONG, JAVA_LONG, ADDRESS, ADDRESS, ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg COPY_BUFFER_TO_TEXTURE = Msg.ofVoid(
            "copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:"
                    + "destinationSlice:destinationLevel:destinationOrigin:",
            ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, ADDRESS, ADDRESS, JAVA_LONG, JAVA_LONG, ADDRESS);
    private static final Msg COPY_BUFFER_TO_BUFFER = Msg.ofVoid(
            "copyFromBuffer:sourceOffset:toBuffer:destinationOffset:size:",
            ADDRESS, JAVA_LONG, ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg BARRIER = Msg.ofVoid("barrierAfterStages:beforeQueueStages:visibilityOptions:",
            JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);
    /**
     * {@code generateMipmapsForTexture:}, read off this machine's SDK header
     * ({@code MTL4ComputeCommandEncoder.h:543}). The compute encoder absorbed Metal 3's blit encoder, so a mip
     * chain is generated here and not on an encoder of its own - which is why this is the road a pack's mipmaps
     * take on the new command model.
     */
    private static final Msg GENERATE_MIPMAPS = Msg.ofVoid("generateMipmapsForTexture:", ADDRESS);

    private static final long STAGE_ALL = Long.MAX_VALUE;
    private static final long VISIBILITY_DEVICE = 1L;

    @Nullable
    private MemorySegment encoder;
    private final String which;
    private boolean ended;

    private MTL4ComputeEncoder(final MemorySegment encoder, final String which) {
        this.encoder = encoder;
        this.which = which;
    }

    /**
     * Opens a compute pass on the given command buffer.
     *
     * @throws Refused when the command buffer will not make one
     */
    public static MTL4ComputeEncoder open(final MTLDevice device, final MemorySegment commandBuffer,
                                          final String which) {
        if (ObjC.isNil(commandBuffer)) {
            throw new Refused("commandBuffer", which + " was given no command buffer to encode into");
        }
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            MemorySegment encoder = COMPUTE_ENCODER.sendPtr(commandBuffer);
            if (ObjC.isNil(encoder)) {
                throw new Refused("encoder", which + " could not open a compute command encoder, which is where"
                        + " this command model puts its copies");
            }
            // Retained for the same reason the render encoder is: the pool this method pushed is about to drain,
            // and a handle held past it without a retain is a dangling pointer rather than a nil check.
            return new MTL4ComputeEncoder(ObjC.retain(encoder), which);
        }
    }

    /**
     * Encodes the producer barrier: everything encoded so far becomes visible to the encoders that follow.
     * <p>
     * The same barrier the render side uses, and for the same reason - a copy that reads what a render pass
     * wrote has to say so on this command model.
     */
    public boolean barrierForSubsequentEncoders() {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || !responds(open, BARRIER.name())) {
            return false;
        }
        BARRIER.send(open, STAGE_ALL, STAGE_ALL, VISIBILITY_DEVICE);
        return true;
    }

    /** Copies a whole texture to another of the same shape. */
    public boolean copyTextureToTexture(final MemorySegment source, final MemorySegment destination) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(source) || ObjC.isNil(destination)) {
            return false;
        }
        COPY_TEXTURE_TO_TEXTURE.send(open, source, destination);
        return true;
    }

    /**
     * Copies one region of a texture to another: the origin and size of the region, and where it lands.
     * <p>
     * The origin is not decoration. A whole-texture copy has nowhere to be wrong about where a pixel came from;
     * a region copy has four coordinates to be wrong about, which is why the smoke that measures this reads back
     * both inside and outside the region it asked for.
     */
    public boolean copyTextureRegion(final MemorySegment source, final long sourceSlice, final long sourceLevel,
                                     final long sourceX, final long sourceY, final long sourceZ,
                                     final long width, final long height, final long depth,
                                     final MemorySegment destination, final long destinationSlice,
                                     final long destinationLevel, final long destinationX,
                                     final long destinationY, final long destinationZ) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(source) || ObjC.isNil(destination)) {
            return false;
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            MemorySegment origin = MTLOrigin.on(stack, sourceX, sourceY, sourceZ);
            MemorySegment size = MTLSize.on(stack, width, height, depth);
            MemorySegment destinationOrigin = MTLOrigin.on(stack, destinationX, destinationY, destinationZ);
            COPY_TEXTURE_REGION_TO_TEXTURE.send(open, source, sourceSlice, sourceLevel, origin, size, destination,
                    destinationSlice, destinationLevel, destinationOrigin);
        }
        return true;
    }

    /** Copies bytes from one buffer into another, which is how a staged upload reaches its destination. */
    public boolean copyBufferToBuffer(final MemorySegment source, final long sourceOffset,
                                      final MemorySegment destination, final long destinationOffset,
                                      final long size) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(source) || ObjC.isNil(destination) || size <= 0L) {
            return false;
        }
        COPY_BUFFER_TO_BUFFER.send(open, source, sourceOffset, destination, destinationOffset, size);
        return true;
    }

    /** Copies a region of a texture out into a buffer, which is how the engine reads a texture back. */
    public boolean copyTextureToBuffer(final MemorySegment source, final long sourceSlice, final long sourceLevel,
                                       final long sourceX, final long sourceY, final long sourceZ,
                                       final long width, final long height, final long depth,
                                       final MemorySegment destination, final long destinationOffset,
                                       final long bytesPerRow, final long bytesPerImage) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(source) || ObjC.isNil(destination)) {
            return false;
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            MemorySegment origin = MTLOrigin.on(stack, sourceX, sourceY, sourceZ);
            MemorySegment size = MTLSize.on(stack, width, height, depth);
            COPY_TEXTURE_TO_BUFFER.send(open, source, sourceSlice, sourceLevel, origin, size, destination,
                    destinationOffset, bytesPerRow, bytesPerImage);
        }
        return true;
    }

    /** Copies a buffer's bytes into a region of a texture, which is how the engine uploads one. */
    public boolean copyBufferToTexture(final MemorySegment source, final long sourceOffset,
                                       final long sourceBytesPerRow, final long sourceBytesPerImage,
                                       final long width, final long height, final long depth,
                                       final MemorySegment destination, final long destinationSlice,
                                       final long destinationLevel, final long destinationX,
                                       final long destinationY, final long destinationZ) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(source) || ObjC.isNil(destination)) {
            return false;
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            MemorySegment size = MTLSize.on(stack, width, height, depth);
            MemorySegment origin = MTLOrigin.on(stack, destinationX, destinationY, destinationZ);
            COPY_BUFFER_TO_TEXTURE.send(open, source, sourceOffset, sourceBytesPerRow, sourceBytesPerImage, size,
                    destination, destinationSlice, destinationLevel, origin);
        }
        return true;
    }

    /**
     * Generates a texture's mip chain from its level 0.
     * <p>
     * False where the encoder is not open or the object does not answer the selector, rather than a call that
     * goes nowhere: the caller's fallback is the contract's own answer, and a generation that silently did
     * nothing would leave a texture whose later levels hold whatever was there.
     */
    public boolean generateMipmaps(final MemorySegment texture) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(texture) || !responds(open, GENERATE_MIPMAPS.name())) {
            return false;
        }
        GENERATE_MIPMAPS.send(open, texture);
        return true;
    }

    // ------------------------------------------------------------------ the compute dispatch itself

    /**
     * {@code setComputePipelineState:}, {@code setArgumentTable:} and
     * {@code dispatchThreadgroups:threadsPerThreadgroup:}, read off this machine's SDK header
     * ({@code MTL4ComputeCommandEncoder.h:51}, {@code :661} and {@code :87}).
     * <p>
     * The argument table takes no stage mask here, which is the one place this encoder is simpler than the
     * render one: a compute dispatch has one stage, so there is nothing to say about which it is.
     */
    private static final Msg SET_COMPUTE_PIPELINE = Msg.ofVoid("setComputePipelineState:", ADDRESS);
    private static final Msg SET_ARGUMENT_TABLE = Msg.ofVoid("setArgumentTable:", ADDRESS);
    private static final Msg DISPATCH_THREADGROUPS =
            Msg.ofVoid("dispatchThreadgroups:threadsPerThreadgroup:", ADDRESS, ADDRESS);

    /** Hands the encoder the pipeline the dispatch runs, answering whether it was accepted. */
    public boolean setComputePipelineState(final MemorySegment pipeline) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || ObjC.isNil(pipeline) || !responds(open, SET_COMPUTE_PIPELINE.name())) {
            return false;
        }
        SET_COMPUTE_PIPELINE.send(open, pipeline);
        return true;
    }

    /**
     * Hands the encoder the table the dispatch's shader reads through.
     * <p>
     * The table is snapshotted when the dispatch is encoded, which the header says in as many words - so a table
     * changed after a dispatch does not change what that dispatch saw, and a caller reusing one table for two
     * dispatches with different contents has to know which dispatch gets which.
     */
    public boolean setArgumentTable(final MTL4ArgumentTable table) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || table == null || !responds(open, SET_ARGUMENT_TABLE.name())) {
            return false;
        }
        SET_ARGUMENT_TABLE.send(open, table.handle());
        return true;
    }

    /**
     * Dispatches a grid of threadgroups.
     * <p>
     * Workgroup counts and the shader's own threads-per-threadgroup, which is the shape a Vulkan
     * {@code vkCmdDispatch} has: the caller asks for groups and the shader declares its local size. Both arrive
     * as {@code MTLSize}, three unsigned integers each, which arm64 hands over as pointers to the struct - the
     * same convention the copy methods' regions use.
     */
    public boolean dispatchThreadgroups(final long groupsX, final long groupsY, final long groupsZ,
                                        final long localX, final long localY, final long localZ) {
        MemorySegment open = open() ? this.encoder : null;
        if (open == null || groupsX <= 0L || groupsY <= 0L || groupsZ <= 0L
                || localX <= 0L || localY <= 0L || localZ <= 0L) {
            return false;
        }
        if (!responds(open, DISPATCH_THREADGROUPS.name())) {
            return false;
        }
        try (MemoryStack stack = MemoryStack.stackPush()) {
            MemorySegment groups = MTLSize.on(stack, groupsX, groupsY, groupsZ);
            MemorySegment threads = MTLSize.on(stack, localX, localY, localZ);
            DISPATCH_THREADGROUPS.send(open, groups, threads);
        }
        return true;
    }

    /** The native encoder, for the dispatch that will be encoded into it. */
    public MemorySegment encoder() {
        return this.encoder == null ? MemorySegment.NULL : this.encoder;
    }

    /** Whether this pass is still open. */
    public boolean open() {
        return this.encoder != null && !this.ended;
    }

    /** Ends the pass. Ending it twice is a no-op, because a caller may end it on more than one path. */
    public void endEncoding() {
        if (this.ended || this.encoder == null) {
            return;
        }
        this.ended = true;
        END_ENCODING.send(this.encoder);
    }

    /** The name this pass was opened under, for a message that has to say which pass it was. */
    public String which() {
        return this.which;
    }

    /** Ends the pass where it is still open, then releases the encoder. */
    @Override
    public void close() {
        endEncoding();
        MemorySegment held = this.encoder;
        this.encoder = null;
        if (held != null) {
            ObjC.release(held);
        }
    }

    /** Whether an object answers a selector, which is the question to ask before reaching for one. */
    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    /** Why a compute pass could not be opened, carrying the stage that failed. */
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
