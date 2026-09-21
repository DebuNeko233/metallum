#!/usr/bin/env python3
"""Classify a Metal 4 session's frames by what they waited on, one frame at a time.

Why this exists
---------------
A percentile summary answers "where did the window's frames land" and not "were they
one population or two". Blocker 16 is exactly that question: this path's arms of one
configuration have been measured up to 1.5x apart while the reference repeats to
1.10x, and the three candidate explanations - the frame's work, the machine's load, the
pacing resource - cannot be separated from a P50 and a P95. So the frame path writes one
line a frame (`-Dmetallum.metal4FrameTrace=true`) and one a submission, and this reads
them.

What it reads
-------------
  M4_FRAME frame=.. slots=.. slot=.. submission=.. wallUs=.. slotWaitUs=..
           drawableWaitUs=.. encodeUs=.. passes=.. encoders=.. tables=.. draws=..
  M4_FRAME_COMMIT submission=.. commitMs=..
  Metal 4 trace: end pass 'LABEL' ..        (only when -Dmetallum.metal4Trace=true)

The frame's own submission's GPU interval is paired by ordinal (the ring commits one
command buffer at a time and the driver reports each commit once, in order), so a frame
line carries the interval of *its own* submission rather than of whichever one arrived
last.

A frame kind can also be *named* rather than only counted. `-Dmetallum.metal4Trace=true`
makes every pass write its own `end pass 'LABEL'` line, and those lines precede the frame's
own `M4_FRAME` line in the same order the frame encoded them, so the labels between two
frame lines are that frame's passes. With them present each kind is printed as the set it is,
and each non-modal kind as what it has over the modal one - which is what turns "a 340 ms
stretch with two passes absent" into "the stretch with the two particle passes absent".

What it prints
--------------
Per arm: the wall distribution as a histogram with its buckets, the waits as totals and
percentiles, and the frames split into the two populations section 28 asks for - A, the
frames that did not wait for their ring slot, and B, the frames that did - each with its
own wall, drawable wait and driver interval, so the populations can be read against the
waits instead of assumed from them.

Then the same figures pooled by ring depth, which is the experiment: one slot forces
every frame to wait for the previous submission, three let the CPU run ahead.

Usage
-----
  tools/metal4-pacing-analysis.py run/m4-pacing [--histogram-bucket-us 2000]
"""
import argparse
import pathlib
import re
import statistics
import sys
from collections import Counter

FIELDS = ("frame", "slots", "slot", "submission", "wallUs", "slotWaitUs", "drawableWaitUs",
          "encodeUs", "passes", "encoders", "tables", "draws")

FRAME_RE = re.compile(r"M4_FRAME " + " ".join(rf"{field}=(-?\d+)" for field in FIELDS))
COMMIT_RE = re.compile(r"M4_FRAME_COMMIT submission=(\d+) commitMs=([\d.]+)")
PASS_RE = re.compile(r"end pass '([^']*)'")


def percentile(values, quantile):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(quantile * (len(ordered) - 1)))))
    return ordered[index]


def read_arm(path, budget):
    """The frames of one arm, and the frames of its probe window.

    The window is the last `budget` frames written *before* the probe's own report line, which is where the
    window closed: the client keeps drawing for a second or two after that while the harness photographs and
    stops it, and a whole-run histogram would mix the loading screens, the settle and the window into one shape.
    """
    frames = []
    commits = {}
    malformed = 0
    report_at = None
    pending = []
    for line in path.read_text(errors="replace").splitlines():
        if "frame-probe " in line and "/{} ".format(budget) in line:
            report_at = len(frames)
        if "M4_FRAME_COMMIT" in line:
            match = COMMIT_RE.search(line)
            if match:
                commits[int(match.group(1))] = float(match.group(2))
            continue
        if "M4_FRAME " not in line:
            # A pass's own line, when the per-pass trace is on. It is written while the pass is being
            # closed, so the labels between two frame lines belong to the frame the later line closes.
            passed = PASS_RE.search(line)
            if passed:
                pending.append(passed.group(1))
            continue
        match = FRAME_RE.search(line)
        if not match:
            malformed += 1
            continue
        frame = {field: int(value) for field, value in zip(FIELDS, match.groups())}
        frame["labels"] = pending
        pending = []
        frames.append(frame)
    for frame in frames:
        frame["commitMs"] = commits.get(frame["submission"], -1.0)
    end = report_at if report_at else len(frames)
    return frames, frames[max(0, end - budget):end], commits, malformed


def describe(frames, weight):
    walls = [frame["wallUs"] / 1000.0 for frame in frames if frame["wallUs"] >= 0]
    commits = [frame["commitMs"] for frame in frames if frame["commitMs"] > 0.0]
    draws = [frame["draws"] for frame in frames]
    return {
        "n": len(frames),
        "wallP50": percentile(walls, 0.50),
        "wallP95": percentile(walls, 0.95),
        "wallMean": statistics.fmean(walls) if walls else 0.0,
        "drawableMean": statistics.fmean([frame["drawableWaitUs"] / 1000.0 for frame in frames]) if frames else 0.0,
        "commitMean": statistics.fmean(commits) if commits else 0.0,
        "commitN": len(commits),
        "drawsMean": statistics.fmean(draws) if draws else 0.0,
    }


def correlation(pairs):
    if len(pairs) < 8:
        return 0.0
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in pairs)
    denominator = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return 0.0 if denominator == 0 else numerator / denominator


def histogram(walls, bucket_us):
    buckets = {}
    for wall in walls:
        if wall < 0:
            continue
        buckets[int(wall * 1000 // bucket_us)] = buckets.get(int(wall * 1000 // bucket_us), 0) + 1
    return buckets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session", help="a run directory holding one directory per arm")
    parser.add_argument("--histogram-bucket-us", type=int, default=2000)
    parser.add_argument("--frames", type=int, default=600, help="the probe window each arm was measured over")
    parser.add_argument("--wait-threshold-us", type=int, default=500,
                        help="how long a wait has to be to count as a real one: a ring that is never really "
                             "waited on still reports a few hundred nanoseconds of bookkeeping")
    args = parser.parse_args()

    session = pathlib.Path(args.session)
    if not session.is_dir():
        raise SystemExit(f"pacing analysis: {session} is not a directory")

    arms = []
    for arm_dir in sorted(path for path in session.iterdir() if path.is_dir()):
        log = arm_dir / "latest.log"
        if not log.is_file():
            continue
        frames, window, commits, malformed = read_arm(log, args.frames)
        if not frames:
            print(f"arm {arm_dir.name}: no M4_FRAME lines - is -Dmetallum.metal4FrameTrace=true in that arm?")
            continue
        arms.append((arm_dir.name, frames, window, commits, malformed))

    if not arms:
        raise SystemExit("pacing analysis: no arm in this session wrote a per-frame line")

    for name, frames, window, commits, malformed in arms:
        slots = frames[0]["slots"]
        console = sys.stdout
        walls = [frame["wallUs"] / 1000.0 for frame in window if frame["wallUs"] >= 0]
        waited = [frame for frame in window if frame["slotWaitUs"] >= args.wait_threshold_us]
        free = [frame for frame in window if frame["slotWaitUs"] < args.wait_threshold_us]
        summary = describe(window, 1.0)
        print(f"arm {name}: slots={slots} frames={summary['n']} of {len(frames)} traced"
              f" submissions={len(commits)} malformedLines={malformed}")
        shifted = [(window[index]["wallUs"] / 1000.0, window[index - 1]["drawableWaitUs"] / 1000.0)
                   for index in range(1, len(window))]
        print(f"  corr(wall(N), drawableWait(N-1)) = {correlation(shifted):+.3f}"
              f"   corr(wall(N), drawableWait(N)) = "
              + f"{correlation([(frame['wallUs'] / 1000.0, frame['drawableWaitUs'] / 1000.0) for frame in window]):+.3f}"
              + "   (the wait a frame pays is inside its *own* period, so the first is the paced pairing)")
        print(f"  wall ms      P50 {summary['wallP50']:.2f}  P95 {summary['wallP95']:.2f}"
              f"  mean {summary['wallMean']:.2f}")
        print(f"  slot wait    total {sum(frame['slotWaitUs'] for frame in window) / 1000.0:.1f} ms"
              f"  frames that really waited {len(waited)} of {len(window)}"
              f"  p50 of those {percentile([f['slotWaitUs'] / 1000.0 for f in waited], 0.50):.2f} ms")
        print(f"  drawable wait mean {summary['drawableMean']:.2f} ms"
              f"  encode mean {statistics.fmean([f['encodeUs'] / 1000.0 for f in window]):.2f} ms")
        print(f"  driver interval  mean {summary['commitMean']:.2f} ms"
              f"  P50 {percentile([f['commitMs'] for f in window if f['commitMs'] > 0], 0.50):.2f}"
              f"  P95 {percentile([f['commitMs'] for f in window if f['commitMs'] > 0], 0.95):.2f}"
              f"  over {summary['commitN']} of {len(window)} frames")
        print(f"  draws a frame mean {summary['drawsMean']:.1f}")
        for label, population in (("A no real slot wait", free), ("B real slot wait", waited)):
            if not population:
                continue
            figures = describe(population, 1.0)
            print(f"  population {label}: frames={figures['n']} wallMeanMs={figures['wallMean']:.2f}"
                  f" wallP50Ms={figures['wallP50']:.2f} drawableMeanMs={figures['drawableMean']:.2f}"
                  f" commitMeanMs={figures['commitMean']:.2f} drawsMean={figures['drawsMean']:.1f}")
        # **The content decomposition, from the trace and not from a fit.** A frame's pass count is not the
        # same on every frame: measured on the no-pack scene this path's frame is one count in the steady state,
        # six passes more on the frame that coincides with a 20 Hz client tick and two fewer in a stretch, so a
        # window's total is `steady*N + tick*T - 2*S` and two arms whose frame rates differ hold different
        # numbers of each. The trace names the kind of every frame, so the coefficients are counted here rather
        # than fitted - which is what the earlier attempt could not do over three arms whose tick counts spanned
        # only 10%.
        kinds = {}
        for frame in window:
            kinds.setdefault(frame["passes"], []).append(frame)
        ordered = sorted(kinds.items(), key=lambda pair: -len(pair[1]))
        if len(ordered) >= 2:
            steady_value, steady_frames = ordered[0]
            line = " ".join(f"passes={value}:{len(group)}"
                            for value, group in sorted(kinds.items(), key=lambda pair: pair[0]))
            print(f"  pass-count decomposition: {line}"
                  f"  (modal {steady_value} on {len(steady_frames)} frames,"
                  f" mean {statistics.fmean([frame['passes'] for frame in window]):.2f},"
                  f" total {sum(frame['passes'] for frame in window)})")
            for value, group in sorted(kinds.items(), key=lambda pair: pair[0]):
                if value == steady_value:
                    continue
                extra = value - steady_value
                print(f"    frames at {value} passes: {len(group)}"
                      f"  ({extra:+d} against the modal, worth {extra * len(group):+d} passes in this window)")
            # What each kind *is*, when the per-pass trace was on beside the frame trace: the passes a kind
            # has that the modal kind does not, and the passes it lacks. A count says a kind is two passes
            # short; only the labels say which two, and a frame kind is not explained until they are named.
            named = {value: Counter(group[0]["labels"]) for value, group in kinds.items() if group[0]["labels"]}
            if steady_value in named:
                modal = named[steady_value]
                print(f"  pass kinds, named from the trace (what this kind has over the modal one;"
                      f" {len(named)} of {len(kinds)} kinds carry the per-pass trace):")
                for value in sorted(kinds):
                    if value not in named:
                        continue
                    shape = named[value]
                    added = shape - modal
                    missing = modal - shape
                    detail = []
                    if added:
                        detail.append("has " + ", ".join(name if count == 1 else f"{name} x{count}"
                                                          for name, count in sorted(added.items())))
                    if missing:
                        detail.append("lacks " + ", ".join(name if count == 1 else f"{name} x{count}"
                                                            for name, count in sorted(missing.items())))
                    print(f"    {value} passes over {len(kinds[value])} frames: "
                          + ("; ".join(detail) if detail else "the modal kind itself"))
        buckets = histogram(walls, args.histogram_bucket_us)
        top = sorted(buckets.items())[:16]
        span = args.histogram_bucket_us / 1000.0
        print("  wall histogram (ms bucket -> frames): "
              + " ".join(f"{start * span:.0f}-{(start + 1) * span:.0f}:{count}" for start, count in top)
              + (" ..." if len(buckets) > len(top) else ""))

    by_slots = {}
    for name, frames, window, commits, _ in arms:
        by_slots.setdefault(window[0]["slots"], []).extend(window)
    print("")
    print("pooled by ring depth (the experiment: one slot forces the wait, three let the CPU run ahead)")
    for slots in sorted(by_slots):
        frames = by_slots[slots]
        summary = describe(frames, 1.0)
        waited = [frame for frame in frames if frame["slotWaitUs"] > 0]
        print(f"  slots={slots}: frames={summary['n']} wallP50={summary['wallP50']:.2f}"
              f" wallP95={summary['wallP95']:.2f} wallMean={summary['wallMean']:.2f}"
              f" drawableMean={summary['drawableMean']:.2f} commitMean={summary['commitMean']:.2f}"
              f" framesWithSlotWait={len(waited)}")
    print("")
    print("Read the two pooled lines against each other and not against a target: what the classification")
    print("says is whether a depth's periods are one population or two, and what each population waited on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
