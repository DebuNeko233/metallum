#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
install_mrt_fixture=false
path_seen=false

usage() {
	echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal] [--mrt-fixture]" >&2
}

for argument in "$@"; do
	case "$argument" in
		--mrt-fixture)
			install_mrt_fixture=true
			;;
		-*)
			usage
			exit 2
			;;
		*)
			if [[ "$path_seen" == true ]]; then
				usage
				exit 2
			fi
			vitrail_root="$argument"
			path_seen=true
			;;
	esac
done

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
	echo "Vitrail Metal smoke runs require Apple-Silicon macOS." >&2
	exit 2
fi

if [[ ! -x "$vitrail_root/gradlew" || ! -f "$vitrail_root/settings.gradle" ]]; then
	echo "Vitrail checkout not found at: $vitrail_root" >&2
	usage
	exit 2
fi

vitrail_root="$(cd "$vitrail_root" && pwd)"

(
	cd "$vitrail_root"
	./gradlew :fabric:jar
)

vitrail_jar=""
for candidate in "$vitrail_root"/fabric/build/libs/vitrail-fabric-*.jar; do
	[[ -f "$candidate" ]] || continue
	[[ "$candidate" == *-sources.jar ]] && continue
	if [[ -z "$vitrail_jar" || "$candidate" -nt "$vitrail_jar" ]]; then
		vitrail_jar="$candidate"
	fi
done

if [[ -z "$vitrail_jar" ]]; then
	echo "No Vitrail Fabric jar was produced under $vitrail_root/fabric/build/libs" >&2
	exit 1
fi

if [[ "$install_mrt_fixture" == true ]]; then
	fixture_source="$vitrail_root/tests/fixtures/shaderpacks/mrt-contract"
	fixture_target="$repo_root/run/shaderpacks/mrt-contract"
	if [[ ! -d "$fixture_source/shaders" ]]; then
		echo "Vitrail MRT smoke fixture not found at: $fixture_source" >&2
		exit 2
	fi

	mkdir -p "$(dirname "$fixture_target")"
	rm -rf "$fixture_target"
	cp -R "$fixture_source" "$fixture_target"
	echo "Installed Vitrail MRT smoke fixture at: $fixture_target"
	echo "Select 'mrt-contract' in Vitrail's shader-pack UI; the launcher does not change pack selection."
fi

echo "Launching Metallum dev client with Vitrail: $vitrail_jar"
echo "The Vitrail Metal shader-pack path is enabled only for this developer run."
echo "Select Prefer Metal in Video Settings and restart this command if the dev profile has not stored it yet."

cd "$repo_root"
exec ./gradlew runClient -PvitrailSmokeJar="$vitrail_jar"
