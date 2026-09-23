package com.metallum.api;

import java.nio.ByteBuffer;
import java.util.List;

/**
 * The narrow seam through which a shader-pack integration applies its own meaning to a stage, without
 * this project having to know what a shader pack is.
 * <p>
 * Metallum owns everything about turning a stage into Metal: the GLSL is compiled to SPIR-V, the
 * SPIR-V is reflected, converted to MSL and handed to Apple's compiler. But two points in that road
 * are not Metallum's to decide, because what happens there is a property of the pack and not of the
 * GPU:
 * <ul>
 * <li><strong>Between the compiler and the reflection.</strong> A pack's SPIR-V may have to be
 * rewritten before anything reads it - an integration may need variables initialised to the value the
 * reference implementations give them, and debug names attached. Doing it after the reflection would
 * change a module the reflection had already described, so the seam is before it.</li>
 * <li><strong>Which declared resources the stage really uses.</strong> A pack's programs share an
 * include that declares every sampler any of them might want, and this road binds what the module
 * declares. How many of them a stage actually reaches is a question about the pack's text and its
 * dead branches, and it decides whether the layout fits the hardware's per-stage slots or has to go
 * through an argument buffer. Metallum can see the declaration; only the integration knows which
 * declared name is code the pack meant.</li>
 * </ul>
 * <p>
 * <strong>The hook is optional and its absence is not an error.</strong> A session with no integration
 * registered compiles every stage exactly as it is, which is what this project does on its own; a
 * hook that answers nothing for a stage leaves that stage alone. Nothing here is allowed to make a
 * compile fail because an integration was not installed.
 * <p>
 * <strong>Nothing on this interface names a pack, a Minecraft type or a Metal handle.</strong> Strings
 * and bytes cross it, which is what lets the caller live in a repository that must not know this one's
 * internals and this one live in a repository that must not know a shader pack's.
 */
public final class MetallumShaderModules {

    /** Increment only when this hook contract changes incompatibly. */
    public static final int API_VERSION = 1;

    /** The hook contract's version, for a caller that has to check before it hands one over. */
    public static int apiVersion() {
        return API_VERSION;
    }

    /**
     * An integration's own half of a stage compile.
     * <p>
     * Every method has a default that changes nothing, so an integration implements only the half it
     * needs and a stage it has no opinion about goes through untouched.
     */
    public interface Hook {

        /**
         * Handed the compiler's own module type, once, before the first stage compiles.
         * <p>
         * <strong>This is for an integration that keeps a module on disk.</strong> Reading a module
         * back out of a store means rebuilding one, and the fields that make one up are package
         * private types an integration may not name. It cannot obtain the module's class either: a
         * store hit is asked for before any module of the session exists. So the one side that has
         * the type hands it over, and everything else can be read off it - the type's own record
         * components say which list holds what, and each list's generic type says what it holds.
         * <p>
         * An integration that keeps nothing ignores this. Called once per session at most.
         */
        default void moduleType(final Class<?> moduleType) {
        }

        /**
         * Whether the compiler should write debug information into the stages it builds.
         * <p>
         * Asked once, while the compiler is constructed, because the option it drives can only be
         * turned on and never off: it is a property of the compiler instance rather than of a
         * compile, and the instance is the one every stage of the session goes through. A hook that
         * answers false makes every module of the session cheaper to build and every stack or dump
         * that names a shader variable poorer; true is what the compiler does on its own.
         */
        default boolean wantsShaderDebugInfo() {
            return true;
        }

        /**
         * A stage compile is starting, on this thread.
         * <p>
         * Paired with {@link #endCompile}, and not guaranteed to arrive: a compile that throws ends
         * without one. An integration that brackets state for the length of a compile therefore has
         * to make this call reset whatever it sets, rather than assume the pair.
         */
        default void beginCompile(final String label) {
        }

        /**
         * The key this unit's compiled module may be kept under, or null to keep none.
         * <p>
         * The unit is identified by its debug name, the source text it was built from and the stage
         * it is; an integration that keys on more than that hashes whatever else it needs into the
         * answer. <strong>Null means the store is off for this unit</strong>, which is also the
         * answer for everything the integration does not own - the game's own shaders and another
         * mod's go through this same compiler, and keeping them would be keeping another project's
         * work under this one's key.
         */
        default String moduleKey(final String label, final String source, final String stage) {
            return null;
        }

        /**
         * The module this integration already has for that key, or null to build one.
         * <p>
         * A non-null answer is used as the compile's result: nothing is compiled, nothing is patched
         * and nothing is narrowed, so what comes back has to be a module built the same way this
         * road would have built it. Null sends the compile on its way, and the integration is then
         * expected to have counted a module as being built.
         */
        default Object cachedModule(final String key, final String label) {
            return null;
        }

        /**
         * A module this road has just built, offered to the integration to keep.
         * <p>
         * Called only for a unit whose {@link #moduleKey} was not null, and only on the road that
         * really built one, so it is never offered a module that came out of a store.
         *
         * @param module what was built, opaque to this side and to be handed back verbatim from
         *               {@link #cachedModule}
         */
        default void keepModule(final String key, final String label, final Object module) {
        }

        /**
         * The stage compile that began at {@link #beginCompile} is over, on this thread.
         */
        default void endCompile(final String label) {
        }

        /**
         * Rewrites the SPIR-V a stage has just compiled to, before it is reflected or converted.
         * <p>
         * Called on the thread doing the compile, once per stage, with the buffer the compiler
         * produced. An implementation may return the buffer it was handed, and it may free that
         * buffer if it returns a replacement - this road keeps no reference to the old one.
         *
         * @param label the debug name the compile was given, which says whose stage this is
         * @param spirv the compiler's output, native order, position at nought
         * @return the SPIR-V to reflect; the argument itself where nothing is to change
         */
        default ByteBuffer patchSpirv(final String label, final ByteBuffer spirv) {
            return spirv;
        }

        /**
         * Which of a stage's declared sampled images its entry point never reaches.
         * <p>
         * The declared names are what the reflection found in the module, in the order it found
         * them; the answer is the subset of those names that no reachable instruction uses. A name
         * the answer omits keeps its slot, so answering nothing is always safe - it costs slots, not
         * correctness.
         *
         * @param label    the debug name the compile was given
         * @param spirv    the same module's SPIR-V, after {@link #patchSpirv}
         * @param declared every sampled image the module declares, by name
         * @return the declared names the entry point never reaches, or an empty list to keep them all
         */
        default List<String> unreachedSampledImages(final String label, final ByteBuffer spirv,
                                                    final List<String> declared) {
            return List.of();
        }
    }

    /** What a session with no integration installed answers: nothing changes, nothing is dropped. */
    private static final Hook NONE = new Hook() {
    };

    private static volatile Hook hook = NONE;

    private MetallumShaderModules() {
    }

    /**
     * Installs an integration's hook, replacing any hook already installed.
     *
     * @param installed the hook, or null to remove the one in force
     */
    public static void install(final Hook installed) {
        hook = installed == null ? NONE : installed;
    }

    /** The hook in force, never null: the no-op one until an integration installs its own. */
    public static Hook hook() {
        return hook;
    }
}
