# Performance testing: the workflow, the traps, and how to read the numbers

This is the operator's guide to `tools/run-vitrail-performance.sh` and to the frame probe it arms.
It is written for the person who has to produce a number another person will act on: what to run,
what not to touch while it runs, and which column decides whether a change is real.

Every claim below was paid for by a run that went wrong first, and the ones that cost the most are
in [Traps](#traps) rather than in the happy path.

## What a measurement is

One run is: a dev client launched into one scene, on one backend, with one set of switches, drawing
600 frames while the probe counts what those frames did, and a screenshot of the frame at the end.

Two runs of the same scene under two sets of switches are a comparison, and
`tools/vitrail-performance-compare.py` prints them side by side.

A measurement is not a judgement of the picture. The client is left standing where the world put it,
so the screenshot is evidence that a plausible frame was drawn, not that it was a good one.

## The pieces

| Piece | What it is |
| --- | --- |
| `tools/run-vitrail-performance.sh` | stages the instance, writes the settings profile, launches the client, arms the probe, collects the artifacts, runs the comparison |
| the dev instance | `run/`, the Loom client's game directory: `options.txt`, `saves/`, `shaderpacks/`, `vitrail/pack.txt`, `config/metallum.properties` |
| the staged world | a world directory **outside** `run/` that is copied into `run/saves/` before every run |
| the staged pack | a `.zip` **outside** `run/shaderpacks/`, copied in with its `<zip>.txt` options file beside it |
| `tools/freeze-world.py` | rewrites the staged world's clock, weather and game rules, takes the entities out, puts the player in spectator |
| the frame probe | `MetalFrameProbe`, armed by `run/metallum/probe-frames` and bounded by `-Dmetallum.frameProbeBudget=N`; one line every N frames |
| `tools/vitrail-performance-compare.py` | the counters table, the per-run summary and the picture comparison |
| `tools/ci-vitrail-performance.py` | the contract that keeps the harness honest (it is named by `ci.yml`) |

## Workflow

### 0. Once: stage the inputs outside the instance

Both the world and the pack are *copied in* by the harness, under their own names. A source that is
already the destination is refused (see [Traps](#traps)), so keep them out of `run/`:

    .perfstage/PerfWorld/                 # the world to measure in
    .perfstage/photon_<version>.zip       # the pack
    .perfstage/photon_<version>.zip.txt   # its options, if it has any

### 1. One scene, no pack (the migration baseline)

    tools/run-vitrail-performance.sh \
      --no-pack --fullscreen \
      --world "$PWD/../.perfstage/PerfWorld" \
      --run plain \
      --out run/m4-nopack

`--no-pack` stages no pack and writes the pack selection disabled, so the frame is the game's own
renderer through this backend. This is the configuration a frame-path change is judged in first,
because nothing of a shader pack can explain what it measures.

### 2. One scene, one pack, one scale

    tools/run-vitrail-performance.sh \
      --pack "$PWD/../.perfstage/photon_<version>.zip" \
      --fullscreen --renderscale 55 \
      --world "$PWD/../.perfstage/PerfWorld" \
      --run plain \
      --out run/m4-pack

`--renderscale` is written into the pack selection, which is the setting MetalFX answers to: below
100 the frame draws smaller and the scaler brings it back at the window's size.

### 3. An A/B pair

`--run NAME[=-Dswitch ...]` may be repeated; the first run is the one the rest are compared against,
and the switches are per-run JVM arguments:

    tools/run-vitrail-performance.sh \
      --pack "$PWD/../.perfstage/photon_<version>.zip" --fullscreen --renderscale 55 \
      --world "$PWD/../.perfstage/PerfWorld" \
      --run plain \
      --run 'present=-Dmetallum.metal4Present=true' \
      --out run/m4-present

**Two runs of one configuration are part of every session**, not an optional extra: they are the only
thing that says how large a difference this scene can be trusted to show. Take them in the same
session, on the same machine state, and read them before reading the A/B.

**Reverse the order for a claim that matters.** Whichever arm runs first carries the machine's state
at that moment; a pair whose two arms differ by more than the floor and whose sign flips when the
order flips is machine state rather than the switch.

### 4. Read the artifacts

Every run writes `<out>/<name>/`:

| File | What it is for |
| --- | --- |
| `latest.log` | the run's own log; the probe lines and the backend line are here |
| `probe.txt` | only the `frame-probe` lines, grepped out |
| `frame.txt` | the arming line (the pack's first full frame, or the server's `Time elapsed:`) |
| `screen.png` | the frame the numbers describe |
| `gradle.log` | the launch, including a failure that stopped the client |
| `order.txt` | the run order, at the top of the output directory |

### Where a frame waits, when its rate is not what Unlimited asked for

Three waits are instrumented, all probe-gated, and none of them changes anything: the present mode the
session configured, the drawable it takes before a frame can be drawn, and the frame tail's wait on the
in-flight submission window. Read them in this order.

`Metal surface: presentMode=… immediatePresentMode=… displaySyncEnabled=…` is printed once, at the first
configure, and it is the first thing to read: `CAMetalLayer` sets `displaySyncEnabled` to the negation of
the `immediatePresentMode` it is handed, and `MetalSurface` hands it `presentMode()==MAILBOX`. So
`presentMode=FIFO displaySyncEnabled=true` is a session locked to the display's refresh, and no amount of
frame time will move it.

`frame-probe waits drawable calls=… p50=… p95=… max=… total=…ms; submitWindow calls=… p50=… p95=… max=…
total=…ms` is printed once, at the end of the armed window. It is two distributions and not one number
because they are two different repairs: a drawable wait near the frame's period is present pacing, and a
submit-window wait near it is the in-flight window. Explicit teardown and cache waits are deliberately not
counted - they happen once, on the close path, and would read as pacing.

Measured on the M5 Pro with an empty scene (no pack, and a pack scene whose window drew no terrain:
`renderPasses` ~1 950 against ~21 000 for a real Photon frame): drawable `p50` 1.47 ms, `p95` 2.62 ms,
`max` 10.03 ms over 600 frames; submit window `p50` 0.00 ms, `p95` 0.83 ms, `max` 1.67 ms over 1200 calls;
`wallP50` 2.28 ms against `gpuP50` 1.14 ms. Nothing there is near a display period, and the session is
MAILBOX with display sync off. **A trap this cost two arms to find:** the probe's `percentile` returns an
already-formatted `String`, so a `String.format("%.2f", …)` around it throws `IllegalFormatConversionException`
at runtime and the line silently never appears - which reads as "no wait". Percentiles are now empty-safe and
passed through as they come.

## Traps

### The backend is not what the settings file says

A session can come up on MoltenVK instead of Metallum's Metal device and measure the wrong engine
entirely. Two mechanisms, both measured:

1. Vitrail's `StartupGuard` answers a startup that ended badly by writing the graphics API back to
   Vulkan **in memory**, before the backend list is built. Metallum only puts its backend in front of
   that list while the vanilla preference is **Default**, so the next run is MoltenVK no matter what
   the harness wrote a second earlier.
2. A crash during startup leaves `startedCleanly` false, which is what the guard reads.

The harness now writes `startedCleanly:true` and `preferredGraphicsBackend:"default"` before every
run, checks `Using graphics backend Metal` after it, and exits 3 when a run came up elsewhere. Read
that exit code: a comparison whose runs did not all come up on Metal is a comparison of another
engine.

A hand run has neither guard, and the game escalates: two startups that ended badly in a row and it
writes the graphics API down to OpenGL, which is how a hand-run session came up on `4.1 Metal - 91.7`
with no Metal device and no probe lines at all. Both keys are worth resetting by hand before a run that
matters, or the run should go through the harness.

`libMoltenVK.dylib` being loaded is **not** evidence of the Vulkan chain: the game constructs
`VulkanBackend` while assembling its backend list, which loads the library. The log line, and F3's
`system` group, are the evidence - both read `DeviceInfo.backendName()` and `driverInfo`.

### The world and the pack must live outside the instance

The harness deletes `run/saves/<world>` before copying the world in, and `cp` refuses a file that is
already the destination. A source inside `run/` therefore either deletes the scene or ends the run at
the copy. Both are refused now, by prefix, with the reason; do not work around the refusal.

### The settings profile is written, not inherited

Every run writes `maxFps` 260, `enableVsync` false, the window mode it was asked for, vanilla clouds
off, and the graphics API. 260 is the slider's maximum, and the maximum means uncapped - measured at
563 frames a second under it, so a capped run and a slow one cannot be confused.

`renderClouds` is the one soft key: the game rewrites it for itself on the way out.

### The Metal HUD is on for a hand run and off for a measured one

`runClient` carries `MTL_HUD_ENABLED=1` so a hand run can watch frames a second, GPU time and the
device. A measured run passes `-PvitrailHud=0`, because the picture evidence is a screenshot and the
overlay's numbers and graph change every frame: measured, 3.39 per cent of pixels above eight levels
between two arms that drew one scene.

### Do not press F3 while a run is measuring

The screenshot is the picture evidence, and F3's text covers most of it. A pair measured with F3 open
in one arm read 59.94 per cent of pixels above eight levels and meant nothing.

### Do not edit sources while a comparison is running

Each run launches `./gradlew runClient`, which recompiles: an edit between the two arms makes them two
different builds, and the counters will say so in a way that looks like the switch.

### The fixture is what makes a comparison repeat

`tools/freeze-world.py` writes the clock to `data/minecraft/world_clocks.dat`'s
`minecraft:overworld.total_ticks`, the weather to `weather.dat` and the rules to `game_rules.dat`
under namespaced names a command never says (`minecraft:advance_time` is `doDaylightCycle`). Writing
them into `level.dat` freezes nothing: the game does not read it, and this cost a whole session of
claims about the picture before it was found.

`--still-life` removes the mobs from the copy and `--spectator` takes the player out of the frame;
without them an entity that happens to be in one run's view moves the counters by a tenth. `--at`,
`--yaw` and `--pitch` pin the camera, because a comparison that judges pixels has to choose its frame.

### Pinning the camera does not fix it, and the pack floor is larger than three and a half per cent

The obvious candidate was the view: the pack runs above were taken at whatever angle the save held, so two
more were staged with `--at 548.5,63,-248.5 --yaw 0 --pitch 7.8` on the same commit and the same
configuration. They read **7.26 and 7.58 ms a frame - 4.4 per cent apart**, with the structural counters
still drifting (`renderPasses` 20922 against 20946, `loadedMiB` 93922.0 against 94007.2). So the camera is
not what varies; the window's own opening is the next suspect, because the harness arms on the pack's
*first* full frame and the world, the pack's temporal history and the machine's state all differ at that
instant between launches. Until the arming moment is made to wait for a settled frame, **a pack-scene
difference below about four and a half per cent is not attributable**, and the pinning of the camera is
worth doing for the picture comparison and not for the numbers.

### A picture comparison needs its own control, and in a pack scene the control is huge

The counters table has a picture comparison beside it, and it is easy to read it as an equivalence test. It is
one only where the scene's own run-to-run picture spread is smaller than the difference being judged, so every
picture claim needs the control first: **two runs of one configuration, same scene, same session**. Measured on
this machine, camera pinned, 600 frames each:

| scene | same configuration, two runs | two different presentations of it |
| --- | --- | --- |
| no pack | mean channel difference **0.04-0.05**, 0.03-1.61 per cent of pixels | plain against `-Dmetallum.metal4Present=true`: **0.04**, 0.08 per cent |
| Photon v1.3b at 55 per cent (MetalFX on) | **4.10**, 90.95 per cent of pixels | **3.65**, 88.84 per cent |
| Photon v1.3b at 100 per cent | **36.37**, 83.89 per cent of pixels | 2.06, 73.01 per cent |

**In the pack scenes the road-against-road difference is smaller than the scene against itself.** A pack brings
temporal history of its own - and at 100 per cent, where MetalFX is out of the picture entirely, the spread
grows to 36, which says the noise is the pack's and not the scaler's. So a picture claim in a pack scene is not
supported by one screenshot pair at any scale, however tight the counters are, and the no-pack scene is where
this test belongs: it is three orders of magnitude sharper, and it is the scene a frame-path change is judged
in first anyway.

Frame time does not follow the picture: the same 100 per cent pair read `wallP50` 10.75 and 10.73 ms while the
pictures differed by 36. Numbers and pictures have different noise floors, and a run that is quiet in one can
be loud in the other.

### The pack scene's spread was the settling time, and it is 0.14 per cent once settled

Two runs of one configuration, Photon v1.3b at 55 per cent with MetalFX, 600 frames each, camera pinned:

| settle after the pack's first full frame | run A | run B | spread |
| --- | --- | --- | --- |
| 5 seconds (the old default) | 7.26 ms | 7.58 ms | 4.4 per cent |
| 25 seconds | **7.26 ms** | **7.27 ms** | **0.14 per cent** |

and the structural counters agree at 25 seconds to 0.03-0.2 per cent (`renderPasses` 20928 against 20922,
`encoders` 21440 against 21435, `loadedMiB` 93943.3 against 93922.0) where at five they moved with the frame
time. So the variation was neither the camera nor the machine: it was the world still streaming and the
pack's temporal history still filling when the window opened. **The harness now waits 25 seconds by default
(`--settle S`), and five is kept as the fast path for a run whose number is not a claim.** This is the
deterministic fixture the earlier entries of this file said was missing, reached by waiting rather than by
building one.

### Machine state drifts, and the floor is the number to respect

Long sessions drift: the same configuration has read 23.0 and 28 ms in one afternoon. The fixture's
own repetition over 600 frames is **1.4 per cent in frame time** and a quarter of a per cent in most
counters. A difference below that is not a result, and a difference above it whose sign flips when the
run order flips is not one either.

### The launch must not move the owner's display, and a fullscreen launch does

The display's mode is machine state a measurement is taken on, and it is also the owner's screen. Measured on
this machine, whose desktop mode is `1800x1169@120` (3600x2338 pixels): **a fullscreen launch moves the display to
`1920x1200@120`** and leaves it there for as long as the client lives, at every window size asked for -
`--fullscreen-size 1600x900` through `1920x1200` all landed on the same mode, and the capture of the arm
(`screen.png`, which is a photograph of the whole display) is the record of it. A windowed launch does not move
it, at any size. The chain is the game's: `Window` asks `glfwSetWindowMonitor` for the monitor's own preferred
video mode, and the window server changes the mode to match.

Two consequences follow, and both are now handled rather than tolerated:

- **It cannot be put back while the client holds the display.** A watcher that restored the session's mode a
  second after the client switched it was refused by the window server - `no mode with id 66 is available now`
  - because the session's *scaled* mode is not in the mode list while an app holds the display exclusively.
  So the only prevention is not to ask for the game's fullscreen mode.
- **A session must not leave the mode or the instance moved.** `run-vitrail-performance.sh` reads the display's
  mode before the session (`tools/display/display-mode.swift`, compiled on first use into `run/display-mode`),
  checks it after every arm, puts it back when an arm left it moved, writes the move into
  `<out>/display-mode-moves.txt`, and puts the instance's own `options.txt` back when the session ends. A
  session that leaves the instance in the measurement profile is how a *later manual launch* came up fullscreen
  and moved the display on startup - the same fault one step earlier in the chain.

**The policy, decided with the owner on 2026-09-21: the game's fullscreen is a measurement-only configuration,
and the switch it causes during an arm is accepted.** The staged instance is left windowed
(`fullscreen:false`, `exclusiveFullscreen:false`), so a manual launch of the dev instance never moves the
display; a measurement session asks for `--fullscreen` and gets the game's own fullscreen window, and the mode
is recorded per session beside the target, checked after every arm, and put back when an arm left it moved. The
alternative - a borderless window that looks fullscreen and never changes the mode - was offered and declined
rather than left unwritten, because it means changing what "fullscreen" means for the client (an undecorated
window instead of an exclusive mode) and that is a product decision and not a harness one.

Every number in this file that was taken with `--fullscreen` is a number taken on whatever mode that session's
client asked for.

## Data analysis

### The two probe lines

    frame-probe openers renderPasses=... blitEncoders=... computeEncoders=... clearEncoders=... \
        metal4Frames=... metal4Us=... metal4Draws=... metal4Presents=...
    frame-probe 600/600 windowFrames=... windowMs=... gpuFrames=... gpuMs=... encoders=... \
        passChanged=... submit=... loadedMiB=... storedMiB=... depthAttachments=... \
        depthLoadedMiB=... depthStoredMiB=... blits=... blittedMiB=... pipeline=... texture=... \
        sampler=... buffer=... viewport=... scissor=... compiles=... compileMs=...

Derived numbers, which are the ones to quote:

| From | Derivation | What it answers |
| --- | --- | --- |
| `windowMs / windowFrames` | wall clock a frame | the frame rate; **the headline** |
| `gpuMs / gpuFrames` | the driver's own `GPUStartTime` to `GPUEndTime` | whether the frame waits on the GPU or on the CPU |
| `windowMs` against `gpuMs` | within 0.3 per cent means GPU-bound | where the next phase can win anything |
| `wallP50`/`wallP95`/`wallP99`/`wallMax` | the window's frame times as a distribution, in milliseconds | what a player feels: the mean hides the frame that took four times the others |
| `gpuP50`/`gpuP95`/`gpuP99`/`gpuMax` | the driver's own GPU time, the same way | read the two together: a wall tail with no GPU tail is CPU or presentation, and a tail in both is work |
| `encoders` | ends that were given a reason | *not* how many encoders were opened - see below |

Counters, and what a change in each means:

| Counter | Meaning |
| --- | --- |
| `renderPasses`/`blitEncoders`/`computeEncoders`/`clearEncoders` (openers line) | encoders **created**, by kind. This is the number to read for encoder work |
| `encoders` | encoders *ended with a reason*: it rises when fewer are ended silently, so it can move the wrong way over a change that removed encoders |
| `passChanged`, `submit` | the pass structure and the frames committed |
| `loadedMiB`, `storedMiB`, `depthLoadedMiB`, `depthStoredMiB`, `depthAttachments` | attachment traffic: the quantity the load/store actions move |
| `blits`, `blittedMiB` | copy-back traffic, which is invisible in a frame-time decomposition otherwise |
| `pipeline`, `texture`, `sampler`, `buffer`, `viewport`, `scissor` | bindings and state set on the encoders |
| `compiles`, `compileMs` | pipeline compilation during the window; zero on a warm store |
| `metal4Frames`, `metal4Us` | frames whose present the Metal 4 queue carried - one command buffer and one commit a frame - and the CPU cost of that one submission |
| `metal4Presents`, `metal4Draws` | drawables taken and presented by the Metal 4 queue, and how many of them drew the picture into it |

A present carried by the Metal 4 queue is the whole of that path's frame work, so `metal4Frames` and
`metal4Presents` should agree; when they do not, a frame was presented by the engine's own road.

`gpuM3Ms` and `gpuM4Ms` are each generation's own GPU time and `gpuMs` is their sum, which is the frame's
whole GPU time. That split is what closed the largest instrument gap this file used to carry: `gpuMs` was
the Metal 3 road alone, so a frame whose present moved to the new queue *lost* GPU time from the report
and read as if it had got cheaper - measured, 26.6 per cent lower while the wall clock did not move. A
Metal 4 submission is timed from its commit feedback (`MTL4CommitOptions`, `addFeedbackHandler:`), because
a Metal 4 queue returns nothing to its caller; `gpuM4Feedbacks` counts the feedback a window saw and
`gpuM4FeedbacksTotal` counts the session's, so "the queue never called back" and "it called back too late"
are different readings rather than the same silence.

One instrument fact worth knowing before trusting that count: **the commit feedback handler is consumed
by one commit.** Registered once, Metal called it once - for the first commit of the session - and never
again over the next 600; the path registers it again before every commit for that reason, which is why
`gpuM4FeedbacksTotal` is the session's commit count (4137 over one run) rather than 1 or 600.

The other gap is unchanged:
- **The per-pass table is the host clock, not the card's.** `-Dvitrail.passTimings=N` prints ranked
  rows that are the CPU cost of *encoding* a pass, because `MetalDevice.getTimestampNow()` is
  `System.nanoTime()`. Read it as encoder cost, never as GPU time.

### The comparison output

    counter             plain           present      first against rest
    windowMs            4315.7            4193.2                   -2.8%
    ...
    plain: 7.19 ms a frame, 139.0 frames a second, 7.09 ms of GPU time a frame over 600 answered frames
    present: 6.99 ms a frame, 143.1 frames a second, -2.8% against plain, ...
    picture, plain against present: mean channel difference 4.00, 94.59% of pixels differ at all,
        8.95% differ by more than 8, 49.91% by more than 2, worst 216 at 1075,311

The distribution is what the phases about low frames are judged on, and it separates two shapes that a
mean reports identically:

    no pack:   wall p50 1.76  p99 2.67  max 2.80 (at frame 510)   gpu p50 1.43  p99 2.36  max 2.50
    Photon 55: wall p50 7.06  p99 8.40  max 9.30                  gpu p50 6.98  p99 7.79  max 8.77

Both scenes are GPU-bound at every percentile: wall and gpu ride together, the no-pack p99 is 1.5 times
its median and the pack's 1.19, and the pack's worst frame is 1.3 times its median. What the distribution
is for is a frame like the one an earlier run of the same no-pack configuration reported - **a 5.60 ms
worst frame while the GPU's worst was 2.41**, three milliseconds the card did not spend. The run after it
reported 2.80 as its worst, so one outlier is not a stall until it repeats; `wallMaxAt` is there to say
whether the frame in question is the window's first, which is the delta across the moment the probe was
armed and therefore the one sample an instrument cannot yet take cleanly.

Read it in this order:

1. **Did both arms draw the same work?** `submit`, `depthAttachments`, `blits`, `storedMiB` and
   `loadedMiB` should agree to within a fraction of a per cent. If they do not, the arms are not the
   same frame and no time difference can be attributed.
2. **Is the difference above the floor?** Compare against the two same-configuration runs of the same
   session, not against a number remembered from another day.
3. **Does it survive the reversed pair?** If the sign flips, it is the machine.
4. **Is the picture inside the noise?** The picture line is only meaningful against the
   same-configuration pair: this tree's pack fixture reads mean 5.24 and 13.20 per cent above eight
   levels between two runs of *one* configuration, so an A/B at 4.00 and 8.95 is inside it.
5. **Which side of the frame moved?** `gpuMs` moving with `windowMs` is GPU work removed; `windowMs`
   moving alone is CPU or presentation.

### What a claim looks like

> No pack, fullscreen, uncapped, 600 frames: **1.77 against 1.79 ms a frame** (563.5 against 559.0
> fps), single-frame counters equal to 0.3 per cent, picture difference mean 0.26 with 0.30 per cent
> of pixels above eight levels.

That sentence carries the configuration, the window, the number, the counters that say the two arms
drew the same work, and the picture. A sentence without the configuration cannot be read, and one
without the counters cannot be trusted.

## A worked example, in this tree

Both scenes, 1920x1200 fullscreen, 600 frames, Metal backend, `maxFps` at the slider's maximum:

| Scene | plain (Metal 3 present) | present (Metal 4 present) | Verdict |
| --- | --- | --- | --- |
| no pack, no MetalFX | 1.78 ms / 560.6 fps | 1.78 ms / 562.1 fps | not slower (inside 1.4 per cent) |
| Photon at 55 per cent, MetalFX on | 7.23 ms / 138.4 fps | 6.95 ms / 143.8 fps | not slower; two pairs read 0 and 3.8 per cent, so the gain needs the reversed pair before it is a gain |

The Metal 4 arm reads `metal4Frames=600 metal4Us=26.6 metal4Draws=600 metal4Presents=600` without a
pack and `metal4Us=52.9` with one: that is the CPU cost of carrying the frame's whole presentation
through the new queue, one command buffer and one commit a frame. The plain arm reads `metal4Frames=0`,
which is what "the other road presented it" looks like in the probe.

In both, `submit`, `blits`, `blittedMiB`, `depthAttachments` and `storedMiB` were equal between the
arms and only `viewport` fell (the Metal 3 present's viewport is gone), which is what says the two
arms drew the same frame.

## Checklist

- [ ] The world and the pack are staged **outside** `run/`.
- [ ] `run` is clean: no leftover marker, no hand-edited `options.txt`.
- [ ] Both arms are one build: no source edit while the comparison runs.
- [ ] The profile line the harness echoes is the one that was wanted (`maxFps`, vsync, window mode).
- [ ] The harness exited 0, and the log says `Using graphics backend Metal`.
- [ ] Two runs of one configuration were taken in the same session.
- [ ] The counters agree between the arms before the frame time is read.
- [ ] The picture delta is read against the same-configuration pair.
- [ ] Nobody pressed F3 in a measured arm.
- [ ] The claim names the scene, the window, the frame count, the switches and the counters.

### What was measured for the mode policy, and where the evidence is

```
run/j1-mode-windowed   windowed, no --fullscreen          capture 3600x2338  display mode unchanged
run/j1-mode-guard      --fullscreen, clean exit           capture 1920x1200  mode restored by the client's own exit
run/j1-mode-kill       --fullscreen, client SIGKILLed     capture 1920x1200  mode restored by the window server
run/j1-mode-windowed2  windowed, after the instance fix   capture 3600x2338  options.txt restored to windowed
```

`--fullscreen-size 1800x1169` (the display's own mode) did not prevent the switch either - the requested size is
not what decides it, which is why the fix is the window mode and not the size - and setting the game's own
`fullscreenResolution` option to the same mode did not prevent it. Both negative results are recorded here
because both look like the obvious fix.
