package com.metallum.objc;

import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.MemoryLayout;
import java.lang.foreign.MemorySegment;
import java.lang.invoke.MethodHandle;

import static java.lang.foreign.ValueLayout.ADDRESS;

public record Msg(String name, MemorySegment sel, MethodHandle handle) {

    public static Msg ofVoid(String selector, MemoryLayout... args) {
        return ofVoid(selector, false, args);
    }

    public static Msg ofVoid(String selector, boolean blocking, MemoryLayout... args) {
        return of(selector, FunctionDescriptor.ofVoid(prepend(args)), blocking);
    }

    public static Msg of(String selector, MemoryLayout returnLayout, MemoryLayout... args) {
        return of(selector, false, returnLayout, args);
    }

    public static Msg of(String selector, boolean blocking, MemoryLayout returnLayout, MemoryLayout... args) {
        return of(selector, FunctionDescriptor.of(returnLayout, prepend(args)), blocking);
    }

    private static Msg of(String selector, FunctionDescriptor descriptor, boolean blocking) {
        return new Msg(selector, ObjC.selector(selector),
                blocking ? ObjC.msgSend(descriptor) : ObjC.msgSendCritical(descriptor));
    }

    private static MemoryLayout[] prepend(MemoryLayout[] args) {
        MemoryLayout[] full = new MemoryLayout[args.length + 2];
        full[0] = ADDRESS;
        full[1] = ADDRESS;
        System.arraycopy(args, 0, full, 2, args.length);
        return full;
    }

    public void send(MemorySegment self) {
        try {
            handle.invokeExact(self, sel);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a) {
        try {
            handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, MemorySegment b) {
        try {
            handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a) {
        try {
            handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a, long b) {
        try {
            handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    /**
     * Three integers.
     * <p>
     * <strong>This overload is not optional.</strong> Without it a call with three {@code long} arguments
     * resolves to {@link #send(MemorySegment, float, float, float)}, because {@code long} widens to
     * {@code float} implicitly and that overload exists - and the handle behind a selector declared with
     * {@code JAVA_LONG} then answers {@code WrongMethodTypeException} at the first frame that reaches it
     * rather than at the call that was written wrong. Measured on the Metal 4 present draw, which never ran
     * because of exactly this.
     */
    public void send(MemorySegment self, long a, long b, long c) {
        try {
            handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, float a, float b, float c) {
        try {
            handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b) {
        try {
            handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    /**
     * A pointer, a count, a pointer and a count - the shape a region copy takes.
     * <p>
     * Added when the frame probe's readback needed it, and named here for the same reason the three-integer
     * overload is: a call whose shape is missing does not always fail to compile, it resolves to whatever
     * overload the arguments widen into and fails at the first frame that reaches it.
     */
    public void send(MemorySegment self, MemorySegment a, long b, MemorySegment c, long d) {
        try {
            handle.invokeExact(self, sel, a, b, c, d);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b, long c) {
        try {
            handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a, MemorySegment b, long c) {
        try {
            handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a, long b, long c, long d, long e) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a, long b, MemorySegment c, long d, MemorySegment e, long f) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e, f);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, long a, long b, long c, MemorySegment d, long e, long f, long g, long h) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e, f, g, h);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b, MemorySegment c, long d, long e) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b, long c, long d, MemorySegment e, MemorySegment f, long g, long h, MemorySegment i) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e, f, g, h, i);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b, long c, MemorySegment d, MemorySegment e, MemorySegment f, long g, long h, MemorySegment i) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e, f, g, h, i);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, MemorySegment a, long b, long c, MemorySegment d, MemorySegment e, MemorySegment f, long g, long h, long i) {
        try {
            handle.invokeExact(self, sel, a, b, c, d, e, f, g, h, i);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, float a) {
        try {
            handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, boolean a) {
        try {
            handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, MemorySegment a) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, MemorySegment a, MemorySegment b) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, MemorySegment a, MemorySegment b, MemorySegment c) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, long a) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public long sendLong(MemorySegment self) {
        try {
            return (long) handle.invokeExact(self, sel);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public long sendLong(MemorySegment self, MemorySegment a) {
        try {
            return (long) handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public long sendLong(MemorySegment self, long a) {
        try {
            return (long) handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public long sendLong(MemorySegment self, long a, long b) {
        try {
            return (long) handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public double sendDouble(MemorySegment self) {
        try {
            return (double) handle.invokeExact(self, sel);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, double a) {
        try {
            handle.invokeExact(self, sel, a);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, double a, double b) {
        try {
            handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public void send(MemorySegment self, double a, double b, double c, double d) {
        try {
            handle.invokeExact(self, sel, a, b, c, d);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, MemorySegment a, long b, long c) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b, c);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, long a, long b, long c, long d) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b, c, d);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, long a, long b, long c, long d, long e, long f) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b, c, d, e, f);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    public MemorySegment sendPtr(MemorySegment self, long a, long b) {
        try {
            return (MemorySegment) handle.invokeExact(self, sel, a, b);
        } catch (Throwable throwable) {
            throw fail(throwable);
        }
    }

    private RuntimeException fail(Throwable throwable) {
        return new IllegalStateException("objc_msgSend failed: " + name, throwable);
    }
}
