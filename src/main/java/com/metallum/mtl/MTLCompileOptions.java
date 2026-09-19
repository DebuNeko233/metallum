package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_BOOLEAN;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/** Compiler options shared by native Metal shader-library compilation. */
@Environment(EnvType.CLIENT)
public final class MTLCompileOptions implements AutoCloseable {
    private static final MemorySegment CLS = ObjC.clazz("MTLCompileOptions");
    private static final Msg NEW = Msg.of("new", ADDRESS);
    private static final Msg SET_PRESERVE_INVARIANCE = Msg.ofVoid("setPreserveInvariance:", JAVA_BOOLEAN);
    private static final Msg SET_LANGUAGE_VERSION = Msg.ofVoid("setLanguageVersion:", JAVA_LONG);

    private final MemorySegment handle;
    private boolean closed;

    public MTLCompileOptions() {
        this.handle = NEW.sendPtr(CLS);
        if (ObjC.isNil(this.handle)) {
            throw new IllegalStateException("MTLCompileOptions new returned nil");
        }
    }

    public MemorySegment handle() {
        return this.handle;
    }

    /**
     * The MSL version this compilation is allowed to be.
     * <p>
     * Set explicitly and always: left alone, the option is whatever the system's newest is, so a session
     * that meant to compile for an older Metal 3 system would silently get the newest language - and the
     * profile the translator was given would then not be the profile the compiler enforced.
     */
    public void setLanguageVersion(final long version) {
        SET_LANGUAGE_VERSION.send(handle, version);
    }

    public void setPreserveInvariance(final boolean preserve) {
        SET_PRESERVE_INVARIANCE.send(this.handle, preserve);
    }

    @Override
    public void close() {
        if (!this.closed) {
            this.closed = true;
            ObjC.release(this.handle);
        }
    }
}
