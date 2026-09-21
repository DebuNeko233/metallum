# The long-term performance plan, as adopted

This repository is now worked to the long-term plan whose text is the goal it was handed: **Metal 4 is frozen as
an experimental backend, and the engineering moves to Metal 3, Vitrail's CPU and GPU, the Vitrail-to-Metallum
boundary, MetalFX and startup latency.** This file records the policy, the tracks and where each one stands, so
the next session reads one page instead of re-deriving it.

## Metal 4 is frozen, not deleted

Metal 4 keeps its provider, its frame path, its argument tables, its residency set, its MetalFX road, its
architecture contract and its deterministic smokes, and a developer can still run it with
`-Dmetallum.execution=metal4`. What stops is *development*: presentation pacing, ring-depth tuning, pass
stitching, barrier narrowing, argument-table micro-optimisation, compute encoder reuse, Blaze3D API completeness
and the cold-probe hunt are closed as active work.

It may still be changed for: a crash or a GPU fault, a corruption, a correctness regression, an SDK or macOS
change that stops it compiling or launching, an architecture-contract failure caused by a shared or Metal 3
change, or a deterministic fixture that regresses. A Metal 4 *performance* finding is recorded in
`docs/metal4-full-frame-report.md` and not acted on unless the plan is reopened.

## The tracks, and where each stands

```
Track A  Metal 3 performance          A1 census DONE (docs/metal3-performance-round2.md); A2/A3 rejected as
                                      measured (redundant binds are 0.1-0.3 % of a frame); A4/A5 not started
Track B  Vitrail CPU / runtime        B1 DONE (docs/vitrail-cpu-performance.md): the frame is 13-17 % CPU
                                      and allocates 71-183 KiB a frame; JFR rejected by measurement; the
                                      per-road allocation attribution is the live question
Track C  Vitrail GPU / shader work    C1 corpus DONE and C3 answered (docs/vitrail-gpu-performance.md): the
                                      frame's GPU work is the terrain's indirect draws and attachment traffic;
                                      at 55 % exactly one pass a frame stays at the window's size (the
                                      interface), so C3's "heavy pass left full-res" is REJECTED for that
                                      pack; C2/C4-C7 not started
Track D  Vitrail <-> Metallum         D1 DONE (docs/bridge-overhead.md): 0.07-0.70 % of the wall, resolution
                                      already cached (2 lookups a session) - MEASURED-BUT-NOT-WORTH-IT, and
                                      with the binding census it closes the CPU micro-optimisation round
Track E  MetalFX spatial              E1 pinned (DONE); E2 ladder DONE (docs/metalfx-performance.md):
                                      55-67 % buys 1.3-1.8x on the two GPU-heavy packs and 1.19x on the
                                      lightest, with the driver's GPU time falling in step; the pack-selection
                                      writer that spoiled 2 of 21 cells is IDENTIFIED and FIXED (the Sodium
                                      binding applied the option's file-format default over the player's
                                      stored scale - a player-visible defect, not only a measurement one)
Track F  shader/pipeline/startup      F1-F4 not started
Track G  measurement infrastructure   G1-G3 partly standing (the harness, the region reader, the census lines);
                                      G4 (profiler stop rule) is policy, recorded below
```

## The benchmark discipline this repository now holds to

- Four scenes: no-pack, MakeUp-UltraFast-9.5e, ComplementaryReimagined r5.9.1, Photon v1.3b. A new pack extends
  the corpus and does not redefine the old baselines.
- Fixed world, dimension, camera, time, weather, entity/particle/cloud state, target, window state, pack and
  preset, render scale, and a 25 s warmup before a 600-frame window.
- Alternating arms - A, B, A, B at least - and the window's tick sampling recorded beside its frame count.
- Thresholds: under 1 % is noise, 1-2 % needs repetition and mechanism, 2-5 % is a real candidate, 5-10 % is high
  value, above 10 % is the main item. A structural correctness fix is not subject to the threshold.
- Every candidate answers: which mechanism, how much real work removed, which counter falls, whether the wall
  falls, whether a picture changed, whether the other generation changed, and whether the complexity is worth it.

## The measurement rules learned the hard way, and now standing

```
- A launch may not move the owner's display. Fullscreen switches the display's mode; the harness records the
  mode per session, checks it after every arm, puts it back when an arm left it moved, restores the instance's
  own options at the end, and recovers from a session that was killed. The owner accepted the switch during a
  measurement arm and chose windowed for everything else. See docs/performance-testing.md.
- A measurement arm runs exclusive fullscreen, because a non-exclusive fullscreen client lives in its own Space
  and a photograph of the display is then of whatever Space is current.
- An arm whose client paused is refused, not annotated: a paused client behind another application reads as a
  slow engine (measured: 100.00 ms a frame at exactly two client ticks a frame).
- A profiler that crashes the JVM or changes the frame is not used for a verdict; an explicit census replaces it.
- A counter that only counts cannot say whether a road is a cost. The A1 census prices the road it names.
```

## What each new document owns

```
docs/metal3-performance-round2.md   Track A: the native-call census and what it names
docs/vitrail-cpu-performance.md     Track B (to be written with B1)
docs/vitrail-gpu-performance.md     Track C (to be written with C1)
docs/bridge-overhead.md             Track D (to be written with D1)
docs/metalfx-performance.md         Track E (to be written with E2)
docs/performance-testing.md         the harness, the session rules and the picture evidence
docs/metal3-performance-report.md   the first Metal 3 round, still the reference for its own conclusions
docs/metal4-full-frame-report.md    Metal 4, frozen, kept as the record of what it proved
```
