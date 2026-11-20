import unittest
from pathlib import Path


class NamedPdkMountContractTests(unittest.TestCase):
    def test_owned_services_instructions_preserve_returned_context_uri(self):
        packages = Path(__file__).resolve().parents[2]
        for agent in ("chip-pdk-binding", "chip-dfm-litho-yield", "chip-drc",
                      "chip-lvs", "chip-library-development"):
            with self.subTest(agent=agent):
                text = (packages / agent / "services-instructions.md").read_text()
                self.assertIn("CreateResponse.storageAssets", text)
                self.assertIn("Call GetResourceContext once", text)
                self.assertIn("exact returned PDK directory URI", text)
                self.assertIn("paths/inputs/", text)
                self.assertIn("must not be copied into named inputMounts", text)
                self.assertIn("limited to 1 CPU and 2Gi RAM", text)
                self.assertIn("at most one native job active", text)
                self.assertNotIn("limited to 2 CPUs and 4Gi RAM", text)
                self.assertIn("do not claim native execution", text)

    def test_library_corner_mapping_distinguishes_metadata_from_execution(self):
        packages = Path(__file__).resolve().parents[2]
        text = (packages / "chip-library-development" / "services-instructions.md").read_text()
        self.assertIn("omit top-level corners", text)
        self.assertIn("objects with name and explicit spice_models, temp_c or vdd", text)
        self.assertIn("never copy bare binding labels", text)


if __name__ == "__main__":
    unittest.main()
