# Vitrail's GPU workload: the structural corpus, the passes a scale does not move, and the shadow stage

Track C of the long-term plan. C1 asks for one structural census across the corpus - passes, draws, shadow,
copies, mipmaps, attachment traffic - so that "this pass is expensive" stops being a guess; C3 asks which passes
still run at the window's own size when the world is drawn small; C2 asks what the shadow stage costs family by
family and whether the terrain in it can be reused. All three are here: C1 and C3 from one batch of five
sessions, C2 from four more.

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
  does not ask for - C2's decomposition is by *workload* (terrain, entities, translucent, mips), and it is the
  section below.
- **The shadow numbers are walks, not GPU time.** 148 walks a second keeping 1700 sections and drawing 1414 of
  them on MakeUp is a lot of geometry to ask the GPU for; what it costs is the GPU's, and C2's removal probes
  below are what priced it.

## Next

1. **C2, the shadow workload**: decomposed in the section below; what is left of it is the entity family and a
   resolving measurement on the second pack.
2. **C7's corpus, which is now cheap**: the attachment-traffic switch has already been measured on one scene
   (`docs/metal3-performance-report.md`); with this table as the baseline, the same switch on the three packs is
   four arms and a table.
3. **The three remaining scenes at 55 per cent** for C3's completeness, which is four sessions.

---

# C2 - the shadow stage, decomposed by the counters that cannot drift

Starting Metallum SHA: `f792ae9`
Ending Metallum SHA: `e9580e9`
Starting Vitrail SHA: `6afce954`
Ending Vitrail SHA: `5b498e70`

## Question

The plan asks what the shadow stage really costs, family by family, and whether the terrain in it may be reused
across frames. The previous programme answered part of that on a pack whose shadow stage voxelises, where the
engine's own reuse is refused by design (`Vitrail-Shaders-Metal/docs/performance-report.md`: opaque terrain
0.04 ms, translucent 0.25 ms, entities unmeasurable on an entity-free fixture, voxelisation UNKNOWN). C1 then
found that **two of the three corpus packs do not voxelise**, so on them the reuse the plan wanted to explore is
already shipping and already at work - which changes the question from "can it be reused" to "what is the reuse
worth, and is a longer arm worth more".

## Baseline

C1's corpus, unchanged: MakeUp-UltraFast-9.5e, ComplementaryReimagined r5.9.1 and Photon v1.3b, 1920x1200,
600-frame windows, 25 s settle, Metal 3, frozen world at 4000 ticks, weather clear, entities stripped.

The one baseline fact C2 had to establish first is **which packs let the engine keep the map at all**, and the
engine says so itself: `Shadow map: the opaque world was drawn into it N times in the last 600 frames`.

```
scene             shadow map  culling                kept/drawn a walk   reuse        opaque draws/600
no-pack           -           -                      no shadow stage     -            -
MakeUp            4080x4080   ADVANCED SWEPT r=255   1700 / 1414         allowed      300
Complementary     2048x2048   DEFAULT SWEPT r=192     975 /  947         allowed      300
Photon            2048x2048   SAFE_ZONE r=128 z=32    496 /  496         REFUSED      600
Complementary@55  2048x2048   DEFAULT SWEPT r=192     975 /  947         allowed      300
```

Photon's refusal is the engine's own, logged in those words: *"This pack voxelises into its shadow pass, so the
map is drawn every frame whatever the reuse setting says"*. The other three draw the opaque world every OTHER
frame, which is `ShadowAmortisation`'s shipped default of one kept frame.

## Instrument

Three default-off removal arms already existed in the tree (`ShadowTerrain`, from `e9a6e30f`):

```
-Dvitrail.probeNoShadowRaster=true        both chunk layers out of the map
-Dvitrail.probeNoShadowTranslucent=true   the translucent layer out
-Dvitrail.probeNoShadowEntities=true      the movers' draw out
```

and beside them the shadow map's own pass count, which C1's `MetalFrameProbe.passTarget` gives: every shadow
raster into the map is one `4080x4080` (or `2048x2048`) render pass, so a pass count per 600 frames *is* a draw
count. That counter is exact, and it is what makes this section readable on a machine whose frame times are not.

One counter did not exist: the removal arms price the raster at the interval the engine ships, and the question
of a *longer* interval is a difference between two arms and not a component of one. `-Dvitrail.probeShadowInterval=N`
was added to `ShadowAmortisation` (`5b498e70`) for it: nought to `MAX_FRAMES` are the selector's own values,
written before a launch because the arming file holds one value for a whole session, and above the cap it is a
measurement arm whose log line says the picture is wrong by construction. Nothing reaches it from the screen.

## The decomposition, where it cannot drift

Per 600-frame window, Metal 3, 1920x1200. The pass column is the shadow map's own render passes, and the
allocation of those passes is exact: `interval 1` = 300 opaque + 600 translucent, `interval 0` = 600 + 600, and
`no raster` = 0.

```
MakeUp-UltraFast-9.5e (4080x4080 map, 1414 sections a walk)
arm                4080^2 passes/600   blits/600   loadedMiB/f  storedMiB/f  depthAtt/f   ms/f
interval 0                1200            4200        417.8        525.2        8.0      7.383
interval 1 (shipped)       900            5400        385.8        461.4        7.5      6.726
interval 2 (selector max)  800            5400        375.0        440.1        7.3      6.344
no translucent             300            5400        258.7        334.4        6.5      6.614
no chunk layers              0            5400        226.4        270.3        6.0      5.269

ComplementaryReimagined r5.9.1 (2048x2048 map, 947 sections a walk)
arm                2048^2 passes/600   blits/600   loadedMiB/f  storedMiB/f  depthAtt/f   ms/f
interval 0                1311            3000        322.2        484.5        8.0      9.194
interval 1 (shipped)      1000            4800        321.8        460.1        7.5      8.289
interval 2 (selector max)  905            4800        321.7-336.4  451.9-466.7   7.3-7.7  8.031 / 8.808
no translucent             407            4800        289.5        427.8        6.9      8.898
no chunk layers             88            4800        273.4        387.6        6.0      7.291
```

Both packs carry a one-off ~100-pass mip cascade at each size from the load, which is why the base is not nought:
`Complementary interval 2` reads 905 = 105 + 200 + 600, and its `interval 0` reads 1311 = 111 + 600 + 600.

**And the arms of one session are not the same frame even when nothing is switched.** Complementary's four
interval arms split by *position*: the first two read 336.7 and 336.4 `loadedMiB` a frame and the last two 321.8
and 321.7, whatever interval each was running - a 4.5 per cent spread in the attachment traffic of a frozen
scene, which is the drift the comparison refuses these sessions on and the reason the Complementary interval-2
pair is unresolved rather than merely noisy.

**What the columns say.** The translucent half runs **every frame** and the opaque half every other frame, so per
frame the translucent layer loads and stores the map's attachments **twice as often** as the opaque one does -
which is why removing it is the larger structural change on both packs (`loadedMiB` falls 33 per cent on MakeUp
and 10 per cent on Complementary, against 12 and 6 for the opaque half, and 20.6 per cent of the frame's loaded
attachment bytes were already attributed to it on the reference pack). The 4080x4080 map costs MakeUp far more
than the 2048x2048 map costs Complementary in absolute traffic, and the pass counts say the rest: **the frame's
shadow work is dominated by the map's attachment traffic, not by the number of sections drawn.**

`blits/600` moves only when the interval moves to nought: 5400 to 4200 on MakeUp and 4800 to 3000 on
Complementary. The keep is what they follow - four blits a kept map on MakeUp, six on Complementary - and what
issues them beyond that is NOT ATTRIBUTED here.

## The wall, and the estimator this machine allows

The machine would not hold still. Arms of **identical structure** - same pass counts, `loadedMiB` within 0.3 per
cent - read between 6.57 and 9.92 ms a frame across sessions, and within one session two arms of one
configuration read 9.92 and 7.07. The display mode was the same before every session (`1800x1169@120`, id 66) and
no arm moved it; the machine's load average was **lower** during the slower arm (3.85 against 5.81); the GPU
trace shows the device at 100 per cent with the client as `fLastSubmissionPID` in every sampled window of every
arm, so no other client is visible during a window; and the CPU side is not the driver (`frameCpuMs` is flat).

What that leaves is a **one-sided** noise - another user of the GPU can only make a frame slower - so the reading
worth comparing between two configurations is the **minimum over repeats**, and the repeats must be able to show
that the minimum is real. They can: one configuration (interval 1 on MakeUp) read

```
6.726  6.734  6.734  6.740  6.750        five arms, four sessions, 0.4 per cent apart
```

while the same configuration in a disturbed arm read up to 9.917. So the intervals below are compared on minima,
and a configuration whose own repeats disagree by more than the effect is reported as unresolved rather than
averaged.

```
MakeUp            interval 0   7.383   (2 arms, 0.01 % apart)
                  interval 1   6.726   (5 arms in 4 sessions, 0.4 % apart)   <- shipped default
                  interval 2   6.344   (2 arms, 0.3 % apart, one session whose reference pair read 6.740/6.734)
Complementary     interval 0   9.194   (2 arms, 0.3 % apart)
                  interval 1   8.289   (4 arms, 0.4 % apart)   <- shipped default
                  interval 2   8.031   (2 arms 9.7 % apart: 8.031 and 8.808)   UNRESOLVED
```

**What the shipped reuse is worth is therefore measured, and on the one pair that is semantically correct rather
than diagnostic**: interval 1 against interval 0 on MakeUp is **0.657 ms of a 6.73 ms frame, 9.8 per cent**.
Two roads bound the two costs it trades. The removal arms give `no translucent - no chunk layers = 1.345 ms` for
`raster + keep` (0.880 against the same session's other removal arm, which is the spread those diagnostic arms
carry), and the interval arms give `interval 0 - interval 1 = 0.657 ms` for `raster - keep`; solved together they
put one drawn 4080x4080 raster at **1.5 to 2.0 ms** and one kept map at **0.1 to 0.7 ms**, and the interval-2
prediction `(raster + keep) / 3 = 0.29 to 0.45 ms` lands around the **0.385 ms measured**.

**The interval-2 candidate is KEPT as a measurement and DEFERRED as a change.** It is worth 5.7 per cent on
MakeUp - above the plan's five per cent gate - but on Complementary its two arms differ by 9.7 per cent, which is
more than either the effect or the plan's noise floor, so the second of the two real packs the high-risk gate
requires is not satisfied yet. Nothing is broken by leaving it: the selector already offers nought, one and two,
so a player who wants the longer arm can choose it today; the only question the measurement would settle is what
the **default** should be, and one pack is not enough to move a default on.

## The family the corpus cannot show: the things that move

Every corpus session strips the world's entities before it starts, so `Shadow casters` read **0 frames gathered**
in all of them and the movers' removal arm moved the frame by nothing. The harness has a fixture for it -
`--vanilla-mobs` stages a pig, a cow, an armour stand, a dropped item and an experience orb in front of the
camera, one of each, placed once and never again - so the arm was taken: MakeUp, same world and protocol, with
the removers' draw kept and removed.

```
arm                 caster census          passes/f   loadedMiB/f  storedMiB/f  depthAtt/f   ms/f
movers drawn        148 frames, 5.0 a frame   22.38       576.2        651.9        10.5     6.574 / 6.868
movers removed      0 frames, 0.0 a frame     21.33       447.3        523.0         9.5     6.865 / 6.854
shadow walk one a second, movers drawn:  kept 1693 a walk, drew 1569 a walk
shadow walk one a second, movers removed: kept 1700 a walk, drew 1414 a walk
```

**The structure is the finding, and it is exact.** Five entities, none of them large, add **one full-size render
pass a frame** into the 4080x4080 map - 1.06 passes a frame over 600 frames - and with it **129 MiB of loaded and
129 MiB of stored attachment traffic a frame**, 29 and 25 per cent of the frame's whole attachment traffic. That
is `4080 x 4080 x 4 bytes x 2` for the pass's load and store, to the mebibyte, so what the movers cost is the
**full map's traffic for a handful of texels of content**, once a frame, and it can never be amortised: they move,
which is the whole reason the engine's reuse covers the opaque world and nothing else.

**Their wall price is NOT RESOLVED.** The removal arm reads 6.865 and 6.854 (0.2 per cent apart) while the two
arms that draw them read 6.574 and 6.868 (4.5 per cent apart), so the arm with less work sits *inside* the spread
of the arm with more - and one of the pairs even orders the wrong way. This session is a case of the rule above:
the repeats disagree by more than the effect, so the answer is unresolved rather than a small number.

## Correctness

- Every arm ran Metal 3 and said so: the probe's own `executingGeneration=metal3`, checked by the harness's new
  `--expect-execution metal3` guard after a whole session was collected on Metal 4 by mistake.
- The structural counters are the correctness evidence for the mechanism: 900 = 300 + 600, 1200 = 600 + 600,
  800 = 200 + 600, and 0 when the chunk layers are removed. No arm's picture was used to decide anything.
- The arms are diagnostic and known-wrong by construction: the removal arms leave the map missing what the pack
  asked it to hold, which is the point of a removal arm. The interval arms are the engine's own setting at
  values the selector already offers, so they are the one family here that is semantically correct.
- The comparison script refuses all of these sessions, on its scene-drift guard, with the difference exactly
  where the switch says it should be (`depthAttachments -2.2 per cent` for one fewer shadow pass in 600 frames).
  That guard is written for arms that draw the same frame; a removal arm is not one, so its refusal here is read
  as "the arms differ, and here is by how much", not as a drifted scene.

## Decision

**KEPT - the finding, not a change.** The shadow stage's decomposition is measured on the two packs where the
engine's reuse applies, and the shipped reuse is worth **9.8 per cent** on MakeUp; the selector's own maximum is
worth another **5.7 per cent** there and is unresolved on Complementary. No code changed for either: the arms are
default-off probes and the one addition is the interval override that makes the comparison possible.

**DEFERRED - raising the default interval from one to two.** Above the gate on one pack, unresolved on the
second, and the setting is already exposed to the player.

**REJECTED - a shadow-specific mip probe.** The existing `-Dvitrail.probeNoMipChains` removes every chain at
once, so the map's own chain cannot be separated from the pack's; the previous programme priced all of them at
0.045 ms, 1.0 per cent, below the plan's 0.1 ms gate, and that is where this stays.

**NOT MEASURED - the voxel family.** The voxel write is inside the same fragment program as the raster and no
switch takes it out without changing what the pack's shader does. The entity family, which was in the same
position at the end of the corpus work, is measured in the section above: five movers, one extra full-size pass a
frame, 129 MiB of attachment traffic a frame, and a wall price this session could not resolve.

## Residual

- **The machine's arm-to-arm spread is NOT ATTRIBUTED.** Identical structure, identical configuration, 47 per
  cent apart across arms; no display-mode move, no foreign submitter visible in the GPU trace, no CPU
  explanation. Every wall figure here is a minimum over repeats for that reason, and an effect smaller than
  about 5 per cent is not resolvable today.
- **Complementary's interval-2 pair did not resolve** (8.031 against 8.808, 9.7 per cent), and one session was
  run without a reference arm of its own, which is why it is not in the table: a session without one yields
  numbers that cannot be placed on any scale. Both are protocol faults of this round, recorded in
  `docs/performance-testing.md`.
- **The keep's blit accounting is not separated** from the rest of the frame's copies.
- **The shadow walk's CPU cost is still unmeasured** - 148 walks a second keeping 1700 sections is a cost on the
  render thread and this round priced only the GPU side.

## Next

1. **A resolving measurement of the entity family and of the Complementary interval**, in sessions whose arms
   carry their own reference and whose repeats agree - which needs the machine to hold one state for the length
   of a session.
2. **C7's corpus** and **C3's remaining three scales**, unchanged from the list above.
