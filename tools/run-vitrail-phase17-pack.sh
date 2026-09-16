#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
pack_path=""
family=""
pack_name=""
pack_version=""
runtime_name=""

usage() {
    cat >&2 <<'EOF'
Usage:
  run-vitrail-phase17-pack.sh \
    --pack /path/to/pack.zip \
    --family <matrix-id> \
    --name <display-name> \
    --version <exact-version> \
    [--runtime-name <name-in-vitrail-log>] \
    [--vitrail /path/to/Vitrail-Shaders-Metal]

This stages one exact real shader pack, launches the existing Vitrail-on-Metallum
developer client, then creates a conservative PHASE 17 evidence JSON from the new
Metal session. It does not assign a compatibility status.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pack)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            pack_path="$2"; shift 2 ;;
        --pack=*) pack_path="${1#--pack=}"; shift ;;
        --family)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            family="$2"; shift 2 ;;
        --family=*) family="${1#--family=}"; shift ;;
        --name)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            pack_name="$2"; shift 2 ;;
        --name=*) pack_name="${1#--name=}"; shift ;;
        --version)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            pack_version="$2"; shift 2 ;;
        --version=*) pack_version="${1#--version=}"; shift ;;
        --runtime-name)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            runtime_name="$2"; shift 2 ;;
        --runtime-name=*) runtime_name="${1#--runtime-name=}"; shift ;;
        --vitrail)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            vitrail_root="$2"; shift 2 ;;
        --vitrail=*) vitrail_root="${1#--vitrail=}"; shift ;;
        -h|--help)
            usage
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            exit 2 ;;
    esac
done

for value_name in pack_path family pack_name pack_version; do
    [[ -n "${!value_name}" ]] || { echo "Missing required option for $value_name." >&2; usage; exit 2; }
done

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "PHASE 17 real-pack runs require Apple-Silicon macOS." >&2
    exit 2
fi

if [[ ! -e "$pack_path" ]]; then
    echo "Shader-pack artifact not found: $pack_path" >&2
    exit 2
fi
if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
    echo "Vitrail checkout not found at: $vitrail_root" >&2
    exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"
collector="$vitrail_root/tests/phase17_collect_session.py"
[[ -f "$collector" ]] || { echo "PHASE 17 collector not found at: $collector" >&2; exit 2; }

if ! git -C "$repo_root" diff --quiet || ! git -C "$repo_root" diff --cached --quiet; then
    echo "Metallum worktree has tracked changes; commit/stash them before recording PHASE 17 evidence." >&2
    exit 2
fi
if ! git -C "$vitrail_root" diff --quiet || ! git -C "$vitrail_root" diff --cached --quiet; then
    echo "Vitrail worktree has tracked changes; commit/stash them before recording PHASE 17 evidence." >&2
    exit 2
fi

metallum_head="$(git -C "$repo_root" rev-parse HEAD)"
vitrail_head="$(git -C "$vitrail_root" rev-parse HEAD)"

pack_path="$(python3 - "$pack_path" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
)"

artifact_base="$(basename "$pack_path")"
if [[ -z "$runtime_name" ]]; then
    runtime_name="$artifact_base"
    runtime_name="${runtime_name%.zip}"
fi

shaderpack_dir="$repo_root/run/shaderpacks"
mkdir -p "$shaderpack_dir" "$repo_root/run/vitrail/phase17"
staged="$shaderpack_dir/$artifact_base"
staged_real="$(python3 - "$staged" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
)"

if [[ "$pack_path" != "$staged_real" ]]; then
    rm -rf "$staged"
    if [[ -d "$pack_path" ]]; then
        cp -R "$pack_path" "$staged"
    else
        cp "$pack_path" "$staged"
    fi
fi

marker="$repo_root/run/.vitrail-phase17-pack-start"
touch "$marker"

cat <<EOF
PHASE 17 real shader-pack evidence run

  Pack:       $pack_name $pack_version
  Family:     $family
  Runtime:    $runtime_name
  Vitrail:    $vitrail_head
  Metallum:   $metallum_head

In the client:
  1. Explicitly select '$runtime_name' in Vitrail's shader-pack selector.
  2. Enter the Overworld compatibility/reference scene and wait for the pack to settle.
  3. Frame the scene used for the Iris/reference comparison and press F2 exactly once.
  4. Exit normally.

The launcher will find the new log/screenshot and create evidence automatically.
It will NOT assign Supported/Partial/Fallback/Unsupported from raw warnings.
EOF

"$repo_root/tools/run-vitrail-smoke.sh" "$vitrail_root"

latest_log="$repo_root/run/logs/latest.log"
if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$marker" ]]; then
    echo "No latest.log from this PHASE 17 client launch was found." >&2
    exit 1
fi

newest_screenshot=""
screenshot_dir="$repo_root/run/screenshots"
if [[ -d "$screenshot_dir" ]]; then
    while IFS= read -r -d '' candidate; do
        if [[ "$candidate" -nt "$marker" && ( -z "$newest_screenshot" || "$candidate" -nt "$newest_screenshot" ) ]]; then
            newest_screenshot="$candidate"
        fi
    done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
fi
if [[ -z "$newest_screenshot" ]]; then
    echo "PHASE 17 requires one fresh F2 screenshot from the tested real pack." >&2
    exit 1
fi

stamp="$(date '+%Y%m%d-%H%M%S')"
safe_family="$(printf '%s' "$family" | tr -cs 'A-Za-z0-9._-' '-')"
evidence_out="$repo_root/run/vitrail/phase17/${safe_family}-${stamp}.json"

python3 "$collector" \
    --log "$latest_log" \
    --pack "$pack_path" \
    --family "$family" \
    --name "$pack_name" \
    --version "$pack_version" \
    --runtime-name "$runtime_name" \
    --vitrail-head "$vitrail_head" \
    --metallum-head "$metallum_head" \
    --screenshot "$newest_screenshot" \
    --out "$evidence_out"

echo "PHASE 17 draft evidence: $evidence_out"
echo "PHASE 17 reference/compatibility review remains pending; no public pack status was assigned."
