package com.metallum.render.execution;

/**
 * What the machine is, for the log and for nothing else.
 * <p>
 * <strong>A device name is not a selection input.</strong> Apple Silicon reports the same GPU families
 * across its generations, so a selector keyed off "M4" or "M5" would be a table of hardware rather than a
 * question about capability - and it would be wrong the day a chip this engine has never seen answers the
 * same selectors. The name is recorded because a run's log should say what it ran on.
 *
 * @param osVersion  the system's version, which is also a fast pre-rejection before a full probe
 * @param deviceName the GPU's name, for the log
 */
public record MetalSystemProfile(String osVersion, String deviceName) {

    public static MetalSystemProfile of(final String deviceName) {
        return new MetalSystemProfile(System.getProperty("os.version", "").trim(), deviceName);
    }

    /** Whether the system is new enough for Metal 4 to be possible at all, as a quick pre-rejection. */
    public boolean mayProvideMetal4() {
        int major = 0;
        int dot = this.osVersion.indexOf('.');
        String head = dot < 0 ? this.osVersion : this.osVersion.substring(0, dot);
        try {
            major = Integer.parseInt(head);
        } catch (NumberFormatException unreadable) {
            // A version this cannot read is not a reason to refuse: the device probe is the authority and
            // this is only here to keep a full probe off systems that cannot possibly answer it.
            return true;
        }

        // Metal 4 arrived with macOS 26; the SDK header spells it `API_AVAILABLE(macos(26.0))`.
        return major >= 26;
    }
}
