# Metallum

[![ci](https://github.com/DebuNeko233/metallum/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/DebuNeko233/metallum/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An experimental **Metal rendering backend for Minecraft on macOS**, built as a
[Fabric](https://fabricmc.net/) mod. Metallum implements Minecraft's graphics layer on Apple's Metal
instead of OpenGL or Vulkan, and draws through [Sodium](https://modrinth.com/mod/sodium). The
shader-pack engine that runs on top of it is the companion project
[Vitrail](https://github.com/DebuNeko233/Vitrail-Shaders-Metal).

> [!WARNING]
> **Experimental, and no release has been published yet.** There is no downloadable build: the
> release automation exists and its first tag is still open work, so building from source is the only
> way to install it today. Performance, stability and mod compatibility vary by system and by pack.

## Features

- A Metal 3 execution path for the whole frame. Metal 4 is kept compilable and manually selectable,
  and is frozen as an experimental backend - no performance work runs on it.
- Minecraft 26.2's indexed color-target model: up to 8 color attachments a pass, with format, write
  mask and blend state set per slot, unused slots preserved.
- Native color-mipmap generation through Metal's blit encoder, and a separate generic depth-mipmap
  bridge for the `D32_FLOAT` chains Apple's native command cannot reduce.
- Shader-storage buffers and shader-writable textures, including true 3D textures, reflected from
  SPIR-V and bound as Metal arguments.
- An optional compute bridge for general shader-pack compute work.
- MetalFX frame scaling where the device supports it.
- An opt-in frame probe reporting frame rate, CPU time and allocation a window, and a Metal 3
  native-call census.

What each capability does **not** decide is as much a part of it as what it does: the detail, and the
boundary against shader-pack policy, is in
[docs/backend-capabilities.md](docs/backend-capabilities.md).

## Requirements

| Component | Version |
| --- | --- |
| Platform | macOS on Apple Silicon (M1 or newer) |
| Minecraft | 26.2 |
| Fabric Loader | 0.19.3 is what it is built and tested against; the jar accepts 0.19.2 or later |
| Java | 25 |
| Sodium | 0.9.2 for 26.2 (`mc26.2-0.9.2-fabric`) |

The loader, Minecraft and Java ranges are the ones `src/main/resources/fabric.mod.json` declares, so
the loader enforces them whether or not this table is current. Two things that metadata does **not**
declare are worth knowing before installing:

- **Sodium is required in practice.** The backend integrates with it - a `sodium:config_api_user`
  entry point and mixins on its classes - but it is not listed as a dependency, so an instance without
  Sodium is refused later rather than at startup.
- **Vitrail is what drives the backend.** Metallum is a backend rather than a mod a player configures;
  the shader-pack engine reached reflectively over `API_VERSION` 1 is the side that decides where the
  backend is used.

## Installation

### Build from source

JDK 25 is required; the Gradle wrapper fetches everything else.

```bash
git clone https://github.com/DebuNeko233/metallum.git
cd metallum
./gradlew build
```

The mod jar is written to `build/libs/`. Drop it into the instance's `mods/` directory together with
Fabric Loader, Minecraft 26.2 and Sodium 0.9.2 for 26.2.

### Development client

```bash
./gradlew runClient
```

This launches the developer client with the mod loaded. `-PvitrailSmokeJar=<path>` additionally
loads a built Vitrail jar for a smoke run, and `-PvitrailHud=0` turns macOS's Metal Performance HUD
off for a measured one.

## Usage

Metallum replaces Sodium's **Graphics API** option through Sodium's public Config API, adding a
*Prefer Metal* choice next to the vanilla ones. The option requires a game restart before it takes
effect.

Metal 4 is not selected through Sodium: it is reachable only through the diagnostics below, and it is
a frozen experimental path rather than a supported one.

## Configuration

Diagnostics are opt-in and read from JVM system properties at class load; none of them changes the
frame unless you ask for it.

| Property | Default | What it does |
| --- | --- | --- |
| `-Dmetallum.probeFrames=true` | `false` | Arms the frame probe, which prints one window line per measurement window |
| `-Dmetallum.frameProbeBudget=<n>` | `600` | The probe window's frame budget |
| `-Dmetallum.m3CallCensus=true` | `false` | The Metal 3 native-call census, and the share of calls whose value the slot already held |
| `-Dmetallum.metal4Frame=<bool>` | `true` | Whether the frame is carried by the Metal 4 path when that generation is selected |
| `-Dmetallum.metal4FoldClears=<bool>` | `true` | Whether a clear becomes the pass's load action; `false` keeps every clear as its own pass, which is the control |
| `-Dmetallum.drawableReadback=true` | `false` | Copies each presented drawable into a shared buffer so the picture can be read back |
| `-Dmetallum.lifecycleProbe=<name>@<tick>,...` | unset | Drives a scripted lifecycle schedule for the lifecycle gate |
| `-Dmetallum.probeRepeat=<n>` | `0` | Repeats the capability probe `n` more times and writes each answer out |

The probe's window line, what each counter means, and how large a difference the fixture can be
trusted to show are in [docs/performance-testing.md](docs/performance-testing.md).

## Status and validation

Metallum pairs with Vitrail by an integration contract rather than by a commit: Vitrail understands
`API_VERSION` 1 and this repository answers `MetallumApi.apiVersion()`, so a build answering anything
else is reported as incompatible instead of used.

- CI runs on an Apple Silicon runner: the contract scripts under `tools/`, the wrapper validation and
  `./gradlew build`.
- Real-device evidence comes from the smoke launchers under `tools/`; [VITRAIL_SMOKE.md](VITRAIL_SMOKE.md)
  describes each gate and how to run it.
- The long-term performance programme's results - what each track proved, rejected and settled - are
  on one page: [docs/long-term-performance-summary.md](docs/long-term-performance-summary.md).
- PHASE 17 real shader-pack compatibility was closed by the project owner's judgement with no per-row
  status recorded, so the compatibility matrix is empty rather than partly filled.

A green build, a successful launch or a clean log is **not** evidence that Metal execution is correct:
correctness on a real pack requires the reviewed screenshot and reference material that
[docs/performance-testing.md](docs/performance-testing.md) defines.

## Documentation

[docs/README.md](docs/README.md) is the router for all of it - which page owns what, the frozen
Metal 4 record, and the rounds the programme supersedes. The pages most often wanted:

| Document | Covers |
| --- | --- |
| [docs/backend-capabilities.md](docs/backend-capabilities.md) | each backend capability, and the policy it deliberately does not decide |
| [docs/performance-testing.md](docs/performance-testing.md) | how a measurement is taken, and how large a difference it can be trusted to show |
| [docs/long-term-performance-summary.md](docs/long-term-performance-summary.md) | what the long-term programme proved, rejected and settled |
| [VITRAIL_SMOKE.md](VITRAIL_SMOKE.md) | each Apple-Silicon smoke gate and how to run it |

## Development

```bash
./gradlew build     # compile, validate the access widener, and jar
./gradlew runClient # development client
```

`.github/workflows/ci.yml` is the single pull-request workflow. Alongside the build it runs the
contract scripts under `tools/ci-*.py`, which pin the shapes this backend must keep - an entry point,
an ordering, a counter that must still be reached from the road that reaches it. A contract that no
workflow names is refused, so one cannot sit in the tree looking like coverage while nothing runs it.

Two conventions the contracts enforce rather than assume:

- **Shader-pack semantics stay out of this repository.** Names such as `colortex*`, `shadowtex*`,
  draw-buffer routing, ping-pong/history and pack scheduling belong to Vitrail. The architecture guard
  refuses that vocabulary here, and the seam is one-directional by design.
- **A pinned shape moves with its contract.** Changing a shape a contract pins is expected; changing
  it without moving the pin fails CI, which is the point.

## Contributing

Issues and pull requests are welcome. `master` is protected by a repository ruleset: changes arrive
through a pull request, history stays linear (rebase or squash, not a merge commit), and the `ci`
check must pass. Run `./gradlew build` and the `tools/ci-*.py` contracts before opening one.

## License

MIT - see [LICENSE](LICENSE).

## Credits

This repository is a fork of [kokodio/metallum](https://github.com/kokodio/metallum), the original
Metal proof-of-concept backend. The shader-pack engine it pairs with is
[DebuNeko233/Vitrail-Shaders-Metal](https://github.com/DebuNeko233/Vitrail-Shaders-Metal).
