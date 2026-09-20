#!/usr/bin/env python3
"""Pins the Metal 4 cold-probe harness, because a harness that quietly stops measuring is worse than none.

The intermittent capability probe is the one thing blocking Metal 4 AUTO, and the only instrument that can
measure a per-process distribution is a process that does nothing else. Three lessons were paid for building
it, and each is a way a later edit could break the harness while it still ran:

  - the probe draws with the engine's built-in pipelines, so a standalone process has to hand their device
    over before probing. Measured: without it every probe fails at stage `exception` with
    `MTLBuiltinPipelines.device is null`, which reads as a device fault and is not one;
  - the results are a distribution over processes, so the two populations are counted apart - one probe per
    fresh JVM against repeated probes in one JVM. A harness that ran only one of them could not tell cold
    first use from anything else, which is the whole question;
  - the answer is one machine-readable line per attempt. A harness whose output has to be parsed out of a
    log is a harness nobody runs thirty times.

This file checks the shape and not the numbers: what the harness prints is data, and only the report may
claim a rate.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "metal4-cold-probe.sh"
PROBE = ROOT / "tools" / "metal4-cold-probe" / "Metal4ColdProbe.java"

for path in (SCRIPT, PROBE):
    if not path.is_file():
        raise SystemExit(f"cold-probe harness: {path.relative_to(ROOT)} is missing, so the per-process "
                         "distribution the AUTO blocker needs cannot be measured at all")

script = SCRIPT.read_text(encoding="utf-8")
probe = PROBE.read_text(encoding="utf-8")

# --- the two populations, asked for by name and defaulted to something worth running -------------------
for needle, why in (
    ("--cold-runs", "the harness cannot be told how many separate processes to probe, so the cold "
                    "population - the one the intermittent fault lives in - is not selectable"),
    ("--warm-runs", "the harness cannot be told how many probes to repeat in one process, so there is no "
                    "control for cold first use"),
    ('--mode) mode="$2"; shift 2 ;;',
     "the harness cannot be told whether to measure the fault itself (one attempt) or the path the "
     "capability record reads (with its retry), so one of the two questions goes unanswered"),
    ('--probes-per-process) probes_per_process="$2"; shift 2 ;;',
     "the harness cannot be told to run more than one probe in a cold process, so a process that is bad and a "
     "draw that went wrong cannot be told apart - which is the question a cold-only fault turns on"),
    ("--out", "the harness cannot be asked to keep its raw lines, so a run's evidence cannot be re-read"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

cold_default = re.search(r"^cold_runs=(\d+)$", script, re.MULTILINE)
warm_default = re.search(r"^warm_runs=(\d+)$", script, re.MULTILINE)
if cold_default is None or warm_default is None:
    raise SystemExit("cold-probe harness: one of the two populations has no default, so a bare run "
                     "measures something the reader cannot name")
if int(cold_default.group(1)) < 30:
    raise SystemExit(
        f"cold-probe harness: the default cold runs are {cold_default.group(1)}, and the plan asks for at "
        "least 30 processes - at two failures in seventy a smaller default would usually measure nothing"
    )
if int(warm_default.group(1)) < 20:
    raise SystemExit(
        f"cold-probe harness: the default warm runs are {warm_default.group(1)}, and the plan asks for at "
        "least 20 repeated probes in one process"
    )
if "java -cp" not in script or "runClient" in script or "gradlew runClient" in script:
    raise SystemExit("cold-probe harness: the harness is not starting a bare JVM, so it is not measuring a "
                     "cold process - a client launch is the seventy seconds this exists to avoid")

# --- the built-in pipelines, which is the lesson the first run paid for ---------------------------------
if "MTLBuiltinPipelines.init(device)" not in probe:
    raise SystemExit(
        "cold-probe harness: the probe no longer hands the built-in pipelines their device before probing, "
        "so every attempt will fail at stage `exception` with a null device field - which reads as a device "
        "fault and is an omission in the harness"
    )
if "MTLBuiltinPipelines.close()" not in probe:
    raise SystemExit("cold-probe harness: the pipelines the probe drew with are never released, so an "
                     "attempt counted as passing is not an attempt that gave its resources back")

# --- one machine-readable line per attempt, with the fields the plan names -------------------------------
if "M4_PROBE_RESULT" not in probe:
    raise SystemExit("cold-probe harness: the result is not printed as a machine-readable line, so a run of "
                     "thirty processes would need a log parser")
# The loop that gives each cold process its probes: a harness that always passed 1 would run the flag and
# ignore it, which is the shape a pin on the usage text cannot see.
if 'Metal4ColdProbe "$index" "$attempts" "$mode"' not in script:
    raise SystemExit("cold-probe harness: the mode the harness was told is never passed to the process, so "
                     "--mode is parsed and ignored and every run measures the same path")

if 'line="$(run_one "$index" "$probes_per_process")"' not in script:
    raise SystemExit("cold-probe harness: the cold loop does not pass the per-process probe count to the "
                     "process, so the flag is parsed and ignored and every process still runs one probe")

for field in ("process=", "attempt=", "mode=", "retried=", "success=", "stage=", "reason=", "epochMs=", "canMakeAndSubmit=",
              "canBindAndDraw=", "familyMetal4=", "queueSelector=", "argumentTableSelector=",
              "deviceCreation=", "deviceName=", "probeMs=", "elapsedMs="):
    if field not in probe:
        raise SystemExit(f"cold-probe harness: the result line has no {field.rstrip('=')} field, which the "
                         "plan asks every attempt to report")
# A fault that clusters in a burst of consecutive processes is a fact about the machine as much as about the
# probe, and a per-process duration cannot show a cluster: absolute time is what lines a failure up against
# whatever else was running.
for needle, why in (
    ('+ " epochMs=" + System.currentTimeMillis()',
     "the result line carries no absolute time, so a cluster of failures cannot be lined up against anything "
     "the machine was doing"),
):
    if needle not in probe:
        raise SystemExit("cold-probe harness: " + why)

if "System.exit(allPassed ? 0 : 1)" not in probe:
    raise SystemExit("cold-probe harness: the process exit code does not carry the verdict, so a failure can "
                     "only be found by reading output")

# --- the device the failures were captured on, and the stage that carries them --------------------------
if "lastFailureStage()" not in probe or "lastFailure()" not in probe:
    raise SystemExit("cold-probe harness: the probe's own stage and reason are not read, so a failure would "
                     "be reported as a bare false - which is what the capability record was already doing")
if "canMakeAndSubmit" not in probe or "canBindAndDraw" not in probe:
    raise SystemExit("cold-probe harness: the two probe stages are not both asked, so a failure cannot be "
                     "attributed to the command structure or to the binding and draw")

# --- and the fix itself, in both halves ---------------------------------------------------------------
# The retry exists because the FIRST probe of a process can fail and no later one ever has (measured: every
# failure in 160 cold processes was its first attempt, and 1100 later probes passed). Both halves are pinned
# because either one alone would leave the capability record answering from a single attempt again - and the
# harness's own mode is how the two paths are told apart, so a harness that stopped taking the retry would
# report a fault the client no longer has.
if "canBindAndDrawPersistently" not in probe:
    raise SystemExit("cold-probe harness: the harness never takes the persistent path, so --mode production "
                     "measures one attempt and reports it as the capability record's answer")
if "production ? MTL4Probe.canBindAndDrawPersistently(device)" not in probe:
    raise SystemExit("cold-probe harness: the harness knows the mode and does not choose the path by it, so "
                     "the two populations it counts are the same population")

metal4 = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "Metal4.java").read_text(encoding="utf-8")
if "MTL4Probe.canBindAndDrawPersistently(device)" not in metal4:
    raise SystemExit(
        "cold-probe harness: the capability record asks the probe once and not persistently, so the first "
        "attempt in a process can still be recorded as `this device cannot` - which is the whole of the AUTO "
        "blocker; the retry belongs on this path and not only in the harness"
    )
# The retry's own visibility: a fix whose firing cannot be seen cannot be verified, and the verification this
# milestone owes is exactly "a first attempt failed and the second answered".
if "lastRetried()" not in probe:
    raise SystemExit("cold-probe harness: the harness never reports whether the persistent path asked twice, "
                     "so a production run cannot show that the retry is what answered")
if "retried = true;" not in (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                             / "MTL4Probe.java").read_text(encoding="utf-8"):
    raise SystemExit("cold-probe harness: the persistent probe never records that it retried, so lastRetried "
                     "answers false whatever happened")

print("Metal 4 cold-probe harness contract: PASS")
