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

## Candidate table

| Candidate | Cost observed? | Candidate implemented? | Result | Decision |
| --- | --- | --- | --- | --- |
| Argument-buffer allocation | yes: 2 native buffers a frame, 0.192 MiB a frame | no | measured; too small to justify an arena | **REJECTED** |
| Render encoder churn | yes: 20928 of 66318 attempts, 31.6 % | no | every recreation is a colour-attachment change | **REJECTED** |
| Argument encoder rebinding | yes: 14400 set calls against 1200 real changes | not yet | | pending |
| Per-pass allocations | not yet | no | | pending |
| Render-pass descriptor | not yet | no | | pending |
| Texel-buffer views | not yet | no | | pending |
| Fence synchronisation | not yet | no | | pending |
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

## Phase 3 - `MTLArgumentEncoder.setArgumentBuffer` rebinding

The census above is this phase's reading: **14400 calls, 1200 of which retarget the encoder.** That is the
shape the plan says to act on (its worked example is 20000 calls against 2000 changes), and the candidate is
taken in the next commit.
