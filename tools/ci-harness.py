#!/usr/bin/env python3
"""Contracts for the measurement harness and the reports it feeds.

This file is the merge of the contract scripts that used to guard this subject separately, so that
the pull-request surface is one script a subject rather than one a rule. Every check below is the
check it was, at the point it was: the merge moved code between files, it did not reword any of it.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_common import ROOT, check_launcher, forbid, read, require, source_tree  # noqa: E402

# Each merged member that used to end in `if __name__ == "__main__": raise SystemExit(main())`
# appends its own status here instead, because a `raise` after the first one would skip the
# rest of the file - and the file is several contracts now.

# Each merged member that used to end in `if __name__ == "__main__": raise SystemExit(main())`
# appends its own status here instead, because a `raise` after the first one would skip the
# rest of the file - and the file is several contracts now.
_MAIN_STATUS: list[int] = []


# ==================== was tools/ci-contracts.py ====================
check_launcher("tools/run-vitrail-smoke.sh", (
    "--mrt-fixture", "--terrain-fixture", "--gbuffer-location-fixture", "--gbuffer-format-fixture",
    "--gbuffer-clear-fixture", "--gbuffer-write-fixture", "--gbuffer-sampling-fixture", "--gbuffer-pingpong-fixture",
    "--armor-glint-fixture", "--block-entity-fixture", "--entity-fixture", "--hand-fixture", "--hand-water-fixture",
    "--hand-glint-fixture", "--hand-water-glint-fixture", "--spider-eyes-fixture",
    "gbuffer-location-contract", "gbuffer-format-contract", "gbuffer-clear-contract", "gbuffer-write-contract",
    "gbuffer-sampling-contract", "gbuffer-pingpong-contract", "VerifyMrtScreenshot.java", "VerifyTerrainScreenshot.java",
    "armor-glint-contract", "VerifyArmorGlintScreenshot.java", "block-entity-contract", "VerifyBlockEntityScreenshot.java",
    "entity-contract", "VerifyEntityScreenshot.java", "hand-contract", "hand-water-contract", "VerifyHandScreenshot.java",
    "hand-glint-contract", "hand-water-glint-contract", "VerifyHandGlintScreenshot.java", "spider-eyes-contract",
    "VerifySpiderEyesScreenshot.java", "run/logs/latest.log", "Using graphics backend Metal",
))
check_launcher("tools/run-vitrail-sky-smoke.sh", (
    "sky-contract", "VerifySkyScreenshot.java", "--overworld", "--end", "gbuffers_skybasic", "gbuffers_skytextured",
    "render stage SKY", "render stage SUNSET", "render stage CUSTOM_SKY", "minecraft:textures/atlas/celestials",
    "minecraft:textures/environment/end_sky", "[colortex1 MAIN]", "coverage mask", "Stopping!",
))
check_launcher("tools/run-vitrail-cloud-smoke.sh", (
    "clouds-contract", "VerifyCloudScreenshot.java", "gbuffers_clouds", "render stage CLOUDS", "0 samplers",
    "[colortex1 MAIN]", "Stopping!",
))
check_launcher("tools/run-vitrail-weather-smoke.sh", (
    "weather-contract", "VerifyWeatherScreenshot.java", "gbuffers_weather", "RAIN_SNOW", "[colortex1 MAIN]", "Stopping!",
), regex=(r"textures/environment/\(rain\|snow\)",))
check_launcher("tools/run-vitrail-particle-smoke.sh", (
    "--opaque", "--translucent", "particles-opaque-contract", "particles-translucent-contract", "VerifyParticleScreenshot.java",
    "Drawing the ${pass_name} particles pass with ${program} of ${fixture_name} at render stage PARTICLES",
    "minecraft:textures/atlas/particles.png", "[colortex1 MAIN]", "It also writes the coverage mask", "Stopping!",
))
check_launcher("tools/run-vitrail-depthtex0-smoke.sh", (
    "depthtex0-contract", "VerifyDepthtex0Screenshot.java", "minecraft:overworld",
    "The world's depth is converted into the pack's window in two images", "The scene's depth is kept", "Stopping!",
))
check_launcher("tools/run-vitrail-depth-batch-smoke.sh", (
    "depthtex1-contract", "depthtex2-contract", "pre-translucent-contract", "VerifyDepthBatchScreenshot.java",
    "--depthtex1", "--depthtex2", "--pre-translucent", "1 samplers this chain read the world",
    "1 more before its translucents [deferred]", "Vitrail depth window", "Stopping!",
))
check_launcher("tools/run-vitrail-depth-final-smoke.sh", (
    "pre-hand-contract", "depth-conversion-contract", "VerifyDepthFinalScreenshot.java", "HAND_SOLID",
    "The depth before the hand is converted into the pack's window in one more image",
    "The world's depth is converted into the pack's window in two images", "Stopping!",
))
check_launcher("tools/run-vitrail-shadow-terrain-smoke.sh", (
    "shadow-terrain-contract", "VerifyShadowTerrainScreenshot.java", "shadow_solid", "shadow_cutout", "shadow_water",
    "pass='shadow_translucent'", "RAW LIGHT-SPACE shadowcolor0 diagnostic", "Shadow map allocated at ",
    "minecraft:textures/atlas/blocks.png", "Stopping!",
))
check_launcher("tools/run-vitrail-shadow-batch-smoke.sh", (
    "shadow-entities-contract", "shadow-depth-contract", "shadow-color-contract", "VerifyShadowBatchScreenshot.java",
    "--entities", "--depth", "--color", "--verify-existing", "entity pass with shadow_entities",
    "shadow_translucent chunk pass with shadow", "shadowcolor0 and shadowcolor1",
    "latest completed shadow batch without launching Minecraft", "shadow mipmaps remain pending", "Stopping!",
), forbidden=("entities in the shadow map pass with shadow_entities",))
check_launcher("tools/run-vitrail-shadow-mipmap-smoke.sh", (
    "shadow-mipmap-contract", "VerifyShadowMipmapScreenshot.java", "--verify-existing", "both shadowtex0 and shadowtex1",
    "shadow_solid chunk pass with shadow", "readable generated shadow depth mips", "Stopping!",
    "and ([2-9]|[1-9][0-9]+) where it reads shadowtex1",
))
check_launcher("tools/run-vitrail-deferred-smoke.sh", (
    "deferred-contract", "VerifyDeferredScreenshot.java", "--verify-existing", "deferred writes colortex0 alt",
    "deferred1 writes colortex0 main", "deferred2 writes colortex0 alt", "final writes the game's own target", "Stopping!",
))
check_launcher("tools/run-vitrail-deferred-depth-smoke.sh", (
    "deferred-depth-contract", "VerifyDeferredDepthScreenshot.java", "--verify-existing", "deferred writes colortex0 alt",
    "deferred1 writes colortex0 main", "deferred2 writes colortex0 alt", "samplers this chain read the world's depth",
    "depthtex0", "The world's depth is converted into the pack's window in two images", "Vitrail depth window", "Stopping!",
))
check_launcher("tools/run-vitrail-deferred-tail-smoke.sh", (
    "deferred-mrt-contract", "deferred-mipmap-contract", "VerifyDeferredTailScreenshot.java", "2 targets doubled: \\[0, 1\\]",
    "level\\(s\\)", "PHASE 10 deferred MRT: PASS", "PHASE 10 deferred mipmap: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-composite-smoke.sh", (
    "composite-flip-contract", "composite-history-contract", "VerifyCompositeScreenshot.java", "--verify-existing",
    "PHASE 11 composite flip parity: PASS", "PHASE 11 composite temporal/history: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-final-smoke.sh", (
    "final-direct-contract", "final-chain-contract", "VerifyFinalScreenshot.java", "--verify-existing",
    "PHASE 12 final direct: PASS", "PHASE 12 final chain-to-screen: PASS", "Batched PHASE 12 Final: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-dimension-routing-smoke.sh", (
    "dimension-convention-contract", "dimension-properties-contract", "VerifyDimensionRoutingScreenshot.java",
    "world0 for minecraft:overworld", "world-1 for minecraft:the_nether", "world1 for minecraft:the_end",
    "surface for minecraft:overworld", "under for minecraft:the_nether", "catchall for minecraft:the_end",
    "--verify-existing", "Batched PHASE 13 Dimension Routing: PASS", "Stopping!",
))
check_launcher("tools/run-vitrail-wide-resources-smoke.sh", (
    "wide-resources-contract", "VerifyWideResourcesScreenshot.java", "sampledImages=33", "Wide resource pipeline",
    "--verify-existing", "Batched PHASE 14 Wide Resources: PASS", "Stopping!",
))


# ==================== was tools/ci-vitrail-performance.py ====================
"""Pins the performance harness's shape, so that measuring this engine stays possible alone.

The harness is the only thing in either repository that can take a measurement without its owner:
it writes the pack selection the UI would have written, launches the client into a world, arms the
frame probe only once the pack has drawn a full frame, and collects the probe's window and a picture.
Every assertion here is about a property that made a hand-run measurement worthless at least once - a
window armed before there was a world, a pack named in the script rather than handed to it, a pack
committed to the repository instead of copied into an ignored dev instance - or about the one thing
that keeps the numbers honest, which is that they are the probe's own and not a second opinion.
"""
import struct
import zlib

LAUNCHER = ROOT / "tools/run-vitrail-performance.sh"
COMPARE = ROOT / "tools/vitrail-performance-compare.py"
CI = ROOT / ".github/workflows/ci.yml"
GITIGNORE = ROOT / ".gitignore"

launcher = LAUNCHER.read_text(encoding="utf-8")
compare = COMPARE.read_text(encoding="utf-8")

subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)


def before(first: str, second: str, why: str) -> None:
    if first not in launcher or second not in launcher:
        raise SystemExit(why + " -- one of the two steps is not in the launcher at all")
    if not launcher.index(first) < launcher.index(second):
        raise SystemExit(why)


# ---------------------------------------------------------------------------
# A window worth counting
#
# The probe arms on the marker's return, so a marker that exists before the launch counts the frames
# before there is a world - which is how three hand-run windows in a row came back measuring a menu.
# The order is the whole of the fix: gone before the client starts, back only once the pack has drawn
# a full frame, and gone again when the runs are over.
# ---------------------------------------------------------------------------
before(
    'rm -f "$marker"\n\t: > "$game_dir/logs/latest.log"',
    "./gradlew runClient",
    "the marker is not cleared before the client starts, so a window would count the frames before a world",
)
before(
    'wait_for_log "$arm_pattern"',
    'touch "$marker"',
    "the marker is not held back until the scene has drawn a frame",
)
for setting in ('arm_pattern="Time elapsed:"', 'arm_pattern="first full frame opened"'):
    if setting not in launcher:
        raise SystemExit(
            "the harness no longer chooses what a window waits for by the run's shape, so a run with no "
            f"pack would wait for a pack frame that never comes (missing {setting})"
        )
if 'rm -f "$marker"\nfi' not in launcher:
    raise SystemExit("the marker outlives the runs, so the next session would arm from a leftover file")

# ---------------------------------------------------------------------------
# A launch that failed costs seconds and not a timeout
#
# The first launch this harness ever made never started a client: Gradle read the game's arguments as
# the option after --args rather than as its value, because a word beginning with two dashes is an
# option to its parser. The harness waited out its whole timeout for a client that was already gone,
# which is the same bug in a second costume - so both halves are pinned here.
# ---------------------------------------------------------------------------
# Vitrail puts the graphics API back to Vulkan by design after a session that ended badly, so a run that
# follows a failed one comes up on MoltenVK and every number it produces is about another engine. The
# harness writes the API before the run and refuses to call a run on anything else a measurement.
if 'grep -q "Using graphics backend Metal"' not in launcher:
    raise SystemExit(
        "the harness does not check which backend a run came up on, so a rescued session measures MoltenVK "
        "and reports it as this engine"
    )

if '"--args=--quickPlaySingleplayer' not in launcher:
    raise SystemExit("the game's arguments are not passed with --args=, so Gradle reads them as options")
if 'wait_for_log "$arm_pattern" "$deadline" "$launcher"' not in launcher:
    raise SystemExit("the wait does not watch the launcher, so a launch that failed looks like a slow one")
if "return 2" not in launcher:
    raise SystemExit("a launcher that exited is waited on until the timeout instead of ending the wait")

# ---------------------------------------------------------------------------
# A pack the harness is handed, never one it knows
#
# Shader packs are not redistributable and this repository is not where one lives. The pack arrives as
# an argument, is copied into the dev instance under run/, and is never named here.
# ---------------------------------------------------------------------------
if "--pack)" not in launcher:
    raise SystemExit("the pack is no longer an argument of the harness")
for pack in ("photon", "complementary", "bliss", "solas", "sundial", "makeup", "bsl", "sildur"):
    if pack in launcher.lower():
        raise SystemExit(f"the harness names a shader pack, which it may not: {pack}")
if 'cp -f "$pack_path" "$pack_dir/$pack_name"' not in launcher:
    raise SystemExit("the pack is not copied into the dev instance")
if 'pack_options="$pack_path.txt"' not in launcher or 'cp -f "$pack_options" "$pack_dir/$pack_name.txt"' not in launcher:
    raise SystemExit("the pack's own options are not staged beside it, so a run measures the pack's defaults")
if "run/" not in GITIGNORE.read_text(encoding="utf-8"):
    raise SystemExit("the dev instance is no longer ignored by git, so a run could be committed")

# ---------------------------------------------------------------------------
# The selection the UI would have made, made here
#
# Both files are what the game reads at startup, which is what lets a run come up on the pack and on
# the Metal path without anybody clicking.
# ---------------------------------------------------------------------------
# A comparison is two launches of one world, and a live world does not draw the same frame twice: the
# sun moves, mobs spawn and weather comes and goes. The staged world is frozen before the client starts,
# and the tool that does it proves its own round-trip before it is trusted with a real save.
# The weather is passed because the state a world is *left* in decides what vanilla draws, and the still-life
# scene stays the default: a comparison wants neither the storm the save was holding nor a mob that moved
# between two launches, and a measurement of what vanilla draws asks for both by switch.
if 'tools/freeze-world.py" "$saves_dir/$world_name" --weather "$weather" --spectator' not in launcher:
    raise SystemExit(
        "the harness does not freeze the world it stages, or does not say what weather it leaves it in, so "
        "two launches draw two scenes"
    )
if '$([[ "$keep_entities" == true ]] && echo "" || echo "--still-life")' not in launcher:
    raise SystemExit(
        "the still-life scene is no longer the default, so an entity left in the world makes two launches of "
        "one configuration draw two different frames"
    )
subprocess.run(["python3", str(ROOT / "tools/freeze-world.py"), "--self-test"], check=True)
if "--continue-world" not in launcher or 'rm -rf "$saves_dir/$world_name"' not in launcher:
    raise SystemExit(
        "the world is not staged again before each run, so two runs of a comparison start at two "
        "different times of day and the comparison measures the world's clock rather than the switch"
    )
if 'cp -R "$world_path" "$saves_dir/$world_name"' not in launcher:
    raise SystemExit("the world is no longer copied into the dev instance at all")
if "--renderscale)" not in launcher or "renderscale=$renderscale" not in launcher:
    raise SystemExit(
        "the render scale is not an argument of the harness, so the seat the upscaling phase replaces cannot be measured"
    )
for needle, why in (
    ('pack=$pack_name', "the pack selection is not written before the launch"),
    ("enabled=true", "the written pack selection does not switch shaders on"),
    ("preferredGraphicsApi=metal", "the written preference does not ask for the Metal path"),
):
    if needle not in launcher:
        raise SystemExit("the dev instance is not prepared: " + why)

# ---------------------------------------------------------------------------
# The jar measured is the jar this run built
#
# Every branch a developer has built leaves its jar in the same output directory, so a listing of
# that directory is not a statement about what was just built: the harness asks the build instead,
# through an init script whose task prints the archive the jar task wrote.
# ---------------------------------------------------------------------------
if "vitrail-perf-jar=" not in launcher:
    raise SystemExit("the harness does not ask the build which jar it produced")
if ":fabric:vitrailPerfJarPath" not in launcher:
    raise SystemExit("the harness does not run the task that names the jar")
if "-print -quit" in launcher:
    raise SystemExit("the harness picks its jar out of a directory listing, which is not the one it built")

# ---------------------------------------------------------------------------
# One session at a time
#
# The numbers of a run are the numbers of the machine it was made on, so another client drawing into the
# same GPU and the same display is a scene fact and not a nuisance. Measured, not hypothetical: three
# clients whose render threads had stopped - the shape a GPU fault leaves behind - were still resident
# thirty to forty-seven minutes later, through two later sessions' windows, because the stop sent SIGTERM
# and a client that is no longer drawing does not act on it. So the harness refuses to start beside one,
# and its stop escalates to SIGKILL and says so if even that does not take.
# ---------------------------------------------------------------------------
if 'if [[ -n "$(client_pids)" ]]; then' not in launcher:
    raise SystemExit(
        "the harness does not check for a client left over from an earlier session, so a run can be measured "
        "beside another one drawing into the same GPU and display"
    )
before(
    'if [[ -n "$(client_pids)" ]]; then',
    "./gradlew runClient",
    "the leftover-client check runs after the client is launched, which is not a check",
)
if 'kill -9 "$pid"' not in launcher:
    raise SystemExit(
        "the stop does not escalate to SIGKILL, and a client whose render thread has stopped does not act on "
        "SIGTERM - measured, and it was still resident while later sessions measured"
    )
before(
    'for pid in $(client_pids "$world_name"); do kill "$pid"',
    'for pid in $(client_pids "$world_name"); do kill -9 "$pid"',
    "SIGKILL is sent before the client has had its chance to exit on SIGTERM",
)
if "stale_client=1" not in launcher or "exit 7" not in launcher:
    raise SystemExit(
        "a client that could not be stopped is not reported, so the arms after it would be compared as if they "
        "had been measured alone"
    )

# ---------------------------------------------------------------------------
# A picture the harness can actually take
#
# The picture evidence is a screenshot of the display, and a locked or asleep display captures as one flat
# colour. Measured: every capture of two sessions was black, and the comparison printed "0.00% of pixels
# differ" for two pictures of nothing twice - the strongest verdict the tool can print, about no evidence.
# So the instrument is checked before the session spends its launches, and the comparison's refusal is
# carried to the harness's own exit code rather than being swallowed.
# ---------------------------------------------------------------------------
if "--capture-check" not in launcher:
    raise SystemExit(
        "the harness does not check that the display can be captured before it measures, so a locked display "
        "produces a session of pictures of nothing that compares as perfect agreement"
    )
before(
    'python3 "$repo_root/tools/vitrail-performance-compare.py" --capture-check',
    "./gradlew runClient",
    "the display is checked for a picture after the first launch, which is where the cost of finding out is",
)
if "compare_status" not in launcher or "exit 9" not in launcher:
    raise SystemExit(
        "the comparison's refusal over flat captures is not carried to the harness's exit code, so a session "
        "whose pictures were never photographed can still end zero"
    )
# And each way of finding out has to be carried to that flag: said out loud, and remembered inside its own
# branch. A message with no flag behind it is worse than no message, because the session that follows it reads
# as a photographed one. Presence is checked before position, so a line an edit deleted is reported as the
# defect it is instead of as a traceback from this file.
for said, terminator, why in (
    ('echo "The display could not be captured', "elif ! python3", "a capture that failed"),
    ('echo "The display captures as one flat colour', "\nfi", "the display capturing flat"),
):
    if said not in launcher:
        raise SystemExit(f"the harness no longer says {why} out loud, so a session whose picture column is void "
                         f"is not told about it")
    at = launcher.index(said)
    if "picture_void=1" not in launcher[at:launcher.index(terminator, at)]:
        raise SystemExit(f"the harness says {why} and then carries on without marking the session's picture "
                         f"column void, so photographs of nothing read as photographs of the frame")
if 'if [[ "$compare_status" == 4 || "${picture_void:-0}" == 1 ]]; then' not in launcher:
    raise SystemExit("the harness does not end non-zero when its picture column is void, so a session whose "
                     "pictures were never photographed can still read as a session that agreed")

# ---------------------------------------------------------------------------
# The window is the harness's length and not the probe's
#
# Two windows of different lengths are not two windows of one thing, so --frames has to reach the
# probe's own budget rather than being a number the harness keeps to itself.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# A pack's frame is not vanilla's frame, and the switches are how the difference is measured
#
# A pack draws its own clouds, so every pack comparison sets `renderClouds` false and every baseline this
# harness has taken has no vanilla clouds in it. Vanilla's own rendering - clouds, the weather's particles,
# mobs - is a different question and needs the things themselves in the frame, which is what these three
# switches are for. Each is off by default, because a baseline written before them is not moved by a switch
# nobody asked for.
# ---------------------------------------------------------------------------
for needle, why in (
    ("--vanilla-clouds) vanilla_clouds=", "the harness cannot put the game's own clouds in a frame, so a "
     "measurement of them needs a keyboard"),
    ('VITRAIL_PROFILE_CLOUD_MODE', "the harness's cloud mode never reaches the options writer, so `fast` "
     "would be written as the boolean `true` and the run would measure the fancy cloud while saying it "
     "measured the flat one"),
    ('"renderClouds": f', "the profile still writes one fixed answer for renderClouds, so the "
     "clouds switch cannot reach the game's options"),
    ('VITRAIL_PROFILE_CLOUDS', "the clouds switch never reaches the profile writer"),
    ("--weather) weather=", "the harness cannot leave the world raining, so vanilla's largest particle system "
     "cannot be in a frame without a keyboard"),
    ("--dimension) dimension=", "the harness cannot choose the dimension its scene is staged in, so a save "
     "left in the nether stages a nether - no sky, no clouds - whatever the rest of the scene says"),
    ('--dimension "$dimension" \\', "the harness's dimension choice never reaches freeze-world, so the staged "
     "player records keep the dimension the save was left in"),
    ("--keep-entities) keep_entities=true", "the harness always takes the world's entities out, so nothing a "
     "mob or a block entity draws can be measured"),
    ("--vanilla-particles) vanilla_particles=true", "the harness cannot stage the vanilla particle fixture"),
    ("--vanilla-mobs) vanilla_mobs=true", "the harness cannot stage the entity fixture, and the staged world "
     "holds no entities of its own, so nothing a mob draws can be in a frame"),
    ("--vanilla-blocks) vanilla_blocks=true", "the harness cannot stage the block-entity fixture, and what a "
     "block's own renderer draws is neither terrain nor an entity, so no scene before it contained one"),
    ("--vanilla-sign) vanilla_sign=true", "the harness cannot stage the sign fixture, and a sign's glyphs are "
                                           "the only live workload on this machine that asks for a depth bias"),
    ("for fixture in showcase mobshow blockshow signshow; do", "a fixture is checked against the game having loaded it "
     "for only some of them, so another can stage and emit nothing and read as a scene that has it"),
    ('blockshow) names="chest bell banner shulker_box enchanting_table"', "the block-entity fixture's names are "
     "not counted, so an arm whose scene has none of them reads as the scene the other arms have"),
    ('signshow) names="sign"', "the sign fixture's placement is not counted, so a window with no sign in it - "
     "and therefore no depth-biased pipeline - reads as the scene the other arms have"),
    ('grep -c "showcase: placed the $entity" "$run_dir/latest.log"',
     "an arm that staged the entity fixture is not counted for what it placed, so a scene with no entities - or "
     "with a number of them that grows with the window - reads as the scene the other arms have. Measured, one "
     "arm of run/vanilla-mobs placed nothing and the fixture's first version placed the pig and the cow every "
     "four to five seconds"),
    (': > "$out_dir/entity-counts.txt"', "the placement record is not emptied between sessions, so counts from "
     "an earlier session would be compared with this one's"),
    ('>> "$out_dir/entity-counts.txt"', "an arm's placements are not written to the record, so the arms cannot be "
     "compared with each other"),
    ('if [[ "$placed" == 0 ]]; then', "an arm that placed none of an entity is not refused, so a scene with no "
     "entities in it reads as one that has them"),
    ("if ! python3 - \"$out_dir/entity-counts.txt\"", "the arms' entity placements are never compared, and what "
     "a comparison needs is that the arms are one scene: measured, each type is placed twice in every arm, a "
     "number the fixture does not control, so the check is equality between the arms and not a constant"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-showcase" "$saves_dir/$world_name/datapacks/showcase"',
     "the particle fixture is not copied from the repository, so the scene would live in an unversioned save"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-mobs" "$saves_dir/$world_name/datapacks/mobshow"',
     "the entity fixture is not copied from the repository, so the scene it describes would live in an "
     "unversioned save"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-blocks" "$saves_dir/$world_name/datapacks/blockshow"',
     "the block-entity fixture is not copied from the repository, so the scene it describes would live in an "
     "unversioned save"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-sign" "$saves_dir/$world_name/datapacks/signshow"',
     "the sign fixture - the only scene that makes a live frame ask for a depth bias - is not copied from the "
     "repository"),
    ('grep -q "Found new data pack file/$fixture" "$run_dir/latest.log"',
     "an arm that staged a fixture is not checked against the game having found it, so a scene without it reads "
     "as a scene with it"),
    ('grep -q "Failed to load function" "$run_dir/latest.log"',
     "an arm is not refused when the game refuses a fixture's function, which is how a fixture that stages and "
     "emits nothing passes for one that works"),
):
    if needle not in launcher:
        raise SystemExit("vitrail performance harness: " + why)
fixture = ROOT / "tools" / "fixtures" / "vanilla-showcase"
for path, why in (
    (fixture / "pack.mcmeta", "the particle fixture has no pack metadata, so the game will not load it"),
    (fixture / "data" / "minecraft" / "tags" / "function" / "tick.json",
     "the fixture has no tick tag, so its function never runs"),
    (fixture / "data" / "showcase" / "function" / "tick.mcfunction",
     "the fixture has no tick function, so the switch stages an empty datapack"),
):
    if not path.is_file():
        raise SystemExit("vitrail performance harness: " + why)
sign = ROOT / "tools" / "fixtures" / "vanilla-sign"
sign_tick = (sign / "data" / "signshow" / "function" / "tick.mcfunction")
for path, why in (
    (sign / "pack.mcmeta", "the sign fixture has no pack metadata, so the game will not load it"),
    (sign / "data" / "minecraft" / "tags" / "function" / "tick.json",
     "the sign fixture has no tick tag, so its function never runs"),
    (sign_tick, "the sign fixture has no tick function, so the switch stages an empty datapack"),
):
    if not path.is_file():
        raise SystemExit("vitrail performance harness: " + why)
# The fixture *is* the trigger: the depth-bias call is only reached by a sign whose text the game draws, so a
# fixture that placed a blank sign would leave every window reading `depthBias=0` again and nothing would fail.
sign_tick = sign_tick.read_text()
for needle, why in (
    ("minecraft:oak_sign", "the sign fixture no longer places a sign, so no live frame reaches the depth-biased "
                           "text pipeline it exists for"),
    ("front_text", "the sign fixture places a sign with no front text, so the pipeline's glyphs are never drawn"),
    ("messages", "the sign fixture's sign carries no text component, so there is nothing to draw"),
):
    if needle not in sign_tick:
        raise SystemExit("vitrail performance harness: " + why)
mobs = ROOT / "tools" / "fixtures" / "vanilla-mobs"
mob_tick = (mobs / "data" / "mobshow" / "function" / "tick.mcfunction")
for path, why in (
    (mobs / "pack.mcmeta", "the entity fixture has no pack metadata, so the game will not load it"),
    (mobs / "data" / "minecraft" / "tags" / "function" / "tick.json",
     "the entity fixture has no tick tag, so its function never runs"),
    (mob_tick, "the entity fixture has no tick function, so the switch stages an empty datapack"),
):
    if not path.is_file():
        raise SystemExit("vitrail performance harness: " + why)
mob_tick = mob_tick.read_text()
if "NoAI:1b" not in mob_tick:
    raise SystemExit("vitrail performance harness: the entity fixture summons entities that move, so two "
                     "launches draw two poses and a picture comparison reads the animation")
# The proof has to come *before* the summon it proves: both are guarded by `unless entity`, and the summon is
# what makes that guard false, so a `say` behind it can never fire. Measured, the first version of this proof
# printed nothing in any arm while the entities were placed.
for tag in ("NoAI:1b", "NoGravity:1b", "Invulnerable:1b", "PersistenceRequired:1b"):
    if mob_tick.count(tag) < 2:
        raise SystemExit(f"vitrail performance harness: the entity fixture does not put {tag} on both its mobs, "
                         f"and each of those tags is one of the ways a placement stops being one - Invulnerable "
                         f"is the one whose absence was measured as a mob re-placed every four to five seconds")
for kind in ("pig", "cow", "armor_stand", "item", "experience_orb"):
    said = mob_tick.find(f"run say showcase: placed the {kind}")
    placed = mob_tick.find(f"run summon minecraft:{kind}")
    if said < 0 or placed < 0:
        raise SystemExit(f"vitrail performance harness: the entity fixture does not both say and summon the "
                         f"{kind}, so its proof of placement is not a proof")
    if said > placed:
        raise SystemExit(f"vitrail performance harness: the entity fixture says it placed the {kind} after the "
                         f"command that places it, and the guard makes that say unreachable")
if "run say showcase: placed the" not in mob_tick:
    raise SystemExit("vitrail performance harness: the entity fixture does not say when it places an entity, so "
                     "an arm whose summons never ran cannot be told from one whose did - which is the reading "
                     "that cost run/vanilla-mobs an arm")
if "unless entity" not in mob_tick:
    raise SystemExit("vitrail performance harness: the entity fixture has no once-only guard, so it summons an "
                     "entity every tick and the scene grows with the window")
if "particle minecraft:flame" not in (fixture / "data" / "showcase" / "function" / "tick.mcfunction").read_text():
    raise SystemExit("vitrail performance harness: the tick function emits no particle, so the fixture stages "
                     "nothing into the frame")
tick = (fixture / "data" / "showcase" / "function" / "tick.mcfunction").read_text()
if " 0 0 0 0 1" not in tick:
    raise SystemExit("vitrail performance harness: the fixture emits its particles with a spread or a speed, so "
                     "the field moves between two launches and a picture comparison of the scene reads the "
                     "animation rather than the renderer - measured, two arms of the reference differed in 68% of "
                     "pixels with a moving field")
if "^0 ^3" not in tick:
    raise SystemExit("vitrail performance harness: the fixture's particles are not placed in front of the "
                     "camera, so the grid lands wherever the world's spawn is and not in the frame")
blocks = ROOT / "tools" / "fixtures" / "vanilla-blocks"
block_tick = blocks / "data" / "blockshow" / "function" / "tick.mcfunction"
for path, why in (
    (blocks / "pack.mcmeta", "the block-entity fixture has no pack metadata, so the game will not load it"),
    (blocks / "data" / "minecraft" / "tags" / "function" / "tick.json",
     "the block-entity fixture has no tick tag, so its function never runs"),
    (block_tick, "the block-entity fixture has no tick function, so the switch stages an empty datapack"),
):
    if not path.is_file():
        raise SystemExit("vitrail performance harness: " + why)
block_tick = block_tick.read_text()
# The names here are the harness's own counted names, and that is the point: a name the harness counts and a
# name the fixture does not say is a check that can never fire.
for kind in ("chest", "bell", "banner", "shulker_box", "enchanting_table"):
    if f"run say showcase: placed the {kind}" not in block_tick:
        raise SystemExit(f"vitrail performance harness: the block-entity fixture does not say it placed the "
                         f"{kind}, so an arm whose placement never ran cannot be told from one whose did")
    block = "minecraft:" + ("white_banner" if kind == "banner" else kind)
    # What the command *places*, which is the text after `run setblock` - the block named before it is the
    # guard's condition, so a check that looked at the whole line would pass on a command that places air.
    placed_tails = [line.split("run setblock", 1)[1] for line in block_tick.splitlines() if "run setblock" in line]
    if not any(block in tail for tail in placed_tails):
        raise SystemExit(f"vitrail performance harness: the block-entity fixture says it placed the {kind} and "
                         f"places none - the guard would read the block as missing for the whole session")
if "say showcase: the block fixture ran" not in block_tick:
    raise SystemExit("vitrail performance harness: the block-entity fixture has no liveness line, so a session in "
                     "which its function never ran cannot be told from one in which every placement was skipped - "
                     "which is the reading that cost this fixture its first run: the function ran 1138 times and "
                     "not one placement fired, because a block predicate does not resolve `^`")
if "execute at @e[type=minecraft:marker" not in block_tick:
    raise SystemExit("vitrail performance harness: the block-entity fixture does not place its blocks at a "
                     "marker, which is the form its own diagnostic left standing: a block predicate reads a "
                     "position only once a command has made it real, so the guard has to be an entity")
if block_tick.count("unless entity @e[type=minecraft:marker") < 5:
    raise SystemExit("vitrail performance harness: the block-entity fixture's placements are not guarded on a "
                     "marker already being there, so it summons one every tick")
if "execute at @a" not in tick:
    raise SystemExit("vitrail performance harness: the particles are not emitted at the camera, so they would "
                     "land wherever the world's spawn is and not in the frame")

# ---------------------------------------------------------------------------
# An arm the machine spoiled is named, and the session is refused
#
# Measured, run/vanilla-grid: one Metal 4 arm read 10.68 ms a frame against the other's 2.46 - 4.35x - while
# every structural counter agreed to a tenth of a per cent, and nothing refused it, because a session with two
# generations in it skips the per-generation structural check by design. Section 115's answer to an arm like
# that is "discard the arm", and a reader can only discard what is named. The same file has to keep the two
# properties that make the check right rather than noisy: it judges an arm against its *own* generation (the
# generations legitimately differ) and its threshold is loose enough for this path's real 15% arm-to-arm
# spread and tight enough to catch 4.35x.
# ---------------------------------------------------------------------------
for needle, why in (
    ("TIMING_OUTLIER = 1.5", "the comparer has no threshold for an arm the machine spoiled, so a 4.35x outlier "
     "reads as a result and is averaged into the generation's answer"),
    ("outliers: list[str] = []", "the timing outlier check is gone from the comparison"),
    ("outliers.append(", "the outlier check finds an arm and records nothing, so the line and the refusal that "
     "depend on it can never fire"),
    ("for name, rate in per_frame.items():", "the check no longer compares each arm with the fastest of its own "
     "generation, which is the whole of what it does"),
    ("per_frame[name] = millis / frames", "the outlier check does not read the arms' own frame rates"),
    ('print("arm outlier: " + "; ".join(outliers)', "the outlier is not said on a line of its own, so a reader "
     "sees it folded into a sentence about scene drift - which is a different fault with a different remedy"),
    ("if drift or outliers:", "an arm the machine spoiled no longer refuses the session, so its numbers are "
     "printed as if they were comparable"),
):
    if needle not in compare:
        raise SystemExit("vitrail performance harness: " + why)
if "TIMING_OUTLIER * fastest" not in compare:
    raise SystemExit("vitrail performance harness: the outlier threshold is not applied to the fastest arm of the "
                     "arm's own generation, so two generations that legitimately differ would be refused")

if "-Dmetallum.frameProbeBudget=$frames" not in launcher:
    raise SystemExit("--frames never reaches the probe, so the window length is not the harness's")

# ---------------------------------------------------------------------------
# A spread *inside* an arm has evidence, not only a spread between arms
#
# `load.txt` is the kernel's one-minute average at two instants, and a burst shorter than that average
# barely moves it: session run/m4-loadtrace's four arms came out 18.22, 18.52, 21.10 and 21.57 ms a
# frame while the fastest of them ran at the highest load and one arm's own cost moved from 8.50 to
# 16.43 ms a frame in six buckets with its commands flat, so the endpoints were the one thing that
# could not say what the machine did in between. The trace is what a later reader correlates against,
# and it is worthless without knowing which of its samples fall inside the counted window.
# ---------------------------------------------------------------------------
if '\t) > "$run_dir/load-trace.txt" 2>/dev/null &' in launcher:
    raise SystemExit("the load tracer redirects its own file, and it shares that file with the arm's window "
                     "markers: its descriptor carries its own offset, so its next sample lands on the marker "
                     "the arm appended and overwrites it - measured, `window-opened` was in none of run/m4-rings' "
                     "four traces")
if '\t: > "$run_dir/load-trace.txt"' not in launcher or \
        '\t) >> "$run_dir/load-trace.txt" 2>/dev/null &' not in launcher:
    raise SystemExit("the load trace is not written by appending writers over a file emptied once, so either "
                     "the trace is never truncated between arms or the writers can overwrite each other")
if 'printf \'window-opened %s\\n\' "$marker_touched" >> "$run_dir/load-trace.txt"' not in launcher:
    raise SystemExit("the load trace does not say when the window opened, so no sample of it can be "
                     "attributed to the frames the probe counted, and the settle cannot be checked against "
                     "the moment the pack's first full frame was detected")
if 'printf \'window-closed %s\\n\' "$(date +%s)" >> "$run_dir/load-trace.txt"' not in launcher:
    raise SystemExit("the load trace does not say when the window closed, so its samples cannot be "
                     "bounded at the far end either")
if 'kill "$load_tracer" 2>/dev/null || true' not in launcher:
    raise SystemExit("the load tracer is never stopped, so a harness that dies mid-arm leaves a loop "
                     "sampling the machine behind it")
# Twice, because an arm can end two ways: its window closes, or it never reaches one. A harness that
# stops the tracer on only the good path leaks it on exactly the arms that are already going wrong.
if launcher.count('kill "$load_tracer" 2>/dev/null || true') < 2:
    raise SystemExit("the load tracer is stopped on one of the two ways an arm can end, so an arm that "
                     "never reached a window leaves it sampling")
if 'seq 1 240' not in launcher:
    raise SystemExit("the load tracer has no sample bound, so a harness that dies before it can stop the "
                     "tracer leaves it running for the rest of the machine's uptime")
if "{latest.log,probe.txt,screen.png,gradle.log,load.txt,load-trace.txt," not in launcher:
    raise SystemExit("the harness does not say in its usage that an arm leaves a load trace, so a reader "
                     "of a session's directory does not know the evidence is there")
if "source-revision.txt}," not in launcher:
    raise SystemExit("the harness does not say in its usage which code an arm ran, so a session taken with a "
                     "repository's sources put back to an earlier commit cannot be told from one that was not")

# ---------------------------------------------------------------------------
# And what the GPU itself was doing, because that is what a frame-time claim is about
#
# `run/m4-ab7` is the session that made this necessary: its four arms read device utilization 100%, which is
# what turns "M4 is 17-35% slower" from a wall-clock difference into GPU work - and the same trace showed the
# accelerator 85-87% busy between arms with no game running, because a browser and a remote-desktop server
# are on this machine. A session that keeps only the CPU's load cannot say either thing.
# ---------------------------------------------------------------------------
if 'bash "$repo_root/tools/gpu-trace.sh" "$out_dir/gpu-trace.txt"' not in launcher:
    raise SystemExit("the harness does not sample the accelerator for the session, so a frame-time spread "
                     "cannot be told from a GPU that was busy with something else")
if 'kill "$gpu_tracer" 2>/dev/null || true' not in launcher:
    raise SystemExit("the GPU tracer is never stopped, so a harness that dies leaves a loop reading the "
                     "driver's statistics behind it")
gpu_tracer = (ROOT / "tools" / "gpu-trace.sh").read_text(encoding="utf-8")
for needle, why in (
    ('"Device Utilization %"', "the trace does not read the accelerator's own utilization, which is the "
                               "reading that says whether a frame was GPU-bound at all"),
    ("grep -o 'fLastSubmissionPID\"=[0-9-]*'",
     "does not read which process submitted to the GPU last, so a second client on the machine is invisible "
     "to it - the comment above it is not the reading"),
    ("set -uo pipefail", "the trace is not written to survive a missing ioreg field, and a trace that exits "
                         "on the first absent key reports a machine that never had a GPU"),
    ("seq 1 \"$count\"", "the trace has no sample bound, so it can outlive the session that started it"),
):
    if needle not in gpu_tracer:
        raise SystemExit("the GPU trace " + why)

# ---------------------------------------------------------------------------
# The numbers are the probe's own
#
# The comparison parses the line the probe printed rather than restating its counters, and refuses a
# picture it cannot read rather than guessing at one: a comparison against a number this side decided
# would agree with itself.
# ---------------------------------------------------------------------------
for counter in ("loadedMiB", "storedMiB", "depthAttachments", "depthLoadedMiB", "depthStoredMiB",
                "encoders", "passChanged", "windowMs"):
    if f'"{counter}"' not in compare:
        raise SystemExit(f"the comparison does not read the probe's {counter}")
if "ms a frame" not in compare:
    raise SystemExit(
        "the comparison does not turn the window's time into a frame rate, which is the reading any change is judged by"
    )
if "not a PNG" not in compare:
    raise SystemExit("the comparison no longer refuses a file that is not a picture")
if "unsupported PNG" not in compare:
    raise SystemExit("the comparison guesses at a picture it cannot read")
if "order.txt" not in compare or "order.txt" not in launcher:
    raise SystemExit("the comparison does not use the order the runs were asked for, so the baseline could be any of them")
# A capped run reads exactly like a slow engine, and this cost four runs to find: the staged instance's
# own maxFps and vsync were never part of what the harness set, so a window that had been 120 a second
# because the game limited it looked like the display doing it.
if 'fullscreen = "true" if os.environ.get("VITRAIL_PROFILE_FULLSCREEN") == "true" else "false"' not in launcher:
    raise SystemExit(
        "the harness no longer writes the window mode into the profile, so a fullscreen run and a "
        "windowed one cannot be told apart by what they set"
    )

for setting in ('"maxFps": "260"', '"enableVsync": "false"', '"fullscreen": fullscreen,',
                '"preferredGraphicsBackend": \'"default"\'', '"startedCleanly": "true"'):
    if setting not in launcher:
        raise SystemExit(
            "the harness does not write the measurement profile it compares under, so a run can be "
            f"capped by the instance it stages, or sent to another engine by the guard that reads "
            f"the clean-start flag (missing {setting})"
        )

# The world is copied in under its own name, so a world that already is the copy is deleted by the copy's
# own first step. Measured: `--world run/saves/PerfWorld` removed the staged world and left an empty run.
if "would delete it before copying it" not in launcher:
    raise SystemExit(
        "the harness copies the world into the instance without refusing a world that is already there, "
        "so the run deletes the scene it was asked to measure"
    )

# The picture a comparison reads is a screenshot, so the Metal HUD's changing numbers and graph are most
# of what would differ between two arms of a scene that was drawn twice. Off for a measured run.
# The same trap as the world, for the pack: `cp` refuses a file that is already the destination, and under
# `set -e` that ends the run before it launches. Measured on `--pack run/shaderpacks/photon_v1.3b.zip`.
if "The shader pack asked for is already inside the instance" not in launcher:
    raise SystemExit(
        "the harness copies the pack into the instance without refusing one that is already there, so a run "
        "with a pack staged in place ends at the copy"
    )

if "-PvitrailHud=0" not in launcher:
    raise SystemExit(
        "the harness leaves the Metal HUD in the frame it photographs, so a picture comparison reads the "
        "overlay's own numbers rather than the scene"
    )

# The picture is asked for before the window's marker is touched and not after it: the two orders are one line
# apart in the source and a session apart in what they measure.
_request = launcher.index(': > "$game_dir/metallum/screenshot-request"')
_marker = launcher.index('touch "$marker"')
if _request > _marker:
    raise SystemExit(
        "the client's picture is asked for after the window's marker is touched, so its readback lands inside the "
        "frames the probe counts"
    )

# The window opens on a settled scene, and how long that takes is a switch rather than a constant: the
# measurement that motivated it - two pinned runs of one configuration 4.4 per cent apart after five seconds
# - says five is not obviously enough.
if "--settle" not in launcher \
        or 'sleep $(( settle_seconds > 3 ? settle_seconds - 3 : settle_seconds ))' not in launcher \
        or "settle_seconds=25" not in launcher:
    raise SystemExit(
        "the harness no longer waits for the scene to settle before opening the probe window, or no longer "
        "lets that wait be raised"
    )
if 'python3 "$repo_root/tools/vitrail-performance-compare.py"' not in launcher:
    raise SystemExit("the harness collects runs and never compares them")

# A window is only a measurement if the run proves it was the run that was asked for. Three arms reported a
# menu frame - and one reported a scene at 100 ms a frame - as a measurement of Photon, because the harness
# judged the window by its counters afterwards. The checkpoint smokes in this repository were already doing it
# the other way round: named evidence first, the fixture's own name inside the asserted string, a failure line
# that is a failure, and a clean shutdown before a number is trusted. These four are that evidence here.
for needle, why in (
    ('grep -qF "No pack asked for" "$run_dir/latest.log"',
     "the harness does not refuse a window whose log says the pack selection was off, which is the engine "
     "telling it that the pack was not drawn at all"),
    ('grep -qF "of $pack_name at render stage" "$run_dir/latest.log"',
     "the harness does not require the pack's own name in the line that proves a pass drew, so a window that "
     "drew another pack - or none - can pass"),
    ('grep -qF "Stopping!" "$run_dir/latest.log"',
     "the harness does not require a clean client shutdown, so a window that ended for another reason is "
     "reported as a measurement"),
    ("performance window: PASS",
     "the harness does not say, per run, that the window is one it stands behind"),
):
    if needle not in launcher:
        raise SystemExit(why)

# And the refusals have to be refusals: a window that did not draw the pack, and a run that never armed, are
# two different faults with two different exits, and neither may end zero - the pass-timings attempt timed out
# at 900 s and this script still exited 0 with an empty comparison.
for needle, why in (
    ("scene_bad=1", "the harness detects a bad window and does not mark the run as one"),
    ("exit 4", "a window that did not draw the pack ends zero, so an empty comparison reads as a result"),
    ("run_failed=1", "an arm that never armed is not marked as one"),
    ("exit 5", "an arm that never armed ends zero, so a missing run reads as a result"),
):
    if needle not in launcher:
        raise SystemExit(why)

# The per-file "is this script named by ci.yml" guard that stood here is now one guard over
# every tools/ci-*.py in ci-repo.py: the same claim, made once and over all of them.

# And the comparison refuses an arm that is not the same scene, because a drifted scene reads exactly like a
# win: one arm drew the pack at 27 000 passes a frame with 511 217 loadedMiB against the baseline's 93 943,
# and every other check the harness had accepted it.
comparison = (ROOT / "tools/vitrail-performance-compare.py").read_text(encoding="utf-8")
for needle, why in (
    ("SCENE_TOLERANCE = 2.0",
     "the comparison has no tolerance for the counters that say two arms are the same scene"),
    ('for counter in (() if cross_generation else ("renderPasses", "depthAttachments")):',
     "the comparison does not judge the scene counters that a switch cannot move - and it must not judge "
     "loadedMiB or blits, which are what the attachment and copy switches exist to move. It is judged where two "
     "arms executed one generation, because two generations differ on those counters by design"),
    ("scene drift: ",
     "the comparison does not name the drift it found"),
    ("return 3", "a drifted arm does not end the comparison non-zero, so it reads as a result"),
    ("so the two arms did not render the same window",
     "the comparison does not judge the window the two arms were photographed at, which a fullscreen arm "
     "takes from the display and --width/--height cannot pin"),
    ("def flat_colour(",
     "the comparison does not ask whether a capture has a picture in it at all"),
    ("if first.name in flat or run.name in flat:",
     "a flat capture is compared anyway, and two of them print the strongest agreement this tool can report "
     "about two photographs of nothing"),
    ("NOT COMPARABLE - the capture is one flat",
     "a flat capture is not refused in as many words, so its verdict reads as a result"),
    ('if len(sys.argv) == 3 and sys.argv[1] == "--capture-check":',
     "the comparison cannot answer the harness's pre-flight question about one capture"),
    ("picture evidence is void: ",
     "the comparison does not end non-zero when no arm's screen was photographed"),
    ("        return 4\n", "flat picture evidence does not end the comparison non-zero, so a session of "
                         "photographs of nothing reads as a session that agreed"),
    # And the one A/B whose structural counters cannot be judged: two arms that executed different generations.
    # Both are pinned, because getting this wrong in either direction is a silent fault - refusing a pair that is
    # a generation apart, or letting a drifted scene through because its arms happened to name a generation.
    ("def generation(line: str) -> str:",
     "the comparison cannot read which generation executed an arm, so it cannot tell a cross-generation pair "
     "from a drifted one"),
    ('re.search(r"executingGeneration=(\\S+)", line)',
     "the generation is read from something other than the probe's own executingGeneration field"),
    ("cross_generation = len(named) > 1",
     "the comparison does not recognise a pair whose arms executed different generations"),
    ("the scene guard for this pair is the harness's own target, pack",
     "the stand-aside does not say where the scene guard moves to, so a reader would take it as the check "
     "having passed"),
):
    if needle not in comparison:
        raise SystemExit(why)

# And the target the world is really drawn at, which is the one thing the arms of a session can share
# while the whole session sits on a target the baseline never used. Measured: a JFR crash left the
# display on another fullscreen mode and every later run inherited it, so a session collected two arms
# of 1760x990 where the baseline is 1056x660 and every one of its numbers was about another frame -
# and the comparison above could not see it, because that pair agreed with each other.
harness = (ROOT / "tools/run-vitrail-performance.sh").read_text(encoding="utf-8")
for needle, why in (
    ("--fullscreen-size) fullscreen_size=\"$2\"; shift 2 ;;",
     "the harness cannot be told which framebuffer the fullscreen window must take, so the render "
     "target is whatever mode the display happens to be in"),
    ('"overrideWidth": override_width, "overrideHeight": override_height',
     "the fullscreen size is not written into the game's own override, which is the only thing that "
     "decides the framebuffer a fullscreen window takes"),
    ('os.environ.get("VITRAIL_PROFILE_FULLSCREEN_SIZE", "")',
     "the size the harness was told is never read, so the override is written from nothing"),
    ('if "x" in size:',
     "the size the harness was told is not parsed, so a flag with a typo in it silently asks for the "
     "display's own mode instead of failing"),
    ("--expect-target) expect_target=\"$2\"; shift 2 ;;",
     "the harness has no way to be told which render target a session must be measured on"),
    ('if [[ -n "$expect_target" ]]; then',
     "the target guard does not run when a target was asked for, so a window on another target passes"),
    ('elif [[ "$drawn_target" != "$expect_target" ]]; then',
     "the harness reads the size the world was drawn at and does not compare it with the one asked for"),
    ("The world renders at [0-9]*x[0-9]*",
     "the target is not read from the log's own line, which is the only place that says which size the "
     "world was really drawn at"),
    # And the two ways that reader can be blind, both measured on a real session:
    #
    #   - a Vitrail build states the target with the pack's own `Drawing <pack> ... at WxH, N full screen`
    #     line and not with the probe's, so a reader that knows one wording reports "never said what size it
    #     drew the world at" for a session that said it plainly;
    #   - and under `set -o pipefail` a `grep` that matches nothing fails its pipeline, so the *fallback* to
    #     the second wording never ran - the guard **killed the harness** between the first arm and the
    #     second, and the failure read as "the session stopped after one arm" with no line saying why. The
    #     `|| true` is what makes a missing line a reported condition rather than an aborted session.
    ("Drawing .* at [0-9]+x[0-9]+, [0-9]+ full screen",
     "the second wording of the target line is not read, so a session whose Vitrail states the target that "
     "way cannot be pinned at all"),
    ("tail -1 | sed 's/.*renders at //' || true)",
     "the first target lookup is not tolerant of finding nothing, so under pipefail a build that does not "
     "print that line kills the harness instead of falling through to the second wording"),
    ("head -1 || true)", "the second target lookup is not tolerant either"),
    # And the machine, which is the one input to an arm's wall time that is not this program's. Measured:
    # session run/perf-ab4's two Metal 3 arms agreed to 0.6 per cent while its two Metal 4 arms differed by
    # 47.7, with the same 8 ms difference on both sides of the encoder - a spread in the frame that no log
    # line could attribute, because the harness recorded nothing about what else the machine was doing.
    ("cpus %s\\n", "the machine's CPU count is not recorded, so a load average cannot be read as a fraction "
                   "of the machine"),
    ("printf 'start %s\\n' \"$(load_average)\"",
     "the load average at the arm's start is not recorded, which is half of what makes a spread between two "
     "arms readable"),
    ("printf 'end %s\\n' \"$(load_average)\" >> \"$run_dir/load.txt\"",
     "the load average when the window closed is not recorded, so an arm whose machine got busy while it "
     "drew cannot be told from one whose frame was slower"),
    ("sysctl -n vm.loadavg", "the load average is not read from the kernel, so it is read from a shell "
                             "command's wording and not from a number"),
    ("load.txt", "nothing in the harness names the file the machine state is written to"),
    # And the CODE the arm ran, which is the other input to a reading that is not the frame's. `--metallum` and
    # `--vitrail` are arguments a person types into the report tool, so a session that put a repository's sources
    # back to an earlier commit - which is how the acceptance's own baseline was re-measured in the machine state
    # the head was read in - carried the head's SHA and read as a session of the wrong code. Measured: the no-pack
    # scene read 1.793 ms a frame against a baseline of 1.678 taken four and a half hours earlier, and with the
    # baseline's own sources back in the worktree it read 1.795 - so which code an arm ran is the whole difference
    # between a finding and the environment, and it is recorded by the arm rather than asserted about it.
    ("source_revision() {",
     "nothing records the revision an arm ran, so a session cannot be audited once the worktree is put back"),
    ('> "$run_dir/source-revision.txt"',
     "the revision an arm ran is not written into the arm's own directory, where a later reader can find it"),
    ('git -C "$root" status --porcelain',
     "the recorded revision does not say whether the worktree WAS that revision, which is the only part that "
     "catches sources put back to an earlier commit"),
    ("repo_revision() {", "the revision line per repository is not written by a function that reads git"),
    ('repo_revision "$repo_root" metallum',
     "this repository's checkout is not named in the arm's own record"),
    ('repo_revision "$vitrail_root" vitrail',
     "Vitrail's checkout is not named in the arm's own record, so which jar an arm ran cannot be read"),
    # Both groups, because they fail differently: sources put back to an earlier commit make a reading about
    # another build, and a changed harness makes it a reading of another instrument - and this programme has a
    # harness change on its own record, the readback that landed inside the window it was measuring.
    ('"$repo_root" metallum tools tools',
     "the state of the measuring tools is not recorded for this repository, so a session run with a changed "
     "harness is indistinguishable from one run without"),
    ('"$vitrail_root" vitrail source',
     "the Vitrail sources the built artifact is made of are not recorded, so a jar built from another revision "
     "reads as this checkout"),
    ('"$vitrail_root" vitrail tools tests',
     "the state of Vitrail's own contract tests is not recorded"),
    # And the derived shader caches, which a session must be able to start without. Measured while reading
    # the load census: every arm of every session so far read `Module cache: 574 units served, 0 built`,
    # because the caches live beside the pack and are keyed on the build - so the corpus has four warm
    # readings of each pack and no cold one at all, and "what does a first load cost" was unanswerable.
    ("--cold-cache) cold_cache=true; shift ;;",
     "the harness cannot be asked for a cold load, so every session it runs measures the warm path"),
    ('dir="$game_dir/vitrail/$cache"',
     "the cache the cold arm removes is not named per cache root, so a build with a second derived cache "
     "would leave it warm"),
    ("du -sh \"$dir\"", "the size of the cache being removed is not read, so a reader cannot say what a cold "
                        "load had to rebuild"),
    ("the first arm of this session is a cold load",
     "the removal does not say which arm it made cold, which is the one fact a reader of the session needs"),
    ("rm -rf \"$dir\"", "nothing is actually removed when a cold load is asked for, so the flag would be a "
                        "no-op that reads as a measurement"),
    # And the three session-validity refusals of section 46 that nothing made, each one a window that would
    # otherwise be read as a measurement: a short window, a window opened before the settle ran, and a client
    # that died during the arm.
    ('counted="$(grep -o \'windowFrames=[0-9]*\' "$run_dir/probe.txt"',
     "nothing refuses a window that counted fewer frames than the caller asked for, and a short window is a "
     "shorter sample of one scene - which the comparison cannot see, both arms of a pair being short"),
    ('elif [[ "$counted" -lt "$frames" ]]; then',
     "the frame count the window reported is read and not compared with the one asked for"),
    ('frame_seen="$(date +%s)"',
     "the moment the pack's first full frame was detected is not kept, so the settle this harness sleeps for "
     "cannot be checked"),
    ('settled_for=$(( marker_touched - frame_seen ))',
     "the settle is not measured, so an arm whose window opened early is not refused"),
    ('if [[ "$settled_for" -lt "$settle_seconds" ]]; then',
     "the settle the window really had is read and not compared with the one asked for"),
    # The picture column: asked for from inside the client while the window is open, waited for with a bound,
    # and the display capture kept as the fallback - because a request answered once, a request that is never
    # answered, and a photograph of whatever is in front are three different pieces of evidence.
    ("-Dmetallum.clientScreenshot=true",
     "the client's own readback is never asked for, so the picture column is a photograph of the display and "
     "nothing else"),
    (': > "$game_dir/metallum/screenshot-request"',
     "the request file is not created, so the client is never asked"),
    # And it is asked for inside the SETTLE and never inside the window. Measured, the first version asked at the
    # window's own opening and put a 273 ms frame at frame 29 of a 300-frame window whose every other arm reads a
    # worst frame of about ten milliseconds - a diagnostic moving the state it reports, which is the one thing a
    # diagnostic may not do.
    ('sleep $(( settle_seconds > 3 ? settle_seconds - 3 : settle_seconds ))',
     "the readback request is not held back inside the settle, so the readback's stall can land inside the window "
     "the probe is counting - measured at 273 ms against every other arm's ten"),
    ('if [[ "$settle_seconds" -gt 3 ]]; then',
     "the settle is not finished after the request, so the window opens before the settle the harness promised"),
    ("the first version of",
     "no pin carries the reason the request sits in the settle, so the next reader can move it back"),
    ('client_picture="$game_dir/metallum/client-screenshot.png"',
     "the client's answer is not named, so nothing waits for it"),
    ('for _ in $(seq 1 30); do',
     "the wait for the client's answer is unbounded or absent: a session that never answers it must still leave "
     "the display capture"),
    ('if [[ -s "$client_picture" ]]; then',
     "the answer's presence is not checked, so an empty file would be kept as the picture"),
    ('picture_source="client readback"',
     "nothing records which road the picture came by, so a reader cannot tell the frame from a photograph"),
    ('printf \'%s\\n\' "$picture_source" > "$run_dir/picture-source.txt"',
     "the road the picture came by is decided and not written down"),
    ('rm -f "$game_dir/metallum/screenshot-request"',
     "the request is not cleared at the end of an arm, so the next arm's client answers the last one's question"),
    ("a window opened before the settle it was told to run",
     "the refusal a reader sees does not name the window that opened early, so a session refused for it reads "
     "as a pack that did not draw"),
    ('for marker in "Minecraft has crashed!"',
     "a client that crashed during an arm is not refused, and its window may have been counted before the "
     "crash - which is the one reading worse than no reading, because it looks like a result"),
    ('"A fatal error has been detected by the Java Runtime Environment"',
     "a native fault is not one of the markers a crash is refused on, so a client killed by one passes"),
    ('"GpuDeviceLossException"',
     "the engine's own device-loss exception is not one of the markers, so an arm that lost the device passes"),
    ("scene_bad=1\n\t\t\tbreak", "the crash scan does not stop at the first marker that fires, so the log "
                                    "line stops naming which road the fault came by"),
    # And the command generation that executed the frame, which is machine state this harness does not write.
    # Measured, and the reason the guard exists: a whole session of the shadow decomposition (run/c2-<pack>)
    # was collected on Metal 4 while the corpus it was to be read against is Metal 3 - the instance's own
    # `vitrail/metal-execution.txt` said metal4, no arm passed `-Dmetallum.execution=metal3`, and every
    # structural counter came out within a per cent of the baseline's, so nothing in the comparison could see
    # it. Only the probe's own `executingGeneration` field said so, and nothing read it.
    ("--expect-execution) expect_execution=\"$2\"; shift 2 ;;",
     "the harness has no way to be told which command generation a session must be measured on"),
    ('if [[ -n "$expect_execution" ]]; then',
     "the generation guard does not run when a generation was asked for, so an arm that executed another one "
     "passes as a measurement of this one"),
    ("grep -o 'executingGeneration=metal[0-9]*' \"$run_dir/probe.txt\"",
     "the generation is read from something other than the probe's own executingGeneration field"),
    ('elif [[ "$executed" != "$expect_execution" ]]; then',
     "the generation the arm executed is read and not compared with the one asked for"),
    ("Vitrail Metal preference:.*",
     "the guard does not quote the session's own preference line, which is the only place that says who asked "
     "for the generation that ran, and would name the cause of a refused arm"),
    # It has to run for every arm and not only for a pack's: the no-pack baseline is the one every pack is
    # read against, and a guard that skipped it would leave the arm the corpus is anchored on unchecked.
    ("\n\tif [[ -n \"$expect_execution\" ]]; then",
     "the generation guard sits inside the pack-shape block, which a --no-pack session never enters"),
):
    if needle not in harness:
        raise SystemExit(why)

# And the comparison refuses a pair whose arms did not draw the same frame, judged within each generation.
#
# This is the check the cross-generation A/B needed and did not have: the drift check stood aside whenever two
# generations were named, because the structural counters move with the generation by design - and that left the
# counters a *switch* cannot move but a *scene* can (how many draws the frame made, how many textures and buffers
# it bound) unjudged. Measured, session run/perf-ab6: the two Metal 3 arms drew to +0.3% and bound to +0.2% while
# the two Metal 4 arms differed by +12.2% of draws, +14.7% of texture bindings and +15.1% of buffer bindings on
# the same world, pack, target and window - and the summary printed "+31.8% against the first arm" for that pair.
comparer = (ROOT / "tools/vitrail-performance-compare.py").read_text(encoding="utf-8")
for needle, why in (
    ("CONTENT_TOLERANCE = 5.0",
     "the comparison has no content tolerance, so the arms of one generation may draw different amounts of the "
     "same scene and still be read as a performance verdict"),
    ('EXACT_COUNTERS = ("windowFrames", "blits", "blittedMiB", "pipelineIdentities")',
     "the counters a frozen scene pins exactly - the frame count, the copy-backs and the program set - are not "
     "pinned exactly"),
    ("by_generation.setdefault(value, []).append(run.name)",
     "the drift check does not group the arms by the generation that executed, so it cannot judge a generation "
     "against itself"),
    ("the arms of one generation did not draw the same frame",
     "nothing says out loud that a generation whose own arms disagree cannot be read against the other one"),
    ("f\"{value}: {counter} of {name} is {change:+.1f}% against {reference_name}\"",
     "the refusal does not name which generation drifted, by which counter and by how much"),
    ('content_counters = ("loadedMiB", "storedMiB", "depthAttachments")',
     "the content check is not made on the three counters that mean the same thing on both generations and grow "
     "with what the frame drew - a guard that includes the native call counts refuses a pair of arms that drew "
     "the same frame, measured: +12.2% of pipeline sets against +0.7% of draws"),
    ("Metal 3 counts a pipeline *change*, this path counts a pipeline *set per draw*",
     "nothing says why the native call counters are not content, so the next reader will put them back"),
):
    if needle not in comparer:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- a fixture pack in the tree is a directory, and the harness stages it --------------------------------
# The MetalFX quadrant fixture is four lines of GLSL and belongs in the tree where a reader can check it against
# the picture it produced; a harness that demanded an archive would have it built by hand outside version
# control, and a fixture nobody can read is a fixture nobody can dispute. So `--pack <directory>` is staged
# into a zip here, and refused without a `shaders/` in it - which is the same refusal the game would make
# twenty calls later, said where it can be acted on.
for needle, why in (
    ('if [[ "$no_pack" == false && -d "$pack_path" ]]; then',
     "the harness refuses a pack directory, so a fixture kept in the tree cannot be measured"),
    ('if [[ ! -d "$pack_path/shaders" ]]; then',
     "a directory without shaders/ in it is staged anyway, so a typo becomes an empty pack rather than a "
     "refusal that says what is missing"),
    ('pack_zip="$repo_root/run/packsrc/$(basename "$pack_path").zip"',
     "the staged zip no longer lives under run/packsrc, so it could be written into the instance's shaderpacks "
     "and the harness would refuse the pack it just made"),
    ('(cd "$pack_path" && zip -qr "$pack_zip" .)',
     "the directory is not staged from its own root, so a pack whose shaders sit beside a README would arrive "
     "with an extra directory level and never load"),
):
    if needle not in harness:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- a session nobody touches, and the two ways that ruins one ------------------------------------------
# A session is eight to twelve minutes of an idle machine, which is the condition a screen locks and sleeps
# under, and a client whose window the display server has occluded is throttled. Measured, one arm of the sky
# session read `wallP50=100.00` with `windowTicks=598` over 300 frames - ten frames a second at exactly two
# client ticks a frame, every counter self-consistent, 14 render passes a frame and 100 pipeline identities -
# while its capture was the browser in front of the game and the client's own log said `Saving and pausing
# game...` eight seconds before the window opened. Nothing in the numbers said so and the flat-capture guard
# could not: a capture of a desktop is not one flat colour. So the session declares the user active for its own
# length, records what was in front of the display per arm, and refuses an arm whose window closed after the
# client paused rather than annotating it - a window that drew the pause screen is not the scene it claims.
for needle, why in (
    ("caffeinate -d -i -m -s -u -w $$ &",
     "the harness no longer declares the user active for the session, so an idle screen can lock mid-session and "
     "an occluded client is throttled to a cadence nobody can tell from a slow engine"),
    ("trap cleanup EXIT",
     "the activity declaration outlives the harness, so a session that ends leaves the machine unable to sleep"),
    ('"${front_app:-unknown}" > "$run_dir/front-app.txt"',
     "the arm no longer records what was in front of the display, so a capture of another application cannot be "
     "told from a capture of the game after the fact"),
    ("front '${front_app:-unknown}'",
     "the PASS line does not name what was in front, so a passing arm's picture column has no witness"),
    ('pause_line="$(grep -n "Saving and pausing game" "$run_dir/latest.log"',
     "the client's own pause line is no longer read, so an arm that measured the pause screen passes as a window"),
    ('"$pause_line" -lt "$report_line"',
     "a pause anywhere in the log is no longer placed against the window it closed after, so either every arm "
     "with a late pause is refused or none is"),
    ("a paused client is not the scene",
     "the refusal does not say what the pause means for the numbers it counted"),
):
    if needle not in harness:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- and it must not leave the owner's display or instance somewhere else ---------------------------------
# The game's fullscreen window asks the window server for a video mode and the window server changes the
# display's mode to match. Measured on this machine: with the desktop on `1800x1169@120` (3600x2338 pixels) a
# fullscreen launch left the display on `1920x1200@120` for as long as the client lived, at every requested
# window size (`--fullscreen-size 1600x900` through `1920x1200`), while a windowed launch left it alone; and a
# client killed before it exited cleanly left it moved. The harness therefore saves the mode before the session,
# checks it after every arm, puts it back when it moved, says so, and puts the instance's own `options.txt` back
# too - because a session that leaves the instance asking for a fullscreen window makes the owner's *next manual
# launch* move their display, which is the same fault one step earlier in the chain. `tools/display/display-mode.swift`
# is the reader and the setter, compiled by the harness on first use; the arm's own check is what makes this a
# guarantee rather than a note at the end.
for needle, why in (
    ('display_mode_bin="$repo_root/run/display-mode"',
     "the harness no longer builds the display-mode reader, so it cannot say or restore the mode it measured on"),
    ('"$display_mode_bin" save "$out_dir/display-mode-before.txt"',
     "the session no longer records the display mode it started on, so a mode the client moved cannot be put "
     "back or noticed"),
    ('"$display_mode_bin" check "$display_mode_saved"',
     "the display is no longer checked between arms, so an arm measured on a mode the client switched to is "
     "indistinguishable from one measured on the session's own mode"),
    ('echo "Run \'$name\' left the display on ${moved}; it is back on $("$display_mode_bin" read)" >&2',
     "a moved display is put back silently, so the session cannot be read afterwards for whether it moved"),
    ('display-mode-moves.txt',
     "the session does not leave a record of the modes its arms moved the display to"),
    ("restore_instance_options",
     "the instance's own options are not put back, so a session leaves the instance in the measurement profile "
     "and the owner's next manual launch is a fullscreen one"),
    ('cp -f "$game_dir/options.txt" "$game_dir/options-before-measurement.txt"',
     "the owner's options are not kept beside the instance, so a session killed before its trap runs leaves the "
     "instance in the measurement profile and the next session adopts that as the owner's setting"),
    ('if [[ -f "$game_dir/options-before-measurement.txt" ]]; then',
     "a killed session's profile is not recovered at the next start, which is the only thing that makes the "
     "marker worth writing"),
    ('rm -f "$game_dir/options-before-measurement.txt"',
     "the marker outlives a clean restore, so the next session would put back a stale file"),
    ('cp -f "$game_dir/options.txt" "$out_dir/options-before.txt"',
     "the instance's options are not kept before they are overwritten, so there is nothing to put back"),
    ('"exclusiveFullscreen": "true",',
     "the measurement profile no longer asks for exclusive fullscreen, so a fullscreen arm is put in its own "
     "Space and the photograph of the display is of whatever Space is current instead of the game - measured, "
     "the picture column then read 99.54 per cent of pixels differing between two arms of one generation"),
    ("note: --fullscreen asks the game for its own fullscreen mode",
     "asking for the game's fullscreen is no longer said to move the display's mode, so a session that must "
     "not touch the screen has nothing to read"),
    ("client_pids() {",
     "client detection is back to a bare pattern, which matches the shell that launched the harness - measured, "
     "it refused a legitimate session"),
    ('case "$(ps -o comm= -p "$pid" 2>/dev/null || true)" in',
     "the client check no longer asks what the process is, so any command line naming the world counts as a "
     "drawing client"),
):
    if needle not in harness:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- the window's tick sampling, which is what a content drift has to be read against --------------------
# A window is a fixed frame count and this client's frame is not the same work every frame (measured on the
# no-pack scene: four render passes in the steady state, six when the two particle passes have work, and six more
# than either on the frame that coincides with a 20 Hz client tick), so a content total is `steady*N + tick*T`
# plus whatever the particle kind is worth: two arms whose frame rates differ cover different numbers of both
# kinds and their totals differ with the same scene. The comparer therefore has to carry the tick fields and
# name them when a content drift fires, or a sampling difference is reported as a scene difference - which is
# what refused the no-pack rung.
for needle, why in (
    ('    "windowTicks",', "the comparer does not carry the window's tick count, so a content drift cannot be "
                          "told from a sampling difference"),
    ('    "framesPerTick",', "the comparer does not carry frames a tick, which is the number that says whether two "
                            "arms covered the same slice of the client's life"),
    ('f" (window ticks {reference_ticks:.0f} against {other_ticks:.0f}, frames"',
     "a content drift no longer names the two arms' tick sampling, so its line reads as a scene difference"),
):
    if needle not in comparer:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- and Phase F's upload census, which is the road and not the scene -------------------------------------
# The census answers whether this generation's staged-write shape is worth replacing, and the question is asked of
# every session rather than of one experiment: the comparer reads the probe's own line, so the counter appears in
# every comparison this harness prints. Pinned here because the census is worth little if it is only ever read by
# hand from a log - the reading that decides it has to appear beside the times it is supposed to explain.
for needle, why in (
    ('    "uploadCalls",', "the comparison does not carry the upload census, so the road CPU bytes take into a "
                           "frame is not read in the session that measures the frame"),
    ('    "uploadCpuMs",', "the comparison carries the upload call count but not what the calls cost, which is the "
                           "only half of the census a frame time can be divided by"),
    ('    "uploadsToTexture",', "the comparison drops the census's third road, so a texture upload would be counted "
                               "in the whole and invisible in the part"),
):
    if needle not in comparer:
        raise SystemExit("Vitrail performance harness contract: " + why)
PACING = ROOT / "tools/metal4-pacing-analysis.py"
if "pass-count decomposition:" not in PACING.read_text(encoding="utf-8"):
    raise SystemExit("Vitrail performance harness contract: the pacing analyser no longer names each arm's frame "
                     "kinds, so a content difference can no longer be attributed to the tick frames and the "
                     "reduced stretches instead of being left unexplained")

# --- the analyser reads the window the session reported, and says what its period is made of ---------------
# Two faults this pins shut, both found by reading the same session twice:
#
# 1. The window used to be whatever `--frames` said, and the default said 600. A 300-frame session read at 600
#    analysed the last 600 traced frames - the settle and the loading tail with the window - and nothing in the
#    output said so, because the report line was looked for by matching the *requested* frame count and a
#    mismatch did not stop it. Measured, the C1/C2 table in `docs/metal4-full-frame-report.md` carries `n` of
#    1839-2024 a row where its own text says the windows were 300 frames. The window is now read from the probe's
#    report line, `--frames` is an override that says when it disagrees, and the arm's header names both.
# 2. A frame's period is `begin(N) - begin(N-1)` and its `encodeUs` is `commit(N) - begin(N)`, so a period is
#    `between + the *previous* frame's encode` and not `+ its own`. The decomposition and its population table are
#    pinned because that pairing is what separates "the client's own work" from "this path's work" - an
#    off-by-one reads as a regression of this engine, which is the one mistake it exists to prevent.
pacing = PACING.read_text(encoding="utf-8")
for needle, why in (
    ('REPORT_RE = re.compile(r"frame-probe (\\d+)/(\\d+) windowFrames=(\\d+)")',
     "the analyser no longer reads the window the probe's own report line names, so a session is analysed over "
     "whatever stretch the caller assumed instead of the one it measured"),
    ("probeWindowFrames=",
     "the arm header does not say how long the probe said its window was, so a reading that is longer than the "
     "window cannot be told from one that is the window"),
    ("** the probe's window was",
     "an overridden window is no longer announced, so the longer stretch reads exactly like the window"),
    ("def between_frames(window):",
     "the period is no longer decomposed, so a slow population cannot be attributed to the client's own work "
     "outside the frame instead of to this path's encoder"),
    ("between(N) = wall(N) - encode(N-1) = begin(N) - commit(N-1)",
     "the decomposition no longer states the pairing it uses, which is the only thing that makes it readable"),
    ("period = between + previous encode:",
     "the identity is not printed, so a period that does not add up cannot be checked against its own parts"),
    ("population {label} (period {side} ",
     "there is no population selected by the period, so the second population has to be assumed rather than read"),
    ("corr(period, previous encode)=",
     "the correlations no longer include the previous frame's encode, which is the half of a period the encoder "
     "owns"),
):
    if needle not in pacing:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- and a frame kind is named, not only counted -----------------------------------------------------------
# The decomposition says a kind is two passes short of the modal one; it does not say *which* two, and a kind
# that is only a number is a kind nobody can act on. `-Dmetallum.metal4Trace=true` makes every pass write
# `end pass 'LABEL'` before the frame's own line, so the analyser can name each kind as the set it is. This
# runs it against a session written here - the same shape the no-pack scene has, `7*steady + 13*tick + 5*reduced`
# being a scene's numbers and not the path's - and refuses the harness if the names do not come back. A text
# grep for the field would pass on a reader that is never called; this one fails when the parse is removed.

ANIMATE = "Animate minecraft:textures/atlas/blocks.png"
BASE = ["Terrain", "Terrain", "Blit render target", "GUI before blur"]
PARTICLES = ["Particles - Solid", "Particles - Translucent"]
TICK = [ANIMATE] * 5 + ["Update light"]
LABELS = {4: BASE, 6: BASE + PARTICLES, 10: BASE + TICK, 12: BASE + PARTICLES + TICK}
with tempfile.TemporaryDirectory() as scratch:
    arm_dir = Path(scratch) / "m4a"
    arm_dir.mkdir()
    lines = []
    # The modal kind is the particle-carrying one, as it is in the measured window, so the reduced kind is
    # named by what it lacks rather than by what it has.
    for index, passes in enumerate((6, 6, 4, 12), start=1):
        for label in LABELS[passes]:
            lines.append(f"[00:00:00] [Render thread/INFO] (metallum) Metal 4 trace: end pass '{label}' "
                         f"depth=true draws=1 indexed=0 scissor=false colours=1 load=clear store=store")
        lines.append(f"[00:00:00] [Render thread/INFO] (metallum) M4_FRAME frame={index} slots=3 slot=0"
                     f" submission={index} wallUs=12500 slotWaitUs=0 drawableWaitUs=9900 encodeUs=12000"
                     f" passes={passes} encoders={passes} tables=9 draws=330")
        lines.append(f"[00:00:00] [Thread-3/INFO] (metallum) M4_FRAME_COMMIT submission={index} commitMs=2.71")
    lines.append("[00:00:00] [Render thread/INFO] (metallum) frame-probe 4/4 windowFrames=4 windowMs=50.00")
    (arm_dir / "latest.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    named = subprocess.run(["python3", str(PACING), scratch, "--frames", "4"],
                           check=True, capture_output=True, text=True).stdout
for needed, why in (
    ("pass kinds, named from the trace",
     "the analyser counts the frame kinds and does not name them, so a kind that is two passes short of the "
     "modal one stays an unexplained count"),
    ("lacks Particles - Solid, Particles - Translucent",
     "the reduced kind is no longer named as the frames whose two particle passes were never opened"),
    ("has Animate minecraft:textures/atlas/blocks.png x5, Update light",
     "the tick kind is no longer named as the five block-atlas animation passes and the lightmap pass the "
     "client does once a tick"),
):
    if needed not in named:
        raise SystemExit("Vitrail performance harness contract: " + why)

# --- and the window it reads is the session's own, not the caller's assumption ---------------------------
# The default used to be 600 frames whatever the session measured, and a 300-frame session analysed at 600 is the
# settle and the loading tail mixed into the window without anything in the output saying so - which is how the
# C1/C2 table in `docs/metal4-full-frame-report.md` came to carry `n` of 1839-2024 a row while its own text says
# the windows were 300 frames. Run here on a session written with eight traced frames and a four-frame window:
# without `--frames` the reading has to be the window, and with it the override has to announce itself.
with tempfile.TemporaryDirectory() as scratch:
    arm_dir = Path(scratch) / "m4a"
    arm_dir.mkdir()
    lines = []
    for index in range(1, 9):
        for label in LABELS[6]:
            lines.append(f"[00:00:00] [Render thread/INFO] (metallum) Metal 4 trace: end pass '{label}' "
                         f"depth=true draws=1 indexed=0 scissor=false colours=1 load=clear store=store")
        lines.append(f"[00:00:00] [Render thread/INFO] (metallum) M4_FRAME frame={index} slots=3 slot=0"
                     f" submission={index} wallUs=12500 slotWaitUs=0 drawableWaitUs=9900 encodeUs=12000"
                     f" passes=6 encoders=6 tables=9 draws=330")
        lines.append(f"[00:00:00] [Thread-3/INFO] (metallum) M4_FRAME_COMMIT submission={index} commitMs=2.71")
    lines.append("[00:00:00] [Render thread/INFO] (metallum) frame-probe 4/4 windowFrames=4 windowMs=50.00")
    (arm_dir / "latest.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    read_window = subprocess.run(["python3", str(PACING), scratch],
                                 check=True, capture_output=True, text=True).stdout
    read_stretch = subprocess.run(["python3", str(PACING), scratch, "--frames", "8"],
                                  check=True, capture_output=True, text=True).stdout
for needed, why in (
    ("frames=4 of 8 traced", "the analyser's default no longer reads the frame count the probe's own report line "
                             "names, so it analyses whatever stretch the caller assumed"),
    ("probeWindowFrames=4", "the arm's header does not say how long the probe said its window was, so a reading "
                            "that is longer than the window cannot be told from one that is the window"),
):
    if needed not in read_window:
        raise SystemExit("Vitrail performance harness contract: " + why)
if "** the probe's window was 4 frames" not in read_stretch:
    raise SystemExit("Vitrail performance harness contract: an overridden window is not announced, so a longer "
                     "stretch reads exactly like the window it was taken beside")

# --- whether the picture column can read anything on this scene ------------------------------------------
# A session whose own arms move by as much as the generations do has a picture column that measures the scene
# and not the switch, and the first session staged with the particle fixture is exactly that one: its reference
# arms differ by 9.11% of pixels where the largest cross-generation difference is 8.80%. The comparer therefore
# carries each pair's share beyond eight levels back with its sentence and says when the generations cannot be
# separated by picture, instead of printing five numbers a reader would take as a verdict.
for needle, why in (
    ("            100 * beyond / count)",
     "the picture comparison no longer returns the share of pixels beyond eight levels, so nothing can read the "
     "scene's own movement against the difference the session is measuring"),
    ("        own = [value for value, same in picture_spread if same and value >= 0.0]",
     "the comparer no longer separates the arms of one generation from the cross-generation pairs, so it cannot "
     "say whether its picture column is a reading of the switch or of the scene"),
    ("so this scene cannot separate the generations by picture",
     "the comparer prints cross-generation picture differences without saying when the scene's own arms move at "
     "least as much - which is the reading a fixture-staged session invites and cannot support"),
):
    if needle not in comparer:
        raise SystemExit("Vitrail performance harness contract: " + why)

PROBE_SOURCE = ROOT / "src/main/java/com/metallum/render/shared/MetalFrameProbe.java"
if "windowTicks={} framesPerTick={}" not in PROBE_SOURCE.read_text(encoding="utf-8"):
    raise SystemExit("Vitrail performance harness contract: the probe no longer reports the tick sampling the "
                     "comparer reads")

# --- and a picture difference has to be attributable to a region -------------------------------------------
# A global mean cannot tell a sky that is a level brighter from a terrain that is, and the audit's sky/cloud
# residual is a claim about a region. `tools/vitrail-picture-regions.py` classifies every pixel by the
# *reference* arm's colour and reads each arm class by class, and this writes a picture with a known sky, cloud
# and terrain band and a known difference in two of them, so the classification and the per-class arithmetic are
# checked rather than eyeballed. The PNG is written here rather than kept in the tree because a fixture that is
# twelve pixels of three colours is a fixture whose reader is the test.
REGIONS = ROOT / "tools/vitrail-picture-regions.py"
regions_text = REGIONS.read_text(encoding="utf-8")
for needle, why in (
    ("def classify(pixel: tuple[int, int, int]) -> str:",
     "the region reader no longer classifies a pixel, so a per-region difference cannot be read at all"),
    ("if min(pixel) >= 170 and max(pixel) - min(pixel) <= 40:",
     "the cloud test is gone, so a white cloud is counted as terrain or as sky"),
    ("if blue >= green >= red and blue >= 120 and blue - red >= 25:",
     "the sky test is gone, so the blue sky is counted as terrain"),
    ("classes = [classify(pixel) for pixel in reference_pixels]",
     "the classification is no longer taken from the reference arm, so a difference can move a pixel from one "
     "class to another and report both as unchanged"),
    ("bands top to bottom (mean |delta| per tenth)",
     "the row-band profile is gone, so a difference cannot be localised to the top or the bottom of a frame "
     "without depending on a colour threshold"),
):
    if needle not in regions_text:
        raise SystemExit("Vitrail performance harness contract: " + why)


def write_png(path, rows):
    """A PNG of 8-bit RGB, filter 0 a row - enough to be read back by the reader under test."""
    height, width = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SKY = (100, 150, 220)
CLOUD = (240, 240, 245)
GROUND = (40, 80, 40)
with tempfile.TemporaryDirectory() as scratch:
    session_dir = Path(scratch)
    (session_dir / "order.txt").write_text("m3\nm4\n", encoding="utf-8")
    for name, bump in (("m3", 0), ("m4", 4)):
        arm_dir = session_dir / name
        arm_dir.mkdir()
        rows = [[tuple(min(255, channel + bump) for channel in SKY) for _ in range(12)] for _ in range(2)]
        rows.append([tuple(min(255, channel + bump) for channel in CLOUD) for _ in range(12)])
        rows.append([GROUND for _ in range(12)])
        write_png(arm_dir / "screen.png", rows)
    read_regions = subprocess.run(["python3", str(REGIONS), scratch],
                                  check=True, capture_output=True, text=True).stdout
for needed, why in (
    ("cloud          12 px", "the cloud band is not counted as cloud, so a white region is not separable"),
    ("sky            24 px", "the sky band is not counted as sky"),
    ("terrain        12 px", "the ground band is not counted as terrain, so the control region is not read"),
    ("sky            24 px  mean |delta|  4.00", "the sky's own difference is not read as its four levels"),
    ("cloud          12 px  mean |delta|  4.00", "the cloud's own difference is not read as its four levels"),
    ("terrain        12 px  mean |delta|  0.00", "the control region's unchanged pixels are not read as zero"),
):
    if needed not in read_regions:
        raise SystemExit("Vitrail performance harness contract: " + why)

print("Vitrail performance harness contract: PASS")

# ==================== was tools/ci-performance-report.py ====================
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


def performance_report_main() -> int:
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



_MAIN_STATUS.append(performance_report_main())

# ==================== was tools/ci-summary.py ====================
"""The contract for the long-term plan's summary page.

`docs/long-term-performance-summary.md` is the one page a reader gets the whole programme from: each track's
decision, the number that decided it, the success criteria audited, and what is left open. Its value is that every
figure on it is the figure the track document owns - and its risk is exactly the same thing. A summary is copied
prose: change 9.8 per cent to 8.9 in `docs/vitrail-gpu-performance.md` and the summary goes on saying 9.8, in the
one document most likely to be read alone.

So the figures below are checked BOTH ways - stated on the summary page, and present in the document the summary
names beside them - and the pair is what makes the check meaningful. A figure that drifts out of its track document
is a summary that is wrong; a figure that leaves the summary is a reader who no longer sees it.

The comparison is on the figure and not on the phrasing: the summary writes "per cent" where a track document
writes "%", and rounds where the document does not, so each entry carries both spellings. Adding a claim to the
summary does not need an entry here; changing one that is here does.
"""

SUMMARY = ROOT / "docs/long-term-performance-summary.md"

# label, as the summary states it, as the owning document states it, the document
CLAIMS = (
    ("A1's redundant share", "0.1-0.3 per cent", "0.1-0.3 %", "metal3-performance-round2.md"),
    ("A1's bind calls", "226 to\n831 bind operations", "830.7", "metal3-performance-round2.md"),
    ("A1's indirect draws", "2425-3759", "2425", "metal3-performance-round2.md"),
    ("B1's allocation", "71-183 KiB", "71.3 KiB", "vitrail-cpu-performance.md"),
    ("D1's seam", "0.066-0.70 per cent", "0.066", "bridge-overhead.md"),
    ("D1's resolution caching", "2 lookups since launch", "2 lookups since launch", "bridge-overhead.md"),
    ("E2's gain on the lightest pack", "1.19x", "1.19x", "metalfx-performance.md"),
    ("F3's cold build", "187 units", "187", "startup-and-cache.md"),
    ("F4's Metal calls", "874 calls", "874", "startup-and-cache.md"),
    ("F4's worst compile", "10.87", "10.87", "startup-and-cache.md"),
    ("C2's shipped reuse", "9.8 per cent", "9.8 per cent", "vitrail-gpu-performance.md"),
    ("C2's interval on the second pack", "3.0 per cent", "3.0 per cent", "vitrail-gpu-performance.md"),
    ("C3's scaled size", "1056x660", "1056x660", "vitrail-gpu-performance.md"),
    ("C4's elided bytes", "17.6 MiB", "17.6 MiB", "vitrail-gpu-performance.md"),
    ("C7's traffic fall", "38.1 per cent", "38.1 per cent", "vitrail-gpu-performance.md"),
    ("G3's readback stall", "273 ms inside", "273", "performance-testing.md"),
    ("F3's in-session reload", "about a second, serves 147 module-cache units", "147", "startup-and-cache.md"),
    # The acceptance table's BASELINE column is the corpus's own, so the two are checked against each other
    # rather than against the summary's copy of itself.
    ("the acceptance baseline's MakeUp traffic", "385.8", "385.8", "vitrail-gpu-performance.md"),
    ("the acceptance baseline's no-pack traffic", "18.3", "18.3", "vitrail-gpu-performance.md"),
    # The acceptance's own correction: the scene that read +6.9 per cent against a baseline four hours older was
    # re-run with the baseline's code, and the two agree. Both halves are pinned, because a correction is a figure
    # like any other and the page most likely to be read alone is the one that would keep the old reading.
    ("the baseline's code re-measured in the acceptance's machine state", "1.795 ms a frame", "1.795",
     "performance-testing.md"),
    ("the acceptance no-pack arm's tail", "2.63 ms", "2.63 ms", "performance-testing.md"),
    # The declined candidate's own number, kept pinned for the reason this file exists: the summary now says the
    # owner decided against the shadow map's default, and the per cent that made it worth asking has to stay in the
    # track document that measured it or the two would part company.
    ("the shadow default that was declined", "5.7 per cent on MakeUp", "5.7", "vitrail-gpu-performance.md"),
)

# The one line the page is for: the success criteria, and the one that is not met.
CRITERIA = (
    "1.  Metal 3 has no visible regression          MET",
    "5.  A batch of low-risk CPU optimisations      NOT MET",
    "11. Metal 4 stays compilable and runnable      MET",
)


def summary_main() -> int:
    if not SUMMARY.is_file():
        raise SystemExit("the summary page is missing: the programme has no single page stating what it proved")

    summary = SUMMARY.read_text(encoding="utf-8")
    for label, stated, _owned, _source in CLAIMS:
        if stated not in summary:
            raise SystemExit(f"the summary no longer states {label} ({stated!r}), so a reader loses the number "
                             f"that decided its track")

    for label, _stated, owned, source in CLAIMS:
        document = ROOT / "docs" / source
        if not document.is_file():
            raise SystemExit(f"the summary names {source}, which is not in docs/")
        if owned not in document.read_text(encoding="utf-8"):
            raise SystemExit(f"the summary states {label} from {source} and {source} no longer carries "
                             f"{owned!r} - the summary is now the only place that number exists")

    for line in CRITERIA:
        if line not in summary:
            raise SystemExit(f"the summary's criteria audit no longer carries {line!r}")

    # `NOT MET` contains `MET`, so a plain count reads eleven criteria met out of eleven and would not notice
    # the one that is not - which is the line a reader most needs to be true.
    met = len(re.findall(r"(?<!NOT )\bMET\b", summary))
    if met != 10:
        raise SystemExit(f"the summary's criteria audit marks {met} criteria MET, and section 61 has eleven of "
                         f"which exactly one is not")
    # The three answers the owner gave, each pinned as the DECISION and not as the topic: a page that says E4
    # "is not started" leaves a reader waiting for it, and one that names the shadow map's default without saying
    # what was decided leaves the next person to re-open a settled question.
    for decided in ("The shadow map's default stays at one kept frame",
                    "E4, dynamic resolution, is declined and will not be built",
                    "Solas is not coming, so the corpus stays at four scenes"):
        if decided not in summary:
            raise SystemExit(f"the summary no longer records the owner's decision: {decided!r}")
    if "Solas" in summary.split("## The owner's answers", 1)[-1].split("## Where the evidence is")[0] \
            and "not coming" not in summary:
        raise SystemExit("the summary mentions Solas as outstanding after the owner declined to supply it")

    print(f"long-term summary contract: PASS ({len(CLAIMS)} figures traced both ways, {met} criteria marked MET)")
    return 0



_MAIN_STATUS.append(summary_main())

raise SystemExit(max(_MAIN_STATUS) if _MAIN_STATUS else 0)
