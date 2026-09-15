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
    echo "Vitrail PHASE 16 smoke requires Apple-Silicon macOS." >&2; exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
advanced_fixture="phase16-advanced-contract"
pbr_fixture="phase16-pbr-contract"
temporal_fixture="terrain-contract"
pbr_resources="phase16-pbr-resources"
advanced_source="$vitrail_root/tests/fixtures/shaderpacks/$advanced_fixture"
pbr_source="$vitrail_root/tests/fixtures/shaderpacks/$pbr_fixture"
temporal_source="$vitrail_root/tests/fixtures/shaderpacks/$temporal_fixture"
resources_source="$vitrail_root/tests/fixtures/resourcepacks/$pbr_resources"
advanced_verifier="$vitrail_root/tests/VerifyPhase16AdvancedScreenshot.java"
pbr_verifier="$vitrail_root/tests/VerifyPhase16PbrScreenshot.java"
temporal_verifier="$vitrail_root/tests/verify_phase16_temporal_log.py"
marker=""

for required in \
    "$advanced_source/shaders/final.fsh" \
    "$advanced_source/shaders/gbuffers_terrain_solid.fsh" \
    "$pbr_source/shaders/gbuffers_terrain.fsh" \
    "$temporal_source/shaders/gbuffers_terrain.fsh" \
    "$resources_source/pack.mcmeta" \
    "$advanced_verifier" \
    "$pbr_verifier" \
    "$temporal_verifier"; do
    [[ -f "$required" ]] || { echo "PHASE 16 acceptance input is missing: $required" >&2; exit 2; }
done

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run/resourcepacks" "$repo_root/run/vitrail"
    for fixture in "$advanced_fixture" "$pbr_fixture" "$temporal_fixture"; do
        case "$fixture" in
            "$advanced_fixture") source_dir="$advanced_source" ;;
            "$pbr_fixture") source_dir="$pbr_source" ;;
            "$temporal_fixture") source_dir="$temporal_source" ;;
        esac
        target_dir="$repo_root/run/shaderpacks/$fixture"
        rm -rf "$target_dir"
        cp -R "$source_dir" "$target_dir"
        echo "Installed Vitrail shader fixture at: $target_dir"
    done

    resource_target="$repo_root/run/resourcepacks/$pbr_resources"
    rm -rf "$resource_target"
    cp -R "$resources_source" "$resource_target"
    echo "Installed Vitrail resource fixture at: $resource_target"

    # The advanced COMPARE quarter is specifically a native-comparison-sampler acceptance.
    # The diagnostic software-comparison switch must stay unarmed for the whole session.
    rm -f "$repo_root/run/vitrail/soft-shadow-compare"

    marker="$repo_root/run/.vitrail-phase16-smoke-start"
    touch "$marker"
    cat <<'INSTRUCTIONS'
Run the complete PHASE 16 Advanced Features hardware acceptance in ONE client session:

  1. Select 'phase16-advanced-contract' and enter an Overworld. Face a large opaque
     block surface so real solid terrain occupies a substantial part of the third quarter.
     VOLUME, NOISE and COMPARE (quarters 1, 2 and 4) should be overwhelmingly GREEN.
     BLEND (quarter 3) is GREEN on drawn solid terrain and BLACK where no solid terrain
     covered the pixel; MAGENTA is failure. A black-only third quarter does not pass.
     Once stable, press F2 exactly once.

  2. Enable resource pack 'phase16-pbr-resources'. THEN open Vitrail's shader-pack
     selector and select 'phase16-pbr-contract'; verify that exact shader-pack name is
     selected rather than leaving 'phase16-advanced-contract' active. Face or place a
     vanilla stone block so a large stone face is visible. The marker stone must be GREEN
     with no meaningful MAGENTA. Only after the shader pack has visibly switched, press F2
     exactly once.

  3. Disable the PBR marker resource pack, select 'terrain-contract', set Render Scale
     to 75% and Temporal Fold to ON. Walk forward/backward and yaw the camera for several
     seconds. Static world detail must stay registered: reject persistent smear or
     wrong-direction reprojection. Then exit normally.

After the client exits this launcher verifies both fresh screenshots, Metal activation,
real gbuffers terrain execution for the Advanced blend gate, all three fixture draws,
native-comparison fallback remaining OFF, temporal motion-vector consumption,
sub-100% render scale, and clean Stopping!.
INSTRUCTIONS
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed PHASE 16 Advanced Features smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this PHASE 16 launch was found." >&2; exit 1
fi

grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" \
    || { echo "PHASE 16 smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for PHASE 16 Advanced Features smoke."

grep -qF "Drawing $advanced_fixture from the root for minecraft:overworld" "$latest_log" \
    || { echo "$advanced_fixture did not draw in the Overworld during this PHASE 16 session." >&2; exit 1; }
grep -qF "Drawing the solid chunk pass with gbuffers_terrain_solid of $advanced_fixture at render stage TERRAIN_SOLID" "$latest_log" \
    || { echo "$advanced_fixture did not execute its real gbuffers_terrain_solid blend marker on opaque terrain." >&2; exit 1; }
grep -qF 'per buffer blend directives read onto the attachment whose rank their target holds' "$latest_log" \
    || { echo "$advanced_fixture did not report an honoured per-buffer geometry blend directive." >&2; exit 1; }
grep -qF 'gbuffers_terrain_solid.colortex3=ONE ZERO' "$latest_log" \
    || { echo "$advanced_fixture did not land the colortex3 ONE ZERO override." >&2; exit 1; }
grep -qF 'gbuffers_terrain_solid.colortex1=ZERO ZERO' "$latest_log" \
    || { echo "$advanced_fixture did not land the colortex1 ZERO ZERO override." >&2; exit 1; }

if ! grep -qF "Drawing $pbr_fixture from the root for minecraft:overworld" "$latest_log"; then
    if grep -qF 'The resource pack answers normals for 1 of the' "$latest_log" \
        && grep -qF 'The resource pack answers specular for 1 of the' "$latest_log"; then
        echo "$pbr_resources loaded its normal/specular companions, but $pbr_fixture never drew." >&2
        echo "The resource pack was enabled while another shader pack remained selected; rerun and explicitly select $pbr_fixture before the second F2." >&2
    else
        echo "$pbr_fixture did not draw in the Overworld during this PHASE 16 session." >&2
    fi
    exit 1
fi

grep -qF "Drawing $temporal_fixture from the root for minecraft:overworld" "$latest_log" \
    || { echo "$temporal_fixture did not draw in the Overworld during this PHASE 16 session." >&2; exit 1; }

if [[ -e "$repo_root/run/vitrail/soft-shadow-compare" ]]; then
    echo "vitrail/soft-shadow-compare was armed; native comparison-sampler acceptance is invalid." >&2
    exit 1
fi
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then
    echo "Vitrail reported a shader-chain failure during PHASE 16 smoke." >&2; exit 1
fi
grep -qF 'Stopping!' "$latest_log" \
    || { echo "PHASE 16 smoke did not reach clean Stopping!." >&2; exit 1; }

pack_file="$repo_root/run/vitrail/pack.txt"
temporal_file="$repo_root/run/vitrail/temporal-fold"
[[ -f "$pack_file" ]] || { echo "Vitrail pack state was not found: $pack_file" >&2; exit 1; }
[[ -f "$temporal_file" ]] || { echo "Vitrail temporal state was not found: $temporal_file" >&2; exit 1; }
python3 "$temporal_verifier" "$latest_log" "$pack_file" "$temporal_file"

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
        # Minecraft screenshot names sort chronologically, so shell glob order preserves
        # Advanced -> PBR without relying on sub-second filesystem mtimes.
        for candidate in "$screenshot_dir"/*.png; do
            [[ -f "$candidate" ]] || continue
            [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate")
        done
    fi
fi
[[ ${#screenshots[@]} -ge 2 ]] \
    || { echo "PHASE 16 smoke requires two fresh F2 screenshots: Advanced first, PBR second." >&2; exit 1; }

advanced_shot=""
advanced_index=-1
for i in "${!screenshots[@]}"; do
    candidate="${screenshots[$i]}"
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-phase16-advanced.XXXXXX")"
    if java "$advanced_verifier" "$candidate" >"$output" 2>&1; then
        advanced_shot="$candidate"
        advanced_index="$i"
        cat "$output"
        rm -f "$output"
        break
    fi
    rm -f "$output"
done
[[ -n "$advanced_shot" ]] \
    || { echo "No fresh screenshot passed all four PHASE 16 Advanced quarters, including a visible real-terrain BLEND marker." >&2; exit 1; }

pbr_shot=""
for i in "${!screenshots[@]}"; do
    (( i > advanced_index )) || continue
    candidate="${screenshots[$i]}"
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-phase16-pbr.XXXXXX")"
    if java "$pbr_verifier" "$candidate" >"$output" 2>&1; then
        pbr_shot="$candidate"
        cat "$output"
        rm -f "$output"
        break
    fi
    rm -f "$output"
done
[[ -n "$pbr_shot" ]] \
    || { echo "No screenshot after the Advanced checkpoint passed the PHASE 16 PBR verifier." >&2; exit 1; }

read -r -p "Temporal camera motion had no persistent smear or wrong-direction reprojection? [y/N] " temporal_visual
case "$temporal_visual" in
    y|Y|yes|YES|Yes) ;;
    *) echo "PHASE 16 motion-vector direction/magnitude visual checkpoint was not accepted." >&2; exit 1 ;;
esac

echo "PHASE 16 sampler3D / noise / per-attachment blend / native compare: PASS screenshot=$advanced_shot"
echo "PHASE 16 PBR normal/specular companions: PASS screenshot=$pbr_shot"
echo "PHASE 16 Metal native comparison execution: PASS softFallback=off"
echo "PHASE 16 motion vectors + temporal accumulation: PASS visual=confirmed"
echo "Batched PHASE 16 Advanced Features: PASS screenshots=$advanced_shot,$pbr_shot"
echo "This closes the selected PHASE 16 real-device criteria only after raw-log review; documented compatibility limitations remain explicit."
