package com.metallum.render.execution;

/**
 * The command API surface a path is written against.
 * <p>
 * Two surfaces and not a version ladder: Metal 4 is a parallel API rather than an upgrade of Metal 3's
 * objects, which is why the engine carries two paths and asks this question once instead of versioning one.
 */
public enum MetalApiGeneration {

    /** {@code MTLCommandQueue}, one command buffer a frame, completion handlers, per-resource binds. */
    METAL3("metal3", "Metal 3"),

    /** {@code MTL4CommandQueue}, one commit a frame, commit feedback, argument tables, barriers. */
    METAL4("metal4", "Metal 4");

    private final String token;
    private final String label;

    MetalApiGeneration(final String token, final String label) {
        this.token = token;
        this.label = label;
    }

    /** The word a log line or a probe field carries: a name with a space in it is not a field value. */
    public String token() {
        return token;
    }

    /** The word a person reads. */
    public String label() {
        return label;
    }
}
