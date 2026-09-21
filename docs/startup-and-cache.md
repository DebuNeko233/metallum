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
(`run/vitrail/modules/<build>` and `run/vitrail/translations/<build>`), keyed on the shader text and the build,
so *every* session this programme had ever run measured the warm path - the corpus's four packs read
`574 units served, 0 built` because the caches had been filled by the first session of that build. The flag
removes both directories before the session's first arm and prints what it removed (`19M, 672 file(s)` and
`16M, 298 file(s)` the first time); every arm is a fresh launch of the same build, so a session with the flag on
its first arm is a reload experiment with one cold arm and the rest warm.

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

Answerable in one session because every arm is a fresh launch of the same jar:

```
                     cold        warm (repeats)          saving
MakeUp               11-12 s     8 s (5 arms, 2 sessions)  3-4 s
Complementary        15 s        11 / 9 / 8 s              4-7 s
```

The cold load's extra seconds are the compiles themselves, and the engine's own spans name them: **1747 ms of
module making and 563 ms of translating** on MakeUp against 18-21 ms and 166-194 ms warm; **1807 ms and
1212 ms** on Complementary against 27-40 ms and 260-416 ms. So the cache is worth 2.3-3.0 s of a checkout's
first load, and it is worth all of it from the second launch on.

One detail worth keeping: Complementary's warm arms **descend** (11, 9, 8 s) while MakeUp's are flat at 8 s.
Something beyond the two shader caches is still warming across the first warm arm - the pack archive in the
page cache, or the game's own resource loading - and it is NOT ATTRIBUTED here.

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

## Next

1. **F4's real question, now sized**: the 0.3-1.6 s of per-launch pipeline state is the largest named startup
   item; a Metal pipeline archive is the candidate and it needs its own phase report and rollback path.
2. **The max compile spike**, if a load is ever seen to hitch: one clock around one compile, reported per load.
3. Back to the GPU list: **C7's attachment-traffic corpus** and **C3's remaining three scales**, both of which
   are structural and unaffected by the machine's frame-time spread.
