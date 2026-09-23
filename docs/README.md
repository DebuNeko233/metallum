# The documentation, and which page owns what

Metallum's long-form record. One page per subject, and each subject has one home: a figure lives in the document
that measured it, and anything that quotes it points there rather than copying the reasoning. Two contracts keep
that true - `tools/ci-harness.py` traces the result page's figures back to their owners, and `tools/ci-repo.py`
traces this index: every page in this directory is listed below, every link resolves, and nothing is listed that
does not exist.

## Where to start

| you want | read |
| --- | --- |
| what the long-term performance programme proved, rejected and settled | [long-term-performance-summary.md](long-term-performance-summary.md) |
| the policy that programme was run to, and what the owner answered | [long-term-performance-plan.md](long-term-performance-plan.md) |
| how a measurement is taken, and how large a difference it can be trusted to show | [performance-testing.md](performance-testing.md) |
| what this repository is, and which capabilities are validated | [../README.md](../README.md) |

## The programme's tracks, A to G

The summary page is the result; these are the evidence, one document a track, each with its decisions and the
numbers behind them.

| track | document | owns |
| --- | --- | --- |
| A | [metal3-performance-round2.md](metal3-performance-round2.md) | the Metal 3 native-call census: binds a frame, how many are redundant, and what the two elimination candidates measured |
| B | [vitrail-cpu-performance.md](vitrail-cpu-performance.md) | the frame's CPU cost and allocation, and what can measure either |
| C | [vitrail-gpu-performance.md](vitrail-gpu-performance.md) | the structural corpus, the passes a render scale does not move, and the shadow stage decomposed |
| D | [bridge-overhead.md](bridge-overhead.md) | the Vitrail-to-Metallum seam: calls, CPU and lookups a frame |
| E | [metalfx-performance.md](metalfx-performance.md) | the render-scale ladder, the 100-per-cent-is-native contract, and the gain each rung buys |
| F | [startup-and-cache.md](startup-and-cache.md) | what a launch serves, what it builds, and what a reload costs |
| G | [performance-testing.md](performance-testing.md) | the harness, the protocol, the refusals, and the rules for reading a session |

## The first round, before the programme

[metal3-performance-report.md](metal3-performance-report.md) is the first Metal 3 optimisation round, in the shape
the plan asks for. The long-term programme supersedes its conclusions where the two disagree and cites it where it
agrees; it is still the reference for its own phases.

## The frozen Metal 4 record

Metal 4 is kept, compilable and manually selectable, and frozen as an experimental backend: no performance work
runs on it, and these four documents are its history rather than a queue of work.

| document | owns |
| --- | --- |
| [metal4-full-frame-report.md](metal4-full-frame-report.md) | the status report: one row a milestone, and what remains unverified in each |
| [metal4-migration.md](metal4-migration.md) | the migration log, in the order the work happened |
| [metal4-resource-ownership.md](metal4-resource-ownership.md) | the ownership ledger: every object the Metal 4 path creates, who makes it, who releases it |
| [pre-m4-boundary-cleanup.md](pre-m4-boundary-cleanup.md) | the boundary cleanup that had to land before the Metal 4 moves |

## The two files outside this directory

[../README.md](../README.md) is what the repository is, its requirements, and the capability list it claims;
[../VITRAIL_SMOKE.md](../VITRAIL_SMOKE.md) describes each Apple-Silicon smoke gate and how to run it.

## The evidence itself

A session's own artifacts are under `run/`, which git does not track: `probe.txt` for the frame probe's window
lines, `latest.log` for the engine's censuses, `load.txt`, `load-trace.txt` and `gpu-trace.txt` for what the
machine was doing, `source-revision.txt` for the code each arm ran, `picture-source.txt` with `client.png` for the
frame itself, and `display-mode-before.txt` for the mode it was drawn in. [performance-testing.md](performance-testing.md)
says which of those a verdict may be read from, and every document above names the sessions its figures came from.

The programme's work landed on `master` in this repository and on `dev` in the companion
(`DebuNeko233/Vitrail-Shaders-Metal`); the commits it cites from the companion remain the record of what was
measured, whether or not a later release has moved that branch on.
