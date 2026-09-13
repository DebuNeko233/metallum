package com.metallum.render;

import com.metallum.mtl.*;
import com.metallum.objc.Cocoa;
import com.metallum.objc.ObjC;
import com.mojang.blaze3d.GpuFormat;
import com.mojang.blaze3d.buffers.GpuBuffer;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.preprocessor.GlslPreprocessor;
import com.mojang.blaze3d.shaders.GpuDebugOptions;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.systems.*;
import com.mojang.blaze3d.textures.*;
import com.mojang.blaze3d.vulkan.glsl.GlslCompiler;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.minecraft.client.renderer.ShaderDefines;
import net.minecraft.resources.Identifier;
import org.jspecify.annotations.NonNull;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.MemorySegment;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.function.Predicate;
import java.util.function.Supplier;
import java.util.regex.Pattern;

@Environment(EnvType.CLIENT)
final class MetalDevice implements GpuDeviceBackend {
    private static final Pattern BLOCK_COMMENTS = Pattern.compile("(?s)/\\*.*?\\*/");
    private static final Pattern LINE_COMMENTS = Pattern.compile("(?m)//[^\\n]*");
    private final MemorySegment metalDeviceHandle;
    private final MTLDevice metalDevice;
    private final CAMetalLayer metalLayer;
    private final Cocoa cocoa;
    private final GpuDebugOptions debugOptions;
    private final MetalCommandEncoder commandEncoder;
    private final DeviceInfo deviceInfo;
    public final MTLCommandQueue commandQueue;
    private final Map<RenderPipeline, MetalCompiledRenderPipeline> compiledPipelines = new IdentityHashMap<>();
    private final List<MetalCompiledRenderPipeline> deferredPipelineReleases = new ArrayList<>();
    private final Map<ShaderCompilationKey, IntermediaryShaderModule> shaderCache = new HashMap<>();
    private final Map<MslFunctionKey, MemorySegment> functionCache = new HashMap<>();
    private final Map<Long, MemorySegment> depthStencilStates = new HashMap<>();
    private final ShaderSource defaultShaderSource;

    MetalDevice(
            final ShaderSource defaultShaderSource,
            final GpuDebugOptions debugOptions,
            final MemorySegment metalDeviceHandle,
            final CAMetalLayer metalLayer,
            final String deviceName,
            final Cocoa cocoa
    ) {
        this.defaultShaderSource = defaultShaderSource;
        this.debugOptions = debugOptions;
        this.metalDeviceHandle = metalDeviceHandle;
        this.metalDevice = new MTLDevice(metalDeviceHandle);
        this.metalLayer = metalLayer;
        this.cocoa = cocoa;
        MTLCommandQueue.setDebugLabelsEnabled(this.useLabels());
        this.commandQueue = this.metalDevice.newCommandQueue();
        MTLBuiltinPipelines.init(this.metalDevice);
        this.commandEncoder = new MetalCommandEncoder(this);
        this.deviceInfo = buildDeviceInfo(deviceName);
    }

    @Override
    public @NonNull GpuSurfaceBackend createSurface(final long windowHandle) {
        return new MetalSurface(this, this.metalLayer);
    }

    @Override
    public @NonNull MetalCommandEncoder createCommandEncoder() {
        return this.commandEncoder;
    }

    @Override
    public @NonNull GpuSampler createSampler(
            final @NonNull AddressMode addressModeU,
            final @NonNull AddressMode addressModeV,
            final @NonNull FilterMode minFilter,
            final @NonNull FilterMode magFilter,
            final int maxAnisotropy,
            final @NonNull OptionalDouble maxLod
    ) {
        return new MetalGpuSampler(this, addressModeU, addressModeV, minFilter, magFilter, maxAnisotropy, maxLod);
    }

    @Override
    public @NonNull GpuTexture createTexture(
            @Nullable final Supplier<String> label,
            @GpuTexture.Usage final int usage,
            final @NonNull GpuFormat format,
            final int width,
            final int height,
            final int depthOrLayers,
            final int mipLevels
    ) {
        return this.createTexture(this.resolveDebugLabel(label), usage, format, width, height, depthOrLayers, mipLevels);
    }

    @Override
    public @NonNull GpuTexture createTexture(
            @Nullable final String label,
            @GpuTexture.Usage final int usage,
            final @NonNull GpuFormat format,
            final int width,
            final int height,
            final int depthOrLayers,
            final int mipLevels
    ) {
        return new MetalGpuTexture(this, usage, label == null ? "" : label, format, width, height, depthOrLayers, mipLevels);
    }

    @Override
    public @NonNull GpuTextureView createTextureView(final @NonNull GpuTexture texture) {
        return this.createTextureView(texture, 0, texture.getMipLevels());
    }

    @Override
    public @NonNull GpuTextureView createTextureView(final @NonNull GpuTexture texture, final int baseMipLevel, final int mipLevels) {
        return new MetalGpuTextureView(texture, baseMipLevel, mipLevels);
    }

    @Override
    public @NonNull GpuBuffer createBuffer(@Nullable final Supplier<String> label, @GpuBuffer.Usage final int usage, final long size) {
        return new MetalGpuBuffer(this, usage, size);
    }

    @Override
    public @NonNull GpuBuffer createBuffer(@Nullable final Supplier<String> label, @GpuBuffer.Usage final int usage, final ByteBuffer data) {
        MetalGpuBuffer buffer = (MetalGpuBuffer) this.createBuffer(label, usage | GpuBuffer.USAGE_COPY_DST, data.remaining());
        if (buffer.isCpuAccessible()) {
            buffer.writeDirect(0L, data);
        } else {
            this.commandEncoder.writeToBuffer(buffer.slice(), data.duplicate());
        }
        return buffer;
    }

    /**
     * Creates a shader-storage buffer for optional backend integrations.
     * <p>
     * Minecraft 26.2 exposes no storage-buffer usage bit on {@link GpuBuffer}. Metal does not need
     * such a usage declaration for {@code MTLBuffer}, so this backend extension allocates a shared
     * buffer directly and zeros it before returning it. The result is intentionally typed as
     * {@link Object}: callers that bridge optional backends can keep Metallum off their compile
     * classpath and hand the opaque object back to this backend for binding and release.
     */
    public Object createStorageBufferResource(final long size) {
        if (size <= 0L) {
            throw new IllegalArgumentException("Storage buffer size must be positive, got " + size);
        }
        MetalGpuBuffer buffer = new MetalGpuBuffer(this, GpuBuffer.USAGE_MAP_WRITE, size);
        buffer.zeroContents();
        return buffer;
    }

    /** Releases a resource returned by {@link #createStorageBufferResource(long)}. */
    public void closeStorageBufferResource(final Object resource) {
        if (!(resource instanceof MetalGpuBuffer buffer)) {
            throw new IllegalArgumentException("Not a Metal storage buffer resource: " + resource);
        }
        buffer.close();
    }

    /**
     * Allocates a shader-readable and shader-writable one-, two-, or three-dimensional texture.
     * <p>
     * Minecraft 26.2's public {@link GpuTexture} usage mask has no storage-image bit and its normal
     * {@code depthOrLayers} path describes array layers rather than a true Metal 3D texture. This
     * backend extension keeps the returned object inside the normal Minecraft texture facade while
     * selecting the correct Metal texture type and {@link MTLTextureUsage#ShaderWrite} internally.
     * No shader-pack naming or clear/reprojection policy is implemented here.
     */
    public GpuTexture createStorageTextureResource(
            @Nullable final String label,
            final GpuFormat format,
            final int width,
            final int height,
            final int depth,
            final int dimensions
    ) {
        if (width <= 0 || height <= 0 || depth <= 0) {
            throw new IllegalArgumentException(
                    "Storage texture extent must be positive, got " + width + "x" + height + "x" + depth
            );
        }

        MTLTextureType type = switch (dimensions) {
            case 1 -> MTLTextureType.Type1D;
            case 2 -> MTLTextureType.Type2D;
            case 3 -> MTLTextureType.Type3D;
            default -> throw new IllegalArgumentException("Storage texture dimensions must be 1, 2, or 3, got " + dimensions);
        };
        int textureHeight = dimensions == 1 ? 1 : height;
        int textureDepth = dimensions == 3 ? depth : 1;
        int usage = GpuTexture.USAGE_TEXTURE_BINDING | GpuTexture.USAGE_COPY_SRC | GpuTexture.USAGE_COPY_DST;
        return new MetalGpuTexture(
                this,
                usage,
                label == null ? "" : label,
                format,
                width,
                textureHeight,
                textureDepth,
                1,
                type,
                true
        );
    }

    @Override
    public @NonNull List<String> getLastDebugMessages() {
        return List.of();
    }

    @Override
    public boolean isDebuggingEnabled() {
        return this.debugOptions.logLevel() > 0 || this.debugOptions.useLabels() || this.debugOptions.useValidationLayers();
    }

    boolean useLabels() {
        return this.debugOptions.useLabels();
    }

    @Override
    public @NonNull CompiledRenderPipeline precompilePipeline(final @NonNull RenderPipeline pipeline, @Nullable final ShaderSource shaderSource) {
        ShaderSource effectiveSource = shaderSource == null ? this.defaultShaderSource : shaderSource;
        return this.compiledPipelines.computeIfAbsent(pipeline, p -> MetalCrossShaderCompiler.compile(this, p, effectiveSource));
    }

    /**
     * Removes selected compiled pipelines from the identity cache without releasing their native
     * Metal objects immediately. Callers may use the returned keys to compile replacements against
     * changed pipeline-visible state while already-recorded GPU work can continue referencing the
     * old objects. The removed native pipelines are released by the next full cache clear, after
     * that path has waited for submitted GPU work to complete.
     */
    public List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        Objects.requireNonNull(predicate, "predicate");

        List<RenderPipeline> evicted = new ArrayList<>();
        Iterator<Map.Entry<RenderPipeline, MetalCompiledRenderPipeline>> entries = this.compiledPipelines.entrySet().iterator();
        while (entries.hasNext()) {
            Map.Entry<RenderPipeline, MetalCompiledRenderPipeline> entry = entries.next();
            if (!predicate.test(entry.getKey())) {
                continue;
            }

            evicted.add(entry.getKey());
            this.deferredPipelineReleases.add(entry.getValue());
            entries.remove();
        }
        return List.copyOf(evicted);
    }

    @Override
    public void clearPipelineCache() {
        this.waitForSubmittedGpuWork();
        this.deferredPipelineReleases.forEach(MetalCompiledRenderPipeline::close);
        this.deferredPipelineReleases.clear();
        this.compiledPipelines.values().forEach(MetalCompiledRenderPipeline::close);
        this.compiledPipelines.clear();
        this.shaderCache.values().forEach(IntermediaryShaderModule::close);
        this.shaderCache.clear();
        for (MemorySegment function : this.functionCache.values()) {
            if (!ObjC.isNil(function)) {
                ObjC.release(function);
            }
        }
        this.functionCache.clear();
    }

    @Override
    public void close() {
        this.waitForSubmittedGpuWork();
        this.commandEncoder.close();
        this.clearPipelineCache();
        try {
            this.cocoa.clearViewLayer();
        } catch (Throwable ignored) {
        }
        MTLStorageTexturePipelines.close();
        MTLBuiltinPipelines.close();
        this.commandQueue.close();
        for (MemorySegment state : depthStencilStates.values()) {
            ObjC.release(state);
        }
        depthStencilStates.clear();
        ObjC.release(this.metalDeviceHandle);
    }

    @Override
    public @NonNull GpuQueryPool createTimestampQueryPool(final int size) {
        return new MetalGpuQueryPool(size);
    }

    @Override
    public long getTimestampNow() {
        return System.nanoTime();
    }

    @Override
    public @NonNull DeviceInfo getDeviceInfo() {
        return this.deviceInfo;
    }

    MemorySegment metalDeviceHandle() {
        return this.metalDeviceHandle;
    }

    MTLDevice metalDevice() {
        return this.metalDevice;
    }

    MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
        long key = (compareFunction.value << 1) | (writeDepth ? 1L : 0L);
        MemorySegment cached = depthStencilStates.get(key);
        if (cached != null) {
            return cached;
        }
        try (MTLDepthStencilDescriptor descriptor = MTLDepthStencilDescriptor.create()) {
            descriptor.depthCompareFunction(compareFunction);
            descriptor.depthWriteEnabled(writeDepth);
            MemorySegment state = metalDevice.newDepthStencilState(descriptor);
            depthStencilStates.put(key, state);
            return state;
        }
    }

    void waitForSubmittedGpuWork() {
        this.commandEncoder.waitForSubmittedGpuWork();
    }

    void queueResourceRelease(final MemorySegment handle) {
        this.commandEncoder.queueForDestroy(() -> ObjC.release(handle));
    }

    MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline) {
        return this.compiledPipelines.computeIfAbsent(pipeline, p -> MetalCrossShaderCompiler.compile(this, p, this.defaultShaderSource));
    }

    IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type, final ShaderDefines defines, final ShaderSource shaderSource) {
        ShaderCompilationKey key = new ShaderCompilationKey(id, type, defines);
        return this.shaderCache.computeIfAbsent(key, k -> {
            String source = shaderSource.get(k.id(), k.type());
            if (source == null) {
                return IntermediaryShaderModule.INVALID;
            }
            String sourceWithDefines = prepareShaderSource(source, k.defines());
            try (GlslCompiler glslCompiler = new GlslCompiler()) {
                return glslCompiler.createIntermediary(k.id().toDebugFileName(), sourceWithDefines, k.type());
            } catch (ShaderCompileException e) {
                throw new IllegalStateException("Failed to compile shader " + k.id(), e);
            }
        });
    }

    private static String prepareShaderSource(final String source, final ShaderDefines defines) {
        String stripped = BLOCK_COMMENTS.matcher(source).replaceAll("");
        stripped = LINE_COMMENTS.matcher(stripped).replaceAll("").stripLeading();
        return GlslPreprocessor.injectDefines(stripped, defines);
    }

    MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        return this.functionCache.computeIfAbsent(
                new MslFunctionKey(msl, entryPoint),
                key -> this.metalDevice.newFunction(key.msl(), key.entryPoint())
        );
    }

    private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines) {
    }

    private record MslFunctionKey(String msl, String entryPoint) {
    }

    private DeviceInfo buildDeviceInfo(final String deviceName) {
        DeviceType type = DeviceType.INTEGRATED;
        Set<String> extensions = Set.of();
        String osVersion = System.getProperty("os.version", "").trim();
        String driverDescription = "macOS " + osVersion;
        long maxMemoryAllocationSize = Math.min(metalDevice.maxBufferLength(), metalDevice.recommendedMaxWorkingSetSize());
        return new DeviceInfo(
                deviceName,
                "Apple",
                driverDescription,
                true,
                "Metal",
                1.0F,
                new DeviceLimits(16, 256, 16384, maxMemoryAllocationSize, 0, 8),
                new DeviceFeatures(false, false, true, true, true, false, true),
                extensions,
                new HintsAndWorkarounds(false, false),
                type
        );
    }

    @Nullable
    private String resolveDebugLabel(@Nullable final Supplier<String> label) {
        return this.useLabels() && label != null ? label.get() : null;
    }
}
