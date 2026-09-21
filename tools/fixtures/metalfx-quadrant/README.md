# metalfx-quadrant - the MetalFX spatial scaler's orientation, read off a live frame

A one-pass pack whose only program paints four quadrants: **top left red (alpha 1.0), top right green (0.75),
bottom left blue (0.5), bottom right yellow (0.25)**. Both axes are split at their middle and every quadrant has
its own colour *and* its own alpha, so a scaler that flips an axis, crops the image, swaps a channel or drops
alpha cannot return the arrangement unchanged - and a symmetric pattern could come back wrong and still look
right.

The pack is run at a render scale below 100 (`--renderscale 55`), which is what puts Vitrail's MetalFX spatial
scaler on the path: the input is then 704x396 for a 3200x1800 target, so the input and the output resolutions
differ and the 1:1 path is not what is being measured. `-Dmetallum.drawableReadback=true` copies the presented
drawable into a shared buffer, and `DrawableReadback` prints a five by five grid of samples with the top row
first plus the mean of each channel - the same reading on both generations, so a difference between the arms is
a difference in the frame and not in the formatting.

What the fixture is for is section 124's remaining item: the scaler's *live-frame* orientation. The probe's own
`canScaleWithMetalFx` proves the scaler on a fixed image in a process with no window; this proves the arrangement
of a frame the client drew and presented.
