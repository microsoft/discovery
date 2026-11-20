#!/usr/bin/env python3
"""Fail the image build unless required Yosys DFT primitives execute."""

import copy
import json
import pathlib
import subprocess
import tempfile


COMMAND_OPTIONS = {
    "dfflibmap": ["-prepare", "-map-only", "-info"],
    "sat": [
        "-seq",
        "-set-at",
        "-set-init-undef",
        "-enable_undef",
        "-max_undef",
        "-dump_vcd",
        "-timeout",
    ],
    "sim": ["-clock", "-reset", "-resetn", "-rstlen", "-vcd", "-n"],
    "equiv_status": ["-assert"],
    "miter": ["-equiv", "-flatten"],
}


def _run(command, cwd=None):
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if process.returncode:
        raise SystemExit(
            "command failed: %s\n%s"
            % (" ".join(command), process.stdout + process.stderr)
        )
    return process.stdout + process.stderr


def _run_expect_failure(command, cwd=None):
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if process.returncode == 0:
        raise SystemExit(
            "command unexpectedly passed: %s\n%s"
            % (" ".join(command), process.stdout + process.stderr)
        )
    return process.stdout + process.stderr


def _validate_scan_result(result, output):
    evidence = result.get("signoff_evidence") or {}
    equivalence = evidence.get("functional_equivalence") or {}
    report = output / "scan_equivalence.log"
    if (
        result.get("status") != "completed"
        or (result.get("validation") or {}).get("verdict") != "pass"
    ):
        raise SystemExit(
            "real scan_insert scenario did not pass:\n"
            + json.dumps(result, indent=2, default=str)
        )
    if not equivalence.get("proven") or equivalence.get("verdict") != "pass":
        raise SystemExit("scan_insert emitted no passing equivalence record")
    if equivalence.get("positive_proof_check_work_count", 0) <= 0:
        raise SystemExit("scan_insert equivalence record has no proof/check work")
    if (
        equivalence.get("equiv_simple_executions", 0) <= 0
        or equivalence.get("equiv_status_executions", 0) <= 0
    ):
        raise SystemExit("scan_insert did not execute both equivalence passes")
    if not report.is_file() or report.stat().st_size <= 0:
        raise SystemExit("scan_insert emitted no non-empty scan_equivalence.log")
    if equivalence.get("report_bytes") != report.stat().st_size:
        raise SystemExit("scan_insert equivalence log size is not reconciled")


def _write_scan_probe(root):
    liberty = root / "scan_cells.lib"
    liberty.write_text(
        """library(test) {
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  current_unit : "1mA";
  pulling_resistance_unit : "1kohm";
  capacitive_load_unit (1,pf);
  leakage_power_unit : "1nW";
  cell (plain_ff) {
    area : 1;
    ff (IQ, IQN) { clocked_on : "CLK"; next_state : "D"; }
    pin (CLK) { direction : input; clock : true; }
    pin (D) { direction : input; }
    pin (Q) { direction : output; function : "IQ"; }
  }
  cell (scan_ff) {
    area : 1;
    ff (IQ, IQN) { clocked_on : "CLK"; next_state : "SCE ? SCD : D"; }
    pin (CLK) { direction : input; clock : true; }
    pin (D) { direction : input; }
    pin (SCD) { direction : input; }
    pin (SCE) { direction : input; }
    pin (Q) { direction : output; function : "IQ"; }
  }
}
""",
        encoding="utf-8",
    )
    netlist = root / "mapped.v"
    netlist.write_text(
        "module probe(input clk, input d, input scan_en, input scan_in, "
        "output q, output scan_out);\n"
        "  wire state;\n"
        "  plain_ff u_ff(.CLK(clk), .D(d), .Q(state));\n"
        "  assign q = state ^ d;\n"
        "endmodule\n",
        encoding="utf-8",
    )
    return liberty, netlist


def _run_real_scan_probe(root):
    import dft_utils

    liberty, netlist = _write_scan_probe(root)
    output = root / "scan-output"
    work = root / "scan-work"
    dft_utils.quick_setup(str(output), str(work))
    result = dft_utils.dispatch(
        {
            "scenario": "scan_insert",
            "top": "probe",
            "netlist": str(netlist),
            "liberty": str(liberty),
            "scan_chains": 1,
            "max_chain_length": 1,
            "scan_in_port": "scan_in",
            "scan_enable_port": "scan_en",
            "scan_out_port": "scan_out",
            "equivalence_depth": 4,
            "scan_cell_mappings": [
                {
                    "from_cell": "plain_ff",
                    "to_cell": "scan_ff",
                    "scan_data_pin": "SCD",
                    "scan_enable_pin": "SCE",
                    "q_pin": "Q",
                }
            ],
            "pdk_binding": {"pdk": "synthetic-capability-probe"},
        }
    )
    _validate_scan_result(result, output)

    pre_scan = json.loads((work / "pre_scan.json").read_text(encoding="utf-8"))
    post_scan = json.loads((work / "post_scan.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(post_scan)
    broken_top = broken["modules"]["probe"]
    broken_top["ports"]["q"]["bits"] = ["0"]
    if "q" in broken_top.get("netnames", {}):
        broken_top["netnames"]["q"]["bits"] = ["0"]
    negative_output = root / "negative-output"
    negative_work = root / "negative-work"
    dft_utils.quick_setup(str(negative_output), str(negative_work))
    negative = dft_utils._prove_scan_functional_equivalence(
        pre_scan,
        broken,
        "probe",
        [
            {
                "from_cell": "plain_ff",
                "to_cell": "scan_ff",
                "scan_data_pin": "SCD",
                "scan_enable_pin": "SCE",
                "q_pin": "Q",
            }
        ],
        ["scan_en", "scan_in", "scan_out"],
        depth=4,
    )
    if negative.get("proven") or negative.get("verdict") != "fail":
        raise SystemExit("deliberately altered scan logic passed equivalence")
    if negative.get("positive_proof_check_work_count", 0) <= 0:
        raise SystemExit("negative equivalence probe executed no proof/check work")


def main():
    missing = []
    for command, options in COMMAND_OPTIONS.items():
        output = _run(["yosys", "-Q", "-T", "-p", "help %s" % command])
        if "No such command" in output or "No help message" in output:
            missing.append(command)
            continue
        missing.extend(
            "%s %s" % (command, option) for option in options if option not in output
        )
    if missing:
        raise SystemExit("missing required DFT capabilities: " + ", ".join(missing))

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "comb.v").write_text(
            "module comb(input a,b,output y); assign y=a^b; endmodule\n",
            encoding="utf-8",
        )
        sat = _run(
            [
                "yosys",
                "-p",
                "read_verilog comb.v; prep -top comb; sat -set y 1 -show-inputs",
            ],
            cwd=root,
        )
        if "model found" not in sat.lower():
            raise SystemExit("SAT capability probe produced no model")

        (root / "equiv.v").write_text(
            "module gold(input a,output y); assign y=a; endmodule\n"
            "module gate(input a,output y); assign y=a; endmodule\n",
            encoding="utf-8",
        )
        _run(
            [
                "yosys",
                "-p",
                "read_verilog equiv.v; equiv_make gold gate equiv; "
                "prep -top equiv; equiv_simple; equiv_status -assert",
            ],
            cwd=root,
        )
        (root / "equiv_bad.v").write_text(
            "module gold(input a,output y); assign y=a; endmodule\n"
            "module gate(input a,output y); assign y=~a; endmodule\n",
            encoding="utf-8",
        )
        _run_expect_failure(
            [
                "yosys",
                "-p",
                "read_verilog equiv_bad.v; equiv_make gold gate equiv; "
                "prep -top equiv; equiv_simple; equiv_status -assert",
            ],
            cwd=root,
        )

        (root / "shift.v").write_text(
            "module shift(input clk,output reg q=0); "
            "always @(posedge clk) q<=~q; endmodule\n",
            encoding="utf-8",
        )
        _run(
            [
                "yosys",
                "-p",
                "read_verilog shift.v; prep -top shift; "
                "sim -clock clk -n 3 -vcd sim.vcd",
            ],
            cwd=root,
        )
        if not (root / "sim.vcd").is_file():
            raise SystemExit("simulation capability probe emitted no VCD")

        (root / "cells.lib").write_text(
            """library(test) {
    cell(BUF) {
        area : 1;
        pin(A) { direction : input; }
        pin(Y) { direction : output; function : \"A\"; }
    }
    cell(NO_FUNCTION) {
        pin(A) { direction : input; }
        pin(Y) { direction : output; }
    }
}
""",
            encoding="utf-8",
        )
        (root / "mapped.v").write_text(
            "module mapped(input a, output y); BUF u(.A(a), .Y(y)); endmodule\n",
            encoding="utf-8",
        )
        _run(
            [
                "yosys",
                "-p",
                "read_liberty -ignore_miss_func -ignore_miss_data_latch cells.lib; "
                "read_verilog mapped.v; hierarchy -check -top mapped; flatten; "
                "techmap; opt; check -assert",
            ],
            cwd=root,
        )

        _run_real_scan_probe(root)

        print("DFT_CAPABILITY PASS")


if __name__ == "__main__":
    main()
