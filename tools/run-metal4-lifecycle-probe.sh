#!/usr/bin/env bash
#
# Section 71's lifecycle gate, driven from inside the client.
#
# The gate lists F3+T, a shader-pack switch, leaving and rejoining a world, a dimension change, a resize, a
# fullscreen change and a shutdown - and every one of them was pressed by a keyboard that this machine's
# automation permission refuses (`osascript` is denied with -1743). A gate that cannot be run is not a gate, so
# `com.metallum.mixin.render.LifecycleProbeMixin` drives the transitions through the client's own methods on a
# schedule the launch line states, and this script is the launch line.
#
#   tools/run-metal4-lifecycle-probe.sh <label> <pack.zip> <metal3|metal4> <schedule> [deadline-seconds]
#
# The schedule is `<name>@<client-tick>` entries, comma separated:
#
#   resize      Window.setWindowed(1600, 900)      a resize to an extent the session did not start at
#   fullscreen  Window.toggleFullScreen()          the fullscreen mode change
#   windowed    Window.setWindowed(1280, 720)      back out of it
#   reload      Minecraft.delayTextureReload()     F3+T's own path: clears the compilation caches
#   leave       Minecraft.clearClientLevel(...)    leaving the world
#   close       GLFW's window-close flag           a quit rather than a signal, so the teardown runs
#
# Two of the transitions the gate lists are NOT driven here and stay manual: a dimension change needs a teleport,
# and an in-session shader-pack *switch* needs the pack screen. The reload covers the half of a switch that this
# path can get wrong - the old compiled artifacts being retired while a frame still names them.
#
# The client is expected to leave on its own: the close action is the whole point, so the script waits for the
# process rather than killing it, and it reports whether that happened.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
jar="$vitrail_root/fabric/build/libs/vitrail-fabric-0.13.0-dev.perf.optimisation+mc26.2.jar"
world=PerfWorld

usage() {
	echo "usage: $0 <label> <pack.zip> <metal3|metal4> <name>@<tick>,... [deadline-seconds]" >&2
	exit 2
}
[[ $# -ge 4 ]] || usage
label="$1"
pack="$2"
generation="$3"
schedule="$4"
deadline_s="${5:-520}"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
	echo "the Metal 4 lifecycle probe requires Apple-Silicon macOS" >&2
	exit 2
fi
[[ -f "$repo_root/run/shaderpacks/$pack" ]] || { echo "no such pack in run/shaderpacks: $pack" >&2; exit 2; }
[[ -f "$jar" ]] || { echo "the Vitrail smoke jar was not found at $jar" >&2; exit 2; }

out="$repo_root/run/m4-lifecycle/$label"
mkdir -p "$out"

if pgrep -f "quickPlaySingleplayer $world" >/dev/null 2>&1; then
	echo "a client is already resident; refusing to start a second one" >&2
	exit 6
fi

cp "$repo_root/run/vitrail/pack.txt" "$out/pack.txt.selected"
sed -i '' "s/^pack=.*/pack=$pack/" "$repo_root/run/vitrail/pack.txt"
rm -f "$repo_root/run/logs/latest.log"
(
	cd "$repo_root"
	./gradlew runClient -PvitrailSmokeJar="$jar" -PvitrailHud=0 \
		-PvitrailPerfVmArgs="-Dmetallum.execution=$generation -Dmetallum.drawableReadback=true -Dmetallum.probeFrames=true -Dmetallum.lifecycleProbe=$schedule" \
		--console=plain \
		"--args=--quickPlaySingleplayer $world --width 1280 --height 720"
) > "$out/gradle.log" 2>&1 &
launcher=$!

deadline=$(( $(date +%s) + deadline_s ))
exited=""
while (( $(date +%s) < deadline )); do
	if ! pgrep -f "quickPlaySingleplayer $world" >/dev/null 2>&1; then
		exited="yes"
		break
	fi
	sleep 2
done
echo "=== $label ($pack, execution=$generation) left on its own: ${exited:-no} ==="
if [[ -z "$exited" ]]; then
	pkill -f "quickPlaySingleplayer $world" 2>/dev/null
fi
wait "$launcher" 2>/dev/null
sleep 1
cp "$repo_root/run/logs/latest.log" "$out/latest.log" 2>/dev/null
cp "$out/pack.txt.selected" "$repo_root/run/vitrail/pack.txt"

echo "--- the transitions the log proves ---"
grep -oE "lifecycle probe: (firing '[a-z]+' at client tick [0-9]+|'reload' completed)" "$out/latest.log" 2>/dev/null || true
echo "--- what the frame path did across them ---"
echo "  chain drawn:        $(grep -c 'the chain can draw' "$out/latest.log" 2>/dev/null)"
echo "  Vitrail stopped:    $(grep -c 'Vitrail stopped drawing' "$out/latest.log" 2>/dev/null)"
echo "  teardown timeouts:  $(grep -c 'was not observed complete\|closing with work' "$out/latest.log" 2>/dev/null)"
echo "  Stopping!:          $(grep -c 'Stopping!' "$out/latest.log" 2>/dev/null)"
echo "  BUILD SUCCESSFUL:   $(grep -c 'BUILD SUCCESSFUL' "$out/gradle.log" 2>/dev/null)"
echo "  presented extents:  $(grep -o 'drawable readback \[metal[34]\]: [0-9]*x[0-9]*' "$out/latest.log" 2>/dev/null | sed 's/.*: //' | uniq -c | tr -s ' ' | tr '\n' ';')"
echo "=== $label: log at $out/latest.log; pack restored to $(head -1 "$repo_root/run/vitrail/pack.txt") ==="
