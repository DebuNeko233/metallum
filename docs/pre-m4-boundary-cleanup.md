# Pre-M4 boundary cleanup

## Pre-M4 boundary cleanup: what is left, and the order it has to land in

The `render.metal3` sealing is done (metallum `267f3b6`) and the generation-neutral capability vocabulary exists
(`96ed4dd`, `66f33ab`). What remains is cross-repository, and two constraints decide the order.

### The shape being built towards

```
Vitrail shader-pack engine
      | semantic capabilities
Vitrail compat/metallum adapters
      | stable reflection ABI
com.metallum.render.* flat public bridges
      |
shared neutral capability interfaces
      |
  render.metal3  (now)     render.metal4 (future)
```

Vitrail may name only the stable flat surface (`MetalBackend`, `MetalDevice`, `MetalAttachmentBridge`,
`MetalFrameBridge`, `MetalComputeBridge`, `MetalDepthMipmapBridge`, `MetalSamplerBridge`, `MetalScaleBridge`,
`MetalTextureBridge`). It may not name `com.metallum.render.metal3.*`, `render.metal4.*`, `mtl.metal3.*` or
`mtl.metal4.*` - in code **or in a string**.

### Batch 1 - Vitrail adapters, and the mixin only with them - **done** (vitrail `44e97493`, `beb3a651`, `bee38231`)

`common/src/main/java/dev/vitrail/mixin/metallum/MetalCommandEncoderMixin.java` targeted
`com.metallum.render.metal3.MetalCommandEncoder` by string. That is the structure that broke once already
(`267f3b6` moved the class, the mixin stopped applying, and every capability it carried disappeared - visible as
darker Photon shadows, with one WARN in the log and no test failure). It has been deleted, in a change that
lands after its replacements rather than with them, which is the order that keeps the regression from returning:

1. `dev.vitrail.compat.metallum.MetallumFrameBridge` - reflection onto `com.metallum.render.MetalFrameBridge`
   (`supports`, `generateMipmaps`, `clearStorageTexture`, `copyStorageTextureRegion`).
2. `dev.vitrail.compat.metallum.MetallumEncoderCapabilities` - implements `MipmapCommands`,
   `StorageImageCommands`, `ComputeCommands`, `AttachmentCommands`, `ScaleCommands` over the existing compat
   bridges plus the new frame bridge; holds only `Object backend`.
3. `Backends.capabilities(Object)` - the encoder when it already implements the requested capabilities, otherwise
   the cached Metallum adapter when `MetallumFrameBridge.supports(backend)`. Adapters cached per backend
   (weakly), because this is on the frame path.
4. Every `instanceof <Capability>` on a raw backend becomes `Backends.capabilities(...) instanceof <Capability>`;
   `Backends.encoder(...)` stays for callers that need backend identity.
5. `tests/test_backend_neutrality_contract.py` gains a second reading that strips **comments only** and rejects
   the four generation package prefixes. It was written and proved - it fires on the mixin target - and then
   reverted because five other scripts were red; it lands with this batch, not before.

With the mixin gone, that second reading no longer has a live target to fire on, so it is proved twice on the
Vitrail side: a self-test that also holds the other direction (a comment may name a generation package, the
stable flat surface stays nameable in a string, the `com/metallum/mtl/metal4/...` spelling is caught), and a
mutation of the live tree - a file naming `com.metallum.render.metal3.MetalCommandEncoder` reported one package
name and went back to zero when removed. The two mixins that remain there name the flat facades
(`com.metallum.render.MetalBackend`, `com.metallum.render.MetalDevice`), which is this document's own allowlist.

### Batch 2 - the Attachment ABI, which is broken today - **done** (metallum `3394d67`, vitrail `ab21e38a`, `ff344317`)

Vitrail resolved `com.metallum.render.AttachmentContents`, a path that does not exist (the type is in
`render.shared`). The fix was not to correct the string but to stop needing it:
`MetalAttachmentBridge.setNextPassContents(Object encoder, boolean[] readAfterwards, boolean[] overwritten)`,
with `AttachmentContents` constructed inside metallum, one entry per slot, defaulting per slot to the interface's
own `CARRIED`; Vitrail passes only the two facts it has decided. `setNextPassReadsStorageImage(Object, boolean)`
is unchanged. The value-typed overload is gone rather than kept beside it, so no name has to be resolved at
runtime for the two facts to arrive, and `tools/ci-metalfx.py` refuses the value-typed signature - proved by
mutation (re-adding it fails with its own message; removing it passes). The Vitrail half is pinned in
`test_pack_pass_writes_every_pixel`, with the same two-way mutation proof.

**What proved it is live, and why that took a new line.** The first A/B (`run/b2-attach`, plain against
`-Dvitrail.narrowStorageBoundary=true`) moved **nothing**: every counter identical (`encoders` 21445,
`passChanged` 20845, `loadedMiB` 93964.6, `storedMiB` 132795.0, `blits` 6600), frame time identical, and a
picture difference of 4.61 mean channel - at this scene's recorded same-configuration floor of 4.10, so it
resolves nothing. The reading is that this pack's passes all answer "may read" for the boundary, which is the
interface's default, so that switch is a no-op here and cannot evidence the ABI either way. What it did expose
is that the adapter had no way to say whether it was delivering at all - the whole fault was silence - so a
Vitrail-side `INFO` line now says once, on the first statement the backend accepts, how many slots it described
(`ff344317`). The second A/B (`run/b2-elide`, plain against `-Dvitrail.elideTargetTraffic=true`) is the one that
evidences it, and all three of its facts agree: the line appears **exactly once** in the elide arm and not at
all in the plain arm ("the backend was told what a pass needs of 2 colour attachment slot(s)"), `loadedMiB`
falls **93964.6 to 65250.7 (-30.6 per cent)** and `storedMiB` **132795.0 to 131199.7 (-1.2 per cent)** with
`encoders`/`passChanged`/`blits`/`depthAttachments` unchanged and frame time +0.2 per cent, and the pictures
differ by **4.05** mean channel - within the same floor, so the elision is not visible on this scene. `Error
loading class` is 0 in every arm.

### Batch 3 - compute/depth/close neutrality (metallum side is partly done)

`MetalFrameDepthMipmaps`, `MetalFrameComputeCommands`, `MetalComputeCompiler` and `MetalComputePipelineResource`
exist and the Metal 3 encoder and execution state implement them; the flat compute and depth facades already
route through them (`96ed4dd`). What is left is the cross-repo half: Vitrail's `MetallumComputeBridge` and
`MetallumDepthMipmapBridge` calling the flat facades (they already do) and the fixtures that prove it.

### Verification, per batch

metallum: `./gradlew build`, `tools/ci-contracts.py`, `tools/ci-architecture.py`, `git diff --check`, all exit 0,
and every `tools/ci-*.py`. Vitrail: `./gradlew build` plus the contract tests. Then one Photon run
(55 %, 600 frames, camera pinned, settle 25) reading `wallP50`, `gpuM3Ms`, `encoders`, `passChanged`, `blits`,
`depthAttachments`, `pipelineIdentities`, `pipelineKeys`, `compiles`, `compileMs`, `metal4Presents` from that
run's log - and for batch 1, the capability path in the log (not a screenshot) is the evidence that the
capabilities are back: the last regression was invisible in every counter and visible only as a picture.

**Batch 1 on hardware** (`run/b1-caps`, `run/b1-caps2`, 2026-09-19 23:57/23:59, Photon v1.3b at 55 %, 600
frames, camera at `548.5,63,-248.5 yaw 0 pitch 7.8`, settle 25, fullscreen). The second arm is counter for
counter identical to `run/mixin-fixed`, where the retargeted mixin still carried the capabilities - and that
equality is the proof, not the individual numbers: `renderPasses` 20934, `blitEncoders` 3000, `computeEncoders`
1800, `clearEncoders` 600, `encoders` 21445, `passChanged` 20845, `loadedMiB` 93964.6, `storedMiB` 132795.0,
`depthAttachments` 4800, `depthLoadedMiB` 14385.6, `depthStoredMiB` 32449.5, `blits` 6600, `compiles` 0,
`compileMs` 0.00, `pipelineIdentities == pipelineKeys` 345, `metal4Presents` 0, `wallP50` 7.38. The two broken
arms (`run/m3-sealed`, `run/sealed-check`) read `Error loading class` 1, `blitEncoders` 2400 and
**`computeEncoders` 0** - the regression in counter form. The first arm read `renderPasses` 21741,
`depthAttachments` 5622, `encoders` 22252, which is **weather, not the change**: its screenshot shows rain, the
one thing this harness does not pin.

