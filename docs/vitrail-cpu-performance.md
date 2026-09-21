# Vitrail and Metallum CPU: the frame's own cost, and what can measure it

Track B of the long-term plan asks what the frame costs the CPU and what it allocates, and the plan's first
phase is allowed to *stop* the CPU work if the answer is that the CPU is not the bottleneck. This is that
answer, and the two instruments it took to get one: a profiler that crashed the client, and two readings that
cannot.

## Starting SHAs

```
Metallum: eef4afd + this round's census fields
Vitrail:  94219c13
```

## Instrument one: a profiler, and it took the client down

The plan's first choice is JFR and its rule is explicit: if a profiler crashes the JVM or changes the frame,
it is not used for a verdict. Measured, twice, in one four-arm session (`run/a2-jfr`, arms `control`, `jfr`,
`control2`, `jfr2`):

```
-XX:StartFlightRecording=filename=...,duration=150s,settings=profile
  arm jfr   the client started, loaded the world, and died with SIGABRT - Gradle reports
            "Process ... finished with non-zero exit value 134"
  arm jfr2  the same
  both recordings are zero bytes
  both arms were photographed at 3600x2338 (the desktop's own mode) because the client never went fullscreen
  and never reached a probe window
```

The two control arms in the same session ran normally at 1920x1200 with a full 300-frame window each. So this
is JFR in this JVM (Temurin 25.0.4.1+1) on this macOS, and not the scene: **JFR is not an instrument this
project can use for a performance verdict.** The plan's section 48 says what to do about that and this file is
the doing of it: an explicit census replaces it.

## Instrument two: sampling the render thread from outside, and how long a dump takes

The second attempt was to sample the render thread's Java stacks from a shell while the world drew -
`jcmd <pid> Thread.print` in a loop, which is a profiler with no agent and no recording. On a quiet Gradle
daemon one dump takes **183 ms**; on the running client it took **5.6 s** (`run/b1-nopack/stacks.txt`: five
dumps in twenty-eight seconds). The client's render thread spends its frame in native downcalls and the
attach's safepoint has to wait for it, so the sampling rate collapses to a handful of samples - far too few to
attribute a 1.7 ms frame. It is recorded as **REJECTED** rather than retried with a longer window: the same
safepoint is what any in-process sampler would need to walk another thread's stack.

## What can measure it: two readings a window, from the JVM's own thread bean

`MetalFrameProbe` now takes two readings when a window opens and two when it closes, and prints them on the
window line it already writes:

```
frame-probe 600/600 windowFrames=600 windowMs=1006.54 ... windowTicks=20 framesPerTick=30.00
                    frameCpuMs=136.17 allocKiB=42765.0
```

- `frameCpuMs` is the render thread's **own CPU time** over the window (`ThreadMXBean.getCurrentThreadCpuTime`),
  not the window's wall time. The first version of this reading used `System.nanoTime()` and read 1000.32 ms for
  a 1001.74 ms window - a busy thread by construction, and a mistake worth recording because the difference
  between the two numbers is the whole reading: a render thread waiting for its drawable is not working.
- `allocKiB` is that thread's allocated bytes over the window (`com.sun.management.ThreadMXBean`'s
  `getThreadAllocatedBytes`), which is the only way to ask a HotSpot JVM what one thread allocated without a
  profiler. A JVM that does not answer prints 0 rather than making a claim.

Both are two calls a window, they change nothing about the frame, and they are on by default while the probe is
armed.

## Baseline

no-pack and MakeUp-UltraFast-9.5e, one Metal 3 arm each, 600-frame windows, fullscreen at 1920x1200, camera and
world as in `docs/metal3-performance-round2.md` (`run/b1-nopack`, `run/b1-makeup`):

```
scene      ms a frame   render thread CPU   CPU share of the frame   allocated   allocated a frame   GPU ms a frame
no-pack          1.68             136.17 ms                  13.5 %   42765 KiB            71.3 KiB             1.37
MakeUp           6.74             703.31 ms                  17.4 %  109724 KiB           182.9 KiB             6.75
```

**The frame is not CPU-bound.** The render thread is busy 13.5 % of the wall on no-pack and 17.4 % on MakeUp,
and the GPU's own time is the wall on both (1.37 of 1.68 ms, 6.75 of 6.74 ms). In absolute terms the frame
costs the CPU **0.23 ms on no-pack and 1.17 ms on MakeUp** - and the plan's first-phase stop rule names
0.3 ms a frame as the point below which the CPU track stops being the place to work.

**What is *not* small is the allocation.** 71.3 KiB a frame on no-pack and 182.9 KiB a frame on MakeUp: at the
measured frame rates that is about **42 MB/s and 27 MB/s** of Java allocation on the render thread alone. At
182.9 KiB a frame a young collection every few thousand frames is expected, and the plan's B6 (object churn)
now has the baseline it was missing - but this file does not claim which objects they are, because that needs a
per-road census and not a profiler.

## Decision

**KEPT: `frameCpuMs` and `allocKiB`**, two readings a window on the line the harness already parses.

**REJECTED: JFR, and external stack sampling, as instruments for a verdict.** Two SIGABRTs and two zero-byte
recordings for the first; 5.6 s a dump on the client for the second.

**APPLIED, the plan's phase-1 stop rule.** With 0.23 ms of CPU a frame on the lightest scene and 1.17 ms on the
heaviest pack, and the GPU's time equal to the wall on both, the CPU is not where the frame goes, and the plan
says to reduce the CPU line's weight and move to the GPU and MetalFX tracks. The native-call census of round one
had already closed the binding micro-optimisation for the same reason (56-72 redundant calls a frame,
0.1-0.3 % of a frame). What survives on this track is the **allocation rate**, which is large and cheap to
reason about, and the **road-level attribution** of it.

## Residual and what is NOT MEASURED

- **Which roads allocate the 183 KiB a frame is not measured.** This file has the total and the frame's CPU
  share, not the attribution: that needs per-road censuses in the shape Vitrail already uses for mipmaps
  (`MipmapCensus`), the shadow walk (`ShadowCensus`), compute dispatch maps (`ComputeDispatchCensus`) and target
  copies (`TargetCopyCensus`). The plan's B2 (resource-name resolution), B3 (sampler binding), B4 (uniform
  publication) and B5 (compute bindings) are exactly that work, and B5 already has its census.
- **Two scenes only.** Complementary and Photon are not measured on this instrument yet; their pack frame is
  heavier (8.3 ms and 11.8 ms a frame in the native census) and their CPU share may differ.
- **The main thread is not counted.** `frameCpuMs` is the render thread's CPU, which is what the frame path
  costs; the client's own tick and the chunk builders are a different question and are not in this number.
- **The allocation reading is the thread's, not the frame's.** A window that covers 600 frames divides evenly,
  but anything the loader, the pack or a background worker allocates on the render thread is inside the number
  and cannot be told apart from the frame's own churn.

## Next

1. **B6 with the baseline in hand**: per-road allocation censuses (resource lookups, uniform publication,
   sampler binding, pass construction) to attribute the 183 KiB a frame, since that is the one CPU-side number
   this round found to be large.
2. **Track E (MetalFX scale ladder)**, which the stop rule promotes: the frame is GPU/pacing-bound on every
   scene measured, and the render scale is the lever that moves real GPU work.
