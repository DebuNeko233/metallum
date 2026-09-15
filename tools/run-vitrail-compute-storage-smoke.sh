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
    echo "Vitrail Compute / Storage smoke requires Apple-Silicon macOS." >&2; exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="compute-storage-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyComputeStorageScreenshot.java"
marker=""
[[ -f "$verifier" ]] || { echo "Compute/storage screenshot verifier is missing: $verifier" >&2; exit 2; }
[[ -f "$source_dir/shaders/composite.csh" ]] || { echo "Compute/storage fixture is missing: $source_dir" >&2; exit 2; }
[[ -f "$source_dir/shaders/composite_a.csh" ]] || { echo "Second compute pass is missing: $source_dir/shaders/composite_a.csh" >&2; exit 2; }

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    target_dir="$repo_root/run/shaderpacks/$fixture"
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail fixture at: $target_dir"

    marker="$repo_root/run/.vitrail-compute-storage-smoke-start"
    touch "$marker"
    cat <<'EOF'
Run the PHASE 15 Compute / Storage hardware acceptance in one client session:

  1. Select 'compute-storage-contract' and enter an Overworld.
  2. Expected output: overwhelmingly GREEN.
     MAGENTA means the first compute's SSBO/storage-image writes were not visible to the
     second compute, imageLoad/imageStore failed, or the following render pass did not see
     the storage image written by compute.
  3. Once GREEN is stable, press F2 once.
  4. Exit normally.

The log must independently prove both compute programs dispatched through the active backend
as one 1x1x1 workgroup, the pack storage buffer and image were allocated, and the composite
render pass followed them. Screenshot colour alone is not enough to close PHASE 15.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed PHASE 15 Compute / Storage smoke."
fi

latest_log="$repo_root/run/logs/latest.log"
[[ -f "$latest_log" ]] || { echo "run/logs/latest.log was not found." >&2; exit 1; }
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this Compute / Storage launch was found." >&2; exit 1
fi

grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log" \
    || { echo "Compute / Storage smoke did not prove Metal was active." >&2; exit 1; }
echo "Confirmed Metal backend for PHASE 15 Compute / Storage smoke."

grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log" \
    || { echo "$fixture did not draw in the Overworld." >&2; exit 1; }
grep -qF 'storage buffer 0 as Phase15Buffer 16 bytes through the active GPU backend' "$latest_log" \
    || { echo "PHASE 15 named SSBO was not allocated through the active backend." >&2; exit 1; }
grep -qF 'storage image phase15Image as phase15Tex TEXTURE_2D RGBA8 1x1' "$latest_log" \
    || { echo "PHASE 15 custom storage image was not allocated." >&2; exit 1; }
grep -qF 'Dispatched compute composite through the active backend: groups=(1, 1, 1), local=(1, 1, 1)' "$latest_log" \
    || { echo "First PHASE 15 compute did not dispatch as the required 1x1x1 workgroup." >&2; exit 1; }
grep -qF 'Dispatched compute composite_a through the active backend: groups=(1, 1, 1), local=(1, 1, 1)' "$latest_log" \
    || { echo "Second PHASE 15 compute did not dispatch as the required 1x1x1 workgroup." >&2; exit 1; }
grep -qF 'Dispatched 2 compute pass(es) at composite' "$latest_log" \
    || { echo "The two PHASE 15 computes were not recorded at the composite boundary." >&2; exit 1; }
grep -qE 'composite writes colortex0 (main|alt)' "$latest_log" \
    || { echo "Composite render pass did not follow the compute chain." >&2; exit 1; }
grep -qF "final writes the game's own target" "$latest_log" \
    || { echo "Final did not present the PHASE 15 diagnostic." >&2; exit 1; }
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then
    echo "Vitrail reported a chain failure during PHASE 15 Compute / Storage smoke." >&2; exit 1
fi
grep -qF 'Stopping!' "$latest_log" \
    || { echo "Compute / Storage smoke did not reach clean Stopping!." >&2; exit 1; }

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
[[ ${#screenshots[@]} -ge 1 ]] || { echo "PHASE 15 Compute / Storage smoke requires one fresh F2 screenshot." >&2; exit 1; }

passing_shot=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-compute-storage.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then
        passing_shot="$candidate"
        cat "$output"
        rm -f "$output"
        break
    fi
    rm -f "$output"
done
[[ -n "$passing_shot" ]] || { echo "No fresh screenshot passed the PHASE 15 Compute / Storage verifier." >&2; exit 1; }

echo "PHASE 15 compute dispatch chain: PASS composite -> composite_a -> render"
echo "PHASE 15 SSBO + storage image + imageLoad/imageStore: PASS"
echo "PHASE 15 Compute / Storage: PASS screenshot=$passing_shot"
echo "This closes PHASE 15 only after raw-log review; later roadmap phases remain independent."
