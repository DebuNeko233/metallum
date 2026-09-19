#!/usr/bin/env python3
"""Pins the performance harness's shape, so that measuring this engine stays possible alone.

The harness is the only thing in either repository that can take a measurement without its owner:
it writes the pack selection the UI would have written, launches the client into a world, arms the
frame probe only once the pack has drawn a full frame, and collects the probe's window and a picture.
Every assertion here is about a property that made a hand-run measurement worthless at least once - a
window armed before there was a world, a pack named in the script rather than handed to it, a pack
committed to the repository instead of copied into an ignored dev instance - or about the one thing
that keeps the numbers honest, which is that they are the probe's own and not a second opinion.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools/run-vitrail-performance.sh"
COMPARE = ROOT / "tools/vitrail-performance-compare.py"
CI = ROOT / ".github/workflows/ci.yml"
GITIGNORE = ROOT / ".gitignore"

launcher = LAUNCHER.read_text(encoding="utf-8")
compare = COMPARE.read_text(encoding="utf-8")

subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)


def before(first: str, second: str, why: str) -> None:
    if first not in launcher or second not in launcher:
        raise SystemExit(why + " -- one of the two steps is not in the launcher at all")
    if not launcher.index(first) < launcher.index(second):
        raise SystemExit(why)


# ---------------------------------------------------------------------------
# A window worth counting
#
# The probe arms on the marker's return, so a marker that exists before the launch counts the frames
# before there is a world - which is how three hand-run windows in a row came back measuring a menu.
# The order is the whole of the fix: gone before the client starts, back only once the pack has drawn
# a full frame, and gone again when the runs are over.
# ---------------------------------------------------------------------------
before(
    'rm -f "$marker"\n\t: > "$game_dir/logs/latest.log"',
    "./gradlew runClient",
    "the marker is not cleared before the client starts, so a window would count the frames before a world",
)
before(
    'wait_for_log "first full frame opened"',
    'touch "$marker"',
    "the marker is not held back until the pack has drawn a full frame",
)
if 'rm -f "$marker"\nfi' not in launcher:
    raise SystemExit("the marker outlives the runs, so the next session would arm from a leftover file")

# ---------------------------------------------------------------------------
# A launch that failed costs seconds and not a timeout
#
# The first launch this harness ever made never started a client: Gradle read the game's arguments as
# the option after --args rather than as its value, because a word beginning with two dashes is an
# option to its parser. The harness waited out its whole timeout for a client that was already gone,
# which is the same bug in a second costume - so both halves are pinned here.
# ---------------------------------------------------------------------------
if '"--args=--quickPlaySingleplayer' not in launcher:
    raise SystemExit("the game's arguments are not passed with --args=, so Gradle reads them as options")
if 'wait_for_log "first full frame opened" "$deadline" "$launcher"' not in launcher:
    raise SystemExit("the wait does not watch the launcher, so a launch that failed looks like a slow one")
if "return 2" not in launcher:
    raise SystemExit("a launcher that exited is waited on until the timeout instead of ending the wait")

# ---------------------------------------------------------------------------
# A pack the harness is handed, never one it knows
#
# Shader packs are not redistributable and this repository is not where one lives. The pack arrives as
# an argument, is copied into the dev instance under run/, and is never named here.
# ---------------------------------------------------------------------------
if "--pack)" not in launcher:
    raise SystemExit("the pack is no longer an argument of the harness")
for pack in ("photon", "complementary", "bliss", "solas", "sundial", "makeup", "bsl", "sildur"):
    if pack in launcher.lower():
        raise SystemExit(f"the harness names a shader pack, which it may not: {pack}")
if 'cp -f "$pack_path" "$pack_dir/$pack_name"' not in launcher:
    raise SystemExit("the pack is not copied into the dev instance")
if 'pack_options="$pack_path.txt"' not in launcher or 'cp -f "$pack_options" "$pack_dir/$pack_name.txt"' not in launcher:
    raise SystemExit("the pack's own options are not staged beside it, so a run measures the pack's defaults")
if "run/" not in GITIGNORE.read_text(encoding="utf-8"):
    raise SystemExit("the dev instance is no longer ignored by git, so a run could be committed")

# ---------------------------------------------------------------------------
# The selection the UI would have made, made here
#
# Both files are what the game reads at startup, which is what lets a run come up on the pack and on
# the Metal path without anybody clicking.
# ---------------------------------------------------------------------------
for needle, why in (
    ('pack=$pack_name', "the pack selection is not written before the launch"),
    ("enabled=true", "the written pack selection does not switch shaders on"),
    ("preferredGraphicsApi=metal", "the written preference does not ask for the Metal path"),
):
    if needle not in launcher:
        raise SystemExit("the dev instance is not prepared: " + why)

# ---------------------------------------------------------------------------
# The jar measured is the jar this run built
#
# Every branch a developer has built leaves its jar in the same output directory, so a listing of
# that directory is not a statement about what was just built: the harness asks the build instead,
# through an init script whose task prints the archive the jar task wrote.
# ---------------------------------------------------------------------------
if "vitrail-perf-jar=" not in launcher:
    raise SystemExit("the harness does not ask the build which jar it produced")
if ":fabric:vitrailPerfJarPath" not in launcher:
    raise SystemExit("the harness does not run the task that names the jar")
if "-print -quit" in launcher:
    raise SystemExit("the harness picks its jar out of a directory listing, which is not the one it built")

# ---------------------------------------------------------------------------
# The window is the harness's length and not the probe's
#
# Two windows of different lengths are not two windows of one thing, so --frames has to reach the
# probe's own budget rather than being a number the harness keeps to itself.
# ---------------------------------------------------------------------------
if "-Dmetallum.frameProbeBudget=$frames" not in launcher:
    raise SystemExit("--frames never reaches the probe, so the window length is not the harness's")

# ---------------------------------------------------------------------------
# The numbers are the probe's own
#
# The comparison parses the line the probe printed rather than restating its counters, and refuses a
# picture it cannot read rather than guessing at one: a comparison against a number this side decided
# would agree with itself.
# ---------------------------------------------------------------------------
for counter in ("loadedMiB", "storedMiB", "depthAttachments", "depthLoadedMiB", "depthStoredMiB",
                "encoders", "passChanged", "windowMs"):
    if f'"{counter}"' not in compare:
        raise SystemExit(f"the comparison does not read the probe's {counter}")
if "ms a frame" not in compare:
    raise SystemExit(
        "the comparison does not turn the window's time into a frame rate, which is the reading any change is judged by"
    )
if "not a PNG" not in compare:
    raise SystemExit("the comparison no longer refuses a file that is not a picture")
if "unsupported PNG" not in compare:
    raise SystemExit("the comparison guesses at a picture it cannot read")
if "order.txt" not in compare or "order.txt" not in launcher:
    raise SystemExit("the comparison does not use the order the runs were asked for, so the baseline could be any of them")
if 'python3 "$repo_root/tools/vitrail-performance-compare.py"' not in launcher:
    raise SystemExit("the harness collects runs and never compares them")

if "tools/ci-vitrail-performance.py" not in CI.read_text(encoding="utf-8"):
    raise SystemExit("this contract is not named by ci.yml, so nothing runs it")

print("Vitrail performance harness contract: PASS")
