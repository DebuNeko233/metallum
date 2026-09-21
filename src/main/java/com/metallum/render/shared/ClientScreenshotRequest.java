package com.metallum.render.shared;

import com.metallum.Metallum;

import com.mojang.blaze3d.pipeline.RenderTarget;
import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * The client's own picture of its frame, taken from the framebuffer when a file asks for one.
 * <p>
 * <strong>Why this exists rather than a screenshot of the display.</strong> The performance harness photographing
 * the screen is photographing the display server's output: whatever window is in front, whatever Space is current
 * and whatever the display is doing. Measured, that is not a hypothetical - a locked or asleep screen captures as
 * one flat colour, and two arms of one session were compared on two pictures of nothing with the comparison
 * printing its strongest verdict, "0.00 per cent of pixels differ"; a non-exclusive fullscreen client lives in a
 * Space of its own, and all four arms of one session photographed the browser instead. The game can read its own
 * framebuffer without any of that, through the very call its own F2 key uses, and that is what this asks for.
 * <p>
 * <strong>It is a request and not a schedule, because the moment wanted is the harness's.</strong> A file in the
 * instance's {@code metallum} directory is the question and a PNG beside it is the answer: the harness writes the
 * request while the frame probe's window is open and reads the picture afterwards, which is the only way the
 * picture is the frame the numbers describe. A tick schedule cannot express that - the load takes eight to fifteen
 * seconds, so the tick a window opens at moves by hundreds between sessions.
 * <p>
 * <strong>Off unless asked for</strong>: {@code -Dmetallum.clientScreenshot=true}, and with it unset the tick
 * handler is one field read and returns. The road is the game's own: {@link Screenshot#takeScreenshot} copies the
 * main render target's colour texture into a buffer and hands the image to a consumer, so nothing here knows
 * anything about Metal or about the frame path - it is one client tick's worth of bookkeeping around a public
 * client call.
 */
public final class ClientScreenshotRequest {

    /** Whether a launch asked for this at all. Read once, as every property in this package is. */
    private static final boolean ENABLED = Boolean.getBoolean("metallum.clientScreenshot");

    /** The file whose presence is the question. Beside the frame probe's marker, in the instance's own directory. */
    private static final String REQUEST = "screenshot-request";

    /** The file written is the answer, and its name is fixed so that a harness can wait for it rather than glob. */
    private static final String ANSWER = "client-screenshot.png";

    /** Counted so that a request answered once cannot be answered again while its own file is being written. */
    private static int taken;

    private ClientScreenshotRequest() {
    }

    /** Whether a launch turned this on. The tick handler asks before it does anything else. */
    public static boolean enabled() {
        return ENABLED;
    }

    /** How many pictures this session has taken, for the harness's own line to be checkable against. */
    public static int taken() {
        return taken;
    }

    /**
     * Takes one picture if the instance holds a request for one, and does nothing otherwise.
     * <p>
     * Called once a second from a client tick rather than once a frame: the file is the question and a second is
     * far inside the window the harness counts, so the cadence costs one {@code stat} a second and nothing at all
     * on the frames between two checks.
     *
     * @return whether a picture was asked for, which the caller does not need and the log does
     */
    public static boolean takeIfAsked(final Minecraft minecraft) {
        if (!ENABLED || minecraft == null || minecraft.gameDirectory == null) {
            return false;
        }

        Path directory = minecraft.gameDirectory.toPath().resolve("metallum");
        Path request = directory.resolve(REQUEST);
        if (!Files.isRegularFile(request)) {
            return false;
        }

        Path answer = directory.resolve(ANSWER);
        // The request goes FIRST: one request is one picture, and a request that outlived its picture would be
        // answered again on the next check. Deleted rather than truncated, so a harness that is watching for the
        // answer cannot see the previous session's file and believe it.
        try {
            Files.deleteIfExists(request);
            Files.deleteIfExists(answer);
        } catch (IOException e) {
            Metallum.LOGGER.warn("client screenshot: could not clear {} - {}", request, e.toString());
            return false;
        }

        RenderTarget target = minecraft.gameRenderer.mainRenderTarget();
        if (target == null || target.getColorTexture() == null) {
            Metallum.LOGGER.warn("client screenshot: the main render target has no colour texture yet, so the"
                    + " request was dropped rather than answered with nothing");
            return false;
        }

        Metallum.LOGGER.info("client screenshot: answering a request, {}x{} of the main render target, to {}",
                target.width, target.height, answer);
        try {
            Screenshot.takeScreenshot(target, image -> write(image, answer));
        } catch (RuntimeException e) {
            // A refused readback is a finding and not a crash: the harness falls back to the display capture and
            // says which road it took, and a session that died here would lose the window it was measuring.
            Metallum.LOGGER.warn("client screenshot: the readback was refused - {}", e.toString());
            return false;
        }

        taken++;
        return true;
    }

    /**
     * Writes the image the client handed over, and says what it wrote.
     * <p>
     * The consumer arrives after the copy has been submitted and the buffer mapped, which is a frame or more after
     * the request, so this is where the picture's own size is known: the target's size at request time is a claim
     * about the frame and this is the frame.
     */
    private static void write(final NativeImage image, final Path answer) {
        try {
            Files.createDirectories(answer.getParent());
            image.writeToFile(answer);
            Metallum.LOGGER.info("client screenshot: wrote {} at {}x{}", answer, image.getWidth(), image.getHeight());
        } catch (IOException | RuntimeException e) {
            Metallum.LOGGER.warn("client screenshot: could not write {} - {}", answer, e.toString());
        } finally {
            image.close();
        }
    }
}
