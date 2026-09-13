## Metallum

Metallum is an experimental rendering backend for Minecraft on macOS that uses Apple’s Metal API instead of OpenGL/Vulkan. It provides a more native rendering path and aims to improve performance and efficiency on Apple Silicon.

This project is still experimental. Performance, stability, and compatibility may vary depending on your system and installed mods. If you encounter bugs, please report them on GitHub.

## Current compatibility target

- Minecraft Java Edition **26.2**
- Fabric Loader **0.19.3**
- Sodium **0.9.2 for Minecraft 26.2** (`mc26.2-0.9.2-fabric`)
- Java **25**
- macOS on Apple Silicon

Version-sensitive Minecraft Graphics API and Sodium integrations must be checked against the 26.2 source/API before backend changes are made.

## Minecraft 26.2 MRT foundation

The Metal backend now follows Minecraft 26.2's indexed color-target model instead of assuming a single color attachment:

- `RenderPassDescriptor.colorAttachments()` slots are preserved by index, including unused/null slots.
- Up to 8 Metal color attachments are supported per render pass.
- `RenderPipeline.getColorTargetStates()` is compiled slot-by-slot into the Metal pipeline descriptor.
- Color format, write mask, and blend state are configured per active target slot.
- Render-pass clear values are tracked per attachment.
- MRT attachment extents are validated before encoding.
- Depth-only render passes no longer depend on a synthetic color attachment for viewport/scissor sizing.

Minecraft 26.2 currently constrains active color targets to compatible blend-function usage at `RenderPipeline.Builder` level; Metallum still keeps the Metal state attachment-local so the backend does not reintroduce a single-target assumption.

This is backend GPU behavior only. Shader-pack concepts such as `colortex*`, draw-buffer routing, ping-pong/history, shadow/deferred/composite scheduling, and pack policy belong in Vitrail rather than Metallum.

## Native mipmap command

The command encoder now exposes backend-level color mipmap generation through Metal's native `MTLBlitCommandEncoder.generateMipmapsForTexture:` path.

- Existing Metal render/blit encoder and `MTLFence` transitions are reused; Vulkan-style barriers are not reproduced in the Metal backend.
- Pending color clears are materialized before the mipmap blit begins.
- Closed textures, single-level textures, active render passes, and non-color `GpuFormat`s are rejected conservatively.
- Depth/stencil mipmap generation is **not** implemented by this native path. Apple's native mipmap command requires color-renderable, color-filterable formats; shader-pack shadow-depth mip chains therefore still require a separate backend implementation before that feature is considered complete.

The method is intentionally a generic Metal command-encoder capability. It contains no Vitrail shader-pack scheduling or texture-name semantics.

## Selective pipeline-cache eviction

`MetalDevice` now exposes a backend-level `evictCachedPipelines(Predicate<RenderPipeline>)` operation for callers whose pipeline-visible state changes without a full resource reload.

- The caller chooses the predicate; Metallum does not know shader-pack, entity, or Vitrail semantics.
- Matching keys leave the identity cache immediately so the next `precompilePipeline` rebuilds them from the current `RenderPipeline` state.
- Their `MetalCompiledRenderPipeline` objects are not released at the eviction point because already-recorded GPU work may still reference them.
- Evicted native pipelines are held until the next `clearPipelineCache()`, whose existing `waitForSubmittedGpuWork()` provides the safe release point before `close()` is called.

This is required for state such as vertex layouts because `MetalCompiledRenderPipeline` writes each binding's `VertexFormat.getVertexSize()` into the `MTLVertexDescriptor` stride at compile time. A cached pipeline therefore cannot safely survive a live vertex-layout change merely because the `RenderPipeline` Java object is unchanged.

Minecraft 26.2's public `GpuDeviceBackend` only exposes full-cache `clearPipelineCache()`; it has no selective invalidation operation, so this remains a Metallum backend extension rather than a replacement for a public Mojang API.

## Shader-storage buffer foundation

Metallum has a backend-level path for shader-storage buffers even though Minecraft 26.2 exposes no `GpuBuffer` storage-usage flag.

- `MetalDevice#createStorageBufferResource(long)` allocates a normal backend-owned `MetalGpuBuffer` in shared memory and zero-initializes the complete allocation before it is exposed to a shader.
- The returned object is still a Minecraft `GpuBuffer`, so integrations can keep resource ownership and deferred destruction inside the normal backend lifetime instead of carrying an `MTLBuffer` handle.
- `MetalCrossShaderCompiler` additionally reflects `SPVC_RESOURCE_TYPE_STORAGE_BUFFER` from the raw SPIR-V. It preserves the binding index already used by the caller's placeholder bind-group entry instead of allocating a duplicate Metal argument slot.
- A reflected storage-buffer entry becomes `ResourceKind.STORAGE_BUFFER`; it therefore shares Metal's buffer index space with uniform buffers and is included when the first free vertex-buffer slot is chosen.
- Render-pass binding uses the same `setVertexBuffer` / `setFragmentBuffer` path as other Metal buffers. No Vulkan descriptor-set or push-descriptor model is reproduced on Metal.

The binding-index reuse is deliberate. Vitrail currently exposes a shader-storage name to Minecraft 26.2 as a placeholder uniform entry because the public bind-group API has no storage-buffer entry type. Its SPIR-V reflection mixin also makes the vanilla rebind pass aware of that resource. Metallum recognizes the underlying SPIR-V resource as storage while retaining that one shared index, so the placeholder is an API bridge rather than a second resource.

## Shader-storage image foundation

Metallum now also exposes backend-native primitives for shader-writable textures without putting shader-pack semantics into the backend.

- `MetalDevice#createStorageTextureResource(...)` creates backend-owned 1D, 2D, or true 3D `GpuTexture` objects with `MTLTextureUsageShaderRead | MTLTextureUsageShaderWrite` and copy usage.
- True 3D textures use `MTLTextureType3D`; Minecraft's ordinary `depthOrLayers` array-texture interpretation is not reused for this path.
- `MetalCrossShaderCompiler` reflects `SPVC_RESOURCE_TYPE_STORAGE_IMAGE` directly from SPIR-V, reuses the caller's placeholder binding index, and classifies the resource as `ResourceKind.STORAGE_IMAGE`.
- A storage image is bound as a Metal texture argument only. No sampler state is written for the storage binding. If a shader-pack directive also exposes a sampled alias, that alias remains an ordinary `SAMPLED_IMAGE` texture-plus-sampler binding.
- `MetalCommandEncoder#clearStorageTexture(...)` clears writable 1D/2D/3D textures to numeric zero through cached typed Metal compute kernels for floating-point, signed-integer, and unsigned-integer storage images.
- `MetalCommandEncoder#copyStorageTextureRegion(...)` performs exact texture-region copies with the Metal blit encoder. It deliberately does not define overlapping in-place copy semantics; callers that shift a volume must provide a distinct scratch texture.
- Render, compute, and blit encoder transitions reuse Metallum's existing `MTLFence` dependency chain instead of copying Vulkan image-layout/barrier logic into Metal.

These methods are backend capabilities only. They do not decide which shader-pack image is cleared, which volumes follow the camera, when scratch storage is needed, or how frame scheduling works. Those remain caller policy.

This foundation does **not** imply that an external shader-pack engine's compute stage is already Metal-capable. In the current Vitrail migration, storage-image allocation, render-stage binding, zero clear, and reanchor copies are being bridged, while Vitrail's custom compute compiler/dispatch path is still Vulkan-specific and must be backend-neutralized separately.

## Validation status

The latest compile-validated backend code is head `881c4337426fe2dd88b08bcad2d029a00bfa3d71`: GitHub Actions run `34761479404` completed `./gradlew build` successfully with Java 25 after storage-image draw binding was added. Earlier MRT/SSBO heads were also compile-validated by the same PR build gate.

Runtime validation is still outstanding. Before this work is ready to merge it needs Apple-Silicon smoke coverage for indexed MRT, native color mipmaps, selective pipeline eviction, SSBO write/read, and writable storage-image clear/write/read behavior including a true 3D texture. Depth/stencil mipmap generation remains outside the implemented capability set.

## Requirements

- macOS
- Apple Silicon (M1 or newer)
