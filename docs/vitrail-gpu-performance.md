# Vitrail's GPU workload: the structural corpus, and the passes a scale does not move

Track C of the long-term plan. C1 asks for one structural census across the corpus - passes, draws, shadow,
copies, mipmaps, attachment traffic - so that "this pass is expensive" stops being a guess; C3 asks which passes
still run at the window's own size when the world is drawn small. This is both, from one batch of five sessions,
plus the one counter that did not exist for either.

## Starting SHAs

```
Metallum: 8f05f7c + this round's pass-size census
Vitrail:  6afce954
```

## The corpus

One Metal 3 arm a scene, 600-frame windows, 25 s settle, fullscreen exclusive at 1920x1200, camera and world as
the rest of this repository's protocol (`run/c1-*`). Every figure is per frame unless it says a second; the
per-second ones are Vitrail's own censuses, which say a rate.

```
scene              ms/f   passes/f  window-size passes/f   blits/f  blitMiB/f  loadMiB/f  storeMiB/f  encoders/f
no-pack            1.68      3.20            9.0            0.0       0.0       18.3       53.4       3.20
MakeUp             6.73     19.31           17.0            9.0     238.8      385.8      461.4      19.75
Complementary      8.29     23.49           20.0            8.0      97.0      321.8      460.0      23.91
Photon            12.96     35.56           27.0           11.0      82.5      416.1      536.0      36.30
Complementary@55   6.90     23.33            1.0            8.0      74.0      138.8      203.5      23.77

scene              indexed draws/f   indirect draws/f   shadow walks/s   mip chains/s   compute/s
no-pack                    5.0              2425              -               -            -
MakeUp                    14.6              3758            148.0           296.0          -
Complementary              7.0              3347            120.4           481.2          -
Photon                     7.5              3350             74.1           150.6        148.2
Complementary@55           7.0              3347            144.2           577.7          -
```

Read together with round one's native-call census (`docs/metal3-performance-round2.md`), the shape is:
**the frame's GPU work is the terrain's**, in indirect draws and attachment traffic, and everything else is
small. The packs add their own passes (7 to 16 more a frame than no-pack's 3.2), a shadow map, a mip cascade and
- Photon only - 148 compute dispatches a second. **The shadow casters census reads 0 frames gathered in every
scene**, which is the harness's own doing (it strips the world's entities before a run), so "what a mob casts"
is NOT MEASURED here and is not zero in a played world.

## The counter that did not exist: a pass's own size

C1 asks for full-resolution and half-resolution passes, and C3 asks which passes stay at the window's size when
the world is scaled; nothing counted either, because a render encoder is told its target and the probe only knew
its attachments. `MetalFrameProbe.passTarget(width, height)` is now called from the pass's own constructor with
its render area, and the window line carries the split, largest first:

```
no-pack          passSizes=2048x2048:20,1920x1200:5400,1024x1024:20,512x512:20,256x256:20,128x128:20,16x16:20
MakeUp           passSizes=4080x4080:900,2048x2048:81,1920x1200:10200,1024x1024:81,...,16x16:81
Complementary    passSizes=2048x2048:999,1920x1200:12000,1024x1024:99,960x600:600,512x512:99,...,16x16:99
Photon           passSizes=2048x2048:1356,1920x1200:16200,1024x1024:156,960x600:1200,512x512:756,480x300:600,
                            256x256:156,192x108:600,128x128:156,16x16:156
Complementary@55 passSizes=2048x2048:983,1920x1200:600,1056x660:11400,1024x1024:83,528x330:600,512x512:83,
                            256x256:83,128x128:83,16x16:83
```

The 16-to-2048 cascade of twenty or so passes each is a one-off (the loading screen's mip chain), and the packs'
own resolution ladder is visible: **Photon draws into 1920x1200, 960x600, 480x300, 512x512 and 192x108 every
frame** - its history and light targets are not all at one size - while Complementary has one half-size target
(960x600, one a frame) and MakeUp draws its shadow map at **4080x4080** where the other two use 2048x2048.

## C3's answer, for the pack that has shadows

At **55 per cent** Complementary's frame is: **one** pass a frame at the window's own 1920x1200, nineteen at the
scaled world's 1056x660, one and a half at the shadow map's 2048x2048, one at a half-of-scaled 528x330, and the
one-off mip cascade. The single native pass is the interface's (the plan's own expectation), the shadow map is
sized by the pack's shadow distance rather than by the render scale (also expected - the plan lists it), and
**every world pass followed the scale**. The traffic says the same thing: `loadedMiB` 321.8 to 138.8 a frame
(-57 %) and `storedMiB` 460.0 to 203.5 (-56 %) at the same pass count.

**So C3's hypothesis - a heavy world pass left at native resolution - is REJECTED for this pack**, and it was
rejected by a counter rather than by an argument. What remains unmeasured is the other three scenes at a scale
(none of them has Photon's five-target ladder) and whether any *pack-declared* target is pinned at the window's
size by the pack's own declaration rather than by the engine's scale (`colortexNMipmapEnabled` and a pack's
fixed-size targets are the candidates).

## Decisions

**KEPT: the pass-size census**, on the window line, with the entry point and the road that reaches it pinned in
`tools/ci-frame-probe.py` and a mutation that deletes the road failing the contract.

**REJECTED: C3's premise for Complementary** - one native pass, the interface's, and the shadow map; no heavy
world pass is left full-resolution. Two more scenes at a scale would extend the claim, and they are sessions'
work rather than code.

**NOT MEASURED, and named rather than left implied**: what shadow casters cost (the harness strips entities),
the storage-boundary counter C1 lists (the probe's `storedMiB` is the traffic; there is no per-boundary count),
and feedback snapshots (the only counter is Metal 4's, and a Metal 3 session reports zero of them - so C5 is an
M4-only question while Metal 4 is frozen).

## Residual and what is NOT MEASURED

- **Draws come from round one's census runs and the rest from this round's**, which is the same scene and the
  same protocol but not the same session; the plan's A/B discipline does not apply to a census, and every figure
  here is either a count (exact) or a rate (per second), so no comparison is made across the two.
- **This is one display mode and one machine state**, and round four measured a **20 per cent wall difference
  between two batches on counters that agreed to half a per cent** (`docs/metalfx-performance.md`): the structural
  figures here are counts and rates and are not exposed to that, but the `ms/f` column is one batch's.
- **Nothing is decomposed per pass.** C1's fields are per frame; "which pass costs what" needs the GPU's own
  per-pass times, which this engine cannot attribute on Metal 3 (no marker road on this path) and which the plan
  does not ask for - C2's decomposition is by *workload* (terrain, entities, translucent, mips), which the next
  step takes up.
- **The shadow numbers are walks, not GPU time.** 148 walks a second keeping 1700 sections and drawing 1414 of
  them on MakeUp is a lot of geometry to ask the GPU for; what it costs is the GPU's, and pricing it is C2's
  removal probes.

## Next

1. **C2, the shadow workload**: decompose it as the plan lists (terrain opaque, cutout, translucent, entities,
   voxel-writing, mip) with removal probes that are default-off, and build the dependency matrix. The corpus
   above says where to start: MakeUp's 148 walks/s drawing 1414 sections a walk, and a 4080x4080 map.
2. **C7's corpus, which is now cheap**: the attachment-traffic switch has already been measured on one scene
   (`docs/metal3-performance-report.md`); with this table as the baseline, the same switch on the three packs is
   four arms and a table.
3. **The three remaining scenes at 55 per cent** for C3's completeness, which is four sessions.
