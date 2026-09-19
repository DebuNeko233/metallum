package com.metallum.render.execution;

import com.metallum.mtl.metal4.MTL4Probe;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.ObjC;
import com.metallum.render.Metal4;
import com.metallum.render.MetalFx;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

/**
 * What this device can actually run, asked once at device creation and immutable afterwards.
 * <p>
 * The record exists because a single question is not enough to choose a path: {@code supportsFamily:} says
 * a family exists, and every one of the selectors and classes below is a separate answer that can be no on
 * a device that says yes to the family - which this engine has already been taught twice, once by a factory
 * whose header declares it and the runtime does not implement, and once by a family answer that came with
 * no argument table only because the wrong selector was asked. So the minimum contract is a list of
 * answers, and the selector requires all of them.
 *
 * @param system                  the machine, for the log
 * @param metal3Family            the device answers for {@code MTLGPUFamilyMetal3}
 * @param metal4Family            the device answers for {@code MTLGPUFamilyMetal4}
 * @param metal4CommandQueue      {@code newMTL4CommandQueue} answers
 * @param metal4CommandAllocator  an allocator is made and can be reset
 * @param metal4CommandBuffer     a command buffer is made, begun, ended and committed (the probe's answer)
 * @param metal4ArgumentTable     a table is made and binds a buffer by address and a texture by id
 * @param metal4RenderEncoder     a render encoder is made from the command buffer and draws
 * @param metal4ComputeEncoder    a compute encoder is made from the command buffer
 * @param argumentBuffersTier2    {@code argumentBuffersSupport} is tier 2
 * @param maxArgumentBufferSamplerCount the device's own sampler ceiling for argument buffers
 * @param residencySets           the device has the residency-set factory
 * @param textureViewPools        the device has the texture-view-pool factory
 * @param metal4Compiler          the device has the compiler factory
 * @param metalFxSpatial          the Metal 3 spatial scaler is available on this device
 * @param metal4FxSpatial         the Metal 4 spatial scaler exists and its factory answers
 * @param shaderLanguageProfile   the newest MSL profile this system's Metal 3 path accepts, probed
 *                                by compiling; the session's profile is chosen with the generation and
 *                                held on {@link MetalShaderLanguageProfile}
 */
@Environment(EnvType.CLIENT)
public record MetalDeviceCapabilities(
        MetalSystemProfile system,
        boolean metal3Family,
        boolean metal4Family,
        boolean metal4CommandQueue,
        boolean metal4CommandAllocator,
        boolean metal4CommandBuffer,
        boolean metal4ArgumentTable,
        boolean metal4RenderEncoder,
        boolean metal4ComputeEncoder,
        boolean argumentBuffersTier2,
        long maxArgumentBufferSamplerCount,
        boolean residencySets,
        boolean textureViewPools,
        boolean metal4Compiler,
        boolean metalFxSpatial,
        boolean metal4FxSpatial,
        MetalShaderLanguageProfile shaderLanguageProfile
) {

    private static final long FAMILY_METAL3 = 5001L;
    private static final long FAMILY_METAL4 = 5002L;

    /**
     * Asks the device everything the record holds.
     * <p>
     * The command-structure answers come from the probe that already made and submitted the objects, so
     * nothing here creates a second queue to find out what the first one proved.
     */
    public static MetalDeviceCapabilities probe(final MTLDevice device, final String deviceName) {
        boolean metal3 = device.supportsFamily(FAMILY_METAL3);
        boolean metal4 = device.supportsFamily(FAMILY_METAL4);
        boolean queue = device.respondsTo("newMTL4CommandQueue");
        boolean allocator = device.respondsTo("newCommandAllocator");
        boolean buffer = device.respondsTo("newCommandBuffer");
        boolean argumentTable = MTL4Probe.respondsTo(device.handle(), "newArgumentTableWithDescriptor:error:")
                || MTL4Probe.respondsTo(device.handle(), "newArgumentTableWithDescriptor:");

        MemorySegment madeBuffer = MemorySegment.NULL;
        boolean renderEncoder = false;
        boolean computeEncoder = false;
        if (buffer) {
            try (com.metallum.objc.AutoreleasePool _ = com.metallum.objc.AutoreleasePool.push()) {
                madeBuffer = com.metallum.objc.Msg.of("newCommandBuffer", java.lang.foreign.ValueLayout.ADDRESS)
                        .sendPtr(device.handle());
                renderEncoder = !ObjC.isNil(madeBuffer)
                        && MTL4Probe.respondsTo(madeBuffer, "renderCommandEncoderWithDescriptor:");
                computeEncoder = !ObjC.isNil(madeBuffer)
                        && MTL4Probe.respondsTo(madeBuffer, "computeCommandEncoder");
            } finally {
                if (!ObjC.isNil(madeBuffer)) {
                    ObjC.release(madeBuffer);
                }
            }
        }

        return new MetalDeviceCapabilities(
                MetalSystemProfile.of(deviceName),
                metal3,
                metal4,
                queue,
                allocator && Metal4.canMakeAndSubmit(),
                buffer && Metal4.canMakeAndSubmit(),
                argumentTable && Metal4.canBindAndDraw(),
                renderEncoder && Metal4.canBindAndDraw(),
                computeEncoder,
                device.supportsArgumentBuffersTier2(),
                device.maxArgumentBufferSamplerCount(),
                // Asked of the device and not of the runtime's class table: these three are protocols, and
                // a protocol is not a class, so `objc_getClass("MTL4Compiler")` answers nothing on a system
                // where the factory works. Measured: all three answers were false by that question and true
                // by this one. What a capability record has to say is whether the object can be made.
                factory(device, "newResidencySetWithDescriptor:error:"),
                factory(device, "newTextureViewPoolWithDescriptor:error:"),
                factory(device, "newCompilerWithDescriptor:error:"),
                MetalFx.spatialSupported(device.handle()),
                MetalFx.metal4SpatialSupported(device.handle()),
                MetalShaderLanguageProbe.newestMetal3Profile(device)
        );
    }

    /**
     * Whether the device satisfies the minimum contract for the new command structure.
     * <p>
     * Every clause is a separate answer on purpose. The list is the specification's, and each entry has
     * been the difference between "the family is there" and "the path works" at least once in this tree.
     */
    public boolean metal4MinimumContract() {
        return this.metal4Family
                && this.metal4CommandQueue
                && this.metal4CommandAllocator
                && this.metal4CommandBuffer
                && this.metal4RenderEncoder
                && this.metal4ComputeEncoder
                && this.metal4ArgumentTable;
    }

    /** Whether the generation the engine has always run on is available, which is the fallback's own gate. */
    public boolean metal3MinimumContract() {
        return this.metal3Family;
    }

    /**
     * Whether choosing Metal 4 would cost the player a feature they have today.
     * <p>
     * The scaler is the one that matters: a device with the Metal 3 spatial scaler and no Metal 4 one that
     * still offered the render-scale setting would have to rebuild the whole backend when the player
     * moved the slider, so a path that cannot scale is not eligible while a path that can is.
     */
    public boolean metalFxParityForMetal4() {
        return !this.metalFxSpatial || this.metal4FxSpatial;
    }

    /** Whether the device answers to a factory, which is the question a protocol cannot be asked. */
    private static boolean factory(final MTLDevice device, final String selector) {
        return device.respondsTo(selector);
    }

    /** One line for the log, which is also what a bug report should quote. */
    public String summary() {
        return "metal3Family=" + this.metal3Family
                + " metal4Family=" + this.metal4Family
                + " queue=" + this.metal4CommandQueue
                + " allocator=" + this.metal4CommandAllocator
                + " buffer=" + this.metal4CommandBuffer
                + " argumentTable=" + this.metal4ArgumentTable
                + " render=" + this.metal4RenderEncoder
                + " compute=" + this.metal4ComputeEncoder
                + " residency=" + this.residencySets
                + " viewPools=" + this.textureViewPools
                + " compiler=" + this.metal4Compiler
                + " metalFx=" + this.metalFxSpatial
                + " metal4Fx=" + this.metal4FxSpatial
                + " msl=" + this.shaderLanguageProfile.token();
    }
}
