package com.metallum.mtl;

import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.util.HashMap;
import java.util.Map;
import com.metallum.mtl.metal3.MTLComputeCommandEncoder;

/**
 * Backend-only compute kernels used for writable texture housekeeping.
 * <p>
 * The kernels know only Metal scalar type and texture dimensionality. Shader-pack decisions such
 * as which image is cleared each frame or when a volume is reanchored remain outside this class.
 */
@Environment(EnvType.CLIENT)
public final class MTLStorageTexturePipelines {
    public enum ScalarKind {
        FLOAT("float"),
        SINT("int"),
        UINT("uint");

        private final String entrySuffix;

        ScalarKind(final String entrySuffix) {
            this.entrySuffix = entrySuffix;
        }
    }

    private static final String ZERO_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            kernel void metallum_zero_1d_float(
              texture1d<float, access::write> image [[texture(0)]],
              uint x [[thread_position_in_grid]]) {
              image.write(float4(0.0), x);
            }

            kernel void metallum_zero_2d_float(
              texture2d<float, access::write> image [[texture(0)]],
              uint2 xy [[thread_position_in_grid]]) {
              image.write(float4(0.0), xy);
            }

            kernel void metallum_zero_3d_float(
              texture3d<float, access::write> image [[texture(0)]],
              uint3 xyz [[thread_position_in_grid]]) {
              image.write(float4(0.0), xyz);
            }

            kernel void metallum_zero_1d_int(
              texture1d<int, access::write> image [[texture(0)]],
              uint x [[thread_position_in_grid]]) {
              image.write(int4(0), x);
            }

            kernel void metallum_zero_2d_int(
              texture2d<int, access::write> image [[texture(0)]],
              uint2 xy [[thread_position_in_grid]]) {
              image.write(int4(0), xy);
            }

            kernel void metallum_zero_3d_int(
              texture3d<int, access::write> image [[texture(0)]],
              uint3 xyz [[thread_position_in_grid]]) {
              image.write(int4(0), xyz);
            }

            kernel void metallum_zero_1d_uint(
              texture1d<uint, access::write> image [[texture(0)]],
              uint x [[thread_position_in_grid]]) {
              image.write(uint4(0), x);
            }

            kernel void metallum_zero_2d_uint(
              texture2d<uint, access::write> image [[texture(0)]],
              uint2 xy [[thread_position_in_grid]]) {
              image.write(uint4(0), xy);
            }

            kernel void metallum_zero_3d_uint(
              texture3d<uint, access::write> image [[texture(0)]],
              uint3 xyz [[thread_position_in_grid]]) {
              image.write(uint4(0), xyz);
            }
            """;

    private static final Map<String, MemorySegment> ZERO_PIPELINES = new HashMap<>();
    private static MTLDevice owner;

    private MTLStorageTexturePipelines() {
    }

    public static void clearZero(
            final MTLDevice device,
            final MTLComputeCommandEncoder encoder,
            final MemorySegment texture,
            final ScalarKind scalarKind,
            final int dimensions,
            final long width,
            final long height,
            final long depth
    ) {
        if (dimensions < 1 || dimensions > 3) {
            throw new IllegalArgumentException("Storage texture dimensions must be 1, 2, or 3, got " + dimensions);
        }
        if (width <= 0L || height <= 0L || depth <= 0L) {
            throw new IllegalArgumentException("Storage texture extent must be positive");
        }

        MemorySegment pipeline = zeroPipeline(device, scalarKind, dimensions);
        encoder.setComputePipelineState(pipeline);
        encoder.setTexture(texture, 0L);
        switch (dimensions) {
            case 1 -> encoder.dispatchThreads(width, 1L, 1L, 64L, 1L, 1L);
            case 2 -> encoder.dispatchThreads(width, height, 1L, 8L, 8L, 1L);
            case 3 -> encoder.dispatchThreads(width, height, depth, 4L, 4L, 4L);
            default -> throw new IllegalStateException("Unexpected texture dimensionality " + dimensions);
        }
    }

    public static void close() {
        ZERO_PIPELINES.values().forEach(ObjC::release);
        ZERO_PIPELINES.clear();
        owner = null;
    }

    private static MemorySegment zeroPipeline(
            final MTLDevice device,
            final ScalarKind scalarKind,
            final int dimensions
    ) {
        if (owner != null && owner.handle().address() != device.handle().address()) {
            close();
        }
        owner = device;

        String entry = "metallum_zero_" + dimensions + "d_" + scalarKind.entrySuffix;
        MemorySegment cached = ZERO_PIPELINES.get(entry);
        if (cached != null) {
            return cached;
        }

        MemorySegment function = device.newFunction(ZERO_MSL, entry);
        if (ObjC.isNil(function)) {
            throw new IllegalStateException("Failed to compile Metal storage-texture zero kernel " + entry);
        }

        MemorySegment pipeline;
        try {
            pipeline = device.newComputePipelineState(function);
        } finally {
            ObjC.release(function);
        }
        if (ObjC.isNil(pipeline)) {
            throw new IllegalStateException("Failed to create Metal storage-texture zero pipeline " + entry);
        }

        ZERO_PIPELINES.put(entry, pipeline);
        return pipeline;
    }
}
