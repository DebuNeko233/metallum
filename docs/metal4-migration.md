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

**The engine side followed, and the client walked past it.** `Metal4FrameEncoder` now owns the pieces an
upload needs: a `MetalTransientMemory` handed the frame's own destruction queue, rotated once per submitted
frame for the same reason the ring's slots are (a staged block handed back while the GPU is still reading it is
the corruption the rotation prevents), and a `MTL4ComputeEncoder` opened on demand for the copies. The four
copies are implemented over it - `writeToBuffer` stages and copies buffer to buffer, `writeToTexture` stages
with the row arithmetic the command needs (`width * pixelSize`), `copyBufferToTexture` honours the source
origin's byte offset, `copyTextureToBuffer` files the caller's callback with the frame's releases, and
`copyTextureToTexture` is the region copy. One detail is a first-version approximation and is written down as
one: the readback callback stands in the slot's deferred releases rather than on the command buffer's
completion block, so it may arrive a frame later - the bytes are ordered correctly, the callback is not as
immediate as Metal 3's.

A copy that arrives before any pass also **begins the frame** now, through the same `beginFrameIfNeeded` the
first pass uses: a command buffer has to be begun before anything can be encoded into it, and beginning it is
also where the slot's previous submission is proved complete. And a pass that follows a copy encodes the
producer barrier, the same over-synchronisation in the other direction.

**Then the client ran again and walked past the upload.** A forced Metal 4 launch now stops at the next
operation the path lacks:

```
Unimplemented: clearColorTexture
  at Metal4FrameEncoder.clearColorTexture
  at CommandEncoder.clearColorTexture
  at net.minecraft.client.renderer.Lightmap.<init>
  at net.minecraft.client.renderer.GameRenderer.<init>
  at net.minecraft.client.Minecraft.<init>
```

so the clears were the next milestone - and the method is still the measured way to find them. (They are
implemented now, in "The clears: a load action needs a pass"; that section also has the client's next stop,
`createFence`, which is where the ladder stands today.)

**What was still refused at that point**: the pass object did not call any of this yet.
`Metal4RenderPass.setPipeline`/`bindTexture`/`setUniform`/`setVertexBuffer`/`setIndexBuffer`/`draw*` still
refused by name, so the encoder's commands had a device proof and the pass's use of them did not. (The next two
subsections are that milestone: the plan and the pass's use of it. This paragraph is the state of the migration
when the client first walked past its upload, not the state now.)

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

### What executes, and the gate before it

The selector answers which generation a session was *selected* for; what *executes* is a second fact, and until
now it was the literal `METAL3` in the device constructor. It is now decided from the preference, with the two
rules the migration asks for written into the line:

- **nothing but a forced Metal 4 launch makes Metal 4 execute.** `AUTO` selecting Metal 4 still executes Metal 3
  with `referenceShell` true, which is section 19's shape and section 74's readiness gate at once: the
  capability selector decides what the session is *for*, and a frame path the migration has not finished is not
  promoted to the road the game runs on;
- **a forced Metal 3 session executes Metal 3** whatever was selected, which keeps the reference path
  measurable exactly as section 75 requires.

A session that does execute Metal 4 says so once, at warn: the frame path is experimental, an operation it does
not encode yet refuses by name, and AUTO will not select it. Section 76's fallback is respected by not changing
the project's public behaviour: a forced Metal 4 launch the device cannot satisfy is a **startup failure with
its reason logged** - the selector's own contract, written before this milestone - and not a quiet fallback to
the old path.

**A forced Metal 4 launch has now been attempted on a real client**, which is the first time the new path is
entered by the game rather than by the cold probe. The session really did execute Metal 4:

```
WARN  Metal execution: Metal 4 EXECUTES this session because metallum.execution=metal4 was asked for. The frame
      path is experimental: an operation it does not encode yet refuses by name, and AUTO will not select it
      until the migration's readiness gate is met
INFO  Metal execution: metal4 selected, metal4 executes (Metal 4 was forced for this launch, and the device
      satisfies its minimum contract)
INFO  Metal execution seam: selectedGeneration=metal4 executingGeneration=metal4 mode=own-path
      referenceShell=false framePathReady=true
INFO  Metal shader profile: msl4.0 selected (Metal 4 executes the frame and the 4.0 toolchain is the one the
      translator was written against)
```

and then it stopped, at the first operation the new path does not encode:

```
com.metallum.render.metal4.Metal4ExecutionProvider$Unimplemented: writeToTexture: the Metal 4 frame encoder does
not encode writeToTexture yet
  at Metal4FrameEncoder.writeToTexture(Metal4FrameEncoder.java:345)
  at com.mojang.blaze3d.systems.CommandEncoder.writeToTexture(CommandEncoder.java:367)
  at net.minecraft.client.renderer.texture.DynamicTexture.upload(DynamicTexture.java:53)
  at net.minecraft.client.renderer.texture.TextureManager.<init>(TextureManager.java:43)
  at net.minecraft.client.Minecraft.<init>(Minecraft.java:596)
```

That is a startup failure and not a frame failure: the game uploads the first dynamic texture while its texture
manager is being constructed, so the Metal 4 path's next required operation is a **texture write**, long before
a draw. The migration's own order puts blit and copy after render, MRT and depth (sections 54 to 55), and the
client is what re-orders it: a frame path that cannot upload a texture cannot begin. The failure is also the
shape the plan asks for - named, at the operation, with the caller visible in the stack - and it is the roadmap
for the next milestone rather than a claim that anything was drawn.

### The copies: no blit encoder, and a client that asked first

Metal 4 has no blit encoder. The compute encoder absorbed it, so a texture upload, a texture download, a region
copy and a mip generation are commands on `MTL4ComputeCommandEncoder` rather than on an encoder of their own.
`mtl.metal4.MTL4ComputeEncoder` wraps the four copies the engine's frame path needs - whole texture to texture,
a region of one texture to another, texture to buffer, buffer to texture - with the regions passed as Metal's
own `MTLOrigin` and `MTLSize` structs by pointer, which is the same calling shape the Metal 3 layer uses so a
region means the same thing on both paths.

**The plan puts blit after render, MRT and depth (sections 54 to 55); the client re-ordered it.** A forced Metal
4 launch stopped at `writeToTexture`, raised from the game's own texture-manager construction, so the first
thing a Metal 4 frame path needs is not a draw but a **texture write** - and that is a copy. The smoke is the
plan's own blit shape, built so a region copy has something to be wrong about:

- a pattern of four flat quadrants is rendered into the source (the pattern the sampled smoke already draws);
- a **32x32 region of it at the origin** is copied into a destination's **other half**, and both the inside of
  where it landed and a pixel outside it are read - the first must be the source's top-left quadrant, the second
  must still be the destination's clear. A whole-texture copy can only be wrong about its contents; a region
  copy has four coordinates to be wrong about, and those two readings are what tell them apart;
- the **whole texture** is copied into a second destination, and all four quadrants are compared with the
  pattern, which is what says the whole-texture form carried the contents rather than a corner of them.

The copies are separated from the passes that wrote what they read by the producer barrier, as everything else
in this migration is: on this command model a copy that reads a render pass's target has to say so.

**Measured on Apple Silicon**: 50 of 50 probes passed in 30 cold processes and 20 warm repeats, with the other
five device smokes passing in the same processes.

**One trap is worth the paragraph**, because it cost a run and its message is misleading. `Msg.ofVoid` prepends
the receiver and the selector, so a declaration must list *only* the selector's own arguments: the first version
of the whole-texture copy declared three where the header has two, and the handle was then invoked with the
wrong arity. That surfaced as `objc_msgSend failed: copyFromTexture:toTexture:` - which reads as a device or
selector problem and is a declaration problem. The contract now refuses that shape by name.

`tools/ci-metal4-cold-probe.py` pins the encoder factory, all four copy selectors, the region's three structs
*together* (each helper also builds another copy's struct, so a bare pin would be satisfied there), the retain,
the barrier, and the smoke's own two readings plus its whole-quadrant comparison - seventeen mutations run, all
caught after three pins were strengthened for exactly that reason.

### The clears: a load action needs a pass, and that is the whole cost

The client's next stop after the copies was `clearColorTexture`, raised from `Lightmap.<init>`: the game clears
a lightmap as it constructs the renderer, which is before any draw. On Metal 3 that call is recorded and folded
into the next pass that uses the attachment - `MTLLoadActionClear` is applied where the attachment is first
bound, and the attachment is never loaded at all. On Metal 4 the load action still exists and still belongs to a
pass, so the first version is the simple one: **a clear is a pass of its own** that loads the attachment cleared
and stores it, with no draw in it.

That is a decision with a price and not a free translation, and the price is stated rather than implied: one
extra pass per clear, one more encoder begin/end on the frame's command buffer, and the attachment load the
folded form avoids. The migration keeps the simple form while the question is whether the path runs at all;
folding a clear into the following pass is a lifetime model of its own (the clear's value has to survive until
the pass that would carry it, and a pass that does not come means the clear must still happen), so it is a later
optimisation with its own measurement - not something to assume now and not a correctness gap today.

The three implemented forms are the client's own calls, and the fourth is left refusing:

- `clearColorTexture(texture, colour)` - one colour attachment, `CARRIED` contents cleared to the colour;
- `clearColorAndDepthTextures(texture, colour, depth, value)` - one pass, two attachments, so a colour+depth
  clear is one pass and not two;
- `clearDepthTexture(depth, value)` - a pass whose only attachment is the depth one;
- `clearColorAndDepthTextures(..., scissorX, scissorY, width, height)` - **still refuses by name**. A scissored
  clear is not the same operation: a load action holds for the whole attachment, so a partial clear has to be a
  draw over that rectangle, and that is a different mechanism (a clearing pipeline) rather than a rectangle
  passed to the same one. Nothing the no-pack frame needs asks for it yet.

**Ordering is encoded, not assumed.** A clear that lands before the copy or pass that wrote what it overwrites
is a wrong picture with no error, so `encodeClear` ends any pass the game still has open (only one encoder may
be open on a command buffer), begins the frame if none is, orders and ends an open copy encoder, opens the
clear's own pass, encodes the producer barrier in it, and closes it. The pass-follows-copy ordering is now
pinned **inside `createRenderPass`'s body and inside `encodeClear`'s body separately**: the same three lines
appear at both sites, so a file-wide pin would have stayed green while one of them lost its barrier, which is
exactly what a mutation showed before the pins were scoped to a method body.

**Then the client ran again, and it is in the render loop.** A forced Metal 4 launch walks past the texture
upload, past the lightmap clear, through `GameRenderer`'s construction and into the frame:

```
Unimplemented: createFence
  at Metal4FrameEncoder.createFence
  at CommandEncoder.createFence
  at com.mojang.blaze3d.buffers.MappableRingBuffer.rotate
  at net.minecraft.client.renderer.FogRenderer.endFrame
  at net.minecraft.client.renderer.GameRenderer.render
  at net.minecraft.client.Minecraft.renderFrame
  at net.minecraft.client.Minecraft.runTick
```

That is the first time a forced Metal 4 session has reached a rendered frame's own code path, and the gap it
names is a **dependency object, not a command**: a fence is how Metal 3 expresses "this wrote, that may read",
and this command model expresses the same thing with barriers and queue events. What the game waits on through
that fence, and what the Metal 4 equivalent of that wait is, is the next decision - it is not a wrapper.

**Measured on Apple Silicon**: the depth-clear smoke passes 50 of 50 probes (30 cold + 20 warm, `--mode raw`),
with all eight of the other device smokes passing in the same processes and the compilation chain compiling a
pipeline in every one of them - and 5 of 5 again after the comparison below was tightened. The depth attachment
is `Depth32Float`, cleared to 0.25 and read back through `MTLTexture.bytes` at a chosen pixel - a clear that
silently did nothing reads as the depth target's own contents and fails the comparison.

`tools/ci-metal4-provider.py` and `tools/ci-metal4-cold-probe.py` pin the clear encoder, each clear's own
attachment, colour and depth value, each one's pass extent taken from the attachment rather than a literal, the
barrier, the two copy-ordering sites, the depth smoke's format/value/readback, the harness's field and count,
and the driver's failure exit - **30 mutations run against them this round, 30 caught**, four of them only
after the pins were moved inside method bodies (the duplicate-anchor weakness above).

**Two of the depth smoke's own lines were strengthened after a review pass**, and neither is a finding anyone
confirmed - they are the two places where the check could not have failed for the fault it names, which is the
one thing a smoke may not be:

- the depth comparison is written as *inside the tolerance*, negated, rather than as *outside it*:
  `Math.abs(read - clear) > 0.0001f` is false for NaN, so a NaN readback would have counted as the value that
  was asked for. `!(Math.abs(read - clear) <= 0.0001f)` cannot pass that way;
- a depth pass that could not be opened used to be reported through the shared `openPass` helper, whose stage
  is the colour-attachment smoke's - so the harness line would have said the attachments smoke failed while
  the same line said `attachments=true`. The smoke now opens its own pass and reports under `depth`.

### The fence: a promise about a submission, and the same three answers

The clears moved the client into the render loop, and the next thing it stopped on was `createFence`, raised
from `MappableRingBuffer.rotate` inside `FogRenderer.endFrame`. **On Metal 3 a fence is not an `MTLFence`**:
`MetalFence` holds the encoder and the submit index that was current when it was made, and `awaitCompletion`
asks the encoder whether *that submission* has completed. The `updateFence`/`waitForFence` calls in the Metal 3
encoder are a different mechanism - the intra-frame dependency chain between encoders - and they are already
replaced on this path by the producer barrier.

**What the two callers actually do** was read off the client's own bytecode rather than assumed, because the
fence's meaning is theirs:

- `MappableRingBuffer` keeps three mapped buffers and three fence slots. `rotate()` closes the current slot's
  fence and makes a new one for that slot - from inside the frame, after the frame's work is encoded and before
  it is submitted - then advances. `currentBuffer()` finds the fence three frames later and calls
  `awaitCompletion(Long.MAX_VALUE)`, i.e. it blocks until the frame that used that buffer has completed, then
  hands the buffer to the CPU. The fence is what stands between a CPU write and a GPU read.
- `StagedVertexBuffer`'s `GpuBufferPool.endFrame` makes one fence for the frame's used buffers, and
  `PendingRecycle.tryRecycle` calls `awaitCompletion(0)` - a **poll** - recycling only when it answers true.

So a fence is one question about one submission, and there are three answers to get right. Metal 4 has no fence
object to wrap, and it does not need one: `MTL4FrameRing` already signals one monotonic value per commit on the
shared event, so this generation's fence is that value plus the ring, and `MTL4FrameRing.awaitSubmission` asks
the event. The answers mirror the Metal 3 encoder's own fence wait **exactly**, because the same callers read
both generations and a fence that means something else on one path is a bug the caller cannot see:

| the submission | poll (`timeout 0`) | wait |
| --- | --- | --- |
| committed (`value <= signalled`) | has the event reached that value? | wait the event up to the timeout |
| not committed (`value > signalled`) | `false` | refused by name: `Cannot wait on a fence for the current submit` |
| no submission at all (`value == 0`) | `true` | `true` |
| the ring is closed | `true` | `true` |

The middle row is the load-bearing one: a poll that answered true for a submission no commit has promised is a
pool handing a buffer back to the CPU while the GPU is still reading it, and Metal 3 answers the same way for
the submit it is recording.

**Which submission a fence is about** is the one decision this generation has to make, and it is the caller's
question read back: a fence made while a frame is open is about that frame - the ring's `nextSubmission()` -
because that frame is what will be committed; a fence made between frames is about the work already submitted,
`submissions()` - there is no open frame for it to be about. Both of the callers above make their fence from
inside a frame, so the first case is the one that runs; the second is what a fence made from a submission
callback or an idle path means.

**Measured on Apple Silicon**: the new smoke `MTL4Probe.canAwaitSubmissions` submits two empty frames and then
checks the contract - both committed values reach completion, the next value polls false, asking to wait for it
raises the same refusal Metal 3 raises, and a value of zero answers complete. It passed **50 of 50 probes (30
cold + 20 warm, `--mode raw`)**, with all nine of the other device smokes passing in the same processes and the
compilation chain compiling in every one.

**Then the client ran again, and it is inside a frame's draw path.** The forced Metal 4 launch walked past
`createFence` and stopped at the pass's own binding contract, which the GUI reaches first:

```
java.lang.IllegalStateException: the Metal 4 pass was asked to bind a resource with no pipeline set,
so which slot it belongs in is not known
  at com.metallum.render.metal4.Metal4RenderPass.requirePlan
  at com.metallum.render.metal4.Metal4RenderPass.setUniform
  at com.mojang.blaze3d.systems.RenderPass.setUniform
  at com.mojang.blaze3d.systems.RenderSystem.bindDefaultUniforms
  at net.minecraft.client.gui.render.GuiRenderer.executeDrawRange
  at net.minecraft.client.renderer.GameRenderer.render
```

`GuiRenderer.executeDrawRange` creates the pass, calls `RenderSystem.bindDefaultUniforms(pass)` and binds more
uniforms by name, and only then sets a pipeline per draw. That is the game's own contract - names are bound
first, the layout that turns them into slots arrives with the pipeline - and it is the next milestone, not a
defect in this one: the pass's plan exists to answer *where* a name goes, so a binding that arrives before the
plan is a binding that has to be remembered and applied when the pipeline arrives.

`tools/ci-metal4-provider.py` and `tools/ci-metal4-cold-probe.py` pin the fence and the ring wait under it: the
class and the interface it implements, the timeout conversion, the closed answer, the three-answer table, the
event the wait goes through, the submission the frame encoder promises, the smoke's five assertions (with the
refusal caught as `IllegalStateException` and not as any runtime fault, which would let a real defect read as
the contract holding), the harness's field and the driver's failure exit - **22 mutations run, 22 caught**.

### A binding is recorded by name, and resolved when the layout arrives

The cleared-and-fenced client got as far as a real draw and stopped one step before it:

```
java.lang.IllegalStateException: the Metal 4 pass was asked to bind a resource with no pipeline set,
so which slot it belongs in is not known
  at com.metallum.render.metal4.Metal4RenderPass.requirePlan
  at com.metallum.render.metal4.Metal4RenderPass.setUniform
  at com.mojang.blaze3d.systems.RenderPass.setUniform
  at com.mojang.blaze3d.systems.RenderSystem.bindDefaultUniforms
  at net.minecraft.client.gui.render.GuiRenderer.executeDrawRange
```

**The game binds by name before it sets a pipeline, and that is not an accident of the GUI.** `executeDrawRange`
creates a pass, calls `RenderSystem.bindDefaultUniforms(pass)` and binds more uniforms by name, and only then
calls `pass.setPipeline(...)` per draw inside `executeDraw`. The Metal 3 pass is built for exactly that order:
its `setUniform`/`bindTexture` put the value in a map and mark the descriptor dirty, `setVertexBuffer` puts the
slice in an array and marks the vertex buffers dirty, and `setPipeline` marks everything dirty again - the
resolution into an argument buffer happens when a draw builds one. The M4 pass had resolved every name
immediately, which worked only because the layout smoke binds after it sets a pipeline.

So the pass keeps the same three recordings - GPU addresses by name, texture-and-sampler pairs by name, vertex
layouts by slot - and resolves them against the plan:

- **a binding made while a pipeline is set** is a claim about *that* pipeline's layout, so a name it does not
  declare, or declares as the other kind of resource, is still a named fault. That is the section 35 rule and
  it is unchanged;
- **a binding made before any pipeline in the pass** is a claim about the pass's own bindings, which a given
  pipeline may or may not read - the GUI hands every pipeline all the default uniforms and most of them use
  some of them - so it is remembered and applied when a pipeline arrives, and skipped where that pipeline does
  not declare it;
- **when the pipeline changes**, the tables are new, so every remembered binding is applied to the new plan
  again. A remembered name the new pipeline declares as the other kind is skipped rather than faulted: the
  remembered value is stale for that layout, and whatever the new pipeline reads is bound by the frame path
  when it binds it.

That is one model with three answers instead of a fault at the first step, and it is the same model the Metal 3
pass runs - which is the point: the same frame has to work on both paths.

**Then the client drew.** With the bindings resolved, `executeDraw` set its pipeline, bound its vertex buffer
and its three textures, set its index buffer, and called `drawIndexed` - where the *encoder* refused:

```
java.lang.IllegalStateException: the Metal 4 encoder refused an indexed draw of 30 indices at address
1099515274752 of 120 bytes, type 0: the encoder does not answer
drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:
```

**The selector was one argument short.** This machine's `MTL4RenderCommandEncoder.h` declares

```objc
- (void)drawIndexedPrimitives:(MTLPrimitiveType)primitiveType
                   indexCount:(NSUInteger)indexCount
                    indexType:(MTLIndexType)indexType
                  indexBuffer:(MTLGPUAddress)indexBuffer
            indexBufferLength:(NSUInteger)indexBufferLength
                instanceCount:(NSUInteger)instanceCount
                   baseVertex:(NSInteger)baseVertex
                 baseInstance:(NSUInteger)baseInstance;
```

- **eight** arguments, and there is no seven-argument form. The method was declared with seven, so
`respondsToSelector:` answered no, which is why the encoder's own guard turned it into a named refusal instead
of a message send with the wrong arity. This is the second time this migration has been bitten by an Objective-C
arity (`copyFromTexture:toTexture:` was the first), and it is the second time the guard is what made it a
one-line diagnosis.

The fix is the declaration, the send, and the one place that calls it - the pass now passes the engine's
`firstInstance` through as the base instance, which is what the game's own `drawIndexed` takes.

**A device proof for indexed geometry exists now**, which the capability matrix had listed as "index PARTLY: no
probe has drawn indexed geometry yet". `MTL4Probe.canDrawIndexed` builds the one shape where the index buffer's
contents are the only way to the expected pixel:

- six vertices forming the same covering triangle twice, with two different flat colours - both exact in eight
  bits - and one index buffer listing all six as `UInt16`;
- the same pass is encoded twice, once at index 0 and once at index 3, which is six bytes into the buffer:

| the draw | what must be read back | what a wrong implementation reads |
| --- | --- | --- |
| `firstIndex = 0` | the first triangle's colour (64, 128, 128, 255) | the clear colour, where the index buffer is not read at all |
| `firstIndex = 3` | the second triangle's colour (128, 64, 128, 255) | the first triangle's colour, where the first index never becomes an offset |

The draw goes through `MTL4RenderEncoder.drawIndexedPrimitives`, so what is proven is the production method's
own selector and argument order. Measured on Apple Silicon: **50 of 50 probes (30 cold + 20 warm, `--mode
raw`)**, with the other ten device smokes passing in the same processes.

**And the client now reaches presentation.** With the binding model and the indexed selector in place, a forced
Metal 4 launch encodes the frame's draws and stops at the surface instead:

```
java.lang.IllegalArgumentException: the surface was handed a com.metallum.render.metal4.Metal4FrameEncoder,
which cannot be presented through; it asks for MetalFramePresentation rather than for a class
  at com.metallum.render.MetalSurface.blitFromTexture
  at com.mojang.blaze3d.systems.GpuSurface.blitFromTexture
  at net.minecraft.client.Minecraft.renderFrame
```

That is the whole encode path running - passes, clears, copies, fences, named bindings, indexed draws - and the
next milestone is the one the plan puts at section 38: the drawable and the present, owned by the same frame
encoder.

`tools/ci-metal4-provider.py` and `tools/ci-metal4-cold-probe.py` pin all of it: the three recordings, the
resolved-when-arrived answer, the fault for a name the set pipeline does not declare, the skip for a remembered
name a new pipeline does not read, the eight-argument selector and the send that carries all eight, the two
draws' own refusal sentences (counted, because both methods say the same thing on purpose), the smoke's two
expected pixels, its filled index buffer, its offset arithmetic and its two readings, the per-frame first index,
the harness's field, the driver's counter and its exit - **34 mutations run against the two milestones of this
round, 34 caught**, four of them only after the pins were moved to the site that matters (a readback line that
also appears in the ring smoke, a refusal branch satisfied by its own guard, a fault message satisfied by the
branch around it, and a duplicate vertex-slot expression).

### The present is the frame's own, and the first world frame hangs the GPU

The surface asked for presentation by name and refused this encoder for not being a
`MetalFramePresentation`. That interface is two members - `presentTextureToDrawable(layer, view)` and `submit()` -
and the frame already owns everything they need: the queue, the one command buffer, the commit. So the present is
the frame's own: the picture is drawn into the layer's next drawable by the engine's present triangle, encoded
into **this frame's** command buffer before `submit()` commits it, and the drawable is presented once that work
has run. One queue, one commit, one presentation path - which is the convergence the migration's section 63 asks
for. The present-only sidecar stays where it is (section 39): it presents on a second queue, ordered by a shared
event, which was the honest way to carry a picture before the frame could carry one itself.

**The header's order, read rather than remembered** (`MTL4CommandQueue.h` on this machine):

```text
waitForDrawable:   "Schedules a wait operation on the command queue to ensure the display is no longer using a
                    specific Metal drawable ... This method returns immediately and doesn't perform any
                    synchronization on the current thread. You are responsible for calling this method before
                    committing any command buffers containing commands that target this drawable."
signalDrawable:    "... after committing all command buffers that contain commands targeting this drawable, and
                    before calling MTLDrawable/present ... fails if you call it after any of the present methods,
                    or if you call it multiple times."
```

So the two halves go on either side of the commit, and the signal goes before `present` and exactly once per
drawable. The implementation holds every drawable the frame took in a list and signals and presents them after
the commit: a present that arrives while another is held must wait for the same commit rather than present the
first one early - and presenting a drawable *before* the commit that draws its picture is the one order that
shows a frame nobody drew. The triangle is drawn and not copied for the reason the sidecar already paid for: a
whole-texture copy has no coordinates to flip and presented the loading screen upside down.

**Measured, and then stopped by the GPU itself.** A forced Metal 4 launch now **presents its own frames**: the
loading screen came up through this path and the client ran more than thirty presented frames. Then, at the first
frame of the loaded world, the submission's completion never arrived - and the machine's own log says why:

```text
kernel: (IOGPUFamily) IOGPUScheduler::hardware_error_interrupt: setting channel 1 restart type to 1
kernel: (IOGPUFamily) IOGPUScheduler::signalHardwareError(eRestartRequest, ...): GPURestartSignaled
kernel: (IOGPUFamily) IOGPUCommandQueue::retireCommandBuffer(IOGPUEventFence *):
        Deny submissions/ignore app[java] with 2 GPURestarts in 86 submissions.
```

**The GPU hung and restarted.** The failing submission is not slow, it is dead, and the ring's timeout was
reporting a machine-level fault with a frame-level sentence. The ring's patience was raised to the Metal 3
encoder's own five seconds while this was being diagnosed - which is the right number anyway, because it is the
reference path's - but the raise did not fix anything and is not claimed to have: the corrected note in
`MTL4FrameRing` says so.

**The control that separates the two questions.** The same world, the same machine, the same harness, with a
Metal 3 frame and the Metal 4 present sidecar:

```text
frame-probe 30/30 ... metal4Frames=30 metal4Draws=30 metal4Presents=30
frame-probe waits drawable calls=30 p50=7.02ms p95=14.94ms max=18.00ms total=243.20ms
9.98 ms a frame, 100.2 frames a second, 3.91 ms of GPU time a frame over 30 answered frames
```

Thirty world frames, no restart in that window, and the drawable wait is 7-18 ms - so **the drawable road works
on this machine** (take, wait, signal, present) and the hang is in what the Metal 4 frame encodes for the world,
not in how it presents. That is the difference the control was run to measure, and it is why the next milestone
is not "fix the present".

**What is refused and what is not, exactly**: the present is implemented and device-observed on screen, and the
first world frame is **BLOCKED** on a GPU fault whose cause is not known yet.

**The instruments that were tried, and what each answered.**

- **Metal API validation** cannot be used on this client: with `MTL_DEBUG_LAYER=1` the engine's own Metal 4
  capability probe fails (`the uniform pass drew (0, 0, 0, 0) where (64, 128, 191, 255) was asked for`), the
  device is then judged not to satisfy the Metal 4 contract, and the game falls back to OpenGL. That is worth
  knowing for its own sake - it is the intermittent probe failure's exact shape, reproducible on demand under
  the validation layer - but it makes validation useless as a lens on the frame.
- **A pass-and-draw trace** was added for exactly this: `-Dmetallum.metal4Trace=true` logs the pipeline each pass
  sets and every draw or indexed draw it encodes, and it is off unless a session asks for it. It localized what
  the frame was doing when the GPU died - the last commands encoded are a loading-screen frame's `GUI before
  blur` pass (two indexed draws, `pipeline/gui` then `pipeline/mojang_logo`, `base vertex 14`, 30 then 12
  indices from the GUI index buffer) and then the present - which is one frame's worth of certainty and not yet
  a culprit.
- **The argument tables' lifetime was the first candidate, and it is refuted.** A table's contents are what the
  GPU reads when it runs the command buffer, and the pass was closing its tables when the pass ended - a release
  between encoding and execution. The fix is right on its own terms (a table's release is now filed with the
  frame's deferred queue, which runs only once that slot's completion has been observed), so it is kept - but
  the A/B says it is not this fault: with the release deferred, the same run stops at the same place
  (`slot 0's completion value 31 did not arrive within 5000 ms`) and the kernel logs the same `GPURestart`.

**The frame path now reads the GPU's own account of a fault.** A Metal 3 command buffer carries an
`errorDescription` the caller reads after it completes; a Metal 4 queue reports nothing back unless the commit
was given options, and then `MTL4CommitFeedback.error` is "a description of an error when the GPU encounters an
issue as it runs the committed command buffers". `MTL4FrameRing` commits with those options where the queue
offers them and reports the fault once, and `MTL4CommitOptions.error` is the reader. The first forced Metal 4
run with it said:

```text
Metal 4 frame: the GPU reported a fault in a committed submission -
The operation couldn't be completed. (MTL4CommandQueueErrorDomain error 1.) (code 1).
```

**`MTL4CommandQueueErrorTimeout`** - read off this machine's `MTL4CommandQueue.h`, where the enum's second case
is `MTL4CommandQueueErrorTimeout = 1`. So the submission did not fail validation; it **did not finish**, and the
driver reset the GPU in response. That reframes the search completely: what is wanted is a command the GPU waits
on for ever, not a command it rejects.

**A ring depth can now be asked for** (`-Dmetallum.metal4RingSlots=N`, default the migration's three) for one
diagnostic purpose: with a single slot a frame is committed only after the previous one has completed, so the
commands the pass trace prints immediately before the fault report *are* the faulting submission's. With one
slot, the faulting submission is a loading-screen frame: the atlas-animation passes (render passes into the
atlas textures, 34 draws in the blocks atlas) and the `GUI before blur` pass with its depth attachment and two
indexed draws - and, in the runs that still presented, the present pass after them.

**Three candidates are now refuted, each by an A/B that changed one thing:**

| candidate | the A/B | the answer |
| --- | --- | --- |
| the argument tables are closed when a pass ends, before the commit | filed with the frame's deferred queue instead | same stop, same value, same `GPURestart` - kept on its own merits, refuted as this fault |
| the present is what stalls the queue | the present draw removed entirely (the drawable is still taken, signalled and presented) | same timeout, same value |
| the drawable wait gates the frame on the display | `waitForDrawable:` removed (and the present pass's producer barrier with it) | same timeout, same value |

So the fault is in the frame's **own encoded work** - the passes the loading screen makes and the copies that
feed them - and the next milestone is named by the one part of Metal 4's resource model this path does not use
at all: **residency**. The header says it in as many words for the address-taking commands this path already
uses ("Use an instance of `MTLResidencySet` to mark residency of the index buffer the `indexBuffer` parameter
references"), and the device reports `residency=true`. The frame path declares nothing resident: it binds
addresses and resource ids and leaves residency to the driver's default, which is the leading hypothesis and
the next thing to measure - not to assume.

### Residency: an address is not a reference, and the GPU said so

The fault that ended every forced Metal 4 run was an MMU fault, and the fix was to say what has to stay resident.

**What the headers say, on the very methods this path uses.** The new command model binds a buffer by
<em>GPU address</em> - the argument table's `setAddress:atIndex:` and the indexed draw's `indexBuffer` - and an
address is not a reference: nothing in a command buffer keeps the allocation behind it resident.
`MTL4RenderCommandEncoder.h` says what to do about it in as many words: "Use an instance of `MTLResidencySet` to
mark residency of the index buffer the `indexBuffer` parameter references." The frame path declared nothing, and
the driver's guess came out wrong: the kernel logged a `GPURestart` and the API reported
`MTL4CommandQueueErrorTimeout` - a submission that never finishes, which is what an MMU fault looks like from
the application's side.

**What was built.** `mtl.metal4.MTL4ResidencySet` wraps the object with the four moves the header describes:
add an allocation (uncommitted), commit, request residency, and hand the set to the queue once. The frame
encoder owns one for its own lifetime - so a reload, a teardown or a second device cannot leave one session's
allocations on another's queue (section 106) - and every place the frame path binds something by address or id
declares it: a colour attachment, a depth attachment, a sampled texture, a uniform, a vertex layout, an index
buffer, and the staging blocks and textures the frame's own copies read. That is deliberately generous: this is
"declare everything the frame touches", not the per-resource READ/WRITE/SAMPLE facts sections 52 and 53 ask
for, and it is written down as the first version rather than as the design.

**The A/B, which is one line of wiring.** With the declarations: a forced Metal 4 launch runs for minutes with
no `GPURestart` in the machine's log - and reaches a *named* API fault instead (next section). Without them:
the same run, the same frame, a kernel `GPURestart` within two seconds and `MTL4CommandQueueErrorTimeout` at
the ring. **50 of 50 cold-probe processes** (30 cold + 20 warm, `--mode raw`) also pass the device smoke for it,
which proves the objects: allocations go in, they are counted, the set commits and requests residency, and the
queue answers `addResidencySet:`.

### A binding is a name the layout decides about, including when it decides nothing

With residency declared, the next stop was not a GPU fault but a named one:

```text
the Metal 4 pipeline minecraft:pipeline/panorama does not declare a binding called 'Fog',
so the frame path and the shader disagree about the layout
```

and after that one was answered:

```text
the Metal 4 pipeline binds 'CloudFaces' as a texture and the frame path bound a buffer to it
  at Metal4RenderPass.slotFor -> setUniform -> CloudRenderer.render
```

**Both of those were this path being stricter than the reference, and both were fixed by matching it.** The
engine hands every pass a fixed set of default uniforms - projection, model view, fog and the rest - and a given
pipeline reads some of them; the cloud pass binds a uniform called `CloudFaces` while its pipeline declares a
*texture* of that name. The Metal 3 pass is built for exactly this: a name goes into a map, a draw encodes the
names the pipeline's argument buffer declares, and the others are never encoded - including a name that exists
as the other kind of resource, because the Metal 3 pass keeps its uniforms and its textures in two maps. So:

- a name this pipeline does not declare is **skipped**;
- a name it declares as the other kind is **skipped**, and reported under `-Dmetallum.metal4Trace` so a pack bug
  is visible to anyone looking rather than fatal to everyone rendering;
- the plan's lookup is **kind-aware** (`slot(name, kind)`, with `declares(name)` for the distinction), because
  one namespace made a buffer and a texture that share a name collide - and the engine really does have one.

With that, the forced Metal 4 launch renders the world: it reaches **Sodium's chunk renderer** and stops at a
contract this path does not implement yet - `MetalPassUniformWriter`, the push-constant path the terrain draw
asks the pass for.

### Push constants, which is a pass that can be written into

The contract is two members, and both are read off the call site rather than guessed:
`allocateTransient(size, alignment, usage)` returns a mapped slice of transient memory that lives for the
caller's block, and `setUniform(name, slice)` binds it - which this pass already did. The slice comes from the
frame's own arena (`MetalTransientMemory`, the same object the frame's copies stage through), so its lifetime
is the frame's: the arena is rotated by the frame encoder once the submission that reads it has been made, and
the caller frees its own view. That is the whole change, and it is what makes the sodium chunk renderer's
twenty-byte camera-translation block reach a shader.

**The ladder after it.** A forced Metal 4 launch now renders the sky - the trace shows `Sky disc`, `Sky sun`
and `Sky moon` passes with their own indexed draws - and enters the terrain pass, where two things are waiting
and both are recorded here rather than fixed in passing:

1. ~~`drawIndexedIndirect`~~ - **implemented and proven on the device.** Sodium's terrain draw reaches its pass
   through `VKIndirectDrawBatch.draw`, which is the indirect indexed form: the arguments
   (`MTLDrawIndexedPrimitivesIndirectArguments`, five 32-bit members, twenty bytes) live in a buffer, and the
   header declares the selector as
   `drawIndexedPrimitives:indexType:indexBuffer:indexBufferLength:indirectBuffer:` - one command per draw, so a
   caller with several arguments in one buffer encodes this once per command and the caller's stride is what has
   to be right. The index buffer is still an address, and the header asks for the same treatment as the direct
   form: "Use an instance of `MTLResidencySet` to mark residency of the indirect buffer that the
   `indirectBuffer` parameter references, and of the index buffer the `indexBuffer` parameter references" - so
   the arguments buffer is declared too.

   Two lessons came out of writing it, both written down because both cost a run:

   - **An Objective-C selector's argument order is fixed, so the declaration has to match it** rather than the
     shape an existing overload happens to have. The first version sent the arguments in an order that fit a
     `Msg` overload - and got `objc_msgSend failed: drawIndexedPrimitives:indexType:indexBuffer:...`, which is
     the third time this migration has been reminded that the arity *and* the order are the framework's. The
     overload was added to `Msg` instead.
   - **The device smoke raced itself**: it wrote one shared arguments buffer for both frames and the first
     frame's draw read the *second* frame's `indexStart`, so it drew the wrong triangle - a CPU write racing a
     submitted read, measured. The smoke now uses one arguments buffer per frame, which is the rule a caller
     with frames in flight has to keep.

   The proof is the indexed smoke's shape with the arguments moved into the buffer: two covering triangles of
   different flat colour, one index buffer listing all six vertices, and an `indexStart` of 3 in the first
   frame and 0 in the second. The pixel says which triangle the arguments selected, so arguments that are
   ignored draw the first triangle twice and arguments that are never read leave the clear colour. 50 of 50
   cold-probe processes (30 cold + 20 warm, `--mode raw`).
2. **One binding disagrees about its kind, and the reference skips it too.** The trace says, in the terrain
   pass: `'u_SectionTimeInfo' is a buffer in the frame path's binding and a texture in the pipeline's layout, so
   it is not encoded`. The kind comes from the translation's own bind-group metadata
   (`MetalCrossShaderTranslator`: `UNIFORM_BUFFER`, `SAMPLED_IMAGE` or `TEXEL_BUFFER` per entry), so this is a
   fact about that pipeline's translated layout and not about this plan - and the Metal 3 pass does exactly the
   same thing with it: it keeps its uniforms and its textures in two maps and encodes only what the layout
   declares. The evidence that the skip is harmless on the reference is the control run: a Metal 3 frame with
   the Metal 4 present sidecar rendered thirty world frames - the same Sodium terrain, through the same
   translation - with that binding skipped in the same place. So it is written down as a note about the
   translation's metadata for `sodium:pipeline/solid_terrain`, not as a difference between the two generations,
   and the next milestone does not depend on it.

**Correction, because the first version of this paragraph claimed too much.** What the four-minute run showed
is that the **loading screen** renders with no fault: whatever the earlier terrain frame was reading by address
is declared now, and the loading screen - which used to fault within two seconds - does not. The **world frame
still faults**, and the first run that loaded a world says so: the integrated server's `Time elapsed: 1783 ms`
appears, the player joins, the chunk builder starts, and then

```text
Metal 4 frame: the GPU reported a fault in a committed submission -
The operation couldn't be completed. (MTL4CommandQueueErrorDomain error 1.)
```

with two kernel `GPURestart`s in that window. So residency is necessary and not yet sufficient: something the
world frame reads by address is still not resident, or something it reads has been let go, and that is the open
question - not a closed one.

**The frame path is not the slow part, and that is now measured rather than suspected.** A per-frame counter
line (`-Dmetallum.metal4FrameStats`, off unless a session asks) reports frames, wall milliseconds a frame,
passes, encoders, argument tables, draws, indexed draws and residency declarations once every sixty frames.
Two lines from the loading screen:

```text
frame stats: frames=60  fps=13.3  msPerFrame=75.26 passesPerFrame=1.5 encodersPerFrame=1.5 tablesPerFrame=5.6
             drawsPerFrame=153.0 indexedPerFrame=2.0 residencyPerFrame=75.6
frame stats: frames=120 fps=440.9 msPerFrame=2.27 passesPerFrame=7.0 encodersPerFrame=7.0 tablesPerFrame=10.5
             drawsPerFrame=11.4  indexedPerFrame=6.3 residencyPerFrame=1.5
```

The first sixty frames are startup - 75 ms a frame, with seventy-six residency declarations a frame as the
atlas and the pipelines arrive - and then the path runs the loading screen at **440 frames a second**. So the
per-pass argument table, the per-pass encoder and the per-frame residency commit are *not* what stands between
this path and a world frame: the world frame's own fault is, and the earlier suspicion that the frame path was
simply slow was wrong.

**What is next is isolation, not optimisation.** The world frame's fault is the only thing between this path
and a counted no-pack frame, and the instrument that has worked twice already is the trace plus a narrowed ring:
the last passes the faulting submission encoded are the world's own, and the candidates are the resources the
world frame reads that the loading screen never does. Two are named by the run itself: the game resizes its
dynamic uniform buffer *during* the first world frame (`Resizing Dynamic Transforms UBO, capacity limit of 2
reached during a single frame`), and the world frame is the first to draw indexed geometry indirectly, to use
the cubemap and cloud passes, and to read the terrain's own region buffers.

**The first narrowing is done, and it is a negative one worth having: it is not a race between frames.** The
same world frame faults with **one** slot in flight - a frame is committed only after the previous one has
completed, so nothing the path does may overlap anything else it does - and the error is the same
`MTL4CommandQueueErrorDomain error 1`, with the kernel logging restarts around it. So the fault is in one
frame's own content: something that frame reads by address is not resident, or something it reads has been let
go, or a dependency inside it is not encoded. The candidates are the resources only a world frame touches, and
the next narrowing is per-operation rather than per-frame: the frame's own passes are the instrument's next
target (the trace names them, and the terrain's indirect draw, the cubemap and cloud passes and the blit are the
ones the loading screen never encodes).

### The argument table's unbound slots faulted the GPU, and the world renders now

The world frame's fault was found, and it was not residency. **An argument table's bindings are not initialised
unless you ask.** This machine's `MTL4ArgumentTable.h` says of `initializeBindings`: "Configures whether Metal
initializes the bindings to nil values upon creation of argument table. The default value of this property is
**false**." The frame path created its tables with the default - the comment beside the call even claimed the
opposite, that an uninitialised slot "would be read as null" - so a slot this path never filled held whatever the
driver left there, and a shader that read one dereferenced it.

And this path **skips a binding by design**: a name a pipeline declares as the other kind of resource is not
encoded, because that is what the Metal 3 pass does (it keeps uniforms and textures in two maps). The engine's
cloud pass is exactly that case - it binds a uniform under a name whose pipeline declares a texture - so its
texture slot was never filled. The loading screen draws no clouds and never faulted; **the first world frame
does, and did**, which is the whole of the "world frame fault" that three rounds were chasing. The fix is one
argument: the tables are created with their bindings initialised to nil, and a nil read is zero, which is what
the Metal 3 pass does with a name its layout never encodes.

**Measured, with the path's own counters.** A forced Metal 4 launch now loads a world and renders it:

```text
Time elapsed: 1783 ms                     (the integrated server completes the load)
Metal 4 frame stats: frames=9360  fps=300.6  msPerFrame=3.33  passesPerFrame=15.0 encodersPerFrame=15.0
                     tablesPerFrame=22.3 drawsPerFrame=33.8 indexedPerFrame=5.0 residencyPerFrame=1.0
```

Nine thousand frames, no fault, no kernel `GPURestart`, and no refusal: **the Metal 4 path renders the no-pack
world at about three hundred frames a second**, with fifteen passes, fifteen encoders, twenty-two argument
tables and thirty-four draws a frame. What is *not* claimed: that the picture is right. Nothing has compared it
with Metal 3's, and the standard harness cannot collect this run yet (next paragraph).

**The harness's next gap, which this run exposed.** The no-pack arm line appears, the run is collected as far as
the screenshot, and then the harness waits for the frame probe's window - which never opens, because
`MetalFrameProbe` is fed by the Metal 3 encoder (`encoderOpened`, the submit window, the frame end) and the
Metal 4 path reports only its pipeline compilations to it. So a forced Metal 4 run is measured today by the
path's own counters and nothing else, and **feeding the frame probe from the full-frame path** is the milestone
that makes the two generations comparable in the standard way - which is what the plan's sections 37, 70 and 94
ask for before any performance claim.

### The probe is fed by the full-frame path, and the first Metal 4 frame is measured

The standard harness waits for the frame probe's window line before it counts anything, and the probe was fed by
the Metal 3 encoder alone - so a forced Metal 4 run was "never collected" however well it rendered. Every
counter the probe prints is now reported from where the Metal 4 path has the fact: the frame boundary
(`frameSubmitted`, which opens the window), the encoders it opens by kind (render pass, copy, clear), each
attachment with its pixel size and its load and store, every binding it fills (pipeline, texture, sampler,
buffer), the scissor, each texture copy as a blit, each present the frame makes, the ring's slot-reuse wait, and
**the queue's own per-commit GPU time** from the commit feedback the ring already reads. The Metal 3-specific
columns (`encoders`, `submit`, `passChanged`, `viewport`) stay zero for this path and say so rather than
pretending: they count a mechanism this generation does not have.

**The first collected run found a gap in the probe itself.** It reported `gpuM4Ms=62.65` over thirty frames with
every `gpuP*` at zero: the queue's feedback times were being accumulated and never made into percentiles, so a
Metal 4 frame had a GPU total and no distribution. The probe now keeps those samples too and prints
`gpuM4P50/P95/P99/Max` beside the Metal 3 ones - a *second* set rather than one, because the two sums already
carry generation names and a percentile read off a mixed set would describe neither.

**The first measured no-pack Metal 4 frame** (1280x720, windowed, no pack, the pinned world):

```text
m4: 8.02 ms a frame, 124.7 frames a second
frame-probe 30/30 windowFrames=30 windowMs=240.65
  selectedGeneration=metal4 executingGeneration=metal4
  gpuM4Feedbacks=30 gpuM4Frames=30 gpuM4Ms=63.48
  wallP50=8.48 wallP95=8.96 wallP99=9.00 wallMax=9.00
  gpuM4P50=2.08 gpuM4P95=2.31 gpuM4P99=2.34 gpuM4Max=2.34
  loadedMiB=9387.8 storedMiB=9387.8 depthLoadedMiB=4640.6 depthStoredMiB=4640.6
  pipeline=1960 texture=745 sampler=745 buffer=2450 scissor=90
  waits: drawable calls=30 p50=7.39ms p95=7.57ms max=7.58ms total=209.49ms
```

**What those numbers say, and what they do not.** The frame costs 8.02 ms of wall time, of which **7.39 ms is the
drawable wait** - the layer handing out a drawable at the display's rate - and **2.08 ms is the GPU's own time**
from the queue's feedback. So this frame is paced by the display and not by the GPU or by the frame path's own
work, which is the shape a first full-frame path should have and is worth knowing before anyone asks whether
Metal 4 is faster. What is *not* claimed here: a comparison. The Metal 3 arm had not yet been run on the same
scene in the same session (the plan's section 114 asks for exactly that alternation) and the picture had not been
compared (section 37) - both of which the comparison below then did, and did byte-for-byte.

**The 9387.8 MiB that looked like an unexplained 313 MiB a frame was two things and neither of them was the
contents facts.** One was the `CARRIED` claim written here first: this path did mark every attachment `CARRIED`,
but so did Metal 3 on a no-pack frame, because those facts are the *pack side's* and no pack was loaded - so
`CARRIED` could not have been the difference. The other was that the counter was reading only the game's passes:
the clear encoders and the presents contributed nothing to it. What the numbers are, and what the traffic's real
mechanism is, is in "The attachment facts reach the pass, and the counter stops leaving the clears out".

### The no-pack comparison: the same picture, the same pace, different mechanisms

The two generations now run in one harness invocation, on the same world, at the same size, with the same
settle - which is the alternation the plan's section 114 asks for and the structural record section 70 asks for
in place of a claim. The run, both arms in sequence:

```text
m3: 8.06 ms a frame, 124.1 frames a second, 4.94 ms of GPU time a frame over 30 answered frames
m4: 8.08 ms a frame, 123.8 frames a second, +0.2% against m3

picture, m3 against m4: mean channel difference 0.00, 0.00% of pixels differ at all,
                        0.00% differ by more than 8, 0.00% differ by more than 2, worst 0 at 0,0
```

**The picture verdict this section first drew from those numbers is withdrawn, and the reason is an instrument
fault.** The two `screen.png` files do hash to the same SHA-256
(`e9a463183b9845376a0a179c1abf677605c4640e8aa6fde3292c469fe2f56519`) - because both are a **single black pixel
colour**, 3600x2338 of `(0,0,0)`: `screencapture` photographed a locked or asleep display, not the game. Two
pictures of nothing compare as perfectly identical, and the comparison printed "0.00% of pixels differ ... worst 0
at 0,0" for them. So the harness's own line was evidence of the display's state and of nothing about either
generation's frame. Three claims in this record were built on it before the file was opened, and all three are
withdrawn here; what survives is the probe's counters, Vitrail's own chain lines, and the absence of a fault or a
refusal - none of which says the frame *looks* right. The instrument now refuses that verdict (see "A picture
column that is not a picture"), and the no-pack frame's appearance is **NOT MEASURED**.

**The pace is the same, and it is the display's.** 8.06 against 8.08 ms, and in both arms about 7.4 ms of that is
the drawable wait the layer imposes at the display's rate (`drawable wait p50 7.45 / 7.41 ms`). So this comparison
says nothing about which generation is faster: both are waiting on the same display, and a scene that is
display-paced cannot separate them. A performance comparison needs a scene where the GPU or the encode path is
the limit, and it needs the two GPU numbers to be comparable first.

**The two GPU numbers are not comparable yet, and the record says so.** Metal 3's `gpuP50 4.92 ms` comes from
`MTLCommandBuffer.gpuMillis` (the driver's own times for a whole command buffer); Metal 4's `gpuM4P50 2.04 ms`
comes from `MTL4CommitFeedback.GPUStartTime/GPUEndTime`. Both are whole-submission numbers and their *kinds* look
alike, but section 92's rule is that the three timing kinds - CPU encode, GPU counter, whole-command-buffer
driver time - are not interchangeable until that is established, and nothing has established that these two
fields measure the same interval. The number is recorded as what each API said, not as a speed-up.

**The structural differences are the migration's own mechanisms, and they are counted.** Section 70 asks for the
logical facts to match and does not ask the native mechanisms to:

| what | M3 | M4 | why they differ |
| --- | --- | --- | --- |
| pipeline identities | 100 | 100 | the same shader programs, which is the comparison's anchor |
| render passes opened | 120 | 360 | **not the same unit**: Metal 3 counts the native encoders it *creates* and reuses one across consecutive passes (`reusePercent 93.9`), Metal 4 counts every logical pass, each of which opens its own |
| clear encoders | 0 | 150 | a clear is a load action, so each clear is a pass of its own here; Metal 3 folds it into the pass that uses the attachment |
| depth attachments | 90 | 330 | **incomplete before the correction below**: a clear's depth attachment plus the pass's, with the clear's half not counted at that time |
| attachment bytes loaded | 950.3 MiB | 9387.8 MiB | **undercounted, and not because of `CARRIED`** - see the correction below |
| attachment bytes stored | 2637.8 MiB | 9387.8 MiB | the same |
| pipeline binds | 460 | 1920 | a table is filled where the pipeline changes, per pass |
| scissor | 330 | 90 | counted where the render encoder is given one |
| viewport | 150 | 0 | the game's render-pass interface has no viewport call at all; Metal 3 counts the encoder's own |

The traffic row is the one real inefficiency this comparison names, and it is measured on **both** sides rather
than suspected - but the two sentences this section first wrote about *why* it differs were wrong, and the round
that gave this path the contents facts is what showed it. They are corrected in the next subsection, which also
records what the counter had been leaving out.

### The attachment facts reach the pass, and the counter stops leaving the clears out

Two things were true and neither was the one the comparison above claimed.

**The per-attachment contents facts did reach Metal 3 and not Metal 4, and now they reach both.** They arrive
through `MetalFrameExtras`, which `MetalCommandEncoder` carries and `Metal4FrameEncoder` did not: the pack side
states, before each pass, whether anything reads each colour attachment afterwards and whether this pass writes
every pixel of it (`AttachmentContents`), and those two facts become the pass descriptor's store and load
actions. The mapping itself - a clear beats the load question, an overwritten attachment is loaded `DontCare`, an
attachment nothing reads is stored `DontCare` - was already in `mtl.metal4.MTL4RenderEncoder` and already
measured on the device; what did not exist was the road from the pack side to it. Now:

- `Metal4FrameEncoder implements … MetalFrameExtras`, keeps the statement, and **takes and clears it before the
  pass is built**, exactly as the Metal 3 encoder does, so a pass nobody described cannot inherit the last
  described pass's answers;
- `Metal4RenderPass` resolves the statement per slot with `AttachmentContents.resolve` (no array, a short array
  and a null slot all mean `CARRIED`, the answer that changes nothing), and opens the descriptor with it;
- the other three members of that contract answer what is true of this generation rather than pretending: the
  storage-image boundary it asks for is already encoded after every pass here (each logical pass is its own
  native encoder and ends with `barrierAfterStages:beforeQueueStages:` over all stages), and `metalFxAvailable`
  is false until the Metal 4 scaler exists - which is what this encoder answered before it carried the contract
  at all, so a caller's fallback road is unchanged. `MetalFrameResourceCommands` stays absent on purpose.

**The counter was reading only part of the frame.** `MetalFrameProbe.attachment` was called from the game's pass
object alone, so the 150 clear encoders a frame opens here and the 30 presents contributed nothing to
`loadedMiB`/`storedMiB` - and a frame that clears in five passes of its own read as cheaper than one that folds
those clears into the passes that use the attachments, which is precisely the comparison those counters exist
for. The counting is now a function of the attachment the descriptor is opened with
(`MTL4RenderEncoder.countAttachment` / `countDepthAttachment`, beside the load/store mapping so the two cannot
drift), and every pass this path opens goes through it: the game's passes, the clear passes and the present.

The measurement, same scene and flags as the comparison above, one harness invocation per session, both arms in
sequence:

```text
                            before the counter covered clears     after
m3 loadedMiB / storedMiB          950.3 / 2637.8           950.3 / 2637.8
m4 loadedMiB / storedMiB         9387.8 / 9387.8         9409.1 / 13206.0
m4 depthAttachments                     330                     480
m4 depthLoadedMiB / storedMiB   4640.6 / 4640.6         4640.6 / 6750.0
m4 renderPasses / clearEncoders  360 / 150                366 / 150
```

- **The 150 clear encoders are visible now**, exactly: `depthAttachments` rises by 150, one per clear pass, and
  `depthStoredMiB` rises by 2109.4 MiB while **`depthLoadedMiB` does not move at all** (4640.6). That is the
  mapping showing up as a measurement - a clear is not a load.
- **`storedMiB` rises 40.7%** (9387.8 → 13206.0) for the same picture: the frame was always storing what its
  clear passes wrote; the counter was not counting it.
- **`loadedMiB` moves +21.3 MiB (0.23%), and no clear can do that.** The six extra render passes this window
  reported (`renderPasses 360 → 366`) are the explanation, and the arithmetic is close: six loaded 1280x720 BGRA
  attachments are 21.1 MiB. This is churn in the scene's pass count between sessions, not an effect of the
  coverage - and the depth half above is the control that says so.
- **The picture column was void, which was not known at the time.** All four arms' `screen.png` hash the same
  because all four are one black colour: the display was not photographed. The clean re-run of the same pair
  (`/tmp/clean-nopack`, three stale clients killed first) reproduced every counter above to the digit - `m3
  950.3/2637.8`, `m4 9387.8/13184.7`, `depthAttachments 480`, `depthLoadedMiB 4640.6` - so the stale clients
  were inert for these counters, and the `loadedMiB` difference is the pass-count churn as attributed.
- **The pace did not move either**: `8.04 / 8.06 ms` a frame for Metal 4 against `8.06 / 8.06 ms` for Metal 3, in
  a scene where ~7.4 ms of each frame is the drawable wait.

**What is now the real mechanism of the traffic gap, stated as measured facts.** Metal 3 creates 4 native render
encoders a frame and reuses one across consecutive passes that agree on attachments and contents
(`reusePercent 93.9`); Metal 4 opens one native encoder per logical pass. Metal 3 folds a clear into the pass
that next uses the attachment, so the attachment is never loaded; Metal 4 clears in a pass of its own, so the
pass that follows loads the attachment again. Both of those are the *design* the first version chose - section
62's over-do-it-first, and the clear's own javadoc says the extra pass is what it costs - and neither is the
per-attachment contents facts, which change nothing on a frame that states nothing. The contents road is what a
*pack* will use; the clear-and-reuse mechanism is what this path pays for without one.

**What is NOT proven yet, and has to be said plainly.** No pack has stated anything to this path on the device.
With `--no-pack` nothing calls `MetalAttachmentBridge`, and the Metal 4 arm's numbers are unchanged to the
probe's own precision by wiring the road (the `before` column above is this round's own re-run of the previous
session's flags) - which is evidence that the road is inert until it is used, and *not* evidence that a stated
`DontCare` reaches the descriptor on a device. That evidence is the smoke-pack staircase (plan section 66) and
the MRT fixture, where a pack's `stillRead`/`writesEveryPixel` answers arrive; the structural half is pinned in
`tools/ci-metal4-provider.py` and mutation-proved (18 mutations of the wiring, the per-slot default, the
take-and-clear order, the clear/present coverage and the two scaler answers, every one of them caught).

### A pack reaches Metal 4, and the capability dispatch decides which facts arrive

The paragraph above ended with "that evidence is the smoke-pack staircase". It was taken: Vitrail's own
`attachment-traffic-contract` fixture - unchanged, staged as a zip from a copy outside the instance - ran
through the Metal 4 path on the pinned no-pack world, four arms in one session:

```text
Vitrail: This pack's first full frame opened 13 render passes, cleared 12 textures and copied 0, for 0 queue submits
m3:  renderPasses=390  clearEncoders=0    pipelineIdentities=105  loadedMiB=3903.4  storedMiB=7940.3
m4:  renderPasses=600  clearEncoders=150  pipelineIdentities=105  loadedMiB=11497.2 storedMiB=17643.4
m3: 8.02 ms a frame, 124.7 fps, gpuP50 5.48   m4: 8.04 ms a frame, 124.3 fps, gpuM4P50 3.60
```

The same pack line, the same 105 pipeline identities, 20 logical passes a frame on the Metal 4 arm, no fault, no
refusal, no `GPURestart`, and the same display-paced frame time. **The pack's two facts did not arrive, though,
and the reason was one contract away from them.** The client installs its capability adapter from
`MetallumFrameBridge.supports(backend)`, which asks Metallum's flat bridge whether the encoder carries
`MetalFrameResourceCommands` - and Metal 4 deliberately did not carry it, because its three operations are not
implemented. So the adapter was absent as a whole: attachment contents, mipmaps, storage images, compute and
scale together. The attachment half is the half that works here.

The two arms say it in three ways at once, and this is what a measured mechanism looks like when two of them
agree by accident:

| | M3, elide off | M3, elide on | M4, elide off | M4, elide on |
| --- | --- | --- | --- | --- |
| bridge's own line | absent | **"the backend was told what a pass needs of 1 colour attachment slot(s)"** | absent | **absent** |
| `loadedMiB` | 3903.4 | 3481.6 (-421.8) | 11497.2 | 11075.3 (-421.9) |
| `storedMiB` | 7940.3 | 7096.6 (-843.7) | 17643.4 | 17643.4 (-0.0) |

The load figure moves on Metal 4 by almost exactly Metal 3's amount *without a statement*: `takeClearOrEmpty` is
the client's own fallback for a backend it cannot tell - an explicit zero clear where the pass had none, which
costs a load no longer. The store figure cannot move that way, because a store is only elided by the fact itself,
and it did not move at all. So the road this migration wired was unreachable on the client, and no counter on its
own would have said so: the load column reads like success.

**The fix is to carry the contract and answer no per operation**, which is the contract's own shape - every
caller takes a boolean and has another road for false - with the reason said once per operation. `Metal4FrameEncoder`
now implements `MetalFrameResourceCommands` and refuses `generateMipmaps`, `clearStorageTexture` and
`copyStorageTextureRegion` by name. What that buys is not those three: it is the dispatch. Measured after, same
fixture pack, same session shape, and reproduced in a second session:

```text
                    m4          m4elide
loadedMiB        11497.2        11075.3   (-421.9, -3.7%)
storedMiB        17643.4        16799.7   (-843.7, -4.8%)
```

`storedMiB` falls by 843.7 MiB - **Metal 3's own figure to the tenth of a MiB** - and the client's "the backend
was told" line appears on this path for the first time. Two generations, two independent mechanisms of delivery,
one number: that is the contents road proven on the device rather than pinned in a file. The three operations stay
unimplemented and unclaimed: the Metal 4 compute encoder carries copies and barriers and no mipmap call, a storage
texture is written by a dispatch or a fill this path has not got, and a 3D region copy is a subresource move where
the copies here are whole-texture and 2D.

**A picture column that is not a picture.** Every `screen.png` of these sessions is a single black pixel colour:
`screencapture` photographed a locked or asleep display. Two of those compare as byte-identical, and the
comparison printed `0.00% of pixels differ` for them - which is how two rounds of this record came to claim a
byte-identical picture between the generations, and why that claim is withdrawn. The instrument now refuses it:
the comparison finds a capture whose pixels are all one colour, prints NOT COMPARABLE with the colour it found
instead of a difference figure, and exits non-zero; the harness asks the same question of a test capture before
its first launch, marks the session's picture column void when the display cannot be photographed, and ends 9 if
it was. The counters still run - they are the measurement, and the picture is the aid - but no session can end
zero with photographs of nothing in it.

**What this milestone does not say.** That the pack's frame is *correct*. The Metal 4 arm's counters and the
client's chain lines say the pack's passes were opened, its programs compiled (identical identities), its targets
cleared and its facts delivered; they do not say the image is right, and no picture was taken. The fixture has an
acceptance test for exactly that - its negative controls are designed so a wrong elision changes pixels - and it
has not been run. That is the next rung, and it needs a display that can be photographed.

### The MRT smoke's drawn half, and two faults a fixture found that reading did not

The MRT smoke had a pass half - four attachments, four clears, four readbacks - and no draw. Four clears put
four values in four slots whatever the pipeline declares, so the pass half cannot tell a four-output fragment
stage from a one-output one, nor a permuted slot order from a correct one. The drawn half is now the probe's
`canDrawMultipleTargets`: one pipeline built with one format per slot, one fullscreen triangle from
`[[vertex_id]]` alone (no vertex buffer, no argument table, so nothing else can fail in the same run), four
`[[color(n)]]` outputs writing four distinct values, and each attachment read back against the value that
slot's own output writes - **at both corners**, because a draw that covered part of a target would pass on the
one pixel a fullscreen triangle happened to reach. Measured on this machine: 50 of 50 probes (30 cold
processes + 20 warm repeats), with every other smoke green and no failure stage.

**Two faults were found by running things rather than by reading them, and both are recorded in the code.**

The first is this smoke's own: its first version never called `beginCommandBufferWithAllocator:` on the buffer
its pass was opened on. The machine did not refuse the encoder - it took the process down with a SIGSEGV
inside `IOGPUDeviceGetNextGlobalTraceID`, with the crash report's own frame reading
`-[IOGPUMetal4RenderCommandEncoder initWithCommandAllocator:]`. It was attributed by printing one line before
each smoke and reading which line came last; the fix is one call, and the pin that refuses its absence carries
the reason.

The second is the frame path's, and Vitrail's MRT fixture found it: a descriptor with a colour slot the caller
left **unfilled** - which is the shape its opaque coverage path produces, one draw buffer against three
fragment-output ranks - killed the frame with

```text
java.lang.NullPointerException: Cannot invoke
"com.metallum.mtl.metal4.MTL4RenderEncoder$Color.texture()" because "color" is null
    at MTL4RenderEncoder.open(MTL4RenderEncoder.java:189)
    at Metal4RenderPass.<init>(Metal4RenderPass.java:242)
```

`Metal4RenderPass` leaves a null for an unused slot and always has; the encoder's loop dereferenced it. An
unused slot is now left empty at its own index, which is what the Metal 3 descriptor loop does with the same
slot, and **not** compacted: compacting would move the attachments that are there to other slots' numbers and
the picture would be a permutation of the right one. The smoke gained a pass of exactly that shape - a filled
slot, an unused one, a filled one - and the readback says the filled slots kept their indices.

**With that, the MRT fixture runs on this path.** Same session, both generations, the fixture's own programs
unchanged:

```text
m3: renderPasses=450  clearEncoders=0    pipelineIdentities=134  loadedMiB=7278.4   storedMiB=13002.8
m4: renderPasses=570  clearEncoders=180  pipelineIdentities=134  loadedMiB=11919.1  storedMiB=20174.7
m3: 8.03 ms a frame, 124.5 fps, gpuP50 5.60    m4: 8.06 ms a frame, 124.1 fps, gpuM4P50 4.64
```

The same 134 programs, 19 logical passes a frame against Metal 3's 15, 30 presents in the window, no fault
and no refusal. **What that does not say is that the picture is right**: the fixture's acceptance is four
coloured quadrants read off a screenshot, and the display cannot be photographed, so its picture column was
void and the MRT frame's correctness was NOT MEASURED at the time.

**The quadrants are now read, and the check the fixture was written for is what closes it.** The readback road
exists on both arms (the picture the present sampled and the drawable it wrote, five by five, top row first), so
the fixture's own acceptance is readable without a display. Its `composite.fsh` writes four attachments by name -
`DRAWBUFFERS:0123`: `gl_FragData[0]` red, `[1]` green, `[2]` blue, `[3]` white - and its `final.fsh` samples one of
them per quadrant, so **the presented frame is the slot table**: each quadrant of the image is one attachment's
colour, and a permuted slot ordering would be a permuted picture. Two arms, one scene, this fixture, 25 seconds of
settle, 3168 and 3163 readbacks:

| | Metal 3 (picture / drawable) | Metal 4 (picture / drawable) |
| --- | --- | --- |
| memory-top rows, left \| right | red (`000000fe`, RGBA8) \| green (`0000ff00`) | red (`000000ff`) \| green (`0000ff00`) |
| memory-bottom rows, left \| right | blue (`fffe0000`) \| white (`fffefefe`) | blue (`00ff0000`) \| white (`00ffffff`) |
| drawable after the present flip | blue \| white on top, red \| green below | blue \| white on top, red \| green below |
| frames at that arrangement | 3168 of 3168 (values wobbling 248-255: the fade) | 3008 of 3008 flat frames, exactly |

So **the slot ordering is proven on both arms**: colour target 0 carries red, 1 green, 2 blue and 3 white, they
are not permuted, the per-quadrant channel is the one the shader wrote, and the Metal 4 arm reproduces the Metal 3
arm's arrangement sample for sample - the only difference between the arms' frames remains the alpha channel
already registered (Metal 4 alpha 0 everywhere; the Metal 3 frame's alpha is spatially structured here, 255 in the
screen's top rows and 0 below the middle, which is a property of the frame's own passes and is what the
pass-boundary instrument is for). Structural evidence from the same pair agrees: the same four colour targets at
2560x1440, the same `composite` (4 attachments) and `final` (4 samplers) passes, the same 2 descriptors, no
`GPURestart` and no refusal in either arm's log.

One cross-arm difference in those logs is **registered and not claimed as a defect**: Vitrail prints its doubled
targets as `[3, 2, 1, 0]` on the Metal 3 arm and `[0, 3, 2, 1]` on the Metal 4 arm. Those are the same cyclic
order rotated by one step - the ping-pong phase at the moment the line is printed - and the picture that comes out
of both is the same arrangement, so nothing measured depends on it; it is written down because a rotation is the
kind of difference that would matter to a temporal chain, and this fixture is not one.

### The depth smoke: a compare that rejects, a write that records, and two faults of the smoke's own

Depth had a clear and a readback. A pass that carries a depth attachment and empties it says nothing about a
compare function or a depth write, so the smoke is now two triangles at known depths: a near lower-left one at
0.25 and a far one at 0.75 covering the target, one pipeline that declares a `Depth32Float` attachment, one
less-than state with writing enabled, and **the far triangle drawn second on purpose**. The near one has
already written 0.25 where they overlap, so a compare rejects the later fragments and the overlap stays red,
where a pass whose depth state did nothing would paint the whole target green.

Four readings, and two of them are a pair: the overlap's colour (the near triangle) and its depth (0.25, so
the winner wrote the buffer), then a pixel outside the near triangle reading the far triangle's colour and its
0.75, so a compare that rejected *everything* fails there too. Measured on this machine: 50 of 50 probes (30
cold processes and 20 warm repeats), every other smoke green, no failure stage.

**Both faults the smoke has had were its own, and the second one was only visible to the warm population.**

The first was the pixel it read: the near triangle's interior is `x ∈ [-1, 0]`, `y ≤ 1` and `y ≥ 2x + 1`, and
the smoke's first version read `(8, 56)` - inside the far triangle only. So it reported a depth compare that
had never been asked to reject anything. Getting there took two experiments that are worth keeping as method:
a `Never` compare read black, which proved the *state* was applied (so the fault was not the state), and
reversing the draw order changed nothing, which proved the failing pixel was not about order either.

The second was a release. The smoke released the depth-stencil state it was handed, and that state is
**cached**: `MTLBuiltinPipelines.ensureDepthStencilState` hands the same object to the engine's own clears for
the life of the process. The second probe of a warm process then died inside `objc_msgSend` with the selector
`release` and a receiver that was already a freed pointer - the crash report's own registers carrying the
selector string `release` and a garbage receiver. The engine already gets this right (`Metal4CompiledRenderPipeline.close`
says in as many words that the state belongs to the compilation context, and releases it once with the rest of
the context), so the smoke was the only thing wrong. **A fault that only repeats can find**: one probe per
process would have passed for ever.

With the compare and the write measured, the frame path's depth road was run as a fixture: Vitrail's
`depthtex0-contract`, whose composite samples the `depthtex0` the terrain wrote and writes a derived value to
another target.

```text
m3: renderPasses=330  clearEncoders=0    depthAttachments=150  pipelineIdentities=103  loadedMiB=3059.7   storedMiB=6252.8
m4: renderPasses=540  clearEncoders=150  depthAttachments=510  pipelineIdentities=103  loadedMiB=10653.4  storedMiB=15955.9
m3: 8.05 ms a frame, 124.2 fps, gpuP50 5.27    m4: 8.08 ms a frame, 123.8 fps, gpuM4P50 3.14
```

The same 103 programs, 18 logical passes a frame against Metal 3's 11, 30 presents, no fault and no refusal.
**That paragraph's next sentence used to read "the game's own draws write depth on this path and a pack pass
samples it afterwards", and the picture refutes it**: the road runs, and no geometry writes that depth on this
path at all - see the section below, which is what reading the pixels rather than the fault list found.

### The picture says otherwise: a no-pack Metal 4 frame is a clear, and the world's terrain never reaches a pass

The two fixtures above were run with the readback road on both arms, and the depth one is the first fixture to
contradict a Metal 3 arm rather than agree with it. That contradiction is the finding, and chasing it found
something bigger than the fixture.

**The depth fixture, read.** `depthtex0-contract` samples the game's depth texture and paints green where it
*varies* between a pixel and its right or down neighbour (a geometry edge), cyan where it is valid but flat, and
magenta where it is outside 0..1. Forty seconds of settle, ~4950 readbacks an arm: the Metal 3 frame is
**100152 green samples against 21380 cyan** - the world's geometry is in the depth buffer - and the Metal 4 frame
is **cyan at every one of its 119625 samples**. A second diagnostic fixture, `depth-value-contract`, paints which
value instead of whether it varies (red for the clear, blue for zero, green for a real depth, magenta for
something that is not a depth at all): Metal 3 reads 100152 green and 21380 red, Metal 4 reads **red for 121500 of
123575 samples**. So the pack's `depthtex0` binding is right (a real depth texture, not an empty or unbound one)
and the depth buffer is cleared correctly, and **no geometry writes it**.

**The no-pack frame, read.** A session with no pack needs no fixture to compare, and it is the Definition of
Done's own "no-pack frame passes" item. Same world, same spawn, same anchor, same switch, forty seconds, ~4950
readbacks an arm:

| | Metal 3 | Metal 4 |
| --- | --- | --- |
| most common frame, all twenty-five samples | sky rows `88b0ff`/`85aeff` over grass and dirt `366821`/`412d1e`/`446b33` | **`00b8d2ff` at every sample** |
| mean BGRA | `(67, 86, 71, 254)` - a world | `(255, 210, 184, 0)` - one light blue, alpha 0 |

The Metal 4 frame is **one flat sky-blue clear** - not a sky with a gradient, not a world seen from an odd
camera: the same value at all twenty-five samples of all 4958 readbacks, and still the same after a **ninety
second** settle, so it is not a world that had not loaded yet. Both halves of the frame agree (the picture's
RGB is the drawable's, the R/B swap of the two formats included), so the present road is doing its job; there is
nothing in the target for it to show.

**Where the draws go missing, measured rather than guessed.** Under `-Dmetallum.metal4Trace=true` the frame path
prints what each of its passes ends with, and the same session says two different things at once:

```text
Terrain                    depth=true draws=0   indexed=0   22836 passes, every one of them zero draws*
Sky sun / Sky moon         depth=true draws=1   indexed=1
Sky disc                   depth=true draws=1   indexed=0
Clouds                     depth=true draws=1   indexed=1
Particles - Solid          depth=true draws=1   indexed=1
GUI before/after blur      depth=true draws=1-11
Blit render target         depth=true draws=1
Update light               depth=false draws=1
Animate ...atlas/...       depth=false draws=1-11, 82420 in one pass label
```

So the frame is not empty of draws: the sky, the clouds, the particles, the GUI, the blits, the light updates
and the atlas animations all encode theirs, and it is **the world's terrain that encodes none**, in every one of
22836 pass endings over a ninety second run.

**Which renderer's pass that is, and which draw path it would take.** Two facts had to be read rather than
guessed, and both are in the sources rather than in the frame. Sodium's own `DefaultChunkRenderer` carries the
label `Terrain`, so the pass the trace shows ending with zero draws is **Sodium's** terrain pass, not vanilla's -
and vanilla's `ChunkSectionsToRender` path is not the one in play at all. And Sodium's draw path on this backend
is not its OpenGL one: `com.metallum.mixin.sodium.DrawBackendMixin` and `DrawContextMixin` intercept Sodium's
backend choice and its draw-context factory when `getDeviceInfo().backendName()` is `Metal`, answering
`DrawBackend.VK_INDIRECT` and Metallum's own `MetalDrawContext extends VKIndirectContext`. So the draw the frame
would ask for is the indirect one - which this path **does** implement - while the multi-draw it still refuses is
on Sodium's OpenGL road, which is not taken here. Vanilla's `RenderPass.multiDrawIndexed` is also gated on
`DeviceFeatures.multiDrawDirectSeparate` *before* it reaches any backend, and Metallum advertises that flag true
(`new DeviceFeatures(false, false, true, true, true, false, true)`), so a call down that road would reach the
Metal 4 pass and be logged by the refusal line - and none is. The draw side is therefore not what is missing.

`*` and that line is the one reading in this record that was **the instrument's fault**. At the time it was taken
the pass really did encode no draws, because the world's geometry had not arrived - but the counter could not have
told anyone when that changed, and it did not: `Metal4RenderPass.drawIndexedIndirect` encoded Sodium's terrain
batches without incrementing the pass's own `drawsEncoded`/`indexedEncoded`, so the pass that draws the world read
`draws=0` whether it drew or not. With the counters fixed the same trace reads **337, 678, 584, 583 and 677 draws**
per terrain ending (Sodium batches hundreds of section draws into one indirect batch) on 5358 endings in a fifteen
second session. A pass that draws indirectly reads as an empty pass; that is pinned now, and it is why this record
does not use the zero as evidence of anything after the geometry was fixed.

**And the same trace now says where each pass wrote and what it was told to do with it**, which is what the
surviving difference needed: its line carries the first colour slot's texture handle and its load, store and clear
actions. Read on a no-pack Metal 4 session: **every drawn pass loads and stores**, the attachment default is
`AttachmentContents.CARRIED` (which maps to `LOAD_LOAD`, so a pass that says nothing does not discard what stood
there), and `Sky sun`, `Sky moon`, `Sky disc`, `Terrain`, `Clouds` and `Blit render target` all write **the same
colour target** (`colour0=0x7c1693b700`, 26539 of 26539 endings). So the sky strip is neither a `DontCare` load
wiping pixels a pass does not cover nor a pass writing somewhere else - both of those are now eliminated by
measurement rather than by argument, and the sky's own content is what has to be looked at next: the sky passes are
encoded *before* the terrain pass (`Sky sun`, `Sky moon`, `Terrain` in that order), they load and store, they share
the target, and the region still holds the clear on this path where Metal 3 renders sky. What tells "the sky's
draws did not rasterise" from "something later overwrote exactly that region" is a copy of the target at a **pass
boundary**, which is the instrument the alpha channel has been waiting for as well.

**Then the instrument found the meshes, and one boolean found the loss.** The diagnostic above was written as
this project's own mixin, `com.metallum.mixin.sodium.ChunkUploadMixin`, off unless
`-Dmetallum.logSodiumTerrain=true`, and what it says in a no-pack Metal 4 session is the opposite of what the
missing arena suggested: **Sodium's upload step is called every frame and every call carries results** - one on the
first call, then 4, 6, 4, 1, 2, 3, and twenty-two by the eighth. The builder produces meshes on this path. So the
loss is inside the upload, and the upload's first engine-visible act on this path is the staging: Sodium's
`MojangStagingBuffer` constructor reads exactly one device feature to decide how it stages -

```text
RenderSystem.getDevice().getDeviceInfo().features().persistentMapping()
    ? new MappedStagingBuffer(size)      // a buffer the CPU maps and keeps mapped
    : ...                                 // the engine-staged path, through writeToBuffer
```

- and Metallum advertised that flag **true**. One boolean withdrawn (`new DeviceFeatures(false, false, true, true,
true, false, false)`) and the same forced Metal 4 no-pack launch **draws the world**: mean BGRA
`(68, 91, 77, 221)` against the Metal 3 arm's `(67, 86, 71, 254)`, with the sampled terrain cells identical cell
for cell (`366821`, `e3090c09`, `1f3913`, `446b33`, `412d1e`, `375729` and the rest), confirmed in a second run.
A Metal 3 launch with the flag withdrawn is byte for byte unchanged. Where the mapped path loses the data on this
generation is **not localised** - that is the follow-up, and the withdrawal is what makes it a follow-up rather
than a blocker - so the claim stays withdrawn and the engine-staged path, which both generations implement, is the
one a session uses.

**And the depth fixture now agrees with Metal 3 too**, which is the check the staircase stopped on: with the
withdrawal in place the Metal 4 arm reads **90719 green samples against 28831 cyan and no magenta** (the world's
geometry is in the depth buffer at the edges, and nothing sampled outside 0..1), against Metal 3's baseline
100152 green and 21380 cyan on its own run - the same reading of the same fixture, on two different scenes.

**One difference survives, and it is registered rather than explained.** The *sky* strip at the top of the frame
does not come through on this path: the Metal 4 arm's first sampled row is the clear colour `00b8d2ff` with alpha
0 where the Metal 3 arm's is rendered sky (`9db0d7`/`85aefe`/`83adff`, alpha 255), while every row below is the
same terrain. Its candidate is the attachment-contents policy seen from the other side: a pass that is declared to
overwrite what it covers is given `LOAD_DONT_CARE`, which is only undefined for the pixels it does *not* cover, and
the sky drawn before it is exactly those pixels. That is the kind of difference that looks right on one driver and
not on another, and telling it apart from "the sky pass did not draw" wants a copy of the target at a **pass
boundary** rather than at present - the same instrument the alpha channel has been waiting for.

**And Sodium's own machinery is all there, allocated once, at startup.** The buffer log shows its indirect rings,
its two 32 MB staging buffers and its terrain uniforms created within the same second the session came up, and
its terrain pass is opened every frame afterwards; what never appears is the one allocation that would mean
geometry had arrived - `ArenaAggregator`'s `Arena buffer`, created on the Metal 3 arm at 268435456, 134217728,
33554432 and 16777216 bytes as sections are uploaded. So the world's chunk meshes are never handed to the upload
step on this path, and the pass that would draw them is opened, frame after frame, empty. A diagnostic mixin on
Sodium's build/upload boundary is what names *that* - the engine cannot see it - and it is the next instrument
rather than a guess.

**The road those draws take is in the vanilla sources**, read rather than remembered: `ChunkSectionsToRender`
takes an `EnumMap<ChunkSectionLayer, Int2ObjectOpenHashMap<List<RenderPass.Draw<...>>>>`, `LevelRenderer.prepareChunkRenders`
fills it from `visibleSections` - one entry per section whose mesh has a draw for that layer *and* whose GPU
buffer slice exists - and `ChunkSectionsToRender.renderGroup` walks it and calls
`renderPass.drawMultipleIndexed(draws, defaultIndexBuffer, defaultIndexType, List.of("ChunkSection"), ...)`,
skipping a group whose list is empty. The pass the trace labels `Terrain` is exactly that pass
(`"Section layers for " + group.label()`), which is why its zero draws are the terrain's and not somebody else's.

**Two things that look like the mechanism are not, and one that does not look like it is.** Sodium is what draws
terrain in this instance, so an empty *vanilla* terrain pass is not by itself evidence of a missing world - and the
trace cannot settle that on its own, because the Metal 3 pass has no trace switch to compare against. What the
device's own allocations settle is the geometry side, and there the difference is total. `-Dmetallum.logBuffers`
names every GPU buffer a session makes, and both arms allocate the same *kinds* of terrain-adjacent machinery -
`Sodium terrain uniforms x256`, Sodium's `Indirect ring buffer #0/#1/#2`, the vanilla `Section time info` - while
only one of them ever allocates **geometry**: the Metal 3 arm allocates Sodium's `Arena buffer`s (268435456,
134217728, 33554432 and 16777216 bytes), and the Metal 4 arm allocates **none at all** (1863 allocations, the
largest of them 32 MB of staging). The vanilla uber buffers (`solid`, `cutout`, `translucent`) are absent from
*both* arms, which is Sodium doing the drawing as expected. So on this path the world's chunk geometry is never
uploaded into GPU memory: Sodium's terrain renderer is initialised (its uniforms and its indirect ring exist) and
never receives a mesh.

**And no operation is refused anywhere in those sessions.** This round made the Metal 4 pass's refusals say so
in the log before they throw - which section 104 asks for on its own, and which was needed here because a
*caller that catches the throw* drops the work silently - and the log names **nothing**: neither
`drawMultipleIndexed` nor any other refused operation. The frame-encoder refusals are absent too. So the draws
are not being refused; they are **not being asked for**, and the empty draw group is where that happens. Three
candidates remain, and none of them is measured yet:

- no chunk mesh is *built* for this path to upload (the chunk-build side);
- meshes are built and the upload to the arena never runs, or runs and lands nowhere (the upload side);
- meshes are in the arena and nothing is visible to the culling that would hand them to a pass (the visibility
  side).

The allocation evidence above already leans on the first two rather than the third - geometry that never reached
a GPU buffer cannot be culled into view - and the instrument that separates them is a log at the upload boundary
itself, which is a game-side call the engine currently cannot see.

`drawMultipleIndexed` is deliberately **not** on that list even though this path still refuses it: a refused call
would now be in the log, and the log is empty. That refusal will need its own implementation - it is the shape a
multi-draw takes on this API, and Metal 3 implements it as a loop - but implementing it cannot be the fix for a
call that is never made. Section 67's rule is what the next step follows: the staircase stops here, at an
M3 PASS / M4 FAIL, until the three candidates are told apart.

**And the comparison needed teaching for this A/B.** Its drift check refuses two arms whose render-pass and
depth-attachment counts differ by more than 2 per cent, because a drifted scene reads like a win; across
generations those counters differ *by design* (this path opens a native encoder per logical pass and a pass per
clear), so the run was refused as drift. The comparison now reads `executingGeneration` from each arm's probe
line and stands that check aside where two generations executed, saying where the scene guard moves to - the
harness's own world, pack, target and window. Two arms of one generation are judged exactly as before.

### A depth a pass wrote, sampled by the pass after it

The compare and the write are one question; whether a shader can read the depth buffer afterwards is another,
and it is the one a pack's composite asks when it samples `depthtex0`. `canSampleDepth` is two passes on one
command buffer. The writer clears the depth attachment to 0.5 and draws one triangle at 0.25 over part of it,
then ends with the producer barrier - which this command model requires of a dependency between encoders, and
which is why the smoke is also a small synchronisation fixture: without the barrier the reader has nothing
ordering it against the writer. The reader samples that depth texture through a one-texture, one-sampler table
at **each fragment's own position** (`in.position.xy / 64`, so the texel a pixel samples is the one its depth
belongs to and not a uv attribute that could be wrong separately) and writes the sampled value out as a colour.

Four readings, both sides of each compared: the depth buffer's own value at the triangle (0.25) and at the clear
(0.5), and the colour the reader wrote from them (64 and 128). The colour target keeps eight bits a channel, so a
depth comes back at one of 256 levels; the comparison allows one level either way, which is 0.4 per cent of the
depth range against two values a quarter of a range apart - the tolerance cannot hide the fault the smoke looks
for, and the two readings disagreeing by half the range is itself the check that the sample follows the position
rather than one texel smeared over the target. Measured on this machine: 50 of 50 probes (30 cold processes and
20 warm repeats), every other smoke green, no failure stage, 0 crash reports.

The depth texture is created with `ShaderRead` as well as the render-target bit: a texture with only the
render-target bit is refused as a sample source, and that refusal is the driver's rather than this engine's.

**One guard was dropped rather than widened.** The first version read the reader target's far corner and
required it to be 0 or 255, which is neither of the two values a correct smoke produces - that corner samples
the cleared 0.5, so it reads 128. It was there to catch a shader that smeared one texel over the target, and the
two readings that disagree by half the depth range already catch that; widening it would have kept a reading
that can only fail a correct implementation.

### A mip chain on the copy encoder, and the residency a copy actually needs

`generateMipmaps` was the last frame-resource operation this path answered false to, and it was not a missing API:
`MTL4ComputeCommandEncoder.h:543` declares `generateMipmapsForTexture:`, and the compute encoder is where Metal 3's
blit commands went - so the frame's own copy encoder is the road. `canGenerateMipmaps` proves it on the device:
a level-0 checkerboard of 0 and 255 uploaded from a buffer, **the levels above it pre-filled with a third value**,
the chain generated, and every level read back. The pre-fill is what makes it a measurement - a generation that
silently did nothing would leave that value there, and a smoke that only checked "level 1 is not level 0" would
pass on a level nobody wrote. Levels 1 and 2 are compared against the box average of the level below them (127.5,
so one level either way), and level 0 is read at two neighbouring texels so the two values the average comes from
are proven to be there. Measured: 50 of 50 probes in 30 cold processes and 20 warm repeats.

**The smoke's first version failed, and what it found is worth more than the smoke.** With neither the source
buffer nor the destination texture declared resident, the buffer-to-texture copy does **nothing at all** - not a
fault, not a refusal: the level reads exactly as it was created. One declaration at a time says it takes both
ends: only the buffer, still nothing; only the texture, still nothing; both, and it lands. That is the "an
address is not a reference" lesson from the world frame's fault, in a second costume - on this command model an
undeclared resource makes a command of this kind vanish, and the frame path's own upload road declares both for
exactly this reason. The smoke was the outlier.

The frame path implements the contract now: the chain is generated on the frame's copy encoder, the texture is
declared resident first, and a render pass the game still has open ends before it, because only one encoder may
be open on a command buffer. It still answers false, by name, where there is nothing to generate - a texture of
one level, a closed one, one that is not this engine's, or a format the native command cannot filter. That format
list is the Metal 3 encoder's own, and `tools/ci-metal4-provider.py` **compares the two lists** rather than
trusting memory: one generation generating a chain for a format the other refuses would only ever show up as a
blurry texture. The comparison caught its own author within the round - a mutation restore had left
`RG11B10_FLOAT` out of the Metal 4 list.

And the client's mipmaps do go through it. Vitrail's `deferred-mipmap-contract` - a 1-pixel checkerboard in
`deferred.fsh`, `colortex0MipmapEnabled = true` in `deferred1.fsh` - runs on this path with 105 pipeline
identities against Metal 3's 105 and no refusal, and under `-Dmetallum.metal4Trace=true` its chain generations
are visible: **2448 of them over the run, each answering true, for a 2560x1440 target**. That count is also an
observation for the performance phase rather than a claim: a pack that asks for a chain per sampler use is asking
for it many times a frame, and nothing here has measured what that costs.

**And the fixture's acceptance is now read rather than inferred.** Its three passes make a chain the picture can
report on: `deferred.fsh` paints a one-pixel checkerboard, `deferred1.fsh` samples it at LOD 6 and paints a green
checkerboard only where the chain averaged it to about 0.5, and `deferred2.fsh` samples *that* at LOD 6 again and
paints cyan only where it recognises the averaged green. Both arms read the same thing - 40 s of settle, 4968 and
4946 readbacks, mean of means RGBA `(5, 241, 241, 254)` on Metal 3 and `(4, 248, 248, 224)` on Metal 4, i.e. the
`rebuilt` cyan - and **neither arm paints magenta anywhere**, which is what a chain that broke at any step would
paint. The three passes, the pack parse and the absence of a fault are the same in both logs. So the deferred and
mipmap step of the staircase is **M3 PASS / M4 PASS** on the picture and not only on the counters, and the
staircase - which section 67 stopped at the depth fixture - has resumed one rung past where it stopped.

### The history rung fails on this path, and the failure is one dependency deep

The next rung after deferred/mipmap is history, and `composite-history-contract` is a chain rather than a colour:
its three passes read and write **one** target, `colortex2`, declared `colortex2Clear = false`, so each pass sees
what the pass before it wrote and the last one seen becomes the next frame's history. The fixture makes the chain
legible - dark history means "first" and paints red, cyan history means "steady" and paints cyan, anything else
paints magenta - and the last pass hands its verdict to `colortex0`, which `final.fsh` copies to the game's target.

**Read on both arms: Metal 3 passes, Metal 4 fails.** Forty seconds of settle, 4943 and 4950 readbacks. Metal 3
presents the fixture's steady state - cyan - with red only during the frames before the chain settles. Metal 4
presents **magenta for 119975 of its 121675 grid samples and never once cyan**: the chain breaks on its first
evaluation and latches, because magenta is what the next frame's "first" test also fails.

Where it breaks was then measured rather than argued, with a diagnostic fixture (`history-value-contract`) whose
last pass hands the value it is judging to the screen instead of its verdict. On Metal 3 that value is **yellow**
(253, 253, 0) - the steady state the chain is supposed to be in - and on Metal 4 it is **dark** (13, 7, 6) on the
first frames and magenta afterwards. Dark at that point means the pass read a copy of `colortex2` that *no earlier
pass of the same frame had written*, and the trace says which copies those are. Every pass's colour attachments are
now printed, and the three pack passes write **two different textures for one logical target** - `composite` writes
`0x7502559e00`, `composite1` writes `0x7502559b80`, `composite2` writes `0x7502559900` and `0x7502559e00` - which is
the pack's doubled-history ping-pong working exactly as Vitrail schedules it, with each pass writing the copy the
next one reads. The one candidate that is *eliminated* by the same reading is a clear: `Vitrail pending colour
clears` attaches `0x7502558f00`, `0x7502559680` and `0x7502559900` every frame (and `0x7502559b80` once at
startup), and **never** attaches `0x7502559e00` or `0x7502559b80` - so the pack's `colortex2Clear = false` is
honoured and the history target is not being emptied between frames.

So the failure is one dependency deep: on this path the second pass's sampler does not see what the first pass
wrote to the target, and reads a copy that holds its initial content instead - while the native smoke for exactly
that dependency (`canSampleAfterCopy`, "a pass writes a texture, the next samples it") is 50 of 50 on this device.
What the trace does not print is the *sampled* texture each pass bound, only the ones it attached, and that is the
next instrument: the two together say whether the binding points at the wrong copy of a doubled target or at the
right copy whose write did not land. Section 67 says the staircase stops at an M3 PASS / M4 FAIL, so it stops here
- one rung past depth and deferred/mipmap, at history.

### And the bindings are right: the history's exchange is a copy, and the copy is a call

The next instrument was the *sampled* texture a pass bound, because the attachments alone cannot tell a wrong copy
from a write that did not land. It is now on the trace line, and what it says takes the binding side off the list:
in all 1783 endings of a traced Metal 4 session,

```text
Vitrail composite    writes 0x..de00            samples colortex2=0x..db80
Vitrail composite1   writes 0x..db80            samples colortex2=0x..de00
Vitrail composite2   writes 0x..d900,0x..de00   samples colortex2=0x..db80
```

- **every pass samples exactly the copy the pass before it wrote**, which is what a doubled target's ping pong is
supposed to do, and the pattern is identical in every one of those 1783 endings. So it is not a mis-bound copy.

**And the pattern not changing between frames is not a frozen phase either: Vitrail exchanges the halves by
copying, not by rebinding.** Its own record says why - `ColorTargets.copyBack` copies the alternate half over the
main one at the end of every frame, "and the exchange alternates for as long as the pack stays loaded" - and the
session agrees with it: `1 targets are copied back from their far half at the end of every frame, because the pack
keeps them`. The engine call that carries it is `encoder.copyTextureToTexture(from, to, 0, 0, 0, 0, 0, w, h)`, and
on this path that call is implemented, declares **both** textures resident (the measured law here is that an
undeclared resource makes a copy do nothing at all), maps to
`copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:...` with the source first and the
destination second, and throws rather than returning quietly when the copy pass refuses. So the call itself is not
obviously the fault either, and the question narrows to **where in the frame that copy is encoded**: Vitrail's
contract for it is "outside any render pass, and after the last one of the frame", and a copy encoded after this
frame's commit would land in the next frame - after the pass that needed it had already read the main half, which
is exactly the stale read the fixture reports. Putting the copy's frame-relative position on the trace is the next
instrument.

### And the copy was zero-sized: one parameter order, and the history rung passes

The instrument named above printed its answer on the first line it produced. Every swap-back copy on this path was
being asked for as a rectangle of **0 by 0**:

```text
Metal 4 trace: texture copy 0x79aabb9e00 -> 0x79aabb9b80 0x0 level 0 at frameBegun=true frameCommitted=false
```

Inside the frame, then, and with the two halves named correctly - and with no area. The shared contract is

```java
copyTextureToTexture(GpuTexture source, GpuTexture destination, int mipLevel,
                     int destX, int destY, int sourceX, int sourceY, int width, int height)
```

and this path's override declared

```java
copyTextureToTexture(GpuTexture source, GpuTexture destination, int mipLevel,
                     int x, int y, int width, int height, int destinationX, int destinationY)
```

- the same nine parameters in a different order. A caller that follows the contract, as Vitrail's `copyBack` does
(`(from, to, 0, 0, 0, 0, 0, width, height)`), was therefore read as: source origin (0, 0) - harmless - then width
`sourceX` = 0 and height `sourceY` = 0, then destination origin `width, height`. Metal accepts a zero-sized copy
without complaint, so **every texture-to-texture copy on this path moved nothing and said nothing**, and the trace
line is what made it visible: the rectangle it printed was the rectangle the copy was given.

The override now reads the contract's order and hands the two origins to the selector where it wants them, and the
fixture the rung was named for passes on both arms: forty seconds of settle, 4926 and 4969 readbacks, Metal 4
reading `(3, 248, 248, 224)` - the steady state, cyan - with 1600 samples of the chain still settling and **no
magenta anywhere**, against Metal 3's `(5, 241, 241, 254)` and 2471, unchanged. Two pins hold the order - the
override's parameter list and the two origins in the selector call - and both are mutation-proved; one of them was
mutation-proved by swapping the two origins, which is the shape of the fault itself. The fix is one signature and
one call, and it is in the frame path rather than in Vitrail, which was right all along and is untouched.

What the same bug reached beyond the fixture is worth stating rather than guessing: every `copyTextureToTexture`
this path made was a no-op, so any pack or engine feature that copies one target over another has been silently
doing nothing - Vitrail's history swap-back is the one that has a fixture, and its shadow target's copy
(`ShadowTargets`, `copyTextureToTexture(depth, noTranslucents, ...)`) is the next candidate to read under the same
instrument.

### The real-pack ladder starts: MakeUp runs on both arms with the same program set

Every rung before this one was a fixture written to be legible. The ladder's first rung is a pack somebody wrote to
look good, and with the world rendering it can finally be read as a pack rather than as a fullscreen pass.

**`MakeUp-UltraFast-9.5e`, both arms, same world, same spawn, same anchor, forty seconds of settle.** No fault of
any kind in either log - no `GPURestart`, no `SIGSEGV`, no `Unimplemented`, and no refusal line - and the numbers
that §70 asks to be equal are equal:

| | Metal 3 | Metal 4 |
| --- | --- | --- |
| **pipeline identities** | **330** | **330** |
| render passes / 600 frames | 10727 | 11344 |
| blit encoders | 3951 | 4468 |
| clear encoders | 535 | 3409 |
| depth attachments | 4198 | 7624 |
| loaded / stored MiB | 279871 / 337410 | 330397 / 435208 |
| presented frames in the window | 4530 | 4521 |
| faults | 0 | 0 |

**The same 330 programs** is the structural fact the ladder was waiting for: the pack's whole translation and
compilation chain produces the same set of native pipelines on both generations, from the same pack, in the same
session shape. The gross picture agrees too - the most common presented frame's first sample is the same light
colour on both arms (`243, 247, 250` against `244, 247, 250`), and only a handful of frames are flat - which is
what §69 allows a cross-launch picture to say and no more.

**And the differences are the ones already registered rather than new ones**: this path opens a native encoder per
logical pass and a pass of its own for every clear, so `clearEncoders` is 3409 against 535 and the attachment
traffic is 1.18x loaded and 1.29x stored for the same scene and the same frame count; and the drawable wait's p50 is
0.03 ms on the reference arm against 3.80 ms here, which is a pacing difference and not a correctness one - it is
**registered for the performance phase** (§93) and not read as a verdict, because the two arms are two launches of
a scene that is not deterministic and the only thing being compared today is structure.

So the ladder's first rung is **M3 PASS / M4 PASS**, and the two heavier packs - Complementary Reimagined and
Photon - are the next rungs rather than this one's work.

**The second rung, and the counter that lied before it was read.** `ComplementaryReimagined_r5.9.1` is a real pack
of 219 shader files with deferred passes, shadows and compute (`world0/shadowcomp.csh`). It runs on both arms with
**no fault of any kind** and, for the second time in this migration, the first reading was the *instrument's* fault
rather than the frame's:

```text
                       Metal 3   Metal 4 (before)   Metal 4 (after)
pipeline identities      334          334                334
render passes          13887        14429              13266
compute encoders         532            0               1893
```

`computeEncoders=0` on this path looked like a pack whose compute never ran - and it was this path's own report:
`Metal4FrameEncoder.dispatchEncoder` opens the dispatch encoder without telling the frame probe, while the
reference arm reports every encoder kind it opens, compute among them. The call is now made where the encoder is
opened, and the same launch reads **1893** compute encoders on this path against 532 on the reference arm. That
difference is the design rather than a gap - this path opens one encoder per dispatch, which is the measured-safe
shape from the storage-image round, and section 70 explicitly does *not* ask the two generations' native encoder
counts to match: what has to match is the program set, and it does, at **334 identities on both arms**.

So the ladder's second rung is **M3 PASS / M4 PASS** too, and the differences it shows are the registered ones: a
pass of its own per clear (3279 against 538), attachment traffic 1.09x loaded and 1.15x stored, and one encoder per
dispatch. Photon is the rung after it.

### The ladder's third rung names the binding design: Photon stops on one pipeline

`photon_v1.3b` is the heaviest pack here - 557 files, 503 shaders, light-propagation compute, mip chains and
fifteen colour targets, eleven of them doubled - and it is the first real pack that does **not** run on this path.
The reference arm serves its whole chain in about ten seconds and draws it; this path serves 251 of its 607 pack
units in twelve seconds and then stops, and the presented frame stays a frame with no pack in it for the rest of
the session. **M3 PASS / M4 FAIL**, and the log names the failure in one exception:

```text
java.lang.IllegalStateException: Pipeline vitrail:pipeline/pack/2/world0/deferred4 requires wide Metal resources,
but Argument Buffer Tier 2 is unavailable
    at com.metallum.render.shared.MetalCrossShaderTranslator.translate(MetalCrossShaderTranslator.java:87)
    at com.metallum.render.metal4.Metal4PipelineCompiler.compile(Metal4PipelineCompiler.java:62)
```

and then Vitrail's own last words on it: `Vitrail stopped drawing this pack after an error`.

**The mechanism is a design boundary this rung is the first to reach, and it is exactly section 46's subject.** A
pipeline whose bindings do not fit MSL's *direct* slots makes the translator fall back to **Metal 3 argument
buffers** (`needsArgumentBuffers(...)`), and the Metal 4 compiler tells the translator that argument-buffer tier 2
is unavailable - correctly, because this generation binds through **argument tables** rather than argument buffers
- so the fallback throws instead of choosing the table path. Photon's `deferred4` is wide enough to reach it. The
fix is the production binding path sections 46 to 51 describe rather than a flag: a wide pipeline on this
generation has to carry its excess resources through the table (or through an address-space buffer the table
points at), which is what `Metal4BindingPlan` exists to decide.

**And one suspicion was refuted on the way, by its own A/B.** The session wrote 525893 lines to its log, 105187 of
them `Metal 4 argument table: made for ...`, one per table per pass - and a per-table INFO line in a hot path looked
like it was starving the render thread while the pack loaded. Gating it behind the trace switch changed the outcome
by **nothing**: the same 251 units, served at the same twelve seconds, before and after. So the gating is kept as
hygiene - one line per object per pass is not what a log is for, and the frame probe's `tablesPerFrame` already
counts every table - and the *cause* it was suspected of is recorded as refuted, in the code comment and in the
pin, so it is not re-run as an experiment. Section 67 stops the ladder here.

### A compute dispatch, and where the client's compute road stops

The plan's compute smoke is "input buffer, compute transformation, output, readback exact", and the first half of it
is now on the device. `canDispatchCompute` builds a pipeline from the probe's own kernel MSL, fills a table with
two buffers **by address** - the output and the uniform the kernel adds - dispatches one threadgroup of 32
threads, and reads every word the kernel wrote. Three facts make it a measurement rather than a call count: the
output buffer is pre-filled with a **sentinel the kernel never writes**, so a dispatch that did nothing leaves it
there rather than passing on what a fresh buffer holds; every thread's expected value is **its own index's
formula** (`id * 2 + 7`), so a grid of the wrong shape, one thread's answer repeated over the buffer, and a table
that carried only one of the two buffers all fail; and both buffers are declared resident first, which the
mipmap round measured to be load-bearing for this command model's commands. Measured: 50 of 50 probes in 30 cold
processes and 20 warm repeats.

The three calls are read off this machine's SDK rather than remembered: `setComputePipelineState:`
(`MTL4ComputeCommandEncoder.h:51`), `setArgumentTable:` (`:661`, and it takes **no stage mask** - a dispatch has
one stage) and `dispatchThreadgroups:threadsPerThreadgroup:` (`:87`), whose two `MTLSize` structs go over as
pointers, the convention the copy methods' regions already use.

**The client's compute road was then run to find where it stops, and it stops before any dispatch.** Vitrail's
`compute-storage-contract` - a kernel that writes a storage buffer and a storage image, and a render pass that
displays them - reaches this on the Metal 4 arm:

```text
java.lang.IllegalStateException: storage image phase15Image was allocated by the active backend
    but that backend could not clear it to zero
```

That is `MetalFrameResourceCommands.clearStorageTexture`, one of the two frame-resource operations this encoder
still answers false to, asked for by the client's own allocation of a storage image. So the work list for this
slice is now measured rather than guessed, in the order the client reaches it:

1. ~~**`clearStorageTexture`**~~ - **done, this round**, and the fixture gets past it: a typed zeroing kernel, the
   image in a table by resource id, and a dispatch over the texture's own extent, with the table's per-dispatch
   snapshot measured by a smoke that re-points one table between two dispatches;
2. **a compute-pipeline compile that does not require the Metal 3 state** - this is where the fixture now stops,
   in its own words: `compute composite backend pipeline failed: Active Metal execution state does not support
   compute`. `MetalComputeBridge.compile` calls `Metal3ComputeBridge.compile`, which refuses anything that is not
   a `Metal3ExecutionState`, so a pack's own compute pipeline cannot be built on this path at all;
3. **`MetalFrameComputeCommands.dispatchCompute`** on the frame encoder - the dispatch itself, with the client's
   reflected binding map resolved into a table;
4. and probably `copyStorageTextureRegion`, the other refusal, when a pack copies storage images.

### The storage clear: a kernel, a table, and the snapshot one table is enough on

The compute fixture's first word on this path was `storage image phase15Image was allocated by the active backend
but that backend could not clear it to zero`, and that is now answered. A storage texture has no contents when it
is made; this command model has no blit fill and no per-resource setter on its encoders, so a clear is the shape
the dispatch round proved: **a typed kernel, the image in an argument table by resource id, and a dispatch over
the texture's own extent**.

The pieces, and the one design choice worth naming: `MTL4StorageTexturePipelines` carries this generation's own
copy of the zeroing kernels - the Metal 3 layer is not on this generation's classpath, and a pin checks that
rather than trusting it - with a cache **owned by the frame encoder** and released with it, rather than the Metal
3 form's static map keyed on a device that could outlive its owner (section 106's rule). `dispatchThreads:`
(`MTL4ComputeCommandEncoder.h:77`) is the open-grid form a clear needs, because the grid is a texture's extent
and is not a multiple of any threadgroup. And `Metal4FrameEncoder.clearStorageTexture` ends an open pass, declares
the image resident - an undeclared resource makes a command of this kind do nothing at all, which the mipmap round
measured - binds it through a one-texture table and dispatches.

**CORRECTED: one table is *not* enough for a frame's clears, and this paragraph used to say the opposite.** It
read the header's sentence - Metal snapshots a table's resources when a dispatch is encoded - as a licence to
re-point one table between dispatches, and `canWriteStorageImage` was written in that shape. That shape is
phase-dependent: the round-42 reproducer measured two dispatches in one encoder through one re-pointed table
reading what the table held when it was first handed over, on every even round, while a table per dispatch is
clean eight rounds of eight (`tools/metal4-cold-probe.sh --repro 8 --own one-encoder`, and its `fresh-table`
mode). So the smoke's green was a false green about half the time, the frame path's clears were built on the
same shape until the engine was fixed, and the smoke itself now makes a table per dispatch. What is measured
50 of 50 in 30 cold processes and 20 warm repeats is the capability - a kernel writes a texture through a table
of its own - and the snapshot question lives in the reproducer, where the shape can be varied one part at a
time.

**And the client gets past it.** The compute-storage fixture now stops one door further on, at the public
compute bridge's compile path, in its own words:

```text
compute composite backend pipeline failed: java.lang.IllegalStateException:
    Active Metal execution state does not support compute
```

`MetalComputeBridge.compile` calls `Metal3ComputeBridge.compile`, which refuses anything that is not a
`Metal3ExecutionState`. So the remaining list for this slice is now: **a compute-pipeline compile that this
generation can do** (SPIR-V to MSL through the shared translator, a Metal 4 function and pipeline state, and the
reflected binding map resolved into a table), then **`MetalFrameComputeCommands.dispatchCompute`** on the frame
encoder. The session itself runs and falls back while that is missing, which is the designed answer for an
absent capability rather than a half frame.

### The compute road: one translation for two generations, and a dispatch that is a table

`MetalComputeBridge.compile` answered with the state's own refusal - `Active Metal execution state does not
support compute` - and that is now the bridge's neutral question answered by this generation. Three pieces, and
the first is not new code at all.

**One translation, in the shared layer.** SPIR-V in and MSL plus remapped bindings out is not a Metal 3 answer:
both generations run compute, and what a kernel's resources *mean* does not depend on which command API encodes
the dispatch. The Metal 3 bridge held that translation in private - 257 lines of SPIRV-Cross, the profile it
reads, the per-kind argument slot allocator, the binding record - so the Metal 4 road needed either a second copy
of metadata that has to agree with the first for a pack to run on both generations, or one home for it.
`render.shared.MetalComputeTranslator` is that home, beside the render translator it already shares an MSL
profile with, and the Metal 3 bridge now calls it. Behaviour is unchanged: same options, same slot allocation,
same limits, same error text. The binding kind is the shared `MetalResourceBinding.ResourceKind` rather than a
private enum saying the same four things.

**The state compiles, the context caches, and the handle holds a reference.** `Metal4ExecutionState implements
MetalComputeCompiler`: translate, `newFunction` for the MSL, `newComputePipelineState` for the function. The
function cache already keys a native function by (MSL, entry point, profile), so a compute pipeline state is
keyed by exactly that and cached beside it - which is why two handles to one kernel share one native state on
this path. Sharing is a refcount and not a hand-over: `Metal4ComputePipeline` retains the state, so the context
releasing its own reference in `clearCachesAfterGpuCompletion()` (which the game reaches on **every resource
reload**, F3+T, through `GpuDevice.clearPipelineCache`) cannot free an object a live handle is dispatching with,
and the handle's `close()` hands its reference to the device's destruction queue the way the Metal 3 handle hands
over the state it owns outright. The handle also owns the one thing Metal 3's does not need: **the argument
table**. This command model has no per-resource setters, so a dispatch is a table and nothing else; it is made on
first use, sized to the argument counts the translation gave that kernel, and released by `close()`.

**And the dispatch is that table, filled from the translation's own numbering.** `Metal4FrameEncoder` now carries
`MetalFrameComputeCommands`: every binding is resolved and declared resident *before* the encoder opens (a
missing binding has to be a refusal with nothing encoded, and an allocation this frame has not declared reads as
nothing at all), then the pipeline, then the filled table, then
`dispatchThreadgroups:threadsPerThreadgroup:` - the same call the Metal 3 bridge makes and not
`dispatchThreads:`, because the caller's counts are workgroups and the shader declares its own local size. The
encoder is the frame's own compute encoder, the one the copies and mip generations use, because this command
model has one encoder for all three and within it program order is the order; the two directions that are not
program order were already handled where they are encoded. Buffers are bound by the address of their slice, and
that addition now has one implementation (`Metal4RenderPass.addressOf`) instead of two.

**Measured: the client encodes both of the fixture's dispatches on this path.** A forced Metal 4 session
(`-Dmetallum.execution=metal4`) with Vitrail's `compute-storage-contract` selected, quick-played into the
overworld, said so in its own words - the compile is no longer the door it stops at:

```text
Metal execution: Metal 4 EXECUTES this session because metallum.execution=metal4 was asked for ...
Metal execution seam: selectedGeneration=metal4 executingGeneration=metal4 mode=own-path framePathReady=true
Drawing compute-storage-contract from the root for minecraft:overworld, at 2560x1440, 1 full screen passes before the final
compute programs dispatched before the pass they hang off: [composite, composite_a]
Dispatched compute composite through the active backend: groups=(1, 1, 1), local=(1, 1, 1)
Dispatched compute composite_a through the active backend: groups=(1, 1, 1), local=(1, 1, 1)
composite writes colortex0 alt, 2 uniforms and 1 samplers, 3 descriptors, a fragment stage that writes every pixel
final writes the game's own target, 2 uniforms and 1 samplers, 3 descriptors, a fragment stage that writes every pixel
```

No `backend pipeline failed`, no `Vitrail stopped drawing this pack after an error`, and no refusal of either
kind this path can raise (a missing binding, a resource the table would not take, a dispatch the encoder would
not encode) - and the storage-image clear that precedes them no longer reports that the backend could not clear
the image. **What is still NOT MEASURED is the picture**: the fixture's correctness claim is a GREEN image, the
in-game F2 screenshot is a framebuffer readback and therefore the one picture road this machine has left (the
display capture is a flat colour), and this session could not press it - macOS refused the automation
(`execution error: 未获得授权将Apple事件发送给System Events (-1743)`), so a human has to press F2 for that half.
The dispatch road and the chain's completion are measured; the pixels are not.

**Two faults were caught by an adversarial review of this round's own commits, before either reached a client,
and both are fixed and pinned.** The first: the pipeline-state cache asked `newComputePipelineState` to build from
a function it had not checked, and a device that refuses a kernel's MSL answers nil for that function - which
Metal asserts on (`computeFunction must not be nil`) and the process dies with SIGABRT rather than the compile
failing. Every sibling call site in the engine guards exactly that value; the new one did not. It now does, in the
cache, and `compileCompute` names a refused **function** and a refused **pipeline** as the two different failures
the Metal 3 path already words apart. The second: the handle held the shared pipeline state as a borrowed
pointer, so the context's cache clear - one F3+T away through `ShaderManager.apply` - would have freed the state
under a live pack handle, and the next dispatch would have messaged freed memory. The retain and the deferred
release above are that fix. Both are mutation-proved in the provider contract (a nil function reaching the
factory, a borrowed pointer, a handle that never gives its reference back, and a handle that releases where it
stands: four mutations, four caught).

Two MSL refusals appear in the same startup, and neither is this round's: `'sampler' attribute parameter is out
of bounds: must be between 0 and 15` and `'id' attribute only applies to non-static data members` are the
capability probe's own measurements of the sampler ceiling and the resource-id rule, both already recorded under
Risks.

### The dependencies across encoders, and the barrier that is not "one command buffer"

Section 60 lists the read/write cases a frame's passes, dispatches and copies make between each other, and
section 61 forbids the proof that says "they are ordered because they share a command buffer". Two of those
cases are now measured natively, each on its own value, each with the API's own ordering primitive encoded
rather than assumed:

- **a dispatch writes a storage image, the pass that follows samples it** (`canSampleComputeOutput`). The
  compute encoder's producer barrier (`barrierForSubsequentEncoders`, `barrierAfterStages:beforeQueueStages:`)
  is asked for before it is sent - an encoder that did not answer it fails the smoke by name - and then the
  render pass binds the same image through a table by resource id and draws a fullscreen triangle over it. The
  colour is a value no other smoke uses (`{17, 99, 201, 255}`), so a target that holds it cannot have got it
  anywhere else. The two readings are the diagnostic: the image is read back on the CPU first, so a kernel that
  never wrote and a sample that never arrived are two different failures rather than one;
- **a dispatch writes a vertex buffer, the draw that follows reads it** (`canDrawFromComputeWrittenBuffer`).
  The buffer is filled by a kernel through a table by plain address, the same buffer is bound to the drawing
  pass's table as vertex data with its attribute stride, and the colour the vertex stage passes through comes
  out of the buffer's own last two components. **The buffer starts as three copies of the origin** - a triangle
  with no area - so a draw that ran before the kernel's data arrived paints nothing and the target keeps its
  clear colour, which the readback can see; and the buffer is read back on the CPU as well, for the same
  reason the image is.

The render-to-render case was already measured the same way (`canDrawSampledTexture`: a pattern pass, its
producer barrier, then a pass that samples what it wrote), so three of section 60's seven fixtures are
native-proven. What is **not** proven: the copy crossing into shader work and back (`blit writes → render
samples`, `render writes → blit reads`, `blit writes → compute reads`), the `compute → compute` visibility the
client's own fixture depends on, and the read/write matrix's WAR direction. Each is its own smoke in the same
shape as the two above, and none of them is claimed yet.

**And the copy's two boundaries are a reproducer, so they are held out of the default census.** A third smoke
of the same shape was written for them - a pass clears a source, a copy moves its region into a destination's
other half, and a second pass samples the destination - and it passes on the device. What it also does is make
the storage-image smoke fail: with it in the suite, four runs of one cold process plus four warm probes failed
the storage-image smoke in **four of four runs, always at the process's fourth probe**, and a ten-warm run
failed at probes 3, 5, 7 and 9 - a period of two - while a run of the same driver without it was clean. Four
bisects narrowed the ingredient rather than the mechanism:

| Variant | Result |
| --- | --- |
| the copy smoke's table made with one buffer slot instead of none | the pattern stays |
| a **fresh** table for the storage smoke's second dispatch instead of the re-pointed one | the pattern stays |
| the copy encoder's block removed, its three textures and both passes kept | **clean, 11 of 11** |
| the copy kept, its producer barrier removed | the pattern stays |

So the smoke is **not in the census** - the census has to keep meaning "this capability works", and a suite
that is red for a reason another suite's field reports is worse than one that does not ask - and the finding
now has an artifact of its own instead: **`tools/metal4-cold-probe/CopyThenDispatchRepro.java`**, run by
`tools/metal4-cold-probe.sh --repro N [--variant NAME]`. It is a mode of the census harness and not a second
harness, so it is compiled against the same classpath and cannot measure another branch's classes. Each round
runs the **victim** first - `canWriteStorageImage`, the smoke the real suite loses - and then the **trigger**,
which is the copy shape above; the parts of the trigger are switches rather than an edit, so one run removes
exactly one of them.

**The variant matrix, six rounds each, `storageFailures` out of six.** `full` reproduces on the even rounds:
3 of 6, and the victim's own second call in the same round (`storageAgain`) fails exactly when the first does,
so it is a state that persists inside the round rather than a first-command-after-a-copy effect.

| variant | storage | trigger's own check | reading |
| --- | --- | --- | --- |
| `full` | 3/6 | clean | reproduces |
| `full-copy` (whole texture, not a region) | 3/6 | clean | the region is not special |
| `no-copy` (encoder kept, command dropped) | **0/6** | clean | the copy **command** is required |
| `no-copy-encoder` | **0/6** | clean | an empty encoder is not enough |
| `buffer-copy` (buffers instead of textures) | **0/6** | clean | it is a **texture** copy, not a copy of any kind |
| `no-sampled-pass` | 3/6 | clean | the pass that samples is not needed |
| `no-source-pass` | 3/6 | 6/6 failed | the source's contents are not needed |
| `no-destination-clear` | 3/6 | clean | the clear is not needed |
| `separate-commit` (its own buffer and commit) | 3/6 | clean | "one command buffer" is not it |
| `no-residency` | 3/6 | clean | residency is not it |
| `textures-released-last` | 3/6 | clean | the release order is not it |
| `plain-destination` (not a render target) | 3/6 | clean | the usage bits are not it |
| `copy-to-unbound` (the copy's target is in no table) | 3/6 | clean | the destination being bound is not it |

**Correction: the copy is a phase, not the cause.** That table was measured before the reproducer had a victim
of its own, and adding one showed the reading to be incomplete - with the own victim in the loop, `full` was
clean and `no-copy` failed, which is the same phenomenon with the sign flipped. What the copy does is change
the *phase* the process is in; it is not what is broken. The victim is: **two dispatches in one compute
encoder, through one table object re-pointed and handed over again between them.** With the own victim written
to that shape, the answer is stable and it is the mechanism:

| own victim's shape (one command buffer, one commit) | result, eight rounds |
| --- | --- |
| one encoder, one table **re-pointed** between the dispatches | **red (1 of 2) on every even round** - the second dispatch's binding is stale |
| one encoder, a **fresh table** for the second dispatch | green (2 of 2), every round |
| one table re-pointed, a **new encoder** per dispatch | green, every round |
| one table re-pointed, a **commit** per dispatch | green, every round |

So the driver's snapshot for a dispatch is not taken from the table as it stands at that dispatch when the same
table object has already been handed to the same encoder: the second dispatch reads what the table held when it
was first handed over. **A table of its own per dispatch is safe** (and so is an encoder per dispatch, which is
the expensive version of the same thing).

**This is the engine's own pattern, and it was a defect rather than a curiosity.**
`Metal4ComputePipeline` held one table per compiled kernel and `Metal4FrameEncoder` handed it over again on
every dispatch of that kernel, while `clearStorageTexture` re-pointed a single `storageTable` for every clear in
a frame - so two dispatches of one kernel in a frame, or two storage clears, could bind what the first one
bound.

**Fixed the same round, in the measured-safe shape.** `Metal4ComputePipeline.newTable(device)` makes a table for
one dispatch and the handle keeps none, and both call sites in the frame encoder - `dispatchCompute` and
`clearStorageTexture` - make their own and give it back through the frame's destruction queue, so a table's
lifetime is still the slot's and not the dispatch's. The client says the path still runs: a forced Metal 4
session with Vitrail's `compute-storage-contract` dispatches both programs and reports no refusal, and the
storage image is still cleared through a kernel with no complaint.

**And the fix has a price, measured rather than waved away**: three tables a frame in that fixture (two
dispatches and one clear), where the old shape made one per kernel. In the same session the log's own count of
`Metal 4 argument table: made` runs to 5708 over the run. That is the honest cost of correctness-first, and
pooling is a phase-21 candidate with the same rule the fix came from: a table may be re-pointed between
*encoders* (measured clean) but not within one, so a pool has to be keyed by the dispatch's place in the frame
rather than by the kernel.

**Measured, and with one honest fault in it.** Two 30-cold + 20-warm censuses and a six-process hunt
(6 × 31 probes) were run: **286 probes**, of which `computeSample` and `computeVertex` are **286 of 286** -
every cold process and every warm repeat, including the 30 cold processes of both censuses. The storage-image
smoke, which is not this round's code, failed **18 of those 286** - all eighteen in one process, all from that
process's third probe onward, every one reading the first dispatch's red where the second dispatch's green was
asked for, with its own message saying so. Six further processes of 31 warm probes each did not reproduce it,
and the second census of the same shape was clean 50 of 50. So this is a **new intermittency with a
signature**: once it starts in a process it persists for the rest of that process, it has not been seen cold,
and it is the *table re-point between two dispatches* that stops taking - which is the mechanism the frame
path's storage clear depends on. It is registered, not explained: the mechanism is a hypothesis until a
reproducer exists, and the exact stage is already known (the second dispatch's write, at (0,0)).

### The safe shape is one encoder per dispatch, and the copy fixture is in the census

The copy's two boundaries - a pass writes a source, a copy moves a region of it into a destination's other
half, and a pass samples that destination - are the third dependency fixture of section 60, and they are
**back in the census** now. They were written in the dependency round and held out because their presence made
the storage-image smoke fail; that turned out to be two separate things, and both are now measured.

**One: the storage smoke's own re-pointed table, fixed.** Two: **a fresh table is not enough either.** With
the copy smoke in the suite, `canWriteStorageImage` - by then making a table per dispatch, and deterministic
174 of 174 on its own - failed again on alternate warm probes, 3 of 8. So the re-point was one fault and not
the whole story, and the table is not the unit the driver honours: **the encoder is.**

| the storage smoke's shape, with the copy smoke in the suite | result |
| --- | --- |
| one encoder, a table per dispatch | 3 of 8 warm probes lost the second dispatch |
| **one encoder per dispatch**, a table each | **93 of 93 probes in three processes, and 50 of 50 in the census, all four smokes green** |

So a dispatch that binds through a table gets an encoder of its own, and that is what the smoke does now. Two
things about the shape are part of it and not incidental: **both encoders must stay alive until the command
buffer has completed** - releasing the first one before the commit crashed the driver inside
`-[AGXG17XFamilyComputeContext_mtlnext dispatchThreads:threadsPerThreadgroup:]`, a SIGSEGV in the Metal
framework rather than a Java-level failure, which is why the smoke keeps both and closes them after its wait;
and a table may be re-pointed between *encoders*, which the reproducer's `two-encoders` mode measured clean.

**And the engine had the shape this rules out, so it was fixed the same round.** `Metal4FrameEncoder`'s
`dispatchCompute` and `clearStorageTexture` both encoded into the frame's shared `copyEncoder()`, so two
table-binding dispatches - or a dispatch and a clear - in one frame shared one encoder, which is exactly the
shape that lost a dispatch in the probe. Both now go through `dispatchEncoder(which)`, which ends a copy
encoder the frame already has open (with its producer barrier, so the copies the dispatch reads are ordered
against it) and opens a fresh encoder for this dispatch alone; `endDispatchEncoder` ends it and files its
release through the frame's destruction queue, because an encoder released before the command buffer it
encoded is committed aborts the driver. A dispatch's encoder also barriers before it ends: with an encoder per
dispatch, whatever follows a dispatch is always another encoder, and that is what the barrier is for. The
mipmap generation and the copies keep the frame's own copy encoder - they bind no table, which is the property
that matters here.

Measured after the change, on the client: a forced Metal 4 session with Vitrail's `compute-storage-contract`
dispatches both of its programs, clears its storage image through a kernel, and reports no refusal of any kind.
The cost is one encoder per dispatch instead of one per frame, and one table per dispatch and per clear; the
log's own count of `Metal 4 argument table: made` lines is a function of the session's length (5708 in one run,
18135 in a longer one), so the per-frame number and what the encoder churn costs are phase-21 measurements with
the counters, not numbers to be read off a log.

**Measured this round, in full.** Two 30-cold + 20-warm censuses (one without the copy smoke, one with it) and
two hunts (four processes of 31 warm probes, and three of 31): **317 probes, no field failure**, with the copy
fixture, the compute-to-pass and the compute-to-draw fixtures all green in every one.

### The read side of the boundary, and section 60's list is complete

The dispatch side of the compute boundary was measured two rounds ago; this is the **read** side. Two smokes,
one road: a producer writes a texture, its encoder barriers, and a dispatch of its own samples that texture and
writes every sample into a buffer - so the answer is **a value on the CPU and not a pixel in a picture**. The
kernel is four lines (`texture2d<float, access::sample> source [[texture(0)]]`, `sampler nearest
[[sampler(0)]]`, `device float4* out [[buffer(0)]]`, `source.sample(...)` over a 4x4 grid), the output buffer
is pre-filled with a sentinel per channel, and every one of the sixteen slots is refused if it still holds the
sentinel and compared against the colour the producer wrote. Each boundary encodes its producer barrier, and
the dispatch gets **an encoder of its own** - the shape the storage smoke measured as the safe one, and now
also the shape the engine uses.

- `canDispatchSampledCopy` - a pass clears a source, a copy moves a region of it into the destination, and the
  dispatch samples the destination. That is section 60's "blit writes → compute reads";
- `canDispatchSampledRender` - the producer is the pass itself, and the dispatch samples what it wrote. That is
  "render writes storage image → compute reads".

**Measured: a 30-cold + 20-warm census is 50 of 50 on all six dependency fields** - render→render,
compute→render, compute→draw, copy→render (and render→copy), copy→compute and render→compute - and 50 of 50 on
the storage smoke, with no capability failure. With that, **all seven of section 60's cases are native-proven**:

| section 60's case | smoke |
| --- | --- |
| render writes texture → render samples texture | `canDrawSampledTexture` (a pattern pass, its barrier, a sampled pass) |
| render writes storage image → compute reads | `canDispatchSampledRender` |
| compute writes storage image → render reads | `canSampleComputeOutput` |
| compute writes buffer → draw reads buffer | `canDrawFromComputeWrittenBuffer` |
| blit writes texture → render samples | `canSampleAfterCopy` |
| render writes → blit reads | `canSampleAfterCopy` (same fixture, the other direction) |
| blit writes → compute reads | `canDispatchSampledCopy` |

**And the chain of two dispatches is measured too** (`canDispatchAfterDispatch`), because that is the shape a
pack's own compute chain is made of and the one Vitrail's compute fixture depends on: the first dispatch writes
a storage image through the storage-write kernel, its encoder barriers, and a second dispatch of its own samples
that image and writes its sixteen samples into a buffer - the same sentinel and the same per-slot comparison as
the two producer smokes, so a second dispatch that never ran, one that ran and wrote nothing and one that read
stale contents are three different failures. Two encoders, two tables, one command buffer, one commit. With it
in the census, **50 of 50 on all seven dependency fields** - and it is the case that would otherwise have gone
unmeasured while the client's compute fixture happened to pass, because the picture of that fixture is not
available on this machine.

**Section 61's three directions are all measured now.** The list above is one of them - **read-after-write**,
which is the direction a producer's barrier is encoded for. The other two are fixtures of their own:

- **write-after-write**: `canWriteStorageImage` is two dispatches writing the same texture through two tables,
  and what it reads is the second write, so the write the encoder after it must see is the one that landed last;
- **write-after-read**: `canWriteAfterRead`, and this is the direction a frame's own reuse takes - a pass samples
  a texture through a table and a later dispatch writes that same texture. Its reading is deliberately two
  facts: the reader's target must hold what the texture held *before* the write, and the texture must hold what
  the writer put. A target holding the writer's colour is a write that overtook a read, which is the failure
  this fixture exists for; a texture still holding the reader's colour is a write that never landed. The reader
  is a render pass and the writer is a dispatch, so the two encoders in the middle of the sequence are of
  different kinds - the shape a pack's composite-then-compute frame has.

The fixture's own sensitivity was checked rather than assumed: pointing its comparison at the writer's colour
instead of the reader's makes it fail, so the readback is live and the assertion is not decoration.

The barrier cost section 62 refuses to optimise before the counters exist is a phase-21 measurement rather than
a correctness question.

### The ownership ledger, and the leak it found

Section 105 asks for a ledger rather than a claim, and it is now a document of its own:
`docs/metal4-resource-ownership.md`. Every object the Metal 4 path makes, with who owns it, where it is made,
how long it lives and where it is released - written by reading each creation and release site rather than from
memory.

Writing it found a leak the sessions had not reported: **the frame's queue**. `Metal4FrameEncoder` asked the
execution services for a `MTL4CommandQueue`, handed it to the ring, and released nothing; the ring is explicit
that it does not own the queue, and the Metal 3 encoder releases the queue the same seam gives it ("the queue is
this encoder's own now"). One queue a session, invisible in every counter. The encoder now keeps the queue and
releases it in `close()` - after the ring, which is the only thing that submits on it - and a pin checks both
halves, because the difference between the two encoders is visible only in their teardowns.

The ledger also records the price of the encoder-per-dispatch rule in objects (one encoder and one table per
table-binding dispatch, both released through the slot's destruction queue), and that nothing in the Metal 4
frame path is a process-global singleton - the queue, the ring, the tables, the residency set, the storage
pipelines and the compilation caches are all owned by the frame encoder or the execution state, so a second
device in one process gets its own.

### The presented drawable, read back: the picture column has a first measurement

Every session's picture column has been empty, and the reason was always about the **observation**: this machine
refuses to let the display be photographed (`screencapture` returns one flat colour) and it refuses automation
that would press the game's own screenshot key (`-1743`). Neither of those says anything about the frame. What
neither of them explained is that the drawable itself was unreachable too - a `CAMetalLayer` is created with
`framebufferOnly = true`, and a framebuffer-only texture may not be the source of a copy.

`-Dmetallum.drawableReadback=true` is that switch: the layer is built with `framebufferOnly` off, the frame
encoder copies the presented drawable into a shared buffer after the present pass (in the frame's own command
buffer, because the drawable is only valid for the frame that took it), and the pixels are read at the next frame
that reuses the slot - the point the ring has proved that slot's submission complete. What it prints is small and
structural: a five by five grid of samples, top row first, and the mean of each channel over a sparse grid of the
whole surface (the layer is BGRA8, so the report names the channels in that order). It is off by default, it says
out loud that it changes the layer's contract, and it costs a whole-surface copy per frame when it is on - a
diagnostic, not a road.

**The first measurement, on a forced Metal 4 session with Vitrail's compute-storage fixture: 150 readbacks.** 69
of them are one flat colour - `meanBGRA=(61, 50, 239, 255)`, the loading screen - and 81 are the world: a dark
image with structure, every sample different (`[ff0d0d0a, ff12110c, ff10100b, ...]`, mean around
`(13, 20, 22)`). **No readback is black**, and none is empty: the presented drawable holds a real, varying image,
so the frame's present road puts a picture into the drawable. What the display capture showed was the capture,
not the frame.

**And the comparison is now measured: the Metal 3 arm reads its drawable the same way.** The Metal 3 present
road's helper answers the drawable it drew into (`encodePresentTextureToDrawable`), the encoder copies it in the
same command buffer, and the pixels are read where this arm already waits - at the point `submit()` closes the
command buffer of the slot being reused, whose completion the window wait has just seen. Both arms read through
the *same* formatter in the shared layer (`DrawableReadback`), because a comparison whose two sides formatted
differently compares the formatting.

Two arms, one scene, the same fixture, the same switch, ten seconds of settle after the fixture's dispatches
(1366 and 1372 readbacks). **Both arms present the fixture's acceptance colour**: the fixture's second compute
writes `vec4(0, 1, 0, 1)` into its storage image and its final pass paints pure green when the chain worked, and
both drawables are green with the red and blue channels at zero. That pair registered two pixel-level differences
and called them "measured and unexplained". **The next measurement withdraws one of them, refutes both of their
candidate mechanisms, and leaves the other one localised.**

### The present roads are faithful, and the ramp was a fade

Each arm now reads **both halves** of the frame it presents: the *picture* the present triangle sampled and the
*drawable* it wrote, copied in one command buffer out of one frame (`DrawableReadback.reportPicture`, pinned on
both arms). That answers the question the round above could not: whether the two present roads changed the image
at all.

**They do not.** Frame for frame, in both arms, the picture's reading and the drawable's reading are the same
reading - the same five-by-five grid, the same means, 1359 pairs on one arm and 1548 on the other at ten seconds,
4951 and 4953 at forty. So the present pass is the identity on this fixture on both roads, and the candidates the
round above named for the alpha - the two passes' attachment load and store actions, and the shared present
pipeline's blend state - **are refuted by measurement rather than by argument**: both passes' attachment treatment
is `DontCare` load and `Store` store, both draw through the same `presentPipeline` object (blending disabled,
`MTLColorWriteMask.All`), and neither of those can be the cause of a difference that is already in the picture
before either road touches it.

**And the ramp was not a difference at all: it was the Metal 3 arm's frame still fading in.** Its mean green climbs
monotonically - 195 at `05:17:01`, 197 at `05:17:01.5`, 205 at `:01`, 215 at `:03`, 230 at `:05`, 247 at `:11` -
and its mean alpha goes 10, 100, 252, 254 in the first two seconds and then holds `254`. **That is a cross-fade
from the loading screen, sampled while it was still running**, not a property of either present road. At a forty
second settle the same arm reaches its steady state: the grid is `ff00ff00` at every sample and the mean is
`(0, 255, 0, 254)` - **flat, opaque green, which is exactly what the fixture's `final.fsh` writes**
(`vec4(0, 1, 0, 1)`). So the comparison basis of the round above - "ten seconds of settle after the fixture's
dispatches makes two runs the same frame" - is **refuted, and the observation it produced is withdrawn**: the
Metal 3 anchor had not settled, and the "gentle radial ramp" was that arm's animation, not the frame's shape.

### The orientation, and a second fixture that answers it

The question the picture column has carried since it opened is orientation: the compute-storage fixture's picture
is a flat colour, so a readback of it can say the colour arrived and cannot say which way up it is. A **second
diagnostic fixture** answers it without touching the companion checkout: `picture-orientation-contract` is that
same chain - the same two compute programs, the same marker test into `colortex0`, the same `final.vsh` - with one
file replaced, and the replacement is short enough to be the record:

```glsl
// shaders/final.fsh, in place of the flat accept/reject colour
vec4 picture = texcoord.x < 0.5
        ? (texcoord.y < 0.5 ? vec4(1.0, 0.0, 0.0, 0.5) : vec4(0.0, 0.0, 1.0, 0.5))
        : (texcoord.y < 0.5 ? vec4(0.0, 1.0, 0.0, 0.5) : vec4(1.0, 1.0, 1.0, 0.5));
gl_FragColor = green ? picture : vec4(1.0, 0.0, 1.0, 1.0);
```

Four quadrants, one channel each and one of all three, so the five-by-five grid - printed top row first - says
which way up the image is and in which order the channels arrived; alpha 0.5, so the same reading says whether an
alpha that is neither 0 nor 1 arrives at all. The pack lives under `run/shaderpacks/` like the smoke fixtures and
is not tracked, because the fixtures that *are* staged from the companion Vitrail checkout may not be added to:
that checkout stays at `4380250f`, which is a standing rule of this program rather than a convenience.

**Measured on both arms, forty seconds of settle, 5162 and 4956 readbacks. Orientation is PROVEN, and the two
roads agree.** The Metal 3 picture reads, top row first: red (`ff0000ff`, RGBA8) and green (`ff00ff00`) across the
top rows, blue (`ffff0000`) and white (`ffffffff`) across the bottom; the same arm's drawable reads blue
(`ff0000ff`, BGRA8) and white across the top, red (`ffff0000`) and green (`ff00ff00`) across the bottom. That is
the present triangle's own mapping, quadrant for quadrant: the draw swaps the two ends of the memory-vertical axis
and changes nothing else - the quadrants that share a row in the shader (`texcoord.y < 0.5`: red with green, blue
with white) still share a row in the drawable, and the columns are not mirrored. The red-and-blue column also
proves the channel conversion: the picture is RGBA8 and the drawable BGRA8, and the same *colour* arrives in both
(the bytes differ by exactly the red/blue swap the two formats imply), so neither road carries a channel order
defect to the screen. **The Metal 4 arm's grid is the same arrangement, sample for sample**, which is what the
orientation question needed: whatever flip the present makes, this road makes the same one. Across the
twenty-five samples of both fixtures, in fact, the two arms agree on every *colour* and differ in exactly one
byte: the alpha, which is the subject of the section below.

### What survives: the alpha, and it is not the pack's

| shader's alpha | Metal 3, 40 s settle | Metal 4, 40 s settle |
| --- | --- | --- |
| `1.0` (compute-storage fixture, green picture) | alpha 255, mean `(0, 255, 0, 254)` | alpha 0, mean `(0, 255, 0, 0)` |
| `0.5` (picture-orientation fixture, four quadrants) | alpha 255 at every sample | alpha 0 at every sample |

The second fixture is what turns the alpha from "a difference between the arms" into "**not the pack's alpha at
all**": the shader's alpha changed from 1.0 to 0.5 and the stored alpha did not move on either arm. So the frame's
alpha does not follow the pack's write on either road - 0.5 arrives as 255 exactly as 1.0 did - and the difference
between the arms is therefore **not** about the pack's write, its pipeline's write mask, or its colour format:
something else in the frame owns that channel, and the two arms disagree about what that something leaves there.

What is measured: both arms draw the pack with the same pipeline-building code and the same
`ColorTargetState.writeMask()`, both sample the game's own render target at present, both agree byte for byte on
the loading screen (the pink `ef,32,3d,ff`, RGBA8) before the chain runs, and the alpha each arm stores is
invariant under the two fixture alphas. What is not measured: which writer sets it, and why the two roads differ -
the candidates are now the frame's own clear of the presented target and any pass after the pack's `final` that
touches that target, and the experiment is a copy of that target **at a pass boundary** rather than at present,
which is also the instrument a multi-target picture check wants. The layer is opaque, so this is invisible on
screen; it is registered as a measured frame difference, not as a visible defect.

What the picture column reads now: **both halves of the frame measured on both arms, the present roads proven to
be the identity in colour and the same flip in orientation, one difference withdrawn as an artefact of an
unsettled anchor, and one - the alpha - reframed by a second fixture as a property of the frame's own clear
rather than of the pack's write.**

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

Phase 4's other half is `render.metal4.Metal4FrameEncoder`. It was written as a frame's lifetime with an empty
encode path inside it; the encode path has since been filled in (the passes, the copies and the clears, each in
its own section), so what is described here is the lifetime half. It implements the neutral `MetalFrameEncoder` -
the contract the device holds - and owns exactly three things: the ring above, the resources a frame cannot
release yet, and the release order between them.

- **The ring.** One per encoder, made from the queue the execution services answer with, so no generation owns
  the device's queue factory and no second lifetime model grows beside the sidecar's (§31).
- **The deferred releases.** `queueForDestroy` files a release against a ring slot - the frame's own slot while
  a frame is begun, the next slot otherwise - and that slot's bucket is emptied only when the ring has proved
  the slot's previous submission complete. A release that ran any earlier would be a resource given back while
  the GPU was still reading what it fed, which is the corruption the ring exists to prevent.
- **The wait.** `waitForSubmittedGpuWork` waits the ring and *then* runs the releases, in that order, and `close`
  does the same before letting the ring go. The order is the method.

**What refused at this point, and what refuses now.** When this section was written every other operation
refused by name: `transientMemory`, `createRenderPass`, `submitRenderPass`, the clears, the five copies,
`createFence` and `writeTimestamp`, each raising the provider's `Unimplemented` with the operation's own name,
so the refusals *were* the migration's remaining work list and a log line could be read against the plan.
Section 35 is the rule they follow: an operation this path cannot encode is never dropped into a half frame -
and a frame that says it cannot run is worth more than one that runs half of itself. Most of that list is now
implemented (the copies in "The copies", the render path in "The pass object" and "The binding plan", the clears
in "The clears"); what still refuses **by name today** is the scissored `clearColorAndDepthTextures`,
`createFence` and `writeTimestamp`, and that shorter list is what a forced client run walks into next.

`submit()` is the one method that is neither: it ends and commits the frame **once** where a frame is begun, and
does nothing where none is. When this section was written nothing began one, because a frame's begin belongs to
whatever first encodes into it and there was no encode path; today `beginFrameIfNeeded` is called by the first
pass, the first copy and the first clear, so a forced client frame begins its own frame - and a `submit()` that
found no frame is now a fact about a frame that encoded nothing rather than about the migration's stage.

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

### One submission structure per session, measured before it was enforced

Section 63 asks the migration to converge on **one** Metal 4 queue, one command ownership model, one commit a
frame, one retirement model and one presentation path, and section 38 forbids the shape by name: the full-frame
path must not be a frame queue beside a present sidecar. The policy above moved *who decides*; this is the step
that makes the decision **exclusive**, and it was taken only after the state it removes was measured.

**Measured first**: a forced Metal 4 launch with `-Dmetallum.metal4Present=true` starts the sidecar *as well as*
the frame encoder's ring - `Metal 4 path: carrying the frame's present, one command buffer and one commit a
frame, 3 allocators and a shared event bounding the frames in flight` once, and
`Metal 4 path: commit feedback registered` once - while the frame encoder's own present road does all the work
(1964 drawable readbacks labelled `[metal4]`, and none from the Metal 3 present road, which that session never
uses). So the session held two Metal 4 queues, two allocator rings, two command buffers, two shared events, two
commit-feedback registrations and two frame retirement models, and the sidecar was **never asked for a picture**:
`Metal4Path.presenting` is reached from the Metal 3 encoder's gate, and a session that executes Metal 4 does not
call that encoder at all. The cost of the shape is not a wrong pixel; it is an object graph that lies about who
presents, and one more queue per session on the way to production.

**The step**: the present road is chosen from the policy *and* the generation that executes, in the one seam that
holds both facts - `MetalExecutionServices`:

```java
private boolean presentingThroughTheSidecar() {
    return presentsThroughMetal4() && executing != MetalApiGeneration.METAL4;
}
```

`startPresentPath` starts the sidecar when that is true and returns the do-nothing gate otherwise, and
`closePresentPath` now asks **the same question the start asked** rather than the policy alone, which is the
asymmetry that would otherwise leave a road that was never started being closed, or a started one behind. The
elsewhere-unchanged property still decides *whether* the sidecar road is used at all, so nothing about the
reference shell moves: a Metal 3-executing session with the property on starts the sidecar exactly as it did.

**Measured after**, three arms on the settled scene:

| arm | execution | sidecar started | presented by |
| --- | --- | --- | --- |
| before | `metal4` + property on | **1** (+1 commit-feedback registration) | the frame encoder, 1964 readbacks |
| after | `metal4` + property on | **0** | the frame encoder, 2182 readbacks |
| after | `metal4`, property off | 0 | the frame encoder, 1959 readbacks |
| after | `metal3` + property on | **1** | the sidecar (one Metal 3 readback, which is the frame before the gate takes the picture) |

The Metal 4 arms load a world, dispatch Vitrail's chain every frame and present through the frame encoder's ring
with no `GPURestart`, no refusal and no fault; the Metal 3 arm with the property on still starts the present-only
road, which is the reference shell section 39 says must not be removed early. Four pins hold the shape - the
helper, its condition, the start that asks it and the close that asks it - **all four mutation-proved**, and the
contract file records the measurement the pins exist for rather than only the code they reject.

What this does **not** do is remove `Metal4Path`: section 107's order is new path proven, presentation moved,
capabilities covered, *then* the sidecar becomes unused and is removed in an isolated cleanup commit. Today it is
still the reference shell's presenter - which is a session whose frame is encoded by Metal 3 - so the sidecar's
own queue is the session's second submission structure there by design, and that is the configuration section 19
calls `referenceShell=true`.

### The wide pipeline, and the ceiling the stages of this migration had already named

The real-pack ladder's third rung is where the binding design stopped being a design question and became a
measurement. `photon_v1.3b` served 251 of its 607 pack units and then threw, in one exception, that
`vitrail:pipeline/pack/2/world0/deferred4` requires wide resources and that argument-buffer tier 2 is unavailable
- a sentence that names the pipeline and nothing about *why* it is wide.

**So the refusal was made to say what it refused, and that alone was the round's measurement.** The decision that
gates it answered with a boolean, and a boolean has no reader but a throw: the layout went into the code and never
into the log, so the only way to learn it was to print it and run the pack again. `wideReason(...)` now returns
null where the resources fit and a sentence naming the counts and the overflowing slot where they do not, the
vertex-layout span moved into its own method so the decision and the sentence cannot disagree about it, and the
same run reads:

```text
Pipeline vitrail:pipeline/pack/2/world0/deferred4 requires wide Metal resources, but Argument Buffer Tier 2 is
unavailable: 20 entries (1 buffers, 19 sampled images, 0 texel buffers) and 1 vertex layouts: the last sampled
image sits at entry 19 and a sampler index is capped at 15
```

Nineteen sampled images, not the sixteen the comment there had recorded, and the buffer rule nowhere near its
ceiling of thirty-one. That number is the whole of the argument that follows.

**The ceiling is the compiler's and the table cannot lift it, which this migration had already asked three ways.**
`MTL4ArgumentTable.h` caps a descriptor at sixteen sampler slots; the cold probe's census reports the device
agreeing from its own side ("seventeen direct samplers refused ... a sampler by resource id refused, a texture by
resource id refused, a table asking for twenty sampler slots accepted"); MSL declares one `[[sampler(n)]]`
attribute per sampled image with no way to put two images on one; and the Metal 3 direct API is capped at the same
sixteen. So section 51's warning - do not conflate the argument table's capacity with the shader's sampler indexing
limit - is now a measurement rather than a caution, and past sixteen sampled images the **argument buffer** is the
only shape there is, on both generations. This generation's first reading of section 46 was that the table
*replaces* the argument buffer, and for everything that fits it does; what it does not replace is the layout.

**So the compiler stopped deciding and started asking, and the pass learned the half that is Metal 4's.** The
compiler hands the shared translator `compilation.device().supportsArgumentBuffersTier2()` where it used to hand it
a literal `false`, and keeps one guard where that literal was: a translation that came back wide on a device with
no tier 2 is refused, because the buffer its resources were laid out in could not be made. The artifact grows the
generation's own half - one `MTLArgumentEncoder` per descriptor set per stage, asked of **that stage's function**
so the buffer length is the shader's own layout and not a number this class guessed, released with the artifact -
and the pass fills a shared-storage, hazard-tracked `MTLBuffer` of that length through the encoder and writes its
GPU address into the table slot the shared layout recorded. The reference generation hands the same buffer to the
encoder directly; this one hands the table its address. That difference is the whole of the generation boundary
here, and it is why no Metal 3 type crosses into `render.metal4`.

Three smaller facts are load-bearing and each was a mistake waiting to be made:

- **A binding an argument buffer carries is not a table slot.** Its metal index is its position *inside* the
  buffer, and the shared translation numbers those two at a time - buffer and texture - so a twenty-entry layout
  reaches thirty-nine. A plan that counted them would size a table of forty buffer slots, which Metal caps at
  thirty-one: a wide pipeline would have failed on the table instead of on the pipeline. The plan counts the
  argument buffer's own slot instead, at the index the shared layout recorded.
- **Every layout is made when the pipeline is set.** A wide pipeline's table carries one buffer slot per
  descriptor set and the shader dereferences whatever address is in it, so a set whose resources are bound after
  the first draw - or never - would still be read. `ensureArgumentBuffers()` runs where the tables are made.
- **A binding no layout carries is a fault, not a skip.** The plan and the artifact are two halves of one
  translation, and a resource in neither is a disagreement between them rather than an unbound resource to be
  tolerated.

**Measured on the pack, both arms, same world and width, 600 frames of counters.** The arm that failed now draws
the chain, with the reference arm's program set (345 pipeline identities on both arms, 345 keys, 736 compiles), one
wide pipeline in each log, and both readback roads agreeing to the byte on a 5x5 grid of a 2560x1440 frame -
drawable mean BGRA `(44, 62, 55, 0)` on both and picture mean `(53, 60, 42, 0)` on both. The three MSL failures in
the arm's log are the cold probe's own negative tests and not the frame's. The rung below was re-run on both arms
to check that the direct path had not moved, and it had not: `ComplementaryReimagined_r5.9.1` reads 334 identities
and 714 compiles on both arms, no wide pipeline in either log, both chains drawn. **The ladder is MakeUp PASS,
Complementary PASS, Photon PASS**, and section 67 no longer stops it.

What this is **not** is a proof that the wide shape generalises: it is one wide pipeline deep, Vitrail's
`wide-resources-contract` fixture - thirty-three sampled images through a single pipeline - has not been run on
this path, and the buffer writes are re-encoded per binding rather than deduplicated, which is section 50's
correctness-first order and explicitly not the finished shape.

### The lifecycle gate, which needed a driver rather than a keyboard

Section 71 lists seven transitions and every one of them was pressed by a keyboard this machine's automation
permission refuses (`osascript` is denied with -1743). That is a reason the gate had no reading, not a reason it
could not have one: four of the seven are single method calls on the client, and the two that are not need a
teleport and a GUI. So they are now driven from inside the client on a schedule the launch line states -
`-Dmetallum.lifecycleProbe=resize@500,fullscreen@700,windowed@900,reload@1100,leave@1500,close@1700` - through
the client's own entry points rather than a simulation of them: `Window.setWindowed` and `toggleFullScreen` for
the window changes, `Minecraft.delayTextureReload` for F3+T's own path, `clearClientLevel` for leaving, and
GLFW's window-close flag for a quit. The flag is the load-bearing one: it is what the close button sets, so the
game loop leaves on its own terms and the whole shutdown path runs, where a signal skips it entirely.

**What it found on the first real run was a teardown fault in this path, and the instrument that found it is now
part of the code.** The frame encoder's close and the device's cache clear both wait for the ring's completion,
and only the second reported anything - so a warning about submission 3813 arriving late was unattributable. Both
waits now print what they waited for and what the ring looked like, and two consecutive lines name the mechanism:

```text
closing - waited 0 ms for 3815 submission(s); complete=true,  ring state: submissions=3815 awaited=[3814, 3815, 3813]
waited  0 ms for 3815 submission(s); complete=false, ring state: submissions=3815 awaited=[0, 0, 0]
```

`awaited` at zeros while `signalled` did not move is `MTL4FrameRing.close()` - it clears the slots' recorded
values and releases the event - so the second wait was on a ring the frame encoder had already released, and
`waitUntilSignaledValue` against a released event returns immediately: the completion that had been proven 0 ms
earlier was reported as a timeout that never arrived. A false alarm rather than a stall, and no destroy ran
before its proof - but the wait proved nothing, which is the one thing a completion wait may not do. The fix is a
deletion: `MetalDevice.close()` no longer clears the pipeline cache itself, because `executionState.close()` at
the end of the same method clears the same caches after the same wait. Three mutations hold the order.

**Measured on the exact build, one session, `photon_v1.3b` on this path**: the resized window takes the presented
extent from 2560x1440 to 3200x1800 and back (2375 / 1061 / 2555 readbacks), the fullscreen change is survived,
the resource reload completes with the pack rebuilt through this path - and the wide pipeline's line appears
*twice*, once at load and once after the reload, so the argument encoders this generation asks of its own
functions were re-asked across a cache clear that retired the artifact owning the first set - the leave is
survived, and the quit runs `Stopping!` through to `BUILD SUCCESSFUL` with the chain drawn twice, no Vitrail
stop, and **zero teardown warnings**. The reference arm on the same schedule is also clean, which is what makes
the timeout Metal 4's own rather than a property of quitting.

**And the dimension change turned out to be drivable after all**, which is worth writing down because the first
reading of the gate had it as unmeasurable. It is not a method call on the client - it is a server-side teleport
- but what a player types is a chat command, and the client's own road to one is
`ClientPacketListener.sendCommand`. Sent as `execute in minecraft:the_nether run tp @s 0 80 0`, the server
answers `Teleported Player478 to 0.5, 80.0, 0.5`, Vitrail logs
`Left minecraft:overworld for minecraft:the_nether: a dimension replaces the root rather than layering over it, so
the whole pack is read, translated and its colour targets allocated again`, and then
`Drawing ComplementaryReimagined_r5.9.1 from world-1 for minecraft:the_nether, at 2560x1440, 8 full screen passes
before the final` - the chain drawn twice, once per dimension, with no stop and zero teardown warnings. That is
the row that re-reads and re-translates a whole pack mid-session, which is where stale targets, stale tables and
stale argument buffers would show.

**One thing the gate still does not cover**, registered rather than implied: an in-session shader-pack *switch*
needs the pack screen. The reload and the dimension change between them cover the half of a switch this path can
get wrong, which is the retirement of the old artifacts while a frame still names them. And one caveat
belongs to the driver: `clearClientLevel` called directly lets a packet arrive for the level just cleared, and
vanilla throws in `ClientPacketListener.handleSetEntityMotion`; the UI path closes the connection first and does
not.

### The mixin surface, which is two gates and not one

The lifecycle driver is a mixin, and adding one turned up two rules that were not written anywhere and cost a
round each. The first: `metallum.mixins.json` names the classes Mixin may transform, and
`MetallumMixinConfigPlugin` is a *second* gate over them - a mixin the config names and the plugin does not admit
is configured and never applied, silently. The session runs, the property has no effect, and the log carries no
line to say why; the measurement is simply empty. The second: Mixin transforms **every** class in its configured
package, so the small schedule type that the driver's record needed could not live beside it - the launch ended
in `ExceptionInInitializerError: Mixin transformation of ... LifecycleSchedule failed` before the client loaded -
and it could not live *inside* the mixin either, because a mixin's nested types are relocated into the target
class: the record became `Minecraft$Action`, which `Minecraft` does not carry in its `InnerClasses` attribute, so
every access threw `IncompatibleClassChangeError` and the schedule line printed as
`[!!!net.minecraft.client.Minecraft$Action$75e25708...=>java.lang.IncompatibleClassChangeError...]`.

Both rules are in `ci-contracts.py` now, with three mutations: every source file in the mixin package must be a
mixin the config names, every mixin the config names must be admitted by the plugin - by name, or as the package
group the sodium diagnostics are admitted as - and the schedule type lives in `render.shared`, which is where a
type that is only *used* belongs.

### The compute fixture's picture, and the arm difference it exposed

The compute road's picture was the one reading the report carried as unreachable, and it was unreachable only
because the fixture's acceptance was written as an F2 press. The drawable and picture readbacks read it instead,
and the fixture turns out to be a near-ideal instrument for them: `final.fsh` writes pure green `(0,1,0,1)` or
pure magenta `(1,0,1,1)` and nothing else, so "which colour is on the screen" is the whole verdict.

Both arms pass it - overwhelmingly green, red and blue at zero in every sampled cell, no magenta, and the
picture read is the drawable written on both, so the present pass is the identity here - and the two arms do
**not** agree about the green:

```text
                              readbacks   green over the run        red/blue   picture == drawable
Metal 3  (comp8-compute-metal3)  4948   60 -> 194 -> 199, flat    zero       yes, ramp for ramp
Metal 4  (comp8-compute-metal4)  4960   50 -> 255, flat           zero       yes, green for green
```

This path is uniform at 255; the reference arm is a stable radial ramp from 255 at the centre to 67 at the
corners, and both are plateaus rather than fades. **A ramp cannot come from the pack** - it has two colours and
this is neither - so on one arm something else is writing the game's target: an overlay multiplied in, or a write
this path does not make. Which of the two it is **is not localised**, and it is registered as the third member of
a family the migration already carries (the sky strip and the alpha channel, both of which want a copy of the
target at a pass boundary). What would separate them is a pass-by-pass trace that reads the target's mean rather
than twenty-five sampled cells, because a radial multiply is exactly the shape such a trace would attribute to a
pass.

It is worth writing down how the reading nearly went wrong, because the same trap is in the presentation row:
the first thing the numbers show is the *fade*, both arms starting at 50-60 as the loading screen clears, and a
single reading taken during it says the arms disagree wildly. Read as a sequence, the two converge to their own
plateaus - which is a difference that survives, and a different claim from the one the first frame supports.

### MetalFX spatial, on this generation's own terms

Section 77 gates this milestone on the frame path being basically correct, and at this point the ladder passes on
all three real packs, the lifecycle gate has readings, and the synchronous matrix is closed on the device - so the
gate is met and the work is the next thing the plan lists.

**It is a second path and not a parameter of the first, and the headers say why.** macOS 26's
`MTL4FXSpatialScaler.h` declares a different protocol whose encode takes an `MTL4CommandBuffer`, and the
descriptor's Metal 4 spelling takes a *compiler* - `newSpatialScalerWithDevice:compiler:` - because Metal 4 keeps
pipeline compilation in an object the app owns rather than on the device. Section 80 asks for exactly the split
that follows: the logical configuration key may be shared, the native objects may not, because a scaler compiles
its own pipeline and one generation's compiled pipeline is not the other's.

Three objects, in the layer that already owns Metal 4's device-level ones:

```text
MTL4Compiler         the compiler object the Metal 4 factory needs. Every way it can fail is an answer and not
                     an exception: no device, no newCompilerWithDescriptor:error:, no MTL4CompilerDescriptor
                     class, and a nil factory are four sentences, each said once, and a null handle
MTL4FXSpatialScaler  the scaler, configured through the base protocol both generations share and encoded with
                     encodeToCommandBuffer: on the frame's own Metal 4 command buffer
Metal4Fx             this generation's capability question, its own configuration-keyed cache, and the encode
```

**Availability is a functional question, which is the whole point of asking it here.** Apple's gate is
`+supportsMetal4FX:`, and a device that answers yes can still refuse a scaler - so `Metal4Fx.supported` asks the
class question and then *makes* one for a plain colour pair with a compiler and lets both go. That is not
tidiness: the capability record uses this answer to decide whether choosing Metal 4 would cost the player the
render-scale setting, and a `respondsTo`-only answer would report a scaler that does not exist as one that does.
The record's clause therefore moved from `MetalFx.metal4SpatialSupported` to `Metal4Fx.supported`, and the
generation-reach ledger grew by one name on a line that already crossed - which is how that ledger is meant to
grow: as a decision with a reason, not a drift.

**No fence, and it is a fact about the new command model rather than an omission.** The Metal 3 path hands its
scaler the frame's fence because this engine's textures opt out of Metal's own hazard tracking, and
`MTLFXSpatialScaler.fence` is exactly what Apple declares for that case. Metal 4 has no fence object in this
engine at all - `Metal4Fence` records why: the new command model orders work with encoder barriers and queue
events - so what orders the scaler against the passes around it is the one command buffer's own encode order plus
the all-stages barrier every pass already ends with. The frame path ends any open encoder of ours first, declares
both textures resident, and the pins hold all of it.

**Measured, ComplementaryReimagined_r5.9.1 at renderscale=55, one arm each, both at 2560x1440:**

```text
Metal 4   Metal 4 MetalFX spatial scaling: available, the device supports it and made one
          (Vitrail) The 55% render scale brings the picture back with MetalFX
          pipelineIdentities=333  pipelineKeys=333  compiles=712  gpuM4Frames=600
Metal 3   MetalFX spatial scaling: available, the device supports it, factory newSpatialScalerWithDevice:
          (Vitrail) The 55% render scale brings the picture back with MetalFX
          pipelineIdentities=333  pipelineKeys=333  compiles=712  gpuFrames=596
```

Both draw the chain at 704x396 and 1408x792 - the pack's own scaled targets, identical on both - present at the
native 2560x1440, refuse no scaler and stop for nothing. The program set matches at 333 identities and 712
compiles, which is section 70's comparison. The two arms' pictures differ and are *not* read as a verdict: two
launches of a pack with history and clouds are what section 116 says not to compare that way.

**And one pair was discarded rather than read.** The first attempt at the same configuration had the Metal 4 arm
at a 1280x720 drawable for its whole session while the Metal 3 arm moved to 2560x1440 after about ten seconds.
The *game's own target* and the drawable moved together, so no code of ours chose either - and the repeat pair
above is 2560x1440 throughout on both arms. It is written down because section 115 says an arm whose output extent
differs is an arm to discard, and that is what happened to it; the lesson is that a render-scale session has one
more scene fact to check than a native-scale one.

**What is not measured** is registered with the readings: output orientation *through the frame path* - see the
smoke below, which proves it on the device - the configuration switch and resize behaviours of section 82 in a
session, and any performance comparison: the two arms above were display-paced and section 84's fixed 1920x1200
target has not been run.

### The scaler smoke, and the census that re-opened a blocker

The MetalFX milestone left one thing a live frame cannot answer: the scaler's **orientation**. This engine never
reads the scaler's output back at its own size, and a scaled frame's picture is not compared across launches
(section 116) - so the question went to the instrument that has no window in it. `canScaleWithMetalFx` uploads a
four-quadrant pattern of four different colours at 64x64, upscales it to 256x256 with this generation's scaler,
and reads the four quadrant interiors back on the CPU. Four colours and not two, read at the interiors: the
closest pair is 204 levels apart while the tolerance is 32, so a flip on either axis moves at least two quadrants
out of tolerance and an upscaler's ringing at an edge cannot. **40 of 40 probes** in a 20-cold/20-warm census,
with a 1:1 configuration and an odd 101x57 to 320x181 one asked for beside the verdict's, because a scaler is
cached per configuration and section 81's identity is what separates them.

**Getting there found three defects in the smoke rather than in the scaler**, which is worth writing down
because a smoke that fails is not evidence until it is read:

- the second and third configurations' textures were released where they stood, with the command buffer that
  names them not yet committed. The run before that fix failed **2 of 80** probes reading a quadrant colour that
  belonged to its neighbour - precisely the shape a released-and-reused allocation takes;
- the first version also encoded a copy of the output into a buffer with a `bytesPerRow` of four for a 256-wide
  texture: a malformed copy whose result nothing read, because the verdict is the CPU read beside it;
- the verdict had to be the four interiors rather than a brightness, or it would have measured "the scaler ran"
  instead of "the picture is the right way up".

**And the same five censuses turned up something the milestone was not looking for.** `canWriteStorageImage`
still loses its second dispatch. The earlier round closed it at "50 of 50 and 124 of 124"; five 40-probe
censuses this round read **21 of 200 (10.5%)**, with the fault's own reason string and no other smoke failing
beside it:

```text
census            cold      warm     total
metalFx smoke in   0/20      2/20     2/40
metalFx smoke out  6/20      4/20    10/40
metalFx smoke out  1/20      0/20     1/40
metalFx smoke in   1/20      0/20     1/40
metalFx smoke in   3/20      4/20     7/40
---------------------------------------------
all five                              21/200
```

So the fix narrowed the fault and did not remove it, and the clean census was the low end of a variable rate
rather than the rate.

**Then the rate moved out from under the measurement.** Three censuses run after the smoke's failure path was
given a diagnostic that re-reads the texel after 50 and 100 ms - a change that runs *only when the smoke has
already failed* - read **0 of 360 probes**, against 21 of 200 in the period above. A fault that is 10.5% in one
period and absent in the next, with nothing changed in the path, is not a property of the build alone: something
outside this instrument moves it, and the harness cannot see what. 360 clean probes is not decisive against a
rate already seen at 25% in a single census - the honest statement is that the rate is not stable, and that this
is the gap section 88's counters exist to close. The diagnostic stays because the next occurrence will then say
whether the dispatch was lost or the CPU read the texture before the GPU's write was visible; those are
different faults with different fixes, and this smoke's readback is a CPU `getBytes:` while every other readback
in the file that comes off the GPU goes through a buffer. **The order effect is not established**: the arms above differ by whether the MetalFX smoke
runs first, and they total 3 of 80 against 11 of 80 - but the spread *within* one arm is 1 to 10, which is wider
than the difference between the arms, so the pooled 10.5% is the honest number and separating a 4% arm from a
14% arm needs a few hundred probes each. This is the same table-and-encoder shape the engine's own
`clearStorageTexture` uses, so a fault at this rate in the probe is one the frame path can reach, and it is the
strongest argument the migration has produced for section 88's counters: what changes the rate is not something
this instrument can see.

### The counter API, read off this machine's headers

Section 89's first instruction is to research the actual SDK rather than write selectors from memory, and the
storage-image intermittent just made that concrete: a fault whose rate moves with something the harness cannot
see is the case the counters exist for. So the API is recorded here from the headers, with the file each fact
came from, before a line of it is written.

```text
MTLDevice.h:1516        - (nullable id<MTL4CounterHeap>)newCounterHeapWithDescriptor:(MTL4CounterHeapDescriptor *)
                            descriptor error:(NSError **)error

MTL4Counters.h          MTL4CounterHeapDescriptor: type (MTL4CounterHeapType), count. The only timestamp type is
                            MTL4CounterHeapTypeTimestamp; MTL4CounterHeapTypeInvalid is the other enumerator
                        MTL4CounterHeap: label, count, type, and the two calls that read it -
                            resolveCounterRange:(NSRange) -> NSData of tightly packed entries
                            invalidateCounterRange:(NSRange) (invalidated entries resolve as 0)
                        MTL4TimestampHeapEntry is `{ uint64_t timestamp; }` - eight bytes an entry
                        MTL4TimestampGranularity: Relaxed (least invasive, "may sample at command encoder
                            boundaries") and Precise ("may cause splitting of command encoders" - a cost stated
                            in the header, which is section 91's question answered in the API)

three places a timestamp can be written
    MTL4CommandBuffer.h:172        writeTimestampIntoHeap:atIndex:                       (no granularity)
    MTL4RenderCommandEncoder.h:645 writeTimestampWithGranularity:afterStage:intoHeap:atIndex:
    MTL4ComputeCommandEncoder.h:832 writeTimestampWithGranularity:intoHeap:atIndex:

two places a heap can be resolved
    MTL4Counters.h         resolveCounterRange:            the CPU timeline, and the header states the rule:
                                                          "signaling an instance of MTLSharedEvent after any
                                                          workloads write counters (and waiting on that signal on
                                                          the CPU) is sufficient to ensure synchronization"
    MTL4CommandBuffer.h:206 resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:   the GPU timeline
```

**Two facts in that table decide the shape of this work, and neither is a guess.**

The first is that the CPU-timeline resolve's stated synchronization rule is *exactly what the frame ring already
does*: one commit a frame, a shared event signalled with the submission's value, and a wait on that value before
anything the GPU wrote is read. So the first version needs no new synchronization object - a heap, three
timestamps and a resolve after the ring's existing wait, which is the smallest candidate section 96 asks for.

The second is that the granularity the header calls `Precise` "may cause splitting of command encoders". That is
a cost the API documents rather than one this engine has to discover, and it is a warning that the counter path
can change the very thing it measures - which is section 91's A/B, not a footnote.

What is **not yet known** and must be measured rather than assumed: whether the resolved `timestamp` is in the
same timebase as the frame's `MTL4CommitFeedback.GPUStartTime/GPUEndTime`, or a different one that needs the
device's own conversion; and what an empty or single-entry range resolves to. Both are cheap to answer in a
process with no window in it, which is where section 90's smoke goes.

### The first counter smoke: the road works, the unit is a nanosecond, and the sampling points do not attribute

Section 90's smoke follows the header reading from the round before it, and its first version is red - which is
the result, not a setback, because what it establishes is *which* roads give a per-pass GPU time and none of the
two tried does.

**What works.** `MTL4CounterHeap.create` makes a heap of type `Timestamp` through the device's
`newCounterHeapWithDescriptor:error:`; timestamps written into it resolve with `resolveCounterRange:`; and the
resolve is legal after the ring's own wait because the header's stated rule - "signaling an instance of
`MTLSharedEvent` after any workloads write counters (and waiting on that signal on the CPU) is sufficient to
ensure synchronization" - is what the ring already does per submission. Nothing new was needed for
synchronization. Zero is refused as a reading, because the header documents that an invalidated entry resolves
as zero and a zero is not a time.

**The unit is measured, not assumed.** `sampleTimestamps:gpuTimestamp:` sampled twice around a 20 ms sleep
returns a GPU delta and a CPU delta that are equal to the tick:

```text
samplerGpuDeltaTicks=21721000   samplerCpuDeltaNs=21721000
samplerGpuDeltaTicks=25084959   samplerCpuDeltaNs=25084959
```

So **a counter tick is a nanosecond on this device**. The header never says the two clocks share a unit, which is
why it is measured; `MTL4CounterHeap`'s readings can therefore be read as nanoseconds without a conversion
factor.

**What does not work.** Two passes with a known and very different workload, bracketed by timestamps:

```text
first attempt   4096x4096 clear     ~16,000 ticks
                512x512 clear       ~31,000 ticks     (a 64-fold difference in store, backwards)
second attempt  128 fullscreen draws 14,644 ticks
                1 fullscreen draw     31,320 ticks     (128 megafragments, one seventh of the time)
```

The second attempt is the one that settles it. The first varied the attachment's size and both readings came out
about 31 us, which could have been a clear being cheap; the second varies only *how much is encoded between the
two markers*, and 128 fullscreen draws over a 1024x1024 attachment cannot cost less than one. It reports less.
Both sampling roads behave the same way - the command buffer's `writeTimestampIntoHeap:atIndex:` *and* the render
encoder's `writeTimestampWithGranularity:afterStage:intoHeap:atIndex:` with `Precise` and the fragment stage - so
what those calls mark is where the command processor has reached, not where the GPU has finished. The header's
own wording for the first is the hint: "work after this call may or may not have started".

**And the instrument proves its own workload is there**, which is the check that keeps the reading honest. The
large pass clears its attachment to black and draws the shader's colour, a pixel of it is read back on the CPU,
and every reading says `drawsLanded=true`. Without that, "the draws cost nothing" and "the timestamps are not
execution points" produce the same measurement, and they are different faults - so the pass's clear colour
differs from the shader's deliberately, and the pixel is what separates them.

**Then the mechanism turned out to be order, and it is measured.** A third shape brackets one pass per draw
count, ascending, each with its own encoder's after-fragment stamp:

```text
1 draw -> 35,008 ticks    16 -> 249,857    256 -> -227,076    4096 -> 226,983
```

The third stamp is **earlier** than the second by about 227,000 ticks in every probe - 6 of 6 at `Precise`, 4 of
4 at `Relaxed` - and the last lands within a hundred ticks of the second. Three candidate explanations were
removed by reading rather than by argument: the values are a plausible machine clock (~4.7 hours of
nanoseconds, the unit the sampler measured); the range resolve returns exactly what the per-entry road does, so
the packing is right; and the granularity makes no difference, so the header's warning that `Precise` "may cause
splitting of command encoders" is a real hazard and not this one. What is left is that the passes write
different attachments and nothing reads either, so nothing orders them - an `afterStage:` stamp fires when that
encoder's fragment stage drains, and for independent work that is not an order.

**The explanation that followed was tested and is refuted, and so are the two after it.** The first said the
passes wrote different attachments and nothing read either, so their fragment work could overlap. The test gives
every step the *same* texture, the first clearing it and each later one **loading** what the step before stored -
pass N cannot begin until pass N-1 has stored, which no GPU may reorder, and it is the smallest dependency this
API can express. The stamps invert in exactly the same place, by the same ~226,000 ticks. The header's warning
that `Precise` "may cause splitting of command encoders" is the second candidate and is also gone: both
granularities give the same shape. The third - that the inversion follows the work - is settled by running the
curve **descending**:

```text
ascending    1 -> 35,008    16 -> 249,857    256 -> -227,076    4096 -> 226,983
descending   4096 -> 270,315  256 -> 708      16 -> -127          1 -> -96,434
```

The inversion stays at entry 3 whichever way the counts run, so it is **positional**; its magnitude collapses
from ~226,000 ticks to ~120 when the heavy steps come first, so what moves it is the work *around* the entry and
not the entry's own count. Two stamps 120 ns apart are two events at one sampling point, not an order.

What is left is that **the sampling point is the driver's rather than the caller's** - which is what `Relaxed`'s
own documentation says of itself, "it may sample at command encoder boundaries", and what the numbers now show of
both granularities. So a difference between two stamps is not the work between them, and **no per-pass GPU time
is reported from this road** until one is found that samples where it is told to. The census stays red so that an
unproven instrument cannot look green, which is section 96's rule applied to an instrument rather than to an
optimisation. A smoke that went green by keeping the two draw counts whose ends happened to agree (4096 against 1
reads 6.8x) would have reported a per-pass time that is not one; the curve is what showed it, and the curve
stays.

### The scaler's creation is the evidence a resize leaves

Section 124 asks that a scaler be cached per configuration and that a resize rebuild rather than reuse, and section
81 asks for the identity that separates two configurations. All three claims had a code path and no reading,
because the Metal 4 path logged a refusal and never a creation - so in a session's log "the identity separated
them" and "an old scaler was silently reused for a new size" were indistinguishable. One line per creation fixes
that: a scaler is made on a cache miss, and a miss means the configuration changed.

Measured on ComplementaryReimagined_r5.9.1 at renderscale=55 with a mid-session resize, this path:

```text
Metal 4 MetalFX spatial scaling: made a scaler for 1408x792 to 2560x1440 ..., 1 in the cache
Metal 4 MetalFX spatial scaling: made a scaler for 1760x990 to 3200x1800 ..., 2 in the cache
```

The resize took the pack's scaled input from 1408x792 to 1760x990 and the output from 2560x1440 to 3200x1800, the
cache went from one entry to two, and the presented extent followed it (2560x1440 for 1591 frames, 3200x1800 for
2047). The MetalFX road was taken - Vitrail's own `The 55% render scale brings the picture back with MetalFX` - no
scaler was refused, the chain drew, a dimension change to `world-1` ran in the same session, and the quit was
clean: zero teardown warnings, `Stopping!`, `BUILD SUCCESSFUL`.

The residue is small and named: no asymmetric fixture has been scaled through the frame path, so the scaler's
orientation is proven on the device (40 of 40) and not in a live frame; and the design's "no fence" reading is
that this path's ordering comes from the one command buffer's encode order, which the frame above is consistent
with rather than proof of.

### The two generations against each other, and the arm spread that forbids the comparison

Sections 93 and 94 ask for the number this migration has to answer for: does the Metal 4 path cost more than the
Metal 3 path, on the same world, at the same size, in one session. The harness that asks it
(`tools/run-vitrail-performance.sh`) runs an ABAB staircase - it was BAAB's mirror image, `m3a, m4a, m3b, m4b` -
because a staircase's whole value is that each generation is measured twice, apart, and the two arms' agreement
is the error bar the verdict is read against. Session `run/perf-ab4` returned exit 0 with all four arms measured,
`--frames 600 --settle 25 --expect-target 3200x1800`, window 1600x900, Complementary on the staged `PerfWorld`,
whose player is in `world-1`/the nether rather than the overworld its historical baseline was taken in.

```text
arm   wallP50  wallP95  wallP99   gpuP50  gpuM4P50   depthAttach  loadedMiB   identities  copy-backs
m3a    21.17    23.63    24.80    21.05     0.00           2504     323336.6      333        5400
m4a    16.93    26.02    26.21     0.00    19.36           6242     398034.9      333        5400
m3b    21.29    27.32    28.57    21.33     0.00           2187     288573.9      333        5400
m4b    25.01    40.82    48.63     0.00    27.42           5706     380020.6      333        5400

harness summary, each against the arm before it:  m4a -8.1%, m3b +1.5%, m4b +30.1%
```

**Nothing here may be read as a Metal 4 verdict, and the reason is measured rather than cautious.** The two
Metal 3 arms agree to **0.6%** (`21.17` against `21.29`), which is the harness working: repeat the same
generation twice in one session and it answers the same number. The two Metal 4 arms differ by **47.7%**
(`16.93` against `25.01`), which is larger than any effect the measurement is being asked to resolve. The
staircase's error bar therefore contains the whole question, and section 67's rule applies as written: an arm
pair whose generations cannot be separated is `NOT MEASURED`, not "Metal 4 is 8% faster on the first pair and
30% slower on the second".

Two things were checked before calling it machine noise, and one of them was wrong.

**The pace is drawn from a different place in each generation, and the wait counters say so.** The frame probe
records the two waits separately, and the four arms split cleanly by generation:

```text
                          drawable wait                    submitWindow wait
m3a   calls=600 p50=0.06ms p95=2.78ms      calls=1200 p50=0.00ms p95=20.44ms
m3b   calls=600 p50=0.06ms p95=6.19ms      calls=1200 p50=0.00ms p95=19.86ms
m4a   calls=600 p50=14.64ms p95=23.96ms    calls=600  p50=0.00ms p95=0.00ms
m4b   calls=600 p50=18.90ms p95=39.10ms    calls=600  p50=0.00ms p95=0.00ms
```

Metal 3 draws 600 frames but calls the drawable wait 600 times at a `0.06 ms` median and the submission wait
**1200** times at roughly 20 ms: its pace is the submission ring, so the wall time is spent waiting for its own
submissions to come back. The Metal 4 arms wait on the **drawable** instead (`14.64` and `18.90` ms medians, 600
calls) and their submission wait is `0.00`: their pace is the display handing over the next drawable. So the
same 600-frame window is bounded by two different resources, and wall-clock time is not the same quantity in the
two arms. That is a mechanism, not a defect, and it is what makes the harness's own percentage summary
unusable across generations here.

**But the pace does not explain the Metal 4 spread, and that is registered rather than resolved.** The two Metal
4 arms differ by `8.08 ms` of wall P50 and by `8.06 ms` of `gpuM4P50` (`19.36` against `27.42`) - the same
magnitude on both sides of the encoder, so the difference is inside the frame's own cost and not only in how
long it waited to be allowed to start. The structural counters do not account for it either: `blits 5400` and
`blittedMiB 101022.1` are **identical to the digit** in all four arms, `pipelineIdentities 333` and
`pipelineKeys 333` are identical, and the two Metal 4 arms' remaining counters differ by 4-9%
(`loadedMiB` 398034.9 against 380020.6, `depthAttachments` 6242 against 5706) in the direction that would make
`m4a` the cheaper arm, which is the arm it is. The `gpuM4Feedbacks` count is 600 in both, so feedback collection
is not sampling differently.

This is written down as a residual - the fifth of this migration's registered residuals, after the sky strip,
the alpha channel, the compute fixture's flat ramp and the counter sampling points - because a 47.7% arm spread
on one generation cannot be dismissed and cannot be explained by anything measured so far. The next session that
wants the number should not repeat this shape: with the Metal 4 path paced by the drawable and its own frame
cost varying arm to arm, the measurement needs either a target that the display does not pace (the ring-depth
question section 84 already raised) or more than two arms per generation to bound the spread.

What the session did settle is smaller and still useful. **The counters are equal across generations where they
must be**: `blits 5400` and `blittedMiB 101022.1` identical in all four arms, `pipelineIdentities 333` and
`pipelineKeys 333` in all four with `compiles 0` and `compileMs 0.00`, so the two paths draw the same programs
and do the same copy-back work at the same size and count, and the cache reached steady state before the window
in every arm. **The attachment traffic gap is the registered pass-per-clear structure**, not scene drift:
`depthAttachments` runs 2187-2504 on Metal 3 against 5706-6242 on Metal 4 and `loadedMiB`
288573.9-323336.6 against 380020.6-398034.9, which is the mechanism the Performance section of
`docs/metal4-full-frame-report.md` already names - Metal 3 reuses one encoder across consecutive passes and
folds a clear into the pass that next uses the attachment where this path clears in a pass of its own, so the
following pass loads the attachment again.

**And the guard that must run before any of this is comparable was repaired in the same round.** The session
above only produced four arms because the target guard - which refuses a run whose world was not drawn at
`--expect-target`, since a moved display mode is machine state and a window on another target is not comparable
with the baseline - had been killing the harness after its first arm. Two faults, both real: it read the target
only from the probe's `The world renders at WxH`, where this Vitrail build states it with the pack's own
`Drawing <pack> from <root> for <dimension>, at WxH, N full screen passes`; and both of its lookups ran under
`set -o pipefail`, where a `grep` that matches nothing fails its pipeline, so the fallback to the second wording
never ran and the guard aborted the session instead of reporting. The reader now tries both wordings and both
lookups tolerate finding nothing, so an absent line is a reported condition. All three properties are pinned in
`tools/ci-vitrail-performance.py` and each was mutation-proved.

### The GUI is drawn and does not appear, and it is not the fragment stage

Reported from play: **under Metal 4 the game's own text and GUI are not on screen** - not the HUD's, not the
chat's, not the title screen's buttons or logo - while the world renders correctly. Everything below is measured
on this machine, in sessions with no pack, `-Dmetallum.execution=metal4`, and the frame probe's own counters: the
first question is whether the GUI is even encoded, the second is where it is lost.

**It is encoded.** On the title screen one frame's pass list is, in order: five `Animate <atlas>` passes, the
`Cubemap` pass (the panorama, one indexed draw of 36 indices, base vertex 0), the `GUI before blur` pass, and the
present - and the GUI's pass carries **7 indexed draws** through `gui_textured`, `gui_text` and `mojang_logo`,
into colour texture `0x7ab6ba3700` with `depth=true load=load store=store`. In a world frame the same pipelines
appear twice, in `GUI before blur` (with `vignette` and the vanilla `blur/0..5` post passes) and in
`GUI after blur`, both writing the target the present reads. So this is not "the GUI is never asked for" and not
"the GUI goes to another attachment": the present's own trace line, added for this question, names the picture it
samples - `presenting picture 0x7ab6ba3700 1708x960 into a drawable 0x...` - and it is the same texture the GUI's
pass wrote.

**And the pass's output reaches the screen, so the pass machinery is not the fault.** Forcing that pass's colour
attachment to be *cleared* to magenta (a diagnostic in the pass constructor, since reverted) makes the whole
window magenta: the load action, the store action, the encoder order and the present are all correct, and what is
missing is only what the GUI's draws write. The same sessions' render-target readbacks - the layer's `picture`
and `drawable`, the road built for the display that cannot be photographed - report the panorama
(`meanBGRA=(20,19,11,255)`) and no GUI at all.

**Then four probes, each in its own session, and none of them changed a single sampled pixel:**

```text
probe                                                     result
the M4 pass sets the front-facing winding to Clockwise    picture readback identical
every draw's cull mode forced to None                     picture readback identical
every pipeline built with blending disabled               picture readback identical
every fragment shader's alpha-0 discard_fragment removed  picture readback identical
the GUI pipelines' fragment colour forced to magenta      picture readback identical
```

That last one is the measurement this question needed: if the GUI's fragments were being produced at all - with
any colour, through any blend, with or without the discard - forcing their output to pure magenta would paint the
buttons and glyphs on the picture. Nothing appears, so **the GUI's fragments are never rasterized**, and the
whole fragment half of the pipeline (blend state, colour write mask, depth state, the discard, the sampled
textures) is excluded at once. The GUI's pipelines declare no depth state at all, so the engine already sets
`Always`/no-write for them and a depth attachment cannot be rejecting them either.

**The vertex stage's state is right on paper, which is where this round's account ends.** Read out of the same
trace: `pipeline/gui_textured`'s plan is `buffers(v=18,f=2) textures(v=0,f=3) samplers(v=2,f=3)
vertexLayouts=16 from slot 2 names=Projection=b0,DynamicTransforms=b1,Sampler0=t2`; the pass fills the vertex
buffer at table slot 2 with `address 0x10002e78000 stride 24 slice offset 0 length 262144`; the translated MSL
declares `Position [[attribute(0)]] UV0 [[attribute(1)]] Color [[attribute(2)]]` with
`Projection [[buffer(0)]]` and `DynamicTransforms [[buffer(1)]]`; and the uniform *contents* read back from the
buffers are correct - the GUI's orthographic projection, and an identity with `z = -11000` at byte offset 256 of
the dynamic-uniform ring, against the panorama's own rotation at offset 0. The panorama's fill is the same shape
in every respect (`slot 0 -> table 2`, stride 12) and it rasterizes.

**What the same trace does show is how narrow the working set is.** Of the pipelines a title-screen frame binds a
vertex buffer through at all, there are five: `gui_textured`, `gui_text`, `gui`, `mojang_logo` and `panorama` -
and only `panorama` rasterizes. The one thing the GUI's formats have that the panorama's does not is a second and
third vertex element (`POSITION_COLOR`, `POSITION_TEX_COLOR` against `POSITION`) and a 16- or 24-byte stride
against 12, so the next state to compare between the generations is the **vertex descriptor those formats build**
- the one object of the user's list that this round did not diff, because both generations' builders are
character-for-character the same and the difference, if there is one, is in what the descriptor receives.

**Two state differences between the generations surfaced while looking, and neither is this fault.** The Metal 3
pass sets `setFrontFacingWinding(MTLWinding.Clockwise)` on every pipeline change and this one does not; setting it
here explicitly changed no sampled pixel, and the probe was reverted - the M4 encoder's default winding is
clockwise, as the reference generation's explicit call assumes. And the Metal 3 pass **applies the depth bias** a
pipeline carries (`setDepthBias:slopeScale:clamp:`) where this one stores the bias in its artifact and never sets
it: that is a real gap in this generation's state, it belongs to shadow and depth-offset geometry rather than to
the GUI, and it should be fixed and measured on its own rather than folded into this question.

**Then it was found, and it is one line of missing residency.** The reading that turned the hunt was a probe that
read back what the vertex buffer the GUI's draws bind actually *holds*: `unreadable:IllegalStateException` - the
buffer is not CPU-visible, so the game cannot be filling it directly. The vanilla source says what it does
instead: `net.minecraft.client.renderer.StagedVertexBuffer` maps a CPU-visible **staging** buffer, writes the
frame's vertices into it, and moves them into the real vertex buffer with a single
`commandEncoder.copyToBuffer(staging.slice(...), vertexBuffer.slice(...))` - and then draws each range with a
**base vertex** into the moved block, which is why every draw in that pass carries a non-zero base vertex and the
one that does not is the first block.

`Metal4FrameEncoder.copyToBuffer` was the only copy road in the class that declared **neither** of its resources
with `useResource`, where `writeToBuffer`, `writeToTexture`, `copyBufferToTexture`, `copyTextureToTexture` and
`copyTextureToBuffer` all declare both. The Metal 4 header asks a copy's resources to be marked in an
`MTLResidencySet`, and an undeclared resource makes a copy do nothing here - silently. So the GUI's, the particles'
and the entities' vertices arrived as zeros, every triangle of every one of those draws collapsed to a point, and
the draws were encoded, correctly bound, correctly stated and invisible. The world rendered through all of it
because Sodium fills its own buffers and because every other upload road declared what it moved.

Declaring both ends is the whole fix, and the reading is the presented picture's own readback on a forced Metal 4
title screen, one session each:

```text
                                   mean BGRA       the GUI's own samples in the 5x5 grid
before   metal4                     (19, 17, 11)    none - the panorama only
after    metal4                     (40, 39, 33)    ff3f3f3f, ff9ea2ad, ff000000
         metal3 (the reference)     (40, 39, 33)    ff3f3f3f, ff9ea2ad, ff000000
```

The two generations read **identically** on that screen, sample for sample: `ff3f3f3f` is the button sprite's grey,
`ff9ea2ad` the logo's, `ff000000` the glyph outlines and the dim overlay around them, and only the animated
panorama's phase differs in the background. An in-world session with the same fix renders with no fault, no refusal
and no restart. What is **NOT MEASURED** is an in-world text reading taken on its own - the staged world's player
is in spectator mode, which hides the HUD, and this machine refuses to press keys - so the in-world HUD is covered
by construction (the same `GuiRenderer` through the same `StagedVertexBuffer` road) and by the title screen's own
glyphs, which do read back equal to Metal 3's.

**Two things this cost, both recorded as lessons rather than as prose.** The five probes that bounded the fault
above the fragment stage - winding, cull, blend, the alpha-0 discard, and a forced fragment colour - are what made
"the draws are invisible" a measurement instead of an opinion, and the forced-colour probe is kept and pinned for
the same reason on every later staircase rung. And a suspicion that looked strong was tested and dropped: every
non-zero base vertex in the frame belonged to the GUI, so the base vertex was the obvious candidate - emulating it
as a shift of the vertex buffer's address left the frame byte-identical, which says the base vertex was being
applied, and that probe was reverted rather than kept.

### The arm spread: the machine is refuted by a trace, the slot wait is named and is not the cost

Two Metal 4 arms of one session differ by up to 50% while the Metal 3 arms beside them agree to 0.2%, and the
harness had exactly one instrument for that question: the kernel's load average, written at each arm's start and
at its window's close. That instrument cannot answer it. `vm.loadavg` is a one-minute average, so a burst of half a
minute barely moves it, and `run/perf-ab6` is a session that shows equal load at both ends of an arm whose own cost
moved by half. **A spread that is not the machine's has to be visible as not the machine's**, and that needs the
reading taken *while* the arm runs.

So the harness keeps it now. Every arm writes `load-trace.txt` beside `load.txt` - the same reading every five
seconds, with `window-opened` and `window-closed` markers so a reader can slice the trace to the frames the probe
counted, bounded at 240 samples, and stopped on both ways an arm can end. Verifying that the markers survive a live
run is what found the bug in the first version: the tracer redirected its own file while the arm appended its
markers to the same one, so the tracer's descriptor carried its own offset and its next sample landed exactly on
the marker just written, erasing it. `window-opened` was in **none** of the four arms' traces - a boundary no
reader could slice by. The file is emptied once per arm and every writer appends now, and the contract refuses the
redirecting form and the missing truncation, both mutation-proved. **A static pin is not a reading**: the contract
passed on the code that lost the marker, and only a session said so.

`run/m4-loadtrace` was the first session with the trace: four Metal 4 arms of one configuration, the same pack,
world, target, window and 25 s of settle, `-Dmetallum.metal4FrameStats=true`. They read 21.10, 18.52, 18.22 and
21.57 ms a frame. The **fastest arm ran at the highest load** (mean 4.28 against the slowest-but-one's 2.78) and,
bucketed against each arm's own sixty-frame cost, the correlation of load with cost is negative in three arms of
four (-0.30, -0.13, -0.08, +0.27). Three other things that session settled:

- **The scene drift the comparer refuses the session for does not order the cost.** The guard refused all four arms
  (`renderPasses` of m4c -2.3% against m4a, `depthAttachments` of m4b +2.4%, tolerances 2% and 5%), and the drift is
  still not the cost: m4b opened *more* render passes a frame than m4c and was not slower.
- **The display is a constant, not a variable.** All six of that day's sessions left the same byte-identical
  156220-byte capture - the flat black a locked or asleep display produces - so the session whose three arms agreed
  to 1.6% and the session whose arms did not had the same display state. It is also the one reason every picture
  column of that day is void.
- **`Metal 4 frame stats`'s `msPerFrame` is the encode, not the frame period** - it begins at a frame's first encode
  and is taken at that frame's commit, so it excludes the drawable wait and the CPU between frames, where the
  probe's `windowMs/windowFrames` is the period. They differ by 1.8x to 2.6x and the ratio moves arm to arm, so the
  earlier reading of "9.67 ms in one sixty-frame bucket and 18.71 in another" is the **encode** moving; it is the
  right instrument for that and the wrong one for a frame rate.

**Then the blocker's own first-named candidate was driven as a lever instead of watched.**
`-Dmetallum.metal4RingSlots=N` is a switch the migration already had for fault traces; `run/m4-rings` ran four
Metal 4 arms at one, two, three and four frames in flight:

```text
arm      slots  ms a frame  wallP50  wallP95   gpuM4P50   drawable wait  submitWindow total  submit p50
slots1     1      20.08      20.14    21.25     18.31       11.11 ms        11031.24 ms      18.41 ms
slots2     2      18.24      18.17    20.45     18.35       16.71 ms         6635.65 ms      14.68 ms
slots3     3      18.32       9.53    37.14     18.48     1610.68 ms          951.49 ms       0.00 ms
slots4     4      24.37      16.90    48.46     24.39     1742.78 ms            0.77 ms       0.00 ms
```

The two populations are the slot wait, and one slot proves it by removing them: three slots is bimodal (P50 9.53
against P95 37.14) with a submission wait of *zero for most frames* and 951 ms concentrated in a few, and one slot
makes every frame wait for the previous submission (p50 18.41 ms, 11031 ms in total) and leaves P50 20.14 against
P95 21.25 - a 1.06x gap instead of 3.9x. **And the slot wait is not what makes an arm slow**: four slots removes the
submission wait almost entirely (0.77 ms) and is the slowest arm of the four, 24.37 ms with 24.39 of its own commit
feedback, while the three arms at one, two and three slots read their own GPU time 18.31, 18.35 and 18.48 - a 0.9%
spread, the tightest this path has produced. Above the migration's own depth the ring is not a free variable, and a
spread of this kind is not the ring's wait. What is **NOT LOCALISED** is what the fourth slot did: whether it made
the GPU's work slower or made the driver's per-commit window wider is not something this session can separate.

The session was then repeated, and that is what makes it a reading rather than an anecdote. `run/m4-rings2`, the
same four arms in the same order, completed three: the bimodality is 3.91x at three slots, 1.12x at two and 1.05x
at one, the same shape to the digit; and the *six* arms of the two sessions at those three depths read their own
commit feedback **18.23, 18.31, 18.35, 18.44, 18.48 and 18.48 ms - 1.4% across two sessions and three
configurations**, the tightest this path has ever read. The fourth arm of the repeat produced no window at all: the
pack reached its first full frame, the encoder ran 1402 submissions and closed cleanly (its ring state naming four
awaited submissions, so the switch took effect) 27 s later, two seconds after the settle ended, with no probe line
and no fault in its log. That is recorded as a second instance of a harness-shaped end - the same shape as the
forced-Metal-4 session that landed on OpenGL - and not as a property of four slots, because one session's four-slot
arm completed and this one's did not.

### The first comparison the GPU itself was busy for, and the two clients that were already on it

Every M3-against-M4 number this migration has taken was a frame that something else paced: the display's
handover, or - with the display asleep - this path's own ring, whose slot wait turns a window bimodal. The frame
period was therefore never the renderer's work, and the arm spreads that blocked the comparison were the pacer
moving rather than the path. What was missing was a reading of the *resource the claim is about*. The driver
keeps one, and it costs nothing to read: `ioreg -r -c IOAccelerator` exposes `PerformanceStatistics` - device,
renderer and tiler utilization, allocated and in-use memory - and `AGCInfo.fLastSubmissionPID`, the process whose
submission the accelerator handled most recently. `tools/gpu-trace.sh` samples that every two seconds for a
session, and the harness now starts and stops it so that every session carries the evidence.

It answered two questions at once, and the first one was not the one it was written for. **At idle, with no game
running, the accelerator is 4-33% busy and the most recent submission belongs to Microsoft Edge (pid 67625)** -
the browser the Web GUI driving this programme is rendered in - with **UURemoteServer (pid 925)**, a remote-desktop
server that captures and encodes the screen, and WindowServer beside it. Between the arms of the session below the
same trace read the accelerator **85-87% busy**. So this machine's GPU is oversubscribed by construction, which no
host-side load average could ever have shown: those clients are GPU-heavy and CPU-light, which is why five
sessions of load sampling failed to order a single arm.

`run/m4-ab7` is the comparison that follows from having the instrument: one session, four arms interleaved in the
plan's own order (M3, M4, M3, M4), Complementary on the staged world at 3200x1800, 600 frames a window and 25 s of
settle, with the GPU sampled throughout.

```text
arm  gen  ms a frame  wallP50  wallP95  own GPU P50     drawable wait          submission wait
m3a  M3     20.31      20.50    23.72   gpuP50   20.54   p50 0.01,  8 ms tot   1200 calls, p95 21.53, 11156 ms tot
m4a  M4     23.85      24.23    29.19   gpuM4P50 23.81   p50 15.36, 7191 ms tot    600 calls,         0.56 ms tot
m3b  M3     20.70      20.81    22.25   gpuP50   20.70   p50 0.01, 56 ms tot   1200 calls, p95 20.07, 11359 ms tot
m4b  M4     27.45      27.40    30.11   gpuM4P50 27.36   p50 0.49, 7138 ms tot    600 calls,         0.42 ms tot

device utilization from the same session's trace: mean 100.0%, max 100%, in all four arms
```

Three readings, and the first is what makes the other two mean anything:

- **The GPU was saturated in every arm**, so the frame period is GPU work in both generations and the comparison
  is finally of work rather than of a pacer. That is the condition under which the plan's performance gate can be
  asked at all.
- **This path asks the GPU for 16-35% more time a frame** - 23.85 and 27.45 against 20.31 and 20.70, by its own
  commit feedback 23.81 and 27.36 against 20.54 and 20.70 - with the caveat the arms themselves supply: Metal 3
  repeats to 1.9% where this path's two arms are 15% apart, so the figure is a range. The cheap end of the range
  is already far outside the plan's `median regression <= ~3%`, so by section 97 this path stays forced and
  experimental and AUTO is not enabled on it. **The question has changed shape**: not "is Metal 4 slower" - it is,
  measured - but "which of the frame's work is bigger", and that is what the counter infrastructure of section 88
  exists for.
- **The two generations are paced by different resources, which is why the wall-clock columns are printed beside
  each other rather than subtracted.** Metal 3's frame is its submission-index wait (1200 waits, p95 ~21 ms,
  totalling the window, 8-56 ms of drawable wait); this path's is its drawable handover (7191 and 7138 ms) with
  about half a millisecond of submission wait. A comparison of the two periods is a comparison of two different
  waits plus whatever work happens to be inside them.

And the pictures, which the session could finally take because the display was awake: `m3a` against `m4a` is a
mean channel difference of 1.29 with 0.55% of pixels differing by more than 8; `m3a` against `m4b` 1.40 and 0.94%;
and **`m3a` against `m3b` - the reference against itself - 0.99 and 0.40%, with the same worst pixel, 222 at
`(3540, 39)`, in all three comparisons**. The generations differ by about what one arm of the reference differs
from another, on a pinned scene in one session. That is the correctness half of this round and it is measured, not
argued.

### The counter road was never the problem: section 90's smoke was failing on its own arithmetic

Section 90 asks for the smallest GPU-counter smoke there is - one pass, a known workload, a timestamp before and
after it, and the property that more work reads as more time - and this smoke has been red since it was written.
Blocker 15 recorded the verdict the readings seemed to force: the heap, the resolve and the unit all work, but the
timestamps do not partition the work, `stamps[3] < stamps[2]` in every probe, and the remaining explanation was
that "the sampling point is the driver's rather than the caller's".

Reading the two headers side by side is what moved it. `MTL4CommandBuffer.h` says of its own marker: "captures a
timestamp after work prior to this command in the command buffer is complete. Work after this call may or may not
have started." That is a pass boundary - no stage, no granularity - exactly what a curve of passes needs. The
render encoder's form takes both (`writeTimestampWithGranularity:afterStage:intoHeap:atIndex:`), and its
`Relaxed` documentation says it "may sample at command encoder boundaries". The smoke's start marker was the
command buffer's and its boundaries were the encoder's, so the curve was a mixture of two sampling points. And
under that, a line: the loop writes one boundary per step at `step + 1`, filling entries 1 to 4 with entry 0 as
the start, and a leftover marker from a three-marker two-pass shape wrote **entry 2 a second time, after every
step**. Entry 2 held "the end of everything" while entry 3 held "the end of step 2", so the inversion was true by
construction - and its magnitude, and its collapse to ~120 ticks when the heavy steps came first, were that
line's arithmetic too.

Three changes, each measured rather than assumed:

- **one marker per boundary, from one site**, written after the pass's encoder is closed;
- **one form for every entry**, the command buffer's, with the header's sentence as the reason;
- **a warm-up pass the curve does not count**, because the curve's first step was the command buffer's first
  encoder *and* its only clearing pass, and it reported ~27,000-33,000 ticks against the sixteen-draw step's
  ~1,000-22,000 - the lightest step the most expensive one.

With those in, the curve is monotone and repeatable, and a fourth thing turned out to be worth measuring rather
than fixing: the road has a **floor**. With the same fixes and the old counts of 1, 16, 256 and 4096, the two
heavy steps repeated to two per cent while 1 and 16 *swapped order between probes* (1,069 against 1,919 ticks the
other way round). So an interval below roughly two thousand ticks on this device is not ordered, and the curve is
`{64, 256, 1024, 4096}` because every step has to be above the floor:

```text
probe  64 draws   256 draws   1024 draws   4096 draws
1         6105       18382        54246       171134
2         6729       18566        54283       170540
3         6720       18343        54304       166420
4         6075       18852        54296       166634

gpuTime=true in 3 of 3 and 4 of 4 probes, rangeAgrees=true, drawsLanded=true, gpuTicksPerCpuNs=1.0000
```

The unit field is corrected in the same round and for the same reason: it printed the absolute first GPU stamp
over a million where a reader checking the tick's unit needs the ratio of the two deltas, which is 1.0000 - a tick
is a nanosecond, and now the line says so.

What that unblocks is the reason it mattered. Section 92 asks for three kinds of timing to be kept apart and there
are now three: CPU encode timing, whole-commit driver timing (`MTL4CommitFeedback.GPUStartTime/GPUEndTime`), and
**GPU counter timing at command-buffer granularity**, above the floor. Section 95's candidates - argument-table
write dedup, residency batching, barrier narrowing, encoder reuse, descriptor reuse, allocator sizing - can be
ranked by a GPU-side attribution instead of a whole-frame A/B alone, which is what section 96 asks for before any
of them is touched. What is still not claimed is a sample *inside* one pass: every marker sits at an encoder
boundary, and that is now by design rather than by defeat.

### The first per-pass GPU time of a real frame, and the claim it overturns

Section 92 asked for three kinds of timing to be kept apart. Two of them existed: the CPU's encode time, and the
driver's own `GPUStartTime`/`GPUEndTime` for a submission. The third - GPU counter ticks between markers this path
places - became available when the smoke was fixed (a duplicated heap index, two sampling forms in one curve and a
first step that was both the clearing pass and the command buffer's first encoder), and this is the round that
pointed it at a real frame.

`-Dmetallum.metal4PassTimes=true` puts one command-buffer marker behind every pass the M4 path opens, and reads the
intervals when the ring begins that slot again - which is exactly where the header's condition is met, because the
ring's `beginFrame` has already waited for that slot's previous submission to complete. One heap per slot, the
marker written through the same `MTL4CounterHeap.writeTimestamp` the smoke uses (one sender for the selector in the
whole engine), the present counted as a pass like any other, and a line that names the kind of timing, the road's
2 us floor, and the ticks as microseconds a frame.

On Complementary, forced Metal 4, 600 frames:

```text
Metal 4 GPU pass time (GPU ticks between markers this path placed, never the CPU's encode time):
  frames=600 labels=43 totalUsAFrame=378.301 unread=0 floorUs=2.0
  top=[Vitrail world-1/composite1 241.068, Vitrail world-1/composite6 18.949, Vitrail shadow chunk 10.876,
       Blit render target 10.716, Vitrail world-1/deferred1 9.814, Vitrail world-1/composite 9.665,
       Vitrail chunk 9.230, Vitrail world-1/composite5 7.869] and 35 more
```

Two things follow, and the second is the one that matters.

**The frame's GPU time has a shape now.** `world-1/composite1` is 241.068 us of the 378.301 the markers attribute -
64% of the frame's measured GPU time in one pass, with the next heaviest at 18.949. Whatever the next optimisation
round is about, it starts here, and it starts from a GPU-side number rather than from a native call count.

**And the claim the previous round made is overturned by it.** That round read `run/m4-ab7` as "this path asks the
GPU for 16-35% more time a frame", on the strength of the commit window and a device utilization of 100%. The
counter says the frame's own pass work is **378 microseconds** while the commit window is 19.4 milliseconds - and
the header says why: `MTL4CommandQueue`'s `waitForDrawable:` "schedules a wait operation on the command queue to
ensure the display is no longer using a specific Metal drawable... before executing any subsequent commands". That
wait is *inside* the commit, so `MTL4CommitFeedback.GPUStartTime/GPUEndTime` measures the wait for the display plus
the work, not the work. The 100% utilization is not evidence about this frame either: the same session's own trace
reads the accelerator 85-87% busy between arms with no game running, because Edge, UURemoteServer and WindowServer
are on it. **So Metal 3 and Metal 4 do not differ by 17-35% of renderer work; they differ by 17-35% of presented
rate, and the two timings that differ are the two waits** - Metal 3's submission-index wait against this path's
drawable handover. The performance question is not answered; it is finally being asked with the right instrument.

**And the instrument does something to what it measures, which section 91 predicted and this session confirmed.**
Four arms of one session - reader off, on, off, on - read **21.79 and 21.80 ms a frame with it off and 19.37 and
19.45 with it on**. The markers made the frame **11% faster**, twice over. So the table is a diagnostic reading and
never a performance verdict, the switch stays off by default, and the effect is now the migration's first candidate
for a *speedup*: what a marker between two passes does to the driver's scheduling has to be measured as its own
mechanism (section 96) before it is believed, and the obvious first hypothesis - that serialising two passes at a
boundary costs less than letting them overlap - is a hypothesis and not a reading.

### Vanilla's own frame: clouds, rain and the game's particles, in the overworld

Every measurement this migration had taken was a shader pack's frame, and every one of them had `renderClouds`
false because a pack draws its own clouds. So the things a pack *replaces* - the game's cloud pass, the weather's
particles, the mobs - had never been in a frame that was measured, and a migration can lose exactly those without
noticing. The user's direction was to test the overworld with vanilla's own rendering in scope, and this is the
round that made that possible and read it.

Four switches, each off by default so that no baseline written before them moves:

  - `--vanilla-clouds on|off` writes `renderClouds`, which the profile had hardcoded to false;
  - `--weather clear|rain|thunder` leaves the world in that state with the weather cycle still off. The cycle
    rule stops the weather *changing* and does nothing about what the save already holds, so rain - vanilla's
    largest particle system - needs the state written, not the cycle;
  - `--keep-entities` keeps the world's mobs instead of taking them out, for a correctness reading rather than an
    A/B (the still-life scene stays the default, because an entity that moved makes two launches two scenes);
  - `--vanilla-particles` stages `tools/fixtures/vanilla-showcase`, a world datapack whose tick function emits
    twenty of the game's own particle types at the camera every tick - the one deterministic way to get particles
    into a frame when nothing can press a key or break a block.

**The fixture earned its refusal before it earned its reading.** The first version wrote the older positional
options for the particles that take them - `particle minecraft:dust 1.0 0.4 0.1 1.5 ...` - and this game version
refused the **whole function** ("Can't parse particle options: No key scale in MapLike[{}]; No key color in
MapLike[{}]"), so the datapack was found, loaded, and emitted nothing while every harness line said the fixture
had been copied in: a scene with no particles in it that reads as a scene with particles, which is the false green
this programme keeps paying for. The harness now refuses an arm whose log does not say the datapack was found or
does say the tick function failed, and both checks are pinned and mutation-proved. The moment they were in place
the first run was refused, the options were rewritten as maps, and the second run drew them.

`run/vanilla-clouds` - overworld, no shader pack, clouds on, weather clear, no particles, still-life, 600 frames,
arms interleaved M3/M4/M3/M4 - is the reading:

```text
arm  gen  ms a frame  frames/s  own GPU time  drawable wait p50  loadedMiB  storedMiB  depthAtt.  clearEnc.  renderPasses
m3a  M3     2.17       460.7      0.84 ms        0.02 ms          26921.3     79655.7     1800          0          1956
m4a  M4     2.54       393.8      0.90 ms        0.77 ms         106129.5    224781.8     5400       3000          2586
m3b  M3     2.16       463.2      0.86 ms        0.02 ms          26921.3     79655.7     1800          0          1956
m4b  M4     2.46       407.3      0.89 ms        0.87 ms         106108.2    224760.5     5400       3000          2580
```

Three things follow. **The game's own cloud pass is drawn on this path and drawn right**: the pictures put M3
against M4 at 0.21% and 0.40% of pixels differing, against the reference's own 0.24% between its two arms. **The
GPU work is the same to 5%** (0.84/0.86 against 0.89/0.90 ms) while the period is 13-17% longer, which is the
shape every earlier session had: the difference is in the waits, this path waiting on the drawable where the
reference waits on its submission index. And **the structural footprint is the pack frames' footprint exactly** -
five clear encoders a frame against none, depth attachments 3x, loadedMiB +294%, renderPasses +32%, no viewport
call where the reference makes 4.3 - none of it moved by a cloud, a raindrop or a particle.

`run/vanilla-overworld` is the same scene with rain and the particles in it, and it produced the round's other
lesson: **two arms of the reference itself differ in 68.45% of pixels there** (mean channel difference 35.64),
because rain streaks and particle offsets are animated and two launches land on different phases. The generation
comparison in that session, 43.65, is the same order - so it says nothing about the path, and the lesson is the
plan's own section 116 arriving in a vanilla scene rather than a temporal pack: a picture verdict needs a scene
whose pixels do not move between launches. The counters were the reading there, and they are the same ones the
cloud session gives to four digits (loadedMiB 106130 against 106129): the traffic this path reports is its pass
structure and not the scene.

**What is NOT MEASURED**, said plainly because the surface is now wide: a deterministic particle or rain scene
(the fixture's emission is random by construction, so its pixels move between launches - a per-tick pattern with
no spread, or one tick photographed while frozen, is what a picture verdict on particles needs); what the mobs and
block entities draw on this path, which is what `--keep-entities` is for and which no session has yet read; and
the pack-and-vanilla-features combination, since every session above is a no-pack one.

### The particle grid, and why vanilla's particles still have no picture verdict

The first particle fixture emitted every type with a spread and a speed - what a player sees - and the harness
photographs one frame of each launch, so the reading it produced was the animation's: with rain and those
particles in the frame, **two arms of the reference implementation itself differed in 68.45% of pixels**. The
obvious fix was to take the motion out: every particle now goes out with `0 0 0 0 1` after its position - no spread
box, no speed, one particle - at a cell of a grid in front of the camera in local (`^`) coordinates, one cell per
render family. Stillness by construction, and a scene that should be the same picture in every launch.

It is not, and the measurement said so before anyone could believe otherwise. `run/vanilla-grid`, the same scene
and flags as `run/vanilla-clouds`:

```text
                                      mean channel difference   pixels differing   differing by more than 8
m3a vs m3b, no particles (clouds only)             0.02               0.24%               0.03%
m3a vs m3b, the still grid                         12.18              24.83%              19.24%
m3a vs m4a, the still grid                         12.14              24.85%              18.88%

what the particles add, each arm against the same scene with none:
m3a 14.88 / 27.69%    m3b 5.92 / 17.35%    m4a 5.77 / 17.19%
```

Three things, and no more, are readable there. The particles **are** drawn on both generations - each arm differs
from the particle-free scene by 5.8 to 14.9 of mean channel difference, so the fixture reaches the frame. This
path's contribution is **inside the reference's own spread** (m4a 5.77 against m3b 5.92 and m3a 14.88), so nothing
about it is generation-specific. And the picture verdict on vanilla particles stays **NOT MEASURED**, now for a
named reason rather than a suspicion: a particle's lifetime is drawn per particle, so which particles a frame
holds - and how faded they are - depends on the tick the screenshot lands on. Taking the spread and the speed out
removed the particles' *motion* and not their *randomness*.

What that would need is an emission whose appearance does not age: one tick's particles photographed while frozen,
or a static block-entity form whose texture animation is driven by the frozen clock. Neither is built, and this is
recorded as the second attempt rather than as a fixture that works.

The same session carried a second lesson about the harness. Its fourth arm read **10.68 ms a frame against the
second M4 arm's 2.46** - 4.23 against 1.11 of its own commit feedback, 8.06 ms of drawable wait at the median -
an arm-level outlier of 433% that section 115 says to discard. Nothing refused it: a session with two generations
in it skips the structural drift check by design, and its own line says so, so the outlier has to be noticed by
reading the table. **An outlier guard for the two-generation case is owed**, and it is the next harness change
rather than a note.

### What a mob draws, and a fixture that says whether it did

The staged world holds no entities: with `--keep-entities` the frame's passes a frame, its pipeline identities and
its depth attachments came out the still-life scene's to the digit, so the entity question had no scene to be asked
in. `tools/fixtures/vanilla-mobs` builds one - a pig, a cow, an armour stand, a dropped item and an experience orb,
summoned in front of the camera, each with `NoAI:1b` so its pose does not move between launches.

**The fixture's proof is the part worth keeping.** Every summon is preceded by a `say` naming it and the harness
refuses an arm whose log does not carry the line - because "staged, loaded and did nothing" is how this scene has
already failed twice. Writing the proof found a third failure for free: the first version put the `say` *after* the
summon, and both are guarded by `unless entity`, so the summon is what makes the guard false and the proof could
never fire. That ordering is now pinned, with the mutation that reverses it refused.

What the proof then showed in a live session is recorded rather than papered over: the pig and the cow lines repeat
every four to five seconds, so a session holds more entities than the five it asks for and two arms of one
configuration hold different numbers of them. The readings that follow have to be read with that in mind.

`run/vanilla-mobs2`, clouds on, 300 frames, arms interleaved M3/M4/M3/M4:

```text
arm  gen  ms a frame  passes a frame  depth a frame  pipeline  identities
m3a  M3     8.30        4.00             3.00          3807        99
m4a  M4    12.45       11.75            15.25          9130        99
m3b  M3     8.30        4.00             3.00          3996        99
m4b  M4    12.45       11.73            15.23          9131        99

pictures by band (mean channel difference / share of pixels over 8):
band                m3a vs m3b       m3a vs m4a       m3a vs m4b
sky   (top 12%)     0.05 (0.1%)      0.09 (0.1%)      0.08 (0.1%)
middle (40-60%)     0.74 (1.3%)      1.90 (6.1%)      0.76 (1.6%)
lower  (70-90%)     0.05 (0.1%)      0.29 (1.4%)      1.21 (5.1%)
```

Both generations draw entities - this path opens 11.7 passes a frame where its still-life frame opened 4.3 - and the
sky is identical across all four arms, so the differences are in the entity bands. They are not in the *same* band
for the two Metal 4 arms, though (m4a in the middle, m4b in the lower, each agreeing elsewhere), and a renderer
difference would sit in one place: what moves is the fixture's placement, which its own proof then confirmed by
logging the pig and the cow again every few seconds. **An entity picture verdict is therefore NOT MEASURED, for a
fixture reason that is named and logged**, and placing the entities once is what the fixture owes next.

### The harness names the arm the machine spoiled

`run/vanilla-grid`'s fourth arm read 10.68 ms a frame against the second Metal 4 arm's 2.46 - 4.35x - while every
structural counter agreed to a tenth of a per cent, and nothing refused it: a session with two generations in it
skips the per-generation structural check by design. Section 115 says to discard an arm like that, and a reader can
only discard what is named, so the comparer now compares each arm against the *fastest arm of its own generation*
and prints an `arm outlier:` line naming it, refusing the session with the same code a scene drift does. The
threshold is measured rather than chosen - this path's own arms legitimately spread to 15%, and `run/m4-four`'s
27.50 ms arm is named at 1.51x, which is the arm this report had discarded by hand. Six checks are pinned and
mutation-proved, and two of them survived a first draft: a check that records nothing, and one that compares no arm.

### The entity scene is one placement, and what a mob draws is the same on both generations

The entity fixture's own proof is what found its fault. A live session logged "placed the pig" and "placed the cow"
**every four to five seconds**, so a session held a number of entities that grew with its window and two arms of one
session held different numbers of them - which is exactly why their pictures differed in different screen bands.
The tag that was missing is `Invulnerable`: the summons are at the camera's own height, which is not necessarily
above the terrain, and a mob placed inside a block takes suffocation damage every tick and dies, so the guard found
no pig a few seconds later and placed another. With `NoAI` (no movement, no look), `NoGravity` (no falling),
`Invulnerable` (no dying) and `PersistenceRequired` (no despawning) each type is placed a stable **two** times an
arm, identical in all four arms of two consecutive sessions.

The number is two and not one, and the harness does not pretend to know why: what a comparison needs is that the
arms are one scene, so the check became *equality between the arms* - each arm's placements are recorded and the
session is refused if an entity's count differs across them - rather than a constant the fixture cannot control.
Five mutations were run against the pins, and each exits 1 with its own sentence.

The reading it bought, `run/vanilla-mobs3`, clouds on, 300 frames, arms interleaved M3/M4/M3/M4:

```text
picture, m3a against m3b:  mean 0.02, 0.24% of pixels differ at all   (the reference against itself)
picture, m3a against m4a:  mean 0.02, 0.63% of pixels differ at all
picture, m3a against m4b:  mean 0.02, 0.88% of pixels differ at all
   - the same worst pixel, 218 at (3547,43), in all three

by band:                     m3a vs m3b      m3a vs m4a      m3a vs m4b
sky   (top 12%)              0.13 (0.1%)     0.10 (0.1%)     0.08 (0.1%)
middle (40-60%)              0.00 (0.0%)     0.00 (0.0%)     0.00 (0.0%)
lower  (70-90%)              0.02 (0.0%)     0.00 (0.0%)     0.03 (0.1%)
```

**The entities are drawn identically.** The whole image agrees to the reference's own 0.02, the band the entities
occupy is identical to the byte, and the single pixel all three arms disagree at is the same pixel - which is what
a cross-launch difference looks like and not a generation difference. The second session of the pair
(`run/vanilla-mobs4`) confirmed the placement counts and produced no picture at all: the display had gone to sleep,
every capture was one flat colour, and the harness refused the session on it - which is the guard doing its job
rather than a lost measurement, since the reading above is from the session whose display was awake.

### Block entities, and a block predicate that cannot guard the command that makes its position real

What a *block's own* renderer draws - a chest's model, a bell, a banner's cloth, a shulker box, an enchanting
table's book - is neither terrain nor an entity in the entity stores, so no scene this harness had measured
contained one. `tools/fixtures/vanilla-blocks` places five of them in front of the camera, and it took three
measured failures to find a form that works:

```text
unless block ^1 ^1 ^4 minecraft:chest     the fixture's liveness line showed the function running 1138 times
                                          in a sixty-frame arm, and not one placement fired - so a block
                                          predicate does not resolve `^` the way an entity's position does
unless block ~1 ~1 ~4 minecraft:chest     the same 1142 runs, the same zero placements

and a four-way diagnostic, one arm, sixty frames:
  say A                                   1146   the function runs
  execute if block ~ ~ ~ minecraft:air     0     never matches, at the server's own position
  execute at @a if block ~ ~ ~ air         0     never matches at the player's either
  setblock ~2 ~1 ~4 chest, then if block   1146  matches as soon as a command has *placed* a block there
```

A block predicate reads a position a command has made real, which is why it cannot guard the command that makes it
real. So the fixture places first and proves with an entity, using only forms the entity fixture had already
proven: a marker entity summoned once per block with the `^` form and an `unless entity` guard, a `say` that fires
while the marker is absent, and a `setblock ~ ~ ~` at the marker's own position every tick - idempotent, so it
cannot be skipped and cannot drift. Each of the five fires a stable two times an arm in every arm, and the harness
compares the arms' placements with each other.

The reading, `run/vanilla-blockents`, clouds on, 300 frames, arms interleaved M3/M4/M3/M4:

```text
picture, m3a against m3b:  mean 0.02, 0.45% of pixels differ at all   (the reference against itself)
picture, m3a against m4a:  mean 0.02, 0.27% of pixels differ at all
picture, m3a against m4b:  mean 0.12, 2.11% of pixels differ at all
   - the same worst pixel, 217 at (3547,43), in all three

by band:                     m3a vs m3b      m3a vs m4a      m3a vs m4b
sky   (top 12%)              0.07 (0.1%)     0.10 (0.1%)     0.27 (0.2%)
middle (40-60%)              0.04 (0.1%)     0.02 (0.0%)     0.34 (0.7%)
lower  (70-90%)              0.00 (0.0%)     0.00 (0.0%)     0.03 (0.1%)
```

**Block entities are drawn on both generations.** One Metal 4 arm reproduces the reference better than the
reference reproduces itself in every band; the other differs by 0.34 of mean channel difference in the band the
blocks occupy, which is one fifth of the difference the entity scene showed before its fixture was fixed and is
**NOT LOCALISED** - the only time-varying thing among the five is the enchanting table's book, which is a
hypothesis and would need a scene without it to separate.

### The first pack scene where this path is inside the gate, and the three things that are not the number

Every pack session before this one had a Metal 4 arm 17-49% slower than the reference. The fixture scenes made a
pack scene available with vanilla content in it - a pack that must draw mobs, a dropped item, an armour stand, an
experience orb and five block entities through its own deferred pipeline - so it was run twice, Complementary with
both fixtures, 300 frames, arms interleaved M3/M4/M3/M4:

```text
                run/pack-vanilla (refused: content drift)   run/pack-vanilla2 (exit 0)
arm  gen  ms a frame   vs m3a    own GPU ms/frame    ms a frame   vs m3a    wallP50   own GPU ms/frame
m3a  M3     18.96       -             19.03            20.19         -        20.20        20.26
m4a  M4     19.06      +0.5%          16.77            20.64       +2.2%      16.86        18.09
m3b  M3     19.43      +2.5%          19.50            20.42       +1.1%      20.39        20.49
m4b  M4     22.97     +21.1%          22.93            20.64       +2.2%      16.84        19.14
```

The repeat is the one to read, and the first thing it says is that a repeat was needed: the first session carries a
21% arm and the comparer refuses it for content drift between the arms of one generation (7-11%), which is the
pack's own variability and section 116's warning about temporal packs. In the repeat this path's two arms are
**identical to two decimals (20.64 and 20.64)** and both **2.2%** above a reference whose own arms differ by 1.1% -
inside the `<= ~3%` section 5 asks for before AUTO - and the session is accepted, exit 0.

Three details matter more than the number. This path's own GPU time is **lower** than the reference's (18.09 and
19.14 against 20.26 and 20.49 ms a frame), so the 2.2% is not GPU work and must not be written as if it were. Its
**median** frame is *shorter* than the reference's (16.86 against 20.20) while its mean is longer: a distribution
that is more skewed, not one that is uniformly slower - which is the same shape the whole performance thread has
had, the frame period being a wait on one side and work on the other. And the counters section 70 calls comparable
agree exactly (`pipelineIdentities 333` in all four arms, `blits 2700`, `blittedMiB 50511.0` to the digit) while the
native call counts do not (24213 pipeline sets against 12670, six clear encoders a frame against one), which is the
first pack session where that rule could be applied to a scene with vanilla content in it.

**What this does not say** is that this path is within 3% of the reference, and the difference between the
configurations is now the question: the no-pack frame at 400 frames a second read +11-17%, the pack staircase's
45-frame-a-second scenes read +17-49%, and this one +2.2% with less GPU work. One configuration, one repeat, and
section 123 is not met on it.

### Eighteen repeats: what the reference repeats to, and what this path repeats to

The performance question has been "which configurations differ" since the pack parity session, and the honest way
to ask it is about *repeatability* rather than about any one number. Every recorded session whose arms of one
generation were the same configuration - a repeat, as opposed to a session whose arms differ by a switch - was read
off disk: 29 generation-sessions.

```text
Metal 3, 11 sessions   1.00x  perf-ab6, nopack-ab1, vanilla-mobs3, vanilla-blockents
                       1.01x  pack-vanilla2, vanilla-clouds           1.02x  pack-vanilla, m4-ab7, perf-ab4
                       1.10x  perf-ab5                               1.32x  vanilla-overworld (the rain-and-
                                                                             particles scene, whose content moves too)
Metal 4, 18 sessions   1.00x  pack-vanilla2, m4-content, m4-passtimes, nopack-ab1, vanilla-blockents
                       1.01x  vanilla-mobs3    1.03x  vanilla-clouds  1.11x  m4-rings2
                       1.15x  m4-ab7, vanilla-overworld              1.18x  m4-loadtrace    1.19x  perf-ab5
                       1.21x  pack-vanilla     1.23x  m4-gputrace    1.34x  m4-stats
                       1.42x  perf-ab4         1.50x  perf-ab6       1.51x  m4-four
```

The reference repeats to **1.00-1.10x** (its one wide session is the rain-and-particles scene, whose *content*
moves between launches as well) and this path repeats to **1.00-1.51x** - and this path can repeat exactly, in six
of its eighteen sessions. That is blocker 16 in its sharpest form: a comparison whose two arms can differ by half
gives a range, and the range is wider than the effect section 5 asks about.

And the wide sessions are not the busy-machine ones, which the load instrument has now been able to test across
enough sessions to say: `perf-ab6`'s arms began at 4.3 and 4.3 and differ by 1.50x; `m4-stats`' slow arm's load
*fell* over its run; `m4-gputrace`'s fastest arm's load *rose* over its. The one session where the load did name
the arm is `m4-four`, whose 27.50 ms arm began at 6.3 while the other three began at 2.5-3.5. So the machine is
one of the ways an arm is spoiled and not the only one, which is exactly why the comparer now *names* the arm
instead of arguing about it.

**What is left is one question**: what makes this path's arms differ by up to half while the reference's agree.
Eighteen repeats say it is not the configuration, not the scene, not the load samples, and not the frame's own
GPU work (which is *lower* on this path in the pack parity session). It is the single item standing between this
report and section 123's performance line.

## Risks

- **Sixteen sampler slots are the compiler's ceiling, not the table's, and the argument buffer is the
  answer the engine already has.** Asked on the M5 Pro, four ways, and answered:
  seventeen direct samplers are **refused** - `'sampler' attribute parameter is out of bounds: must be
  between 0 and 15`; a sampler or a texture named by a resource id on a function argument is **refused** -
  `'id' attribute only applies to non-static data members`; and a table asking for **twenty sampler slots
  is accepted**, so the header's "maximum value is 16" is a statement about the documented range rather
  than a limit the runtime enforces. So the ceiling belongs to MSL, the engine's argument-buffer path is
  what carries a program with more sampled images than slots, and under Metal 4 that path is **a buffer
  bound by address** - which is the shape already proven above. **This risk is now realised rather than
  predicted**: photon's `deferred4` is nineteen sampled images, and the wide path above is the answer it
  got. What is left for those programs is generality - one pack's worth of evidence - and residency.
- **The wide path has one real-device reading.** `deferred4` is the only wide pipeline in the ladder, so the
  plan's slot arithmetic, the up-front `ensureArgumentBuffers` order and the per-artifact buffer lifetime have
  been exercised once. `wide-resources-contract` (thirty-three sampled images, one pipeline) is the fixture
  that would exercise them harder and has not been run on this path.
- **Residency.** Every texture in the engine is created with `hazardTrackingMode` untracked; Metal 4 asks
  for residency sets and the present has so far worked without one. Whether a pack's frame needs a set is
  a measurement, not an assumption.
- **Pipelines.** `newRenderPipelineStateWithDescriptor:` is Metal 3's factory and its objects draw on
  Metal 4 encoders (proven), but `MTL4Compiler` also makes `MTL4RenderPipeline` objects for background
  compilation, which is where the low-frame work wants to go. **Half of this is now realised**: the MetalFX
  milestone needed a compiler object, so `MTL4Compiler` exists and is proven on the device - but it is used for
  one factory and not for the frame's own pipelines, which are still made through the device's Metal 3 factory.
  Moving them is a separate question with a binary-archive and startup answer, and section 100 keeps it out of
  the steady-state work.
- **Machine state.** A migration this wide cannot be judged scene by scene: it needs the deterministic
  fixture the companion repository's smoke scenes provide, and the same-configuration floor taken in the
  same session, or the picture verdicts will be the sun moving.

### The counter road, read by three instruments at once, and the correction that follows

Blocker 15 was closed a round ago on the finding that the three defects behind the timestamp smoke's inversions
were all in the smoke: a duplicated heap index that made the middle boundary hold "the end of everything", two
sampling forms mixed in one curve, and a first step that was both the command buffer's first encoder and its
only clearing pass. With those gone the curve read `6105 18382 54246 171134` and the verdict written was "the
road attributes a pass". **That verdict is now withdrawn, and the instrument that withdraws it is the one the
smoke never had: a second and a third reading of the same submission.**

The smoke already committed its command buffer; it now commits it through `commit:count:options:` with a
feedback handler, so the driver's own account of the same command buffer is read beside the markers -
`MTL4CommitFeedback.GPUStartTime/GPUEndTime`, the road the frame path already reads as `gpuM4P50`. And it times
the CPU's wait for the queue's completion value, which needs no API to be trusted: the event cannot be signalled
before the command buffer has finished. A third reading was needed before any of this meant anything - **the
fixed cost of a commit**, measured by committing one trivial one-draw pass on its own, with the same two
instruments, in the same call. All three are reported: `commitDriverMs`, `cpuWaitMs`, `fixedCommitMs`,
`fixedWaitMs`, and `markerOverDriver`, the marker span as a fraction of the driver's window.

Each workload's presence is proven before its timing is judged, and the two are read back **separately** - the
curve's attachment is one texture and the area pair's is another, so one pixel cannot stand for both: the reading
carries `curveLanded` and `areaLanded` beside the conjunction `drawsLanded`, because "the road does not respond to
area" and "the area target received no draws" would otherwise be the same measurement. Ten probes, one census,
`run/m4-counters/probes.txt` (`--cold-runs 4 --warm-runs 4`), every one `gpuTime=true`:

```text
probe  marker span   driver window   CPU wait   fixed cost   marker/driver   encoder form   curve ordered
1        331.5 us      15.214 ms     15.501 ms    0.075 ms       0.0218          0.95          NO
2        412.8 us      21.442 ms     21.722 ms    0.078 ms       0.0193          0.96          yes
3        472.2 us      20.425 ms     21.021 ms    0.032 ms       0.0231          0.93          yes
4        431.5 us      18.788 ms     19.351 ms    0.075 ms       0.0230          0.96          yes
5        381.2 us      16.760 ms     17.298 ms    5.816 ms       0.0227          0.95          yes
6        432.8 us      18.208 ms     19.719 ms    0.030 ms       0.0238          0.94          yes
warm     483.7 us      20.985 ms     21.744 ms    5.760 ms       0.0231          0.82          yes
warm     268.5 us      12.030 ms     12.588 ms    0.019 ms       0.0223          0.92          yes
warm     386.9 us      17.594 ms     17.826 ms    0.030 ms       0.0220          0.94          yes
warm     310.1 us      13.727 ms     14.272 ms    0.022 ms       0.0226          0.94          yes
```

Every workload in every probe is the same: 5,440 fullscreen draws on a 1024x1024 attachment plus 1,281 on a
4096x4096 one, in one command buffer. Three facts come out of that table and each of them is a refutation:

1. **The markers account for about a forty-third of the submission.** `markerOverDriver` is 0.0193-0.0238 in
   every one of the eighteen probes recorded in the two censuses on disk, while the driver's window moves from
   12.0 ms to 21.4 ms in the table above and to **1198 ms** in `run/m4-counters/probes-loaded.txt` - a census
   taken while the machine was saturated, whose fixed cost rose to 7-9 ms with it. The ratio does not move. A road whose intervals are
   the work would read near one; a road reading the *front end* - command processing, about sixty nanoseconds a
   draw - reads a constant fraction of it, which is what this is.
2. **The fixed cost is not the explanation.** A one-draw submission reads 0.018-0.081 ms of driver window and
   1.59-2.54 ms of CPU wait, so a per-commit cost of a few milliseconds at most cannot account for 18-21 ms of
   window on the work submission.
3. **The CPU's own wait agrees with the driver and not with the markers**: 18.8-20.9 ms against 0.43-0.45 ms of
   markers on the same eight probes.

Two further readings close the mechanisms that could have explained it away. **Both sampling forms behave
identically**: the smoke now writes, at the same boundary as each command-buffer marker, the render encoder's
`writeTimestampWithGranularity:afterStage:intoHeap:atIndex:` with `MTL4RenderStageFragment` and
`MTL4TimestampGranularityPrecise` - the form section 90's first attempt used and the confirmation section 89
asks for - and the ratio of the two is 0.82-0.96 for the whole span and **1.00-1.02 on the single heaviest
pass**. So this is not a granularity, a stage, or an encoder-boundary question: both roads sample the same
place, and it is not where the work ends. **And the area knob, put back, is not a knob at all**: 256 draws on a
4096x4096 attachment read 17,583-309,235 ticks while 1024 draws on the *same* attachment read 49-67 - four
times the work reading four thousand times less.

The single-step orderings are now reported rather than asserted (`curveOrdered`, `lightPairOrdered`,
`heavyPairOrdered`), because they invert: 64 draws read 40,667 ticks against 256 draws' 13,397 in one probe, and
256 read 65,183 against 1024's 277 in another. What the smoke still *requires* is the aggregate the road does
answer - the heaviest step reads longer than the lightest, true in all eight probes - and the census exits 0 on
that. Seven new contract pins hold the new instruments and each is mutation-proved: removing the options commit,
the fixed-cost control, the `markerOverDriver` field, the encoder's precise form, the area knob, the
`curveOrdered` field, or the aggregate requirement each turns `ci-metal4-cold-probe.py` red, and the source is
restored identically after each.

**What this corrects, and it is more than one sentence.** The frame path's pass table - `378 us` of a `19.4 ms`
window in `run/m4-passtimes`, and `421`/`436 us` in the runs beside it - is **withdrawn as the frame's own work**:
it is a front end, and a submission whose driver window is 18-21 ms with a 0.45 ms marker span is not a frame
that does no work. Section 92's three kinds of timing therefore stand differently than the report last wrote
them: CPU encode timing is measured, whole-command-buffer driver timing is measured **and is the only road that
has been shown to track the work**, and GPU counter timing at pass granularity is **NOT AVAILABLE**, which is
what blocker 15 said before it was closed and says again now. The consequence for section 95 is the one the
earlier text already drew: optimisation candidates cannot be ranked by a per-pass GPU time, so they are judged
by a whole-frame A/B and a CPU-side count.

**Three clocks, read separately and never forced to agree.** The driver's `GPUStartTime`/`GPUEndTime` is the
accelerator's own account of when a submission ran; the CPU's `waitUntilSignaledValue:` duration is the host's
wait for the queue's completion signal; and a marker interval is a timestamp the GPU wrote into a heap this path
reads. The two that agree - 9.8-20.7 ms of driver window against 10.4-20.9 ms of CPU wait, within 3% on every
probe - are two different instruments, so their agreement is a reading in its own right: the queue adds no large
amount of time outside the submission. The marker road is then treated as its own clock rather than converted
into theirs, and that is what the correction turns on: it reads a constant 2.19-2.34% of the driver's window
across a 2.7x range of that window, which is a *front-end* clock (about sixty nanoseconds a draw) and not a scaled
version of the work. Scaling it by forty-three is the one move this evidence forbids - it would attribute to a
pass a time the front end never sees. The set is larger than the ten-probe census above: **fifty probes
across eight runs**, with `markerOverDriver` between **0.0219 and 0.0234** in every one.

The one lead left is the road the earlier text named and this round did not try: the **GPU-timeline resolve**
(`MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:`), which puts the resolve in
the command stream instead of on the CPU timeline and is the only remaining candidate that could change where
the sample is taken. It is not a per-pass answer on its own, and it is now the *next* counter experiment rather
than a completed milestone.

### The GPU-timeline resolve, and the counter work stopping on a measurement

The counter road had one experiment left that could have changed the answer rather than restated it: the header
declares a second way to get a heap's values out - `MTL4CommandBuffer.resolveCounterHeap:withRange:intoBuffer:
waitFence:updateFence:` (`MTL4CommandBuffer.h:206`), which encodes a resolve *into the command stream* during the
`MTLStageBlit` stage instead of reading the heap on the CPU timeline. Section 6 allowed two outcomes: either the
resolve's timing is what the caller's readings were wrong about, or the marker positions themselves do not
attribute render work and no resolve road can change that.

**The experiment.** The counter smoke now encodes that resolve twice into the same submission, into a buffer it
declares resident and reads on the CPU *after* the submission's completion value - the header's own condition for
reading it ("If your app needs to access `bufferRange` from the CPU, signal an `MTLSharedEvent` to notify the CPU
when it's ready", `MTL4CommandBuffer.h:195`). The first resolve is mid-stream, placed after the curve's steps and
before the area pair's warm-up, so the entries the command stream had not written yet are the reading that says
whether the resolve is a snapshot at its own position or a dump of the whole heap. The second is at the end, over
every entry, and is compared **stamp for stamp** with the same heap's CPU resolve. The entry size is asked rather
than assumed (`sizeOfCounterHeapEntry:`), and the selector's two by-value structs - `NSRange` and
`MTL4BufferRange`, two `uint64_t`s each - are declared as their four integer words in ABI order, because that is
the order arm64 passes them in and a reordering would have the driver read a length where an address belongs.

**The result, ten probes (`run/m4-counters/timeline-probes.txt`, all `gpuTime=true`).**

```text
probe  entry bytes   timeline vs CPU resolve   mid-stream unwritten tail   timeline span   CPU-resolved span   span/driver
1          8                14/14                       5/9                    481.4 us          481.4 us          0.0229
2          8                14/14                       5/9                    487.3 us          487.3 us          0.0231
3          8                14/14                       5/9                    482.4 us          482.4 us          0.0230
4          8                14/14                       5/9                    500.9 us          500.9 us          0.0231
5          8                14/14                       5/9                    479.7 us          479.7 us          0.0228
6          8                14/14                       5/9                    480.9 us          480.9 us          0.0230
warm       8                14/14                       5/9                    476.9 us          476.9 us          0.0229
warm       8                14/14                       5/9                    352.9 us          352.9 us          0.0228
warm       8                14/14                       5/9                    372.5 us          372.5 us          0.0224
warm       8                14/14                       5/9                    347.9 us          347.9 us          0.0227
```

The road is real: the device advertises an **8-byte** resolved entry, and the mid-stream resolve reads **5 of the
9 entries that did not exist yet as zero** - the area pair's three command-buffer markers and its two encoder
markers - while the four encoder markers the curve had already written read values. So the command executes at its
own position and the range is honoured. And it reads **the same stamps as the CPU resolve, all fourteen, in every
one of the ten probes**, with the span equal to the decimicrosecond and the ratio to four decimals. That is the
first of section 6's two outcomes, measured: what a resolve road changes is how the values travel, not what the
driver put in them.

**The counter work stops here, and the reason is a measurement rather than a budget.** Blocker 15 is closed as an
instrumentation limit: heap creation, both resolve roads and the unit are PROVEN, the two resolve roads agree to
the byte, and markers as pass execution points are REFUTED on both. Per-pass GPU attribution is **UNAVAILABLE**,
so section 95's candidates - argument-table write dedup, residency batching, barrier narrowing, encoder reuse,
allocator sizing - are ranked by whole-frame controlled A/B, CPU and native operation counts and section 70's
structural counters, which is what every milestone of this migration has used anyway. Per section 4 this is an
INSTRUMENTATION blocker: it does not block Metal 4 correctness, lifecycle or AUTO, whose blockers are the
frame-time distribution and the intermittent capability probe.

Fifteen contract pins now hold the whole counter apparatus across its two rounds - the two marker forms, the
options commit that carries the driver's window, the completion wait, the fixed-cost control, the two workloads'
own readbacks, the area knob, the timeline selector and its ABI words, the entry size, and the three timeline
fields - and each is mutation-proved: removing any one of them turns `ci-metal4-cold-probe.py` red.

### The encoded drawable wait, priced by leaving it out

The whole-submit interval this path has called its own GPU time is `MTL4CommitFeedback.GPUStartTime/GPUEndTime`,
and the header says why it cannot be render work while the drawable wait is unseparated: `waitForDrawable:`
"schedules a wait operation on the command queue to ensure the display is no longer using a specific Metal
drawable... before executing any subsequent commands". So the one call that encodes that wait is now behind a
diagnostic switch - `-Dmetallum.metal4NoDrawableWait=true`, off by default, **not a production candidate**, read
in exactly one place, and reported once in the log of any session that sets it, because an arm has to be able to
prove which submission it measured. `ci-metal4-provider.py` holds all four of those properties as pins, each
mutation-proved.

`run/m4-drawwait` is the A/B: Complementary on the staged world, 3200x1800, 600 frames a window, 25 s of settle,
four arms in section 114's order (**normal, no-wait, normal, no-wait**), the same ring depth and the same target
in every one.

```text
arm           wallP50  wallP95  gpuM4P50  gpuM4P95   drawable wait (CPU)      ring wait (CPU)          window mean
m4-normal-a    24.98    40.66    24.26     25.56    p50 21.29, 10954 ms tot   p95 0.00,     0.50 ms     24.25
m4-nowait-a    16.59    37.31    18.44     19.30    p50  0.01,     8 ms tot   p95 16.84, 1021 ms tot     18.34
m4-normal-b    24.93    25.29    21.20     22.42    p50 18.14, 10469 ms tot   p95 0.00,     0.51 ms     21.67
m4-nowait-b    16.59    37.29    18.37     19.29    p50  0.01,     8 ms tot   p95 16.44, 1014 ms tot     18.33
```

**What it measured.** Leaving the encoded wait out moves the whole-submit interval by **2.9 to 5.9 ms** (24.26 to
18.44 and 21.20 to 18.37) and moves the CPU's own pacing from the drawable handover to the ring: 17.4-18.3 ms a
frame of `nextDrawable` becomes 0.01 ms, and the ring's slot wait appears at 1.7 ms a frame with a 16.8 ms p95.
The two no-wait arms agree to **0.4%** on the driver interval and to 0.04% on the window mean, where the two
production arms differ by **14%** - which is blocker 16's spread, and the first session in which a lever moves it.

**What it did not measure.** That the 2.9-5.9 ms is entirely the wait. The two waits are not the same quantity
(the CPU's handover wait is 17-18 ms a frame where the interval moves 3-6 ms), the pacer moved from one resource
to the other, and the presented picture changed with the switch - mean channel difference 1.38-1.40 against the
reference arm's own 0.88, and 17.7-17.8% of pixels differing by more than 2 against 6.6%. So the strong form
(driver-window delta equal to the CPU wait delta, structures unchanged) did **not** hold, and no sentence of the
form "the frame's render cost is 18.4 ms" may be written from this session.

**And the faster arm is not a candidate.** The no-wait arms are 33% faster in wall time and 24-30% faster in
driver interval, and that is precisely the trap section 19 names: the switch changes the ordering the header asks
for and the picture that comes out. It is a measurement of the submission's structure and not an optimisation,
and the production path keeps encoding the wait.

The structural counters say the two shapes do the same frame: `metal4Presents 600`, `clearEncoders 3600`,
`computeEncoders 0`, `blits 5400`, `blittedMiB 101022.1` and `pipelineIdentities 333` in all four arms, with
`renderPasses` within 4% and the content counters (`loadedMiB`, `depthAttachments`) drifting up to 16%, which is
this pack's own variability. The session's GPU trace reads the accelerator 86-100% busy throughout, with the
browser and the remote-desktop server on it as always, so the absolute rates are machine numbers and the deltas
between the arms are the measurement. No arm reports a `GPURestart`, a validation error or a drawable error, and
the comparer refused the session for content drift between arms of one configuration - which is why the numbers
above are read per arm from the logs rather than through its summary.

### The two populations, traced frame by frame, and the quantum under them

Blocker 16 asked what makes this path's arms of one configuration differ by up to half. A percentile summary
cannot answer that - it says where a window's frames landed, not whether they were one population or two - so the
frame path now writes **one line a frame** behind `-Dmetallum.metal4FrameTrace=true`:

```text
M4_FRAME frame=.. slots=.. slot=.. submission=.. wallUs=.. slotWaitUs=.. drawableWaitUs=.. encodeUs=..
         passes=.. encoders=.. tables=.. draws=..
M4_FRAME_COMMIT submission=.. commitMs=..
```

The second line comes from the ring, on Metal's own dispatch queue, one per commit; the ring commits one command
buffer at a time, so the nth feedback is the nth submission and a frame line can carry the interval of *its own*
submission instead of whichever one arrived last. `tools/metal4-pacing-analysis.py` reads both, selects each arm's
probe window by line position (the client keeps drawing for a second or two after the window closes, while the
harness photographs and stops it), and classifies the frames by what they really waited on - with a threshold,
because a ring that is never waited on still reports a few hundred nanoseconds of bookkeeping.

`run/m4-pacing` is six arms interleaved **1, 3, 1, 3, 1, 3** slots, Complementary at 3200x1800:

```text
arm        slots  wall P50   wall P95   driver P50   wait that paces the frame        corr(wall(N), drawableWait(N-1))
slots1-a     1     20.76      22.31       18.92     slot  p50 19.04 ms, 600 of 600             +0.03
slots1-b     1     23.03      24.22       21.21     slot  p50 21.29 ms, 600 of 600             -0.08
slots1-c     1     24.23      25.73       22.53     slot  p50 22.65 ms, 600 of 600             +0.18
slots3-a     3     25.24      41.04       27.67     drawable 15.0 ms a frame, 0 slot waits     +0.56
slots3-b     3     20.88      26.50       19.45     drawable 17.6 ms a frame, 0 slot waits     +0.82
slots3-c     3     24.66      32.31       21.24     drawable 18.3 ms a frame, 0 slot waits     +0.85
```

Three readings, and the third is the mechanism.

**The two depths do not differ in how much the frame waits but in what it waits for.** At depth 3 the ring's slot
wait never fires - 0 of 600 window frames above 0.5 ms, 0.2 ms in total - and the drawable acquisition takes over
at 15.0-18.3 ms a frame. At depth 1 every one of the 600 frames waits for its own previous submission, at a
median of 19.0-22.7 ms, and the drawable wait is 0.02 ms.

**And the production-depth window is two-peaked, at a spacing that is the display's.** `slots3-b`'s wall
histogram is 210 frames at 16-18 ms and 208 at 24-26; `slots3-c`'s is 138 and 261; `slots3-a`'s 52 and 185 with
99 more at 32-34. The drawable waits cluster at about 7, 15 and 23 ms - one, two and three quanta of an **~8 ms**
cadence, which is this machine's 120 Hz panel (8.33 ms). So a period lands on two or three handovers: **16.7 or
25.0 ms, a ratio of 1.50** - and 1.51x is exactly the widest same-configuration arm ratio the eighteen-session
bound measured. The mixture ratio is what a launch changes, and that is the "up to half" of blocker 16.

**The pairing confirms it rather than the shape alone.** The wait a frame pays is inside its *own* period, so the
paced pairing is the previous frame's handover against this frame's wall: `corr(wall(N), drawableWait(N-1))` is
**+0.56, +0.82, +0.85** at depth 3 against **+0.03, -0.08, +0.18** at depth 1 (where the same-frame correlation
is -0.05, -0.46, -0.39 at depth 3). One slot removes the pairing because every frame waits for its own previous
submission and the CPU cannot run ahead of the compositor; three let it, and the handover decides. At depth 1 the
window is one narrow population - `slots1-b` puts 473 of its 600 frames in a single 2 ms bucket, P95/P50 1.05.

**What this closes and what it does not.** Section 33's first form is met: the two populations come from the
drawable handover's quantum, with the pairing, the spacing and the disappearance at one slot as the evidence. What
is not met is the collapse of the across-arm *mean* - 1.17x at depth 1 against 1.21x at depth 3 in this session,
where `run/m4-rings` had read 1.05-1.06x at one slot - so the gate stays open on the mean while the mechanism is
recorded, and section 30's consequence goes into the protocol: a production-depth P50 is not a renderer cost,
because its mixture is the display's. No two-arm benchmark is repeated to chase the remainder.

Six new contract pins hold the trace (the switch, the counters it needs, the frame line's fields, the paired
submission line, the ring's depth and its per-frame slot wait) and six more hold the analyser (every field it
must read, its refusal when no arm wrote a line, and the line and ring accessors it depends on); each is
mutation-proved.

### The scaler's live-frame orientation, and the fixture that could say so

Section 124 has carried one item since the MetalFX milestone: the spatial scaler's output orientation *in a live
frame*. The probe's own `canScaleWithMetalFx` proves the scaler on a fixed image in a process with no window, and
that is not the same claim - it says nothing about the arrangement of a frame the client drew, presented and
handed to the display. What was missing was a fixture: every pattern in the tree was symmetric (a flat colour, a
gradient, two halves), and a symmetric pattern can come back flipped, cropped or channel-swapped and still look
right.

`tools/fixtures/metalfx-quadrant` is that fixture, and it is four lines of GLSL: four quadrants split at the
middle of **both** axes, four different colours **and** four different alphas - top left red at 1.0, top right
green at 0.75, bottom left blue at 0.5, bottom right yellow at 0.25. A flip on either axis, a crop or a channel
swap changes the arrangement; an alpha that did not survive is a different value in each quadrant. It is run at
`--renderscale 55`, which is what puts the scaler on the path - the input is 704x396 for a 3200x1800 target, so
the input and output resolutions differ and the 1:1 road is not what is measured.

The harness learned one thing for it: `--pack` now accepts a **directory** and stages it into `run/packsrc/`,
refusing a directory without `shaders/` in it. The alternative was a fixture built by hand outside version
control, and a fixture nobody can read against the picture it produced is a fixture nobody can dispute. Four
pins hold the staging (the directory road, the `shaders/` refusal, the destination outside the instance's
`shaderpacks/`, and staging from the pack's own root so the archive has no extra level) and each is
mutation-proved.

**The reading**, `run/m4-metalfx-live`, both generations, 600-frame windows, `-Dmetallum.drawableReadback=true`
so the presented drawable is read through the *same* code on both arms - five by five samples, top row first,
ARGB:

```text
arm   drawable readback, 5x5, top row first (ARGB hex)                                     mean BGRA
m3    ff430000 ff8b0000 ff8b1b00 ff008b00 ff004300   ff8b0000 ffda0000 ffcb2800 ff00db00   49, 100, 99, 255
      ff008b00   ff940012 ffd9001a ffa01940 ff27f400 ff1ba600   ff00008c ff0000db ff2828cb
      ffdcdc00 ff8c8c00   ff000043 ff00008b ff1b1b8b ff8c8c00 ff434300
m4    byte-identical to m3, all twenty-five samples                                        49, 100, 99, 255
```

**Orientation is PROVEN with the scaler in the loop**: the corners are `ffRR0000` red top left, `ff00GG00` green
top right, `ff0000BB` blue bottom left and `ffRRGG00` yellow bottom right - the fixture's arrangement, in the
fixture's corners - and the two arms are identical sample for sample (the harness's picture comparison agrees:
mean channel difference 0.02, 0.03% of pixels differ at all). **Channel order is PROVEN** by the same table, and
**no crop** is present: four quadrants of a 704x396 input reach the corners of a 3200x1800 drawable.

**The alpha is not the fixture's, on either arm**: all twenty-five samples read `ff` where the fixture wrote 1.0,
0.75, 0.5 and 0.25. The two generations agree, so this is the present/layer road and not a Metal 4 fault in this
configuration - recorded, not explained, and it narrows the older alpha residual (which was measured on a
different fixture and scene) rather than closing it. **A smooth brightness modulation is present too** - the
corners read about 0.26 of the written colour and the interior about 0.85, with the whole-frame mean at 0.78 of
the four quadrants' mean - and it is identical in both arms, which is why both arms were read. Mechanism NOT
LOCALISED; not a generation difference.

**Section 40's configuration transitions were already measured and are now recorded**: `run/m4-lifecycle` holds
the Metal 4 path making a scaler for **1408x792 to 2560x1440** and, in the same session, one for **1760x990 to
3200x1800** with `2 in the cache` - so the configuration identity separated the change and a second scaler was
built instead of an old-size one being reused, and no third configuration was ever made, because a cache *hit*
makes no scaler and logs nothing. That is why the line reports the cache size: it is the field that turns "no
line" into "a hit". The lookup is by the whole configuration record and creation is behind the miss, and both
are pinned in `ci-metalfx.py` along with the fixture's own asymmetry - four distinct colours, four distinct
alphas, both axes split - so a later edit that made the pattern symmetric turns the contract red instead of
quietly measuring nothing.

### Section 93's ladder: the first rung is refused by its own guards, and what it found instead

With the timing model written down, the ladder restarts at its first rung - the game's own renderer with no pack
staged - under the protocol the pacing work produced: one world, one camera, a pinned target, six arms
interleaved **M3, M4, M3, M4, M3, M4**, 600-frame windows and 25 s of settle.

```text
arm   wall P50   wall P95   wall P99   wallMax   own GPU interval   drawable wait p50   loadedMiB
m3a     8.33       8.58       8.71      8.89      gpuP50 7.68          7.72 ms            28498.5
m3b     8.33       8.58       8.73     15.01      gpuP50 7.42          7.20 ms            28498.5
m3c     8.34       8.59       8.77      9.57      gpuP50 7.30          7.13 ms            28498.5
m4a    12.57      15.94      16.11     21.25      gpuM4P50 2.71       11.28 ms           120267.3
m4b     9.85      15.92      16.05     21.07      gpuM4P50 2.74        8.75 ms           142767.3
m4c     7.82      15.77      15.94     16.05      gpuM4P50 2.56        6.98 ms           160206.6
```

Two readings came out of it and neither is a performance number.

**The reference repeats to 0.01% and this path does not.** Metal 3's three arms read 8.33, 8.33 and 8.34 ms at
the median with `loadedMiB`, `storedMiB`, `depthAttachments` and `pipelineIdentities` identical to the byte in
all three; this path's three arms read 12.57, 9.85 and 7.82 (1.61x) and their content counters drift
monotonically - `loadedMiB` +18.7% then +33.2%, `storedMiB` +9.4% then +16.7%, `depthAttachments` +9.0% then
+16.5% against the first arm. The world is re-staged from the same copy for every arm, so this is a property of
the frame this path builds and not of the scene. **NOT LOCALISED**; the leading candidate, recorded as a
HYPOTHESIS, is the window's phase relative to the client's world streaming - with no pack the frame the harness
waits for arrives at a different point in the load - and it needs its own experiment.

**And the distribution is the second confirmation of the pacing mechanism.** Metal 3 sits at 8.33 ms in every
arm - one quantum of this 120 Hz panel - with its own GPU time (7.3-7.7 ms) just under it, which is a frame that
presents once a refresh. This path's **P95 is 15.77-15.94 ms in all three arms (1.1% apart)**, the *second*
quantum, while its P50 moves from 7.82 to 12.57 with the mixture ratio the launch landed in. So the protocol's
distribution-aware reading is the one this scene needs, and it is now measured on a second scene independently
of `run/m4-pacing`.

**The rung is refused rather than reported.** The comparison names both faults itself - "scene drift: metal4:
loadedMiB of m4c is +33.2% against m4a" and "arm outlier: m4a read 12.49 ms a frame against the fastest arm of
its own generation's 7.79 (1.60x), so the machine moved under it - section 115 says to discard this arm" - and
the picture comparison agrees, `m3a` against `m4c` differing in 21.46% of pixels by more than 8 where `m3a`
against `m4a` differs in 0.09%. Per section 42 the ladder **stops at this rung**: no MakeUp, no Complementary
and no Photon until the no-pack rung can be taken without an arm whose content moved. Per section 67 the
verdict recorded for it is **NOT MEASURED**, and the new blocker above is what stands between it and a number.

### Depth bias: the fields were carried and never sent

Section 58 asked whether this generation actually executes a pipeline's depth bias, and warned that the artifact
might hold `depthBiasConstant` and `depthBiasScaleFactor` while no encoder call exists. It did. The Metal 3 pass
calls `enc.setDepthBias(constant, slopeScaleFactor, 0.0f)` right after the depth-stencil state
(`MetalRenderPass`); the Metal 4 pass set the same depth-stencil state and stopped there, so every pipeline that
asks for a bias - a decal, a shadow-map offset, anything drawn a hair in front of its surface - drew unbiased on
this path and biased on the reference.

`MTL4RenderEncoder.setDepthBias:slopeScale:clamp:` is now bound from the header ({@code
MTL4RenderCommandEncoder.h:138}) with its three floats in the header's order - the same order the Metal 3 call
takes, which is why the declaration spells the arity out rather than relying on a call site to get it right - and
the pass applies it where the reference does. A window now reports `depthBias=N`, the count of pipelines whose
non-zero bias was sent, because "the fields exist" is not a reading and "the encoder was told" is: a scene that
uses one and reports zero is the defect, and a non-zero count is what says real geometry reaches the road rather
than a smoke.

**What is not done**: the offset itself is not measured. No live frame has been shown to carry a non-zero bias
yet, and section 58's fixture - two coplanar surfaces where the biased one must win, read on both generations -
is not built, so the honest verdict for the bias's *behaviour* is NOT MEASURED while the gap that made it
impossible is closed. Five contract pins hold the selector, its argument order, the encoder entry point, the call
site and the counter, and each is mutation-proved.

### The AUTO decision, gate by gate

Section 70 allows three outcomes and this is the one the gates produce, written with the evidence each line
rests on rather than as a verdict from a feeling. The table is in the report under **AUTO readiness**; what
belongs here is the reasoning and the two lines that are NOT MEASURED rather than failed.

**Correctness is the strongest it has been, and it is not complete.** The world frame, the game's own GUI and
text, terrain, depth, MRT, wide resources, the MetalFX live-frame fixture and the lifecycle transitions all pass
on this machine - the MetalFX quadrant fixture added in this round is the newest of them, and it moved section
124's last item from NOT MEASURED to PROVEN. What is left is not a fault but an absence of a reading: the
history packs have not been read this way, and the compute/storage fixture's acceptance picture needs the in-game
screenshot that macOS refuses to synthesise.

**The capability gate is the one that cannot be argued with.** The cold probe failed 21 times in 200 in one
period and zero times in 360 in another, with nothing in the path changed, so the honest statement is a
distribution and not a rate. A production AUTO that quietly promotes a path whose capability probe is
intermittent is exactly what section 15 forbids, and the retry policy the client now carries is a mitigation
rather than a proof.

**And the performance gate is unmet for a new reason.** The mechanism behind this path's arm-to-arm spread is
now measured - the frame's period lands on two or three of the display's handovers, and `run/m4-pacing` shows
the pairing at +0.56/+0.82/+0.85 against +0.03/-0.08/+0.18 at one slot - but section 93's first rung still
cannot be taken, because this path's *content* moved between the arms of one session (`loadedMiB` +18.7% then
+33.2%) where the reference's did not move at all. A comparison needs both halves: a distribution you understand
and arms that measured the same frame.

**So: AUTO stays on Metal 3 and Metal 4 stays forced and EXPERIMENTAL (section 70's C).** Forced Metal 4 remains
available and the forced Metal 3 fallback is verified, so nothing about this decision removes anything a user
already had. The three things that would move it, in the gates' own order: the content-drift experiment, the cold
probe's distribution, and a screenshot road (or a fixture channel that does not need one) for the two picture
residuals.

### The content drift, traced: it is the window's frame count against a 20 Hz tick

The no-pack rung was refused because this path's content counters drifted between arms of one session while the
reference's were identical to the byte. `run/drift-nopack` reproduced the session with the per-frame trace on -
the same six arms interleaved M3/M4 - and the trace says what the drift is.

**What this path's no-pack frame does.** The per-frame pass count is **7 in the steady state and 13 on one frame
every 49.6-50.0 ms**, and the cadence is *wall time*, not frames:

```text
arm    mean frame wall   spike spacing (frames)   spike spacing (wall)   five-pass frames
m4t1       2.48 ms              20.17                49.8 ms             134, at 225..363
m4t2       2.33 ms              21.41                49.6 ms               0
m4t3       2.57 ms              19.27                50.0 ms               7, at 593..599
```

The frame spacing moves with the frame rate and the wall spacing does not: six extra render passes land on the
frame that coincides with the client's **20 Hz game tick**. And one arm holds 134 consecutive frames at **5**
passes - two passes absent for about 340 ms - which is a second, state-shaped variation.

**Why that becomes "content drift" between arms, and how much of it each term is worth.** A 600-frame window
holds `windowWall / 50 ms` tick frames, so its total is `7*600 + 6*T - 2*S` with `T` the tick frames and `S` the
frames in a reduced stretch - and the three arms decompose exactly: `m4t1` 436*7 + 134*5 + 30*13 = 4112 against
its measured 4100, `m4t2` 572*7 + 28*13 = 4368 against 4368, `m4t3` 562*7 + 7*5 + 1*11 + 30*13 = 4370 against
4370. The tick term is therefore worth about **+4%** of a window (27.9-30.7 tick frames in this session) and the
134-frame stretch at 5 passes about **-6%**: both are of the same order, neither is the whole story, and a
least-squares fit of the two coefficients over three arms whose tick counts span 10% is ill-conditioned and
returns nonsense, so it is not fitted. **The mechanism stays NOT LOCALISED**; what is established is the
cadence (50 ms) and that Metal 3's constant frame rate is why its counters do not move at all (its three arms
read `depthAttachments` 1800 and `loadedMiB` 26836.1 / 26900.0 / 26900.0 exactly).

**The remedy is a window definition, not a Metal4 change** - but which normalisation is right is not obvious,
and one of them has already been refuted (below): content per second makes the *reference* drift. What the
decomposition above says is that a window total is `a*frames + b*ticks - c*reduced`, so the comparable
quantities are the **coefficients** and not any single normalisation of the total, and getting them needs the
probe to say how many ticks and how many reduced frames its window held. That is the next measurement task, and
it is a change to the harness and the probe rather than to the renderer.

**And one genuine scene difference survives it.** In the same session one arm's window drew 157 draws a frame
where the other two drew 326, and its draws fell from 223 to 109 across the window - a world-content difference
that normalisation does not remove and that keeps the rung's scene guard necessary after the window is fixed.

### The obvious normalisation, tried and refuted

The content drift's mechanism - a window of a fixed *frame* count against a client that does six extra passes on
every 20 Hz tick - suggests an obvious remedy: compare the content counters **per second of window** instead of
per window. It was implemented in the comparer and it is wrong.

`run/drift-nopack`, the same session that showed the tick:

```text
generation  arm   windowMs   loadedMiB total   loadedMiB a second
metal3      m3a    1112.11       26836.1            24131
metal3      m3b    1225.79       26900.0            21945   (-9.1% against m3a)
metal3      m3c    1254.51       26900.0            21443   (-11.1% against m3a)
```

The reference's three arms agree to 0.24% in their totals - which is the correct answer, because they drew the
same 600-frame window of the same scene - and the rate comparison makes them "drift" by 9-11%, because Metal 3's
own frame rate moved 13% between them (1112.1, 1225.8 and 1254.5 ms windows). The client's content is therefore
**neither per window nor per second**: it is per *frame* plus per *game tick*, and a 600-frame window of a
different frame rate contains a different number of ticks. Only a window pinned by ticks - or a reported tick
count to normalise by - makes the arms comparable, which means the probe must learn to say how many game ticks
its window covered, or the harness must close it on a tick boundary.

The change was reverted rather than shipped: a guard that flags the reference is worse than one that flags the
path, and section 63 forbids writing "probably better" over a measurement that says otherwise. The next step is
the tick count, and it is a harness and probe change rather than a Metal4 one.

### The tick count, and the no-pack rung it made measurable

The drift's decomposition said the missing fact was the window's **client ticks**: a window is a fixed frame
count and this client's frame is not the same work every frame (7 render passes in the steady state, 13 on the
frame that coincides with a 20 Hz tick), so a window's content is `a*frames + b*ticks` and two arms whose frame
rates differ cover different numbers of ticks. So the probe counts ticks: a mixin on the client's own
`Minecraft.tick()` hands each tick to `MetalFrameProbe.gameTick()`, the value at the window's first frame is kept,
and the window line reports `windowTicks` and `framesPerTick`. The mixin is registered in `metallum.mixins.json`
**and admitted by `MetallumMixinConfigPlugin`**, which `ci-contracts.py` refuses to let disagree - a mixin in the
config and not in the plugin's list is configured and never applied, silently, and that gate caught this one
before it could measure nothing.

**`run/ticks-nopack`, six arms interleaved M3/M4, no pack, is the first no-pack session of this programme whose
guards all pass** - no scene drift, no arm outlier, and the pictures inside the reference's own spread:

```text
arm   wall P50   wall P95   wall P99   wallMax   own GPU interval   drawable wait p50   ticks   frames/tick
m3a     8.33       8.87       8.97      11.79      gpuP50 7.60          7.71 ms          100       6.00
m3b     8.33       8.83       9.02      13.40      gpuP50 7.61          7.64 ms          100       6.00
m3c     8.33       8.88       9.13      11.69      gpuP50 7.60          7.66 ms          100       6.00
m4a    13.56      15.94      16.11      16.21      gpuM4P50 2.68        9.50 ms          150       4.00
m4b    14.81      15.95      16.17      16.24      gpuM4P50 2.69        9.13 ms          150       4.00
m4c    14.85      15.95      16.18      18.33      gpuM4P50 2.67        9.17 ms          150       4.00
```

The reference repeats exactly (P50 8.33 three times, `loadedMiB 28498.5` to the digit) and this path's **upper
mode is just as stable - P95 15.94, 15.95, 15.95, 0.06% apart, and its own driver interval 2.67-2.69** - while its
P50 moves 13.56 to 14.85 with the mixture. And every Metal 3 arm covered **100 ticks at 6.00 frames a tick**
against every Metal 4 arm's **150 at 4.00**: the windows sampled the same slice of the client's life, which is the
statement the previous run could not make.

**What the rung says**: on this scene this path is **1.63-1.78x slower in wall time** (13.56-14.85 against
8.33 ms) and the mechanism is the pacing rather than the work - its own commit interval is **2.67-2.69 ms against
the reference's 7.60-7.61**, and its drawable handover wait is 9.1-9.5 ms a frame against the reference's 7.7. A
frame whose own work is 2.7 ms is landing on two 8.33 ms handovers where the reference's lands on one. Per
sections 47 and 49 the two GPU columns are not subtracted; the wall column is the comparison.

**The ladder therefore advances**: rung 1 is measured, so MakeUp is next - and the same guards, the same
interleave and the same tick instrument apply to it.

### The ladder's third rung, and the second rung's artifact

Two things happened on the way up the ladder, and the smaller one is that **`MakeUp-UltraFast-9.5e` is no longer
on this machine**: the correctness ladder ran it earlier (330 pipeline identities on both arms, no fault of any
kind), and a search of the disk now finds only `ComplementaryReimagined_r5.9.1` and `photon_v1.3b`. Its
performance rung is therefore **NOT MEASURED, artifact absent** - a statement about this machine and not about the
path - and the ladder continues with the rungs whose packs exist. Recorded rather than skipped silently, because a
ladder whose missing rung is invisible is a ladder that reads as complete.

**The third rung is Complementary, six arms interleaved M3/M4/M3/M4/M3/M4, and every arm passed its window
guard** - the pack drawn, 21 render passes a frame, 5400 copy-backs, `pipelineIdentities 333` in all six, no
`GPURestart`, no validation error.

```text
arm   wall P50   wall P95   wall P99   own GPU P50   ticks   frames/tick   loadedMiB
m3a    20.65      27.19      29.17       20.91         250       2.40        316592.4
m3b    21.12      27.51      28.85       20.92         251       2.39        316812.1
m3c    18.75      21.77      24.09       18.87         224       2.68        311314.1
m4a    16.74      28.93      30.55       18.29         228       2.63        379273.5
m4b    16.75      28.75      30.54       18.14         227       2.64        364816.2
m4c    25.07      33.48      41.72       27.56         330       1.82        384632.9
```

**The tick instrument is what makes the session readable.** `m3c` covered 224 client ticks where `m3a`/`m3b`
covered 250/251, and `m4c` covered 330 where `m4a`/`m4b` covered 228/227 - and a window is a fixed frame count, so
a different tick count *is* a different frame rate. Those two arms were not measuring the same slice of the
client's life as their siblings, so per section 115 they are named and not averaged, and the comparison is between
the matched pairs: **`m3a`/`m3b` (20.65 and 21.12 ms, 2.3% apart) and `m4a`/`m4b` (16.74 and 16.75, 0.06%
apart)**.

**What the rung says**: at the median this path is **19-21% faster** on this scene (16.74/16.75 against
20.65/21.12 ms) while its own commit interval is 18.14/18.29 against the reference's 20.91/20.92 - and at **P95 it
is 5% slower** (28.75/28.93 against 27.19/27.51), which is the same mixture this report has measured twice: a
frame lands on one display handover or two, and this path's landing is less even. Structure is identical
(`blits 5400`, `pipelineIdentities 333`, 21 passes a frame) and the pictures are inside the reference's own
spread (`m3a` against `m4b` 0.55% of pixels by more than 8, against `m3c` 0.44%).

So the ladder's measured shape is a contrast: **work-light scene, this path far slower because of pacing; pack
scene, faster at the median and slower in the tail because of the same mixture** - and on both, its own commit
interval is the lower of the two, which is the one quantity sections 47 and 49 forbid subtracting. Photon is the
remaining rung whose pack exists.

### The ladder's fourth rung, and the one mechanism all three rungs name

Photon, four arms interleaved M3/M4/M3/M4, every arm passing its window guard (the pack drawn, 30-31 render
passes a frame, `blits 6000`, `pipelineIdentities 343` in all four, no fault):

```text
arm   wall P50   wall P95   wall P99   own GPU P50   ticks   frames/tick   loadedMiB
m3a     8.33       8.79       9.01       7.02          99        6.06        449644.5
m3b     8.34       8.75       8.97       7.03         100        6.00        449644.5
m4a    10.23      15.92      16.01       6.98         150        4.00        558881.5
m4b    12.52      15.83      15.96       7.02         150        4.00        551564.6
```

The reference repeats exactly (8.33/8.34 ms, `loadedMiB` 449644.5 to the digit, 99/100 ticks). This path's P50
moves 22% with the mixture and its **P95 is pinned at 15.92/15.83 (0.6%)**, with its own commit interval 6.98/7.02
(0.6%) - which **equals** the reference's 7.02/7.03. The pictures are inside the reference's own spread (`m3a`
against `m4a` 0.49% of pixels by more than 8, against `m3b` 0.62%).

**And the three measured rungs now name the mechanism's cost in one sentence**: in every one of them this path's
P95 sits at about **15.9 ms - two handovers of this 120 Hz panel** - whenever its own work fits inside one, while
the reference's period tracks its own work (8.8 ms on no-pack and on Photon, 27.2 ms on Complementary where its
work exceeds a handover and it is work-bound). Its own commit interval is lower than the reference's on no-pack
(2.67-2.69 against 7.60-7.61) and on Complementary (18.14-18.29 against 20.91-20.92) and *equal* on Photon
(6.98-7.02 against 7.02-7.03). So the wall-clock difference is not the work: it is **one extra display handover of
latency in the submission**, whose mixture decides the median and whose floor decides the tail.

That is the whole measured ladder - three rungs, one absent pack, one mechanism - and it is what the §69 table in
the report now carries.

### The depth-offset fixture, and the two traps in it

Section 58 asked for two things: make the bias actually execute, and then prove the two generations choose the
same visible surface. The first was a gap (the artifact carried `depthBiasConstant` and
`depthBiasScaleFactor` and nothing sent them); the second needed a fixture that can fail.

`MTL4Probe.canApplyDepthBias` is that fixture. One command buffer, two passes, each into its own colour and depth
target. In each pass the red triangle is drawn at 0.25 and writes its depth, and the green one at 0.75 is drawn
after it: with no bias the less-than compare rejects green and the overlap keeps red and 0.25, and with a bias
large enough to put green in front the compare accepts it and the overlap becomes green with a depth well below
0.25. Both halves run in one submission, so the reading is a comparison between a control and a test rather than a
single coloured pixel - and the census now reports `depthBias=true` for it.

**Two traps are in the smoke because both were hit while building it.** The bias is *encoder state* and applies to
the draws that follow it, so it is sent **zero before the first draw and the requested value before the second**;
the first version sent it once before both draws, which biased the control draw too, put both triangles on the
same clamped depth, had the compare reject the second and read the first triangle's colour - a failure that looks
exactly like the API doing nothing. And the constant has to be large *against the depth format's resolution*:
Metal multiplies a constant bias by that resolution, which is about 1.2e-7 for `Depth32Float`, so the ten million
the smoke uses is worth more than one in normalised depth where a `-0.6` would move the depth by less than the
format can hold. Both properties are contract-pinned and mutation-proved, along with the smoke, the census's ask
and the census's field.

**What the fixture does not say.** No measured scene has a pipeline that asks for a bias - `depthBias=0` in every
window of every session so far - so cross-generation parity on a *biased* frame is vacuous today: the reading that
exists is that the call has an effect on this device, and the instrument is what stands ready if a pack asks for
one.

### The two picture residuals, read through the road that already existed

The AUTO gate's `history` and `compute/storage` lines had been NOT MEASURED for a reason that was never about the
path: the fixtures' acceptance colours needed the game's own screenshot, and macOS refuses to synthesise that key
event on this machine. But the engine already carries a picture road that needs no keyboard - the drawable
readback, `-Dmetallum.drawableReadback=true`, which copies the presented drawable into a shared buffer and reads
it through one shared reader on both generations - and it is the road the MetalFX orientation fixture was read
with in this phase.

Both fixtures were re-run with it, on both arms, `--fixture`, 3200x1800, 300-frame windows:

```text
fixture / arm          centre sample     against the fixture's acceptance colour
compute-storage m3     ff00ff00          green (0,1,0) - PRESENT
compute-storage m4     ff00ff00          identical to the Metal 3 arm, 25 of 25 samples
composite-history m3   ff00ffff          cyan (0,1,1) - PRESENT
composite-history m4   ff00ffff          identical to the Metal 3 arm, 25 of 25 samples
```

**Both acceptance colours are in the presented frame on both generations and the two arms' grids are equal sample
for sample**, and the harness's own picture comparison agrees to 0.02% of pixels. What the reading does not fix is
the alpha channel: it is `00` at the corners where the fixture writes 1.0, on both arms - the present/layer
residual this report already carries, unchanged and not a generation difference.

So two of the AUTO gate's four unmet lines are met, by a road that was already in the engine and had been used
for a different question. The remaining two are the intermittent capability probe and the performance line.
