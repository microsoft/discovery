import unittest

from pad_connectivity_preflight import check_pad_connectivity


class PadConnectivityPreflightTests(unittest.TestCase):
    def test_functional_padframe_passes_when_signal_pin_is_connected(self):
        netlist = """
        module top(input a, output y);
          wire y_net;
          assign y_net = a;
          sky130_ef_io__gpiov2_pad u_pad(.PAD(y_net), .A_ESD_0_H(1'b0));
        endmodule
        """
        result = check_pad_connectivity({
            "io_boundary": {"mode": "functional_padframe"},
            "netlist_text": netlist,
            "outputs": ["y"],
            "signal_pads": [{"instance": "u_pad", "signal_pin": "PAD", "net": "y_net"}],
        })
        self.assertEqual(result["validation"]["verdict"], "pass")
        self.assertEqual(result["results"]["functional_signal_pad_count"]["value"], 1)

    def test_dangling_pad_fails(self):
        netlist = "sky130_ef_io__gpiov2_pad u_pad(.PAD(), .A_ESD_0_H(1'b0));"
        result = check_pad_connectivity({
            "io_boundary": {"mode": "functional_padframe"},
            "netlist_text": netlist,
            "signal_pads": [{"instance": "u_pad", "signal_pin": "PAD", "net": "y_net"}],
        })
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertEqual(result["findings"][0]["code"], "DANGLING_SIGNAL_PAD")

    def test_missing_pad_fails_closed(self):
        result = check_pad_connectivity({
            "io_boundary": {"mode": "functional_padframe"},
            "netlist_text": "module top(output y); endmodule",
            "signal_pads": [{"instance": "u_pad", "signal_pin": "PAD", "net": "y_net"}],
        })
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertEqual(result["findings"][0]["code"], "MISSING_PAD_INSTANCE")

    def test_missing_contract_fails_closed(self):
        result = check_pad_connectivity({
            "io_boundary": {"mode": "functional_padframe"},
            "netlist_text": "module top(output y); endmodule",
        })
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertEqual(result["findings"][0]["code"], "MISSING_SIGNAL_PAD_CONTRACT")


if __name__ == "__main__":
    unittest.main()
