package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.*;

@Environment(EnvType.CLIENT)
public final class CAMetalLayer {
    private static final MemorySegment CLS = ObjC.clazz("CAMetalLayer");
    private static final Msg NEW = Msg.of("new", ADDRESS);
    private static final Msg SET_DEVICE = Msg.ofVoid("setDevice:", ADDRESS);
    private static final Msg SET_FRAMEBUFFER_ONLY = Msg.ofVoid("setFramebufferOnly:", JAVA_BOOLEAN);
    private static final Msg SET_OPAQUE = Msg.ofVoid("setOpaque:", JAVA_BOOLEAN);
    private static final Msg SET_CONTENTS_SCALE = Msg.ofVoid("setContentsScale:", JAVA_DOUBLE);
    private static final Msg SET_PIXEL_FORMAT = Msg.ofVoid("setPixelFormat:", JAVA_LONG);
    private static final Msg SET_DRAWABLE_SIZE = Msg.ofVoid("setDrawableSize:", JAVA_DOUBLE, JAVA_DOUBLE);
    private static final Msg SET_ALLOWS_NEXT_DRAWABLE_TIMEOUT = Msg.ofVoid("setAllowsNextDrawableTimeout:", JAVA_BOOLEAN);
    private static final Msg SET_PRESENTS_WITH_TRANSACTION = Msg.ofVoid("setPresentsWithTransaction:", JAVA_BOOLEAN);
    private static final Msg SET_DISPLAY_SYNC_ENABLED = Msg.ofVoid("setDisplaySyncEnabled:", JAVA_BOOLEAN);
    private static final Msg NEXT_DRAWABLE = Msg.of("nextDrawable", true, ADDRESS);

    private final MemorySegment handle;
    private boolean released;

    /**
     * Whether the drawable may be read instead of only drawn into.
     * <p>
     * {@code framebufferOnly} is true by default and it is what lets the layer keep the drawable's storage in
     * whatever form is cheapest to scan out; a texture that is framebuffer-only may not be the source of a copy,
     * so the presented pixels are unreachable to this process. That is the whole reason the picture column of
     * every measurement session is empty: the display cannot be photographed here, and the drawable could not be
     * read.
     * <p>
     * Turning it off is a **diagnostic**, not a default: it changes the layer's contract and may cost scan-out
     * performance, so it is read from {@code -Dmetallum.drawableReadback=true} and nowhere else, and the session
     * says out loud that it is on.
     */
    private static final boolean READBACK =
            Boolean.parseBoolean(System.getProperty("metallum.drawableReadback", "false"));

    /** Whether this session asked to read the presented drawable back, for the frame path to honour. */
    public static boolean readbackRequested() {
        return READBACK;
    }

    public CAMetalLayer(final MTLDevice device, final double contentsScale) {
        this.handle = NEW.sendPtr(CLS);
        if (ObjC.isNil(this.handle)) {
            throw new IllegalStateException("Failed to create CAMetalLayer");
        }
        SET_DEVICE.send(this.handle, device.handle());
        SET_FRAMEBUFFER_ONLY.send(this.handle, !READBACK);
        SET_OPAQUE.send(this.handle, true);
        SET_CONTENTS_SCALE.send(this.handle, contentsScale);
        if (READBACK) {
            com.metallum.Metallum.LOGGER.warn("Metal layer: framebufferOnly is OFF because"
                    + " metallum.drawableReadback=true, so the presented drawable can be copied out and read -"
                    + " this is a diagnostic that changes the layer's contract, not a default");
        }
    }

    /**
     * Gives back the reference {@code new} took.
     * <p>
     * A layer is made with an explicit +1 that nothing else holds: clearing the view detaches it and
     * does not release it, so a device that is taken down without this leaves the layer - and whatever
     * it holds - allocated for the rest of the process. Guarded so that the failure path and the normal
     * teardown cannot both release one reference.
     */
    public void close() {
        if (!released) {
            released = true;
            ObjC.release(handle);
        }
    }

    public MemorySegment handle() {
        return this.handle;
    }

    public void configure(final double width, final double height, final boolean immediatePresentMode) {
        SET_PIXEL_FORMAT.send(this.handle, MTLPixelFormat.BGRA8Unorm.value);
        SET_DRAWABLE_SIZE.send(this.handle, width, height);
        SET_ALLOWS_NEXT_DRAWABLE_TIMEOUT.send(this.handle, false);
        SET_PRESENTS_WITH_TRANSACTION.send(this.handle, false);
        SET_DISPLAY_SYNC_ENABLED.send(this.handle, !immediatePresentMode);
    }

    @Nullable
    public CAMetalDrawable nextDrawable() {
        // What a frame waits for before it can be drawn at all. Gated on the probe so an unarmed session pays
        // one static boolean and no clock reads, and measured around the send alone: this is the drawable, not
        // the present or the submit.
        if (com.metallum.render.shared.MetalFrameProbe.armed()) {
            long begin = System.nanoTime();
            MemorySegment drawable = NEXT_DRAWABLE.sendPtr(this.handle);
            com.metallum.render.shared.MetalFrameProbe.drawableWait(System.nanoTime() - begin);
            return ObjC.isNil(drawable) ? null : new CAMetalDrawable(drawable);
        }

        MemorySegment drawable = NEXT_DRAWABLE.sendPtr(this.handle);
        return ObjC.isNil(drawable) ? null : new CAMetalDrawable(drawable);
    }
}
