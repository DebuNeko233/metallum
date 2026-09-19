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
if 'Metallum.LOGGER.info("MetalFX spatial scaling: {}, {}"' not in metal_fx:
    raise SystemExit("availability is decided silently")
if "MetalFx.spatialSupported(metalDeviceHandle);" not in device:
    raise SystemExit("the device never asks whether it can scale, so the answer is never reached")

if "tools/ci-metalfx.py" not in CI.read_text(encoding="utf-8"):
    raise SystemExit("this contract is not named by ci.yml, so nothing runs it")

print("MetalFX availability contract: PASS")
