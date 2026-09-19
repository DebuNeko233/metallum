package com.metallum.mtl;

import com.metallum.objc.Msg;
import com.metallum.objc.ObjC;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

/**
 * Makes the Metal 4 core objects once, and lets them go.
 * <p>
 * The shape {@code MTLFXSpatialScalerDescriptor} was probed with, for a reason this class learned the hard
 * way: the first version of it sent {@code newCommandAllocatorWithDescriptor:} without asking, and the
 * device - which does support the Metal 4 family and does answer to {@code newMTL4CommandQueue} - answered
 * with an {@code NSInvalidArgumentException} that ended the process. **A device implements a subset of the
 * factory surface its SDK declares**, so every selector here is asked for before it is sent, and a device
 * that answers no to one is a device this path cannot be built on rather than a crash.
 * <p>
 * What is proven is reachability and nothing else: a queue of the new command structure, an allocator for a
 * command buffer's working memory, and a command buffer begun on that allocator and ended. No frame path
 * creates one.
 */
@Environment(EnvType.CLIENT)
public final class MTL4Probe {

    private static final Msg NEW_QUEUE = Msg.of("newMTL4CommandQueue", ADDRESS);
    private static final Msg NEW_ALLOCATOR = Msg.of("newCommandAllocator", ADDRESS);
    private static final Msg NEW_ALLOCATOR_WITH_DESCRIPTOR = Msg.of("newCommandAllocatorWithDescriptor:", ADDRESS, ADDRESS);
    private static final Msg NEW_COMMAND_BUFFER = Msg.of("newCommandBuffer", ADDRESS);
    private static final Msg BEGIN = Msg.ofVoid("beginCommandBufferWithAllocator:", ADDRESS);
    private static final Msg END = Msg.ofVoid("endCommandBuffer");
    private static final Msg NEW_DESCRIPTOR = Msg.of("new", ADDRESS);
    private static final Msg RESPONDS_TO_SELECTOR = Msg.of("respondsToSelector:", JAVA_LONG, ADDRESS);

    private MTL4Probe() {
    }

    /** Whether an object answers to a selector, which is the question to ask before reaching anything. */
    private static boolean responds(final MemorySegment object, final String selector) {
        return RESPONDS_TO_SELECTOR.sendLong(object, ObjC.selector(selector)) != 0L;
    }

    /**
     * Whether the new command structure can actually be built on this device.
     *
     * @param device the device binding, which is what every selector is asked of first
     * @return whether a queue, an allocator and a begun command buffer were all made
     */
    public static boolean canMakeObjects(final MTLDevice device) {
        boolean allocatorWithoutDescriptor = device.respondsTo("newCommandAllocator");
        boolean allocatorWithDescriptor = device.respondsTo("newCommandAllocatorWithDescriptor:");
        if (!device.respondsTo("newMTL4CommandQueue")
                || !device.respondsTo("newCommandBuffer")
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
                allocator = ObjC.isNil(descriptor)
                        ? MemorySegment.NULL
                        : NEW_ALLOCATOR_WITH_DESCRIPTOR.sendPtr(device.handle(), descriptor);
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
            END.send(buffer);
            return true;
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
