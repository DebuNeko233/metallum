package com.metallum.mixin.render;

import com.metallum.api.MetallumShaderModules;
import com.mojang.blaze3d.shaders.ShaderType;
import com.mojang.blaze3d.vulkan.glsl.IntermediaryShaderModule;
import com.mojang.blaze3d.vulkan.glsl.ShaderCompileException;
import org.lwjgl.util.shaderc.Shaderc;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;

/**
 * Offers the two points of a stage compile that belong to a shader-pack integration, and nothing
 * else.
 * <p>
 * The road this sits on is one call wide: {@code createIntermediary} compiles the GLSL to SPIR-V and
 * then hands that SPIR-V to {@code createFromSpirv}, which reflects it into the record every later
 * step reads. Between those two is the last moment at which the bytes can be rewritten without
 * anything having described them already, and just after it is the first moment at which the
 * reflected resource list exists to be narrowed. So both are taken on the one call, which is why
 * this is a redirect and not two injections: the replacement receives the buffer the compiler
 * produced, runs the integration's patch, builds the record from the patched bytes, and narrows what
 * came back.
 * <p>
 * <strong>Both halves are optional and neither can fail a compile by being absent.</strong> The hook
 * in force is the no-op one until something installs its own, and an integration that answers
 * nothing for a stage leaves that stage exactly as it was. A refusal is different: an integration
 * that throws out of its own patch has refused that stage, and the exception is the compile's.
 * <p>
 * <strong>Why the reflected list is read by reflection.</strong> The record's sampler list holds
 * package-private entries whose own accessors are not visible from here, and this project may not
 * widen that package. The list itself is public and mutable, which is what the narrowing needs: the
 * names come off the entries reflectively, and the removal is an ordinary {@code removeIf} on the
 * list the record was built with.
 * <p>
 * This mixin is named in {@code MetallumMixinConfigPlugin} as well as in the config, because a mixin
 * listed in the config and not in that plugin is never applied and says nothing about it.
 */
@Mixin(targets = "com.mojang.blaze3d.vulkan.glsl.GlslCompiler")
public abstract class ShaderModuleHookMixin {

    /** {@code IntermediaryShaderModule.samplers()}, which is public and hands back the live list. */
    @Unique
    private static final Method SAMPLERS = method(IntermediaryShaderModule.class, "samplers");

    /** {@code SpvSampler.name()}, on a package-private record. */
    @Unique
    private static final Method SAMPLER_NAME = entryName();

    /**
     * The key the compile in flight on this thread is being kept under, or null when it is not.
     * <p>
     * On the thread rather than a field, because compiles run on the render thread and on a worker
     * pool at the same time and each is keeping its own unit. Removed at every road out of the
     * method, so a compile that dies between the two injections cannot leave a key for the next one
     * to keep a module under.
     */
    @Unique
    private static final ThreadLocal<String> CACHE_KEY = new ThreadLocal<>();

    /**
     * Whether the compiler should write debug information, asked once while it is constructed.
     * <p>
     * A redirect rather than a wrap: the option is a call with no result, and the whole of the
     * decision is whether to make it. The hook is consulted per compiler, which is once per compile
     * on this road - {@code Metal3CompilationContext} builds one per stage - so an integration that
     * answers from a file read does it once per stage rather than once per session. Said here
     * because a hook implementation should know what it is being asked and how often.
     */
    @Redirect(method = "<init>", require = 1,
            at = @At(value = "INVOKE",
                    target = "Lorg/lwjgl/util/shaderc/Shaderc;"
                            + "shaderc_compile_options_set_generate_debug_info(J)V"))
    private void metallum$debugInfo(final long options) {
        if (MetallumShaderModules.hook().wantsShaderDebugInfo()) {
            Shaderc.shaderc_compile_options_set_generate_debug_info(options);
        }
    }

    /**
     * Offers the unit to the integration before the compiler is asked for it.
     * <p>
     * The module type is handed over first, because an integration that keeps modules on disk cannot
     * name it and cannot obtain it before one exists - and this is the last moment before it is
     * needed. Then the compile is bracketed and the unit's key asked for; a key means this compile
     * is worth keeping, and a store that already has it cancels the whole road here.
     */
    @Inject(method = "createIntermediary", require = 1, at = @At("HEAD"), cancellable = true)
    private void metallum$cached(final String filename, final String source, final ShaderType type,
                                 final CallbackInfoReturnable<IntermediaryShaderModule> cir) {
        MetallumShaderModules.Hook hook = MetallumShaderModules.hook();
        hook.moduleType(IntermediaryShaderModule.class);
        hook.beginCompile(filename);

        String key = hook.moduleKey(filename, source, type.name());
        if (key == null) {
            CACHE_KEY.remove();

            return;
        }

        Object cached = hook.cachedModule(key, filename);
        if (cached instanceof IntermediaryShaderModule module) {
            CACHE_KEY.remove();
            hook.endCompile(filename);
            cir.setReturnValue(module);

            return;
        }

        CACHE_KEY.set(key);
    }

    /**
     * Offers what the compile produced back to the integration, and closes the bracket.
     * <p>
     * Every return of the method reaches this, and a compile that threw reaches neither: the bracket
     * is then closed by the next {@code beginCompile} on that thread, which is why the interface
     * describes the pair as best-effort rather than as guaranteed.
     */
    @Inject(method = "createIntermediary", require = 1, at = @At("RETURN"))
    private void metallum$keep(final String filename, final String source, final ShaderType type,
                               final CallbackInfoReturnable<IntermediaryShaderModule> cir) {
        String key = CACHE_KEY.get();
        CACHE_KEY.remove();

        MetallumShaderModules.Hook hook = MetallumShaderModules.hook();
        IntermediaryShaderModule built = cir.getReturnValue();
        if (key != null && built != null) {
            hook.keepModule(key, filename, built);
        }

        hook.endCompile(filename);
    }

    /**
     * Replaces the one reflection call with the integration's two halves around it.
     *
     * @param filename the debug name the compile was given, which is the hook's label too
     * @param spirv    the compiler's output
     * @return the record the rest of the road reads
     */
    @Redirect(method = "createIntermediary", require = 1,
            at = @At(value = "INVOKE",
                    target = "Lcom/mojang/blaze3d/vulkan/glsl/IntermediaryShaderModule;createFromSpirv("
                            + "Ljava/lang/String;Ljava/nio/ByteBuffer;)"
                            + "Lcom/mojang/blaze3d/vulkan/glsl/IntermediaryShaderModule;"))
    private static IntermediaryShaderModule metallum$hook(String filename, ByteBuffer spirv)
            throws ShaderCompileException {
        MetallumShaderModules.Hook hook = MetallumShaderModules.hook();
        ByteBuffer patched = hook.patchSpirv(filename, spirv);
        IntermediaryShaderModule module =
                IntermediaryShaderModule.createFromSpirv(filename, patched);
        narrow(hook, filename, patched, module);

        return module;
    }

    /**
     * Drops the declared sampled images the integration says the entry point never reaches.
     * <p>
     * The removal is on the live list so that everything downstream - the bind-group walk, the
     * layout, the argument-buffer decision - sees the narrowed set and no copy of it. A list that
     * cannot be read, or an entry whose name cannot be, leaves the module alone: a narrowing is an
     * optimisation and never a reason to refuse a pack.
     */
    @Unique
    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void narrow(MetallumShaderModules.Hook hook, String filename, ByteBuffer spirv,
                               IntermediaryShaderModule module) {
        try {
            List samplers = (List) SAMPLERS.invoke(module);
            if (samplers == null || samplers.isEmpty()) {
                return;
            }

            List<String> declared = new ArrayList<>(samplers.size());
            for (Object sampler : samplers) {
                String name = (String) SAMPLER_NAME.invoke(sampler);
                if (name == null) {
                    return;
                }
                declared.add(name);
            }

            List<String> unreached = hook.unreachedSampledImages(filename, spirv, declared);
            if (unreached == null || unreached.isEmpty()) {
                return;
            }

            samplers.removeIf(sampler -> {
                try {
                    return unreached.contains(SAMPLER_NAME.invoke(sampler));
                } catch (IllegalAccessException | InvocationTargetException e) {
                    return false;
                }
            });
        } catch (IllegalAccessException | InvocationTargetException | RuntimeException ignored) {
            // Deliberately silent and deliberately non-fatal: the module keeps every declared
            // sampler, which is the state this project was in before the seam existed.
        }
    }

    @Unique
    private static Method entryName() {
        try {
            Class<?> entry = Class.forName("com.mojang.blaze3d.vulkan.glsl.SpvSampler", false,
                    ShaderModuleHookMixin.class.getClassLoader());
            Method name = entry.getDeclaredMethod("name");
            name.setAccessible(true);

            return name;
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    @Unique
    private static Method method(Class<?> owner, String name) {
        try {
            return owner.getMethod(name);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }
}
