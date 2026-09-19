package com.metallum.render.execution;

import com.metallum.Metallum;
import com.metallum.render.MetalExecutionTelemetry;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Chooses the command generation, from capabilities and nothing else.
 * <p>
 * The rules are the specification's, and each of them exists because of a way this can go wrong rather than
 * for symmetry:
 *
 * <ul>
 *   <li>{@code AUTO} prefers the newest generation the device can actually run - the full minimum contract,
 *       the startup probe that made and submitted the objects, and the feature parity that keeps the render
 *       scale working - and falls back to Metal 3 otherwise, because a fallback is what makes a new path
 *       shippable at all;</li>
 *   <li>{@code FORCE_METAL3} is refused only if Metal 3 itself is unavailable, since its whole purpose is to
 *       keep the old path measurable on hardware that could run either;</li>
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
     * The decision, recorded where the engine says which generation is executing.
     *
     * @param preference   what the launch asked for
     * @param capabilities what the device answered
     * @return what to execute and why
     */
    public static Decision select(final MetalExecutionPreference preference,
                                  final MetalDeviceCapabilities capabilities) {
        Decision decision = decide(preference, capabilities);
        MetalExecutionTelemetry.selected(decision.selected(), decision.reason());
        return decision;
    }

    /**
     * The rules themselves, as a pure function, so that what the device answered can be reasoned about
     * without a device: the forced-and-unsatisfiable cases are the ones worth being able to see.
     */
    public static Decision decide(final MetalExecutionPreference preference,
                                  final MetalDeviceCapabilities capabilities) {
        boolean usable = capabilities.metal4MinimumContract()
                && capabilities.metal4CommandBuffer()
                && capabilities.metal4RenderEncoder()
                && capabilities.metal4ArgumentTable()
                && capabilities.metalFxParityForMetal4();

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
                            "the device satisfies the Metal 4 minimum contract and keeps the scaler, so the "
                                    + "newer generation is preferred", capabilities);
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
        if (!capabilities.metalFxParityForMetal4()) {
            missing.append(" (the Metal 4 scaler is missing while the Metal 3 one works)");
        }
        return missing.isEmpty() ? "" : missing.toString();
    }

    /** One line for the log, before the telemetry line that names the answer. */
    public static void say(final MetalDeviceCapabilities capabilities) {
        Metallum.LOGGER.info("Metal device capabilities: {}", capabilities.summary());
    }
}
