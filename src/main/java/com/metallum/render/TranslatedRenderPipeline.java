package com.metallum.render;

import com.metallum.render.shared.MetalResourceBinding;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.util.List;
import java.util.Set;

/**
 * What translating one render pipeline produced: MSL for both stages, the entry points, the bindings the two
 * stages read, whether the pipeline is carried by argument buffers, and which sets each stage's argument buffers
 * live in.
 * <p>
 * It exists to separate two responsibilities that were one method: turning SPIR-V into MSL with its resource
 * metadata is translation and knows nothing about Metal 3's objects, while building a
 * {@code MetalCompiledRenderPipeline} from that result is Metal 3's compilation. The record is the whole of what
 * crosses between them, so a field left behind would be a compile error rather than a silently missing binding.
 */
@Environment(EnvType.CLIENT)
record TranslatedRenderPipeline(
        String vertexMsl,
        String fragmentMsl,
        String vertexEntryPoint,
        String fragmentEntryPoint,
        List<MetalResourceBinding> resources,
        boolean usesArgumentBuffers,
        Set<Integer> vertexArgumentBufferSets,
        Set<Integer> fragmentArgumentBufferSets
) {
}
