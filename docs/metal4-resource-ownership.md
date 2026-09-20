# Metal 4 resource ownership: who makes what, who releases it, and when

Section 105 asks for a ledger rather than a claim: every object the Metal 4 path creates, with its owner, where
it is created, how long it lives, and where it is released. It is written by reading the code - each row names
the file and the method that makes the object and the one that releases it - and it is worth having because the
first time it was written down it found a leak: the frame's queue was made by the execution services, handed to
the encoder, used by the ring, and released by nobody, while the Metal 3 encoder releases the queue the same
seam gives it. That is fixed (the encoder keeps the queue and releases it after the ring, and a pin checks it),
and the ledger is what would have shown it without a session.

Two rules run through every row:

- **the generation that makes an object releases it.** The queue, the allocators, the command buffer, the
  event, the encoders, the tables and the pipelines are all made by Metal 4 code and released by Metal 4 code.
  A shared-layer class never releases a Metal 4 object it did not make;
- **nothing is released while the GPU may still read it.** Everything that can be named by work already encoded
  is released either after the ring's completion value for its slot (the destruction queue) or after
  `clearCachesAfterGpuCompletion`'s precondition, which is the same fact said at the cache level.

## The session's objects

| object | made by | owner | lifetime | released by |
| --- | --- | --- | --- | --- |
| `MTL4CommandQueue` | `Metal4ExecutionProvider.commandQueue` (`newMTL4CommandQueue`) | the frame encoder that asked for it | the encoder's | `Metal4FrameEncoder.close()`, after the ring |
| `MTL4CommandAllocator` × ring slots | `MTL4FrameRing.create` | the ring | the ring's | `MTL4FrameRing.close()` |
| `MTL4CommandBuffer` (one, re-begun) | `MTL4FrameRing.create` | the ring | the ring's; begun per slot and committed once a frame | `MTL4FrameRing.close()` |
| shared event (one) | `MTL4FrameRing.create` | the ring | the ring's; its values are the slot completion proofs | `MTL4FrameRing.close()` |
| `MTL4CommitOptions` | `MTL4FrameRing.create` | the ring | the ring's; it carries the feedback handler and the commit's GPU time is read out of the feedback | `MTL4FrameRing.close()` |
| the feedback block | `MTL4FrameRing.create` | the ring | the ring's; it is the only handle to a submission's GPU time | `MTL4FrameRing.close()` |
| `IntermediaryShaderModule` (SPIR-V) | `Metal4CompilationContext.getOrCompileShader` | the compilation context | keyed by (shader, stage, defines, profile) | `clearCachesAfterGpuCompletion()`, and `close()` |
| native function (MSL → `MTLFunction`) | `Metal4CompilationContext.getOrCompileFunction` | the compilation context | keyed by (MSL, entry point, profile) | `clearCachesAfterGpuCompletion()` |
| `MTLComputePipelineState` | `Metal4CompilationContext.getOrCompileComputePipeline` | the compilation context | keyed like the function it is made from | `clearCachesAfterGpuCompletion()` |
| `Metal4ComputePipeline` (the handle a pack holds) | `Metal4ExecutionState.compileCompute` | the caller (a pack) | until the caller closes it | `Metal4ComputePipeline.close()`, which hands its reference to the state back through `MetalDevice.queueResourceRelease` |
| `MTLDepthStencilState` | `Metal4CompilationContext.depthStencilState` | the compilation context | keyed by compare and write | `Metal4ExecutionState.close()` |
| `Metal4CompiledRenderPipeline` (native pipelines + key) | `Metal4PipelineCompiler.compile` | the compilation context | cached per `RenderPipeline`; a profile mismatch retires it | `clearCachesAfterGpuCompletion()`, via retirement |
| the render pipeline state's cached depth-stencil state | the compilation context (shared) | the compilation context | as long as the context | `Metal4ExecutionState.close()` - **not** by the artifact, which is why an artifact's `close()` does not touch it |

## The frame's objects

| object | made by | owner | lifetime | released by |
| --- | --- | --- | --- | --- |
| `MTL4RenderCommandEncoder` (one per pass) | `MTL4RenderEncoder.open` | the pass | the pass's | `Metal4RenderPass`/`Metal4FrameEncoder` closes it at the end of the pass |
| `MTL4ComputeCommandEncoder` (the copy encoder) | `MTL4FrameEncoder.copyEncoder()` | the frame encoder | one per frame, opened on demand and shared by copies, mip generations and feedback | `Metal4FrameEncoder.close()` |
| `MTL4ComputeCommandEncoder` (one per dispatch) | `Metal4FrameEncoder.dispatchEncoder` | the frame encoder | **one per table-binding dispatch**, ended where it is encoded | `endDispatchEncoder` files `close` on the slot's destruction queue |
| `MTL4ArgumentTable` (per dispatch, per clear) | `Metal4ComputePipeline.newTable`, `MTL4FrameEncoder.clearStorageTexture` | the frame encoder | one per dispatch and per clear - never re-pointed and handed over twice | `queueForDestroy(table::close)`, run when the slot completes |
| `MTL4ArgumentTable` (the present's) | `Metal4FrameEncoder.presentTable()` | the frame encoder | one per frame encoder | `Metal4FrameEncoder.close()` |
| `MTL4ResidencySet` | `Metal4FrameEncoder` (first `useResource`) | the frame encoder | the session's; committed and attached once | `Metal4FrameEncoder.close()` |
| `MTL4StorageTexturePipelines` (the zeroing kernels) | `Metal4FrameEncoder`'s constructor | the frame encoder | the encoder's | `Metal4FrameEncoder.close()` |
| `MetalTransientMemory` (staging arena) | the frame encoder's constructor | the frame encoder | the encoder's | `Metal4FrameEncoder.close()`, after the deferred releases |
| `MetalDestructionQueue` | the frame encoder's constructor | the frame encoder | the encoder's | `Metal4FrameEncoder.close()` |
| deferred releases (per slot) | `queueForDestroy` | the frame encoder | a slot's | `retire(slot)`, run once that slot's completion is observed |
| `CAMetalDrawable` (present) | `presentTextureToDrawable` | the frame encoder | one frame | presented by `presentAll()`, after which the layer may hand it out again |

## The sidecar's objects, which are the ones the frame path must outlive

| object | made by | owner | lifetime | released by |
| --- | --- | --- | --- | --- |
| the sidecar's queue, command buffer, event | `Metal4Path.start` | `Metal4Path` | the session's, while the property selects that road | `Metal4Path.stop`, through `close()` |
| the sidecar's allocators, frame event, table, commit options | `Metal4Path.start` | `Metal4Path` | the session's | `Metal4Path.stop` |

The sidecar is off unless `-Dmetallum.metal4Present=true`, which now selects the **old** road: the frame
encoder's own present is the one that runs by default. Section 107 keeps the sidecar in place until the frame's
own present is real-device proven, and this ledger is where its objects are listed so the cleanup commit can be
checked against them rather than remembered.

## What the ledger has not been able to check: the teardown has never run in a session

Every row above says where an object is released, and **no session so far has run any of those lines**. Measured
rather than assumed: a forced Metal 4 session was launched, allowed to reach its first compute dispatches, and
sent `SIGTERM`. It exited within thirty seconds - the shell reported status 143 - with **no teardown line in the
log and no driver fault report**, and the log's last line is an argument table made mid-frame. So the client is
stopped by a signal rather than quit, the game's own shutdown path does not run, and the frame encoder's
`close()` - the ring's completion wait, the deferred releases, the transient arena, the storage pipelines, the
residency set and now the queue - has no real-device evidence at all.

That is a gap in the migration's own lifecycle gate (section 71 lists "shutdown" among the observations), and it
is registered rather than papered over: what the teardown has is the ownership argument above and the pins that
hold it, and what it needs is a session that quits. Quitting the client needs input this machine's automation
permission refuses (`osascript` is denied with `-1743`), so the honest statement today is **shutdown: NOT
MEASURED**, and the next session that can be quit by hand closes it.

## What the ledger found

- **a leaked queue** (fixed): `Metal4FrameEncoder` asked the execution services for a queue, handed it to the
  ring, and released nothing. The Metal 3 encoder releases the one the same seam gives it, so the difference was
  visible only by reading the two teardowns side by side. Pinned now: the encoder keeps the queue and releases
  it after the ring.
- **the encoder-per-dispatch rule has a price in objects** (measured, not yet optimised): one encoder and one
  table per table-binding dispatch, both released through the slot's destruction queue. Pooling is a phase-21
  candidate under the rule the change came from - a table may be re-pointed between encoders but not within one
  - so a pool would have to be keyed by the dispatch's place in the frame rather than by the kernel.
- **nothing in the Metal 4 path is a process-global singleton** (section 106): the queue, the ring, the tables,
  the residency set, the storage pipelines and the compilation caches are all owned by the frame encoder or the
  execution state, so a second device in one process gets its own. The one static state left in the path is the
  probe's own (`MTL4Probe`, `MTLBuiltinPipelines`), which no session frame path uses.
