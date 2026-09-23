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
| `MTLArgumentEncoder` (one per descriptor set per stage, wide pipelines only) | `Metal4CompiledRenderPipeline.createArgumentBuffers`, from the stage's own function | the artifact | as long as the artifact, which is what makes the encoded length available to every pass that draws the pipeline | `Metal4CompiledRenderPipeline.close()`, with the two pipeline states |
| the render pipeline state's cached depth-stencil state | the compilation context (shared) | the compilation context | as long as the context | `Metal4ExecutionState.close()` - **not** by the artifact, which is why an artifact's `close()` does not touch it |

## The frame's objects

| object | made by | owner | lifetime | released by |
| --- | --- | --- | --- | --- |
| `MTL4RenderCommandEncoder` (one per pass) | `MTL4RenderEncoder.open` | the pass | the pass's | `Metal4RenderPass`/`Metal4FrameEncoder` closes it at the end of the pass |
| `MTL4ComputeCommandEncoder` (the copy encoder) | `MTL4FrameEncoder.copyEncoder()` | the frame encoder | one per frame, opened on demand and shared by copies, mip generations and feedback | `Metal4FrameEncoder.close()` |
| `MTL4ComputeCommandEncoder` (one per dispatch) | `Metal4FrameEncoder.dispatchEncoder` | the frame encoder | **one per table-binding dispatch**, ended where it is encoded | `endDispatchEncoder` files `close` on the slot's destruction queue |
| `MTL4ArgumentTable` (per dispatch, per clear) | `Metal4ComputePipeline.newTable`, `MTL4FrameEncoder.clearStorageTexture` | the frame encoder | one per dispatch and per clear - never re-pointed and handed over twice | `queueForDestroy(table::close)`, run when the slot completes |
| `MTL4ArgumentTable` (the present's) | `Metal4FrameEncoder.presentTable()` | the frame encoder | one per frame encoder | `Metal4FrameEncoder.close()` |
| `MTLBuffer` (the argument buffers, wide pipelines only) | `Metal4RenderPass.bindArgumentBuffer` | **the pass that fills it**, one per descriptor set per stage, made when a wide pipeline is set | the buffer is read when the frame's command buffer runs, which is after the pass has ended | `queueForDestroy(() -> ObjC.release(...))`, filed where it is made, so the slot's completion is the proof |
| `MTL4ResidencySet` | `Metal4FrameEncoder` (first `useResource`) | the frame encoder | the session's; committed and attached once | `Metal4FrameEncoder.close()` |
| `MTL4StorageTexturePipelines` (the zeroing kernels) | `Metal4FrameEncoder`'s constructor | the frame encoder | the encoder's | `Metal4FrameEncoder.close()` |
| `MTL4Compiler` (MetalFX's, this generation's) | `Metal4Fx.create` -> `MTL4Compiler.create` (`newCompilerWithDescriptor:error:`) | the `Metal4Fx` that asked for it | the path's; Metal 4's pipeline factories take one, and MetalFX's Metal 4 spelling is the first thing in this engine that needs it | `Metal4Fx.close()`, with the frame encoder |
| `MTL4FXSpatialScaler` (one per configuration) | `Metal4Fx.makeScaler`, through the descriptor's `newSpatialScalerWithDevice:compiler:` | the `Metal4Fx` that made it, which the frame encoder owns | the session's: a scaler compiles its own pipeline, so it is made once per configuration and reused, and a refused configuration is remembered as refused | `Metal4Fx.close()`, from `Metal4FrameEncoder.close()` |
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
encoder's own present is the one that runs by default. **And it is not started at all for a session that executes
Metal 4**, whatever the property says, because that session's present is the frame encoder's own and one session
must not hold two Metal 4 submission structures: the queue, the allocator ring, the command buffer, the shared
event and the commit-feedback registration in the rows above are made for a session whose *frame* is encoded by a
generation that does not present for itself - the reference shell - and that is the only configuration in which
they exist. Measured before the rule and after it: an `execution=metal4` launch with the property on started this
road once (and registered commit feedback once) while the frame encoder presented 1964 frames, and after the
change the same launch starts none of it and presents 2182, while an `execution=metal3` launch with the property
on still starts it exactly as before. Section 107 keeps the sidecar in place until the frame's own present is
real-device proven, and this ledger is where its objects are listed so the cleanup commit can be checked against
them rather than remembered.

## The teardown, which has now run - and what it found

Every row above says where an object is released, and for a long time **no session had run any of those lines**:
a forced Metal 4 session sent `SIGTERM` exited within thirty seconds with **no teardown line in the log and no
driver fault**, and the log's last line was an argument table made mid-frame - the client stopped by a signal
rather than quit, so the game's own shutdown path never ran.

That is closed, and by the gate rather than by hand: `com.metallum.mixin.render.LifecycleProbeMixin` sets the
window's **own close flag** (`GLFW.glfwSetWindowShouldClose`), which is what the close button sets, so the game
loop leaves on its own terms and the whole shutdown path runs - `Stopping!`, then the frame encoder's close, then
the cache release, then `BUILD SUCCESSFUL`. Driven by `tools/run-metal4-lifecycle-probe.sh`; **no input this
machine refuses is needed**, which was the only thing standing in the way.

**And the first run of it found a fault in the ledger's own subject.** The teardown waited for completion twice
around a close, and the second wait was on a ring the frame encoder had already released:

```text
Metal 4 frame encoder: closing - waited 0 ms for 3815 submission(s); complete=true,  ring state: submissions=3815 awaited=[3814, 3815, 3813]
Metal 4 frame encoder: waited  0 ms for 3815 submission(s); complete=false, ring state: submissions=3815 awaited=[0, 0, 0]
```

`awaited` at zeros with `signalled` unmoved is `MTL4FrameRing.close()`, which clears the slots' values and
releases the event; `waitUntilSignaledValue` against a released event returns immediately, so a completion that
had been proven 0 ms earlier was reported as a timeout that never arrived. It was a false alarm rather than a
stall, and no row above was violated - the destroys ran after a wait that had genuinely succeeded - but the wait
proved nothing, which is the thing this ledger exists to prevent. `MetalDevice.close()` no longer clears the
pipeline cache itself: `executionState.close()` clears the same caches at the end of the same method, after the
same wait. The order is pinned and mutation-proved in `ci-metal4.py`, together with the ring's
`describe()`, because a wait whose outcome is only printed on failure cannot say which of two waits on one ring
timed out.

What is still **NOT MEASURED** among the rows above is the *contended* case: every one of them ran with no work
in flight or with work that had long completed. Nothing here has seen the ring's completion wait actually block,
because a display-paced session has no backlog to wait on.

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
  the residency set, the storage pipelines, the MetalFX compiler and its scalers, and the compilation caches are
  all owned by the frame encoder or the execution state, so a second device in one process gets its own. The one
  static state left in the path is the probe's own (`MTL4Probe`, `MTLBuiltinPipelines`), which no session frame
  path uses. **The MetalFX capability answer is the one static that is deliberate**: `Metal4Fx.supported` is asked
  once per process because it is a property of the device and the system, and it is the answer a *selection* reads
  before any frame encoder exists - but the objects that answer it are made and released inside the question, and
  nothing a frame uses is held there.
- **the Metal 3 and Metal 4 scaler caches share a key and nothing else** (section 80): `MetalFx.scalers` holds
  `MTLFXSpatialScaler` objects and `Metal4Fx.scalers` holds `MTL4FXSpatialScaler` ones, keyed by the same five
  facts plus the colour processing mode because those are the facts that make a different scaler - not because the
  object is interchangeable. It is not: the two are different protocols with different factories and different
  encodes, and a shared cache would have handed one generation's compiled pipeline to the other.
- **a teardown waited twice around a close, and the second wait was on a released ring** (fixed): see the
  section above. It is a ledger finding and not only a bug - the second wait was inside a cache clear that
  `executionState.close()` performs anyway, so the fix was a deletion, and the ownership question it raised ("who
  proves completion before the caches are freed?") has one answer instead of two.
- **the wide path splits one object's lifetime across two owners, deliberately** (added with the argument-buffer
  binding path): the `MTLArgumentEncoder` belongs to the artifact, because the encoded length is the shader's own
  layout and every pass that draws the pipeline needs it; the `MTLBuffer` it writes belongs to the pass, because
  the pass's bindings are its contents. The pass drops its map when the pipeline's artifact changes - a buffer
  made for another layout is the wrong length - and does not close the buffers there, because at that moment the
  GPU may still be reading them; they are filed with the frame where they are made. The artifact releases the
  encoders with its pipeline states, which is why an artifact's `close()` now touches two kinds of object. Both
  rows are one real-device reading deep: `deferred4` is the only wide pipeline the ladder has.
