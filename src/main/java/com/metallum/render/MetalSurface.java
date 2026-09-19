package com.metallum.render;

import com.metallum.mtl.CAMetalLayer;
import com.mojang.blaze3d.systems.CommandEncoderBackend;
import com.mojang.blaze3d.systems.GpuSurface;
import com.mojang.blaze3d.systems.GpuSurfaceBackend;
import com.mojang.blaze3d.systems.SurfaceException;
import com.mojang.blaze3d.textures.GpuTextureView;
import com.metallum.render.shared.MetalFramePresentation;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.NonNull;

import java.util.Collection;
import java.util.EnumSet;
import java.util.Set;

@Environment(EnvType.CLIENT)
final class MetalSurface implements GpuSurfaceBackend {
    private static final Set<GpuSurface.PresentMode> SUPPORTED_PRESENT_MODES = EnumSet.of(GpuSurface.PresentMode.FIFO, GpuSurface.PresentMode.MAILBOX);
    private final MetalDevice device;
    private final CAMetalLayer metalLayer;
    /** The present mode is a property of the session and is said once, at the first configure. */
    private static boolean presentModeSaid;
    private GpuSurface.Configuration configuration;
    private MetalFramePresentation pendingPresentEncoder;

    MetalSurface(final MetalDevice device, final CAMetalLayer metalLayer) {
        this.device = device;
        this.metalLayer = metalLayer;
    }

    @Override
    public void configure(final GpuSurface.Configuration config) throws SurfaceException {
        if (config.width() <= 0 || config.height() <= 0) {
            throw new SurfaceException("Metal surface configuration must be positive, got " + config.width() + "x" + config.height());
        }

        // The one place the present mode becomes a layer property, so the one place that can say what the
        // session's frame pacing is: `immediatePresentMode` is the equality the layer is handed, and the layer
        // sets `displaySyncEnabled` to its negation. An Unlimited-FPS session that is display-locked is the
        // question this line answers, and it cannot be answered after the fact - the marker that arms the probe
        // does not exist yet at this point in a launch.
        final boolean immediatePresentMode = config.presentMode() == GpuSurface.PresentMode.MAILBOX;
        this.metalLayer.configure(config.width(), config.height(), immediatePresentMode);
        if (!presentModeSaid) {
            presentModeSaid = true;
            com.metallum.Metallum.LOGGER.info(
                    "Metal surface: presentMode={} immediatePresentMode={} displaySyncEnabled={}",
                    config.presentMode(), immediatePresentMode, !immediatePresentMode);
        }

        this.configuration = config;
    }

    @Override
    public boolean isSuboptimal() {
        return false;
    }

    @Override
    public void acquireNextTexture() {
    }

    @Override
    public void blitFromTexture(final @NonNull CommandEncoderBackend commandEncoder, final @NonNull GpuTextureView textureView) {
        if (!(commandEncoder instanceof MetalFramePresentation presentation)) {
            throw new IllegalArgumentException(
                    "the surface was handed a " + commandEncoder.getClass().getName()
                            + ", which cannot be presented through; it asks for "
                            + MetalFramePresentation.class.getSimpleName() + " rather than for a class"
            );
        }

        presentation.presentTextureToDrawable(metalLayer, textureView);
        this.pendingPresentEncoder = presentation;
    }

    @Override
    public void present() {
        pendingPresentEncoder.submit();
    }

    @Override
    public void close() {
    }

    @Override
    public @NonNull Collection<GpuSurface.PresentMode> supportedPresentModes() {
        return SUPPORTED_PRESENT_MODES;
    }
}
