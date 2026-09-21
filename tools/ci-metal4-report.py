#!/usr/bin/env python3
"""The final report's own shape, as a contract rather than as a hope.

Section 121 names the sections this report must carry and the fields each one must state, and section 122 makes
"docs updated" one of the things Metal 4's definition of done rests on. A report that quietly loses a section, or
loses the field a section is read by, is a report whose completeness nobody notices - which is exactly how this
document contradicted itself once before: the capability matrix was updated rung by rung while the narrative
sections beneath it were not, and a reader who took the Compute block at its word would have concluded the
compute road did not exist. The check is therefore mechanical: every section, and every field this plan asks a
section to state, is either in the file or this fails.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "metal4-full-frame-report.md"
text = REPORT.read_text(encoding="utf-8")

# Section 121's sections, in its own order.
SECTIONS = (
    "## Starting SHAs",
    "## Cold Probe",
    "## Native Smoke",
    "## M4 Frame",
    "## Render",
    "## Resource Binding",
    "## Blit",
    "## Compute",
    "## Synchronization",
    "## Lifecycle",
    "## MetalFX Spatial",
    "## Performance",
    "## Remaining blockers",
)

# And the fields each of those sections has to state, as section 121 lists them. `Starting SHAs` and
# `Synchronization` and `Remaining blockers` are named without a field list; the sha pair and the blocker list
# are checked by their own words below.
FIELDS = (
    "cold runs:", "warm probes:", "AUTO blocker:",
    "colour:", "vertex:", "uniform:", "texture/sampler:", "multi-pass:",
    "queue:", "allocator", "command buffer", "commit", "present",
    "basic:", "MRT:", "depth:", "blend:", "scissor:",
    "textures:", "samplers:", "uniform buffers:", "vertex/index:", "argument tables:", "residency:",
    "full:", "region:", "mipmap:",
    "dispatch:", "SSBO:", "storage image:", "render\u2192compute:", "compute\u2192render:",
    "F3+T:", "pack switch:", "world join:", "dimension:", "resize:", "fullscreen:", "shutdown:",
    "supported:", "configuration cache:", "M3 result:", "M4 result:", "performance:",
    "wallP50", "wallP95", "wallP99",
)

# The GPU percentiles are stated twice, because this engine has two APIs for them and section 92 says the two
# kinds are not interchangeable: Metal 3's arm reports `gpuP50/P95/P99` from `MTLCommandBuffer.gpuMillis` and this
# path's reports `gpuM4P50/P95/P99` from `MTL4CommitFeedback`. Each spelling is required, and a report that lost
# one of them would be a report that stopped saying what the other generation's GPU time is called.
GPU_FIELDS = tuple(
    spelling
    for quantile in ("50", "95", "99")
    for spelling in (f"gpuP{quantile}", f"gpuM4P{quantile}")
)

for section in SECTIONS:
    if section not in text:
        raise SystemExit("the report no longer carries the section section 121 asks for: " + section)

missing = [field for field in FIELDS + GPU_FIELDS if field not in text]
if missing:
    raise SystemExit("the report no longer states the field(s) section 121 asks for: " + ", ".join(missing))

# Starting SHAs states both repositories, and the final verdict section is what says whether the phrase is earned.
for needle, why in (
    ("STARTING_METALLUM_SHA", "the report does not name the Metallum sha it started from"),
    ("STARTING_VITRAIL_SHA", "the report does not name the Vitrail sha it started from"),
    ("## Metal 4 full-frame implementation complete?",
     "the report has no section that answers the question section 122 is about"),
    ("## The definition of done, item by item",
     "the report does not carry the definition of done item by item, so 'complete? YES' would rest on nothing"),
):
    if needle not in text:
        raise SystemExit("metal 4 report contract: " + why)

print("Metal 4 full-frame report contract: PASS")
