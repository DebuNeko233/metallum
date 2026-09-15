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
    echo "Vitrail Metal shadow mipmap smoke requires Apple-Silicon macOS." >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
fixture="shadow-mipmap-contract"
source_dir="$vitrail_root/tests/fixtures/shaderpacks/$fixture"
target_dir="$repo_root/run/shaderpacks/$fixture"
verifier="$vitrail_root/tests/VerifyShadowMipmapScreenshot.java"
marker=""

if [[ ! -d "$source_dir/shaders" ]]; then
    echo "Vitrail shadow mipmap fixture is missing: $source_dir" >&2
    exit 2
fi
if [[ ! -f "$verifier" ]]; then
    echo "Vitrail shadow mipmap screenshot verifier is missing: $verifier" >&2
    exit 2
fi

if [[ "$verify_existing" == false ]]; then
    mkdir -p "$repo_root/run/shaderpacks" "$repo_root/run"
    rm -rf "$target_dir"
    cp -R "$source_dir" "$target_dir"
    echo "Installed Vitrail shadow mipmap fixture at: $target_dir"

    marker="$repo_root/run/.vitrail-shadow-mipmap-smoke-start"
    touch "$marker"

    cat <<'EOF'
Run the FINAL PHASE 9 shadow checkpoint:

  1. Select 'shadow-mipmap-contract' in Vitrail.
  2. Enter an Overworld daylight scene with ordinary opaque terrain inside the shadow-map area.
     The screen is a diagnostic, not a camera-space picture: BLUE means both LOD 4 reads still
     match their LOD 0 bases; GREEN means BOTH shadow depth chains show generated higher-mip
     reduction; MAGENTA means invalid depth or only one of the two chains reduced.
  3. Wait several frames for the shadow stage to settle. A real progressive nearest pair should
     produce a mixture of GREEN and BLUE with no substantial MAGENTA. If generation failed or high
     LOD stayed clamped to level zero, the diagnostic remains BLUE and the verifier will reject it.
  4. Press F2 once while the GREEN+BLUE diagnostic is visible, then exit normally.

This fixture requests BOTH shadowtex0Mipmap and shadowtex1Mipmap. One screenshot closes neither
name by declaration alone: the verifier requires the two names to show high-LOD reduction together,
rejects one-sided generation as MAGENTA, and the log gate separately requires both names to be bound.
EOF

    "$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"
else
    echo "Re-verifying the latest completed shadow mipmap smoke without launching Minecraft."
fi

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" ]]; then
    echo "Could not confirm the graphics backend: run/logs/latest.log was not found." >&2
    exit 1
fi
if [[ "$verify_existing" == false && ! "$latest_log" -nt "$marker" ]]; then
    echo "Could not confirm the graphics backend: no latest.log from this shadow mipmap launch was found." >&2
    exit 1
fi
if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
    echo "Vitrail shadow mipmap smoke did not prove that Metal was active." >&2
    exit 1
fi
echo "Confirmed Metal backend for this shadow mipmap smoke run."

if ! grep -qF "Drawing $fixture from the root for minecraft:overworld" "$latest_log"; then
    echo "Shadow mipmap smoke did not record $fixture drawing in the Overworld." >&2
    exit 1
fi
if ! grep -qE 'Shadow map allocated at .*pack asks for a chain the light fills every frame' "$latest_log"; then
    echo "Shadow mipmap smoke did not allocate the requested shadow depth mip chain." >&2
    exit 1
fi
if ! grep -qE '([2-9]|[1-9][0-9]+) levels where it reads shadowtex0 and ([2-9]|[1-9][0-9]+) levels where it reads shadowtex1' "$latest_log"; then
    echo "Shadow mipmap smoke did not prove that both shadowtex0 and shadowtex1 received multi-level allocations." >&2
    exit 1
fi
if ! grep -qE "2 samplers this chain read the shadow map: \[(shadowtex0, shadowtex1|shadowtex1, shadowtex0)\]" "$latest_log"; then
    echo "Shadow mipmap smoke did not bind shadowtex0 and shadowtex1 together after the shadow stage." >&2
    exit 1
fi
if ! grep -qF 'Drawing the shadow_solid chunk pass with shadow of shadow-mipmap-contract at render stage TERRAIN_SOLID' "$latest_log"; then
    echo "Shadow mipmap smoke did not record a real opaque terrain draw into the shadow depth base." >&2
    exit 1
fi
if grep -qF 'Vitrail stopped drawing the shadow map after an error' "$latest_log"; then
    echo "Vitrail reported a shadow-stage failure during the shadow mipmap smoke." >&2
    exit 1
fi
if ! grep -qF 'Stopping!' "$latest_log"; then
    echo "Vitrail shadow mipmap smoke did not reach a clean client shutdown (Stopping!)." >&2
    exit 1
fi

screenshots=()
screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    if [[ "$verify_existing" == true ]]; then
        while IFS= read -r logged_name; do
            [[ -n "$logged_name" ]] || continue
            candidate="$screenshot_dir/$logged_name"
            if [[ -f "$candidate" ]]; then
                screenshots+=("$candidate")
            fi
        done < <(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.png' "$latest_log" | sort -u)
    else
        while IFS= read -r -d '' candidate; do
            if [[ "$candidate" -nt "$marker" ]]; then
                screenshots+=("$candidate")
            fi
        done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
    fi
fi
if [[ ${#screenshots[@]} -lt 1 ]]; then
    echo "Shadow mipmap smoke requires one F2 screenshot from this run." >&2
    exit 1
fi

matched=""
for candidate in "${screenshots[@]}"; do
    output="$(mktemp "${TMPDIR:-/tmp}/vitrail-shadow-mipmap.XXXXXX")"
    if java "$verifier" "$candidate" >"$output" 2>&1; then
        matched="$candidate"
        cat "$output"
        rm -f "$output"
        break
    fi
    echo "Rejected shadow-mipmap screenshot candidate: $candidate" >&2
    grep -m1 'shadow mipmap screenshot swatches:' "$output" >&2 || cat "$output" >&2
    rm -f "$output"
done

if [[ -z "$matched" ]]; then
    echo "No screenshot proved readable generated shadow depth mips." >&2
    exit 1
fi

echo "PHASE 9 shadow mipmaps: PASS screenshot=$matched"
echo "This is the final PHASE 9 checkpoint; only mark PHASE 9 closed after reviewing this run's raw log and screenshot verdict together."
