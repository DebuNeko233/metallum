#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
verify_existing=false
usage() { echo "Usage: $0 [--verify-existing] [/path/to/Vitrail-Shaders-Metal]" >&2; }
if [[ ${1:-} == "--verify-existing" ]]; then verify_existing=true; shift; fi
if [[ $# -gt 1 ]]; then usage; exit 2; fi
if [[ $# -eq 1 ]]; then vitrail_root="$1"; fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "Vitrail Wide Resources smoke requires Apple-Silicon macOS." >&2; exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="wide-resources-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyWideResourcesScreenshot.java"
marker=""
[[ -f "$verifier" ]] || { echo "Wide-resource screenshot verifier is missing: $verifier" >&2; exit 2; }
[[ -f "$source_dir/shaders/white.png" ]] || { echo "Wide-resource fixture image is missing: $source_dir/shaders/white.png" >&2; exit 2; }

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    target_dir="$repo_root/run/shaderpacks/$fixture"
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail fixture at: $target_dir"

    marker="$repo_root/run/.vitrail-wide-resources-smoke-start"
    touch "$marker"
    cat <<'EOF'
Run the complete PHASE 14 Wide Resources hardware acceptance in ONE client session:

  1. Select 'wide-resources-contract' and enter an Overworld.
  2. Expected output: overwhelmingly GREEN.
     MAGENTA means at least one of the seventeen active custom samplers was missing,
     stale, aliased to the wrong descriptor, or otherwise read incorrectly.
  3. Once GREEN is stable, press F2 once.
  4. Exit normally.

The raw log must independently prove Metallum selected its generic Metal Argument Buffer path
with sampledImages=17. A GREEN screenshot without that log line does not close PHASE 14.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed PHASE 14 Wide Resources smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this Wide Resources launch was found." >&2; exit 1
fi

grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" \
    || { echo "Wide Resources smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for PHASE 14 Wide Resources smoke."

grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log" \
    || { echo "$fixture did not draw in the Overworld." >&2; exit 1; }
grep -qF "final writes the game's own target" "$latest_log" \
    || { echo "Wide-resource Final was not recorded writing the game's own target." >&2; exit 1; }
grep -qF 'Wide resource pipeline' "$latest_log" \
    || { echo "Metallum did not report the wide-resource Argument Buffer path." >&2; exit 1; }
grep -qE 'Wide resource pipeline .* uses Metal Argument Buffers: resources=[0-9]+, sampledImages=17([,}]|$)' "$latest_log" \
    || { echo "Metallum did not prove exactly seventeen active sampled images on the wide path." >&2; exit 1; }
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then
    echo "Vitrail reported a chain failure during PHASE 14 Wide Resources smoke." >&2; exit 1
fi
grep -qF 'Stopping!' "$latest_log" \
    || { echo "Wide Resources smoke did not reach clean Stopping!." >&2; exit 1; }

screenshots=()
screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    if [[ "$verify_existing" == true ]]; then
        while IFS= read -r logged_name; do
            [[ -n "$logged_name" ]] || continue
            candidate="$screenshot_dir/$logged_name"
            [[ -f "$candidate" ]] && screenshots+=("$candidate")
        done < <(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.png' "$latest_log" | sort -u)
    else
        while IFS= read -r -d '' candidate; do
            [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate")
        done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
[[ ${#screenshots[@]} -ge 1 ]] || { echo "PHASE 14 Wide Resources smoke requires one fresh F2 screenshot." >&2; exit 1; }

wide_shot=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-wide.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then
        wide_shot="$candidate"
        cat "$output"
        rm -f "$output"
        break
    fi
    rm -f "$output"
done
[[ -n "$wide_shot" ]] || { echo "No fresh screenshot passed the PHASE 14 wide-resource verifier." >&2; exit 1; }

echo "PHASE 14 >16 active samplers: PASS screenshot=$wide_shot"
echo "PHASE 14 Metal Argument Buffer execution: PASS sampledImages=17"
echo "Batched PHASE 14 Wide Resources: PASS screenshot=$wide_shot"
echo "After raw-log review this closes PHASE 14 only; PHASE 15 Compute / Storage remains separate."
