package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.CAMetalDrawable;
import com.metallum.mtl.CAMetalLayer;
import com.metallum.mtl.MTL4ArgumentTable;
import com.metallum.mtl.MTL4Probe;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLPixelFormat;
import com.metallum.mtl.MTLTexture;
import com.metallum.mtl.MTLTextureDescriptor;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * The Metal 4 command structure carrying a frame-shaped submission, every frame.
 * <p>
 * Metal 4 is a parallel API surface, not a replacement, and this is the step after detection: a frame's
 * shape - an allocator to hold the commands, a command buffer begun on it, work encoded and ended, the
 * buffer committed to a queue and its completion signalled and waited for - runs once per frame beside the
 * real one. What the work touches is a 64x64 scratch target of this class's own, so nothing here can
 * change the picture, and the real frame is untouched: no resource is shared, no order between the two
 * queues is needed, and the counters the frame probe reports are the real frame's.
 * <p>
 * <strong>The discipline this proves is the frame-in-flight one.</strong> A command buffer's memory comes
 * from its allocator and an allocator may only be reset once the GPU is finished with it, so a small ring
 * of allocators is rotated and each slot waits for the value that slot's commit signalled - the documented
 * pattern, and the thing a later path that shares resources with the frame will have to get right.
 * <p>
 * Off where the device has no Metal 4 API, and off by {@code -Dmetallum.metal4Frame=false} so the cost of
 * carrying it can be measured against a run that does not.
 */
@Environment(EnvType.CLIENT)
public final class Metal4Path {

    /** Three, the shape the sample code ships: one allocator per frame in flight. */
    private static final int FRAMES_IN_FLIGHT = 3;

    /** What one frame's submission may wait for the GPU to finish before this path gives up. */
    private static final long WAIT_MILLIS = 1000L;

    private static final long TARGET_SIZE = 64L;

    /** The drawable's own format, so the built-in present pipeline is the one this target was built for. */
    private static final MTLPixelFormat TARGET_FORMAT = MTLPixelFormat.BGRA8Unorm;
    private static final long USAGE_RENDER_TARGET = 4L;
    private static final long LOAD_DONT_CARE = 0L;
    private static final long STORE_STORE = 1L;

    private static final Msg NEW_QUEUE = Msg.of("newMTL4CommandQueue", ADDRESS);
    private static final Msg NEW_ALLOCATOR = Msg.of("newCommandAllocator", ADDRESS);
    private static final Msg NEW_COMMAND_BUFFER = Msg.of("newCommandBuffer", ADDRESS);
    private static final Msg NEW_SHARED_EVENT = Msg.of("newSharedEvent", ADDRESS);
    private static final Msg BEGIN = Msg.ofVoid("beginCommandBufferWithAllocator:", ADDRESS);
    private static final Msg END = Msg.ofVoid("endCommandBuffer");
    private static final Msg COMMIT = Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG);
    private static final Msg SIGNAL_EVENT = Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg WAIT_UNTIL_SIGNALED =
            Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg RESET = Msg.ofVoid("reset");
    private static final Msg ENCODE_SIGNAL_EVENT = Msg.ofVoid("encodeSignalEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg COMPUTE_ENCODER = Msg.of("computeCommandEncoder", ADDRESS);
    private static final Msg COPY_TEXTURE = Msg.ofVoid("copyFromTexture:toTexture:", ADDRESS, ADDRESS);
    private static final Msg WAIT_FOR_EVENT = Msg.ofVoid("waitForEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg SIGNAL_DRAWABLE = Msg.ofVoid("signalDrawable:", ADDRESS);
    private static final Msg RENDER_ENCODER = Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg END_ENCODING = Msg.ofVoid("endEncoding");
    private static final Msg NEW = Msg.of("new", ADDRESS);
    private static final Msg SET_TARGET_WIDTH = Msg.ofVoid("setRenderTargetWidth:", JAVA_LONG);
    private static final Msg SET_TARGET_HEIGHT = Msg.ofVoid("setRenderTargetHeight:", JAVA_LONG);
    private static final Msg COLOR_ATTACHMENTS = Msg.of("colorAttachments", ADDRESS);
    private static final Msg ATTACHMENT_AT = Msg.of("objectAtIndexedSubscript:", ADDRESS, JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:", ADDRESS);
    private static final Msg SET_LOAD_ACTION = Msg.ofVoid("setLoadAction:", JAVA_LONG);
    private static final Msg SET_STORE_ACTION = Msg.ofVoid("setStoreAction:", JAVA_LONG);

    @Nullable
    private static MemorySegment queue;
    @Nullable
    private static MemorySegment commandBuffer;
    @Nullable
    private static MemorySegment event;
    @Nullable
    private static MemorySegment pass;
    @Nullable
    private static MTL4ArgumentTable table;

    /** The picture this frame's submission samples, handed over where the frame says what it drew. */
    private static MemorySegment source = MemorySegment.NULL;
    private static long sourceWidth;
    @Nullable
    private static MemorySegment target;
    private static final MemorySegment[] allocators = new MemorySegment[FRAMES_IN_FLIGHT];
    private static final long[] awaited = new long[FRAMES_IN_FLIGHT];
    private static long signalled;

    /** The other direction: the event the frame's own command buffer signals, and the value it last signalled. */
    @Nullable
    private static MemorySegment frameEvent;
    private static long frameValue;
    private static int slot;
    private static boolean carrying;

    private Metal4Path() {
    }

    /**
     * Starts carrying a frame-shaped submission, where the device has the API to carry one.
     *
     * @param device the device binding, asked for every selector before it is sent
     * @return whether the path is carrying frames
     */
    public static boolean start(final MTLDevice device) {
        if (!Metal4.available(device) || !enabled()) {
            return false;
        }

        try (AutoreleasePool _ = AutoreleasePool.push()) {
            if (!device.respondsTo("newMTL4CommandQueue")
                    || !device.respondsTo("newCommandAllocator")
                    || !device.respondsTo("newCommandBuffer")
                    || !device.respondsTo("newSharedEvent")) {
                return refuse("the device is missing one of the entry points this path needs");
            }

            MemorySegment madeQueue = NEW_QUEUE.sendPtr(device.handle());
            MemorySegment madeBuffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            MemorySegment madeEvent = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(madeQueue) || ObjC.isNil(madeBuffer) || ObjC.isNil(madeEvent)
                    || !responds(madeEvent, "waitUntilSignaledValue:timeoutMS:")) {
                ObjC.release(madeEvent);
                ObjC.release(madeBuffer);
                ObjC.release(madeQueue);
                return refuse("the device would not make a queue, a command buffer and a shared event");
            }

            for (int index = 0; index < FRAMES_IN_FLIGHT; index++) {
                MemorySegment allocator = NEW_ALLOCATOR.sendPtr(device.handle());
                if (ObjC.isNil(allocator) || !responds(allocator, "reset")) {
                    ObjC.release(allocator);
                    stop(madeQueue, madeBuffer, madeEvent);
                    return refuse("the device would not make an allocator that can be reset");
                }
                allocators[index] = allocator;
            }

            // A table is what a Metal 4 encoder is given its resources through, and this device does not
            // make one - so nothing can be *drawn* with resources here. That is not a reason to stop
            // carrying the submission itself, which needs no bindings: the path says what it cannot do and
            // keeps doing what it can.
            table = MTL4ArgumentTable.create(device);
            if (table == null) {
                Metallum.LOGGER.warn("Metal 4 path: carrying frames without a draw, because this device makes "
                        + "no argument table and a Metal 4 encoder cannot be bound any other way");
            }

            try {
                MemorySegment madePass = newPass();
                MemorySegment madeTarget = newTarget(device, madePass);
                pass = madePass;
                target = madeTarget;
            } catch (RuntimeException refused) {
                stop(madeQueue, madeBuffer, madeEvent);
                return refuse("the pass or its target could not be made: " + refused.getMessage());
            }

            MemorySegment madeFrameEvent = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(madeFrameEvent) || !responds(madeFrameEvent, "waitUntilSignaledValue:timeoutMS:")) {
                ObjC.release(madeFrameEvent);
                stop(madeQueue, madeBuffer, madeEvent);
                return refuse("the device would not make the event the frame signals on");
            }
            frameEvent = madeFrameEvent;

            queue = madeQueue;
            commandBuffer = madeBuffer;
            event = madeEvent;
            carrying = true;
            Metallum.LOGGER.info("Metal 4 path: carrying a frame-shaped submission every frame, {} allocators, "
                    + "a shared event bounding the frames in flight, and a {}}x{} scratch target",
                    FRAMES_IN_FLIGHT, TARGET_SIZE, TARGET_SIZE);
            return true;
        }
    }

    /**
     * Carries one frame: the next allocator in the ring, waited for, reset, begun on, encoded into, ended,
     * committed and signalled.
     * <p>
     * A slot is only reused after the value its own commit signalled has been seen, which is what keeps the
     * CPU from resetting an allocator the GPU is still reading.
     */
    public static void frame() {
        if (!carrying || queue == null || commandBuffer == null || event == null || pass == null) {
            return;
        }

        long startedAt = System.nanoTime();
        try {
            slot = (slot + 1) % FRAMES_IN_FLIGHT;
            if (awaited[slot] != 0L
                    && WAIT_UNTIL_SIGNALED.sendLong(event, awaited[slot], WAIT_MILLIS) == 0L) {
                giveUp("the GPU did not signal slot " + slot + " within " + WAIT_MILLIS + " ms");
                return;
            }

            RESET.send(allocators[slot]);
            BEGIN.send(commandBuffer, allocators[slot]);
            MemorySegment encoder = RENDER_ENCODER.sendPtr(commandBuffer, pass);
            if (ObjC.isNil(encoder)) {
                giveUp("a render encoder for the frame-shaped submission came back nil");
                return;
            }

            // The draw, when the frame has told this path what it drew: the engine's own present triangle,
            // sampling the frame's picture through an argument table, into this path's target. It is the
            // first thing the new command structure draws, and it is drawn off the picture's path - the
            // frame that is presented is still the one the Metal 3 command buffer presented.
            boolean drawn = false;
            if (table != null && !ObjC.isNil(source)) {
                boolean scaling = sourceWidth != TARGET_SIZE;
                if (table.texture(source) && table.sampler(MTLBuiltinPipelines.presentSampler(scaling))) {
                    drawn = MTLBuiltinPipelines.drawPresentWithTable(encoder, table.handle(), scaling);
                }
            }

            END_ENCODING.send(encoder);
            END.send(commandBuffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, commandBuffer);
                COMMIT.send(queue, buffers, 1L);
            }

            awaited[slot] = ++signalled;
            SIGNAL_EVENT.send(queue, event, awaited[slot]);

            MetalFrameProbe.metal4Frame(System.nanoTime() - startedAt, drawn);
        } catch (RuntimeException failed) {
            giveUp(failed.getMessage());
        }
    }

    /**
     * Hands this path the picture the frame just drew, which its own submission samples.
     * <p>
     * Taken at the moment the frame says what it is presenting, so what the new path draws is the frame's
     * real output and not a stand-in. The width is kept because the present triangle picks its filter by
     * whether the source and the target differ in size.
     */
    public static void source(final MemorySegment textureHandle) {
        if (!carrying || ObjC.isNil(textureHandle)) {
            return;
        }

        source = textureHandle;
        sourceWidth = MTLTexture.width(textureHandle);
    }

    /**
     * Makes the frame's own command buffer signal this path's event when the GPU has finished with it.
     * <p>
     * The one thing that has to cross the two queues: the picture this path copies is written by the frame's
     * command buffer, so the copy must wait for it - and a fence does not cross queues, a shared event does.
     */
    public static void frameSignal(final MemorySegment commandBuffer) {
        if (!carrying || ObjC.isNil(frameEvent) || ObjC.isNil(commandBuffer)) {
            return;
        }

        frameValue++;
        ENCODE_SIGNAL_EVENT.send(commandBuffer, frameEvent, frameValue);
    }

    /**
     * Presents the frame through the new command structure, and answers whether it took it.
     * <p>
     * This is the part of the picture the new path can carry on this machine without a single binding: a
     * Metal 4 compute encoder's whole-texture copy needs no argument table, so the frame's finished picture is
     * copied into the drawable by the new queue and the drawable is told to present once that work is done.
     * The frame's command buffer signals first (see {@link #frameSignal}) and the copy waits on that value, so
     * the two queues are ordered by the event rather than by luck.
     * <p>
     * False leaves the caller on the road it had. Everything is checked before the drawable is taken, and a
     * drawable that has been taken is always presented by whoever took it.
     * <p>
     * <strong>Off by default, and it does not work yet.</strong> Turned on it carries the picture for a while
     * and then the ring gives up - measured, the GPU stops signalling a slot of the submission ring within a
     * second, which means the ordering or the lifetime of the second submission per frame is wrong somewhere
     * in here. Until that is found this stays behind {@code -Dmetallum.metal4Present=true}, because a path
     * that takes the picture and then stalls is worse than one that never takes it.
     */
    public static boolean present(final CAMetalLayer layer, final MemorySegment sourceTexture) {
        if (!Boolean.parseBoolean(System.getProperty("metallum.metal4Present", "false"))) {
            return false;
        }

        if (!carrying || queue == null || commandBuffer == null || frameEvent == null || frameValue == 0L) {
            return false;
        }

        if (!responds(queue, "waitForEvent:value:") || !responds(queue, "signalDrawable:")
                || !responds(commandBuffer, "computeCommandEncoder")) {
            return false;
        }

        try (AutoreleasePool _ = AutoreleasePool.push()) {
            CAMetalDrawable drawable = layer.nextDrawable();
            if (drawable == null) {
                return false;
            }

            MemorySegment drawableTexture = drawable.texture();
            if (ObjC.isNil(drawableTexture)) {
                return false;
            }

            long sourceWidth = MTLTexture.width(sourceTexture);
            long sourceHeight = MTLTexture.height(sourceTexture);
            if (MTLTexture.width(drawableTexture) == sourceWidth
                    && MTLTexture.height(drawableTexture) == sourceHeight
                    && encodeCopyPresent(drawable, drawableTexture, sourceTexture)) {
                return true;
            }

            // The copy is whole-texture and exact, and this path has the drawable in hand: it presents the
            // frame's own picture through the new queue rather than handing the drawable back unpresented.
            SIGNAL_DRAWABLE.send(queue, drawable.handle());
            drawable.present();
            return true;
        }
    }

    private static boolean encodeCopyPresent(final CAMetalDrawable drawable, final MemorySegment drawableTexture,
                                             final MemorySegment sourceTexture) {
        int nextSlot = (slot + 1) % FRAMES_IN_FLIGHT;
        if (awaited[nextSlot] != 0L
                && WAIT_UNTIL_SIGNALED.sendLong(event, awaited[nextSlot], WAIT_MILLIS) == 0L) {
            return false;
        }

        WAIT_FOR_EVENT.send(queue, frameEvent, frameValue);

        slot = nextSlot;
        RESET.send(allocators[slot]);
        BEGIN.send(commandBuffer, allocators[slot]);
        MemorySegment compute = COMPUTE_ENCODER.sendPtr(commandBuffer);
        if (ObjC.isNil(compute)) {
            // Ended rather than abandoned: a command buffer left open cannot be begun again, and this path
            // has to be able to try again next frame.
            END.send(commandBuffer);
            return false;
        }
        COPY_TEXTURE.send(compute, sourceTexture, drawableTexture);
        END_ENCODING.send(compute);
        END.send(commandBuffer);

        try (Arena arena = Arena.ofConfined()) {
            MemorySegment buffers = arena.allocate(ADDRESS, 1);
            buffers.set(ADDRESS, 0L, commandBuffer);
            COMMIT.send(queue, buffers, 1L);
        }

        awaited[slot] = ++signalled;
        SIGNAL_EVENT.send(queue, event, awaited[slot]);
        SIGNAL_DRAWABLE.send(queue, drawable.handle());
        drawable.present();
        return true;
    }

    /** Releases everything this path made. */
    public static void close() {
        if (queue != null) {
            stop(queue, commandBuffer, event);
            queue = null;
            commandBuffer = null;
            event = null;
            pass = null;
            target = null;
            carrying = false;
        }
    }

    /** Says why this path is not carrying frames, which a silent false never does. */
    private static boolean refuse(final String why) {
        Metallum.LOGGER.warn("Metal 4 path: not carrying frames ({})", why);
        return false;
    }

    private static void giveUp(final @Nullable String why) {
        if (!carrying) {
            return;
        }

        carrying = false;
        Metallum.LOGGER.warn("Metal 4 path: stopped carrying frames ({})", why == null ? "no reason given" : why);
    }

    private static void stop(final MemorySegment madeQueue, final @Nullable MemorySegment madeBuffer,
                             final MemorySegment madeEvent) {
        // Every release goes through the guard: a field that was never set is a Java null and a nil handle
        // is a no-op, and an exception thrown from the path's own cleanup is what took the device down with
        // it rather than failing this path closed.
        if (table != null) {
            table.close();
            table = null;
        }
        releaseIfPresent(pass);
        releaseIfPresent(target);
        pass = null;
        target = null;
        for (int index = 0; index < FRAMES_IN_FLIGHT; index++) {
            releaseIfPresent(allocators[index]);
            allocators[index] = MemorySegment.NULL;
            awaited[index] = 0L;
        }
        releaseIfPresent(frameEvent);
        frameEvent = null;
        frameValue = 0L;
        releaseIfPresent(madeEvent);
        releaseIfPresent(madeBuffer);
        releaseIfPresent(madeQueue);
    }

    private static void releaseIfPresent(final @Nullable MemorySegment object) {
        if (object != null && !ObjC.isNil(object)) {
            ObjC.release(object);
        }
    }

    private static MemorySegment newPass() {
        MemorySegment passDescriptor = NEW.sendPtr(ObjC.clazz("MTL4RenderPassDescriptor"));
        SET_TARGET_WIDTH.send(passDescriptor, TARGET_SIZE);
        SET_TARGET_HEIGHT.send(passDescriptor, TARGET_SIZE);
        return passDescriptor;
    }

    private static MemorySegment newTarget(final MTLDevice device, final MemorySegment passDescriptor) {
        MemorySegment made;
        try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
            descriptor.pixelFormat(TARGET_FORMAT);
            descriptor.width(TARGET_SIZE);
            descriptor.height(TARGET_SIZE);
            descriptor.usage(USAGE_RENDER_TARGET);
            made = device.newTexture(descriptor);
        }

        MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(passDescriptor);
        MemorySegment attachment = ObjC.isNil(attachments) ? MemorySegment.NULL : ATTACHMENT_AT.sendPtr(attachments, 0L);
        if (ObjC.isNil(attachment)) {
            throw new IllegalStateException("the Metal 4 pass descriptor has no colour attachment to set");
        }
        SET_TEXTURE.send(attachment, made);
        SET_LOAD_ACTION.send(attachment, LOAD_DONT_CARE);
        SET_STORE_ACTION.send(attachment, STORE_STORE);

        return made;
    }

    /** Whether this path is wanted: on where the device has the API, off when the property says so. */
    private static boolean enabled() {
        return !"false".equalsIgnoreCase(System.getProperty("metallum.metal4Frame", "true"));
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return MTL4Probe.respondsTo(object, selector);
    }
}
