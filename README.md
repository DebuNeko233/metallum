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

## Validation status

The MRT, native color-mipmap, and selective pipeline-cache changes on the current feature branch are source-reviewed but are **not yet runtime-validated**. A successful Minecraft/Gradle build and Apple-Silicon smoke coverage are still required before this work should be merged.

## Requirements

- macOS
- Apple Silicon (M1 or newer)

