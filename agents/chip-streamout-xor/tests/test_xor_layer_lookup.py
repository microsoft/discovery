import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / (
    "streamout-xor") / "streamout_xor_utils.py"
SPEC = importlib.util.spec_from_file_location("xor_utils", SOURCE)
UTILS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UTILS)


class LayerLookupScriptTest(unittest.TestCase):
    def test_empty_lyt_uses_real_companion_map_and_pin_purposes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lyt, mapping = root / "node.lyt", root / "node.map"
            lyt.write_text("<technology><reader-options><lefdef><layer-map>"
                           "layer_map()</layer-map></lefdef></reader-options></technology>")
            mapping.write_text("li1 NET,SPNET,VIA 67 20\nli1 LEFPIN,PIN 67 16\n"
                               "DIEAREA ALL 235 4\n")
            self.assertEqual(str(mapping), UTILS._companion_lefdef_map(str(lyt)))
            self.assertEqual([{"layer": "li1", "drawing": [67, 20], "port": [67, 16]}],
                             UTILS._map_port_roles(str(mapping)))
            lyt.write_text("<technology><reader-options><lefdef><layer-map>"
                           "layer_map('li1 : 67/20')</layer-map></lefdef></reader-options></technology>")
            self.assertIsNone(UTILS._companion_lefdef_map(str(lyt)))

    def test_bound_magic_minimum_version_fails_before_streamout(self):
        with patch("builtins.open", mock_open(read_data="requires magic-8.3.693\n")), \
                patch.object(UTILS.os.path, "isfile", return_value=True), \
                patch.object(UTILS.shutil, "which", return_value="magic"), \
                patch.object(UTILS, "_version", return_value="8.3.503"), \
                patch.object(UTILS, "_run") as run:
            result, error = UTILS._magic_streamout(
                "route.def", "TOP", "tech.lef", ["cells.lef"], ["actual.gds"],
                None, "magic.tech")
        self.assertIsNone(result)
        self.assertIn("requires magic-8.3.693", error)
        self.assertIn("8.3.503", error)
        run.assert_not_called()

    def test_zero_byte_magic_output_is_not_accepted_as_gds(self):
        with patch("builtins.open", mock_open(read_data=b"")), \
                patch.object(UTILS.os.path, "isfile", return_value=True), \
                patch.object(UTILS.shutil, "which", return_value="magic"), \
                patch.object(UTILS.shutil, "copy2"), \
                patch.object(UTILS, "_magic_grid_refinement", return_value=None), \
                patch.object(UTILS, "_run", return_value=(SimpleNamespace(returncode=0), "empty GDS")):
            result, error = UTILS._magic_streamout(
                "route.def", "TOP", "tech.lef", ["cells.lef"], ["actual.gds"],
                None, None)
        self.assertIsNone(result)
        self.assertIn("empty GDS", error)

    def test_grid_refinement_requires_explicit_source_precision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lef, tech = root / "tech.lef", root / "magic.tech"
            lef.write_text("MANUFACTURINGGRID 0.0050 ;\n")
            tech.write_text("scalefactor 25 nanometers\n")
            result = UTILS._magic_grid_refinement(str(lef), str(tech))
            self.assertEqual([1, 5], result["scalegrid"])
            lef.write_text("LAYER metal1\n")
            self.assertIsNone(UTILS._magic_grid_refinement(str(lef), str(tech)))

    def test_port_map_uses_declared_purposes_and_preserves_vendor_views(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            magic, lyt = root / "magic.tech", root / "tech.lyt"
            magic.write_text(
                "cifoutput\nstyle gdsii\nlayer METAL1 *m1,obsm1\ncalma 11 0\n"
                "layer M1_PORT\nlabels *m1,obsm1 port\ncalma 11 1\nend\n")
            lyt.write_text(
                "<technology><reader-options><lefdef><layer-map>"
                "layer_map('metal1 : 11/0';'metal1.PIN : 11/0';"
                "'metal1.LABEL : 11/0';'via1 : 12/0')"
                "</layer-map></lefdef></reader-options></technology>")
            before = lyt.read_bytes(), magic.read_bytes()
            with patch.object(UTILS, "WORK", str(root)):
                path, roles = UTILS._align_default_port_map(str(lyt), str(magic))
            self.assertEqual([{"layer": "metal1", "drawing": [11, 0],
                               "port": [11, 1]}], roles)
            text = Path(path).read_text()
            self.assertIn("'metal1 : 11/0'", text)
            self.assertIn("'metal1.PIN : 11/1'", text)
            self.assertIn("'metal1.LABEL : 11/1'", text)
            self.assertIn("'via1 : 12/0'", text)
            self.assertEqual(before, (lyt.read_bytes(), magic.read_bytes()))

    def test_streamout_overlays_only_actual_top_pin_shapes(self):
        scripts = []

        def capture(body, tag):
            compile(body, "native_streamout.py", "exec")
            scripts.append(body)
            return SimpleNamespace(returncode=1), "unit-test: not an engine run"

        roles = [{"layer": "metal1", "drawing": [11, 0], "port": [11, 1]}]
        with patch.object(UTILS, "_companion_lefdef_map", return_value=None), patch.object(UTILS, "_align_default_port_map",
                          return_value=("aligned.lyt", roles)), patch.object(
                UTILS, "_klayout_script", side_effect=capture):
            result, error = UTILS._klayout_streamout(
                "route.def", "TOP", "tech.lef", ["cells.lef"], ["actual.gds"],
                "technology.lyt", magic_tech="magic.tech")
        self.assertIsNone(result)
        self.assertIn("not an engine run", error)
        self.assertIn("list(tc.shapes(pin).each())", scripts[0])
        self.assertIn('tc.shapes(drawing).insert(shape)', scripts[0])
        self.assertIn("if not shape.is_text():", scripts[0])
        self.assertNotIn("pya.Box(", scripts[0])

    def test_magic_preserves_real_gds_by_default_and_keeps_editable_control_separate(self):
        for preserve in (True, False):
            with self.subTest(preserve=preserve):
                writer = mock_open()
                with patch("builtins.open", writer), patch.object(
                        UTILS.shutil, "which", return_value="not-an-engine"), patch.object(
                        UTILS.shutil, "copy2"), patch.object(
                        UTILS, "_run", return_value=(SimpleNamespace(returncode=1), "not an engine")):
                    result, error = UTILS._magic_streamout(
                        "route.def", "TOP", "tech.lef", ["cells.lef"], ["actual.gds"],
                        None, "magic.tech", preserve_cell_gds=preserve)
                self.assertIsNone(result)
                self.assertIn("not an engine", error)
                script = writer().write.call_args.args[0]
                setting = "gds readonly " + ("true" if preserve else "false")
                self.assertLess(script.index(setting), script.index("gds read {actual.gds}"))
                self.assertLess(script.index("gds read {actual.gds}"), script.index("def read"))
                self.assertIn("_editable_control" if not preserve else "TOP_magic.gds", script)

    def test_native_script_preserves_indexes_and_rejects_empty_comparison(self):
        scripts = []

        def capture(body, tag):
            compile(body, "native_xor.py", "exec")
            scripts.append(body)
            return SimpleNamespace(returncode=1), "unit-test: not an engine run"

        with patch.object(UTILS, "_klayout_script", side_effect=capture), patch.object(
                UTILS.shutil, "which", return_value="unit-test-not-an-engine"):
            report, error = UTILS._xor(str(SOURCE), str(SOURCE), "TOP")
        self.assertIsNone(report)
        self.assertIn("not an engine run", error)
        self.assertEqual(1, len(scripts))
        self.assertIn('info.name if info.layer < 0 else ""', scripts[0])
        self.assertIn("ia = indexes[0].get(key)", scripts[0])
        self.assertIn("ib = indexes[1].get(key)", scripts[0])
        self.assertIn("if not any(input_polygons):", scripts[0])
        self.assertIn("with_geometry = False", scripts[0])
        self.assertIn('"truncated": region.count() > len(values)', scripts[0])
        self.assertNotIn("find_layer(info.layer, info.datatype)", scripts[0])


if __name__ == "__main__":
    unittest.main()
