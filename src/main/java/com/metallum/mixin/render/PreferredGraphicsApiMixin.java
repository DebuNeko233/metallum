package com.metallum.mixin.render;

import com.metallum.api.MetallumApi;
import com.metallum.render.MetalBackend;
import com.mojang.blaze3d.systems.GpuBackend;
import net.minecraft.client.PreferredGraphicsApi;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(PreferredGraphicsApi.class)
abstract class PreferredGraphicsApiMixin {
    @Inject(method = "getBackendsToTry", at = @At("RETURN"), cancellable = true)
    private void metallum$preferMetalBackend(final CallbackInfoReturnable<GpuBackend[]> cir) {
        PreferredGraphicsApi self = (PreferredGraphicsApi) (Object) this;
        if (self != PreferredGraphicsApi.DEFAULT || !MetallumApi.isMetalPreferred()) {
            return;
        }

        GpuBackend[] vanillaBackends = cir.getReturnValue();
        GpuBackend[] preferredBackends = new GpuBackend[vanillaBackends.length + 1];
        preferredBackends[0] = new MetalBackend();
        System.arraycopy(vanillaBackends, 0, preferredBackends, 1, vanillaBackends.length);
        cir.setReturnValue(preferredBackends);
    }
}
