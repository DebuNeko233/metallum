package com.metallum.render.execution;

import com.metallum.Metallum;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Chooses the command generation, from capabilities and nothing else.
 * <p>
 * The rules are the specification's, and each of them exists because of a way this can go wrong rather than
 * for symmetry:
 *
 * <ul>
 *   <li>{@code AUTO} prefers the newest generation the device can actually run - the minimum contract, which
 *       is the startup probe that made and submitted the objects - and falls back to Metal 3 otherwise, because
 *       a fallback is what makes a new path shippable at all;</li>
 *   <li>{@code FORCE_METAL3} is refused only if Metal 3 itself is unavailable, since its whole purpose is to
 *       keep the old path measurable on hardware that could run either;</li>
 *   <li>{@code PREFER_METAL4} - what the settings row writes - takes Metal 4 where the core contract is
 *       satisfied and Metal 3, said out loud, where it is not: a player asking for an experimental path is not
 *       demanding a failed launch;</li>
 *   <li>{@code FORCE_METAL4} that the device cannot satisfy is a <strong>startup failure</strong> and not a
 *       quiet fallback: a run whose numbers are believed must be a run of the path that was asked for.</li>
 * </ul>
 *
 * <p>
 * Nothing here reads a device name. Apple Silicon reports the same families across its generations, so a
 * decision keyed off a chip name would be a table of hardware instead of a question about capability - and
 * the name is already in the log, where it belongs.
 */
@Environment(EnvType.CLIENT)
public final class MetalExecutionSelector {

    /**
     * What was chosen, and why, in words a log line can carry.
     *
     * @param selected   the generation to execute
     * @param preference what was asked for
     * @param reason     why this answer, which a fallback has to say out loud
     * @param capabilities what the device answered
     */
    public record Decision(MetalApiGeneration selected, MetalExecutionPreference preference, String reason,
                           MetalDeviceCapabilities capabilities) {
    }

    /** Thrown where a forced preference cannot be satisfied, rather than falling back silently. */
    public static final class UnsatisfiedPreferenceException extends IllegalStateException {
        public UnsatisfiedPreferenceException(final String message) {
            super(message);
        }
    }

    private MetalExecutionSelector() {
    }

    /**
     * The decision, and nothing else.
     * <p>
     * It records nothing: this call decides which generation was <em>selected</em>, and the generation that
     * <em>executes</em> is decided where the execution services are built. Writing the selection into the
     * session's record of what runs is the fault that made a Metal 3 frame report itself as Metal 4, so that
     * record is written by {@code MetalDevice}, which knows both facts.
     *
     * @param preference   what the launch asked for
     * @param capabilities what the device answered
     * @return what to execute and why
     */
    public static Decision select(final MetalExecutionPreference preference,
                                  final MetalDeviceCapabilities capabilities) {
        return decide(preference, capabilities);
    }

    /**
     * The rules themselves, as a pure function, so that what the device answered can be reasoned about
     * without a device: the forced-and-unsatisfiable cases are the ones worth being able to see.
     */
    public static Decision decide(final MetalExecutionPreference preference,
                                  final MetalDeviceCapabilities capabilities) {
        // The core contract decides whether Metal 4 can run, and nothing optional is in it. The Metal 4
        // spatial scaler used to be: a device whose Metal 4 core answered yes on every clause but whose
        // scaler was missing was refused the whole generation, which made one optional effect decide whether
        // the frame path existed. It does not - the render scale has a road of its own for a device without
        // the scaler (`MetalFx`'s parities, and the pack host's bilinear fallback below 100 per cent), and a
        // percentage setting is not a reason to hand a capable device the older generation. So the scaler is
        // an OPTIONAL capability: `metalFxParityForMetal4()` is still answered and still logged, and the
        // decision no longer reads it.
        boolean usable = capabilities.metal4MinimumContract()
                && capabilities.metal4CommandBuffer()
                && capabilities.metal4RenderEncoder()
                && capabilities.metal4ArgumentTable();

        return switch (preference) {
            case FORCE_METAL3 -> {
                if (!capabilities.metal3MinimumContract()) {
                    throw new UnsatisfiedPreferenceException(
                            "metallum.execution=metal3 was asked for, but this device does not answer for the "
                                    + "Metal 3 family, so there is no old path to run either");
                }
                yield new Decision(MetalApiGeneration.METAL3, preference,
                        "Metal 3 was forced for this launch", capabilities);
            }
            case PREFER_METAL4 -> {
                if (usable) {
                    yield new Decision(MetalApiGeneration.METAL4, preference,
                            "Metal 4 was preferred by the player and this device satisfies its core contract"
                                    + optionalScalerNote(capabilities), capabilities);
                }
                if (!capabilities.metal3MinimumContract()) {
                    throw new UnsatisfiedPreferenceException(
                            "Metal 4 was preferred and no generation can run here: this device satisfies neither"
                                    + " the Metal 4 core contract nor the Metal 3 family ("
                                    + capabilities.summary() + ")");
                }
                // The fallback the word names, said in the words a reader of the log needs: which was asked
                // for, that it was not selected, why, and what runs instead.
                yield new Decision(MetalApiGeneration.METAL3, preference,
                        "Metal 4 was preferred by the user but was not selected: the device does not satisfy the"
                                + " Metal 4 core contract" + whyNot(capabilities) + " - falling back to Metal 3",
                        capabilities);
            }
            case FORCE_METAL4 -> {
                if (!usable) {
                    throw new UnsatisfiedPreferenceException(
                            "metallum.execution=metal4 was asked for, and this device does not satisfy the "
                                    + "Metal 4 minimum contract: " + capabilities.summary());
                }
                yield new Decision(MetalApiGeneration.METAL4, preference,
                        "Metal 4 was forced for this launch, and the device satisfies its minimum contract",
                        capabilities);
            }
            case AUTO -> {
                if (usable) {
                    yield new Decision(MetalApiGeneration.METAL4, preference,
                            capabilities.metalFxParityForMetal4()
                                    ? "the device satisfies the Metal 4 minimum contract and keeps the scaler, so "
                                            + "the newer generation is preferred"
                                    : "the device satisfies the Metal 4 minimum contract, so the newer generation"
                                            + " is preferred" + optionalScalerNote(capabilities), capabilities);
                }
                if (!capabilities.metal3MinimumContract()) {
                    throw new UnsatisfiedPreferenceException(
                            "no generation can run here: the device answers for neither the Metal 4 minimum "
                                    + "contract nor the Metal 3 family (" + capabilities.summary() + ")");
                }
                yield new Decision(MetalApiGeneration.METAL3, preference,
                        "the device does not satisfy the Metal 4 minimum contract" + whyNot(capabilities)
                                + ", so Metal 3 is used", capabilities);
            }
        };
    }

    /**
     * What a Metal 4 session loses where its scaler is missing, said as a note and not as a refusal.
     * <p>
     * The scaler is an optional capability: the render scale has its own road for a device without it, so a
     * missing one costs the accelerated upscale and nothing else, and the line says so rather than leaving a
     * reader to work out why a Metal 4 frame's render scale took the fallback road.
     */
    private static String optionalScalerNote(final MetalDeviceCapabilities capabilities) {
        return capabilities.metalFxParityForMetal4()
                ? ""
                : "; the Metal 4 scaler is missing while the Metal 3 one works, which costs the render-scale"
                        + " setting its accelerated road and nothing else";
    }

    /** Which clause of the contract failed, because "it did not qualify" is not a diagnosis. */
    private static String whyNot(final MetalDeviceCapabilities capabilities) {
        StringBuilder missing = new StringBuilder();
        if (!capabilities.metal4Family()) {
            missing.append(" (no Metal 4 family)");
        }
        if (!capabilities.metal4CommandQueue()) {
            missing.append(" (no newMTL4CommandQueue)");
        }
        if (!capabilities.metal4CommandBuffer()) {
            missing.append(" (no command buffer that begins, ends and commits)");
        }
        if (!capabilities.metal4RenderEncoder()) {
            missing.append(" (no render encoder)");
        }
        if (!capabilities.metal4ComputeEncoder()) {
            missing.append(" (no compute encoder)");
        }
        if (!capabilities.metal4ArgumentTable()) {
            missing.append(" (no argument table)");
        }
        // The scaler is deliberately absent from this list: it is not a clause of the contract that decides
        // whether Metal 4 can run, so it may not appear as a reason the generation was refused. What a
        // missing scaler costs is said where the decision is taken, as a note on a Metal 4 session.
        return missing.isEmpty() ? "" : missing.toString();
    }

    /** One line for the log, before the telemetry line that names the answer. */
    public static void say(final MetalDeviceCapabilities capabilities) {
        Metallum.LOGGER.info("Metal device capabilities: {}", capabilities.summary());
    }
}
