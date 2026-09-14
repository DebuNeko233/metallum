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
	echo "Vitrail Metal cloud smoke runs require Apple-Silicon macOS." >&2
	exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
	echo "Vitrail checkout not found at: $vitrail_root" >&2
	exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture_name="clouds-contract"
fixture_label="Clouds"
fixture_verifier="$vitrail_root/tests/VerifyCloudScreenshot.java"
fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
fixture_target="$repo_root/run/shaderpacks/$fixture_name"

if [[ ! -d "$fixture_source/shaders" || ! -f "$fixture_verifier" ]]; then
	echo "Vitrail $fixture_label smoke contract is missing from: $vitrail_root" >&2
	exit 2
fi

mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
rm -rf "$fixture_target"
cp -R "$fixture_source" "$fixture_target"
fixture_marker="$repo_root/run/.vitrail-cloud-smoke-start"
touch "$fixture_marker"

echo "Installed Vitrail Clouds smoke fixture at: $fixture_target"
echo "Select 'clouds-contract' in Vitrail's shader-pack UI; this launcher does not change pack selection."
echo "Keep Minecraft Clouds enabled (Fancy or Fast are both valid) and enter an overworld view where the cloud layer is clearly visible."
echo "The cloud draw has no vertex buffer and samples no texture at draw time: CloudInfo + CloudFaces + gl_VertexID generate the geometry. Stable green clouds prove that buffer-driven ABI, gbuffers_clouds @ CLOUDS routing, post-deferred target ownership and Metal texel-buffer binding all worked."
echo "Press F2 while a broad green cloud region is visible, then exit normally. Weather or sky pixels do not count for this checkpoint."

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
	echo "Could not confirm the graphics backend: no latest.log from this Clouds launch was found." >&2
	exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
	echo "Vitrail Clouds smoke did not prove that Metal was active." >&2
	exit 1
fi
echo "Confirmed Metal backend for this Clouds smoke run."

if ! grep -qE 'Drawing the (fancy|flat) cloud pass with gbuffers_clouds of clouds-contract at render stage CLOUDS, [0-9]+ uniforms and 0 samplers' "$latest_log"; then
	echo "Vitrail Clouds smoke did not record fancy/flat through gbuffers_clouds at CLOUDS with the sampler-free cloud contract. Ensure Clouds are Fancy or Fast, not Off." >&2
	exit 1
fi
if ! grep -qE 'The (fancy|flat) pass records its first draw with gbuffers_clouds$' "$latest_log"; then
	echo "Vitrail Clouds smoke did not record a real cloud draw through the buffer-driven program." >&2
	exit 1
fi
if ! grep -qF "Its draw buffers all reach the pack's own targets, nought included: [colortex1 MAIN]" "$latest_log"; then
	echo "Vitrail Clouds smoke did not prove the isolated [colortex1 MAIN] target." >&2
	exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
	echo "Vitrail Clouds smoke did not reach a clean client shutdown (Stopping!)." >&2
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
	echo "This cloud gate requires pixel evidence; rerun and press F2 while a broad cloud region is visible." >&2
	exit 1
fi

echo "Verifying Clouds smoke screenshot: $newest_screenshot"
java "$fixture_verifier" "$newest_screenshot"
