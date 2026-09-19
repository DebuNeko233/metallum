package com.metallum.render;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLDepthStencilDescriptor;
import com.metallum.mtl.MTLCompareFunction;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.util.HashMap;
import java.util.Map;

/**
 * The compilation state the Metal 3 frame path owns: what it has already made, and how to make more.
 * <p>
 * The device used to own this - caches of depth-stencil states, shader modules, functions and compiled pipelines,
 * with the factories beside them - which made the device a registry of one generation's artifacts. That is the
 * blocker the frame path's move kept hitting: every attempt to move the encoder needed those members, and
 * widening them one at a time is what the first failures did. The state belongs to the generation, so it lives
 * here, and the device asks this object the way the frame path does.
 * <p>
 * It is being filled in one cache at a time rather than in one rewrite, so that each step is a build and a
 * contract run away from a working tree. What is here now is the depth-stencil cache and its factory; the shader
 * module, function and compiled-pipeline caches follow, with their profile guard, and this class stays the single
 * place a Metal 3 compile artifact is keyed.
 */
@Environment(EnvType.CLIENT)
final class Metal3CompilationContext {

    private final MTLDevice device;
    private final Map<Long, MemorySegment> depthStencilStates = new HashMap<>();

    Metal3CompilationContext(final MTLDevice device) {
        this.device = device;
    }

    /** A depth-stencil state for the comparison and write flags, made once and kept. */
    synchronized MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
        long key = (compareFunction.value << 1) | (writeDepth ? 1L : 0L);
        MemorySegment cached = this.depthStencilStates.get(key);
        if (cached != null) {
            return cached;
        }

        try (MTLDepthStencilDescriptor descriptor = MTLDepthStencilDescriptor.create()) {
            descriptor.depthCompareFunction(compareFunction);
            descriptor.depthWriteEnabled(writeDepth);
            MemorySegment state = this.device.newDepthStencilState(descriptor);
            this.depthStencilStates.put(key, state);
            return state;
        }
    }

    /** Releases every state this context made. Called once, by the device that opened it. */
    synchronized void close() {
        for (MemorySegment state : this.depthStencilStates.values()) {
            com.metallum.objc.ObjC.release(state);
        }

        this.depthStencilStates.clear();
    }
}
