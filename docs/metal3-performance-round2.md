# Metal 3, round two: the native-call census

The long-term plan's Track A starts here. Metal 4 is frozen as an experimental backend (section 1 of
`docs/long-term-performance-plan.md`), Metal 3 is the production reference, and the first question is the one
every later candidate depends on: **what does a Metal 3 frame actually ask Metal for, and how much of it is
work the encoder already knows the answer to?**

## Starting SHAs

```
Metallum: de143fa  (perf/optimisation)
Vitrail:  94219c13 (perf/optimisation)
```

## Benchmark

```
machine:       Apple M5 Pro, 15 CPUs, macOS 27.0 (build 26A428)
display:       desktop mode 1800x1169@120 (3600x2338 pixels); a measurement arm runs fullscreen at 1920x1200
scenes:        no-pack, MakeUp-UltraFast-9.5e, ComplementaryReimagined r5.9.1, Photon v1.3b
path:          executingGeneration=metal3
warmup:        25 s settle after the world (or the pack's first full frame)
window:        600 frames
camera/world:  run/worlds/PerfWorld, dimension minecraft:overworld, the save's own camera unless stated
harness:       tools/run-vitrail-performance.sh --fullscreen, the census armed with
               -Dmetallum.m3CallCensus=true
```

Two facts about the instrument are worth stating before any number, because both cost a session to learn and
both are recorded in `docs/performance-testing.md`: a fullscreen launch moves the display's mode (this harness
now records the mode per session, checks it after every arm and puts it back), and a *non-exclusive* fullscreen
client lives in its own Space, so a photograph of the display is of whatever Space is current. The census below
does not depend on the picture column at all - it is a count of calls - which is why it can be taken on the
fullscreen configuration the frame-time baselines use.

## The instrument: a shadow, not a counter

`MetalFrameProbe` now carries a per-encoder **binding shadow** and one entry point per kind of call a render
encoder takes, each taking the value the call carries:

```
frame-probe m3native calls={} native={} repeated={}
        pipeline={} pipelineSame={} depthStencil={} depthStencilSame={}
        cull={} cullSame={} fill={} fillSame={} winding={} windingSame={}
        depthBias={} depthBiasSame={} viewport={} viewportSame={} scissor={} scissorSame={}
        vertexBuffer={} fragmentBuffer={} bufferSame={}
        vertexTexture={} fragmentTexture={} textureSame={}
        vertexSampler={} fragmentSampler={} samplerSame={}
        argBufferSet={} argBufferSkipped={} draws={} drawsIndexed={} drawsIndirect={}
        fencesUpdated={} fencesWaited={}
```

- `calls` is what the frame asked for, in **bind operations**; `native` is how many **native setter calls** that
  became, counting one per stage, because a bind that reaches both vertex and fragment is two downcalls; and
  `repeated` is how many of those native calls carried `Same` value the slot already held - the share of this
  backend's call volume that could be removed without changing a pixel.
- The shadow lives in the probe and **changes nothing**: the encoder still sends every call, so a session with
  the census on is the same frame with one more number. A2 is the commit that would spend it.
- It belongs to the native encoder: `renderEncoderRecreated` clears it, `renderEncoderReused` keeps it - and that
  distinction is most of what the number means, because a logical pass that joins an open encoder inherits every
  slot it does not rebind.
- It is off unless `-Dmetallum.m3CallCensus` is set, and the aggregates the window line has always printed
  (`pipeline=`, `texture=`, `sampler=`, `buffer=`) are incremented by the same entry points, so a session with
  the census on and one with it off report the same frame.

## What the census found

Four scenes, one Metal 3 arm each, 600-frame windows (`run/a1cpu-nopack`, `run/a1cpu-makeup`,
`run/a1-complementary`, `run/a1-photon`), every arm validated by the harness against its own scene and by the
frontmost-application record at the capture:

```
scene            ms/frame   bind operations   native bind calls   redundant        share   indirect draw commands
no-pack             1.67            226.0              225.6            56.2        24.9 %              2425
MakeUp              6.74            545.0              510.6            71.9        14.1 %              3759
Complementary       8.30            625.7              588.8            59.5        10.1 %              3347
Photon             11.80            830.7              780.5            65.1         8.3 %              3350
```

and the same census split by kind, per frame, with each kind's redundant share:

```
                       no-pack                      MakeUp                    Complementary                  Photon
pipeline          9.6   ( 10 % same)        26.4   (  0 % same)        29.9   (  0 % same)       43.7   (  0 % same)
depth stencil     9.0   ( 56 %)            14.0   ( 46 %)            13.0   ( 42 %)           14.5   ( 45 %)
cull / fill       9.6   ( 67 %)            26.4   ( 31 %)            29.9   ( 25 %)           43.7   ( 21 %)
depth bias        9.0   ( 67 %)            14.0   ( 46 %)            13.0   ( 42 %)           14.5   ( 45 %)
viewport          4.2   ( 24 %)            21.3   (  5 %)            25.5   (  4 %)           37.4   (  3 %)
scissor           9.2   ( 65 %)            19.3   (  5 %)            22.5   (  0 %)           34.9   (  1 %)
buffers         129.1   (  5 %)           217.9   (  3 %)           217.4   (  3 %)          293.3   (  2 %)
textures         15.4   ( 33 %)            59.4   ( 19 %)            88.8   (  8 %)          107.1   (  5 %)
samplers         11.4   ( 53 %)            59.4   ( 26 %)            88.8   ( 14 %)          104.1   ( 11 %)
```

**Two of them were priced, because a count cannot say whether a road is a cost or a curiosity.** The indirect
draw loop is timed once per loop (one clock read a call would be measuring the instrument):

```
no-pack   2425 commands a frame in  66 loops  ->  68.3 us a frame = 4.09 % of the window, 28.2 ns a command
MakeUp    3759 commands a frame in 106 loops  -> 146.7 us a frame = 2.18 % of the window, 39.0 ns a command
```

The instrument is inside the span being measured - the census's own two counter increments per command - so the
per-command figure is an upper bound on the downcall rather than a pure one, and the arithmetic at 28-39 ns a
call is consistent with a thin FFM downcall and nothing more.

## What this says, in the plan's own terms

1. **The native-call volume is the *draws*, not the binds.** Every scene issues 2425-3759 indirect draws a frame
   against 226-831 binds, and those indirect calls are the terrain road: one call per visible chunk section. They
   are all *necessary* calls - nothing about them is redundant - so the lever is not "skip calls" but "fewer
   calls for the same work", and they are priced at **2.2-4.1 % of the frame's wall time** in CPU alone.
2. **Redundant binding elimination, the plan's A2, is measured and it is small.** The shares are real and in some
   kinds high - the cull, fill, winding and depth-bias calls are 21-67 % repeats because the pipeline road sets
   them every time the pipeline changes and they almost never change with it, and the scissor is 65 % on no-pack -
   but the absolute figures are 56-72 redundant calls a frame, which at the measured per-call cost is **0.1-0.3 %
   of a frame**. By the plan's own thresholds (section 4: under 1 % is noise) that is
   **MEASURED-BUT-NOT-WORTH-IT** as a performance change, and it is written down as that rather than left as an
   attractive-looking share.
3. **The Metal 3 CPU call overhead is now a number**: binds 226-831 calls and the indirect road 2425-3759 calls a
   frame, priced at 68-147 us for the indirect road and, at the same per-call cost, 7-25 us for the whole binding
   surface. That is **1.5-4 % of the frame's wall time in native calls**, and it is dominated by one road.
4. **The pipeline state road is already minimal**: the five state calls accompany a pipeline change and are not
   re-sent per draw, which is why their per-frame counts equal the pipeline count and why their redundancy is the
   pipeline change's, not the frame's.

## Decision

**KEPT: the census instrument.** It changes nothing that is sent, it is off unless asked for, and it turns the
plan's first question into a table. Its one addition to a measured frame is the timing counter on the indirect
loop, which is inside the span it reports and is said so above.

**REJECTED as a candidate: redundant bind elimination (A2/A3).** 56-72 calls a frame at 28-39 ns a call is
0.1-0.3 % of a frame - below the noise floor this project uses - and the code that would remove it (a shadow in
the hot path plus invalidation on every encoder change) is exactly the kind of complexity section 5's stop rule
exists to refuse. The census keeps the shadow, where it costs nothing and where a later scene that binds
differently can be read.

**NEXT CANDIDATE, not yet attempted: the indirect terrain draw road.** 2425-3759 downcalls a frame for 2.2-4.1 %
of the wall is the largest single native-call cost this census found, and the mechanism is clean (one call per
visible section). What it needs before any code: whether this device and Metal 3 road can replay a batch of
indexed-indirect commands at all - the backend's `multiDraw`/`multiDrawIndexed` are explicit refusals today - and
a picture-parity fixture that proves a batched road draws the same sections in the same order. Neither is
measured yet.

## Residual and what is NOT MEASURED

- **Vitrail's own per-frame CPU** (the plan's B1) and the **Vitrail to Metallum bridge census** (D1) are not
  measured. This census covers the *native* half only: the engine-side downcalls. A frame that spends 68-147 us
  in the terrain draw road may well spend more than that in the Java above it, and nothing here says.
- **Only the indirect road is priced.** The bind kinds are counted, and their cost is inferred from the draw
  road's per-call figure, which is an inference and is labelled one.
- **The per-frame counts move between sessions of one scene** (MakeUp read 636 bind operations a frame in one
  session and 545 in another, with the pack's first full frame and the tick mix as the variable), so the *shares*
  above are the robust reading and the absolute per-frame counts are one session's.
- **The four scenes are one camera and one world.** Section 3 of the plan allows the corpus to grow; nothing here
  is claimed about a scene that draws differently (a GUI-bound scene, a shadow-heavy scene, a 4K target).

## Next

1. **B1 - the Vitrail CPU census**: the same question asked of the Java half, since the census above prices only
   the downcalls. The plan's first-phase stop rule (CPU headroom under 0.3 ms a frame) cannot be answered without
   it.
2. **D1 - the bridge census**: calls per frame across `capabilities()`, the compute/depth/mipmap/scale bridges and
   resource allocation, with reflection and method-handle activity counted, because D2's design depends on which
   of them happen per frame rather than per pass.
3. **The terrain draw road**: a device probe for a batched indexed-indirect road, and a fixture that proves
   picture parity, before any implementation is proposed.
