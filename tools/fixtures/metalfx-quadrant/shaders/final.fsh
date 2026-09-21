#version 120

/*
 * Four quadrants of four different colours and four different alphas, split at the middle of both axes.
 *
 * The pattern is the fixture's whole point: a scaler that flips an axis, crops, or swaps a channel cannot
 * return this arrangement unchanged, and a symmetric pattern (a flat colour, a gradient, two halves) can come
 * back wrong and look right. The alphas differ per quadrant so that "alpha survived the scaler" is a reading
 * and not an assumption - the four values are 1.0, 0.75, 0.5 and 0.25.
 *
 * Which corner is which is decided in the same space the engine's own present triangle reads, so the expected
 * arrangement in the presented frame is fixed by this file and the comparison is between the two generations
 * and not between a shader and a guess.
 */

varying vec2 texcoord;

void main() {
    bool right = texcoord.x > 0.5;
    bool top = texcoord.y > 0.5;
    vec4 colour;
    if (!right && !top) {
        colour = vec4(0.0, 0.0, 1.0, 0.50);   /* bottom left: blue */
    } else if (right && !top) {
        colour = vec4(1.0, 1.0, 0.0, 0.25);   /* bottom right: yellow */
    } else if (!right && top) {
        colour = vec4(1.0, 0.0, 0.0, 1.00);   /* top left: red */
    } else {
        colour = vec4(0.0, 1.0, 0.0, 0.75);   /* top right: green */
    }
    gl_FragColor = colour;
}
