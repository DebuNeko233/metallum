package com.metallum.objc;

import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.Linker;
import java.lang.foreign.MemorySegment;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.util.function.Consumer;

import static java.lang.foreign.ValueLayout.*;

/**
 * An Objective-C block whose body is a Java method, built in native memory.
 * <p>
 * A block is an object whose {@code isa} says how it behaves, followed by an invocation pointer and a
 * descriptor: the storage here is a global block - allocated once for the process, never freed - with the
 * invocation being a foreign-function upcall onto a Java method whose first argument is bound at
 * construction. That is what lets a framework call back into this engine, and it is how Metal's own
 * completion blocks work: {@code addCompletedHandler:} on the Metal 3 road, and
 * {@code MTL4CommitOptions.addFeedbackHandler:} on the Metal 4 one, where the timing of a submission is
 * only ever handed to a callback and there is nothing to poll.
 * <p>
 * The upcall arrives on a queue the framework owns, so the body runs on a thread of the framework's
 * choosing and must not assume the render thread.
 */
public final class ObjCBlock {
    private static final int BLOCK_IS_GLOBAL = 1 << 28;

    private static final MemorySegment NS_CONCRETE_GLOBAL_BLOCK =
            Linker.nativeLinker().defaultLookup().findOrThrow("_NSConcreteGlobalBlock");
    private static final Arena BLOCK_ARENA = Arena.global();
    private static final MemorySegment BLOCK_DESCRIPTOR;
    private static final MethodHandle INVOKE_RUNNABLE;
    private static final MethodHandle INVOKE_CONSUMER;

    static {
        BLOCK_DESCRIPTOR = BLOCK_ARENA.allocate(16, 8);
        BLOCK_DESCRIPTOR.set(JAVA_LONG, 0, 0L);
        BLOCK_DESCRIPTOR.set(JAVA_LONG, 8, 32L);
        try {
            INVOKE_RUNNABLE = MethodHandles.lookup().findStatic(
                    ObjCBlock.class,
                    "invokeRunnable",
                    MethodType.methodType(void.class, Runnable.class, MemorySegment.class, MemorySegment.class)
            );
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Failed to resolve block invoke handle", e);
        }
        try {
            INVOKE_CONSUMER = MethodHandles.lookup().findStatic(
                    ObjCBlock.class,
                    "invokeConsumer",
                    MethodType.methodType(void.class, Consumer.class, MemorySegment.class, MemorySegment.class)
            );
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Failed to resolve block invoke handle", e);
        }
    }

    private ObjCBlock() {
    }

    public static MemorySegment withRunnable(final Runnable action) {
        MethodHandle target = MethodHandles.insertArguments(INVOKE_RUNNABLE, 0, action);
        MemorySegment invoke = ObjC.LINKER.upcallStub(target, FunctionDescriptor.ofVoid(ADDRESS, ADDRESS), BLOCK_ARENA);

        MemorySegment block = BLOCK_ARENA.allocate(32, 8);
        block.set(ADDRESS, 0, NS_CONCRETE_GLOBAL_BLOCK);
        block.set(JAVA_INT, 8, BLOCK_IS_GLOBAL);
        block.set(JAVA_INT, 12, 0);
        block.set(ADDRESS, 16, invoke);
        block.set(ADDRESS, 24, BLOCK_DESCRIPTOR);
        return block;
    }

    /**
     * A block whose invocation hands its argument to {@code action}.
     * <p>
     * The argument is the framework's own object - the commit feedback Metal passes to a feedback handler -
     * and it is only valid for the length of the call, which is what makes the consumer the shape a
     * reporting block needs: the numbers are read out of it and the object is not kept.
     */
    public static MemorySegment withConsumer(final Consumer<MemorySegment> action) {
        MethodHandle target = MethodHandles.insertArguments(INVOKE_CONSUMER, 0, action);
        MemorySegment invoke = ObjC.LINKER.upcallStub(target, FunctionDescriptor.ofVoid(ADDRESS, ADDRESS), BLOCK_ARENA);

        MemorySegment block = BLOCK_ARENA.allocate(32, 8);
        block.set(ADDRESS, 0, NS_CONCRETE_GLOBAL_BLOCK);
        block.set(JAVA_INT, 8, BLOCK_IS_GLOBAL);
        block.set(JAVA_INT, 12, 0);
        block.set(ADDRESS, 16, invoke);
        block.set(ADDRESS, 24, BLOCK_DESCRIPTOR);
        return block;
    }

    private static void invokeRunnable(final Runnable action, final MemorySegment block, final MemorySegment argument) {
        action.run();
    }

    private static void invokeConsumer(final Consumer<MemorySegment> action, final MemorySegment block,
                                       final MemorySegment argument) {
        action.accept(argument);
    }
}
