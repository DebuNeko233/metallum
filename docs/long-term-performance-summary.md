# The long-term performance plan: what it proved, rejected, and left open

This is the result of the plan whose policy of record is `docs/long-term-performance-plan.md`: one page for
whoever comes next, with each track's decision and the number that decided it. The track documents own the
evidence; this one owns the summary, and every figure in it is quoted from one of them.

## The corpus and the protocol

One world (`PerfWorld`, frozen: clock 4000, weather clear, entities stripped, player in spectator), one window
(1920x1200, exclusive fullscreen, `maxFps` 260, vsync off), 600-frame windows after a 25 s settle, Metal 3 (the
production path), and four scenes: **no-pack**, **MakeUp-UltraFast-9.5e**, **ComplementaryReimagined r5.9.1**,
**Photon v1.3b**. A session carries its own reference arms, the wall is read as a minimum over repeats, and every
arm states the command generation it ran in. The harness refuses a window that is on the wrong target, in the
wrong generation, on another backend, drawn from another pack, drifted, short, unsettled, or whose client crashed
(`docs/performance-testing.md`).

**The machine limits what a frame time can say.** Identical structure and configuration have read up to 47 per
cent apart between arms; the sessions that settled the last two questions reproduced to 0.1-0.3 per cent. Every
wall figure below is a minimum over repeats, and an effect under about five per cent is only claimed where the
session's own repeats say it can be read. The corpus's tail is clean: across 85 recorded arms the worst frame is
1.06x the window's own P99 (median), the two outliers being this programme's own instrument arms.

## Track A - Metal 3 performance

**A1, the native-call census** (`docs/metal3-performance-round2.md`). The hot path is priced, not counted: 226 to
831 bind operations a frame across the corpus, 8-25 per cent of them redundant, and the redundant ones are worth
**0.1-0.3 per cent of a frame** at 28-39 ns a call.

```
scene            ms/frame   native bind calls   redundant   share   indirect draw commands
no-pack             1.67            225.6          56.2     24.9 %          2425
MakeUp              6.74            510.6          71.9     14.1 %          3759
Complementary       8.30            588.8          59.5     10.1 %          3347
Photon             11.80            780.5          65.1      8.3 %          3350
```

**A2/A3 REJECTED** as measured - redundant bind elimination is 0.1-0.3 per cent, inside the noise floor, and the
mechanism is real but the volume is not. **A4/A5 NOT MEASURED and closed with the CPU round**: the frame is
GPU-bound (the accelerator reads 100 per cent in every arm's own trace) and the native surface A1 priced is
1.5-4 per cent of a frame, so an arena or a wider submit window has no measured hot path behind it (rule F).
**The indirect terrain draw road is the one named next candidate**: 2425-3759 downcalls a frame for 2.2-4.1 per
cent of the wall.

## Track B - Vitrail CPU and allocation

**B1** (`docs/vitrail-cpu-performance.md`). The frame is **13-17 per cent CPU** and allocates **71-183 KiB a
frame** (27-42 MB/s) on the render thread. **JFR is rejected by measurement**: two launches died with SIGABRT and
zero-byte recordings, so the readings are explicit censuses. One scene read 6.8x the allocation with every counter
identical - a window's CPU and allocation are readings of that window's own content, not of the switch.

**B2-B6 closed with the CPU round** by the plan's own exit condition (two candidates under one per cent), and the
allocation rate is named rather than chased: re-opening needs a profiler that shows it on the frame's path, which
JFR is not here.

## Track C - Vitrail's GPU work

**C1/C3** (`docs/vitrail-gpu-performance.md`). The frame's GPU work is the terrain's indirect draws and its
attachment traffic. At 55 per cent **exactly one pass a frame stays at the window's own size** - the interface's -
on **all three packs** (the window's own passes fall from 17, 20 and 27 a frame to **1**, while 1056x660 appears at
16, 19 and 26), the shadow map is sized by the pack's own shadow settings, and **without a pack there is no scaled
world at all**. C3's hypothesis of a heavy
world pass left at native resolution is **REJECTED on the whole corpus**.

**C2, the shadow stage.** The map's own passes decompose exactly: **300 opaque + 600 translucent** in a 600-frame
window at the shipped interval, 600 + 600 at nought, 200 + 600 at the selector's maximum. The shipped reuse of the
map is worth **9.8 per cent** on MakeUp (6.726 against 7.383 ms); the selector's own maximum is worth **5.7 per
cent** there and **3.0 per cent** on Complementary (8.285 against 8.035, eight arms each). The movers cost one
full-size pass and 129 MiB of attachment traffic a frame for **+0.13 per cent** of frame time, and the voxel
family is NOT MEASURED.

**C4/C5/C6.** The frame-end copybacks are **6, 4 and 10 targets a frame** on the three packs, of which **2, 0 and
3 are read by nothing**; the existing elision switch removes exactly those and no others (5400 blits to 4200 on
MakeUp for **17.6 MiB a frame**, 6600 to 4800 on Photon for 2.6), and is **REJECTED as a default** on 1.1 per cent
where a session can resolve it. **Feedback snapshots are ZERO on every corpus pack** with the counter in place.
Every mip chain has the reader that asked for it, and the census now names the target: MakeUp reduces colortex0
alt and colortex1, Complementary four, Photon two.

**C7.** The attachment traffic falls **17.1, 32.9 and 38.1 per cent** (66, 106 and 158 MiB a frame) with the
elision switch and the frame moves **-1.1 and +0.3 per cent** in the two clean sessions, so the plan's own stop
rule fires: **STOP**, switch off by default.

## Track D - the Vitrail-to-Metallum seam

**D1** (`docs/bridge-overhead.md`): the whole reflective seam is **0.066-0.70 per cent of the wall**, and the
resolution it depends on is already a startup cost - **2 lookups since launch** across seven bridges.
**MEASURED-BUT-NOT-WORTH-IT**, and with A2/A3 it closes the CPU micro-optimisation round. D2/D3 (pre-resolution)
are closed by the same census: there is nothing per-frame left to resolve.

## Track E - MetalFX

**E1** is a hard contract: 100 per cent means the native world target, no availability call, no scaler, no
upscale blit, pinned in Vitrail's tests and `ci-metalfx.py`. **E2's ladder** (`docs/metalfx-performance.md`): the
two GPU-heavy packs gain **1.3-1.8x** by 55-67 per cent, MakeUp **1.19x even at 55**, with the driver's own GPU
time falling in step; the pack-selection writer that spoiled 2 of 21 cells was a **player-visible defect** and is
fixed. E4 (dynamic resolution) is not started - see below.

## Track F - startup, shader and pipeline caches

**F1/F2/F3** (`docs/startup-and-cache.md`). A **warm launch compiles nothing**: 574 module-cache hits and no
misses on MakeUp (581 on Complementary), 45 translation hits and no misses, and what is left of the shader path is
18-40 ms of module rebuilding, 166-416 ms of replaying cached translations and 262-312 ms of pipeline warm-up on
MakeUp against 1.1-1.6 s on Complementary. A **cold** launch builds **187 units in 1747 ms** plus 563 ms of
translating, and the load is **8 s warm against 11-12 s cold** on MakeUp (8-11 against 15 on Complementary). Every distinct input
is built once and read **3.05 times** a load, and **105 of the two packs' inputs are the same input** - 55 per
cent of each pack's compiled vocabulary is the game's own.

**F4** measured what a launch actually asks the Metal compiler for, and **rejected the pipeline archive**: 168
function compiles and 706 pipeline states - **874 calls a launch**, 10.28 ms and 26.32 ms in one session and
21.83 ms for the function half in another, with the **worst single compile 0.29 ms in the first and 10.87 in the
second, that one landing on a warm-up worker** (the render thread's own total did not move) - against a load of
8-15 s. The 0.26-1.6 s
the candidate was recorded with is the wall of the warm-up's parallel job, which contains the translation and
module building the module cache already covers, and which the load never awaits (`FamilyWarmup.awaitAll` runs
once, at client shutdown).

## Track G - measurement infrastructure

**G1**: `tools/vitrail-performance-report.py` writes a session's arms as JSON (repositories, machine, display
mode, target, pack, scale, wall and GPU distribution, CPU and allocation, native census, structural census, the
engine's one-a-second censuses, and the window's tail against its own P99), held by
`tools/ci-performance-report.py` against a fixture built from a real window's lines, with its own mutations proven
to fail it.

**G2**: the harness refuses every invalid window section 46 lists - wrong target, wrong generation, another
backend, a taken-over pack selection, scene and content drift, a short window, an unsettled window, and a client
that crashed or lost the device; the last three were added here and **seen to fire**.

**G3**: every arm's picture is the **client's own readback of its main render target**, asked for by a file inside
the settle so that the readback's stall lands outside the frames the probe counts (measured: 273 ms inside the
window against 9.49 after the fix), with the display capture kept beside it as the fallback and the pass line
saying which road was taken.

**G4** is policy: a profiler that crashes the JVM or changes the frame is not used for a verdict.

## Acceptance on the final head

Criterion 1 - Metal 3 has no visible regression - is the one criterion that is about what the programme's own
changes did, and it was checked rather than assumed: the four-scene corpus was re-run on the head carrying all of
them (the labelled mipmap census, the unarmed and function compile counters, the client-screenshot probe, the
mixins, the harness guards), against the C1 corpus that predates every one of them. One arm a scene, the same
protocol, 600-frame windows. The two collections are four and a half hours apart, and the one scene whose reading
moved across that gap was then re-measured with the baseline's own code in the acceptance's own machine state -
the paragraph below on no-pack, which is the correction this page would otherwise be missing.

```
scene            ms/f base   ms/f now    delta   loadedMiB/f base  now   storedMiB/f base  now
no-pack              1.678      1.793    +6.9%          18.3       18.4         53.4       53.5
MakeUp               6.734      6.723    -0.2%         385.8      385.8        461.4      461.4
Complementary        8.289      8.282    -0.1%         321.8      321.8        460.0      460.1
Photon              12.958     11.810    -8.9%         416.1      415.6        536.0      535.5
```

**MakeUp reproduces to the digit** - `loadedMiB`, `storedMiB`, `depthAttachments`, `blits`, `blittedMiB`,
`renderPasses` and `pipelineIdentities` are identical to the baseline session - and the other three agree on
every world pass count, every attachment counter and every copy counter to within a tenth of a per cent. The
frame times are -0.2 and -0.1 per cent on the two packs whose baselines are strongest.

**Photon's -8.9 is the baseline's own arm being the high one, and not an improvement.** Five arms of that scene,
in four other sessions, read 11.769 to 11.810 ms a frame; the acceptance arm is one of them, and the baseline's
12.958 is one of the two that stand apart.

**No-pack's +6.9 was the machine, and that was measured rather than argued.** Its arm read 1.793 ms a frame with a
95th percentile of 2.63 ms and a GPU 95th of 2.10, against the baseline's 1.678 with a 95th of 1.79 and a GPU 95th
of 1.44, and three arms of the head reproduced it to two decimal places - a step, not a scatter. So both
repositories' runtime was put back to the baseline's own commits (`8f05f7c`, `6afce954`), nothing else changed, and
the same scene then read **1.795 ms a frame with a 95th percentile of 2.64** and a GPU 95th of 2.11: the baseline's
own code, in the acceptance's own machine state, reads what the head reads. The six per cent is the environment the
two sessions were taken in, and the rule it produced is in `docs/performance-testing.md` - a baseline from another
session is re-measured before it is compared against, and no-pack, the one uncapped scene (558 frames a second
against a 120 Hz display), is where anything else on the GPU arrives first. The re-measurement is auditable from
the sessions themselves and not from this page: every arm now writes `source-revision.txt`, the checkout it ran and
whether the worktree was that checkout, for both repositories and for the tools that measure them.

`passSizes` is the one column that differs, and it differs by the same amount at every size at once (20 against
22, 99 against 100, 156 against 142): that is the **load-time mip cascade**, a one-off chain whose tail lands
inside or outside a 600-frame window depending on when the load's cascade runs relative to the marker. The world
passes - 1920x1200, 960x600, 480x300, 1056x660 - are identical in all four scenes.

And the picture column was taken by the client itself on every scene: `picture-source.txt` reads
**"client readback"** in all four arms, including no-pack, with a 3.5-5.3 MB PNG beside it.

## The success criteria, audited

```
1.  Metal 3 has no visible regression          MET - every contract passes on this head, the two pack scenes
                                               whose baselines are strongest reproduce their frame times and
                                               their counters to 0.2 per cent, and the scene that did not
                                               (no-pack, +6.9) was re-measured with the baseline's own code in
                                               the same machine state and reads the same as the head: the six
                                               per cent was the session, not the change
2.  Metal 3's CPU/native cost is audited       MET - A1's census, priced
3.  Vitrail's frame hot path is moved forward  MET AS MEASURED - there is nothing per-frame left worth moving:
                                               the seam is 0.066-0.70 %, redundant binds 0.1-0.3 %
4.  The bridge overhead is quantified          MET - D1
5.  A batch of low-risk CPU optimisations      NOT MET, and not by omission: every candidate measured under
    lands                                      one per cent (A2/A3 and D1), which is section 51's own exit
                                               condition. Landing one would be landing noise
6.  A MetalFX scale/performance curve          MET - E2
7.  A structural census of the GPU work        MET - C1/C2/C3/C4/C5/C6/C7
8.  shadow/copy/attachment/mipmap unguessed    MET - all six of phase 53's list measured end to end
9.  Startup/reload pipeline cache quantified   MET - F1/F2/F3/F4
10. Every rejection has a data reason          MET - A2/A3, the copyback elision, C7's traffic switch, the
                                               pipeline archive, C3's full-res hypothesis
11. Metal 4 stays compilable and runnable      MET - all four Metal 4 contracts pass on this head
```

## What is open

**One decision, and it is the owner's: the shadow map's default.** `ShadowAmortisation.DEFAULT_FRAMES` is 1 kept
frame and the selector already offers 2. Raising the default to the selector's maximum is worth **5.7 per cent on
MakeUp and 3.0 on Complementary** - two real packs, structure exact in the same arms, rollback one constant - and
it costs one more frame of age on the ground in the map (three frames instead of two, about 7 ms at 148 fps; what
moves is redrawn every frame, so it is ground that changed - a block placed or broken - that keeps its old shadow
that much longer). The value 1 is inherited from a judgement about a map kept *whole*, which drawing the movers
back in retired, and no eye has looked at the ground's lag since. It is a change to what every player gets without
asking, so it is not made here.

**E4, dynamic resolution, is not started.** The fixed ladder is stable and it is the only item of the plan that
remains, but it changes public semantics again (the world's resolution adjusting itself) and the plan classes it
as high-risk with its own stop rule for target reallocation and history invalidation. It needs the owner's
direction before a line of it is written.

**F3's in-session reload is measured, and it cannot be a window measurement.** The lifecycle probe drives F3+T's
own path from inside the client, and a reload costs **about a second, serves 147 module-cache units and compiles
nothing** - but vanilla pauses and saves the single-player client around a resource reload (`Reloading
ResourceManager: ...` then `Saving and pausing game...`, in the same second), so an arm that drives one is refused
by the pause guard, correctly, and the reload's cost is read off its own lines.

**Named and unmeasured, and staying that way until something asks for them:** the voxel-writing half of the
shadow stage (inside the same fragment program as the raster, no switch can take it out without changing what the
pack's shader does); the near-duplicate case of F2 (two inputs differing in one define); and **Solas**, the fifth
corpus pack, which has never been staged on this machine and is the owner's to supply.

## Where the evidence is

`docs/metal3-performance-round2.md` (A), `docs/vitrail-cpu-performance.md` (B), `docs/vitrail-gpu-performance.md`
(C), `docs/bridge-overhead.md` (D), `docs/metalfx-performance.md` (E), `docs/startup-and-cache.md` (F),
`docs/performance-testing.md` (the harness and the rules), `docs/metal3-performance-report.md` (the first round,
still the reference for its own conclusions) and `docs/metal4-full-frame-report.md` (Metal 4, frozen). Every
session is under `run/`, named for the phase that took it, with `probe.txt`, `latest.log`, `client.png` and
`picture-source.txt`.
