package com.metallum.render.shared;

import com.mojang.blaze3d.pipeline.RenderPipeline;

/**
 * What a compiled pipeline <em>is</em>, in the terms two command generations can both look up.
 * <p>
 * The engine caches compiled pipelines by the game's own pipeline object today, which is an identity and not
 * a description: it answers "have I compiled this object before" and cannot answer "is the pipeline I am
 * about to compile the same work as one I already have". A key that names the work is what a cache spanning
 * two generations needs, and it is also what keeps a Metal 3 artifact from being handed to a Metal 4 session
 * - the shader profile is part of the identity for that reason and not for tidiness.
 * <p>
 * Everything here is read from the game's own pipeline description plus the two facts the compiler adds: the
 * MSL profile the session will emit, and whether the program is carried by argument buffers. Nothing is
 * inferred from the object's identity or from a counter.
 * <p>
 * <strong>This is not yet a sufficient cache identity, and the difference was measured rather than guessed.</strong>
 * The artifact a compile produces also depends on five things this key does not name - the depth and stencil
 * state (including its colour-target formats), the polygon mode, whether the pipeline culls, the primitive
 * topology and the vertex format bindings - each of which `MetalCompiledRenderPipeline` reads from the
 * pipeline description while it builds. Two pipelines that differ only in their depth state would collide
 * under this key and one of them would be handed the other's artifact. The key is what a diagnostic and the
 * cross-generation isolation need today; making it the cache's identity means adding those five, and that is
 * the step the task file names.
 *
 * @param location         the pipeline's own location, which is the pack program it names
 * @param vertexShader     the vertex shader's location
 * @param fragmentShader   the fragment shader's location
 * @param defines          the shader defines as source directives, which is how the compiler sees them
 * @param shaderProfile    the MSL profile the session emits, so a cache cannot cross profiles
 * @param argumentBuffers  whether the program is carried by argument buffers rather than direct bindings
 */
public record MetalPipelineKey(
        String location,
        String vertexShader,
        String fragmentShader,
        String defines,
        String shaderProfile,
        boolean argumentBuffers
) {

    /** The key for one pipeline as this session would compile it. */
    public static MetalPipelineKey of(final RenderPipeline pipeline, final String shaderProfile,
                                      final boolean argumentBuffers) {
        return new MetalPipelineKey(
                pipeline.getLocation().toString(),
                pipeline.getVertexShader().toString(),
                pipeline.getFragmentShader().toString(),
                pipeline.getShaderDefines().asSourceDirectives(),
                shaderProfile,
                argumentBuffers
        );
    }

    /** One line for a log or a diagnostic, because a record's toString is not something to grep for. */
    public String token() {
        return this.location + "|" + this.vertexShader + "|" + this.fragmentShader + "|"
                + this.shaderProfile + "|" + (this.argumentBuffers ? "argument-buffers" : "direct") + "|"
                + Integer.toHexString(this.defines.hashCode());
    }
}
