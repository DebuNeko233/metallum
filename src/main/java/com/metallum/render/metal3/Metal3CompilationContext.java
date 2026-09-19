package com.metallum.render.metal3;

import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLDepthStencilDescriptor;
import com.metallum.mtl.MTLCompareFunction;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;
import java.util.HashMap;
import java.util.Map;
import java.util.regex.Pattern;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import net.minecraft.resources.Identifier;
import com.mojang.blaze3d.shaders.ShaderType;
import net.minecraft.client.renderer.ShaderDefines;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.mojang.blaze3d.vulkan.glsl.GlslCompiler;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import com.mojang.blaze3d.preprocessor.GlslPreprocessor;
import com.metallum.objc.ObjC;
import java.util.Locale;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Objects;
import java.util.function.Predicate;
import com.metallum.render.shared.MetalFrameProbe;

/**
 * The compilation state the Metal 3 frame path owns: what it has already made, and how to make more.
 * <p>
 * The device used to own this - caches of depth-stencil states, shader modules, functions and compiled pipelines,
 * with the factories beside them - which made the device a registry of one generation's artifacts. That is the
 * blocker the frame path's move kept hitting: every attempt to move the encoder needed those members, and
 * widening them one at a time is what the first failures did. The state belongs to the generation, so it lives
 * here, and the device asks this object the way the frame path does.
 * <p>
 * It is being filled in one cache at a time rather than in one rewrite, so that each step is a build and a
 * contract run away from a working tree. What is here now is the depth-stencil cache and its factory; the shader
 * module, function and compiled-pipeline caches follow, with their profile guard, and this class stays the single
 * place a Metal 3 compile artifact is keyed.
 */
@Environment(EnvType.CLIENT)
final class Metal3CompilationContext {

    private final MTLDevice device;
    private final Metal3PipelineRetirement retirement;
    private static final Pattern GLSL_ERROR_LINE = Pattern.compile("\\b\\d+:(\\d+):");
    private final Map<Long, MemorySegment> depthStencilStates = new HashMap<>();
    private final Map<ShaderCompilationKey, IntermediaryShaderModule> shaderCache = new HashMap<>();
    private final Map<MslFunctionKey, MemorySegment> functionCache = new HashMap<>();
    private final Map<RenderPipeline, MetalCompiledRenderPipeline> compiledPipelines = new IdentityHashMap<>();

    Metal3CompilationContext(final MTLDevice device, final Metal3PipelineRetirement retirement) {
        this.device = device;
        this.retirement = retirement;
    }

    synchronized IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type, final ShaderDefines defines, final ShaderSource shaderSource) {
        // The profile is part of the identity, not a detail of the compile: a module translated for Metal 3.2
        // is not the module a Metal 4 session needs, and the function cache below has always named it
        // (`MslFunctionKey`) while this one did not. It is one token and the profile is fixed per process, so
        // this changes no cache behaviour today - it is what makes the reuse impossible rather than unlikely.
        ShaderCompilationKey key = new ShaderCompilationKey(id, type, defines,
                MetalShaderLanguageProfile.selected().token());
        return this.shaderCache.computeIfAbsent(key, k -> {
            String source = shaderSource.get(k.id(), k.type());
            if (source == null) {
                return IntermediaryShaderModule.INVALID;
            }
            String sourceWithDefines = prepareShaderSource(source, k.defines());
            try (GlslCompiler glslCompiler = new GlslCompiler()) {
                return glslCompiler.createIntermediary(k.id().toDebugFileName(), sourceWithDefines, k.type());
            } catch (ShaderCompileException e) {
                throw new IllegalStateException(shaderCompileFailure(k.id(), sourceWithDefines, e), e);
            }
        });
    }
    private static String prepareShaderSource(final String source, final ShaderDefines defines) {
        String stripped = GlslCommentStripper.strip(source).stripLeading();
        return GlslPreprocessor.injectDefines(stripped, defines);
    }
    private static String shaderCompileFailure(final Identifier id, final String source, final ShaderCompileException error) {
        String message = error.getMessage();
        if (message == null) {
            return "Failed to compile shader " + id;
        }
        var lineMatch = GLSL_ERROR_LINE.matcher(message);
        if (!lineMatch.find()) {
            return "Failed to compile shader " + id;
        }

        int line;
        try {
            line = Integer.parseInt(lineMatch.group(1));
        } catch (NumberFormatException ignored) {
            return "Failed to compile shader " + id;
        }
        return "Failed to compile shader " + id + "\n" + shaderSourceContext(source, line, 4);
    }
    private static String shaderSourceContext(final String source, final int failingLine, final int radius) {
        String[] lines = source.split("\\R", -1);
        if (failingLine < 1 || failingLine > lines.length) {
            return "GLSL source line " + failingLine + " is outside the prepared source (" + lines.length + " lines)";
        }

        int first = Math.max(1, failingLine - radius);
        int last = Math.min(lines.length, failingLine + radius);
        StringBuilder context = new StringBuilder("GLSL source around line ").append(failingLine).append(':');
        for (int line = first; line <= last; line++) {
            context.append('\n')
                    .append(line == failingLine ? ">> " : "   ")
                    .append(String.format(Locale.ROOT, "%5d | %s", line, lines[line - 1]));
        }
        return context.toString();
    }
    /**
     * What a translated module is keyed by: the shader, the stage, the defines it was compiled with **and the
     * MSL profile it was translated for**. The profile is here because a module is not a stage-independent
     * artifact: it carries the MSL the translator produced and the language version Metal accepted it under,
     * so a session that changed profile must not be handed a module from the other one.
     */
    private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines,
                                        String shaderProfile) {
    }
    /**
     * A compiled function for the entry point, keyed by the MSL text, the entry point and the profile.
     * <p>
     * The profile is part of the identity even though the MSL text already differs between profiles: a cache
     * whose key is the text is safe by accident, and one whose key names the profile is safe by construction -
     * and the accident is exactly what a future translator that emits the same text for two profiles would
     * remove. Key, profile token, factory and locking model are unchanged by this move.
     */
    synchronized MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        return this.functionCache.computeIfAbsent(
                new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token()),
                key -> this.device.newFunction(key.msl(), key.entryPoint())
        );
    }

    private record MslFunctionKey(String msl, String entryPoint, String profile) {
    }

    /** The native device this context compiles against. Package-private: it is not integration API. */
    MTLDevice device() {
        return this.device;
    }

    /**
     * The compiled artifact for this pipeline, recompiling it if the one held was translated for another MSL
     * profile. The identity key is the game's own pipeline object, deliberately, and the profile is the one
     * session-scoped input the key cannot name - so it is checked on every hit, and a mismatched artifact goes
     * to retirement rather than being closed: work already recorded against it may still be in flight.
     */
    private MetalCompiledRenderPipeline compiledFor(final RenderPipeline pipeline, final ShaderSource source) {
        MetalCompiledRenderPipeline held = this.compiledPipelines.get(pipeline);
        if (held != null && !held.pipelineKey().shaderProfile().equals(MetalShaderLanguageProfile.selected().token())) {
            this.compiledPipelines.remove(pipeline);
            this.retirement.retire(held);
        }

        return this.compiledPipelines.computeIfAbsent(
                pipeline, p -> Metal3PipelineCompiler.compile(this, p, source));
    }

    /** The compiled artifact for this pipeline. The frame probe is told once, here. */
    synchronized MetalCompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline, final ShaderSource source) {
        MetalCompiledRenderPipeline compiled = compiledFor(pipeline, source);
        MetalFrameProbe.pipelineRequested(pipeline, compiled.pipelineKey());
        return compiled;
    }

    /** Removes the pipelines a predicate selects, handing each to retirement, and answers what it removed. */
    synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        Objects.requireNonNull(predicate, "predicate");

        List<RenderPipeline> evicted = new ArrayList<>();
        Iterator<Map.Entry<RenderPipeline, MetalCompiledRenderPipeline>> entries =
                this.compiledPipelines.entrySet().iterator();
        while (entries.hasNext()) {
            Map.Entry<RenderPipeline, MetalCompiledRenderPipeline> entry = entries.next();
            if (!predicate.test(entry.getKey())) {
                continue;
            }

            evicted.add(entry.getKey());
            this.retirement.retire(entry.getValue());
            entries.remove();
        }
        return List.copyOf(evicted);
    }

    /** Releases the pipelines still in the active cache. Never waits: GPU completion is the caller's business. */
    synchronized void clearActivePipelines() {
        this.compiledPipelines.values().forEach(MetalCompiledRenderPipeline::close);
        this.compiledPipelines.clear();
    }

    /** A depth-stencil state for the comparison and write flags, made once and kept. */
    synchronized MemorySegment depthStencilState(final MTLCompareFunction compareFunction, final boolean writeDepth) {
        long key = (compareFunction.value << 1) | (writeDepth ? 1L : 0L);
        MemorySegment cached = this.depthStencilStates.get(key);
        if (cached != null) {
            return cached;
        }

        try (MTLDepthStencilDescriptor descriptor = MTLDepthStencilDescriptor.create()) {
            descriptor.depthCompareFunction(compareFunction);
            descriptor.depthWriteEnabled(writeDepth);
            MemorySegment state = this.device.newDepthStencilState(descriptor);
            this.depthStencilStates.put(key, state);
            return state;
        }
    }

    /** Releases every state this context made. Called once, by the device that opened it. */
    /** Releases and forgets every compiled function, on the same terms the device released them. */
    synchronized void clearFunctionCache() {
        for (MemorySegment function : this.functionCache.values()) {
            if (!ObjC.isNil(function)) {
                ObjC.release(function);
            }
        }

        this.functionCache.clear();
    }

    /** Closes and forgets every translated module. Called when the device clears its caches. */
    synchronized void clearShaderCache() {
        this.shaderCache.values().forEach(IntermediaryShaderModule::close);
        this.shaderCache.clear();
    }

    synchronized void close() {
        clearShaderCache();
        clearFunctionCache();
        for (MemorySegment state : this.depthStencilStates.values()) {
            com.metallum.objc.ObjC.release(state);
        }

        this.depthStencilStates.clear();
    }
}
