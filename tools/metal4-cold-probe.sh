#!/usr/bin/env bash
#
# The Metal 4 cold-probe harness: how often a fresh process fails the capability probe.
#
# The capability probe has read `argumentTable=false render=false` on some sessions and not on others, and
# always early in a session. That is a claim about a distribution over process starts, and the client cannot
# measure it: one attempt costs a Minecraft launch of about seventy seconds, and the answer is cached for the
# life of the process. This harness runs the probe in a process of its own - no Minecraft, no world, no pack,
# no window - so one attempt is a JVM start and a device, and thirty of them are a couple of minutes.
#
#   tools/metal4-cold-probe.sh --cold-runs 30 --warm-runs 20
#
# `--cold-runs N` starts N separate JVMs, one probe each, which is the measurement the intermittent fault
# lives in. `--warm-runs M` runs M probes inside one JVM, which is the control: if the fault is cold first
# use, the warm repeats all pass and the cold ones do not.
#
# The classpath is asked of the build rather than guessed, through an init script that adds one task, so
# nothing here modifies the project's build files and the harness cannot measure another branch's classes.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cold_runs=30
warm_runs=20
probes_per_process=1
mode="raw"
keep=false
out_file=""

usage() {
	cat >&2 <<'USAGE'
Usage: metal4-cold-probe.sh [options]

  --cold-runs N     how many separate processes to probe in (default 30). Each is a fresh JVM.
  --warm-runs M     how many probes to run inside ONE process (default 20), as the control.
  --mode raw|production
                    which path each probe takes. raw is one attempt, which is how the intermittent fault
                    is measured; production is the capability record's path, which asks once more where
                    the first answer is no (default: raw, because the fault is what this harness exists to
                    keep measuring).
  --probes-per-process K
                    how many probes each COLD process runs (default 1). One probe a process cannot tell a
                    process that is bad from a draw that went wrong: with K probes, a bad process fails
                    most of its own K and an isolated fault fails one of them, which is the question a
                    cold-only fault turns on.
  --out FILE        write the raw M4_PROBE_RESULT lines here as well as summarising them.
  --keep            leave the compiled probe class in place instead of clearing it.
USAGE
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--cold-runs) cold_runs="$2"; shift 2 ;;
		--warm-runs) warm_runs="$2"; shift 2 ;;
		--probes-per-process) probes_per_process="$2"; shift 2 ;;
		--mode) mode="$2"; shift 2 ;;
		--out) out_file="$2"; shift 2 ;;
		--keep) keep=true; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage; exit 2 ;;
	esac
done

# One task, added by init script, that prints where the runtime classpath is. Reading it out of the build
# rather than assembling one by hand is the same lesson the performance harness learned about jars: a
# directory lists files in an order that is not the order they were built in.
ask_classpath="$(mktemp -t m4-classpath)"
cat > "$ask_classpath" <<'INIT'
allprojects {
	afterEvaluate { project ->
		if (project.plugins.hasPlugin("java")) {
			project.tasks.register("m4PrintRuntimeClasspath") {
				doLast {
					println "m4-runtime-classpath=" + project.sourceSets.main.runtimeClasspath.asPath
				}
			}
		}
	}
}
INIT

echo "asking the build for its runtime classpath" >&2
classpath="$("$repo_root/gradlew" -p "$repo_root" -I "$ask_classpath" -q m4PrintRuntimeClasspath 2>/dev/null \
	| grep -m1 '^m4-runtime-classpath=' | cut -d= -f2-)"
rm -f "$ask_classpath"

if [[ -z "$classpath" ]]; then
	echo "the build printed no runtime classpath, so there is nothing to run the probe against" >&2
	exit 3
fi

classes="$(mktemp -d -t m4-cold-probe)"
probe_log="$(mktemp -t m4-cold-probe-log)"

cleanup() {
	[[ "$keep" == true ]] || rm -rf "$classes"
}
trap cleanup EXIT

echo "compiling the probe" >&2
javac -nowarn -cp "$classpath" -d "$classes" "$repo_root/tools/metal4-cold-probe/Metal4ColdProbe.java"

run_one() {
	local index="$1" attempts="$2"
	java -cp "$classes:$classpath" Metal4ColdProbe "$index" "$attempts" "$mode" 2>/dev/null | grep '^M4_PROBE_RESULT' || true
}

echo "cold runs: $cold_runs processes, $probes_per_process probe(s) each, mode $mode" >&2
cold_failures=0
for (( index = 1; index <= cold_runs; index++ )); do
	line="$(run_one "$index" "$probes_per_process")"
	[[ -n "$line" ]] || line="M4_PROBE_RESULT process=$index attempt=1 success=false stage=no-output reason=process-printed-nothing"
	printf '%s\n' "$line" >> "$probe_log"
	# Counted per probe line and not per process: with more than one probe a process, a process can hold both
	# answers, and the question is how many of its own probes a bad process failed.
	while IFS= read -r one; do
		[[ -n "$one" ]] || continue
		[[ "$one" == *" success=true "* ]] || cold_failures=$(( cold_failures + 1 ))
	done <<< "$line"
done

echo "warm runs: $warm_runs probes in one process" >&2
warm_log="$(mktemp -t m4-warm-probe)"
run_one "warm" "$warm_runs" >> "$warm_log" || true
cat "$warm_log" >> "$probe_log"
warm_failures="$(grep -c ' success=false ' "$warm_log" || true)"
warm_total="$(grep -c '^M4_PROBE_RESULT' "$warm_log" || true)"
# The sampled-texture DRAW smoke is counted apart from the capability sequence, because it answers a
# different question: the sequence is what the AUTO blocker is measured with, and the draw is whether a
# table-bound texture and sampler reach a fragment at all. A run that reported only one number for both
# would hide a failing smoke behind a passing capability. The allocator-slot ring is counted apart for the
# same reason again: it asks whether a slot may be reused, which is a lifetime question and not a binding one.
sampled_draws="$(grep -c ' sampledDraw=true ' "$probe_log" || true)"
sampled_draw_failures="$(grep -c ' sampledDraw=false ' "$probe_log" || true)"
ring_passes="$(grep -c ' ring=true ' "$probe_log" || true)"
ring_failures="$(grep -c ' ring=false ' "$probe_log" || true)"
attachment_passes="$(grep -c ' attachments=true ' "$probe_log" || true)"
attachment_failures="$(grep -c ' attachments=false ' "$probe_log" || true)"
layout_passes="$(grep -c ' layout=true ' "$probe_log" || true)"
layout_failures="$(grep -c ' layout=false ' "$probe_log" || true)"
copy_passes="$(grep -c ' copy=true ' "$probe_log" || true)"
copy_failures="$(grep -c ' copy=false ' "$probe_log" || true)"
depth_passes="$(grep -c ' depth=true ' "$probe_log" || true)"
depth_failures="$(grep -c ' depth=false ' "$probe_log" || true)"
fence_passes="$(grep -c ' fence=true ' "$probe_log" || true)"
fence_failures="$(grep -c ' fence=false ' "$probe_log" || true)"

if [[ -n "$out_file" ]]; then
	cp "$probe_log" "$out_file"
fi

# ---------------------------------------------------------------- summary
echo
cold_probes="$(grep -c '^M4_PROBE_RESULT' "$probe_log" || true)"
warm_only="$(grep -c '^M4_PROBE_RESULT process=warm' "$probe_log" || true)"
cold_probes=$(( cold_probes - warm_only ))
echo "cold processes: $cold_runs ($probes_per_process probe(s) each, $cold_probes probes)   failures: $cold_failures"
if (( cold_failures > 0 )); then
	echo "cold failure stages:"
	grep ' success=false ' "$probe_log" | sed -n 's/.*stage=\([^ ]*\).*/  \1/p' | sort | uniq -c
	echo "cold failure reasons:"
	grep ' success=false ' "$probe_log" | sed -n 's/.*reason=\([^ ]*\).*/  \1/p' | sort | uniq -c
fi
echo "warm probes:     $warm_total   failures: $warm_failures"
echo "sampled draws:   $sampled_draws passed   $sampled_draw_failures failed"
echo "allocator rings: $ring_passes passed   $ring_failures failed"
echo "colour attaches: $attachment_passes passed   $attachment_failures failed"
echo "bound layouts:   $layout_passes passed   $layout_failures failed"
echo "texture copies:  $copy_passes passed   $copy_failures failed"
echo "depth clears:    $depth_passes passed   $depth_failures failed"
echo "fence waits:     $fence_passes passed   $fence_failures failed"
echo
# The provider line is the same in every attempt, so it is printed once and not per process - which is also
# what keeps the per-process substitution below to nine capture groups. A tenth would have to be written `\10`,
# and sed reads that as `\1` followed by a literal `0`: the field would print the first group instead of the
# tenth, which is how this line reported every process's probe time as `10 ms` for a run.
echo "provider (every line): $(grep -m1 -o ' provider=[^ ]*' "$probe_log" | cut -c2-)"
# The compilation chain's own answer: the pipeline fixture every probe compiles through the Metal 4 chain.
# Printed once and not counted as a pass or a failure yet, because the first device proof of it is what this
# line reports - the round that makes it a counted smoke is the round that has a rate to count.
echo "pipeline compile: $(grep -m1 -o ' compile=[^ ]*' "$probe_log" | cut -c2-)"
echo
echo "per-process results (success, stage, sampled draw, ring, probe ms):"
grep '^M4_PROBE_RESULT' "$probe_log" | sed -n 's/.*process=\([^ ]*\) attempt=\([^ ]*\) mode=[^ ]* retried=\([^ ]*\) success=\([^ ]*\) stage=\([^ ]*\).* sampled=\([^ ]*\).* sampledDraw=\([^ ]*\).* ring=\([^ ]*\).* provider=[^ ]*.*probeMs=\([^ ]*\).*/  process \1 attempt \2 retried \3 success \4 stage \5 sampled(\6) sampledDraw(\7) ring(\8) \9 ms/p'

if (( cold_failures > 0 )); then
	exit 1
fi

if (( sampled_draw_failures > 0 )); then
	echo "the sampled-texture draw smoke failed in $sampled_draw_failures probe(s)" >&2
	exit 1
fi

if (( ring_failures > 0 )); then
	echo "the allocator-slot ring failed in $ring_failures probe(s)" >&2
	exit 1
fi

if (( attachment_failures > 0 )); then
	echo "the colour-attachment smoke failed in $attachment_failures probe(s)" >&2
	exit 1
fi

if (( layout_failures > 0 )); then
	echo "the bound-layout smoke failed in $layout_failures probe(s)" >&2
	exit 1
fi

if (( copy_failures > 0 )); then
	echo "the texture-copy smoke failed in $copy_failures probe(s)" >&2
	exit 1
fi

if (( depth_failures > 0 )); then
	echo "the depth-clear smoke failed in $depth_failures probe(s)" >&2
	exit 1
fi

if (( fence_failures > 0 )); then
	echo "the fence/submission smoke failed in $fence_failures probe(s)" >&2
	exit 1
fi
