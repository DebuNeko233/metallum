package com.metallum.render.shared;

import com.metallum.render.MetalDevice;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.nio.ByteBuffer;

/**
 * Compiling a compute pipeline, asked of whatever execution state is active.
 * <p>
 * It lives in the shared layer and takes the neutral {@code MetalDevice} facade - the same kind of reference the
 * shared layer already carries - because compilation is a question a caller asks the execution state, not a
 * class it may name. The answer is opaque: a handle to dispatch with, not a compiled artifact anybody inspects.
 */
@Environment(EnvType.CLIENT)
public interface MetalComputeCompiler {

    /** Compiles a compute pipeline from SPIR-V, answering an opaque resource to dispatch with. */
    Object compileCompute(MetalDevice device, String label, ByteBuffer spirv);
}
