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
import com.metallum.mtl.metal3.MTLCommandQueue;
import com.metallum.render.shared.MetalFrameProbe;
import com.metallum.render.shared.MetalGpuBuffer;
import com.metallum.render.shared.MetalGpuTexture;
import com.metallum.render.shared.MetalGpuTextureView;
import com.metallum.render.shared.MetalGpuSampler;
import com.metallum.render.shared.MetalGpuQueryPool;

@Environment(EnvType.CLIENT)
public final class MetalDevice implements GpuDeviceBackend {
    private static final Pattern GLSL_ERROR_LINE = Pattern.compile("\\b\\d+:(\\d+):");
    private final MemorySegment metalDeviceHandle;
    private final MTLDevice metalDevice;
    private final CAMetalLayer metalLayer;
    private final Cocoa cocoa;
    private final GpuDebugOptions debugOptions;
    private final MetalCommandEncoder commandEncoder;
    private final DeviceInfo deviceInfo;
    public final MTLCommandQueue commandQueue;

    /** What executes, and the queue it submits on; the selection replaces this in M4. */
    private final MetalExecutionServices services;
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
        MTLBuiltinPipelines.init(this.metalDevice);
        // Asked once, here, because the answer is a fact about the device and the system rather than
        // about a frame: whether the image can be loaded at all and whether this GPU can run the
        // scaler. Said out loud either way, so that a session's log names which of the two it was.
        MetalFx.spatialSupported(metalDeviceHandle);
        Metal4.available(this.metalDevice);
        boolean newPath = Metal4Path.start(this.metalDevice);
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
        if (!this.services.framePathReady()) {
            com.metallum.Metallum.LOGGER.info(
                    "Metal execution: {} was selected and has no frame path yet, so the frame is {}'s and the "
                            + "selected generation is a reference shell for it",
                    this.services.selected().token(), this.services.executing().token());
        }
        this.commandQueue = new MTLCommandQueue(
                MemorySegment.ofAddress(this.services.commandQueue(this.metalDevice)));
        // Said out loud, because "the seams ask the selection and not a constant" is a claim about a value
        // nothing else prints: `selectedGeneration` in the frame probe comes from the telemetry, not from this
        // instance. Two of these lines - one from an AUTO launch, one from a forced Metal 3 launch - are what
        // says the services really carry the selection.
        com.metallum.Metallum.LOGGER.info("Metal execution seam: servicesSelected={} servicesExecuting={} referenceShell={} framePathReady={}",
                this.services.selected().token(), this.services.executing().token(),
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
        MetalCompiledRenderPipeline compiled = compiledFor(pipeline, effectiveSource);
        MetalFrameProbe.pipelineRequested(pipeline, compiled.pipelineKey());
        return compiled;
    }

    /**
     * Removes selected compiled pipelines from the identity cache without releasing their native
     * Metal objects immediately. Callers may use the returned keys to compile replacements against
     * changed pipeline-visible state while already-recorded GPU work can continue referencing the
     * old objects. The removed native pipelines are released by the next full cache clear, after
     * that path has waited for submitted GPU work to complete.
     */
    public synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
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
    public synchronized void clearPipelineCache() {
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
    public synchronized void close() {
        this.waitForSubmittedGpuWork();
        this.commandEncoder.close();
        this.clearPipelineCache();
        try {
            this.cocoa.clearViewLayer();
            // The view only ever borrowed the layer; this is the reference this code was given.
            this.metalLayer.close();
            // The new command structure's objects go with the device that made them.
            Metal4Path.close();
        } catch (Throwable ignored) {
        }
        MTLStorageTexturePipelines.close();
        MTLBuiltinPipelines.close();
        MetalFx.close();
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

    public     MTLDevice metalDevice() {
        return this.metalDevice;
    }

    synchronized MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
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

    /** The execution services this device was opened with, for the seams that ask which generation runs. */
    MetalExecutionServices executionServices() {
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
    private MetalCompiledRenderPipeline compiledFor(final RenderPipeline pipeline, final ShaderSource source) {
        MetalCompiledRenderPipeline held = this.compiledPipelines.get(pipeline);
        if (held != null && !held.pipelineKey().shaderProfile().equals(MetalShaderLanguageProfile.selected().token())) {
            // Released on the same deferred path an eviction uses: already-recorded GPU work may still be
            // referencing the artifact, so the native objects outlive the map entry by design.
            this.compiledPipelines.remove(pipeline);
            this.deferredPipelineReleases.add(held);
        }

        return this.compiledPipelines.computeIfAbsent(
                pipeline, p -> MetalCrossShaderCompiler.compile(this, p, source));
    }

    synchronized MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline) {
        MetalCompiledRenderPipeline compiled = compiledFor(pipeline, this.defaultShaderSource);
        MetalFrameProbe.pipelineRequested(pipeline, compiled.pipelineKey());
        return compiled;
    }

    synchronized IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type, final ShaderDefines defines, final ShaderSource shaderSource) {
        // The profile is part of the identity, not a detail of the compile: a module translated for Metal 3.2
        // is not the module a Metal 4 session needs, and the function cache below has always named it
        // (`MslFunctionKey`) while this one did not. It is one token and the profile is fixed per process, so
        // this changes no cache behaviour today - it is what makes the reuse impossible rather than unlikely.
        ShaderCompilationKey key = new ShaderCompilationKey(id, type, defines,
                MetalShaderLanguageProfile.selected().token());
        return this.shaderCache.computeIfAbsent(key, k -> {
            String source = shaderSource.get(k.id(), k.type());
            if (source == null) {
                return IntermediaryShaderModule.INVALID;
            }
            String sourceWithDefines = prepareShaderSource(source, k.defines());
            try (GlslCompiler glslCompiler = new GlslCompiler()) {
                return glslCompiler.createIntermediary(k.id().toDebugFileName(), sourceWithDefines, k.type());
            } catch (ShaderCompileException e) {
                throw new IllegalStateException(shaderCompileFailure(k.id(), sourceWithDefines, e), e);
            }
        });
    }

    private static String prepareShaderSource(final String source, final ShaderDefines defines) {
        String stripped = GlslCommentStripper.strip(source).stripLeading();
        return GlslPreprocessor.injectDefines(stripped, defines);
    }

    private static String shaderCompileFailure(final Identifier id, final String source, final ShaderCompileException error) {
        String message = error.getMessage();
        if (message == null) {
            return "Failed to compile shader " + id;
        }
        var lineMatch = GLSL_ERROR_LINE.matcher(message);
        if (!lineMatch.find()) {
            return "Failed to compile shader " + id;
        }

        int line;
        try {
            line = Integer.parseInt(lineMatch.group(1));
        } catch (NumberFormatException ignored) {
            return "Failed to compile shader " + id;
        }
        return "Failed to compile shader " + id + "\n" + shaderSourceContext(source, line, 4);
    }

    private static String shaderSourceContext(final String source, final int failingLine, final int radius) {
        String[] lines = source.split("\\R", -1);
        if (failingLine < 1 || failingLine > lines.length) {
            return "GLSL source line " + failingLine + " is outside the prepared source (" + lines.length + " lines)";
        }

        int first = Math.max(1, failingLine - radius);
        int last = Math.min(lines.length, failingLine + radius);
        StringBuilder context = new StringBuilder("GLSL source around line ").append(failingLine).append(':');
        for (int line = first; line <= last; line++) {
            context.append('\n')
                    .append(line == failingLine ? ">> " : "   ")
                    .append(String.format(Locale.ROOT, "%5d | %s", line, lines[line - 1]));
        }
        return context.toString();
    }

    synchronized MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        // The profile is part of the identity even though the MSL text already differs between profiles:
        // a cache whose key is the text is safe by accident, and one whose key names the profile is safe
        // by construction - and the accident is exactly what a future translator that emits the same text
        // for two profiles would remove.
        return this.functionCache.computeIfAbsent(
                new MslFunctionKey(msl, entryPoint,
                        com.metallum.render.execution.MetalShaderLanguageProfile.selected().token()),
                key -> this.metalDevice.newFunction(key.msl(), key.entryPoint())
        );
    }

    /**
     * What a translated module is keyed by: the shader, the stage, the defines it was compiled with **and the
     * MSL profile it was translated for**. The profile is here because a module is not a stage-independent
     * artifact: it carries the MSL the translator produced and the language version Metal accepted it under,
     * so a session that changed profile must not be handed a module from the other one.
     */
    private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines,
                                        String shaderProfile) {
    }

    private record MslFunctionKey(String msl, String entryPoint, String profile) {
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
