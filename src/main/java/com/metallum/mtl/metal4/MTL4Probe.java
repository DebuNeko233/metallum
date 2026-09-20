package com.metallum.mtl.metal4;

import com.metallum.Metallum;
import com.metallum.render.shared.AttachmentContents;
import java.util.List;
import com.metallum.render.shared.MetalShaderStages;
import com.metallum.render.shared.MetalResourceBinding;
import com.metallum.mtl.MTLFXSpatialScalerDescriptor;
import com.metallum.mtl.MTLIndexType;

import com.metallum.mtl.MTLTexture;

import com.metallum.mtl.MTLSamplerDescriptor;
import com.metallum.mtl.MTLSamplerMinMagFilter;
import com.metallum.mtl.MTLStorageMode;

import com.metallum.mtl.MTLPixelFormat;

import com.metallum.mtl.MTLCullMode;
import com.metallum.mtl.MTLDevice;

import com.metallum.mtl.MTLTextureDescriptor;

import com.metallum.mtl.MTLBuffer;

import com.metallum.mtl.MTLPrimitiveType;

import com.metallum.mtl.MTLBuiltinPipelines;

import com.metallum.objc.AutoreleasePool;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import org.jspecify.annotations.Nullable;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_BYTE;
import static java.lang.foreign.ValueLayout.JAVA_DOUBLE;
import static java.lang.foreign.ValueLayout.JAVA_FLOAT;
import static java.lang.foreign.ValueLayout.JAVA_INT;
import static java.lang.foreign.ValueLayout.JAVA_LONG;
import static java.lang.foreign.ValueLayout.JAVA_SHORT;

/**
 * Makes the Metal 4 core objects once, and lets them go.
 * <p>
 * The shape {@code MTLFXSpatialScalerDescriptor} was probed with, for a reason this class learned the hard
 * way: the first version of it sent {@code newCommandAllocatorWithDescriptor:} without asking, and the
 * device - which does support the Metal 4 family and does answer to {@code newMTL4CommandQueue} - answered
 * with an {@code NSInvalidArgumentException} that ended the process. The cause was not the device's subset
 * of its header but the name: the header's factory has an error out-parameter, so the selector is
 * {@code newCommandAllocatorWithDescriptor:error:} and the shorter name describes a method no object has.
 * Both are asked for now, and the descriptor-less {@code newCommandAllocator} is preferred where it is
 * offered. **A selector is the header's, out-parameters included** - and a probe that guesses a name
 * measures its own guess, which is how the argument table came to be recorded as something this device
 * could not make.
 * <p>
 * What is proven is reachability, encoding and submission: a queue of the new command structure, an
 * allocator for a command buffer's working memory, a command buffer begun on that allocator, a render pass
 * on a 64x64 colour target encoded into it and ended, and that buffer
 * **committed to the queue and waited for** - the queue signals a shared event after the committed work,
 * and the event's own CPU wait answers whether the GPU ran it. No frame path creates any of it, and the
 * whole probe is one submission at device creation.
 */
@Environment(EnvType.CLIENT)
public final class MTL4Probe {

    private static final Msg NEW_QUEUE = Msg.of("newMTL4CommandQueue", ADDRESS);
    private static final Msg NEW_ALLOCATOR = Msg.of("newCommandAllocator", ADDRESS);
    private static final Msg NEW_ALLOCATOR_WITH_ERROR =
            Msg.of("newCommandAllocatorWithDescriptor:error:", ADDRESS, ADDRESS, ADDRESS);
    private static final Msg NEW_ALLOCATOR_WITH_DESCRIPTOR = Msg.of("newCommandAllocatorWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg NEW_COMMAND_BUFFER = Msg.of("newCommandBuffer", ADDRESS);
    private static final Msg BEGIN = Msg.ofVoid("beginCommandBufferWithAllocator:", ADDRESS);
    private static final Msg END = Msg.ofVoid("endCommandBuffer");
    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);
    private static final Msg NEW_RENDER_PASS = Msg.of("new", ADDRESS);
    private static final Msg SET_TARGET_WIDTH = Msg.ofVoid("setRenderTargetWidth:", JAVA_LONG);
    private static final Msg SET_TARGET_HEIGHT = Msg.ofVoid("setRenderTargetHeight:", JAVA_LONG);
    private static final Msg COLOR_ATTACHMENTS = Msg.of("colorAttachments", ADDRESS);
    private static final Msg ATTACHMENT_AT = Msg.of("objectAtIndexedSubscript:", ADDRESS, JAVA_LONG);
    private static final Msg SET_TEXTURE = Msg.ofVoid("setTexture:", ADDRESS);
    private static final Msg SET_LOAD_ACTION = Msg.ofVoid("setLoadAction:", JAVA_LONG);
    /**
     * {@code MTLRenderPassColorAttachmentDescriptor.setClearColor:}, four doubles - {@code MTLClearColor} is
     * four doubles and arm64 passes them in registers, which is how {@code MTLRenderPassDescriptor} already
     * sends it. The Metal 4 descriptor's {@code colorAttachments} is that same class, read off this machine's
     * SDK header rather than assumed: {@code MTL4RenderPass.h:33} declares the property as
     * {@code MTLRenderPassColorAttachmentDescriptorArray}, so the attachment and its clear colour are the
     * Metal 3 ones.
     */
    private static final Msg SET_CLEAR_COLOR = Msg.ofVoid("setClearColor:",
            JAVA_DOUBLE, JAVA_DOUBLE, JAVA_DOUBLE, JAVA_DOUBLE);
    private static final Msg SET_STORE_ACTION = Msg.ofVoid("setStoreAction:", JAVA_LONG);
    private static final Msg RENDER_ENCODER = Msg.of("renderCommandEncoderWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg END_ENCODING = Msg.ofVoid("endEncoding");

    /** One colour target, big enough to be a render target and small enough to cost nothing. */
    private static final long TARGET_SIZE = 64L;
    private static final long USAGE_RENDER_TARGET = 4L;
    private static final long LOAD_DONT_CARE = 0L;

    /**
     * {@code MTLLoadActionClear}, the SDK's own value ({@code MTLRenderPass.h:35}). It is what makes this
     * probe's failures self-describing: with {@code DontCare} an unwritten pixel is undefined by the API's
     * contract, so a missed draw and a wrong colour read the same.
     */
    private static final long LOAD_CLEAR = 2L;

    /** What the second pass's clear leaves behind: black with an opaque alpha, which no draw here produces. */
    private static final int[] CLEAR_PIXEL = {0, 0, 0, 255};
    private static final long STORE_STORE = 1L;
    private static final Msg NEW_SHARED_EVENT = Msg.of("newSharedEvent", ADDRESS);
    private static final Msg COMMIT = Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG);
    private static final Msg SIGNAL_EVENT = Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG);
    private static final Msg WAIT_UNTIL_SIGNALED =
            Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg NEW_BUFFER = Msg.of("newBufferWithLength:options:", ADDRESS, JAVA_LONG, JAVA_LONG);
    private static final Msg SET_ARGUMENT_TABLE = Msg.ofVoid("setArgumentTable:atStages:", ADDRESS, JAVA_LONG);
    private static final Msg SET_RENDER_PIPELINE_STATE = Msg.ofVoid("setRenderPipelineState:", ADDRESS);
    private static final Msg DRAW =
            Msg.ofVoid("drawPrimitives:vertexStart:vertexCount:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
    /**
     * {@code MTL4CommandEncoder.barrierAfterStages:beforeQueueStages:visibilityOptions:} - the producer
     * barrier, read off this machine's SDK header ({@code MTL4CommandEncoder.h:91}): everything encoded in
     * the current encoder up to this point, on {@code afterStages}, completes before work encoded in
     * <em>subsequent</em> encoders on {@code beforeQueueStages} begins.
     * <p>
     * This is the difference between the two command models, and it is why a Metal 4 pass that samples a
     * target an earlier pass wrote encodes the dependency itself: the header documents the barrier as the
     * mechanism, and the migration plan's rule is to express the dependency before optimising it.
     */
    private static final Msg BARRIER = Msg.ofVoid("barrierAfterStages:beforeQueueStages:visibilityOptions:",
            JAVA_LONG, JAVA_LONG, JAVA_LONG);

    /** {@code MTLRenderStagesVertex}, the stage the clear pipeline's uniform is read on. */
    private static final long STAGE_VERTEX = 1L;

    /** {@code MTLStageFragment}, the stage a sampled texture and a sampler are read on. */
    private static final long STAGE_FRAGMENT = 2L;

    /** {@code MTLStageAll}, the conservative mask for "everything encoded so far" ({@code MTLCommandEncoder.h}). */
    private static final long STAGE_ALL = Long.MAX_VALUE;

    /** {@code MTL4VisibilityOptionDevice}: flush to the device coherence point, which is the safe option. */
    private static final long VISIBILITY_DEVICE = 1L;

    /** {@code MTLTextureUsageShaderRead}: a target another pass samples has to declare it. */
    private static final long USAGE_SHADER_READ = 1L;

    /** {@code MTLResourceStorageModeShared}, so the CPU can write the uniforms the pass reads. */
    private static final long STORAGE_SHARED = 0L;

    /** The clear pipeline's uniform block: depth, padding, then the colour it writes. */
    private static final long UNIFORM_LENGTH = 48L;

    /** Three {@code float4} corners: position in the first two, colour in the last two. */
    private static final long VERTEX_LENGTH = 48L;

    /** What {@code (0.25, 0.5, 0.75, 1.0)} is in {@code RGBA8Unorm}: the pixel the uniform draw produces. */
    private static final int[] EXPECTED_UNIFORM_PIXEL = {64, 128, 191, 255};

    /** {@code (0.25, 0.5, 0.5, 1.0)}: the colour only a draw that read its vertex buffer can produce. */
    private static final int[] EXPECTED_VERTEX_PIXEL = {64, 128, 128, 255};

    /** The edge of the sampled smoke's pattern: a {@link #TARGET_SIZE} target split into four quadrants. */
    private static final long PATTERN_EDGE = TARGET_SIZE / 2;

    /**
     * One pixel well inside each quadrant of the pattern, in the order {@link #EXPECTED_PATTERN} lists the
     * colours: top-left, top-right, bottom-left, bottom-right. The inset is what makes the readback a
     * question about a quadrant rather than about a seam.
     */
    private static final long[][] PATTERN_PIXELS = {
            {8L, 8L}, {PATTERN_EDGE + 8L, 8L}, {8L, PATTERN_EDGE + 8L},
            {PATTERN_EDGE + 8L, PATTERN_EDGE + 8L}};

    /**
     * What the pattern pass writes, quadrant by quadrant: red and green carry the quadrant's coordinates and
     * blue is the literal {@code 0.25} the source's own fill writes. The blue channel is what makes the
     * sampled readback distinguishable from every other pixel this probe produces - the clear colour, the
     * uniform draw's 191 and the vertex draw's 128 are all different from 64 - so a sample that reached the
     * wrong target or dropped the texture cannot read as success.
     */
    private static final int[][] EXPECTED_PATTERN = {
            {0, 0, 64, 255}, {255, 0, 64, 255}, {0, 255, 64, 255}, {255, 255, 64, 255}};

    /**
     * The pass that fills the sampled source: four quadrants, each a flat colour of its own.
     * <p>
     * A flat pattern and not a gradient, because the readback is compared channel by channel: a value that
     * arrives through interpolation would make the check a question about the driver's rounding as well as
     * about the binding. {@code in.position.xy} is in pixels of the target, so the quadrant a fragment is in
     * is a step of the same numbers the readback uses, and the top-left quadrant is the one at the low
     * coordinates - which is also what makes a flipped sample read as a flip rather than as a wrong colour.
     */
    private static final String PATTERN_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct PatternOut {
              float4 position [[position]];
            };

            vertex PatternOut metallum_pattern_probe_vs(uint vertexId [[vertex_id]]) {
              const float2 corners[3] = {
                float2(-1.0,  1.0),
                float2( 3.0,  1.0),
                float2(-1.0, -3.0)
              };

              PatternOut out;
              out.position = float4(corners[vertexId], 0.0, 1.0);
              return out;
            }

            fragment float4 metallum_pattern_probe_fs(PatternOut in [[stage_in]]) {
              float2 quadrant = step(float2(%d.0), in.position.xy);
              return float4(quadrant.x, quadrant.y, 0.25, 1.0);
            }
            """.formatted(PATTERN_EDGE);

    /**
     * The pass that samples the pattern back out of it, once, through an argument table.
     * <p>
     * The texture is read by the sampler with nearest filtering at the fragment's own position, so the
     * sample grid is the texel grid and the destination should hold the source: what the readback answers is
     * whether the table-bound texture, the table-bound sampler, the pipeline and the encoder work together,
     * and - because the source is a four-quadrant pattern - whether the sample arrived the right way up.
     */
    private static final String SAMPLED_DRAW_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct SampledOut {
              float4 position [[position]];
              float2 uv;
            };

            vertex SampledOut metallum_sampled_probe_vs(uint vertexId [[vertex_id]]) {
              const float2 corners[3] = {
                float2(-1.0,  1.0),
                float2( 3.0,  1.0),
                float2(-1.0, -3.0)
              };
              const float2 uvs[3] = {
                float2(0.0, 0.0),
                float2(2.0, 0.0),
                float2(0.0, 2.0)
              };

              SampledOut out;
              out.position = float4(corners[vertexId], 0.0, 1.0);
              out.uv = uvs[vertexId];
              return out;
            }

            fragment float4 metallum_sampled_probe_fs(
              SampledOut in [[stage_in]],
              texture2d<float> pattern [[texture(0)]],
              sampler nearest [[sampler(0)]]
            ) {
              return pattern.sample(nearest, in.uv);
            }
            """;

    /**
     * A pipeline whose colour comes out of a vertex buffer.
     * <p>
     * The positions are three float4s and the colour is two of their components, so a pixel that arrives is a
     * pixel that came through the table: a vertex buffer bound by address with an attribute stride is the
     * shape the engine's own terrain and entity draws bind, and it is the one shape the clear pass cannot
     * stand in for.
     */
    private static final String VERTEX_BUFFER_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct ProbeVertexOut {
              float4 position [[position]];
              float4 color;
            };

            vertex ProbeVertexOut metallum_vb_probe_vs(
              uint vertexId [[vertex_id]],
              const device float4* vertices [[buffer(0)]]
            ) {
              ProbeVertexOut out;
              out.position = float4(vertices[vertexId].xy, 0.0, 1.0);
              out.color = float4(vertices[vertexId].zw, 0.5, 1.0);
              return out;
            }

            fragment float4 metallum_vb_probe_fs(ProbeVertexOut in [[stage_in]]) {
              return in.color;
            }
            """;

    private MTL4Probe() {
    }


    /**
     * Whether a uniform bound by GPU address through an argument table reaches a draw, and what it draws.
     * <p>
     * This is the question the migration of the frame's own passes turns on, and it is a different question
     * from whether the command structure can be built: Metal 4's encoders have no binding methods at all, so
     * a pass that reads a buffer reads it through a table, and the table binds a buffer by
     * {@code gpuAddress} rather than by object. The engine's own clear pipeline is the pass used here - its
     * uniform declares {@code [[buffer(1)]]}, which is a slot a table can hold - and the pass is drawn into a
     * shared 64x64 target whose first pixel is then read back and compared with the colour the uniform asked
     * for. A draw that runs and a draw that drew what it was told are two different answers, and only the
     * second one is worth building on.
     *
     * @param device the device binding, asked for every selector before it is sent
     * @return whether a table-bound uniform drew the colour it was given
     */
    /**
     * Why the last {@link #canBindAndDraw(MTLDevice)} answered the way it did, or null when it worked.
     * <p>
     * It exists because a false negative and an absence looked identical: the capability record reads this
     * probe, so a transient failure in its first attempt at a Metal 4 argument table was recorded as "this
     * device cannot", and AUTO then chose Metal 3 - measured as two identical runs in one session selecting
     * different generations (arm a `argumentTable=false render=false`, arm b `argumentTable=true
     * render=true`, forty seconds apart on one device). A probe that can only say no cannot be told apart
     * from a device that can only do no.
     */
    /**
     * Whether the last persistent call had to ask twice, which is what makes the retry visible.
     * <p>
     * A retry that cannot be seen is a retry nobody can verify: the fix that answers the capability question
     * from the device rests on "the first attempt of a process can fail and the second does not", and a run
     * that only prints the verdict cannot show that the second attempt is what answered. This is that fact,
     * per call, for the harness and for the log.
     */
    public static boolean lastRetried() {
        return retried;
    }

    /** Whether the last {@link #canBindAndDrawPersistently} call asked twice. */
    private static boolean retried;

    public static String lastFailure() {
        return failure;
    }

    /**
     * Which stage of the probe the last answer stopped at, or null when it worked. Every stage name is a place
     * the probe can stop, so a failure is locatable rather than merely reported: the first version of this probe
     * collapsed a dozen exits - a nil render pass, an encoder that would not open, a target that was never made,
     * a submission that never signalled - into one `false`, which is why a capability record could disagree with
     * itself between two runs and say nothing about why.
     */
    public static String lastFailureStage() {
        return failureStage;
    }

    /**
     * Whether a table-bound draw works, asked once and once more if the first answer is no.
     * <p>
     * The first {@link #canBindAndDraw} of a process can fail at stage {@code pixel} - the second render
     * pass's whole contribution, its clear included, never reaching its target - and no later one ever has.
     * Measured: over 160 cold processes and 1100 later probes, every failure was the first attempt of its
     * process, and the one process that failed at attempt one passed attempts two to twenty. A capability
     * answer is a fact about the device and not about the first command buffer a process happens to submit,
     * so the question is put again once where that first answer is no.
     * <p>
     * <strong>The first attempt is logged either way, and its stage and reason are what the second attempt
     * is judged against.</strong> A retry that swallowed the first answer would take the fault off the
     * record, which is the one thing a registered intermittent must not do.
     * <p>
     * <strong>And the cause is not known.</strong> What is measured is that the first attempt in a process
     * can fail and later ones do not - with a command buffer already committed and completed in the same
     * process immediately before the failing sequence, which is what rules out a first-commit explanation.
     * The retry rests on that behaviour and not on an explanation of it.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return the second answer where the first was no, and the first where it was yes
     */
    public static boolean canBindAndDrawPersistently(final MTLDevice device) {
        retried = false;
        if (canBindAndDraw(device)) {
            return true;
        }

        retried = true;
        String stage = lastFailureStage();
        String reason = lastFailure();
        boolean second = canBindAndDraw(device);
        Metallum.LOGGER.warn("Metal 4 probe: the first attempt in this process failed at {} ({}), and the"
                + " second answered {} - the capability record reads the second", stage, reason, second);
        return second;
    }

    /**
     * Whether a sampled texture and a sampler can both be carried by one Metal 4 argument table.
     * <p>
     * This is the binding half of the migration plan's fourth render smoke - "a sampled texture and a sampler,
     * drawn as a fixed pattern, read back" - and it is the half the present sidecar has been exercising on the
     * real path since it landed, which is why it is asked here as well: a capability the frame path depends on
     * should be provable in a process that has no window in it. What it does NOT do is draw through them; the
     * sampled draw and its readback are the other half and are named as owed rather than implied by this.
     * <p>
     * Two tables are made and not one, because a table is made for a shape: a table asked for one texture and
     * one sampler is a different object from the buffer tables the other probes make, and the header's ceiling
     * on sampler slots is a property of the table rather than of this call.
     *
     * @return whether both resources were accepted by a table made to hold them
     */
    public static boolean canBindSampledTexture(final MTLDevice device) {
        failure = null;
        failureStage = null;
        MemorySegment texture = MemorySegment.NULL;
        MemorySegment sampler = MemorySegment.NULL;
        MTL4ArgumentTable sampled = null;
        try {
            try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
                descriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
                descriptor.width(SAMPLED_SIZE);
                descriptor.height(SAMPLED_SIZE);
                descriptor.usage(USAGE_RENDER_TARGET);
                descriptor.storageMode(MTLStorageMode.Shared);
                texture = device.newTexture(descriptor);
            }
            if (ObjC.isNil(texture)) {
                return failed("sampled", "newTextureWithDescriptor: answered nil for the " + SAMPLED_SIZE + "x"
                        + SAMPLED_SIZE + " RGBA8 source texture the sampler would read");
            }

            try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {
                descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.supportArgumentBuffers(true);
                sampler = device.newSamplerState(descriptor);
            }
            if (ObjC.isNil(sampler)) {
                return failed("sampled", "newSamplerStateWithDescriptor: answered nil, so nothing can carry the"
                        + " sampler the shader would declare");
            }

            sampled = MTL4ArgumentTable.create(device, 0L, 1L, 1L);
            if (sampled == null) {
                return failed("sampled", "a table asked for one texture and one sampler came back null");
            }

            if (!sampled.texture(texture)) {
                return failed("sampled", "the table refused setTexture:atIndex: for a texture it was made to hold");
            }
            if (!sampled.sampler(sampler)) {
                return failed("sampled", "the table refused setSamplerState:atIndex: for a sampler it was made to"
                        + " hold");
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("sampled", "making or binding the sampled pair threw " + threw);
        } finally {
            if (sampled != null) {
                sampled.close();
            }
            releaseIfPresent(texture);
            releaseIfPresent(sampler);
        }
    }

    /**
     * Whether a sampled texture and a sampler can be <em>drawn through</em> on the real device, and read back.
     * <p>
     * This is the drawn half of the migration plan's fourth render smoke - "a sampled texture and a sampler,
     * drawn as a fixed pattern, read back" - and the half {@link #canBindSampledTexture} recorded as owed. It
     * is a sequence of its own rather than a third pass in {@link #canBindAndDraw} so that the capability
     * record's own measured distribution is not restated by a new question: the two are reported apart and
     * fail apart.
     * <p>
     * The shape is the smallest one that has everything the frame's own passes need. A pattern pass renders
     * four flat quadrants into a 64x64 source that declares it is read by a shader; the pass ends with the
     * producer barrier the new command model requires of a dependency between encoders
     * ({@code MTL4CommandEncoder.barrierAfterStages:beforeQueueStages:visibilityOptions:}); a second pass, in
     * the <em>same</em> command buffer, samples that source through an argument table and draws it into a
     * target of its own; the command buffer is committed once, waited for through a shared event, and both
     * textures are read back pixel by pixel.
     * <p>
     * <strong>What this proves and what it does not.</strong> The binding half proved a table accepts a texture
     * and a sampler. This proves the whole chain carries them - table, texture, sampler, pipeline, encoder,
     * submission, readback - and, because the source is four quadrants of known colour, that the sample
     * arrived in the right place: a flipped or offset sample reads a different quadrant and is reported as
     * one. What it does not prove is anything about filtering beyond nearest, aniso or mip levels, none of
     * which this sequence binds.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether the pattern reached the source and the sample reached the destination, channel by channel
     */
    public static boolean canDrawSampledTexture(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("sampledDraw", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from, so no pass can be encoded");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment source = MemorySegment.NULL;
        MemorySegment destination = MemorySegment.NULL;
        MemorySegment sampler = MemorySegment.NULL;
        MemorySegment patternPipeline = MemorySegment.NULL;
        MemorySegment sampledPipeline = MemorySegment.NULL;
        MTL4ArgumentTable sampled = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("sampledDraw", "a Metal 4 queue, allocator, command buffer or shared event came back"
                        + " nil - queue=" + !ObjC.isNil(queue) + " allocator=" + !ObjC.isNil(allocator)
                        + " buffer=" + !ObjC.isNil(buffer) + " event=" + !ObjC.isNil(event));
            }

            try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
                descriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
                descriptor.width(TARGET_SIZE);
                descriptor.height(TARGET_SIZE);
                // RenderTarget *and* ShaderRead: this texture is rendered into by one pass and sampled by the
                // next, and a texture that does not declare the read is not one a shader may read. The
                // non-sampled targets below declare the render target alone, which is what they are.
                descriptor.usage(USAGE_RENDER_TARGET | USAGE_SHADER_READ);
                descriptor.storageMode(MTLStorageMode.Shared);
                source = device.newTexture(descriptor);
            }
            if (ObjC.isNil(source)) {
                return failed("sampledDraw", "newTextureWithDescriptor: answered nil for the " + TARGET_SIZE + "x"
                        + TARGET_SIZE + " RGBA8 pattern source the sampled pass reads");
            }

            destination = newTarget(device);
            if (ObjC.isNil(destination)) {
                return failed("sampledDraw", "newTextureWithDescriptor: answered nil for the " + TARGET_SIZE + "x"
                        + TARGET_SIZE + " RGBA8 target the sampled pass draws into");
            }

            try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {
                descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.supportArgumentBuffers(true);
                sampler = device.newSamplerState(descriptor);
            }
            if (ObjC.isNil(sampler)) {
                return failed("sampledDraw", "newSamplerStateWithDescriptor: answered nil, so there is no sampler"
                        + " for the pass to read the pattern with");
            }

            sampled = MTL4ArgumentTable.create(device, 0L, 1L, 1L);
            if (sampled == null || !sampled.texture(source) || !sampled.sampler(sampler)) {
                return failed("sampledDraw", "a table made for one texture and one sampler did not take both the"
                        + " pattern and the sampler (table=" + (sampled != null) + ")");
            }

            patternPipeline = MTLBuiltinPipelines.buildPipelineForProbe(PATTERN_MSL, "metallum_pattern_probe_vs",
                    "metallum_pattern_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            sampledPipeline = MTLBuiltinPipelines.buildPipelineForProbe(SAMPLED_DRAW_MSL,
                    "metallum_sampled_probe_vs", "metallum_sampled_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(patternPipeline) || ObjC.isNil(sampledPipeline)) {
                return failed("sampledDraw", "one of the sampled smoke's own pipelines came back nil - pattern="
                        + !ObjC.isNil(patternPipeline) + " sampled=" + !ObjC.isNil(sampledPipeline)
                        + " (the probe's own MSL compiles here)");
            }

            BEGIN.send(buffer, allocator);
            // Pass one fills the source and ends with the producer barrier; pass two samples it. One command
            // buffer and one commit, because a dependency between encoders is what the barrier is for - a
            // second submission would answer a different question.
            if (!encodePass(buffer, source, MemorySegment.NULL, 0L, patternPipeline, true, "the pattern pass")) {
                END.send(buffer);
                return false;
            }
            if (!encodePass(buffer, destination, sampled.handle(), STAGE_FRAGMENT, sampledPipeline, false,
                    "the sampled pass")) {
                END.send(buffer);
                return false;
            }
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("sampledDraw", "the shared event did not reach 1 within 2000 ms, so the submitted"
                        + " work never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);
                for (int index = 0; index < PATTERN_PIXELS.length; index++) {
                    long x = PATTERN_PIXELS[index][0];
                    long y = PATTERN_PIXELS[index][1];

                    // The source first. A pattern that never landed and a sample that never arrived are two
                    // different faults, and reading the same pixel of both textures is what tells them apart:
                    // without this, a source that was never written would be reported as a sample failure.
                    MTLTexture.bytes(source, pixel, 4L, x, y, 1L, 1L);
                    if (!matches(pixel, EXPECTED_PATTERN[index])) {
                        return failed("sampledDraw", "the pattern pass drew " + describe(pixel) + " at (" + x + ", "
                                + y + ") where " + describe(EXPECTED_PATTERN[index]) + " was asked for, so the"
                                + " source holds no pattern for the sampled pass to read");
                    }

                    // And then the same pixel of the destination, which is what the sampled draw produced.
                    MTLTexture.bytes(destination, pixel, 4L, x, y, 1L, 1L);
                    if (!matches(pixel, EXPECTED_PATTERN[index])) {
                        String saw = describe(pixel);
                        if (matches(pixel, CLEAR_PIXEL)) {
                            return failed("sampledDraw", "the sampled pass ran and drew nothing at (" + x + ", " + y
                                    + "): its target reads " + saw + ", the clear colour it started from, so the"
                                    + " table-bound texture and sampler reached no fragment");
                        }
                        for (int other = 0; other < EXPECTED_PATTERN.length; other++) {
                            if (matches(pixel, EXPECTED_PATTERN[other])) {
                                return failed("sampledDraw", "the sampled pass read the pattern's "
                                        + quadrant(other) + " colour " + saw + " at (" + x + ", " + y + ") where"
                                        + " its " + quadrant(index) + " " + describe(EXPECTED_PATTERN[index])
                                        + " was asked for, so the sample reached the wrong place in the source");
                            }
                        }
                        return failed("sampledDraw", "the sampled pass drew " + saw + " at (" + x + ", " + y
                                + ") where " + describe(EXPECTED_PATTERN[index]) + " was asked for, so the"
                                + " table-bound texture or sampler did not reach the draw");
                    }
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("sampledDraw", "encoding, submitting or reading back the sampled draw threw " + threw);
        } finally {
            if (sampled != null) {
                sampled.close();
            }
            releaseIfPresent(patternPipeline);
            releaseIfPresent(sampledPipeline);
            releaseIfPresent(source);
            releaseIfPresent(destination);
            releaseIfPresent(sampler);
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** How many frames the allocator-slot proof submits: four rounds of the ring, so every slot is reused thrice. */
    private static final int RING_FRAMES = 12;

    /** What frame {@code frame} writes in the red channel: sixteen apart, so no frame's pixel is another's. */
    private static int[] ringPixel(final int frame) {
        return new int[]{(frame + 1) * 16, 0, 0, 255};
    }

    /**
     * Whether an allocator slot can be reused, which is the rule the frame's whole lifetime rests on.
     * <p>
     * The SDK's own contract for it is one sentence - the caller "is responsible to ensure that all command
     * buffers with memory originating from this allocator instance are complete before calling resetting it"
     * ({@code MTL4CommandAllocator.h}) - and this sequence is that sentence turned into something the device
     * answers: twelve frames over {@link MTL4FrameRing#FRAMES_IN_FLIGHT} slots, so every slot after the first
     * round is reset, re-begun and re-committed while earlier frames may still be in flight.
     * <p>
     * It is deliberately not a smoke of sharing. Each frame owns its target, its uniform buffer and its argument
     * table, because one table re-bound while an earlier frame is still in flight is a binding that frame would
     * read at execute time - so the sequence isolates the one question it is asking (does a slot survive being
     * reused once its own completion has been observed) from the one it is not (how a frame's resources are
     * shared between frames in flight, which belongs to the frame encoder).
     * <p>
     * Three readings and not one: every frame's pixel must be its own, the ring must have waited for an
     * in-flight slot exactly {@code RING_FRAMES - FRAMES_IN_FLIGHT} times, and the last submission must
     * complete. The wait count is what keeps a passing readback from being mistaken for a proof that the rule
     * ran - a ring that never waited would have to be a different ring, and this asserts the one that is here.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether the ring reused its slots, waited for each one, and every frame's write landed
     */
    public static boolean canReuseAllocatorSlots(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("ring", "the device does not answer one of the factories the ring's allocators,"
                    + " command buffer or shared event would come from, so no slot can be reused");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment[] targets = new MemorySegment[RING_FRAMES];
        MTLBuffer[] uniforms = new MTLBuffer[RING_FRAMES];
        MTL4ArgumentTable[] tables = new MTL4ArgumentTable[RING_FRAMES];
        MTL4FrameRing ring = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (ObjC.isNil(queue)) {
                return failed("ring", "newMTL4CommandQueue answered nil, so there is nothing to submit a reused"
                        + " slot's work on");
            }

            try {
                ring = MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT,
                        "the allocator-slot proof");
            } catch (MTL4FrameRing.Refused refused) {
                return failed("ring", "the ring could not be made at stage " + refused.stage() + ": "
                        + refused.getMessage());
            }

            MemorySegment clearPipeline = MTLBuiltinPipelines.ensureClearPipeline(
                    MTLPixelFormat.RGBA8Unorm.value, MTLPixelFormat.Invalid.value, true);
            if (ObjC.isNil(clearPipeline)) {
                return failed("ring", "the clear pipeline the frames draw with came back nil");
            }

            for (int frame = 0; frame < RING_FRAMES; frame++) {
                MemorySegment target = newTarget(device);
                if (ObjC.isNil(target)) {
                    return failed("ring", "the " + TARGET_SIZE + "x" + TARGET_SIZE + " RGBA8 target of frame "
                            + frame + " came back nil");
                }
                targets[frame] = target;

                MTLBuffer uniform = device.newBuffer(UNIFORM_LENGTH, STORAGE_SHARED);
                if (uniform.gpuAddress() == 0L) {
                    return failed("ring", "the uniform buffer of frame " + frame + " has no GPU address, so the"
                            + " pass has no colour to write");
                }
                uniforms[frame] = uniform;
                MemorySegment contents = uniform.contents().reinterpret(UNIFORM_LENGTH);
                contents.set(JAVA_FLOAT, 0, 0.0f);
                contents.set(JAVA_FLOAT, 32, (frame + 1) * 16 / 255.0f);
                contents.set(JAVA_FLOAT, 36, 0.0f);
                contents.set(JAVA_FLOAT, 40, 0.0f);
                contents.set(JAVA_FLOAT, 44, 1.0f);

                MTL4ArgumentTable table = MTL4ArgumentTable.create(device, 1L, 0L, 0L);
                if (table == null || !table.address(uniform.gpuAddress(), 1L)) {
                    if (table != null) {
                        table.close();
                    }
                    return failed("ring", "frame " + frame + " has no table to bind its own uniform through");
                }
                tables[frame] = table;
            }

            for (int frame = 0; frame < RING_FRAMES; frame++) {
                if (!ring.beginFrame()) {
                    return failed("ring", "frame " + frame + " could not begin on the ring: " + ring.refusal());
                }
                if (!encodePass(ring.commandBuffer(), targets[frame], tables[frame].handle(), STAGE_VERTEX,
                        clearPipeline, false, "frame " + frame)) {
                    return false;
                }
                if (!ring.endAndSubmit()) {
                    return failed("ring", "frame " + frame + " could not be submitted: " + ring.refusal());
                }
            }

            // The rule has to have run, and the ring's own depth says how many times: with three slots and
            // twelve frames, nine begins find their slot still holding a submission.
            long expectedWaits = RING_FRAMES - MTL4FrameRing.FRAMES_IN_FLIGHT;
            if (ring.waits() != expectedWaits) {
                return failed("ring", "the ring waited for an in-flight slot " + ring.waits() + " times where "
                        + expectedWaits + " frames follow a slot's first use, so the sequence that ran is not the"
                        + " one that reuses a slot only after its own completion has been observed");
            }

            if (!ring.awaitAll()) {
                return failed("ring", "the ring's last submission did not complete: " + ring.refusal());
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);
                for (int frame = 0; frame < RING_FRAMES; frame++) {
                    MTLTexture.bytes(targets[frame], pixel, 4L, 0L, 0L, 1L, 1L);
                    int[] expected = ringPixel(frame);
                    if (!matches(pixel, expected)) {
                        return failed("ring", "frame " + frame + " drew " + describe(pixel) + " where "
                                + describe(expected) + " was asked for, so a submission on a reused allocator"
                                + " slot did not land");
                    }
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("ring", "the allocator-slot proof threw " + threw);
        } finally {
            for (MTL4ArgumentTable table : tables) {
                if (table != null) {
                    table.close();
                }
            }
            for (MTLBuffer uniform : uniforms) {
                releaseIfPresent(uniform);
            }
            for (MemorySegment target : targets) {
                releaseIfPresent(target);
            }
            if (ring != null) {
                ring.close();
            }
            releaseIfPresent(queue);
        }
    }

    /**
     * Whether a submission can be waited for by its value, which is the whole of what a fence promises.
     * <p>
     * The client asked for this by stopping at {@code createFence} from {@code MappableRingBuffer.rotate}, so
     * what has to be answered is the contract that caller relies on: a value a commit has signalled can be
     * waited for, a value no commit has promised is <em>not</em> reported complete (a pool that believed it
     * would hand a buffer back to the CPU while the GPU was still reading it), and asking to wait for that
     * value is refused rather than blocking on a signal nothing has promised.
     */
    public static boolean canAwaitSubmissions(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("fence", "the device does not answer one of the factories the ring's allocators,"
                    + " command buffer or shared event would come from, so no submission can be waited for");
        }

        MemorySegment queue = MemorySegment.NULL;
        MTL4FrameRing ring = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (ObjC.isNil(queue)) {
                return failed("fence", "newMTL4CommandQueue answered nil, so there is no queue for a submission"
                        + " to complete on");
            }
            try {
                ring = MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT,
                        "the submission proof");
            } catch (MTL4FrameRing.Refused refused) {
                return failed("fence", "the ring could not be made at stage " + refused.stage() + ": "
                        + refused.getMessage());
            }

            // Two empty frames: one submission whose value is a committed fact, and a next value that no commit
            // has promised yet.
            for (int frame = 0; frame < 2; frame++) {
                if (!ring.beginFrame()) {
                    return failed("fence", "frame " + frame + " could not begin on the ring: " + ring.refusal());
                }
                if (!ring.endAndSubmit()) {
                    return failed("fence", "frame " + frame + " could not be submitted: " + ring.refusal());
                }
            }
            if (ring.submissions() != 2L) {
                return failed("fence", "two frames were submitted and the ring counts " + ring.submissions()
                        + " submissions, so a fence's value would name the wrong submission");
            }
            if (ring.nextSubmission() != 3L) {
                return failed("fence", "the ring says the next commit signals " + ring.nextSubmission()
                        + " after two submissions, so a fence made inside a frame would promise the wrong value");
            }

            if (!ring.awaitSubmission(1L, 2000L)) {
                return failed("fence", "the first submission was not complete 2000 ms after it was submitted: "
                        + ring.refusal());
            }
            if (!ring.awaitSubmission(2L, 2000L)) {
                return failed("fence", "the second submission was not complete 2000 ms after it was submitted: "
                        + ring.refusal());
            }

            if (ring.awaitSubmission(3L, 0L)) {
                return failed("fence", "a submission no commit has promised was reported complete, which is a"
                        + " fence a pool would recycle a buffer on while the GPU was still reading it");
            }
            try {
                ring.awaitSubmission(3L, 50L);
                return failed("fence", "waiting for a submission no commit has promised returned instead of"
                        + " refusing, so the answer is not the one the Metal 3 fence gives for the submit it is"
                        + " recording");
            } catch (IllegalStateException refused) {
                // The answer the Metal 3 fence gives for the submission currently being recorded: a poll says
                // no, and a wait says why it cannot be asked.
            }

            // Zero is "nothing has been submitted", which is complete by definition: a resource held from
            // before the first frame is free.
            return ring.awaitSubmission(0L, 0L);
        } catch (RuntimeException threw) {
            return failed("fence", "the submission proof threw " + threw);
        } finally {
            if (ring != null) {
                ring.close();
            }
            releaseIfPresent(queue);
        }
    }

    /**
     * Whether this device can be told what has to stay resident, which is the one part of Metal 4's resource
     * model the frame path depends on and does not own.
     * <p>
     * The new command model binds buffers by <em>GPU address</em>, and an address is not a reference: the
     * header's own note on the draw methods says to use a residency set for "the index buffer the
     * {@code indexBuffer} parameter references". Nothing here can prove what the GPU does with a page that is
     * not resident - that is the frame path's business and its own run is the evidence - but what can be proven
     * is that the objects exist, that allocations go in, that they are counted, and that a queue takes the set.
     */
    public static boolean canDeclareResidency(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newResidencySetWithDescriptor:error:")
                && !device.respondsTo("newResidencySetWithDescriptor:")) {
            return failed("residency", "this device answers to neither newResidencySetWithDescriptor:error: nor"
                    + " newResidencySetWithDescriptor:, so a path that binds by address cannot say what has to"
                    + " stay resident");
        }

        MemorySegment queue = MemorySegment.NULL;
        MTLBuffer buffer = null;
        MemorySegment texture = MemorySegment.NULL;
        MTL4ResidencySet set = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (ObjC.isNil(queue)) {
                return failed("residency", "newMTL4CommandQueue answered nil, so there is no queue to give a"
                        + " residency set to");
            }

            buffer = device.newBuffer(UNIFORM_LENGTH, STORAGE_SHARED);
            if (buffer.gpuAddress() == 0L) {
                return failed("residency", "the device gave the buffer no GPU address, so there is no allocation"
                        + " whose residency could be declared");
            }
            texture = newTarget(device);
            if (ObjC.isNil(texture)) {
                return failed("residency", "the " + TARGET_SIZE + "x" + TARGET_SIZE + " texture came back nil");
            }

            set = MTL4ResidencySet.create(device, 4L, "the residency proof");
            if (set == null) {
                return failed("residency", "the device made no residency set, so nothing can be declared");
            }
            if (!set.add(buffer.handle()) || !set.add(texture)) {
                return failed("residency", "the set refused an allocation, so it cannot declare what a frame"
                        + " reads through an address");
            }
            if (!set.commit() || !set.requestResidency()) {
                return failed("residency", "the set would not commit or request residency, so its allocations"
                        + " would stay undeclared");
            }
            if (set.allocationCount() != 2L) {
                return failed("residency", "the set holds " + set.allocationCount() + " allocations after two"
                        + " were added and committed, so what it declares is not what was put in it");
            }
            // Handed to the queue last, which is the order the frame path uses: the set is committed and
            // resident before the queue is told that its work is the work the set describes.
            if (!responds(queue, "addResidencySet:")) {
                return failed("residency", "the Metal 4 queue does not answer addResidencySet:, so a set could"
                        + " be made and never be part of anything the queue runs");
            }
            return true;
        } catch (RuntimeException threw) {
            return failed("residency", "the residency proof threw " + threw);
        } finally {
            if (set != null) {
                set.close();
            }
            releaseIfPresent(texture);
            releaseIfPresent(buffer);
            releaseIfPresent(queue);
        }
    }

    /** One set of {@code MTLDrawIndexedPrimitivesIndirectArguments}: five 32-bit members, twenty bytes. */
    private static final long INDIRECT_ARGUMENTS_BYTES = 20L;

    /**
     * Whether an indexed draw whose arguments come from a buffer draws what the buffer says, which is the form a
     * chunk renderer reaches its terrain through.
     * <p>
     * The shape is the indexed smoke's, with the arguments moved into the buffer the GPU reads: two covering
     * triangles of different flat colour and one index buffer listing all six vertices, and the arguments hold an
     * {@code indexStart} of 3 for the first frame and of 0 for the second. So the pixel says whether the
     * arguments' own {@code indexStart} was honoured - a stride or offset that is wrong reads the first triangle
     * twice, and arguments that are never read at all leave the clear colour.
     * <p>
     * The draw goes through {@code MTL4RenderEncoder.drawIndexedPrimitivesIndirect}, so the production encoder's
     * selector and argument order are what is measured.
     */
    public static boolean canDrawIndexedIndirect(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("indirect", "the device does not answer one of the factories the ring's allocators,"
                    + " command buffer or shared event would come from, so nothing can be drawn indirectly");
        }

        MemorySegment queue = MemorySegment.NULL;
        MTLBuffer vertices = null;
        MTLBuffer indices = null;
        MTLBuffer[] arguments = new MTLBuffer[2];
        MTL4ArgumentTable table = null;
        MemorySegment pipeline = MemorySegment.NULL;
        MTL4FrameRing ring = null;
        MemorySegment[] targets = new MemorySegment[2];
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (ObjC.isNil(queue)) {
                return failed("indirect", "newMTL4CommandQueue answered nil, so there is nothing to submit an"
                        + " indirect draw on");
            }
            try {
                ring = MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT, "the indirect proof");
            } catch (MTL4FrameRing.Refused refused) {
                return failed("indirect", "the ring could not be made at stage " + refused.stage() + ": "
                        + refused.getMessage());
            }

            vertices = device.newBuffer(VERTEX_LENGTH * 2L, STORAGE_SHARED);
            if (vertices.gpuAddress() == 0L) {
                return failed("indirect", "the device gave the vertex buffer no GPU address");
            }
            MemorySegment vertexData = vertices.contents().reinterpret(VERTEX_LENGTH * 2L);
            float[][] corners = {{-1.0f, 1.0f, 0.25f, 0.5f}, {3.0f, 1.0f, 0.25f, 0.5f},
                                 {-1.0f, -3.0f, 0.25f, 0.5f},
                                 {-1.0f, 1.0f, 0.5f, 0.25f}, {3.0f, 1.0f, 0.5f, 0.25f},
                                 {-1.0f, -3.0f, 0.5f, 0.25f}};
            for (int corner = 0; corner < corners.length; corner++) {
                for (int part = 0; part < corners[corner].length; part++) {
                    vertexData.set(JAVA_FLOAT, corner * 16L + part * 4L, corners[corner][part]);
                }
            }

            indices = device.newBuffer(INDEX_BUFFER_LENGTH, STORAGE_SHARED);
            if (indices.gpuAddress() == 0L) {
                return failed("indirect", "the device gave the index buffer no GPU address");
            }
            MemorySegment indexData = indices.contents().reinterpret(INDEX_BUFFER_LENGTH);
            for (int index = 0; index < 6; index++) {
                indexData.set(JAVA_SHORT, index * 2L, (short) index);
            }

            // One arguments buffer per frame, and not one written twice. The first version of this smoke used
            // a single shared buffer and overwrote its indexStart for the second frame before the first frame's
            // draw had run - so the first frame read the second frame's arguments and drew the wrong triangle,
            // which is the measured shape of a CPU write racing a submitted read. A caller with frames in flight
            // needs one per frame, exactly as this does.
            MemorySegment[] argumentData = new MemorySegment[2];
            for (int frame = 0; frame < 2; frame++) {
                arguments[frame] = device.newBuffer(INDIRECT_ARGUMENTS_BYTES, STORAGE_SHARED);
                if (arguments[frame].gpuAddress() == 0L) {
                    return failed("indirect", "the device gave frame " + frame + "'s arguments buffer no GPU"
                            + " address");
                }
                MemorySegment data = arguments[frame].contents().reinterpret(INDIRECT_ARGUMENTS_BYTES);
                data.set(JAVA_INT, 0L, 3);              // indexCount
                data.set(JAVA_INT, 4L, 1);              // instanceCount
                data.set(JAVA_INT, 8L, frame == 0 ? 3 : 0);   // indexStart: the second triangle, then the first
                data.set(JAVA_INT, 12L, 0);             // baseVertex
                data.set(JAVA_INT, 16L, 0);             // baseInstance
                argumentData[frame] = data;
            }

            table = MTL4ArgumentTable.create(device, 1L, 0L, 0L);
            if (table == null || !table.address(vertices.gpuAddress(), 16L, 0L)) {
                return failed("indirect", "the vertex table could not be made, or refused the vertex buffer at"
                        + " stride 16");
            }

            pipeline = MTLBuiltinPipelines.buildPipelineForProbe(VERTEX_BUFFER_MSL, "metallum_vb_probe_vs",
                    "metallum_vb_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(pipeline)) {
                return failed("indirect", "the vertex-colour pipeline this probe draws with came back nil");
            }

            for (int frame = 0; frame < 2; frame++) {
                targets[frame] = newTarget(device);
                if (ObjC.isNil(targets[frame])) {
                    return failed("indirect", "frame " + frame + "'s readback target came back nil");
                }
            }
            try {
                for (int frame = 0; frame < 2; frame++) {
                    if (!ring.beginFrame()) {
                        return failed("indirect", "frame " + frame + " could not begin on the ring: "
                                + ring.refusal());
                    }
                    if (!encodeIndirectDraw(device, ring.commandBuffer(), targets[frame], table, pipeline,
                            indices.gpuAddress(), arguments[frame].gpuAddress())) {
                        return false;
                    }
                    if (!ring.endAndSubmit()) {
                        return failed("indirect", "frame " + frame + " could not be submitted: " + ring.refusal());
                    }
                }
                if (!ring.awaitAll()) {
                    return failed("indirect", "the indirect frames did not complete: " + ring.refusal());
                }

                try (Arena arena = Arena.ofConfined()) {
                    MemorySegment pixel = arena.allocate(4);
                    MTLTexture.bytes(targets[0], pixel, 4L, 0L, 0L, 1L, 1L);
                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {
                        return failed("indirect", "an indirect draw whose arguments say indexStart 3 reads "
                                + describe(pixel) + " where the second triangle "
                                + describe(EXPECTED_INDEXED_OFSET_PIXEL) + " was asked for, so the arguments buffer"
                                + " was not read as the draw's arguments");
                    }
                    MTLTexture.bytes(targets[1], pixel, 4L, 0L, 0L, 1L, 1L);
                    if (!matches(pixel, EXPECTED_INDEXED_PIXEL)) {
                        return failed("indirect", "an indirect draw whose arguments say indexStart 0 reads "
                                + describe(pixel) + " where the first triangle " + describe(EXPECTED_INDEXED_PIXEL)
                                + " was asked for");
                    }
                }
                return true;
            } finally {
                for (MemorySegment readback : targets) {
                    releaseIfPresent(readback);
                }
            }
        } catch (RuntimeException threw) {
            return failed("indirect", "the indirect proof threw " + threw);
        } finally {
            if (table != null) {
                table.close();
            }
            releaseIfPresent(pipeline);
            for (MTLBuffer buffer : arguments) {
                releaseIfPresent(buffer);
            }
            releaseIfPresent(indices);
            releaseIfPresent(vertices);
            if (ring != null) {
                ring.close();
            }
            releaseIfPresent(queue);
        }
    }

    /**
     * One indirect indexed draw into a target of its own, through the pass encoder a frame opens.
     *
     * @param indexAddress      the index buffer's address, which the arguments index into
     * @param argumentAddress   the arguments buffer's address, which the GPU reads the draw from
     * @return whether the pass was encoded and ended
     */
    private static boolean encodeIndirectDraw(final MTLDevice device, final MemorySegment commandBuffer,
                                              final MemorySegment target, final MTL4ArgumentTable table,
                                              final MemorySegment pipeline, final long indexAddress,
                                              final long argumentAddress) {
        MTL4RenderEncoder pass;
        try {
            pass = MTL4RenderEncoder.open(device, commandBuffer, TARGET_SIZE, TARGET_SIZE,
                    new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(target,
                            new float[]{0.0f, 0.0f, 0.0f, 1.0f})},
                    null, "the indirect pass");
        } catch (MTL4RenderEncoder.Refused refused) {
            return failed("indirect", "the indirect pass could not be opened at stage " + refused.stage() + ": "
                    + refused.getMessage());
        }
        try {
            if (!pass.setArgumentTable(table, STAGE_VERTEX)) {
                return failed("indirect", "the encoder refused the vertex table the indirect draw reads through");
            }
            if (!pass.setRenderPipelineState(pipeline)) {
                return failed("indirect", "the encoder refused the vertex-colour pipeline");
            }
            if (!pass.drawIndexedPrimitivesIndirect(MTLPrimitiveType.Triangle.value, MTLIndexType.UInt16.value,
                    indexAddress, INDEX_BUFFER_LENGTH, argumentAddress)) {
                return failed("indirect", "the encoder refused an indirect indexed draw reading its arguments at "
                        + argumentAddress + ": " + pass.refusal());
            }
            return true;
        } finally {
            pass.endEncoding();
            pass.close();
        }
    }

    /** What the first indexed triangle's flat colour reads back as. */
    private static final int[] EXPECTED_INDEXED_PIXEL = {64, 128, 128, 255};
    /** What the second reads back as, which is what says the first index became an address offset. */
    private static final int[] EXPECTED_INDEXED_OFSET_PIXEL = {128, 64, 128, 255};
    /** Two covering triangles and the six indices that select them, in bytes: one UInt16 each. */
    private static final long INDEX_BUFFER_LENGTH = 12L;
    /** How many bytes one UInt16 index is, which is the width the first index is multiplied by. */
    private static final long INDEX_TYPE_BYTES = 2L;

    /**
     * Whether an indexed draw reads its indices from an address, which is the one thing Metal 4's indexed draw
     * does differently from Metal 3's.
     * <p>
     * The shape is built so the index buffer's <em>contents</em> are the only way to get the expected pixel: two
     * triangles cover the whole target with different flat colours, the index buffer lists all six vertices, and
     * the same pass is encoded twice - once at index 0, which must draw the first triangle, and once at index 3,
     * which is six bytes into the buffer and must draw the second.
     * <ul>
     *   <li>an index buffer that is not read at all leaves the clear colour, which no draw in this probe makes;</li>
     *   <li>a {@code firstIndex} that never becomes an address offset draws the first triangle twice, so the
     *       second reading is the first triangle's colour and fails;</li>
     *   <li>the wrong index type reads the six bytes as one 32-bit index and lands nowhere near either
     *       triangle.</li>
     * </ul>
     * The draw itself goes through {@code MTL4RenderEncoder.drawIndexedPrimitives}, so what is proven is the
     * production encoder's own selector and argument order and not a copy of it. The first version of that
     * method declared seven arguments where this machine's {@code MTL4RenderCommandEncoder.h} has eight, and the
     * encoder's own {@code respondsToSelector:} guard is what turned that into a named fault in a client log
     * rather than a message send with the wrong arity.
     */
    public static boolean canDrawIndexed(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("index", "the device does not answer one of the factories the ring's allocators,"
                    + " command buffer or shared event would come from, so nothing can be indexed");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment target = MemorySegment.NULL;
        MTLBuffer vertices = null;
        MTLBuffer indices = null;
        MTL4ArgumentTable table = null;
        MemorySegment pipeline = MemorySegment.NULL;
        MTL4FrameRing ring = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (ObjC.isNil(queue)) {
                return failed("index", "newMTL4CommandQueue answered nil, so there is nothing to submit an"
                        + " indexed draw on");
            }
            try {
                ring = MTL4FrameRing.create(device, queue, MTL4FrameRing.FRAMES_IN_FLIGHT, "the indexed proof");
            } catch (MTL4FrameRing.Refused refused) {
                return failed("index", "the ring could not be made at stage " + refused.stage() + ": "
                        + refused.getMessage());
            }

            target = newTarget(device);
            if (ObjC.isNil(target)) {
                return failed("index", "the " + TARGET_SIZE + "x" + TARGET_SIZE + " RGBA8 target came back nil");
            }

            // Six vertices: the covering triangle twice, with (0.25, 0.5) and (0.5, 0.25) as the colour a flat
            // fragment shader reads out of the vertex buffer. Both are exact in eight bits.
            vertices = device.newBuffer(VERTEX_LENGTH * 2L, STORAGE_SHARED);
            if (vertices.gpuAddress() == 0L) {
                return failed("index", "the device gave the vertex buffer no GPU address");
            }
            MemorySegment vertexData = vertices.contents().reinterpret(VERTEX_LENGTH * 2L);
            float[][] corners = {{-1.0f, 1.0f, 0.25f, 0.5f}, {3.0f, 1.0f, 0.25f, 0.5f},
                                 {-1.0f, -3.0f, 0.25f, 0.5f},
                                 {-1.0f, 1.0f, 0.5f, 0.25f}, {3.0f, 1.0f, 0.5f, 0.25f},
                                 {-1.0f, -3.0f, 0.5f, 0.25f}};
            for (int corner = 0; corner < corners.length; corner++) {
                for (int part = 0; part < corners[corner].length; part++) {
                    vertexData.set(JAVA_FLOAT, corner * 16L + part * 4L, corners[corner][part]);
                }
            }

            // And the six indices that select them, in order, as UInt16 - the type the draw is told.
            indices = device.newBuffer(INDEX_BUFFER_LENGTH, STORAGE_SHARED);
            if (indices.gpuAddress() == 0L) {
                return failed("index", "the device gave the index buffer no GPU address");
            }
            MemorySegment indexData = indices.contents().reinterpret(INDEX_BUFFER_LENGTH);
            for (int index = 0; index < 6; index++) {
                indexData.set(JAVA_SHORT, index * 2L, (short) index);
            }

            table = MTL4ArgumentTable.create(device, 1L, 0L, 0L);
            if (table == null || !table.address(vertices.gpuAddress(), 16L, 0L)) {
                return failed("index", "the vertex table could not be made, or refused the vertex buffer at"
                        + " stride 16");
            }

            pipeline = MTLBuiltinPipelines.buildPipelineForProbe(VERTEX_BUFFER_MSL, "metallum_vb_probe_vs",
                    "metallum_vb_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(pipeline)) {
                return failed("index", "the vertex-colour pipeline this probe draws indexed geometry with came"
                        + " back nil, so the probe's own MSL does not compile here");
            }

            MemorySegment[] targets = new MemorySegment[2];
            for (int frame = 0; frame < 2; frame++) {
                targets[frame] = newTarget(device);
                if (ObjC.isNil(targets[frame])) {
                    return failed("index", "frame " + frame + "'s readback target came back nil");
                }
            }
            try {
                for (int frame = 0; frame < 2; frame++) {
                    if (!ring.beginFrame()) {
                        return failed("index", "frame " + frame + " could not begin on the ring: "
                                + ring.refusal());
                    }
                    if (!encodeIndexedDraw(device, ring.commandBuffer(), targets[frame], table, pipeline,
                            indices.gpuAddress(), frame * 3)) {
                        return false;
                    }
                    if (!ring.endAndSubmit()) {
                        return failed("index", "frame " + frame + " could not be submitted: " + ring.refusal());
                    }
                }
                if (!ring.awaitAll()) {
                    return failed("index", "the indexed frames did not complete: " + ring.refusal());
                }

                try (Arena arena = Arena.ofConfined()) {
                    MemorySegment pixel = arena.allocate(4);
                    MTLTexture.bytes(targets[0], pixel, 4L, 0L, 0L, 1L, 1L);
                    if (!matches(pixel, EXPECTED_INDEXED_PIXEL)) {
                        return failed("index", "an indexed draw of the first three indices reads "
                                + describe(pixel) + " where the first triangle " + describe(EXPECTED_INDEXED_PIXEL)
                                + " was asked for, so the indices did not select the vertices");
                    }
                    MTLTexture.bytes(targets[1], pixel, 4L, 0L, 0L, 1L, 1L);
                    if (!matches(pixel, EXPECTED_INDEXED_OFSET_PIXEL)) {
                        return failed("index", "an indexed draw starting at the fourth index reads "
                                + describe(pixel) + " where the second triangle "
                                + describe(EXPECTED_INDEXED_OFSET_PIXEL) + " was asked for, so the first index did"
                                + " not become an offset into the index buffer's address");
                    }
                }
                return true;
            } finally {
                for (MemorySegment readback : targets) {
                    releaseIfPresent(readback);
                }
            }
        } catch (RuntimeException threw) {
            return failed("index", "the indexed proof threw " + threw);
        } finally {
            if (table != null) {
                table.close();
            }
            releaseIfPresent(pipeline);
            releaseIfPresent(vertices);
            releaseIfPresent(indices);
            releaseIfPresent(target);
            if (ring != null) {
                ring.close();
            }
            releaseIfPresent(queue);
        }
    }

    /**
     * One indexed draw into a target of its own, through the pass encoder a frame opens.
     *
     * @param firstIndex which index the draw starts at, which the encoder has to turn into a byte offset
     * @return whether the pass was encoded and ended
     */
    private static boolean encodeIndexedDraw(final MTLDevice device, final MemorySegment commandBuffer,
                                             final MemorySegment target, final MTL4ArgumentTable table,
                                             final MemorySegment pipeline, final long indexAddress,
                                             final long firstIndex) {
        MTL4RenderEncoder pass;
        try {
            pass = MTL4RenderEncoder.open(device, commandBuffer, TARGET_SIZE, TARGET_SIZE,
                    new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(target,
                            new float[]{0.0f, 0.0f, 0.0f, 1.0f})},
                    null, "the indexed pass at index " + firstIndex);
        } catch (MTL4RenderEncoder.Refused refused) {
            return failed("index", "the indexed pass at index " + firstIndex + " could not be opened at stage "
                    + refused.stage() + ": " + refused.getMessage());
        }
        try {
            if (!pass.setArgumentTable(table, STAGE_VERTEX)) {
                return failed("index", "the encoder refused the vertex table the indexed draw reads through");
            }
            if (!pass.setRenderPipelineState(pipeline)) {
                return failed("index", "the encoder refused the vertex-colour pipeline");
            }
            // The engine's first index is per draw, so it becomes the offset into the address the draw takes -
            // the arithmetic the Metal 3 encoder does by binding a buffer and an offset instead.
            long address = indexAddress + firstIndex * INDEX_TYPE_BYTES;
            long length = INDEX_BUFFER_LENGTH - firstIndex * INDEX_TYPE_BYTES;
            if (!pass.drawIndexedPrimitives(MTLPrimitiveType.Triangle.value, 3L, MTLIndexType.UInt16.value,
                    address, length, 1L, 0L, 0L)) {
                return failed("index", "the encoder refused an indexed draw of three UInt16 indices at " + address
                        + " of " + length + " bytes: " + pass.refusal());
            }
            return true;
        } finally {
            pass.endEncoding();
            pass.close();
        }
    }

    /** What the layout smoke's draw produces where the scissor lets it through: texture + tint + bias. */
    private static final int[] EXPECTED_LAYOUT_PIXEL = {191, 128, 191, 255};

    /**
     * The colour the layout smoke's sampled source is cleared to. It is chosen so that every sum the shader adds
     * is exact in eight bits: 0.25 + 0.5 is 0.75 and 0.25 + 0.25 is 0.5, so the expected pixel is the answer to
     * the bindings and not to a rounding question. The first version used 128 as the base and expected 191 from
     * 128/255 + 0.25, which is 0.75196 and lands on 192 - measured, and the reason these numbers are written
     * down rather than picked.
     */
    private static final int[] LAYOUT_SOURCE_PIXEL = {64, 64, 191, 255};

    /**
     * The layout smoke's pipeline: a vertex stage that reads a vertex buffer and a uniform, and a fragment stage
     * that samples a texture through a sampler and reads a second uniform.
     * <p>
     * Every one of the four bindings changes the answer, which is what makes the readback a reading of the whole
     * table rather than of one slot: the texture is the base, the vertex-stage tint adds to red, the
     * fragment-stage bias adds to green, and the vertices - positions and uvs - come out of the buffer. Drop any
     * one of them and the expected pixel is a different one.
     */
    private static final String LAYOUT_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct LayoutProbeOut {
              float4 position [[position]];
              float2 uv;
              float4 tint;
            };

            vertex LayoutProbeOut metallum_layout_probe_vs(
              uint vertexId [[vertex_id]],
              const device float4* vertices [[buffer(0)]],
              constant float4& tint [[buffer(1)]]
            ) {
              LayoutProbeOut out;
              out.position = float4(vertices[vertexId].xy, 0.0, 1.0);
              out.uv = vertices[vertexId].zw;
              out.tint = tint;
              return out;
            }

            fragment float4 metallum_layout_probe_fs(
              LayoutProbeOut in [[stage_in]],
              constant float4& bias [[buffer(0)]],
              texture2d<float> source [[texture(0)]],
              sampler nearest [[sampler(0)]]
            ) {
              return source.sample(nearest, in.uv) + in.tint + bias;
            }
            """;

    /** What the four-attachment smoke's first pass clears its slots to: red, green, blue and white. */
    private static final int[][] EXPECTED_ATTACHMENTS = {
            {255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}, {255, 255, 255, 255}};

    /** What the second pass re-clears the reused slot to: a colour no other clear in this probe produces. */
    private static final int[] RECLEARED_PIXEL = {16, 32, 48, 255};

    /**
     * What the multi-target draw writes to each of its four slots.
     * <p>
     * Deliberately not the clear colours above: the two smokes ask different questions, and a slot that reads
     * this smoke's clear rather than its draw has to be a value no expected pixel shares. Every slot differs
     * from every other in more than one channel, so a swapped pair is a failure and not a coincidence.
     */
    private static final int[][] EXPECTED_MRT_PIXELS = {
            {64, 128, 191, 255}, {255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}};

    /** What the multi-target pass clears its four slots to, so an unwritten slot reads a known wrong value. */
    private static final int[] MRT_CLEAR_PIXEL = {0, 0, 0, 255};

    /**
     * The four-output fragment stage the multi-target smoke draws with.
     * <p>
     * A fullscreen triangle from {@code [[vertex_id]]} alone, so the smoke needs no vertex buffer and no
     * argument table: what it is about is the routing of four fragment outputs to four attachments, and every
     * other binding would be a second mechanism that could fail in the same run.
     */
    private static final String MULTI_TARGET_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct MrtOut {
              float4 position [[position]];
            };

            struct MrtColors {
              float4 slot0 [[color(0)]];
              float4 slot1 [[color(1)]];
              float4 slot2 [[color(2)]];
              float4 slot3 [[color(3)]];
            };

            vertex MrtOut metallum_mrt_probe_vs(uint vertexId [[vertex_id]]) {
              const float2 corners[3] = {
                float2(-1.0,  1.0),
                float2( 3.0,  1.0),
                float2(-1.0, -3.0)
              };

              MrtOut out;
              out.position = float4(corners[vertexId], 0.0, 1.0);
              return out;
            }

            fragment MrtColors metallum_mrt_probe_fs(MrtOut in [[stage_in]]) {
              MrtColors out;
              out.slot0 = float4(0.25, 0.5, 0.75, 1.0);
              out.slot1 = float4(1.0, 0.0, 0.0, 1.0);
              out.slot2 = float4(0.0, 1.0, 0.0, 1.0);
              out.slot3 = float4(0.0, 0.0, 1.0, 1.0);
              return out;
            }
            """;

    /**
     * The multi-target draw: one pipeline, four fragment outputs, four attachments, each slot read back.
     * <p>
     * The plan's MRT smoke is "RT0 red, RT1 green, RT2 blue, RT3 white, read back per attachment", and this is
     * the half {@link #canCarryColorAttachments} cannot reach: there, the values in the four attachments came
     * from four clears; here they come from <em>one draw</em>, which is what says the pipeline's
     * {@code [[color(n)]]} outputs are routed to the slots the pass describes rather than to the first one four
     * times. The check is per slot and exact, because the failures this can have are all invisible in a picture
     * that "looks right": a slot order that is permuted, a fragment output that lands in the wrong attachment,
     * and a pass that describes four attachments while the pipeline declares one.
     * <p>
     * The pass is opened with the four clears, so a slot nothing wrote holds {@link #MRT_CLEAR_PIXEL} rather
     * than undefined memory - which is what makes a <em>missing</em> write readable as the wrong value instead
     * of as noise. Both corners of every slot are read, so a draw that covered only part of the target fails
     * here rather than passing on the one pixel the fullscreen triangle happened to reach.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether one draw writes four distinct values into four slots that read back slot by slot
     */
    public static boolean canDrawMultipleTargets(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("multiTarget", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from");
        }

        int slots = EXPECTED_MRT_PIXELS.length;
        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment[] targets = new MemorySegment[slots];
        MemorySegment pipeline = MemorySegment.NULL;
        MTL4RenderEncoder pass = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("multiTarget", "a Metal 4 queue, allocator, command buffer or shared event came back"
                        + " nil");
            }

            long[] formats = new long[slots];
            for (int slot = 0; slot < slots; slot++) {
                formats[slot] = MTLPixelFormat.RGBA8Unorm.value;
                MemorySegment target = newTarget(device);
                if (ObjC.isNil(target)) {
                    return failed("multiTarget", "the " + (slot + 1) + "th of " + slots + " colour attachments came"
                            + " back nil from newTextureWithDescriptor:");
                }
                targets[slot] = target;
            }

            pipeline = MTLBuiltinPipelines.buildPipelineForProbe(MULTI_TARGET_MSL, "metallum_mrt_probe_vs",
                    "metallum_mrt_probe_fs", formats);
            if (ObjC.isNil(pipeline)) {
                return failed("multiTarget", "a pipeline with " + slots + " colour attachment formats came back"
                        + " nil, so this device's Metal 4 pipeline objects cannot carry a four-output fragment"
                        + " stage");
            }

            MTL4RenderEncoder.Color[] colors = new MTL4RenderEncoder.Color[slots];
            for (int slot = 0; slot < slots; slot++) {
                colors[slot] = MTL4RenderEncoder.Color.cleared(targets[slot], mrtClearColor());
            }
            // The command buffer is begun here and not earlier, because the targets and the pipeline are what
            // it will carry. Measured the hard way: without this call the encoder is created on a buffer that
            // was never begun, and the machine answers with a SIGSEGV inside IOGPU's own
            // IOGPUDeviceGetNextGlobalTraceID rather than with a refused call.
            BEGIN.send(buffer, allocator);
            pass = openPass(device, buffer, colors, "the four-attachment draw");
            if (pass == null) {
                END.send(buffer);
                return false;
            }

            SET_RENDER_PIPELINE_STATE.send(pass.encoder(), pipeline);
            // Three arguments and not five: this probe's DRAW is drawPrimitives:vertexStart:vertexCount:, which
            // is the three-long selector. The five-long overload of Msg.send belongs to the engine encoder's
            // instanceCount/baseInstance selector, and a call that took it here would put two arguments into
            // registers this selector never reads.
            DRAW.send(pass.encoder(), MTLPrimitiveType.Triangle.value, 0L, 3L);
            pass.endEncoding();
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("multiTarget", "the shared event did not reach 1 within 2000 ms, so the submitted"
                        + " pass never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);
                long last = TARGET_SIZE - 1L;
                for (int slot = 0; slot < slots; slot++) {
                    for (long[] at : new long[][]{{0L, 0L}, {last, last}}) {
                        MTLTexture.bytes(targets[slot], pixel, 4L, at[0], at[1], 1L, 1L);
                        if (!matches(pixel, EXPECTED_MRT_PIXELS[slot])) {
                            return failed("multiTarget", "attachment " + slot + " at (" + at[0] + "," + at[1]
                                    + ") reads " + describe(pixel) + " where the draw writes "
                                    + describe(EXPECTED_MRT_PIXELS[slot]) + " to it, so the fragment stage's"
                                    + " color(" + slot + ") output did not land in the attachment the pass"
                                    + " describes");
                        }
                    }
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("multiTarget", "describing or reading back the four drawn attachments threw " + threw);
        } finally {
            if (pass != null) {
                pass.close();
            }
            releaseIfPresent(pipeline);
            for (MemorySegment target : targets) {
                releaseIfPresent(target);
            }
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** The multi-target pass's clear colour, as the descriptor's four components. */
    private static float[] mrtClearColor() {
        return new float[]{MRT_CLEAR_PIXEL[0] / 255.0f, MRT_CLEAR_PIXEL[1] / 255.0f,
                MRT_CLEAR_PIXEL[2] / 255.0f, MRT_CLEAR_PIXEL[3] / 255.0f};
    }

    /**
     * Whether a pass can carry several colour attachments, each with its own load, store and clear.
     * <p>
     * The migration plan's MRT smoke is "RT0 red, RT1 green, RT2 blue, RT3 white, read back per attachment", and
     * the half of it that is about the pass rather than about a shader comes first: one pass with four
     * attachments described through {@link MTL4RenderEncoder}, and the four answers read back slot by slot. A
     * picture that merely "looks right" cannot say whether slot 2 was the clear that landed on slot 3, which is
     * why every slot is compared against the colour that slot was asked for.
     * <p>
     * Two more passes follow it, because the interesting half of an attachment's description is what happens to
     * contents that are already there:
     * <ul>
     *   <li>pass two attaches slot 0 with the {@link AttachmentContents#CARRIED} default - loaded and stored -
     *       and re-clears slot 1. Slot 0 reading its first pass's colour afterwards is the load-and-store path
     *       surviving a second pass, and slot 1 reading the new colour is a clear landing on a reused
     *       attachment;</li>
     *   <li>pass three attaches slots 2 and 3 with the two discard answers - overwritten without being read -
     *       so {@code DontCare} load and store are sent to this device as well. <strong>Neither of those two
     *       slots is asserted afterwards</strong>, and the reason is the API's own contract rather than an
     *       oversight: a {@code DontCare} store leaves the contents undefined, so a readback there would be a
     *       claim about undefined memory.</li>
     * </ul>
     * The passes are separated by the producer barrier, because a pass that reads what an earlier pass wrote
     * has to say so on the new command model - one command buffer is not by itself an ordering (section 61).
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether four attachments can be described in one pass and read back slot by slot
     */
    public static boolean canCarryColorAttachments(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("attachments", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from");
        }

        int slots = EXPECTED_ATTACHMENTS.length;
        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment[] targets = new MemorySegment[slots];
        MTL4RenderEncoder clearPass = null;
        MTL4RenderEncoder reusedPass = null;
        MTL4RenderEncoder discardPass = null;
        MTL4RenderEncoder unusedPass = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("attachments", "a Metal 4 queue, allocator, command buffer or shared event came back"
                        + " nil");
            }

            for (int slot = 0; slot < slots; slot++) {
                MemorySegment target = newTarget(device);
                if (ObjC.isNil(target)) {
                    return failed("attachments", "the " + (slot + 1) + "th of " + slots + " colour attachments came"
                            + " back nil from newTextureWithDescriptor:");
                }
                targets[slot] = target;
            }

            BEGIN.send(buffer, allocator);

            MTL4RenderEncoder.Color[] cleared = new MTL4RenderEncoder.Color[slots];
            for (int slot = 0; slot < slots; slot++) {
                cleared[slot] = MTL4RenderEncoder.Color.cleared(targets[slot], attachmentColor(slot));
            }
            clearPass = openPass(device, buffer, cleared, "the four-attachment clear");
            if (clearPass == null) {
                END.send(buffer);
                return false;
            }
            if (!clearPass.barrierForSubsequentEncoders()) {
                END.send(buffer);
                clearPass.close();
                return failed("attachments", "the first pass's encoder does not answer "
                        + "barrierAfterStages:beforeQueueStages:visibilityOptions:, so the pass that loads its"
                        + " colour cannot be ordered against it");
            }
            clearPass.endEncoding();

            MTL4RenderEncoder.Color[] reused = {
                    new MTL4RenderEncoder.Color(targets[0], AttachmentContents.CARRIED, null),
                    MTL4RenderEncoder.Color.cleared(targets[1], reclearedColor())};
            reusedPass = openPass(device, buffer, reused, "the load-and-reclear pass");
            if (reusedPass == null) {
                END.send(buffer);
                return false;
            }
            reusedPass.endEncoding();

            // Two slots whose contents are discarded: loaded DontCare and stored DontCare. Their result is not
            // asserted below, and cannot be - the API leaves it undefined on purpose.
            MTL4RenderEncoder.Color[] discarded = {
                    new MTL4RenderEncoder.Color(targets[2], new AttachmentContents(false, true), null),
                    new MTL4RenderEncoder.Color(targets[3], new AttachmentContents(false, false), null)};
            discardPass = openPass(device, buffer, discarded, "the discard pass");
            if (discardPass == null) {
                END.send(buffer);
                return false;
            }
            discardPass.endEncoding();

            // A slot the caller reserved and did not fill, which is what an MRT descriptor looks like when the
            // program behind it writes fewer outputs than the pass carries. Measured: this loop used to
            // dereference the null and the whole frame died with a NullPointerException, and the client reached
            // it on Vitrail's MRT fixture, whose coverage path hands the backend two unused slots before the
            // attachment it does write. The filled slots have to keep their own indices, which the readback
            // below says twice: slot 0 still holds its first pass's colour, and the third entry of this array
            // re-clears the texture it names.
            MTL4RenderEncoder.Color[] withUnused = {
                    new MTL4RenderEncoder.Color(targets[0], AttachmentContents.CARRIED, null),
                    null,
                    MTL4RenderEncoder.Color.cleared(targets[1], reclearedColor())};
            unusedPass = openPass(device, buffer, withUnused, "the unused-slot pass");
            if (unusedPass == null) {
                END.send(buffer);
                return false;
            }
            unusedPass.endEncoding();
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("attachments", "the shared event did not reach 1 within 2000 ms, so the submitted"
                        + " passes never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);

                // Slot 0: cleared in pass one, loaded and stored by pass two, never written again - so its
                // colour is the reading that says the load and the store both happened.
                MTLTexture.bytes(targets[0], pixel, 4L, 0L, 0L, 1L, 1L);
                if (!matches(pixel, EXPECTED_ATTACHMENTS[0])) {
                    return failed("attachments", "slot 0 reads " + describe(pixel) + " where pass one cleared it to"
                            + " " + describe(EXPECTED_ATTACHMENTS[0]) + ", so the pass that loaded it either lost"
                            + " it or was given another slot's texture");
                }

                // Slot 1: cleared in pass one and re-cleared in pass two, which is a clear landing on an
                // attachment that already held something.
                MTLTexture.bytes(targets[1], pixel, 4L, 0L, 0L, 1L, 1L);
                if (!matches(pixel, RECLEARED_PIXEL)) {
                    return failed("attachments", "slot 1 reads " + describe(pixel) + " where the second pass"
                            + " re-cleared it to " + describe(RECLEARED_PIXEL) + ", so a clear on a reused"
                            + " attachment did not land or landed in another slot");
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("attachments", "describing or reading back the four attachments threw " + threw);
        } finally {
            if (clearPass != null) {
                clearPass.close();
            }
            if (reusedPass != null) {
                reusedPass.close();
            }
            if (discardPass != null) {
                discardPass.close();
            }
            if (unusedPass != null) {
                unusedPass.close();
            }
            for (MemorySegment target : targets) {
                releaseIfPresent(target);
            }
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** Opens one pass of the attachment smoke, turning its refusal into this probe's stage and reason. */
    private static MTL4RenderEncoder openPass(final MTLDevice device, final MemorySegment buffer,
                                              final MTL4RenderEncoder.Color[] colors, final String which) {
        return openPass(device, buffer, colors, null, which);
    }

    /** The same, for a pass that also carries a depth attachment. */
    private static MTL4RenderEncoder openPass(final MTLDevice device, final MemorySegment buffer,
                                              final MTL4RenderEncoder.Color[] colors,
                                              final MTL4RenderEncoder.Depth depth, final String which) {
        try {
            return MTL4RenderEncoder.open(device, buffer, TARGET_SIZE, TARGET_SIZE, colors, depth, which);
        } catch (MTL4RenderEncoder.Refused refused) {
            failed("attachments", which + " could not be opened at stage " + refused.stage() + ": "
                    + refused.getMessage());
            return null;
        }
    }

    /** The clear colour one attachment slot is asked for, as the descriptor's four components. */
    private static float[] attachmentColor(final int slot) {
        int[] pixel = EXPECTED_ATTACHMENTS[slot];
        return new float[]{pixel[0] / 255.0f, pixel[1] / 255.0f, pixel[2] / 255.0f, pixel[3] / 255.0f};
    }

    /** The colour the second pass re-clears a reused attachment to. */
    private static float[] reclearedColor() {
        return new float[]{RECLEARED_PIXEL[0] / 255.0f, RECLEARED_PIXEL[1] / 255.0f,
                RECLEARED_PIXEL[2] / 255.0f, RECLEARED_PIXEL[3] / 255.0f};
    }


    /**
     * Whether a whole layout can be bound through one table a stage and drawn, which is the new model's core.
     * <p>
     * There is no per-resource setter on a Metal 4 encoder: a pass fills a table and assigns it for the stages
     * that read it. This smoke is that shape end to end - a vertex table carrying a vertex buffer <em>with its
     * attribute stride</em> and a vertex-stage uniform, a fragment table carrying a fragment-stage uniform, a
     * texture and a sampler, both assigned at their own stages, one pipeline, one draw - and the pixel read back
     * is one only the whole chain can produce: the texture is the base, the vertex uniform adds to red, the
     * fragment uniform adds to green, and the vertices themselves come out of the buffer (devices 191, 128, 191
     * and 255, each of which changes if one binding is missing).
     * <p>
     * Two more commands are exercised with a reading rather than a call count: a scissor rectangle set to the
     * left half, so a pixel inside it holds the colour and a pixel outside it holds the pass's clear (which is
     * what makes the scissor a measurement), and an explicit cull mode, whose <em>effect</em> is not asserted
     * here - that needs a deliberately back-facing triangle, which is a milestone of its own - but whose call
     * has to be accepted.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether a two-stage, four-binding layout draws the pixel that only it can produce
     */
    public static boolean canBindALayout(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("layout", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment target = MemorySegment.NULL;
        MemorySegment source = MemorySegment.NULL;
        MemorySegment sampler = MemorySegment.NULL;
        MemorySegment vertexPipeline = MemorySegment.NULL;
        MTLBuffer vertices = null;
        MTLBuffer tint = null;
        MTLBuffer bias = null;
        MTLBuffer clearUniform = null;
        MTL4ArgumentTable vertexTable = null;
        MTL4ArgumentTable fragmentTable = null;
        MTL4ArgumentTable clearTable = null;
        MTL4RenderEncoder clearPass = null;
        MTL4RenderEncoder layoutPass = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("layout", "a Metal 4 queue, allocator, command buffer or shared event came back nil");
            }

            target = newTarget(device);
            source = newTarget(device);
            if (ObjC.isNil(target) || ObjC.isNil(source)) {
                return failed("layout", "one of the two " + TARGET_SIZE + "x" + TARGET_SIZE + " RGBA8 textures came"
                        + " back nil: target=" + !ObjC.isNil(target) + " source=" + !ObjC.isNil(source));
            }

            try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {
                descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.supportArgumentBuffers(true);
                sampler = device.newSamplerState(descriptor);
            }
            if (ObjC.isNil(sampler)) {
                return failed("layout", "newSamplerStateWithDescriptor: answered nil, so the layout's sampler has"
                        + " nothing to bind");
            }

            // Three vertices of position and uv, so the draw's geometry comes out of the buffer and not out of a
            // literal in the shader.
            vertices = device.newBuffer(VERTEX_LENGTH, STORAGE_SHARED);
            if (vertices.gpuAddress() == 0L) {
                return failed("layout", "the vertex buffer has no GPU address");
            }
            MemorySegment vertexData = vertices.contents().reinterpret(VERTEX_LENGTH);
            float[][] corners = {{-1.0f, 1.0f, 0.5f, 0.5f}, {3.0f, 1.0f, 0.5f, 0.5f},
                                 {-1.0f, -3.0f, 0.5f, 0.5f}};
            for (int corner = 0; corner < corners.length; corner++) {
                for (int part = 0; part < corners[corner].length; part++) {
                    vertexData.set(JAVA_FLOAT, corner * 16L + part * 4L, corners[corner][part]);
                }
            }

            // The vertex-stage tint adds to red; the fragment-stage bias adds to green. Each one is a different
            // component, so a binding that did not reach the shader is a different pixel rather than a dimmer one.
            // The layout's own shaders read a float4 at offset 0; the builtin clear shader reads its colour at
            // offset 32, because that struct carries a depth first. Two layouts, so the offset is a parameter.
            tint = newUniform(device, 0.5f, 0.0f, 0.0f, 0.0f, 0L);
            bias = newUniform(device, 0.0f, 0.25f, 0.0f, 0.0f, 0L);
            clearUniform = newUniform(device, LAYOUT_SOURCE_PIXEL[0] / 255.0f, LAYOUT_SOURCE_PIXEL[1] / 255.0f,
                    LAYOUT_SOURCE_PIXEL[2] / 255.0f, 1.0f, 32L);
            if (tint == null || bias == null || clearUniform == null) {
                return failed("layout", "one of the three uniform buffers has no GPU address");
            }

            // The plan is the production object, so the smoke builds one and fills the tables from it rather than
            // from literals: if the plan's mapping is wrong, this is where the pixel stops being the expected one.
            // The three named bindings are the ones the smoke's own MSL declares, described the way the shared
            // translation would describe them: a vertex-stage uniform at buffer 1, a fragment-stage uniform at
            // buffer 0, and a sampled image at texture 0 with its sampler at 0.
            Metal4BindingPlan plan = Metal4BindingPlan.of(List.of(
                    new MetalResourceBinding(MetalResourceBinding.ResourceKind.UNIFORM_BUFFER, "tint", 1,
                            MetalShaderStages.VERTEX, null, 1, -1, -1),
                    new MetalResourceBinding(MetalResourceBinding.ResourceKind.UNIFORM_BUFFER, "bias", 2,
                            MetalShaderStages.FRAGMENT, null, 0, -1, -1),
                    new MetalResourceBinding(MetalResourceBinding.ResourceKind.SAMPLED_IMAGE, "source", 0,
                            MetalShaderStages.FRAGMENT, null, 0, 0, -1)),
                    0, 1);

            // A table is sized to the plan's own answer for its stage, which is one past the highest index that
            // stage is given - not the number of names, and not including another stage's bindings.
            vertexTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.VERTEX),
                    plan.textureSlots(MetalShaderStages.VERTEX), plan.samplerSlots(MetalShaderStages.VERTEX));
            fragmentTable = MTL4ArgumentTable.create(device, plan.bufferSlots(MetalShaderStages.FRAGMENT),
                    plan.textureSlots(MetalShaderStages.FRAGMENT), plan.samplerSlots(MetalShaderStages.FRAGMENT));
            clearTable = MTL4ArgumentTable.create(device, 1L, 0L, 0L);
            if (vertexTable == null || fragmentTable == null || clearTable == null) {
                return failed("layout", "a table this layout needs came back null: vertex=" + (vertexTable != null)
                        + " fragment=" + (fragmentTable != null) + " clear=" + (clearTable != null));
            }
            Metal4BindingPlan.Slot tintSlot = plan.slot("tint");
            Metal4BindingPlan.Slot biasSlot = plan.slot("bias");
            Metal4BindingPlan.Slot sourceSlot = plan.slot("source");
            if (tintSlot == null || biasSlot == null || sourceSlot == null) {
                return failed("layout", "the plan does not hold a binding the smoke's own MSL declares, so a"
                        + " lookup the frame path depends on answered nothing");
            }
            if (!vertexTable.address(vertices.gpuAddress(), 16L, plan.firstVertexBufferSlot())
                    || !vertexTable.address(tint.gpuAddress(), tintSlot.metalIndex())
                    || !fragmentTable.address(bias.gpuAddress(), biasSlot.metalIndex())
                    || !fragmentTable.texture(source, sourceSlot.metalIndex())
                    || !fragmentTable.sampler(sampler, sourceSlot.samplerMetalIndex())
                    || !clearTable.address(clearUniform.gpuAddress(), 1L)) {
                return failed("layout", "one of the layout's bindings was refused by the table the plan sized for"
                        + " it - " + plan.describe());
            }

            vertexPipeline = MTLBuiltinPipelines.buildPipelineForProbe(LAYOUT_MSL, "metallum_layout_probe_vs",
                    "metallum_layout_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            MemorySegment clearPipeline = MTLBuiltinPipelines.ensureClearPipeline(
                    MTLPixelFormat.RGBA8Unorm.value, MTLPixelFormat.Invalid.value, true);
            if (ObjC.isNil(vertexPipeline) || ObjC.isNil(clearPipeline)) {
                return failed("layout", "a pipeline this smoke draws with came back nil: layout="
                        + !ObjC.isNil(vertexPipeline) + " clear=" + !ObjC.isNil(clearPipeline));
            }

            BEGIN.send(buffer, allocator);

            // The source is filled the same way the sampled smoke fills its pattern, so what the layout samples
            // is a colour this sequence wrote rather than one the texture happened to be created with.
            clearPass = openPass(device, buffer,
                    new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(source, new float[]{
                            LAYOUT_SOURCE_PIXEL[0] / 255.0f, LAYOUT_SOURCE_PIXEL[1] / 255.0f,
                            LAYOUT_SOURCE_PIXEL[2] / 255.0f, 1.0f})}, "the layout source's clear");
            if (clearPass == null) {
                END.send(buffer);
                return false;
            }
            if (!clearPass.barrierForSubsequentEncoders()) {
                END.send(buffer);
                clearPass.close();
                return failed("layout", "the pass that fills the sampled source does not answer the producer"
                        + " barrier, so the layout's sample has no encoded dependency on it");
            }
            clearPass.endEncoding();

            layoutPass = openPass(device, buffer,
                    new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(target, new float[]{0.0f, 0.0f,
                            0.0f, 1.0f})}, "the layout draw");
            if (layoutPass == null) {
                END.send(buffer);
                return false;
            }
            // The scissor is set to the left half, so the right half must read the pass's clear: that is the
            // reading that says the scissor reached the encoder rather than being accepted and ignored.
            if (!layoutPass.setScissorRect(0L, 0L, TARGET_SIZE / 2L, TARGET_SIZE)
                    || !layoutPass.setCullMode(MTLCullMode.None.value)
                    || !layoutPass.setRenderPipelineState(vertexPipeline)
                    || !layoutPass.setArgumentTable(vertexTable, STAGE_VERTEX)
                    || !layoutPass.setArgumentTable(fragmentTable, STAGE_FRAGMENT)) {
                END.send(buffer);
                layoutPass.close();
                return failed("layout", "the layout draw's encoder refused one of the commands it needs - the"
                        + " scissor, the cull mode, the pipeline or one of the two tables");
            }
            if (!layoutPass.drawPrimitives(MTLPrimitiveType.Triangle.value, 0L, 3L, 1L, 0L)) {
                END.send(buffer);
                layoutPass.close();
                return failed("layout", "the encoder does not answer the draw selector, so nothing would be drawn"
                        + " even with every binding in place");
            }
            layoutPass.endEncoding();
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("layout", "the shared event did not reach 1 within 2000 ms, so the submitted draw"
                        + " never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);

                // Inside the scissor: the whole layout's answer.
                MTLTexture.bytes(target, pixel, 4L, 8L, 8L, 1L, 1L);
                if (!matches(pixel, EXPECTED_LAYOUT_PIXEL)) {
                    return failed("layout", "the layout draw produced " + describe(pixel) + " where "
                            + describe(EXPECTED_LAYOUT_PIXEL) + " was asked for, so one of the four bindings - the"
                            + " vertex buffer, the vertex tint, the sampled texture or the fragment bias - did not"
                            + " reach the shader");
                }

                // Outside it: the pass's clear, so the rectangle was honoured and not merely accepted.
                MTLTexture.bytes(target, pixel, 4L, TARGET_SIZE - 8L, 8L, 1L, 1L);
                if (!matches(pixel, CLEAR_PIXEL)) {
                    return failed("layout", "the pixel outside the scissor rectangle reads " + describe(pixel)
                            + " where the pass's clear " + describe(CLEAR_PIXEL) + " was expected, so the scissor"
                            + " did not reach the encoder");
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("layout", "binding or drawing the layout threw " + threw);
        } finally {
            if (clearPass != null) {
                clearPass.close();
            }
            if (layoutPass != null) {
                layoutPass.close();
            }
            if (vertexTable != null) {
                vertexTable.close();
            }
            if (fragmentTable != null) {
                fragmentTable.close();
            }
            if (clearTable != null) {
                clearTable.close();
            }
            releaseIfPresent(vertexPipeline);
            releaseIfPresent(sampler);
            releaseIfPresent(source);
            releaseIfPresent(target);
            releaseIfPresent(bias);
            releaseIfPresent(tint);
            releaseIfPresent(clearUniform);
            releaseIfPresent(vertices);
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** A 48-byte uniform buffer with one float4 colour at the offset the shader that reads it declares. */
    private static MTLBuffer newUniform(final MTLDevice device, final float red, final float green, final float blue,
                                        final float alpha, final long colourOffset) {
        MTLBuffer uniform = device.newBuffer(UNIFORM_LENGTH, STORAGE_SHARED);
        if (uniform.gpuAddress() == 0L) {
            return null;
        }
        MemorySegment contents = uniform.contents().reinterpret(UNIFORM_LENGTH);
        contents.set(JAVA_FLOAT, colourOffset, red);
        contents.set(JAVA_FLOAT, colourOffset + 4L, green);
        contents.set(JAVA_FLOAT, colourOffset + 8L, blue);
        contents.set(JAVA_FLOAT, colourOffset + 12L, alpha);
        return uniform;
    }


    /**
     * Whether a texture's contents can be copied on the new command model - whole, and region by region.
     * <p>
     * The plan's blit smoke is "a pattern source texture, a copied subregion, a destination, a readback", and on
     * Metal 4 the copies live in the compute encoder: there is no blit encoder, and this is the shape a frame's
     * texture uploads, downloads and copies take. The smoke is built so that a region copy has four coordinates
     * to be wrong about: a pattern of four flat quadrants is rendered into the source, a 32x32 region of it is
     * copied to a destination's other half, and both the inside and the outside of where it landed are read.
     * <p>
     * Then the whole texture is copied into a second destination - the form that has nowhere to be wrong about
     * where a pixel came from - and every quadrant of it is compared with the pattern, which is what says the
     * whole-texture form carried the contents rather than a corner of them.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether a whole and a region copy both land where they were asked to
     */
    public static boolean canCopyTextureRegions(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("copy", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment source = MemorySegment.NULL;
        MemorySegment regionTarget = MemorySegment.NULL;
        MemorySegment wholeTarget = MemorySegment.NULL;
        MemorySegment patternPipeline = MemorySegment.NULL;
        MTL4RenderEncoder patternPass = null;
        MTL4RenderEncoder clearPass = null;
        MTL4ComputeEncoder copies = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("copy", "a Metal 4 queue, allocator, command buffer or shared event came back nil");
            }

            source = newTarget(device);
            regionTarget = newTarget(device);
            wholeTarget = newTarget(device);
            if (ObjC.isNil(source) || ObjC.isNil(regionTarget) || ObjC.isNil(wholeTarget)) {
                return failed("copy", "one of the three " + TARGET_SIZE + "x" + TARGET_SIZE + " RGBA8 textures came"
                        + " back nil: source=" + !ObjC.isNil(source) + " region=" + !ObjC.isNil(regionTarget)
                        + " whole=" + !ObjC.isNil(wholeTarget));
            }

            patternPipeline = MTLBuiltinPipelines.buildPipelineForProbe(PATTERN_MSL, "metallum_pattern_probe_vs",
                    "metallum_pattern_probe_fs", MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(patternPipeline)) {
                return failed("copy", "the pattern pipeline came back nil, so the source has no four quadrants to"
                        + " copy out of");
            }

            BEGIN.send(buffer, allocator);

            patternPass = openPass(device, buffer,
                    new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(source, new float[]{0.0f, 0.0f,
                            0.0f, 1.0f})}, "the copy source's pattern");
            if (patternPass == null) {
                END.send(buffer);
                return false;
            }
            if (!patternPass.setRenderPipelineState(patternPipeline)
                    || !patternPass.drawPrimitives(MTLPrimitiveType.Triangle.value, 0L, 3L, 1L, 0L)) {
                END.send(buffer);
                patternPass.close();
                return failed("copy", "the pass that draws the copy source's pattern refused its pipeline or its"
                        + " draw");
            }
            if (!patternPass.barrierForSubsequentEncoders()) {
                END.send(buffer);
                patternPass.close();
                return failed("copy", "the pattern pass does not answer the producer barrier, so the copy that"
                        + " reads it has no encoded dependency");
            }
            patternPass.endEncoding();

            // Both destinations cleared, in one pass with two attachments, because a region copy writes only
            // part of its destination and the rest of it has to be a colour the readback knows.
            clearPass = openPass(device, buffer,
                    new MTL4RenderEncoder.Color[]{
                            MTL4RenderEncoder.Color.cleared(regionTarget, new float[]{0.0f, 0.0f, 0.0f, 1.0f}),
                            MTL4RenderEncoder.Color.cleared(wholeTarget, new float[]{0.0f, 0.0f, 0.0f, 1.0f})},
                    "the copy destinations' clear");
            if (clearPass == null) {
                END.send(buffer);
                return false;
            }
            if (!clearPass.barrierForSubsequentEncoders()) {
                END.send(buffer);
                clearPass.close();
                return failed("copy", "the pass that clears the copy destinations does not answer the producer"
                        + " barrier");
            }
            clearPass.endEncoding();

            try {
                copies = MTL4ComputeEncoder.open(device, buffer, "the copy pass");
            } catch (MTL4ComputeEncoder.Refused refused) {
                END.send(buffer);
                return failed("copy", "the copy pass could not be opened at stage " + refused.stage() + ": "
                        + refused.getMessage());
            }

            // The source's top-left quadrant, 32x32 at the origin, into the region destination's top-right
            // quadrant. Its origin is the point of the smoke: a whole-texture copy cannot be wrong about where a
            // pixel came from, and this one can be wrong about four coordinates.
            if (!copies.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, PATTERN_EDGE, PATTERN_EDGE, 1L,
                    regionTarget, 0L, 0L, PATTERN_EDGE, 0L, 0L)) {
                END.send(buffer);
                copies.close();
                return failed("copy", "the compute encoder refused the region copy, so this command model's only"
                        + " copy path does not answer");
            }
            // And the whole texture into the second destination, which is the form the engine's texture views and
            // mip chains use.
            if (!copies.copyTextureToTexture(source, wholeTarget)) {
                END.send(buffer);
                copies.close();
                return failed("copy", "the compute encoder refused the whole-texture copy");
            }
            copies.endEncoding();
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("copy", "the shared event did not reach 1 within 2000 ms, so the submitted copies"
                        + " never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);

                // Where the region landed: the source's top-left quadrant, at the destination's top-right.
                MTLTexture.bytes(regionTarget, pixel, 4L, PATTERN_EDGE + 8L, 8L, 1L, 1L);
                if (!matches(pixel, EXPECTED_PATTERN[0])) {
                    return failed("copy", "the region copy put " + describe(pixel) + " where the source's"
                            + " top-left quadrant " + describe(EXPECTED_PATTERN[0]) + " was asked for, so the"
                            + " region's source origin or its destination origin is not the one it was given");
                }
                // And where it did not: the destination's other half is still the clear it started from, which is
                // what says the copy wrote its region and not the whole texture.
                MTLTexture.bytes(regionTarget, pixel, 4L, 8L, 8L, 1L, 1L);
                if (!matches(pixel, CLEAR_PIXEL)) {
                    return failed("copy", "the region copy also wrote " + describe(pixel) + " outside the region it"
                            + " was given, where the clear " + describe(CLEAR_PIXEL) + " should still be");
                }

                // The whole copy: every quadrant of the source, in its own place.
                for (int index = 0; index < PATTERN_PIXELS.length; index++) {
                    MTLTexture.bytes(wholeTarget, pixel, 4L, PATTERN_PIXELS[index][0], PATTERN_PIXELS[index][1],
                            1L, 1L);
                    if (!matches(pixel, EXPECTED_PATTERN[index])) {
                        return failed("copy", "the whole-texture copy reads " + describe(pixel) + " at ("
                                + PATTERN_PIXELS[index][0] + ", " + PATTERN_PIXELS[index][1] + ") where the"
                                + " pattern's " + quadrant(index) + " " + describe(EXPECTED_PATTERN[index])
                                + " was asked for");
                    }
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("copy", "copying the texture regions threw " + threw);
        } finally {
            if (patternPass != null) {
                patternPass.close();
            }
            if (clearPass != null) {
                clearPass.close();
            }
            if (copies != null) {
                copies.close();
            }
            releaseIfPresent(patternPipeline);
            releaseIfPresent(wholeTarget);
            releaseIfPresent(regionTarget);
            releaseIfPresent(source);
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }


    /** What the depth smoke clears its depth attachment to. */
    private static final double CLEAR_DEPTH = 0.25;

    /**
     * Whether a pass can carry a depth attachment and clear it, which is the half of a frame's clears the
     * attachment smoke does not reach.
     * <p>
     * The plan's depth phase is two overlapping triangles with a known winner; that needs a pipeline, a depth
     * compare state and a draw. What is measured here is the step before it and the one a frame's first clear
     * needs: a pass whose attachments are a colour target and a depth target, both loaded as cleared and both
     * stored, and then a readback of the depth texture itself. A clear that landed in the wrong attachment, or
     * a depth attachment the descriptor dropped, would read as something other than the number it was given.
     *
     * @param device the device binding, as {@link #canBindAndDraw} takes it
     * @return whether a depth attachment is cleared and read back as the value it was given
     */
    public static boolean canClearDepth(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("depth", "the device does not answer one of the factories this sequence's queue,"
                    + " allocator, command buffer or shared event would come from");
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment target = MemorySegment.NULL;
        MemorySegment depth = MemorySegment.NULL;
        MTL4RenderEncoder clearPass = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return failed("depth", "a Metal 4 queue, allocator, command buffer or shared event came back nil");
            }

            target = newTarget(device);
            depth = newDepthTarget(device);
            if (ObjC.isNil(target) || ObjC.isNil(depth)) {
                return failed("depth", "one of the two " + TARGET_SIZE + "x" + TARGET_SIZE + " attachments came"
                        + " back nil: colour=" + !ObjC.isNil(target) + " depth=" + !ObjC.isNil(depth));
            }

            BEGIN.send(buffer, allocator);
            // Opened here rather than through the shared helper, because that one reports a refused pass under
            // the colour-attachment smoke's stage: a depth pass that could not be opened would then be printed
            // as the attachments smoke failing, in the same line that says the attachments smoke passed.
            try {
                clearPass = MTL4RenderEncoder.open(device, buffer, TARGET_SIZE, TARGET_SIZE,
                        new MTL4RenderEncoder.Color[]{
                                MTL4RenderEncoder.Color.cleared(target, new float[]{0.0f, 0.0f, 0.0f, 1.0f})},
                        new MTL4RenderEncoder.Depth(depth, CLEAR_DEPTH), "the depth clear");
            } catch (MTL4RenderEncoder.Refused refused) {
                END.send(buffer);
                return failed("depth", "a pass carrying a depth attachment could not be opened at stage "
                        + refused.stage() + ": " + refused.getMessage());
            }
            if (clearPass == null) {
                END.send(buffer);
                return failed("depth", "the depth-carrying pass did not open and did not say why");
            }
            clearPass.endEncoding();
            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("depth", "the shared event did not reach 1 within 2000 ms, so the submitted clear"
                        + " never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);

                // The colour attachment first: a clear that landed in the wrong attachment would show here.
                MTLTexture.bytes(target, pixel, 4L, 0L, 0L, 1L, 1L);
                if (!matches(pixel, CLEAR_PIXEL)) {
                    return failed("depth", "the colour attachment of a depth-carrying pass reads "
                            + describe(pixel) + " where its clear " + describe(CLEAR_PIXEL) + " was asked for");
                }

                // And the depth attachment itself, as the four bytes a Depth32Float texel is. The comparison is
                // written as "inside the tolerance" and negated rather than as "outside it": NaN is outside no
                // tolerance, so `Math.abs(read - clear) > 0.0001f` would let a NaN readback pass as the value
                // that was asked for, and a check that cannot fail is not evidence.
                MTLTexture.bytes(depth, pixel, 4L, 0L, 0L, 1L, 1L);
                float read = pixel.get(JAVA_FLOAT, 0L);
                if (!(Math.abs(read - (float) CLEAR_DEPTH) <= 0.0001f)) {
                    return failed("depth", "the depth attachment reads " + read + " where its clear "
                            + CLEAR_DEPTH + " was asked for, so the depth clear did not land - or the descriptor"
                            + " dropped the depth attachment");
                }
            }

            return true;
        } catch (RuntimeException threw) {
            return failed("depth", "clearing and reading back the depth attachment threw " + threw);
        } finally {
            if (clearPass != null) {
                clearPass.close();
            }
            releaseIfPresent(depth);
            releaseIfPresent(target);
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** One shared, readback-able depth target: the format a frame's depth attachment is. */
    private static MemorySegment newDepthTarget(final MTLDevice device) {
        try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
            descriptor.pixelFormat(MTLPixelFormat.Depth32Float);
            descriptor.width(TARGET_SIZE);
            descriptor.height(TARGET_SIZE);
            descriptor.usage(USAGE_RENDER_TARGET);
            descriptor.storageMode(MTLStorageMode.Shared);
            return device.newTexture(descriptor);
        }
    }

    /** The name of one of the pattern's quadrants, for a message that says which one a readback landed in. */
    private static String quadrant(final int index) {
        return switch (index) {
            case 0 -> "top-left";
            case 1 -> "top-right";
            case 2 -> "bottom-left";
            default -> "bottom-right";
        };
    }

    private static boolean failed(final String stage, final String why) {
        failureStage = stage;
        failure = why;
        return false;
    }

    private static String failure;
    private static String failureStage;

    public static boolean canBindAndDraw(final MTLDevice device) {
        failure = null;
        failureStage = null;
        if (!device.respondsTo("newMTL4CommandQueue") || !device.respondsTo("newCommandAllocator")
                || !device.respondsTo("newCommandBuffer") || !device.respondsTo("newSharedEvent")) {
            return failed("selectors", "the device does not answer one of newMTL4CommandQueue,"
                    + " newCommandAllocator, newCommandBuffer or newSharedEvent - queue="
                    + device.respondsTo("newMTL4CommandQueue") + " allocator="
                    + device.respondsTo("newCommandAllocator") + " buffer="
                    + device.respondsTo("newCommandBuffer") + " event=" + device.respondsTo("newSharedEvent"));
        }

        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment target = MemorySegment.NULL;
        MemorySegment vertexTarget = MemorySegment.NULL;
        MemorySegment pass = MemorySegment.NULL;
        MTLBuffer uniformBuffer = null;
        MTLBuffer vertexBuffer = null;
        MTL4ArgumentTable table = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)
                    || !responds(event, "waitUntilSignaledValue:timeoutMS:")) {
                return failed("objects", "a Metal 4 queue, allocator, command buffer or shared event came back"
                        + " nil, or the event does not answer waitUntilSignaledValue:timeoutMS: - queue="
                        + !ObjC.isNil(queue) + " allocator=" + !ObjC.isNil(allocator) + " buffer="
                        + !ObjC.isNil(buffer) + " event=" + !ObjC.isNil(event));
            }

            // The address is the whole difference between this path and the Metal 3 one, so it is asked for
            // rather than assumed: a buffer whose address this OS will not give cannot be bound here.
            uniformBuffer = device.newBuffer(UNIFORM_LENGTH, STORAGE_SHARED);
            if (uniformBuffer.gpuAddress() == 0L) {
                return failed("uniform", "the device gave the uniform buffer no GPU address");
            }
            MemorySegment uniforms = uniformBuffer.contents().reinterpret(UNIFORM_LENGTH);
            uniforms.set(JAVA_FLOAT, 0, 0.0f);
            uniforms.set(JAVA_FLOAT, 32, 0.25f);
            uniforms.set(JAVA_FLOAT, 36, 0.5f);
            uniforms.set(JAVA_FLOAT, 40, 0.75f);
            uniforms.set(JAVA_FLOAT, 44, 1.0f);

            table = MTL4ArgumentTable.create(device, 2L, 0L, 0L);
            if (table == null) {
                return failed("table", "newArgumentTableWithDescriptor:error: answered nil");
            }

            if (!table.address(uniformBuffer.gpuAddress(), 1L)) {
                return failed("uniform", "the table refused setAddress:atIndex: for the uniform buffer");
            }

            MemorySegment drawTarget = newTarget(device);
            target = drawTarget;
            if (ObjC.isNil(drawTarget)) {
                // The one exit that had no reason at all, and the one whose failure used to surface later and
                // elsewhere: a nil target is not a draw that went wrong, it is a target that was never made.
                return failed("target", "newTextureWithDescriptor: answered nil for the " + TARGET_SIZE + "x"
                        + TARGET_SIZE + " RGBA8 render target");
            }

            // A second target for the second pass, which is the plan's own two-encoder shape - pass A into
            // target A, pass B into target B, one command buffer, one commit - and it is also what lets both
            // passes be read back. One target cannot do both jobs: the second pass clears its target, so the
            // first pass's pixel would be gone before anything read it and the check on the uniform draw would
            // go with it. EXPECTED_UNIFORM_PIXEL was declared and compared nowhere for exactly that reason.
            vertexTarget = newTarget(device);
            if (ObjC.isNil(vertexTarget)) {
                return failed("target", "newTextureWithDescriptor: answered nil for the second " + TARGET_SIZE + "x"
                        + TARGET_SIZE + " RGBA8 render target, which the vertex-buffer pass draws into");
            }

            // The second shape: a vertex buffer bound by address *and* stride, read by a pipeline whose
            // colour comes out of that buffer.
            vertexBuffer = device.newBuffer(VERTEX_LENGTH, STORAGE_SHARED);
            if (vertexBuffer.gpuAddress() == 0L) {
                return failed("vertex", "the device gave the vertex buffer no GPU address");
            }
            MemorySegment vertices = vertexBuffer.contents().reinterpret(VERTEX_LENGTH);
            float[][] corners = {{-1.0f, 1.0f, 0.25f, 0.5f}, {3.0f, 1.0f, 0.25f, 0.5f},
                                 {-1.0f, -3.0f, 0.25f, 0.5f}};
            for (int corner = 0; corner < corners.length; corner++) {
                for (int part = 0; part < corners[corner].length; part++) {
                    vertices.set(JAVA_FLOAT, corner * 16L + part * 4L, corners[corner][part]);
                }
            }

            MTL4ArgumentTable verticesTable = MTL4ArgumentTable.create(device, 1L, 0L, 0L);
            if (verticesTable == null) {
                return failed("table", "the vertex table answered nil for the second argument table");
            }

            if (!verticesTable.address(vertexBuffer.gpuAddress(), 16L, 0L)) {
                return failed("table", "the table refused setAddress:attributeStride:atIndex: for the vertex"
                        + " buffer (does the device support attribute strides?)");
            }

            MemorySegment clearPipeline = MTLBuiltinPipelines.ensureClearPipeline(
                    MTLPixelFormat.RGBA8Unorm.value, MTLPixelFormat.Invalid.value, true);
            MemorySegment vertexPipeline = MTLBuiltinPipelines.buildPipelineForProbe(
                    VERTEX_BUFFER_MSL, "metallum_vb_probe_vs", "metallum_vb_probe_fs",
                    MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(clearPipeline) || ObjC.isNil(vertexPipeline)) {
                ObjC.release(vertexPipeline);
                verticesTable.close();
                return failed("pipelines", "a built-in pipeline came back nil: clear=" + !ObjC.isNil(clearPipeline)
                        + " vertex=" + !ObjC.isNil(vertexPipeline) + " (the probe's own MSL compiles here)");
            }

            BEGIN.send(buffer, allocator);
            pass = NEW_RENDER_PASS.sendPtr(ObjC.clazz("MTL4RenderPassDescriptor"));
            if (ObjC.isNil(pass)) {
                END.send(buffer);
                ObjC.release(vertexPipeline);
                verticesTable.close();
                return failed("pass", "newRenderPassDescriptor answered nil for the first pass");
            }
            SET_TARGET_WIDTH.send(pass, TARGET_SIZE);
            SET_TARGET_HEIGHT.send(pass, TARGET_SIZE);
            MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(pass);
            MemorySegment attachment = ObjC.isNil(attachments)
                    ? MemorySegment.NULL
                    : ATTACHMENT_AT.sendPtr(attachments, 0L);
            if (ObjC.isNil(attachment)) {
                END.send(buffer);
                ObjC.release(vertexPipeline);
                verticesTable.close();
                return failed("attachment", "the render pass descriptor gave no colour attachment at index 0");
            }
            SET_TEXTURE.send(attachment, drawTarget);
            SET_LOAD_ACTION.send(attachment, LOAD_DONT_CARE);
            SET_STORE_ACTION.send(attachment, STORE_STORE);

            boolean drew = false;
            MemorySegment encoder = RENDER_ENCODER.sendPtr(buffer, pass);
            if (!ObjC.isNil(encoder)) {
                SET_ARGUMENT_TABLE.send(encoder, table.handle(), STAGE_VERTEX);
                SET_RENDER_PIPELINE_STATE.send(encoder, clearPipeline);
                DRAW.send(encoder, MTLPrimitiveType.Triangle.value, 0L, 3L);
                END_ENCODING.send(encoder);
                drew = true;
            }
            ObjC.release(pass);
            pass = MemorySegment.NULL;

            // The same target, cleared and then drawn over by the vertex-buffer pipeline: one more pass in
            // the same command buffer, which is also what says two encoders of the new kind can follow one
            // another without an event between them.
            if (drew) {
                drew = encodeVertexDraw(buffer, vertexTarget, verticesTable.handle(), vertexPipeline);
            }
            END.send(buffer);
            ObjC.release(vertexPipeline);
            verticesTable.close();
            if (!drew) {
                return failed("encoder", "a render command encoder could not be opened on the Metal 4 command"
                        + " buffer, or one of the two passes did not encode");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return failed("completion", "the shared event did not reach 1 within 2000 ms, so the submitted"
                        + " work never completed");
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);

                // Screen one: the uniform pass, into its own target, which nothing has written over. This check
                // was missing entirely - the constant was declared and compared nowhere - so a device whose
                // table-bound uniform stopped reaching the draw was never contradicted, only reported as a
                // vertex-buffer failure one pass later.
                MTLTexture.bytes(target, pixel, 4L, 0L, 0L, 1L, 1L);
                if (!matches(pixel, EXPECTED_UNIFORM_PIXEL)) {
                    return failed("pixel", "the uniform pass drew " + describe(pixel) + " where "
                            + describe(EXPECTED_UNIFORM_PIXEL) + " was asked for, so the address-bound uniform"
                            + " did not reach the draw");
                }

                // Screen two: the vertex-buffer pass, whose target was cleared first, so the answers below are
                // findings rather than one ambiguous pixel.
                MTLTexture.bytes(vertexTarget, pixel, 4L, 0L, 0L, 1L, 1L);
                if (!matches(pixel, EXPECTED_VERTEX_PIXEL)) {
                    String saw = describe(pixel);
                    if (matches(pixel, CLEAR_PIXEL)) {
                        return failed("pixel", "the vertex-buffer pass ran and drew nothing: its target reads "
                                + saw + ", the clear colour it started from, so the pipeline and the encoder took"
                                + " the work and the vertex buffer produced no fragment");
                    }
                    if (matches(pixel, EXPECTED_UNIFORM_PIXEL)) {
                        return failed("pixel", "the second pass read the first pass's colour " + saw + " in its own"
                                + " cleared target, which no clear can leave behind: the two targets are not the"
                                + " two textures the passes were given");
                    }
                    return failed("pixel", "the vertex-buffer pass drew " + saw + " where "
                            + describe(EXPECTED_VERTEX_PIXEL) + " was asked for");
                }
            }

            return true;
        } catch (RuntimeException failed) {
            // The deep half of the probe fails here - a pipeline that would not compile, an encoder that refused
            // an argument table, a readback that threw - and it used to return false as silently as a device
            // that cannot do this at all. Naming the throwable is what tells the two apart.
            return failed("exception", "the draw or the readback threw " + failed);
        } finally {
            if (table != null) {
                table.close();
            }
            releaseIfPresent(uniformBuffer);
            releaseIfPresent(vertexBuffer);
            releaseIfPresent(target);
            releaseIfPresent(vertexTarget);
            releaseIfPresent(pass);
            releaseIfPresent(event);
            releaseIfPresent(buffer);
            releaseIfPresent(allocator);
            releaseIfPresent(queue);
        }
    }

    /** Whether a readback is exactly an expected pixel, channel by channel. */
    private static boolean matches(final MemorySegment pixel, final int[] expected) {
        for (int index = 0; index < expected.length; index++) {
            if ((pixel.get(JAVA_BYTE, index) & 0xFF) != expected[index]) {
                return false;
            }
        }
        return true;
    }

    /** The four channels of a readback, for a message that says what was seen and not only what was wrong. */
    private static String describe(final MemorySegment pixel) {
        return "(" + (pixel.get(JAVA_BYTE, 0L) & 0xFF) + ", " + (pixel.get(JAVA_BYTE, 1L) & 0xFF) + ", "
                + (pixel.get(JAVA_BYTE, 2L) & 0xFF) + ", " + (pixel.get(JAVA_BYTE, 3L) & 0xFF) + ")";
    }

    private static String describe(final int[] pixel) {
        return "(" + pixel[0] + ", " + pixel[1] + ", " + pixel[2] + ", " + pixel[3] + ")";
    }

    /** One shared, readback-able colour target. */
    private static MemorySegment newTarget(final MTLDevice device) {
        try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
            descriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
            descriptor.width(TARGET_SIZE);
            descriptor.height(TARGET_SIZE);
            descriptor.usage(USAGE_RENDER_TARGET);
            descriptor.storageMode(MTLStorageMode.Shared);
            return device.newTexture(descriptor);
        }
    }

    /** The edge of the sampled-texture smoke's source: small, so a readback is four bytes. */
    private static final long SAMPLED_SIZE = 4L;

    /**
     * The vertex-buffer pass, into a target of its own, which it clears before it draws.
     * <p>
     * The clear is what makes a missed draw readable: this target used to hold the first pass's colour on a
     * hit and undefined memory on a miss, and 191 - the first pass's own pixel - was one of the values a miss
     * could legitimately return.
     */
    private static boolean encodeVertexDraw(final MemorySegment commandBuffer, final MemorySegment target,
                                            final MemorySegment vertexTable, final MemorySegment pipeline) {
        return encodePass(commandBuffer, target, vertexTable, STAGE_VERTEX, pipeline, false,
                "the vertex-buffer pass");
    }

    /**
     * One full-screen pass into a target of its own, with the table and the barrier its caller asks for.
     * <p>
     * Every target is cleared rather than left undefined, so that "the pass ran and drew nothing" is a reading
     * and not a guess: an unwritten pixel is the clear colour, which no draw in this probe produces. The
     * barrier is the new command model's producer barrier and is encoded only where a later encoder reads what
     * this one wrote.
     *
     * @param which a name for the pass, so a failure says which one it was
     * @return whether the pass was encoded and ended
     */
    private static boolean encodePass(final MemorySegment commandBuffer, final MemorySegment target,
                                      final MemorySegment table, final long stages, final MemorySegment pipeline,
                                      final boolean barrier, final String which) {
        MemorySegment pass = NEW_RENDER_PASS.sendPtr(ObjC.clazz("MTL4RenderPassDescriptor"));
        if (ObjC.isNil(pass)) {
            return failed("pass", "newRenderPassDescriptor answered nil for " + which);
        }

        try {
            SET_TARGET_WIDTH.send(pass, TARGET_SIZE);
            SET_TARGET_HEIGHT.send(pass, TARGET_SIZE);
            MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(pass);
            MemorySegment attachment = ObjC.isNil(attachments)
                    ? MemorySegment.NULL
                    : ATTACHMENT_AT.sendPtr(attachments, 0L);
            if (ObjC.isNil(attachment)) {
                return failed("attachment", "the descriptor for " + which + " gave no colour attachment at"
                        + " index 0");
            }
            SET_TEXTURE.send(attachment, target);
            SET_LOAD_ACTION.send(attachment, LOAD_CLEAR);
            SET_STORE_ACTION.send(attachment, STORE_STORE);
            SET_CLEAR_COLOR.send(attachment, 0.0, 0.0, 0.0, 1.0);

            MemorySegment encoder = RENDER_ENCODER.sendPtr(commandBuffer, pass);
            if (ObjC.isNil(encoder)) {
                return failed("encoder", "no render command encoder could be opened on this command buffer for "
                        + which);
            }
            if (!ObjC.isNil(table)) {
                SET_ARGUMENT_TABLE.send(encoder, table, stages);
            }
            SET_RENDER_PIPELINE_STATE.send(encoder, pipeline);
            DRAW.send(encoder, MTLPrimitiveType.Triangle.value, 0L, 3L);
            if (barrier) {
                // Asked before it is sent, like every other selector here: a barrier this encoder does not
                // implement is an Objective-C exception, and a pass that sampled without one would be a
                // dependency that was assumed - which is the one thing a migration must not do.
                if (!responds(encoder, BARRIER.name())) {
                    END_ENCODING.send(encoder);
                    return failed("barrier", which + "'s encoder does not answer " + BARRIER.name() + ", so it"
                            + " cannot order itself against the pass that reads its target");
                }
                BARRIER.send(encoder, STAGE_ALL, STAGE_FRAGMENT, VISIBILITY_DEVICE);
            }
            END_ENCODING.send(encoder);
            return true;
        } finally {
            ObjC.release(pass);
        }
    }


    /** Seventeen sampled images with seventeen samplers, which is one past Metal's sampler slots. */
    private static String seventeenSamplersMsl() {
        StringBuilder source = new StringBuilder(
                "#include <metal_stdlib>\nusing namespace metal;\n\nfragment float4 probe_seventeen(\n");
        for (int index = 0; index < 17; index++) {
            source.append("  texture2d<float> t").append(index)
                    .append(" [[texture(").append(index).append(")]],\n");
        }
        for (int index = 0; index < 17; index++) {
            source.append("  sampler s").append(index).append(" [[sampler(").append(index).append(")]]")
                    .append(index == 16 ? "\n" : ",\n");
        }
        source.append(") {\n  float4 sum = float4(0.0);\n");
        for (int index = 0; index < 17; index++) {
            source.append("  sum += t").append(index).append(".sample(s").append(index)
                    .append(", float2(0.5, 0.5));\n");
        }
        source.append("  return sum;\n}\n");
        return source.toString();
    }

    /** A sampler named by a resource id in the buffer index space, which is the other way to bind one. */
    private static final String ID_SAMPLER_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            fragment float4 probe_id_sampler(
              texture2d<float> t0 [[texture(0)]],
              sampler s0 [[id(0)]]
            ) {
              return t0.sample(s0, float2(0.5, 0.5));
            }
            """;

    /** A texture named the same way, for the case where the sampler is the one with a slot left. */
    private static final String ID_TEXTURE_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            fragment float4 probe_id_texture(
              texture2d<float> t0 [[id(0)]],
              sampler s0 [[sampler(0)]]
            ) {
              return t0.sample(s0, float2(0.5, 0.5));
            }
            """;

    /**
     * What a stage past the sixteen sampler slots can do, asked of the compiler and the device.
     * <p>
     * The engine reaches for an argument buffer when a program's highest sampler slot is fifteen or more,
     * and a Metal 4 table holds sixteen samplers - so the question "can the whole chain move" turns on
     * whether there is a second way to bind a sampler. Three answers are worth having and each is one call:
     * whether the compiler takes seventeen direct samplers (it should not), whether it takes a sampler named
     * by a resource id, and whether a table will even be made for twenty sampler slots (the header says the
     * maximum is sixteen, and a header is not the runtime).
     *
     * @return one line of answers, or the empty string where the device cannot be asked at all
     */
    public static String samplerCeiling(final MTLDevice device) {
        String direct = device.newFunction(seventeenSamplersMsl(), "probe_seventeen") == MemorySegment.NULL
                ? "refused" : "accepted";
        String byId = device.newFunction(ID_SAMPLER_MSL, "probe_id_sampler") == MemorySegment.NULL
                ? "refused" : "accepted";
        String textureById = device.newFunction(ID_TEXTURE_MSL, "probe_id_texture") == MemorySegment.NULL
                ? "refused" : "accepted";

        MTL4ArgumentTable wide = MTL4ArgumentTable.create(device, 0L, 0L, 20L);
        String table = wide == null ? "refused" : "accepted";
        if (wide != null) {
            wide.close();
        }

        return "seventeen direct samplers " + direct + ", a sampler by resource id " + byId
                + ", a texture by resource id " + textureById + ", a table asking for twenty sampler slots "
                + table;
    }

    /** Lets a wrapper go by its handle, so a probe that failed half way still releases what it made. */
    private static void releaseIfPresent(final @Nullable MemorySegment object) {
        if (object != null && !ObjC.isNil(object)) {
            ObjC.release(object);
        }
    }

    private static void releaseIfPresent(final @Nullable MTLBuffer object) {
        if (object != null) {
            ObjC.release(object.handle());
        }
    }


    /** Whether an object answers to a selector, which is the question to ask before reaching anything. */
    public static boolean respondsTo(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    /**
     * Whether the new command structure can actually be built on this device.
     *
     * @param device the device binding, which is what every selector is asked of first
     * @return whether a queue, an allocator and a begun command buffer were all made
     */
    public static boolean canMakeAndSubmit(final MTLDevice device) {
        boolean allocatorWithoutDescriptor = device.respondsTo("newCommandAllocator");
        boolean allocatorWithError = device.respondsTo("newCommandAllocatorWithDescriptor:error:");
        boolean allocatorWithDescriptor =
                allocatorWithError || device.respondsTo("newCommandAllocatorWithDescriptor:");
        if (!device.respondsTo("newMTL4CommandQueue")
                || !device.respondsTo("newCommandBuffer")
                || !device.respondsTo("newSharedEvent")
                || !(allocatorWithoutDescriptor || allocatorWithDescriptor)) {
            return false;
        }

        MemorySegment descriptorClass = MemorySegment.NULL;
        MemorySegment descriptor = MemorySegment.NULL;
        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            if (allocatorWithoutDescriptor) {
                allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            } else {
                descriptorClass = ObjC.clazz("MTL4CommandAllocatorDescriptor");
                descriptor = ObjC.isNil(descriptorClass) ? MemorySegment.NULL : NEW_DESCRIPTOR.sendPtr(descriptorClass);
                // The error slot is part of this factory's name, the same way it is for the argument
                // table: `newCommandAllocatorWithDescriptor:` alone is a selector no device implements.
                allocator = ObjC.isNil(descriptor)
                        ? MemorySegment.NULL
                        : (allocatorWithError
                                ? NEW_ALLOCATOR_WITH_ERROR.sendPtr(device.handle(), descriptor, MemorySegment.NULL)
                                : NEW_ALLOCATOR_WITH_DESCRIPTOR.sendPtr(device.handle(), descriptor));
            }

            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer)) {
                return false;
            }

            // Asked of the buffer itself too, for the same reason: an object's protocol is as much a
            // subset of what its header declares as the device's factory surface turned out to be.
            if (!responds(buffer, "beginCommandBufferWithAllocator:") || !responds(buffer, "endCommandBuffer")) {
                return false;
            }
            BEGIN.send(buffer, allocator);

            // A real pass, so what the queue takes is a command buffer with work in it rather than an empty
            // one: one 64x64 colour target that nothing loads and the pass stores, encoded and ended. The
            // pass descriptor is Metal 4's, and its attachments are Metal 3's own classes - which is why
            // the load and store actions here are the ones the engine already sets on its own passes.
            MemorySegment target = MemorySegment.NULL;
            MemorySegment pass = MemorySegment.NULL;
            try (AutoreleasePool _ = AutoreleasePool.push()) {
                MemorySegment passClass;
                try {
                    passClass = ObjC.clazz("MTL4RenderPassDescriptor");
                } catch (Throwable missing) {
                    return false;
                }

                try (MTLTextureDescriptor targetDescriptor = MTLTextureDescriptor.create()) {
                    targetDescriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
                    targetDescriptor.width(TARGET_SIZE);
                    targetDescriptor.height(TARGET_SIZE);
                    targetDescriptor.usage(USAGE_RENDER_TARGET);
                    target = device.newTexture(targetDescriptor);
                } catch (RuntimeException refused) {
                    return false;
                }

                pass = NEW_RENDER_PASS.sendPtr(passClass);
                if (ObjC.isNil(pass) || !responds(buffer, "renderCommandEncoderWithDescriptor:")) {
                    return false;
                }

                SET_TARGET_WIDTH.send(pass, TARGET_SIZE);
                SET_TARGET_HEIGHT.send(pass, TARGET_SIZE);
                MemorySegment attachments = COLOR_ATTACHMENTS.sendPtr(pass);
                MemorySegment attachment = ObjC.isNil(attachments)
                        ? MemorySegment.NULL
                        : ATTACHMENT_AT.sendPtr(attachments, 0L);
                if (ObjC.isNil(attachment)) {
                    return false;
                }

                SET_TEXTURE.send(attachment, target);
                SET_LOAD_ACTION.send(attachment, LOAD_DONT_CARE);
                SET_STORE_ACTION.send(attachment, STORE_STORE);

                MemorySegment encoder = RENDER_ENCODER.sendPtr(buffer, pass);
                if (ObjC.isNil(encoder) || !responds(encoder, "endEncoding")) {
                    return false;
                }
                END_ENCODING.send(encoder);
            } finally {
                ObjC.release(pass);
                ObjC.release(target);
            }

            END.send(buffer);

            // And submitted, because a command buffer that can be begun is not yet one the queue takes.
            // The proof is the queue itself: it signals a shared event after the committed work, and the
            // event's own CPU wait answers whether the GPU got there - a real submission rather than an
            // accepted call. Every one of these is asked for first, like the factories above.
            if (!responds(queue, "commit:count:") || !responds(queue, "signalEvent:value:")) {
                return false;
            }
            MemorySegment event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(event) || !responds(event, "waitUntilSignaledValue:timeoutMS:")) {
                ObjC.release(event);
                return false;
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            boolean ran = WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) != 0L;
            ObjC.release(event);
            return ran;
        } catch (RuntimeException failed) {
            return false;
        } finally {
            ObjC.release(buffer);
            ObjC.release(allocator);
            ObjC.release(queue);
            ObjC.release(descriptor);
        }
    }
}
