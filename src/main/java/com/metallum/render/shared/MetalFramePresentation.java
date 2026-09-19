package com.metallum.render.shared;

import com.metallum.mtl.CAMetalLayer;
import com.mojang.blaze3d.textures.GpuTextureView;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.NonNull;

/**
 * What a surface needs from the frame to put a picture on screen: take it, and hand the finished frame over.
 * <p>
 * The surface is handed whatever backend the frame is being encoded through and has to ask it to present, so
 * naming the encoder's class there made the windowing code a place a generation leaks into. The two members
 * are the whole of what it uses, read off the call site: the take, and the submit (which is the game's own
 * {@code CommandEncoderBackend} contract and is repeated here only so that the surface can hold one type).
 * <p>
 * It is deliberately not {@link MetalFrameExtras}: an encoder that can scale is not the same thing as one
 * that can be presented through, and a caller should be able to say which it needs.
 */
@Environment(EnvType.CLIENT)
public interface MetalFramePresentation {

    /** Records the picture into the layer's next drawable, to be presented by {@link #submit()}. */
    void presentTextureToDrawable(final @NonNull CAMetalLayer layer, final @NonNull GpuTextureView textureView);

    /** Submits what was recorded. */
    void submit();
}
