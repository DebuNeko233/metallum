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
cost a probe:     about 240-460 ms cold; about 4 ms for the second and later probe in one process
                  against the client's ~70 s per arm, which is what made this measurable

cold runs:        160 processes, 1260 probes (50 + 50 + 60, the last with 20 probes each)
                  failures: 4, every one of them at ATTEMPT 1 of its process
warm probes:      500 in three processes      failures: 0
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
                  refusal reported by name. The DRAWN half - a sampled pattern read back channel by
                  channel - is OWED and is the next task; this entry is not it
multi-pass:       PROVEN and now the probe's own shape - two render encoders in one command buffer,
                  each into a target of its own (pass A into target A, pass B into target B), one
                  commit, one shared-event wait, both pixels read back
```

**What the owed half needs, so it is a task and not a wish**: reuse the first pass's target as the source
(a texture this probe has already filled with a known colour, so no texture-write path has to be added),
bind it with a nearest sampler through a one-texture/one-sampler table, draw a full-screen triangle whose
fragment shader samples it, read the third target back and compare with (64, 128, 191, 255).

## M4 Frame

```
provider:            PROVEN as a skeleton - Metal4ExecutionProvider implements the neutral
                     MetalExecutionProvider, its queue factory is real on this device
                     (`newMTL4CommandQueue` returns a non-nil queue), and its two frame halves refuse by
                     name: `queue=ok,state=refused(createExecutionState),encoder=refused(createFrameEncoder)`
                     measured in the cold-probe harness, per process, on Apple Silicon
reached by:          the services now hand out the provider of the EXECUTING generation rather than a
                     constant `new Metal3ExecutionProvider()`, so selected=Metal4 with executing=Metal3
                     still builds the frame from Metal 3 objects, exactly as section 19 requires - the day a
                     Metal 4 frame path is ready, the device constructor's one line changes
queue:               PROVEN for the provider skeleton; no frame is submitted through it yet
allocators:          NOT STARTED
command buffers/frame: NOT STARTED
commits/frame:       NOT STARTED
presentation:        EXPERIMENTAL  (the present sidecar, Metal4Path + Metal4PresentGate, still in place)
```

## Render

```
basic:   NOT STARTED
MRT:     NOT STARTED
depth:   NOT STARTED
blend:   NOT STARTED
scissor: NOT STARTED
```

## Resource Binding

```
textures:        NOT STARTED
samplers:        NOT STARTED
uniform buffers: NOT STARTED
vertex/index:    NOT STARTED   (the probe binds one vertex buffer by address; no production path does)
argument tables: NOT STARTED   (probe only)
residency:       NOT STARTED
```

## Blit

```
full:   NOT STARTED
region: NOT STARTED
mipmap: NOT STARTED
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

No dependency fixture exists yet. The probe's own ordering (two render encoders in one command buffer, one
commit, one shared-event wait) is exercised on every attempt and has never failed at `commit`, `completion` or
`encoder` in 70 attempts - which is evidence about the probe's two-pass shape and not a matrix.

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

No Metal 4 frame exists to time. The Metal 3 reference on the pinned scene is
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
| render          | yes         | yes - `canMakeAndSubmit` encodes and submits a render pass on a 64x64 target | n/a | yes |
| MRT             | yes         | no - one target per pass          | n/a           | no          |
| depth           | yes         | no                                | n/a           | no          |
| sampled texture | yes         | **half** - binds through a table; the drawn pattern is owed | n/a | yes (binding) |
| sampler         | yes         | yes - a nearest sampler with `supportArgumentBuffers` is made and bound | n/a | yes |
| uniform         | yes         | yes - `setAddress:atIndex:` then a draw, read back (64, 128, 191, 255) | n/a | yes |
| vertex/index    | yes         | vertex yes - address + stride 16, colour out of the buffer, read back (64, 128, 128, 255); index no | n/a | yes (vertex) |
| argument table  | n/a (M3 uses argument buffers) | yes - buffer, texture and sampler tables made, bound and used | n/a | yes |
| blit            | yes         | no                                | n/a           | no          |
| mipmap          | yes         | no                                | n/a           | no          |
| compute         | yes         | no                                | n/a           | no          |
| storage buffer  | yes         | no                                | n/a           | no          |
| storage image   | yes         | no                                | n/a           | no          |
| synchronization | yes         | **partly** - two encoders in one command buffer, one commit, one shared-event wait, both pixels read; no cross-encoder dependency fixture | n/a | yes |
| presentation    | yes         | EXPERIMENTAL - the `Metal4Path` sidecar behind `-Dmetallum.metal4Present`, not the frame's road | n/a | yes (sidecar) |
| MetalFX spatial | yes         | no - the Metal 4 factory capability is probed, no scaler path is implemented | n/a | no          |
| counters        | whole frame | no                                | n/a           | no          |

**What the matrix is for here**: it is the list a reader checks before believing any claim about the migration,
and its blanks are the work. Nothing in the `M4 real frame` column can be filled until a Metal 4 frame encoder
exists, which is Phase 4; and nothing in it should be filled from a smoke, because a capability proven in a
process with no window is not the same claim as a capability proven through the client's own frame.

## Remaining blockers

1. **The intermittent capability-probe failure** - 2 of 70, stage `pixel`, two surviving hypotheses. Blocks
   AUTO, does not block implementation.
2. ~~No Metal 4 execution provider~~ - **the skeleton exists**: `Metal4ExecutionProvider` owns the queue and
   refuses the two halves it does not have. What is missing is the frame encoder itself, which is Phase 4.
3. **No Metal 4 frame encoder, render smoke, blit, compute or synchronization fixture** - all of the
   implementation milestones are ahead.

## Metal 4 full-frame implementation complete?

**NO.** One milestone has been measured, and the other twenty-two of the plan's order are ahead. The
Definition of Done in the plan has twenty-one unchecked boxes and none checked.
