## Metallum

Metallum is an experimental rendering backend for Minecraft on macOS that uses Apple’s Metal API instead of OpenGL/Vulkan. It provides a more native rendering path and aims to improve performance and efficiency on Apple Silicon.

This project is still experimental. Performance, stability, and compatibility may vary depending on your system and installed mods. If you encounter bugs, please report them on GitHub.

## Current compatibility target

- Minecraft Java Edition **26.2**
- Fabric Loader **0.19.3**
- Sodium **0.9.2 for Minecraft 26.2** (`mc26.2-0.9.2-fabric`)
- Java **25**
- macOS on Apple Silicon

Version-sensitive Minecraft Graphics API and Sodium integrations must be checked against the 26.2 source/API before backend changes are made.

## Minecraft 26.2 MRT foundation

The Metal backend now follows Minecraft 26.2's indexed color-target model instead of assuming a single color attachment:

- `RenderPassDescriptor.colorAttachments()` slots are preserved by index, including unused/null slots.
- Up to 8 Metal color attachments are supported per render pass.
- `RenderPipeline.getColorTargetStates()` is compiled slot-by-slot into the Metal pipeline descriptor.
- Color format, write mask, and blend state are configured per active target slot.
- Render-pass clear values are tracked per attachment.
- MRT attachment extents are validated before encoding.
- Depth-only render passes no longer depend on a synthetic color attachment for viewport/scissor sizing.

Minecraft 26.2 currently constrains active color targets to compatible blend-function usage at `RenderPipeline.Builder` level; Metallum still keeps the Metal state attachment-local so the backend does not reintroduce a single-target assumption.

This is backend GPU behavior only. Shader-pack concepts such as `colortex*`, draw-buffer routing, ping-pong/history, shadow/deferred/composite scheduling, and pack policy belong in Vitrail rather than Metallum.

## Requirements

- macOS
- Apple Silicon (M1 or newer)

