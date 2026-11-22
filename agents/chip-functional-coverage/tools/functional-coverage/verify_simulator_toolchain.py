"""Fail the image build unless copied Verilator can compile and run real RTL."""
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    for executable in ("verilator", "make", "g++", "ccache"):
        if not shutil.which(executable):
            raise RuntimeError("missing simulator build dependency: " + executable)
    with tempfile.TemporaryDirectory(prefix="simulator-build-probe-") as temporary:
        root = Path(temporary)
        source = root / "build_probe.sv"
        source.write_text(
            "module build_probe;\n"
            "  logic a, b; wire y = a & b;\n"
            "  initial begin\n"
            "    for (int i = 0; i < 4; i++) begin\n"
            "      a = (i & 1) != 0; b = (i & 2) != 0; #1;\n"
            "      if (y !== (i == 3)) $fatal(1, \"wrong AND result\");\n"
            "    end\n"
            "    $display(\"SIMULATOR_BUILD_PROBE_PASS\"); $finish;\n"
            "  end\nendmodule\n", encoding="utf-8")
        subprocess.run([
            "verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
            "--top-module", "build_probe", "--Mdir", str(root / "obj"),
            "-o", str(root / "simulation"), str(source)],
            cwd=root, check=True, timeout=300)
        result = subprocess.run([str(root / "simulation")], cwd=root,
                                check=True, capture_output=True, text=True, timeout=30)
        if "SIMULATOR_BUILD_PROBE_PASS" not in result.stdout:
            raise RuntimeError("compiled simulator did not execute its self-check")
        print("SIMULATOR_BUILD_PROBE_PASS: compiled and executed four AND vectors", flush=True)


if __name__ == "__main__":
    main()