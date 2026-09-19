package com.metallum.render;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * The binding layout a translation is produced against: where push constants go, and how many argument-buffer
 * slots the layout reserves.
 * <p>
 * Both are **Metal 3 layout policy**, not shared semantics - they describe how this generation lays bindings out,
 * and Metal 4's argument tables need not keep the same slots. They are a value passed into translation rather
 * than constants the translator reads from a generation's artifact, so the translator can be asked to produce
 * MSL for a different layout without being rewritten.
 */
@Environment(EnvType.CLIENT)
record TranslationLayout(int pushConstantSlot, int argumentBufferSlotCount) {
}
