package com.metallum.mtl;

import com.metallum.Metallum;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.MemorySegment;
import java.lang.invoke.MethodHandle;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

@Environment(EnvType.CLIENT)
public record MTLDevice(MemorySegment handle) {
    private static final MethodHandle CREATE_SYSTEM_DEFAULT_DEVICE = ObjC.LINKER.downcallHandle(
            ObjC.METAL.findOrThrow("MTLCreateSystemDefaultDevice"), FunctionDescriptor.of(ADDRESS));

    private static final Msg NEW_BUFFER = Msg.of("newBufferWithLength:options:", ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg NEW_COMMAND_QUEUE = Msg.of("newCommandQueue", ADDRESS);
    private static final Msg SUPPORTS_FAMILY = Msg.of("supportsFamily:", JAVA_LONG, JAVA_LONG);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);
    private static final Msg NEW_TEXTURE = Msg.of("newTextureWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg NEW_SAMPLER_STATE = Msg.of("newSamplerStateWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg NEW_DEPTH_STENCIL_STATE = Msg.of("newDepthStencilStateWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg NEW_FENCE = Msg.of("newFence", ADDRESS);
    private static final Msg NEW_LIBRARY_WITH_SOURCE = Msg.of("newLibraryWithSource:options:error:", true, ADDRESS, ADDRESS, ADDRESS, ADDRESS);
    private static final Msg NEW_FUNCTION_WITH_NAME = Msg.of("newFunctionWithName:", true, ADDRESS, ADDRESS);
    private static final Msg NEW_RENDER_PIPELINE_STATE = Msg.of("newRenderPipelineStateWithDescriptor:error:", true, ADDRESS, ADDRESS, ADDRESS);
    private static final Msg NEW_COMPUTE_PIPELINE_STATE = Msg.of("newComputePipelineStateWithFunction:error:", true, ADDRESS, ADDRESS, ADDRESS);
    private static final Msg LOCALIZED_DESCRIPTION = Msg.of("localizedDescription", ADDRESS);
    private static final Msg MINIMUM_TEXTURE_BUFFER_ALIGNMENT = Msg.of("minimumTextureBufferAlignmentForPixelFormat:", JAVA_LONG, JAVA_LONG);
    private static final Msg NAME = Msg.of("name", ADDRESS);
    private static final Msg MAX_BUFFER_LENGTH = Msg.of("maxBufferLength", JAVA_LONG);
    private static final Msg RECOMMENDED_MAX_WORKING_SET_SIZE = Msg.of("recommendedMaxWorkingSetSize", JAVA_LONG);
    private static final Msg ARGUMENT_BUFFERS_SUPPORT = Msg.of("argumentBuffersSupport", JAVA_LONG);
    private static final Msg MAX_ARGUMENT_BUFFER_SAMPLER_COUNT = Msg.of("maxArgumentBufferSamplerCount", JAVA_LONG);

    public MTLDevice {
        if (handle == null || handle.address() == 0L) {
            throw new IllegalArgumentException("MTLDevice handle is null");
        }
    }

    @Nullable
    public static MTLDevice createSystemDefault() {
        try {
            MemorySegment device = (MemorySegment) CREATE_SYSTEM_DEFAULT_DEVICE.invokeExact();
            return ObjC.isNil(device) ? null : new MTLDevice(device);
        } catch (Throwable throwable) {
            throw new IllegalStateException("MTLCreateSystemDefaultDevice failed", throwable);
        }
    }

    public String name() {
        try (AutoreleasePool _ = AutoreleasePool.push()) {
            return ObjC.javaString(NAME.sendPtr(handle));
        }
    }

    public long maxBufferLength() {
        return MAX_BUFFER_LENGTH.sendLong(handle);
    }

    public long recommendedMaxWorkingSetSize() {
        return RECOMMENDED_MAX_WORKING_SET_SIZE.sendLong(handle);
    }

    /** Tier 2 is the generic wide-resource path used for shader-declared argument buffers. */
    public boolean supportsArgumentBuffersTier2() {
        return ARGUMENT_BUFFERS_SUPPORT.sendLong(handle) >= 1L;
    }

    public long maxArgumentBufferSamplerCount() {
        return MAX_ARGUMENT_BUFFER_SAMPLER_COUNT.sendLong(handle);
    }

    public MTLBuffer newBuffer(final long length, final long options) {
        MemorySegment buffer = NEW_BUFFER.sendPtr(handle, length, options);
        if (ObjC.isNil(buffer)) {
            throw new IllegalStateException("newBufferWithLength:options: returned nil (length=" + length + ")");
        }
        return new MTLBuffer(buffer);
    }

    /**
     * Whether this GPU has the features of a GPU family.
     * <p>
     * Apple's own availability question, asked of the device rather than answered from a version table:
     * {@code supportsFamily:} takes an {@code MTLGPUFamily}, and the values are the SDK's -
     * {@code MTLGPUFamilyMetal4} is 5002, available from macOS 26.0.
     *
     * @param family the family's value
     * @return whether the device answers yes
     */
    public boolean supportsFamily(final long family) {
        return SUPPORTS_FAMILY.sendLong(handle, family) != 0L;
    }

    /**
     * Whether this object implements a selector.
     * <p>
     * The question to ask before reaching anything optional, because reaching a selector an object does
     * not implement is an Objective-C exception and one of those ends the process rather than answering
     * nil.
     *
     * @param name the selector's name, colons included
     * @return whether the object answers to it
     */
    public boolean respondsTo(final String name) {
        return RESPONDS_TO_SELECTOR.sendLong(handle, ObjC.selector(name)) != 0L;
    }

    public MTLCommandQueue newCommandQueue() {
        MemorySegment queue = NEW_COMMAND_QUEUE.sendPtr(handle);
        if (ObjC.isNil(queue)) {
            throw new IllegalStateException("newCommandQueue returned nil");
        }
        return new MTLCommandQueue(queue);
    }

    public MemorySegment newTexture(final MTLTextureDescriptor descriptor) {
        MemorySegment texture = NEW_TEXTURE.sendPtr(handle, descriptor.handle());
        if (ObjC.isNil(texture)) {
            throw new IllegalStateException("newTextureWithDescriptor: returned nil");
        }
        return texture;
    }

    public MemorySegment newSamplerState(final MTLSamplerDescriptor descriptor) {
        MemorySegment sampler = NEW_SAMPLER_STATE.sendPtr(handle, descriptor.handle());
        if (ObjC.isNil(sampler)) {
            throw new IllegalStateException("newSamplerStateWithDescriptor: returned nil");
        }
        return sampler;
    }

    public MemorySegment newDepthStencilState(final MTLDepthStencilDescriptor descriptor) {
        MemorySegment state = NEW_DEPTH_STENCIL_STATE.sendPtr(handle, descriptor.handle());
        if (ObjC.isNil(state)) {
            throw new IllegalStateException("newDepthStencilStateWithDescriptor: returned nil");
        }
        return state;
    }

    public MTLFence newFence() {
        MemorySegment fence = NEW_FENCE.sendPtr(handle);
        if (ObjC.isNil(fence)) {
            throw new IllegalStateException("newFence returned nil");
        }
        return new MTLFence(fence);
    }

    public MemorySegment newFunction(final String mslSource, final String entryPoint) {
        try (AutoreleasePool _ = AutoreleasePool.push();
             Arena arena = Arena.ofConfined();
             MTLCompileOptions options = new MTLCompileOptions()) {
            // Vitrail marks gl_Position invariant for geometry that can be redrawn by another
            // program at the exact same depth. SPIRV-Cross carries that through to MSL, but Metal
            // ignores [[invariant]] unless preserveInvariance is enabled at library compilation.
            // Enabling it for the library is safe for ordinary shaders: the conservative contract
            // only applies to position outputs that were actually marked invariant.
            options.setPreserveInvariance(true);
            // The profile the translator emitted, so the two halves of one decision cannot drift apart: a
            // library compiled as 4.0 while the MSL was emitted for 3.2 is a pipeline that either fails or
            // means something neither side asked for.
            options.setLanguageVersion(
                    com.metallum.render.execution.MetalShaderLanguageProfile.selected().metalLanguageVersion());
            MemorySegment errorOut = arena.allocate(ADDRESS);
            MemorySegment nsSource = ObjC.nsString(mslSource);
            MemorySegment library = NEW_LIBRARY_WITH_SOURCE.sendPtr(handle, nsSource, options.handle(), errorOut);
            ObjC.release(nsSource);
            if (ObjC.isNil(library)) {
                Metallum.LOGGER.error("[metallum] Failed to compile MSL: {}", errorDescription(errorOut));
                return MemorySegment.NULL;
            }
            MemorySegment nsEntry = ObjC.nsString(entryPoint);
            MemorySegment function = NEW_FUNCTION_WITH_NAME.sendPtr(library, nsEntry);
            ObjC.release(nsEntry);
            ObjC.release(library);
            if (ObjC.isNil(function)) {
                Metallum.LOGGER.error("[metallum] Failed to resolve MSL entry point '{}'", entryPoint);
                return MemorySegment.NULL;
            }
            return function;
        }
    }

    public MemorySegment newRenderPipelineState(final MTLRenderPipelineDescriptor descriptor) {
        try (AutoreleasePool _ = AutoreleasePool.push(); Arena arena = Arena.ofConfined()) {
            MemorySegment errorOut = arena.allocate(ADDRESS);
            MemorySegment pipeline = NEW_RENDER_PIPELINE_STATE.sendPtr(handle, descriptor.handle(), errorOut);
            if (ObjC.isNil(pipeline)) {
                Metallum.LOGGER.error("[metallum] Failed to create render pipeline state: {}", errorDescription(errorOut));
                return MemorySegment.NULL;
            }
            return pipeline;
        }
    }

    public MemorySegment newComputePipelineState(final MemorySegment function) {
        try (AutoreleasePool _ = AutoreleasePool.push(); Arena arena = Arena.ofConfined()) {
            MemorySegment errorOut = arena.allocate(ADDRESS);
            MemorySegment pipeline = NEW_COMPUTE_PIPELINE_STATE.sendPtr(handle, function, errorOut);
            if (ObjC.isNil(pipeline)) {
                Metallum.LOGGER.error("[metallum] Failed to create compute pipeline state: {}", errorDescription(errorOut));
                return MemorySegment.NULL;
            }
            return pipeline;
        }
    }

    static long minimumTextureBufferAlignment(final MemorySegment device, final long pixelFormat) {
        return MINIMUM_TEXTURE_BUFFER_ALIGNMENT.sendLong(device, pixelFormat);
    }

    /** The text of an NSError an out-parameter was given, for a caller that must say what failed. */
    public static String errorText(final MemorySegment errorOut) {
        return errorDescription(errorOut);
    }

    private static String errorDescription(final MemorySegment errorOut) {
        MemorySegment error = errorOut.get(ADDRESS, 0L);
        return ObjC.isNil(error) ? "unknown error" : ObjC.javaString(LOCALIZED_DESCRIPTION.sendPtr(error));
    }
}
