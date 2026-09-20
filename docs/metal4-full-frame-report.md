# Metal 4 full-frame migration  -  status report

The plan's milestone order, one row per milestone, kept current as each one is measured. A milestone that has
not been attempted says so; nothing here is written as "probably works", and a claim is only made against a
device that was really run.

    PROVEN        measured on this machine, with the evidence named
    NOT PROVEN    attempted or reachable, no evidence yet
    EXPERIMENTAL  runs, but is not the production path and must not be AUTO-selected
    BLOCKED       stopped on a named condition
    NOT STARTED   not attempted

## Starting SHAs

```
Metallum: e55985e  STARTING_METALLUM_SHA, two commits past the plan's own reference 81b3426 -
                    e55985e (the byte unit, the submission-index window, the tail test) then 868d5b5
                    (the same two wordings). Both are Metal 3 bookkeeping and neither is a Metal 4 change.
                    The first Metal 4 commit after this line is 050d1dd, the cold-probe harness.
Vitrail:  4380250f  (perf/optimisation; exactly the plan's reference)
```

Every structure the plan names was checked against this checkout before anything was measured:
`MTL4Probe` (with `lastFailureStage()`/`lastFailure()`), `MetalDeviceCapabilities.probe` and its
`metal4MinimumContract()`, `Metal4.available`/`canMakeAndSubmit`/`canBindAndDraw`, `Metal4Path`,
`Metal4PresentGate`, `MetalExecutionTelemetry`'s selected/executing pair, `MetalFx.metal4SpatialSupported`,
and the two rings `MAX_SUBMITS_IN_FLIGHT` drives.

## Cold Probe

```
harness:          tools/metal4-cold-probe.sh  (tools/metal4-cold-probe/Metal4ColdProbe.java)
what it does:     create device -> run the probe once -> one machine-readable line -> exit
                  no Minecraft, no world, no pack, no window, no frame
cost a probe:     about 220-270 ms of probing in a ~305 ms process in this round's runs (240-460 ms in the
                  earlier ones, taken on a differently loaded machine and with less work in the probe);
                  about 9 ms for the second and later probe in one process
                  against the client's ~70 s per arm, which is what made this measurable

cold runs:        160 processes, 1260 probes (50 + 50 + 60, the last with 20 probes each)
                  failures: 4, every one of them at ATTEMPT 1 of its process
warm probes:      500 in three processes      failures: 0
this round:       50 probes (30 cold + 20 warm, `--mode raw`) with 0 failures. All twelve device smokes
                  passed in every one of them - the drawn sampled texture, the allocator-slot ring, the four
                  colour attachments, the bound layout, the texture copies, the depth clear, the fence wait,
                  the indexed draw and the new **residency set** - and the compilation chain compiled a
                  pipeline in every process (`compile=ok(valid=true)`). The residency smoke is the new one:
                  a set is made, two allocations (a buffer and a texture) go in, it commits and requests
                  residency, it reports two allocations, and the queue answers `addResidencySet:` (50 of 50) -
                  and it is the model the frame path's own run proved necessary, since without those
                  declarations the GPU faulted and with them it renders terrain. The fence wait and the depth clear are the round before it: two empty frames with
                  both committed values waited for, the next value polling false and refused by name for a
                  wait; and a colour target beside a `Depth32Float` target cleared to 0.25 and read back
                  (both 50 of 50). The bound
                  layout smoke still builds its tables from the production `Metal4BindingPlan`, so the plan
                  itself is what those 50 probes measured. The pass object is still NOT reachable here - it
                  needs the engine's device and real texture views - so its evidence remains the structural
                  contract plus the measured layers underneath (the attachment smoke's own evidence: 50 of 50
                  in the round that added it; the ring's: 56 of 56; the drawn smoke's: 100 of 100). Cold
                  processes this round: 517-1075 ms wall, 340-386 ms of probing in them; warm probes 23-34 ms
rate:             4 of 160 first probes = 2.5 %;  0 of 1100 later probes,  0 of 500 warm probes
within-process control:  process 47 failed attempt 1 and passed attempts 2 to 20
uniform pass:     0 failures in all 500 attempts, and this round is the first time it was checked at all
fix:              MTL4Probe.canBindAndDrawPersistently - one more attempt where the first answer is no,
                  with the first attempt's stage and reason logged either way. Metal4.available reads it,
                  so the capability record reports the device and not the first command buffer. Both halves
                  are pinned and mutation-proven.
verified:         production path, 130 cold processes: 0 failures, and ONE of them shows the retry
                  firing - process 128, `retried=true success=true stage=ok` - so the first attempt failed,
                  the second answered, and the capability record reported true
                  (earlier: production 40 cold + 20 warm clean; raw 40 cold + 20 warm clean)
still open:       the CAUSE. What makes a process's first multi-encoder sequence able to lose its second
                  pass while every later sequence in the same process is sound is a hypothesis, so
                  section 14's Path A is not closed as such; the AUTO blocker's behaviour is
AUTO blocker:     MITIGATED on the capability-record path, and AUTO stays blocked on what section 74 lists:
                  there is no Metal 4 full-frame implementation for it to promote. Forced Metal 4
                  development continues.
```

**What a failure now says.** Every failure reads stage `pixel` and

```
reason=the vertex-buffer pass drew (0, 0, 0, 0) where (64, 128, 128, 255) was asked for
canMakeAndSubmit=true  canBindAndDraw=false
familyMetal4=true  queueSelector=true  argumentTableSelector=true
```

(0, 0, 0, 0) is neither the vertex colour nor the clear colour the second pass asked for: it is the second
target **exactly as it was created**, so the second render pass contributed nothing at all - not its draw and
not its clear - while the first pass's own check passed in the same attempt on its own target through the same
table mechanism. That is a narrower statement than the one this report carried last round ("the readback
returned the first pass's pixel, so the second pass's geometry rasterised nothing"), and it is narrower
because the probe now asks a better question.

**Why the probe had to change to ask it.** It drew pass one and read the pixel back only after pass two, with
`LOAD_DONT_CARE` on both, so a missed draw left undefined tile memory and 191 was one of the values the API
permits it to return; and `EXPECTED_UNIFORM_PIXEL` was declared and compared nowhere, so the uniform pass - the
one that proves a uniform bound by GPU address reaches a draw - was never checked at all. Each pass now has its
own target, the second is cleared to a known colour, and both pixels are read. That is the plan's own Smoke 5
shape, and it is why the first pass has 500 attempts of evidence behind it today and none yesterday.

**It is the first probe in a process, and that is now measured rather than suspected.** The harness was given
`--probes-per-process K` so that a bad process and a bad draw could be told apart, and the answer is neither:
sixty cold processes ran twenty probes each and the one failure was attempt 1 of a process whose attempts 2 to
20 all passed - same process, same device, milliseconds later. Every failure in every run has been at attempt
1; none has ever been at a later attempt. So the fault is **first-probe-in-a-process**, not a per-process state
and not a per-draw event.

**Not a capability gap** - every selector answers true in every failure - **and not a timeout**: probe times
were ordinary (227, 362, 438, 326 and 463 ms). What is left is something about the first command buffer a
process submits, which can drop the second render encoder's entire contribution, in about one cold first probe
in twenty-five. Lazy driver initialisation on first use is the candidate that fits and is recorded as a
hypothesis; the experiment that would settle it is a first probe with a throwaway commit before the real
sequence, or a first probe that runs only the first pass. Either result is a fix in the probe's warm-up rather
than in the frame path, and neither has been run yet.

**Rates are not comparable across the two rounds**, because the probe's shape changed between them: round two
measured 1 of 50 cold and 1 of 20 warm with a one-target probe, and the sentence in this report that read that
as "equally frequent cold and warm" is withdrawn.

## Native Smoke

```
colour:           PROVEN as part of canBindAndDraw's first pass - a table-bound uniform draws
                  (0.25, 0.5, 0.75, 1.0) into a 64x64 RGBA8 target and the pixel is read back as
                  (64, 128, 191, 255), channel by channel. Verified separately since the two-target
                  rework, so a failure of this pass is now reported as this pass.
uniform:          PROVEN by the same pass and the same readback - the colour comes from
                  setAddress:atIndex: with no buffer offset, and the value read is the value written
vertex:           PROVEN by the second pass - a vertex buffer bound by GPU address *and* stride 16,
                  drawn by a pipeline whose colour comes out of that buffer, read back as
                  (64, 128, 128, 255). Its channel 2 is a literal in the shader, which is what makes a
                  readback of 191 (the first pass's colour) proof that this pass covered nothing
texture/sampler:  HALF PROVEN. A table made for exactly one texture and one sampler accepts both
                  (`canBindSampledTexture`: create a 4x4 RGBA8 shared texture, a nearest sampler with
                  supportArgumentBuffers, a table of shape (0 buffers, 1 texture, 1 sampler), then
                  setTexture:atIndex: and setSamplerState:atIndex:), measured on Apple Silicon in
                  45 of 45 attempts across 25 cold processes and 20 warm probes, with every call's
                  refusal reported by name
                  DRAWN TOO now, by `canDrawSampledTexture`: a pattern pass renders four flat quadrants
                  into a 64x64 source that declares RenderTarget | ShaderRead, the pass ends with the
                  producer barrier the new command model requires of a dependency between encoders, and a
                  second pass in the SAME command buffer samples that source through a one-texture/
                  one-sampler table at the fragment stage into a target of its own; one commit, one
                  shared-event wait, then both textures are read back at a pixel inside each quadrant.
                  Measured on Apple Silicon: 100 of 100 probes PASS (30 cold + 20 warm in `--mode raw`,
                  30 cold + 20 warm in `--mode production`), capability sequence passing in all of them
multi-pass:       PROVEN and now the probe's own shape - two render encoders in one command buffer,
                  each into a target of its own (pass A into target A, pass B into target B), one
                  commit, one shared-event wait, both pixels read back
```

**How the drawn half answers, and why the answer can fail.** Both textures are read at the same four pixels,
one well inside each quadrant, so the source says whether the pattern landed and the destination says whether
the sample arrived - a pattern that never rendered is reported as that and not as a sample failure. The check
is not vacuous: with the destination readback transposed (a one-character mutation of the read region), the
harness reports

```
sampledDraw=false sampledDrawReason=sampledDraw(the_sampled_pass_read_the_pattern's_bottom-left_colour_
(0,_255,_64,_255)_at_(40,_8)_where_its_top-right_(255,_0,_64,_255)_was_asked_for,_so_the_sample_reached_
the_wrong_place_in_the_source)
```

and the driver exits 1 on it, which is the half of the harness that says a failing smoke cannot report
success. **What it does not prove**: filtering beyond nearest - nothing here binds linear, aniso, mip levels
or an address mode - and that the barrier is what ordered the two passes. The readback is correct with the
barrier encoded; whether this device would also have ordered them without one is NOT MEASURED, because the
API contract for the new command model requires the barrier and the migration's own rule is to express a
dependency before optimising it. The capability record also does not consume this smoke yet:
`Metal4.available` still reads `canBindAndDrawPersistently`, so the AUTO-blocker distribution measured on that
path across 160 processes stays comparable. It is wired into the record when a Metal 4 frame path exists to
need it.

## M4 Frame

```
provider:            PROVEN as a skeleton - Metal4ExecutionProvider implements the neutral
                     MetalExecutionProvider, its queue factory is real on this device
                     (`newMTL4CommandQueue` returns a non-nil queue), and its state is a real object whose
                     four operations answer on the real device:
                     `queue=ok,state=ok,stateMethods=compile:refused(getOrCompilePipeline),
                     evict:returned,clear:returned,close:returned,encoder=not-asked(needs-the-engine-device)`
                     - measured in the cold-probe harness, per process, on Apple Silicon, identical in 53 of
                     53 probes. The encoder is not asked there and the line says why: it is built from the
                     engine's device, which a bare process cannot make
frame encoder:       EXISTS and is entered - `render.metal4.Metal4FrameEncoder` implements the neutral
                     `MetalFrameEncoder`, owns the frame's ring (allocators, one command buffer, one shared
                     event), files every deferred release against a ring slot and runs it only once that
                     slot's completion has been observed, and `createRenderPass`/`submitRenderPass` build a
                     real pass from the game's descriptor (a forced Metal 4 client launch has run this far).
                     It also owns the copies: a `MetalTransientMemory` on the frame's own rotation, a
                     `MTL4ComputeEncoder` opened on demand, and `writeToBuffer`/`writeToTexture`/
                     `copyBufferToTexture`/`copyTextureToBuffer`/`copyTextureToTexture`/`transientMemory`
                     implemented over them. It also owns the clears: `clearColorTexture`, the unscissored
                     `clearColorAndDepthTextures` and `clearDepthTexture` each open a pass of their own over
                     the attachment they clear, ordered against any copy the frame encoded first and closed
                     with the producer barrier (Render below says why a pass, and what it costs).
                     It also owns the fence: `createFence` returns a `Metal4Fence`, a promise about one of
                     the ring's submissions, waited for on the ring's own shared event with the three answers
                     the Metal 3 fence gives (see Synchronization below).
                     It is also what presents: `presentTextureToDrawable` takes the layer's next drawable,
                     registers it with the queue before the commit, draws the engine's present triangle into
                     it inside this frame's command buffer, and `submit()` signals and presents it after the
                     commit. MEASURED: a forced Metal 4 launch encodes and presents its own frames - the
                     loading screen came up through this path for more than thirty frames - and then **hangs
                     the GPU on the first frame of the loaded world** (kernel `GPURestart`; see Remaining
                     blockers). What still refuses by name: the scissored `clearColorAndDepthTextures` and
                     writeTimestamp - two names.
                     NOT PROVEN: no frame has been submitted through it; its evidence is the ring's device
                     proof plus a structural contract
state:               PROVEN on the device - `Metal4ExecutionState` owns this generation's
                     compilation state (SPIR-V modules, native functions, depth-stencil states, compiled
                     artifacts) and `getOrCompilePipeline` compiles through `Metal4PipelineCompiler`: the
                     game's GLSL compiler, the SHARED SPIR-V-to-MSL translator, and this generation's own
                     native pipeline states. It asks the translator for DIRECT bindings and refuses an
                     argument-buffer layout, because Metal 4 binds through tables. Evicted or replaced
                     artifacts are filed and released only in `clearCachesAfterGpuCompletion`, whose contract
                     says GPU completion has been established. MEASURED: the cold-probe harness builds its own
                     pipeline description and GLSL source and compiles them through the chain - 50 of 50
                     probes answered `compile=ok(valid=true)` in 30 cold processes and 20 warm repeats, which
                     is the whole chain (game GLSL compiler, shared translator, this generation's native
                     pipeline state) in a process with no window in it
reached by:          the services hand out the provider of the EXECUTING generation, and what executes is
                     decided from the launch's preference: AUTO still executes Metal 3 with referenceShell
                     true (the readiness gate of section 74), and a launch that asks for
                     `-Dmetallum.execution=metal4` executes Metal 4 and says so once at warn. MEASURED: a
                     forced Metal 4 client launch really did execute Metal 4 -
                     `selectedGeneration=metal4 executingGeneration=metal4 mode=own-path referenceShell=false
                     framePathReady=true`, with the shader profile switched to msl4.0 - and stopped at the
                     first operation the new path does not encode:
                     `Unimplemented: writeToTexture`, raised from
                     `DynamicTexture.upload -> TextureManager.<init> -> Minecraft.<init>`. That is a startup
                     upload rather than a frame: the next Metal 4 milestone is the texture write/copy path
                     (sections 54-55), which the client needs before any draw.
queue:               PROVEN for the provider skeleton; no frame is submitted through it yet
allocators:          PROVEN as a rule, before any encoder was built over it - `MTL4FrameRing` owns three
                     slots, one command buffer and one shared event, and a slot is reset only after the value
                     its own commit signalled has been observed. Measured on Apple Silicon with
                     `MTL4Probe.canReuseAllocatorSlots`: twelve frames over three slots, every slot reset and
                     re-begun twice over, the ring's wait count asserted against its own depth (9 of 12
                     begins), and all twelve frames' pixels exact - 56 of 56 probes in two runs (3 cold + 3
                     warm, then 30 cold + 20 warm, `--mode raw`). The rule is load-bearing and not a
                     formality: with the completion wait removed, frame 0's pass never landed in five of five
                     probes, and the harness reports `frame 0 drew (0, 0, 0, 0) where (16, 0, 0, 255) was
                     asked for`. No frame uses the ring yet: the encoder that will is Phase 4's remaining
                     half
command buffers/frame: one, re-begun per frame - the shape the ring proof submits (12 begins, 12 commits)
render passes:       PROVEN as an object and NOT run: `createRenderPass` builds `Metal4RenderPass` from the
                     game's descriptor - attachments resolved, extent and render area checked, the pass
                     opened through the layer whose attachment mapping is measured on the device (50 of 50
                     probes), and the frame begun on the first pass so that slot's releases can run. Every
                     bind and draw refuses by name; the debug group is a no-op. It cannot run in the
                     cold-probe harness (it needs the engine's device and real texture views), so its
                     evidence is the structural contract and the measured layer under it - no pass has been
                     encoded inside a client frame yet
commits/frame:       one, PROVEN in the ring proof and the plan's own target (section 30); no frame yet
frame probe:         FED by the full-frame path - the frame boundary that opens the probe's window, the encoders
                     it opens by kind, every attachment with its pixel size and load/store, every binding, the
                     scissor, each texture copy as a blit, each present, the ring's slot-reuse wait and the
                     queue's own per-frame GPU time from its commit feedback. MEASURED: the standard harness now
                     collects a forced Metal 4 run, and the first one showed the Metal 4 GPU samples had no
                     percentile path (a gpuM4Ms total with every gpuP* at zero), which is now fixed with
                     gpuM4P50/P95/P99/Max
presentation:        IMPLEMENTED by the frame encoder and OBSERVED ON SCREEN - Metal4FrameEncoder implements
                     MetalFramePresentation: the picture is drawn into the layer's next drawable by the engine's
                     present triangle, encoded into the frame's own command buffer before its one commit, with
                     waitForDrawable: before that commit and signalDrawable: + present after it. A forced Metal 4
                     launch presented its loading screen for more than thirty frames. BLOCKED after that: the
                     first frame of the loaded world hangs the GPU (kernel GPURestart, see Remaining blockers).
                     The present-only sidecar (Metal4Path + Metal4PresentGate) stays in place, and is the control
                     that shows the drawable road itself is sound on this machine
```

## Render

```
basic:   PARTLY - the pass exists end to end: `createRenderPass` resolves the game's descriptor into
         `Metal4RenderPass`, opens it through `MTL4RenderEncoder` (attachments, load/store actions, clear
         colours, target size, the producer barrier between passes), and ends it on `submitRenderPass`.
         The attachment half is measured on the device (50 of 50 probes), the binding plan and the encoder's
         draw commands are measured on the device (the layout smoke), and the pass now implements the no-pack
         binding subset: setPipeline compiles through this generation and builds the plan, the bind calls fill
         plan-sized tables and refuse a name the pipeline does not declare, the vertex buffer is bound with the
         pipeline's own stride, setIndexBuffer is an address the draw offsets, the scissor is set and cleared,
         and draw/drawIndexed assign the tables, set the state and draw. The pass object is still NOT run
         (it needs the engine's device), and the multi-draw, indirect and timestamp forms still refuse by name
MRT:     PROVEN for the pass's half, and only that half - one pass carries four colour attachments cleared
         to red, green, blue and white and each slot is read back against the colour that slot was asked
         for; a second pass loads slot 0's existing contents and re-clears slot 1, so the load, the clear
         on a reused attachment and the store across a pass boundary are all measured. What is NOT proven
         is a pipeline writing several targets at once: no draw is encoded yet
clear:   PROVEN as a pass of its own, and it is a decision with a cost. On this API a clear is a **load
         action**, and a load action belongs to a pass, so `Metal4FrameEncoder.clearColorTexture`,
         `clearColorAndDepthTextures` (unscissored) and `clearDepthTexture` each open a one-attachment pass
         that loads cleared and stores, with no draw in it - the honest first version while the question is
         whether the path runs at all. Metal 3's encoder records the clear and folds it into the next pass
         that uses the attachment, which is cheaper (no extra pass, and the attachment is never loaded) and
         is a lifetime model of its own; that is a later optimisation, not a correctness gap, and it is not
         claimed to be free. The clear's pass ends with the producer barrier, and it is opened only after
         any copy the frame encoded is ordered, so the clear cannot land before what it overwrites
depth:   PARTLY - the descriptor path takes a depth attachment and its clear, and a smoke now proves the
         load action itself: a colour target and a `Depth32Float` target in one pass, the depth cleared to
         0.25, read back through `MTLTexture.bytes` and compared (50 of 50 probes). What is NOT proven is a
         draw that tests or writes depth - no pipeline is bound with a depth-stencil state yet
blend:   NOT STARTED
scissor: PARTLY - the pass's own scissor is set, cleared and measured on the device through the layout
         smoke (a pixel inside the rectangle and a pixel outside it), but the scissored form of
         `clearColorAndDepthTextures` still refuses by name, because clearing part of an attachment is a
         load action that only holds for the whole attachment
```

## Resource Binding

```
textures:         PROVEN as a layout on the device AND implemented in the pass - the layout smoke binds a
                  texture through a table at the slot its shader declares and reads the sampled colour back;
                  the pass records a texture and its sampler by name and resolves them into the table the
                  pipeline's plan sizes, whether the pipeline was set before or after the binding
samplers:         PROVEN as a layout on the device, and implemented in the pass beside the texture it is used
                  with - one sampler at the slot the shader declares
uniform buffers:  PROVEN as a layout on the device AND implemented in the pass - two uniforms on two stages (a
                  vertex-stage tint and a fragment-stage bias), each at its own buffer index, each changing the
                  readback; the pass records a GPU address by name, which is what makes the game's
                  `bindDefaultUniforms`-before-`setPipeline` order work
vertex/index:     vertex PROVEN on the device (address + attribute stride through a table, drawn, read back)
                  and implemented in the pass by slot; **index PROVEN on the device** - two covering triangles
                  of different flat colour and one six-entry UInt16 index buffer, drawn at index 0 and at
                  index 3 through the production encoder's `drawIndexedPrimitives`, each read back against its
                  own triangle (50 of 50), and implemented in the pass as an address the draw offsets
argument tables:  PROVEN - two tables in one pass, one per stage, sized to what that stage binds, assigned with
                  setArgumentTable:atStages:, and the draw reads every slot
residency:        PROVEN AND REQUIRED - the frame encoder owns one `MTL4ResidencySet` and declares every
                  resource the frame binds by address or id (attachments, sampled textures, uniforms, vertex
                  layouts, index buffers, the copies' staging blocks and textures); the set is committed and
                  requested each frame and handed to the queue once. Measured: with it, no GPU fault; without
                  it, a kernel `GPURestart` and `MTL4CommandQueueErrorTimeout` within two seconds. Device smoke:
                  50 of 50 cold-probe processes (30 cold + 20 warm). NOT the per-resource READ/WRITE/SAMPLE facts
                  sections 52 to 53 ask for - this first version declares everything a frame touches
```

## Blit

```
full:   PROVEN as a native smoke and wired INTO the frame encoder - `MTL4ComputeEncoder.copyTextureToTexture`
        copies a 64x64 four-quadrant pattern into a second texture and every quadrant is read back (50 of 50
        probes); `Metal4FrameEncoder.copyTextureToTexture` is the engine's own form of it, and the client has
        walked past the uploads that use the other copies. NOT through a frame: no live frame has encoded one
region: PROVEN as a native smoke and wired INTO the frame encoder - a 32x32 region at the origin is copied
        into the destination's other half, and both a pixel inside where it landed and a pixel outside it are
        read (the first is the source's top-left quadrant, the second is still the clear). The engine's
        `copyBufferToTexture`/`copyTextureToBuffer`/`writeToTexture` are implemented over the same encoder
mipmap: NOT STARTED - no mip chain has been copied on the new path
```

## Compute

```
dispatch:       NOT STARTED
SSBO:           NOT STARTED
storage image:  NOT STARTED
render->compute: NOT STARTED
compute->render: NOT STARTED
```

## Synchronization

```
fence:    PROVEN on the device - `MTL4Probe.canAwaitSubmissions` submits two empty frames on a ring and checks
          the whole contract of a fence: a committed submission's value is waited for on the shared event, the
          value no commit has promised polls false, asking to **wait** for it is refused by name (the same
          refusal the Metal 3 fence gives for the submit it is recording), and a value of zero - nothing
          submitted - is complete. 50 of 50 probes (30 cold + 20 warm, `--mode raw`). This is the object
          `MappableRingBuffer` (await before a CPU write) and `StagedVertexBuffer`'s pool (poll before
          recycling) are built on; both call sites' behaviour was read off the client's own bytecode
fence in a frame: MEASURED as far as the client reaches - a forced Metal 4 launch creates a fence from
          `MappableRingBuffer.rotate`, inside `FogRenderer.endFrame`, and the run walks past it into the drawn
          frame; no fence has yet been observed completing and then gating a CPU write in a live client
          (that needs the client to run more than three frames, which it does not get to yet)
matrix:   NOT STARTED - the read/write dependency matrix the plan's section 60 lists
```

The probe's own ordering (two render encoders in one command buffer, one commit, one shared-event wait) is
exercised on every attempt and has never failed at `commit`, `completion` or `encoder`.

## Lifecycle

```
F3+T:       NOT STARTED
pack switch: NOT STARTED
world join: NOT STARTED
dimension:  NOT STARTED
resize:     NOT STARTED
fullscreen: NOT STARTED
shutdown:   NOT STARTED
```

Every one of these is measured with the Metal 3 path today (`docs/metal3-performance-report.md`), and none has
been run against a Metal 4 frame, because no Metal 4 frame exists yet.

## MetalFX Spatial

```
supported:            PROVEN for Metal 3, and the Metal 4 factory capability is probed
                      (MetalFx.metal4SpatialSupported) - no Metal 4 scaler path is implemented
configuration cache:  Metal 3 only
M3 result:            PROVEN (one scaler per configuration, cached, fallback-safe)
M4 result:            NOT STARTED
performance:          NOT STARTED
```

## Performance

**The two generations have now been run against each other, in one session, on the same world at the same size:**

```text
m3: 8.06 ms a frame, 124.1 frames a second, 4.94 ms of GPU time a frame over 30 answered frames
m4: 8.08 ms a frame, 123.8 frames a second, +0.2% against m3

picture, m3 against m4: mean channel difference 0.00, 0.00% of pixels differ at all,
                        0.00% differ by more than 8, 0.00% differ by more than 2, worst 0 at 0,0
```

**The no-pack frame is the same picture on both generations, and byte-identically so**: the two arms' screenshots
hash to the same SHA-256 (`e9a46318...56519`), and the harness's own comparison reports zero pixels differing.
That is this migration's success criterion measured rather than intended, and it covers the present road as well
as the render path. **The pace is the same and it is the display's**: about 7.4 ms
of each 8.06/8.08 ms frame is the drawable wait, so this scene is display-paced and cannot separate the two.
**The GPU numbers are recorded but not compared**: `gpuP50 4.92 ms` is `MTLCommandBuffer.gpuMillis` and
`gpuM4P50 2.04 ms` is `MTL4CommitFeedback.GPUStartTime/GPUEndTime` - two different APIs, and section 92's rule is
that the timing kinds are not interchangeable until that is established. **The structural differences are the
migration's own mechanisms** (render passes 120 → 360, clear encoders 0 → 150, pipeline binds 460 → 1920,
attachment bytes loaded 950.3 MiB → 9387.8 MiB, stored 2637.8 → 9387.8) with the shader programs identical
(`pipelineIdentities 100` both arms); the load traffic is the one real inefficiency the comparison names, because
every attachment here is `CARRIED` (load and store) - the Metal 3 pass's per-attachment contents facts do not
reach this path yet, and that is the next thing to give it.

The Metal 3 reference on the pinned scene is
`wallP50 7.25-7.26 ms`, `gpuP50 7.28-7.29`, `gpuMs 4366.72 / 4368.05` over two arms of
`run/m3-final`, and it is the baseline any Metal 4 frame will be read against - always with
`--fullscreen-size` and `--expect-target` set, and with nothing else running on the machine.

## Capability matrix

Every cell is a measurement or an explicit absence. `M4 smoke` means proven in a process with no window in it
(the cold-probe harness); `M4 real frame` means through a frame the client drew, which does not exist yet and is
therefore `n/a` everywhere; `Real-device` means the same run was on this machine's Apple Silicon rather than in
CI, which is where every smoke here was run.

| Capability      | M3          | M4 smoke                          | M4 real frame | Real-device |
| --------------- | ----------- | --------------------------------- | ------------- | ----------- |
| render          | yes         | yes - `canMakeAndSubmit` encodes and submits a render pass on a 64x64 target | yes - the no-pack world frame renders (9,000+ frames, no fault, 300 fps, 15 passes and 34 draws a frame), measured by the path's own counters; the picture has not been compared with Metal 3's | yes |
| MRT             | yes         | **pass half** - four colour attachments in one pass, cleared per slot and read back slot by slot; no draw writes more than one target yet | n/a | yes |
| clear           | yes         | yes - colour, colour+depth and depth-only clears each encoded as a pass of their own (a load action needs a pass on this API, where Metal 3 folds the clear into the next pass) | n/a | yes |
| depth           | yes         | **clear half** - a `Depth32Float` attachment cleared to 0.25 in a pass of its own and read back; no depth-stencil state has been bound to a draw | n/a | yes |
| sampled texture | yes         | yes - a table-bound source is sampled by a pass and the result is read back, one pixel inside each of the pattern's four quadrants; and a whole layout's texture is sampled at the slot its shader declares | n/a | yes |
| sampler         | yes         | yes - a nearest sampler with `supportArgumentBuffers` is made, bound and sampled through | n/a | yes |
| uniform         | yes         | yes - `setAddress:atIndex:` then a draw, read back (64, 128, 191, 255); and two uniforms on two stages at their own buffer indices, each changing a channel of the layout smoke's pixel | n/a | yes |
| vertex/index    | yes         | vertex yes - address + stride 16, colour out of the buffer, read back (64, 128, 128, 255), and a second vertex buffer bound with its stride inside a whole layout; index yes - see the indexed-draw row | n/a | yes |
| argument table  | n/a (M3 uses argument buffers) | yes - two tables in one pass, one per stage, sized to what each stage binds, assigned with setArgumentTable:atStages:, with a draw reading every slot | n/a | yes |
| indexed draw    | yes         | yes - an index buffer as an address in the draw, six UInt16 indices, drawn at index 0 and at index 3 with each frame read back against its own triangle; the selector is the eight-argument one this SDK declares | n/a | yes |
| indirect draw   | yes         | yes - the indirect indexed form, one command per draw with `MTLDrawIndexedPrimitivesIndirectArguments` (twenty bytes) in a buffer the GPU reads and the frame path declares resident; the arguments' own `indexStart` selects which of two triangles is drawn, so arguments that are ignored draw the first one twice (50 of 50) | n/a | yes |
| residency       | yes         | yes - a `MTL4ResidencySet` takes allocations, commits, requests residency and is handed to the queue; and in the frame path it is what keeps the addresses the frame binds alive, measured as the difference between a GPU fault and a world frame | yes - the forced Metal 4 launch renders terrain with no `GPURestart` | yes |
| blit            | yes         | yes - whole and region texture copies measured on the device, and the engine's own `writeToBuffer`/`writeToTexture`/`copyBufferToTexture`/`copyTextureToBuffer`/`copyTextureToTexture` implemented over the same compute encoder (the client walked past its texture-manager upload); none encoded inside a live frame yet | n/a | yes |
| mipmap          | yes         | no                                | n/a           | no          |
| compute         | yes         | no                                | n/a           | no          |
| storage buffer  | yes         | no                                | n/a           | no          |
| storage image   | yes         | no                                | n/a           | no          |
| synchronization | yes         | **partly** - two encoders in one command buffer, one commit, one shared-event wait, both pixels read; one cross-encoder dependency fixture (a render pass that samples what the pass before it wrote, with the producer barrier encoded between them); and fences, see the next row - but not the read/write matrix the plan's section 60 lists | n/a | yes |
| fence           | yes         | yes - a submission's value can be waited for on the ring's shared event, an uncommitted value polls false and is refused for a wait, and zero is complete; measured 50 of 50, and created by a forced client run from `MappableRingBuffer.rotate` | n/a | yes |
| presentation    | yes         | **implemented in the frame encoder**: take the drawable, `waitForDrawable:` before the commit, the present triangle in the frame's own command buffer, `signalDrawable:` + present after it | loading screen yes (30+ frames on screen); the world frame hangs the GPU | yes |
| MetalFX spatial | yes         | no - the Metal 4 factory capability is probed, no scaler path is implemented | n/a | no          |
| counters        | whole frame | no                                | n/a           | no          |

**What the matrix is for here**: it is the list a reader checks before believing any claim about the migration,
and its blanks are the work. Nothing in the `M4 real frame` column can be filled until a Metal 4 frame encoder
exists, which is Phase 4; and nothing in it should be filled from a smoke, because a capability proven in a
process with no window is not the same claim as a capability proven through the client's own frame.

## Remaining blockers

The list is current, and fixed items are kept as one-line records so a reader can see what the migration already
answered rather than only what is left.

0. ~~The world frame hung the GPU~~ - **fixed**: an argument table's bindings are not initialised unless you ask
   (`MTL4ArgumentTable.h`: `initializeBindings` defaults to **false**), so a slot this path never fills - and this
   path skips a binding by design where a layout declares it as the other kind of resource - held undefined data,
   and the first frame that drew the clouds read one. Tables are created with their bindings initialised to nil.
   MEASURED: a forced Metal 4 launch loads a world and renders it for nine thousand frames with no fault, no
   `GPURestart` and no refusal.
1. ~~The frame probe was fed by Metal 3 only~~ - **fixed**: the full-frame path reports the frame boundary that
   opens the probe's window, its encoders by kind, every attachment with its pixel size and load/store, every
   binding, the scissor, its texture copies as blits, its presents, the ring's slot-reuse wait and the queue's
   own per-frame GPU time from its commit feedback. The first collected run also exposed that the Metal 4 GPU
   samples had no percentile path (a `gpuM4Ms` total with every `gpuP*` at zero); they have their own
   `gpuM4P50/P95/P99/Max` now.
2. ~~The comparison had not been run~~ - **run**: both arms in one session, same world and size. The picture is
   identical (`0.00% of pixels differ`), the pace is identical (8.06 against 8.08 ms a frame, +0.2%) and it is
   the display's (drawable wait ~7.4 ms of each). What that leaves open is a scene that is *not* display-paced,
   and the two GPU numbers are recorded but not compared because they come from different APIs
   (`MTLCommandBuffer.gpuMillis` against `MTL4CommitFeedback.GPUStartTime/GPUEndTime`) - section 92's timing
   kinds have not been shown to measure the same interval.
3. **The attachment traffic is the one measured inefficiency** - this path loads 9387.8 MiB and stores 9387.8 MiB
   over thirty frames where the Metal 3 arm loads 950.3 and stores 2637.8 on the same scene, because every
   attachment here is `CARRIED` (load and store) and the per-attachment contents facts the Metal 3 pass carries
   do not reach this path yet. Measured on both sides now, and the next thing to give this path.
4. **The intermittent capability-probe failure** - 2 of 70, stage `pixel`, two surviving hypotheses. Blocks
   AUTO, does not block implementation.
5. **What still refuses by name** - the scissored `clearColorAndDepthTextures` (a partial clear is a draw over a
   rectangle, not a load action) and `writeTimestamp` (the counter path, which the plan puts after correctness).
6. **Everything the Definition of Done asks for beyond the no-pack frame** - the Vitrail smoke pack, MRT and
   depth draws, blit and compute fixtures, the synchronization matrix, resize, reload, dimension, shutdown, the
   real packs, and the lifecycle gate. None of them is claimed; each is its own milestone in the plan's order.

## Metal 4 full-frame implementation complete?

**NO, but the first full-frame milestone is reached.** A forced Metal 4 launch loads a world and renders it -
nine thousand frames, 300 fps, no fault, no restart, no refusal - which is what Phase 5 of the plan asks for;
what is not yet true is everything that turns "it renders" into "it renders correctly and measurably": the
picture has not been compared with Metal 3's, the harness cannot collect the run (the frame probe is not fed by
this path), and MRT/depth/blend/scissor, blit/compute, the synchronization fixtures, the lifecycle checks and the
real packs are all still open. Items 0 to 4 of the plan's order are done as far as they can be without a frame: the Metal 3
bookkeeping, the cold-probe harness, the provider (queue, state and encoder), all five native render smokes, the
frame encoder's lifetime - the ring - proven on the device, its copies wired, its clears implemented and
measured, its fence answering the Metal 3 fence's three ways, its bindings recorded by name and resolved when
the layout arrives, its indexed draw proven on the device, and **its own presentation** - a forced Metal 4 launch
presents its loading screen through this path for more than thirty frames. It then **hangs the GPU** on the first
frame of the loaded world, which is a correctness blocker and not a performance one; the control run (Metal 3
frame, Metal 4 present sidecar) shows the drawable road is sound, so the fault is in what the world frame
encodes. Everything the Definition of Done asks for that needs a frame the client actually *drew and presented*
is still unchecked: the no-pack frame, the Vitrail smoke pack, MRT draws, depth writes, blit in a live frame,
compute, the synchronization matrix, resize, reload, dimension, shutdown, and the real-pack and performance
validation. The next item is narrowing the GPU fault on the world frame.
