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
                                      measured (redundant binds are 0.1-0.3 % of a frame); A4/A5 NOT MEASURED
                                      and closed with the rest of the CPU round: the frame is GPU-bound (the
                                      accelerator reads 100 % in every arm's own trace) and the native call
                                      surface A1 priced is 1.5-4 % of a frame, so an arena or a wider submit
                                      window has no measured hot path behind it (rule F of section 5)
Track B  Vitrail CPU / runtime        B1 DONE (docs/vitrail-cpu-performance.md): the frame is 13-17 % CPU
                                      and allocates 71-183 KiB a frame; JFR rejected by measurement. B2-B6 are
                                      closed with the CPU round by the plan's own exit condition (two
                                      candidates under 1 %: A2/A3's redundant binds and D1's bridge), and the
                                      allocation rate is named rather than chased: at 27-42 MB/s over a frame
                                      the engine is GPU-bound in, no evidence puts it on the frame's critical
                                      path. Reopening needs a profiler that shows it, which JFR is not here
Track C  Vitrail GPU / shader work    C1 corpus DONE and C3 answered (docs/vitrail-gpu-performance.md): the
                                      frame's GPU work is the terrain's indirect draws and attachment traffic;
                                      at 55 % exactly one pass a frame stays at the window's size (the
                                      interface), so C3's "heavy pass left full-res" is REJECTED for that
                                      pack. C2 DONE for the two packs where reuse applies, in the same
                                      document: the shadow map decomposes exactly (300 opaque + 600
                                      translucent passes a 600-frame window), the shipped reuse of the map is
                                      worth 9.8 % on MakeUp, the selector's own maximum is worth another
                                      5.7 % there and is UNRESOLVED on Complementary, so raising the default
                                      interval is DEFERRED; the entity family is measured (one extra full-size pass and 129 MiB
                                      of attachment traffic a frame, wall unresolved) and the voxel family is
                                      NOT MEASURED. C4/C5/C6 DONE in the same document: the frame-end
                                      copybacks are 6/4/10 targets a frame (2/0/3 of them read by nothing),
                                      eliding the unread ones removes exactly those and is worth 17.6 MiB a
                                      frame on MakeUp and 2.6 on Photon for about 1 % of a frame where a
                                      session can resolve one - REJECTED as a default; feedback snapshots are
                                      ZERO on every corpus pack; every mip chain has the reader that asked
                                      for it, and the census now says which target. C7 DONE: the attachment
                                      traffic falls 17-38 % with the elision switch and the wall does not move -
                                      two clean sessions at -1.1 % and +0.3 % - so the plan's own stop rule fires
                                      and the switch stays off. Phase 53's list is measured end to end
Track D  Vitrail <-> Metallum         D1 DONE (docs/bridge-overhead.md): 0.07-0.70 % of the wall, resolution
                                      already cached (2 lookups a session) - MEASURED-BUT-NOT-WORTH-IT, and
                                      with the binding census it closes the CPU micro-optimisation round. D2/D3
                                      are closed by the same census rather than by a change: the per-frame
                                      discovery D2 wants removed is two lookups a session, so there is nothing
                                      left to pre-resolve on this seam
Track E  MetalFX spatial              E1 pinned (DONE); E2 ladder DONE (docs/metalfx-performance.md):
                                      55-67 % buys 1.3-1.8x on the two GPU-heavy packs and 1.19x on the
                                      lightest, with the driver's GPU time falling in step; the pack-selection
                                      writer that spoiled 2 of 21 cells is IDENTIFIED and FIXED (the Sodium
                                      binding applied the option's file-format default over the player's
                                      stored scale - a player-visible defect, not only a measurement one)
Track F  shader/pipeline/startup      F1/F2/F3 DONE (docs/startup-and-cache.md): a warm launch compiles
                                      NOTHING (module cache 574/574, translation 45/45) and a cold one builds
                                      187 units in 1747 ms plus 563 ms of translating; a distinct input is built
                                      once and read 3.05 times a load; 105 of the two packs' inputs are the same
                                      input; a warm load is 8 s against a cold 11-12 s on MakeUp (3 cold arms, 16 warm). What
                                      no cache covers is the Metal pipeline state, remade every launch at
                                      0.26-1.6 s - RECORDED as the next candidate, not implemented; F4 not started
Track G  measurement infrastructure   G1 DONE: tools/vitrail-performance-report.py writes a session's arms as
                                      JSON - repositories, machine, display mode, target, pack, scale, wall and
                                      GPU distribution, CPU and allocation stats, the native call census, the
                                      structural census and the engine's one-a-second censuses - with
                                      tools/ci-performance-report.py holding it against a fixture built from a
                                      real window's lines, mutations included. G2/G3 standing (the harness, the
                                      region reader, the census lines, the command-generation guard, the
                                      reference-arm and minimum-over-repeats rules);
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
- A removal arm changes the frame's structure by design, so the comparison's scene-drift guard refuses its
  session. That refusal is read as "the arms differ, and by this much", and the difference is checked against the
  mechanism rather than against a tolerance (docs/performance-testing.md).
- Every session carries a reference arm of its own and repeats it, and the wall is read as the **minimum over
  repeats** because the machine's noise is one-sided. Measured while collecting C2: identical structure, identical
  configuration, 47 per cent apart between arms - and one configuration reproduced to 0.4 per cent across five
  arms in four sessions. A configuration whose repeats disagree by more than the effect is UNRESOLVED, not
  averaged, and a candidate with an unresolved second pack is not shipped.
- An arm states the command generation it ran in (`--expect-execution`), because the generation is the game's own
  stored setting and a whole C2 session was collected on Metal 4 against a Metal 3 corpus without one counter
  showing it.
- **Metal 4 stays verifiable while it is frozen.** All twelve of this repository's contracts pass on the head
  that carries everything above - `ci-architecture`, `ci-metal4-provider`, `ci-metal4-report`,
  `ci-metal4-cold-probe` and `ci-metalfx` among them - and Vitrail's 267 tests pass on its own head, which is
  what section 61's eleventh criterion asks for and what a shared-code change has to be re-checked against.
```

## What is left, in the order the plan asks for it

```
1. THE OWNER'S DECISION      the shadow map's default, and the one product question this programme
                             produced. `ShadowAmortisation.DEFAULT_FRAMES` is 1 kept frame and the
                             selector already offers 2, so raising the default changes what every
                             player gets without asking - section 59's fourth pause. The measurement
                             is done on both packs where the reuse applies: interval 2 is worth
                             5.7 per cent on MakeUp and 3.0 on Complementary, structure exact in the
                             same arms (the shadow map's own passes fall from 900 to 800 a window on
                             MakeUp and from 1000 to 897 on Complementary, and the engine's own line
                             reads 300 draws in 600 frames against 200). What is missing is an eye:
                             the value 1 is inherited from a judgement about a map kept WHOLE, which
                             the movers being drawn back in retired, and nobody has looked at the
                             ground's three-frame lag since.
2. E4, dynamic resolution    only after 1, and only with hysteresis, cooldown, step limits and a
                             stability window, as section 36 requires.
```

Everything else in the plan's track list is measured and carries a decision: A1-A3, B1 with B2-B6 closed
by the CPU round's exit condition, C1-C7 with both of C2's wall questions settled by repetition (the entity
family at 0.13 per cent and Complementary's interval at 3.0, eight arms each), D1 with D2/D3 closed by it,
E1/E2, and F1-F4. All twelve of this repository's contracts and Vitrail's 267 tests pass on this head.

**Track F is complete**, and its last item closed the plan's largest recorded candidate. An on-disk Metal
pipeline cache was recorded at F1/F3 as "0.26-1.6 s a launch, the largest measured startup item left"; F4
measured what a launch actually asks the Metal compiler for - **874 calls, 168 functions and 706 pipeline
states, 36.6 ms in total, worst single 0.29 ms** - and the archive is REJECTED on that size (rules G and E of
section 5). The 0.26-1.6 s was the wall of the warm-up's parallel job, which contains the translation and
module building the module cache already covers and which the load never awaits, `FamilyWarmup.awaitAll` being
called once, at client shutdown. F1's compile count, compile ms and worst spike are answerable for the first
time, which is what that item was holding open.

## What each new document owns

```
docs/metal3-performance-round2.md   Track A: the native-call census and what it names
docs/vitrail-cpu-performance.md     Track B (to be written with B1)
docs/vitrail-gpu-performance.md     Track C: the corpus (C1), the scale audit (C3) and the shadow
                                    stage (C2)
docs/bridge-overhead.md             Track D (to be written with D1)
docs/startup-and-cache.md           Track F: the cache census (F1), the reuse count (F2) and the cold/warm load (F3)
docs/metalfx-performance.md         Track E (to be written with E2)
docs/performance-testing.md         the harness, the session rules and the picture evidence
docs/metal3-performance-report.md   the first Metal 3 round, still the reference for its own conclusions
docs/metal4-full-frame-report.md    Metal 4, frozen, kept as the record of what it proved
```
