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
Metallum: e55985e  (perf/optimisation; the plan's own reference is 81b3426, which this is one commit past -
                    868d5b5 then e55985e, both Metal 3 bookkeeping, neither a Metal 4 change)
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
cost a probe:     about 240 ms, cold; about 4 ms for the second and later probe in one process
                  against the client's ~70 s per arm, which is what made this measurable

cold runs:        50 processes          failures: 1     (process 11)
warm probes:      20 in one process     failures: 1     (attempt 20)
rate:             2 of 70 = 2.9 %

both failures:    stage=pixel
                  reason=the vertex-buffer pass drew 191 in channel 2 where 128 was asked for
                  canMakeAndSubmit=true  canBindAndDraw=false
                  familyMetal4=true  queueSelector=true  argumentTableSelector=true
                  deviceCreation=ok  deviceName=Apple M5 Pro  probeMs=227.3 / 5.4

AUTO blocker:     REGISTERED, and narrowed rather than resolved. AUTO must not promote Metal 4
                  full-frame execution while this is open. Forced Metal 4 development continues.
```

**What the two failures establish.**

The stage is named and the value identifies the failed pass exactly. `EXPECTED_UNIFORM_PIXEL` is
`{64, 128, 191, 255}` and `EXPECTED_VERTEX_PIXEL` is `{64, 128, 128, 255}`; they differ in **channel 2
alone**, so a readback of 191 is the *first* pass's pixel rather than a corrupted one. Pass two's channel 2
comes from a literal in its shader, so it would read 128 if any fragment of it had been written: 191 means
pass two's triangle covered nothing at all, and its clip-space triangle covers the whole target, so the
positions it read must have been degenerate.

Two hypotheses survive and neither is distinguished by anything measured yet: the vertex buffer's contents
written through `contents()` on a `StorageModeShared` buffer not being visible to the GPU, or the argument
table's `setAddress:attributeStride:atIndex:` not taking effect for that draw. Both give three positions at
the origin. The fault is equally frequent cold (1 of 50) and warm (1 of 20), so it is **not** cold first use,
and probe times were ordinary, so it is not a timeout.

**What the two failures retire.**

The capability record's `argumentTable=false render=false` was read as a missing argument-table capability. It
is not: every selector answers true in both failures, and the record ANDs one `canBindAndDraw` verdict into
both fields, so those two flags were never two findings. `-Dmetallum.execution=metal3` still pins the stable
path, and nothing in the frame path gates on the selection.

**What is left for this milestone** is the smallest reproducer that separates the two hypotheses - a probe that
reads the vertex buffer back on the CPU after the draw, or one whose second pass clears its target first so a
missed draw reads as the clear colour instead of as undefined tile memory (`LOAD_DONT_CARE` plus `STORE_STORE`
leaves a missed draw's pixels undefined by the API's own contract).

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
