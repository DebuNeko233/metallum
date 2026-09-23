#!/usr/bin/env python3
"""Contracts for the Metal 4 generation.

This file is the merge of the contract scripts that used to guard this subject separately, so that
the pull-request surface is one script a subject rather than one a rule. Every check below is the
check it was, at the point it was: the merge moved code between files, it did not reword any of it.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_common import ROOT, check_launcher, forbid, read, require, source_tree  # noqa: E402

# Each merged member that used to end in `if __name__ == "__main__": raise SystemExit(main())`
# appends its own status here instead, because a `raise` after the first one would skip the
# rest of the file - and the file is several contracts now.
device = read("src/main/java/com/metallum/render/MetalDevice.java")
encoder = read("src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java")
pipeline = read("src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java")
render_pass = read("src/main/java/com/metallum/render/metal3/MetalRenderPass.java")
compiler = read("src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java")
texture = read("src/main/java/com/metallum/render/shared/MetalGpuTexture.java")
formats = read("src/main/java/com/metallum/mtl/MTLPixelFormat.java")
compare = read("src/main/java/com/metallum/mtl/MTLCompareFunction.java")
mtl_device = read("src/main/java/com/metallum/mtl/MTLDevice.java")
render_encoder = read("src/main/java/com/metallum/mtl/metal3/MTLRenderCommandEncoder.java")
backend = source_tree()
all_java = source_tree("src/main/java")


# ==================== was tools/ci-contracts.py ====================


# ---------------------------------------------------------------------------
# Three more places where the code and Apple's documentation disagreed
#
# 1. A presented frame makes two submits - the frame's own commit and the surface's present-time one,
#    which commits nothing - so "the newest submitted work" is not `currentSubmitIndex - 1`. Derived
#    that way, the wait before a pipeline cache is cleared named an index no in-flight slot holds, and
#    a wait for an index that is not in flight returns at once: a pack reload could release pipeline
#    states while command buffers were still running them.
# 2. Metal's status machine has a state for finished and a state for failed, and both answer
#    `isCompleted`. Nothing read the error, so a failed command buffer was reported as a drawn frame.
# 3. A `CAMetalLayer` is created with an explicit +1 that only this code owns, and clearing the view
#    detaches rather than releases: the layer outlived every device made for it.
# ---------------------------------------------------------------------------
require("the wait names the newest commit and not the newest submit",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "private long lastCommittedSubmitIndex = -1L;",
    "lastCommittedSubmitIndex = currentSubmitIndex;",
    "awaitSubmitCompletion(lastCommittedSubmitIndex, Long.MAX_VALUE);",
))
forbid("the wait no longer derives its index from the submit counter",
       read("src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java"),
       ("currentSubmitIndex - 1L",))

require("a failed command buffer can be read", "src/main/java/com/metallum/mtl/metal3/MTLCommandBuffer.java", (
    'Msg.of("error", ADDRESS)',
    "public String errorDescription()",
))
require("the frame says when a command buffer failed",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "toClose.buffer.errorDescription()",
))

require("the layer gives its own reference back", "src/main/java/com/metallum/mtl/CAMetalLayer.java", (
    "public void close() {",
    "ObjC.release(handle);",
))
require("the device releases the layer it was given",
        "src/main/java/com/metallum/render/MetalDevice.java", ("this.metalLayer.close();",))
require("a failed device creation releases the layer",
        "src/main/java/com/metallum/render/MetalBackend.java", ("metalLayer.close();",))

# ---------------------------------------------------------------------------
# P2: a descriptor already holding a value is not set to it again
#
# The vertex and index paths compared their values from the start; the texture and uniform paths marked
# the descriptor dirty on every call, which is a GPU-facing call for a value that has not moved. The
# comparison is deliberately conservative - a buffer slice by its buffer, offset and length, a texture
# view by its texture and mip range, a sampler by identity - because a comparison that is too keen skips
# a call that was needed and the picture changes, while one that is too dull only sets a descriptor
# again. Measured on the pack in the plan, this removes almost nothing (each image is bound about once a
# pass) and it is kept for the surface P5 binds through, not for a number it produced.
# ---------------------------------------------------------------------------
require("a texture binding is compared before the descriptor is marked",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "private static boolean sameBinding(@Nullable final TextureViewAndSampler left,",
    "leftView.texture() == rightView.texture()",
    "leftView.baseMipLevel() == rightView.baseMipLevel()",
    "if (!sameBinding(samplers.put(name, requested), requested)) {",
))
require("a uniform is compared before the descriptor is marked",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "if (!sameSlice(uniforms.put(name, value), value)) {",
))
require("an absent sampler is not marked dirty again",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "if (samplers.remove(name) != null) {",
))

# ---------------------------------------------------------------------------
# P5's first step: Metal 4 is detected, not assumed
#
# Metal 4 is a parallel API surface - MTL4-prefixed types beside the ones in use - so adopting it is a
# runtime choice, and the framework's own guidance is to detect support and fall back. Two rules follow,
# and both are here because guessing either one is how this project has been burned before: the
# availability question is the device's own (`supportsFamily:` with MTLGPUFamilyMetal4, whose value is
# the SDK's 5002 at MTLDevice.h, not a version table), and reaching the new entry point is asked for with
# `respondsToSelector:` because a selector an object does not implement is an Objective-C exception that
# ends the process rather than a nil. The answer is cached, the negative one included, because a session
# cannot change its GPU.
# ---------------------------------------------------------------------------
require("Metal 4's availability is Apple's own question", "src/main/java/com/metallum/render/Metal4.java", (
    "private static final long FAMILY_METAL4 = 5002L;",
    "if (!device.supportsFamily(FAMILY_METAL4)) {",
    'private static final String QUEUE_SELECTOR = "newMTL4CommandQueue";',
    "if (!device.respondsTo(QUEUE_SELECTOR)) {",
    "if (available != null) {",
))
require("the device is the one asked", "src/main/java/com/metallum/mtl/MTLDevice.java", (
    'Msg.of("supportsFamily:", JAVA_LONG, JAVA_LONG)',
    'Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS)',
    "public boolean supportsFamily(final long family) {",
    "public boolean respondsTo(final String name) {",
))
require("it is asked once, at device creation", "src/main/java/com/metallum/render/MetalDevice.java", (
    "Metal4.available(this.metalDevice);",
))

require("Metal 4's answer is advertised, not only logged", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static boolean supportsMetal4CoreApi() {",
    "return Metal4.isAvailable();",
))
require("a capability nobody has asked about is false", "src/main/java/com/metallum/render/Metal4.java", (
    "public static boolean isAvailable() {",
    "return Boolean.TRUE.equals(available);",
))

# ---------------------------------------------------------------------------
# Every Metal 4 selector is asked for before it is sent
#
# Learned the hard way, and it cost a session: the device supports the Metal 4 family and answers to
# `newMTL4CommandQueue`, and it does **not** implement `newCommandAllocatorWithDescriptor:` even though
# this machine's SDK declares it. Sending it raised NSInvalidArgumentException and the process died with
# SIGABRT. A device implements a subset of the factory surface its header describes, so the rule the
# scaler already lived under extends to every selector of the new path - and to the buffer's own
# protocol, which is as much a subset as the device's is.
# ---------------------------------------------------------------------------
require("the Metal 4 factories are asked for before they are sent",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    'device.respondsTo("newMTL4CommandQueue")',
    'device.respondsTo("newCommandAllocator")',
    'device.respondsTo("newCommandAllocatorWithDescriptor:")',
    'device.respondsTo("newCommandBuffer")',
    'responds(buffer, "beginCommandBufferWithAllocator:")',
    'responds(buffer, "endCommandBuffer")',
    'Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS)',
    "public static boolean canMakeAndSubmit(final MTLDevice device) {",
))

require("the Metal 4 submission is proven by the queue's own signal",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    'Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG)',
    'Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG)',
    'Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG)',
    'responds(queue, "commit:count:")',
    'responds(event, "waitUntilSignaledValue:timeoutMS:")',
    "boolean ran = WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) != 0L;",
    'Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS)',
    'Msg.ofVoid("setLoadAction:", JAVA_LONG)',
    'Msg.ofVoid("setStoreAction:", JAVA_LONG)',
    'END_ENCODING.send(encoder);',
    'ObjC.clazz("MTL4RenderPassDescriptor")',
))

# ---------------------------------------------------------------------------
# A blit already open is where the next blit belongs
#
# Every copy method ended its blit encoder on the way out, so consecutive copies could never share one:
# fifteen blit encoders a frame on this pack, measured. Sharing them is worth ten encoders a frame for
# exactly the same bytes moved, and the rule is here because the shape that made it impossible is one line
# at the end of eight methods - the kind of thing a later refactor puts back without noticing.
# ---------------------------------------------------------------------------
require("a blit shares the encoder that is already open",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLBlitCommandEncoder open) {",
    "        // A blit already open is where the next blit belongs.",
))

require("a compute dispatch shares it the same way",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "if (currentEncoder instanceof MTLComputeCommandEncoder open) {",
))
require("a half-bound dispatch is still ended where it was opened",
        "src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java", (
    "boolean bound = false;",
    "if (!bound) {",
    "commandEncoder.endEncoder();",
))

# ---------------------------------------------------------------------------
# The two questions an F3 line reads, and they are two questions
#
# "Which API is running" and "which API could the device run" are different facts, and one name answering
# both is what put "Metal 4" on the F3 screen of a session encoding every frame through Metal 3's command
# buffer. So the integration surface carries both, named for which one each answers: `metalApiGeneration()`
# is the executing one - read off the telemetry the device records, never off the family probe - and
# `deviceMetalApiGeneration()` is the hardware's newest family. Apple has no API version to query, and the
# upscaler's sentence is the same one it logs. All of them are narrow strings, because the pack-facing side
# reads them by reflection and may not see a Metal type.
# ---------------------------------------------------------------------------
require("the API generation in use is named", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static String metalApiGeneration() {",
    "MetalApiGeneration executing = MetalExecutionTelemetry.executing();",
    "return executing == null ? \"\" : executing.label();",
))
require("what the device could run is a separate answer", "src/main/java/com/metallum/api/MetallumApi.java", (
    "public static String deviceMetalApiGeneration() {",
    "return Metal4.generation();",
))
require("the generation is a family answer, not a version table",
        "src/main/java/com/metallum/render/Metal4.java", (
    "private static final long FAMILY_METAL3 = 5001L;",
    "metal3 = device.supportsFamily(FAMILY_METAL3);",
    'return "Metal 4";',
    'return metal3 ? "Metal 3" : "Metal";',
))
# And the executing fact may not be sourced from the hardware probe again: this is the regression, stated as
# a rule, because the two readings differ on exactly the machine this engine is developed on.
_api_text = read("src/main/java/com/metallum/api/MetallumApi.java")
_in_use_body = _api_text.split("public static String metalApiGeneration() {", 1)[1].split("}", 1)[0]
if "Metal4.generation()" in _in_use_body:
    raise SystemExit(
        "the generation in use is answered from the device's family probe, which is a different question: "
        "that is what reported Metal 4 for a session whose every frame is Metal 3's"
    )
# ---------------------------------------------------------------------------
# The Metal 4 path presents the frame through its own queue, one commit a frame
#
# Apple's order for a Metal 4 game ("Explore Metal 4 games", WWDC25): `nextDrawable`, `waitForDrawable:`,
# encode, `commit:count:`, `signalDrawable:`, `present` - and one command buffer and one commit a frame.
# Three rules are pinned because each of them was learned here: every selector is asked for first (an
# unimplemented one is an Objective-C exception, not a nil), the present is carried out where a frame is
# *committed* rather than where the surface asks (the picture is only the frame's once that commit has
# happened, and a present encoded before it samples a frame that frame has not drawn), and every release
# goes through the guard, because the first version threw a NullPointerException out of its own cleanup and
# took the whole Metal device down with it.
# ---------------------------------------------------------------------------
require("the Metal 4 present is guarded, ordered and carried at the frame boundary",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    "public static boolean start(final MTLDevice device) {",
    'device.respondsTo("newMTL4CommandQueue")',
    'device.respondsTo("newSharedEvent")',
    "public static boolean presenting(final CAMetalLayer layer, final MemorySegment picture) {",
    "public static void presentFrame() {",
    "WAIT_DRAWABLE.send(queue, drawable.handle());",
    "SIGNAL_DRAWABLE.send(queue, drawable.handle());",
    "awaited[slot] = ++signalled;",
    "private static void releaseIfPresent(final @Nullable MemorySegment object) {",
    'System.getProperty("metallum.metal4Frame", "true")',
))
require("the present is carried where a frame is committed",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "presentGate.afterCommit();",
))

# The two binding shapes a Metal 4 encoder needs, proven at device creation against the engine's own
# pipelines and a pixel read back: a uniform by GPU address, and a vertex buffer by address and stride.
# Without the second one the terrain and entity draws have no way to reach an encoder of the new kind,
# and without the readback a table that was accepted would read the same as a table that was used.
# ---------------------------------------------------------------------------
# Which generation executes, said once, and the feedback a Metal 4 commit is timed by
#
# A run whose log does not name the generation that produced it cannot be compared with another; and a
# Metal 4 queue returns nothing to its caller, so a submission's GPU time exists only in the commit
# feedback - without it, moving work to the new queue makes the frame probe read *faster*.
# ---------------------------------------------------------------------------
require("the selected and executing generations are recorded as two facts and said in one line",
        "src/main/java/com/metallum/render/MetalExecutionTelemetry.java", (
    '"Metal execution: {} selected, {} executes ({})"',
    "public static void record(final MetalApiGeneration selected, final MetalApiGeneration executing,",
    "public static MetalApiGeneration executing() {",
    "public static MetalApiGeneration selected() {",
    "public static String executingToken() {",
))
# One field for two facts is the fault, stated as a rule: the selector decides and cannot know what executes,
# so the record is written where both are known, and it is the device that holds the executing generation.
_selector_text = read("src/main/java/com/metallum/render/execution/MetalExecutionSelector.java")
forbid("the selector does not write the session's record", _selector_text, (
    "MetalExecutionTelemetry.selected(",
    "MetalExecutionTelemetry.record(",
))
require("the device records both, where both are known",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "MetalExecutionTelemetry.record(decision.selected(), this.services.executing(), decision.reason());",
))
require("the generations are the two API surfaces and nothing else",
        "src/main/java/com/metallum/render/execution/MetalApiGeneration.java", (
    'METAL3("metal3", "Metal 3")',
    'METAL4("metal4", "Metal 4")',
))
# The selector's rules, and the one input it may not use. A chip name is not a capability: Apple Silicon
# reports the same families across its generations, so a decision keyed off "M4" or "M5" would be a table of
# hardware rather than a question about the device - and it would be wrong on the first chip it had not seen.
# ---------------------------------------------------------------------------
# The shader profile is chosen with the generation, and the two halves of it agree
#
# A session whose translator emits MSL 4.0 while Metal is told to accept 3.2 has pipelines that do not
# compile, or worse, compile into something neither side intended; and a Metal 3 session that emits 4.0
# works on the systems this engine is developed on and fails on the older one the path exists for. So the
# profile is one record with both numbers, it is probed rather than assumed, and it is named in the cache
# identity rather than only implied by the text.
# ---------------------------------------------------------------------------
require("the MSL profile pairs the translator's version with the compiler's",
        "src/main/java/com/metallum/render/execution/MetalShaderLanguageProfile.java", (
    "public record MetalShaderLanguageProfile(int spirvCrossMslVersion, long metalLanguageVersion, String token) {",
    'MSL_3_2 =\n            new MetalShaderLanguageProfile(0x030200, (3L << 16) + 2L, "msl3.2")',
    'MSL_4_0 =\n            new MetalShaderLanguageProfile(0x040000, (4L << 16) + 0L, "msl4.0")',
    "public static final List<MetalShaderLanguageProfile> METAL3_LADDER =",
    "public static void select(final MetalShaderLanguageProfile profile, final String why) {",
))
require("the Metal 3 profile is probed by compiling, newest first",
        "src/main/java/com/metallum/render/execution/MetalShaderLanguageProbe.java", (
    "public static MetalShaderLanguageProfile newestMetal3Profile(final MTLDevice device) {",
    "for (MetalShaderLanguageProfile candidate : MetalShaderLanguageProfile.METAL3_LADDER) {",
    "options.setLanguageVersion(profile.metalLanguageVersion());",
    "NEW_LIBRARY_WITH_SOURCE.sendPtr(device.handle(), source, options.handle(), errorOut)",
))
require("both translators read the session's profile",
        "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the compute translator reads the same one",
        "src/main/java/com/metallum/render/shared/MetalComputeTranslator.java", (
    "MetalShaderLanguageProfile.selected().spirvCrossMslVersion()",
))
require("the library is compiled for the profile the translator emitted",
        "src/main/java/com/metallum/mtl/MTLDevice.java", (
    "options.setLanguageVersion(",
    "MetalShaderLanguageProfile.selected().metalLanguageVersion()",
))
require("a compiled function's identity names the profile",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "new MslFunctionKey(msl, entryPoint,",
    "private record MslFunctionKey(String msl, String entryPoint, String profile) {",
    "MetalShaderLanguageProfile.selected().token()",
))
require("the selection is made from capability and nothing else",
        "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java", (
    "public static Decision decide(final MetalExecutionPreference preference,",
    '"metallum.execution=metal4 was asked for, and this device does not satisfy the "',
    "throw new UnsatisfiedPreferenceException(",
    "capabilities.metalFxParityForMetal4()",
    # The selector decides; the record of what executes is written where both facts are known. A selector
    # that writes it is a selector that can only write the selection - which is the fault this pins.
    "return decide(preference, capabilities);",
))
selector_source = (ROOT / "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java"
                   ).read_text(encoding="utf-8")
# --- and the optional capability is not a clause of the core contract ---------------------------------------
# The Metal 4 scaler used to be one: `usable` ended `&& capabilities.metalFxParityForMetal4()`, so a device whose
# Metal 4 core answered yes on every clause was refused the generation outright when its scaler was missing -
# an optional effect deciding whether the frame path existed. The render-scale setting has a road of its own for
# a device without the scaler, so the clause is answered and logged and no longer decides. What this pair of
# pins holds is both halves: the scalar removal from `usable`, and the fact that the answer is still taken.
if "&& capabilities.metalFxParityForMetal4();" in selector_source:
    raise SystemExit(
        "the Metal 4 core contract includes the Metal 4 scaler again, so a device that answers yes on every "
        "clause of the frame path would be handed the older generation by an optional effect - and the render "
        "scale has its own road for a device without the scaler"
    )
if "&& capabilities.metal4ArgumentTable();" not in selector_source:
    raise SystemExit(
        "the core contract no longer ends at the argument table, so the clause list has changed shape and what "
        "else is in it is not pinned"
    )
if "capabilities.metalFxParityForMetal4()" not in selector_source:
    raise SystemExit(
        "the Metal 4 scaler's parity is no longer read at all, so a session that has to take the render scale's "
        "fallback road would say nothing about why"
    )

for forbidden in ("deviceName", "system().deviceName", 'contains("M1")', 'contains("M4")'):
    if forbidden in selector_source:
        raise SystemExit(
            f"the selector reads {forbidden!r}, and a device name is not a capability: the choice has to come "
            "from the family, the selectors and the probes"
        )
require("the capability record asks every clause of the minimum contract",
        "src/main/java/com/metallum/render/execution/MetalDeviceCapabilities.java", (
    "public boolean metal4MinimumContract() {",
    "public boolean metal3MinimumContract() {",
    "public boolean metalFxParityForMetal4() {",
    "device.supportsFamily(FAMILY_METAL4)",
    "device.respondsTo(\"newMTL4CommandQueue\")",
    # The Metal 4 scaler's clause is the Metal 4 path's own question, and a functional one: the class
    # question plus a scaler actually made with a compiler and released. It is not Metal 3's answer and not
    # Metal 3's object - section 80 - and the record asks it because the answer is what a Metal 4 session
    # says about the render-scale setting: with it no, the setting still works and takes the pack host's
    # fallback road below 100 per cent, and the generation is not refused on its account.
    'Metal4Fx.supported(device.handle())',
))
# The device used to make its own Metal 3 queue, and that one line is what made "the device belongs to
# shared" impossible to write down. The queue now comes through the execution services, whose first consumer
# this is; the handle crosses as an address rather than as a wrapper class, so a version-neutral interface
# never names a generation's type.
# M2: a translated module belongs to one MSL profile. The function cache always named the profile; the module
# cache did not, which made the reuse of a Metal 3 module by a Metal 4 session a thing that merely did not
# happen rather than a thing that could not. Both halves are pinned, because a key that forgot the profile again
# would compile cleanly and pass every other test in this file.
# M2: no compilation artifact may be reused across MSL profiles. The module and function caches name the profile
# in their keys; the pipeline cache cannot (its key is the game's pipeline identity, deliberately), so it is
# guarded on every hit instead. Pinned because the guard is one comparison that no other test would notice losing.
# M3 step B/C: the frame's encoder is known as a contract, and that contract carries no generation type. The
# interface is pinned against the four members the device needs and against the game interface it extends, and the
# device is pinned against naming the concrete class in its field and in the accessor it hands out.
require("the frame's encoder is held as a neutral contract, not as a class",
        "src/main/java/com/metallum/render/shared/MetalFrameEncoder.java", (
    "public interface MetalFrameEncoder extends CommandEncoderBackend {",
    "void writeToBuffer(final GpuBufferSlice destination, final ByteBuffer data);",
    "void waitForSubmittedGpuWork();",
    "void queueForDestroy(final Runnable destroyAction);",
))
require("the device hands out the frame encoder as that contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "private final MetalFrameEncoder commandEncoder;",
    "public @NonNull MetalFrameEncoder createCommandEncoder() {",
))
require("a compiled pipeline is recompiled when its profile is not the session's",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private MetalCompiledRenderPipeline compiledFor(final RenderPipeline pipeline, final ShaderSource source) {",
    "held.pipelineKey().shaderProfile().equals(MetalShaderLanguageProfile.selected().token())",
    "this.compiledPipelines.remove(pipeline);",
    "this.retirement.retire(held);",
))
require("a translated shader module is keyed by its MSL profile",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private static final Pattern GLSL_ERROR_LINE",
    "private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines,",
    "String shaderProfile) {",
    "new ShaderCompilationKey(id, type, defines,",
    "MetalShaderLanguageProfile.selected().token());",
    "synchronized void clearShaderCache() {",
    "this.shaderCache.values().forEach(IntermediaryShaderModule::close);",
))
# M3 seam: what a generation's encoder may ask the device. MetalCommandEncoder read these through package
# access, which is why moving it needed widening; the contract says what it may ask instead.
require("the translator knows no generation type",
        "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java", (
    "public static TranslatedRenderPipeline translate(",
    "TranslatedRenderPipeline(",
    "MetalShaderStages.VERTEX",
    "layout.pushConstantSlot()",
    "layout.argumentBufferSlotCount()",
))
import pathlib as _p

_root = _p.Path(__file__).resolve().parent.parent
_translator = (_root / "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java").read_text(encoding="utf-8")
for _forbidden in ("Metal3CompilationContext", "MetalCompiledRenderPipeline", "MetalDevice",
                   "MetalCommandEncoder", "com.metallum.mtl.metal3", "MTLCommand"):
    if _forbidden in _translator:
        raise SystemExit(f"the translator still names {_forbidden}")

require("the Metal 3 compiler owns lookup, translation, key and artifact",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX,",
    "compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT,",
    "compilation.device().supportsArgumentBuffersTier2()",
    "MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, argumentBuffersTier2)",
    "new TranslationLayout(PUSH_CONSTANT_SLOT, ARGUMENT_BUFFER_SLOT_COUNT)",
    "new MetalCompiledRenderPipeline(",
))
require("the cache miss path asks the Metal 3 compiler",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "pipeline, p -> Metal3PipelineCompiler.compile(this, p, source));",
))
require("the translation result carries every field a pipeline needs",
        "src/main/java/com/metallum/render/shared/TranslatedRenderPipeline.java", (
    "String vertexMsl,", "String fragmentMsl,", "String vertexEntryPoint,", "String fragmentEntryPoint,",
    "List<MetalResourceBinding> resources,", "boolean usesArgumentBuffers,",
    "Set<Integer> vertexArgumentBufferSets,", "Set<Integer> fragmentArgumentBufferSets",
))
# stage masks are shared vocabulary; the two binding slots are Metal 3 layout policy and live with the compiler.
require("the stage masks are shared vocabulary",
        "src/main/java/com/metallum/render/shared/MetalShaderStages.java", (
    "public static final int VERTEX = 1;", "public static final int FRAGMENT = 2;",
    "public static final int ALL = VERTEX | FRAGMENT;",
))
_m3c = (_root / "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java").read_text(encoding="utf-8")
_art = (_root / "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java").read_text(encoding="utf-8")
for _const in ("PUSH_CONSTANT_SLOT", "ARGUMENT_BUFFER_SLOT_COUNT"):
    if _const not in _m3c:
        raise SystemExit(f"the Metal 3 layout policy {_const} is not the compiler's")
if "ARGUMENT_BUFFER_SLOT_COUNT" in _art or "PUSH_CONSTANT_BUFFER_SLOT" in _art:
    raise SystemExit("a Metal 3 binding slot is still declared on the compiled artifact")

require("an encoder answers for the state it was handed",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "Metal3ExecutionState executionState() {",
    "return this.executionState;",
))
require("the depth bridge asks the encoder, not the device",
        "src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java", (
    "Metal3ExecutionState metal3 = encoder.executionState();",
))
import pathlib as _dp
import re as _dr

_root5 = _dp.Path(__file__).resolve().parent.parent


def _code5(path):
    text = (_root5 / path).read_text(encoding="utf-8")
    text = _dr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _dr.sub(r"//[^\n]*", "", text)
    return _dr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


if "device.executionState()" in _code5("src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java"):
    raise SystemExit("the depth bridge still reaches the device for the execution state")

# One caller cannot be rerouted and is allowed by name: compute bridge compile(Object backend, ...) holds the
# device, not an encoder, so the device accessor stays until the bridge's body moves into render.metal3.
# The accessor's one caller is the flat facade now: the implementation takes the state as a parameter.
_compute = _code5("src/main/java/com/metallum/render/MetalComputeBridge.java")
if _compute.count("device.executionState()") != 1:
    raise SystemExit("the compute bridge's use of the device accessor changed shape")

require("the device holds the generation state as the shared contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "private final MetalExecutionState executionState;",
    "MetalExecutionState executionState() {",
    "this.executionState = this.services.createExecutionState(this.metalDevice);",
    "this.commandEncoder = this.services.createFrameEncoder(this, this.executionState, this.defaultShaderSource);",
    "this.executionState.clearCachesAfterGpuCompletion();",
))
import pathlib as _wp
import re as _wr

_root4 = _wp.Path(__file__).resolve().parent.parent


def _code4(path):
    text = (_root4 / path).read_text(encoding="utf-8")
    text = _wr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _wr.sub(r"//[^\n]*", "", text)
    return _wr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


_dev4 = _code4("src/main/java/com/metallum/render/MetalDevice.java")
for _forbidden in ("Metal3ExecutionState", "Metal3CompilationContext", "Metal3PipelineRetirement",
                   "MetalCompiledRenderPipeline", "new MetalCommandEncoder("):
    if _forbidden in _dev4:
        raise SystemExit(f"the device still names {_forbidden}")
for _gone in ("synchronized MetalCompiledRenderPipeline getOrCompilePipeline(",
              "synchronized MemorySegment getOrCompileFunction(", "synchronized MemorySegment depthStencilState("):
    if _gone in _dev4:
        raise SystemExit(f"a Metal 3 migration delegate is still on the device: {_gone}")

# The factory is the only public construction seam, and its signatures are neutral.
_factory = _code4("src/main/java/com/metallum/render/metal3/Metal3ExecutionFactory.java")
for _leak in ("Metal3ExecutionState createState", "MetalCommandEncoder createFrameEncoder",
              "Metal3CompilationContext create", "Metal3PipelineRetirement create"):
    if _leak in _factory:
        raise SystemExit(f"the generation factory hands out an implementation type: {_leak}")
for _needed in ("MetalExecutionState createState(final MTLDevice device)",
                "MetalFrameEncoder createFrameEncoder(final MetalDevice device,",
                "final MetalExecutionState executionState,"):
    if _needed not in _factory:
        raise SystemExit(f"the generation factory signature changed shape: {_needed}")

# The services select a generation factory; they no longer construct the frame implementation.
_services = _code4("src/main/java/com/metallum/render/execution/MetalExecutionServices.java")
if "MetalCommandEncoder" in _services:
    raise SystemExit("the execution services still name the Metal 3 frame encoder")

require("the render pass compiles through the state it was given",
        "src/main/java/com/metallum/render/metal3/MetalRenderPass.java", (
    "this.executionState = executionState;",
    "this.defaultShaderSource = defaultShaderSource;",
    "this.executionState.getOrCompilePipeline(pipeline, this.defaultShaderSource);",
))
for _bridge in ("src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java",
                "src/main/java/com/metallum/render/metal3/Metal3DepthMipmapBridge.java"):
    _src = _code4(_bridge)
    for _gone in ("device.getOrCompileFunction", "device.depthStencilState"):
        if _gone in _src:
            raise SystemExit(f"{_bridge} still reaches the device for {_gone}")

require("the frame-resource capability is generation-neutral vocabulary",
        "src/main/java/com/metallum/render/shared/MetalFrameResourceCommands.java", (
    "public interface MetalFrameResourceCommands {",
    "boolean generateMipmaps(GpuTexture texture);",
    "boolean clearStorageTexture(GpuTexture texture, int dimensions);",
    "boolean copyStorageTextureRegion(",
))
require("the flat frame bridge reaches implementations only through capabilities",
        "src/main/java/com/metallum/render/MetalFrameBridge.java", (
    "public static boolean supports(final @Nullable Object encoder) {",
    "return encoder instanceof MetalFrameResourceCommands;",
    "return encoder instanceof MetalFrameResourceCommands commands && commands.generateMipmaps(texture);",
    "commands.copyStorageTextureRegion(source, destination, sourceX, sourceY, sourceZ,",
))
import pathlib as _fp2
import re as _fr2

_root7 = _fp2.Path(__file__).resolve().parent.parent


def _code7(path):
    text = (_root7 / path).read_text(encoding="utf-8")
    text = _fr2.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _fr2.sub(r"//[^\n]*", "", text)
    return _fr2.sub(r'"(?:\\.|[^"\\])*"', '""', text)


for _facade in ("MetalFrameBridge", "MetalAttachmentBridge", "MetalComputeBridge", "MetalDepthMipmapBridge"):
    _src = _code7(f"src/main/java/com/metallum/render/{_facade}.java")
    for _forbidden in ("render.metal3", "render.metal4", "mtl.metal3", "mtl.metal4"):
        if _forbidden in _src:
            raise SystemExit(f"the flat {_facade} names {_forbidden}")

require("the Metal 3 encoder answers the resource capabilities it owns",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "MetalFrameResourceCommands, MetalFrameDepthMipmaps, MetalFrameComputeCommands {",
    "public boolean generateDepthMipmaps(final GpuTexture texture) {",
    "public boolean dispatchCompute(final Object pipeline,",
    "Metal3ComputeBridge.dispatch(this, pipeline, buffers, textures, samplers,",
))

# One compute translation, not one per generation: the bridge that dispatches keeps the encoder half and the
# shared layer keeps the SPIR-V half, so a second copy of the reflection growing back here is the fault. The
# needle is the SPIRV-Cross entry point every copy of that code has to call, and comments cannot satisfy it
# because the scan reads the source with them stripped.
_compute_bridge_source = _code7("src/main/java/com/metallum/render/metal3/Metal3ComputeBridge.java")
if "spvc_context_create" in _compute_bridge_source:
    raise SystemExit("the Metal 3 compute bridge has grown its own SPIRV-Cross reflection back")

require("the flat compute facade is neutral and forwards",
        "src/main/java/com/metallum/render/MetalComputeBridge.java", (
    "public static Object compile(final Object backend, final String label, final ByteBuffer spirv) {",
    "if (!(device.executionState() instanceof MetalComputeCompiler compiler)) {",
    "return compiler.compileCompute(device, label, spirv);",
    "return encoderBackend instanceof MetalFrameComputeCommands commands",
    "commands.dispatchCompute(pipelineResource, buffers, textures, samplers,",
    "if (pipelineResource instanceof MetalComputePipelineResource resource) {",
))
require("the flat depth-mipmap facade is neutral and forwards",
        "src/main/java/com/metallum/render/MetalDepthMipmapBridge.java", (
    "public static boolean generate(final Object encoderBackend, final GpuTexture texture) {",
    "return encoderBackend instanceof MetalFrameDepthMipmaps depth && depth.generateDepthMipmaps(texture);",
))
import pathlib as _fp
import re as _fr

_root6 = _fp.Path(__file__).resolve().parent.parent


def _code6(path):
    text = (_root6 / path).read_text(encoding="utf-8")
    text = _fr.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _fr.sub(r"//[^\n]*", "", text)
    return _fr.sub(r'"(?:\\.|[^"\\])*"', '""', text)


# The facades keep the API and nothing else: the ledger counts names, these check the files themselves, so a
# generation name that the ledger happens to allow still fails here.
for _facade, _forbidden in (
        ("src/main/java/com/metallum/render/MetalComputeBridge.java",
         ("MetalCommandEncoder", "Metal3ExecutionState", "MTLComputeCommandEncoder", "MTLCommandBuffer",
          "com.metallum.mtl.metal3")),
        ("src/main/java/com/metallum/render/MetalDepthMipmapBridge.java",
         ("MetalCommandEncoder", "Metal3ExecutionState", "MTLRenderCommandEncoder", "com.metallum.mtl.metal3")),
):
    _src = _code6(_facade)
    for _name in _forbidden:
        if _name in _src:
            raise SystemExit(f"{_facade} names {_name}; a flat facade must not know the generation")

# The cluster lives under render.metal3, and the flat paths are gone: a half-move that left a file behind would
# otherwise compile from two places at once.
for _name in ("Metal3ExecutionFactory", "Metal3ExecutionState", "Metal3CompilationContext",
              "Metal3PipelineRetirement", "Metal3PipelineCompiler", "MetalCompiledRenderPipeline",
              "MetalCommandEncoder", "MetalRenderPass"):
    if not (_root6 / f"src/main/java/com/metallum/render/metal3/{_name}.java").is_file():
        raise SystemExit(f"{_name} is not under render.metal3")
    if (_root6 / f"src/main/java/com/metallum/render/{_name}.java").is_file():
        raise SystemExit(f"{_name} still exists in the flat package as well")

require("the shared execution boundary has four operations",
        "src/main/java/com/metallum/render/shared/MetalExecutionState.java", (
    "public interface MetalExecutionState extends AutoCloseable {",
    "CompiledRenderPipeline getOrCompilePipeline(RenderPipeline pipeline, ShaderSource source);",
    "List<RenderPipeline> evictCachedPipelines(Predicate<RenderPipeline> predicate);",
    "void clearCachesAfterGpuCompletion();",
    "void close();",
))
import pathlib as _bp
import re as _re

_root3 = _bp.Path(__file__).resolve().parent.parent


def _code(path):
    """The file's code with comments and strings removed: a leak in prose is not a leak."""
    text = (_root3 / path).read_text(encoding="utf-8")
    text = _re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = _re.sub(r"//[^\n]*", "", text)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


_boundary = _code("src/main/java/com/metallum/render/shared/MetalExecutionState.java")
for _forbidden in ("Metal3", "Metal4", "MTL", "MemorySegment", "MetalCompiledRenderPipeline",
                   "Metal3CompilationContext", "Metal3PipelineRetirement", "MetalCommandEncoder",
                   "MetalRenderPass"):
    if _forbidden in _boundary:
        raise SystemExit(f"the shared execution boundary names {_forbidden} in code")

require("the Metal 3 aggregate implements the boundary without widening its internals",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java", (
    "final class Metal3ExecutionState implements MetalExecutionState, MetalComputeCompiler {",
    "public MetalCompiledRenderPipeline getOrCompilePipeline(",
    "public List<RenderPipeline> evictCachedPipelines(",
    "public void clearCachesAfterGpuCompletion() {",
    "public void close() {",
))
_state_code = _code("src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java")
for _forbidden in ("public MemorySegment getOrCompileFunction", "public MemorySegment depthStencilState",
                   "public IntermediaryShaderModule getOrCompileShader"):
    if _forbidden in _state_code:
        raise SystemExit(f"the boundary widened an implementation internal: {_forbidden}")

# The shader module delegate is dead: the compiler asks the context directly, and nothing else asks anyone.
for _path in ("src/main/java/com/metallum/render/MetalDevice.java",
              "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java"):
    if "getOrCompileShader(" in _code(_path):
        raise SystemExit(f"{_path} still carries the shader module delegate")
require("shader module lookup happens where the modules are",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "compilation.getOrCompileShader(pipeline.getVertexShader(), ShaderType.VERTEX,",
    "compilation.getOrCompileShader(pipeline.getFragmentShader(), ShaderType.FRAGMENT,",
))

require("the Metal 3 execution aggregate owns the compilation state and the retirement queue",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java", (
    "private final Metal3PipelineRetirement retirement = new Metal3PipelineRetirement();",
    "private final Metal3CompilationContext compilation;",
    "this.compilation = new Metal3CompilationContext(device, this.retirement);",
    "void clearCachesAfterGpuCompletion() {",
    "void close() {",
))
import pathlib as _pp

_root2 = _pp.Path(__file__).resolve().parent.parent
_dev2 = (_root2 / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
for _forbidden in ("Metal3CompilationContext compilation", "Metal3PipelineRetirement retirement",
                   "this.compilation", "this.retirement"):
    if _forbidden in _dev2:
        raise SystemExit(f"the device still owns {_forbidden}; it belongs to Metal3ExecutionState")

# Exactly one construction of each: the aggregate makes them, nobody else does.
_sources = "\n".join(p.read_text(encoding="utf-8")
                     for p in (_root2 / "src/main/java").rglob("*.java"))
if _sources.count("new Metal3PipelineRetirement()") != 1:
    raise SystemExit("Metal3PipelineRetirement is constructed somewhere other than the aggregate")
if _sources.count("new Metal3CompilationContext(") != 1:
    raise SystemExit("Metal3CompilationContext is constructed somewhere other than the aggregate")

require("the active pipeline cache belongs to the compilation context",
        "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java", (
    "private final Map<RenderPipeline, MetalCompiledRenderPipeline> compiledPipelines = new IdentityHashMap<>();",
    "synchronized MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {",
    "synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {",
    "synchronized void clearActivePipelines() {",
    "this.retirement.retire(entry.getValue());",
))
# The ownership is a negative fact as much as a positive one: the device must not keep the active cache, and the
# teardown order is control flow, not the presence of three lines - a frame-probe contract already showed that
# presence is not order.
import pathlib as _pathlib

_root = _pathlib.Path(__file__).resolve().parent.parent
_dev = (_root / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
_ctx = (_root / "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java").read_text(encoding="utf-8")
_ret = (_root / "src/main/java/com/metallum/render/metal3/Metal3PipelineRetirement.java").read_text(encoding="utf-8")

if "compiledPipelines = new IdentityHashMap" in _dev:
    raise SystemExit("the active pipeline cache is declared on MetalDevice as well as on the context")

_state = (_root / "src/main/java/com/metallum/render/metal3/Metal3ExecutionState.java").read_text(encoding="utf-8")
# The device waits, then hands over: the wait must come first, and the aggregate must not know how to wait.
if _dev.index("this.waitForSubmittedGpuWork();") > _dev.index("this.executionState.clearCachesAfterGpuCompletion();"):
    raise SystemExit("clearPipelineCache releases the caches before the GPU wait")

_order = (
    "this.retirement.releaseRetired();",
    "this.compilation.clearActivePipelines();",
    "this.compilation.clearShaderCache();",
    "this.compilation.clearFunctionCache();",
)
_positions = [_state.index(_line) for _line in _order]
if _positions != sorted(_positions):
    raise SystemExit(
        "the aggregate no longer releases in the order retired, active, shaders, functions: "
        + str(list(zip(_order, _positions)))
    )
for _forbidden in ("waitForSubmittedGpuWork", "MetalCommandEncoder", "MetalFrameEncoder"):
    if _forbidden in _state:
        raise SystemExit(f"the Metal 3 execution aggregate must not know about {_forbidden}")
for _forbidden in ("Metal4", "MTL4", "Metal4PresentGate", "Metal4Path"):
    if _forbidden in _state:
        raise SystemExit(f"the Metal 3 execution aggregate must not know about {_forbidden}")

for _forbidden in ("waitForSubmittedGpuWork", "MetalCommandEncoder", "MetalFrameEncoder", "MetalDevice"):
    if _forbidden in _ret:
        raise SystemExit(f"the retirement owner must not know about {_forbidden}")

require("the pipeline cache asks the artifact one question through a contract",
        "src/main/java/com/metallum/render/shared/MetalCompiledArtifact.java", (
    "public interface MetalCompiledArtifact {",
    "MetalPipelineKey pipelineKey();",
))
require("the Metal 3 artifact answers it",
        "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "implements CompiledRenderPipeline, MetalCompiledArtifact, AutoCloseable {",
    "public MetalPipelineKey pipelineKey() {",
))
require("a generation's encoder asks the device through a contract",
        "src/main/java/com/metallum/render/shared/MetalDeviceFacts.java", (
    "public interface MetalDeviceFacts {",
    "boolean useLabels();",
    "MemorySegment metalDeviceHandle();",
))
require("the execution services are a facade fact, not package access",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "public MetalExecutionServices executionServices() {",
))
require("the device answers that contract",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "public final class MetalDevice implements GpuDeviceBackend, MetalDeviceFacts {",
    "public boolean useLabels() {",
))
require("the frame's queue comes from the execution services",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    # The constants are gone: the services are built from BOTH facts - what was selected and what executes -
    # because a forced Metal 4 launch executes Metal 4 while AUTO still executes the reference path.
    "this.services = MetalExecutionServices.of(decision.selected(), executesToday);",
    "this.commandEncoder = this.services.createFrameEncoder(this, this.executionState, this.defaultShaderSource);",
    "this.presentGate = this.services.startPresentPath(this.metalDevice);",
))
# The queue itself is the Metal 3 implementation's object: the address still comes from the services, but the
# type and its teardown live where the generation does, so the facade names no command-generation type for the
# sake of one caller.
require("the frame's queue belongs to the generation that encodes the frame",
        "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java", (
    "private final com.metallum.mtl.metal3.MTLCommandQueue commandQueue;",
    "device.executionServices().commandQueue(device.metalDevice())",
    "return commandBuffer = this.commandQueue.makeCommandBuffer(",
    "this.commandQueue.close();",
))
# The only observation of the seam's own answer. It exists because the claim "the services carry the selection
# and not a constant" had nothing to read it with: `selectedGeneration` in the frame probe comes from the
# telemetry, so before this line an AUTO launch that chose Metal 4 and a forced Metal 3 launch printed the same
# thing at this seam. Pinned because a log line nobody guards is a log line somebody deletes.
require("the seam prints the generation the services themselves carry, and what the launch asked for",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    '"Metal execution seam: selectedGeneration={} executingGeneration={} requestedPreference={} mode={}'
    ' referenceShell={} framePathReady={}"',
    "this.services.selected().token(), this.services.executing().token(),",
    "decision.preference().word(),",
    "this.services.framePathReady() ? \"own-path\" : \"reference-shell\",",
    "this.services.isReferenceShell(), this.services.framePathReady());",
))
require("the generation owns the queue factory, behind a neutral signature",
        "src/main/java/com/metallum/render/metal3/Metal3ExecutionProvider.java", (
    'Msg.of("newCommandQueue"',
    "return NEW_COMMAND_QUEUE.sendPtr(device.handle()).address();",
    "public MetalExecutionState createExecutionState(final MTLDevice device) {",
))
require("the services hold a provider and name no generation",
        "src/main/java/com/metallum/render/execution/MetalExecutionServices.java", (
    "long commandQueue(MTLDevice device);",
    "private final MetalExecutionProvider provider =",
    "return this.provider.commandQueue(device);",
    "return this.provider.createExecutionState(device);",
    "return this.provider.createFrameEncoder(device, executionState, defaultShaderSource);",
))
device_source = (ROOT / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8")
if "this.metalDevice.newCommandQueue()" in device_source:
    raise SystemExit(
        "the device makes its own command queue again, which puts a generation inside the device and is what "
        "the execution-services seam exists to prevent"
    )
require("the services say what executes, not only what was chosen",
        "src/main/java/com/metallum/render/execution/MetalExecutionServices.java", (
    "MetalApiGeneration selected();",
    "MetalApiGeneration executing();",
    "boolean isReferenceShell();",
    # The pin used to require the literal, which recorded the shape rather than the design: what it is
    # about is that the services answer with what executes, so it now requires the parameter.
    "return executing;",
))
require("a launch that names no generation is Metal 3",
        "src/main/java/com/metallum/render/execution/MetalExecutionPreference.java", (
    "public static final MetalExecutionPreference DEFAULT = FORCE_METAL3;",
    "String asked = System.getProperty(PROPERTY);",
    "return DEFAULT;",
))
# The absent property is the ordinary case and must not be a capability question: reading it as AUTO is what
# put `selectedGeneration=metal4 executingGeneration=metal3 referenceShell=true` in a normal startup's log.
_preference_source = (ROOT / "src/main/java/com/metallum/render/execution/MetalExecutionPreference.java"
                      ).read_text(encoding="utf-8")
if "System.getProperty(PROPERTY, AUTO.word)" in _preference_source:
    raise SystemExit("architecture contract: an absent metallum.execution reads as AUTO again, so an ordinary "
                     "startup selects a generation it does not execute")
if "return AUTO;" in _preference_source:
    raise SystemExit("architecture contract: the preference falls back to AUTO, which is a diagnostic mode and "
                     "not what a player who never chose a generation should run")
require("the preference is one property with four words",
        "src/main/java/com/metallum/render/execution/MetalExecutionPreference.java", (
    'public static final String PROPERTY = "metallum.execution";',
    'AUTO("auto")',
    'FORCE_METAL3("metal3")',
    'PREFER_METAL4("prefer-metal4")',
    'FORCE_METAL4("metal4")',
))
# The player's word and the developer's are different words, and the difference is the whole of the safety:
# a settings row that wrote `metal4` would turn an opt-in into a startup failure on a device that cannot run
# the experimental path. The selector has to *fall back* for the preference and only for it.
_selector_words = (ROOT / "src/main/java/com/metallum/render/execution/MetalExecutionSelector.java"
                   ).read_text(encoding="utf-8")
for needle, why in (
    ("case PREFER_METAL4 -> {",
     "the selector has no branch for the player's preference, so `prefer-metal4` would fall through to another "
     "word's rules"),
    ("Metal 4 was preferred by the user but was not selected:",
     "the player's preference does not say that Metal 4 was not selected, so a session that fell back would "
     "leave a reader to work out which generation ran"),
    ("- falling back to Metal 3",
     "the fallback a player's preference takes is not named as one"),
    ('"Metal 4 was preferred and no generation can run here',
     "the preference does not fail where neither generation can run, so a device with neither would be handed "
     "a session that cannot draw"),
):
    if needle not in _selector_words:
        raise SystemExit("architecture contract: " + why)
require("the device records capabilities and selects once",
        "src/main/java/com/metallum/render/MetalDevice.java", (
    "MetalDeviceCapabilities capabilities =",
    "MetalExecutionSelector.say(capabilities);",
    # The preference is read once, before the probe, because it decides how much of the device is asked: a
    # launch that can only run Metal 3 must not pay for the Metal 4 functional probe, and a session must not be
    # probed for one generation and selected as another.
    "MetalExecutionPreference preference = MetalExecutionPreference.read();",
    "boolean probeMetal4 = preference.probesMetal4();",
    "MetalExecutionSelector.select(preference, capabilities);",
))
# And the scope itself, in both halves: nothing Metal 4 is asked where it cannot run, and `not-probed` is a
# word of its own rather than a false clause.
for needle, why in (
    ("Metal4.available(this.metalDevice);", "the Metal 4 functional probe is not run where it is needed"),
    ("if (probeMetal4) {", "the Metal 4 probe is not behind the scope, so a forced Metal 3 launch pays for it"),
    ("Metal 4 capability not probed for this session",
     "a skipped probe is not said out loud, so a reader cannot tell it from a device that answered no"),
):
    if needle not in (ROOT / "src/main/java/com/metallum/render/MetalDevice.java").read_text(encoding="utf-8"):
        raise SystemExit("architecture contract: " + why)
_capability_source = (ROOT / "src/main/java/com/metallum/render/execution/MetalDeviceCapabilities.java"
                     ).read_text(encoding="utf-8")
for needle, why in (
    ("final boolean probeMetal4) {", "the capability probe has no scope, so every launch asks everything"),
    ('+ " metal4=not-probed"', "a session that did not probe says nothing distinct about Metal 4"),
    ("return this.metal4Probed\n                && this.metal4Family",
     "the minimum contract can be claimed by a session that never asked the Metal 4 questions"),
    ("return !this.metal4Probed || !this.metalFxSpatial || this.metal4FxSpatial;",
     "the scaler parity is claimed absent for a session that never asked about the scaler"),
):
    if needle not in _capability_source:
        raise SystemExit("architecture contract: " + why)
require("a Metal 4 commit carries the options its feedback arrives through",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    'Msg.ofVoid("commit:count:options:", ADDRESS, JAVA_LONG, ADDRESS)',
    "commitOptions = MTL4CommitOptions.create();",
    "feedbackBlock = ObjCBlock.withConsumer(Metal4Path::reportCommitFeedback);",
    "double millis = MTL4CommitOptions.gpuMillis(feedback);",
    "MetalFrameProbe.gpuFrameMetal4(millis);",
    "if (commitOptions != null) {",
    "commitOptions.feedbackHandler(feedbackBlock);",
    "COMMIT_WITH_OPTIONS.send(queue, buffers, 1L, commitOptions.handle());",
))
require("the feedback object is the only place a Metal 4 submission's timing is read",
        "src/main/java/com/metallum/mtl/metal4/MTL4CommitOptions.java", (
    'Msg.ofVoid("addFeedbackHandler:", ADDRESS)',
    'Msg.of("GPUStartTime", JAVA_DOUBLE)',
    'Msg.of("GPUEndTime", JAVA_DOUBLE)',
    "return (ended - started) * 1000.0;",
))
require("a block can hand its argument to a Java method",
        "src/main/java/com/metallum/objc/ObjCBlock.java", (
    "public static MemorySegment withConsumer(final Consumer<MemorySegment> action) {",
    "private static void invokeConsumer(final Consumer<MemorySegment> action, final MemorySegment block,",
))
# The compiled pipeline's identity, introduced beside the cache and not yet used by it: the cache is keyed
# by the game's pipeline object, which answers "have I compiled this object" and not "is this the same work",
# and a cache that spans two generations needs the second question answered. The profile is part of the key
# so that a Metal 3 artifact cannot be handed to a Metal 4 session, and every compiled pipeline carries its
# own key so the step that moves the cache has something to move it to.
require("a compiled pipeline carries what it is, not only the object it was asked for",
        "src/main/java/com/metallum/render/metal3/MetalCompiledRenderPipeline.java", (
    "private final MetalPipelineKey pipelineKey;",
    "MetalPipelineKey pipelineKey() {",
    "this.pipelineKey = pipelineKey;",
))
require("the identity is read from the game's description plus the session's own two facts",
        "src/main/java/com/metallum/render/shared/MetalPipelineKey.java", (
    "pipeline.getLocation().toString()",
    "pipeline.getVertexShader().toString()",
    "pipeline.getFragmentShader().toString()",
    "pipeline.getShaderDefines().asSourceDirectives()",
    "MetalPipelineKey of(final RenderPipeline pipeline, final String shaderProfile,",
))
require("the key is built where the pipeline is compiled",
        "src/main/java/com/metallum/render/metal3/Metal3PipelineCompiler.java", (
    "MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(), translated.usesArgumentBuffers())",
    "MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout, argumentBuffersTier2)",
))
require("the Metal 4 binding shapes are proven, not assumed",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    "public static boolean canBindAndDraw(final MTLDevice device) {",
    "uniformBuffer.gpuAddress() == 0L",
    "table.address(uniformBuffer.gpuAddress(), 1L)",
    "verticesTable.address(vertexBuffer.gpuAddress(), 16L, 0L)",
    "MTLTexture.bytes(target, pixel, 4L, 0L, 0L, 1L, 1L);",
    "EXPECTED_VERTEX_PIXEL",
))
# The ceiling question that decides whether every program can move: asked of the compiler rather than
# assumed from the header, because the header's "maximum 16 sampler slots" is not what the runtime
# enforces and the compiler's own limit is what a shader has to live inside.
require("the sampler ceiling is asked of the compiler",
        "src/main/java/com/metallum/mtl/metal4/MTL4Probe.java", (
    "public static String samplerCeiling(final MTLDevice device) {",
    "seventeenSamplersMsl()",
    'device.newFunction(ID_SAMPLER_MSL, "probe_id_sampler")',
    "MTL4ArgumentTable.create(device, 0L, 0L, 20L)",
))
require("a buffer's Metal 4 address is asked for rather than assumed",
        "src/main/java/com/metallum/mtl/MTLBuffer.java", (
    'MTL4Probe.respondsTo(handle, "gpuAddress")',
))
require("the argument table is asked for by the selector its header declares",
        "src/main/java/com/metallum/mtl/metal4/MTL4ArgumentTable.java", (
    'device.respondsTo("newArgumentTableWithDescriptor:error:")',
    "NEW_TABLE_WITH_ERROR.sendPtr(device.handle(), descriptor, MemorySegment.NULL)",
    # The texture binding moved from a hard-coded slot zero to the slot the layout names, because the
    # sampled-texture smoke samples through one slot while the frame's own layouts bind more than one: the
    # pin follows the call and keeps what it was watching, which is the resource id and the header's selector.
    "public boolean texture(final MemorySegment textureHandle, final long index) {",
    "SET_TEXTURE.send(handle, RESOURCE_ID.sendLong(textureHandle), index);",
    # Asked for with one and not zero, which this contract used to pin the other way round. The header says
    # `initializeBindings` defaults to false, so a table created with the default leaves a slot this path never
    # fills holding whatever the driver left there - and this path skips a binding by design where a layout
    # declares it as the other kind of resource. The first world frame, the first frame that draws the clouds,
    # read one of those slots and killed the GPU; with the bindings initialised to nil it renders.
    "SET_INITIALIZE.send(descriptor, 1L);",
))
require("a missing table is said out loud rather than hidden",
        "src/main/java/com/metallum/render/Metal4Path.java", (
    "not carrying the present, because this device makes",
    "private static boolean refuse(final String why) {",
))

print("Metal and engine contracts: PASS")

# ==================== was tools/ci-metal4-provider.py ====================
"""Pins the Metal 4 execution provider's skeleton: what it owns, what it refuses, and how it is reached.

Phase 2 asks for a generation-specific provider and only a skeleton of one. Two things about that are easy to
undo by accident and expensive to notice:

  - the provider must stay reachable through the NEUTRAL interface, so the services can hand it out for the
    executing generation without learning a Metal 4 type. A provider that grew a Metal 4 command type in a
    signature would put a generation into the shared seam;
  - its unimplemented halves must fail by name. A provider that returned null would move the failure into
    whatever first used the state, twenty calls later, which section 35 of the migration plan forbids and
    which is exactly the distortion the capability probe was rebuilt to remove.
"""
import re

ROOT = Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ExecutionProvider.java"
SERVICES = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "execution" / "MetalExecutionServices.java"
HARNESS = ROOT / "tools" / "metal4-cold-probe" / "Metal4ColdProbe.java"

for path in (PROVIDER, SERVICES, HARNESS):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.relative_to(ROOT)} is missing")

provider = PROVIDER.read_text(encoding="utf-8")
services = SERVICES.read_text(encoding="utf-8")
harness = HARNESS.read_text(encoding="utf-8")

# --- it is the neutral interface's implementation, and no generation type leaks into it -----------------
if "implements MetalExecutionProvider" not in provider:
    raise SystemExit("metal 4 provider: the provider does not implement the neutral execution interface, so "
                     "the services cannot hand it out without naming a Metal 4 type")
for signature in ("public long commandQueue(final MTLDevice device)",
                  "public MetalExecutionState createExecutionState(final MTLDevice device)",
                  "public MetalFrameEncoder createFrameEncoder("):
    if signature not in provider:
        raise SystemExit(f"metal 4 provider: the neutral signature '{signature}' is gone, so the provider no "
                         "longer honours the interface a generation-neutral caller uses")
for forbidden in ("render.metal3", "mtl.metal3"):
    if forbidden in provider:
        raise SystemExit(f"metal 4 provider: the provider imports {forbidden}, which the migration plan's "
                         "architecture rules forbid: a Metal 4 implementation must not depend on a Metal 3 one")

# --- the queue is real and a nil one is named -----------------------------------------------------------
if 'Msg.of("newMTL4CommandQueue"' not in provider:
    raise SystemExit("metal 4 provider: the queue factory is not the SDK's own selector, so the provider does "
                     "not own the queue it claims to")
if "throw new Unimplemented(\"commandQueue\"" not in provider:
    raise SystemExit("metal 4 provider: a nil queue is not refused by name, so a device that cannot make one "
                     "would be reported as a process that made nothing")

# --- the state and the encoder exist, and the refusals moved inside them ---------------------------------
# Phase 4 asked for the frame encoder and its state. Both are real objects now, so the pins moved with them:
# what used to be "the provider refuses by name" is now "the provider returns this generation's objects, and
# each object refuses, by name, exactly the operations it does not have". The reason is unchanged - section 35
# forbids an unknown operation being dropped into a half frame - and a provider that returned null for either
# half would still move the failure twenty calls later.
STATE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ExecutionState.java"
ENCODER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4FrameEncoder.java"
for path in (STATE, ENCODER):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so one half of the provider's frame path "
                         "has no implementation at all")

state = STATE.read_text(encoding="utf-8")
encoder = ENCODER.read_text(encoding="utf-8")


def body_of(source, signature):
    """The body of one Java method, from its signature to its matching closing brace.

    Several of the facts pinned below are statements whose text appears at more than one call site - a pass that
    ends a copy encoder, a depth attachment built from a caller's value - so a file-wide search would stay green
    while the one site that matters lost it. Reading a method body is what makes those pins pins.
    """
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise SystemExit(f"metal 4 provider: {signature[:40]}... has no closing brace, so its body cannot be read")


if "return new Metal4ExecutionState(device);" not in provider:
    raise SystemExit("metal 4 provider: createExecutionState no longer returns this generation's state")
if "return new Metal4FrameEncoder(device, metal4, defaultShaderSource);" not in provider:
    raise SystemExit("metal 4 provider: createFrameEncoder no longer returns this generation's encoder")
if "instanceof Metal4ExecutionState metal4" not in provider:
    raise SystemExit("metal 4 provider: the encoder is built from a state that was not checked to be this "
                     "generation's, so a Metal 3 state could be handed to a Metal 4 encoder")

# The state: the three operations that are true answers for a cache that holds nothing, and the one that is a
# refusal - which has to carry the operation's name, because "cannot compile yet" and "the caller passed
# nothing" are different facts about the frame path.
for needle, why in (
    ("implements MetalExecutionState", "the state no longer implements the neutral contract the device holds"),
    ("return this.compilation.getOrCompilePipeline(pipeline, source);",
     "the state does not compile through this generation's own chain, so a Metal 4 session would be handed "
     "something built somewhere else"),
    ("return this.compilation.evictCachedPipelines(predicate);",
     "eviction no longer reaches the compilation state, so a pack reload would evict nothing"),
    ("return this.compilation.clearCachesAfterGpuCompletion();" if False else
     "this.compilation.clearCachesAfterGpuCompletion();",
     "the cache clear is gone, so a pack reload or a teardown has no answer"),
    ("this.compilation.close();", "the state has no release, so a teardown has nothing to call"),
):
    if needle not in state:
        raise SystemExit("metal 4 provider: " + why)

# The queue the services hand the encoder is the encoder's to release: the ring explicitly does not own it, and
# the Metal 3 encoder releases the one the same seam gives it. Pinned because the two encoders' teardowns are
# where the difference is visible and nowhere else - this was a queue leaked once a session until the ledger.
if "this.queue = MemorySegment.ofAddress(queue);" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder does not keep the queue it was given, so it cannot"
                     " release it")
if "ObjC.release(this.queue);" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder never releases its queue, and the ring does not own"
                     " it - the Metal 3 encoder releases the queue the same seam hands it")

# The encoder: the neutral contract, the ring it owns, and a named refusal for every operation it lacks.
if "implements MetalFrameEncoder, MetalFramePresentation, MetalFrameExtras,\n        MetalFrameResourceCommands, MetalFrameComputeCommands {" \
        not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not implement the neutral frame contract, so the "
                     "device cannot hold it")
# Which optional contracts this path carries, and what each one is here for. Presentation is the surface's own
# request. MetalFrameExtras carries the attachment-contents question, which the pack side asks before every pass
# and which this path answers in full. MetalFrameResourceCommands is carried with three honest refusals, and the
# *carrying* is the part that matters: the client installs its capability adapter for a backend that carries this
# contract, so a generation that omitted it lost the attachment half that does work here - measured, a pack's
# stores were never elided on Metal 4 and the attachment bridge's "the backend was told" line never appeared.
if "MetalFrameResourceCommands" not in encoder.split("implements", 1)[1].split("{", 1)[0]:
    raise SystemExit("metal 4 provider: the encoder dropped MetalFrameResourceCommands, which does not cost it "
                     "three unimplemented operations but the whole capability dispatch - the attachment-contents "
                     "half included, which is measured to stop arriving when the contract is absent")
for needle, why in (
    # Mipmap generation is implemented now rather than refused, and what is pinned is the whole road: the
    # texture has to be one a chain can be generated for, the command goes on the frame's copy encoder, and the
    # texture is declared resident first.
    ("|| texture.getMipLevels() <= 1 || !supportsMipmapGeneration(texture.getFormat())",
     "mipmap generation no longer refuses a texture with one level or a format the native command cannot filter,"
     " so a caller would be told a chain was built"),
    ("boolean generated = copies.generateMipmaps(metal.nativeHandle());",
     "the frame path does not send the mipmap command, so the operation is still a refusal with a longer body"),
    ("Metal 4 trace: generated the mip chain of a {}x{} texture: {}",
     "a generated chain is not said under the trace switch, so nothing on a device run can show that a pack's"
     " mipmaps went through this path"),
    ("useResource(metal.nativeHandle());\n        boolean generated = copies.generateMipmaps(",
     "the texture is not declared resident before its chain is generated, and an undeclared resource makes a"
     " command of this kind do nothing at all - measured"),
    ("private static boolean supportsMipmapGeneration(final com.mojang.blaze3d.GpuFormat format) {",
     "the format list the native mipmap command needs is gone, so a texture it cannot filter would be sent"),
    # A storage texture is cleared by a typed kernel through a table now, not refused. What is pinned is the
    # whole road: the shape checks, the table, the residency declaration, and the dispatch the helper encodes.
    ("|| dimensions < 1 || dimensions > 3) {\n            return false;",
     "clearing a storage texture no longer refuses a dimensionality this engine does not carry"),
    ("cleared = this.storagePipelines.clearZero(copies, table, metal.nativeHandle(),",
     "the frame path does not dispatch the zeroing kernel, so the operation is still a refusal with a longer"
     " body"),
    ("MTL4ComputeEncoder copies = dispatchEncoder(\"the storage clear of a \" + dimensions + \"D texture\");",
     "the storage clear shares the frame's copy encoder instead of getting one of its own - the shape that lost"
     " a dispatch in the probe"),
    ("useResource(metal.nativeHandle());\n        boolean cleared;",
     "the image is not declared resident before it is written by a kernel, and an undeclared resource makes a"
     " command of this kind do nothing at all - measured"),
    ("MTL4ArgumentTable table = MTL4ArgumentTable.create(this.executionState.device(), 0L, 1L, 0L);",
     "there is no table for a storage dispatch to bind its image through, and this command model has no"
     " per-resource setter on the encoder"),
    ("queueForDestroy(table::close);\n        MTL4ComputeEncoder copies = dispatchEncoder(",
     "the clear's table is not given back through the frame's destruction queue, so it would outlive the slot"
     " that may still read it - or leak"),
    ("name.endsWith(\"_UINT\") ? com.metallum.mtl.metal4.MTL4StorageTexturePipelines.ScalarKind.UINT",
     "the zeroing kernel's scalar type is not read from the texture's own format, so a uint image would be zeroed"
     " by the float kernel and the pipeline would not build or would write the wrong bits"),
    ("return refuseResourceOperation(\"copyStorageTextureRegion\");",
     "a storage-texture region copy no longer refuses by name, so a caller would be told it was copied"),
    ("private boolean refuseResourceOperation(final String operation) {",
     "the remaining resource refusals no longer run through one helper, so one of them can be answered without a "
     "name or without a line in the log"),
    ("this.refusedResourceOperations.add(operation)",
     "a resource refusal is not remembered, so an operation called every frame would fill the log"),
    ("Metal 4 frame encoder: {} is not implemented on this path yet, so the caller",
     "the resource refusal no longer names the operation it refused"),
    ("+ \" takes its own fallback.",
     "the resource refusal no longer says what the caller does instead of the operation"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
# What a pass said about its attachments reaches the pass and not the encoder that outlives it: the statement is
# taken and cleared before the pass is built, exactly as the Metal 3 encoder takes it, so a pass nobody described
# cannot inherit the last described pass's answers. A wrong DontCare is a wrong image rather than a slower frame,
# which is why this half is pinned with its order and not only its presence.
if "private AttachmentContents[] nextPassContents;" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder has nowhere to keep what the next pass was told about "
                     "its attachments, so every pass keeps the load and store actions it would have had and the "
                     "measurement is of nothing")
for needle, why in (
    ("public void setNextPassContents(final @Nullable AttachmentContents[] contents) {",
     "the encoder does not accept the attachment-contents statement the pack side makes before every pass"),
    ("this.nextPassContents = contents == null ? null : contents.clone();",
     "the statement is kept by reference, so a caller that reuses its arrays would rewrite a pass's answers"),
    ("Metal4RenderPass pass = new Metal4RenderPass(this, descriptor, passContents,",
     "the pass is still created without the facts stated for it, so the descriptor's load and store actions "
     "ignore what the pack side knows"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
read_facts = encoder.index("AttachmentContents[] passContents = this.nextPassContents;")
# Presence before position, so a line an edit deleted is reported as the defect it is instead of as a traceback
# from this file - the same rule the other contracts here follow.
if "this.nextPassContents = null;" not in encoder[read_facts:]:
    raise SystemExit("metal 4 provider: what the next pass was told is never cleared when it is taken, so a pass "
                     "nobody described would inherit the last described pass's answers")
cleared = encoder.index("this.nextPassContents = null;", read_facts)
built = encoder.index("new Metal4RenderPass(", read_facts)
if not read_facts < cleared < built:
    raise SystemExit("metal 4 provider: what one pass was told is read and cleared after that pass is built, so it "
                     "would leak onto the next")
# The other three members of the contract answer what is true of this generation. The storage-image boundary is
# already encoded after every pass on this path, so accepting the flag is not a silent drop. The scaler used to be
# a literal `false` with the Metal 4 MetalFX milestone named as the reason; that milestone has landed, so the pins
# moved to the invariants that make the answer honest: the capability is the scaler path's own existence - the
# device's functional answer, never a literal - and the scale is the generation's own object rather than a
# borrowed one, which is section 80's split and the reason a Metal 4 frame cannot be handed a Metal 3 scaler.
if "public void setNextPassReadsStorageImage(final boolean reads) {" not in encoder:
    raise SystemExit("metal 4 provider: the encoder does not accept the storage-image boundary statement, so a "
                     "caller finds the contract incomplete on the road that does answer the attachment half of "
                     "it and falls back from both")
if "return !this.closed && this.metalFx != null;" not in body_of(encoder, "public boolean metalFxAvailable() {"):
    raise SystemExit("metal 4 provider: the MetalFX answer is no longer the scaler path's own existence, so a "
                     "session would either claim a scaled road it cannot take or refuse one it has")
for needle, why in (
    ("this.metalFx = Metal4Fx.create(nativeDevice);",
     "the encoder does not make this generation's own MetalFX path, so the answer cannot be its existence"),
    ("return this.metalFx.scale(this.ring.commandBuffer(), color.nativeHandle(), output.nativeHandle(),",
     "the scale is not encoded on this frame's own Metal 4 command buffer through this generation's scaler"),
    ("if (this.copyEncoder != null && this.copyEncoder.open()) {\n            this.copyEncoder.endEncoding();",
     "an encoder of ours may still be open when the scaler encodes, which orders the upscale before work it has "
     "to follow"),
    ("if (this.metalFx != null) {\n            this.metalFx.close();",
     "the scalers and their compiler are not released with the encoder that made them, so a second device in one "
     "process could be handed the first one's compiled pipelines"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("MTL4FrameRing.create(nativeDevice, this.queue, FRAMES_IN_FLIGHT,",
     "the encoder does not make the frame's ring, so the frame's allocator lifetime has no owner"),
    ("device.executionServices().commandQueue(nativeDevice)",
     "the queue no longer comes from the execution services, which is the seam the frame path's isolation "
     "turns on - a generation that made its own queue would put a generation back inside the device"),
    ("private static Metal4ExecutionProvider.Unimplemented unimplemented(final String operation)",
     "the refusals no longer run through one helper, so a new operation can be dropped in without a name"),
    ("this.deferred[slot].add(destroyAction);",
     "a queued release is not filed against a ring slot, so nothing proves the GPU is done with it"),
    ("this.ring.awaitAll()", "the encoder does not wait for the ring before it releases what the GPU may be "
                             "reading"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- the render pass, which is the object a client frame would enter through -----------------------------
# The pass's attachment mapping is measured on the device in the cold probe (four colour attachments, per-slot
# clears, a load across a pass boundary), so what is pinned here is the object over it: that it is the neutral
# contract and only that contract, that it resolves the game's attachments and opens through the measured
# layer, and that every operation it cannot perform refuses by name rather than drawing nothing.
ARGUMENT_TABLE = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4ArgumentTable.java")
PASS = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4RenderPass.java"
if not PASS.is_file():
    raise SystemExit("metal 4 provider: Metal4RenderPass.java is gone, so createRenderPass has no pass object "
                     "and the frame cannot be entered at all")
pass_source = PASS.read_text(encoding="utf-8")

if "implements RenderPassBackend, MetalPassUniformWriter {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass does not implement the game's render pass contract and the "
                     "push-constant contract the sodium draw path asks it for by name")
for needle, why in (
    ("MTL4RenderEncoder.open(owner.nativeDevice(), owner.commandBuffer(), width, height,",
     "the pass does not open through the layer whose attachment mapping is measured on the device, so what ran "
     "in the cold probe is not what a frame runs"),
    ("MetalGpuTextureView metal", "the pass does not read the native texture a view names"),
    ("attachment.clearValue().orElse(null)", "the descriptor's clear value is ignored, so a cleared attachment "
                                            "would load what stood there instead"),
    ("descriptor.renderArea", "the render area is not read, so a pass could be opened over an area outside its "
                              "attachments"),
    ("is outside Metal attachment extent", "an area outside the attachments is not refused"),
    ("barrierForSubsequentEncoders()",
     "the pass ends without the producer barrier, so a later pass that reads what it wrote has no encoded "
     "dependency - which section 61 forbids"),
    ("public void pushDebugGroup(final @NonNull Supplier<String> label) {\n    }",
     "the debug group is no longer a no-op: it is a capture label and not work, and refusing it would break a "
     "frame for no correctness reason"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# The pass spends the facts the frame path stated for it. The one thing that may not drift is the agreement
# between the two readers of those facts: the descriptor that is opened and the probe that counts the traffic.
# They are pinned through the single mapping that decides them, so a pass that counted a load it did not ask for
# (or a store it discarded) fails here rather than turning into a wrong reading of what a frame costs.
for needle, why in (
    ("MTL4RenderEncoder.Color[] colors = new MTL4RenderEncoder.Color[attachments.size()];",
     "the pass no longer describes one colour slot per attachment the descriptor has, so an unused slot would "
     "be compacted away and every attachment after it would sit at another slot's number - measured on "
     "Vitrail's MRT fixture, whose unused slots come before the attachment that is written"),
    ("final float @Nullable [][] foldedColourClears, final @Nullable Double foldedDepthClear) {",
     "the pass constructor no longer takes what the frame path stated for it - the contents of each slot and"
     " the clears the frame deferred - so nothing can reach the descriptor's load and store actions"),
    ("AttachmentContents[] stated = AttachmentContents.resolve(contents, attachments.size());",
     "the pass does not default the statement per slot, so a caller that said nothing about a slot is not "
     "answered with the answer that changes nothing"),
    ("AttachmentContents slotContents = stated[index];",
     "the statement is not read per slot, so every attachment would be opened with the same answer"),
    ("MTL4RenderEncoder.Color color = new MTL4RenderEncoder.Color(attachmentTexture, slotContents,",
     "the pass no longer builds the attachment from the slot's own facts, so what the descriptor is opened "
     "with is not what the counter is given"),
    ("MTL4RenderEncoder.countAttachment(color, pixelSize(view));",
     "the pass states one set of facts to the counter and another to the descriptor, which makes the two "
     "readings incomparable"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
if "boolean depthCleared = depthAttachment.clearValue().isPresent();" not in pass_source:
    raise SystemExit("metal 4 provider: the depth load the pass asks for is not read from the descriptor, so the "
                     "counted depth load is a guess")
if "MTL4RenderEncoder.countDepthAttachment(depthAttachmentValue, pixelSize(view));" not in pass_source:
    raise SystemExit("metal 4 provider: the pass counts no depth traffic, or counts it from a restatement of the "
                     "descriptor rather than from the attachment it opens")

# The no-pack subset is implemented now, so this list is what a no-pack frame does NOT need yet - the multi
# and indirect draw forms, and the counters. They refuse by name rather than disappearing, which is what keeps
# the pass's gaps a list.
for operation in ("setPipeline", "bindTexture", "setUniform", "enableScissor", "disableScissor",
                  "setVertexBuffer", "setIndexBuffer", "draw", "drawIndexed"):
    if f'public void {operation}(' not in pass_source:
        raise SystemExit(f"metal 4 provider: the render pass no longer implements {operation}, which a no-pack "
                         "frame needs")

for needle, why in (
    # Pinned with its body, because the same `begun` test appears in submit() and a bare test would be satisfied
    # by the other occurrence while the frame stopped being begun at all. It is one method now, because the first
    # pass and the first copy both need it.
    ("private void beginFrameIfNeeded() {\n        if (this.ring.begun()) {\n            return;\n        }\n",
     "the frame is not begun at the first pass, so a pass has no command buffer"),
    ("retire(this.ring.slot());", "the slot's filed releases are not run once its completion has been observed"),
    ("retire(this.ring.slot());", "the slot's filed releases are not run once its completion has been observed"),
    ("this.currentPass = pass;", "the open pass is not remembered, so nothing can end it"),
    ("pass.finish();", "submitRenderPass does not end the pass"),
    ("if (this.currentPass != null) {", "a second pass can be opened while one is still open, which is two "
                                        "encoders in one command buffer with no order between them"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- the diagnostic drawable-wait switch, which must stay a diagnostic ------------------------------------
# The switch exists for one question - what the encoded `waitForDrawable:` contributes to the interval
# `MTL4CommitFeedback.GPUStartTime/GPUEndTime` reports - and the risk it carries is that a session which
# measures a faster number adopts it. So the pins say three things: it is off unless the property is set, it is
# consulted at exactly one place and that place still encodes the wait when it is off, and a session that sets
# it says so in its own log, because an arm has to be able to prove which submission it measured.
if 'Boolean.getBoolean("metallum.metal4NoDrawableWait")' not in encoder:
    raise SystemExit("metal 4 provider: the drawable-wait diagnostic switch is gone, so the wait inside the "
                     "commit window can no longer be priced by an experiment")
if "if (!NO_DRAWABLE_WAIT && !this.ring.waitForDrawable(drawable.handle())) {" not in encoder:
    raise SystemExit("metal 4 provider: the drawable wait is no longer encoded when the switch is off, which is "
                     "the production path - a diagnostic that also removed the wait by default would ship the "
                     "diagnostic")
if "metallum.metal4NoDrawableWait is ON" not in encoder:
    raise SystemExit("metal 4 provider: a session that leaves the drawable wait out no longer says so in its "
                     "log, so the arm that measured a different submission cannot be identified from its own "
                     "evidence")
if len([line for line in encoder.splitlines()
        if "NO_DRAWABLE_WAIT" in line and not line.strip().startswith(("*", "//", "/*"))]) != 3:
    raise SystemExit("metal 4 provider: the drawable-wait switch is read in {} code lines where it must be read "
                     "in three - its declaration, the present that consults it and the log line that reports it - "
                     "so a production path may have grown a way to reach it".format(
                         len([line for line in encoder.splitlines()
                              if "NO_DRAWABLE_WAIT" in line
                              and not line.strip().startswith(("*", "//", "/*"))])))
if "|| NO_DRAWABLE_WAIT" in encoder or "NO_DRAWABLE_WAIT = true" in encoder:
    raise SystemExit("metal 4 provider: the drawable-wait switch can be on without the property being set, "
                     "which would make a diagnostic the default submission")

# --- the pipeline's depth bias, which section 58 found carried but never sent -----------------------------
# The artifact has held `depthBiasConstant` and `depthBiasScaleFactor` since it was written and nothing on this
# path ever handed them to an encoder, so a pipeline that asks for a bias - a decal, a shadow-map offset - drew
# unbiased here and biased on the reference. The three pins are the selector with the floats the header declares,
# the call site where the Metal 3 pass makes it, and the counter that lets a live frame say whether any real
# scene reaches it.
ENCODER_FILE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4RenderEncoder.java"
metal4_encoder_source = ENCODER_FILE.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("setDepthBias:slopeScale:clamp:",', "the encoder cannot be told a pipeline's depth bias, so a "
     "biased pipeline draws at a different depth here than on the reference"),
    ("Msg.ofVoid(\"setDepthBias:slopeScale:clamp:\",\n            JAVA_FLOAT, JAVA_FLOAT, JAVA_FLOAT)",
     "the depth-bias selector's three floats are not declared in the header's order, so a swapped bias and "
     "slope-scale would compile and send the wrong adjustment"),
    ("public boolean setDepthBias(final float constant, final float slopeScale, final float clamp) {",
     "the encoder's depth-bias entry point is gone"),
):
    if needle not in metal4_encoder_source and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("this.encoder.setDepthBias(this.artifact.depthBiasConstant(), this.artifact.depthBiasScaleFactor(), 0.0f);",
     "the pass no longer applies the pipeline's depth bias, which is the gap section 58 found"),
    ("MetalFrameProbe.depthBiasApplied();",
     "a non-zero depth bias is no longer counted, so no live frame can say whether real geometry reaches the "
     "road - and 'the fields exist' is not the same reading as 'the encoder was told'"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
PROBE_SOURCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "shared" / "MetalFrameProbe.java"
probe_source = PROBE_SOURCE.read_text(encoding="utf-8")
for needle, why in (
    ("public static void depthBiasApplied() {", "the probe cannot count an applied depth bias"),
    ("depthBias={}", "the window line does not report the depth-bias count, so a session cannot say whether "
                     "any pipeline in it asked for a bias"),
):
    if needle not in probe_source:
        raise SystemExit("metal 4 provider: " + why)

# --- the compilation chain, which is what a draw needs before it needs anything else ---------------------
# The state now compiles Metal 4 artifacts rather than refusing: the game's GLSL compiler turns a pack's source
# into SPIR-V, the SHARED translator turns that into MSL and names the resources, and this generation builds its
# own native pipeline states from it. Nothing Metal 3's is reached - which is the whole point, and the reason
# these classes exist rather than a call into the reference implementation.
CONTEXT = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4CompilationContext.java"
COMPILER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4PipelineCompiler.java"
ARTIFACT = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
            / "Metal4CompiledRenderPipeline.java")
PLAN = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "Metal4BindingPlan.java")
for path in (CONTEXT, COMPILER, ARTIFACT, PLAN):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so the generation has no compilation chain")
context = CONTEXT.read_text(encoding="utf-8")
compiler = COMPILER.read_text(encoding="utf-8")
artifact = ARTIFACT.read_text(encoding="utf-8")
plan = PLAN.read_text(encoding="utf-8")

# The plan's half of the wide path, and the two mistakes that would make a wide pipeline's table unfittable: a
# binding an argument buffer carries has an argument index and not a table slot, so counting it would size the
# table past Metal's thirty-one buffer slots; and the argument buffer itself has to be counted, or the table
# would not cover the slot the pass writes its address into.
for needle, why in (
    ("if (slot.buffer() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer binding's index as a table slot, so a wide pipeline's table would be "
     "sized to the argument index space and refused for exceeding Metal's thirty-one buffer slots"),
    ("if (slot.texture() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer texture's index as a table slot"),
    ("if (slot.sampled() && !slot.indirect() && slot.readBy(stage)) {",
     "the plan counts an argument-buffer sampler's index as a table slot, which is the sixteen-slot ceiling the "
     "wide path exists to get around"),
    ("highest = Math.max(highest, argumentBuffer.bufferIndex());",
     "the plan does not count the argument buffer's own buffer slot, so the table would not cover the slot the "
     "pass has to write its address into"),
    ("public boolean indirect() {", "the plan does not say whether a slot is carried by an argument buffer"),
    ("public boolean usesArgumentBuffers() {", "the plan does not say whether it is a wide one"),
):
    if needle not in plan:
        raise SystemExit("metal 4 provider: " + why)

if "new Metal4CompilationContext(device)" not in state:
    raise SystemExit("metal 4 provider: the state owns no compilation context, so it can compile nothing")
# Imports, not mentions: these files explain in prose which package they may not depend on, and a pin that a
# comment can fail is a pin that pushes the explanation out of the code.
for source, name in ((context, "context"), (compiler, "compiler"), (artifact, "artifact")):
    if re.search(r"^import\s+.*(render\.metal3|mtl\.metal3)", source, re.MULTILINE):
        raise SystemExit(f"metal 4 provider: the {name} imports a Metal 3 package, which the architecture rules"
                         " forbid: the new generation may not depend on the reference one")

for needle, why in (
    ("Metal4PipelineCompiler.compile(this, p, source)",
     "the cache does not compile through this generation's compiler"),
    # The profile is part of every cache key for the same reason it is in the Metal 3 context: a module or a
    # function translated for one profile is not the one another profile needs.
    ("new ShaderCompilationKey(id, type, defines,\n                MetalShaderLanguageProfile.selected().token())",
     "a translated module is keyed without the MSL profile, so a session that changed profile could be handed "
     "the other one's module"),
    ("new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token())",
     "a compiled function is keyed without the MSL profile"),
    ("this.retired.add(held);", "a replaced artifact is not retired, so it would either leak or be closed while "
                                "work naming it is still in flight"),
    ("this.retired.poll().close();",
     "retired artifacts are not released where the contract says GPU completion has been established"),
    ("GlslCommentStripper.strip(source).stripLeading()",
     "the GLSL preparation no longer strips comments, which the Metal 3 path paid for: independent comment "
     "regexes leave a live slash behind on a pack's toggle block"),
):
    if needle not in context and needle not in artifact and needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

# The wide-pipeline boundary, which moved on a measurement rather than on taste. This generation first asked the
# shared translator for direct bindings unconditionally, on the reading that an argument buffer is Metal 3's
# mechanism and the table replaces it. The table replaces it for everything that fits; what it cannot replace is
# the sampler ceiling, because MTL4ArgumentTable.h caps a table at sixteen sampler slots and MSL declares one
# sampler attribute per sampled image. Photon's deferred4 reads nineteen. So the compiler hands the translator the
# DEVICE's argument-buffer answer, and the invariant that keeps this safe is that a wide translation is refused
# where the device has no tier 2 to hold it. The pin therefore moved from "always false" to the capability being
# the device's plus the guard, and it still forbids the translation from being duplicated here.
for needle, why in (
    ("boolean argumentBuffersTier2 = compilation.device().supportsArgumentBuffersTier2();",
     "the compiler does not ask the DEVICE for the argument-buffer answer, so the wide shape is decided by a "
     "literal again"),
    ("MetalCrossShaderTranslator.translate(vertexSpirv, fragmentSpirv, pipeline, layout,\n"
     "                            argumentBuffersTier2);",
     "the compiler no longer asks the SHARED translator for the layout, so either the translation is duplicated "
     "here or it is asked with an answer that is not the device's"),
    ("if (translated.usesArgumentBuffers() && !argumentBuffersTier2) {",
     "a translation that came back wide is accepted on a device with no argument-buffer tier 2, so the resources "
     "would be laid out in a buffer that could not be made"),
    ("translated.usesArgumentBuffers()",
     "the artifact is not told whether its resources are carried by an argument buffer"),
    ("translated.vertexArgumentBufferSets()",
     "the compiler does not pass the vertex stage's argument-buffer sets to the artifact"),
    ("translated.fragmentArgumentBufferSets()",
     "the compiler does not pass the fragment stage's argument-buffer sets to the artifact"),
    ("MetalPipelineKey.of(pipeline, MetalShaderLanguageProfile.selected().token(),\n"
     "                            translated.usesArgumentBuffers())",
     "the artifact's key does not name the profile and the binding-shape decision, so a direct artifact and a "
     "wide one could collide"),
):
    if needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

if "translate(vertexSpirv, fragmentSpirv, pipeline, layout, false)" in compiler:
    raise SystemExit(
        "metal 4 provider: the compiler asks for direct bindings by literal again, so a wide pipeline would be "
        "refused rather than carried through the table"
    )

for needle, why in (
    ("implements CompiledRenderPipeline, MetalCompiledArtifact, AutoCloseable",
     "the artifact is not both the game's compiled pipeline and a keyed neutral artifact"),
    ("compilation.device().newRenderPipelineState(descriptor)",
     "the artifact does not build its own native pipeline state through the compiled functions"),
    ("MTLPixelFormat.Depth32Float", "no depth variant is built, so a pass with a depth attachment has no state"),
    ("private static MTLVertexDescriptor buildVertexDescriptor(",
     "the vertex layouts are not described, so a vertex-buffer draw has no attribute mapping"),
    ("return highest + 1;",
     "the vertex layouts no longer start past the named vertex-stage buffers, so they would overwrite them"),
    ("BitSet allResources()", "the artifact does not publish the binding footprint a pass has to fill"),
    # The wide shape's own half: an encoder asked of the stage's own function, one layout per set per stage, and
    # the pack's own vertex-buffer base because an argument index is not a table slot.
    ("MTLArgumentEncoder.forFunction(vertexFunction, set)",
     "the artifact does not ask the vertex stage's own function for an argument encoder, so the buffer length "
     "would be a number this class guessed rather than the shader's layout"),
    ("MTLArgumentEncoder.forFunction(fragmentFunction, set)",
     "the artifact does not ask the fragment stage's own function for an argument encoder"),
    ("new MetalArgumentBufferLayout(MetalShaderStages.VERTEX, set, set,",
     "the vertex stage's argument buffer is not given the shared layout a plan is written against"),
    ("new MetalArgumentBufferLayout(MetalShaderStages.FRAGMENT, set, set,",
     "the fragment stage's argument buffer is not given the shared layout a plan is written against"),
    ("private static final int WIDE_VERTEX_BUFFER_BASE = 9;",
     "a wide pipeline has no fixed vertex-buffer base, so its vertex layouts would land in the argument index "
     "space the named bindings numbered"),
    ("? WIDE_VERTEX_BUFFER_BASE", "the wide vertex-buffer base is not the one the artifact uses"),
    ("layout.encoder().close();", "the argument encoders are not released with the artifact"),
):
    if needle not in artifact:
        raise SystemExit("metal 4 provider: " + why)

# The no-pack binding subset is implemented now, so the pins describe what the pass does rather than that it
# refuses: the pipeline is compiled through this generation, the binding plan comes from the artifact's own
# footprint, the tables are sized from that plan, a name the pipeline does not declare is a fault, and the
# vertex stride is the pipeline's own.
for needle, why in (
    ("Metal4CompiledRenderPipeline compiled = this.owner.compiled(pipeline);",
     "the pass does not compile through this generation's own path, so a Metal 4 pass would draw with something "
     "built elsewhere"),
    ("this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.argumentBufferLayouts(),",
     "the binding plan is not built with the artifact's argument buffers, so a wide pipeline's table would not "
     "cover the slot its argument buffer lands in"),
    ("plan.bufferSlots(MetalShaderStages.VERTEX)",
     "the vertex table is not sized from the plan, so it may not cover the slots it is given"),
    ("plan.bufferSlots(MetalShaderStages.FRAGMENT)",
     "the fragment table is not sized from the plan"),
    ("Metal4BindingPlan.Slot slot = this.plan.slot(name, texture);",
     "a binding is filled without looking it up in the pipeline's layout by name and kind"),
    ("if (slot != null) {\n            return slot;\n        }\n        if (TRACE && this.plan.declares(name)) {",
     "a name the pipeline does not declare is not skipped, so this path would be stricter than the Metal 3 pass "
     "it is the reference for: the engine hands every pass a fixed set of default uniforms and a given pipeline "
     "reads some of them, which the first run that got this far proved by binding Fog to the panorama pipeline; "
     "and a name the pipeline declares as the other kind is skipped for the same reason, which the cloud pass "
     "proved by the cloud pass"),
    ("private static final boolean TRACE = Boolean.getBoolean(\"metallum.metal4Trace\");",
     "the pass trace is not off unless a session asks for it, so every session would log a line per draw"),
    ('Metallum.LOGGER.info("Metal 4 trace: indexed draw {} of {} indices at {} of {} bytes, type {},"',
     "an indexed draw is not traced, so the command a GPU fault follows cannot be named"),
    ('Metallum.LOGGER.info("Metal 4 trace: draw {} of {} vertices from {}, instance {}, in \'{}\'",',
     "a draw is not traced"),
    ("this.owner.queueForDestroy(vertex::close);",
     "the vertex table is closed when the pass ends rather than when the frame that bound through it has "
     "completed, which is a release between encoding and execution"),
    ("this.owner.queueForDestroy(fragment::close);",
     "the fragment table is closed when the pass ends rather than with the frame"),
    # The wide pipeline's binding path, which is the whole of what this generation adds to the reference one: the
    # resources are written into a buffer by the shader's own argument encoder, and what the table carries is
    # that buffer's address at the slot the shared layout recorded. The two pins that matter for correctness are
    # the fault when no layout covers a binding, and the allocation of every layout up front - a wide pipeline's
    # table has a buffer slot per set and the shader dereferences whatever is in it.
    ("if (slot.indirect()) {\n            MetalGpuBuffer buffer = bufferOf(slice);",
     "an argument-buffer binding is written straight into the table, where its index is an argument index and "
     "not a table slot"),
    ("encoder.setBuffer(buffer.metalBuffer(), slice.offset(), slot.metalIndex());",
     "the argument buffer is not written with the buffer and offset the frame path bound, so the shader would "
     "read the wrong bytes"),
    ("encoder.setTexture(sampled.texture(), slot.metalIndex());",
     "a sampled image is not written into the argument buffer at the index the MSL declares"),
    ("encoder.setSamplerState(sampled.sampler(), slot.samplerMetalIndex());",
     "the sampler is not written into the argument buffer, so a sampled image would read one that is not there"),
    ("MTLArgumentEncoder encoder = bindArgumentBuffer(layout);",
     "the encoder is not asked of the pass's own argument buffer, so the write would go to a different buffer "
     "than the table slot points at"),
    ("MTLResourceOptions.of(MTLStorageMode.Shared, MTLHazardTrackingMode.Tracked)",
     "the argument buffer is not made with the storage and hazard tracking a CPU-written, GPU-read buffer needs"),
    ("this.owner.queueForDestroy(() -> ObjC.release(created.handle()));",
     "the argument buffer is not filed with the frame, so it would be released between encoding and execution"),
    ("table.address(buffer.gpuAddress(), layout.bufferIndex())",
     "the argument buffer's address does not reach the table slot the shared layout recorded, so nothing the "
     "shader dereferences would be the buffer this pass filled"),
    ("private void ensureArgumentBuffers() {",
     "the argument buffers are not all made when the pipeline is set, so a set whose resources are bound late "
     "would leave the shader dereferencing an address the table holds as nil"),
    ("        this.tablesAssigned = false;\n        ensureArgumentBuffers();",
     "the argument buffers are not made when the pipeline is set, so a wide pipeline's table buffer slots would "
     "still hold nil when the first draw reads them"),
    ("throw new IllegalStateException(\"no Metal 4 argument buffer carries '\" + slot.name() + \"' set=\"",
     "a binding no argument buffer carries is silently dropped rather than named as the disagreement between the "
     "translation and the artifact that it is"),
    ("this.encoder.drawIndexedPrimitives(this.artifact.topology().value, indexCount, this.indexTypeValue,\n"
     "                address, length, instanceCount, vertexOffset, firstInstance)",
     "the indexed draw does not carry the draw's own base instance, or does not pass the offset arithmetic's "
     "address and length"),
    ("this.vertexTable.address(address, stride, plan.firstVertexBufferSlot() + slot)",
     "a vertex layout is bound at the game's own slot rather than at the slot the pipeline's descriptor starts "
     "its layouts from, so it would overwrite a named vertex-stage buffer (the same expression appears in the "
     "fault's own message, which is why the pin is the call)"),
    ("if (TRACE && this.plan.declares(name)) {",
     "a name the pipeline declares as the other kind is neither skipped nor reported: the Metal 3 pass skips it "
     "and this path must agree with the reference it is compared against"),
    # And the model itself: a binding is remembered and resolved when a layout exists, which is the game's own
    # order (a pass's default uniforms are bound by name before any pipeline is set) and the Metal 3 pass's own
    # model (it keeps its uniforms and textures in maps and resolves them into the argument buffer a draw
    # builds).
    ("private final Map<String, GpuBufferSlice> uniformBindings = new LinkedHashMap<>();",
     "a uniform bound before the pipeline is not remembered, so the binding the game makes first would be lost. "
     "The remembered value is the slice and not a resolved address, because an argument buffer needs the buffer "
     "and the offset the frame path bound rather than an addition of them"),
    ("private final Map<String, Sampled> textureBindings = new LinkedHashMap<>();",
     "a texture bound before the pipeline is not remembered"),
    ("private final Map<Integer, GpuBufferSlice> vertexBuffers = new LinkedHashMap<>();",
     "a vertex layout bound before the pipeline is not remembered"),
    ("applyBindings();", "the remembered bindings are not resolved when a pipeline arrives"),
    ("Metal4BindingPlan.Slot slot = slotFor(name, true);",
     "a texture is not resolved against the layout, or not by name"),
    ("Metal4BindingPlan.Slot slot = slotFor(name, false);",
     "a uniform is not resolved against the layout, or not by name"),
    ("if (this.pipeline == null) {\n            return null;",
     "a binding made before the pipeline has no remembered answer, so the game's default uniforms would be "
     "refused instead of resolved when a pipeline arrives"),
    ("if (slot != null && !slot.texture()) {",
     "a remembered uniform is filled for a pipeline that declares the name as a texture, so a stale binding "
     "would be written into a texture's slot"),
    ("if (slot != null && !slot.buffer()) {",
     "a remembered texture is filled for a pipeline that declares the name as a buffer"),
    ("this.vertexBuffers.put(slot, buffer);",
     "a vertex layout bound before the pipeline is not remembered with its slot"),
    ("long stride = format == null ? 0L : format.getVertexSize();",
     "the vertex stride is not the pipeline's own vertex format, so a layout would be read per buffer rather "
     "than per vertex"),
    ("this.indexBufferAddress + (long) firstIndex * this.indexTypeBytes",
     "the indexed draw does not turn the engine's first index into an address offset, which is the one thing "
     "Metal 4's indexed draw does differently"),
    ("this.scissorWidth = this.targetWidth;",
     "disableScissor does not set the whole attachment, so the last rectangle would stay in force"),
    ("if (!this.tablesAssigned) {",
     "the tables are assigned on every draw rather than when they changed, which is the first-version "
     "compromise section 50 asks for"),
    ("throw new IllegalStateException(\"the Metal 4 pass was asked to encode \" + operation + \" with no\"",
     "a draw without a pipeline is not a named fault"),
    ("private void releaseTables() {", "a replaced pipeline's tables are not released at all"),
    ("        this.plan = Metal4BindingPlan.of(compiled.resources(), compiled.argumentBufferLayouts(),\n"
     "                compiled.firstAvailableVertexBufferSlot(), compiled.vertexBufferCount());\n"
     "        releaseTables();",
     "a replaced pipeline's tables are not released, so a stale plan could be read through a new pipeline"),
    # Pinned with the condition that guards them, because a table assignment short-circuited away still contains
    # the call: this is the shape a text pin cannot see on its own, and it is recorded here rather than left to
    # look like a pin that covers it.
    ("if (this.vertexTable != null && !this.encoder.setArgumentTable(this.vertexTable,",
     "the vertex table is never assigned to the encoder"),
    ("if (this.fragmentTable != null && !this.encoder.setArgumentTable(this.fragmentTable,",
     "the fragment table is never assigned to the encoder"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# What a no-pack frame does not need yet still refuses by name, so the gap is a list and not a silence.
for operation in ("multiDrawIndexed", "drawMultipleIndexed", "multiDraw", "drawIndirect",
                  "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in pass_source:
        raise SystemExit(f"metal 4 provider: the render pass does not refuse {operation} by name, so an "
                         "operation it cannot encode would be dropped into a half frame")

# --- the engine side of the copies, which is what the client's first gap asked for -------------------------
# The native layer was measured first (MTL4ComputeEncoder: the region and whole copies, 50 of 50 probes); this is
# the frame encoder's use of it, and the pieces that make an upload possible at all - the staging arena, the
# rotation that hands its blocks back only after the frame that reads them is proved complete, and the compute
# encoder the copies are encoded into. A copy that arrives before any pass also begins the frame, because a
# command buffer has to be begun before anything can be encoded into it.
for needle, why in (
    ("private final MetalTransientMemory transientMemory;",
     "the encoder has no staging arena, so nothing can be uploaded"),
    ("this.transientMemory = new MetalTransientMemory(device, this.destroyQueue);",
     "the arena is not the engine's own, or is not handed this encoder's destruction queue, so its blocks would "
     "be released on a second rotation"),
    ("return this.transientMemory;", "transientMemory() no longer answers with the arena"),
    ("this.transientMemory.rotate();",
     "the arena is never rotated, so a staged block would be reused while the frame that reads it may still be in "
     "flight"),
    ("this.transientMemory.close();", "the arena is never released"),
    ("private MTL4ComputeEncoder copyEncoder() {",
     "the copies have no encoder of their own, and this command model has no blit encoder to fall back on"),
    ("if (this.copyEncoder == null || !this.copyEncoder.open()) {",
     "the copy encoder is not re-opened when it has been ended, so a second copy in a frame would be encoded "
     "into a closed encoder"),
    ("this.transientMemory.uploadStaging(data, 4L, GpuBuffer.USAGE_COPY_SRC);",
     "a buffer write is not staged, so it has nothing to copy from"),
    ("int rowBytes = width * pixelSize;",
     "a texture upload does not compute the row layout the command copies with, which is a sheared image rather "
     "than an error"),
    ("source.offset() + skipBytes", "a buffer-to-texture copy ignores the source origin's byte offset"),
    ("queueForDestroy(callback);",
     "a readback's callback is not filed against the frame whose completion makes its bytes valid"),
    ("this.copyEncoder.barrierForSubsequentEncoders();",
     "a pass that follows a copy is not ordered against it, which section 61 forbids"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# The copy a frame encoded before a pass wrote something that pass may read, so the dependency is encoded
# wherever a render encoder opens. The clear encoder writes those three calls in its own body - it is a second
# reader of this frame's copies - and every other road into a render encoder goes through the shared pair the
# opening pin above requires, so this pins the clear's own copy of them and requires that the shared pair is the
# only other place they appear. Measured: a resume that opened its render encoder with the copy encoder still
# open crashed inside AGX, which is what the shared pair exists to prevent.
COPY_THEN_PASS = ("if (this.copyEncoder != null && this.copyEncoder.open()) {\n"
                  "            this.copyEncoder.barrierForSubsequentEncoders();\n"
                  "            this.copyEncoder.endEncoding();")
if COPY_THEN_PASS not in body_of(encoder, "private void encodeClear(final String operation,"):
    raise SystemExit("metal 4 provider: a clear is encoded without ordering the copies the frame encoded before"
                     " it, so it may clear over what a copy has not finished writing")
# And the road a pass takes goes through the shared method rather than writing the pair again: a pass that
# opened its render encoder with the copy encoder still open is what crashed, so the call is pinned where a pass
# opens - and the two other roads that need it (a compute dispatch and the present) keep their own copies, which
# is why this pins the call sites rather than a count.
if "endCopyEncoderBeforeAPass();" not in body_of(
        encoder, "public @NonNull RenderPassBackend createRenderPass(final RenderPassDescriptor descriptor) {"):
    raise SystemExit("metal 4 provider: a render pass is opened without ending the frame's copy encoder through"
                     " the shared road, so a pass may begin while a copy encoder is still open")

# The indexed draw's selector, which is the one command whose arity was wrong: this machine's
# MTL4RenderCommandEncoder.h declares eight arguments, and the form without baseInstance: does not exist. The
# guard asks the encoder before it is sent, so a short declaration is a named refusal in a log rather than a
# message send with the wrong arity - and the smoke draws through this method rather than through a copy of it.
ENCODER = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4RenderEncoder.java"
encoder_source = ENCODER.read_text(encoding="utf-8")
for needle, why in (
    ('"drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:"\n'
     '                    + "baseInstance:",',
     "the indexed draw's selector is not the eight-argument one this SDK declares, so respondsToSelector: "
     "answers no and every indexed draw refuses"),
    ("JAVA_LONG, JAVA_LONG, JAVA_LONG, ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG);",
     "the indexed selector is not declared with the eight argument widths it takes"),
    ("indexBufferLength, instanceCount, baseVertex, baseInstance);",
     "the indexed draw is not sent all eight arguments"),
    ("public String refusal() {", "the encoder cannot say why a draw was refused, so a client log names the "
     "draw and not the reason"),
    ("public boolean drawPresent(final MTL4ArgumentTable table, final boolean scaling) {",
     "the encoder cannot draw the engine's present triangle, so the frame's own present has no draw"),
    ("if (indexBufferAddress == 0L) {\n"
     "            this.refusal = \"the index buffer has no GPU address, so there is nothing to read \"",
     "an index buffer with no GPU address is refused without saying so, so the one fault this milestone found "
     "would read as a draw that was asked for and did not happen"),
    ("if (indexCount <= 0L) {", "an indexed draw of no indices is refused without saying so"),
    ("public boolean drawIndexedPrimitivesIndirect(final long primitiveType, final long indexType,",
     "the encoder has no indirect indexed draw for the pass to encode through"),
    ("if (indirectBufferAddress == 0L) {\n"
     "            this.refusal = \"the indirect buffer has no GPU address, so the draw has no arguments to read\";",
     "an indirect draw with no arguments buffer is refused without saying so"),
    ('"drawIndexedPrimitives:indexType:indexBuffer:indexBufferLength:indirectBuffer:"',
     "the encoder cannot encode the indirect indexed draw: the selector is the five-argument one this SDK "
     "declares"),
):
    if needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
# The two draws' "not open" refusal is the same sentence in both methods on purpose, so it is counted rather
# than searched: a search would be satisfied by the other method's copy while one of them went silent.
if encoder_source.count('this.refusal = "the pass " + this.which + " is not open, so there is no encoder to draw'
                        ' on";') != 3:
    raise SystemExit("metal 4 provider: a closed pass is refused without saying so in one of the three draws -"
                     " the direct, the indexed and the indirect one")

if "public boolean drawIndexedPrimitives(final long primitiveType, final long indexCount, final long indexType,\n" \
        "                                         final long indexBufferAddress, final long indexBufferLength,\n" \
        "                                         final long instanceCount, final long baseVertex, final long baseInstance)" \
        not in encoder_source:
    raise SystemExit("metal 4 provider: the indexed draw does not take a base instance, which the SDK's "
                     "selector requires")

# The copies have to be there as implementations and not only absent from the refusal list: a method that was
# renamed away would leave the refusal check passing and the frame path with nowhere to upload a texture.
for implementation in ("public void writeToBuffer(final @NonNull GpuBufferSlice destination",
                       "public void copyToBuffer(final @NonNull GpuBufferSlice source",
                       "public void writeToTexture(final @NonNull GpuTexture destination",
                       "public void copyBufferToTexture(final @NonNull GpuBufferSlice source",
                       "public void copyTextureToBuffer(final @NonNull GpuTexture source",
                       "public void copyTextureToTexture(final @NonNull GpuTexture source"):
    if implementation not in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder does not implement {implementation.split()[2]}, "
                         "which the client asked for by stopping there")

# The present, which the surface asks for by name: the picture drawn into the layer's next drawable by the
# engine's own present triangle, in this frame's command buffer, with Apple's two halves of the drawable order on
# either side of the commit. The present is the frame's own - one queue, one commit, one presentation path - and
# the sidecar that presents on a second queue stays where it is until this road is proven on the device.
for needle, why in (
    ("public void presentTextureToDrawable(final @NonNull CAMetalLayer layer, final @NonNull GpuTextureView textureView) {",
     "the encoder cannot be presented through, so the surface refuses it and no Metal 4 frame reaches the screen"),
    ("CAMetalDrawable drawable = layer.nextDrawable();",
     "no drawable is taken, so there is nothing to present into"),
    ("if (!NO_DRAWABLE_WAIT && !this.ring.waitForDrawable(drawable.handle())) {",
     "the queue is not told which drawable the command buffer about to be committed targets - the half of "
     "Apple's order that comes first, without which signalDrawable: is an unrecognised selector - except under "
     "the diagnostic switch that exists to price exactly this call"),
    ("new AttachmentContents(true, true), null)",
     "the present pass does not say that it stores the drawable and overwrites every pixel of it, so the "
     "drawable would be loaded before a triangle that covers all of it"),
    ("pass.drawPresent(table, scalingTo(drawableTexture, picture.nativeHandle()))",
     "the present is not drawn with the engine's own present triangle, so the V convention would be whatever "
     "this new road guessed - the copy road presented the loading screen upside down"),
    ("if (!this.ring.signalDrawable(drawable.handle())) {",
     "the drawable is never signalled, so nothing presents it"),
    ("            presentAll();\n            return;",
     "a drawable taken by a present is dropped when the frame encoded nothing, which leaks it"),
    ("        // After the commit, which is the half that comes second: the queue is told the drawable may be shown\n"
     "        // once the work it just committed has run.\n        presentAll();",
     "the drawable is not presented after the commit, so nothing this frame committed would ever be shown"),
    ("private final List<CAMetalDrawable> presentDrawables = new ArrayList<>();",
     "the frame does not hold the drawables it presents into, so a present that arrives before the commit that "
     "legalises it would have nowhere to wait"),
    ("this.presentDrawables.add(drawable);",
     "the drawable taken for a present is not held for the commit that makes presenting it legal"),
    ("            drawable.present();", "the drawable is never presented"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# What a no-pack frame does not need yet still refuses by name, so the gap is a list and not a silence; and the
# copies are no longer in that list, because the client asked for them by stopping there.
for operation in ("clearColorAndDepthTextures", "writeTimestamp"):
    if f'throw unimplemented("{operation}")' not in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder does not refuse {operation} by name, so an "
                         "operation it cannot encode would be dropped into a half frame")
for operation in ("writeToBuffer", "copyToBuffer", "writeToTexture", "copyBufferToTexture", "copyTextureToBuffer",
                  "copyTextureToTexture", "transientMemory", "clearColorTexture", "clearDepthTexture",
                  "createFence"):
    if f'throw unimplemented("{operation}")' in encoder:
        raise SystemExit(f"metal 4 provider: the frame encoder still refuses {operation}, which the client asked "
                         "for by stopping there")

# And the binding plan itself: the mapping the device proof drives.
PLAN = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "Metal4BindingPlan.java"
if not PLAN.is_file():
    raise SystemExit("metal 4 provider: Metal4BindingPlan.java is gone, so the tables the pass fills have no "
                     "shape to be built from")
plan_source = PLAN.read_text(encoding="utf-8")
for needle, why in (
    ("public int bufferSlots(final int stage) {",
     "the plan does not answer how many buffer slots a stage's table needs"),
    ("highest = Math.max(highest, this.firstVertexBufferSlot + this.vertexBufferCount - 1);",
     "the plan's buffer count does not account for the vertex layouts, so a table could be made too small for "
     "the slots it is given"),
    ("public int textureSlots(final int stage) {", "the plan does not answer a stage's texture slots"),
    ("public int samplerSlots(final int stage) {", "the plan does not answer a stage's sampler slots"),
    ("return this.byName.get(name);", "the plan does not look a binding up by the name the pack gave it"),
    ("public Slot slot(final String name, final boolean texture) {",
     "the plan cannot look a binding up by name and kind, so a layout holding a buffer and a texture under one "
     "name would collide - which one of the engine's own passes does"),
    ("public boolean declares(final String name) {",
     "the plan cannot say whether a name exists at all, which is what tells a skip from a kind mismatch"),
    ("(slot.texture() ? textures : buffers).put(slot.name(), slot);",
     "the plan's per-kind maps are not filled, so the kind-aware lookup would answer nothing"),
    ("public boolean sampled() {", "a slot does not say whether it has a sampler beside it"),
):
    if needle not in plan_source:
        raise SystemExit("metal 4 provider: " + why)
# And the probe drives the plan rather than literals, which is what makes the device proof a proof of this class.
probe_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "MTL4Probe.java").read_text(encoding="utf-8")
for needle, why in (
    ("Metal4BindingPlan.of(List.of(", "the layout smoke does not build a plan, so the plan is not what runs"),
    ("plan.bufferSlots(MetalShaderStages.VERTEX)", "the smoke does not size its tables from the plan"),
    ("plan.slot(\"tint\")", "the smoke does not look its bindings up in the plan"),
    ("plan.firstVertexBufferSlot()", "the smoke does not take the vertex slot from the plan"),
):
    if needle not in probe_source:
        raise SystemExit("metal 4 provider: " + why)

# The clears: a clear is a load action, a load action belongs to a pass, so the first version opens a pass of its
# own and encodes the clear as that pass's loading. It is a real cost (one pass per clear) and it is the honest
# answer while the question is whether the path runs at all; the Metal 3 encoder folds the clear into the next
# pass that uses the attachment instead, which is a lifetime model of its own.
#
# Every needle below is looked for inside one method body and not in the file: "if (this.currentPass != null)"
# and the depth attachment's construction each appear at several call sites, so a file-wide search would be
# satisfied by a clear that lost its own ordering or its own value and stayed green.
CLEAR_ENCODER = body_of(encoder, "private void encodeClear(final String operation,")
for needle, why in (
    ("pass = MTL4RenderEncoder.open(this.executionState.device(), this.ring.commandBuffer(), width, height,\n"
     "                    colors, depth, operation);",
     "a clear is not encoded as a pass over the attachment it clears"),
    ("if (this.currentPass != null) {\n            submitRenderPass();",
     "a clear can be encoded while a pass the game owns is still open, which is two encoders on one command "
     "buffer"),
    ("pass.barrierForSubsequentEncoders()",
     "a pass that follows a clear is not ordered against it, which section 61 forbids"),
):
    if needle not in CLEAR_ENCODER:
        raise SystemExit("metal 4 provider: " + why)

CLEARS = {
    "clearColorTexture": (
        body_of(encoder, "public void clearColorTexture(final @NonNull GpuTexture colorTexture,"),
        (("deferClear(new PendingClear(color.nativeHandle(), components(clearColor), color.pixelSize(),",
          "the colour clear does not record its attachment, its colour and its extent"),
         ("colorTexture.getWidth(0), colorTexture.getHeight(0)",
          "the colour clear's pass is not described at the attachment's own extent, which is a wrongly-sized "
          "pass")),
    ),
    "clearColorAndDepthTextures": (
        body_of(encoder, "public void clearColorAndDepthTextures(final @NonNull GpuTexture colorTexture, final "
                         "@NonNull Vector4fc clearColor,\n                                           final "
                         "@NonNull GpuTexture depthTexture, final double clearDepth) {"),
        (("deferClear(new PendingClear(color.nativeHandle(), components(clearColor), color.pixelSize(),\n"
          "                depth.nativeHandle(), clearDepth, depth.pixelSize(),",
          "the colour-and-depth clear does not record both attachments and their values, so the depth "
          "attachment would keep whatever it held"),
         ("colorTexture.getWidth(0), colorTexture.getHeight(0)",
          "the colour-and-depth clear's pass is not described at the attachment's own extent")),
    ),
    "clearDepthTexture": (
        body_of(encoder, "public void clearDepthTexture(final @NonNull GpuTexture depthTexture,"),
        (("deferClear(new PendingClear(null, null, 0, depth.nativeHandle(), clearDepth, depth.pixelSize(),",
          "the depth-only clear does not record its attachment and its value"),
         ("depthTexture.getWidth(0), depthTexture.getHeight(0)",
          "the depth-only clear's pass is not described at the attachment's own extent")),
    ),
}
for name, (body, needles) in CLEARS.items():
    for needle, why in needles:
        if needle not in body:
            raise SystemExit(f"metal 4 provider: {why} ({name})")

# --- and a clear the frame deferred is a promise it has to keep -------------------------------------------
# Measured on one no-pack Metal 4 scene: 1500 clear encoders against Metal 3's nought, 7.7x the attachment load
# traffic, and 23.7 GiB loaded into depth where Metal 3 loads none - because a clear was a pass of its own where
# Metal 3 folds clears into the passes that use the attachments. The frame now records a clear and lets the next
# pass carry it as a load action, which is a scheduling change with one rule that has to hold: a reader of the
# attachment sees the clear, so anything that is not a pass attaching that whole texture materialises it first.
# Each half is pinned, and the flush roads are pinned by name because a road that forgot is a clear a shader
# reads before it was written - which is a wrong image and not an exception.
PROBE_TEXT = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "shared"
              / "MetalFrameProbe.java").read_text(encoding="utf-8")
for needle, why in (
    ("private final List<PendingClear> pendingClears = new ArrayList<>();",
     "the frame keeps no deferred clears, so every clear is a pass of its own again"),
    ("private void deferClear(final PendingClear clear) {",
     "there is no road that records a clear instead of encoding it"),
    ("private void flushPendingClears() {",
     "the frame cannot materialise what it deferred, so a reader could see an attachment before its clear"),
    ("private @Nullable FoldedClears foldPendingClears(final RenderPassDescriptor descriptor) {",
     "a pass does not fold the clears it could carry, so the traffic this is for is not saved"),
    ("FoldedClears folded = foldPendingClears(descriptor);",
     "the pass is opened without asking what it can carry"),
    ("if (!materialise.isEmpty()) {", "a clear that cannot fold is not materialised before the pass that cannot "
     "carry it opens"),
    ("return folded ? new FoldedClears(colourClears, depthClear) : null;",
     "the folded clears never reach the pass"),
    ("view.baseMipLevel() == 0\n                && view.mipLevels() >= view.texture().getMipLevels()",
     "a partial view is foldable, so a clear's load action could cover a range the clear never wrote"),
    ("if (slot >= 0 && colours.get(slot).clearValue().isEmpty()) {",
     "a descriptor's own clear is overridden by a deferred one, so a pass could be opened with a clear the game "
     "did not ask for there"),
    ("metal4Frame();" if False else "clearDeferred();", "a deferred clear is not counted, so the trade this makes "
     "is not readable in a session"),
    ("clearDeferred={} clearFolds={}", "the frame probe does not report the deferred and folded clears"),
):
    if needle == "clearDeferred={} clearFolds={}":
        if needle not in PROBE_TEXT:
            raise SystemExit("metal 4 provider: " + "the frame probe does not report the deferred and folded "
                             "clears")
        continue
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("MetalFrameProbe.clearFolded();",
     "a folded clear is not counted where the pass carries it, so the trade the frame probe reports would be "
     "one-sided"),
    ("folded != null ? folded\n                            : clear == null ? null : new float[]{clear.x(),",
     "the folded clear does not reach the colour attachment's load action, so the pass would load the pixels the "
     "clear was supposed to have written"),
    ("depthValue = foldedDepthClear;", "the folded depth clear does not reach the depth attachment's value"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
# The five roads out of a frame that owe the clear, each pinned where it is taken.
for road, why in (
    ("private MTL4ComputeEncoder copyEncoder() {\n"
     "        // A copy may read or write an attachment whose clear is outstanding, and a clear is only a promise until\n"
     "        // it is encoded: every road into a copy, a dispatch or the present keeps the promise before it opens.\n"
     "        flushPendingClears();",
     "a copy can read or write an attachment whose clear is still deferred"),
    ("private MTL4ComputeEncoder dispatchEncoder(final String which) {\n        flushPendingClears();",
     "a dispatch can read an attachment whose clear is still deferred"),
    ("public void presentTextureToDrawable(final @NonNull CAMetalLayer layer, final @NonNull GpuTextureView textureView) {\n        // The presented picture is a reader",
     "the presented picture can be read before a deferred clear was written"),
    ("public void submit() {\n        if (this.closed) {\n            return;\n        }\n        // A frame is not committed with a clear still owed",
     "a frame can be committed with a clear still owed"),
    ("public void close() {\n        if (this.passTimes != null) {\n            this.passTimes.close();\n        }\n        flushPendingClears();",
     "a frame can be closed with a clear still owed"),
):
    if road not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# The fence: Metal 3's fence is not an MTLFence, it is a promise about the submit index that was current when it
# was made, and the same callers read both generations. So what is pinned is that this generation answers the
# same three ways - a committed submission is waited for on the ring's event, one no commit has promised is not
# complete for a poll and is refused for a wait, and a fence between frames promises the work already submitted
# rather than a frame that does not exist.
FENCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4Fence.java"
if not FENCE.is_file():
    raise SystemExit("metal 4 provider: Metal4Fence.java is gone, so createFence has nothing to hand back")
fence = FENCE.read_text(encoding="utf-8")
for needle, why in (
    ("public final class Metal4Fence implements GpuFence {",
     "the fence does not implement the interface the game waits on"),
    ("return this.ring.awaitSubmission(this.submission, timeoutNS / 1_000_000L);",
     "the fence does not ask the ring whether its own submission completed, which is the whole promise"),
    ("if (this.closed) {", "a closed fence would still be waited on"),
):
    if needle not in fence:
        raise SystemExit("metal 4 provider: " + why)

RING = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4FrameRing.java"
ring = RING.read_text(encoding="utf-8")
for needle, why in (
    ("MTL4CommitOptions.error(feedback)", "the commit handler reads no error, so a GPU fault reaches the frame "
     "path as a completion value that never arrives instead of as the account the queue actually gave"),
    ("private static final long WAIT_MILLIS = 5000L;",
     "the ring does not wait the Metal 3 encoder's own five seconds for a slot's completion, so a legitimate "
     "stall would be reported as a lifetime fault"),
    ("public long nextSubmission() {\n        return signalled + 1L;",
     "the ring cannot say which submission the next commit will signal, or says the wrong one"),
    ("M4_FRAME_COMMIT submission={} commitMs={}",
     "a submission's own GPU interval is no longer paired with the ordinal of the frame that submitted it, so a "
     "per-frame pacing trace has no GPU time in it and the populations cannot be read against it"),
    ("public long lastSlotWaitNanos() {",
     "the ring no longer keeps the frame's own slot wait, so a per-frame line cannot say what a frame waited on"),
    ("public boolean waitForDrawable(final MemorySegment drawable) {",
     "the ring cannot register a drawable with its queue, so signalDrawable: would be an unrecognised selector"),
    ("public boolean signalDrawable(final MemorySegment drawable) {",
     "the ring cannot signal a drawable, so nothing would present it"),
    ("public boolean awaitSubmission(final long submission, final long timeoutMs) {",
     "the ring cannot be asked whether a submission completed, so a fence has nothing to ask"),
    ("if (submission > signalled) {\n            if (timeoutMs == 0L) {\n                return false;\n            }\n"
     "            throw new IllegalStateException(\"Cannot wait on a fence for the current submit\");",
     "a submission no commit has promised is reported complete, or a wait for it blocks instead of being "
     "refused by name - which is how a pool recycles a buffer the GPU is still reading"),
    ("if (submission <= 0L) {\n            return true;\n        }",
     "a fence about no submission at all is reported incomplete, so a resource held from before the first "
     "frame would never be handed back"),
    ("WAIT_UNTIL_SIGNALED.sendLong(event, submission, timeoutMs)",
     "the wait does not go through the shared event the commits signal on"),
):
    if needle not in ring:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("long submission = this.ring.begun() ? this.ring.nextSubmission() : this.ring.submissions();",
     "createFence does not promise the frame being encoded when one is open, or the work already submitted "
     "when none is"),
    ("return new Metal4Fence(this.ring, submission);", "createFence does not hand back this generation's fence"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if 'throw unimplemented("createFence")' in encoder:
    raise SystemExit("metal 4 provider: the frame encoder still refuses createFence, which the client asked for "
                     "by stopping there")

# The GPU's own account of a fault, which is the one thing a Metal 4 queue says about a submission that went
# wrong: a Metal 3 command buffer carries an errorDescription, and a Metal 4 queue reports nothing unless the
# commit was given options. Without this a GPU fault reads as a lifetime fault - measured, and the reason it
# exists: the first forced Metal 4 run that reported one said MTL4CommandQueueErrorDomain error 1, which the SDK
# header names MTL4CommandQueueErrorTimeout.
COMMIT_OPTIONS = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4CommitOptions.java"
if not COMMIT_OPTIONS.is_file():
    raise SystemExit("metal 4 provider: MTL4CommitOptions.java is gone, so a commit's GPU time and its fault "
                     "have no reader")
commit_options = COMMIT_OPTIONS.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("error", ADDRESS)', "the feedback's error is not read, so a GPU fault cannot be named"),
    ("public static String error(final MemorySegment feedback) {",
     "the feedback's error is not turned into words a log can carry"),
    ('LOCALIZED_DESCRIPTION.sendPtr(failure)', "the error's own description is not read"),
):
    if needle not in commit_options:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ('Msg.ofVoid("commit:count:options:", ADDRESS, JAVA_LONG,\n            ADDRESS)',
     "the ring has no commit-with-options form, so the queue's feedback can never be asked for"),
    ("private MTL4CommitOptions commitOptions;", "the ring holds no commit options"),
    ("commitOptions.feedbackHandler(feedbackBlock);\n                COMMIT_WITH_OPTIONS.send(queue, buffers, 1L,"
     " commitOptions.handle());",
     "the commit does not carry the options, so its feedback is never delivered"),
    ("block = ObjCBlock.withConsumer(MTL4FrameRing::reportFeedback);",
     "nothing reads the feedback, so a fault is still a silent timeout"),
    ("if (!faultReported) {\n            faultReported = true;",
     "a dead GPU is reported once per commit instead of once"),
    ('Integer.getInteger("metallum.metal4RingSlots", MTL4FrameRing.FRAMES_IN_FLIGHT)',
     "the ring's depth cannot be asked for, which is how a fault is correlated with the submission that caused "
     "it: at one slot the commands a trace prints before the fault report are the faulting submission's"),
):
    if needle not in ring and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- residency, which is what the frame path's addresses are -------------------------------------------------
# The new command model binds a buffer by GPU address and an address is not a reference, so nothing but a
# residency set keeps the allocation behind it resident. This is not a nicety: the first forced Metal 4 runs
# ended in a kernel GPURestart and an MTL4CommandQueueErrorTimeout until the frame path declared what it reads,
# and the A/B is one line of wiring - with the declarations, no restart and no timeout; without them, both.
RESIDENCY = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4ResidencySet.java"
if not RESIDENCY.is_file():
    raise SystemExit("metal 4 provider: MTL4ResidencySet.java is gone, so the frame path cannot declare what its"
                     " addresses name")
residency_source = RESIDENCY.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("newResidencySetWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS)',
     "the residency set has no factory, so nothing can be declared"),
    ('Msg.ofVoid("addAllocation:", ADDRESS)', "an allocation cannot be added to the set"),
    ('Msg.ofVoid("commit")', "the set cannot be committed, so its additions never take effect"),
    ('Msg.ofVoid("requestResidency")', "residency is never requested, which is the whole point of the set"),
    ('Msg.of("allocationCount", JAVA_LONG)', "the set cannot be asked what it holds"),
    ('Msg.ofVoid("endResidency")', "the set is released without ending its residency"),
    ("public boolean add(final MemorySegment allocation) {", "the wrapper cannot add an allocation"),
    ("public boolean commit() {", "the wrapper cannot commit"),
    ("public boolean requestResidency() {", "the wrapper cannot request residency"),
):
    if needle not in residency_source:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ('Msg.ofVoid("addResidencySet:", ADDRESS)',
     "the ring cannot hand a residency set to its queue, so the frame's declarations would belong to nothing"),
    ("public boolean addResidencySet(final MemorySegment set) {", "the ring has no call that takes a set"),
    ("void useResource(final @Nullable MemorySegment allocation) {",
     "the frame encoder cannot be told what the frame reads through an address"),
    ("MTL4ResidencySet.create(this.executionState.device(), 64L,", "the frame encoder makes no residency set"),
    ("commitResidency();", "the frame's declarations are never committed before its work is"),
    ("this.residencyAttached = this.ring.addResidencySet(this.residency.handle());",
     "the set is never given to the queue, so the GPU is never told about it"),
    ("this.residency.close();", "the set is never released with the encoder"),
):
    if needle not in ring and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# Every place the frame path binds something by address or id has to declare it, which is the difference the A/B
# measured: an attachment, a sampled texture, a uniform, a vertex layout and an index buffer are five different
# call sites and each one is pinned separately, because a pin on one of them would be satisfied by the others.
for needle, why in (
    ("public void drawIndexedIndirect(final @NonNull GpuBufferSlice commands, final int drawCount) {\n"
     "        // A frame encoder may have taken this pass's encoder away since the last call - see resume().\n"
     "        resume();\n"
     "        if (!prepareDraw(\"drawIndexedIndirect\")) {",
     "an indirect indexed draw is not implemented - the chunk renderer reaches its terrain through exactly that "
     "form - or is encoded without the state a draw needs"),
    ("this.encoder.drawIndexedPrimitivesIndirect(this.artifact.topology().value, this.indexTypeValue,",
     "the pass does not encode through the encoder's indirect draw, so the form would be a refusal again"),
    ("indirect += INDIRECT_ARGUMENTS_BYTES;",
     "the arguments of the next indirect draw are not twenty bytes further on, so every draw after the first "
     "would read the first one's arguments"),
    ("private static final long INDIRECT_ARGUMENTS_BYTES = 20L;",
     "the indirect arguments' stride is not the twenty bytes MTLDrawIndexedPrimitivesIndirectArguments is"),
    ("declare(commands.buffer());\n        long indirect = addressOf(commands.buffer(), commands.offset());",
     "the indirect arguments buffer is not declared resident, which is what the header asks for on this command "
     "by name"),
    ("public GpuBufferSlice.MappedView allocateTransient(final long size, final long alignment, final int usage) {",
     "a draw path that writes its own push constants has nowhere to write them, and the terrain draw asks for "
     "exactly that"),
    ("return this.owner.transientMemory().allocateGpuMapped(size, alignment, usage);",
     "the push-constant slice does not come from the frame's own arena, so its lifetime would be nobody's"),
    ("this.owner.useResource(attachmentTexture);", "a colour attachment is not declared resident"),
    ("this.owner.useResource(depthTexture);", "a depth attachment is not declared resident"),
    ("this.owner.useResource(textureView.nativeHandle());", "a sampled texture is not declared resident"),
    ("        declare(slice.buffer());", "a uniform buffer's allocation is not declared resident"),
    ("        declare(buffer.buffer());", "a vertex layout's allocation is not declared resident"),
    ("        declare(buffer);", "an index buffer's allocation is not declared resident, which is the case the"
     " header names by name"),
    ("        this.owner.useResource(metal.metalBuffer().handle());", "the declaration does not reach the"
     " allocation the address belongs to"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# The frame's own counters, which are the instrument the next question needed: the path rendered the loading
# screen at a fraction of the Metal 3 rate and the candidate list (a table a pass, an encoder a pass, a residency
# commit a frame) is exactly what these separate. Off unless a session asks, because a line every sixty frames is
# a diagnostic and not a session's log.
for needle, why in (
    ('Boolean.getBoolean("metallum.metal4FrameStats")',
     "the frame path cannot be asked what a frame cost, so a slow frame is a guess again"),
    ("private static final boolean COUNTING = TRACE || STATS || FRAME_TRACE;",
     "the counters are not kept when any diagnostic is on - the trace, the summary or the per-frame pacing line "
     "- so a diagnostic run would report passes, tables and draws of zero"),
    ('Boolean.getBoolean("metallum.metal4FrameTrace")',
     "the per-frame pacing line cannot be asked for, so a window's populations cannot be classified from what "
     "each frame waited on"),
    ("M4_FRAME frame={} slots={} slot={} submission={} wallUs={} slotWaitUs={}",
     "the per-frame line no longer carries the frame's own waits, which is what the classification reads"),
    ("Metal 4 frame stats: frames={} fps={} msPerFrame={}", "the counters are never reported"),
    ("this.statPasses++;", "a pass is not counted"),
    ("this.statEncoders++;", "an encoder is not counted"),
    ("this.statTables += tables;", "an argument table is not counted"),
    ("this.statResidency++;", "a residency declaration is not counted"),
    ("this.statFrameNanos += System.nanoTime() - this.statBeganAt;", "a frame's wall time is not measured"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if ("owner.statPass(this.drawsEncoded, this.indexedEncoded);\n        if (TRACE) {") not in pass_source:
    raise SystemExit("metal 4 provider: a pass's draws are counted only while the per-draw trace is on, so the"
                     " counters that answer what a frame cost report passes with no draws")
if "owner.statPass(this.drawsEncoded, this.indexedEncoded);" not in pass_source:
    raise SystemExit("metal 4 provider: a pass's draws are not reported to the frame's counters")
if "owner.statEncoder();" not in pass_source:
    raise SystemExit("metal 4 provider: a pass's encoder is not reported to the frame's counters")
if "statTables(plan.usesStage(MetalShaderStages.VERTEX) ? 1L : 0L" not in pass_source:
    raise SystemExit("metal 4 provider: the tables a pass makes are not reported to the frame's counters")

# The argument table's unbound slots, which is a correctness fact and not a detail: the header says
# initializeBindings defaults to false, so a slot this path never fills holds whatever the driver left there, and
# a shader that reads one dereferences it. This path skips a binding by design where a layout declares it as the
# other kind of resource, and the first world frame - the first that draws the clouds - was killing the GPU with
# an MMU fault until the tables were created with their bindings initialised to nil. Nil reads as zero, which is
# what the Metal 3 pass does with a name its layout never encodes.
if "SET_INITIALIZE.send(descriptor, 1L);" not in ARGUMENT_TABLE.read_text(encoding="utf-8"):
    raise SystemExit("metal 4 provider: the argument table is not created with its bindings initialised, so a"
                     " slot this path skips by design holds undefined data and a shader that reads it faults the"
                     " GPU - measured, and the first world frame was doing exactly that")

# The mipmap format list is the Metal 3 encoder's list, and the two are compared here rather than trusted: a
# format Metal 3 will generate a chain for and Metal 4 refuses is a difference between the generations, and one
# that would only show up as a blurry texture.
def mipmap_formats(source: str, marker: str) -> set[str]:
    """The format names one mipmap-support switch lists, read as identifiers rather than as text.

    Reading them as text picked up the method's own signature - the switch's opening line ends in a parameter
    named `format`, and a split on commas happily returned `... GpuFormat format) { return switch (format) {
    R8_UNORM` as one entry. An identifier scan over the switch body cannot do that.
    """
    at = source.index(marker)
    body = source[source.index("return switch (format) {", at):source.index("default -> false;", at)]
    return set(re.findall(r"[A-Z][A-Z0-9_]*", body))


metal3_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal3"
                  / "MetalCommandEncoder.java")
if not metal3_encoder.is_file():
    raise SystemExit("metal 4 provider: MetalCommandEncoder.java is gone, so there is no reference list of the"
                     " formats a native mipmap command can filter")
metal3_source = metal3_encoder.read_text(encoding="utf-8")
m3_formats = mipmap_formats(metal3_source, "private static boolean supportsNativeMipmaps(")
m4_formats = mipmap_formats(encoder, "private static boolean supportsMipmapGeneration(")
if not m3_formats or m3_formats != m4_formats:
    raise SystemExit("metal 4 provider: the mipmap formats the two generations will generate a chain for differ:"
                     f" metal 3 {sorted(m3_formats)} against metal 4 {sorted(m4_formats)}")

# The zeroing kernels this generation dispatches, which are its own copy and its own cache.
storage_pipelines = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                     / "MTL4StorageTexturePipelines.java")
if not storage_pipelines.is_file():
    raise SystemExit("metal 4 provider: MTL4StorageTexturePipelines.java is gone, so a storage texture has no"
                     " kernel to be zeroed by")
storage_source = storage_pipelines.read_text(encoding="utf-8")
for needle, why in (
    ("public enum ScalarKind {", "the kernels are not split by scalar type, so a uint image has no kernel"),
    ("texture2d<float, access::write> image [[texture(0)]]",
     "the zeroing kernel does not take a writable 2D image"),
    ("public boolean clearZero(final MTL4ComputeEncoder encoder, final MTL4ArgumentTable table,",
     "the zeroing call does not take the table the image is bound through"),
    ("if (!table.texture(texture, 0L) || !encoder.setArgumentTable(table)) {",
     "the image is not put in the table and the table is not handed to the encoder, which is the whole difference"
     " between this generation's clear and Metal 3's"),
    ("case 2 -> encoder.dispatchThreads(width, height, 1L, 8L, 8L, 1L);",
     "the 2D clear does not dispatch over the texture's own extent"),
    ("private final Map<String, MemorySegment> pipelines = new HashMap<>();",
     "the pipelines are cached statically rather than owned by the encoder that made them, so a second device in"
     " one process would inherit the first one's"),
    ("public void close() {", "the pipelines this object made are never released"),
):
    if needle not in storage_source:
        raise SystemExit("metal 4 provider: " + why)
# An import or a use of the Metal 3 class, and not the class's own prose: the javadoc says in as many words which
# layer it is not reaching into, and a pin that read the whole file would refuse its own explanation.
for forbidden in ("import com.metallum.mtl.metal3", "com.metallum.mtl.metal3.MTLStorageTexturePipelines",
                  "metal3.MTLComputeCommandEncoder"):
    if forbidden in storage_source:
        raise SystemExit(f"metal 4 provider: the Metal 4 storage pipelines reach into the Metal 3 layer"
                         f" ({forbidden}), which is the cross-generation import the architecture law forbids")

# The frame probe, fed by the full-frame path. The probe is how the standard harness collects a run at all - it
# waits for the probe's window line - and it was fed by the Metal 3 encoder alone, so a forced Metal 4 run was
# "never collected" no matter how well it rendered. Every counter the probe prints is reported from where the
# Metal 4 path has the fact, and the frame boundary is what opens the window.
for needle, why in (
    ("MetalFrameProbe.frameSubmitted();", "the full-frame path never reports a frame boundary, so the probe's"
     " window never opens and the harness cannot collect a forced Metal 4 run"),
    ("MetalFrameProbe.encoderOpened(0);", "a render pass the full-frame path opened is not counted"),
    ("MetalFrameProbe.encoderOpened(1);", "a copy encoder is not counted"),
    ("MetalFrameProbe.encoderOpened(3);", "a clear pass is not counted"),
    ("MetalFrameProbe.attachment(",
     "a colour attachment is not counted, so the probe's load and store traffic reports nothing"),
    ("MetalFrameProbe.depthAttachment(", "a depth attachment is not counted"),
    ("MetalFrameProbe.pipelineBound();", "a pipeline bind is not counted"),
    ("MetalFrameProbe.textureBound();", "a texture bind is not counted"),
    ("MetalFrameProbe.samplerBound();", "a sampler bind is not counted"),
    ("MetalFrameProbe.bufferBound();", "a buffer bind is not counted"),
    ("MetalFrameProbe.scissorSet();", "a scissor is not counted"),
    ("MetalFrameProbe.blit(width, height, textureOf(destination).pixelSize());",
     "a texture copy is not counted as a blit"),
    ("MetalFrameProbe.metal4Present();", "a present the full-frame path made is not counted"),
    ("long waited = System.nanoTime() - waitBegan;\n            this.lastSlotWaitNanos = waited;\n"
     "            MetalFrameProbe.submitWindowWait(waited);",
     "the ring's slot-reuse wait is not timed, so the waits line reports nothing for this path - and the "
     "per-frame trace, which reads the same wait out of this field, would report no wait at all"),
    ("MetalFrameProbe.gpuFrameMetal4(millis);", "the queue's per-commit GPU time is read but not reported to the"
     " probe, so a Metal 4 frame has no GPU time at all"),
):
    if needle not in encoder and needle not in pass_source and needle not in ring \
            and needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
if "private static int pixelSize(final GpuTextureView view) {" not in pass_source:
    raise SystemExit("metal 4 provider: the pass cannot say how large an attachment's pixels are, so the probe's"
                     " attachment accounting would count nothing")

# Which passes that traffic is counted for. The counter has to cover every pass this path opens, or a frame that
# clears in passes of its own reads as cheaper than one that folds those clears into the passes that use the
# attachments - a comparison of two designs on a number that only one of them is paying into. The counter is
# also fed from the mapping that opens the descriptor and not from a caller's restatement of it, so the two
# cannot drift.
for needle, why in (
    ("public static void countAttachment(final Color color, final int pixelSize) {",
     "the attachment counter is not a function of the attachment the descriptor is opened with, so a caller "
     "restating the mapping could count traffic Metal was never asked for"),
    ("loadAction(color.contents(), color.clear() != null) == LOAD_LOAD",
     "the counter no longer asks the load mapping, so a cleared or discarded load would still be counted"),
    ("storeAction(color.contents()) == STORE_STORE",
     "the counter no longer asks the store mapping, so a discarded store would still be counted"),
    ("public static void countDepthAttachment(final Depth depth, final int pixelSize) {",
     "the depth attachment has no counter of its own, so the slot the pack side cannot answer for is uncounted"),
    ("depth.clearDepth() == null", "the counted depth load is not read from the attachment the pass is opened "
                                   "with"),
):
    if needle not in encoder_source:
        raise SystemExit("metal 4 provider: " + why)
if encoder_source.count("MetalFrameProbe.attachment(") != 1 \
        or encoder_source.count("MetalFrameProbe.depthAttachment(") != 1:
    raise SystemExit("metal 4 provider: the counter no longer has exactly one colour and one depth entry point, "
                     "so some attachment traffic is counted somewhere the mapping does not reach")
for needle, why in (
    ("MTL4RenderEncoder.countAttachment(color, pixelSize(view));",
     "the game's own passes are no longer counted, so the frame's traffic has a hole in it"),
    ("MTL4RenderEncoder.countDepthAttachment(depthAttachmentValue, pixelSize(view));",
     "the game's own passes count no depth traffic"),
    ("MTL4RenderEncoder.countAttachment(colors[index], colorPixelSizes[index]);",
     "a clear's pass of its own is not counted, so clearing the way this path does reads as free"),
    ("MTL4RenderEncoder.countDepthAttachment(depth, depthPixelSize);",
     "a clear's depth attachment is not counted"),
    ("MTL4RenderEncoder.countAttachment(presentAttachment, picture.pixelSize());",
     "the present pass is not counted, so the drawable it overwrites is missing from the frame's traffic"),
):
    if needle not in pass_source and needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- what EXECUTES is a decision with a gate of its own ---------------------------------------------------
# The selector answers which generation the session is for; this answers which one encodes today, and the two
# are deliberately different facts. The two opt-in preferences execute what they selected - the player's
# `prefer-metal4`, which falls back to Metal 3 where the device cannot run Metal 4, and the developer's
# `metal4`, which the selector refuses to select as anything else - while AUTO and FORCE_METAL3 execute Metal 3
# whatever was selected: AUTO must not promote a frame path the migration has not finished (section 74's
# readiness gate), and a forced Metal 3 session stays Metal 3.
DEVICE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device = DEVICE.read_text(encoding="utf-8")
for needle, why in (
    ("case PREFER_METAL4, FORCE_METAL4 -> decision.selected();",
     "the executing generation is not decided from the preference, so either the player's opt-in would not run "
     "the path it asked for, or AUTO could promote an unfinished frame path"),
    ("MetalExecutionServices.of(decision.selected(), executesToday);",
     "the services are not built from both facts, so the selection and what executes could disagree again"),
    ("executing == MetalApiGeneration.METAL4" if False else "executesToday == MetalApiGeneration.METAL4",
     "a session that executes Metal 4 is not named as experimental, which is the one thing a reader of its "
     "numbers has to know"),
    ("Metal 4 EXECUTES this session", "the experimental warning does not say that Metal 4 is what runs"),
):
    if needle not in device:
        raise SystemExit("metal 4 provider: " + why)
# And the gate itself: AUTO must not be able to reach Metal 4 by the executing-generation line, and a player's
# preference must not be able to execute Metal 4 by a road that does not also carry the developer's strict one.
if "case AUTO -> MetalApiGeneration.METAL4" in device or "preference() == MetalExecutionPreference.AUTO" in device:
    raise SystemExit("metal 4 provider: AUTO can reach the executing Metal 4 path, which is the readiness gate "
                     "section 74 puts before it")
if "case AUTO, FORCE_METAL3 -> MetalApiGeneration.METAL3;" not in device:
    raise SystemExit("metal 4 provider: the executing-generation decision no longer names both generations that "
                     "must stay on the reference path, so a preference could promote a frame path the migration "
                     "has not finished")


# --- and it is reached by the EXECUTING generation, not by a constant ------------------------------------
if "switch (executing)" not in services:
    raise SystemExit("metal 4 provider: the services do not choose the provider by the executing generation, "
                     "so a session that executes Metal 4 would be built from Metal 3 objects - or the choice "
                     "is a constant again and this provider is dead code")
if "case METAL4 -> new com.metallum.render.metal4.Metal4ExecutionProvider();" not in services:
    raise SystemExit("metal 4 provider: the executing generation's Metal 4 case does not name this provider")

# --- and the present road is not started beside a frame path that already presents -------------------------
# Measured before it was written down: a forced Metal 4 session with `-Dmetallum.metal4Present=true` started the
# sidecar as well as the frame encoder's ring - two Metal 4 submission structures in one session, two
# commit-feedback registrations, one frame retirement model each - while only the frame encoder ever presented
# (1964 readbacks labelled with this generation's name, and none from the Metal 3 present road). Section 38
# forbids that shape by name and section 63 asks the migration to converge out of it, so the sidecar is started
# only for a session whose frame is encoded by a generation that does not present for itself, and its close asks
# the question its start asked.
for needle, why in (
    ("private boolean presentingThroughTheSidecar() {",
     "the present road is chosen from the policy alone, so a session that executes Metal 4 would start a second "
     "Metal 4 submission structure beside the frame encoder's own"),
    ("return presentsThroughMetal4() && executing != MetalApiGeneration.METAL4;",
     "the present road does not consider which generation executes, which is the fact that decides whether the "
     "sidecar is this session's present or a second one"),
    ("this.presentGate = presentingThroughTheSidecar()",
     "the present road is started without asking the question the helper states"),
    ("if (presentingThroughTheSidecar()) {",
     "the present road's close does not ask the question its start did, so a road that was never started could "
     "be closed, or a started one left behind"),
):
    if needle not in services:
        raise SystemExit("metal 4 provider: " + why)

# --- and the skeleton has real-device evidence -----------------------------------------------------------
if "provider=" not in harness or "Metal4ExecutionProvider" not in harness:
    raise SystemExit("metal 4 provider: the harness does not ask the provider on the real device, so the "
                     "skeleton has no evidence from an Apple Silicon run")
for needle, why in (
    ("MetalExecutionState state = metal4.createExecutionState(probeDevice);",
     "the harness does not make the state on the real device, so nothing reports what the state answers"),
    ("+ \" compile=\" + compile.replace(' ', '_')",
     "the harness does not report what the compilation chain answered, so the chain has no evidence from an "
     "Apple Silicon run"),
    ("RenderPipeline.builder()",
     "the harness does not build a pipeline description, so the compile is not reachable at all"),
    ("compileState.getOrCompilePipeline(compileFixture, compileSource)",
     "the harness never asks the state to compile through the chain"),
    ("new ColorTargetState(Optional.empty(), GpuFormat.RGBA8_UNORM,",
     "the fixture declares no colour target, and the pipeline builder refuses one without"),
    ("state.evictCachedPipelines(pipeline -> false)",
     "the harness does not ask the state to evict, so an empty cache's answer is assumed rather than measured"),
    ("state.clearCachesAfterGpuCompletion()", "the harness does not ask the state to clear its caches"),
    ("state.close()", "the harness does not release the state, so a run is not a run that gave its objects back"),
    ('",stateMethods=" + stateMethods', "the harness does not report what the state's operations answered"),
    ('",encoder=not-asked(needs-the-engine-device)"',
     "the harness no longer says why the encoder is not asked, so a reader cannot tell a deliberate omission "
     "from a missing answer"),
):
    if needle not in harness:
        raise SystemExit("metal 4 provider: " + why)


# --- the compute road, which is the door the client's compute fixture reaches ------------------------------
# Vitrail's `compute-storage-contract` stopped on this path at "Active Metal execution state does not support
# compute", which is the neutral bridge asking its question and getting no. So this generation's state answers
# it now, and what is pinned here is the shape of that answer: the translation is the SHARED one, the pipeline
# state is cached by the context that caches the function it was made from, and the handle owns a table without
# owning the state.
COMPUTE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4" / "Metal4ComputePipeline.java"
for path in (COMPUTE, CONTEXT):
    if not path.is_file():
        raise SystemExit(f"metal 4 provider: {path.name} is missing, so the compute road has no implementation")

compute = COMPUTE.read_text(encoding="utf-8")


def without_comments(source: str) -> str:
    """The source with comments and string literals removed, so a rule reads what a compiler reads."""
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", source)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)


for needle, why in (
    ("implements MetalExecutionState, MetalComputeCompiler",
     "the Metal 4 state does not answer the neutral compute-compile question, which is the one Vitrail's "
     "fixture asks"),
    ("public Object compileCompute(final MetalDevice device, final String label, final ByteBuffer spirv)",
     "the compute compile's neutral signature is gone"),
    ("MetalComputeTranslator.translate(spirv)",
     "the state does not translate through the shared layer, so this generation has grown its own SPIR-V "
     "reflection or has none"),
    ("return new Metal4ComputePipeline(device, label, translated.entryPoint(), pipelineState,",
     "the compile does not answer this generation's pipeline resource, so a dispatch has nothing to name"),
):
    if needle not in state:
        raise SystemExit("metal 4 provider: " + why)

# One translation, two generations: the Metal 4 compute path may not carry SPIRV-Cross of its own.
for name, source in (("Metal4ExecutionState", state), ("Metal4ComputePipeline", compute)):
    if "spvc_" in without_comments(source):
        raise SystemExit(f"metal 4 provider: {name} carries its own SPIRV-Cross calls, so the compute "
                         "translation is duplicated rather than shared")

for needle, why in (
    ("synchronized MemorySegment getOrCompileComputePipeline(final String msl, final String entryPoint)",
     "the context does not compile a compute pipeline state, so every handle makes its own"),
    ("MemorySegment function = getOrCompileFunction(key.msl(), key.entryPoint());",
     "the pipeline state is not made from the cached native function, so the function cache is bypassed"),
    ("this.computePipelineCache.clear();",
     "the compute pipeline states are never released, so a session leaks one per kernel"),
):
    if needle not in context:
        raise SystemExit("metal 4 provider: " + why)
if context.index("for (MemorySegment pipeline : this.computePipelineCache.values())") > \
        context.index("this.computePipelineCache.clear();"):
    raise SystemExit("metal 4 provider: the compute pipeline cache is cleared before it is released")
# Read inside the method, not file-wide: the function cache's key is the same text, and a file-wide search would
# stay green while this cache lost the profile from its own.
compile_pipeline_body = body_of(context, "synchronized MemorySegment getOrCompileComputePipeline(")
if "new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token())" \
        not in compile_pipeline_body:
    raise SystemExit("metal 4 provider: the compute pipeline cache is not keyed by the profile, so a state "
                     "compiled for one MSL profile would be handed to a session on another")
if "this.computePipelineCache.clear();" not in body_of(context, "synchronized void clearCachesAfterGpuCompletion()"):
    raise SystemExit("metal 4 provider: the compute pipeline cache is not released with the caches, so it "
                     "outlives the completion that made the release legal")

for needle, why in (
    ("MTL4ArgumentTable newTable(final MTLDevice device) {",
     "the compute handle no longer makes a table for a dispatch, and every dispatch needs one sized to that"
     " kernel's argument counts - a cached one is the shape that reads what the first dispatch bound"),
    ("private final Map<String, MetalComputeTranslator.Binding> bindings;",
     "the handle does not store the shared translation's bindings, so a dispatch would have to re-reflect"),
    ("Map<String, MetalComputeTranslator.Binding> bindings() {",
     "the handle does not answer with its bindings, so a dispatch cannot fill a table from them"),
    ("MTL4ArgumentTable.create(device, this.bufferSlots, this.textureSlots, this.samplerSlots)",
     "the handle's table is not sized to the argument counts the translation gave it"),
):
    if needle not in compute:
        raise SystemExit("metal 4 provider: " + why)
# The state is SHARED, so a handle holds a reference rather than the object: it retains one of its own, and its
# close hands that reference to the device's deferred release. Both halves are pinned, because either one alone
# is a lifetime fault - no retain means a borrowed pointer into a cache the game clears on every resource reload
# (F3+T reaches `clearCachesAfterGpuCompletion`), and a direct `ObjC.release` means a handle that frees an object
# another handle is still dispatching through, or frees its own while encoded work may still name it.
for needle, why in (
    ("this.pipelineState = ObjC.retain(Objects.requireNonNull(pipelineState, \"pipelineState\"));",
     "the handle holds the pipeline state without a reference of its own, so a cache clear frees an object it "
     "is still dispatching with"),
    ("this.device.queueResourceRelease(this.pipelineState);",
     "the handle never gives its reference back, so every compiled kernel leaks its state"),
):
    if needle not in compute:
        raise SystemExit("metal 4 provider: " + why)
if "ObjC.release" in without_comments(compute):
    raise SystemExit("metal 4 provider: the compute pipeline handle releases a native object where it stands, "
                     "but work already encoded may still name it - the release belongs on the device's "
                     "destruction queue")
if "queueResourceRelease(" not in body_of(compute, "public void close()"):
    raise SystemExit("metal 4 provider: the handle's close does not hand its reference to the state back, so a "
                     "dispatched kernel's state outlives every handle to it")

# And the nil a refused function answers with never reaches the pipeline factory: Metal asserts on
# `computeFunction must not be nil` and kills the process, which is not a compile the client can fall back from.
compile_pipeline = body_of(context, "synchronized MemorySegment getOrCompileComputePipeline(")
if "ObjC.isNil(function)" not in compile_pipeline or "MemorySegment.NULL" not in compile_pipeline:
    raise SystemExit("metal 4 provider: the compute pipeline cache asks the factory to build a state from a "
                     "function it has not checked, and a nil function aborts the process instead of failing the "
                     "compile")
if "Failed to compile Metal compute function for " not in state:
    raise SystemExit("metal 4 provider: a refused function is not named as itself, so a caller cannot tell a "
                     "kernel this device would not compile from a pipeline it would not make")


# --- and the dispatch, which is the half after the compile -------------------------------------------------
# The Metal 3 bridge's dispatch is per-resource encoder calls; this one is a table, and the facts that matter are
# the ones the new command model changed: the bindings are filled before the encoder opens, every allocation is
# declared resident, and the table is handed over before the dispatch that snapshots it.
dispatch_body = body_of(encoder, "public boolean dispatchCompute(")

if "MetalFrameResourceCommands, MetalFrameComputeCommands {" not in encoder:
    raise SystemExit("metal 4 provider: the frame encoder does not carry the neutral compute contract, so the "
                     "flat bridge's capability check answers no and the client never dispatches here")

for needle, why in (
    ("pipeline instanceof Metal4ComputePipeline resource", "the dispatch does not recognise this generation's "
     "pipeline resource, so it would answer false for its own handles"),
    ("MTL4ArgumentTable table = resource.newTable(this.executionState.device());",
     "the dispatch does not make a table for itself, and a table object re-pointed and handed to one encoder"
     " twice is not reliably re-read - measured in the cold-probe reproducer's one-encoder mode"),
    ("queueForDestroy(table::close);",
     "the dispatch's table is not given back through the frame's destruction queue, so it would outlive the"
     " slot that may still read it - or leak"),
    ("case UNIFORM_BUFFER, STORAGE_BUFFER -> bindDispatchBuffer(table, binding, buffers);",
     "buffers are not bound by address through the table"),
    ("case SAMPLED_IMAGE -> bindDispatchSampledImage(table, binding, textures, samplers);",
     "sampled images are not bound with their samplers"),
    ("case STORAGE_IMAGE -> bindDispatchStorageImage(table, binding, textures);",
     "storage images are not bound, so a kernel that writes one writes nothing"),
    ("MTL4ComputeEncoder compute = dispatchEncoder(\"the dispatch of \" + resource.label());",
     "the dispatch does not open an encoder of its own, and one encoder carrying two dispatches is the shape"
     " that lost the second one in the probe"),
    ("compute.setComputePipelineState(resource.pipelineState())",
     "the dispatch never hands the encoder the pipeline"),
    ("compute.setArgumentTable(table)", "the dispatch never hands the encoder the table it filled"),
    ("compute.dispatchThreadgroups(groupsX, groupsY, groupsZ, localX, localY, localZ)",
     "the dispatch is not encoded as workgroups, which is the shape a pack's vkCmdDispatch has"),
    ("compute.barrierForSubsequentEncoders();",
     "the dispatch's encoder ends without its producer barrier, so whatever encoder follows it - and an encoder"
     " per dispatch means something always does - may not see what the dispatch wrote"),
):
    if needle not in dispatch_body:
        raise SystemExit("metal 4 provider: " + why)

# The order of the three encoder calls is the API's: a pipeline, then the table it reads through, then the
# dispatch that snapshots it. Any other order encodes a dispatch the driver has nothing to run or nothing to
# bind, which is why this is a position check and not three presence checks.
# The one-encoder-per-dispatch rule lives in two helpers beside the dispatch, so it is pinned against the file.
for needle, why in (
    ("private MTL4ComputeEncoder dispatchEncoder(final String which) {",
     "there is no one place that says a table-binding dispatch gets a new encoder, so the rule could be lost"
     " one call site at a time"),
    ("private void endDispatchEncoder(final MTL4ComputeEncoder compute) {",
     "a dispatch encoder is not ended and filed for release in one place, so one of the two could be missed"),
    ("queueForDestroy(compute::close);",
     "a dispatch's encoder is released where it stands, and an encoder released before its command buffer is"
     " committed aborts the driver - measured"),
    ("this.copyEncoder.barrierForSubsequentEncoders();\n            this.copyEncoder.endEncoding();",
     "a copy encoder left open is not ended with its barrier before a dispatch opens its own, so the copies the"
     " dispatch reads are not ordered against it - or two encoders end up open at once"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

_pipeline_at = dispatch_body.index("compute.setComputePipelineState(resource.pipelineState())")
_table_at = dispatch_body.index("compute.setArgumentTable(table)")
_dispatch_at = dispatch_body.index("compute.dispatchThreadgroups(groupsX, groupsY, groupsZ, localX, localY, localZ)")
if not _pipeline_at < _table_at < _dispatch_at:
    raise SystemExit("metal 4 provider: the dispatch hands over the pipeline, the table and the workgroups in "
                     "an order the API does not allow")

# The residency declaration is not decoration on this path: an undeclared allocation reads as nothing at all,
# which the cold record measured one declaration at a time.
for helper in ("bindDispatchBuffer", "bindDispatchSampledImage", "bindDispatchStorageImage"):
    helper_body = body_of(encoder, f"private void {helper}(")
    if "useResource(" not in helper_body:
        raise SystemExit(f"metal 4 provider: {helper} binds a resource without declaring it resident, and an "
                         "undeclared allocation reads as nothing at all on this path")
# And every binding is resolved before the encoder is opened, so a caller's missing binding is a refusal with
# nothing encoded rather than a half-bound dispatch.
if "((MetalGpuTexture) view.texture()).markContentsDirty();" \
        not in body_of(encoder, "private void bindDispatchStorageImage("):
    raise SystemExit("metal 4 provider: the storage image's bookkeeping is not invalidated, so a clear the "
                     "engine recorded as materialized would be elided over contents a dispatch overwrote")

_first_binding = min(dispatch_body.index(call) for call in
                     ("bindDispatchBuffer(", "bindDispatchSampledImage(", "bindDispatchStorageImage("))
if dispatch_body.index("dispatchEncoder(") < _first_binding:
    raise SystemExit("metal 4 provider: the dispatch opens its encoder before the bindings are resolved, so a "
                     "missing binding would be found with the pipeline already set")
# The address of a slice is one addition, and it is not this class's to repeat.
if "Metal4RenderPass.addressOf(slice.buffer(), slice.offset())" not in body_of(encoder, "private void bindDispatchBuffer("):
    raise SystemExit("metal 4 provider: the dispatch computes a buffer's GPU address itself instead of using "
                     "the one helper that adds the slice offset")
# The kind this generation cannot bind is refused rather than dropped.
if "case TEXEL_BUFFER -> throw new IllegalStateException(" not in dispatch_body:
    raise SystemExit("metal 4 provider: a binding kind the dispatch cannot fill is dropped in silence")


# --- and a refusal by name is said out loud as well as thrown ----------------------------------------------
# Measured on the first no-pack Metal 4 session that was read rather than counted: the presented frame was one
# flat clear colour (`00b8d2ff` at all twenty-five samples of all 4958 readbacks), the world's `Terrain` pass ended
# with `draws=0` on every one of its 5316 traced passes, and the log said nothing - because the game's terrain
# batching asks for a multi-draw, the Metal 4 pass refuses it by throwing, and the caller catches the throw.
# Section 35 forbids a silent drop, and a throw alone is not enough when the caller swallows it: the refusal is
# logged where it is made, naming the pass, once per operation rather than once per draw.
if ("Metal 4 render pass '{}': {} is not encoded by this path yet, so the work that" not in pass_source):
    raise SystemExit("metal 4 provider: a refused operation is not said out loud, so a caller that catches the "
                     "throw drops the work with nothing in the log - measured as a world missing from a frame whose "
                     "session reported no fault")
for needle, why in (
    ("if (REFUSED_OPERATIONS.add(operation)) {",
     "the refusal line is not de-duplicated, so a refused multi-draw asked for every frame would fill a session's "
     "log"),
    ("private static final java.util.Set<String> REFUSED_OPERATIONS",
     "the refusal names are not kept anywhere, so the once-per-operation line has nothing to check"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- the drawable readback, which is the only way this machine can see the picture -------------------------
# The display cannot be photographed here and a drawable that is framebuffer-only cannot be copied from, so the
# picture column of every session has been empty for a reason about the *observation* rather than the frame.
# `-Dmetallum.drawableReadback=true` turns the layer's framebufferOnly off and copies the presented drawable into
# a shared buffer, where it can be read. It is a diagnostic and it is pinned as one: off by default, said out
# loud when on, asked for through one accessor, and released with the frame.
LAYER = ROOT / "src/main/java/com/metallum/mtl/CAMetalLayer.java"
if not LAYER.is_file():
    raise SystemExit("metal 4 provider: CAMetalLayer.java is gone, so framebufferOnly is nowhere")
layer = LAYER.read_text(encoding="utf-8")
for needle, why in (
    ('System.getProperty("metallum.drawableReadback", "false")',
     "the drawable readback is not asked for by one property with a default of off"),
    ("SET_FRAMEBUFFER_ONLY.send(this.handle, !READBACK);",
     "the layer is framebuffer-only whatever the diagnostic says, so the copy it exists for would be refused -"
     " or it is off without anyone asking"),
    ("public static boolean readbackRequested() {",
     "the frame path cannot ask the layer whether the drawable may be read, so the property would be read twice"
     " and could disagree with itself"),
    ("framebufferOnly is OFF because", "a session that changes the layer's contract does not say so"),
):
    if needle not in layer:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("private final boolean drawableReadback = com.metallum.mtl.CAMetalLayer.readbackRequested();",
     "the frame encoder does not ask whether the drawable may be read"),
    ("copyDrawableForReadback(drawableTexture, width, height);",
     "the presented drawable is never copied out, so the picture is still unreadable"),
    ("staging = this.executionState.device().newBuffer(bytes, MTLStorageMode.Shared.value);",
     "the readback's staging buffer is not a shared buffer on this generation's device, so the CPU could not read"
     " what the GPU wrote"),
    ("useResource(staging.handle());",
     "the readback's staging buffer is not declared resident, and an undeclared resource makes a copy do nothing"
     " at all - measured"),
    ("copies.copyTextureToBuffer(drawableTexture, 0L, 0L, 0L, 0L, 0L, width, height, 1L,",
     "the drawable is not copied into the buffer the report reads"),
    ("reportDrawableReadback(this.ring.slot());",
     "the copied drawable is never read, or it is read before the slot's submission is known complete"),
    ("com.metallum.render.shared.DrawableReadback.report(\"metal4\", width, height,",
     "the frame path does not read its copied drawable through the shared formatter, so the two arms' lines"
     " would not be comparable"),
    ("copyPictureForReadback(picture.nativeHandle(), MTLTexture.width(picture.nativeHandle()),",
     "the picture this path's present triangle read is never copied out, so a wrong picture and a present that"
     " changed it would read the same"),
    ("reportPictureReadback(this.ring.slot());",
     "the copied picture is never read, or it is read before the slot's submission is known complete"),
    ("com.metallum.render.shared.DrawableReadback.reportPicture(\"metal4\", width, height,",
     "the frame path does not read its copied picture through the shared formatter, so the two arms' halves would"
     " not be comparable"),
    ("ObjC.release(this.pictureStaging[slot].handle());",
     "the picture readback's staging buffers are never released with the encoder"),
    ("com.metallum.render.shared.DrawableReadback.bytesPerRow(width);",
     "the readback's row stride is computed here rather than by the shared helper the other arm uses"),
    ("ObjC.release(this.readbackStaging[slot].handle());",
     "the readback's staging buffers are never released with the encoder"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)


# And the same readback on the reference arm, because a comparison needs both sides: the Metal 3 present road's
# helper answers the drawable it drew into, the encoder copies it in the same command buffer and reads it where
# that arm already waits - and both arms format through the shared layer.
SHARED_READBACK = ROOT / "src/main/java/com/metallum/render/shared/DrawableReadback.java"
if not SHARED_READBACK.is_file():
    raise SystemExit("metal 4 provider: the shared drawable formatter is gone, so the two arms would format"
                     " their own lines and a comparison would compare the formatting")
shared_readback = SHARED_READBACK.read_text(encoding="utf-8")
for needle, why in (
    ("public static void report(final String which, final long width, final long height,",
     "the shared formatter does not take which arm read the drawable, so the two lines could not be told apart"),
    ("rows(top first)=[{}] meanBGRA=",
     "the shared formatter prints nothing structural, so a reader could not tell a black drawable from a wrong"
     " one"),
    ("public static long bytesPerRow(final long width) {",
     "the row stride is not shared, so the two arms could disagree about it"),
    ("public static void reportPicture(final String which, final long width, final long height,",
     "the shared formatter cannot read the picture a present road sampled, so a reading could not tell a picture"
     " that was wrong from a present that changed it"),
    ('read("picture", which, width, height, pixels, bytesPerRow);',
     "the picture's line is not labelled apart from the drawable's, so one run's two halves would read as two"
     " frames"),
):
    if needle not in shared_readback:
        raise SystemExit("metal 4 provider: " + why)

M3_ENCODER = ROOT / "src/main/java/com/metallum/render/metal3/MetalCommandEncoder.java"
if not M3_ENCODER.is_file():
    raise SystemExit("metal 4 provider: MetalCommandEncoder.java is gone, so the reference arm has no drawable"
                     " readback and the comparison has one side")
m3 = M3_ENCODER.read_text(encoding="utf-8")
for needle, why in (
    ("private final boolean drawableReadback = com.metallum.mtl.CAMetalLayer.readbackRequested();",
     "the reference arm does not ask whether the drawable may be read"),
    ("MemorySegment drawableTexture =\n                    commandBuffer.encodePresentTextureToDrawable(",
     "the reference arm's present road does not take back the drawable it drew into, so it cannot be read"),
    ("blitCommandEncoder().copyFromTextureToBuffer(drawableTexture, 0L, 0L, 0L, 0L, width, height, staging, 0L,",
     "the reference arm never copies its drawable out"),
    ("reportDrawableReadback((int) (currentSubmitIndex % MAX_SUBMITS_IN_FLIGHT));",
     "the reference arm never reads what it copied, or reads it before the slot's submission is known complete"),
    ('com.metallum.render.shared.DrawableReadback.report("metal3", width, height,',
     "the reference arm does not read through the shared formatter"),
    ("copyPictureForReadback(source.nativeHandle());",
     "the reference arm never copies the picture its present triangle read, so the two halves of a comparison"
     " could only come from two runs"),
    ("reportPictureReadback((int) (currentSubmitIndex % MAX_SUBMITS_IN_FLIGHT));",
     "the reference arm's copied picture is never read, or it is read before the slot's submission is known"
     " complete"),
    ('com.metallum.render.shared.DrawableReadback.reportPicture("metal3", width, height,',
     "the reference arm does not read its picture through the shared formatter"),
    ("ObjC.release(this.pictureStaging[slot].handle());",
     "the reference arm's picture staging buffers are never released with the encoder"),
):
    if needle not in m3:
        raise SystemExit("metal 4 provider: " + why)

# --- and what buffers a session made can be named, because a missing world asked for it --------------------
# The no-pack Metal 4 frame is one flat clear and its terrain passes encode no draws; the three candidates left
# (no section visible, no GPU slice for a visible one, or no mesh at all) are told apart by whether the terrain's
# own buffers are created and how large they are - a question about the device, not about any pass. Off unless
# asked for, and one line per allocation.
DEVICE_SOURCE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalDevice.java"
device_source = DEVICE_SOURCE.read_text(encoding="utf-8")
for needle, why in (
    ('Boolean.getBoolean("metallum.logBuffers")',
     "the buffer diagnostic is not asked for by one property, so it could not be off by default"),
    ('com.metallum.Metallum.LOGGER.info("Metal buffer: {} bytes, usage {} - {}", size, usage,',
     "an allocation is not named, so a missing terrain mesh and an unbound one read the same"),
):
    if needle not in device_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and the device does not claim what this path has not delivered ------------------------------------------
# Measured with one variable changed. With `persistentMapping` advertised true, Sodium stages its chunk meshes
# through a persistently mapped buffer - `MojangStagingBuffer`'s constructor picks `MappedStagingBuffer` on that
# flag and the engine-staged path otherwise - and on this path not one of them arrives: a no-pack Metal 4 session
# presented one flat sky-blue clear for all 4958 readbacks of a 40 s window (and again after 90 s), Sodium's own
# upload step reported build results every frame, and the geometry arena that would mean a mesh was accepted was
# never allocated, on either arm's log. With the flag withdrawn the same launch draws the world - the sampled
# terrain cells are the Metal 3 arm's own, cell for cell - and a Metal 3 launch is byte for byte unchanged. Where
# the mapped path loses the data is not localised, so the claim stays withdrawn until it is: the engine-staged
# path this selects instead goes through `writeToBuffer`, which both generations implement.
#
# The withdrawal was written for the whole device, though, and the flag is a fact about a generation: Metal 3
# advertised it since the backend existed and its frames were never the ones losing meshes, so the device-level
# answer made one generation's workaround decide the other generation's upload road. It is derived from what
# executes now, and what this pin refuses is the shape that leaked: a literal here would put the device - which
# knows nothing about the frame path - back in charge of a generation's answer. `tools/ci-metal3.py` holds
# the other half of the rule, including the generation test itself.
if "new DeviceFeatures(false, false, true, true, true, false, false)," in device_source:
    raise SystemExit("metal 4 provider: the device advertises persistently mapped buffers again as a device-wide "
                     "literal, so one generation's workaround would decide the other generation's staging road - "
                     "and on this path a session that stages through a mapped buffer loses the world's geometry: "
                     "measured as a no-pack frame that is one flat clear while Sodium's arena is never allocated")
if "persistentMappingFor(this.services.executing())" not in device_source:
    raise SystemExit("metal 4 provider: persistentMapping is not answered from what executes, so Metal 4's "
                     "engine-staged road and Metal 3's own could not be told apart")

# --- and a pass survives having its encoder taken away -----------------------------------------------------
# Measured: a dynamic uniform write inside an open pass grows the transient ring, that needs a copy encoder,
# `copyEncoder()` ends the pass the game still has open, `finish()` releases the tables with it, and the next
# `setVertexBuffer` died with "the Metal 4 pipeline ... has no vertex table for vertex buffer 0" - a frame lost
# on the render scale's fallback road. The reference generation survives the same interruption by reopening its
# encoder on demand, and this is that behaviour for this generation. Two things had to be true together, and
# both were measured: the pass keeps its tables and reopens an encoder (a suspension, not an end), and the frame
# keeps it as its current pass so that the game's own close still ends the reopened encoder - clearing the
# current pass instead left it open and the next compute clear crashed inside AGX's `endEncoding`.
for needle, why in (
    ("this.currentPass.suspendEncoder();",
     "the copy encoder does not suspend the open pass, so a pass the game is still encoding into either loses "
     "the tables it needs or keeps a reopened encoder open under another encoder's ending"),
    ("endCopyEncoderBeforeAPass();",
     "the frame has no single road that ends the copy encoder before a render encoder opens"),
    ("void endCopyEncoderBeforeAPass() {",
     "the copy encoder's ending is repeated inline instead of shared, so a road into a render encoder - a "
     "resumed pass - can miss it"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
for forbidden, why in (
    ("Metal4RenderPass interrupted = this.currentPass;",
     "the copy encoder takes the current pass out of the frame after suspending it, so the game's own close "
     "would find nothing to end and the reopened encoder would stay open"),
    ("interruptedByAFrameEncoder",
     "a marking entry point is back beside the suspension, so a pass could be marked without its encoder being "
     "ended - or ended without the frame keeping it"),
):
    if forbidden in encoder:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("void suspendEncoder() {",
     "the pass cannot be suspended, so the frame has to end it outright and a pass the game is still encoding "
     "into loses the tables it needs"),
    ("if (this.interrupted || this.finished) {",
     "a suspended or finished pass can be suspended again, so its encoder would be ended twice"),
    ("private void resume() {",
     "the pass has no resume, so any mid-pass copy ends it for good"),
    ("this.owner.endCopyEncoderBeforeAPass();\n        try {\n            this.encoder = MTL4RenderEncoder.open(",
     "the resumed pass opens its encoder without ending the copy encoder the suspension was for, so two "
     "encoders are open at once - measured as a SIGSEGV inside AGX's compute performEndEncoding"),
    ("this.encoder = MTL4RenderEncoder.open(this.owner.nativeDevice(), this.owner.commandBuffer(),",
     "the resumed pass does not open an encoder of its own, so nothing it encodes afterwards reaches the GPU"),
    ("this.targetWidth, this.targetHeight, this.reopenColours, this.reopenDepth, label());",
     "the resumed encoder is opened over something other than the pass's own attachments"),
    ("new AttachmentContents(color.contents().readAfterwards(), false), null);",
     "a reopened attachment does not keep its store answer and forbid a clear and an assumed overwrite, so a "
     "resume could throw away what the pass already wrote or read undefined tile contents"),
    ("this.reopenDepth = depth == null ? null : new MTL4RenderEncoder.Depth(depth.texture(), null);",
     "a reopened depth attachment is passed its clear value again, so the resume would clear the depth the pass "
     "has already written"),
    ("this.tablesAssigned = false;\n        this.resumes++;",
     "the resumed pass does not force the tables to be assigned to the new encoder"),
    ("pass '{}' reopened its encoder after the frame took it",
     "a resumed pass is not said out loud, so the extra encoder a frame's counters show would have no source"),
    ("\", resumed=\" + this.resumes", "the failure message does not say that this pass was resumed"),
    ("private void endEncoder() {",
     "the two endings - a pass the game finished and a pass the frame suspended - do not share one encoder end, "
     "so one of them would forget the producer barrier or the pass boundary marker"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
# And the pass's own tables are released where the pass is OVER and nowhere else: a suspension that released
# them would have to rebuild them for the resumed encoder, which is the leak the first version of this fix had.
for needle, why in (
    ("releaseTables();\n        endEncoder();",
     "the ending of a finished pass no longer releases its tables before it ends the encoder, so a replaced plan "
     "could be read through stale tables"),
    ("this.interrupted = true;\n        endEncoder();",
     "the suspension does not end the encoder through the shared path"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)
suspension = pass_source[pass_source.index("void suspendEncoder() {"):pass_source.index("private void endEncoder() {")]
if "releaseTables" in suspension:
    raise SystemExit("metal 4 provider: a suspension releases the pass's tables, so a resumed pass would rebuild "
                     "them and leave the first set filed for destruction with nothing to destroy it")

# --- and a draw is counted by every path that encodes one -----------------------------------------------
# The pass's counters are what its own trace line and the frame's `drawsPerFrame` are made of. The indirect
# indexed path did not increment them, and the world's terrain pass - which Sodium batches as indirect draws -
# therefore read `draws=0` on every one of 22836 endings in a frame that was drawing the world correctly. That
# single false reading sent two rounds of localisation after a pass that was never empty, so the count is pinned
# where the encoders are, not where the numbers are printed.
for needle, why in (
    ("            this.indexedEncoded++;\n            this.drawsEncoded++;\n            indirect +=",
     "the indirect indexed draw is not counted, so a pass that draws through it reads as an empty pass - measured "
     "as a terrain pass reporting zero draws while the world rendered"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and the trace says what a pass read as well as what it wrote -------------------------------------------
# A pass's attachments alone cannot answer the history question: on a target the pack doubles for history, two
# physical textures stand for one logical name, and "the pass read the copy it is about to write" and "the pass read
# the right copy whose write did not land" look identical from the write side. Measured with this line: every
# history pass samples exactly the copy the pass before it wrote (composite writes 0x..de00 and samples 0x..db80,
# composite1 writes 0x..db80 and samples 0x..de00, composite2 writes 0x..de00 and samples 0x..db80), in all 1783
# endings of the run - so the binding is not what breaks the chain, and the round that added this stopped having to
# argue about it.
for needle, why in (
    ("private String sampledTextures() {",
     "the trace cannot say which texture a pass sampled, so a wrong copy and an unlanded write read the same"),
    ("samples=[{}]", "the sampled textures are not printed on the pass's own line"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

# --- and a copy's rectangle is read in the contract's order, not the implementation's ----------------------
# Measured as a failing history chain and found in one trace line. The shared contract is
# `copyTextureToTexture(source, destination, mipLevel, destX, destY, sourceX, sourceY, width, height)`; this path's
# override declared `(source, destination, mipLevel, x, y, width, height, destinationX, destinationY)`, so a correct
# caller - Vitrail's history swap-back passes zero offsets and the target's width and height, as the contract asks -
# was read as a rectangle of **0 by 0** at destination (width, height). Metal accepts a zero-sized copy without
# complaint, so every texture-to-texture copy on this path moved nothing and said nothing: the trace line printed
# `texture copy 0x.. -> 0x.. 0x0 level 0`, and the history fixture's chain, which depends on that copy bringing the
# alternate half back over the main one, latched to magenta on its first frame and stayed there for the whole run.
# The override now reads the contract's order and passes the two origins where the native selector wants them.
for needle, why in (
    ("final int destX, final int destY, final int sourceX,\n                                     final int sourceY,"
     " final int width, final int height) {",
     "the override's parameters are not in the shared contract's order, so a correct caller's rectangle is read as"
     " the wrong region - measured as a zero-sized copy that moved nothing"),
    ("copyTextureRegion(textureOf(source).nativeHandle(), 0L, mipLevel, sourceX, sourceY, 0L,\n"
     "                width, height, 1L, textureOf(destination).nativeHandle(), 0L, mipLevel, destX, destY, 0L)",
     "the source origin is not the caller's source origin, or the destination origin is not the caller's"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- and a compute encoder is reported as one ---------------------------------------------------------------
# The frame probe's counters are the only way the two arms' encoder kinds are compared, and this path reported
# render, blit and clear but never compute: Complementary Reimagined's shadow compute read as **532** compute
# encoders over 600 frames on the reference arm against **0** here, which is a difference in the counter and not in
# the frame. The call is made where the dispatch encoder is opened, which is the same place the reference arm makes
# it, and nothing else in the probe is fed by it.
for needle, why in (
    ("        MetalFrameProbe.encoderOpened(2);\n        try {\n            return MTL4ComputeEncoder.open(",
     "a dispatched compute encoder is not reported to the frame probe, so this path's compute counts read as zero "
     "however much it dispatches - measured against the reference arm's 532"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# --- and a per-pass creation event is not printed per pass -----------------------------------------------
# This path makes an argument table per pass, so a Photon session wrote 525893 lines to its log and 105187 of them
# were that one line, one per table per pass. The line is now said under the trace switch, which is the same
# property the per-pass trace uses, and the routine fact stays with the frame probe's `tablesPerFrame`, which
# counts every table without printing any. **It is hygiene and not a fix**: gating it was first tried as the
# explanation for a pack load that stopped, and it changed that session's outcome by nothing - the same 251 pack
# units served at the same twelve seconds, before and after. The pin holds the gating; it does not claim a cause.
ARGUMENT_TABLE = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4ArgumentTable.java"
table_source = ARGUMENT_TABLE.read_text(encoding="utf-8")
for needle, why in (
    ('private static final boolean TRACE = Boolean.getBoolean("metallum.metal4Trace");',
     "the table's creation line is not gated on the trace switch, so a pack with many passes prints a line per"
     " table per frame - measured as 105187 of 525893 lines and a load that served 251 units in 300 seconds"),
    ("            if (TRACE) {\n                Metallum.LOGGER.info(\"Metal 4 argument table: made for",
     "the creation line is printed unconditionally again"),
):
    if needle not in table_source:
        raise SystemExit("metal 4 provider: " + why)

# --- the device waits for completion once, and not again on a ring the encoder has released -----------------
# Section 71's lifecycle gate had never run, because every session so far was *stopped* rather than quit. Driving
# the quit from inside the client gave the teardown its first real-device reading, and the reading was a false
# alarm: `MetalDevice.close()` waited for submitted work, closed the frame encoder - which submits any open pass,
# waits, and releases the ring - and then cleared the pipeline cache, whose own wait landed on that released ring.
# Measured after `Minecraft`'s `Stopping!`: the encoder's wait proved submission 3813 complete in 0 ms with
# `awaited=[3811, 3812, 3813]`, and the next wait read the same value as a timeout while the ring said
# `awaited=[0, 0, 0]`. The clear was also redundant - `executionState.close()` clears the same caches at the end -
# so the pin is the order: the device's close waits, closes the encoder, and does not clear the caches itself.
device_source = DEVICE.read_text(encoding="utf-8")
device_close = body_of(device_source, "public synchronized void close()")
if device_close is None:
    raise SystemExit("metal 4 provider: MetalDevice.close() was not found, so the teardown that runs once a "
                     "session is not pinned at all")
waited_at = device_close.find("this.waitForSubmittedGpuWork();")
encoder_at = device_close.find("this.commandEncoder.close();")
state_at = device_close.find("this.executionState.close();")
if min(waited_at, encoder_at, state_at) < 0 or not waited_at < encoder_at < state_at:
    raise SystemExit("metal 4 provider: the device's teardown no longer waits for submitted work, closes the "
                     "encoder that releases the ring, and releases the state that owns the caches - in that order")
if "this.clearPipelineCache();" in device_close:
    raise SystemExit("metal 4 provider: the device's teardown clears the pipeline cache after the encoder's close, "
                     "so the wait inside that clear lands on a released ring and reports a completion that already "
                     "arrived as a timeout - measured as submission 3813 with awaited=[0, 0, 0]")
# ---------------------------------------------------------------------------
# Section 88's per-pass GPU time: the frame path reads the GPU's clock behind its own pass boundaries
#
# The road was proven by the cold probe's counter smoke before any of this existed (its intervals scale with
# the work, its unit is a nanosecond, and an interval below about two thousand ticks is not ordered). What this
# pins is the frame path's use of it, because every one of these properties is a way the table would quietly
# stop being a measurement: a marker written before the pass ended, a read taken before the ring's wait, a
# second sampling form, a report that hides the floor, or a heap that outlives the encoder whose slot it
# describes.
# ---------------------------------------------------------------------------
pass_times = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
              / "Metal4PassTimes.java")
if not pass_times.is_file():
    raise SystemExit("metal 4 provider: Metal4PassTimes is missing, so the frame path has no per-pass GPU time "
                     "at all and section 92's third kind of timing is an assertion rather than a reading")
pass_times = pass_times.read_text(encoding="utf-8")
for needle, why in (
    ('Boolean.getBoolean("metallum.metal4PassTimes")',
     "the per-pass reader has no switch, so it either never runs or always does - and section 91 says "
     "instrumentation is off by default unless its overhead has been measured"),
    ("floorUs=2.0", "the report does not name the road's resolution floor, so a pass under it reads as a fast "
     "pass rather than as noise"),
    ("never the CPU's", "the line does not say which of section 92's three kinds of timing it is, so a reader "
     "cannot tell a GPU interval from the CPU's encode time"),
    ("resolveRange(0L, count)", "the slot's own frame is not read as one range, so the reading is of entries "
     "resolved one at a time rather than of the packed range the header promises"),
    ("this.totals.computeIfAbsent(label", "the intervals are not attributed to the pass that ended at the "
     "marker, so the table cannot say which pass cost what"),
    ("this.heaps[slot].writeTimestamp(commandBuffer, at)", "the boundary markers are not written into the "
     "slot's own heap at its own index"),
):
    if needle not in pass_times:
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ("this.passTimes = Metal4PassTimes.create(nativeDevice, FRAMES_IN_FLIGHT);",
     "the reader is not made once per encoder with one heap per slot, so its heaps would outlive or lag the "
     "ring they describe"),
    ("this.passTimes.beginFrame(this.ring.slot(), this.ring.commandBuffer());",
     "the slot's previous frame is not read where the ring has already waited for it, which is the header's own "
     "condition for resolving a heap on the CPU timeline"),
    ("this.passTimes.boundary(this.ring.slot(), this.ring.commandBuffer(), label);",
     "the pass boundary is not written from one place, so a pass can end without a marker"),
    ('recordPassBoundary("the present");',
     "the present is not counted with the passes, though it is a pass of the frame's own command buffer"),
    ("this.passTimes.close();", "the heaps are not released with the encoder that made them"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)
if "this.owner.recordPassBoundary(label());" not in pass_source:
    raise SystemExit("metal 4 provider: a render pass no longer records its own boundary when it ends, so the "
                     "marker would be placed somewhere other than behind the pass")

for needle, why in (
    ("this.ring.describe()",
     "the ring's state is not printed, so a wait that times out cannot say which value it waited for"),
    ("public String describe() {", "the ring has no state description to print"),
):
    if needle not in encoder and needle not in (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl"
                                                / "metal4" / "MTL4FrameRing.java").read_text(encoding="utf-8"):
        raise SystemExit("metal 4 provider: " + why)
for needle, why in (
    ('Metallum.LOGGER.info("Metal 4 frame encoder: waited {} ms for {} submission(s); complete={}, {}",',
     "the device-side wait reports nothing when it succeeds, so two waits on one ring cannot be told apart"),
    ('Metallum.LOGGER.info("Metal 4 frame encoder: closing - waited {} ms for {} submission(s); complete={}, {}",',
     "the encoder's close-time wait reports nothing when it succeeds"),
):
    if needle not in encoder:
        raise SystemExit("metal 4 provider: " + why)

# And the present names the texture it samples. "The GUI is not in the presented frame" is a question about two
# objects - the texture the passes drew into and the texture the present read - and a log that names one of them
# cannot answer it. Measured with this line: on a forced Metal 4 title screen the GUI's own pass and the present's
# picture are the same texture, so the missing GUI is not a mis-picked attachment.
if 'Metal 4 trace: presenting picture 0x{} {}x{} into a drawable 0x{} {}x{}' not in encoder:
    raise SystemExit("metal 4 provider: the present does not name the picture it samples and the drawable it "
                     "writes, so a frame with content missing cannot be told from a present that read another "
                     "texture")

# And every road that moves bytes declares both of its ends resident.
#
# This is the shape a whole interface's absence took. The Metal 4 header asks a copy's resources to be marked in an
# MTLResidencySet, this engine's model declares them with useResource, and an undeclared resource makes a copy do
# nothing on this API - silently, with no error and no fault. copyToBuffer was the one road that declared neither
# end, and it is the road Minecraft's own staged vertex buffer uses: the GUI's, the particles' and the entities'
# vertices arrived as zeros, every triangle collapsed to a point, and the draws were encoded, correctly bound,
# correctly stated and invisible on a frame whose world (drawn from Sodium's own buffers) was perfect. Measured on
# a forced Metal 4 title screen: the picture readback's mean went from (19, 17, 11) with no GUI in it to
# (40, 39, 33) with the buttons and the logo sampled, against Metal 3's own (40, 39, 33) on the same screen.
COPIERS = (
    "writeToBuffer", "copyToBuffer", "writeToTexture", "copyBufferToTexture", "copyTextureToTexture",
    "copyTextureToBuffer",
)
for name in COPIERS:
    signature = "void " + name + "("
    found = 0
    encoding = 0
    at = 0
    while True:
        start = encoder.find(signature, at)
        if start < 0:
            break
        at = start + 1
        found += 1
        body = encoder[start:encoder.find("\n    }", start)]
        # An overload that only hands its arguments to another overload encodes nothing and declares nothing, and
        # that is not the road this rule is about; the one that talks to the encoder is.
        if "copyEncoder()" not in body and ".copy" not in body.split("copyEncoder()")[0]:
            continue
        if "copyEncoder()" not in body:
            continue
        encoding += 1
        if "useResource" not in body:
            raise SystemExit("metal 4 provider: " + name + " encodes a copy without declaring either end resident,"
                             " and this engine's model makes an undeclared resource a copy that does nothing -"
                             " measured as the whole of Minecraft's GUI, particles and entities missing from a"
                             " frame whose world was correct")
    if found == 0 or encoding == 0:
        raise SystemExit("metal 4 provider: " + name + " is not an encoding road in the frame encoder any more, so"
                         " the road this contract is about has moved and the check is stale")

# And the rasterizer probe stays available, because it is what separated "this draw wrote nothing" from "this draw
# wrote something that looks like its background" - the reading that ended the hunt for Minecraft's GUI.
compiler = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "metal4"
            / "Metal4PipelineCompiler.java").read_text(encoding="utf-8")
for needle, why in (
    ('System.getProperty("metallum.probeForceColour")',
     "the forced-colour probe is gone, so a draw that produces no pixel can no longer be told from one whose pixel "
     "matches its background"),
    ("out.fragColor = float4(1.0, 0.0, 1.0, 1.0);",
     "the forced-colour probe no longer forces a colour, so it probes nothing"),
):
    if needle not in compiler:
        raise SystemExit("metal 4 provider: " + why)

# And a Metal device that refuses to initialize says that the reference path is skipped too.
#
# Measured under Metal API validation: forcing -Dmetallum.execution=metal4 on a device that does not satisfy the
# contract fails backend creation, and the backend the game picks afterwards is OpenGL - not the Metal 3
# reference every comparison in this programme is against. Nothing in the session said so, which is how a
# developer ends up measuring neither generation.
backend = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "render" / "MetalBackend.java"
           ).read_text(encoding="utf-8")
if "will not run the Metal 3" not in backend:
    raise SystemExit("Metal 4 execution provider contract: a Metal device that refuses to initialize does not say "
                     "that the Metal 3 reference path is skipped as well, so a forced Metal 4 session on a device "
                     "that cannot take it measures OpenGL with nothing in the log saying so")

# --- a buffer the shader reads as a texture ---------------------------------------------------------------
# The frame path can bind a `GpuBuffer` by name, and a shader may read it either as a buffer (a uniform or
# storage buffer) or as a texture (a texel buffer, which Metal presents as a view over the buffer's memory).
# Asking for a buffer slot alone dropped every texel buffer in silence, and the game's own cloud is drawn from
# exactly that shape: its face data is a texel buffer bound through `setUniform`, so the vertex stage read a
# slot nothing had filled and every face collapsed toward one point - clouds piled up over the camera. The plan
# has to carry the format for it, the pass has to ask for the texel kind *before* the buffer kind, the view has
# to be created over the buffer's memory, and it has to be released with the pass's other transients.
BINDING_PLAN = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "Metal4BindingPlan.java").read_text(encoding="utf-8")

for needle, why in (
    ("public @Nullable Slot texelBuffer(final String name)",
     "the binding plan cannot be asked for the texel buffer a name declares, so the frame path has only the "
     "buffer-slot question and a texel buffer is dropped again"),
    ("@Nullable GpuFormat texelBufferFormat) {",
     "the plan's slot no longer carries the format a texel buffer is read as, and a view made without it would "
     "read the buffer at the wrong stride"),
    ("resource.argumentBufferSet(), resource.texelBufferFormat()))",
     "the plan is built without the binding's texel format, so every texel buffer would be refused as missing "
     "one"),
):
    if needle not in BINDING_PLAN:
        raise SystemExit("metal 4 provider: " + why)

for needle, why in (
    ("Metal4BindingPlan.Slot texel = plan == null ? null : plan.texelBuffer(name);",
     "the Metal 4 pass asks only for a buffer slot when a buffer is bound by name, which is how a texel "
     "buffer - a buffer the shader reads as a texture - was dropped without a word"),
    ("fillTexelBuffer(name, texel, slice);",
     "nothing builds a texture view over the buffer a texel-buffer binding names"),
    ("MTLTexture.newBufferTextureView(",
     "the texel-buffer view is no longer a Metal texture created over the buffer's memory, which is the only "
     "way a `texture_buffer` argument can be read"),
    ("this.owner.queueForDestroy(() -> ObjC.release(view));",
     "the texel-buffer view is never released, so every frame with a texel buffer leaks one"),
    ("Metal4BindingPlan.Slot texel = plan.texelBuffer(name);",
     "a texel buffer bound before its pipeline arrives is never re-applied, so the first frame of such a pass "
     "reads an unbound slot"),
):
    if needle not in pass_source:
        raise SystemExit("metal 4 provider: " + why)

print("Metal 4 execution provider contract: PASS")

# ==================== was tools/ci-metal4-cold-probe.py ====================
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
if ('"$classes:$classpath" Metal4ColdProbe' not in script
        or "runClient" in script or "gradlew runClient" in script):
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

# --- the fourth render smoke's binding half --------------------------------------------------------------
# The migration plan's smoke 4 is "a sampled texture and a sampler, drawn as a fixed pattern, read back". The
# binding half is what the present sidecar exercises on the real path and what this proves in a process with no
# window in it; the draw and readback are the other half and are recorded as owed rather than implied.
# The heap is where the road's only writing call lives, so the smoke's marker and the frame path's marker are
# one sender: a contract that only read the probe could not tell that they had been split apart again.
counter_heap_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                       / "MTL4CounterHeap.java").read_text(encoding="utf-8")
for needle, why in (
    ("public static boolean canBindSampledTexture(", "the sampled-texture smoke is gone from the probe"),
    ("MTL4ArgumentTable.create(device, 0L, 1L, 1L)",
     "the smoke does not make a table of the shape it is testing, so its answer is about some other table"),
    ("return failed(\"sampled\", \"the table refused setTexture:atIndex:",
     "a refused texture binding is not reported, so a table that took the call and dropped it would read as "
     "success"),
    ("return failed(\"sampled\", \"the table refused setSamplerState:atIndex:",
     "a refused sampler binding is not reported"),
    ("releaseIfPresent(texture);", "the smoke's source texture is never released"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
if "sampled=" not in probe:
    raise SystemExit("cold-probe harness: the harness does not report the sampled-texture smoke, so it has no "
                     "evidence from an Apple Silicon run")

# --- the fourth render smoke's drawn half ----------------------------------------------------------------
# The binding half proved a table accepts a texture and a sampler. The drawn half is the plan's own smoke -
# "drawn as a fixed pattern, read back" - and it is a sequence of its own: a pattern pass, the producer barrier
# the new command model requires of a dependency between encoders, a sampled pass through the table, one
# commit, and a readback of the same four quadrants in both textures. What the pins below are for is that each
# part of that chain is still there, because a smoke that quietly stopped drawing would still print a line.
for needle, why in (
    ("public static boolean canDrawSampledTexture(",
     "the drawn half of the sampled-texture smoke is gone from the probe, so the smoke the plan asks for is "
     "owed again"),
    ("private static final int[][] EXPECTED_PATTERN = {",
     "the drawn smoke has no expected pattern, so its readback cannot fail and cannot pass either"),
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ);",
     "the source texture no longer declares that a shader reads it, so the sampled pass reads a texture the "
     "device was never told about - the usage is part of the question and not bookkeeping"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ("BARRIER.send(encoder, STAGE_ALL, STAGE_FRAGMENT, VISIBILITY_DEVICE);",
     "the pass that fills the sampled source ends without the producer barrier, so the dependency between the "
     "two encoders is assumed rather than encoded - which is exactly what section 61 forbids while migrating"),
    ("if (!responds(encoder, BARRIER.name())) {",
     "the barrier is sent without asking the encoder for the selector first, so a device that does not "
     "implement it raises an Objective-C exception instead of reporting a stage"),
    ("encodePass(buffer, destination, sampled.handle(), STAGE_FRAGMENT, sampledPipeline, false,",
     "the sampled pass is not given the table at the fragment stage, so the table-bound texture and sampler "
     "have no stage to reach the shader on"),
    ("MTLTexture.bytes(source, pixel, 4L, x, y, 1L, 1L);",
     "the source is not read back, so a pattern that never landed is reported as a sample that never arrived"),
    ("MTLTexture.bytes(destination, pixel, 4L, x, y, 1L, 1L);",
     "the destination is not read back, so the drawn smoke claims a result it never measured"),
    ("so the sample reached the wrong place in the source",
     "a sample that landed in the wrong quadrant is not reported as one, so a flip reads as a wrong colour "
     "and the answer stops naming the fault"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

# The harness's own half: the drawn result is reported, and counted apart from the capability sequence. The
# print expressions are pinned rather than the bare field names, because the field names also appear in the
# class's own documentation - a pin that a comment can satisfy is a pin that a removed print still passes.
for needle, why in (
    ('+ " sampledDraw=" + sampledDraw',
     "the harness does not print the drawn smoke's answer, so a run of it leaves no evidence"),
    ('+ " sampledDrawReason=" + sampledDrawReason',
     "the harness prints whether the drawn smoke passed and not why it failed, which is the half that says "
     "where to look"),
):
    if needle not in probe:
        raise SystemExit("cold-probe harness: " + why)
if "MTL4Probe.canDrawSampledTexture(device)" not in probe:
    raise SystemExit("cold-probe harness: the harness never asks the drawn smoke, so the probe's answer is "
                     "measured nowhere")
# The driver counts the drawn smoke in a line of its own and fails the run on it: a smoke whose failures are
# only printed is a smoke the next reader has to notice by eye.
for needle, why in (
    ("sampled_draw_failures=\"$(grep -c ' sampledDraw=false ' \"$probe_log\" || true)\"",
     "the driver does not count the drawn smoke's failures, so a run cannot say how many there were"),
    ("if (( sampled_draw_failures > 0 )); then",
     "the driver counts the drawn smoke's failures and does not fail the run on them, so a failing smoke "
     "reports success through the harness's own exit code"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the texel-buffer smoke, which is the cloud defect's own kind ------------------------------------------
# The game's own cloud pass binds a byte-format texel buffer on every frame it draws a cloud, and Metal carries
# that kind as a texture made over the buffer rather than as a buffer slot - so a pass that asks only the
# buffer-slot question finds nothing, skips the binding and draws with the slot nil. That is what the first
# full-frame Metal 4 runs did, and it put every cloud face at one point. The smoke asks the capability in the
# game's own shape (R8_SINT, three texels a face) and asks it twice, because one pass cannot tell a binding
# from a pipeline.
for needle, why in (
    ("public static boolean canSampleTexelBuffer(",
     "the texel-buffer smoke is gone from the probe, so the kind of binding the vanilla cloud defect was is "
     "measured nowhere but a live frame"),
    ("MTLPixelFormat.R8Sint.value",
     "the smoke no longer asks for the format the game's own cloud binding declares, so it answers a question "
     "about some other texel buffer"),
    ("texture_buffer<int> faces [[texture(0)]]",
     "the smoke's fragment stage no longer declares the kind MSL calls a texel buffer, so a pass could pass it "
     "while binding nothing the shader reads"),
    ("MTLTexture.newBufferTextureView(first.handle(), MTLPixelFormat.R8Sint.value, 0L,",
     "the smoke does not make its view over the buffer with the call the frame path makes, so it measures a "
     "different capability from the one the frames need"),
    ("TEXEL_SECOND_OFFSET, TEXEL_TEXELS, TEXEL_TEXELS);",
     "the smoke's second view is no longer made at a non-zero offset, so a view whose offset was read as an "
     "element index, dropped or applied to the wrong end of the range has nothing to fail against"),
    ("private static final long TEXEL_SECOND_OFFSET = 64L;",
     "the offset the smoke's second range begins at is gone, so the fixture is back to a single zero offset"),
    ("so the view's offset was not honoured",
     "a reading of the bytes at byte zero is not reported as an offset that did not reach the view, so the one "
     "fault a zero-offset fixture cannot see would read as a colour nobody recognises"),
    ("if (!table.texture(secondView)) {",
     "the second pass is not given its own view through the same table, so a table whose snapshot was taken "
     "once would pass as a binding that followed the pass"),
    ("binding was not the one this pass was given",
     "a pass that read the other buffer's values is not reported as a stale binding, so the second pass's whole "
     "point would be invisible in a failure"),
    ("texel-buffer view reached no fragment at all",
     "the clear colour is not reported as a binding that reached nothing, which is the exact fault a dropped "
     "texel-buffer binding produces"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ('+ " texelBuffer=" + texelBuffer',
     "the harness does not print the texel-buffer smoke's answer, so a run of it leaves no evidence"),
    ('+ " texelBufferReason=" + texelBufferReason',
     "the harness prints whether the texel-buffer smoke passed and not why it failed, which is the half that "
     "says where to look"),
):
    if needle not in probe:
        raise SystemExit("cold-probe harness: " + why)
if "MTL4Probe.canSampleTexelBuffer(device)" not in probe:
    raise SystemExit("cold-probe harness: the harness never asks the texel-buffer smoke, so the probe's answer "
                     "is measured nowhere")
# And the driver counts it and fails the run on it, for the reason the drawn smoke is counted: a smoke whose
# failures are only printed is a smoke the next reader has to notice by eye.
for needle, why in (
    ("texel_buffer_failures=\"$(grep -c ' texelBuffer=false ' \"$probe_log\" || true)\"",
     "the driver does not count the texel-buffer smoke's failures, so a run cannot say how many there were"),
    ("if (( texel_buffer_failures > 0 )); then",
     "the driver counts the texel-buffer smoke's failures and does not fail the run on them, so a failing smoke "
     "reports success through the harness's own exit code"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the frame's allocator rule --------------------------------------------------------------------------
# The one part of the frame's lifetime where a guess is a use-after-free, and the rule the frame encoder is
# built on: a slot is not reset until the value its own commit signalled has been observed. Measured on the
# device, the rule is load-bearing - with the wait removed, frame 0's pass never landed in five of five
# probes - so this file pins the order the two calls appear in and not merely that both exist.
#
# The pins below are the structural half of that guard and they are not the whole guard: a wait that is
# present in the text but short-circuited (`if (false && ...)`) passes every pin here, and is caught by the
# sequence itself, which asserts on the device that the ring waited exactly RING_FRAMES - FRAMES_IN_FLIGHT
# times. Structural pins and the device's own count together, and neither alone.
ring = ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4" / "MTL4FrameRing.java"
if not ring.is_file():
    raise SystemExit("cold-probe harness: MTL4FrameRing.java is gone, so the frame's allocator lifetime has no "
                     "owner and every frame path would have to grow a ring of its own")
ring_source = ring.read_text(encoding="utf-8")

wait_needle = "WAIT_UNTIL_SIGNALED.sendLong(event, awaited[next], WAIT_MILLIS)"
reset_needle = "RESET.send(allocators[next]);"
if wait_needle not in ring_source or reset_needle not in ring_source:
    raise SystemExit("cold-probe harness: the ring no longer waits for a slot's completion before resetting "
                     "it, which is the sentence MTL4CommandAllocator.h puts on the caller")
if ring_source.index(reset_needle) < ring_source.index(wait_needle):
    raise SystemExit("cold-probe harness: the ring resets the allocator BEFORE it has observed that slot's "
                     "completion value - the exact ordering MTL4CommandAllocator.h says the caller is "
                     "responsible for, and the ordering a run of this harness showed to be load-bearing")
begin_needle = "BEGIN.send(commandBuffer, allocators[next]);"
if begin_needle not in ring_source:
    raise SystemExit("cold-probe harness: the ring never begins the command buffer on the slot's allocator")
if ring_source.index(reset_needle) > ring_source.index(begin_needle):
    raise SystemExit("cold-probe harness: the ring begins encoding on the allocator and only then marks its "
                     "heaps for reuse, which would hand the memory the frame is being encoded into back to the "
                     "allocator underneath it")
for needle, why in (
    ("public boolean beginFrame()", "the ring has no begin, so nothing proves a slot is free before it is used"),
    ("awaited[slot] = ++signalled;", "a committed frame records no completion value, so its slot can never be "
                                     "proved free and would be reset blind"),
    ("SIGNAL_EVENT.send(queue, event, signalled);",
     "the commit is never signalled on the event, so no completion can be waited for at all"),
    ("public boolean awaitAll()", "the ring cannot be waited for, so a readback or a teardown has no point at "
                                  "which the GPU is known to be finished"),
    ("public void close()", "the ring has no release, so its allocators, command buffer and event leak"),
    ("MTL4CommandAllocator.h", "the header the rule comes from is no longer named where the rule is implemented"),
):
    if needle not in ring_source:
        raise SystemExit("cold-probe harness: " + why)
# Section 106's rule, as a property of the file: the frame's lifetime is device-owned, and a static native
# handle would be a second lifetime reaching across sessions. The check is on fields - a declaration that ends
# in `=` or `;` - so the factory that returns a ring is not mistaken for one. What may be static is the
# selector cache: a `Msg` holds a selector and a method handle, not a device's object.
if re.search(r"static\s+(?:final\s+)?(?:MemorySegment|MTL4FrameRing|MTL4ArgumentTable|MTLBuffer)\s+\w+\s*(?:=|;)",
             ring_source):
    raise SystemExit("cold-probe harness: the ring holds native state in a static, so a device teardown, a "
                     "reload or a second device could reach another session's allocators - which is what the "
                     "migration's section 106 forbids the production path to do")

ring_probe = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
              / "MTL4Probe.java").read_text(encoding="utf-8")
for needle, why in (
    ("public static boolean canReuseAllocatorSlots(",
     "the allocator-slot rule is measured nowhere, so the frame's ring would be built on a contract no run has "
     "answered"),
    ("MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT",
     "the proof does not use the ring's own frame depth, so it would be measuring some other lifetime"),
    ("ring.waits() != expectedWaits",
     "the proof does not check that the ring waited for an in-flight slot, so a ring that never waited would "
     "pass on whatever the pixels happened to hold"),
    ("ring.awaitAll()", "the proof reads its targets without waiting for the ring's submissions"),
    ("so a submission on a reused allocator",
     "a frame whose pixel is wrong on a reused slot is not reported as that, so the readback stops naming the "
     "fault"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

# And the harness's half: reported, and counted apart from the capability sequence.
for needle, why in (
    ('+ " ring=" + ring', "the harness does not print the allocator-slot answer, so a run of it leaves no "
                          "evidence"),
    ('+ " ringReason=" + ringReason', "the harness prints whether the ring passed and not why it failed"),
    ("MTL4Probe.canReuseAllocatorSlots(device)", "the harness never asks the allocator-slot proof"),
    ("ring_failures=\"$(grep -c ' ring=false ' \"$probe_log\" || true)\"",
     "the driver does not count the ring's failures, so a run cannot say how many there were"),
    ("if (( ring_failures > 0 )); then",
     "the driver counts the ring's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- several colour attachments, each with its own load, store and clear ---------------------------------
# The render pass is where an attachment's two lifetime facts become load and store actions, so it is the one
# place a mapping mistake is a wrong image rather than a slow frame. The smoke proves the mapping on the device
# by reading every slot back against the colour that slot was asked for, and by loading a slot a second time.
render_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4RenderEncoder.java")
if not render_encoder.is_file():
    raise SystemExit("cold-probe harness: MTL4RenderEncoder.java is gone, so the frame's render passes have no"
                     " implementation and the attachment mapping has nowhere to live")
render_encoder_source = render_encoder.read_text(encoding="utf-8")
for needle, why in (
    ("COLOR_ATTACHMENTS.sendPtr(descriptor)", "the pass descriptor's colour attachments are never reached"),
    ("ATTACHMENT_AT.sendPtr(attachments, index)",
     "only one attachment is ever described, so a second colour target has nowhere to go"),
    ("if (color == null || ObjC.isNil(color.texture())) {",
     "a colour slot the caller did not fill is not recognised as unused, so the loop dereferences a null Color "
     "- measured: this was a NullPointerException that killed the whole frame on Vitrail's MRT fixture, whose "
     "coverage path hands the backend unused slots before the attachment it does write"),
    ("                    continue;\n                }\n                MemorySegment attachment = ATTACHMENT_AT",
     "an unused colour slot is not left empty at its own index, so the attachments that are there would move to "
     "other slots' numbers"),
    ("SET_LOAD_ACTION.send(attachment, loadAction(color.contents(), color.clear() != null));",
     "the load action is not the mapping's answer, so a clear and a load are the same call"),
    ("SET_STORE_ACTION.send(attachment, storeAction(color.contents()));",
     "the store action is not the mapping's answer"),
    ("return contents.overwritten() ? LOAD_DONT_CARE : LOAD_LOAD;",
     "an overwritten attachment no longer skips its load, which is the traffic the fact exists to save"),
    ("return contents.readAfterwards() ? STORE_STORE : STORE_DONT_CARE;",
     "an attachment nothing reads is still stored"),
    ("ObjC.retain(encoder)",
     "the encoder is held past the pool that made it without a retain, which is a dangling handle rather than a "
     "nil check - measured as a segfault in objc_msgSend on the first message to it"),
    ("endEncoding()", "the pass has no end, so a second pass can never be opened in the same command buffer"),
    ("MTL4RenderPass.h", "the header the attachment classes come from is no longer named"),
):
    if needle not in render_encoder_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ("public static boolean canCarryColorAttachments(",
     "the frame's multi-attachment pass is measured nowhere, so the render pass's own half of the MRT smoke is "
     "an assumption"),
    ("MTL4RenderEncoder.Color.cleared(targets[slot], attachmentColor(slot))",
     "the smoke does not describe one attachment per slot, so it cannot say which slot a clear landed in"),
    ("new MTL4RenderEncoder.Color(targets[0], AttachmentContents.CARRIED, null)",
     "the smoke never loads an attachment's existing contents, which is the half of the mapping a clear cannot "
     "prove"),
    ("new AttachmentContents(false, true)", "the discard answers are never sent to the device"),
    ("clearPass.barrierForSubsequentEncoders()",
     "the pass that loads another pass's colour is not ordered against it, which section 61 forbids"),
    ("slot 1 reads ", "a clear on a reused attachment is not compared against the colour it was given"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " attachments=" + attachments', "the harness does not print the attachment smoke's answer"),
    ('+ " attachmentsReason=" + attachmentsReason', "the harness does not print why the attachment smoke failed"),
    ("MTL4Probe.canCarryColorAttachments(device)", "the harness never asks the attachment smoke"),
    ("attachment_failures=\"$(grep -c ' attachments=false ' \"$probe_log\" || true)\"",
     "the driver does not count the attachment smoke's failures"),
    ("if (( attachment_failures > 0 )); then",
     "the driver counts the attachment smoke's failures and does not fail the run on them"),
    # The drawn half of the MRT smoke, counted apart from the pass half because the two fail independently.
    ('+ " multiTarget=" + multiTarget', "the harness does not print the multi-target draw smoke's answer"),
    ('+ " multiTargetReason=" + multiTargetReason',
     "the harness does not print why the multi-target draw smoke failed"),
    ("MTL4Probe.canDrawMultipleTargets(device)", "the harness never asks the multi-target draw smoke"),
    ("multi_target_failures=\"$(grep -c ' multiTarget=false ' \"$probe_log\" || true)\"",
     "the driver does not count the multi-target draw smoke's failures"),
    ("if (( multi_target_failures > 0 )); then",
     "the driver counts the multi-target draw smoke's failures and does not fail the run on them"),
    # The depth DRAW smoke, counted apart from the depth clear: a pass that carries a depth attachment and
    # clears it says nothing about a compare function or a write.
    ('+ " depthDraw=" + depthDraw', "the harness does not print the depth draw smoke's answer"),
    ('+ " depthDrawReason=" + depthDrawReason', "the harness does not print why the depth draw smoke failed"),
    ("MTL4Probe.canDrawWithDepth(device)", "the harness never asks the depth draw smoke"),
    ("depth_draw_failures=\"$(grep -c ' depthDraw=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth draw smoke's failures"),
    ("if (( depth_draw_failures > 0 )); then",
     "the driver counts the depth draw smoke's failures and does not fail the run on them"),
    # And the sampling half of depth, counted apart from the draw.
    ('+ " depthSample=" + depthSample', "the harness does not print the depth sampling smoke's answer"),
    ('+ " depthSampleReason=" + depthSampleReason',
     "the harness does not print why the depth sampling smoke failed"),
    ("MTL4Probe.canSampleDepth(device)", "the harness never asks the depth sampling smoke"),
    ("depth_sample_failures=\"$(grep -c ' depthSample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth sampling smoke's failures"),
    ("if (( depth_sample_failures > 0 )); then",
     "the driver counts the depth sampling smoke's failures and does not fail the run on them"),
    # And the mip chain, counted on its own.
    ('+ " mipmaps=" + mipmaps', "the harness does not print the mipmap smoke's answer"),
    ('+ " mipmapsReason=" + mipmapsReason', "the harness does not print why the mipmap smoke failed"),
    ("MTL4Probe.canGenerateMipmaps(device)", "the harness never asks the mipmap smoke"),
    ("mipmap_failures=\"$(grep -c ' mipmaps=false ' \"$probe_log\" || true)\"",
     "the driver does not count the mipmap smoke's failures"),
    ("if (( mipmap_failures > 0 )); then",
     "the driver counts the mipmap smoke's failures and does not fail the run on them"),
    # And the dispatch, counted on its own.
    ('+ " compute=" + compute', "the harness does not print the compute smoke's answer"),
    ('+ " computeReason=" + computeReason', "the harness does not print why the compute smoke failed"),
    ("MTL4Probe.canDispatchCompute(device)", "the harness never asks the compute smoke"),
    ("compute_failures=\"$(grep -c ' compute=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute smoke's failures"),
    ("if (( compute_failures > 0 )); then",
     "the driver counts the compute smoke's failures and does not fail the run on them"),
    # And a kernel writing a texture, counted on its own.
    ('+ " storageImage=" + storageImage', "the harness does not print the storage-image smoke's answer"),
    ('+ " storageImageReason=" + storageImageReason',
     "the harness does not print why the storage-image smoke failed"),
    ("MTL4Probe.canWriteStorageImage(device)", "the harness never asks the storage-image smoke"),
    ("storage_image_failures=\"$(grep -c ' storageImage=false ' \"$probe_log\" || true)\"",
     "the driver does not count the storage-image smoke's failures"),
    ("if (( storage_image_failures > 0 )); then",
     "the driver counts the storage-image smoke's failures and does not fail the run on them"),
    # And the two cross-encoder dependencies, each counted on its own: a dispatch and a copy that both work say
    # nothing about whether a later encoder of another kind can see what the dispatch wrote.
    ('+ " computeSample=" + computeSample', "the harness does not print the compute-to-pass smoke's answer"),
    ('+ " computeSampleReason=" + computeSampleReason',
     "the harness does not print why the compute-to-pass smoke failed"),
    ("MTL4Probe.canSampleComputeOutput(device)", "the harness never asks the compute-to-pass smoke"),
    ("compute_sample_failures=\"$(grep -c ' computeSample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-pass smoke's failures"),
    ("if (( compute_sample_failures > 0 )); then",
     "the driver counts the compute-to-pass smoke's failures and does not fail the run on them"),
    ('+ " computeVertex=" + computeVertex', "the harness does not print the compute-to-draw smoke's answer"),
    ('+ " computeVertexReason=" + computeVertexReason',
     "the harness does not print why the compute-to-draw smoke failed"),
    ("MTL4Probe.canDrawFromComputeWrittenBuffer(device)", "the harness never asks the compute-to-draw smoke"),
    ("compute_vertex_failures=\"$(grep -c ' computeVertex=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-draw smoke's failures"),
    ("if (( compute_vertex_failures > 0 )); then",
     "the driver counts the compute-to-draw smoke's failures and does not fail the run on them"),
    # The three dependency smokes wired after that one: the copy's two boundaries and the two producers a
    # dispatch reads. Each needs its field, its invocation and a counted failure, or a run that fails one would
    # print it and exit zero.
    ('+ " copySample=" + copySample', "the harness does not print the copy-to-pass smoke's answer"),
    ('+ " copySampleReason=" + copySampleReason',
     "the harness does not print why the copy-to-pass smoke failed"),
    ("MTL4Probe.canSampleAfterCopy(device)", "the harness never asks the copy-to-pass smoke"),
    ("copy_sample_failures=\"$(grep -c ' copySample=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy-to-pass smoke's failures"),
    ("if (( copy_sample_failures > 0 )); then",
     "the driver counts the copy-to-pass smoke's failures and does not fail the run on them"),
    ('+ " copyDispatch=" + copyDispatch', "the harness does not print the copy-to-dispatch smoke's answer"),
    ('+ " copyDispatchReason=" + copyDispatchReason',
     "the harness does not print why the copy-to-dispatch smoke failed"),
    ("MTL4Probe.canDispatchSampledCopy(device)", "the harness never asks the copy-to-dispatch smoke"),
    ("copy_dispatch_failures=\"$(grep -c ' copyDispatch=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy-to-dispatch smoke's failures"),
    ("if (( copy_dispatch_failures > 0 )); then",
     "the driver counts the copy-to-dispatch smoke's failures and does not fail the run on them"),
    ('+ " renderDispatch=" + renderDispatch',
     "the harness does not print the render-to-dispatch smoke's answer"),
    ('+ " renderDispatchReason=" + renderDispatchReason',
     "the harness does not print why the render-to-dispatch smoke failed"),
    ("MTL4Probe.canDispatchSampledRender(device)", "the harness never asks the render-to-dispatch smoke"),
    ("render_dispatch_failures=\"$(grep -c ' renderDispatch=false ' \"$probe_log\" || true)\"",
     "the driver does not count the render-to-dispatch smoke's failures"),
    ("if (( render_dispatch_failures > 0 )); then",
     "the driver counts the render-to-dispatch smoke's failures and does not fail the run on them"),
    # And the chain of two dispatches, which is a different question from either producer above.
    ('+ " computeChain=" + computeChain', "the harness does not print the compute-to-compute smoke's answer"),
    ('+ " computeChainReason=" + computeChainReason',
     "the harness does not print why the compute-to-compute smoke failed"),
    ("MTL4Probe.canDispatchAfterDispatch(device)", "the harness never asks the compute-to-compute smoke"),
    ("compute_chain_failures=\"$(grep -c ' computeChain=false ' \"$probe_log\" || true)\"",
     "the driver does not count the compute-to-compute smoke's failures"),
    ("if (( compute_chain_failures > 0 )); then",
     "the driver counts the compute-to-compute smoke's failures and does not fail the run on them"),
    # And the third direction, whose failure is a write that overtook a read.
    ('+ " writeAfterRead=" + writeAfterRead',
     "the harness does not print the write-after-read smoke's answer"),
    ('+ " writeAfterReadReason=" + writeAfterReadReason',
     "the harness does not print why the write-after-read smoke failed"),
    ("MTL4Probe.canWriteAfterRead(device)", "the harness never asks the write-after-read smoke"),
    ("write_after_read_failures=\"$(grep -c ' writeAfterRead=false ' \"$probe_log\" || true)\"",
     "the driver does not count the write-after-read smoke's failures"),
    ("if (( write_after_read_failures > 0 )); then",
     "the driver counts the write-after-read smoke's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the drawn half of MRT, where the probe's own contract is the readback -------------------------------
# The pass half describes four attachments and reads them back slot by slot after four clears. What it cannot
# say is whether one draw's four fragment outputs are routed to the four slots the pass describes: a pipeline
# that carried the stage as one output, and a slot order that is permuted, both pass the clear smoke. So the
# drawn smoke is pinned on the three things that make it a measurement rather than a call count - four formats
# on the pipeline, one draw, and an exact per-slot comparison of both corners.
engine_probe = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                / "MTL4Probe.java")
if not engine_probe.is_file():
    raise SystemExit("cold-probe harness: MTL4Probe.java is gone, so the smoke the harness prints an answer for "
                     "does not exist")
engine_probe_source = engine_probe.read_text(encoding="utf-8")
if "public static boolean canDrawMultipleTargets(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the multi-target draw smoke is gone, so the harness's multiTarget field "
                     "would report a call that is not there")
mrt_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawMultipleTargets("):]
mrt_probe = mrt_probe[:mrt_probe.index("private static float[] mrtClearColor()")]
for needle, why in (
    ("MTLBuiltinPipelines.buildPipelineForProbe(MULTI_TARGET_MSL, \"metallum_mrt_probe_vs\",",
     "the multi-target smoke no longer builds its pipeline from the four-output MSL"),
    ("\"metallum_mrt_probe_fs\", formats)",
     "the multi-target smoke builds a pipeline with something other than one format per slot"),
    ("long[] formats = new long[slots];", "the pipeline is given no format a slot"),
    ("BEGIN.send(buffer, allocator);",
     "the multi-target smoke never begins its command buffer, and a render encoder created on a buffer that "
     "was not begun is a SIGSEGV inside IOGPU's own IOGPUDeviceGetNextGlobalTraceId rather than a refused call "
     "- measured, and it is the fault this smoke was first written with"),
    ("DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L)",
     "the multi-target smoke does not draw the fullscreen triangle, which is the only thing that can put a "
     "value in a slot"),
    ("for (long[] at : new long[][]{{0L, 0L}, {last, last}})",
     "only one pixel a slot is read, so a draw that covered part of a target passes"),
    ("if (!matches(pixel, EXPECTED_MRT_PIXELS[slot]))",
     "the multi-target readback is not compared against the value that slot's fragment output writes"),
):
    if needle not in mrt_probe:
        raise SystemExit("cold-probe harness: " + why)
if "DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L, 1L, 0L)" in mrt_probe:
    raise SystemExit("cold-probe harness: the multi-target smoke draws with the engine encoder's five-argument "
                     "selector, which this probe's drawPrimitives:vertexStart:vertexCount: is not - the extra "
                     "arguments land in registers the selector never reads")
for needle, why in (
    ("MTL4RenderEncoder.Color[] withUnused = {", "the attachment smoke no longer describes an unused slot"),
    ("                    null,\n", "the attachment smoke has no unused slot in the array it describes"),
    ('"the unused-slot pass"', "the attachment smoke's unused-slot pass has no name, so a refusal from it would "
                               "not say which pass"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canDrawWithDepth(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the depth draw smoke is gone, so the harness's depthDraw field would "
                     "report a call that is not there")
depth_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawWithDepth("):]
depth_probe = depth_probe[:depth_probe.index("private static float[] depthClearColor()")]
for needle, why in (
    ("MTLBuiltinPipelines.depthStencilStateForProbe(MTLCompareFunction.Less, true)",
     "the depth smoke no longer asks for a less-than compare with writing enabled, so a depth buffer that "
     "rejected everything or wrote nothing would pass it"),
    ("setDepthStencilState(depthState)",
     "the depth smoke never assigns the depth-stencil state to the encoder, so the compare it asks for is "
     "never applied"),
    ("new MTL4RenderEncoder.Depth(depth, 1.0)", "the depth smoke's pass carries no depth attachment"),
    ("DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L);\n            "
     "DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 3L, 3L);",
     "the depth smoke no longer draws the near triangle before the far one, and the order is what makes the "
     "overlap a test of the compare rather than of the draw order"),
    ("MTLTexture.bytes(target, pixel, 4L, 8L, 32L, 1L, 1L);",
     "the overlap pixel is not the one inside both triangles - the failure this smoke was first written with, "
     "which reported a depth compare that had never been asked to reject anything"),
    ("float overlapDepth = pixel.get(JAVA_FLOAT, 0L);",
     "the depth buffer is not read at the overlap, so a compare that rejected the later draw without writing "
     "the winner would pass"),
    ("float farDepth = pixel.get(JAVA_FLOAT, 0L);",
     "the depth buffer is not read where only the far triangle is, so a pass whose compare rejected everything "
     "would pass"),
    ("MTLPixelFormat.Depth32Float.value)",
     "the depth smoke's pipeline declares no depth format, and a pipeline that declares none has no depth test "
     "to apply whatever state the encoder is given"),
):
    if needle not in depth_probe:
        raise SystemExit("cold-probe harness: " + why)
if "releaseIfPresent(depthState);" in depth_probe:
    raise SystemExit("cold-probe harness: the depth smoke releases the depth-stencil state, which is cached and "
                     "shared with the engine's own clears - measured as a SIGSEGV inside objc_msgSend with the "
                     "selector `release` on the next probe of a warm process, which is the fault only the "
                     "repeated-probe population can see")
if "The depth-stencil state is NOT released" not in depth_probe:
    raise SystemExit("cold-probe harness: the reason the depth-stencil state is not released is not written "
                     "down, so the next reader will release it again")
# And the state itself: the compare and the write decision have to be the caller's, all the way to the
# descriptor. A probe whose state silently wrote nothing would pass a smoke that only reads colour back.
builtin = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "MTLBuiltinPipelines.java")
if not builtin.is_file():
    raise SystemExit("cold-probe harness: MTLBuiltinPipelines.java is gone, so the probe has no built-in "
                     "pipelines and no depth-stencil state factory")
builtin_source = builtin.read_text(encoding="utf-8")
for needle, why in (
    ("return ensureDepthStencilState(compareFunction, writeDepth);",
     "the probe's depth-stencil state factory does not forward the caller's compare and write decision"),
    ("descriptor.depthWriteEnabled(writeDepth);",
     "the depth-stencil state is built without the write decision, so a caller asking for depth writes gets a "
     "state that writes nothing"),
    ("descriptor.depthCompareFunction(compareOp);",
     "the depth-stencil state is built without the caller's compare function"),
):
    if needle not in builtin_source:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canSampleDepth(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the depth sampling smoke is gone, so the harness's depthSample field "
                     "would report a call that is not there")
sample_probe = engine_probe_source[engine_probe_source.index("public static boolean canSampleDepth("):]
sample_probe = sample_probe[:sample_probe.index("private static float[] depthClearColor()")]
for needle, why in (
    ("newSampledDepthTarget(device)",
     "the depth the reader samples is created without the ShaderRead bit, and a texture with only the "
     "render-target bit is refused as a sample source by the driver"),
    ("new MTL4RenderEncoder.Depth(depth, SAMPLE_DEPTH_CLEAR)",
     "the writer does not clear the depth attachment it is about to draw over"),
    ("barrierForSubsequentEncoders()",
     "the whole point of the smoke is a dependency between two passes and no barrier is encoded, so the reader "
     "has nothing ordering it against the writer"),
    ("table = MTL4ArgumentTable.create(device, 0L, 1L, 1L);",
     "the reader has no one-texture, one-sampler table to sample the depth through"),
    ("table.texture(depth)", "the depth texture is never put in the reader's table"),
    ("setArgumentTable(table, STAGE_FRAGMENT)",
     "the reader's table is never assigned to the fragment stage"),
    ("MTLTexture.bytes(depth, pixel, 4L, x, y, 1L, 1L);",
     "the depth buffer's own value is not read, so a failure cannot say what the pass wrote"),
    ("MTLTexture.bytes(readerTarget, pixel, 4L, x, y, 1L, 1L);",
     "the value the reader's shader wrote is not read back, so the smoke is about the buffer and not about "
     "sampling it"),
    ("Math.abs(read - expectedPixel) > 1",
     "the sampled depth is compared with no tolerance at all, which the eight-bit conversion of a float depth "
     "cannot meet - or with a tolerance wide enough to hide the quarter-range difference the smoke looks for"),
    ("releaseIfPresent(sampler);",
     "the sampler the smoke makes is never released, so a session of probes leaks one sampler each time"),
):
    if needle not in sample_probe:
        raise SystemExit("cold-probe harness: " + why)
# Scoped to the helper, because the same two bits are set by another smoke's source texture: a pin that read the
# whole file would be satisfied by that call site while the depth texture lost its readability.
if "private static MemorySegment newSampledDepthTarget(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the shader-readable depth target helper is gone, so the smoke's depth "
                     "texture is whatever the writer's helper makes - which has no ShaderRead bit")
sampled_depth_helper = engine_probe_source[
    engine_probe_source.index("private static MemorySegment newSampledDepthTarget("):]
sampled_depth_helper = sampled_depth_helper[:sampled_depth_helper.index("/**")]
for needle, why in (
    ("descriptor.pixelFormat(MTLPixelFormat.Depth32Float);",
     "the sampled depth target is not a Depth32Float texture"),
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ);",
     "the sampled depth target's usage bits are not both set, so the texture a pass wrote cannot be sampled by "
     "the pass after it"),
):
    if needle not in sampled_depth_helper:
        raise SystemExit("cold-probe harness: " + why)
if "public static boolean canGenerateMipmaps(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the mipmap smoke is gone, so the harness's mipmaps field would report "
                     "a call that is not there")
mip_probe = engine_probe_source[engine_probe_source.index("public static boolean canGenerateMipmaps("):]
mip_probe = mip_probe[:mip_probe.index("/** The depth smoke's colour clear")]
for needle, why in (
    ("newMipmappedTarget(device)", "the mipmap smoke's texture is not one with a chain to generate"),
    ("resident.add(checker.handle())", "the source buffer is not declared resident before the copy"),
    ("resident.add(mips)", "the destination texture is not declared resident before the copy"),
    ("ADD_RESIDENCY_SET.send(queue, resident.handle());",
     "the residency set is never handed to the queue, so nothing declares what the copy touches"),
    ("resident.close()", "the residency set the smoke makes is never released"),
    ("copies.copyBufferToTexture(checker.handle(), 0L, row, row * TARGET_SIZE, TARGET_SIZE,",
     "level 0 is not filled from the checkerboard, so the chain has nothing to be generated from"),
    ("mips, 0L, 1L, 0L, 0L, 0L)", "level 1 is not pre-filled, so a generation that did nothing would pass"),
    ("mips, 0L, 2L, 0L, 0L, 0L)", "level 2 is not pre-filled, so a generation that did nothing would pass"),
    ("copies.generateMipmaps(mips)",
     "the generation is never asked for, so the smoke would read levels nobody wrote"),
    ("MTLTexture.bytes(mips, pixel, 4L, at / 2L, at / 2L, 1L, 1L, level);",
     "the levels above 0 are not read from their own mip level, so the smoke cannot see a chain at all"),
    ("Math.abs(red - CHECKER_AVERAGE) > 1 || Math.abs(blue - CHECKER_AVERAGE) > 1",
     "a generated level is not compared against the box average of the level below it"),
    ("if (red == MIP_PREFILLED) {",
     "the value the level was pre-filled with is not refused, so a generation that did nothing could pass on a"
     " coincidence"),
    ("MTLTexture.bytes(mips, pixel, 4L, 33L, 32L, 1L, 1L, 0L);",
     "the checkerboard's neighbouring texel is not read, so the two values the average comes from are not both"
     " proven to be there"),
):
    if needle not in mip_probe:
        raise SystemExit("cold-probe harness: " + why)
# The texture's own level count, scoped to its helper: it is the property the smoke exists for.
if "private static MemorySegment newMipmappedTarget(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the mipmapped target helper is gone, so the smoke's texture is one with"
                     " no chain whatever it asks for")
mip_helper = engine_probe_source[engine_probe_source.index("private static MemorySegment newMipmappedTarget("):]
mip_helper = mip_helper[:mip_helper.index("/**")]
if "descriptor.mipmapLevelCount(MIP_LEVELS);" not in mip_helper:
    raise SystemExit("cold-probe harness: the texture the mipmap smoke generates has one level, so there is no"
                     " chain to generate")
# --- the dispatch itself, where the probe's own kernel is the contract ----------------------------------
if "public static boolean canDispatchCompute(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the compute dispatch smoke is gone, so the harness's compute field "
                     "would report a call that is not there")
compute_probe = engine_probe_source[engine_probe_source.index("public static boolean canDispatchCompute("):]
compute_probe = compute_probe[:compute_probe.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ('device.newFunction(COMPUTE_MSL, "metallum_compute_probe")',
     "the dispatch smoke builds no pipeline from the probe's own kernel"),
    ("device.newComputePipelineState(function)",
     "the kernel is never made into a compute pipeline, so there is nothing to dispatch"),
    ("table.address(out.gpuAddress(), 0L)", "the output buffer is not bound by address"),
    ("table.address(bias.gpuAddress(), 1L)", "the uniform the kernel adds is not bound by address"),
    ("resident.add(out.handle())", "the output buffer is not declared resident before the dispatch"),
    ("resident.add(bias.handle())", "the uniform buffer is not declared resident before the dispatch"),
    ("dispatch.setComputePipelineState(pipeline)", "the pipeline is never handed to the encoder"),
    ("dispatch.setArgumentTable(table)", "the table is never handed to the encoder"),
    ("dispatch.dispatchThreadgroups(1L, 1L, 1L, COMPUTE_THREADS, 1L, 1L)",
     "the dispatch is never encoded, so nothing runs"),
    ("outWords.set(JAVA_INT, index * 4L, COMPUTE_SENTINEL);",
     "the output buffer is not pre-filled with a sentinel, so a dispatch that did nothing could pass on"
     " whatever a fresh buffer holds"),
    ("if (read == COMPUTE_SENTINEL) {",
     "the sentinel is not refused afterwards, so the pre-fill proves nothing"),
    ("int expected = (int) (index * 2L) + COMPUTE_BIAS;",
     "each thread's output is not compared against its own index's formula, so a grid of the wrong shape or one"
     " thread's answer repeated could pass"),
):
    if needle not in compute_probe:
        raise SystemExit("cold-probe harness: " + why)
# --- a kernel writing a texture, where a table per dispatch is the mechanism ------------------------------
if "public static boolean canWriteStorageImage(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the storage-image smoke is gone, so the harness's storageImage field "
                     "would report a call that is not there")
storage_probe = engine_probe_source[engine_probe_source.index("public static boolean canWriteStorageImage("):]
storage_probe = storage_probe[:storage_probe.index("private static void writeColor(")]
for needle, why in (
    ("descriptor.usage(USAGE_SHADER_WRITE | USAGE_SHADER_READ);",
     "the storage smoke's texture has no shader-write bit, so the driver refuses it as a storage image"),
    ("table.texture(texture, 0L)", "the image is not bound through the table by resource id"),
    ("table.address(first.gpuAddress(), 0L)", "the first colour is not bound by address"),
    ("secondTable = MTL4ArgumentTable.create(device, 1L, 1L, 0L);",
     "the second dispatch has no table of its own, so the smoke is back on the re-pointed shape whose green is"
     " phase-dependent - measured"),
    ("if (secondTable == null || !secondTable.texture(texture, 0L)\n"
     "                    || !secondTable.address(second.gpuAddress(), 0L)",
     "the second dispatch's table is not given the image by resource id and the second colour by address"),
    ("secondDispatch = MTL4ComputeEncoder.open(device, buffer, \"the storage smoke's second dispatch\");",
     "the second dispatch has no encoder of its own, which is the measured safe shape: a second table handed to"
     " the same encoder is not reliably honoured, and with the copy dependency smoke in the suite the smoke then"
     " failed on alternate warm probes"),
    ("|| !secondDispatch.setComputePipelineState(pipeline)\n"
     "                    || !secondDispatch.setArgumentTable(secondTable)) {",
     "the second dispatch's own encoder is not given the pipeline and its table, so the smoke would measure"
     " nothing"),
    ("secondDispatch.endEncoding();",
     "the second dispatch's encoder is never ended, so its work would not be submitted"),
    ("if (secondDispatch != null) {",
     "the second dispatch's encoder is never released, so every probe leaks one - and releasing one before the"
     " commit is what crashed the driver when that was tried"),
    ("if (secondTable != null) {",
     "the second dispatch's table is never released, so every probe of this smoke leaks one"),
    ("for (long[] at : new long[][]{{0L, 0L}, {STORAGE_EDGE - 1L, STORAGE_EDGE - 1L}, {1L, 3L}})",
     "the readback does not cover the corners and the middle, so a dispatch that wrote one texel could pass"),
    ("if (!matches(pixel, STORAGE_SECOND_PIXEL)) {",
     "the readback is not compared against the colour the second dispatch wrote"),
):
    if needle not in storage_probe:
        raise SystemExit("cold-probe harness: " + why)
# The kernel itself lives above the method, so it is pinned against the file rather than the slice.
for needle, why in (
    ("kernel void metallum_storage_write_probe(texture2d<float, access::write> image [[texture(0)]],",
     "the storage kernel takes no writable image at the texture slot the table binds"),
    ("constant float4& colour [[buffer(0)]]",
     "the storage kernel does not read its colour from a buffer, so the reading cannot say which buffer the table"
     " held"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

# --- the two cross-encoder dependencies, where the API's ordering is what the smoke proves ----------------
# Both are new kinds of question: every smoke above establishes one encoder's own capability, and these two ask
# whether what one encoder wrote is visible to an encoder of another kind in the same command buffer. The
# producer barrier is the answer, so a pin checks it is encoded rather than inferred from "one command buffer".
for smoker, stage, why_gone in (
    ("canSampleComputeOutput", "computeSample",
     "the compute-to-pass dependency smoke is gone, so the harness's computeSample field would report a call"
     " that is not there"),
    ("canDrawFromComputeWrittenBuffer", "computeVertex",
     "the compute-to-draw dependency smoke is gone, so the harness's computeVertex field would report a call"
     " that is not there"),
):
    if "public static boolean " + smoker + "(" not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why_gone)

sample_probe = engine_probe_source[engine_probe_source.index("public static boolean canSampleComputeOutput("):]
sample_probe = sample_probe[:sample_probe.index("public static boolean canDrawFromComputeWrittenBuffer(")]
for needle, why in (
    ("dispatch.barrierForSubsequentEncoders()",
     "the compute-to-pass smoke samples what a dispatch wrote without encoding the producer barrier, so it would"
     " be proving that one command buffer happened to be enough - which section 61 forbids"),
    ("if (!dispatch.barrierForSubsequentEncoders()) {",
     "the producer barrier is sent without asking whether the encoder answers it"),
    ("if (!dispatch.dispatchThreads(STORAGE_EDGE, STORAGE_EDGE, 1L, STORAGE_EDGE, STORAGE_EDGE, 1L)) {",
     "the dispatch into the storage image is not encoded, so the pass has nothing to see"),
    ("descriptor.usage(USAGE_SHADER_WRITE | USAGE_SHADER_READ);",
     "the image both encoders touch does not declare both usages, so one of them would be refused"),
    ("!sampledTable.texture(image, 0L)", "the image is not bound to the pass's table by resource id"),
    ("!sampledTable.sampler(sampler, 0L)", "the sampler is not bound to the pass's table"),
    ("MTLTexture.bytes(image, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the dispatch's own output is not read back, so a kernel that never wrote and a sample that never arrived"
     " would be one failure"),
    ("if (!matches(pixel, COMPUTE_IMAGE_PIXEL)) {",
     "the image is not compared against the colour the dispatch wrote"),
    ("if (matches(pixel, CLEAR_PIXEL)) {",
     "a target holding the pass's clear colour is not named as the dependency failure it is, so an unordered"
     " sample would read as a wrong colour"),
    ("for (long[] at : new long[][]{{0L, 0L}, {TARGET_SIZE - 1L, TARGET_SIZE - 1L}, {17L, 41L}})",
     "the target is read at one place only, so a sample that landed in one corner could pass"),
):
    if needle not in sample_probe:
        raise SystemExit("cold-probe harness: " + why)

vertex_probe = engine_probe_source[engine_probe_source.index("public static boolean canDrawFromComputeWrittenBuffer("):]
vertex_probe = vertex_probe[:vertex_probe.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("sentinel.set(JAVA_FLOAT, word * 4L, 0.0f);",
     "the vertex buffer is not pre-filled with a degenerate triangle, so a draw that ran before the dispatch's"
     " data arrived could still paint pixels"),
    ("dispatch.barrierForSubsequentEncoders()",
     "the compute-to-draw smoke draws what a dispatch wrote without encoding the producer barrier"),
    ("if (!dispatch.dispatchThreadgroups(1L, 1L, 1L, COMPUTE_THREADS, 1L, 1L)) {",
     "the dispatch that fills the vertex buffer is not encoded"),
    ("|| !computeTable.address(vertices.gpuAddress(), 0L)",
     "the same buffer is not bound to the dispatch's table by address"),
    ("|| !vertexTable.address(vertices.gpuAddress(), 16L, 0L)) {",
     "the same buffer is not bound to the draw's table as vertex data with its stride, so the draw could not"
     " read what the dispatch wrote"),
    ("pass.setArgumentTable(vertexTable, STAGE_VERTEX)",
     "the vertex table is not handed to the drawing pass"),
    ("float firstX = written.get(JAVA_FLOAT, 0L);",
     "the buffer is not read back on the CPU, so a dispatch that never wrote and a draw that never read would"
     " be one failure"),
    ("if (!matches(pixel, EXPECTED_VERTEX_PIXEL)) {",
     "the drawn pixel is not compared against the colour that comes out of the buffer's own components"),
):
    if needle not in vertex_probe:
        raise SystemExit("cold-probe harness: " + why)
# The kernel that fills the buffer, pinned against the file: it writes the same three corners the vertex smoke's
# own literal uses, so the colour the draw passes through is read from the buffer and not from the shader.
for needle, why in (
    ("kernel void metallum_vertex_write_probe(device float4* vertices [[buffer(0)]],",
     "the vertex-writing kernel takes no device buffer at the slot the table binds"),
    ("vertices[id] = float4(corners[id], 0.25, 0.5);",
     "the kernel does not write the colour the vertex stage carries through, so a pixel could not say the draw"
     " read this buffer"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

# --- the reproducer, which is a mode of this harness and a laboratory rather than a smoke -----------------
# Round 41's fault - a later dispatch through a table reading the first dispatch's colour after a texture copy -
# has a deterministic reproducer: round 41 measured it in the suite, and this artifact is what keeps it
# runnable without the suite. It is compiled against the same classpath and run by the same script, so it
# cannot measure another branch's classes and needs no second build path.
for needle, why in (
    ("--repro) repro_rounds=\"$2\"; shift 2 ;;", "the harness has no reproducer mode"),
    ("--variant) variant=\"$2\"; shift 2 ;;", "the harness cannot select a variant of the reproducer"),
    ("CopyThenDispatchRepro.java", "the reproducer is not compiled, so the mode would run nothing"),
    ("CopyThenDispatchRepro \"$repro_rounds\" \"$variant\"",
     "the reproducer is run without its rounds or its variant, so a run could not say which shape it asked"),
    ("variant $variant", "the harness does not say which variant it ran"),
    ("if grep -q 'storageFailures=0 ' \"$repro_out\"; then",
     "the reproducer's answer is not read, so a run's exit code could not say whether it reproduced"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

REPRO = ROOT / "tools" / "metal4-cold-probe" / "CopyThenDispatchRepro.java"
if not REPRO.is_file():
    raise SystemExit("cold-probe harness: the copy-then-dispatch reproducer is gone, so the fault it made "
                     "deterministic has no artifact again")
repro = REPRO.read_text(encoding="utf-8")
for needle, why in (
    ("boolean storage = MTL4Probe.canWriteStorageImage(device);",
     "the reproducer does not run the victim smoke, so it is not reproducing the measured fault"),
    ("boolean storageAgain = MTL4Probe.canWriteStorageImage(device);",
     "the reproducer does not run the victim twice, so a state a second call clears cannot be told from one "
     "that persists"),
    ("String copyReason = trigger(device, shape);",
     "the reproducer never runs the trigger, so every variant would be clean and mean nothing"),
    ("copy.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, HALF, HALF, 1L,\n"
     "                                        into, 0L, 0L, HALF, 0L, 0L);",
     "the trigger's texture-to-texture region copy is gone, and that copy is what every variant measures"),
    ("case \"no-copy\" ->", "the variant that removes the copy command is gone, so the one control that "
     "separates the copy from its surroundings cannot be run"),
    ("case \"buffer-copy\" ->", "the variant that copies buffers instead of textures is gone, so nothing "
     "separates a texture copy from a copy of any kind"),
    ("case \"separate-commit\" ->", "the variant that gives the copy its own command buffer is gone, so "
     "\"one command buffer\" cannot be ruled out"),
    ("case \"copy-to-unbound\" ->", "the variant whose copy target no table names is gone, so the copy's "
     "destination being a bound resource cannot be ruled out"),
    ("case \"no-residency\" ->", "the variant that declares nothing is gone, so residency cannot be ruled out"),
    ("case \"textures-released-last\" ->", "the variant that hands the textures back after the command buffer "
     "is gone, so a release-order fault cannot be ruled out"),
    ("case \"plain-destination\" ->", "the variant whose textures are not render targets is gone, so the usage "
     "bits cannot be ruled out"),
    ("M4_REPRO SUMMARY variant=", "the reproducer prints no summary, so a shell cannot read its answer"),
):
    if needle not in repro:
        raise SystemExit("cold-probe harness: " + why)
# The two release orders have to be different code, or the variant is a comment.
release_orders = repro.split("if (shape.texturesReleasedLast()) {")
if len(release_orders) != 2 or release_orders[1].index("release(source);") > \
        release_orders[1].index("} else {"):
    raise SystemExit("cold-probe harness: the reproducer's two release orders are the same code, so the "
                     "variant that reorders them measures nothing")

# The own victim and its modes: the mechanism this artifact exists to measure is "one table object re-pointed
# and handed to the same encoder twice", so a pin checks the victim can be asked in that shape and in the two
# shapes that are safe, or the measured answer would be unfalsifiable.
for needle, why in (
    ("private static String ownVictim(final MTLDevice device, final String ownMode)",
     "the reproducer has no victim of its own, so the phase sensitivity it exposed cannot be measured apart "
     "from the probe's smoke"),
    ("if (ownMode.equals(\"one-encoder\")) {",
     "the unsafe shape - one encoder, one table re-pointed - cannot be asked for"),
    ("} else if (ownMode.equals(\"fresh-table\")) {",
     "the fresh-table control is gone, so the workaround this round measured has no experiment"),
    ("if (ownMode.equals(\"two-commits\") && index == 1) {",
     "the commit-per-dispatch control is gone"),
    ("private static boolean repoint(final MTL4ComputeEncoder dispatch, final MTL4ArgumentTable table,",
     "the re-point is not a step of its own, so the fault's shape is not expressible"),
    ("long signalled = 0L;",
     "the own victim signals one event value for two commits, so its second wait returns immediately and its "
     "readback is a race rather than a measurement"),
    ("if (matches(seen, OWN_COLOURS[0])) {",
     "the own victim does not say which colour survived, so a stale binding and a dropped command read alike"),
):
    if needle not in repro:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ("--own) own_mode=\"$2\"; shift 2 ;;", "the harness cannot select the own victim's mode"),
    ("CopyThenDispatchRepro \"$repro_rounds\" \"$variant\" \"$own_mode\"",
     "the own victim's mode does not reach the reproducer"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the dependency smokes wired after the compute ones: the copy's boundaries and the read side ------------
# `canSampleAfterCopy` (a pass, a copy, a pass that samples), `canDispatchSampledCopy` and
# `canDispatchSampledRender` (a dispatch that samples what a pass or a copy wrote) were wired into the harness
# before they had pins. What is pinned here is what makes each of them a measurement: the barriers at every
# boundary, the readbacks that separate "never wrote" from "never read", and - for the two dispatch smokes - the
# safe shape the storage smoke measured, a table AND an encoder for the dispatch itself.
for smoker, why in (
    ("canSampleAfterCopy", "the copy-to-pass smoke is gone, so its harness field would report a call that is not"
     " there"),
    ("canDispatchSampledCopy", "the copy-to-dispatch smoke is gone"),
    ("canDispatchSampledRender", "the render-to-dispatch smoke is gone"),
):
    if "public static boolean " + smoker + "(" not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

copy_boundaries = engine_probe_source[engine_probe_source.index("public static boolean canSampleAfterCopy("):]
copy_boundaries = copy_boundaries[:copy_boundaries.index("private static float[] colorOf(")]
for needle, why in (
    ("copy.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, COPY_HALF, COPY_HALF, 1L,\n"
     "                    destination, 0L, 0L, COPY_HALF, 0L, 0L)",
     "the copy smoke does not encode the region it reads back"),
    ("if (!copy.barrierForSubsequentEncoders()) {",
     "the copy smoke's copy does not barrier before the pass that samples its output"),
    ("MTLTexture.bytes(destination, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the copy smoke does not read the destination's untouched half, so a copy that overwrote everything would"
     " pass"),
    ("MTLTexture.bytes(target, pixel, 4L, COPY_HALF + 8L, 8L, 1L, 1L);",
     "the copy smoke never reads the copied half through the sampler, which is the dependency it exists for"),
):
    if needle not in copy_boundaries:
        raise SystemExit("cold-probe harness: " + why)

sampled = engine_probe_source[engine_probe_source.index("private static boolean sampledProducer("):]
sampled = sampled[:sampled.index("/** How many levels the mipmap smoke asks for")]
# The kernel lives above the method, so it is pinned against the file rather than the slice.
for needle, why in (
    ("kernel void metallum_sampling_probe(texture2d<float, access::sample> source [[texture(0)]],",
     "the sampling kernel does not take the texture it reads at the slot the table binds"),
    ("sampler nearest [[sampler(0)]],", "the sampling kernel has no sampler, so it cannot sample"),
    ("device float4* out [[buffer(0)]],", "the sampling kernel writes nowhere the smoke can read back"),
    ("source.sample(", "the kernel does not sample, so the smoke measures no read at all"),
):
    if needle not in engine_probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ("resident.add(out.handle())", "the dispatch's output buffer is not declared resident, and an undeclared"
     " resource makes a dispatch do nothing at all - measured"),
    ("|| !table.address(out.gpuAddress(), 0L)) {",
     "the output buffer is not bound to the dispatch's table by address"),
    ("if (!pass.barrierForSubsequentEncoders()) {",
     "the producer pass does not barrier before the encoder that reads its output"),
    ("dispatch = MTL4ComputeEncoder.open(device, buffer, \"the \" + stage + \" smoke's dispatch\");",
     "the sampling dispatch has no encoder of its own, which is the measured safe shape"),
    ("if (!dispatch.barrierForSubsequentEncoders()) {",
     "the dispatch's encoder does not barrier, so whatever encoder follows it has no encoded dependency"),
    ("words.set(JAVA_FLOAT, slot * 16L + channel * 4L, SAMPLING_SENTINEL);",
     "the output buffer is not pre-filled with a sentinel, so a dispatch that never ran could pass on whatever"
     " a fresh buffer holds"),
    ("still holds the sentinel it was", "the sentinel is not refused afterwards, so the pre-fill proves nothing"),
    ("MemorySegment written = out.contents().reinterpret(SAMPLING_SLOTS * 16L);\n"
     "            for (long slot = 0; slot < SAMPLING_SLOTS; slot++) {",
     "the readback does not cover every sample the dispatch wrote - and the needle carries the line above it,"
     " because the pre-fill loop is the same text and would satisfy a bare one"),
    ("if (!matches(seen, COPY_SOURCE_PIXEL)) {",
     "the samples are not compared against the colour the producer wrote, so a wrong read could pass"),
):
    if needle not in sampled:
        raise SystemExit("cold-probe harness: " + why)
if "return sampledProducer(device, true, \"copyDispatch\");" not in engine_probe_source \
        or "return sampledProducer(device, false, \"renderDispatch\");" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the two producer-to-dispatch smokes no longer differ in their producer,"
                     " so one of section 60's cases is measured twice and the other not at all")

# --- the chain of two dispatches, which is the shape a pack's own compute chain is made of -------------------
if "public static boolean canDispatchAfterDispatch(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the compute-to-compute smoke is gone, so the harness's computeChain "
                     "field would report a call that is not there")
chain = engine_probe_source[engine_probe_source.index("public static boolean canDispatchAfterDispatch("):]
chain = chain[:chain.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("writerFunction = device.newFunction(STORAGE_WRITE_MSL, \"metallum_storage_write_probe\");",
     "the writing dispatch does not use the storage-write kernel, so nothing writes the image"),
    ("readerFunction = device.newFunction(SAMPLING_DISPATCH_MSL, \"metallum_sampling_probe\");",
     "the reading dispatch does not sample, so the chain measures no read"),
    ("!writerTable.address(colour.gpuAddress(), 0L) || !writerTable.texture(image, 0L)",
     "the writer's table is not given the colour and the image"),
    ("|| !readerTable.address(out.gpuAddress(), 0L) || !readerTable.texture(image, 0L)",
     "the reader's table is not given its output buffer and the same image"),
    ("|| !resident.add(out.handle())", "the reader's output buffer is not declared resident"),
    ("writer = MTL4ComputeEncoder.open(device, buffer, \"the compute chain's writer\");",
     "the writing dispatch has no encoder of its own"),
    ("reader = MTL4ComputeEncoder.open(device, buffer, \"the compute chain's reader\");",
     "the reading dispatch has no encoder of its own, so the two share one - the shape that loses a dispatch"),
    ("if (!writer.barrierForSubsequentEncoders()) {",
     "the writer does not barrier, so the reader has no encoded dependency on it"),
    ("if (!reader.barrierForSubsequentEncoders()) {",
     "the reader does not barrier before whatever follows the chain"),
    ("if (!matches(seen, COPY_SOURCE_PIXEL)) {",
     "the samples are not compared against the colour the other dispatch wrote"),
    ('" still holds the"', "the sentinel is not refused, so a chain that never ran could pass"),
):
    if needle not in chain:
        raise SystemExit("cold-probe harness: " + why)

# --- write-after-read, the direction whose failure is a write that overtook a read --------------------------
if "public static boolean canWriteAfterRead(" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the write-after-read smoke is gone, so the harness's writeAfterRead "
                     "field would report a call that is not there")
war = engine_probe_source[engine_probe_source.index("public static boolean canWriteAfterRead("):]
war = war[:war.index("/** How many levels the mipmap smoke asks for")]
for needle, why in (
    ("descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ | USAGE_SHADER_WRITE);",
     "the texture the reader samples and the writer writes does not declare all three usages, so one of the two"
     " would be refused"),
    ("|| !sampledTable.texture(texture, 0L) || !sampledTable.sampler(sampler, 0L)",
     "the reader's table is not given the texture and its sampler"),
    ("|| !writerTable.address(colour.gpuAddress(), 0L) || !writerTable.texture(texture, 0L)) {",
     "the writer's table is not given the colour and the same texture"),
    ("if (!pass.barrierForSubsequentEncoders()) {\n                    END.send(buffer);\n"
     "                    return failed(\"writeAfterRead\", \"the reader does not answer the producer barrier",
     "the reader does not barrier, so the write after it has no encoded dependency on the read"),
    ('writer = MTL4ComputeEncoder.open(device, buffer, "the write-after-read smoke\'s writer");',
     "the writing dispatch has no encoder of its own"),
    ("if (matches(pixel, WAR_WRITE_PIXEL)) {",
     "the reader's target is not checked against the colour the later write put in, which is the ordering failure"
     " this fixture exists for"),
    ("so the write was ordered before", "the ordering failure is not named as itself"),
    ("if (!matches(pixel, WAR_READ_PIXEL)) {",
     "the reader's target is not compared against what the texture held before the write"),
    ("if (!matches(pixel, WAR_WRITE_PIXEL)) {\n                    return failed(\"writeAfterRead\", \"the texture reads ",
     "the texture is not read back, so a write that never landed would pass"),
):
    if needle not in war:
        raise SystemExit("cold-probe harness: " + why)

# And the native calls themselves, where the commands live.
compute_encoder = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                   / "MTL4ComputeEncoder.java")
if not compute_encoder.is_file():
    raise SystemExit("cold-probe harness: MTL4ComputeEncoder.java is gone, so a mip chain has no command to be"
                     " generated by")
compute_source = compute_encoder.read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("generateMipmapsForTexture:", ADDRESS)',
     "the mip generation selector is not the one this SDK's MTL4ComputeCommandEncoder.h:543 declares"),
    ("if (open == null || ObjC.isNil(texture) || !responds(open, GENERATE_MIPMAPS.name())) {",
     "the generation is sent without asking whether the encoder answers it, so an encoder that does not would"
     " take the command and do nothing"),
    # The dispatch's three calls and their selectors, read off MTL4ComputeCommandEncoder.h.
    ('Msg.ofVoid("setComputePipelineState:", ADDRESS)',
     "the compute pipeline selector is not the one MTL4ComputeCommandEncoder.h:51 declares"),
    ('Msg.ofVoid("setArgumentTable:", ADDRESS)',
     "the compute argument table selector is not the one MTL4ComputeCommandEncoder.h:661 declares - and it takes"
     " no stage mask, because a dispatch has one stage"),
    ('Msg.ofVoid("dispatchThreadgroups:threadsPerThreadgroup:", ADDRESS, ADDRESS)',
     "the dispatch selector is not the one MTL4ComputeCommandEncoder.h:87 declares"),
    ("MTLSize.on(stack, groupsX, groupsY, groupsZ)",
     "the workgroup counts are not passed as an MTLSize, which is how the header declares them"),
    ("MTLSize.on(stack, localX, localY, localZ)",
     "the threads-per-threadgroup counts are not passed as an MTLSize"),
    ("if (open == null || groupsX <= 0L || groupsY <= 0L || groupsZ <= 0L",
     "a dispatch with an empty grid is sent rather than refused"),
    ("if (!responds(open, DISPATCH_THREADGROUPS.name())) {",
     "the dispatch is sent without asking whether the encoder answers it"),
    ('Msg.ofVoid("dispatchThreads:threadsPerThreadgroup:", ADDRESS, ADDRESS)',
     "the open-grid dispatch selector is not the one MTL4ComputeCommandEncoder.h:77 declares, and a texture clear"
     " whose extent is not a multiple of its threadgroup needs that form"),
    ("if (!responds(open, DISPATCH_THREADS.name())) {",
     "the open-grid dispatch is sent without asking whether the encoder answers it"),
):
    if needle not in compute_source:
        raise SystemExit("cold-probe harness: " + why)
if "EXPECTED_MRT_PIXELS = {" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the multi-target smoke has no table of the values its slots are "
                     "compared against, so the readback is a claim about nothing")
if "float4 slot3 [[color(3)]]" not in engine_probe_source:
    raise SystemExit("cold-probe harness: the four-output fragment stage no longer declares a fourth color(n) "
                     "output, so the smoke cannot tell four targets from one")
if "SET_RENDER_PIPELINE_STATE.send(pass.encoder(), pipeline);" not in mrt_probe:
    raise SystemExit("cold-probe harness: the four-output pipeline is never assigned to the pass's encoder, so "
                     "the draw would run the previous pipeline")

# The compilation chain's own answer, printed by the driver: the pipeline fixture every probe compiles through
# the Metal 4 chain. Not counted as a pass yet - the first device proof of the chain is what this line reports,
# and the round that makes it a counted smoke is the round that has a rate to count.
if 'echo "pipeline compile: $(grep -m1 -o \' compile=[^ ]*\' \"$probe_log\" | cut -c2-)"' not in script:
    raise SystemExit("cold-probe harness: the driver does not print what the compilation chain answered, so a "
                     "run of it leaves the chain's first device proof unread")

# --- a whole layout bound through one table a stage -----------------------------------------------------
# This is the new model's core and the thing that makes a draw possible: there is no per-resource setter, so a
# pass fills a table and assigns it. The pins below are the shape of that - a table per stage, the stride on the
# vertex buffer, the indices the shader declares, the draw's selector, and the two readings that make the smoke
# a measurement rather than a call count.
encoder_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4RenderEncoder.java").read_text(encoding="utf-8")
for needle, why in (
    ('Msg.ofVoid("setArgumentTable:atStages:", ADDRESS, JAVA_LONG)',
     "the encoder cannot be given a table, so nothing can be bound at all"),
    ('"drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:",',
     "the encoder has no draw, so a pass can bind everything and draw nothing"),
    ('"drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferLength:instanceCount:baseVertex:"',
     "the encoder has no indexed draw, so the engine's indexed geometry has nowhere to go"),
    ('                    + "baseInstance:",',
     "the indexed draw's selector is one argument short of the eight this SDK declares, so respondsToSelector: "
     "answers no and every indexed draw refuses - the fault a forced Metal 4 client stopped on"),
):
    if needle is not None and needle not in encoder_source:
        raise SystemExit("cold-probe harness: " + why)
# The index buffer is an ADDRESS on this model, not a bound object: that is the whole difference from Metal 3's
# indexed draw and the thing a later port of the engine's draws has to know.
if "MemorySegment.ofAddress(indexBufferAddress)" not in encoder_source:
    raise SystemExit("cold-probe harness: the indexed draw no longer passes the index buffer as an address, so "
                     "the selector's indexBuffer argument is something else than the header declares")

for needle, why in (
    ("public static boolean canBindALayout(",
     "the layout binding is measured nowhere, so the new model's core has no run behind it"),
    # Pinned with its assignment and with the plan as the source of the sizes: the same factory call appears in
    # canBindAndDraw's own table, and a table sized from literals would stop covering the slots it is given
    # without the smoke noticing.
    ("vertexTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.VERTEX),",
     "the smoke does not make a vertex table sized from the plan, so what it proves is not the plan's mapping"),
    ("fragmentTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.FRAGMENT),",
     "the smoke does not make a fragment table sized from the plan"),
    ("vertexTable.address(vertices.gpuAddress(), 16L, plan.firstVertexBufferSlot())",
     "the vertex buffer is bound without its attribute stride, or outside the plan's vertex region, so an indexed"
     " vertex read has no layout"),
    ("layoutPass.setArgumentTable(vertexTable, STAGE_VERTEX)",
     "the vertex table is never assigned to the stage that reads it"),
    ("layoutPass.setArgumentTable(fragmentTable, STAGE_FRAGMENT)",
     "the fragment table is never assigned to the stage that reads it"),
    ("layoutPass.setScissorRect(0L, 0L, TARGET_SIZE / 2L, TARGET_SIZE)",
     "the scissor is not set, so the outside-the-rectangle reading has nothing to disagree with"),
    ("the pixel outside the scissor rectangle reads ",
     "a scissor that was accepted and ignored would not be reported as that: the reading outside the rectangle "
     "is what makes the scissor a measurement"),
    ("expected to the bindings and not to a rounding question" if False else "0.25 + 0.5 is 0.75",
     "the smoke's colours are no longer explained as exact sums, which is what keeps its expected pixel a "
     "reading of the bindings and not of rounding"),
):
    if needle not in ring_probe:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " layout=" + layout', "the harness does not print the layout smoke's answer"),
    ('+ " layoutReason=" + layoutReason', "the harness does not print why the layout smoke failed"),
    ("MTL4Probe.canBindALayout(device)", "the harness never asks the layout smoke"),
    ("layout_failures=\"$(grep -c ' layout=false ' \"$probe_log\" || true)\"",
     "the driver does not count the layout smoke's failures"),
    ("if (( layout_failures > 0 )); then",
     "the driver counts the layout smoke's failures and does not fail the run on them"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the copy path, which is where this command model puts its blits ------------------------------------
# Metal 4 has no blit encoder: a copy is a compute encoder command, so the smoke and the wrapper are the only
# path a texture upload, download or region copy can take. The pins cover the selectors, the region's four
# coordinates, and the two readings that make the smoke a measurement.
compute_source = (ROOT / "src" / "main" / "java" / "com" / "metallum" / "mtl" / "metal4"
                  / "MTL4ComputeEncoder.java").read_text(encoding="utf-8")
for needle, why in (
    ('Msg.of("computeCommandEncoder", ADDRESS)',
     "the copies are not made on the command model's compute encoder, which is where they live"),
    ('"copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:"',
     "the region copy selector is gone, so a subregion copy has no command"),
    ('"copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:"',
     "the texture-to-buffer selector is gone, so the engine cannot read a texture back"),
    ('"copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:"',
     "the buffer-to-texture selector is gone, so the engine cannot upload one"),
    # The three structs are pinned with the send they belong to, because the same helpers build the origins and
    # sizes of the texture-to-buffer copy too - a bare pin would be satisfied by that call while the region copy
    # stopped passing the coordinates it was given.
    ("COPY_TEXTURE_REGION_TO_TEXTURE.send(open, source, sourceSlice, sourceLevel, origin, size, destination,\n"
     "                    destinationSlice, destinationLevel, destinationOrigin);",
     "the region copy does not send the coordinates it was given"),
    ("MemorySegment origin = MTLOrigin.on(stack, sourceX, sourceY, sourceZ);\n"
     "            MemorySegment size = MTLSize.on(stack, width, height, depth);\n"
     "            MemorySegment destinationOrigin = MTLOrigin.on(stack, destinationX, destinationY, destinationZ);",
     "the region's source origin, its size or its destination origin is not passed as the header's structs - the "
     "three together, because each helper also builds another copy's struct and a bare pin would be satisfied "
     "there"),
    ("ObjC.retain(encoder)", "the encoder is held past its autorelease pool without a retain"),
    ("barrierForSubsequentEncoders()", "a copy that reads what a pass wrote has no way to say so"),
):
    if needle not in compute_source:
        raise SystemExit("cold-probe harness: " + why)
# The declaration and the call have to agree: a selector declared with one argument too many makes the handle
# throw on invocation, which reads as "objc_msgSend failed" rather than as a nil - measured while writing this.
if 'Msg.ofVoid("copyFromTexture:toTexture:", ADDRESS, ADDRESS, ADDRESS)' in compute_source:
    raise SystemExit("cold-probe harness: the whole-texture copy selector is declared with three arguments where "
                     "the header has two, so the handle is invoked with the wrong arity")

for needle, why in (
    ("public static boolean canCopyTextureRegions(",
     "the copy path is measured nowhere, so the only route a texture upload can take has no run behind it"),
    ("copies.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, PATTERN_EDGE, PATTERN_EDGE, 1L,",
     "the smoke does not copy a subregion from a non-zero-sized source, so the four coordinates a region copy "
     "can be wrong about are not exercised"),
    ("copies.copyTextureToTexture(source, wholeTarget)", "the smoke does not make a whole-texture copy"),
    ("the region copy also wrote ", "a copy that wrote outside its region is not reported as that"),
    ("the whole-texture copy reads ", "a whole copy that lost a quadrant is not reported as that"),
):
    # The probe's own source, not the harness's: the smoke lives in MTL4Probe and the harness only asks it.
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " copy=" + copy', "the harness does not print the copy smoke's answer"),
    ('+ " copyReason=" + copyReason', "the harness does not print why the copy smoke failed"),
    ("MTL4Probe.canCopyTextureRegions(device)", "the harness never asks the copy smoke"),
    ("copy_failures=\"$(grep -c ' copy=false ' \"$probe_log\" || true)\"",
     "the driver does not count the copy smoke's failures"),
    ("if (( copy_failures > 0 )); then", "the driver counts the copy smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the depth attachment, which is the half of a frame's clears the attachments smoke does not reach -------
# The plan's depth phase is two overlapping triangles with a known winner; that needs a pipeline and a draw.
# What is pinned here is the step before it: a pass whose attachments are a colour target and a depth target,
# both loaded as cleared and both stored, and the depth texture read back as the number it was given.
for needle, why in (
    ("public static boolean canClearDepth(",
     "the depth attachment and its clear are measured nowhere, so the first thing a depth pass needs has no run"),
    ("descriptor.pixelFormat(MTLPixelFormat.Depth32Float);",
     "the smoke's depth target is not the format a frame's depth attachment is"),
    ("new MTL4RenderEncoder.Depth(depth, CLEAR_DEPTH)",
     "the smoke does not clear the depth attachment to a known value"),
    ("MTLTexture.bytes(depth, pixel, 4L, 0L, 0L, 1L, 1L);",
     "the depth texture is never read back, so the clear is asserted nowhere"),
    ("if (!(Math.abs(read - (float) CLEAR_DEPTH) <= 0.0001f)) {",
     "the depth comparison is written so that a NaN readback counts as the value that was asked for, which is a "
     "check a broken clear could pass"),
    ("the depth attachment reads ", "a depth clear that did not land is not reported as that"),
    ("return failed(\"depth\", \"a pass carrying a depth attachment could not be opened at stage \"",
     "a depth pass that could not be opened is reported under the colour-attachment smoke's stage, so the line "
     "would say the attachments smoke failed while the same line says it passed"),
    ("return failed(\"depth\", \"the depth-carrying pass did not open and did not say why\");",
     "a depth pass that came back null fails the smoke without saying anything, which reads as a smoke that "
     "passed for a reason no one can see"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " depth=" + depth', "the harness does not print the depth smoke's answer"),
    ('+ " depthReason=" + depthReason', "the harness does not print why the depth smoke failed"),
    ("MTL4Probe.canClearDepth(device)", "the harness never asks the depth smoke"),
    ("depth_failures=\"$(grep -c ' depth=false ' \"$probe_log\" || true)\"",
     "the driver does not count the depth smoke's failures"),
    ("if (( depth_failures > 0 )); then", "the driver counts the depth smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- a fence is a promise about one submission, and the client asked for it by stopping at createFence -------
# The contract of a fence is three answers, because that is what the Metal 3 fence answers and the same callers
# read both: a committed submission can be waited for, a submission no commit has promised is not complete (a
# pool that believed otherwise would hand a buffer back to the CPU while the GPU read it), and asking to wait
# for it says so rather than blocking on a signal nothing promised.
for needle, why in (
    ("public static boolean canAwaitSubmissions(", "nothing measures whether a submission's value can be waited for"),
    ("if (!ring.awaitSubmission(1L, 2000L)) {", "the smoke never waits for a submission that was committed"),
    ("if (!ring.awaitSubmission(2L, 2000L)) {", "the smoke never waits for the newest committed submission"),
    ("if (ring.awaitSubmission(3L, 0L)) {", "the smoke never polls the value no commit has promised, or polls "
     "it in a way a true answer would not fail"),
    ("ring.awaitSubmission(3L, 50L);", "the smoke never asks to wait for a submission no commit has promised"),
    ("} catch (IllegalStateException refused) {",
     "the smoke catches every runtime fault as the expected refusal, so a real defect inside the wait would be "
     "reported as the contract holding"),
    ("return ring.awaitSubmission(0L, 0L);",
     "the smoke does not check that a fence for no submission at all is complete"),
    ("ring.nextSubmission() != 3L",
     "the smoke does not check that the next commit's value is the one a fence made inside a frame would promise"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " fence=" + fence', "the harness does not print the fence smoke's answer"),
    ('+ " fenceReason=" + fenceReason', "the harness does not print why the fence smoke failed"),
    ("MTL4Probe.canAwaitSubmissions(device)", "the harness never asks the fence smoke"),
    ("fence_failures=\"$(grep -c ' fence=false ' \"$probe_log\" || true)\"",
     "the driver does not count the fence smoke's failures"),
    ("if (( fence_failures > 0 )); then", "the driver counts the fence smoke's failures and does not fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the indexed draw, which is the one command the client stopped on twice --------------------------------
# The proof is built so the index buffer's contents are the only way to the expected pixel: two covering
# triangles of different flat colour, all six indices listed, and the same pass encoded at index 0 and at
# index 3 - which is six bytes in and must draw the second triangle. A first index that never becomes an
# offset draws the first triangle twice and the second reading fails.
for needle, why in (
    ("public static boolean canDrawIndexed(", "nothing measures an indexed draw, which the client reached by "
     "stopping there"),
    ("private static final int[] EXPECTED_INDEXED_PIXEL = {64, 128, 128, 255};",
     "the indexed smoke's first expected pixel is gone or is not exact in eight bits"),
    ("private static final int[] EXPECTED_INDEXED_OFSET_PIXEL = {128, 64, 128, 255};",
     "the indexed smoke's second expected pixel is gone, so a first index that never becomes an offset would "
     "pass"),
    ("indexData.set(JAVA_SHORT, index * 2L, (short) index);",
     "the index buffer is not filled with the six indices the draw selects"),
    ("long address = indexAddress + firstIndex * INDEX_TYPE_BYTES;",
     "the first index does not become a byte offset into the index buffer's address"),
    ("MTLTexture.bytes(targets[1], pixel, 4L, 0L, 0L, 1L, 1L);\n"
     "                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {",
     "the second frame's pixel is not read and compared, so the offset arithmetic is asserted nowhere (the read "
     "alone appears in the allocator-ring smoke too, which is why the pin is the pair)"),
    ("indices.gpuAddress(), frame * 3)",
     "both indexed frames start at the same index, so the offset arithmetic is never exercised"),
    ("pass.drawIndexedPrimitives(MTLPrimitiveType.Triangle.value, 3L, MTLIndexType.UInt16.value,",
     "the smoke does not draw through the production encoder's indexed draw, so the proof is of a copy"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " index=" + indexed', "the harness does not print the indexed smoke's answer"),
    ('+ " indexReason=" + indexedReason', "the harness does not print why the indexed smoke failed"),
    ("MTL4Probe.canDrawIndexed(device)", "the harness never asks the indexed smoke"),
    ("index_failures=\"$(grep -c ' index=false ' \"$probe_log\" || true)\"",
     "the driver does not count the indexed smoke's failures"),
    ("if (( index_failures > 0 )); then", "the driver counts the indexed smoke's failures and does not fail the "
     "run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- residency, which is what the frame path's addresses depend on -----------------------------------------
# The new command model binds buffers by GPU address, and an address is not a reference: this machine's
# MTL4RenderCommandEncoder.h says to use a residency set for "the index buffer the indexBuffer parameter
# references". What the smoke can prove is the objects: allocations go in, they are counted, the set commits and
# requests residency, and the queue answers the call that makes the set part of its work.
for needle, why in (
    ("public static boolean canDeclareResidency(", "nothing measures whether this device can be told what has to"
     " stay resident, which is the model the frame path's addresses depend on"),
    ("set = MTL4ResidencySet.create(device, 4L, \"the residency proof\");",
     "the smoke never makes a residency set"),
    ("if (!set.add(buffer.handle()) || !set.add(texture)) {",
     "the smoke never adds an allocation, so nothing is declared"),
    ("if (!set.commit() || !set.requestResidency()) {",
     "the smoke does not commit and request, which is what makes an added allocation effective"),
    ("if (set.allocationCount() != 2L) {",
     "the smoke does not check that what the set holds is what was put in it"),
    ('if (!responds(queue, "addResidencySet:")) {',
     "the smoke does not ask whether the queue takes a residency set at all"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " residency=" + residency', "the harness does not print the residency smoke's answer"),
    ('+ " residencyReason=" + residencyReason', "the harness does not print why the residency smoke failed"),
    ("MTL4Probe.canDeclareResidency(device)", "the harness never asks the residency smoke"),
    ("residency_failures=\"$(grep -c ' residency=false ' \"$probe_log\" || true)\"",
     "the driver does not count the residency smoke's failures"),
    ("if (( residency_failures > 0 )); then", "the driver counts the residency smoke's failures and does not "
     "fail the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the indirect indexed form, which is how a chunk renderer reaches its terrain ---------------------------
# The arguments live in a buffer the GPU reads, so what the smoke proves is that they are read as arguments: the
# same two-triangle shape as the indexed smoke, with the arguments' own indexStart choosing the triangle. The
# smoke also had to learn the lifetime rule the hard way - its first version wrote one shared arguments buffer
# for both frames and the first frame read the second's arguments - so the pins include one buffer per frame.
for needle, why in (
    ("public static boolean canDrawIndexedIndirect(", "nothing measures the indirect indexed draw, which the"
     " chunk renderer reaches its terrain through"),
    ("private static final long INDIRECT_ARGUMENTS_BYTES = 20L;",
     "the smoke does not say how big MTLDrawIndexedPrimitivesIndirectArguments is"),
    ("data.set(JAVA_INT, 8L, frame == 0 ? 3 : 0);   // indexStart",
     "the smoke does not vary the arguments' own indexStart, so arguments that are ignored would pass"),
    ("MemorySegment[] argumentData = new MemorySegment[2];",
     "the smoke shares one arguments buffer between frames, so a CPU write can race a submitted read - measured,"
     " and the first version of this smoke drew the wrong triangle because of it"),
    ("pass.drawIndexedPrimitivesIndirect(MTLPrimitiveType.Triangle.value, MTLIndexType.UInt16.value,",
     "the smoke does not draw through the production encoder's indirect form, so the proof is of a copy"),
    ("MTLTexture.bytes(targets[0], pixel, 4L, 0L, 0L, 1L, 1L);\n"
     "                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {",
     "the first frame's pixel is not read and compared with the triangle its arguments asked for (the read"
     " appears in the indexed smoke too, which is why the pin is the pair)"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ('+ " indirect=" + indirect', "the harness does not print the indirect smoke's answer"),
    ('+ " indirectReason=" + indirectReason', "the harness does not print why the indirect smoke failed"),
    ("MTL4Probe.canDrawIndexedIndirect(device)", "the harness never asks the indirect smoke"),
    ("indirect_failures=\"$(grep -c ' indirect=false ' \"$probe_log\" || true)\"",
     "the driver does not count the indirect smoke's failures"),
    ("if (( indirect_failures > 0 )); then", "the driver counts the indirect smoke's failures and does not fail "
     "the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

for needle, why in (
    ("MTL4Probe.canScaleWithMetalFx(device)", "the harness never asks this generation's MetalFX scaler smoke"),
    ('+ " metalFx=" + metalFx', "the harness does not print the scaler smoke's answer"),
    ('+ " metalFxReason=" + metalFxReason', "the harness does not print why the scaler smoke failed"),
    ("metal_fx_failures=\"$(grep -c ' metalFx=false ' \"$probe_log\" || true)\"",
     "the driver does not count the scaler smoke's failures"),
    ("if (( metal_fx_failures > 0 )); then", "the driver counts the scaler smoke's failures and does not fail "
     "the run"),
):
    if needle not in probe and needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# ---------------------------------------------------------------------------
# The MetalFX scaler smoke's own three defects, because each was a way the smoke could pass while measuring
# nothing - and one of them made it fail 2 of 80 probes with a quadrant colour belonging to its neighbour.
#
#   1. the verdict is a CPU read of the output. The first version also encoded a copy of the output into a
#      buffer with a bytesPerRow of four for a 256-wide texture: a malformed copy whose result nothing read,
#      because the CPU read is the verdict. Deleting it is the fix, so the pin is its absence;
#   2. the second and third configurations' textures must outlive the commit. The first version released each
#      pair where it stood, with the command buffer that names them not yet committed - the shape that produced
#      the neighbour's colour, and the reason `others` exists;
#   3. the four colours are four and the tolerance is narrower than the distance between the closest pair, or a
#      flip on an axis could pass. That is what makes this a measurement of orientation rather than of "the
#      scaler ran".
# ---------------------------------------------------------------------------
for needle, why in (
    ("private static final int[][] METALFX_QUADRANTS = {", "the scaler smoke has no pattern to judge"),
    ("private static final long METALFX_INPUT = 64L;", "the scaler smoke's input size is gone"),
    ("private static final long METALFX_OUTPUT = 256L;", "the scaler smoke's output size is gone"),
    ("private static final int METALFX_TOLERANCE = 32;", "the scaler smoke's tolerance is gone"),
    ("for (int quadrant = 0; quadrant < 4; quadrant++) {\n                    long x = quadrant % 2 == 0",
     "the scaler smoke does not read all four quadrant interiors, which is what makes the verdict an "
     "orientation rather than a brightness"),
    ("others.add(small);", "the second and third configurations' textures are not held until the commit that "
     "names them has completed, so a released-and-reused allocation can be read instead of the scaled output"),
    ("for (MemorySegment held : others) {", "the held textures are never released, so the smoke leaks on every "
     "probe"),
    ("MTL4ComputeEncoder.open(device, buffer, \"the MetalFX smoke's upload\")",
     "the scaler smoke does not open the encoder its upload is copied in"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

if "copyTextureToBuffer(output" in probe_source:
    raise SystemExit(
        "the scaler smoke encodes a copy of its output again: the verdict is the CPU read, and a copy whose "
        "bytesPerRow was four for a 256-wide texture is a copy of nothing that nothing reads"
    )

# ---------------------------------------------------------------------------
# The storage-image smoke's failure path localises its own mechanism
#
# The smoke's second dispatch is lost intermittently - 21 times in 200 probes in one period, and not once in 360
# probes in another, on the same device and with the same smoke - and the reason string it printed named the
# symptom ("the texture reads the first colour where the second table held the second") without saying whether
# the dispatch was lost or the CPU read the texture before its write was visible. Those are different faults with
# different fixes, and the smoke's readback is a CPU `getBytes:` while every other readback in this file that
# comes off the GPU goes through a buffer.
#
# So the failure path re-reads the texel after 50 and after 100 ms and puts all three readings in the reason.
# It is on the failure path only, so a passing probe's timing is untouched; a probe that passes cannot be slowed
# by it, and the rate being measured is not disturbed by the instrument.
# ---------------------------------------------------------------------------
for needle, why in (
    ("Thread.sleep(50L);", "the storage-image failure path does not re-read the texel, so its reason cannot say "
     "whether the second dispatch was lost or the read was early"),
    ("read again after 50 ms it is ", "the storage-image failure reason does not carry the later readings, so "
     "the next occurrence names its symptom and not its mechanism"),
    ("String readNow = describe(pixel);", "the first reading is not kept, so the three readings cannot be "
     "compared in one sentence"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

# ---------------------------------------------------------------------------
# Section 58's depth-offset fixture: the bias is sent, and its effect is read
#
# The engine carried a pipeline's `depthBiasConstant` and `depthBiasScaleFactor` for rounds without ever sending
# them to an encoder, so the fix is one call - and a call is not an effect. This smoke is the effect: the red
# triangle at 0.25 writes its depth, the green one at 0.75 is drawn with a constant bias large enough to put it in
# front, and the less-than compare rejects it when no bias is applied and accepts it when one is. Both halves run
# in one command buffer into their own targets, so the reading is a comparison and not a single coloured pixel.
#
# Two things about it are pinned because both were got wrong on the way: the bias is sent **zero** before the first
# draw and the requested value before the second (sending it once before both biased the control draw too, put
# both triangles on the same clamped depth and read as "the call does not work"), and the constant is ten million,
# which the header's own definition of the constant - multiplied by the depth format's minimum resolvable
# difference, about 1.2e-7 for Depth32Float - makes worth more than one in normalised depth. A constant of -0.6
# would move the depth by less than the format can hold.
# ---------------------------------------------------------------------------
cold_probe_driver = (ROOT / "tools" / "metal4-cold-probe" / "Metal4ColdProbe.java").read_text(
    encoding="utf-8")

for needle, why in (
    ("public static boolean canApplyDepthBias(final MTLDevice device) {",
     "the depth-offset smoke is gone, so whether the bias has an effect is unmeasured again"),
    ("SET_DEPTH_BIAS_PROBE.send(pass.encoder(), 0.0f, 0.0f, 0.0f);\n        DRAW.send(pass.encoder(),"
     " MTLPrimitiveType.Triangle.value, 0L, 3L);\n        SET_DEPTH_BIAS_PROBE.send(pass.encoder(), bias, 0.0f,"
     " 0.0f);",
     "the bias is no longer sent zero before the first draw and the requested value before the second, so the "
     "control draw is biased too and the smoke reads the first triangle's colour however the call behaves"),
    ("private static final float DEPTH_BIAS_CONSTANT = -1.0e7f;",
     "the bias constant is small enough that the depth format cannot represent the offset, so the smoke would "
     "read the control's colour whatever the API does"),
    ("depthBias = makeAndSubmit && MTL4Probe.canApplyDepthBias(device);",
     "the census no longer asks the depth-offset smoke, so a device that cannot apply a bias is not reported"),
    ('+ " depthBias=" + depthBias', "the census line no longer carries the depth-offset answer"),
):
    if needle not in probe_source and needle not in cold_probe_driver:
        raise SystemExit("cold-probe harness: " + why)

# ---------------------------------------------------------------------------
# Section 90's counter smoke: what the road is, measured with three instruments at once
#
# The smoke was red for rounds and the pins held the measurement rather than a verdict. The second verdict -
# "the timestamps DO partition the work, and the three things that made them look as if they did not were
# defects in the smoke itself" - is now CORRECTED by reading the same submission with two more instruments,
# which is what this round added:
#
#   * the commit's own feedback (`commit:count:options:` and `MTL4CommitFeedback.GPUStartTime/GPUEndTime`), the
#     road the frame path already reads as gpuM4P50;
#   * the CPU's wait for the queue's completion value, which needs no API to be trusted;
#   * a fixed-cost control: one trivial pass committed on its own, read with the same two instruments;
#   * each workload's own attachment read back, because the curve's target and the area pair's are two
#     textures and one proof cannot stand for both.
#
# Measured, thirty-one probes across seven runs: the marker span is 225-643 us while the driver reports 9.8-27.9
# ms for the same command buffer and the CPU waits 10.4-28.2 ms for its completion, against a fixed cost of
# 0.018-4.201 ms. The
# ratio is 0.0219-0.0234 in every probe even as the driver's window moves by 2.7x, which is the shape of a front
# end (about sixty nanoseconds a draw) and not of the render work behind it. Both marker forms agree to a per
# cent (`heavyStepEncoderOverCb` 1.00-1.02 in every probe), so this is not a granularity or a stage question, and
# the area pair is not a pair at all: 256 draws on 4096x4096 read 17,583-337,062 ticks while 1024 draws on it read
# 49-173. So the smoke's requirement is the aggregate - the heaviest step reads longer than the lightest, which
# held in every probe - and every single-step ordering is reported instead of asserted.
#
# The unit is MEASURED rather than assumed and the field that reports it is the ratio of the two deltas:
# `sampleTimestamps:gpuTimestamp:` twice around a sleep gives gpuDelta/1 cpuDelta = 1.0000, so a tick is a
# nanosecond on this device.
# ---------------------------------------------------------------------------
for needle, why in (
    ("heap.writeTimestamp(buffer, ", "the command-buffer marker is gone, and it is the smoke's only "
     "sampling point - written through MTL4CounterHeap, the engine's single sender of that selector"),
    ("Work after this call may or may not have started", "the header's own statement of what a "
     "command-buffer marker means is gone, so nothing says why a marker behind a pass is a pass boundary"),
    ("writeTimestampWithGranularity:afterStage:intoHeap:atIndex:",
     "the render encoder's stage-and-granularity form is no longer named anywhere, so the form the smoke now "
     "writes at the same boundary as the command buffer's is gone and the two cannot be read against each other"),
    ("WRITE_TIMESTAMP_AFTER_STAGE.send(pass.encoder(), TIMESTAMP_PRECISE, STAGE_FRAGMENT",
     "the encoder's precise after-fragment marker is no longer written inside the pass, so the second sampling "
     "form is not measured at the same boundary and 'the two forms agree' cannot be read"),
    ("commit:count:options:", "the commit no longer carries a feedback handler, so the smoke cannot read the "
     "driver's own window for the submission its markers describe"),
    ("fixedCommitMs=", "the fixed cost of a commit is no longer measured on a submission of its own, so a "
     "driver window can no longer be separated into work and per-commit cost"),
    ("cpuWaitMs=", "the CPU's completion wait is no longer reported, which is the one instrument that needs no "
     "API to be trusted"),
    ("markerOverDriver=", "the marker span is no longer reported against the driver's window, which is the "
     "number the correction turns on"),
    ("heavyStepEncoderOverCb=", "the two sampling forms are no longer compared on one pass"),
    ("curveOrdered=", "the single-step inversions are no longer reported, so a census cannot count them"),
    ("lightPairOrdered=", "the light pair's ordering - the pair that inverts most often - is no longer reported"),
    ("the heaviest step does not read longer than the lightest",
     "the smoke no longer requires even the aggregate the road does answer"),
    ("private static final long COUNTER_AREA_EDGE = 4096L;",
     "the area knob is gone again, and a draw-count curve alone cannot separate 'the road does not read the "
     "store' from 'the store is not what it responds to'"),
    ("heap.writeTimestamp(buffer, timestampIndex);",
     "the boundary markers are not written from one site, so a second form can come back one call at a time"),
    ("if (timestampIndex >= 0L) {", "the warm-up pass is not excluded from the curve, so the first measured "
     "step is the clearing pass and the command buffer's first encoder again"),
    ("\"the counter smoke's warm-up\"", "the warm-up pass is gone, which is the reading that separated the "
     "first step's cost from the fifteen extra draws"),
    ("private static final int[] COUNTER_DRAWS = {64, 256, 1024, 4096};",
     "the curve is not the one measured above the road's floor, so the smoke can fail on a step whose interval "
     "is inside the noise rather than on the counter"),
    ("below roughly two thousand ticks on this device is not ordered",
     "the road's resolution floor is no longer recorded, so the next reader would take the curve's light points "
     "for a property of the counter"),
    ("4096 -> 211505", "the four runs the curve was measured with are not in the code, so the numbers behind the "
     "choice of counts are gone"),
    ("sampleTimestamps:gpuTimestamp:", "the CPU/GPU clock relationship is no longer measured, so the tick's unit "
     "would be an assumption again"),
    ("(double) sample[2] / sample[3]", "the reported unit is not the ratio of the two deltas, so the field a "
     "reader checks a tick with is some other number"),
    ("samplerGpuDeltaTicks=", "the clock-ratio reading is not reported, so a reader cannot check the unit"),
    ("boolean drew = false;", "the smoke no longer proves its own workload is present"),
    ("drawsLanded=", "the workload proof is not reported"),
    ("areaLanded=", "the area pair's own attachment is no longer read back, so 'the road does not respond to"
     " area' and 'the area target received no draws' become the same measurement"),
    ("MTLTexture.bytes(small, pixel, 4L, COUNTER_EDGE / 2L",
     "the curve's attachment is no longer the one whose pixel is read, so one proof stands for both workloads"),
    ("if (stamps[index] < stamps[index - 1]) {",
     "the smoke no longer checks that the stamps are in submission order, which is the reading the whole "
     "counter question turns on"),
    ("Msg.ofVoid(\n            \"resolveCounterHeap:withRange:intoBuffer:waitFence:updateFence:\",",
     "the GPU-timeline resolve's selector is no longer the one this SDK declares, so the one counter road that "
     "could have changed where the sample is taken is gone and the rejection would rest on the CPU resolve alone"),
    ("ADDRESS, JAVA_LONG, JAVA_LONG, JAVA_LONG, JAVA_LONG, ADDRESS, ADDRESS);",
     "the resolve's argument words are no longer declared in the ABI's own order - the heap, the two words of "
     "NSRange, the two of MTL4BufferRange and the two fences - so a later edit could reorder an address and a "
     "length without the call failing to compile"),
    ("RESOLVE_COUNTER_HEAP.send(commandBuffer, heap.handle(),",
     "the GPU-timeline resolve is no longer encoded into the submission, so nothing writes the resolve buffer "
     "and the comparison against the CPU resolve cannot be made"),
    ("Msg.of(\"sizeOfCounterHeapEntry:\", JAVA_LONG, JAVA_LONG);",
     "the resolved entry's size is assumed rather than asked, so a device whose resolved entries are not eight "
     "bytes would be read with the wrong stride"),
    ("timelineAgrees=", "the two resolve roads are no longer compared, which is the measurement this whole "
     "experiment exists for"),
    ("timelineMidUnwrittenZero=", "the mid-stream resolve's unwritten tail is no longer reported, so a resolve "
     "that dumped the whole heap instead of snapshotting its position could not be told from one that did"),
    ("timelineOverDriver=", "the timeline-resolved span is no longer reported against the driver's window, so "
     "the two roads agreeing could not be read as the rejection it is"),
    ("COMMIT_WITH_OPTIONS.send(queue, buffers, 1L, options.handle());",
     "the driver's own window is no longer read on the submission the markers describe, so the cross-check the "
     "correction rests on is gone"),
    ("WAIT_UNTIL_SIGNALED.sendLong(event, 2L, 5000L)", "the CPU no longer waits for the submission's completion "
     "value before it reads the resolve buffer, which is the header's own condition for reading it"),
    ("MTL4RenderEncoder.Color(target, AttachmentContents.CARRIED, null)",
     "the steps are no longer dependent: each one must load what the step before stored, so a reordering of the "
     "work cannot be what an inversion means"),
    ("long[] range = heap.resolveRange(0L, stamps.length);",
     "the range resolve is gone, so the per-entry road is no longer checked against the road the header says "
     "returns tightly packed entries"),
    ("clearPipeline = MTLBuiltinPipelines.ensureClearPipeline(",
     "the passes no longer draw, so the workload is a clear again - which was measured not to scale (4096x4096 "
     "and 512x512 both read about 31 us)"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)

# And the duplicated boundary must not come back: it is the one defect that made the smoke fail on arithmetic
# that looked like a driver property for rounds.
if ("public boolean writeTimestamp(final MemorySegment commandBuffer, final long index)"
        not in counter_heap_source):
    raise SystemExit("cold-probe harness: MTL4CounterHeap no longer offers the road's writing call, so a marker "
                     "has to be sent from somewhere else and the smoke and the frame path stop sharing one call")
if "writeTimestampIntoHeap:atIndex:" not in counter_heap_source:
    raise SystemExit("cold-probe harness: the heap no longer sends the selector the header declares, so the "
                     "marker's road is not the one MTL4CommandBuffer.h documents")
if "writeTimestamp(buffer, 2L)" in probe_source:
    raise SystemExit("cold-probe harness: a marker is written to a fixed heap index again, which is how the "
                     "middle boundary came to hold the end of everything and the curve came to look inverted")

for needle, why in (
    ("gpu_time_failures=\"$(grep -c ' gpuTime=false ' \"$probe_log\" || true)\"",
     "the driver does not count the counter smoke's failures"),
    ("gpu_time_passes=\"$(grep -c ' gpuTime=true ' \"$probe_log\" || true)\"",
     "the driver does not count the counter smoke's successes"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

# --- the retry, which no session had ever exercised ------------------------------------------------------
# The capability gate rests on "the first attempt of a process can fail and the second does not", and the real
# fault has not recurred in 240 probes with nothing changed - so the policy's mechanics are the half that can be
# priced on demand, and `-Dmetallum.probeInjectFirstFailure=true` is how. It is a diagnostic and not a
# production path: the switch has to be read as a property that is absent by default, it has to be spent by its
# first use so the retry's own attempt is measured rather than injected, and the failure it produces has to say
# in words that it was injected - a census line that could not tell an injected failure from a device fault
# would make this the most dangerous switch in the tree.
for needle, why in (
    ('Boolean.getBoolean("metallum.probeInjectFirstFailure")',
     "the switch that lets the retry be exercised is gone, so the capability gate's policy is unexercised again "
     "and nothing can price it without waiting for a fault that has not recurred in 240 probes"),
    ("private static boolean injectionSpent;",
     "the injection is not one-shot, so every attempt of a process would fail rather than the first - which "
     "measures a broken path and not the retry"),
    ("boolean injected = injectFirstFailure();",
     "the check the fault fails on no longer asks whether this attempt is the injected one"),
    ("is failed on purpose",
     "an injected failure is not marked as injected, so a census line cannot be told from a measurement of the "
     "device"),
):
    if needle not in probe_source:
        raise SystemExit("cold-probe harness: " + why)
for needle, why in (
    ("--vmargs) read -r -a probe_vmargs <<< \"$2\"; shift 2 ;;",
     "the harness cannot give the probe process a JVM argument, so the switch above can never reach a run"),
    ('java ${probe_vmargs[@]+"${probe_vmargs[@]}"} -cp "$classes:$classpath" Metal4ColdProbe',
     "the probe JVM is started without the caller's arguments, so a run asked to inject the failure measures "
     "the unmodified path"),
):
    if needle not in script:
        raise SystemExit("cold-probe harness: " + why)

print("Metal 4 cold-probe harness contract: PASS")

# ==================== was tools/ci-metal4-report.py ====================
"""The final report's own shape, as a contract rather than as a hope.

Section 121 names the sections this report must carry and the fields each one must state, and section 122 makes
"docs updated" one of the things Metal 4's definition of done rests on. A report that quietly loses a section, or
loses the field a section is read by, is a report whose completeness nobody notices - which is exactly how this
document contradicted itself once before: the capability matrix was updated rung by rung while the narrative
sections beneath it were not, and a reader who took the Compute block at its word would have concluded the
compute road did not exist. The check is therefore mechanical: every section, and every field this plan asks a
section to state, is either in the file or this fails.
"""


REPORT = ROOT / "docs" / "metal4-full-frame-report.md"
text = REPORT.read_text(encoding="utf-8")

# Section 121's sections, in its own order.
SECTIONS = (
    "## Starting SHAs",
    "## Cold Probe",
    "## Native Smoke",
    "## M4 Frame",
    "## Render",
    "## Resource Binding",
    "## Blit",
    "## Compute",
    "## Synchronization",
    "## Lifecycle",
    "## MetalFX Spatial",
    "## Performance",
    "## Remaining blockers",
)

# And the fields each of those sections has to state, as section 121 lists them. `Starting SHAs` and
# `Synchronization` and `Remaining blockers` are named without a field list; the sha pair and the blocker list
# are checked by their own words below.
FIELDS = (
    "cold runs:", "warm probes:", "AUTO blocker:",
    "colour:", "vertex:", "uniform:", "texture/sampler:", "multi-pass:",
    "queue:", "allocator", "command buffer", "commit", "present",
    "basic:", "MRT:", "depth:", "blend:", "scissor:",
    "textures:", "samplers:", "uniform buffers:", "vertex/index:", "argument tables:", "residency:",
    "full:", "region:", "mipmap:",
    "dispatch:", "SSBO:", "storage image:", "render\u2192compute:", "compute\u2192render:",
    "F3+T:", "pack switch:", "world join:", "dimension:", "resize:", "fullscreen:", "shutdown:",
    "supported:", "configuration cache:", "M3 result:", "M4 result:", "performance:",
    "wallP50", "wallP95", "wallP99",
)

# The GPU percentiles are stated twice, because this engine has two APIs for them and section 92 says the two
# kinds are not interchangeable: Metal 3's arm reports `gpuP50/P95/P99` from `MTLCommandBuffer.gpuMillis` and this
# path's reports `gpuM4P50/P95/P99` from `MTL4CommitFeedback`. Each spelling is required, and a report that lost
# one of them would be a report that stopped saying what the other generation's GPU time is called.
GPU_FIELDS = tuple(
    spelling
    for quantile in ("50", "95", "99")
    for spelling in (f"gpuP{quantile}", f"gpuM4P{quantile}")
)

for section in SECTIONS:
    if section not in text:
        raise SystemExit("the report no longer carries the section section 121 asks for: " + section)

missing = [field for field in FIELDS + GPU_FIELDS if field not in text]
if missing:
    raise SystemExit("the report no longer states the field(s) section 121 asks for: " + ", ".join(missing))

# Starting SHAs states both repositories, and the final verdict section is what says whether the phrase is earned.
for needle, why in (
    ("STARTING_METALLUM_SHA", "the report does not name the Metallum sha it started from"),
    ("STARTING_VITRAIL_SHA", "the report does not name the Vitrail sha it started from"),
    ("## Metal 4 full-frame implementation complete?",
     "the report has no section that answers the question section 122 is about"),
    ("## The definition of done, item by item",
     "the report does not carry the definition of done item by item, so 'complete? YES' would rest on nothing"),
):
    if needle not in text:
        raise SystemExit("metal 4 report contract: " + why)

print("Metal 4 full-frame report contract: PASS")
