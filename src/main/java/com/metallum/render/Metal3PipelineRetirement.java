package com.metallum.render;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.util.ArrayList;
import java.util.List;

/**
 * The pipelines a Metal 3 session has stopped using but cannot release yet.
 * <p>
 * A compiled pipeline's native objects have to outlive the cache entry that named them, because work already
 * recorded against them may still be in flight. This holds those objects until the caller that knows about
 * submission says the GPU has caught up, and it is deliberately narrow: it does not compile, does not choose a
 * profile, does not own the active pipeline cache, and **must not wait for anything** - it cannot know how
 * frames are submitted, and a retirement owner that waits is a retirement owner that has taken over the
 * execution lifecycle.
 */
@Environment(EnvType.CLIENT)
final class Metal3PipelineRetirement {

    private final List<MetalCompiledRenderPipeline> retired = new ArrayList<>();

    /** Takes ownership of a pipeline that is no longer in the active cache. */
    void retire(final MetalCompiledRenderPipeline pipeline) {
        this.retired.add(pipeline);
    }

    /** Releases everything retired so far. Called only after the caller has established GPU completion. */
    void releaseRetired() {
        this.retired.forEach(MetalCompiledRenderPipeline::close);
        this.retired.clear();
    }
}
