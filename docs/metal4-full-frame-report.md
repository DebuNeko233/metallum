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
Vitrail:  4380250f  (perf/optimisation; exactly the plan's reference) - that is STARTING_VITRAIL_SHA, unchanged
                    through every reading in this report, and Vitrail is unmodified at it
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

cold runs:        789 processes, 2786 probes (378 processes and 1619 probes through the compute round, then the
                  dependency round's two censuses and a six-process hunt, then a census and its four-process hunt,
                  then the later rounds' runs); capability failures: 4 all-time, every one of them at ATTEMPT 1 of
                  its process
                  **and this round's four runs added 160 processes and 240 probes with no capability failure at
                  all**: 30 + 50 + 20 processes (the last with five probes each) + 60, of which **160 probes were
                  first-in-process probes, every one correct** - which is section 14's Path B, not a resolution
warm probes:      1510 in forty-one processes  field failures: 18 all-time, all in one process of the
                  dependency round and all of them the storage-image smoke - whose shape was the fault: **317
                  probes in the round that closed that shape are green**, after the smoke was moved to a table per
                  dispatch and then to an encoder per dispatch. This round's three warm runs added 60 repeats and
                  no failure
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

**And two hundred and forty cold probes passed, which is section 14's Path B and not a resolution.** The harness
was run four times today on this machine, and no run subsumes another - the shapes differ in how many probes each
process runs - so all four are kept:

```text
run                                                cold processes  probes  failures  warm  warm failures
--cold-runs 30 --warm-runs 20                      30              30      0         20    0
--cold-runs 50 --warm-runs 20                      50              50      0         20    0
--cold-runs 20 --probes-per-process 5 --warm 20    20              100     0         20    0
--cold-runs 60                                     60              60      0         0     0
                                                   ----------------------------------------------
                                                   160             240     0         60    0
                   of which first-in-process probes: 160, all correct, each costing ~0.49 s
one cold probe costs ~0.5 s, and the probes after a process's first cost ~110-125 ms each
sampled draws, allocator rings, colour attaches, multi-targets, depth draws, depth samples, mip chains,
MetalFX spatial, compute, storage images, bound layouts, texture copies, depth clears, fence waits,
indexed draws, residency sets, indirect draws, compute->pass, compute->draw, copy->pass: 50 passed, 0 failed
GPU pass time: 0 passed, 50 failed
```

So the intermittency **did not reproduce in two hundred and forty cold probes**, the probe is fast enough to make that a
measurement rather than an occasion (half a second against the seventy a client launch costs, which was section
10's goal), and the failure **stays registered** as intermittent - section 14 forbids deleting it because the
harness could not reproduce it.

**What the two hundred and forty do and do not say, because the two are easy to run together.** They say the current probe
shape did not fail in two hundred and forty cold probes on this machine in this session, which is the strongest single
reading the harness can produce without a failure to localise. They do **not** say the fault is gone: no failure
means **no stage and no mechanism**, so nothing has been fixed, and the historical rate of about one in
twenty-five was measured with the **older probe shape** - the shape changed between that round and this one, and
the report already withdrew the sentence that read the old cold and warm rates as equally frequent for exactly
that reason. A fault that no longer reproduces in a shape that has changed is a fault whose status is
**NOT PROVEN either way**, and the honest sentence is the one section 14 asks for: not reproducible today, still
registered, still blocking AUTO. **And the shape of a first use in a process is measurable, even though the fault is not.** The third run put five
probes in each cold process - the harness's own `--probes-per-process`, which exists because *"one probe a process
cannot tell a process that is bad from a draw that went wrong"* - and the per-attempt times say what the recorded
hypothesis is about:

```text
process 1 attempt 1  490.7 ms   attempt 2  119.6 ms   attempt 3  110.3 ms   attempt 4  119.6 ms
process 1 attempt 5  112.3 ms   process 2 attempt 1  488.2 ms
```

**And the four-times cost is the *first* probe's, for every process in the run and not a warm-up of the machine.**
The last run was sixty processes with one probe each, so every one of its probes is a first-in-process probe, and
processes 1, 30 and 60 read 486.3, 494.2 and 500.8 ms - the same cost at the end of the run as at the start. That
is what makes it a per-process signature rather than a cold-machine one, and it is why the volume belongs there:
**160 first-in-process probes today, every one correct**, is the closest this harness has come to the window the
recorded hypothesis names.

**The first probe in a process costs about four times what the rest cost, in every process, cold or warm** - so
the thing the recorded hypothesis names, lazy initialisation on first use, is really there and has a signature.
What it does **not** do, in 240 probes across 160 processes today, is fail: a first probe that is slower and
correct is a different thing from a first probe that is wrong one time in twenty-five. That sharpens the
hypothesis rather than confirming it, and it says where the next attempt should look - the 4x window is where a
fault would live, and the experiment is the first pass alone, in volume, with `--probes-per-process` telling a bad
process from a bad draw.

**AUTO stays blocked** by it, `-Dmetallum.execution=metal4` stays forced and EXPERIMENTAL, and
Metal 4 development continues under it, which is what section 15 asks for.

Two details a reader of that block should not misread. The harness **exits non-zero on this run**, and the only
red line is `GPU pass time`, which was blocker 15 - and whose state has moved twice since: it went green when the
counter smoke's own three defects (a duplicated heap index, two sampling forms in one curve, and a first pass that
was both the clearing pass and the command buffer's first encoder) were fixed, and **it then went back to
NOT AVAILABLE when the same submission was finally read with a second and a third instrument** - the driver's own
window and the CPU's completion wait, against a fixed-cost control. The smoke itself still exits 0 on what the
road does answer, so this line is not what a fresh harness run fails on; see blocker 15 for the census that
withdrew the attribution claim. The capability probe's own cold failures are and were zero. And the first
hypothesis recorded above, **lazy driver initialisation on first use**, is still un-run: the experiment is a first
probe with a throwaway commit before the real sequence, or a first probe that runs only its first pass, and
neither has been tried. With fifty probes passing, the next useful shape for it is a harness that runs the
probe's first pass *alone* in a fresh process many times, because a fault that shows in one cold probe in
twenty-five needs volume rather than a client.

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

## Vanilla's own frame in the overworld

Every comparison this report had taken was a *pack's* frame, and every one of them set `renderClouds` false, because
a pack draws its own clouds. Vanilla's own rendering - clouds, the weather's particles, the mobs - was therefore
never in a frame that was measured, and the things a pack replaces are exactly the things a migration can lose
without noticing. Three switches on the harness and one tracked fixture close that gap, and this is what they read.

```text
--vanilla-clouds on|off     renderClouds: off is the default because a pack draws its own, and on is what a
                            measurement of the game's own rendering needs
--weather clear|rain|thunder  what the world is left holding, with the weather cycle off either way; rain is a
                            particle system of its own and this is how vanilla's particles enter a frame
--keep-entities             keep the mobs and block entities instead of taking them out (correctness, not A/B)
--vanilla-particles         stage tools/fixtures/vanilla-showcase: a world datapack whose tick function emits
                            twenty of the game's own particle types at the camera, every tick
```

**The fixture is staged from the repository and the run is refused if it does not load**, which is not tidiness: the
first version wrote the positional particle options (`particle minecraft:dust 1.0 0.4 0.1 1.5 ...`) and this game
version refused the **whole function** - `Can't parse particle options: No key scale in MapLike[{}]` - so the scene
staged, loaded as a datapack and emitted nothing at all while every line said the fixture had been copied in. The
harness now refuses an arm whose log does not say the pack was found or does say the tick function failed.

**Reading one: vanilla's own frame is drawn correctly by this path, clouds and particles included.**
`run/vanilla-clouds` - overworld, no pack, clouds on, weather clear, 600 frames, arms interleaved M3/M4/M3/M4:

```text
arm  gen  ms a frame  frames/s  own GPU time  wallP50  drawable wait p50  loadedMiB  storedMiB  depthAtt.  clearEnc.  renderPasses
m3a  M3     2.17       460.7      0.84 ms        1.32      0.02 ms          26921.3     79655.7     1800          0          1956
m4a  M4     2.54       393.8      0.90 ms        1.66      0.77 ms         106129.5    224781.8     5400       3000          2586
m3b  M3     2.16       463.2      0.86 ms        1.18      0.02 ms          26921.3     79655.7     1800          0          1956
m4b  M4     2.46       407.3      0.89 ms        1.54      0.87 ms         106108.2    224760.5     5400       3000          2580

pictures:  m3a vs m3b  0.02 mean, 0.24% of pixels differ     (the reference against itself)
           m3a vs m4a  0.02 mean, 0.21% of pixels differ
           m3a vs m4b  0.01 mean, 0.40% of pixels differ
```

**This path draws the game's own cloud pass, and it draws it as the reference does** - to 0.21-0.40% of pixels
against the reference's own 0.24% between two arms of one configuration. The GPU work is the same within 5% (0.84
and 0.86 against 0.89 and 0.90 ms) and the *period* is 13-17% longer, which is the same shape the pack sessions
showed: the difference is in the waits, not in the drawing (this path waits on the drawable, 0.77-0.87 ms at the
median where the reference waits on its submission index and its drawable wait is 0.02 ms).

**Reading two: the structural footprint on a vanilla frame is the same one the pack frames showed.** Five clear
encoders a frame against the reference's none, `depthAttachments` 3x, `loadedMiB` +294%, `storedMiB` +182%,
`renderPasses` +32%, and no viewport call at all where the reference makes ~4.3 a frame with one scissor a frame
against its ~4.3-6.3 - all of it section 62's deliberate first version (a clear is a pass of its own; each pass
loads what the one before stored), and none of it changed by clouds, rain or particles: the particles-and-rain
session reads the *same* `loadedMiB` to four digits (106130 against 106129). The traffic this path reports is its
own pass structure and not the scene.

**Reading three: with rain and particles in the frame, a cross-launch picture comparison is void, and that is
measured rather than assumed.** (This reading was taken with the fixture as it was then - particles emitted with a
spread and a speed. The fixture has since been rewritten to remove both, and the reading below says why that was
not enough either.) `run/vanilla-overworld` - same scene with weather `rain` and the particle fixture
staged: `m3a` against `m3b`, **two arms of the reference itself**, differ in **68.45% of pixels** (mean channel
difference 35.64), because rain streaks and particle positions are animated and two launches land on different
phases. The generation comparison in that session is 43.65 (M3 vs M4) - the same order as the reference's own 35.64
- so it says **nothing** about the path, and the counters are the reading there (the fixture loaded, the frame rate
is 208-360 a second against 400-460 with clouds alone, and the structure is the same as reading two's). What is
**NOT MEASURED** is a *deterministic* particle or rain scene: the fixture emitted at random offsets, so its pixels
moved between launches by construction, and a picture verdict on particles needed a fixture whose emission is
fixed.

**The deterministic fixture was then built, and it is still not deterministic - which is the second reading.** The
first fixture emitted each particle with a spread and a speed, so a copy with `0 0 0 0 1` after each position
became the second: no spread box, no speed, one particle, at a cell of a grid in front of the camera (local `^`
coordinates) with one cell per render family. `run/vanilla-grid`, same scene and flags:

```text
                                      mean channel difference   pixels differing   differing by more than 8
m3a vs m3b, no particles (run/vanilla-clouds)      0.02               0.24%               0.03%
m3a vs m3b, the still grid                         12.18              24.83%              19.24%
m3a vs m4a, the still grid                         12.14              24.85%              18.88%
m3a vs m4b, the still grid (the outlier arm)       14.80              42.02%              25.85%

and what the particles add, each arm against the same scene with none:
m3a 14.88 / 27.69%    m3b 5.92 / 17.35%    m4a 5.77 / 17.19%    m4b 8.21 / 40.77%
```

Three things are readable there and no more. **The particles are drawn on both generations**: each arm differs from
the particle-free scene by 5.8 to 14.9 of mean channel difference, so the fixture reaches the frame. **This path's
particle contribution is inside the reference's own spread** (m4a 5.77 against m3b 5.92 and m3a 14.88), so nothing
about it is generation-specific - and it cannot be, because the contribution's own spread across three arms is
2.5x, which is the phase of a randomly-lived field and not a renderer. **And a cross-launch picture comparison of
a particle scene stays NOT MEASURED**, twice over and now for a named reason: particle lifetimes are drawn per
particle, so which particles a frame holds depends on the tick the screenshot lands on. A picture verdict on
particles needs an emission whose *appearance* does not age - one tick's particles photographed while frozen, or a
static block-entity form - and neither is built.

**One more thing that session shows and the harness did not guard - and now does.** `m4b` read **10.68 ms a frame
against `m4a`'s 2.46** (its own commit feedback 4.23 against 1.11, its drawable wait 8.06 ms at the median): an
arm-level outlier of 433%, which section 115 says to discard, and nothing refused it because a session with two
generations in it skips the structural drift check by design. The comparer now compares each arm against the
fastest arm of **its own generation** and prints an `arm outlier:` line naming it: `run/vanilla-grid` exits 3 with
`m4b ... 4.35x`, `run/vanilla-clouds` exits 0 with nothing said, and `run/m4-four`'s 27.50 ms arm is named at
1.51x - the arm this report discarded by hand two rounds ago. The threshold is measured rather than chosen (this
path's own arms legitimately spread to 15%), and six checks are pinned and mutation-proved.

**The entity fixture was then built, and the path draws what it places - with the placement itself still not
settled.** The staged world holds no entities of its own, which is a measurement and not an assumption: with
`--keep-entities` the frame's passes a frame, its pipeline identities and its depth attachments come out the
still-life scene's to the digit. `tools/fixtures/vanilla-mobs` therefore summons five entities of five render
families - a pig, a cow, an armour stand, a dropped item and an experience orb - in front of the camera, each with
`NoAI:1b` so its pose does not move, staged from the repository, and each summon preceded by a `say` that names it
so the harness can refuse an arm whose scene never got them. `run/vanilla-mobs2`, clouds on, 300 frames:

```text
arm  gen  ms a frame  passes a frame  depth a frame  pipeline  identities
m3a  M3     8.30        4.00             3.00          3807        99
m4a  M4    12.45       11.75            15.25          9130        99
m3b  M3     8.30        4.00             3.00          3996        99
m4b  M4    12.45       11.73            15.23          9131        99

pictures, by band of the 3600x2338 capture (mean channel difference / share of pixels over 8):
band                m3a vs m3b       m3a vs m4a       m3a vs m4b
sky   (top 12%)     0.05 (0.1%)      0.09 (0.1%)      0.08 (0.1%)
middle (40-60%)     0.74 (1.3%)      1.90 (6.1%)      0.76 (1.6%)
lower  (70-90%)     0.05 (0.1%)      0.29 (1.4%)      1.21 (5.1%)
```

What that says, and what it does not. **Both generations draw entities**: this path opens 11.7 passes a frame
where its own still-life frame opened 4.3, and the still-life scene's numbers are the reference's here (4.0). **The
sky is identical across all four arms** (0.05-0.09), so the clouds and the sky account for none of this. **The
differences sit in the bands the entities are in, and not in the same band for the two Metal 4 arms**: m4a differs
from the reference in the middle (1.90, 2.6x the reference's own 0.74) and m4b in the lower (1.21), each agreeing
with the reference in the other. A renderer difference would sit in the same place in both arms, so this reads as
the *fixture's placement* moving between launches - and the fixture's own proof says why: a live session logged
"placed the pig" and "placed the cow" **every four to five seconds**, so a session's entity count is not the five
it asks for and the arms hold different numbers of them. **An entity picture verdict is NOT MEASURED, for a fixture
reason that is named and logged rather than suspected**, and a once-only placement is what the fixture owes next.

**And the entity scene was then made one placement, which turned that NOT MEASURED into a reading.** The
fixture's own proof is what found the fault: a live session logged "placed the pig" and "placed the cow" every four
to five seconds. The missing tag was `Invulnerable:1b` - the summons are at the camera's own height, which is not
necessarily above the terrain, and a mob placed inside a block takes suffocation damage every tick and dies, so the
`unless entity` guard found no pig a few seconds later and placed another. With `NoAI` (no movement, no look),
`NoGravity` (no falling), `Invulnerable` (no dying) and `PersistenceRequired` (no despawning) each type is placed a
**stable two times an arm** in every arm of two consecutive sessions, and the harness compares the arms' placements
with each other rather than against a constant the fixture does not control. What that buys is the reading this
scene was built for - `run/vanilla-mobs3`, clouds on, 300 frames, arms interleaved M3/M4/M3/M4:

```text
picture, m3a against m3b:  mean 0.02, 0.24% of pixels differ at all   (the reference against itself)
picture, m3a against m4a:  mean 0.02, 0.63% of pixels differ at all
picture, m3a against m4b:  mean 0.02, 0.88% of pixels differ at all
   - the same worst pixel, 218 at (3547,43), in all three

by band:                     m3a vs m3b      m3a vs m4a      m3a vs m4b
sky   (top 12%)              0.13 (0.1%)     0.10 (0.1%)     0.08 (0.1%)
middle (40-60%)              0.00 (0.0%)     0.00 (0.0%)     0.00 (0.0%)
lower  (70-90%)              0.02 (0.0%)     0.00 (0.0%)     0.03 (0.1%)
```

**So the entities are drawn identically**: the whole image agrees to the reference's own 0.02, the band the entities
occupy is **identical** (0.00) in both generation comparisons, and the one pixel all three disagree at is the same
pixel - which is what a cross-launch difference looks like and not a generation difference.

**And the block entities, which are neither terrain nor entities, are drawn the same too.** What a *block's own*
renderer draws - a chest's model, a bell, a banner's cloth, a shulker box, an enchanting table's book - had never
been in a measured frame. `tools/fixtures/vanilla-blocks` places five of them, and the way it places them is three
measurements old: `unless block ^1 ^1 ^4 minecraft:chest` never fired (the fixture's liveness line shows the
function running 1138 times in a sixty-frame arm with not one placement, so a block predicate does not resolve `^`
the way an entity's position does), `~` did not fix it either, and a four-way diagnostic separated the parts -
`if block ~ ~ ~ minecraft:air` never matches, at the server's position or the player's, while
`if block <position> minecraft:chest` matches as soon as a command has *placed* a block there. A block predicate
reads a position a command has made real, so it cannot guard the command that makes it real; the fixture therefore
places first and proves with an entity (a marker summoned once per block, the `say` firing while it is absent, the
`setblock` at the marker's own position every tick). `run/vanilla-blockents`, clouds on, 300 frames:

```text
picture, m3a against m3b:  mean 0.02, 0.45% of pixels differ at all   (the reference against itself)
picture, m3a against m4a:  mean 0.02, 0.27% of pixels differ at all
picture, m3a against m4b:  mean 0.12, 2.11% of pixels differ at all
   - the same worst pixel, 217 at (3547,43), in all three

by band:                     m3a vs m3b      m3a vs m4a      m3a vs m4b
sky   (top 12%)              0.07 (0.1%)     0.10 (0.1%)     0.27 (0.2%)
middle (40-60%)              0.04 (0.1%)     0.02 (0.0%)     0.34 (0.7%)
lower  (70-90%)              0.00 (0.0%)     0.00 (0.0%)     0.03 (0.1%)
```

**So the block entities are drawn on both generations**: one Metal 4 arm reproduces the reference to better than the
reference reproduces itself in every band (middle 0.02 against 0.04), and the other differs by 0.34 of mean channel
difference in the band the blocks occupy - 0.7% of pixels over 8, with the same worst pixel as every other arm. That
small difference is **NOT LOCALISED**: the only time-varying thing among the five is the enchanting table's book,
which is a hypothesis and not a reading, and separating it needs a scene without it.

**And the first pack configuration in which this path's two arms agree exactly is also the first in which it is
inside section 5's gate - which is a reading, not a verdict.** Every pack session before this one had a Metal 4 arm
17-49% slower than the reference; the fixture scenes made a pack scene available with vanilla content in it, so one
was run twice, Complementary with the entity and block-entity fixtures, 300 frames, arms interleaved M3/M4/M3/M4:

```text
                run/pack-vanilla (refused: content drift)   run/pack-vanilla2 (exit 0)
arm  gen  ms a frame   vs m3a    own GPU ms/frame    ms a frame   vs m3a    wallP50   own GPU ms/frame
m3a  M3     18.96       -             19.03            20.19         -        20.20        20.26
m4a  M4     19.06      +0.5%          16.77            20.64       +2.2%      16.86        18.09
m3b  M3     19.43      +2.5%          19.50            20.42       +1.1%      20.39        20.49
m4b  M4     22.97     +21.1%          22.93            20.64       +2.2%      16.84        19.14
```

The repeat is the one to read: **this path's two arms are identical to two decimals (20.64 and 20.64) and both
2.2% above the reference, whose own arms differ by 1.1%** - inside the `<= ~3%` section 5 asks for before AUTO.
Three things about it are worth more than the number. **This path's own GPU time is *lower* than the reference's**
(18.09 and 19.14 against 20.26 and 20.49 ms a frame), so the 2.2% is not GPU work and cannot be read as one. **Its
median frame is *shorter* than the reference's** (16.86 against 20.20) while its mean is longer, which is a
distribution that is more skewed rather than uniformly slower. **And the comparable counters agree exactly**
(`pipelineIdentities 333` in all four arms, `blits 2700` and `blittedMiB 50511.0` to the digit) where the native
call counts do not (24213 against 12670 pipeline sets, six clear encoders a frame against one) - section 70's rule
holding on a real pack. The first session of the pair is refused by the comparer for content drift between arms of
one generation (7-11%), which is the pack's own variability and section 116's warning; its 21% arm is why a repeat
was needed before any of this was writable.

**And the repeatability the gate rests on can now be bounded, because there are enough recorded sessions to do
it.** Every session whose arms of one generation were the *same configuration* - which is what a repeat is, and a
session whose arms differ by a switch is not one - read from disk, 29 generation-sessions in all:

```text
Metal 3, 11 sessions   1.00x  perf-ab6, nopack-ab1, vanilla-mobs3, vanilla-blockents
                       1.01x  pack-vanilla2, vanilla-clouds           1.02x  pack-vanilla, m4-ab7, perf-ab4
                       1.10x  perf-ab5                               1.32x  vanilla-overworld (the rain-and-
                                                                             particles scene, whose content moves too)
Metal 4, 18 sessions   1.00x  pack-vanilla2, m4-content, m4-passtimes, nopack-ab1, vanilla-blockents
                       1.01x  vanilla-mobs3    1.03x  vanilla-clouds  1.11x  m4-rings2
                       1.15x  m4-ab7, vanilla-overworld              1.18x  m4-loadtrace    1.19x  perf-ab5
                       1.21x  pack-vanilla     1.23x  m4-gputrace    1.34x  m4-stats
                       1.42x  perf-ab4         1.50x  perf-ab6       1.51x  m4-four
```

**So the same configuration repeats to 1.00-1.10x on the reference and to 1.00-1.51x on this path, in the same
sessions and on the same machine** - and this path *can* repeat exactly, in six of its eighteen sessions. That is
the sharpest form blocker 16's question takes, and it is why the gate is not met on one good session: a
comparison whose two arms can differ by half is a comparison whose answer is a range, and the range is wider than
the effect section 5 asks about. What the wide sessions have in common is not the load samples - `perf-ab6`'s
arms began at 4.3 and 4.3 and differ by 1.50x, `m4-stats`' slow arm's load *fell*, `m4-gputrace`'s fastest arm's
load *rose* - and the outlier guard now names the arm in each of those cases rather than averaging it in.

**What is NOT MEASURED**, said plainly because the surface is now wide: a particle or rain scene whose picture can
be compared across launches; what the one block-entity arm's small middle-band difference is; whether that 2.2% is
what a pack scene *is*; and **what makes this path's arms differ by up to half while the reference's agree** -
which, after eighteen sessions, is the single question standing between this report and section 123's performance
item.

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

render→compute:      MEASURED in the synchronization matrix below rather than here - a compute dispatch that
                      samples a texture a render pass wrote, and a compute dispatch that writes a storage image a
                      later render pass samples. Both are section 60's fixtures and both are green; this section
                      owns the dispatch road itself, which is the block above.
compute→render:      the other half of the same pair, and the same fixtures; the reading is that both
                      generations order the two the same way, which is what makes the pair a measurement rather
                      than an assumption.

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

**And the configuration cache and the resize rebuild were re-taken after the copy-road fix, which is what section
124 asks for.** `tools/run-metal4-lifecycle-probe.sh m4fx ComplementaryReimagined_r5.9.1.zip metal4
resize@400,close@1200`, renderscale=55, one client, exit 0:

```text
Metal 4 MetalFX spatial scaling: available, the device supports it and made one
Metal 4 MetalFX spatial scaling: made a scaler for 1408x792 to 2560x1440 with colour format 70 and output format 70, 1 in the cache
Metal 4 MetalFX spatial scaling: made a scaler for 1760x990 to 3200x1800 with colour format 70 and output format 70, 2 in the cache
(Vitrail) The 55% render scale brings the picture back with MetalFX
presented extents: 2560x1440 for 2074 frames, 3200x1800 for 4430
Stopping! 1, BUILD SUCCESSFUL 1, teardown timeouts 0, chain drawn 1
```

So on this build: the capability is the device's answer rather than a version check, the Metal 4 factory makes the
scaler, **the cache is keyed by configuration (1 entry, then 2 for the new size)**, the resize produces a new
configuration and a new scaler, the presented extent follows the new scale, and the session ends cleanly with no
teardown timeout. **What section 124 still does not have**: the *failure* path falls back safely (no scaler was
ever refused in a session, so the fallback is code and not a reading), the output orientation is proven on the
device (40 of 40) and **not in a live frame** (blocker 17's note), and no asymmetric fixture has been scaled
through the frame path.

**And the fallback was then probed for, which is how the *shape* of that gap was found rather than guessed.** A
diagnostic was added that makes this generation's capability answer **no** as if the device had
(`-Dmetallum.probeNoMetalFx=true`), and the session it produced did not reach the frame path at all:

```text
the device does not satisfy the Metal 4 minimum contract (the request was -Dmetallum.execution=metal4)
Failed to create backend Metal
Metal device initialization failed (metallum.execution=metal4 was asked for and this device does not satisfy
    the Metal 4 minimum contract: ... metalFx=true ...), so this session will not run the Metal 3 reference
    path either
Using graphics backend OpenGL
```

The mechanism is in the capability record and it is deliberate: `metal4MinimumContract()` is the command
structure's own list and does not mention the scaler, but **eligibility is a second question** -
`metalFxParityForMetal4()` is `!metal3Scaler || metal4Scaler`, so a device that can scale on Metal 3 and cannot
on Metal 4 is **refused Metal 4 rather than demoted to a path that cannot scale**. So:

- **section 124's "failure falls back safely" cannot be reached by removing the capability.** The gate refuses
  the generation before a frame is drawn; the road that *is* reachable is the per-configuration refusal - a
  scaler that fails to *create* for one size, which is what `Metal4Fx.refused` holds and what a reading would
  have to provoke. That is the honest status of the item: not a reading nobody took of a road nobody drives.
- **and the clause is not an AUTO risk, which was checked rather than assumed.** `AUTO`'s eligibility is
  `metal4MinimumContract() && metal4CommandBuffer() && metal4RenderEncoder() && metal4ArgumentTable() &&
  metalFxParityForMetal4()`, so a device that scales on Metal 3 and not on Metal 4 is **demoted to the reference
  path** with `whyNot` naming the clause - the safe direction, and the reason the parity clause sits in the
  eligibility expression rather than only in the refusal message. Writing it out matters because
  `metal4MinimumContract()` alone does *not* carry it, so a reader of that method would expect Metal 4 to be
  selected on exactly the device where the selector says no. The consequence of the clause is therefore confined
  to the **forced** road, which is the behaviour section 76 owns and which this reading deliberately leaves alone.

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

**The GPU percentiles, which section 121 asks for beside the wall ones, from the two sessions on disk.** Each
generation reports its own API's numbers and they are printed as collected rather than converted - a report that
put `gpuP95` and `gpuM4P95` in one column would be claiming section 92's rule has been established:

```text
                    wallP50  wallP95  wallP99   gpuP50  gpuP95  gpuP99   gpuM4P50  gpuM4P95  gpuM4P99
no-pack  m3a          8.23     9.36     9.47      2.21   2.38    2.42        -         -         -
run/nopack-ab1 m4a    8.48     9.13     9.53       -      -       -        2.55      2.75      2.78
         m3b          8.37     8.98     9.42      2.21   2.40    2.42        -         -         -
         m4b          8.40     8.94     9.48       -      -       -        2.52      2.70      2.75

pack     m3a         21.07    22.65    22.95     21.06  22.25   22.42        -         -         -
run/perf-ab6 m4a      9.51    37.45    37.83       -      -       -       18.55    19.41     19.50
         m3b         21.02    22.66    23.02     21.04  22.23   22.35        -         -         -
         m4b         27.04    54.74    56.02       -      -       -       27.74    28.90     29.05
```

Read together with the pacing above, the percentiles say the same thing the medians did: on the no-pack scene
both generations are settled and tight (a 0.2 ms spread from P50 to P99), and on the pack scene Metal 3's arms
stay tight (21.07 to 22.95) while **this path's own GPU numbers are as stable as Metal 3's within an arm**
(18.55 to 19.50, and 27.74 to 29.05) and the arm-to-arm difference is the machine state the two sections above
are about. Nothing in that pair of columns is a Metal 3 against Metal 4 verdict, for the reason section 92 gives
and the two spellings here repeat.

**And the no-pack frame - section 37's first comparison - was taken between the two generations after the copy
road was fixed, four arms in one session on the staged `PerfWorld`, window 1600x900, `--frames 600 --settle 25`
(`run/nopack-ab1`, `--no-pack`).** Every arm reports the Metal backend and its own generation
(`selectedGeneration=metal4 executingGeneration=metal4`, and metal3's own), no arm has a GPU fault, a restart or
an `Unimplemented` line, and every arm drew the world rather than a screen: 4 render pass openers a frame and
47.5 MiB of attachment traffic a frame on the Metal 3 side, 6.3 openers a frame on this one.

```text
counter                        m3a        m4a        m3b        m4b      M4/M3
wallP50 (ms)                   8.23       8.48       8.37       8.40     +3.0%, +0.4%
wallP95 / wallP99              9.36/9.47  9.13/9.53  8.98/9.42  8.94/9.48
drawable wait p50 (ms)         7.57       7.55       7.57       7.57     the pace, in both
submitWindow wait p50          0.00       0.00       0.00       0.00
gpuP50 / gpuM4P50              2.21       2.55       2.21       2.52     not comparable - two APIs
pipelineIdentities / keys      99/99      99/99      99/99      99/99    equal
compiles / compileMs           0 / 0.00   0 / 0.00   0 / 0.00   0 / 0.00  equal
render pass openers            2400       3768       2400       3636     +57%, +52%
blit encoders                  960        1300       974        1300     +35%, +33%
compute encoders               0          0          0          0        equal
clear encoders (passes)        0          3000       0          3000     the pass-per-clear structure
clears folded into passes      1800       0          1800       0        the same structure, other side
loadedMiB                      28498.5    141350.1   28498.5    135549.3 x4.96, x4.76
storedMiB                      81232.9    260002.4   81232.9    254201.7 x3.20, x3.13
depthAttachments               1800       6168       1800       6036     x3.43, x3.35
depthLoadedMiB / storedMiB     0.0/39550.8 69609.4/135527.3 ...        this path loads the depth it clears
blits / blittedMiB             0 / 0.0    0 / 0.0    0 / 0.0    0 / 0.0  equal - neither needs one here
viewport sets / scissor sets   3000/3360  0/600      3000/3374  0/600    this path sets no viewport
presents                       600        600        600        600      every frame
```

Three readings and not one verdict:

- **The pace is the display's in both generations, and it is the same site in both**: `drawable wait p50 7.57 ms`
  against a `wallP50` of 8.2-8.5 ms, with the submission window paying `0.00`. So this scene is capped by the
  display's hand-over and the two generations agree to **3.0%** on P50 and within a tenth of a millisecond on
  P95/P99 - which is a *correctness* reading rather than a performance verdict, and the reason a no-pack scene
  cannot be one: there is nothing left to measure when the display is the pacer.
- **The structural differences are exactly the registered mechanisms and nothing new**: this path opens a pass per
  logical pass and a pass per clear (openers 2400 → 3700, clear encoders 0 → 3000 where Metal 3 folds 1800 clears
  into the passes that use them), and therefore loads and stores the attachments it clears. `pipelineIdentities`
  99 on every arm, `compiles` 0 on every arm and `blits` 0 on every arm say the two paths draw the same programs,
  in the same number, with no compilation and no copy in either.
- **The two GPU numbers are recorded and not compared.** `gpuP50` is `MTLCommandBuffer.gpuMillis` and
  `gpuM4P50` is `MTL4CommitFeedback.GPUStartTime/GPUEndTime`: two APIs, and section 92's rule that the timing kinds
  are not interchangeable until that is established still holds.

The picture column of this session is void - the display was locked, every capture is one flat colour and the
harness says so and ends non-zero for it - so no pixel of either generation was read here. The frames themselves
were read for the fix above, in sessions with the display in the same state.

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

**The first comparison in which the GPU was the bottleneck, and it is the first one this report can read as a
performance claim.** `run/m4-ab7`: one session, four arms interleaved in section 114's order (**M3, M4, M3, M4**),
Complementary on the same staged world, 3200x1800, 600 frames a window, 25 s of settle - and, new this round, the
accelerator's own statistics sampled every two seconds for the whole session (`tools/gpu-trace.sh`: the driver's
device/renderer/tiler utilization, its memory, and the pid of its most recent submission).

```text
arm  gen  ms a frame  wallP50  wallP95  own GPU P50     drawable wait          submission wait
m3a  M3     20.31      20.50    23.72   gpuP50   20.54   p50 0.01,  8 ms tot   1200 calls, p95 21.53, 11156 ms tot
m4a  M4     23.85      24.23    29.19   gpuM4P50 23.81   p50 15.36, 7191 ms tot    600 calls,         0.56 ms tot
m3b  M3     20.70      20.81    22.25   gpuP50   20.70   p50 0.01, 56 ms tot   1200 calls, p95 20.07, 11359 ms tot
m4b  M4     27.45      27.40    30.11   gpuM4P50 27.36   p50 0.49, 7138 ms tot    600 calls,         0.42 ms tot

from the same session's GPU trace: device utilization mean 100.0%, max 100%, in all four arms
```

- **The GPU was saturated in every arm, which is what makes the period a measure of work rather than of a
  pacer.** Every previous M3/M4 comparison in this report was taken on a frame that something else paced - the
  display's handover, or (with the display asleep) this path's own ring - and this one is not: 100.0% device
  utilization over 14-18 samples an arm, in both generations. **So the two generations are being compared as GPU
  work for the first time.**
- **This path asks the GPU for 16-35% more time per frame**: 23.85 and 27.45 ms against Metal 3's 20.31 and 20.70,
  by its own commit feedback 23.81 and 27.36 against 20.54 and 20.70. Metal 3 repeats to **1.9%**; this path's two
  arms are **15%** apart, so the honest form of the figure is a range and not a point - and even the cheap end of
  it is far outside section 5's "median regression <= ~3%". **Per section 97 this path therefore stays forced and
  experimental, AUTO is not enabled on it, and the next question is not "is it slower" (measured: yes) but "which
  of the frame's work is bigger"**, which needs a per-pass GPU attribution that the timestamp road was supposed
  to give. **The attribution was claimed in a later round and has now been withdrawn**: the per-pass table below
  reads the frame's own pass work at 378 us of this bullet's 19.4 ms window, and a two-instrument census of the
  same kind of submission (blocker 15) shows that number is a *front end* and not work - so this bullet's
  "16-35% more GPU time" is **NOT MEASURED as work**, and it is equally unproven that the 16-35% is made of the
  two pacing waits. What the driver's window is made of - wait or work - is the open experiment.
- **And the two generations are paced by different resources, which is a standing caveat on every wall-clock
  comparison here.** Metal 3's frame *is* its submission-index wait (1200 waits a window, p95 ~21 ms, totalling
  the window, with 8-56 ms of drawable wait); this path's is its **drawable handover** (7191 and 7138 ms a window,
  with ~0.5 ms of submission wait). So "Metal 4 is slower" and "Metal 4 waits somewhere else" are two statements
  about the same table, and only the first is a performance claim - the second is why the two columns are printed
  side by side rather than subtracted.
- **The pictures agree as well as Metal 3 agrees with itself.** `m3a` against `m4a`: mean channel difference 1.29,
  56.30% of pixels differ at all, 0.55% by more than 8, worst 222 at `(3540, 39)`; `m3a` against `m4b`: 1.40,
  57.72%, 0.94%, worst 222 at the same pixel; and **`m3a` against `m3b` - two arms of the reference itself -
  0.99, 52.09%, 0.40%, worst 222 at that same pixel**. The worst pixel is the same in all three, so the frame's
  difference between the generations is of the same size and in the same place as the reference's own
  arm-to-arm difference, on a pinned scene in one session. This is section 69's kind of reading and not a
  screenshot verdict: it says the two generations draw the same picture to within the resolution this scene has.

**The environment, which was invisible until this round's trace and is half of what these numbers are.** The
trace's last field is the pid of the driver's most recent submission, and during these arms it was almost never the
game's: this machine carries **Microsoft Edge (pid 67625)**, which is rendering the Web GUI this programme is being
driven through, **UURemoteServer (pid 925)**, a remote-desktop server that captures and encodes the screen, and
WindowServer. The same trace read the accelerator **85-87% busy between arms with no game running at all**. So the
GPU is oversubscribed by construction here - and, measured in the same session, the game still got 100% of it
during its own windows, so the M3/M4 figures above are not a contention artefact. What they are not is a
production frame rate on a quiet machine: section 123 stays unmet for that reason as well as for the range, and
the machine-state half of it is now named rather than suspected.

**And then the third kind of timing arrived, and it overturns the paragraph above - and then it too was
overturned, one round later.** `-Dmetallum.metal4PassTimes=true`
puts one command-buffer marker behind every pass this path opens and reads the intervals when the ring begins that
slot again - the road section 90's smoke proved, with the unit and the floor it measured. On the same pack, forced
Metal 4, 600 frames (**the table below is kept as the measurement it is, and every number in it is a marker
interval, which blocker 15's census shows is a front end and not the frame's work**):

```text
Metal 4 GPU pass time (GPU ticks between markers this path placed, never the CPU's encode time):
  frames=600 labels=43 totalUsAFrame=378.301 unread=0 floorUs=2.0
  top=[Vitrail world-1/composite1 241.068, Vitrail world-1/composite6 18.949, Vitrail shadow chunk 10.876,
       Blit render target 10.716, Vitrail world-1/deferred1 9.814, Vitrail world-1/composite 9.665,
       Vitrail chunk 9.230, Vitrail world-1/composite5 7.869] and 35 more
```

Three readings, and **the first two are both withdrawn below** - the round that added the cross-check read the same
kind of submission with two more instruments and found the table's numbers are not work:

- ~~**The frame's own GPU work is 378 microseconds.**~~ Every pass of the frame, marked and attributed:
  `world-1/composite1` alone is **241.068 us, 64% of the attributed time**, and the next heaviest is 18.949 us.
  **Withdrawn as a work claim**: a submission whose driver window is 18-21 ms and whose marker span is 0.45 ms has
  been measured directly - on the counter smoke, with a fixed-cost control - and the marker span is a constant
  **2.19-2.34%** of the driver's window while both sampling forms agree with each other and the area knob is not a
  knob (256 draws on 4096x4096 read 17,583-309,235 ticks; 1024 draws on the same attachment read 49-67). So this
  table is a *front-end* reading, the `241.068 us` pass is the pass that issues the most draws, and **no per-pass
  GPU attribution exists**. The eight-probe census is in blocker 15.
- **The commit window is not that work *alone*, and the header says why the two cannot simply be subtracted.**
  `MTL4CommandQueue`'s `waitForDrawable:` "schedules a wait operation on the command queue to ensure the display
  is no longer using a specific Metal drawable... before executing any subsequent commands" - a queue-level wait
  *inside* the commit, so `MTL4CommitFeedback.GPUStartTime/GPUEndTime` measures the wait for the display plus the
  work. What has changed is that the window is now the *trusted* half of the pair: on a submission with no
  drawable it reads a stable 18.5-20.7 ms across eight probes and agrees with the CPU's completion wait to within
  3%, against a per-commit fixed cost of 0.02-0.08 ms. **So the paragraph above is still wrong as a work claim,
  but for the opposite reason than this text said**: "this path asks the GPU for 16-35% more time a frame" cannot
  be dismissed as "two pacing waits" either, because the instrument that was used to dismiss it does not measure
  work at all, and the frame's window is not known to be dominated by a wait. The honest statement is that
  Metal 3 and Metal 4 delivered 49 and 42-46 frames a second in that session and **which of the two waits or how
  much work is inside Metal 4's window is NOT MEASURED** - it needs the wait separated from the work by an
  experiment (a frame committed with and without `waitForDrawable:`, or the GPU-timeline resolve), not by a
  subtraction.
- **And the instrument changes the thing it measures, which is section 91's case exactly.** Four arms of one
  session - reader off, on, off, on - read **21.79 and 21.80 ms a frame with it off and 19.37 and 19.45 with it
  on**: the markers make the frame **11% faster**, twice over. So the table is a diagnostic reading and never a
  performance verdict, the switch stays off by default, and what a marker between two passes does to the driver's
  scheduling is a question of its own - the first candidate this migration has for a *speedup* rather than a cost,
  and one that has to be measured as its own mechanism before it is believed. **This reading is unaffected by the
  correction above** - it is a wall-clock A/B with the markers as the only variable - but its interpretation is
  narrower now: the markers do not attribute the 11%, they only move it.

**What the encoded drawable wait is worth, measured by leaving it out.** The whole-submit interval
`MTL4CommitFeedback.GPUStartTime/GPUEndTime` is the number this report has used as "this path's own GPU time", and
the header says the `MTL4CommandQueue`'s `waitForDrawable:` "schedules a wait operation on the command queue...
before executing any subsequent commands" - so that interval *contains* the display's pacing. Section 51 of the
plan forbids calling it rendering work while that is unseparated, so a *diagnostic* switch
(`-Dmetallum.metal4NoDrawableWait=true`, off by default, logged once in the arm that sets it, and pinned in
`ci-metal4-provider.py` as read in exactly one place) leaves that one call out and changes nothing else.
`run/m4-drawwait`: Complementary on the staged world, 3200x1800, 600 frames a window, 25 s of settle, four arms
interleaved **normal, no-wait, normal, no-wait** - and the arms' own logs prove which submission each one
measured:

```text
arm           wallP50  wallP95  gpuM4P50  gpuM4P95   drawable wait (CPU)      ring wait (CPU)          window mean
m4-normal-a    24.98    40.66    24.26     25.56    p50 21.29, 10954 ms tot   p95 0.00,     0.50 ms     24.25
m4-nowait-a    16.59    37.31    18.44     19.30    p50  0.01,     8 ms tot   p95 16.84, 1021 ms tot     18.34
m4-normal-b    24.93    25.29    21.20     22.42    p50 18.14, 10469 ms tot   p95 0.00,     0.51 ms     21.67
m4-nowait-b    16.59    37.29    18.37     19.29    p50  0.01,     8 ms tot   p95 16.44, 1014 ms tot     18.33
```

Three verdicts, kept apart because they are three different strengths of claim:

- **MEASURED: leaving the encoded wait out moves the whole-submit interval by 2.9 to 5.9 ms** (24.26 → 18.44 and
  21.20 → 18.37), and it **moves the CPU's own pacing wait from the drawable handover to the ring slot**
  (17.4-18.3 ms a frame of `nextDrawable` becomes 0.01 ms, while the ring's slot wait appears at 1.7 ms a frame
  with a 16.8 ms p95). The structures are the same in all four arms - `metal4Presents 600`, `clearEncoders 3600`,
  `computeEncoders 0`, `blits 5400`, `blittedMiB 101022.1`, `pipelineIdentities 333` to the digit - with
  `renderPasses` within 4% and the content counters (`loadedMiB`, `depthAttachments`) drifting up to 16%, which is
  this pack's own variability and not the switch.
- **NOT PROVEN: that the 2.9-5.9 ms is *entirely* the wait.** The two waits are not the same quantity - the CPU's
  handover wait is 17-18 ms a frame and the interval only moves 3-6 ms - and the pacer moved, which is the
  caveat section 22 names: the no-wait arms are paced by the ring instead. The strong form the plan asks for
  (driver-window delta ≈ CPU drawable-wait delta, structures unchanged) did **not** hold, so the honest sentence
  is the one above and not "the frame's render cost is 18.4 ms".
- **DIAGNOSTIC ONLY, and the faster arm is not a candidate.** The no-wait arms are faster in wall time
  (24.98/24.93 → 16.59/16.59 ms P50) and their driver interval is stable to 0.4% where the production arms differ
  by 14% - and that is exactly why the switch must not ship: the presented *picture* changes with it (mean
  channel difference 1.38-1.40 against the reference arm's own 0.88; 17.7-17.8% of pixels differ by more than 2
  against 6.6%), the wait is the ordering the header asks for, and removing it changes the submission rather than
  the work. What the reading is good for is the next question: with the wait out, the interval and the period
  agree in both arms (18.44 against 18.34, 18.37 against 18.33), which is what a frame whose queue is the
  bottleneck looks like - and the production configuration adds 2.9-5.9 ms of pacing on top of it.

Two environment readings sit beside the table and are half of what these numbers are: the session's GPU trace
(`tools/gpu-trace.sh`, `run/m4-drawwait/gpu-trace.txt`) reads the accelerator 86-100% busy through the arms, with
Edge and the remote-desktop server on it as always, and no arm reports a `GPURestart`, a validation error or a
drawable error. So the *absolute* rates here are not production numbers, and the *deltas* between arms of one
session are the measurement.

**The two populations, and the quantum they are made of.** Blocker 16's question was what makes this path's arms
of one configuration differ by up to half while the reference's agree, and the first candidate the migration ever
named was the ring depth. `run/m4-pacing` is that experiment with the instrument it needed: six arms interleaved
**1, 3, 1, 3, 1, 3** slots (`-Dmetallum.metal4RingSlots=`), Complementary at 3200x1800, and a per-frame line a
frame (`-Dmetallum.metal4FrameTrace=true`) carrying the wall, the ring's slot wait, the drawable acquisition
wait, the encode span and the structure counters, with each submission's own driver interval paired to the frame
that submitted it (`M4_FRAME_COMMIT submission=`). `tools/metal4-pacing-analysis.py` reads those lines and
classifies the window's frames by what they waited on.

```text
arm        slots  wall P50   wall P95   driver P50   wait that paces the frame        corr(wall(N), drawableWait(N-1))
slots1-a     1     20.76      22.31       18.92     slot  p50 19.04 ms, 600 of 600             +0.03
slots1-b     1     23.03      24.22       21.21     slot  p50 21.29 ms, 600 of 600             -0.08
slots1-c     1     24.23      25.73       22.53     slot  p50 22.65 ms, 600 of 600             +0.18
slots3-a     3     25.24      41.04       27.67     drawable 15.0 ms a frame, 0 slot waits     +0.56
slots3-b     3     20.88      26.50       19.45     drawable 17.6 ms a frame, 0 slot waits     +0.82
slots3-c     3     24.66      32.31       21.24     drawable 18.3 ms a frame, 0 slot waits     +0.85
```

- **At the production depth the frame is paced by the drawable handover, and the ring's slot wait never fires:**
  0 of 600 window frames at each of the three depth-3 arms waited more than 0.5 ms for a slot (0.2 ms in total),
  where all 600 frames of every depth-1 arm did (19.0, 21.3 and 22.7 ms at the median). So the two configurations
  do not differ in how much the frame waits, but in *what it waits for*.
- **And the period is quantised by that handover.** Every depth-3 window is two-peaked - `slots3-b`'s wall
  histogram is 210 frames at 16-18 ms and 208 at 24-26, `slots3-c`'s 138 and 261, `slots3-a`'s 52 and 185 with a
  further 99 at 32-34 - and the drawable waits cluster at about **7, 15 and 23 ms**, i.e. one, two and three
  quanta of an **~8 ms** cadence. This is a 120 Hz panel (built-in Liquid Retina XDR, ProMotion), whose handover
  interval is 8.33 ms, so a frame's period lands on two or three of them: **16.7 or 25.0 ms, which is a ratio of
  1.50 - exactly the widest same-configuration arm ratio the eighteen-session bound measured (1.51x)**. The
  mixture ratio is what differs between launches, and that is the "up to half" this report has been asking about.
- **The mechanism is confirmed by the pairing, not only by the shape.** The wait a frame pays is inside its *own*
  period, so the paced pairing is the previous frame's handover against this frame's wall:
  `corr(wall(N), drawableWait(N-1))` is **+0.56, +0.82 and +0.85** at depth 3 and **+0.03, −0.08 and +0.18** at
  depth 1, where the same-frame correlation at depth 3 is −0.05, −0.46 and −0.39. One slot removes the pairing
  because every frame waits for its own previous submission and the CPU can never run ahead of the compositor;
  three let it, and the handover decides.
- **At depth 1 the distribution is one narrow population** - `slots1-b` puts 473 of its 600 frames in a single
  2 ms bucket and 69 more in the next, with a P95/P50 of 1.05 - which is what a frame whose period is its own
  submission looks like.

**What this does and does not close.** Section 33's first form is satisfied: **the two populations come from the
drawable handover's quantum**, measured by the pairing, the peak spacing and the disappearance at one slot. What
it does *not* yet give is the collapse of the across-arm *mean*: in this session the three depth-1 arms read
20.76/23.03/24.23 ms (1.17x) against depth 3's 25.24/20.88/24.66 (1.21x), where the earlier `run/m4-rings`
sessions read 1.05-1.06x at one slot. So the *shape* is explained and the *mean* is not yet controlled to the
1.0x the gate wants, and section 30's consequence is written into the protocol below rather than assumed away: a
production-depth comparison may not read a P50 as a renderer cost, because its mixture is the display's.

**The scaler's live-frame orientation, read off an asymmetric fixture.** Section 124's remaining item was the
orientation of a frame the client drew and presented *through the scaler*, and the obstacle was that no fixture in
the tree painted an asymmetric pattern: a flat colour or a gradient can come back flipped, cropped or
channel-swapped and still look right. So `tools/fixtures/metalfx-quadrant` is a one-pass pack that paints four
quadrants split at the middle of **both** axes - **top left red (alpha 1.0), top right green (0.75), bottom left
blue (0.5), bottom right yellow (0.25)** - and the harness now stages a *directory* pack into a zip, so the
fixture lives in this repository where a reader can check it against the picture it produced. It is run at
`--renderscale 55`, which is what puts the scaler on the path: the input is 704x396 for a 3200x1800 target, so
input and output resolutions differ and the 1:1 road is not what is being measured.

`run/m4-metalfx-live`, both generations, 600-frame windows, `-Dmetallum.drawableReadback=true` - the presented
drawable read through the same code on both arms, five by five samples with the top row first, ARGB:

```text
arm   drawable readback, 5x5, top row first (ARGB hex)                                     mean BGRA
m3    ff430000 ff8b0000 ff8b1b00 ff008b00 ff004300   ff8b0000 ffda0000 ffcb2800 ff00db00   49, 100, 99, 255
      ff008b00   ff940012 ffd9001a ffa01940 ff27f400 ff1ba600   ff00008c ff0000db ff2828cb
      ffdcdc00 ff8c8c00   ff000043 ff00008b ff1b1b8b ff8c8c00 ff434300
m4    byte-identical to m3, all twenty-five samples                                        49, 100, 99, 255
```

- **Orientation: PROVEN with the scaler in the loop.** The four corner samples are the fixture's four quadrants in
  the fixture's arrangement - `ffRR0000` red at the top left, `ff00GG00` green at the top right, `ff0000BB` blue
  at the bottom left and `ffRRGG00` yellow at the bottom right - and the two arms are **identical sample for
  sample** (the harness's own picture comparison agrees: mean channel difference 0.02, 0.03% of pixels differ).
- **Channel order: PROVEN** (the components land in R, G and B as written; a swap would move two quadrants).
- **Crop: none observed** - all four quadrants are present at the corners of a 3200x1800 drawable drawn from a
  704x396 input.
- **Alpha: NOT the fixture's, on either arm** - every one of the twenty-five samples reads alpha `ff` where the
  fixture wrote 1.0, 0.75, 0.5 and 0.25. Equal across the generations, so this is not a Metal 4 fault in this
  configuration; it is the present/layer road, and it is recorded rather than explained. It also narrows the
  older alpha residual rather than closing it: that reading (M4 flat with alpha 0 where M3 was opaque) was taken
  on a different fixture and a different scene.
- **A smooth brightness modulation is present and identical in both arms**: the corners read about 0.26 of the
  written colour and the interior about 0.85, with the whole-frame mean at 0.78 of the four quadrants' mean.
  Mechanism NOT LOCALISED, and it is not a generation difference - which is the point of reading both arms.

**And section 40's transitions are MEASURED, in `run/m4-lifecycle`**: the Metal 4 path made a scaler for
**1408x792 to 2560x1440** and, in the same session, one for **1760x990 to 3200x1800** - the second line reporting
`2 in the cache` - so the configuration identity separated a render-scale or a resize change and a new scaler was
built rather than an old one reused, and no third configuration was ever created (a cache *hit* makes no scaler
and logs nothing, which is why the cache-size field is the evidence). The cache is keyed by the whole
configuration record and creation is behind the miss: both are contract-pinned in `ci-metalfx.py`.

**The §93 ladder, first rung: MEASURED, once the window could say what it sampled.** `run/ticks-nopack` is the
same six-arm M3/M4 interleave with the tick instrument in the line, and every guard passes: no scene drift, no arm
outlier, and the picture comparison inside the reference's own spread (`m3a` against `m4b` 0.48% of pixels differ,
against `m4c` 0.64%).

```text
arm   wall P50   wall P95   wall P99   wallMax   own GPU interval   drawable wait p50   ticks   frames/tick
m3a     8.33       8.87       8.97      11.79      gpuP50 7.60          7.71 ms          100       6.00
m3b     8.33       8.83       9.02      13.40      gpuP50 7.61          7.64 ms          100       6.00
m3c     8.33       8.88       9.13      11.69      gpuP50 7.60          7.66 ms          100       6.00
m4a    13.56      15.94      16.11      16.21      gpuM4P50 2.68        9.50 ms          150       4.00
m4b    14.81      15.95      16.17      16.24      gpuM4P50 2.69        9.13 ms          150       4.00
m4c    14.85      15.95      16.18      18.33      gpuM4P50 2.67        9.17 ms          150       4.00
```

Four readings, and they are the first no-pack numbers this report can stand behind:

- **The reference repeats exactly and so does this path's upper mode.** Metal 3: P50 8.33 ms in all three arms,
  P95 within 0.6%, `loadedMiB 28498.5` to the digit. This path: **P95 15.94, 15.95, 15.95 ms - 0.06% apart** - and
  its own driver interval 2.67-2.69 ms, 0.7% apart, where its **P50 moves 13.56 to 14.85 (9.5%)** with the
  mixture. So the stable quantity is the upper mode and the driver interval, and the P50 is the mixture ratio.
- **The windows sampled the same slice of the client's life, and the instrument is what says so**: every Metal 3
  arm covered **100 client ticks at 6.00 frames a tick** and every Metal 4 arm **150 at 4.00**. That equality is
  new - it is what the previous run could not state, and why its content guard fired.
- **The wall-clock comparison: this path is 1.63-1.78x slower on this scene** (13.56-14.85 against 8.33 ms), and
  the mechanism is the pacing and not the work: **its own commit interval is 2.67-2.69 ms against the reference's
  7.60-7.61**, while its drawable handover wait is 9.1-9.5 ms a frame against the reference's 7.7. A frame whose
  own work is 2.7 ms is landing on **two 8.33 ms handovers** where the reference's lands on one.
- **Per sections 47 and 49 the two GPU columns are not subtracted**: Metal 3's `gpuP50` is
  `MTLCommandBuffer.gpuMillis` and this path's is `MTL4CommitFeedback`, and the intervals have not been shown to
  be the same quantity. The wall column is the comparison; the GPU columns are what each generation says about
  itself, and the structural counters (`pipelineIdentities 99`, `blits 0`, `windowFrames 600`, `depthBias 0`)
  agree.

**The refused first attempt is kept below**, because the instrument it lacked is the reason this one exists.

**The §93 ladder, first rung: attempted under the new protocol, and refused by its own guards.**
`run/perf93-nopack` is the no-pack rung - the game's own renderer through this engine's backend - with six arms
interleaved **M3, M4, M3, M4, M3, M4**, one world, one camera, 3200x1800, 600-frame windows, 25 s of settle, the
target pinned with `--expect-target` and no pack staged:

```text
arm   wall P50   wall P95   wall P99   wallMax   own GPU interval   drawable wait p50   loadedMiB
m3a     8.33       8.58       8.71      8.89      gpuP50 7.68          7.72 ms            28498.5
m3b     8.33       8.58       8.73     15.01      gpuP50 7.42          7.20 ms            28498.5
m3c     8.34       8.59       8.77      9.57      gpuP50 7.30          7.13 ms            28498.5
m4a    12.57      15.94      16.11     21.25      gpuM4P50 2.71       11.28 ms           120267.3
m4b     9.85      15.92      16.05     21.07      gpuM4P50 2.74        8.75 ms           142767.3
m4c     7.82      15.77      15.94     16.05      gpuM4P50 2.56        6.98 ms           160206.6
```

- **The reference repeats perfectly and the path does not.** Metal 3's three arms read 8.33, 8.33 and 8.34 ms at
  the median and are **identical to the byte in every content counter** (`loadedMiB 28498.5`, `storedMiB 81232.9`,
  `depthAttachments 1800`, `pipelineIdentities 99` in all three) - 0.01%. This path's three arms read 12.57, 9.85
  and 7.82 (1.61x) and their content counters **drift monotonically**: `loadedMiB` +18.7% then +33.2%,
  `storedMiB` +9.4% then +16.7%, `depthAttachments` +9.0% then +16.5% against the first arm.
- **The distribution is the measurement, and it is the handover quantum again.** Metal 3 sits at **8.33 ms - one
  quantum of this 120 Hz panel - in every arm, with its own GPU time (7.3-7.7 ms) just under it. This path's
  **P95 is pinned at 15.77-15.94 ms in all three arms (1.1% apart) - the *second* quantum - while its P50 moves
  from 7.82 to 12.57 with the mixture ratio.** So the two modes are one and two handovers, exactly as
  `run/m4-pacing` measured, and on this scene the P50 is a reading of *which mixture the launch landed in*.
- **And the rung is refused rather than reported**: the comparison names both faults itself - "scene drift:
  metal4: loadedMiB of m4c is +33.2% against m4a" and "arm outlier: m4a read 12.49 ms a frame against the fastest
  arm of its own generation's 7.79 (1.60x), so the machine moved under it - section 115 says to discard this arm"
  - and the picture comparison agrees, with `m3a` against `m4c` differing in 21.46% of pixels by more than 8 where
  `m3a` against `m4a` differs in 0.09%. **Per section 42 the ladder stops at this rung**: no MakeUp, no
  Complementary, no Photon until the no-pack rung can be measured without an arm whose content moved.

**What the no-pack rung therefore leaves open, recorded as a blocker rather than as a number.** This path's
*content* is not stable across launches in one session where the reference's is: the same world, camera and
target produce `loadedMiB` 120267, 142767 and 160207 in three arms of one generation. That is a property of the
frame this path builds and not of the world - the world was re-staged from the same copy for every arm and Metal
3's counters are bit-identical - and it is **NOT LOCALISED**. The leading candidate is the window's phase
relative to the client's world streaming (the window opens 25 s after the frame the harness waits for, and with
no pack that frame arrives at a different point in the load), and it is stated as a hypothesis. Until it is
settled, §93's first rung cannot produce a comparison, and per §67 the honest verdict for it is **NOT MEASURED**.

## Timing model

Every number in this report was measured, and this section says what each instrument measures and what it does
not, because a migration that reads a clock it has not priced is a migration that optimises the wrong thing. The
counter road is the worked example: it returned a time, the time was not the work, and only a second and third
instrument on the same submission could say so.

| name | measures | does NOT measure |
| ---- | -------- | ---------------- |
| CPU encode | the CPU building a frame's commands | GPU execution |
| counter marker (command buffer, either resolve road) | the driver's *front end*: about 60 ns a draw issued | per-pass GPU work - REFUTED, and equal on both resolve roads (14/14 stamps) |
| submit feedback (`MTL4CommitFeedback.GPUStartTime/GPUEndTime`) | the whole committed submission's interval, pacing included | isolated pass work; and it is not pure render work while `waitForDrawable:` is inside it |
| CPU completion wait (`waitUntilSignaledValue:`) | the host's wait for a submission to finish | a kernel's execution interval |
| drawable wait (`nextDrawable`) | the presentation/handover contribution to the frame loop | renderer work |
| per-frame trace (`M4_FRAME`, `M4_FRAME_COMMIT`) | the distribution: what each frame waited on and what it encoded | anything about a pass |

Three consequences are now protocol rather than preference, and they are section 30's menu with the entries this
migration has evidence for:

1. **A production-depth Metal 4 P50 is not a renderer cost.** At the production ring depth the period is a mixture
   of two or three drawable handovers (16.7 and 25.0 ms on this 120 Hz panel), so that P50 measures the display's
   mixture as much as the path.
2. **A comparison is therefore one of**: a work-bound scene (`section 93`'s ladder, where the GPU is the
   bottleneck in both generations); **or** a controlled pacing condition, which for this path means the diagnostic
   one-slot ring depth - named as diagnostic and never as production; **or** a distribution-aware reading
   (P50 with P95 and the per-frame populations, which `tools/metal4-pacing-analysis.py` prints).
3. **Timings from different APIs are not subtracted.** `MTLCommandBuffer.gpuMillis` (Metal 3) and
   `MTL4CommitFeedback` (Metal 4) have not been shown to measure the same interval, so a cross-generation
   speedup is read from wall time under the condition above plus the structural counters, and a *within*-Metal 4
   A/B may use the driver interval because its presentation structure is the same in both arms.

**And the counter work stops here.** Section 36's stop rule applies: the tested Metal 4 APIs - both resolve roads
and both marker forms - do not attribute a pass, the verdict is recorded as an instrumentation limit, and no
further timestamp selector is tried. Optimisation uses whole-frame controlled A/B, CPU and native operation
counts, and section 70's structural counters.

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
| counters        | whole frame | **the heap road works and the marker road does not measure the work - corrected this round, and the correction is a measurement and not a doubt.** The plumbing is proven: `MTL4CounterHeap` of type Timestamp, timestamps resolved on the CPU after the ring's shared-event wait (the header's own synchronization rule), per-entry and range resolves agreeing, and **a counter tick is a nanosecond** on this device (`gpuTicksPerCpuNs=1.0000`). What is withdrawn is the reading: with the submission's own driver window and the CPU's completion wait read beside the markers, and a fixed-cost control on a submission of its own, the marker span is **452/436/432/434/442/426/225/231 us** where the driver reports **20.7/18.7/18.5/18.6/19.0/18.6/9.8/10.0 ms** and the CPU waits **20.9/19.3/19.1/19.1/19.5/18.8/10.4/10.6 ms** for the same eight submissions - a constant `markerOverDriver` of **0.0219-0.0234** while the window moves by 2.7x, which is a *front end* (about sixty nanoseconds a draw) and not render work. Both sampling forms agree at the same boundary (`encoderOverCb` 0.82-0.96, and **1.00-1.02** on the heaviest pass), so it is not a granularity or a stage question, and the area pair is not a pair (256 draws on 4096x4096 read 17,583-309,235 ticks; 1024 draws on the same attachment read 49-67). **And the last road was then tried**: `MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:` was encoded into the same submission twice (mid-stream and at the end) and read on the CPU after the shared event - it is a real, position-sensitive resolve (the mid-stream region reads the nine not-yet-written entries' area markers as zero, the five that had not run) and it reads **byte-identical stamps to the CPU resolve, 14/14 in all ten probes** (`run/m4-counters/timeline-probes.txt`). **So GPU counter timing at pass granularity is NOT AVAILABLE on either resolve road**, section 92's third kind of data is the whole-commit driver timing alone, section 95 cannot rank candidates by a per-pass GPU time, and per section 36 the counter work stops here. Blocker 15 is CLOSED AS AN INSTRUMENTATION LIMIT. `run/m4-counters/probes.txt` (ten probes) and the timeline census, all `gpuTime=true`; fifteen new contract pins across the two rounds, each mutation-proved. Blocker 15 | yes - `MTL4CommitFeedback.GPUStartTime/GPUEndTime` per commit, reported as `gpuM4P50/P95/P99/Max`; **and this is now the only road shown to track the work**: on a submission with no drawable it reads a stable 18.5-20.7 ms across probes and agrees with the CPU's completion wait to within 3% | yes |

**What the matrix is for here**: it is the list a reader checks before believing any claim about the migration,
and its blanks are the work. A `yes` in `M4 real frame` means the harness collected it from a frame the client
drew and presented; a capability with no live-frame reading is `n/a` rather than inferred from a smoke, because a
capability proven in a process with no window is not the same claim.

## AUTO readiness

The decision the plan allows three forms of, taken gate by gate and with the evidence each line rests on.

| gate | state | evidence |
| ---- | ----- | -------- |
| no-pack world correct | PASS | the frame is a world again since blocker 10 (mean BGRA `(68, 91, 77, 221)` against Metal 3's `(67, 86, 71, 254)`, terrain cells identical cell for cell) |
| GUI and text correct | PASS | blocker 17: the title screen reads back identically to Metal 3's, glyph samples equal to the byte |
| terrain correct | PASS | terrain cells identical and the pack fixtures agree |
| depth correct | PASS | `depthtex0-contract` and `depth-value-contract` on both arms: ~90,000 green against ~28,000 cyan, no magenta |
| MRT correct | PASS | the fixture's four quadrants are the slot table in both arms, sample for sample |
| history correct | **NOT MEASURED** | the temporal/history packs have not been read this way |
| compute and storage correct | **NOT MEASURED** | the dispatches are encoded and the chain runs; the fixture's GREEN picture needs the in-game screenshot that macOS refuses to synthesise |
| wide resources correct | PASS, one real-device reading | photon's `deferred4` (nineteen sampled images) runs through the argument-buffer road; generality beyond it is NOT MEASURED |
| MetalFX live-frame fixture correct | **PASS this round** | the asymmetric quadrant fixture: orientation and channel order proven with the scaler in the loop, identical in both arms |
| lifecycle | PASS, two transitions manual | `run/m4-lifecycle`: reload (F3+T's path), resize, leave, close; a dimension change and an in-session pack switch are not driven |
| shutdown clean | PASS | the close action runs the teardown and the ring reports every submission retired |
| no known GPU restart | PASS | no `GPURestart` in any collected arm, including this round's four sessions |
| cold capability probe deterministic | **NOT MET** | 240 probes passed in one period and 21 of 200 failed in an earlier one, with nothing in the path changed; the retry policy exists but is not proven safe as a production gate |
| performance stable enough to compare | **NOT MET** | section 93's first rung is NOT MEASURED: this path's content counters drift within one session (`loadedMiB` +18.7% then +33.2%) where the reference's are identical to the byte |
| forced Metal 3 fallback | PASS | `-Dmetallum.execution=metal3` runs the reference path unchanged, verified in every session's arms |
| instrumentation | PASS | wall, the whole-submit driver window, both waits, the per-frame trace and the structural counters are all measured; per-pass GPU time is NOT AVAILABLE and section 56 says AUTO does not require it |

**AUTO stays on Metal 3, and Metal 4 stays forced and EXPERIMENTAL - section 70's outcome C.** The reason is
not the frame's correctness as a whole, which is the strongest it has been: it is that **two gate lines are
NOT MEASURED rather than failed** - the history and compute pictures, which need a screenshot this machine cannot
take, and the §93 first rung, which needs a session in which this path's content does not move - and that the
cold capability probe's intermittency is unresolved. Section 123's own list is therefore not met on four counts
(history, compute/storage, the capability probe, and performance), and section 70 puts that in C rather than B:
the performance *distribution* is explained (the drawable handover's quantum) but the *comparison* it was meant
to serve is not yet measurable, so promoting Metal 4 would be promoting a path whose frame-rate claim rests on a
mixture nobody has bounded on a real scene.

What would move it, in the order the gates are listed: the content-drift blocker above (one experiment: trace the
per-frame content counters through the window and watch them move), the cold probe's distribution (a harness that
runs the probe's first pass alone in volume), and the two picture residuals (a screenshot road that works, or a
fixture channel that does not need one).

## Remaining blockers

- **Depth bias: the gap is FIXED, the fixture is not built.** Section 58 was right: `Metal4CompiledRenderPipeline`
  has carried `depthBiasConstant` and `depthBiasScaleFactor` since it was written and **nothing on this path ever
  sent them to an encoder** - so a pipeline that asks for a bias (a decal, a shadow-map offset, anything the game
  draws a hair in front of its surface) drew unbiased here and biased on the reference, which is a visible
  difference on exactly the geometry the bias exists for. `MTL4RenderEncoder.setDepthBias:slopeScale:clamp:` is
  now bound with the header's three floats in the header's order and applied by the pass where the Metal 3 pass
  makes the same call (`setDepthBias(constant, slopeScale, 0.0f)`, right after the depth-stencil state), and a
  window reports `depthBias=N` so a live session can say whether any real pipeline reaches it. **What is NOT
  MEASURED is the offset itself**: no live frame has yet been shown to carry a non-zero bias, and the fixture
  section 58 asks for - two coplanar surfaces where the biased one must win, read on both generations - is not
  built. The fix and its four pins are a separate commit from any performance work, as section 58 requires.

- **The content drift is decomposed and NOT LOCALISED, and the tick term is smaller than it first looked.**
  The decomposition of the traced windows, exactly: a frame is **7 passes** in the steady state, **13** on a
  tick frame and **5** in one stretch, so a window's total is `7*600 + 6*T - 2*S` with `T` the tick frames and
  `S` the reduced ones. `m4t1`: 436*7 + 134*5 + 30*13 = **4112** against its measured 4100 (the 134-frame
  stretch at 5 passes is worth -268 passes, six times the tick term's +180); `m4t2`: 572*7 + 28*13 = 4368
  against 4368; `m4t3`: 562*7 + 7*5 + 1*11 + 30*13 = 4370 against 4370. So **the tick term is real but worth
  about 4% of a window, and a ~340 ms stretch with two passes absent is worth about 6%** - which is the shape
  the drift has, and a least-squares fit of the two coefficients over three arms with tick counts 27.9-30.7 is
  ill-conditioned and returns nonsense, so it is NOT fitted and the mechanism stays NOT LOCALISED.
- **What the tick finding does establish is the cadence, not the size.** `run/drift-nopack` (same
  six-arm M3/M4 interleave, no pack, with the per-frame trace on) shows what the per-frame pass count of this
  path's no-pack frame actually is: **7 passes in the steady state, 13 on one frame every 49.6-50.0 ms** - the
  client's 20 Hz tick, measured in wall time and not in frames (`run/drift-nopack/m4t2`: spikes spaced 21.4
  frames but 49.6 ms; `m4t3`: 19.3 frames, 50.0 ms; `m4t1`: 20.2 frames, 49.8 ms) - and 5 passes for a
  contiguous 134-frame stretch in one arm. The probe's window is a fixed **frame** count, so the number of
  tick-frames inside it is `windowWall / 50 ms`: **Metal 3's frame rate is constant, so its window always contains
  the same number of them and its content counters are identical to the byte (`depthAttachments 1800` and
  `loadedMiB 26836/26900/26900` in all three arms), while this path's frame rate is the pacing mixture, so its
  windows contain different numbers and its counters differ.** The guard's 2%/5% tolerances were calibrated on the
  reference's steady frame rate, and on this path they measure the window's sampling before they measure the
  frame. **The remedy is a window definition and not a Metal4 change**: pin the window by game ticks or by wall
  time, or report the content counters per second and per tick beside the per-frame ones, before the rung is
  re-run.
- **And the remedy was tried and REFUTED, which narrows the next step.** Comparing the content counters as
  *rates per second of window* instead of per window was the obvious normalisation, and it is wrong: on
  `run/drift-nopack` it makes **the reference itself drift** - Metal 3's arms read `loadedMiB` 24131, 21945 and
  21443 MiB a second (-9.1% and -11.1%) where their window totals are 26836.1, 26900.0 and 26900.0 - because
  Metal 3's own frame rate moved 13% between those arms (1112.1, 1225.8 and 1254.5 ms windows) while its per
  *frame* work stayed the same. So the client's content is neither per window nor per second: it is **per frame
  plus per game tick**, and only a window pinned by *ticks* (or a reported tick count to normalise by) makes the
  arms comparable. That is a harness and probe change - measure the window's game ticks, or close it on a tick
  boundary - and it is the next measurement task; the rate comparison was reverted rather than shipped, because a
  guard that flags the reference is worse than one that flags the path.
- **And a genuine scene difference sits beside it.** In the same session one M4 arm's window drew 157 draws a
  frame where the other two drew 326, falling from 223 to 109 across the window - a world-content difference that
  no normalisation removes, and the reason the rung still needs a scene guard after the window is fixed.
- **This path's frame content is not stable across launches within one session, and it blocks the first rung of
  section 93's ladder.** `run/perf93-nopack`: Metal 3's three arms are identical to the byte in every content
  counter (`loadedMiB 28498.5`, `storedMiB 81232.9`, `depthAttachments 1800`, `identities 99` all three times,
  0.01% apart in time), while this path's three arms read `loadedMiB` 120267, 142767 and 160207 - +18.7% and
  +33.2% - with `storedMiB` and `depthAttachments` following. The world is re-staged from the same copy for
  every arm and the reference does not move, so this is a property of the frame this path builds. **NOT
  LOCALISED**; the leading candidate, stated as a HYPOTHESIS, is the probe window's phase relative to the
  client's world streaming, since with no pack the frame the harness waits for arrives at a different point in
  the load. It is why the ladder stops at its first rung (section 42) and why the rung's verdict is NOT
  MEASURED (section 67) rather than a number.

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

13. ~~**The two arms disagree about how bright a fixture's frame is, and neither reading comes from the pack**~~ - **RESOLVED, and it was the same fault as blocker 17.** The disagreement was real and its explanation was written here as "an overlay multiplied in, or a write this path skips": it was a write this path skipped. The overlay is vanilla's own loading fade, drawn through the engine's staged vertex buffer, whose buffer copy declared neither of its resources resident and therefore moved nothing on Metal 4 - so the Metal 3 arm showed the fixture's green under a fading multiply and this arm showed the fixture's green alone. With the copy road's declarations in place, the same fixture, same pack, same world, one arm each, read from the presented picture's own readback:

   ```text
                                                green over the run                        blue
   metal3 (before and after the fix)   61, 203, 206, 207, 207, 207, 207, 207, 207, 207   239 -> 0
   metal4 before the fix               50, 255, 255, 255, ...  (flat, no fade)           -     -> 0
   metal4 after the fix                61, 202, 206, 207, 207, 207, 207, 207, 207, 207   239 -> 0
   ```

   The two generations now read the same ramp, the same plateau (207) and the same starting point (61); the single intermediate sample that differs by one is the ramp's phase at the instant it was sampled. The original account of this blocker follows, because the readings it records are what made it a blocker and what shows the fix changed it.

   **The two arms disagree about how bright a fixture's frame is, and neither reading comes from the pack.**
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

15. ~~**The GPU timestamp road works and its sampling points do not attribute a pass, so section 90's smoke is
   red.**~~ - **FIXED, and the sampling points were never the problem: the smoke was.** The whole of this item
   below is kept because it is the record of what was measured and of the three wrong explanations that were
   ruled out honestly - and because the resolution is that the road was right all along. The mechanism is at the
   end of the item. What is proven: `MTL4CounterHeap` is made, timestamps written into it resolve on the CPU after the
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
   each attachment clears to black and then draws the shader's colour, **a pixel of each is read back
   separately** (the curve's target and the area pair's are two textures, so one proof cannot stand for both),
   and every reading says `drawsLanded=true`, `curveLanded=true` and `areaLanded=true`. Without that check, "the
   draws cost nothing" and "the timestamps are not execution points" are the same measurement - and a road that
   does not respond to area cannot be told from an area target nothing drew into - and they are different faults.

   **RESOLVED: the road attributes a pass, and the three defects were the smoke's own.** Every inversion above was
   arithmetic. The loop writes one boundary per step at `step + 1`, so a four-step curve fills entries 1 to 4 with
   entry 0 as the start - and a leftover marker from a three-marker two-pass shape wrote **entry 2 a second time,
   after every step had been encoded**. Entry 2 therefore held "the end of everything" while entry 3 held "the end
   of step 2", and `stamps[3] < stamps[2]` was true by construction: the ~226,000-tick inversion, its collapse to
   ~120 when the heavy steps came first, and every reading built on "the interval between two stamps is not the
   work between them" came from that one line. Two more defects were behind the rest of the scatter: the
   boundaries mixed **two sampling forms** (entry 0 was the command buffer's marker, entries 1-4 the render
   encoder's after-stage ones), and the curve's first step was both the command buffer's **first encoder and its
   only clearing pass**, which made the lightest step the most expensive in every probe (~27,000-33,000 ticks for
   one draw against ~1,000-22,000 for sixteen).

   With one form, one write per entry, and a warm-up pass the curve does not count, the readings are an ordered
   partition of the work - and they also measure the road's own floor:

   ```text
   probe  64 draws   256 draws   1024 draws   4096 draws
   1         6105       18382        54246       171134
   2         6729       18566        54283       170540
   3         6720       18343        54304       166420
   4         6075       18852        54296       166634
   ```

   Monotone in every probe, the two heavy steps repeating to about two per cent, 3 of 3 and 4 of 4 probes passing
   (`gpuTime=true`), with `rangeAgrees=true`, `drawsLanded=true` and the unit still a nanosecond
   (`gpuTicksPerCpuNs=1.0000`, now reported as the ratio of the two deltas rather than as the absolute first
   stamp). **The floor is the road's and it is now part of the smoke's design**: with the same fixes and the old
   counts, 256 and 4096 repeated to two per cent while 1 and 16 *swapped order between probes* (1,069 against
   1,919 ticks the other way round), so an interval below roughly two thousand ticks on this device is not
   ordered, and the curve is `{64, 256, 1024, 4096}` because every step has to be above it.

   **What this changes for sections 92 and 95.** Section 90's acceptance - "increasing shader work, reported GPU
   work increases" - is now **MET**, and section 92's three kinds of data are all three available: CPU encode
   timing, whole-command-buffer driver timing (`MTL4CommitFeedback.GPUStartTime/GPUEndTime`), and **GPU counter
   timing, at command-buffer granularity and above the floor**. Section 95's candidates can now be ranked by a
   GPU-side attribution rather than by a whole-frame A/B alone. What is *not* claimed is a within-pass sample:
   the granularity this smoke uses has no stage, each marker sits at an encoder boundary, and where a driver
   places a stamp *inside* one encoder is still the driver's - which no longer matters, because the smoke brackets
   passes and not fragments.

   What is left to try, in the order the evidence suggests: the GPU-timeline resolve
   (`MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:`), which puts the resolve
   itself in the command stream; more than one entry resolved at once, since this smoke resolves one at a time;
   and the whole-frame road the frame path already uses (`MTL4CommitFeedback.GPUStartTime/GPUEndTime`), which does
   produce plausible per-frame times and may be the only attribution this API gives. **Until one of them
   brackets execution, no per-pass GPU time may be reported**, and the census stays red on this smoke so that an
   unproven instrument cannot look green.

   **AND THE RESOLUTION ABOVE IS NOW WITHDRAWN, one round later, by an instrument it did not have.** The same
   submission was committed through `commit:count:options:` so that the driver's own window could be read beside
   the markers, the CPU's wait for the completion value was timed, and a one-draw submission was committed on its
   own as a fixed-cost control. Eight probes, `run/m4-counters/probes.txt`, every one `gpuTime=true`:

   ```text
   probe  marker span   driver window   CPU wait   fixed cost   marker/driver   encoder form   curve ordered
   1        331.5 us      15.214 ms     15.501 ms    0.075 ms       0.0218          0.95          NO
   2        412.8 us      21.442 ms     21.722 ms    0.078 ms       0.0193          0.96          yes
   3        472.2 us      20.425 ms     21.021 ms    0.032 ms       0.0231          0.93          yes
   4        431.5 us      18.788 ms     19.351 ms    0.075 ms       0.0230          0.96          yes
   5        381.2 us      16.760 ms     17.298 ms    5.816 ms       0.0227          0.95          yes
   6        432.8 us      18.208 ms     19.719 ms    0.030 ms       0.0238          0.94          yes
   warm     483.7 us      20.985 ms     21.744 ms    5.760 ms       0.0231          0.82          yes
   warm     268.5 us      12.030 ms     12.588 ms    0.019 ms       0.0223          0.92          yes
   warm     386.9 us      17.594 ms     17.826 ms    0.030 ms       0.0220          0.94          yes
   warm     310.1 us      13.727 ms     14.272 ms    0.022 ms       0.0226          0.94          yes
   ```

   Eighteen probes are recorded in the two censuses on disk - `run/m4-counters/probes.txt`, the table above, and
   `run/m4-counters/probes-loaded.txt`, a second census that ran while the machine was saturated and whose driver
   windows were 411, 1177 and 1198 ms against a fixed cost of 7-9 ms - and `markerOverDriver` is **0.0193-0.0238**
   in every one of them. The marker span is **one part in 42 to 52 of the submission** while the driver's window
   moves by a factor of a hundred,
   the fixed cost is three orders below the window it would have to explain, and the CPU - which cannot be
   signalled early - waits the driver's number and not the markers'. Three mechanisms that could have excused it
   are closed: the encoder's own `Precise` after-fragment form at the same boundary reads the same interval
   (**1.00-1.02** on the heaviest pass, so it is not a granularity or a stage question); the area knob, put back,
   is not a knob (256 draws on 4096x4096 read 17,583-309,235 ticks while 1024 draws on it read 49-67); and the
   single-step orderings invert often enough to be reported rather than asserted (`curveOrdered` false in 2 of the
   8). So the three defects this item found *were* real and *were* the smoke's - and fixing them moved the road
   from "plainly wrong" to "consistently a front end", which is still not the work. **The verdict is the one this
   item opened with**, now measured with instruments rather than inferred from a curve: a difference between two
   of these stamps is not the work between them, no per-pass GPU time is reported from this road, and section 92's
   third kind of data is the whole-commit driver window alone. The smoke's own requirement is the aggregate the
   road does answer - the heaviest step reads longer than the lightest, true in all eight probes - and it exits 0
   on that; seven new contract pins hold the new instruments and each is mutation-proved. The next candidate is
   the one named above and still untried: the GPU-timeline resolve
   (`MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:`).

   **AND THAT LAST ROAD HAS NOW BEEN TRIED, WHICH CLOSES THE ITEM.** `run/m4-counters/timeline-probes.txt`,
   ten probes (six cold, four warm), all `gpuTime=true`. The smoke encodes the GPU-timeline resolve twice into
   the same submission - once mid-stream, where the area pair's markers do not exist yet, and once at the end
   over every entry - and reads the resolve buffer on the CPU after the shared event, which is the header's own
   condition ("If your app needs to access `bufferRange` from the CPU, signal an `MTLSharedEvent` to notify the
   CPU when it's ready", `MTL4CommandBuffer.h:195`):

   ```text
   probe  entry bytes   timeline vs CPU resolve   mid-stream unwritten tail   timeline span   CPU-resolved span   span/driver
   1          8                14/14                       5/9                    481.4 us          481.4 us          0.0229
   2          8                14/14                       5/9                    487.3 us          487.3 us          0.0231
   3          8                14/14                       5/9                    482.4 us          482.4 us          0.0230
   4          8                14/14                       5/9                    500.9 us          500.9 us          0.0231
   5          8                14/14                       5/9                    479.7 us          479.7 us          0.0228
   6          8                14/14                       5/9                    480.9 us          480.9 us          0.0230
   warm       8                14/14                       5/9                    476.9 us          476.9 us          0.0229
   warm       8                14/14                       5/9                    352.9 us          352.9 us          0.0228
   warm       8                14/14                       5/9                    372.5 us          372.5 us          0.0224
   warm       8                14/14                       5/9                    347.9 us          347.9 us          0.0227
   ```

   Three facts, and the first two are what make the third one a verdict rather than a coincidence:

   - **The resolve road is real and position-sensitive.** `sizeOfCounterHeapEntry:` answers **8** bytes, and the
     mid-stream resolve reads **5 of the 9 entries that did not exist yet as zero** - exactly the area pair's
     command-buffer markers (5, 6, 7) and its encoder markers (12, 13), while the four encoder markers written
     before it read values. So the command executes at its own position in the stream and the range argument is
     honoured; this is a snapshot and not a post-hoc dump.
   - **And it reads byte-identical stamps to the CPU resolve** - `14/14` in every one of the ten probes, with the
     span equal to the decimicrosecond (`481.4` against `481.4`) and the ratio equal to four decimals
     (`0.0229` against `0.0229`).
   - **Therefore the sampling point is not a function of how the heap is resolved.** Section 5's experiment was
     built to allow either answer, and it returned the first of section 6's two: the resolve change alters
     neither the marker nor its meaning - the interval is the driver's front end either way, at the same
     ~1/43 of the submission.

   **Blocker 15 - CLOSED AS AN INSTRUMENTATION LIMIT.** The template the plan asks for, with each line a
   measurement and not an inference:

   ```text
   counter heap creation:                     PROVEN
   counter resolve, CPU timeline:             PROVEN
   counter resolve, GPU timeline:             PROVEN (position-sensitive, and equal to the CPU road 14/14)
   counter unit:                              PROVEN  (1 tick = 1 ns; resolved entry = 8 bytes)
   counter markers as pass execution points:  REFUTED for both resolve roads
   whole-submit CommitFeedback timing:        PROVEN  (the only road shown to track the work)
   per-pass GPU attribution:                  UNAVAILABLE
   ```

   **What this costs and what it does not.** Per section 36 the counter work **stops here**: no further timestamp
   selector is tried, and Metal 4 optimisation proceeds on whole-frame controlled A/B, CPU/native operation
   counts and the structural counters of section 70 - which is what every milestone of this migration has
   actually used anyway. Per section 4 this is an **INSTRUMENTATION blocker, not an execution one**: it blocks
   ranking optimisation candidates by per-pass GPU time, and it does not block Metal 4 correctness, lifecycle or
   the AUTO decision, whose real blockers are the frame-time distribution (blocker 16) and the intermittent
   capability probe.

   **Three clocks, read separately and never forced to agree.** The driver's `GPUStartTime`/`GPUEndTime` is the
   accelerator's own account of when a submission ran; the CPU's `waitUntilSignaledValue:` duration is the host's
   wait for the queue's completion signal; and a marker interval is a timestamp the GPU wrote into a heap this
   path reads. The two that *do* agree - 9.8-20.7 ms of driver window against 10.4-20.9 ms of CPU wait, within 3%
   on every probe - are two different instruments, so their agreement is itself a reading: the queue adds no large
   amount of time outside the submission. The marker road is then treated as its own clock rather than converted
   into theirs, and that is the point of the correction: it reads a constant 2.19-2.34% of the driver's window
   across a 2.7x range of that window, which is a *front-end* clock (about sixty nanoseconds a draw) and not a
   scaled version of the work. Scaling it by forty-three would be the one move this evidence forbids - it would
   attribute to a pass a time the front end never sees - so where a per-pass number is wanted, the whole-commit
   driver window is the only road that has been shown to track the work, and it is whole-commit. The full set is
   larger than the census above: **thirty-one probes across seven runs** (`run/m4-counters/probes.txt` and the six
   runs before it), with `markerOverDriver` between **0.0219 and 0.0234** in every one of them.

16. **Blocker 16 - RESOLVED as a mechanism, and the mixture is the display's.** Observed: this path's arms of
   one configuration repeat to 1.00-1.51x while the reference's repeat to 1.00-1.10x. Cause, measured in
   `run/m4-pacing` (six arms interleaved 1, 3, 1, 3, 1, 3 slots, a per-frame trace, `tools/metal4-pacing-analysis.py`):
   **at the production ring depth the frame is paced by the drawable handover and its period lands on two or three
   quanta of that handover** - every depth-3 window is two-peaked with the peaks about 8 ms apart, the drawable
   waits cluster at ~7, ~15 and ~23 ms, and `corr(wall(N), drawableWait(N-1))` is +0.56/+0.82/+0.85 where at one
   slot it is +0.03/-0.08/+0.18 and the window collapses to one narrow peak. 25.0 ms over 16.7 ms is **1.50x**,
   the bound the eighteen sessions measured. Diagnostic isolation: one slot removes the populations because every
   frame then waits for its own previous submission and the CPU cannot run ahead of the compositor. Production
   implication: the depth stays as it is - the wait is the ordering the header asks for and removing it changes
   the presented picture. Benchmark implication: **a production-depth P50 is not a renderer cost**, so a
   comparison is either taken at a controlled depth, on a work-bound scene, or read as a distribution (section 30).
   **What is not closed**: the across-arm *mean* did not collapse at one slot in this session (1.17x against
   1.21x), so the gate stays unmet until a session with more repeats at both depths says otherwise.

   *(Kept below: the chain that got here.)* **The Metal 4 frame's own cost varies between two arms of one session by 47.7%, which is wider than any
   effect the comparison is meant to resolve, so section 93's "Metal 4 is not slower than Metal 3" is NOT
   MEASURED.** *(Superseded twice, and kept because the chain that got there is the record. `run/m4-ab7` measured
   this path at 23.85 and 27.45 ms a frame against the reference's 20.31 and 20.70, arms interleaved M3/M4/M3/M4,
   with the GPU trace reading device utilization 100% in all four - and that was read as "16-35% more GPU time".
   The per-pass counter that followed (the Performance section's `run/m4-passtimes`) read the frame's own pass
   work at **378 us of a 19.4 ms window**, and that was read as "the 16-35% therefore compares the two
   generations' pacing waits and not their renderer work". **That step is withdrawn** - the two-instrument census
   in blocker 15 shows the 378 us figure is a front end and not the work, so the window cannot be dismissed as a
   wait by subtracting it - and the performance question stays open with the driver's window as the one road
   shown to track the work.)*
   Session `run/perf-ab4` (exit 0, `m3a, m4a, m3b, m4b`, `--frames 600 --settle 25
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

   **Re-run after the copy-road fix, and the spread is still there - with the same structure and the same waits,
   which is the useful part.** Session `run/perf-ab6`, the same shape as `run/perf-ab4` (Complementary, four arms,
   600 frames a window, 25 s of settle, 3200x1800):

   ```text
   arm   wallP50  wallP95  wallP99   gpuP50/gpuM4P50  windowMs   drawable wait p95  submitWindow p95  loadedMiB
   m3a    21.07    22.65    22.95    21.06 / 0.00      12623      0.03 ms            20.32 ms          ...
   m4a     9.51    37.45    37.83     0.00 / 18.55     11095      7.59 ms            16.78 ms          394175.0
   m3b    21.02    22.66    23.02    21.04 / 0.00      12621      0.03 ms            20.37 ms          ...
   m4b    27.04    54.74    56.02     0.00 / 27.74     16618      7.58 ms            17.98 ms          403045.3

   machine load, sampled at each arm's start and end (15 cpus): m4a 4.33 -> 4.26, m4b 4.27 -> 4.76
   ```

   Metal 3's arms agree to **0.2%**; this path's differ by **184%** on P50 and by **50%** on its own GPU
   feedback. Four things are ruled out by the readings rather than by argument: the **scene** (loadedMiB
   394175.0 against 403045.3, `blits 5400` and `blittedMiB 101022.1` identical to the digit, `depthAttachments`
   5872 against 5938, `pipelineIdentities 333` and `compiles 0` in both), the **machine** (the load samples above
   are the same to a tenth within each arm, and the instrument exists precisely to say so), the **wait sites**
   (drawable p95 7.59 against 7.58 ms, submission p95 16.78 against 17.98), and the **structure** (every counter
   within 2%). What differs is the frame's own cost - and `m4a`'s shape is the interesting one: `wallP50 9.51`
   against `wallP95 37.45` means its 600 frames fall into two populations, while `m4b`'s cluster near 27. A
   generation whose frame cost takes two different values on the same input is not a performance measurement
   problem, it is a **frame-cost** problem, and it is the first thing the next session on this path should
   characterise: whether the two populations are the ring's slot reuse, the transient arena, the argument tables,
   or a residency commit landing inside one frame in two.

   **And the content counters name most of it.** The same four arms, read for what the frame *did* rather than
   what it cost:

   ```text
   arm   draws (pipeline)   texture binds   buffer binds   loadedMiB   depthAtt.   wallP50   gpu (own API)
   m3a   16990              48464           59433*         309384.0    2377        21.07     21.06
   m3b   17048  (+0.3%)     48575  (+0.2%)  59433*         315756.1    2435        21.02     21.04
   m4a   36603              52127           40533          394175.0    5872         9.51     18.55
   m4b   41056  (+12.2%)    59803  (+14.7%) 46636  (+15.1%) 403045.3   5938        27.04     27.74
   * the Metal 3 arms' buffer binds are within 0.2% of each other
   ```

   **And that reading was wrong, which is the more useful half of it.** `pipeline`, `texture` and `buffer` are
   native call counts, not content: Metal 3's pass counts a pipeline *change* where this path counts a pipeline
   *set per draw*, and the texture and buffer counters are fills that include the re-fills every pipeline change
   causes - the counters section 70 says are not comparable. Measured directly from the per-pass trace, session
   `run/m4-content`, two Metal 4 arms of one session, normalised per traced frame:

   ```text
                                   m4a        m4b        difference
   draws a frame                   1110.2     1118.1     +0.7%, all of it the shadow pass's own coverage
   passes a frame                  20.55      20.55      none, to two decimals
   clears a frame                  2.33       2.33       none, to two decimals
   by pass, per frame              Vitrail shadow chunk 778.23 -> 785.32 (+7.09)
                                   Vitrail chunk        293.60 -> 294.32 (+0.72)
                                   every other pass      within a hundredth
   ```

   So the two Metal 4 arms **did draw the same frame**, to seven parts in a thousand, and the +12.2% of pipeline
   sets was a state-set difference on arms that drew the same frame.

   **Four consecutive Metal 4 arms on one session say where the spread lives.** `run/m4-four`, same pack, world,
   target and window, 600 frames an arm, 25 s of settle:

   ```text
   arm   wallP50  wallP95  gpuM4P50   windowMs  loadedMiB   depthAtt.  blits  ids  compiles  load start->end
   m4a     9.55    37.60    18.58      11104    354843.2    5474       5400   333  0         2.50 -> 2.92
   m4b     9.50    37.40    18.40      11048    410962.7    ...        5400   333  0         2.92 -> 3.52
   m4c     9.44    36.97    18.18      10934    385826.7    ...        5400   333  0         3.52 -> 3.52
   m4d    27.13    54.49    27.60      16502    356156.3    5464       5400   333  0         6.28 -> 5.15
   ```

   Three arms read **18.18-18.58 ms** of their own GPU time - a spread of **2.2%** - and the fourth reads 27.60,
   and the fourth is the arm whose **machine load sample was twice the others'** at its start (6.28 against
   2.50-3.52 on 15 cpus). Its waits are the same as the fast arm's (drawable p95 7.59 ms in both, submission p95
   16.39 against 17.75) and its frame is the same frame (`blits 5400` to the digit, `depthAttachments` 5474
   against 5464, 333 pipeline identities, 0 compiles). **So the cost of this path is stable to 2.2% across
   consecutive arms on a quiet machine, the outlier is the arm the machine was busy for, and that is the first
   time the load instrument has attributed anything.** It is not the whole story: `run/perf-ab6`'s slow arm had
   load samples equal to its fast arm's (4.27 -> 4.76 against 4.33 -> 4.26). What is left to try is the frame's
   own per-frame counters - `-Dmetallum.metal4FrameStats=true` prints passes, encoders, tables, draws and
   **residency declarations** once every sixty frames - on a session where an outlier appears, because a
   residency set or table count that grows with the session is the one state a session-level cause would show up
   in.

   **For section 123's gate this is the reading that matters**: the number §93 needs is readable when the
   machine is quiet and the arms are consecutive (2.2% spread, all four frames identical), and the outlier has to
   be discarded rather than averaged - which is what `run/m4-four` now lets a reader do.

   **And a session with the path's own per-frame counters on says the cost moves *within* one window.**
   `run/m4-stats`, two Metal 4 arms with `-Dmetallum.metal4FrameStats=true`, which prints passes, encoders,
   tables, draws, indexed draws and **residency declarations** a frame once every sixty frames:

   ```text
   m4a (this session's slow arm)   msPerFrame 9.67 11.92 13.51 18.71 13.93 13.77   wallP50 17.02  gpuM4P50 24.50
   m4b (this session's fast arm)   msPerFrame 7.76  7.15  6.95  6.52  7.70  7.67   wallP50  9.54  gpuM4P50 18.23

   both arms, every bucket       passesPerFrame 20.6-23.5  encodersPerFrame = passes  tablesPerFrame 26.4-30.5
                                 drawsPerFrame 1209.6-1216.6  indexedPerFrame 1180.5-1181.5  residencyPerFrame 1.7-2.5
   ```

   Two things follow, and they are the end of this blocker's investigation:

   - **It is not a session state.** `residencyPerFrame` sits between 1.7 and 2.5 in both arms for the whole
     session, `tablesPerFrame` between 26 and 31, `drawsPerFrame` within half a per cent - so no residency set, no
     table cache and no resource list grows with the session, and the commands are the same commands. The
     instrument that was chosen for a session-level cause has now cleared it.
   - **It is the frame cost moving in time, by a factor of two, on identical commands** - 9.67 ms in one
     sixty-frame bucket and 18.71 ms in another, with `drawsPerFrame` 1214.5 against 1215.8. What absorbs that
     variation on one generation and not the other is the pacing site this section already named: **Metal 3's
     frame time is its submission-index wait**, so a slower GPU or a busier machine shrinks that wait and leaves
     `wallP50` where it was (its arms agree to 0.2% across four sessions), while **this path's frame time is its
     work** - its waits are zero for most frames - so the same variation lands in the frame time whole.

   That is what the section 123 gate has to be built on, and it is why the gate is not met yet: a P50 taken on
   this path on this machine is a reading of the machine as much as of the path, so the number §93 wants needs
   either a quiet machine or a pacing site of its own. At the time this paragraph was written **NOT MEASURED** was
   the honest verdict for the Metal 3 against Metal 4 performance comparison, and the blocker was narrowed to that
   - a pacing and machine-state question rather than an unexplained generation difference. **It has since been
   measured, and then re-measured with a better instrument, which changed what the number is** (the Performance
   section carries both readings): `run/m4-ab7` put this path at 23.85 and 27.45 ms a frame against the
   reference's 20.31 and 20.70, and the per-pass counter that followed read the frame's own pass work at **378 us
   of a 19.4 ms window**. **The second re-measurement is the correction and it is the one to read**: the 378 us
   figure is a marker-road *front end*, not the frame's work (blocker 15's two-instrument census), so
   `waitForDrawable:` being inside the commit window does not license the subtraction that was made with it. What
   stands is the *presented rate* difference of 17-35% in that session and the fact that **the two generations'
   wall-clock numbers are paced by different resources**, which the waits table shows directly; **what is NOT
   MEASURED is how much of this path's commit window is the drawable wait and how much is work**, which is an
   experiment rather than a subtraction. The content guard this round added is built
   on the three counters that mean the same thing on both generations and grow with what the frame drew -
   `loadedMiB`, `storedMiB`, `depthAttachments` - and `run/perf-ab6` passes it (commit `6804310`). Metal 3's wall time did not move for its own 2% content drift because
   its frames are paced by its **submission index**, not by its work (its `submitWindow` wait is called twice a
   frame at a 20 ms p95 where this path's is called once); this path's frame time *is* its work, so content drift
   lands in its wall time directly. **The comparison was unreadable, not the generation** - and the instrument now
   says so: `vitrail-performance-compare.py` judges the arms of one generation against each other (commit
   `a352db3`), on the counters a frozen scene pins exactly and on the frame's content within 5%, which is the
   plan's own performance gate. `run/perf-ab6` is refused with its reason; `run/nopack-ab1` passes it. What is
   still **NOT LOCALISED** is what made the two Metal 4 arms draw different amounts at all - the world, the pack,
   the target and the window were the same, and the Metal 3 arms in the same session saw the same content - so
   that is the question the next session on this path opens with.

   **That session was run, with an instrument the sessions before it did not have, and it moved the question on.**
   `run/m4-loadtrace`: four Metal 4 arms of one configuration - the same pack, world, target, window and 25 s of
   settle - with `-Dmetallum.metal4FrameStats=true`, and the kernel's load average sampled **every five seconds
   for the whole session** rather than at each arm's two ends:

   ```text
   arm   ms a frame  wallP50  wallP95   gpuM4P50   load mean/max   drawable wait  submitWindow  passes a frame
   m4a     21.10      12.38    43.00     21.16      2.78 / 3.08     1703 ms total  1778 ms       21.35
   m4b     18.52       9.52    37.54     18.55      3.21 / 3.51     1622 ms total   989 ms       21.81
   m4c     18.22       9.50    36.97     18.16      4.28 / 5.33     1586 ms total   896 ms       21.39
   m4d     21.57      12.74    43.68     21.55      3.99 / 4.34     1777 ms total  2112 ms       22.07
   ```

   Four readings, and the first of them is the instrument finally saying something a pair of samples could not:

   - **The machine is refuted by the trace, and inverted rather than merely unproven.** The *fastest* arm ran at
     the *highest* load (m4c, mean 4.28 against m4a's 2.78) and the slow arms at the low end, and bucketed against
     each arm's own sixty-frame cost the correlation is **negative in three arms of four** (r = -0.30, -0.13, -0.08,
     +0.27). A spread that came with a busier machine would have to come with one; this one comes with a quieter
     one, so blocker 16's earlier "the machine" elimination no longer rests on two endpoints - it rests on the
     session's own trace.
   - **The scene drift the harness refuses the session for does not order the cost either.** The comparer refused
     all four arms (`renderPasses` of m4c is -2.3% against m4a, `depthAttachments` of m4b is +2.4%, against a 2%
     scene tolerance), so by this project's own rule no arm of this session may be read against another - and the
     drift is nonetheless not the cost: m4b opened **more** render passes a frame than m4c (21.81 against 21.39)
     and was not slower, and m4d opened the most (22.07) for a cost that is high but not the highest. The refusal
     stands as a refusal; the pass count is not the mechanism behind the two levels.
   - **It is not the display, which is the one machine state every session today shares.** All six sessions of
     today left the *same* capture: byte-identical 156220-byte files, the flat black a locked or asleep display
     produces, in `run/nopack-ab1`, `run/m4-content`, `run/m4-four`, `run/m4-stats`, `run/perf-ab6` and this one -
     so the session whose three arms agreed to 1.6% and the session whose arms did not had the same display state.
     (Only `run/perf-ab5`, from the 19th, has real captures.) It is also the single reason the picture column of
     every session above is void, and it is now a *stated* constant of the measurement rather than a suspicion.
   - **And the instrument had to be read correctly before any of it meant anything.** `Metal 4 frame stats`'s
     `msPerFrame` is **the encode**: it begins at a frame's first encode and is taken at that frame's commit, so it
     excludes the drawable wait and the CPU time between frames, where the probe's `windowMs/windowFrames` is the
     frame *period*. They differ by 1.8x in m4a and 2.6x in m4c, and the ratio itself moves arm to arm, so the two
     are not one number: this blocker's earlier reading ("9.67 ms in one sixty-frame bucket and 18.71 in another")
     is the **encode** moving in time, and it is the right instrument for that question and the wrong one for a
     frame rate.

   What the trace leaves standing is the sharpest statement of this blocker so far: **the path's own encode costs
   between 7.3 and 16.4 ms a frame for the same commands inside one arm** - m4a's window buckets run 8.50, 9.71,
   10.28, 10.86, 12.07, 12.41, 13.07, 13.13, 14.24, 16.43 while its `drawsPerFrame` sits at 1212-1216 (+-0.2%) and
   its `residencyPerFrame` at 1.7-2.7, and m4b's same-shaped work sits at 7.28-9.49. So one arm is not only slower
   than the other, it is **less stable**, and the four arms fall into two pairs by *every* percentile at once
   (wallP50 12.38/12.74 against 9.50/9.52, wallP95 43.00/43.68 against 36.97/37.54, `gpuM4P50` 21.16/21.55 against
   18.16/18.55) - a shifted distribution rather than occasional stalls, which is what a rate difference looks
   like. The candidates this blocker named are now worth driving as a lever rather than watching: the ring's slot
   reuse (`-Dmetallum.metal4RingSlots`), the transient arena and the argument tables, each of which can be varied
   and re-measured, and that is the session this one hands over to.

   **And the ring's own depth was then driven as a lever rather than watched, which names one mechanism and
   excludes it as the cause.** `-Dmetallum.metal4RingSlots=N` is a diagnostic switch the migration already had
   (one slot is what makes a fault trace's last commands the faulting submission's); `run/m4-rings` ran four
   Metal 4 arms of one configuration at one, two, three and four frames in flight:

   ```text
   arm      slots  ms a frame  wallP50  wallP95   gpuM4P50   drawable wait  submitWindow total  submit p50
   slots1     1      20.08      20.14    21.25     18.31       11.11 ms        11031.24 ms      18.41 ms
   slots2     2      18.24      18.17    20.45     18.35       16.71 ms         6635.65 ms      14.68 ms
   slots3     3      18.32       9.53    37.14     18.48     1610.68 ms          951.49 ms       0.00 ms
   slots4     4      24.37      16.90    48.46     24.39     1742.78 ms            0.77 ms       0.00 ms
   ```

   - **The two populations are the slot-reuse wait, and one slot proves it by removing them.** At three slots the
     arm's frames are bimodal - P50 9.53 against P95 37.14, a 3.9x gap - while its submission wait is *zero for
     most frames* (p50 0.00 ms) and totals 951 ms, so the waiting is concentrated in a few frames rather than
     spread. At **one slot every frame waits for the previous submission** (submitWindow p50 18.41 ms, total
     11031 ms, which is the entire window) and the bimodality is **gone**: P50 20.14 against P95 21.25, a 1.06x
     gap. So the fast and slow populations of the default depth are the frames that find their third-oldest
     submission complete and the frames that do not - the first of this blocker's named candidates, measured.
   - **And it is not what makes an arm slow, which is the useful half.** Four slots removes the submission wait
     almost entirely (total 0.77 ms, p50 0.00) and is the **slowest arm of the four** - 24.37 ms a frame, its
     own commit feedback 24.39 - while the default three slots, with 951 ms of submission waiting, is 18.32 and
     18.48. More room to run ahead bought nothing and cost a third of the frame. The three arms at one, two and
     three slots read their own GPU time **18.31, 18.35 and 18.48 ms - a 0.9% spread**, the tightest this path
     has produced; the fourth reads 24.39, and its own commit windows sum to its whole wall time (14629 against
     14621 ms), so the GPU was busy for all of it. **What this session cannot say is whether the fourth slot made
     the GPU's work slower or made the driver's per-commit window wider**; what it can say is that the ring depth
     is not a free variable above the migration's own number, and that a spread of the kind blocker 16 is about
     is not the slot wait.
   - **The load trace again fails to order the arms**, on its first session as a harness feature: the machine's
     own one-minute average rose from 4.12 (slots1) through 4.54 and 5.49 to 5.77 (slots4) as the session ran, and
     the arm at the *highest* load was the slow one while the arm at the *second highest* was the fastest.

   **And it was repeated, which is when a reading stops being an anecdote.** `run/m4-rings2`, the same four arms in
   the same order, completed three of them:

   ```text
   slots1  12137.59 ms / 600   20.23 ms a frame   wallP50 20.28  wallP95 21.30 (1.05x)   gpuM4P50 18.48
   slots2  11045.75 ms / 600   18.41               wallP50 18.42  wallP95 20.71 (1.12x)   gpuM4P50 18.44
   slots3  10908.45 ms / 600   18.18               wallP50  9.45  wallP95 36.94 (3.91x)   gpuM4P50 18.23
   ```

   The shape repeats to the digit that matters: the bimodality is 3.91x at three slots, 1.12x at two and **1.05x at
   one**, and the *six* arms of the two sessions at one, two and three slots read their own commit feedback
   **18.23, 18.31, 18.35, 18.44, 18.48 and 18.48 ms - a 1.4% spread across two sessions and three configurations**.
   That is the tightest this path has ever read, and it says the machinery is not drifting; what moves the arm
   totals is what happens *around* the commit. The fourth arm of the repeat produced **no window at all**: the pack
   reached its first full frame, the encoder ran 1402 submissions and closed cleanly (`complete=true`, ring state
   naming four awaited submissions, so the switch took effect) 27 s later - two seconds after the settle ended -
   with no probe line and no fault, exception or restart in its log. **NOT LOCALISED**: it is the same
   "no window" shape as the forced-Metal-4 session of blocker 18 and it is not the path refusing anything, so it
   is recorded as a second instance of a harness-shaped end rather than as a property of four slots. The repeat's
   traces also carry `window-opened` in all four arms, which is the fix below verified in a live session rather
   than in the code.

   **The harness now keeps that evidence by itself.** Every arm writes `load-trace.txt` beside `load.txt` - the
   same reading every five seconds, with `window-opened` and `window-closed` lines so a later reader can slice it
   to the frames the probe counted, bounded at 240 samples and stopped on **both** ways an arm can end (its window
   closes, or it never reaches one). `tools/ci-vitrail-performance.py` pins the trace, the two markers, the stop
   and the bound, and each of those checks was mutation-proved. **And the markers were not there in that session's
   four traces, which the first run of the new code is what found**: the tracer had redirected its own file while
   the arm appended its markers to the same one, so the tracer's descriptor carried its own offset and its next
   sample landed on the marker the arm had just written, erasing it - `window-opened` was absent from all four arms.
   The file is emptied once per arm and every writer appends now, and the contract refuses the redirecting form and
   the missing truncation (both mutation-proved) rather than trusting the shape that produced the loss.

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
not where the caller does (blocker 15 - **and this round measured that directly, with the driver's window, the
CPU's completion wait and a fixed-cost control on the same submission: the markers account for a constant
2.19-2.34% of it, so no per-pass attribution exists**), and the four-arm performance session's Metal 4 arms
disagree by more than
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


## The definition of done, item by item

Section 122 lists the items the phrase "Metal 4 full-frame implementation complete? YES" is allowed to rest on.
This is that list with the state each item actually has, and where each reading is:

```text
[MEASURED]   Cold-probe problem either fixed or still explicitly blocks AUTO
             registered as intermittent (blockers 5 and 6); 30 cold processes are the harness's job and AUTO
             stays blocked until they pass - the item as written, satisfied by being explicit
[MEASURED]   Metal4 execution provider exists          Metal4Path, one queue, selectedGeneration/executingGeneration
[MEASURED]   Metal4 frame encoder exists               Metal4FrameEncoder, one command buffer and one commit a frame
[MEASURED]   native render smoke passes                the cold census, every field 50 of 50
[MEASURED]   no-pack frame passes                      run/nopack-ab1, four arms, one frame a generation, no fault
[MEASURED]   Vitrail fullscreen smoke passes           the fixture packs' passes run through this path
[MEASURED]   MRT passes                                four attachments cleared, drawn and read back, both arms
[MEASURED]   depth passes                              two depth fixtures read on both arms
[MEASURED]   argument-table binding passes             the production binding path, photon's wide pipeline through it
[MEASURED]   blit passes                               blits 5400 and blittedMiB 101022.1 equal on both
                                                       generations in every session of the ladder
[MEASURED]   compute passes                            compute-storage-contract dispatches twice a frame on this path
[MEASURED]   synchronization fixtures pass             section 60's seven fixtures and 61's three directions
[MEASURED]   presentation owned by full M4 path        the frame's own command buffer and queue; the sidecar is not
                                                       started when this path executes
[MEASURED]   resize passes                             the lifecycle session's 2560x1440 -> 3200x1800 -> 2560x1440
[MEASURED]   reload passes                             F3+T through delayTextureReload, caches cleared, chain rebuilt
[MEASURED]   dimension passes                          the nether teleport in the same session as the frame
[MEASURED]   shutdown clean                            Stopping!, BUILD SUCCESSFUL, zero teardown warnings
[MEASURED]   M3 forced path unchanged                  -Dmetallum.execution=metal3 runs the reference path, and the
                                                       no-pack ladder reads it identical across four sessions
[FINDING]    fallback works                            the Metal 3 *fallback* is verified; what is NOT is the
                                                       forced-Metal-4 path finding it - see blocker 18
[MEASURED]   architecture CI green                     twelve contracts, every new one mutation-proved
[ONGOING]    real Apple Silicon validation complete    every reading in this report is from this machine, and the
                                                       work that remains is the state a quiet machine is needed for
[MEASURED]   docs updated                              this report and docs/metal4-migration.md
```

**So the phrase is still not earned, and the two items that stop it are named**: the cold probe's intermittency
(which blocks AUTO and not the implementation) and the forced-Metal-4 fallback below. Everything else on the list
has a reading behind it, and the readings are in this report rather than in a summary of it.

## Blocker 18, found while trying to run the cold probe under Metal API validation

`MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1` is the environment's own validation layer, and it is the only way to
have the driver say *why* a native call is refused - so it was tried on the cold probe and on a forced Metal 4
launch. The probe process prints nothing at all under it (the harness reports `process-printed-nothing` for every
cold run), and a client launched under it reports:

```text
Metal device capabilities: metal3Family=true metal4Family=true queue=true allocator=true buffer=true
                          argumentTable=false render=false compute=true residency=true viewPools=true
                          compiler=true metalFx=true
Metal execution: Metal 4 probe: the first attempt in this process failed at pixel (the uniform pass drew
                 (0, 0, 0, 0) where (64, 128, 191, 255) was asked for ...), and the second ...
Failed to create backend Metal: Metal device initialization failed: metallum.execution=metal4 was asked for,
                 and this device does not satisfy the Metal 4 minimum contract
Using graphics backend OpenGL
```

Two findings, neither of them the GUI fault this round was about, and both worth having:

- **The validation layer is not usable here.** It makes the probe's own `argumentTable` and `render` capabilities
  read false, which is either the layer refusing something the probe does or the probe doing something the layer
  will not accept - and either way the device then satisfies no Metal 4 contract at all. So the road to "let the
  driver name the fault" is closed in this environment until that is understood, and every native claim in this
  report rests on the cold census and on measured pictures rather than on the validation layer's agreement.
- **A forced Metal 4 launch whose device fails the contract ends on OpenGL, not on Metal 3.** Section 76 says a
  device that cannot satisfy `-Dmetallum.execution=metal4` must not crash and must say what happened, and that is
  what it does - the two lines above are printed - but the engine that picks up the frame afterwards is the
  OpenGL backend, where this project's whole comparison assumes the Metal 3 reference. A developer who forces
  Metal 4 on a device that cannot take it therefore measures neither generation, and nothing in the log says the
  reference path was skipped. **The silence is fixed (commit `d5dba49`): the refusal now says the Metal 3
  reference path is not being taken either and names the switch that takes it**, so the session is no longer
  able to measure OpenGL without saying so. What is **NOT FIXED** is the behaviour itself, and it is deliberately
  not touched: this project's public behaviour for a forced generation the device cannot satisfy is a startup
  failure rather than a silent demotion, so landing on Metal 3 would be a change to that behaviour rather than a
  repair of it - the decision belongs with the plan's section 76, not with this reading.
