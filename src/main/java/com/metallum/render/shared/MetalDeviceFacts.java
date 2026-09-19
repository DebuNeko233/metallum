package com.metallum.render.shared;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import java.lang.foreign.MemorySegment;

/**
 * The device facts a generation's encoder may ask for.
 * <p>
 * The frame path used to read these through package access - {@code MetalCommandEncoder} called
 * {@code device.useLabels()} ten times and the native device handle four - which works only while the encoder
 * and the device sit in one package. Moving the encoder therefore needed exactly these members, and widening
 * them by hand is what the failed moves did; a contract says instead what a generation may ask the device.
 */
@Environment(EnvType.CLIENT)
public interface MetalDeviceFacts {

    /** Whether native objects should carry debug labels. */
    boolean useLabels();

    /** The device's native handle, for the objects a generation makes from it. */
    MemorySegment metalDeviceHandle();

}
