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

The one binding shape **not** proven is the engine's argument-buffer path, and it is not proven because
it may not have an equivalent: a table's sampler slots are capped at 16 by the header, and the engine
reaches for an argument buffer precisely when a program's highest sampler slot is 15 or more. That is
the open risk of this migration and it is described under [Risks](#risks).

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

## Risks

- **Sixteen sampler slots.** The engine uses an argument buffer where a program's highest sampler slot is
  15 or more, and a table holds at most 16 samplers. A program past that ceiling therefore cannot be bound
  by the sampler slots alone, and the table protocol has one method that might cover it:
  `setResource:atBufferIndex:` binds a resource *by id* into a buffer slot, which is the `[[id(n)]]`
  mechanism rather than an argument buffer. **This is the first thing to answer, before slice 2**, because
  it decides whether "the whole chain" is reachable at all - and it is a question about the device and the
  compiler rather than about this tree, so it is a probe and not a design.
- **Residency.** Every texture in the engine is created with `hazardTrackingMode` untracked; Metal 4 asks
  for residency sets and the present has so far worked without one. Whether a pack's frame needs a set is
  a measurement, not an assumption.
- **Pipelines.** `newRenderPipelineStateWithDescriptor:` is Metal 3's factory and its objects draw on
  Metal 4 encoders (proven), but `MTL4Compiler` also makes `MTL4RenderPipeline` objects for background
  compilation, which is where the low-frame work wants to go.
- **Machine state.** A migration this wide cannot be judged scene by scene: it needs the deterministic
  fixture the companion repository's smoke scenes provide, and the same-configuration floor taken in the
  same session, or the picture verdicts will be the sun moving.
