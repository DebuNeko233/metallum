#!/usr/bin/env bash
#
# The performance harness: measure Vitrail without anybody watching.
#
# Every measurement this repository has taken needed its owner to launch the game, pick the pack,
# play for a while and hand back a log. The pieces needed to remove them were all here already and
# none of them was joined up:
#
#   - Metallum's Loom client is the only dev client that can run the Metal path, and `runClient`
#     takes `--args`, so `--quickPlaySingleplayer` walks straight into a world with no menu.
#   - `vitrail/pack.txt` is a plain properties file, so the pack is chosen before the game starts
#     rather than in its UI, and `config/metallum.properties` does the same for the Metal preference.
#   - the frame probe is armed by a marker file in the game directory, so it can be armed from out
#     here once the pack's first full frame has been reached - which is the moment a window worth
#     counting begins, and the moment a window armed at launch never reaches.
#   - `screencapture` needs no cooperation from the game, so a run leaves a picture behind without
#     anybody pressing F2.
#
# So one run is: prepare the instance, launch into the world with one set of switches, wait for the
# pack to draw a full frame, arm the probe, wait for its window, photograph the screen, stop. Two
# runs of one scene under two sets of switches are the comparison this exists for, and
# `vitrail-performance-compare.py` prints them side by side.
#
# What it cannot do is play. The client is left standing where the world put it, so the picture it
# leaves is evidence of a plausible frame and not a person's judgement of one, and the difference
# between two runs is a difference of pixels and counters rather than of opinions.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
pack_path=""
world_path=""
out_dir="$repo_root/run/performance"
frames=600
renderscale=100
shadowmap_scale=100
aim_args=()
width=1600
height=900
timeout_seconds=900
settle_seconds=25
runs=()
keep=false
met_all=0
fresh_world=true
no_pack=false
fixture_pack=false
fullscreen=false
expect_target=""
fullscreen_size=""

usage() {
	cat >&2 <<'USAGE'
Usage: run-vitrail-performance.sh --pack ZIP --world SAVE_DIR [options]

  --fullscreen           ask the game for a fullscreen window, which is the configuration a frame's
                         ceiling is read in: the display's own mode, no window chrome, and no compositor
                         limit on the frame rate.
  --no-pack              measure the game's own renderer through this engine's backend: no pack is
                         staged and the pack selection is written disabled, so nothing of a pack is in
                         the frame. This is the baseline a pack's cost is read against, and the
                         configuration a migration of the frame path is judged in first.
  --pack ZIP             the shader pack to measure, staged into the dev instance together with the
                         options file beside it, if there is one. It is copied and never committed;
                         run/ is ignored by git.
  --world SAVE_DIR       a world directory to measure in, copied into run/saves under its own name.
  --run NAME[=VMARGS]    one configuration to measure; repeat for as many as wanted, and the first
                         is the one the others are compared against. VMARGS are extra JVM
                         arguments for that run, e.g.
                         --run plain --run 'elide=-Dvitrail.elideTargetTraffic=true'
  --vitrail DIR          the Vitrail checkout (default: a sibling of this repository).
  --frames N             frames each window counts (default 600, the probe's own default).
  --renderscale N        the render scale written into the pack selection (default 100). Below
                         100 the frame draws smaller and pays an upscale at the window's own
                         size, which is the setting the upscaling phase has to replace.
  --at X,Y,Z             where the scene is looked at from, written into the staged world's player
                         records before each run.
  --yaw DEG --pitch DEG  how it is looked at. A comparison that judges pixels has to choose its frame:
                         the same world holds an animated block texture from one angle and open sky
                         from another, and the save's own angle is wherever the player left it.
  --shadowmapscale N     the shadow map scale written into the pack selection (default 100). It is
                         a separate setting from the render scale because it moves a different
                         half of the frame: shadows are geometry and vertex work, which the render
                         scale does not touch.
  --fullscreen-size WxH  the framebuffer the fullscreen window must take, written into the game's own
                         overrideWidth/overrideHeight. Without it the game asks the display for nothing
                         in particular and takes whatever mode it is already in, which is machine state:
                         four different modes were measured across one evening, and a JFR crash moved the
                         display from 1920x1200 to 3200x1800 in the middle of a programme. Written for
                         every run, so the arms of a session and the sessions of a programme are all on
                         one target.
  --expect-target WxH    refuse a run whose world is not drawn at this size, read from the log's own
                         "The world renders at WxH" line. The render target is not pinned by anything
                         else: the display has several fullscreen modes, the game takes the one the
                         display is already in, and a crashed client can leave it on another - measured,
                         one JFR crash moved every later run from 1056x660 to 1760x990 and two arms of
                         one session were measured on a target 2.2x the baseline's. Two arms that agree
                         with each other are still not comparable with the baseline, which the compare
                         script cannot see because it only compares the arms with each other.
  --width W --height H   the window the scene is drawn at (default 1600x900).
  --timeout S            how long to wait for the world, the pack and the window (default 900).
  --settle S             how long to keep drawing between the frame that says the chain is up and the
                         marker that opens the window (default 25). The window used to open five seconds
                         after the pack's first full frame, and measured against that: two runs of one
                         configuration read 7.26 and 7.58 ms a frame with the camera pinned - 4.4 per cent
                         apart. At 25 seconds the same pair read 7.26 and 7.27 with the structural counters
                         within 0.2 per cent, because the world's streaming and the pack's temporal history
                         have reached the same state in both arms by then. Five is kept as the fast path for
                         a run whose result is not a claim.
  --out DIR              where the collected logs and pictures go.
  --keep                 leave the collected dev instance in place instead of clearing the marker.
  --continue-world       let each run carry on from the world the last one saved instead of
                         starting from the staged copy again. Off by default, because the world's
                         clock runs while a session is loaded and a scene lit by a moved sun is a
                         different scene: a comparison across runs that share a save measures the
                         sun rather than the switch.

Every run writes <out>/<name>/{latest.log,probe.txt,screen.png,gradle.log}, and the harness ends by
printing the comparison between them.
USAGE
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--pack) pack_path="$2"; shift 2 ;;
		--world) world_path="$2"; shift 2 ;;
		--run)
			runs+=("$2")
			shift 2
			;;
		--vitrail) vitrail_root="$2"; shift 2 ;;
		--frames) frames="$2"; shift 2 ;;
		--renderscale) renderscale="$2"; shift 2 ;;
		--shadowmapscale) shadowmap_scale="$2"; shift 2 ;;
		--fullscreen) fullscreen=true; shift ;;
		--expect-target) expect_target="$2"; shift 2 ;;
		--fullscreen-size) fullscreen_size="$2"; shift 2 ;;
		--no-pack) no_pack=true; shift ;;
		--fixture) fixture_pack=true; shift ;;
		--at) aim_args+=(--at "$2"); shift 2 ;;
		--yaw) aim_args+=(--yaw "$2"); shift 2 ;;
		--pitch) aim_args+=(--pitch "$2"); shift 2 ;;
		--width) width="$2"; shift 2 ;;
		--height) height="$2"; shift 2 ;;
		--timeout) timeout_seconds="$2"; shift 2 ;;
		--settle) settle_seconds="$2"; shift 2 ;;
		--out) out_dir="$2"; shift 2 ;;
		--keep) keep=true; shift ;;
		--continue-world) fresh_world=false; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
	esac
done

if [[ -z "$world_path" || ( -z "$pack_path" && "$no_pack" == false ) ]]; then
	usage
	exit 2
fi
if [[ ${#runs[@]} -eq 0 ]]; then
	runs=("plain")
fi
if [[ "$no_pack" == false && ! -f "$pack_path" ]]; then
	echo "No pack at: $pack_path" >&2
	exit 2
fi
if [[ ! -d "$world_path" ]]; then
	echo "No world at: $world_path" >&2
	exit 2
fi

game_dir="$repo_root/run"
marker_dir="$game_dir/metallum"
marker="$marker_dir/probe-frames"
export VITRAIL_PROFILE_FULLSCREEN="$fullscreen"
export VITRAIL_PROFILE_FULLSCREEN_SIZE="$fullscreen_size"
saves_dir="$game_dir/saves"
pack_dir="$game_dir/shaderpacks"
pack_name="$(basename "$pack_path")"
world_name="$(basename "$world_path")"

# A world is copied *into* the instance under its own name, so one that already is the copy is deleted by
# the copy's own first step: `--world run/saves/PerfWorld` removes run/saves/PerfWorld and then has nothing
# to copy, which is measured - it took the staged world with it and the run collected an empty directory.
# Refused here rather than trusted. The world to measure is the staged one outside the instance.
if [[ "$(cd "$world_path" && pwd -P)" == "$saves_dir/"* ]]; then
	echo "The world asked for is already inside the instance: $world_path" >&2
	echo "This harness would delete it before copying it. Point --world at a staged copy outside $saves_dir." >&2
	exit 2
fi

# The pack is copied in under its own name the same way, and `cp` refuses a file that is already the
# destination rather than silently doing nothing - which, under `set -e`, ends the run before it starts.
# Measured on a pack staged where it was being copied to. Refused here with the reason, because the fix is
# the same one: the pack to measure is the staged copy outside the instance.
if [[ "$no_pack" == false && "$(cd "$(dirname "$pack_path")" && pwd -P)/$(basename "$pack_path")" == "$pack_dir/"* ]]; then
	echo "The shader pack asked for is already inside the instance: $pack_path" >&2
	echo "Point --pack at a copy outside $pack_dir; the harness stages it into the instance itself." >&2
	exit 2
fi

echo "Preparing the dev instance at $game_dir"

# A client left over from an earlier session draws into the same GPU and the same display, so a session that
# starts with one running is not the scene it says it is - and this is measured, not hypothetical: three
# clients whose render threads had stopped (the shape a GPU fault leaves behind) were still resident thirty to
# forty-seven minutes later, through two later sessions' windows, because `stop_run` sends SIGTERM and a client
# that is no longer drawing does not act on it. Refused rather than measured around: the numbers of a run made
# beside another client are not that run's numbers.
if pgrep -f "quickPlaySingleplayer" >/dev/null 2>&1; then
	echo "Another Minecraft client is already running, and it would draw into the GPU and display this run measures:" >&2
	pgrep -fl "quickPlaySingleplayer" >&2 || true
	echo "Stop it first, then run this again: pkill -9 -f quickPlaySingleplayer" >&2
	exit 6
fi

mkdir -p "$pack_dir" "$saves_dir" "$game_dir/vitrail" "$game_dir/config" "$marker_dir" \
	"$game_dir/logs" "$out_dir"

# The picture evidence this harness produces is a screenshot of the display, and a locked, asleep or absent
# display captures as a single flat colour. Measured rather than imagined: every capture of two sessions was
# one black colour, and the comparison then printed "0.00% of pixels differ" for two pictures of nothing - the
# strongest verdict it can print, about no evidence at all. The instrument is checked here, before a session
# spends its launches, and a display that cannot be photographed is carried as a void picture column rather
# than as a refusal of the session: the counters are the measurement and the picture is the aid, and a harness
# that refused to measure at all whenever a screen was asleep would not be the harness this is.
picture_void=0
capture_probe="$out_dir/capture-probe.png"
if ! screencapture -x "$capture_probe" 2>/dev/null || [[ ! -s "$capture_probe" ]]; then
	echo "The display could not be captured at all, so this session's picture column will be void." >&2
	picture_void=1
elif ! python3 "$repo_root/tools/vitrail-performance-compare.py" --capture-check "$capture_probe"; then
	echo "The display captures as one flat colour, which is what a locked or asleep screen does, so this session's picture column will be void: its counters are measurements and its pictures are not." >&2
	picture_void=1
fi
rm -f "$capture_probe"

# The pack is copied rather than moved or linked: a run must not be able to write to the owner's
# copy of it, and the harness must be re-runnable against the same archive.
if [[ "$no_pack" == false ]]; then
	cp -f "$pack_path" "$pack_dir/$pack_name"
fi

# The choices the owner made in the pack's own settings screen sit beside the archive in a file named
# after it with .txt after that, and they travel with the archive or the pack comes up on its own
# defaults. That is not the same scene: a pack option selects which targets a program samples, so the
# defaults can be a different number of samplers in a program and therefore a different pipeline shape
# from the one the owner has been measuring. The sidecar is copied when it is there and its absence is
# said out loud, because a run that quietly measured a pack nobody has configured would still look
# like a run.
pack_options="$pack_path.txt"
if [[ "$no_pack" == true ]]; then
	:
elif [[ -f "$pack_options" ]]; then
	cp -f "$pack_options" "$pack_dir/$pack_name.txt"
else
	echo "No options beside the pack, so it comes up on its own defaults: $pack_options" >&2
fi

# What the pack-selection UI would have written, written here instead, so that the game comes up
# with the pack already applied rather than waiting for a click. The four keys are the whole of the
# file, and leaving the ones this harness has no opinion about at their defaults is deliberate.
if [[ "$no_pack" == true ]]; then
	echo "No pack: the game draws its own image through this engine's backend" >&2
	pack_name=""
	enabled=false
else
	enabled=true
fi
cat > "$game_dir/vitrail/pack.txt" <<EOF
pack=$pack_name
enabled=$enabled
shadowdistance=32
renderscale=$renderscale
shadowmapscale=$shadowmap_scale
EOF

# What this run asked for, fingerprinted, because the file is shared and two other things write it: the
# settings screen picking a pack, and the video settings moving one of its three numbers - both through a
# read-modify-write of the whole file. A session of the owner's own, or any reload that re-reads the file,
# can therefore turn the pack off under a run that is already counting. Measured: the pack loads, the probe
# arms, and the window counts the game's own frame, because the file said `enabled=false` by then.
pack_fingerprint="$(shasum -a 256 "$game_dir/vitrail/pack.txt" | cut -d' ' -f1)"

# The measurement profile, written into the staged instance on every run, because a frame rate must not
# be capped by a setting nobody remembered. `maxFps` is the game's own limiter - 120 here, which is
# invisible until the engine gets fast and then reads exactly like a display cap, measured: the same run
# read 120.2 frames a second with it and 137.4 without - and `enableVsync` is off for the same reason.
# Fullscreen is off because every baseline is a window, and the vanilla clouds are off because the pack
# draws its own.
python3 - "$game_dir/options.txt" <<'OPTIONS'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
fullscreen = "true" if os.environ.get("VITRAIL_PROFILE_FULLSCREEN") == "true" else "false"
# The graphics API is written too, and for a reason that has cost this harness several runs: Vitrail puts
# the API back to Vulkan by design when a session ends badly, so a run that follows a failed one comes up on
# MoltenVK - a different engine - and every number it produces is about that engine. Written before every run,
# and checked after it below. The word is the game's own `default`, which is the state Metallum's "Prefer
# Metal" (`config/metallum.properties`, written just below) needs: Metallum puts its backend in front of the
# game's list while the vanilla preference is Default, and only then, so a file naming Vulkan or OpenGL takes
# the Metal device out of the list entirely. An earlier version wrote the unparseable word `metal` here, which
# worked only because a value the game cannot parse falls back to that same default - a coincidence, not a
# spelling, and one that would have read as a harness fault the day it stopped.
#
# `startedCleanly` is the other half of the same trap, and writing the API alone does not close it. That flag
# is the game's own, read once at the head of `Minecraft`'s constructor, where it is set false and saved; a
# session killed before startup finishes leaves it false on disk, and Vitrail's `StartupGuard` answers the
# next launch by setting the API back to Vulkan *in memory*, before the backend list is built - which beats
# anything this harness wrote a second earlier. Measured: a Metal 4 run that hung left the two runs after it
# on MoltenVK, each of them logging "The last startup ended badly ... the API is put back to vulkan". Written
# true, so the guard has nothing to answer and the run after a hang is still the run that was asked for; a
# real player's instance is untouched, and the check below still refuses any run that came up elsewhere.
# The fullscreen window's own size, which is what decides the framebuffer and therefore the render
# target. `0x0` is the game's "ask the display for nothing in particular", and what that answers is
# whatever mode the display happens to be in: the same harness measured 1920x1200, 3200x1800,
# 3840x2400 and 3600x2038 across one evening, and a crashed fullscreen client left the display on
# another mode for every run after it. Pinning it is what makes the arms of a session, and the
# sessions of a programme, one target.
size = os.environ.get("VITRAIL_PROFILE_FULLSCREEN_SIZE", "").strip()
if "x" in size:
    width, _, height = size.partition("x")
    override_width, override_height = width.strip(), height.strip()
else:
    override_width, override_height = "0", "0"
profile = {"maxFps": "260", "enableVsync": "false", "fullscreen": fullscreen,
           "renderClouds": '"false"', "preferredGraphicsBackend": '"default"',
           "startedCleanly": "true",
           "overrideWidth": override_width, "overrideHeight": override_height}
lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
written = set()
for index, line in enumerate(lines):
    name = line.split(":", 1)[0]
    if name in profile:
        lines[index] = f"{name}:{profile[name]}"
        written.add(name)
for name, value in profile.items():
    if name not in written:
        lines.append(f"{name}:{value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
OPTIONS
echo "measurement profile: maxFps 260, vsync off, $([[ "$fullscreen" == true ]] && echo fullscreen || echo windowed), vanilla clouds off, Metal HUD off" >&2

# The Metal path is the one being measured, and a run that came up on another backend would measure
# nothing at all.
cat > "$game_dir/config/metallum.properties" <<'EOF'
#Metallum graphics API preference
preferredGraphicsApi=metal
EOF


# Which jar to measure is asked of the build rather than read out of its output directory. Every
# branch anybody has built leaves a jar in the same place, and a directory lists them in an order
# that is not the order they were built in, so listing that directory can measure a jar from another
# branch without saying so. The init script adds one task that runs after the jar and prints where
# that jar went; it has no outputs of its own, so it is never up to date and answers even when the
# jar itself was not rebuilt.
ask_which_jar="$(mktemp -t vitrail-perf-jar)"
cat > "$ask_which_jar" <<'INIT'
allprojects { project ->
	if (project.path != ":fabric") {
		return
	}
	project.afterEvaluate {
		def jarTask = project.tasks.named("jar")
		project.tasks.register("vitrailPerfJarPath") {
			dependsOn jarTask
			doLast {
				println "vitrail-perf-jar=" + jarTask.get().archiveFile.get().asFile.absolutePath
			}
		}
	}
}
INIT
asked="$("$vitrail_root/gradlew" -p "$vitrail_root" -I "$ask_which_jar" :fabric:jar \
	:fabric:vitrailPerfJarPath -q --console=plain | grep -F 'vitrail-perf-jar=' | tail -1 || true)"
rm -f "$ask_which_jar"
jar="${asked#vitrail-perf-jar=}"
if [[ ! -f "$jar" ]]; then
	echo "Vitrail's fabric jar was not produced under $vitrail_root/fabric/build/libs" >&2
	exit 1
fi
echo "Measuring with $(basename "$jar")"

# One line of the log per run, and the numbers the harness waits on are the ones the engine already
# prints: the pack's first full frame, and the probe's window. A launcher that has already exited is
# waited on no longer: a launch that failed says so in seconds, and a harness that sat out its whole
# timeout for a client that never started would be a harness nobody runs.
wait_for_log() {
	local pattern="$1" deadline="$2" launcher="$3"
	while [[ "$(date +%s)" -lt "$deadline" ]]; do
		if [[ -f "$game_dir/logs/latest.log" ]] && grep -qF "$pattern" "$game_dir/logs/latest.log"; then
			return 0
		fi
		if [[ -n "$launcher" ]] && ! kill -0 "$launcher" 2>/dev/null; then
			return 2
		fi
		sleep 2
	done
	return 1
}

stop_run() {
	# The client is stopped by the arguments it was launched with rather than by a signal to Gradle,
	# because Gradle's own process is the parent and killing it leaves the game running.
	#
	# Terminate, and then insist. A client that is still drawing exits on SIGTERM, and one whose render
	# thread has stopped does not - measured: three of those from earlier sessions were resident thirty to
	# forty-seven minutes later, holding the GPU and a window while later sessions measured, which is the
	# scene fact the pre-flight check above now refuses. SIGKILL is what takes them, so it is sent here
	# rather than left to the operator, and a client even that does not take is said out loud.
	pkill -f "quickPlaySingleplayer $world_name" 2>/dev/null || true
	for _ in $(seq 1 20); do
		pgrep -f "quickPlaySingleplayer $world_name" >/dev/null 2>&1 || return 0
		sleep 0.5
	done
	echo "A client from the last run did not act on SIGTERM; killing it" >&2
	pkill -9 -f "quickPlaySingleplayer $world_name" 2>/dev/null || true
	sleep 1
	if pgrep -f "quickPlaySingleplayer $world_name" >/dev/null 2>&1; then
		echo "A client from the last run is still resident after SIGKILL, so the next run's numbers would be read with it drawing" >&2
		stale_client=1
	fi
}

: > "$out_dir/order.txt"
for run in "${runs[@]}"; do
	name="${run%%=*}"
	printf '%s\n' "$name" >> "$out_dir/order.txt"
	vmargs=""
	if [[ "$run" == *=* ]]; then
		vmargs="${run#*=}"
	fi

	run_dir="$out_dir/$name"
	rm -rf "$run_dir"
	mkdir -p "$run_dir"

	# The world starts from the staged copy again, unless the caller asked each run to carry on. That
	# copy holds one time of day and one player position, so two runs of one comparison draw the same
	# scene rather than two scenes a few minutes of world time apart.
	if [[ "$fresh_world" == true ]]; then
		rm -rf "$saves_dir/$world_name"
	fi
	if [[ ! -d "$saves_dir/$world_name" ]]; then
		cp -R "$world_path" "$saves_dir/$world_name"
	fi

	# The copy above is a live world: the sun moves, mobs spawn, weather comes and goes, and two runs of
	# it therefore draw two different frames - measured at eleven per cent in pipelines and nineteen in
	# depth attachments between the arms of one comparison, which is a different scene rather than a
	# switch. It is frozen before the client starts, and the time it is frozen at is the same one every
	# run, so the two arms of a comparison are the same frame. The freeze also takes the world's entities
	# out: a rule can stop new mobs and cannot remove the ones already standing there, and one extra
	# entity draws a family's pass - measured as `cutout_cull entity` in one run of one configuration and
	# not in the other, which moves the depth attachments by a tenth. The player goes into spectator mode
	# with it, because a player draws their own entity and their hand and those are the last things inside
	# a frame that vary: with them, two runs of one configuration differ in five to nine per cent of their
	# texture and sampler counts, which is enough to swamp an effect of a few per cent.
	python3 "$repo_root/tools/freeze-world.py" "$saves_dir/$world_name" --still-life --spectator \
		${aim_args[@]+"${aim_args[@]}"}

	# The marker is removed before the launch and created only once the pack has drawn a full frame.
	# That order is the whole of what makes a window worth counting: armed at launch it counts the
	# frames before there is a world, which is what every hand-run window so far has measured.
	rm -f "$marker"
	: > "$game_dir/logs/latest.log" 2>/dev/null || true

	echo "Run '$name'${vmargs:+ with $vmargs}"
	# How long the window is belongs to this harness and not to the probe, because two windows of
	# different lengths are not two windows of one thing. The probe's own default is the same 600, so
	# the flag only matters when it is asked for.
	#
	# The Metal HUD is taken out of this run's frame, and that is not tidiness: the picture a comparison
	# reads is `screencapture`, so an overlay whose numbers and graph change every frame lands in it -
	# measured, 3.39 per cent of pixels above eight levels between two arms that drew the same scene. A
	# hand run keeps the overlay, which is what it is for.
	# The game's arguments go in through `--args=`, and not through `--args` and a separate word: a
	# word that begins with two dashes is read as the next option rather than as the option's
	# argument, which is how the first launch of this harness failed to start a client at all.
	(
		cd "$repo_root"
		./gradlew runClient -PvitrailSmokeJar="$jar" \
			-PvitrailHud=0 \
			-PvitrailPerfVmArgs="-Dmetallum.frameProbeBudget=$frames${vmargs:+ $vmargs}" \
			--console=plain \
			"--args=--quickPlaySingleplayer $world_name --width $width --height $height"
	) > "$run_dir/gradle.log" 2>&1 &
	launcher=$!

	deadline="$(( $(date +%s) + timeout_seconds ))"
	# What a window worth counting waits for. With a pack it is that pack's own first full frame, which is
	# the moment the chain it will be measured on has drawn something end to end. With no pack there is no
	# such line to wait for: the game draws its own image through this backend, and the signal that there is
	# a world to draw it in is the server's own world-load line. The window then opens a moment earlier in
	# the session than a pack's would, which is the same moment for every arm of a comparison.
	if [[ "$no_pack" == true ]]; then
		arm_pattern="Time elapsed:"
	else
		arm_pattern="first full frame opened"
	fi

	wait_for_log "$arm_pattern" "$deadline" "$launcher" && reached=0 || reached=$?
	if [[ "$reached" != 0 ]]; then
		if [[ "$reached" == 2 ]]; then
			echo "Run '$name' stopped before the pack drew a frame; see $run_dir/gradle.log" >&2
		else
			echo "Run '$name' never reached a full frame; see $run_dir/gradle.log" >&2
		fi
		# An arm that never armed measured nothing, and a harness that ends zero on it hands back an empty
		# comparison as if it were a result. Measured: the pass-timings arm timed out at 900 s and this
		# script still exited 0.
		run_failed=1
		stop_run
		wait "$launcher" 2>/dev/null || true
		continue
	fi

	# The scene is given time to settle before the window opens, and the amount is a switch because what
	# "settled" costs is a measurement: the first version of this waited five seconds and two runs of one
	# configuration still read 4.4 per cent apart with the camera pinned.
	sleep "$settle_seconds"
	touch "$marker"
	if ! wait_for_log "frame-probe" "$deadline" "$launcher"; then
		echo "Run '$name' never produced a probe window" >&2
		run_failed=1
	fi

	# Taken while the game is still drawing, so the picture is the frame the numbers describe. The
	# whole screen rather than the game's window, because asking for a window would need the window
	# server to be told which one, and the harness is already standing in front of it.
	screencapture -x "$run_dir/screen.png" 2>/dev/null || \
		echo "No screenshot for run '$name'; the display may be locked." >&2

	cp -f "$game_dir/logs/latest.log" "$run_dir/latest.log" 2>/dev/null || true
	# A run that came up on another backend is not this engine's frame, and Vitrail's own rescue is what puts
	# it there: after a session that ended badly it writes the API back to Vulkan, so the next launch is
	# MoltenVK with no Metal device and no pack. Said out loud here rather than left for a reader to notice
	# from a missing probe line.
	if ! grep -q "Using graphics backend Metal" "$run_dir/latest.log"; then
		backend="$(grep -o "Using graphics backend [A-Za-z]*" "$run_dir/latest.log" | head -1)"
		echo "Run '$name' did not come up on Metal (${backend:-no backend line at all}): a session that ended badly makes Vitrail put the graphics API back, and this run measured another engine" >&2
		met_all=1
	fi

	grep -F "frame-probe" "$run_dir/latest.log" > "$run_dir/probe.txt" 2>/dev/null || true
	grep -F "$arm_pattern" "$run_dir/latest.log" > "$run_dir/frame.txt" 2>/dev/null || true

	# A pack run whose window drew almost nothing is not a measurement of the pack, and it does not look
	# like a failure: the probe answers, the counters are self-consistent, and the numbers are the game's own
	# frame or a menu's. Three arms were lost to this before it was noticed, so it is refused here, by the
	# shape the fault actually has - a pack frame opens tens of passes a frame and copies its targets back,
	# and a frame with three passes and no copies at all is neither.
	# A fixture pack is a handful of full-screen passes and copies nothing, so the shape net below is about
	# a real pack and not about it: what has to hold there is the named evidence, which is checked either way.
	if [[ "$no_pack" == false && "$fixture_pack" == false ]]; then
		# Named evidence first, in the shape the smoke scripts use: the run must prove it was the run asked
		# for, and the pack's own name has to be in the line that proves it, so a window that quietly drew
		# something else cannot pass. `No pack asked for` is the engine saying the selection was off, and
		# `Left the world` is the session ending under the window.
		if grep -qF "No pack asked for" "$run_dir/latest.log"; then
			echo "Run '$name' has 'No pack asked for' in its log: the pack selection said nothing, so this window drew the game's own frame" >&2
			scene_bad=1
		fi
		if ! grep -qF "of $pack_name at render stage" "$run_dir/latest.log" && ! grep -qF "$pack_name" "$run_dir/latest.log"; then
			echo "Run '$name' never names the pack it asked for ($pack_name) in its log, so it did not draw it" >&2
			scene_bad=1
		fi
		if ! grep -qF "Stopping!" "$run_dir/latest.log"; then
			# A note and not a refusal: this harness stops the client itself once the window is in, so a
			# clean shutdown is evidence of a session that ended on its own and its absence says nothing
			# about the window. Requiring it refused an arm that had drawn the pack for 11 stage lines at
			# 39 passes a frame with 6600 copy-backs.
			echo "note: run '$name' has no clean-shutdown line, which is expected when this harness stopped it" >&2
		fi

		# And the shape, as the second net rather than the argument: a pack frame opens tens of passes a
		# frame and copies its targets back, whatever the log says.
		render_passes="$(grep -o 'renderPasses=[0-9]*' "$run_dir/probe.txt" | head -1 | cut -d= -f2)"
		frame_count="$(grep -o 'windowFrames=[0-9]*' "$run_dir/probe.txt" | head -1 | cut -d= -f2)"
		copies="$(grep -o 'blits=[0-9]*' "$run_dir/probe.txt" | head -1 | cut -d= -f2)"
		if [[ -n "$render_passes" && -n "$frame_count" && "$frame_count" -gt 0 \
			&& $((render_passes / frame_count)) -lt 10 && "${copies:-0}" -eq 0 ]]; then
			echo "Run '$name' counted $((render_passes / frame_count)) render passes a frame with no copy-backs: the window did not draw the pack, so its numbers are the game's own frame and are not a measurement" >&2
			scene_bad=1
		fi

		# And the cause, where it can be named: the selection file is shared, and it is the one thing that
		# decides whether the pack is drawn at all.
		if [[ "$(shasum -a 256 "$game_dir/vitrail/pack.txt" | cut -d' ' -f1)" != "$pack_fingerprint" ]]; then
			echo "Run '$name' had its pack selection changed while it was counting (pack.txt was $([ "$enabled" == true ] && echo 'enabled for '"$pack_name" || echo 'disabled') when the run started): another writer owns that file, so this window measured whatever the change left behind" >&2
			scene_bad=1
		fi

		# And the render target, where the caller asked for one. The world's drawn size is the only thing
		# that says which target a window measured, and the display's mode is machine state that a crash
		# can move: without this a session can collect two arms that agree with each other on a target the
		# baseline never used, and every number in them is about a different frame.
		if [[ -n "$expect_target" ]]; then
			drawn_target="$(grep -o 'The world renders at [0-9]*x[0-9]*' "$run_dir/latest.log" | tail -1 | sed 's/.*renders at //')"
			if [[ -z "$drawn_target" ]]; then
				echo "Run '$name' never said what size it drew the world at, so the target it measured cannot be checked against $expect_target" >&2
				scene_bad=1
			elif [[ "$drawn_target" != "$expect_target" ]]; then
				echo "Run '$name' drew the world at $drawn_target and not at $expect_target: the display's mode is machine state, a crash can move it, and a window on another target is not comparable with the baseline - restore the display mode and run again" >&2
				scene_bad=1
			fi
		fi

		if [[ "${scene_bad:-0}" == 0 ]]; then
			echo "Run '$name' performance window: PASS ($pack_name drawn, $((${render_passes:-0} / ${frame_count:-1})) render passes a frame, ${copies:-0} copy-backs, loadedMiB $(grep -o 'loadedMiB=[0-9.]*' "$run_dir/probe.txt" | head -1 | cut -d= -f2), storedMiB $(grep -o 'storedMiB=[0-9.]*' "$run_dir/probe.txt" | head -1 | cut -d= -f2))"
		fi
	fi

	stop_run
	# Gradle's own run task waits on the client, so a stopped client ends it; the wait is bounded so
	# that a client which refused to stop cannot hold the harness for the rest of the day.
	for _ in $(seq 1 30); do
		kill -0 "$launcher" 2>/dev/null || break
		sleep 2
	done
	kill "$launcher" 2>/dev/null || true
	wait "$launcher" 2>/dev/null || true

	echo "Run '$name' collected into $run_dir"
done

if [[ "$keep" == false ]]; then
	rm -f "$marker"
fi

# The comparison's own refusal is kept rather than re-raised through `set -e`, so that the checks below still
# report what they know: a compare that exits 4 over flat captures and a harness that exits 5 over a run that
# never armed are two different faults, and a reader wants both.
compare_status=0
python3 "$repo_root/tools/vitrail-performance-compare.py" "$out_dir" || compare_status=$?

if [[ "$met_all" == 1 ]]; then
	echo "At least one run did not come up on Metal; the comparison above is about another engine." >&2
	exit 3
fi

if [[ "${scene_bad:-0}" == 1 ]]; then
	echo "At least one run's window did not draw the pack it asked for; the comparison above holds that window's numbers and they are not a measurement of the pack." >&2
	exit 4
fi

if [[ "${run_failed:-0}" == 1 ]]; then
	echo "At least one run never armed, so the comparison above is missing it entirely." >&2
	exit 5
fi

if [[ "${stale_client:-0}" == 1 ]]; then
	echo "A client could not be stopped and was still resident, so the arms after it were measured beside another drawing client." >&2
	exit 7
fi

if [[ "$compare_status" == 4 || "${picture_void:-0}" == 1 ]]; then
	echo "No picture evidence: the display is not a screen this session could photograph (a locked or asleep display captures one flat colour), so the picture column above is not a verdict - the counters are." >&2
	exit 9
fi

if [[ "$compare_status" != 0 ]]; then
	echo "The comparison refused these runs with exit $compare_status; its own line above says why." >&2
	exit "$compare_status"
fi
