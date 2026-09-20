package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;

/**
 * A Metal 4 compiler object: the thing a Metal 4 factory that has to build a pipeline asks for.
 * <p>
 * Metal 4 keeps pipeline compilation in a compiler the app owns rather than on the device, so the factories that
 * take one - {@code MTLFXSpatialScalerDescriptor}'s Metal 4 spelling among them - cannot be reached without this
 * object existing. Nothing else in this backend needs a compiler yet: the frame path builds the game's pipelines
 * through the device's own factories, which are Metal 3's and are proven to work on Metal 4 encoders.
 * <p>
 * <strong>Every way it can fail is an answer and not an exception</strong>, in the shape section 104 asks for: a
 * device that does not answer the factory, a class that is not there, and a factory that comes back nil are three
 * different sentences, each said once, and the caller is handed null rather than a handle that would fault twenty
 * calls later.
 */
@Environment(EnvType.CLIENT)
public final class MTL4Compiler implements AutoCloseable {

    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    /** The device's own factory: the header's {@code MTLDevice.h} declares it with an error out-parameter. */
    private static final Msg NEW_COMPILER =
            Msg.of("newCompilerWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS);

    private final MemorySegment handle;

    private MTL4Compiler(final MemorySegment handle) {
        this.handle = handle;
    }

    /**
     * A compiler for this device, or null where the device will not make one.
     *
     * @param device the device binding
     */
    @Nullable
    public static MTL4Compiler create(final MTLDevice device) {
        if (device == null || ObjC.isNil(device.handle())) {
            Metallum.LOGGER.warn("Metal 4 compiler: there is no device to make one from");
            return null;
        }
        if (!device.respondsTo("newCompilerWithDescriptor:error:")) {
            Metallum.LOGGER.warn("Metal 4 compiler: this device does not answer newCompilerWithDescriptor:error:,"
                    + " so nothing that needs a compiler can be made on it");
            return null;
        }

        MemorySegment descriptor;
        try {
            descriptor = NEW_DESCRIPTOR.sendPtr(ObjC.clazz("MTL4CompilerDescriptor"));
        } catch (Throwable missing) {
            Metallum.LOGGER.warn("Metal 4 compiler: MTL4CompilerDescriptor is not there ({})",
                    missing.getMessage());
            return null;
        }
        if (ObjC.isNil(descriptor)) {
            Metallum.LOGGER.warn("Metal 4 compiler: MTL4CompilerDescriptor could not be made");
            return null;
        }

        MemorySegment made = NEW_COMPILER.sendPtr(device.handle(), descriptor, MemorySegment.NULL);
        ObjC.release(descriptor);
        if (ObjC.isNil(made)) {
            Metallum.LOGGER.warn("Metal 4 compiler: the device made none, with a null error slot");
            return null;
        }
        return new MTL4Compiler(made);
    }

    /** The object itself, which is what a Metal 4 factory is handed. */
    public MemorySegment handle() {
        return this.handle;
    }

    @Override
    public void close() {
        if (!ObjC.isNil(this.handle)) {
            ObjC.release(this.handle);
        }
    }
}
