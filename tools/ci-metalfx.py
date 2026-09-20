#!/usr/bin/env python3
"""Pins how this backend finds out whether it can scale a frame with MetalFX.

MetalFX is a framework of its own rather than a part of Metal, and this backend reaches Objective-C
through `objc_getClass`, which sees only the images that are already loaded. So the availability question
has three ways to come out false - no framework, a framework without the class, or a device that cannot
run the scaler - and every one of them has to be an answer rather than an exception, because a system
without MetalFX is a system this engine runs on. Availability is asked of Apple's own question on the
device and never of a version number, and the answer is said out loud, because "this Mac cannot do it"
and "this build cannot do it" are different sentences.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METAL_FX = ROOT / "src/main/java/com/metallum/render/MetalFx.java"
OBJC = ROOT / "src/main/java/com/metallum/objc/ObjC.java"
DEVICE = ROOT / "src/main/java/com/metallum/render/MetalDevice.java"
CI = ROOT / ".github/workflows/ci.yml"

metal_fx = METAL_FX.read_text(encoding="utf-8")
objc = OBJC.read_text(encoding="utf-8")
device = DEVICE.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# The image is loaded, and its absence is an answer
#
# `SymbolLookup.libraryLookup` is the dlopen, and it is what makes the classes visible at all. On a
# system without MetalFX it throws, so this framework alone is asked for through the optional road: an
# engine that cannot run one optional effect must not fail to start because of it.
# ---------------------------------------------------------------------------
if "public static SymbolLookup optionalLibrary(final String path)" not in objc:
    raise SystemExit("the runtime interface no longer has a road for a framework an engine can live without")
if "catch (IllegalArgumentException | UnsatisfiedLinkError missing)" not in objc:
    raise SystemExit("the optional framework road does not catch the two ways a missing image reports itself")
if 'ObjC.optionalLibrary("/System/Library/Frameworks/MetalFX.framework/MetalFX")' not in metal_fx:
    raise SystemExit("MetalFX's image is not loaded through the optional road")
if "SymbolLookup.libraryLookup(LOAD" in metal_fx or "METAL_FX.findOrThrow" in metal_fx:
    raise SystemExit("MetalFX is loaded or looked up in a way that throws when the system has no such framework")

# ---------------------------------------------------------------------------
# Availability is asked of the device, never of a version
#
# Apple's own question is `+[MTLFXSpatialScalerDescriptor supportsDevice:]`, and it is false on a GPU
# that cannot run the scaler whatever the system says. A version table here would be a second opinion
# that goes stale on the next system and cannot see the hardware at all.
# ---------------------------------------------------------------------------
if 'Msg.of("supportsDevice:", JAVA_LONG, ADDRESS)' not in metal_fx:
    raise SystemExit("the device is not asked Apple's own support question")
if "SUPPORTS_DEVICE.sendLong(scalerClass, device)" not in metal_fx:
    raise SystemExit("the support question is not asked of the scaler's own class object")
for forbidden in ("os.version", "System.getProperty(\"os", "MACOS_VERSION", "isAtLeast"):
    if forbidden in metal_fx:
        raise SystemExit(f"MetalFX availability is decided by {forbidden} rather than by asking the device")

# ---------------------------------------------------------------------------
# A class this backend only asks about is not a class it requires
#
# `ObjC.clazz` throws for a name nothing answers to, which is right for Metal and wrong for a framework
# that may not be installed.
# ---------------------------------------------------------------------------
if "private static MemorySegment classOrNull(final String name)" not in metal_fx:
    raise SystemExit("the descriptor class is fetched without a road for it being absent")
if "return ObjC.clazz(name);" not in metal_fx or "catch (Throwable missing)" not in metal_fx:
    raise SystemExit("the descriptor class is asked for in a way that throws when nothing answers")

# ---------------------------------------------------------------------------
# Asked once, kept, and said out loud
#
# The answer is a fact about the device and the system rather than about a frame, so it is asked at
# device creation and remembered; and it is logged either way, because the reason is what a reader needs
# when a session cannot scale.
# ---------------------------------------------------------------------------
if "if (asked) {" not in metal_fx or "asked = true;" not in metal_fx:
    raise SystemExit("the availability answer is asked more than once, or not kept")
if "public static String reason()" not in metal_fx:
    raise SystemExit("the reason for the answer is not available to a caller or a screen")
if 'Metallum.LOGGER.info("MetalFX spatial scaling: available, {}, factory {}"' not in metal_fx:
    raise SystemExit("availability is decided silently")
if 'Metallum.LOGGER.info("MetalFX spatial scaling: unavailable, {}"' not in metal_fx:
    raise SystemExit("a system that cannot scale is not told why")
if "MetalFx.spatialSupported(metalDeviceHandle);" not in device:
    raise SystemExit("the device never asks whether it can scale, so the answer is never reached")

# ---------------------------------------------------------------------------
# A scaler per configuration, and the selector is asked for rather than assumed
#
# Making a scaler compiles its own pipeline, so one a frame would be a per-frame compile: the cache is
# keyed by everything that would make a different scaler, and a configuration the device refused is
# remembered as refused rather than retried every frame. The factory's Objective-C selector is asked of
# the class, because the documentation names it in Swift and a wrong guess is a silent nil.
# ---------------------------------------------------------------------------
require = lambda label, source, needles: [
    needle for needle in needles if needle not in source
] and (_ for _ in ()).throw(SystemExit(f"{label}: missing " + ", ".join(
    needle for needle in needles if needle not in source)))

descriptor = (ROOT / "src/main/java/com/metallum/mtl/MTLFXSpatialScalerDescriptor.java").read_text(encoding="utf-8")
scaler = (ROOT / "src/main/java/com/metallum/mtl/MTLFXSpatialScaler.java").read_text(encoding="utf-8")

require("the factory is asked for, not assumed", descriptor, (
    '"newSpatialScalerWithDevice:"',
    '"makeSpatialScalerWithDevice:"',
    'RESPONDS_TO_SELECTOR.sendLong(scalerClass, ObjC.selector(selector))',
))
if "Msg.of(selector, ADDRESS, ADDRESS).sendPtr(handle, device)" not in descriptor:
    raise SystemExit("the factory is not the selector the class answered to")

require("the scaler is encoded in Apple's order", scaler, (
    'Msg.ofVoid("setColorTexture:", ADDRESS)',
    'Msg.ofVoid("setOutputTexture:", ADDRESS)',
    'Msg.ofVoid("setInputContentWidth:", JAVA_LONG)',
    'Msg.ofVoid("setInputContentHeight:", JAVA_LONG)',
    'Msg.ofVoid("encodeToCommandBuffer:", ADDRESS)',
))

require("one scaler per configuration", metal_fx, (
    "private record Configuration(",
    "private static final Map<Configuration, MTLFXSpatialScaler> scalers = new LinkedHashMap<>();",
    "private static final Map<Configuration, Boolean> refused = new LinkedHashMap<>();",
    "refused.put(configuration, Boolean.TRUE);",
    "scalers.put(configuration, scaler);",
    "public static void close() {",
))
if "MetalFx.close();" not in device:
    raise SystemExit("the cached scalers are not released when the device goes down")

if "tools/ci-metalfx.py" not in CI.read_text(encoding="utf-8"):
    raise SystemExit("this contract is not named by ci.yml, so nothing runs it")

# ---------------------------------------------------------------------------
# The door reflection can enter, and no selector sent blind
#
# Two faults found by running it. The pack-facing side reflects into this backend, and reflection cannot
# enter a package-private class however public the method on it is: the capabilities that already worked
# exposed a public class of their own, and so do these two. And a selector an object does not answer to
# is not a wrong number - it is an Objective-C exception that ends the process, which is what
# setInputContentOriginX: did when the spatial scaler was asked to move its content rectangle it does not
# have. Both rules are pinned here so a later edit cannot quietly unlearn them.
#
# A third fault was found the same way, and it is the reason the attachment door takes primitives. It used
# to take this layer's own value type, which the pack-facing side built by reflection from a class name -
# `com.metallum.render.AttachmentContents`, a path that does not exist, because the type is in
# `render.shared`. The lookup threw, every call was caught, and every pass silently kept its default for as
# long as the name was wrong. A name resolved at runtime is not an ABI; two arrays of booleans are.
# ---------------------------------------------------------------------------
require("the MetalFX door is public", (ROOT / "src/main/java/com/metallum/render/MetalScaleBridge.java").read_text(encoding="utf-8"), (
    "public final class MetalScaleBridge {",
    "public static boolean available(final Object encoder)",
    "public static boolean scale(",
))
attachment_door = (ROOT / "src/main/java/com/metallum/render/MetalAttachmentBridge.java").read_text(encoding="utf-8")
require("the attachment door is public", attachment_door, (
    "public final class MetalAttachmentBridge {",
    "public static void setNextPassContents(final Object encoder, final @Nullable boolean[] readAfterwards,",
    "final @Nullable boolean[] overwritten) {",
    "public static void setNextPassReadsStorageImage(final Object encoder",
))
if "setNextPassContents(final Object encoder, final @Nullable AttachmentContents[]" in attachment_door:
    raise SystemExit(
        "the attachment door hands this layer's own value type across a repository boundary, where it can only "
        "be resolved by name - and a name that moves stops answering without failing, which is the fault this "
        "door already had once"
    )
if "RESPONDS_TO_SELECTOR.sendLong(handle, ObjC.selector(\"setInputContentOriginX:\"))" not in scaler:
    raise SystemExit(
        "the scaler sends a selector it may not answer to; an unrecognized one is an Objective-C exception and ends the process"
    )

# ---------------------------------------------------------------------------
# The fence Apple documents for a resource Metal does not track
#
# Every texture this backend creates opts out of hazard tracking, which the documentation allows only
# on its own terms - the app then synchronises through a fence. The scaler is the one encoder in a
# frame that is not one of this engine's own, and MetalFX declares the property for exactly that case:
# `MTLFXSpatialScaler.fence` is the fence "this scaler waits for and updates". Without it the upscale's
# read of the input and write of the output sit in no part of the engine's fence chain, so a frame can
# sample an input that is still being stored or an output the scaler has not written yet. The binding
# still asks before it sends, for the reason above: an unrecognised selector ends the process.
# ---------------------------------------------------------------------------
require("the scaler takes a fence", scaler, (
    'Msg.ofVoid("setFence:", ADDRESS)',
    'ObjC.selector("setFence:")',
    "SET_FENCE.send(handle, fence)",
))
require("the encoder hands the frame's fence to the scaler",
        (ROOT / "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java").read_text(encoding="utf-8"), (
    "MetalFx.scale(device.metalDeviceHandle(), commandBuffer().handle(), fence.handle(), color,",
))
require("the scaler is given it before it encodes", (ROOT / "src/main/java/com/metallum/render/MetalFx.java").read_text(encoding="utf-8"), (
    "if (!scaler.fence(fence) && !fenceRefused) {",
))

# ---------------------------------------------------------------------------
# The Metal 4 scaler is a second path and not a parameter of the first
#
# Section 80: the logical configuration key may be shared, the native objects may not, because a scaler compiles
# its own pipeline and one generation's compiled pipeline is not the other's. So the Metal 4 path has its own
# class, its own cache and its own factory - and the factory needs a compiler object, which is the whole of the
# API difference the header declares (macOS 26's MTL4FXSpatialScaler.h takes an MTL4CommandBuffer, and the
# descriptor's Metal 4 spelling is `newSpatialScalerWithDevice:compiler:`).
#
# Its availability question is a functional one on purpose. `+supportsMetal4FX:` is Apple's own gate, and a
# device that answers yes can still refuse a scaler - so the answer reported to the capability record is the one
# that actually made a scaler and let it go. A `respondsTo`-only answer would tell the record that choosing
# Metal 4 keeps the render-scale setting while the device refuses every scaler it is asked for.
#
# And there is no fence on this path, which is a difference the two generations' APIs force rather than a
# preference: Metal 4 has no fence object in this engine at all - Metal4Fence records that the new command model
# orders work with encoder barriers and queue events - so what orders the scaler against the passes around it is
# the one command buffer's encode order. The pin holds that the Metal 4 scaler is never handed a Metal 3 fence.
# ---------------------------------------------------------------------------
METAL4_FX = ROOT / "src/main/java/com/metallum/mtl/metal4/Metal4Fx.java"
M4_SCALER = ROOT / "src/main/java/com/metallum/mtl/metal4/MTL4FXSpatialScaler.java"
M4_COMPILER = ROOT / "src/main/java/com/metallum/mtl/metal4/MTL4Compiler.java"
for path in (METAL4_FX, M4_SCALER, M4_COMPILER):
    if not path.is_file():
        raise SystemExit(f"the Metal 4 MetalFX path is missing {path.name}, so one generation of the scaler "
                         "has no implementation")

metal4_fx = METAL4_FX.read_text(encoding="utf-8")
m4_scaler = M4_SCALER.read_text(encoding="utf-8")
m4_compiler = M4_COMPILER.read_text(encoding="utf-8")
m4_encoder = (ROOT / "src/main/java/com/metallum/render/metal4/Metal4FrameEncoder.java").read_text(encoding="utf-8")

require("the Metal 4 scaler asks Apple's Metal 4 gate", metal4_fx, (
    'Msg.of("supportsMetal4FX:", JAVA_LONG, ADDRESS)',
    "if (!MTL4Probe.respondsTo(scalerClass, \"supportsMetal4FX:\")) {",
    "SUPPORTS_METAL4_FX.sendLong(scalerClass, device) == 0L",
))
require("the Metal 4 factory is the header's", metal4_fx, (
    'Msg.of("newSpatialScalerWithDevice:compiler:", ADDRESS, ADDRESS, ADDRESS)',
    'MTL4Probe.respondsTo(descriptor.handle(),\n                    "newSpatialScalerWithDevice:compiler:")',
    "NEW_SCALER_WITH_COMPILER.sendPtr(descriptor.handle(), device,",
))
require("availability is a functional question", metal4_fx, (
    "MTL4Compiler probeCompiler = MTL4Compiler.create(new MTLDevice(device));",
    "MTL4FXSpatialScaler probe = makeScaler(device, probeCompiler, new Configuration(1280, 720, 1920, 1080,",
    "supported = true;",
))
require("the Metal 4 path keeps its own scalers", metal4_fx, (
    "private final Map<Configuration, MTL4FXSpatialScaler> scalers = new LinkedHashMap<>();",
    "private final Map<Configuration, Boolean> refused = new LinkedHashMap<>();",
    "this.scalers.put(configuration, scaler);",
))
if "MetalFx." in metal4_fx or "MTLFXSpatialScaler " in metal4_fx:
    raise SystemExit(
        "the Metal 4 scaler path names the Metal 3 one, so the two generations share a native scaler - section 80 "
        "forbids it, and a shared compiled pipeline is the shape that would make it look fine until a resize"
    )
require("the Metal 4 scaler encodes into a Metal 4 command buffer", m4_scaler, (
    'Msg.ofVoid("encodeToCommandBuffer:", ADDRESS)',
    "ENCODE.send(this.handle, commandBuffer);",
    'RESPONDS_TO_SELECTOR.sendLong(this.handle, ObjC.selector("setInputContentOriginX:"))',
))
if "setFence:" in m4_scaler:
    raise SystemExit(
        "the Metal 4 scaler is handed a fence, and Metal 4 has no fence object in this engine: the ordering it "
        "would be given does not exist on this path"
    )
require("the compiler factory is the header's and every failure is an answer", m4_compiler, (
    'Msg.of("newCompilerWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS)',
    'device.respondsTo("newCompilerWithDescriptor:error:")',
    "if (ObjC.isNil(made)) {",
))
require("the frame path uses its own scaler and no fence", m4_encoder, (
    "this.metalFx = Metal4Fx.create(nativeDevice);",
    "return !this.closed && this.metalFx != null;",
    "return this.metalFx.scale(this.ring.commandBuffer(), color.nativeHandle(), output.nativeHandle(),",
    "if (this.metalFx != null) {\n            this.metalFx.close();",
))
if "MetalFx.scale(" in m4_encoder:
    raise SystemExit(
        "the Metal 4 frame path calls the Metal 3 scaler's encode, which takes an MTLCommandBuffer - the wrong "
        "object for this command model"
    )

print("MetalFX availability contract: PASS")
