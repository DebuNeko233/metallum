#!/usr/bin/env bash
#
# The driver's own account of what the GPU was doing, sampled while a session runs.
#
# The harness records the machine's CPU load; this records the *GPU's* state, which is the resource a
# frame-time comparison is actually about, and it is the only reading here that can see another client:
# `PerformanceStatistics` carries the accelerator's own utilization and memory, and `AGCInfo` carries
# `fLastSubmissionPID`, the process whose submission the driver handled most recently. Measured on this
# machine at idle, that PID is UURemoteServer's - a remote-desktop server that captures and encodes the
# screen - so a host-side load average cannot see it and a frame-time spread attributed to "the machine"
# may be a second GPU client rather than the host being busy.
#
# Usage: gpu-trace.sh <output file> <seconds between samples> <number of samples>
set -uo pipefail

out="$1"
interval="${2:-1}"
count="${3:-1200}"

: > "$out"
for _ in $(seq 1 "$count"); do
	stats="$(ioreg -r -c IOAccelerator -d 1 2>/dev/null | tr '\n' ' ')"
	device="$(printf '%s' "$stats" | grep -o '"Device Utilization %"=[0-9]*' | head -1 | cut -d= -f2)"
	renderer="$(printf '%s' "$stats" | grep -o '"Renderer Utilization %"=[0-9]*' | head -1 | cut -d= -f2)"
	tiler="$(printf '%s' "$stats" | grep -o '"Tiler Utilization %"=[0-9]*' | head -1 | cut -d= -f2)"
	allocated="$(printf '%s' "$stats" | grep -o '"Alloc system memory"=[0-9]*' | head -1 | cut -d= -f2)"
	inuse="$(printf '%s' "$stats" | grep -o '"In use system memory"=[0-9]*' | head -1 | cut -d= -f2)"
	lastpid="$(printf '%s' "$stats" | grep -o 'fLastSubmissionPID"=[0-9-]*' | head -1 | cut -d= -f2)"
	submissions="$(printf '%s' "$stats" | grep -o 'fSubmissionsSinceLastCheck"=[0-9]*' | head -1 | cut -d= -f2)"
	busy="$(printf '%s' "$stats" | grep -o 'fBusyCount"=[0-9]*' | head -1 | cut -d= -f2)"
	game="$(pgrep -f devlaunchinjector 2>/dev/null | head -1)"
	printf '%s %s %s %s %s %s %s %s %s %s\n' \
		"$(date +%s)" "${device:--1}" "${renderer:--1}" "${tiler:--1}" "${allocated:--1}" \
		"${inuse:--1}" "${lastpid:--1}" "${game:--1}" "${submissions:--1}" "${busy:--1}" >> "$out"
	sleep "$interval"
done
