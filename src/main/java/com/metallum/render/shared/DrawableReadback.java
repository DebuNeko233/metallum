package com.metallum.render.shared;

import com.metallum.Metallum;
import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;

import java.lang.foreign.MemorySegment;

import static java.lang.foreign.ValueLayout.JAVA_BYTE;

/**
 * What a present road read and what it wrote, in one place for both generations.
 * <p>
 * The display cannot be photographed on this machine and its own screenshot key cannot be pressed, so the only
 * road to the picture is the drawable itself: the layer is built with {@code framebufferOnly} off
 * ({@code -Dmetallum.drawableReadback=true}), each generation copies the drawable it presented into a shared
 * buffer, and the buffer is read once that submission is known complete. What the two arms must not differ in is
 * how the pixels are read and said - a comparison whose two sides formatted differently would be comparing the
 * formatting - so the reading lives here, in the neutral layer, and each generation only has to produce the
 * buffer.
 * <p>
 * Two halves are read through here and each is labelled: the <em>drawable</em>, which is what left the process,
 * and the <em>picture</em>, which is what the present triangle read. A reading that has only the drawable cannot
 * tell a picture that was wrong from a present that changed it, and that is exactly the question two present
 * roads disagreeing about one frame turns into.
 * <p>
 * The layer's format is BGRA8, so the bytes are blue, green, red, alpha and every message says them in that
 * order. What is printed is deliberately structural: a five by five grid of samples with the top row first -
 * which is what an orientation or a flat colour can be read from - and the mean of each channel over a sparse
 * grid of the whole surface, which is what a black drawable, a wrong colour or a wrong scale can be read from.
 */
@Environment(EnvType.CLIENT)
public final class DrawableReadback {

    /** How many samples across and down the grid: five by five, corners included. */
    private static final int GRID = 5;
    /** The stride the whole-surface mean is taken at, in pixels: every sixteenth in both directions. */
    private static final long MEAN_STRIDE = 16L;

    private DrawableReadback() {
    }

    /**
     * Reads a copied drawable and says what it holds.
     *
     * @param which       which arm read it, so a comparison's two lines are told apart in one log
     * @param width       the drawable's width in pixels
     * @param height      the drawable's height in pixels
     * @param pixels      the buffer the drawable was copied into, top row first
     * @param bytesPerRow the row stride the copy was given
     */
    public static void report(final String which, final long width, final long height, final MemorySegment pixels,
                              final long bytesPerRow) {
        read("drawable", which, width, height, pixels, bytesPerRow);
    }

    /**
     * Reads a copied picture - the texture a present triangle sampled - and says what it holds, in the same
     * shape as the drawable's line.
     *
     * @param which       which arm read it, so one run's two halves are told apart in one log
     * @param width       the picture's width in pixels
     * @param height      the picture's height in pixels
     * @param pixels      the buffer the picture was copied into, top row first
     * @param bytesPerRow the row stride the copy was given
     */
    public static void reportPicture(final String which, final long width, final long height,
                                     final MemorySegment pixels, final long bytesPerRow) {
        read("picture", which, width, height, pixels, bytesPerRow);
    }

    private static void read(final String what, final String which, final long width, final long height,
                             final MemorySegment pixels, final long bytesPerRow) {
        if (width <= 0L || height <= 0L || pixels == null) {
            return;
        }

        StringBuilder grid = new StringBuilder();
        for (int row = 0; row < GRID; row++) {
            long y = Math.min(height - 1L, row * (height - 1L) / (GRID - 1L));
            if (row > 0) {
                grid.append(' ');
            }
            for (int column = 0; column < GRID; column++) {
                long x = Math.min(width - 1L, column * (width - 1L) / (GRID - 1L));
                long at = y * bytesPerRow + x * 4L;
                if (column > 0) {
                    grid.append(',');
                }
                grid.append(String.format("%02x%02x%02x%02x",
                        pixels.get(JAVA_BYTE, at + 3L) & 0xFF,
                        pixels.get(JAVA_BYTE, at + 2L) & 0xFF,
                        pixels.get(JAVA_BYTE, at + 1L) & 0xFF,
                        pixels.get(JAVA_BYTE, at) & 0xFF));
            }
        }

        long[] mean = new long[4];
        long counted = 0L;
        for (long y = 0L; y < height; y += MEAN_STRIDE) {
            for (long x = 0L; x < width; x += MEAN_STRIDE) {
                long at = y * bytesPerRow + x * 4L;
                mean[0] += pixels.get(JAVA_BYTE, at) & 0xFF;
                mean[1] += pixels.get(JAVA_BYTE, at + 1L) & 0xFF;
                mean[2] += pixels.get(JAVA_BYTE, at + 2L) & 0xFF;
                mean[3] += pixels.get(JAVA_BYTE, at + 3L) & 0xFF;
                counted++;
            }
        }
        if (counted == 0L) {
            counted = 1L;
        }
        Metallum.LOGGER.info("{} readback [{}]: {}x{} ARGB rows(top first)=[{}] meanBGRA=({}, {}, {}, {})"
                        + " over {} samples",
                what, which, width, height, grid, mean[0] / counted, mean[1] / counted, mean[2] / counted,
                mean[3] / counted, counted);
    }

    /** How many bytes a row of a drawable of this width needs, rounded up the way Metal asks. */
    public static long bytesPerRow(final long width) {
        return ((width * 4L + 255L) / 256L) * 256L;
    }
}
