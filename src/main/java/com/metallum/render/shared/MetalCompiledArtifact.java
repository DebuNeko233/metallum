package com.metallum.render.shared;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * What the pipeline cache needs from a compiled artifact: the key it was compiled under.
 * <p>
 * The cache lives on the device and the artifact belongs to the generation that compiles it, so the question
 * "was this artifact translated for this session's MSL profile?" has to be answerable across that boundary. It
 * is the same shape as {@link MetalDeviceFacts} in the other direction: the device asks the artifact one
 * question, and the generation keeps everything else about it.
 */
@Environment(EnvType.CLIENT)
public interface MetalCompiledArtifact {

    /** The description this artifact was compiled for: shaders, profile, layout mode and rendering state. */
    MetalPipelineKey pipelineKey();
}
