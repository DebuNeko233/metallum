package com.metallum.render.shared;

/**
 * Where one argument buffer sits and how big it is, in the terms both generations share.
 * <p>
 * What an argument buffer <em>is</em> belongs to a generation - on Metal 3 it is a buffer an
 * {@code MTLArgumentEncoder} writes, and Metal 4's tables replace it with slots - but where it lands and
 * how much room it needs are facts about the pipeline's own layout: which stages read it, which descriptor
 * set of the pack it comes from, which buffer slot the compiled shader reads it at, and its encoded length.
 * Those four are what a cache key, a validation and a diagnostic can all be written against without
 * knowing which command API will carry it.
 *
 * @param stageMask     which stages read this argument buffer
 * @param descriptorSet which of the pack's descriptor sets it stands for
 * @param bufferIndex   the buffer slot the compiled shader reads it at
 * @param encodedLength the length the encoder wants, before any padding to the platform's alignment
 */
public record MetalArgumentBufferLayout(
        int stageMask,
        int descriptorSet,
        int bufferIndex,
        long encodedLength
) {
}
