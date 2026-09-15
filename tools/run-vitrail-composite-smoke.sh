#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
verify_existing=false
usage() { echo "Usage: $0 [--verify-existing] [/path/to/Vitrail-Shaders-Metal]" >&2; }
if [[ ${1:-} == "--verify-existing" ]]; then verify_existing=true; shift; fi
if [[ $# -gt 1 ]]; then usage; exit 2; fi
if [[ $# -eq 1 ]]; then vitrail_root="$1"; fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then echo "Vitrail Composite smoke requires Apple-Silicon macOS." >&2; exit 2; fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2; fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixtures=(composite-flip-contract composite-history-contract)
verifier="$vitrail_root/tests/VerifyCompositeScreenshot.java"
marker=""
[[ -f "$verifier" ]] || { echo "Composite screenshot verifier is missing: $verifier" >&2; exit 2; }

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    for fixture in "${fixtures[@]}"; do
        source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
        target_dir="$repo_root/run/shaderpacks/$fixture"
        [[ -d "$source_dir/shaders" ]] || { echo "Missing fixture: $source_dir" >&2; exit 2; }
        rm -rf "$target_dir"; cp -R "$source_dir" "$target_dir"
        echo "Installed Vitrail fixture at: $target_dir"
    done
    marker="$repo_root/run/.vitrail-composite-smoke-start"; touch "$marker"
    cat <<'EOF'
Run BOTH PHASE 11 Composite checkpoints in ONE client / ONE Overworld session:

  1. Select 'composite-flip-contract' and enter an Overworld.
     Expected: overwhelmingly BLUE. RED/GREEN/MAGENTA means Composite order or flip parity failed.
     Press F2 once.
  2. Without leaving the world, switch to 'composite-history-contract'.
     Its first frame is intentionally RED. Wait until it becomes overwhelmingly CYAN and stays CYAN.
     CYAN is only reachable after colortex2 from the previous frame was preserved and copied ALT -> MAIN.
     MAGENTA means stale/wrong-half/broken history; persistent RED means the target was cleared every frame.
     Press F2 once while CYAN is visible.
  3. Exit normally.

Screenshot order is irrelevant: the launcher classifies both fresh screenshots independently.
The history checkpoint deliberately needs a later frame, so do not capture its initial RED frame.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed batched PHASE 11 Composite smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then echo "No latest.log from this Composite launch was found." >&2; exit 1; fi
grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" || { echo "Composite smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for this batched PHASE 11 Composite smoke run."

for fixture in "${fixtures[@]}"; do
    grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log" || { echo "$fixture did not draw in the Overworld." >&2; exit 1; }
done

# Same-frame Composite parity: MAIN -> ALT -> MAIN -> ALT through three real sampled passes.
grep -qF 'composite writes colortex0 alt' "$latest_log" || { echo "Composite flip fixture did not record composite -> ALT." >&2; exit 1; }
grep -qF 'composite1 writes colortex0 main' "$latest_log" || { echo "Composite flip fixture did not record composite1 -> MAIN." >&2; exit 1; }
grep -qF 'composite2 writes colortex0 alt' "$latest_log" || { echo "Composite flip fixture did not record composite2 -> ALT." >&2; exit 1; }
grep -qF '1 targets doubled: [0]' "$latest_log" || { echo "Composite flip fixture did not allocate colortex0 ping-pong." >&2; exit 1; }

# Previous-frame history: colortex2 is persistent, ends flipped, and must be restored to MAIN for next frame.
grep -qF 'composite writes colortex2 alt' "$latest_log" || { echo "Composite history fixture did not record temporal target ALT write." >&2; exit 1; }
grep -qF 'composite1 writes colortex2 main' "$latest_log" || { echo "Composite history fixture did not record temporal target MAIN write." >&2; exit 1; }
grep -qF 'composite2 writes colortex0 alt, colortex2 alt' "$latest_log" || { echo "Composite history fixture did not record its final temporal ALT write." >&2; exit 1; }
grep -qE '2 targets doubled: \[(0, 2|2, 0)\]' "$latest_log" || { echo "Composite history fixture did not allocate both required ping-pong targets." >&2; exit 1; }
grep -qF 'targets the pack keeps between frames: [2]' "$latest_log" || { echo "Composite history fixture did not mark colortex2 persistent." >&2; exit 1; }
grep -qF '1 targets are copied back from their far half at the end of every frame, because the pack keeps them and the chain left them there: [2]' "$latest_log" || { echo "Composite history fixture did not schedule colortex2 ALT -> MAIN copy-back." >&2; exit 1; }
grep -qF 'colortex2 is not written until composite1, later in the same frame, so composite reads the frame before, and the clear colour on the first one' "$latest_log" || { echo "Composite history fixture did not record a previous-frame history read." >&2; exit 1; }
grep -qE 'samplers this chain read a real colour target: .*colortex0.*colortex2|samplers this chain read a real colour target: .*colortex2.*colortex0' "$latest_log" || { echo "Composite history fixture did not prove its colour targets were sampled." >&2; exit 1; }

split='0 of this chain run before the world [], 0 more before its translucents [], 4 after'
if [[ $(grep -Fc "$split" "$latest_log") -lt 2 ]]; then echo "Both fixtures did not place all Composite passes after the world." >&2; exit 1; fi
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then echo "Vitrail reported a chain failure during PHASE 11 Composite smoke." >&2; exit 1; fi
grep -qF 'Stopping!' "$latest_log" || { echo "Composite smoke did not reach clean Stopping!." >&2; exit 1; }

screenshots=(); screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    if [[ "$verify_existing" == true ]]; then
        while IFS= read -r logged_name; do [[ -n "$logged_name" ]] || continue; candidate="$screenshot_dir/$logged_name"; [[ -f "$candidate" ]] && screenshots+=("$candidate"); done < <(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.png' "$latest_log" | sort -u)
    else
        while IFS= read -r -d '' candidate; do [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate"); done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
[[ ${#screenshots[@]} -ge 2 ]] || { echo "Batched PHASE 11 Composite smoke requires two fresh F2 screenshots." >&2; exit 1; }

flip_shot=""; history_shot=""
match_mode() {
    local mode="$1" label="$2" output candidate
    for candidate in "${screenshots[@]}"; do
        [[ "$candidate" == "$flip_shot" || "$candidate" == "$history_shot" ]] && continue
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-composite.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"; cat "$output"; rm -f "$output"
            if [[ "$mode" == "--flip" ]]; then flip_shot="$candidate"; else history_shot="$candidate"; fi
            return 0
        fi
        rm -f "$output"
    done
    echo "No fresh screenshot independently passed the $label verifier." >&2; return 1
}
match_mode --flip 'Composite flip parity'
match_mode --history 'Composite previous-frame history'

echo "PHASE 11 composite flip parity: PASS screenshot=$flip_shot"
echo "PHASE 11 composite temporal/history: PASS screenshot=$history_shot"
echo "Batched PHASE 11 Composite: PASS flip=$flip_shot history=$history_shot"
echo "After raw-log review these independent verdicts close PHASE 11 only; PHASE 12 Final remains separate."
