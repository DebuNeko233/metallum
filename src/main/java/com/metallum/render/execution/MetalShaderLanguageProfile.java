package com.metallum.render.execution;

/**
 * The MSL version the shader compiler targets, which has to be chosen with the execution generation.
 * <p>
 * A profile is not a preference and not a version table: it is what SPIRV-Cross is told to emit, and a
 * profile newer than the generation's toolchain can refuse is a pipeline that does not compile. Today the
 * engine emits one profile for both generations, which is correct only while both run on the same system -
 * so this enum exists to be <em>selected with the generation</em> and carries one value until the shader
 * profile milestone gives it the older one that Metal 3 on an older macOS needs.
 */
public enum MetalShaderLanguageProfile {

    /** The profile the engine emits today. */
    MSL_4_0("msl4.0");

    private final String token;

    MetalShaderLanguageProfile(final String token) {
        this.token = token;
    }

    public String token() {
        return token;
    }
}
