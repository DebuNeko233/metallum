package com.metallum.mtl.metal4;

import com.metallum.mtl.MTLDevice;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.util.HashMap;
import java.util.Map;

/**
 * The writable-texture housekeeping kernels this generation dispatches, and the pipelines they are built into.
 * <p>
 * The first job is the one a storage allocation asks for before anything reads it: writing a texture to zero. A
 * pack's storage image has no contents when it is made, and the client's own allocation says as much - it asks
 * the backend to clear it and refuses to use it if the backend cannot. That refusal is where Vitrail's
 * compute-storage fixture stopped on this path, one line before its first dispatch.
 * <p>
 * <strong>This is a copy of the Metal 3 kernels and not an import of them.</strong> The MSL is the same shape
 * because the work is the same - a kernel knows only Metal scalar type and texture dimensionality, and the two
 * generations compile the same text into their own pipeline objects - but {@code mtl.metal3} is not on this
 * generation's classpath, which is the same rule that keeps the two command models from reaching into each
 * other. What differs is the binding: a Metal 4 dispatch has no per-resource setter, so the image goes into an
 * {@link MTL4ArgumentTable} by its resource id, and the table is handed to the encoder before the dispatch.
 * <p>
 * <strong>The cache is the frame encoder's, not a process's.</strong> Pipelines are made per device, once each,
 * and released by whoever owns this object - rather than by a static map keyed on a device that could outlive its
 * owner, which is how the Metal 3 form of this class is written and what section 106 of the migration asks the
 * full-frame path not to repeat.
 */
@Environment(EnvType.CLIENT)
public final class MTL4StorageTexturePipelines {

    /** Which scalar type a texture's format holds, and therefore which kernel zeroes it. */
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

    private final MTLDevice device;
    private final Map<String, MemorySegment> pipelines = new HashMap<>();
    /** Whether a pipeline this device could not make has been reported, so a session says it once. */
    private boolean reported;

    public MTL4StorageTexturePipelines(final MTLDevice device) {
        this.device = device;
    }

    /**
     * Writes a texture to zero.
     * <p>
     * The image goes into the caller's table by resource id and the table goes to the encoder before the
     * dispatch, which is the whole difference from the Metal 3 form of this call. The table's contents are
     * snapshotted when the dispatch is encoded and not when the GPU runs it, so the same table may be re-pointed
     * at another image between two dispatches on one encoder - which is what a frame that clears several does.
     *
     * @return whether a dispatch was encoded, which is false rather than an exception where this device cannot
     *         make the kernel: the caller's contract is a boolean and its fallback is its own
     */
    public boolean clearZero(final MTL4ComputeEncoder encoder, final MTL4ArgumentTable table,
                             final MemorySegment texture, final ScalarKind scalarKind, final int dimensions,
                             final long width, final long height, final long depth) {
        if (encoder == null || table == null || ObjC.isNil(texture)
                || dimensions < 1 || dimensions > 3
                || width <= 0L || height <= 0L || depth <= 0L) {
            return false;
        }

        MemorySegment pipeline = zeroPipeline(scalarKind, dimensions);
        if (ObjC.isNil(pipeline)) {
            return false;
        }
        if (!encoder.setComputePipelineState(pipeline)) {
            return false;
        }
        if (!table.texture(texture, 0L) || !encoder.setArgumentTable(table)) {
            return false;
        }
        // The grid is the texture's extent and the threadgroup is what the Metal 3 kernels use for the same
        // dimensionality, so a 3D texture does not pay a 2D group's worth of empty threads.
        return switch (dimensions) {
            case 1 -> encoder.dispatchThreads(width, 1L, 1L, 64L, 1L, 1L);
            case 2 -> encoder.dispatchThreads(width, height, 1L, 8L, 8L, 1L);
            case 3 -> encoder.dispatchThreads(width, height, depth, 4L, 4L, 4L);
            default -> false;
        };
    }

    /** The zeroing kernel for one scalar type and dimensionality, made once per device. */
    private MemorySegment zeroPipeline(final ScalarKind scalarKind, final int dimensions) {
        String entry = "metallum_zero_" + dimensions + "d_" + scalarKind.entrySuffix;
        MemorySegment cached = this.pipelines.get(entry);
        if (cached != null) {
            return cached;
        }

        MemorySegment function = this.device.newFunction(ZERO_MSL, entry);
        MemorySegment pipeline = ObjC.isNil(function) ? MemorySegment.NULL
                : this.device.newComputePipelineState(function);
        ObjC.release(function);
        if (ObjC.isNil(pipeline)) {
            if (!this.reported) {
                this.reported = true;
                com.metallum.Metallum.LOGGER.warn("Metal 4 storage pipeline: the device made no compute pipeline"
                        + " for {} (dimensions {}), so a storage texture this frame cannot be zeroed through this"
                        + " path", scalarKind, dimensions);
            }
            return MemorySegment.NULL;
        }

        this.pipelines.put(entry, pipeline);
        return pipeline;
    }

    /** Releases every pipeline this object made. Called by the encoder that owns it. */
    public void close() {
        for (MemorySegment pipeline : this.pipelines.values()) {
            if (!ObjC.isNil(pipeline)) {
                ObjC.release(pipeline);
            }
        }
        this.pipelines.clear();
    }
}
