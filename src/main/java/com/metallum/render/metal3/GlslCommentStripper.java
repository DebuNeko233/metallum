package com.metallum.render.metal3;

/**
 * Removes GLSL comments without changing the source's line structure or joining tokens that were
 * separated by a comment.
 * <p>
 * Comment openers overlap: {@code //*} is a line comment, not the start of a block comment at its
 * second slash. Shader packs pair that spelling with a line-commented block closer as a convenient
 * switch around blocks of source. Running independent block- and line-comment regular expressions
 * loses that lexical ordering and can leave the first slash behind as live GLSL. One left-to-right
 * scan keeps the same first-token-wins rule as the language.
 */
final class GlslCommentStripper {
    private GlslCommentStripper() {
    }

    static String strip(final String source) {
        StringBuilder stripped = new StringBuilder(source.length());
        int index = 0;
        while (index < source.length()) {
            char c = source.charAt(index);
            if (c == '/' && index + 1 < source.length()) {
                char next = source.charAt(index + 1);
                if (next == '/') {
                    index = stripLineComment(source, index, stripped);
                    continue;
                }
                if (next == '*') {
                    int close = source.indexOf("*/", index + 2);
                    if (close < 0) {
                        // Keep malformed source malformed so the compiler still reports the real
                        // unterminated-comment error instead of silently accepting a different unit.
                        stripped.append(source, index, source.length());
                        break;
                    }
                    index = stripBlockComment(source, index, close + 2, stripped);
                    continue;
                }
            }

            stripped.append(c);
            index++;
        }
        return stripped.toString();
    }

    private static int stripLineComment(final String source, int index, final StringBuilder stripped) {
        stripped.append("  ");
        index += 2;
        while (index < source.length()) {
            char c = source.charAt(index);
            if (c == '\n' || c == '\r') {
                // A backslash-newline is removed before comments are recognised. Preserve the
                // physical break for diagnostics, but keep consuming the same logical comment.
                if (index > 0 && source.charAt(index - 1) == '\\') {
                    index = appendLineBreak(source, index, stripped);
                    continue;
                }
                return index;
            }
            stripped.append(' ');
            index++;
        }
        return index;
    }

    private static int stripBlockComment(
            final String source,
            int index,
            final int end,
            final StringBuilder stripped
    ) {
        while (index < end) {
            char c = source.charAt(index);
            if (c == '\n' || c == '\r') {
                index = appendLineBreak(source, index, stripped);
            } else {
                stripped.append(' ');
                index++;
            }
        }
        return index;
    }

    private static int appendLineBreak(final String source, int index, final StringBuilder stripped) {
        char c = source.charAt(index);
        stripped.append(c);
        index++;
        if (c == '\r' && index < source.length() && source.charAt(index) == '\n') {
            stripped.append('\n');
            index++;
        }
        return index;
    }
}
