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
verified:         production path, 40 cold processes + 20 warm: 0 failures
                  raw path,        40 cold processes + 20 warm: 0 failures (the fault did not fire in them)
not verified:     the retry has NOT been observed firing - that arm caught nothing in forty processes, so
                  this rests on the earlier evidence (every failure ever seen was a process's first
                  attempt; 1100 later probes passed) and not on these two runs
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
colour:           NOT STARTED
vertex:           NOT STARTED
uniform:          NOT STARTED
texture/sampler:  NOT STARTED
multi-pass:       NOT STARTED
```

## M4 Frame

```
queue:               NOT STARTED   (the probe makes one and proves it takes a submit; no frame encoder exists)
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

## Remaining blockers

1. **The intermittent capability-probe failure** - 2 of 70, stage `pixel`, two surviving hypotheses. Blocks
   AUTO, does not block implementation.
2. **No Metal 4 execution provider**: Metal 4 is a present sidecar today, and the provider boundary the plan's
   Phase 2 asks for does not exist yet.
3. **No Metal 4 frame encoder, render smoke, blit, compute or synchronization fixture** - all of the
   implementation milestones are ahead.

## Metal 4 full-frame implementation complete?

**NO.** One milestone has been measured, and the other twenty-two of the plan's order are ahead. The
Definition of Done in the plan has twenty-one unchecked boxes and none checked.
