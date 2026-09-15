package com.metallum.render;

import com.mojang.blaze3d.platform.CompareOp;
import com.mojang.blaze3d.textures.GpuSampler;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Optional-backend seam for sampler comparison state that Minecraft 26.2's public
 * {@link GpuSampler} description cannot express.
 * <p>
 * The caller owns the meaning of the comparison and supplies both the ordinary sampler whose
 * filtering/addressing/LOD state must be preserved and the generic comparison operation. Metallum
 * only clones that sampler into a native Metal sampler state with {@code compareFunction} enabled.
 * No shader-pack names, shadow-buffer policy, or directive interpretation live here.
 */
@Environment(EnvType.CLIENT)
public final class MetalSamplerBridge {
    private MetalSamplerBridge() {
    }

    public static GpuSampler comparisonSampler(
            final Object backend,
            final GpuSampler template,
            final CompareOp compareOp
    ) {
        if (!(backend instanceof MetalDevice device)) {
            throw new IllegalArgumentException("Not a Metallum MetalDevice backend: " + backend);
        }
        if (!(template instanceof MetalGpuSampler sampler) || sampler.isClosed()) {
            throw new IllegalArgumentException("Comparison sampler template is not a live Metal sampler");
        }
        if (sampler.device() != device) {
            throw new IllegalArgumentException("Comparison sampler template belongs to another Metal device");
        }
        return sampler.comparisonVariant(compareOp);
    }
}
