import com.metallum.mtl.MTLBuiltinPipelines;
import com.metallum.mtl.MTLDevice;
import com.metallum.mtl.MTLPixelFormat;
import com.metallum.mtl.MTLSamplerDescriptor;
import com.metallum.mtl.MTLSamplerMinMagFilter;
import com.metallum.mtl.MTLStorageMode;
import com.metallum.mtl.MTLTexture;
import com.metallum.mtl.MTLTextureDescriptor;
import com.metallum.mtl.metal4.MTL4ArgumentTable;
import com.metallum.mtl.metal4.MTL4ComputeEncoder;
import com.metallum.mtl.metal4.MTL4Probe;
import com.metallum.mtl.metal4.MTL4RenderEncoder;
import com.metallum.mtl.metal4.MTL4ResidencySet;
import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import org.lwjgl.system.MemoryStack;

import java.lang.foreign.Arena;
import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * The smallest functional reproducer for the fault the round-41 census found: a region copy encoded in a
 * compute encoder, in a command buffer that also holds render passes, leaves the process in a state where the
 * *storage-image smoke's second dispatch stops landing* - the texture reads the first dispatch's colour where
 * the second's was asked for.
 *
 * <p>What it does per round, in this order and for the reason the real suite runs in this order:
 *
 * <ol>
 *   <li>{@link MTL4Probe#canWriteStorageImage} - the victim. It is a kernel writing a texture through a table
 *       re-pointed between two dispatches, which is the mechanism the frame path's storage clear is built
 *       from;</li>
 *   <li>the trigger - a pass that clears a source, a copy of a region of it into a destination's other half,
 *       and a pass that samples the destination. Three encoders, one command buffer, one commit.</li>
 * </ol>
 *
 * <p>The measured signature with the trigger in the real suite: rounds 1 and 2 pass and every odd round from
 * the third fails - four runs of one cold process plus four warm probes failed the storage smoke in four of
 * four runs, and a ten-warm run failed probes 3, 5, 7 and 9. Four bisects in that round removed the table
 * shape, the table re-point and the copy's barrier as causes, and removing the copy encoder's block while
 * keeping its textures, passes, table and residency set made the fault disappear (11 of 11). So what is left
 * to find is which part of *this* block does it, and this file is where that is asked - one variant per run,
 * with the trigger's own lines as the only difference between them.
 *
 * <p>It is deliberately not wired into the census: the census has to keep meaning "this capability works",
 * and a suite that is red for a reason it does not itself explain is worse than a suite that does not ask.
 *
 * <pre>
 * M4_REPRO round=3 storage=FAIL copy=ok storageReason=storageImage(...) copyReason=-
 * </pre>
 */
public final class CopyThenDispatchRepro {

    private static final Msg NEW_QUEUE = Msg.of("newMTL4CommandQueue", ADDRESS);
    private static final Msg NEW_ALLOCATOR = Msg.of("newCommandAllocator", ADDRESS);
    private static final Msg NEW_COMMAND_BUFFER = Msg.of("newCommandBuffer", ADDRESS);
    private static final Msg NEW_SHARED_EVENT = Msg.of("newSharedEvent", ADDRESS);
    private static final Msg BEGIN = Msg.ofVoid("beginCommandBufferWithAllocator:", ADDRESS);
    private static final Msg END = Msg.ofVoid("endCommandBuffer");
    private static final Msg COMMIT = Msg.ofVoid("commit:count:", ADDRESS, JAVA_LONG);
    private static final Msg SIGNAL_EVENT = Msg.ofVoid("signalEvent:value:", ADDRESS, JAVA_LONG);
    /** Return type first, then the two arguments: the SDK's selector takes a value and a timeout. */
    private static final Msg WAIT_UNTIL_SIGNALED =
            Msg.of("waitUntilSignaledValue:timeoutMS:", JAVA_LONG, JAVA_LONG, JAVA_LONG);
    private static final Msg ADD_RESIDENCY_SET = Msg.ofVoid("addResidencySet:", ADDRESS);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private static final long EDGE = 64L;
    private static final long HALF = EDGE / 2L;
    private static final long USAGE_RENDER_TARGET = 4L;
    private static final long USAGE_SHADER_READ = 1L;
    private static final long USAGE_SHADER_WRITE = 2L;
    private static final long STORAGE_SHARED = 0L;
    private static final int[] SOURCE_PIXEL = {30, 60, 90, 255};
    private static final int[] DESTINATION_PIXEL = {200, 100, 50, 255};

    /** A full-screen triangle sampling a table-bound texture and sampler, which is the sampled pass's half. */
    private static final String SAMPLED_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            struct ReproOut {
              float4 position [[position]];
              float2 uv;
            };

            vertex ReproOut repro_vs(uint vertexId [[vertex_id]]) {
              const float2 corners[3] = { float2(-1.0, 1.0), float2(3.0, 1.0), float2(-1.0, -3.0) };
              const float2 uvs[3] = { float2(0.0, 0.0), float2(2.0, 0.0), float2(0.0, 2.0) };
              ReproOut out;
              out.position = float4(corners[vertexId], 0.0, 1.0);
              out.uv = uvs[vertexId];
              return out;
            }

            fragment float4 repro_fs(ReproOut in [[stage_in]],
                                     texture2d<float> source [[texture(0)]],
                                     sampler nearest [[sampler(0)]]) {
              return source.sample(nearest, in.uv);
            }
            """;

    /** The three colours the own victim's three dispatches write, in order: red, green, blue. */
    private static final int[][] OWN_COLOURS = {{255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}};

    /** The own victim's kernel: one colour per dispatch, written over the whole image. */
    private static final String OWN_VICTIM_MSL = """
            #include <metal_stdlib>
            using namespace metal;

            kernel void repro_write(texture2d<float, access::write> image [[texture(0)]],
                                    constant float4& colour [[buffer(0)]],
                                    uint2 xy [[thread_position_in_grid]]) {
              image.write(colour, xy);
            }
            """;

    private CopyThenDispatchRepro() {
    }

    /**
     * The shape's parts, so one run can remove exactly one of them.
     * <p>
     * The variants exist because the ingredient is one of these and not the whole: `no-copy` keeps the compute
     * encoder and drops the copy command, `no-copy-encoder` drops the encoder with it, `no-sampled-pass` keeps
     * the copy and drops the pass that reads it, `separate-commit` gives the copy a command buffer and a commit
     * of its own, `no-residency` declares nothing, and `textures-released-last` hands the textures back after
     * the command buffer, the allocator and the queue instead of before them.
     */
    private record Shape(
            boolean sourcePass,
            boolean destinationClear,
            boolean copyEncoder,
            boolean copyCommand,
            boolean sampledPass,
            boolean separateCommit,
            boolean residency,
            boolean texturesReleasedLast,
            boolean wholeCopy,
            boolean plainTextures,
            boolean unboundCopyTarget,
            boolean bufferCopy
    ) {
    }

    private static Shape shape(final String variant) {
        // sourcePass, destinationClear, copyEncoder, copyCommand, sampledPass, separateCommit, residency,
        // texturesReleasedLast, wholeCopy, plainTextures, unboundCopyTarget, bufferCopy
        return switch (variant) {
            case "full" -> new Shape(true, true, true, true, true, false, true, false, false, false, false, false);
            case "full-copy" ->
                    new Shape(true, true, true, true, true, false, true, false, true, false, false, false);
            case "buffer-copy" ->
                    new Shape(true, true, true, true, true, false, true, false, false, false, false, true);
            case "no-copy" ->
                    new Shape(true, true, true, false, true, false, true, false, false, false, false, false);
            case "no-copy-encoder" ->
                    new Shape(true, true, false, false, true, false, true, false, false, false, false, false);
            case "no-sampled-pass" ->
                    new Shape(true, true, true, true, false, false, true, false, false, false, false, false);
            case "no-source-pass" ->
                    new Shape(false, true, true, true, true, false, true, false, false, false, false, false);
            case "no-destination-clear" ->
                    new Shape(true, false, true, true, true, false, true, false, false, false, false, false);
            case "separate-commit" ->
                    // No destination clear: it is encoded in the main buffer, which is committed after the
                    // copy's own commit, so it would land on top of what the copy wrote.
                    new Shape(true, false, true, true, true, true, true, false, false, false, false, false);
            case "no-residency" ->
                    new Shape(true, true, true, true, true, false, false, false, false, false, false, false);
            case "textures-released-last" ->
                    new Shape(true, true, true, true, true, false, true, true, false, false, false, false);
            case "plain-destination" ->
                    new Shape(true, false, true, true, true, false, true, false, false, true, false, false);
            case "copy-to-unbound" ->
                    new Shape(true, true, true, true, true, false, true, false, false, false, true, false);
            default -> null;
        };
    }

    public static void main(final String[] args) {
        int rounds = args.length > 0 ? Integer.parseInt(args[0]) : 8;
        String variant = args.length > 1 ? args[1] : "full";
        String ownMode = args.length > 2 ? args[2] : "one-encoder";
        Shape shape = shape(variant);
        if (shape == null) {
            System.out.println("M4_REPRO device=failed reason=unknown-variant(" + variant + ")");
            System.exit(2);
            return;
        }
        MTLDevice device;
        try {
            device = MTLDevice.createSystemDefault();
        } catch (Throwable throwable) {
            System.out.println("M4_REPRO device=failed reason=" + oneLine(throwable.getMessage()));
            System.exit(2);
            return;
        }
        if (device == null) {
            System.out.println("M4_REPRO device=failed reason=no-system-default-device");
            System.exit(2);
            return;
        }
        MTLBuiltinPipelines.init(device);

        int storageFailures = 0;
        int copyFailures = 0;
        for (int round = 1; round <= rounds; round++) {
            // The victim first, then the trigger: that is the order the real suite runs them in, and it is what
            // makes the failure a fact about the *next* round rather than about this one.
            boolean storage = MTL4Probe.canWriteStorageImage(device);
            String storageReason = storage ? "-" : MTL4Probe.lastFailureStage() + "(" + MTL4Probe.lastFailure() + ")";
            // The same smoke again, immediately: a first call that fails where the second passes is a stale
            // state a second attempt clears, and a pair that both fail is the state itself.
            boolean storageAgain = MTL4Probe.canWriteStorageImage(device);
            // The own victim, beside the probe's: three dispatches, each through a table of its own, each
            // writing the whole image its own colour. The colour that is left says how many of the three
            // commands landed - blue is all three, green is two, red is one - which is what separates a dropped
            // command from a binding that went stale.
            String ownVictim = ownVictim(device, ownMode);
            String copyReason = trigger(device, shape);
            boolean copy = copyReason == null;
            if (!storage) {
                storageFailures++;
            }
            if (!copy) {
                copyFailures++;
            }
            System.out.println("M4_REPRO variant=" + variant
                    + " round=" + round
                    + " storage=" + storage
                    + " storageAgain=" + storageAgain
                    + " ownVictim=" + ownVictim
                    + " copy=" + copy
                    + " storageReason=" + oneLine(storageReason).replace(' ', '_')
                    + " copyReason=" + oneLine(copyReason == null ? "-" : copyReason).replace(' ', '_'));
        }
        System.out.println("M4_REPRO SUMMARY variant=" + variant + " rounds=" + rounds
                + " storageFailures=" + storageFailures + " copyFailures=" + copyFailures);
        System.exit(0);
    }

    /**
     * The victim with a counter in it: three dispatches of the same kernel through three tables of their own,
     * each writing the whole image its own colour.
     * <p>
     * The colour left in the image is the answer to "how many commands landed": blue is all three, green is the
     * first two, red is the first alone. A re-pointed table would fail differently - the later dispatches would
     * write the first colour, which reads as red with the *third* command having run - so this is what tells
     * the two apart, and it is why the own victim exists beside the probe's smoke rather than instead of it.
     *
     * @return which colour the image holds, or why the sequence could not be run
     */
    private static String ownVictim(final MTLDevice device, final String ownMode) {
        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment image = MemorySegment.NULL;
        MemorySegment function = MemorySegment.NULL;
        MemorySegment pipeline = MemorySegment.NULL;
        com.metallum.mtl.MTLBuffer[] colours = new com.metallum.mtl.MTLBuffer[2];
        MTL4ArgumentTable table = null;
        MTL4ArgumentTable secondTable = null;
        MTL4ResidencySet resident = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return "no-queue";
            }

            try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
                descriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
                descriptor.width(8L);
                descriptor.height(8L);
                descriptor.usage(USAGE_SHADER_WRITE | USAGE_SHADER_READ);
                descriptor.storageMode(MTLStorageMode.Shared);
                image = device.newTexture(descriptor);
            }
            if (ObjC.isNil(image)) {
                return "no-image";
            }

            for (int index = 0; index < 2; index++) {
                colours[index] = device.newBuffer(16L, STORAGE_SHARED);
                if (colours[index] == null || colours[index].gpuAddress() == 0L) {
                    return "no-colour-buffer";
                }
                MemorySegment words = colours[index].contents().reinterpret(16L);
                for (int channel = 0; channel < 4; channel++) {
                    words.set(java.lang.foreign.ValueLayout.JAVA_FLOAT, channel * 4L,
                            OWN_COLOURS[index][channel] / 255.0f);
                }
            }

            // One table, handed the first colour, re-pointed at the second between the dispatches: the probe
            // smoke's own shape, which is what makes this victim comparable to it.
            table = MTL4ArgumentTable.create(device, 1L, 1L, 0L);
            if (table == null || !table.address(colours[0].gpuAddress(), 0L) || !table.texture(image, 0L)) {
                return "no-table";
            }

            function = device.newFunction(OWN_VICTIM_MSL, "repro_write");
            if (ObjC.isNil(function)) {
                return "no-function";
            }
            pipeline = device.newComputePipelineState(function);
            if (ObjC.isNil(pipeline)) {
                return "no-pipeline";
            }

            resident = MTL4ResidencySet.create(device, 4L, "the own victim");
            if (resident == null || !resident.add(image) || !resident.add(colours[0].handle())
                    || !resident.add(colours[1].handle())
                    || !resident.commit() || !resident.requestResidency()
                    || !responds(queue, "addResidencySet:")) {
                return "no-residency";
            }
            ADD_RESIDENCY_SET.send(queue, resident.handle());

            // One command buffer, one commit, and the encoder count is the switch: one encoder carrying both
            // dispatches (what the engine does), one encoder each, or a commit each.
            // The event's value advances with every commit, which is what makes each wait a wait for its own
            // submission: signalling 1 twice would make the second wait return immediately and read an image
            // the second dispatch had not written yet.
            long signalled = 0L;
            MTL4ComputeEncoder dispatch = null;
            BEGIN.send(buffer, allocator);
            for (int index = 0; index < 2; index++) {
                if (index == 1) {
                    if (!table.address(colours[1].gpuAddress(), 0L)) {
                        END.send(buffer);
                        return "no-repoint";
                    }
                }
                if (ownMode.equals("two-commits") && index == 1) {
                    END.send(buffer);
                    signalled++;
                    try (Arena arena = Arena.ofConfined()) {
                        MemorySegment buffers = arena.allocate(ADDRESS, 1);
                        buffers.set(ADDRESS, 0L, buffer);
                        COMMIT.send(queue, buffers, 1L);
                    }
                    SIGNAL_EVENT.send(queue, event, signalled);
                    if (WAIT_UNTIL_SIGNALED.sendLong(event, signalled, 2000L) == 0L) {
                        return "no-completion";
                    }
                    BEGIN.send(buffer, allocator);
                }
                // The switch that matters: `one-encoder` is the probe smoke's own shape - one encoder
                // carrying both dispatches, with the table re-pointed between them - while `two-encoders`
                // gives each dispatch its own.
                if (ownMode.equals("one-encoder")) {
                    if (index == 0) {
                        dispatch = MTL4ComputeEncoder.open(device, buffer, "the own victim's one encoder");
                        if (!prepare(dispatch, pipeline, table)) {
                            END.send(buffer);
                            return "no-dispatch";
                        }
                    } else if (ownMode.equals("fresh-table")) {
                        // The same encoder, a table of its own for the second dispatch: this is the question of
                        // whether a table may be re-pointed inside an encoder at all, or whether the encoder's
                        // snapshot is what is cached.
                        secondTable = MTL4ArgumentTable.create(device, 1L, 1L, 0L);
                        if (secondTable == null || !secondTable.texture(image, 0L)
                                || !secondTable.address(colours[1].gpuAddress(), 0L)
                                || !prepare(dispatch, pipeline, secondTable)) {
                            END.send(buffer);
                            return "no-fresh-table";
                        }
                    } else if (!repoint(dispatch, table, colours[1])) {
                        END.send(buffer);
                        return "no-repoint";
                    }
                } else {
                    try (MTL4ComputeEncoder one = MTL4ComputeEncoder.open(device, buffer,
                            "the own victim's dispatch " + (index + 1))) {
                        if (!prepare(one, pipeline, table)) {
                            END.send(buffer);
                            return "no-dispatch";
                        }
                    }
                }
            }
            if (dispatch != null) {
                dispatch.close();
                dispatch = null;
            }
            if (false) {
            }
            END.send(buffer);

            signalled++;
            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, signalled);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, signalled, 2000L) == 0L) {
                return "no-completion";
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);
                MTLTexture.bytes(image, pixel, 4L, 0L, 0L, 1L, 1L);
                int[] seen = read(pixel);
                if (matches(seen, OWN_COLOURS[1])) {
                    return "green(2-of-2)";
                }
                if (matches(seen, OWN_COLOURS[0])) {
                    return "red(1-of-2)";
                }
                return "other" + describe(seen);
            }
        } catch (RuntimeException threw) {
            return "threw";
        } finally {
            if (resident != null) {
                resident.close();
            }
            if (secondTable != null) {
                secondTable.close();
            }
            if (table != null) {
                table.close();
            }
            release(pipeline);
            release(function);
            release(image);
            release(colours[0]);
            release(colours[1]);
            release(event);
            release(buffer);
            release(allocator);
            release(queue);
        }
    }

    /** Hands an encoder the pipeline and the table, and dispatches one group over the whole image. */
    private static boolean prepare(final MTL4ComputeEncoder dispatch, final MemorySegment pipeline,
                                   final MTL4ArgumentTable table) {
        return dispatch != null
                && dispatch.setComputePipelineState(pipeline)
                && dispatch.setArgumentTable(table)
                && dispatch.dispatchThreads(8L, 8L, 1L, 8L, 8L, 1L);
    }

    /** Points the table at the second colour and hands it to the encoder again, which is the re-point. */
    private static boolean repoint(final MTL4ComputeEncoder dispatch, final MTL4ArgumentTable table,
                                   final com.metallum.mtl.MTLBuffer colour) {
        return table.address(colour.gpuAddress(), 0L)
                && dispatch.setArgumentTable(table)
                && dispatch.dispatchThreads(8L, 8L, 1L, 8L, 8L, 1L);
    }

    /**
     * The trigger: a pass, a region copy in a compute encoder, and a pass that samples what the copy wrote.
     *
     * @return null when the copy's destination held the copied colour where it should, or why not
     */
    private static String trigger(final MTLDevice device, final Shape shape) {
        MemorySegment queue = MemorySegment.NULL;
        MemorySegment allocator = MemorySegment.NULL;
        MemorySegment buffer = MemorySegment.NULL;
        MemorySegment event = MemorySegment.NULL;
        MemorySegment copyQueue = MemorySegment.NULL;
        MemorySegment copyAllocator = MemorySegment.NULL;
        MemorySegment copyBuffer = MemorySegment.NULL;
        MemorySegment copyEvent = MemorySegment.NULL;
        MemorySegment source = MemorySegment.NULL;
        MemorySegment destination = MemorySegment.NULL;
        MemorySegment spare = MemorySegment.NULL;
        com.metallum.mtl.MTLBuffer firstBuffer = null;
        com.metallum.mtl.MTLBuffer secondBuffer = null;
        MemorySegment target = MemorySegment.NULL;
        MemorySegment sampler = MemorySegment.NULL;
        MemorySegment pipeline = MemorySegment.NULL;
        MTL4ArgumentTable table = null;
        MTL4ResidencySet resident = null;
        try {
            queue = NEW_QUEUE.sendPtr(device.handle());
            allocator = NEW_ALLOCATOR.sendPtr(device.handle());
            buffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
            event = NEW_SHARED_EVENT.sendPtr(device.handle());
            if (ObjC.isNil(queue) || ObjC.isNil(allocator) || ObjC.isNil(buffer) || ObjC.isNil(event)) {
                return "a queue, allocator, command buffer or event came back nil";
            }
            if (shape.separateCommit()) {
                copyQueue = NEW_QUEUE.sendPtr(device.handle());
                copyAllocator = NEW_ALLOCATOR.sendPtr(device.handle());
                copyBuffer = NEW_COMMAND_BUFFER.sendPtr(device.handle());
                copyEvent = NEW_SHARED_EVENT.sendPtr(device.handle());
                if (ObjC.isNil(copyQueue) || ObjC.isNil(copyAllocator) || ObjC.isNil(copyBuffer)
                        || ObjC.isNil(copyEvent)) {
                    return "the copy's own queue, allocator, command buffer or event came back nil";
                }
            }

            long textureUsage = shape.plainTextures()
                    ? USAGE_SHADER_READ | USAGE_SHADER_WRITE
                    : USAGE_RENDER_TARGET | USAGE_SHADER_READ;
            source = target(device, textureUsage);
            destination = target(device, textureUsage);
            // The discriminator: the copy's destination is a texture no table names, while the table keeps
            // binding the texture the copy does not touch.
            spare = shape.unboundCopyTarget() ? target(device, textureUsage) : MemorySegment.NULL;
            target = target(device, USAGE_RENDER_TARGET);
            if (ObjC.isNil(source) || ObjC.isNil(destination) || ObjC.isNil(target)
                    || (shape.unboundCopyTarget() && ObjC.isNil(spare))) {
                return "a texture came back nil";
            }

            if (shape.bufferCopy()) {
                firstBuffer = device.newBuffer(16L, STORAGE_SHARED);
                secondBuffer = device.newBuffer(16L, STORAGE_SHARED);
                if (firstBuffer == null || secondBuffer == null) {
                    return "the two buffers came back nil";
                }
            }

            try (MTLSamplerDescriptor descriptor = MTLSamplerDescriptor.create()) {
                descriptor.minFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.magFilter(MTLSamplerMinMagFilter.Nearest);
                descriptor.supportArgumentBuffers(true);
                sampler = device.newSamplerState(descriptor);
            }
            if (ObjC.isNil(sampler)) {
                return "no sampler";
            }

            pipeline = MTLBuiltinPipelines.buildPipelineForProbe(SAMPLED_MSL, "repro_vs", "repro_fs",
                    MTLPixelFormat.RGBA8Unorm.value);
            if (ObjC.isNil(pipeline)) {
                return "the sampled pipeline came back nil";
            }

            table = MTL4ArgumentTable.create(device, 0L, 1L, 1L);
            if (table == null || !table.texture(destination, 0L) || !table.sampler(sampler, 0L)) {
                return "the table would not take the destination and its sampler";
            }

            if (shape.residency()) {
                resident = MTL4ResidencySet.create(device, 4L, "the copy-then-dispatch reproducer");
                if (resident == null || !resident.add(source) || !resident.add(destination)
                        || !resident.add(target)
                        || (shape.unboundCopyTarget() && !resident.add(spare))
                        || !resident.commit() || !resident.requestResidency()
                        || !responds(queue, "addResidencySet:")) {
                    return "the residency set would not take the three textures";
                }
                ADD_RESIDENCY_SET.send(queue, resident.handle());
                if (shape.separateCommit()) {
                    ADD_RESIDENCY_SET.send(copyQueue, resident.handle());
                }
            }

            BEGIN.send(buffer, allocator);

            if (shape.sourcePass()) {
                try (MTL4RenderEncoder pass = MTL4RenderEncoder.open(device, buffer, EDGE, EDGE,
                        new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(source,
                                new float[]{SOURCE_PIXEL[0] / 255.0f, SOURCE_PIXEL[1] / 255.0f,
                                        SOURCE_PIXEL[2] / 255.0f, 1.0f})}, null, "the reproducer's source pass")) {
                    if (!pass.barrierForSubsequentEncoders()) {
                        END.send(buffer);
                        return "the source pass does not answer the producer barrier";
                    }
                }
            }

            if (shape.destinationClear()) {
                try (MTL4RenderEncoder pass = MTL4RenderEncoder.open(device, buffer, EDGE, EDGE,
                        new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(destination,
                                new float[]{DESTINATION_PIXEL[0] / 255.0f, DESTINATION_PIXEL[1] / 255.0f,
                                        DESTINATION_PIXEL[2] / 255.0f, 1.0f})}, null,
                        "the reproducer's clear pass")) {
                    if (!pass.barrierForSubsequentEncoders()) {
                        END.send(buffer);
                        return "the destination's clear pass does not answer the producer barrier";
                    }
                }
            }

            if (shape.copyEncoder()) {
                // The copy goes in its own command buffer and its own commit when the variant asks for that,
                // which is the one structural difference that says whether "one command buffer" is the
                // ingredient or whether the copy is.
                boolean separate = shape.separateCommit();
                MemorySegment encoderBuffer = separate ? copyBuffer : buffer;
                if (separate) {
                    BEGIN.send(copyBuffer, copyAllocator);
                }
                try (MTL4ComputeEncoder copy = MTL4ComputeEncoder.open(device, encoderBuffer,
                        "the reproducer's copy")) {
                    if (shape.copyCommand()) {
                        MemorySegment into = shape.unboundCopyTarget() ? spare : destination;
                        if (shape.bufferCopy()) {
                            if (!copy.copyBufferToBuffer(firstBuffer.handle(), 0L, secondBuffer.handle(),
                                    0L, 16L)) {
                                END.send(buffer);
                                if (separate) {
                                    END.send(copyBuffer);
                                }
                                return "the copy encoder did not answer the buffer copy";
                            }
                        }
                        boolean copied = shape.bufferCopy() || shape.wholeCopy()
                                ? copy.copyTextureToTexture(source, into)
                                : copy.copyTextureRegion(source, 0L, 0L, 0L, 0L, 0L, HALF, HALF, 1L,
                                        into, 0L, 0L, HALF, 0L, 0L);
                        if (!shape.bufferCopy() && !copied) {
                            END.send(buffer);
                            if (separate) {
                                END.send(copyBuffer);
                            }
                            return "the copy encoder did not answer the copy";
                        }
                    }
                    if (!copy.barrierForSubsequentEncoders()) {
                        END.send(buffer);
                        if (separate) {
                            END.send(copyBuffer);
                        }
                        return "the copy encoder does not answer the producer barrier";
                    }
                }
                if (separate) {
                    END.send(copyBuffer);
                    try (Arena arena = Arena.ofConfined()) {
                        MemorySegment buffers = arena.allocate(ADDRESS, 1);
                        buffers.set(ADDRESS, 0L, copyBuffer);
                        COMMIT.send(copyQueue, buffers, 1L);
                    }
                    SIGNAL_EVENT.send(copyQueue, copyEvent, 1L);
                    if (WAIT_UNTIL_SIGNALED.sendLong(copyEvent, 1L, 2000L) == 0L) {
                        END.send(buffer);
                        return "the copy's own submission did not complete within 2000 ms";
                    }
                }
            }

            if (shape.sampledPass()) {
                try (MTL4RenderEncoder pass = MTL4RenderEncoder.open(device, buffer, EDGE, EDGE,
                        new MTL4RenderEncoder.Color[]{MTL4RenderEncoder.Color.cleared(target,
                                new float[]{0.0f, 0.0f, 0.0f, 1.0f})}, null, "the reproducer's sampled pass")) {
                    if (!pass.setCullMode(com.metallum.mtl.MTLCullMode.None.value)
                            || !pass.setRenderPipelineState(pipeline)
                            || !pass.setArgumentTable(table, 2L)
                            || !pass.drawPrimitives(com.metallum.mtl.MTLPrimitiveType.Triangle.value, 0L, 3L, 1L,
                            0L)) {
                        END.send(buffer);
                        return "the sampled pass refused one of its commands";
                    }
                }
            }

            END.send(buffer);

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment buffers = arena.allocate(ADDRESS, 1);
                buffers.set(ADDRESS, 0L, buffer);
                COMMIT.send(queue, buffers, 1L);
            }
            SIGNAL_EVENT.send(queue, event, 1L);
            if (WAIT_UNTIL_SIGNALED.sendLong(event, 1L, 2000L) == 0L) {
                return "the shared event did not reach 1 within 2000 ms";
            }

            try (Arena arena = Arena.ofConfined()) {
                MemorySegment pixel = arena.allocate(4);
                if (shape.copyCommand() && shape.destinationClear()) {
                    MTLTexture.bytes(shape.unboundCopyTarget() ? spare : destination, pixel, 4L, HALF, 0L, 1L, 1L);
                    int[] copied = read(pixel);
                    if (!matches(copied, SOURCE_PIXEL)) {
                        return "the copy's destination half reads " + describe(copied) + " where the source's "
                                + describe(SOURCE_PIXEL) + " was asked for";
                    }
                }
                if (shape.sampledPass() && shape.copyCommand() && shape.sourcePass()
                        && shape.destinationClear() && !shape.unboundCopyTarget()) {
                    MTLTexture.bytes(target, pixel, 4L, HALF + 8L, 8L, 1L, 1L);
                    int[] sampled = read(pixel);
                    if (!matches(sampled, SOURCE_PIXEL)) {
                        return "the sampled pass drew " + describe(sampled) + " where the copy's "
                                + describe(SOURCE_PIXEL) + " was asked for";
                    }
                }
            }

            return null;
        } catch (RuntimeException threw) {
            return "the trigger threw " + threw;
        } finally {
            if (resident != null) {
                resident.close();
            }
            if (table != null) {
                table.close();
            }
            release(pipeline);
            release(sampler);
            // The variant exists because a texture handed back while the command buffer that copied it is still
            // held is the shape of a lifetime fault, so the order is a switch rather than a habit.
            if (shape.texturesReleasedLast()) {
                release(copyEvent);
                release(copyBuffer);
                release(copyAllocator);
                release(copyQueue);
                release(event);
                release(buffer);
                release(allocator);
                release(queue);
                release(target);
                release(destination);
                release(source);
            } else {
                release(target);
                release(spare);
                release(destination);
                release(source);
                release(copyEvent);
                release(copyBuffer);
                release(copyAllocator);
                release(copyQueue);
                release(event);
                release(buffer);
                release(allocator);
                release(queue);
            }
        }
    }

    /** The four bytes a one-pixel readback wrote, as unsigned channels. */
    private static int[] read(final MemorySegment pixel) {
        int[] channels = new int[4];
        for (int channel = 0; channel < 4; channel++) {
            channels[channel] = pixel.get(java.lang.foreign.ValueLayout.JAVA_BYTE, channel) & 0xFF;
        }
        return channels;
    }

    private static MemorySegment target(final MTLDevice device, final long usage) {
        try (MTLTextureDescriptor descriptor = MTLTextureDescriptor.create()) {
            descriptor.pixelFormat(MTLPixelFormat.RGBA8Unorm);
            descriptor.width(EDGE);
            descriptor.height(EDGE);
            descriptor.usage(usage);
            descriptor.storageMode(MTLStorageMode.Shared);
            return device.newTexture(descriptor);
        }
    }

    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    private static void release(final MemorySegment object) {
        if (!ObjC.isNil(object)) {
            ObjC.release(object);
        }
    }

    private static void release(final com.metallum.mtl.MTLBuffer buffer) {
        if (buffer != null) {
            release(buffer.handle());
        }
    }

    private static boolean matches(final int[] pixel, final int[] expected) {
        for (int channel = 0; channel < 4; channel++) {
            if (Math.abs(pixel[channel] - expected[channel]) > 1) {
                return false;
            }
        }
        return true;
    }

    private static String describe(final int[] pixel) {
        return "(" + pixel[0] + ", " + pixel[1] + ", " + pixel[2] + ", " + pixel[3] + ")";
    }

    private static String oneLine(final String text) {
        return text == null ? "-" : text.replace('\n', ' ');
    }
}
