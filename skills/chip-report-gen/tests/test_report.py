import contextlib
from html.parser import HTMLParser
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import unquote
import xml.etree.ElementTree as ET


SKILL = Path(__file__).resolve().parents[1]
PROJECT = SKILL.parent.parent
if PROJECT.name == ".github":
    PROJECT = PROJECT.parent
SPEC = importlib.util.spec_from_file_location("render_report", SKILL / "scripts" / "render_report.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
REAL_RUN = Path(os.environ["REPORT_GEN_REAL_RUN"]) if os.environ.get("REPORT_GEN_REAL_RUN") else None
NATIVE_RUN = Path(os.environ["REPORT_GEN_NATIVE_RUN"]) if os.environ.get("REPORT_GEN_NATIVE_RUN") else None

VCD = """$date example $end
$timescale
  10 ps
$end
$scope module tb $end
$var reg 1 ! clk $end
$var wire
  4 " count [3:0]
$end
$var reg 1 # rst_n $end
$scope module dut $end
$var wire 4 " count [3:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
bx "
0#
$end
#5
1!
b10xz "
#5
0!
#6
bz "
1#
#10
b11 "
1!
#20
"""


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.json_text = [], set(), ""
        self.in_data = False
        self.external = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs["href"])
        if "src" in attrs or (tag == "link" and "href" in attrs):
            self.external.append(attrs)
        if tag == "script" and attrs.get("id") == "wave-data":
            self.in_data = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, text):
        if self.in_data:
            self.json_text += text


def assert_icarus_records(test, run, trace):
    """Independent line-oriented comparison for the recorded Icarus fixtures."""
    expected = {key: [] for key in trace["changes"]}
    tick = 0
    for line in (run / trace["source"]).read_text().splitlines():
        line = line.strip()
        if line.startswith("#"):
            tick = int(line[1:])
        elif line.startswith("b"):
            bits, code = line[1:].split()
            if code in expected:
                width = next(s["width"] for s in trace["signals"] if s["id"] == code)
                expected[code].append([tick, bits.rjust(width, bits[0] if bits[0] in "xz" else "0")])
        elif len(line) > 1 and line[0] in "01xz" and line[1:] in expected:
            expected[line[1:]].append([tick, line[0]])
    test.assertEqual(trace["changes"], expected)


class VCDTests(unittest.TestCase):
    def test_scopes_aliases_multiline_x_z_and_same_time(self):
        trace = report.parse_vcd(VCD)
        self.assertEqual(trace["timescale"], "10ps")
        self.assertEqual(trace["end"], 20)
        self.assertEqual(len(trace["declarations"]), 4)
        self.assertEqual(trace["changes"]['"'], [[0, "xxxx"], [5, "10xz"], [6, "zzzz"], [10, "0011"]])
        self.assertEqual(trace["changes"]["!"], [[0, "0"], [5, "1"], [5, "0"], [10, "1"]])
        self.assertEqual(trace["selected_records"], 10)
        self.assertEqual(len(trace["windows"]), 2)

    def test_exact_signal_selection(self):
        trace = report.parse_vcd(VCD, ["tb.dut.count"])
        self.assertEqual([s["name"] for s in trace["signals"]], ["tb.dut.count"])
        self.assertEqual(trace["selected_records"], 4)
        for requested in (["missing"], ["tb.clk"] * 2, ["a"] * 13):
            with self.subTest(requested=requested), self.assertRaises(report.EvidenceError):
                report.parse_vcd(VCD, requested)

    def test_malformed_and_unsupported_fail_not_partial(self):
        variants = [
            "", VCD.replace("10 ps", "3ns"), VCD.replace("10 ps", ""),
            VCD.replace("#20", "#-1"), VCD.replace("#20", "#4"),
            VCD.replace("#20", f"#{2**53}"), VCD.replace("b11", "b11111"),
            VCD.replace("b11", "b102"), VCD.replace("b11 \"", "b11 undeclared"),
            VCD.replace("b11 \"", "r1.25 \""),
            VCD.replace("$var wire 4", "$var real 4"),
            VCD.replace('$var wire 4 "', '$var wire 8 "'),
            VCD.replace("$upscope $end", "", 1), VCD + "$dumpvars\n",
            VCD.replace('$var reg 1 ! clk $end', '$var reg 1 ! clk'),
            VCD + "$unknown $end",
        ]
        for text in variants:
            with self.subTest(text=text[-80:]), self.assertRaises(report.EvidenceError):
                report.parse_vcd(text)
        with self.assertRaises(report.EvidenceError):
            report.parse_vcd(VCD, max_changes=2)

    def test_dump_off_values_preserved(self):
        trace = report.parse_vcd(VCD + '#21\n$dumpoff\nx!\nbx "\n$end\n#22\n')
        self.assertEqual(trace["changes"]["!"][-1], [21, "x"])

    def test_constant_scalar_does_not_invent_vertical_edges(self):
        trace = report.parse_vcd(VCD, ["tb.rst_n"])
        trace["windows"] = [{"start": 0, "end": 5, "label": "constant reset"}]
        svg = report.static_wave(trace)
        root = ET.fromstring(svg)
        paths = root.findall("{http://www.w3.org/2000/svg}path")
        scalar = [p for p in paths if p.attrib.get("stroke") == "#5ce0c3"]
        self.assertEqual(len(scalar), 1)
        self.assertNotIn("V", scalar[0].attrib["d"])


class ReportFixture(unittest.TestCase):
    def setUp(self):
        (PROJECT / "results").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="chip-report-gen-tests-", dir=PROJECT / "results")
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "results" / "example"
        self.run.mkdir(parents=True)
        self.output = self.run.parent / "new-report" / "report.html"
        self.cde_name = "attempt-01/verify/output/common_design_envelope.json"
        self.cde = {
            "status": "completed", "stage": "funcverif",
            "validation": {"verdict": "pass"},
            "results": {"sim_passed": {"value": True, "class": "gating", "closes_at": "== true"}},
            "provenance": {"runtime": {"elapsed_seconds": 0.125}},
        }
        self.summary = {
            "run_id": "example", "status": "PASS", "initial_attempts": 1, "corrective_attempts": 0,
            "stages": [{"stage": "verify", "status": "PASS", "exit_code": 0,
                        "cde": self.cde_name, "sim_passed": True,
                        "comparisons": 5, "mismatches": 0, "final_marker": "TEST PASSED"}],
            "coverage": {"reset_edges": 2}, "limitations": ["No physical signoff"],
            "artifacts": {"waveform": "trace.vcd", "simulation_log": "vvp.log"},
        }
        self.write("results.md", "# Original results")
        self.write("trace.vcd", VCD)
        self.write("vvp.log", "COMPARISONS=5 MISMATCHES=0\nTEST PASSED\n")
        self.write("attempt-01/smoke-test.json", {
            "status": "passed", "agent_activation": "unverified",
            "stages": [{"stage": "verify", "status": "passed", "attempt": 1, "exit_code": 0}],
        })
        self.sync()

    def write(self, name, value):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

    def sync(self):
        self.write("results.json", self.summary)
        self.write(self.cde_name, self.cde)

    def render(self, **kwargs):
        return report.render(self.run, self.output, **kwargs)

    def inspect(self):
        text = self.output.read_text(encoding="utf-8")
        parsed = Inspector()
        parsed.feed(text)
        return text, parsed


class InvocationDiagramTests(ReportFixture):
    def set_dispatch(self, entries, scope="Complete parent-recorded history"):
        self.summary["artifacts"]["dispatch_record"] = "dispatch.json"
        self.write("dispatch.json", {"scope": scope, "dispatch_order": entries})
        self.sync()

    def test_full_retry_sequence_order_counts_and_final_verdict_separation(self):
        names = [
            "chip-rtl-design", "chip-rtl-design", "chip-rtl-lint",
            "chip-rtl-design", "chip-rtl-lint", "chip-functional-verification",
            "chip-rtl-design", "chip-rtl-lint", "chip-functional-verification",
        ]
        statuses = ["blocked", "pass", "fail", "pass", "pass", "fail", "pass", "pass", "pass"]
        self.set_dispatch([
            {"agent": name, "reason": f"Unique reason {i}", "outcome": f"Unique outcome {i}",
             "status": status}
            for i, (name, status) in enumerate(zip(names, statuses), 1)
        ])
        result = self.render()
        self.assertEqual(result["evidence_issues"], [])
        self.assertEqual(result["reported_status"], "PASS")
        text, parsed = self.inspect()
        self.assertIn("agent-invocations", parsed.ids)
        self.assertFalse(parsed.external)
        self.assertIn("9 recorded invocations", text)
        for expected in ("chip-rtl-design: 4", "chip-rtl-lint: 3",
                         "chip-functional-verification: 2", "not an activation audit"):
            self.assertIn(expected, text)
        diagram = text.split('<ol class="invocation-flow"', 1)[1].split("</ol>", 1)[0]
        self.assertEqual(diagram.count('class="invocation-node '), 9)
        self.assertEqual(diagram.count('class="invocation-node fail"'), 2)
        self.assertEqual(diagram.count('class="invocation-node blocked"'), 1)
        reasons = [diagram.index(f"Unique reason {i}") for i in range(1, 10)]
        self.assertEqual(reasons, sorted(reasons))
        for i in range(1, 10):
            self.assertIn(f'number">{i}</span>', diagram)
            self.assertIn(f"Unique outcome {i}", diagram)
        self.assertIn("::after", text)
        self.assertNotIn("mermaid", text.lower())

    def test_missing_fields_never_infer_pass_or_reason_from_native_stages(self):
        self.set_dispatch([{"agent": "designer", "outcome": "Everything passed",
                            "status": "completed"}, {}])
        self.assertEqual(self.render()["evidence_issues"], [])
        text, _ = self.inspect()
        diagram = text.split('<ol class="invocation-flow"', 1)[1].split("</ol>", 1)[0]
        self.assertEqual(diagram.count('class="invocation-node unknown"'), 2)
        self.assertIn("<b>Why:</b> not recorded", diagram)
        self.assertIn("<b>Outcome:</b> not recorded", diagram)
        self.assertNotIn('class="badge pass"', diagram)

    def test_legacy_aliases_and_explicit_canonical_precedence(self):
        self.set_dispatch([
            {"agent_type": "legacy", "reported_status": "blocked"},
            {"agent": "canonical", "agent_type": "ignored",
             "status": "fail", "reported_status": "pass"},
        ])
        self.assertEqual(self.render()["evidence_issues"], [])
        text, _ = self.inspect()
        diagram = text.split('<ol class="invocation-flow"', 1)[1].split("</ol>", 1)[0]
        self.assertIn("<h3>legacy</h3>", diagram)
        self.assertIn("<h3>canonical</h3>", diagram)
        self.assertNotIn("ignored", diagram)
        self.assertIn('class="invocation-node blocked"', diagram)
        self.assertIn('class="invocation-node fail"', diagram)

    def test_no_dispatch_does_not_invent_history(self):
        self.assertEqual(self.render()["evidence_issues"], [])
        text, _ = self.inspect()
        self.assertIn("No readable dispatch record supplied", text)
        self.assertNotIn('<ol class="invocation-flow"', text)

    def test_empty_dispatch_retains_visible_fallback(self):
        self.set_dispatch([])
        self.assertEqual(self.render()["evidence_issues"], [])
        text, _ = self.inspect()
        self.assertIn("No invocation sequence recorded", text)
        self.assertNotIn('<ol class="invocation-flow"', text)

    def test_malformed_fields_and_shape_are_visible(self):
        self.set_dispatch([{"agent": False, "reason": [], "outcome": {}, "status": None}])
        result = self.render()
        for field in ("agent", "reason", "outcome", "status"):
            self.assertTrue(any(f"dispatch_order[0] {field}" in item
                                for item in result["evidence_issues"]), result)
        self.output = self.output.with_name("malformed-sequence.html")
        self.set_dispatch([{"agent": "valid"}, "not an object"])
        result = self.render()
        self.assertTrue(any("dispatch_order" in item for item in result["evidence_issues"]))
        self.assertIn("No invocation sequence recorded", self.output.read_text())

    def test_diagram_text_escaped_and_static_without_scripts(self):
        payload = '</p><img src=x onerror="alert(1)"><script>bad()</script>'
        self.set_dispatch([{"agent": payload, "reason": payload, "outcome": payload,
                            "status": "pass"}], scope=payload)
        self.assertEqual(self.render()["evidence_issues"], [])
        text, parsed = self.inspect()
        self.assertNotIn(payload, text)
        self.assertFalse(parsed.external)
        self.assertIn("&lt;img", text)
        static = text.split('<script id="wave-data"', 1)[0]
        self.assertIn('<ol class="invocation-flow"', static)
        self.assertIn("<b>Why:</b>", static)
        self.assertIn("<b>Outcome:</b>", static)
        self.assertEqual(text.count("</script>"), 2)


class ReportTests(ReportFixture):
    def test_complete_output_links_and_no_overwrite(self):
        result = self.render()
        self.assertEqual(result["evidence_issues"], [])
        text, parsed = self.inspect()
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertTrue(text.rstrip().endswith("</html>"))
        self.assertNotIn("@@", text)
        self.assertFalse(parsed.external)
        self.assertIn("wave-svg", parsed.ids)
        self.assertIn("wave-controls", parsed.ids)
        self.assertEqual(json.loads(parsed.json_text)["changes"]['"'][0], [0, "xxxx"])
        for href in parsed.links:
            self.assertTrue((self.output.parent / unquote(href)).is_file(), href)
        ET.fromstring(text[text.index("<svg "):text.index("</svg>") + 6])
        before = self.output.read_bytes()
        with self.assertRaises(report.EvidenceError):
            self.render()
        self.assertEqual(self.output.read_bytes(), before)
        self.output = self.output.with_name("same-evidence.html")
        self.render()
        self.assertEqual(self.output.read_bytes(), before)

    def test_html_script_and_link_escaping(self):
        payload = '</script><img src=x onerror=alert(1)>&"'
        self.summary["run_id"] = payload
        self.summary["coverage"][payload] = 3
        self.write("results.md", payload)
        self.write("vvp.log", payload + "\nCOMPARISONS=5 MISMATCHES=0\nTEST PASSED\n")
        self.write("trace.vcd", VCD.replace("clk", "clk</script><img>"))
        self.sync()
        self.render()
        text, parsed = self.inspect()
        self.assertNotIn(payload, text)
        self.assertIn("&lt;/script&gt;", text)
        self.assertIn("\\u003c/script\\u003e", parsed.json_text)
        self.assertEqual(text.count("</script>"), 2)
        self.assertFalse(parsed.external)
        self.assertEqual(json.loads(parsed.json_text)["declarations"][0]["name"], "tb.clk</script><img>")

    def test_truthful_fail_blocked_unknown_and_completed(self):
        for source_status in ("FAIL", "BLOCKED", None, "completed"):
            with self.subTest(status=source_status):
                self.output = self.output.with_name(f"status-{source_status}.html")
                self.summary["stages"][0]["status"] = source_status
                self.cde["validation"]["verdict"] = source_status
                self.sync()
                result = self.render()
                self.assertTrue(result["evidence_issues"])
                self.assertIn(report.normalize_status(source_status), self.output.read_text())
        self.assertEqual(report.normalize_status("completed"), "UNKNOWN")
        self.assertEqual(report.normalize_status(True), "UNKNOWN")

    def test_null_false_and_nonzero_gating_never_accepted(self):
        for value in (None, False, 1, "true"):
            with self.subTest(value=value):
                self.output = self.output.with_name(f"gate-{value}.html")
                self.cde["results"]["sim_passed"]["value"] = value
                self.sync()
                self.assertTrue(any("gating" in issue for issue in self.render()["evidence_issues"]))

    def test_failed_lifecycle_and_closure_ineligible_are_not_hidden(self):
        self.cde["status"] = "blocked"
        self.sync()
        result = self.render()
        self.assertTrue(any("native verdict BLOCKED" in issue for issue in result["evidence_issues"]))
        self.output = self.output.with_name("closure.html")
        self.cde["status"] = "completed"
        self.cde["progress"] = {"gate_closed": False}
        self.sync()
        self.assertTrue(any("closure ineligibility" in issue for issue in self.render()["evidence_issues"]))

    def test_malformed_metric_and_oversize_counter_are_visible(self):
        self.cde["results"]["sim_passed"] = {}
        self.summary["stages"][0]["sim_passed"] = None
        self.summary["coverage"]["huge"] = 10**400
        self.summary["coverage"]["negative"] = -2
        self.sync()
        result = self.render()
        self.assertTrue(any("malformed metric" in issue for issue in result["evidence_issues"]))
        self.assertTrue(any("coverage.huge" in issue for issue in result["evidence_issues"]))

    def test_missing_empty_bad_vcd_has_visible_fallback(self):
        for index, content in enumerate((None, "", "#0\nr1 !")):
            self.output = self.output.with_name(f"vcd-{index}.html")
            if content is None:
                (self.run / "trace.vcd").unlink()
            else:
                self.write("trace.vcd", content)
            result = self.render()
            text, parsed = self.inspect()
            self.assertEqual(result["waveform_records"], 0)
            self.assertIn("Waveform unavailable", text)
            self.assertEqual(json.loads(parsed.json_text), None)
            self.assertTrue(result["evidence_issues"])

    def test_tick_zero_only_has_no_invented_duration(self):
        self.write("trace.vcd", VCD[:VCD.index("#5")])
        result = self.render()
        self.assertEqual(result["waveform_records"], 0)
        self.assertTrue(any("tick-zero" in issue for issue in result["evidence_issues"]))

    def test_malformed_missing_shapes_and_unknown_timing(self):
        self.write("results.json", "{bad")
        self.write(self.cde_name, {"results": [], "validation": [], "provenance": None})
        self.write("attempt-01/smoke-test.json", {"stages": None})
        result = self.render()
        self.assertTrue(result["evidence_issues"])
        self.assertIn("UNKNOWN", self.output.read_text())
        self.assertIn("No measured numeric data recorded", self.output.read_text())

    def test_readonly_and_limits(self):
        before = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        result = self.render(max_vcd_bytes=10)
        self.assertTrue(any("byte limit" in issue for issue in result["evidence_issues"]))
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.output = self.output.with_name("changes-limit.html")
        self.assertEqual(self.render(max_changes=1)["waveform_records"], 0)

    def test_forbidden_artifacts_not_linked_or_read(self):
        self.summary["artifacts"].update({"escape": "../secret", "url": "https://example.com/a",
                                          "absolute": "C:\\Windows\\win.ini"})
        self.summary["stages"][0]["cde"] = "../secret"
        self.sync()
        result = self.render()
        self.assertGreaterEqual(len(result["evidence_issues"]), 4)
        _, parsed = self.inspect()
        self.assertFalse(any("secret" in href or "example.com" in href for href in parsed.links))

    def test_log_contradiction_and_all_attempts_visible(self):
        self.write("vvp.log", "COMPARISONS=4 MISMATCHES=1\nTEST FAILED\n")
        self.write("attempt-02/smoke-test.json", {"status": "blocked", "agent_activation": "unverified",
                                                "stages": [{"stage": "verify", "status": "blocked", "attempt": 2}]})
        result = self.render()
        self.assertTrue(any("comparisons" in issue for issue in result["evidence_issues"]))
        self.assertTrue(any("failure diagnostics" in issue for issue in result["evidence_issues"]))
        self.assertIn("attempt-02/smoke-test.json", self.output.read_text())

    def test_frontmatter_exact_name_and_trigger(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: chip-report-gen\n"))
        front = text.split("---", 2)[1]
        fields = {line.split(":", 1)[0] for line in front.splitlines() if line.strip()}
        self.assertEqual(fields, {"name", "description", "license", "compatibility"})
        self.assertIn("license: MIT", front)
        self.assertEqual(SKILL.name, "chip-report-gen")
        for phrase in ("final report", "results summary", "HTML report", "chip/RTL"):
            self.assertIn(phrase, front)

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(["--run-dir", str(self.run), "--output", str(self.output)]), 0)
        self.output = self.output.with_name("issues.html")
        self.write("trace.vcd", "")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(["--run-dir", str(self.run), "--output", str(self.output)]), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main(["--run-dir", str(self.run), "--output", str(self.output)]), 1)


class RealEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(REAL_RUN and REAL_RUN.is_dir(), "REPORT_GEN_REAL_RUN not supplied")
    def test_real_schema_and_vcd_readonly(self):
        before = {p: report.hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in REAL_RUN.rglob("*") if p.is_file()}
        with tempfile.TemporaryDirectory(prefix="chip-report-gen-real-test-", dir=REAL_RUN.parent) as temp:
            output = Path(temp) / "report.html"
            result = report.render(REAL_RUN, output)
            self.assertEqual(result["evidence_issues"], [])
            self.assertEqual(result["reported_status"], "PASS")
            self.assertGreater(result["waveform_records"], 3000)
            parsed = Inspector()
            text = output.read_text()
            parsed.feed(text)
            trace = json.loads(parsed.json_text)
            self.assertEqual(trace["timescale"], "1ps")
            self.assertEqual({s["name"].split(".")[-1] for s in trace["signals"]},
                             {"clk", "rst_n", "clear", "enable", "count", "overflow"})
            self.assertTrue(any("saturation" in w["label"] for w in trace["windows"]))
            self.assertTrue(any("priority" in w["label"] for w in trace["windows"]))
            assert_icarus_records(self, REAL_RUN, trace)
            self.assertIn("2184", text)
            self.assertIn("unverified", text)
            for href in parsed.links:
                self.assertTrue((output.parent / unquote(href)).is_file(), href)
        self.assertEqual(before, {p: report.hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    @unittest.skipUnless(NATIVE_RUN and NATIVE_RUN.is_dir(), "REPORT_GEN_NATIVE_RUN not supplied")
    def test_native_ordered_real_run_readonly_and_lossless(self):
        before = {p: report.hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in NATIVE_RUN.rglob("*") if p.is_file()}
        with tempfile.TemporaryDirectory(prefix="chip-report-gen-native-real-", dir=NATIVE_RUN.parent) as temp:
            output = Path(temp) / "report.html"
            result = report.render(NATIVE_RUN, output)
            self.assertEqual(result["evidence_issues"], [])
            self.assertEqual(result["reported_status"], "PASS")
            parsed = Inspector()
            text = output.read_text(encoding="utf-8")
            parsed.feed(text)
            self.assertFalse(parsed.external)
            self.assertNotIn("@@", text)
            self.assertIn("CONSISTENT EVIDENCE", text)
            self.assertIn("recorded tool execution is not agent activation", text)
            self.assertIn("audits found: 0; explicit stage execution records: 3", text)
            trace = json.loads(parsed.json_text)
            self.assertGreater(trace["selected_records"], 0)
            assert_icarus_records(self, NATIVE_RUN, trace)
            for href in parsed.links:
                self.assertTrue((output.parent / unquote(href)).is_file(), href)
            ET.fromstring(text[text.index("<svg "):text.index("</svg>") + 6])
        self.assertEqual(before, {p: report.hashlib.sha256(p.read_bytes()).hexdigest() for p in before})


class NativeExecutionTests(ReportFixture):
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.run / "attempt-01")
        self.write("input/counter.v", "module counter; endmodule\n")
        self.digest = report.hashlib.sha256((self.run / "input/counter.v").read_bytes()).hexdigest()
        self.rtl_bytes = (self.run / "input/counter.v").stat().st_size
        self.summary = {
            "status": "pass", "execution_mode": "ordered", "rtl_sha256": self.digest,
            "coverage": {"comparisons": 5, "mismatches": 0},
            "artifacts": {"Waveform": "trace.vcd", "Simulation log": "vvp.log"},
            "stages": [],
        }
        self.native = []
        for index, (name, tool) in enumerate((
                ("design", "rtl-design"), ("lint_and_format", "rtl-lint"),
                ("simulation", "functional-verification")), 1):
            root = "" if index == 1 else f"stage{index}/"
            cde_ref = root + "output/common_design_envelope.json"
            evidence = {"invocation": root + "evidence/invocation.json",
                        "exit": root + "evidence/container-exit.txt", "rtl": root + "input/counter.v"}
            stage = {"stage": name, "status": "pass", "cde": cde_ref, "execution_evidence": evidence}
            self.summary["stages"].append(stage)
            self.write(evidence["rtl"], "module counter; endmodule\n")
            arguments = ["run", "--rm", tool + ":latest", "python3", "/app/run.py"]
            self.write(evidence["invocation"], arguments if index == 2 else {"arguments": arguments})
            self.write(evidence["exit"], "0")
            cde = {
                "status": "completed", "tool": tool, "validation": {"verdict": "pass"},
                "results": {"clean": {"value": True, "class": "gating", "closes_at": "== true"}},
                "signoff_evidence": {"native_exit_codes": {"tool": 0}},
                "provenance": {
                    "input_hashes": {"counter.v": {"sha256": self.digest, "bytes": self.rtl_bytes}},
                    "runtime": {"started_utc": f"2026-11-03T21:0{index}:00Z", "elapsed_seconds": 1},
                    "finished_utc": f"2026-11-03T21:0{index}:01Z",
                },
            }
            if index == 3:
                cde["results"] = {
                    "sim_passed": {"value": True, "class": "gating", "closes_at": "== true"},
                    "comparisons": {"value": 5, "class": "gating", "closes_at": "> 0"},
                    "mismatches": {"value": 0, "class": "gating", "closes_at": "== 0"},
                }
            self.native.append(cde)
        self.sync_native()

    def sync_native(self):
        self.write("results.json", self.summary)
        for stage, cde in zip(self.summary["stages"], self.native):
            self.write(stage["cde"], cde)

    def assert_issue(self, substring):
        result = self.render()
        self.assertTrue(any(substring in issue for issue in result["evidence_issues"]),
                        result["evidence_issues"])

    def test_native_ordered_records_without_smoke_audit(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = report.main(["--run-dir", str(self.run), "--output", str(self.output)])
        self.assertEqual(code, 0)
        text, parsed = self.inspect()
        self.assertIn("CONSISTENT EVIDENCE", text)
        self.assertIn("unverified; recorded tool execution is not agent activation", text)
        self.assertIn("audits found: 0; explicit stage execution records: 3", text)
        self.assertIn("Simulation console", text)
        self.assertEqual(json.loads(parsed.json_text)["selected_records"], 10)
        self.assertFalse(parsed.external)
        for href in parsed.links:
            self.assertTrue((self.output.parent / unquote(href)).is_file(), href)

    def test_missing_stage_execution_never_waives_audit(self):
        del self.summary["stages"][1]["execution_evidence"]
        self.sync_native()
        self.assert_issue("execution_evidence")

    def test_host_exit_must_be_integer_zero(self):
        evidence = self.summary["stages"][1]["execution_evidence"]
        for index, value in enumerate(({"exit_code": False}, {"exit_code": None},
                                       {"exit_code": "0"}, {"exit_code": 7}, {}, "bad", None)):
            with self.subTest(value=value):
                self.output = self.output.with_name(f"exit-{index}.html")
                self.write(evidence["exit"], value)
                self.assert_issue("host exit")

    def test_native_exits_are_recursive_and_strict(self):
        for index, value in enumerate(({}, {"tool": False}, {"tool": 1},
                                       {"tool": None}, {"tool": {"format": 2}})):
            with self.subTest(value=value):
                self.output = self.output.with_name(f"native-exit-{index}.html")
                self.native[1]["signoff_evidence"]["native_exit_codes"] = value
                self.sync_native()
                self.assert_issue("native_exit_codes")

    def test_invocation_is_read_not_invented(self):
        evidence = self.summary["stages"][0]["execution_evidence"]
        for index, value in enumerate(({}, [], ["rtl-lint:latest"], ["rtl-design:latest"],
                                       {"arguments": "rtl-design"},
                                       {"arguments": ["rtl-design:latest", None]})):
            with self.subTest(value=value):
                self.output = self.output.with_name(f"invocation-{index}.html")
                self.write(evidence["invocation"], value)
                self.assert_issue("invocation")

    def test_missing_files_and_escaped_paths_fail_closed(self):
        evidence = self.summary["stages"][1]["execution_evidence"]
        for index, key in enumerate(("invocation", "exit", "rtl")):
            original = evidence[key]
            for case, name in enumerate(("missing.json", "../outside.json", "C:\\outside.json")):
                with self.subTest(key=key, name=name):
                    self.output = self.output.with_name(f"missing-{index}-{case}.html")
                    evidence[key] = name
                    self.sync_native()
                    self.assertTrue(self.render()["evidence_issues"])
            evidence[key] = original

    def test_hash_must_match_native_record_and_actual_bytes(self):
        for index, value in enumerate((None, "0" * 64, "not-a-hash", True)):
            with self.subTest(value=value):
                self.output = self.output.with_name(f"hash-{index}.html")
                self.native[1]["provenance"]["input_hashes"]["counter.v"]["sha256"] = value
                self.sync_native()
                self.assert_issue("SHA256")

    def test_missing_native_hash_not_replaced_by_summary_hash(self):
        del self.native[1]["provenance"]["input_hashes"]
        self.sync_native()
        self.assert_issue("no native RTL SHA256")

    def test_explicit_null_hash_evidence_is_not_silently_skipped(self):
        self.native[1]["signoff_evidence"]["source_hashes_before"] = None
        self.native[2]["signoff_evidence"].update(rtl_sha256_before=None, rtl_sha256_after=None)
        self.sync_native()
        result = self.render()
        for phrase in ("source_hashes_before", "rtl_sha256_before", "rtl_sha256_after"):
            self.assertTrue(any(phrase in issue for issue in result["evidence_issues"]), result)

    def test_rtl_mutation_and_false_unchanged_are_detected(self):
        self.write("stage2/input/counter.v", "changed\n")
        self.native[1]["signoff_evidence"]["sources_unchanged"] = False
        self.sync_native()
        result = self.render()
        for phrase in ("SHA256 mismatch", "byte count mismatch", "sources_unchanged", "identical RTL"):
            self.assertTrue(any(phrase in issue for issue in result["evidence_issues"]), result)

    def test_handoff_before_after_hashes_supported_and_cross_checked(self):
        cde = self.native[2]
        del cde["provenance"]["input_hashes"]
        cde["signoff_evidence"].update(rtl_sha256_before=self.digest,
                                       rtl_sha256_after=self.digest, sources_unchanged=True)
        self.sync_native()
        self.assertEqual(self.render()["evidence_issues"], [])
        self.output = self.output.with_name("after-mismatch.html")
        cde["signoff_evidence"]["rtl_sha256_after"] = "0" * 64
        self.sync_native()
        self.assert_issue("rtl_sha256_after")

    def test_source_hash_maps_and_nested_exit_maps(self):
        signoff = self.native[1]["signoff_evidence"]
        signoff["native_exit_codes"] = {"lint": 0, "format": {"/input/counter.v": 0}}
        for field in ("source_hashes", "source_hashes_before", "source_hashes_after"):
            signoff[field] = {"/input/counter.v": {"sha256": self.digest, "bytes": self.rtl_bytes}}
        signoff["sources_unchanged"] = True
        self.sync_native()
        self.assertEqual(self.render()["evidence_issues"], [])
        self.output = self.output.with_name("before-mismatch.html")
        signoff["source_hashes_before"]["/input/counter.v"]["sha256"] = "0" * 64
        self.sync_native()
        self.assert_issue("source_hashes_before")

    def test_order_must_be_supported_by_native_timestamps(self):
        for index, start in enumerate((None, "bad", "2026-11-03T21:01:00",
                                       "2026-11-03T21:01:00Z", "2026-11-03T21:09:00Z")):
            with self.subTest(start=start):
                self.output = self.output.with_name(f"order-{index}.html")
                self.native[1]["provenance"]["runtime"]["started_utc"] = start
                self.sync_native()
                self.assertTrue(self.render()["evidence_issues"])

    def test_native_simulation_checks_do_not_require_summary_sim_passed(self):
        for index, log in enumerate((
                "COMPARISONS=4 MISMATCHES=0\nTEST PASSED\n",
                "COMPARISONS=5 MISMATCHES=1\nTEST PASSED\n",
                "COMPARISONS=5 MISMATCHES=0\nTEST FAILED\n",
                "COMPARISONS=5 MISMATCHES=0\nprefix TEST PASSED\n",
                "COMPARISONS=5 MISMATCHES=0\nTEST PASSED\nFATAL: late failure\n",
                "TEST PASSED\nCOMPARISONS=5 MISMATCHES=0\n",
                "COMPARISONS=5\nTEST PASSED\n",
                "COMPARISONS=0 MISMATCHES=0\nTEST PASSED\n")):
            with self.subTest(log=log):
                self.output = self.output.with_name(f"log-{index}.html")
                self.write("vvp.log", log)
                self.assertTrue(self.render()["evidence_issues"])

    def test_coverage_and_native_simulation_counters_both_cross_checked(self):
        self.summary["coverage"]["comparisons"] = 6
        self.native[2]["results"]["mismatches"]["value"] = 1
        self.sync_native()
        result = self.render()
        for phrase in ("coverage.comparisons", "native mismatches"):
            self.assertTrue(any(phrase in issue for issue in result["evidence_issues"]), result)

    def test_positive_comparison_gate_is_not_ignored(self):
        self.native[2]["results"]["comparisons"]["value"] = 0
        self.sync_native()
        self.assert_issue("gating comparisons")

    def test_conflicting_aliases_are_not_silently_preferred(self):
        self.write("other.log", "COMPARISONS=4 MISMATCHES=0\nTEST PASSED\n")
        self.summary["artifacts"]["simulation_log"] = "other.log"
        self.sync_native()
        self.assert_issue("Conflicting artifact aliases")

    def test_equivalent_aliases_to_same_file_are_allowed(self):
        self.summary["artifacts"].update(simulation_log="vvp.log", waveform="trace.vcd")
        self.sync_native()
        self.assertEqual(self.render()["evidence_issues"], [])

    def test_native_execution_does_not_hide_failed_attempt_audit(self):
        self.write("attempt-02/smoke-test.json", {"status": "failed", "stages": []})
        self.assert_issue("audit overall status=FAIL")

    def test_ordered_execution_cannot_reuse_one_envelope_for_two_stages(self):
        self.summary["stages"][1]["cde"] = self.summary["stages"][0]["cde"]
        self.write("results.json", self.summary)
        self.assert_issue("distinct nonempty cde")

    def test_alias_fix_alone_cannot_turn_missing_audit_into_exit_zero(self):
        for stage in self.summary["stages"]:
            del stage["execution_evidence"]
        self.sync_native()
        with contextlib.redirect_stdout(io.StringIO()):
            code = report.main(["--run-dir", str(self.run), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertTrue(self.output.is_file())
        text, parsed = self.inspect()
        self.assertIn("no execution evidence", text)
        self.assertIn("explicit stage execution records: 0", text)
        self.assertGreater(json.loads(parsed.json_text)["selected_records"], 0)

    def test_parent_fallback_attribution_keeps_blocked_dispatch_separate(self):
        self.summary["workflow_status"] = "partial: lint and FV agents blocked; parent executed native contracts"
        self.summary["stages"][0]["executor"] = "chip-rtl-design"
        self.summary["stages"][1]["executor"] = "parent native runner; chip-rtl-lint dispatch blocked"
        self.summary["stages"][2]["executor"] = "parent native runner; chip-functional-verification dispatch blocked"
        self.summary["artifacts"]["dispatch_record"] = "agent-dispatch.json"
        self.write("agent-dispatch.json", {
            "dispatch_order": [
                {"agent_type": "chip-rtl-lint", "reported_status": "blocked",
                 "reason": "Bookshelf-only tool access", "fallback": "parent native runner"},
                {"agent_type": "chip-functional-verification", "reported_status": "blocked",
                 "reason": "Bookshelf-only tool access", "fallback": "parent native runner"},
            ],
            "scope": "Parent-recorded dispatch results; not an agent-runtime activation audit",
        })
        self.sync_native()
        self.assertEqual(self.render()["evidence_issues"], [])
        text, parsed = self.inspect()
        self.assertIn("Workflow completion (source-reported)", text)
        self.assertIn("partial: lint and FV agents blocked", text)
        self.assertIn("Executor (source-reported): parent native runner", text)
        self.assertIn("Bookshelf-only tool access", text)
        self.assertIn("not an activation audit", text)
        self.assertIn("unverified; recorded tool execution is not agent activation", text)
        self.assertIn("agent-dispatch.json", text)
        self.assertGreater(json.loads(parsed.json_text)["selected_records"], 0)

    def test_attribution_cannot_waive_missing_native_execution(self):
        self.summary["stages"][1]["executor"] = "parent native runner"
        del self.summary["stages"][1]["execution_evidence"]
        self.sync_native()
        self.assert_issue("no execution evidence")

    def test_dispatch_record_is_read_confined_and_escaped(self):
        payload = '<script>alert("not trusted")</script>'
        self.summary["workflow_status"] = payload
        self.summary["stages"][1]["executor"] = payload
        self.summary["artifacts"]["dispatch_record"] = "agent-dispatch.json"
        self.write("agent-dispatch.json", {"dispatch_order": [], "scope": payload})
        self.sync_native()
        self.assertEqual(self.render()["evidence_issues"], [])
        text, _ = self.inspect()
        self.assertNotIn(payload, text)
        self.assertIn("&lt;script&gt;", text)
        self.output = self.output.with_name("escaped-dispatch.html")
        self.summary["artifacts"]["dispatch_record"] = "../outside.json"
        self.sync_native()
        self.assert_issue("run-relative")

    def test_malformed_attribution_and_dispatch_shapes_are_visible(self):
        self.summary["workflow_status"] = None
        self.summary["stages"][1]["executor"] = False
        self.summary["artifacts"]["dispatch_record"] = "agent-dispatch.json"
        self.write("agent-dispatch.json", {"dispatch_order": "blocked"})
        self.sync_native()
        result = self.render()
        for phrase in ("workflow_status", "executor", "dispatch_order"):
            self.assertTrue(any(phrase in issue for issue in result["evidence_issues"]), result)


if __name__ == "__main__":
    unittest.main()
