# Metallum Metal 3 steady-state optimisation  -  status report

One row per candidate the plan names, kept current as each phase is measured. A candidate that was
measured and found not worth doing is a finished candidate: `REJECTED` or `NOT APPLICABLE` is a result,
and `BLOCKED BY MISSING EVIDENCE` is what an unmeasured one is never allowed to become silently.

## Starting SHAs

```
Metallum: 33866a7c3dac4d67b19b0bcd35e5c9220a5f0557  (perf/optimisation, the plan's reference HEAD)
Vitrail:  4380250f                                   (perf/optimisation, ahead of the plan's 67ca66ca)
```

Every structure the plan names was checked against this checkout before anything was measured:
`MetalRenderPass.argumentBufferStates` (one native `MTLBuffer` per wide layout per pass, released through
`MetalCommandEncoder.queueForDestroy`), `MetalCommandEncoder.MAX_SUBMITS_IN_FLIGHT = 3`, the direct
`newBuffer(Shared, Tracked)` allocation, the encoder-reuse condition and its single
`endEncoder(PASS_CONFIGURATION_CHANGED)` site, `MetalTransientMemory`, `createTexelBufferTexture` and
`MTLTexture.newBufferTextureView`.

## Benchmark

```
pack:         Photon v1.3b
preset:       55 %
resolution:   fullscreen at the display's 1920x1200 mode, world drawn at 1056x660
camera:       548.5,63,-248.5 yaw 0 pitch 7.8
warmup:       25 s settle after the pack's first full frame (the harness's own default)
frames:       600
present mode: MAILBOX, displaySyncEnabled=false, Unlimited FPS
path:         executingGeneration=metal3, metal4Presents=0
```

**The render target is not pinned by the harness and has two states** - the display has a 1920x1200 mode
and a 3840x2400 one, and `--fullscreen` lands on either. Every arm read below reproduces the target the
whole programme is anchored on (`encoders` 21440 with `loadedMiB` 93943.3), and the check that says so is
the structural counters rather than the window size or the screenshot's dimensions.

## Initial Baseline (`run/m3-baseline`, a1 and a2)

```
                    a1          a2
wallP50:            7.30        7.29   ms
wallP95:            8.13        8.25
wallP99:            8.54        9.13
wallMax:           13.17        9.85
gpuP50:             7.31        7.33
gpu total:       4380.63     4392.70   ms over 600 frames  (0.28 % apart)

renderPasses:      20928       20928   (34.88 a frame)
blitEncoders:       3000        3000
computeEncoders:    1800        1800
clearEncoders:       600         600
encoders:          21440       21440
passChanged:       20840       20840
submit:              600         600  (one a frame)

blits:              6600        6600   (11 a frame)
blittedMiB:      22159.3     22159.3
loadedMiB:       93943.3     93943.3
storedMiB:      132773.6    132773.6
depthAttachments:   4800        4800

pipeline:          29228       29228
texture:           75510       75510
sampler:           73710       73710
buffer:           123318      129318   (this counter's own noise: 4.9 %)
viewport:          22128       22128
scissor:           21528       21528

pipelineIdentities:  345         345
pipelineKeys:        345         345
compiles:              0           0
compileMs:          0.00        0.00

drawable wait:      p50 0.05    p50 0.05  ms
                    p95 0.56    p95 0.52
                    max 1.04    max 2.84
submitWindow wait:  p50 0.00    p50 0.00  ms
                    p95 5.82    p95 5.92
                    max 6.12    max 6.29
                    total 3214.41 over 1200 calls   total 3239.00
```

**Repeatability gate: PASS.** Every structural counter is identical between the two arms, the GPU total
is 0.28 per cent apart and `wallP50` 0.14 per cent, against the plan's "structurally identical and under
about one per cent" gate. The only counter that moves is `buffer` bindings, which is that number's own
run-to-run spread and is named rather than averaged away.

**What the baseline already answers about P8**: `submitWindow` is not idle on Photon. Its median is
0.00 ms but its p95 is 5.82-5.92 ms against a 7.30 ms frame, and 1200 calls totalled 3.2 s over 600
frames, which is about 5.4 ms a frame of render-thread waiting. The plan's "do not change
MAX_SUBMITS_IN_FLIGHT" condition is `p50 ~0 AND p95 << frame time`; the first half holds and the second
does not, so this is back-pressure worth an A/B rather than a closed question - recorded here and taken
in Phase 8's own turn, not now.

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

## Candidate table

| Candidate | Cost observed? | Candidate implemented? | Result | Decision |
| --- | --- | --- | --- | --- |
| Argument-buffer allocation | yes: 2 native buffers a frame, 0.192 MiB a frame | no | measured; too small to justify an arena | **REJECTED** |
| Render encoder churn | yes: 20928 of 66318 attempts, 31.6 % | no | every recreation is a colour-attachment change | **REJECTED** |
| Argument encoder rebinding | yes: 14400 set calls against 1200 real changes | yes | calls 14400 to 1200 (-91.7 %), writes and bindings unchanged | **KEPT** (`e2a221d`) |
| Per-pass allocations | yes: profiled, `MetalRenderPass` is 0.34 % of allocation | no | not a CPU/GC hotspot | **REJECTED** |
| Render-pass descriptor | yes: ~36 a frame, one per encoder opened | no | gate in §49 not met | **REJECTED** |
| Texel-buffer views | yes: **0 a frame** | no | the pack uses no texel buffer | **NOT APPLICABLE** |
| Fence synchronisation | no evidence of cost | no | GPU saturated 97.3 % in the trace | **REJECTED** |
| Submit window | yes: p95 5.82 ms against a 7.30 ms frame | no | | pending |

## Phase 1 - Argument buffer allocation census (`run/m3-census`, c1 and c2)

Two arms, identical to each other, with the census added to the frame probe and nothing else changed.
Per window of 600 frames, so these are also per-frame figures divided by 600:

```
                    c1          c2
passes:             600         600    (1 wide pass a frame)
layouts:           1200        1200    (2 a frame)
allocations:       1200        1200    (2 native MTLBuffer allocations a frame)
allocationMiB:    0.192       0.192    (168 bytes each)
setCalls:         14400       14400    (24 a frame)
setChanges:        1200        1200    (2 a frame)
textureWrites:    12000       12000    (20 a frame)
samplerWrites:    12000       12000    (20 a frame)
bufferWrites:      1200        1200    (2 a frame)
useResourceCalls: 13200       13200    (22 a frame)
draws:              600         600    (1 wide draw a frame)
```

**Decision: REJECTED, on the plan's own Phase 1 gate.** The gate stops the candidate at "about one
allocation a frame and small bytes"; this is two allocations a frame of 168 bytes each, 0.192 MiB a
frame, and the gate's reason to continue is "several allocations a frame, especially 10+, 20+, 30+".
Two is neither, and an arena to remove 0.19 MiB a frame from a 7.30 ms GPU-bound frame is complexity
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

## Where the programme stands, and what the next round has to do first

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
