# Vitrail Metal smoke run

This is a developer-only launch path for exercising the companion Vitrail branch against Metallum on Apple-Silicon macOS. It does not change Metallum's published dependencies and it does not make Metal a supported Vitrail backend.

## Prerequisites

Keep sibling checkouts of the two current feature branches, or pass the Vitrail checkout path explicitly:

- Metallum: `feat/mc26.2-mrt-foundation`
- Vitrail-Shaders-Metal: `feat/backend-neutral-sodium-terrain-hook`
- Java 25
- Apple-Silicon macOS

## Launch

From the Metallum checkout:

```sh
./tools/run-vitrail-smoke.sh ../Vitrail-Shaders-Metal
```

The script builds Vitrail's Fabric jar, passes that jar to Metallum's Loom client through the developer-only `localRuntime` configuration, and supplies the two Fabric API modules Vitrail declares. It sets no Vitrail property: the developer switch that used to be needed here (`vitrail.experimentalMetal`) is gone, because Metal is the only path Vitrail draws on and a session is let in on its own answers.

On the first dev-profile launch, open Video Settings, select **Prefer Metal**, close the client, and run the same command again. The second launch then tests the complete selection chain rather than bypassing it: Metallum owns and persists Prefer Metal, Minecraft starts the Metal backend, Vitrail sees compatible `MetallumApi` v1 plus the selected preference, and Vitrail's Metal capability provider must publish after successful device creation before the shader-pack path can open.

### Deterministic MRT fixture

To install Vitrail's developer-only MRT contract pack into this Loom profile before launch, add `--mrt-fixture`:

```sh
./tools/run-vitrail-smoke.sh ../Vitrail-Shaders-Metal --mrt-fixture
```

This refreshes `run/shaderpacks/mrt-contract` from the companion Vitrail checkout. The launcher intentionally does **not** change Vitrail's selected shader pack or Minecraft options; select `mrt-contract` in Vitrail's shader-pack UI and restart the same command. Keeping selection on the Vitrail side preserves the runtime/backend ownership boundary.

The fixture has two jobs. Its fullscreen composite writes colortex0 red, colortex1 green, colortex2 blue, and colortex3 white, and its final pass displays all four as screen quadrants. Its terrain fragment declares one draw buffer while producing three fragment-output ranks, causing Vitrail's opaque coverage path to hand the backend two nullable color-attachment slots before the coverage attachment. Metallum must preserve those slot indices rather than compacting them.

While the four-colour result is visible in-world, press **F2 once**. The launcher records a marker before starting the client; after a clean client exit it looks for the newest PNG created after that marker and runs Vitrail's developer-only `tests/VerifyMrtScreenshot.java` against it. The verifier samples multiple points around the center of each quadrant and accepts the four expected swatches in any orientation, so vertical texture orientation is deliberately irrelevant.

If no new screenshot was taken, the launcher reports that pixel verification was skipped and still exits successfully. If a new screenshot exists but does not contain one red, green, blue and white quadrant, the verifier fails the smoke command. Take the screenshot while the world view is visible rather than from a menu or pause overlay.

You can also run the verifier directly:

```sh
java ../Vitrail-Shaders-Metal/tests/VerifyMrtScreenshot.java run/screenshots/<file>.png
```

The verifier itself is CI-self-tested with a generated four-colour image. It is test infrastructure only and is not packaged into either mod.

### First-person hand glint fixtures

The two first-person glint moments are independent acceptance gates even though both correctly request `gbuffers_armor_glint`. Run them separately:

```sh
./tools/run-vitrail-smoke.sh ../Vitrail-Shaders-Metal --hand-glint-fixture
./tools/run-vitrail-smoke.sh ../Vitrail-Shaders-Metal --hand-water-glint-fixture
```

For `--hand-glint-fixture`, select `hand-glint-contract`, use first person, and hold a glinting opaque/non-translucent item such as an enchanted book or tool. Acceptance requires the `hand_glint` piece at `HAND_SOLID`, a real Minecraft enchanted-glint texture, isolated `[colortex1 MAIN]`, the stable green screenshot gate, and clean `Stopping!`.

For `--hand-water-glint-fixture`, select `hand-water-glint-contract` and hold a translucent block model whose item glint is forced/enabled (glass with a glint override is suitable). `hand_water` means the Iris-compatible translucent hand pass; the player does not need to stand underwater. Acceptance requires `hand_water_glint @ HAND_TRANSLUCENT` plus the same real-texture, target, pixel and clean-shutdown evidence. Camera armor glint and the solid hand-glint run do not substitute for this second gate.

The launcher does not create or mutate inventory stacks. In particular, it does not manufacture the glinting translucent test item; prepare that held stack in the dev world before taking the screenshot.

### Final PHASE 9 shadow mipmap fixture

The final shadow checkpoint has its own launcher because it must prove real D32 depth mip generation rather than merely prove that the shader pack declared a mipmap directive:

```sh
./tools/run-vitrail-shadow-mipmap-smoke.sh ../Vitrail-Shaders-Metal
```

Select `shadow-mipmap-contract`, use an Overworld daylight scene with ordinary opaque terrain in the light-space walk, wait for the diagnostic to settle, press **F2 once** while the screen contains both GREEN and BLUE, and exit normally. The pack requests mip chains for both `shadowtex0` and `shadowtex1`; level zero is written with an alternating depth pattern, while the fullscreen diagnostic compares level zero with explicit LOD 4 from both names. GREEN means **both** depth names show readable generated higher-mip reduction. BLUE means both valid high-LOD reads match their bases at that pixel. MAGENTA means invalid depth **or a one-sided mismatch where only one shadow depth chain reduced**.

The important negative cases are deliberately distinct. An all-BLUE image is exactly what happens when mip generation fails or Vitrail correctly keeps both samplers clamped to level zero, and `VerifyShadowMipmapScreenshot.java` rejects it. A one-sided `shadowtex0`/`shadowtex1` implementation produces MAGENTA and is rejected as well. The launcher also requires a fresh Metal log showing the requested multi-level allocations, both shadow depth samplers bound together, a real opaque shadow-terrain draw, no shadow-stage failure, and clean `Stopping!`. Only the screenshot plus those log gates together count as real-device acceptance.

After a completed launch you can rerun the same log/screenshot verdict without starting Minecraft:

```sh
./tools/run-vitrail-shadow-mipmap-smoke.sh --verify-existing ../Vitrail-Shaders-Metal
```

Do not mark PHASE 9 closed from CI alone. The production path and fixture may be CI Verified while shadow mipmaps remain **Real-device Pending** until this command passes on Apple Silicon.

### Particle fixtures

Opaque and translucent particles are separate schedule checkpoints. Run both independently:

```sh
./tools/run-vitrail-particle-smoke.sh ../Vitrail-Shaders-Metal --opaque
./tools/run-vitrail-particle-smoke.sh ../Vitrail-Shaders-Metal --translucent
```

The opaque route uses `gbuffers_particles @ PARTICLES` before deferred and must also prove the coverage mask. The translucent route uses `gbuffers_particles_translucent @ PARTICLES` after deferred. Both require the real particle atlas, isolated `[colortex1 MAIN]`, a new screenshot and clean shutdown.

### Weather fixture

Weather is a separate post-deferred family even though it reuses the four-element PARTICLE vertex format. Run:

```sh
./tools/run-vitrail-weather-smoke.sh ../Vitrail-Shaders-Metal
```

Select `weather-contract`, enter a biome where precipitation is possible, then run `/weather rain`. Visible rain or snow is valid evidence: Minecraft draws both from the same weather mesh/program and changes only the sampled image, so the launcher accepts a real `minecraft:textures/environment/rain.png` or `snow.png`. Acceptance requires `gbuffers_weather @ RAIN_SNOW`, isolated `[colortex1 MAIN]`, the stable green screenshot gate and clean `Stopping!`. A particle, cloud or sky draw does not substitute for this checkpoint.

You can also use the underlying hook directly with an already-built jar:

```sh
./gradlew runClient -PvitrailSmokeJar=/absolute/path/to/vitrail-fabric-....jar
```

Supplying `vitrailSmokeJar` is what adds the local Vitrail/Fabric-API runtime dependencies and the Vitrail smoke JVM property. With no property, Metallum's normal build and normal `runClient` dependency set are unchanged.

## Measuring one scene twice

A smoke fixture answers whether a frame is drawn; a measurement answers what it costs, and the two are taken by different tools. One run of the performance harness is a whole measurement, with nobody at the keyboard:

```sh
./tools/run-vitrail-performance.sh --pack /path/to/pack.zip --world /path/to/save \
  --run plain --run 'elided=-Dvitrail.elideTargetTraffic=true'
```

The pack and the options file beside it are staged into `run/`, the pack selection and the Metal preference are written where the settings screen would have written them, the Loom client is launched straight into the world with `--quickPlaySingleplayer`, the frame probe is armed **only once the pack has drawn a full frame**, its 600-frame window is collected together with a screenshot, and the client is stopped by the arguments it was started with rather than by a signal to Gradle. Every run leaves `<out>/<name>/{latest.log,probe.txt,screen.png,gradle.log}`, and the runs are compared at the end by `tools/vitrail-performance-compare.py`, which parses the probe's own line rather than restating its counters; `--run` may be repeated, and the first is the baseline.

Three things it does not do. It cannot play: the client is left standing where the world put it, so the picture is evidence of a plausible frame rather than of anybody's judgement of one. It cannot photograph the screen on macOS until the process it runs under has been granted Screen Recording in System Settings, so a run may report that it has no picture - the counters are unaffected. And it measures no time yet: the probe counts bytes, encoders and bindings, and the only frame rate in the log belongs to the first full frame, which is a warming window.

`tools/ci-harness.py` pins the launcher's shape, because every property it has is one a hand-run measurement has already got wrong: a window armed before the pack had drawn a frame, a pack named in the script rather than handed to it, a jar picked out of the directory that holds every branch's jar, and a run that measured the pack's own defaults instead of the options its owner had chosen.

## What counts as evidence

A client reaching a world is only the entry point. Record the actual backend reported by the game and exercise the acceptance matrix in the companion PRs: indexed MRT including a hole, single-target regression, multi-binding/per-instance vertices, eligible and rejected mipmap paths, entity layout changes, SSBO and storage-image write/read visibility, true 3D storage, scratch/reanchor copies, writable `colorimgN`, compute ordering including deferred clears, descriptor remapping stress, oversized local-size refusal, depth/stencil fallback, and Vulkan regression.

For the deterministic MRT fixture specifically, a complete result now has two independent pieces of evidence: the log must show the terrain/composite/final chain running on Metal without render-pass/pipeline attachment-index errors, and the screenshot verifier must report `MRT screenshot pixel check: PASS` for the four-colour output.

Do not remove the Vitrail smoke gate or mark either PR ready merely because this launcher starts successfully. Compile-green and launch-green are not proof of correct Metal rendering.
