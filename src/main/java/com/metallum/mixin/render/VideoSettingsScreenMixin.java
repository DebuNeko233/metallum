package com.metallum.mixin.render;

import com.metallum.config.MetallumGraphicsOptions;
import net.minecraft.client.OptionInstance;
import net.minecraft.client.Options;
import net.minecraft.client.gui.screens.options.VideoSettingsScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(VideoSettingsScreen.class)
abstract class VideoSettingsScreenMixin {
    @Inject(method = "displayOptions", at = @At("RETURN"), cancellable = true)
    private static void metallum$replaceGraphicsApiOption(
            Options options,
            CallbackInfoReturnable<OptionInstance<?>[]> cir
    ) {
        OptionInstance<?>[] original = cir.getReturnValue();
        OptionInstance<?> vanillaGraphicsApi = options.preferredGraphicsBackend();
        OptionInstance<?>[] replacement = original.clone();

        for (int i = 0; i < replacement.length; i++) {
            if (replacement[i] == vanillaGraphicsApi) {
                replacement[i] = MetallumGraphicsOptions.createVanillaOption(options);
                cir.setReturnValue(replacement);
                return;
            }
        }
    }
}
