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

# The boundary an imageStore owes is decided by the pass that READS it, not by the pass that wrote
# it. Breaking the encoder at the write pays the whole boundary - every attachment of the next pass
# reloaded and stored again - on passes that read no storage image at all. What keeps that honest is
# the default: a pass nobody described asks for the boundary rather than going without one, because
# an unordered read of an untracked write is a wrong image and not a slower frame.
submit = command.index("public void submitRenderPass()")
flag = command.index("currentRenderPass.hasGraphicsStorageImageWrites()", submit)
closed = command.index("currentRenderPass = null;", flag)
if "this.storageUnordered = true;" not in command:
    raise SystemExit("graphics storage-image writes are no longer remembered for the pass that reads them")
remembered = command.index("this.storageUnordered = true;", closed)
if not submit < flag < closed < remembered:
    raise SystemExit("graphics storage-image writes are no longer remembered for the pass that reads them")
if "if (this.storageUnordered && readsStorageImage) {" not in command:
    raise SystemExit("the graphics storage-image boundary is not owed by the pass that reads")
create = command.index("public @NonNull RenderPassBackend createRenderPass(")
submit_at = command.index("public void submitRenderPass()")
if not create < command.index("this.storageUnordered && readsStorageImage") < submit_at:
    raise SystemExit(
        "the boundary a storage write owes is not decided where the pass that reads it is built"
    )
if "private boolean nextPassReadsStorageImage = true;" not in command:
    raise SystemExit("a pass nobody described no longer asks for the storage-image boundary")
if "this.nextPassReadsStorageImage = true;" not in command:
    raise SystemExit("one pass's storage-image answer is not reset before the next pass")
if command.count("storageUnordered = false;") != 2:
    raise SystemExit("the boundary a storage write owes does not leave with the encoder it was owed to")

for forbidden in ("Photon", "photon", "colorimg", "gbuffers_", "shadowtex"):
    if forbidden in render or forbidden in command:
        raise SystemExit("graphics storage-image backend contract leaked shader-pack semantics: " + forbidden)

print("Metal graphics storage-image ownership/synchronization contract: PASS")
