#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
vitrail_root="$repo_root/../Vitrail-Shaders-Metal"
fixture_mode=""
path_seen=false

usage() {
	echo "Usage: $0 [/path/to/Vitrail-Shaders-Metal] [--mrt-fixture|--terrain-fixture|--gbuffer-location-fixture|--gbuffer-format-fixture|--gbuffer-clear-fixture|--gbuffer-write-fixture|--gbuffer-sampling-fixture|--gbuffer-pingpong-fixture|--entity-fixture|--block-entity-fixture|--spider-eyes-fixture|--armor-glint-fixture|--hand-fixture|--hand-water-fixture|--hand-glint-fixture|--hand-water-glint-fixture]" >&2
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
		--mrt-fixture) set_fixture_mode mrt ;;
		--terrain-fixture) set_fixture_mode terrain ;;
		--gbuffer-location-fixture) set_fixture_mode gbuffer-location ;;
		--gbuffer-format-fixture) set_fixture_mode gbuffer-format ;;
		--gbuffer-clear-fixture) set_fixture_mode gbuffer-clear ;;
		--gbuffer-write-fixture) set_fixture_mode gbuffer-write ;;
		--gbuffer-sampling-fixture) set_fixture_mode gbuffer-sampling ;;
		--gbuffer-pingpong-fixture) set_fixture_mode gbuffer-pingpong ;;
		--entity-fixture) set_fixture_mode entity ;;
		--block-entity-fixture) set_fixture_mode block-entity ;;
		--spider-eyes-fixture) set_fixture_mode spider-eyes ;;
		--armor-glint-fixture) set_fixture_mode armor-glint ;;
		--hand-fixture) set_fixture_mode hand ;;
		--hand-water-fixture) set_fixture_mode hand-water ;;
		--hand-glint-fixture) set_fixture_mode hand-glint ;;
		--hand-water-glint-fixture) set_fixture_mode hand-water-glint ;;
		-*) usage; exit 2 ;;
		*)
			if [[ "$path_seen" == true ]]; then usage; exit 2; fi
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
		gbuffer-format)
			fixture_name="gbuffer-format-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer format"
			;;
		gbuffer-clear)
			fixture_name="gbuffer-clear-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer clear"
			;;
		gbuffer-write)
			fixture_name="gbuffer-write-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer write"
			;;
		gbuffer-sampling)
			fixture_name="gbuffer-sampling-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer sampling"
			;;
		gbuffer-pingpong)
			fixture_name="gbuffer-pingpong-contract"
			fixture_verifier="$vitrail_root/tests/VerifyMrtScreenshot.java"
			fixture_label="GBuffer ping-pong"
			;;
		entity)
			fixture_name="entity-contract"
			fixture_verifier="$vitrail_root/tests/VerifyEntityScreenshot.java"
			fixture_label="Entity"
			;;
		block-entity)
			fixture_name="block-entity-contract"
			fixture_verifier="$vitrail_root/tests/VerifyBlockEntityScreenshot.java"
			fixture_label="Block entity"
			;;
		spider-eyes)
			fixture_name="spider-eyes-contract"
			fixture_verifier="$vitrail_root/tests/VerifySpiderEyesScreenshot.java"
			fixture_label="Spider eyes"
			;;
		armor-glint)
			fixture_name="armor-glint-contract"
			fixture_verifier="$vitrail_root/tests/VerifyArmorGlintScreenshot.java"
			fixture_label="Armor glint"
			;;
		hand)
			fixture_name="hand-contract"
			fixture_verifier="$vitrail_root/tests/VerifyHandScreenshot.java"
			fixture_label="Hand solid"
			;;
		hand-water)
			fixture_name="hand-water-contract"
			fixture_verifier="$vitrail_root/tests/VerifyHandScreenshot.java"
			fixture_label="Hand translucent"
			;;
		hand-glint)
			fixture_name="hand-glint-contract"
			fixture_verifier="$vitrail_root/tests/VerifyHandGlintScreenshot.java"
			fixture_label="Hand glint solid"
			;;
		hand-water-glint)
			fixture_name="hand-water-glint-contract"
			fixture_verifier="$vitrail_root/tests/VerifyHandGlintScreenshot.java"
			fixture_label="Hand glint translucent"
			;;
		*) echo "Internal error: unknown fixture mode '$fixture_mode'" >&2; exit 2 ;;
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
	if [[ "$fixture_mode" == mrt || "$fixture_mode" == gbuffer-location || "$fixture_mode" == gbuffer-format || "$fixture_mode" == gbuffer-clear || "$fixture_mode" == gbuffer-write || "$fixture_mode" == gbuffer-sampling || "$fixture_mode" == gbuffer-pingpong ]]; then
		echo "While the four-colour result is visible in-world, press F2 once; this launcher will verify that new screenshot after exit."
	elif [[ "$fixture_mode" == entity ]]; then
		echo "Frame one ordinary living entity close enough to occupy a visible region; green means the entity ABI passed, magenta means it failed. Press F2 once, then exit normally."
		echo "Do not use a block entity, spider-eye/emissive layer, armor glint, hand, particle, weather, cloud or sky element as evidence for this checkpoint."
	elif [[ "$fixture_mode" == block-entity ]]; then
		echo "Frame one ordinary model-backed block entity (a chest is recommended) close enough to occupy a visible region; green means block routing plus the carried vertex ABI passed, magenta means the ABI failed. Press F2 once, then exit normally."
		echo "Ordinary entities, spider eyes, armor glint, hand, particles, weather, clouds and sky do not count for this checkpoint."
	elif [[ "$fixture_mode" == spider-eyes ]]; then
		echo "Frame a spider close to the camera with its glowing eye layer clearly visible. The fixture displays only the eye target: green means gbuffers_spidereyes routing plus full-bright input passed, magenta means full-bright failed, and black means the eye program did not draw. Press F2 once, then exit normally."
		echo "Ordinary entity body colour, block entities, armor glint, hand, particles, weather, clouds and sky do not count for this checkpoint."
	elif [[ "$fixture_mode" == armor-glint ]]; then
		echo "Frame a world entity or armor stand wearing enchanted armor close to the camera. The fixture displays only the camera glint target: stable solid green means gbuffers_armor_glint plus the POSITION_TEX/glint synthesized-input ABI passed, magenta means that ABI failed, and black means the camera glint did not draw. The animated glint stripes are verified separately through the real texture log gate and do not modulate the pixel colour. Press F2 once, then exit normally."
		echo "A held enchanted item or any hand glint does not count for this checkpoint; hand and hand_water remain separate later gates."
	elif [[ "$fixture_mode" == hand ]]; then
		echo "Use first person and hold an ordinary opaque/non-translucent item. The fixture displays only the solid hand target: green means gbuffers_hand routing plus the carried entity-polygon ABI passed, magenta means the ABI failed, and black means the solid hand did not draw. Press F2 once, then exit normally."
		echo "Do not hold a translucent block model for this checkpoint; that belongs to --hand-water-fixture."
	elif [[ "$fixture_mode" == hand-water ]]; then
		echo "Use first person and hold a translucent block model; glass is recommended. This is the Iris-compatible hand_water trigger and does not mean the player should stand underwater. Green means gbuffers_hand_water at HAND_TRANSLUCENT plus the carried entity-polygon ABI passed, magenta means the ABI failed, and black means that pass did not draw. Press F2 once, then exit normally."
	elif [[ "$fixture_mode" == hand-glint ]]; then
		echo "Use first person and hold a glinting opaque/non-translucent item; an enchanted book or enchanted tool is suitable. Stable green means hand_glint routed through gbuffers_armor_glint at HAND_SOLID and the GLINT/POSITION_TEX synthesized-input ABI passed; magenta means ABI failure and black means hand_glint did not draw. Press F2 once, then exit normally."
		echo "Camera armor glint and hand_water_glint do not count for this checkpoint."
	elif [[ "$fixture_mode" == hand-water-glint ]]; then
		echo "Use first person and hold a translucent block model with glint forced/enabled; glass with an item glint override is suitable. This is the Iris-compatible HAND_TRANSLUCENT pass, not physical immersion in water. Stable green means hand_water_glint routed through gbuffers_armor_glint and the GLINT/POSITION_TEX ABI passed. Press F2 once, then exit normally."
		echo "Camera armor glint and solid hand_glint do not count for this checkpoint."
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

	if [[ "$fixture_mode" == entity ]] && ! grep -qE 'Drawing the .* entity pass with gbuffers_entities of entity-contract' "$latest_log"; then
		echo "Vitrail Entity smoke did not record an ordinary entity draw through gbuffers_entities; frame a normal living entity and rerun --entity-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == block-entity ]] && ! grep -qE 'Drawing the block_.* entity pass with gbuffers_block of block-entity-contract at render stage BLOCK_ENTITIES' "$latest_log"; then
		echo "Vitrail Block entity smoke did not record a block-entity draw through gbuffers_block at BLOCK_ENTITIES; frame a chest or another ordinary model-backed block entity and rerun --block-entity-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == spider-eyes ]] && ! grep -qE 'Drawing the (eyes|eyes_emissive) entity pass with gbuffers_spidereyes of spider-eyes-contract at render stage NONE' "$latest_log"; then
		echo "Vitrail Spider eyes smoke did not record an eye/emissive-eye draw through gbuffers_spidereyes at render stage NONE; frame a spider with its glowing eye layer visible and rerun --spider-eyes-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == armor-glint ]] && ! grep -qE 'Drawing the glint_late .* pass with gbuffers_armor_glint of armor-glint-contract at render stage NONE' "$latest_log"; then
		echo "Vitrail Armor glint smoke did not record the camera glint_late draw through gbuffers_armor_glint; frame enchanted armor on a world entity or armor stand and rerun --armor-glint-fixture. Held-item/hand glint does not count." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == armor-glint ]] && ! grep -qF 'The glint_late pass records its first draw with gbuffers_armor_glint, reading minecraft:textures/misc/enchanted_glint_armor.png' "$latest_log"; then
		echo "Vitrail Armor glint smoke did not prove that glint_late sampled minecraft:textures/misc/enchanted_glint_armor.png; rerun --armor-glint-fixture with enchanted armor visible." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand ]] && ! grep -qE 'Drawing the hand_[^ ]* entity pass with gbuffers_hand of hand-contract at render stage HAND_SOLID' "$latest_log"; then
		echo "Vitrail Hand solid smoke did not record a first-person hand draw through gbuffers_hand at HAND_SOLID; use first person with an opaque/non-translucent held item and rerun --hand-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand ]] && ! grep -qE 'The hand_[^ ]* pass records its first draw with gbuffers_hand, reading minecraft:' "$latest_log"; then
		echo "Vitrail Hand solid smoke did not prove a real Minecraft texture sample through gbuffers_hand; rerun --hand-fixture with the held hand/item visible." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-water ]] && ! grep -qE 'Drawing the hand_water_[^ ]* entity pass with gbuffers_hand_water of hand-water-contract at render stage HAND_TRANSLUCENT' "$latest_log"; then
		echo "Vitrail Hand translucent smoke did not record a first-person hand draw through gbuffers_hand_water at HAND_TRANSLUCENT; hold a translucent block model such as glass and rerun --hand-water-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-water ]] && ! grep -qE 'The hand_water_[^ ]* pass records its first draw with gbuffers_hand_water, reading minecraft:' "$latest_log"; then
		echo "Vitrail Hand translucent smoke did not prove a real Minecraft texture sample through gbuffers_hand_water; rerun --hand-water-fixture with a translucent block model visible." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-glint ]] && ! grep -qE 'Drawing the hand_glint .* pass with gbuffers_armor_glint of hand-glint-contract at render stage HAND_SOLID' "$latest_log"; then
		echo "Vitrail Hand glint solid smoke did not record hand_glint through gbuffers_armor_glint at HAND_SOLID; use first person with a glinting opaque/non-translucent held item and rerun --hand-glint-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-glint ]] && ! grep -qE 'The hand_glint pass records its first draw with gbuffers_armor_glint, reading minecraft:textures/misc/enchanted_glint_(item|armor)\.png' "$latest_log"; then
		echo "Vitrail Hand glint solid smoke did not prove a real Minecraft enchanted-glint texture sample; rerun --hand-glint-fixture with the held glint visible." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-water-glint ]] && ! grep -qE 'Drawing the hand_water_glint .* pass with gbuffers_armor_glint of hand-water-glint-contract at render stage HAND_TRANSLUCENT' "$latest_log"; then
		echo "Vitrail Hand glint translucent smoke did not record hand_water_glint through gbuffers_armor_glint at HAND_TRANSLUCENT; use a glinting translucent held block model and rerun --hand-water-glint-fixture." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-water-glint ]] && ! grep -qE 'The hand_water_glint pass records its first draw with gbuffers_armor_glint, reading minecraft:textures/misc/enchanted_glint_(item|armor)\.png' "$latest_log"; then
		echo "Vitrail Hand glint translucent smoke did not prove a real Minecraft enchanted-glint texture sample; rerun --hand-water-glint-fixture with the held glint visible." >&2
		exit 1
	fi
	if [[ "$fixture_mode" == hand-glint || "$fixture_mode" == hand-water-glint ]]; then
		if ! grep -qF "Its draw buffers all reach the pack's own targets, nought included: [colortex1 MAIN]" "$latest_log"; then
			echo "Vitrail $fixture_label smoke did not prove the isolated [colortex1 MAIN] target." >&2
			exit 1
		fi
		if ! grep -qF 'Stopping!' "$latest_log"; then
			echo "Vitrail $fixture_label smoke did not reach a clean client shutdown (Stopping!)." >&2
			exit 1
		fi
	fi

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
		if [[ "$fixture_mode" == hand-glint || "$fixture_mode" == hand-water-glint ]]; then
			echo "This hand-glint gate requires pixel evidence; rerun --${fixture_mode}-fixture and press F2 while the held glint is visible." >&2
			exit 1
		fi
		echo "Pixel verification was not run; launch again with --${fixture_mode}-fixture and press F2 while the contract scene is visible."
	fi
fi
