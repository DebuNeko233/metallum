#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
fixture_mode=""
path_seen=false

usage() {
	echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal] [--mrt-fixture|--terrain-fixture|--gbuffer-location-fixture]" >&2
}

set_fixture_mode() {
	if [[ -n "$fixture_mode" ]]; then
		echo "Choose only one smoke fixture per launch." >&2
		usage
		exit 2
	fi
	fixture_mode="$1"
}

for argument in "$@"; do
	case "$argument" in
		--mrt-fixture)
			set_fixture_mode mrt
			;;
		--terrain-fixture)
			set_fixture_mode terrain
			;;
		--gbuffer-location-fixture)
			set_fixture_mode gbuffer-location
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

fixture_marker=""
fixture_verifier=""
fixture_label=""
if [[ -n "$fixture_mode" ]]; then
	case "$fixture_mode" in
		mrt)
			fixture_name="mrt-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="MRT"
			;;
		terrain)
			fixture_name="terrain-contract"
			fixture_verifier="$vitrail_root/tests/VerifyTerrainScreenshot.java"
			fixture_label="Terrain"
			;;
		gbuffer-location)
			fixture_name="gbuffer-location-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer location"
			;;
		*)
			echo "Internal error: unknown fixture mode '$fixture_mode'" >&2
			exit 2
			;;
	esac

	fixture_source="$vitrail_root/tests/fixtures/shaderpacks/$fixture_name"
	fixture_target="$repo_root/run/shaderpacks/$fixture_name"
	if [[ ! -d "$fixture_source/shaders" ]]; then
		echo "Vitrail $fixture_label smoke fixture not found at: $fixture_source" >&2
		exit 2
	fi
	if [[ ! -f "$fixture_verifier" ]]; then
		echo "Vitrail $fixture_label screenshot verifier not found at: $fixture_verifier" >&2
		exit 2
	fi

	mkdir -p "$(dirname "$fixture_target")" "$repo_root/run"
	rm -rf "$fixture_target"
	cp -R "$fixture_source" "$fixture_target"
	fixture_marker="$repo_root/run/.vitrail-${fixture_mode}-smoke-start"
	touch "$fixture_marker"
	echo "Installed Vitrail $fixture_label smoke fixture at: $fixture_target"
	echo "Select '$fixture_name' in Vitrail's shader-pack UI; the launcher does not change pack selection."
	if [[ "$fixture_mode" == mrt || "$fixture_mode" == gbuffer-location ]]; then
		echo "While the four-colour result is visible in-world, press F2 once; this launcher will verify that new screenshot after exit."
	else
		echo "Frame opaque blocks, cutout foliage/fire/flowers, and water together, then press F2 once."
		echo "The automatic check requires substantial red/green/blue terrain regions; transparent cutout silhouettes remain a manual visual check."
	fi
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

if [[ -n "$fixture_mode" ]]; then
	latest_log="$repo_root/run/logs/latest.log"
	if [[ ! -f "$latest_log" || ! "$latest_log" -nt "$fixture_marker" ]]; then
		echo "Could not confirm the graphics backend: no latest.log from this $fixture_label smoke launch was found." >&2
		exit 1
	fi

	if ! grep -qE 'Using graphics backend Metal|Client setup reached on the Metal backend' "$latest_log"; then
		actual_backend="$(sed -n 's/.*Using graphics backend \([^,]*\),.*/\1/p' "$latest_log" | tail -n1)"
		if [[ -n "$actual_backend" ]]; then
			echo "Vitrail $fixture_label smoke did not run on Metal; actual backend: $actual_backend." >&2
		else
			echo "Vitrail $fixture_label smoke did not provide evidence that the Metal backend was active." >&2
		fi
		echo "Select Prefer Metal, restart the client, and rerun --${fixture_mode}-fixture before treating this as Metal acceptance." >&2
		exit 1
	fi
	echo "Confirmed Metal backend for this $fixture_label smoke run."

	newest_screenshot=""
	screenshot_dir="$repo_root/run/screenshots"
	if [[ -d "$screenshot_dir" ]]; then
		while IFS= read -r -d '' candidate; do
			if [[ "$candidate" -nt "$fixture_marker" && ( -z "$newest_screenshot" || "$candidate" -nt "$newest_screenshot" ) ]]; then
				newest_screenshot="$candidate"
			fi
		done < <(find "$screenshot_dir" -type f -name '*.png' -print0)
	fi

	if [[ -n "$newest_screenshot" ]]; then
		echo "Verifying $fixture_label smoke screenshot: $newest_screenshot"
		java "$fixture_verifier" "$newest_screenshot"
	else
		echo "No screenshot newer than this $fixture_label smoke launch was found."
		echo "Pixel verification was not run; launch again with --${fixture_mode}-fixture and press F2 while the contract scene is visible."
	fi
fi
