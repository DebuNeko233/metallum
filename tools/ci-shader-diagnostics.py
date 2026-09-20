#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "src/main/java/com/metallum/render/MetalDevice.java"
COMPILATION = ROOT / "src/main/java/com/metallum/render/metal3/Metal3CompilationContext.java"
CROSS = ROOT / "src/main/java/com/metallum/render/shared/MetalCrossShaderTranslator.java"
# The stripper moved to the shared layer with the Metal 4 compilation chain: two generations prepare
# GLSL the same way, and neither may reach into the other's package for the helper.
STRIPPER = ROOT / "src/main/java/com/metallum/render/shared/GlslCommentStripper.java"
STRIPPER_PACKAGE = "com.metallum.render.shared"
source = COMPILATION.read_text(encoding="utf-8")
cross_source = CROSS.read_text(encoding="utf-8")

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

pad_option = "Spvc.SPVC_COMPILER_OPTION_MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS"
pad_index = cross_source.find(pad_option)
if pad_index < 0:
    raise SystemExit("Metal fragment outputs must enable SPIRV-Cross component padding")
if cross_source.count(pad_option) != 1:
    raise SystemExit("Metal fragment-output padding option must be configured exactly once")
fragment_gate = "if (executionModel == Spv.SpvExecutionModelFragment)"
gate_index = cross_source.rfind(fragment_gate, 0, pad_index)
if gate_index < 0 or pad_index - gate_index > 300:
    raise SystemExit("Metal fragment-output padding must be scoped to fragment MSL compilation")
if '"spvc_compiler_options_set_bool(MSL_PAD_FRAGMENT_OUTPUT_COMPONENTS)"' not in cross_source:
    raise SystemExit("Metal fragment-output padding must retain a named SPIRV-Cross failure stage")

harness = textwrap.dedent(
    r'''
    package com.metallum.render.shared;

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

            String splice = "float a = 1.0; // continued " + '\\' + "\n/ still comment\nfloat b = 2.0;\n";
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
    package_dir = root / STRIPPER_PACKAGE.replace(".", "/")
    package_dir.mkdir(parents=True)
    contract = package_dir / "GlslCommentStripperContract.java"
    contract.write_text(harness, encoding="utf-8")
    out = root / "out"
    subprocess.run(["javac", "-d", str(out), str(STRIPPER), str(contract)], check=True)
    subprocess.run(
        ["java", "-cp", str(out), STRIPPER_PACKAGE + ".GlslCommentStripperContract"],
        check=True,
    )

print("shader compile diagnostic/comment/fragment-output contract: PASS")
