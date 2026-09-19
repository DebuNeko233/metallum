package com.metallum.render;

import com.metallum.render.execution.MetalApiGeneration;
import com.metallum.render.execution.MetalDeviceCapabilities;
import com.metallum.render.execution.MetalExecutionPreference;
import com.metallum.render.execution.MetalExecutionSelector;
import com.metallum.render.execution.MetalExecutionServices;
import com.metallum.render.execution.MetalShaderLanguageProfile;
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
import com.metallum.mtl.metal3.MTLStorageTexturePipelines;
import com.metallum.render.shared.MetalDeviceFacts;
import com.metallum.render.shared.MetalFrameEncoder;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.shared.MetalGpuQueryPool;

@Environment(EnvType.CLIENT)
public final class MetalDevice implements GpuDeviceBackend, MetalDeviceFacts {
    private final MemorySegment metalDeviceHandle;
    private final MTLDevice metalDevice;
    private final CAMetalLayer metalLayer;
    private final Cocoa cocoa;
    private final GpuDebugOptions debugOptions;
    // The frame's encoder as a contract rather than as this generation's class: the device owns the frame's
    // lifetime and calls four operations on it, and none of them needs to know which generation encodes it.
    private final com.metallum.render.shared.MetalFramePresentGate presentGate;
    private final MetalFrameEncoder commandEncoder;
    private final DeviceInfo deviceInfo;

    /** What executes, and the queue it submits on; the selection replaces this in M4. */
    private final MetalExecutionServices services;
    /** The pipelines a Metal 3 session retired: the cache no longer names them, the GPU may still use them. */
    private final Metal3PipelineRetirement retirement = new Metal3PipelineRetirement();
    /** The Metal 3 compilation state this device opened; it owns the caches, the device delegates. */
    private final Metal3CompilationContext compilation;
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
        MTLBuiltinPipelines.init(this.metalDevice);
        // Asked once, here, because the answer is a fact about the device and the system rather than
        // about a frame: whether the image can be loaded at all and whether this GPU can run the
        // scaler. Said out loud either way, so that a session's log names which of the two it was.
        MetalFx.spatialSupported(metalDeviceHandle);
        Metal4.available(this.metalDevice);
        // What this device can run, asked once and immutable; then which generation this launch executes.
        // The selector answers from capability - never from a chip name - and a forced preference the device
        // cannot satisfy fails the launch rather than falling back to the path nobody asked for. What is
        // executing today is still Metal 3's command buffer, which the services say plainly rather than
        // letting a selection read as a fact about the frame.
        MetalDeviceCapabilities capabilities =
                MetalDeviceCapabilities.probe(this.metalDevice, deviceName);
        MetalExecutionSelector.say(capabilities);
        MetalExecutionSelector.Decision decision =
                MetalExecutionSelector.select(MetalExecutionPreference.read(), capabilities);

        // The queue comes from the execution services rather than from the device, which is the seam the
        // frame path's isolation needs: a device that makes its own Metal 3 queue is a device that belongs to
        // one generation, and the package split cannot be written until that is untrue.
        // <p>
        // And the services carry the generation this launch was *selected* to execute rather than a constant.
        // They used to be built for Metal 3 before the selection was taken, which made the one object every
        // seam asks - the queue, the present policy - disagree with the selection this same constructor had
        // just logged. Nothing read it yet, so nothing broke; the day something does, an AUTO launch that
        // chose Metal 4 and a forced Metal 3 launch would have looked identical to it.
        // Metal 3 executes the frame whatever was selected: the selected generation's own frame path is what
        // M4 builds, and until it exists this argument is the honest answer rather than a constant baked into
        // the services. `framePathReady()` is then asked - not to change anything, but because a readiness seam
        // nothing asks is a readiness seam that answers wrongly the first time something does.
        this.services = MetalExecutionServices.of(decision.selected(), MetalApiGeneration.METAL3);
        this.presentGate = this.services.startPresentPath(this.metalDevice);
        if (!this.services.framePathReady()) {
            com.metallum.Metallum.LOGGER.info(
                    "Metal execution: {} was selected and has no frame path yet, so the frame is {}'s and the "
                            + "selected generation is a reference shell for it",
                    this.services.selected().token(), this.services.executing().token());
        }
        // Said out loud, because "the seams ask the selection and not a constant" is a claim about a value
        // nothing else prints: `selectedGeneration` in the frame probe comes from the telemetry, not from this
        // instance. Two of these lines - one from an AUTO launch, one from a forced Metal 3 launch - are what
        // says the services really carry the selection.
        com.metallum.Metallum.LOGGER.info("Metal execution seam: selectedGeneration={} executingGeneration={} mode={} referenceShell={} framePathReady={}",
                this.services.selected().token(), this.services.executing().token(),
                this.services.framePathReady() ? "own-path" : "reference-shell",
                this.services.isReferenceShell(), this.services.framePathReady());

        // The shader profile follows what *executes*, not what was selected: a session that has chosen
        // Metal 4 but still encodes its frame through Metal 3 needs MSL the Metal 3 path can compile, and
        // the day the new path executes is the day this switches to 4.0. The Metal 3 ladder is walked by
        // compiling a probe library, so "3.2" here means the system took it and not that the OS is new.
        MetalApiGeneration executing = this.services.executing();
        if (executing == MetalApiGeneration.METAL3) {
            MetalShaderLanguageProfile.select(capabilities.shaderLanguageProfile(),
                    "Metal 3 executes the frame and " + capabilities.shaderLanguageProfile().token()
                            + " is the newest profile it accepted");
        } else {
            MetalShaderLanguageProfile.select(MetalShaderLanguageProfile.MSL_4_0,
                    "Metal 4 executes the frame and the 4.0 toolchain is the one the translator was written "
                            + "against");
        }
        this.commandEncoder = this.services.createFrameEncoder(this);
        this.compilation = new Metal3CompilationContext(this.metalDevice, this.retirement);
        this.deviceInfo = buildDeviceInfo(deviceName);
    }

    @Override
    public @NonNull GpuSurfaceBackend createSurface(final long windowHandle) {
        return new MetalSurface(this, this.metalLayer);
    }

    @Override
    public @NonNull MetalFrameEncoder createCommandEncoder() {
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

    @Override
    public boolean useLabels() {
        return this.debugOptions.useLabels();
    }

    /**
     * Compiles or finds a render pipeline under the same device monitor used by every cache the
     * compiler can touch. Metal permits pipeline-state creation away from the render thread, but
     * the Java caches and the mutable intermediary SPIR-V modules are shared. Serializing their
     * mutation here makes this public entry point safe for background warm-up while command
     * encoding remains render-thread-owned.
     */
    @Override
    public synchronized @NonNull CompiledRenderPipeline precompilePipeline(final @NonNull RenderPipeline pipeline, @Nullable final ShaderSource shaderSource) {
        ShaderSource effectiveSource = shaderSource == null ? this.defaultShaderSource : shaderSource;
        return this.compilation.getOrCompilePipeline(pipeline, effectiveSource);
    }

    /**
     * Removes selected compiled pipelines from the identity cache without releasing their native
     * Metal objects immediately. Callers may use the returned keys to compile replacements against
     * changed pipeline-visible state while already-recorded GPU work can continue referencing the
     * old objects. The removed native pipelines are released by the next full cache clear, after
     * that path has waited for submitted GPU work to complete.
     */
    public synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        return this.compilation.evictCachedPipelines(predicate);
    }

    @Override
    public synchronized void clearPipelineCache() {
        this.waitForSubmittedGpuWork();

        this.retirement.releaseRetired();
        this.compilation.clearActivePipelines();

        this.compilation.clearShaderCache();
        this.compilation.clearFunctionCache();
    }

    @Override
    public synchronized void close() {
        this.waitForSubmittedGpuWork();
        this.commandEncoder.close();
        this.clearPipelineCache();
        try {
            this.cocoa.clearViewLayer();
            // The view only ever borrowed the layer; this is the reference this code was given.
            this.metalLayer.close();
        } catch (Throwable ignored) {
        }
        MTLStorageTexturePipelines.close();
        MTLBuiltinPipelines.close();
        MetalFx.close();
        // The present road's objects go with the device that made them, and this is the one place they are
        // released. The call used to appear twice: once inside the surface teardown above, where a throw from
        // the layer release would have skipped it, and once here. The unconditional site is the one that stays.
        this.services.closePresentPath();
        this.compilation.close();
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

    @Override

    public MemorySegment metalDeviceHandle() {
        return this.metalDeviceHandle;
    }

    public     MTLDevice metalDevice() {
        return this.metalDevice;
    }

    synchronized MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
        return this.compilation.depthStencilState(compareFunction, writeDepth);
    }

    void waitForSubmittedGpuWork() {
        this.commandEncoder.waitForSubmittedGpuWork();
    }

    /**
     * The execution services this device was opened with, for the seams that ask which generation runs.
     * <p>
     * Public because it is the facade's own fact and the milestone's central seam - the queue factory, the frame
     * encoder factory, the present gate and the readiness question all come through it - and because the frame
     * path, once it lives in its own package, has to ask the same question the device does.
     */
    public MetalExecutionServices executionServices() {
        return this.services;
    }

    public     void queueResourceRelease(final MemorySegment handle) {
        this.commandEncoder.queueForDestroy(() -> ObjC.release(handle));
    }

    /**
     * The compiled artifact for this pipeline, recompiling it if the one held was translated for another MSL
     * profile.
     * <p>
     * <strong>Why a guard and not a composite key.</strong> The identity cache is keyed by the game's own
     * pipeline object, which is the shader identity and is what makes two equal descriptions share one artifact
     * (measured: 345 identities against 345 keys on the settled pack scene, so a keyed cache would hold exactly
     * these entries). What that key does not name is the <em>profile the artifact was translated for</em>, and a
     * module or a pipeline state is not profile-independent - it carries the MSL the translator produced and the
     * language version Metal accepted it under. Today the profile is chosen once per process before any compile,
     * which is why this cannot bite yet; the guard is what makes a cross-profile hit impossible rather than
     * merely unlikely, at the cost of one string comparison per pipeline request.
     * <p>
     * The other half of the artifact's identity, the binding layout mode, is not checkable here - it is derived
     * from the pipeline's bind group layouts inside the compiler, which is where the artifact is built - but it
     * is carried on the artifact's {@link MetalPipelineKey} and it is a pure function of the pipeline and the
     * device's capabilities, both of which are constant for the life of this cache. The profile is the one input
     * that is a property of the <em>session</em>, so it is the one that is checked.
     */
    /** Migration-only delegate: the active cache and its profile guard live in the compilation context. */
    synchronized MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline) {
        return this.compilation.getOrCompilePipeline(pipeline, this.defaultShaderSource);
    }

    /**
     * Migration-only delegate: the module cache, its key and its factory live in
     * {@link Metal3CompilationContext}; it goes when {@code MetalCrossShaderTranslator} holds the context.
     */
    synchronized IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type, final ShaderDefines defines, final ShaderSource shaderSource) {
        return this.compilation.getOrCompileShader(id, type, defines, shaderSource);
    }




    /**
     * Migration-only delegate: the function cache and its factory live in {@link Metal3CompilationContext};
     * it goes when the bridges and the compiled artifact hold the context.
     */
    synchronized MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        return this.compilation.getOrCompileFunction(msl, entryPoint);
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
