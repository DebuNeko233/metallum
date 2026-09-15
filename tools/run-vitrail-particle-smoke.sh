#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
mode=""
path_seen=false

usage() {
	echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal] [--opaque|--translucent]" >&2
}

for argument in "$@"; do
	case "$argument" in
		--opaque)
			[[ -z "$mode" ]] || { echo "Choose only one particle smoke mode." >&2; exit 2; }
			mode="opaque"
			;;
		--translucent)
			[[ -z "$mode" ]] || { echo "Choose only one particle smoke mode." >&2; exit 2; }
			mode="translucent"
			;;
		-*) usage; exit 2 ;;
		*)
			if [[ "$path_seen" == true ]]; then usage; exit 2; fi
			vitrail_root="$argument"
			path_seen=true
			;;
	esac
done

if [[ -z "$mode" ]]; then
	usage
	exit 2
fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
	echo "Vitrail Metal particle smoke runs require Apple-Silicon macOS." >&2
	exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
	echo "Vitrail checkout not found at: $vitrail_root" >&2
	exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture_verifier="$vitrail_root/tests/VerifyParticleScreenshot.java"
if [[ "$mode" == opaque ]]; then
	fixture_name="particles-opaque-contract"
	fixture_label="Particles opaque"
	pass_name="particles"
	program="gbuffers_particles"
else
	fixture_name="particles-translucent-contract"
	fixture_label="Particles translucent"
	pass_name="particles_translucent"
	program="gbuffers_particles_translucent"
fi

fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
fixture_target="$repo_root/run/shaderpacks/$fixture_name"
if [[ ! -d "$fixture_source/shaders" || ! -f "$fixture_verifier" ]]; then
	echo "Vitrail $fixture_label smoke contract is missing from: $vitrail_root" >&2
	exit 2
fi

mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
rm -rf "$fixture_target"
cp -R "$fixture_source" "$fixture_target"
fixture_marker="$repo_root/run/.vitrail-particles-${mode}-smoke-start"
touch "$fixture_marker"

echo "Installed Vitrail $fixture_label smoke fixture at: $fixture_target"
echo "Select '$fixture_name' in Vitrail's shader-pack UI; this launcher does not change pack selection."
if [[ "$mode" == opaque ]]; then
	echo "Spawn a dense vanilla smoke burst in front of the camera. Minecraft 26.2 smoke is an OPAQUE particle; for example use command autocomplete for: /particle minecraft:smoke ~ ~1 ~ 0.6 0.6 0.6 0.01 300 force"
	echo "Stable green means gbuffers_particles @ PARTICLES plus the four-element PARTICLE ABI passed. Translucent-only particles do not close this gate. Press F2 while the smoke is visible, then exit normally."
else
	echo "Spawn a dense vanilla witch-particle burst in front of the camera. Minecraft 26.2 witch particles are TRANSLUCENT; for example use command autocomplete for: /particle minecraft:witch ~ ~1 ~ 0.6 0.6 0.6 0.01 300 force"
	echo "Stable green means gbuffers_particles_translucent @ PARTICLES plus the four-element PARTICLE ABI passed. Opaque particles do not close this gate. Press F2 while the particles are visible, then exit normally."
fi

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
	echo "Could not confirm the graphics backend: no latest.log from this $fixture_label launch was found." >&2
	exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
	echo "Vitrail $fixture_label smoke did not prove that Metal was active." >&2
	exit 1
fi
echo "Confirmed Metal backend for this $fixture_label smoke run."

if ! grep -qF "Drawing the ${pass_name} particles pass with ${program} of ${fixture_name} at render stage PARTICLES" "$latest_log"; then
	echo "Vitrail $fixture_label smoke did not record the required $pass_name route through $program at PARTICLES." >&2
	exit 1
fi
if ! grep -qF "The ${pass_name} pass records its first draw with ${program}, reading minecraft:textures/atlas/particles.png" "$latest_log"; then
	echo "Vitrail $fixture_label smoke did not prove a real minecraft:textures/atlas/particles.png sample." >&2
	exit 1
fi
if ! grep -qF "Its draw buffers all reach the pack's own targets, nought included: [colortex1 MAIN]" "$latest_log"; then
	echo "Vitrail $fixture_label smoke did not prove the isolated [colortex1 MAIN] target." >&2
	exit 1
fi
if [[ "$mode" == opaque ]] && ! grep -qF 'It also writes the coverage mask' "$latest_log"; then
	echo "Vitrail Particles opaque smoke did not prove the pre-deferred coverage path." >&2
	exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
	echo "Vitrail $fixture_label smoke did not reach a clean client shutdown (Stopping!)." >&2
	exit 1
fi

newest_screenshot=""
screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
	while IFS= read -r -d '' candidate; do
		if [[ "$candidate" -nt "$fixture_marker" && ( -z "$newest_screenshot" || "$candidate" -nt "$newest_screenshot" ) ]]; then
			newest_screenshot="$candidate"
		fi
	done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
fi
if [[ -z "$newest_screenshot" ]]; then
	echo "This particle gate requires pixel evidence; rerun with --${mode} and press F2 while the required particle burst is visible." >&2
	exit 1
fi

echo "Verifying $fixture_label smoke screenshot: $newest_screenshot"
java "$fixture_verifier" "$newest_screenshot"
