#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "src/main/java/com/metallum/render/MetalDevice.java"
STRIPPER = ROOT / "src/main/java/com/metallum/render/GlslCommentStripper.java"
source = DEVICE.read_text(encoding="utf-8")

required = (
    'Pattern.compile("\\\\b\\\\d+:(\\\\d+):")',
    "shaderCompileFailure(k.id(), sourceWithDefines, e)",
    'new StringBuilder("GLSL source around line ")',
    'line == failingLine ? ">> " : "   "',
    'String.format(Locale.ROOT, "%5d | %s", line, lines[line - 1])',
    "GlslCommentStripper.strip(source).stripLeading()",
)
missing = [needle for needle in required if needle not in source]
if missing:
    raise SystemExit("shader compile diagnostic contract missing: " + ", ".join(missing))

if 'new IllegalStateException(shaderCompileFailure(k.id(), sourceWithDefines, e), e)' not in source:
    raise SystemExit("shader compile diagnostics must preserve ShaderCompileException as the cause")
if "BLOCK_COMMENTS" in source or "LINE_COMMENTS" in source:
    raise SystemExit("shader preparation must not use independent block/line comment regexes")

harness = textwrap.dedent(
    r'''
    package com.metallum.render;

    public final class GlslCommentStripperContract {
        public static void main(String[] args) {
            String toggle = "//*\nfloat active = 1.0;\n//*/\n";
            String toggleOut = stripSameLines("toggle-active", toggle);
            require("toggle-active", toggleOut.contains("float active = 1.0;"));
            require("toggle-active", toggleOut.lines().noneMatch(line -> line.strip().equals("/")));

            String disabled = "/*\nfloat hidden = 1.0;\n//*/\nfloat active = 2.0;\n";
            String disabledOut = stripSameLines("toggle-disabled", disabled);
            require("toggle-disabled", !disabledOut.contains("float hidden"));
            require("toggle-disabled", disabledOut.contains("float active = 2.0;"));

            String lineWithBlockText = "float a = 1.0; // mention /* without close\nfloat b = 2.0;\n";
            String lineWithBlockTextOut = stripSameLines("line-block-text", lineWithBlockText);
            require("line-block-text", lineWithBlockTextOut.contains("float a = 1.0;"));
            require("line-block-text", lineWithBlockTextOut.contains("float b = 2.0;"));
            require("line-block-text", !lineWithBlockTextOut.contains("mention"));

            String blockWithLineText = "float a = 1.0; /* // text */ float b = 2.0;\n";
            String blockWithLineTextOut = stripSameLines("block-line-text", blockWithLineText);
            require("block-line-text", blockWithLineTextOut.contains("float a = 1.0;"));
            require("block-line-text", blockWithLineTextOut.contains("float b = 2.0;"));
            require("block-line-text", !blockWithLineTextOut.contains("text"));

            String splice = "float a = 1.0; // continued \\\n/ still comment\nfloat b = 2.0;\n";
            String spliceOut = stripSameLines("splice", splice);
            require("splice", !spliceOut.contains("still comment"));
            require("splice", spliceOut.contains("float b = 2.0;"));
            require("splice", spliceOut.lines().noneMatch(line -> line.strip().equals("/")));

            checkExact("division", "float c = a / b;\n", "float c = a / b;\n");
            String separation = GlslCommentStripper.strip("int value = a/**/b;\n");
            require("token-separation", separation.matches("(?s).*a\\s+b;.*"));

            String unterminated = "float a; /* keep compiler error";
            checkExact("unterminated", unterminated, unterminated);
        }

        private static String stripSameLines(String label, String source) {
            String actual = GlslCommentStripper.strip(source);
            long before = source.chars().filter(c -> c == '\n').count();
            long after = actual.chars().filter(c -> c == '\n').count();
            if (before != after) {
                throw new AssertionError(label + ": line count changed from " + before + " to " + after);
            }
            return actual;
        }

        private static void checkExact(String label, String source, String expected) {
            String actual = GlslCommentStripper.strip(source);
            if (!expected.equals(actual)) {
                throw new AssertionError(label + " expected [" + expected + "] but got [" + actual + "]");
            }
        }

        private static void require(String label, boolean condition) {
            if (!condition) {
                throw new AssertionError(label);
            }
        }
    }
    '''
).strip() + "\n"

with tempfile.TemporaryDirectory(prefix="metallum-shader-comments-") as tmp:
    root = Path(tmp)
    package_dir = root / "com/metallum/render"
    package_dir.mkdir(parents=True)
    contract = package_dir / "GlslCommentStripperContract.java"
    contract.write_text(harness, encoding="utf-8")
    out = root / "out"
    subprocess.run(["javac", "-d", str(out), str(STRIPPER), str(contract)], check=True)
    subprocess.run(
        ["java", "-cp", str(out), "com.metallum.render.GlslCommentStripperContract"],
        check=True,
    )

print("shader compile diagnostic/comment contract: PASS")
