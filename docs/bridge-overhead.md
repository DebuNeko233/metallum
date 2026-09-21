# The Vitrail-to-Metallum seam: what a frame pays for it

Track D of the long-term plan asks what the cross-repository boundary costs in steady state: calls a frame, CPU,
allocation, and how much of it is reflection that could be resolved once. This is that census, and it is the
second CPU-side candidate in a row to come in under the plan's noise floor.

## Starting SHAs

```
Metallum: f2dce75 (the frame CPU and allocation readings)
Vitrail:  94219c13 + this round's bridge census
```

## The instrument

`dev/vitrail/compat/metallum/BridgeCensus.java` counts every call across the seam by bridge, the argument counts
it hands over, and the nanoseconds the call took, and prints one line a second while a frame is drawing:

```
Vitrail bridge: 1631 calls over 1003 ms (1625.7 a second, 3955 ns a call), frame 743 (740.6/s, 6 ms),
                sampler 888 (885.1/s, 0 ms) - 1631 varargs arrays over the second (~40.0 KiB),
                2 reflective lookup(s) since launch
```

It is wired into all **nine** reflective invoke roads the seven bridges carry (the frame, compute, depth, texture
and sampler bridges each have one invoke helper; the scale and attachment bridges invoke where they use it) and
into all **seven** reflective *resolutions* (`methods()`, `method()`, `surface()`), because the plan's rule for
this seam - reflection at startup, direct work in the frame - is only proven by counting the two apart.
`tests/test_bridge_census.py` pins the roads, the resolutions and the arithmetic, and a mutation that deletes one
road fails it. The timer wraps the whole `Method.invoke`, so the per-call figure is **what the caller pays**,
including the callee's own work for that call and not only the reflection.

## Measured

One Metal 3 arm a scene, 600-frame windows, fullscreen at 1920x1200, 25 s settle
(`run/d1-makeup`, `run/d1-nopack`):

```
scene            ms a frame   fps   bridge calls/s   calls a frame   ns a call   CPU share of the wall   lookups
no-pack                1.67   598             0             0.0          -              0 %             0
MakeUp                 6.74   148          1631            11.0      3955-4895        0.70 %            2
Complementary          8.30   120          5084            42.2      1447-1642        0.16 %            2
Photon                12.54    80           917            11.5      4696-6184        0.066 %           6
```

- **The seam is reached only by a pack.** The game's own frame calls none of the seven bridges at all: the line
  never prints, which is the census's own way of saying the boundary costs nothing when nothing asks for it.
- **Two bridges carry almost all of it**: `frame` (mipmap reductions, clears, storage copies) and `sampler`
  (comparison samplers). MakeUp calls them 743 and 888 times a second, Complementary 1089 and 3995, Photon 616
  and 152. Compute is reached by Photon only (152/s), and depth, texture, scale and attachment by none of the
  four scenes.
- **The call rate runs the other way from the frame time**: Complementary, the middle scene by frame time, makes
  42 calls a frame where Photon makes 12 and MakeUp 11 - and Photon's calls cost four times Complementary's,
  because the span includes the callee's own work (a mipmap reduction is not a comparison-sampler creation).
- **The reflective *resolution* is already a startup cost**: **2 lookups since launch** across seven bridges, so
  the plan's D2/D3 target ("discover once, invoke directly") is *already true* here - what happens per frame is
  the invocation, not the lookup.
- **The varargs arrays are nothing**: one `Object[]` a call, ~40 KiB a second, which against the frame's own
  71-183 KiB a frame (`docs/vitrail-cpu-performance.md`) is under 0.2 % of the frame's allocation.
- **A call costs 1.4 to 6.2 microseconds** depending on the bridge and the pack. That is ten to fifty times a
  direct call and it is the honest price of a `Method.invoke` through a varargs bridge - but across four scenes
  and 11 to 42 calls a frame it is **0.066 % to 0.70 % of the wall**.

## Decision

**MEASURED-BUT-NOT-WORTH-IT: replacing the reflective invoke with a `MethodHandle`, an interface handle or a
resolved direct adapter.** Every scene measured is under the plan's own 1 % noise floor (section 4) - 0.066 % to
0.70 % of the wall - and the two bridges that carry it are called 11 to 42 times a frame. The mechanism is real and the per-call cost is high; the
volume is what makes it not worth the change - and the change itself would touch every road across the seam,
which is the boundary the architecture contract exists to keep narrow.

**D2/D3 have nothing to win on this seam**: the resolution is cached (2 lookups a session), so "reflection only at
startup" is proven rather than asserted, and a capability snapshot would not remove a per-frame lookup because
there is none.

**And this closes the plan's CPU micro-optimisation round.** Section 51's exit condition is two consecutive
candidates measured under 1 %: the first was Metal 3's redundant binding elimination (56-72 calls a frame,
0.1-0.3 % of a frame, `docs/metal3-performance-round2.md`), and this is the second. The CPU work that remains is
not in the seam and not in the binding paths - it is the frame's own allocation, if anything, and the frame's
time is the GPU's.

## Residual and what is NOT MEASURED

- **The corpus is the plan's three packs and the no-pack baseline**, which is what section 3.1 asks for; a pack
  that dispatches far more compute (each dispatch is a bridge call) could raise the rate, and Photon's 152 compute
  calls a second is the most any of them does.
- **The census prints a rate, not a window total.** Its line is per second, so a comparison of two arms reads it
  as a rate; a per-window total would need the harness to parse it, and nothing needs that yet.
- **The 4-5 µs per call includes the callee.** A mipmap reduction or a comparison-sampler creation is real work
  that the caller pays for inside the span; the census prices the boundary as the caller experiences it and does
  not separate the reflection from the work behind it.
- **Nothing here says what the seam would cost if it were called** by a pack that reaches every bridge: the
  eight-bridge total is not a linear extrapolation of two.

## Next

Per the plan's order and the stop rule: **E2, the MetalFX scale ladder** - the frame's time is the GPU's on every
scene measured so far, and the render scale is the lever that moves real GPU work - and, on the CPU side, the
**allocation attribution** (`docs/vitrail-cpu-performance.md`'s residual), which is the one CPU number still
large.
