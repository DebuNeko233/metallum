# Moving the frame's passes to Metal 4

The present is already carried by a Metal 4 queue: one command buffer, one `commit:count:`, the picture
drawn into the drawable through the engine's present pipeline and an argument table. Everything else -
the pack's render passes, its compute dispatches, the engine's clears and blits, the MetalFX upscale -
is still encoded into one **Metal 3** command buffer a frame.

This is the plan for the rest of it, written down because it is the largest change in the tree and
because half of it is decided by facts that took a run each to establish.

## What is proven, and how

Everything below was answered on the M5 Pro / macOS 27.0 by a probe that runs once at device creation
(`MTL4Probe`) and by the two scenes in `performance-testing.md`.

| Question | Answer | Evidence |
| --- | --- | --- |
| Is the Metal 4 core API there? | yes | `Metal 4 core API: available` ... |
| Is the selection deterministic between two runs? | **it flipped once and did not again** | one session's two identical no-pack arms reported `metal3` then `metal4`; a later session's **three** identical arms all reported `metal4`, all three capability lines identical (`argumentTable=true render=true`) and all three probes saying they "drew what they were told to" |
| Why? | a **functional** probe, and probably a cold one | in the flipping session the capability lines differed in exactly two fields (`argumentTable=false render=false` against `true/true`), which are the only fields read through `Metal4.canBindAndDraw()`; the session that did not flip ran minutes after several runs that had each presented 600 frames through Metal 4 argument tables |
| Can an argument table be made? | yes, by `newArgumentTableWithDescriptor:error:` | the header's out-parameter is part of the selector; the one-argument name is a method no object has |
| Can a texture and a sampler be bound through one? | yes | the present draws the picture through it, 600 of 600 frames, and the picture **is** the Metal 3 road's picture - measured in the no-pack scene, where this test is sharp (mean channel difference 0.04, 0.08% of pixels differ at all, against a same-configuration repeat of 0.04-0.05); in the pack scene it is not resolvable, see below |
| Can a **uniform buffer** be bound, by GPU address? | yes, and the pass *used* it | the engine's clear pipeline drew `(0.25, 0.5, 0.75, 1)` with its uniform in slot 1 of a table; the pixel was read back |
| Can a **vertex buffer** be bound, by address and stride? | yes, and the pass read it | a pipeline taking `const device float4* [[buffer(0)]]` drew a colour it could only get from that buffer, with `attributeStride` 16, read back as `(0.25, 0.5, 0.5, 1)` |
| Do Metal 3 pipeline states work on Metal 4 encoders? | yes | the present pipeline, the clear pipeline and a probe pipeline all draw on `MTL4RenderCommandEncoder` |
| Two new-kind encoders in one command buffer? | yes | the probe encodes two render passes into one command buffer and commits once |
| Is the sixteen-sampler ceiling a problem for the table? | no: it is MSL's, and the table took twenty slots | `sampler ceiling` probe, below |

The two things this document once listed as open are answered: the sampler ceiling is the compiler's
(`sampler` attributes are 0 to 15) and not the table's (a table took twenty slots), and the engine's
argument-buffer path binds as a buffer by address under Metal 4 - the same shape as a uniform, proven
above. Nothing in the binding surface is now unknown, which is why the slices below can start.

### The pipeline cache stays keyed by the game's own pipeline object

The migration table's "shared logical pipeline + generation-specific compile artifacts" invites moving
`MetalDevice`'s cache from `IdentityHashMap<RenderPipeline, ...>` onto a description key, so that two equal
descriptions share one artifact. The key exists (`MetalPipelineKey`, in `render.shared`) and it is a
sufficient identity: beyond the shaders it names the shader profile, the argument-buffer mode and one
composed `renderingState` description holding the depth and stencil state (which carries the colour-target
formats), the polygon mode, culling, the primitive topology and the vertex format bindings - every accessor
`MetalCompiledRenderPipeline` reads while it builds.

It was then measured instead of moved. The probe counts the distinct pipeline **identities** and the
distinct **keys** the device was asked for from process start, and on the settled pack scene
(`--settle 25`, camera pinned, Photon v1.3b at 55 per cent) the two read **345 and 345**:

    ... compiles=0 compileMs=0.00 pipelineIdentities=345 pipelineKeys=345 ...
    plain: 7.27 ms a frame, 137.6 frames a second, 7.28 ms of GPU time a frame over 600 answered frames

Equal counts mean a keyed cache would hold exactly the entries the identity cache holds. The move therefore
buys no compilations - the game builds each pipeline once and asks for it by that same object - while
costing the eviction contract (`evictCachedPipelines` takes a `Predicate<RenderPipeline>` and answers with
the pipelines it removed) and a hoist of the argument-buffer decision out of
`MetalCrossShaderCompiler.compile`, where it is derived from the layout entries. **So the cache keeps its
identity key, deliberately, and `MetalPipelineKey` keeps the job it was built for**: naming an artifact
across the two generations and saying in a log which description a compile belonged to.

The census stays on the probe rather than being removed after its one answer. It costs one identity-set
insertion per pipeline request and hashes the key only when the identity is new, and it is the only thing
that would report a future caller - a pack loader, or a Metal 4 table path - handing the device freshly
built equal pipelines. That run read inside the configuration's settled band (7.25-7.28 ms), so the
instrument did not move the number it measures.

### The services carry the selection, not a constant

`MetalDevice` built its `MetalExecutionServices` for `MetalApiGeneration.METAL3` **before** the selector had
run, and then took the selection a few lines later. Nothing read `selected()` from that instance, so nothing
broke - but the one object every seam asks (the queue factory, the present policy, and whatever M4 asks next)
disagreed with the selection the same constructor had just logged, and an AUTO launch that chose Metal 4 and a
forced Metal 3 launch would have looked identical to it. The services are now built from
`decision.selected()`, the queue is made from them where it always was, and `executing()` is read back from
the same instance rather than from a second one built from the same decision.

The contract that pinned this seam pinned the constant (`this.services = MetalExecutionServices.of(MetalApiGeneration.METAL3);`)
and failed the moment the constant was gone, which is what a pin should do: what it is really about is that
**the device has no opinion of its own about which queue to make**, so it now pins the selection instead.

The claim is now observed rather than inferred, because a value nothing printed cannot be checked: the device
logs the services' own answer at construction, and two arms in one session say the seam follows the selection -

    auto                                servicesSelected=metal4 servicesExecuting=metal3 referenceShell=true
    -Dmetallum.execution=metal3         servicesSelected=metal3 servicesExecuting=metal3 referenceShell=false

- while both execute Metal 3 (`1.78` and `1.78` ms wallP50, `-0.1 per cent`, and a picture difference of 0.03,
which is the no-pack bed's own repeat). The AUTO line is the one that matters: before this change that arm's
services would have answered `metal3` while the selection next to it said `metal4`. That line is now pinned by a contract, and the pin was mutation-proven: replacing the
format string makes the contracts fail with `the seam prints the generation the services themselves carry:
missing "Metal execution seam: ..."`, and restoring it passes - a log line nobody guards is a log line
somebody deletes, and this one is the only observation this seam has.

### The readiness seam is declared and never asked

`MetalExecutionServices.framePathReady()` exists, is documented, and **nothing calls it**: a search for it and
for `isReferenceShell()` across the sources finds exactly one reader, the log line added above. So the question
"can this generation encode a frame yet" is currently unasked, and its answer is structurally `false` - the
default implementation is `!isReferenceShell() && selected() == executing()`, and `executing()` is a constant
`METAL3` in the only implementation there is, while AUTO's `selected()` is `metal4`.

That was the shape M4 turned on, and it is the same shape as the bug fixed next door - so it was fixed next:
**`executing()` is now a parameter of the services rather than a literal**, `isReferenceShell()` asks whether the
executing generation is the selected one instead of whether the selection is Metal 3 (the right answer for the
wrong reason, until now), and the device **asks `framePathReady()`** where it used to leave the seam dormant:

    Metal execution: metal4 was selected and has no frame path yet, so the frame is metal3's and the selected
    generation is a reference shell for it
    Metal execution seam: servicesSelected=metal4 servicesExecuting=metal3 referenceShell=true framePathReady=false

The device passes `MetalApiGeneration.METAL3` for what executes, with the reason written where it is passed: the
selected generation's own frame path is what M4 builds, so until it exists that argument is the honest answer
rather than a constant baked into the services. What a contract cannot prove is that the caller passes the
generation that really executes - only M4's own frame path can settle that, which is exactly what
`framePathReady()` is for.

**And the next pack run showed the trap this seam sets.** Two things came back at once from a single settled
pack run: the capability probe answered `argumentTable=false render=false` **again** - the second independent
observation of the flip, in a different session from the first - and with the selection degraded to Metal 3 the
seam read

    Metal execution: metal3 selected (the device does not satisfy the Metal 4 minimum contract (no render
    encoder) (no argument table), so Metal 3 is used)
    Metal execution seam: servicesSelected=metal3 servicesExecuting=metal3 referenceShell=false framePathReady=true

`framePathReady()` is **true here**, because the selected generation *is* the one executing - which is exactly
what the predicate says and not what a caller wants to hear. It answers "does the selected generation have a
frame path of its own", so on a machine (or a run) whose Metal 4 contract fails, it reports ready while the
frame is drawn by Metal 3. **M4 must not gate on `framePathReady()` to decide whether the new path can be
used**; the question it needs is whether *the Metal 4 path* is available, which is the capability record's
answer, not this one. The predicate is a self-consistency check and the difference only shows up on the runs
where the probe disagrees with itself - which is why the second observation above matters twice.

Frame time did not care: `wallP50` 7.24 ms with `gpuM3Ms=4368.17`, inside the band this scene has held all
session (7.24-7.31), because both selections execute Metal 3.

The probe's deep half now speaks too: the `catch (RuntimeException)` that used to `return false` silently
records the throwable (`the draw or the readback threw ...`), and a pixel that arrives wrong says which channel
was wrong and what was asked for, because "the encoder took the binding and the GPU ignored it" and "the call
failed" are different findings. **It has not fired yet**: three more no-pack arms after the change all selected
Metal 4 with the probe succeeding, so the flip stands at **two observations in nine arms** (roughly one arm in
four or five), and its cause is still unlocated. What is in place is the instrument that will name it the next
time it happens - which is the honest description of this step, not a fix.

**Eight arms later it still has not fired, and the tally now carries a pattern.** Five more no-pack arms in one
session all selected Metal 4 with the probe succeeding, so the flip stands at **two observations in fourteen
arms** - and both were a session's **first arm**: the run whose arm `a` answered `metal3` while arm `b` answered
`metal4`, and a single-arm pack run. Other first-arm runs did not flip, so this is a tendency and not a rule,
but it is the first thing about the flip that is not just "sometimes": the leading explanation is now **the
first Metal 4 argument-table attempt in a session**, which is what the original observation suggested too (the
session that flipped was the first to touch Metal 4 in a while; the one that did not ran minutes after runs
that had each presented 600 frames through it).

The next attempt wants a cheaper trigger than a reboot: a fresh process against an idle GPU, as the first arm,
several times. Eight warm arms cost six minutes and answered nothing, which is the shape of this bug.

**Three contract pins fired while this was being written** - the seam's log format, the queue seam's factory
call, and the `executing()` literal - each naming the line that had moved. The third is the interesting one: it
had pinned an implementation detail (`return MetalApiGeneration.METAL3;`) as if it were the design, and now pins
`return executing;` for the property it was actually about.

### The probe is staged, and the cold/warm question has a harness shape

Every exit of `MTL4Probe.canBindAndDraw()` now names a stage and a reason - nineteen call sites: `selectors`,
`objects`, `uniform`, `table`, `vertex`, `target`, `pipelines`, `pass`, `attachment`, `encoder`, `commit`,
`completion`, `pixel`, `exception` - and `MTL4Probe.lastFailureStage()` is printed by the capability record
beside the reason. Two exits had no reason at all before this and both could produce the flip silently: the
**selector pre-check** at the top (which says nothing about *which* of the four selectors is missing, and now
prints all four answers) and **`newTarget` returning nil**, which had no check on the result at all - a nil
target was not reported as a failed target but surfaced later as a draw or a readback that went wrong. The
vertex table's nil check and its `setAddress:attributeStride:atIndex:` refusal were two conditions in one
`return false` and are now two findings, because a device without attribute strides is a different fact from a
device that would not make a second table.

**The cheap trigger exists now, and it has already caught the fault** (`tools/metal4-cold-probe.sh`,
`tools/metal4-cold-probe/Metal4ColdProbe.java`). A process of its own - `create device → run the probe once →
print one machine-readable line → exit`, with no Minecraft, no world, no pack, no window - costs about
**240 ms** a probe against the client's seventy seconds, so the cold/warm question is now a distribution
measured over processes rather than a coincidence waited for in sessions:

```
tools/metal4-cold-probe.sh --cold-runs 50 --warm-runs 20
  cold processes: 50   failures: 1     (process 11)
  warm probes:    20   failures: 1     (attempt 20)
```

Two failures in seventy attempts, **2.9 per cent**, and both carry the same stage and reason:

```
stage=pixel  reason=the vertex-buffer pass drew 191 in channel 2 where 128 was asked for
             canMakeAndSubmit=true canBindAndDraw=false
             familyMetal4=true queueSelector=true argumentTableSelector=true
```

**That retires two of the descriptions this issue has carried, on evidence rather than on argument.**

*It is not an argument-table capability gap.* Every selector answers true in both failures, the queue and
the command buffer are made and submitted, and `argumentTable=false render=false` in the capability record is
what a *single* `canBindAndDraw` answer becomes: `MetalDeviceCapabilities.probe` ANDs that one verdict into
both fields. The record's two false flags were never two findings.

*The readback says exactly which pass failed and how.* `EXPECTED_UNIFORM_PIXEL` is `{64, 128, 191, 255}` and
`EXPECTED_VERTEX_PIXEL` is `{64, 128, 128, 255}` - the two differ in **channel 2 alone** - so a readback of
191 is the *first* pass's pixel, not a corrupted or half-written one. Pass two's colour takes its channel 2
from a literal in the shader (`float4(vertices[vertexId].zw, 0.5, 1.0)`), so 128 arrives with any fragment at
all; 191 means pass two covered pixel (0, 0) with nothing. Its triangle is `(-1, 1), (3, 1), (-1, -3)` in clip
space, which covers the whole target, so the only way it covers nothing is that the three positions it read
were degenerate.

**The probe's own ambiguity was part of the problem, and it is fixed.** The probe drew pass one and read the
pixel back only after pass two, and both passes used `LOAD_DONT_CARE` with `STORE_STORE` - so a missed draw
left undefined tile memory, and 191 was one of the values the API permits it to return. Worse,
`EXPECTED_UNIFORM_PIXEL` was **declared and compared nowhere**: the uniform pass, whose entire purpose is
"does a uniform bound by GPU address through an argument table reach a draw", was never checked, and its
failure could only surface one pass later as a vertex-buffer failure. The probe now gives each pass its own
target - the plan's own Smoke 5 shape, pass A into target A and pass B into target B, one command buffer, one
commit - clears the second target to a known colour, and reads both back:

```
(64, 128, 128, 255)  the vertex-buffer draw arrived                      -> pass
(0, 0, 0, 255)       the second pass cleared its target and drew nothing  -> a draw that produced no fragment
(64, 128, 191, 255)  the first pass's colour inside a cleared target      -> the two targets are not the two
                                                                             textures the passes were given
anything else        reported with all four channels, not with one
```

`MTLLoadActionClear` is 2 and the clear colour is four doubles, both read from this machine's SDK header
(`MTLRenderPass.h:33-35,148-151`) rather than guessed; `MTL4RenderPass.h:33` declares the Metal 4 descriptor's
`colorAttachments` as the **Metal 3** `MTLRenderPassColorAttachmentDescriptorArray`, which is why the ordinary
`setClearColor:` is the right call.

**What the diagnostic probe then measured, twice.**

```
run A:   50 cold processes -> 3 failures (processes 46, 48 and 49)   300 warm probes -> 0
run B:   50 cold processes -> 0 failures                             100 warm probes -> 0
totals:  3 of 100 cold (3 %),   0 of 400 warm,   0 of 500 on the uniform/table pass
```

All three read stage `pixel` and reason `the vertex-buffer pass drew (0, 0, 0, 0) where (64, 128, 128, 255)
was asked for`. **That value is the finding**: it is neither the vertex colour nor the clear colour, it is the
second target **exactly as it was created**, so the second render pass contributed nothing at all - not its
draw and not its clear - while the first pass's own check passed in the same attempt, on its own target,
through the same table mechanism.

**And it is the FIRST probe in a process, which is what the next instrument settled.** One probe a process
cannot tell a process that is bad from a draw that went wrong, so the harness was given
`--probes-per-process K`: sixty cold processes, twenty probes each, twelve hundred probes, with the absolute
time (`epochMs`) recorded too. It produced **one failure**, and that process answers the question by itself:

```
process 47:  attempt 1  FAILED   (pixel, (0,0,0,0))
             attempts 2 to 20  all passed      <- same process, same device, milliseconds later
```

Every failure in every run has been at `attempt=1`: four of them, across ten processes of one shape and sixty
of this one, and never a second attempt. So the fault is **first-probe-in-a-process**, not a per-process state
and not a per-draw event: the identical sequence, on the identical device, a few milliseconds later in the
same process, works. That is a within-process control, and it is much stronger evidence than a rate.

**Which reinstates the hypothesis this document withdrew two rounds ago, and says why it was withdrawn
wrongly.** The original note said the flips were "often observed on a session's first arm" and called that a
hypothesis about cold first use. It was then withdrawn on a reading of 1 of 50 cold against 1 of 20 warm taken
with the **one-target probe**, whose failure could not distinguish a missing draw from a missing pass. The
better instrument now says the first reading was right about the *when* and wrong about the *what*: it is the
first probe in a process, and what fails is the second render pass's whole contribution - its clear included -
to its target.

**And the blocker is mitigated on the path the capability record reads, with the cause still open.**
`MTL4Probe.canBindAndDrawPersistently` asks once more where the first answer is no, and logs the first
attempt's stage and reason either way - a retry that swallowed the first answer would take a registered
intermittent off the record, which is the one thing this issue may not do. `Metal4.available` reads the
persistent answer, so what `MetalDeviceCapabilities.argumentTable`/`render` report is the device's answer
rather than the first command buffer's. Both halves are pinned by `tools/ci-metal4-cold-probe.py` and
mutation-proven: a harness that stops taking the persistent path, and a capability record that stops asking
persistently, each fail the contract for their own reason.

Why a retry is the right shape and not a workaround: **the fault has never been observed at any attempt but
the first.** Across 160 cold processes and 1100 later probes, every failure was a process's first attempt, and
the one process that failed at attempt one passed attempts two to twenty - same process, same device, same
sequence, milliseconds later. A capability answer is a fact about the device; the first attempt in a process
is not.

**And the retry is now visible, which is what let it be verified rather than assumed.** The probe records
whether the persistent call had to ask twice (`lastRetried()`) and the harness prints it per attempt, so a
production run shows the first attempt failing and the second answering instead of only the verdict. One
hundred and thirty cold processes on the path the capability record reads:

```
cold processes: 130   failures: 0
attempts that needed the retry:  1
    process 128  attempt 1  retried true  success true  stage ok
```

**That single line is the milestone's verification.** The fault fired in that process - its first attempt
failed, and the probe logged that attempt's stage and reason - the second attempt answered, and the answer the
capability record reports is `true`, so AUTO's selection would not have dropped to Metal 3. It is also the
first time the retry has been *seen* working: the earlier two runs (40 production, 40 raw) both came back
clean, which showed the path passing but not that the retry fires.

**The one thing still not established is the cause**, and it stays a hypothesis: what makes a process's first
multi-encoder sequence able to lose its second pass, while every later sequence in the same process is sound.
Section 14's Path A asks for "exact mechanism understood" as well as a fix, so this milestone is **not**
closed as Path A; what is closed is the AUTO blocker's *behaviour* - the answer no longer depends on which
sequence happened to be first.

**What that leaves open, exactly.** Something about the first command buffer a process submits can drop the
second render encoder's work, and it does so in about one cold first probe in twenty-five (4 of 160). The
candidate that fits, and that §13's list allows as a hypothesis, is lazy driver initialisation during the first
use of the new command structure. **It is not yet a root cause**, and the experiment that would settle it is
named rather than guessed: give the first probe a throwaway commit before the real sequence, or run only the
first pass in a process's first probe - if either makes the fault vanish, it is first-command-buffer
warm-up, and the fix is a warm-up rather than anything in the frame path.

**The three failures were three of the last five processes of run A, and the next run did not reproduce
them.** Fifty more cold processes, none failed. A per-process constant failure probability would put three in
five at about 0.07 per cent; a state that builds over a burst of consecutive process starts, or an
environmental one, fits better - and §13's list has both (driver state, and a low-frequency race). Stated
without over-reading: in this data the fault is **cold-process-only** (3 of 100 against 0 of 400), it
**clusters**, and when it happens the second pass's work never reaches its target.

**The shape changed between the two rounds, so the rates are not comparable, and the earlier "equally
frequent cold and warm, so not cold first use" is withdrawn.** Round two's probe used one target for both
passes; round three's gives each pass its own. Round two's 1 of 50 cold and 1 of 20 warm were measured with the
old shape, and with the two-target probe the warm population is clean over 400 probes. The two rounds
measured two different probe shapes, and only the second can say which pass failed.

Two of the four candidate causes in the registered issue are therefore excluded by measurement (an
argument-table capability gap, and - in the new shape's data - warm or repeated failure). What remains is
**what differs on a cold process**, now narrowed from "the vertex draw produced no valid pixel" to "the second
render pass contributed nothing to its target at all".

### Registered: the intermittent argument-table probe failure

    Blocks:              Metal4 AUTO production enable
    Does not block:      M1 / M2 / M3 / Metal4 implementation work

The probe's verdict feeds `MetalDeviceCapabilities.argumentTable`/`render`, hence `selected()` under AUTO, and
nothing else: no behaviour gates on `selected()` today (a search finds only log lines reading
`referenceShell`/`framePathReady`), the frame executes Metal 3 with `executing` passed explicitly, and
`-Dmetallum.execution=metal3|metal4` pins the selection deterministically in the meantime. So the issue is
**out of the main line** and is not to be chased with further hot-arm runs or more diagnostic code until the
cross-process harness exists (below).

**Wording correction, because the earlier sentence claimed more than the reading supports.** "26 calls in one
process, all true" shows only that **no in-process high-frequency or deterministic repeat failure was
observed**. It does **not** show that a failure must come from cold/first use. The open possibilities still
include a **low-frequency race**, an **object-lifetime** problem (a released table, buffer or event still
referenced), and **driver/GPU state** that a warm process happens not to be in. Two observations in fourteen
arms, both on a session's first arm, is a hypothesis about cold first use and nothing more.

What remains to do about it:

1. ~~build the cross-process cold-probe harness~~ - **done**, `tools/metal4-cold-probe.sh`;
2. ~~count cold-first and warm/repeated separately~~ - **done**: 1 of 50 cold, 1 of 20 warm, so not cold-only;
3. ~~locate it from the existing stage/reason instrumentation~~ - **done**: stage `pixel`, and the value read
   identifies the failed pass exactly;
4. ~~build the smallest reproducer~~ - **done**: each pass has its own target, the second is cleared, and
   both pixels are read, so a failure names which pass contributed nothing instead of leaving an ambiguous
   value. What it shows is that the *second render pass as a whole* contributes nothing, not merely that its
   draw produced no fragment;
5. **find what differs on a cold process**, which is now the whole of the question: the fault is cold-only in
   this data (3 of 100 against 0 of 400) and clustered, and it is not an argument-table capability gap - every
   selector answers true in every failure;
6. `-Dmetallum.probeRepeat` is a **development diagnostic switch**; it stays out of the normal hot path (it is
   inert unless the property is set, and nothing in the frame path reads it). The new harness does not use it:
   it repeats the probe in its own process, which is the experiment the switch was standing in for.

### Ownership, not count, is what the frame path's isolation has been moving on

This round the facade stopped naming any generation type at all: the frame's queue became the Metal 3 encoder's
own object (built from the services' address factory, closed with its teardown), and `Metal4Path.start`/`close`
moved behind `MetalExecutionServices.startPresentPath`/`closePresentPath`, with `Metal4PresentGate` holding the
road's static start and close and the gate chosen and kept once per session. `MetalDevice` now names
`MTLCommandQueue`, `Metal4Path` and `MetalCommandEncoder` **zero times**, and its ledger line is gone; the ledger
reads **15 couplings in 6 files**, the queue's type having moved into the encoder's entry and the present path's
into the services' - both relocations toward the owner, which is why the number moves less than the coupling does.

**What is left is one coupled change, and that is why step 5 was not done piecemeal.** `MetalComputeBridge` is
547 lines whose body is inseparable from `MTLComputeCommandEncoder` - it binds buffers, sampled images and
storage images through a compute encoder and shares that encoder across dispatches on purpose. A neutral
interface cannot hand out a compute encoder, so the bridge cannot become a thin facade without its body moving
as a file, and the body belongs in the same package as the encoder it drives. Steps 5 and 6 are therefore one
step: move the two bridges' implementations into `render.metal3` behind thin public facades that keep their names
and signatures, and move `MetalCommandEncoder`/`MetalRenderPass` at the same time - otherwise the cast inside a
moved body points backwards at a class still outside its package.

**Recorded, non-blocking (M2 follow-up).** The pipeline cache's generation/MSL safety is *validate-on-hit*: a hit
whose artifact was translated for another profile is recompiled. That is a safety mechanism and it is pinned, but
the better long-term shape is for the cache **identity itself** to contain the generation and MSL profile -
especially ahead of concurrent pre-compilation, `MTL4Compiler` and a binary archive. It is not in this phase's
scope and nothing depends on it now.

### The move was attempted and stopped, and the seam it found is one class

Steps 5 and 6 were attempted as the audit said they had to be - a whole-cluster move, not a piecemeal one - and
they were stopped under the rule that a package move which produces dozens of visibility errors means the order
is still wrong. The attempt: `git mv` of `MetalCommandEncoder` and `MetalRenderPass` into
`render/metal3`, package lines updated, and imports generated for every same-package type they referenced.

**82 compile errors. 26 of them one symbol: `MetalCompiledRenderPipeline在com.metallum.render中不是公共的`** -
the compiled pipeline record the encoder and the render pass both hold, which is package-private in `render` and
is not part of the cluster that was moved. The other ~56 are same-package type references the import generator
did not map (nested types such as `MetalCompiledRenderPipeline.ArgumentBufferLayout`, and `mtl`/`objc` types).
The move was reverted, `./gradlew build` is clean again and the ledger reads the same 15 couplings in 6 files.

Two things this settles. **The frame path's cluster is bigger than its two biggest files**: it is at least
`MetalCommandEncoder`, `MetalRenderPass`, `MetalCompiledRenderPipeline` (and its nested layout record), and the
bridges that encode through the first of them - moving two of them leaves the rest behind and that is what the
26 errors are. And **a mechanical move needs a same-package reference fixer that understands nested and
`mtl`/`objc` types**, not a regex over top-level names; doing it by hand is what produced the earlier attempts'
100/118/144 errors, and doing it with this generator produced 82.

So the next attempt is not another move: it is deciding the cluster's membership first (does
`MetalCompiledRenderPipeline` become a contract in `render.shared`, or does it move with the frame path?), and
fixing the imports with something that resolves nested types. That is the architecture seam §6 asked to find,
and it is written down here rather than discovered again.

### The move is blocked on a collaborator surface, not on import mechanics

Second attempt, with the decision made (`MetalCompiledRenderPipeline` stays in `render` and became visible to the
moved cluster): **118 errors, worse than the first attempt's 82.** The compiler named the next layer, and it is
not tooling:

| count | symbol |
| --- | --- |
| 24 | `MetalCompiledRenderPipeline.STAGE_VERTEX` / `STAGE_FRAGMENT` (nested constants) |
| 10 | `MetalCompiledRenderPipeline.ArgumentBufferLayout` (nested record) |
| 14 | **`MetalDevice.useLabels()` and `MetalDevice.metalDeviceHandle()`** - the facade's package-private members |
| 30 | `cannot find symbol` (imports and their cascades) |

**The frame path uses the facade's internals by package access.** That is the seam: `MetalCommandEncoder` calls
`device.useLabels()` ten times and `device.metalDeviceHandle()` four, which works only while both classes sit in
`com.metallum.render`. Moving the encoder makes those public widenings, which is what §H forbids - so the fix is
a contract for what a generation's encoder may ask the device (labels, the native device handle) rather than a
package accident. The nested constants and the layout record are the same shape one level down: they are part of
the artifact's surface that the frame path reads directly.

Reverted again under the rule, and this time the number went **up**, which is the useful part: the first attempt
looked like an import problem (82) and the second shows it is a collaborator-surface problem (118). Until the
encoder's device questions and the artifact's nested surface are contracts, no ordering of `git mv` will make
this move compile without widening visibility, and widening is the thing that produced the original 100/118/144.

### The third attempt: the compiled artifact is a collaborator, not a value

With the device-fact contract and the artifact's surface in place, the move was retried: **96 errors, down from
118 - and the remaining ones are the answer.** They are not imports and not the class's visibility; they are its
**accessors**, read by the Metal 3 render pass:

    stageMask() 18 · descriptorSet() 4 · bufferIndex() 4 · argumentBuffers() 4 · vertexBufferCount() 2
    firstAvailableVertexBufferSlot() 2 · executionServices() 4 (the device's own)

Thirteen-odd package-private accessors of `MetalCompiledRenderPipeline` and its layout record are called from the
frame path. **That is a collaborator, not a value being carried**, and it falsifies the decision recorded above:
keeping the record in `render` and opening its surface would mean opening a dozen members one at a time, which is
the widening this milestone forbids and the shape of the original 100/118/144 failures.

So the cluster is at least **`MetalCommandEncoder`, `MetalRenderPass`, `MetalCompiledRenderPipeline`** - and the
entities that stay behind (the device's pipeline cache and its profile guard, which reads `pipelineKey()` on that
record) must then talk to it through a contract, exactly as the encoder now talks to the device through
`MetalDeviceFacts`. The move is therefore: one contract for the artifact (key/profile, what a cache needs), one
for the device facts (done), and then the three files in one commit - not another ordering of `git mv`.

Reverted again under the rule. `./gradlew build` clean, ledger unchanged at 15 couplings in 6 files.

### The fourth attempt: the device owns caches the frame path calls directly

With the artifact moved as part of the cluster (fourth attempt: encoder + render pass + artifact), the errors fell
to 94 and are now two things: 80 `cannot find symbol` from the import fixer, and **four more of the device's
package-private members**:

    getOrCompileFunction(String, String) 4 · executionServices() 4 · getOrCompilePipeline(RenderPipeline) 2
    depthStencilState(MTLCompareFunction, boolean) 2

**`MetalDevice` is not only a facade: it owns the Metal 3 caches and the depth-stencil state factory that the
frame path calls directly.** That is the deepest layer of the seam, and it is why every attempt has needed more
widening: the cluster's real dependency is not a class or two but the device's *internals*.

So the shape of the finished move is now known end to end, and it is not a `git mv`:

1. the generation owns its caches - shaders, functions, compiled pipelines, depth-stencil states - and the device
   keeps only what a facade must (the pipeline cache it reports through `precompilePipeline`, plus the guard);
2. the device asks the generation through contracts (`MetalDeviceFacts` and `MetalCompiledArtifact` are the first
   two, both in place);
3. `executionServices()` becomes a public facade fact (it is one already: the services are the seam the whole
   milestone is built on);
4. and the import fixer must resolve nested and `mtl`/`objc` types, or the 80 symbol errors stay.

Reverted under the rule again; `./gradlew build` clean; ledger unchanged at 15 couplings in 6 files.

### The Metal 3 compilation chain, audited as one owner

The chain is `shader source → IntermediaryShaderModule → MTLFunction → MetalCompiledRenderPipeline → retirement`,
and it is one lifetime, not four: a module is kept because a function was made from it, a function because a
pipeline holds it, and a pipeline because the frame may still reference it. So `Metal3CompilationContext` is the
owner and stays one object; the migration into it is done one cache at a time only so that every step is a build
and a contract run away from a working tree.

**Moved so far:** the depth-stencil cache and its factory (`848dc5c`) - first, because it is the only one of the
five with a self-contained key and no dependency on the shader chain.

**Remaining, with what each needs:** `shaderCache` + `getOrCompileShader` (its only caller is
`MetalCrossShaderCompiler`; the key already carries the MSL profile, and that key must not change in this
migration); `functionCache` + `getOrCompileFunction` (three callers, all Metal 3 frame-path classes);
`compiledPipelines` + `deferredPipelineReleases` + `compiledFor` and the profile guard + `getOrCompilePipeline`,
`precompilePipeline`, `evictCachedPipelines`, `clearPipelineCache`. The device keeps thin **migration-only**
delegates for the callers until the frame classes move; those delegates are to be deleted before M3 ends, and no
new generation-specific getter is to be added to the device in the meantime - the context is injected where the
Metal 3 implementation is constructed, not fetched from the device.

**`deferredPipelineReleases` is not a cache.** It exists so native objects outlive their map entry while
already-recorded GPU work may still reference them, and it is drained where the device waits for submitted work
before releasing. That is **GPU retirement lifetime**, not cache lifetime, and the two must not be conflated to
save a class: the compilation context may hold it temporarily to keep behaviour identical, but its final home is
a Metal 3 execution-lifetime/retirement service, and the audit note is here so that a future reader does not read
"cache" and shrink it away.

**`MetalCrossShaderCompiler` has two responsibilities and only one of them is Metal 3's.** It translates -
GLSL through `GlslCompiler` to SPIR-V and on to MSL through SPIRV-Cross, with the MSL profile chosen from
`MetalShaderLanguageProfile` - and it *also* builds the native side: it asks the device for shader modules and
functions and constructs a `MetalCompiledRenderPipeline`. The translation, the profile choice and the
resource/entry-point metadata are what a Metal 4 compiler would need again, so they stay shared and must not be
dragged into `render.metal3` by the package move; the native construction and its caches belong to the context.
The intended shape is `MetalCrossShaderTranslator` (shared) → MSL source/module description →
`Metal3CompilationContext` → `MTLLibrary`/`MTLFunction`/pipeline.

**A failed step, recorded rather than hidden.** The first attempt at relocating the four remaining caches and
their factories mechanically - by extracting each method body and rewriting `this.` to the context or to the
device - stopped on a declaration whose annotations (`public synchronized @NonNull`) the extractor did not
match, before it wrote anything. The tree was left untouched and verified clean; the next attempt should move
one cache at a time by hand with the compiler as the oracle, which is how the depth-stencil cache was done.


**Method note for the shader-module migration: hand-edit, do not script it.** Four attempts to move
`shaderCache` + `getOrCompileShader` + `ShaderCompilationKey` into `Metal3CompilationContext` failed on *assembly*,
never on ownership: (A) the extracted members and the delegate compiled, and the only error was a malformed header
(`Metal3CompilationContext.java:3 需要<标识符>`, 1 error); (B) rebuilding that header dropped the imports the file
already had (46 errors); (C) appending only the missing import lines landed them in the broken region (20 errors);
(D) hand-writing the context file and patching the device by regex made the record-removal consume neighbouring
code (64 errors). Every attempt was reverted with build, contracts and guard verified clean.

What this means for the next attempt, exactly:

1. read `MetalDevice.java` and `Metal3CompilationContext.java` in full first, and edit by hand - no regex
   extraction, no generated headers;
2. add these imports **below** the existing block in the context and leave `MTLDevice`,
   `MTLDepthStencilDescriptor`, `MTLCompareFunction` untouched where they are: `GlslCompiler`,
   `IntermediaryShaderModule`, `Identifier`, `ShaderType`, `ShaderDefines`, `ShaderSource`,
   `ShaderCompileException`, `MetalShaderLanguageProfile`;
3. insert, in this order, building after the two riskiest edits: the `shaderCache` field; the record
   `ShaderCompilationKey(Identifier, ShaderType, ShaderDefines, String shaderProfile)`; `getOrCompileShader`
   verbatim with its two helper calls prefixed `MetalDevice.` (the helpers stay on the device as package-private
   pure string functions for this step, and move with the class later); the `close()` release loop;
4. in the device: delete the field, replace the method body with the migration-only delegate, delete the record,
   relax the two helpers from `private static` to `static`;
5. split the contract pin into two - `ShaderCompilationKey` against the context, `MslFunctionKey` still against
   the device - by matched parentheses, not by cutting at the first `))` (that produced a Python `SyntaxError`
   in an earlier attempt), then mutation-test the moved half;
6. then the pack smoke, and stop: no `functionCache`, no `compiledPipelines`, no `MTLCommandBuffer`-style frame
   work, no compiler split, no frame move.

Until that lands, `MetalDevice` still owns the shader module cache: `shaderCache` and `getOrCompileShader` are
the implementation there, not delegates, and `Metal3CompilationContext` owns only the depth-stencil cache.


**The sealing's two remaining items, and the one exception that stays.** Moving the eight-file cluster into
`render.metal3` now compiles down to exactly two files - `MetalComputeBridge` and `MetalDepthMipmapBridge` - whose
bodies are Metal 3 implementations wearing public names; the compiler's list from the attempt is `Metal3ExecutionState`
(16), `MetalCommandEncoder.flushPendingClear` (12), `endEncoder` (8), `renderCommandEncoder` (4). The depth bridge
now takes the state from the encoder it already holds (`encoder.executionState()`), so it is ready to move; the
encoder answers for its own state through a package-private accessor, which is generation-internal and needs no
widening.

**`MetalComputeBridge.compile(Object backend, String label, ByteBuffer spirv)` is the one caller that cannot be
rerouted**: its backend is the device, not an encoder, so `MetalDevice.executionState()` stays - package-private,
typed `MetalExecutionState`, naming no generation - and the contract records that shape rather than forbidding it.
Phase D's condition ("delete it if no neutral caller needs it") is therefore not met, and the accessor is the
seam the moved `Metal3ComputeBridge.compile` will use.

### The Metal 4 provider exists, and it refuses what it does not have

Phase 2 asks for a generation-specific execution provider rather than more present-sidecar code, and the seam
for it was already there: `MetalExecutionProvider` with `Metal3ExecutionProvider` behind it, chosen in
`MetalExecutionServices.of(selected, executing)`. What was missing is the Metal 4 side, and what it is is a
skeleton with one real method and two named refusals:

```
Metal4ExecutionProvider implements MetalExecutionProvider
    commandQueue(MTLDevice)            newMTL4CommandQueue, real, nil refused by name
    createExecutionState(MTLDevice)    throws Unimplemented("createExecutionState")
    createFrameEncoder(...)            throws Unimplemented("createFrameEncoder")
measured in the cold-probe harness, per process, on Apple Silicon:
    provider queue=ok,state=refused(createExecutionState),encoder=refused(createFrameEncoder)
```

**It refuses rather than returning nothing** because section 35 forbids an unknown operation being silently
dropped: a provider that answered null would move the failure into whatever first used the state, twenty calls
later, which is the distortion the capability probe was rebuilt to remove. The refusal carries its stage for the
same reason `lastFailureStage()` does - "not implemented" cannot be told from "the whole provider is missing".

**And the services now choose the provider by the EXECUTING generation**, not by a constant: the switch reads
`executing`, so a session that selected Metal 4 while a Metal 3 path stands in for it still builds its frame
from Metal 3 objects with `referenceShell` true, exactly as section 19 requires. Today that is every session -
the device constructor passes `METAL3` - so nothing about which road a frame takes has changed; what changed is
which object would own it, which is one line in that constructor when the Metal 4 frame encoder exists.

`tools/ci-metal4-provider.py` pins the neutral interface, the real queue factory and its nil check, both
refusals by name, the stage the refusal carries, that no Metal 3 package is imported by a Metal 4
implementation, that the services choose by `executing`, and that the harness asks the provider on a real
device - six mutations, each failing for its own reason.

### The fourth render smoke: the binding half, and then the drawn half

The migration plan's Phase 3 asks for five native smokes before anything touches the Minecraft frame, and four
of them are already the probe's own shape: the constant-colour draw is its first pass (a table-bound uniform
writing (0.25, 0.5, 0.75, 1.0), read back as (64, 128, 191, 255)), the uniform smoke is that same pass, the
vertex smoke is its second (a buffer bound by address and stride 16, drawn by a pipeline whose colour comes out
of the buffer, read back as (64, 128, 128, 255)), and the two-encoder smoke is the pair - pass A into target A,
pass B into target B, one command buffer, one commit, one shared-event wait, both pixels read.

The fifth had no coverage at all: **a sampled texture and a sampler**. Its binding half landed first,
`MTL4Probe.canBindSampledTexture`: a 4x4 RGBA8 shared texture, a nearest sampler that declares argument buffer
support, and a table made for exactly one texture and one sampler, then both setters - with each refusal
reported by name rather than as a bare false. Measured on Apple Silicon in 45 of 45 attempts across 25 cold
processes and 20 warm probes.

**The drawn half landed next**, as `MTL4Probe.canDrawSampledTexture` - a sequence of its own rather than a
third pass inside `canBindAndDraw`, so that the per-process distribution the AUTO blocker is measured with is
not restated by a new question: the two are reported in separate fields and fail apart. It is the smallest
shape that has everything a frame's own pass needs.

1. A pattern pass renders four flat quadrants into a 64x64 source that declares `RenderTarget | ShaderRead`.
   The usage is part of the question and not bookkeeping: a texture that does not declare the read is not one
   a shader may read.
2. The pass ends with `barrierAfterStages:beforeQueueStages:visibilityOptions:`, the producer barrier the new
   command model requires of a dependency between encoders - the first place in this engine where a Metal 4
   dependency is encoded rather than assumed. The selector is asked of the encoder before it is sent, like
   every other selector here, so a device that does not implement it reports a stage instead of raising.
3. A second pass in the **same** command buffer samples that source at the fragment stage through a
   one-texture/one-sampler table and draws it into a target of its own.
4. The command buffer is committed **once**, waited for through a shared event, and then both textures are
   read back at the same four pixels - one well inside each quadrant.

Reading both textures is what keeps the answer from being a guess. The source says whether the pattern landed
and the destination says whether the sample arrived, so a pattern that never rendered is not reported as a
sample that never arrived; and because the source is four quadrants of known colour, a sample that arrives
flipped or offset reads a different quadrant and the message names the quadrant it read and the one it was
asked for.

Measured on Apple Silicon (Apple M5 Pro, macOS 27): **100 of 100 probes passed** - 30 cold processes plus 20
warm repeats of one process in `--mode raw`, and the same again in `--mode production` - with the capability
sequence passing in every one of them and nothing to attribute. The check is not vacuous: with the destination
readback transposed (a one-character mutation of the read region) the same harness reports
`sampledDraw=false` with `the sampled pass read the pattern's bottom-left colour (0, 255, 64, 255) at (40, 8)
where its top-right (255, 0, 64, 255) was asked for, so the sample reached the wrong place in the source`, and
the driver exits 1. `tools/ci-metal4-cold-probe.py` pins the whole chain - the sequence's presence, the
expected pattern, the source's `ShaderRead` usage, the barrier and the selector check before it, the table at
the fragment stage, both readbacks and the wrong-quadrant report, plus the harness's two printed fields and the
driver's count. Sixteen mutations were run against those pins: the first pass caught ten and exposed two pins
that documentation text alone could satisfy (the printed field name also appears in the class's javadoc, and the
count variable is named more than once), so those two were strengthened against the print expressions and the
counting line themselves and then caught the same mutations - sixteen of sixteen. Two more were run against
`tools/ci-contracts.py`'s updated table pin, and both were caught.

**What it does not prove.** Nothing here binds linear filtering, anisotropy, a mip level or an address mode, so
the smoke says nothing about them. And the barrier's necessity is not measured: the readback is correct with it
encoded, while whether this device would also have ordered the two passes without one is NOT MEASURED - the API
contract for the new command model requires it and the migration's rule is to express a dependency before
optimising it, so the barrier is written and the question is left open rather than answered by a passing
readback. The capability record does not consume the smoke yet either: `Metal4.available` still reads
`canBindAndDrawPersistently`, which keeps the AUTO-blocker distribution measured across 160 processes
comparable; the smoke joins the record when a Metal 4 frame path exists to need it.

Two smaller corrections came with it. The argument table's texture binding moved from a hard-coded slot zero to
the slot the layout names (`texture(handle, index)`), because the smoke binds a slot the shader's own
`[[texture(n)]]` attribute names and one table will have to hold more than one image - `tools/ci-contracts.py`'s
pin on that call was updated to follow the call rather than deleted. And the harness's per-process line had a
sed bug of its own: with a tenth capture group it had to be written `\10`, which sed reads as `\1` followed by
a literal `0`, so probe times printed as `10 ms` for every process. The provider line is now printed once and
the substitution has nine groups, which is also why the fix is written down in the script next to the sed.

### The pass object: `Metal4RenderPass`, and what a frame can now enter

`createRenderPass` no longer refuses. `render.metal4.Metal4RenderPass` implements the game's own
`RenderPassBackend`, resolves the descriptor's colour and depth attachments, checks the two rules the Metal 3
pass checks - every attachment agrees on an extent, and the render area lies inside it - and opens the pass
through `MTL4RenderEncoder`, which is the layer whose attachment mapping is already measured on the device. A
descriptor that has no area, an area outside its attachments, a view that is not this engine's, or a pass the
device will not open: each is a named fault rather than a pass that silently draws nothing.

The frame's begin moved with it. A frame is begun at the **first pass** that encodes into it, inside
`createRenderPass`, because that is the first thing that knows the frame has work; beginning it there is also
where the slot's previous submission has been proved complete (the ring waits inside `beginFrame`), so that is
the one place a slot's filed releases may legally run - which is the retirement rule from section 32 finally
wired end to end rather than described. A second `createRenderPass` before a `submitRenderPass` is a named
fault, because two open passes are two encoders in one command buffer with no order between them.

**What refuses.** Every operation that would bind a resource or issue work, one name each: `setPipeline`,
`bindTexture`, `setUniform`, `enableScissor`, `disableScissor`, `setVertexBuffer`, `setIndexBuffer`,
`drawIndexed`, `multiDrawIndexed`, `drawIndexedIndirect`, `drawMultipleIndexed`, `draw`, `multiDraw`,
`drawIndirect` and `writeTimestamp`. **One operation is a no-op instead**: `pushDebugGroup`/`popDebugGroup` are
capture labels and not work, so dropping them costs a reader of a GPU capture something while refusing them
would break a frame for no correctness reason - the distinction the plan's section 35 draws between an
operation dropped and a frame half-drawn.

Each pass ends by encoding the **producer barrier** before its encoder closes. Only the pass that *reads* an
attachment knows whether a dependency exists, and that fact does not reach this generation yet (the Metal 3
pass learns it through `MetalFrameExtras`, which Metal 4 does not implement), so the migration's section 62
rule for this stage applies: over-synchronise while the path is being built.

**The evidence, stated exactly.** The pass object cannot run in the cold-probe harness - it is built from the
engine's device and from `GpuTextureView`s, which a bare process has no way to make - so its evidence is a
structural contract rather than a device run, and the layer underneath it is the one with the device run: the
descriptor, the attachment loop, the load and store mapping, the clears and the barrier are all
`MTL4RenderEncoder`, measured in 50 of 50 probes across 30 cold processes and 20 warm repeats. What that leaves
unproven is the pass object's own wiring, which the first no-pack frame is what will exercise.

`tools/ci-metal4-provider.py` was extended for it: the pass implements the game's contract and only that
contract, opens through the measured layer, reads the clear values and the render area, refuses an area outside
its attachments, encodes the barrier, keeps the debug group a no-op, and refuses each of the fifteen operations
by name; and the frame encoder begins its frame at the first pass, runs that slot's releases, remembers the open
pass, ends it on `submitRenderPass` and ends an open one on `close`. Seventeen mutations were run against those
pins, all caught - two of them only after the pins were strengthened, which is the mutation test doing its job:
a pin on `pushDebugGroup`'s signature alone was satisfied by a body that refused, and a pin on the frame-begin
test alone was satisfied by the same test inside `submit()`.

### The compilation chain: a Metal 4 pipeline is compiled by Metal 4

`Metal4ExecutionState.getOrCompilePipeline` no longer refuses. The generation now owns its own chain -
`Metal4CompilationContext`, `Metal4PipelineCompiler` and `Metal4CompiledRenderPipeline` - and nothing in it
reaches into `render.metal3`:

- the **game's own GLSL compiler** turns a pack's source into SPIR-V, cached per (shader, stage, defines,
  profile);
- the **shared translator** (`MetalCrossShaderTranslator`, already shared and already the layer the plan's
  section 27 puts between the generations) turns that into MSL and names the resources it declared;
- **this generation** builds the native pipeline states from the MSL, with the attachment formats, the blend or
  disabled blend and write mask, the vertex descriptor and the depth format taken from the pipeline itself -
  two states, with and without a depth format, for the same reason the Metal 3 artifact keeps two.

**The one argument that differs from the Metal 3 compiler, and the reason for it.** The Metal 3 compiler asks
the translator for an argument-buffer layout where the device supports one; this one asks for **direct
bindings** (`translate(..., false)`) and refuses a translation that comes back with argument buffers anyway.
Metal 4's binding mechanism is the argument *table*, and a pipeline translated for argument buffers would be
handed the previous generation's mechanism inside the new path - so `Metal4CompiledRenderPipeline.resources()`
is a list of direct bindings, each carrying the metal index its MSL was compiled against, which is exactly what
a table slot is filled from.

**The MSL profile is part of every cache key** - the module key, the function key and the artifact key - for the
reason the Metal 3 context records: a module translated for one profile is not the one another profile needs,
and a cache keyed only on source text would be safe by accident.

**Retirement is smaller here, and deliberately.** An artifact that is evicted or replaced may still be named by
work in flight, so it is **filed** rather than closed, and released by `clearCachesAfterGpuCompletion()` - whose
neutral contract already says the caller has established GPU completion. The Metal 3 context can retire per
submit because it can ask the frame encoder; this one has one queue and one method, which is the smaller
lifetime model and the one the contract actually describes.

**One shared-layer move came with it**: `GlslCommentStripper` moved from `render.metal3` to
`render.shared`, because both generations prepare GLSL the same way (strip comments first - the pack toggle-block
lexical trap the Metal 3 path paid for - then inject defines) and neither may reach into the other's package.
The Metal 3 context uses the shared class now; its behaviour is unchanged. `tools/ci-shader-diagnostics.py`
follows the file and the package its contract harness compiles it into.

**And it has now run on the device.** The cold-probe harness builds a pipeline description and a GLSL shader
source of its own - a full-screen triangle whose fragment colour comes from the vertex stage, so neither shader
is a constant - and compiles it through the state the provider hands out. That is the whole chain in a bare
process: the game's GLSL compiler, the shared translator, and this generation's native pipeline state, which the
artifact reports valid. Measured on Apple Silicon: **50 of 50 probes** answered `compile=ok(valid=true)` in 30
cold processes and 20 warm repeats.

Two things about how it is asked, because both are measurement decisions rather than details:

- the fixture is built **before** the probe loop, because building it does no native work, and the compile runs
  **after** the deep probes inside each attempt. Those probes have to stay the process's first native work: the
  cold-fault distribution is a distribution over first use, and a warm-up in front of them would quietly change
  the thing being measured. The first version put the compile first, which warmed the very path the fault lives
  in and dropped the reported probe time from ~220 ms to ~30 ms - a measurement bug caught by reading the
  numbers, and the reason the order is written down here;
- the first attempt of a process compiles and the later attempts answer from the cache, so the field reports
  both the compile and, implicitly, that the cache answers.

The two failures the first attempts hit are recorded because they are the shape of the work: the pipeline
builder refuses a location with a namespace in it (`metallum:m4_probe` is read as a path under `minecraft:`), and
it refuses a pipeline with no primitive topology. Both are the game's own contracts rather than Metal's.

`tools/ci-metal4-provider.py` and `tools/ci-metal4-cold-probe.py` pin the chain and its proof: the state owns a
compilation context and compiles through this generation's compiler, the module, function and artifact keys all
name the MSL profile, a replaced artifact is retired rather than closed and released where the contract says GPU
completion has been established, the translator is asked for direct bindings and refuses to accept argument
buffers, the artifact builds its own native states with a depth variant and a vertex descriptor, and the harness
builds a fixture and reports what the chain answered - sixteen mutations against the chain and four against its
proof, all caught.

### The binding model, measured: a layout through one table a stage

Metal 4's encoders have no per-resource setters at all. A pass binds by filling an argument **table** and
assigning it to the stages that read it, which is the whole reason this migration exists rather than a port of
`setVertexTexture:atIndex:` to a new class. `MTL4RenderEncoder` now carries that path - `setArgumentTable:atStages:`,
the pipeline, the depth-stencil state, the cull and fill modes, `setScissorRect:`, and the two draw selectors
(`drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:` and
`drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:`) - and
`MTL4Probe.canBindALayout` measures it end to end on the device.

The smoke is the production shape rather than a convenience:

- a **vertex table** sized to what the vertex stage binds, carrying a vertex buffer **with its attribute stride**
  at index 0 and a vertex-stage uniform at index 1;
- a **fragment table** carrying a uniform at buffer 0, a texture at texture 0 and a sampler at sampler 0;
- both tables assigned at their own stages, one pipeline built from the probe's own MSL, one draw;
- a **scissor** rectangle over the left half of the target, and two readings: the pixel inside it must be the
  layout's colour and the pixel outside it must be the pass's clear. That second reading is what makes the
  scissor a measurement rather than a call count;
- an explicit **cull mode**, whose call has to be accepted; its *effect* is deliberately not asserted, because
  that needs a back-facing triangle and is a milestone of its own.

Every one of the four bindings changes the answer, which is what makes the readback a reading of the table
rather than of one slot: the texture is the base, the vertex uniform adds to red, the fragment uniform adds to
green, and the geometry and uvs come out of the vertex buffer. Measured on Apple Silicon: **50 of 50 probes**
passed in 30 cold processes and 20 warm repeats.

**Two things the first attempts taught, both recorded because they are the shape of this work.**

1. The expected pixel has to be an exact sum in eight bits. The first version cleared the sampled source to 128
   and added 0.25 to its red, expecting 191: 128/255 + 0.25 is 0.75196, which lands on **192** - measured, and
   the reason the smoke's colours are now 0.25 and 0.5 (0.25 + 0.5 = 0.75, 0.25 + 0.25 = 0.5) with the
   arithmetic written beside them.
2. A stale build reads as a device fault. One run reported the texture's own colour with the uniforms missing,
   which looked like a binding that did not arrive; the source had been edited but not recompiled, so the probe
   was running the previous shader. The harness asks the build only for its classpath, so a source change needs
   a compile before a measurement - the same class of mistake as the earlier warm-up bug, and worth writing
   down.

**What is still refused, and therefore still unproven through a frame**: the pass object does not call any of
this yet. `Metal4RenderPass.setPipeline`/`bindTexture`/`setUniform`/`setVertexBuffer`/`setIndexBuffer`/`draw*`
still refuse by name, so the encoder's commands have a device proof and the pass's use of them does not. Wiring
the pass - pipeline lookup through the artifact, the binding plan that maps a layout to table slots, and the
draws - is the next milestone, and the fixture that would prove it needs the engine's device.

`tools/ci-metal4-cold-probe.py` pins the encoder's commands, the address form of the indexed draw, the tables'
shapes, the stride, the stage each table is assigned to, the scissor and its two readings, and the harness's
field, count and exit code - seventeen mutations run, sixteen caught by the pins themselves and one after a pin
was strengthened (a table-size pin satisfied by another smoke's identical call).

### The binding plan, and the pass that fills it

The layout smoke above proved the mechanism; the production objects are `Metal4BindingPlan` and the pass's own
use of it. The plan is the Metal 4 half of the binding question: the shared translation decides *what* a program
binds and what the MSL calls each one, and the plan turns that into the shape a table is filled in - which
stage's table a resource belongs to, which slot in it, and how many slots each stage's table needs. It is built
once, when a pipeline is compiled, so that filling a table per pass is a lookup rather than a discovery (§48's
own rule: no string parsing, no regex, no resource-kind discovery per frame).

Two details it answers that a first guess gets wrong:

- **a table is sized to the highest index a stage is given, not to the number of names.** A named buffer at
  metal index 2 needs a three-slot table even though it is the only binding, and the vertex stage's table also
  has to cover the vertex layouts, which are not named bindings at all: they live at the buffer slots after the
  named vertex-stage ones, and the plan's buffer count accounts for them;
- **vertex buffers are not in the plan's named slots.** A vertex buffer is a layout the pipeline's vertex
  descriptor describes, bound by address <em>and stride</em> at the plan's own vertex region - which is why the
  pass takes the stride from the pipeline's vertex format rather than from the binding.

The plan is in the bindings layer beside `MTL4ArgumentTable` rather than in the frame path, and that placement
paid for itself: the layout smoke now builds a plan, sizes its tables from it, looks its bindings up in it and
takes its vertex slot from it, so **the device proof is a proof of the production plan** and not of a parallel
copy of it.

**The pass now fills that path.** `Metal4RenderPass` implements the no-pack subset the migration's section 34
asks for and refuses the rest by name:

- `setPipeline` compiles through this generation's own chain, builds the plan from the artifact's footprint,
  makes the tables the plan sizes, and releases the previous ones - so a replaced pipeline cannot be read
  through a stale table;
- `bindTexture`, `setUniform` (whole buffer and slice) and `setVertexBuffer` look the name up in the plan and
  fill the stage's table at the plan's slot; a binding read by both stages is filled in both; **a name the
  pipeline does not declare, or a texture bound to a buffer's name, is a named fault** rather than a binding
  that quietly goes nowhere, which is the half frame section 35 forbids;
- `setIndexBuffer` remembers the buffer as an <em>address</em> and the draw turns the engine's first index into
  an offset on that address, which is the one difference Metal 4's indexed draw has from Metal 3's;
- `enableScissor`/`disableScissor` set and clear the rectangle, and clearing it means setting the whole
  attachment rather than leaving the last one in force;
- a draw assigns the tables where they have changed, sets the pipeline state (the depth variant chosen by
  whether the pass has a depth attachment), the depth-stencil state, the culling and fill modes and the scissor,
  and then draws.

The multi-draw, indirect and timestamp forms still refuse by name: a no-pack frame does not need them, and
section 34 says not to build what the current slice does not use.

**The evidence, stated exactly.** The plan has a device proof (through the layout smoke, 50 of 50 probes), the
encoder's commands have one, and the compilation chain has one. The pass object's own wiring has none: it is
built from the engine's device and from real texture views, so what stands behind it is the structural contract
plus the two measured layers it composes. `tools/ci-metal4-provider.py` pins that wiring - the compile path,
the plan-built tables, the lookups and their refusals, the pipeline's own stride, the index address arithmetic,
the scissor clearing, the table release on a pipeline change, the assign-only-when-changed rule, the draw
sequences and the operations still refused - and twenty-one mutations were run against those pins: eighteen
caught at once, three after the pins were strengthened (a lookup pin satisfied by a second identical line, a
release pin satisfied by another call site, and two assignment pins that a short-circuit could step over). The
last pair is the shape a text pin cannot see on its own, and the contract file says so where it is pinned.

## The API mapping

Metal 4 has no per-resource binding methods on its encoders at all. Each row is a call the engine makes
today and what it becomes.

| Today (Metal 3) | Metal 4 | Notes |
| --- | --- | --- |
| `MTLCommandQueue` + one `MTLCommandBuffer` a frame | `MTL4CommandQueue` + one `MTL4CommandBuffer` begun on an `MTL4CommandAllocator` from a ring | the allocator may only be reset once the GPU is done with it; the ring and the shared event that bounds it already exist in `Metal4Path` |
| `renderCommandEncoderWithDescriptor:` | same selector, on the command buffer, with an `MTL4RenderPassDescriptor` | the pass descriptor's attachments are Metal 3's own classes, so load and store actions move unchanged |
| `computeCommandEncoder` | same selector, on the command buffer | `MTL4ComputeCommandEncoder` keeps the blit it absorbed, which is how the engine's copy-backs and mip passes move for free |
| `blitCommandEncoder` | the compute encoder's copy methods | `copyFromTexture:toTexture:` takes two objects and no structures |
| `setVertexBuffer:offset:atIndex:` | `MTL4ArgumentTable.setAddress:attributeStride:atIndex:` + `setArgumentTable:atStages:` | proven above; the stride is the vertex layout the shader indexes with |
| `setVertexBytes:length:atIndex:` / `setFragmentBytes:length:atIndex:` | the same bytes written into a buffer and bound by address | the engine already allocates transient GPU-mapped memory for uniforms (`MetalRenderPass`), so this is a change of destination, not of source |
| `setVertexBuffer:`/`setFragmentBuffer:` for uniform buffers | `setAddress:atIndex:` | proven above |
| `setVertexTexture:atIndex:` / `setFragmentTexture:atIndex:` | `setTexture:atIndex:` by `gpuResourceID` | proven by the present |
| `setVertexSamplerState:atIndex:` / `setFragmentSamplerState:atIndex:` | `setSamplerState:atIndex:` by resource id | proven by the present |
| the per-layout argument buffer written by `MTLArgumentEncoder` | the table itself: the resources are bound into table slots instead of being encoded into a buffer | this is the part with the 16-sampler ceiling |
| `useResource:usage:stages:` | `MTLResidencySet` added to the queue (`addResidencySet:`) | the present works without one, so residency is a correctness/performance question to measure rather than a blocker |
| `updateFence:afterStages:` / `waitForFence:beforeStages:` | `barrierAfterEncoderStages:beforeEncoderStages:` and `barrierAfterStages:beforeQueueStages:` on the encoders | the engine's fence chain is what P1's read/write description was built for; the producer barrier is already encoded and measured in the probe's sampled-texture smoke - a render pass that samples what the pass before it wrote, in one command buffer |
| `MTLFXSpatialScaler` (+ `encodeToCommandBuffer:` on a Metal 3 buffer) | `MTL4FXSpatialScaler` (on the Metal 4 buffer), built by `MTLFXSpatialScalerDescriptor.newSpatialScalerWithDevice:compiler:` | the Metal 4 variants ship in the same framework |

### What the headers say about the frame's lifetime, before a line of the frame encoder is written

Read off this machine's SDK (`MacOSX.sdk/.../Metal.framework/Headers`) rather than remembered, because the
frame's ring is the one place where a guess is a use-after-free:

- `MTL4CommandAllocator.h`: `reset` "marks the command allocator's heaps for reuse", and "you are responsible
  to ensure that all command buffers with memory originating from this allocator instance are complete before
  calling resetting it". So the slot's completion is the caller's proof, not the framework's.
- `MTL4CommandBuffer.h`: "Command allocators only service a single command buffer at a time", and "you can
  safely reuse command allocators after ending the command buffer using it by calling `endCommandBuffer`" -
  while `endCommandBuffer` is also the call that "allows you to reuse the `MTL4CommandAllocator` to start
  servicing other command buffers", and committing a buffer that was never ended is an error.
- `MTL4CommandEncoder.h`: a dependency between encoders is a barrier the caller encodes
  (`barrierAfterStages:beforeQueueStages:visibilityOptions:` for the producer direction), which the sampled
  smoke above now exercises on the real device.

What that fixes for Phase 4: the frame's ring is **allocators plus the completion value each slot's commit
signalled** - the shape `Metal4Path` already runs today (`Metal4Path.java:371-381`: wait the incoming slot's
own value, then `reset`, then `beginCommandBufferWithAllocator:`) - with one command buffer re-begun per frame,
and `reset` only ever called after that slot's value has been observed. The neutral frame encoder owns that
ring, its own command buffer and its own shared event, so the frame path does not grow a second lifetime model
beside the sidecar's (§31), and the sidecar's statics collapse into the encoder when the frame path takes the
present over (§107).

### The ring itself: `MTL4FrameRing`, and the rule answered by the device

That paragraph was written as a design. The design is now an object - `mtl.metal4.MTL4FrameRing` - and the rule
it rests on has been measured on the device rather than assumed, because a ring is the one place in a frame
path where being wrong is a use-after-free rather than a wrong colour.

The object owns the allocators, a command buffer and a shared event, and it does not own the queue: the
generation that made the queue keeps it, and the ring is handed its handle. `beginFrame()` is the whole rule in
one call - pick the next slot, **wait for that slot's own signalled completion value where it has one**, reset
its allocator, then begin the command buffer on it - because that is the only place in a frame that knows the
slot is about to be handed back to the GPU, and a wait offered as a separate call is a wait a caller can forget.
`endAndSubmit()` ends, commits **once**, records the value and signals it; `awaitAll()` waits the newest value,
which is the wait a readback or a teardown needs. Nothing in it is static: the rule that the production path
should be device-owned rather than a process-global singleton (§106) is checked as a property of the file, and a
`MTL4FrameRing` cannot be created without a queue, so a second device cannot reach another session's allocators.

**The proof** is `MTL4Probe.canReuseAllocatorSlots`: twelve frames over three slots - so every slot after the
first round is reset, re-begun and re-committed while earlier frames may still be in flight - one commit each,
and three readings. Every frame owns its target, its uniform buffer and its argument table, so the sequence
isolates the lifetime question from the sharing one (a table re-bound while an earlier frame is in flight is a
binding that frame would read at execute time, and that question belongs to the frame encoder). The readings
are: every frame's pixel is its own; the ring waited for an in-flight slot exactly as many times as the ring's
own depth says it must (9 of 12 begins); and the last submission completes. Measured on Apple Silicon: **56 of
56 probes** passed in two runs (3 cold + 3 warm, then 30 cold + 20 warm, `--mode raw`), on the same device
every other smoke ran on.

**And the rule is load-bearing, which is the one thing a passing readback could not have told us.** With the
wait removed - a one-line mutation, restored afterwards - the ring's wait count assertion fires
(`the ring waited for an in-flight slot 0 times where 9 frames follow a slot's first use`), and with the count
relaxed as well the pixels answer: `frame 0 drew (0, 0, 0, 0) where (16, 0, 0, 255) was asked for, so a
submission on a reused allocator slot did not land` - the same result in five of five probes, four cold
processes and one warm. So on this device, resetting an allocator while the GPU is still reading what was
encoded on it loses the frame's work outright. That is the failure the header's sentence about the caller's
responsibility is protecting against, and it is why the ring waits rather than trusting the queue. What is
*not* measured is which of the reset, the re-begin or the commit loses the work; the observation is the lost
frame and the hypothesis is not written as a cause.

`tools/ci-metal4-cold-probe.py` pins the ring: the existence of the object, the wait and reset and begin calls
*in that order* (a reset before the wait, or a reset after the begin, both fail the contract), the recorded
completion value, the signal, the wait for everything, the release, the header the rule comes from, the
absence of static native state, and the harness's field, count and exit code - eighteen mutations run against
those pins, seventeen caught by the pins themselves. The eighteenth, a wait present in the text but
short-circuited by `if (false && ...)`, is the shape a text pin cannot see: it is caught by the sequence's own
wait-count assertion on the device, which is why that assertion exists and why the two halves are noted
together in the contract file.

### The render pass's attachments: `MTL4RenderEncoder`, and the mapping answered on the device

A pass is where an attachment's two lifetime facts turn into the load and store actions a tile-based GPU pays
for, so a mistake there is a wrong image and not a slow frame. `mtl.metal4.MTL4RenderEncoder` is that mapping
and the descriptor it is described on, and the Metal 3 semantics are kept deliberately identical, because the
images have to be:

- a clear beats the load question - a pass that asked to be handed a colour is not asking to be handed what
  stood there;
- otherwise an attachment this pass overwrites entirely is loaded `DontCare`, and one it does not is loaded;
- an attachment nothing reads afterwards is stored `DontCare`, and one something reads is stored.

The Metal 3 layer does this in `MTLCommandBuffer`; it is here rather than inside a pass object because the
actions *are* the descriptor's shape, and a second place that computed them could read the same two facts
differently. The attachment objects are Metal 3's own classes - `MTL4RenderPass.h:33` declares
`colorAttachments` as an `MTLRenderPassColorAttachmentDescriptorArray` and line 36 the depth attachment as an
`MTLRenderPassDepthAttachmentDescriptor` - read off this machine's SDK rather than assumed.

**It is measured on the device.** `MTL4Probe.canCarryColorAttachments` describes one pass with four colour
attachments cleared to red, green, blue and white, reads every slot back against the colour *that slot* was
asked for, then runs a second pass that loads slot 0's existing contents and re-clears slot 1, and a third that
attaches two more slots with the discard answers. What the readbacks assert is exactly what the API defines:
slot 0 still reads its first pass's colour (so the load and the store both happened across a pass boundary,
ordered by the producer barrier), and slot 1 reads the new colour (so a clear lands on an attachment that
already held something). The two discard slots are **not** asserted afterwards, and that is the API's contract
rather than an omission: a `DontCare` store leaves the contents undefined, so a readback there would be a claim
about undefined memory. Measured on Apple Silicon: **50 of 50 probes** passed in 30 cold processes and 20 warm
repeats.

**One fault was paid for here and is worth the paragraph.** The first version held the encoder the command
buffer handed back across the autorelease pool the factory had pushed, which is a dangling handle rather than a
nil check: the first message to it was a segfault inside `objc_msgSend`, with the crash log naming
`MTL4RenderEncoder.responds` and the FFM downcall under it. The fix is one call - `ObjC.retain(encoder)`, the
same thing `MTLCommandBuffer.makeRenderCommandEncoder` has always done - and it is now a pinned line in the
contract, because the failure mode is a crash rather than a wrong pixel.

`tools/ci-metal4-cold-probe.py` pins the mapping's two answers, the attachment loop, the retain, the pass's
end, the header the classes come from, and the smoke's own shape - every slot described from its own texture, an
attachment loaded and not only cleared, the discard answers sent, the barrier between the passes, and the
re-clear compared - plus the harness's field, count and exit code. Eighteen mutations were run against those
pins, and all eighteen were caught.

**What this does not yet do**: no pass object exists in the frame encoder, so no draw is encoded into any of
these passes and `createRenderPass` still refuses. The attachment half of the plan's MRT smoke is measured; the
half that needs a pipeline writing several targets is the next one.

## The frame encoder, and the list its refusals draw

Phase 4's other half is `render.metal4.Metal4FrameEncoder`, and what it is now is a frame's lifetime with an
empty encode path inside it. It implements the neutral `MetalFrameEncoder` - the contract the device holds - and
owns exactly three things: the ring above, the resources a frame cannot release yet, and the release order
between them.

- **The ring.** One per encoder, made from the queue the execution services answer with, so no generation owns
  the device's queue factory and no second lifetime model grows beside the sidecar's (§31).
- **The deferred releases.** `queueForDestroy` files a release against a ring slot - the frame's own slot while
  a frame is begun, the next slot otherwise - and that slot's bucket is emptied only when the ring has proved
  the slot's previous submission complete. A release that ran any earlier would be a resource given back while
  the GPU was still reading what it fed, which is the corruption the ring exists to prevent.
- **The wait.** `waitForSubmittedGpuWork` waits the ring and *then* runs the releases, in that order, and `close`
  does the same before letting the ring go. The order is the method.

**Everything else refuses, by name, one line per operation**: `transientMemory`, `createRenderPass`,
`submitRenderPass`, `clearColorTexture`, `clearColorAndDepthTextures` (both forms), `clearDepthTexture`,
`writeToBuffer`, `copyToBuffer`, `writeToTexture`, `copyBufferToTexture`, `copyTextureToBuffer` (both forms),
`copyTextureToTexture`, `createFence` and `writeTimestamp`. Each raises the provider's `Unimplemented` carrying
the operation's own name, so the refusals *are* the migration's remaining work list and a log line can be read
against the plan. Section 35 is the rule they follow: an operation this path cannot encode is never dropped
into a half frame - and a frame that says it cannot run is worth more than one that runs half of itself.

`submit()` is the one method that is neither: it ends and commits the frame **once** where a frame is begun, and
does nothing where none is. Nothing begins one yet, because a frame's begin belongs to whatever first encodes
into it and that is the render-pass path this class does not have - so `submit()` today finds no frame, which is
a fact about the migration's stage rather than a licence to skip the commit.

**What it deliberately does not implement** are the bridges' optional contracts - `MetalFrameExtras`,
`MetalFrameResourceCommands`, `MetalFramePresentation` and the rest. Each of them is an operation this path
cannot perform yet, and the bridges already treat a missing contract as the explicit answer: `MetalFrameBridge`
answers false, `MetalAttachmentBridge` does nothing, and `MetalSurface` raises naming the contract. Implementing
them with do-nothing bodies would be exactly the silent drop the plan forbids, so the class declares one
contract and lists only `MetalFrameEncoder`.

**The state beside it** is `Metal4ExecutionState`: it owns the device this generation executes on, and three of
the neutral state's four operations are true answers rather than refusals - nothing is cached, so eviction
selects nothing, clearing after GPU completion clears nothing, and closing releases nothing. The fourth,
`getOrCompilePipeline`, refuses by name: there is no Metal 4 compilation chain, and a state that answered it with
a Metal 3 artifact would be a Metal 4 path silently running Metal 3's pipelines.

**Measured on the device**: the state is made for real inside the cold-probe harness, and its four operations
answer there - `53 of 53 probes` reported

```
state=ok,stateMethods=compile:refused(getOrCompilePipeline),evict:returned,clear:returned,close:returned
```

across 30 cold processes, 20 warm repeats and the three-probe smoke of the change itself, with no
exception and no variation between them. `encoder=not-asked(needs-the-engine-device)` is recorded beside it, because the
encoder is built from the engine's device, which a bare process cannot make: asking it with nulls would raise a
NullPointerException that reads as a device fault. So the encoder's evidence is the ring's own device proof plus
a structural contract, and **no frame has been submitted through it** - nothing encodes into one yet. That is
recorded as the gap it is rather than implied away.

`tools/ci-metal4-provider.py` was updated rather than replaced, because the concept moved and did not change:
what used to be pinned as "the provider refuses the two halves it does not have" is now "the provider returns
this generation's objects, and each refuses, by name, exactly the operations it does not have". It pins the
state's three answers and its one refusal, the encoder's neutrality, the ring it makes, the queue coming from
the services, the single refusal helper, the per-slot filing of releases, the wait-before-release order, every
one of the fourteen refused operations, the absence of Metal 3 imports and the absence of static native state -
and seventeen mutations were run against those pins, all caught.

## The slices, in order

Each slice is measured before the next one starts, with the harness and the recipe in
`performance-testing.md`. A slice that cannot say what it bought is a slice that is not finished.

1. **The frame's command buffer becomes an MTL4 one, with nothing else changed.** `MetalCommandEncoder`
   begins an `MTL4CommandBuffer` where it begins the Metal 3 one, commits it through the Metal 4 queue,
   and every encoder it opens is still created the old way... which is impossible: an encoder comes from
   the command buffer it is encoded into. So this slice and the next are one: the command buffer and the
   render-pass twin move together, behind `-Dmetallum.metal4Frame=true`, with the Metal 3 path intact
   beside it.
   *Acceptance*: one no-pack scene, `windowMs` and `gpuMs` inside the floor, every counter equal, the
   picture inside the fixture's own noise, and `submit=600` with one commit a frame.
2. **Binding through tables, per layout and per stage.** One table per pipeline layout per stage, sized
   to what that layout binds. `MetalRenderPass` fills it where it fills the argument buffer or calls the
   direct setters today, and the vertices go in by address and stride.
   *Acceptance*: the pack's first full frame drawn on the new path with the picture matching the Metal 3
   road within the noise floor, and the binding counters (`texture`, `sampler`, `buffer`) unchanged - the
   same number of resources reaches the GPU, by a different route.
3. **Barriers where the fence chain is.** The engine already marks storage-image writes as unordered
   (`MetalCommandEncoder.storageUnordered`) and updates a fence at every encoder end; that description
   becomes the barrier that replaces it.
   *Acceptance*: the same picture, and a pass that reads another's storage image ordered by a barrier
   rather than by the fence.
4. **The present joins the same command buffer.** The drawable is taken where the surface says what it
   presents, the present pass is encoded after the frame's passes, and the frame's one commit is
   followed by `signalDrawable:` and `present`.
   *Acceptance*: one command buffer and one commit a frame in the probe, the present counters equal to
   the frame counters, and the picture unchanged.
5. **MetalFX moves with it**: `MTL4FXSpatialScaler` created through a `MTL4Compiler` and encoded into the
   same buffer.
   *Acceptance*: the same three render scales as P6's seat measurement, `gpuMs` not worse.
6. **The Metal 3 command buffer and the fence chain are removed**, which is when `AppKit`'s own present
   road (`encodePresentTextureToDrawable`) and the Metal 3 encoder classes lose their last callers.

### The isolation that is left is counted, not estimated

`tools/ci-architecture.py` grew a second kind of rule beside the layer rules: a ledger of every file outside
the generation packages that still names the frame path's concrete generation, checked in **both**
directions. A file that starts naming `MTLCommandBuffer`, `MetalCommandEncoder`, `MetalRenderPass` or their
kind is a regression and fails the guard; a file that stops doing so must have its line deleted in the same
commit, because a ledger nobody prunes reports work that is already done. The guard prints the total on every
run, so the milestone's cost is a number that can only go down:

    architecture guard: PASS (110 sources, 5 package rules, one mixing rule; the frame path's isolation
    still owes 17 couplings in 6 files, and 1 the other way)

Reading that ledger is what says where the facade move actually is. It is not ten members in one file:
`render/shared/MetalTransientMemory.java` names `MetalCommandEncoder` - a shared-layer file reaching into
what will become Metal 3's package, which the layer rule will fail the day the encoder moves - and
`mtl/MTLDevice.java` names `MTLCommandQueue`, with `MTLBuiltinPipelines` and `MTLStorageTexturePipelines`
naming Metal 3 encoders from the bindings side. A file naming its own class is not counted, because
`MetalRenderPass` declaring `MetalRenderPass` says nothing about generations.

The first of those is gone, and the ledger's own rule is what removed the line: `MetalTransientMemory` took
the encoder only to retire its rotated blocks, so what it needs is the **destruction queue** the encoder
itself adds to, not the encoder. Taking the same instance keeps the semantics identical by construction -
retired blocks are released on the encoder's rotation, as before - while the shared layer stops naming the
frame path's concrete class, which the layer rule would have failed the day the encoder moved to
`render.metal3`. Verified on the settled pack scene: 7.31 ms with `gpuM3Ms=4391.78` against the immediately
preceding run's 7.31 ms and `gpuM3Ms=4392.35`, every counter equal.

The second line to go needed no abstraction at all: `mtl/MTLDevice.java` named `MTLCommandQueue` only in
`newCommandQueue()`, a queue factory **nothing called** - the services build the queue from the device's
handle directly. A generation name carried by dead code is the cheapest line in the ledger to remove: the
method, its `Msg` and its import are gone, and the removal cannot change behaviour because there was no
caller to change it for (a repo-wide search for the call, not the name, is what says so).

The third and fourth are where the plan this document was carrying turned out to be wrong, and the code
said so. Two of the four bridges - `MetalAttachmentBridge` and `MetalScaleBridge` - only *ask* the encoder
things (hand the next pass its answers, ask whether the scaler is available, ask it to scale), so those
questions became a contract: `render/shared/MetalFrameExtras`, four methods on shared and game types only,
with `MetalCommandEncoder` implementing it and the two bridges dispatching on the interface instead of on
the class. **The other two bridges cannot be abstracted at all.** `MetalComputeBridge` and
`MetalDepthMipmapBridge` do not ask, they encode: their bodies drive `MTLComputeCommandEncoder` and
`MTLRenderCommandEncoder` directly, and any interface that could express them would have to hand out a
generation's encoder from the neutral layer - the layer rule fails exactly that, and it is right to. They
are Metal 3's own code, so they move to `render.metal3` with the encoder and get a Metal 4 sibling, and
`instanceof` stays their seam. An interface there would be the split undone in the name of the split.

The next caller was the same shape: `MetalDrawContext`, the sodium draw path, reached its pass through the
game's own `RenderPass` and named `MetalRenderPass` to write push constants. What it uses is two members, so
those two became `render/shared/MetalPassUniformWriter` - a mapped slice of transient memory, and a way to
bind it - and the draw path now asks for that contract, with an `IllegalArgumentException` naming the class
it actually got instead of an unchecked cast. One member had to be opened by it: `allocateTransient` was
package-private and is now public, **because the interface is what needs it** - which is the difference
between opening a member by contract and the hand-opening that produced a hundred "not public" errors in the
moves that failed.

The ledger reads 18 couplings in 7 files, and **1 the other way** - and that second number is the point of
this paragraph. `MTLBuiltinPipelines` is the neutral home of the built-in pipelines: the present pipeline
lives there once, drawn by Metal 3 through `MTLCommandBuffer` and by Metal 4 through `drawPresentWithTable`,
and the Metal 3 wrappers call into it from their own convenience methods. Wrapper calls neutral is the
direction that takes a generation out of the engine; counting it as work to be removed pushed towards pulling
the encode bodies into the wrappers, which is the opposite of the split. So the guard now lists those
separately and checks the direction is still what it claims: the neutral class must be called from inside a
generation package, or the line fails. `MTLStorageTexturePipelines` is deliberately **not** in that group yet
- it is called from `render` today, so it is debt until the encoder moves, and the ledger is where that
becomes a delegation.

The lesson is the metric's, not the code's: a count that cannot tell a design from a debt will eventually
argue for a bad change, and the fix is to make the count say which is which.

The surface followed the recipe next, and it is the closest one to the frame the migration is for.
`MetalSurface` is handed whatever backend the frame was encoded through and had to name `MetalCommandEncoder`
to present, so the take and the submit became `render/shared/MetalFramePresentation`, implemented by the
encoder and asked for by the surface - which now holds one type and presents through it, with the class it
actually got named in the exception instead. It is deliberately separate from `MetalFrameExtras`: an encoder
that can scale is not the same thing as one that can be presented through, and a caller should be able to say
which it needs.

What this does **not** yet decide is the thing the seam is really about: whether the frame presents through
Metal 3 or Metal 4 is still asked *inside* the Metal 3 encoder (`Metal4Path.presenting(layer, texture)`), so
the present-only Metal 4 path can only ever be reached by the Metal 3 path asking for it. The surface now
talks to a contract, which is where that decision can move to the execution services; until then the ledger's
`Metal4Path` entries stay. Verified on the settled pack scene: 7.25 ms, `gpuM3Ms=4359.03`, `submit=600`, with
the counters this configuration repeats (21435 encoders, 6600 blits, 345 identities against 345 keys).

### The present policy moved, and the two roads do not draw the same picture

The policy half of the present decision now lives in the execution services
(`MetalExecutionServices.presentsThroughMetal4()`, `-Dmetallum.metal4Present` parsed there and nowhere else),
the readiness half stays with the present path, and the encoder asks them in that order so a session that does
not want the road never records a layer for it. It deliberately does not yet consult `selected()`: that would
silently change which road a forced-Metal-3 session presents through, and it is the change that makes the
Metal 4 frame path the frame's own road rather than a probe.

Verified as a two-arm A/B in one session on the settled pack scene (600 frames each, camera pinned), which is
the pair the step needs because it moves a safety interlock:

    arm plain     (property off) wallP50 7.20 ms  gpuM3Ms 4355.64  metal4Presents 0   metal4Frames 0
    arm m4present (property on)  wallP50 7.27 ms  gpuM3Ms 4359.57  metal4Presents 600 metal4Frames 600
                                  gpuM4Ms 28.97, metal4Us 54.8, gpuM4Feedbacks 600 (+0.1% wall against plain)

Both roads run and both are selectable, which is the point of the step. **What the picture comparison says is
not what this document used to claim.** The compare tool reports, plain against m4present: mean channel
difference 3.65, 88.84 per cent of pixels differing at all, 9.24 per cent differing by more than 8, worst 174
at (43, 45). A difference of that size is not the 0.14-0.41 per cent two runs of **one** configuration repeat
to; the two arms differ by their own present encoding as well (the m4 arm sets 600 fewer viewports and binds
4200 more buffers, because it presents by drawing rather than by blitting), so the frames are not the same
frame either. So the honest state of the claim "the Metal 4 present shows the same picture" is: **it was made
on the earlier five-second protocol and is not reproduced by a settled two-arm run**, and until it is
explained - a different scale filter, the V-flip, the drawable's own contents, or the frame itself differing -
the Metal 4 present road is verified as *running*, not as *equivalent*.

**The difference has since been classified by re-reading the two screenshots** (the same PNG reader the
compare tool uses, so no second decoder was introduced), and two of the three candidate causes are now ruled
out:

- **Not a flip and not a shift.** Mean channel difference by alignment: identity **2.447**, vertical flip
  50.910, row shift -4 8.629, -2 6.843, -1 4.976, +1 4.472, +2 6.324, +4 8.358. Identity is the minimum by a
  wide margin, so the picture is the right way up and in the right place - the V-flip the present pipeline
  does is correct, and the frame is not offset by a row or more.
- **Concentrated at edges, with a small floor everywhere.** Splitting the pixels by the plain arm's own local
  gradient: flat pixels (624 098 of them) mean max-channel difference **1.652**; edge pixels (304 461) mean
  **8.027**; worst single pixel 174. A global tone or gamma shift would put the same offset everywhere; an
  edge-weighted error five times the flat one is the signature of **filtering** - the Metal 4 present draws the
  picture through a pipeline with `presentSampler(scaling)`, where the Metal 3 road `blit`s it, so the two
  roads resample and round differently even at one to one.

**And reading the two present implementations then ruled the filtering story out as well.** They are the same
present: the same `presentPipeline` built from the same `PRESENT_MSL`, the same three-vertex triangle, and the
same sampler rule read from the same predicate - Metal 3's `requiresScaling = width(source) != drawableWidth ||
height(source) != drawableHeight` against Metal 4's `scaling = width(drawable) != width(source) ||
height(drawable) != height(source)`. Metal 3 binds the sampler directly and Metal 4 through an argument table;
everything that decides a pixel is shared. So "the roads filter differently" is not available as an
explanation, and the edge-weighted shape has to come from somewhere else.

The remaining candidate that fits the shape is **the frame's own content, through MetalFX's temporal work**:
the m4 arm does not only present differently, it changes what happens *before* the frame's commit - the Metal 4
present waits for the drawable and the frame's commit signals the event that wait is on, so the frame is
synchronised differently and a temporal upscaler accumulating over those frames can settle on a slightly
different image. Edges are where a temporal scaler differs most and flat areas where it differs least, which is
the split that was measured (1.652 against 8.027). One counter difference points the same way: the m4 arm sets
600 fewer viewports and binds 4200 more buffers, because the present draw brings its own binding work.

**The separating test has been run, and it says the measurement method was the problem, not the road.** A
same-road pair in one session (`m4present` against `m4present`, 600 frames each, same scene, same camera):

    arm m4a  wallP50 7.24 ms  gpuM3Ms 4362.10  gpuM4Ms 28.82  metal4Presents 600
    arm m4b  wallP50 7.24 ms  gpuM3Ms 4365.27  gpuM4Ms 29.49  metal4Presents 600   (+0.1% wall)
    picture, m4a against m4b: mean channel difference 4.10, 90.95% of pixels differ at all, 11.35% by more
    than 8, 49.30% by more than 2, worst 174 at (357, 238)

**The road against itself differs more than the two roads differ from each other** (4.10 against 3.65, 90.95
against 88.84 per cent). So the cross-road picture difference is not a property of the road: it is inside the
noise this scene shows between two runs of *one* configuration, and this configuration's picture noise is
about the same size as the thing being measured. Frame time, in contrast, repeats tightly (+0.1 per cent, and
the same `wallP50` to two decimals both times).

That corrects the last three conclusions in this document's own history, and the correction is about method
rather than about Metal 4: the filtering story was ruled out by reading the two present implementations, the
frame-content story is not supported by a same-road repeat of the same size, and **the claim "the picture
matches the Metal 3 road" is neither confirmed nor contradicted by any of it** - a single end-of-run screenshot
pair cannot resolve a difference smaller than the scene's own run-to-run picture noise. The row above stays
"running", and the honest statement is that this document has no valid picture-equivalence measurement yet.

**And in that sharp scene the equivalence holds.** No-pack, camera pinned, 600 frames each, `plain` against
`-Dmetallum.metal4Present=true`:

    picture, plain against m4: mean channel difference 0.04, 0.08% of pixels differ at all, 0.07% by more
    than 8, worst 219 at (1627, 334)
    plain  wallP50 1.75 ms  gpuM3Ms 826.93  metal4Presents 0    viewport 2526
    m4     wallP50 1.75 ms  gpuM3Ms 691.99  metal4Presents 600  viewport 1926  gpuM4Ms 47.03  metal4Us 13.3

**0.04 is the same number two runs of one configuration show in this scene**, so the Metal 4 present's picture
is the Metal 3 road's picture to the limit this test can resolve - the claim this document has been carrying
since the present first drew, and which three turns of measurement could not confirm in the pack scene, is now
confirmed where the test is sharp. The two arms also agree on `wallP50` exactly (1.75 ms), and the counters
differ only where the presentation differs by construction: the m4 arm sets 600 fewer viewports (the Metal 3
present sets one per frame; the Metal 4 present leaves the encoder's default) and its present's GPU time is
accounted on the other queue (`gpuM4Ms` 47.03), which is what makes its `gpuM3Ms` read lower.

The pack scene was then given the same treatment at a scale where the scaler is out of the picture
(`--renderscale 100`: `scaling` is false, both roads use the nearest sampler), and it settled the question the
other way: `plain` against `m4present` read **2.06**, but the *control* - two runs of `plain` alone, same
session, same scene - read **36.37**. In the pack scene the road-against-road difference is smaller than the
scene against itself, at both scales measured (3.65 against 4.10 at 55 per cent, 2.06 against 36.37 at 100 per
cent), so **no picture claim is supportable there** and the no-pack scene is the only bed this test has. The
full table and the rule live in `performance-testing.md`.

**What a valid one needs was measured the same way** - the same
configuration twice, camera pinned, 600 frames each, no shader pack:

    picture, a against b: mean channel difference 0.05, 1.61% of pixels differ at all, 0.09% by more than 8

**0.05 against the pack scene's 4.10 is the whole story**: without a pack the screenshot comparison is sharp
(one and a half per cent of pixels differ at all), and with one it is not. The difference is the pack's
temporal upscaler accumulating differently over the two runs, exactly as the same-road pair suggested, and it
means the **no-pack scene is where picture equivalence can be measured** - which is the scene a frame-path
change should be judged in first anyway, by this document's own rule. The Metal 4 present has not yet been
compared there; that is the next experiment, and it is a valid one now.

### The flipping selection is a functional probe, and its first answer in a session is wrong

The two arms' capability lines differ in **exactly two fields**, and that is the whole diagnosis:

    arm a  19:49:45  ... argumentTable=false render=false compute=true ...
    arm b  19:50:25  ... argumentTable=true  render=true  compute=true ...

Everything else is identical, including `buffer=true`, `msl=msl3.2` and the MetalFX answers. Reading
`MetalDeviceCapabilities` says which two fields those are and why they can disagree: `argumentTable` is
`respondsTo(device, "newArgumentTableWithDescriptor:error:") || respondsTo(..., ":")` **AND**
`Metal4.canBindAndDraw()`, and `render` is `renderEncoder && Metal4.canBindAndDraw()`. A selector question
cannot change its answer between two processes, so the part that flipped is the **functional** half - a probe
that actually makes an argument table, binds through it and draws. **On the first run in a session it said no;
forty seconds later it said yes, on the same device and the same build.**

So AUTO's verdict currently depends on whether a functional Metal 4 probe succeeded, and its first answer in a
session is a false negative. Two things follow, and both are small:

- the probe should not turn a transient failure into a capability verdict - a retry (or a warm-up before the
  verdict is read) is the difference between "this device cannot" and "this attempt did not";
- a false negative has to be **distinguishable from an absence**, which means the probe's failure has to say
  what failed rather than collapsing into `false`. This project already holds that rule for its own guards
  ("a guard that cannot fail is a guard that is not there"); a capability probe deserves it more, because the
  whole AUTO rule - capability, never a chip name - is only as good as the honesty of this one answer.

**The repeat did not reproduce it, and that is now the state of the finding.** Three identical no-pack arms in a
later session all reported `selectedGeneration=metal4`, all three capability lines identical and all three
functional probes succeeding: `... and two passes whose resources were bound through argument tables drew what
they were told to - a uniform by GPU address, and a vertex buffer by address and stride`. So the flip is
**observed once, not reproduced on demand**, and the leading explanation is a **cold** first attempt: the
session that flipped was the first to touch Metal 4 argument tables in a while, while the session that did not
ran minutes after runs that had each presented 600 frames through them. Testing that needs a genuinely cold
state - a reboot, or a long idle, or the first run of the day - not another warm session, and it has not been
done.

Two honest notes about what this does and does not say. The `lastFailure()` plumbing added for the diagnosis
**has not fired yet**, because nothing failed in the session that was run after it: it is unproven usefulness,
not a fix. And "not reproduced in three runs" is not "does not happen": one session did flip, so a selection
that can differ between two runs of one build is a real observation, and it stays ahead of M4 - which is the
milestone whose behaviour depends on that answer - until a cold session either reproduces it or does not.

**The same run turned up something else, and it is not about pictures.** The two arms of that pair reported
different selections: arm `a` `selectedGeneration=metal3`, arm `b` `selectedGeneration=metal4`, in one session,
same device, same build, no switch between them. Two identical runs selecting different generations means the
capability verdict is not deterministic run to run, which is a problem for the one rule this migration leans on
-hardest ("AUTO is chosen from capability, never from a chip name"): a selection that flips between two runs of
one build cannot be argued about, tested against, or shipped. It is also small to chase - the probe that reads
the capabilities and the selector that consumes them are both in `render.execution`, and the log already prints
the capability line - but it comes before M4, because M4 is the milestone whose behaviour depends on that
answer.

### The present decision is two decisions, and only one of them can move

Moving "who presents" to the execution services looked like one edit and is not, and reading the condition
is what says so. `Metal4Path.presenting(layer, picture)` conjoins two different things:

- **policy** - whether the frame should present through Metal 4 at all: today
  `Boolean.parseBoolean(System.getProperty("metallum.metal4Present", "false"))`, which is a system property
  standing in for a question the selector is supposed to answer;
- **readiness** - whether the Metal 4 present can actually run: `carrying`, a queue, a command buffer, a frame
  event with a non-zero value, an argument table, four consulted selectors (`waitForDrawable:`,
  `waitForEvent:value:`, `signalDrawable:`, `renderCommandEncoderWithDescriptor:`) and a non-nil layer and
  picture.

Policy belongs in `MetalExecutionServices` - it is a question about which generation executes. Readiness
belongs where the Metal 4 objects are, because only the present path knows whether its queue and table exist.
So the shape is a conjunction: the services answer the policy, the present path answers readiness, and the
property is read in exactly one place (the services) with `Metal4Path` losing its own read.

**Two things about that step are worth writing down before it is taken.** It does **not** shrink the ledger:
the encoder still names the present path to ask whether it is ready, so the `Metal4Path` lines stay - what it
buys is that *the selector rather than a system property* decides the presentation road, which is the
precondition for the Metal 4 frame path rather than a tidying. And it moves a safety interlock: the property
is the gate on a path with a SIGABRT in its history (`signalOnCommandQueue:` was called before
`waitForDrawable:`), so it wants a two-arm session on the settled scene - the property on and off, both
against the same baseline - not a single run. Both arms are already routine here; the work is the pair, plus
the picture check that says the presented image is the frame's either way.

## Risks

- **Sixteen sampler slots are the compiler's ceiling, not the table's, and the argument buffer is the
  answer the engine already has.** Asked on the M5 Pro, four ways, and answered:
  seventeen direct samplers are **refused** - `'sampler' attribute parameter is out of bounds: must be
  between 0 and 15`; a sampler or a texture named by a resource id on a function argument is **refused** -
  `'id' attribute only applies to non-static data members`; and a table asking for **twenty sampler slots
  is accepted**, so the header's "maximum value is 16" is a statement about the documented range rather
  than a limit the runtime enforces. So the ceiling belongs to MSL, the engine's argument-buffer path is
  what carries a program with more sampled images than slots, and under Metal 4 that path is **a buffer
  bound by address** - which is the shape already proven above. What is left for those programs is
  residency, not binding.
- **Residency.** Every texture in the engine is created with `hazardTrackingMode` untracked; Metal 4 asks
  for residency sets and the present has so far worked without one. Whether a pack's frame needs a set is
  a measurement, not an assumption.
- **Pipelines.** `newRenderPipelineStateWithDescriptor:` is Metal 3's factory and its objects draw on
  Metal 4 encoders (proven), but `MTL4Compiler` also makes `MTL4RenderPipeline` objects for background
  compilation, which is where the low-frame work wants to go.
- **Machine state.** A migration this wide cannot be judged scene by scene: it needs the deterministic
  fixture the companion repository's smoke scenes provide, and the same-configuration floor taken in the
  same session, or the picture verdicts will be the sun moving.
