package com.metallum.mtl;

import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import org.lwjgl.system.MemoryStack;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public final class MTLTexture {
    private static final Msg PIXEL_FORMAT = Msg.of("pixelFormat", JAVA_LONG);
    private static final Msg WIDTH = Msg.of("width", JAVA_LONG);
    private static final Msg HEIGHT = Msg.of("height", JAVA_LONG);
    private static final Msg TEXTURE_TYPE = Msg.of("textureType", JAVA_LONG);
    private static final Msg ARRAY_LENGTH = Msg.of("arrayLength", JAVA_LONG);
    private static final Msg MIPMAP_LEVEL_COUNT = Msg.of("mipmapLevelCount", JAVA_LONG);
    private static final Msg STORAGE_MODE = Msg.of("storageMode", JAVA_LONG);
    private static final Msg DEVICE = Msg.of("device", ADDRESS);
    private static final Msg LENGTH = Msg.of("length", JAVA_LONG);
    private static final Msg NEW_TEXTURE_VIEW = Msg.of(
            "newTextureViewWithPixelFormat:textureType:levels:slices:",
            ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg NEW_TEXTURE_FROM_BUFFER = Msg.of(
            "newTextureWithDescriptor:offset:bytesPerRow:", ADDRESS, ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final MemorySegment TEXTURE_DESCRIPTOR_CLS = ObjC.clazz("MTLTextureDescriptor");
    private static final Msg TEXTURE_BUFFER_DESCRIPTOR = Msg.of(
            "textureBufferDescriptorWithPixelFormat:width:resourceOptions:usage:",
            ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg SET_STORAGE_MODE = Msg.ofVoid("setStorageMode:", JAVA_LONG);
    private static final Msg SET_HAZARD_TRACKING_MODE = Msg.ofVoid("setHazardTrackingMode:", JAVA_LONG);
    private static final Msg GET_BYTES = Msg.ofVoid(
            "getBytes:bytesPerRow:fromRegion:mipmapLevel:", ADDRESS, JAVA_LONG, ADDRESS, JAVA_LONG);

    private MTLTexture() {
    }

    /**
     * Copies one region of a texture back into memory the caller owns.
     * <p>
     * Only a texture whose storage is shared answers this; a private one is only ever read by the GPU. The
     * region is passed as the header declares it - by pointer - the way the engine passes a viewport.
     */
    public static void bytes(final MemorySegment texture, final MemorySegment into, final long bytesPerRow,
                            final long x, final long y, final long width, final long height) {
        try (MemoryStack stack = MemoryStack.stackPush()) {
            MemorySegment region = MemorySegment.ofAddress(stack.nmalloc(8, 48)).reinterpret(48);
            region.set(JAVA_LONG, 0, x);
            region.set(JAVA_LONG, 8, y);
            region.set(JAVA_LONG, 16, 0L);
            region.set(JAVA_LONG, 24, width);
            region.set(JAVA_LONG, 32, height);
            region.set(JAVA_LONG, 40, 1L);
            GET_BYTES.send(texture, into, bytesPerRow, region, 0L);
        }
    }

    public static long pixelFormat(final MemorySegment texture) {
        return PIXEL_FORMAT.sendLong(texture);
    }

    public static long width(final MemorySegment texture) {
        return WIDTH.sendLong(texture);
    }

    public static long height(final MemorySegment texture) {
        return HEIGHT.sendLong(texture);
    }

    public static MemorySegment newTextureView(final MemorySegment texture, final long baseMipLevel, final long mipLevelCount) {
        if (mipLevelCount <= 0) {
            return MemorySegment.NULL;
        }
        long totalMipLevels = MIPMAP_LEVEL_COUNT.sendLong(texture);
        if (baseMipLevel >= totalMipLevels || baseMipLevel + mipLevelCount > totalMipLevels) {
            return MemorySegment.NULL;
        }
        return NEW_TEXTURE_VIEW.sendPtr(
                texture,
                PIXEL_FORMAT.sendLong(texture),
                TEXTURE_TYPE.sendLong(texture),
                baseMipLevel, mipLevelCount,
                0L, sliceCount(texture)
        );
    }

    public static MemorySegment newBufferTextureView(
            final MemorySegment buffer,
            final long pixelFormat,
            final long offset,
            final long width,
            final long bytesPerRow
    ) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            if (pixelFormat == MTLPixelFormat.Invalid.value || width <= 0 || bytesPerRow <= 0 || offset < 0) {
                return MemorySegment.NULL;
            }
            long bufferLength = LENGTH.sendLong(buffer);
            if (offset > bufferLength || bytesPerRow > bufferLength - offset) {
                return MemorySegment.NULL;
            }

            MemorySegment device = DEVICE.sendPtr(buffer);
            long alignment = MTLDevice.minimumTextureBufferAlignment(device, pixelFormat);
            if (alignment <= 0 || offset % alignment != 0) {
                return MemorySegment.NULL;
            }
            long alignedBytesPerRow = roundUp(bytesPerRow, alignment);

            MemorySegment descriptor = TEXTURE_BUFFER_DESCRIPTOR.sendPtr(
                    TEXTURE_DESCRIPTOR_CLS, pixelFormat, width, 0L, MTLTextureUsage.ShaderRead.value);
            SET_STORAGE_MODE.send(descriptor, STORAGE_MODE.sendLong(buffer));
            SET_HAZARD_TRACKING_MODE.send(descriptor, MTLHazardTrackingMode.Untracked.value);

            return NEW_TEXTURE_FROM_BUFFER.sendPtr(buffer, descriptor, offset, alignedBytesPerRow);
        }
    }

    private static long sliceCount(final MemorySegment texture) {
        long type = TEXTURE_TYPE.sendLong(texture);
        if (type == MTLTextureType.Type2DArray.value) {
            return Math.max(ARRAY_LENGTH.sendLong(texture), 1L);
        }
        if (type == MTLTextureType.TypeCube.value) {
            return 6L;
        }
        if (type == MTLTextureType.TypeCubeArray.value) {
            return Math.max(ARRAY_LENGTH.sendLong(texture), 1L) * 6L;
        }
        return 1L;
    }

    private static long roundUp(final long value, final long alignment) {
        long remainder = value % alignment;
        return remainder == 0 ? value : value + alignment - remainder;
    }
}
