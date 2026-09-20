package com.metallum.mixin.sodium;

import net.caffeinemc.mods.sodium.client.render.chunk.UniformBufferManager;
import net.caffeinemc.mods.sodium.client.render.chunk.region.RenderRegionManager;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.Collection;
import java.util.concurrent.atomic.AtomicLong;

/**
 * A diagnostic, off unless {@code -Dmetallum.logSodiumTerrain=true}: how many chunk-build results Sodium hands to
 * its own upload step.
 * <p>
 * It exists because of one measurement and one question. The measurement: a forced Metal 4 no-pack session
 * presents one flat clear colour, the world's terrain pass is opened and ended empty every frame, and the
 * allocation that would mean a mesh arrived - `ArenaAggregator`'s arena buffer, made on the Metal 3 arm at 268 MB
 * and up as sections upload - never happens. The question that leaves: does Sodium's builder produce meshes that
 * the upload then loses, or does the builder produce nothing at all? The engine cannot see either side of that
 * boundary, and this line can: a count that never leaves zero puts the fault in the builder, and one that rises
 * puts it inside the upload.
 * <p>
 * It reads a collection's size and counts calls. It changes no behaviour, and with the property off it is one
 * field read per upload call.
 */
@Mixin(RenderRegionManager.class)
public class ChunkUploadMixin {

    private static final boolean LOG = Boolean.getBoolean("metallum.logSodiumTerrain");
    private static final AtomicLong CALLS = new AtomicLong();
    private static final AtomicLong CALLS_WITH_RESULTS = new AtomicLong();
    private static final AtomicLong RESULTS = new AtomicLong();
    private static final AtomicLong FRAMES = new AtomicLong();

    @Inject(
            method = "uploadResults(Ljava/util/Collection;Lnet/caffeinemc/mods/sodium/client/render/chunk/UniformBufferManager;)V",
            at = @At("HEAD"),
            remap = false
    )
    private void metallum$countUploadResults(final Collection<?> results, final UniformBufferManager uniforms,
                                             final CallbackInfo ci) {
        if (!LOG) {
            return;
        }

        long call = CALLS.incrementAndGet();
        int size = results == null ? -1 : results.size();
        boolean carrying = size > 0;
        if (carrying) {
            CALLS_WITH_RESULTS.incrementAndGet();
            RESULTS.addAndGet(size);
        }
        long frame = FRAMES.incrementAndGet();
        // The first call, every call that carries anything, and then one in six hundred: an upload step that is
        // never reached and one that is reached empty have to read differently, and a periodic line alone cannot
        // tell them apart when the call is rare.
        if (call == 1L || carrying || frame % 600L == 0L) {
            com.metallum.Metallum.LOGGER.info("Sodium terrain upload: call {}, {} frames seen, {} of those calls"
                            + " carried results, {} results in total, this one {}",
                    call, frame, CALLS_WITH_RESULTS.get(), RESULTS.get(), size);
        }
    }
}
