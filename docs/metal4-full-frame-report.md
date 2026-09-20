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

cold runs:        100 (two runs of 50)        failures: 3     (processes 46, 48, 49 of the first run)
warm probes:      400 (300 then 100)          failures: 0
rate:             3 of 100 cold = 3 %;  0 of 400 warm
uniform pass:     0 failures in all 500 attempts, and this round is the first time it was checked at all
AUTO blocker:     REGISTERED. AUTO must not promote Metal 4 full-frame execution while this is open.
                  Forced Metal 4 development continues.
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

**Not cold first use of the argument table, and not a capability gap.** Every selector answers true in every
failure, and `selected`/`executing` are untouched by any of this. What is left is what differs on a cold
process: the fault appears in cold processes only (3 of 100 against 0 of 400), it clustered in three of the
last five processes of one run and did not reproduce in the next fifty, and its probe times were ordinary
(227, 362, 438 and 463 ms), so it is not a timeout. Driver state accumulated over a burst of process starts,
and a low-frequency race, both remain candidates and neither is distinguished yet.

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
