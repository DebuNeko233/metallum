package com.metallum.mixin.render;

import com.metallum.render.shared.MetalFrameProbe;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Counts the client's ticks so a frame-probe window can say how many of them it covered.
 * <p>
 * <strong>Why a probe needs the client's clock.</strong> A window is a fixed *frame* count, and this client's
 * frame is not the same work every frame: measured on the no-pack scene, a frame is 7 render passes in the
 * steady state and 13 on the frame that coincides with a client tick, so a window's content is
 * {@code a*frames + b*ticks}. Two arms whose frame rates differ therefore put different numbers of tick frames
 * into the same 600-frame window, which is what `run/drift-nopack` shows: the reference's three arms read
 * `depthAttachments 1800` exactly because its frame rate is constant, while this path's differed by 9% and the
 * content guard named it as scene drift. The tick count is the fact that separates "these arms sampled different
 * slices of the client's life" from "these arms drew different worlds".
 * <p>
 * With no probe armed this is one field read per client tick, and the probe's own entry point returns before
 * doing anything.
 */
@Mixin(Minecraft.class)
public class ClientTickProbeMixin {

    @Inject(method = "tick()V", at = @At("HEAD"))
    private void metallum$countClientTick(final CallbackInfo ci) {
        MetalFrameProbe.gameTick();
    }
}
