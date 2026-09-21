package com.metallum.mtl.metal4;

import com.metallum.mtl.MTLDevice;

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
 * <strong>The factory's name is the header's, out-parameter and all.</strong> This class asked for
 * {@code newArgumentTableWithDescriptor:} for a day and got no, and the no was read as the device refusing
 * to make tables - which stopped the whole Metal 4 picture path. The header declares two arguments
 * ({@code MTLDevice.h}: {@code newArgumentTableWithDescriptor:(MTL4ArgumentTableDescriptor *)descriptor
 * error:(NSError * _Nullable *)error}), so the selector is {@code newArgumentTableWithDescriptor:error:},
 * and a native probe on the M5 Pro answers yes to it and makes a table with an error slot of null. The
 * plain name is kept as a fallback rather than as the first question: a device that implements the one a
 * header does not describe is the surprising case, not this one.
 * <p>
 * Every selector is asked for before it is sent, like the rest of the new path: an unimplemented one is an
 * Objective-C exception, not a nil.
 */
@Environment(EnvType.CLIENT)
public final class MTL4ArgumentTable implements AutoCloseable {

    /** The switch the frame path's per-pass trace uses, so one property asks for every creation event. */
    private static final boolean TRACE = Boolean.getBoolean("metallum.metal4Trace");

    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    /** The header's own factory: the descriptor and a null error slot. */
    private static final Msg NEW_TABLE_WITH_ERROR =
            Msg.of("newArgumentTableWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS);
    /** The name without the error slot, which this device does not implement - kept for a device that does. */
    private static final Msg NEW_TABLE = Msg.of("newArgumentTableWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg SET_MAX_BUFFER = Msg.ofVoid("setMaxBufferBindCount:", JAVA_LONG);
    private static final Msg SET_MAX_TEXTURE = Msg.ofVoid("setMaxTextureBindCount:", JAVA_LONG);
    private static final Msg SET_MAX_SAMPLER = Msg.ofVoid("setMaxSamplerStateBindCount:", JAVA_LONG);
    private static final Msg SET_INITIALIZE = Msg.ofVoid("setInitializeBindings:", JAVA_LONG);
    private static final Msg SET_ATTRIBUTE_STRIDES = Msg.ofVoid("setSupportAttributeStrides:", JAVA_LONG);
    private static final Msg SET_ADDRESS = Msg.ofVoid("setAddress:atIndex:", JAVA_LONG, JAVA_LONG);
    private static final Msg SET_ADDRESS_STRIDED =
            Msg.ofVoid("setAddress:attributeStride:atIndex:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
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
        return create(device, 0L, 1L, 1L);
    }

    /**
     * The same, sized to what a layout binds: buffers, textures and samplers.
     * <p>
     * The counts are the descriptor's own limits and a table is made for what a layout uses rather than for
     * what some other layout might. Metal caps them at 31 buffers, 128 textures and 16 samplers.
     *
     * @param device   the device binding
     * @param buffers  the buffer slots this table is to have
     * @param textures the texture slots
     * @param samplers the sampler slots
     */
    @Nullable
    public static MTL4ArgumentTable create(final MTLDevice device, final long buffers, final long textures,
                                           final long samplers) {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            boolean withError = device.respondsTo("newArgumentTableWithDescriptor:error:");
            boolean withoutError = device.respondsTo("newArgumentTableWithDescriptor:");
            if (!withError && !withoutError) {
                Metallum.LOGGER.warn("Metal 4 argument table: this device answers to neither "
                        + "newArgumentTableWithDescriptor:error: nor newArgumentTableWithDescriptor:, so "
                        + "nothing can be bound on the new path");
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

            SET_MAX_BUFFER.send(descriptor, buffers);
            SET_MAX_TEXTURE.send(descriptor, textures);
            SET_MAX_SAMPLER.send(descriptor, samplers);
            // Initialised to nil, and the reason is measured rather than reasoned: the header says this
            // property's default is false, so a slot the frame path never fills holds whatever the driver left
            // there - and a shader that reads one dereferences that. The first world frame - the first frame that
            // draws the clouds - was killing the GPU with an MMU fault on exactly that, so a slot this path does
            // not fill must read as zero, which is what the Metal 3 pass does with a name its layout never
            // encodes.
            //
            // This comment used to name the cloud pass as the example of a binding that is skipped by design -
            // "the engine's own cloud pass binds a uniform under a name its pipeline gives a texture". That was
            // the defect itself rather than a description of one: the name is a texel buffer, which Metal binds
            // as a texture made over the buffer, and the pass was skipping the binding because it asked only the
            // buffer-slot question. Both generations bind it now (MetalRenderPass.createTexelBufferTexture, and
            // this generation's fillTexelBuffer), and the initialisation below is what a slot with genuinely no
            // binding still needs.
            SET_INITIALIZE.send(descriptor, 1L);
            // The header asks for this before a vertex buffer is bound with a stride: it is what reserves
            // room for the strides in the table. Reserving it on a table with buffer slots costs a little
            // memory and is what makes `setAddress:attributeStride:atIndex:` the call the header describes.
            SET_ATTRIBUTE_STRIDES.send(descriptor, buffers > 0L ? 1L : 0L);

            MemorySegment made = withError
                    ? NEW_TABLE_WITH_ERROR.sendPtr(device.handle(), descriptor, MemorySegment.NULL)
                    : NEW_TABLE.sendPtr(device.handle(), descriptor);
            ObjC.release(descriptor);
            if (ObjC.isNil(made)) {
                Metallum.LOGGER.warn("Metal 4 argument table: the device made none for {} buffers, {} textures "
                        + "and {} samplers (asked with {})", buffers, textures, samplers,
                        withError ? "the error slot" : "no error slot");
                return null;
            }

            // Said under the trace switch rather than every time, because this path makes a table per pass: a
            // Photon session wrote 525893 lines to its log and 105187 of them were this one, one per table per
            // pass. The routine fact belongs to the frame probe's `tablesPerFrame`, which counts every table
            // without printing any, and a creation event is what a reader asks for by name.
            //
            // It is hygiene and **not** a fix for anything: this line was first suspected of starving the render
            // thread while a pack loaded, and gating it changed that session's outcome by nothing at all - the
            // same 251 pack units served at the same twelve seconds, before and after. The stop was elsewhere,
            // and the suspicion is recorded here so nobody re-runs it as an experiment.
            if (TRACE) {
                Metallum.LOGGER.info("Metal 4 argument table: made for {} buffers, {} textures and {} samplers, "
                        + "through {}", buffers, textures, samplers,
                        withError ? "newArgumentTableWithDescriptor:error:" : "newArgumentTableWithDescriptor:");
            }
            return new MTL4ArgumentTable(made);
        }
    }

    /**
     * Points one of the table's buffer slots at a GPU address, which is how Metal 4 binds a buffer.
     *
     * @return whether there was an address to bind
     */
    public boolean address(final long gpuAddress, final long index) {
        if (gpuAddress == 0L) {
            return false;
        }

        SET_ADDRESS.send(handle, gpuAddress, index);
        return true;
    }

    /**
     * The same, with the stride a vertex-array buffer is read by, which is what {@code attributeStride}
     * exists for: without it a table-bound vertex buffer has no layout to read.
     */
    public boolean address(final long gpuAddress, final long stride, final long index) {
        if (gpuAddress == 0L) {
            return false;
        }

        SET_ADDRESS_STRIDED.send(handle, gpuAddress, stride, index);
        return true;
    }

    /** Points the table's one texture slot at a texture, by the resource id the framework gives it. */
    public boolean texture(final MemorySegment textureHandle) {
        return texture(textureHandle, 0L);
    }

    /**
     * The same, at the slot the layout binds.
     * <p>
     * A pass that samples more than one image fills more than one slot, and the slot is the index the shader's
     * own {@code [[texture(n)]]} attribute names - which is why the index is the caller's and not this
     * class's: the binding is the program's, and a table that always wrote slot zero could bind one image and
     * silently leave a second one unread.
     *
     * @return whether there was a resource id to bind
     */
    public boolean texture(final MemorySegment textureHandle, final long index) {
        if (ObjC.isNil(textureHandle) || !responds(textureHandle, "gpuResourceID")) {
            return false;
        }

        SET_TEXTURE.send(handle, RESOURCE_ID.sendLong(textureHandle), index);
        return true;
    }

    /** Points the table's one sampler slot at a sampler state, the same way. */
    public boolean sampler(final MemorySegment samplerHandle) {
        return sampler(samplerHandle, 0L);
    }

    /**
     * The same, at the slot the layout binds: a stage that samples more than one image fills more than one
     * sampler slot, and the slot is the index the shader's own {@code [[sampler(n)]]} attribute names.
     *
     * @return whether there was a resource id to bind
     */
    public boolean sampler(final MemorySegment samplerHandle, final long index) {
        if (ObjC.isNil(samplerHandle) || !responds(samplerHandle, "gpuResourceID")) {
            return false;
        }

        SET_SAMPLER.send(handle, RESOURCE_ID.sendLong(samplerHandle), index);
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
