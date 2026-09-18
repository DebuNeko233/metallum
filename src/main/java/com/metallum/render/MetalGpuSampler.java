package com.metallum.render;

import com.metallum.mtl.MTLCompareFunction;
import com.metallum.mtl.MTLSamplerAddressMode;
import com.metallum.mtl.MTLSamplerDescriptor;
import com.metallum.mtl.MTLSamplerMinMagFilter;
import com.metallum.mtl.MTLSamplerMipFilter;
import com.mojang.blaze3d.platform.CompareOp;
import com.mojang.blaze3d.textures.AddressMode;
import com.mojang.blaze3d.textures.FilterMode;
import com.mojang.blaze3d.textures.GpuSampler;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.NonNull;

import java.lang.foreign.MemorySegment;
import java.util.EnumMap;
import java.util.OptionalDouble;

@Environment(EnvType.CLIENT)
final class MetalGpuSampler extends GpuSampler {
    private final MetalDevice device;
    private final MemorySegment nativeHandle;
    private final AddressMode addressModeU;
    private final AddressMode addressModeV;
    private final FilterMode minFilter;
    private final FilterMode magFilter;
    private final int maxAnisotropy;
    private final OptionalDouble maxLod;
    private final EnumMap<CompareOp, MetalGpuSampler> comparisonVariants = new EnumMap<>(CompareOp.class);
    private boolean closed;

    MetalGpuSampler(
            final MetalDevice device,
            final AddressMode addressModeU,
            final AddressMode addressModeV,
            final FilterMode minFilter,
            final FilterMode magFilter,
            final int maxAnisotropy,
            final OptionalDouble maxLod
    ) {
        this(device, addressModeU, addressModeV, minFilter, magFilter, maxAnisotropy, maxLod, null);
    }

    private MetalGpuSampler(
            final MetalDevice device,
            final AddressMode addressModeU,
            final AddressMode addressModeV,
            final FilterMode minFilter,
            final FilterMode magFilter,
            final int maxAnisotropy,
            final OptionalDouble maxLod,
            final CompareOp comparison
    ) {
        this.device = device;
        try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {
            descriptor.minFilter(MTLSamplerMinMagFilter.from(minFilter));
            descriptor.magFilter(MTLSamplerMinMagFilter.from(magFilter));
            descriptor.mipFilter(toMtlMipFilter(maxLod));
            descriptor.sAddressMode(MTLSamplerAddressMode.from(addressModeU));
            descriptor.tAddressMode(MTLSamplerAddressMode.from(addressModeV));
            descriptor.rAddressMode(MTLSamplerAddressMode.from(addressModeV));
            if (comparison != null) {
                descriptor.compareFunction(MTLCompareFunction.from(comparison));
            }
            // A sampler can be rebound through Metal's direct argument table or an argument
            // buffer depending on which compiled pipeline consumes it. Apple requires samplers
            // referenced from argument buffers to be created with this flag; it defaults false.
            descriptor.supportArgumentBuffers(true);
            descriptor.maxAnisotropy(Math.max(1, maxAnisotropy));
            descriptor.lodMinClamp(0.0f);
            double lodMaxClamp = toMtlMaxLodClamp(maxLod);
            descriptor.lodMaxClamp(lodMaxClamp >= 0.0 && Double.isFinite(lodMaxClamp) ? (float) lodMaxClamp : Float.MAX_VALUE);
            this.nativeHandle = device.metalDevice().newSamplerState(descriptor);
        }
        this.addressModeU = addressModeU;
        this.addressModeV = addressModeV;
        this.minFilter = minFilter;
        this.magFilter = magFilter;
        this.maxAnisotropy = maxAnisotropy;
        this.maxLod = maxLod;
    }

    MetalGpuSampler comparisonVariant(final CompareOp compareOp) {
        if (this.closed) {
            throw new IllegalStateException("Cannot create a Metal comparison sampler from a closed sampler");
        }
        return this.comparisonVariants.computeIfAbsent(compareOp, op -> new MetalGpuSampler(
                this.device,
                this.addressModeU,
                this.addressModeV,
                this.minFilter,
                this.magFilter,
                this.maxAnisotropy,
                this.maxLod,
                op
        ));
    }

    MetalDevice device() {
        return this.device;
    }

    @Override
    public @NonNull AddressMode getAddressModeU() {
        return this.addressModeU;
    }

    @Override
    public @NonNull AddressMode getAddressModeV() {
        return this.addressModeV;
    }

    @Override
    public @NonNull FilterMode getMinFilter() {
        return this.minFilter;
    }

    @Override
    public @NonNull FilterMode getMagFilter() {
        return this.magFilter;
    }

    @Override
    public int getMaxAnisotropy() {
        return this.maxAnisotropy;
    }

    @Override
    public @NonNull OptionalDouble getMaxLod() {
        return this.maxLod;
    }

    @Override
    public void close() {
        if (this.closed) {
            return;
        }
        this.closed = true;
        for (MetalGpuSampler variant : this.comparisonVariants.values()) {
            variant.close();
        }
        this.comparisonVariants.clear();
        this.device.queueResourceRelease(this.nativeHandle);
    }

    boolean isClosed() {
        return this.closed;
    }

    MemorySegment nativeHandle() {
        return this.nativeHandle;
    }

    private static MTLSamplerMipFilter toMtlMipFilter(final OptionalDouble maxLod) {
        return maxLod.orElse(1000.0) > 0.25 ? MTLSamplerMipFilter.Linear : MTLSamplerMipFilter.Nearest;
    }

    private static double toMtlMaxLodClamp(final OptionalDouble maxLod) {
        return Math.max(0.25, maxLod.orElse(1000.0));
    }
}
