# Vitrail's startup: what a load serves, what it builds, and what it still pays for

Track F of the long-term plan. F1 asks for the cache census - module, translation, function and pipeline
hit/miss, compile count, compile ms, the worst spike; F2 asks whether anything is compiled more than once for
the same source, defines, formats, layout and specialisation; F3 asks whether the second and third load of a pack
are cheaper than the first. This is all three, from three sessions of four arms each, plus the harness switch
that made a cold load possible at all.

Track F is also the one track the machine cannot spoil: a load's counts are exact and its compile times are
CPU-side, so the 47 per cent arm-to-arm spread that limits Track C's frame times does not enter here.

## Starting SHAs

```
Metallum: 6ac62a6 + this round's load census and --cold-cache
Vitrail:  5b498e70 (unchanged: nothing in the engine was changed for this)
```

## Question

How much of a load is compiling, how much of it is already on disk, does anything get compiled twice, and how
much does the second load save? The plan's Track F exists because startup is the part of the experience no
frame-time measurement sees, and success criterion 9 asks for a quantified pipeline-cache result.

## Instrument

Three lines the engine already prints, and one switch the harness did not have.

```
Module cache: N units served, M built by the compiler, N and M since this launch, X MB in <dir>
A of B leftover pipelines compiled ahead of their first draw, C ms of background work, translations included
With the families in, flattening the chain's units cost D ms over E of them with F more handed back,
  translating cost G ms over H translator calls with I programs served from the translation cache and
  J translated, and making modules cost K ms over L modules, shaderc and SPIRV-Cross together
[hh:mm:ss] ... This pack's first full frame opened
```

**`--cold-cache` is the switch that was missing.** Both caches live in the instance
(`run/vitrail/modules/<build>` and `run/vitrail/translations/<build>`), keyed on the shader text and the build, so
a session that does not remove them measures whatever an earlier session of the same build left behind. That is
readable in the corpus itself: under one build, `no-pack` built 6 units, `MakeUp` built none (an earlier session
had filled it), `Complementary` built **86** - the first load of that pack under that build - and `Photon` built
none. What the corpus never had was a load with the caches removed on purpose, and without one the cold number
appears only by accident, in whichever pack happens to be first. The flag removes both directories before the
session's first arm and prints what it removed (`19M, 672 file(s)` and `16M, 298 file(s)` the first time); every
arm is a fresh launch of the same build, so a session with the flag on its first arm is a reload experiment with
one cold arm and the rest warm.

`tools/vitrail-load-census.py` reads the four into one table per session, and the load wall is the arm's own log
timestamps from its first line to `This pack's first full frame opened`.

## F1 - the census

MakeUp-UltraFast-9.5e, 1920x1200, Metal 3, the frozen `PerfWorld`, 600-frame windows, caches removed before the
first arm. `translations` is served/translated; the ms columns are the engine's own spans and the wall is the
load's.

```
arm      lookups  built   translations   expand        translate     modules        warmup        load
cold         574    187       0/45       97 ms/78      563 ms/53     1747 ms/125    62/62 2020 ms  11 s
warm1        574      0      45/0       109 ms/78      166 ms/53       18 ms/124    62/62  279 ms   8 s
warm2        574      0      45/0       124 ms/78      180 ms/53       21 ms/124    62/62  308 ms   8 s
warm3        574      0      45/0       118 ms/78      194 ms/53       21 ms/124    62/62  307 ms   8 s

ComplementaryReimagined r5.9.1, the same session shape
arm      lookups  built   translations   expand        translate     modules        warmup        load
cold         581    191       0/48      394 ms/90     1212 ms/56     1807 ms/125    62/62 2969 ms  15 s
warm1        581      0      48/0       576 ms/90      416 ms/56       40 ms/125    62/62 1635 ms  11 s
warm2        581      0      48/0       440 ms/90      299 ms/56       27 ms/124    62/62 1082 ms   9 s
warm3        581      0      48/0       370 ms/90      260 ms/56       29 ms/124    62/62 1101 ms   8 s
```

A second MakeUp session repeated the split: `574 lookups, 187 built, 11-12 s` cold against
`574, 0, 8 s` warm, so the cold/warm difference is reproducible and not one session's machine state.

**Read together:** on a warm launch the module cache is **574 hits and no misses** and the translation cache is
**45 hits and no misses** - the disk caches are complete for the pack, and what remains of the shader path is
18-40 ms of module rebuilding, 166-416 ms of replaying the cached translations, and 279-308 ms (MakeUp) to
1.1-1.6 s (Complementary) of pipeline warm-up. **The caches are not the startup cost any more; the load is.**

## F2 - compiled once, reused

Two questions and two answers, both exact.

**Within one load, every distinct input is built once.** A cold arm's `served` and `built` add up to its total
lookups, and the split is the reuse: the cache is written as it is read, so a unit asked for three times is
built once and served twice.

```
pack            lookups   distinct inputs built on a cold load   lookups per input
MakeUp              574                  187                            3.07
Complementary       581                  191                            3.04
no-pack             115                 NOT MEASURED
Photon              607                 NOT MEASURED
```

**Between two packs, 105 of those inputs are the same input.** The cache file name is a hash of everything that
decides what the unit turns into, so the two packs' file sets intersect exactly on the units both asked for:
MakeUp needs 187, Complementary 191, they share **105**, and 82 and 86 are the packs' own. That is **55 per cent
of each pack's compiled vocabulary being the game's own**, and it is why a cold load of the second pack is
cheaper than a cold load of the first on a machine that has run either: measured, MakeUp's cold load built 187
units in 11-12 s, and Complementary's - with those 105 already on disk from MakeUp's session - still built 191,
because this round removed the cache between the sessions to keep each cold. The sharing is real in ordinary
use and this round's flags hid it; the count is the count either way.

**At the pipeline level nothing is duplicated either.** The backend's own census reads
`pipelineIdentities=330 pipelineKeys=330` on MakeUp: 330 distinct game pipelines, 330 distinct Metal pipeline
keys, no two identities collapsing onto the same state.

**What is NOT measured is the near-duplicate**: two inputs that differ only in a define, and could have been one
program with a branch or one unit with a smaller define set. The plan's F2 lists that case and nothing counts
it: the cache answers "same input" exactly and says nothing about "nearly the same input".

## F3 - the second and third load

Answerable in one session because every arm is a fresh launch of the same jar, and answerable across sessions
because the counts say which arms were cold. A cold arm is one that built units; a warm arm built none.

```
pack            arms                    cold (built > 0)          warm (built = 0)
MakeUp          c2-makeup               11 s  (187 built)         8, 8, 10, 10 s
                c2b-interval                                       8, 8, 9 s
                c2c-interval2                                      9, 8, 8 s
                f1-makeup               11 s  (187 built)         8, 8, 8 s
                f2-makeup               12 s  (187 built)         8 s
Complementary   f1-complementary        15 s  (191 built)         11, 9, 8 s
```

So the cold/warm split is a replicate, not one session: **three cold MakeUp arms in three sessions each built
187 units and took 11-12 s**, and sixteen warm MakeUp arms in five sessions built none and took **8 s on twelve
of them and 9-10 s on four**. The wall is looser than the counts - nothing here is as tight as "0 built" - and
the modal warm figure is the one to quote. Complementary has one cold arm and three warm ones, so its 15 s
against 8-11 s is one session's reading.

The cold load's extra seconds are the compiles themselves, and the engine's own spans name them: **1734-1763 ms
of module making and 529-563 ms of translating** on MakeUp against 18-23 ms and 164-244 ms warm; **1807 ms and
1212 ms** on Complementary against 27-40 ms and 260-416 ms. So the cache is worth about 2.3-2.4 s of a
checkout's first load - the modal warm load is 8 s and the cold ones are 11-12 s - and it is worth all of it
from the second launch on.

One detail worth keeping: Complementary's warm arms **descend** (11, 9, 8 s) while MakeUp's are flat at 8 s.
Something beyond the two shader caches is still warming across the first warm arm - the pack archive in the
page cache, or the game's own resource loading - and it is NOT ATTRIBUTED here.

**The cache is per build, and that is why this programme had never seen a cold load.** `ModuleCache`'s key
carries the mod's version and, on a development build, the commit behind it, so a fresh commit opens a fresh
directory and pays the cold load once - visible in this machine's instance as
`modules/0.13.0-dev+mc26.2+6afce954` beside `modules/0.13.0-dev+mc26.2+5b498e70`, the first of which was 399
files the second had to rebuild. On a release build the key is the version, so a player pays the cold load once
per Vitrail update and never again; on a development build it is once per commit, which is what every session of
this programme has been paying without saying so.

## What no cache covers: the pipeline state, remade every launch

The warm rows are the finding's edge: with **zero** modules built and **zero** translations translated, the load
still spends **279-308 ms** (MakeUp) and **1082-1635 ms** (Complementary) compiling **62 of 62 leftover
pipelines ahead of their first draw**. Nothing about that work is on disk anywhere:

- Vitrail's two caches hold the GLSL translation and the game-compiler module;
- Metallum's caches - `compiledPipelines` keyed on the game's own `RenderPipeline` object, `functionCache` keyed
  on `(MSL, entry point, profile)` - are **in-memory HashMaps**, so they are empty at every launch;
- and there is no `MTLBinaryArchive` anywhere in the backend.

So every launch re-creates every Metal function and every pipeline state from scratch, and that is the largest
named startup item left after the caches. **It is recorded as a candidate and not implemented**: an on-disk
Metal pipeline cache would be worth 0.26-0.31 s per launch on MakeUp and 1.1-1.6 s on Complementary by the
warm-up spans above, on a track whose gate is measurement rather than a picture, and it is the first Track F item
that is bigger than the noise.

## Correctness

- No engine code was changed for any of this: the numbers are the engine's own lines, read by a tool committed
  beside them (`tools/vitrail-load-census.py`), and the only new harness behaviour is removing derived caches
  that the load rebuilds.
- The scenes are the corpus's frozen `PerfWorld` and every arm reported its target (1920x1200) and its command
  generation (metal3) through the harness's guards; the structural frame counters agree with the earlier corpus
  sessions to the tenth (`loadedMiB 231450.5` for MakeUp in both).
- The removal is printed with its size and file count before it happens, so a session's log says what it
  destroyed; both caches are derived, keyed on the shader text and the build, and are rebuilt by the load that
  needs them.

## Decision

**KEPT - F1, F2 and F3 answered as measurements.** No engine change ships from this round: the census already
existed and what was missing was a cold arm and a table.

- F1: on a warm launch the module cache is 574/574 and the translation cache 45/45, and the largest remaining
  shader-path cost is the pipeline warm-up rather than any compile.
- F2: every distinct input is built once (3.04-3.07 lookups per input), no two pipeline identities share a key,
  and 105 of the two packs' inputs are the same input.
- F3: a warm launch compiles nothing and saves 3-4 s on MakeUp and 4-7 s on Complementary against a cold one.

**RECORDED, NOT IMPLEMENTED - an on-disk Metal pipeline cache.** 0.26-1.6 s a launch by the warm-up spans, on
every launch, with no disk cache of any kind behind it today.

**CORRECTION - the frame probe's `compiles` and `compileMs` fields are window-scoped.** They read
`compiles=0 compileMs=0.00` in every corpus window because the compiles happen before the window opens, which is
correct and is not "nothing was compiled": the load's compiles are the `1747 ms over 125 modules` line above.
A reader who takes those two fields as the session's compile cost reads zero for a load that built 187 units.

**NOT MEASURED - the in-session reload.** F3+T reloads the pack without restarting the client, and this harness
presses no keys; the relaunch is the proxy. `ModuleCache`'s own note says F3+T already hits, because the load
number stays out of the disk key - so the prediction is "0 built", and it is a prediction.

## Residual

- **No per-compile timing**, so F1's "max compile spike" cannot be answered: the census keeps totals per load,
  and the worst single unit's milliseconds are nowhere. A maximum would need a clock around one compile, which
  is the next thing to add if a spike is ever suspected.
- **The 8 s warm load is not decomposed.** The shader path accounts for 0.2-0.5 s of it; the rest - JVM start,
  mod loading, resource pack, the world and the pack's own first passes - is outside Track F and unmeasured.
- **`no-pack`'s and Photon's distinct unit counts are not measured** (115 and 607 are lookups, not inputs).
- **Complementary's descending warm arms are not attributed** (11, 9, 8 s).
- **The near-duplicate case of F2 is unmeasured** by construction of the key.

# F4 - the pipeline warm-up, and a correction to what it was worth

## Question

F4 asks what is left of the first-world path once the caches are warm, and the F1/F3 measurement named a
candidate: a warm launch builds nothing but still "compiles 62 of 62 leftover pipelines ahead of their first
draw", 262-312 ms on MakeUp and 1.08-1.64 s on Complementary. An on-disk Metal pipeline cache was recorded as
**the largest measured startup item left, 0.26-1.6 s a launch**. This section is that claim checked, and it is
**wrong as stated**.

## What the load actually waits for

`FamilyWarmup.awaitAll()` is called from **exactly one place** in the engine: `PackChain.close()`, the client's
shutdown, where it is capped at two seconds. The pack load never joins it. The warm-up is three MIN_PRIORITY
worker threads started when a chain is built, and their work proceeds beside the rest of the load.

The logs say the same thing by their timestamps: the warm-up line lands **5-10 s** into the load and the pack's
first full frame **2-6 s after it**.

```
arm                        load    warm-up line at   first full frame
f1-makeup cold             11 s         8 s               11 s
f1-makeup warm1             8 s         5 s                8 s
f1-complementary cold      15 s        10 s               15 s
f1-complementary warm3      8 s         6 s                8 s
c2-makeup plain            11 s         8 s               11 s
c46-complementary plain    15 s         9 s               15 s
```

So the 0.26-1.6 s is **the span of background work the load does not wait for**, not a saving the load would
see. What an archive could buy is therefore two smaller things:

1. **The CPU the warm-up takes from the load's own work** - three low-priority threads over that span, whose
   effect on an 8 s load the load wall could show only as a fraction of a second, and does not resolve.
2. **Any pipeline a first draw asked for before the warm-up reached it**, which is the hitch the warm-up exists
   to prevent. **No counter can see this today**: `MetalFrameProbe.pipelineCompiled` is gated on the measurement
   window, and the window opens after the pack's first full frame and a 25 s settle - so every compile that
   happens during a load or in the world's first seconds is invisible by construction.

## Decision

**DEFERRED, and the candidate corrected.** The record at F1/F3 that an on-disk pipeline cache is worth
"0.26-1.6 s a launch" is withdrawn: that figure is the span of background work the load overlaps, and neither of
the two things an archive could actually buy is measured. A change that removes work nobody waits for, sized by a
span nobody waits on, is not a candidate yet - it is a hypothesis with a number attached to the wrong quantity.

**What would size it**: a counter for the *unarmed* window. The engine already has the two accumulators
(`MetalFrameProbe.pipelineCompiled` and its window gate); what it needs is to count and report the compiles from
the pack load to the first seconds of the world - how many, their total time, and the worst single one - and to
say whether any of them was a *first draw* compiling on the render thread rather than a background worker
finishing it. That is the same instrument F1 asks for as "max compile spike", and it is the next step here.

## Next

1. **F4's unarmed-window counter**, which sizes or dismisses the pipeline archive: compiles from the load to the
   first seconds of the world, their total, and the worst one.
2. **The max compile spike** generally, which the same addition gives - F1 asks for it and today's census has
   totals per load and no maximum.
3. Back to the GPU list: **C3's remaining three scales**, which is structural and unaffected by the machine's
   frame-time spread.
