#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
verify_existing=false

usage() {
    echo "Usage: $0 [--verify-existing] [/path/to/Vitrail-Shaders-Metal]" >&2
}

if [[ ${1:-} == "--verify-existing" ]]; then
    verify_existing=true
    shift
fi
if [[ $# -gt 1 ]]; then
    usage
    exit 2
fi
if [[ $# -eq 1 ]]; then
    vitrail_root="$1"
fi
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "Vitrail Metal deferred/composite smoke requires Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="deferred-composite-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
target_dir="$repo_root/run/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyDeferredCompositeScreenshot.java"
marker=""

if [[ ! -d "$source_dir/shaders" ]]; then
    echo "Vitrail deferred/composite fixture is missing: $source_dir" >&2
    exit 2
fi
if [[ ! -f "$verifier" ]]; then
    echo "Vitrail deferred/composite screenshot verifier is missing: $verifier" >&2
    exit 2
fi

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail deferred/composite fixture at: $target_dir"

    marker="$repo_root/run/.vitrail-deferred-composite-smoke-start"
    touch "$marker"

    cat <<'EOF'
Run PHASE 10A deferred/composite ordering checkpoint:

  1. Select 'deferred-composite-contract' in Vitrail.
  2. Enter any Overworld scene and wait for the full-screen chain to settle.
  3. The expected screen is overwhelmingly BLUE.
     RED means final sampled the deferred result.
     GREEN means final sampled the first composite result.
     MAGENTA means a composite sampled the wrong/stale half or ran out of order.
  4. Press F2 once while the BLUE diagnostic is visible, then exit normally.

The log is an independent gate: deferred must write colortex0 ALT, composite MAIN,
composite1 ALT, and final must write the game's own target. Pixel success without that
ordered write-side evidence does not close PHASE 10A.
EOF

    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed deferred/composite smoke without launching Minecraft."
fi

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" ]]; then
    echo "Could not confirm the graphics backend: run/logs/latest.log was not found." >&2
    exit 1
fi
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this deferred/composite launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Deferred/composite smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this deferred/composite smoke run."

if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then
    echo "Deferred/composite smoke did not record $fixture drawing in the Overworld." >&2
    exit 1
fi
if ! grep -qF 'deferred writes colortex0 alt' "$latest_log"; then
    echo "Deferred/composite smoke did not prove deferred wrote the ALT half of colortex0." >&2
    exit 1
fi
if ! grep -qF 'composite writes colortex0 main' "$latest_log"; then
    echo "Deferred/composite smoke did not prove composite wrote the MAIN half after deferred." >&2
    exit 1
fi
if ! grep -qF 'composite1 writes colortex0 alt' "$latest_log"; then
    echo "Deferred/composite smoke did not prove composite1 wrote ALT after composite." >&2
    exit 1
fi
if ! grep -qF "final writes the game's own target" "$latest_log"; then
    echo "Deferred/composite smoke did not record final presenting to the game's target." >&2
    exit 1
fi
if ! grep -qE 'samplers this chain read a real colour target: .*colortex0' "$latest_log"; then
    echo "Deferred/composite smoke did not prove the chain sampled a real colortex0 surface." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Deferred/composite smoke did not reach a clean client shutdown (Stopping!)." >&2
    exit 1
fi

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
if [[ ${#screenshots[@]} -lt 1 ]]; then
    echo "Deferred/composite smoke requires one F2 screenshot from this run." >&2
    exit 1
fi

matched=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-deferred-composite.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then
        matched="$candidate"
        cat "$output"
        rm -f "$output"
        break
    fi
    echo "Rejected deferred/composite screenshot candidate: $candidate" >&2
    grep -m1 'deferred/composite screenshot swatches:' "$output" >&2 || cat "$output" >&2
    rm -f "$output"
done

if [[ -z "$matched" ]]; then
    echo "No screenshot proved the ordered deferred/composite ping-pong chain." >&2
    exit 1
fi

echo "PHASE 10A deferred/composite ordering: PASS screenshot=$matched"
echo "Only mark PHASE 10A closed after reviewing this run's raw log and screenshot verdict together."
