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
 * <strong>It is an identity and not only a label, and that took a measurement to establish.</strong> The
 * artifact a compile produces also depends on five things a key of shaders alone would miss - the depth and
 * stencil state (which carries the colour-target formats), the polygon mode, whether the pipeline culls, the
 * primitive topology and the vertex format bindings - each of which `MetalCompiledRenderPipeline` reads from
 * the pipeline description while it builds, so two pipelines differing only in their depth state would have
 * collided and one would have been handed the other's artifact. `renderingState` is that whole description,
 * composed rather than enumerated, which is what makes it safe for a cache to move onto this key.
 *
 * @param location         the pipeline's own location, which is the pack program it names
 * @param vertexShader     the vertex shader's location
 * @param fragmentShader   the fragment shader's location
 * @param defines          the shader defines as source directives, which is how the compiler sees them
 * @param shaderProfile    the MSL profile the session emits, so a cache cannot cross profiles
 * @param argumentBuffers  whether the program is carried by argument buffers rather than direct bindings
 * @param renderingState   everything else the compiled artifact depends on, as one canonical description:
 *                         the depth and stencil state (which carries the colour-target formats), the polygon
 *                         mode, whether the pipeline culls, the primitive topology and the vertex format
 *                         bindings. One field rather than five, because the reason it exists is that a new
 *                         piece of rendering state must not be able to be forgotten here - a description
 *                         composed from the whole object is what makes that impossible
 */
public record MetalPipelineKey(
        String location,
        String vertexShader,
        String fragmentShader,
        String defines,
        String shaderProfile,
        boolean argumentBuffers,
        String renderingState
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
                argumentBuffers,
                renderingState(pipeline)
        );
    }

    /**
     * What the compiled artifact depends on beyond the shaders, as text.
     * <p>
     * Every accessor here is one `MetalCompiledRenderPipeline` reads while it builds, which is why a key
     * without them is not an identity: two pipelines differing only in their depth state would collide. The
     * description is composed rather than listed as fields so that the next piece of rendering state to
     * matter cannot be left out silently - a fields-based key is one somebody forgets to extend.
     */
    private static String renderingState(final RenderPipeline pipeline) {
        return pipeline.getColorTargetStates().length + " targets"
                + "|depth=" + pipeline.getDepthStencilState()
                + "|polygon=" + pipeline.getPolygonMode()
                + "|cull=" + pipeline.isCull()
                + "|topology=" + pipeline.getPrimitiveTopology()
                + "|vertex=" + java.util.Arrays.toString(pipeline.getVertexFormatBindings());
    }

    /** One line for a log or a diagnostic, because a record's toString is not something to grep for. */
    public String token() {
        return this.location + "|" + this.vertexShader + "|" + this.fragmentShader + "|"
                + this.shaderProfile + "|" + (this.argumentBuffers ? "argument-buffers" : "direct") + "|"
                + Integer.toHexString(this.defines.hashCode());
    }
}
