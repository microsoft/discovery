import copy
import contextlib
import html
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "render.py"
spec = importlib.util.spec_from_file_location("renderer", SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((HERE / "example.json").read_text(encoding="utf-8"),
                               parse_float=Decimal)

    def test_normal_values_provenance_and_structure(self):
        result = renderer.render(renderer.validate(self.data))
        for expected in ("SYNTH-DISEASE:001", "SYNTH-TARGET:001", "SYNTH-TARGET:002",
                         "SYNTH-EVIDENCE:001", "SYNTH-EVIDENCE:002", "0.62",
                         "style=\"width:62.00%\"", "<td>0", 'aria-label="Not returned or not established"', "synthetic-registry",
                         "returned, not independently verified", "Synthetic input; no provider query"):
            self.assertIn(expected, result)
        self.assertIn(">Associations</h2>", result)
        self.assertIn(">Individual evidence</h2>", result)
        self.assertIn('id="target"', result)
        self.assertIn('id="source"', result)

    def test_details_preserve_fields_and_filter_controls(self):
        self.data["evidence"][0]["uncertainty"] = "Source-specific uncertainty"
        result = renderer.render(renderer.validate(self.data))
        for expected in ('<tr class="evidence-record"', '<td><details><summary>View details</summary>',
                         'class="evidence-table"', 'id="reset"', 'id="assoc-count"',
                         'id="evidence-count"', "2 of 2 shown", "Source-specific uncertainty",
                         "Record release", "Evidence ID", "Source ID", "not independently verified",
                         "All provided records remain available."):
            self.assertIn(expected, result)
        self.assertIn("target.value = ''; source.value = ''; filter();", result)
        self.assertIn("section === 'evidence' && source.value", result)

    def test_evidence_table_order_and_zero_vs_missing(self):
        self.data["evidence"][0]["score"] = Decimal("0.000")
        self.data["evidence"][1]["score"] = None
        result = renderer.render(renderer.validate(self.data))

        class EvidenceRows(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "tr" and attrs.get("class") == "evidence-record":
                    self.current = {"target": attrs["data-target"], "text": []}
                elif tag == "span" and self.current is not None and attrs.get("class") == "missing":
                    self.current["text"].append("[missing]")

            def handle_data(self, data):
                if self.current is not None:
                    self.current["text"].append(data)

            def handle_endtag(self, tag):
                if tag == "tr" and self.current is not None:
                    self.rows.append(self.current)
                    self.current = None

        parser = EvidenceRows()
        parser.feed(result)
        self.assertEqual([r["target"] for r in parser.rows],
                         [r["target_id"] for r in self.data["evidence"]])
        self.assertIn("0.000", parser.rows[0]["text"])
        self.assertIn("[missing]", parser.rows[1]["text"])
        for row, expected in zip(parser.rows, self.data["evidence"]):
            self.assertIn(expected["evidence_id"], row["text"])

    def test_metadata_separate_exact_and_legacy_unchanged(self):
        legacy = 'Observed metadata: {"studyId":null}. Not inspected.'
        self.data["evidence"][0]["uncertainty"] = legacy
        self.data["evidence"][0]["technical_metadata"] = {
            "studyId": None, "values": [Decimal("0.000"), True, "<script>unsafe</script>"],
            "nested": {"empty": [], "number": Decimal("1.234567890123456789")},
        }
        result = renderer.render(renderer.validate(self.data))
        self.assertIn(f"<dd>{html.escape(legacy)}</dd>", result)
        self.assertIn("<dt>Limitations &amp; notes</dt>", result)
        self.assertEqual(result.count("Technical metadata</summary>"), 1)
        self.assertIn("0.000", result)
        self.assertIn("1.234567890123456789", result)
        self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;", result)
        self.assertNotIn("<script>unsafe</script>", result)
        encoded = renderer.metadata_json(self.data["evidence"][0]["technical_metadata"], "metadata")
        self.assertEqual(json.loads(encoded, parse_float=Decimal),
                         self.data["evidence"][0]["technical_metadata"])

    def test_metadata_rejects_non_object_and_non_json_values(self):
        for value in (None, [], {"bad": Decimal("NaN")}, {"bad": object()}):
            candidate = copy.deepcopy(self.data)
            candidate["evidence"][0]["technical_metadata"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                renderer.validate(candidate)

    def test_metadata_nesting_limit(self):
        value = 0
        for _ in range(63):
            value = [value]
        self.data["evidence"][0]["technical_metadata"] = {"nested": value}
        result = renderer.render(renderer.validate(self.data))
        self.assertIn("Technical metadata", result)
        self.data["evidence"][0]["technical_metadata"] = {"nested": [value]}
        with self.assertRaisesRegex(ValueError, "maximum metadata nesting depth of 64"):
            renderer.validate(self.data)

    def test_cli_rejects_deep_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "deep.json"
            output_path = Path(folder) / "report.html"
            data = json.loads((HERE / "example.json").read_text(encoding="utf-8"))
            data["evidence"][0]["technical_metadata"] = {"nested": "DEEP_VALUE"}
            document = json.dumps(data)
            for depth in (64, 2000):
                input_path.write_text(document.replace('"DEEP_VALUE"', "[" * depth + "0" + "]" * depth),
                                      encoding="utf-8")
                result = subprocess.run([sys.executable, str(SCRIPT), "--input", str(input_path),
                                         "--output", str(output_path)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Error:", result.stderr)
                self.assertTrue("maximum metadata nesting depth of 64" in result.stderr or
                                "input nesting exceeds the Python recursion limit" in result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output_path.exists())

    def test_cli_reports_decoder_recursion_error(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "deep.json"
            output_path = Path(folder) / "report.html"
            input_path.write_text("{}", encoding="utf-8")
            stderr = io.StringIO()
            with mock.patch.object(sys, "argv", [str(SCRIPT), "--input", str(input_path),
                                                "--output", str(output_path)]), \
                 mock.patch.object(renderer.json, "loads", side_effect=RecursionError), \
                 contextlib.redirect_stderr(stderr):
                self.assertEqual(renderer.main(), 1)
            self.assertIn("Error: input nesting exceeds the Python recursion limit", stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_query_is_collapsed_and_preserved_with_loaded_counts(self):
        query = '\n  query Example($value: String!) {\r\n    test(value: "<script>&")\n  }\n' + "page=0; " * 1000
        self.data["provenance"]["query"] = query
        result = renderer.render(renderer.validate(self.data))
        self.assertIn('<details class="query-details"><summary>Query details &amp; reproducibility</summary>', result)
        self.assertIn('Loaded in this report: 2 association records and 2 evidence records; these are not platform totals.', result)

        class QueryText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.inside = False
                self.parts = []

            def handle_starttag(self, tag, attrs):
                if tag == "div" and dict(attrs).get("class") == "query-text":
                    self.inside = True

            def handle_data(self, data):
                if self.inside:
                    self.parts.append(data)

            def handle_endtag(self, tag):
                if tag == "div" and self.inside:
                    self.inside = False

        parser = QueryText()
        parser.feed(result)
        self.assertEqual("".join(parser.parts), query)
        self.assertNotIn('<script>&', result)
        self.data["associations"] = []
        self.data["evidence"] = []
        empty = renderer.render(renderer.validate(self.data))
        self.assertIn('Loaded in this report: 0 association records and 0 evidence records;', empty)

    def test_empty_and_independent_disease(self):
        self.data["disease"] = {"id": "OTHER:002", "label": "Independent synthetic disease"}
        self.data["associations"] = []
        self.data["evidence"] = []
        result = renderer.render(renderer.validate(self.data))
        self.assertIn("Independent synthetic disease", result)
        self.assertIn("No evidence records match", result)
        self.assertIn('id="evidence-empty" class="empty">', result)
        self.assertIn('id="assoc-count" aria-live="polite">0 of 0 shown', result)
        self.assertNotIn("SYNTH-TARGET:001", result)

    def test_html_escaping_and_safe_links(self):
        self.data["disease"]["label"] = '<script>alert("x")</script>'
        self.data["associations"][0]["target_label"] = 'x" onmouseover="evil'
        result = renderer.render(renderer.validate(self.data))
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", result)
        self.assertNotIn('<script>alert("x")</script>', result)
        self.assertIn('x&quot; onmouseover=&quot;evil', result)
        self.assertIn('rel="noopener noreferrer"', result)
        for url in ("javascript:alert(1)", "https://user:pass@example.org", "https://example.org/\nfoo",
                    "https://example.org\\malicious",
                    "https://example.org:invalid"):
            candidate = copy.deepcopy(self.data)
            candidate["evidence"][0]["links"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                renderer.validate(candidate)

    def test_constructed_link_and_out_of_scale_score(self):
        self.data["evidence"][0]["links"][0]["origin"] = "constructed"
        self.data["associations"][0]["score"] = Decimal("1.234567890123456789")
        result = renderer.render(renderer.validate(self.data))
        self.assertIn("constructed, not independently verified", result)
        self.assertIn("1.234567890123456789", result)
        self.assertNotIn("123.4567890123456789%", result)

    def test_invalid_shapes_fail_explicitly(self):
        for mutate in (
            lambda d: d["evidence"][0].update(target_id="missing"),
            lambda d: d["associations"][0].update(score="0"),
            lambda d: d["associations"].append(copy.deepcopy(d["associations"][0])),
            lambda d: d["evidence"][0]["links"][0].update(origin="guessed"),
            lambda d: d["provenance"].pop("scope"),
        ):
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.assertRaises(ValueError):
                renderer.validate(data)

    def test_cli_writes_and_refuses_overwrite_or_invalid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "report.html"
            command = [sys.executable, str(SCRIPT), "--input", str(HERE / "example.json"), "--output", str(dest)]
            good = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn("SYNTH-EVIDENCE:001", dest.read_text(encoding="utf-8"))
            repeat = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeat.returncode, 0)
            self.assertIn("Error:", repeat.stderr)
            invalid = Path(folder) / "invalid.json"
            invalid.write_text('{"score": NaN}', encoding="utf-8")
            failure = subprocess.run([sys.executable, str(SCRIPT), "--input", str(invalid),
                                      "--output", str(Path(folder) / "bad.html")], capture_output=True, text=True)
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("Error:", failure.stderr)


if __name__ == "__main__":
    unittest.main()
