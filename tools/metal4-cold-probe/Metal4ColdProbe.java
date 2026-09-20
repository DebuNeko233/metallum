import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLDevice;
import com.metallum.render.execution.MetalShaderLanguageProfile;
import com.metallum.mtl.metal4.MTL4Probe;
import com.metallum.render.metal4.Metal4ExecutionProvider;
import com.metallum.render.shared.MetalExecutionState;
import com.mojang.blaze3d.GpuFormat;
import com.mojang.blaze3d.PrimitiveTopology;
import com.mojang.blaze3d.pipeline.ColorTargetState;
import com.mojang.blaze3d.pipeline.CompiledRenderPipeline;
import com.mojang.blaze3d.pipeline.RenderPipeline;
import com.mojang.blaze3d.shaders.ShaderSource;
import com.mojang.blaze3d.shaders.ShaderType;

import java.util.Optional;

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
 *                 ring=&lt;bool&gt; ringReason=&lt;text&gt;
 *                 attachments=&lt;bool&gt; attachmentsReason=&lt;text&gt;
 *                 layout=&lt;bool&gt; layoutReason=&lt;text&gt;
 *                 copy=&lt;bool&gt; copyReason=&lt;text&gt;
 *                 depth=&lt;bool&gt; depthReason=&lt;text&gt;
 *                 provider=&lt;text&gt; epochMs=&lt;n&gt; probeMs=&lt;n&gt; elapsedMs=&lt;n&gt;
 * </pre>
 *
 * <p>Exit code 0 when every attempt in this process passed, 1 when a probe attempt failed, 2 when the
 * device could not be made at all - so the driver counts failures without reading a line.
 */
public final class Metal4ColdProbe {

    /** The fixture's vertex shader: a full-screen triangle whose uv is its own corner, so nothing is bound. */
    private static final String PROBE_VERTEX_GLSL = """
            #version 450
            layout(location = 0) out vec2 probeUv;
            void main() {
                vec2 corner = vec2(float((gl_VertexIndex << 1) & 2), float(gl_VertexIndex & 2));
                gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0);
                probeUv = corner;
            }
            """;

    /** The fixture's fragment shader: a colour that depends on the vertex stage, so neither is a constant. */
    private static final String PROBE_FRAGMENT_GLSL = """
            #version 450
            layout(location = 0) in vec2 probeUv;
            layout(location = 0) out vec4 probeColor;
            void main() {
                probeColor = vec4(probeUv, 0.25, 1.0);
            }
            """;

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
        // real, its execution state is a real object whose one unanswerable operation refuses by name, and its
        // frame encoder needs the engine's device, which a bare process does not have. This is section 110's
        // "native smoke passed + real Apple Silicon passed" for the skeleton, and it costs one queue and a few
        // calls.
        String provider;
        try {
            Metal4ExecutionProvider metal4 = new Metal4ExecutionProvider();
            // Held in a final local because the device is assigned inside a try above, so it is not
            // effectively final and cannot be captured by the lambdas below.
            MTLDevice probeDevice = device;
            long queue = metal4.commandQueue(probeDevice);
            String stateOutcome;
            String stateMethods;
            try {
                MetalExecutionState state = metal4.createExecutionState(probeDevice);
                stateOutcome = "ok";
                // The state compiles now, but compiling needs a pipeline and a shader source, and a bare
                // process has no way to make either - so the chain's own device proof is its own milestone and
                // is recorded as an omission here rather than asked with nulls. What is asked is the rest of
                // the neutral contract.
                stateMethods = "compile:not-asked(needs-a-pipeline-and-a-shader-source)"
                        + ",evict:" + refusal(() -> state.evictCachedPipelines(pipeline -> false))
                        + ",clear:" + refusal(() -> {
                            state.clearCachesAfterGpuCompletion();
                            return null;
                        })
                        + ",close:" + refusal(() -> {
                            state.close();
                            return null;
                        });
            } catch (Throwable throwable) {
                stateOutcome = "exception(" + throwable.getClass().getSimpleName() + ")";
                stateMethods = "-";
            }
            // The encoder is deliberately not asked, which is a fact about this process rather than a gap: it is
            // built from the engine's device, which a bare process cannot make, and asking with nulls would
            // raise a NullPointerException that reads as a device fault.
            provider = "queue=" + (queue != 0L ? "ok" : "nil")
                    + ",state=" + stateOutcome
                    + ",stateMethods=" + stateMethods
                    + ",encoder=not-asked(needs-the-engine-device)";
        } catch (Throwable throwable) {
            provider = "queue=exception(" + throwable.getClass().getSimpleName() + ")";
        }

        // The compilation chain's own device proof: a pipeline description and a shader source, both made here.
        // The fixture is built before the probe loop because building it does no native work, and the compile
        // itself runs AFTER the deep probes inside each attempt - deliberately, because those probes have to stay
        // the process's first native work: that is what the cold-fault distribution is a distribution of, and a
        // warm-up in front of them would quietly change the thing being measured.
        MetalExecutionState compileState = new Metal4ExecutionProvider().createExecutionState(device);
        RenderPipeline compileFixture = RenderPipeline.builder()
                .withLocation("m4_probe")
                .withVertexShader("m4_probe_vs")
                .withFragmentShader("m4_probe_fs")
                .withColorTargetState(new ColorTargetState(Optional.empty(), GpuFormat.RGBA8_UNORM,
                        ColorTargetState.WRITE_ALL))
                .withPrimitiveTopology(PrimitiveTopology.TRIANGLES)
                .build();
        ShaderSource compileSource = (id, type) -> type == ShaderType.VERTEX
                ? PROBE_VERTEX_GLSL
                : PROBE_FRAGMENT_GLSL;

        String sampledReason = "-";
        String sampledDrawReason = "-";
        String ringReason = "-";
        String attachmentsReason = "-";
        String layoutReason = "-";
        String copyReason = "-";
        String depthReason = "-";
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
            // The frame's allocator rule, measured before any frame encoder is built over it: twelve frames
            // over three slots, each slot reset only after its own completion value was observed, and every
            // frame's pixel its own. A field of its own, for the same reason the drawn smoke is.
            boolean ring = makeAndSubmit && MTL4Probe.canReuseAllocatorSlots(device);
            if (!ring) {
                ringReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // The pass's own half of the MRT smoke: four colour attachments described through the frame's own
            // pass encoder, each with its own load, store and clear, read back slot by slot.
            boolean attachments = makeAndSubmit && MTL4Probe.canCarryColorAttachments(device);
            if (!attachments) {
                attachmentsReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // The new model's core: a whole layout bound through one table a stage - a vertex buffer with its
            // stride and a uniform on one stage, a uniform, a texture and a sampler on the other - then a draw,
            // a scissor and a readback of both sides of it.
            boolean layout = makeAndSubmit && MTL4Probe.canBindALayout(device);
            if (!layout) {
                layoutReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // The copy path: a pattern's region copied to another texture's other half, and the whole texture
            // copied into a second one, both read back - which is what a frame's uploads, downloads and copies
            // are made of on this command model.
            boolean copy = makeAndSubmit && MTL4Probe.canCopyTextureRegions(device);
            if (!copy) {
                copyReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            }
            // The depth attachment and its clear, which is where a pass that a frame's depth work needs begins.
            boolean depth = makeAndSubmit && MTL4Probe.canClearDepth(device);
            if (!depth) {
                depthReason = MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
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

            // The chain, asked once per attempt: the first attempt compiles (the game's GLSL compiler, the
            // shared translator, this generation's native pipeline state) and the later ones answer from the
            // cache, which is itself one of the things this reports.
            String compile = "-";
            try {
                MetalShaderLanguageProfile.select(MetalShaderLanguageProfile.MSL_3_2,
                        "the cold probe compiles its own pipeline through the Metal 4 chain");
                CompiledRenderPipeline compiled = compileState.getOrCompilePipeline(compileFixture, compileSource);
                compile = "ok(valid=" + compiled.isValid() + ")";
            } catch (Throwable throwable) {
                compile = "failed(" + throwable.getClass().getSimpleName() + ": " + oneLine(throwable.getMessage())
                        + ")";
            }


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
                    + " ring=" + ring
                    + " ringReason=" + ringReason.replace(' ', '_')
                    + " attachments=" + attachments
                    + " attachmentsReason=" + attachmentsReason.replace(' ', '_')
                    + " layout=" + layout
                    + " layoutReason=" + layoutReason.replace(' ', '_')
                    + " copy=" + copy
                    + " copyReason=" + copyReason.replace(' ', '_')
                    + " depth=" + depth
                    + " depthReason=" + depthReason.replace(' ', '_')
                    + " provider=" + provider.replace(' ', '_')
                    + " compile=" + compile.replace(' ', '_')
                    // The absolute time, so a failure can be lined up against whatever else the machine was
                    // doing: a fault that clusters in a run of consecutive processes is a fact about the
                    // environment as much as about the probe, and a per-process duration cannot show that.
                    + " epochMs=" + System.currentTimeMillis()
                    + " probeMs=" + millis(probeStart)
                    + " elapsedMs=" + millis(startNanos));
        }

        // The compilation state, then the pipelines the probe drew with: both go back before the process does, so
        // an attempt that is counted as passing is also an attempt that released what it made.
        compileState.close();
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
