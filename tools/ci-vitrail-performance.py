#!/usr/bin/env python3
"""Pins the performance harness's shape, so that measuring this engine stays possible alone.

The harness is the only thing in either repository that can take a measurement without its owner:
it writes the pack selection the UI would have written, launches the client into a world, arms the
frame probe only once the pack has drawn a full frame, and collects the probe's window and a picture.
Every assertion here is about a property that made a hand-run measurement worthless at least once - a
window armed before there was a world, a pack named in the script rather than handed to it, a pack
committed to the repository instead of copied into an ignored dev instance - or about the one thing
that keeps the numbers honest, which is that they are the probe's own and not a second opinion.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
if 'pgrep -f "quickPlaySingleplayer" >/dev/null 2>&1' not in launcher:
    raise SystemExit(
        "the harness does not check for a client left over from an earlier session, so a run can be measured "
        "beside another one drawing into the same GPU and display"
    )
before(
    'pgrep -f "quickPlaySingleplayer" >/dev/null 2>&1',
    "./gradlew runClient",
    "the leftover-client check runs after the client is launched, which is not a check",
)
if 'pkill -9 -f "quickPlaySingleplayer $world_name"' not in launcher:
    raise SystemExit(
        "the stop does not escalate to SIGKILL, and a client whose render thread has stopped does not act on "
        "SIGTERM - measured, and it was still resident while later sessions measured"
    )
before(
    'pkill -f "quickPlaySingleplayer $world_name"',
    'pkill -9 -f "quickPlaySingleplayer $world_name"',
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
     "measurement of vanilla's rendering has to edit the instance by hand"),
    ('"renderClouds": f', "the profile still writes one fixed answer for renderClouds, so the "
     "clouds switch cannot reach the game's options"),
    ('VITRAIL_PROFILE_CLOUDS', "the clouds switch never reaches the profile writer"),
    ("--weather) weather=", "the harness cannot leave the world raining, so vanilla's largest particle system "
     "cannot be in a frame without a keyboard"),
    ("--keep-entities) keep_entities=true", "the harness always takes the world's entities out, so nothing a "
     "mob or a block entity draws can be measured"),
    ("--vanilla-particles) vanilla_particles=true", "the harness cannot stage the vanilla particle fixture"),
    ("--vanilla-mobs) vanilla_mobs=true", "the harness cannot stage the entity fixture, and the staged world "
     "holds no entities of its own, so nothing a mob draws can be in a frame"),
    ("for fixture in showcase mobshow; do", "only one fixture is checked against the game having loaded it, so "
     "the other can stage and emit nothing and read as a scene that has it"),
    ('grep -q "showcase: placed the pig"', "an arm that staged the entity fixture is not checked against the game "
     "having placed anything, which is how a fixture that loads and does nothing reads as a scene with entities - "
     "measured, one arm of run/vanilla-mobs had the summons and the arm beside it did not"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-showcase" "$saves_dir/$world_name/datapacks/showcase"',
     "the particle fixture is not copied from the repository, so the scene would live in an unversioned save"),
    ('cp -R "$repo_root/tools/fixtures/vanilla-mobs" "$saves_dir/$world_name/datapacks/mobshow"',
     "the entity fixture is not copied from the repository, so the scene it describes would live in an "
     "unversioned save"),
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
if 'printf \'window-opened %s\\n\' "$(date +%s)" >> "$run_dir/load-trace.txt"' not in launcher:
    raise SystemExit("the load trace does not say when the window opened, so no sample of it can be "
                     "attributed to the frames the probe counted")
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
if "{latest.log,probe.txt,screen.png,gradle.log,load.txt,load-trace.txt}" not in launcher:
    raise SystemExit("the harness does not say in its usage that an arm leaves a load trace, so a reader "
                     "of a session's directory does not know the evidence is there")

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

# The window opens on a settled scene, and how long that takes is a switch rather than a constant: the
# measurement that motivated it - two pinned runs of one configuration 4.4 per cent apart after five seconds
# - says five is not obviously enough.
if "--settle" not in launcher or 'sleep "$settle_seconds"' not in launcher \
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

if "tools/ci-vitrail-performance.py" not in CI.read_text(encoding="utf-8"):
    raise SystemExit("this contract is not named by ci.yml, so nothing runs it")

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

print("Vitrail performance harness contract: PASS")
