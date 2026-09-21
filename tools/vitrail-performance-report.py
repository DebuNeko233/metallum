#!/usr/bin/env python3
"""Track G's unified report: one session's arms as machine-readable JSON.

Section 45 of the long-term plan asks for a report that carries the repository SHAs, the machine and OS, the
display mode, the target, the pack, the preset and the render scale, and then the arm's wall stats, CPU stats,
native census and structural census. Until this tool that report was a set of log lines spread over a session's
arm directories, readable by a person and by nothing else - and every claim in the programme's documents was
transcribed out of them by hand.

What this reads, and nothing else:

    <session>/<arm>/probe.txt        the frame probe's lines: the window, the pacing distribution, the native
                                     call census and the structural counters
    <session>/<arm>/latest.log       the arm's own log: the pack and the target it drew, the backend it came up
                                     on, the command generation that executed, and the one-a-second censuses
                                     (shadow, mipmap, feedback, bridge, load clock)
    <session>/display-mode-before.txt  the display's mode when the session started
    <session>/order.txt              the arms in the order they ran

Nothing is computed from a comparison: each arm is reported as it was measured, and a caller that wants a
difference takes two arms. Fields a session does not carry are absent rather than zero.

Usage: vitrail-performance-report.py <session dir> [more session dirs] [--out FILE] [--metallum SHA] [--vitrail SHA]
"""
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

# The probe's own field names, grouped as section 45 groups them. Anything not listed is carried under
# "other" rather than dropped, because a counter added to the probe should appear here without an edit.
STRUCTURAL = ("encoders", "passChanged", "submit", "passFullSize", "passSmaller", "passSizes",
              "loadedMiB", "storedMiB", "depthAttachments", "depthLoadedMiB", "depthStoredMiB",
              "blits", "blittedMiB")
NATIVE = ("pipeline", "texture", "sampler", "buffer", "viewport", "scissor", "depthBias",
          "pipelineIdentities", "pipelineKeys", "compiles", "compileMs",
          "unarmedCompiles", "unarmedCompileMs", "unarmedCompileMaxMs",
          "unarmedRenderCompiles", "unarmedRenderCompileMs",
          "unarmedFunctions", "unarmedFunctionMs", "unarmedFunctionMaxMs",
          "unarmedRenderFunctions", "unarmedRenderFunctionMs")
CPU = ("frameCpuMs", "allocKiB", "windowTicks", "framesPerTick")
PACING = ("wallP50", "wallP95", "wallP99", "wallMax", "wallMaxAt",
          "gpuP50", "gpuP95", "gpuP99", "gpuMax", "gpuMs")
SESSION_FIELDS = ("windowFrames", "windowMs", "gpuFrames", "selectedGeneration", "executingGeneration")

# The two instrumented waits, read as their own group and REMOVED from the text before the flat scan below:
# their lines carry `calls`, `p50`, `p95`, `max` and `total`, and a flat scan that left them in would put a
# wait's p50 beside the frame's wallP50 under a name that looks like the frame's.
WAITS = re.compile(r"frame-probe waits drawable calls=(\d+) p50=([\d.]+)ms p95=([\d.]+)ms max=([\d.]+)ms "
                   r"total=([\d.]+)ms; submitWindow calls=(\d+) p50=([\d.]+)ms p95=([\d.]+)ms max=([\d.]+)ms "
                   r"total=([\d.]+)ms")

# The one-a-second censuses, each keyed by the first words of its line so a rename shows up as a missing field
# rather than as a wrong number.
CENSUS = {
    "shadow_walk": re.compile(r"Shadow walk: (\d+) walks \(([\d.]+) a second\), kept (\d+) a walk, "
                              r"drew (\d+) a walk, (\d+) loaded, terrain=(\w+) culling=([A-Z_ ]+)"),
    "shadow_casters": re.compile(r"Shadow casters: (\d+) frames gathered, ([\d.]+) entities and "
                                 r"([\d.]+) block entities"),
    "shadow_draws": re.compile(r"Shadow map: the opaque world was drawn into it (\d+) times in the last "
                               r"(\d+) frames"),
    "mip_chains": re.compile(r"Mip chains: (\d+) reduced over (\d+) ms \(([\d.]+) a second\), (\d+) levels "
                             r"\(([\d.]+) a chain\), (\d+) pixels \(([\d]+) a frame at ([\d.]+) a second\)"
                             r"(?:, by target ([^\n]*))?"),
    "feedback_copies": re.compile(r"Feedback copies: (\d+) copies of ([\d.]+) MiB in the last (\d+) ms, "
                                  r"([\d.]+) copies and ([\d.]+) MiB a second"),
    "module_cache": re.compile(r"Module cache: (\d+) units served, (\d+) built by the compiler, (\d+) and "
                               r"(\d+) since this launch, ([\d.]+) MB"),
    "warmup": re.compile(r"(\d+) of (\d+) leftover pipelines compiled ahead of their first draw, (\d+) ms"),
    "target_copies": re.compile(r"(\d+) targets are copied back from their far half at the end of every "
                                r"frame[^:]*: \[([^\]]*)\](.*)"),
    "render_scale": re.compile(r"render scale is (\d+)%"),
    "target_drawn": re.compile(r"Drawing (\S+) from (\S+) for (\S+), at (\d+)x(\d+), (\d+) full screen passes"),
    "backend": re.compile(r"Using graphics backend (\w+)"),
    "metal_preference": re.compile(r"Vitrail Metal preference: ([^,]*)(?:,|$)"),
}


def probe_fields(text: str) -> dict[str, str]:
    """Every `name=value` the probe printed, last value winning: a session's later window is the later one.

    The value runs to the next space rather than to the next character outside an identifier: `passSizes` is a
    comma-separated list of `WxH:count` and a narrower pattern read it as the first size alone, silently
    dropping every other pass size in the window.
    """
    fields: dict[str, str] = {}
    for name, value in re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", text):
        fields[name] = value
    return fields


def number(value: str) -> object:
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def censuses(text: str) -> dict[str, object]:
    found: dict[str, object] = {}
    for name, pattern in CENSUS.items():
        matches = pattern.findall(text)
        if not matches:
            continue
        groups = matches[-1]
        if isinstance(groups, str):
            # One group: `findall` hands back the group's own string rather than a one-tuple, and reading it as
            # a tuple of characters is what turned "Metal" into a list of five letters.
            groups = (groups,)
        if name == "target_copies":
            found[name] = {"targets": int(groups[0]), "which": groups[1].strip(),
                           "unread": ("read by nothing" in groups[2])}
        elif len(groups) == 1:
            found[name] = number(groups[0])
        else:
            found[name] = [number(one) for one in groups]
    return found


def machine() -> dict[str, str]:
    read = lambda *command: subprocess.run(command, capture_output=True, text=True).stdout.strip()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "cpu": read("sysctl", "-n", "machdep.cpu.brand_string") if platform.system() == "Darwin" else "",
        "python": platform.python_version(),
    }


def display_mode(session: Path) -> str:
    before = session / "display-mode-before.txt"
    return before.read_text(encoding="utf-8").strip() if before.is_file() else ""


def source_recorded(arm: Path) -> dict[str, str]:
    """The revision the arm recorded, and whether the worktree was that revision.

    Written by the harness beside `load.txt` and for the same reason: `--metallum` and `--vitrail` on this tool's
    own command line are an assertion, and a session measured with a repository's sources put back to an earlier
    commit - which is how the acceptance's own baseline was re-measured in the machine state the head was read in -
    would carry the head's SHA and read as a session of the wrong code. Absent for every arm older than the file.
    """
    path = arm / "source-revision.txt"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        label, _, rest = line.partition(" ")
        rest = rest.strip()
        if not label or not rest:
            continue
        if "-" in label:
            # A group line: `<repo>-<source|tools> <paths that differ from it, or clean>`.
            repository, _, group = label.partition("-")
            values[repository + "_" + group.replace("-", "_")] = rest
            continue
        revision, _, branch = rest.partition(" ")
        values[label] = revision
        if branch.strip():
            values[label + "_branch"] = branch.strip()
    return values


def arm_report(arm: Path) -> dict[str, object]:
    probe = " ".join((arm / "probe.txt").read_text(encoding="utf-8", errors="replace").split()) \
        if (arm / "probe.txt").is_file() else ""
    log = (arm / "latest.log").read_text(encoding="utf-8", errors="replace") \
        if (arm / "latest.log").is_file() else ""
    waits = WAITS.search(" ".join(probe.split()))
    fields = probe_fields(WAITS.sub("", probe))

    report: dict[str, object] = {"arm": arm.name, "measured": bool(probe)}
    if waits:
        report["waits"] = {
            "drawable": {"calls": number(waits.group(1)), "p50": number(waits.group(2)),
                         "p95": number(waits.group(3)), "max": number(waits.group(4)),
                         "total": number(waits.group(5))},
            "submitWindow": {"calls": number(waits.group(6)), "p50": number(waits.group(7)),
                             "p95": number(waits.group(8)), "max": number(waits.group(9)),
                             "total": number(waits.group(10))},
        }
    for group, names in (("session", SESSION_FIELDS), ("pacing", PACING), ("cpu", CPU),
                         ("native", NATIVE), ("structural", STRUCTURAL)):
        values = {name: number(fields[name]) for name in names if name in fields}
        if values:
            report[group] = values

    # Anything the probe printed that the lists above do not name, kept rather than dropped: a counter added
    # to the probe should land in this report without an edit here, and a reader should see it.
    known = set(SESSION_FIELDS) | set(PACING) | set(CPU) | set(NATIVE) | set(STRUCTURAL)
    other = {name: number(value) for name, value in fields.items() if name not in known}
    if other:
        report["other"] = other

    # The window's tail against its own P99. A ratio near one is an ordinary distribution and a large one is a
    # frame the environment put in the window - measured across this programme's eighty-five recorded arms the
    # median is 1.06, and the two arms above seven are both its own instrument experiments, one of which was a
    # readback landing inside the window it was measuring and the other an occluded client that paused. It is
    # reported rather than refused because a single stall is not what makes a window invalid: what a reader needs
    # is to see it before believing a P99.
    pacing = report.get("pacing")
    if isinstance(pacing, dict) and pacing.get("wallP99"):
        pacing["wallTail"] = round(pacing["wallMax"] / pacing["wallP99"], 2)

    recorded = source_recorded(arm)
    if recorded:
        report["source"] = recorded

    report["census"] = censuses(log)
    load = arm / "load.txt"
    if load.is_file():
        report["machine_at_arm"] = " ".join(load.read_text(encoding="utf-8").split())
    return report


def session_report(session: Path) -> dict[str, object]:
    order = [line.strip() for line in (session / "order.txt").read_text(encoding="utf-8").splitlines()
             if line.strip()] if (session / "order.txt").is_file() else []
    arms = [arm_report(session / name) for name in order]
    if not arms:
        arms = [arm_report(arm) for arm in sorted(p for p in session.iterdir() if p.is_dir())]

    # The distinct sources the arms recorded, with the arms that shared each. Normally one entry: a session whose
    # arms recorded two is a session that measured two revisions of the code on purpose - a baseline's own sources
    # put back and run beside the head, which is the only way a reading is comparable across machine states - and a
    # reader has to see which arm was which before reading any difference between them.
    sources: dict[tuple[str, str, str, str], list[str]] = {}
    for one in arms:
        source = one.get("source") if isinstance(one, dict) else None
        if not isinstance(source, dict):
            continue
        key = (source.get("metallum", ""), source.get("metallum_source", ""),
               source.get("vitrail", ""), source.get("vitrail_source", ""))
        sources.setdefault(key, []).append(str(one.get("arm", "")))

    recorded = [{"metallum": key[0], "metallum_source": key[1], "vitrail": key[2], "vitrail_source": key[3],
                 "arms": names} for key, names in sources.items()]

    return {
        "session": session.name,
        "display_mode": display_mode(session),
        "order": order,
        "arms": arms,
        "source_recorded": recorded,
    }


def main() -> int:
    argv = sys.argv[1:]
    out = None
    shas = {"metallum": "", "vitrail": ""}
    sessions: list[Path] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--out":
            out = Path(argv[index + 1]); index += 2
        elif argument == "--metallum":
            shas["metallum"] = argv[index + 1]; index += 2
        elif argument == "--vitrail":
            shas["vitrail"] = argv[index + 1]; index += 2
        else:
            sessions.append(Path(argument)); index += 1

    if not sessions:
        raise SystemExit(__doc__)

    document = {
        "schema": "vitrail-performance-report/1",
        "repositories": shas,
        "machine": machine(),
        "sessions": [session_report(session) for session in sessions],
    }

    text = json.dumps(document, indent=2, sort_keys=False)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out} with {sum(len(one['arms']) for one in document['sessions'])} arm(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
