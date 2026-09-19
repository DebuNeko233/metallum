# Moving the frame's passes to Metal 4

The present is already carried by a Metal 4 queue: one command buffer, one `commit:count:`, the picture
drawn into the drawable through the engine's present pipeline and an argument table. Everything else -
the pack's render passes, its compute dispatches, the engine's clears and blits, the MetalFX upscale -
is still encoded into one **Metal 3** command buffer a frame.

This is the plan for the rest of it, written down because it is the largest change in the tree and
because half of it is decided by facts that took a run each to establish.

## What is proven, and how

Everything below was answered on the M5 Pro / macOS 27.0 by a probe that runs once at device creation
(`MTL4Probe`) and by the two scenes in `performance-testing.md`.

| Question | Answer | Evidence |
| --- | --- | --- |
| Is the Metal 4 core API there? | yes | `Metal 4 core API: available` ... |
| Can an argument table be made? | yes, by `newArgumentTableWithDescriptor:error:` | the header's out-parameter is part of the selector; the one-argument name is a method no object has |
| Can a texture and a sampler be bound through one? | yes | the present draws the picture through it, 600 of 600 frames, and the picture matches the Metal 3 road |
| Can a **uniform buffer** be bound, by GPU address? | yes, and the pass *used* it | the engine's clear pipeline drew `(0.25, 0.5, 0.75, 1)` with its uniform in slot 1 of a table; the pixel was read back |
| Can a **vertex buffer** be bound, by address and stride? | yes, and the pass read it | a pipeline taking `const device float4* [[buffer(0)]]` drew a colour it could only get from that buffer, with `attributeStride` 16, read back as `(0.25, 0.5, 0.5, 1)` |
| Do Metal 3 pipeline states work on Metal 4 encoders? | yes | the present pipeline, the clear pipeline and a probe pipeline all draw on `MTL4RenderCommandEncoder` |
| Two new-kind encoders in one command buffer? | yes | the probe encodes two render passes into one command buffer and commits once |
| Is the sixteen-sampler ceiling a problem for the table? | no: it is MSL's, and the table took twenty slots | `sampler ceiling` probe, below |

The two things this document once listed as open are answered: the sampler ceiling is the compiler's
(`sampler` attributes are 0 to 15) and not the table's (a table took twenty slots), and the engine's
argument-buffer path binds as a buffer by address under Metal 4 - the same shape as a uniform, proven
above. Nothing in the binding surface is now unknown, which is why the slices below can start.

### The pipeline cache stays keyed by the game's own pipeline object

The migration table's "shared logical pipeline + generation-specific compile artifacts" invites moving
`MetalDevice`'s cache from `IdentityHashMap<RenderPipeline, ...>` onto a description key, so that two equal
descriptions share one artifact. The key exists (`MetalPipelineKey`, in `render.shared`) and it is a
sufficient identity: beyond the shaders it names the shader profile, the argument-buffer mode and one
composed `renderingState` description holding the depth and stencil state (which carries the colour-target
formats), the polygon mode, culling, the primitive topology and the vertex format bindings - every accessor
`MetalCompiledRenderPipeline` reads while it builds.

It was then measured instead of moved. The probe counts the distinct pipeline **identities** and the
distinct **keys** the device was asked for from process start, and on the settled pack scene
(`--settle 25`, camera pinned, Photon v1.3b at 55 per cent) the two read **345 and 345**:

    ... compiles=0 compileMs=0.00 pipelineIdentities=345 pipelineKeys=345 ...
    plain: 7.27 ms a frame, 137.6 frames a second, 7.28 ms of GPU time a frame over 600 answered frames

Equal counts mean a keyed cache would hold exactly the entries the identity cache holds. The move therefore
buys no compilations - the game builds each pipeline once and asks for it by that same object - while
costing the eviction contract (`evictCachedPipelines` takes a `Predicate<RenderPipeline>` and answers with
the pipelines it removed) and a hoist of the argument-buffer decision out of
`MetalCrossShaderCompiler.compile`, where it is derived from the layout entries. **So the cache keeps its
identity key, deliberately, and `MetalPipelineKey` keeps the job it was built for**: naming an artifact
across the two generations and saying in a log which description a compile belonged to.

The census stays on the probe rather than being removed after its one answer. It costs one identity-set
insertion per pipeline request and hashes the key only when the identity is new, and it is the only thing
that would report a future caller - a pack loader, or a Metal 4 table path - handing the device freshly
built equal pipelines. That run read inside the configuration's settled band (7.25-7.28 ms), so the
instrument did not move the number it measures.

## The API mapping

Metal 4 has no per-resource binding methods on its encoders at all. Each row is a call the engine makes
today and what it becomes.

| Today (Metal 3) | Metal 4 | Notes |
| --- | --- | --- |
| `MTLCommandQueue` + one `MTLCommandBuffer` a frame | `MTL4CommandQueue` + one `MTL4CommandBuffer` begun on an `MTL4CommandAllocator` from a ring | the allocator may only be reset once the GPU is done with it; the ring and the shared event that bounds it already exist in `Metal4Path` |
| `renderCommandEncoderWithDescriptor:` | same selector, on the command buffer, with an `MTL4RenderPassDescriptor` | the pass descriptor's attachments are Metal 3's own classes, so load and store actions move unchanged |
| `computeCommandEncoder` | same selector, on the command buffer | `MTL4ComputeCommandEncoder` keeps the blit it absorbed, which is how the engine's copy-backs and mip passes move for free |
| `blitCommandEncoder` | the compute encoder's copy methods | `copyFromTexture:toTexture:` takes two objects and no structures |
| `setVertexBuffer:offset:atIndex:` | `MTL4ArgumentTable.setAddress:attributeStride:atIndex:` + `setArgumentTable:atStages:` | proven above; the stride is the vertex layout the shader indexes with |
| `setVertexBytes:length:atIndex:` / `setFragmentBytes:length:atIndex:` | the same bytes written into a buffer and bound by address | the engine already allocates transient GPU-mapped memory for uniforms (`MetalRenderPass`), so this is a change of destination, not of source |
| `setVertexBuffer:`/`setFragmentBuffer:` for uniform buffers | `setAddress:atIndex:` | proven above |
| `setVertexTexture:atIndex:` / `setFragmentTexture:atIndex:` | `setTexture:atIndex:` by `gpuResourceID` | proven by the present |
| `setVertexSamplerState:atIndex:` / `setFragmentSamplerState:atIndex:` | `setSamplerState:atIndex:` by resource id | proven by the present |
| the per-layout argument buffer written by `MTLArgumentEncoder` | the table itself: the resources are bound into table slots instead of being encoded into a buffer | this is the part with the 16-sampler ceiling |
| `useResource:usage:stages:` | `MTLResidencySet` added to the queue (`addResidencySet:`) | the present works without one, so residency is a correctness/performance question to measure rather than a blocker |
| `updateFence:afterStages:` / `waitForFence:beforeStages:` | `barrierAfterEncoderStages:beforeEncoderStages:` and `barrierAfterStages:beforeQueueStages:` on the encoders | the engine's fence chain is what P1's read/write description was built for |
| `MTLFXSpatialScaler` (+ `encodeToCommandBuffer:` on a Metal 3 buffer) | `MTL4FXSpatialScaler` (on the Metal 4 buffer), built by `MTLFXSpatialScalerDescriptor.newSpatialScalerWithDevice:compiler:` | the Metal 4 variants ship in the same framework |

## The slices, in order

Each slice is measured before the next one starts, with the harness and the recipe in
`performance-testing.md`. A slice that cannot say what it bought is a slice that is not finished.

1. **The frame's command buffer becomes an MTL4 one, with nothing else changed.** `MetalCommandEncoder`
   begins an `MTL4CommandBuffer` where it begins the Metal 3 one, commits it through the Metal 4 queue,
   and every encoder it opens is still created the old way... which is impossible: an encoder comes from
   the command buffer it is encoded into. So this slice and the next are one: the command buffer and the
   render-pass twin move together, behind `-Dmetallum.metal4Frame=true`, with the Metal 3 path intact
   beside it.
   *Acceptance*: one no-pack scene, `windowMs` and `gpuMs` inside the floor, every counter equal, the
   picture inside the fixture's own noise, and `submit=600` with one commit a frame.
2. **Binding through tables, per layout and per stage.** One table per pipeline layout per stage, sized
   to what that layout binds. `MetalRenderPass` fills it where it fills the argument buffer or calls the
   direct setters today, and the vertices go in by address and stride.
   *Acceptance*: the pack's first full frame drawn on the new path with the picture matching the Metal 3
   road within the noise floor, and the binding counters (`texture`, `sampler`, `buffer`) unchanged - the
   same number of resources reaches the GPU, by a different route.
3. **Barriers where the fence chain is.** The engine already marks storage-image writes as unordered
   (`MetalCommandEncoder.storageUnordered`) and updates a fence at every encoder end; that description
   becomes the barrier that replaces it.
   *Acceptance*: the same picture, and a pass that reads another's storage image ordered by a barrier
   rather than by the fence.
4. **The present joins the same command buffer.** The drawable is taken where the surface says what it
   presents, the present pass is encoded after the frame's passes, and the frame's one commit is
   followed by `signalDrawable:` and `present`.
   *Acceptance*: one command buffer and one commit a frame in the probe, the present counters equal to
   the frame counters, and the picture unchanged.
5. **MetalFX moves with it**: `MTL4FXSpatialScaler` created through a `MTL4Compiler` and encoded into the
   same buffer.
   *Acceptance*: the same three render scales as P6's seat measurement, `gpuMs` not worse.
6. **The Metal 3 command buffer and the fence chain are removed**, which is when `AppKit`'s own present
   road (`encodePresentTextureToDrawable`) and the Metal 3 encoder classes lose their last callers.

### The isolation that is left is counted, not estimated

`tools/ci-architecture.py` grew a second kind of rule beside the layer rules: a ledger of every file outside
the generation packages that still names the frame path's concrete generation, checked in **both**
directions. A file that starts naming `MTLCommandBuffer`, `MetalCommandEncoder`, `MetalRenderPass` or their
kind is a regression and fails the guard; a file that stops doing so must have its line deleted in the same
commit, because a ledger nobody prunes reports work that is already done. The guard prints the total on every
run, so the milestone's cost is a number that can only go down:

    architecture guard: PASS (110 sources, 5 package rules, one mixing rule; the frame path's isolation
    still owes 18 couplings in 7 files, and 1 the other way)

Reading that ledger is what says where the facade move actually is. It is not ten members in one file:
`render/shared/MetalTransientMemory.java` names `MetalCommandEncoder` - a shared-layer file reaching into
what will become Metal 3's package, which the layer rule will fail the day the encoder moves - and
`mtl/MTLDevice.java` names `MTLCommandQueue`, with `MTLBuiltinPipelines` and `MTLStorageTexturePipelines`
naming Metal 3 encoders from the bindings side. A file naming its own class is not counted, because
`MetalRenderPass` declaring `MetalRenderPass` says nothing about generations.

The first of those is gone, and the ledger's own rule is what removed the line: `MetalTransientMemory` took
the encoder only to retire its rotated blocks, so what it needs is the **destruction queue** the encoder
itself adds to, not the encoder. Taking the same instance keeps the semantics identical by construction -
retired blocks are released on the encoder's rotation, as before - while the shared layer stops naming the
frame path's concrete class, which the layer rule would have failed the day the encoder moved to
`render.metal3`. Verified on the settled pack scene: 7.31 ms with `gpuM3Ms=4391.78` against the immediately
preceding run's 7.31 ms and `gpuM3Ms=4392.35`, every counter equal.

The second line to go needed no abstraction at all: `mtl/MTLDevice.java` named `MTLCommandQueue` only in
`newCommandQueue()`, a queue factory **nothing called** - the services build the queue from the device's
handle directly. A generation name carried by dead code is the cheapest line in the ledger to remove: the
method, its `Msg` and its import are gone, and the removal cannot change behaviour because there was no
caller to change it for (a repo-wide search for the call, not the name, is what says so).

The third and fourth are where the plan this document was carrying turned out to be wrong, and the code
said so. Two of the four bridges - `MetalAttachmentBridge` and `MetalScaleBridge` - only *ask* the encoder
things (hand the next pass its answers, ask whether the scaler is available, ask it to scale), so those
questions became a contract: `render/shared/MetalFrameExtras`, four methods on shared and game types only,
with `MetalCommandEncoder` implementing it and the two bridges dispatching on the interface instead of on
the class. **The other two bridges cannot be abstracted at all.** `MetalComputeBridge` and
`MetalDepthMipmapBridge` do not ask, they encode: their bodies drive `MTLComputeCommandEncoder` and
`MTLRenderCommandEncoder` directly, and any interface that could express them would have to hand out a
generation's encoder from the neutral layer - the layer rule fails exactly that, and it is right to. They
are Metal 3's own code, so they move to `render.metal3` with the encoder and get a Metal 4 sibling, and
`instanceof` stays their seam. An interface there would be the split undone in the name of the split.

The next caller was the same shape: `MetalDrawContext`, the sodium draw path, reached its pass through the
game's own `RenderPass` and named `MetalRenderPass` to write push constants. What it uses is two members, so
those two became `render/shared/MetalPassUniformWriter` - a mapped slice of transient memory, and a way to
bind it - and the draw path now asks for that contract, with an `IllegalArgumentException` naming the class
it actually got instead of an unchecked cast. One member had to be opened by it: `allocateTransient` was
package-private and is now public, **because the interface is what needs it** - which is the difference
between opening a member by contract and the hand-opening that produced a hundred "not public" errors in the
moves that failed.

The ledger reads 18 couplings in 7 files, and **1 the other way** - and that second number is the point of
this paragraph. `MTLBuiltinPipelines` is the neutral home of the built-in pipelines: the present pipeline
lives there once, drawn by Metal 3 through `MTLCommandBuffer` and by Metal 4 through `drawPresentWithTable`,
and the Metal 3 wrappers call into it from their own convenience methods. Wrapper calls neutral is the
direction that takes a generation out of the engine; counting it as work to be removed pushed towards pulling
the encode bodies into the wrappers, which is the opposite of the split. So the guard now lists those
separately and checks the direction is still what it claims: the neutral class must be called from inside a
generation package, or the line fails. `MTLStorageTexturePipelines` is deliberately **not** in that group yet
- it is called from `render` today, so it is debt until the encoder moves, and the ledger is where that
becomes a delegation.

The lesson is the metric's, not the code's: a count that cannot tell a design from a debt will eventually
argue for a bad change, and the fix is to make the count say which is which.

## Risks

- **Sixteen sampler slots are the compiler's ceiling, not the table's, and the argument buffer is the
  answer the engine already has.** Asked on the M5 Pro, four ways, and answered:
  seventeen direct samplers are **refused** - `'sampler' attribute parameter is out of bounds: must be
  between 0 and 15`; a sampler or a texture named by a resource id on a function argument is **refused** -
  `'id' attribute only applies to non-static data members`; and a table asking for **twenty sampler slots
  is accepted**, so the header's "maximum value is 16" is a statement about the documented range rather
  than a limit the runtime enforces. So the ceiling belongs to MSL, the engine's argument-buffer path is
  what carries a program with more sampled images than slots, and under Metal 4 that path is **a buffer
  bound by address** - which is the shape already proven above. What is left for those programs is
  residency, not binding.
- **Residency.** Every texture in the engine is created with `hazardTrackingMode` untracked; Metal 4 asks
  for residency sets and the present has so far worked without one. Whether a pack's frame needs a set is
  a measurement, not an assumption.
- **Pipelines.** `newRenderPipelineStateWithDescriptor:` is Metal 3's factory and its objects draw on
  Metal 4 encoders (proven), but `MTL4Compiler` also makes `MTL4RenderPipeline` objects for background
  compilation, which is where the low-frame work wants to go.
- **Machine state.** A migration this wide cannot be judged scene by scene: it needs the deterministic
  fixture the companion repository's smoke scenes provide, and the same-configuration floor taken in the
  same session, or the picture verdicts will be the sun moving.
