#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
render = (ROOT / "src/main/java/com/metallum/render/MetalRenderPass.java").read_text(encoding="utf-8")
command = (ROOT / "src/main/java/com/metallum/render/MetalCommandEncoder.java").read_text(encoding="utf-8")
compute = (ROOT / "src/main/java/com/metallum/render/MetalComputeBridge.java").read_text(encoding="utf-8")

if render.count("noteGraphicsStorageImageWrite(textureView);") != 2:
    raise SystemExit("direct and argument-buffer graphics storage-image paths must both invalidate ownership state")
for needle in (
    "((MetalGpuTexture) textureView.texture()).markContentsDirty();",
    "this.graphicsStorageImageWrites = true;",
    "boolean hasGraphicsStorageImageWrites()",
):
    if needle not in render:
        raise SystemExit("missing graphics storage-image ownership contract: " + needle)
if "((MetalGpuTexture) view.texture()).markContentsDirty();" not in compute:
    raise SystemExit("compute storage-image writes no longer invalidate texture clear state")

submit = command.index("public void submitRenderPass()")
flag = command.index("currentRenderPass.hasGraphicsStorageImageWrites()", submit)
closed = command.index("currentRenderPass = null;", flag)
fence = command.index("endEncoder();", closed)
if not submit < flag < closed < fence:
    raise SystemExit("graphics storage-image logical-pass boundary does not reach the native fence transition")

for forbidden in ("Photon", "photon", "colorimg", "gbuffers_", "shadowtex"):
    if forbidden in render or forbidden in command:
        raise SystemExit("graphics storage-image backend contract leaked shader-pack semantics: " + forbidden)

print("Metal graphics storage-image ownership/synchronization contract: PASS")
