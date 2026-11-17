import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "build_dashboard.py"
sys.path.insert(0, str(SKILL / "scripts"))

import build_dashboard as bd  # noqa: E402


def record(rid="R1", **overrides):
    base = {"id": rid, "source_url": "https://example.org/" + rid, "fields": {"a": 1}}
    base.update(overrides)
    return base


def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")


class MissingDataPolicy(unittest.TestCase):
    def test_zero_false_and_literal_strings_are_real_values(self):
        for value, shown in [(0, "0"), (0.0, "0.0"), (False, "false"), ("0", "0"), ("N/A", "N/A")]:
            self.assertEqual(bd.cell_text(value, set()), shown)

    def test_none_blank_and_empty_list_are_missing(self):
        for value in [None, "", "   ", []]:
            self.assertIsNone(bd.cell_text(value, set()))

    def test_missing_tokens_are_explicit_opt_in(self):
        self.assertEqual(bd.cell_text("NA", set()), "NA")
        self.assertIsNone(bd.cell_text("NA", {"na"}))

    def test_absent_field_is_missing_not_dropped(self):
        model = bd.normalize({"records": [record("R1", fields={"a": 1, "b": 2}), record("R2", fields={"a": 3})]})
        self.assertIsNone(model["records"][1]["cells"]["b"])
        self.assertEqual(bd.coverage(model)["b"], {"reported": 1, "missing": 1, "total": 2})

    def test_float_text_round_trips_exactly(self):
        self.assertEqual(bd.cell_text(0.1 + 0.2, set()), "0.30000000000000004")


class InputValidation(unittest.TestCase):
    def rejected(self, data):
        with self.assertRaises(bd.InputError) as ctx:
            bd.normalize(data)
        return " ".join(ctx.exception.problems)

    def test_source_link_is_required(self):
        self.assertIn("source_url", self.rejected({"records": [{"id": "R1", "fields": {"a": 1}}]}))

    def test_non_http_links_are_rejected(self):
        for url in ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "https://", "https://a b.example", "https://[::1"]:
            self.assertIn("source_url", self.rejected({"records": [record(source_url=url)]}), url)

    def test_duplicate_ids_and_nested_values_are_rejected(self):
        self.assertIn("duplicate", self.rejected({"records": [record("R1"), record("R1")]}))
        self.assertIn("flatten", self.rejected({"records": [record(fields={"a": {"x": 1}})]}))

    def test_reports_every_problem_at_once(self):
        text = self.rejected({"records": [{"id": "R1"}, {"id": "R2", "source_url": "ftp://x"}]})
        self.assertIn("R1", text)
        self.assertIn("R2", text)

    def test_nan_and_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in [("nan.json", '{"records":[{"id":"R","fields":{"a":NaN}}]}'), ("dup.json", '{"records":[],"records":[]}')]:
                path = Path(tmp) / name
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(bd.InputError):
                    bd.load_json(path)


class BuildAndVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, data, name="in.json", *extra):
        src = self.dir / name
        src.write_text(json.dumps(data), encoding="utf-8")
        out = self.dir / "out.html"
        result = run_cli("build", str(src), "--out", str(out), *extra)
        return src, out, result

    def test_samples_build_and_verify(self):
        for sample in ["sample-evidence.json", "sample-catalysis.json"]:
            out = self.dir / (sample + ".html")
            built = run_cli("build", str(SKILL / "assets" / sample), "--out", str(out), "--missing-token", "NA")
            self.assertEqual(built.returncode, 0, built.stderr)
            checked = run_cli("verify", str(SKILL / "assets" / sample), str(out), "--missing-token", "NA")
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertTrue(out.with_suffix(".provenance.json").exists())

    def test_declared_columns_and_missing_token_applied(self):
        out = self.dir / "c.html"
        sample = SKILL / "assets" / "sample-catalysis.json"
        self.assertEqual(run_cli("build", str(sample), "--out", str(out), "--missing-token", "NA").returncode, 0)
        page = out.read_text(encoding="utf-8")
        self.assertNotIn("operator_notes", page.split("<tbody>")[1])
        self.assertIn("Fields in the input but not shown: operator_notes", page)
        table = page.split("<tbody>")[1].split("</tbody>")[0]
        self.assertEqual(table.count('data-missing="true"'), 3)  # NA token, absent temperature, null solvent

    def test_hostile_text_is_escaped_and_verifies(self):
        hostile = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'
        data = {"title": hostile, "records": [record("R1", label=hostile, fields={hostile: hostile})]}
        src, out, result = self.build(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        page = out.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", page)
        self.assertEqual(run_cli("verify", str(src), str(out)).returncode, 0)

    def test_control_characters_in_text_still_verify(self):
        tricky = "line1\r\nline2\rline3\nline4\tend \u202e \U0001F9EA"
        data = {"records": [record("R\r\n1", label=tricky, fields={"a": tricky}, source_url="https://example.org/r1")]}
        src, out, result = self.build(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = run_cli("verify", str(src), str(out))
        self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_page_has_no_remote_resources_and_pins_inline_code(self):
        _, out, _ = self.build({"records": [record()]})
        page = out.read_text(encoding="utf-8")
        self.assertIn("default-src &#x27;none&#x27;", page)
        self.assertIn("sha256-", page)
        for marker in ["<link", "<iframe", "<img", "<script src", "@import", "url("]:
            self.assertNotIn(marker, page)

    def test_verify_detects_changed_value_link_and_input(self):
        src, out, _ = self.build({"records": [record("R1", fields={"a": 1}), record("R2", fields={"a": 2})]})
        original = out.read_text(encoding="utf-8")

        out.write_text(original.replace('data-missing="false">2<', 'data-missing="false">3<'), encoding="utf-8")
        tampered = run_cli("verify", str(src), str(out))
        self.assertEqual(tampered.returncode, 1)
        self.assertIn("R2.a", tampered.stdout)

        out.write_text(original.replace("https://example.org/R1", "https://example.org/other"), encoding="utf-8")
        self.assertIn("source link differs", run_cli("verify", str(src), str(out)).stdout)

        out.write_text(original, encoding="utf-8")
        src.write_text(json.dumps({"records": [record("R1", fields={"a": 9}), record("R2", fields={"a": 2})]}), encoding="utf-8")
        self.assertIn("input file changed", run_cli("verify", str(src), str(out)).stdout)

    def test_verify_detects_value_hidden_as_missing(self):
        src, out, _ = self.build({"records": [record("R1", fields={"a": 1})]})
        page = out.read_text(encoding="utf-8").replace('data-missing="false">1<', 'data-missing="true">not reported<')
        out.write_text(page, encoding="utf-8")
        self.assertEqual(run_cli("verify", str(src), str(out)).returncode, 1)

    def test_rejected_input_writes_nothing(self):
        _, out, result = self.build({"records": [{"id": "R1", "fields": {"a": 1}}]})
        self.assertEqual(result.returncode, 2)
        self.assertIn("source_url", result.stderr)
        self.assertFalse(out.exists())

    def test_malformed_url_is_rejected_without_a_traceback(self):
        _, out, result = self.build({"records": [record(source_url="https://[::1")]})
        self.assertEqual(result.returncode, 2)
        self.assertIn("source_url", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(out.exists())

    def test_verify_takes_settings_from_the_caller_not_the_page(self):
        data = {"records": [record("R1", fields={"a": "42", "b": "x"})]}

        # A real value hidden as missing: the page and its metadata agree, but the caller did not ask for the token.
        src, out, _ = self.build(data, "in.json", "--missing-token", "42")
        hidden = run_cli("verify", str(src), str(out))
        self.assertEqual(hidden.returncode, 1)
        self.assertIn("--missing-token", hidden.stdout)
        self.assertEqual(run_cli("verify", str(src), str(out), "--missing-token", "42").returncode, 0)

        # A column dropped: the page and its metadata agree, but the caller did not ask for fewer columns.
        src, out, _ = self.build(data, "in.json", "--columns", "b")
        dropped = run_cli("verify", str(src), str(out))
        self.assertEqual(dropped.returncode, 1)
        self.assertIn("--columns", dropped.stdout)
        confirmed = run_cli("verify", str(src), str(out), "--columns", "b")
        self.assertEqual(confirmed.returncode, 0, confirmed.stdout)
        self.assertIn("Input fields not shown: a", confirmed.stdout)

    def test_verify_detects_edits_outside_the_table(self):
        src, out, _ = self.build({"records": [record("R1", fields={"a": 1})]})
        original = out.read_text(encoding="utf-8")
        edits = {
            "script": original.replace("apply();\n})();", "})();"),
            "styles": original.replace("color:#1b1b1b", "color:#fff"),
            "coverage": original.replace("1 of 1 reported", "0 of 1 reported"),
            "title": original.replace("<h1>Evidence comparison</h1>", "<h1>Verified clinical results</h1>"),
            "csp": original.replace("default-src &#x27;none&#x27;", "default-src *"),
        }
        for name, page in edits.items():
            self.assertNotEqual(page, original, name)
            out.write_text(page, encoding="utf-8")
            result = run_cli("verify", str(src), str(out))
            self.assertEqual(result.returncode, 1, name)
            self.assertIn("not identical to a fresh build", result.stdout, name)

    def test_verify_reports_unreadable_pages_without_a_traceback(self):
        src, out, _ = self.build({"records": [record()]})
        good = out.read_bytes()
        cases = {
            "invalid utf-8": good[:200] + b"\xff\xfe" + good[200:],
            "invalid metadata json": good.replace(b'content="{&quot;', b'content="{oops&quot;', 1),
            "metadata not an object": re.sub(rb'(name="evidence-build" content=")[^"]*(")', rb"\g<1>[1]\g<2>", good),
            "metadata incomplete": re.sub(rb'(name="evidence-build" content=")[^"]*(")', rb"\g<1>{}\g<2>", good),
            "metadata nested too deep": re.sub(rb'(name="evidence-build" content=")[^"]*(")', rb"\g<1>" + b"[" * 100000 + rb"\g<2>", good),
            "truncated": good[: len(good) // 2],
            "unclosed cell": good.replace(b"</a></th>", b"</a>", 1),
        }
        for name, content in cases.items():
            self.assertNotEqual(content, good, name)
            out.write_bytes(content)
            result = run_cli("verify", str(src), str(out))
            self.assertEqual(result.returncode, 1, f"{name}: {result.stdout}{result.stderr}")
            self.assertIn("VERIFY FAILED", result.stdout, name)
            self.assertNotIn("Traceback", result.stderr, name)


if __name__ == "__main__":
    unittest.main()
