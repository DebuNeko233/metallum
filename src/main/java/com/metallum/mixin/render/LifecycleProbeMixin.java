package com.metallum.mixin.render;

import com.metallum.Metallum;
import com.metallum.render.shared.MetalLifecycleSchedule;
import com.mojang.blaze3d.platform.Window;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.multiplayer.ClientPacketListener;
import org.lwjgl.glfw.GLFW;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * A diagnostic, off unless {@code -Dmetallum.lifecycleProbe=<name>@<tick>,...} is set: drives the lifecycle
 * transitions section 71 lists, from inside the client, on a schedule the launch line states.
 * <p>
 * <strong>It exists because those transitions need input this machine refuses.</strong> The gate asks for F3+T, a
 * shader-pack switch, leaving and rejoining a world, a dimension change, a resize, a fullscreen change and a
 * shutdown - and every one of them was pressed by a keyboard that the automation permission here will not drive
 * (`osascript` is denied with -1743). A gate that cannot be run is not a gate, so the transitions are driven
 * through the client's own methods instead: {@code Window.setWindowed} and {@code toggleFullScreen} for the two
 * window changes, {@code Minecraft.delayTextureReload} for F3+T's own path, {@code clearClientLevel} for leaving,
 * and GLFW's window-close flag for a quit that is the close button's rather than a signal's.
 * <p>
 * <strong>It is a driver and not a test.</strong> Each action logs a marker line where it fires and, where the
 * action completes somewhere else, a second line where it completed - a reload's future, for instance - so the
 * log proves the transition happened rather than that it was asked for. Nothing here asserts an outcome: what a
 * stale table, a use-after-release or a lost pipeline looks like is the frame path's own business, and the
 * observations are read out of the same log.
 * <p>
 * With the property unset this is one field read per client tick.
 */
@Mixin(Minecraft.class)
public class LifecycleProbeMixin {

    /**
     * The schedule, parsed once from the property: {@code resize@300,fullscreen@500,reload@900,close@1400}.
     * <p>
     * Ticks rather than frames, because the transitions run while there may be no world to render - after
     * {@code clearClientLevel} the client is on a title screen and still ticking, which is where the shutdown has
     * to be driven from.
     */
    private static final List<MetalLifecycleSchedule.Action> SCHEDULE =
            MetalLifecycleSchedule.parse(System.getProperty("metallum.lifecycleProbe", ""));

    /** The names fired so far, so a tick that arrives twice cannot fire one twice. */
    private final Set<String> metallum$fired = new LinkedHashSet<>();

    /** Whether the schedule itself has been written to the log, which is one line and not one per tick. */
    private boolean metallum$announced;

    private long metallum$ticks;

    @Inject(method = "tick()V", at = @At("HEAD"))
    private void metallum$driveLifecycle(final CallbackInfo ci) {
        if (SCHEDULE.isEmpty()) {
            return;
        }

        // The instance is the mixin's own target rather than Minecraft.getInstance(), so a tick that arrives
        // before the static is set - which the first ticks of a session do - cannot dereference null here.
        Minecraft minecraft = (Minecraft) (Object) this;
        long tick = ++this.metallum$ticks;
        if (!this.metallum$announced) {
            this.metallum$announced = true;
            Metallum.LOGGER.info("lifecycle probe: {} action(s) scheduled - {}", SCHEDULE.size(), SCHEDULE);
        }

        for (MetalLifecycleSchedule.Action action : SCHEDULE) {
            if (action.tick() > tick || !this.metallum$fired.add(action.name())) {
                continue;
            }
            Metallum.LOGGER.info("lifecycle probe: firing '{}' at client tick {}", action.name(), tick);
            try {
                apply(minecraft, action.name());
            } catch (Throwable failure) {
                // A refused transition is a finding and not a crash: the point of the probe is to find out what
                // the frame path does across a lifecycle edge, and a throw here would end the session before the
                // edge could be read.
                Metallum.LOGGER.warn("lifecycle probe: '{}' failed at client tick {} - {}",
                        action.name(), tick, failure);
            }
        }
    }

    /** One transition, through the client's own entry point for it. */
    private static void apply(final Minecraft minecraft, final String name) {
        Window window = minecraft.getWindow();
        switch (name) {
            // A resize to an extent the session did not start at: every render target, every table and every
            // argument buffer that names one has to be rebuilt, which is section 72's subject.
            case "resize" -> window.setWindowed(1600, 900);
            case "fullscreen" -> window.toggleFullScreen();
            // Back out of fullscreen, at the session's own extent, so the two window changes are both taken.
            case "windowed" -> window.setWindowed(1280, 720);
            // F3+T's own path, submitted to the client thread exactly as the key does. Its future is what proves
            // the reload finished, and finishing is when the compilation caches are cleared - which is the moment
            // a compiled artifact and the argument encoders asked of its functions stop being current.
            case "reload" -> minecraft.delayTextureReload().thenRun(() ->
                    Metallum.LOGGER.info("lifecycle probe: 'reload' completed - the compilation caches have been"
                            + " cleared and the pack has been rebuilt through this path"));
            case "leave" -> minecraft.clearClientLevel(new TitleScreen());
            // The one transition that needs a command rather than a method: a dimension change is a server-side
            // teleport, and the client's own road to one is the chat command it would send if a player typed it.
            // It therefore needs a world with cheats on - the log says so plainly when it does not, and the
            // command's own feedback is what distinguishes "the dimension changed" from "the command was
            // refused", so both are read out of the same session rather than assumed.
            case "dimension" -> sendDimensionChange(minecraft);
            // The window's own close flag, which is what the close button sets: the game loop leaves on its own
            // terms and the whole shutdown path runs, which a signal does not do.
            case "close" -> GLFW.glfwSetWindowShouldClose(window.handle(), true);
            default -> Metallum.LOGGER.warn("lifecycle probe: '{}' is not a transition this probe knows", name);
        }
    }

    /**
     * Sends the teleport a player would type, and says which road it took.
     * <p>
     * The target is stated in the schedule's own terms - the nether, at the origin, high enough to be inside the
     * world - so the dimension the frame path is asked to render is not this method's opinion. A session with no
     * connection (the probe's own {@code leave} action ran first) is not a fault of the frame path, and the log
     * says which of the two it was.
     */
    private static void sendDimensionChange(final Minecraft minecraft) {
        ClientPacketListener connection = minecraft.getConnection();
        if (connection == null) {
            Metallum.LOGGER.warn("lifecycle probe: 'dimension' was scheduled with no connection, so there is no"
                    + " world to change the dimension of - the schedule is at fault, not the frame path");
            return;
        }
        Metallum.LOGGER.info("lifecycle probe: sending the dimension change a player would type -"
                + " 'execute in minecraft:the_nether run tp @s 0 80 0'");
        connection.sendCommand("execute in minecraft:the_nether run tp @s 0 80 0");
    }
}
