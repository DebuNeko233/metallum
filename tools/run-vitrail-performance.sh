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
width=1600
height=900
timeout_seconds=900
runs=()
keep=false

usage() {
	cat >&2 <<'USAGE'
Usage: run-vitrail-performance.sh --pack ZIP --world SAVE_DIR [options]

  --pack ZIP             the shader pack to measure, staged into the dev instance. It is copied
                         and never committed; run/ is ignored by git.
  --world SAVE_DIR       a world directory to measure in, copied into run/saves under its own name.
  --run NAME[=VMARGS]    one configuration to measure; repeat for as many as wanted, and the first
                         is the one the others are compared against. VMARGS are extra JVM
                         arguments for that run, e.g.
                         --run plain --run 'elide=-Dvitrail.elideTargetTraffic=true'
  --vitrail DIR          the Vitrail checkout (default: a sibling of this repository).
  --frames N             frames each window counts (default 600, the probe's own default).
  --width W --height H   the window the scene is drawn at (default 1600x900).
  --timeout S            how long to wait for the world, the pack and the window (default 900).
  --out DIR              where the collected logs and pictures go.
  --keep                 leave the collected dev instance in place instead of clearing the marker.

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
		--width) width="$2"; shift 2 ;;
		--height) height="$2"; shift 2 ;;
		--timeout) timeout_seconds="$2"; shift 2 ;;
		--out) out_dir="$2"; shift 2 ;;
		--keep) keep=true; shift ;;
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
mkdir -p "$pack_dir" "$saves_dir" "$game_dir/vitrail" "$game_dir/config" "$marker_dir" "$out_dir"

# The pack is copied rather than moved or linked: a run must not be able to write to the owner's
# copy of it, and the harness must be re-runnable against the same archive.
cp -f "$pack_path" "$pack_dir/$pack_name"

# What the pack-selection UI would have written, written here instead, so that the game comes up
# with the pack already applied rather than waiting for a click. The four keys are the whole of the
# file, and leaving the ones this harness has no opinion about at their defaults is deliberate.
cat > "$game_dir/vitrail/pack.txt" <<EOF
pack=$pack_name
enabled=true
shadowdistance=32
renderscale=100
shadowmapscale=100
EOF

# The Metal path is the one being measured, and a run that came up on another backend would measure
# nothing at all.
cat > "$game_dir/config/metallum.properties" <<'EOF'
#Metallum graphics API preference
preferredGraphicsApi=metal
EOF

if [[ ! -d "$saves_dir/$world_name" ]]; then
	cp -R "$world_path" "$saves_dir/$world_name"
fi

jar="$("$vitrail_root/gradlew" -p "$vitrail_root" :fabric:jar -q --console=plain >/dev/null && \
	find "$vitrail_root/fabric/build/libs" -maxdepth 1 -name '*.jar' ! -name '*-sources.jar' \
		! -name '*-dev.jar' -print -quit)"
if [[ ! -f "$jar" ]]; then
	echo "Vitrail's fabric jar was not produced under $vitrail_root/fabric/build/libs" >&2
	exit 1
fi
echo "Measuring with $(basename "$jar")"

# One line of the log per run, and the numbers the harness waits on are the ones the engine already
# prints: the pack's first full frame, and the probe's window.
wait_for_log() {
	local pattern="$1" deadline="$2"
	while [[ "$(date +%s)" -lt "$deadline" ]]; do
		if [[ -f "$game_dir/logs/latest.log" ]] && grep -qF "$pattern" "$game_dir/logs/latest.log"; then
			return 0
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

	# The marker is removed before the launch and created only once the pack has drawn a full frame.
	# That order is the whole of what makes a window worth counting: armed at launch it counts the
	# frames before there is a world, which is what every hand-run window so far has measured.
	rm -f "$marker"
	: > "$game_dir/logs/latest.log" 2>/dev/null || true

	echo "Run '$name'${vmargs:+ with $vmargs}"
	(
		cd "$repo_root"
		./gradlew runClient -PvitrailSmokeJar="$jar" -PvitrailPerfVmArgs="$vmargs" \
			--console=plain --args "--quickPlaySingleplayer $world_name --width $width --height $height"
	) > "$run_dir/gradle.log" 2>&1 &
	launcher=$!

	deadline="$(( $(date +%s) + timeout_seconds ))"
	if ! wait_for_log "first full frame opened" "$deadline"; then
		echo "Run '$name' never reached a full frame; see $run_dir/gradle.log" >&2
		stop_run
		wait "$launcher" 2>/dev/null || true
		continue
	fi

	sleep 5
	touch "$marker"
	if ! wait_for_log "frame-probe" "$deadline"; then
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
