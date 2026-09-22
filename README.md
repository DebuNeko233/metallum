## Metallum

Metallum is an experimental rendering backend for Minecraft on macOS that uses Apple’s Metal API instead of OpenGL/Vulkan. It provides a more native rendering path and aims to improve performance and efficiency on Apple Silicon.

This project is still experimental. Performance, stability, and compatibility may vary depending on your system and installed mods. If you encounter bugs, please report them on GitHub.

How the two halves fit together, and how to obtain this one yet: the shader-pack engine is [Vitrail](https://github.com/DebuNeko233/Vitrail-Shaders-Metal), and Metallum is the backend its Metal path executes on. Vitrail's Metal path is the maintained one as of `v0.12.0-metal-beta`. **This repository has not published a release**, so there is no downloadable version of it yet and the pairing is a build-from-source matter; the release machinery exists and its first tag is open work. A platform whose renderer is not Metal has no path either way, which is a narrowing the companion repository accepted deliberately.

## Requirements

| Component | Version |
| --- | --- |
| Minecraft | 26.2 |
| Fabric Loader | 0.19.3, which is what it is built and tested against; the jar accepts 0.19.2 or later |
| Sodium | 0.9.2 for Minecraft 26.2 (`mc26.2-0.9.2-fabric`), which is what the backend draws through |
| Java | 25 |
| Platform | macOS on Apple Silicon (M1 or newer) |

The loader, Minecraft and Java ranges above are what the jar's own metadata declares, so the loader
enforces them whether or not this table is current: `src/main/resources/fabric.mod.json`. Two things
that metadata does **not** declare, and both are worth knowing before installing:

- **Sodium.** The backend integrates with it, through a `sodium:config_api_user` entry point and
  mixins on its classes, but the metadata does not list it as a dependency, so an instance without
  Sodium is not refused at startup the way a missing dependency is refused. Installing Sodium 0.9.2
  for 26.2 alongside this is required in practice.
- **Vitrail.** This is a backend rather than a mod a player drives. The shader-pack engine that runs
  on it is [Vitrail](https://github.com/DebuNeko233/Vitrail-Shaders-Metal), reached reflectively
  over `API_VERSION` 1, and it is the side that decides where the backend is used.

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
- Depth/stencil mipmap generation is **not** implemented by this native path. Apple's native mipmap command requires color-renderable, color-filterable formats, so a depth chain is reduced instead by the separate `MetalDepthMipmapBridge`: a generic progressive nearest-filter render pass over a `D32_FLOAT` texture, reached by an optional integration through reflection. A backend without it leaves the sampler clamped to level zero rather than failing the shadow stage. The bridge knows only the generic GPU contract; shader-pack depth target names and mip scheduling stay outside Metallum.

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
- `MetalDevice.close()` releases the cached storage-zero compute pipeline states through `MTLStorageTexturePipelines.close()`, keeping those native objects inside the Metal device lifetime.

These methods are backend capabilities only. They do not decide which shader-pack image is cleared, which volumes follow the camera, when scratch storage is needed, or how frame scheduling works. Those remain caller policy.

## Shader-pack compute backend foundation

The Metal backend now has a separate optional bridge for general shader-pack compute work. It is intentionally lower-level than a shader-pack engine and does not decide pack scheduling or resource meanings.

- `MTLComputeCommandEncoder` exposes Metal's `setBuffer:offset:atIndex:`, `setTexture:atIndex:`, and `setSamplerState:atIndex:` argument-table operations in addition to the existing storage-clear path.
- Pack dispatch counts are encoded with `dispatchThreadgroups:threadsPerThreadgroup:`. This preserves Vulkan `vkCmdDispatch` semantics: the first triplet is the number of workgroups, while the second triplet is the shader's local workgroup size. The existing `dispatchThreads:threadsPerThreadgroup:` method remains for workloads such as exact texel clears where the first size is a total thread grid instead.
- `MetalComputeBridge.compile(...)` accepts SPIR-V and keeps the resulting MSL source, `MTLFunction`, compute pipeline state, resource reflection, and native lifetime inside Metallum. The returned value is opaque to optional callers and is only valid when handed back to the bridge.
- Compute reflection currently covers uniform buffers, storage buffers, combined sampled images, and storage images. SPIR-V binding decorations are retained as Metal argument indices through SPIRV-Cross's MSL decoration-binding mode.
- `MetalComputeBridge.dispatch(...)` accepts already-resolved Minecraft `GpuBufferSlice`, `GpuTextureView`, and `GpuSampler` maps by shader resource name. Sampled images receive both texture and sampler state; storage images receive only a writable texture binding and are marked dirty before dispatch.
- Every dispatch uses Metallum's existing compute encoder and `MTLFence` chain. Finishing the compute encoder updates the same fence that subsequent render, blit, or compute encoders wait on, so Vulkan pipeline barriers are not copied into the Metal implementation.
- `MetalComputeBridge.close(...)` defers release of the native compute pipeline through Metallum's normal command-encoder destruction queue.

The bridge deliberately does **not** map `colortex*`, shadow images, custom textures, ping-pong halves, uniform names, or dispatch moments. Those are Vitrail policy and must be resolved before a resource reaches Metallum. Oversized shader-pack shared/threadgroup-memory rewriting and any resource classes outside the four reflected kinds above are not yet claimed as supported.

The companion Vitrail engine has an optional backend-neutral compute path that routes `PackCompute` through backend capabilities when both compute-device and compute-command providers are present, alongside that engine's existing path; the companion repository no longer treats its Vulkan path as one that has to be preserved, so this plumbing is described here by what it does rather than by what it sits beside. Compile-testing that plumbing in isolation proves nothing about Metal execution, so writable resource contents, encoder ordering, later render/compute visibility and fallback behavior are covered by the Apple-Silicon smoke launchers under `tools/` instead; see [Validation status](#validation-status).

## Validation status

The two builds are paired by the integration contract rather than by a commit. Vitrail understands `API_VERSION` 1 and this repository answers `MetallumApi.apiVersion()`; a build that answers anything else is reported by Vitrail as incompatible rather than used. The head is named where a piece of evidence rests on one, because a run records the exact material it ran, but it is not how the pair is described: this repository has not been released yet, so there is no version on this side to name, and a commit hash on a branch that has since been merged names history rather than a head. What is current is the long-term performance programme, which has landed on `master`: [docs/long-term-performance-summary.md](docs/long-term-performance-summary.md) is its result on one page - what each track proved, rejected and settled, and the owner's answers on what was left - and the policy it was run to is [docs/long-term-performance-plan.md](docs/long-term-performance-plan.md). The Apple-Silicon guard, the Vitrail runtime and configuration contracts, this repository's fifteen contract scripts, `./gradlew build` and artifact capture all complete on that head. [docs/README.md](docs/README.md) is the router for the rest of the documentation: which page owns what, the frozen Metal 4 record, and the first round the programme supersedes.

`tools/ci-contracts.py` is the home for those static contracts, and `.github/workflows/ci.yml` is the only workflow that runs on a pull request. It now also refuses a workflow that could author a commit anywhere in this repository: a self-pushing one-shot helper existed here and is deleted, and the shape is refused rather than the single file, so the next one cannot be added unnoticed.

The capability list this section once carried as "runtime validation still outstanding" is no longer outstanding. Indexed MRT including an unused middle slot, a multi-binding and per-instance vertex descriptor, native color mipmaps, selective pipeline eviction, SSBO and storage-image write/read including a true 3D texture, `colorimgN` shader-write allocation and shader-pack compute write/read visibility all belong to the PHASE 2 and PHASE 5-16 baselines, which the companion Vitrail PR records as closed with Apple-Silicon real-device evidence. The launchers under `tools/` are what produce that evidence and `VITRAIL_SMOKE.md` describes each gate. [docs/performance-testing.md](docs/performance-testing.md) is the operator's guide to the performance harness: how a run is staged and what it refuses, the frame-rate and GPU-time numbers the probe prints and what each counter means, and how large a difference this fixture can be trusted to show.

Both pull requests have since been merged, companion first, and the companion released `v0.12.0-metal-beta` from that work. PHASE 17 real shader-pack compatibility was closed by the project owner's judgement with no per-row compatibility status recorded, so it is no longer a merge blocker and no shader pack is promoted by it: the compatibility matrix is empty rather than partly filled. What that leaves unverified, and the findings that were open when it closed, are recorded in the companion repository's `docs/phase17-compatibility.md`. A green build, a successful launch or a clean log is still not evidence that Metal execution is correct: correctness on a real pack requires the reviewed screenshot and reference material that policy defines.
