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
    echo "Vitrail Metal shadow batch smoke requires Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
verifier="$vitrail_root/tests/VerifyShadowBatchScreenshot.java"
fixtures=(shadow-entities-contract shadow-depth-contract shadow-color-contract)

if [[ ! -f "$verifier" ]]; then
    echo "Vitrail shadow batch screenshot verifier is missing: $verifier" >&2
    exit 2
fi

mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
for fixture in "${fixtures[@]}"; do
    source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
    target_dir="$repo_root/run/shaderpacks/$fixture"
    if [[ ! -d "$source_dir/shaders" ]]; then
        echo "Vitrail shadow batch fixture is missing: $source_dir" >&2
        exit 2
    fi
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail shadow batch fixture at: $target_dir"
done

marker="$repo_root/run/.vitrail-shadow-batch-smoke-start"
touch "$marker"

cat <<'EOF'
Run THREE independent PHASE 9 checkpoints in ONE Overworld client session. Every screen below is a RAW LIGHT-SPACE shadow-map diagnostic; its colored texels do not line up with the objects in front of the camera.

  1. Select 'shadow-entities-contract'. Keep several ordinary mobs (cows/sheep/zombies, etc.) inside the nearby shadow-map area. Wait for the shadow stage to settle. The raw map should contain GREEN entity regions and BLUE terrain regions; broad MAGENTA is failure. Press F2.
  2. Select 'shadow-depth-contract'. Use a daylight scene whose nearby light-space walk contains ordinary terrain plus a visible body of water. The raw depth diagnostic should contain CYAN where shadowtex0/shadowtex1 agree and WHITE where translucent shadow geometry changed the completed depth after the pre-translucent copy. Broad MAGENTA is failure. Press F2.
  3. Select 'shadow-color-contract'. Any ordinary terrain in the shadow map is enough. The raw map should contain YELLOW where shadowcolor0/1 were written as an independent red+green pair and RED where both buffers retained their black clear. Broad MAGENTA is failure. Press F2.
  4. Exit normally.

Screenshot order does not matter; the launcher classifies fresh screenshots by independent color signatures.
This batch closes only shadow entities, shadow depth and shadow color. Shadow mipmaps remain a separate checkpoint because Metal D32_FLOAT mip generation needs an explicit backend path rather than the native color mipmap command.
EOF

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this shadow batch launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail shadow batch smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this shadow batch smoke run."

for fixture in "${fixtures[@]}"; do
    if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then
        echo "Shadow batch did not record $fixture drawing in the Overworld." >&2
        exit 1
    fi
done
if ! grep -qF 'Shadow map allocated at ' "$latest_log"; then
    echo "Shadow batch did not allocate the pack shadow map." >&2
    exit 1
fi

# Entity checkpoint: a real Vitrail shadow-entity row must be selected and draw a real entity texture.
if ! grep -qE 'Drawing the shadow_[^ ]+ entities in the shadow map pass with shadow_entities of shadow-entities-contract at render stage ENTITIES' "$latest_log"; then
    echo "shadow-entities checkpoint did not record a direct shadow_entities feature draw." >&2
    exit 1
fi
if ! grep -qE 'The shadow_[^ ]+ pass records its first draw with shadow_entities, reading minecraft:' "$latest_log"; then
    echo "shadow-entities checkpoint did not prove a real entity texture sample." >&2
    exit 1
fi
if ! grep -qE "On this frame the light's walk submitted [1-9][0-9]* entities" "$latest_log"; then
    echo "shadow-entities checkpoint did not submit a real entity into the light-space walk." >&2
    exit 1
fi

# Depth checkpoint: both completed and pre-translucent depth names must be live in one chain,
# and the translucent chunk route must really draw after the copy point.
if ! grep -qE "2 samplers this chain read the shadow map: \[(shadowtex0, shadowtex1|shadowtex1, shadowtex0)\]" "$latest_log"; then
    echo "shadow-depth checkpoint did not record shadowtex0 and shadowtex1 together." >&2
    exit 1
fi
if ! grep -qF 'Drawing the shadow_translucent chunk pass with shadow of shadow-depth-contract at render stage TERRAIN_TRANSLUCENT' "$latest_log"; then
    echo "shadow-depth checkpoint did not record the translucent chunk shadow route through generic shadow." >&2
    exit 1
fi
if ! grep -qF 'The shadow_translucent pass records its first draw with shadow, reading minecraft:textures/atlas/blocks.png' "$latest_log"; then
    echo "shadow-depth checkpoint did not prove a real translucent block-atlas draw." >&2
    exit 1
fi

# Color checkpoint: both independent shadow color attachments must be sampled together afterwards.
if ! grep -qE "2 samplers this chain read the shadow map: \[(shadowcolor0, shadowcolor1|shadowcolor1, shadowcolor0)\]" "$latest_log"; then
    echo "shadow-color checkpoint did not record shadowcolor0 and shadowcolor1 together." >&2
    exit 1
fi
if ! grep -qF 'Drawing the shadow_solid chunk pass with shadow of shadow-color-contract at render stage TERRAIN_SOLID' "$latest_log"; then
    echo "shadow-color checkpoint did not record a real generic shadow terrain draw." >&2
    exit 1
fi

if grep -qF 'Vitrail stopped drawing the shadow map after an error' "$latest_log"; then
    echo "Vitrail reported a shadow-stage failure during the shadow batch." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail shadow batch smoke did not reach a clean client shutdown (Stopping!)." >&2
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
if [[ ${#screenshots[@]} -lt 3 ]]; then
    echo "Shadow batch requires at least three fresh F2 screenshots, one independently passing each checkpoint." >&2
    exit 1
fi

entities_shot=""
depth_shot=""
color_shot=""

match_mode() {
    local mode="$1"
    local label="$2"
    local output
    local candidate

    for candidate in "${screenshots[@]}"; do
        if [[ "$candidate" == "$entities_shot" || "$candidate" == "$depth_shot" || "$candidate" == "$color_shot" ]]; then
            continue
        fi
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-shadow-batch.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"
            cat "$output"
            rm -f "$output"
            case "$mode" in
                --entities) entities_shot="$candidate" ;;
                --depth) depth_shot="$candidate" ;;
                --color) color_shot="$candidate" ;;
            esac
            return 0
        fi
        rm -f "$output"
    done

    echo "No fresh screenshot independently passed the $label verifier." >&2
    return 1
}

match_mode --entities shadow-entities
match_mode --depth shadow-depth
match_mode --color shadow-color

echo "PHASE 9 shadow batch: PASS entities=$entities_shot depth=$depth_shot color=$color_shot"
echo "shadow mipmaps remain pending as the final PHASE 9 checkpoint."
