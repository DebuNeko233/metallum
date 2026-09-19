package com.metallum.render.execution;

import com.metallum.Metallum;

import java.util.Locale;

/**
 * What the player or the developer asked for, which is not the same question as what the device can do.
 * <p>
 * {@code AUTO} is the default and may fall back; the two forced values exist so that a path can be
 * exercised on hardware that could run either, and a forced value that the device cannot satisfy is a
 * startup failure rather than a silent fallback - a test that quietly ran the other path is worse than no
 * test, because its numbers would be believed.
 */
public enum MetalExecutionPreference {

    /** Use the newest generation the device can actually run, Metal 3 otherwise. */
    AUTO("auto"),

    /** Use Metal 3 whatever the device can do, which is how the old path stays measurable. */
    FORCE_METAL3("metal3"),

    /** Use Metal 4 or fail at startup, which is how the new path is exercised deliberately. */
    FORCE_METAL4("metal4");

    /** The one property, read once at device creation. */
    public static final String PROPERTY = "metallum.execution";

    private final String word;

    MetalExecutionPreference(final String word) {
        this.word = word;
    }

    public String word() {
        return word;
    }

    /**
     * The preference this launch asks for.
     * <p>
     * A word nothing answers to is the default and says so: a typo that silently forced the wrong
     * generation would be a session whose numbers are about a path nobody chose.
     */
    public static MetalExecutionPreference read() {
        String asked = System.getProperty(PROPERTY, AUTO.word).trim().toLowerCase(Locale.ROOT);
        for (MetalExecutionPreference preference : values()) {
            if (preference.word.equals(asked)) {
                return preference;
            }
        }

        Metallum.LOGGER.warn("{} says \"{}\", which is not one of auto, metal3 or metal4, so {} is used",
                PROPERTY, asked, AUTO.word);
        return AUTO;
    }
}
