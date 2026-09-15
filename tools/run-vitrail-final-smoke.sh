#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
verify_existing=false
usage() { echo "Usage: $0 [--verify-existing] [/path/to/Vitrail-Shaders-Metal]" >&2; }
if [[ ${1:-} == "--verify-existing" ]]; then verify_existing=true; shift; fi
if [[ $# -gt 1 ]]; then usage; exit 2; fi
if [[ $# -eq 1 ]]; then vitrail_root="$1"; fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then echo "Vitrail Final smoke requires Apple-Silicon macOS." >&2; exit 2; fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2; fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixtures=(final-direct-contract final-chain-contract)
verifier="$vitrail_root/tests/VerifyFinalScreenshot.java"
marker=""
[[ -f "$verifier" ]] || { echo "Final screenshot verifier is missing: $verifier" >&2; exit 2; }

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    for fixture in "${fixtures[@]}"; do
        source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
        target_dir="$repo_root/run/shaderpacks/$fixture"
        [[ -d "$source_dir/shaders" ]] || { echo "Missing fixture: $source_dir" >&2; exit 2; }
        rm -rf "$target_dir"; cp -R "$source_dir" "$target_dir"
        echo "Installed Vitrail fixture at: $target_dir"
    done
    marker="$repo_root/run/.vitrail-final-smoke-start"; touch "$marker"
    cat <<'EOF'
Run BOTH PHASE 12 Final checkpoints in ONE client / ONE Overworld session:

  1. Select 'final-direct-contract' and enter an Overworld.
     Expected: overwhelmingly GREEN. This pack contains only final.
     Press F2 once.
  2. Without leaving the world, switch to 'final-chain-contract'.
     Expected: LEFT half BLUE, RIGHT half YELLOW. MAGENTA means final sampled stale/clear/wrong-half data.
     Press F2 once.
  3. Exit normally.

Screenshot order is irrelevant: the launcher classifies both fresh screenshots independently.
The two verdicts together close PHASE 12 only after raw-log review.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed batched PHASE 12 Final smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then echo "No latest.log from this Final launch was found." >&2; exit 1; fi
grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" || { echo "Final smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for this batched PHASE 12 Final smoke run."

for fixture in "${fixtures[@]}"; do
    grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log" || { echo "$fixture did not draw in the Overworld." >&2; exit 1; }
done

# Direct Final: there are no prior fullscreen pack passes; final alone paints the game's target.
grep -qF 'Drawing final-direct-contract from the root for minecraft:overworld' "$latest_log" || { echo "Final direct fixture did not run." >&2; exit 1; }
grep -qF '0 full screen passes before the final' "$latest_log" || { echo "Final direct fixture was not final-only." >&2; exit 1; }

# Chain -> Final: the latest colortex0 half must be sampled by final and presented from the game's target.
grep -qF 'Drawing final-chain-contract from the root for minecraft:overworld' "$latest_log" || { echo "Final chain fixture did not run." >&2; exit 1; }
grep -qF 'composite writes colortex0 alt' "$latest_log" || { echo "Final chain fixture did not write colortex0 ALT." >&2; exit 1; }
grep -qF "final writes the game's own target" "$latest_log" || { echo "No pack final was recorded writing the game's own target." >&2; exit 1; }
grep -qF '1 targets doubled: [0]' "$latest_log" || { echo "Final chain fixture did not allocate colortex0 ping-pong." >&2; exit 1; }
grep -qF '1 samplers this chain read a real colour target: [colortex0]' "$latest_log" || { echo "Final chain fixture did not prove colortex0 sampling." >&2; exit 1; }

direct_split='0 of this chain run before the world [], 0 more before its translucents [], 1 after'
chain_split='0 of this chain run before the world [], 0 more before its translucents [], 2 after'
grep -qF "$direct_split" "$latest_log" || { echo "Final direct fixture was not placed after the world." >&2; exit 1; }
grep -qF "$chain_split" "$latest_log" || { echo "Final chain fixture was not placed after the world." >&2; exit 1; }
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then echo "Vitrail reported a chain failure during PHASE 12 Final smoke." >&2; exit 1; fi
grep -qF 'Stopping!' "$latest_log" || { echo "Final smoke did not reach clean Stopping!." >&2; exit 1; }

screenshots=(); screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    if [[ "$verify_existing" == true ]]; then
        while IFS= read -r logged_name; do [[ -n "$logged_name" ]] || continue; candidate="$screenshot_dir/$logged_name"; [[ -f "$candidate" ]] && screenshots+=("$candidate"); done < <(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.png' "$latest_log" | sort -u)
    else
        while IFS= read -r -d '' candidate; do [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate"); done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
[[ ${#screenshots[@]} -ge 2 ]] || { echo "Batched PHASE 12 Final smoke requires two fresh F2 screenshots." >&2; exit 1; }

direct_shot=""; chain_shot=""
match_mode() {
    local mode="$1" label="$2" output candidate
    for candidate in "${screenshots[@]}"; do
        [[ "$candidate" == "$direct_shot" || "$candidate" == "$chain_shot" ]] && continue
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-final.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"; cat "$output"; rm -f "$output"
            if [[ "$mode" == "--direct" ]]; then direct_shot="$candidate"; else chain_shot="$candidate"; fi
            return 0
        fi
        rm -f "$output"
    done
    echo "No fresh screenshot independently passed the $label verifier." >&2; return 1
}
match_mode --direct 'Final direct-to-main-target'
match_mode --chain 'Final chain-to-main-target'

echo "PHASE 12 final direct: PASS screenshot=$direct_shot"
echo "PHASE 12 final chain-to-screen: PASS screenshot=$chain_shot"
echo "Batched PHASE 12 Final: PASS direct=$direct_shot chain=$chain_shot"
echo "After raw-log review these independent verdicts close PHASE 12 only; PHASE 13 Dimension Routing remains separate."
