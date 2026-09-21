package com.metallum.render.execution;

import com.metallum.Metallum;

import java.util.Locale;

/**
 * What the player or the developer asked for, which is not the same question as what the device can do.
 * <p>
 * <strong>{@code FORCE_METAL3} is what a launch that says nothing gets</strong>, because Metal 4 is opt-in:
 * the user-facing choice belongs to the pack host's settings screen, which writes this property only when
 * the JVM has not been given one, so an ordinary startup is Metal 3 unless a player asked otherwise or a
 * developer named a generation. {@code AUTO} stays for the development and diagnostic harnesses that ask
 * for it by name, and is no longer anybody's default: its answer is a selection the migration has not
 * finished and a reference shell that encodes through Metal 3, which is not a thing to hand a player who
 * did not ask for it.
 * <p>
 * The two forced values exist so that a path can be exercised on hardware that could run either, and a
 * forced value that the device cannot satisfy is a startup failure rather than a silent fallback - a test
 * that quietly ran the other path is worse than no test, because its numbers would be believed.
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

    /**
     * What a launch that names no generation gets, which is the stable path.
     * <p>
     * Metal 4 is experimental and opt-in, so the absent property is Metal 3 and not a capability question:
     * a player who never opens the setting runs the path every other session of this engine has run, and a
     * device capable of Metal 4 is not on its own a reason to give them an unfinished frame path.
     */
    public static final MetalExecutionPreference DEFAULT = FORCE_METAL3;

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
     * generation would be a session whose numbers are about a path nobody chose. An absent property is not
     * a typo and says nothing - it is the ordinary case and its answer is {@link #DEFAULT}.
     */
    public static MetalExecutionPreference read() {
        String asked = System.getProperty(PROPERTY);
        if (asked == null) {
            return DEFAULT;
        }

        String word = asked.trim().toLowerCase(Locale.ROOT);
        for (MetalExecutionPreference preference : values()) {
            if (preference.word.equals(word)) {
                return preference;
            }
        }

        Metallum.LOGGER.warn("{} says \"{}\", which is not one of auto, metal3 or metal4, so {} is used",
                PROPERTY, asked, DEFAULT.word);
        return DEFAULT;
    }
}
