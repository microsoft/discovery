from pathlib import Path
import unittest


class ServicesJsonContractTest(unittest.TestCase):
    def test_instruction_requires_one_unmodified_json_object(self):
        source = Path(__file__).resolve().parents[1] / "services-instructions.md"
        text = source.read_text(encoding="utf-8")
        for requirement in (
            "exactly one JSON object and nothing else",
            "Do not append user preferences",
            "instruction markers, prose, or code fences",
            "/input/params.json",
        ):
            self.assertIn(requirement, text)


if __name__ == "__main__":
    unittest.main()
