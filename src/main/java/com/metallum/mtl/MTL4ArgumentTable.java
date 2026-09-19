package com.metallum.mtl;

import com.metallum.Metallum;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * A Metal 4 argument table, which is how the new encoders are given resources.
 * <p>
 * Metal 4's encoder protocols have no per-resource binding methods at all: what an encoder sees is an
 * argument table it has been assigned, and the table is filled by resource id rather than by object. This
 * class is that table for the shape this engine needs - one texture and one sampler - and it hides the id
 * step, so a caller hands it the resource handles the rest of the engine already carries.
 * <p>
 * Every selector is asked for before it is sent, like the rest of the new path: an unimplemented one is an
 * Objective-C exception, not a nil.
 */
@Environment(EnvType.CLIENT)
public final class MTL4ArgumentTable implements AutoCloseable {

    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    private static final Msg NEW_TABLE = Msg.of("newArgumentTableWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg SET_MAX_BUFFER = Msg.ofVoid("setMaxBufferBindCount:", JAVA_LONG);
    private static final Msg SET_MAX_TEXTURE = Msg.ofVoid("setMaxTextureBindCount:", JAVA_LONG);
    private static final Msg SET_MAX_SAMPLER = Msg.ofVoid("setMaxSamplerStateBindCount:", JAVA_LONG);
    private static final Msg SET_INITIALIZE = Msg.ofVoid("setInitializeBindings:", JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:atIndex:", JAVA_LONG, JAVA_LONG);
    private static final Msg SET_SAMPLER = Msg.ofVoid("setSamplerState:atIndex:", JAVA_LONG, JAVA_LONG);
    private static final Msg RESOURCE_ID = Msg.of("gpuResourceID", JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private final MemorySegment handle;

    private MTL4ArgumentTable(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * Makes a table for one texture and one sampler, or null where this device will not make one.
     *
     * @param device the device binding
     */
    @Nullable
    public static MTL4ArgumentTable create(final MTLDevice device) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            if (!device.respondsTo("newArgumentTableWithDescriptor:")) {
                Metallum.LOGGER.warn("Metal 4 argument table: this device answers to no "
                        + "newArgumentTableWithDescriptor:, so nothing can be bound on the new path");
                return null;
            }

            MemorySegment descriptor;
            try {
                descriptor = NEW_DESCRIPTOR.sendPtr(ObjC.clazz("MTL4ArgumentTableDescriptor"));
            } catch (Throwable missing) {
                Metallum.LOGGER.warn("Metal 4 argument table: MTL4ArgumentTableDescriptor is not there ({})",
                        missing.getMessage());
                return null;
            }
            if (ObjC.isNil(descriptor)) {
                return null;
            }

            SET_MAX_BUFFER.send(descriptor, 0L);
            SET_MAX_TEXTURE.send(descriptor, 1L);
            SET_MAX_SAMPLER.send(descriptor, 1L);
            // The table is filled every frame before it is used, so its bindings need no initial values -
            // and one that was left uninitialised would be read as null and fault the draw rather than draw
            // the wrong thing, which is the direction to fail in.
            SET_INITIALIZE.send(descriptor, 0L);

            MemorySegment made = NEW_TABLE.sendPtr(device.handle(), descriptor);
            ObjC.release(descriptor);
            if (ObjC.isNil(made)) {
                Metallum.LOGGER.warn("Metal 4 argument table: the device made none for one texture and one "
                        + "sampler");
                return null;
            }

            return new MTL4ArgumentTable(made);
        }
    }

    /** Points the table's one texture slot at a texture, by the resource id the framework gives it. */
    public boolean texture(final MemorySegment textureHandle) {
        if (ObjC.isNil(textureHandle) || !responds(textureHandle, "gpuResourceID")) {
            return false;
        }

        SET_TEXTURE.send(handle, RESOURCE_ID.sendLong(textureHandle), 0L);
        return true;
    }

    /** Points the table's one sampler slot at a sampler state, the same way. */
    public boolean sampler(final MemorySegment samplerHandle) {
        if (ObjC.isNil(samplerHandle) || !responds(samplerHandle, "gpuResourceID")) {
            return false;
        }

        SET_SAMPLER.send(handle, RESOURCE_ID.sendLong(samplerHandle), 0L);
        return true;
    }

    public MemorySegment handle() {
        return handle;
    }

    @Override
    public void close() {
        if (!ObjC.isNil(handle)) {
            ObjC.release(handle);
        }
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }
}
