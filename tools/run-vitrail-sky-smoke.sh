#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
mode=""
path_seen=false

usage() {
	echo "Usage: $0 <--overworld|--end> [/path/to/Vitrail-Shaders-Metal]" >&2
}

for argument in "$@"; do
	case "$argument" in
		--overworld|--end)
			if [[ -n "$mode" ]]; then usage; exit 2; fi
			mode="$argument"
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
	echo "Vitrail Metal sky smoke runs require Apple-Silicon macOS." >&2
	exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
	echo "Vitrail checkout not found at: $vitrail_root" >&2
	exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture_name="sky-contract"
fixture_verifier="$vitrail_root/tests/VerifySkyScreenshot.java"
fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
fixture_target="$repo_root/run/shaderpacks/$fixture_name"

if [[ ! -d "$fixture_source/shaders" || ! -f "$fixture_verifier" ]]; then
	echo "Vitrail Sky smoke contract is missing from: $vitrail_root" >&2
	exit 2
fi

mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
rm -rf "$fixture_target"
cp -R "$fixture_source" "$fixture_target"
mode_name="${mode#--}"
fixture_marker="$repo_root/run/.vitrail-sky-${mode_name}-smoke-start"
touch "$fixture_marker"

echo "Installed Vitrail Sky smoke fixture at: $fixture_target"
echo "Select 'sky-contract' in Vitrail's shader-pack UI; this launcher does not change pack selection."
if [[ "$mode" == "--overworld" ]]; then
	echo "OVERWORLD gate: enter the Overworld with a clear horizon, run /weather clear and /time set 12000, and wait until the cyan sky disc, yellow sunrise/sunset fan and green celestial quad are all visible."
	echo "This proves POSITION (disc), POSITION_COLOR (sunrise/sunset), POSITION_TEX (sun/moon), pre-deferred coverage and Metal triangle-fan execution."
else
	echo "END gate: enter minecraft:the_end and look into open sky. The broad End cube should be green."
	echo "This independently proves POSITION_TEX_COLOR, the real end_sky.png sample, CUSTOM_SKY routing and pre-deferred coverage."
fi
echo "Press F2 only after the requested swatches are clearly visible, then exit normally. Clouds/weather do not count for this checkpoint."

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
	echo "Could not confirm the graphics backend: no latest.log from this Sky launch was found." >&2
	exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
	echo "Vitrail Sky smoke did not prove that Metal was active." >&2
	exit 1
fi
echo "Confirmed Metal backend for this Sky smoke run."

if ! grep -qF "Its draw buffers all reach the pack's own targets, nought included: [colortex1 MAIN]" "$latest_log"; then
	echo "Vitrail Sky smoke did not prove the isolated [colortex1 MAIN] target." >&2
	exit 1
fi
if ! grep -qF "It also writes the coverage mask, so nothing paints the game's own picture back over what this pass wrote" "$latest_log"; then
	echo "Vitrail Sky smoke did not prove the pre-deferred sky coverage path." >&2
	exit 1
fi

if [[ "$mode" == "--overworld" ]]; then
	if ! grep -qE 'Drawing the disc sky pass with gbuffers_skybasic of sky-contract at render stage SKY' "$latest_log"; then
		echo "Sky Overworld smoke did not record the POSITION sky disc through gbuffers_skybasic @ SKY." >&2
		exit 1
	fi
	if ! grep -qF 'The disc pass records its first draw with gbuffers_skybasic' "$latest_log"; then
		echo "Sky Overworld smoke did not record a real sky-disc draw." >&2
		exit 1
	fi
	if ! grep -qE 'Drawing the sunrise sky pass with gbuffers_skybasic of sky-contract at render stage SUNSET' "$latest_log"; then
		echo "Sky Overworld smoke did not record the POSITION_COLOR sunrise/sunset fan. Rerun near sunset; /time set 12000 is the intended trigger." >&2
		exit 1
	fi
	if ! grep -qF 'The sunrise pass records its first draw with gbuffers_skybasic' "$latest_log"; then
		echo "Sky Overworld smoke did not record a real sunrise/sunset draw." >&2
		exit 1
	fi
	if ! grep -qE 'Drawing the (sun|moon) sky pass with gbuffers_skytextured of sky-contract at render stage (SUN|MOON)' "$latest_log"; then
		echo "Sky Overworld smoke did not record a POSITION_TEX celestial draw through gbuffers_skytextured." >&2
		exit 1
	fi
	if ! grep -qE 'The (sun|moon) pass records its first draw with gbuffers_skytextured, reading minecraft:textures/atlas/celestials\.png' "$latest_log"; then
		echo "Sky Overworld smoke did not prove a real celestial-atlas sample." >&2
		exit 1
	fi
else
	if ! grep -qE 'Drawing the endsky sky pass with gbuffers_skytextured of sky-contract at render stage CUSTOM_SKY' "$latest_log"; then
		echo "Sky End smoke did not record the POSITION_TEX_COLOR End cube through gbuffers_skytextured @ CUSTOM_SKY." >&2
		exit 1
	fi
	if ! grep -qE 'The endsky pass records its first draw with gbuffers_skytextured, reading minecraft:textures/environment/end_sky\.png' "$latest_log"; then
		echo "Sky End smoke did not prove a real minecraft:textures/environment/end_sky.png sample." >&2
		exit 1
	fi
fi

if ! grep -qF 'Stopping!' "$latest_log"; then
	echo "Vitrail Sky smoke did not reach a clean client shutdown (Stopping!)." >&2
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
	echo "This sky gate requires pixel evidence; rerun and press F2 after the requested sky swatches are visible." >&2
	exit 1
fi

echo "Verifying Sky smoke screenshot ($mode_name): $newest_screenshot"
java "$fixture_verifier" "$mode" "$newest_screenshot"
