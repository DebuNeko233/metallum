#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
path_seen=false

usage() {
	echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal]" >&2
}

for argument in "$@"; do
	case "$argument" in
		-*) usage; exit 2 ;;
		*)
			if [[ "$path_seen" == true ]]; then usage; exit 2; fi
			vitrail_root="$argument"
			path_seen=true
			;;
	esac
done

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
	echo "Vitrail Metal weather smoke runs require Apple-Silicon macOS." >&2
	exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
	echo "Vitrail checkout not found at: $vitrail_root" >&2
	exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture_name="weather-contract"
fixture_label="Weather"
fixture_verifier="$vitrail_root/tests/VerifyWeatherScreenshot.java"
fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
fixture_target="$repo_root/run/shaderpacks/$fixture_name"

if [[ ! -d "$fixture_source/shaders" || ! -f "$fixture_verifier" ]]; then
	echo "Vitrail $fixture_label smoke contract is missing from: $vitrail_root" >&2
	exit 2
fi

mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
rm -rf "$fixture_target"
cp -R "$fixture_source" "$fixture_target"
fixture_marker="$repo_root/run/.vitrail-weather-smoke-start"
touch "$fixture_marker"

echo "Installed Vitrail Weather smoke fixture at: $fixture_target"
echo "Select 'weather-contract' in Vitrail's shader-pack UI; this launcher does not change pack selection."
echo "In a biome with precipitation, run /weather rain. Rain or snow is valid: both use the same gbuffers_weather @ RAIN_SNOW program and PARTICLE vertex ABI, while the game changes only the sampled weather image between the two draws."
echo "Stable green precipitation means weather routing, post-deferred target ownership, PARTICLE ABI and real weather-texture sampling passed. Press F2 while the curtain is clearly visible, then exit normally."
echo "A particle burst, cloud layer or sky element does not count for this checkpoint."

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
	echo "Could not confirm the graphics backend: no latest.log from this Weather launch was found." >&2
	exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
	echo "Vitrail Weather smoke did not prove that Metal was active." >&2
	exit 1
fi
echo "Confirmed Metal backend for this Weather smoke run."

if ! grep -qE 'Drawing the (weather|weather_depth) weather pass with gbuffers_weather of weather-contract at render stage RAIN_SNOW' "$latest_log"; then
	echo "Vitrail Weather smoke did not record weather/weather_depth through gbuffers_weather at RAIN_SNOW. Run /weather rain in a biome where rain or snow is visibly falling." >&2
	exit 1
fi
if ! grep -qE 'The (weather|weather_depth) pass records its first draw with gbuffers_weather, reading minecraft:textures/environment/(rain|snow)\.png' "$latest_log"; then
	echo "Vitrail Weather smoke did not prove a real Minecraft rain.png or snow.png sample." >&2
	exit 1
fi
if ! grep -qF "Its draw buffers all reach the pack's own targets, nought included: [colortex1 MAIN]" "$latest_log"; then
	echo "Vitrail Weather smoke did not prove the isolated [colortex1 MAIN] target." >&2
	exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
	echo "Vitrail Weather smoke did not reach a clean client shutdown (Stopping!)." >&2
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
	echo "This weather gate requires pixel evidence; rerun and press F2 while rain or snow is visibly falling." >&2
	exit 1
fi

echo "Verifying Weather smoke screenshot: $newest_screenshot"
java "$fixture_verifier" "$newest_screenshot"
