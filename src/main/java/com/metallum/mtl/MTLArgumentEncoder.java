package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/** Encodes Metal resources into a shader-declared argument buffer. */
@Environment(EnvType.CLIENT)
public final class MTLArgumentEncoder implements AutoCloseable {
    private static final Msg NEW_ARGUMENT_ENCODER = Msg.of("newArgumentEncoderWithBufferIndex:", ADDRESS, JAVA_LONG);
    private static final Msg ENCODED_LENGTH = Msg.of("encodedLength", JAVA_LONG);
    private static final Msg SET_ARGUMENT_BUFFER = Msg.ofVoid("setArgumentBuffer:offset:", ADDRESS, JAVA_LONG);
    private static final Msg SET_BUFFER = Msg.ofVoid("setBuffer:offset:atIndex:", ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:atIndex:", ADDRESS, JAVA_LONG);
    private static final Msg SET_SAMPLER = Msg.ofVoid("setSamplerState:atIndex:", ADDRESS, JAVA_LONG);

    private final MemorySegment handle;

    private MTLArgumentEncoder(final MemorySegment handle) {
        if (ObjC.isNil(handle)) {
            throw new IllegalArgumentException("MTLArgumentEncoder handle is nil");
        }
        this.handle = handle;
    }

    public static MTLArgumentEncoder forFunction(final MemorySegment function, final long bufferIndex) {
        MemorySegment encoder = NEW_ARGUMENT_ENCODER.sendPtr(function, bufferIndex);
        if (ObjC.isNil(encoder)) {
            throw new IllegalStateException(
                    "newArgumentEncoderWithBufferIndex: returned nil for buffer index " + bufferIndex
            );
        }
        return new MTLArgumentEncoder(encoder);
    }

    public long encodedLength() {
        return ENCODED_LENGTH.sendLong(handle);
    }

    public void setArgumentBuffer(final MTLBuffer buffer, final long offset) {
        SET_ARGUMENT_BUFFER.send(handle, buffer == null ? MemorySegment.NULL : buffer.handle(), offset);
    }

    public void setBuffer(final MTLBuffer buffer, final long offset, final long index) {
        SET_BUFFER.send(handle, buffer == null ? MemorySegment.NULL : buffer.handle(), offset, index);
    }

    public void setTexture(final MemorySegment texture, final long index) {
        SET_TEXTURE.send(handle, ObjC.orNil(texture), index);
    }

    public void setSamplerState(final MemorySegment sampler, final long index) {
        SET_SAMPLER.send(handle, ObjC.orNil(sampler), index);
    }

    @Override
    public void close() {
        ObjC.release(handle);
    }
}
