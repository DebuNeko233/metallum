# Metallum Metal 3 steady-state optimisation

The final report, in the shape the plan asks for, followed by the phase-by-phase evidence it is read
from. Every number comes from an arm in `run/`; nothing is estimated, and a candidate that was measured
and found not worth doing is written down as a result rather than left open.

## Starting SHAs

```
Metallum: 33866a7c3dac4d67b19b0bcd35e5c9220a5f0557  (perf/optimisation; the plan's own reference HEAD)
Vitrail:  4380250f                                   (perf/optimisation; ahead of the plan's 67ca66ca, not reset)
```

## Benchmark

```
pack:          Photon v1.3b
preset:        55 %
resolution:    fullscreen at 1920x1200, world drawn at 1056x660
camera:        548.5,63,-248.5 yaw 0 pitch 7.8
warmup:        25 s settle after the pack's first full frame
frames:        600
present mode:  MAILBOX, displaySyncEnabled=false, Unlimited FPS
path:          executingGeneration=metal3, metal4Presents=0, compiles=0
```

The framebuffer is pinned by `--fullscreen-size 1920x1200`, which the harness now writes into the game's
own `overrideWidth`/`overrideHeight`, and every arm is checked against `--expect-target 1056x660`.
Before that flag existed the target was whatever mode the display was in: four modes were measured in
one evening and a crashed client moved the display between sessions. See "The instrument" at the end.

## Initial Baseline (`run/m3-baseline`, a1 and a2)

```
                 a1         a2
wallP50:       7.30       7.29   ms
wallP95:       8.13       8.25
wallP99:       8.54       9.13
wallMax:      13.17       9.85
gpuP50:        7.31       7.33
gpu total:  4380.63    4392.70   ms over 600 frames (0.28 % apart)

renderPasses/frame:   34.88      34.88
renderEncoders/frame: 35.73      35.73   (encoders 21440 / 21440)
blitEncoders/frame:    5.00       5.00   (3000)
computeEncoders/frame: 3.00       3.00   (1800)
clearEncoders/frame:   1.00       1.00   (600)

passChanged/frame:    34.73      34.73   (20840 / 20840)
blits/frame:          11.00      11.00   (6600)
loadedMiB/frame:     156.57     156.57   (93943.3 / 93943.3)
storedMiB/frame:     221.29     221.29   (132773.6 / 132773.6)

pipeline binds 29228 / 29228 · texture 75510 / 75510 · sampler 73710 / 73710
buffer 123318 / 129318 (this counter's own noise) · viewport 22128 / 22128 · scissor 21528 / 21528
pipelineIdentities 345 == pipelineKeys 345 · compiles 0 · compileMs 0.00

drawable wait:      p50 0.05 / 0.05 · p95 0.56 / 0.52 · max 1.04 / 2.84   ms
submitWindow wait:  p50 0.00 / 0.00 · p95 5.82 / 5.92 · max 6.12 / 6.29   ms
                    total 3214.41 / 3239.00 ms over 1200 calls
```

**Repeatability gate: PASS** - every structural counter identical, `gpuMs` 0.28 per cent apart,
`wallP50` 0.14 per cent. The two arms of one session are all the gate needs and all it is given.

Every structure the plan names was checked against this checkout before anything was measured:
`MetalRenderPass.argumentBufferStates` (one native `MTLBuffer` per wide layout per pass, released through
`MetalCommandEncoder.queueForDestroy`), `MetalCommandEncoder.MAX_SUBMITS_IN_FLIGHT = 3`, the direct
`newBuffer(Shared, Tracked)` allocation, the encoder-reuse condition and its single
`endEncoder(PASS_CONFIGURATION_CHANGED)` site, `MetalTransientMemory`, `createTexelBufferTexture` and
`MTLTexture.newBufferTextureView`.

## Candidate table

| Candidate | Cost observed? | Candidate implemented? | Result | Decision |
| --- | --- | --- | --- | --- |
| Argument-buffer allocation | yes: 2 native buffers a frame of 168 bytes, 336 bytes a frame | no | measured; too small to justify an arena | **REJECTED** |
| Render encoder churn | yes: 20928 of 66318 attempts, 31.6 % | no | every recreation is a colour-attachment change | **REJECTED** |
| Argument encoder rebinding | yes: 14400 set calls against 1200 real changes | yes | calls 14400 to 1200 (-91.7 %), writes and bindings unchanged | **KEPT** (`e2a221d`) |
| Per-pass allocations | yes: profiled, `MetalRenderPass` is 0.34 % of allocation | no | not a CPU/GC hotspot | **REJECTED** |
| Render-pass descriptor | yes: ~36 a frame, one per encoder opened | no | gate in §49 not met | **REJECTED** |
| Texel-buffer views | yes: **0 a frame** | no | the pack uses no texel buffer | **NOT APPLICABLE** |
| Fence synchronisation | no evidence of cost | no | GPU saturated 97.3 % in the trace | **REJECTED** |
| Submit window | yes: p95 6.11 ms against a 7.26 ms frame at depth 3; gone at 5; P99 5.6 % better at 5, repeatably | no | medians flat at 3, 4 and 5; latency cost unmeasured | **3 KEPT** |

## Argument Buffers (`run/m3-census`, c1 and c2)

```
wide passes/frame:           1.0
layouts/frame:               2.0
native allocations/frame:    2.0      (168 bytes each)
native bytes/frame:          336 bytes  (0.192 MiB over the 600-frame window)
setArgumentBuffer calls/frame:  2.0 after the kept change, 24.0 before it
actual changes/frame:        2.0      (unchanged by the kept change)
```

Decision: **REJECTED** for the arena (2 allocations a frame of 168 bytes is neither the "about one" the
plan stops at nor the "10+" it continues at), and **KEPT** for the rebinding the census found in the same
numbers.

## Render Encoder Churn (`run/m3-census`, c1 and c2)

```
reuse attempts:  66318      (110.5 a frame)
reused:          45390      (75.6 a frame, 68.4 %)
recreated:       20928      (34.9 a frame, equal to renderPasses)

clear:            3000      color: 20928      depth: 4800      contents: 10888
multiple:        10888      onlyColor: 10040  onlyClear: 0  onlyDepth: 0  onlyContents: 0
```

Decision: **REJECTED** - every recreation had a colour-attachment mismatch, so the churn is what the
frame's own attachment changes require. There is no clear-only and no contents-only case for §28 or §31
to work on.

## Submit Window (`run/m3-submits`)

`submitWindow` is real on Photon and this is the measurement §84 asks for, at three window depths, all on
the pinned 1056x660 target:

```
              depth 3      depth 3      depth 4      depth 5
              (s3)         (s3b)        (s4)         (s5)
wallP50        7.26         7.26         7.27         7.28   ms
wallP95        8.45         8.65         8.53         8.45
wallP99        9.48         9.58         9.04         8.67
wallMax        9.71         9.87         9.97         9.59
gpuP50         7.29         7.29         7.30         7.29
gpuMs       4368.27      4368.25      4376.60      4369.25
loadedMiB   93922.0      93943.3      93922.0      93922.0

submitWindow  p50/p95/max      0.00 / 6.11 / 6.33      0.00 / 6.18 / 6.51
                               0.00 / 6.19 / 6.44      0.00 / 0.00 / 0.00
              total           3303.51 ms             3342.70 ms
                              3364.63 ms                0.12 ms

drawable      p50/p95/max      0.05 / 0.79 / 1.17      0.05 / 0.81 / 2.22
                               0.05 / 0.81 / 1.30      0.05 / 0.86 / 3.03
```

**And the repeat found something the design had not controlled.** The test the plan's own "reverse the
order for a claim that matters" rule asks for was run as 3, 5, 3, 5 (`run/m3-submits-repeat`), and its
first arm is an outlier at either depth:

```
            depth  gpuMs     wallP50  wallP95  wallP99   (first arm of the session flagged)
s3a            3   4298.41     7.13     8.05     8.46    <-- first arm
s5a            5   4368.85     7.29     8.40     8.73
s3b            3   4369.82     7.27     8.60     9.23
s5b            5   4366.76     7.27     8.04     8.53
```

Pooled with the first session and with the first arm set aside, `wallP99` is **9.23, 9.48 and 9.58 at
depth three** against **8.53, 8.67 and 8.73 at depth five** - the two sets did not overlap, and depth five
was about 0.8 ms (8 per cent) lower on the worst frame in a hundred. **But depth five was never measured
first in either session, and the one arm that read better than every depth-five arm was a depth-three
first arm**, so the two effects were entangled in that design and the difference could not be attributed
to the depth from it. The reversed order below settles it.

**The reversed order (5, 3, 5, 3) settles it** (`run/m3-submits-reversed`):

```
            depth  gpuMs     wallP50  wallP95  wallP99  wallMax   submitWindow total
s5c            5   4389.81     7.31     8.27     8.71     8.99     0.12 ms   <-- first arm
s3c            3   4368.49     7.25     8.51     9.29    10.52  3358.61 ms
s5d            5   4378.58     7.29     8.51     8.78    10.41     0.15 ms
s3d            3   4372.37     7.25     8.39     8.69     9.36  3380.00 ms
```

**Depth five is measured first here and still lands in its own band (8.71), while a depth-three arm
measured fourth reads 8.69 - inside that band.** So the effect is real and the first-arm effect is not
what produced it, but the two distributions are not cleanly separated either:

```
wallP99 at depth 5 (five samples, none discarded): 8.53 8.67 8.71 8.73 8.78   mean 8.68
wallP99 at depth 3 (first arms excluded, four samples): 8.69 9.23 9.29 9.58   mean 9.20
wallP99 at depth 3 (the two first arms): 8.46 9.48
```

**So: the P99 improvement repeats, it is about 0.5 ms (5.6 per cent) at the mean, five of the six
adjacent depth-three-against-depth-five comparisons in the three sessions favour depth five and the sixth
is a 0.09 ms tie - and one depth-three sample out of four lands inside the depth-five band.** It is not
noise, and it is not a clean separation either. `gpuMs`, `wallP50` and `wallP95` are flat across every
arm at every depth, including the reversed order.


**Decision: three kept, on the tradeoff and not on the frame.** The wait is not idle chatter - at three it is 3303 and 3343 ms over 1200 calls,
a p95 of 6.11 and 6.18 ms against a 7.26 ms frame - and at five it disappears entirely (p95 0.00, 0.12 ms
in total). **And the frame does not move**: `gpuMs` 4368.27 and 4368.25 at three, 4376.60 at four, 4369.25
at five, `wallP50` 7.26 / 7.27 / 7.28. Depth four does not even remove the wait, which is why the trial
was worth running rather than reasoning about: 4 sits between the two and behaves like neither prediction.

**What the depth counts, said precisely, because the obvious reading is wrong.** It is a
**submission-index window**, not a count of frames in flight: the ring is indexed by `currentSubmitIndex`,
which advances on every submission **including an empty one**, so a depth of three is three submission
indices and not three rendered frames. On this client, which submits twice a frame (1200 submit-window
calls over 600 frames), that works out at about one and a half frames of slack at three and two and a
half at five - a useful figure and not the definition. A reading of "three frames in flight" would
overstate the window by half and would make the tradeoff below sound larger than it is.

**Why three keeps, stated as an inference and not as a fact.** The measurement is that the wait moves and
the frame does not: 3300 ms of waiting becomes 0.12 ms, and `gpuMs`, `wallP50` and `wallP95` are flat
across all three depths. The explanation that fits is that the wait is the render thread being held to
the submission rate of a frame the card is already saturated on, so running further ahead buys a queue
rather than a frame - that is, **consistent with GPU pacing, and the replacement pacing site was not
separately measured**. The arms establish the flatness and not the reason for it. They cannot separate
"the CPU is paced by the GPU" from "the throttle is what the frame costs and this is merely where it
appears", because both predict a wait that vanishes when the ring is deep enough and a frame that does
not move; and nothing here shows *where* the pacing went instead - the wait may have moved into the
drawable wait, into the submit itself, or nowhere at all, and the drawable wait was not read at five
against three for this purpose. What would separate them is a measurement this programme did not take: a frame whose
`gpuMs` is below its `wallP50`, where a deeper window would have slack to use.

**Why three and not five, with the P99 result on the table.** Depth five is better on both things this
programme can measure: the stall goes, and the tail improves by about 5.6 per cent repeatably. What §65
asks to be weighed is what was *not* measured, and it points the other way: each slot holds a command
buffer and its share of the transient allocator's blocks (512 KiB blocks, rotated per submit), and the
render thread ends up about one to two and a half submissions further ahead of the picture the player
sees, so two more slots is more memory and roughly half a frame more input latency in a configuration
that already runs unlimited frames ahead. The frame's medians do not move, so the change would buy a
tail metric with an unmeasured latency cost - and §65's instruction is precisely not to decide that on
frame numbers alone. **Production therefore stays at three**, and what would reopen it is one
measurement this backend does not have: input latency at the two depths. If that reads flat, five is the
better window on all the evidence there is, and the trial is one property away.

The trial's mechanism was a `-Dmetallum.submitsInFlight=N` read, which is **reverted**: production code
holds `public static final int MAX_SUBMITS_IN_FLIGHT = 3` with the measurement written beside it. Nothing
of the trial is left in the tree except the javadoc that records why three is three.

## Per-Pass Allocation (`run/m3-alloc`, JFR)

```
MetalRenderPass/frame:     34.9 constructed
binding objects/frame:     TextureViewAndSampler below the sampling floor
array allocations/frame:   not visible in the sampled set
profile result:            MetalRenderPass 0.34 % of steady-state allocation pressure
```

Decision: **REJECTED** - not a CPU or GC hotspot, and the two candidates that would remove these
objects (4A's unchanged binding record, 4C's scratch arrays) have no measured cost to remove.

## Texel Views (`run/m3-census` and `run/m3-census2`)

```
created/frame:  0
unique/frame:   0
```

Decision: **NOT APPLICABLE** - this pack binds no texel buffer, so `newBufferTextureView` never runs.

## Synchronisation (`run/m3-census`, `run/m3-census2`, the repository's GPU trace)

```
evidence:   no capture attributes cost to a fence; the trace reads 13.65 s of shader-core activity in a
            14.04 s window (97.3 %, every second between 0.99 and 1.03), so the card is saturated and
            there is no idle time for a fence wait to hide in. The pass table cannot supply the missing
            evidence because its rows are CPU encode time on this backend.
candidate:  none implemented
result:     conservative model retained - 23 fence sites, Untracked resources, updateFence on the
            closing encoder and waitForFence on the next
```

Decision: **REJECTED** - §83 makes "no evidence of significant cost; conservative model retained" a
complete answer.

## Phase 4 - Per-Pass Allocation Census (JFR, `run/m3-alloc`)

The plan asks for a real allocation profiler before any counter, and one was armed
(`-XX:StartFlightRecording=filename=/tmp/m3-alloc.jfr,settings=profile,dumponexit=true`), on the reference
scene, as the first arm of a session.

**The instrument crashed the client, and that is recorded rather than worked around.** The launch died
with `Internal Error (signals_posix.cpp:1793) ... ShouldNotReachHere()` at 22.3 s elapsed, after the
pack's first full frame and about twelve seconds of steady play - a JVM fault in the signal handler, not
a Java exception and not this engine's code (the command line in `run/hs_err_pid33650.log` shows the
recording armed). The crash wrote its own emergency recording, `run/hs_err_pid33650.jfr`, and that is
what the profile below is read from: 3280 `jdk.ObjectAllocationSample` events over the whole 22 s, of
which **918 fall inside the steady-state window** (first full frame to the crash, about 1600 frames).
The second arm of that session never ran.

**What the steady-state window says** (sampled weight, 3040.0 MB total):

```
class                                                      MB        %   samples
int[]                                                 1037.80   34.14 %      173
byte[]                                                 410.06   13.49 %      171
long[]                                                 309.14   10.17 %       60
java.lang.Object[]                                     168.58    5.55 %       28
Sodium BlockRenderer lambda                            130.15    4.28 %       97
com.mojang.serialization.DataResult$Success             94.86    3.12 %       39
java.lang.ScopedValue$Snapshot                          75.79    2.49 %       30
net.minecraft.nbt.CompoundTag                           58.61    1.93 %        6
java.lang.ScopedValue$Carrier                           57.51    1.89 %       31
java.util.HashMap                                       56.95    1.87 %       16
Sodium ChunkVertexEncoder$Vertex                        54.82    1.80 %       42
...
com.mojang.blaze3d.util.TransientBlockAllocator         31.73    1.04 %        1
com.mojang.blaze3d.buffers.GpuBufferSlice               15.52    0.51 %        7
com.mojang.blaze3d.systems.CommandEncoder                12.14    0.40 %        4
com.metallum.render.metal3.MetalRenderPass              10.26    0.34 %        3
GpuBufferSlice[]                                         9.29    0.31 %        2
MetalTransientMemory$TransientGpuBuffer                   6.23    0.21 %        3
org.joml.Matrix4f                                        4.55    0.15 %        2
```

**Decision: REJECTED - the per-pass objects are not a CPU or GC hotspot.** `MetalRenderPass` - the
object §39 puts at ~35 a frame and ~5000 a second, with its `ScissorState`, its three maps, its `BitSet`
and its three cloned attachment arrays - is **0.34 per cent** of the steady-state allocation pressure,
and its attachment arrays do not appear in the sampled set at all. `TextureViewAndSampler`, the record
§41 proposes to stop allocating when a binding has not moved, **does not appear either**, so §41's
candidate has no measured cost to remove. What the sample is dominated by is Sodium's meshing (`int[]`,
`byte[]`, `long[]`, its vertex and lambda objects) and Mojang's own data structures, none of which this
backend owns.

**What would change this answer**: an allocation profile of the *whole* play window rather than the
twelve seconds before a crash, and a JVM that can run the profiler. The sampling floor is the other
limit and is stated: a class at 0.34 per cent is three samples, so the figure is an order of magnitude
and not a precise share - which is all the decision needs, because a hotspot would be tens of per cent.

**The instrument itself is now a known quantity**: JFR armed on this client (Temurin 25, macOS 27,
FFM/ObjC) crashed it once out of one attempt, and the retry in `run/m3-census2` is recorded with its
outcome. Nothing in this programme depends on it, because the counters it was meant to replace came in
at no measurable cost.

## Phase 5 - Native render-pass descriptor census (`run/m3-census2`, c1 and c2)

```
                        c1        c2
passDescriptors:     21738     21744      (~36.2 a frame)
encoders:            21615     21620      (the encoder ends of the same window)
renderPasses:        21138     21144
blit / compute / clear encoders:  3000 / 1800 / 600
```

**One descriptor per render encoder opened**, which is what §48 says it should be; the residual between
opens and ends (about 122 over 600 frames) is the window's own boundary - an encoder still open when the
line was written is counted as an open and not as an end.

**Decision: REJECTED, on §49's own gate.** Reuse of one descriptor per `MetalCommandEncoder` is
permitted only where the native allocation cost is *clearly visible in the CPU profile*, and it is not:
the descriptor's Java side does not appear in the steady-state allocation profile of Phase 4, and its
native side is one `alloc`/`release` pair per encoder open. What reuse would buy is 36 ObjC allocations
a frame on a frame that is GPU-bound at 7.30 ms, and what it would cost is the whole reset contract of
§50/§51 - every colour slot, both actions, the clear values, the depth attachment and the render-target
size, with the 8-attachments-to-2 case pinned by a fixture - so that a stale slot cannot be read. The
plan's gate is not met, and this candidate is not one of §88's completion requirements either.

**The arms ran on another render target and the report says so**: 1760x990 for a 3200x1800 window,
`loadedMiB` 202946.9 against the anchor's 93943.3, `gpuP50` 10.27 against 7.30. The two arms agree with
each other (0.01 per cent on `loadedMiB`), and the counters read here are per-pass structural ones, so
the answer stands - but the session is not a baseline and could not have been compared with one. The
cause is recorded under Phase 4: the JFR crash left the display on another fullscreen mode.

## Phase 6 - Texel-buffer texture view census (`run/m3-census`, c1 and c2)

```
texelViews:            0        0        (both arms, anchor target)
```

**Decision: NOT APPLICABLE.** §82's rule is that a nought ends the direction immediately: `Photon v1.3b`
binds no texel buffer at all, so `createTexelBufferTexture` and its `MTLTexture.newBufferTextureView`
never run on this pack and there is nothing to cache. The counter is a per-descriptor-push count of a
structural event, so the zero is a property of the pack and not of the target it was measured on: the
same nought appears in the sessions on the anchor target and, in the same session, beside the Phase 5
arms on the other one.

What remains is the *possibility* rather than the measurement, and it is named: a pack that binds a
buffer as `TEXTURE_BUFFER` would create one view per descriptor push per pass, and §54/§55's cache (with
a `backingGeneration` on `MetalGpuBuffer` so a `swapBacking` invalidates the key) is what it would need.
No such pack is on this machine, so the candidate is closed as NOT APPLICABLE rather than built for a
workload nobody has.

## Phase 7 - Fence and encoder synchronisation

**Decision: REJECTED - no evidence of significant cost; the conservative model is retained.** §83 makes
exactly this a complete answer, and §57 gates any change on one of three pieces of evidence, none of
which exists here:

- **No GPU capture attributes cost to a fence.** The GPU trace this repository already has reads 13.65 s
  of shader-core activity in a 14.04 s window - 97.3 per cent, every second between 0.99 and 1.03 - so
  the card is saturated and there is no idle time in which a fence wait could be hiding.
- **The pass table cannot supply the second**, because on this backend its rows are CPU encode time
  (`MetalDevice.getTimestampNow()` is `System.nanoTime()`), so a gap between its stamps is not a GPU
  wait and cannot be attributed to an encoder transition.
- **No controlled A/B exists**, and one could not be read cleanly anyway: §60 forbids changing the fence
  model and the hazard-tracking mode in the same change, so a trial would have to be fence-only with the
  resources left `Untracked` - a shape that is safe to run but whose result would still need the
  resource-dependency proof of §59 to be kept.

The conservative model stays: 23 fence sites, `Untracked` resources, `updateFence` on the closing encoder
and `waitForFence` on the next. Nothing about it was changed, and nothing about it is claimed.

## Phase 1 - Argument buffer allocation census (`run/m3-census`, c1 and c2)

Two arms, identical to each other, with the census added to the frame probe and nothing else changed.
**Every figure in this block is the whole 600-frame window**, which is what the probe's line reports; the
per-frame figure is beside it in brackets. The one place that distinction bites is `allocationMiB`, the
memory the window's allocations asked the device for: 0.192 MiB over 600 frames is **336 bytes a frame**,
not 0.192 MiB a frame.

```
                    c1          c2
passes:             600         600    (1 wide pass a frame)
layouts:           1200        1200    (2 a frame)
allocations:       1200        1200    (2 native MTLBuffer allocations a frame)
allocationMiB:    0.192       0.192    (168 bytes an allocation, 336 bytes a frame)
setCalls:         14400       14400    (24 a frame)
setChanges:        1200        1200    (2 a frame)
textureWrites:    12000       12000    (20 a frame)
samplerWrites:    12000       12000    (20 a frame)
bufferWrites:      1200        1200    (2 a frame)
useResourceCalls: 13200       13200    (22 a frame)
draws:              600         600    (1 wide draw a frame)
```

**Decision: REJECTED, on the plan's own Phase 1 gate.** The gate stops the candidate at "about one
allocation a frame and small bytes"; this is two allocations a frame of 168 bytes each - **336 bytes a
frame**, which is the 0.192 MiB the census line reports for the whole 600-frame window - and the gate's
reason to continue is "several allocations a frame, especially 10+, 20+, 30+".
Two is neither, and an arena to remove 336 bytes a frame from a 7.30 ms GPU-bound frame is complexity
bought on a number too small to pay for it. The measurement is what the plan asks for, so this is a
finished candidate and not an unmeasured one.

**What the same census found instead**, and it is the larger number: 14400 `setArgumentBuffer` calls in
the window for 1200 that actually retarget the encoder. 22 calls a frame wrote nothing. That is Phase 3.

## Phase 2 - Render encoder change-reason census (`run/m3-census`, c1 and c2)

```
                       c1        c2
attempts:           66318     66262    (110.5 a frame)
reused:             45390     45340    (75.6 a frame)
recreated:          20928     20922    (34.9 a frame, and equal to renderPasses)
reusePercent:        68.4      68.4

causes (a pass may fail several):
noEncoder:           4288      4287
clear:               3000      3000
color:              20928     20922
depth:               4800      4800
contents:           10888     10887

exclusive buckets (these sum to the encoders):
multiple:           10888     10887
onlyColor:          10040     10035
onlyClear:              0         0
onlyDepth:              0         0
onlyContents:           0         0
onlyNoEncoder:          0         0
```

**Decision: REJECTED - the churn is required by the frame's own attachment changes.** Every single one
of the 20928 recreations had a **colour attachment handle mismatch**; the count is exactly equal to the
recreations. The exclusive buckets say what a pass costs: 10040 recreations differ in nothing but their
colour attachments, and the remaining 10888 differ in colour as well as in declared contents. A clear
never stands alone (3000 passes carry one and every one of them also changes colour), and depth is never
the sole reason either (4800 appearances, always with colour).

So the plan's Phase 2 stopping condition is met in its strongest form: this is not "many encoders", it is
"the frame genuinely renders into different colour attachment sets 20928 times". §28's clear-preserving
reuse has no passes to work on (`onlyClear` is nought), and §31's contents experiment has none either
(`onlyContents` is nought). Nothing is changed here, and 68.4 per cent of pass asks already take the
encoder that is open.

## Phase 3 - `MTLArgumentEncoder.setArgumentBuffer` rebinding (KEPT)

The census above is this phase's "before": **14400 calls, 1200 of which retarget the encoder.** That is
the shape the plan says to act on (its worked example is 20000 calls against 2000 changes).

**The change**: `MetalRenderPass.setArgumentBuffer` keeps the buffer each compiled pipeline's
`MTLArgumentEncoder` was last handed - an identity map keyed by the encoder OBJECT, cleared wherever the
pipeline changes - and skips the call when the encoder already holds that buffer. The descriptor writes
themselves are untouched; what is not repeated is telling the encoder which buffer they belong in.

**Why it is sound**, pinned by a contract rather than argued: one `MetalRenderPass` per logical pass, so
the map starts empty and cannot outlive its pass; a layout's buffer is allocated once per pass and never
replaced under the map; and the encoder objects belong to a compiled pipeline and are shared between
passes, which is why the map is keyed by the object and cleared on a pipeline change. The encoder is told
first and the map records after, so a throw between the two leaves the map not knowing rather than lying.

**Mutation-tested**, all six failing for the intended reason:

| mutation | contract's answer |
| --- | --- |
| shadow cleared across a pipeline change | the shadow is not cleared exactly once, where the pipeline changes |
| shadow hoisted to a static | the shadow is not an instance field of the pass |
| a second, untracked `setArgumentBuffer` site | a second call exists, which the shadow does not track |
| the map recording before the encoder is told | the map records before the encoder is told |
| the pass pooled instead of built per pass | the pass is no longer built fresh for every logical pass |
| the skip removed | the skip is not decided in exactly one place |

**Measured A/B** (`run/m3-shadow-argbuf`, b1 and b2, against the census arms c1 and c2 of the same scene):

```
                              c1 / c2      b1 / b2
setArgumentBuffer calls:    14400 / 14400   1200 / 1200     -91.7 %
calls the shadow skipped:       0 / 0    13200 / 13200
textureWrites:              12000 / 12000  12000 / 12000    unchanged
samplerWrites:              12000 / 12000  12000 / 12000    unchanged
bufferWrites:                1200 / 1200    1200 / 1200     unchanged
useResourceCalls:           13200 / 13200  13200 / 13200    unchanged
passes / layouts / draws:  600/1200/600    600/1200/600     unchanged
native allocations:          1200 / 1200    1200 / 1200     unchanged

encoders:                   21440 / 21440   21435 / 21435   (the anchor's own spread)
passChanged:                20840 / 20840   20835 / 20835
loadedMiB:               93943.3 / 93943.3  93922.0 / 93922.0
storedMiB:              132773.6 /132773.6 132752.3 /132752.3
blits / blittedMiB:        6600 / 22159.3   6600 / 22159.3  unchanged
pipelineIdentities == keys:      345            345        unchanged
compiles / compileMs:            0 / 0.00       0 / 0.00    unchanged

gpuMs over 600:           4380.63 / 4392.70 4367.87 / 4366.48
wallP50:                     7.30 / 7.29       7.27 / 7.27
```

**Correctness**: every descriptor write and every `useResource` call is unchanged, so nothing about what is
bound moved; the structural counters sit inside the anchor's documented spread; and the picture the runs
drew is the same frame by the counters that describe it. The screenshots the harness left are **not** the
evidence - two launches of a temporal pack never draw the same frame - which is why this is argued from
counters and a contract.

**Frame time: no claim.** `gpuMs` reads 0.3-0.6 per cent better than the baseline arms, which is *inside*
the noise floor this scene has (the baseline's own two arms are 0.28 per cent apart, and the plan says
under one per cent is noise without strong mechanism evidence). The mechanism here is CPU ObjC call count
on a GPU-bound frame, so the measured result is the call count and nothing else.

## The instrument, and what it cost to trust

Four findings about measuring this backend came out of the programme. Each one changed how a number was
read, and three of them are now pinned by a contract so the next session cannot pay for them again.

**The render target was machine state, not a setting.** The game asks the display for nothing in
particular when it goes fullscreen unless `overrideWidth`/`overrideHeight` say otherwise, and the harness
did not write them. Four framebuffers were measured across one evening - 1920x1200, 3200x1800, 3840x2400
and 3600x2038, which is 1056x660, 1760x990, 2112x1320 and 1980x1120 drawn - and a crashed fullscreen
client left the display on another mode for every run after it. Two arms of one session can agree with
each other on a target the baseline never used, which `vitrail-performance-compare.py` cannot see because
it only compares the arms with each other. The harness now takes `--fullscreen-size WxH`, writes it into
the game's own override, and checks every run against `--expect-target WxH`; the final baseline was
reproduced on the initial baseline's target exactly with it. Eight mutation tests pin the flag, the
write, the read, the parse, the guard, the comparison and the log line it reads.

**JFR cannot run on this client.** Two armed attempts, two JVM faults: `Internal Error
(signals_posix.cpp:1793) ... ShouldNotReachHere()` at 22 s, with the recording armed in the command line
of `run/hs_err_pid33650.log` and `run/hs_err_pid34617.log`. The plan's preferred instrument for Phase 4
is therefore unusable, and the profile that answered the phase came from the crash's own emergency
recording - 918 steady-state samples, which is enough to rank allocation by class and not enough to be
precise about a class at a third of a per cent. Both halves are stated where the number is used.

**The pass-timing table cannot price a GPU pass on this backend.** `MetalDevice.getTimestampNow()` is
`System.nanoTime()` and the device reports a timestamp period of `1.0`, so a `Vitrail shadow chunk` row is
the *CPU cost of encoding that pass*. That is why Phase 7 could not use the table's gaps as fence
evidence, and it is the correction the Vitrail programme recorded in the same week.

**A crashed client costs more than the session it crashed in**, which is the practical form of the first
finding: the JFR crash moved the target for the two sessions after it, and one of those produced a pair
of arms that had to be thrown away. The guard turns that into a failed run instead of a wrong number,
which is the only kind of fix available from outside the game.

## Kept Optimisations

```
commit:             e2a221d  perf(m3): skip the argument-buffer rebinding the encoder already holds
mechanism:          MTLArgumentEncoder.setArgumentBuffer is state on the encoder object, and the
                    descriptor push re-pointed it once per resource written - 14400 calls a window for
                    1200 that retargeted anything. MetalRenderPass now keeps the buffer each compiled
                    pipeline's encoder was last handed, in an identity map keyed by the encoder object
                    and cleared wherever the pipeline changes, and hands it nothing when it already
                    holds that buffer.
before:             14400 setArgumentBuffer calls a window (24 a frame), 1200 of them real changes
after:              1200 calls, 13200 skipped (-91.7 per cent)
correctness proof:  texture, sampler and buffer descriptor writes and every useResource call unchanged
                    (12000 / 12000 / 1200 / 13200 in both arms); structural counters inside the anchor's
                    own spread; a contract pinning the three facts the skip rests on (one pass per
                    logical pass, buffers stable within a pass, map cleared at the pipeline change,
                    encoder told before the map records) with six mutations each failing for its own
                    reason
frame result:       none claimed - gpuMs moved 0.3 to 0.6 per cent, inside a floor this scene sets at
                    0.28, and the plan's section 70 says that is noise
```

## Rejected Optimisations

| Candidate | measurement | why the complexity was not justified |
| --- | --- | --- |
| Argument-buffer arena / suballocation | 2 native allocations a frame of 168 bytes, 336 bytes a frame (0.192 MiB over the whole 600-frame window), one wide pass and one wide draw a frame | Sections 14 and 22: the gate is about one allocation a frame, and an arena that removes 336 bytes a frame from a 7.30 ms GPU-bound frame is complexity bought on a number too small to pay for it |
| Render-encoder reuse by preserving a clear or by a looser contents policy | 20928 recreations, **every one** with a colour-attachment mismatch; onlyClear 0, onlyContents 0 | The churn is what the frame's own attachment changes require, and both candidates have no passes to work on |
| Per-pass allocation reduction (4A unchanged binding record, 4C scratch arrays, 4B clone removal) | JFR steady state: `MetalRenderPass` 0.34 per cent of allocation pressure, `TextureViewAndSampler` below the sampling floor, the attachment arrays absent | Not a CPU or GC hotspot, so there is no measured cost for a pool or a scratch array to remove |
| Render-pass descriptor reuse | 21738/21744 descriptors a window, one per encoder opened | Section 49's gate is that the native cost be visible in the CPU profile; it is not, and reuse would owe the whole reset contract of sections 50/51 to save one alloc/release pair per open |
| Texel-buffer view cache | 0 views a frame | Section 82: a nought ends the direction. Building a backing-generation cache for a workload this machine does not have is speculative complexity |
| Fence / encoder synchronisation | no capture attributes cost to a fence; the trace reads 97.3 per cent shader-core activity, so there is no idle time to hide a wait in | Section 57's evidence does not exist, and section 83 makes the conservative model a complete answer |
| Wider submit window (4, 5) | the wait disappears at 5 (3303 ms to 0.12 ms over 1200 calls) and **the frame does not move** (gpuMs 4368.27/4368.25 at 3, 4376.60 at 4, 4369.25 at 5) | A GPU-bound frame gains nothing from letting the render thread further ahead, and the deeper window costs memory and one to two frames of input latency |

## Final Baseline (`run/m3-final`, f1 and f2, pinned 1056x660)

```
                 f1         f2
wallP50:       7.26       7.25   ms
wallP95:       8.04       8.64
wallP99:       8.55       9.40
wallMax:       9.19      10.86
gpuP50:        7.28       7.29
gpu total:  4366.72    4368.05   ms over 600 frames (0.03 % apart)

renderPasses/frame:   34.90      34.90
renderEncoders/frame: 35.73      35.73   (21440 / 21435)
blitEncoders/frame:    5.00       5.00
computeEncoders/frame: 3.00       3.00
clearEncoders/frame:   1.00       1.00
passChanged/frame:    34.73      34.73
blits/frame:          11.00      11.00   (6600, blittedMiB 22159.3)
loadedMiB/frame:     156.57     156.54   (93943.3 / 93922.0)
storedMiB/frame:     221.29     221.25
depthAttachments:      4800       4800
pipelineIdentities 345 == pipelineKeys 345 · compiles 0 · compileMs 0.00

setArgumentBuffer calls/frame:   2.0 (1200)      skipped/frame: 22.0 (13200)
native argument allocations/frame: 2.0 (336 bytes)
descriptor writes/frame: 20 texture + 20 sampler + 2 buffer
passDescriptors/frame: 35.88 / 35.87   texelViews/frame: 0
argument layouts/frame: 2.0    wide passes/frame: 1.0    wide draws/frame: 1.0

drawable wait:     p50 0.05 / 0.05 · p95 0.66 / 0.86 · max 0.99 / 2.51  ms
submitWindow wait: p50 0.00 / 0.00 · p95 6.02 / 6.14 · max 6.38 / 6.42  ms
                   total 3293.08 / 3322.49 ms over 1200 calls
```

The final baseline reproduces the initial one's target exactly (1056x660, `encoders` 21440, `loadedMiB`
93943.3) and repeats to 0.03 per cent on `gpuMs`, which is tighter than the initial pair's 0.28.

## Net Improvement

```
wall absolute:           7.30/7.29  ->  7.26/7.25 ms   (-0.04 ms a frame, -0.5 %)
wall percentage:         -0.5 %, which is inside this scene's own floor
GPU absolute:            4386.67   ->  4367.39 ms over 600 frames (-19.28 ms, -0.032 ms a frame)
GPU percentage:          -0.44 %, inside the 0.28-0.7 % floor the scene measures
P95/P99 change:          8.13/8.25 -> 8.04/8.64 (p95), 8.54/9.13 -> 8.55/9.40 (p99): unchanged
native allocation change: none made and none needed (2 a frame before and after)
ObjC-call change:        setArgumentBuffer 14400 -> 1200 a window, -91.7 %, 13200 skipped
```

**No frame-time improvement is claimed, because none was measured.** The programme's one kept change
removes 13200 ObjC calls a window on a frame that is GPU-bound, and the plan's own noise floor puts
everything under one per cent in the noise class. That is the result the plan asks to be reported
honestly rather than dressed up: a backend cost that was real, measurable and large in *call count*, and
which the frame never paid for.

## Remaining Cost, and why further optimisation stopped

The frame is 7.26 ms of GPU work the card is saturated on, and what Metal 3 spends it on is now
decomposed. What remains is not backend overhead:

- **the pack's own raster and shader execution.** The whole backend-cost census - argument buffers,
  descriptor pushes, encoder opens, per-pass objects, texel views, fences, submit window - accounts for
  no measurable share of a GPU-bound frame. The shadow stage alone, measured in the Vitrail programme on
  the same scene, is 0.29 ms of the 7.30, and it is the pack's own required raster.
- **34.9 required render passes a frame**, each into the colour attachments its own program named: every
  one of the 20928 recreations was a colour-attachment change, which is what the frame is.
- **11 copy-backs and 1 clear a frame**, which the Vitrail programme measured as removable bytes that
  move no time on this scene.
- **the required synchronisation**, retained conservatively and with no evidence it costs anything.
- **the submit-window wait**, which widening the window moves without moving the frame (the reasoning
  behind that is an inference and is labelled as one in the Submit Window block above).

Further optimisation stopped because there is no remaining candidate with both a measured cost and a
provable correctness argument. The plan's closing condition is met: the residual is shader execution,
terrain raster, required passes, required attachment changes, required copies and required
synchronisation, and no measurably significant avoidable backend overhead is left in it.

## Metal3 steady-state optimisation complete?

**YES.** All seven of section 88's questions are answered, and "answered" here means measured rather than
modified:

| question | answer |
| --- | --- |
| Argument-buffer allocation | 2 native allocations a frame of 168 bytes - **REJECTED**, too small for an arena |
| Render encoder churn | 20928 recreations, **all** from colour-attachment changes - **REJECTED**, required by the frame |
| Argument encoder rebinding | 14400 calls for 1200 changes - **KEPT**, 14400 to 1200 |
| Per-pass allocation | `MetalRenderPass` 0.34 per cent of allocation pressure - **REJECTED**, not a hotspot |
| Texel-buffer views | 0 a frame - **NOT APPLICABLE** |
| Fence / synchronisation significance | no evidence of significant cost - **REJECTED**, conservative model retained |
| Submit-window significance | real at 3 (p95 6.11 ms), gone at 5, medians flat at 3, 4 and 5, P99 repeatably 5.6 % better at 5 (10 arms over three sessions) - **3 kept**, on the unmeasured latency tradeoff |

**And the tail question the last round left open is answered: the P99 improvement at depth five repeats.**
Ten arms over three sessions, two of them run in the reverse order to control the arm-position effect the
same test discovered: depth five reads 8.53 to 8.78 in all five of its samples, three of four non-first
depth-three samples sit above that band, and five of six adjacent comparisons favour depth five with the
sixth a tie. So this is not a candidate to close as unmeasurable, and the line is not closed on that
criterion; it is closed on the decision, which is that the two things this programme can measure both
favour depth five and the one it cannot measure - input latency - is what keeps production at three.



Answered and closed: argument-buffer allocation (REJECTED, 2 allocations a frame of 168 bytes),
render-encoder churn (REJECTED, every recreation is a colour-attachment change), argument-encoder
rebinding (KEPT, 14400 calls to 1200), per-pass allocation (REJECTED, `MetalRenderPass` is 0.34 per cent
of allocation pressure), texel views (NOT APPLICABLE, nought a frame), fences (REJECTED, no evidence of
significant cost). One candidate is measured and not yet decided: the submit window.

**The next round's first action is to restore the render target.** The initial baseline was taken on the
display's 1920x1200 mode (world 1056x660); the JFR crash left the display on a 3200x1800 mode (world
1760x990), and a crashed fullscreen client does not put it back. `--expect-target 1056x660` now refuses a
session that lands elsewhere, which turns a silent incomparability into a failed run - but it cannot
restore the mode itself, so the display has to be put back before the Phase 8 A/B and the final baseline,
or both have to be taken on one target together with a re-measured initial baseline on that same target.

**Phase 8's shape is known before it is run.** `MAX_SUBMITS_IN_FLIGHT` sizes `inFlight[]`,
`submitSemaphores[]` and `submitSignalBlocks[]` together, and section 64 requires
`MetalDestructionQueue` and transient-resource lifetime to be rotated with it, so the trial is not one
constant: it is a check that every ring believes the same depth. What the baseline says is that the
window is neither idle nor obviously worth widening - `submitWindow` p50 0.00 ms, p95 5.82-5.92 ms
against a 7.30 ms frame, total 3214 ms over 1200 calls - and that the frame is GPU-bound, so running the
CPU further ahead cannot make the card faster.

## Post-M4 regression audit: persistentMapping

**A Metal 4 correctness workaround had been deciding Metal 3's upload road.** `ab741fc` withdrew the
`persistentMapping` device feature for the whole device, and it was right to: with the flag advertised, Sodium's
`MojangStagingBuffer` picks `MappedStagingBuffer` and on the Metal 4 path not one chunk mesh ever arrived - a
no-pack frame was one flat clear for 4958 readbacks while Sodium's own upload step reported build results every
frame and the geometry arena was never allocated. Where the mapped road loses the data on that generation is
still not localised, so Metal 4 keeps the engine-staged road through `writeToBuffer`.

**What was wrong was the shape, not the withdrawal.** `DeviceFeatures` is built once, by `buildDeviceInfo`, and
both generations read it: the flag is a fact about a generation - Metal 3 had advertised it since this backend
existed and its frames were never the ones losing meshes - and a device-level answer made one generation's
workaround change the other generation's staging strategy. That is the cross-generation leak this audit's first
phase exists to close. The value is now derived from what executes:
`persistentMappingFor(this.services.executing())` answers true where the Metal 3 path encodes the frame and false
where Metal 4 does, `tools/ci-contracts.py` pins both halves of that rule and refuses the old literal by name,
and three mutations of the rule are caught.

**The A/B, on one generation, one session, one scene** (`run/pm-ab`; no-pack, spectator, fullscreen at
1920x1200, `--at 548.5,80,-248.5 --yaw 45 --pitch -25`, 25 s settle, 600-frame windows, `-Dmetallum.execution=metal3`
on every arm, the only variable being `-Dmetallum.persistentMapping=`):

```
                window mean    wallP50   P95     P99     max     M3 GPU/frame
mapped1          1.905 ms      1.83      2.64    2.94    5.96      1.374 ms
staged1          1.922         1.85      2.65    2.79    2.96      1.438
mapped2          1.917         1.79      2.63    2.81    2.88      1.479
staged2          2.011         1.93      2.61    2.75    2.89      1.516
```

**Decision: KEPT - Metal 3 advertises `persistentMapping=true`, as it did before the workaround.** The sign is
the same in both adjacent pairs (mapped 0.9 per cent faster, then 4.7 per cent faster) and the road is never
worse, but the honest reading of the magnitude is *not worse* rather than *faster*: the session drifted
monotonically - the per-frame GPU interval rises 1.374, 1.438, 1.479, 1.516 across the four arms in the order
they ran - and a drift of that size is the same order as the difference being measured, which is why the
comparison is read pair by pair and not across the whole session. Repeating the arms in the opposite order on a
quiet machine is what would price the road; nothing here is large enough to need it before the road is restored,
because the withdrawal was never a Metal 3 result.

**Correctness holds, and it is the picture rather than the counter that says so.** Both roads drew the same
scene: the mapped arm's capture and the staged arm's capture carry the same terrain, trees, water and cloud
edges, and the whole-frame comparison between two arms of the *same* road reads 0.09 mean / worst 65 - as large
as the reading between the two roads (0.17 mean / worst 65), which is cloud animation and antialiasing rather
than content. Sodium's own upload counter prints on both: `call 3, 3 frames seen, 3 of those calls carried
results, 29 results in total` on the mapped arm against `call 3 ... 4 results in total` on the staged one. The
counter alone is exactly the instrument that failed to notice the Metal 4 loss, so it is quoted as corroboration
and the captures are the evidence.
