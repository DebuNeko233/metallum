package com.metallum.render.metal4;

import com.metallum.Metallum;
import com.metallum.mtl.MTLCompareFunction;
import com.metallum.mtl.MTLDepthStencilDescriptor;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.ObjC;
import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.metallum.render.shared.GlslCommentStripper;
import com.metallum.render.shared.MetalFrameProbe;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.preprocessor.GlslPreprocessor;
import net.minecraft.client.renderer.ShaderDefines;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vulkan.glsl.GlslCompiler;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.minecraft.resources.Identifier;

import java.lang.foreign.MemorySegment;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.function.Predicate;
import java.util.regex.Pattern;

/**
 * The compilation state a Metal 4 session owns: what it has already made, and how to make more.
 * <p>
 * The Metal 3 context is the reference for what this has to answer - a shader module per shader, a native
 * function per entry point, a depth-stencil state per comparison, a compiled artifact per pipeline - and this is
 * the Metal 4 generation's own copy of that structure rather than a use of the Metal 3 one, because
 * {@code render.metal4} may not depend on {@code render.metal3}. What each cache holds is the same kind of
 * thing; what it is keyed by is written out here rather than inherited.
 * <p>
 * <strong>The profile is part of every key</strong>, as it is in the Metal 3 context: a module or a function
 * translated for one MSL profile is not the one another profile needs, and a cache that keyed only on the source
 * text would be safe by accident rather than by construction.
 * <p>
 * <strong>Retirement is the frame's business, and this context is honest about that.</strong> An artifact that is
 * evicted or replaced may still be referenced by work in flight, so it is not closed here: it is filed in
 * {@link #retired} and released by {@link #clearCachesAfterGpuCompletion()}, whose contract already says the
 * caller has established GPU completion. The Metal 3 context retires per submit because it can ask the frame
 * encoder; this one has one queue and one method, which is the smaller lifetime model and the one the neutral
 * contract actually describes.
 */
@Environment(EnvType.CLIENT)
final class Metal4CompilationContext {

    private static final Pattern GLSL_ERROR_LINE = Pattern.compile("\\b\\d+:(\\d+):");

    private final MTLDevice device;
    private final Map<ShaderCompilationKey, IntermediaryShaderModule> shaderCache = new HashMap<>();
    private final Map<MslFunctionKey, MemorySegment> functionCache = new HashMap<>();
    private final Map<Long, MemorySegment> depthStencilStates = new HashMap<>();
    private final Map<RenderPipeline, Metal4CompiledRenderPipeline> compiledPipelines = new IdentityHashMap<>();
    private final ArrayDeque<Metal4CompiledRenderPipeline> retired = new ArrayDeque<>();

    Metal4CompilationContext(final MTLDevice device) {
        this.device = device;
    }

    /** The native device this context compiles against. Package-private: it is not integration API. */
    MTLDevice device() {
        return this.device;
    }

    /**
     * The SPIR-V module for a shader, compiled once per (shader, stage, defines, profile).
     * <p>
     * This is the one step that is not Metal-specific at all: the game's own GLSL compiler turns a pack's source
     * into the module both generations translate from. It is here rather than shared because the shared layer
     * owns the translation and not the compilation, and because the Metal 3 context keeps its own copy until the
     * two collapse - a collapse that would touch the reference path and is therefore not part of this migration.
     */
    synchronized IntermediaryShaderModule getOrCompileShader(final Identifier id, final ShaderType type,
                                                             final ShaderDefines defines,
                                                             final ShaderSource shaderSource) {
        ShaderCompilationKey key = new ShaderCompilationKey(id, type, defines,
                MetalShaderLanguageProfile.selected().token());
        return this.shaderCache.computeIfAbsent(key, k -> {
            String source = shaderSource.get(k.id(), k.type());
            if (source == null) {
                return IntermediaryShaderModule.INVALID;
            }
            String prepared = GlslPreprocessor.injectDefines(
                    GlslCommentStripper.strip(source).stripLeading(), k.defines());
            try (GlslCompiler compiler = new GlslCompiler()) {
                return compiler.createIntermediary(k.id().toDebugFileName(), prepared, k.type());
            } catch (ShaderCompileException failure) {
                throw new IllegalStateException(shaderCompileFailure(k.id(), prepared, failure), failure);
            }
        });
    }

    /** The native function for this MSL and entry point, compiled once per (text, entry, profile). */
    synchronized MemorySegment getOrCompileFunction(final String msl, final String entryPoint) {
        return this.functionCache.computeIfAbsent(
                new MslFunctionKey(msl, entryPoint, MetalShaderLanguageProfile.selected().token()),
                key -> this.device.newFunction(key.msl(), key.entryPoint()));
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

    /**
     * The compiled artifact for this pipeline, compiling it if the cache does not hold one - and recompiling it
     * where the held one was translated for another MSL profile. The mismatched artifact is retired rather than
     * closed, because work already recorded against it may still be in flight.
     */
    synchronized CompiledRenderPipeline getOrCompilePipeline(final RenderPipeline pipeline,
                                                             final ShaderSource source) {
        Metal4CompiledRenderPipeline held = this.compiledPipelines.get(pipeline);
        if (held != null && !held.pipelineKey().shaderProfile().equals(
                MetalShaderLanguageProfile.selected().token())) {
            this.compiledPipelines.remove(pipeline);
            this.retired.add(held);
            held = null;
        }

        Metal4CompiledRenderPipeline compiled = held != null
                ? held
                : this.compiledPipelines.computeIfAbsent(pipeline,
                        p -> Metal4PipelineCompiler.compile(this, p, source));
        MetalFrameProbe.pipelineRequested(pipeline, compiled.pipelineKey());
        return compiled;
    }

    /** Removes the pipelines a predicate selects, retiring each, and answers what it removed. */
    synchronized List<RenderPipeline> evictCachedPipelines(final Predicate<RenderPipeline> predicate) {
        Objects.requireNonNull(predicate, "predicate");

        List<RenderPipeline> evicted = new ArrayList<>();
        Iterator<Map.Entry<RenderPipeline, Metal4CompiledRenderPipeline>> entries =
                this.compiledPipelines.entrySet().iterator();
        while (entries.hasNext()) {
            Map.Entry<RenderPipeline, Metal4CompiledRenderPipeline> entry = entries.next();
            if (!predicate.test(entry.getKey())) {
                continue;
            }

            evicted.add(entry.getKey());
            this.retired.add(entry.getValue());
            entries.remove();
        }
        return List.copyOf(evicted);
    }

    /**
     * Releases everything this generation may release, once the caller has established GPU completion.
     * <p>
     * Retired artifacts first, then the ones still in the cache: a pipeline released before the work that named
     * it has completed is the corruption the retirement queue exists to prevent.
     */
    synchronized void clearCachesAfterGpuCompletion() {
        while (!this.retired.isEmpty()) {
            this.retired.poll().close();
        }
        this.compiledPipelines.values().forEach(Metal4CompiledRenderPipeline::close);
        this.compiledPipelines.clear();
        this.shaderCache.values().forEach(IntermediaryShaderModule::close);
        this.shaderCache.clear();
        for (MemorySegment function : this.functionCache.values()) {
            if (!ObjC.isNil(function)) {
                ObjC.release(function);
            }
        }
        this.functionCache.clear();
    }

    /** Releases the compilation state itself, including the depth-stencil states it made. */
    synchronized void close() {
        clearCachesAfterGpuCompletion();
        for (MemorySegment state : this.depthStencilStates.values()) {
            if (!ObjC.isNil(state)) {
                ObjC.release(state);
            }
        }
        this.depthStencilStates.clear();
    }

    /**
     * What a translated module is keyed by: the shader, the stage, the defines it was compiled with, and the MSL
     * profile it was translated for.
     */
    private record ShaderCompilationKey(Identifier id, ShaderType type, ShaderDefines defines, String shaderProfile) {
    }

    /** A compiled function for the entry point, keyed by the MSL text, the entry point and the profile. */
    private record MslFunctionKey(String msl, String entryPoint, String profile) {
    }

    /** A GLSL compile failure with the source around the line the compiler named, as the Metal 3 path reports it. */
    private static String shaderCompileFailure(final Identifier id, final String source,
                                               final ShaderCompileException error) {
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

    /** Says one thing once for the life of the context, because a compile path may not log a line a pipeline. */
    static void warnOnce(final String words) {
        Metallum.LOGGER.warn(words);
    }
}
