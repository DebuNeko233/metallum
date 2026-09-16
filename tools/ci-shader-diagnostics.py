#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "src/main/java/com/metallum/render/MetalDevice.java"
source = DEVICE.read_text(encoding="utf-8")

required = (
    'Pattern.compile("\\\\b\\\\d+:(\\\\d+):")',
    "shaderCompileFailure(k.id(), sourceWithDefines, e)",
    'new StringBuilder("GLSL source around line ")',
    'line == failingLine ? ">> " : "   "',
    'String.format(Locale.ROOT, "%5d | %s", line, lines[line - 1])',
)
missing = [needle for needle in required if needle not in source]
if missing:
    raise SystemExit("shader compile diagnostic contract missing: " + ", ".join(missing))

if 'new IllegalStateException(shaderCompileFailure(k.id(), sourceWithDefines, e), e)' not in source:
    raise SystemExit("shader compile diagnostics must preserve ShaderCompileException as the cause")

print("shader compile diagnostic contract: PASS")
