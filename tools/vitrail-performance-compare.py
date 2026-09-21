#!/usr/bin/env python3
"""Prints what the performance harness collected, side by side.

The counters are the frame probe's own line, parsed rather than restated: what the probe counted is
what this prints, so a change to the probe's shape is a change here and not a second opinion about
it. The pictures are compared as pixels and not as opinions, because the harness cannot play and a
person's eye is the one thing it does not have.

The comparison is between the first run and each of the others, and it is a difference rather than a
verdict: the harness draws the same world at the same window under different switches, so a fall in
the bytes and no difference in the picture is the result being looked for, and a difference in the
picture is what says a switch changed what the frame is.

Usage: vitrail-performance-compare.py OUT_DIR
"""
from __future__ import annotations

import re
import struct
import sys
import zlib
from pathlib import Path

# The probe's own words, in the order it prints them. A counter added there and not here is still
# printed raw below the table rather than dropped.
# Two arms of one configuration differ by well under a per cent on the scene counters - the settled pack
# fixture read 0.2 per cent - so this is generous and still refuses another scene.
SCENE_TOLERANCE = 2.0
# What the arms of one generation may differ by and still be the same frame. The counters below move with the
# world's own streaming and its entities - measured: two Metal 3 arms of one session differed by 2.1% of
# loadedMiB and 2.4% of depth attachments while their wall time agreed to 0.2%, and two Metal 4 arms differed by
# 12.2% of draws, 14.7% of texture bindings and 15.1% of buffer bindings on the same world, pack, target and
# window. Five per cent is the plan's own performance gate, so a content difference of a size no verdict could
# survive is the size this refuses.
CONTENT_TOLERANCE = 5.0

# How far one arm's own frame rate may sit from the fastest arm of its generation before the arm is named as one
# the machine spoiled rather than one the change moved. 1.5 rather than a tighter number because this path's own
# arms legitimately spread by up to 15% between consecutive runs (measured, run/m4-four: 18.22, 18.41, 18.51 and
# 27.50 - and the 27.50 is the arm whose load sample was twice the others'), and looser than that would let the
# 433% of run/vanilla-grid through unnamed.
TIMING_OUTLIER = 1.5
# The counters a frozen scene pins exactly, whatever the world is doing: the frame count, the copy-backs the
# pack asks for, and the program set it compiled.
EXACT_COUNTERS = ("windowFrames", "blits", "blittedMiB", "pipelineIdentities")

COUNTERS = (
    "windowFrames",
    "windowMs",
    "gpuFrames",
    "gpuMs",
    "encoders",
    "passChanged",
    "submit",
    "loadedMiB",
    "storedMiB",
    "depthAttachments",
    "depthLoadedMiB",
    "depthStoredMiB",
    "blits",
    "blittedMiB",
    "pipeline",
    "texture",
    "sampler",
    "buffer",
    "viewport",
    "scissor",
    "compiles",
    "compileMs",
    "pipelineIdentities",
    "pipelineKeys",
)

FIELD = re.compile(r"(\w+)=([0-9.]+)")


def probe_line(run: Path) -> str:
    path = run / "probe.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def counters(line: str) -> dict[str, float]:
    return {name: float(value) for name, value in FIELD.findall(line)}


def generation(line: str) -> str:
    """Which generation executed the arm, or "" where its line does not say."""
    found = re.search(r"executingGeneration=(\S+)", line)
    return found.group(1) if found else ""


def read_png(path: Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    """A PNG as width, height and one RGB triple a pixel.

    Only what a screenshot is: eight bits a channel, no interlacing. Anything else is refused
    rather than approximated, because a picture compared wrongly is worse than one not compared.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")

    at = 8
    width = height = depth = colour = 0
    idat = bytearray()
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or colour not in (2, 6) or interlace != 0:
                raise ValueError(f"unsupported PNG: depth {depth}, colour {colour}, interlace {interlace}")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        at += 12 + length

    channels = 3 if colour == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    pixels: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    at = 0
    for _ in range(height):
        filter_type = raw[at]
        line = bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - up_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
                nearest = (left, up, up_left)[distances.index(min(distances))]
                line[index] = (line[index] + nearest) & 0xFF
        previous = line
        for index in range(0, stride, channels):
            pixels.append((line[index], line[index + 1], line[index + 2]))

    return width, height, pixels


def flat_colour(png: tuple[int, int, list[tuple[int, int, int]]]) -> tuple[int, int, int] | None:
    """The one colour a capture that has nothing in it is made of, or None for a picture with anything in it.

    A screenshot of a locked, asleep or absent display is a single flat colour, and two of those compare as
    byte-identical - which is the strongest verdict this tool can print, about two pictures of nothing.
    Measured: every capture of two sessions was black, and the comparison below was run on them for two
    rounds before anybody looked at the file. So a flat capture is a fact about the instrument and is
    reported as one, rather than being compared.
    """
    pixels = png[2]
    if not pixels:
        return (0, 0, 0)

    first = pixels[0]
    for pixel in pixels:
        if pixel != first:
            return None

    return first


def compare_pictures(left: tuple[int, int, list[tuple[int, int, int]]],
                     right: tuple[int, int, list[tuple[int, int, int]]]) -> str:
    if left[0] != right[0] or left[1] != right[1]:
        return f"different sizes: {left[0]}x{left[1]} against {right[0]}x{right[1]}"

    total = 0
    moved = 0
    beyond = 0
    beyond_two = 0
    worst = 0
    worst_at = (0, 0)
    # The worst pixel and where it is, because that is the number a fixture's own acceptance test is
    # written against: a mean is what an animated scene moves, and a single region at 200 levels is
    # what a wrong attachment action looks like.
    for index, ((lr, lg, lb), (rr, rg, rb)) in enumerate(zip(left[2], right[2])):
        delta = max(abs(lr - rr), abs(lg - rg), abs(lb - rb))
        total += delta
        if delta:
            moved += 1
            if delta > 2:
                beyond_two += 1
        if delta > 8:
            beyond += 1
        if delta > worst:
            worst = delta
            worst_at = (index % left[0], index // left[0])
    count = max(1, len(left[2]))
    return (f"mean channel difference {total / count:.2f}, "
            f"{100 * moved / count:.2f}% of pixels differ at all, "
            f"{100 * beyond / count:.2f}% differ by more than 8, "
            f"{100 * beyond_two / count:.2f}% by more than 2, "
            f"worst {worst} at {worst_at[0]},{worst_at[1]}")


def main() -> int:
    # The harness's pre-flight question, asked of one file: is this capture a picture at all? A session that
    # cannot photograph its own screen cannot produce picture evidence, and it is cheaper to find that out
    # before four launches than after them.
    if len(sys.argv) == 3 and sys.argv[1] == "--capture-check":
        try:
            png = read_png(Path(sys.argv[2]))
        except (ValueError, OSError, zlib.error) as error:
            print(f"the capture could not be read: {error}", file=sys.stderr)
            return 5

        colour = flat_colour(png)
        if colour is not None:
            print(f"the capture is one flat colour ({colour[0]},{colour[1]},{colour[2]})", file=sys.stderr)
            return 3

        print(f"the capture has a picture in it: {png[0]}x{png[1]}")
        return 0

    if len(sys.argv) != 2:
        print(__doc__.strip().split("Usage: ")[1], file=sys.stderr)
        return 2

    out = Path(sys.argv[1])
    collected = {path.name: path for path in out.iterdir() if path.is_dir() and (path / "probe.txt").is_file()}
    # The first run asked for is the one the others are measured against, which is the order the
    # launcher recorded rather than any order of names: sorted, `elide` would precede `plain` and the
    # comparison would be printed upside down.
    order = out / "order.txt"
    if order.is_file():
        runs = [collected[name] for name in order.read_text(encoding="utf-8").split() if name in collected]
    else:
        runs = list(collected.values())
    if not runs:
        print(f"No collected runs under {out}.", file=sys.stderr)
        return 1

    measured = {run.name: counters(probe_line(run)) for run in runs}
    first = runs[0]
    baseline = measured[first.name]

    width = max(len("counter"), *(len(name) for name in measured))
    header = f"{'counter':<{width}}"
    for run in runs:
        header += f"  {run.name:>16}"
    if len(runs) > 1:
        header += f"  {'first against rest':>22}"
    print(header)

    for counter in COUNTERS:
        row = f"{counter:<{width}}"
        values = [measured[run.name].get(counter) for run in runs]
        for value in values:
            row += "  " + ("-" if value is None else f"{value:>16.1f}")
        if len(runs) > 1 and values[0] is not None:
            changes = [
                f"{100 * (value - values[0]) / values[0]:+.1f}%"
                for value in values[1:]
                if value is not None and values[0]
            ]
            row += f"  {', '.join(changes):>22}"
        print(row)

    # The arms of an A/B have to be the same scene, and the counters that say so are not the ones under
    # test: how many passes the frame opened and how many bytes it loaded are properties of the world, the
    # pack and the camera, not of the switch. Two arms of one configuration differ by well under a per cent
    # on them; an arm that differs by more is another scene, and its time column is not comparable with the
    # first arm's. Said as a refusal rather than as a footnote, because a drifted scene reads exactly like a
    # win - measured: an arm that drew the pack at 27 000 passes a frame with 511 217 loadedMiB against the
    # baseline's 93 943, which every other check here accepted.
    drift: list[str] = []
    # The counters that say "the same scene" are the ones no switch can move - but they are also the ones a
    # *generation* moves, and this comparison is used for exactly that A/B. Two arms that name different
    # executing generations open different numbers of native passes by design (this path opens one native
    # encoder per logical pass and a pass per clear, where Metal 3 reuses one encoder and folds the clear in),
    # so the check says so and stands aside rather than refusing the pair it cannot judge. The scene guard for
    # such a pair is the harness's own: same world, same pack, same target, same window.
    generations = {run.name: generation(probe_line(run)) for run in runs}
    named = {value for value in generations.values() if value}
    cross_generation = len(named) > 1
    if cross_generation:
        print()
        print("scene: " + ", ".join(f"{name}={value or 'unknown'}" for name, value in generations.items())
              + " - two generations executed, so the structural counters are expected to differ and the drift "
                "check is not applied to them; the scene guard for this pair is the harness's own target, pack "
                "and world checks")
    # Only counters no switch can move: `loadedMiB`, `storedMiB` and `blits` are what the attachment-traffic
    # and copy switches are *for*, so judging them here would refuse the very A/B they exist to decide.
    for counter in (() if cross_generation else ("renderPasses", "depthAttachments")):
        reference = measured[first.name].get(counter)
        if not reference:
            continue
        for run in runs[1:]:
            value = measured[run.name].get(counter)
            if value is None:
                continue
            change = 100 * (value - reference) / reference
            if abs(change) > SCENE_TOLERANCE:
                drift.append(f"{counter} of {run.name} is {change:+.1f}% against {runs[0].name}")

    # And the arms of one generation must have drawn the same frame, judged among themselves.
    #
    # This is the check the cross-generation A/B needed and did not have. A generation's own arms share its
    # binding structure, so the counters a *switch* cannot move are the counters a *scene* moves: how many
    # draws the frame made, how many textures and buffers it bound, how many bytes it loaded. Judging them
    # across generations would refuse the comparison by design (this path binds per pass and Metal 3 binds per
    # draw), so the judgment is made *within* each generation, where the structure is constant and only the
    # content can move. Measured, session run/perf-ab6: the two Metal 3 arms bound their textures to +0.2% and
    # drew to +0.3%, while the two Metal 4 arms differed by +12.2% of draws and +14.7% of texture bindings on
    # the same world, pack, target and window - and the comparer's own summary offered "+31.8% against the
    # first arm" for that pair, which is a content difference wearing the costume of a performance verdict.
    # What the frame's content is, in counters that mean the same thing on both generations and grow with what
    # the frame drew rather than with how many native calls it made. `pipeline`, `texture` and `buffer` look like
    # content and are not: Metal 3 counts a pipeline *change*, this path counts a pipeline *set per draw*, and the
    # texture and buffer counters are fills that include the re-fills every pipeline change causes. Measured, and
    # it is why this sentence exists: run/perf-ab6's two Metal 4 arms differ by +12.2% of `pipeline`, +14.7% of
    # `texture` and +15.1% of `buffer`, and their *frames* differ by +0.7% of draws (1110.2 against 1118.1 a
    # frame, all of it the shadow pass), by 20.55 passes a frame and by 2.33 clears a frame - identical to two
    # decimals. A guard built on those three counters refuses a pair of arms that drew the same frame.
    content_counters = ("loadedMiB", "storedMiB", "depthAttachments")
    by_generation: dict[str, list[str]] = {}
    for run in runs:
        value = generations[run.name] or "unknown"
        by_generation.setdefault(value, []).append(run.name)
    generation_drifted: list[str] = []
    for value, names in by_generation.items():
        if len(names) < 2:
            continue
        reference_name = names[0]
        for name in names[1:]:
            for counter, tolerance in ([(name, 0.0) for name in EXACT_COUNTERS]
                                       + [(name, CONTENT_TOLERANCE) for name in content_counters]):
                reference = measured[reference_name].get(counter)
                other = measured[name].get(counter)
                if reference is None or other is None:
                    continue
                change = 100 * (other - reference) / reference if reference else 0.0
                if abs(change) > tolerance:
                    generation_drifted.append(
                        f"{value}: {counter} of {name} is {change:+.1f}% against {reference_name}"
                        + ("" if tolerance else " (exact)"))
    if generation_drifted:
        drift.extend(generation_drifted)
        if len(by_generation) > 1:
            generation_drifted.append(
                "the arms of one generation did not draw the same frame, so no arm of it can be read against "
                "the other generation's in this session")

    # And a generation's own arms have to have run in the same *machine state*, which its time column says and
    # its counters do not. Measured, session run/vanilla-grid: one Metal 4 arm read 10.68 ms a frame against the
    # other's 2.46 - 4.2x, with 4.23 against 1.11 of its own commit feedback - while every structural counter
    # agreed to a tenth of a per cent, and nothing refused it, because a session with two generations in it
    # skips the structural check above by design. Section 115's answer to an arm like that is "discard the arm",
    # and a reader can only discard what is named: the arm is named here and the session is refused, because a
    # mean taken across an arm the machine spoiled is the reading this whole file exists to prevent.
    outliers: list[str] = []
    for value, names in by_generation.items():
        if len(names) < 2:
            continue
        per_frame = {}
        for name in names:
            frames = measured[name].get("windowFrames")
            millis = measured[name].get("windowMs")
            if frames:
                per_frame[name] = millis / frames
        if len(per_frame) < 2:
            continue
        fastest = min(per_frame.values())
        for name, rate in per_frame.items():
            if fastest > 0 and rate > TIMING_OUTLIER * fastest:
                outliers.append(
                    f"{value}: {name} read {rate:.2f} ms a frame against the fastest arm of its own generation's"
                    f" {fastest:.2f} ({rate / fastest:.2f}x), so the machine moved under it - section 115 says to"
                    f" discard this arm and not to average it")
    # And the window itself: a fullscreen arm renders the display's own mode, so the resolution is a scene
    # property the harness cannot pin with --width/--height and has to judge here. Measured: two arms of one
    # configuration photographed 1920x1200 and 3600x2338 - but only a capture with a picture in it is a
    # photograph of a window at all, so a flat one is left out of this check and reported as its own fault.
    captures: dict[str, tuple[int, int, list[tuple[int, int, int]]]] = {}
    unreadable: dict[str, str] = {}
    for run in runs:
        screen = run / "screen.png"
        if not screen.is_file():
            unreadable[run.name] = "no picture"
            continue
        try:
            captures[run.name] = read_png(screen)
        except (ValueError, OSError, zlib.error) as error:
            unreadable[run.name] = f"not read: {error}"

    flat: dict[str, tuple[int, int, int]] = {
        name: colour
        for name, png in captures.items()
        if (colour := flat_colour(png)) is not None
    }
    first_capture = captures.get(first.name)
    if first_capture is not None and first.name not in flat:
        first_size = first_capture[:2]
        for run in runs[1:]:
            capture = captures.get(run.name)
            if capture is None or run.name in flat:
                continue
            if capture[:2] != first_size:
                drift.append(
                    f"{run.name} was photographed at {capture[0]}x{capture[1]} against "
                    f"{first_size[0]}x{first_size[1]}, so the two arms did not render the same window"
                )

    if drift:
        print()
        print("scene drift: " + "; ".join(drift) + f" (scene tolerance {SCENE_TOLERANCE:.1f}%,"
              f" content tolerance {CONTENT_TOLERANCE:.1f}%)", file=sys.stderr)

    if outliers:
        print()
        print("arm outlier: " + "; ".join(outliers), file=sys.stderr)


    # The rate is the two numbers the probe printed divided by each other and not a second opinion:
    # bytes are the cost a change moves, and this is what the frame paid for them. A change that
    # lowers the bytes and leaves this where it was is a change to a counter and not to a frame.
    #
    # The GPU's own time is printed beside it and divided by the frames the driver answered for rather
    # than by the window, because the two are read at different moments: the window is counted when a
    # frame is committed and the GPU time arrives when the driver says a frame finished, three frames
    # later. The difference between the two rates is what the CPU and the presentation cost.
    print()
    for run in runs:
        counted = measured[run.name]
        frames = counted.get("windowFrames")
        millis = counted.get("windowMs")
        if not frames or not millis:
            print(f"{run.name}: no window time in the probe's line")
            continue
        rate = millis / frames
        change = ""
        baseline_ms = measured[first.name].get("windowMs")
        baseline_frames = measured[first.name].get("windowFrames")
        if len(runs) > 1 and run is not first and baseline_ms and baseline_frames:
            baseline = baseline_ms / baseline_frames
            change = f", {100 * (rate - baseline) / baseline:+.1f}% against {first.name}"
        gpu = ""
        gpu_frames = counted.get("gpuFrames")
        gpu_millis = counted.get("gpuMs")
        if gpu_frames and gpu_millis:
            gpu = f", {gpu_millis / gpu_frames:.2f} ms of GPU time a frame over {gpu_frames:.0f} answered frames"
        print(f"{run.name}: {rate:.2f} ms a frame, {1000 / rate:.1f} frames a second{change}{gpu}")

    print()
    for run in runs:
        line = probe_line(run)
        print(f"{run.name}: {line if line else 'no probe window collected'}")

    if len(runs) > 1:
        print()
        for run in runs[1:]:
            if first.name in unreadable or run.name in unreadable:
                print(f"picture, {first.name} against {run.name}: no picture on one side")
                continue
            if first.name in flat or run.name in flat:
                # Said as NOT COMPARABLE rather than as a number, because the number two flat captures
                # produce is "0.00% of pixels differ" - the strongest agreement this tool can report, from
                # two photographs of nothing. That is how this went unnoticed for two rounds.
                colour = flat.get(first.name, flat.get(run.name))
                print(f"picture, {first.name} against {run.name}: NOT COMPARABLE - the capture is one flat"
                      f" colour ({colour[0]},{colour[1]},{colour[2]}), so there is no picture to compare and"
                      f" no arm's screen was photographed")
                continue
            print(f"picture, {first.name} against {run.name}: "
                  f"{compare_pictures(captures[first.name], captures[run.name])}")

    if flat:
        print(f"picture evidence is void: {', '.join(sorted(flat))} captured a single colour, so no arm's "
              f"picture was photographed at all. A locked or asleep display captures black - unlock it, or "
              f"keep it awake, and run the session again.", file=sys.stderr)
        return 4

    if drift or outliers:
        # A drifted arm's time column is not comparable with the first arm's, and a refusal is the only
        # reading of that which cannot be mistaken for a result - and an arm the machine spoiled is the same
        # fault arriving through the clock instead of through the counters.
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
