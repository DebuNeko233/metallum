package com.metallum.render.shared;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * A compiled compute pipeline as its owner sees it: something that can be dispatched with and released.
 * <p>
 * The handle stays opaque - the flat bridge that closes one never learns which generation compiled it - and it
 * extends {@link AutoCloseable} so release is the same shape a caller would expect of any resource.
 */
@Environment(EnvType.CLIENT)
public interface MetalComputePipelineResource extends AutoCloseable {

    @Override
    void close();
}
