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
    echo "Vitrail Metal deferred depth smoke requires Apple-Silicon macOS." >&2; exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2; exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="deferred-depth-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
target_dir="$repo_root/run/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyDeferredDepthScreenshot.java"
marker=""

if [[ ! -d "$source_dir/shaders" ]]; then echo "Vitrail deferred depth fixture is missing: $source_dir" >&2; exit 2; fi
if [[ ! -f "$verifier" ]]; then echo "Vitrail deferred depth screenshot verifier is missing: $verifier" >&2; exit 2; fi

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail deferred depth fixture at: $target_dir"
    marker="$repo_root/run/.vitrail-deferred-depth-smoke-start"
    touch "$marker"
    cat <<'EOF'
Run the PHASE 10 Deferred depth checkpoint:

  1. Select 'deferred-depth-contract' in Vitrail.
  2. Enter an Overworld view containing both open sky/background and nearby solid terrain.
  3. Wait for the full-screen chain to settle. The diagnostic should contain BOTH:
       RED    = valid locally constant opaque-world depth
       YELLOW = valid local opaque-world depth variation
     Broad MAGENTA means one deferred pass saw invalid depth, disagreed with the prior
     deferred pass about the same depth snapshot, or the colour-state chain broke.
  4. Press F2 once while RED+YELLOW are visible, then exit normally.

All of deferred, deferred1 and deferred2 sample depthtex0. The fixture carries the local-depth
variation bit through colortex0, so the final RED/YELLOW image is only reachable when all three
passes agree on the converted pre-translucent opaque-world depth. The final shader only presents
the latest colortex0 and does not count as PHASE 12 acceptance.
EOF
    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed deferred depth smoke without launching Minecraft."
fi

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" ]]; then echo "run/logs/latest.log was not found." >&2; exit 1; fi
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then echo "No latest.log from this deferred depth launch was found." >&2; exit 1; fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then echo "Deferred depth smoke did not prove Metal was active." >&2; exit 1; fi
echo "Confirmed Metal backend for this deferred depth smoke run."

if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then echo "Deferred depth fixture did not draw in the Overworld." >&2; exit 1; fi
if ! grep -qF 'deferred writes colortex0 alt' "$latest_log"; then echo "Deferred depth fixture did not record deferred writing ALT." >&2; exit 1; fi
if ! grep -qF 'deferred1 writes colortex0 main' "$latest_log"; then echo "Deferred depth fixture did not record deferred1 writing MAIN." >&2; exit 1; fi
if ! grep -qF 'deferred2 writes colortex0 alt' "$latest_log"; then echo "Deferred depth fixture did not record deferred2 writing ALT." >&2; exit 1; fi
if ! grep -qE "samplers this chain read the world's depth: .*depthtex0" "$latest_log"; then echo "Deferred depth chain did not record depthtex0 as a real world-depth sampler." >&2; exit 1; fi
if ! grep -qF '0 of this chain run before the world [], 3 more before its translucents [deferred, deferred1, deferred2], 1 after' "$latest_log"; then echo "Deferred depth fixture did not place all three deferred passes in the before-translucents cut." >&2; exit 1; fi
if ! grep -qF "The world's depth is converted into the pack's window in two images" "$latest_log"; then echo "Deferred depth smoke did not allocate the converted R32F world-depth pair." >&2; exit 1; fi
if ! grep -qF 'Vitrail depth window' "$latest_log"; then echo "Deferred depth smoke did not record the depth-window conversion pass." >&2; exit 1; fi
if grep -qF 'Vitrail stopped drawing this pack after an error' "$latest_log"; then echo "Vitrail reported a chain failure during the deferred depth smoke." >&2; exit 1; fi
if ! grep -qF 'Stopping!' "$latest_log"; then echo "Deferred depth smoke did not reach clean Stopping!." >&2; exit 1; fi

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
        while IFS= read -r -d '' candidate; do [[ "$candidate" -nt "$marker" ]] && screenshots+=("$candidate"); done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
if [[ ${#screenshots[@]} -lt 1 ]]; then echo "Deferred depth smoke requires one F2 screenshot from this run." >&2; exit 1; fi

matched=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-deferred-depth.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then matched="$candidate"; cat "$output"; rm -f "$output"; break; fi
    echo "Rejected deferred-depth screenshot candidate: $candidate" >&2
    grep -m1 'deferred depth screenshot swatches:' "$output" >&2 || cat "$output" >&2
    rm -f "$output"
done
if [[ -z "$matched" ]]; then echo "No screenshot proved stable deferred-family opaque-world depth sampling." >&2; exit 1; fi

echo "PHASE 10 deferred depth: PASS screenshot=$matched"
echo "This closes only the PHASE 10 Deferred depth slice after raw-log review; MRT and mipmap remain separate."
