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

cold runs:        629 processes, 2546 probes (378 processes and 1619 probes through the compute round, then the
                  dependency round's two censuses and a six-process hunt, then this round's census and its
                  four-process hunt); capability failures: 4, every one of them at ATTEMPT 1 of its process
warm probes:      1450 in thirty-eight processes  field failures: 18 all-time, all in one process of the
                  dependency round and all of them the storage-image smoke - whose shape was the fault: **317
                  probes this round are green**, after the smoke was moved to a table per dispatch and then to an
                  encoder per dispatch
this round:       **write-after-read, the last of section 61's three directions**: a pass samples a texture
                  through a table and a later dispatch writes that same texture, read back as two facts - what the
                  reader saw before the write, and that the write landed - with the ordering failure named as
                  itself. The fixture's own sensitivity was checked by inverting its comparison, which makes it
                  fail. The census is **50 of 50 on all eight dependency fields** and on the storage smoke, 0
                  failures. The round before this one: **the read side of the compute boundary, and section 60's
                  list finished**: a dispatch that
                  samples what a copy or a pass wrote, read back as sixteen values against a per-channel sentinel.
                  The census is 50 of 50 on all six dependency fields and on the storage smoke. The round before
                  this one: **two shapes were wrong, and both are fixed**: the storage smoke depended on a re-pointed
                  table and then, with a table per dispatch, still shared one encoder with the copy dependency
                  smoke in the suite - three of eight warm probes lost the second dispatch. **One encoder per
                  dispatch** is 93 of 93 in three processes and 50 of 50 in the census, with the copy fixture now
                  in it: two 30-cold + 20-warm censuses and two hunts, **317 probes, no field failure**. The
                  round before this one: **two new smokes, the two cross-encoder dependencies**: a dispatch writes a storage image that
                  the next pass samples, and a dispatch writes a vertex buffer that the next draw reads - each
                  encoding the producer barrier rather than inferring the order from one command buffer. Two
                  30-cold + 20-warm censuses and a six-process hunt: 286 probes, 286 of 286 green for both, and
                  18 failures of the storage-image smoke in one process (recorded under Remaining blockers). The
                  round before this one: 84 probes (30 cold and 54 warm across the census and the runs on the way to it), the whole
                  of it after the storage-image smoke was added: **0 failures** and 50 of 50 on every one of the
                  nineteen device smokes, the new one included, with 0 crash reports. The smoke this round added
                  is the **storage image**: a kernel writes a texture through a table, twice, with the table
                  re-pointed between the dispatches, and the texture is read back at both corners and the middle.
                  The compute round's smoke before it was the **dispatch**: a pipeline from the probe's own kernel,
                  a table carrying two buffers by address, one threadgroup of 32 threads, and every output word
                  compared against its own index's formula with a sentinel that proves the kernel ran over it. The intermittent
                  capability fault did not appear in a third 30-process run, which is its known shape rather
                  than a resolution of it: it has been observed twice in about seventy cold starts and never
                  on demand, and it still blocks AUTO. The smoke the depth round added is the **depth draw**:
                  two triangles at known depths, a less-than compare with writing enabled, and the overlap
                  read back as the winner's colour *and* its depth - plus a pixel outside the near triangle,
                  so a compare that rejected everything fails too. The MRT round's smoke before it was the
                  **multi-target draw**: a four-output fragment stage, one fullscreen triangle and every
                  attachment read back against that slot's own value; its pass smoke gained an unfilled slot
                  between two filled ones. The residency smoke was: a set is made, two allocations (a buffer
                  and a texture) go in, it commits and requests
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
                     commit. MEASURED: a forced Metal 4 launch loads a world, runs Vitrail's compute-storage
                     chain every frame and presents its own frames - three sessions on one afternoon, 1947,
                    1959 and 2182 drawable readbacks labelled with this generation's name, no `GPURestart`, no
                     refusal and no fault in any of them. **It is the session's only Metal 4 submission
                     structure**: the present sidecar is not started beside it (see the presentation row and
                     the migration record's convergence note), which is measured before and after the change -
                     the sidecar's start line 1 time against 0, with the frame encoder presenting in both.
                     What still refuses by name: the scissored `clearColorAndDepthTextures` and writeTimestamp
                     - two names.
                     PROVEN: frames are submitted through it - `MTL4FrameRing.endAndSubmit` commits once a frame
                     and the drawable readback of a slot cannot be read before that slot's commit has completed,
                     which is the wait `beginFrame` does; the ring's own device proof (`canReuseAllocatorSlots`,
                     50 of 50) is what makes that wait the proof of the commit rather than a hope
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
queue:               PROVEN, and there is exactly one per session - the frame encoder's ring submits on the
                     queue the Metal 4 provider made (`newMTL4CommandQueue`), one queue, one command buffer and
                     one commit a frame, and the present-only sidecar is **not** started when Metal 4 executes,
                     so a session does not hold a second Metal 4 queue beside its frame's. MEASURED before and
                     after: with `-Dmetallum.execution=metal4 -Dmetallum.metal4Present=true` the sidecar's
                     start line appeared once and its commit-feedback registration once, with the frame encoder
                     presenting 1964 frames; after the convergence change the same launch starts no sidecar and
                     presents 2182, and the reference shell (`-Dmetallum.execution=metal3` with the property on)
                     still starts the sidecar exactly as before
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
                     launch presented its loading screen for more than thirty frames, and the no-pack world frame
                     presents too - 30 presents a 30-frame window. The drawn image is **NOT MEASURED**: every screenshot was one black colour because the display was not photographed.
                     The world frame's first submission used to hang the GPU (kernel GPURestart); that was the
                     argument table's uninitialised bindings and is fixed (Remaining blockers 0). The present-only
                     sidecar (Metal4Path + Metal4PresentGate) stays in place, and is the control that shows the
                     drawable road itself is sound on this machine
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
MRT:     PROVEN, both halves. The pass half: one pass carries four colour attachments cleared to red,
         green, blue and white and each slot is read back against the colour that slot was asked for; a
         second pass loads slot 0's existing contents and re-clears slot 1, so the load, the clear on a
         reused attachment and the store across a pass boundary are all measured; a third describes a slot
         the caller left unfilled between two it filled, which is the MRT shape a program with fewer outputs
         than the pass produces. The drawn half (`canDrawMultipleTargets`): one pipeline with four
         `[[color(n)]]` outputs, one fullscreen triangle from `[[vertex_id]]` alone, and every attachment
         read back against the value that slot's own output writes - at both corners, so a draw that covered
         part of a target fails rather than passing on one pixel. Measured on Apple Silicon: 50 of 50 probes
         (30 cold + 20 warm). What is NOT MEASURED is the image: the frame path runs Vitrail's MRT fixture
         end to end (134 pipeline identities against Metal 3's 134, 30 presents a window, no fault), and no
         picture of it exists - see the picture-column blocker.
clear:   PROVEN as a pass of its own, and it is a decision with a cost. On this API a clear is a **load
         action**, and a load action belongs to a pass, so `Metal4FrameEncoder.clearColorTexture`,
         `clearColorAndDepthTextures` (unscissored) and `clearDepthTexture` each open a one-attachment pass
         that loads cleared and stores, with no draw in it - the honest first version while the question is
         whether the path runs at all. Metal 3's encoder records the clear and folds it into the next pass
         that uses the attachment, which is cheaper (no extra pass, and the attachment is never loaded) and
         is a lifetime model of its own; that is a later optimisation, not a correctness gap, and it is not
         claimed to be free. The clear's pass ends with the producer barrier, and it is opened only after
         any copy the frame encoded is ordered, so the clear cannot land before what it overwrites
depth:   PROVEN, all three halves. The clear: a colour target and a `Depth32Float` target in one pass, the
         depth cleared to 0.25, read back through `MTLTexture.bytes` and compared (50 of 50 probes). The
         compare and the write (`canDrawWithDepth`): two triangles at known depths, a pipeline that declares a
         `Depth32Float` attachment, one less-than state with writing enabled, and the FAR triangle drawn
         SECOND so the overlap is a test of the compare rather than of the draw order - the overlap reads the
         near triangle's colour AND its 0.25 (so the winner wrote the buffer), and a pixel outside the near
         triangle reads the far triangle's colour and its 0.75 (so a compare that rejected everything fails
         there too). Measured on Apple Silicon: 50 of 50 probes (30 cold + 20 warm). The sampling: Vitrail's
         `depthtex0-contract` runs on this path - the game's own draws write depth and a pack pass samples it
         afterwards - with 103 pipeline identities against Metal 3's 103, 18 logical passes a frame against 11,
         no fault and no refusal. The SAMPLING is readback-proven too (`canSampleDepth`): one pass writes depth
         (0.25 over a clear of 0.5) and ends with the producer barrier, the next samples that depth texture
         through a one-texture, one-sampler table at each fragment's own position, and the depth buffer's own
         values (0.25 and 0.5) are read back beside the colours the reader wrote from them (64 and 128, within
         the one level an eight-bit conversion is) - 50 of 50 probes. That fixture's picture is NOT MEASURED: the
         display cannot be photographed
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
wide resources:   PROVEN AND MEASURED IN A REAL PACK - a pipeline whose resources do not fit MSL's direct slots
                  is laid out by the shared translation for an argument buffer, and this generation carries
                  that buffer in one of the table's buffer slots: the artifact asks the stage's own function
                  for an `MTLArgumentEncoder`, the pass makes a shared-storage, hazard-tracked buffer of the
                  encoded length, fills it through that encoder and writes its GPU address into the table slot
                  the shared layout recorded. The ceiling is the header's and not a guess: this machine's
                  `MTL4ArgumentTable.h` caps a descriptor at sixteen sampler slots, the cold probe reports it
                  as "seventeen direct samplers refused ... a table asking for twenty sampler slots accepted",
                  and MSL declares one sampler attribute per sampled image with no way to pack them - so a
                  program past sixteen samplers cannot be expressed by table slots at all. Measured:
                  photon_v1.3b's `deferred4` reads 19 sampled images behind one uniform buffer, and on the
                  Metal 4 arm it now compiles, draws and presents with the reference arm's program set (345
                  pipeline identities on both arms, 345 keys, 736 compiles) and the reference arm's picture
                  (drawable mean BGRA `(44, 62, 55, 0)` on both, picture mean `(53, 60, 42, 0)` on both, over a
                  5x5 grid of a 2560x1440 frame). One wide pipeline on both arms - and no wide pipeline
                  anywhere else in the ladder, MakeUp and Complementary being direct-only, which their re-run
                  confirms (334 identities on both arms). The direct path is unchanged: the compiler asks the
                  DEVICE for its argument-buffer answer where it used to ask for direct bindings by literal,
                  and a wide translation on a device with no tier 2 is refused rather than carried.
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
full:   PROVEN on the device, wired into the frame encoder, and NOW MEASURED IN LIVE FRAMES - the native smoke
        copies a 64x64 four-quadrant pattern into a second texture and every quadrant is read back (50 of 50
        probes), `Metal4FrameEncoder.copyTextureToTexture` is the engine's own form of it, and a live frame now
        encodes thousands of them: photon_v1.3b's window reports `blits=5049 blittedMiB=55882.4` against Metal
        3's `blits=4972` on the same scene, which is Vitrail's history swap-back copy plus the mip work below
region: PROVEN on the device and wired into the frame encoder - a 32x32 region at the origin is copied into the
        destination's other half, and both a pixel inside where it landed and a pixel outside it are read (the
        first is the source's top-left quadrant, the second is still the clear). The engine's
        `copyBufferToTexture`/`copyTextureToBuffer`/`writeToTexture` are implemented over the same encoder.
        **Region semantics are also where this path had a real fault**: every texture-to-texture copy moved
        nothing for a while, because the override read the contract's nine parameters in a different order and a
        correct caller's rectangle arrived as 0x0 - and Metal accepts a zero-sized copy silently. The history
        fixture reads cyan on both arms now; blocker 11 has the measurement
mipmap: PROVEN on the device and used by live frames - `canGenerateMipmaps` uploads a level-0 checkerboard, the
        levels above it are pre-filled with a third value, the chain is generated and every level read back
        against the box average of the one below (50 of 50). In the frame path a Vitrail fixture's chain
        generations are visible under the trace switch (2448 over the run, each true, for a 2560x1440 target),
        and that fixture's acceptance colour is in the presented frame on both arms
```

## Compute

```
dispatch:       PROVEN on the device AND RUNNING in live frames - `canDispatchCompute` builds a pipeline from the
                probe's own kernel, fills a table with two buffers by address, dispatches one threadgroup of 32
                threads and reads every output word back against its own index's formula, with a sentinel
                proving the kernel ran (50 of 50 in a 30-cold/20-warm census). In the client, Vitrail's
                `compute-storage-contract` reports both of its dispatches on a forced Metal 4 session
                (`Dispatched compute composite`, `Dispatched compute composite_a ... groups=(1, 1, 1),
                local=(1, 1, 1)`), and photon_v1.3b's window counts 1893 compute encoders against Metal 3's 532
                - one encoder per dispatch is this path's shape, which section 70 explicitly does not compare
SSBO:           PROVEN as a binding, not as a shader read - the fixture's `Phase15Buffer` is allocated through the
                backend, declared resident, and the dispatch that reads it is encoded with the buffer in its
                table by address; no probe shader declares an SSBO, so what is proven on the device is the
                binding and not the read
storage image:  PROVEN on the device - `canWriteStorageImage` has a kernel write a texture **twice, each
                dispatch in its own compute encoder with a table of its own**, because both the re-pointed form
                and the shared-encoder form lost the second dispatch; the texture is read back at both corners
                and the middle (50 of 50 in the census, 93 of 93 in a hunt, against 18 failures in one warm
                process of the round that found it). The frame path's `clearStorageTexture` dispatches a typed
                zeroing kernel over the texture's own extent with a table per clear
render->compute: PROVEN - `canDispatchSampledRender` (a pass writes a storage image, a dispatch samples it) and
                `canDispatchSampledCopy` (a copy writes it), each with a per-channel sentinel and all sixteen
                samples compared against the producer's colour; plus `canDispatchAfterDispatch`, the two-dispatch
                chain a pack's own compute chain is made of
compute->render: PROVEN - `canSampleComputeOutput` (a pass samples what a dispatch wrote, with the CPU readback
                making "the kernel never wrote" and "the sample never arrived" two different failures) and
                `canDrawFromComputeWrittenBuffer` (a draw reads vertices a dispatch wrote, from a buffer that
                starts as three copies of the origin so an early draw paints nothing)
picture:        MEASURED through the readback road rather than an F2 press, and the two arms AGREE ON THE
                VERDICT but not on the brightness. On the `compute-storage-contract` fixture, both arms are
                overwhelmingly GREEN with **red and blue at zero in every sampled cell** - no magenta anywhere,
                which is the fixture's acceptance criterion (`final.fsh` writes green or magenta and nothing
                else) - and the picture read is the drawable written frame for frame. What differs is the green
                itself: this path presents a **uniform** green (mean G 255, flat from 200 readbacks in) while the
                reference arm presents a **radial green ramp** (mean G 199, stable for the last 2000 of its 4948
                readbacks). Since `final.fsh` can only write (0,1,0) or (1,0,1), neither a ramp nor a dimming
                can come from the pack, and the two arms therefore differ in what else writes the game's target.
                **The mechanism is NOT LOCALISED** and it is registered as blocker 13; the sequential readings
                are in that blocker, and the alpha byte is the separate residual it always was
```

**A note on these two blocks, because they are how a report goes wrong.** They read "NOT STARTED" long after the
work behind them had landed: the capability matrix above was updated rung by rung while the narrative sections
beneath it were not, so the same document contradicted itself - a reader who took the Compute block at its word
would have concluded the compute road did not exist while the matrix three screens up described its dispatches
running in a live frame. Both are rewritten against the counter readings and the device smokes rather than from
memory, and the rule that produced the gap is the one worth keeping: a section is part of the update, not a
summary written once.

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
F3+T:       PASS - driven through the client's own reload entry point (`Minecraft.delayTextureReload`), which is
            the path the key submits to, and its future completed: the compilation caches were cleared and the
            pack was rebuilt through this path in the same session, with the chain drawn again afterwards and no
            stop, no stale pipeline and no use-after-release. `tools/run-metal4-lifecycle-probe.sh`.
pack switch: PARTIAL, and it stays partial for a reason that is about the GUI and not about the frame path -
            the half a switch puts at risk is the retirement of the old compiled artifacts while a frame still
            names them, which the reload above exercises across 5994 submissions and across a *dimension* change
            that re-reads and re-translates the whole pack. Selecting a different pack in the pack screen itself
            is NOT MEASURED.
world leave: PASS - `Minecraft.clearClientLevel(new TitleScreen())`, the path Save-and-Quit takes. The frame
            path survived it: the sessions that leave and then quit run to a clean `Stopping!`. One caveat of
            the driver rather than of the frame path: a packet that arrives for the level just cleared makes
            vanilla throw in `ClientPacketListener.handleSetEntityMotion` (`this.level` is null), which the real
            UI path does not hit because the connection is closed first.
world join:  PASS - every one of these sessions joins a world through `--quickPlaySingleplayer` and renders it.
dimension:  PASS - and it is the one transition on the list that is a command rather than a method call, which
            is why it was the last to be driven: `ClientPacketListener.sendCommand("execute in minecraft:the_nether
            run tp @s 0 80 0")` is what a player's chat line becomes. Measured on this path with
            ComplementaryReimagined_r5.9.1: the server answers `Teleported Player478 to 0.5, 80.0, 0.5`, Vitrail
            logs `Left minecraft:overworld for minecraft:the_nether: a dimension replaces the root rather than
            layering over it, so the whole pack is read, translated and its colour targets allocated again`, and
            then `Drawing ComplementaryReimagined_r5.9.1 from world-1 for minecraft:the_nether, at 2560x1440, 8
            full screen passes before the final`. The chain drew twice - once for `world0`, once for `world-1` -
            with no stop, no fault and zero teardown warnings, which is the moment stale targets, stale tables
            and stale argument buffers would show.
resize:     PASS and measured in the frame path - `Window.setWindowed(1600, 900)` mid-session takes the
            presented extent from 2560x1440 to 3200x1800 and back to 2560x1440 over 2375/1061/2555 readbacks,
            with every render target, table and argument buffer that names one rebuilt across it and no fault.
            **And with MetalFX live it rebuilds the scaler rather than reusing one**: at renderscale=55 the same
            transition makes a scaler for 1408x792 to 2560x1440 and then a second for 1760x990 to 3200x1800, the
            cache going from one entry to two - section 72's MetalFX clause and section 124's resize item, with a
            reading
fullscreen: PASS - `Window.toggleFullScreen()` mid-session, same session as the resize, no fault; the presented
            extent did not change on this display, so what is proven is that the transition is survived rather
            than that a different mode was rendered.
shutdown:   PASS, and it took the gate to find a fault - see blocker 7. The quit is the window's own close flag
            rather than a signal, so the whole teardown runs: `Stopping!`, then the encoder's close, then the
            cache release, then `BUILD SUCCESSFUL`.
```

The first four rows were "NOT STARTED" for the honest reason that driving them needed input this machine will
not synthesise, and the gate was therefore unrun rather than failed. `LifecycleProbeMixin` drives them from
inside the client instead, on a schedule the launch line states, so the transitions are the client's own methods
rather than a simulation of them - and what it found on its first real run was a teardown fault in this path.

## MetalFX Spatial

```
supported:            PROVEN on BOTH generations, and by a functional question on each. Metal 3 asks
                      +[MTLFXSpatialScalerDescriptor supportsDevice:] and then makes one. Metal 4 asks
                      +supportsMetal4FX: and then makes one with a compiler and lets it go
                      (Metal4Fx.supported) - the class question alone is not the answer, because a device
                      that answers yes can still refuse every scaler. The capability record uses the Metal 4
                      answer, which is what it must ask before choosing Metal 4 does not cost the render-scale
                      setting
configuration cache:  one per generation, keyed identically and holding nothing shared - the M3 scalers in
                      MetalFx, the M4 scalers in Metal4Fx, because a scaler is a compiled pipeline and one
                      generation's is not the other's (section 80). A refused configuration is remembered as
                      refused in each
M3 result:            PROVEN (one scaler per configuration, cached, fallback-safe) and re-measured this round
                      at 55%: it takes the MetalFX road and the chain draws
fixed-image smoke:    PROVEN on the device - `canScaleWithMetalFx` uploads a four-quadrant pattern of four
                      different colours at 64x64, upscales it to 256x256 with this generation's scaler, and
                      reads the four quadrant interiors back on the CPU; **40 of 40 probes** in a 20-cold/
                      20-warm census, with a 1:1 configuration and an odd 101x57 -> 320x181 one asked for
                      beside the verdict's. The four colours are 204 levels apart at their closest and the
                      tolerance is 32, so a flip on either axis cannot pass. Three defects in the smoke itself
                      were found and fixed getting there - the second and third configurations' textures were
                      released before the commit that names them (which failed 2 of 80 probes with a
                      neighbouring quadrant's colour), a malformed output copy with a `bytesPerRow` of four
                      for a 256-wide texture that nothing read, and a verdict that had to be the interiors
                      rather than a brightness
orientation:          PROVEN on the device, by the smoke above: the four quadrants arrive where the pattern
                      put them, so the scaler neither flips nor crops. It is **NOT PROVEN in a live frame** -
                      no asymmetric fixture has been scaled through the frame path - and the probe's reading
                      is of the scaler on this device rather than of the engine's use of it
M4 result:            PROVEN ON THE DEVICE AND IN A LIVE FRAME - `MTL4Compiler` asks the device for
                      `newCompilerWithDescriptor:error:`, the artifact is made with the descriptor's Metal 4
                      spelling `newSpatialScalerWithDevice:compiler:`, and `Metal4FrameEncoder.scaleWithMetalFx`
                      encodes it into the frame's own Metal 4 command buffer with no encoder of ours open.
                      MEASURED, ComplementaryReimagined_r5.9.1 at renderscale=55, one session each:

                        Metal 4   "Metal 4 MetalFX spatial scaling: available, the device supports it and
                                   made one"; (Vitrail) "The 55% render scale brings the picture back with
                                   MetalFX"; 333 pipeline identities, 333 keys, 712 compiles, 600 M4 frames
                        Metal 3   "MetalFX spatial scaling: available, the device supports it, factory
                                   newSpatialScalerWithDevice:"; the same Vitrail line; 333 identities,
                                   333 keys, 712 compiles, 596 frames

                      Both draw the chain at 704x396 and 1408x792 - the pack's own scaled targets, identical
                      on both - present at the native 2560x1440, refuse no scaler and stop for nothing. The
                      program set matches at 333 identities and 712 compiles, which is section 70's
                      comparison; the arms' *pictures* differ and are not read as a verdict, because two
                      launches of a pack with history and clouds are what section 116 says not to compare
                      that way. **Output orientation is NOT MEASURED for the scaler in a live frame** - no
                      asymmetric fixture has been scaled through the frame path, though the device smoke proves
                      the scaler's own orientation on a fixed pattern, 40 of 40 - and no fence is set on this
                      generation's path,
                      which is a fact about Metal 4 rather than a choice: there is no fence object in this
                      engine's Metal 4 model at all, so what orders the scaler is the one command buffer's
                      encode order and the all-stages barrier every pass already ends with. What tests that
                      is the render-scale frame above, and it does not test it adversarially
resize rebuild:       **PROVEN in a live frame, and it needed one line to be readable.** Section 124 asks that a
                      scaler be cached per configuration and that a resize rebuild rather than reuse, and
                      section 81 asks for the identity that separates two configurations; all three had a code
                      path and no reading, because this path logged a refusal and never a creation - so "the
                      identity separated them" and "an old scaler was silently reused for a new size" looked
                      identical in a session's log. A scaler is made on a cache miss and a miss means the
                      configuration changed, so one line per creation is the evidence these claims can have.
                      MEASURED at renderscale=55 with a mid-session resize on this path:
                      `made a scaler for 1408x792 to 2560x1440 ..., 1 in the cache` and then
                      `made a scaler for 1760x990 to 3200x1800 ..., 2 in the cache`. The resize took the pack's
                      scaled input from 1408x792 to 1760x990 and the output from 2560x1440 to 3200x1800, the
                      cache went from one entry to two, the presented extent followed (2560x1440 for 1591
                      frames, 3200x1800 for 2047), Vitrail's own `The 55% render scale brings the picture back
                      with MetalFX` line appeared, no scaler was refused, and a dimension change to `world-1`
                      ran in the same session with a clean quit
performance:          NOT STARTED for either generation's scaler: the two arms' frames were paced by the
                      display in this pair, and section 84's 1920x1200 fixed target has not been run
```

## Performance

**The two generations have now been run against each other, in one session, on the same world at the same size:**

```text
m3: 8.06 ms a frame, 124.1 frames a second, 4.94 ms of GPU time a frame over 30 answered frames
m4: 8.08 ms a frame, 123.8 frames a second, +0.2% against m3

picture, m3 against m4: mean channel difference 0.00, 0.00% of pixels differ at all,
                        0.00% differ by more than 8, 0.00% differ by more than 2, worst 0 at 0,0
```

**The no-pack frame's picture is NOT MEASURED, and this section's first version was wrong about it.** It claimed
the two arms' screenshots were byte-identical - they are, and they are both a **single black pixel colour**:
`screencapture` photographed a locked or asleep display, and two pictures of nothing compare as perfectly
identical. The claim is withdrawn, the comparison now refuses that verdict, and what the no-pack frame is known
by is the probe's counters, the client's own chain lines and the absence of a fault or a refusal - none of which
says the image is right. **The pace is the same and it is the display's**: about 7.4 ms
of each 8.06/8.08 ms frame is the drawable wait, so this scene is display-paced and cannot separate the two.
**The GPU numbers are recorded but not compared**: `gpuP50 4.92 ms` is `MTLCommandBuffer.gpuMillis` and
`gpuM4P50 2.04 ms` is `MTL4CommitFeedback.GPUStartTime/GPUEndTime` - two different APIs, and section 92's rule is
that the timing kinds are not interchangeable until that is established. **The structural differences are the
migration's own mechanisms** (render passes 120 → 360, clear encoders 0 → 150, pipeline binds 460 → 1920,
attachment bytes loaded 950.3 MiB → 9387.8 MiB, stored 2637.8 → 9387.8) with the shader programs identical
(`pipelineIdentities 100` both arms). **The two sentences this section first wrote about the traffic were wrong,
and the round that wired the contents facts showed it** - see "The attachment facts reach the pass" in
`docs/metal4-migration.md`, and the corrected numbers below.

**The attachment traffic, corrected.** The road from the pack side's per-attachment facts to this path's pass
descriptors did not exist and now does (`MetalFrameExtras` on the Metal 4 encoder, taken and cleared before each
pass, resolved per slot, with three of its four members answering what is true of this generation rather than
pretending). Wiring it changed **no number and no pixel** on a no-pack frame, which is the honest result: with no
pack nothing states anything, and the Metal 4 arm's readings reproduced the previous session's to the probe's
own precision. What the same round found is that the counter had been reading only part of the frame: the clear
passes and the presents were not counted at all, so the comparison above understated this path's own traffic. With
the counting a function of the attachment each descriptor is opened with, and every pass this path opens going
through it:

```text
                            before the counter covered clears     after
m4 loadedMiB / storedMiB         9387.8 / 9387.8         9409.1 / 13206.0
m4 depthAttachments                     330                     480
m4 depthLoadedMiB / storedMiB   4640.6 / 4640.6         4640.6 / 6750.0
```

`depthAttachments` rises by exactly the 150 clear encoders and `depthStoredMiB` by 2109.4 MiB while
`depthLoadedMiB` does not move: a clear is not a load, which is the mapping showing up as a measurement. The
`loadedMiB` movement of +21.3 MiB (0.23%) is the six extra render passes this window reported (360 → 366), not
anything a clear can do - and a clean re-run on a machine with the three stale clients from earlier sessions
killed reproduced every counter here to the digit (`m3 950.3/2637.8`, `m4 9387.8/13184.7`, `depthAttachments 480`,
`depthLoadedMiB 4640.6`), so those clients were inert for these numbers.

**The mechanism of the gap is pass structure, not the missing facts.** Metal 3 creates 4 native render encoders
a frame and reuses one across consecutive passes (`reusePercent 93.9`) where this path opens one per logical
pass, and Metal 3 folds a clear into the pass that next uses the attachment where this path clears in a pass of
its own - so the following pass loads the attachment again. Both are the first version's deliberate choice
(section 62: over-do it first, measure, then narrow), and neither is about contents facts, which change nothing
on a frame that states nothing.

The Metal 3 reference on the pinned scene is
`wallP50 7.25-7.26 ms`, `gpuP50 7.28-7.29`, `gpuMs 4366.72 / 4368.05` over two arms of
`run/m3-final`, and it is the baseline any Metal 4 frame will be read against - always with
`--fullscreen-size` and `--expect-target` set, and with nothing else running on the machine.

**The two generations were then run against each other on a real pack, four arms in one session, and the
result is NOT MEASURED - for a measured reason.** Session `run/perf-ab4`, exit 0, arm order
`m3a, m4a, m3b, m4b`, `--frames 600 --settle 25 --expect-target 3200x1800`, window 1600x900, pack
ComplementaryReimagined_r5.9.1 on the staged `PerfWorld` (whose player is in `world-1`/the nether, so these
numbers are not comparable with the overworld reference above):

```text
arm   wallP50  wallP95  wallP99   gpuP50  gpuM4P50   depthAttach  loadedMiB   identities  copy-backs
m3a    21.17    23.63    24.80    21.05     0.00           2504     323336.6      333        5400
m4a    16.93    26.02    26.21     0.00    19.36           6242     398034.9      333        5400
m3b    21.29    27.32    28.57    21.33     0.00           2187     288573.9      333        5400
m4b    25.01    40.82    48.63     0.00    27.42           5706     380020.6      333        5400

harness summary, each arm against the one before it:  m4a -8.1%, m3b +1.5%, m4b +30.1%
```

Metal 3's two arms agree to **0.6%**, so the harness is answering the same number twice for one generation. The
two Metal 4 arms differ by **47.7%**, which is wider than any effect being measured: the error bar contains the
question, so no Metal 3 against Metal 4 performance claim may be drawn from this session, and the eight-percent
first pair and thirty-percent second pair are both to be read as the spread.

**The pace is taken from a different resource in each generation**, which is why wall-clock time is not the same
quantity across these arms. The probe's two waits split by generation:

```text
                          drawable wait                    submitWindow wait
m3a   calls=600 p50=0.06ms p95=2.78ms      calls=1200 p50=0.00ms p95=20.44ms
m3b   calls=600 p50=0.06ms p95=6.19ms      calls=1200 p50=0.00ms p95=19.86ms
m4a   calls=600 p50=14.64ms p95=23.96ms    calls=600  p50=0.00ms p95=0.00ms
m4b   calls=600 p50=18.90ms p95=39.10ms    calls=600  p50=0.00ms p95=0.00ms
```

Metal 3's wall time is spent waiting on its own submission ring (1200 submission waits at roughly 20 ms) with a
`0.06 ms` drawable median; the Metal 4 arms spend it waiting for the display to hand over the drawable
(`14.64`/`18.90` ms medians) with a `0.00` submission wait.

**The Metal 4 spread is not explained by the pace, and is registered as a residual.** The two Metal 4 arms
differ by `8.08 ms` of wall P50 and `8.06 ms` of `gpuM4P50` - the same magnitude on both sides of the encoder -
so part of it is inside the frame's own cost. The counters do not account for it: `blits 5400` and
`blittedMiB 101022.1` are identical to the digit in all four arms, `identities` and `keys` are `333` in all four
with `compiles 0`, and the arms' other counters differ by 4-9% in the direction that makes the cheaper arm the
one it is. **The counters that must be equal are equal**, and the attachment-traffic gap
(`depthAttachments` ~2.5x, `loadedMiB` ~1.2x) is the registered pass-per-clear structure this section already
names, not scene drift.

The harness itself needed repairing before this session could produce four arms: its target guard read the
target from only one of the two wordings a build may use, and both of its lookups ran under `set -o pipefail`,
so a build that did not print the first line had the guard **kill the session between the first arm and the
second** - the previous session stopped after one arm with no line saying why. It now reads either wording and
tolerates finding neither; all three properties are pinned in `tools/ci-vitrail-performance.py` and each was
mutation-proved. The full account is in `docs/metal4-migration.md`.

## Capability matrix

Every cell is a measurement or an explicit absence. `M4 smoke` means proven in a process with no window in it
(the cold-probe harness); `M4 real frame` means through a frame the client drew and presented, which for the
cells below is a forced `-Dmetallum.execution=metal4` no-pack launch collected by the harness (30-frame windows,
both arms in one session), and `n/a` where the capability has no live-frame reading yet; `Real-device` means the
same run was on this machine's Apple Silicon rather than in CI, which is where every smoke here was run.

| Capability      | M3          | M4 smoke                          | M4 real frame | Real-device |
| --------------- | ----------- | --------------------------------- | ------------- | ----------- |
| render          | yes         | yes - `canMakeAndSubmit` encodes and submits a render pass on a 64x64 target | yes - a forced Metal 4 launch loads a world, presents 9,000+ frames with no fault and no refusal at Metal 3's display-paced frame time, and a Vitrail fixture pack's fullscreen passes run through it; **and the picture is measured now, which is how blocker 10 was found and fixed**: the no-pack frame on this path is a world again (mean BGRA `(68, 91, 77, 221)` against Metal 3's `(67, 86, 71, 254)`, terrain cells identical cell for cell), with the sky strip at the top of the frame still to be accounted for. **And the half of this row that was FAIL is now fixed (blocker 17): the game's own GUI reads back identically to Metal 3's on the title screen** - mean BGRA `(40, 39, 33)` on both, with the button, logo and glyph samples equal to the byte - where the same reading was `(19, 17, 11)` with no GUI in it before the copy road's missing residency declaration was fixed. The cause was one buffer copy that declared neither resource, which made every vanilla staged vertex buffer move zeros | yes |
| MRT             | yes         | **both halves** - four colour attachments in one pass, cleared per slot and read back slot by slot, plus one pipeline with four `[[color(n)]]` outputs drawing into all four and every slot read back at both corners (50 of 50); a slot the caller left unfilled is carried at its own index | **executes, correctness NOT MEASURED** - Vitrail's MRT fixture runs on this path (134 pipeline identities against Metal 3's 134, 19 logical passes a frame against 15, 30 presents, no fault), and **the fixture's four quadrants are now read**, on both arms: 25 s of settle after its chain can draw, 3168 and 3163 readbacks, and the presented frame is the slot table the fixture was written as - colour target 0 red, 1 green, 2 blue, 3 white, each in its own quadrant, not permuted, with the Metal 4 arm reproducing the Metal 3 arm's arrangement sample for sample (3008 flat frames against 3168 wobbling by the loading fade). The only difference between the arms' frames remains the alpha channel registered in the presentation row | yes |
| clear           | yes         | yes - colour, colour+depth and depth-only clears each encoded as a pass of their own (a load action needs a pass on this API, where Metal 3 folds the clear into the next pass) | yes - 150 clear encoders a window and 150 of its 480 depth attachments are the clear passes' own; a clear is never a load, which the counter now shows (`depthLoadedMiB` did not move when those 150 were counted) | yes |
| depth           | yes         | **all three halves** - a `Depth32Float` attachment cleared and read back, plus two triangles at known depths with a less-than state and writing enabled where the overlap reads the winner's colour *and* its depth, and a pixel outside the near triangle reads the far one's (50 of 50) | **M3 PASS / M4 PASS, measured in the picture**: two diagnostic fixtures read on both arms, one world and one anchor. `depthtex0-contract` paints green where the sampled depth *varies* between neighbours, cyan where it is valid but flat, magenta where it is outside 0..1 - the Metal 3 frame is 100152 green samples against 21380 cyan (the world's geometry is in the depth buffer) and the Metal 4 frame is **cyan at every one of its 119625 samples**. `depth-value-contract` paints which value instead, red for the clear, blue for zero and green for a real depth: Metal 3 reads 100152 green and 21380 red, Metal 4 reads **red for 121500 of 123575 samples**, the clear and nothing else. So the pack's `depthtex0` binding is right (a real depth texture, not an empty or unbound one) and the depth texture is cleared correctly, but **no geometry writes it on this path** - re-run after blocker 10's fix, which is what that reading was waiting for: the Metal 4 arm now reads 90719 green against 28831 cyan and no magenta - the same reading of the same fixture Metal 3 gives on its own run (100152 green, 21380 cyan, no magenta) | yes |
| sampled texture | yes         | yes - a table-bound source is sampled by a pass and the result is read back, one pixel inside each of the pattern's four quadrants; and a whole layout's texture is sampled at the slot its shader declares | yes in the reading the window takes: 775 texture binds a window and the picture is Metal 3's; the pixel-exact proof is the smoke's | yes |
| sampler         | yes         | yes - a nearest sampler with `supportArgumentBuffers` is made, bound and sampled through | as the texture row, 775 sampler binds a window | yes |
| uniform         | yes         | yes - `setAddress:atIndex:` then a draw, read back (64, 128, 191, 255); and two uniforms on two stages at their own buffer indices, each changing a channel of the layout smoke's pixel | the window reports 2476 buffer binds, which are its uniforms, vertex and index buffers together; not separated | yes |
| vertex/index    | yes         | vertex yes - address + stride 16, colour out of the buffer, read back (64, 128, 128, 255), and a second vertex buffer bound with its stride inside a whole layout; index yes - see the indexed-draw row | as the uniform row: the geometry is drawn through table by address and the picture matches | yes |
| argument table  | n/a (M3 uses argument buffers) | yes - two tables in one pass, one per stage, sized to what each stage binds, assigned with setArgumentTable:atStages:, with a draw reading every slot | yes - the frame's bindings are made through a table per stage, built from the compiled layout | yes |
| attachment contents | yes - per-slot `readAfterwards`/`overwritten` from the pack side, through `MetalFrameExtras` | not a smoke subject: the facts become the descriptor's load and store actions, which the attachment smoke exercises | **device-proven**: the fixture pack's statements reach the pass descriptors and the descriptor actions follow - with the elision switch on, `loadedMiB` falls 11497.2 → 11075.3 (−421.9) and `storedMiB` 17643.4 → 16799.7 (−843.7, Metal 3's own figure to the tenth of a MiB), the client's "the backend was told" line appears, and it reproduces in a second session. (Getting there needed `MetalFrameResourceCommands` to be carried: the client gates its whole capability adapter on it.) | yes |
| indexed draw    | yes         | yes - an index buffer as an address in the draw, six UInt16 indices, drawn at index 0 and at index 3 with each frame read back against its own triangle; the selector is the eight-argument one this SDK declares | not separated from the direct draws by the window's counters; `-Dmetallum.metal4Trace` and `-Dmetallum.metal4FrameStats` print the split | yes |
| indirect draw   | yes         | yes - the indirect indexed form, one command per draw with `MTLDrawIndexedPrimitivesIndirectArguments` (twenty bytes) in a buffer the GPU reads and the frame path declares resident; the arguments' own `indexStart` selects which of two triangles is drawn, so arguments that are ignored draw the first one twice (50 of 50) | n/a - a no-pack frame draws directly | yes |
| residency       | yes         | yes - a `MTL4ResidencySet` takes allocations, commits, requests residency and is handed to the queue; and in the frame path it is what keeps the addresses the frame binds alive, measured as the difference between a GPU fault and a world frame | yes - the forced Metal 4 launch renders terrain with no `GPURestart` | yes |
| blit            | yes         | yes - whole and region texture copies measured on the device, and the engine's own `writeToBuffer`/`writeToTexture`/`copyBufferToTexture`/`copyTextureToBuffer`/`copyTextureToTexture` implemented over the same compute encoder (the client walked past its texture-manager upload); none encoded inside a live frame yet | n/a - a no-pack frame needs no copy, and the window reports `blits 0` | yes |
| mipmap          | yes         | yes - `canGenerateMipmaps`: a level-0 checkerboard uploaded, the levels above it pre-filled with a third value, the chain generated, and every level read back against the box average of the one below (50 of 50) | **executes, and the picture is read now - M3 PASS / M4 PASS**: Vitrail's `deferred-mipmap-contract` runs on this path (105 pipeline identities against Metal 3's 105, no refusal), its chain generations are visible under the trace switch (2448 over the run, each true, for a 2560x1440 target), and the fixture's own acceptance is in the presented frame on both arms: 40 s of settle after its chain can draw, 4968 and 4946 readbacks, and both present the `rebuilt` colour (`deferred2.fsh`'s cyan, mean of means RGBA `(5, 241, 241, 254)` against `(4, 248, 248, 224)`) - which it only paints when `deferred1`'s green checkerboard was averaged to 0.5 by the mip chain and recognised again - with **no magenta in either arm**, magenta being what any break in the chain paints. The same three passes, the same pack parse and no fault in either log | yes |
| compute         | yes         | yes - `canDispatchCompute`: a pipeline from the probe's own kernel, a table carrying two buffers by address, one threadgroup of 32 threads, and every output word read back against its own index's formula with a sentinel proving the kernel ran (50 of 50); and the translation itself is one shared class both generations compile through | **dispatches**: on a forced Metal 4 session Vitrail's `compute-storage-contract` reports `Dispatched compute composite` and `Dispatched compute composite_a ... groups=(1, 1, 1), local=(1, 1, 1)`, the chain runs on to `final writes the game's own target`, and no pipeline, binding or encoding refusal appears. The picture is NOT MEASURED: the fixture's GREEN claim needs the in-game F2 screenshot, which this session could not press (macOS refused the key event) | yes |
| storage buffer  | yes         | no - a buffer is bound by address and a kernel writes it (the compute smoke), but no shader in the probe declares an SSBO | **binds** - the fixture's `Phase15Buffer` is allocated through the backend, and the dispatch that reads it is encoded with the buffer in its table by address; the shader's own read of it is what the missing GREEN picture would confirm | yes |
| storage image   | yes         | yes - `canWriteStorageImage`: a kernel writes a texture **twice, each dispatch in its own compute encoder with a table of its own** (both the re-pointed form and the shared-encoder form lost the second dispatch), and the texture is read back at both corners and the middle (50 of 50 in the census, 93 of 93 in a hunt); the frame path's `clearStorageTexture` dispatches the typed zeroing kernel over the texture's own extent, with a table per clear - though a blocker below records that the engine still shares one encoder across them | **cleared and dispatched through**: the fixture allocates `phase15Image` with no complaint about clearing it, and its two dispatches - which write it through tables - are encoded on this path; whether the second dispatch *sees* the first's writes is what the GREEN picture would confirm, and the picture is NOT MEASURED | yes |
| synchronization | yes         | **all seven of section 60's fixtures** - two encoders in one command buffer, one commit, one shared-event wait, both pixels read; a pass that samples what the pass before it wrote; **a pass that samples what a dispatch wrote** (`canSampleComputeOutput`: the producer barrier is asked for before it is sent, the image is read back on the CPU so a kernel that never wrote and a sample that never arrived are two failures, and the target holds a colour no other smoke uses); **a draw that reads vertices a dispatch wrote** (`canDrawFromComputeWrittenBuffer`: the buffer starts as three copies of the origin, so a draw that ran early paints nothing). Plus **the copy's two boundaries** (`canSampleAfterCopy`: a pass writes a source, a copy moves a region into the destination's other half, and a pass samples it - both halves read on the CPU and both through the sampler, 50 of 50 in the census and 93 of 93 in a hunt). And **the read side**: `canDispatchSampledRender` (a pass writes, a dispatch samples it - "render writes storage image → compute reads") and `canDispatchSampledCopy` (a copy writes, a dispatch samples it - "blit writes → compute reads"), each with a sentinel per channel and all sixteen samples compared against the producer's colour. And **`canDispatchAfterDispatch`**, the chain of two dispatches a pack's own compute chain is made of and the shape Vitrail's compute fixture depends on: the first writes a storage image, the second samples it, sixteen samples read back against a per-channel sentinel (50 of 50). By section 61's classification **all three directions are measured**: read-after-write is the seven fixtures above and the compute chain; write-after-write is the storage smoke (two dispatches writing one texture, read as the second write); and **write-after-read is `canWriteAfterRead`** - a pass samples a texture through a table and a later dispatch writes that same texture, read back as two facts (what the reader saw before the write, and that the write landed), with the ordering failure named as itself. Its sensitivity was checked by pointing the comparison at the writer's colour, which makes it fail. A 30-cold + 20-warm census is 50 of 50 on all eight fields | yes for the frame's own boundaries: every logical pass is its own native encoder and ends with the all-stages producer barrier, which is why the storage-image boundary a pack states is already encoded unconditionally; the rest of the matrix is still the plan's fixtures | yes |
| fence           | yes         | yes - a submission's value can be waited for on the ring's shared event, an uncommitted value polls false and is refused for a wait, and zero is complete; measured 50 of 50, and created by a forced client run from `MappableRingBuffer.rotate` | yes - the world frame makes fences and the ring's completion values answer them | yes |
| presentation    | yes         | **implemented in the frame encoder**: take the drawable, `waitForDrawable:` before the commit, the present triangle in the frame's own command buffer, `signalDrawable:` + present after it. **Both halves of the presented frame are readable on both generations** behind `-Dmetallum.drawableReadback=true` (the layer's `framebufferOnly` off, the picture the triangle sampled *and* the drawable it wrote copied into a shared buffer, read when the slot completes, one formatter in the shared layer) | yes - 30 presents a window; **and the two arms compared on one scene, one fixture, one switch, at ten and at forty seconds of settle (1366/1372 and 4951/4953 readbacks): both present the fixture's acceptance colour (pure green, red and blue at zero), and on both arms the picture read is the drawable written, frame for frame - so the present pass is the identity on this fixture and the difference is frame content, not present treatment.** One difference is measured and persists forty seconds: the Metal 4 frame is flat green with **alpha 0** where the Metal 3 frame is flat opaque green - invisible on an opaque layer, mechanism not yet localised (the pack's write into the game's target, a later pass, or the sampling of it), and its experiment is a pass-boundary copy plus a fixture whose colour is asymmetric and whose alpha is not 1. The "gentle radial ramp (230..255)" registered in an earlier round is **withdrawn**: it was the Metal 3 arm's frame still cross-fading from the loading screen, and at forty seconds that arm reads flat opaque green. **Orientation is PROVEN on a second, diagnostic fixture** (four quadrant colours at alpha 0.5): both arms present the same arrangement sample for sample - the present draw swaps the two ends of the memory-vertical axis and nothing else - and the RGBA8/BGRA8 channel conversion is correct on both. **The alpha is not the pack's**: the shader's alpha moved 1.0 to 0.5 and the stored alpha did not move on either arm (255 on Metal 3, 0 on Metal 4), so the difference is in the frame's own clear rather than in the pack's write, and which writer owns that channel is not yet localised. **The full-frame path is the session's only Metal 4 submission structure**: the present-only sidecar is not started when Metal 4 executes (measured before and after the convergence change - its start line 1 time and one commit-feedback registration against 0, with the frame encoder presenting 1964 then 2182 frames), and it is still started for the reference shell, a Metal 3-executing session with the property on. **Blocker 17 narrows this row rather than leaving it**: the present is faithful - the picture the triangle samples is the texture the GUI's pass wrote and a forced clear through that pass appears on screen - so what is missing was never handed to it | yes |
| MetalFX spatial | yes         | **a second path, not a parameter of the first** - this generation's own compiler (`newCompilerWithDescriptor:error:`), its own scaler made by the descriptor's Metal 4 spelling, its own configuration-keyed cache, and an encode into a `MTL4CommandBuffer` | **yes, in a live frame**: `metalFxAvailable()` answers the scaler path's own existence, and at renderscale=55 Vitrail logs `The 55% render scale brings the picture back with MetalFX` on this path with the reference arm's program set (333 identities, 712 compiles) and the pack's own scaled targets (704x396, 1408x792) on both. Output orientation for the scaler is NOT MEASURED | yes |
| counters        | whole frame | **CLOSED FOR THIS SHAPE, and what it does not give is as measured as what it does.** The heap road works - a `MTL4CounterHeap` of type Timestamp, timestamps resolved on the CPU after the ring's shared-event wait (the header's own synchronization rule, which the ring already implements), per-entry and range resolves agreeing, and **a counter tick is a nanosecond** on this device, measured by sampling the CPU and GPU clocks together twice. **But no sampling point tried attributes a pass's work**, and three explanations are refuted rather than open: 4096 fullscreen draws report 6.8x one draw while 128 report *less* than one (so not a floor), the inversion survives a real load-after-store dependency on one shared attachment (so not overlap), both granularities give the same shape (so not the header's `Precise` splitting warning), and it stays at entry 3 with the curve reversed while its magnitude falls from ~226,000 ticks to ~120 (so not the work). What remains is that the sampling point is the driver's, not the caller's. **Therefore per-pass GPU time is NOT AVAILABLE from this road**, and section 92's three kinds of data are: CPU encode timing (have), whole-command-buffer driver timing (have, `MTL4CommitFeedback.GPUStartTime/GPUEndTime`, reported as `gpuM4P50/P95/P99/Max`), GPU counter timing (**not available**). Section 90's smoke is RED, the census with it, and section 95's candidates must be argued without a per-pass GPU time until a road is found that samples where it is told to. Blocker 15 | yes - `MTL4CommitFeedback.GPUStartTime/GPUEndTime` per commit, reported as `gpuM4P50/P95/P99/Max`; a whole frame and, for this path, the same as a whole command buffer, because the frame is one commit | yes |

**What the matrix is for here**: it is the list a reader checks before believing any claim about the migration,
and its blanks are the work. A `yes` in `M4 real frame` means the harness collected it from a frame the client
drew and presented; a capability with no live-frame reading is `n/a` rather than inferred from a smoke, because a
capability proven in a process with no window is not the same claim.

## Remaining blockers

The list is current, and fixed items are kept as one-line records so a reader can see what the migration already
answered rather than only what is left.

0. ~~The world frame hung the GPU~~ - **fixed**: an argument table's bindings are not initialised unless you ask
   (`MTL4ArgumentTable.h`: `initializeBindings` defaults to **false**), so a slot this path never fills - and this
   path skips a binding by design where a layout declares it as the other kind of resource - held undefined data,
   and the first frame that drew the clouds read one. Tables are created with their bindings initialised to nil.
   MEASURED: a forced Metal 4 launch loads a world and presents for nine thousand frames with no fault, no
   `GPURestart` and no refusal. **What that sentence must not be read as saying is that the world is in those
   frames** - see blocker 10, which is what reading the pixels rather than the fault list found.
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
   kinds have not been shown to measure the same interval. **What that leaves open is a scene that is *not*
   display-paced**: the follow-up on a real pack, four arms in one session, is blocker 16, and it did not close
   the question - Metal 3 repeated to 0.6% while Metal 4's two arms differed by 47.7%.
3. **The attachment traffic is the one measured inefficiency, and it is pass structure.** This path loads
   9387.8 MiB and stores 13184.7 MiB over thirty frames where the Metal 3 arm loads 950.3 and stores 2637.8 on
   the same scene - the corrections above replaced the first reading of 9387.8/9387.8, which was the game's
   passes alone and left every clear pass and present out. The mechanism is this path's own design and not the
   missing contents facts: one native encoder per logical pass where Metal 3 reuses one (`reusePercent 93.8`),
   and a clear in a pass of its own where Metal 3 folds it into the pass that uses the attachment, so the
   following pass loads the attachment again. The contents road is now **device-proven** on Vitrail's
   attachment-traffic fixture pack (see the capability matrix), and getting there needed one more thing than the
   road itself: the client gates its whole capability adapter on `MetalFrameResourceCommands`, which this path
   now carries with three honest refusals.
4. **The display cannot be photographed in this environment.** Every `screencapture` of the last sessions is
   one black colour (a locked, asleep or otherwise uncapturable display), so **no picture evidence exists for any
   Metal 4 frame**, and three earlier claims of a byte-identical picture were pictures of nothing. The harness and
   the comparison now refuse that verdict and end non-zero rather than printing "0.00% of pixels differ" for two
   black images; the counters are unaffected and remain the measurement. Blocks every correctness claim that
   needs a picture - the no-pack frame's appearance and the fixture pack's acceptance test - and needs the
   machine's display awake.
5. **The intermittent capability-probe failure** - 2 of 70, stage `pixel`, two surviving hypotheses. Blocks
   AUTO, does not block implementation.
6. **The storage-image smoke still loses its second dispatch, and the census now measures the rate at which
   it does.** The earlier rounds' reading was that this was fixed - "50 of 50 in this round's census and 124 of
   124 in a four-process hunt" after `canWriteStorageImage` was changed to make a table *and* an encoder per
   dispatch. Five 40-probe censuses this round, on the same device and build, say otherwise:

   ```text
   census            cold      warm     total      (each is 20 fresh processes + 20 warm probes)
   metalFx smoke in   0/20      2/20     2/40
   metalFx smoke out  6/20      4/20    10/40
   metalFx smoke out  1/20      0/20     1/40
   metalFx smoke in   1/20      0/20     1/40
   metalFx smoke in   3/20      4/20     7/40
   ---------------------------------------------------
   all five                              21/200  (10.5%)
   ```

   The failures carry the shape's own reason string (`the texture at (0,0) reads (255,0,0,255) where the second
   dispatch's own table held (0,255,0,255)`), they are spread across the run rather than clustered at the
   start, and **no other smoke fails beside them** - `writeAfterRead`, `computeChain` and `layout` are clean in
   all 200 probes. So the fix narrowed the fault and did not remove it, and the six-per-cent claim of a clean
   census was the low end of a variable rate rather than the rate.

   **The order effect is not established.** The two configurations above differ by what runs before the smoke -
   the MetalFX scaler sequence - and their totals are 3 of 80 against 11 of 80. But the per-census spread
   *within* one configuration is 1 to 10, which is wider than the difference between the configurations, so the
   honest reading is the pooled 10.5% and the order question is left open. What would settle it is a census
   large enough to separate a 4% arm from a 14% arm, which is a few hundred probes each.

   **And the rate moved out from under the measurement.** Three censuses run after the smoke's failure path was
   given a self-localising diagnostic - the only change, and a change that runs *only when the smoke has already
   failed* - read **0 of 360** (0 of 40, 0 of 120, 0 of 200), against the 21 of 200 above:

   ```text
   period                                          probes   storage-image failures
   the five censuses that re-opened this entry       200     21  (10.5%; counts 10, 2, 1, 1, 7)
   the three censuses after the diagnostic           360      0  (counts 0/40, 0/120, 0/200)
   ```

   A fault that is 10.5% in one period and absent in the next, with nothing in the path changed, is not a
   property of the build alone: something outside this instrument moves it - machine load, driver or clock state
   - and the harness cannot see which. That is the gap section 88's counter work exists to close, and it is the
   strongest argument for it that the migration has produced. **What this does not say is that the fault is
   gone**: 360 clean probes is not decisive against a rate already observed at 25% in a single census, and the
   honest statement is that the rate is not stable.

   **The failure path now localises itself.** The reason string used to name the symptom; it now re-reads the
   texel after 50 and after 100 ms and prints all three readings, which separates the two faults that produce
   the symptom: a dispatch that was lost reads the same colour three times, and a CPU read that arrived before
   the GPU's write was visible reads the right colour on the second attempt. That second candidate is real here
   and not a straw man - this smoke's readback is a CPU `getBytes:`, while every other readback in the file that
   comes off the GPU goes through a buffer. So the next occurrence names its own mechanism rather than the
   report having to guess at it.

   This is the same table-and-encoder shape the engine's own `clearStorageTexture` uses, so a fault at this
   rate in the probe is a fault the frame path can reach. It is re-opened here rather than carried as fixed,
   and it is the strongest argument for the counter work in section 88 that the migration has produced: what
   changes the rate is not something this instrument can see.

   The original entry follows, as the record of what was found and what was changed.

   **The storage-image smoke loses its second dispatch, and it is now reproducible on demand.**
   One census this round failed eighteen consecutive warm probes in a single process (its third probe onward),
   each reading the *first* dispatch's red where the *second* dispatch's green was asked for. That is the same
   table-snapshot property `Metal4FrameEncoder.clearStorageTexture` depends on, so it was chased rather than
   filed: a smoke of the copy's two boundaries makes it deterministic - four of four runs failed the process's
   fourth probe, a ten-warm run failed probes 3, 5, 7 and 9 - and four bisects put the ingredient on the
   **region copy encoded in a compute encoder between two render encoders**, not on the table, the re-point or
   the barrier. **The reproducer is now a committed artifact**: `tools/metal4-cold-probe/CopyThenDispatchRepro.java`
   under `tools/metal4-cold-probe.sh --repro N [--variant NAME]`, and **the mechanism is now measured**: two
   dispatches in one compute encoder through one table object re-pointed between them, where the second
   dispatch reads what the table held when it was first handed over - red instead of green, on every even
   round, in a victim of the reproducer's own. A **fresh table per dispatch** is clean, and so is an encoder or
   a commit per dispatch. **The engine does exactly the unsafe thing**: `Metal4ComputePipeline` keeps one table
   per compiled kernel and hands it over again per dispatch, and `Metal4FrameEncoder.clearStorageTexture`
   re-points one table for every clear in a frame - so two dispatches of one kernel, or two storage clears, could
   bind what the first bound. **Fixed the same round** in the measured-safe shape: a table per dispatch, made at
   the call site and given back through the frame's destruction queue, in both `dispatchCompute` and
   `clearStorageTexture`; the client still dispatches both of the fixture's programs with no refusal, and the
   cost is three tables a frame there (pooling is a phase-21 candidate, keyed by the dispatch's place in the
   frame rather than by the kernel). **And the smoke that carried the same shape has been corrected too** -
   `canWriteStorageImage` now makes a table per dispatch, because its old green was phase-dependent and
   therefore a false green: 50 of 50 in this round's census and 124 of 124 in a four-process hunt, against 18
   failures in one warm process of the round that found it. **And a second shape was wrong too**, found with the
   copy fixture in the suite: a fresh table is not enough, because the unit the driver honours is the
   **encoder** - one encoder carrying two dispatches lost the second one, three of eight warm probes, while one
   encoder per dispatch is 93 of 93 in three processes and 50 of 50 in the census. **The engine was fixed the
   same way**: `dispatchCompute` and `clearStorageTexture` each open an encoder of their own, end it with a
   producer barrier and file its release through the frame's destruction queue, while copies and mip
   generations keep the frame's shared encoder because they bind no table - and the client still dispatches
   both of the fixture's programs with no refusal. What is still **not measured** is the fix *changing an
   outcome* in the client: Vitrail's compute fixture dispatches two different kernels, so the shapes that lose
   a dispatch are not in its frame - a fixture that dispatches one kernel twice per frame is what would show
   it, and the reproducer is what shows it native.
7. ~~The Metal 4 teardown has never run in a session~~ - **run, and it held one fault.** Every session before
   this one was *stopped* rather than quit: a forced Metal 4 session sent `SIGTERM` exited within thirty seconds
   with no teardown line in its log, so the frame encoder's `close()` - the ring's completion wait, the deferred
   releases, the transient arena, the storage pipelines, the residency set and the queue - had no real-device
   evidence at all. `LifecycleProbeMixin` sets the window's close flag instead, which is the close button's own
   path, and the teardown ran: `Stopping!`, the encoder's close, the cache release, `BUILD SUCCESSFUL`. The
   fault it found was the wait that follows: `MetalDevice.close()` waited for submitted work, closed the frame
   encoder - which releases the ring - and then cleared the pipeline cache, whose own wait landed on the
   released ring and reported a completion that had arrived 0 ms earlier as a timeout that never would. Measured
   with the ring's own state in the line (`submissions=3815 awaited=[3814, 3815, 3813]` complete, then
   `awaited=[0, 0, 0]` not), fixed by deleting the redundant clear - `executionState.close()` clears the same
   caches at the end, after the same wait - and re-measured on the exact build with `photon_v1.3b`: one clean
   teardown, zero warnings, chain drawn twice. **Shutdown: PASS on the executing path.** The reference arm's
   shutdown is unchanged and also clean.
8. **What still refuses by name** - the scissored `clearColorAndDepthTextures` (a partial clear is a draw over a
   rectangle, not a load action), `writeTimestamp` (the counter path, which the plan puts after correctness), and
   the two frame-resource operations the Metal 4 encoder carries and answers false to (`clearStorageTexture`,
   `copyStorageTextureRegion`) - carried so that the capability dispatch installs at all, refused so that no
   caller is told work was done. `generateMipmaps` left that list when the frame's copy encoder learned the
   command, which this SDK declares on `MTL4ComputeCommandEncoder`.
9. **Everything the Definition of Done asks for beyond the no-pack frame** - the rest of the Vitrail smoke-pack
   staircase, MRT and depth draws, the blit fixture inside a live frame, the synchronization matrix, resize,
   reload, dimension, shutdown, the real packs, and the lifecycle gate. None of them is claimed; each is its own
   milestone in the plan's order. (The compute fixture's dispatches now run through this path, which is a
   different sentence from the fixture passing: its pixels are not measured.)

10. ~~The world's terrain is not drawn on this path~~ - **fixed, and the fix is one device feature.** A forced
   Metal 4 no-pack session presented one flat sky-blue clear (`00b8d2ff` at all twenty-five samples of all 4958
   readbacks, and again after 90 s) where Metal 3 on the same world presented a world, its depth buffer held
   nothing but the clear, and its terrain pass - Sodium's own, whose `DefaultChunkRenderer` carries that label -
   ended with `draws=0` on every one of 22836 endings (**which was true then and cannot be read as evidence now**: the indirect draw path was not counted, so that instrument would have read zero whether the pass drew or not - it reports 337, 678 and 584 draws per ending once the counters count indirect draws). The draw side was ruled out by measurement: two Metallum
   mixins route Sodium to `DrawBackend.VK_INDIRECT` and `MetalDrawContext extends VKIndirectContext`, so the draw
   it asks for is the *indirect* one this path implements, and vanilla's feature-gated multi-draw road would have
   been logged by the refusal line if it were taken. A diagnostic mixin added for it
   (`com.metallum.mixin.sodium.ChunkUploadMixin`, off unless `-Dmetallum.logSodiumTerrain=true`) then showed
   Sodium's upload step receiving build results **every frame**, while the geometry arena it would allocate never
   appeared - so the loss was inside the upload, and the upload's first decision is
   `DeviceFeatures.persistentMapping`, which `MojangStagingBuffer` reads to choose between a persistently mapped
   buffer and the engine-staged path. Metallum advertised it **true**; withdrawing it
   (`new DeviceFeatures(false, false, true, true, true, false, false)`) makes the same launch **draw the world** -
   mean BGRA `(68, 91, 77, 221)` against Metal 3's `(67, 86, 71, 254)`, terrain cells identical cell for cell,
   confirmed in a second run - and leaves a Metal 3 launch unchanged. The depth fixture agrees now too. **NOT
   PROVEN**: where the mapped path loses the data on this generation; the claim stays withdrawn until it is, and
   the engine-staged path is the one taken. **And one difference survives**: the sky strip at the top of the frame
   is the clear colour on this path where Metal 3 renders sky, and **its two obvious candidates are eliminated
   by measurement**: the trace line now carries each pass's first colour target and its load/store/clear actions,
   and every drawn pass loads and stores (`AttachmentContents.CARRIED`, the default, maps to `LOAD_LOAD`), while
   the sky, terrain, clouds and blit passes all write the same colour target. The sky passes are encoded before
   the terrain pass and share its target, so what is left is the sky's own content or a later write over exactly
   that region - and a copy of the target at a pass boundary settles it, exactly like the alpha channel. One
   instrument correction came with that reading: `drawIndexedIndirect` did not increment the pass's draw
   counters, so a pass that draws the world through Sodium's indirect batches read as an empty pass (`draws=0`);
   pinned now, and the same trace reads 337, 678 and 584 draws per terrain ending.

11. ~~The history rung fails on this path~~ - **fixed, and the fault was one parameter order.** Vitrail's
   `composite-history-contract` is a chain of three passes over one target declared `colortex2Clear = false`, and
   its verdict is legible in the presented frame - cyan when the chain is in its steady state, magenta whenever it
   is not. Metal 3 presents cyan (with red only while the chain settles); Metal 4 presents **magenta for 119975 of
   121675 grid samples and never cyan**, because the chain breaks on its first evaluation and latches. Measured one
   step deeper with a diagnostic fixture that hands the *value* being judged to the screen: Metal 3 reads **yellow**
   (the steady state) where Metal 4 reads **dark** (13, 7, 6) on the first frames and magenta after. Dark at that
   point means the pass read a copy of the doubled history target that no earlier pass of the same frame had
   written - and the trace's new per-pass attachment list shows the doubling working as Vitrail schedules it
   (`composite` writes `0x7502559e00`, `composite1` writes `0x7502559b80`, `composite2` writes both `0x7502559900`
   and `0x7502559e00`), while the clear pass attaches `0x7502558f00`, `0x7502559680` and `0x7502559900` every frame
   and never the history target, so `colortex2Clear = false` is honoured and a clear is **eliminated** as the cause.
   The native smoke for this exact dependency (`canSampleAfterCopy`) is 50 of 50 on this device, so what is missing
   is in the frame path - and the instrument that names it is the *sampled* texture per pass, which the trace does
   not print yet - and **that list has since been added, and it takes the binding side off the list**: in all 1783
   endings of a traced session every history pass samples exactly the copy the pass before it wrote
   (`composite` writes `0x..de00` and samples `0x..db80`, `composite1` writes `0x..db80` and samples `0x..de00`,
   `composite2` writes `0x..de00` and samples `0x..db80`), and the reason those bindings do not change between
   frames is that Vitrail exchanges the halves by *copying* (`ColorTargets.copyBack`: "1 targets are copied back
   from their far half at the end of every frame"). That copy is one engine call, `copyTextureToTexture`, which
   this path implements with both textures declared resident, the right selector and the right argument order,
   and throws rather than returning quietly. So the question narrows to **where in the frame that copy is
   encoded**: after this frame's commit it would land in the next frame, behind the pass that needed it.
   **And the copy was zero-sized.** The next instrument printed the rectangle each swap-back copy was given
   and every one of them read `0x0`: the shared contract is
   `copyTextureToTexture(source, destination, mipLevel, destX, destY, sourceX, sourceY, width, height)`,
   while this path's override declared `(source, destination, mipLevel, x, y, width, height, destinationX,
   destinationY)` - the same nine parameters in a different order - so a correct caller's rectangle was read as
   width 0, height 0 at destination (width, height). Metal accepts that without complaint, so **every
   texture-to-texture copy on this path moved nothing and said nothing**. The override now reads the contract's
   order, and the fixture passes on both arms: 4926 and 4969 readbacks, Metal 4 `(3, 248, 248, 224)` - the steady
   state, cyan, with 1600 settling samples and **no magenta** - against Metal 3's `(5, 241, 241, 254)`, unchanged.
   Two pins hold the order and are mutation-proved, one of them by swapping the two origins, which is the shape
   of the fault. What the same bug reached beyond this fixture: Vitrail's shadow target copy
   (`ShadowTargets`, `copyTextureToTexture(depth, noTranslucents, ...)`) is the next candidate to read under the
   same instrument, and any pack that copies one target over another had been silently doing nothing on this path.

12. ~~A pipeline that does not fit MSL's direct slots refuses to compile, so Photon stops~~ - **fixed, and the
   fix is the wide binding path**. `photon_v1.3b`'s `deferred4` is nineteen sampled images behind one uniform
   buffer, so the last sampler it asks for sits at index 19; `MTL4ArgumentTable.h` caps a descriptor at sixteen
   sampler slots, MSL declares one sampler attribute per sampled image, and so the wide shape - an argument
   buffer - is the only shape there is, on both generations. This path asked the shared translator for direct
   bindings by literal, which made that shape a throw. The compiler now asks the **device** for its
   argument-buffer answer and keeps one guard where the literal was (a wide translation on a device with no tier
   2 is refused, because the buffer the resources were laid out in could not be made); the artifact asks the
   stage's own function for an `MTLArgumentEncoder` per set per stage; and the pass makes a shared-storage,
   hazard-tracked buffer of the encoded length, fills it through that encoder, and writes its GPU address into
   the table slot the shared layout recorded. The plan stops counting an indirect binding's index as a table
   slot - those are positions inside the argument buffer, and counting them would size a table past Metal's
   thirty-one buffer slots - and counts the argument buffer itself instead. MEASURED: photon draws on this path
   with the reference arm's program set (345/345 identities, 345/345 keys, 736/736 compiles) and the reference
   arm's readback means to the byte, with one wide pipeline in each arm's log and no error of its own in this
   arm's. **What is NOT PROVEN**: that the shape holds for a pipeline wider than one pack's; the writes are not
   deduplicated (section 50's correctness-first order); and Vitrail's `wide-resources-contract` fixture, which
   drives thirty-three sampled images through one pipeline, has not been run on this path.

13. **The two arms disagree about how bright a fixture's frame is, and neither reading comes from the pack.**
   `compute-storage-contract`'s `final.fsh` writes pure green `(0,1,0,1)` where it judges the compute chain's
   marker correct and pure magenta `(1,0,1,1)` where it does not - nothing else, at any brightness. Measured
   through the drawable and picture readbacks on both arms in one round, 40 s of settle after each chain drew:

   ```text
                              readbacks   green over the run        red/blue   picture == drawable
   Metal 3  (comp8-compute-metal3)  4948   60 -> 194 -> 199, flat    zero       yes, ramp for ramp
   Metal 4  (comp8-compute-metal4)  4960   50 -> 255, flat           zero       yes, green for green
   ```

   Both arms pass the fixture's verdict - overwhelmingly green, red and blue at zero in every sampled cell, no
   magenta - and both read the same thing on both roads, so the present pass is the identity on this fixture on
   both generations. What differs is the green: this path is **uniform at 255**, the reference arm is a **stable
   radial ramp** whose centre reads 255 and whose corners read 67, and each is a plateau rather than a fade
   (Metal 4 reaches 255 within 200 readbacks and stays; Metal 3 converges to 199 within 400 and holds it for the
   last 2000). A ramp cannot come from the pack, so something else is writing the game's target on one arm and
   not the other - **an overlay multiplied in, or a write this path skips, and which of the two is not
   localised.** It is the third residual of the same family and it is registered rather than resolved: the sky
   strip and the alpha channel both want a copy of the target at a pass boundary, and so does this. What would
   localise it is the pass-by-pass attachment trace of a session that reads the target's *mean* rather than its
   sampled cells, because a multiply by a radial mask is exactly what a per-pass readback would separate from
   the pack's own write.

14. **The MetalFX scaler's output orientation and its configuration edges are NOT MEASURED, and its ordering is
   argued rather than adversarially tested.** The Metal 4 path is a second scaler with its own protocol, and what
   is proven about it is: the device makes one (functionally, not by a `respondsTo`), Vitrail takes the road, the
   frame draws, and the reference arm's program set and scaled target sizes match. What is not:
   **orientation in a live frame** - the device smoke now proves the scaler's orientation on a fixed pattern
   (40 of 40), but no asymmetric fixture has been scaled *through the frame path*, and the scaler is the one
   thing in the frame whose output this engine never reads back at its own size; **the configuration switch and resize** of section 82 - a
   scaler is cached per configuration and a new one is made for a new size, which is the code path but has no
   reading; and **ordering** - the Metal 3 scaler is handed the frame's fence because this engine's textures opt
   out of hazard tracking, and Metal 4 has no fence object at all in this engine's model, so the encode order
   inside one command buffer plus the all-stages barrier every pass ends with is what orders it. That is a claim
   about the API that the render-scale frame is consistent with and does not falsify. The experiment that would is
   a fixture whose scaled output is read back at the input's size and compared against a pattern the input could
   not have produced late.

15. **The GPU timestamp road works and its sampling points do not attribute a pass, so section 90's smoke is
   red.** What is proven: `MTL4CounterHeap` is made, timestamps written into it resolve on the CPU after the
   ring's own shared-event wait (the header states that rule and the ring already implements it), the three
   readings are monotonic, and the unit is a **nanosecond** - measured rather than assumed, by sampling
   `sampleTimestamps:gpuTimestamp:` twice around a sleep and finding the GPU and CPU deltas equal to the tick
   (`gpuDelta=21721000` against `cpuDelta=21721000`). What is not:

   ```text
   workload                                          small            large          ratio
   128 vs 1 fullscreen draws, 1024x1024              31,320 ticks     14,644 ticks   0.5
   4096x4096 vs 512x512 clears (before the draws)    ~31,000 ticks    ~16,000 ticks  0.5
   ```

   More work reports **less** time, and neither magnitude is near what the work must cost - 128 megafragments
   cannot be under a millisecond, and one fullscreen clear of 64 MiB cannot be 16 microseconds. Both roads were
   tried and both behave the same way: the command buffer's `writeTimestampIntoHeap:atIndex:` and the render
   encoder's `writeTimestampWithGranularity:afterStage:intoHeap:atIndex:`. The header's own wording for the first
   is the hint - "work after this call may or may not have started" - so what it marks is where the command
   processor has reached and not where the GPU has finished.

   **The mechanism is now measured, and it is order.** A third shape brackets one pass per draw count, ascending,
   each with its own encoder's after-fragment stamp:

   ```text
   1 draw -> 35,008 ticks    16 -> 249,857    256 -> -227,076    4096 -> 226,983
   ```

   The third stamp is **earlier** than the second by about 227,000 ticks, in **every** probe - 6 of 6 at
   `Precise` and 4 of 4 at `Relaxed` - and the last stamp lands within a hundred ticks of the second. So the
   stamps are not in submission order, systematically, and **it is not the granularity**: the header's warning
   that `Precise` "may cause splitting of command encoders" was the right kind of candidate and the reading rules
   it out, because both granularities give the same curve. The absolute values are a plausible machine clock
   (~4.7 hours of nanoseconds, the unit the sampler measured) and the range resolve returns exactly the values
   the per-entry road does, so neither the clock nor the packing is what is wrong.

   **The explanation that followed - overlap - was tested and is wrong**, and so are the two after it:

   ```text
   explanation given   the passes wrote different attachments and nothing read either, so their fragment work
                       could overlap and an after-stage stamp is not an order
   the test            every step writes ONE texture, the first clearing it and each later one LOADING what the
                       step before stored - pass N cannot begin until pass N-1 has stored, which no GPU may
                       reorder, and it is the smallest dependency this API can express
   the result          the stamps invert in exactly the same place, by the same ~226,000 ticks
   ```

   The header's warning that `Precise` "may cause splitting of command encoders" was the second candidate and is
   also gone - both granularities give the same shape. The third was that the inversion follows the work, and the
   curve run **descending** settles it:

   ```text
   ascending    1 -> 35,008    16 -> 249,857    256 -> -227,076    4096 -> 226,983
   descending   4096 -> 270,315  256 -> 708      16 -> -127          1 -> -96,434
   ```

   The inversion stays at **entry 3** whichever way the counts run, so it is a property of the entry's position
   and not of what the passes drew; its magnitude collapses from ~226,000 ticks to ~120 when the heavy steps come
   first, so what moves it is the work *around* the entry rather than the entry's own count. Two stamps 120 ns
   apart are not an order either - they are two events at one sampling point.

   What is left is that the sampling point is the **driver's rather than the caller's**, which is what
   `Relaxed`'s own documentation says of itself ("it may sample at command encoder boundaries") and what the
   numbers now show of both. A difference between two of these stamps is therefore not the work between them, and
   **no per-pass GPU time is reported from this road** until one is found that samples where it is told to. The
   smoke stays red for that reason, and a smoke that went green by keeping the two ends that agreed would be
   reporting a per-pass time that is not one.

   **What this closes and what it leaves.** Section 90's acceptance is "increasing shader work, reported GPU work
   increases", and the honest verdict is **NOT MET for a per-pass interval** - what is met is that the heap, the
   resolve and the unit work, which is the instrument's plumbing and not its reading. Section 92 asks for three
   kinds of timing to be kept apart, and this is where they stand: CPU encode timing (measured), whole-command
   buffer driver timing (measured, `MTL4CommitFeedback.GPUStartTime/GPUEndTime`, which on this path is a whole
   frame because the frame is one commit), and **GPU counter timing (not available)**. The consequence for
   section 95 is explicit: its optimisation candidates - argument-table write dedup, residency batching, barrier
   narrowing, encoder reuse, allocator sizing - cannot be ranked by a per-pass GPU time, so each has to be judged
   by a whole-frame A/B and a CPU-side count instead, and any that needs per-pass attribution waits.

   What would still be worth trying is recorded rather than assumed: the GPU-timeline resolve
   (`MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:`), which puts the resolve
   itself in the command stream instead of on the CPU timeline; and one commit per bracket, cross-checked against
   that commit's `MTL4CommitFeedback` times, which would say whether the road attributes at command-buffer
   granularity even though it does not within one. Both are cheap; neither is a per-pass answer on their own.

   **The workload is proven present before the timing is judged**, which is what separates the two explanations:
   the large pass clears its attachment to black and draws the shader's colour, a pixel is read back, and every
   reading says `drawsLanded=true`. Without that check, "the draws cost nothing" and "the timestamps are not
   execution points" are the same measurement, and they are different faults.

   What is left to try, in the order the evidence suggests: the GPU-timeline resolve
   (`MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:`), which puts the resolve
   itself in the command stream; more than one entry resolved at once, since this smoke resolves one at a time;
   and the whole-frame road the frame path already uses (`MTL4CommitFeedback.GPUStartTime/GPUEndTime`), which does
   produce plausible per-frame times and may be the only attribution this API gives. **Until one of them
   brackets execution, no per-pass GPU time may be reported**, and the census stays red on this smoke so that an
   unproven instrument cannot look green.

16. **The Metal 4 frame's own cost varies between two arms of one session by 47.7%, which is wider than any
   effect the comparison is meant to resolve, so section 93's "Metal 4 is not slower than Metal 3" is NOT
   MEASURED.** Session `run/perf-ab4` (exit 0, `m3a, m4a, m3b, m4b`, `--frames 600 --settle 25
   --expect-target 3200x1800`, Complementary on the staged nether `PerfWorld`) measured Metal 3 twice at
   `wallP50 21.17` and `21.29` - **0.6% apart**, the harness answering the same number - and Metal 4 twice at
   `wallP50 16.93` and `25.01` - **47.7% apart**. The harness's own summary therefore reads `m4a -8.1%`,
   `m3b +1.5%`, `m4b +30.1%`, and none of those three is a finding.

   Two things were separated before the spread was registered as a residual rather than blamed on the machine.
   **The pace is taken from a different resource in each generation**: Metal 3's 600 frames wait on the drawable
   at a `0.06 ms` median and on the submission ring 1200 times at ~20 ms, while the Metal 4 arms wait on the
   drawable at `14.64`/`18.90 ms` medians and on the submission ring at `0.00`, so wall-clock time is not the
   same quantity across the arms. **But the pace does not explain the spread**: the two Metal 4 arms differ by
   `8.08 ms` of `wallP50` and by `8.06 ms` of `gpuM4P50`, the same magnitude on both sides of the encoder, so
   part of the difference is inside the frame's own cost. The counters do not account for it either - `blits
   5400` and `blittedMiB 101022.1` are identical to the digit in all four arms, `pipelineIdentities 333` and
   `pipelineKeys 333` in all four with `compiles 0`, every arm collected 600 feedbacks, and the remaining
   counters differ by 4-9% in the direction that makes the cheaper arm the one it is. **The adjacent fact that
   would matter is not in doubt**: the two paths draw the same 333 programs and do the same 5400 copy-backs of
   101022.1 MiB, so the comparison's own inputs are equal and only its timing is unstable.

   What would make the number readable is named rather than guessed: **more than two arms per generation** to
   bound the spread, or **a target the display does not pace** (the ring-depth question section 84 raised), since
   a drawable-paced Metal 4 arm measures the display's handover as much as the frame. Repeating this shape and
   reporting its first pair would be the mistake this blocker exists to prevent. The record is in the Performance
   section above and in `docs/metal4-migration.md`.

17. ~~**Minecraft's own GUI, HUD and text are not drawn by this path at all**~~ - **FIXED, and the mechanism is
   named.** The whole interface was missing on Metal 4 while the world rendered, reported from play and confirmed
   here. It was not the fragment stage, not blending, not depth, not culling, not the attachments and not a lost
   attachment: it was **one buffer copy that declared neither of its resources resident**, and on this API an
   undeclared resource makes a copy do nothing - silently, with no error and no fault.

   **The evidence that bounded it**, all measured in pack-free forced-Metal-4 sessions with the per-pass trace, the
   frame probe's counters and the render-target readback:

   - **the GUI is encoded.** The title screen's `GUI before blur` pass carries 7 indexed draws through
     `gui_textured`, `gui_text`, `gui` and `mojang_logo` into colour texture `0x7ab6ba3700` with
     `depth=true load=load store=store`, encoded before the present, and a world frame has the same pipelines in
     `GUI before blur` and `GUI after blur`;
   - **the target is the presented one** - the present's own trace names the picture it samples and it is that
     texture;
   - **the pass's writes reach the screen** - forcing that pass's colour attachment to be *cleared* to magenta made
     the whole window magenta, which proves the load action, the store action, the encoder order and the present;
   - **the GUI's fragments were never produced.** Five probes, one session each, changed not a single sampled
     pixel: the front-facing winding set to Clockwise, every draw's cull mode forced to `None`, every pipeline
     built with blending disabled, the alpha-0 `discard_fragment()` removed from every fragment shader, and **the
     GUI pipelines' fragment colour forced to magenta**. The last is decisive: magenta buttons and glyphs would
     appear if the fragments existed at all;
   - **the vertex stage's state was right on paper** - the plan, the vertex fill (table slot 2, `stride 24`,
     `slice offset 0`), the MSL's attribute and buffer indices, and the uniform *contents* read back correct (the
     GUI's orthographic projection and an identity with `z=-11000` at byte offset 256 of the dynamic-uniform ring);
   - **and the vertex offset was not it**: emulating the draw's base vertex as a shift of the vertex buffer's
     address - which selects the same vertices if the base vertex is honoured - left the frame byte-identical, so
     the base vertex was being applied. That probe was reverted.

   **What the vertex buffer being unreadable from the CPU said.** Reading back what the bound buffer holds is what
   a draw's correctness finally rests on, and that reading came back `unreadable:IllegalStateException`: the GUI's
   vertex buffer is **not CPU-visible**, so the game cannot be filling it directly and must be filling it through
   this backend's copy road. The vanilla source says exactly that -
   `net.minecraft.client.renderer.StagedVertexBuffer` maps a CPU-visible **staging** buffer, writes the frame's
   vertices into it, and moves them into the real vertex buffer with
   `commandEncoder.copyToBuffer(staging.slice(...), vertexBuffer.slice(...))`, then draws each range with a
   **base vertex** into the moved block. That is one call.

   **The fault.** `Metal4FrameEncoder.copyToBuffer` was the one copy road in the class that called
   `useResource` on neither end, where `writeToBuffer`, `writeToTexture`, `copyBufferToTexture`,
   `copyTextureToTexture` and `copyTextureToBuffer` all declare both. The Metal 4 header asks a copy's resources to
   be marked in an `MTLResidencySet`; an undeclared one makes the copy do nothing. So the GUI's, the particles' and
   the entities' vertices arrived as **zeros**, every triangle of them collapsed to a point, and the draws were
   encoded, bound, stated - and invisible. The world rendered because Sodium fills its own buffers and because
   every other upload road declared what it moved. **The lesson is the header's own sentence** - every road that
   moves bytes declares both of its ends - and it is now a contract rather than a memory.

   **The fix, and the reading that proves it.** `copyToBuffer` declares both ends. Forced Metal 4, title screen,
   one session each, the presented picture's own readback:

   ```text
                                       mean BGRA       the GUI's own samples in the 5x5 grid
   before   metal4                     (19, 17, 11)    none - the panorama only
   after    metal4                     (40, 39, 33)    ff3f3f3f, ff9ea2ad, ff000000
            metal3 (the reference)     (40, 39, 33)    ff3f3f3f, ff9ea2ad, ff000000
   ```

   The two generations now read **identically** on that screen, sample for sample, with only the animated
   panorama's phase differing in the background - and `ff3f3f3f` is the button sprite's grey, `ff9ea2ad` the logo's
   light grey and `ff000000` the glyph outlines and the dim overlay around them. An in-world session with the same
   fix renders its world with no fault, no refusal and no restart. **What is still NOT MEASURED**: an in-world
   *text* reading taken on its own (the staged world's player is in spectator mode, which hides the HUD, and this
   machine refuses to press keys) - the in-world HUD and its text are drawn by the same `GuiRenderer` through the
   same `StagedVertexBuffer` road this blocker was about, and the title screen's own glyphs are read back
   identical to Metal 3's, but the in-world frame has not been read for them separately.

## Metal 4 full-frame implementation complete?

**NO, and the first full-frame milestone is behind it.** A forced Metal 4 launch loads a world, renders it and
presents it - nine thousand frames, 300 fps, no fault, no restart, no refusal - the harness collects the run from
this path's own counters, and a Vitrail fixture pack's fullscreen passes now run through this path too, with its
per-attachment facts reaching the pass descriptors and the elision they ask for measured at Metal 3's own figure.
What is **not** established is that any of it *looks* right, and the observation road has changed under that
question since it was first written: **the picture column the harness collects is not evidence in this environment** - the display captures of the four-arm session `run/perf-ab5` are photographs of the browser window in front of the game, not of the game, and its 88%-of-pixels-differ readings are that and nothing else. What carries the question instead is the frame's
own readback: the layer is built with
`framebufferOnly` off behind `-Dmetallum.drawableReadback=true`, and each generation now copies **both halves** of
the frame it presents (the picture the present triangle sampled and the drawable it wrote) into a shared buffer,
read when that slot's submission completes and printed through one formatter. On the `compute-storage-contract`
fixture that road says: the fixture's acceptance colour arrives on both arms, on both arms the picture read is the
drawable written frame for frame, and the Metal 4 frame carries **alpha 0** where the Metal 3 frame carries alpha
255. On a second, diagnostic fixture whose four quadrants are four different colours at alpha 0.5, it says more:
**orientation is proven and the two roads agree** (the present draw swaps the two ends of the memory-vertical
axis and nothing else, quadrant for quadrant, and the RGBA8-to-BGRA8 channel conversion is correct on both), and
**the alpha is not the pack's** - the shader's alpha moved from 1.0 to 0.5 and the stored alpha did not move on
either arm. So "does it look right" is now measurable in the pixels rather than blocked on the display - and it is
measured where it can be, not finished: which writer owns the presented target's alpha, and why the two roads
disagree about it, is not localised, and no other fixture's picture has been read. The counters, the client's own
chain lines, the readbacks and the absence of a fault are what the frame is known by.

**And the question "does it look right" now has a first answer, from a session in which the game's own interface
was looked for and not found.** On a forced Metal 4 launch the world draws and **Minecraft's GUI does not** -
neither the title screen's buttons, logo and text nor the in-world HUD - and `docs/metal4-migration.md` carries
the measurement. The state of this path is therefore read as its parts rather than as one verdict:

```text
Metal4 no-pack world geometry:      PASS
Metal4 title-screen GUI + text:     PASS   (blocker 17 fixed; reads back identical to Metal 3)
Metal4 in-world GUI/HUD:            PASS by construction (same GuiRenderer, same StagedVertexBuffer road);
                                    an in-world text reading of its own is NOT MEASURED
Metal4 text/glyph rendering:        PASS on the title screen; the same NOT MEASURED in a world
Metal4 full-frame correctness:      NOT READY - the GUI was one of its blockers, not the last
```

**The pause on the compute pipeline neutralisation is lifted.** It was paused because blocker 17 was a correctness
failure that made every later comparison meaningless; with the road fixed and the reading equal to the reference
generation's, the programme resumes where it stopped. **What blocker 17 leaves behind is a lesson that is now a
contract**: every road that moves bytes declares both of its ends resident, because on this API an undeclared
resource is a copy that does nothing and says nothing.

What has been done, in the plan's order: the Metal 3 bookkeeping, the cold-probe harness, the Metal 4 provider
(queue, state, encoder, clears, copies, fence, indexed and indexed-indirect draws, residency, presentation in the
frame's own command buffer), all five native render smokes, the binding model through argument tables, the
per-attachment contents facts delivered to the pass descriptors **and proven on the device through a Vitrail
fixture pack**, the attachment counter made a function of the descriptor and extended over every pass this path
opens, the capability dispatch that had been hiding the contents half, and the compute road - one shared
translation, this generation's compile, and a dispatch that is an argument table - which Vitrail's
`compute-storage-contract` now encodes twice per frame on a forced Metal 4 session; the MRT fixture's four
attachments have been read off the presented frame on both arms; and the read/write synchronization matrix is
closed - all seven of section 60's fixtures and all three of section 61's directions measured on the device, with
every field 50 of 50 in the cold census. What is **not** done is the rest of the Definition of Done: the rest of
the smoke-pack staircase (the deferred, shadow and history packs beyond the three fixtures whose pixels have been
read), blit inside a live frame, resize, pack reload, dimension change, shutdown, the lifecycle gate, MetalFX
Spatial on this generation, GPU counters and Metal 4 performance - the latter two have now been run and are
**measured to be unmeasurable as the instruments stand**: the counter road samples where the driver chooses and
not where the caller does (blocker 15), and the four-arm performance session's Metal 4 arms disagree by more than
the effect it was asked to resolve (blocker 16). **The real-pack ladder passes on all three rungs**: `MakeUp-UltraFast-9.5e` runs on both arms with the same
**330 pipeline identities**, the same gross picture and no fault of any kind in either log;
`ComplementaryReimagined_r5.9.1` with **334 identities and 714 compiles on both arms**, its compute dispatching
on both; and `photon_v1.3b` with **345 identities, 345 keys and 736 compiles on both arms** and both readback
roads agreeing to the byte, which needed the wide binding path below. The differences each rung shows are this
path's known ones (a pass per clear, 1.18x/1.29x attachment traffic, drawable-wait pacing) registered for the
performance
phase rather than read as verdicts. **and its second rung passes too**: `ComplementaryReimagined_r5.9.1`, a 219-file pack with deferred passes,
shadows and compute, runs on both arms with **334 pipeline identities on each**, a dispatching compute road on
each and no fault of any kind. That reading needed one instrument fix first - this path opened its dispatch
encoder without reporting it, so its compute counted as zero against the reference arm's 532 and the pack's
shadow compute looked absent until the counter was told about it, after which the same launch read 1893. **and its third rung does not pass**: `photon_v1.3b` serves 251 of its 607 pack units and then stops, because
one of its pipelines (`world0/deferred4`) does not fit MSL's direct binding slots and the translator's
fallback to Metal 3 argument buffers is refused on this generation - which binds through tables. M3 PASS /
M4 FAIL, localised to the exception line, and the fix is section 46-51's production binding path for a wide
pipeline rather than a flag. **And the pictures that have been read agree, now that blocker
10 is fixed**: the fixtures whose output the *pack* writes are right on both arms (the acceptance colour, the four
MRT attachments, the orientation), the frames the *game* draws are right too - the no-pack Metal 4 frame is a world
whose sampled terrain cells are the Metal 3 arm's own, and the depth fixture reads green at the geometry's edges on
both arms instead of cyan everywhere - and what is left is registered rather than claimed: the sky strip at the top
of the frame and the alpha channel, both waiting on a copy of the target at a pass boundary. The Definition of
Done's "no-pack frame passes" item is therefore measured rather than failing, and the smoke-pack staircase - which
section 67 stopped at the first M3 PASS / M4 FAIL - can resume from where it stopped. The remaining blockers above
are the list; AUTO stays off this path on the intermittent capability probe, and the migration's own success
criterion cannot be claimed until the pictures that have been read agree with the frames they are supposed to be -
which they now do, with two differences registered and neither of them a claim of correctness.

### And the real-pack ladder's third rung passes, on the wide binding path

`photon_v1.3b` was where the staircase stopped: M3 served the pack's whole chain in about ten seconds and drew it,
this path served 251 of its 607 units and then threw `requires wide Metal resources, but Argument Buffer Tier 2 is
unavailable`. That refusal was a design decision and not a gap - this generation asked the shared translator for
direct bindings unconditionally, on the reading that the argument *table* replaces the argument *buffer* - and the
measurement that ended it is in the refusal's own message once the message says what the layout was: photon's
`deferred4` is **nineteen sampled images behind one uniform buffer**, so the last sampler it asked for sat at index
19.

The table cannot hold that, and no amount of it can. `MTL4ArgumentTable.h` caps a descriptor at **sixteen** sampler
slots, the cold probe reports the same ceiling from the device's side ("seventeen direct samplers refused ... a
table asking for twenty sampler slots accepted"), and MSL declares one `[[sampler(n)]]` attribute per sampled
image with no way to pack two images onto one. That is section 51's distinction measured rather than argued:
argument-table capacity is not the shader's sampler indexing limit, and past sixteen the wide shape is the only
shape there is - on **both** generations. So the compiler now hands the translator the device's argument-buffer
answer, and what this generation adds is only how the buffer is handed over: the artifact asks the stage's own
function for an `MTLArgumentEncoder`, the pass makes a shared-storage, hazard-tracked buffer of the encoded length,
fills it through that encoder, and writes its GPU address into the table slot the shared layout recorded.

Measured on the same world, same width, both arms, 600 frames of counters:

```text
                        Metal 3      Metal 4 (before)   Metal 4 (after)
chain can draw            yes              no                 yes
Vitrail stopped           no              yes                  no
wide pipelines              1               0                   1
pipeline identities       345             167                 345
pipeline keys             345             167                 345
compiles                  736              --                 736
drawable mean BGRA   (44,62,55,0)         --          (44,62,55,0)
picture mean BGRA    (53,60,42,0)         --          (53,60,42,0)
```

Both readback roads agree with the reference arm to the byte on the 5x5 grid of a 2560x1440 frame, the program set
matches at 345 identities and 736 compiles, and the arm's log carries no error of its own - the three MSL failures
in it are the cold probe's own negative tests. The differences that remain are the registered ones and section 70's
exclusions: attachment traffic, one native encoder per logical pass, and far fewer per-resource binding calls
because one table slot now stands for a whole set (82,175 buffer binds against 111,340). The rung below was re-run
on both arms to check that the direct path did not move, and it did not: `ComplementaryReimagined_r5.9.1` reads
**334 pipeline identities and 714 compiles on both arms**, no wide pipeline in either log, both chains drawn, and
the same picture inside a temporal pack's cross-launch tolerance. MakeUp is direct-only by the same argument and
its previous rung reading stands.

So the ladder is **MakeUp PASS, Complementary PASS, Photon PASS**, and section 67 no longer stops it. What Photon's
pass does not say is that its frame is *right*: the readback grid is a 25-sample mean of a temporal pack across two
process launches, which section 116 forbids reading as a regression test. It says the pack compiles, draws and
presents with the reference arm's program set and the reference arm's gross picture.

**What this leaves open.** The wide path is one wide pipeline deep. Nothing else in the ladder is wide, so its
table sizing, its `ensureArgumentBuffers` order and its per-artifact buffer lifetime have one real-device reading
behind them and no second pack; Vitrail's `wide-resources-contract` fixture, which drives **thirty-three** sampled
images through a single pipeline, is the one that would test the shape harder, and it has not been run on this
path. And the argument-buffer writes are not deduplicated - every binding write re-encodes into the buffer, which
is correctness-first and section 50's order, not the finished shape.
