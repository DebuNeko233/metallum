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
    echo "Vitrail Metal final depth smoke runs require Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
verifier="$vitrail_root/tests/VerifyDepthFinalScreenshot.java"
fixtures=(pre-hand-contract depth-conversion-contract)

if [[ ! -f "$verifier" ]]; then
    echo "Vitrail final depth screenshot verifier is missing from: $vitrail_root" >&2
    exit 2
fi

mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
for fixture in "${fixtures[@]}"; do
    source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
    target_dir="$repo_root/run/shaderpacks/$fixture"
    if [[ ! -d "$source_dir/shaders" ]]; then
        echo "Vitrail final depth fixture is missing: $source_dir" >&2
        exit 2
    fi
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail final depth fixture at: $target_dir"
done

marker="$repo_root/run/.vitrail-depth-final-smoke-start"
touch "$marker"

cat <<'EOF'
Run the last two PHASE 8 checkpoints in ONE Overworld client session.
Use first person and hold an ordinary opaque/non-translucent item or block prominently. Keep open sky/background plus nearby terrain in view. Do not use glass or another translucent held block.

  1. Select 'pre-hand-contract'. Wait for compilation to settle. The held hand/item should create a GREEN region while the rest of the scene is mostly CYAN. Broad MAGENTA is failure. Press F2.
  2. Select 'depth-conversion-contract'. Keep the same opaque held item and view. The forced near-plane hand/item should be GREEN, untouched far-plane sky/background should be WHITE, and ordinary mid-depth world surfaces may be BLUE. Broad MAGENTA is failure. Press F2.
  3. Exit normally.

Screenshot order does not matter; the launcher classifies fresh screenshots by independent signatures.
The pre-hand gate requires Vitrail itself to draw the solid hand. The conversion gate proves both affine endpoints of the reversed-Z to pack-depth conversion on the real GPU; neither gate is inferred from the other.
EOF

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this final depth launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail final depth smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this final depth smoke run."

for fixture in "${fixtures[@]}"; do
    if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then
        echo "Final depth smoke did not record $fixture drawing in the Overworld." >&2
        exit 1
    fi
    if ! grep -qE "Drawing the hand_[^ ]* entity pass with gbuffers_hand of $fixture at render stage HAND_SOLID" "$latest_log"; then
        echo "$fixture did not record a Vitrail-owned solid hand draw through gbuffers_hand at HAND_SOLID." >&2
        exit 1
    fi
done

if ! grep -qF "The depth before the hand is converted into the pack's window in one more image" "$latest_log"; then
    echo "pre-hand checkpoint did not allocate/fill the dedicated pre-hand depth window." >&2
    exit 1
fi
if ! grep -qE "2 samplers this chain read the world's depth: \[(depthtex1, depthtex2|depthtex2, depthtex1)\]" "$latest_log"; then
    echo "pre-hand checkpoint did not record both depthtex1 and depthtex2 in one chain." >&2
    exit 1
fi
if ! grep -qF "1 samplers this chain read the world's depth: [depthtex1]" "$latest_log"; then
    echo "depth-conversion checkpoint did not record depthtex1 as its world-depth sampler." >&2
    exit 1
fi
if ! grep -qF "The world's depth is converted into the pack's window in two images" "$latest_log"; then
    echo "Final depth smoke did not allocate the converted R32F world-depth pair." >&2
    exit 1
fi
if ! grep -qF "Vitrail depth window" "$latest_log"; then
    echo "Final depth smoke did not record the depth-window conversion pass." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail final depth smoke did not reach a clean client shutdown (Stopping!)." >&2
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
if [[ ${#screenshots[@]} -lt 2 ]]; then
    echo "This final batch requires at least two fresh F2 screenshots, one independently passing each checkpoint." >&2
    exit 1
fi

pre_hand_shot=""
conversion_shot=""

match_mode() {
    local mode="$1"
    local label="$2"
    local output
    local candidate

    for candidate in "${screenshots[@]}"; do
        if [[ "$candidate" == "$pre_hand_shot" || "$candidate" == "$conversion_shot" ]]; then
            continue
        fi
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-depth-final.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"
            cat "$output"
            rm -f "$output"
            case "$mode" in
                --pre-hand) pre_hand_shot="$candidate" ;;
                --conversion) conversion_shot="$candidate" ;;
            esac
            return 0
        fi
        rm -f "$output"
    done

    echo "No fresh screenshot independently passed the $label verifier." >&2
    return 1
}

match_mode --pre-hand pre-hand
match_mode --conversion depth-conversion

echo "PHASE 8 final depth smoke: PASS pre-hand=$pre_hand_shot conversion=$conversion_shot"
echo "When both independent verdicts are accepted, PHASE 8 depth is complete."
