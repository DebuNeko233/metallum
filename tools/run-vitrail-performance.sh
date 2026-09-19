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
width=1600
height=900
timeout_seconds=900
runs=()
keep=false
fresh_world=true

usage() {
	cat >&2 <<'USAGE'
Usage: run-vitrail-performance.sh --pack ZIP --world SAVE_DIR [options]

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
  --width W --height H   the window the scene is drawn at (default 1600x900).
  --timeout S            how long to wait for the world, the pack and the window (default 900).
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
		--width) width="$2"; shift 2 ;;
		--height) height="$2"; shift 2 ;;
		--timeout) timeout_seconds="$2"; shift 2 ;;
		--out) out_dir="$2"; shift 2 ;;
		--keep) keep=true; shift ;;
		--continue-world) fresh_world=false; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
	esac
done

if [[ -z "$pack_path" || -z "$world_path" ]]; then
	usage
	exit 2
fi
if [[ ${#runs[@]} -eq 0 ]]; then
	runs=("plain")
fi
if [[ ! -f "$pack_path" ]]; then
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
saves_dir="$game_dir/saves"
pack_dir="$game_dir/shaderpacks"
pack_name="$(basename "$pack_path")"
world_name="$(basename "$world_path")"

echo "Preparing the dev instance at $game_dir"
mkdir -p "$pack_dir" "$saves_dir" "$game_dir/vitrail" "$game_dir/config" "$marker_dir" \
	"$game_dir/logs" "$out_dir"

# The pack is copied rather than moved or linked: a run must not be able to write to the owner's
# copy of it, and the harness must be re-runnable against the same archive.
cp -f "$pack_path" "$pack_dir/$pack_name"

# The choices the owner made in the pack's own settings screen sit beside the archive in a file named
# after it with .txt after that, and they travel with the archive or the pack comes up on its own
# defaults. That is not the same scene: a pack option selects which targets a program samples, so the
# defaults can be a different number of samplers in a program and therefore a different pipeline shape
# from the one the owner has been measuring. The sidecar is copied when it is there and its absence is
# said out loud, because a run that quietly measured a pack nobody has configured would still look
# like a run.
pack_options="$pack_path.txt"
if [[ -f "$pack_options" ]]; then
	cp -f "$pack_options" "$pack_dir/$pack_name.txt"
else
	echo "No options beside the pack, so it comes up on its own defaults: $pack_options" >&2
fi

# What the pack-selection UI would have written, written here instead, so that the game comes up
# with the pack already applied rather than waiting for a click. The four keys are the whole of the
# file, and leaving the ones this harness has no opinion about at their defaults is deliberate.
cat > "$game_dir/vitrail/pack.txt" <<EOF
pack=$pack_name
enabled=true
shadowdistance=32
renderscale=$renderscale
shadowmapscale=100
EOF

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
	pkill -f "quickPlaySingleplayer $world_name" 2>/dev/null || true
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
	python3 "$repo_root/tools/freeze-world.py" "$saves_dir/$world_name" --still-life --spectator

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
	# The game's arguments go in through `--args=`, and not through `--args` and a separate word: a
	# word that begins with two dashes is read as the next option rather than as the option's
	# argument, which is how the first launch of this harness failed to start a client at all.
	(
		cd "$repo_root"
		./gradlew runClient -PvitrailSmokeJar="$jar" \
			-PvitrailPerfVmArgs="-Dmetallum.frameProbeBudget=$frames${vmargs:+ $vmargs}" \
			--console=plain \
			"--args=--quickPlaySingleplayer $world_name --width $width --height $height"
	) > "$run_dir/gradle.log" 2>&1 &
	launcher=$!

	deadline="$(( $(date +%s) + timeout_seconds ))"
	wait_for_log "first full frame opened" "$deadline" "$launcher" && reached=0 || reached=$?
	if [[ "$reached" != 0 ]]; then
		if [[ "$reached" == 2 ]]; then
			echo "Run '$name' stopped before the pack drew a frame; see $run_dir/gradle.log" >&2
		else
			echo "Run '$name' never reached a full frame; see $run_dir/gradle.log" >&2
		fi
		stop_run
		wait "$launcher" 2>/dev/null || true
		continue
	fi

	sleep 5
	touch "$marker"
	if ! wait_for_log "frame-probe" "$deadline" "$launcher"; then
		echo "Run '$name' never produced a probe window" >&2
	fi

	# Taken while the game is still drawing, so the picture is the frame the numbers describe. The
	# whole screen rather than the game's window, because asking for a window would need the window
	# server to be told which one, and the harness is already standing in front of it.
	screencapture -x "$run_dir/screen.png" 2>/dev/null || \
		echo "No screenshot for run '$name'; the display may be locked." >&2

	cp -f "$game_dir/logs/latest.log" "$run_dir/latest.log" 2>/dev/null || true
	grep -F "frame-probe" "$run_dir/latest.log" > "$run_dir/probe.txt" 2>/dev/null || true
	grep -F "first full frame opened" "$run_dir/latest.log" > "$run_dir/frame.txt" 2>/dev/null || true

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

python3 "$repo_root/tools/vitrail-performance-compare.py" "$out_dir"
