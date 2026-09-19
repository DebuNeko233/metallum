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
# ---------------------------------------------------------------------------
require("the MetalFX door is public", (ROOT / "src/main/java/com/metallum/render/MetalScaleBridge.java").read_text(encoding="utf-8"), (
    "public final class MetalScaleBridge {",
    "public static boolean available(final Object encoder)",
    "public static boolean scale(",
))
require("the attachment door is public", (ROOT / "src/main/java/com/metallum/render/MetalAttachmentBridge.java").read_text(encoding="utf-8"), (
    "public final class MetalAttachmentBridge {",
    "public static void setNextPassContents(final Object encoder",
    "public static void setNextPassReadsStorageImage(final Object encoder",
))
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
        (ROOT / "src/main/java/com/metallum/render/MetalCommandEncoder.java").read_text(encoding="utf-8"), (
    "MetalFx.scale(device.metalDeviceHandle(), commandBuffer().handle(), fence.handle(), color,",
))
require("the scaler is given it before it encodes", (ROOT / "src/main/java/com/metallum/render/MetalFx.java").read_text(encoding="utf-8"), (
    "if (!scaler.fence(fence) && !fenceRefused) {",
))

print("MetalFX availability contract: PASS")
