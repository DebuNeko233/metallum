package com.metallum.render.shared;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

/**
 * Which stages a binding belongs to, as a mask.
 * <p>
 * This is generation-neutral: "a uniform the vertex stage reads" means the same thing to Metal 3's binding code
 * and to whatever Metal 4 does with argument tables, so the vocabulary lives in the shared layer rather than on
 * one generation's compiled artifact - which is where the translator used to read it from, and what made a
 * translation helper depend on a Metal 3 object.
 */
@Environment(EnvType.CLIENT)
public final class MetalShaderStages {

    public static final int VERTEX = 1;
    public static final int FRAGMENT = 2;
    public static final int ALL = VERTEX | FRAGMENT;

    private MetalShaderStages() {
    }
}
