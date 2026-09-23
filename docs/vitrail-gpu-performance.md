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
`tools/ci-metal3.py` and a mutation that deletes the road failing the contract.

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
                  interval 1   8.285   (4 arms in 2 sessions, 0.3 % apart)   <- shipped default
                  interval 2   8.035   (4 arms in 2 sessions, 0.14 % apart)
```

**Complementary's interval-2 pair was unresolved when this section was first written** (8.031 against 8.808, 9.7
per cent apart) and it is settled here by repetition, which is what the plan's own rule asks for: eight more arms
over two sessions put interval 1 at 8.285, 8.287, 8.290 and 8.311 and interval 2 at 8.035, 8.036, 8.037 and
8.046 - each configuration's four arms inside 0.3 per cent, the two configurations **3.0 per cent** apart, and
the mechanism exact in the same arms: `2048x2048` falls from 1000 passes a window to 897 and the engine's own
line reads `drawn into it 300 times in the last 600 frames` against `200`.

**So the interval-2 candidate is worth 3.0 per cent on Complementary and 5.7 on MakeUp**, measured on the two
packs where the reuse applies at all, with the structure exact on both. What it is not is shipped: the setting
the candidate moves is a player's, `ShadowAmortisation.DEFAULT_FRAMES` is 1 and the selector already offers 2, so
raising the default is a change to what every player gets without asking - section 59's fourth pause - and what
the reference's own note says is missing is an *eye*: the map kept whole at three frames read as a bug and the
movers are drawn back in now, so what ages is the ground and nobody has looked at it. The measurement is done and
the decision is the owner's.

**What the shipped reuse is worth is therefore measured, and on the one pair that is semantically correct rather
than diagnostic**: interval 1 against interval 0 on MakeUp is **0.657 ms of a 6.73 ms frame, 9.8 per cent**.
Two roads bound the two costs it trades. The removal arms give `no translucent - no chunk layers = 1.345 ms` for
`raster + keep` (0.880 against the same session's other removal arm, which is the spread those diagnostic arms
carry), and the interval arms give `interval 0 - interval 1 = 0.657 ms` for `raster - keep`; solved together they
put one drawn 4080x4080 raster at **1.5 to 2.0 ms** and one kept map at **0.1 to 0.7 ms**, and the interval-2
prediction `(raster + keep) / 3 = 0.29 to 0.45 ms` lands around the **0.385 ms measured**.

**The interval-2 candidate is KEPT as a measurement, measured on both packs, and the owner has declined it.**
It is worth 5.7 per cent on MakeUp and 3.0 on Complementary (above), which satisfies the "two real packs" half of
the plan's high-risk gate and leaves two things against it: one of the two packs is under the five per cent the
gate asks for, and the map is three frames old instead of two for the ground, which no screenshot of a still
camera can show. **The default stays at one kept frame.** Nothing is broken by the answer: the selector already
offers nought, one and two, so a player who wants the longer arm can choose it today, and what was declined was
the default and not the measurement - the numbers above stand as taken.

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

**Their wall price is 0.13 per cent**, and it took repetition to say so. The first session had the removal arm
at 6.865 and 6.854 against 6.574 and 6.868 for the arms that draw them - the arm with less work inside the spread
of the arm with more - and the rule above says that is unresolved rather than a small number. Eight more arms
over two sessions settle it:

```
movers removed   6.853  6.854  6.866  6.872      (4 arms, 0.3 per cent apart)
movers drawn     6.862  6.875  6.878  6.885      (4 arms, 0.3 per cent apart)
                 +0.009 ms a frame, +0.13 per cent
```

So the movers' shadow pass - one full-size pass a frame and 129 MiB of attachment traffic with it - costs
**thirteen hundredths of one per cent of a frame**, which agrees with C7's finding next door: on this backend a
large fall in attachment bytes does not move the frame, because the frame is not attachment-bound. The family is
CLOSED: structure measured exactly, wall measured to a tenth of a per cent, and no candidate in it.

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

**DECLINED BY THE OWNER - raising the default interval from one to two.** Above the gate on one pack,
unresolved on the second, and the setting is already exposed to the player; the owner has decided that the
default stays at one kept frame, so this is a closed decision and not a deferral - the measurement stays in this
document and the ground's lag stays as it is.

**REJECTED - a shadow-specific mip probe.** The existing `-Dvitrail.probeNoMipChains` removes every chain at
once, so the map's own chain cannot be separated from the pack's; the previous programme priced all of them at
0.045 ms, 1.0 per cent, below the plan's 0.1 ms gate, and that is where this stays.

**NOT MEASURED - the voxel family.** The voxel write is inside the same fragment program as the raster and no
switch takes it out without changing what the pack's shader does. The entity family, which was in the same
position at the end of the corpus work, is closed in the section above: five movers, one extra full-size pass a
frame, 129 MiB of attachment traffic a frame, and a wall price of 0.13 per cent over eight arms.

## Residual

- **The machine's arm-to-arm spread is NOT ATTRIBUTED**, and it is intermittent rather than constant: the
  sessions that closed the entity family and Complementary's interval reproduced to 0.1-0.3 per cent across all
  eight arms each, where earlier ones scattered by 47. Every wall figure here is a minimum over repeats, and the
  repeats now say which sessions are usable instead of the machine being written off wholesale.
- **Complementary's interval-2 pair is resolved** (3.0 per cent over eight arms, above), and the one session
  run without a reference arm of its own is still not in any table: a session without one yields numbers that
  cannot be placed on any scale. That protocol fault is recorded in `docs/performance-testing.md`.
- **The keep's blit accounting is not separated** from the rest of the frame's copies.
- **The shadow walk's CPU cost is still unmeasured** - 148 walks a second keeping 1700 sections is a cost on the
  render thread and this round priced only the GPU side.

## Next

1. **A resolving measurement of the entity family and of the Complementary interval**, in sessions whose arms
   carry their own reference and whose repeats agree - which needs the machine to hold one state for the length
   of a session. **Both were taken and both are closed in this section above**: eight arms each, the entity
   family at +0.13 per cent and Complementary's interval at 3.0, with every configuration's own repeats inside
   0.3 per cent.
2. **C7's corpus** and **C3's remaining three scales**, both done in this document's later sections.

---

# C4, C5 and C6 - the copies, the feedback targets, and the chains

Starting Metallum SHA: `6ac62a6`
Ending Metallum SHA: `6ac62a6` + this round's documents
Starting Vitrail SHA: `5b498e70`
Ending Vitrail SHA: `5b498e70` + this round's labelled mipmap census

## Question

C4 asks which copies are a semantic requirement and which are only a schedule result, and which packs never
read what they copy. C5 asks how many feedback snapshots a frame takes and what they cost. C6 asks how many mip
chains are reduced, of which targets, and whether any is filled after nobody reads it. All three are structural
questions in a programme whose frame-time instrument cannot resolve a few per cent, and two of the three turned
out to be answerable from counters that already existed.

## Instrument

- **The copybacks are declared at load**, once per pack: *"N targets are copied back from their far half at the
  end of every frame, because the pack keeps them and the chain left them there: [...], and M of those are read
  by nothing in the frame"*. The `-Dvitrail.elideTargetCopies` arm, written by the earlier programme and off by
  default, is what turns that list into a measurement.
- **The blit counter** (`blits`, `blittedMiB` in the frame probe) is what the earlier programme said was missing
  when it first looked at this: a copy-back is a transfer, so no attachment counter sees one.
- **`TargetCopyCensus`** already prints *"Feedback copies: N copies of X MiB in the last M ms"* once a second,
  and fires only where a geometry program samples a target it also writes.
- **`MipmapCensus`** already printed chains, levels and pixels; what it could not say was *which* target, and a
  rate of four chains a second is four images and not one. It now takes the caller's label - a pack target's own
  name, or `shadow` / `shadowtex1` for the map's two images - and prints the breakdown. The count is taken at the
  one road both callers reach, so a pack target's chain is counted once.

## A/B - the copybacks, across the corpus

Three arms a pack, one session each: `plain`, `elide`, `plain-b`. Order and counts are the engine's; the frame
times are the session's own.

```
scene           copied back   read by nothing   elide removes   blits/600        blittedMiB/600
MakeUp               6            2             2 copies        5400 -> 4200     143305.7 -> 132758.8
Complementary        4            0             0               4800 -> 4800      58175.4 ->  58175.4
Photon              10            3             3 copies        6600 -> 4800      49516.1 ->  47927.3
no-pack              0            -             -               -                 -
```

**The declaration and the counter agree on all three packs**, which is the correctness result: the switch removes
exactly the copies the engine said nothing reads, and no others. What they are worth is exact too: **17.6 MiB a
frame** on MakeUp, where both unread copies are full-size 1920x1200 targets at 8.79 MiB each, and **2.6 MiB a
frame** on Photon, where all three are small ones at 0.88 MiB - the resolution ladder it draws into, not the
window. On Complementary the switch removes nothing at all, because nothing there is unread, and the frame is
unchanged to the byte.

The frame times, against each session's own repeat pair:

```
MakeUp          plain 6.731   plain-b 6.740   (0.13 % apart)   elide 6.657   -1.1 %
Complementary   plain 8.280   plain-b 9.988   (20.6 % apart)   elide 8.323   +0.5 %   (nothing removed)
Photon          plain 13.158  plain-b 12.144  ( 8.4 % apart)   elide 12.535  -4.7 %   (inside the spread)
```

**So the copy class is REJECTED as a default, on the corpus rather than on one pack.** One session resolves 1.1
per cent on the pack whose copies are a seventh of its blit traffic; the other two cannot resolve anything, and
the pack that removes nothing moves by half a per cent - which is the noise floor of this machine saying what it
is. That is the same verdict the earlier programme reached on Photon alone, now with three packs and with the
blit counter that was missing then; section 5's rule G applies, and the switch stays where it is, off by default.

## C5 - feedback snapshots

**Zero, on every pack of the corpus.** `TargetCopyCensus` exists, prints once a second and never fires: none of
MakeUp, Complementary or Photon samples a colour target on the half it writes, which is the condition that makes
the engine keep a copy. The mechanism is a semantic workaround and not an optimisation - the public descriptor
cannot express a pass that reads its own attachment - so C5's "only optimise where a real pack shows a
significant cost" resolves to nothing to optimise, with the counter standing for the pack that does need it
(Sildur's water, in the class's own note). **NOT MEASURED on any pack outside this corpus**: no real pack of the
corpus triggers it, so its cost has never been paid here.

## C6 - the chains, by target

`plain` arms, 600-frame windows, chains a frame derived from the interval and the window's frame rate.

```
scene           chains/frame   targets
no-pack             0          none: no pack, no chain
MakeUp              2.0        colortex0 alt, colortex1
Complementary       4.0        colortex5 alt, colortex0 alt, colortex3, colortex0
Photon              2.0        colortex11 alt, colortex5
```

Every chain is 11 levels (the pack targets' full chain), and every one of them is filled **because a pass asked
for a lod**: `PackChain` generates a surface's chain at the `lodRead` that precedes the reader and only where the
surface is not already current for this frame, so a chain nothing reads cannot be filled by construction. The
map's own two images follow the pack's declaration instead - MakeUp's, Complementary's and Photon's ask for no
shadow chain at all, which the allocation line says by its silence - and the fixture that does declare them gets
exactly two, verified this round by running `tests/fixtures/shaderpacks/shadow-mipmap-contract` through the
performance harness:

```
Shadow map allocated at 1024x1024, ... and the pack asks for a chain the light fills every frame,
  10 levels where it reads shadowtex0 and ... where it reads shadowtex1
Mip chains: 1002 reduced over 1000 ms (1001.1 a second), 10.0 a chain, by target shadowtex1=501,shadow=501
```

**No candidate: the validity rule the plan asks about is already the rule in force.** A chain is filled for a
reader that asked for a lod and skipped when it is still true, and the shadow pair exists only where a pack
declared it. What the new labels add is that a reading of the line can now tell the shadow map's chains from a
pack's - which the corpus does not exercise, and the fixture does.

## Correctness

- No engine behaviour changed: the copy measurements are the existing switch and the existing counters, and the
  mipmap census change is counting, a label and a line, with the chain itself filled by the same call it was.
- The A/B's correctness argument is the engine's own reader analysis: a copyback is elided only where the plan's
  own read set says nothing reads that target in the frame, which is why Complementary removes nothing.
- The Vitrail suite passes (267 tests), including two assertions updated for the changed call shape - the
  capability check and the chain-written pair - and a new test pinning the label flow and the single counting
  site. The shadow-chain road was then exercised end to end through the fixture above.
- Every arm reported Metal 3 and its target through the harness's guards, and the scene counters agree with the
  corpus to the tenth (`loadedMiB 231450.5` on MakeUp, `321.8` a frame on Complementary).

## Decision

**REJECTED - eliding the unread copybacks, as a default.** Correct, counter-confirmed, and 17.6 or 2.6 MiB a
frame; the one session that resolves a frame time puts it at 1.1 per cent. The switch stays off by default.

**NOTHING TO OPTIMISE - C5.** Zero feedback snapshots across the corpus, with the counter in place for the pack
that needs one.

**NO CANDIDATE - C6.** Every chain has the reader that asked for it; the shadow pair follows the pack's own
declaration.

**KEPT - the labelled census.** A chain's target is now in the line, which is what makes C6's question answerable
at all.

## Residual

- **C4's wall on two of three packs is UNRESOLVED**: Complementary's repeat pair is 20.6 per cent apart and
  Photon's 8.4, so neither can carry a verdict - the same machine state that limits every frame-time claim in
  this programme.
- **C5 is not measured where it costs anything.** No corpus pack takes a feedback copy, so its price on a pack
  that does (Sildur's water) is unknown.
- **The copybacks' *sizes* were derived from the counter** (17.6 MiB over 2 copies, 2.6 over 3) rather than read
  per target; which of the ten Photon targets the three small ones are is not said by any line.
- **C7 remains**: the attachment-traffic switch (`elideTargetTraffic`) on this corpus, which the plan wants
  before it is closed.

## Next

1. **The entity/interval re-measurement**, which needs a machine that holds one state for a session.
2. **Track C is otherwise complete**: C1 and C3 in the first section, C2 in the second, C4/C5/C6 in the third
   and C7 in the fourth, all on the same corpus.

---

# C3 completed - the other three scales

Starting Metallum SHA: `74ee07f`
Ending Metallum SHA: `74ee07f` + this round's documents
Starting Vitrail SHA: `bb5db273`
Ending Vitrail SHA: `bb5db273`

## Question

C1 and C3 measured Complementary at 55 per cent and found exactly one pass a frame still at the window's own
size, which is the interface's, with every world pass following the scale. The C3 section left the other three
scenes as completeness work; this is it, three sessions at 55 per cent on a 1920x1200 window.

## The pass tables

Shadow map's own passes first, then the window's size, then the world's. Counts are per 600-frame window.

```
scene              scale   4080^2      2048^2   1920x1200        1056x660   528x330 or smaller
no-pack             100        -           20     5400 (9 a frame)     -            -
no-pack              55        -           21     5400 (9 a frame)     -            -
MakeUp              100      900           81    10200 (17 a frame)    -            -
MakeUp               55      900           65      600 (1 a frame)   9600 (16)       -
Complementary       100        -          999    12000 (20 a frame)    -        960x600: 600
Complementary        55        -          983      600 (1 a frame)  11400 (19)   528x330: 600
Photon              100        -         1356    16200 (27 a frame)    -      960x600:1200, 480x300:600
Photon               55        -         1300      600 (1 a frame)  15600 (26) 528x330:1200, 264x165:600, 192x108:600
```

## What it answers

**Every world pass follows the scale on every pack that has one**, and the pass at the window's own size is
**one a frame** in all three: 1920x1200 falls from 17, 20 and 27 passes a frame to **exactly 1** on MakeUp,
Complementary and Photon, while 1056x660 (55 per cent of the window) appears at 16, 19 and 26. That one pass is
the interface's - the GUI and the final blit are drawn at the window's size by design - so **C3's hypothesis of a
heavy world pass left at native resolution is REJECTED on the whole corpus**, not only on the pack it was
rejected on first.

**The shadow map is not scaled and is not expected to be.** MakeUp's 4080x4080 is 900 passes at both scales;
Complementary's 2048x2048 is 999 against 983 and Photon's is 1356 against 1300, and in both rows the whole
difference is the **load-time mip cascade** (99 against 83, 156 against 100) rather than the map: the map's own
passes are 900 and 1200 at both scales, which is the opaque plus translucent pair of C2's decomposition. A shadow
map is sized by the pack's own shadow distance and multiplied by the player's shadow-map scale, both separate
settings from the render scale, and the plan lists this case itself.

**Without a pack there is no scaled world at all.** `--no-pack --renderscale 55` draws the same table as
`--no-pack --renderscale 100` - 5400 passes at 1920x1200 and no 1056x660 anywhere - so the render scale is a
**shader-pack path**: with no pack the game's own frame is drawn at the window's size and the setting has nothing
to scale. That is worth knowing for the product direction the plan ends on, where the scale is offered as a
pack-side quality setting rather than a global one.

**And one fixed-size target is visible on Photon**: 512x512 at 756 passes at 100 per cent and 700 at 55, against
128x128 and 256x256 which follow the cascade. It is a pack-declared target at a size the pack named rather than
one the engine scaled, which is the second half of what C3 set out to check - "whether any *pack-declared* target
is pinned at a size by the pack's own declaration rather than by the engine's scale" - and the answer is yes, and
by declaration rather than by accident.

## Correctness and one trap

- The three arms are 600-frame windows, Metal 3, the frozen `PerfWorld`, and two of them were **refused by the
  harness's target guard** (`--expect-target 1920x1200`): at a render scale below 100 per cent **both** of the
  engine's target lines report the *scaled* world - `The world renders at 1056x660` and `Drawing ... at
  1056x660` - so the expectation for a 55 per cent arm is the scaled size and not the window's. The guard was
  right and the expectation was wrong; the arms' counters are unaffected, and the rule is written into
  `docs/performance-testing.md`.
- Nothing was changed in either repository for this measurement.

## Decision

**REJECTED - C3's hypothesis, on the whole corpus.** No world pass is left at native resolution by the scale.
The one pass at the window's size is the interface's, the shadow map is sized by the pack's own settings, and
the only pack-declared fixed size found is Photon's 512x512, which the pack asked for by name.

## Residual

- **Solas**, the fifth scene the plan names for C3's family of questions, is still not staged on this machine.
- **No-pack at a render scale is a no-op**, measured here - and whether that is the *intended* product behaviour
  for the MetalFX path without a pack is a product question rather than a measurement one, and it is not asked.

## Next

1. **The entity/interval re-measurement**, which needs the machine to hold one state for a session.
2. **E4, dynamic resolution**, last and only if 1 and the shadow interval's second pack are settled.

---

# C7 - the attachment traffic

Starting Metallum SHA: `10e7021`
Ending Metallum SHA: `10e7021` + this round's documents
Starting Vitrail SHA: `bb5db273`
Ending Vitrail SHA: `bb5db273`

## Question

The plan asks for `elideTargetTraffic` to be re-measured across the corpus rather than on one scene, and it
names the verdict in advance: **if the loaded and stored mebibytes fall a long way and the wall never moves,
stop.** The switch is the earlier programme's, off by default, and it answers two separate questions at once - a
pass that writes every pixel of an attachment has no use for what stood there (the load becomes a fill), and a
target nothing reads afterwards has no use for what it leaves (the store does not happen).

## Instrument

The frame probe's `loadedMiB`, `storedMiB` and `depthAttachments`, which are exact counts of attachment traffic,
and the per-program load-time line that already says how many of a pass's targets nothing reads afterwards:

```
nothing reads what it leaves in 1 of its 2 targets      MakeUp (one program), Photon (one program)
nothing reads what it leaves in 2 of its 2 targets      MakeUp (another program)
nothing reads what it leaves in 2 of its 3 targets      Complementary (one program)
```

Three arms a pack, one session each: `plain`, `elide` (`-Dvitrail.elideTargetTraffic=true`), `plain-b`.

## A/B

```
scene           arm      ms/f     loadedMiB/f          storedMiB/f        depthAtt/f
MakeUp          plain    6.717    385.8                461.4              7.5
                plain-b  6.730    385.8                461.4              7.5     (0.2 % apart)
                elide    6.644    319.8  -66.0 -17.1%  435.0  -26.4  -5.7%  7.5
Complementary   plain    8.286    321.8                460.1              7.5
                plain-b  9.834    342.2                480.4              7.9     (drifted: structure differs)
                elide    7.713    216.1 -105.7 -32.9%  442.2  -17.9  -3.9%  7.5
Photon          plain   11.769    415.5                535.4              8.0
                plain-b 11.813    415.5                535.5              8.0     (0.4 % apart)
                elide   11.808    257.4 -158.1 -38.1%  526.7   -8.7  -1.6%  8.0
```

**The traffic falls a long way and the frame does not move.** Two of the three sessions are clean - their own
reference pairs agree to 0.2 and 0.4 per cent - and in them the load traffic falls **17.1** and **38.1 per cent**
while the frame time moves **-1.1 per cent** and **+0.3 per cent**, both at or inside this programme's
resolution floor. The third pack's session drifted so far between its references (18.7 per cent, and its
structure with it) that its frame time carries no verdict at all; its traffic, which is a count, still does:
**-32.9 per cent**.

The load and the store are not the same size and the reason is in the mechanism rather than in the packs: a
full-screen pass that overwrites its attachment can always drop the load, so the load saving is spread over every
such pass, where the store can only be dropped for a target nothing reads afterwards, which the load-time lines
above say is one or two targets of one program. Photon's **158.1 MiB a frame** of load against 8.7 of store is
that asymmetry at its widest.

## Correctness

- Nothing changed: the switch is the earlier programme's, off by default, and neither repository was touched for
  this measurement.
- The traffic counters are exact and agree with the corpus to the tenth (`385.8` loaded on MakeUp, `415.5` on
  Photon, `321.8` on Complementary), so the arms drew the same frame.
- Every arm reported Metal 3 and its target through the harness's guards; the drifted Complementary session was
  caught by the same guard that refuses one, and is reported as drifted rather than used.

## Decision

**STOP - and the switch stays off by default.** The plan's own stop rule for this item fires exactly: a large fall
in loaded and stored mebibytes with no movement in the wall. Correct, counter-confirmed, and not where a frame's
time is - on three packs rather than the one the earlier programme had, with two of the three sessions clean
enough to resolve a one per cent difference and neither showing one.

**What this closes.** With C1 and C3 (the corpus and the scale audit), C2 (shadow), C4/C5/C6 (copies, feedback,
chains) and C7 (attachment traffic), the plan's phase 53 list - shadow, full-resolution pass, copy, attachment
traffic, mipmap, feedback - is measured end to end on this corpus, and success criterion 8 is met for all six:
none of them is guessed at any more, and each has a data reason for the decision it carries.

## Residual

- **The Complementary frame time is UNRESOLVED** for this item (its session drifted), so C7 has two clean packs
  and one drifted - the stop rule fires on the two, and the third's traffic alone is reported.
- **The elision is not separated into its load half and its store half by any arm**: one switch does both, and a
  future reader wanting to know which half buys what would need one switch each.
- **Solas, the fifth scene the plan names for C7, is not in the corpus** - the pack has never been staged on this
  machine, and the plan's own rule is that a new pack extends the corpus rather than redefining it.

## Next

1. **C3's remaining three scales** and the **entity/interval re-measurement**: the scales are done in the next
   section and the walls are closed in the C2 section.
2. **Track F's recorded candidate** - an on-disk Metal pipeline cache, then recorded at 0.26-1.6 s a launch.
   **That figure was the wall of the warm-up's parallel job and the archive is REJECTED on its measured size**
   in `docs/startup-and-cache.md` F4: a launch asks the Metal compiler for 874 things, 36.6 ms, worst 0.29 ms.

---

# Where this document stands

Track C is complete on one corpus and one protocol. C1 built the structural census, C3 asked which passes a
render scale leaves behind and answered it on all four scenes, C2 decomposed the shadow stage and settled both of
its wall questions by repetition, C4/C5/C6 measured the copies, the feedback targets and the chains, and C7 took
the attachment traffic across the three packs. Every figure in it is a count, a rate or a minimum over repeats,
and every verdict carries either a mechanism that reproduces in an independent counter or a named reason it could
not be resolved. The one thing Track C leaves open is not a measurement: it is whether the shadow map's default
should move from one kept frame to the selector's two, worth 5.7 and 3.0 per cent on the two packs where the
reuse applies, which is the owner's to decide because it changes what every player gets without asking.
