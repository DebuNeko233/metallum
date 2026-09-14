#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"

usage() {
    echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal]" >&2
}

if [[ $# -gt 1 ]]; then
    usage
    exit 2
fi
if [[ $# -eq 1 ]]; then
    vitrail_root="$1"
fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "Vitrail Metal depthtex0 smoke runs require Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture_name="depthtex0-contract"
fixture_verifier="$vitrail_root/tests/VerifyDepthtex0Screenshot.java"
fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
fixture_target="$repo_root/run/shaderpacks/$fixture_name"

if [[ ! -d "$fixture_source/shaders" || ! -f "$fixture_verifier" ]]; then
    echo "Vitrail depthtex0 smoke contract is missing from: $vitrail_root" >&2
    exit 2
fi

mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
rm -rf "$fixture_target"
cp -R "$fixture_source" "$fixture_target"
fixture_marker="$repo_root/run/.vitrail-depthtex0-smoke-start"
touch "$fixture_marker"

echo "Installed Vitrail depthtex0 smoke fixture at: $fixture_target"
echo "Select 'depthtex0-contract' in Vitrail's shader-pack UI before entering the test world."
echo "Enter the Overworld and face a scene containing BOTH open sky/background and nearby solid terrain (a hillside, trees or ground across the lower half works well)."
echo "The diagnostic should show cyan constant-depth regions and green live-depth variation. Broad magenta is failure."
echo "Press F2 only after both cyan and green are clearly visible, then exit normally."
echo "This checkpoint proves composite-side depthtex0 scene-depth sampling only; depthtex1/depthtex2, pre-translucent, pre-hand and exact depth conversion remain separate gates."

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this depthtex0 launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail depthtex0 smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this depthtex0 smoke run."

if ! grep -qF 'Drawing depthtex0-contract from the root for minecraft:overworld' "$latest_log"; then
    echo "depthtex0 smoke did not record the dedicated fixture chain in the Overworld." >&2
    exit 1
fi
if ! grep -qF "The world's depth is converted into the pack's window in two images" "$latest_log"; then
    echo "depthtex0 smoke did not allocate the converted R32F world-depth pair." >&2
    exit 1
fi
if ! grep -qE "The scene's depth is kept (after the world|before the game clears it)" "$latest_log"; then
    echo "depthtex0 smoke did not record a whole-scene depth capture for the post-world chain." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail depthtex0 smoke did not reach a clean client shutdown (Stopping!)." >&2
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
    echo "This depthtex0 gate requires pixel evidence; rerun and press F2 after both cyan and green regions are visible." >&2
    exit 1
fi

echo "Verifying depthtex0 smoke screenshot: $newest_screenshot"
java "$fixture_verifier" "$newest_screenshot"
