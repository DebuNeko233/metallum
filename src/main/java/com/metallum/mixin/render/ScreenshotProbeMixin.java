package com.metallum.mixin.render;

import com.metallum.render.shared.ClientScreenshotRequest;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Answers a client-screenshot request once a second, off unless a launch asked for it.
 * <p>
 * The reading is the client's own framebuffer rather than a photograph of the display, which is what section 47
 * of the long-term plan asks for and what the harness's picture column needs: a display capture is of whatever
 * window is in front, and a locked screen captures as one flat colour - measured, twice, once as two pictures of
 * nothing compared and once as four arms that photographed the browser. What is read here is the frame the
 * counters beside it describe.
 * <p>
 * <strong>Once a second from the client's own tick, and not once a frame.</strong> The question is a file in the
 * instance's directory and a second sits far inside the window a measurement counts, so the cadence costs one
 * {@code stat} a second where a per-frame check would pay one on every frame of every session that has this on.
 * The work itself is a public client call, {@code Screenshot.takeScreenshot}, which is the same readback the
 * game's F2 key uses.
 * <p>
 * With {@code -Dmetallum.clientScreenshot} unset this is one field read per client tick, and the tick counter
 * below is the only state it keeps.
 */
@Mixin(Minecraft.class)
public class ScreenshotProbeMixin {

    /** How many ticks between two questions, which is one second at the client's own twenty ticks. */
    private static final int EVERY_TICKS = 20;

    private long metallum$ticks;

    @Inject(method = "tick()V", at = @At("HEAD"))
    private void metallum$answerScreenshotRequests(final CallbackInfo ci) {
        if (!ClientScreenshotRequest.enabled()) {
            return;
        }

        if (++this.metallum$ticks % EVERY_TICKS != 0) {
            return;
        }

        // The instance is the mixin's own target rather than Minecraft.getInstance(), so a tick that arrives
        // before the static is set cannot dereference null here - the same reason the lifecycle probe beside this
        // one takes its instance that way.
        ClientScreenshotRequest.takeIfAsked((Minecraft) (Object) this);
    }
}
