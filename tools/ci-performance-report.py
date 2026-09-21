#!/usr/bin/env python3
"""The contract for Track G's unified report.

Section 45 of the long-term plan asks for a machine-readable report of a session: the repositories, the machine
and OS, the display mode, the target, the pack, the preset, the render scale, and then the arm's wall stats, CPU
stats, native census and structural census. `tools/vitrail-performance-report.py` is that report, and this file
is what keeps it honest.

Most of it runs against a session THIS FILE BUILDS, in a temporary directory, out of lines copied from a real
one: a report tool is only ever as good as its parser, and a parser tested against a live session is tested
against whatever that session happened to contain. The fixture below carries the shapes that have already broken
it once - a `passSizes` list with commas and colons in it, a one-group census line, and a wait line whose fields
are named like the frame's - so a regression is a failure here rather than a wrong number in a document.
"""
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/vitrail-performance-report.py"

# One probe window, copied from run/w1-interval/i1 and cut down to what the report reads. The passSizes list is
# the whole of it: a narrower value pattern read it as `2048x2048` and dropped four other pass sizes in silence.
PROBE = """[00:00:01] [Render thread/INFO] (metallum) frame-probe openers renderPasses=14350 blitEncoders=3000 computeEncoders=0 clearEncoders=600
[00:00:01] [Render thread/INFO] (metallum) frame-probe 600/600 windowFrames=600 windowMs=4972.35 gpuFrames=600 gpuMs=4978.72 selectedGeneration=metal3 executingGeneration=metal3 encoders=14350 passChanged=13750 submit=600 loadedMiB=193089.6 storedMiB=276044.2 depthAttachments=4500 blits=4800 blittedMiB=58175.4 pipeline=17965 texture=52680 sampler=52680 buffer=114780 viewport=0 scissor=13500 depthBias=0 compiles=0 compileMs=0.00 unarmedCompiles=706 unarmedCompileMs=24.63 unarmedCompileMaxMs=0.27 unarmedRenderCompiles=272 unarmedRenderCompileMs=11.22 unarmedFunctions=168 unarmedFunctionMs=10.28 unarmedFunctionMaxMs=0.25 unarmedRenderFunctions=113 unarmedRenderFunctionMs=5.69 pipelineIdentities=334 pipelineKeys=334 wallP50=8.36 wallP95=10.12 wallP99=10.86 wallMax=11.69 wallMaxAt=169 gpuP50=7.62 gpuP95=9.11 gpuP99=9.14 gpuMax=9.21 windowTicks=99 framesPerTick=6.06 frameCpuMs=966.63 allocKiB=126080.3 passFullSize=1000 passSmaller=13100 passSizes=2048x2048:1000,1920x1200:12000,1024x1024:100,960x600:600,512x512:100,256x256:100,128x128:100,16x16:100
[00:00:01] [Render thread/INFO] (metallum) frame-probe waits drawable calls=600 p50=0.05ms p95=0.06ms max=0.09ms total=22.45ms; submitWindow calls=1200 p50=0.00ms p95=7.92ms max=8.35ms total=4002.15ms
"""

LOG = """[00:00:20] [Render thread/INFO] (Vitrail) Drawing ComplementaryReimagined_r5.9.1 from world0 for minecraft:overworld, at 1920x1200, 8 full screen passes
[00:00:21] [Render thread/INFO] (metallum) Using graphics backend Metal
[00:00:21] [Render thread/INFO] (Vitrail) The render scale is 100%, so the world is drawn at the window's own size and MetalFX is off
[00:00:22] [Render thread/INFO] (Vitrail) 4 targets are copied back from their far half at the end of every frame, because the pack keeps them and the chain left them there: [1, 2, 4, 7]
[00:00:23] [Render thread/INFO] (Vitrail) Shadow walk: 121 walks (120.4 a second), kept 975 a walk, drew 947 a walk, 22104 loaded, terrain=true culling=DEFAULT SWEPT r=192
[00:00:23] [Render thread/INFO] (Vitrail) Shadow casters: 0 frames gathered, 0.0 entities and 0.0 block entities a frame
[00:00:23] [Render thread/INFO] (Vitrail) Shadow map: the opaque world was drawn into it 300 times in the last 600 frames
[00:00:23] [Render thread/INFO] (Vitrail) Mip chains: 484 reduced over 1004 ms (481.6 a second), 5324 levels (11.0 a chain), 371678120 pixels (767930 a frame at 481.6 a second), by target Vitrail colortex5 alt=121,Vitrail colortex0 alt=121
[00:00:24] [Render thread/INFO] (Vitrail) Module cache: 495 units served, 0 built by the compiler, 495 and 0 since this launch, 10.6 MB in /somewhere
[00:00:24] [Render thread/INFO] (Vitrail) 62 of 62 leftover pipelines compiled ahead of their first draw, 273 ms of background work, translations included
"""


def fixture(root: Path) -> Path:
    session = root / "session"
    for arm in ("i1", "i2"):
        directory = session / arm
        directory.mkdir(parents=True)
        (directory / "probe.txt").write_text(PROBE, encoding="utf-8")
        (directory / "latest.log").write_text(LOG, encoding="utf-8")
        (directory / "load.txt").write_text("cpus 15\nstart 2.02 3.08 3.70\nend 1.53 2.82 3.58\n", encoding="utf-8")
        # The code the arm ran, as the harness records it. The second arm's sources are `dirty` - put back to an
        # earlier commit, which is how the acceptance's own baseline was re-measured in the machine state the head
        # was read in - and the recorded SHA is deliberately NOT the one this contract passes on the command line:
        # the report must carry what the arm recorded, not what its caller asserted.
        (directory / "source-revision.txt").write_text(
            "metallum deadbee0000 perf/optimisation\nmetallum-source "
            + ("clean\n" if arm == "i1"
               else "M src/main/java/com/metallum/render/shared/MetalFrameProbe.java\n")
            + "metallum-tools clean\n"
            + "vitrail cafef00 perf/optimisation\nvitrail-source clean\nvitrail-tools clean\n",
            encoding="utf-8")
    (session / "order.txt").write_text("i1\ni2\n", encoding="utf-8")
    (session / "display-mode-before.txt").write_text("66 1800 1169\n", encoding="utf-8")
    return session


def report(session: Path, *extra: str) -> dict:
    result = subprocess.run([sys.executable, str(TOOL), str(session), *extra],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> int:
    if not TOOL.is_file():
        raise SystemExit("the report tool is missing: section 45's report has no implementation")

    source = TOOL.read_text(encoding="utf-8")
    for needle, why in (
        ('"schema": "vitrail-performance-report/1"', "the report carries no schema name, so a reader cannot "
                                                      "tell which shape it was written against"),
        ('"repositories"', "the report does not carry the repository SHAs section 45 asks for"),
        ('"machine"', "the report does not carry the machine or the OS"),
        ('"display_mode"', "the report does not carry the display mode the session ran on"),
        ('"pacing"', "the report does not group the wall and GPU distribution"),
        ('"cpu"', "the report does not carry the CPU and allocation stats"),
        ('"native"', "the report does not carry the native call census"),
        ('"structural"', "the report does not carry the structural census"),
        ('"census"', "the report does not carry the engine's one-a-second censuses"),
        ("WAITS.sub", "the wait lines are not taken out of the flat scan, so their p50 lands under a name that "
                      "looks like the frame's"),
        ('isinstance(groups, str)', "a one-group census line is read as a tuple of characters - 'Metal' became "
                                    "five letters, measured"),
    ):
        if needle not in source:
            raise SystemExit("unified performance report: " + why)

    with tempfile.TemporaryDirectory() as temporary:
        document = report(fixture(Path(temporary)), "--metallum", "deadbee", "--vitrail", "cafef00")

    if document["repositories"] != {"metallum": "deadbee", "vitrail": "cafef00"}:
        raise SystemExit("unified performance report: the SHAs it was given are not the SHAs it printed")
    if not document["machine"].get("os"):
        raise SystemExit("unified performance report: the machine section is empty")
    session = document["sessions"][0]
    if session["display_mode"] != "66 1800 1169" or session["order"] != ["i1", "i2"]:
        raise SystemExit("unified performance report: the session's own state - display mode and order - is not "
                         "carried")
    if len(session["arms"]) != 2:
        raise SystemExit("unified performance report: an arm of the session is missing from the report")

    arm = session["arms"][0]
    sizes = arm["structural"]["passSizes"]
    if sizes.count(":") != 8:
        raise SystemExit(f"unified performance report: passSizes was cut short - {sizes!r} carries "
                         f"{sizes.count(':')} of the window's 8 sizes")
    if arm["structural"]["loadedMiB"] != 193089.6:
        raise SystemExit("unified performance report: a structural counter is wrong or missing")
    if arm["native"]["unarmedFunctions"] != 168:
        raise SystemExit("unified performance report: the unarmed compile census is not carried")
    if arm["census"]["backend"] != "Metal":
        raise SystemExit(f"unified performance report: the backend line was read as {arm['census']['backend']!r}")
    if arm["census"]["render_scale"] != 100:
        raise SystemExit("unified performance report: the render scale is not read from the engine's own line")
    if arm["census"]["shadow_draws"] != [300, 600]:
        raise SystemExit("unified performance report: the shadow draw census is not carried")
    if arm["census"]["module_cache"][:2] != [495, 0]:
        raise SystemExit("unified performance report: the module cache census is not carried")
    if arm["census"]["target_drawn"][:3] != ["ComplementaryReimagined_r5.9.1", "world0", "minecraft:overworld"]:
        raise SystemExit("unified performance report: the pack and the target are not carried")
    if arm["pacing"].get("wallTail") != round(11.69 / 10.86, 2):
        raise SystemExit(
            f"unified performance report: the window's tail against its own P99 is not reported - {arm['pacing']}"
        )
    # The code each arm ran, recorded rather than asserted: the SHAs here are the arms' own and not the
    # `--metallum deadbee` this contract passed in, which is the whole point of writing them down.
    if arm["source"].get("metallum") != "deadbee0000" or arm["source"].get("metallum_branch") != "perf/optimisation":
        raise SystemExit(f"unified performance report: the revision an arm recorded is not carried - {arm['source']}")
    if arm["source"].get("metallum_source") != "clean":
        raise SystemExit(f"unified performance report: an arm that ran the checkout is reported as modified - "
                         f"{arm['source']}")
    if arm["source"].get("metallum_tools") != "clean":
        raise SystemExit(f"unified performance report: the state of the measuring tools is not carried, so a "
                         f"session run with a changed harness reads as a clean one - {arm['source']}")
    second = session["arms"][1]["source"]
    if second.get("metallum_source") != "M src/main/java/com/metallum/render/shared/MetalFrameProbe.java":
        raise SystemExit(f"unified performance report: an arm whose sources were put back to an earlier commit "
                         f"reads as one that ran the checkout - {second}")
    recorded = session["source_recorded"]
    if len(recorded) != 2 or recorded[0]["arms"] != ["i1"] or recorded[1]["arms"] != ["i2"]:
        raise SystemExit(f"unified performance report: a session that measured two revisions of the code does not "
                         f"say which arm was which - {recorded}")

    if arm["waits"]["submitWindow"]["calls"] != 1200:
        raise SystemExit("unified performance report: the instrumented waits are not carried as their own group")
    if "p50" in arm.get("other", {}):
        raise SystemExit("unified performance report: a wait line's p50 is still in the flat scan, where it "
                         "cannot be told from the frame's")

    print("unified performance report contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
