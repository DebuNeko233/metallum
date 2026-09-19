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


def compare_pictures(first: Path, other: Path) -> str:
    if not first.is_file() or not other.is_file():
        return "no picture on one side"
    try:
        left = read_png(first)
        right = read_png(other)
    except (ValueError, OSError, zlib.error) as error:
        return f"not compared: {error}"
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
    for counter in ("renderPasses", "loadedMiB"):
        baseline = measured[runs[0].name].get(counter)
        if not baseline:
            continue
        for run in runs[1:]:
            value = measured[run.name].get(counter)
            if value is None:
                continue
            change = 100 * (value - baseline) / baseline
            if abs(change) > SCENE_TOLERANCE:
                drift.append(f"{counter} of {run.name} is {change:+.1f}% against {runs[0].name}")
    if drift:
        print()
        print("scene drift: " + "; ".join(drift) + f" (tolerance {SCENE_TOLERANCE:.1f}%)", file=sys.stderr)


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
            print(f"picture, {first.name} against {run.name}: "
                  f"{compare_pictures(first / 'screen.png', run / 'screen.png')}")

    if drift:
        # A drifted arm's time column is not comparable with the first arm's, and a refusal is the only
        # reading of that which cannot be mistaken for a result.
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
