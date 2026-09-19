package com.metallum.render.execution;

import com.metallum.Metallum;

import java.util.List;

/**
 * The MSL version a shader compiler is told to emit, chosen with the generation that will execute it.
 * <p>
 * A profile is two numbers that must agree: what SPIRV-Cross targets and what
 * {@code MTLCompileOptions.languageVersion} asks Metal to accept. They are one record because a session
 * whose translator emits 4.0 while the compiler is told 3.2 is a session with pipelines that do not
 * compile - or, worse, compile into something neither side intended.
 * <p>
 * <strong>Metal 3 must not be handed 4.0.</strong> Metal 4's surface is only on systems whose Metal 3 path
 * also accepts 4.0 today, so a hardcoded 4.0 works here and would break on the older system the Metal 3 path
 * exists for - which is exactly why the ladder below is probed rather than assumed. The probe compiles a
 * tiny library at each version and takes the newest that the system accepts; nothing is inferred from a
 * version string.
 */
public record MetalShaderLanguageProfile(int spirvCrossMslVersion, long metalLanguageVersion, String token) {

    /** {@code SPVC_MSL_VERSION_3_0} and {@code MTLLanguageVersion3_0}: {@code (3 << 16) + 0}. */
    public static final MetalShaderLanguageProfile MSL_3_0 =
            new MetalShaderLanguageProfile(0x030000, (3L << 16) + 0L, "msl3.0");

    /** The same pairing at 3.1. */
    public static final MetalShaderLanguageProfile MSL_3_1 =
            new MetalShaderLanguageProfile(0x030100, (3L << 16) + 1L, "msl3.1");

    /** The same pairing at 3.2, which is the newest profile a Metal 3 path may use. */
    public static final MetalShaderLanguageProfile MSL_3_2 =
            new MetalShaderLanguageProfile(0x030200, (3L << 16) + 2L, "msl3.2");

    /** The pairing for Metal 4, whose toolchain is the one this engine's translator was written against. */
    public static final MetalShaderLanguageProfile MSL_4_0 =
            new MetalShaderLanguageProfile(0x040000, (4L << 16) + 0L, "msl4.0");

    /** Newest first, which is the order the probe walks: a system that takes 3.2 must not be asked for 3.0. */
    public static final List<MetalShaderLanguageProfile> METAL3_LADDER =
            List.of(MSL_3_2, MSL_3_1, MSL_3_0);

    private static volatile MetalShaderLanguageProfile selected = MSL_4_0;

    /**
     * Fixes the profile for the session, said out loud.
     * <p>
     * Called once, after the generation is known and before any shader is compiled: every later compilation
     * - a pack program, a compute kernel, a built-in pipeline - reads the same answer, because a session
     * that changed profiles half way would have two caches that cannot be compared and pipelines that were
     * built against neither.
     */
    public static void select(final MetalShaderLanguageProfile profile, final String why) {
        selected = profile;
        Metallum.LOGGER.info("Metal shader profile: {} selected ({})", profile.token(), why);
    }

    /** The session's profile, which is the one every compilation uses. */
    public static MetalShaderLanguageProfile selected() {
        return selected;
    }
}
