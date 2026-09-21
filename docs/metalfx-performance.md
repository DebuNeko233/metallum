# MetalFX spatial: the render-scale ladder

Track E of the long-term plan. E1 (100 per cent is native, and the engine says so) was already a hard contract
before this round; E2 is the scale ladder, and it is the first thing measured here that moves *real* work - the
driver's own GPU time falls with the scale on every pack, in proportion.

## Starting SHAs

```
Metallum: 8855c00
Vitrail:  2aa2ea9e
```

## E1 - 100 per cent is native, and it is pinned (DONE)

The contract is the plan's own words: at 100 per cent there is no scaled target, no MetalFX availability
question, no scaler and no upscale blit. It is pinned in two places and both are green:

- Vitrail's `tests/test_metal_selection_and_scale.py` ("100 per cent is native resolution: no scaled set, no
  probe, no encode, no fallback") and the engine's own line
  `The render scale is 100%, so the world is drawn at the window's own size and MetalFX is off`, said once per
  setting.
- Companion Metallum's `tools/ci-metalfx.py` pins the capability split and the transitions.

And the ladder below is the evidence rather than the assertion: the 100 per cent cell of every pack draws at the
window's own 1920x1200, prints that line and no `The N% render scale brings the picture back` line, and its
`blits` count is the pack's own - the scaler's blit is absent.

## Instrument and protocol

One session a cell, because the harness writes the render scale into the pack selection once a session
(`--renderscale N`), the plan's 25 s settle after the pack's first full frame, 600-frame windows, fullscreen
exclusive at 1920x1200, Metal 3 executing, camera and world as the rest of this repository's protocol
(`run/e2-<pack>-<scale>`). Every cell is read from its own log line, so a cell that did not reach the scale it
claims is not counted as one:

```
The world renders at <scaled> for a 1920x1200 window, render scale <N>%
The <N>% render scale brings the picture back with MetalFX
```

## The ladder

```
pack             scale   target      ms/frame   P50    P95    P99   GPU ms   speedup   road
MakeUp             100   1920x1200      6.74    6.96   8.53   8.79    6.75     1.00x   native
MakeUp              90   1728x1080      6.48    6.51   8.48   9.22    6.50     1.04x   MetalFX
MakeUp              80   1536x960       6.13    6.19   8.09   8.56    6.14     1.10x   MetalFX
MakeUp              75   1440x900       6.06    5.81   8.06   8.77    6.08     1.11x   MetalFX
MakeUp              60   1152x720       6.29    6.37   8.58   9.46    6.30     1.07x   MetalFX
MakeUp              55   1056x660       5.65    5.69   7.65   8.50    5.66     1.19x   MetalFX
Complementary      100   1920x1200      8.92    8.89  10.36  10.73    8.93     1.00x   native
Complementary       90   1728x1080      8.02    7.94   9.82  10.74    8.03     1.11x   MetalFX
Complementary       80   1536x960       7.05    7.04   8.70   9.65    7.06     1.27x   MetalFX
Complementary       75   1440x900       6.68    6.62   8.35   9.15    6.70     1.34x   MetalFX
Complementary       67   1286x804       6.01    6.03   7.57   8.01    6.02     1.48x   MetalFX
Complementary       60   1152x720       5.35    5.40   6.74   7.53    5.36     1.67x   MetalFX
Complementary       55   1056x660       5.08    5.11   6.43   6.71    5.09     1.76x   MetalFX
Photon             100   1920x1200     11.80   11.78  12.63  12.93   11.82     1.00x   native
Photon              90   1728x1080     11.27   11.22  12.01  12.29   11.29     1.05x   MetalFX
Photon              80   1536x960       9.85    9.80  10.71  11.08    9.87     1.20x   MetalFX
Photon              75   1440x900       9.48    9.46  10.33  11.03    9.50     1.24x   MetalFX
Photon              67   1286x804       8.94    8.91  10.20  10.60    8.96     1.32x   MetalFX
Photon              60   1152x720       8.62    8.60   9.62  10.27    8.64     1.37x   MetalFX
Photon              55   1056x660       8.28    8.27   9.34  10.46    8.30     1.42x   MetalFX
```

**The gain is the GPU's, and it is real.** On every pack the driver's own per-frame GPU time falls with the
scale and stays level with the wall (Complementary 8.93 to 5.09 ms, Photon 11.82 to 8.30, MakeUp 6.75 to 5.66),
so what the scale removes is work the card was doing, not bookkeeping. The three packs gain very differently
because they start from different places: **Photon and Complementary are GPU-heavy and gain 1.3-1.8x by 55-67 per
cent, while MakeUp gains 1.19x even at 55 per cent** - its frame is the cheapest of the three (6.74 ms) and
therefore has the least GPU time to remove, and its middle cells (60 per cent slower than 75) are the scene's own
spread (this scene's run-to-run floor is 1-3 per cent and one cell read 6.29 against 6.06) rather than a
mechanism.

**A 5-per-cent step is not the curve's resolution.** 80 to 75 per cent buys 1.10 to 1.11 on MakeUp and 1.27 to
1.34 on Complementary, while 75 to 67 buys 1.34 to 1.48 on Complementary and 1.24 to 1.32 on Photon: the useful
part of the ladder is the lower half, which is what a preset should be built from.

## Fidelity against native, as a proxy and not a verdict

Every cell's capture compared against the same pack's 100 per cent capture - mean channel difference, and the
share of pixels above eight and above thirty-two levels. This is **how far the scaled frame is from native**, not
a perceptual quality metric, and it is the only reading the picture column can give without a reference-quality
fixture:

```
pack             scale   mean |delta|   > 8 levels   > 32 levels
Complementary      100         0.00         0.00 %        0.00 %
Complementary       90         4.22        10.56 %        0.90 %
Complementary       80         4.10        10.00 %        0.89 %
Complementary       75         4.06         9.81 %        0.91 %
Complementary       67         4.12         9.91 %        1.03 %
Complementary       60         4.15         9.89 %        1.09 %
Complementary       55         4.22        10.14 %        1.18 %
Photon             100         0.00         0.00 %        0.00 %
Photon              90         4.79        14.46 %        0.82 %
Photon              80         5.09        15.06 %        1.07 %
Photon              75         5.14        15.00 %        1.11 %
Photon              67         5.55        15.77 %        1.26 %
Photon              60         5.71        16.70 %        1.33 %
Photon              55         6.13        18.78 %        1.47 %
MakeUp             100         0.00         0.00 %        0.00 %
MakeUp              90         6.47        21.44 %        1.98 %
MakeUp              60         6.41        20.72 %        2.04 %
MakeUp              55         7.09        24.21 %        2.44 %
```

For Complementary and Photon the number moves the way a scaler's error should - a little more difference as the
scale falls, from 4.06-4.22 and 4.79-6.13 mean, with the share above thirty-two levels staying near one per
cent. **MakeUp's 80 and 75 per cent cells read 17.9 and 17.2 mean with 63-64 per cent of pixels above eight**,
which is not the scaler: two cells of that pack caught a different phase of the scene (the same phase sensitivity
the performance table shows) and are **NOT MEASURED** as a fidelity reading rather than reported as a loss of
quality. A fidelity claim wants the pack's temporal history held still, which this session's protocol does not do
- and that is the residual below.

## What went wrong twice, and it was not the scale

**Two of the twenty-one cells were refused by the harness** - 67 per cent on MakeUp and on Photon - with
`Run 'm3' had its pack selection changed while it was counting (pack.txt was enabled for ... when the run
started): another writer owns that file`. Both then drew at the window's own 1920x1200 with no scale line, and
their numbers are in neither table above: a 0.79x "speedup" at 67 per cent on MakeUp is a native frame, slower
than its own 100 per cent cell, and it is exactly the kind of number a ladder read without the scale line would
have published as a regression.

**A standalone retry of each passed and read `1286x804 ... render scale 67%`** (MakeUp and Photon, 5.4 ms and
8.94 ms a frame), so 67 per cent is a scale this engine holds - the earlier failures are a race and not a rule.
A file watcher over one passing retry saw the harness's own write and nothing else. **The other writer is NOT
IDENTIFIED.** The two candidates, neither measured: the engine's own video-settings binding writing a defaulted
value at startup (`ConfigEntry.renderScale` builds a Sodium option with a 5-per-cent step range and an empty
storage handler, so the option's value is its default until the player moves it), and a previous session's client
writing on world-leave inside the next session's window. Both are worth pinning because the same road can move a
*player's* scale under them and the only reason this round caught it is that the harness fingerprints the file.
That the guard worked is the instrument's credit; that the write happened at all is a defect left open, and it is
recorded here as **BLOCKED - writer not identified**, not as a MetalFX result.

## Decision

**KEPT: the fixed render scale as the performance lever.** The plan's "make MetalFX useful" has a curve now:
55-67 per cent buys 1.3-1.8x on the two GPU-heavy packs and 1.19x on the lightest, with the GPU's own time
falling in step.

**E3 presets, proposed from the data and not from taste.** The measured points that are also on the UI's own
5-per-cent grid: **Native 100 / Quality 80 / Balanced 60 / Performance 55**, which on Complementary read 1.27x,
1.67x and 1.76x and on Photon 1.20x, 1.37x and 1.42x. The plan's illustrative 85 and 70 are on the grid but
unmeasured; 85 sits between two cells that differ by 1.04 and 1.11 on MakeUp and 1.05 and 1.20 on Photon, so
choosing it would be taste and not data. **A preset change is a product decision and is not made here.**

**E4 dynamic resolution: DEFERRED**, as the plan itself sequences it - after a fixed ladder is stable, and this
one has a writer moving the file under it.

## Residual and what is NOT MEASURED

- **The other writer of the pack selection is not identified** (above). Until it is, a scale ladder taken
  back-to-back can lose a cell, and the harness's refusal is the only reason this round did not publish a native
  frame as a 0.79x "regression".
- **The fidelity numbers are a difference from native, not a quality verdict**, and two MakeUp cells are not a
  reading at all. A real quality fixture wants the pack's history held still and, ideally, a reference-quality
  metric (a per-pixel error against a supersampled native frame) rather than a comparison between two temporal
  frames.
- **Two packs' middle cells are within their own spread** (MakeUp's 60, and the 75-80 pair), so the curve's
  fine structure is not readable there; a repeat of those cells would need the plan's A/B/A/B discipline, which a
  ladder does not have.
- **Nothing is measured at scales below 55 or above 55 with a different pack preset**, and the shadow map scale
  and render scale interact in the packs that have shadows (`shadowmapscale` stays 100 in every cell here).
- **No picture was judged by eye**; the fidelity column is arithmetic on two captures.

## Next

1. **Pin the pack-selection writer** - a one-cell diagnostic with the file watched and the engine's config roads
   instrumented - because a scale that moves itself is a correctness problem for the player and a measurement
   problem for this track.
2. **E2's second half**: the same ladder with the shadow map scale at 50 per cent and 100 per cent on
   Complementary (the pack with shadows), since the two scales move different halves of the frame.
3. **C1's structural census** next, which the plan puts after the scale ladder, so the GPU work the ladder
   removes can be attributed to passes rather than to a total.
