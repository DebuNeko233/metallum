package com.metallum.mixin;

import net.fabricmc.loader.api.FabricLoader;
import org.objectweb.asm.tree.ClassNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class MetallumMixinConfigPlugin implements IMixinConfigPlugin {
    private static final String PREFERRED_GRAPHICS_API_MIXIN =
            "com.metallum.mixin.render.PreferredGraphicsApiMixin";
    private static final String VIDEO_SETTINGS_SCREEN_MIXIN =
            "com.metallum.mixin.render.VideoSettingsScreenMixin";
    /**
     * The seam a shader-pack integration applies its own meaning to a stage through.
     * <p>
     * Named here for the reason above and one of its own: this mixin is the only place the
     * integration is ever called from, and a build where it silently does not apply looks exactly
     * like a build with no integration installed - every pack compiles, every picture is drawn, and
     * the one difference is a stage this engine rewrote and this road did not. That is a wrong
     * picture with nothing in the log, which is the failure mode the list exists to prevent.
     */
    private static final String SHADER_MODULE_HOOK_MIXIN =
            "com.metallum.mixin.render.ShaderModuleHookMixin";
    /**
     * The lifecycle driver, which section 71's gate needs and this machine's input cannot drive.
     * <p>
     * It is named here because this plugin is a gate and not a formality: a mixin listed in the config but not
     * named below is never applied, and the failure is silent - the session runs, the property has no effect, and
     * the log carries no line to say why. That cost a measurement round, so the list is where a new diagnostic has
     * to be added and the reason lives rather than being remembered.
     */
    private static final String LIFECYCLE_PROBE_MIXIN =
            "com.metallum.mixin.render.LifecycleProbeMixin";

    /**
     * The client's tick, counted for the frame probe's windows.
     * <p>
     * It is named here for the same reason the lifecycle driver is: a mixin in the config and not in this list is
     * never applied, silently. This one matters to a *reading* rather than to a transition - a frame-probe window
     * is a fixed frame count and this client's frame is not the same work every frame (7 render passes in the
     * steady state, 13 on the frame that coincides with a client tick), so a window that cannot say how many
     * ticks it covered cannot say whether two arms sampled the same slice of the client's life.
     */
    private static final String CLIENT_TICK_PROBE_MIXIN =
            "com.metallum.mixin.render.ClientTickProbeMixin";

    /**
     * The client's own picture of its frame, taken when a file asks for one.
     * <p>
     * Named here for the third time and the same reason: a mixin in the config and not in this list is never
     * applied, silently, and this one's silence would be a measurement's - the performance harness would fall
     * back to photographing the display and say so in a line nobody would connect to the missing class.
     */
    private static final String SCREENSHOT_PROBE_MIXIN =
            "com.metallum.mixin.render.ScreenshotProbeMixin";

    private boolean isMacOs;

    @Override
    public void onLoad(String mixinPackage) {
        String osName = System.getProperty("os.name", "");
        this.isMacOs = osName.toLowerCase(Locale.ROOT).contains("mac");
    }

    @Override
    public String getRefMapperConfig() {
        return null;
    }

    @Override
    public boolean shouldApplyMixin(String targetClassName, String mixinClassName) {
        if (!this.isMacOs) {
            return false;
        }
        if (mixinClassName.contains(".mixin.sodium.")) {
            return FabricLoader.getInstance().isModLoaded("sodium");
        }
        return PREFERRED_GRAPHICS_API_MIXIN.equals(mixinClassName)
                || VIDEO_SETTINGS_SCREEN_MIXIN.equals(mixinClassName)
                || SHADER_MODULE_HOOK_MIXIN.equals(mixinClassName)
                || LIFECYCLE_PROBE_MIXIN.equals(mixinClassName)
                || CLIENT_TICK_PROBE_MIXIN.equals(mixinClassName)
                || SCREENSHOT_PROBE_MIXIN.equals(mixinClassName);
    }

    @Override
    public void acceptTargets(Set<String> myTargets, Set<String> otherTargets) {
    }

    @Override
    public List<String> getMixins() {
        return null;
    }

    @Override
    public void preApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {
    }

    @Override
    public void postApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {
    }
}
