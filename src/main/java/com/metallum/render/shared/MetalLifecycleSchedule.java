package com.metallum.render.shared;

import java.util.ArrayList;
import java.util.List;

/**
 * The lifecycle probe's schedule, parsed from {@code -Dmetallum.lifecycleProbe}.
 * <p>
 * <strong>It lives outside the mixin package and outside the mixin, and both were learned the hard way.</strong>
 * A mixin's nested types are merged into the target class, and the first version of this declared the record
 * inside the mixin. The first
 * version of this declared the record inside the mixin, and Mixin relocated it into
 * {@code net.minecraft.client.Minecraft} - which does not carry it in its {@code InnerClasses} attribute, so every
 * access threw {@code IncompatibleClassChangeError} and the schedule line came out as
 * {@code [!!!net.minecraft.client.Minecraft$Action$75e25708...@5eed1a62=>java.lang.IncompatibleClassChangeError...]}.
 * The actions still fired, because the record's accessors resolved; its {@code toString} did not. Moving it out
 * of the mixin but leaving it in {@code com.metallum.mixin.render} was worse rather than better: the mixin
 * processor transforms every class in its configured package, so the next launch ended in
 * {@code ExceptionInInitializerError: Mixin transformation of ... LifecycleSchedule failed} before the client
 * loaded. Anything a mixin declares lives in the class it is applied to, and a type that is only *used* belongs
 * outside the package as well.
 * <p>
 * The syntax is {@code <name>@<tick>} entries separated by commas, so a launch line states the whole schedule:
 * {@code -Dmetallum.lifecycleProbe=resize@500,fullscreen@700,reload@1100,close@1700}. Ticks and not frames,
 * because two of the transitions run while there is no world to render.
 */
public final class MetalLifecycleSchedule {

    /** One scheduled transition, in the order the schedule will fire it. */
    public record Action(String name, long tick) {
    }

    private MetalLifecycleSchedule() {
    }

    /** The schedule a property asks for, sorted by tick. An unparseable entry is a launch-line fault, not a skip. */
    public static List<Action> parse(final String property) {
        List<Action> actions = new ArrayList<>();
        for (String entry : property.split(",")) {
            String trimmed = entry.trim();
            if (trimmed.isEmpty()) {
                continue;
            }
            int at = trimmed.indexOf('@');
            if (at <= 0 || at == trimmed.length() - 1) {
                throw new IllegalArgumentException("metallum.lifecycleProbe entry '" + trimmed
                        + "' is not <name>@<tick>");
            }
            actions.add(new Action(trimmed.substring(0, at), Long.parseLong(trimmed.substring(at + 1))));
        }
        actions.sort((left, right) -> Long.compare(left.tick(), right.tick()));
        return List.copyOf(actions);
    }
}
