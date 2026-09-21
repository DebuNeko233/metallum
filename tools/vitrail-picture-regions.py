#!/usr/bin/env python3
"""Say *where* in a frame two captures differ, not only by how much.

Why this exists
---------------
`tools/vitrail-performance-compare.py` answers "do these two pictures differ" with one global number, and a
global number cannot tell a sky that is a level brighter from a terrain that is, a cloud that moved from a cloud
that changed colour, or a HUD difference from either. The audit's sky/cloud residual is exactly that question -
Metal 4's overworld frame is *lighter* than Metal 3's, which is a claim about a region and cannot be settled by
a mean over the whole frame.

So each pixel is classified by the **reference arm's** colour into one of three regions, and every arm is read
against the reference class by class:

    cloud    near-white and low saturation: min channel >= 170 and max - min <= 40
    sky      blue-dominant: b >= g >= r, b >= 120 and b - r >= 25
    terrain  everything else - the control region, since a shading change that moved the ground too would not
             be a sky or cloud defect at all

The classification is on the reference and never on the arm under test, because a class decided per arm would
let the difference move a pixel from one class to another and then report both classes as unchanged. The
thresholds are the only judgement in the file and they are printed with the counts they produce, so a reader can
see whether "sky" is really the sky in that frame before believing a per-class number.

A row-band profile is printed beside the classes: the mean difference per tenth of the frame's height, which
localises a difference to the top or the bottom of a frame without depending on a colour threshold at all.

Usage
-----
  tools/vitrail-picture-regions.py run/j1-sky [--reference NAME]
"""
import argparse
import pathlib
import struct
import sys
import zlib


def read_png(path: pathlib.Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    """A PNG as width, height and one RGB triple a pixel - eight bits a channel, no interlacing.

    The same reader and the same refusals as the comparison's, and separate on purpose: this file is about a
    region and that one is about a whole frame, so neither may quietly become a dependency of the other.
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


def classify(pixel: tuple[int, int, int]) -> str:
    """Which region a reference pixel belongs to, by the thresholds documented at the top of this file."""
    red, green, blue = pixel
    if min(pixel) >= 170 and max(pixel) - min(pixel) <= 40:
        return "cloud"
    if blue >= green >= red and blue >= 120 and blue - red >= 25:
        return "sky"
    return "terrain"


def mean(pixels, index) -> float:
    return sum(pixel[index] for pixel in pixels) / len(pixels) if pixels else 0.0


def row_bands(height: int, deltas: list[int], width: int, bands: int = 10) -> list[float]:
    """The mean absolute difference of each tenth of the frame, top band first."""
    out = []
    for band in range(bands):
        first, last = band * height // bands, (band + 1) * height // bands
        values = deltas[first * width:last * width]
        out.append(sum(values) / len(values) if values else 0.0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", help="a session directory holding one directory per arm")
    parser.add_argument("--reference", help="the arm to classify against (default: the first in order.txt)")
    args = parser.parse_args()

    session = pathlib.Path(args.session)
    order_file = session / "order.txt"
    if not session.is_dir():
        raise SystemExit(f"picture regions: {session} is not a directory")
    if order_file.is_file():
        order = [name for name in order_file.read_text(encoding="utf-8").split() if name]
    else:
        order = sorted(path.name for path in session.iterdir() if path.is_dir())

    pictures = {}
    for name in order:
        shot = session / name / "client.png"
        if not shot.is_file():
            shot = session / name / "screen.png"
        if not shot.is_file():
            print(f"arm {name}: no screen.png, skipped")
            continue
        try:
            pictures[name] = read_png(shot)
        except ValueError as refusal:
            print(f"arm {name}: {refusal}, skipped")
    if not pictures:
        raise SystemExit("picture regions: no arm in this session left a readable picture")

    reference_name = args.reference if args.reference in pictures else order[0]
    reference = pictures[reference_name]
    width, height, reference_pixels = reference
    print(f"reference {reference_name}: {width}x{height}, {len(reference_pixels)} pixels")
    classes = [classify(pixel) for pixel in reference_pixels]
    counts = {name: classes.count(name) for name in ("cloud", "sky", "terrain")}
    for name, count in counts.items():
        share = 100.0 * count / len(classes)
        pixels = [pixel for pixel, kind in zip(reference_pixels, classes) if kind == name]
        print(f"  {name:<8} {count:>8} px  {share:5.1f} %  reference mean"
              f" ({mean(pixels, 0):6.1f}, {mean(pixels, 1):6.1f}, {mean(pixels, 2):6.1f})")

    for name, (arm_width, arm_height, pixels) in pictures.items():
        if name == reference_name:
            continue
        if (arm_width, arm_height) != (width, height):
            print(f"arm {name}: photographed at {arm_width}x{arm_height} against"
                  f" {width}x{height}, so it cannot be read against the reference")
            continue
        deltas = [max(abs(a - b) for a, b in zip(arm, base))
                  for arm, base in zip(pixels, reference_pixels)]
        print(f"arm {name} against {reference_name}:")
        print(f"  whole frame   mean |delta| {sum(deltas) / len(deltas):5.2f}"
              f"   above 8 levels {100.0 * sum(1 for d in deltas if d > 8) / len(deltas):5.2f} %")
        for kind in ("sky", "cloud", "terrain"):
            chosen = [index for index, value in enumerate(classes) if value == kind]
            if not chosen:
                continue
            arm_pixels = [pixels[index] for index in chosen]
            base_pixels = [reference_pixels[index] for index in chosen]
            kind_deltas = [deltas[index] for index in chosen]
            print(f"  {kind:<8} {len(chosen):>8} px  mean |delta| {sum(kind_deltas) / len(kind_deltas):5.2f}"
                  f"  above 8 levels {100.0 * sum(1 for d in kind_deltas if d > 8) / len(kind_deltas):5.2f} %"
                  f"   reference ({mean(base_pixels, 0):6.1f}, {mean(base_pixels, 1):6.1f},"
                  f" {mean(base_pixels, 2):6.1f})  arm ({mean(arm_pixels, 0):6.1f},"
                  f" {mean(arm_pixels, 1):6.1f}, {mean(arm_pixels, 2):6.1f})")
        bands = row_bands(height, deltas, width)
        print("  bands top to bottom (mean |delta| per tenth): "
              + " ".join(f"{value:.2f}" for value in bands))
    return 0


if __name__ == "__main__":
    sys.exit(main())
