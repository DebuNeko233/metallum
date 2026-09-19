package com.metallum.render;

/**
 * Which command generation is executing the frame.
 * <p>
 * A token and not a version number: Apple has no API version to ask for, and what a device runs is a set
 * of families - which is why the engine's own F3 line answers "Metal 4" from the newest family a device
 * answers for. This is the same answer, for the path rather than for the screen.
 */
public enum MetalExecutionGeneration {

    /** {@code MTLCommandQueue}, {@code MTLCommandBuffer}, one submission a frame with completion handlers. */
    METAL_3("metal3"),

    /** {@code MTL4CommandQueue}, {@code MTL4CommandBuffer}, one commit a frame with commit feedback. */
    METAL_4("metal4");

    private final String token;

    MetalExecutionGeneration(final String token) {
        this.token = token;
    }

    /** The word logs and probe lines carry, because a name with a space in it is not a field value. */
    public String token() {
        return token;
    }
}
