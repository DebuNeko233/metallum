import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.metal4.MTL4Probe;
import com.metallum.render.metal4.Metal4ExecutionProvider;

/**
 * One Metal 4 capability probe, in a process with nothing else in it.
 *
 * <p>The capability probe has read {@code argumentTable=false render=false} on some sessions and not on
 * others, and always early in a session, which is the shape of a cold-first-use fault. The client cannot
 * answer that question: it runs the probe behind a Minecraft launch that costs about seventy seconds, it
 * caches the answer for the life of the process, and the two arms of a comparison are minutes apart. This
 * process does nothing else - no Minecraft, no world, no pack, no window, no frame - so a cold attempt is a
 * JVM start, a device, one probe and an exit.
 *
 * <p>What it prints is one machine-readable line per attempt, because the thing being counted is a
 * distribution over processes and nothing here should need a log parser:
 *
 * <pre>
 * M4_PROBE_RESULT process=&lt;n&gt; attempt=&lt;n&gt; mode=&lt;raw|production&gt; success=&lt;bool&gt;
 *                 retried=&lt;bool&gt; stage=&lt;ok|stage&gt; reason=&lt;text&gt;
 *                 canMakeAndSubmit=&lt;bool&gt; canBindAndDraw=&lt;bool&gt; familyMetal4=&lt;bool&gt; queueSelector=&lt;bool&gt;
 *                 argumentTableSelector=&lt;bool&gt; deviceCreation=&lt;ok|failure&gt; deviceName=&lt;name&gt;
 *                 sampled=&lt;bool&gt; sampledReason=&lt;text&gt; sampledDraw=&lt;bool&gt; sampledDrawReason=&lt;text&gt;
 *                 provider=&lt;text&gt; epochMs=&lt;n&gt; probeMs=&lt;n&gt; elapsedMs=&lt;n&gt;
 * </pre>
 *
 * <p>Exit code 0 when every attempt in this process passed, 1 when a probe attempt failed, 2 when the
 * device could not be made at all - so the driver counts failures without reading a line.
 */
public final class Metal4ColdProbe {

    /** {@code MTLGPUFamilyMetal4}, the SDK's own value (MTLDevice.h). */
    private static final long FAMILY_METAL4 = 5002L;

    private Metal4ColdProbe() {
    }

    public static void main(final String[] args) {
        // A label and not a number: the driver passes the cold process's ordinal, and `warm` for the one
        // process that repeats the probe, so the field says which population a line belongs to.
        String index = args.length > 0 ? args[0] : "0";
        int attempts = args.length > 1 ? Integer.parseInt(args[1]) : 1;
        // Two populations and they answer different questions. `raw` is one attempt, which is how the fault
        // itself is measured - the first multi-encoder sequence of a process, and nothing else. `production`
        // is the path the capability record now reads, which asks once more where the first answer is no.
        // Measuring only the fixed path would hide the fault; measuring only the raw one would say nothing
        // about what the client decides.
        String mode = args.length > 2 ? args[2] : "raw";
        boolean production = "production".equals(mode);

        long startNanos = System.nanoTime();
        String deviceCreation = "ok";
        MTLDevice device = null;

        try {
            device = MTLDevice.createSystemDefault();
        } catch (Throwable throwable) {
            deviceCreation = throwable.getClass().getSimpleName() + "(" + oneLine(throwable.getMessage()) + ")";
        }

        if (device == null) {
            System.out.println("M4_PROBE_RESULT process=" + index
                    + " attempt=1 success=false stage=device reason=no-system-default-device"
                    + " canMakeAndSubmit=false canBindAndDraw=false"
                    + " familyMetal4=false queueSelector=false argumentTableSelector=false"
                    + " deviceCreation=" + deviceCreation + " deviceName=none"
                    + " epochMs=0 probeMs=0 elapsedMs=" + millis(startNanos));
            System.exit(2);
        }

        // The one thing the client does before it probes that a standalone process does not: the probe draws
        // with the engine's own builtin pipelines, so the device they are built on has to be handed over
        // first. Measured by this harness's first run - without it every probe fails at stage `exception`
        // with `MTLBuiltinPipelines.device is null` - and `close()` at the end gives them back.
        MTLBuiltinPipelines.init(device);

        String deviceName = oneLine(device.name()).replace(' ', '_');
        boolean familyMetal4 = device.supportsFamily(FAMILY_METAL4);
        boolean queueSelector = device.respondsTo("newMTL4CommandQueue");
        boolean argumentTableSelector =
                MTL4Probe.respondsTo(device.handle(), "newArgumentTableWithDescriptor:error:")
                        || MTL4Probe.respondsTo(device.handle(), "newArgumentTableWithDescriptor:");

        // The provider skeleton, asked on the real device and reported once per process: its queue factory is
        // real, and its two frame halves must refuse by name rather than return something a caller would use.
        // This is section 110's "native smoke passed + real Apple Silicon passed" for the skeleton, and it
        // costs one queue and three calls.
        String provider;
        try {
            Metal4ExecutionProvider metal4 = new Metal4ExecutionProvider();
            // Held in a final local because the device is assigned inside a try above, so it is not
            // effectively final and cannot be captured by the two lambdas below.
            MTLDevice probeDevice = device;
            long queue = metal4.commandQueue(probeDevice);
            provider = "queue=" + (queue != 0L ? "ok" : "nil")
                    + ",state=" + refusal(() -> metal4.createExecutionState(probeDevice))
                    + ",encoder=" + refusal(() -> metal4.createFrameEncoder(null, null, null));
        } catch (Throwable throwable) {
            provider = "queue=exception(" + throwable.getClass().getSimpleName() + ")";
        }

        String sampledReason = "-";
        String sampledDrawReason = "-";
        boolean allPassed = true;
        for (int attempt = 1; attempt <= attempts; attempt++) {
            long probeStart = System.nanoTime();
            boolean makeAndSubmit = MTL4Probe.canMakeAndSubmit(device);
            // The fourth render smoke's DRAWN half, asked first of the three deep probes and reported in a
            // field of its own: it is a sequence of its own - a pattern pass, an encoder barrier, a sampled
            // pass, one commit, a readback - and a failure in it must not be reported as a failure of the
            // capability sequence below, whose per-process distribution is what the AUTO blocker is measured
            // with. Asked before that sequence because the stage and reason fields below belong to it.
            boolean sampledDraw = makeAndSubmit && MTL4Probe.canDrawSampledTexture(device);
            if (!sampledDraw) {
                sampledDrawReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // The fourth render smoke's binding half, asked on every attempt: a table made for one texture and
            // one sampler, and both accepted. Reported beside the draw probe rather than folded into it, so a
            // failure says which of the two contracts broke.
            boolean sampled = makeAndSubmit && MTL4Probe.canBindSampledTexture(device);
            if (!sampled) {
                sampledReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // Mirrors the capability record's own order: the bind probe is only asked where the first one
            // passed, so a failure here reports the stage that really stopped the sequence.
            boolean bindAndDraw = makeAndSubmit
                    && (production ? MTL4Probe.canBindAndDrawPersistently(device) : MTL4Probe.canBindAndDraw(device));
            String stage = MTL4Probe.lastFailureStage();
            String reason = MTL4Probe.lastFailure();
            boolean success = makeAndSubmit && bindAndDraw;
            allPassed &= success;

            System.out.println("M4_PROBE_RESULT process=" + index
                    + " attempt=" + attempt
                    + " mode=" + mode
                    // Whether this attempt needed the second one. In raw mode it is always false, which is
                    // what makes a production run's true readable rather than assumed.
                    + " retried=" + MTL4Probe.lastRetried()
                    + " success=" + success
                    + " stage=" + (stage == null ? "ok" : stage)
                    + " reason=" + (reason == null ? "-" : oneLine(reason))
                    + " canMakeAndSubmit=" + makeAndSubmit
                    + " canBindAndDraw=" + bindAndDraw
                    + " familyMetal4=" + familyMetal4
                    + " queueSelector=" + queueSelector
                    + " argumentTableSelector=" + argumentTableSelector
                    + " deviceCreation=" + deviceCreation
                    + " deviceName=" + deviceName
                    + " sampled=" + sampled
                    + " sampledReason=" + sampledReason.replace(' ', '_')
                    + " sampledDraw=" + sampledDraw
                    + " sampledDrawReason=" + sampledDrawReason.replace(' ', '_')
                    + " provider=" + provider.replace(' ', '_')
                    // The absolute time, so a failure can be lined up against whatever else the machine was
                    // doing: a fault that clusters in a run of consecutive processes is a fact about the
                    // environment as much as about the probe, and a per-process duration cannot show that.
                    + " epochMs=" + System.currentTimeMillis()
                    + " probeMs=" + millis(probeStart)
                    + " elapsedMs=" + millis(startNanos));
        }

        // The pipelines the probe drew with go back before the process does, so an attempt that is counted
        // as passing is also an attempt that released what it made.
        MTLBuiltinPipelines.close();

        // The process is the unit of measurement and the device goes with it: `MTLCreateSystemDefaultDevice`
        // hands back a +1 object this class does not own a release for, and a probe process that outlives its
        // attempt would be measuring something else. Said here rather than left to be inferred.
        System.out.flush();
        System.exit(allPassed ? 0 : 1);
    }

    /**
     * What one provider entry point did: refused by name, returned something, or failed some other way. A
     * provider that answered where it has no implementation would be a silent half-frame, so "returned" is
     * reported as loudly as a wrong exception.
     */
    private static String refusal(final java.util.function.Supplier<?> call) {
        try {
            call.get();
            return "returned";
        } catch (Metal4ExecutionProvider.Unimplemented refused) {
            return "refused(" + refused.stage() + ")";
        } catch (Throwable other) {
            return "wrong(" + other.getClass().getSimpleName() + ")";
        }
    }

    private static String millis(final long sinceNanos) {
        return String.format(java.util.Locale.ROOT, "%.1f", (System.nanoTime() - sinceNanos) / 1_000_000.0);
    }

    /** The probe's own reason text can carry newlines, which would break the one-line contract. */
    private static String oneLine(final String text) {
        if (text == null) {
            return "-";
        }

        return text.replace('\n', ' ').replace('\r', ' ').trim().replace(' ', '_');
    }
}
