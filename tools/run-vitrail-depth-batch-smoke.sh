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
    echo "Vitrail Metal depth batch smoke runs require Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
verifier="$vitrail_root/tests/VerifyDepthBatchScreenshot.java"
fixtures=(depthtex1-contract depthtex2-contract pre-translucent-contract)

if [[ ! -f "$verifier" ]]; then
    echo "Vitrail batched depth screenshot verifier is missing from: $vitrail_root" >&2
    exit 2
fi

mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
for fixture in "${fixtures[@]}"; do
    source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
    target_dir="$repo_root/run/shaderpacks/$fixture"
    if [[ ! -d "$source_dir/shaders" ]]; then
        echo "Vitrail depth fixture is missing: $source_dir" >&2
        exit 2
    fi
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail depth fixture at: $target_dir"
done

marker="$repo_root/run/.vitrail-depth-batch-smoke-start"
touch "$marker"

cat <<'EOF'
Run all three checkpoints in ONE Overworld client session, keeping roughly the same view with open sky/background and nearby solid terrain:

  1. Select 'depthtex1-contract'. Wait for compilation to settle. Expect BLUE constant-depth regions plus YELLOW live-depth variation, then press F2.
  2. Select 'depthtex2-contract'. Wait for compilation to settle. Expect RED constant-depth regions plus CYAN live-depth variation, then press F2.
  3. Select 'pre-translucent-contract'. Wait for compilation to settle. Expect GREEN constant-depth regions plus WHITE live-depth variation, then press F2.
  4. Exit normally.

Broad MAGENTA is failure in every checkpoint. Screenshot order does not matter: the launcher classifies fresh screenshots by their independent colour signatures.

This batch closes only depthtex1, depthtex2 and pre-translucent when all three independent verdicts pass. The later pre-hand semantic difference and exact depth conversion remain separate gates.
EOF

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this depth batch launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail depth batch smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this batched depth smoke run."

for fixture in "${fixtures[@]}"; do
    if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then
        echo "Depth batch smoke did not record $fixture drawing in the Overworld." >&2
        exit 1
    fi
done

if ! grep -qF "1 samplers this chain read the world's depth: [depthtex1]" "$latest_log"; then
    echo "depthtex1 checkpoint did not record depthtex1 as the world-depth sampler." >&2
    exit 1
fi
if ! grep -qF "1 samplers this chain read the world's depth: [depthtex2]" "$latest_log"; then
    echo "depthtex2 checkpoint did not record depthtex2 as the world-depth sampler." >&2
    exit 1
fi
if ! grep -qF "0 of this chain run before the world [], 1 more before its translucents [deferred], 1 after" "$latest_log"; then
    echo "pre-translucent checkpoint did not record deferred in the before-translucents cut." >&2
    exit 1
fi
if ! grep -qF "The world's depth is converted into the pack's window in two images" "$latest_log"; then
    echo "Depth batch smoke did not allocate the converted R32F world-depth pair." >&2
    exit 1
fi
if ! grep -qF "Vitrail depth window" "$latest_log"; then
    echo "Depth batch smoke did not record the depth-window conversion pass." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail depth batch smoke did not reach a clean client shutdown (Stopping!)." >&2
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
    echo "This batch requires at least three fresh F2 screenshots, one independently passing each checkpoint." >&2
    exit 1
fi

depthtex1_shot=""
depthtex2_shot=""
pre_translucent_shot=""

match_mode() {
    local mode="$1"
    local label="$2"
    local output
    local candidate

    for candidate in "${screenshots[@]}"; do
        if [[ "$candidate" == "$depthtex1_shot" || "$candidate" == "$depthtex2_shot" || "$candidate" == "$pre_translucent_shot" ]]; then
            continue
        fi
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-depth-batch.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"
            cat "$output"
            rm -f "$output"
            case "$mode" in
                --depthtex1) depthtex1_shot="$candidate" ;;
                --depthtex2) depthtex2_shot="$candidate" ;;
                --pre-translucent) pre_translucent_shot="$candidate" ;;
            esac
            return 0
        fi
        rm -f "$output"
    done

    echo "No fresh screenshot independently passed the $label verifier." >&2
    return 1
}

match_mode --depthtex1 depthtex1
match_mode --depthtex2 depthtex2
match_mode --pre-translucent pre-translucent

echo "Batched PHASE 8 depth smoke: PASS depthtex1=$depthtex1_shot depthtex2=$depthtex2_shot pre-translucent=$pre_translucent_shot"
echo "pre-hand and exact depth conversion remain pending."
