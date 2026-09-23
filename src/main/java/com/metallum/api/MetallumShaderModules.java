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
