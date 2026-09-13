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

The script builds Vitrail's Fabric jar, passes that jar to Metallum's Loom client through the developer-only `localRuntime` configuration, supplies the two Fabric API modules Vitrail declares, and sets Vitrail's non-persisted `vitrail.experimentalMetal=true` smoke property for the game JVM.

On the first dev-profile launch, open Video Settings, select **Prefer Metal**, close the client, and run the same command again. The second launch then tests the complete selection chain rather than bypassing it: Metallum owns and persists Prefer Metal, Minecraft starts the Metal backend, Vitrail sees compatible `MetallumApi` v1 plus the selected preference, and Vitrail's Metal capability provider must publish after successful device creation before the shader-pack path can open.

### Deterministic MRT fixture

To install Vitrail's developer-only MRT contract pack into this Loom profile before launch, add `--mrt-fixture`:

```sh
./tools/run-vitrail-smoke.sh ../Vitrail-Shaders-Metal --mrt-fixture
```

This refreshes `run/shaderpacks/mrt-contract` from the companion Vitrail checkout. The launcher intentionally does **not** change Vitrail's selected shader pack or Minecraft options; select `mrt-contract` in Vitrail's shader-pack UI and restart the same command. Keeping selection on the Vitrail side preserves the runtime/backend ownership boundary.

The fixture has two jobs. Its fullscreen composite writes colortex0 red, colortex1 green, colortex2 blue, and colortex3 white, and its final pass displays all four as screen quadrants. Its terrain fragment declares one draw buffer while producing three fragment-output ranks, causing Vitrail's opaque coverage path to hand the backend two nullable color-attachment slots before the coverage attachment. Metallum must preserve those slot indices rather than compacting them.

You can also use the underlying hook directly with an already-built jar:

```sh
./gradlew runClient -PvitrailSmokeJar=/absolute/path/to/vitrail-fabric-....jar
```

Supplying `vitrailSmokeJar` is what adds the local Vitrail/Fabric-API runtime dependencies and the Vitrail smoke JVM property. With no property, Metallum's normal build and normal `runClient` dependency set are unchanged.

## What counts as evidence

A client reaching a world is only the entry point. Record the actual backend reported by the game and exercise the acceptance matrix in the companion PRs: indexed MRT including a hole, single-target regression, multi-binding/per-instance vertices, eligible and rejected mipmap paths, entity layout changes, SSBO and storage-image write/read visibility, true 3D storage, scratch/reanchor copies, writable `colorimgN`, compute ordering including deferred clears, descriptor remapping stress, oversized local-size refusal, depth/stencil fallback, and Vulkan regression.

For the deterministic MRT fixture specifically, capture the four-color quadrant result and confirm Metal validation emits no render-pass/pipeline attachment-index error while opaque terrain is visible. The fixture's compile-time contract test is useful regression evidence but is not a GPU test.

Do not remove the Vitrail smoke gate or mark either PR ready merely because this launcher starts successfully. Compile-green and launch-green are not proof of correct Metal rendering.
