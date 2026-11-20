#!/usr/bin/env python3
"""Fail the image build unless deployed multi-domain formal modes execute."""
import pathlib
import subprocess
import tempfile


def _run(config, sources, expected):
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        for name, text in sources.items():
            (root / name).write_text(text, encoding="utf-8")
        path = root / "check.sby"
        path.write_text(config, encoding="utf-8")
        process = subprocess.run(
            ["sby", "-f", str(path)], cwd=root, capture_output=True, text=True)
        output = process.stdout + "\n" + process.stderr
        if expected not in output:
            raise SystemExit(
                "formal capability probe did not produce %r:\n%s" %
                (expected, output[-4000:]))


def main():
    source = {"multiclock.sv": """module multiclock(input clk_a, input clk_b);
reg [2:0] binary = 0;
wire [2:0] gray = binary ^ (binary >> 1);
always @(posedge clk_a) binary <= binary + 3'b001;
reg past_valid = 0;
always @(posedge clk_a) past_valid <= 1;
`ifndef PROVE
always @(posedge clk_a) if (past_valid) begin
  gray_safe: assert ((((gray ^ $past(gray)) & ((gray ^ $past(gray)) - 1)) == 0));
  gray_active: cover (gray != $past(gray));
end
`else
always @(*) gray_definition: assert (gray == (binary ^ (binary >> 1)));
`endif
always @(posedge clk_b) assert (1'b1);
endmodule
"""}
    for mode in ("bmc", "prove", "cover"):
        define = " -DPROVE" if mode == "prove" else ""
        config = """[options]
mode %s
depth 12
multiclock on

[engines]
smtbmc z3

[script]
read_verilog -sv -formal%s multiclock.sv
prep -top multiclock

[files]
multiclock.sv
""" % (mode, define)
        _run(config, source, "DONE (PASS")

    live_source = {"live.sv": """module live(input clk, input req);
reg ack = 0;
always @(posedge clk) ack <= req;
wire ready = 1'b1;
always @(posedge clk) begin
  assume property (s_eventually ready);
  if (req) assert property (s_eventually ack);
end
endmodule
"""}
    live_config = """[options]
mode live
timeout 30

[engines]
aiger suprove

[script]
read_verilog -sv -formal live.sv
prep -top live

[files]
live.sv
"""
    _run(live_config, live_source, "DONE (PASS")
    print("CDC_FORMAL_CAPABILITY PASS")


if __name__ == "__main__":
    main()
