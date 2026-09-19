package com.metallum.render;

import com.metallum.Metallum;
import com.metallum.mtl.CAMetalDrawable;
import com.metallum.mtl.CAMetalLayer;
import com.metallum.mtl.MTL4ArgumentTable;
import com.metallum.mtl.MTL4Probe;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLTexture;
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
 * The Metal 4 command structure presenting the frame, one command buffer and one commit a frame.
 * <p>
 * Metal 4 is a parallel API surface, not a replacement, and this is the step after detection: the frame's
 * picture is drawn into the drawable by the new queue, through the engine's own present pipeline and an
 * argument table that carries the picture and a sampler. The shape is Apple's own order -
 * {@code nextDrawable}, {@code waitForDrawable:}, encode, {@code commit:count:}, {@code signalDrawable:},
 * {@code present} - and it is the same order printed on the framework's page for a Metal 4 game, which is
 * why the frame's own command buffer signals a shared event this path waits on rather than the two halves
 * being ordered by luck.
 * <p>
 * <strong>The discipline this has to keep is the frame-in-flight one.</strong> A command buffer's memory
 * comes from its allocator and an allocator may only be reset once the GPU is finished with it, so a small
 * ring of allocators is rotated and each slot waits for the value that slot's commit signalled.
 * <p>
 * Off where the device has no Metal 4 API. The frame's present goes through it under
 * {@code -Dmetallum.metal4Present=true} and the path is not built at all under
 * {@code -Dmetallum.metal4Frame=false}, which is how the cost of carrying it is measured against a run
 * that does not.
 */
@Environment(EnvType.CLIENT)
public final class Metal4Path {

    /** Three, the shape the sample code ships: one allocator per frame in flight. */
    private static final int FRAMES_IN_FLIGHT = 3;

    /** What one frame's submission may wait for the GPU to finish before this path gives up. */
    private static final long WAIT_MILLIS = 1000L;

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
    private static final Msg WAIT_FOR_EVENT = Msg.ofVoid("waitForEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg WAIT_DRAWABLE = Msg.ofVoid("waitForDrawable:", ADDRESS);
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
    private static MTL4ArgumentTable table;

    /**
     * The frame's present, recorded where the surface says what it is presenting and carried out after the
     * frame's own commit: the layer the drawable comes from, and the picture to draw into it.
     */
    @Nullable
    private static CAMetalLayer pendingLayer;
    private static MemorySegment pendingPicture = MemorySegment.NULL;

    private static final MemorySegment[] allocators = new MemorySegment[FRAMES_IN_FLIGHT];
    private static final long[] awaited = new long[FRAMES_IN_FLIGHT];
    private static long signalled;
    private static boolean presentWarned;

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

            // A table is what a Metal 4 encoder is given its resources through, and this device makes one:
            // the factory's name carries the error out-parameter its header declares, and asking with the
            // shorter name was what made this read as a device that could not bind at all. One texture and
            // one sampler, which is the shape the present draw binds; the passes of the chain get the tables
            // item 3 sizes.
            table = MTL4ArgumentTable.create(device);
            if (table == null) {
                Metallum.LOGGER.warn("Metal 4 path: not carrying the present, because this device makes no "
                        + "argument table and a Metal 4 encoder cannot be bound any other way");
                stop(madeQueue, madeBuffer, madeEvent);
                return refuse("no argument table, so nothing can be bound on the new path");
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
            Metallum.LOGGER.info("Metal 4 path: carrying the frame's present, one command buffer and one "
                    + "commit a frame, {} allocators and a shared event bounding the frames in flight",
                    FRAMES_IN_FLIGHT);
            return true;
        }
    }

    /** One line for a failure, naming what failed and what it was, for the log rather than for a reader. */
    private static String describe(final Throwable failed) {
        Throwable cause = failed.getCause() == null ? failed : failed.getCause();
        String message = cause.getMessage();
        return failed.getMessage() + " (" + cause.getClass().getSimpleName()
                + (message == null ? "" : ": " + message) + ")";
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
     * Whether this frame's present goes through the new command structure, and the picture it will draw.
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
     * <strong>Off by default, and the first thing it did was end the process.</strong> Turned on it died a
     * second into the session with
     * {@code -[AGXG17XFamilyRenderContext_mtlnext signalOnCommandQueue:]: unrecognized selector}, which is the
     * framework telling a drawable to register itself on this queue - the half of Apple's order that says which
     * drawable the queue is about to wait for, before any command buffer targeting it is committed. The wait
     * half is here now; whether that is the whole of what the signal half needs is what the next run answers,
     * and until it does this stays behind {@code -Dmetallum.metal4Present=true}.
     */
    public static boolean presenting(final CAMetalLayer layer, final MemorySegment picture) {
        if (!Boolean.parseBoolean(System.getProperty("metallum.metal4Present", "false"))) {
            return false;
        }

        if (!carrying || queue == null || commandBuffer == null || frameEvent == null || frameValue == 0L
                || table == null || layer == null || ObjC.isNil(picture)) {
            return false;
        }

        if (!responds(queue, "waitForDrawable:") || !responds(queue, "waitForEvent:value:")
                || !responds(queue, "signalDrawable:")
                || !responds(commandBuffer, "renderCommandEncoderWithDescriptor:")) {
            return false;
        }

        pendingLayer = layer;
        pendingPicture = picture;
        return true;
    }

    /**
     * Presents the frame {@link #presenting} recorded, which is called after the frame's own command buffer has
     * been committed and has signalled this path's event.
     * <p>
     * <strong>The order is the whole of it.</strong> The surface says what it is presenting *before* the
     * frame's command buffer is committed, so a present encoded there samples a picture the frame that writes
     * it has not drawn yet - a frame old, or torn, or part of both - and no event value the frame has not
     * signalled can order it. Recorded here and presented after the commit, the wait below is on the frame
     * that produced the picture, which is what makes this the frame the player sees.
     */
    public static void presentFrame() {
        CAMetalLayer layer = pendingLayer;
        MemorySegment picture = pendingPicture;
        pendingLayer = null;
        pendingPicture = MemorySegment.NULL;
        if (layer == null || ObjC.isNil(picture)) {
            return;
        }

        try (AutoreleasePool _ = AutoreleasePool.push()) {
            CAMetalDrawable drawable = layer.nextDrawable();
            if (drawable == null) {
                return;
            }

            // Apple's order has this half before anything is committed against the drawable and the signal
            // half after, and this path was missing the first one: `signalDrawable:` alone ended the process
            // with `-[AGXG17XFamilyRenderContext_mtlnext signalOnCommandQueue:]: unrecognized selector`,
            // which is the framework asking a drawable that was never registered with this queue to register
            // itself on it. Asked for a drawable, so the queue is told which one it is about to wait for
            // before the command buffer that targets it is committed.
            WAIT_DRAWABLE.send(queue, drawable.handle());

            MemorySegment drawableTexture = drawable.texture();

            // Drawn and not copied. A whole-texture copy is exact and needs no bindings, which is what made
            // it the first thing this path could carry - and it presents the picture upside down, because the
            // engine's own present triangle flips V and a copy has no coordinates to flip: measured, the
            // loading screen arrived 180 degrees over. The present pipeline and the sampler already handle the
            // convention, and the argument table is what the triangle is given its source through.
            long startedAt = System.nanoTime();
            boolean drawn = !ObjC.isNil(drawableTexture) && encodeDrawPresent(drawableTexture, picture);
            MetalFrameProbe.metal4Frame(System.nanoTime() - startedAt, drawn);
            MetalFrameProbe.metal4Present();
            if (!drawn) {
                warnOnce("Metal 4 present: nothing could be drawn into the drawable, so the frame is presented "
                        + "by the new queue with nothing of the picture in it");
            }

            // Taken, so presented: the drawable cannot be handed back to the other road, which takes one of
            // its own from the same layer and would leave this one in the pool for ever.
            SIGNAL_DRAWABLE.send(queue, drawable.handle());
            drawable.present();
        } catch (RuntimeException failed) {
            giveUp(describe(failed));
        }
    }

    /** Says one thing once for the life of the path, because a frame path may not log one line a frame. */
    private static void warnOnce(final String words) {
        if (!presentWarned) {
            presentWarned = true;
            Metallum.LOGGER.warn(words);
        }
    }

    private static boolean encodeDrawPresent(final MemorySegment drawableTexture,
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

        MemorySegment pass = newDrawablePass(drawableTexture);
        if (ObjC.isNil(pass)) {
            // Ended rather than abandoned: a command buffer left open cannot be begun again, and this path
            // has to be able to try again next frame.
            END.send(commandBuffer);
            return false;
        }

        // Filled here rather than once: the table holds the picture and the sampler this present samples, and
        // both belong to the frame being presented. The filter is chosen by whether the drawable and the
        // picture differ in size, which is the same question the engine's own drawable road asks.
        boolean scaling = MTLTexture.width(drawableTexture) != MTLTexture.width(sourceTexture)
                || MTLTexture.height(drawableTexture) != MTLTexture.height(sourceTexture);
        if (!table.texture(sourceTexture) || !table.sampler(MTLBuiltinPipelines.presentSampler(scaling))) {
            END.send(commandBuffer);
            return false;
        }

        boolean drawn = false;
        try {
            MemorySegment encoder = RENDER_ENCODER.sendPtr(commandBuffer, pass);
            if (!ObjC.isNil(encoder)) {
                drawn = MTLBuiltinPipelines.drawPresentWithTable(encoder, table.handle(), scaling);
                END_ENCODING.send(encoder);
            }
        } finally {
            ObjC.release(pass);
        }
        END.send(commandBuffer);

        try (Arena arena = Arena.ofConfined()) {
            MemorySegment buffers = arena.allocate(ADDRESS, 1);
            buffers.set(ADDRESS, 0L, commandBuffer);
            COMMIT.send(queue, buffers, 1L);
        }

        awaited[slot] = ++signalled;
        SIGNAL_EVENT.send(queue, event, awaited[slot]);
        return drawn;
    }

    /**
     * A pass over the drawable's own texture, at the drawable's size, for the present triangle.
     * <p>
     * Made per present rather than kept: the layer hands out a different texture every frame and the size
     * belongs to the drawable, not to this path. Not a clear - the triangle covers every pixel of it - so the
     * load action is dontCare and the store action is store.
     */
    private static MemorySegment newDrawablePass(final MemorySegment drawableTexture) {
        MemorySegment descriptor = NEW.sendPtr(ObjC.clazz("MTL4RenderPassDescriptor"));
        if (ObjC.isNil(descriptor)) {
            return MemorySegment.NULL;
        }

        SET_TARGET_WIDTH.send(descriptor, MTLTexture.width(drawableTexture));
        SET_TARGET_HEIGHT.send(descriptor, MTLTexture.height(drawableTexture));
        MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(descriptor);
        MemorySegment attachment = ObjC.isNil(attachments) ? MemorySegment.NULL : ATTACHMENT_AT.sendPtr(attachments, 0L);
        if (ObjC.isNil(attachment)) {
            ObjC.release(descriptor);
            return MemorySegment.NULL;
        }

        SET_TEXTURE.send(attachment, drawableTexture);
        SET_LOAD_ACTION.send(attachment, LOAD_DONT_CARE);
        SET_STORE_ACTION.send(attachment, STORE_STORE);
        return descriptor;
    }

    /** Releases everything this path made. */
    public static void close() {
        if (queue != null) {
            stop(queue, commandBuffer, event);
            queue = null;
            commandBuffer = null;
            event = null;
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

    /** Whether this path is wanted: on where the device has the API, off when the property says so. */
    private static boolean enabled() {
        return !"false".equalsIgnoreCase(System.getProperty("metallum.metal4Frame", "true"));
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return MTL4Probe.respondsTo(object, selector);
    }
}
