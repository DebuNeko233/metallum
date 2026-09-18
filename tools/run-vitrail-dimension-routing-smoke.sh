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
    echo "Vitrail Dimension Routing smoke requires Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixtures=(dimension-convention-contract dimension-properties-contract)
verifier="$vitrail_root/tests/VerifyDimensionRoutingScreenshot.java"
marker=""
[[ -f "$verifier" ]] || { echo "Dimension screenshot verifier is missing: $verifier" >&2; exit 2; }

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    for fixture in "${fixtures[@]}"; do
        source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
        target_dir="$repo_root/run/shaderpacks/$fixture"
        [[ -d "$source_dir/shaders" ]] || { echo "Missing fixture: $source_dir" >&2; exit 2; }
        rm -rf "$target_dir"
        cp -R "$source_dir" "$target_dir"
        echo "Installed Vitrail fixture at: $target_dir"
    done

    marker="$repo_root/run/.vitrail-dimension-routing-smoke-start"
    touch "$marker"
    cat <<'EOF'
Run ALL PHASE 13 Dimension Routing checkpoints in ONE client session.
Use a cheats-enabled test world; spectator mode makes the cross-dimension teleports safe.

A. Conventional routing pack
  1. Select 'dimension-convention-contract' in the Overworld.
     Expected GREEN (world0). Press F2.
  2. /gamemode spectator
     /execute in minecraft:the_nether run tp @s 0 80 0
     Expected RED (world-1). Press F2.
  3. /execute in minecraft:the_end run tp @s 0 80 0
     Expected BLUE (world1). Press F2.

B. dimension.properties routing pack
  4. /execute in minecraft:overworld run tp @s 0 100 0
     Select 'dimension-properties-contract'.
     Expected CYAN (arbitrary folder 'surface'). Press F2.
  5. /execute in minecraft:the_nether run tp @s 0 80 0
     Expected YELLOW (arbitrary folder 'under'). Press F2.
  6. /execute in minecraft:the_end run tp @s 0 80 0
     Expected WHITE: End is intentionally unmapped and must use dimension.catchall = *.
     Press F2.
  7. Exit normally.

MAGENTA is always a failure signature: it means routing fell back to the shader root.
Screenshot order is irrelevant; the launcher classifies all six fresh screenshots independently.
The fixture also declares exact custom dimension 'vitrail:moon' -> folder 'moon'; that exact-ID
path is locked by CI/source contract without adding test-only dimension policy to Metallum.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed batched PHASE 13 Dimension Routing smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this Dimension Routing launch was found." >&2
    exit 1
fi

grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" \
    || { echo "Dimension Routing smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for this batched PHASE 13 Dimension Routing smoke run."

routes=(
    "Drawing dimension-convention-contract from world0 for minecraft:overworld"
    "Drawing dimension-convention-contract from world-1 for minecraft:the_nether"
    "Drawing dimension-convention-contract from world1 for minecraft:the_end"
    "Drawing dimension-properties-contract from surface for minecraft:overworld"
    "Drawing dimension-properties-contract from under for minecraft:the_nether"
    "Drawing dimension-properties-contract from catchall for minecraft:the_end"
)
for route in "${routes[@]}"; do
    grep -qF "$route" "$latest_log" || { echo "Missing routed draw: $route" >&2; exit 1; }
done

grep -qF "a dimension replaces the root rather than layering over it" "$latest_log" \
    || { echo "No dimension-triggered whole-chain reload was recorded." >&2; exit 1; }
grep -qF "final writes the game's own target" "$latest_log" \
    || { echo "No routed Final was recorded writing the game's own target." >&2; exit 1; }
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then
    echo "Vitrail reported a chain failure during PHASE 13 Dimension Routing smoke." >&2
    exit 1
fi
grep -qF 'Stopping!' "$latest_log" || { echo "Dimension Routing smoke did not reach clean Stopping!." >&2; exit 1; }

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
[[ ${#screenshots[@]} -ge 6 ]] || { echo "Batched PHASE 13 smoke requires six fresh F2 screenshots." >&2; exit 1; }

declare -A matched=()
match_mode() {
    local mode="$1" label="$2" output candidate
    for candidate in "${screenshots[@]}"; do
        [[ -n ${matched["$candidate"]+x} ]] && continue
        output="$(mktemp "${TMPDIR:-/tmp}/vitrail-dimension.XXXXXX")"
        if java "$verifier" "$mode" "$candidate" >"$output" 2>&1; then
            echo "Matched $label screenshot: $candidate"
            cat "$output"
            rm -f "$output"
            matched["$candidate"]=1
            return 0
        fi
        rm -f "$output"
    done
    echo "No fresh screenshot independently passed the $label verifier." >&2
    return 1
}

match_mode --convention-overworld 'conventional Overworld / world0'
match_mode --convention-nether 'conventional Nether / world-1'
match_mode --convention-end 'conventional End / world1'
match_mode --properties-overworld 'dimension.properties Overworld / surface'
match_mode --properties-nether 'dimension.properties Nether / under'
match_mode --properties-fallback 'dimension.properties wildcard fallback / catchall'

echo "PHASE 13 conventional world0/world-1/world1: PASS"
echo "PHASE 13 dimension.properties arbitrary folders: PASS"
echo "PHASE 13 dimension.properties wildcard fallback: PASS"
echo "Batched PHASE 13 Dimension Routing: PASS screenshots=${#matched[@]}"
echo "After raw-log review this closes PHASE 13 only; PHASE 14 Wide Resources remains separate."
