package com.metallum.render.execution;

import com.metallum.Metallum;
import com.metallum.mtl.MTLCompileOptions;
import com.metallum.mtl.MTLDevice;
import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;

/**
 * Which MSL profile this system's Metal 3 path actually accepts, asked by compiling something tiny.
 * <p>
 * The ladder is walked newest first - 3.2, then 3.1, then 3.0 - and the first version that compiles is the
 * session's. A version string is not an answer: what a system accepts depends on the OS and on the toolchain
 * the library was built against, and the failure this exists to prevent is a Metal 3 session that emits 4.0
 * and discovers it on a machine nobody has here. It is three library compilations of one function, once per
 * session, and the answer is then fixed for every shader the session compiles.
 */
@Environment(EnvType.CLIENT)
public final class MetalShaderLanguageProbe {

    /** The smallest thing that can be compiled: no resources, one entry point, MSL 3 has everything it uses. */
    private static final String PROBE_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            fragment float4 metallum_profile_probe() {
                return float4(0.0);
            }
            """;

    private static final Msg NEW_LIBRARY_WITH_SOURCE =
            Msg.of("newLibraryWithSource:options:error:", true, ADDRESS, ADDRESS, ADDRESS, ADDRESS);
    private MetalShaderLanguageProbe() {
    }

    /**
     * The newest Metal 3 profile the device accepts.
     *
     * @param device the device to compile against
     * @return the newest accepted profile, or the oldest one where none of them compiled
     */
    public static MetalShaderLanguageProfile newestMetal3Profile(final MTLDevice device) {
        for (MetalShaderLanguageProfile candidate : MetalShaderLanguageProfile.METAL3_LADDER) {
            if (compiles(device, candidate)) {
                return candidate;
            }
        }

        Metallum.LOGGER.warn("Metal shader profile: none of the Metal 3 profiles compiled a probe library, so "
                + "{} is used and a pipeline that fails to build will say so", MetalShaderLanguageProfile.MSL_3_0.token());
        return MetalShaderLanguageProfile.MSL_3_0;
    }

    /** Whether one profile compiles the probe library, which is the only question worth asking of it. */
    private static boolean compiles(final MTLDevice device, final MetalShaderLanguageProfile profile) {
        try (AutoreleasePool _ = AutoreleasePool.push();
             Arena arena = Arena.ofConfined();
             MTLCompileOptions options = new MTLCompileOptions()) {
            options.setLanguageVersion(profile.metalLanguageVersion());
            MemorySegment errorOut = arena.allocate(ADDRESS);
            MemorySegment source = ObjC.nsString(PROBE_MSL);
            MemorySegment library = NEW_LIBRARY_WITH_SOURCE.sendPtr(device.handle(), source, options.handle(), errorOut);
            ObjC.release(source);
            if (ObjC.isNil(library)) {
                // Said at debug and not as an error: a version a system does not take is what the ladder is
                // for, and three error lines in every log would train a reader to ignore the fourth.
                Metallum.LOGGER.debug("Metal shader profile: {} refused ({})", profile.token(),
                        MTLDevice.errorText(errorOut));
                return false;
            }

            ObjC.release(library);
            return true;
        } catch (RuntimeException failed) {
            return false;
        }
    }
}
