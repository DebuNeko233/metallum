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

mrt_marker=""
if [[ "$install_mrt_fixture" == true ]]; then
	fixture_source="$vitrail_root/tests/fixtures/shaderpacks/mrt-contract"
	fixture_target="$repo_root/run/shaderpacks/mrt-contract"
	verifier_source="$vitrail_root/tests/VerifyMrtScreenshot.java"
	if [[ ! -d "$fixture_source/shaders" ]]; then
		echo "Vitrail MRT smoke fixture not found at: $fixture_source" >&2
		exit 2
	fi
	if [[ ! -f "$verifier_source" ]]; then
		echo "Vitrail MRT screenshot verifier not found at: $verifier_source" >&2
		exit 2
	fi

	mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
	rm -rf "$fixture_target"
	cp -R "$fixture_source" "$fixture_target"
	mrt_marker="$repo_root/run/.vitrail-mrt-smoke-start"
	touch "$mrt_marker"
	echo "Installed Vitrail MRT smoke fixture at: $fixture_target"
	echo "Select 'mrt-contract' in Vitrail's shader-pack UI; the launcher does not change pack selection."
	echo "While the four-colour result is visible in-world, press F2 once; this launcher will verify that new screenshot after exit."
fi

echo "Launching Metallum dev client with Vitrail: $vitrail_jar"
echo "The Vitrail Metal shader-pack path is enabled only for this developer run."
echo "Select Prefer Metal in Video Settings and restart this command if the dev profile has not stored it yet."

cd "$repo_root"
set +e
./gradlew runClient -PvitrailSmokeJar="$vitrail_jar"
client_status=$?
set -e

if [[ $client_status -ne 0 ]]; then
	exit "$client_status"
fi

if [[ "$install_mrt_fixture" == true ]]; then
	newest_screenshot=""
	screenshot_dir="$repo_root/run/screenshots"
	if [[ -d "$screenshot_dir" ]]; then
		while IFS= read -r -d '' candidate; do
			if [[ "$candidate" -nt "$mrt_marker" && ( -z "$newest_screenshot" || "$candidate" -nt "$newest_screenshot" ) ]]; then
				newest_screenshot="$candidate"
			fi
		done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
	fi

	if [[ -n "$newest_screenshot" ]]; then
		echo "Verifying MRT smoke screenshot: $newest_screenshot"
		java "$vitrail_root/tests/VerifyMrtScreenshot.java" "$newest_screenshot"
	else
		echo "No screenshot newer than this MRT smoke launch was found."
		echo "Pixel verification was not run; launch again with --mrt-fixture and press F2 while the four-colour world view is visible."
	fi
fi
