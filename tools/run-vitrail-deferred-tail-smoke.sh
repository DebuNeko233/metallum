#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
verify_existing=false
usage() { echo "Usage: $0 [--verify-existing] [/path/to/Vitrail-Shaders-Metal]" >&2; }
if [[ ${1:-} == "--verify-existing" ]]; then verify_existing=true; shift; fi
if [[ $# -gt 1 ]]; then usage; exit 2; fi
if [[ $# -eq 1 ]]; then vitrail_root="$1"; fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then echo "Vitrail deferred tail smoke requires Apple-Silicon macOS." >&2; exit 2; fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2; fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixtures=(deferred-mrt-contract deferred-mipmap-contract)
verifier="$vitrail_root/tests/VerifyDeferredTailScreenshot.java"
marker=""
if [[ ! -f "$verifier" ]]; then echo "Deferred tail screenshot verifier is missing: $verifier" >&2; exit 2; fi

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    for fixture in "${fixtures[@]}"; do
        source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
        target_dir="$repo_root/run/shaderpacks/$fixture"
        [[ -d "$source_dir/shaders" ]] || { echo "Missing fixture: $source_dir" >&2; exit 2; }
        rm -rf "$target_dir"; cp -R "$source_dir" "$target_dir"
        echo "Installed Vitrail fixture at: $target_dir"
    done
    marker="$repo_root/run/.vitrail-deferred-tail-smoke-start"; touch "$marker"
    cat <<'EOF'
Run BOTH remaining PHASE 10 checkpoints in ONE client / ONE Overworld session:

  1. Select 'deferred-mrt-contract' and enter an Overworld.
     Expected: LEFT half BLUE, RIGHT half RED. MAGENTA means MRT state/half/order failure.
     Press F2 once.
  2. Without leaving the world, switch to 'deferred-mipmap-contract'.
     Expected: overwhelmingly CYAN. MAGENTA means missing/stale/wrong-half mip generation.
     Press F2 once.
  3. Exit normally.

Screenshot order is irrelevant: the launcher classifies both fresh screenshots independently.
MRT and mipmap keep separate verdicts even though they share this one hardware session.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed batched Deferred MRT+mipmap smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then echo "No latest.log from this deferred tail launch was found." >&2; exit 1; fi
grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" || { echo "Deferred tail smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for this batched deferred tail smoke run."

for fixture in "${fixtures[@]}"; do
    grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log" || { echo "$fixture did not draw in the Overworld." >&2; exit 1; }
done

# Deferred MRT: both targets must walk ALT -> MAIN -> ALT together and both become sampled inputs.
grep -qF 'deferred writes colortex0 alt, colortex1 alt' "$latest_log" || { echo "Deferred MRT did not write both ALT targets." >&2; exit 1; }
grep -qF 'deferred1 writes colortex0 main, colortex1 main' "$latest_log" || { echo "Deferred MRT deferred1 did not write both MAIN targets." >&2; exit 1; }
grep -qF 'deferred2 writes colortex0 alt, colortex1 alt' "$latest_log" || { echo "Deferred MRT deferred2 did not write both ALT targets." >&2; exit 1; }
grep -q '2 targets doubled: \[0, 1\]' "$latest_log" || { echo "Deferred MRT did not allocate both ping-pong targets." >&2; exit 1; }
grep -qE 'samplers this chain read a real colour target: .*colortex0.*colortex1' "$latest_log" || { echo "Deferred MRT did not prove both colour targets were sampled." >&2; exit 1; }

# Deferred mipmap: one doubled target must carry a real chain and be sampled by the deferred readers.
grep -qE 'Allocating colortex0 .* ([2-9]|[1-9][0-9]+) level\(s\)' "$latest_log" || { echo "Deferred mipmap fixture did not allocate a multi-level colortex0." >&2; exit 1; }
grep -qF '1 targets doubled: [0]' "$latest_log" || { echo "Deferred mipmap fixture did not allocate colortex0 ping-pong." >&2; exit 1; }
grep -qF '1 samplers this chain read a real colour target: [colortex0]' "$latest_log" || { echo "Deferred mipmap fixture did not prove colortex0 sampling." >&2; exit 1; }

split='0 of this chain run before the world [], 3 more before its translucents [deferred, deferred1, deferred2], 1 after'
if [[ $(grep -Fc "$split" "$latest_log") -lt 2 ]]; then echo "Both fixtures did not place all three Deferred passes before translucents." >&2; exit 1; fi
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then echo "Vitrail reported a chain failure during the batched Deferred tail smoke." >&2; exit 1; fi
grep -qF 'Stopping!' "$latest_log" || { echo "Deferred tail smoke did not reach clean Stopping!." >&2; exit 1; }

screenshots=(); screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    if [[ "$verify_existing" == true ]]; then
        while IFS= read -r logged_name; do [[ -n "$logged_name" ]] || continue; candidate="$screenshot_dir/$logged_name"; [[ -f "$candidate" ]] && screenshots+=("$candidate"); done < <(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.png' "$latest_log" | sort -u)
    else
        while IFS= read -r -d '' candidate; do [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate"); done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
[[ ${#screenshots[@]} -ge 2 ]] || { echo "Batched Deferred tail smoke requires two fresh F2 screenshots." >&2; exit 1; }

mrt_shot=""; mipmap_shot=""
match_mode() {
    local mode="$1" label="$2" output candidate
    for candidate in "${screenshots[@]}"; do
        [[ "$candidate" == "$mrt_shot" || "$candidate" == "$mipmap_shot" ]] && continue
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-deferred-tail.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"; cat "$output"; rm -f "$output"
            if [[ "$mode" == "--mrt" ]]; then mrt_shot="$candidate"; else mipmap_shot="$candidate"; fi
            return 0
        fi
        rm -f "$output"
    done
    echo "No fresh screenshot independently passed the $label verifier." >&2; return 1
}
match_mode --mrt 'Deferred MRT'
match_mode --mipmap 'Deferred mipmap'

echo "PHASE 10 deferred MRT: PASS screenshot=$mrt_shot"
echo "PHASE 10 deferred mipmap: PASS screenshot=$mipmap_shot"
echo "Batched PHASE 10 deferred tail: PASS MRT=$mrt_shot mipmap=$mipmap_shot"
echo "After raw-log review these two independent verdicts close the remaining PHASE 10 slices; PHASE 11 Composite remains separate."
