package com.metallum.mtl;

import com.metallum.objc.Msg;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public final class MTLBuffer {
    private static final Msg CONTENTS = Msg.of("contents", ADDRESS);
    private static final Msg LENGTH = Msg.of("length", JAVA_LONG);
    private static final Msg GPU_ADDRESS = Msg.of("gpuAddress", JAVA_LONG);

    private final MemorySegment handle;

    MTLBuffer(final MemorySegment handle) {
        if (handle == null || handle.address() == 0L) {
            throw new IllegalArgumentException("MTLBuffer handle is null");
        }
        this.handle = handle;
    }

    public MemorySegment handle() {
        return handle;
    }

    public MemorySegment contents() {
        return CONTENTS.sendPtr(handle);
    }

    public long length() {
        return LENGTH.sendLong(handle);
    }

    /**
     * The address Metal 4's argument tables bind a buffer by, or zero where this OS has no such property.
     * <p>
     * Asked for rather than assumed: {@code gpuAddress} arrived after the rest of the buffer surface, and a
     * buffer that answers nothing is a buffer the new path cannot bind - a fact to report, not to crash on.
     */
    public long gpuAddress() {
        return MTL4Probe.respondsTo(handle, "gpuAddress") ? GPU_ADDRESS.sendLong(handle) : 0L;
    }
}
