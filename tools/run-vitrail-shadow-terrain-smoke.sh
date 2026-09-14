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
    echo "Vitrail Metal shadow-terrain smoke runs require Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="shadow-terrain-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
target_dir="$repo_root/run/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyShadowTerrainScreenshot.java"

if [[ ! -d "$source_dir/shaders" ]]; then
    echo "Vitrail shadow-terrain fixture is missing: $source_dir" >&2
    exit 2
fi
if [[ ! -f "$verifier" ]]; then
    echo "Vitrail shadow-terrain screenshot verifier is missing: $verifier" >&2
    exit 2
fi

mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
rm -rf "$target_dir"
cp -R "$source_dir" "$target_dir"
echo "Installed Vitrail shadow-terrain fixture at: $target_dir"

marker="$repo_root/run/.vitrail-shadow-terrain-smoke-start"
touch "$marker"

cat <<'EOF'
Run the PHASE 9 shadow-terrain checkpoint in one Overworld session:

  1. Select 'shadow-terrain-contract'.
  2. Use a daylight scene containing all three chunk materials inside the nearby shadow-map area: substantial solid ground/stone, cutout foliage or tall grass, and visible water. A pond beside a leafy tree is ideal.
  3. Wait for pack compilation and the shadow stage to settle. The diagnostic shadow-map view must contain GREEN solid terrain, YELLOW cutout terrain and BLUE water. Broad MAGENTA means the carried chunk ABI/atlas contract failed.
  4. Press F2 once while all three colours are visible, then exit normally.

This checkpoint closes only PHASE 9 shadow terrain. shadow entities, shadow depth semantics/sampling, the full shadow-colour contract and shadow mipmaps remain independent gates even though shadowcolor0 is used here as the diagnostic carrier.
EOF

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this shadow-terrain launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail shadow-terrain smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this shadow-terrain smoke run."

if ! grep -qF 'Shadow map allocated at ' "$latest_log"; then
    echo "Shadow-terrain smoke did not allocate the pack shadow map." >&2
    exit 1
fi

for route in shadow_solid shadow_cutout shadow_water; do
    case "$route" in
        shadow_solid) stage='TERRAIN_SOLID' ;;
        shadow_cutout) stage='TERRAIN_CUTOUT' ;;
        shadow_water) stage='TERRAIN_TRANSLUCENT' ;;
    esac
    if ! grep -qF "Drawing the $route chunk pass with $route of shadow-terrain-contract at render stage $stage" "$latest_log"; then
        echo "Shadow-terrain smoke did not record $route through its dedicated chunk shadow program at $stage." >&2
        exit 1
    fi
    if ! grep -qF "The $route pass records its first draw with $route, reading minecraft:textures/atlas/blocks.png" "$latest_log"; then
        echo "Shadow-terrain smoke did not prove a real block-atlas sample for $route; keep that material visible in the light-space walk and rerun." >&2
        exit 1
    fi
done

if grep -qF 'Vitrail stopped drawing the shadow map after an error' "$latest_log"; then
    echo "Vitrail reported a shadow-stage failure during the shadow-terrain run." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail shadow-terrain smoke did not reach a clean client shutdown (Stopping!)." >&2
    exit 1
fi

screenshots=()
screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    while IFS= read -r -d '' candidate; do
        if [[ "$candidate" -nt "$marker" ]]; then
            screenshots+=("$candidate")
        fi
    done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
fi
if [[ ${#screenshots[@]} -lt 1 ]]; then
    echo "Shadow-terrain smoke requires a fresh F2 screenshot from this launch." >&2
    exit 1
fi

matched=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-shadow-terrain.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then
        echo "Matched shadow-terrain screenshot: $candidate"
        cat "$output"
        matched="$candidate"
        rm -f "$output"
        break
    fi
    rm -f "$output"
done

if [[ -z "$matched" ]]; then
    echo "No fresh screenshot independently passed the shadow-terrain green/yellow/blue verifier." >&2
    exit 1
fi

echo "PHASE 9 shadow terrain smoke: PASS screenshot=$matched"
echo "shadow entities, shadow depth, shadow color and shadow mipmaps remain pending."
